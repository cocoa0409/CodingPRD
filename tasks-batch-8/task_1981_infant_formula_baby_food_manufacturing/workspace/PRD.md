# Infant Formula & Baby Food Manufacturing API — Product Requirements Document

## 1. Introduction

Infant formula and baby food manufacturing is one of the most tightly regulated food production domains in the world. A single nutrient deviation, an unqualified supplier, or an inadequately validated thermal process can result in product that harms infants — and a single delayed recall can turn a contained quality incident into a public health emergency. The Infant Formula & Baby Food Manufacturing API exists to make those failures structurally impossible: it encodes, as enforceable workflow constraints, the regulatory scaffolding that a compliant manufacturer must operate under — nutrient profile registration against codified standards, supplier qualification and re-audit, process validation for dry-blend and wet-process lines, positive-release batch testing, label review, complaint and adverse-event escalation, recall execution with effectiveness verification, and fair allocation of scarce inventory during shortage periods.

The system is built for a cross-functional team — regulatory affairs specialists, quality assurance managers, quality analysts, production supervisors, supply chain planners, and complaint handlers — each of whom owns a distinct slice of the lifecycle, and none of whom can bypass the segregation-of-duties gates that the regulation demands. Every state transition is auditable, every calculation is deterministic, and every cross-entity cascade (a suspended supplier quarantining their lots, a recalled batch flipping out of `RELEASED`, an allocation plan fulfilling its entries) is performed by the system rather than left as an operator burden. This document is the complete product specification for that API.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contract that applies uniformly to every endpoint the API exposes. All endpoints are mounted under the `/api/v1` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which they act. If either header is missing, empty, or contains a role value the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not authorized for the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly seven roles: `ADMIN`, `REGULATORY_AFFAIRS`, `QA_MANAGER`, `QUALITY_ANALYST`, `PRODUCTION_SUPERVISOR`, `SUPPLY_CHAIN_PLANNER`, and `COMPLAINT_HANDLER`. The binding between `X-User-ID` and the persisted data model differs by role:

- When `X-User-Role` is `ADMIN`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, on administrative actions) but does not compare it to any entity's `id`.
- When `X-User-Role` is `REGULATORY_AFFAIRS`, `QA_MANAGER`, `QUALITY_ANALYST`, `PRODUCTION_SUPERVISOR`, `SUPPLY_CHAIN_PLANNER`, or `COMPLAINT_HANDLER`, `X-User-ID` is the `id` of the acting `SystemUser`. Segregation-of-duties checks compare the resource's recorded prior actor (for example, the user who submitted a nutrient profile or who submitted batch test results) against the `X-User-ID` presented on the approval or release call; the role name alone is not sufficient for those checks.

A `SystemUser` resource stores `username` (unique), `full_name`, `role`, and `department`. Only an `ADMIN` may create new `SystemUser` records.

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

List endpoints accept two optional query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip before returning results and defaults to 0.

Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. List responses include four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary entity in the system — `NutrientProfile`, `Supplier`, `AuditRecord`, `Ingredient`, `IngredientLot`, `Formula`, `ProductionBatch`, `ProcessValidation`, `LabelSubmission`, `Complaint`, `RecallCampaign`, `RecallScope`, `AllocationPlan`, and `AllocationEntry` — carries the following system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): a system-managed integer that increments by one on every mutation, including system-driven state transitions and cascades.

The `SystemUser` entity is the sole exception to this convention: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from `SystemUser` records.

### 2.5. Precision, Rounding, and Quantity Discipline

The system maintains three distinct precision regimes, and the regime that applies is determined by the kind of quantity being manipulated:

- Kilogram quantities (such as `quantity_kg`, `batch_size_kg`, `actual_yield_kg`, `total_available_kg`, `requested_kg`, `allocated_kg`, `fulfilled_kg`, `quantity_shipped_kg`, `quantity_recovered_kg`, `remaining_kg`, and `recovered_kg`) are stored and computed to exactly 3 decimal places. Allocation arithmetic **truncates** intermediate results down to 3 decimal places (floor semantics) rather than rounding — surplus kilograms are never manufactured by rounding. The primitive step of allocation is one milligram — 0.001 kg.
- Nutrient concentrations measured per 100 kilocalories (`measured_per_100kcal`, `min_per_100kcal`, `max_per_100kcal`, `target_per_100kcal`) are stored to 4 decimal places and rounded half-up when a rounding step is required.
- Percentages and scores (`recovery_pct`, audit `score`, intermediate recency factors, and the audit score's pass/fail thresholds) are stored to 2 decimal places and rounded half-up.

Calendar-month arithmetic is used wherever shelf-life is computed: adding N months means N calendar months, not N × 30 days.

### 2.6. Optimistic Concurrency Control

Two write endpoints require an explicit optimistic-concurrency field carrying the caller's last observed `version` of the relevant parent entity. The server compares the submitted value against the parent's current `version` and rejects the request with `ERR_STALE_VERSION` (HTTP 412) on mismatch:

- Creating a new production batch requires the request body to include `expected_formula_version`, matching the current `version` of the `Formula` referenced by `formula_id`. This prevents a stale write against a formula whose composition or process type has been edited since the client last read it.
- Activating an allocation plan requires the request body to include `expected_plan_version`, matching the current `version` of the target `AllocationPlan`. Because adding or removing an entry increments the plan's `version`, this prevents activating a plan whose entry list has changed since the client last read it.

Endpoints not listed above do not take a version field; optimistic concurrency is opt-in only on these two writes.

### 2.7. Hierarchical Consistency and Cascading State Transitions

The system maintains consistency across parent–child relationships through automatic cascades. When a parent's lifecycle transitions in a way that invalidates a child's current state, the cascade happens immediately and atomically, and every affected resource has its `version` incremented and `updated_at` refreshed. Four cascades are central to the domain:

1. **Supplier suspension and disqualification cascade onto ingredient lots.** Suspending a `QUALIFIED` supplier flips every lot from that supplier currently in `QC_PASSED` to `QUARANTINED`. Disqualifying a supplier (from either `PENDING_AUDIT` or `SUSPENDED`) flips every lot from that supplier not already in `QC_FAILED` to `QC_FAILED`. Reinstating a `SUSPENDED` supplier flips every lot from that supplier currently in `QUARANTINED` back to `QC_PASSED`.
2. **Recall scope creation cascades onto batches.** Adding a `RecallScope` entry to a campaign transitions the referenced `ProductionBatch` from `RELEASED` to `RECALLED`. Terminating a campaign reverses that cascade: every batch in scope is restored from `RECALLED` to `RELEASED`.
3. **Recall campaign lifecycle cascades onto scope entries.** Notifying a campaign flips all scope entries from `PENDING` to `NOTIFIED`; beginning recovery flips them from `NOTIFIED` to `IN_PROGRESS`; terminating a campaign marks every scope entry `VERIFIED` regardless of prior status.
4. **Allocation entry mutation cascades onto plan version.** Every entry added to a plan increments the plan's `version` by one, which is what the plan-activation OCC check (§2.6) protects against.

When a state-machine transition is invoked against a resource that is not in a state from which that transition is defined, the request is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 2.8. Nested Resource Retrieval and Validation Ordering

Wherever an endpoint path nests one resource inside another (for example, an audit under a supplier, a scope under a campaign, an entry under a plan, a list of batches under a formula), the path parameters are validated left-to-right: the parent identifier is resolved first, and only if it exists does the system resolve the child identifier. A failure at any level is rejected with `ERR_NOT_FOUND` (HTTP 404). The same `ERR_NOT_FOUND` applies when a foreign-key field in the request body — `formula_id`, `nutrient_profile_id`, `ingredient_id`, `supplier_id`, `plan_id`, `recall_id`, `batch_id`, `product_formula_id`, `reviewer_id`, `audit_record_id` — references a resource that does not exist.

Validation is applied in a fixed priority order across all endpoints. Authentication (presence and recognizability of headers) is checked first, then authorization (role-to-endpoint permission), then path-parameter existence, then foreign-key existence in the body, then state-machine validity, then segregation-of-duties and domain safety rules (lot QC, supplier qualification, validation currency, lot expiry, escalation warrant, batch test outcome), then business constraints (uniqueness, percentage sums, nutrient ranges, audit age, fulfillment-versus-allocation, recall recovery thresholds, completeness of test results, label approval, active-batch blocking), and finally field shape rules (required-field presence, enum membership, numeric range) with the OCC version check applied immediately before write commit. Because authentication and path-existence checks run before any business check, a missing resource always surfaces as `ERR_NOT_FOUND` rather than being masked by a later rule failure.

### 2.9. The Logical Clock

All time-dependent logic — audit-age checks, validation expiry, lot expiry, shelf-life computation, risk-rating recency decay — reads from a single logical clock rather than from the host's wall clock. Before any operator intervention the logical clock is initialized to `2026-08-01T00:00:00Z`. An `ADMIN` may advance the clock to a supplied instant via the `to_iso8601` parameter of the test-driving endpoint; from that call onward, every time-dependent calculation treats the new instant as "now". The endpoint returns the current logical time as `current_utc`.

## 3. Business Logic & Workflows

### 3.1. Nutrient Profiles and the Regulatory Baseline

The regulatory starting point for every product is a `NutrientProfile` — a versioned set of nutritional min/max/target bounds anchored to a specific regulation. Each profile is identified by a `profile_code` drawn from a fixed codified set: `INF-0-6M` (infant formula, birth to 6 months), `INF-6-12M` (follow-on formula, 6–12 months), `TODDLER-12-36M`, `CEREAL-6M`, and `PUREE-4M`. The `profile_code` is unique across the system; an attempt to create a profile with a `profile_code` already in use is rejected with `ERR_DUPLICATE_CODE` (HTTP 409). A profile carries `regulation_ref` (for example, `21 CFR 107.100` or `EU 2016/127`), `effective_from`, an optional `effective_until` that is `null` while the profile is currently effective, and a `nutrient_specs` array. Each entry in `nutrient_specs` names a `nutrient_code` from the recognized codex list, a `unit`, and three numeric bounds: `min_per_100kcal`, `max_per_100kcal`, and `target_per_100kcal`. At least one nutrient spec is required.

A new profile starts in `DRAFT`. A `REGULATORY_AFFAIRS` operator submits it for approval, transitioning `DRAFT → SUBMITTED`; at this step the server enforces three structural rules in order. First, the `nutrient_specs` array must be non-empty. Second, for every spec the minimum must not exceed the maximum. Third, for every spec the target must lie within the closed interval from minimum to maximum. A violation of either numeric rule is rejected with `ERR_NUTRIENT_RANGE_INVALID` (HTTP 422). From `SUBMITTED`, a `REGULATORY_AFFAIRS` approver — necessarily a different `SystemUser` from the one who submitted, otherwise the request fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) — may transition the profile to `APPROVED`. At that moment two side effects occur: if `effective_from` was not already set, it is set to the current logical timestamp; and any other currently `APPROVED` profile carrying the same `profile_code` is automatically transitioned to `SUPERSEDED` with its `effective_until` set to the newer profile's `effective_from`. A submitted profile may instead be returned to `DRAFT` via the return-for-revision action with no preconditions. A profile in either `DRAFT` or `APPROVED` may be withdrawn to the terminal `WITHDRAWN` state; withdrawal from `APPROVED` is refused if any `Formula` currently in `ACTIVE` status references the profile — such a withdrawal has no separate error code and is surfaced as `ERR_INVALID_STATE`. The terminal states for a profile are `SUPERSEDED` and `WITHDRAWN`. Every transition increments the profile's `version`.

### 3.2. Suppliers, Audits, and Ingredient Lots

A `Supplier` is created by a `QA_MANAGER` with a unique `supplier_code` (max 32 characters), the supplier's `legal_name`, a non-empty `ingredient_categories` list drawn from the domain's category vocabulary, and an `audit_frequency_days` integer between 30 and 730 inclusive. New suppliers begin in `PENDING_AUDIT`. The supplier's `risk_rating` is a computed field starting at `HIGH`; `last_audit_date` is `null` until the first passing audit; `next_audit_due` is `null` while the supplier is not `QUALIFIED`.

A `QUALITY_ANALYST` files an `AuditRecord` against a supplier by supplying `audit_type` (one of `INITIAL`, `SURVEILLANCE`, `FOR_CAUSE`, `RE_QUALIFICATION`), `audit_date`, `auditor_name`, a numeric `score` between 0 and 100 with 2 decimal places, an optional `findings` array (each finding carrying `finding_code`, `severity`, `description`, and a `capa_required` flag), and an optional `capa_deadline` when any finding requires corrective action. The audit's `result` is computed from the score and findings in this exact order: any finding with `severity` equal to `CRITICAL` yields `FAIL`; otherwise a score strictly below 50.00 yields `FAIL`; otherwise the presence of any `MAJOR` finding, or a score strictly below 75.00, yields `CONDITIONAL_PASS`; otherwise the result is `PASS`. An audit whose `audit_date` is more than 365 days in the past relative to the logical clock cannot qualify a supplier and is rejected with `ERR_AUDIT_TOO_OLD` (HTTP 422).

When a submitted audit's computed result is `PASS` or `CONDITIONAL_PASS` and the supplier is currently `PENDING_AUDIT`, the supplier automatically transitions `PENDING_AUDIT → QUALIFIED`. On that transition the supplier's `last_audit_date` is set to the audit's `audit_date`, `next_audit_due` is computed as `last_audit_date + audit_frequency_days` (calendar days), and the `risk_rating` is recomputed.

The risk-rating recomputation works as follows. Let `days_since_audit` be the number of days (a real number) between the current logical timestamp and the most recent passing audit's `audit_date`. The recency factor is the greater of 0.5 and the value obtained by subtracting `days_since_audit / 730` from 1.0 — that is, the recency contribution decays linearly from 1.0 toward 0.5 over a 730-day horizon and never falls below 0.5. The adjusted score is the audit `score` multiplied by the recency factor, rounded half-up to 2 decimal places. An adjusted score of 80 or higher yields `risk_rating` `LOW`; an adjusted score of 60 or higher but below 80 yields `MEDIUM`; anything below 60 yields `HIGH`. This recomputation also fires whenever a new audit is submitted for an already-`QUALIFIED` supplier.

A `QUALITY_ANALYST` may suspend a `QUALIFIED` supplier by providing a `reason`; the supplier's `qualification_status` transitions `QUALIFIED → SUSPENDED` and the cascade of §2.7 immediately quarantines every `QC_PASSED` lot from that supplier. Reinstatement requires that a new `AuditRecord` with `result` equal to `PASS` (not `CONDITIONAL_PASS`) has been submitted after the suspension date; the analyst supplies the `audit_record_id` of that new audit, the supplier transitions `SUSPENDED → QUALIFIED`, and the cascade flips every `QUARANTINED` lot from that supplier back to `QC_PASSED`. A `QA_MANAGER` may disqualify a supplier from either `PENDING_AUDIT` or `SUSPENDED` by supplying a `rationale`; the supplier moves to the terminal `DISQUALIFIED` state, and — when disqualifying from `SUSPENDED` — every lot from that supplier not already in `QC_FAILED` is cascaded to `QC_FAILED`.

The ingredients a supplier may furnish come from a closed category vocabulary: `DAIRY_BASE`, `VEGETABLE_OIL`, `VITAMIN_PREMIX`, `MINERAL_PREMIX`, `PROBIOTIC`, `CARBOHYDRATE`, `NUCLEOTIDE`, `OTHER`. An `Ingredient` record is created by a `QA_MANAGER` with a unique `ingredient_code`, a human-readable `ingredient_name`, a `category` from that same vocabulary, a `pathogen_risk_class` of `HIGH_RISK`, `MEDIUM_RISK`, or `LOW_RISK`, a `storage_condition` of `AMBIENT`, `REFRIGERATED`, `FROZEN`, or `CONTROLLED_HUMIDITY`, and an optional `allergen_flags` list (for example, `MILK`, `SOY`, `GLUTEN`) defaulting to empty.

Physical stock arrives as `IngredientLot` records, created by a `SUPPLY_CHAIN_PLANNER`. A lot references its `ingredient_id` and `supplier_id`, carries the supplier-assigned `lot_number` (unique per ingredient-and-supplier pair), the `quantity_kg` received (3 decimal places, strictly positive), the `received_date`, and the `expiry_date` after which the lot may not be used. Lots begin in `PENDING_QC`. The system tracks `remaining_kg` separately from `quantity_kg`: `remaining_kg` starts equal to `quantity_kg`, is decremented as production consumes the lot, and is restored if a consuming batch is later rejected.

A `QUALITY_ANALYST` transitions a lot from `PENDING_QC` to `QC_PASSED` via the QC-pass action; this transition is refused with `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 422) if the lot's supplier is not currently `QUALIFIED`, with `ERR_LOT_EXPIRED` (HTTP 422) if the lot's `expiry_date` is not strictly after the current logical timestamp, and with `ERR_INVALID_STATE` if any recall campaign is active against the lot. The QC-fail action moves the lot from `PENDING_QC` to `QC_FAILED` and requires a `failure_reason` in the body. Two explicit actions mirror the supplier-driven cascades: an analyst may move a lot from `QC_PASSED` to `QUARANTINED` by supplying a `reason`, and may release it back from `QUARANTINED` to `QC_PASSED` via release-quarantine. `QC_FAILED` is the terminal lot state.

### 3.3. Formulas and Process Validations

A `Formula` is the manufacturing recipe. A `REGULATORY_AFFAIRS` operator creates one with a unique `formula_code`, a `product_name`, the `nutrient_profile_id` of the `NutrientProfile` it must satisfy, an `ingredients` array of at least two entries (each entry naming an `ingredient_id`, a `percentage_by_weight`, and an `is_critical` flag), and a `process_type` drawn from `DRY_BLEND`, `WET_PROCESS`, or `COMBINATION`. The new formula starts in `DRAFT`.

Submitting a formula for review transitions `DRAFT → IN_REVIEW` and is refused with `ERR_PERCENTAGE_SUM_INVALID` (HTTP 422) if the ingredient percentages do not sum to 100.000 within a tolerance of 0.001, with `ERR_PROFILE_NOT_APPROVED` (HTTP 422) if the referenced nutrient profile is not currently `APPROVED`, and with `ERR_NOT_FOUND` if any referenced `ingredient_id` does not exist.

Approval — `IN_REVIEW → APPROVED` — is performed by a `QA_MANAGER` other than the user who submitted for review (violations yield `ERR_SEGREGATION_OF_DUTIES`), and additionally requires that at least one `ProcessValidation` for this formula exists with `status` equal to `PASSED` and a `validation_type` matching the formula's `process_type`. A `COMBINATION` formula is satisfied by either a `COMBINATION_FULL` validation or by having both a `DRY_BLEND_HOMOGENEITY` and a `WET_PROCESS_THERMAL` validation in `PASSED` state. A formula may instead be returned from `IN_REVIEW` to `DRAFT` by a `QA_MANAGER` with no additional preconditions.

The final activation step — `APPROVED → ACTIVE` — is gated on two independent referential checks: at least one `LabelSubmission` for the formula must exist in `APPROVED` status (otherwise `ERR_LABEL_NOT_APPROVED`, HTTP 422), and at least one `ProcessValidation` for the formula must exist in `PASSED` status with a `valid_until` strictly after the current logical timestamp (otherwise `ERR_VALIDATION_REQUIRED`, HTTP 422). A `QA_MANAGER` may discontinue an `ACTIVE` formula only when no `ProductionBatch` for that formula exists in any of `IN_PRODUCTION`, `TESTING`, or `POSITIVE_RELEASE_HOLD`; otherwise the request fails with `ERR_ACTIVE_BATCHES_EXIST` (HTTP 422).

A `ProcessValidation` is a time-boxed certification that a particular process type is under control for a particular formula. A `QA_MANAGER` creates one with `formula_id`, a `validation_type` of `DRY_BLEND_HOMOGENEITY`, `WET_PROCESS_THERMAL`, `PATHOGEN_ENVIRONMENTAL`, or `COMBINATION_FULL`, a `protocol_version` reference, and a `validation_validity_days` integer between 30 and 1095 inclusive. New validations begin in `PLANNED`. A `PRODUCTION_SUPERVISOR` moves a validation to `IN_PROGRESS`, which sets `started_at`. A `QUALITY_ANALYST` then concludes the run by one of two paths. If every entry in the supplied `test_results` array has its `pass` flag true, the analyst completes the validation: it transitions to `PASSED`, `completed_at` is set to the logical timestamp, and `valid_until` is computed as `completed_at + validation_validity_days` (calendar days). If at least one test result has `pass` false and a `failure_summary` is supplied, the analyst fails the validation: it transitions to the terminal `FAILED` state with `completed_at` set. A `PASSED` validation whose `valid_until` passes is automatically transitioned by the system to the terminal `EXPIRED` state, which propagates into formula activation gating and batch production gating as described elsewhere in this section.

### 3.4. Production Batches: Consumption, Processing, and Positive Release

A `ProductionBatch` is created by a `PRODUCTION_SUPERVISOR` against an `ACTIVE` formula. The creation payload carries `formula_id`, the planned `batch_size_kg` (strictly positive, 3 decimal places), the planned `production_date`, and the OCC field `expected_formula_version` per §2.6. The server assigns a unique `batch_number` in the format `B-{YYYYMMDD}-{seq}`. If the referenced formula is not in `ACTIVE` status, creation is refused with `ERR_FORMULA_NOT_ACTIVE` (HTTP 422). Successful creation increments the parent formula's `version` by one. New batches start in `PLANNED`, with `ingredient_consumptions` empty and `actual_yield_kg`, `nutrient_results`, `pathogen_results`, and `release_decision` unset.

Starting production — `PLANNED → IN_PRODUCTION` — is the most heavily gated transition in the system. The server enforces, in priority order: that the formula is `ACTIVE`; that every ingredient lot the recipe will consume currently has `qc_status` equal to `QC_PASSED` (else `ERR_LOT_NOT_QC_PASSED`, HTTP 422); that each such lot's supplier is `QUALIFIED` at this moment (else `ERR_SUPPLIER_NOT_QUALIFIED`); that for a `DRY_BLEND` or `COMBINATION` formula at least one `ProcessValidation` of type `DRY_BLEND_HOMOGENEITY` exists in `PASSED` state with `valid_until` strictly after the current logical timestamp, and correspondingly for a `WET_PROCESS` or `COMBINATION` formula a `WET_PROCESS_THERMAL` validation (else `ERR_VALIDATION_REQUIRED`); that every lot to be consumed has `expiry_date` strictly after now (else `ERR_LOT_EXPIRED`); and that the eligible lots collectively hold enough `remaining_kg` to satisfy the recipe (else `ERR_INSUFFICIENT_INGREDIENT_QUANTITY`, HTTP 422).

On success, the system consumes ingredients first-expiry-first-out. For each ingredient in the recipe, the required quantity is the `batch_size_kg` multiplied by the ingredient's `percentage_by_weight` divided by 100. The eligible lots for that ingredient — those with matching `ingredient_id`, `qc_status` `QC_PASSED`, `remaining_kg` strictly positive, and `expiry_date` strictly after now — are sorted by `expiry_date` ascending, with `created_at` ascending as the tie-break. Lots are consumed in that order: from each lot the system takes the smaller of the lot's `remaining_kg` and the quantity still needed, decrements the lot's `remaining_kg` by that amount, and appends an entry to the batch's `ingredient_consumptions` naming the `ingredient_lot_id`, the `consumed_kg`, and a monotonically increasing `consumption_order` sequence number. If, after consuming all eligible lots, the cumulative consumption for an ingredient is still short of the required quantity, the transition fails with `ERR_INSUFFICIENT_INGREDIENT_QUANTITY` and no partial consumption is committed.

From `IN_PRODUCTION`, the production path depends on `process_type`. A batch whose formula's `process_type` is `DRY_BLEND` or `COMBINATION` is moved by a `PRODUCTION_SUPERVISOR` to `BLENDING_COMPLETE` via the complete-blending step; attempting that transition on a `WET_PROCESS` formula is rejected with `ERR_INVALID_STATE`. All batches then converge on the complete-processing step, which transitions either `IN_PRODUCTION → PROCESSING_COMPLETE` (wet-process batches) or `BLENDING_COMPLETE → PROCESSING_COMPLETE` (dry-blend and combination batches) and sets `actual_yield_kg` from the request body. A `QUALITY_ANALYST` then submits the batch for testing, transitioning `PROCESSING_COMPLETE → TESTING` only when `actual_yield_kg` is set and strictly positive.

While the batch is in `TESTING`, a `QUALITY_ANALYST` submits the lab results. The body carries two arrays: `nutrient_results` (one entry per nutrient, each with `nutrient_code` and `measured_per_100kcal`) and `pathogen_results` (each with `pathogen_code`, a `detected` flag, and `cfu_per_g`). Submission requires that the nutrient results cover every nutrient listed in the formula's governing nutrient profile and that the pathogen panel covers at least the panel required for the most stringent `pathogen_risk_class` among the batch's consumed ingredients; otherwise the submission is rejected with `ERR_INCOMPLETE_TEST_RESULTS` (HTTP 422).

On accepted submission the system transitions `TESTING → POSITIVE_RELEASE_HOLD` and auto-evaluates every result. The nutrient evaluation has two variants governed by the governing profile's `profile_code`:

- For any profile other than `INF-0-6M`, the standard variant applies. Each measured value passes if and only if it lies within the closed interval from that spec's `min_per_100kcal` to its `max_per_100kcal`.
- For `INF-0-6M`, a stricter borderline variant applies. The effective minimum is the spec's `min_per_100kcal` multiplied by 1.02 — a two-percent upward safety margin — and the effective maximum is the spec's `max_per_100kcal` multiplied by 0.98 — a two-percent downward safety margin. The measured value passes if and only if it lies within the closed interval from the effective minimum to the effective maximum.

Each nutrient result's `pass` flag is set accordingly, and any nutrient listed in the profile but absent from `nutrient_results` is treated as a failing result. Each pathogen result passes if and only if `detected` is false; the overall evaluation requires every nutrient to pass and every pathogen to be undetected.

A batch sits in `POSITIVE_RELEASE_HOLD` until a `QA_MANAGER` either releases or rejects it. Release transitions `POSITIVE_RELEASE_HOLD → RELEASED` and is refused with `ERR_BATCH_TESTS_FAILED` (HTTP 422) if any nutrient result has `pass` false or any pathogen result has `detected` true, and with `ERR_SEGREGATION_OF_DUTIES` if the releasing manager is the same user who submitted the test results. On release the system sets `release_decision` to `RELEASED`, computes the batch's `expiry_date` (see below), and increments the batch's `version`. Rejection transitions `POSITIVE_RELEASE_HOLD → REJECTED`, requires a `rejection_reason` in the body, and requires that at least one nutrient result has `pass` false or at least one pathogen result has `detected` true; on rejection the system sets `release_decision` to `REJECTED` and restores `remaining_kg` on every lot in the batch's `ingredient_consumptions` by the exact `consumed_kg` amounts originally recorded, undoing the FIFO consumption in full.

The batch `expiry_date` is computed from `production_date` plus a shelf-life that depends on the governing profile's `profile_code` and the formula's `process_type`. The base shelf-life in calendar months is 24 for `INF-0-6M`, 24 for `INF-6-12M`, 18 for `TODDLER-12-36M`, 12 for `CEREAL-6M`, 9 for `PUREE-4M`, and 12 for any other code. If `process_type` is `DRY_BLEND`, three additional calendar months are added on top of the base. The expiry is `production_date` plus that many calendar months.

A batch that has been `RELEASED` may subsequently be transitioned to `RECALLED` by the recall cascade described in §3.6; `RELEASED`, `REJECTED`, and `RECALLED` are the batch's three terminal states.

### 3.5. Label Submissions and Marketing Review

No formula can reach `ACTIVE` without an approved label. A `LabelSubmission` is created by a `REGULATORY_AFFAIRS` operator with `formula_id`, a `submission_type` drawn from `NEW_PRODUCT_REGISTRATION`, `LABEL_AMENDMENT`, `NOTIFICATION`, or `RENEWAL`, the full `label_text`, and an optional `claims` array. New submissions begin in `DRAFT`.

The submission step moves `DRAFT → SUBMITTED`, requires that `label_text` be non-empty, and requires that the referenced formula be in either `APPROVED` or `ACTIVE` status; on submission the server stamps `submitted_at`. A `QA_MANAGER` then assigns a reviewer by providing `reviewer_id`; the referenced `SystemUser` must have `role` equal to `REGULATORY_AFFAIRS` or `QA_MANAGER`, and on assignment the submission moves `SUBMITTED → UNDER_REVIEW` and `reviewer_id` is recorded. While under review, reviewers accumulate entries into the `review_comments` array (each entry carrying `comment`, `severity`, and a `resolved` flag).

Approval — `UNDER_REVIEW → APPROVED` — is performed by a `QA_MANAGER` other than the user who submitted the label (else `ERR_SEGREGATION_OF_DUTIES`) and requires every entry in `review_comments` to have `resolved` true. Rejection — `UNDER_REVIEW → REJECTED` — requires at least one comment with `resolved` false and a `rejection_reason` in the body. Both decisions stamp `decided_at`. A `QA_MANAGER` may also return a submission from `UNDER_REVIEW` to `DRAFT` with no preconditions. A `REGULATORY_AFFAIRS` operator may withdraw a submission from either `DRAFT` or `SUBMITTED` to the terminal `WITHDRAWN` state; withdrawal from `UNDER_REVIEW` is not defined and yields `ERR_INVALID_STATE`. The submission's terminal states are `APPROVED`, `REJECTED`, and `WITHDRAWN`.

### 3.6. Complaints, Adverse Events, and Recall Campaigns

A `Complaint` is filed by a `COMPLAINT_HANDLER` with `complainant_name`, `complainant_contact`, the `product_formula_id` of the formula the complaint concerns, an optional `batch_id` when the specific batch is known, a `complaint_type` of `QUALITY_DEFECT`, `FOREIGN_MATTER`, `PACKAGING`, `ADVERSE_EVENT`, `ILLNESS`, or `OTHER`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and a free-text `description`. The server assigns a `complaint_ref` in the format `C-{YYYYMMDD}-{seq}` and computes the boolean `is_adverse_event`: true whenever `complaint_type` is `ADVERSE_EVENT` or `ILLNESS`, or `severity` is `CRITICAL`, and false otherwise. New complaints begin in `RECEIVED`.

A `COMPLAINT_HANDLER` begins investigation, moving `RECEIVED → INVESTIGATING`. From `INVESTIGATING`, the handler may either resolve or escalate. Resolution requires a non-empty `resolution` text and moves the complaint to `RESOLVED`, stamping `resolved_at`. Escalation moves the complaint to `ESCALATED`, stamps `escalated_at`, requires an `escalation_reason` in the body, and is gated by the escalation rule: the complaint must either have `is_adverse_event` true or `severity` equal to `HIGH` or `CRITICAL`; otherwise the escalation is rejected with `ERR_ESCALATION_NOT_WARRANTED` (HTTP 422). When the escalated complaint carries a `batch_id` whose batch is currently in `RELEASED` status, the system flags that batch for potential recall review.

An `ESCALATED` complaint may be resolved only by a `QA_MANAGER`, not by the original handler. The same non-empty `resolution` requirement applies, and if `batch_id` is set, the resolution is additionally gated on the batch having been reviewed for recall linkage — either a recall has been initiated against it or a documented no-recall decision has been recorded. A resolved complaint is moved from `RESOLVED` to the terminal `CLOSED` state by a `COMPLAINT_HANDLER`, which requires that `resolved_at` is set.

A `RecallCampaign` is initiated by a `QA_MANAGER` with a `reason` of `PATHOGEN_CONTAMINATION`, `NUTRIENT_DEVIATION`, `FOREIGN_MATTER`, `MISLABELING`, `PACKAGING_DEFECT`, or `PRECAUTIONARY`, a `recall_class` of `CLASS_I`, `CLASS_II`, or `CLASS_III`, and a free-text `scope_description`. The server assigns a `recall_ref` in the format `R-{YYYYMMDD}-{seq}`, stamps `initiated_at` from the logical clock, and records the initiating user as `initiated_by`. New campaigns begin in `INITIATED`.

Scope is added to a campaign one entry at a time. A `QA_MANAGER` creates a `RecallScope` entry under a campaign by supplying `batch_id`, a `withdrawal_level` of `CONSUMER`, `RETAIL`, `WHOLESALE`, or `DISTRIBUTION_CENTER`, and the `quantity_shipped_kg` that was shipped for that batch (non-negative, 3 decimal places). Adding a scope entry immediately cascades the referenced batch from `RELEASED` to `RECALLED` (§2.7) and increments the batch's `version`; if any `AllocationEntry` has recorded `fulfilled_kg` drawn from that batch, those entries are flagged for recall notification. New scope entries start in `PENDING` with `quantity_recovered_kg` zero and `recovery_pct` computed as described below.

Notification moves the campaign from `INITIATED → NOTIFIED` and is performed by a `REGULATORY_AFFAIRS` operator. It is refused with `ERR_RECALL_SCOPE_EMPTY` (HTTP 422) if the campaign has no scope entries, and with `ERR_INVALID_STATE` if any scope entry is not currently `PENDING`. On success, every scope entry transitions `PENDING → NOTIFIED`. Beginning recovery — `NOTIFIED → IN_PROGRESS`, performed by a `SUPPLY_CHAIN_PLANNER` — flips every scope entry `NOTIFIED → IN_PROGRESS`.

Recovery is recorded per scope entry by a `SUPPLY_CHAIN_PLANNER` supplying a `recovered_kg` amount. Each record increments `quantity_recovered_kg` by the recorded amount and recomputes `recovery_pct` for the entry: when `quantity_shipped_kg` is zero, `recovery_pct` is 100.00 by vacuous completion; otherwise it is `quantity_recovered_kg` divided by `quantity_shipped_kg`, multiplied by 100, rounded half-up to 2 decimal places. When all quantities that will be recovered have been recorded, the entry's status transitions to `RECOVERED`. A `QUALITY_ANALYST` may additionally verify a scope entry, moving it from `IN_PROGRESS` or `RECOVERED` to the terminal `VERIFIED` state.

Once every scope entry has reached `RECOVERED` or `VERIFIED`, a `QUALITY_ANALYST` may start the effectiveness check, transitioning the campaign `IN_PROGRESS → EFFECTIVENESS_CHECK` and populating the campaign's `effectiveness_checks` array with aggregated per-consignee data (each entry carrying `check_date`, `consignee_count`, `response_count`, and `recovery_pct`). Completion of the campaign — `EFFECTIVENESS_CHECK → COMPLETED`, performed by a `QA_MANAGER` — is gated on two conditions: every scope entry must be in `VERIFIED` status, and the overall `recovery_pct` aggregated across scope entries must meet the regulatory floor for the campaign's class. The floor is 90.00 for `CLASS_I`, 80.00 for `CLASS_II`, and 70.00 for `CLASS_III`; failure to meet the class floor is rejected with `ERR_RECOVERY_THRESHOLD_NOT_MET` (HTTP 422). A completed campaign stamps `completed_at`. A `QA_MANAGER` may also terminate a campaign from `INITIATED` by supplying a `termination_reason`; termination cascades every scope entry to `VERIFIED` regardless of prior state and restores every in-scope batch from `RECALLED` back to `RELEASED`. `COMPLETED` and `TERMINATED` are the campaign's terminal states.

### 3.7. Allocation Plans and Shortage Management

When supply is constrained, a `SUPPLY_CHAIN_PLANNER` constructs an `AllocationPlan` to distribute the available quantity of a formula across customers. Creating a plan requires `formula_id`, the `total_available_kg` to distribute (strictly positive, 3 decimal places), and an `allocation_method` of `PRO_RATA`, `PRIORITY_TIER`, `EQUAL_SPLIT`, or `WATERFALL`. The server assigns a `plan_ref` in the format `A-{YYYYMMDD}-{seq}`. New plans begin in `DRAFT`.

Entries are added to the plan one at a time. Each `AllocationEntry` is created under a plan with `customer_code`, `customer_name`, `requested_kg` (strictly positive, 3 decimal places), and an optional `priority_tier` integer between 1 and 10 inclusive used by the `PRIORITY_TIER` and `WATERFALL` methods (lower numbers are higher priority). Each entry begins in `PENDING` with `allocated_kg` and `fulfilled_kg` both zero. Every entry creation increments the parent plan's `version` by one.

Activation — `DRAFT → ACTIVE`, performed by a `SUPPLY_CHAIN_PLANNER` — stamps `activated_at` from the logical clock, runs the allocation calculation, and populates `allocated_kg` on every entry. Activation is refused with `ERR_ALLOCATION_PLAN_EMPTY` (HTTP 422) when the plan has no entries, with `ERR_INVALID_RANGE` (HTTP 422) when `total_available_kg` is not strictly positive, and per §2.6 it requires the OCC field `expected_plan_version` matching the plan's current `version`. The allocation method governs how the available kilograms are divided:

- **`PRO_RATA`.** Sum the `requested_kg` across every entry currently in `PENDING` status. If the total requested is at most `total_available_kg`, every entry is allocated exactly its requested quantity. Otherwise, compute the ratio of `total_available_kg` to total requested, and process entries in `created_at` ascending order: for each entry, multiply its `requested_kg` by the ratio, truncate the result down to 3 decimal places (floor at the milligram step), and assign that as `allocated_kg`. After the pass, compute the remainder as `total_available_kg` minus the sum of all `allocated_kg` values, and walk the entries again in `created_at` ascending order, adding 0.001 to each entry in turn while the remainder is at least 0.001.
- **`PRIORITY_TIER`.** Walk tiers from 1 to 10 in ascending order. For each tier, collect the entries with that `priority_tier` and status `PENDING`; if none, continue to the next tier. Let `remaining` start at `total_available_kg`. If `remaining` is at least the tier's total requested, allocate every entry in the tier its full `requested_kg` and subtract that total from `remaining`, then move to the next tier. Otherwise, compute the ratio of `remaining` to the tier's total requested and apply the same per-entry truncation and 0.001-step remainder distribution within the tier (in `created_at` ascending order), set `remaining` to zero, and stop — every entry in any higher tier number receives `allocated_kg` of zero.
- **`EQUAL_SPLIT`.** Count the entries in `PENDING` status; if zero, no allocation occurs. The base share is `total_available_kg` divided by that count, truncated down to 3 decimal places. In `created_at` ascending order, each entry is allocated the smaller of the base share and its `requested_kg`. Any surplus left over (because capped entries took less than the base share) is then redistributed: while the surplus is at least 0.001 and at least one entry remains uncapped, compute a per-entry surplus share by dividing the current surplus by the number of currently uncapped entries and truncating to 3 decimal places. If that share is below 0.001, give the entire remaining surplus to the first uncapped entry in `created_at` order and finish; otherwise grant each uncapped entry the smaller of the per-entry surplus share and the entry's remaining unfulfilled request, subtract the granted amounts from the surplus, and recompute the uncapped set for the next iteration.
- **`WATERFALL`.** Behaves as `PRIORITY_TIER` with strict tier-by-tier filling: entries in a lower tier number are filled completely (up to their requested amount) before any allocation flows to the next tier.

The allocation computed at activation is **provisional**: it is derived from the entries that are in `PENDING` at the moment of activation. If entries are added or removed after activation but before any fulfillment has been recorded, the calculation is rerun and only entries still in `PENDING` participate in the recomputation — the **final** allocation may therefore differ from the provisional one for the same inputs.

Fulfillment is recorded against an entry by a `SUPPLY_CHAIN_PLANNER` providing a `fulfilled_kg` amount. The parent plan must be in `ACTIVE` status, and the cumulative `fulfilled_kg` after this record must not exceed the entry's `allocated_kg`; otherwise the record is rejected with `ERR_FULFILLMENT_EXCEEDS_ALLOCATION` (HTTP 422). On a successful record, `fulfilled_kg` increases by the recorded amount. If after the record the cumulative `fulfilled_kg` is strictly less than `allocated_kg`, the entry transitions `PENDING → PARTIALLY_FULFILLED` (or remains in `PARTIALLY_FULFILLED`). If after the record the cumulative `fulfilled_kg` equals `allocated_kg`, the entry transitions to the terminal `FULFILLED` state (from either `PENDING` or `PARTIALLY_FULFILLED`).

An entry that cannot be fully fulfilled may be marked as a shortfall by a `SUPPLY_CHAIN_PLANNER` providing a `shortfall_reason`. From `PENDING`, shortfall marking requires `allocated_kg` strictly less than `requested_kg`. From `PARTIALLY_FULFILLED`, shortfall marking requires `fulfilled_kg` strictly less than `allocated_kg`. Both paths move the entry to the terminal `SHORTFALL` state. When every entry in a plan has reached either `FULFILLED` or `SHORTFALL`, the plan automatically transitions `ACTIVE → FULFILLED` and stamps `fulfilled_at`. A `SUPPLY_CHAIN_PLANNER` may cancel a plan from `DRAFT` unconditionally; cancelling from `ACTIVE` requires that no entry yet has `fulfilled_kg` strictly greater than zero. `FULFILLED` and `CANCELLED` are the plan's terminal states.

## 4. Endpoint Definitions

Operations that create a new resource — whether a top-level resource or a child resource added to a parent's collection — return `201 Created`. Operations that modify an existing resource, including every state transition, return `200 OK`. The two activation endpoints below are listed with their scaffold-declared status codes.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/api/v1/_clock/set_current_utc` | Set the logical system clock | ADMIN |
| POST | `/api/v1/system-users` | Create a new system user | ADMIN |
| GET | `/api/v1/system-users` | List system users | ADMIN, QA_MANAGER |
| GET | `/api/v1/system-users/{id}` | Get a system user by ID | ADMIN, QA_MANAGER |
| POST | `/api/v1/nutrient-profiles` | Create a new nutrient profile | REGULATORY_AFFAIRS |
| GET | `/api/v1/nutrient-profiles` | List nutrient profiles | REGULATORY_AFFAIRS, QA_MANAGER, QUALITY_ANALYST |
| GET | `/api/v1/nutrient-profiles/{id}` | Get a nutrient profile by ID | REGULATORY_AFFAIRS, QA_MANAGER, QUALITY_ANALYST |
| POST | `/api/v1/nutrient-profiles/{id}/submit` | Submit a nutrient profile for approval | REGULATORY_AFFAIRS |
| POST | `/api/v1/nutrient-profiles/{id}/approve` | Approve a submitted nutrient profile | REGULATORY_AFFAIRS |
| POST | `/api/v1/nutrient-profiles/{id}/return-for-revision` | Return a submitted profile to draft | REGULATORY_AFFAIRS |
| POST | `/api/v1/nutrient-profiles/{id}/withdraw` | Withdraw a nutrient profile | REGULATORY_AFFAIRS |
| POST | `/api/v1/suppliers` | Create a new supplier | QA_MANAGER |
| GET | `/api/v1/suppliers` | List suppliers | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/suppliers/{id}` | Get a supplier by ID | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/suppliers/{id}/suspend` | Suspend a qualified supplier | QUALITY_ANALYST |
| POST | `/api/v1/suppliers/{id}/reinstate` | Reinstate a suspended supplier | QUALITY_ANALYST |
| POST | `/api/v1/suppliers/{id}/disqualify` | Disqualify a supplier permanently | QA_MANAGER |
| POST | `/api/v1/suppliers/{id}/audits` | Submit an audit record for a supplier | QUALITY_ANALYST |
| GET | `/api/v1/suppliers/{id}/audits` | List audit records for a supplier | QA_MANAGER, QUALITY_ANALYST |
| GET | `/api/v1/audit-records/{id}` | Get an audit record by ID | QA_MANAGER, QUALITY_ANALYST |
| POST | `/api/v1/ingredients` | Create a new ingredient | QA_MANAGER |
| GET | `/api/v1/ingredients` | List ingredients | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/ingredients/{id}` | Get an ingredient by ID | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/ingredient-lots` | Receive a new ingredient lot | SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/ingredient-lots` | List ingredient lots | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/ingredient-lots/{id}` | Get an ingredient lot by ID | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/ingredients/{id}/lots` | List lots for a specific ingredient | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/suppliers/{id}/lots` | List lots supplied by a specific supplier | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/ingredient-lots/{id}/qc-pass` | Mark an ingredient lot as QC passed | QUALITY_ANALYST |
| POST | `/api/v1/ingredient-lots/{id}/qc-fail` | Mark an ingredient lot as QC failed | QUALITY_ANALYST |
| POST | `/api/v1/ingredient-lots/{id}/quarantine` | Explicitly quarantine an ingredient lot | QUALITY_ANALYST |
| POST | `/api/v1/ingredient-lots/{id}/release-quarantine` | Release an ingredient lot from quarantine | QUALITY_ANALYST |
| POST | `/api/v1/formulas` | Create a new formula | REGULATORY_AFFAIRS |
| GET | `/api/v1/formulas` | List formulas | REGULATORY_AFFAIRS, QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/formulas/{id}` | Get a formula by ID | REGULATORY_AFFAIRS, QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/formulas/{id}/submit-for-review` | Submit formula for QA review | REGULATORY_AFFAIRS |
| POST | `/api/v1/formulas/{id}/approve` | Approve a formula | QA_MANAGER |
| POST | `/api/v1/formulas/{id}/return-for-revision` | Return formula to draft for revision | QA_MANAGER |
| POST | `/api/v1/formulas/{id}/activate` | Activate an approved formula for production | QA_MANAGER |
| POST | `/api/v1/formulas/{id}/discontinue` | Discontinue a formula | QA_MANAGER |
| POST | `/api/v1/process-validations` | Create a new process validation | QA_MANAGER |
| GET | `/api/v1/process-validations` | List process validations | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR |
| GET | `/api/v1/process-validations/{id}` | Get a process validation by ID | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR |
| GET | `/api/v1/formulas/{id}/process-validations` | List process validations for a formula | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR |
| POST | `/api/v1/process-validations/{id}/start` | Start a process validation run | PRODUCTION_SUPERVISOR |
| POST | `/api/v1/process-validations/{id}/complete` | Complete a process validation as passed | QUALITY_ANALYST |
| POST | `/api/v1/process-validations/{id}/fail` | Mark a process validation as failed | QUALITY_ANALYST |
| POST | `/api/v1/production-batches` | Create a new production batch | PRODUCTION_SUPERVISOR |
| GET | `/api/v1/production-batches` | List production batches | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/production-batches/{id}` | Get a production batch by ID | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/formulas/{id}/batches` | List batches for a formula | QA_MANAGER, QUALITY_ANALYST, PRODUCTION_SUPERVISOR, SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/production-batches/{id}/start-production` | Start production on a planned batch | PRODUCTION_SUPERVISOR |
| POST | `/api/v1/production-batches/{id}/complete-blending` | Mark blending step as complete | PRODUCTION_SUPERVISOR |
| POST | `/api/v1/production-batches/{id}/complete-processing` | Mark processing as complete and record yield | PRODUCTION_SUPERVISOR |
| POST | `/api/v1/production-batches/{id}/submit-for-testing` | Submit batch for quality testing | QUALITY_ANALYST |
| POST | `/api/v1/production-batches/{id}/submit-test-results` | Submit nutrient and pathogen test results | QUALITY_ANALYST |
| POST | `/api/v1/production-batches/{id}/release` | Release a batch from positive-release hold | QA_MANAGER |
| POST | `/api/v1/production-batches/{id}/reject` | Reject a batch from positive-release hold | QA_MANAGER |
| POST | `/api/v1/label-submissions` | Create a new label submission | REGULATORY_AFFAIRS |
| GET | `/api/v1/label-submissions` | List label submissions | REGULATORY_AFFAIRS, QA_MANAGER |
| GET | `/api/v1/label-submissions/{id}` | Get a label submission by ID | REGULATORY_AFFAIRS, QA_MANAGER |
| GET | `/api/v1/formulas/{id}/label-submissions` | List label submissions for a formula | REGULATORY_AFFAIRS, QA_MANAGER |
| POST | `/api/v1/label-submissions/{id}/submit` | Submit label for regulatory review | REGULATORY_AFFAIRS |
| POST | `/api/v1/label-submissions/{id}/assign-reviewer` | Assign a reviewer to a label submission | QA_MANAGER |
| POST | `/api/v1/label-submissions/{id}/approve` | Approve a label submission | QA_MANAGER |
| POST | `/api/v1/label-submissions/{id}/reject` | Reject a label submission | QA_MANAGER |
| POST | `/api/v1/label-submissions/{id}/return-for-revision` | Return label to draft for revision | QA_MANAGER |
| POST | `/api/v1/label-submissions/{id}/withdraw` | Withdraw a label submission | REGULATORY_AFFAIRS |
| POST | `/api/v1/complaints` | File a new complaint | COMPLAINT_HANDLER |
| GET | `/api/v1/complaints` | List complaints | COMPLAINT_HANDLER, QA_MANAGER |
| GET | `/api/v1/complaints/{id}` | Get a complaint by ID | COMPLAINT_HANDLER, QA_MANAGER |
| POST | `/api/v1/complaints/{id}/start-investigation` | Start investigating a complaint | COMPLAINT_HANDLER |
| POST | `/api/v1/complaints/{id}/escalate` | Escalate a complaint to adverse event | COMPLAINT_HANDLER |
| POST | `/api/v1/complaints/{id}/resolve` | Resolve a complaint | COMPLAINT_HANDLER, QA_MANAGER |
| POST | `/api/v1/complaints/{id}/close` | Close a resolved complaint | COMPLAINT_HANDLER |
| POST | `/api/v1/recall-campaigns` | Initiate a new recall campaign | QA_MANAGER |
| GET | `/api/v1/recall-campaigns` | List recall campaigns | QA_MANAGER, REGULATORY_AFFAIRS, QUALITY_ANALYST, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/recall-campaigns/{id}` | Get a recall campaign by ID | QA_MANAGER, REGULATORY_AFFAIRS, QUALITY_ANALYST, SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/recall-campaigns/{id}/notify` | Send recall notifications to consignees | REGULATORY_AFFAIRS |
| POST | `/api/v1/recall-campaigns/{id}/begin-recovery` | Begin physical recovery of recalled product | SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/recall-campaigns/{id}/start-effectiveness-check` | Start effectiveness check on recovery progress | QUALITY_ANALYST |
| POST | `/api/v1/recall-campaigns/{id}/complete` | Complete a recall campaign | QA_MANAGER |
| POST | `/api/v1/recall-campaigns/{id}/terminate` | Terminate a recall campaign early | QA_MANAGER |
| POST | `/api/v1/recall-campaigns/{id}/scopes` | Add a batch scope entry to a recall campaign | QA_MANAGER |
| GET | `/api/v1/recall-campaigns/{id}/scopes` | List scope entries for a recall campaign | QA_MANAGER, REGULATORY_AFFAIRS, QUALITY_ANALYST, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/recall-scopes` | List all recall scope entries | QA_MANAGER, REGULATORY_AFFAIRS, QUALITY_ANALYST, SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/recall-scopes/{id}` | Get a recall scope entry by ID | QA_MANAGER, REGULATORY_AFFAIRS, QUALITY_ANALYST, SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/recall-scopes/{id}/record-recovery` | Record recovered quantity for a scope entry | SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/recall-scopes/{id}/verify` | Verify a recall scope entry as fully recovered | QUALITY_ANALYST |
| POST | `/api/v1/allocation-plans` | Create a new allocation plan | SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/allocation-plans` | List allocation plans | SUPPLY_CHAIN_PLANNER, QA_MANAGER |
| GET | `/api/v1/allocation-plans/{id}` | Get an allocation plan by ID | SUPPLY_CHAIN_PLANNER, QA_MANAGER |
| POST | `/api/v1/allocation-plans/{id}/activate` | Activate an allocation plan (runs allocation calculation) | SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/allocation-plans/{id}/cancel` | Cancel an allocation plan | SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/allocation-plans/{id}/entries` | Add an entry to an allocation plan | SUPPLY_CHAIN_PLANNER |
| GET | `/api/v1/allocation-plans/{id}/entries` | List entries for an allocation plan | SUPPLY_CHAIN_PLANNER, QA_MANAGER |
| GET | `/api/v1/allocation-entries/{id}` | Get an allocation entry by ID | SUPPLY_CHAIN_PLANNER, QA_MANAGER |
| POST | `/api/v1/allocation-entries/{id}/record-fulfillment` | Record a fulfillment shipment against an entry | SUPPLY_CHAIN_PLANNER |
| POST | `/api/v1/allocation-entries/{id}/mark-shortfall` | Mark an entry as shortfall | SUPPLY_CHAIN_PLANNER |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_RANGE` | 422 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PROFILE_NOT_APPROVED` | 422 |
| `ERR_NUTRIENT_RANGE_INVALID` | 422 |
| `ERR_PERCENTAGE_SUM_INVALID` | 422 |
| `ERR_SUPPLIER_NOT_QUALIFIED` | 422 |
| `ERR_LOT_NOT_QC_PASSED` | 422 |
| `ERR_LOT_EXPIRED` | 422 |
| `ERR_VALIDATION_REQUIRED` | 422 |
| `ERR_FORMULA_NOT_ACTIVE` | 422 |
| `ERR_INSUFFICIENT_INGREDIENT_QUANTITY` | 422 |
| `ERR_AUDIT_TOO_OLD` | 422 |
| `ERR_BATCH_TESTS_FAILED` | 422 |
| `ERR_INCOMPLETE_TEST_RESULTS` | 422 |
| `ERR_ACTIVE_BATCHES_EXIST` | 422 |
| `ERR_LABEL_NOT_APPROVED` | 422 |
| `ERR_ESCALATION_NOT_WARRANTED` | 422 |
| `ERR_RECOVERY_THRESHOLD_NOT_MET` | 422 |
| `ERR_FULFILLMENT_EXCEEDS_ALLOCATION` | 422 |
| `ERR_RECALL_SCOPE_EMPTY` | 422 |
| `ERR_ALLOCATION_PLAN_EMPTY` | 422 |
