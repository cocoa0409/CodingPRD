# Juice Bottling Plant API — Product Requirements Document

## 1. Introduction

A beverage co-packing bottler does not own the products it ships. Brand owners arrive with formulas — a target sugar content, a kill-step process, a container format, a set of label claims — and the plant commits shared, finite resources to turn each approved recipe into finished, shippable goods: blending tanks that must be washed between incompatible allergens, pasteurization and high-pressure processing capacity whose parameters must be proven rather than assumed, bottling lines that need reconfiguration between container formats, chilled warehouse bays, and a floating pool of returnable pallets. Every one of these commitments is constrained, and most of the constraints cross entity boundaries: a formula whose label claims are under review cannot be confirmed for production, a batch that failed its sugar reading cannot be bottled, and a customer who has breached its credit line cannot place another order.

This document specifies the Juice Bottling Plant API, a flat resource space mounted under `/v1` that governs the full co-pack lifecycle: customer onboarding and credit control, formula registration and label-claim compliance review, tank booking and blending with quality verdicts and corrective reblending, process validation for both kill-step technologies, container supply quality, production-run scheduling and execution, finished-goods warehousing with shelf-life dating, first-expired-first-out distribution, invoicing, pallet escrow accounting, and a housekeeping epoch that sweeps expiries, stale orders, credit breaches, and aging pallets. Two design commitments pervade the system. First, time inside the plant is driven by a single logical clock rather than the wall clock, so every temporal gate — cleaning durations, booking windows, delivery dates, expiry — reads the same deterministic instant. Second, judgment is deliberately segregated from execution: the operator who blends a batch may not pass it, and the developer who submits a label may not approve it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes ten operational roles: `PlantManager`, `FinanceClerk`, `ProductDeveloper`, `LabelComplianceReviewer`, `BlendOperator`, `QAInspector`, `ProductionPlanner`, `WarehouseLead`, `CustomerServiceRep`, and `CustomerContact`. The label `Any`, used throughout this document, means any authenticated caller and applies to the read-only retrieval endpoints. Attempting an operation outside one's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Identity semantics differ by role. When `X-User-Role` is `PlantManager`, `FinanceClerk`, `ProductDeveloper`, `LabelComplianceReviewer`, `BlendOperator`, `QAInspector`, `ProductionPlanner`, `WarehouseLead`, or `CustomerServiceRep`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow demands an actor stamp — for example as `blended_by_user_id` on a batch, `submitted_by_user_id` on a formula, or `reviewer_user_id` on a label review — but it does not compare it to any entity's `id`. When `X-User-Role` is `CustomerContact`, the `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`, and a `CustomerContact` attempting to act for any other customer is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

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

List endpoints accept two query parameters. The `limit` parameter bounds the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless stated otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Calendar Semantics

Plant time is a server-held logical clock, never the wall clock. Before any clock-setting call, the clock reads exactly 2026-08-01T00:00:00Z. A `PlantManager` advances it by supplying `to_iso8601`; the supplied instant must be at or after the current reading — setting an earlier instant is rejected with `ERR_CLOCK_REGRESSION` — and the response reports the resulting `current_utc`. All window comparisons in the plant are made at minute granularity.

Two window dialects coexist and must never be conflated. Tank occupation windows are **closed intervals**: a batch booked from its `planned_start_at` through its `planned_end_at` occupies the tank at both endpoints. Bottling-line bookings are **half-open intervals**: a run booked from its `scheduled_start_at` to its `scheduled_end_at` occupies the line from the start inclusive up to but not including the end. Shelf-life dating, pallet aging, and stale-order aging are calendar computations over `YYYY-MM-DD` dates; the calendar date of any instant is the date component of the logical clock.

### 2.5. Common Resource Properties

Every primary resource carries a standard bookkeeping quartet:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): the same format, refreshed on every change to the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation, including mutations the server applies itself as side effects of another operation.

Two record types are deliberately leaner. A pallet ledger entry and a housekeeping epoch record are append-only facts: each carries only `id` and `created_at`, and both `updated_at` and `version` are absent from them.

### 2.6. Validation Discipline and Error Precedence

Every request is validated against a fixed pipeline of check categories, evaluated in the order below; when several checks would fail, the earliest category's error is the one returned. This ordering is part of the contract, not an implementation detail.

1. **Header presence.** The two identity headers must be present and non-empty.
2. **Role authorization.** The caller's role must be listed for the endpoint, and a `CustomerContact` may act only on its own `customer_id`.
3. **Path existence.** Resource identifiers in the path are validated strictly left to right, and the first miss surfaces as that resource's not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_FORMULA_NOT_FOUND`, `ERR_LABEL_REVIEW_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_PROCESS_RUN_NOT_FOUND`, `ERR_CONTAINER_LOT_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_PRODUCTION_RUN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_SHIPMENT_ORDER_NOT_FOUND`, or `ERR_PALLET_ACCOUNT_NOT_FOUND`. A retrieval of one customer's production runs against a nonexistent customer therefore reports the missing customer before any list is contemplated.
4. **Optimistic-concurrency agreement** on the three endpoints that carry it (§2.7), rejected as `ERR_STALE_VERSION`.
5. **State-machine admissibility** of the target entity, plus cross-entity state gates such as the customer being `ACTIVE`; this family reports `ERR_CUSTOMER_STATE_INVALID`, `ERR_CUSTOMER_NOT_ACTIVE`, `ERR_FORMULA_STATE_INVALID`, `ERR_REVIEW_STATE_INVALID`, `ERR_TANK_STATE_INVALID`, `ERR_BATCH_STATE_INVALID`, `ERR_PROCESS_RUN_STATE_INVALID`, `ERR_PROCESS_RUN_ACTIVE_EXISTS`, `ERR_CONTAINER_LOT_STATE_INVALID`, `ERR_LINE_STATE_INVALID`, `ERR_RUN_STATE_INVALID`, `ERR_LOT_STATE_INVALID`, and `ERR_ORDER_STATE_INVALID`.
6. **Label and quality safety gates**: formula label approval at run confirm and schedule, pinned-label currency at run start, segregation of duties on quality verdicts, dispositions, releases, and label decisions, process validation before release, and the brix tolerance band — the `ERR_LABEL_NOT_APPROVED`, `ERR_LABEL_VERSION_STALE`, `ERR_SOD_QA_SELF_APPROVAL`, `ERR_SOD_LABEL_SELF_REVIEW`, `ERR_PROCESS_NOT_VALIDATED`, and `ERR_BRIX_OUT_OF_TOLERANCE` family, guarding the confirm, schedule, start, verdict, disposition, release, and label-decision operations.
7. **Referential linkability**: a batch must be released, unlinked, and of the run's formula before it can back a schedule; a container lot must be untouched before it can be returned — the `ERR_BATCH_NOT_RELEASED` and `ERR_BATCH_ALREADY_LINKED` family, guarding scheduling and container-lot return.
8. **Structural constraints** (the 422 family): window shape, tank capacity, minimum batch size, tank-window spacing, line changeover spacing, supported container types, the minimum run size, the reblend limit, adjustment capacity, fill-count bounds, zone temperature and capacity rules, container supply sufficiency, formula-customer agreement, and payment bounds.
9. **Clock-relative gates**: clean-in-place duration, run-window activity, delivery dates in the past, and clock monotonicity — the `ERR_CIP_DURATION_INSUFFICIENT`, `ERR_RUN_WINDOW_NOT_ACTIVE`, `ERR_DELIVERY_DATE_IN_PAST`, and `ERR_CLOCK_REGRESSION` family, guarding wash completion, run start, order placement, and clock setting.
10. **Money gates**: the reactivation threshold and the pallet-return ceiling — `ERR_REACTIVATION_THRESHOLD_NOT_MET` and `ERR_PALLET_RETURN_EXCEEDS_OUTSTANDING`, guarding customer reactivation and pallet returns.

A request that is both stale (category 4) and structurally invalid (category 8) is answered with the staleness error; a request whose role is wrong never reaches the existence checks. Independently of this pipeline, payloads that are malformed in a basic sense — a missing required field, a value of the wrong type, or an enum member outside its documented set — are rejected with `ERR_INVALID_REQUEST`.

### 2.7. Optimistic Concurrency Control

Exactly three write operations participate in optimistic concurrency control, each checked against its parent entity's current `version`:

- Submitting a formula for label review (`POST /v1/formulas/{id}/submit-label-review`) requires the request to carry `expected_formula_version` equal to the formula's current `version`.
- Scheduling or re-scheduling a production run (`POST /v1/production-runs/{id}/schedule`) requires `expected_production_run_version` equal to the run's current `version`.
- Allocating or topping up a shipment order (`POST /v1/shipment-orders/{id}/allocate`) requires `expected_shipment_order_version` equal to the order's current `version`.

In each case the field is non-optional. If the supplied value does not equal the parent entity's current `version` — because a prior successful write has legitimately advanced it since the client last read the resource — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no part of the write is applied. Endpoints not listed above do not take a version field.

### 2.8. Units, Precision, and Pinned Rounding

Batch volumes and every computed blend addition are tracked to a tenth of a liter, rounded half up. The giveaway volume computed at run completion is likewise expressed to one decimal place, half up. All monetary amounts are integer cents; the only rounding applied to money is the half-up rounding of the giveaway deduction at invoice finalization (§3.8). Window and duration comparisons are made at minute granularity (§2.4); date arithmetic is calendar-day arithmetic over `YYYY-MM-DD` dates.

Several calculations pin their rounding order, and the pinned order is part of the contract: theoretical container counts round down after division; the container-supply overage rounds up after the five-percent inflation; billable units are floored to whole cases of twelve and only then scaled back up — never computed by rounding a sum; a production run's pallet count is a single ceiling over its filled units, while a shipment order's pallet count ceilings each allocated lot separately and sums those ceilings; the high-pressure shelf-life extension floors after multiplication; and the credit-reactivation threshold floors after the four-fifths multiplication.

### 2.9. Conserved Quantities and Ledger Invariants

Three conservation laws hold at every observable instant, and every side effect in §3 preserves them. On a container lot, `quantity_received` always equals `quantity_available` plus `quantity_reserved` plus `quantity_consumed`. On a batch, `quantity_liters` always equals `initial_quantity_liters` plus `added_water_liters` plus `added_concentrate_liters`. On a pallet account, `pallets_outstanding` always equals `pallets_out_total` minus `pallets_returned_total` minus `pallets_converted_total` and never goes negative, and `escrow_balance_cents` always equals `pallets_outstanding` multiplied by the owning customer's `pallet_deposit_cents`. Warehouse occupancy is derived rather than stored independently: a zone's `pallets_stored` is the sum of `pallet_count` over the finished-good lots residing in that zone that still have units remaining on site.

### 2.10. Cascading Integrity

State changes in the plant rarely stay on one entity. Condemning a batch aborts its live process runs, blocks the production run that reserved it, releases that run's container reservations, and frees its line window. A label rejection demotes every confirmed run of the formula; a later approval restores them. The expiry or recall of a finished lot strips allocations off open shipment orders and demotes the shorted ones. Completing a run fans out into a finished-goods lot, container consumption, batch consumption, and a provisional ledger posting. The server applies each cascade synchronously, within the request that triggered it, and each affected resource is mutated in the ordinary sense — its `updated_at` refreshed and its `version` advanced per §2.5.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and the Credit Lifecycle

A `PlantManager` onboards a co-pack customer by supplying its display `name`, its `credit_limit_cents`, its `minimum_run_units`, and its `pallet_deposit_cents`. The account is born in `PENDING_CREDIT` with `outstanding_balance_cents` at zero, and exactly one pallet account is created alongside it with every counter at zero (§3.10). The declared minimum run is a standing co-pack floor: every production run for this customer must plan at least that many units when it confirms (§3.7). The pallet deposit is the per-pallet escrow charged each time finished goods leave the building on returnable pallets.

Credit approval — moving the account from `PENDING_CREDIT` to `ACTIVE` — is a `FinanceClerk` action that requires the account to currently sit in `PENDING_CREDIT`; any other state draws `ERR_CUSTOMER_STATE_INVALID`. An `ACTIVE` customer can be placed on manual hold (`ACTIVE` → `SUSPENDED`) by a `FinanceClerk`, and the housekeeping epoch can impose the same transition automatically when the ledger breaches the credit line (§3.10). A suspended customer is locked out of new commercial commitment: confirming a production run, placing a shipment order, and allocating a shipment order all require the customer to be `ACTIVE`, and each is refused with `ERR_CUSTOMER_NOT_ACTIVE` while the hold stands.

Reactivation carries a deliberate hysteresis band. The account must sit in `SUSPENDED`, and its `outstanding_balance_cents` must have fallen to no more than the floor of four-fifths of `credit_limit_cents`; otherwise the attempt is refused with `ERR_REACTIVATION_THRESHOLD_NOT_MET`. Paying the balance down to exactly the credit limit is not enough — the gate demands real headroom below it.

The outstanding balance itself is a ledger, not a field anyone sets directly: it grows by provisional invoice postings (§3.8) and by pallet escrow charges at shipment (§3.10), and it shrinks by payments, by pallet-return credits, and by the giveaway delta posted when an invoice is finalized. A `FinanceClerk` posts a payment by supplying `amount_cents`; the amount must be strictly greater than zero and no greater than the current `outstanding_balance_cents`, else the posting is refused with `ERR_PAYMENT_INVALID_AMOUNT`, and a successful posting reduces the balance by exactly that amount.

Closing an account requires a clean plant. Closure from `ACTIVE` or `SUSPENDED` to `CLOSED` — again a `FinanceClerk` action — is refused with `ERR_CUSTOMER_STATE_INVALID` while any of the customer's production runs sits in `QUOTED`, `CONFIRMED`, `SCHEDULED`, `IN_PRODUCTION`, `BLOCKED_SUPPLY`, or `BLOCKED_LABEL`, while any of its shipment orders sits in `PLACED`, `ALLOCATED`, `PICKED`, or `BACKORDERED`, or while its pallet account still shows a non-zero `pallets_outstanding`. The customer directory can be listed with an optional `status` filter, and each account exposes reverse listings of its production runs, its shipment orders, and its pallet account — the last returned as an array holding zero or one element.

### 3.2. Formula Registration and the Label-Claim Review Loop

A `ProductDeveloper` registers a formula for its owning customer (`customer_id`) with a recipe code (`formula_code`) unique within that customer's catalogue, a display `name`, a `target_brix` together with the inclusive `brix_tolerance` band surrounding it, a `process_type` of `PASTEURIZATION` or `HPP`, the nominal `container_fill_ml`, the `concentrate_brix` of the concentrate used for upward sugar correction, an `allergen_group` of `NONE`, `SULFITE`, `TREE_NUT`, or `MILK`, a label-claim `shelf_life_days` counted in calendar days from the production date, and a list of `claims` drawn from `ORGANIC`, `NON_GMO`, `NO_ADDED_SUGAR`, `VITAMIN_C`, and `COLD_PRESSED`. A new formula is born `DRAFT` with `label_version` at zero.

Submitting a formula for label review moves it into `LABEL_REVIEW` from `DRAFT`, `REVISION_REQUIRED`, `APPROVED`, or even from `LABEL_REVIEW` itself; any other source state draws `ERR_FORMULA_STATE_INVALID`. The submission carries the optimistic-concurrency field described in §2.7. Each accepted submission creates a fresh `LabelClaimReview` standing in `PENDING`, freezes the formula's current `claims` into the review's `claims_snapshot`, stamps `submitted_by_user_id` with the caller, flips any still-`PENDING` earlier review of the same formula to `SUPERSEDED`, and advances the formula's `version` by one — which is precisely why a second submission bearing the previously observed version reads as stale. Re-submitting an `APPROVED` formula does not demote runs already `CONFIRMED` on it; their pinned label version remains current unless and until a later approval bumps the formula's label version.

Decisions belong to a `LabelComplianceReviewer`, and the review loop is segregated: the deciding reviewer's `X-User-ID` must differ from the formula's `submitted_by_user_id`, else the decision is refused with `ERR_SOD_LABEL_SELF_REVIEW`. The review must still stand in `PENDING`, else `ERR_REVIEW_STATE_INVALID`, and an approval only lands when the decided review is the formula's current pending review. Approval moves the review to `APPROVED`, records the decider in `reviewer_user_id`, returns the formula to `APPROVED`, increments `label_version` by exactly one, and automatically restores every production run of that formula sitting in `BLOCKED_LABEL` back to `CONFIRMED`. Rejection — which may carry an optional `review_note` — moves the review to `REJECTED`, drops the formula to `REVISION_REQUIRED`, and cascades every `CONFIRMED` run of the formula into `BLOCKED_LABEL` (§2.10).

Retirement moves a formula terminally to `RETIRED`; it is permitted only from `DRAFT` or `APPROVED`, and only while no production run of the formula occupies `QUOTED`, `CONFIRMED`, `SCHEDULED`, `IN_PRODUCTION`, `BLOCKED_SUPPLY`, or `BLOCKED_LABEL`; violations draw `ERR_FORMULA_STATE_INVALID`. The formula catalogue can be browsed with optional `customer_id` and `status` filters, and each formula exposes reverse listings of its label reviews and of the batches blended from it.

### 3.3. Booking the Blend: Tanks, Batches, and Clean-in-Place

Before any juice moves, a `PlantManager` registers each blending tank with a human `tank_code` and its `capacity_liters` working volume; the tank begins with `posture` of `AVAILABLE` and an `allergen_group` of `NONE`.

A `BlendOperator` plans a batch by naming its `formula_id` and `tank_id` and booking a closed tank-occupation window from `planned_start_at` through `planned_end_at` — both endpoints included — with the end strictly after the start, else `ERR_INVALID_WINDOW`. The initial `quantity_liters` must be at least 500 liters, else `ERR_BATCH_TOO_SMALL`, and must not exceed the tank's capacity, else `ERR_TANK_CAPACITY_EXCEEDED`. The tank must currently stand `AVAILABLE`, else `ERR_TANK_STATE_INVALID`. The new window must also respect the bookings already held on that tank: batches in `PLANNED`, `BLENDING`, `AWAITING_QA`, `QA_PASSED`, `QA_FAILED`, or `PROCESSING` still hold their windows, while batches in `PROCESSED`, `RELEASED`, `CONDEMNED`, or `CONSUMED` have vacated. Two windows on the same tank coexist only when a flat three-hour hygiene gap fits between them — the later window's start must fall at least three hours after the earlier window's end, in either order, and a gap of exactly three hours suffices; crowding is rejected with `ERR_TANK_WINDOW_CONFLICT`.

Creating the batch lands it in `PLANNED`, stamps `initial_quantity_liters` equal to the requested volume — an anchor that is never overwritten — and flips the tank from `AVAILABLE` to `OCCUPIED`, pointing `occupying_batch_id` at the new batch and adopting the formula's allergen group as the tank's `allergen_group`. When the operator begins blending (`PLANNED` → `BLENDING`), the batch must stand in `PLANNED` (else `ERR_BATCH_STATE_INVALID`) and the tank must currently be `OCCUPIED` by this very batch (else `ERR_TANK_STATE_INVALID`). Recording the blend (`BLENDING` → `AWAITING_QA`) captures the measured sugar content into `measured_brix` and stamps `blended_by_user_id` with the acting operator — the segregation marker that every later quality decision checks against.

A batch vacates its tank the moment it enters processing, or the moment it is condemned: the tank's posture falls from `OCCUPIED` to `AWAITING_CIP` and `occupying_batch_id` clears. From `AWAITING_CIP`, a `BlendOperator` begins clean-in-place (any other posture draws `ERR_TANK_STATE_INVALID`), which stamps `cip_started_at` from the logical clock and computes `cip_required_hours` — six hours when the tank's recorded allergen group is anything other than `NONE`, two hours otherwise. Completing the wash is allowed only from `IN_CIP` and only once the clock has reached `cip_started_at` plus the required hours; finishing at exactly the required instant is permitted, while an earlier attempt is refused with `ERR_CIP_DURATION_INSUFFICIENT`. Completion returns the posture to `AVAILABLE`, resets the tank's `allergen_group` to `NONE`, and clears `cip_started_at`. Tanks can be listed and inspected individually, and each tank exposes a reverse listing of its batches. The batch book itself can be listed with optional `formula_id`, `tank_id`, and `status` filters.

### 3.4. Quality Verdicts, Brix Correction, and Condemnation

Quality judgment is rendered by a `QAInspector` who must not be the operator who blended the batch: a caller whose `X-User-ID` equals the batch's `blended_by_user_id` is refused with `ERR_SOD_QA_SELF_APPROVAL`. This segregation check guards the verdict, the condemnation, the release, and the process disposition described here and in §3.5.

The verdict on a batch standing in `AWAITING_QA` — any other state draws `ERR_BATCH_STATE_INVALID` — takes a `verdict` of `PASS` or `FAIL`. Passing is gated by chemistry: the absolute gap between `measured_brix` and the formula's `target_brix` must not exceed the formula's `brix_tolerance`, with the boundary inclusive, and a `PASS` attempted outside the band is rejected with `ERR_BRIX_OUT_OF_TOLERANCE`. A passing verdict lands the batch in `QA_PASSED`; a failing one lands it in `QA_FAILED`.

A failed batch may be corrected at most twice: once `adjustment_count` has reached two, a further correction attempt is refused with `ERR_REBLEND_LIMIT_EXCEEDED`. The correction itself is computed, not guessed. When the blend is too sweet — measured above target by more than the tolerance — the system dilutes with water all the way to target, not merely to the band's edge: the addition equals the current `quantity_liters` multiplied by the excess of `measured_brix` over `target_brix`, divided by `target_brix`. When the blend is too thin — measured below target by more than the tolerance — the system fortifies with concentrate, again to target: the addition equals `quantity_liters` multiplied by the shortfall of `measured_brix` below `target_brix`, divided by the difference between the formula's `concentrate_brix` and its `target_brix`. The computed addition is rounded to the nearest tenth of a liter, half up, before the capacity check is applied. A correction requested while the measurement still sits inside the tolerance band is refused with `ERR_NOTHING_TO_ADJUST`, and one whose rounded addition would push the batch past the tank's `capacity_liters` is refused with `ERR_ADJUSTMENT_EXCEEDS_TANK_CAPACITY` — no partial addition is ever applied. A successful correction accumulates into `added_water_liters` or `added_concentrate_liters` as appropriate, grows `quantity_liters` by the same addition, increments `adjustment_count` by one, and returns the batch to `BLENDING` for re-measurement, preserving the mass-balance invariant of §2.9 throughout.

Condemnation is the heaviest hammer in the plant. A `QAInspector` may condemn a batch standing in `QA_FAILED`, `PROCESSED`, or `RELEASED` — any other state draws `ERR_BATCH_STATE_INVALID` — subject to the same self-approval bar, including condemnation after release when a retained sample fails. The cascade runs four hops deep (§2.10): any of the batch's process runs still standing in `SCHEDULED`, `RUNNING`, or `DEVIATED` is aborted; the production run currently reserving the batch through its `linked_run_id`, if that run sits in `SCHEDULED`, is demoted to `BLOCKED_SUPPLY`; that run's container reservations are released back to their lots; and its bottling-line window is freed. If the tank was still `OCCUPIED` by the condemned batch, its posture drops to `AWAITING_CIP` at the same moment.

Release is gated on validated processing. Releasing from `PROCESSED` is the ordinary path — the validation gate already held when the batch completed processing. Releasing straight out of `PROCESSING` is the fast path: the governing process run — the batch's latest process run that is not `ABORTED` — must stand in `VALIDATED` or `DISPOSITION_RELEASED`, else the release is refused with `ERR_PROCESS_NOT_VALIDATED`; and if the loss figures have not yet been computed, they are computed at release exactly as they would have been at processing completion (§3.5). From either source the batch must currently stand in `PROCESSED` or `PROCESSING`, else `ERR_BATCH_STATE_INVALID`, and a successful release lands it in `RELEASED`, eligible to back a production schedule (§3.7).

### 3.5. Process Validation: Pasteurization and High-Pressure Processing

A `QA_PASSED` batch is committed to the kill step by a `BlendOperator`, who supplies the `batch_id` and the setpoints appropriate to the formula's process. The run's `process_type` is copied from the formula at creation; a pasteurization run requires `setpoint_temp_c` and `setpoint_hold_seconds`, while an HPP run requires `setpoint_pressure_mpa` and `setpoint_pressure_hold_seconds`. A batch carries at most one live process run — creating another while a sibling stands in `SCHEDULED` or `RUNNING` is refused with `ERR_PROCESS_RUN_ACTIVE_EXISTS` — and the batch itself must stand in `QA_PASSED`, else `ERR_BATCH_STATE_INVALID`. The new run stands in `SCHEDULED`.

Starting the run moves it from `SCHEDULED` to `RUNNING` (any other source state draws `ERR_PROCESS_RUN_STATE_INVALID`) and again requires the batch to be `QA_PASSED` (else `ERR_BATCH_STATE_INVALID`). The start moves the batch from `QA_PASSED` into `PROCESSING` and — because the product has physically left the tank — drops the tank's posture from `OCCUPIED` to `AWAITING_CIP`, clearing `occupying_batch_id`.

Completion is where the readings arrive. For a pasteurization run the operator reports `min_temp_c` and `time_below_setpoint_seconds`; for an HPP run, `min_pressure_mpa` and `pressure_hold_shortfall_seconds`, the latter counting the seconds by which the pressure hold fell short of its setpoint. The run must stand in `RUNNING`, else `ERR_PROCESS_RUN_STATE_INVALID`. Judgment then follows fixed, inclusive thresholds. For pasteurization: when `min_temp_c` is at least `setpoint_temp_c` and `time_below_setpoint_seconds` is exactly zero, the run is `VALIDATED` with `deviation_class` `NONE`; otherwise, when `min_temp_c` is no more than two degrees Celsius below the setpoint and `time_below_setpoint_seconds` is no more than sixty seconds, the run is `DEVIATED` with `deviation_class` `MINOR`; anything worse is `DEVIATED` with `deviation_class` `MAJOR`. For HPP the same three-way ladder applies on its own axes: `min_pressure_mpa` at least `setpoint_pressure_mpa` with `pressure_hold_shortfall_seconds` exactly zero yields `VALIDATED` and `NONE`; pressure no more than twenty megapascals below setpoint with a shortfall of no more than thirty seconds yields `DEVIATED` and `MINOR`; anything worse yields `DEVIATED` and `MAJOR`.

A `VALIDATED` run immediately completes its batch's processing: the batch moves from `PROCESSING` to `PROCESSED`, and the process loss is booked — `loss_liters` is two percent of the batch's current `quantity_liters`, rounded to the nearest tenth of a liter half up, and `processed_liters` is what remains of `quantity_liters` after that loss. A `DEVIATED` run leaves its batch in `PROCESSING` pending disposition. A `BlendOperator` may also abort a run standing in `SCHEDULED` or `RUNNING` (any other state draws `ERR_PROCESS_RUN_STATE_INVALID`); aborting a run whose batch had entered `PROCESSING` returns the batch to `QA_PASSED`, so a replacement run can be scheduled against it, and condemnation (§3.4) aborts live runs without any manual request.

Disposition of a deviated run belongs to a `QAInspector` under the same self-approval bar as §3.4 — the caller must differ from the batch's `blended_by_user_id`, else `ERR_SOD_QA_SELF_APPROVAL` — and the run must stand in `DEVIATED`, else `ERR_PROCESS_RUN_STATE_INVALID`. A `disposition` of `RELEASE` moves the run to `DISPOSITION_RELEASED` and completes the batch's processing exactly as a validation would have: the batch moves to `PROCESSED` and the loss figures are booked. A `disposition` of `REJECT` moves the run to `DISPOSITION_REJECTED`, condemns the batch out of `PROCESSING`, and fires the full condemn cascade of §3.4 — with the nuance that the process run itself is already terminal, so the cascade's first hop has nothing left to abort. Each batch exposes reverse listings of the process runs executed against it and of the production runs that have been linked to it.

### 3.6. Container Lots and Packaging Supply Quality

Empty containers arrive as lots. A `WarehouseLead` receives a lot by declaring its `container_type` — one of `GLASS_355`, `PET_473`, `PET_1000`, or `CAN_330` — the `quantity_received`, and the supplier's `supplier_lot_code`. The lot is born in `RECEIVED` with its full count available: `quantity_available` equals `quantity_received`, and `quantity_reserved` and `quantity_consumed` are zero.

A `QAInspector` then renders a `verdict` on a `RECEIVED` lot — any other state draws `ERR_CONTAINER_LOT_STATE_INVALID` — moving it to `QC_PASSED` or `QC_FAILED`. Only `QC_PASSED` stock is eligible to be reserved for production (§3.7). A failed lot may be sent back to its supplier by a `WarehouseLead`, but only as a whole: the lot must stand in `QC_FAILED` with `quantity_reserved` and `quantity_consumed` both at zero, else `ERR_CONTAINER_LOT_STATE_INVALID`, whereupon it moves to `RETURNED`. When a run completion consumes the last available units of a passed lot — `quantity_available` reaching zero — the lot flips automatically to `DEPLETED`. Lots can be listed with optional `container_type` and `status` filters, and the conservation invariant of §2.9 holds across every reservation, consumption, and release.

### 3.7. Quoting, Confirming, and Scheduling Production Runs

Bottling lines, like tanks, are plant setup: a `PlantManager` registers each line with a human `line_code`, the `supported_container_types` it can fill, and its `nominal_cpm` nameplate speed, and a new line stands in `ACTIVE`. Taking a line down (`ACTIVE` → `MAINTENANCE`) is refused with `ERR_LINE_STATE_INVALID` while any run on that line stands in `SCHEDULED` or `IN_PRODUCTION`, and only a line in `MAINTENANCE` can be returned to service — any other source state for either transition draws the same `ERR_LINE_STATE_INVALID`. Lines can be listed and inspected individually, and each line exposes a reverse listing of the runs booked on it.

A `ProductionPlanner` quotes a run by naming the `customer_id`, the `formula_id`, the `container_type`, the `planned_units`, and the agreed `unit_price_cents`. The formula must belong to the customer being quoted — its `customer_id` must equal the run's — else the quote is refused with `ERR_FORMULA_CUSTOMER_MISMATCH`. A quoted run stands in `QUOTED` with its invoice dimension in `NOT_INVOICED`.

Confirming the quote (`QUOTED` → `CONFIRMED`) stacks three gates on top of the state check (`ERR_RUN_STATE_INVALID` otherwise): the customer must be `ACTIVE` (else `ERR_CUSTOMER_NOT_ACTIVE`, per §3.1), the formula must stand in `APPROVED` (else `ERR_LABEL_NOT_APPROVED`), and `planned_units` must reach the customer's `minimum_run_units` — a run planned at exactly the minimum is acceptable, while anything smaller is refused with `ERR_MINIMUM_RUN_NOT_MET`.

Scheduling — from `CONFIRMED`, or from `BLOCKED_SUPPLY` when a condemned batch forced a re-plan — is the densest operation in the plant. The request names the `batch_id`, the `line_id`, and a half-open line window from `scheduled_start_at` to `scheduled_end_at`, and it must carry the optimistic-concurrency field of §2.7. The formula must still stand in `APPROVED` (else `ERR_LABEL_NOT_APPROVED`). The batch must stand in `RELEASED` and must belong to the run's formula — a batch of any other state or any other formula is refused with `ERR_BATCH_NOT_RELEASED` — and it must be unlinked, a non-null `linked_run_id` drawing `ERR_BATCH_ALREADY_LINKED`. The line must exist and stand in `ACTIVE` (else `ERR_LINE_STATE_INVALID`; a line in `MAINTENANCE` cannot take bookings), it must list the run's `container_type` among its `supported_container_types` (else `ERR_LINE_UNSUPPORTED_CONTAINER`), and the window's end must be strictly after its start (else `ERR_INVALID_WINDOW`).

The line window itself is checked against every other run booked on the same line in `SCHEDULED` or `IN_PRODUCTION`, under half-open semantics with a directional changeover buffer. The buffer between two consecutive runs is fifteen minutes when both fill the same container type and ninety minutes when they differ, plus a further sixty minutes when the outgoing run's formula carries an allergen group other than `NONE` that differs from the incoming run's allergen group. The surcharge is directional on purpose: washing out of an allergen run costs the hour, but starting an allergen run behind a `NONE` run costs nothing. A new booking conflicts with an existing one unless the newcomer's end plus the newcomer-to-existing changeover lands no later than the existing run's start, or the existing run's end plus the existing-to-newcomer changeover lands no later than the newcomer's start; equality is permitted — the final buffer minute itself is free. A clash is rejected with `ERR_LINE_WINDOW_CONFLICT`.

Container supply is the last scheduling gate, and it is atomic. The pool is the sum of `quantity_available` over all `QC_PASSED` lots of the run's container type; it must cover the planned count inflated by five percent and rounded up to a whole unit, else the schedule is refused with `ERR_CONTAINER_SUPPLY_INSUFFICIENT` and nothing is reserved. On success the reservation walks the passed lots of that type in creation order, oldest first, taking from each the lesser of its availability and the remaining need until the inflated count is fully reserved, updating each lot's counters as it goes. The same five-percent overage ceiling reappears at completion as the upper bound on fill count (§3.8).

A successful scheduling pins `label_version_pinned` to the formula's current `label_version`, computes `theoretical_units` as the whole containers obtainable from the batch — the batch's `processed_liters` converted to milliliters, divided by the formula's `container_fill_ml`, rounded down — sets the batch's `linked_run_id` to the run while leaving the batch itself in `RELEASED`, books the line window, and advances the run's `version` by one. Re-scheduling out of `BLOCKED_SUPPLY` follows the identical path with a fresh batch.

Starting the run (`SCHEDULED` → `IN_PRODUCTION`) checks the state (else `ERR_RUN_STATE_INVALID`), then time and truth: the logical clock must read at or after `scheduled_start_at` and strictly before `scheduled_end_at`, else `ERR_RUN_WINDOW_NOT_ACTIVE`; the pinned label version must still equal the formula's current `label_version` — a label approval in between has bumped it, and the start is refused with `ERR_LABEL_VERSION_STALE`; and the line must still stand in `ACTIVE`, else `ERR_LINE_STATE_INVALID`.

Two involuntary transitions shadow the happy path. When the run's linked batch is condemned, the run drops from `SCHEDULED` to `BLOCKED_SUPPLY`, its container reservations are released, its line window is freed, and the batch link is cleared. When the formula's label review is rejected, the run drops from `CONFIRMED` to `BLOCKED_LABEL`; a later approval restores it to `CONFIRMED` (§3.2). A planner may also cancel outright from `QUOTED`, `CONFIRMED`, `SCHEDULED`, `BLOCKED_SUPPLY`, or `BLOCKED_LABEL` — any other state draws `ERR_RUN_STATE_INVALID` — landing the run terminally in `CANCELLED`. Cancellation compensates in full: container reservations are released, the line window is freed, the batch link is cleared while the batch itself remains `RELEASED`, and nothing is ever invoiced — the invoice dimension stays `NOT_INVOICED`.

### 3.8. Run Completion, Yield Accounting, and Invoicing

Completion is reported by a `ProductionPlanner` for a run standing in `IN_PRODUCTION` (else `ERR_RUN_STATE_INVALID`), supplying the filler's `actual_units_filled`, the measured `avg_fill_ml`, and the `warehouse_zone_id` where the pallets will land; the zone rules themselves live in §3.9. The fill count must be at least one and no more than the smaller of `theoretical_units` and the reserved ceiling — the planned count inflated by five percent and rounded up — else the report is refused with `ERR_FILL_COUNT_EXCEEDS_THEORETICAL`.

Yield accounting then runs in a pinned order. Giveaway — product given away by overfilling — is the excess of `avg_fill_ml` over the formula's `container_fill_ml`, floored at zero when the filler underfills, multiplied by `actual_units_filled` and divided by one thousand to express `giveaway_liters` in liters, rounded to one decimal place half up. Billing is case-floored: `billable_units` is `actual_units_filled` divided by twelve with the remainder discarded — whole cases of twelve — then multiplied back by twelve, and this floor-then-scale order is pinned; summing first and rounding later is not an equivalent computation. The run's `pallet_count` is `actual_units_filled` divided by the pallet density of its container type, rounded up: a pallet holds 2,016 units of `GLASS_355`, 1,440 of `PET_473`, 960 of `PET_1000`, or 2,880 of `CAN_330`.

The provisional invoice is `billable_units` multiplied by `unit_price_cents`, posted into `provisional_invoice_cents` at completion. Completion also creates the finished-goods lot (§3.9), consumes containers off the run's reserved lots in the same oldest-first order in which they were reserved — `actual_units_filled` consumed in total, with the unconsumed reserved balance released back to availability in the same request — moves the batch from `RELEASED` to `CONSUMED` and clears its `linked_run_id`, flips the invoice dimension from `NOT_INVOICED` to `PROVISIONAL`, and adds `provisional_invoice_cents` to the customer's `outstanding_balance_cents`.

Finalization belongs to a `FinanceClerk` and is gated on both dimensions: the run's `production_status` must be `COMPLETED` and its `invoice_status` must be `PROVISIONAL`, else `ERR_RUN_STATE_INVALID`. The final invoice subtracts the giveaway deduction — `giveaway_liters` multiplied by 140 cents per liter, rounded half up to a whole cent — from `provisional_invoice_cents`, and the ledger receives only the delta: `outstanding_balance_cents` moves by the difference between `final_invoice_cents` and `provisional_invoice_cents`. Provisional and final therefore legitimately differ for identical fill data whenever any giveaway was recorded, and the invoice dimension moves to `FINAL`. The two dimensions of a run evolve independently after completion: a run is done producing long before its invoice is final. The run book can be listed with optional `customer_id`, `formula_id`, and `production_status` filters, and each run exposes a reverse listing of the finished-goods lots it produced.

### 3.9. Finished Goods, Shelf-Life Dating, and FEFO Distribution

Warehouse space is structured into zones, each registered by a `PlantManager` with a `zone_code`, a `temperature_class` of `AMBIENT`, `CHILLED`, or `FROZEN`, and a `pallet_capacity`; a new zone starts with `pallets_stored` at zero. The zone named at run completion must suit the product: high-pressure product requires a `CHILLED` zone, pasteurized product may land in `AMBIENT` or `CHILLED`, and `FROZEN` is never acceptable — a mismatch is refused with `ERR_ZONE_TEMPERATURE_MISMATCH`. Capacity is checked inclusively: the zone's current `pallets_stored` plus the incoming run's `pallet_count` must not exceed `pallet_capacity`, with a zone filled exactly to capacity still acceptable, and an overflow refused with `ERR_ZONE_CAPACITY_EXCEEDED`.

Each completion creates one finished-goods lot in `AVAILABLE`, carrying the run's `production_run_id` and, denormalized for lookup, its `formula_id` and `customer_id`, the receiving `warehouse_zone_id`, a server-minted `lot_code` of the form `FG-` followed by the production run's id, `units_total` equal to the run's `actual_units_filled`, and a `production_date` taken as the calendar date of the logical clock at completion. Two expiry dates are computed at creation and stored. The label date, `expiry_label_date`, is the production date plus the formula's `shelf_life_days`. The stability date, `expiry_stability_date`, depends on the process: for `HPP` product it is the production date plus the floor of one and a half times `shelf_life_days`; for `PASTEURIZATION` product it is the production date plus `shelf_life_days` minus seven days. A lot's `units_available` is what remains of `units_total` after `units_allocated` and `units_shipped`, and its `pallet_count` is the uns shipped remainder divided by the container type's pallet density, rounded up; a zone's occupancy (§2.9) counts only lots with units still on site.

Distribution begins when a `CustomerServiceRep` — or a `CustomerContact` acting for its own account (§2.1) — places a shipment order with `customer_id`, `formula_id`, a `channel` of `DIRECT_RETAIL`, `CLUB`, `FOODSERVICE`, or `EXPORT`, a `requested_delivery_date`, and `units_requested`. The formula's owning customer must match the order's customer, else `ERR_FORMULA_CUSTOMER_MISMATCH`. The customer must be `ACTIVE`, else `ERR_CUSTOMER_NOT_ACTIVE`, and the requested delivery date must not precede the current logical date, else `ERR_DELIVERY_DATE_IN_PAST`. The order is born in `PLACED` with a channel-derived `min_shelf_life_days` — thirty days for `DIRECT_RETAIL`, forty-five for `CLUB`, twenty-one for `FOODSERVICE`, and sixty for `EXPORT` — the minimum shelf life the goods must still carry on the requested delivery date.

Allocation is first-expired-first-out, performed by a `WarehouseLead` on an order standing in `PLACED` or `BACKORDERED` (else `ERR_ORDER_STATE_INVALID`), carrying the optimistic-concurrency field of §2.7, and gated on the customer being `ACTIVE` (else `ERR_CUSTOMER_NOT_ACTIVE`). The eligible pool is lots of the same formula and the same customer standing in `AVAILABLE` with `units_available` greater than zero, whose remaining life reaches the delivery date: the calendar days between `requested_delivery_date` and the lot's effective expiry must be at least `min_shelf_life_days`. The effective expiry is channel-dependent — `EXPORT` orders read the lot's `expiry_stability_date`, while every other channel reads `expiry_label_date`. Lots are ranked by that effective expiry ascending, ties broken by lot creation order ascending, and the waterfall takes from each lot the lesser of its availability and the remaining need until the request is covered or the pool runs dry. The taken quantities are recorded in the order's `allocations` as lot-and-units pairs, summed into `allocated_units`, and each lot's `units_allocated` and `units_available` move accordingly. The outcome is binary: the order lands in `ALLOCATED` when `allocated_units` equals `units_requested`, and in `BACKORDERED` otherwise — an empty eligible pool is not an error, merely a fully backordered order. Re-allocating a `BACKORDERED` order keeps its existing allocations and tops them up, the resulting allocation set superseding the prior one, and every allocation advances the order's `version` by one.

An `ALLOCATED` order is picked by a `WarehouseLead` (any other state draws `ERR_ORDER_STATE_INVALID`), moving it to `PICKED`. Shipping, again a `WarehouseLead` action, requires `PICKED` and one last safety sweep: every allocated lot must still stand in `AVAILABLE` — an allocated lot that has since become `EXPIRED`, `RECALLED`, or `DEPLETED` blocks the shipment with `ERR_ORDER_CONTAINS_UNSHIPPABLE_LOT`. A successful ship moves each allocated lot's units out (`units_shipped` up, `units_allocated` down, the lot's pallet count recomputed, and the zone's `pallets_stored` recomputed), moves the order to `SHIPPED`, and posts the pallet escrow described in §3.10. Cancellation by a `WarehouseLead` or `CustomerServiceRep` is available from `PLACED`, `BACKORDERED`, `ALLOCATED`, or `PICKED` (else `ERR_ORDER_STATE_INVALID`), moving the order terminally to `CANCELLED` and releasing every allocation back to its lots' availability; the housekeeping epoch cancels stale orders on its own schedule (§3.10).

Finished lots leave `AVAILABLE` three ways. Shipping the last units flips a lot to `DEPLETED`, at which point it contributes zero to its zone's occupancy. The housekeeping epoch flips a lot to `EXPIRED` when the current logical date reaches `expiry_label_date` — equality expires. And a `QAInspector` may recall a lot standing in `AVAILABLE` or `EXPIRED` (else `ERR_LOT_STATE_INVALID`), moving it to `RECALLED`. Expiry and recall from `AVAILABLE` fire the same de-allocation cascade: allocation entries referencing the lot are stripped from shipment orders standing in `PLACED`, `ALLOCATED`, or `BACKORDERED`, their `allocated_units` recomputed, and any such order whose allocated total now falls short of its `units_requested` is demoted to `BACKORDERED` (this demotion moves orders out of `ALLOCATED`, or out of `PICKED` where applicable). Orders standing in `PICKED` keep their allocations untouched — the shipping gate above, not de-allocation, is what stops them. Lots can be browsed with optional `formula_id`, `customer_id`, and `status` filters, and orders with `customer_id`, `formula_id`, and `status` filters; each warehouse zone exposes a reverse listing of the lots stored in it, and runs and customers expose their own reverse listings as noted in §3.8 and §3.1.

### 3.10. Pallet Escrow and the Housekeeping Epoch

Every customer carries exactly one pallet account, created with the customer itself, tracking the returnable-pallet float through an append-only ledger. Each ledger entry records its `pallet_account_id`, an `entry_type` of `SHIP`, `RETURN`, or `CONVERSION`, a positive `pallet_count`, the originating `shipment_order_id` for `SHIP` entries (absent otherwise), the `entry_date` — the calendar date of the logical clock when the entry posted — and a `running_balance` equal to the account's `pallets_outstanding` immediately after posting. Entries are ordered chronologically by `entry_date` and then by creation order, and running balances follow that order. A customer's pallet account is retrievable directly or through the customer's own reverse lookup, and its entry history is listed chronologically.

Shipping posts the outward leg: a `SHIP` entry carrying the order's `pallet_count` — computed per §3.9 as the per-lot ceilings of each allocation summed together — raises `pallets_out_total` by that count, raises `escrow_balance_cents` by the count times the customer's `pallet_deposit_cents`, and charges the same amount into the customer's `outstanding_balance_cents`. A `WarehouseLead` records physical returns by supplying a `pallet_count`; the count must not exceed the account's `pallets_outstanding`, else `ERR_PALLET_RETURN_EXCEEDS_OUTSTANDING`. A return posts a `RETURN` entry that raises `pallets_returned_total`, and credits both the escrow balance and the customer's outstanding balance by the count times the deposit.

The housekeeping epoch is a `PlantManager` action that runs the plant's periodic sweep and records what it did as an epoch record: the logical timestamp `ran_at`, plus `lots_expired_count`, `orders_backordered_count`, `orders_cancelled_count`, `customers_suspended_count`, and `pallets_converted_count`. Four sweeps run per epoch. The credit sweep suspends every `ACTIVE` customer whose `outstanding_balance_cents` is strictly greater than `credit_limit_cents` — a balance exactly equal to the limit does not suspend. The stale-order sweep cancels every shipment order standing in `PLACED` or `BACKORDERED` whose `requested_delivery_date` lies more than a full calendar week — seven days — in the past; an order exactly seven days stale keeps its place, and cancellation releases its allocations. The expiry sweep flips lots per §3.9, always reading the label date with equality expiring, and fires the de-allocation cascade for each. The pallet-aging sweep walks each account's `SHIP` entries oldest first by `entry_date` and creation order, netting `RETURN` entries against them in first-in-first-out order; any `SHIP` entry with a net outstanding count whose `entry_date` lies at least thirty days before the current logical date — an entry exactly thirty days old converts — posts a `CONVERSION` entry for its net count, raising `pallets_converted_total` and reducing `escrow_balance_cents` by the converted count times the deposit while leaving `pallets_outstanding` untouched: the deposit on converted pallets is forfeited, having already been collected at ship. The conserved identities of §2.9 hold across every one of these postings.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — onboarding a customer, registering a formula, tank, line, or zone, receiving a container lot, planning a batch, scheduling a process run, quoting a run, placing an order, posting a payment or pallet return, submitting a label review, or recording a housekeeping epoch — return `201 Created`. Operations that modify an existing resource in place, including every state transition and the clock-setting capability, return `200 OK`, as do all retrievals. The table below is a summary only; request payloads, response shapes, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Advance the logical clock | PlantManager |
| POST | `/v1/customer-accounts` | Onboard a co-pack customer; auto-creates its pallet account | PlantManager |
| GET | `/v1/customer-accounts` | List customers | Any |
| GET | `/v1/customer-accounts/{id}` | Get one customer | Any |
| POST | `/v1/customer-accounts/{id}/approve-credit` | Approve credit; activate the account | FinanceClerk |
| POST | `/v1/customer-accounts/{id}/suspend` | Place a manual credit hold | FinanceClerk |
| POST | `/v1/customer-accounts/{id}/reactivate` | Reactivate under the eighty-percent threshold gate | FinanceClerk |
| POST | `/v1/customer-accounts/{id}/close` | Close an account with no open work and zero pallet balance | FinanceClerk |
| POST | `/v1/customer-accounts/{id}/payments` | Post a payment against the outstanding balance | FinanceClerk |
| GET | `/v1/customer-accounts/{id}/production-runs` | List the customer's production runs | Any |
| GET | `/v1/customer-accounts/{id}/shipment-orders` | List the customer's shipment orders | Any |
| GET | `/v1/customer-accounts/{id}/pallet-account` | Get the customer's pallet account (array of zero or one) | Any |
| GET | `/v1/pallet-accounts/{id}` | Get one pallet account | Any |
| POST | `/v1/pallet-accounts/{id}/returns` | Record returned returnable pallets | WarehouseLead |
| GET | `/v1/pallet-accounts/{id}/entries` | List the pallet ledger entries chronologically | Any |
| POST | `/v1/formulas` | Register a formula for a customer | ProductDeveloper |
| GET | `/v1/formulas` | List formulas | Any |
| GET | `/v1/formulas/{id}` | Get one formula | Any |
| POST | `/v1/formulas/{id}/submit-label-review` | Submit claims for compliance review; supersedes any pending review | ProductDeveloper |
| POST | `/v1/formulas/{id}/retire` | Retire a formula with no open runs | ProductDeveloper |
| GET | `/v1/formulas/{id}/label-reviews` | List the formula's label reviews | Any |
| GET | `/v1/formulas/{id}/batches` | List batches blended from the formula | Any |
| GET | `/v1/label-reviews/{id}` | Get one label review | Any |
| POST | `/v1/label-reviews/{id}/approve` | Approve claims; bumps the formula's label version | LabelComplianceReviewer |
| POST | `/v1/label-reviews/{id}/reject` | Reject claims; demotes confirmed runs of the formula | LabelComplianceReviewer |
| POST | `/v1/blending-tanks` | Register a blending tank | PlantManager |
| GET | `/v1/blending-tanks` | List tanks | Any |
| GET | `/v1/blending-tanks/{id}` | Get one tank | Any |
| POST | `/v1/blending-tanks/{id}/start-cip` | Begin clean-in-place; stamps start time and required hours | BlendOperator |
| POST | `/v1/blending-tanks/{id}/complete-cip` | Finish clean-in-place after the required duration | BlendOperator |
| GET | `/v1/blending-tanks/{id}/batches` | List batches booked into the tank | Any |
| POST | `/v1/batches` | Plan a blend batch into a tank window | BlendOperator |
| GET | `/v1/batches` | List batches | Any |
| GET | `/v1/batches/{id}` | Get one batch | Any |
| POST | `/v1/batches/{id}/start-blend` | Begin blending | BlendOperator |
| POST | `/v1/batches/{id}/record-blend` | Record the measured brix | BlendOperator |
| POST | `/v1/batches/{id}/qa-verdict` | Render the quality pass/fail verdict | QAInspector |
| POST | `/v1/batches/{id}/apply-adjustment` | Apply the computed brix correction | BlendOperator |
| POST | `/v1/batches/{id}/condemn` | Condemn the batch with the full cascade | QAInspector |
| POST | `/v1/batches/{id}/release` | Release a processed batch for scheduling | QAInspector |
| GET | `/v1/batches/{id}/process-runs` | List the batch's process runs | Any |
| GET | `/v1/batches/{id}/production-runs` | List production runs linked to the batch | Any |
| POST | `/v1/process-runs` | Schedule a pasteurization or HPP run for a passed batch | BlendOperator |
| GET | `/v1/process-runs/{id}` | Get one process run | Any |
| POST | `/v1/process-runs/{id}/start` | Start the run; the batch leaves the tank | BlendOperator |
| POST | `/v1/process-runs/{id}/complete` | Record readings; validate or flag deviation | BlendOperator |
| POST | `/v1/process-runs/{id}/abort` | Abort a scheduled or running process run | BlendOperator |
| POST | `/v1/process-runs/{id}/qa-disposition` | Dispose of a deviated run | QAInspector |
| POST | `/v1/container-lots` | Receive a container lot | WarehouseLead |
| GET | `/v1/container-lots` | List container lots | Any |
| GET | `/v1/container-lots/{id}` | Get one container lot | Any |
| POST | `/v1/container-lots/{id}/qc-verdict` | Render the container quality verdict | QAInspector |
| POST | `/v1/container-lots/{id}/return` | Return a full failed lot to the supplier | WarehouseLead |
| POST | `/v1/bottling-lines` | Register a bottling line | PlantManager |
| GET | `/v1/bottling-lines` | List bottling lines | Any |
| GET | `/v1/bottling-lines/{id}` | Get one bottling line | Any |
| POST | `/v1/bottling-lines/{id}/set-maintenance` | Take a line down for maintenance | PlantManager |
| POST | `/v1/bottling-lines/{id}/set-active` | Return a line to service | PlantManager |
| GET | `/v1/bottling-lines/{id}/production-runs` | List runs booked on the line | Any |
| POST | `/v1/production-runs` | Quote a co-pack production run | ProductionPlanner |
| GET | `/v1/production-runs` | List production runs | Any |
| GET | `/v1/production-runs/{id}` | Get one production run | Any |
| POST | `/v1/production-runs/{id}/confirm` | Confirm a quoted run | ProductionPlanner |
| POST | `/v1/production-runs/{id}/schedule` | Schedule or re-schedule a run: batch, line window, container reservation | ProductionPlanner |
| POST | `/v1/production-runs/{id}/start` | Start a scheduled run inside its window | ProductionPlanner |
| POST | `/v1/production-runs/{id}/complete` | Complete a run; compute yield and post the provisional invoice | ProductionPlanner |
| POST | `/v1/production-runs/{id}/finalize-invoice` | Finalize the invoice; post the giveaway delta | FinanceClerk |
| POST | `/v1/production-runs/{id}/cancel` | Cancel a non-terminal run with full compensation | ProductionPlanner |
| GET | `/v1/production-runs/{id}/finished-good-lots` | List finished lots produced by the run | Any |
| GET | `/v1/finished-good-lots` | List finished-good lots | Any |
| GET | `/v1/finished-good-lots/{id}` | Get one finished-good lot | Any |
| POST | `/v1/finished-good-lots/{id}/recall` | Recall an available or expired lot; de-allocates open orders | QAInspector |
| POST | `/v1/warehouse-zones` | Register a warehouse zone | PlantManager |
| GET | `/v1/warehouse-zones` | List warehouse zones | Any |
| GET | `/v1/warehouse-zones/{id}` | Get one warehouse zone | Any |
| GET | `/v1/warehouse-zones/{id}/finished-good-lots` | List lots stored in the zone | Any |
| POST | `/v1/shipment-orders` | Place a distribution order | CustomerContact, CustomerServiceRep |
| GET | `/v1/shipment-orders` | List shipment orders | Any |
| GET | `/v1/shipment-orders/{id}` | Get one shipment order | Any |
| POST | `/v1/shipment-orders/{id}/allocate` | Allocate or top up eligible lots, first-expired-first-out | WarehouseLead |
| POST | `/v1/shipment-orders/{id}/pick` | Mark an allocated order picked | WarehouseLead |
| POST | `/v1/shipment-orders/{id}/ship` | Ship a picked order; posts pallet escrow | WarehouseLead |
| POST | `/v1/shipment-orders/{id}/cancel` | Cancel an open order; releases allocations | WarehouseLead, CustomerServiceRep |
| POST | `/v1/ops-runs` | Run the housekeeping epoch sweeps | PlantManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined where the guarded workflow is described in §2 and §3; this table is the index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_FORMULA_NOT_FOUND` | 404 Not Found |
| `ERR_LABEL_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_TANK_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_PROCESS_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_CONTAINER_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCTION_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PALLET_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CUSTOMER_STATE_INVALID` | 409 Conflict |
| `ERR_CUSTOMER_NOT_ACTIVE` | 409 Conflict |
| `ERR_FORMULA_STATE_INVALID` | 409 Conflict |
| `ERR_REVIEW_STATE_INVALID` | 409 Conflict |
| `ERR_TANK_STATE_INVALID` | 409 Conflict |
| `ERR_BATCH_STATE_INVALID` | 409 Conflict |
| `ERR_PROCESS_RUN_STATE_INVALID` | 409 Conflict |
| `ERR_PROCESS_RUN_ACTIVE_EXISTS` | 409 Conflict |
| `ERR_CONTAINER_LOT_STATE_INVALID` | 409 Conflict |
| `ERR_LINE_STATE_INVALID` | 409 Conflict |
| `ERR_RUN_STATE_INVALID` | 409 Conflict |
| `ERR_LOT_STATE_INVALID` | 409 Conflict |
| `ERR_ORDER_STATE_INVALID` | 409 Conflict |
| `ERR_LABEL_NOT_APPROVED` | 409 Conflict |
| `ERR_LABEL_VERSION_STALE` | 409 Conflict |
| `ERR_SOD_QA_SELF_APPROVAL` | 403 Forbidden |
| `ERR_SOD_LABEL_SELF_REVIEW` | 403 Forbidden |
| `ERR_PROCESS_NOT_VALIDATED` | 409 Conflict |
| `ERR_BRIX_OUT_OF_TOLERANCE` | 409 Conflict |
| `ERR_BATCH_NOT_RELEASED` | 409 Conflict |
| `ERR_BATCH_ALREADY_LINKED` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_TANK_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BATCH_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_TANK_WINDOW_CONFLICT` | 422 Unprocessable Entity |
| `ERR_LINE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_LINE_UNSUPPORTED_CONTAINER` | 422 Unprocessable Entity |
| `ERR_MINIMUM_RUN_NOT_MET` | 422 Unprocessable Entity |
| `ERR_REBLEND_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_NOTHING_TO_ADJUST` | 409 Conflict |
| `ERR_ADJUSTMENT_EXCEEDS_TANK_CAPACITY` | 422 Unprocessable Entity |
| `ERR_FILL_COUNT_EXCEEDS_THEORETICAL` | 422 Unprocessable Entity |
| `ERR_ZONE_TEMPERATURE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CONTAINER_SUPPLY_INSUFFICIENT` | 409 Conflict |
| `ERR_FORMULA_CUSTOMER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAYMENT_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_CIP_DURATION_INSUFFICIENT` | 409 Conflict |
| `ERR_RUN_WINDOW_NOT_ACTIVE` | 409 Conflict |
| `ERR_DELIVERY_DATE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |
| `ERR_REACTIVATION_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_PALLET_RETURN_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_ORDER_CONTAINS_UNSHIPPABLE_LOT` | 409 Conflict |
