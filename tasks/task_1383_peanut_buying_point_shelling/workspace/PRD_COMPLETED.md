# Peanut Buying Point & Shelling API — Product Requirements Document

## 1. Introduction

Every harvest season, a Georgia peanut buying point sits at the junction of several unforgiving workflows at once: farmer stock rolls across the scale and must be graded against a published discount schedule, the aflatoxin laboratory clears or segregates every lot, drying capacity has to be rationed by booking, warehouses fill toward capacity while the intake gate widens or narrows in response, growers pledge stored tonnage as marketing-loan collateral, shellers call for delivery against seasonal contracts, and — at the end — each grower receives a settlement that nets purchase value against discounts, drying charges, loan payoffs, and a share of the hull revenue pool, all under quota-tier pricing rules.

This document specifies the API that operates that buying point. It governs the full lifecycle from load reporting through weighing, grading, laboratory clearance, drying, storage, lending, delivery, reconciliation, and settlement, with segregation-of-duties controls on the laboratory bench and the settlement desk, optimistic concurrency on the three write paths where a stale read would corrupt money or tonnage, and a system-swept operations checkpoint that converts missed dryer windows and blown dock windows into strikes and defaults. The API is mounted under `/buying-points` and is the single source of truth for every ton, cent, and state the buying point tracks.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request whose headers are missing, or whose role value is not one of the declared role names, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the target operation is rejected with `ERR_FORBIDDEN`.

The system recognizes six roles, spelled exactly as follows: `BuyingPointAdmin`, `Grower`, `GradingInspector`, `LabTechnician`, `SettlementClerk`, and `ShellerRep`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower` entity; ownership checks on any resource that references a grower — a load's `grower_id`, a pledge's `grower_id`, a settlement's `grower_id`, a quota history's `grower_id` — compare that field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_FORBIDDEN`. When `X-User-Role` is `ShellerRep`, `X-User-ID` is an opaque operator identifier that is not the `id` of any persisted entity, but contract ownership is anchored on it: a sheller representative may act only on contracts whose `sheller_ref` equals `X-User-ID`, and on the delivery calls of those contracts; acting outside that scope is rejected with `ERR_OWNERSHIP_FORBIDDEN`. When `X-User-Role` is `BuyingPointAdmin`, `GradingInspector`, `LabTechnician`, or `SettlementClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity's `id`; the server may record it — as `inspector_ref` on a grade sheet, as `lab_tech_ref`, `result_recorded_by`, or `confirmed_by` on a certificate, or as `computed_by`, `approved_by`, or `paid_by` on a settlement — but it never compares such values to an entity `id`.

Ownership scoping also shapes read traffic. List endpoints auto-scope for the two ownership-bound roles: a `Grower` listing growers sees only its own record; a `Grower` listing loads, pledges, settlements, or quota histories sees only its own; a `ShellerRep` listing contracts sees only contracts with its `sheller_ref`, and listing delivery calls sees only calls on its own contracts.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100 — a `limit` below 1 or above 100 is clamped to the nearest bound, not rejected. The `offset` parameter says how many items to skip and defaults to 0; a negative `offset` is clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order; resources created at the same logical-clock instant are ordered by insertion sequence.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification.
- `version` (integer): a system-managed counter that starts at 1 on creation and increments on every mutation of the resource; it is the basis of optimistic concurrency control.

One entity breaks this convention: an `AllocationLine` is a system-created junction record and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from allocation lines.

### 2.5. The Logical Clock

All time-dependent rules in this system — weigh timestamps, schedule windows, booking windows, dock windows, loan interest, maturity, hull-pool membership, and the operations sweep — read a single server-held **logical clock**, never wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any operator action it remains at that default.

An admin-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant; the response reports the new reading as `current_utc`. Every timestamp the server records itself — including `created_at` and `updated_at` as well as `weighed_at`, `stored_at`, `pledged_at`, and `sold_at` — is taken from this clock.

### 2.6. Units, Precision, and Rounding Discipline

Tonnage, money, and laboratory values each have a fixed precision contract:

- **Tonnages** (`gross_tons`, `payable_tons`, booking `tons`, receipt balances, pledged and shelled tonnages) are carried at three decimal places; whenever the system derives a tonnage it rounds half up to three decimals. Every client-supplied tonnage (`gross_tons`, booking `tons`, `pledged_tons`, `total_units_tons`, `requested_tons`, `shelled_kernel_tons`, `hull_tons`, `quota_tons`) may carry at most three decimal places and must be strictly positive except where §3 expressly allows zero.
- **Monetary amounts** are integer cents. Every derived cent amount is rounded half up to whole cents at the step the relevant rule prescribes; per-tier and per-line rounding happens before summation wherever §3 says so.
- **Percentages** supplied by clients (`moisture_pct`, `foreign_material_pct`, `damage_pct`, `lsk_pct`, `actual_moisture_after`) carry at most two decimal places and must each lie between 0 and 100 inclusive.
- **Aflatoxin results** (`result_ppb`) carry at most two decimal places in parts per billion and must be non-negative.
- **Loan interest** accrues per whole day: partial days are discarded, and a negative day count is treated as zero.

### 2.7. Warehouse Capacity and Intake Posture

A buying point's willingness to accept farmer stock is a computed posture, not a configuration flag. The posture derives from aggregate free tonnage: for each warehouse, `free_tons` is its `capacity_tons` minus `stored_tons` minus `reserved_tons`, and the buying point's aggregate free tonnage is the sum of that expression over all of its warehouses.

The posture thresholds are pinned. When aggregate free tonnage is at or below zero, `intake_posture` is `SUSPENDED` and all load creation is rejected with `ERR_INTAKE_SUSPENDED`. When aggregate free tonnage is above zero but no more than 500 tons, the posture is `RESTRICTED`: load reporting remains open, but any weigh-in whose `gross_tons` exceeds 50 tons is rejected with `ERR_RESTRICTED_LOAD_LIMIT`. When aggregate free tonnage exceeds 500 tons, the posture is `OPEN`. The boundaries are exact: exactly zero free tons means `SUSPENDED`, exactly 500 means `RESTRICTED`, and 501 means `OPEN`. A buying point with no warehouses has zero aggregate free tonnage and is therefore `SUSPENDED` from the moment it is created.

The posture is recomputed on every mutation that touches warehouse stored or reserved totals — storing a receipt, allocating or cancelling or defaulting a delivery call, delivering tonnage, forfeiting collateral, cancelling a receipt, or creating a warehouse — and the posture moves freely in both directions as capacity tightens and frees.

### 2.8. Optimistic Concurrency Control

Three write endpoints guard a parent entity's version, and each names its own required input field:

- Computing a settlement for a grower requires `expected_grower_version`, carrying the client's last-observed `version` of that grower.
- Allocating (or re-allocating) a delivery call requires `expected_delivery_call_version`, carrying the client's last-observed `version` of the call.
- Creating a grade sheet on a load requires `expected_farmer_stock_load_version`, carrying the client's last-observed `version` of the load.

In each case, if the supplied value does not match the parent entity's current `version` — because another writer has advanced that version since the client last read the parent — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A settlement computed against a stale grower view, an allocation layered over a superseded allocation, or a re-grade based on a sheet the client has not observed would otherwise silently overwrite newer state; the check exists to surface those cases. Endpoints not listed here do not accept a version field at all.

### 2.9. Validation Priority Order

When several checks could fire on the same request, the server evaluates them in a fixed order and reports the first failure:

1. **Authentication** — presence and validity of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`).
2. **Request schema** — required fields present, types valid, enum values in range, and numeric constraints satisfied (positive tonnages, percentages within 0 to 100, positive `amount_cents`): `ERR_INVALID_REQUEST`.
3. **Role permission** — the role is permitted for this endpoint at all (`ERR_FORBIDDEN`).
4. **Existence** — path identifiers and body foreign-key references resolve, validated left to right (`ERR_NOT_FOUND`).
5. **Ownership scope** — a `Grower` or `ShellerRep` acting within its ownership boundary (`ERR_OWNERSHIP_FORBIDDEN`).
6. **State preconditions** — the target resource is in a valid from-state, and state-gated creations are satisfied (`ERR_INVALID_STATE`, including the specialized grower-suspension, intake-suspension, and drying gate codes described in §3).
7. **Optimistic concurrency** — the §2.8 version fields (`ERR_STALE_VERSION`).
8. **Segregation of duties and compliance gates** — `ERR_SEG_OF_DUTIES`, aflatoxin clearance, and compartment segregation.
9. **Uniqueness and overlap constraints** — certificate uniqueness, quota-history uniqueness, schedule window overlap, dryer and dock window overlap, warehouse capacity, the settlement re-grade lock, the retest cap, and open-calls blocking contract cancellation.
10. **Temporal windows** — dock windows inside the contract window, foreclosure maturity, schedule coverage at finalize, and the restricted-posture load cap at weigh.
11. **Fiscal limits** — contract remaining tonnage, allocable tonnage sufficiency, loan collateralization, settlement payability, quota headroom at approval, and reconcile shrink tolerance.

### 2.10. Nested Resource Retrieval

Requests that address a resource through another resource's path — a grade sheet under a load's `{id}`, a certificate under a load, a settlement under a grower's `{growerId}` — validate identifiers sequentially from left to right. The request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before any later identifier or body reference is examined. The same existence rule covers foreign keys supplied in request bodies: a payload naming a `dryer_id`, `load_id`, `warehouse_id`, `storage_receipt_id`, `contract_id`, or `grower_id` that does not exist is rejected with `ERR_NOT_FOUND` at this stage.

### 2.11. Segregation of Duties

Three steps in the workflow are deliberately split so that no single operator id can carry a transaction through both sides of a control point. The technician who records an aflatoxin result may not confirm it. The clerk who computes a settlement may not approve it. The clerk who approves a settlement may not pay it. Each crossing is rejected with `ERR_SEG_OF_DUTIES`. The fields that record these hand-offs — `result_recorded_by` versus `confirmed_by` on the certificate, `computed_by` versus `approved_by` versus `paid_by` on the settlement — are system-stamped from `X-User-ID` and are never accepted as client input.

## 3. Business Logic & Workflows

### 3.1. Configuring the Buying Point: Prices, Warehouses, Dryers, and Discount Policy

A `BuyingPointAdmin` opens a season by creating the buying point itself: a display `name`, the operating `crop_year` (an integer such as 2026), and the five money and rate fields that anchor every later calculation, each a non-negative integer number of cents. Two are purchase prices per payable ton — `quota_price_cents_per_ton` for quota-tier peanuts and `additional_price_cents_per_ton` for over-quota tonnage. Two are marketing-loan rates per pledged ton — `loan_rate_quota_cents_per_ton` and `loan_rate_additional_cents_per_ton`. One is the drying tariff, `drying_rate_per_cycle_cents`, the base charge per dryer cycle before the moisture multiplier. The buying point's `ops_run_index` starts at zero and increments only through the operations checkpoint described in §3.6. Because a fresh buying point has no warehouses, its computed `intake_posture` begins at `SUSPENDED` per §2.7.

Warehouses come next. Each warehouse is created with its `buying_point_id`, a `name`, a positive integer `capacity_tons`, and a `compartment` of either `GENERAL` or `SEGREGATED`; a `SEGREGATED` warehouse holds only aflatoxin-segregated stock. At creation `stored_tons` and `reserved_tons` are zero and `free_tons` equals capacity, and creating a warehouse recomputes the buying point's posture — typically lifting a new buying point out of `SUSPENDED`. Dryers are registered the same way, each with its `buying_point_id`, a `name`, a positive integer `cycle_capacity_tons`, and a positive integer `cycle_hours`. Warehouse and dryer lists accept a `buying_point_id` filter; the warehouse list additionally accepts a `compartment` filter.

The discount schedule is the buying point's published grading policy. A schedule is created in `DRAFT` status with a human label `schedule_code` (for example FALL-2026), a half-open coverage window from `effective_from` (inclusive) to `effective_to` (exclusive) — `effective_from` must be strictly before `effective_to` — and three discount instruments. `moisture_tiers` is an ordered list of tiers, each pairing an `up_to_pct` ceiling with a `discount_cents_per_ton`; the first tier whose ceiling is at least the measured moisture wins, a moisture exactly equal to a tier's ceiling selects that tier (the boundary is inclusive), and a tier whose `up_to_pct` is null is the unbounded final tier that matches anything. `foreign_material_tiers` has the same ordered shape and is selected on the foreign-material percentage. Each tier list must be a non-empty array whose tiers carry an `up_to_pct` (null permitted) and an integer `discount_cents_per_ton`, and `damage_rate_cents_per_pct` is a non-negative integer; if no tier's ceiling covers a measured percentage and no null tier is present, that instrument's per-ton discount is zero. `damage_rate_cents_per_pct` is a flat cents-per-ton discount for each full or fractional percentage point of kernel damage, applied as described in §3.4.

Activation is where the schedule earns force. Activating a `DRAFT` schedule moves it to `ACTIVE`, but only if its half-open window does not overlap the window of any other `ACTIVE` schedule — an overlap is rejected with `ERR_SCHEDULE_WINDOW_OVERLAP`, so at most one active schedule covers any instant. Retiring moves an `ACTIVE` schedule to its terminal `RETIRED` state. Retirement is not retroactive: grade sheets already finalized keep the `schedule_id` they pinned (version-pinning of policy), but any finalization after the retire requires some other `ACTIVE` schedule to cover the load's weigh timestamp, and fails with `ERR_NO_ACTIVE_SCHEDULE` when none does. The schedule list accepts a `status` filter.

### 3.2. Growers, Farm Records, and Quota Histories

Growers are registered by a `BuyingPointAdmin` with a legal `name` and an FSA `farm_number`; the farm number must be unique across all registered growers, and a duplicate is rejected with `ERR_INVALID_REQUEST`. A new grower starts `ACTIVE` with `no_show_strikes` at zero. The grower list accepts a `status` filter, and a `Grower`-role caller is scoped to its own record as described in §2.1.

Each grower's annual poundage quota is recorded as a quota history: a payload of `grower_id`, `crop_year`, and `quota_tons` (zero or more tons). At most one quota history may exist per grower per crop year — a second record for the same pair is rejected with `ERR_DUPLICATE_QUOTA_HISTORY`. A quota history begins with `used_quota_tons` at zero and, once recorded, carries no status field and never transitions through any state machine of its own; `used_quota_tons` moves only through the settlement approve and void cascades of §3.9. Wherever a calculation needs a grower's quota and no history exists for the relevant crop year, the quota is treated as zero. Quota histories may be listed with `grower_id` and `crop_year` filters.

Standing can be lost two ways, both detailed where they occur: dryer no-shows accumulate strikes (§3.6), and an administrator may suspend outright. Reinstating a `SUSPENDED` grower returns it to `ACTIVE` and resets `no_show_strikes` to zero.

### 3.3. Load Intake and Weighing

Intake begins when a load of farmer stock is reported — either by a `BuyingPointAdmin` or by the delivering `Grower` itself, in which case the payload's `grower_id` must be the caller's own id. The payload is just `grower_id` and `crop_year`; the crop year ties the load to the buying point's operating year for later settlement grouping. A crop year resolves to the first-created buying point bearing that `crop_year`; a report whose crop year matches no buying point is rejected with `ERR_NOT_FOUND`, and the same resolution selects the buying point whose prices and rates drive the settlement computation of §3.9. Two gates guard creation: the grower must be `ACTIVE`, or the report is rejected with `ERR_GROWER_SUSPENDED`, and the buying point's posture must not be `SUSPENDED`, or the report is rejected with `ERR_INTAKE_SUSPENDED`. A reported load opens with `status` `REPORTED`, `aflatoxin_status` `UNTESTED`, and `drying_status` `NOT_REQUIRED`; `gross_tons`, `weighed_at`, `payable_tons`, `provisional_net_estimate_cents`, and `settlement_id` are all null until later stages fill them.

The scale house weighs the load next. Recording a weight supplies `gross_tons` — strictly positive, at most three decimal places — stamps `weighed_at` from the logical clock, moves the load from `REPORTED` to `WEIGHED`, and increments the load's `version`. The posture gate is re-checked here in its restricted form: while the buying point is `RESTRICTED`, a weigh-in whose gross tonnage exceeds 50 tons is rejected with `ERR_RESTRICTED_LOAD_LIMIT`, per the thresholds of §2.7.

Loads may be listed with `grower_id`, `status`, `aflatoxin_status`, and `settlement_id` filters; a `Grower`-role listing is auto-scoped to the caller's own loads.

### 3.4. Grading and the Grade Sheet Lifecycle

Grading is the exclusive province of a `GradingInspector`. A grade sheet is opened on a load that is `WEIGHED`, `GRADED`, or `STORED`, with four measured percentages — `moisture_pct`, `foreign_material_pct`, `damage_pct`, and `lsk_pct` (loose shelled kernels as a percent of gross weight) — plus the concurrency field `expected_farmer_stock_load_version` from §2.8. The new sheet is a `DRAFT`, its `inspector_ref` is stamped from the caller's `X-User-ID`, its `payable_tons` stays null, and creating it increments the load's `version` — which is precisely what makes the OCC field meaningful, since a second sheet opened against the same load invalidates the first writer's view. Grade sheets may be listed with `load_id`, `schedule_id`, and `status` filters.

Finalization is where grading becomes binding. The finalize step requires an `ACTIVE` discount schedule whose half-open window covers the load's `weighed_at`; absent one, the finalize fails with `ERR_NO_ACTIVE_SCHEDULE`. On success the sheet pins that schedule's `schedule_id`, becomes `FINALIZED`, and computes `payable_tons`: the foreign-material tonnage is the load's `gross_tons` multiplied by the foreign-material percentage divided by one hundred, rounded half up to three decimal places; the loose-shelled-kernel tonnage is computed the same way from `lsk_pct`; and payable tonnage is the gross tonnage minus those two rounded deduction tonnages, itself rounded half up to three decimals. The per-component rounding must happen first — computing a single combined deduction percentage against gross weight in one multiplication is not permitted, because the two orders differ at the third decimal.

Finalization also drives the load's other axes. The load moves `WEIGHED` → `GRADED`. Its drying axis becomes `REQUIRED` when the measured moisture is above 10.49 percent and `NOT_REQUIRED` otherwise. Its `provisional_net_estimate_cents` is computed as a forward-looking estimate of settlement value: the per-load net value of §3.9 computed with quota headroom taken as the grower's annual quota minus already-consumed quota with no intra-settlement consumption, minus an estimated drying charge when drying is `REQUIRED`, with hull credit and loan offset treated as zero. The estimated drying charge divides the gross tonnage by the smallest `cycle_capacity_tons` among the buying point's dryers, rounds up to whole cycles, multiplies by `drying_rate_per_cycle_cents` and by the moisture multiplier of §3.6, and rounds half up to whole cents; when the buying point has no dryers, the drying estimate is zero because no estimate is possible. The load's `version` increments.

One finalize outcome overrides everything else: when the measured moisture exceeds 15.00 percent, the sheet still finalizes — it pins the covering `schedule_id` and its own `payable_tons` and remains the grade of record — but the load moves terminally to `REJECTED` from any of `WEIGHED`, `GRADED`, or `STORED`, may never be stored, and the load's own `payable_tons`, drying axis, and `provisional_net_estimate_cents` are left unchanged by the rejected finalize.

Re-grading keeps history rather than rewriting it. Finalizing a newer `DRAFT` sheet on a load already `GRADED` requires that the load's `settlement_id` is still null — once a load is locked into an approved settlement, re-grade attempts are rejected with `ERR_LOAD_LOCKED_BY_SETTLEMENT` — and again requires an active schedule covering the weigh timestamp. The prior `FINALIZED` sheet becomes `SUPERSEDED`, a terminal read-only record that retains its pinned `schedule_id`; the new sheet finalizes; `payable_tons`, the drying axis, and the provisional estimate are all recomputed; the load's `version` increments; and every settlement in `COMPUTED` or `DISPUTED` whose `included_load_ids` contains this load is swept to `STALE`. A re-grade of a `STORED` load follows the same supersede-and-recompute pattern with the same settlement lock and the same `STALE` cascade, and the load remains `STORED`; should that re-grade come in above the moisture reject threshold, the load's storage receipt is cancelled with the release cascade of §3.7. The per-ton discount rates used at settlement come from the pinned schedule: the moisture tier and the foreign-material tier are selected by the inclusive boundary rule of §3.1, and the damage line is the measured `damage_pct` multiplied by `damage_rate_cents_per_pct`, rounded half up to whole cents per ton.

### 3.5. Aflatoxin Certification and Segregation

Every load that will ever be stored needs laboratory clearance, handled exclusively by `LabTechnician` operators. Drawing a sample creates the load's aflatoxin certificate with a client-supplied `sample_ref` label; the load must be `WEIGHED` or `GRADED` (any other state is rejected with `ERR_INVALID_STATE`), and at most one certificate may ever exist for a load — a second draw is rejected with `ERR_CERTIFICATE_EXISTS`. The certificate opens in `SAMPLED` status, its `lab_tech_ref` is stamped from the creator, the load's `aflatoxin_status` moves to `SAMPLED`, and the load's `version` increments. Certificates may be listed with `load_id` and `status` filters.

Recording a result moves the certificate `SAMPLED` → `RESULT_RECORDED`: the technician supplies `result_ppb` (two decimal places), the server stamps `result_recorded_by` from the caller, and the `determination` is recomputed on every recording. The determination thresholds are pinned: a result at or below 15.00 parts per billion is `PASS`; a result above 15.00 and at or below 50.00 is `SEGREGATE`; a result above 50.00 is `REJECT`.

A certificate in `RESULT_RECORDED` has two exits. Ordering a retest cycles the certificate back to `SAMPLED`, increments `retest_count`, and retains the prior `result_ppb` and `determination` until a new recording overwrites them; the retest cycle is capped at two, and ordering a retest when `retest_count` has already reached 2 is rejected with `ERR_RETEST_LIMIT_EXCEEDED`. Confirming the result is the terminal step: the confirming technician's `X-User-ID` must differ from `result_recorded_by` per §2.11 (a self-confirm is rejected with `ERR_SEG_OF_DUTIES`), `confirmed_by` is stamped, and the certificate reaches `CONFIRMED`. Confirmation maps the determination onto the load — `aflatoxin_status` becomes `PASSED`, `SEGREGATED`, or `REJECTED` respectively — and when the determination is `REJECT` and the load is still `WEIGHED` or `GRADED`, the load itself moves terminally to `REJECTED` and may not be stored. The load's `version` increments on confirmation.

### 3.6. Drying Operations and the Operations Checkpoint

When finalization leaves a load's drying axis at `REQUIRED`, the load cannot be stored until it has been dried. A `BuyingPointAdmin` books dryer capacity with a payload of `dryer_id`, `load_id`, `tons`, and `starts_at`. The booking tonnage must equal the load's `gross_tons` (a mismatch is rejected with `ERR_INVALID_REQUEST`), and the load's drying axis must be `REQUIRED` at booking time (otherwise `ERR_INVALID_STATE`); a load may have only one active booking. The booking's `ends_at` is computed, not supplied: the number of cycles is the booking tonnage divided by the dryer's `cycle_capacity_tons`, rounded up to a whole cycle, and the end is the start plus that many cycles times the dryer's `cycle_hours`. Bookings occupy half-open intervals — a new booking whose interval from `starts_at` to `ends_at` intersects another `BOOKED` booking on the same dryer is rejected with `ERR_DRYER_OVERLAP`, while back-to-back adjacency is allowed. At creation the booking snapshots `moisture_at_booking` from the load's finalized grade sheet, opens in `BOOKED` status, flips the load's drying axis to `BOOKED`, and increments the load's `version`. The booking list accepts `dryer_id`, `load_id`, and `status` filters.

Completing a booking records `actual_moisture_after` and moves it to `COMPLETED`. The load's drying axis then becomes `DRIED` if the measured moisture is at or below 10.49 percent; otherwise it returns to `REQUIRED` and the grower must re-book. Completion increments the load's `version`. Cancelling a `BOOKED` booking moves it to `CANCELLED` and returns the load's drying axis to `REQUIRED`.

The drying tariff is settled only on completed work, at settlement time: for each `COMPLETED` booking of an included load, the charge is the number of cycles — booking tonnage divided by the dryer's per-cycle capacity, rounded up — multiplied by `drying_rate_per_cycle_cents` and by a moisture multiplier, with the product rounded half up to whole cents. The multiplier starts at one and increases by 0.05 for each full percentage point by which `moisture_at_booking` exceeds 10.49 percent, disregarding any fractional part of a point. All completed bookings of an included load are charged regardless of the crop year the booking itself was made in; the charge is keyed by the load.

The operations checkpoint is the buying point's sweep of broken commitments. A `BuyingPointAdmin` triggers it; `ops_run_index` increments by one, and the sweep then processes in a pinned order — dryer bookings first, delivery calls second. Every `BOOKED` booking of this buying point whose `ends_at` falls strictly before the current logical clock, processed in ascending `starts_at` order with ties broken by ascending `created_at`, becomes `NO_SHOW`: the load's drying axis returns to `REQUIRED`, and the grower's `no_show_strikes` increments by one. When a grower's strikes reach the limit of 2, the grower moves `ACTIVE` → `SUSPENDED` and every remaining `BOOKED` booking of that grower is cancelled immediately — before those bookings are swept — so a mid-sweep suspension cancels later bookings rather than no-showing them, and already-cancelled bookings are skipped. Each cancelled booking's load returns to `REQUIRED`. A grower suspended for strikes may be reinstated as described in §3.2; an administrative suspension moves `ACTIVE` → `SUSPENDED` directly and likewise cancels the grower's `BOOKED` bookings with their loads returning to `REQUIRED`, and while suspended the grower cannot report new loads (§3.3). The delivery-call half of the sweep is described in §3.8.

### 3.7. Warehousing and Marketing Loans

Storing a graded load creates its storage receipt and is guarded by four layered gates, each with its own rejection. The drying axis must be `NOT_REQUIRED` or `DRIED` (`ERR_DRYING_REQUIRED`). The aflatoxin axis must be `PASSED` or `SEGREGATED` (`ERR_AFLATOXIN_NOT_CLEARED`). The warehouse's `compartment` must match the load's clearance: a `SEGREGATED` load requires a `SEGREGATED` compartment and a `PASSED` load requires a `GENERAL` compartment (`ERR_COMPARTMENT_SEGREGATION`). And the warehouse's `free_tons` must be at least the load's `gross_tons` (`ERR_WAREHOUSE_CAPACITY`). At most one receipt exists per load. The receipt opens `OPEN` with `tons_initial` equal to the load's gross tonnage, a `segregated` snapshot that is true exactly when the load's aflatoxin axis was `SEGREGATED` at store time, and `stored_at` stamped from the logical clock; the warehouse's `stored_tons` increases by the gross tonnage, the buying point's posture recomputes, the load moves `GRADED` → `STORED`, and the load's `version` increments. Receipts may be listed with `warehouse_id`, `load_id`, and `status` filters.

A receipt then lives under its remaining tonnage. `tons_remaining` starts at `tons_initial` and falls with shipped tonnage and forfeitures; when shipments bring it to zero the receipt moves `OPEN` → `CLOSED` automatically and its load becomes `DEPLETED` (§3.8). A re-grade that comes in above the moisture reject threshold cancels an `OPEN` receipt: the warehouse's `stored_tons` is reduced by the remaining tonnage, `tons_remaining` is zeroed, every allocation line referencing the receipt is deleted with its reservation released, any delivery call whose allocations dropped below its requested tonnage reverts `ALLOCATED` → `ISSUED`, and the buying point's posture recomputes.

An `OPEN` receipt may be pledged as marketing-loan collateral by its grower or by a `BuyingPointAdmin`, with a payload of `grower_id`, `storage_receipt_id`, `pledged_tons`, and `maturity_date`; the maturity date is accepted as supplied and is never compared against the logical clock at pledge time. The receipt must be `OPEN` (otherwise `ERR_INVALID_STATE`), the receipt's load must belong to the supplied `grower_id` (otherwise `ERR_INVALID_REQUEST`), and the full-receipt pledge rule applies: `pledged_tons` must equal the receipt's `tons_remaining` — pledging less is rejected with `ERR_INVALID_REQUEST`, pledging more with `ERR_LOAN_UNDER_COLLATERALIZED`. The pledge opens `ACTIVE` with `pledged_at` stamped from the logical clock, and the receipt moves `OPEN` → `PLEDGED` with its `version` incremented.

The principal splits across the loan's two tiers. The grower's loan quota headroom is the annual `quota_tons` minus `used_quota_tons` minus the quota portions of the grower's other `ACTIVE` pledges for the crop year — loans reserve quota headroom without consuming it, and a missing quota history means a quota of zero. `quota_part_tons` is the pledged tonnage capped at that headroom (never below zero), and `additional_part_tons` is the remainder. `principal_cents` is the quota portion times `loan_rate_quota_cents_per_ton`, rounded half up to whole cents, plus the additional portion times `loan_rate_additional_cents_per_ton`, rounded half up to whole cents. Interest accrues on `outstanding_principal_cents` at two basis points per day — two ten-thousandths of principal per whole day elapsed from `pledged_at`, partial days discarded — and `accrued_interest_cents` carries that accrual net of the interest portion of repayments, rounded half up to whole cents. The accrual is anchored stepwise at each repayment: the balance accrued up to the payment date is fixed (rounded half up to whole cents) when the payment is applied, and from then on interest accrues only on the reduced outstanding principal for the whole days elapsed since that fixing.

Repayment is an interest-first waterfall. The payer — the owning grower or an administrator — supplies `amount_cents`, which must be positive and no more than the outstanding principal plus interest accrued to the payment date (otherwise `ERR_INVALID_REQUEST`). The payment retires accrued interest first, recomputed to the payment date, and the remainder retires principal. A partial payment keeps the pledge `ACTIVE`; a payment covering the full outstanding principal plus accrued interest moves the pledge `ACTIVE` → `REPAID`, zeroes both `outstanding_principal_cents` and `accrued_interest_cents`, and returns the receipt `PLEDGED` → `OPEN` with its `version` incremented. A settlement payoff at pay time produces the same `REPAID` outcome (§3.9).

Every pledge read reports collateral two ways. `collateral_value_standard_cents` values the quota portion at the quota purchase price and the additional portion at the additional purchase price, each product rounded half up to whole cents and summed. `collateral_value_conservative_cents` values all pledged tons at the additional-tier price. Against these, `margin_status` is `MARGIN_OK` when the conservative value is at least 110 percent of the outstanding principal plus interest accrued to the current clock — the threshold is compared exactly, with no rounding — and `MARGIN_CALL` otherwise.

Foreclosure is the administrator's remedy on a matured loan: it requires the current logical clock to be strictly later than `maturity_date` (otherwise `ERR_FORECLOSE_NOT_MATURED`) and the outstanding principal plus accrued interest to be above zero (otherwise `ERR_INVALID_STATE`). Foreclosure moves the pledge `ACTIVE` → `FORECLOSED`, records `foreclosure_credit_cents` as the amount by which the standard collateral value exceeds the outstanding exposure (zero when it does not), moves the receipt `PLEDGED` → `FORFEITED`, zeroes the receipt's `tons_remaining`, reduces the warehouse's `stored_tons` by that tonnage, and recomputes the buying point's posture. Pledges may be listed with `grower_id`, `storage_receipt_id`, and `status` filters.

### 3.8. Sheller Contracts, Delivery Calls, and Reconciliation

A sheller contract commits a sheller to buy tonnage out of the warehouses. A `BuyingPointAdmin` creates one in `DRAFT` with the buying point reference `buying_point_id`, the sheller identity `sheller_ref` (the `ShellerRep` ownership anchor of §2.1), a positive `total_units_tons`, the sheller's purchase `price_per_ton_cents`, an `accepts_segregated` flag saying whether aflatoxin-segregated receipts are eligible to fill its calls, and an inclusive contract window from `window_start` to `window_end` (equal endpoints are permitted; a `window_end` before `window_start` is rejected with `ERR_INVALID_REQUEST`). The `price_per_ton_cents` is a non-negative integer. The contract opens with `fulfilled_units_tons` and `default_count` at zero. Activating moves `DRAFT` → `ACTIVE`; contracts may be listed with `buying_point_id`, `sheller_ref`, and `status` filters. A contract's open commitment, `remaining_units_tons`, is the total minus fulfilled tonnage minus the requested tonnage of its `ISSUED` and `ALLOCATED` calls. Cancellation from `DRAFT` or `ACTIVE` is blocked while any call is `ISSUED` or `ALLOCATED` (`ERR_CONTRACT_HAS_OPEN_CALLS`).

Against an `ACTIVE` contract, the `ShellerRep` who owns it issues a delivery call: `contract_id`, a positive `requested_tons`, and a closed dock window from `dock_window_start` to `dock_window_end` (equal endpoints are permitted; a `dock_window_end` before `dock_window_start` is rejected with `ERR_INVALID_REQUEST`). Three constraints guard the call. The requested tonnage must not exceed the contract's `remaining_units_tons` (`ERR_CONTRACT_REMAINING_EXCEEDED`). The dock window must fit fully inside the contract window (`ERR_DOCK_WINDOW_OUTSIDE_CONTRACT`). And dock windows on the same contract may not crowd each other: each call's closed window, expanded by a 120-minute turnaround buffer on both sides, must not intersect any other non-terminal call's buffered window on that contract (`ERR_DOCK_WINDOW_OVERLAP`). The buffered window is closed at both ends: buffered windows that share even a single instant — for instance, a call whose window starts exactly 240 minutes after another call's window ends — count as intersecting, and the incoming call is rejected. A new call opens `ISSUED` with `allocated_tons` and `delivered_tons` at zero; calls may be listed with `contract_id` and `status` filters.

Allocation is the administrator's act of backing a call with physical stock, and it carries the OCC field `expected_delivery_call_version` from §2.8. The selector walks the buying point's eligible receipts — `OPEN` receipts with positive `tons_remaining` in warehouses of the call's contract's buying point, excluding `segregated` receipts unless the contract's `accepts_segregated` allows them — in first-in-first-out order: ascending `stored_at`, ties broken by ascending `created_at`, never by identifier. From each receipt in turn it reserves the smaller of the receipt's remaining tonnage and the call's outstanding need, creating one allocation line per contributing receipt, until the need is met. If the eligible receipts in total cannot cover the requested tonnage, the whole allocation is rejected with `ERR_INSUFFICIENT_ALLOCABLE_TONS` and no partial set of lines is persisted; on a re-allocation that fails this check, the prior lines and their reservations remain untouched. On success the call moves `ISSUED` → `ALLOCATED`, each contributing warehouse's `reserved_tons` rises by its allocated tonnage, the buying point's posture recomputes, and the call's `version` increments. Re-allocating an `ALLOCATED` call is permitted under the same OCC rule: the prior allocation lines are deleted and their reservations released, then the selector runs again from scratch; the call stays `ALLOCATED` and its `version` increments again. Allocation lines are a read-only junction — each records its `delivery_call_id`, `storage_receipt_id`, `allocated_tons`, and later `shipped_tons` and `shelled_tons` — discoverable through the allocation-line list with `delivery_call_id` and `storage_receipt_id` filters.

Delivery executes the allocation as a full truckout: each line's `shipped_tons` becomes its `allocated_tons`, each contributing receipt's `tons_remaining` falls by the shipped tonnage (a receipt reaching zero closes and flips its load to `DEPLETED`), each warehouse's `stored_tons` and `reserved_tons` fall by the shipped amount, and the posture recomputes. The call's `delivered_tons` becomes its `allocated_tons`, the contract's `fulfilled_units_tons` rises by the delivered tonnage — and when fulfillment reaches or exceeds the contracted total, equality included, the contract moves `ACTIVE` → `FULFILLED` and no further delivery calls may be created against it — the call moves `ALLOCATED` → `DELIVERED`, and its `version` increments.

Reconciliation is the sheller's outturn report and belongs to the `ShellerRep` who owns the contract. The sheller supplies `shelled_kernel_tons` and `hull_tons` (either may be zero); the two together may not exceed the delivered tonnage, and the unaccounted remainder — delivered minus shelled kernel minus hull — may not exceed one percent of the delivered tonnage, or the reconcile is rejected with `ERR_HULL_RECONCILE_MISMATCH`. On success the shelled kernel tonnage is attributed across the call's allocation lines pro rata by each line's `shipped_tons` at three-decimal rounding, with any remainder going to the earliest-created line; each contributing receipt's `shelled_tons` accumulates its lines' attribution; a hull lot is created in `GENERATED` status with `tons` equal to the reported hull tonnage; and the call moves `DELIVERED` → `RECONCILED` with its `version` incremented.

Cancelling a call is open to the owning `ShellerRep` or an administrator. From `ISSUED` it simply moves to `CANCELLED`; from `ALLOCATED` it additionally deletes the allocation lines, releases their warehouse reservations, and recomputes the posture.

The operations checkpoint of §3.6 sweeps calls after bookings. Every `ISSUED` or `ALLOCATED` call of this buying point whose `dock_window_end` falls strictly before the current logical clock, processed in ascending `dock_window_end` order with ties broken by ascending `created_at`, becomes `DEFAULTED`: an allocated call's lines are deleted and reservations released, the contract's `default_count` increments by one, and when the count reaches the limit of 2 the contract moves `ACTIVE` → `DEFAULTED` — at which point every remaining `ISSUED` or `ALLOCATED` call on that contract is cancelled, their reservations are released, and the buying point's posture recomputes.

### 3.9. Hull Disposition and Grower Settlement

Reconciliation leaves the buying point holding hulls. A hull lot in `GENERATED` may be listed for sale by an administrator, which records `sale_price_cents_per_ton` (a non-negative integer) and moves it to `LISTED`. Selling a listed lot stamps `sold_at` from the logical clock, computes `revenue_cents` as the lot's tonnage times its sale price per ton rounded half up to whole cents, moves it to `SOLD`, and enters its revenue into the hull pool for future settlements. A lot in `GENERATED` or `LISTED` may instead be disposed of, which records a `disposition_ref` manifest reference and moves it to `DISPOSED`; disposed lots never enter the revenue pool. Hull lots may be listed with `delivery_call_id` and `status` filters.

Settlement is the season's accounting to the grower, computed exclusively by a `SettlementClerk`. The compute request names the `crop_year` being settled and carries `expected_grower_version` per §2.8 — if the grower's `version` has advanced since the clerk last read it, for instance because another settlement for the same grower and year was just computed, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The inclusion set is the grower's loads for that crop year in `STORED` or `DEPLETED` status whose `settlement_id` is still null, in ascending load creation order; a compute that finds no eligible loads is rejected with `ERR_INVALID_STATE`. The compute captures `included_load_ids` and the `offset_pledge_ids` of the grower's `ACTIVE` pledges, stamps `computed_by` from the caller, links `supersedes_settlement_id` to the settlement it replaces (null for the first; when a single compute supersedes several prior settlements, the most recently created of them), and increments the grower's `version`.

The figures build up in a pinned order. Each included load is priced in inclusion order under the quota straddle: its `quota_tons_applied` is the payable tonnage capped at the grower's remaining quota, where remaining quota is the annual `quota_tons` minus `used_quota_tons` minus the quota-tier tonnage of loads earlier in this same settlement's inclusion order — other `COMPUTED` settlements do not reduce this view, a deliberate overcommit window that approval re-validates — and its `additional_tons_applied` is the rest. `gross_value_cents` sums the per-load gross values, each being the quota portion times `quota_price_cents_per_ton` rounded half up to whole cents plus the additional portion times `additional_price_cents_per_ton` rounded half up to whole cents. `discount_cents` sums the per-load discount amounts, and for each load the three discount lines — payable tonnage times the moisture per-ton rate, times the foreign-material per-ton rate, and times the damage per-ton rate — are each rounded half up to whole cents before being summed; summing the rates first and multiplying once is not permitted, as the two orders produce different cent totals. `drying_cents` sums the §3.6 drying charges over `COMPLETED` bookings of the included loads. `loan_offset_cents` sums, over the grower's `ACTIVE` pledges, the outstanding principal plus interest accrued to the settlement's compute date; offsets are frozen at compute — approval and payment never recompute them, and any change requires a fresh superseding settlement. `hull_credit_cents` allocates the hull pool: the pool is the `revenue_cents` of `SOLD` hull lots whose delivery call's contract belongs to this buying point and whose `sold_at` is no later than the settlement's compute date; each grower's shelled tonnage is the sum of allocation-line `shelled_tons` over `RECONCILED` calls attributed to that grower's loads; each contributing grower's base share is the pool times its shelled tonnage divided by the total shelled tonnage, rounded down (floored) to whole cents; and the undistributed remainder is then dealt out one cent at a time to growers in order of their earliest contributing allocation line's `created_at`, ties broken by the grower's own `created_at`, never by identifier, until the remainder is exhausted. A grower's hull credit is zero when no shelled tonnage exists at all. Finally, `net_payment_cents` is the gross value minus discounts, minus drying, minus the loan offset, plus the hull credit.

The new settlement opens in `COMPUTED` status. Computing it supersedes the grower's prior non-terminal settlements for the same crop year: any in `DISPUTED` or `STALE` moves to `SUPERSEDED`. Multiple `COMPUTED` settlements for the same grower and crop year coexist, each having seen the same quota headroom at compute; `APPROVED` and `PAID` settlements are locked and are never superseded.

Approval is a second clerk's act — the approver's `X-User-ID` must differ from `computed_by` (`ERR_SEG_OF_DUTIES`). Two fiscal gates apply, and this is where the quota overcommit window closes: the net payment must not be negative (`ERR_SETTLEMENT_NOT_PAYABLE`), and the live quota check requires the history's `used_quota_tons` plus this settlement's `quota_tons_applied` to be no more than `quota_tons` (`ERR_QUOTA_EXCEEDED`). Approval stamps `approved_by`, adds `quota_tons_applied` into the quota history's `used_quota_tons`, and writes this settlement's id into every included load's `settlement_id` — which is what locks those loads against re-grade per §3.4.

Payment requires a third clerk distinct from the approver (`ERR_SEG_OF_DUTIES`). It stamps `paid_by`, moves `APPROVED` → `PAID`, and pays off the loan offset: every pledge in `offset_pledge_ids` that is still `ACTIVE` moves to `REPAID`, and its storage receipt returns to `OPEN`.

Two exits remain before payment. The grower may dispute its own `COMPUTED` settlement, moving it to `DISPUTED`. And an administrator may void an `APPROVED` settlement, moving it `APPROVED` → `VOIDED`: voiding subtracts `quota_tons_applied` back out of the quota history's `used_quota_tons` — the compensating invariant that keeps consumed quota consistent — and clears every included load's `settlement_id`. A re-grade that supersedes a sheet for an included load sweeps any containing settlement in `COMPUTED` or `DISPUTED` to `STALE`, as §3.4 describes. Settlements may be listed with `grower_id`, `status`, and `supersedes_settlement_id` filters.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, and all reads, return `200 OK`. Error responses use the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/buying-points` | Create a buying point | BuyingPointAdmin |
| GET | `/buying-points/{id}` | Get a buying point (posture, prices, ops_run_index) | BuyingPointAdmin, Grower, GradingInspector, LabTechnician, SettlementClerk, ShellerRep |
| POST | `/buying-points/{id}/run_ops` | Ops-run checkpoint: bump ops_run_index, then sweep bookings and delivery calls in pinned order | BuyingPointAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z) | BuyingPointAdmin |
| POST | `/buying-points/growers` | Register a grower | BuyingPointAdmin |
| GET | `/buying-points/growers/{id}` | Get a grower | BuyingPointAdmin, Grower, SettlementClerk |
| GET | `/buying-points/growers` | List growers (Grower role scoped to its own record) | BuyingPointAdmin, SettlementClerk, Grower |
| POST | `/buying-points/growers/{id}/suspend` | Administratively suspend an ACTIVE grower; cancels the grower's BOOKED dryer bookings | BuyingPointAdmin |
| POST | `/buying-points/growers/{id}/reinstate` | Reinstate a SUSPENDED grower (strikes reset to 0) | BuyingPointAdmin |
| POST | `/buying-points/discount-schedules` | Create a discount schedule (DRAFT) | BuyingPointAdmin |
| GET | `/buying-points/discount-schedules/{id}` | Get a discount schedule | BuyingPointAdmin, GradingInspector, SettlementClerk |
| GET | `/buying-points/discount-schedules` | List discount schedules | BuyingPointAdmin, GradingInspector, SettlementClerk |
| POST | `/buying-points/discount-schedules/{id}/activate` | Activate a schedule; rejects half-open window overlap with any other ACTIVE schedule | BuyingPointAdmin |
| POST | `/buying-points/discount-schedules/{id}/retire` | Retire an ACTIVE schedule (pinned grade sheets unaffected) | BuyingPointAdmin |
| POST | `/buying-points/loads` | Report a farmer stock load (REPORTED); Grower role reports for itself | BuyingPointAdmin, Grower |
| GET | `/buying-points/loads/{id}` | Get a load (all three state axes, payable_tons, provisional estimate) | BuyingPointAdmin, Grower, GradingInspector, LabTechnician, SettlementClerk |
| GET | `/buying-points/loads` | List loads; Grower role auto-scoped to own loads | BuyingPointAdmin, Grower, GradingInspector, LabTechnician, SettlementClerk |
| POST | `/buying-points/loads/{id}/weigh` | Record scale weight; REPORTED to WEIGHED; RESTRICTED posture cap re-checked here | BuyingPointAdmin |
| POST | `/buying-points/loads/{id}/grade-sheets` | Create a DRAFT grade sheet on a WEIGHED/GRADED/STORED load (OCC on load version) | GradingInspector |
| GET | `/buying-points/grade-sheets/{id}` | Get a grade sheet | BuyingPointAdmin, GradingInspector, SettlementClerk |
| GET | `/buying-points/grade-sheets` | List grade sheets | BuyingPointAdmin, GradingInspector, SettlementClerk |
| POST | `/buying-points/grade-sheets/{id}/finalize` | Finalize: pin schedule, compute payable_tons, supersede prior sheet, drive load transitions and STALE cascade | GradingInspector |
| POST | `/buying-points/loads/{id}/aflatoxin-certificates` | Draw an aflatoxin sample; at most one certificate per load; load must be WEIGHED or GRADED | LabTechnician |
| GET | `/buying-points/aflatoxin-certificates/{id}` | Get a certificate | BuyingPointAdmin, LabTechnician, SettlementClerk |
| GET | `/buying-points/aflatoxin-certificates` | List certificates | BuyingPointAdmin, LabTechnician, SettlementClerk |
| POST | `/buying-points/aflatoxin-certificates/{id}/record-result` | Record ppb result; SAMPLED to RESULT_RECORDED; determination recomputed | LabTechnician |
| POST | `/buying-points/aflatoxin-certificates/{id}/confirm` | Confirm result (confirmer must differ from recorder); drives load aflatoxin status | LabTechnician |
| POST | `/buying-points/aflatoxin-certificates/{id}/order-retest` | Re-enter SAMPLED for a retest; retest cap 2 | LabTechnician |
| POST | `/buying-points/dryers` | Create a dryer | BuyingPointAdmin |
| GET | `/buying-points/dryers/{id}` | Get a dryer | BuyingPointAdmin |
| GET | `/buying-points/dryers` | List dryers | BuyingPointAdmin |
| POST | `/buying-points/dryer-bookings` | Book drying capacity; half-open interval exclusivity per dryer; one active booking per load | BuyingPointAdmin |
| GET | `/buying-points/dryer-bookings/{id}` | Get a booking | BuyingPointAdmin |
| GET | `/buying-points/dryer-bookings` | List bookings | BuyingPointAdmin |
| POST | `/buying-points/dryer-bookings/{id}/complete` | Complete a booking; load DRIED iff actual moisture at or below 10.49, else back to REQUIRED | BuyingPointAdmin |
| POST | `/buying-points/dryer-bookings/{id}/cancel` | Cancel a BOOKED booking; load returns to REQUIRED | BuyingPointAdmin |
| POST | `/buying-points/warehouses` | Create a warehouse; recomputes buying point posture | BuyingPointAdmin |
| GET | `/buying-points/warehouses/{id}` | Get a warehouse | BuyingPointAdmin, SettlementClerk |
| GET | `/buying-points/warehouses` | List warehouses | BuyingPointAdmin, SettlementClerk |
| POST | `/buying-points/storage-receipts` | Store a GRADED load through the layered gates; creates an OPEN receipt | BuyingPointAdmin |
| GET | `/buying-points/storage-receipts/{id}` | Get a receipt | BuyingPointAdmin, Grower, SettlementClerk |
| GET | `/buying-points/storage-receipts` | List receipts | BuyingPointAdmin, Grower, SettlementClerk |
| POST | `/buying-points/loan-pledges` | Pledge an OPEN receipt as loan collateral; principal uses the quota tier split | BuyingPointAdmin, Grower |
| GET | `/buying-points/loan-pledges/{id}` | Get a pledge (computed interest, collateral variants, margin status at current clock) | BuyingPointAdmin, Grower, SettlementClerk |
| GET | `/buying-points/loan-pledges` | List pledges; Grower role auto-scoped to own | BuyingPointAdmin, Grower, SettlementClerk |
| POST | `/buying-points/loan-pledges/{id}/repay` | Repay with the interest-first waterfall; full payoff marks REPAID and reopens the receipt | BuyingPointAdmin, Grower |
| POST | `/buying-points/loan-pledges/{id}/foreclose` | Foreclose a matured ACTIVE pledge; receipt forfeited, credit recorded | BuyingPointAdmin |
| POST | `/buying-points/sheller-contracts` | Create a sheller contract (DRAFT) | BuyingPointAdmin |
| GET | `/buying-points/sheller-contracts/{id}` | Get a contract (ShellerRep scoped to own sheller_ref) | BuyingPointAdmin, ShellerRep, SettlementClerk |
| GET | `/buying-points/sheller-contracts` | List contracts; ShellerRep auto-scoped to own | BuyingPointAdmin, ShellerRep, SettlementClerk |
| POST | `/buying-points/sheller-contracts/{id}/activate` | Activate a contract | BuyingPointAdmin |
| POST | `/buying-points/sheller-contracts/{id}/cancel` | Cancel a DRAFT/ACTIVE contract; blocked while calls are open | BuyingPointAdmin |
| POST | `/buying-points/delivery-calls` | Issue a delivery call against an ACTIVE own contract; dock window must fit contract window and buffered non-overlap | ShellerRep |
| GET | `/buying-points/delivery-calls/{id}` | Get a delivery call | BuyingPointAdmin, ShellerRep, SettlementClerk |
| GET | `/buying-points/delivery-calls` | List delivery calls; ShellerRep auto-scoped to own contracts | BuyingPointAdmin, ShellerRep, SettlementClerk |
| POST | `/buying-points/delivery-calls/{id}/allocate` | Run the FIFO allocation selector; OCC on call version; re-allocation supersedes prior lines | BuyingPointAdmin |
| POST | `/buying-points/delivery-calls/{id}/deliver` | Ship all allocated tonnage; receipts decrement/close; contract fulfillment bubble-up; posture recompute | BuyingPointAdmin |
| POST | `/buying-points/delivery-calls/{id}/reconcile` | Sheller reports shelled outturn; tolerance-checked; creates hull lot and attributes shelled tons per line | ShellerRep |
| POST | `/buying-points/delivery-calls/{id}/cancel` | Cancel an ISSUED/ALLOCATED call; releases reservations | BuyingPointAdmin, ShellerRep |
| GET | `/buying-points/allocation-lines/{id}` | Get an allocation line | BuyingPointAdmin, SettlementClerk |
| GET | `/buying-points/allocation-lines` | List allocation lines (discovery channel for cascade-created lines) | BuyingPointAdmin, SettlementClerk |
| POST | `/buying-points/growers/{growerId}/settlements` | Compute a settlement for grower and crop year; supersedes the prior non-terminal settlement; OCC on grower version | SettlementClerk |
| GET | `/buying-points/settlements/{id}` | Get a settlement | BuyingPointAdmin, SettlementClerk, Grower |
| GET | `/buying-points/settlements` | List settlements; Grower role auto-scoped to own | BuyingPointAdmin, SettlementClerk, Grower |
| POST | `/buying-points/settlements/{id}/approve` | Approve a COMPUTED settlement; approver must differ from computer; consumes quota; locks included loads | SettlementClerk |
| POST | `/buying-points/settlements/{id}/dispute` | Grower disputes a COMPUTED settlement | Grower |
| POST | `/buying-points/settlements/{id}/pay` | Pay an APPROVED settlement; payer must differ from approver; offset pledges are paid off | SettlementClerk |
| POST | `/buying-points/settlements/{id}/void` | Void an APPROVED settlement pre-payment; releases quota and load locks | BuyingPointAdmin |
| POST | `/buying-points/quota-histories` | Record a grower's annual poundage quota; unique per grower and crop year | BuyingPointAdmin |
| GET | `/buying-points/quota-histories/{id}` | Get a quota history | BuyingPointAdmin, SettlementClerk, Grower |
| GET | `/buying-points/quota-histories` | List quota histories; Grower role auto-scoped to own | BuyingPointAdmin, SettlementClerk, Grower |
| GET | `/buying-points/hull-lots/{id}` | Get a hull lot | BuyingPointAdmin, SettlementClerk |
| GET | `/buying-points/hull-lots` | List hull lots (discovery channel for reconcile-created lots) | BuyingPointAdmin, SettlementClerk |
| POST | `/buying-points/hull-lots/{id}/list-for-sale` | List a GENERATED hull lot for sale | BuyingPointAdmin |
| POST | `/buying-points/hull-lots/{id}/sell` | Sell a LISTED hull lot; revenue enters the hull credit pool at sold_at | BuyingPointAdmin |
| POST | `/buying-points/hull-lots/{id}/dispose` | Dispose a GENERATED/LISTED hull lot (never enters the revenue pool) | BuyingPointAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNERSHIP_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_GROWER_SUSPENDED` | 409 |
| `ERR_INTAKE_SUSPENDED` | 409 |
| `ERR_RESTRICTED_LOAD_LIMIT` | 409 |
| `ERR_SEG_OF_DUTIES` | 409 |
| `ERR_NO_ACTIVE_SCHEDULE` | 409 |
| `ERR_SCHEDULE_WINDOW_OVERLAP` | 409 |
| `ERR_CERTIFICATE_EXISTS` | 409 |
| `ERR_RETEST_LIMIT_EXCEEDED` | 409 |
| `ERR_AFLATOXIN_NOT_CLEARED` | 409 |
| `ERR_COMPARTMENT_SEGREGATION` | 409 |
| `ERR_DRYING_REQUIRED` | 409 |
| `ERR_WAREHOUSE_CAPACITY` | 409 |
| `ERR_DRYER_OVERLAP` | 409 |
| `ERR_DOCK_WINDOW_OVERLAP` | 409 |
| `ERR_DOCK_WINDOW_OUTSIDE_CONTRACT` | 409 |
| `ERR_CONTRACT_REMAINING_EXCEEDED` | 409 |
| `ERR_CONTRACT_HAS_OPEN_CALLS` | 409 |
| `ERR_INSUFFICIENT_ALLOCABLE_TONS` | 409 |
| `ERR_DUPLICATE_QUOTA_HISTORY` | 409 |
| `ERR_LOAN_UNDER_COLLATERALIZED` | 409 |
| `ERR_FORECLOSE_NOT_MATURED` | 409 |
| `ERR_SETTLEMENT_NOT_PAYABLE` | 409 |
| `ERR_QUOTA_EXCEEDED` | 409 |
| `ERR_LOAD_LOCKED_BY_SETTLEMENT` | 409 |
| `ERR_HULL_RECONCILE_MISMATCH` | 409 |
