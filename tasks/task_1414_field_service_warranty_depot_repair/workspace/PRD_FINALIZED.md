# Field Service Warranty Depot Repair API — Product Requirements Document

## 1. Introduction

An original-equipment-manufacturer depot repair center lives and dies by turnaround discipline: defective units arrive under a return merchandise authorization, warranty coverage must be judged from serial numbers and purchase dates, every job forces a repair-versus-replace economic decision, customers without coverage must be quoted and billed, and a pool of loaner units keeps customers running while their hardware is on the bench. Behind the bench, recurring failures on the same model and failure code are an engineering signal that cannot be allowed to slip; past a defined recurrence threshold the model may need containment before any more replacement units ship.

This document specifies the REST API that operates that depot, mounted under `/depot`. It covers RMA intake and authorization, inbound receiving and triage, diagnosis with a pinned cost-estimation model, customer quoting with approval and revision, bay scheduling, parts consumption with failure-code attribution, a four-eyes quality gate, loaner and advance-exchange logistics with deposit exposure control, settlement with tiered loyalty credits, and the engineering escalation lifecycle from automatic detection through containment, resolution, and monitoring. All behavior is deterministic: a server-side logical clock drives every date computation, monetary values follow pinned rounding rules, and each workflow is expressed as an explicit state machine so that two independent implementations reading only this document arrive at the same system.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly six roles: `Customer`, `IntakeAgent`, `DepotTechnician`, `DepotManager`, `WarrantyAdministrator`, and `EngineeringLead`. A request with missing headers, or whose `X-User-Role` does not name one of these six roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity is resolved as follows. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer linkage — the `customer_id` carried on a unit or an RMA, or the owning chain behind a quote, a loaner reservation, or a notification — to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403). When `X-User-Role` is `IntakeAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The same is true for `DepotTechnician`, for `DepotManager`, for `WarrantyAdministrator`, and for `EngineeringLead`: in each case `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow writes it — for example as `diagnosed_by`, `repair_completed_by`, or `consumed_by` on bench work, or as `warranty_override_by` on a goodwill grant — but it never compares the identifier to any entity's `id`.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

All date and time arithmetic in the system — warranty eligibility, SLA turnaround, quote expiry, loaner late fees, escalation monitoring windows, and the daily ops checkpoint — reads a server-side logical clock, never the wall clock. Before the clock has been explicitly set, it starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `DepotManager` advances it through an admin-only test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`; the call mutates no entity.

Wherever this document speaks of business days, a business day is a Monday-through-Friday calendar date; there is no holiday calendar. The business-day count between two dates is the number of business-day dates strictly after the first date and on or before the second date.

### 2.5. Common Resource Properties

Every primary resource — customers, product models, units, RMAs, quotes, repair lines, parts, failure codes, depot bays, loaner units, loaner reservations, and engineering escalations — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every mutation of the resource.

Notification events are the single exception: a `NotificationEvent` carries only `id` and `created_at`; both `updated_at` and `version` are absent, because a notification is an immutable fact once written.

### 2.6. Money, Dates, and Rounding Discipline

All monetary amounts are integer cents; no field carries fractional cents. Every pinned rounding step in this document uses the round-half-up method at whole-cent granularity, applied exactly at the step where the document names it — the pinned rounding order is authoritative, and alternative evaluation orders that differ by cents are non-conformant. Calendar-date fields are ISO 8601 dates compared at day granularity; timestamps are ISO 8601 UTC. Threshold comparisons are stated inclusively or exclusively at each use; nothing in this system approximates.

### 2.7. Optimistic Concurrency Control on RMA Writes

Three write operations are guarded by optimistic concurrency control against the parent RMA: editing a draft RMA, creating a revised quote for an RMA, and recording a parts-consumption line on an RMA. Each of these requests must carry `expected_rma_version`, a non-optional input holding the `version` of the `ServiceRMA` the client last observed. If the supplied value does not match the RMA's current `version` — because another write has advanced the version since the client last read it — the request is rejected with `ERR_STALE_RMA_VERSION` (HTTP 412). Each of these three writes, on success, increments the RMA's `version` by one. Endpoints not named in this section do not take a version field.

### 2.8. Validation Order and Nested Path Resolution

Every request is checked against a fixed sequence of validation layers, and an earlier failure masks later ones. First, authentication headers (§2.1), yielding `ERR_UNAUTHENTICATED`. Second, role authorization, yielding `ERR_FORBIDDEN`. Third, customer-ownership scoping, yielding `ERR_NOT_OWNER`. Fourth, existence of path identifiers, resolved left to right along the URL: identifiers such as `customerId`, `modelId`, `unitId`, `partId`, `bayId`, `loanerUnitId`, `rmaId`, `quoteId`, `reservationId`, `escalationId`, `repairLineId`, and the bare `id` used on nested quote and notification listings are checked in the order they appear, and the first identifier that does not resolve short-circuits the request with its own 404 — respectively `ERR_CUSTOMER_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_FAILURE_CODE_NOT_FOUND`, `ERR_BAY_NOT_FOUND`, `ERR_LOANER_UNIT_NOT_FOUND`, `ERR_RMA_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_ESCALATION_NOT_FOUND`, or `ERR_REPAIR_LINE_NOT_FOUND`. Fifth, the optimistic-concurrency check of §2.7, yielding `ERR_STALE_RMA_VERSION`. Sixth, state-machine legality — whether the target entity is in a state permitting the requested transition — yielding the matching error among `ERR_INVALID_RMA_STATE`, `ERR_INVALID_QUOTE_STATE`, `ERR_INVALID_RESERVATION_STATE`, `ERR_INVALID_LOANER_STATE`, `ERR_INVALID_ESCALATION_STATE`, and `ERR_INVALID_LINE_STATE`.

Business rules follow, in their pinned relative order. The safety gates come first among them: model containment (`ERR_MODEL_CONTAINMENT`), the engineering-review gate (`ERR_ENGINEERING_REVIEW_PENDING`), and segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`) are evaluated ahead of the referential and constraint rules. Within those remaining rules the pinned sequence is: unit-versus-customer referential integrity (`ERR_UNIT_CUSTOMER_MISMATCH`); serial match at receiving (`ERR_SERIAL_MISMATCH`); serial uniqueness (`ERR_DUPLICATE_SERIAL`); the open-RMA check (`ERR_UNIT_HAS_OPEN_RMA`); bay window shape (`ERR_INVALID_BAY_WINDOW`) before bay status (`ERR_BAY_INACTIVE`) before bay overlap (`ERR_BAY_OVERLAP`); loaner window shape (`ERR_INVALID_LOANER_WINDOW`) before loaner window overlap (`ERR_LOANER_WINDOW_OVERLAP`) before service-option and model compatibility (`ERR_SERVICE_OPTION_INCOMPATIBLE`, `ERR_LOANER_MODEL_MISMATCH`) before the deposit credit check (`ERR_CREDIT_LIMIT_EXCEEDED`); stock sufficiency (`ERR_INSUFFICIENT_STOCK`); quote expiry (`ERR_QUOTE_EXPIRED`) before payment presence (`ERR_PAYMENT_REQUIRED`); the recorded-work check (`ERR_NO_WORK_RECORDED`); the advance-exchange fulfillment check (`ERR_EXCHANGE_NOT_FULFILLED`); and the outstanding-loaner check (`ERR_LOANER_OUTSTANDING`). Generic payload-shape validation — required fields present, enum values valid, integers in range such as a `quantity` of at least 1, ISO-formatted dates — is the final backstop, evaluated only after every rule above, and yields `ERR_VALIDATION` (HTTP 400).

### 2.9. Segregation of Duties

Three sensitive actions enforce a four-eyes principle, each rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when violated. A manager overriding the repair-versus-replace decision must not be the technician recorded in the RMA's `diagnosed_by`. A technician releasing a repair from the quality gate must not be the technician recorded in `repair_completed_by`. A manager scrapping a unit after a declined quote must not be the administrator recorded in the RMA's `warranty_override_by`, whenever that field is set; when no goodwill grant exists on the RMA, this third check does not apply.

### 2.10. Customer Notification Audit Trail

Every customer-visible milestone writes an immutable `NotificationEvent` carrying the `rma_id` it concerns, an `event_type`, the `recipient` — the customer's `email` address captured at event time — and the rendered `message` text. The twelve event types are `RMA_AUTHORIZED`, `RECEIVED`, `QUOTE_SENT`, `QUOTE_APPROVED`, `QUOTE_DECLINED`, `QUOTE_EXPIRED`, `SHIPPED`, `SLA_BREACH`, `LOANER_LATE`, `ESCALATION_OPENED`, `CLOSED`, and `CANCELLED`. The `LOANER_LATE` event fires at most once per reservation; a `late_notification_sent` flag on the reservation records that it has fired. A customer's notifications for an RMA can be listed, optionally filtered by `event_type`.

## 3. Business Logic & Workflows

### 3.1. Registering the Depot's Catalog, Customers, and Fleet

An `IntakeAgent` registers each customer with a `name` and an `email` address — the notification recipient, unique across customers — and optionally a `credit_limit_cents` (defaulting to 100000 cents, the maximum outstanding loaner deposit exposure the customer may carry) and a `loyalty_tier` of `STANDARD` or `PREFERRED` (defaulting to `STANDARD`). The loyalty flag is informational only; the settlement credit tier is computed from the settlement gross, never from this flag. A fresh customer's `deposit_exposure_cents` starts at 0; thereafter it is maintained as the sum of `deposit_value_cents` over that customer's loaner reservations sitting in `RESERVED` or `SHIPPED`.

A `DepotManager` registers each product model with a unique `model_code`, a free-text `description`, and the commercial constants that drive every later computation: `standard_warranty_days` (warranty length in calendar days from the basis date), `registration_bonus_days` (defaulting to 30, extra days granted to a `RETAIL` unit that carries a registration), `replacement_cost_cents` (the full replacement unit cost that anchors the repair-versus-replace threshold), `flat_rate_repair_cents` (the book-rate provisional estimate used before diagnosis), `labor_rate_cents_per_minute`, `replace_threshold_pct`, `sla_turnaround_business_days` (the depot turnaround SLA measured in business days from receive to ship), `loaner_grace_days` (defaulting to 10, the free calendar days after the repaired unit ships before loaner late fees accrue), `recurring_failure_threshold` (defaulting to 3, the recurring-failure score at or above which an engineering escalation opens automatically), and `quote_valid_days` (defaulting to 14, the calendar days a `SENT` quote remains approvable). A model's `containment_flag` starts false; it becomes true only while an engineering escalation for the model is in containment, and while true it blocks replacement shipment of that model.

An `IntakeAgent` registers each serialized unit with its `serial_number` (globally unique across all units — a duplicate is rejected with `ERR_DUPLICATE_SERIAL`), the `model_id` and owning `customer_id` it references, the sales `channel` (`RETAIL` or `ENTERPRISE`, which selects the warranty basis date), the `purchase_date` (the `RETAIL` warranty basis), the `ship_date` (the `ENTERPRISE` warranty basis — the date the OEM shipped to the enterprise), and optionally a `registration_date`. A unit's `disposition` starts `ACTIVE` and becomes `SCRAPPED` only when an RMA scraps it. Units can be listed with filters on `customer_id`, `model_id`, or `serial_number`.

Catalog administration is rounded out by four more registrations. A `DepotManager` creates each part with a unique `sku`, a `name`, its `unit_cost_cents`, and an `initial_stock` that seeds `stock_on_hand`; an optional `reorder_point` (default 0) is an informational low-water mark. An `EngineeringLead` authors failure codes, each with a unique `code` (for example F-PWR-01), a `description`, and a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`. A `DepotManager` registers each repair bench by its unique `bay_code`; a bay's `status` starts `ACTIVE`, and the manager may deactivate it to `OUT_OF_SERVICE` and later reactivate it to `ACTIVE`. Finally, a `DepotManager` registers each pool loaner unit with a unique `asset_tag`, the `model_id` it satisfies, a `condition_grade` of `A`, `B`, or `C` (grade `C` units are excluded from automatic selection), and a `deposit_value_cents`; the unit starts `AVAILABLE` with `completed_loan_cycles` at 0. Loaner units can be listed filtered by `model_id` or `status`.

### 3.2. Opening an RMA, Authorizing It, and Granting Goodwill

A `Customer` (for their own units) or an `IntakeAgent` (on a customer's behalf) opens a service case with a payload carrying the `customer_id`, the `unit_id`, the customer's `reported_issue` symptom text, and optionally a `service_option` of `STANDARD`, `LOANER`, or `ADVANCE_EXCHANGE` (defaulting to `STANDARD`). The referenced unit must belong to the payload customer; a unit owned by someone else is rejected with `ERR_UNIT_CUSTOMER_MISMATCH`. The RMA is born in `DRAFT` status and is assigned a human reference `rma_number` of the form RMA- followed by a zero-padded sequence. While the RMA remains in `DRAFT`, the customer or an intake agent may still edit its `reported_issue` or `service_option`; this edit is OCC-guarded per §2.7 — the request must carry `expected_rma_version`, a stale value is rejected with `ERR_STALE_RMA_VERSION`, and a successful edit bumps the RMA's `version` — and editing an RMA that has left `DRAFT` is rejected with `ERR_INVALID_RMA_STATE`.

Authorization by an `IntakeAgent` moves the RMA from `DRAFT` to `AUTHORIZED`. Authorization is refused with `ERR_UNIT_HAS_OPEN_RMA` when any other RMA for the same unit sits in a non-terminal state — that is, any state other than `CLOSED`, `SCRAPPED`, or `CANCELLED`. On authorization the system evaluates warranty eligibility once, as of the logical clock's date, and pins the result on the RMA. For a `RETAIL` unit the basis end date is the unit's `purchase_date` plus the model's `standard_warranty_days`; when the unit carries a `registration_date`, a registration end is also computed — the `registration_date` plus `standard_warranty_days` plus `registration_bonus_days` — and the basis end becomes the later of the two. For an `ENTERPRISE` unit the basis end is the `ship_date` plus `standard_warranty_days`, and the `purchase_date` is ignored; the two bases yield different end dates for identical model constants. The computed basis end is pinned as `warranty_end_date_used`, and the RMA's `coverage_path` is pinned to `IN_WARRANTY` when the clock date is on or before that end — eligibility is inclusive of the final warranty day — and to `OUT_OF_WARRANTY` otherwise. Authorization also pins the `provisional_estimate_cents` to the model's `flat_rate_repair_cents`, records `authorized_at` from the logical clock, and emits an `RMA_AUTHORIZED` notification.

The pinned `coverage_path` is mutated only by a goodwill grant. An RMA's `goodwill_pct` starts at 0, its `warranty_override_by` starts null, and its `decision_overridden` flag starts false; all three change only through the workflows that set them. A `WarrantyAdministrator` may override coverage with an `override_coverage` of `GOODWILL_FULL` or `GOODWILL_PARTIAL`, an optional `goodwill_pct` discount, and a mandatory `reason`; the grant pins `goodwill_pct` on the RMA and records the administrator's `X-User-ID` in `warranty_override_by`. When a `SENT` quote is outstanding on the RMA, the grant supersedes it — the old quote becomes `SUPERSEDED` — and creates a replacement quote with the next `quote_seq` whose `discount_pct` equals the granted `goodwill_pct`, while an RMA waiting on quote approval stays in `AWAITING_QUOTE_APPROVAL`. If the RMA was routed to `AWAITING_QUOTE_APPROVAL` and the override is `GOODWILL_FULL`, the RMA instead re-routes to `IN_REPAIR` with the outstanding quote superseded, because full goodwill means the customer owes nothing.

Cancellation is available to the owning `Customer` or an `IntakeAgent` while the RMA is in `DRAFT` or `AUTHORIZED`. From `DRAFT` it simply moves the RMA to `CANCELLED` and emits a `CANCELLED` notification. From `AUTHORIZED` it additionally unwinds the loaner commitment: every reservation of the RMA still in `RESERVED` moves to `CANCELLED`, each such reservation's loaner unit returns from `RESERVED` to `AVAILABLE`, and the customer's `deposit_exposure_cents` is decremented by each released unit's `deposit_value_cents`, before the `CANCELLED` notification fires.

### 3.3. Receiving, Triage, and Recurring-Failure Surveillance

When the physical unit arrives, an `IntakeAgent` records receipt with a payload `serial_number` that must equal the registered serial of the RMA's unit; a mismatch is rejected with `ERR_SERIAL_MISMATCH`. Receipt moves the RMA from `AUTHORIZED` to `RECEIVED`, pins `received_at` from the logical clock — this is the SLA anchor from which turnaround is measured — and emits a `RECEIVED` notification.

Triage, also performed by an `IntakeAgent`, moves the RMA from `RECEIVED` to `TRIAGED` and pins the `primary_failure_code_id` supplied in the payload alongside optional `notes`; the code must reference an existing failure code, otherwise the request fails with `ERR_FAILURE_CODE_NOT_FOUND`. Pinning the primary code triggers a recurring-failure evaluation for the (unit, failure code) pair. The recurring-failure score of a pair, as of the logical clock, sums over the unit's `CLOSED` RMAs whose `primary_failure_code_id` equals the code and whose `closed_at` falls within the trailing 365 days: each such RMA weighs 2 when it closed within the most recent 90 days of that window and 1 when it closed earlier in the window. On top of that history, the score gains a further 2 when the evaluating, still-open RMA itself carries evidence of the code — either its own `primary_failure_code_id` equals the code, or a `CONSUMED` repair line on it references the code. When the score reaches or exceeds the model's `recurring_failure_threshold`, and no escalation already exists for the (model, failure code) pair in `OPEN`, `ACKNOWLEDGED`, `CONTAINMENT_ACTIVE`, or `MONITORING`, the system opens an `EngineeringEscalation` in `OPEN` with `trigger_source` `AUTO_RECURRING`, sets `engineering_review_pending` to true on the evaluating RMA, and emits an `ESCALATION_OPENED` notification on it.

### 3.4. Diagnosis and the Repair-versus-Replace Decision

A `DepotTechnician` diagnoses a `TRIAGED` RMA by supplying `labor_minutes_est`, a `repairability` verdict of `REPAIRABLE` or `BER` (beyond economical repair), and optionally a `planned_parts` array of part-and-quantity pairs. Every referenced part must exist; an unknown part reference is rejected with `ERR_PART_NOT_FOUND`. Diagnosis pins `repairability`, `labor_minutes_est`, the `planned_parts` snapshot, and the technician's `X-User-ID` as `diagnosed_by`, and moves the RMA from `TRIAGED` to `DIAGNOSED`.

Diagnosis computes the final estimate, stored in `final_estimate_cents`: the `labor_minutes_est` multiplied by the model's `labor_rate_cents_per_minute`, rounded half-up to whole cents, plus the sum over each planned parts line of its quantity multiplied by the part's current `unit_cost_cents`. The final variant deliberately uses raw part costs with no handling uplift — quotes apply handling separately, per §3.5 — so the final estimate and a quote total for the same work can legitimately differ, just as the flat book rate pinned at authorization can diverge from both once real labor and parts are known.

The repair-versus-replace `decision` is computed immediately. The threshold is the model's `replacement_cost_cents` multiplied by `replace_threshold_pct` and divided by 100, with any fractional cent discarded. When the technician's verdict is `BER`, the decision is `REPLACE`. Otherwise, when the recurring-failure score of the (unit, primary failure code) pair as of the logical clock is at or above the model's `recurring_failure_threshold`, the decision is `REPLACE` — the lemon rule, forcing replacement of a unit that keeps failing the same way. Otherwise, when the `final_estimate_cents` is at or above the threshold — exact equality is replacement, the comparison is inclusive — the decision is `REPLACE`. In every remaining case the decision is `REPAIR`.

Routing fires automatically in the same request. A `REPAIR` decision on an RMA whose `coverage_path` is `IN_WARRANTY` or `GOODWILL_FULL` routes straight to `IN_REPAIR`. A `REPAIR` decision with `coverage_path` `OUT_OF_WARRANTY` or `GOODWILL_PARTIAL` routes to `AWAITING_QUOTE_APPROVAL` and auto-creates a quote in `SENT` with `quote_seq` 1, built from the planned parts and the estimated labor with the RMA's `goodwill_pct` as its `discount_pct`; a `QUOTE_SENT` notification fires, and an SLA pause interval opens. A `REPLACE` decision routes to `REPLACEMENT_PENDING` regardless of coverage.

A `DepotManager` may override the computed decision by supplying a `new_decision` and a `reason`, subject to the segregation-of-duties rule of §2.9 against `diagnosed_by`. Overriding a `REPLACEMENT_PENDING` RMA to `REPAIR` sets `decision` to `REPAIR`, raises `decision_overridden` to true, and re-fires the auto-route: covered coverage paths proceed to `IN_REPAIR`, while `OUT_OF_WARRANTY` or `GOODWILL_PARTIAL` route to `AWAITING_QUOTE_APPROVAL` with an auto-created quote as above. Overriding an RMA in `AWAITING_QUOTE_APPROVAL` to `REPLACE` requires that the current quote, if any, is not already `APPROVED` — overriding over an approved quote is rejected with `ERR_INVALID_RMA_STATE`; the override sets `decision` to `REPLACE` and `decision_overridden` to true, moves any `SENT` quote to `SUPERSEDED` while clearing `current_quote_id`, routes the RMA to `REPLACEMENT_PENDING`, and closes the open SLA pause interval.

### 3.5. Out-of-Warranty Quoting and the Customer's Decision

A quote snapshots everything the customer is asked to pay. Each quote records its parent `rma_id`, a 1-based `quote_seq` that increments with every revision of the RMA's quote chain, and a `lines` snapshot in which each line carries its `part_id`, `quantity`, the `unit_cost_cents` captured from the part at creation, and the computed `line_total_cents`. The totals follow a pinned rounding order — per-line rounding first, then summation. Each line's `line_total_cents` is its `quantity` multiplied by its snapshot `unit_cost_cents`, increased by a five percent handling uplift, rounded half-up to whole cents at creation; the `parts_subtotal_cents` is the sum of those already-rounded line totals. Summing raw line products and rounding once at the end can differ by cents; the pinned per-line-round-then-sum order is authoritative. The `labor_cents` is the `labor_minutes` billed on the quote multiplied by the model's `labor_rate_cents_per_minute`, rounded half-up. The subtotal — parts subtotal plus labor — then yields `discount_cents`, the subtotal multiplied by the quote's `discount_pct` and divided by 100, rounded half-up; the `discount_pct` itself comes from the RMA's `goodwill_pct` on an auto-created quote, or from explicit input on a manual revision. The `taxable_cents` is the subtotal minus the discount, and the `tax_cents` is eight percent of the taxable amount, rounded half-up. When the `expedite` flag is set, a flat `expedite_fee_cents` of 7500 cents applies; otherwise it is 0. The `total_cents` is the taxable amount plus tax plus the expedite fee. A quote's `sent_at` records when it became `SENT`, and its `expires_at` is `sent_at` extended by the model's `quote_valid_days`; `decided_at` and `payment_reference` stay null until the customer acts.

The owning `Customer` approves a quote by presenting a `payment_reference`; approval without one is rejected with `ERR_PAYMENT_REQUIRED`. The quote must resolve (an unresolvable reference is `ERR_QUOTE_NOT_FOUND`), must be the RMA's current quote and in `SENT` (otherwise `ERR_INVALID_QUOTE_STATE`), and the logical clock must not be later than the quote's `expires_at` — approval at or before the expiry instant is permitted, approval after it is rejected with `ERR_QUOTE_EXPIRED`. Approval moves the quote to `APPROVED`, pins `decided_at` and the `payment_reference`, moves the RMA from `AWAITING_QUOTE_APPROVAL` to `IN_REPAIR`, closes the open SLA pause interval by appending it to `sla_pause_intervals`, and emits a `QUOTE_APPROVED` notification. The customer may instead decline a `SENT` quote: the quote moves to `DECLINED` with `decided_at` pinned, the RMA moves from `AWAITING_QUOTE_APPROVAL` to `QUOTE_DECLINED`, a `QUOTE_DECLINED` notification fires, and the SLA pause remains open — the depot's clock is stopped while the ball is in the customer's court. All the while, the RMA's `sla_pause_intervals` accumulate the half-open intervals, from opening to closing instant, spent in `AWAITING_QUOTE_APPROVAL` or `QUOTE_DECLINED`; they are subtracted from elapsed turnaround per §3.9.

A `DepotTechnician` may revise the quote chain by submitting fresh `labor_minutes`, fresh `parts_lines`, an optional `discount_pct`, and an optional `expedite` flag; the request is OCC-guarded per §2.7 and must carry `expected_rma_version`, with stale views rejected as `ERR_STALE_RMA_VERSION`. Revision is permitted exactly when the RMA sits in `AWAITING_QUOTE_APPROVAL` with its latest quote `SENT` or `EXPIRED`, or when the RMA sits in `QUOTE_DECLINED` with its latest quote `DECLINED` or `EXPIRED`; any other latest-quote state is rejected with `ERR_INVALID_QUOTE_STATE`. A revision moves the previous latest quote to `SUPERSEDED`, creates the new quote in `SENT` with `quote_seq` one greater than its predecessor and totals computed by the pinned quote-total rules above, increments the RMA's `version` by one, returns a `QUOTE_DECLINED` RMA to `AWAITING_QUOTE_APPROVAL` (an RMA already waiting stays waiting), and fires a fresh `QUOTE_SENT` notification. The new quote becomes the RMA's `current_quote_id`. Separately, the daily ops checkpoint (§3.9) moves a `SENT` quote whose `expires_at` is strictly before the logical clock to `EXPIRED`, emitting `QUOTE_EXPIRED`; the RMA remains in `AWAITING_QUOTE_APPROVAL` with its SLA still paused, awaiting a revision or a decision.

Once a quote has been declined, two exits exist. An `IntakeAgent` may return the unit unrepaired: the RMA moves from `QUOTE_DECLINED` to `READY_TO_SHIP`, its `return_reason` is pinned to `UNREPAIRED`, and the SLA pause interval closes. Alternatively, a `DepotManager` may scrap the unit, subject to the segregation-of-duties rule of §2.9 against `warranty_override_by`: the RMA moves from `QUOTE_DECLINED` to `SCRAPPED`, the unit's `disposition` becomes `SCRAPPED`, the SLA pause closes, and the settlement fields are computed per §3.8 from loaner fees only, since no approved quote exists.

### 3.6. Bench Execution: Bays, Parts, and the Quality Gate

While a job is on the bench, a `DepotTechnician` may book a repair bay by naming a `bay_id` with inclusive `start_date` and `end_date` ISO dates. Booking is valid only while the RMA is in `TRIAGED`, `DIAGNOSED`, `IN_REPAIR`, or `AWAITING_PARTS`; at any other state the request fails with `ERR_INVALID_RMA_STATE`. The window must be well-formed — an `end_date` earlier than the `start_date` is rejected with `ERR_INVALID_BAY_WINDOW` — and the named bay must be `ACTIVE`, else `ERR_BAY_INACTIVE`. Bay bookings are closed intervals and carry a one-day turnaround buffer on each side: a new booking conflicts, and is rejected with `ERR_BAY_OVERLAP`, when the padded interval beginning the day before its `start_date` and ending the day after its `end_date` intersects any existing booking on the same bay held by an RMA in `TRIAGED`, `DIAGNOSED`, `IN_REPAIR`, `AWAITING_PARTS`, `QA_HOLD`, or `READY_TO_SHIP`. A successful booking pins `bay_id`, `bay_start_date`, and `bay_end_date` on the RMA.

When a bench job stalls on inventory, the technician flags the RMA as waiting: it moves from `IN_REPAIR` to `AWAITING_PARTS`. Restock is the compensating trigger: a `DepotManager` adding a `quantity` of a part increases its `stock_on_hand` by that quantity and bumps the part's `version` by one, and every RMA sitting in `AWAITING_PARTS` whose `planned_parts` snapshot includes the restocked part automatically resumes to `IN_REPAIR`, processed in `created_at` ascending order with no identifier tie-break.

Parts consumption is recorded per line by a `DepotTechnician` supplying the `part_id`, the `quantity` consumed (at least 1, enforced by generic payload validation), the `failure_code_id` this consumption is attributed to, and `expected_rma_version` per §2.7. The part's `stock_on_hand` must cover the quantity, otherwise the request fails with `ERR_INSUFFICIENT_STOCK`. Success creates a `RepairLine` in `CONSUMED` status with the part's `unit_cost_cents` snapshotted onto the line, a `line_total_cents` of quantity multiplied by that snapshot unit cost (raw cost accounting, no handling uplift), and the recording technician's `X-User-ID` in `consumed_by`; the part's `stock_on_hand` decreases by the quantity, the RMA's `version` increments by one, and the recurring-failure score of §3.3 is recomputed for the line's failure code — a threshold crossing opens the escalation and raises `engineering_review_pending` exactly as at triage. An erroneous consumption can be reversed: the line must still be `CONSUMED` (reversing an already-`REVERSED` line fails with `ERR_INVALID_LINE_STATE`) and its RMA must be in `IN_REPAIR` or `AWAITING_PARTS` (else `ERR_INVALID_RMA_STATE`); reversal moves the line to `REVERSED` and returns its quantity to the part's `stock_on_hand` as a compensating restock. Repair lines can be listed filtered by `rma_id`, `part_id`, `failure_code_id`, or `status`.

Completing the bench work requires proof of work: the technician's repair-complete call is rejected with `ERR_NO_WORK_RECORDED` unless at least one `CONSUMED` repair line exists for the RMA. Success moves the RMA from `IN_REPAIR` to `QA_HOLD` and pins the technician's `X-User-ID` as `repair_completed_by`. The quality gate is a second technician's call with an `outcome`, and it is four-eyes per §2.9: the releasing technician must differ from `repair_completed_by`. On `PASS`, the gate additionally requires `engineering_review_pending` to be false — an RMA under engineering review holds at the gate with `ERR_ENGINEERING_REVIEW_PENDING` until engineering resolves the escalation — and success moves the RMA from `QA_HOLD` to `READY_TO_SHIP`, releasing its bay booking for future overlap checks while keeping the window for audit. On `FAIL` the RMA loops back from `QA_HOLD` to `IN_REPAIR` and its `rework_count` increments by one.

### 3.7. Loaner Pool and Advance-Exchange Logistics

A customer whose RMA carries a `service_option` of `LOANER` or `ADVANCE_EXCHANGE` can have a pool unit reserved by an `IntakeAgent`; attempting to reserve against a `STANDARD` RMA is rejected with `ERR_SERVICE_OPTION_INCOMPATIBLE`. The reservation names a half-open window — a `start_date` that is inclusive and an `end_date` that is exclusive, with the end required to be strictly after the start or the request fails with `ERR_INVALID_LOANER_WINDOW` — and may name an explicit `loaner_unit_id` or leave selection to the server. An explicit pick whose model differs from the model of the RMA's unit is rejected with `ERR_LOANER_MODEL_MISMATCH`. An explicit pick that resolves to an existing loaner unit is not gated on that unit's current status — a unit in any status may be named, with the model match and the half-open window-conflict rule below as the only constraints, so a back-to-back reservation against a unit still committed to an earlier reservation is lawful; `ERR_INVALID_LOANER_STATE` is never raised at reservation time (it belongs to post-return inspection, below). Window conflicts use half-open semantics: the new window conflicts with an existing `RESERVED` or `SHIPPED` reservation on the same unit exactly when the new start is before the existing end and the existing start is before the new end, and back-to-back adjacency — the new start equal to the existing end — is allowed; a conflict is rejected with `ERR_LOANER_WINDOW_OVERLAP`. When `loaner_unit_id` is omitted, the selector considers pool units that are `AVAILABLE`, whose `model_id` matches the RMA's unit model, and whose `condition_grade` is `A` or `B` — grade `C` is excluded from auto-select — ranks them by `completed_loan_cycles` ascending with ties broken by `created_at` ascending (never by identifier), and takes the first; an empty candidate set rejects the request with `ERR_LOANER_UNAVAILABLE`. Before any reservation is created, the customer's deposit headroom is checked: the customer's `deposit_exposure_cents` plus the candidate unit's `deposit_value_cents` must not exceed the customer's `credit_limit_cents`, or the reservation fails with `ERR_CREDIT_LIMIT_EXCEEDED`.

Creating the reservation stamps the reservation in `RESERVED` with its `mode` copied from the RMA's `service_option`, adds the unit's `deposit_value_cents` to the customer's `deposit_exposure_cents`, and moves the chosen loaner unit from `AVAILABLE` to `RESERVED` when the unit is currently `AVAILABLE`; when an explicit pick names a unit in any other status — for example one still `RESERVED` or `SHIPPED_OUT` on an adjacent, non-overlapping window — the unit's status is left unchanged. Reservations can be listed filtered by `rma_id`, `loaner_unit_id`, or `status`. Shipping the loaner to the customer moves the reservation from `RESERVED` to `SHIPPED` — a reservation already past that point is rejected with `ERR_INVALID_RESERVATION_STATE` — moves the unit from `RESERVED` to `SHIPPED_OUT`, and pins the reservation's `shipped_at`. Cancelling a reservation that has not yet shipped returns it from `RESERVED` to `CANCELLED`, the unit from `RESERVED` to `AVAILABLE`, and releases the deposit exposure; the same release cascades from an RMA cancellation (§3.2) and from the daily auto-cancel (§3.9).

Return logistics depend on condition. Receiving a loaner back takes a `condition` and an optional `damage_assessment_cents`; return is a `LOANER`-mode workflow, and attempting it on an `ADVANCE_EXCHANGE` reservation is rejected with `ERR_INVALID_RESERVATION_STATE`. A return in OK condition closes the reservation as `CLOSED_RETURNED`; a return reported as damaged closes it as `CLOSED_DAMAGED` and pins a `damage_fee_cents` equal to the lesser of the `damage_assessment_cents` and the unit's `deposit_value_cents`. Either way the accrued `late_fee_cents` is finalized per the rule below, `returned_at` is pinned, the unit moves from `SHIPPED_OUT` to `INSPECTION`, and the customer's deposit exposure is released. A customer who simply keeps the loaner triggers forfeiture by an `IntakeAgent` or `DepotManager`: the reservation closes as `CLOSED_FORFEITED`, its `forfeit_charge_cents` is set to the unit's `deposit_value_cents` plus the accrued `late_fee_cents`, the unit moves from `SHIPPED_OUT` to `RETIRED`, and the deposit exposure is released.

Late fees apply to `LOANER`-mode reservations only. When the repaired (or replacement) unit ships, every `LOANER`-mode reservation of the RMA still in `SHIPPED` receives a `due_date`: the ship date plus the model's `loaner_grace_days`. The fee is zero while `due_date` is unset, and zero when the as-of date is on or before the `due_date` — a loaner returned on its due date owes nothing. Past the due date, the days late are the calendar days strictly after the `due_date` up to and including the as-of date, and the fee is the days late multiplied by 2500 cents, capped at the unit's `deposit_value_cents`. The daily ops checkpoint (§3.9) recomputes the accrual on every `SHIPPED` loaner reservation past its due date and fires the once-only `LOANER_LATE` notification; the return and forfeit flows finalize the fee.

Post-return, a `DepotTechnician` inspects the unit with an `outcome`; inspection of a unit not in `INSPECTION` is rejected with `ERR_INVALID_LOANER_STATE`. A `PASS` returns the unit to `AVAILABLE` and increments its `completed_loan_cycles` by one, completing the loan cycle that the auto-selector later ranks on. A `FAIL` moves the unit to `RETIRED`, ending its pool life.

### 3.8. Shipment, Settlement, and Closure

Shipment by a `DepotTechnician`, recorded with a `carrier` and `tracking_number`, has two lawful origins. From `READY_TO_SHIP`, the repaired unit ships: `shipped_at` is pinned from the logical clock, and the RMA's `return_reason` becomes `REPAIRED` when it is still unset and the decision was `REPAIR`, otherwise it keeps its existing value — notably `UNREPAIRED` on the decline-and-return path. From `REPLACEMENT_PENDING`, a replacement unit ships, which is guarded twice: the unit's model must not be under containment, otherwise the ship is rejected with `ERR_MODEL_CONTAINMENT`, and when the RMA's `service_option` is `ADVANCE_EXCHANGE` an advance-exchange reservation for the RMA must already be in `SHIPPED` — promising a customer an exchange that never left the depot fails with `ERR_EXCHANGE_NOT_FULFILLED`. Replacement shipment pins `return_reason` to `REPLACED`. On either path, each `LOANER`-mode reservation in `SHIPPED` receives its `due_date` per §3.7, and a `SHIPPED` notification fires.

Closure by an `IntakeAgent` or `DepotManager` moves a `SHIPPED` RMA to `CLOSED` and is blocked while any of its reservations remains in `RESERVED` or `SHIPPED`, surfacing `ERR_LOANER_OUTSTANDING` until the loaner is returned, forfeited, or otherwise released. Closing pins `closed_at` and computes the three settlement fields. The settlement gross — `settlement_gross_cents` — is the `total_cents` of the RMA's current `APPROVED` quote (zero when no approved quote exists) plus, summed over all of the RMA's loaner reservations, each reservation's `late_fee_cents`, `damage_fee_cents`, and `forfeit_charge_cents`. The loyalty tier is keyed on that gross before any credit: a gross of at least 50000 cents earns ten percent, a gross of at least 20000 cents but below 50000 earns five percent, and anything below earns nothing. The `settlement_loyalty_credit_cents` is the gross multiplied by the tier percentage and divided by 100, rounded half-up, and the `settlement_total_cents` is the gross minus the credit. The evaluation order is pinned — gross first, tier from gross, then credit, then net — and the net is never fed back into tier selection. (The same computation runs at scrap time per §3.5, where only loaner fees contribute.) Closure also recomputes the recurring-failure score of §3.3 and performs the recurrence bookkeeping: when a `MONITORING` escalation exists for the RMA's (model, primary failure code) pair and the logical clock date is on or before its `monitoring_until`, that escalation reopens to `OPEN` with its `recurrence_count` incremented by one and an `ESCALATION_OPENED` notification on the triggering RMA. A `CLOSED` notification concludes the case.

### 3.9. Engineering Escalation, Containment, and the Daily Close

An `EngineeringEscalation` links the `rma_id` that triggered it, the `model_id` denormalized from that RMA's unit, and the `failure_code_id` under scrutiny; it records its `trigger_source` (`AUTO_RECURRING` for threshold-detected recurrences per §3.3, `MANUAL` for human-raised ones), a `status`, a `monitoring_until` date, a `recurrence_count` starting at 0, and eventually a `resolution_note`. An `EngineeringLead` may open one manually by naming an `rma_id` and `failure_code_id`: it is born `OPEN` with `trigger_source` `MANUAL`, and `engineering_review_pending` is set on the linked RMA. Escalations can be listed filtered by `rma_id`, `failure_code_id`, `model_id`, or `status`.

The lead works the escalation through a small lifecycle. Acknowledgement moves it from `OPEN` to `ACKNOWLEDGED`. Activating containment — available from either `OPEN` or `ACKNOWLEDGED` — moves it to `CONTAINMENT_ACTIVE` and sets the model's `containment_flag` true, which is precisely what blocks replacement shipment of that model per §3.8. Resolving, which requires a `resolution_note`, is lawful from `OPEN`, `ACKNOWLEDGED`, or `CONTAINMENT_ACTIVE`: the escalation moves to `RESOLVED` and immediately on to `MONITORING` as an automatic companion transition, with `monitoring_until` set to the logical clock date plus 90 days. Resolution clears `engineering_review_pending` on every RMA sharing the escalation's (model, failure code) pair, and releases the model's `containment_flag` — unless another escalation for the same model remains in `CONTAINMENT_ACTIVE`. While `MONITORING`, the watch continues: if a service RMA for the same (model, failure code) pair reaches `CLOSED` while the clock date is on or before `monitoring_until`, the escalation reopens to `OPEN` with `recurrence_count` incremented and `ESCALATION_OPENED` fired on the triggering RMA, per §3.8. Once the clock date passes `monitoring_until` without a recurrence, the daily close moves the escalation to its terminal `CLOSED_FINAL`.

The daily close is a `DepotManager`-run ops checkpoint evaluated against the logical clock, and it returns five lists summarizing what it did: `expired_quote_ids`, `auto_cancelled_rma_ids`, `sla_breached_rma_ids`, `late_fee_reservation_ids`, and `closed_final_escalation_ids`. In order of concern: every quote still `SENT` whose `expires_at` is strictly before the clock becomes `EXPIRED` with a `QUOTE_EXPIRED` notification, leaving its RMA paused in `AWAITING_QUOTE_APPROVAL` per §3.5. Every RMA still in `AUTHORIZED` whose `authorized_at` is more than 30 calendar days behind the clock — a unit that was never received — is auto-cancelled to `CANCELLED`: its `RESERVED` reservations are cancelled, their loaner units return to `AVAILABLE`, the customers' deposit exposure is released, and a `CANCELLED` notification fires. The turnaround SLA is then evaluated for every RMA in `RECEIVED`, `TRIAGED`, `DIAGNOSED`, `AWAITING_QUOTE_APPROVAL`, `QUOTE_DECLINED`, `IN_REPAIR`, `AWAITING_PARTS`, `QA_HOLD`, `READY_TO_SHIP`, or `REPLACEMENT_PENDING`: the elapsed time is the business-day count from the `received_at` date to the clock date, the paused time is the sum over the half-open `sla_pause_intervals` of the business-day count from each interval's `from` date to its `to` date, and the net is elapsed minus paused. When the net is strictly greater than the model's `sla_turnaround_business_days` — a net exactly equal to the target is not a breach — and the RMA is not already flagged, `sla_breached` is set and an `SLA_BREACH` notification fires. Next, every `SHIPPED` `LOANER`-mode reservation past its `due_date` has its `late_fee_cents` recomputed per §3.7, with the once-only `LOANER_LATE` notification guarded by `late_notification_sent`. Finally, each `MONITORING` escalation whose `monitoring_until` the clock date has passed closes to `CLOSED_FINAL`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or act without creating a resource return `200 OK`. The 201 set covers registering customers, product models, units, parts, failure codes, depot bays, and loaner units, as well as opening an RMA draft, creating a revised quote, creating a loaner reservation, and opening an engineering escalation; every other operation returns 200. Request payloads, state preconditions, and side effects for each operation are specified by the workflows in §3; this table is the navigational index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/depot/_clock/set_current_utc` | Set the logical clock (starts at 2026-08-01T00:00:00Z; never falls back to wall-clock) | DepotManager |
| POST | `/depot/ops/run_daily_close` | Daily ops checkpoint: quote expiry, stale-authorization auto-cancel, SLA breach, late-fee accrual, monitoring close-out | DepotManager |
| POST | `/depot/customers` | Register a customer account | IntakeAgent |
| GET | `/depot/customers/{customerId}` | Get a customer (Customer role limited to own record) | Customer, IntakeAgent, DepotManager, WarrantyAdministrator |
| POST | `/depot/product-models` | Create a product model with warranty/commercial constants | DepotManager |
| GET | `/depot/product-models/{modelId}` | Get a product model | IntakeAgent, DepotTechnician, DepotManager, WarrantyAdministrator, EngineeringLead |
| POST | `/depot/units` | Register a serialized unit for a customer | IntakeAgent |
| GET | `/depot/units/{unitId}` | Get a unit (Customer role limited to own units) | Customer, IntakeAgent, DepotTechnician, DepotManager |
| GET | `/depot/units` | List units with filters | IntakeAgent, DepotTechnician, DepotManager |
| POST | `/depot/parts` | Create a catalog part with initial stock | DepotManager |
| GET | `/depot/parts/{partId}` | Get a part | DepotTechnician, DepotManager |
| POST | `/depot/parts/{partId}/restock` | Add stock; auto-resumes matching AWAITING_PARTS RMAs in created_at ascending order | DepotManager |
| POST | `/depot/failure-codes` | Create a failure code | EngineeringLead |
| POST | `/depot/depot-bays` | Register a repair bench | DepotManager |
| GET | `/depot/depot-bays/{bayId}` | Get a bay | DepotTechnician, DepotManager |
| POST | `/depot/depot-bays/{bayId}/deactivate` | Take a bay out of service | DepotManager |
| POST | `/depot/depot-bays/{bayId}/reactivate` | Return a bay to service | DepotManager |
| POST | `/depot/loaner-units` | Register a pool loaner unit | DepotManager |
| GET | `/depot/loaner-units/{loanerUnitId}` | Get a loaner unit | IntakeAgent, DepotTechnician, DepotManager |
| GET | `/depot/loaner-units` | List loaner units with filters | IntakeAgent, DepotManager |
| POST | `/depot/loaner-units/{loanerUnitId}/inspect` | Post-return inspection: PASS completes the cycle to AVAILABLE; FAIL retires the unit | DepotTechnician |
| POST | `/depot/rmas` | Open a draft RMA for a unit | Customer, IntakeAgent |
| GET | `/depot/rmas/{rmaId}` | Get an RMA (Customer role limited to own RMAs) | Customer, IntakeAgent, DepotTechnician, DepotManager, WarrantyAdministrator, EngineeringLead |
| GET | `/depot/rmas` | List RMAs with filters | IntakeAgent, DepotTechnician, DepotManager, WarrantyAdministrator, EngineeringLead |
| PATCH | `/depot/rmas/{rmaId}` | Edit a DRAFT RMA (OCC-guarded) | Customer, IntakeAgent |
| POST | `/depot/rmas/{rmaId}/authorize` | Authorize the RMA; evaluates and pins warranty coverage | IntakeAgent |
| POST | `/depot/rmas/{rmaId}/receive` | Record inbound receipt; serial must match | IntakeAgent |
| POST | `/depot/rmas/{rmaId}/triage` | Record inbound triage and primary failure code | IntakeAgent |
| POST | `/depot/rmas/{rmaId}/diagnose` | Record diagnosis; computes final estimate, decision, and auto-routes | DepotTechnician |
| POST | `/depot/rmas/{rmaId}/schedule-bay` | Book a depot bay window (closed interval with one-day buffer overlap rule) | DepotTechnician |
| POST | `/depot/rmas/{rmaId}/await-parts` | Flag repair as waiting on parts | DepotTechnician |
| POST | `/depot/rmas/{rmaId}/parts` | Record part consumption with failure-code attribution (OCC-guarded) | DepotTechnician |
| POST | `/depot/rmas/{rmaId}/repair-complete` | Mark repair work complete; requires recorded work | DepotTechnician |
| POST | `/depot/rmas/{rmaId}/qa-release` | QA gate: PASS releases to ship, FAIL loops back for rework (four-eyes) | DepotTechnician |
| POST | `/depot/rmas/{rmaId}/ship` | Ship repaired unit (from READY_TO_SHIP) or replacement unit (from REPLACEMENT_PENDING) | DepotTechnician |
| POST | `/depot/rmas/{rmaId}/close` | Close a shipped RMA; computes settlement and recurrence bookkeeping | IntakeAgent, DepotManager |
| POST | `/depot/rmas/{rmaId}/cancel` | Cancel a DRAFT or AUTHORIZED RMA with compensating release of reservations | Customer, IntakeAgent |
| POST | `/depot/rmas/{rmaId}/return-unrepaired` | After quote decline: return the unit unrepaired | IntakeAgent |
| POST | `/depot/rmas/{rmaId}/scrap` | After quote decline: scrap the unit (segregated from the goodwill grantor) | DepotManager |
| POST | `/depot/rmas/{rmaId}/override-decision` | Manager override of the computed repair/replace decision (segregated from the diagnoser) | DepotManager |
| POST | `/depot/rmas/{rmaId}/warranty-override` | Goodwill warranty grant; regenerates an outstanding SENT quote with the goodwill discount | WarrantyAdministrator |
| POST | `/depot/rmas/{rmaId}/quotes` | Create a revised quote (supersedes the latest SENT/DECLINED/EXPIRED quote; OCC-guarded) | DepotTechnician |
| GET | `/depot/quotes/{quoteId}` | Get a quote (Customer role limited to own RMAs' quotes) | Customer, IntakeAgent, DepotTechnician, DepotManager |
| GET | `/depot/rmas/{id}/quotes` | List quotes for an RMA | Customer, IntakeAgent, DepotTechnician, DepotManager |
| POST | `/depot/quotes/{quoteId}/approve` | Customer approves a SENT quote | Customer |
| POST | `/depot/quotes/{quoteId}/decline` | Customer declines a SENT quote | Customer |
| POST | `/depot/rmas/{rmaId}/loaner-reservations` | Reserve a loaner/exchange unit; server-selects when the unit is omitted | IntakeAgent |
| GET | `/depot/loaner-reservations/{reservationId}` | Get a loaner reservation (Customer role limited to own RMAs' reservations) | Customer, IntakeAgent, DepotTechnician, DepotManager |
| GET | `/depot/loaner-reservations` | List loaner reservations with filters | IntakeAgent, DepotTechnician, DepotManager |
| POST | `/depot/loaner-reservations/{reservationId}/ship` | Ship the loaner to the customer | IntakeAgent |
| POST | `/depot/loaner-reservations/{reservationId}/return` | Receive the loaner back (LOANER mode only); condition drives the damage fee | IntakeAgent |
| POST | `/depot/loaner-reservations/{reservationId}/cancel` | Cancel a RESERVED (not yet shipped) reservation | IntakeAgent |
| POST | `/depot/loaner-reservations/{reservationId}/forfeit` | Customer keeps the loaner; full deposit plus late fees charged | IntakeAgent, DepotManager |
| POST | `/depot/engineering-escalations` | Manually open an escalation for an RMA and failure code (model derived from the RMA's unit) | EngineeringLead |
| GET | `/depot/engineering-escalations/{escalationId}` | Get an engineering escalation | DepotTechnician, DepotManager, EngineeringLead |
| GET | `/depot/engineering-escalations` | List escalations with filters | DepotTechnician, DepotManager, EngineeringLead |
| POST | `/depot/engineering-escalations/{escalationId}/acknowledge` | Acknowledge an OPEN escalation | EngineeringLead |
| POST | `/depot/engineering-escalations/{escalationId}/contain` | Activate containment; sets the model's containment flag | EngineeringLead |
| POST | `/depot/engineering-escalations/{escalationId}/resolve` | Resolve; releases containment, clears review gates, enters 90-day monitoring | EngineeringLead |
| GET | `/depot/repair-lines/{repairLineId}` | Get a repair line | DepotTechnician, DepotManager, EngineeringLead |
| GET | `/depot/repair-lines` | List repair lines with filters | DepotTechnician, DepotManager, EngineeringLead |
| POST | `/depot/repair-lines/{repairLineId}/reverse` | Reverse an erroneous consumption; restocks the part (compensating action) | DepotTechnician |
| GET | `/depot/rmas/{id}/notifications` | List notification events for an RMA (Customer role limited to own RMAs) | Customer, IntakeAgent, DepotManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the workflow narratives of §2 and §3; this catalogue is the index of identifiers to HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_MODEL_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_PART_NOT_FOUND` | 404 Not Found |
| `ERR_FAILURE_CODE_NOT_FOUND` | 404 Not Found |
| `ERR_BAY_NOT_FOUND` | 404 Not Found |
| `ERR_LOANER_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_RMA_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_ESCALATION_NOT_FOUND` | 404 Not Found |
| `ERR_REPAIR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_LINE_STATE` | 409 Conflict |
| `ERR_STALE_RMA_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_RMA_STATE` | 409 Conflict |
| `ERR_INVALID_QUOTE_STATE` | 409 Conflict |
| `ERR_INVALID_RESERVATION_STATE` | 409 Conflict |
| `ERR_INVALID_LOANER_STATE` | 409 Conflict |
| `ERR_INVALID_ESCALATION_STATE` | 409 Conflict |
| `ERR_UNIT_CUSTOMER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SERIAL_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_UNIT_HAS_OPEN_RMA` | 409 Conflict |
| `ERR_INVALID_BAY_WINDOW` | 422 Unprocessable Entity |
| `ERR_BAY_INACTIVE` | 409 Conflict |
| `ERR_BAY_OVERLAP` | 409 Conflict |
| `ERR_INVALID_LOANER_WINDOW` | 422 Unprocessable Entity |
| `ERR_LOANER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SERVICE_OPTION_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_LOANER_MODEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LOANER_UNAVAILABLE` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_PAYMENT_REQUIRED` | 402 Payment Required |
| `ERR_MODEL_CONTAINMENT` | 409 Conflict |
| `ERR_ENGINEERING_REVIEW_PENDING` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NO_WORK_RECORDED` | 409 Conflict |
| `ERR_EXCHANGE_NOT_FULFILLED` | 409 Conflict |
| `ERR_LOANER_OUTSTANDING` | 409 Conflict |
