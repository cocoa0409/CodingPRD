# Heat Treating Service API — Product Requirements Document

## 1. Introduction

Commercial heat treating is a trust business. Customers ship irreplaceable lots of machined parts to a shop that must transform their metallurgy inside a furnace nobody can see into, then prove afterward that every minute of the cycle stayed inside the qualified envelope. This document specifies the Heat Treating Service API, the system of record for that proof. It governs the full commercial workflow: customer accounts and credit standing, process recipes keyed by alloy and specification, furnace registration and AMS2750 pyrometry, work-order intake with rush-lane turnaround guarantees, load building and furnace scheduling, load-thermocouple traceability, hardness inspection, disposition of nonconforming lots, customer material liability, and Nadcap audit evidence packaging.

Two design commitments shape everything that follows. First, qualification is a posture, not a sticker: a furnace's right to accept work is continuously derived from the currency of its temperature-uniformity surveys and instrument calibrations, and loads still being built are automatically parked whenever that posture lapses. Second, money follows the physics: rush surcharges are quoted at intake but settled against the measured turnaround, energy surcharges are settled per order when a load completes, and liability for scrapped material is computed from the customer's elected coverage tier — each with pinned rounding rules so that every cent is auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and boilerplate that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The API recognizes exactly seven roles: `CustomerServiceRep` (front office: customer accounts, work-order intake, ship and cancel, claim settlement), `ShopScheduler` (furnace registration, load building, assignments, release), `FurnaceOperator` (run execution and thermocouple readings), `CalibrationTech` (pyrometry surveys and instrument calibrations), `QualityEngineer` (recipes, inspection tests, disposition decisions, audit package compilation), `NadcapAuditor` (issues audit packages; read-only otherwise), and `Customer` (the heat treater's customer; reads own resources and accepts liability claims). A request missing either header, or carrying an empty or whitespace-only value for one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A role attempting an operation reserved for another role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403); an `X-User-Role` value outside the seven recognized roles is likewise rejected with `ERR_INSUFFICIENT_PERMISSIONS` on every endpoint.

Identity semantics differ by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting CustomerAccount; ownership checks on any resource that references a CustomerAccount compare the resource's `customer_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). This scoping applies when a `Customer` retrieves a single work order, retrieves a single liability claim, or accepts a liability claim. For the remaining six roles — `CustomerServiceRep`, `ShopScheduler`, `FurnaceOperator`, `CalibrationTech`, `QualityEngineer`, and `NadcapAuditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `recorded_by_user_id` on an InspectionTest or as `decided_by_user_id` on a DispositionCase) but does not compare it to any entity's `id`.

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

Requests to an undefined route, or to an unsupported method on a defined route, are rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope.

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — a value outside that range is clamped to the nearest bound, and a non-integer value falls back to the default. `offset` specifies how many items to skip and defaults to 0; a negative value is clamped to 0 and a non-integer value falls back to the default. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Most list endpoints accept optional equality filters matching fields of the listed resource: work orders filter by `customer_id`, `recipe_id`, `processing_status`, or `service_lane`; pyrometry records by `furnace_id` or `record_type`; inspection tests by `work_order_id` or `result`; disposition cases by `work_order_id`, `inspection_test_id`, or `status`; liability claims by `customer_id`, `work_order_id`, or `status`; load batches by `furnace_id`, `recipe_id`, or `status`; load assignments by `load_batch_id`, `work_order_id`, or `status`; thermocouple readings by `load_batch_id`; audit packages by `furnace_id` or `status`.

### 2.4. Common Resource Properties

Most resources carry a standard system-managed quartet of fields. `id` is a server-minted unique identifier formatted as a UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. `updated_at` follows the same format, equals `created_at` at creation, and refreshes on every mutation. `version` is a system-managed integer that starts at 1 at creation and increments on every mutation. System-driven cascades count as mutations: when an assignment change ripples into a load's booked weight, the load's `updated_at` refreshes and its `version` increments alongside.

Three resources are append-only evidence records and carry a reduced property set: a PyrometryRecord, a LoadThermocoupleReading, and an InspectionTest each expose `id` and `created_at` only — both `updated_at` and `version` are absent, and no endpoint modifies or deletes them.

### 2.5. The Logical Clock

Every timestamp described in this document as "the logical clock" — lot receipt, assignment, run start, run completion, shipment, package issuance — reads a server-maintained logical clock, never wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it holds that value until an operator moves it. An operator of any role may advance the clock through the test-driving clock capability, supplying the target instant as `to_iso8601` in ISO 8601 form; the endpoint accepts any target instant, forward or backward. Furnace qualification posture (§2.7) is always evaluated against this clock, so advancing time can by itself push a furnace out of compliance and park its loads. Setting the clock does not by itself recompute any posture: the new instant takes effect at the next recomputation point listed in §2.7 (a furnace read, a pyrometry-record creation, or a release/start-run check).

### 2.6. Precision, Rounding, and Measurement Conventions

Money is integer cents everywhere: quoted and final surcharges, energy surcharges, liability payouts, and exposure totals are whole-cent integers, and every rounding step called out in this document uses the round-half-up method. Weights are tracked in pounds with up to three decimal places, which applies to both an order's `received_weight_lb` and a load's `total_weight_lb`. Averaged hardness is reported to one decimal place, rounded half-up. Furnace and thermocouple temperatures are integer degrees Fahrenheit. Datetime comparisons — turnaround promises, pyrometry validity windows — are evaluated on the exact parsed instants, with no rounding or truncation (inputs are conventionally supplied at whole-second precision).

### 2.7. Furnace Qualification Posture

A furnace's `qualification_status` is not a stored state; it is a derived posture recomputed from that furnace's pyrometry history against the logical clock on every furnace read, on every pyrometry-record creation, and at every load release or start-run check. The four postures, in pinned precedence order from most to least severe, are `UNQUALIFIED`, `SURVEY_OVERDUE`, `CALIBRATION_OVERDUE`, and `QUALIFIED`; the full derivation is specified in §3.3. Posture drives floor capacity: whenever a furnace's posture leaves `QUALIFIED`, every LoadBatch on that furnace currently in `BUILDING` is moved to `HOLD`, and when the posture returns to `QUALIFIED`, each such `HOLD` load moves back to `BUILDING`. Only a `QUALIFIED` furnace may have loads released or started.

### 2.8. Validation Pipeline Order

When several checks could reject the same request, the server evaluates them in a fixed pipeline and surfaces the first failure rather than an arbitrary one. The order is: (1) user-context headers present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role permitted for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`); (3) customer-ownership scoping (`ERR_OWNERSHIP_MISMATCH`); (4) resource existence — path identifiers validated left to right, then request-body foreign keys (the `ERR_*_NOT_FOUND` family); (5) state-machine preconditions and optimistic-concurrency checks (the state errors such as `ERR_LOAD_NOT_BUILDING`, plus `ERR_STALE_VERSION`); (6) business safety gates — furnace qualification, furnace-class rank, quench-media compatibility, segregation of duties; (7) recipe referential consistency — approval state, recipe match between order and load, alloy/spec uniqueness; (8) temporal rules — rush guarantee window, pyrometry validity containment, schedule overlap and purge gap; (9) constraint checks — load weight capacity, non-empty load, re-treat ceiling, required fields and enum validity; (10) fiscal standing (`ERR_CUSTOMER_CREDIT_HOLD`). A work order submitted with a malformed body against a credit-held customer therefore fails with `ERR_INVALID_REQUEST`, never reaching the credit check.

### 2.9. Optimistic Concurrency Control on Load Builds

Exactly two write operations are concurrency-guarded, both targeting a LoadBatch: assigning a work order to a load, and removing an assignment from a load. Each requires the non-optional request field `expected_load_batch_version`, carrying the load's `version` as the client last observed it; omitting the field is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and the staleness comparison applies when the supplied value is an integer. If that value does not equal the LoadBatch's current `version` — because another write (an assign, an unassign, or a cascade such as an abort or an order cancellation) has advanced it since the client's read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from rebuilding a load it has not observed. No other endpoint accepts a version field.

### 2.10. Nested Resource Retrieval and Foreign-Key Existence

Requests that address nested resources validate path identifiers left to right and stop at the first miss. Removing assignment `{assignmentId}` from load `{loadBatchId}` first confirms the load exists (`ERR_LOAD_BATCH_NOT_FOUND`), then confirms the assignment exists on that load (`ERR_ASSIGNMENT_NOT_FOUND`). Foreign keys supplied in request bodies must reference existing resources, each with its own identifier: `customer_id` surfaces `ERR_CUSTOMER_NOT_FOUND`, `recipe_id` surfaces `ERR_RECIPE_NOT_FOUND`, `furnace_id` surfaces `ERR_FURNACE_NOT_FOUND`, `work_order_id` surfaces `ERR_WORK_ORDER_NOT_FOUND`, and `load_batch_id` surfaces `ERR_LOAD_BATCH_NOT_FOUND`. Reads of a single nonexistent resource fail with that resource's specific identifier — `ERR_CUSTOMER_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`, `ERR_FURNACE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PYROMETRY_RECORD_NOT_FOUND`, `ERR_THERMOCOUPLE_READING_NOT_FOUND`, `ERR_INSPECTION_TEST_NOT_FOUND`, `ERR_DISPOSITION_CASE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_AUDIT_PACKAGE_NOT_FOUND` as applicable.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts, Liability Tiers, and Credit Standing

A `CustomerServiceRep` opens a CustomerAccount with the company `name` and two optional flags. `liability_tier` selects the coverage variant used if material is ever scrapped: `STANDARD` (the default when omitted) caps compensation at a multiple of the processing charge, while `EXTENDED` values material by weight — the mechanics are defined in §3.8. `credit_hold` defaults to `false`; while it is `true`, work-order intake for the account is rejected with `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402). Each account also carries `outstanding_liability_exposure_cents`, a computed figure that starts at 0: the sum of `payout_cents` over that customer's claims in `PENDING` or `ACCEPTED` status, recomputed whenever a claim is created, paid, or rejected.

### 3.2. Process Recipes and Furnace Registration

Recipes are authored by a `QualityEngineer` and describe one qualified thermal cycle. `alloy_code` and `spec_code` identify the alloy/specification pairing (for example, 4140 under AMS2759); the pair must be unique across all recipes, and a duplicate is rejected with `ERR_DUPLICATE_RECIPE` (HTTP 409). `soak_temp_f` is the soak setpoint, with an allowed plus-or-minus band of `soak_tolerance_f` governing load thermocouples, and `min_soak_minutes` is the minimum time at temperature. `quench_media` is one of `OIL`, `WATER`, `POLYMER`, `AIR`, or `GAS`. `required_furnace_class` names the minimum AMS2750 furnace class the cycle demands — `CLASS_1`, `CLASS_2`, `CLASS_3`, or `CLASS_5`, with `CLASS_1` the strictest. `max_retreats` caps how many re-treat cycles a lot run under this recipe may undergo. `fixture_distortion_allowance_in` is the maximum acceptable part distortion in inches given the recipe's fixturing, and `hardness_min_hrc` / `hardness_max_hrc` are whole-number HRC values bounding the acceptable average hardness, inclusive on both ends. A new recipe starts in `DRAFT`. Approval by a `QualityEngineer` moves it to `APPROVED`, which is terminal; attempting to approve a recipe that is no longer in `DRAFT` is rejected with `ERR_INVALID_REQUEST`. Loads may only be built against `APPROVED` recipes (§3.5).

A `ShopScheduler` registers each Furnace with a unique `furnace_code` — a duplicate `furnace_code` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — its AMS2750 `furnace_class`, a `max_load_weight_lb` charge-weight capacity, and the `quench_media_supported` list naming every quench medium the furnace can run. Furnace classes are ranked `CLASS_1` as 1, `CLASS_2` as 2, `CLASS_3` as 3, and `CLASS_5` as 5; a furnace may serve a recipe only when the furnace's class rank is less than or equal to the rank of the recipe's `required_furnace_class` — a `CLASS_1` furnace can run a `CLASS_3` recipe, but a `CLASS_3` furnace cannot run a `CLASS_1` recipe. A freshly registered furnace has no pyrometry history, so its `qualification_status` computes to `UNQUALIFIED` and both `current_tus_due_at` and `current_calibration_due_at` are null.

### 3.3. Pyrometry Records and the Qualification Derivation

Pyrometry evidence is recorded by a `CalibrationTech` as append-only PyrometryRecords, each carrying `furnace_id`, `record_type` (`TUS` for a temperature-uniformity survey or `INSTRUMENT_CALIBRATION`), `performed_at`, and `result` (`PASS` or `FAIL`). The `instrument_id` field identifies the calibrated instrument: it is required on calibration records and optional on surveys (reading back as null when omitted), and omitting a required input is rejected with `ERR_INVALID_REQUEST`. Each record's `next_due_at` is computed as `performed_at` plus an interval in whole days. For surveys the interval depends on the furnace's class — 30 days for `CLASS_1`, 60 days for `CLASS_2`, 90 days for `CLASS_3`, and 180 days for `CLASS_5` — while instrument calibrations always run on a 90-day interval regardless of class.

From these records the posture derivation of §2.7 proceeds as follows. For each record type, the "latest" record is the one with the greatest `performed_at`, ties broken by the greatest `created_at`. If the latest survey is missing or its `result` is `FAIL`, or the latest calibration is missing or `FAIL`, the furnace is `UNQUALIFIED`. Otherwise, if the latest survey's `next_due_at` is earlier than the logical clock, the posture is `SURVEY_OVERDUE`; otherwise, if the latest calibration's `next_due_at` is earlier than the clock, the posture is `CALIBRATION_OVERDUE`; otherwise the furnace is `QUALIFIED`. Precedence is pinned top to bottom, so when survey and calibration are both overdue the furnace reports `SURVEY_OVERDUE`. The convenience fields `current_tus_due_at` and `current_calibration_due_at` expose the `next_due_at` of the latest `PASS` survey and the latest `PASS` calibration respectively, each null when no passing record of that type exists.

Recording pyrometry is how a furnace earns work eligibility — and how it loses it. The moment a posture recomputation moves a furnace out of `QUALIFIED`, whether from a failing record or simply from the logical clock passing a due date, every LoadBatch sitting in `BUILDING` on that furnace drops to `HOLD`; when the posture returns to `QUALIFIED`, each such `HOLD` load resumes `BUILDING`. Loads already released or running are not retroactively parked — the posture gate instead bites at release and start-run time (§3.5, §3.6).

### 3.4. Work Order Intake and the Rush Lane

Intake is a `CustomerServiceRep` function. Receiving a lot requires the `customer_id` of the material owner and the `recipe_id` of the selected cycle, the `part_quantity` piece count, the lot's `received_weight_lb` in pounds, the customer's `declared_value_cents` (which later caps any liability payout), and the quoted `processing_charge_cents`. Two optional fields control the service lane: `service_lane` defaults to `STANDARD` but may be `RUSH`, and `guaranteed_turnaround_hours` carries the promised turnaround in whole hours. A `RUSH` order submitted without `guaranteed_turnaround_hours` is rejected with `ERR_INVALID_REQUEST`; a value below 4 hours is rejected with `ERR_INVALID_GUARANTEE_WINDOW` (HTTP 422). Recall from §2.8 that these field-level checks fire before the fiscal gate — a credit-held customer's malformed intake fails format validation first, while a well-formed one fails with `ERR_CUSTOMER_CREDIT_HOLD`.

Creation stamps the order with the logical clock as `received_at`, sets `processing_status` to `RECEIVED` and `quality_status` to `PENDING_TEST`, and initializes `retreat_count` to 0. For `RUSH` lots, `promised_due_at` is `received_at` plus the guaranteed hours; for `STANDARD` lots it stays null, and a `guaranteed_turnaround_hours` value supplied on a `STANDARD` order is ignored — the stored field reads null. `shipped_at`, `rush_surcharge_final_cents`, and `energy_surcharge_cents` are all null at intake — they are settled later — and `turnaround_breached` reads `false` until the lot actually ships.

Rush pricing is quoted provisionally at intake into `rush_surcharge_quoted_cents`. The quote starts from a base of 15,000 cents plus 20 percent of the lot's `processing_charge_cents`, the percentage portion rounded half-up to whole cents before being added to the base. When the promised turnaround is 24 hours or less, this combined base is then multiplied by 1.5 and again rounded half-up to whole cents. The quoted surcharge is that figure clamped to a floor of 25,000 cents and a ceiling of 200,000 cents. `STANDARD`-lane orders quote 0. Final settlement happens at ship time (§3.8), where identical quoted surcharges settle to different totals depending on whether the turnaround guarantee was met.

### 3.5. Load Building, Assignment, and the Release Gate

Load building is the `ShopScheduler`'s craft. A new LoadBatch names its `furnace_id` and `recipe_id` and a planned window from `scheduled_start_at` to `scheduled_end_at`; a start that is not strictly earlier than the end is rejected with `ERR_INVALID_REQUEST`. The batch is born in `BUILDING` with `total_weight_lb` at 0, `out_of_spec` false, `total_energy_surcharge_cents` null, and `started_at` / `completed_at` null. Creation already enforces three compatibility gates: the recipe must be `APPROVED` (`ERR_RECIPE_NOT_APPROVED`, HTTP 409); the furnace's class rank must be less than or equal to the rank of the recipe's `required_furnace_class` (`ERR_RECIPE_CLASS_MISMATCH`, HTTP 422); and the furnace's `quench_media_supported` must include the recipe's `quench_media` (`ERR_QUENCH_MEDIA_INCOMPATIBLE`, HTTP 422). Creation also checks the furnace's committed schedule — meaning all of its loads in `RELEASED`, `RUNNING`, or `COMPLETED`: a window overlapping any of them is rejected with `ERR_FURNACE_SCHEDULE_OVERLAP` (HTTP 409) — windows that merely abut, one ending exactly when the other begins, are not overlapping and are permitted — and when an adjacent load uses a different quench medium with less than 60 minutes between the earlier run's end and the later run's start, the request fails with `ERR_QUENCH_PURGE_GAP_VIOLATION` (HTTP 409). Adjacent loads sharing the same quench medium need no purge gap, though they still may not overlap.

Work orders join a load through LoadAssignments. Assigning requires the `work_order_id` and, per §2.9, the non-optional `expected_load_batch_version`; a stale version is rejected with `ERR_STALE_VERSION`. The load must be in `BUILDING` or `HOLD` — assignment writes against a load in any other status fail with `ERR_LOAD_NOT_BUILDING`. The order's `processing_status` must be `RECEIVED` or `AWAITING_RETREAT` (`ERR_WORK_ORDER_NOT_ASSIGNABLE`, HTTP 409), and the order's `recipe_id` must equal the load's `recipe_id` (`ERR_RECIPE_MISMATCH`, HTTP 422). Capacity is enforced by weight: a load's `total_weight_lb` is the sum of `received_weight_lb` over its `ACTIVE` assignments, and an assignment that would push that total strictly above the furnace's `max_load_weight_lb` is rejected with `ERR_LOAD_WEIGHT_EXCEEDED` — a load landing exactly at the maximum is permitted. A successful assignment is created `ACTIVE` with `assigned_at` stamped from the logical clock; the order advances from `RECEIVED` (or `AWAITING_RETREAT`) to `SCHEDULED`; the load's `total_weight_lb` is recomputed and its `version` increments by one.

Removal mirrors assignment. Unassigning is likewise a `ShopScheduler` action, likewise guarded by `expected_load_batch_version`, and likewise requires the load to be in `BUILDING` or `HOLD` (`ERR_LOAD_NOT_BUILDING` otherwise); unassigning an assignment that is no longer `ACTIVE` is rejected with `ERR_INVALID_REQUEST`. It moves the assignment from `ACTIVE` to `REMOVED`, returns the order to `RECEIVED` when its `retreat_count` is 0 or to `AWAITING_RETREAT` when the lot has already been re-treated at least once, recomputes the load's `total_weight_lb`, and bumps the load's `version`.

Release is the full compliance gate, and its checks fire in the pipeline order of §2.8. The load must be in `BUILDING` (`ERR_LOAD_NOT_BUILDING`, HTTP 409). The furnace's `qualification_status` must be `QUALIFIED` (`ERR_FURNACE_NOT_QUALIFIED`, HTTP 422) — posture is recomputed against the logical clock at this moment, so a survey that fell overdue since the last read blocks the release. The recipe must still be `APPROVED` (`ERR_RECIPE_NOT_APPROVED`). The entire scheduled window must be contained in the pyrometry validity intervals: `scheduled_start_at` must fall on or after the most recent passing survey's `performed_at` and `scheduled_end_at` must fall on or before its `next_due_at`, and the same containment must hold against the most recent passing calibration's interval — otherwise the release fails with `ERR_PYROMETRY_WINDOW_VIOLATION` (HTTP 422). The overlap and purge-gap rules are then re-evaluated against the furnace's `RELEASED`, `RUNNING`, and `COMPLETED` loads (`ERR_FURNACE_SCHEDULE_OVERLAP`, `ERR_QUENCH_PURGE_GAP_VIOLATION`). Finally, releasing an empty load — one with no `ACTIVE` assignment — is rejected with `ERR_EMPTY_LOAD` (HTTP 422). A release that clears every gate moves the batch from `BUILDING` to `RELEASED`.

### 3.6. Running the Load: Traceability, Completion, and Abort

Once a load is `RELEASED`, a `FurnaceOperator` starts the run. Start-run requires the `RELEASED` status (`ERR_LOAD_NOT_RELEASED`, HTTP 409) and re-checks that the furnace is still `QUALIFIED` (`ERR_FURNACE_NOT_QUALIFIED`). The load moves to `RUNNING`, `started_at` is stamped from the logical clock, and every `ACTIVE` assignment's work order advances from `SCHEDULED` to `IN_PROCESS`.

While the load runs, the operator appends LoadThermocoupleReadings — the batch-traceability record — each with the `load_batch_id`, a `channel` label such as LOAD_TC_1, the `recorded_at` instant, and the measured `temp_f`. Readings are accepted only while the load is `RUNNING`; appending against a load in any other status fails with `ERR_LOAD_NOT_RUNNING`. Like pyrometry records, readings are append-only and immutable.

Completing the run requires `RUNNING` (`ERR_LOAD_NOT_RUNNING`). The load becomes `COMPLETED` with `completed_at` stamped from the logical clock, and completion triggers two settlements. First, thermocouple excursion assessment: `out_of_spec` is set to `true` if and only if at least one of the load's readings deviates from the recipe's `soak_temp_f` by more than `soak_tolerance_f` in either direction — a reading exactly at the tolerance band edge is within tolerance. Second, energy-surcharge settlement: every `ACTIVE` assignment's work order moves from `IN_PROCESS` to `PROCESSED` and receives its `energy_surcharge_cents`, computed at 133 cents per pound of that order's `received_weight_lb` and rounded half-up to whole cents per order line. The load's `total_energy_surcharge_cents` is then the sum of those per-order rounded amounts. The rounding order is pinned: each order line is rounded first and the rounded values are summed — summing raw values and rounding once at the end produces different cents and is non-conformant.

Aborting a run likewise requires `RUNNING` (`ERR_LOAD_NOT_RUNNING`). The load moves to `ABORTED`, every `ACTIVE` assignment flips to `REMOVED`, each affected work order returns from `IN_PROCESS` to `RECEIVED`, and `total_weight_lb` is recomputed — to zero, since no assignments remain `ACTIVE`. Both `COMPLETED` and `ABORTED` are terminal for the batch.

### 3.7. Hardness Inspection and Disposition of Nonconforming Lots

After a lot reaches `PROCESSED`, quality evidence is gathered by a `QualityEngineer` through an InspectionTest naming the `work_order_id`, a non-empty `hardness_readings` array of HRC numbers, and the measured `measured_distortion_in`. An empty readings array is rejected with `ERR_INVALID_REQUEST`, and testing an order whose `processing_status` is not `PROCESSED` or whose `quality_status` is not `PENDING_TEST` fails with `ERR_WORK_ORDER_NOT_TESTABLE` (HTTP 409). The server records the caller's identity in `recorded_by_user_id` and computes two derived values: `avg_hardness_hrc`, the mean of `hardness_readings` rounded to one decimal place half-up, and `result`, which is `PASS` when the average lies between `hardness_min_hrc` and `hardness_max_hrc` inclusive and `measured_distortion_in` does not exceed the recipe's `fixture_distortion_allowance_in`, and `FAIL` otherwise. The record is immutable once created.

The test outcome cascades into the order's independent quality dimension. A `PASS` moves `quality_status` from `PENDING_TEST` to `PASSED`. A `FAIL` moves it from `PENDING_TEST` to `FAILED` and opens a DispositionCase in `OPEN` status, capturing the failing lot's `work_order_id` and the test's `inspection_test_id`, with `decision` and `decided_by_user_id` null until a decision is recorded.

Disposition is decided by a `QualityEngineer` — but never the same one who recorded the failing test: if the decider's `X-User-ID` equals the test's `recorded_by_user_id`, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The case must still be `OPEN`, failing with `ERR_DISPOSITION_NOT_OPEN` (HTTP 409) otherwise, and the `decision` must be one of three values, each with its own cascade. `RE_TREAT` is available only while the order's `retreat_count` remains strictly below the recipe's `max_retreats` — once the count has reached the cap, a re-treat attempt fails with `ERR_RETREAT_LIMIT_REACHED` (HTTP 422); a successful re-treat moves the order from `PROCESSED` to `AWAITING_RETREAT`, increments `retreat_count` by one, and resets `quality_status` from `FAILED` to `PENDING_TEST`, ready to be scheduled onto a new load. `SCRAP` moves the order from `PROCESSED` to `SCRAPPED` and opens a `PENDING` LiabilityClaim whose `payout_cents` follows §3.8, adding that payout to the customer's `outstanding_liability_exposure_cents`. `RETURN_AS_IS` waives the failure: `quality_status` moves from `FAILED` to `WAIVED` while `processing_status` stays `PROCESSED`, leaving the lot shippable. In every branch the server records `decided_by_user_id` from the caller's header, and the case moves to `DECIDED`, which is terminal.

### 3.8. Shipping, Cancellation, and Liability Settlement

Shipping is performed by a `CustomerServiceRep` and is gated on quality: the order must be `PROCESSED` with `quality_status` either `PASSED` or `WAIVED`, failing otherwise with `ERR_WORK_ORDER_NOT_SHIPPABLE` (HTTP 409). Shipping stamps `shipped_at` from the logical clock and moves the order to `SHIPPED`, a terminal status. For `RUSH` lots this is also the moment of truth for the guarantee: `turnaround_breached` is `true` when `shipped_at` is strictly later than `promised_due_at` — shipping exactly at the promised instant meets the guarantee and is not a breach. Settlement follows immediately: `rush_surcharge_final_cents` becomes the previously quoted surcharge when the guarantee was met, and 0 when it was breached. `STANDARD` lots always settle with `turnaround_breached` false and a final surcharge of 0.

Cancellation, likewise a `CustomerServiceRep` action, is possible only while the order is `RECEIVED` or `SCHEDULED` (`ERR_WORK_ORDER_NOT_CANCELLABLE`, HTTP 409) and lands in the terminal `CANCELLED` status. Cancelling a `SCHEDULED` order additionally flips its `ACTIVE` assignment to `REMOVED`, recomputes the load's `total_weight_lb`, and increments the load's `version` by one.

Liability claims exist only because a disposition decided `SCRAP`; each is created in `PENDING` with `work_order_id` and `customer_id` copied from the scrapped order. The payout depends on the customer's elected tier. Under `STANDARD`, `payout_cents` is the lesser of the order's `declared_value_cents` and three times its `processing_charge_cents`. Under `EXTENDED`, the material is valued by weight: first extend 85 cents per pound across the lot's `received_weight_lb`, round that extension half-up to whole cents, and only then apply the cap — `payout_cents` is the lesser of `declared_value_cents` and the rounded extension. The rounding order is pinned: the per-pound extension is rounded before the declared-value cap is applied.

From `PENDING`, a claim can be accepted by the customer it belongs to — ownership is enforced by comparing `X-User-ID` to the claim's `customer_id` (`ERR_OWNERSHIP_MISMATCH`), and a claim no longer `PENDING` rejects acceptance with `ERR_CLAIM_NOT_PENDING` (HTTP 409) — moving it to `ACCEPTED`. A `CustomerServiceRep` then settles an `ACCEPTED` claim by paying it (any other status fails with `ERR_CLAIM_NOT_ACCEPTED`, HTTP 409), moving it to `PAID` and subtracting `payout_cents` from the customer's `outstanding_liability_exposure_cents`. Alternatively, a `CustomerServiceRep` may reject a `PENDING` claim (`ERR_CLAIM_NOT_PENDING`), moving it to `REJECTED` and likewise releasing `payout_cents` from the exposure total. `PAID` and `REJECTED` are terminal. The account's exposure figure always reflects the sum of payouts over claims still `PENDING` or `ACCEPTED`, recomputed on claim creation, payment, and rejection.

### 3.9. Nadcap Audit Evidence Packages

For accreditation audits, a `QualityEngineer` compiles an AuditPackage over a furnace by supplying `furnace_id` and a `load_batch_ids` array. Every listed load must be `COMPLETED` on that furnace; a load in any other status, or completed on a different furnace, fails compilation with `ERR_LOAD_NOT_COMPLETED` (HTTP 409). At creation the server computes the `evidence_manifest` — an object with `load_batch_ids`, `pyrometry_record_ids`, and `thermocouple_reading_counts` — bundling the listed loads (the manifest's `load_batch_ids` echoes the submitted array), the furnace's pyrometry records whose `performed_at` is on or before the latest listed load's `completed_at` (`pyrometry_record_ids` lists the matching records in their creation order), and per-load thermocouple reading counts (`thermocouple_reading_counts` is an object mapping each listed load's id to its reading count). The `load_batch_ids` array may be empty, which yields an empty `pyrometry_record_ids` list and empty counts. The package is created in `DRAFT` with `issued_at` null.

Issuance is the auditor's act, segregated from compilation by role: a `NadcapAuditor` issues a package that is still in `DRAFT` (any other status fails with `ERR_PACKAGE_NOT_DRAFT`, HTTP 409). Issuance stamps `issued_at` from the logical clock, freezes the `evidence_manifest` immutable thereafter, and moves the package to `ISSUED`, which is terminal and locked.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, preconditions, and side effects for each operation are specified in the workflows of §3 — fields beyond those named for an operation, including server-managed computed fields such as `outstanding_liability_exposure_cents`, are ignored when supplied; the table below is the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customer-accounts` | Create a customer account | CustomerServiceRep |
| GET | `/customer-accounts/{customerId}` | Get a customer account | Any |
| POST | `/furnace-recipes` | Create a furnace recipe (DRAFT) | QualityEngineer |
| GET | `/furnace-recipes/{recipeId}` | Get a furnace recipe | Any |
| POST | `/furnace-recipes/{recipeId}/approve` | Approve a DRAFT recipe | QualityEngineer |
| POST | `/furnaces` | Register a furnace | ShopScheduler |
| GET | `/furnaces/{furnaceId}` | Get a furnace (posture recomputed against the logical clock) | Any |
| POST | `/pyrometry-records` | Record a TUS or instrument calibration | CalibrationTech |
| GET | `/pyrometry-records` | List pyrometry records (filterable by furnace) | Any |
| GET | `/pyrometry-records/{recordId}` | Get a pyrometry record | Any |
| POST | `/work-orders` | Receive a customer material lot | CustomerServiceRep |
| GET | `/work-orders` | List work orders (filterable; paginated) | Any |
| GET | `/work-orders/{workOrderId}` | Get a work order | Any |
| POST | `/work-orders/{workOrderId}/ship` | Ship a processed, quality-cleared lot | CustomerServiceRep |
| POST | `/work-orders/{workOrderId}/cancel` | Cancel a RECEIVED or SCHEDULED work order | CustomerServiceRep |
| POST | `/inspection-tests` | Record a hardness + distortion inspection | QualityEngineer |
| GET | `/inspection-tests` | List inspection tests | Any |
| GET | `/inspection-tests/{testId}` | Get an inspection test | Any |
| GET | `/disposition-cases` | List disposition cases | Any |
| GET | `/disposition-cases/{caseId}` | Get a disposition case | Any |
| POST | `/disposition-cases/{caseId}/decide` | Decide a failed lot's disposition (segregated from the test recorder) | QualityEngineer |
| GET | `/liability-claims` | List liability claims | Any |
| GET | `/liability-claims/{claimId}` | Get a liability claim | Any |
| POST | `/liability-claims/{claimId}/accept` | Customer accepts the payout offer | Customer |
| POST | `/liability-claims/{claimId}/reject` | Reject a pending claim (no payout owed) | CustomerServiceRep |
| POST | `/liability-claims/{claimId}/pay` | Pay an accepted claim | CustomerServiceRep |
| POST | `/load-batches` | Create a furnace load batch (BUILDING) | ShopScheduler |
| GET | `/load-batches` | List load batches | Any |
| GET | `/load-batches/{loadBatchId}` | Get a load batch | Any |
| POST | `/load-batches/{loadBatchId}/assignments` | Assign a work order to a BUILDING/HOLD load (OCC-guarded) | ShopScheduler |
| POST | `/load-batches/{loadBatchId}/assignments/{assignmentId}/unassign` | Remove an assignment from a BUILDING/HOLD load (OCC-guarded) | ShopScheduler |
| GET | `/load-assignments` | List load assignments | Any |
| GET | `/load-assignments/{assignmentId}` | Get a load assignment | Any |
| POST | `/load-batches/{loadBatchId}/release` | Release a built load to the floor (full gate: state, posture, containment, schedule, non-empty) | ShopScheduler |
| POST | `/load-batches/{loadBatchId}/start-run` | Start the furnace run | FurnaceOperator |
| POST | `/load-batches/{loadBatchId}/complete-run` | Complete the run (quench verified) | FurnaceOperator |
| POST | `/load-batches/{loadBatchId}/abort` | Abort a running load | FurnaceOperator |
| POST | `/thermocouple-readings` | Append a load thermocouple reading (batch traceability) | FurnaceOperator |
| GET | `/thermocouple-readings` | List load thermocouple readings | Any |
| GET | `/thermocouple-readings/{readingId}` | Get a thermocouple reading | Any |
| POST | `/audit-packages` | Compile a Nadcap evidence package over completed loads | QualityEngineer |
| GET | `/audit-packages` | List audit packages | Any |
| GET | `/audit-packages/{packageId}` | Get an audit package | Any |
| POST | `/audit-packages/{packageId}/issue` | Issue (lock) a DRAFT package | NadcapAuditor |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving endpoint) | Any |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status contract.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_RECIPE_NOT_FOUND` | 404 Not Found |
| `ERR_FURNACE_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LOAD_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DISPOSITION_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_PYROMETRY_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_THERMOCOUPLE_READING_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_RECIPE_NOT_APPROVED` | 409 Conflict |
| `ERR_DUPLICATE_RECIPE` | 409 Conflict |
| `ERR_FURNACE_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_RECIPE_CLASS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_QUENCH_MEDIA_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_RECIPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WORK_ORDER_NOT_ASSIGNABLE` | 409 Conflict |
| `ERR_LOAD_WEIGHT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EMPTY_LOAD` | 422 Unprocessable Entity |
| `ERR_LOAD_NOT_BUILDING` | 409 Conflict |
| `ERR_LOAD_NOT_RELEASED` | 409 Conflict |
| `ERR_LOAD_NOT_RUNNING` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_TESTABLE` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_SHIPPABLE` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DISPOSITION_NOT_OPEN` | 409 Conflict |
| `ERR_RETREAT_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CLAIM_NOT_PENDING` | 409 Conflict |
| `ERR_CLAIM_NOT_ACCEPTED` | 409 Conflict |
| `ERR_LOAD_NOT_COMPLETED` | 409 Conflict |
| `ERR_PACKAGE_NOT_DRAFT` | 409 Conflict |
| `ERR_FURNACE_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_QUENCH_PURGE_GAP_VIOLATION` | 409 Conflict |
| `ERR_PYROMETRY_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_INVALID_GUARANTEE_WINDOW` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_CREDIT_HOLD` | 402 Payment Required |
