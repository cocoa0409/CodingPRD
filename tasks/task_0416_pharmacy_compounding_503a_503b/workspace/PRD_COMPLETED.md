# Pharmacy Compounding (503A/503B) API — Product Requirements Document

## 1. Introduction

Compounding pharmacies operate under one of two federal regimes. A traditional **503A pharmacy** prepares patient-specific preparations against a named prescription, while a **503B outsourcing facility** is registered to compound office-use stock in anticipation of demand, subject to far tighter stability and quantity controls. Both regimes share the same physical reality — formula records, ingredient lots with assayed potency, controlled cleanrooms monitored under USP chapters, batch production with yield reconciliation, quality-control and endotoxin testing, beyond-use dating, labeling, and the ever-present possibility of a recall — but they diverge sharply in what the law permits and how a finished unit may reach a patient.

This API governs that full operational lifecycle as a single auditable system of record. It models the journey of a preparation from a master formulation record, through the receipt and potency-correction of raw components, the opening and starting of a compounding batch, the minting of individually serialized finished units at compile time, independent quality-assurance release under strict segregation of duties, and finally the dispensing of a patient unit or the distribution of an office-use unit. Layered over this happy path are the controls that make compounding safe: rolling anticipatory-compounding limits for 503B office use, beyond-use dating that can never outlive its ingredients, environmental-excursion gates on sterile release, and a recall machinery that cascades through every affected finished unit and prescription.

The design goal is determinism and traceability. Every facility carries its own logical clock so that beyond-use dating, prescription expiry, lot expiry, and rolling-window calculations are reproducible. Every derived quantity — remaining grams of a lot, units dispensed against a prescription, units consumed against an anticipatory ledger — is reconciled from primary events rather than trusted as free-standing input. The sections that follow specify the system-wide contracts first, then the business workflows in which the individual rules live.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint of the API. All resources are mounted under the `/pharmacy-compounding` path prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which they are acting. If either header is absent, or if `X-User-Role` carries a value that is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.

The system recognizes exactly four roles, spelled precisely as follows: `SystemAdmin`, `CompoundingPharmacist`, `QualityAssurancePharmacist`, and `DispensingPharmacist`. When a role attempts an operation it is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

All four roles are **opaque operator identities**: in each case the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity, and the server never compares it to any entity's `id`. The server does, however, record `X-User-ID` where a state transition explicitly captures it. Specifically, when a `CompoundingPharmacist` compiles a batch, the server records the acting `X-User-ID` as the batch's `compiled_by_user_id`; and when a `QualityAssurancePharmacist` releases a batch, the server records the acting `X-User-ID` as the batch's `released_by_user_id`. These recorded identifiers drive the segregation-of-duties control described in §3, but they are stored operator fingerprints, not ownership keys.

The broad division of labor is as follows. A `SystemAdmin` provisions facilities and controls each facility's deterministic clock. A `CompoundingPharmacist` authors master formulation records and ingredient lots, opens and charges batches, and drives a batch from start through compile, quarantine, and reprocess. A `QualityAssurancePharmacist` performs the independent quality-control work — running QC tests, releasing or rejecting batches, returning quarantined lots to service, and operating recalls — and by design is a different person from the compiler. A `DispensingPharmacist` dispenses 503A patient units and distributes 503B office-use units, and manages prescriptions at the point of sale. Every role may read and list every resource. The precise per-endpoint authorization is enumerated in §4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties broken by ascending `id`.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Facility Clock

Most resources in this system are first-class records that carry a standard set of system-managed fields. Every such resource has an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording when it was created, an `updated_at` timestamp (same format) refreshed on every mutation, and an integer `version` that begins at its initial value of `1` and increments by one on every modification to the resource. This `version` is the basis for the optimistic concurrency control described in §2.7.

One entity is deliberately leaner. An `EnvironmentalLog` is an immutable monitoring reading: it carries only `id` and `created_at`, and has neither an `updated_at` field nor a `version` field. Once written, an environmental reading is never mutated.

Time in this system is not wall-clock time. Each `Facility` owns a deterministic logical clock, exposed as `current_utc`, which is initialized to `1970-01-01T00:00:00.000Z` when the facility is created and thereafter advances only when an operator explicitly sets it through the clock-set capability. Every time-dependent rule in the system — beyond-use dating, prescription expiry, ingredient-lot expiry, the rolling anticipatory window, and the stamping of reading timestamps — reads this facility clock rather than the host's real time. When the clock is set forward, subsequent reads of a prescription or an ingredient lot lazily re-evaluate whether that resource has expired.

### 2.5. Hierarchical Consistency, Cascades, and Nested Retrieval

The collections in this system are flat siblings under the common prefix, linked to one another by foreign-key fields carried in request bodies (such as `facility_id`, `master_formulation_record_id`, `compounding_batch_id`, `ingredient_lot_id`, `prescription_id`, and `finished_preparation_id`) rather than by nesting in the URL. Where an endpoint path does contain more than one identifier, the system validates those identifiers left to right and rejects the request at the first one that does not resolve to an existing resource, returning that resource's specific not-found error before any later identifier or business rule is considered.

Many operations in this domain do not touch a single record in isolation; they cascade across related records. Releasing a batch advances child finished preparations; rejecting a batch both rejects those units and restores ingredient inventory; recording a failed sterility or endotoxin test quarantines the lots that fed the batch; and a recall ripples through finished units, prescriptions, and the anticipatory ledger. Wherever such a cascade occurs, every affected first-class resource independently has its `updated_at` refreshed; `version` increments are called out explicitly in §3 where they matter for concurrency. The detailed cascade rules live in the workflow narratives of §3.

### 2.6. Precision, Rounding, and Derived-Field Reconciliation

Numeric results in this system are computed with fixed precision. Potency-adjusted active grams are rounded to four decimal places using round-half-up, and a lot's remaining grams are likewise carried to four decimal places. Yield variance percentages are rounded to two decimal places using round-half-up. Beyond-use dating is computed in whole days of UTC datetime arithmetic. Unit counts — units prescribed, units dispensed, theoretical and actual yield, and anticipatory consumed and remaining units — are integers.

Derived quantities are never accepted as free input; they are reconciled from primary events. A lot's `remaining_grams`, a prescription's `units_dispensed`, a batch's `yield_variance_pct`, and an anticipatory ledger's `consumed_units` and `remaining_units` are all computed from the underlying usage rows, dispense events, and batch states. The exact formulas appear in §3 alongside the workflows that produce them.

### 2.7. Optimistic Concurrency Control on Batch Release

Batch release is the one mutation in this system guarded by optimistic concurrency control. The release operation requires a non-optional `expected_batch_version` field in its request body, carrying the client's last observed `version` of the target `CompoundingBatch`. Before performing the release, the server compares `expected_batch_version` against the batch's current `version`. If they do not match — meaning a prior release has already advanced the batch's version since the client last read it — the release is rejected with `ERR_STALE_VERSION` and HTTP status 412. This protects against a stale releaser double-crediting the anticipatory ledger or re-releasing finished preparations that have already been released. No other endpoint in the system takes a version field; release is the sole holder of this contract.

### 2.8. Segregation of Duties and the Quality-Assurance Wall

A foundational compliance control separates the person who compiles a batch from the person who releases it. The `compiled_by_user_id` recorded at compile and the `released_by_user_id` recorded at release must be two different operators. The detailed enforcement, including the error returned when the same operator attempts both, is described with the release workflow in §3.

### 2.9. Registration Type, Sterility, and the 503A/503B Divide

Each facility declares a `registration_type` of either `503A` or `503B`, and this single attribute governs a family of downstream rules: whether a batch may be compounded for office use at all, how beyond-use dating is capped, and how a finished unit may leave the facility. Separately, each formulation's sterility is derived rather than entered — a master formulation record's `is_sterile` flag is true exactly when its dosage form is a sterile form, and sterility in turn governs whether USP <797> applies and whether sterility and endotoxin testing are mandatory before release. These divides are woven through the workflows of §3; they are surfaced here because they cut across nearly every business rule.

## 3. Business Logic & Workflows

### 3.1. Facilities and the Deterministic Clock

The root of every data tree is a **Facility**, created by a `SystemAdmin`. Creation supplies the facility's `name`, its `registration_type` (one of `503A` or `503B`), and its `state_code` (the two-letter US state of licensure). On creation the facility's `current_utc` clock is initialized to `1970-01-01T00:00:00.000Z`.

Because all time-dependent behavior reads the facility clock, a `SystemAdmin` is given an explicit, admin-only test-driving capability that advances a facility's logical clock to a supplied absolute UTC instant. The target instant is provided as `to_iso8601`, and setting the clock causes subsequent reads to lazily re-evaluate prescription and ingredient-lot expiry against the new `current_utc`. This capability is the only way the clock moves; no other operation advances it implicitly.

### 3.2. Master Formulation Records and the Anticipatory Ledger

A `CompoundingPharmacist` authors a **Master Formulation Record** (MFR), the formula/master record that every batch is compounded against. Creation supplies the owning `facility_id`, the preparation `name`, the `dosage_form`, the base nonsterile beyond-use window `default_bud_days_nonsterile` (at least 1), the nominal `theoretical_yield_units` a full batch yields (at least 1), and the office-use anticipatory cap `anticipatory_max_units` (zero or more). The rolling window length `anticipatory_window_days` may be supplied; when omitted it defaults to 30 days, and when supplied it must be at least 1.

The `dosage_form` is one of `ORAL_SOLID`, `ORAL_LIQUID`, `TOPICAL`, `NONSTERILE_OTHER`, `STERILE_AQUEOUS`, or `STERILE_NONAQUEOUS`. From it the system computes the read-only `is_sterile` flag: the record is sterile exactly when its dosage form is `STERILE_AQUEOUS` or `STERILE_NONAQUEOUS`. A fresh record begins with `status` of `ACTIVE`. A `CompoundingPharmacist` may later retire the record, moving its `status` to `RETIRED`; retire carries no state precondition and simply sets `status` to `RETIRED` (an already-`RETIRED` record remains `RETIRED`, with its `updated_at` refreshed and `version` incremented). A `RETIRED` record accepts no new batch starts, and an attempt to start a batch against a retired formula is rejected with `ERR_MFR_RETIRED`.

Creating a master formulation record also creates exactly one **Anticipatory Limit Ledger** bound to it through `master_formulation_record_id` — one ledger per formula. This ledger is the rolling accounting record that caps 503B office-use anticipatory compounding. Three of its quantities are always derived against the facility clock at read time. The `window_start_utc` is the left edge of the rolling window, computed as the facility's `current_utc` minus the formula's `anticipatory_window_days`. The `consumed_units` is the sum of `actual_yield_units` over every office-use batch of this formula that is currently in `RELEASED` status and whose `released_at_utc` falls on or after `window_start_utc`; batches that were rejected or recalled are excluded from this sum, and the left window edge is inclusive. The `remaining_units` is the formula's `anticipatory_max_units` minus `consumed_units`, floored at zero so it never goes negative. The ledger can be read directly, and it can also be reached as a computed read for a given formula; in both cases the three derived quantities are recomputed against the current clock at the moment of the read.

### 3.3. Ingredient Lots, Potency, and Inventory Reconciliation

Raw components enter the system as **Ingredient Lots**, received into inventory by a `CompoundingPharmacist`. Receiving a lot supplies the owning `facility_id`, the `component_name` (the API or excipient chemical name), the supplier `lot_number`, the certificate-of-analysis `labeled_potency_pct` (assayed potency as a percent of label, strictly greater than 0 and at most 200), the `initial_grams` received (strictly greater than 0), and the manufacturer `expiration_utc`. Two further fields are optional. The measured `endotoxin_eu_per_mg` raw-component endotoxin burden defaults to 0 and is relevant only for sterile compounding; it must be zero or more. The `parent_lot_id` may be supplied to mark this lot as a split or re-assayed child of a source lot, establishing a self-reference to another ingredient lot.

A freshly received lot begins with `status` of `AVAILABLE` and with its `remaining_grams` equal to `initial_grams`. From that point, `remaining_grams` is a reconciled quantity: it equals `initial_grams` minus the sum of `grams_used` across every usage row of this lot that belongs to a batch which is neither in `DRAFT` nor `REJECTED` status. In other words, charging a lot to a draft batch reserves nothing against inventory, starting a batch consumes the charged grams, and rejecting a batch restores them. Remaining grams are carried to four decimal places.

A lot's `status` is one of `AVAILABLE`, `QUARANTINED`, `EXPIRED`, or `DISCARDED`. A lot moves from `AVAILABLE` to `QUARANTINED` when a contamination trace implicates it (see the QC failure cascade in §3.6), and a `QualityAssurancePharmacist` may return a `QUARANTINED` lot to `AVAILABLE` after investigation; attempting this return on a lot that is not currently `QUARANTINED` is rejected with `ERR_BATCH_NOT_IN_STATE`. Expiry is evaluated lazily against the facility clock: reading a lot whose `expiration_utc` is at or before the facility's `current_utc`, and whose status was `AVAILABLE`, lazily transitions that lot to `EXPIRED`.

### 3.4. Environmental Monitoring under USP <795> and <797>

Cleanroom conditions are documented as **Environmental Log** readings, which a `QualityAssurancePharmacist` or a `CompoundingPharmacist` may record. Each reading names the `facility_id`, the `usp_chapter` it documents (`USP_795` or `USP_797`), the monitored `reading_type` (one of `ISO_PARTICLE_COUNT`, `VIABLE_AIR_CFU`, `SURFACE_CFU`, `ROOM_TEMP_C`, or `ROOM_HUMIDITY_PCT`), the numeric `measured_value`, and the `action_limit` that reading must respect. All monitored parameters here are upper-bounded, so the system computes the read-only `in_spec` flag as true exactly when the `measured_value` is at most the `action_limit`, and false otherwise. The reading's timestamp, `reading_utc`, is stamped from the facility's `current_utc` at the moment the reading is logged. Environmental readings are immutable once written. Their relevance to release — specifically, that an out-of-spec `USP_797` reading within a sterile batch's window blocks that batch's release — is detailed in §3.7.

### 3.5. Prescriptions (503A Patient-Specific)

A 503A patient-specific preparation begins with a **Prescription**, which a `DispensingPharmacist` or a `CompoundingPharmacist` may create. Creating a prescription supplies the `facility_id`, the `master_formulation_record_id` of the formula prescribed, the `patient_name`, the prescriber's `prescriber_npi` (National Provider Identifier), the `units_prescribed` the prescription authorizes (at least 1), and the `written_utc` date the prescription was written. A new prescription begins with `status` of `ACTIVE` and a `units_dispensed` running total of 0.

The `units_dispensed` field is reconciled, not entered: it is a running count of finished units handed out against this prescription, incremented by each patient dispense and decremented when a recall claws a dispensed unit back. When the prescription is `ACTIVE` and its `units_dispensed` reaches its `units_prescribed` on a dispense, the prescription automatically transitions from `ACTIVE` to `FILLED`. A `DispensingPharmacist` may cancel a prescription, moving it from `ACTIVE` to `CANCELLED`, but only while the prescription is still `ACTIVE` — otherwise the cancel is rejected with `ERR_PRESCRIPTION_NOT_ACTIVE` — and only while no units have yet been dispensed; a cancel attempt when `units_dispensed` is greater than zero is rejected with `ERR_PRESCRIPTION_HAS_DISPENSES`. Finally, prescription validity is bounded in time: when the facility's `current_utc` is strictly later than the `written_utc` plus 180 days, the prescription is considered `EXPIRED`. This expiry is evaluated lazily whenever the prescription is read or used as a precondition of a dispense.

### 3.6. The Compounding Batch: From Draft Through Compile

The central production entity is the **Compounding Batch**, opened in `DRAFT` status by a `CompoundingPharmacist`. Opening a batch supplies the `facility_id`, the `master_formulation_record_id` of the formula being compounded, the `purpose` of the run, and — conditionally — a `prescription_id`. The `purpose` is either `PRESCRIPTION` (a 503A patient-specific run) or `OFFICE_USE` (a 503B anticipatory or office-stock run). The two purposes have strict coherence rules at creation: a `PRESCRIPTION` batch requires a `prescription_id` whose prescription belongs to the same formula and facility, while an `OFFICE_USE` batch forbids a `prescription_id` entirely. Furthermore, a 503A facility may never create an `OFFICE_USE` batch, and `OFFICE_USE` is permitted only at a 503B facility. Any violation of this purpose/prescription coherence is rejected with `ERR_PURPOSE_PRESCRIPTION_MISMATCH`. At creation the batch also snapshots the formula's `theoretical_yield_units` into its own `theoretical_yield_units` field, freezing the nominal yield as of batch creation.

Ingredients are attached to a draft batch as **Batch Ingredient Usage** rows, each created by a `CompoundingPharmacist` and naming the `compounding_batch_id` it charges, the `ingredient_lot_id` drawn from, and the `grams_used` (strictly greater than 0). A usage row may be charged only while its batch is still `DRAFT`; charging a non-draft batch is rejected with `ERR_BATCH_NOT_IN_STATE`. On creation the system computes the row's read-only `potency_adjusted_grams` as `grams_used` multiplied by the lot's `labeled_potency_pct` divided by 100, rounded to four decimal places — the effective active grams after potency correction.

Starting a batch is the act that consumes inventory. A `CompoundingPharmacist` starts a batch, moving it from `DRAFT` to `IN_PROCESS`, only when a chain of preconditions holds, evaluated against the following requirements. The batch must currently be `DRAFT`, or the start is rejected with `ERR_BATCH_NOT_IN_STATE`. The formula must be `ACTIVE` and not `RETIRED`, or the start is rejected with `ERR_MFR_RETIRED`. At least one batch ingredient usage row must exist for the batch, or the start is rejected with `ERR_NO_INGREDIENTS_CHARGED`. Every charged lot must be in `AVAILABLE` status with an `expiration_utc` strictly later than the facility's `current_utc`, or the start is rejected with `ERR_LOT_NOT_AVAILABLE`. And every charged lot's `remaining_grams` must be at least the `grams_used` charged against it at that point, or the start is rejected with `ERR_LOT_INSUFFICIENT_GRAMS`. When all hold, the start succeeds and, as its side effect, decrements each charged lot's `remaining_grams` by the corresponding `grams_used`.

Compiling a batch is where finished units are born. A `CompoundingPharmacist` compiles an `IN_PROCESS` batch, supplying the operator-counted `actual_yield_units` (zero or more) in the body; the batch must be `IN_PROCESS` or the compile is rejected with `ERR_BATCH_NOT_IN_STATE`, and a missing or negative `actual_yield_units` is rejected with `ERR_INVALID_REQUEST`. Compile records the acting operator as `compiled_by_user_id`, computes the yield variance, stamps the beyond-use datetime, and mints the finished units. The **yield variance** (`yield_variance_pct`) is one hundred times the actual yield minus the theoretical yield, divided by the theoretical yield, rounded to two decimal places; a negative result signals under-yield. The variance must fall within plus or minus the yield tolerance of 5.00 percent — that is, a variance from negative 5.00 through positive 5.00 inclusive is acceptable, while negative 5.01 or positive 5.01 is rejected with `ERR_YIELD_OUT_OF_RANGE`.

When compile succeeds, the system mints exactly `actual_yield_units` **Finished Preparations**, each carrying the parent `compounding_batch_id`, the inherited `facility_id`, a system-minted per-unit `unit_serial` composed of the first eight characters of the batch identifier in uppercase, then a hyphen, then the unit's one-based sequence number within the batch zero-padded to four digits (so the first unit is suffixed `-0001`, the second `-0002`, and so on), the computed `label_text`, and a `beyond_use_utc` snapshotted from the batch's stamped beyond-use datetime. Each minted unit begins with `qc_status` of `AWAITING_QC` and `dispense_status` of `IN_INVENTORY`. The beyond-use datetime stamped on the batch is recorded as the batch's `assigned_bud_utc`.

The **beyond-use date** calculation deserves care because it differs by registration regime. The base window in days depends on sterility: for a sterile formula the base is 14 days when the dosage form is `STERILE_AQUEOUS` and 45 days when it is `STERILE_NONAQUEOUS`; for a nonsterile formula the base is the formula's `default_bud_days_nonsterile`. For a 503A patient-specific run (a `PRESCRIPTION` batch — the only purpose a 503A facility allows) this base window is used directly with no further cap. For a 503B office-use run (an `OFFICE_USE` batch, which only a 503B facility may create) the base window is first capped at 90 days — the outsourcing-facility stability-data limit — before anything else; concretely, the smaller of the base window and 90 days is used. So for a nonsterile formula with a 180-day nonsterile default, a 503A run keeps the full 180 days while a 503B office-use run is held to 90 days. After the regime-appropriate base window is chosen, an ingredient-expiry floor is applied: a preparation may never outlive its ingredients, so the candidate beyond-use datetime — the facility's `current_utc` plus the chosen window in whole days — is compared against the earliest `expiration_utc` among all ingredient lots referenced by the batch's usage rows (regardless of each lot's status at compile time), and the assigned beyond-use datetime is the earlier of the two. When the candidate and the earliest lot expiry coincide, the ingredient expiry is taken.

The compile-minted `label_text` is composed deterministically. It opens with a header consisting of the formula `name`, then the literal " | LOT " followed by the first eight characters of the batch identifier in uppercase, then " | BUD " followed by the beyond-use date formatted as YYYY-MM-DD. For an `OFFICE_USE` batch the header is followed by " | 503B OUTSOURCING FACILITY — OFFICE USE ONLY — NOT FOR RESALE". For a `PRESCRIPTION` batch the header is instead followed by " | RX PATIENT: " and the linked prescription's `patient_name`, then " | PRESCRIBER NPI: " and the prescription's `prescriber_npi`.

After compile, a `CompoundingPharmacist` moves a `COMPILED` batch to `QUARANTINED` pending QA release; the batch must be `COMPILED` or the move is rejected with `ERR_BATCH_NOT_IN_STATE`. A quarantined batch is not yet final — it may be reworked. Reprocessing a batch returns it from `QUARANTINED` to `IN_PROCESS` so it can be re-compiled. Reprocess is permitted only when the batch is `QUARANTINED` (otherwise `ERR_BATCH_NOT_IN_STATE`) and only when no finished preparation of the batch has a `dispense_status` of `DISPENSED` (otherwise `ERR_BATCH_HAS_DISPENSED_UNITS`). As its side effects, reprocess voids and deletes all finished preparations minted by the prior compile and clears the batch's `compiled_by_user_id`, `actual_yield_units`, `yield_variance_pct`, and `assigned_bud_utc`.

### 3.7. Quality Control, Endotoxin Testing, and the Contamination Cascade

Quality is established through **Quality Control Tests**, which a `QualityAssurancePharmacist` adds to a batch. Adding a test supplies the `compounding_batch_id`, the `test_type` (one of `POTENCY_ASSAY`, `STERILITY`, `ENDOTOXIN`, or `VISUAL_INSPECTION`), and optionally a numeric `measured_value` together with the inclusive acceptance bounds `lower_limit` and `upper_limit`; pass/fail-only tests omit the numeric value. A test may be added only while the parent batch is in `COMPILED` or `QUARANTINED` status, or the add is rejected with `ERR_BATCH_NOT_IN_STATE`. A new test begins with `result` of `PENDING`.

A test is worked in two steps. A `QualityAssurancePharmacist` first begins the test, moving it from `PENDING` to `IN_PROGRESS`; the test must be `PENDING` (otherwise `ERR_QC_NOT_IN_STATE`) and its parent batch must be in `COMPILED` or `QUARANTINED` status (otherwise `ERR_BATCH_NOT_IN_STATE`). The pharmacist then records the result on an `IN_PROGRESS` test (otherwise `ERR_QC_NOT_IN_STATE`), supplying a `measured_value` and/or a `pass` flag as appropriate to the test type. Recording auto-evaluates the test to either `PASSED` or `FAILED`. For an ordinary numeric test, the result is `PASSED` when the `measured_value` is at least the `lower_limit` and at most the `upper_limit`, and `FAILED` when it falls below the `lower_limit` or above the `upper_limit`. For a pass/fail-only test, the result is `PASSED` when the body `pass` flag is true and `FAILED` when it is false. An `ENDOTOXIN` test is evaluated by the specialized projection described next.

The **endotoxin evaluation** is multi-input and route-tiered. The batch's total active milligrams are 1000 times the sum of `potency_adjusted_grams` across the batch's usage rows. The per-unit endotoxin ceiling depends on route: it is 175 EU per unit when the formula's dosage form is `STERILE_AQUEOUS` (the injectable case) and 350 EU per unit otherwise. The `measured_value` recorded on an endotoxin test is reported as EU per milligram of the preparation, so the projected endotoxin per unit is that `measured_value` multiplied by the total active milligrams divided by the batch's `theoretical_yield_units`. The test is `PASSED` when the projected endotoxin per unit is at most the route ceiling and `FAILED` otherwise; the comparison is made at full floating-point precision and the boundary value passes.

A failed sterility or endotoxin test on a sterile batch triggers a **contamination-trace cascade**. When a recorded test of type `STERILITY` or `ENDOTOXIN` evaluates to `FAILED` and the parent batch's formula is sterile, the system quarantines every ingredient lot charged to that batch whose status is currently `AVAILABLE`, moving each such lot from `AVAILABLE` to `QUARANTINED`. This is how a contamination signal traces back to suspect raw materials.

### 3.8. Releasing or Rejecting a Batch

Releasing a batch is the most heavily guarded transition in the system, performed by a `QualityAssurancePharmacist` and moving the batch from `QUARANTINED` to `RELEASED`. The release body must carry `expected_batch_version`. The checks are evaluated in a fixed order, and the order matters because it determines which error surfaces first when more than one condition is wrong. First, the batch must be `QUARANTINED`, or the release is rejected with `ERR_BATCH_NOT_IN_STATE`. Next, the optimistic-concurrency check: the supplied `expected_batch_version` must equal the batch's current `version`, or the release is rejected with `ERR_STALE_VERSION` (HTTP 412); this is checked after the state precondition but before the segregation, QC, environmental, and anticipatory checks. Then segregation of duties: the releasing operator's `X-User-ID` must differ from the batch's `compiled_by_user_id`, or the release is rejected with `ERR_SEGREGATION_OF_DUTIES`. Then the QC gate: every required QC test must exist and have `result` of `PASSED`, and none may be `FAILED`. The required set is always `POTENCY_ASSAY` and `VISUAL_INSPECTION`, plus `STERILITY` and `ENDOTOXIN` additionally when the formula is sterile; if any required test is missing or not yet passed the release is rejected with `ERR_QC_INCOMPLETE`, while any required test that is `FAILED` rejects the release with `ERR_QC_FAILED`. Then, for sterile batches only, the environmental gate: there must be no `USP_797` environmental log with `in_spec` false whose `reading_utc` falls within the window from the batch's start through the present; such an excursion rejects the release with `ERR_ENVIRONMENTAL_EXCURSION`. Finally, for an `OFFICE_USE` batch only, the anticipatory gate: the formula's anticipatory ledger `remaining_units` must be at least the batch's `actual_yield_units`, or the release is rejected with `ERR_ANTICIPATORY_LIMIT_EXCEEDED`.

When every gate is cleared, release applies its side effects: it records the releasing operator as `released_by_user_id`, sets the batch's `released_at_utc` to the facility's `current_utc` (this timestamp anchors the rolling anticipatory window), increments the batch's `version` by one, and transitions every child finished preparation's `qc_status` from `AWAITING_QC` to `QC_RELEASED`. For an `OFFICE_USE` batch, release also recomputes the formula's anticipatory ledger `consumed_units` and `remaining_units` so the just-released yield is reflected in the rolling window.

Rejecting a batch is the QA disposition opposite to release. A `QualityAssurancePharmacist` may reject a batch that is in either `QUARANTINED` or `COMPILED` status, moving it to `REJECTED`; a reject attempt from any other state is rejected with `ERR_BATCH_NOT_IN_STATE`. Rejection transitions every child finished preparation's `qc_status` to `QC_REJECTED` and, as a compensating restock that conserves total grams, restores each charged lot's `remaining_grams` by the `grams_used` that had been consumed at start. Both `REJECTED` and `RECALLED` are terminal batch states.

### 3.9. Dispensing and Distribution

A finished preparation carries two independent status dimensions that evolve separately until a recall overrides one of them. The `qc_status` dimension runs `AWAITING_QC` to either `QC_RELEASED` or `QC_REJECTED`, following the parent batch's release or rejection. The `dispense_status` dimension runs `IN_INVENTORY` to `DISPENSED`, with a `RECALLED` value that supersedes either of those when a recall strikes.

A `DispensingPharmacist` dispenses or distributes a single finished unit. The request supplies the `facility_id`, the `finished_preparation_id` of the specific unit, and — by channel — either a `prescription_id` or an `office_account_name`. The channel must cohere with the unit's batch purpose: a 503A `PRESCRIPTION` unit requires an active same-formula `prescription_id` and forbids an `office_account_name`, while a 503B `OFFICE_USE` unit requires an `office_account_name` (the receiving clinic or office name) and forbids a `prescription_id`. A channel mismatch is rejected with `ERR_DISPENSE_CHANNEL_MISMATCH`; this same `ERR_DISPENSE_CHANNEL_MISMATCH` is also returned when the supplied `prescription_id` resolves to a prescription that is not currently `ACTIVE`, or whose `master_formulation_record_id` does not match the unit's batch formula. This channel check (including the active and same-formula conditions) is evaluated before the unit-state preconditions below. Beyond the channel, three unit-state preconditions hold: the unit's `qc_status` must be `QC_RELEASED`, or the dispense is rejected with `ERR_UNIT_NOT_RELEASED`; the unit's `dispense_status` must be `IN_INVENTORY`, or the dispense is rejected with `ERR_UNIT_NOT_IN_INVENTORY`; and the facility's `current_utc` must be at or before the unit's `beyond_use_utc`, or the dispense is rejected with `ERR_BEYOND_USE_DATE_PASSED`.

A successful dispense creates a **Dispense** record, moves the unit's `dispense_status` from `IN_INVENTORY` to `DISPENSED`, and stamps the record's `dispensed_utc` from the facility clock. For a 503A patient unit, the dispense additionally increments the linked prescription's `units_dispensed` by one, and if that brings `units_dispensed` to equal `units_prescribed`, the prescription transitions from `ACTIVE` to `FILLED`.

### 3.10. Recalls and Their Cascades

A **Recall** is initiated by a `QualityAssurancePharmacist` against a released batch. Initiation supplies the `facility_id`, the `compounding_batch_id` of the batch under recall, the `reason` (one of `STERILITY_FAILURE`, `POTENCY_OOS`, `ENDOTOXIN_OOS`, `ENVIRONMENTAL_EXCURSION`, or `LABELING_ERROR`), and the FDA `classification` (`CLASS_I`, `CLASS_II`, or `CLASS_III`). The target batch must be `RELEASED`, or the initiation is rejected with `ERR_BATCH_NOT_RELEASED`. A new recall begins with `status` of `INITIATED` and a `units_reconciled` count of 0.

Initiating a recall fires a broad cascade. The batch itself transitions from `RELEASED` to `RECALLED`. Every finished preparation of the batch has its `dispense_status` set to `RECALLED`, overriding whatever `IN_INVENTORY` or `DISPENSED` value it held. The recall snapshots `units_in_scope` as the count of finished preparations belonging to the batch at the moment of initiation. For every unit that had been dispensed against a 503A prescription, that prescription's `units_dispensed` is decremented by one, and if the prescription had been `FILLED` it reverts to `ACTIVE`. And if the recalled batch was an `OFFICE_USE` batch, the formula's anticipatory ledger `consumed_units` is recomputed, since a recalled batch leaves the rolling-window total.

A recall is then worked through a small lifecycle by a `QualityAssurancePharmacist`. Advancing a recall moves it from `INITIATED` to `IN_PROGRESS` (it must be `INITIATED`, else `ERR_RECALL_NOT_IN_STATE`). Reconciling a recall recomputes `units_reconciled` as the count of in-scope units now in `RECALLED` dispense status and moves the recall from `IN_PROGRESS` to `RECONCILED` — but only when `units_reconciled` equals `units_in_scope`; if units remain outstanding the reconcile is rejected with `ERR_RECALL_UNITS_OUTSTANDING` (the recomputed `units_reconciled` is nonetheless persisted and the recall's `updated_at` and `version` are refreshed, but its `status` stays `IN_PROGRESS`), and a reconcile attempted from any non-`IN_PROGRESS` state is rejected with `ERR_RECALL_NOT_IN_STATE`. A recall under reconciliation may be reopened to widen scope, moving it from `IN_PROGRESS` back to `INITIATED` (it must be `IN_PROGRESS`, else `ERR_RECALL_NOT_IN_STATE`). Finally, closing a recall moves it from `RECONCILED` to `CLOSED` (it must be `RECONCILED`, else `ERR_RECALL_NOT_IN_STATE`); `CLOSED` is terminal.

### 3.11. Referential Integrity and Existence Checks

Across all of the above, the system applies a uniform layer of structural validation ahead of business rules. Authentication and role checks come first, as described in §2.1. Then, for any endpoint whose path names a resource, the system confirms that each path identifier resolves to an existing resource — returning the resource-specific not-found error such as `ERR_FACILITY_NOT_FOUND`, `ERR_MFR_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_QC_TEST_NOT_FOUND`, `ERR_FINISHED_PREPARATION_NOT_FOUND`, `ERR_RECALL_NOT_FOUND`, or `ERR_ENVIRONMENTAL_LOG_NOT_FOUND`. Then the request body itself is validated structurally: malformed bodies, missing required fields, type mismatches, and out-of-range numerics (such as a negative `grams_used` or an `actual_yield_units` below zero) are rejected with `ERR_INVALID_REQUEST`, and an enum field carrying a value outside its declared set is rejected with `ERR_INVALID_ENUM_VALUE`. Only after this body-structure validation passes does the system, for create operations that carry foreign keys in the body — any of `facility_id`, `master_formulation_record_id`, `prescription_id`, `ingredient_lot_id`, `finished_preparation_id`, or `compounding_batch_id` — confirm that each referenced resource exists within the same facility, rejecting the create with `ERR_REFERENCED_RESOURCE_NOT_FOUND` otherwise. Only after these structural gates pass does the system evaluate the state-machine and business rules described throughout §3.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and the clock-set capability — return a `200 OK` status code. All read and list operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pharmacy-compounding/facilities` | Create a compounding facility | SystemAdmin |
| GET | `/pharmacy-compounding/facilities` | List facilities | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/facilities/{fid}` | Get a facility | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/facilities/{fid}/_clock/set` | Set the facility's deterministic clock | SystemAdmin |
| POST | `/pharmacy-compounding/master-formulation-records` | Create a master formulation record | CompoundingPharmacist |
| GET | `/pharmacy-compounding/master-formulation-records` | List master formulation records | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/master-formulation-records/{mid}` | Get a master formulation record | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/master-formulation-records/{mid}/retire` | Retire a master formulation record | CompoundingPharmacist |
| GET | `/pharmacy-compounding/master-formulation-records/{mid}/anticipatory-ledger` | Read the rolling anticipatory ledger for the formula | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/anticipatory-ledgers` | List anticipatory ledgers | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/anticipatory-ledgers/{alid}` | Get an anticipatory ledger by id | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/ingredient-lots` | Receive an ingredient lot into inventory | CompoundingPharmacist |
| GET | `/pharmacy-compounding/ingredient-lots` | List ingredient lots | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/ingredient-lots/{lid}` | Get an ingredient lot | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/ingredient-lots/{lid}/release-quarantine` | Return a quarantined lot to available | QualityAssurancePharmacist |
| POST | `/pharmacy-compounding/environmental-logs` | Record a USP <795>/<797> environmental reading | QualityAssurancePharmacist, CompoundingPharmacist |
| GET | `/pharmacy-compounding/environmental-logs` | List environmental logs | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/environmental-logs/{eid}` | Get an environmental log entry | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/prescriptions` | Create a patient-specific prescription | DispensingPharmacist, CompoundingPharmacist |
| GET | `/pharmacy-compounding/prescriptions` | List prescriptions | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/prescriptions/{pid}` | Get a prescription | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/prescriptions/{pid}/cancel` | Cancel an active prescription with no dispenses | DispensingPharmacist |
| POST | `/pharmacy-compounding/compounding-batches` | Open a draft compounding batch | CompoundingPharmacist |
| GET | `/pharmacy-compounding/compounding-batches` | List compounding batches | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/compounding-batches/{bid}` | Get a compounding batch | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/compounding-batches/{bid}/start` | Begin compounding; consume charged grams | CompoundingPharmacist |
| POST | `/pharmacy-compounding/compounding-batches/{bid}/compile` | Compile; record yield, stamp BUD, mint units | CompoundingPharmacist |
| POST | `/pharmacy-compounding/compounding-batches/{bid}/quarantine` | Move a compiled batch to quarantine | CompoundingPharmacist |
| POST | `/pharmacy-compounding/compounding-batches/{bid}/reprocess` | Rework a quarantined batch back to in-process | CompoundingPharmacist |
| POST | `/pharmacy-compounding/compounding-batches/{bid}/release` | QA releases a quarantined batch | QualityAssurancePharmacist |
| POST | `/pharmacy-compounding/compounding-batches/{bid}/reject` | QA rejects a batch | QualityAssurancePharmacist |
| POST | `/pharmacy-compounding/batch-ingredient-usages` | Charge an ingredient lot to a draft batch | CompoundingPharmacist |
| GET | `/pharmacy-compounding/batch-ingredient-usages` | List batch ingredient usages | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/batch-ingredient-usages/{uid}` | Get a batch ingredient usage by id | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/qc-tests` | Add a QC test to a compiled batch | QualityAssurancePharmacist |
| GET | `/pharmacy-compounding/qc-tests` | List QC tests | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/qc-tests/{qid}` | Get a QC test | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/qc-tests/{qid}/begin` | Move a QC test to in-progress | QualityAssurancePharmacist |
| POST | `/pharmacy-compounding/qc-tests/{qid}/record` | Record a QC result; auto pass/fail | QualityAssurancePharmacist |
| GET | `/pharmacy-compounding/finished-preparations` | List finished preparations | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/finished-preparations/{pid}` | Get a finished preparation | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/dispenses` | Dispense or distribute a finished unit | DispensingPharmacist |
| GET | `/pharmacy-compounding/dispenses` | List dispenses | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/dispenses/{did}` | Get a dispense record by id | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/recalls` | Initiate a recall against a released batch | QualityAssurancePharmacist |
| GET | `/pharmacy-compounding/recalls` | List recalls | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| GET | `/pharmacy-compounding/recalls/{rid}` | Get a recall | SystemAdmin, CompoundingPharmacist, QualityAssurancePharmacist, DispensingPharmacist |
| POST | `/pharmacy-compounding/recalls/{rid}/advance` | Advance a recall to in-progress | QualityAssurancePharmacist |
| POST | `/pharmacy-compounding/recalls/{rid}/reconcile` | Reconcile in-scope units | QualityAssurancePharmacist |
| POST | `/pharmacy-compounding/recalls/{rid}/reopen` | Reopen a recall to widen scope | QualityAssurancePharmacist |
| POST | `/pharmacy-compounding/recalls/{rid}/close` | Close a reconciled recall | QualityAssurancePharmacist |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_MFR_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_QC_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_FINISHED_PREPARATION_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_ENVIRONMENTAL_LOG_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM_VALUE` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_BATCH_NOT_IN_STATE` | 409 Conflict |
| `ERR_BATCH_NOT_RELEASED` | 409 Conflict |
| `ERR_QC_NOT_IN_STATE` | 409 Conflict |
| `ERR_RECALL_NOT_IN_STATE` | 409 Conflict |
| `ERR_PRESCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_MFR_RETIRED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_QC_INCOMPLETE` | 409 Conflict |
| `ERR_QC_FAILED` | 409 Conflict |
| `ERR_ENVIRONMENTAL_EXCURSION` | 409 Conflict |
| `ERR_NO_INGREDIENTS_CHARGED` | 409 Conflict |
| `ERR_LOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_LOT_INSUFFICIENT_GRAMS` | 409 Conflict |
| `ERR_PURPOSE_PRESCRIPTION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_YIELD_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_BEYOND_USE_DATE_PASSED` | 409 Conflict |
| `ERR_DISPENSE_CHANNEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_UNIT_NOT_RELEASED` | 409 Conflict |
| `ERR_UNIT_NOT_IN_INVENTORY` | 409 Conflict |
| `ERR_BATCH_HAS_DISPENSED_UNITS` | 409 Conflict |
| `ERR_PRESCRIPTION_HAS_DISPENSES` | 409 Conflict |
| `ERR_ANTICIPATORY_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_RECALL_UNITS_OUTSTANDING` | 409 Conflict |
