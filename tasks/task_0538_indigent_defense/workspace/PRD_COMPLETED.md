# Indigent Defense API — Product Requirements Document

## 1. Introduction

Public defender offices operate under two relentless pressures at once: the constitutional obligation to furnish competent counsel to every financially eligible defendant, and the fiscal reality of a fixed annual budget for the panel attorneys, investigators, and experts that counsel depends on. This API is the system of record for that balancing act. It follows a criminal matter from the moment it is referred at intake, through financial-eligibility screening, conflict clearance, attorney assignment, court-event calendaring, ancillary-service authorization, and panel billing, all the way to disposition and the recoupment of costs from partially eligible defendants.

The platform treats attorney capacity as a scarce, weighted resource that competing cases draw down, and it treats the office voucher budget as a ledger that must never be quietly overdrawn. Around both scarcities sit compliance controls: conflict-of-interest screening before any assignment, segregation of duties between the officer who screens a defendant and the supervisor who may later waive that defendant's recoupment, and a hard budget gate that suspends new service spending once the office nears its ceiling. The sections below define the data contract, the global invariants that hold across every endpoint, and the detailed workflows that move each entity through its lifecycle.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that govern every endpoint. Individual business workflows and the calculations they trigger are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_USER_CONTEXT`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes five roles: `IntakeClerk`, `ScreeningOfficer`, `AssignmentCoordinator`, `SupervisingAttorney`, and `Attorney`. An `IntakeClerk` refers new cases and submits financial screenings. A `ScreeningOfficer` decides eligibility on submitted screenings. An `AssignmentCoordinator` runs conflict checks, assigns and reassigns attorneys, adjusts case weight, calendars and vacates court events, requests and completes services, and disposes cases. A `SupervisingAttorney` administers offices, attorneys, and courtrooms, suspends and reactivates attorneys, approves service requests, approves/rejects/voids vouchers, and collects or waives recoupment. An `Attorney` authors and submits their own vouchers. All five roles may read (`GET`) any resource.

For `IntakeClerk`, `ScreeningOfficer`, `AssignmentCoordinator`, and `SupervisingAttorney`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow captures it — for example as `decided_by_user_id` on a `FinancialScreening` when a screening is decided, or as `waived_by_user_id` on a `RecoupmentOrder` when an order is waived — but it never compares that identifier to any entity's `id`. For `Attorney`, by contrast, `X-User-ID` is the `id` of the acting `Attorney` entity; ownership checks on any resource that references an attorney compare the resource's attorney foreign key to `X-User-ID`. Concretely, when an `Attorney` creates, submits, or revises a `Voucher`, that voucher's `attorney_id` must equal `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED`. On creation the match is applied to the `attorney_id` supplied in the body before any resource existence is resolved; on submit and revise, which act on an existing voucher identified in the path, the voucher's existence is resolved first (`ERR_VOUCHER_NOT_FOUND` if it does not resolve) and the ownership match against the persisted `attorney_id` is applied immediately afterward.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` defaults to 0 and represents the number of leading records to skip. A `limit` or `offset` that is not a valid integer, or that falls outside these bounds, is rejected with `ERR_VALIDATION`. List results are always ordered by `created_at` ascending (oldest first), and records sharing an identical `created_at` are further ordered by their creation sequence (insertion order). Each list response reports `limit`, `offset`, `total_count` (the count of records matching the filter before pagination), and `has_more` (true when records remain beyond the current page) inside `meta`.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id`, which is a UUID with no type prefix. Timestamps `created_at` and `updated_at` are ISO 8601 UTC strings with three fractional digits. Most resources also carry an integer `version` that begins at 1 when the resource is created and increments by one on every mutation that changes the resource, alongside a refresh of `updated_at`.

Two resources are configuration or audit artifacts that are never mutated after creation and therefore carry only `id` and `created_at` — they have neither an `updated_at` nor a `version` field. These are `Courtroom` (a static configuration record holding a `name` and a `courthouse`) and `ConflictCheck` (an immutable audit record whose `result` is fixed at creation). Every other entity — `DefenderOffice`, `Attorney`, `Case`, `FinancialScreening`, `Assignment`, `CourtEvent`, `ServiceRequest`, `Voucher`, and `RecoupmentOrder` — carries the full set of common fields including `updated_at` and `version`.

### 2.5. Hierarchical Consistency and Derived Aggregates

Several fields are read-only aggregates the server maintains rather than accepting from clients; they must always equal the sum they are defined against. An `Attorney`'s `current_weighted_load` always equals the sum of `assigned_weight` across that attorney's `Assignment` records in `ACTIVE` status; it starts at 0, rises when an assignment becomes active, and falls when one leaves the active state. A `DefenderOffice`'s `voucher_spent_cents` always equals the sum of `approved_amount_cents` across that office's vouchers currently in `APPROVED` status (vouchers that have been `VOIDED` are excluded); it starts at 0. A `Case`'s `assigned_attorney_id` is a derived convenience field reflecting the attorney of the case's current `ACTIVE` `Assignment`, or null when none exists; it is not a stored foreign key.

Whenever an operation cascades a change across more than one entity, every affected entity is re-saved: its `updated_at` is refreshed and, where the entity carries one, its `version` increments. When a cascade recomputes an aggregate such as `current_weighted_load` or `voucher_spent_cents`, the derived status fields that depend on that aggregate (`Attorney.status`, `DefenderOffice.budget_status`) are re-evaluated in the same operation so the stored value never lags the aggregate.

### 2.6. Left-to-Right Resource Resolution

Requests are validated in a fixed order before any business rule runs. First the user-context headers are checked, then the role's permission for the endpoint. Next, every identifier is resolved: path identifiers and every foreign key present in the body are checked for existence left to right, and the first one that does not resolve produces the matching not-found error — `ERR_OFFICE_NOT_FOUND`, `ERR_ATTORNEY_NOT_FOUND`, `ERR_COURTROOM_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_CONFLICT_CHECK_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_COURT_EVENT_NOT_FOUND`, `ERR_SERVICE_REQUEST_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`, or `ERR_RECOUPMENT_ORDER_NOT_FOUND`. Only after all referenced resources exist does the server validate that the request body is well-formed — required fields present, enum values legal, and numeric constraints satisfied — rejecting violations with `ERR_VALIDATION`.

### 2.7. Validation Precedence

When several checks could fire on one request, they are evaluated in the following priority order, and the first failure is the one returned. (1) User-context headers present and role recognized, else `ERR_MISSING_USER_CONTEXT`. (2) Role permitted for the endpoint, and for an `Attorney` acting on a `Voucher` the ownership match, else `ERR_UNAUTHORIZED`. (3) Existence of every path id and body foreign key, else the relevant not-found error. (4) Body well-formedness, else `ERR_VALIDATION`. (5) The target resource is in the correct state for the operation, else the operation's state error (for example `ERR_CASE_NOT_SCREENED`, `ERR_CASE_NOT_ASSIGNED`, `ERR_CASE_NOT_DISPOSED`, `ERR_VOUCHER_INVALID_STATE`, `ERR_SERVICE_REQUEST_NOT_APPROVED`, `ERR_SERVICE_REQUEST_NOT_COMPLETED`, `ERR_COURT_EVENT_NOT_SCHEDULED`, `ERR_RECOUPMENT_NOT_COLLECTIBLE`, or `ERR_SCREENING_ALREADY_DECIDED`). (6) Cross-entity referential state gates, such as the target attorney not being suspended, else `ERR_ATTORNEY_NOT_ACTIVE`. (7) Conflict clearance for assignment, else `ERR_CONFLICT_NOT_CLEARED`. (8) Screening uniqueness, else `ERR_SCREENING_ALREADY_EXISTS`. (9) Event not in the past, else `ERR_EVENT_IN_PAST`. (10) Attorney calendar buffer, else `ERR_ATTORNEY_SCHEDULE_CONFLICT`. (11) Courtroom double-booking, else `ERR_COURTROOM_DOUBLE_BOOKED`. (12) Segregation of duties on waiver, else `ERR_SEGREGATION_OF_DUTIES`. (13) Office budget posture, else `ERR_BUDGET_RESTRICTED`. (14) Caseload capacity, else `ERR_CASELOAD_CAPACITY_EXCEEDED`. The optimistic-concurrency version check on reassignment (Section 2.8) is evaluated as part of that endpoint's state handling, after the case's own state is confirmed and before the downstream attorney, conflict, and capacity checks.

### 2.8. Optimistic Concurrency on Reassignment

Reassigning a case to a new attorney is the one operation guarded by optimistic concurrency control. A reassignment request must carry `expected_case_version`, and this field is required, not optional. Its value must equal the target `Case`'s current `version`. If another writer has already advanced the case's version since the client last read it — for instance because a prior reassignment succeeded and legitimately superseded the earlier assignment — then the client's view is stale, and the request is rejected with `ERR_STALE_CASE_VERSION` and HTTP status 412. This prevents a client from superseding an assignment it never observed. No other endpoint accepts or requires a version field.

### 2.9. Monetary and Weight Precision

All monetary quantities are stored and computed as integer cents; there are no fractional cents anywhere in the system. Where a calculation multiplies hours by a per-hour rate, or an income or asset amount by a rate, the product is rounded half up to the nearest whole cent. Caseload weights are decimal numbers carried to two decimal places; every actual-basis weight computation is rounded half up to two decimals. The specific per-component rounding order for the partial-eligibility contribution is load-bearing and is spelled out in Section 3.2.

### 2.10. Office Budget Posture

Each `DefenderOffice` sets an `annual_voucher_budget_cents` ceiling (which must be greater than zero) and begins life with `budget_status` of `OPEN` and `voucher_spent_cents` of 0. The office flips to `RESTRICTED` the moment its `voucher_spent_cents` exceeds ninety percent of its `annual_voucher_budget_cents`. While an office is `RESTRICTED`, new service-request approvals are blocked with `ERR_BUDGET_RESTRICTED`. Voiding an approved voucher can bring spending back down; if `voucher_spent_cents` falls to ninety percent of the budget or below, the office returns to `OPEN`. These transitions are always driven as cascades from voucher approval and voiding, never set directly.

### 2.11. The Logical Clock

Time in this system is driven by a server logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it the clock stays at that default and never falls back to real time. An administrative capability accepts a `to_iso8601` instant and advances the logical clock to it. All temporal comparisons — whether a court event lies in the past, and the timestamp captured at disposition — read this clock.

## 3. Business Logic & Workflows

### 3.1. Case Referral and Intake

The lifecycle begins when an `IntakeClerk` refers a matter, supplying the `office_id` of the funding `DefenderOffice`, the `defendant_name`, and the `charge_class`. The `charge_class` is one of `FELONY_A`, `FELONY_B`, `MISDEMEANOR`, `JUVENILE`, or `APPEAL`, and it drives nearly every downstream number: base caseload weight, panel fee cap, and statutory recoupment schedule. A freshly referred case opens in `status` `REFERRED` with `eligibility_status` `PENDING`, `case_weight` 0, `weight_basis` `PROVISIONAL`, `complexity_tier` `STANDARD`, and `co_defendant_count` 0; its `disposition_type` and `disposition_date` are null and its `assigned_attorney_id` is null. Cases can be retrieved individually or listed, and the list may be filtered by `office_id` and by `status`.

A `Case` moves through `REFERRED → SCREENED → ASSIGNED → DISPOSED` on the eligible path, or forks to the terminal `DENIED` state at screening. `DISPOSED` and `DENIED` are the two terminal states.

### 3.2. Financial Eligibility Screening and the Decision Fork

Before counsel can be assigned, the defendant's means must be screened. An `IntakeClerk` submits a `FinancialScreening` for a case by supplying the `case_id`, the annual `household_income_cents`, the `household_size` (which must be at least 1), and the `asset_value_cents`. Income and asset amounts must be zero or greater. Exactly one screening may exist per case; a second submission for the same case is rejected with `ERR_SCREENING_ALREADY_EXISTS`. A new screening opens in `status` `SUBMITTED` with `result` `PENDING` and `contribution_amount_cents` 0. Screenings can be fetched individually or listed, filtered by `case_id`.

A `ScreeningOfficer` then decides the screening. Deciding is permitted only while the screening is `SUBMITTED`; deciding one that is already `DECIDED` is rejected with `ERR_SCREENING_ALREADY_DECIDED`. On decision the server computes the eligibility result as follows. First it derives the federal poverty line for the household: a base of $15,000 (1,500,000 cents) plus $5,000 (500,000 cents) for each additional household member beyond the first. If the countable `asset_value_cents` is strictly greater than the asset cap of $20,000 (2,000,000 cents), the result is `INELIGIBLE` regardless of income. Otherwise, if `household_income_cents` is at most the poverty line multiplied by 1.25, the result is `ELIGIBLE`; else if it is at most the poverty line multiplied by 2.00, the result is `PARTIAL`; otherwise it is `INELIGIBLE`. Both income comparisons are inclusive at their upper bound, so income exactly at 1.25 times the poverty line resolves to `ELIGIBLE`, and one cent above resolves to `PARTIAL`.

Deciding always sets the screening's `status` to `DECIDED`, records the deciding user's identifier into `decided_by_user_id`, and copies the computed `result` onto the parent case's `eligibility_status`. The decision forks the case. When the result is `ELIGIBLE` or `PARTIAL`, the case advances from `REFERRED` to `SCREENED`, opening the path to counsel. When the result is `INELIGIBLE`, the case moves to the terminal `DENIED` state, no counsel path opens, and no contribution is set. These two branches are mutually exclusive and carry disjoint effects.

When and only when the result is `PARTIAL`, the server also computes the defendant's `contribution_amount_cents`, and the per-component rounding order here is deliberate. Take the income excess as `household_income_cents` minus the eligibility ceiling (the poverty line multiplied by 1.25). Take the asset excess as the amount by which `asset_value_cents` exceeds the asset contribution floor of $5,000 (500,000 cents), or zero if it does not exceed it. Multiply the income excess by ten percent and round that product half up to whole cents to obtain the income component. Separately multiply the asset excess by five percent and round that product half up to whole cents to obtain the asset component. The contribution is the sum of the two already-rounded components — each component is rounded first, and only then are they added, because rounding each and then summing can differ from summing and then rounding by up to one cent. For any result other than `PARTIAL`, `contribution_amount_cents` remains 0.

### 3.3. Conflict Clearance and Attorney Assignment

Attorneys are registered by a `SupervisingAttorney`, who supplies the `office_id`, `name`, `attorney_type` (`STAFF` or `PANEL`), `bar_number`, `hourly_rate_cents` (zero or greater), and `max_weighted_caseload` (greater than zero). A new attorney opens with `current_weighted_load` 0 and `status` `ACTIVE`. Attorneys can be fetched or listed, filtered by `office_id` and `status`.

Before any attorney is assigned to a case, an `AssignmentCoordinator` runs a conflict-of-interest check, supplying the `case_id`, the candidate `attorney_id`, and an optional list of `co_defendant_names` (adverse parties, defaulting to an empty list). The check's `result` is computed once at creation and then frozen: it is `CONFLICT` if any supplied co-defendant name equals the `defendant_name` of some other case that currently has an `ACTIVE` `Assignment` to that same attorney, and `CLEAR` otherwise. Conflict checks are append-only and never change after creation; they can be fetched or listed, filtered by `case_id` and by `attorney_id`.

Assignment itself is performed by an `AssignmentCoordinator`, who supplies the `case_id` and `attorney_id`. Assignment is gated by four business rules beyond header, permission, existence, and body checks, and they surface in this order: the case must be in `SCREENED` status, else `ERR_CASE_NOT_SCREENED`; the target attorney must not be `SUSPENDED`, else `ERR_ATTORNEY_NOT_ACTIVE`; a `ConflictCheck` for exactly this case and attorney with `result` `CLEAR` must already exist, else `ERR_CONFLICT_NOT_CLEARED`; and the attorney must have room, else `ERR_CASELOAD_CAPACITY_EXCEEDED`. Capacity is judged inclusively: the attorney's current active load plus the provisional weight of this case must be no greater than the attorney's `max_weighted_caseload`; a load landing exactly at the maximum is allowed, and only a result strictly above it is rejected.

On a successful assignment the case's provisional weight is computed as the base weight for its charge class alone — `FELONY_A` is 4.0, `FELONY_B` is 2.5, `MISDEMEANOR` is 1.0, `JUVENILE` is 1.5, and `APPEAL` is 3.0 — and this becomes the case's `case_weight` with `weight_basis` `PROVISIONAL`. A new `Assignment` is created in `ACTIVE` status whose `assigned_weight` snapshots that provisional `case_weight` at the moment it becomes active. The case advances to `ASSIGNED` and its `assigned_attorney_id` is set to the attorney. The attorney's `current_weighted_load` increases by the assigned weight, and if that load reaches or exceeds `max_weighted_caseload` the attorney's `status` flips to `AT_CAPACITY`. Assignments can be fetched or listed, filtered by `case_id`, `attorney_id`, and `status`.

Reassigning a case, also an `AssignmentCoordinator` action, moves counsel to a `new_attorney_id` while the case stays in `ASSIGNED` (this is an `ASSIGNED → ASSIGNED` transition). The request carries `expected_case_version` for the concurrency guard described in Section 2.8. Beyond that guard, the case must currently be `ASSIGNED` (else `ERR_CASE_NOT_ASSIGNED`), the new attorney must not be `SUSPENDED` (else `ERR_ATTORNEY_NOT_ACTIVE`), a `CLEAR` `ConflictCheck` must exist for this case and the new attorney (else `ERR_CONFLICT_NOT_CLEARED`), and the new attorney's active load plus the case's current `case_weight` must not exceed the new attorney's `max_weighted_caseload` (else `ERR_CASELOAD_CAPACITY_EXCEEDED`). A successful reassignment does several things at once: the prior `ACTIVE` `Assignment` transitions to `REASSIGNED` and the prior attorney's `current_weighted_load` decreases by that assignment's weight (and if the prior attorney was `AT_CAPACITY` and their load now sits below their maximum, they revert to `ACTIVE`); a new `Assignment` is created `ACTIVE` with `assigned_weight` equal to the case's current `case_weight`, the new attorney's `current_weighted_load` increases accordingly (flipping them to `AT_CAPACITY` if it reaches their maximum); and the case's `assigned_attorney_id` is repointed to the new attorney while the case's `version` increments by one.

### 3.4. Caseload Weighting and Attorney Availability

Provisional weight is a fast estimate; the true weight of a case is settled by an `AssignmentCoordinator` through a weight adjustment, which supplies the `complexity_tier` and the `co_defendant_count`. Adjustment recomputes the case to the actual basis: multiply the charge class's base weight by the complexity multiplier — `STANDARD` is 1.0, `COMPLEX` is 1.5, `CAPITAL` is 2.0 — then add a co-defendant increment of 0.25 for each co-defendant, and round the total half up to two decimal places. The result becomes the case's `case_weight`, its `weight_basis` becomes `ACTUAL`, and the supplied `complexity_tier` and `co_defendant_count` are stored on the case. An actual weight can differ from the provisional weight for an identical charge class.

Because the weight changed, the case's `ACTIVE` `Assignment` has its `assigned_weight` updated to the new value and the holding attorney's `current_weighted_load` is recomputed. This recomputation is capacity-checked: the attorney's active load excluding this case plus the new candidate weight must not exceed `max_weighted_caseload`, else the adjustment is rejected with `ERR_CASELOAD_CAPACITY_EXCEEDED`. If the recomputed load reaches or exceeds the maximum, the attorney flips to `AT_CAPACITY`; if it drops below a maximum they were previously at, they revert to `ACTIVE`.

An attorney's `status` is one of `ACTIVE`, `AT_CAPACITY`, or `SUSPENDED`. `AT_CAPACITY` is load-derived and toggles automatically whenever `current_weighted_load` reaches or falls below `max_weighted_caseload`. `SUSPENDED`, by contrast, is set manually: a `SupervisingAttorney` may suspend an attorney (from either `ACTIVE` or `AT_CAPACITY`), and suspending one who is already `SUSPENDED` is rejected with `ERR_ATTORNEY_NOT_ACTIVE`. A `SupervisingAttorney` may reactivate a suspended attorney, and reactivating an attorney who is not currently `SUSPENDED` is rejected with `ERR_ATTORNEY_NOT_ACTIVE`; on reactivation the attorney returns to `ACTIVE`, unless the current `current_weighted_load` already meets or exceeds `max_weighted_caseload`, in which case they resolve to `AT_CAPACITY` instead.

### 3.5. Court-Event Calendaring

Courtrooms are simple configuration records a `SupervisingAttorney` creates with a `name` and a `courthouse`, retrievable individually. An `AssignmentCoordinator` calendars a `CourtEvent` against an assigned case by supplying the `case_id`, the `courtroom_id`, the `event_type` (one of `ARRAIGNMENT`, `MOTION_HEARING`, `PRETRIAL`, `TRIAL`, or `SENTENCING`), and the `scheduled_start` and `scheduled_end`. The parent case must be `ASSIGNED` so that an assigned attorney exists to attend, else the request is rejected with `ERR_CASE_NOT_ASSIGNED`; on success the event's `attorney_id` is copied from the case's `assigned_attorney_id` at scheduling time. A new event opens in `status` `SCHEDULED`.

Several temporal rules govern scheduling. The `scheduled_end` must be strictly after the `scheduled_start`, and a violation is a body malformation rejected with `ERR_VALIDATION`. The `scheduled_start` must not lie before the current logical clock; a start in the past is rejected with `ERR_EVENT_IN_PAST`. The assigned attorney's calendar is protected by a thirty-minute travel buffer: the new event must be at least thirty minutes edge-to-edge away from every other `SCHEDULED` event of that same attorney, treating the intervals as half-open and adding the buffer, and any encroachment is rejected with `ERR_ATTORNEY_SCHEDULE_CONFLICT`. The courtroom's calendar is protected without a buffer: the new event must not overlap any other `SCHEDULED` event in the same courtroom, again treating intervals as half-open so that two events sharing an exact boundary sit back-to-back and are allowed; an overlap is rejected with `ERR_COURTROOM_DOUBLE_BOOKED`. Events in `VACATED` status are excluded from both the attorney and courtroom overlap scans.

An `AssignmentCoordinator` may vacate a scheduled event, which requires the event to be `SCHEDULED` (else `ERR_COURT_EVENT_NOT_SCHEDULED`) and moves it to `VACATED`, releasing its interval so a later event may reuse that attorney or courtroom slot. Court events can be fetched or listed, filtered by `case_id`, `attorney_id`, `courtroom_id`, and `status`.

### 3.6. Investigator and Expert Services

When counsel needs an investigator or expert, an `AssignmentCoordinator` files a `ServiceRequest` against an assigned case, supplying the `case_id`, the `service_type` (`INVESTIGATOR`, `EXPERT_PSYCH`, or `EXPERT_FORENSIC`), the `estimated_hours` (greater than zero), and the provider's `estimated_rate_cents` (zero or greater). The request opens in `status` `REQUESTED` with `authorized_amount_cents` 0. Service requests can be fetched or listed, filtered by `case_id`.

A `SupervisingAttorney` approves a request, moving it from `REQUESTED` to `APPROVED`. Approval is permitted only from `REQUESTED` (a wrong-state approval is rejected with `ERR_SERVICE_REQUEST_NOT_APPROVED`), requires the parent case to be `ASSIGNED` (else `ERR_CASE_NOT_ASSIGNED`), and is blocked while the office is `RESTRICTED` (else `ERR_BUDGET_RESTRICTED`). On approval the server sets the authorized ceiling: it multiplies `estimated_hours` by `estimated_rate_cents`, rounds that product half up to whole cents, and caps it at the per-type service cap — $2,500 (250,000 cents) for `INVESTIGATOR`, $5,000 (500,000 cents) for `EXPERT_PSYCH`, and $7,500 (750,000 cents) for `EXPERT_FORENSIC` — storing the lesser of the two into `authorized_amount_cents`. An `AssignmentCoordinator` later marks the request `COMPLETED`, which requires it to be `APPROVED` (else `ERR_SERVICE_REQUEST_NOT_APPROVED`); completion is what unlocks a service voucher for the work.

### 3.7. Panel and Service Voucher Billing

Payment flows through vouchers. An `Attorney` creates a `Voucher` in `DRAFT`, supplying the `case_id`, the `attorney_id` (which must equal their own `X-User-ID`), the `voucher_type` (`PANEL_FEE` or `SERVICE`), the `claimed_hours` (greater than zero), and, for a service voucher only, the `service_request_id` of the completed service; for a panel-fee voucher that link is null. New vouchers open with `approved_amount_cents` 0. Vouchers can be fetched or listed, filtered by `case_id`, `attorney_id`, and `service_request_id`.

The voucher lifecycle is `DRAFT → SUBMITTED → APPROVED`, with a rejection loop and a terminal void. An `Attorney` submits a draft, which requires `DRAFT` status (else `ERR_VOUCHER_INVALID_STATE`). Submission has a type-dependent precondition: a `PANEL_FEE` voucher may be submitted only once its parent case is `DISPOSED` (else `ERR_CASE_NOT_DISPOSED`), while a `SERVICE` voucher may be submitted only once its linked `ServiceRequest` is `COMPLETED` (else `ERR_SERVICE_REQUEST_NOT_COMPLETED`). A `SupervisingAttorney` approves a submitted voucher (requiring `SUBMITTED`, else `ERR_VOUCHER_INVALID_STATE`) or rejects it to `REJECTED` (same state requirement). An `Attorney` may revise a rejected voucher, returning it from `REJECTED` to `DRAFT` (else `ERR_VOUCHER_INVALID_STATE`), which resets `approved_amount_cents` to 0 and allows `claimed_hours` to be re-edited before the next submission; this REJECTED-to-DRAFT-to-SUBMITTED path may cycle. Finally, a `SupervisingAttorney` may void an approved voucher, moving it from `APPROVED` to the terminal `VOIDED` (else `ERR_VOUCHER_INVALID_STATE`).

Approval is where the amount is settled. The server first computes a gross figure by rounding, half up to whole cents, the product of `claimed_hours` and the applicable hourly rate. For a `PANEL_FEE` voucher the rate is the attorney's `hourly_rate_cents`, and the payable amount is capped by the case fee cap for the charge class net of prior panel approvals: take the case fee cap — $7,500 (750,000 cents) for `FELONY_A`, $5,000 (500,000 cents) for `FELONY_B`, $2,000 (200,000 cents) for `MISDEMEANOR`, $3,000 (300,000 cents) for `JUVENILE`, and $6,000 (600,000 cents) for `APPEAL` — subtract the sum of `approved_amount_cents` across this case's `PANEL_FEE` vouchers already in `APPROVED` status, floor that remaining cap at zero, and set `approved_amount_cents` to the lesser of the gross and the remaining cap. For a `SERVICE` voucher the rate is the linked `ServiceRequest`'s `estimated_rate_cents`, and the cap is that service request's `authorized_amount_cents` net of prior service approvals: subtract the sum of `approved_amount_cents` across vouchers already `APPROVED` against the same service request, floor the remainder at zero, and set `approved_amount_cents` to the lesser of the gross and that remaining cap.

Approving a voucher debits the office ledger: the office's `voucher_spent_cents` increases by the voucher's `approved_amount_cents`, and because spending rose, if `voucher_spent_cents` now exceeds ninety percent of the office's `annual_voucher_budget_cents` the office's `budget_status` flips to `RESTRICTED`. Voiding an approved voucher compensates that debit: the office's `voucher_spent_cents` decreases by the same `approved_amount_cents`, and if the result is at or below ninety percent of the budget the office returns to `OPEN`.

### 3.8. Disposition, Recoupment, and Collections

An `AssignmentCoordinator` disposes an assigned case, supplying the `disposition_type` (`DISMISSED`, `PLEA`, `ACQUITTAL`, or `CONVICTION`). Disposition requires the case to be `ASSIGNED`, else `ERR_CASE_NOT_ASSIGNED`. On disposition the case moves to the terminal `DISPOSED` state, its `disposition_type` is stored, and its `disposition_date` captures the current logical-clock UTC instant. Disposition then cascades in a chain: the case's `ACTIVE` `Assignment` closes (transitions to `CLOSED`); because that assignment closed, the holding attorney's `current_weighted_load` decreases by that assignment's `assigned_weight`; and because that load dropped, if the attorney was `AT_CAPACITY` and their load now sits below their `max_weighted_caseload`, the attorney reverts to `ACTIVE`.

Disposition has one further consequence. If the case's decided `FinancialScreening` had a `result` of `PARTIAL`, the server automatically creates a `RecoupmentOrder` against the case in `status` `ASSESSED`, with `collected_amount_cents` 0. The order's `basis` is copied from the office's `recoupment_basis` at creation, and the `assessed_amount_cents` is computed accordingly. Under a `SCHEDULE` basis the assessed amount is the flat statutory figure for the charge class — $500 (50,000 cents) for `FELONY_A`, $400 (40,000 cents) for `FELONY_B`, $150 (15,000 cents) for `MISDEMEANOR`, $100 (10,000 cents) for `JUVENILE`, and $350 (35,000 cents) for `APPEAL`. Under an `ACTUAL` basis the assessed amount is the means-based `contribution_amount_cents` from the case's decided screening, which can differ from the schedule figure for identical case data. An office declares its `recoupment_basis` (`SCHEDULE` or `ACTUAL`, defaulting to `SCHEDULE`) at creation, and a `DefenderOffice` is created by a `SupervisingAttorney` from a `name` and an `annual_voucher_budget_cents`; the office is readable by any role. Recoupment orders are never created directly by clients — they surface only from disposition — and can be fetched or listed, filtered by `case_id` and `status`.

Collections are recorded by a `SupervisingAttorney`, who supplies an `amount_cents` payment. Collection is allowed only while the order is `ASSESSED` or `PARTIALLY_COLLECTED` (else `ERR_RECOUPMENT_NOT_COLLECTIBLE`) and the amount must be positive. Each collection adds `amount_cents` to `collected_amount_cents`; if the running total is still below the `assessed_amount_cents` the order sits in `PARTIALLY_COLLECTED`, and once the running total reaches or exceeds the assessed amount the order becomes `SATISFIED`. A single payment at or above the full assessed amount takes an `ASSESSED` order straight to `SATISFIED`.

Alternatively, a `SupervisingAttorney` may waive an outstanding order, which requires the order to be `ASSESSED` or `PARTIALLY_COLLECTED` (else `ERR_RECOUPMENT_NOT_COLLECTIBLE`) and moves it to the terminal `WAIVED`, recording the waiving user into `waived_by_user_id`. Waiver enforces segregation of duties: the `X-User-ID` performing the waiver must differ from the `decided_by_user_id` recorded on that case's `FinancialScreening`. The officer who judged a defendant eligible may not also forgive that defendant's debt; an attempt to do so is rejected with `ERR_SEGREGATION_OF_DUTIES`. `SATISFIED` and `WAIVED` are the two terminal states of a recoupment order.

## 4. Endpoint Definitions

All endpoints return the standard envelope. Resource-creating endpoints respond with HTTP 201 and the created resource; state transitions and other modifications respond with HTTP 200 and the updated resource; reads respond with 200. Error responses use the status codes listed in Section 5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/defender-offices` | Create a defender office / funding unit | SupervisingAttorney |
| GET | `/defender-offices/{officeId}` | Get a defender office | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/attorneys` | Register a staff or panel attorney | SupervisingAttorney |
| GET | `/attorneys/{attorneyId}` | Get an attorney | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| GET | `/attorneys` | List attorneys; filter by office_id/status | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/attorneys/{attorneyId}/suspend` | Suspend an attorney | SupervisingAttorney |
| POST | `/attorneys/{attorneyId}/reactivate` | Reactivate a suspended attorney | SupervisingAttorney |
| POST | `/courtrooms` | Create a courtroom | SupervisingAttorney |
| GET | `/courtrooms/{courtroomId}` | Get a courtroom | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/cases` | Refer a new case (intake) | IntakeClerk |
| GET | `/cases/{caseId}` | Get a case | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| GET | `/cases` | List cases; filter by office_id/status | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/cases/{caseId}/reassign` | Reassign a case to a new attorney (OCC on case version) | AssignmentCoordinator |
| POST | `/cases/{caseId}/adjust-weight` | Recompute case weight to actual basis | AssignmentCoordinator |
| POST | `/cases/{caseId}/dispose` | Record disposition and close the case | AssignmentCoordinator |
| POST | `/financial-screenings` | Submit a financial-eligibility screening | IntakeClerk |
| GET | `/financial-screenings/{screeningId}` | Get a financial screening | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| GET | `/financial-screenings` | List screenings; filter by case_id | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/financial-screenings/{screeningId}/decide` | Decide eligibility; drives the case fork | ScreeningOfficer |
| POST | `/conflict-checks` | Run a conflict check for (case, attorney) | AssignmentCoordinator |
| GET | `/conflict-checks/{conflictCheckId}` | Get a conflict check | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| GET | `/conflict-checks` | List conflict checks; filter by case_id/attorney_id | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/assignments` | Assign a screened case to an attorney | AssignmentCoordinator |
| GET | `/assignments/{assignmentId}` | Get an assignment | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| GET | `/assignments` | List assignments; filter by case_id/attorney_id/status | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/court-events` | Calendar a court event for an assigned case | AssignmentCoordinator |
| GET | `/court-events/{courtEventId}` | Get a court event | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| GET | `/court-events` | List court events; filter by case_id/attorney_id/courtroom_id/status | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/court-events/{courtEventId}/vacate` | Vacate a scheduled court event | AssignmentCoordinator |
| POST | `/service-requests` | Request an investigator or expert | AssignmentCoordinator |
| GET | `/service-requests/{serviceRequestId}` | Get a service request | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| GET | `/service-requests` | List service requests; filter by case_id | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/service-requests/{serviceRequestId}/approve` | Approve a service request | SupervisingAttorney |
| POST | `/service-requests/{serviceRequestId}/complete` | Mark a service request completed | AssignmentCoordinator |
| POST | `/vouchers` | Create a draft voucher (panel fee or service) | Attorney |
| GET | `/vouchers/{voucherId}` | Get a voucher | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| GET | `/vouchers` | List vouchers; filter by case_id/attorney_id/service_request_id | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/vouchers/{voucherId}/submit` | Submit a draft voucher for approval | Attorney |
| POST | `/vouchers/{voucherId}/approve` | Approve a submitted voucher; debit office budget | SupervisingAttorney |
| POST | `/vouchers/{voucherId}/reject` | Reject a submitted voucher | SupervisingAttorney |
| POST | `/vouchers/{voucherId}/revise` | Return a rejected voucher to draft | Attorney |
| POST | `/vouchers/{voucherId}/void` | Void an approved voucher; compensate budget | SupervisingAttorney |
| GET | `/recoupment-orders/{recoupmentOrderId}` | Get a recoupment order | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| GET | `/recoupment-orders` | List recoupment orders; filter by case_id | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |
| POST | `/recoupment-orders/{recoupmentOrderId}/collect` | Record a recoupment collection | SupervisingAttorney |
| POST | `/recoupment-orders/{recoupmentOrderId}/waive` | Waive a recoupment order | SupervisingAttorney |
| POST | `/_clock/set_current_utc` | Set the server logical clock | IntakeClerk, ScreeningOfficer, AssignmentCoordinator, SupervisingAttorney, Attorney |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_USER_CONTEXT | 400 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_STALE_CASE_VERSION | 412 |
| ERR_OFFICE_NOT_FOUND | 404 |
| ERR_ATTORNEY_NOT_FOUND | 404 |
| ERR_COURTROOM_NOT_FOUND | 404 |
| ERR_CASE_NOT_FOUND | 404 |
| ERR_SCREENING_NOT_FOUND | 404 |
| ERR_CONFLICT_CHECK_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_COURT_EVENT_NOT_FOUND | 404 |
| ERR_SERVICE_REQUEST_NOT_FOUND | 404 |
| ERR_VOUCHER_NOT_FOUND | 404 |
| ERR_RECOUPMENT_ORDER_NOT_FOUND | 404 |
| ERR_CASE_NOT_SCREENED | 409 |
| ERR_CASE_NOT_ASSIGNED | 409 |
| ERR_CASE_NOT_DISPOSED | 409 |
| ERR_SCREENING_ALREADY_DECIDED | 409 |
| ERR_ATTORNEY_NOT_ACTIVE | 409 |
| ERR_SERVICE_REQUEST_NOT_APPROVED | 409 |
| ERR_SERVICE_REQUEST_NOT_COMPLETED | 409 |
| ERR_VOUCHER_INVALID_STATE | 409 |
| ERR_COURT_EVENT_NOT_SCHEDULED | 409 |
| ERR_RECOUPMENT_NOT_COLLECTIBLE | 409 |
| ERR_SCREENING_ALREADY_EXISTS | 409 |
| ERR_CONFLICT_NOT_CLEARED | 409 |
| ERR_CASELOAD_CAPACITY_EXCEEDED | 409 |
| ERR_EVENT_IN_PAST | 409 |
| ERR_ATTORNEY_SCHEDULE_CONFLICT | 409 |
| ERR_COURTROOM_DOUBLE_BOOKED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_BUDGET_RESTRICTED | 402 |
