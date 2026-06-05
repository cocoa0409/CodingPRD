# Cannabis Seed-To-Sale API — Product Requirements Document

## 1. Introduction

This document specifies the Cannabis Seed-to-Sale Compliance API, a regulated-traceability platform modeled on state METRC-style track-and-trace mandates. The system follows a unit of regulated cannabis from the moment a cultivator tags a plant lot, through growth, harvest, drying, packaging, mandatory laboratory testing, custody transfer between licensed operators, and finally retail dispensing to a verified customer. Every gram is accounted for at all times: product that fails testing, is physically lost, or is intentionally destroyed must be reconciled through an auditable destruction record rather than silently disappearing from inventory.

Because the domain is a compliance system rather than a convenience system, the API is uncompromising about *who* may act, *when* a transition is legal, and *whether* the numbers still add up. Operators hold state licenses of distinct types, and the type of a license gates which operations its holder may perform. Several controls implement a strict separation of duties — the person who certifies a product as passing cannot be the person who releases it for sale, and the auditor who flags a discrepancy cannot be the person who clears it. The platform also enforces per-customer purchase caps, age verification, and laboratory holds, so that no product reaches a consumer without having cleared every regulatory gate.

The remainder of this document defines the global request/response contract and system-wide principles (§2), the detailed business workflows and their state machines (§3), the endpoint catalogue (§4), and the canonical error codes (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that govern every endpoint. All resource paths described here and in §4 are mounted under the `/compliance` prefix.

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header on a protected endpoint is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly seven roles, spelled precisely as follows: `StateRegulator`, `Cultivator`, `QALabUser`, `ComplianceManager`, `DistributionAgent`, `Budtender`, and `InventoryAuditor`.

- A `StateRegulator` is the issuing authority. It registers licenses and drives the license lifecycle — suspension, reinstatement, and revocation.
- A `Cultivator` operates a cultivation license: creating plant batches, advancing growth stages, recording harvests, curing and finishing them, packaging product, and recording plant-side destruction.
- A `QALabUser` operates a testing license and records potency and pesticide laboratory results. It may not release the packages it has tested.
- A `ComplianceManager` releases passed packages, clears reconciliation holds, voids draft manifests, and may also create packages and record waste events. Its release and hold-clearing powers are bound by separation of duties (see §2.6).
- A `DistributionAgent` operates a distribution license and builds, departs, recalls, and receives transfer manifests.
- A `Budtender` operates a retail license, opening sales, adding dispensing lines, finalizing or voiding sales, and registering customers.
- An `InventoryAuditor` performs physical inventory counts and records reconciliation results.

Each of these seven roles carries an **opaque** identity: when `X-User-Role` names any of them, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity's `id`. The server does not compare `X-User-ID` to any resource's foreign key. It may, however, record the value where a workflow explicitly captures it — for example, the `QALabUser` who recorded a passing result and the `InventoryAuditor` who performed a count are remembered (the latter stored as `counted_by_user_id` on the reconciliation record) so that the separation-of-duties checks in §2.6 can compare the acting `X-User-ID` against the previously recorded one.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every top-level resource carries a server-minted `id` formatted as a UUID with no type prefix — the identifier is opaque and conveys nothing but identity. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at the moment of creation.

The principal resources — License, PlantBatch, Harvest, Package, Manifest, Customer, and Sale — additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation of the resource, including mutations that arise as cascades from operations on related resources. The `version` field begins at 1 when the resource is created and increments by exactly 1 on every mutation, again including cascades. Whenever a state transition or a derived-field recomputation changes a resource, both `updated_at` and `version` advance together.

By contrast, the append-only and child records — LabResult, ManifestLine, SaleLine, ReconciliationCount, and WasteEvent — carry only `id` and `created_at`. These records have neither an `updated_at` field nor a `version` field, because they are written once and never modified. Wherever this document refers to one of these records being "recorded," it is created exactly once and is thereafter immutable.

### 2.5. Hierarchical Consistency and Cascading Side Effects

The provenance graph runs License → PlantBatch → Harvest → Package → SaleLine, with Manifest and ManifestLine, LabResult, ReconciliationCount, and WasteEvent referencing packages across aggregate boundaries. Because of this density of cross-references, a single operation frequently mutates more than one resource, and each affected resource independently advances its own `updated_at` and `version`.

Each stateful resource exposes its lifecycle position through a `status` field whose permitted values are enumerated per entity in the workflows of §3. When a parent operation cascades into children, the cascade is part of the same logical transaction. Departing a manifest, for example, does not merely change the manifest — it drives every package on the manifest's lines into transit as well, and each such package's `version` advances. Receiving a manifest re-homes or returns each line's package, finalizing a sale decrements the remaining quantity of each dispensed package and may push a package into a depleted terminal state, and destroying the last live package of a cured harvest may close that harvest automatically. Each of these secondary mutations is real and observable; none is optional. The specific cascade chains are described in the relevant workflow narratives in §3, and an implementation must apply every hop, not merely the primary one.

### 2.6. Segregation of Duties

Two release-style operations enforce a strict separation between the operator who created a control artifact and the operator who acts on its strength. A package that has earned a passing laboratory result may be released into active inventory only by an operator whose `X-User-ID` differs from the `QALabUser` who recorded that passing result; if the same user attempts both, the release is rejected with `ERR_SEGREGATION_OF_DUTIES`. Symmetrically, a package placed on hold by a discrepant physical count may be cleared only by an operator whose `X-User-ID` differs from the `InventoryAuditor` whose count placed the hold; a self-clear is likewise rejected with `ERR_SEGREGATION_OF_DUTIES`. Both checks compare the acting user identifier against the identifier recorded at the time the artifact was created.

### 2.7. License-Type Gating and License Status

Many operations are valid only under a license of the appropriate type and only while that license is in good standing. The operating or owning license must be in `ACTIVE` status for the following operations: advancing a plant batch's growth stage, recording a harvest, creating a package, finalizing a sale, and departing a manifest. If the governing license is `SUSPENDED` or `REVOKED` when one of these operations is attempted, it is rejected with `ERR_LICENSE_NOT_ACTIVE`.

Separately, the *type* of the operating license must match the operation. Only a `CULTIVATION`-type license may host plant-batch and harvesting operations, only a `RETAIL`-type license may open and finalize sales, only a `TESTING`-type license may record laboratory results, and only an appropriate shipping license may originate a manifest. A mismatch between `license_type` and the attempted operation is rejected with `ERR_LICENSE_TYPE_MISMATCH`. This type check applies to plant-batch creation, sale creation, lab-result recording, and manifest creation.

### 2.8. Nested Resource Retrieval and Existence Ordering

Several read endpoints address a child collection through a parent path — for instance, listing the lab results, reconciliation counts, waste events, sale lines, or manifest lines that reference a particular package. When a path contains a resource identifier, the system validates the existence of each path identifier left-to-right and, more generally, validates every referenced resource — path identifiers first, then foreign keys carried in the request body — before applying any business rule. A reference to a resource that does not exist is rejected with `ERR_NOT_FOUND`. This existence sweep precedes state and business validation, so that an operation against a non-existent parent is reported as missing rather than as being in the wrong state.

### 2.9. Precision and Rounding

All weight and flower-equivalent calculations are carried out in decimal arithmetic and the stored results are rounded to exactly 2 decimal places using the round-half-up convention. This applies to per-line flower-equivalent grams, aggregated sale flower-equivalent grams, reconciliation variance, and harvest packaged and remaining weights. Where a calculation prescribes a particular order of rounding relative to summation, that order is binding and is stated with the calculation in §3; a different rounding order that happens to differ by a cent is not acceptable.

### 2.10. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a parent whose composition has changed underneath it.

Departing a manifest requires the request to carry `expected_manifest_version`, which must equal the manifest's current `version`. Every time a manifest line is attached, the manifest's `version` advances; if another writer has attached or removed a line since the client last read the manifest, the client's notion of which packages will ship is stale. In that case the depart is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than shipping a stale line set.

Finalizing a sale requires the request to carry `expected_sale_version`, which must equal the sale's current `version`. Adding a sale line advances the sale's `version`; if another writer has added a line since the client last read the sale, the flower-equivalent total that the daily-limit check evaluates would be computed against a stale line set. The finalize is therefore rejected with `ERR_STALE_VERSION` (HTTP 412) on the version mismatch, so the limit is never checked against a stale composition. Endpoints other than manifest depart and sale finalize do not take an expected-version field.

### 2.11. Validation Priority

When several checks could fail on a single request, they are evaluated in a fixed order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization (`ERR_UNAUTHORIZED`), then existence of every referenced resource (`ERR_NOT_FOUND`). State checks come next: the target resource must be in a legal state for the requested transition (`ERR_INVALID_STATE`), and for child-creation the parent must be in the correct state (`ERR_INVALID_PARENT_STATE`); the full-destroy terminalization rule (`ERR_PARTIAL_DESTROY_NOT_TERMINAL`) is also evaluated at this state tier.

After state come the business-safety checks, in this order: license-active (`ERR_LICENSE_NOT_ACTIVE`), license-type (`ERR_LICENSE_TYPE_MISMATCH`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), lab hold (`ERR_LAB_HOLD_ACTIVE`), and — on sale finalize — age verification (`ERR_AGE_VERIFICATION_FAILED`), which is evaluated at the safety tier before the fiscal daily-limit check. Then come the referential and constraint checks: source-discriminator agreement for waste (`ERR_SOURCE_DISCRIMINATOR_MISMATCH`), tag uniqueness (`ERR_DUPLICATE_TAG`), quantity sufficiency (`ERR_INSUFFICIENT_QUANTITY`), weight-range bounds (`ERR_WEIGHT_RANGE`), manifest-overlap (`ERR_MANIFEST_OVERLAP`), and sale-window-overlap (`ERR_SALE_WINDOW_OVERLAP`). The fiscal daily-limit check (`ERR_DAILY_LIMIT_EXCEEDED`) follows, then optimistic-concurrency staleness (`ERR_STALE_VERSION`), and finally generic request-shape validation (`ERR_INVALID_REQUEST`) for missing fields, invalid enums, or out-of-range numbers. The guiding intent is that a higher-tier violation surfaces its own error rather than being masked by a lower-tier check.

## 3. Business Logic & Workflows

### 3.1. Licensing and the Regulatory Clock

Everything in the system hangs off a **License**, the regulated operating permit issued by a `StateRegulator`. Registering a license requires a `license_number` (the state-issued number, which must be unique across all licenses and non-empty), a `license_type`, a two-uppercase-letter `state_code`, and an `expires_on` expiry date. The `license_type` is one of `CULTIVATION`, `MANUFACTURING`, `RETAIL`, `TESTING`, or `DISTRIBUTION`. A retail license may also be registered with a `daily_purchase_limit_grams` value, the per-customer daily flower-equivalent cap in grams; if omitted it defaults to 28.5 grams, and it must be at least 0. This cap is consulted only when the license type is `RETAIL`. A newly registered license is born in `ACTIVE` status with `version` 1. If the supplied `license_number` collides with an existing license, the registration is rejected with `ERR_DUPLICATE_TAG`.

A license moves through a small status machine driven entirely by the regulator. From `ACTIVE` it may be suspended to `SUSPENDED`, and a `SUSPENDED` license may be reinstated back to `ACTIVE` provided its `expires_on` still lies strictly in the future relative to the server clock; a reinstate attempted when `expires_on` is at or before the current clock is rejected with `ERR_INVALID_STATE`. Each of suspend, reinstate, and revoke requires the license to be in the appropriate originating status, and an attempt from any other status is likewise rejected with `ERR_INVALID_STATE`. From either `ACTIVE` or `SUSPENDED`, the regulator may revoke the license to the terminal `REVOKED` state. Each of these transitions increments the license's `version`. While a license is `SUSPENDED`, no child cultivation or inventory operation that requires an active license may proceed beneath it, as enforced by the license-active check in §2.7.

Because expiry windows and dated sale windows must be testable, an administrative test-driving capability lets a `StateRegulator` set the server's current UTC clock to a supplied instant. The request carries the target instant as `to_iso8601`, and the server adopts that moment as "now" for subsequent expiry and sale-date evaluations.

### 3.2. Cultivation: Plant Batches and Their Destruction

A `Cultivator` begins a grow by registering a **PlantBatch** under a cultivation license. Creation supplies the owning `license_id`, a unique METRC plant-lot `lot_tag` (unique across all plant batches and non-empty), a `strain` cultivar name, an initial `plant_count` of at least 1, and a `planted_at` date. The batch is created in `IMMATURE` status, and its `live_plant_count` is initialized to the supplied `plant_count`. The `live_plant_count` is a derived figure: it is the original `plant_count` minus the cumulative plants destroyed through waste events recorded against this batch. A duplicate `lot_tag` is rejected with `ERR_DUPLICATE_TAG`.

Growth advances one stage at a time. Advancing a batch moves it from `IMMATURE` to `VEGETATIVE`, and a second advance moves it from `VEGETATIVE` to `FLOWERING`. Each advance is permitted only when the batch is currently in the originating stage, the owning license is `ACTIVE`, and the batch still has at least one live plant (`live_plant_count` of 1 or more); each advance increments the batch's `version`. An advance attempted from a state that is not the legal predecessor is rejected with `ERR_INVALID_STATE`.

A batch may be wholly destroyed from any of its growing stages — `IMMATURE`, `VEGETATIVE`, or `FLOWERING` — by recording a plant-side waste event (see §3.8). Destruction terminalizes the batch to `DESTROYED` only when the waste event destroys every remaining live plant; that is, when the destroyed plant count equals the batch's current `live_plant_count`. A full-batch destruction drives `live_plant_count` to 0, sets the batch's status to `DESTROYED`, and increments its `version`. A partial destruction (fewer plants than are live) only decrements `live_plant_count` and leaves the batch in its current growing stage; it does not terminalize.

### 3.3. Harvest, Drying, and Curing

When a `FLOWERING` batch is ready, the `Cultivator` records a **Harvest** cut from it. Creating a harvest supplies the source `plant_batch_id`, an operator-assigned `harvest_name`, and the `wet_weight_grams` recorded at cut, which must be greater than 0. The harvest's owning `license_id` is copied from the source batch at harvest time rather than supplied by the client. Recording the harvest is permitted only when the source batch is in `FLOWERING`, its owning license is `ACTIVE`, and the batch has at least one live plant; it both creates the harvest in `DRYING` status and, as a cascade, flips the source batch from `FLOWERING` to `HARVESTED` and increments the batch's `version`.

A drying harvest is cured by recording its `dry_weight_grams`, moving it from `DRYING` to `CURED`. The supplied `dry_weight_grams` must be greater than 0 and must not exceed the harvest's `wet_weight_grams`; a dry weight above the wet weight is rejected with `ERR_WEIGHT_RANGE`. Curing is permitted only from `DRYING` and only while the owning license is `ACTIVE`. On curing, the harvest stores the supplied dry weight, recomputes its `remaining_weight_grams`, and increments its `version`.

The remaining and packaged weights are derived figures recomputed by the yield reconciliation described in §3.4. Before curing, while the harvest is still `DRYING` and no dry weight has been set, `remaining_weight_grams` is undefined and packaging is blocked. Once cured (or finished), `remaining_weight_grams` is fully defined.

A cured harvest is closed by finishing it, moving it from `CURED` to the terminal `FINISHED` state. Finishing is permitted only when the harvest is `CURED`, its `remaining_weight_grams` has been packaged down to exactly 0, the owning license is `ACTIVE`, and the harvest has at least one package. Finishing increments the harvest's `version`. The harvest can also reach `FINISHED` automatically: when the harvest is `CURED` with `remaining_weight_grams` at exactly 0 and every one of its packages has reached a terminal status — either `DEPLETED` through sale or `DESTROYED` through a failed-test destruction — the system closes the harvest from `CURED` to `FINISHED` on its own and increments the harvest's `version`. This auto-finish is the third hop of the failed-test destruction cascade described in §3.5.

### 3.4. Packaging and Harvest Yield Reconciliation

Product leaves the harvest bin as **Packages**. A package is pulled from a harvest by a `Cultivator` or `ComplianceManager`, supplying the source `harvest_id`, a unique METRC `package_tag` (unique across all packages and non-empty), a `product_category` of `FLOWER`, `CONCENTRATE`, or `EDIBLE`, and a net `quantity_grams` greater than 0. Packaging is permitted only when the source harvest is in `CURED` status; attempting to package from a non-`CURED` harvest is rejected with `ERR_INVALID_PARENT_STATE`. The requested `quantity_grams` must not exceed the harvest's current `remaining_weight_grams`; an over-pull is rejected with `ERR_INSUFFICIENT_QUANTITY`. A duplicate `package_tag` is rejected with `ERR_DUPLICATE_TAG`. The package's custodying `license_id` is derived (initially the harvest's license) and changes only when a transfer is received. A new package is created in `TESTING` status with `lab_hold` true, its `remaining_grams` initialized to its `quantity_grams`, and its `thc_pct` null until a passing result exists.

Creating a package triggers the harvest yield reconciliation. The harvest's `packaged_weight_grams` is the sum, across every package ever pulled from that harvest, of each package's `quantity_grams` — taken at the original quantity, which never changes, and counted regardless of that package's later status. The harvest's `remaining_weight_grams` is then the harvest's `dry_weight_grams` minus that packaged total, with both figures rounded to 2 decimal places using round-half-up. Crucially, this reconciliation runs on package creation only. Later shrinkage of a package's `remaining_grams` through sale or destruction does **not** change the harvest's packaged or remaining totals, because those grams left the bin at the moment the package was cut; package destruction never re-runs this reconciliation. The package-creation insufficiency check guarantees `remaining_weight_grams` never falls below 0. Each package creation also increments the source harvest's `version` as a cascade.

### 3.5. Laboratory Testing and Package Release

Before product can move or sell, it must clear testing. A `QALabUser`, operating a `TESTING`-type license, records a **LabResult** against a package that is in `TESTING` status. The result supplies the `package_id` under test, the `testing_license_id` of the recording lab, the measured `thc_pct` (between 0 and 100 inclusive), a `pesticide_pass` boolean, and the `tested_at` timestamp. A lab result is an append-only record. The system computes its `overall_result`: the result is `PASS` only when `pesticide_pass` is true and the measured `thc_pct` is at or below the regulatory potency ceiling; otherwise the result is `FAIL`. The regulatory potency ceiling is 100, equal to the upper bound of the valid `thc_pct` range, so every in-range potency is at or below the ceiling and the `PASS`/`FAIL` decision reduces to the value of `pesticide_pass`. The recording license must be `ACTIVE` and must not be the package's custodying license; a recording license whose id equals the package's custodying `license_id` is rejected with `ERR_LICENSE_TYPE_MISMATCH`.

The recorded result drives a divergent branch on the package. On a `PASS`, the package transitions from `TESTING` to `PASSED`, its `lab_hold` is cleared to false, its `thc_pct` is set from the lab result's measured value, and its `version` increments. On a `FAIL`, the package transitions from `TESTING` to `FAILED`, its `lab_hold` remains true, nothing is cleared, and its `version` increments. The two branches are symmetric only in that both advance the version; the `PASS` branch clears the hold and stamps potency, while the `FAIL` branch clears nothing.

A `PASSED` package is released into salable inventory by a `ComplianceManager`, moving it from `PASSED` to `ACTIVE` and incrementing its `version`. Release is permitted only when the package is `PASSED` with `lab_hold` false, and only when the releasing operator differs from the `QALabUser` who recorded the passing result, per the separation-of-duties rule in §2.6.

A `FAILED` package is removed from inventory by destroying it through a package-side waste event whose reason is failed testing (see §3.8). This is a three-hop cascade. First, the destruction sets the package's `remaining_grams` to 0; because the destruction is required to consume the full remaining grams, this drives the package to the terminal `DESTROYED` status as the second hop, and the package's `version` increments. As the third hop, if the source harvest is `CURED` with `remaining_weight_grams` at exactly 0 and every package of that harvest is now terminal (`DEPLETED` or `DESTROYED`), the harvest auto-finishes from `CURED` to `FINISHED` and its `version` increments. A partial destroy on a `FAILED` package through a `FAILED_TEST` waste event does not terminalize it and is rejected with `ERR_PARTIAL_DESTROY_NOT_TERMINAL`; this full-consumption requirement is evaluated only for the `FAILED`-package-plus-`FAILED_TEST` combination, and a package-side waste event in any other combination simply decrements `remaining_grams` (consuming any permitted partial amount) without terminalizing the package.

### 3.6. Transfer Manifests Between Licensees

Movement of product between licensed operators is governed by a **Manifest**, created by a `DistributionAgent` between an `origin_license_id` and a `destination_license_id`. A new manifest is born in `DRAFT` status with `version` 1. Its `line_count` (the number of attached lines) and `total_grams` (the sum of the grams across attached lines) are derived figures, both starting at 0, and its `departed_at` timestamp is null until departure.

Packages are added to a draft manifest one **ManifestLine** at a time, each line bound to its parent manifest by `manifest_id`. Attaching a line supplies the `package_id` being shipped and the `grams` of that package allocated to the line, where `grams` must be greater than 0 and must not exceed the package's `remaining_grams` at attach time; an over-allocation is rejected with `ERR_INSUFFICIENT_QUANTITY`. A line may be attached only while the manifest is in `DRAFT`; attaching to a non-draft manifest is rejected with `ERR_INVALID_PARENT_STATE`. A package may sit on at most one open manifest line at a time — that is, on at most one manifest in `DRAFT` or `IN_TRANSIT` — so attaching a package that is already on another open manifest line is rejected as a transfer-window overlap with `ERR_MANIFEST_OVERLAP`. Each line attachment recomputes the manifest's `line_count` and `total_grams` and increments the manifest's `version`.

Departing a manifest moves it from `DRAFT` to `IN_TRANSIT`. Departure is permitted only when the manifest is `DRAFT`, has at least one line, every line's package is in `ACTIVE` status with `lab_hold` false, the origin license is `ACTIVE`, and the supplied `expected_manifest_version` matches the manifest's current `version` (see §2.10). A package still on lab hold cannot be transferred as final and triggers `ERR_LAB_HOLD_ACTIVE`. On departure the manifest's status becomes `IN_TRANSIT`, its `departed_at` is set to the current clock, every line's package is cascaded from `ACTIVE` to `IN_TRANSIT` (each package's `version` advancing), and the manifest's `version` increments.

A manifest in transit may be recalled back to `DRAFT` by the distributor, which clears `departed_at` to null and cascades every line's package from `IN_TRANSIT` back to `ACTIVE`, incrementing the manifest's `version`; this `DRAFT → IN_TRANSIT → DRAFT` loop lets the distributor re-edit a shipment before it is received. Receiving an in-transit manifest carries a `decision` indicating acceptance or rejection, supplied as the exact string `"accept"` or `"reject"`; any other value is rejected with `ERR_INVALID_REQUEST`. On acceptance the manifest moves to the terminal `RECEIVED` state, the destination license must be `ACTIVE`, and each line's package has its `license_id` re-homed to the destination license and its status set back to `ACTIVE`. On rejection the manifest moves to the terminal `REJECTED` state and each line's package is returned to origin custody with its status set back to `ACTIVE`. Both receive branches cascade across every line's package and increment the manifest's `version`; they differ only in whether custody moves to the destination or stays at origin. Finally, a `ComplianceManager` may void a manifest that is still in `DRAFT`, moving it to the terminal `VOIDED` state and incrementing its `version`.

### 3.7. Retail Sales, Flower-Equivalent Math, and Daily Limits

Retail dispensing begins by registering a **Customer**, which a `Budtender` or `ComplianceManager` may do. Registration supplies a `birthdate` for age verification and optionally `is_medical` (defaulting to false) and a `medical_card_number` (defaulting to null). A medical patient enjoys a higher daily limit, as described below.

A `Budtender` operating a retail license opens a **Sale** for a customer by supplying the `retail_license_id`, the `customer_id`, and the `sale_date` to which the sale is attributed. A sale is born in `OPEN` status with its `flower_equiv_grams` at 0. A customer may have at most one open sale per retail license per `sale_date`; opening a second overlapping same-day sale window for that customer at that license is rejected with `ERR_SALE_WINDOW_OVERLAP`.

Product is dispensed onto a sale as **SaleLines**, each line bound to its parent sale by `sale_id`. Adding a line supplies the `package_id` dispensed from and the `grams` dispensed, where `grams` must be greater than 0 and must not exceed the package's `remaining_grams` at add time (an over-draw is rejected with `ERR_INSUFFICIENT_QUANTITY`). A line may be added only while the sale is `OPEN` (otherwise `ERR_INVALID_PARENT_STATE`), and the dispensed package must not be on lab hold — a package with `lab_hold` true cannot be sold and triggers `ERR_LAB_HOLD_ACTIVE`. Each line computes its own `flower_equiv_grams`: the dispensed `grams` multiplied by the flower-equivalent factor for the package's `product_category`, where `FLOWER` weighs 1.0, `CONCENTRATE` weighs 5.0, and `EDIBLE` weighs 0.1, with that product rounded to 2 decimal places using round-half-up. The sale's aggregate `flower_equiv_grams` is the sum of the already-rounded per-line values, that sum itself rounded to 2 decimal places — the rounding is applied per line first and only then summed, never the reverse. Adding a line increments the sale's `version`.

Finalizing a sale moves it from `OPEN` to the terminal `FINALIZED` state and is performed by a `Budtender`. Finalize requires the sale to be `OPEN`, to have at least one line, the retail license to be `ACTIVE`, and the supplied `expected_sale_version` to match the sale's current `version` (see §2.10). Two compliance gates apply at finalize. First, age verification: the customer must be at least 21 years old at the `sale_date`, computed from the customer's `birthdate`; a customer below that age is rejected with `ERR_AGE_VERIFICATION_FAILED`, and this safety check is evaluated before the fiscal daily-limit check. Second, the daily-limit check: the system gathers all of the customer's `FINALIZED` sales for the same `customer_id` and the same `sale_date`, sums their `flower_equiv_grams` to obtain the prior total (open and voided sales are excluded), and adds the current sale's `flower_equiv_grams` to it, rounding the projection to 2 decimal places. The customer's limit is the retail license's `daily_purchase_limit_grams`, multiplied by 3 for a medical customer (when `is_medical` is true) and by 1 for an adult-use customer. If the projected same-day total is strictly greater than that limit, finalize is rejected with `ERR_DAILY_LIMIT_EXCEEDED`; a projection exactly equal to the limit passes.

On a successful finalize, the sale moves to `FINALIZED`, each line's package has its `remaining_grams` decremented by that line's `grams` as a cascade, any package whose `remaining_grams` thereby reaches exactly 0 auto-transitions from `ACTIVE` to the terminal `DEPLETED` state (with its `version` advancing), and the sale's `version` increments. A `Budtender` may instead void an `OPEN` sale, moving it to the terminal `VOIDED` state and incrementing its `version`; because an open sale's lines never decremented any package's remaining grams, voiding releases no inventory.

### 3.8. Reconciliation Counts and Waste Destruction

Physical inventory is audited through **ReconciliationCounts** recorded by an `InventoryAuditor`. A count supplies the `package_id` being counted, the `counted_by_user_id` of the auditor performing the physical count, the physically observed `counted_grams` (at least 0), and the `counted_at` timestamp. The count is an append-only record. At count time the system snapshots the package's current `remaining_grams` as the `expected_grams`, computes the signed `variance_grams` as the counted grams minus the expected grams rounded to 2 decimal places, and derives the `outcome`. The outcome is `MATCH` when the absolute value of the variance is at or below the tolerance of 0.5 grams (the boundary of exactly 0.5 is a match), and `DISCREPANCY` when the absolute variance exceeds 0.5 grams. A `MATCH` leaves the package `ACTIVE` and places no hold. A `DISCREPANCY` drives the package from `ACTIVE` to `ON_HOLD` as a cross-entity cascade and increments the package's `version`.

A package placed on hold by a discrepant count is returned to circulation by a `ComplianceManager` clearing the hold, moving it from `ON_HOLD` back to `ACTIVE` and incrementing its `version`. Clearing is permitted only when the package is `ON_HOLD` and only when the clearing operator differs from the `InventoryAuditor` whose discrepant count placed the hold, per §2.6.

Both plant and product destruction are recorded through a single polymorphic **WasteEvent**, which a `Cultivator` or `ComplianceManager` may record. Every waste event carries a `source_type` discriminator of either `PLANT_BATCH` or `PACKAGE`, a `reason` code of `MOLD`, `PEST`, `FAILED_TEST`, `EXPIRED`, or `OTHER`, and a `destroyed_at` timestamp. The discriminator must agree with the supplied foreign keys: a `PLANT_BATCH` event must carry `plant_batch_id` with a null `package_id`, and a `PACKAGE` event must carry `package_id` with a null `plant_batch_id`; a mismatch is rejected with `ERR_SOURCE_DISCRIMINATOR_MISMATCH`. A plant-batch event supplies `destroyed_plant_count` (at least 0, defaulting to 0), which must not exceed the batch's `live_plant_count`; a package event supplies `destroyed_grams` (at least 0, defaulting to 0), which must not exceed the package's `remaining_grams`. A destroyed count or weight beyond the available amount is rejected with `ERR_WEIGHT_RANGE`.

For a plant-batch source, the event decrements the batch's `live_plant_count`, and a full destruction (destroyed plant count equal to the live count) terminalizes the batch to `DESTROYED` as described in §3.2. For a package source, the event decrements the package's `remaining_grams`, and a full `FAILED_TEST` destruction of a `FAILED` package drives the failed-test cascade described in §3.5. Package-side waste recomputes nothing on the source harvest's packaged or remaining weights, since those grams already left the bin at packaging.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new record to a collection return `201 Created`. Operations that modify an existing resource — including state transitions and the test-driving clock — return `200 OK`. All paths below are mounted under the `/compliance` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/compliance/licenses` | Register a state license | StateRegulator |
| GET | `/compliance/licenses` | List licenses (filter by license_type/status) | StateRegulator, ComplianceManager, DistributionAgent, Budtender, Cultivator, QALabUser, InventoryAuditor |
| GET | `/compliance/licenses/{id}` | Get one license | StateRegulator, ComplianceManager, DistributionAgent, Budtender, Cultivator, QALabUser, InventoryAuditor |
| POST | `/compliance/licenses/{id}/suspend` | Suspend a license | StateRegulator |
| POST | `/compliance/licenses/{id}/reinstate` | Reinstate a suspended license | StateRegulator |
| POST | `/compliance/licenses/{id}/revoke` | Revoke a license (terminal) | StateRegulator |
| POST | `/compliance/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | StateRegulator |
| POST | `/compliance/plant-batches` | Create an immature plant batch | Cultivator |
| GET | `/compliance/plant-batches` | List plant batches (filter by license_id/status) | Cultivator, ComplianceManager, StateRegulator, InventoryAuditor |
| GET | `/compliance/plant-batches/{id}` | Get one plant batch | Cultivator, ComplianceManager, StateRegulator, InventoryAuditor |
| POST | `/compliance/plant-batches/{id}/advance` | Advance batch growth stage | Cultivator |
| GET | `/compliance/plant-batches/{id}/waste-events` | List waste events for a plant batch | Cultivator, ComplianceManager, InventoryAuditor, StateRegulator |
| POST | `/compliance/harvests` | Harvest a FLOWERING batch | Cultivator |
| GET | `/compliance/harvests` | List harvests (filter by plant_batch_id/license_id/status) | Cultivator, ComplianceManager, StateRegulator, InventoryAuditor |
| GET | `/compliance/harvests/{id}` | Get one harvest | Cultivator, ComplianceManager, StateRegulator, InventoryAuditor |
| POST | `/compliance/harvests/{id}/cure` | Record dry weight; cure the harvest | Cultivator |
| POST | `/compliance/harvests/{id}/finish` | Close a fully-packaged harvest | Cultivator |
| POST | `/compliance/packages` | Pull a package from a cured harvest | Cultivator, ComplianceManager |
| GET | `/compliance/packages` | List packages (filter by harvest_id/license_id/status) | Cultivator, ComplianceManager, DistributionAgent, Budtender, QALabUser, InventoryAuditor, StateRegulator |
| GET | `/compliance/packages/{id}` | Get one package | Cultivator, ComplianceManager, DistributionAgent, Budtender, QALabUser, InventoryAuditor, StateRegulator |
| GET | `/compliance/packages/{id}/lab-results` | List lab results for a package | Cultivator, ComplianceManager, QALabUser, StateRegulator, InventoryAuditor |
| GET | `/compliance/packages/{id}/reconciliation-counts` | List reconciliation counts for a package | ComplianceManager, InventoryAuditor, StateRegulator |
| GET | `/compliance/packages/{id}/waste-events` | List package-source waste events for a package | ComplianceManager, Cultivator, InventoryAuditor, StateRegulator |
| GET | `/compliance/packages/{id}/manifest-lines` | List manifest lines referencing a package | DistributionAgent, ComplianceManager, StateRegulator |
| GET | `/compliance/packages/{id}/sale-lines` | List sale lines dispensed from a package | Budtender, ComplianceManager, StateRegulator |
| POST | `/compliance/packages/{id}/release` | Release a PASSED package to ACTIVE | ComplianceManager |
| POST | `/compliance/packages/{id}/clear-hold` | Clear a reconciliation hold | ComplianceManager |
| POST | `/compliance/lab-results` | Record a potency/pesticide test result | QALabUser |
| GET | `/compliance/lab-results` | List lab results (filter by package_id/testing_license_id) | QALabUser, ComplianceManager, StateRegulator |
| GET | `/compliance/lab-results/{id}` | Get one lab result | QALabUser, ComplianceManager, StateRegulator |
| POST | `/compliance/manifests` | Create a transfer manifest | DistributionAgent |
| GET | `/compliance/manifests` | List manifests (filter by origin/destination/status) | DistributionAgent, ComplianceManager, StateRegulator |
| GET | `/compliance/manifests/{id}` | Get one manifest | DistributionAgent, ComplianceManager, StateRegulator |
| POST | `/compliance/manifests/{id}/lines` | Attach a package to a DRAFT manifest | DistributionAgent |
| GET | `/compliance/manifests/{id}/lines` | List the lines on a manifest | DistributionAgent, ComplianceManager, StateRegulator |
| POST | `/compliance/manifests/{id}/depart` | Depart a manifest (OCC-guarded) | DistributionAgent |
| POST | `/compliance/manifests/{id}/recall` | Recall an in-transit manifest to DRAFT | DistributionAgent |
| POST | `/compliance/manifests/{id}/receive` | Receive an in-transit manifest (accept/reject) | DistributionAgent |
| POST | `/compliance/manifests/{id}/void` | Void a DRAFT manifest | ComplianceManager |
| POST | `/compliance/customers` | Register a retail customer/patient | Budtender, ComplianceManager |
| GET | `/compliance/customers/{id}` | Get one customer | Budtender, ComplianceManager, StateRegulator |
| POST | `/compliance/sales` | Open a retail sale | Budtender |
| GET | `/compliance/sales` | List sales (filter by license/customer/sale_date/status) | Budtender, ComplianceManager, StateRegulator |
| GET | `/compliance/sales/{id}` | Get one sale | Budtender, ComplianceManager, StateRegulator |
| POST | `/compliance/sales/{id}/lines` | Add a dispensing line to an OPEN sale | Budtender |
| GET | `/compliance/sales/{id}/lines` | List the lines on a sale | Budtender, ComplianceManager, StateRegulator |
| POST | `/compliance/sales/{id}/finalize` | Finalize an OPEN sale (OCC-guarded) | Budtender |
| POST | `/compliance/sales/{id}/void` | Void an OPEN sale | Budtender |
| POST | `/compliance/reconciliation-counts` | Record a physical inventory count | InventoryAuditor |
| GET | `/compliance/reconciliation-counts` | List reconciliation counts (filter by package_id/outcome) | InventoryAuditor, ComplianceManager, StateRegulator |
| POST | `/compliance/waste-events` | Record a destruction of plants or product | Cultivator, ComplianceManager |
| GET | `/compliance/waste-events` | List waste events (filter by source/plant_batch_id/package_id/reason) | Cultivator, ComplianceManager, InventoryAuditor, StateRegulator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LICENSE_NOT_ACTIVE` | 403 |
| `ERR_LICENSE_TYPE_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_LAB_HOLD_ACTIVE` | 409 |
| `ERR_SOURCE_DISCRIMINATOR_MISMATCH` | 422 |
| `ERR_DUPLICATE_TAG` | 409 |
| `ERR_INSUFFICIENT_QUANTITY` | 409 |
| `ERR_MANIFEST_OVERLAP` | 409 |
| `ERR_SALE_WINDOW_OVERLAP` | 409 |
| `ERR_DAILY_LIMIT_EXCEEDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PARENT_STATE` | 409 |
| `ERR_WEIGHT_RANGE` | 422 |
| `ERR_AGE_VERIFICATION_FAILED` | 422 |
| `ERR_PARTIAL_DESTROY_NOT_TERMINAL` | 409 |
