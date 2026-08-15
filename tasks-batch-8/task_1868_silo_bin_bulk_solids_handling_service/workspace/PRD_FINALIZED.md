# Silo Bin Bulk Solids Service API — Product Requirements Document

## 1. Introduction

Bulk-solids service contractors operate in a tightly regulated niche: they monitor customers' silos, bins and hoppers, dispatch field crews to diagnose flow problems (bridging, ratholing), perform cleanouts and inspections under permit, retrofit aeration and vibrator hardware, and reconcile everything against contract pricing or capital project budgets. The operational risk surface is unusual — a single silo can simultaneously be a confined-space engulfment hazard, a quality problem when moisture ruins the stored material, a calibration liability when its load-out scale drifts, and a replenishment commitment that the customer is contractually owed. Existing spreadsheet-driven workflows routinely lose track of these interactions, leading to double-booked crews, missed reorder points, and — worst of all — bin entries authorized against inbound deliveries.

This document specifies the Silo Bin Bulk Solids Service API, a back-end service that acts as the single operational system of record for such a contractor. The system models customer sites, their storage vessels, inventory level readings, material quality lab reports, load-out scale calibrations, replenishment orders, service tickets, and the confined-space entry permits that gate any human entry into a vessel. It automates reorder triggering, computes provisional estimates and final invoices with pinned per-line rounding, enforces segregation-of-duties between permit issuers and entrants, and propagates a worst-case flow posture from individual vessels up to the site level so that operations managers see an accurate escalation picture without polling every silo.

The audience for this document is the engineering team that will build the service, the operations leaders who will run it day to day, and the safety officers who must be able to defend every entry-permit decision in an audit. All endpoint paths, state names, error identifiers and field names appearing in this document are contractual.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting principal and `X-User-Role` naming the operational capacity in which they act. The system recognizes exactly four roles: `ServiceManager`, `PlantOperator`, `Technician`, and `SafetyOfficer`. A request that omits either header, or presents a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the targeted endpoint, or that violates entity-backed ownership, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The interpretation of `X-User-ID` varies by role:

- When `X-User-Role` is `ServiceManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `issuer_user_id` on an `EntryPermit` when the acting role is `SafetyOfficer`) but does not compare it to any entity's `id`.
- When `X-User-Role` is `PlantOperator`, `X-User-ID` is the `id` of the acting `CustomerSite`; ownership checks on any resource that references a `CustomerSite` compare the resource's `site_id` foreign-key field to `X-User-ID`. A `PlantOperator` may only post level readings, open service tickets, approve contract-service quotes, receive deliveries, or cancel replenishment orders against its own site.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's `technician_id` foreign-key field to `X-User-ID`. Starting or completing a service ticket requires that the acting technician's `X-User-ID` equal the ticket's `technician_id`.
- When `X-User-Role` is `SafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `issuer_user_id` on any `EntryPermit` the officer issues, but does not compare it to any entity's `id`.

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

List endpoints accept two pagination query parameters. `limit` controls the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many items to skip and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending. The `meta` block of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Vessel & Site Posture Roll-Up

Each `Vessel` carries a computed `flow_posture` field with three values: `NORMAL`, `PENDING_REPLENISHMENT`, and `FLOW_IMPAIRED`. A vessel is `FLOW_IMPAIRED` when its most recent `MaterialQualityReport` breaches either the vessel's moisture limit or the caking threshold; otherwise it is `PENDING_REPLENISHMENT` when at least one open `ReplenishmentOrder` (status `TRIGGERED` or `DISPATCHED`) exists for the vessel; otherwise it is `NORMAL`.

The parent `CustomerSite` then surfaces a worst-case `site_posture` field with values `NORMAL`, `ATTENTION`, and `CRITICAL`. The site is `CRITICAL` if any of its vessels is `FLOW_IMPAIRED`, else `ATTENTION` if any is `PENDING_REPLENISHMENT`, else `NORMAL`. Both `flow_posture` and `site_posture` are recomputed automatically whenever a level reading arrives, a quality report is filed, or a replenishment order is received, cancelled, or voided.

A special safety cascade attaches to this roll-up: when a vessel's `flow_posture` becomes `FLOW_IMPAIRED`, every `EntryPermit` for that vessel whose status is `DRAFT` or `ISSUED` is automatically transitioned to `VOIDED` with `void_reason` set to `AUTO_QUALITY_HAZARD`. The transition is system-initiated; no client call is required.

### 2.5. Load-Out Scale Calibration Posture

Each `Vessel` carries a computed `scale_status` field with values `IN_TOLERANCE` and `OUT_OF_TOLERANCE`. The field starts as `IN_TOLERANCE` when the vessel is created and is rewritten by every subsequent `ScaleCalibration` record. A calibration passes when the absolute value of `error_pct` is at most `tolerance_pct` (the boundary is inclusive); otherwise it fails. A pass sets `scale_status` to `IN_TOLERANCE`; a failure sets it to `OUT_OF_TOLERANCE`. Receiving a replenishment order against a vessel whose `scale_status` is `OUT_OF_TOLERANCE` is rejected with `ERR_SCALE_OUT_OF_TOLERANCE` (HTTP 409) — an out-of-tolerance load-out scale is treated as a hard receiving block.

### 2.6. Common Resource Properties

Primary top-level resources (`CustomerSite`, `Technician`, `Vessel`, `ReplenishmentOrder`, `ServiceTicket`, `EntryPermit`) carry a standard set of system-managed fields:

- `id` — a server-minted UUID, no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits set at creation.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` — an integer that increments on every mutation; used for optimistic concurrency control.

Sub-resources `LevelReading`, `MaterialQualityReport`, and `ScaleCalibration` are immutable measurement records; they carry only `id` and `created_at`. Neither `updated_at` nor `version` is present on those entities.

### 2.7. Precision, Rounding, and Monetary Values

Inventory quantities in tons are stored and returned at 1 decimal place, rounded half up. Average daily usage and remaining-capacity hour values are computed at 2 decimal places, rounded half up. Calibration `error_pct` values are computed at 3 decimal places, rounded half up. Monetary fields (`estimate_cents`, `invoice_labor_cents`, `invoice_mobilization_cents`, `invoice_disposal_cents`, `invoice_subtotal_cents`, `invoice_discount_cents`, `invoice_tax_cents`, `invoice_total_cents`, `capital_threshold_cents`) are integer cents — no fractional cent is ever exposed, and each rounding step uses round half up.

### 2.8. Optimistic Concurrency Control

One endpoint participates in optimistic concurrency control: `PATCH /vessels/{id}`. A request to update a vessel's monitoring configuration must include `expected_vessel_version` carrying the vessel's `version` as last observed by the caller. If the supplied value does not match the vessel's current `version` on the server, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from silently overwriting a configuration change it never saw. No other endpoint accepts an `expected_*_version` field.

### 2.9. Nested Resource Retrieval

When an endpoint path references a parent resource and a child sub-resource (for example, listing a vessel's level readings or scale calibrations), the system validates the path left to right. A request naming a non-existent parent identifier is rejected immediately with the corresponding not-found error (`ERR_VESSEL_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, etc.) before any child lookup is attempted. The same rule applies when a request body references related resources — every referenced `site_id`, `vessel_id`, `technician_id`, `ticket_id`, `trigger_reading_id`, or `entrant_technician_id` must resolve to an existing entity, otherwise the request fails with the matching `ERR_*_NOT_FOUND` (HTTP 404).

### 2.10. Validation Ordering

Incoming requests are checked against a fixed priority sequence. Authentication headers are validated first — a missing or invalid `X-User-ID` or `X-User-Role` surfaces `ERR_UNAUTHENTICATED` before any body parsing occurs. The request body is then checked for structural validity (required fields present, types correct, enum values in range, numeric ranges respected, no unknown fields) and any violation yields `ERR_VALIDATION`. Only after the body is well-formed does role-based authorization run (`ERR_FORBIDDEN`), then existence of every referenced resource (the appropriate `ERR_*_NOT_FOUND`), then the OCC check `ERR_STALE_VERSION` where applicable, then state-machine from-state validation (`ERR_INVALID_TICKET_STATE`, `ERR_INVALID_ORDER_STATE`, `ERR_INVALID_PERMIT_STATE`), then the bin-entry safety cluster (lockout, segregation of duties, engulfment control, atmosphere limits, entry-permit presence), then the temporal/scheduling cluster (window-in-past, technician double-booking, vessel downtime buffer, scale tolerance, inventory non-negativity), and finally the fiscal gate (`ERR_CREDIT_HOLD`). This ordering guarantees, for example, that a mid-flight credit hold surfaces as `ERR_CREDIT_HOLD` only after the request has already passed every structural and safety check, and that a stale `expected_vessel_version` always masks any later business rule.

### 2.11. Logical Clock

The service maintains a server-side logical clock that drives window validation and the trailing-window usage calculation. At startup the clock is exactly `2026-08-01T00:00:00Z`. A `ServiceManager` may advance it via the clock-set capability, supplying a `to_iso8601` timestamp. The clock never falls back to wall-clock time; every "is this window in the future" check and every trailing-14-day usage window reads from this logical clock.

## 3. Business Logic & Workflows

### 3.1. Onboarding Sites, Technicians, and Vessels

A `ServiceManager` onboards a customer site by creating a `CustomerSite` with a display `name` and a two-letter `state_code`. The site optionally carries a `contract_discount_pct` (default 0, range 0–100) applied to estimates and invoices, a `capital_threshold_cents` (default 500000 integer cents — i.e. $5,000.00) above which quoted tickets route to the capital-project track, and a `credit_hold` boolean (default false) that, when true, blocks scheduling of new service. A newly created site has no vessels, so its `site_posture` is `NORMAL`.

Field capacity is onboarded by creating a `Technician` with a `name` and a `weekly_capacity_hours` total (must be greater than zero). Optional `certifications` is a free-form array of labels such as `CONFINED_SPACE`, defaulting to empty. The `active` flag defaults to true; an inactive technician cannot be scheduled. At registration the technician's `remaining_capacity_hours` is initialized equal to `weekly_capacity_hours`.

A `Vessel` is registered under a site via a payload containing `site_id`, a vessel tag `name` (e.g. `SILO-3`), a `vessel_kind` of `SILO`, `BIN`, or `HOPPER`, a `capacity_tons` (must be greater than zero), and the `material_name` of the stored bulk solid. Reorder behaviour is configured through `reorder_point_pct` (0–100), an optional `target_fill_pct` (default 90, must be greater than zero and at most 100), an optional `replenishment_policy` of `TARGET_FILL` (default) or `DAYS_OF_COVER`, an optional `cover_days` (default 7, must be greater than zero), and an optional `default_usage_tons` (default 1.0, must be at least zero) used as a fallback when fewer than two readings exist in the trailing usage window. An optional `opening_inventory_tons` (default 0, must be at least zero) anchors the vessel's inventory before any level reading is recorded. Quality monitoring is configured via `moisture_limit_pct` (default 12.0, range 0–100). Scale-calibration behaviour is configured via `error_basis` — `OF_READING` (default) or `OF_FULL_SCALE` — and `full_scale_tons`, which is required when `error_basis` is `OF_FULL_SCALE` and ignored otherwise. On creation the vessel's `current_inventory_tons` is set equal to `opening_inventory_tons`, `flow_posture` starts at `NORMAL`, and `scale_status` starts at `IN_TOLERANCE`.

A `ServiceManager` may later adjust the vessel's monitoring configuration (`reorder_point_pct`, `target_fill_pct`, `moisture_limit_pct`) by submitting the new values together with `expected_vessel_version`. The update increments the vessel's `version`. This configuration change is not retroactive: it does not cause the system to re-evaluate whether an existing reading should have triggered a replenishment order — reorder evaluation happens only when a new level reading is recorded.

### 3.2. Recording Inventory Levels and Auto-Triggering Replenishment

A `PlantOperator` (for vessels of its own site only) or a `Technician` records a `LevelReading` by supplying `vessel_id`, `measured_at` (ISO 8601 UTC), and `level_pct` (0–100 inclusive). An optional `source` of `MANUAL` (default) or `SENSOR` may be attached. Recording the reading bumps the vessel's `version` and triggers three pieces of work.

First, the vessel's `current_inventory_tons` is recomputed. The anchor for the calculation is the vessel's `LevelReading` with the latest `measured_at`, with ties broken by the latest `created_at`; if no readings exist at all, the implicit anchor is the vessel's `created_at` paired with `opening_inventory_tons`. The anchor inventory is the anchor reading's `level_pct` multiplied by `capacity_tons` and divided by 100, rounded half up to 1 decimal place. The vessel's `current_inventory_tons` is then the anchor inventory plus the sum of `delivered_tons` across all replenishment orders for the vessel whose status is `RECEIVED` and whose `received_at` is strictly after the anchor's `measured_at`, again rounded half up to 1 decimal place. A receipt whose `received_at` is at or before the anchor's `measured_at` is understood to be already inside the anchor and contributes nothing. A `RECEIVED` order that is later `VOIDED` simply leaves the received set, so receive followed by void restores the pre-receipt value exactly.

Second, the system runs a reorder evaluation. If the new reading's `level_pct` is at or below the vessel's `reorder_point_pct`, and there is no replenishment order for the vessel in `TRIGGERED` or `DISPATCHED` status, the system auto-creates a `ReplenishmentOrder` in `TRIGGERED` status, snapshotting the vessel's current `replenishment_policy` onto `policy_used` and the triggering reading's `id` onto `trigger_reading_id`. The order's `order_quantity_tons` is computed by one of two variants and rounded half up to 1 decimal place, with a floor of zero (a negative computed quantity is clamped to zero):

- Under `TARGET_FILL`, the quantity is `target_fill_pct` divided by 100, multiplied by `capacity_tons`, minus `current_inventory_tons` — it fills to a fixed capacity percentage regardless of consumption rate.
- Under `DAYS_OF_COVER`, the quantity is `cover_days` multiplied by the vessel's average daily usage in tons, minus `current_inventory_tons`. The average daily usage is computed over the trailing 14 days: take the vessel's readings whose `measured_at` falls in the window from 14 days before the current logical clock up to and including the current logical clock, ordered by `measured_at` ascending (ties by `created_at` ascending). If fewer than two readings fall in the window, the usage defaults to the vessel's `default_usage_tons`. Otherwise, let the earliest and latest readings bound the window. Compute the inventory at each boundary as that reading's `level_pct` times `capacity_tons` divided by 100, rounded half up to 1 decimal place. Sum `delivered_tons` across orders in `RECEIVED` status whose `received_at` falls strictly after the earliest boundary's `measured_at` and at or before the latest boundary's `measured_at`. The usage is then (inventory at the earliest reading minus inventory at the latest reading plus the in-window receipts) divided by the elapsed days between the two boundary readings (a fractional value), floored at zero, and rounded half up to 2 decimal places.

Third, the vessel's `flow_posture` is recomputed and the parent site's `site_posture` rolls up per §2.4. If the new order was auto-created, the vessel transitions to `PENDING_REPLENISHMENT` and the site may move to `ATTENTION`.

### 3.3. Material Quality Reports and the Flow-Impairment Cascade

A `Technician` submits a `MaterialQualityReport` with `vessel_id`, `sampled_at`, `moisture_pct` (0–100), and `caking_index` (an integer from 1 for free-flowing to 5 for fully caked). The system derives a `flowability_grade`: the report is `POOR` if `moisture_pct` exceeds the vessel's `moisture_limit_pct` or `caking_index` is at least 4; otherwise it is `MARGINAL` if `moisture_pct` exceeds the vessel's `moisture_limit_pct` minus 2 or `caking_index` is exactly 3; otherwise it is `GOOD`.

Filing the report bumps the vessel's `version` and recomputes its `flow_posture`. The vessel is `FLOW_IMPAIRED` whenever its latest quality report (latest by `sampled_at`, ties by `created_at`) breaches either the moisture limit or the caking threshold of 4. When a vessel transitions into `FLOW_IMPAIRED`, the safety cascade of §2.4 fires: every `EntryPermit` of the vessel whose status is `DRAFT` or `ISSUED` is auto-transitioned to `VOIDED` with `void_reason` set to `AUTO_QUALITY_HAZARD`. The site's `site_posture` is then recomputed from its child vessels.

### 3.4. Load-Out Scale Calibration

A `Technician` records a `ScaleCalibration` by supplying `vessel_id`, `tested_at`, the certified `test_weight_tons` applied (must be greater than zero), and the `indicated_tons` shown by the scale under that weight (must be at least zero). An optional `tolerance_pct` (default 0.25, must be greater than zero) controls the pass band. The vessel's `error_basis` at the moment of the test is snapshotted onto the record as `error_basis_used` so historical records remain interpretable after the vessel is reconfigured.

The calibration's `error_pct` is computed at 3 decimal places, rounded half up, by one of two variants. Under `OF_READING`, the error is the difference between `indicated_tons` and `test_weight_tons`, divided by `test_weight_tons`, multiplied by 100 — error expressed relative to the applied test weight. Under `OF_FULL_SCALE`, the error is the difference between `indicated_tons` and `test_weight_tons`, divided by the vessel's `full_scale_tons`, multiplied by 100 — error expressed relative to full-scale capacity, so identical weights yield a smaller absolute `error_pct` and can flip the pass/fail outcome relative to `OF_READING`. The calibration's `result` is `PASS` when the absolute value of `error_pct` is at most `tolerance_pct` (the boundary is inclusive) and `FAIL` otherwise. The vessel's `scale_status` is rewritten accordingly and its `version` is bumped.

### 3.5. Replenishment Order Lifecycle

A replenishment order is always born `TRIGGERED`, either by the auto-trigger in §3.2 or never — there is no manual create. From `TRIGGERED` a `ServiceManager` may dispatch the order, advancing it to `DISPATCHED`; the order remains in the open-order set used by `flow_posture` derivation, so the vessel remains `PENDING_REPLENISHMENT`.

A `PlantOperator` (for its own site) or a `Technician` may record delivery of a `DISPATCHED` order by supplying `delivered_tons` (must be greater than zero, otherwise `ERR_VALIDATION`) and `received_at`. Receiving is rejected with `ERR_SCALE_OUT_OF_TOLERANCE` while the vessel's scale is `OUT_OF_TOLERANCE`. On success the order transitions to `RECEIVED` and several cascades fire: the vessel's `current_inventory_tons` is recomputed (the receipt joins the received set only when its `received_at` is strictly after the current anchor's `measured_at`; otherwise the receipt is already inside the anchor and inventory does not change), the vessel's `flow_posture` is recomputed (the order leaves the open-order set, so `PENDING_REPLENISHMENT` may clear), the parent site's `site_posture` is recomputed, and the vessel's `version` is bumped.

A `PlantOperator` (for its own site) or a `ServiceManager` may cancel a `TRIGGERED` order, advancing it to `CANCELLED`. Cancellation removes the order from the open-order set, recomputes the vessel's `flow_posture` and the site's `site_posture`, and bumps the vessel's `version`.

A `ServiceManager` may void a `RECEIVED` order, but only when doing so does not drive the vessel's `current_inventory_tons` below zero — otherwise the void is rejected with `ERR_INVENTORY_WOULD_GO_NEGATIVE`. This non-negativity check is evaluated by recomputing `current_inventory_tons` under the §3.2 rule with this order treated as already removed from the received set, and rejecting only when that recomputed value would be below zero; it is not a subtraction of the order's `delivered_tons` from the currently reported value. Consequently, voiding a receipt whose `received_at` is at or before the current anchor's `measured_at` — a receipt that contributes nothing to inventory per §3.2 — passes the check and leaves inventory unchanged. A successful void transitions the order to `VOIDED`, recomputes the vessel's `current_inventory_tons` without this receipt (mass-balance compensation), recomputes the vessel's `flow_posture` and the site's `site_posture`, and bumps the vessel's `version`. Any attempt to invoke these transitions from a wrong from-state is rejected with `ERR_INVALID_ORDER_STATE` (HTTP 409).

### 3.6. Service Ticket Intake, Estimate, and Commercial Routing

A `PlantOperator` (for its own site) or a `ServiceManager` opens a `ServiceTicket` by supplying `site_id`, `vessel_id`, a `job_type` of `DIAGNOSIS`, `CLEANOUT`, `INSPECTION`, `RETROFIT_AERATION`, or `RETROFIT_VIBRATOR`, a `requires_entry` flag (true when personnel will enter the vessel, which makes the ticket permit-gated), `est_hours` (must be greater than zero), `crew_size` (must be at least 1), and an optional free-text `description` (default empty). The new ticket is in `DRAFT` status.

At creation the system computes a provisional `estimate_cents` in integer cents. The base is the per-crew-hour rate for the `job_type` — 9500 cents for `DIAGNOSIS`, 14500 cents for `CLEANOUT`, 11000 cents for `INSPECTION`, 22000 cents for `RETROFIT_AERATION`, and 18000 cents for `RETROFIT_VIBRATOR` — multiplied by `est_hours` and by `crew_size`. When the vessel's `flow_posture` at creation is `FLOW_IMPAIRED`, the base is further multiplied by an emergency multiplier of 1.5; otherwise the multiplier is 1.0. The multiplied result is rounded half up to integer cents, then a contract discount equal to that subtotal multiplied by the site's `contract_discount_pct` and divided by 100, again rounded half up to integer cents, is subtracted to yield `estimate_cents`.

A `ServiceManager` then finalizes the quote, transitioning the ticket from `DRAFT` to `QUOTED`. This transition resolves the ticket's `commercial_track`: the ticket is routed to `CAPITAL_PROJECT` when `estimate_cents` is greater than or equal to the site's `capital_threshold_cents`, and to `CONTRACT_SERVICE` otherwise. The approval path forks on this track. On the `CONTRACT_SERVICE` track, the owning `PlantOperator` (the one whose `X-User-ID` equals the ticket's `site_id`) approves, advancing the ticket from `QUOTED` to `APPROVED`. On the `CAPITAL_PROJECT` track, a `ServiceManager` approves, representing internal capital review. An approval attempted by a role that does not match the ticket's `commercial_track` is rejected with `ERR_FORBIDDEN`. A `PlantOperator` may instead decline a `QUOTED` ticket, moving it to the terminal `DECLINED` state.

### 3.7. Scheduling, Technician Capacity, and the Vessel Downtime Calendar

A `ServiceManager` schedules an `APPROVED` ticket by supplying `technician_id`, `window_start`, and `window_end`. The scheduling action runs a battery of checks in the order dictated by §2.10. The referenced technician must exist (`ERR_TECHNICIAN_NOT_FOUND`) and must be `active` (otherwise `ERR_VALIDATION`). The window must be strictly in the future — `window_end` must be strictly after `window_start`, and `window_start` must be strictly after the current logical clock — otherwise `ERR_WINDOW_IN_PAST`. The technician must not already occupy a half-open-overlapping window on another ticket in `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD` status; adjacency is permitted, but any positive overlap is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`. The vessel must observe a 2-hour downtime buffer against every other occupied downtime interval on the same vessel — that is, every other ticket's window whose status is `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`, and every `EntryPermit` window whose status is `DRAFT`, `ISSUED`, `ACTIVE`, or `SUSPENDED`, excluding any interval that shares this ticket's `id`. The gap from this window to each such interval must be at least 2 hours on both sides; a closer interval is rejected with `ERR_VESSEL_DOWNTIME_CONFLICT`. Finally, the site's `credit_hold` must be false; otherwise the schedule is rejected with `ERR_CREDIT_HOLD`.

On a successful schedule the ticket transitions from `APPROVED` to `SCHEDULED`, the supplied `technician_id`, `window_start`, and `window_end` are stored on the ticket, and the technician's `remaining_capacity_hours` is recomputed. That field equals `weekly_capacity_hours` minus the sum of `est_hours` across the technician's tickets whose status is `SCHEDULED` or `IN_PROGRESS`, expressed at 2 decimal places, rounded half up. Tickets in `ON_HOLD` no longer count (the crew is released to standby by the safety hold), and tickets in `COMPLETED` or `DECLINED` never count; consequently schedule-then-complete restores the pre-schedule value exactly.

### 3.8. Entry Permits, Atmosphere Control, and the Bound-Ticket Cascade

Before any ticket with `requires_entry` set to true can be started, a `SafetyOfficer` must draft an `EntryPermit` against the vessel. The draft supplies `vessel_id`, `ticket_id`, `entrant_technician_id` (the technician who will physically enter), `window_start`, and `window_end` (with `window_end` strictly after `window_start`). The permit's window joins the vessel's downtime calendar — the same 2-hour buffer rule of §3.7 applies at draft time, evaluated against other tickets' occupied windows and other permits' windows, exempting any interval that shares the same `ticket_id`. A new permit is `DRAFT`; `atmosphere_ok` starts unset, `void_reason` starts at `NONE`.

The permit is then issued by a `SafetyOfficer` supplying `lockout_checklist_confirmed`. Issue is refused when `lockout_checklist_confirmed` is not true (`ERR_LOCKOUT_NOT_VERIFIED`), when the issuing officer's `X-User-ID` equals the permit's `entrant_technician_id` (`ERR_SOD_ISSUER_EQUALS_ENTRANT` — segregation of duties), or when a replenishment order for the vessel is currently `DISPATCHED` (`ERR_INBOUND_DELIVERY_PENDING` — engulfment control). On a successful issue the permit transitions from `DRAFT` to `ISSUED` and `issuer_user_id` is recorded from the acting officer's `X-User-ID`.

Activation requires a pre-entry atmosphere test. A `SafetyOfficer` activates an `ISSUED` permit by supplying `oxygen_pct` and `combustible_pct`. The atmosphere passes when `oxygen_pct` is between 19.5 and 23.5 inclusive on both ends, and `combustible_pct` (expressed as a percentage of the lower explosive limit) is at most 10.0. A failing reading is rejected with `ERR_ATMOSPHERE_UNSAFE`. On a pass the permit transitions from `ISSUED` to `ACTIVE`, `atmosphere_ok` becomes true, and `last_oxygen_pct` and `last_combustible_pct` are recorded.

While a permit is `ACTIVE`, continuous monitoring continues. A `SafetyOfficer` or a `Technician` records a follow-up atmosphere reading by supplying `oxygen_pct` and `combustible_pct`. A passing reading leaves the permit `ACTIVE` and only updates `last_oxygen_pct` and `last_combustible_pct`. A failing reading transitions the permit from `ACTIVE` to `SUSPENDED`, sets `atmosphere_ok` to false, records the last readings, and cascades: the bound `ServiceTicket` (the one whose `id` equals the permit's `ticket_id`) whose status is `IN_PROGRESS` automatically transitions to `ON_HOLD`, releasing its `est_hours` from the technician's `remaining_capacity_hours` while the hold persists.

A `SafetyOfficer` resumes a `SUSPENDED` permit by supplying fresh `oxygen_pct` and `combustible_pct`. The same pass band as activation applies; a failure is rejected with `ERR_ATMOSPHERE_UNSAFE`. On a pass the permit returns from `SUSPENDED` to `ACTIVE`, `atmosphere_ok` becomes true, the last readings are recorded, and the reverse cascade fires: the bound ticket whose status is `ON_HOLD` automatically returns to `IN_PROGRESS`, with its `est_hours` re-allocated against the technician's `remaining_capacity_hours`.

A `SafetyOfficer` closes an `ACTIVE` permit by supplying `findings`. When `findings` is anything other than `NONE` — for example `BRIDGING_OBSERVED` or `RATHOLING_OBSERVED` — the system auto-creates a follow-up `ServiceTicket` in `DRAFT` status with `site_id` copied from the vessel's owning site, `vessel_id` copied from the permit, `job_type` set to `DIAGNOSIS`, `requires_entry` set to false, `est_hours` set to 4, `crew_size` set to 1, and `source_permit_id` set to the closing permit's `id`; its `estimate_cents` is computed at creation per §3.6. The permit itself transitions to `CLOSED`.

Permits in wrong from-states reject any of these transitions with `ERR_INVALID_PERMIT_STATE` (HTTP 409).

### 3.9. Starting, Completing, and Invoicing a Ticket

The assigned `Technician` starts a `SCHEDULED` ticket. The acting technician's `X-User-ID` must equal the ticket's `technician_id` (otherwise `ERR_FORBIDDEN`). When the ticket's `requires_entry` is true, there must exist an `EntryPermit` whose `ticket_id` equals the ticket's `id` and whose status is `ACTIVE`; otherwise the start is rejected with `ERR_ENTRY_PERMIT_REQUIRED`. On success the ticket transitions from `SCHEDULED` to `IN_PROGRESS`.

Completion is performed by the same assigned technician (again, `X-User-ID` must equal `technician_id`). The completion payload supplies `actual_hours` (must be greater than zero), `mileage_miles` (must be at least zero), and `disposal_tons` (must be at least zero). The ticket transitions from `IN_PROGRESS` to `COMPLETED`, the technician's `remaining_capacity_hours` is recomputed (the ticket's `est_hours` is released), and the invoice is computed with a pinned rounding order — per line first, then sum, then discount, then tax:

- `invoice_labor_cents` is `actual_hours` multiplied by the per-crew-hour rate for the ticket's `job_type` (the same rate table as §3.6: 9500 / 14500 / 11000 / 22000 / 18000 cents for `DIAGNOSIS` / `CLEANOUT` / `INSPECTION` / `RETROFIT_AERATION` / `RETROFIT_VIBRATOR` respectively) multiplied by `crew_size`, rounded half up to integer cents.
- `invoice_mobilization_cents` is `mileage_miles` multiplied by 331.7 cents per mile, rounded half up to integer cents.
- `invoice_disposal_cents` is `disposal_tons` multiplied by 3653.92 cents per ton, rounded half up to integer cents.
- `invoice_subtotal_cents` is the sum of the three per-line rounded values.
- `invoice_discount_cents` is `invoice_subtotal_cents` multiplied by the site's `contract_discount_pct` and divided by 100, rounded half up to integer cents.
- `invoice_tax_cents` is the taxable amount — `invoice_subtotal_cents` minus `invoice_discount_cents` — multiplied by 6.0 and divided by 100, rounded half up to integer cents.
- `invoice_total_cents` is the taxable amount plus `invoice_tax_cents`.

Summing raw fractional lines and rounding once at the end is non-conformant and produces different cents; the per-line rounding order is part of the contract. Any attempt to invoke a ticket action from a wrong from-state is rejected with `ERR_INVALID_TICKET_STATE` (HTTP 409).

### 3.10. Logical Clock and Test-Driving

A `ServiceManager` may advance the server's logical clock by supplying a `to_iso8601` timestamp. The clock is used by every window validation ("must be strictly in the future") and by the trailing-14-day usage window of §3.2. The startup default is exactly `2026-08-01T00:00:00Z`, and the logical clock never falls back to wall-clock time.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/sites`                                  | Create a customer site | ServiceManager |
| GET    | `/sites/{id}`                             | Get a site (includes computed site_posture) | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| POST   | `/technicians`                            | Register a field technician | ServiceManager |
| GET    | `/technicians/{id}`                       | Get a technician (includes computed remaining_capacity_hours) | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| POST   | `/vessels`                                | Register a silo/bin/hopper at a site | ServiceManager |
| GET    | `/vessels/{id}`                           | Get a vessel (computed fields resolved at read) | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| GET    | `/vessels`                                | List vessels, optionally filtered by `site_id` | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| PATCH  | `/vessels/{id}`                           | Update vessel monitoring configuration (OCC via `expected_vessel_version`) | ServiceManager |
| POST   | `/level-readings`                         | Record an inventory level reading for a vessel | PlantOperator, Technician |
| GET    | `/vessels/{id}/level-readings`            | List level readings of a vessel (newest `measured_at` first) | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| POST   | `/quality-reports`                        | Submit a moisture/caking lab report for a vessel | Technician |
| GET    | `/vessels/{id}/quality-reports`           | List quality reports of a vessel | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| POST   | `/scale-calibrations`                     | Record a load-out scale calibration test for a vessel | Technician |
| GET    | `/vessels/{id}/scale-calibrations`        | List calibration records of a vessel | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| GET    | `/replenishment-orders/{id}`              | Get a replenishment order | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| GET    | `/replenishment-orders`                   | List replenishment orders, optional filters `vessel_id`, `trigger_reading_id`, `status` | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| POST   | `/replenishment-orders/{id}/dispatch`     | Dispatch a TRIGGERED order | ServiceManager |
| POST   | `/replenishment-orders/{id}/receive`      | Record delivery of a DISPATCHED order | PlantOperator, Technician |
| POST   | `/replenishment-orders/{id}/cancel`       | Cancel a TRIGGERED order | PlantOperator, ServiceManager |
| POST   | `/replenishment-orders/{id}/void`         | Void a RECEIVED order (compensating inventory reversal) | ServiceManager |
| POST   | `/service-tickets`                        | Open a service ticket | PlantOperator, ServiceManager |
| GET    | `/service-tickets/{id}`                   | Get a service ticket | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| GET    | `/service-tickets`                        | List service tickets, optional filters `site_id`, `vessel_id`, `technician_id`, `source_permit_id`, `status` | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| POST   | `/service-tickets/{id}/quote`             | Finalize the quote and resolve commercial_track | ServiceManager |
| POST   | `/service-tickets/{id}/approve`           | Approve a QUOTED ticket (track-dependent actor) | PlantOperator, ServiceManager |
| POST   | `/service-tickets/{id}/decline`           | Customer declines a QUOTED ticket | PlantOperator |
| POST   | `/service-tickets/{id}/schedule`          | Assign a technician and time window to an APPROVED ticket | ServiceManager |
| POST   | `/service-tickets/{id}/start`             | Assigned technician begins work | Technician |
| POST   | `/service-tickets/{id}/complete`          | Assigned technician completes work; invoice computed | Technician |
| POST   | `/entry-permits`                          | Draft a bin-entry permit | SafetyOfficer |
| GET    | `/entry-permits/{id}`                     | Get an entry permit | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| GET    | `/entry-permits`                          | List entry permits, optional filters `vessel_id`, `ticket_id`, `entrant_technician_id`, `status` | ServiceManager, PlantOperator, Technician, SafetyOfficer |
| POST   | `/entry-permits/{id}/issue`               | Issue a DRAFT permit after lockout confirmation | SafetyOfficer |
| POST   | `/entry-permits/{id}/activate`            | Activate an ISSUED permit after a passing pre-entry atmosphere test | SafetyOfficer |
| POST   | `/entry-permits/{id}/atmosphere-check`    | Record a continuous-monitoring atmosphere reading on an ACTIVE permit | SafetyOfficer, Technician |
| POST   | `/entry-permits/{id}/resume`              | Resume a SUSPENDED permit after a passing atmosphere re-test | SafetyOfficer |
| POST   | `/entry-permits/{id}/close`               | Close an ACTIVE permit at end of entry | SafetyOfficer |
| POST   | `/_clock/set_current_utc`                 | Set the server's logical clock (test-driving endpoint) | ServiceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED`              | 401 |
| `ERR_VALIDATION`                   | 400 |
| `ERR_FORBIDDEN`                    | 403 |
| `ERR_SITE_NOT_FOUND`               | 404 |
| `ERR_VESSEL_NOT_FOUND`             | 404 |
| `ERR_TECHNICIAN_NOT_FOUND`         | 404 |
| `ERR_TICKET_NOT_FOUND`             | 404 |
| `ERR_PERMIT_NOT_FOUND`             | 404 |
| `ERR_ORDER_NOT_FOUND`              | 404 |
| `ERR_STALE_VERSION`                | 412 |
| `ERR_INVALID_TICKET_STATE`         | 409 |
| `ERR_INVALID_ORDER_STATE`          | 409 |
| `ERR_INVALID_PERMIT_STATE`         | 409 |
| `ERR_LOCKOUT_NOT_VERIFIED`         | 409 |
| `ERR_SOD_ISSUER_EQUALS_ENTRANT`    | 409 |
| `ERR_INBOUND_DELIVERY_PENDING`     | 409 |
| `ERR_ATMOSPHERE_UNSAFE`            | 409 |
| `ERR_ENTRY_PERMIT_REQUIRED`        | 409 |
| `ERR_WINDOW_IN_PAST`               | 409 |
| `ERR_TECHNICIAN_DOUBLE_BOOKED`     | 409 |
| `ERR_VESSEL_DOWNTIME_CONFLICT`     | 409 |
| `ERR_SCALE_OUT_OF_TOLERANCE`       | 409 |
| `ERR_INVENTORY_WOULD_GO_NEGATIVE`  | 409 |
| `ERR_CREDIT_HOLD`                  | 409 |
