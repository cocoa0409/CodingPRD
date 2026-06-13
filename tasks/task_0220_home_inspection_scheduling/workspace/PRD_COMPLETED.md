# Home Inspection Scheduling API — Product Requirements Document

## 1. Introduction

Real-estate transactions live and die on the home inspection. A buyer needs to know what they are walking into, a seller wants a clean bill of health before listing, and a four-point or wind-mitigation report can decide whether a property is insurable at all. This API is the operational backbone for an inspection company that has to juggle all of these inspection types against a finite roster of certified inspectors, geographic territories, day-by-day capacity, and a pricing book that changes every quarter. It coordinates the full arc of an order: a client or agent requests an inspection, a dispatcher schedules it against the right inspector at the right time and place, the inspector performs the on-site work and authors a defect report, the report is reviewed and graded, and the finished product is delivered to the people who paid for it.

The hard parts of this domain are temporal and financial. Two appointments must never collide for the same inspector once travel time between properties is accounted for, an inspector cannot be booked past their daily on-site limit, and the same property cannot be visited twice in one day. Fees are quoted up front from recorded square footage and then trued up against what the inspector actually measures on site, which means every order carries two distinct fee figures and a running balance. When an inspection turns up serious defects, the company offers a discounted re-inspection — but only once per delivered order, which forces a concurrency discipline so that a stale request cannot spawn a duplicate. This document specifies every entity, state transition, calculation, and validation needed to implement that system faithfully.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly four roles: `Scheduler`, `Inspector`, `Client`, and `Agent`. A request that omits either header, or that presents an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to invoke the targeted endpoint is rejected with `ERR_FORBIDDEN`.

The `Scheduler` is an operational dispatcher role. When `X-User-Role` is `Scheduler`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and act on it but does not compare it to any entity's `id`. The other three roles are entity-backed. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`, and ownership checks on any resource that references an inspector compare that resource's inspector foreign key to `X-User-ID`; this is how the system enforces that only the order's assigned inspector may start it, author its report, log a defect on that report, submit, or revise. An inspector who is authenticated and otherwise permitted but is not the assigned inspector of the targeted order — on the start, report, defect-logging, submit, or revise operations — is rejected with `ERR_NOT_ASSIGNED_INSPECTOR`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`, and when `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent`; for both, ownership checks on a resource that references a client or agent compare the resource's corresponding foreign key to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1 and no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0. A `limit` or `offset` outside its permitted bounds, or a malformed date query parameter where one is accepted, is rejected with `ERR_VALIDATION_RANGE`.

Unless an endpoint states otherwise, list results are returned sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every resource carries a server-minted `id` formatted as a UUID with no type prefix; the `id` is identity only and is never supplied by the client. Most resources also carry three further system-managed fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that begins at 1 and increments by one on every mutation of the resource.

Two entities are deliberately leaner. A `Client` and an `Agent` carry only an `id` and a `created_at` — they have no `updated_at` and no `version`, because once created they are not mutated through any state machine. Every other entity (`Territory`, `FeeSchedule`, `Inspector`, `Property`, `InspectionOrder`, `AddOn`, `Report`, `Defect`, `Delivery`) carries the full `id`/`created_at`/`updated_at`/`version` quartet.

### 2.5. Hierarchical Consistency and Cascades

Several operations mutate more than one resource at once, and the system keeps these cascades internally consistent. Whenever a child resource is created, removed, or transitioned in a way that affects its parent's derived fields, the parent is itself mutated — its `updated_at` is refreshed and its `version` is incremented — so that the parent always reflects the live state of its children. The specific cascades (an order's cancellation voiding its report and that report's defects, a delivery snapshotting a report's grade, an add-on changing an order's duration and fee) are described in §3 alongside the workflows that trigger them. Each distinct entity mutation independently bumps that entity's own `version`.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many paths name a parent resource before a child — for example, the defects of a report or the add-ons of an order. The system validates the existence of every path identifier left to right, and of every foreign key in a request body after the path identifiers. The first identifier that does not resolve to an existing resource causes the request to fail with `ERR_NOT_FOUND` before any later identifier or any business rule is evaluated. This ordering holds for reads, creates, and state transitions alike: the parent's existence is always confirmed before the child is looked up.

### 2.7. Monetary Amounts, Durations, and Rounding

All money in this system is expressed in integer cents — there are no fractional cents and no floating-point currency fields. Fee components are computed as described in §3; the only place rounding occurs in the fee calculation is at the inspection-type-multiplier step, where the running amount is rounded half up to a whole number of cents. Add-on prices are already whole cents and are added without any further rounding. The re-inspection discount likewise rounds half up to whole cents after the discount fraction is applied. Defect risk scores are integers, and rounding within that calculation is applied half up to an integer once per defect before the per-defect figures are summed. All durations are integer minutes, and all daily-load aggregates are integer minutes.

### 2.8. Optimistic Concurrency Control on Re-inspection

Spawning a re-inspection against a delivered order is the one operation in the system guarded by optimistic concurrency. The re-inspection request must carry `expected_order_version` as a required input field, holding the `version` of the parent `InspectionOrder` that the client last observed. If `expected_order_version` does not equal the parent order's current `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. This matters because a successful re-inspection itself bumps the parent order's `version` to record that a child was spawned: a first re-inspection call legitimately creates the child and advances the parent, while a second call that still carries the pre-spawn `version` is detected as stale and rejected, preventing a duplicate re-inspection for the same delivered order. No other endpoint accepts or requires a version field; OCC applies only to re-inspection.

### 2.9. Fiscal Conservation

Each order maintains its own small ledger of money. The outstanding balance on an order, `amount_due_cents`, is always the order's effective fee minus what has been paid plus what has been refunded, where the effective fee depends on the order's lifecycle stage (detailed in §3.6). When an order is cancelled, every cent recorded as paid is refunded, so the cumulative refunded total equals the cumulative paid total and the net collected on a cancelled order is zero. Money is neither created nor destroyed by any transition.

## 3. Business Logic & Workflows

### 3.1. Configuration: Territories, Fee Schedules, and Inspectors

Before any inspection can be booked, a `Scheduler` lays down the operating configuration. A **Territory** is a named service area defined by a `name` and a `zip_codes` array of five-digit ZIP strings; each ZIP belongs to exactly one territory. A territory also carries a `travel_buffer_minutes` value — the gap of travel time inserted after each appointment in that territory before the next one there may begin — which defaults to 30 minutes and must lie between 0 and 240 inclusive. A territory is created in an active service state.

Pricing lives in a **FeeSchedule**, a versioned price book identified by a human `label` such as a quarter name. A fee schedule pins a flat `base_rate_cents` applied to every order (at least 0), three marginal per-square-foot rates `tier1_rate_cents_per_sqft`, `tier2_rate_cents_per_sqft`, and `tier3_rate_cents_per_sqft` (each at least 0), and the two tier boundaries `tier1_max_sqft` and `tier2_max_sqft`. The first boundary defaults to 2000 and must be greater than 0; the second defaults to 4000 and must be strictly greater than `tier1_max_sqft`. The schedule also fixes the three add-on prices `addon_radon_cents`, `addon_termite_cents`, and `addon_sewer_cents` (each at least 0), and a `reinspection_discount_pct` — the base fraction of a re-inspection's recomputed fee that is waived — expressed as a value at least 0 and at most 1 and defaulting to 0.5. A fee schedule is created in `DRAFT` and carries a `status` of `DRAFT` or `PUBLISHED`. Publishing it moves `status` from `DRAFT` to `PUBLISHED`; publishing a schedule that is not in `DRAFT` is rejected with `ERR_INVALID_STATE`. Only a `PUBLISHED` schedule may be pinned to a new order; an order that references a non-`PUBLISHED` schedule is rejected with `ERR_INVALID_REQUEST`.

An **Inspector** is a field professional with a `full_name`, a single `territory_id` naming the one territory they serve, and a `certifications` array drawn from the inspection types `BUYER`, `SELLER`, `FOUR_POINT`, and `WIND_MIT` listing which kinds of inspection they are qualified to perform. Each inspector has a `daily_capacity_minutes` ceiling on bookable on-site minutes per calendar day, defaulting to 480 and required to be greater than 0. An inspector's `status` is `ACTIVE` or `SUSPENDED`, beginning `ACTIVE`; suspending an inspector moves `status` from `ACTIVE` to `SUSPENDED`, after which they cannot be newly booked, and suspending an inspector who is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. A `Scheduler` may read any inspector's booked minutes for a given calendar `date` through a daily-load capability that returns the inspector's `inspector_id`, the `date`, the `booked_minutes` on that date, and the `daily_capacity_minutes` ceiling. The `date` is supplied as a required query parameter in `YYYY-MM-DD` form; a missing or malformed `date` is rejected with `ERR_VALIDATION_RANGE`.

### 3.2. The Parties and the Property

Two kinds of human counterparty participate in a deal. A **Client** is the buyer or seller who orders the inspection and receives the finished report; a client carries a `full_name`, an `email` used on delivery records, and a `role_in_deal` of either `BUYER` or `SELLER`. An **Agent** is the real-estate agent on the deal who may also order and pay and who likewise receives the report; an agent carries a `full_name`, an `email` used on delivery records, and a `brokerage` name.

A **Property** is the dwelling under inspection. It records an `address_line`, a `zip_code` of five digits, a `square_footage` of recorded living area (greater than 0) that drives fee tiering, and a `year_built` between 1850 and 2100 inclusive that gates four-point eligibility. A property's `zip_code` is expected to fall inside some active territory's served ZIP list. Properties may be created by a `Scheduler`, a `Client`, or an `Agent`.

### 3.3. Ordering and Scheduling an Inspection

A new inspection begins when a `Scheduler`, `Client`, or `Agent` places a primary order. The create payload names the `property_id` to be inspected, the ordering `client_id`, the `agent_id` who is the delivery recipient on the deal, the `fee_schedule_id` of the `PUBLISHED` schedule to pin, and the `inspection_type`, which is one of `BUYER`, `SELLER`, `FOUR_POINT`, or `WIND_MIT`. The order is born in `REQUESTED` status with `order_kind` of `PRIMARY`, no assigned inspector, `amount_paid_cents` and `amount_refunded_cents` both at 0, and `version` at 1. Its `status` field moves through `REQUESTED`, `SCHEDULED`, `IN_PROGRESS`, `REPORT_DRAFT`, `DELIVERED`, and `CANCELLED`, of which `DELIVERED` and `CANCELLED` are terminal. The `parent_order_id` field is null on a primary order.

Scheduling is the act of binding a `REQUESTED` order to an inspector and a start time, performed by a `Scheduler` who supplies the `inspector_id` and the `scheduled_start` (an ISO 8601 UTC instant). This transition takes the order from `REQUESTED` to `SCHEDULED` and is heavily guarded; the checks below are evaluated in their listed priority order, with authentication, authorization, and existence of all path and body references already confirmed first (§2.1, §2.6). The order must currently be in `REQUESTED` status, or the request fails with `ERR_INVALID_STATE`. The chosen inspector must exist and be `ACTIVE` — a `SUSPENDED` inspector cannot be booked, and an attempt to schedule against a `SUSPENDED` inspector is rejected with `ERR_INVALID_STATE`. The inspector must be certified for the order's `inspection_type` (the type must appear in their `certifications`), and if the type is `FOUR_POINT`, the property's `year_built` must be no later than 2000; a failure of either certification or four-point eligibility raises `ERR_INSPECTOR_NOT_CERTIFIED`. The property's `zip_code` must lie inside the assigned inspector's territory ZIP list, or the request fails with `ERR_TERRITORY_MISMATCH`. The `scheduled_start` must not collide with another of that inspector's appointments once the territory travel buffer is applied as a half-open overlap window, or the request fails with `ERR_INSPECTOR_DOUBLE_BOOKED`; the appointments considered are that inspector's other orders that are `SCHEDULED`, `IN_PROGRESS`, `REPORT_DRAFT`, or `DELIVERED` and carry a non-null `scheduled_start`. No other non-terminal order for the same `property_id` may share the calendar date being booked, or the request fails with `ERR_PROPERTY_SAME_DAY_CONFLICT`. Finally, adding this order's on-site minutes to the inspector's already-booked minutes for that calendar date must not exceed their `daily_capacity_minutes`, or the request fails with `ERR_DAILY_CAPACITY_EXCEEDED`. Relative to one another these business checks run in the order: inspector-not-certified (and four-point eligibility), then territory match, then double-booking, then same-day property conflict, then daily-capacity.

When scheduling succeeds, the system assigns the `inspector_id` and `scheduled_start`, derives the `scheduled_date` as the YYYY-MM-DD UTC calendar date of `scheduled_start`, and computes the order's `duration_minutes` and quoted fee. It debits the inspector's daily scheduled-minutes ledger for `scheduled_date` by the order's `duration_minutes`, sets `quoted_fee_cents` from the property's recorded square footage, recomputes `amount_due_cents`, and increments the order's `version` by one. A `Scheduler` may reverse a booking: unscheduling a `SCHEDULED` order returns it to `REQUESTED` (an order that is not `SCHEDULED` is rejected with `ERR_INVALID_STATE`), clears `inspector_id`, `scheduled_start`, `scheduled_date`, and `quoted_fee_cents`, and credits that inspector's daily ledger for the prior `scheduled_date` by the same `duration_minutes` so net daily load is unchanged, then increments the order's `version`.

### 3.4. Add-ons, Duration, and Capacity Accounting

A `Scheduler`, `Client`, or `Agent` may attach optional services to an order that has not yet started. An **AddOn** is created with only a `kind` of `RADON`, `TERMITE`, or `SEWER`; on creation the system stamps it with the matching `order_id`, pins its `price_cents` from the order's pinned fee schedule (the `addon_radon_cents`, `addon_termite_cents`, or `addon_sewer_cents` value), and sets its `added_duration_minutes` from the fixed table where RADON contributes 30 minutes, TERMITE 20 minutes, and SEWER 45 minutes. An add-on begins with a `status` of `ACTIVE` and may later become `REMOVED`; a `REMOVED` add-on stops contributing to both fee and duration. Each add-on `kind` may appear at most once per order counting only `ACTIVE` add-ons (a `REMOVED` add-on of the same kind does not block re-adding that kind), and the order must still be `REQUESTED` or `SCHEDULED` (not yet started); a duplicate kind or an already-started order is rejected with `ERR_DUPLICATE_ADDON`, with the order-state check evaluated before the duplicate-kind check.

An order's `duration_minutes` is the sum of a base value keyed on `inspection_type` — 180 minutes for `BUYER`, 150 for `SELLER`, 90 for `FOUR_POINT`, and 60 for `WIND_MIT` — plus the `added_duration_minutes` of every `ACTIVE` add-on on the order. Creating an add-on recomputes the order's `duration_minutes`, and if the order is already `SCHEDULED`, recomputes its `quoted_fee_cents`; the order's `version` is incremented. Removing an add-on (only permitted while the owning order is `REQUESTED` or `SCHEDULED`, i.e. not yet started; removal against an already-started order is rejected with `ERR_INVALID_STATE`) moves the add-on's `status` from `ACTIVE` to `REMOVED` — an add-on that is not `ACTIVE` is itself rejected with `ERR_INVALID_STATE`, and the order-state check is evaluated before the add-on-state check — recomputes the order's `duration_minutes` and, if `SCHEDULED`, its `quoted_fee_cents`, and increments the order's `version`.

The inspector's per-day capacity is tracked as a ledger of booked minutes. For a given inspector and calendar date, booked minutes are the sum of the `duration_minutes` of every one of that inspector's orders whose `scheduled_date` equals the date and whose `status` is one of `SCHEDULED`, `IN_PROGRESS`, `REPORT_DRAFT`, or `DELIVERED`. Scheduling and re-inspection debit this figure; unscheduling and cancellation credit back the same `duration_minutes` for the same date, so the ledger never drifts. The capacity guard at schedule time requires that the booked minutes after adding the new order remain no greater than the inspector's `daily_capacity_minutes`.

### 3.5. Payment, Delivery, and the Order Balance

An order accumulates money through a payment capability open to a `Scheduler`, `Client`, or `Agent`. Recording a payment supplies an `amount_cents` (a required integer of at least 0), which is added to the order's `amount_paid_cents`; the order's `amount_due_cents` is then recomputed and the order's `version` incremented. The effective fee that drives `amount_due_cents` depends on the order's lifecycle stage: it is 0 while the order is `REQUESTED`, the `quoted_fee_cents` while the order is `SCHEDULED`, `IN_PROGRESS`, or `REPORT_DRAFT`, the `final_fee_cents` once the order is `DELIVERED`, and 0 once the order is `CANCELLED`. From that effective fee, `amount_due_cents` is the effective fee minus `amount_paid_cents` plus `amount_refunded_cents`.

An inspector starts the on-site work on an order assigned to them, advancing it from `SCHEDULED` to `IN_PROGRESS`; the order must be `SCHEDULED` (else `ERR_INVALID_STATE`) and the acting inspector's `id` must equal the order's `inspector_id` (otherwise `ERR_NOT_ASSIGNED_INSPECTOR`), the `SCHEDULED`-state check being evaluated before the assigned-inspector check, and the order's `version` is incremented. From `IN_PROGRESS` the same assigned inspector authors the report, advancing the order to `REPORT_DRAFT`. Delivery is the closing act, performed by a `Scheduler`: it moves a `REPORT_DRAFT` order to `DELIVERED`. Delivery is gated on three conditions — the order must be in `REPORT_DRAFT` (else `ERR_INVALID_STATE`), the order's report must be `APPROVED` (a missing or non-`APPROVED` report is rejected with `ERR_INVALID_STATE`), and the order must be fully paid, meaning `amount_due_cents` is at most 0; an attempt to deliver an order that still owes money is rejected with `ERR_ORDER_UNPAID`. These conditions are evaluated in that order: the `REPORT_DRAFT` state check first, then the report-`APPROVED` check, then the full-payment check. On delivery the system computes `final_fee_cents` from the report's measured square footage, recomputes `amount_due_cents` against that final fee, locks the report into a delivered state, and creates two delivery records before incrementing the order's `version`.

A **Delivery** row captures who received the report. On delivery the system creates exactly two delivery rows, one with `recipient_kind` of `CLIENT` and one of `AGENT`, each in `SENT` status. Each row stamps a `recipient_email` captured from the corresponding client or agent at delivery time and a `severity_band_snapshot` copied from the report's grade at that moment. A delivery's `status` is `SENT` or `CANCELLED`; it becomes `CANCELLED` only when the owning order is cancelled. Each of the two delivery creations participates in recomputing the order's `amount_due_cents` against the final fee.

### 3.6. The Defect Report and Its Review Cycle

Once an inspection is in progress, the assigned inspector files a **Report**, which is unique to its order — at most one report per order. The report-creation payload records the `measured_square_footage` (greater than 0), the on-site measurement that will later drive the final fee. The report is born in `DRAFT` with its `provisional_risk_score` initialized to 0, and creating it advances the owning order from `IN_PROGRESS` to `REPORT_DRAFT` while incrementing the order's `version`. Creating a report requires, evaluated in this order, the order to be `IN_PROGRESS` (else `ERR_INVALID_STATE`), the acting inspector to be the order's assigned inspector (otherwise `ERR_NOT_ASSIGNED_INSPECTOR`), and no report to already exist on the order (else `ERR_INVALID_STATE`). A report carries a `status` of `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`, or `VOIDED`, with `VOIDED` terminal, plus its own `version`.

While the report is in `DRAFT`, the assigned inspector logs defects against it; logging requires the report to be in `DRAFT` (else `ERR_INVALID_STATE`), and that state check is evaluated before the assigned-inspector check (otherwise `ERR_NOT_ASSIGNED_INSPECTOR`). A **Defect** records a `location` and a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and is created with a `status` of `LOGGED`; logging a defect increments the report's `version`. Each defect carries the `report_id` of its parent. A defect's lifecycle runs `LOGGED`, `CONFIRMED`, `CLEARED`, or `VOIDED`, resolved during report approval.

Submitting a `DRAFT` report moves it to `SUBMITTED`. Submission requires the report to be in `DRAFT` (else `ERR_INVALID_STATE`), is restricted to the assigned inspector of the owning order (otherwise `ERR_NOT_ASSIGNED_INSPECTOR`), and requires the owning order to be in `REPORT_DRAFT` (else `ERR_INVALID_STATE`); these are evaluated in that order — report-`DRAFT` state first, then the assigned-inspector check, then the owning-order `REPORT_DRAFT` check — and submission then recomputes the report's `provisional_risk_score` over every non-`VOIDED` defect before incrementing the report's `version`. A submitted report is then reviewed by a `Scheduler`, who either approves or rejects it; approving or rejecting a report that is not in `SUBMITTED` is rejected with `ERR_INVALID_STATE`. Approval moves a `SUBMITTED` report to `APPROVED`: it resolves each still-`LOGGED` defect — a `MAJOR` or `CRITICAL` defect becomes `CONFIRMED`, while a `MINOR` defect becomes `CLEARED` — then computes the report's `final_risk_score` over the `CONFIRMED` defects only, derives the report's `severity_band` from that final score, and increments the report's `version`. Rejection moves a `SUBMITTED` report to `REJECTED` and increments its `version`. A rejected report can be reopened for revision by the assigned inspector, which returns it from `REJECTED` to `DRAFT` and increments its `version`; the report must be `REJECTED` (else `ERR_INVALID_STATE`) and that state check is evaluated before the assigned-inspector check (otherwise `ERR_NOT_ASSIGNED_INSPECTOR`), and the `REJECTED → DRAFT → SUBMITTED` loop may repeat as many times as needed. The report's `final_risk_score` is null until the report is `APPROVED`, and its `severity_band` — one of `PASS`, `MINOR`, `MAJOR`, or `CRITICAL` — is derived only at approval, taking `PASS` when there are zero defects.

The two risk scores differ in scope. The `provisional_risk_score`, computed at submission, ranges over every defect whose `status` is not `VOIDED` (the `LOGGED` defects plus any already `CONFIRMED` or `CLEARED`). The `final_risk_score`, computed at approval, ranges over only the `CONFIRMED` defects; because `MINOR` defects are `CLEARED` at approval, they are excluded from the final figure. Both use the same per-defect weighting: a `MINOR` defect weighs 1, a `MAJOR` defect weighs 4, and a `CRITICAL` defect weighs 10. For each included defect, its weighted points are the defect's weight multiplied by 100 and divided by 3, rounded half up to an integer; these per-defect integers are then summed to form the score. This per-defect-then-sum order is fixed and is not the same as summing first and rounding once. In practical terms a `MINOR` defect contributes 33 points, a `MAJOR` defect 133 points, and a `CRITICAL` defect 333 points.

The `severity_band` is read off the `final_risk_score` by integer thresholds, with each floor inclusive. A final score of exactly 0 yields `PASS`. A score from 1 up to but not including 133 yields `MINOR`. A score from 133 up to but not including 666 yields `MAJOR` — so a single confirmed `MAJOR` defect, at 133, lands exactly on the `MAJOR` floor. A score of 666 or more yields `CRITICAL` — so two confirmed `CRITICAL` defects, at 666, land exactly on the `CRITICAL` floor.

### 3.7. Computing the Fee: Quoted and Final

Every order carries two fee figures computed by the same engine over different square-footage inputs. The forward-looking `quoted_fee_cents` is computed at scheduling (and at re-inspection) from the property's recorded `square_footage`; the `final_fee_cents` is computed at delivery from the report's `measured_square_footage` and is null until the order is `DELIVERED`. The two may diverge whenever the measured footage differs from the recorded footage.

The fee is built in a pinned order of operations against the order's pinned fee schedule. First, the square-footage component is computed by marginal tiers rather than a single average rate. The footage that falls within tier 1 is the lesser of the input footage and `tier1_max_sqft`; the footage within tier 2 is the input footage capped at `tier2_max_sqft` minus `tier1_max_sqft`, but never less than 0; the footage in tier 3 is the input footage minus `tier2_max_sqft`, but never less than 0. The square-footage component in cents is the tier-1 footage times `tier1_rate_cents_per_sqft`, plus the tier-2 footage times `tier2_rate_cents_per_sqft`, plus the tier-3 footage times `tier3_rate_cents_per_sqft`. Second, an inspection-type multiplier is applied to the sum of `base_rate_cents` and that square-footage component: the multiplier is 1.00 for `BUYER`, 0.90 for `SELLER`, 0.75 for `FOUR_POINT`, and 0.60 for `WIND_MIT`, and the product is rounded half up to whole cents at this step. Third, the prices of all `ACTIVE` add-ons are summed as flat amounts — they are not subject to the type multiplier — and added to the rounded typed amount to give the final fee in cents. `REMOVED` add-ons are excluded from this sum. The evaluation order is fixed: tier component, then multiply by the type multiplier and round, then add the add-ons.

### 3.8. Re-inspection of a Failed Inspection

When a delivered inspection grades out poorly, the company offers a discounted re-inspection, spawned and scheduled in a single `Scheduler` action against the delivered parent order. This is the system's branching point out of a terminal-looking state: the parent remains `DELIVERED`, while a brand-new order is created in `SCHEDULED` with `order_kind` of `REINSPECTION` and its `parent_order_id` set to the parent's `id`. The re-inspect payload supplies the new appointment's `inspector_id`, its `scheduled_start`, and the `expected_order_version` for the optimistic-concurrency check (§2.8).

Several preconditions gate the spawn. The parent order must be `DELIVERED`. The supplied inspector must be `ACTIVE` — a `SUSPENDED` inspector is rejected with `ERR_INVALID_STATE`. The parent report's `severity_band` must be `MAJOR` or `CRITICAL`, since only a failing inspection warrants a re-inspection; a parent that graded `PASS` or `MINOR` is rejected with `ERR_REINSPECTION_NOT_WARRANTED`. The `expected_order_version` must equal the parent order's current `version`, or the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The new `scheduled_start` must be at least 48 hours after the parent order's `scheduled_start`, or the request is rejected with `ERR_REINSPECTION_TOO_SOON`. Beyond these, the re-inspection runs the full set of normal scheduling checks against the supplied inspector — certification and four-point eligibility (`ERR_INSPECTOR_NOT_CERTIFIED`), territory match (`ERR_TERRITORY_MISMATCH`), travel-buffer double-booking (`ERR_INSPECTOR_DOUBLE_BOOKED`), same-day property conflict (`ERR_PROPERTY_SAME_DAY_CONFLICT`), and daily-capacity (`ERR_DAILY_CAPACITY_EXCEEDED`). When more than one precondition would fail at once, they are evaluated in this fixed priority order: parent-`DELIVERED`, then inspector-`ACTIVE`, then certification and four-point eligibility, then territory match, then double-booking, then same-day property conflict, then re-inspection-too-soon, then re-inspection-not-warranted, then daily-capacity, and finally the stale-version check.

On success, the new re-inspection order is created already in `SCHEDULED`, its `quoted_fee_cents` computed by the standard quoted-fee engine and then discounted, the inspector's daily scheduled-minutes ledger debited for the new `scheduled_date`, and the parent order's `version` incremented by one to record the spawned child. The discount works as follows. First the standard quoted fee is computed for the new order. Then a discount fraction is selected by a band keyed on the parent order's `final_fee_cents`: when the parent's `final_fee_cents` is below 50000 cents, the fraction is the schedule's `reinspection_discount_pct`; when it is at least 50000 but below 100000 cents, the fraction is `reinspection_discount_pct` plus 0.10; and when it is 100000 cents or more, the fraction is `reinspection_discount_pct` plus 0.20, capped at a maximum of 0.90. The re-inspection's fee is then the quoted fee multiplied by one minus the selected fraction, rounded half up to whole cents.

### 3.9. Cancellation and Its Cascades

A `Scheduler` may cancel any non-terminal order — one whose `status` is `REQUESTED`, `SCHEDULED`, `IN_PROGRESS`, or `REPORT_DRAFT` — moving it to the terminal `CANCELLED` state and triggering a coordinated unwind; cancelling an order that is already terminal (`DELIVERED` or `CANCELLED`) is rejected with `ERR_INVALID_STATE`. If the order had been booked (it was `SCHEDULED`, `IN_PROGRESS`, or `REPORT_DRAFT`), the inspector's daily scheduled-minutes ledger is credited back by the order's `duration_minutes` for its `scheduled_date`, leaving net daily load unchanged. Every cent of `amount_paid_cents` is refunded by adding it to `amount_refunded_cents`, conserving money so that nothing remains net-collected. Any report on the order is moved to `VOIDED`, and as a consequence of that void, all of that report's non-`VOIDED` defects are themselves moved to `VOIDED`. Any `SENT` delivery on the order is moved to `CANCELLED`. The order's `version` is incremented. The same report-void cascade applies whenever a report is voided by its owning order's cancellation: the report transitions from whichever of `DRAFT`, `SUBMITTED`, `APPROVED`, or `REJECTED` it occupied to `VOIDED`, its non-`VOIDED` defects follow it to `VOIDED`, and the report's `version` is incremented.

## 4. Endpoint Definitions

Operations that create a new, distinct resource (a territory, fee schedule, inspector, client, agent, property, primary order, add-on, report, defect, or re-inspection order) return `201 Created`. Operations that modify an existing resource — every state transition, payment, publish, suspend, schedule, deliver, cancel, and the like — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/territories` | Create a territory | Scheduler |
| GET | `/territories/{id}` | Get a territory | Scheduler, Inspector |
| GET | `/territories` | List territories | Scheduler, Inspector |
| POST | `/fee-schedules` | Create a fee schedule (DRAFT) | Scheduler |
| POST | `/fee-schedules/{id}/publish` | Publish a fee schedule | Scheduler |
| GET | `/fee-schedules/{id}` | Get a fee schedule | Scheduler, Inspector |
| POST | `/inspectors` | Create an inspector | Scheduler |
| GET | `/inspectors/{id}` | Get an inspector | Scheduler, Inspector |
| GET | `/inspectors` | List inspectors, optionally by territory | Scheduler, Inspector |
| POST | `/inspectors/{id}/suspend` | Suspend an inspector | Scheduler |
| GET | `/inspectors/{id}/daily-load` | Read an inspector's booked minutes for a date | Scheduler, Inspector |
| POST | `/clients` | Create a client | Scheduler |
| GET | `/clients/{id}` | Get a client | Scheduler, Client |
| POST | `/agents` | Create an agent | Scheduler |
| GET | `/agents/{id}` | Get an agent | Scheduler, Agent |
| POST | `/properties` | Create a property | Scheduler, Client, Agent |
| GET | `/properties/{id}` | Get a property | Scheduler, Client, Agent |
| POST | `/inspection-orders` | Create a primary inspection order | Scheduler, Client, Agent |
| GET | `/inspection-orders/{id}` | Get an inspection order | Scheduler, Inspector, Client, Agent |
| GET | `/inspection-orders` | List inspection orders | Scheduler, Inspector, Client, Agent |
| POST | `/inspection-orders/{id}/schedule` | Schedule a REQUESTED order | Scheduler |
| POST | `/inspection-orders/{id}/unschedule` | Return a SCHEDULED order to REQUESTED | Scheduler |
| POST | `/inspection-orders/{id}/start` | Inspector begins the on-site inspection | Inspector |
| POST | `/inspection-orders/{id}/report` | Inspector creates the report | Inspector |
| POST | `/inspection-orders/{id}/pay` | Record a payment against the order | Scheduler, Client, Agent |
| POST | `/inspection-orders/{id}/deliver` | Deliver the approved report | Scheduler |
| POST | `/inspection-orders/{id}/cancel` | Cancel a non-terminal order | Scheduler |
| POST | `/inspection-orders/{id}/reinspect` | Spawn and schedule a re-inspection order | Scheduler |
| POST | `/inspection-orders/{id}/addons` | Attach an add-on to a not-yet-started order | Scheduler, Client, Agent |
| GET | `/inspection-orders/{id}/addons` | List add-ons for an order | Scheduler, Inspector, Client, Agent |
| POST | `/addons/{id}/remove` | Remove an add-on from a not-yet-started order | Scheduler, Client, Agent |
| GET | `/reports/{id}` | Get a report | Scheduler, Inspector, Client, Agent |
| GET | `/inspection-orders/{id}/reports` | List the report(s) for an order | Scheduler, Inspector, Client, Agent |
| POST | `/reports/{id}/submit` | Inspector submits the report for approval | Inspector |
| POST | `/reports/{id}/approve` | Scheduler approves a submitted report | Scheduler |
| POST | `/reports/{id}/reject` | Scheduler rejects a submitted report | Scheduler |
| POST | `/reports/{id}/revise` | Inspector reopens a rejected report | Inspector |
| POST | `/reports/{id}/defects` | Log a defect on a DRAFT report | Inspector |
| GET | `/reports/{id}/defects` | List defects on a report | Scheduler, Inspector, Client, Agent |
| GET | `/inspection-orders/{id}/deliveries` | List delivery records for an order | Scheduler, Inspector, Client, Agent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_INSPECTOR` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INSPECTOR_NOT_CERTIFIED` | 409 Conflict |
| `ERR_TERRITORY_MISMATCH` | 409 Conflict |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_PROPERTY_SAME_DAY_CONFLICT` | 409 Conflict |
| `ERR_DAILY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_ADDON` | 409 Conflict |
| `ERR_REINSPECTION_NOT_WARRANTED` | 409 Conflict |
| `ERR_REINSPECTION_TOO_SOON` | 409 Conflict |
| `ERR_ORDER_UNPAID` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION_RANGE` | 400 Bad Request |
