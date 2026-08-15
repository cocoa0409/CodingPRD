# Aircraft Management & Owner Services API — Product Requirements Document

## 1. Introduction

Aircraft owners who place their jets under professional management expect two things from the management company: operational excellence and financial transparency. The owner wants a clear monthly operating statement, an annual budget that is proposed and ratified in a controlled fashion, crew that are trained and legally dispatched, a maintenance program whose accruals and forecasts stay ahead of the airframe, and — when the relationship ends — a clean, auditable handover of every maintenance and compliance record. The management company, meanwhile, must segregate duties across its own staff so that the person who prepares a statement is never the person who certifies it, and so that owner-scoped approvals (budgets, charter trips) can only be exercised by the owner of record.

This document specifies a REST API for an Aircraft Management & Owner Services platform in the style of a Jet Aviation-class manager. The platform covers the full commercial relationship: onboarding the owner and registering airframes; negotiating and activating the management agreement; drafting and approving the annual operating budget; hiring, training, and rostering the dedicated crew; requesting, approving, scheduling, and completing trips (both owner-use and revenue charter); forecasting recurring maintenance events and accruing hourly program costs; filing insurance and regulatory paperwork; negotiating hangar and fuel vendor contracts; and producing the monthly owner statement in which accrual-basis and cash-basis totals, the management fee, the charter revenue offset, the budget variance, and the owner-versus-charter tax split are all pinned to precise arithmetic.

A central design commitment is that the owner statement is a reconciliation artifact, not a report to be eyeballed. Every number on it is derivable from posted expenses, completed trips, and the agreement's commercial terms — and the system enforces that derivation at certification time. The document first establishes system-wide contracts (identity, response envelope, pagination, precision, optimistic concurrency, validation ordering), then walks each business workflow in narrative form, and finally summarizes the HTTP endpoint surface and the error code catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. If either header is absent, or if the role value is not one of the declared roles below, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the acting role is not listed among an endpoint's authorized roles, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Owner-scoped actions additionally compare `X-User-ID` to the owning entity as described below; a mismatch there is also `ERR_FORBIDDEN_ROLE`.

The declared roles are exactly: `Owner`, `AccountExecutive`, `FlightOpsManager`, `MaintenancePlanner`, `FinanceController`, `ComplianceOfficer`, `ContractsManager`, and `PlatformAdmin`.

Role identity semantics are as follows. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner`; owner-scoped checks (budget approve/reject, charter trip approve/decline) compare the acting `X-User-ID` against the `owner_id` of the `ManagementAgreement` attached to the aircraft in question — a non-owner caller is refused with `ERR_FORBIDDEN_ROLE`. When `X-User-Role` is any of `AccountExecutive`, `FlightOpsManager`, `MaintenancePlanner`, `FinanceController`, `ComplianceOfficer`, `ContractsManager`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `prepared_by_user_id` or `certified_by_user_id` on a `MonthlyStatement`) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10; the minimum accepted value is 1 and the maximum is 100. The default `offset` is 0. Results are always sorted by `created_at` ascending. The `meta` block of a list response carries four pagination fields — `limit`, `offset`, `total_count`, and `has_more` — alongside the standard `api_request_id` and `api_request_timestamp`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id`, which is a UUID with no type prefix. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits. Resources whose lifecycle admits mutation additionally carry `updated_at` (same timestamp format) and an integer `version` that starts at the value set at creation and increments by 1 on every state transition or terms amendment that the platform performs on that resource. In this domain all entities — `Owner`, `Aircraft`, `ManagementAgreement`, `OperatingBudget`, `Expense`, `MonthlyStatement`, `CrewMember`, `TripRequest`, `DutyAssignment`, `MaintenanceProgram`, `MaintenanceEvent`, `ComplianceFiling`, and `VendorContract` — carry the full common set of `id`, `created_at`, `updated_at`, and `version`; there are no entities that omit `updated_at` and `version`.

### 2.5. The Logical Clock

All server-side timestamps — `notice_given_at`, `filed_at`, `completed_at`, `certified_by_user_id`-stamping, and every "now" used in duty-window and overdue evaluation — read from a logical clock, never from the wall clock. Before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. A `PlatformAdmin` may advance the logical clock to a supplied instant via a test-driving capability; the request body carries the target instant in `to_iso8601`, and the response echoes the new clock reading as `current_utc`.

### 2.6. Monetary Precision and Rounding

All money amounts are integer cents; no sub-cent arithmetic is ever performed. Percentages such as `variable_fee_pct` and `charter_owner_share_pct` are carried as fractions (for example, 0.10 means ten percent). Wherever a calculation must round — the variable component of the management fee, the monthly share of an annual budget, the owner credit on a completed charter, and each line of the mixed-expense tax split — the rule is round half up to the nearest integer cent. Duty-hour accumulators are kept at 2 decimal places with round half up applied per assignment. Airframe-hour arithmetic is exact on its inputs and is expressed to at least one decimal place.

### 2.7. Optimistic Concurrency Control on Agreement Terms

Exactly one write endpoint participates in optimistic concurrency control: amending the commercial terms of a `ManagementAgreement`. The request must carry `expected_agreement_version`, holding the `version` of the agreement the client last observed. If that value does not equal the agreement's current `version` — meaning another writer has advanced the agreement since the client last read it — the amendment is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412); the client's view of the fee and revenue-share terms is stale, so the amendment is refused rather than silently overwriting newer terms. A successful amendment increments the agreement's `version` by 1. Endpoints not named in this rule do not take a version field.

### 2.8. Validation Ordering

When a request fails for more than one reason, the error the caller sees is determined by a fixed priority order, evaluated top to bottom. First, the user-context headers are checked (§2.1). Second, role authorization and owner-scoping are checked. Third, every path identifier and every body-supplied foreign-key reference — `owner_id`, `aircraft_id`, `trip_id`, `crew_member_id`, the entries of `record_ids`, and so on — must resolve to an existing resource, validated left-to-right along the path; any unresolved reference yields `ERR_NOT_FOUND` (HTTP 404). Fourth, request schema is enforced: required fields present, enum values valid, ISO dates parseable, `amount_cents` strictly greater than zero, `block_hours_est` strictly greater than zero, rates non-negative, `duty_start_at` strictly earlier than `duty_end_at`, `term_start` strictly earlier than `term_end`, and `period` matching the YYYY-MM shape; violations yield `ERR_VALIDATION` (HTTP 400). Only after all four of those gates pass do state-machine preconditions, business-safety gates, temporal gates, uniqueness constraints, fiscal staleness checks, and finally the OCC stale-version check run, in that order. Within the trip-scheduling gate stack specifically, the agreement-status check runs first, then the maintenance-overdue check, then the insurance-currency check, then the crew-complement check, and finally the aircraft-overlap check. Within the assignment gate stack, the crew-member-qualified check runs first, then the duty-limit check, then the duty-overlap check.

### 2.9. Nested Resource Retrieval

Several list endpoints are nested under a parent path segment — budgets, statements, crew, trips, programs, filings, and contracts are all listed under the aircraft that owns them. Path identifiers are validated left-to-right: an unresolved parent id produces `ERR_NOT_FOUND` before the child collection is ever consulted. Standalone list endpoints that accept query filters (`aircraft_id`, `statement_id`, `trip_id`, `status`, `category`, `previous_event_id`, `crew_member_id`, `owner_id`) treat each supplied filter as an equality match; a filter value that does not resolve to an existing resource likewise yields `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Onboarding Owners, Aircraft, and the Management Agreement

An `AccountExecutive` onboards a new aircraft owner by supplying the owner's `legal_name` and `contact_email`. The same role then registers airframes under that owner, each registration carrying the owning `owner_id`, the `tail_number`, the `model` designation, and the `home_base_icao` of its home airport. The `tail_number` must be unique across every registered aircraft; a duplicate is rejected with `ERR_TAIL_NUMBER_EXISTS`. Each aircraft also carries a read-only `total_time_hours`, which starts at zero and accumulates as trips complete.

With an owner and an airframe in place, the `AccountExecutive` drafts the management agreement — the commercial heart of the relationship. The creation payload names the `owner_id` and `aircraft_id` together with the commercial terms: `monthly_management_fee_cents` (a flat fee billed on every monthly statement), `variable_fee_pct` (the fraction of the pre-fee accrual subtotal added to the monthly fee), `charter_owner_share_pct` (the fraction of net charter revenue credited back to the owner), and `tax_allocation_method`, which is either `FLIGHT_HOURS` or `TRIP_LEGS` and governs how mixed-use expenses are split. An agreement is born in `PENDING` status. At most one agreement per aircraft may be live — that is, in `PENDING`, `ACTIVE`, `TERMINATION_PENDING`, or `HANDOVER_IN_PROGRESS`; attempting to create a second live agreement for the same aircraft is rejected with `ERR_AGREEMENT_CONFLICT_EXISTS`.

Activation moves the agreement from `PENDING` to `ACTIVE`, increments its `version` by 1, and is performed by an `AccountExecutive`. While `ACTIVE`, the commercial terms may be amended — `monthly_management_fee_cents`, `variable_fee_pct`, `charter_owner_share_pct`, and `tax_allocation_method` are each individually optional in the amendment payload — but the amendment is guarded by the optimistic-concurrency rule of §2.7 and requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_INVALID_STATE` otherwise). A successful amendment also increments the agreement's `version` by 1.

### 3.2. The Annual Operating Budget

For each fiscal year, the `AccountExecutive` drafts an `OperatingBudget` against an aircraft, supplying `aircraft_id`, the four-digit `fiscal_year`, and six annual cost lines in cents: `fuel_cents`, `maintenance_cents`, `crew_cents`, `hangar_cents`, `insurance_cents`, and `other_cents`. At most one budget may exist per aircraft and fiscal year; a duplicate is rejected with `ERR_BUDGET_YEAR_EXISTS`. A new budget starts in `DRAFT` status.

Submission moves the budget from `DRAFT` to `SUBMITTED` and is performed by the `AccountExecutive`. The owner then decides: approval moves the budget to `APPROVED`; rejection moves it to `REJECTED` and records the owner-supplied `reason` in the budget's `rejection_reason`. Both owner actions are owner-scoped: the acting `X-User-ID` must equal the `owner_id` on the aircraft's agreement, or the call is refused with `ERR_FORBIDDEN_ROLE`. Approve and reject both require the budget to be `SUBMITTED`; otherwise `ERR_BUDGET_INVALID_STATE`.

A `REJECTED` budget is not terminal. When the `AccountExecutive` revises any of the six amount fields, the budget reopens: the supplied amounts replace the stored ones, `rejection_reason` is cleared, and the budget returns to `DRAFT`, ready to be submitted again. Revision is permitted only from `DRAFT` or `REJECTED`.

### 3.3. Crew Hiring, Training, and Duty Limits

The `FlightOpsManager` hires crew for a specific aircraft by supplying `aircraft_id`, the crew member's `full_name`, the `crew_role` (`CAPTAIN` or `FIRST_OFFICER`), and the `hire_date`. Crew are dedicated to exactly one managed aircraft. A new crew member starts in `HIRED` status with `training_hours_accumulated` at zero.

Beginning training moves the crew member from `HIRED` to `IN_TRAINING`. Completing training requires the request to carry `training_hours` of at least 25 hours and `check_ride_passed` equal to true; a submission failing either condition is rejected with `ERR_INSUFFICIENT_TRAINING`. On success, the crew member moves from `IN_TRAINING` to `QUALIFIED` and the supplied `training_hours` are added to `training_hours_accumulated`. Deactivation from `HIRED`, `IN_TRAINING`, or `QUALIFIED` moves the crew member to `INACTIVE`; when a crew member in `HIRED` or `QUALIFIED` status is deactivated, every `ASSIGNED` duty assignment of that crew member whose trip is still in `REQUESTED`, `APPROVED`, or `SCHEDULED` is released to `RELEASED`, so a departing crew member never holds future duty.

Duty scheduling assigns a crew member to a trip with a duty window. The request names the `trip_id`, the `crew_member_id`, the `duty_role` (`PIC` or `SIC`), and the window bounds `duty_start_at` and `duty_end_at`. Because crew are dedicated to one aircraft, an assignment naming a crew member who is not dedicated to the trip's aircraft is a schema-level rejection with `ERR_VALIDATION`. The referenced trip must be in `APPROVED` or `SCHEDULED` status — otherwise `ERR_TRIP_INVALID_STATE`. The crew member must be `QUALIFIED`, else `ERR_CREW_NOT_QUALIFIED`. The assignment's own `duty_hours` is the difference between `duty_end_at` and `duty_start_at` expressed in hours, rounded half up to two decimal places.

Two safety gates then apply, in order. First, projected duty totals: each crew member carries two computed accumulators, `duty_hours_7d` and `duty_hours_28d`, which sum `duty_hours` over the crew member's assignments in `ASSIGNED` or `COMPLETED` status whose `duty_end_at` falls inside the trailing seven-day or twenty-eight-day window ending at the logical clock's now — window bounds are lower-exclusive, upper-inclusive, and an assignment whose window membership straddles a bound counts in full. The new assignment is rejected with `ERR_DUTY_LIMIT_EXCEEDED` when the projected seven-day total (the current `duty_hours_7d` plus the new `duty_hours`) is strictly greater than 40 hours, or when the projected twenty-eight-day total is strictly greater than 120 hours; landing exactly on either limit is allowed. Second, duty-window overlap: the new half-open window from `duty_start_at` to `duty_end_at` must have a strictly empty intersection with every other `ASSIGNED` or `COMPLETED` duty window of the same crew member; two windows that merely touch — one's end equal to the other's start — do not conflict, but any strictly positive intersection is rejected with `ERR_CREW_OVERLAP`.

Releasing an assignment (performed by the `FlightOpsManager`, or by the system during trip cancellation or crew deactivation) moves it from `ASSIGNED` to `RELEASED`; the crew member's `duty_hours_7d` and `duty_hours_28d` decrease by the released assignment's `duty_hours` while window membership is otherwise unchanged. Releasing anything not in `ASSIGNED` is `ERR_ASSIGNMENT_INVALID_STATE`. When a trip completes, each of its `ASSIGNED` assignments moves to `COMPLETED`, and each assigned crew member's `flight_hours_total` — the running sum of `block_hours_actual` over trips that have reached completion where the crew member held an assignment, with a completed trip that is later voided still counted in the sum (voiding does not un-perform the duty, §3.4) — increases by the trip's `block_hours_actual`.

### 3.4. Trip Requests, Charter Approval, Scheduling Gates, and Completion

A trip is requested by a `FlightOpsManager` or the `Owner`, supplying `aircraft_id`, `trip_use` (`OWNER_USE` or `CHARTER`), `depart_icao`, `arrive_icao`, the scheduled `departure_at` instant, and `block_hours_est`. A `CHARTER` trip must also carry `charter_quote_cents` — the price quoted to the charter customer — and omitting it is rejected with `ERR_QUOTE_REQUIRED`. New trips start in `REQUESTED`. An `OWNER_USE` trip auto-approves at creation, transitioning immediately from `REQUESTED` to `APPROVED`. A `CHARTER` trip waits for the owner: approval by the owner moves it `REQUESTED → APPROVED`, and the acting `X-User-ID` must equal the aircraft agreement's `owner_id` or the call is refused with `ERR_FORBIDDEN_ROLE`. The owner may instead decline the charter, moving it to `DECLINED` and recording the supplied `reason` in `decline_reason`; only `CHARTER` trips may be declined, and declining an `OWNER_USE` trip is `ERR_TRIP_INVALID_STATE`.

A `DECLINED` trip is not dead. Resubmission — by the `FlightOpsManager` or the owner — moves it back to `REQUESTED`; any of `departure_at`, `block_hours_est`, or `charter_quote_cents` supplied in the resubmission replace the stored values, and `decline_reason` is cleared. A resubmitted `CHARTER` trip therefore re-enters the owner-approval queue.

Scheduling is the most heavily gated transition in the system, performed by the `FlightOpsManager` against an `APPROVED` trip. Five gates are evaluated in fixed order. (1) Agreement: the aircraft's management agreement must be `ACTIVE`, else `ERR_AGREEMENT_INVALID_STATE`. (2) Maintenance: no `MaintenanceEvent` of the aircraft in `FORECAST` or `SCHEDULED` status may have `due_at_aircraft_hours` at or below the aircraft's current `total_time_hours` — an event due exactly at the current hour reading already counts as overdue, and any such event blocks scheduling with `ERR_MAINTENANCE_OVERDUE`. (3) Insurance: an `ACCEPTED` `ComplianceFiling` of kind `INSURANCE_COI` whose `valid_until` is on or after the calendar date of `departure_at` must exist for the aircraft, else `ERR_INSURANCE_NOT_CURRENT`. (4) Crew complement: the trip must hold at least one `ASSIGNED` duty assignment with `duty_role` `PIC` held by a `QUALIFIED` `CAPTAIN`, and at least one `ASSIGNED` assignment with `duty_role` `SIC` held by a `QUALIFIED` `FIRST_OFFICER`, else `ERR_CREW_COMPLEMENT_INCOMPLETE`. (5) Aircraft occupancy: the candidate trip's occupancy interval — running from `departure_at` for `block_hours_est` hours — must leave a turnaround buffer of at least one hour to every other `SCHEDULED` or `COMPLETED` trip of the same aircraft; a gap of exactly one hour passes, and anything shorter is rejected with `ERR_AIRCRAFT_OVERLAP`. Passing all five gates moves the trip from `APPROVED` to `SCHEDULED`.

Completion, performed by the `FlightOpsManager` against a `SCHEDULED` trip, carries the actual block time in `block_hours_actual`, which must be strictly greater than zero (`ERR_VALIDATION` otherwise). Completion is the busiest cascade in the platform, and its effects are: the trip's `block_hours_actual` is set; the aircraft's `total_time_hours` increases by `block_hours_actual`; every `ASSIGNED` duty assignment of the trip transitions to `COMPLETED`; each assigned crew member's `flight_hours_total` increases by `block_hours_actual`; and for `CHARTER` trips the owner credit and any shortfall are computed as described in §3.8. In addition, if a `MaintenanceProgram` of the aircraft is `ENROLLED` at the completion instant, the platform posts a new `Expense` with `category` `PROGRAM_ACCRUAL`, `tax_use` `MIXED`, `trip_id` set to this trip, `service_date` set to the completion date, and `amount_cents` equal to `block_hours_actual` multiplied by the program's `rate_per_hour_cents`, rounded half up to integer cents. That new expense itself triggers recomputation of any `DRAFT` monthly statement covering the completion period, as does the completion itself — the statement's charter offset and accrual totals pick up the new values.

Cancellation is available to the `FlightOpsManager` or the owner from any of `REQUESTED`, `APPROVED`, or `SCHEDULED`, moving the trip to `CANCELLED` and releasing every `ASSIGNED` duty assignment of the trip to `RELEASED`. Voiding is the data-error path for a trip already `COMPLETED`: performed by the `FlightOpsManager`, it requires the completion-created `PROGRAM_ACCRUAL` expense (if one exists) to still be `POSTED` — if that accrual has already been `BILLED` onto a certified statement, the void is rejected with `ERR_EXPENSE_NOT_POSTED`. A successful void subtracts `block_hours_actual` from the aircraft's `total_time_hours`, moves the completion-created accrual expense to `VOID`, resets `owner_credit_cents` and `charter_shortfall_cents` to null, and recomputes any `DRAFT` statement covering the period. Duty that was actually performed is not un-performed: the trip's duty assignments remain `COMPLETED`, and the crew members' `flight_hours_total` is not reversed.

### 3.5. Maintenance Programs and Event Forecasting

A `MaintenancePlanner` quotes an hourly-cost maintenance program for an aircraft by supplying `aircraft_id`, a `program_name`, and the `rate_per_hour_cents` at which the program accrues. A program starts `QUOTED`. Enrollment moves it from `QUOTED` to `ENROLLED`, and the same enroll action resumes a `SUSPENDED` program back to `ENROLLED`; enrollment is open to both the `MaintenancePlanner` and the `AccountExecutive`. Suspension by the `MaintenancePlanner` moves an `ENROLLED` program to `SUSPENDED`, and while suspended no accrual is posted at trip completion. Cancellation by the `AccountExecutive` moves a program from `QUOTED`, `ENROLLED`, or `SUSPENDED` to `CANCELLED`. Attempting any of these transitions from the wrong status is `ERR_PROGRAM_INVALID_STATE`.

Recurring airframe maintenance is forecast as a chain of events. The `MaintenancePlanner` creates a base event with `aircraft_id`, an `event_code` such as a hundred-hour inspection, the recurring `interval_hours`, and an explicit `due_at_aircraft_hours` reading at which the event comes due. Base events start in `FORECAST` with `previous_event_id` null. Scheduling by the `MaintenancePlanner` moves a `FORECAST` event to `SCHEDULED` and sets `scheduled_date` from the request. Completion by the `MaintenancePlanner` moves a `SCHEDULED` event to `COMPLETED`, stamps `completed_at` from the logical clock, captures `actual_aircraft_hours` as the aircraft's `total_time_hours` at the completion instant, and then auto-spawns the successor: a new `MaintenanceEvent` in `FORECAST` whose `previous_event_id` is the completed event, whose `event_code` and `interval_hours` match the completed event, and whose `due_at_aircraft_hours` is the completed event's `actual_aircraft_hours` plus `interval_hours`. Scheduling or completing from the wrong status is `ERR_EVENT_INVALID_STATE`. The chain of successors is browsable: the event list accepts a `previous_event_id` filter that returns exactly the successors spawned from a given event.

### 3.6. Insurance and Regulatory Compliance Filings

The `ComplianceOfficer` drafts a filing by supplying `aircraft_id`, the `filing_kind` (`INSURANCE_COI`, `REGISTRATION`, or `OPS_SPECS_AMENDMENT`), the `authority` (for example the FAA or an insurer), the external `reference_no`, and the `valid_until` date through which the filing will be valid once accepted. A filing starts in `DRAFT` with `filed_at` null.

Filing submission moves a `DRAFT` filing to `FILED` and stamps `filed_at` from the logical clock; the same action re-files a `REJECTED` filing back to `FILED`. On either filing or re-filing, `reference_no` and `valid_until` are replaced by the request values when present. Recording the authority's decision against a `FILED` filing carries an `outcome` — `ACCEPTED` or `REJECTED` — and optional `notes`; the decision moves the filing to the named status and records the notes in `decision_notes`. Filing from a status other than `DRAFT` or `REJECTED`, or recording a decision against anything not `FILED`, is `ERR_FILING_INVALID_STATE`. An `ACCEPTED` insurance certificate is what the trip-scheduling gate of §3.4 looks for.

### 3.7. Hangar and Fuel Vendor Contracts

The `ContractsManager` drafts a vendor contract by supplying `aircraft_id`, the `vendor_kind` (`HANGAR` or `FUEL`), the vendor's legal `vendor_name`, the billing `unit` (`MONTH` or `GALLON`), the negotiated `rate_cents_per_unit`, and the term bounds `term_start` and `term_end`. A contract starts in `DRAFT`.

Negotiation is a propose/counter exchange. Proposing moves a `DRAFT` contract to `PROPOSED`; the same propose action re-proposes revised terms from `COUNTERED` back to `PROPOSED`. On either flavor of propose, `rate_cents_per_unit` is replaced by the request value when supplied. Recording a vendor counter-offer moves a `PROPOSED` contract to `COUNTERED` and replaces `rate_cents_per_unit` with the countered value, which is required on the counter action. Execution — an `AccountExecutive` privilege — moves a contract from `PROPOSED` or `COUNTERED` to `EXECUTED` at the currently proposed terms. Expiry by the `ContractsManager` moves a contract still in negotiation — `PROPOSED` or `COUNTERED` — to `EXPIRED`. Any of these transitions attempted from the wrong status is `ERR_CONTRACT_INVALID_STATE`.

### 3.8. Expenses and the Monthly Owner Statement

The `FinanceController` posts actual costs against an aircraft, supplying `aircraft_id`, the `category` (`FUEL`, `CREW`, `MAINTENANCE`, `HANGAR`, `INSURANCE`, `PROGRAM_ACCRUAL`, `CHARTER_DIRECT`, or `OTHER`), `amount_cents`, the `service_date` on which the cost was incurred, the `vendor_name`, and the `tax_use` (`OWNER_USE`, `CHARTER_USE`, or `MIXED`). The `paid_date` is optional; a null `paid_date` marks the cost as unpaid. A `CHARTER_DIRECT` expense must carry the `trip_id` of an existing `CHARTER` trip, and any other category must not carry a `trip_id` at all; violations are rejected with `ERR_QUOTE_REQUIRED`. A new expense starts in `POSTED` status with `statement_id` null, and its arrival triggers recomputation of any `DRAFT` monthly statement covering its `service_date` period. Voiding by the `FinanceController` moves a `POSTED` expense to `VOID` — anything else is `ERR_EXPENSE_NOT_POSTED` — and likewise triggers recomputation of any `DRAFT` statement covering that period, with totals dropping the voided line.

The monthly statement is generated by an `AccountExecutive` with `aircraft_id` and a `period` in YYYY-MM form; the period covers from the first day of the named month, inclusive, up to the first day of the following month, exclusive. Generation is idempotent over drafts: at most one statement per aircraft and period may exist in `CERTIFIED` or `DELIVERED` — a duplicate there is rejected with `ERR_STATEMENT_EXISTS` — while generating over an existing `DRAFT` recomputes and returns that draft rather than creating a duplicate. Generation stamps `prepared_by_user_id` with the acting `X-User-ID` and computes the full set of derived figures.

The totals are computed as follows. The `accrual_total_cents` is the sum of `amount_cents` over the aircraft's non-`VOID` expenses — `POSTED` and `BILLED` alike — whose `service_date` falls inside the period, compared by calendar date. The `cash_total_cents` is the sum of `amount_cents` over the same non-`VOID` expense set whose `paid_date` is non-null and falls inside the period; the two totals diverge whenever an expense is paid in a different month than it was incurred. Both sums are integer cents with no rounding applied.

The management fee is pinned to an evaluation order that breaks the apparent circularity between the fee and the grand total. The direct subtotal is exactly the `accrual_total_cents` — there is no management-fee expense category, so the fee never enters its own basis. The statement's `management_fee_cents` is then the agreement's `monthly_management_fee_cents` plus the agreement's `variable_fee_pct` multiplied by that direct subtotal, the product rounded half up to integer cents. The grand total due is the direct subtotal plus the management fee minus the `charter_offset_cents`; the fee is computed on the pre-fee subtotal and is never reduced by the charter offset, which is applied only after the fee.

The `charter_offset_cents` is the sum of `owner_credit_cents` over the aircraft's `CHARTER` trips that completed with their completion timestamp inside the period. The per-trip credit itself is computed at trip completion: let the direct charter cost be the sum of `amount_cents` over the trip's non-`VOID` expenses in category `CHARTER_DIRECT`, and let the net be `charter_quote_cents` minus that direct cost. When the net is strictly positive, `owner_credit_cents` is the net multiplied by the agreement's `charter_owner_share_pct`, rounded half up to integer cents, and `charter_shortfall_cents` is zero. When the net is exactly zero — a break-even trip — both values are zero; break-even is not a shortfall. When the net is negative, the credit floors at zero and `charter_shortfall_cents` is the absolute amount by which direct costs exceeded the quote. For `OWNER_USE` trips both values are zero.

The `budget_variance_cents` compares actuals to plan. The platform finds the `APPROVED` `OperatingBudget` for the statement's aircraft whose `fiscal_year` equals the year of the period start; if none exists, `budget_variance_cents` is null. Otherwise the annual total is the sum of the budget's six lines, the monthly share is that annual total divided by twelve and rounded half up to integer cents, and `budget_variance_cents` is the `accrual_total_cents` minus that monthly share.

The mixed-expense tax split produces `mixed_owner_share_cents` and `mixed_charter_share_cents`. First the charter ratio is established from the aircraft's trips in `COMPLETED` status whose completion timestamp falls inside the period. Under the `FLIGHT_HOURS` method the ratio is the charter block hours — the sum of `block_hours_actual` over the in-period completed `CHARTER` trips — divided by the total block hours over all in-period completed trips. Under the `TRIP_LEGS` method the ratio is the count of in-period completed `CHARTER` trips divided by the count of all in-period completed trips. If the denominator is zero — no completed trips in the period — the ratio is zero and everything allocates to owner use. The owner ratio is one minus the charter ratio. Each in-period non-`VOID` expense line whose `tax_use` is `MIXED` is then split per line: the line's owner share is its `amount_cents` multiplied by the owner ratio, rounded half up to integer cents, and the line's charter share is the `amount_cents` minus that owner share. The statement's `mixed_owner_share_cents` is the sum of the per-line owner shares and `mixed_charter_share_cents` is the sum of the per-line charter shares — rounding is applied per line before summing, never once at the end, because the two orders disagree on odd-cent lines. The method in force on the agreement at generation time is recorded on the statement as `tax_method_used`, and the two shares always sum back to the total of the in-period mixed lines.

Certification is a `FinanceController` action against a `DRAFT` statement, and it carries a segregation-of-duties rule: the acting `X-User-ID` must differ from the statement's `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Certification also enforces staleness: if any `POSTED` expense of the aircraft exists whose `service_date` falls in the period and which is not reflected in the statement's last computation, certification is rejected with `ERR_STATEMENT_STALE` — the preparer must regenerate the draft to pick up the new expense. The statement's last computation for this check is its most recent explicit generation or regeneration via `POST /statements`: the event-triggered recomputation of a `DRAFT` statement described above (on expense posting or voiding, and on trip completion or voiding) refreshes the draft's figures in place but does not advance the computation point the staleness check consults, so an expense posted after the last explicit generation still blocks certification until the draft is explicitly regenerated. Successful certification moves the statement from `DRAFT` to `CERTIFIED`, stamps `certified_by_user_id` with the acting `X-User-ID`, and locks the ledger: every in-period `POSTED` expense of the aircraft transitions to `BILLED` with its `statement_id` set to the certifying statement. Delivery by an `AccountExecutive` moves a `CERTIFIED` statement to `DELIVERED`. Certify from a non-`DRAFT` state or deliver from a non-`CERTIFIED` state is `ERR_STATEMENT_INVALID_STATE`.

### 3.9. Termination and Records Handover

Either the `Owner` or the `AccountExecutive` may give termination notice against an `ACTIVE` agreement, moving it to `TERMINATION_PENDING`. Notice has three immediate side effects beyond the state change. The `notice_given_at` timestamp is set from the logical clock. A snapshot is taken: `records_total` becomes the count of all `MaintenanceEvent` and `ComplianceFiling` records, of any status, belonging to the agreement's aircraft. And every trip of the aircraft still in `REQUESTED`, `APPROVED`, or `SCHEDULED` is cascade-cancelled to `CANCELLED` — each such cancellation in turn releases that trip's `ASSIGNED` duty assignments to `RELEASED`, exactly as a manual cancellation would. The agreement's `version` increments by 1.

Records release is the handover mechanism, performed by the `AccountExecutive` with a body listing `record_ids`. Every entry must identify a `MaintenanceEvent` or `ComplianceFiling` belonging to the agreement's aircraft — anything else is `ERR_RECORD_NOT_IN_SCOPE` — and no named record may already have its `handed_over_at` set, which is `ERR_RECORD_ALREADY_RELEASED`. A successful release sets `handed_over_at` on each named record, increases the agreement's `records_released` by the number of records in the batch, and increments the agreement's `version`. Release requires the agreement to be in `TERMINATION_PENDING` or `HANDOVER_IN_PROGRESS` (`ERR_AGREEMENT_INVALID_STATE` otherwise), and the first successful release moves the agreement from `TERMINATION_PENDING` to `HANDOVER_IN_PROGRESS`.

Completion of the termination — again an `AccountExecutive` action — requires the agreement to be in `HANDOVER_IN_PROGRESS` and is guarded by two obligation checks: `records_released` must equal `records_total`, else `ERR_HANDOVER_INCOMPLETE`; and the aircraft must hold no trip in `REQUESTED`, `APPROVED`, or `SCHEDULED` and no maintenance program in `ENROLLED`, else `ERR_OPEN_OBLIGATIONS`. On success the agreement moves to `TERMINATED`, every `SUSPENDED` maintenance program of the aircraft is set to `CANCELLED`, and the agreement's `version` increments by 1. Termination is the agreement's terminal state.

## 4. Endpoint Definitions

All endpoints are served from the API root. Creating a new resource returns HTTP 201; operations that modify an existing resource — state transitions, amendments, revisions, releases — return HTTP 200. Every response conforms to the envelope of §2.2, and every list endpoint paginates per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /owners | Onboard an aircraft owner | AccountExecutive |
| GET | /owners/{id} | Fetch one owner | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /aircraft | Register an aircraft under an owner | AccountExecutive |
| GET | /aircraft/{id} | Fetch one aircraft | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /aircraft | List aircraft, optionally filtered by owner | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /agreements | Create a management agreement (starts PENDING) | AccountExecutive |
| GET | /agreements/{id} | Fetch one agreement | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /agreements | List agreements, optionally filtered by owner and/or aircraft | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| PATCH | /agreements/{id}/terms | Amend commercial terms while ACTIVE; OCC-guarded by expected_agreement_version | AccountExecutive |
| POST | /agreements/{id}/activate | Activate a PENDING agreement | AccountExecutive |
| POST | /agreements/{id}/give-termination-notice | Owner or manager gives termination notice; snapshots records_total and cascade-cancels open trips | AccountExecutive, Owner |
| POST | /agreements/{id}/release-records | Release a batch of maintenance/compliance records to the owner during handover | AccountExecutive |
| POST | /agreements/{id}/complete-termination | Complete termination once records handover is complete and no open obligations remain | AccountExecutive |
| POST | /budgets | Draft an annual operating budget for an aircraft | AccountExecutive |
| GET | /aircraft/{id}/budgets | List budgets of an aircraft | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| PATCH | /budgets/{id} | Revise budget amounts; a REJECTED budget returns to DRAFT | AccountExecutive |
| POST | /budgets/{id}/submit | Submit a DRAFT budget to the owner | AccountExecutive |
| POST | /budgets/{id}/approve | Owner approves a SUBMITTED budget | Owner |
| POST | /budgets/{id}/reject | Owner rejects a SUBMITTED budget | Owner |
| POST | /expenses | Post an actual cost against an aircraft | FinanceController |
| GET | /expenses/{id} | Fetch one expense | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /expenses | List expenses with optional filters | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /expenses/{id}/void | Void a POSTED expense | FinanceController |
| POST | /statements | Generate (or recompute an existing DRAFT of) the monthly operating statement for an aircraft and period | AccountExecutive |
| GET | /statements/{id} | Fetch one statement | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /aircraft/{id}/statements | List statements of an aircraft | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /statements/{id}/certify | FinanceController certifies a DRAFT statement; locks in-period POSTED expenses to BILLED; certifier must differ from preparer | FinanceController |
| POST | /statements/{id}/deliver | Deliver a CERTIFIED statement to the owner | AccountExecutive |
| POST | /crew | Hire a crew member for an aircraft | FlightOpsManager |
| GET | /crew/{id} | Fetch one crew member (includes computed duty accumulators) | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /aircraft/{id}/crew | List crew of an aircraft | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /crew/{id}/begin-training | Move a HIRED crew member into training | FlightOpsManager |
| POST | /crew/{id}/complete-training | Complete training; qualifies the crew member when hours and check ride pass | FlightOpsManager |
| POST | /crew/{id}/deactivate | Deactivate a crew member; releases their ASSIGNED duty assignments on non-terminal trips | FlightOpsManager |
| POST | /trips | Request a trip; OWNER_USE trips auto-approve, CHARTER trips await owner approval | FlightOpsManager, Owner |
| GET | /trips/{id} | Fetch one trip | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /aircraft/{id}/trips | List trips of an aircraft | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /trips/{id}/approve | Owner approves a REQUESTED charter trip | Owner |
| POST | /trips/{id}/decline | Owner declines a REQUESTED charter trip | Owner |
| POST | /trips/{id}/resubmit | Resubmit a DECLINED trip with optionally revised terms | FlightOpsManager, Owner |
| POST | /trips/{id}/schedule | Schedule an APPROVED trip after agreement, maintenance, insurance, crew-complement, and aircraft-overlap gates | FlightOpsManager |
| POST | /trips/{id}/complete | Complete a SCHEDULED trip with actual block hours; drives hours accrual, charter credit, program accrual, and crew flight hours | FlightOpsManager |
| POST | /trips/{id}/cancel | Cancel a non-terminal trip; releases its ASSIGNED duty assignments | FlightOpsManager, Owner |
| POST | /trips/{id}/void | Void a COMPLETED trip (data error); reverses airframe hours and the unbilled program accrual | FlightOpsManager |
| POST | /assignments | Assign crew to a trip with a duty window | FlightOpsManager |
| GET | /assignments/{id} | Fetch one assignment | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /assignments | List assignments with optional filters | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| DELETE | /assignments/{id} | Release an ASSIGNED duty assignment | FlightOpsManager |
| POST | /programs | Quote an hourly-cost maintenance program for an aircraft | MaintenancePlanner |
| GET | /programs/{id} | Fetch one program | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /aircraft/{id}/programs | List programs of an aircraft | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /programs/{id}/enroll | Enroll a QUOTED program or resume a SUSPENDED one | MaintenancePlanner, AccountExecutive |
| POST | /programs/{id}/suspend | Suspend an ENROLLED program (accrual stops) | MaintenancePlanner |
| POST | /programs/{id}/cancel | Cancel a program | AccountExecutive |
| POST | /events | Create a base maintenance event forecast with an explicit due hour reading | MaintenancePlanner |
| GET | /events/{id} | Fetch one maintenance event | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /events | List maintenance events with optional filters (previous_event_id lists a chain's successors) | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /events/{id}/schedule | Schedule a FORECAST event | MaintenancePlanner |
| POST | /events/{id}/complete | Complete a SCHEDULED event; records actual airframe hours and spawns the successor forecast | MaintenancePlanner |
| POST | /filings | Draft an insurance or regulatory filing | ComplianceOfficer |
| GET | /filings/{id} | Fetch one filing | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /aircraft/{id}/filings | List filings of an aircraft | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /filings/{id}/file | File a DRAFT or re-file a REJECTED filing | ComplianceOfficer |
| POST | /filings/{id}/record-decision | Record the authority's decision on a FILED filing | ComplianceOfficer |
| POST | /contracts | Draft a hangar or fuel vendor contract | ContractsManager |
| GET | /contracts/{id} | Fetch one contract | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| GET | /aircraft/{id}/contracts | List contracts of an aircraft | AccountExecutive, Owner, FlightOpsManager, MaintenancePlanner, FinanceController, ComplianceOfficer, ContractsManager |
| POST | /contracts/{id}/propose | Propose terms (from DRAFT) or re-propose revised terms (from COUNTERED) | ContractsManager |
| POST | /contracts/{id}/counter | Record a vendor counter-offer with a revised rate | ContractsManager |
| POST | /contracts/{id}/execute | Execute the contract at the currently proposed terms | AccountExecutive |
| POST | /contracts/{id}/expire | Expire a contract still in negotiation | ContractsManager |
| POST | /_clock/set_current_utc | Set the server's logical clock (test-driving endpoint). Before any call to this endpoint the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_AGREEMENT_INVALID_STATE | 409 |
| ERR_STALE_AGREEMENT_VERSION | 412 |
| ERR_AGREEMENT_CONFLICT_EXISTS | 409 |
| ERR_HANDOVER_INCOMPLETE | 409 |
| ERR_OPEN_OBLIGATIONS | 409 |
| ERR_RECORD_NOT_IN_SCOPE | 422 |
| ERR_RECORD_ALREADY_RELEASED | 409 |
| ERR_BUDGET_INVALID_STATE | 409 |
| ERR_BUDGET_YEAR_EXISTS | 409 |
| ERR_TAIL_NUMBER_EXISTS | 409 |
| ERR_EXPENSE_NOT_POSTED | 409 |
| ERR_STATEMENT_EXISTS | 409 |
| ERR_STATEMENT_INVALID_STATE | 409 |
| ERR_STATEMENT_STALE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_CREW_INVALID_STATE | 409 |
| ERR_CREW_NOT_QUALIFIED | 409 |
| ERR_INSUFFICIENT_TRAINING | 422 |
| ERR_DUTY_LIMIT_EXCEEDED | 422 |
| ERR_CREW_OVERLAP | 409 |
| ERR_AIRCRAFT_OVERLAP | 409 |
| ERR_CREW_COMPLEMENT_INCOMPLETE | 409 |
| ERR_INSURANCE_NOT_CURRENT | 409 |
| ERR_MAINTENANCE_OVERDUE | 409 |
| ERR_TRIP_INVALID_STATE | 409 |
| ERR_QUOTE_REQUIRED | 422 |
| ERR_ASSIGNMENT_INVALID_STATE | 409 |
| ERR_PROGRAM_INVALID_STATE | 409 |
| ERR_EVENT_INVALID_STATE | 409 |
| ERR_FILING_INVALID_STATE | 409 |
| ERR_CONTRACT_INVALID_STATE | 409 |
