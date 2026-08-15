# Seafood Processing & Import Compliance API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Seafood Processing & Import Compliance API, a system designed to manage the full lifecycle of imported seafood from foreign supplier qualification through processing, labeling, and regulatory release. The platform serves a seafood processor and importer operating under FDA's Foreign Supplier Verification Program (FSVP), HACCP seafood safety regulations, and country-of-origin labeling (COOL) requirements.

The operational challenge is multifaceted: raw material arrives with catch documentation that must be verified for species accuracy, cold-chain integrity must be continuously monitored for histamine-susceptible species and parasite-destruction protocols, processing yields must be tracked with dual-variant estimation (provisional vs. measured), and every finished product lot must carry a compliant label before commercial release. A single species mismatch or temperature excursion triggers a cascading response — quarantine, corrective action, supplier risk re-evaluation, and potentially recall.

The API supports five operational roles plus a platform administration role, each with strictly segregated duties. The compliance audit archetype dominates: every significant action is gated by validations, every mutation bumps a version counter, and the system maintains a full audit trail across supplier evaluations, import entries, receipt lots, processing batches, temperature logs, HACCP monitoring records, corrective actions, labels, and recalls. All monetary values are tracked in integer cents; all weights in kilograms with 3-decimal precision; all percentages with 2-decimal precision, rounded half-up.

---

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles: `ImportCoordinator`, `ReceivingInspector`, `QualityAssuranceTech`, `ProcessingSupervisor`, `ComplianceManager`, and `PlatformAdmin`. Failure to provide both headers, or providing a role not among those listed, will result in an `ERR_UNAUTHENTICATED` error (HTTP 401). Access to specific operations is restricted by role; an attempt to perform an action outside the caller's designated role will be rejected with an `ERR_UNAUTHORIZED_ROLE` error (HTTP 403). Where §4 marks an endpoint's authorized role as "Any", the five operational roles (`ImportCoordinator`, `ReceivingInspector`, `QualityAssuranceTech`, `ProcessingSupervisor`, `ComplianceManager`) are accepted; `PlatformAdmin` is not authorized for those endpoints.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it in system fields such as `opened_by` on CorrectiveAction, `closed_by` on CorrectiveAction, and `evaluated_by` on SupplierEvaluation, but it does not compare it to any entity's `id`. Segregation of duties is enforced by comparing `X-User-ID` values against recorded fields (e.g., a CorrectiveAction's resolver must differ from its `opened_by`).

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

Requests to paths the API does not define are rejected with `ERR_NOT_FOUND` (HTTP 404); a defined path invoked with an unsupported method is rejected with `ERR_NOT_FOUND` (HTTP 405); unexpected server failures are rejected with `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION_FAILED` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; resources created at the same timestamp are ordered by creation (insertion) order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources carry a standard set of system-managed fields:

- **`id`** (string): A unique, system-generated identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-15T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at`** (string): An ISO 8601 UTC timestamp indicating when the resource was last modified. Updated upon any change to the resource's properties. Until the first modification, `updated_at` equals `created_at`.
- **`version`** (integer): A system-managed integer that increments with every modification to the resource. Starts at 1 on creation.

Two entities — **TemperatureLog** and **HaccpMonitoringRecord** — do **not** carry `updated_at` or `version`. They carry only `id` and `created_at`; they are immutable append-only records once created.

All server-assigned business timestamps (`created_at`, `updated_at`, `prior_notice_filed_at`, `entry_filed_at`, `approved_at`, `released_at`, `notified_at`) are taken from the logical clock (§3.13), not wall-clock time. Server-set action timestamps render with three fractional digits at all times; request-echoed and derived datetimes (e.g., `scheduled_arrival`, `harvest_date`, `period_start`, `period_end`, `interval_start`, `interval_end`, `measured_at`, `last_evaluation_period_end`, `next_evaluation_due`) render in ISO 8601 UTC with a `Z` suffix and include three fractional digits only when the millisecond component is nonzero.

### 2.5. Precision, Rounding, and Units

All numeric values in the system follow strict precision rules. Monetary values (`goods_value_cents`, `freight_cost_cents`, `duty_cents`, `allocatable_total_cents`, `allocated_cost_cents`) are integer cents — no fractional cents exist. Weights (`quantity_received_kg`, `quantity_accepted_kg`, `consumed_kg`, `remaining_kg`, `quantity_kg`, `input_total_kg`, `provisional_output_kg`, `actual_output_kg`, `trim_waste_kg`, `other_waste_kg`, `net_weight_kg`) are numbers with exactly 3 decimal places. Percentages (`yield_pct_provisional`, `yield_pct_final`, `yield_variance_pct`, `duty_rate_pct`) and evaluation scores (`hazard_analysis_score`, `record_review_score`, `performance_score`, `overall_score`, `risk_score`) use 2 decimal places. All rounding is **round half up**.

Temperature values (`receiving_temp_c`, `core_temp_c`, `avg_temp_c`) are Celsius numbers at 1 decimal place. Duration accumulations (`cumulative_abuse_minutes`, freeze-protocol required minutes) are whole minutes.

Numeric fields submitted at finer precision than their class are rounded half-up to the class precision on write rather than rejected; monetary (integer-cents) fields must be submitted as integers.

### 2.6. Nested Resource Retrieval and Path Validation

The API enforces strict left-to-right validation for all requests that target nested resources. When an endpoint path contains a resource identifier (e.g., a supplier id, an import entry id, a receipt lot id), the system validates the existence of that identifier. The request is rejected immediately with a `404 Not Found` error carrying the resource-specific error ID corresponding to the *first* identifier that does not correspond to an existing resource. Body-referenced foreign keys are validated after path parameters.

### 2.7. Optimistic Concurrency Control

Two write endpoints require optimistic concurrency control via a version-pinning field:

- **Completing a ProcessingBatch** requires `expected_batch_version` in the request payload, carrying the client's last observed `version` of the batch. If the batch's current `version` does not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Completion computes yield from the batch's current input composition; an input addition the client has not observed (which itself bumps the batch version) makes the client's expected version stale.
- **Creating a SupplierEvaluation** requires `expected_supplier_version` in the request payload, carrying the client's last observed `version` of the ForeignSupplier. If the supplier's current `version` does not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A new evaluation legitimately re-derives the supplier's FSVP posture; another mutation landing in between (e.g., a suspend or a prior evaluation, each of which bumps the supplier version) makes the current writer's view stale.

Endpoints not listed above do not take a version field. On both endpoints the version comparison is the final check, applied only after all other validations have passed.

### 2.8. Validation Priority Ordering

When a request violates multiple rules, the system evaluates them in a fixed priority order. Lower-numbered checks run first. Authentication (headers present, role known) is checked before role authorization, which is checked before path-resource existence, which is checked before body-referenced foreign-key existence. Field-level validation (required fields, types, enum membership, numeric ranges) comes next — all field-level validation failures are rejected with `ERR_VALIDATION_FAILED` (HTTP 400) — followed by state-machine checks (target resource in a valid from-state), then domain-specific business rules in ascending priority order. The full ordering is expressed through the §3 narratives; each validation rule's trigger condition appears alongside the workflow it guards.

---

## 3. Business Logic & Workflows

### 3.1. Foreign Supplier Registration and FSVP Lifecycle

A `ComplianceManager` registers a new foreign supplier by providing `legal_name`, `country_code` (ISO 3166-1 alpha-2), and `facility_registration_number` (an FDA food facility registration number, unique across all suppliers; a duplicate registration number is rejected with `ERR_VALIDATION_FAILED`, HTTP 400). Optionally, the registration indicates whether the supplier `handles_histamine_susceptible_species` — a boolean defaulting to `false`. Upon creation, the supplier enters `PENDING_EVALUATION` status, its `risk_score` and `risk_tier` are null, `open_corrective_action_count` and lifetime counters (`total_species_mismatches`, `total_haccp_deviations`) are zeroed, and `last_evaluation_period_end` and `next_evaluation_due` are null. The `version` starts at 1.

The supplier's FSVP posture is driven by periodic evaluations recorded by a `ComplianceManager`. Each evaluation provides `supplier_id`, `period_start`, and `period_end` — the coverage window is a closed interval where both endpoints are inclusive, and `period_end` must be strictly after `period_start`. Three scores are submitted: `hazard_analysis_score`, `record_review_score`, and `performance_score`, each a number from 0 to 100. Each submitted score is rounded half-up to 2 decimal places on write, and the system computes `overall_score` from the rounded scores as the weighted sum: 50% of the hazard analysis score, 30% of the record review score, and 20% of the performance score, rounded half-up to 2 decimal places. The `outcome` is derived from the overall score: 70 or above yields `APPROVED`, 50 or above (but below 70) yields `CONDITIONAL`, and below 50 yields `REJECTED`. The `evaluated_by` field records the `X-User-ID` of the creating `ComplianceManager`.

Evaluation periods for the same supplier must not overlap. Because coverage windows are closed intervals, a new evaluation whose period intersects any existing evaluation's period — including sharing a boundary day — is rejected with `ERR_EVALUATION_PERIOD_OVERLAP` (HTTP 422).

The supplier's state machine responds to evaluation outcomes as follows. From `PENDING_EVALUATION`, an `APPROVED` outcome (score 70 or above) transitions the supplier to `APPROVED`, setting `last_evaluation_period_end` to the evaluation's `period_end`, recomputing `risk_score` and `risk_tier` (see §3.8), and setting `next_evaluation_due` to the period end plus the tier interval: 36 months for `LOW`, 12 months for `MODERATE`, 3 months for `HIGH`. A `REJECTED` outcome (score below 50) transitions to `REJECTED` (terminal), recomputing risk fields. A `CONDITIONAL` outcome (score 50 to below 70) leaves the supplier in `PENDING_EVALUATION` — conditional does not approve a never-approved supplier — while still recomputing risk fields and bumping the version.

From `APPROVED`, an `APPROVED` or `CONDITIONAL` outcome (score 50 or above) re-certifies the supplier in place (stays `APPROVED`), updating `last_evaluation_period_end`, recomputing risk fields, and setting `next_evaluation_due` to the new period end plus the tier interval. A `REJECTED` outcome from `APPROVED` transitions the supplier to `SUSPENDED`.

From `REEVALUATION_DUE`, an `APPROVED` or `CONDITIONAL` outcome restores the supplier to `APPROVED` with updated evaluation dates and risk fields. A `REJECTED` outcome moves to `SUSPENDED`.

From `SUSPENDED`, an `APPROVED` outcome (score 70 or above) restores the supplier to `APPROVED` with the full date and risk recomputation. Any other evaluation outcome submitted for a `SUSPENDED` supplier, and any evaluation submitted for a `REJECTED` supplier (terminal), is rejected with `ERR_INVALID_STATE` (HTTP 409). Transitions into `SUSPENDED` or `REJECTED` leave `last_evaluation_period_end` and `next_evaluation_due` unchanged.

A `ComplianceManager` may also directly suspend an `APPROVED` supplier via the suspend action, transitioning `fsvp_status` from `APPROVED` to `SUSPENDED` and incrementing the supplier version. Attempting to suspend a supplier that is not `APPROVED` is rejected with `ERR_INVALID_STATE` (HTTP 409). This blocks new prior notices and entry filings for that supplier.

A system sweep runs whenever the logical clock is set (see §3.12). Any `APPROVED` supplier whose `next_evaluation_due` is not null and is less than or equal to the current logical time transitions to `REEVALUATION_DUE`, incrementing the supplier version.

### 3.2. Import Entry Filing and FDA Disposition

An `ImportCoordinator` creates an import entry by providing `supplier_id`, `entry_number` (unique across all entries; a duplicate entry number is rejected with `ERR_VALIDATION_FAILED`, HTTP 400), `species_declared` (an uppercase token such as `TUNA`), `transport_mode` (one of `VESSEL`, `AIR`, `ROAD`), `scheduled_arrival`, `port_code`, `goods_value_cents` (must be greater than 0), `freight_cost_cents` (must be 0 or greater), `duty_rate_pct` (a decimal fraction of goods value, 0 or greater), and `total_weight_kg` (greater than 0). The entry starts in `DRAFT` status with `prior_notice_filed_at`, `prior_notice_confirmation`, and `entry_filed_at` all null; `duty_cents` and `allocatable_total_cents` likewise remain null until the entry reaches `RELEASED`.

Filing the FDA prior notice is the first step. The `ImportCoordinator` calls the prior-notice filing action. Preconditions: the entry must be in `DRAFT`, the referenced supplier must currently have `fsvp_status` equal to `APPROVED` (checked at the time of the call — a supplier suspended between entry creation and prior-notice filing blocks the operation with `ERR_SUPPLIER_NOT_APPROVED`, HTTP 422), and the current logical time must not be later than `scheduled_arrival` minus the lead time for the entry's `transport_mode`: 8 hours for `VESSEL`, 4 hours for `AIR`, 2 hours for `ROAD`. Equality passes — filing exactly at the deadline is allowed. A missed window is rejected with `ERR_PRIOR_NOTICE_WINDOW_MISSED` (HTTP 422). On success, the entry transitions to `PRIOR_NOTICE_FILED`, the system sets `prior_notice_filed_at` to the current logical time and mints a `prior_notice_confirmation` string of the form `PN` followed by 12 uppercase hexadecimal characters.

Next, the `ImportCoordinator` files the customs entry summary. The entry must be in `PRIOR_NOTICE_FILED`. Supplier approval is re-checked at this point: if the supplier has been suspended between prior notice and entry filing, the operation is rejected with `ERR_SUPPLIER_NOT_APPROVED`. On success, the entry transitions to `ENTRY_FILED` and `entry_filed_at` is set.

The FDA disposition is recorded by the `ImportCoordinator` with an `outcome` payload of `RELEASED`, `DETAINED`, or `REFUSED`. From `ENTRY_FILED`, all three outcomes are valid. `RELEASED` computes `duty_cents` as the goods value in cents multiplied by the duty rate, rounded half-up to integer cents, and `allocatable_total_cents` as the sum of goods value, freight cost, and duty. It then runs entry cost allocation (see §3.7) over the entry's `ACCEPTED` receipt lots. `DETAINED` and `REFUSED` are simpler transitions. From `DETAINED`, the entry may later be `RELEASED` (same computation and allocation as from `ENTRY_FILED`) or `REFUSED`. `REFUSED` and `RELEASED` are terminal states for the entry. A disposition call from `DRAFT` or `PRIOR_NOTICE_FILED`, any disposition call on a terminal entry, and a `DETAINED` outcome on an already-`DETAINED` entry are rejected with `ERR_INVALID_STATE` (HTTP 409).

Every entry mutation increments the ImportEntry version by 1.

### 3.3. Raw Material Receipt and Catch Documentation

Once an import entry reaches `RELEASED` status, a `ReceivingInspector` may receive raw-material lots against it. Receipt creation requires the import entry to be `RELEASED`; any other status is rejected with `ERR_ENTRY_NOT_RELEASED` (HTTP 409). The inspector provides `import_entry_id`, `vessel_name`, `harvest_date`, `catch_area_code` (FAO major fishing area), `harvest_country_code` (ISO country code, drives COOL labeling), `production_method` (`WILD` or `FARMED`), `species_declared`, `grade` (`A`, `B`, or `C`), `quantity_received_kg` (greater than 0), `receiving_temp_c`, and optionally `ice_deduction_pct` (0 to 50, defaults to 0) and `freeze_protocol` (one of `NONE`, `STANDARD`, `BLAST`, `COMBO`; defaults to `NONE`).

The system computes `quantity_accepted_kg` as the received quantity multiplied by one minus the ice deduction percentage divided by 100, rounded half-up to 3 decimal places. `remaining_kg` starts equal to `quantity_accepted_kg`; `consumed_kg` starts at 0. `cumulative_abuse_minutes` starts at 0, `freeze_compliant` starts at `false`, and `mislabel_flag` starts at `false`. `species_verified` starts null and `allocated_cost_cents` starts at 0. The lot enters `UNDER_INSPECTION` status.

### 3.4. Species Verification and Mislabeling Prevention

Before a lot can be accepted, a species verification must be performed. A `ReceivingInspector` records a verification by providing `receipt_lot_id`, `test_method` (`DNA_BARCODING` or `SENSORY`), `sample_size` (greater than 0), and `verified_species`. The lot must be in `UNDER_INSPECTION` or `QUARANTINED` status; a lot in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409).

The system computes `is_match` by comparing `verified_species` to the lot's `species_declared` at creation time. If they match, the verification enters `CONFIRMED` status, and the lot's `species_verified` is set to the verified species (bumping the lot's version). If they do not match, the verification enters `MISMATCH` status and a three-link cascade fires:

1. The lot transitions from `UNDER_INSPECTION` or `ACCEPTED` to `QUARANTINED` (if not already quarantined), incrementing the ReceiptLot version.
2. The quarantine entry auto-creates a CorrectiveAction with `source_type` `SPECIES_MISMATCH`, `receipt_lot_id` set to the lot, `supplier_id` traced through the lot's import entry to its supplier, `opened_by` set to the requesting `X-User-ID`, and `status` `OPEN`.
3. The CorrectiveAction creation increments the supplier's `open_corrective_action_count` by 1 and `total_species_mismatches` by 1, then recomputes the supplier's `risk_score` and `risk_tier` (see §3.8), incrementing the ForeignSupplier version.

A mismatch can be resolved by a `QualityAssuranceTech` providing a `resolution` of either `RELABEL_AS_VERIFIED` or `REJECT_LOT`. The verification must be in `MISMATCH` status and the lot must be `QUARANTINED`; violations are rejected with `ERR_INVALID_STATE` (HTTP 409). With `RELABEL_AS_VERIFIED`, the lot's `species_declared` is overwritten to the verified species, `species_verified` is set, and `mislabel_flag` is set to `true`. The verification transitions to `RESOLVED_RELABELED`. The lot remains `QUARANTINED` until the linked corrective action is resolved and quarantine-release is called. With `REJECT_LOT`, the lot transitions to `REJECTED` and the verification to `RESOLVED_REJECTED`. `CONFIRMED`, `RESOLVED_RELABELED`, and `RESOLVED_REJECTED` are all terminal for the verification.

### 3.5. Lot Acceptance, Quarantine, and Rejection Gates

Accepting a receipt lot is the most heavily gated operation in the system. A `ReceivingInspector` may accept a lot in `UNDER_INSPECTION` status — a lot in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409) — only when all of the following conditions are met simultaneously:

- A SpeciesVerification for this lot exists with status `CONFIRMED` or `RESOLVED_RELABELED`. Its absence is rejected with `ERR_VERIFICATION_REQUIRED` (HTTP 422).
- If the lot's `species_declared` is among the histamine-susceptible species (TUNA, MAHI_MAHI, MACKEREL, SARDINE, ANCHOVY, BLUEFISH), a HaccpMonitoringRecord with `hazard_type` `HISTAMINE` for this lot with `verdict` `PASS` must exist. Absence is rejected with `ERR_HISTAMINE_CRITICAL_LIMIT` (HTTP 422).
- The lot's `cumulative_abuse_minutes` must be strictly less than 240. At exactly 240 or above, acceptance is rejected with `ERR_TEMPERATURE_ABUSE_EXCEEDED` (HTTP 422).
- If the lot's `freeze_protocol` is not `NONE`, `freeze_compliant` must be `true`. Otherwise rejected with `ERR_FREEZE_PROTOCOL_NOT_MET` (HTTP 422).
- No CorrectiveAction linked to this lot may have status `OPEN` or `INVESTIGATING`. Violation yields `ERR_OPEN_CORRECTIVE_ACTIONS` (HTTP 422).

On acceptance, the lot transitions to `ACCEPTED` and the entry cost allocation runs over the entry's `ACCEPTED` lots — the newly accepted lot is now included (see §3.7).

A lot in `UNDER_INSPECTION` may be rejected outright by a `ReceivingInspector` providing a `reason`; the reason is accepted but not persisted on the lot. This transitions to `REJECTED` (terminal).

A `QualityAssuranceTech` may place a hold on a lot in `UNDER_INSPECTION` or `ACCEPTED` by providing a `reason` (accepted but not persisted on the lot), transitioning it to `QUARANTINED`; a lot in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). If the lot was previously `ACCEPTED`, the entry cost allocation re-runs with this lot now excluded from the eligible set.

Releasing a quarantined lot back to `ACCEPTED` is a `ComplianceManager` operation. The lot must be `QUARANTINED`, no linked CorrectiveAction may be `OPEN` or `INVESTIGATING` (`ERR_OPEN_CORRECTIVE_ACTIONS`), a SpeciesVerification with `CONFIRMED` or `RESOLVED_RELABELED` must exist (`ERR_VERIFICATION_REQUIRED`), the histamine PASS gate applies for susceptible species (`ERR_HISTAMINE_CRITICAL_LIMIT`), abuse minutes must be below 240 (`ERR_TEMPERATURE_ABUSE_EXCEEDED`), and freeze compliance must hold if applicable (`ERR_FREEZE_PROTOCOL_NOT_MET`). On release, the lot returns to `ACCEPTED` and cost allocation re-runs with the lot re-included.

A `QUARANTINED` lot may also be rejected by a `ReceivingInspector` providing a `reason`, or by mismatch resolution with `REJECT_LOT`. Both paths lead to `REJECTED`. Rejecting a lot in any other status (e.g., `ACCEPTED`, `CONSUMED`) is rejected with `ERR_INVALID_STATE` (HTTP 409).

When a lot's `remaining_kg` reaches exactly 0 after a batch input addition, the system auto-transitions the lot from `ACCEPTED` to `CONSUMED` (terminal), incrementing the lot version.

### 3.6. Processing Batches, Input Consumption, and Yield Reconciliation

A `ProcessingSupervisor` opens a processing batch by providing `target_species` and `product_form` (one of `FILLET`, `LOIN`, `PORTION`). The batch starts `IN_PROCESS` with `input_total_kg` and computed yield fields at zero or null.

Consuming raw material into the batch is done by adding batch input lots. The supervisor provides `receipt_lot_id` and `quantity_kg` (greater than 0, 3 decimal places). The batch must be `IN_PROCESS`; adding an input to a batch in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). The referenced lot must be in `ACCEPTED` status — otherwise `ERR_LOT_NOT_ACCEPTED` (HTTP 409). The species gate checks that the lot's effective species — `species_verified` if set, otherwise `species_declared` — equals the batch's `target_species`. A mismatch yields `ERR_SPECIES_MISMATCH` (HTTP 422). The quantity must not exceed the lot's `remaining_kg`; exceeding it yields `ERR_INSUFFICIENT_LOT_REMAINING` (HTTP 422).

On addition, the lot's `consumed_kg` increases by the input quantity and `remaining_kg` is recomputed as `quantity_accepted_kg` minus `consumed_kg`. If `remaining_kg` reaches exactly 0, the lot auto-transitions from `ACCEPTED` to `CONSUMED`. The batch's `input_total_kg` and `provisional_output_kg` are recomputed. Both the ReceiptLot and ProcessingBatch versions increment by 1.

Removing a batch input (a compensating action) is allowed while the batch is `IN_PROCESS`; against a batch in any other status it is rejected with `ERR_INVALID_STATE` (HTTP 409). The lot's `consumed_kg` decreases by the removed quantity. If the lot had been auto-consumed (`CONSUMED`) and its `remaining_kg` is now greater than 0, it transitions back to `ACCEPTED`. Batch totals are recomputed and both versions increment. The response returns the removed BatchInputLot row.

The provisional yield estimation runs on every input addition and removal. For each BatchInputLot row of the batch, the per-lot provisional contribution `provisional_yield_kg` is computed as: the input `quantity_kg` multiplied by the base yield factor for the batch's `product_form` (0.42 for `FILLET`, 0.55 for `LOIN`, 0.48 for `PORTION`), multiplied by the grade factor for the lot's `grade` (1.00 for `A`, 0.95 for `B`, 0.88 for `C`), with each per-lot contribution rounded half-up to 3 decimal places **first**. The batch's `provisional_output_kg` is then the sum of these individually rounded `provisional_yield_kg` values. Summing first and then rounding is forbidden — it produces different results. `input_total_kg` is the simple sum of all input quantities at 3 decimal places. `yield_pct_provisional` is 100 times the provisional output divided by the input total, rounded half-up to 2 decimal places.

Completing the batch is an OCC-gated operation (see §2.7). The supervisor provides `expected_batch_version`, `actual_output_kg`, `trim_waste_kg`, and `other_waste_kg`; the three measured values must each be 0 or greater. The batch must be `IN_PROCESS` and must have at least 1 input row — zero inputs yields `ERR_BATCH_HAS_NO_INPUTS` (HTTP 422). On completion, the system recomputes `input_total_kg`, `provisional_output_kg`, and `yield_pct_provisional`, then computes `yield_pct_final` as 100 times `actual_output_kg` divided by `input_total_kg`, rounded half-up to 2 decimal places, and `yield_variance_pct` as the final percentage minus the provisional percentage, rounded half-up to 2 decimal places. If the absolute value of `yield_variance_pct` exceeds 5.0, a CorrectiveAction is auto-created with `source_type` `YIELD_VARIANCE`, `processing_batch_id` set to the batch, `supplier_id` null, and `opened_by` set to the requesting `X-User-ID`. The batch transitions to `COMPLETED` and its version increments.

A `COMPLETED` batch may be reopened by a `ProcessingSupervisor` only if no FinishedProductLot of this batch has status `RELEASED` or `RECALLED`. Reopening transitions the batch back to `IN_PROCESS`; the recorded `actual_output_kg`, `trim_waste_kg`, `other_waste_kg`, and computed yield fields are retained. Reopening a batch that is not `COMPLETED`, or one with a `RELEASED`/`RECALLED` finished lot, is rejected with `ERR_INVALID_STATE` (HTTP 409).

Reconciling a `COMPLETED` batch locks it; reconciling a batch in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). The mass-balance invariant requires `input_total_kg` to exactly equal the sum of `actual_output_kg`, `trim_waste_kg`, and `other_waste_kg` — exact equality at 3 decimal places. Violation yields `ERR_MASS_IMBALANCE` (HTTP 422). If the absolute value of `yield_variance_pct` exceeds 5.0, a CorrectiveAction with `source_type` `YIELD_VARIANCE` for this batch with status `RESOLVED` must exist; otherwise `ERR_YIELD_VARIANCE_EXCEEDED` (HTTP 422). On reconciliation, the batch transitions to `RECONCILED` (terminal).

### 3.7. Entry Cost Allocation

Entry cost allocation is a waterfall algorithm that distributes an import entry's total allocatable cost across its eligible receipt lots. The `allocatable_total_cents` — computed when the entry reaches `RELEASED` as goods value plus freight plus duty — is distributed among the entry's ReceiptLot rows that have status `ACCEPTED`.

For each eligible lot, its share is the lot's `quantity_accepted_kg` divided by the sum of `quantity_accepted_kg` across all eligible lots, computed at full precision. The base allocation for each lot is the floor of the allocatable total multiplied by its share. The remainder — the allocatable total minus the sum of all floor values — is distributed one cent at a time to lots ordered by: share descending, then `quantity_accepted_kg` descending, then `created_at` ascending. The first `remainder` lots in this ordering each receive one additional cent.

The invariant is that the sum of `allocated_cost_cents` across all eligible lots must equal `allocatable_total_cents`. If the eligible set is empty, all allocations are 0.

Allocation re-runs on exactly four events: the entry reaching `RELEASED`, a lot's acceptance (`UNDER_INSPECTION` → `ACCEPTED`), a lot transitioning from `ACCEPTED` to `QUARANTINED`, and a quarantine release (`QUARANTINED` → `ACCEPTED`). Receipt-lot creation and the automatic `ACCEPTED` ↔ `CONSUMED` transitions on batch-input addition and removal do not re-run allocation. Each re-run fully recomputes from scratch; the eligible set changing re-allocates the same total over the new set, and every lot outside the eligible set carries `allocated_cost_cents` 0. Allocation updates `allocated_cost_cents` in place and does not increment the version of any lot.

### 3.8. Supplier Risk Scoring

The supplier risk score is a weighted composite that drives the FSVP evaluation cadence. It recomputes whenever: a SupplierEvaluation is created, a CorrectiveAction is opened, resolved, reopened, or escalated, a species mismatch occurs, or a HACCP deviation occurs.

The formula combines three components. The evaluation component is 100 minus the latest evaluation's `overall_score` (where "latest" is determined by `period_end`, with ties broken by `created_at` ascending); before the first evaluation, this component is 0 and `risk_score` is null. The open-penalty component is the supplier's `open_corrective_action_count` multiplied by 10, capped at 100. The history-penalty component is `total_species_mismatches` multiplied by 25 plus `total_haccp_deviations` multiplied by 15, capped at 100.

The counters are derived from the supplier's corrective actions: `open_corrective_action_count` counts supplier-linked corrective actions with status `OPEN` or `INVESTIGATING`, `total_species_mismatches` counts supplier-linked corrective actions with `source_type` `SPECIES_MISMATCH`, and `total_haccp_deviations` counts supplier-linked corrective actions with `source_type` `HISTAMINE_DEVIATION` or `TEMPERATURE_ABUSE` — a temperature-abuse event therefore also raises `total_haccp_deviations`.

The `risk_score` is 40% of the evaluation component plus 30% of the open penalty plus 30% of the history penalty, rounded half-up to 2 decimal places. The `risk_tier` is derived from the score: below 30 is `LOW`, 30 to below 70 is `MODERATE`, and 70 or above is `HIGH`. The boundary is inclusive — exactly 30.00 is `MODERATE`, exactly 70.00 is `HIGH`.

The tier drives the evaluation cadence: `LOW` requires re-evaluation every 36 months, `MODERATE` every 12 months, `HIGH` every 3 months. The `next_evaluation_due` is set to the evaluation's `period_end` plus this interval, with the day clamped to the last day of the resulting month when the period-end day does not exist in it.

### 3.9. Cold Chain Monitoring: Temperature Logs and Freeze Protocols

Temperature logs record thermal intervals for either a receipt lot or a processing batch — exactly one subject must be specified per log. Providing both `receipt_lot_id` and `processing_batch_id`, or neither, is rejected with `ERR_AMBIGUOUS_SUBJECT` (HTTP 400). The `ReceivingInspector` and `QualityAssuranceTech` roles may create temperature logs. Each log provides `interval_start`, `interval_end` (must be strictly after `interval_start`), `core_temp_c`, `avg_temp_c`, and `source` (`CONTINUOUS_MONITOR` or `MANUAL_PROBE`).

Temperature intervals for the same subject are half-open: the start is inclusive, the end is exclusive. A new interval that overlaps an existing interval for the same subject is rejected with `ERR_TEMPERATURE_INTERVAL_OVERLAP` (HTTP 422). Adjacency is allowed — a new interval whose start equals an existing interval's end is not an overlap.

For lots with a `freeze_protocol` other than `NONE`, the system accumulates qualifying minutes from the lot's temperature logs. The logs are ordered by `interval_start` ascending, with ties broken by `created_at` ascending. Only minutes where `core_temp_c` is at or below the protocol threshold count:

- `STANDARD`: threshold is -20.0 degrees Celsius; required accumulation is 10,080 minutes (168 hours).
- `BLAST`: threshold is -35.0 degrees Celsius; required accumulation is 900 minutes (15 hours).
- `COMBO`: two phases. Phase 1 requires at least 240 minutes (4 hours) with `core_temp_c` at or below -35.0. Phase 2 counts only intervals whose `interval_start` is at or after the end of the first interval that reached -35.0 or below; in those intervals, minutes with `core_temp_c` at or below -20.0 must total at least 1,440 minutes (24 hours). Both phases must pass.

Intervals above the threshold contribute 0 minutes — the accumulation pauses but does not reset. `freeze_compliant` becomes `true` once the required minutes are met. When `freeze_protocol` is `NONE`, `freeze_compliant` is meaningless.

For lots whose `species_declared` is among the histamine-susceptible species, the system tracks `cumulative_abuse_minutes`. For each temperature log of the lot, if `avg_temp_c` exceeds 4.4 degrees Celsius, the interval's duration in whole minutes contributes to the cumulative total; otherwise 0. The logs are ordered by `interval_start` ascending with ties by `created_at` ascending. When `cumulative_abuse_minutes` reaches or exceeds 240 and the lot is currently `UNDER_INSPECTION` or `ACCEPTED`, the system auto-creates a CorrectiveAction with `source_type` `TEMPERATURE_ABUSE` and `opened_by` set to the requesting `X-User-ID`, transitions the lot from `UNDER_INSPECTION` or `ACCEPTED` to `QUARANTINED`, and updates the supplier's counters and risk score. The boundary is inclusive: exactly 240 blocks acceptance. These recomputations update `cumulative_abuse_minutes` and `freeze_compliant` in place without incrementing the lot's version; the lot's version increments only when the abuse threshold crossing quarantines the lot.

### 3.10. HACCP Monitoring Records and Histamine/Parasite Control

A `QualityAssuranceTech` records HACCP monitoring results. Each record has a `hazard_type` (`HISTAMINE` or `PARASITE`) and a `phase` (`SCREENING` or `CONFIRMATORY`). The `hazard_type` enum is validated before the existence of any referenced subject. The subject pairing is strict: `HISTAMINE` records require a `receipt_lot_id` and forbid a `processing_batch_id`; `PARASITE` records require a `processing_batch_id` and forbid a `receipt_lot_id`. Violations yield `ERR_AMBIGUOUS_SUBJECT` (HTTP 400).

For `SCREENING` phase records, `measured_value` is required — it is the measured ppm for HISTAMINE or the parasite count for PARASITE. `subsample_values` is forbidden for `SCREENING`. `measured_value` and each subsample value are rounded half-up to 1 decimal place on write.

For `CONFIRMATORY` phase HISTAMINE records, `subsample_values` is required — an array of at least 3 subsample ppm values. `measured_value` is forbidden for `CONFIRMATORY`. Providing fewer than 3 subsamples yields `ERR_VALIDATION_FAILED` (HTTP 400). For `CONFIRMATORY` phase PARASITE records, both `measured_value` and `subsample_values` are forbidden (`ERR_VALIDATION_FAILED`, HTTP 400); with no measured value present, the record's verdict is `PASS`.

The verdict computation for HISTAMINE records follows two variants. In the **screening** variant, the verdict is `DEVIATION` if the measured value is 50.0 ppm or greater, otherwise `PASS`. In the **confirmatory** variant, the average of all subsample values is computed and rounded half-up to 2 decimal places. The verdict is `PASS` only if the rounded average is below 50.0 ppm **and** every individual subsample value is below 100.0 ppm. Otherwise it is `DEVIATION`. A lot can fail screening yet pass confirmatory — the two variants use different logic.

For PARASITE records, the verdict is `DEVIATION` if the measured value is 1 or greater, otherwise `PASS`.

When the verdict is `DEVIATION`, the system auto-creates a CorrectiveAction with `source_type` `HISTAMINE_DEVIATION`, `monitoring_record_id` set to the record, `receipt_lot_id` set to the record's lot, `supplier_id` traced through the lot's import entry, and `opened_by` set to the requesting `X-User-ID`. The lot transitions from `UNDER_INSPECTION` or `ACCEPTED` to `QUARANTINED`. The supplier's `total_haccp_deviations` increments by 1, `open_corrective_action_count` increments by 1, and the risk score and tier are recomputed. On `PASS`, the `corrective_action_id` on the monitoring record remains null. For `PARASITE` records the deviation corrective action is batch-linked instead: `processing_batch_id` is set to the record's batch, `receipt_lot_id` and `supplier_id` are null, no quarantine occurs, and supplier counters are unaffected.

The `measured_at` field is required and records when the measurement was taken.

### 3.11. Corrective Actions, Segregation of Duties, and Recalls

Corrective actions are the system's primary compliance tracking mechanism. They originate in two ways: auto-creation by system events (species mismatch, histamine deviation, temperature abuse, yield variance) or manual creation by a `ComplianceManager`. Manual creation requires `source_type` to be `MANUAL` and at least one of `receipt_lot_id` or `processing_batch_id` to be provided, along with a `reason`. Providing any other `source_type` for manual creation is rejected with `ERR_VALIDATION_FAILED` (HTTP 400). Provided subject ids must reference existing resources (`ERR_RECEIPT_LOT_NOT_FOUND` / `ERR_PROCESSING_BATCH_NOT_FOUND`, HTTP 404).

Auto-created corrective actions trace `supplier_id` through the linked lot's import entry when lot-linked; batch-only corrective actions (e.g., yield variance) have `supplier_id` null. The `opened_by` field records the `X-User-ID` of the request that caused the deviation. When a supplier-linked CA is created, the supplier's `open_corrective_action_count` increments by 1 and the risk score recomputes.

The CA lifecycle starts at `OPEN`. A `ComplianceManager` may move `OPEN` to `INVESTIGATING` via the investigate action. Investigating a corrective action in any status other than `OPEN` or `RESOLVED` is rejected with `ERR_INVALID_STATE` (HTTP 409). From `INVESTIGATING`, the resolve action transitions to `RESOLVED` — but only if the resolving `X-User-ID` differs from the CA's `opened_by` (segregation of duties). Violation yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Resolving a corrective action not in `INVESTIGATING` is rejected with `ERR_INVALID_STATE` (HTTP 409). The resolver provides a `resolution_note`; the system sets `closed_by` to the resolver's `X-User-ID`. On resolution of a supplier-linked CA, the supplier's `open_corrective_action_count` decrements by 1 and risk recomputes.

A `RESOLVED` CA may be reopened for re-audit via the investigate action, transitioning back to `INVESTIGATING`; the recorded `resolution_note` and `closed_by` are retained. On reopen from `RESOLVED`, the supplier's `open_corrective_action_count` increments by 1 and risk recomputes.

Escalation is available from both `OPEN` and `INVESTIGATING`; escalating a corrective action in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). The `ComplianceManager` provides a `reason` and a non-empty `scope_lot_ids` array of FinishedProductLot ids. Every scope lot must exist and must not already be `RECALLED`. Empty scope yields `ERR_VALIDATION_FAILED` (HTTP 400); a non-existent lot yields `ERR_FINISHED_LOT_NOT_FOUND` (HTTP 404); an already-recalled lot yields `ERR_INVALID_STATE` (HTTP 409). The `reason` and scope-shape validations run before scope-lot existence checks, which run before the corrective-action state check.

Escalation creates a Recall with `corrective_action_id` set to the CA, the provided `reason` and scope, and status `INITIATED`. The CA's `recall_id` is set to the new recall's id. Every in-scope FinishedProductLot with status not already `RECALLED` transitions to `RECALLED`, each incrementing its version. For supplier-linked CAs, `open_corrective_action_count` decrements by 1 (ESCALATED is no longer open) and risk recomputes. The CA transitions to `ESCALATED` (terminal). The escalate response returns the updated CorrectiveAction.

A `ComplianceManager` marks a recall as notified via the notify action, transitioning from `INITIATED` to `NOTIFIED` (terminal) and setting `notified_at` to the current logical clock, rendered as an ISO 8601 UTC timestamp with three fractional digits (e.g., `2026-08-01T00:00:00.000Z`). Notifying a recall not in `INITIATED` is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.12. Product Labeling, Allergen Declaration, and Country-of-Origin

A `ComplianceManager` drafts a product label by providing `market_name` (FDA acceptable market name), `scientific_name` (Latin binomial), `species` (species code this label may be applied to), `production_method` (`WILD` or `FARMED`), `country_of_origin` (COOL country declaration text), and optionally `keep_frozen_statement` (boolean, defaults to `false`) and `supersedes_label_id` (reference to an existing label for version chaining; an unknown id is rejected at creation with `ERR_PRODUCT_LABEL_NOT_FOUND`, HTTP 404). The `allergen_statement` is computed by the system as "Contains: Fish (" followed by the `market_name` followed by ")" — any input for this field is ignored. The label starts in `DRAFT` status with `approved_at` null.

Approving a label requires the label to be in `DRAFT`; approving a label in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). If `supersedes_label_id` is provided, the referenced label must exist and have status `APPROVED`; otherwise the approval is rejected with `ERR_INVALID_STATE` (HTTP 409). On approval, the label transitions to `APPROVED`, `approved_at` is set to the current logical time, and the label version increments. If superseding, the referenced label transitions to `SUPERSEDED` (terminal) and its version increments. Every FinishedProductLot pinned to the superseded label has its `label_stale` set to `true` and its version incremented — this is the mechanism by which label changes propagate to finished inventory.

A `ProcessingSupervisor` creates a finished product lot from a batch by providing `processing_batch_id` and `net_weight_kg` (greater than 0, 3 decimals). The batch must be `COMPLETED` or `RECONCILED`; otherwise the creation is rejected with `ERR_INVALID_STATE` (HTTP 409). The sum of `net_weight_kg` across all of the batch's finished lots must not exceed the batch's `actual_output_kg` — equality is allowed. Exceeding it yields `ERR_FINISHED_WEIGHT_EXCEEDS_OUTPUT` (HTTP 422). The finished lot starts `UNLABELED` with `product_label_id`, `label_version_pinned`, `allergen_statement`, `country_of_origin`, and `released_at` null and `label_stale` false.

Applying a label to an `UNLABELED` finished lot transitions it to `LABELED`. The label must be `APPROVED` (`ERR_LABEL_NOT_APPROVED`, HTTP 409) and its `species` must equal the batch's `target_species` (a species mismatch yields `ERR_SPECIES_MISMATCH`, HTTP 422). On application, the system sets `product_label_id` to the label's id, pins `label_version_pinned` to the label's current `version` (version pinning), sets `label_stale` to `false`, copies `allergen_statement` from the label, and computes `country_of_origin` from the batch's input lots: if all input lots share the same `harvest_country_code`, that code is used; otherwise the value is "MIXED:" followed by the distinct codes sorted in ascending order joined by "+".

Re-applying a label to a `LABELED` lot is possible only when `label_stale` is `true` — meaning the pinned label was superseded. The new label must be `APPROVED` and its species must match the batch target. Re-application re-pins `product_label_id` and `label_version_pinned` to the new label's version, clears `label_stale` to `false`, and refreshes `allergen_statement` and `country_of_origin`. Applying a label to a lot in any other state — a `LABELED` lot whose label is not stale, or a `RELEASED`/`RECALLED` lot — is rejected with `ERR_INVALID_STATE` (HTTP 409).

Releasing a finished lot for commerce is a `ComplianceManager` operation. The lot must be `LABELED` (otherwise `ERR_INVALID_STATE`, HTTP 409), the batch must be `RECONCILED` (a batch not yet reconciled yields `ERR_INVALID_STATE`, HTTP 409), `label_stale` must be `false` (a stale label yields `ERR_LABEL_STALE`, HTTP 409), the pinned label must currently be `APPROVED` (otherwise `ERR_LABEL_NOT_APPROVED`, HTTP 409), and no CorrectiveAction linked to the batch may be `OPEN` or `INVESTIGATING` (`ERR_OPEN_CORRECTIVE_ACTIONS`, HTTP 422). On release, `released_at` is set and the lot transitions to `RELEASED`.

Recall creation (via CA escalation, see §3.11) transitions every in-scope finished lot — regardless of whether it was `UNLABELED`, `LABELED`, or `RELEASED` — to `RECALLED` (terminal).

### 3.13. Logical Clock and Time-Driven Sweep

A `PlatformAdmin` controls the system's logical clock via a test-driving capability that sets the current UTC time to a supplied `to_iso8601` instant. The startup default — before any call — is exactly 2026-08-01T00:00:00Z; the server must not fall back to wall-clock time. Setting the clock triggers a supplier sweep: every `APPROVED` supplier whose `next_evaluation_due` is not null and is less than or equal to the new current time transitions to `REEVALUATION_DUE`, incrementing the supplier version. The response returns an object carrying `current_utc` set to the new logical time; a missing or malformed `to_iso8601` is rejected with `ERR_VALIDATION_FAILED` (HTTP 400).

---

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (e.g., a ForeignSupplier, ImportEntry, ReceiptLot, SpeciesVerification, ProcessingBatch, TemperatureLog, HaccpMonitoringRecord, CorrectiveAction, ProductLabel, FinishedProductLot, SupplierEvaluation, BatchInputLot) return a `201 Created` status code. Operations that modify an existing resource (e.g., accept, reject, quarantine, apply-label, release, file-prior-notice, complete, reconcile, investigate, resolve, escalate, approve, notify, suspend, fda-disposition, reopen, quarantine-release, resolve-verification, set clock) return a `200 OK` status code. Deleting a batch input lot returns `200 OK`. All list and fetch endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------- |
| POST | `/seafood/suppliers` | Register a foreign supplier | ComplianceManager |
| GET | `/seafood/suppliers/{id}` | Fetch one supplier with computed risk fields | Any |
| POST | `/seafood/suppliers/{id}/suspend` | Suspend an APPROVED supplier | ComplianceManager |
| POST | `/seafood/supplier-evaluations` | Record a periodic FSVP evaluation (OCC on supplier version) | ComplianceManager |
| GET | `/seafood/supplier-evaluations/{id}` | Fetch one evaluation | Any |
| GET | `/seafood/supplier-evaluations` | List evaluations; filter by `supplier_id`; paginated | Any |
| POST | `/seafood/import-entries` | Create an import entry in DRAFT | ImportCoordinator |
| GET | `/seafood/import-entries/{id}` | Fetch one entry with computed duty/allocation totals | Any |
| GET | `/seafood/import-entries` | List entries; filter by `supplier_id` and/or `status`; paginated | Any |
| POST | `/seafood/import-entries/{id}/file-prior-notice` | File FDA prior notice (supplier APPROVED; lead-time window) | ImportCoordinator |
| POST | `/seafood/import-entries/{id}/file-entry` | File the customs entry summary (supplier approval re-checked) | ImportCoordinator |
| POST | `/seafood/import-entries/{id}/fda-disposition` | Record FDA disposition: RELEASED, DETAINED, or REFUSED | ImportCoordinator |
| POST | `/seafood/receipt-lots` | Receive a raw-material lot against a RELEASED entry | ReceivingInspector |
| GET | `/seafood/receipt-lots/{id}` | Fetch one lot with computed cold-chain/yield/allocation fields | Any |
| GET | `/seafood/receipt-lots` | List lots; filter by `import_entry_id` and/or `status`; paginated | Any |
| POST | `/seafood/receipt-lots/{id}/accept` | Accept a lot after inspection (all gates) | ReceivingInspector |
| POST | `/seafood/receipt-lots/{id}/reject` | Reject a lot | ReceivingInspector |
| POST | `/seafood/receipt-lots/{id}/quarantine` | Place a hold on a lot | QualityAssuranceTech |
| POST | `/seafood/receipt-lots/{id}/quarantine-release` | Release a quarantined lot to ACCEPTED | ComplianceManager |
| POST | `/seafood/species-verifications` | Record a species verification result | ReceivingInspector |
| GET | `/seafood/species-verifications/{id}` | Fetch one verification | Any |
| GET | `/seafood/species-verifications` | List verifications; filter by `receipt_lot_id`; paginated | Any |
| POST | `/seafood/species-verifications/{id}/resolve` | Resolve a mismatch: RELABEL_AS_VERIFIED or REJECT_LOT | QualityAssuranceTech |
| POST | `/seafood/processing-batches` | Open a processing batch | ProcessingSupervisor |
| GET | `/seafood/processing-batches/{id}` | Fetch one batch with computed yield fields | Any |
| POST | `/seafood/processing-batches/{id}/inputs` | Consume kg from an ACCEPTED lot into the batch | ProcessingSupervisor |
| DELETE | `/seafood/batch-input-lots/{id}` | Remove a batch input (compensating action) | ProcessingSupervisor |
| GET | `/seafood/batch-input-lots/{id}` | Fetch one batch input row | Any |
| GET | `/seafood/batch-input-lots` | List batch input rows; filter by `processing_batch_id` and/or `receipt_lot_id`; paginated | Any |
| POST | `/seafood/processing-batches/{id}/complete` | Complete the batch with measured output/waste (OCC) | ProcessingSupervisor |
| POST | `/seafood/processing-batches/{id}/reopen` | Reopen a COMPLETED batch for rework | ProcessingSupervisor |
| POST | `/seafood/processing-batches/{id}/reconcile` | Lock the batch (mass balance + variance gates) | ProcessingSupervisor |
| POST | `/seafood/temperature-logs` | Append a temperature interval | ReceivingInspector, QualityAssuranceTech |
| GET | `/seafood/temperature-logs/{id}` | Fetch one temperature log | Any |
| GET | `/seafood/temperature-logs` | List temperature logs; filter by `receipt_lot_id` and/or `processing_batch_id`; paginated | Any |
| POST | `/seafood/haccp-monitoring-records` | Record a CCP monitoring result | QualityAssuranceTech |
| GET | `/seafood/haccp-monitoring-records/{id}` | Fetch one monitoring record | Any |
| GET | `/seafood/haccp-monitoring-records` | List monitoring records; filter by `receipt_lot_id`, `processing_batch_id`, `hazard_type`, `corrective_action_id`; paginated | Any |
| POST | `/seafood/corrective-actions` | Manually open a corrective action | ComplianceManager |
| GET | `/seafood/corrective-actions/{id}` | Fetch one corrective action | Any |
| GET | `/seafood/corrective-actions` | List corrective actions; filter by `supplier_id`, `receipt_lot_id`, `processing_batch_id`, `monitoring_record_id`, `recall_id`, `status`; paginated | Any |
| POST | `/seafood/corrective-actions/{id}/investigate` | Move OPEN to INVESTIGATING; reopens RESOLVED | ComplianceManager |
| POST | `/seafood/corrective-actions/{id}/resolve` | Resolve an INVESTIGATING CA (segregation of duties) | ComplianceManager |
| POST | `/seafood/corrective-actions/{id}/escalate` | Escalate a CA to a recall | ComplianceManager |
| POST | `/seafood/product-labels` | Draft a product label | ComplianceManager |
| GET | `/seafood/product-labels/{id}` | Fetch one label | Any |
| GET | `/seafood/product-labels` | List labels; filter by `supersedes_label_id` and/or `status`; paginated | Any |
| POST | `/seafood/product-labels/{id}/approve` | Approve a DRAFT label; supersedes referenced label | ComplianceManager |
| POST | `/seafood/finished-product-lots` | Create a packed finished lot from a batch | ProcessingSupervisor |
| GET | `/seafood/finished-product-lots/{id}` | Fetch one finished lot | Any |
| GET | `/seafood/finished-product-lots` | List finished lots; filter by `processing_batch_id`, `product_label_id`, `status`; paginated | Any |
| POST | `/seafood/finished-product-lots/{id}/apply-label` | Apply or re-apply an APPROVED label | ProcessingSupervisor |
| POST | `/seafood/finished-product-lots/{id}/release` | Release a labeled lot for commerce | ComplianceManager |
| GET | `/seafood/recalls/{id}` | Fetch one recall | Any |
| GET | `/seafood/recalls` | List recalls; filter by `corrective_action_id`; paginated | Any |
| POST | `/seafood/recalls/{id}/notify` | Mark the recall as notified | ComplianceManager |
| POST | `/_clock/set_current_utc` | Set the logical clock and run supplier sweep | PlatformAdmin |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_VALIDATION_FAILED` | 400 |
| `ERR_SUPPLIER_NOT_FOUND` | 404 |
| `ERR_IMPORT_ENTRY_NOT_FOUND` | 404 |
| `ERR_RECEIPT_LOT_NOT_FOUND` | 404 |
| `ERR_PROCESSING_BATCH_NOT_FOUND` | 404 |
| `ERR_BATCH_INPUT_NOT_FOUND` | 404 |
| `ERR_SPECIES_VERIFICATION_NOT_FOUND` | 404 |
| `ERR_PRODUCT_LABEL_NOT_FOUND` | 404 |
| `ERR_FINISHED_LOT_NOT_FOUND` | 404 |
| `ERR_CORRECTIVE_ACTION_NOT_FOUND` | 404 |
| `ERR_RECALL_NOT_FOUND` | 404 |
| `ERR_EVALUATION_NOT_FOUND` | 404 |
| `ERR_TEMPERATURE_LOG_NOT_FOUND` | 404 |
| `ERR_HACCP_RECORD_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INTERNAL` | 500 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ENTRY_NOT_RELEASED` | 409 |
| `ERR_LOT_NOT_ACCEPTED` | 409 |
| `ERR_SUPPLIER_NOT_APPROVED` | 422 |
| `ERR_PRIOR_NOTICE_WINDOW_MISSED` | 422 |
| `ERR_EVALUATION_PERIOD_OVERLAP` | 422 |
| `ERR_TEMPERATURE_INTERVAL_OVERLAP` | 422 |
| `ERR_AMBIGUOUS_SUBJECT` | 400 |
| `ERR_HISTAMINE_CRITICAL_LIMIT` | 422 |
| `ERR_TEMPERATURE_ABUSE_EXCEEDED` | 422 |
| `ERR_FREEZE_PROTOCOL_NOT_MET` | 422 |
| `ERR_SPECIES_MISMATCH` | 422 |
| `ERR_LABEL_NOT_APPROVED` | 409 |
| `ERR_LABEL_STALE` | 409 |
| `ERR_OPEN_CORRECTIVE_ACTIONS` | 422 |
| `ERR_VERIFICATION_REQUIRED` | 422 |
| `ERR_INSUFFICIENT_LOT_REMAINING` | 422 |
| `ERR_BATCH_HAS_NO_INPUTS` | 422 |
| `ERR_MASS_IMBALANCE` | 422 |
| `ERR_YIELD_VARIANCE_EXCEEDED` | 422 |
| `ERR_FINISHED_WEIGHT_EXCEEDS_OUTPUT` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
