# Water Treatment Chemical Service API — Product Requirements Document

## 1. Introduction

Industrial water systems — cooling towers, boilers, and closed loops — fail slowly and expensively when their chemistry drifts: scale insulates heat-transfer surfaces, corrosion eats metallurgy, and under-chlorinated warm water breeds Legionella. The service provider who maintains these systems runs a recurring field operation: survey the system, design a treatment program, keep chemical feed pumps dosed correctly, visit each asset on a testing route, hang corrosion coupons in sidestream racks, maintain a Legionella risk plan per asset, log blowdown to prove water savings, and keep chemical totes full through scheduled deliveries and exchanges. Commercially, two pricing models coexist: some customers buy a flat monthly service contract with discounted product, others buy product alone at list price.

This document specifies the API that runs that operation end to end. It governs the full arc from system survey and program design through chemical feed-rate and inventory telemetry, water-testing routes with result trending, the corrosion and scale coupon program, Legionella risk management, blowdown and water-savings reporting, chemical delivery with tote exchange, and the dual-variant invoicing that bills each account under its contracted pricing model. The system is built around a logical clock (test-driving, not wall-clock), a derived compliance posture that gates field work, optimistic concurrency on the three writes where stale snapshots cause real damage, and a strictly ordered validation pipeline. All resources are mounted under the `/wt` prefix.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose `X-User-Role` value is not one of the declared roles, or whose role is not permitted to call the target endpoint, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Four roles exist, spelled exactly as follows:

- `PlatformAdmin` — operator of the service platform; owns the chemical product catalog and the logical clock.
- `AccountManager` — commercial owner of customer accounts; owns account lifecycle, delivery orders, and invoicing.
- `WaterChemist` — field service chemist; owns surveys, program designs, feed stations, telemetry, test routes, results, coupons, Legionella plans, blowdown logging, and delivery execution.
- `CustomerContact` — the industrial customer acting on its own account; accepts or requests revision of program designs and pays invoices.

The identity semantics of `X-User-ID` differ by role. When `X-User-Role` is `PlatformAdmin`, `AccountManager`, or `WaterChemist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `recorded_by_user_id` on a `CorrectiveAction`, where a `WaterChemist`'s identifier anchors segregation of duties — but it is never compared to any entity's `id`. When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource compare the resource's owning-account reference to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403). This ownership rule governs program-design acceptance, revision requests, invoice payment, and every `GET` performed by a `CustomerContact`, whose reads are scoped to its own account subtree.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0.

Unless a specific endpoint states a different ordering, every list endpoint returns resources sorted by `created_at` in ascending order. Three lists pin their own ordering: telemetry readings of a station are returned by `recorded_at` ascending with `created_at` ascending as the tie-break; the stops of a route are returned by `sequence_index` ascending; blowdown events of an asset are returned by `occurred_at` ascending.

The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

All time-sensitive behavior in the system — visit windows, validation due dates, invoice aging, telemetry freshness, blowdown windows — is measured against a server-side **logical clock**, never against wall-clock time. Before any call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must not fall back to wall-clock time under any circumstance.

A `PlatformAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc` value. Setting the clock is not a passive act: the new instant drives two automatic sweeps. First, every Legionella risk plan in `ACTIVE` status whose `validation_due_at` has been reached or passed by the new clock transitions to `VALIDATION_DUE`. Second, every invoice in `ISSUED` status that remains unpaid transitions to `OVERDUE` when the new clock is strictly later than thirty days after its `period_end`. Timestamps supplied by clients — telemetry `recorded_at`, blowdown `occurred_at`, coupon `installed_at`, delivery `scheduled_for` — are all validated against this logical clock.

### 2.5. Common Resource Properties and Identity Conventions

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID, with no type prefix, assigned at creation.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that increments by one on every mutation of the resource; this is the field optimistic concurrency control reads.

Three record types are deliberately thinner: `TelemetryReading`, `WaterTestResult`, and `BlowdownEvent` carry only `id` and `created_at`. They have no `updated_at` and no `version`; they are append-only measurements and events, and none of them participates in optimistic concurrency.

Every mutation of a resource — including system-driven changes to computed fields such as a station's `setpoint_ml_per_min`, an asset's `posture`, or an account's `open_balance_cents` — refreshes that resource's `updated_at` and increments its `version`.

### 2.6. Validation Pipeline and Priority Ordering

Every request passes through a single validation pipeline of fifteen tiers, evaluated strictly in ascending priority order. The first tier whose check fails determines the error response; later tiers are never consulted for that request. This ordering is load-bearing: a request that would fail at two tiers surfaces the earlier tier's error.

1. **Header presence.** `X-User-ID` and `X-User-Role` must both be present and non-empty; failure is `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to all endpoints.
2. **Role authorization.** `X-User-Role` must be one of the four declared roles and permitted for the target endpoint; failure is `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Applies to all endpoints.
3. **Customer ownership.** For a `CustomerContact` caller, `X-User-ID` must equal the `id` of the `CustomerAccount` that owns the target resource; failure is `ERR_FORBIDDEN` (HTTP 403). Applies to program-design acceptance, revision requests, invoice payment, and all `CustomerContact` reads.
4. **Existence.** Every path identifier must resolve to an existing resource, validated left-to-right across path segments, and then every foreign-key-valued body field must resolve, validated in the body's declared input order; the first unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404). Applies to all endpoints.
5. **Request shape.** The body must contain all required input fields with correct primitive types, and every enum value must be a member of its declared enum set; failure is `ERR_INVALID_REQUEST` (HTTP 400). Applies to all endpoints.
6. **Transition legality.** The target resource must be in a state from which the requested transition is declared; failure is `ERR_INVALID_STATE` (HTTP 409). Applies to all action endpoints.
7. **Cross-entity state gates.** Operations that depend on a related resource's state fail here: arriving at a stop requires its route to be `PUBLISHED` (`ERR_ROUTE_NOT_PUBLISHED`); scheduling a delivery requires an `ACCEPTED` program design on the destination asset (`ERR_PROGRAM_NOT_ACCEPTED`) and an `ACTIVE` account (`ERR_ACCOUNT_NOT_ACTIVE`); activating a Legionella plan requires the asset to be `IN_SERVICE` (`ERR_ASSET_NOT_IN_SERVICE`); and any operation gated by a `FROZEN` asset posture — arriving at a stop, approving a corrective action, recording a water test result — fails with `ERR_ASSET_FROZEN`. All are HTTP 409.
8. **Legionella safety gate.** Approving a corrective action while the asset's Legionella plan is `SUSPENDED` is rejected with `ERR_LEGIONELLA_PLAN_SUSPENDED` (HTTP 409). Recording a water test result on an asset whose plan is `DELINQUENT` remains allowed, but the result feeds the asset's posture as described in §2.8.
9. **Segregation of duties.** The `X-User-ID` approving or declining a corrective action must differ from the action's `recorded_by_user_id`; failure is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
10. **Field-range and shape constraints.** Scalar constraints on create payloads fail with `ERR_FIELD_CONSTRAINT` (HTTP 422): `proposed_coc` must lie between 1.5 and 12.0 inclusive; the pH control band must satisfy `ph_min` at least 6.0, `ph_max` at most 10.0, and `ph_min` strictly below `ph_max`; `active_pct` must be greater than 0 and at most 100; `contract_price_cents_per_gal` must not exceed `unit_price_cents_per_gal`; `sequence_index` must be unique within its route; `position_index` must not exceed the rack's `position_count`; `asset_tag` must be unique per account; `product_code` must be unique across the catalog. A delivery `quantity_gal` that is not a positive whole multiple of the destination product's `container_size_gal` carries its own code, `ERR_QUANTITY_NOT_CONTAINER_MULTIPLE` (HTTP 422). Applies to all create endpoints.
11. **Temporal rules.** Time-bearing operations fail with their domain codes (all HTTP 422): arriving outside the half-open visit window bounded by `window_start` inclusive and `window_end` exclusive is `ERR_OUTSIDE_VISIT_WINDOW`; marking a stop missed before its `window_end` has been reached is `ERR_WINDOW_NOT_ELAPSED`; a `scheduled_for` that is not strictly in the future is `ERR_SCHEDULE_IN_PAST`; dispatch before `scheduled_for` is `ERR_TOO_EARLY_TO_DISPATCH`; telemetry with `recorded_at` later than the current clock is `ERR_TELEMETRY_FUTURE`; a blowdown `occurred_at` that is not strictly after the previous event on the same asset is `ERR_NON_MONOTONIC_EVENT`; declaring delinquency before the grace period has elapsed is `ERR_GRACE_NOT_ELAPSED`; and coupon exposure shorter than one full day is `ERR_EXPOSURE_TOO_SHORT`.
12. **Resource temporal overlap.** Two interval regimes live at this tier (both HTTP 409): a new route stop whose visit window overlaps another stop on the same asset under the half-open rules of §3.4 is `ERR_WINDOW_CONFLICT`; a new coupon whose install interval violates the closed-interval-plus-buffer rules of §3.6 on the same rack position is `ERR_COUPON_INTERVAL_CONFLICT`. Same tier, different resources and different interval semantics.
13. **Referential integrity.** Cross-references must be coherent (HTTP 409): a recorded result's `asset_id` must equal its stop's `asset_id` (`ERR_ASSET_MISMATCH`); coupons may only be installed on a rack that is `INSTALLED`, not `ARCHIVED` (`ERR_RACK_ARCHIVED`); a delivery order's destination station must not be `LOCKED_OUT` (`ERR_STATION_LOCKED_OUT`); and any station or order referencing a `DELISTED` product is rejected (`ERR_PRODUCT_DELISTED`).
14. **Fiscal gates.** An account on `credit_hold` cannot have deliveries scheduled (`ERR_CREDIT_HOLD`, HTTP 409), and an account cannot be closed while its `open_balance_cents` is non-zero (`ERR_UNPAID_BALANCE`, HTTP 409).
15. **Optimistic concurrency.** On the three OCC-guarded writes enumerated in §2.7, the supplied expected-version field must equal the parent resource's current `version`; a mismatch is `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Optimistic Concurrency Control

Three writes, and only these three, require the caller to prove it has observed the current state of the resource it acts upon. Each takes a non-optional expected-version field carrying the caller's last observed `version` of the relevant parent entity; if that value no longer equals the entity's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here take no version field.

- **Program design acceptance.** A `POST /wt/program-designs/{designId}/accept` request must carry `expected_program_design_version` equal to the design's current `version`. The classic stale case: another writer has just accepted a different design for the same asset, superseding this one's siblings and advancing versions, leaving this client's view of the design stale.
- **Corrective action approval.** A `POST /wt/corrective-actions/{actionId}/approve` request must carry `expected_feed_station_version` equal to the target feed station's current `version`. The stale case: another writer has applied a setpoint change to the same station, so this client's intended delta was computed against a baseline it has not observed.
- **Delivery scheduling.** A `POST /wt/delivery-orders/{orderId}/schedule` request — both the initial scheduling and rescheduling after a failed delivery — must carry `expected_delivery_order_version` equal to the order's current `version`. The stale case: another writer has rescheduled the order and this client's chosen slot was computed from a stale order snapshot.

### 2.8. Asset Posture — the Derived Compliance Dimension

Alongside its lifecycle `status`, every `SystemAsset` carries a derived parallel dimension, `posture`, taking values `COMPLIANT`, `WATCH`, `NON_COMPLIANT`, or `FROZEN`. Posture is never set directly; it is recomputed from drivers across the system, and it gates child operations. An asset begins at `COMPLIANT`.

The drivers are: creation of a water test result (an `OUT_OF_RANGE` result moves a `COMPLIANT` asset to `WATCH`, and pushes the asset to `NON_COMPLIANT` once the consecutive out-of-range count reaches the escalation threshold of §3.5); application of a corrective action (posture recomputed from the reset counter); a Legionella plan transitioning to `DELINQUENT` (posture becomes `NON_COMPLIANT`); a Legionella plan transitioning to `SUSPENDED` (posture becomes `FROZEN`); suspension of the owning account (posture becomes `FROZEN`); and recovery paths — account reactivation, plan validation, or an `IN_RANGE` result — each recompute posture, returning the asset toward `COMPLIANT` when no other driver holds it down (for example, plan validation with a zero violation count restores `COMPLIANT`).

A `FROZEN` posture is a hard gate: no water test result may be recorded on the asset, no delivery order for the asset may be scheduled, and no corrective action may be approved — each rejected with `ERR_ASSET_FROZEN` as described in §2.6.

### 2.9. Units, Precision, and Rounding

All stored decimal values follow pinned precision rules, and every rounding in the system is **round half up**. The Langelier Saturation Index (`lsi_provisional`, `lsi_final`) is stored to 2 decimal places, with all intermediate terms held at full double precision until the final store. Feed-rate setpoints (`setpoint_ml_per_min`) and the telemetry consumption rate (`consumption_rate_gal_per_day`) are stored to 4 decimal places. Water-balance quantities on blowdown events (`evaporation_gal`, `balance_residual_gal`, and the report's savings figures) are stored to 2 decimal places. Corrosion rates (`corrosion_rate_mpy`) are stored to 3 decimal places. Invoice money is integer cents: each delivery line is rounded half up to whole cents before any summation, and totals are integer sums of those rounded lines. Computed timestamps (`projected_depletion_at`, `validation_due_at`, `removed_at`) are expressed to whole seconds. Exposure durations are whole days of 86,400 seconds each, obtained by rounding the elapsed seconds down to a whole number of days.

### 2.10. Nested Path and Body Reference Resolution

Requests that address nested resources resolve identifiers in a fixed order: path segments first, strictly left to right, then foreign-key-valued body fields in the body's declared input order. The first identifier that does not resolve to an existing resource terminates the request with `ERR_NOT_FOUND` (HTTP 404); no later check runs. A request to record a result under a non-existent stop therefore fails on the stop before the system ever looks at the body's `asset_id`, and a blowdown logged under a non-existent asset never reaches payload validation.

---

## 3. Business Logic & Workflows

### 3.1. Customer Accounts and the Commercial Envelope

An `AccountManager` opens a relationship by creating a customer account with its legal `account_name`. Two commercial switches sit on the account. The `credit_hold` boolean — defaulting to `false` — is the fiscal gate: while it is set, no delivery for the account may be scheduled, and a scheduling attempt is rejected with `ERR_CREDIT_HOLD`. The `billing_model` enum — `PRODUCT` or `SERVICE_CONTRACT`, defaulting to `PRODUCT` — selects which invoice pricing variant applies to the account, as detailed in §3.9. New accounts are born `ACTIVE` with an `open_balance_cents` of zero; that balance is a computed figure, the sum of `invoice_total_cents` over the account's invoices currently in `ISSUED` or `OVERDUE` status. An account's lifecycle `status` runs `ACTIVE`, `SUSPENDED`, and the terminal `CLOSED`.

Suspension is the commercial kill-switch. Suspending an `ACTIVE` account — any other state is rejected with `ERR_INVALID_STATE` — cascades through the account's open logistics: every delivery order of the account still in `DRAFT`, `PENDING`, or `SCHEDULED` transitions to `CANCELLED`, releasing each scheduled order's tote allocation, and every asset of the account has its posture recomputed to `FROZEN`, which in turn blocks result recording, delivery scheduling, and corrective approvals per §2.8. Reactivation moves a `SUSPENDED` account back to `ACTIVE` and recomputes each asset's posture, thawing assets that have no other driver holding them down.

Closing an account is permitted only from `ACTIVE` and only when `open_balance_cents` is exactly zero; a non-zero balance is rejected with `ERR_UNPAID_BALANCE`. Closure decommissions every asset of the account, moving each to `DECOMMISSIONED`. The account list view supports filtering by `status`, and accounts are individually readable by all four roles — subject, for a `CustomerContact`, to the ownership rule of §2.1.

### 3.2. Assets, Surveys, and the Program Design Cycle

Field work begins when a `WaterChemist` registers a system asset under an account, supplying the owning `account_id`, a human `asset_tag` that must be unique within that account (for example, CT-1 or BLR-2), the `asset_type` — one of `COOLING_TOWER`, `BOILER`, or `CLOSED_LOOP` — the design `recirculation_rate_gpm` and `system_volume_gal`, both strictly positive, and the wetted `metallurgy`, one of `MILD_STEEL`, `COPPER_ALLOY`, `STAINLESS`, or `GALVANIZED`. Two hydraulic constants may be overridden at registration but rarely are: `evaporation_factor`, the fraction of recirculation evaporated per ten degrees Fahrenheit of cooling range, defaults to 0.0085, and `drift_factor`, the fraction lost to drift, defaults to 0.0002. A new asset enters `COMMISSIONING`, starts with `posture` `COMPLIANT`, runs on a baseline `target_coc` of 3.0 cycles of concentration, and carries a `consecutive_out_of_range_count` of zero. Asset list views accept `account_id` and `status` filters.

The treatment program for an asset is negotiated through a `ProgramDesign`, which a `WaterChemist` opens against an `asset_id` with optional `survey_notes`. The design's lifecycle is a cycle, not a line: `SURVEY_SCHEDULED` → `SURVEYED` → `DRAFTED` → `PROPOSED`, and from `PROPOSED` either forward to `ACCEPTED`, back into the cycle via `REVISE_REQUESTED`, or out to `WITHDRAWN`. `ACCEPTED` and `WITHDRAWN` are the terminal states; a design that has been `SUPERSEDED` by a newer acceptance is likewise final. A design's `revision_number` starts at 1 and increments by one each time the design cycles through `REVISE_REQUESTED` back to `SURVEYED`.

Recording the survey — `SURVEY_SCHEDULED` → `SURVEYED` — captures the chemist's `survey_notes`. Drafting the design — `SURVEYED` → `DRAFTED` — is where the chemistry is committed: the payload must set `proposed_coc` (between 1.5 and 12.0 inclusive), `inhibitor_target_ppm` (strictly positive), the pH control band `ph_min` and `ph_max` (with `ph_min` at least 6.0, `ph_max` at most 10.0, and the minimum strictly below the maximum), `conductivity_max_umhos` (a positive whole number), and the flat `service_rate_cents_per_month` quoted on this design (zero or more). A draft attempt missing any of these six parameters is rejected with `ERR_INCOMPLETE_DESIGN`. Proposing — `DRAFTED` → `PROPOSED` — freezes the draft into a customer-facing offer.

Acceptance belongs to the customer. A `CustomerContact` accepting a design must own the account that owns the design's asset — otherwise `ERR_FORBIDDEN` — and the request must carry `expected_program_design_version` matching the design's current `version`, per the OCC rule in §2.7; a stale value is rejected with `ERR_STALE_VERSION`. Acceptance is the pivot of the whole system, and its side effects are extensive: any *other* design of the same asset currently `ACCEPTED` transitions automatically to `SUPERSEDED`; the asset's `target_coc` is frozen to the accepted `proposed_coc`, ending the 3.0 baseline era; every feed station of the asset has its `setpoint_ml_per_min` recomputed by the feed-rate calculation of §3.3 against the new target; every station's `projected_depletion_at` is recomputed by the depletion projection of §3.3; and the accepted design's own `version` increments by one.

A customer who wants changes instead requests revision — `PROPOSED` → `REVISE_REQUESTED`, again ownership-checked with `ERR_FORBIDDEN` on failure — after which a `WaterChemist` reopens the survey, returning the design to `SURVEYED` and incrementing `revision_number` by one. A `WaterChemist` may also withdraw a `PROPOSED` design outright, moving it to `WITHDRAWN`. Any transition attempted from a state that does not declare it is rejected with `ERR_INVALID_STATE`. The designs list view supports `asset_id` and `status` filters.

Commissioning an asset — `COMMISSIONING` → `IN_SERVICE` — requires two proofs of readiness, each with its own error: at least one program design of the asset must be `ACCEPTED` (`ERR_NO_ACCEPTED_PROGRAM`), and at least one feed station of the asset must be `ONLINE` (`ERR_NO_ONLINE_FEED_STATION`). Commissioning recomputes the asset's posture, which starts the in-service era at `COMPLIANT`. Decommissioning — `IN_SERVICE` → `DECOMMISSIONED` — is refused while any coupon on any rack of the asset remains `INSTALLED` (`ERR_COUPONS_STILL_INSTALLED`) and while any route stop of the asset remains `SCHEDULED` or `ARRIVED` (`ERR_OPEN_ROUTE_STOPS`). Decommissioning cascades: every feed station of the asset transitions to `LOCKED_OUT`, and the asset's Legionella risk plan transitions to `SUSPENDED`.

### 3.3. Product Catalog, Feed Stations, and Telemetry

The `PlatformAdmin` maintains the chemical catalog. Each product carries a unique `product_code`, an `active_pct` giving the active-ingredient fraction as a percent strictly greater than 0 and at most 100, a nominal `container_size_gal` for its tote, and two price points in integer cents per gallon: the list `unit_price_cents_per_gal` and the service-contract `contract_price_cents_per_gal`, each zero or more, with the contract price never exceeding the list price. The `density_g_per_ml` used by feed-rate math defaults to 1.0. Products are born `LISTED`; delisting moves one to `DELISTED`, after which creating a feed station or a delivery order that references it is rejected with `ERR_PRODUCT_DELISTED`. Product reads (list, with an optional `status` filter, and detail) are open to `AccountManager`, `WaterChemist`, and `PlatformAdmin`.

A `WaterChemist` equips an asset by creating a feed station bound to an `asset_id` and a `product_id`, with a strictly positive `capacity_cap_ml_per_min` hardware cap and an optional `feed_mode` — `CONTINUOUS` or `SHOT_FEED`, defaulting to `CONTINUOUS` — which selects the feed-rate formula branch. A new station is `OFFLINE`, with `inventory_gal`, `consumption_rate_gal_per_day`, and `setpoint_ml_per_min` each at their default of 0, `last_telemetry_at` null, and `projected_depletion_at` null. The setpoint is computed by the feed-rate calculation at creation and is recomputed on design acceptance and corrective-action application.

The **feed-rate setpoint calculation** runs with a pinned evaluation order — evaporation, drift, blowdown, mode branch, clamp — and reads the asset's `recirculation_rate_gpm`, `evaporation_factor`, `drift_factor`, and current `target_coc`, the inhibitor target from the asset's `ACCEPTED` program design, the product's `active_pct`, and the station's own `feed_mode` and `capacity_cap_ml_per_min`. First, the evaporation flow in gallons per minute is the recirculation rate multiplied by the evaporation factor. Second, the drift flow is the recirculation rate multiplied by the drift factor. Third, the required blowdown flow is the greater of zero and the quantity: the evaporation flow divided by (`target_coc` minus one), minus the drift flow. Fourth, the mode branch: for a `CONTINUOUS` station the raw dose is `inhibitor_target_ppm` times the blowdown flow times 3,785.411 millilitres per gallon, divided by (`active_pct` times 100); for a `SHOT_FEED` station the raw dose is `inhibitor_target_ppm` times the blowdown flow times 3,785.411 times 1,440 — the minutes in a day, the whole day's dose delivered as one daily shot — divided by (`active_pct` times 100), with that result then divided by 1,440. Fifth, the clamp: the commanded `setpoint_ml_per_min` is the smaller of `capacity_cap_ml_per_min` and the greater of zero and the raw dose, stored to 4 decimal places rounded half up.

Bringing a station online moves it from `OFFLINE` to `ONLINE`, or from `LOCKED_OUT` back to `ONLINE`; both are refused with `ERR_ASSET_DECOMMISSIONED` when the station's asset is `DECOMMISSIONED`, and from any other state with `ERR_INVALID_STATE`. Lockout moves an `ONLINE` station to `LOCKED_OUT`, which blocks new delivery orders referencing it per §3.9.

Once `ONLINE`, a station accepts telemetry: a `WaterChemist` appends readings carrying `recorded_at` (which must not be later than the current clock, else `ERR_TELEMETRY_FUTURE`), a non-negative stroke count `feed_pulses`, a strictly positive calibration volume `ml_per_pulse`, and a non-negative tote level `level_gal`. Posting to a station that is not `ONLINE` is rejected with `ERR_INVALID_STATE`. Each reading mutates the station: its `inventory_gal` is decremented by the reading's dosed volume (`feed_pulses` times `ml_per_pulse`, converted to gallons by dividing by 3,785.411), its `consumption_rate_gal_per_day` and `projected_depletion_at` are recomputed, and its `last_telemetry_at` is set to the reading's `recorded_at`.

The **inventory and depletion projection** works over a trailing seven-day window: the half-open interval from seven days before the current clock up to the current clock, with readings ordered by `recorded_at` ascending and ties broken by `created_at` ascending — never by `id`. Consumed gallons over the window are the sum of (`feed_pulses` times `ml_per_pulse`) across the window's readings, divided by 3,785.411. When at least one reading falls in the window, the span is taken as 7 days and `consumption_rate_gal_per_day` is the consumed gallons divided by 7, stored to 4 decimal places rounded half up; with no readings in the window the rate is 0. The station's `inventory_gal` reconciles deliveries against consumption: the sum of `delivered_gal` over the station's delivery orders in `DELIVERED` or `CLOSED` status, minus the sum of `returned_residual_gal` over its `CLOSED` orders, minus lifetime consumed gallons. The `projected_depletion_at` is the current clock plus (`inventory_gal` divided by the consumption rate) days, expressed to whole seconds, and is null while the consumption rate is 0. A projection landing within fourteen days of the current clock — the boundary inclusive — constitutes a depletion alert; §3.5 shows how that alert auto-drafts a replenishment order when a corrective action is applied.

### 3.4. Test Routes, Visit Windows, and Field Results

Route planning starts when a `WaterChemist` creates a test route for an account with an `account_id` and a `route_name` such as NORTH-TUESDAY; the route is born `PLANNED`. Stops are added while the route is `PLANNED` — adding to a route in any other state is `ERR_INVALID_STATE` — each stop carrying its owning `route_id` and naming the visited `asset_id`, a half-open visit window from `window_start` inclusive to `window_end` exclusive (with `window_end` strictly after `window_start`), and a `sequence_index` at least 1 and unique within the route. A new stop begins `SCHEDULED`. The route-stops list view supports `route_id`, `asset_id`, and `status` filters.

Stop windows on the same asset must not overlap under **half-open interval semantics**: a conflict exists when the new stop's `window_start` is strictly before an existing stop's `window_end` and that existing stop's `window_start` is strictly before the new stop's `window_end`. Back-to-back adjacency — the new `window_start` exactly equal to an existing `window_end` — is allowed. Only existing stops in `SCHEDULED` or `ARRIVED` status participate in the check; a violation is rejected with `ERR_WINDOW_CONFLICT`.

Publishing — `PLANNED` → `PUBLISHED` — requires at least one `SCHEDULED` stop on the route, failing with `ERR_EMPTY_ROUTE` otherwise. From there the route runs itself: when every stop of a `PUBLISHED` route has reached `SAMPLED`, `SKIPPED`, or `MISSED`, the route transitions automatically to `COMPLETED`. Cancelling is allowed from either `PLANNED` or `PUBLISHED` and moves the route to `CANCELLED`, cascading every still-`SCHEDULED` stop to `SKIPPED`.

In the field, the chemist arrives at a stop — `SCHEDULED` → `ARRIVED` — under four guards: the stop must be `SCHEDULED` (`ERR_INVALID_STATE`); the owning route must be `PUBLISHED` (`ERR_ROUTE_NOT_PUBLISHED`); the asset's posture must not be `FROZEN` (`ERR_ASSET_FROZEN`); and the current clock must be at or after `window_start` and strictly before `window_end` (`ERR_OUTSIDE_VISIT_WINDOW`). A stop never visited in its window is marked missed — `SCHEDULED` → `MISSED` — which is permitted only once the clock has reached `window_end`, failing earlier with `ERR_WINDOW_NOT_ELAPSED`.

At an `ARRIVED` stop, the chemist records a water test result against that stop's `stop_id`, supplying the sampled `asset_id` and the field measurements `ph` (between 0 and 14 inclusive), `conductivity_umhos` (a positive whole number), `calcium_ppm` and `alkalinity_ppm` (both strictly positive), `temperature_f` (strictly between 32 and 212), and `inhibitor_residual_ppm` (zero or more). The stop must be `ARRIVED` (`ERR_INVALID_STATE` on any other state); the asset must be `IN_SERVICE` (`ERR_ASSET_NOT_IN_SERVICE`) and its posture must not be `FROZEN` (`ERR_ASSET_FROZEN`); and the payload's `asset_id` must equal the stop's `asset_id` (`ERR_ASSET_MISMATCH`). Recording a result automatically advances the stop from `ARRIVED` to `SAMPLED`.

Each recorded result immediately carries a provisional Langelier Saturation Index, `lsi_provisional`, and a `classification`. The index is assembled from four intermediate terms held at full double precision. Term A: take the base-10 logarithm of the TDS value in ppm, subtract 1, and divide the difference by 10. Term B: convert `temperature_f` to Celsius by subtracting 32 and multiplying by five-ninths; term B is then negative 13.12 multiplied by the base-10 logarithm of (the Celsius temperature plus 273), plus 34.55. Term C: the base-10 logarithm of `calcium_ppm`, minus 0.4. Term D: the base-10 logarithm of `alkalinity_ppm`. The saturation pH is (9.3 plus A plus B) minus (C plus D), and the index is the measured `ph` minus that saturation pH, stored to 2 decimal places rounded half up. The `classification` follows the index bands: a value of 2.5 or higher is `SCALE_FORMING`, a value of negative 2.5 or lower is `CORROSIVE`, and anything strictly between those bounds is `BALANCED`. Both boundaries are inclusive — exactly 2.5 is scale-forming and exactly negative 2.5 is corrosive. In the provisional variant, used at recording time before any lab work returns, the TDS value is estimated as `conductivity_umhos` multiplied by 0.7.

Every result also carries a `range_status`, `IN_RANGE` or `OUT_OF_RANGE`, judged against the asset's accepted control ranges — the `ph_min`/`ph_max` band, `conductivity_max_umhos`, and `inhibitor_target_ppm` of the asset's `ACCEPTED` program design. This flag feeds the escalation cascade of §3.5 at the moment the result is created.

A result lives as `RECORDED` until laboratory TDS arrives. Confirmation — `RECORDED` → `CONFIRMED` — requires `lab_tds_ppm` in the payload (`ERR_LAB_TDS_REQUIRED` when absent) and fires the finalized variant of the index: `lsi_final` is computed exactly as the provisional, except the TDS value is the measured `lab_tds_ppm` rather than the conductivity estimate, so identical field inputs yield a different final index whenever the lab value differs from the estimate; `classification` is then recomputed from the final index's band. The `lab_tds_ppm` value is present only on `CONFIRMED` results, and `lsi_final` stays null until then. Voiding — `RECORDED` → `VOIDED` — retracts a bad sample and compensates everything the result had caused: if the result had contributed an `OUT_OF_RANGE` to the asset's counter, `consecutive_out_of_range_count` is decremented by one (never below zero) and the asset's posture is recomputed, and any corrective action still `PENDING` that names this result as its `triggering_result_id` transitions to `DECLINED`. The results list views support `asset_id` and `range_status` filters for trend review, and results are also listable per stop.

### 3.5. Escalation, Corrective Actions, and Segregation of Duties

Out-of-range chemistry escalates mechanically. When a result is created with `range_status` `OUT_OF_RANGE`, the asset's `consecutive_out_of_range_count` is incremented by one. If the count has reached the escalation threshold of 3 — note the boundary: the second consecutive violation does not escalate, the third does — the system auto-creates a corrective action in `PENDING` status with `triggering_result_id` set to this result and `recorded_by_user_id` set to the current request's `X-User-ID`, and the asset's posture becomes `NON_COMPLIANT`. Below the threshold, an `OUT_OF_RANGE` result moves a `COMPLIANT` asset to `WATCH`. When a result is created with `range_status` `IN_RANGE`, the counter is reset to 0 and the posture is recomputed, clearing `WATCH` when no other driver holds it.

A corrective action proposes a signed `setpoint_delta_ml_per_min` adjustment with a free-text `rationale`, both supplied at approval time. Approval — `PENDING` → `APPROVED` — is the most heavily gated write in the system, and its checks fall out of the global pipeline in this order: the action must be `PENDING` (`ERR_INVALID_STATE`); the asset's posture must not be `FROZEN` (`ERR_ASSET_FROZEN`); the asset's Legionella plan must not be `SUSPENDED` (`ERR_LEGIONELLA_PLAN_SUSPENDED`); the approving `X-User-ID` must differ from the action's `recorded_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`) — the chemist who recorded the triggering result may never approve the fix; and the request must carry `expected_feed_station_version` equal to the target station's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` per §2.7. Declining — `PENDING` → `DECLINED` — applies the same segregation-of-duties rule: the decliner must differ from the recorder.

Application — `APPROVED` → `APPLIED` — is where the delta bites. The target station's `setpoint_ml_per_min` is set to the smaller of its `capacity_cap_ml_per_min` and the greater of zero and (the current setpoint plus `setpoint_delta_ml_per_min`); the station's `consumption_rate_gal_per_day` and `projected_depletion_at` are recomputed; the asset's `consecutive_out_of_range_count` is reset to 0 and its posture recomputed. One more cascade fires here: if the recomputed `projected_depletion_at` falls within fourteen days of the current clock — the boundary inclusive — the system auto-creates a replenishment delivery order for this station in `DRAFT` status with `auto_drafted` set to `true` and a `quantity_gal` of exactly one `container_size_gal` of the station's product. The corrective-action list view supports `asset_id`, `status`, and `triggering_result_id` filters.

### 3.6. Corrosion Coupons and Rack Management

Corrosion monitoring runs on physical coupon racks installed in an asset's sidestream. A `WaterChemist` installs a rack by naming its `asset_id`, a `rack_code` unique within the asset, and a `position_count` between 1 and 8 inclusive; the rack is born `INSTALLED`. Archiving moves a rack from `INSTALLED` to `ARCHIVED`, after which installing coupons on it is rejected with `ERR_RACK_ARCHIVED`. Rack list views accept an `asset_id` filter.

Each position hosts one coupon at a time. Installing a coupon binds it to its hosting `rack_id` and takes the `position_index` (at least 1 and no more than the rack's `position_count`), the coupon `alloy` — `MILD_STEEL`, `COPPER`, `ADMIRALTY`, or `STAINLESS_304` — the `density_g_cm3` and exposed `area_in2` used by the corrosion math (both strictly positive), the strictly positive `pre_weight_g` at install, and the `installed_at` timestamp that opens the exposure interval. Coupons on the same rack and position follow **closed-interval semantics with a mandatory re-passivation buffer**, stricter than the route windows of §3.4: a new coupon conflicts — and is rejected with `ERR_COUPON_INTERVAL_CONFLICT` — when any existing coupon on the same rack and `position_index` is still `INSTALLED` (an installed coupon's interval is treated as open-ended), or when the new `installed_at` is earlier than an existing removed coupon's `removed_at` plus seven days of re-passivation buffer. Adjacency is not allowed here: the new `installed_at` must be at or after the previous coupon's `removed_at` plus the full seven-day buffer. A fresh coupon is `INSTALLED`, with `removed_at`, `exposure_days`, `corrosion_rate_mpy`, and `rating` all unset. The coupons of a rack are listable with an optional `status` filter.

Removing a coupon closes the interval: the request carries the `post_weight_g`, which must be strictly positive and must not exceed `pre_weight_g` plus a 2.0-gram deposit allowance — a heavier coupon beyond that allowance is rejected with `ERR_COUPON_WEIGHT_GAIN`. On removal, `removed_at` is set to the current clock, `exposure_days` is the elapsed time from `installed_at` to `removed_at` rounded down to whole days of 86,400 seconds, and the exposure must total at least one full day, failing with `ERR_EXPOSURE_TOO_SHORT` otherwise. The coupon's `corrosion_rate_mpy` is then computed: the weight loss in grams (`pre_weight_g` minus `post_weight_g`) multiplied by 22,300, divided by the product of `density_g_cm3`, `area_in2`, and `exposure_days`, stored to 3 decimal places rounded half up. Finally, the `rating` is set: `RELIABLE` when `exposure_days` is at least 30 — exactly 30 days is reliable — and `UNRELIABLE` below that. Removal leaves the coupon in terminal `REMOVED` status.

### 3.7. Legionella Risk Plans and Validation Discipline

Every asset under Legionella control carries a risk plan, created by a `WaterChemist` with the `asset_id`, a narrative `plan_text` control scheme, and a `validation_interval_days` between 7 and 365 inclusive. A new plan is a `DRAFT`, its `last_validated_at` null.

Activation — `DRAFT` → `ACTIVE` — requires the asset to be `IN_SERVICE` (`ERR_ASSET_NOT_IN_SERVICE`) and starts the validation clock: `validation_due_at` is set to the current clock plus `validation_interval_days` days. From then on the clock rules the plan. When the logical clock reaches or passes `validation_due_at`, the sweep of §2.4 moves the plan from `ACTIVE` to `VALIDATION_DUE` automatically. Should validation remain undone, a `WaterChemist` may declare the plan delinquent — `VALIDATION_DUE` → `DELINQUENT` — but only after a fourteen-day grace period: the current clock must be strictly later than `validation_due_at` plus 14 days, failing earlier with `ERR_GRACE_NOT_ELAPSED`. Declaring delinquency recomputes the asset's posture to `NON_COMPLIANT`.

Validation sampling restores discipline: validating a plan in `VALIDATION_DUE` or `DELINQUENT` returns it to `ACTIVE`, stamps `last_validated_at` with the current clock, refreshes `validation_due_at` to the current clock plus `validation_interval_days` days, and recomputes the asset's posture — which may clear a `NON_COMPLIANT` that the delinquency had caused. When a plan has never been validated, its `validation_due_at` is computed from activation plus the interval; thereafter from `last_validated_at` plus the interval.

Suspension is the `AccountManager`'s instrument and applies from `ACTIVE`, `VALIDATION_DUE`, or `DELINQUENT` (any other state is `ERR_INVALID_STATE`): the plan moves to `SUSPENDED` and the asset's posture is recomputed to `FROZEN`, with all the gating consequences of §2.8. A suspended plan is not dead — a `WaterChemist` may return it to `DRAFT`, which recomputes the asset's posture and may clear the `FROZEN` hold. Plan list views support `asset_id` and `status` filters.

### 3.8. Blowdown Events, Water Balance, and Savings Reporting

Blowdown — deliberate discharge of concentrated water — is where water savings are proven. A `WaterChemist` logs a blowdown event against an asset with the `occurred_at` timestamp, the `blowdown_gal` discharged, and the `makeup_gal` admitted, both gallon figures strictly positive. The `occurred_at` must not exceed the current clock and must be strictly after the previous event's `occurred_at` on the same asset; a violation of that monotonic ordering is rejected with `ERR_NON_MONOTONIC_EVENT`.

Each event is put through the **cycles and water-balance calculation** in a pinned order. The event window runs from the previous blowdown event's `occurred_at` on the same asset — or from the asset's creation for the asset's first event — up to this event's `occurred_at`, measured in minutes. First, the evaporation allocated to the window, `evaporation_gal`, is the asset's `recirculation_rate_gpm` times its `evaporation_factor` times the window minutes. Second, the drift allocation is the `recirculation_rate_gpm` times the `drift_factor` times the window minutes. Third, the achieved cycles of concentration for the window, `achieved_coc`, is `makeup_gal` divided by the sum of `blowdown_gal` and the drift allocation — a denominator guaranteed positive because `blowdown_gal` is strictly positive. Fourth, the invariant probe: `balance_residual_gal` is `makeup_gal` minus `evaporation_gal` minus `blowdown_gal` minus the drift allocation, rounded half up to 2 decimal places; a correctly kept water balance leaves a residual of zero within rounding. Savings are then measured against the baseline of 3.0 cycles: the baseline blowdown for the same window is `evaporation_gal` divided by (3.0 minus one) minus the drift allocation, and the event's `saved_gal` is the greater of zero and the baseline blowdown minus the actual `blowdown_gal`.

The asset's water-savings report — readable by all four roles — aggregates this math: per-event rows showing each event's `evaporation_gal`, achieved cycles, and `saved_gal`, plus totals exposed as `total_saved_gal`, `baseline_blowdown_gal`, `actual_blowdown_gal`, and `event_count`.

### 3.9. Deliveries, Tote Exchange, and Invoicing

Replenishment flows through delivery orders, which an `AccountManager` creates in `DRAFT` status by naming the billed `account_id`, the destination `station_id` (which determines the product), and a `quantity_gal` that must be strictly positive and a whole multiple of the destination product's `container_size_gal` (`ERR_QUANTITY_NOT_CONTAINER_MULTIPLE` when it is not). Creation also enforces referential integrity: the destination station must not be `LOCKED_OUT` (`ERR_STATION_LOCKED_OUT`) and its product must be `LISTED` (`ERR_PRODUCT_DELISTED`). Orders created by the inventory-depletion cascade of §3.5 arrive with `auto_drafted` set to `true`; human-created orders carry `false`. The orders list supports `account_id`, `station_id`, and `status` filters.

The order lifecycle runs `DRAFT` → `PENDING` → `SCHEDULED` → `IN_TRANSIT` → `DELIVERED` → `CLOSED`, with `FAILED_DELIVERY` looping back to `SCHEDULED` and `CANCELLED` available from the early states. Submission — `DRAFT` → `PENDING` — is a bare state move. Scheduling — `PENDING` → `SCHEDULED` — is heavily gated: the request supplies a `scheduled_for` that must be strictly later than the current clock (`ERR_SCHEDULE_IN_PAST`); the destination station's asset must have an `ACCEPTED` program design (`ERR_PROGRAM_NOT_ACCEPTED`); the account's `credit_hold` must be `false` (`ERR_CREDIT_HOLD`); the account's `status` must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`); and the request must carry `expected_delivery_order_version` equal to the order's current `version` (`ERR_STALE_VERSION`, per §2.7). A successful schedule stores the supplied `scheduled_for` and increments the order's `version` by one. Rescheduling after a failure — `FAILED_DELIVERY` → `SCHEDULED` — uses the same endpoint with the same future-dated `scheduled_for` requirement, the same credit-hold gate, and the same OCC guard; note that the program-accepted and account-active checks belong to the `PENDING` branch only.

Dispatch — `SCHEDULED` → `IN_TRANSIT` — is refused before the scheduled instant: the current clock must be at or after `scheduled_for` (`ERR_TOO_EARLY_TO_DISPATCH`). Delivery confirmation — `IN_TRANSIT` → `DELIVERED` — is performed by the `WaterChemist` on site, who reports the `delivered_gal` actually dropped; it must be strictly positive and no more than the ordered `quantity_gal` (`ERR_DELIVERY_QUANTITY`). Confirmation credits the destination station's `inventory_gal` by `delivered_gal` and recomputes the station's depletion projection. When the drop cannot be completed, failing the delivery moves the order from `IN_TRANSIT` to `FAILED_DELIVERY`, from which it may be rescheduled as above.

Tote exchange happens at close — `DELIVERED` → `CLOSED` — when the chemist reports the `returned_residual_gal` left in the exchanged tote; it must be zero or more and no more than the product's `container_size_gal` (`ERR_RESIDUAL_EXCEEDS_CONTAINER`). Closing debits the destination station's `inventory_gal` by `returned_residual_gal` — the residual leaves with the old tote — and reconciles the tote-exchange mass invariant per station: the sum of `delivered_gal` minus the sum of `returned_residual_gal` equals consumed gallons plus on-hand `inventory_gal`. Cancellation is available from `DRAFT`, `PENDING`, or `SCHEDULED` (any other state is `ERR_INVALID_STATE`); cancelling a `SCHEDULED` order releases its tote allocation, a pure compensation since no inventory has yet moved, while cancelling from `DRAFT` or `PENDING` has no inventory effect.

Billing closes the commercial loop. An `AccountManager` creates an invoice in `DRAFT` for an `account_id` and a half-open billing window from `period_start` inclusive to `period_end` exclusive, with `period_end` strictly after `period_start`. Issuing — `DRAFT` → `ISSUED` — snapshots the `pricing_variant` from the account's current `billing_model` and computes the totals. The line set is the account's delivery orders in `DELIVERED` or `CLOSED` status whose `scheduled_for` falls within the billing window, and the rounding order is pinned: each line is rounded half up to whole cents first, and only then are lines summed — never sum raw values and round once. Under the `PRODUCT` variant, each line is the order's `delivered_gal` times the product's `unit_price_cents_per_gal`, rounded half up to whole cents, and the `service_fee_cents` is 0. Under the `SERVICE_CONTRACT` variant, each line is `delivered_gal` times the `contract_price_cents_per_gal`, rounded the same way, and the `service_fee_cents` is the `service_rate_cents_per_month` from the `ACCEPTED` program design of the destination station's asset — 0 when no accepted design exists. The `product_charges_cents` is the sum of the rounded lines and `invoice_total_cents` is `product_charges_cents` plus `service_fee_cents`; the same delivery set therefore yields a different total under the two variants. Issuing also debits the account: `open_balance_cents` is increased by `invoice_total_cents`.

An invoice left unpaid ages automatically: the clock sweep of §2.4 moves it from `ISSUED` to `OVERDUE` when the current clock passes thirty days beyond `period_end`. Payment — from either `ISSUED` or `OVERDUE` to `PAID` — belongs to the `CustomerContact`, who must own the invoice's account (`ERR_FORBIDDEN` otherwise), and credits the account: `open_balance_cents` is decreased by `invoice_total_cents`. A `DRAFT` invoice may instead be voided — `DRAFT` → `VOID` — by an `AccountManager`. Invoice list views accept `account_id` and `status` filters.

---

## 4. Endpoint Definitions

Operations that create a new resource — an account, asset, design, product, station, reading, route, stop, result, rack, coupon, plan, blowdown event, delivery order, or invoice — return `201 Created`. Operations that modify an existing resource, including all state-transition actions and the clock-setting capability, return `200 OK`, as do all list and detail reads. Where the Authorized Role(s) column reads "Any", every authenticated role may call the endpoint — `AccountManager`, `WaterChemist`, `CustomerContact`, and `PlatformAdmin` — subject always to the `CustomerContact` ownership scoping of §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/wt/_clock/set_current_utc` | Set the server's logical clock; runs due/overdue sweeps | PlatformAdmin |
| POST | `/wt/accounts` | Create a customer account | AccountManager |
| GET | `/wt/accounts` | List customer accounts | AccountManager, WaterChemist, PlatformAdmin |
| GET | `/wt/accounts/{accountId}` | Get a customer account | Any |
| POST | `/wt/accounts/{accountId}/suspend` | Suspend an account; cancels open delivery orders and freezes asset posture | AccountManager |
| POST | `/wt/accounts/{accountId}/reactivate` | Reactivate a suspended account | AccountManager |
| POST | `/wt/accounts/{accountId}/close` | Close an account; requires zero open balance | AccountManager |
| POST | `/wt/assets` | Register a system asset under an account | WaterChemist |
| GET | `/wt/assets` | List assets | Any |
| GET | `/wt/assets/{assetId}` | Get an asset | Any |
| GET | `/wt/assets/{assetId}/water-savings` | Water-savings report for an asset | Any |
| POST | `/wt/assets/{assetId}/commission` | Move asset COMMISSIONING → IN_SERVICE | WaterChemist |
| POST | `/wt/assets/{assetId}/decommission` | Move asset IN_SERVICE → DECOMMISSIONED | WaterChemist |
| POST | `/wt/program-designs` | Open a system survey / program design | WaterChemist |
| GET | `/wt/program-designs` | List program designs | Any |
| GET | `/wt/program-designs/{designId}` | Get a program design | Any |
| POST | `/wt/program-designs/{designId}/record-survey` | Record survey findings (SURVEY_SCHEDULED → SURVEYED) | WaterChemist |
| POST | `/wt/program-designs/{designId}/draft` | Commit design parameters (SURVEYED → DRAFTED) | WaterChemist |
| POST | `/wt/program-designs/{designId}/propose` | Propose a design (DRAFTED → PROPOSED) | WaterChemist |
| POST | `/wt/program-designs/{designId}/accept` | Accept a design (PROPOSED → ACCEPTED); OCC-guarded | CustomerContact |
| POST | `/wt/program-designs/{designId}/request-revision` | Request changes (PROPOSED → REVISE_REQUESTED) | CustomerContact |
| POST | `/wt/program-designs/{designId}/reopen-survey` | Reopen survey (REVISE_REQUESTED → SURVEYED); revision +1 | WaterChemist |
| POST | `/wt/program-designs/{designId}/withdraw` | Withdraw a design (PROPOSED → WITHDRAWN) | WaterChemist |
| POST | `/wt/products` | Create a catalog product | PlatformAdmin |
| GET | `/wt/products` | List products | AccountManager, WaterChemist, PlatformAdmin |
| GET | `/wt/products/{productId}` | Get a product | AccountManager, WaterChemist, PlatformAdmin |
| POST | `/wt/products/{productId}/delist` | Delist a product (LISTED → DELISTED) | PlatformAdmin |
| POST | `/wt/feed-stations` | Create a feed station on an asset for a product | WaterChemist |
| GET | `/wt/feed-stations` | List feed stations | Any |
| GET | `/wt/feed-stations/{stationId}` | Get a feed station with inventory and depletion projection | Any |
| POST | `/wt/feed-stations/{stationId}/bring-online` | Bring a station online (OFFLINE/LOCKED_OUT → ONLINE) | WaterChemist |
| POST | `/wt/feed-stations/{stationId}/lockout` | Lock out a station (ONLINE → LOCKED_OUT) | WaterChemist |
| POST | `/wt/feed-stations/{id}/telemetry` | Append a telemetry reading | WaterChemist |
| GET | `/wt/feed-stations/{id}/telemetry` | List telemetry readings of a station | Any |
| POST | `/wt/test-routes` | Create a test route for an account | WaterChemist |
| GET | `/wt/test-routes` | List test routes | Any |
| GET | `/wt/test-routes/{routeId}` | Get a test route | Any |
| POST | `/wt/test-routes/{id}/stops` | Add a stop to a PLANNED route | WaterChemist |
| GET | `/wt/test-routes/{id}/stops` | List stops of a route | Any |
| POST | `/wt/test-routes/{routeId}/publish` | Publish a route (PLANNED → PUBLISHED) | WaterChemist |
| POST | `/wt/test-routes/{routeId}/cancel` | Cancel a route; SCHEDULED stops → SKIPPED | WaterChemist |
| GET | `/wt/route-stops` | List route stops | Any |
| GET | `/wt/route-stops/{stopId}` | Get a route stop | Any |
| POST | `/wt/route-stops/{stopId}/arrive` | Mark arrival within the visit window (SCHEDULED → ARRIVED) | WaterChemist |
| POST | `/wt/route-stops/{stopId}/mark-missed` | Mark a stop missed after its window (SCHEDULED → MISSED) | WaterChemist |
| POST | `/wt/route-stops/{id}/water-test-results` | Record a water test result at an ARRIVED stop | WaterChemist |
| GET | `/wt/route-stops/{id}/water-test-results` | List results recorded at a stop | Any |
| GET | `/wt/water-test-results` | List results for trending | Any |
| GET | `/wt/water-test-results/{resultId}` | Get a single water test result | Any |
| POST | `/wt/water-test-results/{resultId}/confirm` | Confirm a result with lab TDS (RECORDED → CONFIRMED) | WaterChemist |
| POST | `/wt/water-test-results/{resultId}/void` | Void a result (RECORDED → VOIDED) with compensation | WaterChemist |
| GET | `/wt/corrective-actions` | List corrective actions | Any |
| GET | `/wt/corrective-actions/{actionId}` | Get a corrective action | Any |
| POST | `/wt/corrective-actions/{actionId}/approve` | Approve an action (PENDING → APPROVED); SoD + OCC | WaterChemist |
| POST | `/wt/corrective-actions/{actionId}/apply` | Apply an approved action (APPROVED → APPLIED) | WaterChemist |
| POST | `/wt/corrective-actions/{actionId}/decline` | Decline an action (PENDING → DECLINED); SoD | WaterChemist |
| POST | `/wt/racks` | Install a coupon rack on an asset | WaterChemist |
| GET | `/wt/racks` | List coupon racks | Any |
| GET | `/wt/racks/{rackId}` | Get a coupon rack | Any |
| POST | `/wt/racks/{rackId}/archive` | Archive a rack (INSTALLED → ARCHIVED) | WaterChemist |
| POST | `/wt/racks/{id}/coupons` | Install a coupon on a rack position | WaterChemist |
| GET | `/wt/racks/{id}/coupons` | List coupons of a rack | Any |
| POST | `/wt/coupons/{couponId}/remove` | Remove a coupon; computes exposure, rate, rating | WaterChemist |
| POST | `/wt/legionella-plans` | Create a Legionella risk plan (DRAFT) | WaterChemist |
| GET | `/wt/legionella-plans` | List Legionella risk plans | Any |
| GET | `/wt/legionella-plans/{planId}` | Get a Legionella risk plan | Any |
| POST | `/wt/legionella-plans/{planId}/activate` | Activate a plan (DRAFT → ACTIVE) | WaterChemist |
| POST | `/wt/legionella-plans/{planId}/validate` | Validate a plan (VALIDATION_DUE/DELINQUENT → ACTIVE) | WaterChemist |
| POST | `/wt/legionella-plans/{planId}/declare-delinquent` | Declare a plan delinquent after grace (VALIDATION_DUE → DELINQUENT) | WaterChemist |
| POST | `/wt/legionella-plans/{planId}/suspend` | Suspend a plan; freezes asset posture | AccountManager |
| POST | `/wt/legionella-plans/{planId}/return-to-draft` | Return a suspended plan to DRAFT | WaterChemist |
| POST | `/wt/assets/{id}/blowdown-events` | Log a blowdown event for an asset | WaterChemist |
| GET | `/wt/assets/{id}/blowdown-events` | List blowdown events of an asset | Any |
| POST | `/wt/delivery-orders` | Create a delivery order (DRAFT) | AccountManager |
| GET | `/wt/delivery-orders` | List delivery orders | Any |
| GET | `/wt/delivery-orders/{orderId}` | Get a delivery order | Any |
| POST | `/wt/delivery-orders/{orderId}/submit` | Submit an order (DRAFT → PENDING) | AccountManager |
| POST | `/wt/delivery-orders/{orderId}/schedule` | Schedule or reschedule an order; OCC-guarded | AccountManager |
| POST | `/wt/delivery-orders/{orderId}/dispatch` | Dispatch an order (SCHEDULED → IN_TRANSIT) | AccountManager |
| POST | `/wt/delivery-orders/{orderId}/confirm-delivery` | Confirm delivery; credits station inventory | WaterChemist |
| POST | `/wt/delivery-orders/{orderId}/fail` | Fail a delivery (IN_TRANSIT → FAILED_DELIVERY) | WaterChemist |
| POST | `/wt/delivery-orders/{orderId}/close` | Close an order; tote-exchange residual debited | WaterChemist |
| POST | `/wt/delivery-orders/{orderId}/cancel` | Cancel an order; releases tote allocation | AccountManager |
| POST | `/wt/invoices` | Create a DRAFT invoice for an account and period | AccountManager |
| GET | `/wt/invoices` | List invoices | Any |
| GET | `/wt/invoices/{invoiceId}` | Get an invoice | Any |
| POST | `/wt/invoices/{invoiceId}/issue` | Issue an invoice; snapshots variant, debits open balance | AccountManager |
| POST | `/wt/invoices/{invoiceId}/pay` | Pay an invoice (ISSUED/OVERDUE → PAID) | CustomerContact |
| POST | `/wt/invoices/{invoiceId}/void` | Void a DRAFT invoice | AccountManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ROUTE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ASSET_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_ASSET_FROZEN` | 409 Conflict |
| `ERR_LEGIONELLA_PLAN_SUSPENDED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_FIELD_CONSTRAINT` | 422 Unprocessable Entity |
| `ERR_QUANTITY_NOT_CONTAINER_MULTIPLE` | 422 Unprocessable Entity |
| `ERR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_COUPON_INTERVAL_CONFLICT` | 409 Conflict |
| `ERR_OUTSIDE_VISIT_WINDOW` | 422 Unprocessable Entity |
| `ERR_WINDOW_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_TOO_EARLY_TO_DISPATCH` | 422 Unprocessable Entity |
| `ERR_TELEMETRY_FUTURE` | 422 Unprocessable Entity |
| `ERR_NON_MONOTONIC_EVENT` | 422 Unprocessable Entity |
| `ERR_GRACE_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_EXPOSURE_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_COUPON_WEIGHT_GAIN` | 422 Unprocessable Entity |
| `ERR_DELIVERY_QUANTITY` | 422 Unprocessable Entity |
| `ERR_RESIDUAL_EXCEEDS_CONTAINER` | 422 Unprocessable Entity |
| `ERR_ASSET_MISMATCH` | 409 Conflict |
| `ERR_RACK_ARCHIVED` | 409 Conflict |
| `ERR_STATION_LOCKED_OUT` | 409 Conflict |
| `ERR_PRODUCT_DELISTED` | 409 Conflict |
| `ERR_CREDIT_HOLD` | 409 Conflict |
| `ERR_UNPAID_BALANCE` | 409 Conflict |
| `ERR_NO_ACCEPTED_PROGRAM` | 409 Conflict |
| `ERR_NO_ONLINE_FEED_STATION` | 409 Conflict |
| `ERR_INCOMPLETE_DESIGN` | 422 Unprocessable Entity |
| `ERR_EMPTY_ROUTE` | 409 Conflict |
| `ERR_COUPONS_STILL_INSTALLED` | 409 Conflict |
| `ERR_OPEN_ROUTE_STOPS` | 409 Conflict |
| `ERR_LAB_TDS_REQUIRED` | 422 Unprocessable Entity |
