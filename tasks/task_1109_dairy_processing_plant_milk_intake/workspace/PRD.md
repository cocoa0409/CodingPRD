# Dairy Plant Milk Intake API — Product Requirements Document

## 1. Introduction

Grade A fluid milk plants live at the intersection of food-safety regulation and federal milk marketing order economics. Every inbound tanker of raw milk must be held in quarantine until antibiotic and somatic-cell evidence clears it, and every load that cannot be cleared must be turned away — with consequences that compound for the shipping farm across a rolling thirty-day window. At the same time, producers are paid monthly on component value, over-order premiums, and hauling deductions, all of which depend on a Marketing Order Pool whose Producer Price Differential cannot be finalized until the regulatory announcement calendar allows it.

This document specifies the API for a dairy processing plant that receives raw milk from licensed producers, runs laboratory and component testing on every inbound tanker, schedules pasteurizer runs and clean-in-place cycles under PMO (Pasteurized Milk Ordinance) constraints, codes finished product with shelf-life-aware distribution routing, maintains its Grade A permit through state inspections, and settles with producers monthly under the Federal Milk Marketing Order pooling rules. The audience is the engineering team implementing the service; the perspective is the plant operations and financial controller who must satisfy both the State Inspector and the pool auditor.

The system enforces segregation of duties between laboratory and quality-assurance staff, optimistic concurrency on the two writes where stale producer or pool state is most damaging, and a pinned evaluation order for the pool blend price so that the apparent circular dependency between utilization and the Producer Price Differential resolves deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_AUTH`. A request whose role is not authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`. The role names, spelled exactly as the API expects them, are `PlantController`, `QualityAssuranceManager`, `LabTechnician`, `PasteurizerOperator`, and `StateInspector`.

All five roles use an **opaque** identity model. When `X-User-Role` is `PlantController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. The same rule holds for `QualityAssuranceManager`, `LabTechnician`, `PasteurizerOperator`, and `StateInspector` — each role's `X-User-ID` is an opaque operator identifier, never a foreign key into the `Producer`, `Hauler`, or any other persisted entity table. Segregation-of-duties checks compare `X-User-ID` values against specific operator-id fields that are themselves opaque (for example `lab_technician_id` on `LabTest` and on the `CipCycle` creator); they never compare `X-User-ID` to a resource `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be non-negative. List responses always populate `meta.limit`, `meta.offset`, `meta.total_count`, and `meta.has_more`. Default sort order across all list endpoints is `created_at` ascending; no list endpoint accepts an explicit sort parameter.

### 2.4. Common Resource Properties, Identity, and Versioning

Every entity described in §3 carries the following system-managed fields in addition to its domain fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits; `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation; and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every state transition or mutating update to the entity. All entities listed in this PRD — `Producer`, `Hauler`, `TankerReceipt`, `LabTest`, `ComponentAssay`, `ProducerSettlement`, `PasteurizerRun`, `CipCycle`, `ProductBatch`, `DistributionRoute`, `GradeAPermit`, `MarketingOrderPool` — carry the full common-field set; none are timestamp-only.

### 2.5. Nested Resource Retrieval and Path-Parameter Resolution

Several resources are addressed through nested paths (a lab test under its tanker receipt, a settlement under its producer, a CIP cycle or product batch under its pasteurizer run). Path template identifiers are validated left to right. If any segment fails to resolve to an existing resource, the request is rejected with `ERR_NOT_FOUND` and no further segments are evaluated. A request for a child whose parent id does not exist therefore reports `ERR_NOT_FOUND` on the parent rather than the child, and a request whose child id does not exist under a valid parent likewise reports `ERR_NOT_FOUND`.

### 2.6. Logical Clock and Time Semantics

The server maintains a logical clock distinct from the host wall clock. On startup, the logical clock is initialized to `2026-05-01T00:00:00Z` and never falls back to wall-clock time. A `PlantController` may advance the logical clock via a test-driving capability that accepts a target instant `to_iso8601`; the clock moves forward to that instant. All timestamps written by the server — `created_at`, `updated_at`, `completed_at`, `actual_start_at`, `actual_end_at`, and any "current clock" reference in a precondition — read from this logical clock. Temporal validations (the FMMO announcement window, the trailing-30-day rejection window, the trailing-24-hour CIP freshness window) are all evaluated against the logical clock, never against wall time.

### 2.7. Optimistic Concurrency Control

Two write endpoints in the system carry a mandatory optimistic-concurrency input, and no other endpoint takes a version field.

Releasing a tanker receipt out of quarantine is guarded against stale producer state: the request must include `expected_producer_version` carrying the `version` value of the linked `Producer` that the client most recently observed. If the producer's current `version` does not match — because another writer has since advanced it, for example by rejecting a different tanker for the same producer and cascading `quality_flag` to `PROBATION` or `status` to `SUSPENDED` — the release is rejected with `ERR_STALE_PRODUCER_VERSION` (HTTP 412). This prevents the client from releasing milk against a producer whose standing it has not observed.

Finalizing a marketing-order pool is guarded against stale pool state: the request must include `expected_pool_version` carrying the `version` value of the `MarketingOrderPool` the client most recently observed. If the pool's current `version` no longer matches — because another writer has since announced it, which legitimately bumps `version` — the finalize is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412). This prevents the client from finalizing against a pool state it has not observed.

Endpoints not listed in this subsection do not take a version input field.

### 2.8. Precision, Rounding, and Currency

All monetary amounts in the API are integer cents unless explicitly stated otherwise. Component masses (`butterfat_lbs`, `protein_lbs`, `other_solids_lbs`) are carried to exactly 2 decimal places and rounded half-up. The Producer Price Differential is an integer number of cents per hundredweight; the division that derives it from the pool component value uses floor division, not rounding. Producer payment lines (`gross_pool_credit_cents`, `over_order_premium_cents`, `hauling_deduction_cents`, `net_payment_cents`) are integer cents, rounded half-up once at the end of the calculation. Shelf-life and routing comparisons use whole calendar days and treat threshold comparisons as inclusive where stated.

### 2.9. Component Pounds Rounding Discipline

When a `ComponentAssay` is recorded against a tanker receipt, each of `butterfat_lbs`, `protein_lbs`, and `other_solids_lbs` is rounded half-up to 2 decimal places **per component**, and only the per-component rounded values flow downstream into pooling and settlement. Summing the raw unrounded component values and rounding once at the end is not permitted; the per-component-then-summed order is load-bearing for the producer pool credit.

### 2.10. Validation Ordering and Authorization Precedence

When multiple validation rules apply to the same endpoint, they are evaluated in a fixed priority order and the first failure determines the response. The order, from first-evaluated to last, is: authentication presence (missing or malformed headers → `ERR_MISSING_AUTH`), then role authorization for the endpoint (→ `ERR_UNAUTHORIZED_ROLE`), then path-existence resolution left-to-right (→ `ERR_NOT_FOUND`), then state-machine precondition (→ `ERR_INVALID_STATE`), then the business-rule checks enumerated for that endpoint in §3, and finally any field-shape or enum-violation check (→ `ERR_INVALID_INPUT`). A caller can therefore rely on a missing header surfacing as `ERR_MISSING_AUTH` rather than being masked by a downstream state check, and on a non-existent parent id surfacing as `ERR_NOT_FOUND` before any business-safety rule is consulted.

### 2.11. Status Code Conventions

Successful creation of a new resource returns HTTP 201. Successful modifications — including all state-transition actions, completions, approvals, and markings — return HTTP 200. Error responses use the HTTP status paired with each `error_id` in §5.

## 3. Business Logic & Workflows

### 3.1. Producer and Hauler Onboarding

A `PlantController` registers a new producer by submitting the producer's FMMO-issued `producer_code`, the display `farm_name`, and the negotiated `base_hauling_rate_cents_per_cwt`. On creation the producer starts with `status` set to `ACTIVE` (the full lifecycle is `ACTIVE`, `SUSPENDED`, or `TERMINATED`), `quality_flag` set to `STANDARD`, `rolling_rejection_count_30d` at 0, and `version` at 1. Producers may be listed and fetched by `PlantController`, `QualityAssuranceManager`, and `StateInspector`; the list endpoint accepts the pagination parameters `limit` and `offset` plus optional filters on `quality_flag` and `status`.

Haulers are onboarded in a similar flow. A `PlantController` registers each licensed bulk-milk hauler with a `hauler_code`, the `company_name`, and the PMO hauler-license expiry `license_expires_at`. A new hauler begins with `status` `ACTIVE`. Haulers can be fetched by id by `PlantController` and `QualityAssuranceManager`. A hauler's license expiry is not just informational — it gates whether tanker receipts delivered by that hauler may be released, as described in §3.3.

### 3.2. Receiving Milk: Tanker Receipts in Quarantine

When a tanker arrives at the plant bay, a `QualityAssuranceManager` records an inbound `TankerReceipt`. The intake payload names the shipping farm via `producer_id` and the delivering hauler via `hauler_id`, and carries the scale readings `gross_weight_lbs` and `tare_weight_lbs`, the bay arrival timestamp `arrived_at`, and the milk temperature `temperature_f` at the bay. The tare weight must be strictly less than the gross weight; a payload that violates this shape is rejected with `ERR_INVALID_INPUT`. On creation the server computes `net_weight_lbs` as the gross weight minus the tare weight, sets `disposition` to `QUARANTINE`, initializes `antibiotic_result` to `PENDING`, leaves `scc_cells_per_ml` and `rejection_reason` unset, and stamps `created_at` from the logical clock. Receipts may be listed (paginated via `limit` and `offset`, filterable by `producer_id`, `hauler_id`, and `disposition`) and fetched by id by the QA, controller, inspector, and lab roles per §4.

A receipt remains in `QUARANTINE` until the laboratory evidence arrives and the QA manager makes a disposition decision. While in `QUARANTINE` the receipt contributes nothing to the pool, cannot be consumed by a batch, and cannot be paid on.

### 3.3. Laboratory Testing and the Release Decision

Laboratory work is performed by `LabTechnician` operators against a receipt in `QUARANTINE`. A lab test is created with `tanker_receipt_id` bound to the parent receipt, a `test_type` of `ANTIBIOTIC`, `SCC`, or `TEMPERATURE_RECHECK`, a numeric `result_value` whose interpretation depends on the test type — somatic-cell results in cells per millilitre, antibiotic results in parts per billion with 0 indicating a negative screen, temperature recheck results in degrees Fahrenheit — and the `lab_technician_id` of the operator recording the result. New tests start with `status` `DRAFT`.

Completion is a separate step by a `LabTechnician`. When a test moves from `DRAFT` to `COMPLETED`, the server stamps `completed_at` from the logical clock and derives `result_disposition` from the test-type threshold: an `ANTIBIOTIC` test passes only when `result_value` equals 0, an `SCC` test passes only when `result_value` is below 750000 cells per millilitre, and a `TEMPERATURE_RECHECK` test passes only when `result_value` is at most 45 degrees Fahrenheit. Completion propagates onto the parent receipt: an `ANTIBIOTIC` completion sets the receipt's `antibiotic_result`, an `SCC` completion sets `scc_cells_per_ml`, and a `TEMPERATURE_RECHECK` completion overwrites `temperature_f`. Completion is only permitted while the parent receipt is still in `QUARANTINE`; attempting it against a receipt that has already been released, rejected, or diverted is rejected with `ERR_RECEIPT_NOT_IN_QUARANTINE`. Segregation of duties also applies at completion: the `LabTechnician` completing the test must not be the same `X-User-ID` as the `QualityAssuranceManager` who created the parent receipt — otherwise the request is rejected with `ERR_SOD_VIOLATION`. If a completed test's `result_disposition` is `FAIL`, the parent receipt remains in `QUARANTINE` awaiting the QA disposition decision.

The release decision is the heart of intake safety. Releasing a receipt, transitioning `disposition` from `QUARANTINE` to `RELEASED_FOR_PROCESSING`, is performed by a `QualityAssuranceManager` and is guarded by a strict battery of preconditions evaluated in the order specified in §2.10. All required lab tests — at minimum one `ANTIBIOTIC` and one `SCC` — for this receipt must be `COMPLETED`, otherwise `ERR_LAB_TESTS_PENDING`. The receipt's `antibiotic_result` must be `NEGATIVE`, otherwise `ERR_ANTIBIOTIC_POSITIVE`. The receipt's `scc_cells_per_ml` must be below 750000 cells per millilitre, otherwise `ERR_SCC_EXCEEDED`. The receipt's `temperature_f` must be at most 45 degrees Fahrenheit, otherwise `ERR_TEMPERATURE_EXCEEDED`. The linked hauler must currently be in `ACTIVE` `status` and its `license_expires_at` must be later than the receipt's `arrived_at`, otherwise `ERR_HAULER_LICENSE_EXPIRED`. The linked producer must currently be `ACTIVE`, otherwise `ERR_PRODUCER_SUSPENDED`. And the plant's most recent `GradeAPermit` must be in `ACTIVE` `status` and not expired, otherwise `ERR_PERMIT_NOT_ACTIVE`. The release request must also carry `expected_producer_version` matching the producer's current `version`, as described in §2.7; a mismatch is rejected with `ERR_STALE_PRODUCER_VERSION` before any state mutation occurs.

On a successful release, several cascades fire together. The receipt's `disposition` becomes `RELEASED_FOR_PROCESSING` and its `version` and `updated_at` advance. The producer's `version` is incremented by 1 — this is the mutation the OCC guard on release is designed to serialize against. Each `ComponentAssay` recorded against the receipt becomes eligible for settlement pooling. And the `MarketingOrderPool` for the receipt's calendar month has its `total_pooled_lbs` incremented by this receipt's `net_weight_lbs`. The producer's `rolling_rejection_count_30d` is recomputed, though on the release transition that recompute produces no change.

### 3.4. Rejection, Diversion, and the Rolling Quality Flag

Rejection is the complement of release and may be invoked by a `QualityAssuranceManager` only while the receipt is in `QUARANTINE`. Rejection requires that at least one rejection criterion is met — antibiotic result `POSITIVE`, somatic-cell count at or above 750000 cells per millilitre, temperature above 45 degrees Fahrenheit, or a hauler license expired relative to `arrived_at`. If none of these criteria holds, the rejection is rejected with `ERR_NO_REJECTION_CRITERION`. On a successful rejection, `disposition` moves to `REJECTED` (a terminal state for the receipt) and the server sets `rejection_reason` to the highest-priority matching criterion, where the priority order is `ANTIBIOTIC_POSITIVE`, then `SCC_EXCEEDED`, then `TEMPERATURE_EXCEEDED`, then `HAULER_LICENSE_EXPIRED`. Any `ComponentAssay` records attached to the receipt become ineligible for pooling.

Rejection also feeds the producer's standing. The producer's `rolling_rejection_count_30d` is recomputed as the count of this producer's receipts that entered `REJECTED` within the trailing 30-calendar-day window, inclusive of both endpoints of the window. If that count reaches or exceeds 4, the producer's `status` transitions to `SUSPENDED`. Otherwise, if the count reaches or exceeds 2, the producer's `quality_flag` transitions to `PROBATION`. Otherwise, if the count is at least 1, `quality_flag` is `STANDARD`. Only when the count is 0 does the producer hold the `PREMIUM` quality flag.

A receipt that has already been released may still be diverted — for example if a downstream quality concern emerges before the milk is consumed. Diversion transitions `disposition` from `RELEASED_FOR_PROCESSING` to `DIVERTED` and is performed by a `QualityAssuranceManager`. Diversion is blocked if any `ProductBatch` that consumed this receipt for the pool month has already been `CODED`; such a request is rejected with `ERR_BATCH_ALREADY_CODED`. On a successful diversion, the `MarketingOrderPool` for the receipt's calendar month has its `total_pooled_lbs` decremented by `net_weight_lbs`, and the draft `ProducerSettlement` records for the affected pool month are recomputed to reflect the reduced pool.

### 3.5. Component Assay and the Pooling Input Set

Once a receipt is `RELEASED_FOR_PROCESSING`, a `LabTechnician` may record a `ComponentAssay` against it. The payload supplies `tanker_receipt_id`, plus three percentages — `butterfat_pct`, `protein_pct`, and `other_solids_pct` — each carried to 2 decimal places. The server then computes the component masses per §2.9: `butterfat_lbs` is the receipt's `net_weight_lbs` multiplied by `butterfat_pct` and divided by 100, rounded half-up to 2 decimal places; `protein_lbs` is `net_weight_lbs` multiplied by `protein_pct` and divided by 100, rounded half-up to 2 decimal places; and `other_solids_lbs` is `net_weight_lbs` multiplied by `other_solids_pct` and divided by 100, also rounded half-up to 2 decimal places. Assays are eligible input to the settlement pooling calculations only while their parent receipt is in `RELEASED_FOR_PROCESSING`; rejection, diversion, or abort cascades mark them ineligible. Assays may be listed per receipt by `LabTechnician`, `PlantController`, and `QualityAssuranceManager`.

### 3.6. Pasteurizer Runs, Batches, and Shelf-Life Coding

Pasteurization is scheduled by a `PasteurizerOperator`. Creating a `PasteurizerRun` requires the physical `pasteurizer_id` (such as `HTST-1` or `HTST-2`), a `scheduled_start_at`, a `scheduled_end_at` that must be strictly later than the start, a `flow_rate_gph` in gallons per hour, and a `min_hold_temp_f` that must be at least 161 degrees Fahrenheit for HTST operation. New runs begin in `SCHEDULED`. Runs may be listed (paginated via `limit` and `offset`, filterable by `pasteurizer_id` and `status`) and fetched by id.

Starting a run — transitioning `SCHEDULED` to `RUNNING` — is gated by three preconditions. The plant's most recent `GradeAPermit` must be `ACTIVE` and its `expires_at` must be later than the run's `scheduled_end_at`, otherwise `ERR_PERMIT_NOT_ACTIVE`. The most recent completed `CipCycle` for the same `pasteurizer_id` must have a `validation_outcome` of `PASS` and a `completed_at` within the trailing 24 hours of the current logical clock, otherwise `ERR_CIP_STALE`. And no other `PasteurizerRun` for the same `pasteurizer_id` may already be in `RUNNING` with an overlapping half-open window from `scheduled_start_at` to `scheduled_end_at`, otherwise `ERR_PASTEURIZER_OVERLAP`. On a successful start the server stamps `actual_start_at` from the logical clock.

While a run is `RUNNING`, the operator schedules product batches against it. A `ProductBatch` is created with `pasteurizer_run_id`, a `product_code` of `WHOLE_MILK`, `TWO_PERCENT`, `SKIM`, `HEAVY_CREAM`, `BUTTER`, or `CONDENSED_SKIM`, a `quantity_gallons` planned, and a `shelf_life_days` coded shelf life. New batches start in `SCHEDULED`. Beginning a batch moves it from `SCHEDULED` to `IN_PRODUCTION` and requires the parent run to currently be `RUNNING`, otherwise `ERR_RUN_NOT_RUNNING`. Coding a batch moves it from `IN_PRODUCTION` to `CODED`. Coding enforces the product-specific shelf-life cap — at most 21 days for `WHOLE_MILK`, `TWO_PERCENT`, and `SKIM`; at most 30 days for `HEAVY_CREAM`; at most 180 days for `BUTTER`; and at most 270 days for `CONDENSED_SKIM` — otherwise `ERR_SHELF_LIFE_EXCEEDED`. Coding also enforces distribution feasibility: for every `DistributionRoute` the batch will ship on, the number of days from the current logical clock to `code_date` minus that route's `transit_days` must be at least the route's `min_days_of_code_required`, otherwise `ERR_INSUFFICIENT_CODE_LIFE`. On successful coding the server computes `code_date` as the parent run's `actual_end_at` (or the current logical clock if the run is still `RUNNING`) plus `shelf_life_days` calendar days; this date drives distribution routing downstream.

A batch may instead be scrapped by the operator, transitioning `IN_PRODUCTION` to `SCRAPPED` with no further preconditions.

Completing a run moves it from `RUNNING` to `COMPLETE`. The completion requires that every `ProductBatch` for the run be in `CODED` or `SCRAPPED`; otherwise `ERR_BATCHES_UNFINISHED`. On completion the server stamps `actual_end_at` from the logical clock and, for every `CODED` batch, recomputes `code_date` as the now-final `actual_end_at` plus the batch's `shelf_life_days`. Aborting a run moves it from `RUNNING` to `ABORTED` with no preconditions; on abort the server stamps `actual_end_at`, transitions every non-terminal batch of the run to `SCRAPPED`, and marks every `ComponentAssay` linked to receipts consumed by this run ineligible for pooling. Cancelling a run moves it from `SCHEDULED` to `CANCELLED` and requires that no batch for the run be in `IN_PRODUCTION`, otherwise `ERR_BATCH_IN_PRODUCTION`; on cancel, every `SCHEDULED` batch of the run transitions to `SCRAPPED`.

### 3.7. Clean-in-Place Validation

Clean-in-place is recorded per pasteurizer run by a `PasteurizerOperator`, with `pasteurizer_run_id` bound to the parent run and `started_at`, `caustic_conductivity_ms`, and `rinse_ph` supplied at recording time. A new CIP cycle starts in `IN_PROGRESS`. CIP validation is a `QualityAssuranceManager` decision with two preconditions evaluated together: the final rinse's `caustic_conductivity_ms` must be at least 80.0 mS/cm (a shortfall is rejected with `ERR_CIP_CAUSTIC_LOW`, or with the umbrella `ERR_CIP_VALIDATION_FAILED` when the rule is reported at the endpoint level), and the final rinse's `rinse_ph` must lie in the inclusive range from 6.5 to 8.0 (an out-of-range pH is rejected with `ERR_CIP_PH_OUT_OF_RANGE`, or with the umbrella `ERR_CIP_VALIDATION_FAILED`). Segregation of duties applies: the `QualityAssuranceManager` validating the cycle must not share `X-User-ID` with the operator who created it, otherwise `ERR_SOD_VIOLATION`. On a successful validation the cycle transitions `IN_PROGRESS` to `VALIDATED`, `validation_outcome` is set to `PASS`, and `completed_at` is stamped from the logical clock. A cycle may instead be marked failed — moving `IN_PROGRESS` to `FAILED`, setting `validation_outcome` to `FAIL`, and stamping `completed_at` — in which case the parent `PasteurizerRun` cannot be started until a subsequent `VALIDATED` cycle exists.

### 3.8. Distribution Routing and Code-Life at Delivery

Distribution routes are managed by the `PlantController`. Registering a `DistributionRoute` requires a `route_code`, the destination `destination_zip`, the calendar `transit_days` from dock to destination, and the customer's `min_days_of_code_required` at delivery. A new route starts in `ACTIVE`. Routes may be fetched by id by `PlantController` and `PasteurizerOperator`.

The route's purpose is realized at batch-coding time. When a batch is coded, the `code_date` derived in §3.6 is compared against each route the batch will ship on: the calendar-day difference between `code_date` and the current logical clock, minus the route's `transit_days`, must be at least the route's `min_days_of_code_required`. If the batch would arrive with fewer days of code than the customer requires, the coding is rejected with `ERR_INSUFFICIENT_CODE_LIFE`.

### 3.9. Grade A Permit and Inspection Cadence

A `StateInspector` registers the plant's Grade A permit with `permit_number`, `issued_at`, and `expires_at`. A new permit begins in `ACTIVE` with `violation_count_12mo` at 0. Permits may be fetched by id by `StateInspector`, `PlantController`, and `QualityAssuranceManager`.

Recording an inspection is the primary driver of permit state. The inspector submits an `inspection_score` and a `violations_found` count. If the inspection passed — that is, the score is 90 or higher and the new violations do not push `violation_count_12mo` to 3 or more — then moving the permit to `UNDER_REVIEW` is inappropriate, and the request is rejected with `ERR_INSPECTION_PASSED`. Otherwise the permit transitions from `ACTIVE` to `UNDER_REVIEW`, its `inspection_score` is updated, and its `violation_count_12mo` is incremented by `violations_found`. `UNDER_REVIEW` is reachable only from `ACTIVE`.

From `UNDER_REVIEW` the inspector has three exits. Suspending the permit requires `violation_count_12mo` to be at least 3, otherwise `ERR_INSUFFICIENT_VIOLATIONS`; on suspension the permit transitions to `SUSPENDED`, every `SCHEDULED` `PasteurizerRun` transitions to `CANCELLED`, and `ProducerSettlement` approvals are blocked until reinstatement. Reinstating the permit requires `violation_count_12mo` to be below 3 after corrective action, otherwise `ERR_VIOLATIONS_OUTSTANDING`; on reinstatement the permit transitions to `REINSTATED`. Revoking the permit requires `violation_count_12mo` to be at least 5, otherwise `ERR_VIOLATIONS_BELOW_REVOCATION`; on revocation the permit transitions to `REVOKED`, all future `TankerReceipt` intake is blocked, and receipts still in `QUARANTINE` are diverted. `SUSPENDED` and `REVOKED` are terminal states for the permit.

### 3.10. Marketing Order Pool and the PPD Waterfall

A `PlantController` opens the monthly `MarketingOrderPool` with `pool_month` in `YYYY-MM` format, the FMMO-announced `announced_class_i_price_cents` (cents per hundredweight), and the three component prices `butterfat_price_cents_per_lb`, `protein_price_cents_per_lb`, and `other_solids_price_cents_per_lb`. A new pool begins in `DRAFT` with `total_pooled_lbs` at 0 and `producer_price_differential_cents` unset. Pools may be fetched by id by `PlantController` and `StateInspector`.

Announcing a pool transitions it from `DRAFT` to `ANNOUNCED`. Two preconditions apply. All component prices must be positive, otherwise `ERR_PRICES_INCOMPLETE`. And the current logical clock must be at or after the 23rd of the month following `pool_month` at 00:00 UTC — the FMMO announcement date — otherwise `ERR_ANNOUNCEMENT_TOO_EARLY`. On a successful announce the server computes `producer_price_differential_cents` using the pinned evaluation order that resolves the apparent circular dependency between utilization and PPD. First, `utilization_pct` is computed as the pool's Class I pounds divided by `total_pooled_lbs` and multiplied by 100. Second, the blend price per hundredweight is selected from a tier table based on utilization: at least 60 percent utilization yields a blend price of 2400 cents per hundredweight, at least 40 percent but below 60 percent yields 2100 cents, and below 40 percent yields 1800 cents. Third, the pool's aggregate `component_value_cents` is computed as the sum across all receipts in the pool month with `disposition` `RELEASED_FOR_PROCESSING` of `butterfat_lbs` times `butterfat_price_cents_per_lb`, plus `protein_lbs` times `protein_price_cents_per_lb`, plus `other_solids_lbs` times `other_solids_price_cents_per_lb`. Fourth and finally, the `producer_price_differential_cents` is the blend price per hundredweight minus the floor of `component_value_cents` multiplied by 100 and divided by `total_pooled_lbs` — floor division, not rounding.

Finalizing a pool transitions it from `ANNOUNCED` to `FINALIZED`. Finalization is guarded by the OCC rule from §2.7: the request must carry `expected_pool_version` matching the pool's current `version`, otherwise `ERR_STALE_POOL_VERSION` (HTTP 412). Finalization also requires that every `ProducerSettlement` for the pool month still be in `DRAFT` with `pricing_variant` `PROVISIONAL`; if any settlement has already been approved, the finalize is rejected with `ERR_SETTLEMENTS_ALREADY_APPROVED`. On a successful finalize the pool's `version` increments by 1 and, for each `ProducerSettlement` of the month, `pricing_variant` transitions from `PROVISIONAL` to `FINAL` and the settlement's credit is recomputed under the `FINAL` variant. `FINALIZED` is the terminal state for the pool.

### 3.11. Producer Settlement: Provisional and Final Variants

Settlement creation is a `PlantController` action against a specific producer. The payload supplies the monthly `period_start_date` and `period_end_date`. On creation the settlement begins in `DRAFT` with `pricing_variant` `PROVISIONAL`, and the four financial lines are computed immediately under the provisional variant. Settlements may be listed per producer (with an optional `producer_id` filter) and fetched by id by `PlantController` and `StateInspector`.

The provisional computation walks every `TankerReceipt` for this producer whose arrival falls within the settlement period and whose `disposition` is `RELEASED_FOR_PROCESSING`. The component value is the sum across those receipts of `butterfat_lbs` times the pool's `butterfat_price_cents_per_lb`, plus `protein_lbs` times `protein_price_cents_per_lb`, plus `other_solids_lbs` times `other_solids_price_cents_per_lb`; this becomes the provisional `gross_pool_credit_cents`. The `over_order_premium_cents` is the total delivered hundredweight multiplied by a per-hundredweight tier that depends on the producer's `quality_flag`: 150 cents per hundredweight for `STANDARD`, 250 cents for `PREMIUM`, and 0 for `PROBATION`. The `hauling_deduction_cents` applies the producer's `base_hauling_rate_cents_per_cwt` on a two-tier schedule: for total delivered hundredweight up to and including 1000, the deduction is the total hundredweight multiplied by the base rate; for any hundredweight above 1000, the first 1000 hundredweight is charged at the full base rate and the excess is charged at 80 percent of the base rate. The provisional `net_payment_cents` is `gross_pool_credit_cents` plus `over_order_premium_cents` minus `hauling_deduction_cents`, rounded half-up to integer cents.

Settlement amounts are recomputed on every subsequent receipt for the period that transitions into `RELEASED_FOR_PROCESSING` or `DIVERTED`, so the draft always reflects the current pool.

Approval is the moment the provisional variant flips to final. Approving a settlement, transitioning `DRAFT` to `APPROVED`, is a `PlantController` action with two preconditions: the `MarketingOrderPool` for the settlement's pool month must be in `FINALIZED`, otherwise `ERR_POOL_NOT_FINALIZED`, and the settlement's `pricing_variant` must already be `FINAL` (which the pool finalize cascade has set). On approval, the four financial lines are recomputed under the `FINAL` variant: the `gross_pool_credit_cents` gains an additional term equal to the pool's `producer_price_differential_cents` multiplied by the producer's pooled hundredweight, and the hauling tier-2 discount percentage flips from 80 to 75, so any hundredweight above 1000 is charged at 75 percent of the base rate. The other lines follow through the same formula and the recomputed `net_payment_cents` reflects both changes.

Marking a settlement paid transitions `APPROVED` to `PAID`. The single precondition is that `net_payment_cents` is non-negative, otherwise `ERR_NEGATIVE_SETTLEMENT`. Cancelling a settlement transitions `DRAFT` to `CANCELLED` with no preconditions; both `PAID` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

All endpoints are mounted under the `/dairy` prefix. Resource creation endpoints return HTTP 201 with the created resource in `data`. State-transition and modification endpoints return HTTP 200 with the updated resource in `data`. Error responses follow §2.2 and use the HTTP status paired with the relevant `error_id` in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /dairy/_clock/set_current_utc | Advance the server's logical clock | PlantController |
| POST | /dairy/producers | Register a producer | PlantController |
| GET | /dairy/producers | List producers (paginated) | PlantController, QualityAssuranceManager, StateInspector |
| GET | /dairy/producers/{id} | Fetch a producer | PlantController, QualityAssuranceManager, StateInspector |
| POST | /dairy/haulers | Register a hauler | PlantController |
| GET | /dairy/haulers/{id} | Fetch a hauler | PlantController, QualityAssuranceManager |
| POST | /dairy/tanker-receipts | Record an inbound tanker receipt in quarantine | QualityAssuranceManager |
| GET | /dairy/tanker-receipts | List tanker receipts (paginated) | QualityAssuranceManager, PlantController, StateInspector |
| GET | /dairy/tanker-receipts/{id} | Fetch a receipt | QualityAssuranceManager, PlantController, StateInspector, LabTechnician |
| POST | /dairy/tanker-receipts/{id}/release | Release a receipt from quarantine into processing | QualityAssuranceManager |
| POST | /dairy/tanker-receipts/{id}/reject | Reject a receipt with a reason | QualityAssuranceManager |
| POST | /dairy/tanker-receipts/{id}/divert | Divert a previously released receipt | QualityAssuranceManager |
| POST | /dairy/tanker-receipts/{id}/lab-tests | Record a new lab test against a receipt | LabTechnician |
| GET | /dairy/tanker-receipts/{id}/lab-tests | List lab tests for a receipt | QualityAssuranceManager, LabTechnician, PlantController, StateInspector |
| POST | /dairy/tanker-receipts/{id}/lab-tests/{testId}/complete | Complete a lab test, deriving pass/fail | LabTechnician |
| POST | /dairy/tanker-receipts/{id}/component-assays | Record a component assay against a released receipt | LabTechnician |
| GET | /dairy/tanker-receipts/{id}/component-assays | List assays for a receipt | LabTechnician, PlantController, QualityAssuranceManager |
| POST | /dairy/producers/{producerId}/settlements | Create a draft monthly settlement | PlantController |
| GET | /dairy/producers/{id}/settlements | List settlements for a producer | PlantController, StateInspector |
| GET | /dairy/producers/{producerId}/settlements/{id} | Fetch a settlement | PlantController, StateInspector |
| POST | /dairy/producers/{producerId}/settlements/{id}/approve | Approve a settlement | PlantController |
| POST | /dairy/producers/{producerId}/settlements/{id}/mark-paid | Mark an approved settlement paid | PlantController |
| POST | /dairy/producers/{producerId}/settlements/{id}/cancel | Cancel a draft settlement | PlantController |
| POST | /dairy/pasteurizer-runs | Schedule a pasteurizer run | PasteurizerOperator |
| GET | /dairy/pasteurizer-runs | List runs | PasteurizerOperator, PlantController, QualityAssuranceManager |
| GET | /dairy/pasteurizer-runs/{id} | Fetch a run | PasteurizerOperator, PlantController, QualityAssuranceManager |
| POST | /dairy/pasteurizer-runs/{id}/start | Start a run | PasteurizerOperator |
| POST | /dairy/pasteurizer-runs/{id}/complete | Complete a run | PasteurizerOperator |
| POST | /dairy/pasteurizer-runs/{id}/abort | Abort a run | PasteurizerOperator |
| POST | /dairy/pasteurizer-runs/{id}/cancel | Cancel a scheduled run | PasteurizerOperator |
| POST | /dairy/pasteurizer-runs/{runId}/cip-cycles | Record a CIP cycle | PasteurizerOperator |
| GET | /dairy/pasteurizer-runs/{id}/cip-cycles | List CIP cycles for a run | PasteurizerOperator, QualityAssuranceManager, PlantController |
| POST | /dairy/pasteurizer-runs/{runId}/cip-cycles/{id}/validate | Validate a CIP cycle | QualityAssuranceManager |
| POST | /dairy/pasteurizer-runs/{runId}/cip-cycles/{id}/fail | Mark a CIP cycle failed | QualityAssuranceManager |
| POST | /dairy/pasteurizer-runs/{runId}/batches | Schedule a product batch against a run | PasteurizerOperator |
| GET | /dairy/pasteurizer-runs/{id}/batches | List batches for a run | PasteurizerOperator, PlantController, QualityAssuranceManager |
| POST | /dairy/pasteurizer-runs/{runId}/batches/{id}/begin | Begin a batch | PasteurizerOperator |
| POST | /dairy/pasteurizer-runs/{runId}/batches/{id}/code | Code a batch | PasteurizerOperator |
| POST | /dairy/pasteurizer-runs/{runId}/batches/{id}/scrap | Scrap a batch | PasteurizerOperator |
| POST | /dairy/distribution-routes | Register a distribution route | PlantController |
| GET | /dairy/distribution-routes/{id} | Fetch a route | PlantController, PasteurizerOperator |
| POST | /dairy/grade-a-permits | Register a Grade A permit | StateInspector |
| GET | /dairy/grade-a-permits/{id} | Fetch a permit | StateInspector, PlantController, QualityAssuranceManager |
| POST | /dairy/grade-a-permits/{id}/record-inspection | Record a state inspection result | StateInspector |
| POST | /dairy/grade-a-permits/{id}/suspend | Suspend a permit | StateInspector |
| POST | /dairy/grade-a-permits/{id}/reinstate | Reinstate a permit | StateInspector |
| POST | /dairy/grade-a-permits/{id}/revoke | Revoke a permit | StateInspector |
| POST | /dairy/marketing-order-pools | Create a monthly pool | PlantController |
| GET | /dairy/marketing-order-pools/{id} | Fetch a pool | PlantController, StateInspector |
| POST | /dairy/marketing-order-pools/{id}/announce | Announce a pool | PlantController |
| POST | /dairy/marketing-order-pools/{id}/finalize | Finalize a pool | PlantController |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_PRODUCER_VERSION | 412 |
| ERR_STALE_POOL_VERSION | 412 |
| ERR_ANTIBIOTIC_POSITIVE | 422 |
| ERR_SCC_EXCEEDED | 422 |
| ERR_TEMPERATURE_EXCEEDED | 422 |
| ERR_HAULER_LICENSE_EXPIRED | 422 |
| ERR_PRODUCER_SUSPENDED | 422 |
| ERR_PERMIT_NOT_ACTIVE | 422 |
| ERR_PASTEURIZER_OVERLAP | 409 |
| ERR_CIP_STALE | 422 |
| ERR_CIP_VALIDATION_FAILED | 422 |
| ERR_CIP_CAUSTIC_LOW | 422 |
| ERR_CIP_PH_OUT_OF_RANGE | 422 |
| ERR_SOD_VIOLATION | 403 |
| ERR_SHELF_LIFE_EXCEEDED | 422 |
| ERR_INSUFFICIENT_CODE_LIFE | 422 |
| ERR_LAB_TESTS_PENDING | 422 |
| ERR_RECEIPT_NOT_IN_QUARANTINE | 422 |
| ERR_NO_REJECTION_CRITERION | 422 |
| ERR_BATCH_ALREADY_CODED | 422 |
| ERR_BATCHES_UNFINISHED | 422 |
| ERR_BATCH_IN_PRODUCTION | 422 |
| ERR_RUN_NOT_RUNNING | 422 |
| ERR_POOL_NOT_FINALIZED | 422 |
| ERR_SETTLEMENTS_ALREADY_APPROVED | 422 |
| ERR_PRICES_INCOMPLETE | 422 |
| ERR_ANNOUNCEMENT_TOO_EARLY | 422 |
| ERR_NEGATIVE_SETTLEMENT | 422 |
| ERR_INSPECTION_PASSED | 422 |
| ERR_INSUFFICIENT_VIOLATIONS | 422 |
| ERR_VIOLATIONS_OUTSTANDING | 422 |
| ERR_VIOLATIONS_BELOW_REVOCATION | 422 |
| ERR_INVALID_INPUT | 400 |
