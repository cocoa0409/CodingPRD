# Driveway Sealcoating API — Product Requirements Document

## 1. Introduction

Residential driveways and commercial parking lots represent a significant capital asset for property owners, and sealcoating contractors operate within a punishing set of physical constraints: sealer chemistry only cures within specific temperature and moisture envelopes, the operating season in most markets runs from early spring through late autumn, and a job sold against one set of measurements must be priced, scheduled, supplied, and warrantied with complete internal consistency. This document specifies the Driveway Sealcoating & Asphalt Maintenance Service API, the operational backbone for a contractor running that full cycle — from the first on-site measurement of cracks and potholes, through tiered per-square-foot quoting and weather-gated route scheduling, to final invoicing against crew-recorded actuals and multi-season warranty administration.

The system serves five distinct actors whose duties are deliberately segregated. Back-office staff register customers, properties, materials, and crews; field estimators measure sites and build quotes; dispatchers build daily route sheets and coordinate vehicle displacement with property occupants; crew leaders execute the work and record what was actually applied; and customers accept quotes, pay invoices, and file warranty claims. Because sealer lots are finite, route days have hard capacity and drive-time ceilings, and a weather front can invalidate an entire published schedule, the API treats optimistic concurrency, compensating releases, and cascade propagation as first-class concerns rather than afterthoughts. All resources are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that apply uniformly to every endpoint: authentication, response envelope, pagination, resource identity, monetary precision, concurrency control, and the cross-cutting physical rules of the sealcoating trade.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles: `OfficeAdmin`, `Estimator`, `Dispatcher`, `CrewLead`, and `Customer`. Every resource carries a system-managed `status` field (or, on the work order, the three parallel status dimensions described in §3.4) whose values are the exact uppercase enumerations narrated in §3.

For the four staff roles — `OfficeAdmin`, `Estimator`, `Dispatcher`, and `CrewLead` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow calls for it (for example, as `investigated_by` on a warranty claim when an `OfficeAdmin` opens an investigation), but it is never compared to any entity's `id`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that traces back to a customer — a quote on their property, an invoice for their work order, a warranty record covering their lot — compare the resource's owning customer foreign key against `X-User-ID`. A customer acting on a resource owned by a different customer is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — customers, properties, site assessments, materials, material lots, crews, route sheets, quotes, work orders, displacement plans, invoices, warranty records, and warranty claims — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): a system-managed counter starting at 1 that increments by one on every mutation of the resource, including mutations driven by system cascades (for example, when submitting an assessment refreshes the owning property's measured area, the property's `version` increments).

The sole exception is the weather snapshot: a weather observation or forecast is an immutable fact once posted, so weather snapshots carry only `id` and `created_at` — `updated_at` and `version` are absent from that resource.

### 2.5. Monetary Precision and Rounding

All money in the system is expressed as integer cents. Every rounding performed inside a pricing or settlement calculation uses the round-half-up method, and every such rounding produces integer cents. Quote pricing, invoice settlement, and material cost floors all share this discipline. Where the pricing rules require per-line rounding before summation, that order is pinned and described in §3; implementations that sum unrounded intermediate values and round once at the end produce different cent amounts and are non-conformant. Non-monetary derived values follow their own stated precision: condition scores are integers, utilization percentages carry exactly one decimal place (rounded half-up), and material reservations are expressed in whole gallons rounded up.

### 2.6. Optimistic Concurrency Control

Two write operations in the system are protected by explicit optimistic concurrency control; no other endpoint takes a version field.

Creating a quote requires the request to carry `expected_property_version`, holding the client-last-observed `version` of the target property. Because quote creation supersedes any prior open quote on the property and advances the property's version, a client working from a stale view of the property would otherwise silently overwrite a sibling's work. If `expected_property_version` does not match the property's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Rescheduling a weather-held work order requires the request to carry `expected_work_order_version`, matching the work order's current `version`. Repeated rain-outs make re-rescheduling a legitimate, everyday action, so the version check — not any state precondition — is the serialization point: if another writer has advanced the work order's version since the client last read it, the reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. The Logical Clock and the Paving Season

All time-sensitive evaluation in the system — quote expiry, assessment staleness, season windows, cure completion, warranty expiry, lazy route-sheet closure — is evaluated against a logical server clock, never the host's wall clock. At startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z. An `OfficeAdmin` may advance it to a supplied instant via an admin-only test-driving capability accepting `to_iso8601`; once set, the clock stays where it was put and never falls back to wall-clock time. Lazy state evaluations (described in §3) are all computed against this clock at the moment the relevant resource is loaded or acted upon.

The paving season is fixed: sealcoating work may only be scheduled on dates whose month-and-day fall within the inclusive window from April 1 through October 31. A scheduling request naming a date outside that window is rejected with `ERR_OUTSIDE_SEASON`; a date in the past relative to the logical clock is rejected with `ERR_DATE_IN_PAST`.

### 2.8. Weather Gating and Weather-Driven Cascades

Sealer cannot be applied in cold or wet conditions, and the system enforces this twice: once when a job is scheduled against a forecast, and again when the crew attempts to start on the service date against the latest observation. Every material product declares its own application envelope through `min_apply_temp_f` and `max_precip_probability_pct`. For any gated operation, the relevant weather snapshot is the latest one posted for the service date — latest by creation time, with an observed reading preferred over a forecast when both were posted at the same instant. If no snapshot exists for the service date at all, the operation fails with `ERR_WEATHER_DATA_MISSING`. If the latest snapshot shows a minimum temperature below the material's `min_apply_temp_f`, or a precipitation probability above the material's `max_precip_probability_pct`, the operation fails with `ERR_WEATHER_WINDOW_VIOLATION`.

Weather also propagates. When a newly posted snapshot is the latest for its target date and that snapshot shows either a precipitation probability strictly greater than 60 percent or a minimum temperature strictly below 40 degrees Fahrenheit, every published route sheet whose service date matches that target date is forced into `WEATHER_HOLD`; every scheduled work order on such a sheet follows into `WEATHER_HOLD` (retaining its material reservation and route booking); and each affected work order's displacement plan, if it had already reached a notified or cleared state, is marked `STALE`, because the access window it described is no longer trustworthy.

### 2.9. The Material Lot Ledger

Sealer inventory is tracked per delivery lot as a four-column ledger. Each lot records `delivered_gallons` at receipt; `reserved_gallons` accumulates the reservations held by work orders in scheduled, weather-held, or in-progress states; `consumed_gallons` accumulates what crews actually drew at finish time; and `wasted_gallons` accumulates spillage recorded by the office. The derived `on_hand_gallons` is always the delivered quantity minus reserved, consumed, and wasted gallons. Each lot also declares a `reorder_threshold_gallons`; the boolean `reorder_flag` is true exactly when on-hand gallons are at or below that threshold, and it is recomputed on every mutation of the ledger — so a cancellation that releases a reservation can clear a reorder flag just as a new reservation can set one. Lots are born in `RECEIVED` status, move to `IN_USE` the first time a reservation lands on them, and return to `RECEIVED` if both reserved and consumed gallons settle back to zero. A lot reaches `DEPLETED` when on-hand gallons hit zero — after a waste recording with no reservations outstanding, or after consumption when nothing remains reserved. A lot whose quality is suspect may be moved to the terminal `QUARANTINED` state by an office administrator; a lot still holding reservations cannot be quarantined and the attempt is rejected with `ERR_MATERIAL_LOT_IN_USE`, while referencing a quarantined or depleted lot for new work is rejected with `ERR_MATERIAL_LOT_UNAVAILABLE`.

### 2.10. Route Density and Daily Capacity Discipline

Each crew runs one route sheet per service date, and each sheet carries a `capacity_sqft` ceiling and a hard drive-time budget of 180 minutes for the day. The sheet's `booked_sqft` and `total_drive_minutes` aggregate the work orders on the sheet whose execution status is scheduled, weather-held, in-progress, curing, or completed — cancelled work orders are excluded, and pending work orders contribute nothing because they are not yet attached to any sheet. The derived `open_capacity_sqft` is capacity minus booked area, recomputed on every mutation. §3.5 details the gates that protect these ceilings at scheduling time, including equality semantics: a candidate that exactly fills remaining capacity or exactly exhausts the drive budget is permitted.

### 2.11. Validation Order

When a request fails for more than one reason, the reported error is determined by a fixed priority order, evaluated from first to last: authentication context (missing or malformed headers) first; then role authorization; then customer ownership; then existence of every referenced identifier, with path identifiers validated left-to-right; then state-machine legality (including the lazy expiry flips for quotes, assessments, and warranties); then the weather gate; then referential usability of configuration (assessment status and property match, lot status, lot-to-quote material match, and on-hand sufficiency); then temporal rules (season, past dates, notice lead time, cure completion, re-application interval); then structural conflicts (crew window overlap, property access overlap, capacity, drive limit, striping scope, window-hour sanity, segregation of duties, lot-in-use); then fiscal rules (discount range, price floor, payment exactness); and finally optimistic-concurrency staleness.

## 3. Business Logic & Workflows

This section narrates the lifecycle of work as it flows through the business: how sites are measured, how quotes are priced and accepted, how route days are built and weather-tested, how jobs are executed and settled, and how warranties are honored. State names appear as their exact enumeration values; the HTTP contract for each capability lives in §4.

### 3.1. Customers, Properties, Materials, and the Seal Cycle

An `OfficeAdmin` registers each material product with its `product_name`, a `grade` of `STANDARD`, `PREMIUM`, or `ECO`, and the physical and commercial parameters the pricing and weather engines consume: `coverage_sqft_per_gallon`, `min_apply_temp_f`, `max_precip_probability_pct`, `cure_hours_vehicle`, `reapplication_months`, `warranty_months`, and `price_per_gallon_cents`. The office also receives material into inventory lot by lot: each lot names its `material_id`, the `delivered_gallons` received, the `unit_cost_cents` paid per gallon, the `received_on` date, and the `reorder_threshold_gallons` that arms the reorder flag.

An `OfficeAdmin` registers each customer with a `name`, a `customer_type` of `RESIDENTIAL` or `COMMERCIAL`, and contact details (`email` and `phone`). Properties are then registered against a customer with a `customer_id`, a street `address`, and a `lot_kind` of `RESIDENTIAL_DRIVEWAY` or `COMMERCIAL_LOT` — a distinction with teeth later, because striping work is only lawful on commercial lots.

A property aggregates its own history. Its `current_area_sqft` reflects the measured area from its most recently submitted site assessment and stays null until one is submitted. Its `open_quote_id` points at the property's single non-terminal quote — one in `DRAFT`, `SENT`, or `REVISION_REQUESTED` — and is null when no such quote exists; the system enforces this singularity by superseding, never by rejecting. Its `last_completed_seal_on` records when the most recent non-warranty seal job completed, and `next_seal_eligible_on` projects when the same property may be sealed again: the completion timestamp plus that job's material `reapplication_months` — calendar months added to the completion timestamp itself, with the completion's time of day preserved, so `next_seal_eligible_on` is a full timestamp rather than a bare date. Both stay null until a seal job completes. A non-warranty seal job scheduled before `next_seal_eligible_on`'s date is rejected with `ERR_RESEAL_INTERVAL_NOT_MET`; warranty repairs are exempt from this interval because they redo work already owed.

### 3.2. Site Measurement and the Pavement Condition Index

An `Estimator` creates a site assessment in `DRAFT` status against a `property_id`, recording `measured_area_sqft` (which must be greater than zero), `crack_linear_ft`, `pothole_count`, `pothole_area_sqft`, `oil_spot_area_sqft` (the oil-contaminated area that will need primer), and a `slope_severity` of `NONE`, `MODERATE`, or `STEEP`. The crack, pothole, and oil measurements must each be zero or greater.

At creation the system computes the `pavement_condition_index`, a 0-to-100 score that starts at 100 and subtracts four deductions. The crack deduction is the crack footage divided by the measured area, multiplied by 400, rounded half-up to an integer, and capped at 40. The pothole deduction is the pothole area divided by the measured area, multiplied by 700, rounded half-up to an integer, and capped at 35. The oil deduction is the oil-spot area divided by the measured area, multiplied by 300, rounded half-up to an integer, and capped at 15. The slope deduction is 10 points for `STEEP`, 5 for `MODERATE`, and 0 for `NONE`. The score is the remainder after subtracting all four deductions from 100, floored at zero. Assessments are immutable once created; the index is never recomputed.

Submitting an assessment — permitted only while it is `DRAFT`, else `ERR_ASSESSMENT_NOT_SUBMITTABLE` — stamps `submitted_at` with the current clock and triggers two cascades: any other `SUBMITTED` assessment for the same property flips to `SUPERSEDED`, and the property's `current_area_sqft` refreshes to this assessment's measured area, incrementing the property's `version`. Supersession is deliberately gentle on downstream work: quotes that pinned a now-superseded assessment keep their pinned snapshots and their totals do not change. Separately, an assessment has a 30-day shelf life: whenever a quote creation or quote send loads an assessment whose submission date is more than 30 days in the past, the assessment lazily flips to `EXPIRED` and the referencing operation fails with `ERR_ASSESSMENT_EXPIRED`.

### 3.3. Quoting: Scope, Tiered Pricing, and the Cost Floor

An `Estimator` builds a quote against a property by pinning a specific `assessment_id` (which must belong to the same property, else `ERR_ASSESSMENT_PROPERTY_MISMATCH`), selecting a `material_id`, and declaring scope through four booleans — `include_crack_fill`, `include_patch`, `include_seal`, and `include_striping` — plus a `coats` count of 1 or 2 (defaulting to 1). Striping is commercial-only: requesting `include_striping` on a residential driveway, or planning striping on one later, is rejected with `ERR_STRIPING_COMMERCIAL_ONLY`. When striping is included, `stripe_linear_ft` must be supplied. A negotiated `discount_pct` between 0 and 0.30 inclusive may be applied (defaulting to 0); a value outside that range is an invalid request.

At creation the quote pins three measurement snapshots from the assessment — `area_sqft_snapshot`, `crack_ft_snapshot`, and `pothole_area_snapshot` — and computes provisional pricing. The seal line uses average-rate tiering on the total area: an area of exactly 1000 square feet or less prices at 30 cents per square foot; an area above 1000 up to and including exactly 5000 square feet prices at 24 cents per square foot; an area above 5000 prices at 18 cents per square foot. The selected rate is then multiplied by a grade factor — 1.00 for `STANDARD`, 1.35 for `PREMIUM`, 1.15 for `ECO` — and by the coat count, with the result rounded half-up to integer cents into `seal_line_cents` (zero when sealing is excluded). Crack filling prices at 150 cents per linear foot into `crack_line_cents`; pothole patching at 800 cents per square foot into `patch_line_cents`; striping at 90 cents per linear foot into `striping_line_cents`; each line rounded half-up individually and zeroed when its scope flag is off. The rounding order is pinned: each line rounds to integer cents first, and only then does `subtotal_cents` sum the four rounded lines. The `discount_cents` is the rounded-half-up product of the subtotal and the discount fraction. A mobilization fee of 7500 cents applies when the subtotal minus the discount is strictly below 200000 cents — two thousand dollars — and is otherwise waived; it lands in `mobilization_fee_cents`. The `total_cents` is the subtotal minus discount plus mobilization fee, raised to a 25000-cent minimum charge when the arithmetic falls below it.

Every quote must also clear a cost floor: the estimated material cost — the gallons the job would require (per the whole-gallon reservation formula of §3.5, computed from the pinned area, coat count, and the material's `coverage_sqft_per_gallon`) times the material's `price_per_gallon_cents`, counted only when sealing is in scope — plus a labor floor of the pinned area times 5 cents per square foot, rounded half-up. A quote whose total falls below this floor is rejected with `ERR_PRICE_BELOW_COST_FLOOR`.

Only one open quote may exist per property. Creating a new quote supersedes any prior `DRAFT`, `SENT`, or `REVISION_REQUESTED` quote on the same property, points `open_quote_id` at the newcomer, and increments the property's `version` — which is precisely why quote creation carries the OCC requirement described in §2.6. Supersession is strictly a consequence of a successful create: a create rejected for any reason (including the cost-floor rejection above) persists no quote, leaves any prior open quote in its current state, and does not modify `open_quote_id` or the property's `version`. A revision edit by an estimator is permitted while the quote is `DRAFT` or `REVISION_REQUESTED` (otherwise `ERR_QUOTE_NOT_EDITABLE`); it recomputes every pricing field from the revised inputs and clears `sent_at` and `expires_on` back to null, restarting the send cycle. A `REVISION_REQUESTED` quote edited this way returns to `DRAFT`.

Sending a quote — permitted only from `DRAFT`, else `ERR_QUOTE_NOT_SENDABLE` — requires the pinned assessment to still be `SUBMITTED`; if it has been superseded the send fails with `ERR_ASSESSMENT_NOT_USABLE`, and if it has aged past 30 days the assessment flips to `EXPIRED` and the send fails with `ERR_ASSESSMENT_EXPIRED`. A successful send stamps `sent_at` and computes `expires_on` as the calendar date 14 days after the sent date.

The customer then decides. Acceptance, decline, and revision-request all require the quote to be `SENT` (else `ERR_QUOTE_NOT_ACCEPTABLE`) and require the acting customer to own the quote's property (else `ERR_NOT_RESOURCE_OWNER`). If the current clock date has passed `expires_on`, the quote lazily flips to `EXPIRED`, `open_quote_id` is cleared if it pointed at this quote, and the attempted action fails with `ERR_QUOTE_EXPIRED`. Acceptance moves the quote to `ACCEPTED` and is the consequential path: it creates the work order (§3.4), supersedes every other open quote on the property, clears `open_quote_id`, and increments the property's `version`. Decline moves the quote to `DECLINED`, clears `open_quote_id`, and increments the property's `version`. Request-revision merely moves the quote to `REVISION_REQUESTED`, leaving it open for the estimator's revision edit.

### 3.4. The Work Order: Three Parallel Dimensions

Acceptance materializes a work order that freezes the deal: `property_id` and `quote_id` copied from the quote; `include_crack_fill`, `include_patch`, `include_seal`, `include_striping`, and `coats` snapshotted from the scope; `material_grade` snapshotted from the quote's material; `quoted_area_sqft` set to the quote's pinned area; and `quoted_total_cents` frozen at the quote's total. The work order is born with `execution_status` of `PENDING`, `billing_status` of `UNINVOICED`, and a `striping_status` of `PLANNING` when striping is in scope and `NOT_REQUIRED` otherwise. While pending, `route_sheet_id`, `material_lot_id`, and `scheduled_date` are all null.

These three status dimensions evolve in parallel. The execution dimension runs `PENDING → SCHEDULED → IN_PROGRESS → CURING → COMPLETED → CLOSED`, with `WEATHER_HOLD` branching off `SCHEDULED` and `CANCELLED` reachable from any pre-start state. The billing dimension runs `UNINVOICED → INVOICED → PAID`, driven entirely by the invoice lifecycle. The striping dimension runs `PLANNING → PLANNED → APPROVED → APPLIED → VERIFIED` when striping is required. The dimensions interact at specific checkpoints: a striping job cannot complete execution until its striping is `VERIFIED`, and a completed job closes itself when its invoice is paid.

### 3.5. Scheduling: Route Sheets, Gates, and Reservations

A `Dispatcher` prepares capacity by creating a route sheet for a `crew_id` on a `service_date` — one sheet per crew per date. The sheet's `capacity_sqft` defaults to the crew's `daily_capacity_sqft` when omitted. Crews carry a `crew_name`, a `home_zone`, and an `active` flag (default true); inactive crews cannot receive new sheets. A sheet is born `OPEN` and becomes `PUBLISHED` when the dispatcher publishes it; a weather-held sheet may be re-published, but re-publishing does not auto-return its work orders — each one stays `WEATHER_HOLD` until individually rescheduled.

Scheduling a pending work order onto a sheet is the system's most heavily gated operation, performed by a `Dispatcher` supplying `route_sheet_id`, `material_lot_id`, `scheduled_date`, `window_start_hour`, `window_end_hour`, `drive_minutes_est`, and `vehicles_to_move`. The gates, in the order a failure surfaces:

1. The work order must be `PENDING` (else `ERR_WORK_ORDER_NOT_SCHEDULABLE`); rescheduling requires `WEATHER_HOLD` and carries the same error for any other state.
2. The route sheet must exist, be `OPEN` or `PUBLISHED`, its `service_date` must equal the requested `scheduled_date`, and its crew must be active — any failure is `ERR_ROUTE_SHEET_NOT_SCHEDULABLE`.
3. The weather gate of §2.8 runs against the scheduled date.
4. The season and past-date rules of §2.7 run.
5. The re-application interval of §3.1 runs for non-warranty seal jobs.
6. Capacity: the sheet's booked square footage plus the candidate's `quoted_area_sqft` must not exceed the sheet's `capacity_sqft` — equality is allowed — else `ERR_ROUTE_CAPACITY_EXCEEDED`.
7. Drive time: the sheet's total drive minutes plus the candidate's `drive_minutes_est` must not exceed 180 — equality is allowed — else `ERR_ROUTE_DRIVE_LIMIT_EXCEEDED`.
8. Crew window: the half-open interval from `window_start_hour` to `window_end_hour` must not overlap any other non-cancelled work order's window on the same sheet, else `ERR_CREW_WINDOW_OVERLAP`. The window hours themselves must be sane: start between 6 and 19 inclusive, end between 7 and 20 inclusive, end strictly after start — violations are `ERR_INVALID_WINDOW_HOURS`.
9. Property access: the cure-buffered blocked interval for this job — from the scheduled date at `window_start_hour` through the provisional access-block end described below — must not overlap any other non-cancelled work order's blocked interval on the same property, else `ERR_ACCESS_WINDOW_OVERLAP`.
10. The material lot must be `RECEIVED` or `IN_USE` (else `ERR_MATERIAL_LOT_UNAVAILABLE`), must stock the same material the quote specified, and its on-hand gallons must cover the reservation (else `ERR_INSUFFICIENT_MATERIAL`).

The reservation quantity deserves precision. When sealing is not in scope, no sealer is drawn and the reservation is zero. Otherwise the gallons required are the area times the coat count times a waste factor of 1.10, divided by the material's `coverage_sqft_per_gallon`, rounded up to whole gallons — the same formula feeds both the quote cost floor and the lot reservation.

On a successful schedule the world shifts in several places at once. The work order moves to `SCHEDULED` with its `version` incremented and `reserved_gallons` set per the formula. The lot's `reserved_gallons` grows by that amount, a first reservation flips the lot from `RECEIVED` to `IN_USE`, and the lot's on-hand gallons and `reorder_flag` recompute. The sheet's `booked_sqft` grows by `quoted_area_sqft`, `total_drive_minutes` grows by `drive_minutes_est`, `open_capacity_sqft` recomputes, and the sheet's `version` increments. Finally, a displacement plan is born in `NOTICE_PENDING` status, one-to-one with the work order via its `work_order_id`: it copies `vehicles_to_move`, sets `access_block_start` to the scheduled date at `window_start_hour` UTC, and sets a provisional `access_block_end` to the scheduled date at `window_end_hour` UTC plus a forecast-based cure projection.

That cure projection works as follows. The base is the material's `cure_hours_vehicle`. The latest weather snapshot for the scheduled date — latest by creation, observed preferred over forecast on ties — is consulted: if its minimum temperature is below 55 degrees Fahrenheit, the base is multiplied by 1.5 and rounded up to whole hours; if its precipitation amount is greater than zero millimeters, 12 hours are added on top; if no snapshot exists for the date, the base stands unadjusted.

Rescheduling a weather-held work order replays the entire scheduling ceremony against a new `route_sheet_id`, `scheduled_date`, window hours, and `drive_minutes_est` — the same gate set, the same error codes — with the OCC guard of §2.6 layered on. The compensating side releases the old booking first: the old sheet's booked area and drive minutes shrink, the old lot's reservation returns and its ledger recomputes, and then the new booking, reservation, and cascades apply exactly as a fresh schedule. The displacement plan's access-block window is recomputed, and a plan in `NOTICE_SENT`, `CLEARED`, or `STALE` resets to `NOTICE_PENDING` with `notice_sent_at` cleared, because occupants must be re-notified against the new window.

Cancelling a work order — allowed from `PENDING`, `SCHEDULED`, or `WEATHER_HOLD`, else `ERR_WORK_ORDER_NOT_CANCELLABLE` — runs the mirror-image compensation: the sheet's booking releases and its open capacity recomputes; the lot's `reserved_gallons` drops by the reservation, the work order's reservation zeroes, the lot ledger recomputes (which may clear the reorder flag), and a lot left `IN_USE` with both reserved and consumed gallons at zero returns to `RECEIVED`; the displacement plan, whatever its state, moves to `CANCELLED`.

A route sheet itself may be cancelled from `OPEN`, `PUBLISHED`, or `WEATHER_HOLD`, but only while no work order on it sits in `SCHEDULED`, `WEATHER_HOLD`, `IN_PROGRESS`, or `CURING` — otherwise `ERR_ROUTE_SHEET_NOT_CANCELLABLE`. Sheets close lazily: when read or written after their service date has passed with no work order remaining in an active state, they settle to `COMPLETED`.

### 3.6. Vehicle Displacement and the Notice Clock

Sealcoating a driveway or lot means nobody parks on it — during the work window and for the entire cure afterward. The displacement plan tracks this obligation. A `Dispatcher` sends the notice from `NOTICE_PENDING` or `STALE` (else `ERR_PLAN_NOT_NOTICABLE`), and the notice must go out with at least 48 hours of lead time: the current clock plus 48 hours must not be later than `access_block_start`, else `ERR_NOTICE_LEAD_TIME_SHORT`. Sending stamps `notice_sent_at`. Once occupants confirm the vehicles are moved, the dispatcher confirms the plan from `NOTICE_SENT` to `CLEARED` (from any other state, `ERR_PLAN_NOT_NOTICED`). The two staleness cascades — a weather hold on the owning work order, or a reschedule — push a notified or cleared plan back to `STALE`, forcing the notice cycle to run again before work can begin.

### 3.7. Execution: Start, Actuals, and the Cure Window

On the service date, a `CrewLead` starts the job. Starting requires `SCHEDULED` status (else `ERR_WORK_ORDER_NOT_STARTABLE`), requires the current clock date to equal `scheduled_date` (else `ERR_DATE_IN_PAST`), requires the displacement plan to be `CLEARED` (else `ERR_DISPLACEMENT_NOT_CLEARED`), re-runs the weather gate against the latest snapshot for today, and re-confirms the lot is still usable. The work order moves to `IN_PROGRESS` and `started_at` is stamped.

When the application is done, the crew lead records what actually happened: `actual_area_sqft`, `actual_crack_ft`, `actual_pothole_area_sqft`, `actual_stripe_ft`, and `gallons_used`. The gallons drawn may not exceed the work order's reservation (else `ERR_INSUFFICIENT_MATERIAL`); finishing requires `IN_PROGRESS` (else `ERR_WORK_ORDER_NOT_FINISHABLE`). Finishing stamps `finished_at` and computes `cure_until` by the same cure projection of §3.5, but in its observed variant — keyed to the finish date's latest snapshot rather than the scheduled date's forecast. The displacement plan's `access_block_end` finalizes to `cure_until`, so the access block now reflects real chemistry. Simultaneously the lot ledger settles: the reservation is released in full, `consumed_gallons` grows by `gallons_used`, the work order's `reserved_gallons` zeroes, and on-hand gallons and the reorder flag recompute. The work order rests in `CURING`.

Completion — again by the crew lead — requires `CURING`, requires the current clock to have reached `cure_until` (else `ERR_CURE_INCOMPLETE`), and, when striping was in scope, requires the striping dimension to have reached `VERIFIED` (else `ERR_STRIPING_NOT_VERIFIED`). Completion stamps `completed_at`, moves execution to `COMPLETED`, and fans out three consequences. First, an invoice is born in `DRAFT` (§3.9) — priced on actual measurements for ordinary jobs, zeroed line-by-line for warranty repairs so its total is exactly zero cents. Second, for non-warranty jobs, a warranty record is born `ACTIVE` (§3.10). Third, for non-warranty seal jobs, the property's seal-cycle dates advance and its `version` increments, as described in §3.1. For warranty-repair completions, the originating claim resolves and its warranty record is exhausted, per §3.10. A completed work order whose invoice reaches `PAID` closes automatically, moving execution to `CLOSED`.

### 3.8. Striping: The Commercial-Lot Dimension

Striping runs its own approval chain because it is a layout discipline, not just labor. An `Estimator` submits the plan by supplying `stall_count`, the commercial stall count the work order records; planning requires the work order's `include_striping` to be true and its striping status to be `PLANNING` (else `ERR_STRIPING_NOT_PLANNABLE`), and requires the property to be a commercial lot (else `ERR_STRIPING_COMMERCIAL_ONLY`). Planning computes the accessible-stall requirement: 25 stalls or fewer require 1 accessible stall; 26 through 50 require 2; 51 through 75 require 3; 76 through 100 require 4 — and exactly 100 stalls is 4, since the overflow formula starts at 101. Beyond 100, add one accessible stall for each additional block of 50 stalls or fraction thereof. The computed `ada_stalls_required` feeds `stripe_linear_ft_computed`: 18 linear feet per stall plus 40 linear feet per accessible stall.

The estimator then approves the layout (`PLANNED → APPROVED`), the crew lead marks it applied (`APPROVED → APPLIED`, requiring execution to be in `CURING` or `COMPLETED`, else `ERR_WORK_ORDER_NOT_FINISHABLE`), and the estimator verifies the finished markings (`APPLIED → VERIFIED`). Each step rejects from the wrong state with `ERR_STRIPING_NOT_PLANNABLE`. Only `VERIFIED` striping releases the completion gate of §3.7.

### 3.9. Invoicing and Settlement: Final Pricing on Actuals

The invoice born at completion settles the job on what the crew measured, not what the estimator estimated. Its `line_items` recompute the four scope lines — seal, crack fill, patch, striping — using the identical tier rates, grade factors, per-unit rates, and per-line half-up rounding of the quote, but applied to `actual_area_sqft`, `actual_crack_ft`, `actual_pothole_area_sqft`, and `actual_stripe_ft`. The evaluation order is pinned: round each line to integer cents first; then a mobilization line of 7500 cents joins when the sum of those four rounded lines is strictly below 200000 cents (invoices carry no discount — the negotiated discount already lived on the quote); the invoice's `subtotal_cents` is the sum of the rounded lines plus the mobilization line; a fuel surcharge tier is then keyed on that rounded subtotal — 6 percent when below 100000 cents, 4 percent when at least 100000 but below 500000, 2 percent when at least 500000 — and `fuel_surcharge_cents` is the rounded-half-up product; `total_cents` is the subtotal plus the surcharge. Implementations that sum unrounded line values, or key the surcharge tier off an unrounded sum, produce different cents and are non-conformant.

An `OfficeAdmin` issues a `DRAFT` invoice (else `ERR_INVOICE_NOT_ISSUABLE`), stamping `issued_at` and flipping the work order's billing dimension to `INVOICED`. Payment — by the owning customer or an `OfficeAdmin` — requires `ISSUED` (else `ERR_INVOICE_NOT_PAYABLE`), and the tendered `amount_cents` must equal the invoice's `total_cents` exactly (else `ERR_PAYMENT_AMOUNT_MISMATCH`). Payment stamps `paid_at`, moves billing to `PAID`, and closes a `COMPLETED` work order as described in §3.7.

### 3.10. Warranty: Coverage, Claims, and Segregation of Duties

Every completed non-warranty job grants a warranty record: `started_on` set to the completion date, `warranty_months` taken from the material and extended by 6 months when the job applied two coats, and `expires_on` computed by adding those calendar months to the start date. The record is born `ACTIVE`.

A customer files a claim by naming the `warranty_record_id`, a `claim_type` of `CRACK_RECURRENCE`, `PEELING`, or `FADE`, and a `description`. Filing requires the record to be `ACTIVE` (else `ERR_WARRANTY_NOT_ACTIVE`) and the acting customer to own the warranty's property (else `ERR_NOT_RESOURCE_OWNER`). If the current clock date has passed `expires_on`, the record lazily flips to `EXPIRED` and the filing fails with `ERR_WARRANTY_EXPIRED`. A successful filing moves the record to `CLAIM_OPEN`.

An `OfficeAdmin` opens the investigation, moving the claim from `OPEN` to `INVESTIGATING` (else `ERR_CLAIM_NOT_OPEN`) and recording their identity in `investigated_by`. Adjudication is segregated: whichever admin approves or denies the claim must be a different person than the investigator, and a matching identity is rejected with `ERR_SEGREGATION_OF_DUTIES`. Denial moves the claim to `DENIED` and returns the warranty record from `CLAIM_OPEN` to `ACTIVE`. Approval moves the claim to `APPROVED` and materializes a warranty-repair work order: execution `PENDING`, `warranty_claim_id` pointing back at the claim, `quoted_area_sqft` taken from the original work order's actual area, `quoted_total_cents` zeroed, scope flags copied from the original job, `coats` fixed at 1, and striping `NOT_REQUIRED`. The claim's `repair_work_order_id` records the new work order.

From there the repair re-enters the ordinary machinery: scheduling it (exempt from the re-application interval) moves the claim from `APPROVED` to `REPAIR_SCHEDULED`, and its completion moves the claim to `RESOLVED` while the warranty record exhausts from `CLAIM_OPEN` to `EXHAUSTED`.

### 3.11. Weather Postings, Utilization, and the Clock

An `OfficeAdmin` or `Dispatcher` posts weather snapshots carrying `target_date`, `min_temp_f`, `max_temp_f`, `precip_probability_pct`, `precipitation_mm` (zero or greater), and a `source` of `FORECAST` or `OBSERVED`. Beyond feeding the scheduling and cure gates, a failing snapshot that is the latest for its date drives the hold cascade of §2.8.

For capacity planning, an `OfficeAdmin` or `Dispatcher` may read a crew's utilization for any calendar `month`. The report covers the crew's sheets whose service date falls in that month, excluding cancelled sheets, and sums their `capacity_sqft` into the month's capacity. Two percentages are always returned together, each rounded half-up to one decimal place — and both are zero when the month's capacity sums to zero. The projected figure divides by that capacity the summed `quoted_area_sqft` of work orders in scheduled, weather-held, in-progress, curing, or completed states: forward-looking booked demand, including jobs that have not run yet. The realized figure instead sums `actual_area_sqft` over completed and closed work orders only. A month of scheduled-but-unfinished work therefore reads high on projected and low on realized, which is exactly the signal dispatch uses when deciding how aggressively to book the remaining season.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, preconditions, and side effects for every endpoint are specified by the narratives in §2 and §3; the table below is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical server clock | OfficeAdmin |
| POST | `/api/customers` | Register a customer | OfficeAdmin |
| GET | `/api/customers` | List customers (paginated) | OfficeAdmin, Estimator, Dispatcher, CrewLead |
| GET | `/api/customers/{customerId}` | Get one customer | OfficeAdmin, Estimator, Dispatcher, CrewLead, Customer |
| POST | `/api/properties` | Register a property for a customer | OfficeAdmin |
| GET | `/api/properties` | List properties, optionally filtered by customer | OfficeAdmin, Estimator, Dispatcher, CrewLead, Customer |
| GET | `/api/properties/{propertyId}` | Get one property (computed area, open quote, seal-cycle dates, version) | OfficeAdmin, Estimator, Dispatcher, CrewLead, Customer |
| POST | `/api/assessments` | Create a site assessment (DRAFT); computes the condition index | Estimator |
| GET | `/api/assessments` | List assessments, filterable by property and status | OfficeAdmin, Estimator, Dispatcher, CrewLead, Customer |
| GET | `/api/assessments/{assessmentId}` | Get one assessment | OfficeAdmin, Estimator, Dispatcher, CrewLead, Customer |
| POST | `/api/assessments/{assessmentId}/submit` | Submit an assessment; supersedes prior submission, refreshes property area | Estimator |
| POST | `/api/materials` | Register a sealer product | OfficeAdmin |
| GET | `/api/materials` | List materials | OfficeAdmin, Estimator, Dispatcher, CrewLead |
| GET | `/api/materials/{materialId}` | Get one material | OfficeAdmin, Estimator, Dispatcher, CrewLead |
| POST | `/api/material-lots` | Receive a material lot into inventory | OfficeAdmin |
| GET | `/api/material-lots` | List lots, filterable by material and status | OfficeAdmin, Dispatcher |
| GET | `/api/material-lots/{lotId}` | Get one lot (ledger fields) | OfficeAdmin, Dispatcher |
| POST | `/api/material-lots/{lotId}/quarantine` | Quarantine a lot (quality hold) | OfficeAdmin |
| POST | `/api/material-lots/{lotId}/record-waste` | Record spilled/unusable gallons against a lot | OfficeAdmin |
| POST | `/api/crews` | Register a crew | OfficeAdmin |
| GET | `/api/crews` | List crews | OfficeAdmin, Dispatcher |
| GET | `/api/crews/{crewId}` | Get one crew | OfficeAdmin, Dispatcher |
| GET | `/api/crews/{crewId}/utilization` | Monthly projected vs realized utilization | OfficeAdmin, Dispatcher |
| POST | `/api/route-sheets` | Create a route sheet for a crew on a date | Dispatcher |
| GET | `/api/route-sheets` | List route sheets, filterable by crew, date, status | OfficeAdmin, Dispatcher, CrewLead |
| GET | `/api/route-sheets/{routeSheetId}` | Get one route sheet (booked/open capacity, drive minutes) | OfficeAdmin, Dispatcher, CrewLead |
| POST | `/api/route-sheets/{routeSheetId}/publish` | Publish an OPEN sheet (or re-publish a WEATHER_HOLD sheet) | Dispatcher |
| POST | `/api/route-sheets/{routeSheetId}/cancel` | Cancel a sheet with no non-terminal work orders | Dispatcher |
| POST | `/api/quotes` | Create a quote (DRAFT) from a SUBMITTED assessment; OCC on the property | Estimator |
| GET | `/api/quotes` | List quotes, filterable by property, assessment, material, status | OfficeAdmin, Estimator, Dispatcher, Customer |
| GET | `/api/quotes/{quoteId}` | Get one quote (computed pricing fields) | OfficeAdmin, Estimator, Dispatcher, Customer |
| PATCH | `/api/quotes/{quoteId}` | Revise a DRAFT or REVISION_REQUESTED quote; recomputes pricing | Estimator |
| POST | `/api/quotes/{quoteId}/send` | Send a DRAFT quote to the customer | Estimator |
| POST | `/api/quotes/{quoteId}/accept` | Customer accepts a SENT quote; creates the work order | Customer |
| POST | `/api/quotes/{quoteId}/decline` | Customer declines a SENT quote | Customer |
| POST | `/api/quotes/{quoteId}/request-revision` | Customer asks for changes on a SENT quote | Customer |
| GET | `/api/work-orders` | List work orders; multi-filter list | OfficeAdmin, Estimator, Dispatcher, CrewLead, Customer |
| GET | `/api/work-orders/{workOrderId}` | Get one work order (all three state dimensions) | OfficeAdmin, Estimator, Dispatcher, CrewLead, Customer |
| POST | `/api/work-orders/{workOrderId}/schedule` | Schedule a PENDING work order; runs all gates; reserves gallons | Dispatcher |
| POST | `/api/work-orders/{workOrderId}/reschedule` | Move a WEATHER_HOLD work order to a new sheet/date; OCC on the work order | Dispatcher |
| POST | `/api/work-orders/{workOrderId}/start` | Crew starts a SCHEDULED work order on its service date | CrewLead |
| POST | `/api/work-orders/{workOrderId}/finish-application` | Record actuals and gallons; enters cure | CrewLead |
| POST | `/api/work-orders/{workOrderId}/complete` | Complete after cure; generates invoice and warranty | CrewLead |
| POST | `/api/work-orders/{workOrderId}/cancel` | Cancel a non-started work order; compensating releases | Dispatcher |
| GET | `/api/displacement-plans` | List displacement plans, filterable by work order and status | OfficeAdmin, Dispatcher, CrewLead, Customer |
| GET | `/api/displacement-plans/{planId}` | Get one displacement plan | OfficeAdmin, Dispatcher, CrewLead, Customer |
| POST | `/api/displacement-plans/{planId}/send-notice` | Send (or re-send) the vehicle-displacement notice; 48h lead time | Dispatcher |
| POST | `/api/displacement-plans/{planId}/confirm-cleared` | Confirm vehicles cleared and access free | Dispatcher |
| POST | `/api/work-orders/{workOrderId}/striping/plan` | Submit stall count; computes ADA stalls and striping footage | Estimator |
| POST | `/api/work-orders/{workOrderId}/striping/approve` | Approve the striping layout | Estimator |
| POST | `/api/work-orders/{workOrderId}/striping/mark-applied` | Crew marks striping applied | CrewLead |
| POST | `/api/work-orders/{workOrderId}/striping/verify` | Estimator verifies applied striping | Estimator |
| GET | `/api/invoices` | List invoices, filterable by work order and status | OfficeAdmin, Customer |
| GET | `/api/invoices/{invoiceId}` | Get one invoice | OfficeAdmin, Customer |
| POST | `/api/invoices/{invoiceId}/issue` | Issue a DRAFT invoice to the customer | OfficeAdmin |
| POST | `/api/invoices/{invoiceId}/pay` | Pay an ISSUED invoice in full | OfficeAdmin, Customer |
| GET | `/api/warranty-records` | List warranty records, filterable by work order and property | OfficeAdmin, Dispatcher, Customer |
| GET | `/api/warranty-records/{recordId}` | Get one warranty record | OfficeAdmin, Dispatcher, Customer |
| POST | `/api/warranty-claims` | Customer files a claim against an ACTIVE, unexpired warranty | Customer |
| GET | `/api/warranty-claims` | List claims, filterable by warranty record and status | OfficeAdmin, Dispatcher, Customer |
| GET | `/api/warranty-claims/{claimId}` | Get one claim | OfficeAdmin, Dispatcher, Customer |
| POST | `/api/warranty-claims/{claimId}/investigate` | Open investigation; records the investigating admin | OfficeAdmin |
| POST | `/api/warranty-claims/{claimId}/approve` | Approve a claim (different admin than investigator); creates repair work order | OfficeAdmin |
| POST | `/api/warranty-claims/{claimId}/deny` | Deny a claim (different admin than investigator); warranty returns to ACTIVE | OfficeAdmin |
| POST | `/api/weather-snapshots` | Post a forecast/observation; may cascade sheets into WEATHER_HOLD | OfficeAdmin, Dispatcher |
| GET | `/api/weather-snapshots` | List weather snapshots, filterable by target date | OfficeAdmin, Dispatcher, CrewLead |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_WINDOW_HOURS` | 400 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_MATERIAL_NOT_FOUND` | 404 |
| `ERR_MATERIAL_LOT_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_ROUTE_SHEET_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_DISPLACEMENT_PLAN_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_WARRANTY_RECORD_NOT_FOUND` | 404 |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ASSESSMENT_NOT_SUBMITTABLE` | 409 |
| `ERR_ASSESSMENT_NOT_USABLE` | 422 |
| `ERR_ASSESSMENT_EXPIRED` | 422 |
| `ERR_ASSESSMENT_PROPERTY_MISMATCH` | 422 |
| `ERR_QUOTE_NOT_EDITABLE` | 409 |
| `ERR_QUOTE_NOT_SENDABLE` | 409 |
| `ERR_QUOTE_NOT_ACCEPTABLE` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_STRIPING_COMMERCIAL_ONLY` | 422 |
| `ERR_STRIPING_NOT_PLANNABLE` | 409 |
| `ERR_STRIPING_NOT_VERIFIED` | 409 |
| `ERR_PRICE_BELOW_COST_FLOOR` | 422 |
| `ERR_WEATHER_DATA_MISSING` | 422 |
| `ERR_WEATHER_WINDOW_VIOLATION` | 422 |
| `ERR_OUTSIDE_SEASON` | 422 |
| `ERR_DATE_IN_PAST` | 422 |
| `ERR_RESEAL_INTERVAL_NOT_MET` | 422 |
| `ERR_ROUTE_SHEET_NOT_SCHEDULABLE` | 409 |
| `ERR_ROUTE_SHEET_NOT_PUBLISHABLE` | 409 |
| `ERR_ROUTE_SHEET_NOT_CANCELLABLE` | 409 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 |
| `ERR_ROUTE_DRIVE_LIMIT_EXCEEDED` | 409 |
| `ERR_CREW_WINDOW_OVERLAP` | 409 |
| `ERR_ACCESS_WINDOW_OVERLAP` | 409 |
| `ERR_MATERIAL_LOT_UNAVAILABLE` | 409 |
| `ERR_MATERIAL_LOT_IN_USE` | 409 |
| `ERR_INSUFFICIENT_MATERIAL` | 422 |
| `ERR_WORK_ORDER_NOT_SCHEDULABLE` | 409 |
| `ERR_WORK_ORDER_NOT_STARTABLE` | 409 |
| `ERR_WORK_ORDER_NOT_FINISHABLE` | 409 |
| `ERR_WORK_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_DISPLACEMENT_NOT_CLEARED` | 409 |
| `ERR_PLAN_NOT_NOTIFIABLE` | 409 |
| `ERR_PLAN_NOT_NOTICED` | 409 |
| `ERR_NOTICE_LEAD_TIME_SHORT` | 422 |
| `ERR_CURE_INCOMPLETE` | 422 |
| `ERR_INVOICE_NOT_ISSUABLE` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_WARRANTY_NOT_ACTIVE` | 409 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_CLAIM_NOT_OPEN` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
