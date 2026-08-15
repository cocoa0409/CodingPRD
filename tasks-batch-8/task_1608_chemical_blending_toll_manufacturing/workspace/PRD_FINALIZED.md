# Chemical Blending & Toll Manufacturing API — Product Requirements Document

## 1. Introduction

A toll blender manufactures chemical products on behalf of customers who supply both the recipe and the raw materials. The blender's plant is a tank farm: vessels must be reserved, verified clean, charged with customer-owned consignment stock in a defined order, mixed, held for quality review, drained, packaged, placarded, and shipped — while every residual "heel" of customer material is either returned to consignment or sent to waste under a manifest. Because the blender never owns the inventory, the books must reconcile to the kilogram at all times, and because the products are hazardous, storage zoning, tank-to-product segregation, safety data sheets, and DOT placarding are hard gates on the workflow rather than paperwork afterthoughts.

This document specifies the API that runs that plant. It covers customer onboarding and credit standing, pricing agreements under two commercial models (a flat-plus-per-kilogram tolling fee, or a formulated price per kilogram of actual output with an over-yield credit split), recipe approval with hazard profiling, consignment lot intake and derived inventory accounting, tank cleaning and QA validation under segregation of duties, the batch job lifecycle from intake to QA disposition, SDS authoring and issuance, packaging and shipment dispatch, and heel disposition. All resources are mounted under `/toll-operations`. The design favors immediate consistency: every derived quantity described here is reconciled at the moment the underlying event occurs, and contested writes are guarded by optimistic concurrency.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API: authentication, response envelopes, pagination, identity and versioning conventions, the logical clock, hazard segregation policy, numeric precision, optimistic concurrency, and the order in which validations are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes six operational roles — `QualityManager`, `BatchScheduler`, `TankOperator`, `QAValidator`, `SDSAuthor`, and `ShippingClerk` — plus the label `Any`, which denotes the read-only operations shared by all authenticated roles. A request whose role is not permitted for the targeted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

For each of `QualityManager`, `BatchScheduler`, `TankOperator`, `QAValidator`, `SDSAuthor`, `ShippingClerk`, and `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `validated_by` on a cleaning record when a `QAValidator` approves the cleaning — but it never compares `X-User-ID` to any entity's `id`. The single place where two `X-User-ID` values are compared to each other is the cleaning-validation segregation-of-duties rule described in §3.5.

Duties are divided as follows. A `QualityManager` owns customers, pricing agreements, recipes, tank registration, and the logical clock. A `BatchScheduler` owns raw-material lot intake and batch-job intake, release, and cancellation. A `TankOperator` executes the physical floor work: committing charges, starting charging and mixing, holding batches for QA, performing cleaning, and recording heel disposals. A `QAValidator` validates cleaning records and completes or rejects batches, and is deliberately segregated from the `TankOperator` who performed the work. An `SDSAuthor` authors and issues safety data sheets. A `ShippingClerk` owns package configuration and the shipment lifecycle.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Several collections support additional filters. The recipe list accepts `customer_id`. The tank list accepts `occupied_by_batch_id`. The customer-scoped batch-job list accepts `status`, and the top-level batch-job collection accepts `customer_id`, `recipe_id`, `pricing_agreement_id`, `tank_id`, and `status`. The top-level charge and heel-disposal collections accept both `batch_job_id` and `raw_material_lot_id`, while the top-level SDS, package-config, and shipment collections accept `batch_job_id`.

### 2.4. Resource Identity and Change Tracking

Every resource in the system — customers, pricing agreements, raw-material lots, recipes, tanks, cleaning records, batch jobs, batch charges, SDS documents, package configurations, shipments, and heel disposal records — carries the same four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits, and `updated_at` follows the same format and is refreshed on every mutation. The `version` is an integer that starts at 1 when the resource is created and increments on every mutation of that resource.

Mutation includes cascade-driven change. When a batch release reserves a tank, the tank's `version` increments and its `updated_at` refreshes even though the client addressed the batch, not the tank. The same applies to lot quantities reconciled by charge commits and heel postings, to agreements superseded by a sibling's activation, and to an SDS superseded by re-authoring. Clients that cache any resource must therefore treat `version` as the authoritative freshness marker.

### 2.5. The Logical Clock

The server maintains a logical clock rather than consulting wall-clock time. At startup, and until it is explicitly set, the clock reads exactly 2026-08-01T00:00:00Z; it never silently falls back to wall-clock time. A `QualityManager` may advance the clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. This clock is what temporal business rules consult — most importantly the pricing-agreement window check performed when a batch is released (§3.6).

### 2.6. Hazard Classes, Storage Zones, and Segregation Policy

Every material and product is classified into exactly one GHS hazard class: `FLAMMABLE`, `OXIDIZER`, `ACID`, `BASE`, `TOXIN`, or `NON_HAZ`. For hazard profiling the classes have a strict severity order, from most to least severe: `FLAMMABLE`, then `OXIDIZER`, then `TOXIN`, then `ACID`, then `BASE`, then `NON_HAZ`.

The warehouse and tank farm are divided into six storage zones — `Z_FLAM`, `Z_OXID`, `Z_ACID`, `Z_BASE`, `Z_TOXIC`, and `Z_GENERAL` — and each zone admits exactly one class: `Z_FLAM` admits only `FLAMMABLE` material, `Z_OXID` only `OXIDIZER`, `Z_ACID` only `ACID`, `Z_BASE` only `BASE`, `Z_TOXIC` only `TOXIN`, and `Z_GENERAL` only `NON_HAZ`. Beyond zoning, four class pairings are forbidden from co-location and from sequential use of the same tank without a validated cleaning in between: `FLAMMABLE` with `OXIDIZER`, `ACID` with `BASE`, `TOXIN` with `FLAMMABLE`, and `TOXIN` with `OXIDIZER`. The pairing rule is symmetric — a `FLAMMABLE` batch following an `OXIDIZER` product is exactly as forbidden as the reverse. Any placement or sequencing that violates these rules is rejected with `ERR_INCOMPATIBLE_SEGREGATION` (HTTP 409).

Cleaning efficacy is measured as residual contamination in parts per million. The acceptance limit is 50 parts per million: a cleaning record reporting `residue_ppm` at or below that limit may pass validation, while anything above it may not.

### 2.7. Units, Precision, and Rounding

Masses are expressed in kilograms. Computed masses — theoretical output, and the derived lot balances described in §3.4 — are carried to three decimal places with round-half-up rounding. Volumes computed at batch completion (`density_corrected_output_l`) are likewise carried to three decimal places with round-half-up rounding, while configured package volumes (`total_volume_l`) are whole litres. Densities are expressed in kilograms per litre at 20 degrees Celsius, and batch sizes and tank capacities in litres.

All monetary values are integer cents. Every price the system computes — the provisional quote at batch creation and the final invoice at completion — is rounded half-up to a whole cent. Yield variance is expressed as a percentage.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency, and each names its guard field explicitly.

Releasing a batch job requires the request to carry `expected_batch_job_version`, holding the batch's `version` as the client last observed it. If another writer has advanced the batch's `version` since that observation — a cancellation, or a charge commit that cascaded a version bump onto the batch — the release is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client never acts on a batch state it has not seen.

Activating a pricing agreement requires the request to carry `expected_pricing_agreement_version` with the same semantics: a mismatch against the agreement's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), covering the case where another writer has terminated the agreement or otherwise modified it since the client last read it.

Both fields are non-optional on their respective operations. No other endpoint accepts a version field. The stale-version check is evaluated after every other applicable validation, as detailed in §2.9.

### 2.9. Nested Resource Resolution and the Order of Validation

Most resources live inside a customer-scoped hierarchy, and requests targeting nested resources are validated left to right along the path: the system first confirms the customer identified by `{id}` exists, then the agreement or batch job identified by `{agreementId}` or `{batchJobId}` beneath it, then any deeper resource such as `{chargeId}`, `{recordId}`, or `{sdsId}`. The first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404), and no further checks run. Foreign-key references supplied in request bodies — `recipe_id`, `pricing_agreement_id`, `tank_id`, and `raw_material_lot_id` — must likewise resolve to existing resources, or the request fails with `ERR_NOT_FOUND`. In addition to the nested paths, top-level collections exist for batch jobs, batch charges, SDS documents, package configs, shipments, and heel disposals so that any resource remains reachable by its bare `id` (for example, a package config via its `{packageConfigId}` or a shipment via its `{shipmentId}`), supporting the filter queries listed in §2.3.

When several rules could reject the same request, the system evaluates them in a fixed order and reports the first failure. Header context comes first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_UNAUTHORIZED`), then left-to-right path existence and body foreign-key existence (`ERR_NOT_FOUND`), then source-state validity for the requested transition (`ERR_INVALID_STATE`). Business rules follow, in this relative order: customer credit standing (`ERR_CUSTOMER_CREDIT_HOLD`) ahead of tank cleanliness (`ERR_TANK_NOT_CLEAN_VALIDATED`) ahead of segregation (`ERR_INCOMPATIBLE_SEGREGATION`) ahead of cleaning segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`) ahead of pricing-agreement currency (`ERR_AGREEMENT_NOT_ACTIVE`) ahead of tank schedule overlap (`ERR_TANK_SCHEDULE_OVERLAP`) ahead of agreement-window overlap (`ERR_AGREEMENT_WINDOW_OVERLAP`) ahead of tank capacity (`ERR_BATCH_SIZE_EXCEEDS_CAPACITY`) ahead of charge completeness (`ERR_INCOMPLETE_CHARGES`) ahead of lot sufficiency (`ERR_INSUFFICIENT_LOT_QUANTITY`) ahead of recipe approval status (`ERR_RECIPE_NOT_APPROVED`) ahead of recipe composition (`ERR_RECIPE_FRACTION_SUM_INVALID`) ahead of SDS consistency (`ERR_SDS_INCONSISTENT`) ahead of SDS issuance (`ERR_SDS_NOT_ISSUED`) ahead of UN-rated packaging (`ERR_UN_RATED_PACKAGE_REQUIRED`) ahead of package volume (`ERR_PACKAGE_VOLUME_INSUFFICIENT`) ahead of placarding (`ERR_PLACARD_MISSING`) ahead of waste-manifest completeness (`ERR_WASTE_MANIFEST_REQUIRED`) ahead of heel disposition (`ERR_HEEL_NOT_DISPOSITIONED`). The optimistic-concurrency check (`ERR_STALE_VERSION`) runs last, so a request that fails any earlier rule never surfaces a stale-version rejection.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and Commercial Standing

A `QualityManager` onboards a customer by supplying its `legal_name` and, optionally, a `credit_hold` flag that defaults to false. The new customer begins in `ACTIVE` status with `version` 1. Commercial standing is managed through a small lifecycle: suspension moves a customer from `ACTIVE` to `SUSPENDED`, reinstatement returns a `SUSPENDED` customer to `ACTIVE`, and termination moves a `SUSPENDED` customer to `TERMINATED`, which is final. Each of these transitions refreshes `updated_at` and increments `version`, and each requires the correct source state — suspending a customer who is not `ACTIVE`, for instance, is rejected with `ERR_INVALID_STATE` (HTTP 409).

Termination carries an additional guard: the customer must have no in-flight batch jobs, meaning no batch in `INTAKE`, `RELEASED`, `CHARGING`, `MIXING`, or `HOLD_QA` status. Attempting to terminate around open work is rejected with `ERR_OPEN_BATCH_JOBS` (HTTP 409). The `credit_hold` flag, together with non-`ACTIVE` status, is the commercial gate on new work: a customer on credit hold or not currently `ACTIVE` can neither take new batch jobs into intake nor release them, and the rejection carries `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 403).

### 3.2. Pricing Agreements and Commercial Terms

Every batch is billed under a pricing agreement pinned at creation. A `QualityManager` drafts an agreement beneath a customer by choosing a `pricing_mode` — `TOLLING_FEE` or `FORMULATED_PRICE` — and supplying the rate card: `tolling_base_fee_cents` and `tolling_per_kg_cents` for the tolling model, `formulated_price_per_kg_cents` for the formulated model, each an integer of zero or more. The `over_yield_split_pct` field, defaulting to 50 and bounded between 0 and 100, fixes the customer's percentage share of the over-yield credit described in §3.6; the blender retains the remainder, and the field is consulted only when a batch's actual output exceeds its theoretical output. Each agreement also carries an effectiveness window from `effective_from` to `effective_to`, interpreted as a half-open interval: the agreement is usable at the `effective_from` instant and remains usable up to, but not including, `effective_to`. A new agreement starts in `DRAFT` with `version` 1; range violations such as a negative rate or an `over_yield_split_pct` outside its bounds are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Activation moves an agreement from `DRAFT` to `ACTIVE` and is a guarded write: the request must carry `expected_pricing_agreement_version` as described in §2.8, the window's `effective_from` must be strictly earlier than its `effective_to` (otherwise `ERR_INVALID_REQUEST`), and the window must be reconciled against the customer's other agreements. If another `ACTIVE` agreement for the same customer has an overlapping window, one of two things happens. When the incoming window fully covers the existing agreement's window, the existing agreement is cascaded to `SUPERSEDED` — its `version` increments and `updated_at` refreshes — and the activation proceeds. When the overlap is only partial, the activation is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP` (HTTP 409). Supersession is never retroactive: batch jobs already created keep the `pricing_agreement_id` they pinned at intake, and are billed under it. An `ACTIVE` agreement may also be terminated outright, moving it to `TERMINATED` with the usual version increment; termination requires the agreement to actually be `ACTIVE`.

### 3.3. Recipe Authoring, Approval, and Hazard Profiling

Recipes are customer-proprietary: a `QualityManager` creates one by supplying a `name`, a `revision` counter that increases monotonically within the customer's recipes of that name and must be at least 1, the owning `customer_id`, a `target_density_kg_per_l` greater than zero that converts between kilograms and litres at 20 degrees Celsius, a `theoretical_yield_pct` greater than zero and at most 100, and the `components` list. Each component names a `material_code`, a `mass_fraction_pct`, and a `charge_order`. The mass fractions across the list must sum to exactly 100.000, within a tolerance of 0.000001, and the `charge_order` values must be distinct positive integers. Composition failures at creation are rejected with `ERR_RECIPE_FRACTION_SUM_INVALID` (HTTP 422). A recipe is born in `DRAFT`.

At creation the system also computes the recipe's `highest_component_ghs`: each component's material code is looked up against the customer's raw-material lots — every lot of a given `material_code` for a customer shares the same `ghS_class` — and the class sitting highest in the severity order of §2.6 wins, with ties broken in favor of the component with the smallest `charge_order`. Approval moves the recipe from `DRAFT` to `APPROVED`, freezes `highest_component_ghs` at its approved value, and increments `version`. Approval re-verifies composition: a mass-fraction sum that misses 100.000 is again rejected with `ERR_RECIPE_FRACTION_SUM_INVALID`, while `charge_order` values that are not distinct positive integers are rejected with `ERR_RECIPE_CHARGE_ORDER_INVALID`. Retirement moves an `APPROVED` recipe to `RETIRED`, but only while no in-flight batch — one in `INTAKE`, `RELEASED`, `CHARGING`, `MIXING`, or `HOLD_QA` — references it; otherwise the retirement is rejected with `ERR_RECIPE_IN_USE` (HTTP 409). Only an `APPROVED` recipe may anchor a new batch job, as detailed in §3.6.

### 3.4. Consignment Lot Intake and Inventory Accounting

Raw materials arrive as customer-owned consignment. A `BatchScheduler` receives a lot beneath its owning customer by recording the `material_code`, the lot's `ghS_class`, the `quantity_kg_received` in kilograms (zero or more), the `storage_zone` where the lot will be shelved, and the `received_at` receipt timestamp. Intake is itself a segregation checkpoint: the lot's class must be one the chosen zone admits under the zone map of §2.6, or the receipt is rejected with `ERR_INCOMPATIBLE_SEGREGATION`. A freshly received lot starts with `quantity_kg_on_hand` equal to `quantity_kg_received` and `quantity_kg_committed` equal to zero.

Three quantities on every lot are derived, never stored by hand, and are re-evaluated whenever a charge or heel disposal touching the lot mutates. The committed balance `quantity_kg_committed` is the sum of `charged_qty_kg` across the lot's charge rows whose own status is `COMMITTED` — exactly the draws promised to batches still in flight. The on-hand balance `quantity_kg_on_hand` is `quantity_kg_received` minus the mass consumed (the sum of `charged_qty_kg` over the lot's `CONSUMED` charge rows) minus the mass sent to waste (the sum of `heel_disposed_kg` over the lot's `POSTED` heel disposal records). The spendable balance `quantity_kg_available` is then `quantity_kg_on_hand` minus `quantity_kg_committed`. Returned heels stay in consignment: a posted return does not reduce `quantity_kg_on_hand`. All three balances carry three decimal places.

Consignment ownership also constrains charging. A batch may draw only from lots owned by the batch's own customer, and a charge that promises more than the lot's `quantity_kg_available` is rejected with `ERR_INSUFFICIENT_LOT_QUANTITY` (HTTP 422) at the moment it is committed (§3.6).

### 3.5. Tank Registration, Cleaning, and QA Validation

A `QualityManager` registers each vessel with a human-readable `tank_code`, a geometric `capacity_l` greater than zero, a `working_capacity_l` that must be greater than zero and no larger than `capacity_l`, and the `current_zone` where the tank physically sits. A new tank enters service with `operational_state` set to `AVAILABLE`, `cleaning_state` set to `DIRTY`, and both `occupied_by_batch_id` and `last_product_ghs` null.

Tanks carry two independent state axes. The operational axis runs `AVAILABLE` to `RESERVED` to `IN_USE` and back to `AVAILABLE`, driven entirely by cascades from the batch lifecycle (§3.6); `OUT_OF_SERVICE` also exists as an operational value. The cleaning axis runs `DIRTY` to `CLEANING_IN_PROGRESS` to `CLEAN_PENDING_VALIDATION` to `CLEAN_VALIDATED`, with any contamination event returning the tank to `DIRTY`.

Cleaning follows a strict maker-checker protocol. A `TankOperator` opens a cleaning record on a tank that is `AVAILABLE` and `DIRTY` — any other combination is rejected with `ERR_INVALID_STATE` — supplying the `method` (one of `SOLVENT_FLUSH`, `CAUSTIC_CIP`, `STEAM`, or `DRY_PURGE`), the `started_at` and `completed_at` timestamps (completion must be strictly later than the start, or the request fails with `ERR_INVALID_REQUEST`), and the measured `residue_ppm`, zero or greater. The record is created with `validation_outcome` set to `PENDING` and `validated_by` null, and the tank moves to `CLEANING_IN_PROGRESS`. When the operator is satisfied, submitting the record moves the tank to `CLEAN_PENDING_VALIDATION`.

A `QAValidator` then decides, passing a `decision` of PASS or FAIL. Two people must be involved: the validator's `X-User-ID` must differ from the `X-User-ID` that created the record, or the validation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — this applies to both PASS and FAIL decisions. A PASS decision requires the record to still be `PENDING` and, when the tank has a non-null `last_product_ghs`, the measured `residue_ppm` to be at most the 50-parts-per-million limit; a tank that has never held product always passes the residue test. On PASS the record's `validation_outcome` becomes `PASSED`, `validated_by` records the validator's `X-User-ID`, the tank moves to `CLEAN_VALIDATED`, and its `last_product_ghs` is cleared to null. On FAIL the record becomes `FAILED` and the tank returns to `DIRTY`, ready for another attempt. Every step increments the tank's `version`.

Only a tank whose cleaning axis rests at `CLEAN_VALIDATED` may be reserved for a batch, as the next section describes.

### 3.6. The Batch Job Lifecycle: Intake to QA Disposition

A `BatchScheduler` opens a batch job beneath a customer with a payload carrying the `recipe_id`, the `pricing_agreement_id` that will bill the run (pinned at creation and frozen thereafter), the `tank_id` of the intended vessel, the `batch_size_l` ordered in litres (greater than zero), and a `scheduled_start` and `scheduled_end` that must form a strict ordering, with the half-open interval between them used for overlap testing. Intake is gated commercially and technically: the customer must be `ACTIVE` and free of `credit_hold` (otherwise `ERR_CUSTOMER_CREDIT_HOLD`), and the referenced recipe must be `APPROVED` (otherwise `ERR_RECIPE_NOT_APPROVED`, HTTP 409). A malformed window or non-positive size fails with `ERR_INVALID_REQUEST`.

Creation does three computations. The `theoretical_output_kg` is the ordered litres multiplied by the recipe's `target_density_kg_per_l`, multiplied by the recipe's `theoretical_yield_pct` divided by one hundred, rounded half-up to three decimal places, and frozen for the life of the batch. The `highest_component_ghs_snapshot` copies the recipe's `highest_component_ghs` and is never refreshed, so later recipe edits cannot rewrite history. The `quoted_price_cents` is the provisional price, computed under the pricing variant pinned by the agreement. The batch is born in `INTAKE` with `version` 1, and with `actual_output_kg`, `density_corrected_output_l`, `yield_variance_pct`, and `invoiced_price_cents` all null.

Pricing has two variants around one rate card. Under `TOLLING_FEE`, the price is the agreement's `tolling_base_fee_cents` plus its `tolling_per_kg_cents` multiplied by the batch's `theoretical_output_kg`; because the fee never looks at actual output, the provisional quote and the final invoice are computed identically. Under `FORMULATED_PRICE`, the provisional quote multiplies `formulated_price_per_kg_cents` by the theoretical output as the best pre-run estimate, while the final invoice multiplies it by `actual_output_kg`; when the actual output exceeds the theoretical, the excess kilograms generate an over-yield credit — the excess mass multiplied by the per-kilogram formulated rate, multiplied by the agreement's `over_yield_split_pct` divided by one hundred — which is subtracted from the invoice, the blender retaining the unsplit remainder. Every computed price is rounded half-up to a whole cent.

Release moves the batch from `INTAKE` to `RELEASED` and is the most heavily guarded transition in the system; a `BatchScheduler` performs it with `expected_batch_job_version` in the body (§2.8). The checks fire in the order of §2.9: the batch must be in `INTAKE` (else `ERR_INVALID_STATE`); the customer `ACTIVE` and not on credit hold (else `ERR_CUSTOMER_CREDIT_HOLD`); the tank `CLEAN_VALIDATED` (else `ERR_TANK_NOT_CLEAN_VALIDATED`, HTTP 409); segregation satisfied — the batch's `highest_component_ghs_snapshot` must be admitted by the tank's `current_zone`, and if the tank's `last_product_ghs` is non-null with cleaning short of `CLEAN_VALIDATED`, the pairing of old and new classes must not be a forbidden pair (else `ERR_INCOMPATIBLE_SEGREGATION`); the pinned agreement `ACTIVE` with the logical clock inside its half-open window (else `ERR_AGREEMENT_NOT_ACTIVE`, HTTP 409); no other non-terminal batch on the same tank with an overlapping scheduled window (else `ERR_TANK_SCHEDULE_OVERLAP`, HTTP 409); the ordered litres no greater than the tank's `working_capacity_l` (else `ERR_BATCH_SIZE_EXCEEDS_CAPACITY`, HTTP 422); and finally the stale-version guard (else `ERR_STALE_VERSION`). This list is exhaustive: the source-state check is the batch's alone, release performs no check on the tank's `operational_state`, and the cleanliness, segregation, schedule-overlap, and capacity rules are the only tank-side guards. A successful release cascades the tank from `AVAILABLE` to `RESERVED` — a state the release writes onto the tank, not a precondition the tank must satisfy — writes the batch's `id` into the tank's `occupied_by_batch_id`, and increments both the tank's and the batch's `version`.

With the batch `RELEASED`, a `TankOperator` commits the raw-material draws. Each charge carries a `raw_material_lot_id`, a `charge_order` matching one of the recipe components' `charge_order` values, and a `charged_qty_kg` greater than zero; the promised mass may not exceed the lot's `quantity_kg_available` (else `ERR_INSUFFICIENT_LOT_QUANTITY`). Each committed charge is created in `COMMITTED` status, raises the lot's `quantity_kg_committed` by the promised mass with a lot `version` increment, and increments the batch's own `version` — which is precisely what a stale `expected_batch_job_version` at release protects against.

Starting charging moves the batch from `RELEASED` to `CHARGING` and requires the charge book to be complete: exactly one charge per recipe component, each drawn from a lot whose `material_code` matches that component's and owned by the batch's customer (otherwise `ERR_INCOMPLETE_CHARGES`, HTTP 409). The cascade is threefold: the tank moves from `RESERVED` to `IN_USE`; every `COMMITTED` charge flips to `CONSUMED`; and for each drawn lot the promised mass leaves both `quantity_kg_on_hand` and `quantity_kg_committed`, with a lot `version` increment per lot. Starting mixing then moves the batch from `CHARGING` to `MIXING`, permitted only once every charge row reads `CONSUMED`, and holding for QA moves it from `MIXING` to `HOLD_QA`. Each of these steps increments the batch's `version`.

Completion is a `QAValidator` decision that moves the batch from `HOLD_QA` to `COMPLETED`, with the measured `actual_output_kg` (zero or more) supplied in the body. Five gates stand in front of it, checked in the order of §2.9. An SDS for the batch must exist in `ISSUED` status (else `ERR_SDS_NOT_ISSUED`, HTTP 409). If the package configuration is not UN-rated while the classification is anything other than `NON_HAZ`, the completion fails with `ERR_UN_RATED_PACKAGE_REQUIRED` (HTTP 422). The package configuration must exist and its `total_volume_l` must reach at least the batch's drained volume — the `density_corrected_output_l` computed below — rounded up to the next whole litre (else `ERR_PACKAGE_VOLUME_INSUFFICIENT`, HTTP 422). When `placard_required` is true, the configuration's `placard_class` must be set and the shipment's `vehicle_placards` must contain it (else `ERR_PLACARD_MISSING`, HTTP 422). And every component lot must have at least one `POSTED` heel disposal record (else `ERR_HEEL_NOT_DISPOSITIONED`, HTTP 409).

A successful completion writes `actual_output_kg`, then derives the remaining measures: `density_corrected_output_l` is the drained mass divided by the recipe's `target_density_kg_per_l`, rounded half-up to three decimal places; `yield_variance_pct` is the difference between actual and theoretical output, divided by the theoretical output, expressed as a percentage; and `invoiced_price_cents` is the final price under the pinned variant, over-yield credit included where due. Completion increments the batch's `version`. The tank then cascades from `IN_USE` back to `AVAILABLE`: `occupied_by_batch_id` clears to null, `last_product_ghs` takes the batch's `highest_component_ghs_snapshot`, and `cleaning_state` returns to `DIRTY` — the vessel cannot be reserved again until it has been cleaned and validated anew.

Two exits short-circuit the happy path. Rejection by a `QAValidator` moves the batch from `HOLD_QA` to `REJECTED_QA`: the tank cascades back to `AVAILABLE` with `last_product_ghs` set and `cleaning_state` returned to `DIRTY`, and every charge still `COMMITTED` flips to `RELEASED`, returning its promised mass to the lot's available balance with a lot `version` increment; charges already `CONSUMED` are not auto-released, because that material is physically in the tank. Cancellation by a `BatchScheduler` is permitted only from `INTAKE` or `RELEASED`; from `RELEASED` the tank cascades from `RESERVED` back to `AVAILABLE` with `occupied_by_batch_id` cleared but `cleaning_state` and `last_product_ghs` untouched, since no material was ever drawn, and any `COMMITTED` charges flip to `RELEASED` with lot quantities reconciled. Both exits increment the batch's `version`. `COMPLETED`, `CANCELLED`, and `REJECTED_QA` are terminal.

### 3.7. Safety Data Sheet Authoring and Issuance

Each batch carries exactly one living SDS. An `SDSAuthor` authors it by declaring the final `ghs_classification`, a `signal_word` of `DANGER`, `WARNING`, or `NONE`, and the `hazard_statements` list of H-codes such as `H225` or `H314`, which may be empty only when the classification is `NON_HAZ`. Authoring computes an `authoring_consistency_flag` that is true only when all three of the following hold: the declared `ghs_classification` equals the batch's frozen `highest_component_ghs_snapshot`; the `signal_word` is `DANGER` whenever the classification is `FLAMMABLE`, `OXIDIZER`, or `TOXIN`, and is `WARNING` or `NONE` otherwise; and the `hazard_statements` list is non-empty, unless the classification is `NON_HAZ`. Issuance moves the document from `DRAFT` to `ISSUED` and is permitted only while that flag is true — an inconsistent document is rejected with `ERR_SDS_INCONSISTENT` (HTTP 422).

Re-authoring is revisioned rather than destructive. When an author posts a fresh SDS for a batch whose existing document is `ISSUED`, the old document cascades to `SUPERSEDED` with a `version` increment and the new one is created in `DRAFT` with `authoring_revision` one higher than its predecessor; when no issued document exists, the new draft simply starts at `authoring_revision` 1. The revision counter increases monotonically per batch. Listing a batch's SDS history therefore returns at most one living `DRAFT` or `ISSUED` document alongside any `SUPERSEDED` predecessors. An `ISSUED` document is a hard precondition of batch completion (§3.6).

### 3.8. Packaging, Placarding, and Shipment Dispatch

A `ShippingClerk` records the batch's single package configuration by choosing a `package_type`, declaring whether the packaging is UN-rated via `un_rated`, and giving a `package_count` greater than zero. Four package types exist with fixed capacities: `DRUM_205L` holds 205 litres, `IBC_1000L` holds 1,000 litres, `TOTE_500L` holds 500 litres, and `PAIL_20L` holds 20 litres. The configuration's `total_volume_l` is the package count multiplied by the type's capacity. UN-rated packaging is mandatory whenever the batch's classification is anything other than `NON_HAZ`; the requirement is enforced both when the configuration is created and again at batch completion, and a violation is rejected with `ERR_UN_RATED_PACKAGE_REQUIRED`.

Placarding is derived, not declared. Consulting the latest non-`SUPERSEDED` SDS classification, `placard_required` is true when the classification is anything other than `NON_HAZ` and the `total_volume_l` reaches or exceeds the 454-litre DOT bulk-packaging threshold — a configuration of exactly 454 litres therefore does require placarding. When required, `placard_class` is assigned from the classification: `FLAMMABLE` maps to `CLASS_3_FLAMMABLE`, `OXIDIZER` to `CLASS_5_1_OXIDIZER`, `TOXIN` to `CLASS_6_1_TOXIC`, and both `ACID` and `BASE` to `CLASS_8_CORROSIVE`. When placarding is not required, `placard_class` is null.

The same clerk plans the batch's single shipment by naming the `carrier_name`, listing the `vehicle_placards` actually mounted on the vehicle, and fixing the `departure_at` instant; the shipment is born in `PLANNED` with `shipped_volume_l` null until dispatch. Loading may start — moving the shipment from `PLANNED` to `LOADING` — only once the batch itself stands at `COMPLETED`, and any attempt earlier is rejected with `ERR_INVALID_STATE`. Dispatch moves the shipment from `LOADING` to `DISPATCHED` behind two final checks: when `placard_required` is true the configuration's `placard_class` must appear among the `vehicle_placards` (else `ERR_PLACARD_MISSING`), and when placarding is required at or above the 454-litre threshold the `carrier_name` must be non-empty (else `ERR_INVALID_REQUEST`). Dispatch snapshots `shipped_volume_l` from the configuration's `total_volume_l` and increments `version`. A shipment may be cancelled from either `PLANNED` or `LOADING`, moving it to `CANCELLED`; `DISPATCHED` and `CANCELLED` are terminal.

### 3.9. Heel Disposition and Waste Manifest Compliance

After draining, every lot charged into a batch leaves a residual heel that must be dispositioned. A `TankOperator` records the disposition for one charged lot at a time, supplying the `raw_material_lot_id` — which must be a lot actually charged into this batch — together with `heel_returned_kg` and `heel_disposed_kg`, each zero or more, with at least one of the two strictly positive. When any mass is sent to waste, a `disposal_method` of `INCINERATION`, `FUEL_BLENDING`, or `HAZARDOUS_LANDFILL` and a `waste_manifest_number` become mandatory; both are optional only for a pure return. The `disposed_at` timestamp completes the record, which is created in `PENDING` status. Records that violate the mass bounds fail with `ERR_INVALID_REQUEST`.

Posting is the regulated step. Per the ordering of §2.9, the segregation check fires before the manifest check: when `heel_returned_kg` is positive, the lot's `storage_zone` must be one that admits the lot's `ghS_class` under the zone map (else `ERR_INCOMPATIBLE_SEGREGATION`); when `heel_disposed_kg` is positive, `disposal_method` must be present and `waste_manifest_number` non-empty (else `ERR_WASTE_MANIFEST_REQUIRED`, HTTP 422). Posting moves the record from `PENDING` to `POSTED` and settles the inventory: returned mass stays in consignment, leaving the lot's `quantity_kg_on_hand` unchanged, while disposed mass leaves the lot's `quantity_kg_on_hand` with a lot `version` increment, and the record's own `version` increments. Batch completion then refuses to proceed until every component lot carries at least one `POSTED` record, surfacing `ERR_HEEL_NOT_DISPOSITIONED` otherwise.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Read endpoints return `200 OK`. Request and response payloads are not repeated here — the workflow narratives of §3 define each operation's inputs, computed fields, and side effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | QualityManager |
| POST | `/toll-operations/customers` | Create a customer | QualityManager |
| GET | `/toll-operations/customers` | List customers | Any |
| GET | `/toll-operations/customers/{id}` | Fetch one customer | Any |
| POST | `/toll-operations/customers/{id}/suspend` | Suspend a customer | QualityManager |
| POST | `/toll-operations/customers/{id}/reinstate` | Reinstate a suspended customer | QualityManager |
| POST | `/toll-operations/customers/{id}/terminate` | Terminate a suspended customer with no open batch jobs | QualityManager |
| POST | `/toll-operations/customers/{id}/pricing-agreements` | Create a pricing agreement in DRAFT | QualityManager |
| GET | `/toll-operations/customers/{id}/pricing-agreements` | List a customer's pricing agreements | Any |
| GET | `/toll-operations/customers/{id}/pricing-agreements/{agreementId}` | Fetch one pricing agreement | Any |
| POST | `/toll-operations/customers/{id}/pricing-agreements/{agreementId}/activate` | Activate a DRAFT agreement (OCC-guarded); fully covered overlapping agreements cascade to SUPERSEDED | QualityManager |
| POST | `/toll-operations/customers/{id}/pricing-agreements/{agreementId}/terminate` | Terminate an ACTIVE pricing agreement | QualityManager |
| POST | `/toll-operations/customers/{id}/raw-material-lots` | Receive a customer-owned consignment lot | BatchScheduler |
| GET | `/toll-operations/customers/{id}/raw-material-lots` | List a customer's lots | Any |
| GET | `/toll-operations/customers/{id}/raw-material-lots/{lotId}` | Fetch one lot | Any |
| POST | `/toll-operations/recipes` | Create a recipe in DRAFT | QualityManager |
| GET | `/toll-operations/recipes` | List recipes; filter by customer_id | Any |
| GET | `/toll-operations/recipes/{recipeId}` | Fetch one recipe | Any |
| POST | `/toll-operations/recipes/{recipeId}/approve` | Approve a DRAFT recipe | QualityManager |
| POST | `/toll-operations/recipes/{recipeId}/retire` | Retire an APPROVED recipe with no in-flight batches | QualityManager |
| POST | `/toll-operations/tanks` | Register a tank | QualityManager |
| GET | `/toll-operations/tanks` | List tanks; filter by occupied_by_batch_id | Any |
| GET | `/toll-operations/tanks/{id}` | Fetch one tank | Any |
| POST | `/toll-operations/tanks/{id}/cleaning-records` | Open a cleaning record on a DIRTY, AVAILABLE tank | TankOperator |
| GET | `/toll-operations/tanks/{id}/cleaning-records` | List a tank's cleaning records | Any |
| GET | `/toll-operations/tanks/{id}/cleaning-records/{recordId}` | Fetch one cleaning record | Any |
| POST | `/toll-operations/tanks/{id}/cleaning-records/{recordId}/submit` | Submit a cleaning record for QA review | TankOperator |
| POST | `/toll-operations/tanks/{id}/cleaning-records/{recordId}/validate` | QA-validates a cleaning record (PASS or FAIL) | QAValidator |
| POST | `/toll-operations/customers/{id}/batch-jobs` | Create a batch job in INTAKE; pins the pricing agreement, snapshots recipe hazard class, computes theoretical output and the provisional quote | BatchScheduler |
| GET | `/toll-operations/customers/{id}/batch-jobs` | List a customer's batch jobs; filter by status | Any |
| GET | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}` | Fetch one batch job | Any |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/release` | Release an INTAKE batch job (OCC-guarded); reserves the tank | BatchScheduler |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/start-charging` | Move RELEASED to CHARGING; consumes all committed charges and decrements lot quantities | TankOperator |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/start-mixing` | Move CHARGING to MIXING | TankOperator |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/hold-for-qa` | Move MIXING to HOLD_QA | TankOperator |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/complete` | Move HOLD_QA to COMPLETED; computes drained-mass derivations and the final invoice | QAValidator |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/reject-qa` | Move HOLD_QA to REJECTED_QA; releases the tank and reconciles committed charges | QAValidator |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/cancel` | Cancel an INTAKE or RELEASED batch job | BatchScheduler |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/batch-charges` | Commit a raw-material draw against a batch job | TankOperator |
| GET | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/batch-charges` | List a batch's charges | Any |
| GET | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/batch-charges/{chargeId}` | Fetch one charge | Any |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/sds` | Author (or re-author) the batch's SDS; an existing ISSUED document is SUPERSEDED | SDSAuthor |
| GET | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/sds` | List the batch's SDS documents (living document plus SUPERSEDED history) | Any |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/sds/{sdsId}/issue` | Issue a DRAFT SDS whose consistency flag holds | SDSAuthor |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/package-config` | Create the batch's 1:1 package configuration; computes volume and placarding | ShippingClerk |
| GET | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/package-config` | Fetch the batch's package configuration | Any |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/shipment` | Create the batch's 1:1 shipment | ShippingClerk |
| GET | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/shipment` | Fetch the batch's shipment | Any |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/shipment/start-loading` | Move shipment PLANNED to LOADING | ShippingClerk |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/shipment/dispatch` | Move LOADING to DISPATCHED; placard check enforced | ShippingClerk |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/shipment/cancel` | Cancel a PLANNED or LOADING shipment | ShippingClerk |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/heel-disposals` | Record heel disposition for one charged lot | TankOperator |
| GET | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/heel-disposals` | List heel disposal records for a batch | Any |
| POST | `/toll-operations/customers/{id}/batch-jobs/{batchJobId}/heel-disposals/{recordId}/post` | Post a heel disposal; validates manifest and segregation, applies lot adjustments | TankOperator |
| GET | `/toll-operations/batch-jobs/{batchJobId}` | Fetch a batch job by bare id | Any |
| GET | `/toll-operations/batch-jobs` | List batch jobs; filter by customer_id, recipe_id, pricing_agreement_id, tank_id, status | Any |
| GET | `/toll-operations/batch-charges/{chargeId}` | Fetch a batch charge by bare id | Any |
| GET | `/toll-operations/batch-charges` | List batch charges; filter by batch_job_id and raw_material_lot_id | Any |
| GET | `/toll-operations/sds-documents/{sdsId}` | Fetch an SDS document by bare id | Any |
| GET | `/toll-operations/sds-documents` | List SDS documents; filter by batch_job_id | Any |
| GET | `/toll-operations/package-configs/{packageConfigId}` | Fetch a package config by bare id | Any |
| GET | `/toll-operations/package-configs` | List package configs; filter by batch_job_id | Any |
| GET | `/toll-operations/shipments/{shipmentId}` | Fetch a shipment by bare id | Any |
| GET | `/toll-operations/shipments` | List shipments; filter by batch_job_id | Any |
| GET | `/toll-operations/heel-disposals/{recordId}` | Fetch a heel disposal record by bare id | Any |
| GET | `/toll-operations/heel-disposals` | List heel disposal records; filter by batch_job_id and raw_material_lot_id | Any |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives where the rule is enforced; this catalogue lists only identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CUSTOMER_CREDIT_HOLD` | 403 Forbidden |
| `ERR_TANK_NOT_CLEAN_VALIDATED` | 409 Conflict |
| `ERR_INCOMPATIBLE_SEGREGATION` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TANK_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_BATCH_SIZE_EXCEEDS_CAPACITY` | 422 Unprocessable Entity |
| `ERR_INCOMPLETE_CHARGES` | 409 Conflict |
| `ERR_INSUFFICIENT_LOT_QUANTITY` | 422 Unprocessable Entity |
| `ERR_RECIPE_NOT_APPROVED` | 409 Conflict |
| `ERR_RECIPE_FRACTION_SUM_INVALID` | 422 Unprocessable Entity |
| `ERR_RECIPE_CHARGE_ORDER_INVALID` | 422 Unprocessable Entity |
| `ERR_RECIPE_IN_USE` | 409 Conflict |
| `ERR_OPEN_BATCH_JOBS` | 409 Conflict |
| `ERR_SDS_NOT_ISSUED` | 409 Conflict |
| `ERR_SDS_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_UN_RATED_PACKAGE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PACKAGE_VOLUME_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_PLACARD_MISSING` | 422 Unprocessable Entity |
| `ERR_WASTE_MANIFEST_REQUIRED` | 422 Unprocessable Entity |
| `ERR_HEEL_NOT_DISPOSITIONED` | 409 Conflict |
