# Industrial Gas Cylinder Fill API — Product Requirements Document

## 1. Introduction

An industrial gas production plant lives and dies by three disciplines at once: the physics of cryogenic liquid inventory, the regulatory weight of pressure-vessel and hazardous-materials compliance, and the commercial reality of cylinder rental billing. This document specifies the Industrial Gas Cylinder Fill API, a system that runs those disciplines as one coherent whole. The platform covers plant and cryogenic storage tank registry with liquid-level telemetry, cylinder asset tracking with hydrostatic retest compliance, fill lots graded by laboratory purity analysis, customer rental and demurrage billing, hazmat delivery routing with driver certification enforcement, customer-site bulk tank installations with telemetry-driven replenishment, custom gas mixture blending, and the loss or retirement of cylinder assets.

Two design commitments shape every workflow in this document. First, the system is audit-grade: laboratory work is segregated from production work through hard identity checks, quality holds propagate outward to cylinders, rentals, and customer accounts through explicit cascades, and every mutation advances a version counter so that configuration writes can be protected against stale reads. Second, all date arithmetic in the system — hydrostatic due dates, certificate expiries, overdue sweeps, rental accrual windows — evaluates against a single logical clock, never against wall-clock time, so that compliance determinations are deterministic and reproducible. All API resources are mounted under `/api`.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly seven roles, spelled precisely as follows: `PlantManager`, `ProductionOperator`, `LabAnalyst`, `QualityManager`, `LogisticsCoordinator`, `BillingClerk`, and `Driver`. A request with either header missing, or with a role value outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Each endpoint declares the roles permitted to call it; a caller whose role is not listed, or who violates a role-scoped restriction on an otherwise permitted endpoint, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The identity carried in `X-User-ID` is interpreted per role. When `X-User-Role` is `PlantManager`, `ProductionOperator`, `LabAnalyst`, `QualityManager`, `LogisticsCoordinator`, or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `recorded_by_user_id` on a telemetry reading or a purity analysis, as `completed_by_user_id` on a fill lot, or as `blended_by_user_id` on a blend order — but it never compares such an identifier to any entity's `id`. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver` entity, and it must be an existing driver's `id`; an unknown driver identifier is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Ownership checks on resources that reference a driver compare the resource's `driver_id` field to `X-User-ID`: a `Driver` may complete only a route assigned to them personally, and a `Driver` may never cancel a route.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Plant Logical Clock

All date and time arithmetic in the system — hydrostatic due-date derivation, certificate expiry checks, rental overdue sweeps, replenishment spacing, telemetry acceptance — evaluates against a single logical clock, never against wall-clock time. A `PlantManager` may advance the logical clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. Before any such call, the server's startup default is exactly 2026-08-01T00:00:00Z, and the logical clock never falls back to wall-clock time. Every clock-derived field — cylinder `hydro_status`, driver certification status, rental overdue state — is computed against the logical clock at the moment it is next evaluated.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on any change to the resource, including changes driven purely by derived-field reconciliation or by a cascade that merely touches the resource. The `version` field is an integer that starts at 1 and increments by exactly 1 on every mutation, again including derived-field reconciliation and cascade touches. One resource family is exempt from the full set: telemetry readings are immutable, append-only records and carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.6. Units, Precision, and Rounding Discipline

Liquid volumes are expressed in liters and computed to exactly 2 decimal places using round-half-up; where a rule pins its rounding to a specific step (for example, the final sum of a fill draw, or each tier segment of a demurrage line), the rule says so, and no additional rounding is applied anywhere else. Pressures are expressed in bar. All monetary values are integer cents; whenever a monetary formula produces a fractional cent, the value is rounded half-up to whole cents at the step the formula pins. Dates are ISO calendar dates; instants are ISO 8601 UTC timestamps. Day-count arithmetic throughout the system is in whole calendar days.

### 2.7. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, and no other endpoint takes a version field of any kind.

- Updating a storage tank's configuration via `PATCH /api/tanks/{tankId}` requires a non-optional `expected_tank_version` carrying the caller's last observed `version` of the tank. If the tank's current `version` has advanced past the supplied value, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's view of thresholds such as the reorder point is stale and the lost update is refused rather than silently overwriting another writer's configuration.
- Updating a customer account's credit terms via `PATCH /api/customers/{customerId}` requires a non-optional `expected_customer_version` carrying the caller's last observed `version` of the account. A mismatch with the account's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because the credit terms the caller observed no longer describe the account.
- Creating a replenishment order via `POST /api/replenishment-orders` requires a non-optional `expected_installation_version` carrying the caller's last observed `version` of the installation. A mismatch with the installation's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); creation supersedes any pending order on the installation, and a caller whose view is stale cannot have seen the order its request would supersede.

### 2.8. Request Validation Pipeline and Check Ordering

Every request passes through a fixed validation pipeline. When several checks could reject the same request, the rejection reported is the earliest applicable check in the order below — a state-gate failure, for instance, masks a hydro-compliance failure that would also have fired.

1. **Authentication context.** Both headers are present and the role is a declared role; for the entity-backed `Driver` role, `X-User-ID` must be an existing driver `id`. Failure: `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization.** The caller's role is listed on the endpoint and role-scoped restrictions hold — a `Driver` may complete only a route whose `driver_id` equals their `X-User-ID`, and may never cancel any route. Failure: `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Body well-formedness.** Required fields are present, types are correct, every enum member is one of the declared values, exactly-one field pairs carry exactly one side, reading levels lie within owner capacity, `period_start` is not after `period_end`, and route window bounds hold (start hour between 0 and 23 inclusive, end hour between 1 and 24 inclusive, end strictly after start). Failure: `ERR_INVALID_REQUEST` or, for an undeclared enum member, `ERR_INVALID_ENUM_VALUE` (both HTTP 400).
4. **Existence.** Path identifiers and body foreign-key references exist, validated left-to-right: path identifiers first, then body fields in declaration order. Failure: `ERR_NOT_FOUND` (HTTP 404).
5. **State gates.** The target resource's state permits the operation — the plant is `OPERATING` for production transitions, the tank is `IN_SERVICE` for starting a fill, the lot, blend, route, rental, analysis, and billing run sit in the from-state their machine requires, the customer is `ACTIVE` for rental and blend creation, the cylinder is `FILLED` for rental checkout or `IN_STOCK` for lot assignment, and the installation is `ACTIVE` for replenishment creation. Failures: `ERR_PLANT_NOT_OPERATING`, `ERR_TANK_NOT_IN_SERVICE`, `ERR_FILL_LOT_INVALID_STATE`, `ERR_BLEND_ORDER_INVALID_STATE`, `ERR_ROUTE_INVALID_STATE`, `ERR_RENTAL_NOT_ACTIVE`, `ERR_ANALYSIS_INVALID_STATE`, `ERR_BILLING_RUN_INVALID_STATE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_CYLINDER_NOT_AVAILABLE`, `ERR_INSTALLATION_INVALID_STATE`, `ERR_DRIVER_NOT_QUALIFIED`, or `ERR_REPLENISHMENT_INVALID_STATE` (all HTTP 409).
6. **Hydrostatic compliance.** At cylinder assignment into a lot and at rental checkout — those two operations exactly — the cylinder's `hydro_status` must not be `OVERDUE`; a cylinder due exactly today passes. Failure: `ERR_HYDRO_RETEST_OVERDUE` (HTTP 422).
7. **Product-service alignment.** The cylinder's `service_gas` equals the lot's `product_code` at assignment, and the lot's `product_code` equals its tank's `product_code` at lot creation. Failure: `ERR_PRODUCT_SERVICE_MISMATCH` (HTTP 422).
8. **Hazmat coverage.** At driver assignment and again at dispatch, the union of stop hazmat classes is covered by the driver's endorsements, a missing class is distinguished from an expired endorsement, and the medical card is valid. Failures: `ERR_HAZMAT_ENDORSEMENT_MISSING` or `ERR_DRIVER_CERT_EXPIRED` (both HTTP 422).
9. **Segregation of duties.** The analyst recording a purity result differs from the operator who completed the subject's fill or blend, and the manager overriding an analysis differs from the analyst who recorded it. Failure: `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).
10. **Route window overlap.** At driver assignment, no other assigned or dispatched route of the same driver on the same date overlaps the half-open window. Failure: `ERR_DRIVER_ROUTE_OVERLAP` (HTTP 409).
11. **Telemetry temporal sanity.** A reading's `measured_at` is not later than the logical clock. Failure: `ERR_TELEMETRY_FUTURE_DATED` (HTTP 422).
12. **Replenishment spacing.** A new order's `scheduled_delivery_at` respects the minimum gap after the installation's last delivered order. Failure: `ERR_REPLENISHMENT_WINDOW_CONFLICT` (HTTP 409).
13. **Tank capacity and lot occupancy.** At start-fill, headroom covers the estimated draw plus the minimum tank reserve and the lot holds at least one reserved cylinder; at start-blend, every component's tank pool is non-empty. Failures: `ERR_TANK_LEVEL_TOO_LOW` or `ERR_LOT_HAS_NO_CYLINDERS` (both HTTP 409).
14. **Serial uniqueness.** A new cylinder's `serial_number` is globally unique. Failure: `ERR_DUPLICATE_CYLINDER_SERIAL` (HTTP 409).
15. **Blend composition.** The components array is well-formed and its target percentages sum correctly. Failure: `ERR_BLEND_COMPONENT_SUM_INVALID` (HTTP 422).
16. **Credit limit.** At rental checkout, the projected balance stays within the credit limit. Failure: `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

### 2.9. Existence Validation and Path Identifiers

When an endpoint path contains a resource identifier, the server validates identifiers in a strict left-to-right order — path identifiers first, then body foreign-key fields in their declaration order — and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. The path identifiers used across the API are `{plantId}`, `{tankId}`, `{readingId}`, `{cylinderId}`, `{fillLotId}`, `{analysisId}`, `{customerId}`, `{rentalId}`, `{driverId}`, `{routeId}`, `{installationId}`, `{orderId}`, `{blendOrderId}`, and `{billingRunId}`. Two resource families carry polymorphic references governed by an exactly-one rule: a telemetry reading targets exactly one of `tank_id` or `installation_id`, and a purity analysis targets exactly one of `fill_lot_id` or `blend_order_id` as selected by its `subject_type`; supplying both sides or neither side is a well-formedness violation rejected with `ERR_INVALID_REQUEST`.

### 2.10. Cross-Aggregate Cascades, Versioning, and Volume Conservation

Many operations in this domain mutate more than one aggregate. Whenever a single operation touches several resources — a lot recall quarantining cylinders and holding rentals, a billing post moving a customer onto credit hold and pausing installations, a driver losing certification and shedding routes — every resource touched by the operation, including resources touched only by a cascade, has its `updated_at` refreshed and its `version` incremented by 1. The server performs these reconciliations immediately as part of the triggering operation; no lazy transitions occur on later reads.

Tank liquid accounting follows a strict conservation invariant, referred to in this document as the volume invariant. Starting a fill reserves the estimated draw against the tank's `reserved_liters`; completing a fill releases that reservation in full and adds the measured actual draw to `drawn_liters`; venting a lot undoes whatever the lot had done — restoring the reservation in full when the fill had only started, or subtracting the actual draw back out of `drawn_liters` when the fill had completed. Under every path, the liquid a tank is accountable for is exactly its latest telemetry level minus the physical draws not yet reflected in a newer reading.

## 3. Business Logic & Workflows

### 3.1. Plant Registry, Tank Commissioning, and Liquid Telemetry

A `PlantManager` registers a production plant by supplying a `plant_name`. A new plant enters `OPERATING` status and thereafter alternates between `OPERATING` and `MAINTENANCE_SHUTDOWN` through a status-setting action carrying a `target_status`. While a plant is in `MAINTENANCE_SHUTDOWN`, all four production transitions — starting a fill, completing a fill, starting a blend, and completing a blend — are rejected with `ERR_PLANT_NOT_OPERATING`; returning the plant to `OPERATING` re-enables them. A status request naming a target unreachable from the plant's current state is rejected with `ERR_INVALID_REQUEST`, and each successful transition increments the plant's `version` by 1. The plant list supports filtering by `status`.

Under each plant, cryogenic storage tanks are registered with the owning `plant_id`, a `product_code` drawn from `O2`, `N2`, `AR`, `CO2`, `H2`, or `HE`, a `capacity_liters` greater than zero, an `initial_level_liters` between zero and capacity inclusive, and an informational `reorder_point_liters` low-level threshold, likewise between zero and capacity inclusive. Registration seeds an `INITIAL_LOAD` telemetry reading measured at the creation clock time with `measured_level_liters` equal to the supplied initial level; the tank enters `IN_SERVICE` with `reserved_liters` at zero, `drawn_liters` at zero, and its `low_level_flag` computed. A tank's `status` moves between `IN_SERVICE`, `MAINTENANCE`, and `QUARANTINED` under `PlantManager` control: leaving `IN_SERVICE` for either non-service state is refused with `ERR_FILL_LOT_INVALID_STATE` while any fill lot on the tank is in `FILLING` or `AWAITING_ANALYSIS`, and while a tank is in `MAINTENANCE` or `QUARANTINED`, starting a fill against it is rejected with `ERR_TANK_NOT_IN_SERVICE`. Returning to `IN_SERVICE` from either state is always permitted, and every transition increments the tank's `version`. Updating a tank's `reorder_point_liters` is an OCC-protected configuration write (see §2.7) that recomputes `low_level_flag` and increments `version`. The tank list supports filtering by `plant_id`, `status`, and `product_code`.

Liquid telemetry is recorded by a `ProductionOperator` or `LogisticsCoordinator`. Each reading carries exactly one of `tank_id` or `installation_id` (see §2.9), a `measured_level_liters` between zero and the owner's capacity inclusive, a `measured_at` instant that must not be later than the logical clock (future-dated readings are rejected with `ERR_TELEMETRY_FUTURE_DATED`), and a `source` of `IOT_SENSOR`, `MANUAL_DIP`, `INITIAL_LOAD`, or `SYSTEM_REPLENISHMENT`; the server stamps `recorded_by_user_id` from the caller's header. The owner's current level is a projection over its readings: the governing reading is the one with the greatest `measured_at`, with ties broken in favor of the later `created_at` — a later-recorded reading wins an equal `measured_at`. A late-arriving reading whose `measured_at` is earlier than the current governing reading's changes nothing. For a storage tank, `current_level_liters` is the governing reading's level minus `drawn_liters`, recomputed on every reading and on every fill or blend draw; whenever a new reading becomes the governing one, `drawn_liters` resets to zero, because the physical draw is now reflected in the measurement. A bulk installation has no draws: its `current_level_liters` is simply the governing reading's level. A tank's `low_level_flag` is true exactly when `current_level_liters` is less than or equal to `reorder_point_liters`, and is recomputed whenever the current level changes.

When a reading posted against a bulk installation leaves the installation's current level at or below its reorder point and no replenishment order is currently `PENDING` for it, the system automatically creates a replenishment order — quantity computed per §3.8, delivery scheduled 24 hours after the current clock instant — and increments the installation's `version`. The telemetry list supports filtering by `tank_id`, `installation_id`, and `source`, providing reverse reachability for both polymorphic targets.

### 3.2. Cylinder Fleet Registry and Hydrostatic Compliance

A `ProductionOperator` registers a cylinder asset with a `serial_number`, a `size_code` of `SMALL`, `STANDARD`, or `LARGE`, a `service_gas` dedicating the cylinder to one of the six product gases, and a `last_hydro_date` recording its most recent passed hydrostatic test. Serial numbers are globally unique across every cylinder ever registered, including cylinders later marked `LOST` or `RETIRED`; a duplicate is rejected with `ERR_DUPLICATE_CYLINDER_SERIAL`. The cylinder's `water_capacity_liters` is derived from its size — 10 liters for `SMALL`, 50 for `STANDARD`, 100 for `LARGE` — and any client-supplied value is ignored. A new cylinder enters `IN_STOCK` with both `current_fill_lot_id` and `last_fill_lot_id` null.

Hydrostatic compliance is a second, independent derived dimension on every cylinder, evaluated against the logical clock and never stored in the cylinder's `status`. The `hydro_due_date` is computed by adding the retest interval for the cylinder's `service_gas` to its `last_hydro_date` — 6 months for `CO2`, 12 months for every other gas — with the day clamped to the target month's last day when the computed day does not exist in that month. The `hydro_status` is then `OVERDUE` when the clock date is strictly after the due date, `DUE_SOON` when the due date is today or up to 30 days in the future, and `COMPLIANT` when it is more than 30 days away. A cylinder due exactly today is `DUE_SOON` and remains fillable and rentable; only `OVERDUE` blocks, and the gate applies at exactly two moments — assignment into a fill lot and rental checkout — where an overdue cylinder is rejected with `ERR_HYDRO_RETEST_OVERDUE`.

A `ProductionOperator` records a hydrostatic retest by supplying a `test_date` and a `result` of `PASS` or `FAIL`; the cylinder must be `IN_STOCK` or `QUARANTINED`, otherwise the request is rejected with `ERR_CYLINDER_NOT_AVAILABLE`. A passed retest sets `last_hydro_date` to the test date, recomputes `hydro_due_date`, and leaves a quarantined cylinder in `QUARANTINED` — release is a separate quality action — while a failed retest drives the cylinder into `QUARANTINED`; either way the cylinder's `version` increments. A `QualityManager` may release a quarantined cylinder back to `IN_STOCK`, but only when its `current_fill_lot_id` is null or references a lot in `VENTED` or `RECALLED` state; otherwise the release is rejected with `ERR_CYLINDER_NOT_AVAILABLE`. A successful release clears `current_fill_lot_id` and increments `version`. Finally, a `QualityManager` may decommission an in-plant cylinder with a `disposition` of `LOST` or `RETIRED`, permitted only from `IN_STOCK` or `QUARANTINED`; both dispositions are terminal states for the asset. The cylinder list supports filtering by `status`, `service_gas`, `current_fill_lot_id`, and `last_fill_lot_id`.

### 3.3. Fill Lot Production and Tank Volume Conservation

A fill lot plans a production run against one storage tank. A `ProductionOperator` plans a lot with a `tank_id`, a `product_code`, and a `target_fill_pressure_bar` greater than zero; the lot's `product_code` must equal the tank's stored product, otherwise creation is rejected with `ERR_PRODUCT_SERVICE_MISMATCH`. A new lot enters `PLANNED` with `draw_estimate_liters` at zero until cylinders are assigned, and `draw_actual_liters` null until the fill completes.

With the lot still `PLANNED`, a `ProductionOperator` assigns cylinders into it one at a time by supplying a `cylinder_id`. Assignment is refused with `ERR_FILL_LOT_INVALID_STATE` when the lot is not `PLANNED`, with `ERR_CYLINDER_NOT_AVAILABLE` when the cylinder is not `IN_STOCK`, with `ERR_HYDRO_RETEST_OVERDUE` when the cylinder is hydro-overdue at the clock date, and with `ERR_PRODUCT_SERVICE_MISMATCH` when the cylinder's `service_gas` differs from the lot's `product_code`. A successful assignment moves the cylinder from `IN_STOCK` to `RESERVED`, sets its `current_fill_lot_id` to the lot, recomputes the lot's `draw_estimate_liters`, and increments both the cylinder's and the lot's `version`.

The estimated draw follows the provisional variant of the fill-draw rule: each cylinder reserved into the lot contributes its `water_capacity_liters` multiplied by the difference between the lot's `target_fill_pressure_bar` and a standard residual of 5 bar, divided by 100; once at least one cylinder is assigned, a line loss of 2 liters is added to the sum, and with no cylinders assigned the estimate is zero. Rounding to 2 decimal places, round half up, is applied to the final sum only. The estimate is recomputed on every assignment into the lot and on every release out of it.

Starting the fill is the reservation step. It requires the lot's plant to be `OPERATING` (else `ERR_PLANT_NOT_OPERATING`), the tank to be `IN_SERVICE` (else `ERR_TANK_NOT_IN_SERVICE`), at least one cylinder `RESERVED` into the lot (else `ERR_LOT_HAS_NO_CYLINDERS`), and sufficient headroom: the tank's `current_level_liters` minus its `reserved_liters` must be greater than or equal to the lot's `draw_estimate_liters` plus a minimum tank reserve of 100 liters, with equality allowed; otherwise the start is rejected with `ERR_TANK_LEVEL_TOO_LOW`. On success the lot moves from `PLANNED` to `FILLING`, the tank's `reserved_liters` increases by the estimated draw, `low_level_flag` is recomputed, and both the lot's and the tank's `version` increment.

Completing the fill supplies the measured per-cylinder residual pressures as `measured_residuals`, a list pairing each `cylinder_id` with its observed `residual_pressure_bar`. The plant must be `OPERATING` and the lot must be `FILLING`, else the request is rejected with `ERR_PLANT_NOT_OPERATING` or `ERR_FILL_LOT_INVALID_STATE` respectively. The server now computes the final variant of the fill draw: identical to the provisional rule except that each cylinder's measured residual pressure replaces the 5-bar standard. The gap matters — a lot of two `STANDARD` cylinders filled to a 200-bar target draws 197.0 liters provisionally, but 187.0 liters when each cylinder's measured residual is 15 bar. Completion moves the lot from `FILLING` to `AWAITING_ANALYSIS`, subtracts the estimated draw from the tank's `reserved_liters`, adds the actual draw to the tank's `drawn_liters`, recomputes the tank's `current_level_liters` and `low_level_flag` — reconciling the provisional reservation to the final actual — stores the actual in `draw_actual_liters`, stamps `completed_by_user_id` from the acting operator's header, and increments both the lot's and the tank's `version`.

A lot whose analysis failed can be reworked. The rework action requires the lot to be `ANALYSIS_FAILED` (else `ERR_FILL_LOT_INVALID_STATE`) and the plant to be `OPERATING` (else `ERR_PLANT_NOT_OPERATING`); it returns the lot to `FILLING` and moves every cylinder still linked to the lot through `current_fill_lot_id` from `QUARANTINED` back to `RESERVED`. No tank re-reservation occurs: the failed fill's liquid stays drawn, and the rework re-pressurizes the same cylinders. The lot's and each cylinder's `version` increment.

Venting abandons a lot and is the volume invariant's compensating path. A lot may be vented from `PLANNED`, `FILLING`, `AWAITING_ANALYSIS`, or `ANALYSIS_FAILED` — from any other state the request is rejected with `ERR_FILL_LOT_INVALID_STATE` — and venting is terminal, landing the lot in `VENTED`. The compensation depends on how far the lot progressed: a lot vented from `PLANNED` adjusts nothing on the tank, since nothing was reserved yet; a lot vented from `FILLING` has the full estimated draw subtracted back out of the tank's `reserved_liters`, restoring the reservation exactly; a lot vented from `AWAITING_ANALYSIS` or from `ANALYSIS_FAILED` has the actual draw subtracted back out of the tank's `drawn_liters`, reversing the physical draw, with `current_level_liters` and `low_level_flag` recomputed. In every case the lot's linked cylinders — `RESERVED` ones, or `QUARANTINED` ones when the lot had failed — return to `IN_STOCK` with their `current_fill_lot_id` cleared.

A released lot can later be recalled by a `QualityManager`; the lot must be `RELEASED`, otherwise the recall is rejected with `ERR_FILL_LOT_INVALID_STATE`. Recall is terminal — the lot lands in `RECALLED` — and fires a four-link cascade: every cylinder whose `last_fill_lot_id` equals the recalled lot and whose status is `FILLED` or `ON_RENT` moves to `QUARANTINED`; every rental in `ACTIVE` or `OVERDUE` whose cylinder was just quarantined moves to `RECALL_HOLD`; and every customer account owning a rental that just entered `RECALL_HOLD` has its `recall_flag` set to true. The lot's, every touched cylinder's, every touched rental's, and every flagged customer's `version` each increment by 1. The fill lot list supports filtering by `tank_id` and `status`.

### 3.4. Laboratory Purity Analysis, Quality Override, and Recall Consequences

Laboratory work is performed by a `LabAnalyst` and is deliberately segregated from production work. Recording an analysis requires a `subject_type` of `FILL_LOT` or `BLEND_ORDER`, which selects which of `fill_lot_id` or `blend_order_id` must be present — exactly one, per §2.9 — plus a `readings` array. The subject must currently sit in `AWAITING_ANALYSIS`; analyzing anything else is rejected with `ERR_ANALYSIS_INVALID_STATE`. Segregation of duties is enforced by identity: the analyst's `X-User-ID`, stamped onto the analysis as `recorded_by_user_id`, must differ from the subject's `completed_by_user_id` on a fill lot or `blended_by_user_id` on a blend order, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

For a fill lot, each entry in `readings` pairs an `analyte` with a `reading_ppm`, compared against the grade limits of the lot's product at 2 decimal places: for `O2`, carbon monoxide limited to 10 ppm and water to 20 ppm; for `N2`, oxygen 10 ppm and water 10 ppm; for `AR`, oxygen 10 ppm and water 10 ppm; for `CO2`, water 10 ppm and total hydrocarbons 20 ppm; for `H2`, oxygen 5 ppm and water 10 ppm; for `HE`, oxygen 5 ppm and water 5 ppm. An analyte with no limit defined for the lot's grade is rejected with `ERR_INVALID_REQUEST`. Each reading bands independently: a reading at or below its limit is OK, a reading above the limit but at or below one and a half times the limit is MARGINAL, and a reading above one and a half times the limit is FAIL — equality at the limit is OK, and equality at one-and-a-half-times the limit is MARGINAL. The analysis `result` is the worst band across all readings.

For a blend order, each entry in `readings` pairs a `product_code` with an `actual_pct`. The deviation of each component is the absolute difference between its measured percentage and its `target_pct`, rounded half-up to 2 decimal places. A deviation at or below the component's `tolerance_pct` is OK; a deviation above tolerance but at or below twice the tolerance is MARGINAL; a deviation above twice the tolerance is FAIL — equality at tolerance is OK, and equality at twice the tolerance is MARGINAL. A reading naming a product that is not a blend component, or a component with no reading at all, bands as FAIL. Again the `result` is the worst band across all components.

The result drives the subject. A `PASS` releases the subject: a fill lot moves from `AWAITING_ANALYSIS` to `RELEASED`, and every cylinder reserved into it becomes `FILLED` with its `current_fill_lot_id` cleared and its `last_fill_lot_id` stamped with the lot's identity as permanent provenance — that provenance is set at release and never cleared, and it is what recall targeting later reads. A `MARGINAL` result leaves the subject in `AWAITING_ANALYSIS` pending a quality decision. A `FAIL` moves a fill lot to `ANALYSIS_FAILED` and drives every cylinder reserved into it to `QUARANTINED` with the lot link kept so that rework can find them, or moves a blend order to `REWORK`. These transitions increment the lot's or blend's `version` and every affected cylinder's `version`.

A `QualityManager` may override a marginal analysis. The analysis must be in `RECORDED` status with a `result` of `MARGINAL` — anything else is rejected with `ERR_ANALYSIS_INVALID_STATE` — and the manager's identity must differ from the analysis's `recorded_by_user_id`, otherwise the override is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. A successful override moves the analysis from `RECORDED` to `OVERRIDDEN` (its terminal state), rewrites the `result` to `PASS_OVERRIDE`, stamps `overridden_by_user_id`, releases the subject exactly as a `PASS` would — a waiting fill lot releases with its cylinders filled, a waiting blend order releases — and increments both the analysis's and the subject's `version`. The analysis list supports filtering by `fill_lot_id`, `blend_order_id`, and `result`.

### 3.5. Customer Accounts and Cylinder Rental Billing

A `BillingClerk` opens a customer account with an `account_name`, a `billing_variant` of `CALENDAR_DAY` or `GRACE_PERIOD`, a `free_days` count of zero or more — deducted from the billable base under `GRACE_PERIOD` and ignored under `CALENDAR_DAY` — and a `credit_limit_cents` greater than zero. A new account is `ACTIVE` with `outstanding_balance_cents` at zero and `recall_flag` false. Credit terms may later be updated — optionally a new `credit_limit_cents`, `free_days`, or `billing_variant` — through the OCC-protected account write described in §2.7, which increments the account's `version`.

Payments reduce the balance: a payment carries an `amount_cents` greater than zero, subtracts it from `outstanding_balance_cents`, and may drive the balance to zero but never below it — an amount exceeding the outstanding balance is rejected with `ERR_INVALID_REQUEST`. After every payment, and after every charge posting anywhere in the system, the account's credit standing is re-evaluated under a hysteresis rule. An `ACTIVE` account whose outstanding balance becomes strictly greater than its credit limit moves to `CREDIT_HOLD` — equality at the limit does not trigger the hold. A `CREDIT_HOLD` account returns to `ACTIVE` once its balance falls to at most 80% of the credit limit, with that release threshold rounded half-up to whole cents — equality at the release point does release. Between the release threshold and the limit the status is sticky: a held account stays held, an active account stays active. Entering `CREDIT_HOLD` blocks new rentals and new blend orders with `ERR_ACCOUNT_NOT_ACTIVE` and cascades to the customer's bulk installations, moving every `ACTIVE` one to `PAUSED`; leaving the hold does not auto-resume those installations — an operator resumes them explicitly. The customer list supports filtering by `status` and `billing_variant`.

Checking out a cylinder to a customer is a `BillingClerk` action carrying a `customer_id`, a `cylinder_id`, a `daily_rate_cents` greater than zero, and a `planned_days` greater than zero. The customer must be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`), the cylinder must be `FILLED` (else `ERR_CYLINDER_NOT_AVAILABLE`) and not hydro-overdue (else `ERR_HYDRO_RETEST_OVERDUE`), and the credit check must pass: the account's `outstanding_balance_cents` plus the estimated charge — the customer's billing-variant base computed over `planned_days` — must not be strictly greater than `credit_limit_cents`, with equality allowed; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. On success the rental starts `ACTIVE`, the cylinder moves from `FILLED` to `ON_RENT` with a `version` increment, `out_date` is set to the logical clock date, `due_date` is `planned_days` whole days after `out_date`, `billed_through_date` is initialized to `due_date`, and `demurrage_billed_cents` starts at zero.

Returning a cylinder carries a `return_condition` of `OK` or `DAMAGED` and is permitted while the rental is `ACTIVE`, `OVERDUE`, or `RECALL_HOLD`; any other state is rejected with `ERR_RENTAL_NOT_ACTIVE`. The `return_date` is the logical clock date. The final charge closes the rental out: the billing-variant base over the days out, plus demurrage accrued through the return date, minus the `demurrage_billed_cents` already charged by billing runs, floored at zero, and stored in `final_charge_cents`. Days out is the whole-day count from `out_date` to the end date with the end date exclusive; the overdue day count is the whole days from `due_date` to the end date, never below zero. Under `CALENDAR_DAY` the base is the daily rate multiplied by the days out — every out day bills. Under `GRACE_PERIOD` the base is the daily rate multiplied by the days out minus `free_days`, floored at zero — nine days out with three free days bills six days, not nine. The charge is posted to the account's `outstanding_balance_cents`, the credit-hold rule re-evaluates, the rental lands in `RETURNED`, and the cylinder's disposition depends on the path: an `OK` return sends it to `IN_STOCK`, a `DAMAGED` return sends it to `QUARANTINED`, and the return of a `RECALL_HOLD` rental sends it to `QUARANTINED` regardless of the declared condition. The rental's, cylinder's, and customer's `version` each increment.

When a rented cylinder is lost, a `BillingClerk` settles the loss on a rental in `ACTIVE` or `OVERDUE` — any other state is rejected with `ERR_RENTAL_NOT_ACTIVE`. The final charge is the size-keyed loss fee — 15000 cents for `SMALL`, 45000 for `STANDARD`, 80000 for `LARGE` — plus the variant base accrued through the logical clock date, plus demurrage accrued through the clock date, minus the demurrage already billed, floored at zero. The charge posts to the account with the usual credit evaluation, the rental lands in `LOST_SETTLED`, and the cylinder moves from `ON_RENT` to `LOST`, terminal for the asset. Rental, cylinder, and customer versions increment. The rental list supports filtering by `customer_id`, `cylinder_id`, and `status`.

### 3.6. Periodic Billing Runs, Demurrage Accrual, and Credit-Hold Cascades

Demurrage is not charged lazily; it is charged by periodic billing runs operated by a `BillingClerk`. Opening a run supplies a `period_start` and a `period_end`, with the start not after the end (else `ERR_INVALID_REQUEST`); demurrage accrues through `period_end` inclusive. A new run is `DRAFT`.

Finalizing a run — permitted only from `DRAFT`, else `ERR_BILLING_RUN_INVALID_STATE` — performs two sweeps. First, the overdue checkpoint: every rental still `ACTIVE` whose `due_date` is strictly earlier than the logical clock date moves to `OVERDUE`. This finalize sweep is the only place rentals go overdue; reads never transition them lazily. Second, charge computation: every rental in `ACTIVE` or `OVERDUE` whose `due_date` is earlier than `period_end` accrues demurrage over a window of overdue day indices. Overdue day index 1 is the day after `due_date`. The window's first index is one more than the whole-day count from the rental's `due_date` to its `billed_through_date`, and its last index is the whole-day count from `due_date` to `period_end`; a rental whose window is empty or inverted accrues nothing in this run. Each overdue day bills by tier: indices 1 through 7 at one times the daily rate, indices 8 through 30 at one and a half times, and index 31 onward at twice the daily rate. Each tier segment is rounded half-up to whole cents on its own — segment days times daily rate times multiplier — and a rental's charge line is the sum of its already-rounded segments, never rounded again. The run's `charge_lines` carry one entry per accrued rental with its `rental_id`, `customer_id`, `overdue_days`, and `demurrage_cents`, and `total_charges_cents` is the plain sum of the per-line values with no further rounding — sum-then-round is forbidden, so two rentals at 333 cents per day, each eight days overdue, total 2831 plus 2831 equals 5662 cents, never 5661. Every accrued rental has its `billed_through_date` advanced to `period_end` and its `demurrage_billed_cents` increased by its line amount; the run's and every swept rental's `version` increment.

Posting a run — permitted only from `FINALIZED`, else `ERR_BILLING_RUN_INVALID_STATE` — lands it in `POSTED`, terminal, and fires the financial cascade. Each customer's `outstanding_balance_cents` increases by the sum of that customer's lines; any customer thereby pushed strictly over its credit limit moves to `CREDIT_HOLD`, and each customer newly on hold has all of its `ACTIVE` bulk installations moved to `PAUSED`. Posting also clears `recall_flag` on any customer that no longer has any rental in `RECALL_HOLD` — that flag is cleared nowhere else. The run's, every touched customer's, and every touched installation's `version` increment. The billing run list supports filtering by `status`.

### 3.7. Driver Certification and Hazmat Route Dispatch

A `LogisticsCoordinator` registers a driver with a `driver_name`, a `cdl_class` of `A` or `B`, a `hazmat_endorsements` list in which each entry pairs an `endorsement_class` — one of `FLAMMABLE_GAS`, `NONFLAMMABLE_GAS`, `OXIDIZER`, `POISON_GAS`, or `CRYOGENIC` — with an `expiry_date`, and a `medical_card_expiry`. A new driver is `QUALIFIED` when the medical card and every endorsement expire on or after the logical clock date, and `CERT_EXPIRED` otherwise.

Certification maintenance is continuous. Updating a driver's `medical_card_expiry` or `hazmat_endorsements` such that any expiry falls earlier than the logical clock date flips the driver from `QUALIFIED` to `CERT_EXPIRED` and cascades: every route of that driver in `DRIVER_ASSIGNED` or `DISPATCHED` returns to `PLANNED` with its `driver_id` cleared to null, and the driver's and each touched route's `version` increment. Suspension by a coordinator moves a `QUALIFIED` driver to `SUSPENDED` with exactly the same route-unassignment cascade. Reinstatement — from `SUSPENDED` or from `CERT_EXPIRED` back to `QUALIFIED` — requires the medical card and every endorsement to expire on or after the clock date, and is rejected with `ERR_DRIVER_CERT_EXPIRED` when any credential is still expired.

A hazmat delivery route is planned with a `route_date`, a `window_start_hour` between 0 and 23 inclusive, a `window_end_hour` between 1 and 24 inclusive and strictly greater than the start — together defining a half-open window that includes the start hour and excludes the end hour — and an ordered `stops` list, at least one stop, where each stop carries a `stop_name` and a `hazmat_classes` list drawn from the endorsement-class enum. A new route is `PLANNED` with `driver_id` null.

Assigning a driver supplies a `driver_id` and runs the full safety gate against the route. The route must be `PLANNED` (else `ERR_ROUTE_INVALID_STATE`) and the driver `QUALIFIED` (else `ERR_DRIVER_NOT_QUALIFIED`). Coverage is evaluated over the union of all stops' hazmat classes — an empty union always passes: a required class for which the driver holds no endorsement at all is rejected with `ERR_HAZMAT_ENDORSEMENT_MISSING`; a class whose only covering endorsement expires before the `route_date` is rejected with `ERR_DRIVER_CERT_EXPIRED`, as is a medical card expiring before the `route_date`. Finally, the temporal check: the driver must hold no other route in `DRIVER_ASSIGNED` or `DISPATCHED` on the same `route_date` whose half-open window overlaps this one, where windows that merely touch — one ending exactly when the other begins — do not overlap; a genuine overlap is rejected with `ERR_DRIVER_ROUTE_OVERLAP`. A successful assignment sets `driver_id`, moves the route to `DRIVER_ASSIGNED`, and increments its `version`.

Dispatch re-validates against the current moment: the route must be `DRIVER_ASSIGNED` (else `ERR_ROUTE_INVALID_STATE`), and the driver must still be `QUALIFIED` with a medical card unexpired at the current clock date, otherwise the dispatch is rejected with `ERR_DRIVER_CERT_EXPIRED`. Success moves the route to `DISPATCHED` with a `version` increment. Completion is permitted only from `DISPATCHED` (else `ERR_ROUTE_INVALID_STATE`) and may be performed by a `LogisticsCoordinator` or by the `Driver` whose identity equals the route's `driver_id` — a different driver is rejected with `ERR_UNAUTHORIZED_ROLE`; the route lands in `COMPLETED`, terminal. Cancellation is a coordinator-only action permitted from `PLANNED`, `DRIVER_ASSIGNED`, or `DISPATCHED` — from a terminal state it is rejected with `ERR_ROUTE_INVALID_STATE`, and a `Driver` attempting any cancellation is rejected with `ERR_UNAUTHORIZED_ROLE`; the route lands in `CANCELLED`, terminal. The route list supports filtering by `driver_id`, `status`, and `route_date`; the driver list by `status`.

### 3.8. Bulk Customer Installations and Replenishment

Beyond cylinders, the plant services customer-site bulk tanks. A `PlantManager` proposes an installation with a `customer_id`, a `product_code`, a `capacity_liters` greater than zero, an `initial_level_liters` between zero and capacity inclusive, a `reorder_point_liters` auto-replenishment trigger level between zero and capacity inclusive, and a `max_order_qty_liters` customer cap per delivery, greater than zero. Registration seeds an `INITIAL_LOAD` telemetry reading measured at the creation clock time, and the installation enters `PROPOSED`.

The installation lifecycle is driven by status actions carrying a `target_status`: from `PROPOSED` to `INSTALLED`, from `INSTALLED` to `ACTIVE`, from `ACTIVE` to `PAUSED`, from `PAUSED` back to `ACTIVE`, and from `INSTALLED`, `ACTIVE`, or `PAUSED` to `DECOMMISSIONED`, which is terminal. A request naming a target unreachable from the current state is rejected with `ERR_INSTALLATION_INVALID_STATE`. Resuming from `PAUSED` to `ACTIVE` additionally requires the owning customer to be `ACTIVE`, otherwise the resume is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. Decommissioning cancels every `PENDING` replenishment order of the installation. While an installation is `PAUSED`, creating a new replenishment order against it is rejected with `ERR_INSTALLATION_INVALID_STATE` — only `ACTIVE` installations accept orders. The credit cascade lands here too: when a customer enters `CREDIT_HOLD`, every one of its `ACTIVE` installations moves to `PAUSED`, and a later release from the hold does not resume them. Each transition increments the installation's `version`.

A `LogisticsCoordinator` creates a replenishment order by supplying an `installation_id`, a `scheduled_delivery_at` instant, and the OCC field `expected_installation_version` (§2.7). Spacing is enforced against delivery history: the scheduled instant must be at least 24 hours after the `delivered_at` of the installation's most recently delivered order; with no prior delivered order, there is no spacing constraint, and a violation is rejected with `ERR_REPLENISHMENT_WINDOW_CONFLICT`. The order quantity is fixed at creation as `requested_qty_liters`, the smallest of three values — the installation's remaining capacity (its capacity minus its current level), the 20000-liter truck capacity, and the installation's `max_order_qty_liters`; a result of zero or less is rejected with `ERR_INVALID_REQUEST`. Creating an order supersedes any existing `PENDING` order on the same installation: the older order moves to `SUPERSEDED` with its `superseded_by_order_id` pointing at the new order, and the installation's `version` increments. The new order starts `PENDING`.

Marking an order delivered — permitted only from `PENDING`, else `ERR_REPLENISHMENT_INVALID_STATE` — lands the order in `DELIVERED`, terminal, stamps `delivered_at` with the logical clock instant, and posts a system telemetry reading against the installation: `source` `SYSTEM_REPLENISHMENT`, `measured_level_liters` equal to the installation's current level plus the delivered quantity, capped at capacity, `measured_at` equal to `delivered_at`. The installation's `current_level_liters` then recomputes from that reading per the projection rule of §3.1, and both the order's and the installation's `version` increment. Cancelling an order — also only from `PENDING`, or automatically through the decommission cascade — lands it in `CANCELLED`. Recall from §3.1 that low telemetry against an installation at or below its reorder point with no `PENDING` order outstanding triggers automatic order creation with delivery scheduled 24 hours after the clock instant. The installation list supports filtering by `customer_id` and `status`; the order list by `installation_id` and `status`.

### 3.9. Custom Gas Mixture Blending

Custom gas mixtures are quoted and produced as blend orders. A `BillingClerk` quotes a blend with a `customer_id`, a `batch_qty_liters` greater than zero, and a `components` array in which each component carries a `product_code`, a `target_pct`, a `tolerance_pct` greater than zero, and a `unit_cost_cents_per_liter` of zero or more. The customer must be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`). Composition rules are strict: at least two components are required, and the `target_pct` values — each taken at 2 decimal places — must sum to exactly 100.00; any breach is rejected with `ERR_BLEND_COMPONENT_SUM_INVALID`.

The price quote is computed once at creation in a pinned evaluation order that breaks the apparent circle between cost, fee, and total. First, `component_cost_cents` is the sum over components of each component's percentage of the batch quantity multiplied by its unit cost — that is, `target_pct` divided by 100, times `batch_qty_liters`, times `unit_cost_cents_per_liter` — with each component's contribution rounded half-up to whole cents before summing. Second, `service_fee_cents` is keyed only on that component cost, never on the total: a cost below 100000 cents pays a flat 15000 cents; a cost from 100000 up to and including 499999 cents pays 12% of the cost rounded half-up to whole cents; a cost of 500000 cents or more pays 10% of the cost rounded half-up to whole cents. Third, `total_price_cents` is the component cost plus the service fee. A new blend order enters `DRAFT`.

A `QualityManager` approves a quoted blend, moving it from `DRAFT` to `APPROVED` — from any other state the approval is rejected with `ERR_BLEND_ORDER_INVALID_STATE` — with a `version` increment. Production then begins with the start-blend action, permitted from `APPROVED` or from `REWORK` (else `ERR_BLEND_ORDER_INVALID_STATE`) and only while the plant of the selected tanks is `OPERATING` (else `ERR_PLANT_NOT_OPERATING`). The server selects a source tank per component: a tank is eligible when it stores the component's `product_code`, is `IN_SERVICE`, and has headroom — `current_level_liters` minus `reserved_liters` — of at least the required quantity plus the 100-liter minimum reserve, where the required quantity is the component's percentage of the batch quantity rounded half-up to 2 decimal places. Eligible tanks are ranked by `current_level_liters` descending with ties broken by earliest `created_at`. An empty eligible pool for any component rejects the start with `ERR_TANK_LEVEL_TOO_LOW`, and all components must resolve before any state change occurs. The chosen tank is stamped onto each component as `selected_tank_id`, the blend moves to `BLENDING`, and its `version` increments.

Completing the blend requires the blend to be `BLENDING` (else `ERR_BLEND_ORDER_INVALID_STATE`) and the plant `OPERATING` (else `ERR_PLANT_NOT_OPERATING`). For each component, the selected tank's `drawn_liters` increases by the component's required quantity, with `current_level_liters` and `low_level_flag` recomputed per tank; the server stamps `blended_by_user_id` from the acting operator, moves the blend to `AWAITING_ANALYSIS`, and increments the blend's and every selected tank's `version`. The blend is then graded by the laboratory per §3.4: a `PASS` (or an overridden `PASS_OVERRIDE`) releases it to `RELEASED`, terminal; a `FAIL` sends it to `REWORK`, from which start-blend may be run again with freshly re-selected tanks — drawn component quantities are not returned to their tanks, since the off-spec blend is retained for re-blending; a `MARGINAL` leaves it awaiting a quality override. The blend order list supports filtering by `customer_id` and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions, configuration writes, and actions — return `200 OK`. The table below is a routing summary only: request payloads, computed fields, and side effects are specified in the narratives of §2 and §3, and the state-pair names there disambiguate endpoints that share a path shape.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock used for all date arithmetic | PlantManager |
| POST | `/api/plants` | Register a production plant | PlantManager |
| GET | `/api/plants` | List plants | Any |
| GET | `/api/plants/{plantId}` | Get one plant | Any |
| POST | `/api/plants/{plantId}/set-status` | Transition plant between OPERATING and MAINTENANCE_SHUTDOWN | PlantManager |
| POST | `/api/tanks` | Register a cryogenic storage tank; seeds an INITIAL_LOAD reading | PlantManager |
| GET | `/api/tanks` | List tanks with filters | Any |
| GET | `/api/tanks/{tankId}` | Get one tank | Any |
| PATCH | `/api/tanks/{tankId}` | Update tank thresholds under OCC | PlantManager |
| POST | `/api/tanks/{tankId}/set-status` | Transition tank among IN_SERVICE, MAINTENANCE, QUARANTINED | PlantManager |
| POST | `/api/telemetry-readings` | Append a level reading for a tank or a bulk installation | ProductionOperator, LogisticsCoordinator |
| GET | `/api/telemetry-readings` | List readings with filters | Any |
| GET | `/api/telemetry-readings/{readingId}` | Get one reading | Any |
| POST | `/api/cylinders` | Register a cylinder asset | ProductionOperator |
| GET | `/api/cylinders` | List cylinders with filters | Any |
| GET | `/api/cylinders/{cylinderId}` | Get one cylinder | Any |
| POST | `/api/cylinders/{cylinderId}/hydro-retests` | Record a hydrostatic retest; PASS extends the due date | ProductionOperator |
| POST | `/api/cylinders/{cylinderId}/release-quarantine` | Release a quarantined cylinder back to stock | QualityManager |
| POST | `/api/cylinders/{cylinderId}/decommission` | Retire or mark lost an in-plant cylinder | QualityManager |
| POST | `/api/fill-lots` | Plan a fill lot against a storage tank | ProductionOperator |
| GET | `/api/fill-lots` | List fill lots with filters | Any |
| GET | `/api/fill-lots/{fillLotId}` | Get one fill lot | Any |
| POST | `/api/fill-lots/{fillLotId}/cylinders` | Assign a cylinder into a PLANNED lot | ProductionOperator |
| POST | `/api/fill-lots/{fillLotId}/start-fill` | Begin filling; reserves the estimated draw on the tank | ProductionOperator |
| POST | `/api/fill-lots/{fillLotId}/complete-fill` | Complete the fill with measured per-cylinder residuals | ProductionOperator |
| POST | `/api/fill-lots/{fillLotId}/rework` | Rework a failed lot; de-quarantines its cylinders | ProductionOperator |
| POST | `/api/fill-lots/{fillLotId}/vent` | Vent a lot; restores tank reservation or drawn volume exactly | ProductionOperator |
| POST | `/api/fill-lots/{fillLotId}/recall` | Recall a RELEASED lot; quarantines cylinders, holds rentals, flags customers | QualityManager |
| POST | `/api/purity-analyses` | Record a lab analysis on a fill lot or blend order | LabAnalyst |
| GET | `/api/purity-analyses` | List analyses with filters | Any |
| GET | `/api/purity-analyses/{analysisId}` | Get one analysis | Any |
| POST | `/api/purity-analyses/{analysisId}/override` | Override a MARGINAL result to PASS_OVERRIDE | QualityManager |
| POST | `/api/customers` | Open a customer account | BillingClerk |
| GET | `/api/customers` | List customers | Any |
| GET | `/api/customers/{customerId}` | Get one customer | Any |
| PATCH | `/api/customers/{customerId}` | Update credit terms under OCC | BillingClerk |
| POST | `/api/customers/{customerId}/payments` | Apply a payment against the outstanding balance | BillingClerk |
| POST | `/api/rentals` | Check out a FILLED cylinder to a customer | BillingClerk |
| GET | `/api/rentals` | List rentals with filters | Any |
| GET | `/api/rentals/{rentalId}` | Get one rental | Any |
| POST | `/api/rentals/{rentalId}/return` | Return a rented cylinder; computes and posts the final charge | BillingClerk |
| POST | `/api/rentals/{rentalId}/settle-loss` | Settle a lost rented cylinder: loss fee plus accrued charges | BillingClerk |
| POST | `/api/drivers` | Register a driver with hazmat endorsements | LogisticsCoordinator |
| GET | `/api/drivers` | List drivers | Any |
| GET | `/api/drivers/{driverId}` | Get one driver | Any |
| PATCH | `/api/drivers/{driverId}` | Update certifications; expired certs flip to CERT_EXPIRED and unassign routes | LogisticsCoordinator |
| POST | `/api/drivers/{driverId}/set-status` | Suspend or reinstate a driver (reinstatement revalidates certs) | LogisticsCoordinator |
| POST | `/api/routes` | Plan a hazmat delivery route | LogisticsCoordinator |
| GET | `/api/routes` | List routes with filters | Any |
| GET | `/api/routes/{routeId}` | Get one route | Any |
| POST | `/api/routes/{routeId}/assign-driver` | Assign a qualified, cert-covered, non-overlapping driver | LogisticsCoordinator |
| POST | `/api/routes/{routeId}/dispatch` | Dispatch an assigned route; revalidates certs against the clock | LogisticsCoordinator |
| POST | `/api/routes/{routeId}/set-status` | Complete (coordinator or assigned driver) or cancel (coordinator only) | LogisticsCoordinator, Driver |
| POST | `/api/bulk-installations` | Propose a customer-site bulk tank; seeds an INITIAL_LOAD reading | PlantManager |
| GET | `/api/bulk-installations` | List installations with filters | Any |
| GET | `/api/bulk-installations/{installationId}` | Get one installation | Any |
| POST | `/api/bulk-installations/{installationId}/set-status` | Drive the installation lifecycle; decommission cancels pending orders | PlantManager |
| POST | `/api/replenishment-orders` | Create a replenishment order under installation OCC; supersedes any pending order | LogisticsCoordinator |
| GET | `/api/replenishment-orders` | List replenishment orders with filters | Any |
| GET | `/api/replenishment-orders/{orderId}` | Get one replenishment order | Any |
| POST | `/api/replenishment-orders/{orderId}/set-status` | Mark delivered (posts a SYSTEM_REPLENISHMENT reading) or cancel | LogisticsCoordinator |
| POST | `/api/blend-orders` | Quote a custom gas mixture; computes cost, fee, and total at creation | BillingClerk |
| GET | `/api/blend-orders` | List blend orders with filters | Any |
| GET | `/api/blend-orders/{blendOrderId}` | Get one blend order | Any |
| POST | `/api/blend-orders/{blendOrderId}/approve` | Quality approval of a quoted blend | QualityManager |
| POST | `/api/blend-orders/{blendOrderId}/start-blend` | Start blending; server selects source tanks per component | ProductionOperator |
| POST | `/api/blend-orders/{blendOrderId}/complete-blend` | Complete blending; draws component quantities from selected tanks | ProductionOperator |
| POST | `/api/billing-runs` | Open a billing run for a period | BillingClerk |
| GET | `/api/billing-runs` | List billing runs | Any |
| GET | `/api/billing-runs/{billingRunId}` | Get one billing run | Any |
| POST | `/api/billing-runs/{billingRunId}/finalize` | Sweep overdue rentals and compute per-line demurrage charges | BillingClerk |
| POST | `/api/billing-runs/{billingRunId}/post` | Post charges to customer balances; triggers the credit-hold cascade | BillingClerk |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the canonical index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM_VALUE | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_PLANT_NOT_OPERATING | 409 |
| ERR_TANK_NOT_IN_SERVICE | 409 |
| ERR_CYLINDER_NOT_AVAILABLE | 409 |
| ERR_FILL_LOT_INVALID_STATE | 409 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_RENTAL_NOT_ACTIVE | 409 |
| ERR_DRIVER_NOT_QUALIFIED | 409 |
| ERR_ROUTE_INVALID_STATE | 409 |
| ERR_INSTALLATION_INVALID_STATE | 409 |
| ERR_BLEND_ORDER_INVALID_STATE | 409 |
| ERR_BILLING_RUN_INVALID_STATE | 409 |
| ERR_ANALYSIS_INVALID_STATE | 409 |
| ERR_REPLENISHMENT_INVALID_STATE | 409 |
| ERR_HYDRO_RETEST_OVERDUE | 422 |
| ERR_PRODUCT_SERVICE_MISMATCH | 422 |
| ERR_HAZMAT_ENDORSEMENT_MISSING | 422 |
| ERR_DRIVER_CERT_EXPIRED | 422 |
| ERR_SEGREGATION_OF_DUTIES_VIOLATION | 403 |
| ERR_TANK_LEVEL_TOO_LOW | 409 |
| ERR_LOT_HAS_NO_CYLINDERS | 409 |
| ERR_DUPLICATE_CYLINDER_SERIAL | 409 |
| ERR_DRIVER_ROUTE_OVERLAP | 409 |
| ERR_REPLENISHMENT_WINDOW_CONFLICT | 409 |
| ERR_BLEND_COMPONENT_SUM_INVALID | 422 |
| ERR_TELEMETRY_FUTURE_DATED | 422 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_STALE_VERSION | 412 |
