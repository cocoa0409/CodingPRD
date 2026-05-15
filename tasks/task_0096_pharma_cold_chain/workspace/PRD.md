# Pharma Cold Chain API — Product Requirements Document

## 1. Introduction

Pharmaceutical distribution centres operate under a regulatory regime that treats temperature history, segregation, and lot provenance as legally significant artefacts: a single hour at the wrong temperature on the wrong pallet can void a Class II batch and trigger a full downstream recall. Today, the manual coordination between receiving docks, the QA function, picking lines, and the recall office routinely loses tens of person-hours per excursion event reconciling sensor traces, carrier logger printouts, and bin maps that disagree with each other — and when a customer-facing recall is required, the same data has to be reassembled under a regulator clock measured in hours.

This document specifies the back-end API for a unified cold-chain warehouse management service. The system is the system of record for warehouse topology (zones, bins, capacities, alarm thresholds), inbound receipt workflows with carrier-logger verification, FEFO-driven bin allocation and outbound picking, real-time temperature deviation classification with cascading stock isolation, and lot-recall coordination across regulatory authority, GSP reporting, pharmacovigilance, and TMS integrations. The deliberate emphasis throughout is on deterministic, auditable, and segregation-of-duties-aware execution: every meaningful change of state writes an audit-log entry and (where applicable) an outbound external-system event, every transition between two parties is gated against single-actor compromise, and every numeric outcome is reconstructible from the inputs the user supplied.

The API is mounted under the top-level path `/warehouses` for warehouse-scoped resources, with cross-cutting roots `/suppliers`, `/products`, `/zones`, `/receipts`, `/lots`, `/shipments`, `/deviations`, `/capas`, and `/recalls` for the entities whose identifiers carry through the URL once minted. Time is modelled by a deterministic per-warehouse clock measured in integer minutes since a logical epoch; production behaviour and test reproducibility both depend on this clock advancing only through explicit API calls.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which selects the operator's role for authorisation. A request missing the role header is rejected with `ERR_AUTH_MISSING_ROLE` (HTTP 401); a request missing the user header is rejected with `ERR_AUTH_MISSING_USER` (HTTP 401); a request whose role is not authorised for the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles are recognised, with exact spelling: `WarehouseAdmin`, `Receiver`, `QAOfficer`, `Picker`, and `RecallOfficer`. For all five roles, `X-User-ID` is an opaque operator identifier — none of the roles is backed by a persisted user entity, and the server does not compare `X-User-ID` to any entity's `id`. The server does, however, record the calling identity wherever audit and segregation-of-duties enforcement require it: every state-changing operation persists the acting `X-User-ID` and `X-User-Role` as the `actor_user_id` and `actor_role` of an `AuditLogEntry` row, and the same identifier is used to enforce the segregation-of-duties checks described later (for example, the inspector of an inbound receipt must not be the same `X-User-ID` that performs the corresponding acceptance, and the assessor of a deviation must not be the same `X-User-ID` that announces a recall built from the lots that deviation affected; both surface as `ERR_SOD_VIOLATION` with HTTP 403).

A `WarehouseAdmin` is the configuration role: it creates warehouses, zones, and bins, registers suppliers and products, ingests temperature readings, advances the deterministic clock, and runs the housekeeping sweep. A `Receiver` is responsible for booking inbound deliveries and recording the first-pass inspection. A `QAOfficer` is the quality role: it accepts, quarantines, releases-from-quarantine, or rejects inspected receipts, assesses closed deviations, releases quarantined shipments back to packed, and closes CAPAs. A `Picker` is the outbound operator: it creates shipments, executes the FEFO pick, packs, dispatches, and cancels. A `RecallOfficer` runs the recall lifecycle from draft through closure.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and has a maximum of 100; `offset` defaults to 0 and has no upper bound other than the underlying total. Results are returned in ascending order of `created_at`. List responses populate `limit`, `offset`, `total_count`, and `has_more` inside the `meta` block as described in §2.2.

### 2.4. Common Resource Properties and Identifier Conventions

Every resource minted by the API is assigned a server-minted UUID in the `id` field — there is no type prefix on identifiers (a warehouse `id` and a recall `id` are both bare UUIDs and only their referencing context disambiguates them). Resources that carry the standard mutable contract additionally expose `created_at` and `updated_at` (ISO 8601 UTC with three fractional digits) and `version` (an integer that starts at 1 on creation and increments by 1 on every successful mutation). Three resource families are deliberately append-only and do not carry `updated_at` or `version`: temperature events (`TemperatureEvent`), recall scope entries (`RecallScopeEntry`), external-system synchronisation events (`ExternalSyncEvent`), and audit log entries (`AuditLogEntry`). For those four entities, only `id` and `created_at` are present.

Body-referenced foreign keys — for example `supplier_id`, `product_id`, and `customer_id` on receipt and shipment creation — must point at existing resources; a missing target yields `ERR_NOT_FOUND` (HTTP 404). When a URL nests resources (for example a zone under a warehouse under the API root), path parameters are validated left to right: the outer resource is checked first, the inner second, and the first failure short-circuits with `ERR_NOT_FOUND`.

### 2.5. Optimistic Concurrency Control and Version Semantics

All state-changing operations on existing resources accept an optional `version` field inside the request body. When `version` is supplied, the server compares it against the resource's current `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When `version` is omitted, the optimistic-concurrency check is skipped and the request proceeds against the latest committed state.

On every successful mutation the affected resource's `version` increments by exactly 1 and its `updated_at` refreshes. Where a single operation cascades into sibling resources (for example, a hold that flips many bins from `AVAILABLE` to `LOCKED`, or a deviation closure that quarantines many lots), every resource the operation actually mutated has its `version` bumped and its `updated_at` refreshed; resources that were merely read are untouched.

### 2.6. Status Codes

A request that mints a brand-new resource returns HTTP 201; every other successful operation — including state transitions on existing resources, the deterministic clock advance, and the sweep — returns HTTP 200. List endpoints return HTTP 200.

### 2.7. The Deterministic Clock

Each warehouse carries its own logical clock — `clock_minutes`, a non-negative integer measured in minutes since a per-warehouse epoch and defaulting to 0 on warehouse creation. The clock advances only through explicit operator action: the dedicated clock-advance capability accepts a positive `minutes` increment, adds it to `clock_minutes`, and triggers any time-gated cascades that have become due (most importantly, CAPAs whose `due_minutes` has elapsed transition to `OVERDUE`, and recalls in `RETURNS_IN_PROGRESS` past their `report_due_minutes` auto-advance to `EFFECTIVENESS_CHECK`). All time-bearing fields on every entity — `expiry_minutes`, `qualification_expiry_minutes`, `at_minutes`, `started_at_minutes`, `ended_at_minutes`, `dispatched_at_minutes`, `initiated_at_minutes`, `report_due_minutes`, and `due_minutes` — are integers in the same minutes-since-epoch coordinate.

A companion housekeeping sweep capability is idempotent: invoking it once or many times within the same logical minute produces the same end state. The sweep walks every CAPA in the warehouse and flips any whose `due_minutes` is strictly less than `clock_minutes` into `OVERDUE`, advances any recall whose deadline has elapsed past `RETURNS_IN_PROGRESS`, and recomputes zone posture from currently open deviations.

### 2.8. Hierarchical Consistency: Bin, Zone, and Warehouse Roll-up

Bin-level state is the source of truth for utilisation: a bin's `occupied_volume` and `occupied_weight_kg` rise on allocation and fall on pick or cancel. The parent zone's `utilization_units` is always exactly the sum of `occupied_volume` across its child bins — recomputed inline at the end of every request handler that touched any of those bins, with the recompute order pinned as bin-level fields first, then the zone-level roll-up, then any warehouse-level aggregates. No drift between bins and their parent zone is ever permitted to persist past the end of a single request.

The same hierarchical contract drives `version`/`updated_at` propagation: when a bin's stock state changes as part of an accept, pick, or cancel, both the bin and its parent zone have their `version` and `updated_at` refreshed because both rows were mutated.

### 2.9. Precision and Rounding

Two precision regimes apply. Temperature readings and deviation magnitudes are recorded in Celsius and rounded to two decimal places using round-half-up. Monetary amounts produced by the shipment-summary calculation are computed in integer cents at the per-line level, each per-line component being rounded half-up to whole cents before being summed; the final total is therefore always an integer in cents. Effectiveness ratios are rounded to four decimal places using round-half-up before being compared against the threshold. All time values are integer minutes and require no rounding.

### 2.10. Cold-Chain Integrity and Zone Posture

Each zone broadcasts a single posture in `current_posture` — one of `OPEN`, `RESTRICTED`, or `FROZEN` — which derives entirely from the zone's currently open deviations. `OPEN` is the steady state. A `MINOR`-classified open deviation moves the zone to `RESTRICTED`, in which picks may still proceed against already-released lots but new allocations from inbound acceptance are blocked. Any alarm-level reading (whether `ALARM_LOW` or `ALARM_HIGH`) drives the zone to `FROZEN`; while a zone is `FROZEN`, every child bin's `status` flips to `LOCKED`, and any attempt to accept, release-from-quarantine, or pick against those bins is rejected with `ERR_ZONE_FROZEN` (HTTP 409). When the underlying deviation finally reaches `CLOSED_ASSESSED` and no other deviation on the zone is still open, the zone returns to `OPEN`; bins that were `LOCKED` revert to `AVAILABLE` or `OCCUPIED` according to whether their `current_lot_id` is null.

### 2.11. Concurrency Outcomes

Five concurrent-edit scenarios have specific, named winners and losers. When two `QAOfficer` calls attempt to accept the same inbound receipt at the same moment, the first writer wins the `INSPECTED` to `ACCEPTED` transition and the loser is rejected with `ERR_RECEIPT_NOT_INSPECTED` (HTTP 409). When two pickers race for the last available units of a single lot, the first writer wins the atomic decrement on `quantity_on_hand` and the loser is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 409). When two FEFO bin allocations target the same bin, the first writer wins the `current_lot_id` assignment while the bin was `AVAILABLE` and the loser is rejected with `ERR_BIN_UNAVAILABLE` (HTTP 409). When a `QAOfficer` assess on a deviation arrives at the same moment a new alarm event would open a fresh deviation on the same zone, the in-flight deviation's assessment wins; the new alarm always materialises as a separate `Deviation` row rather than mutating the row currently under assessment, and a duplicate assess against an already-progressed deviation is rejected with `ERR_DEVIATION_STATE_INVALID` (HTTP 409). When two `RecallOfficer` calls attempt to announce the same recall, the first writer wins the `DRAFT` to `ANNOUNCED` transition and the loser is rejected with `ERR_RECALL_NOT_DRAFT` (HTTP 409).

### 2.12. Validation Priority Order

When more than one rule could fail on the same request, the rules are evaluated in a fixed priority order. The earliest categories are header authentication and authorisation: a missing `X-User-Role` is the first failure (`ERR_AUTH_MISSING_ROLE`), followed by a missing `X-User-ID` (`ERR_AUTH_MISSING_USER`), followed by RBAC denial (`ERR_FORBIDDEN`). Existence checks follow: path-bound resources are validated left to right (`ERR_NOT_FOUND`), then body-referenced foreign keys on receipt and shipment creation (`ERR_NOT_FOUND`). State preconditions evaluate next, in the order receipt-pending check (`ERR_RECEIPT_NOT_PENDING`), receipt-inspected check (`ERR_RECEIPT_NOT_INSPECTED`), shipment state (`ERR_SHIPMENT_STATE_INVALID`), recall-not-draft (`ERR_RECALL_NOT_DRAFT`), deviation state (`ERR_DEVIATION_STATE_INVALID`). Cold-chain safety follows: zone-frozen blocking (`ERR_ZONE_FROZEN`), then supplier qualification (`ERR_UNQUALIFIED_SUPPLIER`), then product qualification (`ERR_UNQUALIFIED_PRODUCT`), then lot expiry (`ERR_EXPIRED_LOT`). Business constraints follow in this declared order: packaging match (`ERR_PACKAGING_MISMATCH`), segregation (`ERR_SEGREGATION_VIOLATION`), FEFO discipline (`ERR_FEFO_VIOLATION`), temperature pre-check (`ERR_TEMP_PRECHECK_FAIL`), bin capacity (`ERR_BIN_CAPACITY_EXCEEDED`), positive-quantity check on shipment creation (`ERR_QUANTITY_INVALID`), pick-time stock availability (`ERR_INSUFFICIENT_STOCK`), and segregation-of-duties enforcement (`ERR_SOD_VIOLATION`). Referential and temporal rules follow: logger data validity (`ERR_LOGGER_DATA_INVALID`), recall scope non-empty (`ERR_RECALL_SCOPE_EMPTY`), return scope validity (`ERR_RETURN_SCOPE_INVALID`), temperature event timing (`ERR_TEMP_EVENT_TIME_INVALID`), recall deadline sanity (`ERR_RECALL_DEADLINE_INVALID`). The zone-capacity budget (`ERR_ZONE_CAPACITY_EXCEEDED`) is the final business check, followed by the optimistic-concurrency check (`ERR_VERSION_CONFLICT`). The practical implication is that, for example, a request that violates both a zone-frozen rule and a segregation rule surfaces as `ERR_ZONE_FROZEN`, not `ERR_SEGREGATION_VIOLATION` — the earlier rule wins.

### 2.13. Audit Trail and External-System Synchronisation

Every state-changing action persists an `AuditLogEntry` row carrying the warehouse, the acting `actor_user_id`, the acting `actor_role`, a verb-plus-entity `action` string, the `target_id` of the affected entity, and the `at_minutes` clock reading at write. Audit entries are append-only and tamper-evident — they carry only `id` and `created_at`, never `updated_at` or `version`. A parallel append-only `ExternalSyncEvent` log carries, for each event the system publishes downstream, the `target_system` (`REGULATORY_AUTHORITY`, `GSP_REPORT`, `PHARMACOVIGILANCE`, or `TMS`), the `event_type` (`INBOUND_ACCEPTED`, `INBOUND_QUARANTINED`, `DEVIATION_OPENED`, `DEVIATION_CLOSED`, `RECALL_ANNOUNCED`, `RECALL_CLOSED`, `SHIPMENT_DISPATCHED`, or `CAPA_OVERDUE`), and a `payload` snapshot of the relevant ids and counts. The relationship between operational verbs and the sync events they emit is described inline in the workflows in §3 — for example, an accepted receipt produces two sync events, one targeted at the regulatory authority and one at GSP reporting, while a quarantined receipt produces only the regulatory authority event.

## 3. Business Logic & Workflows

### 3.1. Warehouse, Zone, and Bin Topology

A warehouse is the configuration root for everything else: it carries a unique short `code`, a display `name`, a `gsp_license_no` for the operating licence, a `status` that defaults to `ACTIVE` (the alternative is `SUSPENDED`), and the `clock_minutes` register described in §2.7. Creation by a `WarehouseAdmin` mints the warehouse with `clock_minutes` of 0; from that point onwards, `clock_minutes` advances only through the dedicated clock-advance capability, which accepts a positive `minutes` increment and applies it.

A zone is created under a warehouse with a `code` unique within that warehouse, a `zone_type` (one of `FROZEN`, `REFRIGERATED`, `COOL`, `ROOM_TEMP`, `CONTROLLED_TEMP`, or the special `QUARANTINE` bucket reserved for non-conforming receipts and returned recall stock), an inclusive permitted operating range expressed as `target_temp_low_c` and `target_temp_high_c` in Celsius, two hard alarm thresholds expressed as `alarm_low_c` (which lies below `target_temp_low_c`) and `alarm_high_c` (which lies above `target_temp_high_c`), and a total `capacity_units` budget that fixes the zone's aggregate storage budget — the sum of its child bins' `volume_units`. The zone's `current_posture` starts at `OPEN`, `last_sensor_reading_c` starts null, and `utilization_units` starts at 0; all three are computed thereafter from child bin state and incoming temperature events.

Within a zone, a `WarehouseAdmin` creates bins, each carrying a `code` unique within its parent zone, a `volume_units` capacity in abstract storage units, a `weight_limit_kg` cap, and an optional `special_storage_tag` defaulting to `NONE` and taking values from the segregation universe (`NONE`, `NARCOTIC`, `PSYCHOTROPIC`, `BIOLOGICAL`, `VACCINE`). Each bin's parent is recorded in its `zone_id`, and a denormalised `warehouse_id` is carried alongside to speed FEFO and recall queries. The bin exposes computed `current_lot_id` (null when empty), `occupied_volume`, `occupied_weight_kg`, and `status` (`AVAILABLE`, `OCCUPIED`, or `LOCKED`). Initial state is empty and `AVAILABLE`. List queries against bins accept an optional `filter[status]` and list queries against zones accept `filter[zone_type]` and `filter[current_posture]`.

Suppliers and products are flat master-data resources. A supplier carries a legal `name`, a boolean `qualified` flag defaulting to true, and a `qualification_expiry_minutes` after which the qualification lapses. A product carries a unique `sku`, a display `name`, a `required_zone_type` (the storage class it must live in, drawn from the same temperature universe except `QUARANTINE`), an optional `special_storage_tag` defaulting to `NONE`, a `qualified` flag defaulting to true, a per-unit weight in `unit_weight_kg`, and a `stability_budget_minutes` — the maximum cumulative out-of-range minutes the product can tolerate before quality is presumed lost, used downstream by the deviation cascade.

### 3.2. Inbound Receipt, Inspection, and Quality Decision

An inbound receipt is booked by a `Receiver` against a warehouse with a payload containing the originating `supplier_id`, the `product_id` to be stocked, the `lot_number` from the manufacturer, the lot's `expiry_minutes`, the received `quantity_units`, the chronological `carrier_logger_readings` array (each element being a `{minutes, temp_c}` pair from the carrier's data logger), and a boolean `visual_pass` recording the visual-and-packaging inspection outcome. The receipt is born in `PENDING_INSPECTION` with a null `assigned_bin_id`, a null `acceptance_certificate_no`, a null `temp_chain_intact`, and a `nonconformance_reason` not yet computed. The denormalised `warehouse_id` is fixed from the URL.

Inspection by the same `Receiver` role advances the receipt from `PENDING_INSPECTION` to `INSPECTED`. The inspect call requires that `carrier_logger_readings` is non-empty and that `visual_pass` is provided; the readings array must additionally be monotonic in `minutes` (each entry's `minutes` is greater than or equal to the previous entry's), and violating either of these surfaces as `ERR_LOGGER_DATA_INVALID` (HTTP 422). On a valid inspect, the system computes `temp_chain_intact` as true if and only if every entry's `temp_c` falls within the permitted operating range of the product's `required_zone_type` (looked up against any zone of that type in the warehouse, since all zones of the same type share the same `target_temp_low_c` and `target_temp_high_c`). The system then computes `nonconformance_reason` using a strict priority cascade — the first matching reason wins, all others are ignored. The priority order is: `UNQUALIFIED_SUPPLIER` (the supplier's `qualified` flag is false or `qualification_expiry_minutes` is less than or equal to the warehouse's `clock_minutes`), then `UNQUALIFIED_PRODUCT` (the product's `qualified` flag is false), then `EXPIRED_ON_ARRIVAL` (the lot's `expiry_minutes` is less than or equal to the warehouse's `clock_minutes`), then `VISUAL_FAIL` (`visual_pass` is false), then `TEMP_EXCURSION` (`temp_chain_intact` is false). If none of those match, `nonconformance_reason` is set to `NONE`.

From `INSPECTED`, a `QAOfficer` — and not the same `X-User-ID` that performed the inspect, on pain of `ERR_SOD_VIOLATION` (HTTP 403) — chooses one of three routes. Acceptance is available only when `nonconformance_reason` is `NONE`. Acceptance allocates a destination bin via the FEFO bin-allocation calculation described in §3.4, mints a new `Lot` row with `quantity_on_hand` equal to the receipt's `quantity_units`, `quantity_picked` of 0, `quality_status` of `RELEASED`, the `bin_id` set to the assigned bin, the `product_id`, `supplier_id`, `lot_number`, `expiry_minutes`, and `receipt_id` all copied from the receipt, the denormalised `warehouse_id` set to the parent warehouse, and `cumulative_excursion_minutes` of 0; sets the bin's `current_lot_id` to the new lot, the bin's `status` to `OCCUPIED`, raises `occupied_volume` by `quantity_units`, raises `occupied_weight_kg` by `quantity_units` multiplied by the product's `unit_weight_kg`, recomputes the parent zone's `utilization_units` as the sum of its bins' `occupied_volume`, generates the `acceptance_certificate_no` in the format `CERT-{warehouse.code}-{seq:06d}` where the sequence is a six-digit zero-padded monotonic counter per warehouse, fixes the receipt's `assigned_bin_id` and `status` of `ACCEPTED`, appends one `ExternalSyncEvent` to the `REGULATORY_AUTHORITY` target and a second to the `GSP_REPORT` target, both carrying `event_type` of `INBOUND_ACCEPTED`, and writes an `AuditLogEntry` with `action` of `RECEIPT_ACCEPT`.

Routing the receipt to quarantine is the corresponding decision when `nonconformance_reason` is anything other than `NONE`. The system allocates a bin in a `QUARANTINE`-type zone of the same warehouse, mints a `Lot` whose `quality_status` is `QUARANTINED` and whose `bin_id` points at the quarantine bin, appends one `ExternalSyncEvent` targeted at `REGULATORY_AUTHORITY` with `event_type` `INBOUND_QUARANTINED`, and writes an `AuditLogEntry` with `action` `RECEIPT_QUARANTINE`. The receipt's `status` becomes `QUARANTINED`.

From `QUARANTINED`, a `QAOfficer` whose `X-User-ID` differs from the officer who originally performed the quarantine transition (again on pain of `ERR_SOD_VIOLATION`) may release the receipt back to `ACCEPTED`, but only when the `nonconformance_reason` is `VISUAL_FAIL` or `TEMP_EXCURSION` — the unqualified-supplier, unqualified-product, and expired-on-arrival paths are not releasable. The release-from-quarantine path re-runs the FEFO bin allocation, updates the lot's `quality_status` to `RELEASED` and `bin_id` to the new bin, clears the quarantine bin's `current_lot_id`, generates a fresh `acceptance_certificate_no`, and writes an `AuditLogEntry` with `action` `RECEIPT_RELEASE_FROM_QUARANTINE`. From either `INSPECTED` (when `nonconformance_reason` is `UNQUALIFIED_SUPPLIER`, `UNQUALIFIED_PRODUCT`, or `EXPIRED_ON_ARRIVAL`) or `QUARANTINED`, a `QAOfficer` may reject the receipt outright: the receipt enters the terminal `REJECTED` state, any quarantine-held lot has its `quality_status` set to `REJECTED` and its bin's `current_lot_id` cleared, and an `AuditLogEntry` with `action` `RECEIPT_REJECT` is written.

The acceptance-time safety checks are tightly interrelated and use category-specific error codes. The supplier check fails with `ERR_UNQUALIFIED_SUPPLIER` (HTTP 422) when the supplier's `qualified` is false or `qualification_expiry_minutes` is less than or equal to `clock_minutes`; the product check fails with `ERR_UNQUALIFIED_PRODUCT` (HTTP 422) when the product's `qualified` is false; the lot-expiry check fails with `ERR_EXPIRED_LOT` (HTTP 422) when the lot's `expiry_minutes` is less than or equal to `clock_minutes` plus 1 (so a lot that expires this minute or the next is not acceptable). All three errors apply to acceptance only — the same conditions on `INSPECTED` are surfaced as `nonconformance_reason` rather than as request-time errors, which is what routes the receipt to quarantine or reject instead.

### 3.3. Temperature Monitoring, Deviation Lifecycle, and Stock Isolation

A `WarehouseAdmin` (acting as the data-ingestion role for sensor hardware) records temperature events one at a time against a zone, supplying the reading's `at_minutes` and its `temp_c`. The system rejects the reading with `ERR_TEMP_EVENT_TIME_INVALID` (HTTP 422) unless `at_minutes` is at least `clock_minutes` minus 1 and at most `clock_minutes` — that is, the event must have been recorded in the current logical minute or the immediately preceding one. The system then classifies the reading by comparing `temp_c` against the zone's thresholds: a reading inside `[target_temp_low_c, target_temp_high_c]` (inclusive) is classified `IN_RANGE`; a reading at or below `alarm_low_c` is `ALARM_LOW`; a reading at or above `alarm_high_c` is `ALARM_HIGH`; a reading strictly between `target_temp_low_c` and `alarm_low_c` (i.e. below target but above hard alarm) is `WARNING_LOW`; a reading strictly between `target_temp_high_c` and `alarm_high_c` is `WARNING_HIGH`. The classification is persisted as `kind` and the zone's `last_sensor_reading_c` is refreshed.

An out-of-range event (any classification other than `IN_RANGE`) is aggregated into a `Deviation` row. The temperature event row itself records the originating `zone_id` and a denormalised `warehouse_id`, both copied from the URL-bound zone. If no deviation is currently open on the zone, a new `Deviation` is created with its own `zone_id` and denormalised `warehouse_id` set to the same zone, `started_at_minutes` set to the event's `at_minutes`, `status` `OPEN`, and `qa_decision` `PENDING`; if one is already open, the event joins it, and `deviation_id` on the event row records the linkage. The deviation's `max_magnitude_c` is the maximum absolute deviation from the nearest crossed zone bound across all its events, rounded half-up to two decimal places. When a follow-up `IN_RANGE` reading arrives, the open deviation transitions to `CLOSED_PENDING_QA`: `ended_at_minutes` is set to the previous out-of-range event's `at_minutes`, `duration_minutes` is computed as `ended_at_minutes` minus `started_at_minutes` plus 1, and `classification` is pinned by the deviation-classification calculation described below. At the same moment, every lot whose `bin_id` lies in the affected zone has its `cumulative_excursion_minutes` raised by the deviation's `duration_minutes`, and every such lot whose `quality_status` was `RELEASED` is moved to `QUARANTINED`. The cascade extends to outbound shipments: every shipment in `PACKED` whose `pick_lot_id` has just been quarantined is itself moved to `QUARANTINED` to freeze it pending QA. One `ExternalSyncEvent` targeted at `REGULATORY_AUTHORITY` with `event_type` `DEVIATION_CLOSED` is appended, alongside an `AuditLogEntry` with `action` `DEVIATION_CLOSE`.

Classification of a closed deviation uses the deviation's `max_magnitude_c` (in Celsius) and its `duration_minutes` (an integer). The system applies an inclusive-tier cascade in order from most severe to least: if `duration_minutes` is at least 240 minutes (4 hours), or if `max_magnitude_c` is at least 5.0, the deviation is `CRITICAL`; otherwise, if `duration_minutes` is at least 60 minutes, or if `max_magnitude_c` is at least 2.0, the deviation is `MAJOR`; otherwise the deviation is `MINOR`. The first matching tier wins, so a deviation lasting 5 hours at a magnitude of 1 Celsius still classifies as `CRITICAL`.

A `QAOfficer` then assesses the closed deviation, supplying `qa_decision` of `RELEASE`, `QUARANTINE`, or `REJECT`, and — when the classification is `MAJOR` or `CRITICAL` and `qa_decision` is `RELEASE` — a `capa_id` referencing an `OPEN` corrective-and-preventive-action row. Assessment is rejected with `ERR_DEVIATION_STATE_INVALID` (HTTP 409) unless the deviation is currently in `CLOSED_PENDING_QA`. On a valid assess, each affected lot's `quality_status` is set according to the decision (`RELEASE` becomes `RELEASED`, `QUARANTINE` becomes `QUARANTINED`, `REJECT` becomes `REJECTED`); if the classification is `MAJOR` or `CRITICAL`, the system opens a new `CAPA` row whose `due_minutes` is the deviation's closure `clock_minutes` plus 720 minutes (12 hours) when the classification is `CRITICAL`, or that closure plus 4320 minutes (72 hours) when the classification is `MAJOR`. The deviation moves to `CLOSED_ASSESSED` and an `AuditLogEntry` with `action` `DEVIATION_ASSESS` is written. CAPAs carry an originating `deviation_id` or `recall_id` (exactly one is populated) and progress through `OPEN`, `IN_PROGRESS`, `COMPLETED`, or `OVERDUE`. Completion via the dedicated capability moves a CAPA to `COMPLETED`; the sweep capability described in §2.7 flips any CAPA whose `due_minutes` is strictly less than `clock_minutes` to `OVERDUE`. The `CAPA_OVERDUE` value is one of the `event_type` enums available on the `ExternalSyncEvent` stream for downstream consumers that subscribe to overdue notifications.

Zone posture is driven entirely by deviation state. When an `ALARM_LOW` or `ALARM_HIGH` reading is classified, the zone's `current_posture` immediately becomes `FROZEN` and every child bin's `status` flips to `LOCKED`; if no deviation was currently open for the zone, a new one opens. A `WARNING_*`-only deviation moves the zone to `RESTRICTED` rather than `FROZEN`, allowing picks against already-released lots to continue while blocking new acceptance allocations. A subsequent alarm reading on a zone already in `RESTRICTED` escalates it to `FROZEN`. When every deviation on the zone reaches `CLOSED_ASSESSED`, the zone's `current_posture` returns to `OPEN`; bins that were `LOCKED` revert to `AVAILABLE` if their `current_lot_id` is null and to `OCCUPIED` otherwise. Any attempt to accept (whether direct accept or release-from-quarantine) or to pick on bins whose parent zone is currently `FROZEN` is rejected with `ERR_ZONE_FROZEN` (HTTP 409); the same error guards the three operations identically.

### 3.4. FEFO Bin Allocation on Acceptance

When an acceptance (whether direct or via release-from-quarantine) needs to choose a destination bin, the system runs the FEFO bin-allocation calculation. The candidate set is every bin in the warehouse whose `status` is `AVAILABLE`, whose parent zone's `zone_type` equals the product's `required_zone_type`, whose parent zone's `current_posture` is `OPEN`, whose `special_storage_tag` exactly matches the product's `special_storage_tag` (a `NARCOTIC`, `PSYCHOTROPIC`, `BIOLOGICAL`, or `VACCINE` product must land in a bin tagged the same way, and a `NONE` product must land in a `NONE` bin — any other pairing is a `ERR_SEGREGATION_VIOLATION` at HTTP 422), whose `volume_units` is at least the receipt's `quantity_units`, and whose `weight_limit_kg` is at least the receipt's `quantity_units` multiplied by the product's `unit_weight_kg` (a per-bin capacity miss surfaces as `ERR_BIN_CAPACITY_EXCEEDED` at HTTP 422). The candidates are then ordered by a three-key sort: first ascending by the zone-earliest-neighbour expiry, defined as the smallest `expiry_minutes` of any lot already stored anywhere in the candidate's parent zone (or treated as plus-infinity when that zone holds no lots, sending empty zones to the back of the queue); then ascending lexicographically by the zone's `code`; then ascending lexicographically by the bin's `code`. The first candidate after this sort is the chosen bin. If the candidate set is empty after filtering, the request fails with `ERR_NO_ELIGIBLE_BIN` (HTTP 422). An additional zone-level capacity ceiling enforces that the zone's current `utilization_units` plus the receipt's `quantity_units` does not exceed the zone's `capacity_units`; exceeding the ceiling surfaces as `ERR_ZONE_CAPACITY_EXCEEDED` (HTTP 422).

### 3.5. Outbound Shipments, FEFO Picking, and Packaging Pre-Checks

A `Picker` creates an outbound shipment against a warehouse, supplying the downstream `customer_id` (a free-form string identifier — customers are not managed entities of this service), the `product_id`, the requested `quantity_units`, the cold-chain `packaging_kind` selected from `INSULATED_PCM`, `INSULATED_DRY_ICE`, or `AMBIENT`, the recorded packing-bay temperature `pick_temp_c`, and the courier vehicle's pre-conditioning reading `vehicle_precondition_temp_c`. A zero or negative `quantity_units` is rejected on creation with `ERR_QUANTITY_INVALID` (HTTP 422). The shipment is born in `PLANNED` with a null `pick_lot_id`, a null `dispatched_at_minutes`, and `logger_armed` of false.

Picking moves the shipment from `PLANNED` to `PICKED`. The FEFO pick-selection calculation walks every lot in the warehouse whose `product_id` matches the shipment's, whose `quality_status` is `RELEASED`, whose `expiry_minutes` is strictly greater than the warehouse's `clock_minutes`, and whose `quantity_on_hand` is at least the shipment's `quantity_units`. The candidates are sorted by three ascending keys: `expiry_minutes` first (earliest expiry wins, which is the FEFO discipline), then `created_at`, then `id`. The first candidate is the picked lot, recorded as `pick_lot_id`. If no candidate exists, the request fails with `ERR_NO_FEFO_LOT` (HTTP 422); attempting to override the selection with a non-FEFO-earliest lot is rejected with `ERR_FEFO_VIOLATION` (HTTP 422). When stock runs short at pick time — the chosen lot's `quantity_on_hand` is less than the shipment's `quantity_units` — the request fails with `ERR_INSUFFICIENT_STOCK` (HTTP 409). On success, the chosen lot's `quantity_on_hand` is decremented by the shipment's `quantity_units` and its `quantity_picked` is incremented by the same amount; the bin's `occupied_volume` and `occupied_weight_kg` are recomputed (with `occupied_weight_kg` reduced by `quantity_units` multiplied by the product's `unit_weight_kg`), the bin's `status` flips to `AVAILABLE` if `occupied_volume` reaches 0, and the parent zone's `utilization_units` is rolled up.

Packing moves the shipment from `PICKED` to `PACKED` after two temperature pre-checks and one packaging-match check. The packaging-match rule binds packaging selection to the product's required zone type: a product in `FROZEN` must ship in `INSULATED_DRY_ICE`; products in `REFRIGERATED`, `COOL`, or `CONTROLLED_TEMP` must ship in `INSULATED_PCM`; products in `ROOM_TEMP` must ship `AMBIENT`. Any mismatch is rejected with `ERR_PACKAGING_MISMATCH` (HTTP 422). The temperature pre-checks require that both `pick_temp_c` and `vehicle_precondition_temp_c` lie within the product's required operating range (the same `[target_temp_low_c, target_temp_high_c]` band of the matching `zone_type`); a violation in either reading surfaces as `ERR_TEMP_PRECHECK_FAIL` (HTTP 422). The same temperature pre-checks are re-evaluated at dispatch, which moves the shipment from `PACKED` to `DISPATCHED`, sets `logger_armed` to true, sets `dispatched_at_minutes` to the current `clock_minutes`, appends one `ExternalSyncEvent` targeted at `TMS` with `event_type` `SHIPMENT_DISPATCHED`, and writes an `AuditLogEntry` with `action` `SHIPMENT_DISPATCH`. A shipment held in `PACKED` may be quarantined as a system cascade when a deviation on the zone that previously held its lot closes (as described in §3.3); a `QAOfficer` may then release the shipment back to `PACKED` provided the linked deviation's `qa_decision` is `RELEASE`, writing an `AuditLogEntry` with `action` `SHIPMENT_QA_RELEASE`.

A shipment may be cancelled by a `Picker` from `PLANNED` (no stock side effects, since no pick has occurred) or from `PICKED` (the previously decremented stock is restored — the picked lot's `quantity_on_hand` rises by the shipment's `quantity_units` and `quantity_picked` falls by the same amount, with bin and zone utilisation recomputed). A request to drive a shipment through a transition that does not match its current `status` is rejected with `ERR_SHIPMENT_STATE_INVALID` (HTTP 409). The compensating cancel preserves an invariant that holds at all times for every lot: the lot's `quantity_on_hand` plus its `quantity_picked` is always equal to the original receipt's `quantity_units` that minted the lot.

### 3.6. Shipment Summary Cost Calculation

A computed-read summary on each shipment returns the shipment's outbound total in integer cents using a three-component tiered model. The base packaging cost is fixed by the product's `required_zone_type`: 5000 cents for `FROZEN`, 3000 cents for `REFRIGERATED`, 1500 cents for `COOL`, 500 cents for `ROOM_TEMP`, and 4000 cents for `CONTROLLED_TEMP`. A packaging-kind surcharge is added on top. When the `packaging_kind` is `INSULATED_DRY_ICE`, the surcharge is the greater of 2000 cents and 100 cents multiplied by the shipment's `quantity_units` — that is, a floor of 2000 cents and a per-unit rate of 100 cents. When the `packaging_kind` is `INSULATED_PCM`, the surcharge is the smaller of 3000 cents and 50 cents multiplied by the shipment's `quantity_units` — that is, a cap of 3000 cents and a per-unit rate of 50 cents. When the `packaging_kind` is `AMBIENT`, the surcharge is 0. A special-handling premium of 1000 cents is added when the product's `special_storage_tag` is any of `NARCOTIC`, `PSYCHOTROPIC`, `BIOLOGICAL`, or `VACCINE`; otherwise the premium is 0.

The three components are evaluated independently. Each component is rounded half-up to whole cents in isolation, and the three rounded components are then summed to produce the final total (per-line rounding, not aggregate rounding — the order is fixed because a future per-unit fee would diverge under aggregate rounding).

### 3.7. Recall Lifecycle

A `RecallOfficer` opens a recall against a warehouse with a payload containing a `classification` of `CLASS_I`, `CLASS_II`, or `CLASS_III` and a free-text `reason`. The recall is born in `DRAFT` with a null `initiated_at_minutes`, a null `report_due_minutes`, a null `notifications_required`, a `notifications_sent` of 0, a null `returns_expected_units`, a `returns_received_units` of 0, and a null `effectiveness_pass`. Scope entries are added one at a time, each carrying the `lot_id` to include, an optional `shipment_id` (present for stock that has already been shipped, absent for on-hand stock), the `units` quantity, and a `scope_kind` of `ON_HAND` or `SHIPPED`. The `recall_id` and `created_at` on each scope entry are server-assigned and the entries are append-only with no `updated_at` or `version`.

Announcing the recall moves it from `DRAFT` to `ANNOUNCED`. Announcement requires at least one `RecallScopeEntry` (the empty-scope failure surfaces as `ERR_RECALL_SCOPE_EMPTY` at HTTP 422), and the acting `RecallOfficer`'s `X-User-ID` must differ from the `QAOfficer` `X-User-ID` that performed the most recent deviation assessment on any in-scope lot (a segregation-of-duties violation surfaces as `ERR_SOD_VIOLATION` at HTTP 403). On valid announce, `initiated_at_minutes` is set to the warehouse's current `clock_minutes`; the regulatory `report_due_minutes` is computed as `initiated_at_minutes` plus a class-specific offset — 1440 minutes (24 hours) for `CLASS_I`, 4320 minutes (72 hours) for `CLASS_II`, or 14400 minutes (240 hours, equivalently 10 days) for `CLASS_III`. A sanity check requires that `report_due_minutes` is strictly greater than `initiated_at_minutes`; a violation surfaces as `ERR_RECALL_DEADLINE_INVALID` (HTTP 422). Every in-scope lot's `quality_status` is set to `RECALLED` as a cascade, and `notifications_required` is computed as the count of distinct `customer_id` values appearing in scope entries whose `scope_kind` is `SHIPPED`. Two `ExternalSyncEvent` rows are appended — one targeted at `REGULATORY_AUTHORITY` and one at `PHARMACOVIGILANCE`, both carrying `event_type` `RECALL_ANNOUNCED` — and an `AuditLogEntry` with `action` `RECALL_ANNOUNCE` is written.

From `ANNOUNCED`, the officer dispatches customer notifications one at a time, each call incrementing `notifications_sent` by 1. The recall remains in `ANNOUNCED` until `notifications_sent` reaches `notifications_required`, at which point it auto-advances to `RETURNS_IN_PROGRESS`. Notification calls beyond the required count are rejected. Returns are recorded one entry at a time, each call supplying the `scope_entry_id` of an existing `SHIPPED` scope entry attached to this recall, plus the returned `units`. A return targeting a non-existent, wrong-recall, or `ON_HAND` scope entry is rejected with `ERR_RETURN_SCOPE_INVALID` (HTTP 422). Each valid return increments `returns_received_units` by the supplied `units` and physically moves those units into a `QUARANTINE`-zone bin in the warehouse (raising the bin's `occupied_volume` and rolling up the parent zone's `utilization_units`). The recall auto-advances from `RETURNS_IN_PROGRESS` to `EFFECTIVENESS_CHECK` when `returns_received_units` reaches `returns_expected_units` (the sum of `units` across all `SHIPPED` scope entries), or when the warehouse's `clock_minutes` reaches `report_due_minutes`, whichever comes first.

Closing the recall is the `RecallOfficer`'s final act and requires that the effectiveness calculation has been performed. The authoritative effectiveness ratio is `returns_received_units` divided by `returns_expected_units` (where a zero denominator yields a ratio of 0), rounded half-up to four decimal places. The recall's `effectiveness_pass` is true if and only if the rounded ratio is at least 0.80; the denominator includes only `SHIPPED` scope entries — `ON_HAND` units are excluded. When `effectiveness_pass` is false, the system opens a new `CAPA` whose `due_minutes` is the current `clock_minutes` plus 4320 minutes (72 hours). Closing additionally appends one `ExternalSyncEvent` targeted at `REGULATORY_AUTHORITY` with `event_type` `RECALL_CLOSED` and writes an `AuditLogEntry` with `action` `RECALL_CLOSE`; the recall moves to the terminal `CLOSED` state. A read-only preview capability is also available before close and uses a provisional projection variant of the same calculation: it adds to `returns_received_units` a credit equal to the count of notified-but-not-yet-returned customers (with a per-notification credit of 1.0 unit), divides by `returns_expected_units`, and reports a projected pass against the same 0.80 threshold. The preview's projected ratio diverges from the authoritative ratio whenever `notifications_sent` outpaces actual returns; the preview never mutates state.

### 3.8. Audit and External-Event Log Inspection

The append-only `AuditLogEntry` log and the append-only `ExternalSyncEvent` log are both readable through dedicated list capabilities scoped to a warehouse. The audit list accepts filters `filter[action]` and `filter[actor_role]`; the external-events list accepts `filter[target_system]` and `filter[event_type]`. Both lists honour the standard `limit` and `offset` pagination contract from §2.3, return rows in ascending `created_at` order, and are visible to the `WarehouseAdmin`, `QAOfficer`, and `RecallOfficer` roles. Receipt, shipment, deviation, CAPA, and recall list endpoints similarly accept their respective status and classification filters: receipts accept `filter[status]`, shipments accept `filter[status]`, deviations accept `filter[status]` and `filter[classification]`, CAPAs accept `filter[status]`, recalls accept `filter[status]` and `filter[classification]`, lots accept `filter[product_id]` and `filter[quality_status]`, temperature-event lists accept `filter[kind]`.

## 4. Endpoint Definitions

A creation endpoint that mints a brand-new resource returns HTTP 201; every other successful endpoint returns HTTP 200. State-changing endpoints accept an optional `version` in the request body for optimistic concurrency control; full request semantics, side-effects, and validation triggers are described in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/warehouses` | Create warehouse | `WarehouseAdmin` |
| GET | `/warehouses` | List warehouses | `WarehouseAdmin`, `Receiver`, `QAOfficer`, `Picker`, `RecallOfficer` |
| GET | `/warehouses/{wid}` | Get warehouse | `WarehouseAdmin`, `Receiver`, `QAOfficer`, `Picker`, `RecallOfficer` |
| POST | `/warehouses/{wid}/zones` | Create zone | `WarehouseAdmin` |
| GET | `/warehouses/{wid}/zones` | List zones (filter by `zone_type`, `current_posture`) | `WarehouseAdmin`, `Receiver`, `QAOfficer`, `Picker`, `RecallOfficer` |
| GET | `/zones/{id}` | Get zone (with posture and utilisation) | `WarehouseAdmin`, `Receiver`, `QAOfficer`, `Picker`, `RecallOfficer` |
| POST | `/zones/{zid}/bins` | Create bin | `WarehouseAdmin` |
| GET | `/zones/{zid}/bins` | List bins in zone (filter by `status`) | `WarehouseAdmin`, `Receiver`, `QAOfficer`, `Picker`, `RecallOfficer` |
| POST | `/suppliers` | Register supplier | `WarehouseAdmin` |
| GET | `/suppliers/{id}` | Get supplier | `WarehouseAdmin`, `Receiver`, `QAOfficer` |
| POST | `/products` | Register product | `WarehouseAdmin` |
| GET | `/products/{id}` | Get product | `WarehouseAdmin`, `Receiver`, `QAOfficer`, `Picker` |
| POST | `/warehouses/{wid}/receipts` | Create inbound receipt (initial `PENDING_INSPECTION`) | `Receiver` |
| GET | `/warehouses/{wid}/receipts` | List receipts (filter by `status`) | `Receiver`, `QAOfficer`, `WarehouseAdmin` |
| GET | `/receipts/{id}` | Get receipt | `Receiver`, `QAOfficer`, `WarehouseAdmin` |
| POST | `/receipts/{id}/inspect` | Receiver inspection — computes `temp_chain_intact` and `nonconformance_reason` | `Receiver` |
| POST | `/receipts/{id}/accept` | QA acceptance — mints lot, allocates bin, issues `acceptance_certificate_no` | `QAOfficer` |
| POST | `/receipts/{id}/quarantine` | QA route to quarantine zone | `QAOfficer` |
| POST | `/receipts/{id}/release-from-quarantine` | QA release of quarantined receipt back to accepted | `QAOfficer` |
| POST | `/receipts/{id}/reject` | QA reject (terminal) | `QAOfficer` |
| GET | `/warehouses/{wid}/lots` | List lots (filter by `product_id`, `quality_status`) | `Receiver`, `QAOfficer`, `Picker`, `RecallOfficer`, `WarehouseAdmin` |
| GET | `/lots/{id}` | Get lot | `Receiver`, `QAOfficer`, `Picker`, `RecallOfficer`, `WarehouseAdmin` |
| POST | `/warehouses/{wid}/shipments` | Create outbound shipment (initial `PLANNED`) | `Picker` |
| GET | `/warehouses/{wid}/shipments` | List shipments (filter by `status`) | `Picker`, `QAOfficer`, `RecallOfficer`, `WarehouseAdmin` |
| GET | `/shipments/{id}` | Get shipment | `Picker`, `QAOfficer`, `RecallOfficer`, `WarehouseAdmin` |
| GET | `/shipments/{id}/summary` | Computed shipment outbound total in cents | `Picker`, `WarehouseAdmin` |
| POST | `/shipments/{id}/pick` | FEFO pick — selects lot, decrements stock | `Picker` |
| POST | `/shipments/{id}/pack` | Pack — packaging-match and temperature pre-check | `Picker` |
| POST | `/shipments/{id}/dispatch` | Dispatch — arms logger | `Picker` |
| POST | `/shipments/{id}/qa-release` | Release a quarantined shipment back to packed | `QAOfficer` |
| POST | `/shipments/{id}/cancel` | Cancel shipment (compensates lot stock) | `Picker` |
| POST | `/zones/{id}/temperature-events` | Record sensor reading; classify, cascade deviation and posture | `WarehouseAdmin` |
| GET | `/zones/{id}/temperature-events` | List temperature events for zone (filter by `kind`) | `WarehouseAdmin`, `QAOfficer`, `RecallOfficer` |
| GET | `/warehouses/{wid}/deviations` | List deviations (filter by `status`, `classification`) | `QAOfficer`, `RecallOfficer`, `WarehouseAdmin` |
| GET | `/deviations/{id}` | Get deviation | `QAOfficer`, `RecallOfficer`, `WarehouseAdmin` |
| POST | `/deviations/{id}/assess` | QA decision (`RELEASE`/`QUARANTINE`/`REJECT`) on closed deviation | `QAOfficer` |
| GET | `/warehouses/{wid}/capas` | List CAPAs (filter by `status`) | `QAOfficer`, `RecallOfficer`, `WarehouseAdmin` |
| GET | `/capas/{id}` | Get CAPA | `QAOfficer`, `RecallOfficer`, `WarehouseAdmin` |
| POST | `/capas/{id}/complete` | Mark CAPA completed | `QAOfficer` |
| POST | `/warehouses/{wid}/recalls` | Create recall (initial `DRAFT`) | `RecallOfficer` |
| POST | `/recalls/{id}/scope` | Add a recall scope entry | `RecallOfficer` |
| POST | `/recalls/{id}/announce` | Announce recall — sets deadline, marks lots `RECALLED` | `RecallOfficer` |
| POST | `/recalls/{id}/notify-next-customer` | Send one customer notification | `RecallOfficer` |
| POST | `/recalls/{id}/record-return` | Record customer return into quarantine bin | `RecallOfficer` |
| POST | `/recalls/{id}/close` | Close after effectiveness check | `RecallOfficer` |
| GET | `/recalls/{id}` | Get recall | `RecallOfficer`, `QAOfficer`, `WarehouseAdmin` |
| GET | `/recalls/{id}/preview` | Provisional effectiveness projection | `RecallOfficer`, `QAOfficer` |
| GET | `/warehouses/{wid}/recalls` | List recalls (filter by `status`, `classification`) | `RecallOfficer`, `QAOfficer`, `WarehouseAdmin` |
| GET | `/warehouses/{wid}/external-events` | List external sync events (filter by `target_system`, `event_type`) | `WarehouseAdmin`, `RecallOfficer`, `QAOfficer` |
| GET | `/warehouses/{wid}/audit-log` | List audit-log entries (filter by `action`, `actor_role`) | `WarehouseAdmin`, `QAOfficer`, `RecallOfficer` |
| POST | `/warehouses/{wid}/_clock/advance` | Advance deterministic clock by `minutes`; trigger scheduled cascades | `WarehouseAdmin` |
| POST | `/warehouses/{wid}/_sweep/run` | Idempotent sweep: overdue CAPAs, recall deadlines, zone postures | `WarehouseAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_MISSING_ROLE` | 401 |
| `ERR_AUTH_MISSING_USER` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_RECEIPT_NOT_PENDING` | 409 |
| `ERR_RECEIPT_NOT_INSPECTED` | 409 |
| `ERR_RECEIPT_NOT_QUARANTINED` | 409 |
| `ERR_SHIPMENT_STATE_INVALID` | 409 |
| `ERR_RECALL_NOT_DRAFT` | 409 |
| `ERR_RECALL_STATE_INVALID` | 409 |
| `ERR_DEVIATION_STATE_INVALID` | 409 |
| `ERR_CAPA_STATE_INVALID` | 409 |
| `ERR_BIN_UNAVAILABLE` | 409 |
| `ERR_ZONE_FROZEN` | 409 |
| `ERR_UNQUALIFIED_SUPPLIER` | 422 |
| `ERR_UNQUALIFIED_PRODUCT` | 422 |
| `ERR_EXPIRED_LOT` | 422 |
| `ERR_TEMP_PRECHECK_FAIL` | 422 |
| `ERR_LOGGER_DATA_INVALID` | 422 |
| `ERR_PACKAGING_MISMATCH` | 422 |
| `ERR_SEGREGATION_VIOLATION` | 422 |
| `ERR_FEFO_VIOLATION` | 422 |
| `ERR_NO_FEFO_LOT` | 422 |
| `ERR_NO_ELIGIBLE_BIN` | 422 |
| `ERR_BIN_CAPACITY_EXCEEDED` | 422 |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 422 |
| `ERR_QUANTITY_INVALID` | 422 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_RECALL_SCOPE_EMPTY` | 422 |
| `ERR_RETURN_SCOPE_INVALID` | 422 |
| `ERR_TEMP_EVENT_TIME_INVALID` | 422 |
| `ERR_RECALL_DEADLINE_INVALID` | 422 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_VALIDATION_FAILED` | 422 |
