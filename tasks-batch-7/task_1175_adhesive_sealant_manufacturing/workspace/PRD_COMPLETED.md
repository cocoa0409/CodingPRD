# Adhesive & Sealant Manufacturing API — Product Requirements Document

## 1. Introduction

Adhesive and sealant manufacturing sits at an uncomfortable intersection of chemistry and commerce. A batch of reactive resin begins gelation the moment mixing completes, moisture in the air can ruin an entire packaging shift for a silicone or polyurethane formulation, and a lot cannot legally ship until a laboratory has demonstrated that its bond strength meets the published specification. Once product leaves the plant, the commercial side takes over: hazmat regulations classify the shipment based on solvent content and flash point, distributors hold consigned stock under credit-limited agreements, and monthly consumption reports must be settled with tiered rebates that depend on the gross value of what was actually consumed.

This document specifies a manufacturing execution and consignment commerce API that models the full chain — from the moment a mixer is booked against a vessel, through moisture-controlled packaging and quality-assurance lot release, to shipment planning under hazardous-goods rules and the monthly settlement of consigned consumption. The system is built around two intertwined concerns: **temporal windows** (pot life, mix windows, packaging windows, shelf life) which the server enforces through a logical clock, and **segregation of duties** (the technician who records a cure test may never be the manager who releases the lot). Every mutation that matters carries a durable audit trail through versioned resources and an explicit optimistic-concurrency protocol on the consignment side, so that commercial terms are never silently overwritten.

The audience is the engineer implementing the service. The document deliberately separates the global mechanical contract (§2) from the business narrative (§3) so that the structural rules of the wire protocol are stated once, while the workflow logic is told as a story of batches, runs, lots, tests, shipments, and settlements.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under the `/api` path prefix; all endpoint paths in §4 are expressed relative to that mount.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which that user is acting. A request in which either header is absent, or in which the declared role is not one of the recognized roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are validated, the role is checked against the operation's authorization; an attempt to perform an action outside the role's designated scope is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes nine roles, spelled exactly as follows: `PlatformAdmin`, `PlantManager`, `BatchOperator`, `QATechnician`, `QAManager`, `TechServiceEngineer`, `CommercialManager`, `LogisticsCoordinator`, and `Distributor`.

For eight of these roles — `PlatformAdmin`, `PlantManager`, `BatchOperator`, `QATechnician`, `QAManager`, `TechServiceEngineer`, `CommercialManager`, and `LogisticsCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `released_by` on a `ProductionLot` when a `QAManager` releases the lot, or as `technician_id` on a `CureTest` recorded by a `QATechnician`) but does not compare it to any entity's `id`.

For the `Distributor` role, `X-User-ID` is the `id` of the acting `Distributor` record; ownership checks on any resource that references a `Distributor` compare the resource's foreign-key field to `X-User-ID`. In practice this means a `Distributor` may only submit a `FormulationRequest` whose `distributor_id` equals their own `X-User-ID`, may only call `respond` on a request whose `distributor_id` matches, may only create or submit or revise `ConsumptionReport`s against agreements whose owning `Distributor`'s `id` matches, and sees only its own rows when listing formulation requests. Any cross-account access is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

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
- The same envelope is produced for requests that match no defined route (`ERR_NOT_FOUND`, HTTP 404) and for a defined route called with an unsupported HTTP method (`ERR_INVALID_REQUEST`, HTTP 405).

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum allowed value of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; resources that share a `created_at` millisecond are ordered by creation sequence. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every primary resource in this API — `Formulation`, `MixingVessel`, `DryRoom`, `ProductionBatch`, `PackagingRun`, `ProductionLot`, `CureTest`, `FormulationRequest`, `Distributor`, `ConsignmentAgreement`, `ConsignmentStock`, `ConsumptionReport`, and `Shipment` — carries a standard set of system-managed fields:

- **`id`** (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- **`version`** (integer): a system-managed integer that starts at 1 and increments by exactly 1 on every mutation, including state transitions and any cascade-driven update to a derived counter.

The `MoistureExposureEvent` entity is the single exception: it is an append-only log record and carries only `id` and `created_at` — both `updated_at` and `version` are absent on this resource.

Two write operations on the consignment side are guarded by optimistic concurrency control, and both name the same field. A `POST /api/consignment-agreements/{agreementId}/consumption-reports` request must carry `expected_agreement_version` matching the target agreement's current `version`. A `PATCH /api/consignment-agreements/{agreementId}` request must likewise carry `expected_agreement_version`. In both cases, if the value supplied by the client does not match the agreement's current `version` — for instance because the client last read the agreement before another writer advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; supplying one elsewhere has no effect and is not required.

### 2.5. Validation Order

Every write request is screened by an ordered validation pipeline, and the order matters because several failures can co-exist on one request. The pipeline evaluates the following categories in this exact sequence:

1. **User-context presence.** `X-User-ID` and `X-User-Role` must be present and the role must be a declared role; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role permission.** The role must be permitted for the operation; otherwise `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). `Distributor`-role ownership is *not* decided at this step, with one exception: on `POST /api/formulation-requests` a body-supplied `distributor_id` that differs from the caller's `X-User-ID` is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403) before the body-schema checks of step 3.
3. **Request-body schema.** Required fields must be present, types and enum members must be valid, `mix_end_at` must be strictly after `mix_start_at`, `planned_end_at` must be at or after `planned_start_at`, integers flagged as positive must be positive, a `QUICK` cure test must carry exactly 1 specimen and a `FULL` cure test exactly 5, a consumption report's `period` must match `YYYY-MM` with a valid month, and `agreement_id` must be present on a shipment exactly when `shipment_kind` is `CONSIGNMENT` or `CONSIGNMENT_REPLENISHMENT` and must be absent for `SALE`. The fields flagged as positive (minimum 1) are `capacity_liters`, `max_concurrent_runs`, `batch_volume_ml`, `unit_volume_ml`, `planned_units`, shipment-line `units`, `consumed_units`, and stock-return `units`; `credit_limit_cents`, `unit_price_cents`, `max_consigned_value_cents`, `reorder_threshold_units`, `reorder_qty_units`, `pot_life_minutes`, `shelf_life_months`, `min_remaining_shelf_life_days`, `exposure_minutes`, and `expected_agreement_version` are non-negative (minimum 0). Violations surface as `ERR_INVALID_REQUEST` (HTTP 400).
4. **Existence and ownership.** Path identifiers are validated left to right, then foreign-key identifiers in the request body; any miss returns `ERR_NOT_FOUND` (HTTP 404). Once the targeted resource has been resolved, ownership for `Distributor`-role writes is verified against `X-User-ID` — a cross-account target is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403), ahead of any state, temporal, constraint, or referential check.
5. **State preconditions.** Transition from-states and cross-entity state gates (for example `ERR_BATCH_INVALID_STATE`, `ERR_FORMULATION_NOT_EFFECTIVE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_LOT_NOT_SHIPPABLE`, `ERR_LOT_ON_HOLD`, `ERR_SHIPMENT_BLOCKED_LINES`) are enforced; violations carry HTTP 409. The optimistic-concurrency check (`ERR_STALE_VERSION`, HTTP 412) runs immediately after the state preconditions on consumption-report creation, and immediately after existence on the agreement patch, which is itself not state-gated.
6. **Safety.** The moisture-packaging protocol (`ERR_MOISTURE_PROTOCOL_VIOLATION`), the hazmat transport-mode gate (`ERR_HAZMAT_MODE_FORBIDDEN`), and segregation of duties on lot release/reject (`ERR_SEGREGATION_OF_DUTIES`) are checked here, before any temporal check; violations carry HTTP 422 except `ERR_SEGREGATION_OF_DUTIES`, which is HTTP 403.
7. **Temporal.** Pot life at packaging-run create and complete (`ERR_POT_LIFE_EXCEEDED`, HTTP 422) and minimum remaining shelf life per shipment line at confirm (`ERR_MIN_SHELF_LIFE_VIOLATION`, HTTP 422) are enforced after the safety checks.
8. **Constraint.** Vessel half-open window overlap (`ERR_VESSEL_TIME_OVERLAP`), vessel capacity (`ERR_VESSEL_CAPACITY_EXCEEDED`), dry-room closed-interval aggregate capacity (`ERR_DRY_ROOM_CAPACITY_EXCEEDED`), pack-format and unit-volume consistency within a batch (`ERR_PACK_FORMAT_MISMATCH`), duplicate lot line (`ERR_DUPLICATE_LOT_LINE`), strict FIFO (`ERR_FIFO_VIOLATION`), retest limit (`ERR_RETEST_LIMIT_EXCEEDED`), and one non-`VOID` report per agreement-period (`ERR_REPORT_PERIOD_DUPLICATE`) — these sit in the 409 family except `ERR_VESSEL_CAPACITY_EXCEEDED`, which is HTTP 422.
9. **Referential sufficiency.** Batch volume sufficiency at run complete (`ERR_INSUFFICIENT_BATCH_VOLUME`), lot availability at line add (`ERR_INSUFFICIENT_LOT_STOCK`), consumption not exceeding on-hand (`ERR_STOCK_NEGATIVE`, applied atomically), returns not exceeding on-hand (`ERR_RETURN_EXCEEDS_ON_HAND`), and the close guards (`ERR_AGREEMENT_HAS_OPEN_REPORTS`, `ERR_CONSIGNMENT_STOCK_REMAINING`) — mostly HTTP 422, with the close guards and lot-stock check at 409.
10. **Fiscal.** The credit limit at agreement activate or resume (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402).

### 2.6. The Logical Clock and Lazy Pot-Life Enforcement

Time in this system is driven by a logical clock, not the host wall clock. At service startup the clock reads exactly `2026-05-01T00:00:00Z`, and it never silently falls back to wall-clock time. The logical clock governs business time only — `mixed_at`, `pot_life_deadline`, lot dating, ship-date arithmetic, and the sweep described below; audit timestamps (`created_at`, `updated_at`, and `meta.api_request_timestamp`) are generated separately at write time. The clock is advanced only through an admin-only test-driving capability, restricted to `PlatformAdmin`, which sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`.

Advancing the clock triggers one specific sweep: every `ProductionBatch` still in `MIXING` whose `mix_end_at` now lies strictly before the current clock reading is transitioned to `EXPIRED`, and each such batch's `ProductionLot` — if its `qa_status` is still `AWAITING_TEST`, `TESTING`, or `UNDER_REVIEW` — is moved to `REJECTED`. Released lots are unaffected by this sweep.

Pot-life expiry for batches that have already completed mixing is deliberately **not** part of the clock sweep. Instead, pot life is enforced lazily, on-touch: whenever a packaging run is created against a `MIXED` or `PACKING` batch, or an `OPEN` run is completed, or a batch is voided, the server compares the current clock to the batch's `pot_life_deadline`. If the deadline has passed, the batch expiry cascade fires (see §3.4) and the triggering call fails with `ERR_POT_LIFE_EXCEEDED`. The batch is usable while elapsed time since `mixed_at` is less than or equal to the formulation's `pot_life_minutes` — the boundary is inclusive. A consequence is that a `MIXING` batch whose mix window has already ended is caught at complete-mix time by the state precondition (the batch is by then `EXPIRED`), so there is no separate "mix window exceeded" error code.

### 2.7. Cascading State Propagation

Several operations mutate more than one resource at a time, and the PRD describes every cascade hop at its natural home in §3. Three cascades deserve advance notice because they cross section boundaries.

First, the **batch expiry / void cascade**: when a batch reaches `EXPIRED` or `VOID`, every `OPEN` or `HOLD` packaging run of the batch is moved to `VOID`, and a lot still in `AWAITING_TEST`, `TESTING`, or `UNDER_REVIEW` is moved to `REJECTED`. Second, the **moisture exposure cascade**: logging an exposure event with `exposure_minutes` of at least 30 on an `OPEN` or `SEALED` run moves the run to `HOLD`; on a `SEALED` run this additionally quarantines its produced units on the lot, sets the lot's `hold_status` to `QUARANTINE_HOLD`, and forces every `PLANNED` or `CONFIRMED` shipment containing a line for that lot into `EXCEPTION`. Third, the **report-revision compensation**: when a disputed `ConsumptionReport` is cycled back to `DRAFT`, the stock waterfall applied at submit is rolled back row by row, the provisional settlement is cleared, and any auto-created replenishment shipment that is still in `DRAFT` is moved to `CANCELLED`.

### 2.8. Numeric Precision and Rounding

All monetary values in this API are integer cents — there are no fractional cents. Bond-strength means are recorded to exactly 2 decimal places using round-half-up. Per-unit packaging fill volumes are whole millilitres, computed with round-half-up at the per-unit step only (see §3.4 for the pinned evaluation order). Calendar arithmetic for shelf-life dating operates at day precision (`YYYY-MM-DD`); pot-life comparisons operate at whole-minute precision. Where a rule describes an inclusive boundary ("at least", "no more than", "exactly N passes"), the comparison is exactly as stated — equality always satisfies a "greater than or equal" or "less than or equal" rule.

### 2.9. Nested Resource Retrieval

For any endpoint whose path carries more than one identifier — for example a specific shipment's line removal, which names both the shipment and the lot — the server validates path identifiers sequentially, left to right. The first identifier in the path that does not correspond to an existing resource produces the `ERR_NOT_FOUND` response, and later identifiers are not consulted. Body-supplied foreign keys are checked only after every path identifier has been resolved; when a body carries several foreign keys, they are consulted in the order the creating passage in §3 names them.

---

## 3. Business Logic & Workflows

### 3.1. The Formulation Master Data Lifecycle

Everything in the plant traces back to a **Formulation** — the recipe and specification record that governs how a batch may be mixed, packaged, tested, and shipped. A `PlantManager` creates a formulation by supplying a `code` that is unique across all formulations (a duplicate is rejected with `ERR_INVALID_REQUEST`), a display `name`, and the chemistry profile: `chemistry_family` (one of `EPOXY`, `POLYURETHANE`, `SILICONE`, or `ACRYLIC`), a `moisture_sensitive` boolean that will later force dry-room packaging, `solvent_content_pct` between 0 and 100 inclusive, the `flash_point_c` in Celsius, the working window `pot_life_minutes` (how long after mix completion the batch remains usable before it gels), the `shelf_life_months` used for expiry dating, the release specification `spec_min_bond_strength_mpa`, and the default `min_remaining_shelf_life_days` that shipments must respect at ship date. A new formulation begins life in `DRAFT` status.

While in `DRAFT`, a formulation can be advanced to `EFFECTIVE` by a `PlantManager` calling activation; if the formulation is not in `DRAFT` the call fails with `ERR_FORMULATION_INVALID_STATE`. Only an `EFFECTIVE` formulation accepts new batches or permits lot release — any attempt to create a batch, or to release a lot, against a formulation that has left `EFFECTIVE` is rejected with `ERR_FORMULATION_NOT_EFFECTIVE`.

Withdrawal moves a formulation from `EFFECTIVE` to `WITHDRAWN`. Withdrawal is refused with `ERR_FORMULATION_INVALID_STATE` when the formulation is not currently `EFFECTIVE`, and refused with `ERR_FORMULATION_HAS_INFLIGHT_BATCHES` when any batch referencing it is still in `MIXING`, `MIXED`, or `PACKING`. Once withdrawn, no new batch can reference the formulation and no further lot of that formulation can be released, but lots already in `RELEASED` remain shippable — withdrawal does not cascade into the lot ledger.

### 3.2. Registering Plant Capacity: Vessels and Dry Rooms

A `PlantManager` also registers the physical plant. Each **MixingVessel** is created with a `vessel_code` unique across all vessels (a duplicate is rejected with `ERR_INVALID_REQUEST`) and a `capacity_liters` ceiling — the maximum batch volume the vessel can hold. Each **DryRoom** is created with a `room_code` unique across all dry rooms (a duplicate is rejected with `ERR_INVALID_REQUEST`), a `max_concurrent_runs` count describing how many packaging runs may have overlapping windows inside the room at once, and an informational `humidity_limit_pct`. Both resources are read-only after creation; there is no update or delete surface.

### 3.3. Booking and Completing a Batch

A `BatchOperator` opens production by creating a **ProductionBatch** in a payload containing the `formulation_id` (which must resolve to an `EFFECTIVE` formulation — otherwise `ERR_FORMULATION_NOT_EFFECTIVE`), the `vessel_id`, the planned mix window as `mix_start_at` and `mix_end_at`, and the total `batch_volume_ml` in millilitres. Two constraints guard vessel booking. The mix window is treated as a half-open interval that includes the start and excludes the end: a new batch overlaps an existing non-terminal batch on the same vessel (one in `MIXING`, `MIXED`, or `PACKING`) only when the new `mix_start_at` falls strictly before the existing batch's `mix_end_at` **and** the existing batch's `mix_start_at` falls strictly before the new `mix_end_at`; touching windows — where one batch's `mix_start_at` equals the other's `mix_end_at` — are permitted. Any genuine overlap is rejected with `ERR_VESSEL_TIME_OVERLAP`. Independently, `batch_volume_ml` must not exceed the vessel's capacity expressed in millilitres (its `capacity_liters` multiplied by 1000); exceeding it is rejected with `ERR_VESSEL_CAPACITY_EXCEEDED`.

Creation is atomic with the creation of the batch's 1:1 **ProductionLot**: the lot is born in `AWAITING_TEST` qa status with `hold_status` `CLEAR`, its `lot_number` assigned by the server as `LOT-` followed by a zero-padded six-digit creation sequence (for example `LOT-000001`), its `batch_id` pointing back to the batch, its `formulation_id` denormalized from the batch for FIFO queries, and its `production_lot_id` stored on the batch for the reverse lookup. The batch's `remaining_bulk_volume_ml` starts equal to `batch_volume_ml`, its `written_off_volume_ml` starts at 0, and its `mixed_at`, `pot_life_deadline` remain null until mix completion. The lot's unit counters — `units_filled`, `units_quarantined`, `units_condemned`, `units_shipped`, and `retest_count` — all start at 0, and its `manufacture_date`, `expiry_date`, `pack_format`, `unit_volume_ml`, and `released_by` start null.

A batch in `MIXING` is finished by a `BatchOperator` completing the mix. The server stamps `mixed_at` with the current logical-clock reading, computes `pot_life_deadline` as `mixed_at` plus the formulation's `pot_life_minutes`, and projects the lot's dating: `manufacture_date` becomes the calendar date of `mixed_at` in `YYYY-MM-DD` form, and `expiry_date` becomes `manufacture_date` advanced by the formulation's `shelf_life_months` calendar months, with the day-of-month clamped to the last day of the target month when it would otherwise overflow (so a manufacture date of 2026-01-31 with a one-month shelf life yields an expiry of 2026-02-28). Complete-mix requires the batch still be in `MIXING`; because the clock sweep expires overdue `MIXING` batches the moment the clock passes `mix_end_at`, a late completion observes an `EXPIRED` batch and fails with `ERR_BATCH_INVALID_STATE`.

A batch may also be voided by a `BatchOperator` while it is in `MIXING` or `MIXED` — any other status fails with `ERR_BATCH_INVALID_STATE` — optionally carrying a `reason`. Voiding moves the batch to `VOID`, moves every `OPEN` or `HOLD` packaging run of the batch to `VOID`, and moves the lot to `REJECTED` if its qa status is still `AWAITING_TEST`, `TESTING`, or `UNDER_REVIEW`.

### 3.4. Packaging Runs, Pot Life, and Fill Allocation

Once a batch is `MIXED`, a `BatchOperator` opens **PackagingRun**s against it. The creation payload names the `batch_id` (the batch must currently be `MIXED` or `PACKING`), the `pack_format` (one of `CARTRIDGE`, `PAIL`, or `DRUM`), the `unit_volume_ml` nominal fill per unit, the requested `planned_units`, and the packing window `planned_start_at` to `planned_end_at`. The `dry_room_id` field is optional in general but **required** when the batch's formulation is `moisture_sensitive`; omitting it for such a formulation is rejected with `ERR_MOISTURE_PROTOCOL_VIOLATION`. All runs of a single batch must share the same `pack_format` and `unit_volume_ml` — the first run of the batch pins both onto the lot's `pack_format` and `unit_volume_ml`, moves the batch from `MIXED` to `PACKING`, and any later run whose `pack_format` or `unit_volume_ml` differs is rejected with `ERR_PACK_FORMAT_MISMATCH`.

When `dry_room_id` is supplied, a capacity check runs against the room. The set of occupants is every run of the same room whose status is `OPEN` or `HOLD`, and window comparison uses **closed** interval semantics: an existing run overlaps the new one when the existing `planned_start_at` is at or before the new `planned_end_at` and the new `planned_start_at` is at or before the existing `planned_end_at` — touching windows count as overlapping because they share the boundary instant. If the count of overlapping occupants has already reached the room's `max_concurrent_runs`, the new run is rejected with `ERR_DRY_ROOM_CAPACITY_EXCEEDED`. This is aggregate capacity, not exclusive use.

Creation also performs the lazy pot-life check described in §2.6: if the current clock has passed the batch's `pot_life_deadline`, the batch expiry cascade fires and the call fails with `ERR_POT_LIFE_EXCEEDED`. A new run starts in `OPEN` status, with `per_unit_fill_ml`, `units_produced`, `total_filled_ml`, and `held_from` all null.

Completing a run — a `BatchOperator` action valid only while the run is `OPEN` (otherwise `ERR_RUN_INVALID_STATE`) — performs the fill allocation with a **pinned rounding order**: round per unit first, then multiply by units. The per-unit fill is the run's `unit_volume_ml` scaled by an overfill percentage keyed on `pack_format` — 2% for `CARTRIDGE`, 1% for `PAIL`, and 0.5% for `DRUM` — with the result rounded half-up to a whole millilitre and stored as `per_unit_fill_ml`. The number of `units_produced` is then the smaller of the requested `planned_units` and the whole number of per-unit fills that fit inside the batch's current `remaining_bulk_volume_ml` (that is, the floor of the remaining volume divided by the per-unit fill). `total_filled_ml` is `units_produced` multiplied by `per_unit_fill_ml`. The per-unit-first order is normative: it can differ from computing the exact total and rounding once (three units of an exact 316.2 ml fill yield 949 ml under sum-then-round, versus 948 ml under the pinned per-unit-first order). If the allocation yields zero units, the completion is rejected with `ERR_INSUFFICIENT_BATCH_VOLUME`. A successful completion moves the run to `SEALED`, decrements the batch's `remaining_bulk_volume_ml` by `total_filled_ml`, increments the lot's `units_filled` by `units_produced`, and — when the remaining bulk volume reaches exactly zero — transitions the batch from `PACKING` to `PACKED`. The lazy pot-life check runs here too: completing a run after `pot_life_deadline` fires the batch expiry cascade and fails with `ERR_POT_LIFE_EXCEEDED`.

When a batch in `MIXED` or `PACKING` crosses its pot-life deadline and is touched, the expiry cascade moves the batch to `EXPIRED`, moves all of its `OPEN` and `HOLD` runs to `VOID`, rejects a lot still in `AWAITING_TEST`, `TESTING`, or `UNDER_REVIEW`, and — because units already sealed are unsalvageable — moves every unit of `SEALED` runs into condemnation while the lot's qa status is still pending: the lot's `units_condemned` grows by each such run's `units_produced` and the batch's `written_off_volume_ml` grows by each such run's `total_filled_ml`. Units of runs that were `SEALED` when they were driven into `HOLD` are likewise moved out of quarantine into condemnation — the lot's `units_quarantined` falls and its `units_condemned` grows by the run's `units_produced`, and the batch's `written_off_volume_ml` grows by the run's `total_filled_ml` — for any lot not yet `RELEASED`, and the lot's `hold_status` returns to `CLEAR` once no run of the batch remains in `HOLD`. `RELEASED` lots and their units are unaffected by batch expiry.

### 3.5. Moisture Exposure, Quarantine, and Hold Release

Moisture exposure is tracked as a first-class log. A `BatchOperator` records a **MoistureExposureEvent** against a packaging run, supplying `exposure_minutes`, the `occurred_at` timestamp, and an optional free-text `note`. The run must currently be `OPEN` or `SEALED`, failing with `ERR_RUN_INVALID_STATE` otherwise. Events are retrievable individually and as a filtered list, and the `MoistureExposureEvent` resource carries no `updated_at` or `version` — it is append-only.

An exposure of less than 30 minutes is merely recorded. An exposure of 30 minutes or more triggers the hold cascade. On an `OPEN` run, the run moves to `HOLD` with `held_from` recording `OPEN`; because an `OPEN` run has produced no units, there are no unit effects. On a `SEALED` run, the cascade has three hops: the run moves to `HOLD` with `held_from` recording `SEALED`; the lot absorbs the quarantine — its `units_quarantined` grows by the run's `units_produced` and its `hold_status` becomes `QUARANTINE_HOLD`; and every shipment in `PLANNED` or `CONFIRMED` containing a line for that lot is forced into `EXCEPTION`.

A `QAManager` resolves a hold through the hold-release action, supplying an `outcome` and an optional `note`. The run must be in `HOLD`, failing with `ERR_RUN_INVALID_STATE` otherwise. With `outcome` `RELEASE`, the run returns to whatever status `held_from` recorded (`OPEN` or `SEALED`), `held_from` is cleared, and for a run that had been `SEALED` the lot's `units_quarantined` is decremented by the run's `units_produced`; the lot's `hold_status` returns to `CLEAR` when no other run of that lot remains in `HOLD`, and stays `QUARANTINE_HOLD` otherwise. Shipments already in `EXCEPTION` are **not** auto-restored — they must be replanned manually. With `outcome` `CONDEMN`, the run moves to `VOID`; if it had been `SEALED`, its units leave quarantine and enter condemnation — the lot's `units_quarantined` decreases by the run's `units_produced`, its `units_condemned` increases by the same amount, and the batch's `written_off_volume_ml` increases by the run's `total_filled_ml`, while `remaining_bulk_volume_ml` is **not** restored. The lot's `hold_status` is recomputed exactly as in the release branch, and `held_from` is cleared.

### 3.6. Cure Testing, Assessment, and Lot Release

Quality assurance centres on the **CureTest**. A `QATechnician` records a test against a lot by providing the `method` — `QUICK` for a single-specimen screen or `FULL` for the formal five-specimen assessment — and the `specimens` array of bond-strength readings in MPa. The lot's `qa_status` must be `AWAITING_TEST` or `TESTING` (else `ERR_LOT_INVALID_STATE`); the first test recorded against an `AWAITING_TEST` lot moves it to `TESTING`. The recording technician's `X-User-ID` is stamped onto the test as `technician_id`. A test is born in `RECORDED` status with `evaluated_value_mpa` and `assessment_pass` null.

A `QAManager` accepts a `RECORDED` test; acceptance requires the lot's `qa_status` to be `TESTING` (a test out of place fails with `ERR_TEST_INVALID_STATE`, a lot out of state with `ERR_LOT_INVALID_STATE`). Acceptance computes the assessment per method. For `QUICK`, exactly 1 specimen is required; `evaluated_value_mpa` is that single specimen, and `assessment_pass` is true when the value is at least the formulation's `spec_min_bond_strength_mpa` — the comparison is inclusive. For `FULL`, exactly 5 specimens are required; the readings are sorted ascending, exactly one minimum and one maximum are dropped, the mean of the three retained specimens is taken and rounded half-up to two decimal places to produce `evaluated_value_mpa`, and `assessment_pass` is true only when both the rounded trimmed mean — `evaluated_value_mpa` itself — is at least `spec_min_bond_strength_mpa` **and** the smallest retained specimen is no more than 2.0 MPa below `spec_min_bond_strength_mpa`. The two variants are deliberately not interchangeable: the same lot data can pass `QUICK` while failing `FULL`, and vice versa. Acceptance also supersedes any previously `ACCEPTED` test of the same lot — the older test moves to `SUPERSEDED` — and moves the lot's `qa_status` to `UNDER_REVIEW`. A `QAManager` may alternatively void a `RECORDED` test outright (with an optional `reason`), moving it to `VOIDED`.

From `UNDER_REVIEW`, a `QAManager` has three exits. **Request retest** returns the lot to `TESTING`, incrementing `retest_count` by one; the lot allows at most two retest cycles, so a request when `retest_count` has already reached 2 fails with `ERR_RETEST_LIMIT_EXCEEDED`, and a request from any other qa status fails with `ERR_LOT_INVALID_STATE`. **Reject** moves the lot to `REJECTED`; segregation of duties applies — the acting `X-User-ID` must differ from the `technician_id` of the accepted test, else `ERR_SEGREGATION_OF_DUTIES`. Rejection condemns the sealed units: the lot's `units_condemned` grows by the quantity `units_filled` minus `units_condemned` minus `units_quarantined`, the batch's `written_off_volume_ml` grows by the sum of `total_filled_ml` over the batch's runs still in `SEALED` status, and `units_quarantined` is unchanged. **Release** moves the lot to `RELEASED` and is the most heavily gated transition in the system. Evaluated in order: the lot must be in `UNDER_REVIEW` (else `ERR_LOT_INVALID_STATE`); its `hold_status` must be `CLEAR` (else `ERR_LOT_ON_HOLD`); the most recently `ACCEPTED` (and not subsequently `SUPERSEDED`) test must be a `FULL` assessment whose `assessment_pass` is true (else `ERR_BOND_STRENGTH_BELOW_SPEC` — a passing `QUICK` screen never suffices); segregation of duties must hold between the releaser and the recording technician (else `ERR_SEGREGATION_OF_DUTIES`); and the formulation must still be `EFFECTIVE` (else `ERR_FORMULATION_NOT_EFFECTIVE`). On release the server stamps `released_by` with the acting `X-User-ID`.

### 3.7. Technical-Service Formulation Requests

Distributors request new or adapted products through the **FormulationRequest** pipeline. A `Distributor` submits a request with `distributor_id` (which must equal the caller's `X-User-ID`), a `contact_name`, the `target_substrate` the adhesive must bond, the `required_bond_strength_mpa`, and free-text `application_notes`. The request is born `SUBMITTED`, with `info_request_note`, `response_note`, `decision_outcome`, and `resulting_formulation_id` all null.

A `TechServiceEngineer` picks up the request via start-review, moving `SUBMITTED` to `TECH_REVIEW`. From `TECH_REVIEW` the engineer may either request more information — moving the request to `NEEDS_INFO` and recording the payload's `info_request_note` — or decide it. The owning distributor answers an information request by calling respond, which cycles the request from `NEEDS_INFO` back into `TECH_REVIEW` and records the payload's `response_note`; only the distributor whose `distributor_id` owns the request may respond, otherwise `ERR_INSUFFICIENT_PERMISSIONS`. The decide action takes an `outcome` of `APPROVED` or `DECLINED` with an optional `decision_note`, moving the request from `TECH_REVIEW` to the matching state and stamping `decision_outcome`. An `APPROVED` request is moved to `IN_DEVELOPMENT` by start-development, and from `IN_DEVELOPMENT` the convert action completes the pipeline: it creates a brand-new `Formulation` in `DRAFT` from the convert payload's `formulation_code`, `formulation_name`, `chemistry_family`, `moisture_sensitive`, `solvent_content_pct`, `flash_point_c`, `pot_life_minutes`, `shelf_life_months`, `spec_min_bond_strength_mpa`, and `min_remaining_shelf_life_days` — the new `formulation_code` must be unique across all formulations, a check applied after the `IN_DEVELOPMENT` state gate and surfacing as `ERR_INVALID_REQUEST` — sets the request's `resulting_formulation_id` to the new formulation's id, and moves the request to `CONVERTED`. Every step requires the request to be in the expected from-state, failing with `ERR_REQUEST_INVALID_STATE` otherwise. When listing requests, a `Distributor`-role caller sees only rows whose `distributor_id` matches their own `X-User-ID`; the listing supports `distributor_id` and `resulting_formulation_id` filters.

### 3.8. Consignment Agreements and the Credit Check

The commercial side of the house begins with the **Distributor** record, which a `CommercialManager` registers with a `name`, a `credit_limit_cents` ceiling on total consigned value, and a `contact_email`.

Against a distributor, a `CommercialManager` opens a **ConsignmentAgreement** naming the `distributor_id`, the single covered `formulation_id`, the `unit_price_cents` used at settlement, the `max_consigned_value_cents` the agreement may hold, the replenishment parameters `reorder_threshold_units` and `reorder_qty_units`, and optionally a `min_remaining_shelf_life_days` that overrides the formulation's default for consignment shipments of this agreement (when omitted it stays null and the formulation default applies). An agreement is born in `DRAFT`.

Activation moves `DRAFT` to `ACTIVE` and runs the credit check: the sum of `max_consigned_value_cents` across the distributor's agreements currently in `ACTIVE` or `SUSPENDED`, plus the candidate agreement's own `max_consigned_value_cents`, must not exceed the distributor's `credit_limit_cents`. The boundary is inclusive — a total exactly equal to the limit passes — while a strictly greater total is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. An agreement not in `DRAFT` fails activation with `ERR_AGREEMENT_INVALID_STATE`. Suspension moves `ACTIVE` to `SUSPENDED`, and resume moves `SUSPENDED` back to `ACTIVE` while re-running the same credit check. Close moves an agreement from `ACTIVE` or `SUSPENDED` to `CLOSED`, but only when no `ConsumptionReport` of the agreement remains in `DRAFT`, `SUBMITTED`, or `DISPUTED` (else `ERR_AGREEMENT_HAS_OPEN_REPORTS`) and every `ConsignmentStock` row of the agreement shows `qty_on_hand` of zero (else `ERR_CONSIGNMENT_STOCK_REMAINING`).

Commercial terms can be amended while preserving concurrency safety: the patch operation accepts any subset of `reorder_threshold_units`, `reorder_qty_units`, `min_remaining_shelf_life_days`, and `max_consigned_value_cents`, and **requires** `expected_agreement_version` matching the agreement's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) on mismatch (see §2.4). The patch is permitted in any agreement status, and an explicit `null` for `min_remaining_shelf_life_days` clears the override. Successful activation, suspension, resume, close, and patch each increment the agreement's `version` by 1.

### 3.9. Shipments, FIFO, Hazmat Classification, and Shelf-Life Gating

A `LogisticsCoordinator` builds a **Shipment** by supplying the `shipment_kind` (`SALE`, `CONSIGNMENT`, or `CONSIGNMENT_REPLENISHMENT`), the `distributor_id`, the `transport_mode` (`ROAD`, `AIR`, or `SEA`), and the planned `ship_date` in `YYYY-MM-DD` form. The `agreement_id` is required for the two consignment kinds and must be null for `SALE`; violations of either rule are `ERR_INVALID_REQUEST`. A shipment is born in `DRAFT` with an empty `lines` array, `hazmat_class` null, `auto_replenishment` false, and `proposed_units` null.

Lines are added to a shipment only while it is in `DRAFT` or `EXCEPTION`; each line names a `lot_id` and a `units` count, and a lot may appear at most once per shipment — a duplicate line is rejected with `ERR_DUPLICATE_LOT_LINE`. Line addition enforces a chain of lot checks. The lot must be shippable: `qa_status` `RELEASED`, `hold_status` `CLEAR`, and an `expiry_date` strictly after the shipment's `ship_date`. A lot failing the release or dating leg is rejected with `ERR_LOT_NOT_SHIPPABLE`; a lot under quarantine is rejected with `ERR_LOT_ON_HOLD`. Then strict FIFO applies across the formulation: among every `RELEASED`, `CLEAR` lot of the same `formulation_id` whose `expiry_date` lies strictly after `ship_date` and which still has available units, the lot with the earliest `expiry_date` (ties broken by the earliest `created_at`, then by creation order) must be the lot on the line; choosing any newer eligible lot while an older one still has availability is rejected with `ERR_FIFO_VIOLATION`. Availability itself is computed as the lot's `units_filled` minus `units_quarantined` minus `units_condemned` minus `units_shipped` minus a reservation term that sums the `units` of every line referencing the lot across all shipments in `DRAFT`, `PLANNED`, or `CONFIRMED`; a line whose `units` exceed that availability is rejected with `ERR_INSUFFICIENT_LOT_STOCK`. Lines may similarly be removed while the shipment is in `DRAFT` or `EXCEPTION`, releasing the reservation; removing a `lot_id` that has no line on the shipment fails with `ERR_NOT_FOUND`.

Planning a shipment moves `DRAFT` to `PLANNED` and requires at least one line (else `ERR_INVALID_REQUEST`). Planning computes the shipment's `hazmat_class` as the highest-risk classification across its lines. Each line is classified from its formulation and pack: when the formulation's `solvent_content_pct` is at least 24.0 and its `flash_point_c` is below 60.5 °C, the line falls under UN1133 Class 3 — packing group `UN1133_CLASS3_PG_II` when `flash_point_c` is below 23.0 °C, otherwise `UN1133_CLASS3_PG_III`. Any other formulation is `NON_REGULATED`. Ranking runs `NON_REGULATED` below `UN1133_CLASS3_PG_III` below `UN1133_CLASS3_PG_II`, and the shipment takes the worst rank across lines.

Confirmation moves `PLANNED` to `CONFIRMED` and applies its gates **in order: safety first, then temporal**. The hazmat mode gate applies only when `transport_mode` is `AIR`: any line classified `UN1133_CLASS3_PG_II` whose lot's `unit_volume_ml` exceeds 5000 ml is forbidden, and any `UN1133_CLASS3_PG_III` line packed as a `DRUM` is likewise forbidden; both surface as `ERR_HAZMAT_MODE_FORBIDDEN`. `ROAD` and `SEA` impose no additional gate. The temporal gate then checks each line's remaining shelf life at `ship_date`: the applicable minimum is the agreement's `min_remaining_shelf_life_days` when the shipment is a consignment kind and the override is not null, otherwise the formulation's `min_remaining_shelf_life_days`; the remaining days are the calendar-day difference between the lot's `expiry_date` and the `ship_date`, and the line passes when the remainder is at least the applicable minimum — equality passes, anything less fails with `ERR_MIN_SHELF_LIFE_VIOLATION`. For consignment kinds, confirmation also requires the agreement to be `ACTIVE`, failing with `ERR_AGREEMENT_NOT_ACTIVE` otherwise.

Dispatch moves `CONFIRMED` to `DISPATCHED`. For consignment kinds the agreement must still be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`). Dispatch performs two stock effects per line: the lot's `units_shipped` grows by the line's `units`, and for consignment kinds the **ConsignmentStock** row keyed by the unique `(agreement_id, lot_id)` pair (carried on the row's `row_key`) is upserted — created on first dispatch with counters at zero, thereafter incremented — with `qty_shipped` and `qty_on_hand` each growing by the line's `units`. A stock row's `qty_on_hand` is always its `qty_shipped` minus `qty_consumed` minus `qty_returned`, and `qty_consumed` and `qty_returned` start at zero.

The moisture cascade reaches shipments directly: any shipment in `PLANNED` or `CONFIRMED` that contains a line for a lot entering `QUARANTINE_HOLD` is moved to `EXCEPTION`. From `EXCEPTION`, a `LogisticsCoordinator` replans once every blocked line has been removed — replan requires that no remaining line reference a lot whose `hold_status` is not `CLEAR`, else `ERR_SHIPMENT_BLOCKED_LINES` — and the shipment returns to `PLANNED` with `hazmat_class` recomputed from the remaining lines. Cancellation moves a shipment from any of `DRAFT`, `PLANNED`, `CONFIRMED`, or `EXCEPTION` to `CANCELLED` (with an optional `reason`), releasing all line reservations by virtue of the terminal status. Any state call against a shipment not in the expected from-state fails with `ERR_SHIPMENT_INVALID_STATE`.

### 3.10. Consumption Reports, Stock Waterfall, and Settlement

Consignment billing runs on the **ConsumptionReport** cycle. A `Distributor` creates a report against one of its agreements by supplying the `period` (in `YYYY-MM` form), the `consumed_units` count (at least 1), and the OCC token `expected_agreement_version` (see §2.4 — a stale token is rejected with `ERR_STALE_VERSION`). Creation requires the agreement to be `ACTIVE`, failing with `ERR_AGREEMENT_NOT_ACTIVE` otherwise. At most one non-`VOID` report may exist per agreement and period: when a non-`DRAFT` report (one in `SUBMITTED`, `SETTLED`, or `DISPUTED`) already exists for the pair, creation is rejected with `ERR_REPORT_PERIOD_DUPLICATE`; when a `DRAFT` report already exists for the pair, the new report legitimately supersedes it and the older `DRAFT` is moved to `VOID`. Because a superseding create is exactly the kind of action a stale view must not perform blindly, the OCC guard on this endpoint is non-optional. A successful create also advances the agreement's `version` by 1. The new report is born in `DRAFT`, with `provisional_settlement_cents`, `rebate_tier`, `rebate_cents`, `final_net_settlement_cents`, and `dispute_reason` all null.

Submitting a report is a `Distributor` action with several preconditions: the report must be in `DRAFT` (else `ERR_REPORT_INVALID_STATE`), the agreement must be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`), and the agreement's owning `distributor_id` must equal the caller's `X-User-ID` (else `ERR_INSUFFICIENT_PERMISSIONS`). Submit then applies the stock waterfall: the agreement's `ConsignmentStock` rows with positive `qty_on_hand` are visited in FIFO order — ascending by their lot's `expiry_date`, ties broken by ascending lot `created_at`, then by creation order — and each row yields up to its full `qty_on_hand` toward the reported `consumed_units`, incrementing `qty_consumed` and decrementing `qty_on_hand` by the amount taken, until the reported quantity is fully allocated. If the rows collectively cannot cover `consumed_units`, the submit fails with `ERR_STOCK_NEGATIVE` and **no row is modified** — the check is atomic, with no partial application. On success the report moves to `SUBMITTED` and the provisional settlement is recorded as `consumed_units` times the agreement's `unit_price_cents`, stored in `provisional_settlement_cents`. Submit finishes with the reorder cascade: when the agreement's total `qty_on_hand` has fallen below its `reorder_threshold_units`, and no shipment already exists for this agreement with `auto_replenishment` true in `DRAFT`, `PLANNED`, or `CONFIRMED`, the server creates a replenishment shipment — `shipment_kind` `CONSIGNMENT_REPLENISHMENT`, `auto_replenishment` true, `proposed_units` set to the agreement's `reorder_qty_units`, the distributor taken from the agreement, `transport_mode` `ROAD`, `ship_date` set seven days after the current logical-clock date, and status `DRAFT`.

Settlement, dispute, and revision complete the cycle. A `CommercialManager` settles a `SUBMITTED` report, producing the final figures in a pinned evaluation order: the gross is `consumed_units` times the agreement's `unit_price_cents`; the `rebate_tier` is keyed on that gross — a gross of at least 1000000 cents earns `TIER2` at 10%, a gross of at least 500000 cents earns `TIER1` at 5%, and anything below earns `NONE` at 0%, with both thresholds inclusive (a gross of exactly 500000 cents already earns `TIER1`); `rebate_cents` is the gross multiplied by the tier percentage and divided by 100, rounded half-up to whole cents; and `final_net_settlement_cents` is the gross minus the rebate. The provisional figure computed at submit is always the flat list-price gross with no rebate, so it is at least the final net whenever a tier applies. Dispute moves a `SUBMITTED` report to `DISPUTED` and requires and records the payload's `reason` into `dispute_reason`. Revision — a `Distributor` action on a `DISPUTED` report whose owning agreement belongs to the caller — cycles the report back to `DRAFT`, rolls back the submit waterfall row by row (each row's `qty_consumed` decreases and `qty_on_hand` increases by the amount that row had contributed), clears `provisional_settlement_cents` and `dispute_reason` to null, and cancels the linked auto-replenishment shipment when it is still in `DRAFT` (one already `PLANNED` or further is left untouched); a `consumed_units` value supplied in the revise payload replaces the report's figure. Settlement, dispute, and revision each require the expected from-state, failing with `ERR_REPORT_INVALID_STATE` otherwise.

Finally, a `CommercialManager` may return consigned units to the manufacturer through the stock-return action, supplying `units` and an optional `note`. The return is the compensating action of dispatch: it requires the agreement not to be `CLOSED` (else `ERR_AGREEMENT_INVALID_STATE`), requires `units` not to exceed the stock row's `qty_on_hand` (else `ERR_RETURN_EXCEEDS_ON_HAND`), and on success grows the row's `qty_returned` by `units`, shrinks `qty_on_hand` by `units`, and decrements the lot's `units_shipped` by the same amount.

---

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource (including all state transitions) return `200 OK`. The single exception to the create/modify split is the logical-clock endpoint, which returns `200 OK`. All endpoints are mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; sweeps overdue MIXING batches to EXPIRED | PlatformAdmin |
| POST | `/api/formulations` | Create a formulation in DRAFT | PlantManager |
| GET | `/api/formulations` | List formulations | Any |
| GET | `/api/formulations/{formulationId}` | Get one formulation | Any |
| POST | `/api/formulations/{formulationId}/activate` | Activate a DRAFT formulation | PlantManager |
| POST | `/api/formulations/{formulationId}/withdraw` | Withdraw an EFFECTIVE formulation (blocked by in-flight batches) | PlantManager |
| POST | `/api/mixing-vessels` | Register a mixing vessel | PlantManager |
| GET | `/api/mixing-vessels/{vesselId}` | Get one vessel | Any |
| POST | `/api/dry-rooms` | Register a dry room | PlantManager |
| GET | `/api/dry-rooms/{dryRoomId}` | Get one dry room | Any |
| POST | `/api/batches` | Create a batch in MIXING; atomically creates its 1:1 ProductionLot | BatchOperator |
| GET | `/api/batches` | List batches (filterable by `formulation_id`, `vessel_id`) | Any |
| GET | `/api/batches/{batchId}` | Get one batch | Any |
| POST | `/api/batches/{batchId}/complete-mix` | Complete mixing; stamps mixed_at, pot-life deadline, lot dates | BatchOperator |
| POST | `/api/batches/{batchId}/void` | Void a MIXING or MIXED batch with run/lot cascade | BatchOperator |
| POST | `/api/packaging-runs` | Open a packaging run for a MIXED or PACKING batch | BatchOperator |
| GET | `/api/packaging-runs` | List packaging runs (filterable by `batch_id`, `dry_room_id`) | Any |
| GET | `/api/packaging-runs/{runId}` | Get one packaging run | Any |
| POST | `/api/packaging-runs/{runId}/complete` | Seal an OPEN run; computes fill allocation and decrements bulk volume | BatchOperator |
| POST | `/api/packaging-runs/{runId}/exposure-events` | Log a moisture exposure event; >= 30 min triggers HOLD cascade | BatchOperator |
| GET | `/api/exposure-events` | List exposure events (filterable by `packaging_run_id`) | Any |
| GET | `/api/exposure-events/{eventId}` | Get one exposure event | Any |
| POST | `/api/packaging-runs/{runId}/hold-release` | Release a held run back to service or condemn it | QAManager |
| GET | `/api/production-lots` | List lots (filterable by `batch_id`, `formulation_id`) | Any |
| GET | `/api/production-lots/{lotId}` | Get one lot | Any |
| POST | `/api/production-lots/{lotId}/cure-tests` | Record a cure/bond-strength test against a lot | QATechnician |
| POST | `/api/production-lots/{lotId}/release` | Release an UNDER_REVIEW lot (gated: hold CLEAR, FULL pass, SoD, formulation EFFECTIVE) | QAManager |
| POST | `/api/production-lots/{lotId}/reject` | Reject an UNDER_REVIEW lot; condemns sealed units | QAManager |
| POST | `/api/production-lots/{lotId}/request-retest` | Return an UNDER_REVIEW lot to TESTING (max two retests) | QAManager |
| GET | `/api/cure-tests` | List cure tests (filterable by `lot_id`) | Any |
| GET | `/api/cure-tests/{testId}` | Get one cure test | Any |
| POST | `/api/cure-tests/{testId}/accept` | Accept a RECORDED test; computes assessment; lot to UNDER_REVIEW | QAManager |
| POST | `/api/cure-tests/{testId}/void` | Void a RECORDED test | QAManager |
| POST | `/api/formulation-requests` | Submit a technical-service formulation request | Distributor |
| GET | `/api/formulation-requests` | List requests (Distributor role sees only its own) | Any |
| GET | `/api/formulation-requests/{requestId}` | Get one request | Any |
| POST | `/api/formulation-requests/{requestId}/start-review` | Move a SUBMITTED request into technical review | TechServiceEngineer |
| POST | `/api/formulation-requests/{requestId}/request-info` | Ask the distributor for more information | TechServiceEngineer |
| POST | `/api/formulation-requests/{requestId}/respond` | Distributor answers an information request | Distributor |
| POST | `/api/formulation-requests/{requestId}/decide` | Approve or decline a request in review | TechServiceEngineer |
| POST | `/api/formulation-requests/{requestId}/start-development` | Move an APPROVED request into development | TechServiceEngineer |
| POST | `/api/formulation-requests/{requestId}/convert` | Convert an IN_DEVELOPMENT request into a new DRAFT formulation | TechServiceEngineer |
| POST | `/api/distributors` | Register a distributor | CommercialManager |
| GET | `/api/distributors/{distributorId}` | Get one distributor | Any |
| POST | `/api/consignment-agreements` | Create a consignment agreement in DRAFT | CommercialManager |
| GET | `/api/consignment-agreements` | List agreements (filterable by `distributor_id`, `formulation_id`) | Any |
| GET | `/api/consignment-agreements/{agreementId}` | Get one agreement | Any |
| PATCH | `/api/consignment-agreements/{agreementId}` | Update commercial terms (OCC-guarded) | CommercialManager |
| POST | `/api/consignment-agreements/{agreementId}/activate` | Activate a DRAFT agreement with credit check | CommercialManager |
| POST | `/api/consignment-agreements/{agreementId}/suspend` | Suspend an ACTIVE agreement | CommercialManager |
| POST | `/api/consignment-agreements/{agreementId}/resume` | Resume a SUSPENDED agreement with credit re-check | CommercialManager |
| POST | `/api/consignment-agreements/{agreementId}/close` | Close an agreement (guarded by open reports and remaining stock) | CommercialManager |
| GET | `/api/consignment-stock` | List consignment stock rows (filterable by `agreement_id`, `lot_id`) | Any |
| GET | `/api/consignment-stock/{stockId}` | Get one stock row | Any |
| POST | `/api/consignment-stock/{stockId}/return` | Return consigned units to the manufacturer | CommercialManager |
| POST | `/api/consignment-agreements/{agreementId}/consumption-reports` | Create a consumption report (OCC-guarded; supersedes a DRAFT for the same period) | Distributor |
| GET | `/api/consumption-reports` | List consumption reports (filterable by `agreement_id`) | Any |
| GET | `/api/consumption-reports/{reportId}` | Get one consumption report | Any |
| POST | `/api/consumption-reports/{reportId}/submit` | Submit a DRAFT report; FIFO waterfall, provisional settlement, reorder cascade | Distributor |
| POST | `/api/consumption-reports/{reportId}/settle` | Settle a SUBMITTED report with tiered rebate | CommercialManager |
| POST | `/api/consumption-reports/{reportId}/dispute` | Dispute a SUBMITTED report | CommercialManager |
| POST | `/api/consumption-reports/{reportId}/revise` | Cycle a DISPUTED report back to DRAFT with rollback | Distributor |
| POST | `/api/shipments` | Create a shipment in DRAFT | LogisticsCoordinator |
| GET | `/api/shipments` | List shipments (filterable by `distributor_id`, `agreement_id`, `shipment_kind`, `status`) | Any |
| GET | `/api/shipments/{shipmentId}` | Get one shipment | Any |
| POST | `/api/shipments/{shipmentId}/lines` | Add a lot line (DRAFT or EXCEPTION only; shippability, FIFO, stock checks) | LogisticsCoordinator |
| POST | `/api/shipments/{shipmentId}/lines/{lotId}/remove` | Remove a lot line (DRAFT or EXCEPTION only) | LogisticsCoordinator |
| POST | `/api/shipments/{shipmentId}/plan` | Plan a DRAFT shipment; computes hazmat class | LogisticsCoordinator |
| POST | `/api/shipments/{shipmentId}/confirm` | Confirm a PLANNED shipment; hazmat mode gate then shelf-life gate | LogisticsCoordinator |
| POST | `/api/shipments/{shipmentId}/dispatch` | Dispatch a CONFIRMED shipment; lot units_shipped and consignment stock upsert | LogisticsCoordinator |
| POST | `/api/shipments/{shipmentId}/cancel` | Cancel a shipment; releases line reservations | LogisticsCoordinator |
| POST | `/api/shipments/{shipmentId}/replan` | Return an EXCEPTION shipment to PLANNED after blocked lines are removed | LogisticsCoordinator |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FORMULATION_NOT_EFFECTIVE` | 409 |
| `ERR_FORMULATION_INVALID_STATE` | 409 |
| `ERR_FORMULATION_HAS_INFLIGHT_BATCHES` | 409 |
| `ERR_VESSEL_TIME_OVERLAP` | 409 |
| `ERR_VESSEL_CAPACITY_EXCEEDED` | 422 |
| `ERR_DRY_ROOM_CAPACITY_EXCEEDED` | 409 |
| `ERR_MOISTURE_PROTOCOL_VIOLATION` | 422 |
| `ERR_PACK_FORMAT_MISMATCH` | 409 |
| `ERR_BATCH_INVALID_STATE` | 409 |
| `ERR_POT_LIFE_EXCEEDED` | 422 |
| `ERR_RUN_INVALID_STATE` | 409 |
| `ERR_INSUFFICIENT_BATCH_VOLUME` | 422 |
| `ERR_TEST_INVALID_STATE` | 409 |
| `ERR_LOT_INVALID_STATE` | 409 |
| `ERR_LOT_ON_HOLD` | 409 |
| `ERR_RETEST_LIMIT_EXCEEDED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_BOND_STRENGTH_BELOW_SPEC` | 422 |
| `ERR_REQUEST_INVALID_STATE` | 409 |
| `ERR_AGREEMENT_INVALID_STATE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_HAS_OPEN_REPORTS` | 409 |
| `ERR_CONSIGNMENT_STOCK_REMAINING` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_REPORT_INVALID_STATE` | 409 |
| `ERR_REPORT_PERIOD_DUPLICATE` | 409 |
| `ERR_STOCK_NEGATIVE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SHIPMENT_INVALID_STATE` | 409 |
| `ERR_SHIPMENT_BLOCKED_LINES` | 409 |
| `ERR_DUPLICATE_LOT_LINE` | 409 |
| `ERR_LOT_NOT_SHIPPABLE` | 409 |
| `ERR_FIFO_VIOLATION` | 409 |
| `ERR_INSUFFICIENT_LOT_STOCK` | 409 |
| `ERR_MIN_SHELF_LIFE_VIOLATION` | 422 |
| `ERR_HAZMAT_MODE_FORBIDDEN` | 422 |
| `ERR_RETURN_EXCEEDS_ON_HAND` | 422 |
