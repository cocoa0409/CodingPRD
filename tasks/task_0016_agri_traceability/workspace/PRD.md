# Agri-Traceability API — Product Requirements Document

## 1. Introduction

Modern food supply chains span dozens of independent actors — farms, agrochemical regulators, certified inspection laboratories, refrigerated logistics carriers, distributors, retailers — and a single contaminated batch can reach consumers in hours while taking weeks to recall. Regulators and consumers increasingly demand a verifiable record that begins at the field plot and ends at the QR code on the carton: every pesticide application, every withdrawal-period elapse, every cold-chain reading, every lab measurement, and every disposal entry tied back to the same identifier. The Agri-Traceability API exists to enforce that record as a hard contract rather than a best effort.

The API governs the full lifecycle of a planting batch — registration, agrochemical application, harvest, warehouse storage, inspection, logistics with IoT temperature monitoring, consumer-facing QR-code tracing, and recall execution — across six segregated roles whose authority is non-overlapping by design. The system is built around three load-bearing principles: (a) compliance is enforced at write time, never at read time; (b) violations cascade automatically across related entities so that no actor needs to chase consistency manually; and (c) every state transition and every recall action is permanently recorded in an immutable audit trail. Where regulatory rules conflict with operational convenience — a prohibited substance, an over-disposed recall, an inspector grading her own grower's batch — the API rejects rather than permits.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. If either header is missing or empty, the request is rejected with `ERR_AUTH_MISSING`. If `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_AUTH_INVALID_ROLE`. If the role is recognized but not permitted on the requested endpoint, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes six roles: `Grower`, `Inspector`, `RegulatoryOfficer`, `LogisticsOperator`, `Distributor`, and `Consumer`. Two of those roles are entity-backed and four are opaque operator identities — the distinction governs how `X-User-ID` is interpreted on every request:

- When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `PlantingBatch` owner (the grower's own user identifier); ownership checks on any resource referencing a planting batch compare the batch's `grower_id` field to `X-User-ID`. A grower may only operate on planting batches whose `grower_id` matches their own `X-User-ID`.
- When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting `Distributor` row; ownership checks on logistics legs compare `LogisticsLeg.to_party_id` to `X-User-ID` (a distributor may acknowledge only legs whose destination is itself), and ownership checks on disposal records compare the supplied `distributor_id` against `X-User-ID`.
- When `X-User-Role` is `Inspector`, `X-User-ID` is an opaque inspector identifier not tied to any persisted entity. The server records it on inspection reports as `inspector_id` for segregation-of-duties checks but does not compare it to any entity's `id`.
- When `X-User-Role` is `RegulatoryOfficer`, `X-User-ID` is an opaque officer identifier not tied to any persisted entity. The server may record it (for example, as `initiated_by_user_id` on a `RecallOrder`) but does not compare it to any entity's `id`.
- When `X-User-Role` is `LogisticsOperator`, `X-User-ID` is an opaque carrier identifier not tied to any persisted entity. It is recorded on agrochemical applications as `applied_by_user_id` only when the application is performed by an operator acting on the grower's behalf; otherwise the server does not compare it to any entity's `id`.
- When `X-User-Role` is `Consumer`, `X-User-ID` is an opaque consumer identifier not tied to any persisted entity. It is not compared to any entity's `id` and exists solely to attribute QR-code scans.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if omitted, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless an endpoint's section specifies otherwise (the QR full-chain trace and the leg sensor-readings list have explicit ordering rules), all list endpoints sort by `created_at` ascending.

Paginated and list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most primary entities — `PlantingBatch`, `StorageBin`, `LogisticsLeg`, `InspectionReport`, `Distributor`, `RecallOrder` — carry the standard system-managed fields:

- **`id`** (string): a server-minted UUID. The identifier is a bare UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp indicating the last mutation to the resource. It is updated on every change to the resource's properties, including derived-field reconciliations such as a `PlantingBatch` whose `total_quantity_kg` or `posture` is recomputed in response to a child event.
- **`version`** (integer): a server-managed integer that increments on every mutation. It supports optimistic concurrency control as described in §2.10.

Some entities are append-only or registry-style and therefore omit `updated_at` and `version` entirely; for these, only `id` and `created_at` are present. The entities that carry only `id` and `created_at` (no `updated_at`, no `version`) are: `PesticideRegistry`, `AgrochemicalApplication`, `HarvestRecord`, `SensorReading`, `QRCode`, and `AuditLog`. These records are immutable once written — corrections take the form of a new compensating record (for example, a revoked inspection report and a fresh draft) rather than in-place edits.

### 2.5. Hierarchical Consistency and Cascades

A planting batch is the apex of every traceability chain in the system, and side effects flow downward, upward, and across siblings whenever the batch's compliance posture changes.

**Downward cascade on recall.** When a recall is initiated for a batch (whether by a `RegulatoryOfficer` manually or auto-emitted by the cold-chain breach detector), the batch's `recall_status` flips to `ACTIVE_RECALL` and `status` becomes `RECALLED`; every `QRCode` row associated with any of the batch's harvest records has `revoked` set to true; and every `LogisticsLeg` of the batch currently in `PLANNED` or `IN_TRANSIT` is marked `ABNORMAL`. Each affected resource has its `updated_at` refreshed and its `version` incremented when the entity carries those fields.

**Upward cascade on harvest, application, and inspection.** Inserting an `AgrochemicalApplication` triggers a recompute of `earliest_legal_harvest_date` on the parent batch. Inserting a `HarvestRecord` increments the batch's `total_quantity_kg` and the destination `StorageBin`'s `occupied_kg`. Issuing an `InspectionReport` with a `PASS` result advances the batch to `INSPECTED_PASS`; issuing with a `FAIL` result advances to `INSPECTED_FAIL` and sets `posture` to `BLOCKED`. Revoking a previously issued report reverts the batch to `HARVESTED` and triggers a posture recomputation.

**Reverse cascade on cancel.** When a recall is cancelled before any disposal record has been appended, `recall_status` reverts to `NONE`, `revoked` on every previously cascaded `QRCode` is set back to false, and `PlantingBatch.status` reverts to whatever value it held immediately before recall initiation (the prior status is recovered from the matching `AuditLog` entry's `before_state` recorded at recall init).

Every cascade above is part of the same logical write as the triggering action. A reader who fetches a batch immediately after a child mutation observes the recomputed parent fields; partial visibility is never exposed.

### 2.6. Nested Resource Retrieval and Path Validation

Many endpoints take nested path parameters (for example, `/planting-batches/{id}/agrochemical-applications` or `/logistics-legs/{id}/sensor-readings`). The system validates path identifiers strictly left-to-right: the outer identifier must resolve before any inner identifier is even looked up. The first unresolved identifier yields `ERR_NOT_FOUND` immediately; the request never proceeds to deeper path components or to body validation. This ordering matters when a child resource happens to share an id with another batch's child — the parent in the URL is authoritative.

### 2.7. Numeric Precision and Rounding

Quantities expressed in kilograms (`quantity_kg`, `disposed_kg`, `capacity_kg`, `occupied_kg`, `total_quantity_kg`, `total_quantity_recalled_kg`, `total_quantity_disposed_kg`) are stored and reported with two decimal places, rounded half up. The order in which rounding is applied differs by calculation: for storage-bin occupancy, the running sum is computed from raw values and the final summed total is rounded half up to two decimal places; for recall disposal reconciliation, each `disposed_kg` input is rounded half up to two decimal places before the sum is taken, and the resulting sum is the final value with no further rounding. Dosage in grams per hectare (`dosage_g_per_hectare`, `max_dosage_per_hectare_g`) and area in hectares (`plot_area_hectares`) are stored at the precision the client supplied; the system performs no rounding on these inputs.

Laboratory measurements (`pesticide_residue_mg_per_kg`, `heavy_metals_mg_per_kg`, `microorganism_cfu_per_g`) are truncated to six decimal places before being compared to thresholds; no further rounding is applied. The withdrawal period is whole-day arithmetic: a date plus a `withdrawal_period_days` integer is again a date, stored at UTC midnight.

### 2.8. Optimistic Concurrency Control

Mutating endpoints that target a specific resource by id may carry an optional `version` field in the request body. When present, the server compares the supplied `version` to the current resource version; if they differ, the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted from the body, the server processes the mutation without an OCC check. This protection covers every PATCH endpoint and every state-transition endpoint that targets a single resource by id, ensuring callers acting on stale reads cannot silently overwrite a concurrent change.

### 2.9. Idempotency for Sensor Ingestion

IoT sensor ingestion is the highest-throughput write path in the system and is exposed to retry storms when carrier networks are unreliable. Every sensor reading is therefore submitted with a client-supplied `idempotency_key` that is unique within its parent leg. A second POST carrying the same `(logistics_leg_id, idempotency_key)` pair returns the originally-stored row with HTTP 200 and an outcome surfaced as `ERR_IDEMPOTENT_REPLAY` rather than creating a duplicate row. Repeat submissions therefore neither corrupt the chronological ordering used by the breach detector nor inflate `abnormal_segment_count`.

### 2.10. Compliance and Segregation of Duties

The API is structured so that no single role can both create and validate the same record. A `Grower` who registers a batch cannot inspect that batch — at issuance time the inspector's `X-User-ID` is compared against the batch's `grower_id`, and equality yields `ERR_SEGREGATION_VIOLATION`. A `Distributor` who acknowledges a leg must be the leg's destination party — the acknowledger's `X-User-ID` must equal `to_party_id`. A `Distributor` who records a disposal must supply a `distributor_id` matching their own `X-User-ID`. Recall initiation and recall completion are reserved to `RegulatoryOfficer`s, so the same actor who flags the violation also signs off on full disposal reconciliation. These constraints are mechanical, not advisory.

### 2.11. Validation Priority and Evaluation Order

Validations on every endpoint are evaluated in a fixed priority order, top to bottom. The order matters because the lower-numbered checks would otherwise be masked by spurious failures from higher-numbered ones, and because tests assert the specific `error_id` returned for each failure. Authentication runs first: header presence yields `ERR_AUTH_MISSING`, role recognition yields `ERR_AUTH_INVALID_ROLE`, RBAC permission yields `ERR_FORBIDDEN`. Path-parameter resolution is next, returning `ERR_NOT_FOUND`. State-machine validity comes after that, returning `ERR_INVALID_STATE` when the target resource is in a state that does not admit the requested transition.

Business safety rules outrank business referential rules, which outrank business temporal and constraint rules. Concretely, on agrochemical-application creation a prohibited-substance check (`ERR_PROHIBITED_SUBSTANCE`) is evaluated before the registration-existence check (`ERR_REGISTRATION_NOT_FOUND`) and before the dosage check (`ERR_DOSAGE_EXCEEDED`); on inspection-issue the segregation-of-duties check (`ERR_SEGREGATION_VIOLATION`) is evaluated before any computation of the report's pass/fail; on recall creation an existing-active-recall check (`ERR_RECALL_ALREADY_ACTIVE`) precedes any other recall-side validation. The `ERR_VERSION_CONFLICT` OCC check, when triggered, fires after authentication and existence and before state-transition logic. Generic shape errors — missing required body fields, type mismatches — surface as `ERR_VALIDATION` and are evaluated alongside the business-shape rules at the same tier.

## 3. Business Logic & Workflows

### 3.1. Pesticide Registry as the Substance Authority

The pesticide registry is the system's authoritative catalog of substances that may legally be applied to a crop. A `RegulatoryOfficer` populates and curates the registry. Each registry record carries a government-issued `registration_no` whose format conforms to one of two patterns — a pesticide identifier matching `^PD-[0-9]{6}$` or a fertilizer identifier matching `^FT-[0-9]{6}$` — and the `registration_no` value is unique across the registry. The record also carries the substance's `product_name`, its `category` (one of `PESTICIDE` or `FERTILIZER`), the regulatory `withdrawal_period_days` (a non-negative integer measured in days from last application to earliest legal harvest), and the regulatory `max_dosage_per_hectare_g` (the upper bound on application dosage in grams per hectare). On creation, a registry entry's `prohibited` flag defaults to false and its `prohibited_since` defaults to null; the registry record is immutable thereafter.

When a substance is later banned, a regulatory action prohibits the registry entry by setting `prohibited` to true and recording the date in `prohibited_since`. The historical record remains queryable — registry rows are never deleted, since past applications must remain inspectable. The query path supports two filters: `prohibited` to scope to currently-prohibited rows and `category` to scope to either pesticides or fertilizers.

### 3.2. Planting Batch Registration and the Compliance Posture

Every traceable unit begins as a planting batch registered by a `Grower`. The grower supplies a human-readable `batch_code` matching the pattern `^PB-[A-Z0-9]{8}$` (uppercase alphanumeric, 8 characters after the prefix); duplicate or malformed codes are rejected with `ERR_BATCH_CODE_INVALID`. The registration payload also carries the geographic `field_plot_id`, the `plot_area_hectares` (which must be strictly greater than zero), the `crop_variety`, the `planting_date`, the expected harvest window bounded by `expected_harvest_start` and `expected_harvest_end`, and the snapshot `grower_name`. The system enforces date sanity at registration: the planting date must be on or before the expected harvest start, and the expected harvest end must be on or after the expected harvest start; any violation yields `ERR_PLANTING_DATES_INVALID`. The registering grower's `X-User-ID` is captured as `grower_id` on the batch.

A newly registered batch starts in `REGISTERED` with `posture` `CLEAN`, `recall_status` `NONE`, `total_quantity_kg` 0, and `earliest_legal_harvest_date` null. The lifecycle thereafter walks through `REGISTERED → GROWING → HARVESTED`, then either `→ INSPECTED_PASS → IN_TRANSIT → DELIVERED` on the happy path or `→ INSPECTED_FAIL` on the failure path, with `RECALLED → DISPOSED` as a possible diversion from the post-inspection states. The terminal states are `DELIVERED` and `DISPOSED`. The `posture` field is the orthogonal compliance dimension — it can take the values `CLEAN`, `FLAGGED`, or `BLOCKED` — and is used by downstream endpoints (notably the leg-departure and leg-acknowledge transitions) to decide whether logistics may proceed even while `status` says the batch is otherwise in flight.

A grower may explicitly advance a batch from `REGISTERED` to `GROWING` without first recording an application; this declaration carries no body. The same transition occurs implicitly upon insertion of the first agrochemical application.

### 3.3. Agrochemical Application and the Earliest-Legal-Harvest Calculation

Within a registered or growing batch, a `Grower` records each pesticide or fertilizer application as it happens. The application payload carries the substance's `registration_no`, the `application_date` (which must be on or after the batch's `planting_date`), and the `dosage_g_per_hectare` (which must be strictly greater than zero). The acting grower's identifier is captured as `applied_by_user_id`. Three validations are evaluated in this order: the registry must contain a matching `registration_no` (else `ERR_REGISTRATION_NOT_FOUND`); the registry record must not be prohibited at the application date — meaning either `prohibited` is false, or `prohibited` is true but the application's `application_date` is strictly before `prohibited_since` — else `ERR_PROHIBITED_SUBSTANCE`; and the supplied `dosage_g_per_hectare` must be less than or equal to the registry's `max_dosage_per_hectare_g`, else `ERR_DOSAGE_EXCEEDED`.

After a successful insert, the system recomputes the batch's `earliest_legal_harvest_date`. The computation walks every agrochemical application on the batch (status filtering does not apply because applications are immutable once written) and, for each, looks up the referenced registry row to fetch its `withdrawal_period_days`. For each application the candidate earliest legal harvest is the application's `application_date` advanced by `withdrawal_period_days` whole days; the batch's `earliest_legal_harvest_date` is the latest of those candidates, stored at UTC midnight of the resulting date. If a batch has no applications recorded, the field is null. The computation also stores `withdrawal_end_date` on the inserted application itself — the application's own `application_date` plus its registry's `withdrawal_period_days`, again at UTC midnight.

Inserting the first application on a batch in `REGISTERED` simultaneously transitions the batch to `GROWING`. The audit log records both the create event on the application and the state-transition event on the batch.

### 3.4. Harvest, Storage Bins, and Capacity Reconciliation

Once the withdrawal period for the latest agrochemical application has elapsed, a `Grower` records harvests against the batch. Each harvest record carries a `harvest_date`, a `quantity_kg` (strictly greater than zero), a `quality_grade` from the enumeration `A`, `B`, `C`, or `REJECT`, a free-form `packaging_spec` such as a carton specification, and a `storage_bin_id` pointing to the warehouse bin that will hold the produce. The withdrawal-period guard rejects the insert with `ERR_WITHDRAWAL_NOT_ELAPSED` whenever `earliest_legal_harvest_date` is not null and `harvest_date` is strictly before it; equality with `earliest_legal_harvest_date` is permitted.

A storage bin is created by a `LogisticsOperator` with a `bin_code` matching the pattern `^WH-[A-Z][0-9]{3}$` (a single uppercase letter followed by three digits, prefixed by `WH-`), a `warehouse_zone` string such as `COLD` or `AMBIENT`, and a `capacity_kg` strictly greater than zero. The bin's `occupied_kg` is computed: it is the rounded-half-up sum, to two decimal places, of `quantity_kg` over every harvest record assigned to the bin whose parent batch has not reached the terminal `DELIVERED` or `DISPOSED` states. The bin's `status` is computed from the same query: it is `FULL` whenever the unrounded summed weight is at least the bin's `capacity_kg`; otherwise it is `QUARANTINE` if any related batch's `posture` is `BLOCKED`; otherwise it is `AVAILABLE`. A harvest insert is rejected with `ERR_BIN_CAPACITY_EXCEEDED` when the destination bin's current `occupied_kg` plus the new `quantity_kg` would exceed the bin's `capacity_kg`, or when the bin's `status` is `QUARANTINE` at the time of insertion.

A successful harvest insert appends to the batch's `total_quantity_kg`, refreshes the destination bin's `occupied_kg` and `status`, and — when this is the first harvest on the batch — transitions the batch from `GROWING` to `HARVESTED`. Both the create event on the harvest and the state transition on the batch are recorded in the audit log. Concurrent harvest writes targeting the same bin where their combined weight would breach capacity are serialized: the first writer succeeds and the second receives `ERR_BIN_CAPACITY_EXCEEDED` (the bin's `version` field is the optimistic-locking pivot for this serialization).

### 3.5. Inspection Reports and the Pass/Fail Decision

Once a batch has at least one harvest, an `Inspector` opens a draft inspection report against the batch. The draft is created with a `sampling_rule` from the enumeration `RANDOM_5PCT`, `FIXED_3KG`, or `FULL_LOT`, and a non-empty `test_items` array selecting any subset of `PESTICIDE_RESIDUE`, `HEAVY_METALS`, and `MICROORGANISMS`. For each test item selected, the corresponding measurement field is required: `pesticide_residue_mg_per_kg` for `PESTICIDE_RESIDUE`, `heavy_metals_mg_per_kg` for `HEAVY_METALS`, and `microorganism_cfu_per_g` for `MICROORGANISMS`; absent measurements for selected items surface as `ERR_VALIDATION`. The draft's `status` starts at `DRAFT`, `result` at `PENDING`, and `issued_at` at null; the inspector's identifier is captured as `inspector_id`.

Issuance is a separate action that runs the pass/fail computation and locks the report. Before computation runs, the segregation-of-duties guard fires: if the inspector's `X-User-ID` equals the batch's `grower_id`, the request is rejected with `ERR_SEGREGATION_VIOLATION`. The pass/fail computation then walks `test_items` in order. Each measurement is first truncated to six decimal places before comparison. For `PESTICIDE_RESIDUE`, the item passes when the truncated `pesticide_residue_mg_per_kg` is less than or equal to `0.50` (boundary inclusive — exact equality passes). For `HEAVY_METALS`, the item passes when the truncated `heavy_metals_mg_per_kg` is less than or equal to `0.20` (boundary inclusive — exact equality passes). For `MICROORGANISMS`, the item passes when the truncated `microorganism_cfu_per_g` is strictly less than `100000` (boundary strict — exact equality fails). The walk short-circuits on the first failing item: as soon as one item fails, the overall `result` is `FAIL` and the loop terminates without evaluating subsequent items, even if a later item would have passed. The audit log's change summary records which item caused the failure. Only when every item passes does the overall `result` become `PASS`.

Issuance sets the report's `status` to `ISSUED`, locks the computed `result`, and stamps `issued_at` to the current server time. A `PASS` result advances the parent batch from `HARVESTED` to `INSPECTED_PASS` and leaves `posture` `CLEAN` (unless an agrochemical violation has already pushed the batch to `FLAGGED`). A `FAIL` result advances the parent batch from `HARVESTED` to `INSPECTED_FAIL`, sets `posture` to `BLOCKED`, and as a follow-on cascade rejects every `LogisticsLeg` of the batch currently in `PLANNED`. An audit `STATE_TRANSITION` event is recorded on both the report and the batch.

A `RegulatoryOfficer` may revoke an issued report when the parent batch has not yet reached `DELIVERED` or `DISPOSED`. Revocation moves the report's `status` to `REVOKED` and reverts the batch to `HARVESTED`, with `posture` recomputed afterward. If an inspector attempts to issue a report whose state has shifted out of `DRAFT` between the time the inspector reads it and the time they issue it (for example, a parallel revoke by an officer affecting a sibling report), the issuance is rejected with `ERR_INVALID_STATE`.

### 3.6. Logistics Legs, Cold Chain, and Sensor Ingestion

Once a batch reaches `INSPECTED_PASS` it becomes eligible for shipping. A `LogisticsOperator` plans each leg of the chain individually. The plan payload supplies the `leg_index` (a positive integer that uniquely orders this leg within the batch's chain — every `(planting_batch_id, leg_index)` combination must be unique), the `from_party_id` and `to_party_id` opaque party identifiers, the planned `depart_at` and `arrive_at` instants (with `arrive_at` strictly after `depart_at`), and the cargo's required temperature window bounded by `temperature_min_c` and `temperature_max_c` (with the maximum at least the minimum). The leg also carries computed fields: `status` starts at `PLANNED`, `abnormal_segment_count` at 0, and `handover_acknowledged` at false.

Two legs of the same batch may not have overlapping intervals using closed-open semantics — leg A's interval is `[A.depart_at, A.arrive_at)`, leg B's interval is `[B.depart_at, B.arrive_at)`, and the system rejects the second plan with `ERR_LEG_INTERVAL_OVERLAP` when the two intervals share any instant. Two legs that touch at a single instant — A's `arrive_at` exactly equals B's `depart_at` — do not overlap and are accepted.

When the carrier dispatches the cargo, the operator marks the leg departed; the leg's `status` advances from `PLANNED` to `IN_TRANSIT`, and on the very first leg of the batch the parent batch's `status` advances from `INSPECTED_PASS` to `IN_TRANSIT`. Departure is rejected when `posture` is `BLOCKED` or when the batch's status is not in either `INSPECTED_PASS` or `IN_TRANSIT`. The system also requires that at least one harvest record on the batch already has a minted QR code before the first departure can occur.

Throughout transit, IoT sensor readings stream into the leg. Each reading carries a `device_id`, an `idempotency_key` unique within the leg (see §2.9), a `reading_at` timestamp, and a measured `temperature_c`. The reading's `out_of_range` flag is computed at insert time: it is true when `temperature_c` is strictly less than the leg's `temperature_min_c` or strictly greater than the leg's `temperature_max_c`; readings exactly at either boundary are in-range. The `reading_at` must lie in the half-open window that is left-open and right-closed: a reading at exactly `depart_at` is rejected with `ERR_READING_OUT_OF_LEG_WINDOW`, and a reading at exactly `arrive_at` is accepted; readings outside the window on either side are likewise rejected.

The cold-chain breach detector runs after every successful sensor insert. The detector pulls every reading on the leg, sorts them by `reading_at` ascending with `created_at` ascending as tie-breaker, and walks the sorted sequence. A run of three or more consecutive readings whose `out_of_range` is true counts as one abnormal segment; `abnormal_segment_count` is recomputed from scratch as the number of such runs. The detector handles out-of-order ingestion: when a late reading arrives whose `reading_at` predates already-ingested readings, the entire chronological replay is rerun and `abnormal_segment_count` is redeclared from the new sorted sequence rather than appended to. A leg whose `abnormal_segment_count` was non-zero may revert to its prior count under chronological replay, but only if `recall_status` on the parent batch is still `NONE`; once the breach has cascaded into a recall, the cascade is irreversible regardless of subsequent re-sorts. Whenever `abnormal_segment_count` becomes at least one and the leg is currently `IN_TRANSIT`, the leg auto-transitions to `ABNORMAL`, and if and only if `recall_status` is `NONE` at that moment, an automatic recall is emitted with `reason_code` `COLD_CHAIN_BREACH` — that recall walks the full `RECALLED` cascade described in §3.8.

Handover closes the leg. The receiving party acknowledges arrival, which sets `handover_acknowledged` to true and advances the leg's `status` from `IN_TRANSIT` to `HANDED_OVER`. The acknowledger's `X-User-ID` must equal the leg's `to_party_id`. When the acknowledged leg is the final leg recorded for the batch (no other leg has a greater `leg_index`), the parent batch advances from `IN_TRANSIT` to `DELIVERED`. Final-leg acknowledgement is rejected when the leg's `abnormal_segment_count` is greater than zero unless a recall triggered by cold-chain breach has been driven through a full disposal-and-close sequence. For a leg that reached `ABNORMAL`, only a `RegulatoryOfficer` may acknowledge — never the destination distributor — and acknowledgement is permitted only after the corresponding recall has been closed or explicitly overridden.

### 3.7. QR Code Minting and the Consumer Trace Path

Once a harvest record is locked, the `Grower` mints exactly one `QRCode` for it. The mint endpoint takes no body; the server generates an opaque `qr_code_value` (a 32-character hexadecimal string, server-unique) and an `anti_counterfeit_token` that is held privately and returned exactly once at mint time. The QR code carries the parent batch via `planting_batch_id` and the bound harvest via `harvest_record_id`. The one-code-one-product invariant is enforced by uniqueness on `harvest_record_id`: a second mint attempt on the same harvest is rejected with `ERR_QR_ALREADY_BOUND`.

Consumers and other downstream actors trace a product by submitting the `qr_code_value` and the `anti_counterfeit_token` to the trace endpoint. The lookup rejects with `ERR_QR_REVOKED` if the QR row's `revoked` is true (post-recall scans are blocked) and rejects with `ERR_QR_TOKEN_INVALID` if the supplied token does not match the stored token. On a successful trace, the response projects the full chain in a defined order: the planting block contains the batch's fields and its `agrochemical_applications` sorted by `application_date` ascending; the harvest block contains the bound `HarvestRecord`; the inspection block contains the most recent `InspectionReport` for the batch whose `status` is `ISSUED` (sorted by `issued_at` descending with `id` ascending as the tie-break); the logistics block contains the batch's legs sorted by `leg_index` ascending, each carrying its `abnormal_segment_count`. Every successful 200 increments the QR's `scan_count` by one — the increment is not idempotent across rapid same-second scans; every successful response is a count.

### 3.8. Recall Initiation, Notification, Disposal, and Closure

A recall is the system's escape hatch when a batch's compliance posture cannot be salvaged. It is opened by a `RegulatoryOfficer` (or auto-emitted by the cold-chain detector). The initiation payload supplies the target `planting_batch_id`, the severity `recall_class` from the enumeration `CLASS_I`, `CLASS_II`, or `CLASS_III`, and the `reason_code` from the enumeration `INSPECTION_FAIL`, `COLD_CHAIN_BREACH`, `PROHIBITED_SUBSTANCE`, or `CONSUMER_COMPLAINT`. The officer's `X-User-ID` is captured as `initiated_by_user_id`. The recall is permitted only when the target batch's status is in the set `INSPECTED_PASS`, `IN_TRANSIT`, or `DELIVERED`. If the batch already has an `ACTIVE_RECALL` recall, the request is rejected with `ERR_RECALL_ALREADY_ACTIVE`.

The recall starts in `INITIATED`. The system computes `scope_distributor_ids` as the distinct `to_party_id` values appearing on any `LogisticsLeg` of the batch where the destination party is a registered `Distributor`; this set drives subsequent notification routing. The system also computes `total_quantity_recalled_kg` at initiation as the sum of `quantity_kg` over every `HarvestRecord` for the batch whose `created_at` is on or before the recall's `created_at` — late harvests on an already-recalled batch are excluded from the recall's scope and rejected separately by validation. The cascade described in §2.5 fires immediately: the batch moves to `RECALLED` with `recall_status` `ACTIVE_RECALL`, every `QRCode` for the batch has `revoked` set to true, and every `LogisticsLeg` in `PLANNED` or `IN_TRANSIT` is marked `ABNORMAL`. An audit `RECALL_INITIATE` and corresponding `STATE_TRANSITION` events are recorded.

Two simultaneous recalls on the same batch serialize on the batch's `recall_status` flip from `NONE` to `ACTIVE_RECALL`: the first writer succeeds and the second receives `ERR_RECALL_ALREADY_ACTIVE`.

Notification advances the recall from `INITIATED` to `NOTIFIED`. For each distributor in `scope_distributor_ids`, the system emits a `recall_notification` event addressed to the distributor's `notification_endpoint` (captured at distributor registration alongside `name`, `contact_email`, and `tier` from the enumeration `WHOLESALE` or `RETAIL`). An audit `RECALL_NOTIFY` event is recorded.

Disposal is the distributor-side leg of the workflow. Each `Distributor` in the scope records one or more disposal entries against the recall. The disposal payload supplies the `distributor_id` (which must equal the acting distributor's own `X-User-ID`), the `disposed_kg` (the weight disposed of, which is rounded half up to two decimal places before being summed), and the `disposed_at` timestamp. The first disposal advances the recall from `NOTIFIED` to `IN_PROGRESS`; subsequent disposals stay in `IN_PROGRESS` and append to the recall's append-only `disposal_records` array — once an entry is appended, it is immutable. Each insert recomputes `total_quantity_disposed_kg` by walking `disposal_records` ordered by `disposed_at` ascending with `created_at` ascending as tie-break, applying the per-record rounding rule first and then summing. A disposal that would push the cumulative disposed weight strictly above `total_quantity_recalled_kg` is rejected with `ERR_RECALL_OVER_DISPOSED`.

Closure is the regulatory officer's final action. Completion is permitted only when the recall is in `IN_PROGRESS` and the running residual is exactly zero — that is, `total_quantity_disposed_kg` equals `total_quantity_recalled_kg`. A non-zero residual yields `ERR_RECALL_RESIDUAL_NONZERO`; this boundary is strictly zero, not less than or equal to zero. On success, the recall's `status` advances to `COMPLETED`, the parent batch's `recall_status` advances to `COMPLETED`, the batch's `status` advances to `DISPOSED`, and audit `RECALL_COMPLETE` and corresponding `STATE_TRANSITION` events are recorded.

Cancellation is the alternate exit. An officer may cancel a recall while it is still in `INITIATED` and no disposal record has been appended; the recall's `status` advances to `CANCELLED`, the batch's `recall_status` reverts to `NONE`, the batch's `status` reverts to whatever it held immediately before recall initiation (recovered from the audit log's `change_summary.before_state`), and the previously-cascaded `revoked` flags on every `QRCode` of the batch are set back to false. Cancellation against a recall that already has at least one disposal record is rejected with `ERR_RECALL_HAS_DISPOSALS`. A simultaneous disposal-and-cancel race serializes on the recall's `status`: if the cancel commits first, the disposal arrives to find the recall no longer `IN_PROGRESS` or `NOTIFIED` and is rejected with `ERR_INVALID_STATE`; if the disposal commits first, the cancel finds at least one disposal record present and is rejected with `ERR_RECALL_HAS_DISPOSALS`.

A simultaneous inspector-issue and officer-revoke on the same batch's report serializes on the report's `status`: exactly one operation succeeds, and the loser receives `ERR_INVALID_STATE` because the target `status` has changed by the time the loser's check runs. A simultaneous QR mint by two callers on the same harvest serializes on the unique-`harvest_record_id` constraint; the loser receives `ERR_QR_ALREADY_BOUND`. Two POSTs of the same `(logistics_leg_id, idempotency_key)` pair return the originally-stored row with HTTP 200 and an `ERR_IDEMPOTENT_REPLAY` outcome; no duplicate row is ever written.

### 3.9. Audit Trail, Event Synchronization, and Test-Driving Utilities

Every state transition, every recall action, and every entity creation produces an `AuditLog` row. Each row carries the actor's `actor_user_id` and `actor_role`, the affected `entity_type` from the enumeration `PlantingBatch`, `AgrochemicalApplication`, `HarvestRecord`, `InspectionReport`, `LogisticsLeg`, `RecallOrder`, `QRCode`, the affected `entity_id`, the `action` taken (one of `CREATE`, `UPDATE`, `STATE_TRANSITION`, `RECALL_INITIATE`, `RECALL_NOTIFY`, `RECALL_DISPOSE`, `RECALL_COMPLETE`), the `before_state` (null on `CREATE`), the `after_state`, and a `change_summary` JSON object capturing the field deltas relevant to the action (for example, the first failing test item on a `FAIL` issuance, or the prior batch status at recall initiation). Audit access is reserved to a `RegulatoryOfficer`; the listing endpoint accepts `entity_type`, `entity_id`, and `action` filters in addition to the standard pagination knobs.

Two test-driving utilities are reserved for `RegulatoryOfficer`. The first is an admin-only logical-clock advance capability: it accepts a target instant in `to` and fast-forwards the server's notion of "now" to drive time-gated rules such as withdrawal-period elapse and recall scope snapshots in test scenarios. The second is an admin-only event-injection capability that simulates an external regulatory, logistics, or retail event to exercise the event-driven sync paths; it accepts an `event_type` and a `payload`, and may itself trigger a recall (for example, on a `REGULATORY_PROHIBITION_NOTICE` event) or a distributor notification.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a planting batch, an agrochemical application, a harvest record, a logistics leg, a sensor reading, an inspection report, a QR code, a distributor, a recall order, a disposal entry) return `201 Created`. Operations that modify an existing resource — state transitions, prohibitions, notifications, completions, cancellations, acknowledgements, revocations, and the test-driving utilities — return `200 OK`. Read endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/pesticide-registry`                                              | Register a pesticide or fertilizer entry                                | RegulatoryOfficer |
| GET    | `/pesticide-registry`                                              | List registry entries; supports prohibited and category filters         | RegulatoryOfficer, Grower, Inspector |
| PATCH  | `/pesticide-registry/{registration_no}/prohibit`                   | Prohibit an existing registry entry                                     | RegulatoryOfficer |
| POST   | `/planting-batches`                                                | Register a new planting batch                                           | Grower |
| GET    | `/planting-batches`                                                | List batches; supports status, posture, recall_status filters           | Grower, Inspector, RegulatoryOfficer |
| GET    | `/planting-batches/{id}`                                           | Read a planting batch                                                   | Grower, Inspector, RegulatoryOfficer, LogisticsOperator, Distributor |
| POST   | `/planting-batches/{id}/declare-growing`                           | Optional explicit advance of a batch to GROWING                         | Grower |
| POST   | `/planting-batches/{id}/agrochemical-applications`                 | Record a pesticide or fertilizer application                            | Grower |
| GET    | `/planting-batches/{id}/agrochemical-applications`                 | List a batch's agrochemical applications                                | Grower, Inspector, RegulatoryOfficer |
| POST   | `/planting-batches/{id}/harvest-records`                           | Record a harvest entry                                                  | Grower |
| GET    | `/planting-batches/{id}/harvest-records`                           | List a batch's harvest records                                          | Grower, Inspector, RegulatoryOfficer |
| POST   | `/storage-bins`                                                    | Create a warehouse bin                                                  | LogisticsOperator |
| GET    | `/storage-bins/{id}`                                               | Read a bin including current occupancy                                  | LogisticsOperator, Grower, RegulatoryOfficer |
| POST   | `/planting-batches/{id}/logistics-legs`                            | Plan a logistics leg for the batch                                      | LogisticsOperator |
| POST   | `/logistics-legs/{id}/depart`                                      | Mark a leg as departed                                                  | LogisticsOperator |
| POST   | `/logistics-legs/{id}/acknowledge`                                 | Acknowledge a leg's handover                                            | Distributor, LogisticsOperator, RegulatoryOfficer |
| GET    | `/planting-batches/{id}/logistics-legs`                            | List a batch's legs ordered by leg_index ascending                      | Grower, Inspector, RegulatoryOfficer, LogisticsOperator, Distributor |
| POST   | `/logistics-legs/{id}/sensor-readings`                             | Ingest an IoT temperature reading (idempotent)                          | LogisticsOperator |
| GET    | `/logistics-legs/{id}/sensor-readings`                             | List readings for a leg sorted by reading_at ascending                  | LogisticsOperator, RegulatoryOfficer |
| POST   | `/planting-batches/{id}/inspection-reports`                        | Create a draft inspection report                                        | Inspector |
| POST   | `/inspection-reports/{id}/issue`                                   | Issue the report; runs pass/fail; cascades batch                        | Inspector |
| POST   | `/inspection-reports/{id}/revoke`                                  | Revoke an issued report; cascades batch back to HARVESTED               | RegulatoryOfficer |
| POST   | `/harvest-records/{id}/qr-code`                                    | Mint the QR code for a harvest record (one per record)                  | Grower |
| GET    | `/qr-codes/{qr_code_value}/trace`                                  | Consumer full-chain trace                                               | Consumer, RegulatoryOfficer, Distributor |
| POST   | `/distributors`                                                    | Register a distributor                                                  | RegulatoryOfficer |
| GET    | `/distributors`                                                    | List distributors; supports tier filter                                 | RegulatoryOfficer, LogisticsOperator |
| POST   | `/recall-orders`                                                   | Initiate a recall                                                       | RegulatoryOfficer |
| POST   | `/recall-orders/{id}/notify`                                       | Send recall notification to scope distributors                          | RegulatoryOfficer |
| POST   | `/recall-orders/{id}/disposals`                                    | Record a distributor's disposal                                         | Distributor |
| POST   | `/recall-orders/{id}/complete`                                     | Finalize a recall after full disposal                                   | RegulatoryOfficer |
| POST   | `/recall-orders/{id}/cancel`                                       | Cancel a recall before any disposal                                     | RegulatoryOfficer |
| GET    | `/recall-orders/{id}`                                              | Read a recall order including disposal history                          | RegulatoryOfficer, Distributor |
| GET    | `/audit-logs`                                                      | Query the audit trail                                                   | RegulatoryOfficer |
| POST   | `/_clock/advance`                                                  | Test-only logical-clock advance                                         | RegulatoryOfficer |
| POST   | `/_events/emit`                                                    | Test-only external event injection                                      | RegulatoryOfficer |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_AUTH_MISSING`                | 401 Unauthorized |
| `ERR_AUTH_INVALID_ROLE`           | 401 Unauthorized |
| `ERR_FORBIDDEN`                   | 403 Forbidden    |
| `ERR_NOT_FOUND`                   | 404 Not Found    |
| `ERR_INVALID_STATE`               | 409 Conflict     |
| `ERR_VERSION_CONFLICT`            | 409 Conflict     |
| `ERR_PROHIBITED_SUBSTANCE`        | 422 Unprocessable Entity |
| `ERR_REGISTRATION_NOT_FOUND`      | 422 Unprocessable Entity |
| `ERR_DOSAGE_EXCEEDED`             | 422 Unprocessable Entity |
| `ERR_WITHDRAWAL_NOT_ELAPSED`      | 422 Unprocessable Entity |
| `ERR_BIN_CAPACITY_EXCEEDED`       | 409 Conflict     |
| `ERR_BATCH_CODE_INVALID`          | 422 Unprocessable Entity |
| `ERR_PLANTING_DATES_INVALID`      | 422 Unprocessable Entity |
| `ERR_LEG_INTERVAL_OVERLAP`        | 422 Unprocessable Entity |
| `ERR_READING_OUT_OF_LEG_WINDOW`   | 422 Unprocessable Entity |
| `ERR_IDEMPOTENT_REPLAY`           | 200 OK           |
| `ERR_SEGREGATION_VIOLATION`       | 403 Forbidden    |
| `ERR_QR_ALREADY_BOUND`            | 409 Conflict     |
| `ERR_QR_REVOKED`                  | 409 Conflict     |
| `ERR_QR_TOKEN_INVALID`            | 403 Forbidden    |
| `ERR_RECALL_ALREADY_ACTIVE`       | 409 Conflict     |
| `ERR_RECALL_OVER_DISPOSED`        | 422 Unprocessable Entity |
| `ERR_RECALL_RESIDUAL_NONZERO`     | 422 Unprocessable Entity |
| `ERR_RECALL_HAS_DISPOSALS`        | 409 Conflict     |
| `ERR_VALIDATION`                  | 400 Bad Request  |
