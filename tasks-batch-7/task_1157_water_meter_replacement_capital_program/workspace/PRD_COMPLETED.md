# Water Meter Replacement Program API — Product Requirements Document

## 1. Introduction

A water utility facing an aging meter population runs its replacement effort as a multi-wave capital program: thousands of legacy meters must be swapped for AMI-capable units without losing control of budget, customer communication, field quality, or contractor payment. This document specifies the API that backs that program office. It covers wave planning and budget commitment, customer notification and appointment scheduling, the physical meter swap with final and initial read reconciliation, the no-access escalation ladder, AMI endpoint registration and communication verification, bench testing and contractor quality audit, high-bill complaint adjudication, and contractor invoicing. All endpoints are mounted under the `/api` prefix.

The operating model is one of strict segregation of duties: contractors perform work, independent auditors verify it, customer service adjudicates disputes, and the program manager governs waves, money, and reporting. Every state transition, calculation, and validation described here is deterministic, and every system-generated timestamp is drawn from a controllable logical clock so the full program lifecycle can be exercised reproducibly. Section 2 states the system-wide contracts, Section 3 walks the business workflows, and Sections 4 and 5 give the HTTP and error-code reference.

## 2. Global Specifications & System-Wide Principles

### 2.1 User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles exist, spelled exactly as follows:

- `ProgramManager` — the utility's capital-program owner: creates programs and drives them through activation, closing, and closure; creates and transitions waves; onboards, suspends, and reinstates contractors; approves or disputes invoices; reads the completion report; and drives the logical clock.
- `Scheduler` — utility operations: registers service accounts and meters, performs baseline installs and meter disposal, creates work orders, assigns contractors, sends customer notifications and confirms their delivery, books appointments, advances and resolves no-access cases, and closes or cancels work orders.
- `FieldContractor` — a contractor crew: completes appointments, reports no-access, performs swaps and reconciliations, submits rework after a failed audit, appends meter readings, and creates and submits its own invoices.
- `QualityAuditor` — the independent meter shop and field QC function: records bench tests, raises for-cause quality audits, and records audit results.
- `AmiOperator` — the AMI network operator: registers endpoints, ingests network reads, verifies communication, and replaces failed endpoints.
- `CustomerService` — the CSR desk: confirms and cancels appointments with customers, and files, triages, orders bench tests for, adjudicates, and withdraws high-bill complaints.

Role identity works in two ways. When `X-User-Role` is `FieldContractor`, `X-User-ID` is the `id` of the acting `Contractor`; ownership checks on any resource that references a contractor compare the resource's foreign-key field — `Appointment.contractor_id`, `WorkOrder.contractor_id`, or `ContractorInvoice.contractor_id` — to `X-User-ID`, and a mismatch is rejected with `ERR_CONTRACTOR_MISMATCH` (HTTP 403). When `X-User-Role` is `ProgramManager`, `Scheduler`, `QualityAuditor`, `AmiOperator`, or `CustomerService`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

All six roles may call every list and detail read endpoint. Mutating endpoints are restricted per the authorization column of Section 4.

### 2.2 API Response Structure

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
- The `message` provides a human-readable explanation of what went wrong. A request to an undeclared path or with an unsupported method is rejected with `ERR_NOT_FOUND` (HTTP 404) in this envelope, and an unexpected server failure returns HTTP 500 with `error_id` `ERR_INTERNAL` in this same envelope.

### 2.3 Pagination

List endpoints accept the `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and must be zero or greater. A non-integer or out-of-range `limit` or `offset` is refused with `ERR_VALIDATION`. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Every list is sorted by `created_at` ascending, with ties broken by insertion order.

List endpoints also accept filter parameters that share names with resource fields: programs filter by `status`; contractors by `program_id` and `status`; accounts by `status`, `meter_location`, and `priority_tier`; meters by `service_account_id`, `status`, and `technology`; waves by `program_id` and `status`; work orders by `wave_id`, `service_account_id`, `contractor_id`, `status`, `old_meter_id`, and `new_meter_id`; notifications by `work_order_id`, `no_access_case_id`, and `status`; appointments by `work_order_id`, `contractor_id`, `slot_date`, and `status`; no-access cases by `work_order_id`, `stage`, and `status`; readings by `work_order_id`, `meter_id`, and `read_type`; endpoint registrations by `work_order_id`, `meter_id`, and `status`; bench tests by `meter_id`, `work_order_id`, `complaint_id`, and `result`; complaints by `service_account_id`, `work_order_id`, `bench_test_id`, and `status`; quality audits by `work_order_id`, `contractor_id`, and `result_status`; invoices by `contractor_id`, `program_id`, and `status`.

### 2.4 Resource Identity, Timestamps, and the Logical Clock

Every resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp formatted as ISO 8601 UTC with three fractional digits. Mutable resources additionally carry `updated_at`, refreshed to the current clock on every mutation, and `version`, an integer that increments by exactly one on every mutation of the resource. The one exception is the meter reading: a reading is an append-only event carrying only `id` and `created_at`; it has no `updated_at` and no `version`, and no endpoint modifies or deletes a recorded reading.

All system-generated timestamps — `created_at`, `updated_at`, and the business timestamps the workflows stamp, such as a notification's `sent_at`, a registration's `registered_at`, a bench test's `tested_at`, an audit's `recorded_at`, and a work order's `closed_at` — are drawn from a server-side logical clock, never from wall-clock time. At startup the logical clock reads exactly 2026-05-01T00:00:00Z. A `ProgramManager`-only test-driving capability accepts a `to_iso8601` instant and sets the clock to it, returning the resulting `current_utc`; every subsequent system timestamp and every date comparison in the rule set uses this clock. Whole-day differences used by the calculations are computed as the floor of the elapsed seconds divided by 86,400, and calendar-date comparisons (such as appointment slot checks) compare against the logical clock's current date.

### 2.5 Optimistic Concurrency Control on Work Orders

Five write operations require the caller to supply `expected_work_order_version`, carrying the `version` of the work order as the client last observed it: assigning a contractor to a work order, booking an appointment, recording a swap, reconciling a swap, and submitting rework. If the supplied value does not match the work order's current `version` — because another writer has advanced the work order since the client last read it — the request is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), preventing the client from acting on a stale decision basis. Endpoints not in this list do not take a version field.

### 2.6 Money, Percentages, and Measurement Conventions

All monetary amounts are integer cents; where a calculation produces a fractional cent, it rounds half up to a whole cent, and where a settlement sums components, each component is rounded to whole cents first and the components are then summed. Percentages are carried at two decimal places, rounded half up. Contractor quality is expressed in integer basis points, with 10,000 basis points representing a perfect record. Dates produced by forecasts are rounded up to whole days. Register reads and measured volumes are never negative. Register read values — an account's `last_billed_read_value`, an install's `initial_read_value`, a swap's `final_read_value` and `initial_read_value`, and a reading's `value` — are integers; `avg_daily_usage_ccf` and the bench-test measured volumes may be non-integer numbers.

### 2.7 Validation Order and Request Governance

Every request passes through the same gauntlet of checks, and the stages are evaluated strictly in the order given here: a failure at an earlier stage is the one reported, even when a later stage would also have failed.

1. Authentication — the `X-User-Role` and `X-User-ID` headers are present and the role is one of the six declared roles; otherwise `ERR_UNAUTHENTICATED`.
2. Role authorization — the role is permitted on this endpoint; otherwise `ERR_FORBIDDEN`.
3. Contractor ownership — on contractor-owned writes, the acting `FieldContractor` owns the targeted resource; otherwise `ERR_CONTRACTOR_MISMATCH`. Where the targeted resource is addressed by the URL path, its existence is established first (a missing path resource yields `ERR_NOT_FOUND`) and ownership is then evaluated against the loaded resource, before any body-supplied foreign keys are resolved; where the contractor identity itself arrives in the body (invoice creation), ownership is evaluated before that reference's existence.
4. Existence — every path identifier resolves to an existing resource, validated left to right along the URL path (path variables are named `programId`, `contractorId`, `accountId`, `meterId`, `waveId`, `workOrderId`, `notificationId`, `appointmentId`, `caseId`, `readingId`, `registrationId`, `benchTestId`, `complaintId`, `auditId`, and `invoiceId`); body foreign-key references are then resolved in the order the endpoint declares its payload fields, each reference's existence checked immediately before that field's own schema validation, so an unresolvable earlier reference is reported before a schema fault on a later field, while a missing or non-string reference falls through to stage 5; otherwise `ERR_NOT_FOUND`.
5. Payload schema — required fields are present, types are valid, enum members are valid, and ranges hold (budgets and capacities strictly positive, read values zero or greater, and so on); a missing or malformed JSON body is treated as an empty payload; otherwise `ERR_VALIDATION`.
6. Uniqueness — `account_number` collides with a registered account (`ERR_ACCOUNT_NUMBER_CONFLICT`), `serial_number` with a registered meter (`ERR_METER_SERIAL_CONFLICT`), `endpoint_serial` with an existing registration, including the serial supplied on a replacement (`ERR_AMI_ENDPOINT_SERIAL_CONFLICT`), or `wave_number` duplicated within the same program (`ERR_VALIDATION`).
7. State validity — the target resource is in a valid from-state for the requested transition, terminal states reject every transition, and complaint filing additionally requires the work order to be `SWAPPED` or later; otherwise `ERR_INVALID_STATE`. Immediately after state validity, and before stages 8–14, the five versioned operations of Section 2.5 evaluate the `expected_work_order_version` comparison, refusing a mismatch with `ERR_STALE_WORK_ORDER_VERSION`.
8. Program-active gate — wave opening, work order creation, and contractor onboarding require the program to be `ACTIVE`; otherwise `ERR_PROGRAM_NOT_ACTIVE`.
9. Safety rules — the critical-channel booking rule (`ERR_CRITICAL_CHANNEL_REQUIRED`), the forced-entry stage rule (`ERR_FORCED_ENTRY_NOT_AUTHORIZED`), and the mandatory-bench-test adjudication rule (`ERR_BENCH_TEST_REQUIRED`).
10. Temporal rules — the notice window (`ERR_NOTICE_WINDOW_NOT_MET`), the slot-not-in-past rule (`ERR_APPOINTMENT_SLOT_PAST`), and the wave window non-overlap rule (`ERR_WAVE_WINDOW_OVERLAP`).
11. Capacity constraints — the crew window bucket (`ERR_CREW_WINDOW_FULL`), wave capacity (`ERR_WAVE_CAPACITY_EXCEEDED`), and the one-open-work-order-per-account rule (`ERR_ACCOUNT_ALREADY_IN_PROGRAM`).
12. Open-item blockers — an open complaint (`ERR_OPEN_COMPLAINT_EXISTS`), an open no-access case (`ERR_OPEN_NO_ACCESS_CASE`), or a missing delivered stage notification on escalation advance (`ERR_ESCALATION_STEP_REQUIRED`).
13. Referential compatibility — contractor must be `ACTIVE` and belong to the same program (`ERR_CONTRACTOR_NOT_ACTIVE`, `ERR_CROSS_PROGRAM_REFERENCE`), the complaint's account must match the work order's account (`ERR_ACCOUNT_WORK_ORDER_MISMATCH`), the meter must be in the required status and technology (`ERR_METER_NOT_AVAILABLE`), and the reading plausibility rules (`ERR_READING_SEQUENCE_INVALID`, `ERR_RECONCILE_READINGS_INCOMPLETE`).
14. Fiscal gates — the complaint variance threshold (`ERR_COMPLAINT_VARIANCE_BELOW_THRESHOLD`), the wave-lock commitment ceiling (`ERR_BUDGET_COMMITMENT_EXCEEDED`), the invoice-approval affordability check (`ERR_BUDGET_AVAILABLE_EXCEEDED`), and the non-empty invoice period rule (`ERR_INVOICE_PERIOD_EMPTY`).

### 2.8 State Machines, Mutation Consistency, and Cascades

Each entity in Section 3 carries a status field whose values are fixed enumerations, spelled in uppercase exactly as written there. A transition is legal only from its declared from-states; a resource sitting in a terminal state rejects every further transition with `ERR_INVALID_STATE`. Every successful transition increments the resource's `version` by one and refreshes its `updated_at`, and where a transition has side effects on other entities — a swap that touches two meters, a work order, and an account in one call, for example — all of those effects land together as part of the same request, each affected resource bumping its own `version`. Derived counters and budget figures described in Section 3 are recomputed immediately whenever an underlying mutation touches their input set; there is no deferred or batch recalculation. Changes to these derived figures — the program budget figures and `completed_meter_count`, the wave `committed_count` and `completed_count`, and the contractor `installs_completed_count` — do not increment the owning resource's `version` or refresh its `updated_at`; likewise the contractor quality-score recomputation of Section 3.7 writes `quality_score_bp` and `audits_failed_count` without a `version` bump, incrementing the contractor's `version` only when its status actually changes.

## 3. Business Logic & Workflows

### 3.1 Program Setup, Budget Posture, and Completion Reporting

A `ProgramManager` opens a replacement program by supplying its `name`, a `fiscal_year` label such as FY2027, the `budget_total_cents` capital ceiling (strictly positive), the `target_meter_count` of planned replacements (strictly positive), the `rate_per_ccf_cents` volumetric rate used for swap true-ups (zero or greater), the `default_unit_allowance_cents` planning allowance committed per work order at creation (zero or greater), and optionally `notice_days`, the regulatory minimum days between notification delivery and appointment slot (zero or greater), which defaults to 3 when omitted. A new program starts in `PLANNING` status with `budget_committed_cents` and `budget_spent_cents` at zero, `completed_meter_count` at zero, and `budget_posture` of `FUNDED`.

Activation moves the program `PLANNING` → `ACTIVE`, and only an `ACTIVE` program accepts new waves opening, work order creation, and contractor onboarding. When the program's waves have all reached `COMPLETE` or `CANCELLED`, the program manager may begin closing, moving `ACTIVE` → `CLOSING`; once every contractor invoice of the program has reached `APPROVED`, closure moves `CLOSING` → `CLOSED`, the program's terminal state.

The program's budget is a live ledger recomputed on every mutation that touches a work order commitment — creation, assignment, closure, or cancellation — and on every invoice approval. `budget_committed_cents` is the sum of `committed_amount_cents` over the program's work orders whose `lifecycle_status` is neither `CLOSED` nor `CANCELLED` (a work order belongs to the program through its wave). `budget_spent_cents` is the sum of `net_amount_cents` over the program's invoices in `APPROVED` status only; `DRAFT`, `SUBMITTED`, and `DISPUTED` invoices do not count. `budget_available_cents` is `budget_total_cents` minus `budget_committed_cents` minus `budget_spent_cents`. The `budget_posture` is `OVERRUN` when committed plus spent exceeds `budget_total_cents`; otherwise `TIGHT` when `budget_available_cents` falls below ten percent of `budget_total_cents` (the floor of that product); otherwise `FUNDED`.

A program-manager-only completion report returns `completed_meter_count`, `target_meter_count`, the `completion_pct` derived from completed against target meters, the four budget figures `budget_total_cents`, `budget_committed_cents`, `budget_spent_cents`, and `budget_available_cents`, the current `budget_posture`, and two forecast dates computed in different ways. The run-rate variant divides `completed_meter_count` by the number of whole days elapsed since the program's creation date (at least one day) to get a daily completion rate; the `forecast_run_rate_date` is then the current logical date advanced by the ceiling of the remaining meter count divided by that daily rate, with the rate floored at one ten-thousandth of a meter per day so the division is always defined. The stage-weighted variant instead values the live pipeline: each open work order contributes a fractional credit by `lifecycle_status` — `CREATED` 0.05, `NOTIFIED` 0.15, `SCHEDULED` 0.30, `ACCESS_FAILED` 0.25, `SWAPPED` 0.60, `RECONCILED` 0.75, `AMI_VERIFIED` 0.85, `QA_REVIEW` 0.90, `QA_FAILED` 0.55 — and `equivalent_done` is `completed_meter_count` plus the sum of those credits. Total crew weekly capacity is the sum over the program's `ACTIVE` contractors of `crew_capacity_per_window` multiplied by nine windows per week; the remaining work in weeks is the target minus `equivalent_done`, divided by the greater of that capacity and one; and the `forecast_stage_weighted_date` is the current logical date advanced by the ceiling of those remaining weeks converted to days at seven per week. Both forecast dates are rendered as `YYYY-MM-DD` calendar dates.

### 3.2 Master Data: Service Accounts, Meter Inventory, and Contractor Governance

Before any wave can run, the `Scheduler` populates the program's master data. A service account is registered with its unique `account_number` (a duplicate is refused with `ERR_ACCOUNT_NUMBER_CONFLICT`), the `service_address`, the `meter_location` — `INSIDE` or `OUTSIDE`, where an `INSIDE` meter requires the customer's presence at the appointment — the `customer_name` and `customer_phone`, an optional `priority_tier` of `STANDARD`, `SENSITIVE`, or `CRITICAL` defaulting to `STANDARD`, the historical `avg_daily_usage_ccf` (zero or greater), and the billing baseline `last_billed_read_value` with its `last_billed_read_at` timestamp. A new account starts `ELIGIBLE`. From there the account's status is driven entirely by system events: creating a work order for the account moves it `ELIGIBLE` → `IN_PROGRAM`; the swap on that work order moves it `IN_PROGRAM` → `REPLACED`; a no-access case resolving with `ACCOUNT_EXEMPTED` moves it `IN_PROGRAM` → `EXEMPTED`, which is terminal; and cancelling the account's open work order returns it `IN_PROGRAM` → `ELIGIBLE` provided no other open work order remains.

Meters enter the inventory through the `Scheduler` with a unique `serial_number` (a duplicate is refused with `ERR_METER_SERIAL_CONFLICT`), a `size_code` of `S_5_8`, `S_3_4`, `S_1`, `S_1_5`, or `S_2`, and a `technology` of `LEGACY` or `AMI`, starting life `IN_STOCK`. A baseline install places an `IN_STOCK` meter onto an account — the request carries the target `service_account_id`, the `initial_read_value` observed at install, and the `installed_at` timestamp — and is refused with `ERR_METER_NOT_AVAILABLE` when the account already has an `INSTALLED` meter; a successful install moves the meter `IN_STOCK` → `INSTALLED` and records `service_account_id` and `installed_read_value` on the meter. The remaining meter transitions are downstream of program workflows: a swap removes the old meter (`INSTALLED` → `REMOVED`, clearing its `service_account_id`), a bench test verdict moves a `REMOVED` meter to `BENCH_PASSED` or `BENCH_FAILED`, and disposal by the `Scheduler` moves a `BENCH_PASSED` meter to `DISPOSED` or a `BENCH_FAILED` meter to `RETURNED_TO_VENDOR`, both terminal.

Contractors are onboarded by the `ProgramManager` against an `ACTIVE` program — onboarding into a non-active program fails with `ERR_PROGRAM_NOT_ACTIVE` — with the `program_id`, the legal `name`, the `crew_capacity_per_window` (at least one appointment per date-and-window bucket), and the negotiated `unit_price_cents` per completed change-out (zero or greater). A new contractor starts `ACTIVE` with `quality_score_bp` at 10,000 basis points, `audits_failed_count` at zero, and `installs_completed_count` — the count of that contractor's work orders that have reached `CLOSED` — at zero. The program manager may suspend a contractor (`ACTIVE` → `SUSPENDED`) and later reinstate it (`SUSPENDED` → `ACTIVE`); suspension also happens automatically when the quality score recomputation of Section 3.7 drops `quality_score_bp` below 9,200 basis points. While a contractor is `SUSPENDED`, assigning it to a work order and booking appointments against its crews are refused with `ERR_CONTRACTOR_NOT_ACTIVE`.

### 3.3 Wave Planning and Work Order Intake

Work is organized into waves. The `ProgramManager` creates a wave in `DRAFT` status with its `program_id`, an integer `wave_number` unique within the program, a planning window from `window_start` (inclusive) to `window_end` (exclusive) — a half-open interval of ISO 8601 instants, accepted as supplied with no ordering check between the bounds — and a `capacity` of at least one, the maximum number of non-cancelled work orders the wave will hold. The wave's `committed_count` (its work orders not in `CANCELLED`) and `completed_count` (its work orders in `CLOSED`) are maintained automatically.

Opening a wave (`DRAFT` → `OPEN`) requires the program to be `ACTIVE`, failing otherwise with `ERR_PROGRAM_NOT_ACTIVE`, and requires the wave's half-open window not to intersect any other wave of the same program in `OPEN` or `LOCKED` status — adjacency, where one wave's `window_end` equals the other's `window_start`, is permitted — failing with `ERR_WAVE_WINDOW_OVERLAP`. Locking a wave (`OPEN` → `LOCKED`) runs a program-wide commitment check: `budget_committed_cents`, including this wave's live work orders, must not exceed `budget_total_cents`, with equality allowed; a breach is refused with `ERR_BUDGET_COMMITMENT_EXCEEDED`. A `LOCKED` wave whose work orders have all reached `CLOSED` or `CANCELLED` is completed (`LOCKED` → `COMPLETE`). A wave in `DRAFT` or `OPEN` carrying zero non-cancelled work orders may be cancelled into `CANCELLED`; both `COMPLETE` and `CANCELLED` are terminal.

Once a wave is `OPEN`, the `Scheduler` raises change-out work orders against it, each carrying just `wave_id` and `service_account_id`. Creation requires the program `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`), the wave's `committed_count` still below its `capacity` (`ERR_WAVE_CAPACITY_EXCEEDED`), and no other open work order — one whose `lifecycle_status` is neither `CLOSED` nor `CANCELLED` — on the account (`ERR_ACCOUNT_ALREADY_IN_PROGRAM`). At creation the system captures the account's currently `INSTALLED` meter as the work order's `old_meter_id` (null when the account has no `INSTALLED` meter at creation), books a budget commitment equal to the program's `default_unit_allowance_cents` into `committed_amount_cents`, moves the account `ELIGIBLE` → `IN_PROGRAM`, recomputes the program budget, and leaves the work order in `lifecycle_status` `CREATED` with `hold_status` `CLEAR`, `no_access_strikes` at zero, and `contractor_id` and `new_meter_id` not yet set.

Assigning a contractor is a `Scheduler` action carrying the `contractor_id` and, per Section 2.5, `expected_work_order_version`. The contractor must be `ACTIVE` (`ERR_CONTRACTOR_NOT_ACTIVE`) and must belong to the same program as the work order's wave (`ERR_CROSS_PROGRAM_REFERENCE`). Re-assignment is legitimate while the work order is in `CREATED`, `NOTIFIED`, `SCHEDULED`, or `ACCESS_FAILED`; each assignment reprices the work order's `committed_amount_cents` to the contractor's `unit_price_cents`, recomputes the program budget, and bumps the work order's `version`.

A work order in `CREATED`, `NOTIFIED`, `SCHEDULED`, or `ACCESS_FAILED` may be cancelled by the `Scheduler`, provided no `OPEN` no-access case exists for it (`ERR_OPEN_NO_ACCESS_CASE`). Cancellation is terminal (`→ CANCELLED`) and shares one set of side effects regardless of the from-state: `committed_amount_cents` is zeroed, any appointment of the work order still `BOOKED` or `CONFIRMED` is moved to `SUPERSEDED`, the account returns to `ELIGIBLE` if no other open work order remains, the program budget is recomputed to release the commitment, and the work order's `version` increments.

### 3.4 Customer Contact: Notification, Scheduling, and No-Access Escalation

With a work order in `CREATED`, the `Scheduler` notifies the customer by creating a notification with the `work_order_id` and a `channel` of `USPS_MAIL`, `CERTIFIED_MAIL`, `DOOR_HANGER`, `PHONE`, or `EMAIL`; creation requires only that the work order exist — its lifecycle status is not checked. The notification starts `SENT` with `sent_at` stamped from the logical clock. Delivery is later confirmed by the `Scheduler` with an `outcome` of `DELIVERED`, `FAILED`, or `RETURNED`; a `DELIVERED` outcome also records the supplied `delivered_at` instant, defaulting to the current logical clock when `delivered_at` is omitted. The first notification of the work order to reach `DELIVERED` — on any channel — moves the work order `CREATED` → `NOTIFIED`.

Booking an appointment is a `Scheduler` action carrying `work_order_id`, the `slot_date` in YYYY-MM-DD form, a `window` of `AM`, `PM`, or `EVE`, and `expected_work_order_version`. Booking is legal from `NOTIFIED`, from `SCHEDULED` (re-booking), and from `ACCESS_FAILED` (re-booking after a failed visit), and in every case the same rules apply. The work order's `hold_status` must be `CLEAR`. The notice window must be satisfied: among the work order's notifications in `DELIVERED` status, the qualifying ones — for a `CRITICAL`-tier account, only `CERTIFIED_MAIL` deliveries qualify; for other tiers, every delivered notification qualifies — the latest `delivered_at` governs, and the `slot_date` must fall on or after that delivery's calendar date plus the program's `notice_days`, with a slot exactly `notice_days` after the latest qualifying delivery being valid (`ERR_NOTICE_WINDOW_NOT_MET`). Booking a `CRITICAL` account without any `DELIVERED` `CERTIFIED_MAIL` notification is refused outright with `ERR_CRITICAL_CHANNEL_REQUIRED`. The `slot_date` must not be earlier than the current logical-clock date (`ERR_APPOINTMENT_SLOT_PAST`). The assigned contractor must be `ACTIVE` (`ERR_CONTRACTOR_NOT_ACTIVE`) — a work order with no contractor assigned yet fails booking with the same error — and its crew bucket — the count of that contractor's appointments in `BOOKED` or `CONFIRMED` status on the same (`slot_date`, `window`) — must be strictly below `crew_capacity_per_window` (`ERR_CREW_WINDOW_FULL`). On success, any existing appointment of the work order in `BOOKED` or `CONFIRMED` is moved to `SUPERSEDED`, the new appointment starts `BOOKED` with `contractor_id` copied from the work order and an `attempt_number` one greater than the count of the work order's prior non-`SUPERSEDED` appointments, and the work order moves to `SCHEDULED`.

From `BOOKED`, a `CustomerService` confirmation moves the appointment to `CONFIRMED`. The assigned `FieldContractor` — and only that contractor, on pain of `ERR_CONTRACTOR_MISMATCH` — marks the visit `COMPLETED`, from either `BOOKED` or `CONFIRMED`. A customer cancellation, taken by the `Scheduler` or `CustomerService`, moves a `BOOKED` or `CONFIRMED` appointment to `CANCELLED_BY_CUSTOMER` and deliberately does not fire the work order's access-failure cascade: no strike is counted.

When the crew cannot get in, the assigned `FieldContractor` reports no-access on a `BOOKED` or `CONFIRMED` appointment. The appointment becomes `NO_ACCESS`, the work order's `no_access_strikes` increments by one, and the work order moves `SCHEDULED` → `ACCESS_FAILED`. The third strike is the escalation boundary: once `no_access_strikes` reaches at least three and no `OPEN` no-access case exists for the work order, the system opens a `NoAccessCase` in `OPEN` status at stage `STAGE_1_DOOR_HANGER`, recording `strikes_at_open` equal to the strike count, and immediately auto-creates the stage-one customer notification — `channel` `DOOR_HANGER`, status `SENT`, linked back to the case through `no_access_case_id`. At most one case per work order is `OPEN` at a time, and an `OPEN` case blocks both cancellation and closure of the work order with `ERR_OPEN_NO_ACCESS_CASE`.

The case then climbs a fixed four-stage ladder, each advance a `Scheduler` action gated on delivery evidence: advancing out of `STAGE_1_DOOR_HANGER` requires a `DELIVERED` notification linked to the case on the `DOOR_HANGER` channel, and lands in `STAGE_2_CERTIFIED_MAIL` with an auto-created `CERTIFIED_MAIL` notification; advancing out of `STAGE_2_CERTIFIED_MAIL` requires the `CERTIFIED_MAIL` notification `DELIVERED`, and lands in `STAGE_3_PHONE_CAMPAIGN` with an auto-created `PHONE` notification; advancing out of `STAGE_3_PHONE_CAMPAIGN` requires the `PHONE` notification `DELIVERED` and lands in `STAGE_4_FIELD_VISIT`, which auto-creates no notification. `STAGE_4_FIELD_VISIT` is the top of the ladder: advancing from it is rejected with `ERR_INVALID_STATE`. Any advance without the current stage's delivered notification is refused with `ERR_ESCALATION_STEP_REQUIRED`. Resolution by the `Scheduler` closes the case into `RESOLVED` with a `resolution` of `ACCESS_GAINED`, `ACCOUNT_EXEMPTED`, or `FORCED_ENTRY` — the last permitted only from `STAGE_4_FIELD_VISIT`, earlier attempts failing with `ERR_FORCED_ENTRY_NOT_AUTHORIZED`. A resolution of `ACCOUNT_EXEMPTED` additionally cancels the work order with the full shared cancellation side effects of Section 3.3 and moves the account `IN_PROGRAM` → `EXEMPTED`.

### 3.5 Field Execution: Swap, Readings, and Reconciliation

The physical change-out happens at a completed visit. The assigned `FieldContractor` records the swap on a `SCHEDULED` work order whose `hold_status` is `CLEAR` and which has an appointment in `COMPLETED` status, supplying `expected_work_order_version`, the `new_meter_id`, the `final_read_value` off the old meter, and the `initial_read_value` off the new meter. The new meter must be `IN_STOCK` and of `AMI` technology (`ERR_METER_NOT_AVAILABLE`); the `final_read_value` must be no less than the account's `last_billed_read_value` (`ERR_READING_SEQUENCE_INVALID`); and the `initial_read_value` must not exceed one CCF, the factory ceiling for a new register (`ERR_READING_SEQUENCE_INVALID`). The swap then lands its full cascade at once: the old meter moves `INSTALLED` → `REMOVED` with its `service_account_id` cleared; the new meter moves `IN_STOCK` → `INSTALLED` with `service_account_id` set to the account and `installed_read_value` set to the declared `initial_read_value`; the work order records `new_meter_id`; the account moves `IN_PROGRAM` → `REPLACED`; and the work order moves `SCHEDULED` → `SWAPPED`.

At swap time a provisional true-up is booked into `provisional_trueup_cents` using the prorated estimate variant: the whole days elapsed between the account's `last_billed_read_at` and the swap's clock timestamp are multiplied by the account's `avg_daily_usage_ccf`, the product is rounded half up to two decimal places to give the estimated usage in CCF, and that usage is multiplied by the program's `rate_per_ccf_cents` and rounded half up to whole cents.

The swap payload's read values are the crew's declared figures; the billing-grade evidence arrives as meter readings. Readings are append-only events — the `FieldContractor` or the `Scheduler` appends one with `work_order_id`, `meter_id`, a `read_type` of `FINAL`, `INITIAL`, `VERIFICATION`, or `ESTIMATED`, the register `value` in CCF (zero or greater), a `source` of `FIELD_CREW`, `AMI_NETWORK`, `CUSTOMER`, or `SYSTEM_ESTIMATE`, and the `read_at` instant the read was taken. A `FINAL` reading for the old meter and an `INITIAL` reading for the new meter are both mandatory before reconciliation.

Reconciliation, again by the assigned `FieldContractor` with `expected_work_order_version`, requires those two readings to exist (`ERR_RECONCILE_READINGS_INCOMPLETE`) and moves the work order `SWAPPED` → `RECONCILED`. It books the measured-variant true-up into `trueup_amount_cents`: measured usage is the swap call's declared `final_read_value` (not the `FINAL` reading's value) minus the account's `last_billed_read_value`, and that usage multiplied by `rate_per_ccf_cents`, rounded half up to whole cents, is the measured true-up. The `trueup_delta_cents` booked alongside is the measured true-up minus the provisional true-up — a negative delta means the prorated estimate overcharged the customer and the difference comes back as a credit.

### 3.6 AMI Endpoint Registration and Communication Verification

Once a work order is `RECONCILED`, the `AmiOperator` registers its AMI endpoint by supplying the `work_order_id` and the `endpoint_serial`, unique across all registrations (`ERR_AMI_ENDPOINT_SERIAL_CONFLICT`). At most one registration per work order may be outside `REPLACED` status at a time — a second live registration is refused with `ERR_INVALID_STATE`. The registration copies the work order's `new_meter_id` into its `meter_id`, stamps `registered_at` from the logical clock, starts its `reads_received_count` and `rssi_sum_dbm` counters at zero, and enters `REGISTERED` status.

Network traffic is fed in through an `AmiOperator`-only ingest capability that takes the `endpoint_registration_id`, the signal strength `rssi_dbm`, and the `read_at` instant, incrementing `reads_received_count` by one and adding `rssi_dbm` into `rssi_sum_dbm`.

Verification evaluates a fixed threshold over the seventy-two-hour window that opens at `registered_at`: reads whose `read_at` falls no earlier than `registered_at` and no later than seventy-two hours after it — both bounds inclusive — count toward the window. Communication is verified when the window holds at least four reads and the average signal strength across them is −95 dBm or stronger, with the average computed exactly, without rounding; the boundary is inclusive, so exactly four reads at exactly −95 dBm passes. A passing verification moves the registration `REGISTERED` → `COMM_VERIFIED` and chains the work order `RECONCILED` → `AMI_VERIFIED` → `QA_REVIEW` in one automatic sequence. The arrival into `QA_REVIEW` drives audit sampling: if the count of this contractor's work orders that have entered `QA_REVIEW`, including this one, is a multiple of five (each work order counting once, however many times it enters `QA_REVIEW`), the system auto-creates a `SAMPLED` quality audit in `PENDING` status with the `contractor_id` copied from the work order. A failing verification moves the registration `REGISTERED` → `COMM_FAILED` with no work-order effect.

A `COMM_FAILED` endpoint is replaced by the `AmiOperator` supplying a `new_endpoint_serial`, which must also be globally unique (`ERR_AMI_ENDPOINT_SERIAL_CONFLICT`). The old registration moves to `REPLACED`, and a fresh registration is created for the same work order in `REGISTERED` status with `registered_at` restamped from the clock and both counters reset.

### 3.7 Field Quality Audits, Rework, and Work Order Close-Out

Quality oversight on completed work is split from the crews that performed it. Beyond the auto-created audits of Section 3.6, a `QualityAuditor` may raise an audit against a work order sitting in `QA_REVIEW` or `QA_FAILED`, supplying the `work_order_id` and an `audit_type` — `SAMPLED` audits are the auto-created ones, so naming `SAMPLED` on a manual create is refused with `ERR_VALIDATION`, while manually raised audits use `FOR_CAUSE`. Either way the audit copies `contractor_id` from the work order and starts `PENDING`, with `checks_total`, `checks_passed`, `defects_found`, and `recorded_at` unset until the audit is recorded.

Recording the audit supplies `checks_total` (at least one), `checks_passed`, and `defects_found` (both zero or greater). The audit passes — `result_status` `PASS` — only when `defects_found` is zero and `checks_passed` equals `checks_total`; any shortfall records `FAIL`. Either verdict stamps `recorded_at` from the logical clock and triggers a recomputation of the contractor's quality score: over the contractor's latest twenty recorded audits, ordered by `recorded_at` descending with ties broken by `created_at` ascending (any remaining ties by insertion order), the score `quality_score_bp` is 10,000 basis points minus 400 basis points for each `FAIL` in that window, floored at zero — so a passing record can raise the score by evicting an old failure from the window — while `audits_failed_count` counts every recorded `FAIL` audit of the contractor without any window. A recorded `FAIL` also cascades: the work order moves `QA_REVIEW` → `QA_FAILED`, and if the recomputed score has dropped below 9,200 basis points while the contractor is `ACTIVE`, the contractor is auto-suspended to `SUSPENDED`, which immediately blocks future appointment booking for its crews per Sections 3.2 and 3.4.

Rework after a failed audit is the assigned `FieldContractor` submitting the work order back with `expected_work_order_version`, moving it `QA_FAILED` → `QA_REVIEW` for a fresh review.

Close-out is the `Scheduler`'s final action on a work order in `QA_REVIEW`, and it is gated on a clean ledger: the work order's `hold_status` must be `CLEAR` (otherwise `ERR_INVALID_STATE`), no quality audit of the work order may remain `PENDING` (otherwise `ERR_INVALID_STATE`), no high-bill complaint of the work order may sit in `FILED`, `UNDER_REVIEW`, or `BENCH_TEST_ORDERED` (`ERR_OPEN_COMPLAINT_EXISTS`), and no no-access case may be `OPEN` (`ERR_OPEN_NO_ACCESS_CASE`). A successful close moves the work order `QA_REVIEW` → `CLOSED`, stamps `closed_at` from the logical clock, zeroes `committed_amount_cents` to release the commitment, and recomputes the program's budget figures and `completed_meter_count`.

### 3.8 Bench Testing and High-Bill Complaint Adjudication

A bench test measures a removed meter against the metrology lab's known volumes. The `QualityAuditor` records a test for a meter in `REMOVED` status (`ERR_METER_NOT_AVAILABLE` otherwise), optionally naming the `work_order_id` of the change-out that removed it and a `complaint_id` when the test was ordered for a dispute, and supplies the three volumes the meter registered: `measured_low_ccf`, `measured_mid_ccf`, and `measured_high_ccf`. Computation is synchronous at creation, stamped with `tested_at` from the logical clock, and follows a pinned rounding order — each per-flow accuracy is rounded first, and only then are the rounded figures weighted. The known test volumes are 2 CCF at low flow, 20 CCF at mid flow, and 30 CCF at high flow: `accuracy_low_pct` is the measured low volume divided by 2, times one hundred, rounded half up to two decimal places; `accuracy_mid_pct` the same against 20; `accuracy_high_pct` the same against 30. The `weighted_accuracy_pct` is then twenty percent of `accuracy_low_pct` plus thirty percent of `accuracy_mid_pct` plus fifty percent of `accuracy_high_pct`, rounded half up to two decimal places. The `result` is a two-sided band verdict: `PASS` only when `weighted_accuracy_pct` is at least 98.5 and at most 101.5 and `accuracy_low_pct` is at least 95.0 and at most 105.0; anything outside either bound is a `FAIL`, so over-registration fails just as under-registration does. The verdict moves the meter to `BENCH_PASSED` or `BENCH_FAILED`, and when the test was ordered for a complaint, the complaint is linked through `bench_test_id` and returns `BENCH_TEST_ORDERED` → `UNDER_REVIEW`.

Customers dispute post-swap bills through the `CustomerService` desk. Filing a complaint names the `service_account_id`, the `work_order_id` of the change-out preceding the disputed bill, the `claimed_bill_cents` (zero or greater), the `baseline_bill_cents` from billing history for the same period (strictly positive), and the disputed period from `billing_period_start` inclusive to `billing_period_end` exclusive, both ISO 8601 instants accepted as supplied with no ordering check between them. The work order must be `SWAPPED` or later in its lifecycle (`ERR_INVALID_STATE`), the complaint's account must be the work order's own account (`ERR_ACCOUNT_WORK_ORDER_MISMATCH`), and no other open complaint may exist on the work order (`ERR_OPEN_COMPLAINT_EXISTS`). At filing the `variance_pct` is computed as the claimed bill minus the baseline, divided by the baseline, times one hundred, rounded half up to two decimal places, and a variance below 25 percent is refused with `ERR_COMPLAINT_VARIANCE_BELOW_THRESHOLD`. Filing also flips the work order's parallel hold dimension: while `hold_status` is `CLEAR`, a new `FILED` complaint moves it to `ON_HOLD`, and an `ON_HOLD` work order cannot be booked, swapped, or closed until the hold clears.

Triage moves a complaint `FILED` → `UNDER_REVIEW`. When meter accuracy is in question, the desk orders a bench test — legal only while the work order's old meter is `REMOVED` (`ERR_METER_NOT_AVAILABLE`) — moving the complaint `UNDER_REVIEW` → `BENCH_TEST_ORDERED`, from which the recorded bench test returns it to `UNDER_REVIEW` as described above. Adjudication carries a `decision` of `ADJUSTED` or `DENIED`. A denial simply moves the complaint to `DENIED`. An adjustment computes `adjustment_cents` and records which `adjudication_variant` produced it, in a pinned evaluation order: the variance is computed at filing; then, if a bench test linked to the complaint — one naming the complaint in its own `complaint_id`, or the one referenced by the complaint's `bench_test_id` — recorded `FAIL`, the `REGISTRATION_ERROR` variant applies — the claimed bill is multiplied by one hundred, divided by the test's `weighted_accuracy_pct`, and rounded half up to whole cents to recover what the bill would have been at perfect registration, and the adjustment is the claimed bill minus that amount. Otherwise the `GOODWILL_TIERED` variant applies: the excess of `claimed_bill_cents` over `baseline_bill_cents` is credited at a tiered rate on the variance — ten percent when the variance is at least 25 and below 50, twenty percent when at least 50 and below 100, thirty percent when at least 100 — with the product rounded half up to whole cents. Note the gate this creates: adjudicating `ADJUSTED` on a complaint whose `variance_pct` is 50 or greater requires a linked `FAIL` bench test, failing with `ERR_BENCH_TEST_REQUIRED` otherwise. Withdrawal by `CustomerService` is permitted from `FILED`, from `UNDER_REVIEW`, and from `BENCH_TEST_ORDERED`, each moving the complaint to `WITHDRAWN`.

`ADJUSTED`, `DENIED`, and `WITHDRAWN` are all terminal, and each releases the hold dimension: when a complaint reaching one of those states was the work order's last open complaint, `hold_status` moves `ON_HOLD` → `CLEAR`, unblocking booking, swap, and close.

### 3.9 Contractor Invoicing and Settlement

Payment runs on invoices the contractor raises for a billing window. A `FieldContractor` creates an invoice in `DRAFT` with its own `contractor_id` — which must match its `X-User-ID` identity, on pain of `ERR_CONTRACTOR_MISMATCH` — plus the `period_start` (inclusive) and `period_end` (exclusive), both ISO 8601 instants accepted as supplied with no ordering check between them; the `program_id` is copied from the contractor. No amounts exist on a draft: the whole settlement is computed and frozen at submit time.

Submitting — from `DRAFT`, or again from `DISPUTED` after a program-manager dispute — re-runs the full settlement against the submit instant and freezes every figure. The `units_completed` is the count of the contractor's work orders in `CLOSED` whose `closed_at` falls on or after `period_start` and strictly before `period_end`; a period yielding zero units is refused with `ERR_INVOICE_PERIOD_EMPTY`. The `gross_amount_cents` is `units_completed` times the contractor's `unit_price_cents`. The `bonus_cents` is two percent of the gross, rounded half up to whole cents, when the contractor's `quality_score_bp` at submit is at least 9,800 basis points, and zero otherwise. The penalty counts the contractor's `FAIL` audits whose `recorded_at` falls in the same half-open period: `penalty_cents` is the smaller of that failure count times one percent of the gross (rounded half up to whole cents) and ten percent of the gross (rounded half up to whole cents). The `retainage_cents` is ten percent of the gross, rounded half up to whole cents, when the contractor is `SUSPENDED` at submit, and five percent of the gross otherwise. The `net_amount_cents` is then the gross plus the bonus minus the penalty minus the retainage. Submitting moves the invoice to `SUBMITTED`.

The `ProgramManager` then settles or contests. Approval requires the invoice's `net_amount_cents` to be no greater than the program's `budget_available_cents`, with equality allowed — a shortfall is refused with `ERR_BUDGET_AVAILABLE_EXCEEDED` — and on approval the invoice moves `SUBMITTED` → `APPROVED`, its net is added into the program's `budget_spent_cents`, and the budget posture is recomputed. A dispute moves `SUBMITTED` → `DISPUTED` and records the supplied `reason` in `dispute_reason`; the contractor's remedy is to correct and resubmit, and a resubmitted invoice retains its prior `dispute_reason`. `APPROVED` is the invoice's terminal state, and a program cannot close while any invoice stands short of it.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the created resource; action endpoints that transition or modify an existing resource return HTTP 200 with the updated resource; list and detail reads return HTTP 200. Request and response payloads are exactly as described in Sections 2 and 3 — the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/programs | Create program (status `PLANNING`) | ProgramManager |
| GET | /api/programs | List programs (paginated) | All six roles |
| GET | /api/programs/{programId} | Get program | All six roles |
| POST | /api/programs/{programId}/activate | `PLANNING` → `ACTIVE` | ProgramManager |
| POST | /api/programs/{programId}/begin-closing | `ACTIVE` → `CLOSING` (all waves terminal) | ProgramManager |
| POST | /api/programs/{programId}/close | `CLOSING` → `CLOSED` (all invoices `APPROVED`) | ProgramManager |
| GET | /api/programs/{programId}/completion-report | Completion/budget report with both forecast variants | ProgramManager |
| POST | /api/contractors | Onboard contractor (status `ACTIVE`; program must be `ACTIVE`) | ProgramManager |
| GET | /api/contractors | List contractors | All six roles |
| GET | /api/contractors/{contractorId} | Get contractor | All six roles |
| POST | /api/contractors/{contractorId}/suspend | `ACTIVE` → `SUSPENDED` | ProgramManager |
| POST | /api/contractors/{contractorId}/reinstate | `SUSPENDED` → `ACTIVE` | ProgramManager |
| POST | /api/accounts | Register premise (status `ELIGIBLE`) | Scheduler |
| GET | /api/accounts | List accounts | All six roles |
| GET | /api/accounts/{accountId} | Get account | All six roles |
| POST | /api/meters | Register meter in stock (`IN_STOCK`) | Scheduler |
| GET | /api/meters | List meters | All six roles |
| GET | /api/meters/{meterId} | Get meter | All six roles |
| POST | /api/meters/{meterId}/install | Legacy baseline install onto account (`IN_STOCK` → `INSTALLED`) | Scheduler |
| POST | /api/meters/{meterId}/dispose | `BENCH_PASSED` → `DISPOSED`; `BENCH_FAILED` → `RETURNED_TO_VENDOR` | Scheduler |
| POST | /api/waves | Create wave (`DRAFT`) | ProgramManager |
| GET | /api/waves | List waves | All six roles |
| GET | /api/waves/{waveId} | Get wave | All six roles |
| POST | /api/waves/{waveId}/open | `DRAFT` → `OPEN` (window non-overlap, program `ACTIVE`) | ProgramManager |
| POST | /api/waves/{waveId}/lock | `OPEN` → `LOCKED` (commitment within budget, equality allowed) | ProgramManager |
| POST | /api/waves/{waveId}/complete | `LOCKED` → `COMPLETE` (all work orders terminal) | ProgramManager |
| POST | /api/waves/{waveId}/cancel | `DRAFT`/`OPEN` → `CANCELLED` (no live work orders) | ProgramManager |
| POST | /api/work-orders | Create change-out work order in an `OPEN` wave; captures `old_meter_id`; commits default allowance | Scheduler |
| GET | /api/work-orders | List work orders | All six roles |
| GET | /api/work-orders/{workOrderId} | Get work order | All six roles |
| POST | /api/work-orders/{workOrderId}/assign | Assign/re-assign contractor (OCC); reprices commitment to `unit_price_cents` | Scheduler |
| POST | /api/work-orders/{workOrderId}/swap | Record physical swap with final/initial reads (OCC); cascades meters, true-up, account | FieldContractor |
| POST | /api/work-orders/{workOrderId}/reconcile | `SWAPPED` → `RECONCILED`; measured true-up and delta booked (OCC) | FieldContractor |
| POST | /api/work-orders/{workOrderId}/submit-rework | `QA_FAILED` → `QA_REVIEW` after corrective work (OCC) | FieldContractor |
| POST | /api/work-orders/{workOrderId}/close | `QA_REVIEW` → `CLOSED` (hold clear, no pending audit, no open complaint/case) | Scheduler |
| POST | /api/work-orders/{workOrderId}/cancel | `CREATED`/`NOTIFIED`/`SCHEDULED`/`ACCESS_FAILED` → `CANCELLED` | Scheduler |
| POST | /api/notifications | Send customer notification (status `SENT`) | Scheduler |
| POST | /api/notifications/{notificationId}/confirm-delivery | Vendor delivery callback: `DELIVERED` / `FAILED` / `RETURNED` | Scheduler |
| GET | /api/notifications | List notifications | All six roles |
| GET | /api/notifications/{notificationId} | Get notification | All six roles |
| POST | /api/appointments | Book appointment (OCC on work order); supersedes existing `BOOKED`/`CONFIRMED` | Scheduler |
| GET | /api/appointments | List appointments | All six roles |
| GET | /api/appointments/{appointmentId} | Get appointment | All six roles |
| POST | /api/appointments/{appointmentId}/confirm | `BOOKED` → `CONFIRMED` (customer confirmation via CSR) | CustomerService |
| POST | /api/appointments/{appointmentId}/complete | `BOOKED`/`CONFIRMED` → `COMPLETED` (owning crew) | FieldContractor |
| POST | /api/appointments/{appointmentId}/no-access | `BOOKED`/`CONFIRMED` → `NO_ACCESS`; strike cascade on work order | FieldContractor |
| POST | /api/appointments/{appointmentId}/cancel | `BOOKED`/`CONFIRMED` → `CANCELLED_BY_CUSTOMER` (no strike) | Scheduler, CustomerService |
| GET | /api/no-access-cases | List no-access cases | All six roles |
| GET | /api/no-access-cases/{caseId} | Get no-access case | All six roles |
| POST | /api/no-access-cases/{caseId}/advance | Advance escalation stage (current stage notification must be `DELIVERED`) | Scheduler |
| POST | /api/no-access-cases/{caseId}/resolve | Resolve case (`FORCED_ENTRY` only at `STAGE_4_FIELD_VISIT`) | Scheduler |
| POST | /api/readings | Append a meter reading (append-only) | FieldContractor, Scheduler |
| GET | /api/readings | List readings | All six roles |
| GET | /api/readings/{readingId} | Get reading | All six roles |
| POST | /api/endpoint-registrations | Register AMI endpoint for a `RECONCILED` work order | AmiOperator |
| GET | /api/endpoint-registrations | List endpoint registrations | All six roles |
| GET | /api/endpoint-registrations/{registrationId} | Get endpoint registration | All six roles |
| POST | /api/endpoint-registrations/{registrationId}/verify | Run communication threshold → `COMM_VERIFIED` / `COMM_FAILED` | AmiOperator |
| POST | /api/endpoint-registrations/{registrationId}/replace | `COMM_FAILED` → `REPLACED`; creates successor registration (201) | AmiOperator |
| POST | /api/_ami/ingest-read | Test-driving endpoint: ingest one AMI network read for a registration | AmiOperator |
| POST | /api/bench-tests | Record bench test of a `REMOVED` meter; computes accuracies and result | QualityAuditor |
| GET | /api/bench-tests | List bench tests | All six roles |
| GET | /api/bench-tests/{benchTestId} | Get bench test | All six roles |
| POST | /api/complaints | File high-bill complaint (variance at least 25%; work order `SWAPPED` or later; one open per work order) | CustomerService |
| GET | /api/complaints | List complaints | All six roles |
| GET | /api/complaints/{complaintId} | Get complaint | All six roles |
| POST | /api/complaints/{complaintId}/triage | `FILED` → `UNDER_REVIEW` | CustomerService |
| POST | /api/complaints/{complaintId}/order-bench-test | `UNDER_REVIEW` → `BENCH_TEST_ORDERED` (old meter must be `REMOVED`) | CustomerService |
| POST | /api/complaints/{complaintId}/adjudicate | `UNDER_REVIEW` → `ADJUSTED` / `DENIED`; computes adjustment | CustomerService |
| POST | /api/complaints/{complaintId}/withdraw | `FILED`/`UNDER_REVIEW`/`BENCH_TEST_ORDERED` → `WITHDRAWN` | CustomerService |
| POST | /api/quality-audits | Create `FOR_CAUSE` audit for a work order in `QA_REVIEW`/`QA_FAILED` | QualityAuditor |
| GET | /api/quality-audits | List quality audits | All six roles |
| GET | /api/quality-audits/{auditId} | Get quality audit | All six roles |
| POST | /api/quality-audits/{auditId}/record | `PENDING` → `PASS` / `FAIL`; `FAIL` cascades to work order and contractor | QualityAuditor |
| POST | /api/invoices | Create `DRAFT` invoice for a period (amounts computed at submit) | FieldContractor |
| GET | /api/invoices | List invoices | All six roles |
| GET | /api/invoices/{invoiceId} | Get invoice | All six roles |
| POST | /api/invoices/{invoiceId}/submit | `DRAFT`/`DISPUTED` → `SUBMITTED`; settlement computed and frozen | FieldContractor |
| POST | /api/invoices/{invoiceId}/approve | `SUBMITTED` → `APPROVED`; budget check (equality allowed); debits program spent | ProgramManager |
| POST | /api/invoices/{invoiceId}/dispute | `SUBMITTED` → `DISPUTED` with reason | ProgramManager |
| POST | /api/_clock/set_current_utc | Set the logical clock (ISO 8601 UTC); startup default 2026-05-01T00:00:00Z | ProgramManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of Sections 2 and 3; this table is the identifier-to-status reference.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_CONTRACTOR_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_ACCOUNT_NUMBER_CONFLICT | 409 |
| ERR_METER_SERIAL_CONFLICT | 409 |
| ERR_AMI_ENDPOINT_SERIAL_CONFLICT | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_WORK_ORDER_VERSION | 412 |
| ERR_PROGRAM_NOT_ACTIVE | 422 |
| ERR_CRITICAL_CHANNEL_REQUIRED | 422 |
| ERR_FORCED_ENTRY_NOT_AUTHORIZED | 422 |
| ERR_BENCH_TEST_REQUIRED | 422 |
| ERR_NOTICE_WINDOW_NOT_MET | 422 |
| ERR_APPOINTMENT_SLOT_PAST | 422 |
| ERR_WAVE_WINDOW_OVERLAP | 409 |
| ERR_CREW_WINDOW_FULL | 409 |
| ERR_WAVE_CAPACITY_EXCEEDED | 422 |
| ERR_ACCOUNT_ALREADY_IN_PROGRAM | 409 |
| ERR_OPEN_COMPLAINT_EXISTS | 409 |
| ERR_OPEN_NO_ACCESS_CASE | 409 |
| ERR_ESCALATION_STEP_REQUIRED | 422 |
| ERR_CONTRACTOR_NOT_ACTIVE | 422 |
| ERR_CROSS_PROGRAM_REFERENCE | 422 |
| ERR_ACCOUNT_WORK_ORDER_MISMATCH | 422 |
| ERR_METER_NOT_AVAILABLE | 422 |
| ERR_READING_SEQUENCE_INVALID | 422 |
| ERR_RECONCILE_READINGS_INCOMPLETE | 422 |
| ERR_COMPLAINT_VARIANCE_BELOW_THRESHOLD | 422 |
| ERR_BUDGET_COMMITMENT_EXCEEDED | 422 |
| ERR_BUDGET_AVAILABLE_EXCEEDED | 422 |
| ERR_INVOICE_PERIOD_EMPTY | 422 |
| ERR_INTERNAL | 500 |
