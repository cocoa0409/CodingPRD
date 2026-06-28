# Prepurchase Vehicle Inspection API — Product Requirements Document

## 1. Introduction

Used-vehicle buyers — independent shoppers, franchise dealers, and wholesale auction houses alike — face a recurring problem: the car they are about to pay for may hide mechanical faults, an odometer that has been wound back, or a title quietly branded as salvage, flood, or lemon. This API powers a third-party prepurchase inspection marketplace in the style of Lemon Squad and Carfax, where an ordering account commissions a field inspector to drive out to a vehicle, perform a multi-point inspection and optional road test, photograph defects, and compile a VIN history report drawn from title, odometer, and branding events plus open manufacturer recalls.

The platform coordinates the full fulfillment chain — order intake, location dispatch to a certified inspector, report authoring, buyer delivery, and post-delivery disputes — against two independent concerns that run in parallel: how far along the inspection workflow has progressed, and whether the order has been paid, invoiced under net terms, or refunded. Pricing is sensitive to the inspection tier, optional VIN-history bundling, dispatch distance, and turnaround urgency, with a forward-looking estimate quoted up front and a final charge reconciled at delivery that depends on whether the service-level deadline was met. Because money, vehicle safety, and inspector capacity are all at stake, the system enforces strict ownership, state, scheduling, and fiscal rules at every transition, and records an auditable trail of every report, photo, recall match, and dispute resolution.

This document specifies the system-wide contracts (Section 2) and the business workflows (Section 3), followed by the endpoint catalogue (Section 4) and error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the role under which the request is made. If either header is missing, or `X-User-Role` is not one of the three recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly three roles, spelled precisely as `OpsAdmin`, `AccountHolder`, and `Inspector`.

`OpsAdmin` is the platform operations role: it creates accounts, fee schedules, inspectors, and recall records; offers and releases dispatch assignments; invoices and delivers orders; appends VIN history and compiles VIN reports; adjudicates disputes; and drives the logical clock. When `X-User-Role` is `OpsAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`; ownership checks do not apply to operations performed by an `OpsAdmin`.

`AccountHolder` represents a dealer, auction house, or individual buyer acting as their own `Account`. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's `account_id` to `X-User-ID`. An `AccountHolder` may only create, pay, cancel, and dispute orders belonging to its own account, and may only supply additional information on disputes it filed.

`Inspector` represents a field inspector resource. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`; ownership checks on any resource that references an `Inspector` compare the resource's `inspector_id` to `X-User-ID`. An `Inspector` may only accept or decline assignments offered to itself, and may only author reports against an assignment it holds.

Ownership violations — for example, an `AccountHolder` attempting to cancel another account's order, or an `Inspector` accepting a peer's offered assignment — are rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the start of the result set; it defaults to 0 and has a minimum of 0. A `limit` or `offset` outside its allowed bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 422).

Unless a specific endpoint states otherwise, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order. The `meta` object of a list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, and `version` is an integer that begins at 1 and increments by one on each mutation of the resource. These four common fields are present on `Account`, `FeeSchedule`, `Inspector`, `InspectionOrder`, `DispatchAssignment`, `InspectionReport`, `VinReport`, `RecallRecord`, and `Dispute`.

Three entities are immutable lightweight records and therefore carry only `id` and `created_at`, with no `updated_at` and no `version` field at all: `Vehicle`, `ReportPhoto`, and `VinHistoryRecord`. The implementer must not emit `updated_at` or `version` on these three.

All time-dependent behavior in the system — when an order was placed, whether a delivery is late, the calendar date used for inspector daily caps — is measured against a single server-side **logical clock**, never against wall-clock time. On startup the logical clock reads exactly `2026-04-01T00:00:00Z` and stays there until explicitly moved; before any clock-set call it never falls back to the host's real time. An operator capability advances the clock to a supplied instant via the `to_iso8601` field, and all subsequent timestamp computations read from the moved clock.

### 2.5. Monetary Precision and Rounding

All money in the system is represented as an integer number of cents; there are no fractional-cent values and no floating-point currency fields exposed in responses. Wherever a calculation multiplies cents by a possibly-fractional quantity (such as a per-mile rate times a fractional mileage, or a percentage surcharge), the intermediate product is rounded to a whole number of cents using the round-half-up convention before the next step proceeds. Rounding is applied at each pinned step of a calculation, not deferred to the end; the exact pinned order for each fee calculation is given in Section 3. Risk scores and condition scores follow their own precision rules, stated alongside their formulas.

### 2.6. State Consistency and Cascading Side Effects

An `InspectionOrder` tracks two independent state axes that advance separately: a `workflow_status` describing fulfillment progress (`DRAFT`, `DISPATCHED`, `IN_PROGRESS`, `REPORTED`, `DELIVERED`, `CANCELLED`) and a `payment_status` describing billing (`UNPAID`, `PAID`, `INVOICED`, `REFUNDED`). The two axes do not gate each other except where Section 3 explicitly says so; an order can be paid while still in `DRAFT`, or delivered while invoiced.

Several operations mutate more than one entity in a single request. When that happens, every affected resource has its `updated_at` refreshed and its `version` incremented (for resources that carry those fields), and each cascade described in Section 3 must be applied in full — partial application is never acceptable. The most consequential cascades are: accepting an assignment advancing the order from `DRAFT` to `DISPATCHED`; cancelling a dispatched order releasing its accepted assignment; releasing an accepted assignment reverting a still-dispatched order back to `DRAFT`; and resolving a dispute adjusting the order's refund tally and possibly the account's outstanding balance and the linked report's status. The order's `version` is the anchor for optimistic concurrency (Section 2.7), so every operation listed in Section 3 as bumping the order version must do so.

### 2.7. Optimistic Concurrency on Order Dispatch

Offering a dispatch assignment is guarded by optimistic concurrency control against the target order. A request to create (offer) a `DispatchAssignment` must include `expected_order_version`, a non-optional field carrying the client's last observed `version` of the referenced `InspectionOrder`. If `expected_order_version` does not equal the order's current `version` at the moment the offer is processed, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a second dispatch attempt that was composed against a pre-dispatch view of the order from quietly overwriting work: once one assignment has been accepted it advances the order from `DRAFT` to `DISPATCHED` and bumps the order's `version`, so any offer still carrying the older version number is working from a stale view and is refused. No other endpoint takes a version field; OCC applies only to offering a dispatch assignment.

### 2.8. Nested and Referenced Resource Validation

Resource identifiers may appear both in the URL path and in request bodies as foreign keys. Existence is validated left to right: path parameters are resolved first in the order they appear, then body foreign keys. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any business rule runs. List endpoints support reverse lookup by foreign key: orders may be filtered by `account_id`, `vehicle_id`, or `fee_schedule_id`; assignments by `order_id` or `inspector_id`; reports by `order_id` or `assignment_id`; photos by `report_id`; VIN history records by `vehicle_id`; VIN reports by `order_id` or `vehicle_id`; disputes by `order_id`, `report_id`, or `account_id`; and recall records by `year`, `make`, or `model`.

### 2.9. Validation Ordering

When several checks apply to a single request, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. The order is: (1) authentication of headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`); (3) existence of all referenced resources, path before body (`ERR_NOT_FOUND`); (4) resource ownership for ownership-scoped mutations (`ERR_NOT_RESOURCE_OWNER`); (5) request-body well-formedness — required fields present, enum members valid, numeric ranges satisfied (`ERR_INVALID_REQUEST`); (6) the optimistic-concurrency version check on dispatch-assignment creation (`ERR_STALE_VERSION`); (7) the target resource being in a state from which the requested transition is defined (`ERR_INVALID_STATE`); and then the domain-specific business rules described in Section 3, which sit below these in priority. Among the business rules, account suspension is checked when creating orders or offering dispatch; inspector availability and tier certification are checked when accepting an assignment; the critical-photo requirement is checked at report submission; window and vehicle collision and daily-cap checks are applied at assignment acceptance; report and VIN-report prerequisites are checked at delivery and report creation; and payment and invoice-eligibility are checked at delivery and invoicing. Where a single endpoint carries several business checks, the specific evaluation order is described with that workflow in Section 3.

## 3. Business Logic & Workflows

### 3.1. Accounts, Vehicles, Fee Schedules, and Inspectors

The platform's reference data is set up by operations staff. An account is created with an `account_type` of `DEALER`, `AUCTION`, or `INDIVIDUAL`, a `legal_name`, and a contact `email` that must be unique across active accounts. The optional `net_terms_days` defaults to 0 and represents invoice net terms in days: dealers and auctions may set it above zero to bill on net terms, while individual buyers must keep it at 0 and prepay. An account also carries an optional `rush_discount_pct`, defaulting to 0, which is a negotiated discount on rush surcharges constrained to lie between 0 and 0.50 inclusive; a value outside that band is a malformed request. A new account begins with `status` of `ACTIVE` and an `outstanding_balance_cents` of 0; a `SUSPENDED` account blocks the creation of new orders and any new dispatch. The `outstanding_balance_cents` is a computed running total of the `fee_total_cents` for that account's orders that are currently in `INVOICED` payment status. Suspending an account flips its `status` from `ACTIVE` to `SUSPENDED`.

A vehicle is registered by its `vin` — exactly 17 uppercase alphanumeric characters that exclude the letters I, O, and Q — together with its `year`, `make`, and `model`. The VIN is the immutable identity of the inspected car; a VIN that is not exactly 17 valid characters is a malformed request. Because a vehicle is an immutable record, it carries no `updated_at` or `version`.

Pricing lives on fee schedules. A fee schedule has a `tier_code` of `STANDARD`, `PREMIUM`, or `HEAVY_DUTY`, a `base_fee_cents` base inspection fee, a `vin_history_fee_cents` add-on charged when the VIN-history report is bundled, and a `per_mile_dispatch_cents` travel charge per mile from the inspector's base to the inspection location. The optional `effective` flag defaults to true and marks whether new orders may reference the schedule. When an order is created it pins the fee schedule selected at that moment, so later pricing edits never retroactively change an existing order's quote.

An inspector is created with a `full_name`, a home base given by `base_lat` and `base_lng`, and a `certified_tiers` array — a non-empty subset of `STANDARD`, `PREMIUM`, and `HEAVY_DUTY` naming which inspection tiers the inspector may perform. The optional `max_daily_jobs` defaults to 3 and caps how many accepted assignments the inspector may hold whose appointment window starts on a single UTC calendar date. A new inspector's `status` defaults to `AVAILABLE`; the operator or the inspector can toggle it between `AVAILABLE` and `OFFLINE` by supplying a new `status`, and an `OFFLINE` inspector is not eligible for dispatch.

### 3.2. Placing an Order: Estimated Fee and SLA Deadline

An `AccountHolder` opens an inspection by submitting an order against its own account. The create payload supplies the `account_id`, the `vehicle_id`, the `fee_schedule_id`, the inspection `location_lat` and `location_lng`, an optional `include_vin_history` flag (defaulting to false) indicating whether the VIN-history add-on is purchased, and an optional `rush_tier` (defaulting to `NONE`, otherwise `EXPRESS` or `SAME_DAY`) expressing turnaround urgency. Creation is refused with `ERR_ACCOUNT_SUSPENDED` if the ordering account is not `ACTIVE`. A new order starts with `workflow_status` of `DRAFT` and `payment_status` of `UNPAID`. Its `ordered_at` is stamped from the logical clock at creation, and the system records `dispatch_miles` only later, at dispatch time, so the dispatch component of the fee is treated as zero until then.

At creation the system also computes the service-level deadline. The deadline horizon depends on the rush tier: a `NONE` order allows 120 hours, an `EXPRESS` order allows 48 hours, and a `SAME_DAY` order allows 8 hours. The `sla_deadline` is the `ordered_at` instant plus that many hours. An order is considered late only when the logical clock at delivery is strictly greater than `sla_deadline`; a delivery exactly at the deadline is on time.

The forward-looking quote, `estimated_fee_cents`, is computed at creation assuming the order will be delivered on time. It is built in a pinned order. First, the subtotal is the sum of three components: the base, which is the schedule's `base_fee_cents`; the VIN-history add-on, which is the schedule's `vin_history_fee_cents` when `include_vin_history` is true and otherwise zero; and the dispatch charge, which is the schedule's `per_mile_dispatch_cents` multiplied by the order's `dispatch_miles`, rounded half up to whole cents (this dispatch charge is zero at creation, since miles are not yet known, and is re-quoted at dispatch). Second, the rush surcharge is the subtotal multiplied by the tier's rush percentage — 0 for `NONE`, 0.20 for `EXPRESS`, and 0.50 for `SAME_DAY` — with that product rounded half up to whole cents. Third, the negotiated discount is applied to the rush surcharge alone, never to the base or dispatch: the discounted surcharge is the rush surcharge multiplied by one minus the account's `rush_discount_pct`, again rounded half up to whole cents. The `estimated_fee_cents` is the subtotal plus the discounted rush surcharge.

When the order is later dispatched, the supplied `dispatch_miles` is recorded on the order and the `estimated_fee_cents` is re-quoted by re-running the same three-step computation, now with a non-zero dispatch component.

An `AccountHolder` may cancel its own order only while it is in `DRAFT` or `DISPATCHED` workflow status, transitioning it to `CANCELLED`; attempting to cancel from any other state is rejected as an invalid state transition. Cancelling a `DISPATCHED` order also cascades the order's accepted assignment to `RELEASED`, freeing the inspector's slot. In either case, if the order's `payment_status` was `PAID`, cancellation moves it to `REFUNDED` and sets `refunded_cents` to the full `fee_total_cents` (or the `estimated_fee_cents` if a final fee was never computed); the account's `outstanding_balance_cents` is left untouched on cancellation.

### 3.3. Paying and Invoicing

There are two billing paths, both running on the order's payment axis independently of the workflow axis. The prepaid path, used by individual buyers, is the account paying its own order, moving `payment_status` from `UNPAID` to `PAID`; this is allowed only while the payment status is `UNPAID` and the order is not `CANCELLED` (a cancelled order rejects payment as an invalid state).

The net-terms path is operator-driven invoicing, moving `payment_status` from `UNPAID` to `INVOICED`. Invoicing is permitted only when the account's `net_terms_days` is greater than zero; an attempt to invoice an account with zero net terms is rejected with `ERR_INVOICE_NOT_ELIGIBLE`. Invoicing also requires the order not to be `CANCELLED`. When an order is invoiced, the account's `outstanding_balance_cents` increases by that order's current `estimated_fee_cents`; the balance is later trued up to the final fee at delivery.

### 3.4. Dispatch: Offering and Accepting Assignments

Operations staff dispatch an order by offering a `DispatchAssignment`, supplying the `order_id`, the chosen `inspector_id`, the appointment `window_start` and `window_end`, the pre-computed road `dispatch_miles` from the inspector's base to the location, and the `expected_order_version` for the concurrency check described in Section 2.7. The appointment window is interpreted with `window_start` inclusive and `window_end` exclusive. A new offer begins in `OFFERED` status; creating it records the order's `dispatch_miles`, re-quotes `estimated_fee_cents`, and increments the order's `version`. Offering is also refused with `ERR_ACCOUNT_SUSPENDED` when the order's account is suspended.

An inspector responds to an offer addressed to itself. Declining an `OFFERED` assignment moves it to `DECLINED`, a terminal state, and has no further effect. Accepting an `OFFERED` assignment is the pivotal scheduling event and runs a battery of checks. The acting inspector must be the assignment's `inspector_id`. The inspector's `status` must be `AVAILABLE`, otherwise the acceptance is refused with `ERR_INSPECTOR_OFFLINE`. The order's fee-schedule `tier_code` must appear in the inspector's `certified_tiers`, otherwise the acceptance is refused with `ERR_TIER_NOT_CERTIFIED`. Then two distinct collision checks run with deliberately different interval semantics:

- **Inspector overlap (half-open).** The new window must not overlap the `[window_start, window_end)` window of any other `ACCEPTED` assignment held by the same inspector. Because the interval is half-open, two windows that merely touch at an endpoint — where one window's end equals the next window's start — do not collide. A genuine overlap is rejected with `ERR_WINDOW_OVERLAP`.
- **Vehicle double-booking (closed).** The same vehicle (the order's `vehicle_id`) must not have another `ACCEPTED` assignment whose window collides under closed-interval semantics, where touching endpoints *do* collide — the same car cannot be present at two back-to-back appointments. A collision here is rejected with `ERR_VEHICLE_DOUBLE_BOOKED`.

Finally, the inspector's count of `ACCEPTED` assignments whose `window_start` falls on the same UTC calendar date as the new window must be strictly below `max_daily_jobs`; reaching the cap rejects the acceptance with `ERR_DAILY_CAP_EXCEEDED`. These business checks run after the standard state check that the assignment is still `OFFERED`. When all checks pass, the assignment moves to `ACCEPTED` and cascades the order from `DRAFT` to `DISPATCHED`, incrementing the order's `version`.

An accepted assignment can be released by operations, moving it to `RELEASED` and freeing the inspector's slot for overlap and daily-cap re-eligibility. Release is permitted only while the order is `DISPATCHED` or `CANCELLED`; once the order has progressed to `IN_PROGRESS` the assignment can no longer be released, and the attempt is rejected as an invalid state. When release is invoked directly while the order is still `DISPATCHED`, it also reverts the order's `workflow_status` from `DISPATCHED` back to `DRAFT` and increments the order's `version`. (The same `RELEASED` transition is also reached automatically as the cascade when a dispatched order is cancelled, as described in Section 3.2.)

### 3.5. Authoring the Inspection Report

Once an order is dispatched, the holding inspector authors a report. Creating a report requires that an `ACCEPTED` assignment exists for the order, otherwise the create is rejected with `ERR_NO_ACCEPTED_ASSIGNMENT`. The create payload supplies the `order_id`, the `assignment_id` of the accepting assignment, the `odometer_reading` recorded at inspection, the `points_total` number of checkpoints evaluated, the `points_failed` count of checkpoints that failed (which must be between 0 and `points_total` inclusive, a malformed request otherwise), and an optional `road_test_done` flag defaulting to false. A new report begins with `status` of `DRAFT`, and creating it cascades the order from `DISPATCHED` to `IN_PROGRESS`. There is one report per order.

While a report is in `DRAFT` or `AMENDED`, the inspector attaches photographs to it. Each `ReportPhoto` carries a `caption`, an optional `is_critical` flag defaulting to false that marks whether the photo documents a critical or safety defect, and a stored `url`; the photo references its owning report by `report_id`. Photos are immutable records and carry no `updated_at` or `version`.

Submitting the report computes its score and outcome and advances the workflow. Submission is allowed from `DRAFT` or from `AMENDED`. It first requires `points_total` to be at least 1, otherwise it is refused with `ERR_EMPTY_REPORT`. The `condition_score` is computed on a 0-to-100 scale from several interacting inputs. The pass ratio is the number of passing checkpoints — `points_total` minus `points_failed` — divided by `points_total`, and the raw score is that ratio times 100. A road-test bonus of 5 points is added when `road_test_done` is true and 0 otherwise. The critical-photo count is the number of this report's photos whose `is_critical` is true; each critical defect floors the score harder than a plain failed checkpoint, so the critical penalty is 15 points per critical photo, capped at 40 points. The `condition_score` is the raw score plus the road-test bonus minus the critical penalty, then clamped to lie between 0 and 100, and rounded half up to two decimal places. The `outcome` is then derived from the rounded score and the critical count: if there is at least one critical photo, or the score is below 50, the outcome is `FAIL`; otherwise, if the score is below 80, the outcome is `CONDITIONAL`; otherwise the outcome is `PASS`. A score of exactly 50 is not a fail, and a score of exactly 80 is a pass.

Because a `FAIL` outcome is consequential, submission of a report whose computed outcome would be `FAIL` is refused with `ERR_CRITICAL_PHOTO_REQUIRED` unless at least one critical photo is attached. On a successful submission the report moves to `SUBMITTED` and the order cascades from `IN_PROGRESS` to `REPORTED`.

Before the order is delivered, the inspector may reopen a submitted report for correction. Amending a `SUBMITTED` report moves it to `AMENDED`, cascades the order from `REPORTED` back to `IN_PROGRESS`, and re-opens authoring; the amend payload may revise `odometer_reading`, `points_total`, `points_failed`, and `road_test_done`. A fresh submission from `AMENDED` recomputes `condition_score` and `outcome` from the amended values and returns the report to `SUBMITTED` and the order to `REPORTED`, subject to the same empty-report and critical-photo gates. A report may not be amended once the order is `DELIVERED`, except through dispute resolution; an amend attempt after delivery is rejected with `ERR_REPORT_LOCKED`.

### 3.6. Compiling VIN History and Recalls

VIN history is a chronology of events attached to a vehicle, appended by operations staff. Each `VinHistoryRecord` has a `record_type` of `TITLE`, `ODOMETER`, or `BRANDING`, an `event_date` used for chronological ordering, an optional `odometer_value` (defaulting to 0, the mileage on `ODOMETER` records and 0 for the rest), an optional `branding_code` (defaulting to `NONE`, otherwise `SALVAGE`, `FLOOD`, `LEMON`, or `REBUILT`, used on `BRANDING` records), and an optional `title_state` issuing-state code (defaulting to an empty string, used on `TITLE` records). The record references its subject vehicle by `vehicle_id`. These records are immutable and carry no `updated_at` or `version`.

Manufacturer recalls are tracked separately. A `RecallRecord` carries a `campaign_id`, the affected `year`, `make`, and `model`, and a `severity` of `LOW`, `MEDIUM`, or `HIGH`. A new recall begins with `status` of `OPEN`; closing it moves the `status` to `CLOSED`, which excludes it from future open-recall counts. Recall lookup lists records filtered by `year`, `make`, and `model`.

Compiling a `VinReport` against an order is an operator action that snapshots the vehicle's history into a single risk assessment; the compile payload supplies the `order_id`, and the report records the subject `vehicle_id`. A compiled report's `status` is `COMPILED`, which is terminal once generated. Compilation derives several fields:

- **`title_count`** is the number of `TITLE` records for the vehicle, standing in for the number of prior owners or title transfers.
- **`worst_branding`** is the most severe `branding_code` across the vehicle's `BRANDING` records, taken by a severity rank where `NONE` ranks 0, `REBUILT` 1, `FLOOD` 2, `SALVAGE` 3, and `LEMON` 4. With no `BRANDING` records the worst branding is `NONE`.
- **`open_recall_count`** is the number of `RecallRecord` rows still `OPEN` at compile time whose `year`, `make`, and `model` match the vehicle.
- **`odometer_rollback`** is determined by replaying the vehicle's `ODOMETER` records in ascending `event_date` order, breaking ties by ascending `created_at`. Walking the records in that order while tracking the running maximum reading seen so far, the flag is set to true if any later reading is lower than the running maximum by more than a tolerance of 100 miles. The comparison is strict: a reading must be more than 100 miles below the running maximum to flag a rollback, so a reading exactly 100 miles below does not flag. After each record the running maximum is updated to the larger of itself and the current reading.

The `risk_score` is then a 0-to-100 title-history risk computed in a pinned order, clamped last. The branding points come from the worst branding: `NONE` contributes 0, `REBUILT` 25, `FLOOD` 40, `SALVAGE` 55, and `LEMON` 70. The owner-churn points are the `title_count` capped at 5, multiplied by 6. The rollback points are 30 when `odometer_rollback` is true and 0 otherwise. The recall points are the `open_recall_count` capped at 3, multiplied by 5. The `risk_score` is the sum of branding, owner-churn, rollback, and recall points, with the total capped at 100.

### 3.7. Delivery and Final Fee Reconciliation

Delivering the report to the buyer is an operator action and the moment the final fee is settled. Delivery requires the order to be in `REPORTED` workflow status. It requires the order's `payment_status` to be either `PAID` or `INVOICED`, otherwise it is refused with `ERR_PAYMENT_REQUIRED`. If the order was placed with `include_vin_history` set to true, a compiled `VinReport` must exist for the order, otherwise delivery is refused with `ERR_VIN_REPORT_MISSING`. (Delivery's dependence on a submitted report and an accepted assignment is implied by reaching `REPORTED`, which is unreachable without them; an attempt to progress without the necessary accepted assignment surfaces as `ERR_NO_ACCEPTED_ASSIGNMENT`.)

On delivery the order moves to `DELIVERED`, the `late_delivery` flag is set to true when the logical clock at delivery is strictly past the `sla_deadline` and false otherwise, and `fee_total_cents` is finalized. The final fee re-runs the same pinned subtotal-and-surcharge computation used for the estimate — base plus VIN add-on plus rounded dispatch charge to form the subtotal, then the rounded tiered rush surcharge, then the rounded discounted surcharge — and then applies the on-time-versus-late adjustment. When the delivery is on time, `fee_total_cents` equals the subtotal plus the discounted rush surcharge, which matches `estimated_fee_cents`. When the delivery is late, the entire rush surcharge is credited back because the customer paid for speed that was not delivered, so `fee_total_cents` equals the subtotal alone — strictly less than the estimate whenever the rush tier is not `NONE`. If the order's payment status is `INVOICED`, the account's `outstanding_balance_cents` is adjusted by the difference between the final fee and the previously booked estimated fee, so a late credit reduces the account's outstanding balance accordingly.

### 3.8. Buyer Disputes and Compensation

After delivery, an `AccountHolder` may dispute the inspection on its own order. Filing a dispute supplies the `order_id`, the `report_id` under dispute, a `reason` of `MISSED_DEFECT`, `LATE_DELIVERY`, or `WRONG_VEHICLE`, and the `claimed_cents` amount the filer believes should be refunded; the dispute records the filing `account_id` as the acting account, which must own the order. A dispute may be filed only against a `DELIVERED` order, otherwise the filing is rejected as an invalid state. A new dispute begins in `OPEN` status.

Disputes move through a cyclic review managed by operations. Starting review moves an `OPEN` dispute to `UNDER_REVIEW`. From `UNDER_REVIEW`, operations may request additional information, moving it to `NEEDS_INFO`. The filing account then supplies the requested information, moving a `NEEDS_INFO` dispute back to `OPEN` for another review round; only the dispute's own filing account may supply this information, and a violation is rejected with `ERR_NOT_RESOURCE_OWNER`. From `UNDER_REVIEW`, operations either resolve or reject the dispute. Rejecting moves it to the terminal `REJECTED` state, leaves `approved_cents` at 0, and issues no refund.

Resolving a dispute is permitted only from `UNDER_REVIEW` and only while the underlying order is `DELIVERED`, otherwise it is refused as an invalid state; a successful resolution moves the dispute to the terminal `RESOLVED` state. Resolution computes `approved_cents` in a pinned order that resolves an otherwise circular-looking dependency. First the system reads the order's already-finalized `fee_total_cents`. Then it notes the order's accumulated `refunded_cents` from any prior resolved disputes. The refundable ceiling is the `fee_total_cents` minus the already-refunded amount, never below 0. The reason cap depends on the dispute reason: for `MISSED_DEFECT` it is the floor of half the `fee_total_cents`; for `LATE_DELIVERY` it is the rush surcharge that was actually billed (which is 0 when the order was already late-credited, since no surcharge was charged); and for `WRONG_VEHICLE` it is the full `fee_total_cents`. The `approved_cents` is the smallest of the `claimed_cents`, the reason cap, and the refundable ceiling, and is never negative.

Resolution then cascades. The order's `refunded_cents` increases by the `approved_cents`. If the order's `payment_status` was `PAID` and the approved amount is greater than 0, the payment status moves to `REFUNDED`; if the order was `INVOICED`, the account's `outstanding_balance_cents` is reduced by the approved amount. Separately, when the reason is `MISSED_DEFECT`, the linked report is flagged for re-authoring by moving its `status` from `SUBMITTED` to `AMENDED`, while the order remains `DELIVERED`. The refundable ceiling guarantees that cumulative refunds across multiple resolved disputes can never exceed the order's `fee_total_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and the logical-clock control — return `200 OK`. All request and response bodies follow the envelope in Section 2.2; the request payloads, side effects, and computed outputs for each endpoint are described in the Section 3 workflows rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create an account | OpsAdmin |
| GET | `/accounts/{accountId}` | Get an account (includes computed balance) | OpsAdmin, AccountHolder |
| POST | `/accounts/{accountId}/suspend` | Suspend an account | OpsAdmin |
| GET | `/accounts/{accountId}/orders` | List an account's inspection orders | OpsAdmin, AccountHolder |
| POST | `/vehicles` | Register a vehicle by VIN | OpsAdmin, AccountHolder |
| GET | `/vehicles/{vehicleId}` | Get a vehicle | OpsAdmin, AccountHolder |
| POST | `/fee-schedules` | Create a fee-schedule pricing tier | OpsAdmin |
| GET | `/fee-schedules/{feeScheduleId}` | Get a fee schedule | OpsAdmin, AccountHolder |
| POST | `/inspectors` | Create an inspector | OpsAdmin |
| GET | `/inspectors/{inspectorId}` | Get an inspector | OpsAdmin, Inspector |
| POST | `/inspectors/{inspectorId}/set-status` | Set inspector availability | OpsAdmin, Inspector |
| GET | `/inspectors/{inspectorId}/assignments` | List an inspector's assignments | OpsAdmin, Inspector |
| POST | `/inspection-orders` | Create an inspection order | AccountHolder |
| GET | `/inspection-orders/{orderId}` | Get an inspection order | OpsAdmin, AccountHolder |
| GET | `/inspection-orders` | List/filter inspection orders | OpsAdmin, AccountHolder |
| POST | `/inspection-orders/{orderId}/pay` | Prepay an order | AccountHolder |
| POST | `/inspection-orders/{orderId}/invoice` | Invoice an order on net terms | OpsAdmin |
| POST | `/inspection-orders/{orderId}/deliver` | Deliver the report; finalize fee | OpsAdmin |
| POST | `/inspection-orders/{orderId}/cancel` | Cancel an order | AccountHolder |
| POST | `/dispatch-assignments` | Offer a dispatch assignment (OCC-guarded) | OpsAdmin |
| GET | `/dispatch-assignments/{assignmentId}` | Get a dispatch assignment | OpsAdmin, Inspector |
| GET | `/dispatch-assignments` | List/filter dispatch assignments | OpsAdmin, AccountHolder, Inspector |
| POST | `/dispatch-assignments/{assignmentId}/accept` | Accept an offered assignment | Inspector |
| POST | `/dispatch-assignments/{assignmentId}/decline` | Decline an offered assignment | Inspector |
| POST | `/dispatch-assignments/{assignmentId}/release` | Release an accepted assignment | OpsAdmin |
| POST | `/inspection-reports` | Create a draft inspection report | Inspector |
| GET | `/inspection-reports/{reportId}` | Get an inspection report | OpsAdmin, AccountHolder, Inspector |
| GET | `/inspection-reports` | List/filter inspection reports | OpsAdmin, AccountHolder, Inspector |
| POST | `/inspection-reports/{reportId}/photos` | Attach a photo to a report | Inspector |
| GET | `/report-photos/{photoId}` | Get a single report photo | OpsAdmin, AccountHolder, Inspector |
| GET | `/report-photos` | List/filter report photos | OpsAdmin, AccountHolder, Inspector |
| POST | `/inspection-reports/{reportId}/submit` | Submit a report; compute score & outcome | Inspector |
| POST | `/inspection-reports/{reportId}/amend` | Amend a submitted report (pre-delivery) | Inspector |
| POST | `/vehicles/{vehicleId}/history-records` | Append a VIN history record | OpsAdmin |
| GET | `/vin-history-records/{recordId}` | Get a single VIN history record | OpsAdmin, AccountHolder |
| GET | `/vin-history-records` | List/filter VIN history records | OpsAdmin, AccountHolder |
| POST | `/vin-reports` | Compile a VIN report for an order | OpsAdmin |
| GET | `/vin-reports/{vinReportId}` | Get a compiled VIN report | OpsAdmin, AccountHolder |
| GET | `/vin-reports` | List/filter VIN reports | OpsAdmin, AccountHolder |
| POST | `/recall-records` | Create a recall campaign record | OpsAdmin |
| POST | `/recall-records/{recallRecordId}/close` | Close a recall campaign | OpsAdmin |
| GET | `/recall-records` | List recall records (recall lookup) | OpsAdmin, AccountHolder |
| POST | `/disputes` | File a dispute on a delivered order | AccountHolder |
| GET | `/disputes/{disputeId}` | Get a dispute | OpsAdmin, AccountHolder |
| GET | `/disputes` | List/filter disputes | OpsAdmin, AccountHolder |
| POST | `/disputes/{disputeId}/start-review` | Move a dispute to under review | OpsAdmin |
| POST | `/disputes/{disputeId}/request-info` | Request more dispute info | OpsAdmin |
| POST | `/disputes/{disputeId}/supply-info` | Supply requested dispute info | AccountHolder |
| POST | `/disputes/{disputeId}/resolve` | Resolve a dispute; compute refund | OpsAdmin |
| POST | `/disputes/{disputeId}/reject` | Reject a dispute (no refund) | OpsAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_INSPECTOR_OFFLINE` | 409 |
| `ERR_TIER_NOT_CERTIFIED` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_VEHICLE_DOUBLE_BOOKED` | 409 |
| `ERR_DAILY_CAP_EXCEEDED` | 409 |
| `ERR_NO_ACCEPTED_ASSIGNMENT` | 409 |
| `ERR_EMPTY_REPORT` | 409 |
| `ERR_CRITICAL_PHOTO_REQUIRED` | 409 |
| `ERR_REPORT_LOCKED` | 409 |
| `ERR_PAYMENT_REQUIRED` | 409 |
| `ERR_INVOICE_NOT_ELIGIBLE` | 409 |
| `ERR_VIN_REPORT_MISSING` | 409 |
| `ERR_PAGINATION_INVALID` | 422 |
