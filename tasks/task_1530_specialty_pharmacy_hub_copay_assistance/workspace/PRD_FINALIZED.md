# Specialty Pharmacy Hub API — Product Requirements Document

## 1. Introduction

Specialty medications — high-cost, limited-distribution therapies for complex diagnoses — reach patients only after clearing a gauntlet of benefits checks, prior authorizations, financial-assistance matching, cold-chain logistics, and mandatory patient education. Manufacturer-sponsored hub programs exist to shepherd each patient through that gauntlet, and this document specifies the REST API that operates such a hub. The system coordinates seven distinct operator roles across the full patient journey: enrollment and benefits investigation, prior authorization submission with appeal support, copay card and charitable foundation assistance matching under accumulator-aware rules, shipment scheduling with cold-chain enforcement and adherence-based refill gating, nurse-led injection training, adverse-event reporting back to the manufacturer, and periodic outcomes reporting to the payer.

Two design commitments shape everything that follows. First, every cent of manufacturer or charitable assistance is tracked explicitly — reserved, disbursed at ship time, reversed on spoilage, and returned at release — so that card balances and foundation pool balances reconcile exactly at every step. Second, all time-dependent behavior (delivery-date validation, adherence measurement, funding windows, and the adverse-event reporting window) is evaluated against a server-side logical clock rather than wall-clock time, so that system behavior is deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints are mounted under the `/hub` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the user's operational capacity. The system recognizes exactly seven roles: `HubAdmin`, `CaseManager`, `FinancialCounselor`, `NurseEducator`, `PharmacyPartner`, `PayerReviewer`, and `ManufacturerMonitor`. A request missing either header, carrying a blank header value, or naming a role outside these seven is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`; the same code applies when a `NurseEducator` attempts to resolve a nurse visit assigned to a different nurse.

For all seven roles, `X-User-ID` is an opaque operator identifier not tied to the `id` of any persisted entity, and it is never compared against any entity's `id`. Where the workflows below persist or compare the identifier, they do so against dedicated operator fields, not entity identities. When `X-User-Role` is `CaseManager`, the server records the identifier as `case_manager_id` on each Enrollment the operator creates (audit only; no ownership restriction follows), as `reported_by_user_id` on each adverse event the operator files, and as `created_by_user_id` on each outcome report the operator creates. When `X-User-Role` is `FinancialCounselor`, the identifier is recorded as `matched_by_user_id` on each CopayAssistance the operator matches, where it later anchors the segregation-of-duties check at release time. When `X-User-Role` is `NurseEducator`, the identifier is compared against a visit's `nurse_id` at resolution time, is recorded as `completed_by_user_id` on the resolved visit, and is recorded as `reported_by_user_id` when the nurse files an adverse event. When `X-User-Role` is `HubAdmin`, `PharmacyPartner`, `PayerReviewer`, or `ManufacturerMonitor`, the identifier authorizes the action but is not persisted onto or compared against any resource field.

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

List endpoints paginate through two query parameters. The `limit` parameter specifies the maximum number of items to return: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, giving a stable chronological listing. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, marking creation and the most recent modification respectively. The `version` field is an integer that increments by one on every mutation of the resource and serves as the basis for optimistic concurrency control. One entity is exempt from the full set: a BenefitsInvestigation is immutable once created and therefore carries only `id` and `created_at` — both `updated_at` and `version` are absent from it. Whenever a cascade or a child-side action mutates a parent entity (for example, a nurse visit completion that increments an enrollment's training counter), that mutation refreshes the parent's `updated_at` and increments its `version` just as a direct write would.

### 2.5. The Logical Clock

The server maintains a logical clock that governs every time-sensitive rule in the system. At startup, before any clock operation is received, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `HubAdmin` advances the clock through an admin-only capability that accepts a target instant supplied as `to_iso8601` in ISO 8601 UTC; the response reports the resulting clock reading as `current_utc`. All date and time comparisons — a `requested_delivery_date` that must not lie in the past, an `awareness_at` that must not lie in the future, the 24-hour adverse-event reporting window, foundation funding windows, and every adherence evaluation — resolve against this logical clock.

### 2.6. Validation Order

Incoming requests pass through a fixed cascade of checks, evaluated in the following order, and the first failing check determines the error returned:

1. **Authentication.** Presence and validity of `X-User-ID` and `X-User-Role`; failures yield `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization.** The declared role must be authorized for the endpoint, and a nurse visit resolution additionally requires the caller's identity to match the visit's assigned nurse; failures yield `ERR_FORBIDDEN` (HTTP 403).
3. **Existence of path identifiers.** Path identifiers are resolved left to right, and the first unresolved identifier yields its per-resource 404 (see §2.7).
4. **Request body schema.** Required fields present, types valid, enum values in range, and dates parseable — including the two date-sanity rules that a `requested_delivery_date` must fall on or after the current logical clock date and an `awareness_at` must be no later than the current logical clock time; failures yield `ERR_VALIDATION` (HTTP 400).
5. **State validity.** The target entity must not be terminal and must be in a valid from-state for the operation: a terminal enrollment rejects all child-mutating operations with `ERR_ENROLLMENT_DISCONTINUED` (HTTP 409); a terminal prior authorization, assistance, shipment, visit, adverse event, or outcome report rejects any further transition with `ERR_ALREADY_TERMINAL` (HTTP 409); an operation attempted from the wrong non-terminal state — including shipment creation when the enrollment is not ready and outcome report creation outside the permitted enrollment states — yields `ERR_INVALID_TRANSITION` (HTTP 409), except shipment creation against a non-ready enrollment, which carries the dedicated `ERR_ENROLLMENT_NOT_READY_FOR_SHIPMENT` (HTTP 409). A stale enrollment version on a concurrency-guarded write is rejected here with `ERR_STALE_VERSION` (HTTP 412).
6. **Compliance and safety gates.** Cold-chain transit limits (`ERR_COLD_CHAIN_EXCEEDED`, HTTP 422), the adverse-event reporting window (`ERR_AE_REPORT_WINDOW_MISSED`, HTTP 422), and the segregation-of-duties rule on grant release (`ERR_SEGREGATION_OF_DUTY`, HTTP 403).
7. **Domain constraints.** The first-fill training gate (`ERR_TRAINING_INCOMPLETE`, HTTP 422), the refill adherence gate (`ERR_ADHERENCE_TOO_LOW`, HTTP 422), prior authorization attempted when the plan does not require one (`ERR_PA_NOT_REQUIRED`, HTTP 422), malformed visit windows (`ERR_VISIT_WINDOW_INVALID`, HTTP 422), and outcome-report periods closed by a submitted report (`ERR_REPORT_PERIOD_CLOSED`, HTTP 422).
8. **Temporal conflicts.** Overlapping nurse visit windows (`ERR_VISIT_WINDOW_OVERLAP`, HTTP 409) and refill spacing violations (`ERR_REFILL_SPACING_VIOLATION`, HTTP 422).
9. **Funding capacity.** Foundation matching against an empty eligible pool set (`ERR_NO_ELIGIBLE_FOUNDATION`, HTTP 422).

The ordering is observable. A shipment request naming a missing enrollment surfaces the 404 before its body is even inspected; a stale-version outcome report create surfaces `ERR_STALE_VERSION` before its period-overlap check runs; and on shipment creation a cold-chain violation surfaces before the training or adherence gates, which in turn surface before refill spacing is examined.

### 2.7. Nested Resource Retrieval

Every endpoint path that names one or more resource identifiers validates those identifiers in strict left-to-right order, and the request is rejected immediately with the 404 that corresponds to the first identifier that does not resolve. Each resource type carries its own not-found code: `ERR_DRUG_PROGRAM_NOT_FOUND` (including enrollment creation that names an unknown program), `ERR_FOUNDATION_POOL_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PRIOR_AUTHORIZATION_NOT_FOUND`, `ERR_COPAY_ASSISTANCE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_NURSE_VISIT_NOT_FOUND`, `ERR_ADVERSE_EVENT_NOT_FOUND`, and `ERR_OUTCOME_REPORT_NOT_FOUND`. A nested request therefore never proceeds to body or state validation while a parent identifier is unresolved.

### 2.8. Monetary Precision and Percentage Rounding

All monetary fields are integer cents; copay card splits require no rounding at all. Where a percentage-based foundation grant produces a fractional cent, the amount is rounded half-up to a whole cent, and that rounding is applied per fill before any summation takes place (see §3.6). Adherence percentages are reported rounded half-up to exactly one decimal place. Monetary values appear in API responses as JSON numbers.

### 2.9. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, both against the Enrollment's `version`. Running a copay-assistance match requires the request body to carry `expected_enrollment_version`, holding the enrollment `version` the client last observed; if that value does not match the enrollment's current `version`, the match is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful match supersedes any non-terminal assistance and increments the enrollment's `version` by one, so a writer carrying the previously observed version would otherwise be acting on a stale view of the enrollment. Creating an outcome report is guarded identically: the request must carry `expected_enrollment_version`, a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and a successful create supersedes overlapping draft reports and increments the enrollment's `version` by one. No endpoint other than these two accepts a version field.

### 2.10. Cascading Consistency Across the Enrollment Hierarchy

The Enrollment is the aggregate root of the hub's working state, and several of its transitions propagate automatically to child resources without any explicit client request against them. Approval of an enrollment activates a reserved assistance and schedules shipments that were waiting on financial clearance; termination of an enrollment releases every non-terminal assistance with its undisbursed funds returned and cancels every shipment still awaiting fulfillment. A spoil event likewise cascades in two links, compensating the funding assistance first and rolling back the payer-side accrual second. Each resource touched by a cascade is genuinely mutated — its `updated_at` refreshes and its `version` increments — so downstream readers and concurrency-guarded writers always observe the cascade's effects.

## 3. Business Logic & Workflows

### 3.1. Program and Foundation Configuration

A `HubAdmin` configures each manufacturer drug program by supplying its display `name`, the sponsoring `manufacturer_name`, and the ICD-10-style `diagnosis_code` the program covers. Two policy flags drive downstream gates: `requires_injection_training` demands at least one completed nurse training session before a first fill may be created, and `requires_cold_chain` binds every shipment's planned transit duration to the program's `max_transit_hours`. Refill cadence is governed by `min_days_between_fills`, the minimum gap in days between one delivered fill and the next requested delivery. Copay card economics live on the program as well: `copay_card_per_fill_cap_cents` caps the card's payout per fill, `copay_card_annual_cap_cents` caps the annual benefit per patient, and `default_days_supply` records the default days of therapy a fill supplies.

Charitable funding enters the system as foundation pools, also created by a `HubAdmin`. A pool is defined by its fund `name`, the `diagnosis_code` it covers, its `total_funding_cents` endowment (immutable after creation), the fixed `grant_amount_cents` reserved per matched patient, the `coverage_pct` of per-fill patient cost share the grant covers (from 0 to 100), and an inclusive funding window from `start_date` through `end_date` in `YYYY-MM-DD` form. At creation, the pool's `remaining_balance_cents` initializes to `total_funding_cents`; thereafter it decreases by `grant_amount_cents` each time a patient is matched against the pool and increases by a grant's undisbursed remainder whenever a grant is released or superseded. Pool balances remain readable by every role so that fund reconciliation is always possible.

### 3.2. Patient Enrollment and Benefits Investigation

A `CaseManager` enrolls a patient into a program by submitting a payload containing the target `program_id`, an external de-identified `patient_ref`, and the patient's `diagnosis_code`, which later drives foundation eligibility matching. Naming a program that does not exist is rejected with `ERR_DRUG_PROGRAM_NOT_FOUND`. The new Enrollment opens in `INTAKE`, with the creator's header identity stamped into `case_manager_id` for audit purposes only. Its counters begin at zero — `training_sessions_completed` and `fills_delivered_count` both start at 0, and `payer_accumulated_oop_cents` starts at 0 — while `remaining_oop_cents` stays null until a benefits investigation exists and `therapy_start_date` stays null until the first delivery. The adherence projections `pdc_confirmed_pct` and `pdc_provisional_pct` are likewise null until `therapy_start_date` is set. The enrollment listing supports optional filtering by `status` and `program_id` alongside the standard `limit` and `offset` pagination parameters.

An enrollment's `status` moves through eight possible values — `INTAKE`, `BENEFITS_VERIFIED`, `PA_PENDING`, `PA_DENIED`, `APPROVED`, `ACTIVE`, `DENIED_CLOSED`, and `DISCONTINUED` — of which `DENIED_CLOSED` and `DISCONTINUED` are terminal.

The benefits investigation is the enrollment's first milestone, and exactly one investigation may exist per enrollment; it is immutable once recorded. A `CaseManager` records the `payer_name`, the patient's `member_id` at the payer, whether the plan `requires_prior_auth`, whether the plan `plan_has_accumulator` (true when the plan runs a copay accumulator program that excludes manufacturer assistance from out-of-pocket accrual), the per-fill `patient_cost_share_cents` before any assistance, and the patient's annual `oop_max_cents`. Like every child record in the hub, the investigation carries an `enrollment_id` reference back to its parent enrollment. Creating the investigation while the enrollment is in `INTAKE` — with no prior investigation on file — moves the enrollment to `BENEFITS_VERIFIED` and sets `remaining_oop_cents` to the reported `oop_max_cents`. When the plan does not require prior authorization, the same creation immediately advances the enrollment from `BENEFITS_VERIFIED` to `APPROVED`, again setting `remaining_oop_cents` to `oop_max_cents`, and fires the approval cascade: any `RESERVED` assistance on the enrollment activates, and any `REQUESTED` shipments whose financial clearance is now open move to `SCHEDULED`. Reading the investigation back returns an array of length zero or one.

A `CaseManager` may discontinue any enrollment that has not reached a terminal state — that is, one sitting in `BENEFITS_VERIFIED`, `PA_PENDING`, `PA_DENIED`, `APPROVED`, or `ACTIVE` — optionally passing a `reason`. Discontinuation lands the enrollment in `DISCONTINUED` and cascades: every non-terminal assistance is released with its undisbursed funds returned to the funding source, and every shipment still `REQUESTED` or `SCHEDULED` is cancelled. Once an enrollment stands in `DISCONTINUED` or `DENIED_CLOSED`, every child-mutating operation against it is rejected with `ERR_ENROLLMENT_DISCONTINUED`.

### 3.3. Prior Authorization, Decisions, and Appeals

When the benefits investigation reports that the plan requires prior authorization, a `CaseManager` prepares the submission with `clinical_notes` justifying the therapy and a payer-facing `payer_reference`. Creation is only valid while the enrollment is in `BENEFITS_VERIFIED` — attempting it from any other enrollment state is `ERR_INVALID_TRANSITION` — and only when the investigation's `requires_prior_auth` is true; submitting a prior authorization for a plan that does not require one is rejected with `ERR_PA_NOT_REQUIRED`. These two gates are evaluated in §2.6's fixed order — the enrollment-state check precedes the plan-requirement check — so an attempt that would fail both, as when the enrollment has already auto-advanced past `BENEFITS_VERIFIED` on an investigation that reported `requires_prior_auth` false, is rejected with `ERR_INVALID_TRANSITION`. The new PriorAuthorization enters `SUBMITTED` with an `appeal_round` of zero, and the enrollment moves `BENEFITS_VERIFIED` → `PA_PENDING`.

Decisions belong to the `PayerReviewer`, who supplies an `outcome` of `APPROVED` or `DENIED` together with an optional `rationale`. The supplied rationale is persisted as the authorization's `decision_rationale`, which remains null until the first decision is recorded. A decision acts on an authorization in `SUBMITTED` or `APPEALED`, and the branches unfold as follows. An `APPROVED` outcome moves the authorization `SUBMITTED` → `APPROVED` or `APPEALED` → `APPROVED` — `APPROVED` is terminal — and cascades the enrollment `PA_PENDING` → `APPROVED` with the full approval cascade: a `RESERVED` assistance activates, and `REQUESTED` shipments whose financial clearance is now open move to `SCHEDULED`. A `DENIED` outcome moves the authorization to `DENIED` whenever its `appeal_round` is below the hard cap of two appeal rounds (`MAX_APPEAL_ROUNDS`) — at the initial decision the round count is zero, which is always below the cap, so a first denial always lands in `DENIED`, and a denial of the first appeal, filed at round one, lands in `DENIED` as well. Each such denial cascades the enrollment `PA_PENDING` → `PA_DENIED`. A `DENIED` decision on an authorization in `APPEALED` whose `appeal_round` has reached two instead terminates the authorization in `DENIED_FINAL` and cascades the enrollment `PA_PENDING` → `DENIED_CLOSED`; the enrollment sits in `PA_PENDING` while the final appeal is under review. That final cascade releases any assistance standing in `RESERVED`, `ACTIVE`, or `EXHAUSTED` — computing its `returned_cents` and crediting the funding source — and cancels every shipment still `REQUESTED` or `SCHEDULED`.

A `CaseManager` may appeal a denial while the authorization stands in `DENIED` and its `appeal_round` remains below two, optionally refreshing the `clinical_notes`. The appeal moves the authorization `DENIED` → `APPEALED`, increments `appeal_round` by one, and swings the enrollment `PA_DENIED` → `PA_PENDING`. Appealing an authorization in any other non-terminal state — for instance one still `SUBMITTED` — is rejected with `ERR_INVALID_TRANSITION`, and any decision or appeal attempted on a terminal authorization (`APPROVED` or `DENIED_FINAL`) is rejected with `ERR_ALREADY_TERMINAL`.

### 3.4. Financial Assistance Matching and Fund Management

A `FinancialCounselor` matches an enrollment to assistance by supplying an `assistance_type` of `COPAY_CARD` or `FOUNDATION` together with the concurrency guard `expected_enrollment_version` described in §2.9. At most one non-terminal assistance may exist per enrollment: a successful match supersedes any existing non-terminal record, releasing it with its `returned_cents` computed — for a foundation grant the pool is credited — and increments the enrollment's `version` by one.

For a `COPAY_CARD` match, the new record copies the program's `copay_card_per_fill_cap_cents` into its `per_fill_cap_cents`, sets its `annual_benefit_cap_cents` from the program's `copay_card_annual_cap_cents`, and leaves both `foundation_pool_id` and `coverage_pct` null. For a `FOUNDATION` match, the system runs the pool selection algorithm. A pool is eligible when its `diagnosis_code` exactly matches the enrollment's `diagnosis_code`, when the current logical clock date falls on or after the pool's `start_date` and on or before its `end_date`, and when the pool's `remaining_balance_cents` is at least its `grant_amount_cents`. Eligible candidates rank by `coverage_pct` descending; ties break toward the earliest `start_date`, and any remaining tie breaks toward the earliest `created_at`. On success, the selected pool's `remaining_balance_cents` is debited by `grant_amount_cents`, and the new assistance copies the pool's `coverage_pct`, records the pool in `foundation_pool_id`, sets `annual_benefit_cap_cents` to the pool's `grant_amount_cents`, and leaves `per_fill_cap_cents` null. An empty candidate set rejects the match with `ERR_NO_ELIGIBLE_FOUNDATION`: no assistance is created, no pool is mutated, and the enrollment's `version` is not incremented.

Every new assistance begins with `remaining_annual_benefit_cents` equal to its `annual_benefit_cap_cents`, `disbursed_cents` at zero, and the matching counselor's identity stamped into `matched_by_user_id`. The record is born `RESERVED`, unless the enrollment already stands in `APPROVED` or `ACTIVE`, in which case it activates immediately. Activation — the `RESERVED` → `ACTIVE` transition, which also fires when the enrollment later reaches approval — opens financial clearance, and any `REQUESTED` shipments on the enrollment move to `SCHEDULED` as a consequence. An assistance walks four statuses: `RESERVED`, `ACTIVE`, `EXHAUSTED`, and the terminal `RELEASED`. When a ship-time disbursement drains `remaining_annual_benefit_cents` to exactly zero, the record moves `ACTIVE` → `EXHAUSTED`; should a later spoil reversal restore the remaining benefit above zero, the record automatically reverts `EXHAUSTED` → `ACTIVE`.

Release returns a grant's unused funding to its source. A `FinancialCounselor` may release any non-terminal assistance — `RESERVED`, `ACTIVE`, or `EXHAUSTED` — and enrollment termination (§3.2, §3.3) releases it automatically. Manual release carries a segregation-of-duties guard: the releasing user's `X-User-ID` must differ from the record's `matched_by_user_id`, and a same-user release attempt is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403). Release computes `returned_cents` as the `annual_benefit_cap_cents` minus the cumulative `disbursed_cents` — for an `EXHAUSTED` record this equals the full cap, since disbursement has reached the cap — and, for a `FOUNDATION` grant, credits that amount back to the pool's `remaining_balance_cents`. Assistance history is listable both per enrollment and per foundation pool, the latter showing every grant drawn from that pool, each listing in chronological order.

### 3.5. Nurse Education and Injection Training

A `CaseManager` schedules a nurse education visit by naming the assigned nurse through `nurse_id` — an opaque identifier matching the resolving nurse's `X-User-ID` — together with a visit window from `window_start` to `window_end`, both ISO 8601 UTC instants. The window is half-open: it begins at `window_start` and ends strictly before `window_end`, and `window_end` must fall strictly after `window_start`; an empty or inverted window is rejected with `ERR_VISIT_WINDOW_INVALID`. Scheduling is conflict-checked per nurse: a new window that overlaps another `SCHEDULED` visit for the same `nurse_id` under half-open interval comparison is rejected with `ERR_VISIT_WINDOW_OVERLAP` (HTTP 409), while merely touching windows — one visit's `window_end` equal to the other's `window_start` — are permitted.

A visit is born `SCHEDULED`, and only the assigned nurse may resolve it: a resolution attempted under any other identity is rejected with `ERR_FORBIDDEN`. The nurse supplies an `outcome` of `COMPLETED` or `NO_SHOW`, and the resolver's identity is recorded in the visit's `completed_by_user_id`. A `COMPLETED` resolution increments the enrollment's `training_sessions_completed` by one — a parent mutation that bumps the enrollment's `version`, which concurrency-guarded writers will observe. Both outcomes are terminal; after a `NO_SHOW`, rescheduling means creating an entirely new visit. When the program's `requires_injection_training` flag is set, the first fill cannot be created until at least one session has completed, as enforced by the training gate in §3.6.

### 3.6. Shipment Fulfillment and the Patient Responsibility Split

A `CaseManager` requests a fill by supplying the `requested_delivery_date`, the planned `transit_hours`, and the `days_supply` of therapy the fill provides. The requested delivery date must fall on or after the current logical clock date, failing which the request is rejected with `ERR_VALIDATION`. Creation requires the enrollment to stand in `PA_PENDING`, `APPROVED`, or `ACTIVE`; any other non-terminal state yields `ERR_ENROLLMENT_NOT_READY_FOR_SHIPMENT`, and a terminal enrollment yields `ERR_ENROLLMENT_DISCONTINUED`. Each shipment receives a per-enrollment `fill_number`, one greater than the highest fill number already on the enrollment and starting at one, and a `fill_type` of `FIRST_FILL` when no prior `DELIVERED` shipment exists for the enrollment, otherwise `REFILL`. The patient's cost share is frozen at creation: the shipment's `patient_cost_share_cents` copies the benefits investigation's value, so later payer changes never retroactively alter a fill.

Creation-time gates apply in the order §2.6 fixes. Cold chain comes first: when the program's `requires_cold_chain` is set, the planned `transit_hours` must not exceed the program's `max_transit_hours`, and a shipment that would run longer is rejected with `ERR_COLD_CHAIN_EXCEEDED`. Next, the first-fill training gate: when the program's `requires_injection_training` is set, a `FIRST_FILL` requires `training_sessions_completed` of at least one, failing which creation is rejected with `ERR_TRAINING_INCOMPLETE`. Then the refill gates: a `REFILL` requires confirmed adherence of at least 80.0 percent (§3.7), failing which creation is rejected with `ERR_ADHERENCE_TOO_LOW`, and its `requested_delivery_date` must fall no earlier than the latest `DELIVERED` shipment's `delivered_date` plus the program's `min_days_between_fills` days — an earlier date is rejected with `ERR_REFILL_SPACING_VIOLATION`.

Where a shipment lands at creation depends on financial clearance. A shipment created while its enrollment sits in `PA_PENDING` enters `REQUESTED`, and so does one created under an `APPROVED` or `ACTIVE` enrollment while a `RESERVED` assistance still blocks clearance. Otherwise — enrollment `APPROVED` or `ACTIVE` with no `RESERVED` assistance present — the shipment enters `SCHEDULED` directly at creation. Whenever the enrollment reaches approval or an assistance activates, the system re-evaluates waiting shipments: a `REQUESTED` shipment on an `APPROVED` or `ACTIVE` enrollment with no `RESERVED` assistance moves to `SCHEDULED`.

The `PharmacyPartner` ships a `SCHEDULED` shipment. Shipping requires the enrollment to stand in `APPROVED` or `ACTIVE` and no `RESERVED` assistance to remain on it; attempting to ship a shipment still `REQUESTED` is rejected with `ERR_INVALID_TRANSITION`. At ship time the financial split runs against the shipment's frozen `patient_cost_share_cents`, and its three outputs — `assistance_pay_cents`, `patient_pay_cents`, and `payer_accumulator_delta_cents` — are null until the shipment reaches `SHIPPED`, at which point they are stamped onto it:

- With a non-terminal `COPAY_CARD` assistance whose `remaining_annual_benefit_cents` is positive, `assistance_pay_cents` is the smallest of three values — the assistance's `per_fill_cap_cents`, its `remaining_annual_benefit_cents`, and the frozen cost share — and `patient_pay_cents` is the frozen cost share minus the assistance portion. The assistance portion is never negative; its floor is zero cents.
- With a non-terminal `FOUNDATION` assistance whose remaining benefit is positive, the raw assistance amount is the frozen cost share multiplied by the grant's `coverage_pct` and divided by one hundred; that raw amount is rounded half-up to a whole cent for this fill, and `assistance_pay_cents` is the smaller of the rounded amount and the remaining annual benefit, with `patient_pay_cents` again the frozen cost share minus the assistance portion. The rounding order is pinned: each fill is rounded first, and `disbursed_cents` accumulates the per-fill rounded amounts. Computing the annual total first and rounding once is a different, non-conforming algorithm that yields different cents — a 999-cent cost share at 50 percent coverage over three fills disburses 500 + 500 + 500 = 1500 cents, whereas summing first and rounding once would yield 1499 cents.
- With no non-terminal assistance at all, or a remaining benefit of zero, `assistance_pay_cents` is zero and the patient pays the full frozen cost share; the accumulator variant below still applies.

The payer-side accrual then depends on the investigation's accumulator flag. Under an accumulator plan (`plan_has_accumulator` true), manufacturer assistance is excluded from the patient's out-of-pocket accrual, so `payer_accumulator_delta_cents` equals `patient_pay_cents`. Under a non-accumulator plan, assistance counts toward the out-of-pocket maximum, so the delta equals `patient_pay_cents` plus `assistance_pay_cents` — that is, the full frozen cost share. The same ship event debits the assistance: its `remaining_annual_benefit_cents` decreases by the assistance portion and its `disbursed_cents` increases by the same amount, firing the `EXHAUSTED` transition if the remainder reaches exactly zero. The enrollment then accrues: `payer_accumulated_oop_cents` becomes the smaller of the investigation's `oop_max_cents` and its prior value plus the delta, and `remaining_oop_cents` is recomputed as `oop_max_cents` minus the accumulated total.

Delivery is confirmed by the `PharmacyPartner` supplying a `delivered_date` — a field that stays null until this moment — moving a `SHIPPED` shipment to `DELIVERED`. The first delivery activates therapy: the enrollment moves `APPROVED` → `ACTIVE`, its `therapy_start_date` takes the shipment's `delivered_date`, and `fills_delivered_count` increments by one. Every subsequent delivery also increments `fills_delivered_count` by one and recomputes the adherence projections `pdc_confirmed_pct` and `pdc_provisional_pct`. Spoilage — a cold-chain excursion or damage in transit — moves a `SHIPPED` shipment to `SPOILED`, optionally accompanied by a `reason`, and triggers a two-link compensation cascade. First, the assistance that funded the fill is compensated: its `remaining_annual_benefit_cents` is increased by the fill's `assistance_pay_cents` and its `disbursed_cents` is decreased by the same amount, a step skipped entirely when the fill's assistance portion was zero or the assistance already stands `RELEASED`; if the restoration lifts the remaining benefit above zero, an `EXHAUSTED` assistance automatically reverts to `ACTIVE`. Second, the enrollment's `payer_accumulated_oop_cents` is reduced by the fill's `payer_accumulator_delta_cents`, never dropping below zero, and `remaining_oop_cents` is recomputed from the new total. Only a `SHIPPED` shipment can be delivered or spoiled. Enrollment termination cancels shipments still `REQUESTED` or `SCHEDULED` (moving them to `CANCELLED`); `DELIVERED`, `SPOILED`, and `CANCELLED` are terminal, and any further transition attempted on a terminal shipment is rejected with `ERR_ALREADY_TERMINAL`.

### 3.7. Adherence Measurement and Refill Gating

Adherence is measured as a proportion of days covered, evaluated in two variants over a window that opens at the enrollment's `therapy_start_date` and closes at the evaluation date. Both variants are null while `therapy_start_date` is null. The window length is the number of whole days from `therapy_start_date` to the evaluation date, floored at one day so a same-day evaluation still measures a one-day window. Covered days are the sum of `days_supply` across the variant's shipment set, capped at the window length. The percentage itself is one hundred times the covered days divided by the window days, rounded half-up to exactly one decimal place.

The confirmed variant counts only `DELIVERED` shipments; it feeds the enrollment's `pdc_confirmed_pct`, the refill gate below, and the adherence figure on outcome reports, and it is evaluated at the current logical clock date for the first two of those uses. The provisional variant counts shipments in `SHIPPED` or `DELIVERED`, feeding the enrollment's `pdc_provisional_pct` — the forward-looking outreach view. For identical data the provisional figure is never below the confirmed figure, and it is strictly greater whenever a shipped-but-not-yet-delivered fill exists. Both variants exclude `SPOILED` and `CANCELLED` shipments.

The refill gate stands at 80.0: creating a `REFILL` shipment requires the confirmed-variant percentage, evaluated at the current logical clock date, to be at least 80.0 — and exactly 80.0 passes the gate. A refill requested below the threshold is rejected with `ERR_ADHERENCE_TOO_LOW`.

### 3.8. Pharmacovigilance and Payer Outcomes Reporting

Adverse events are the hub's pharmacovigilance channel back to the manufacturer. A `CaseManager` or a `NurseEducator` reports an event by supplying `awareness_at` — the instant hub staff became aware of the event, in ISO 8601 UTC — a `seriousness` of `SERIOUS` or `NON_SERIOUS`, and a free-text `description`. The awareness instant may not lie in the future relative to the logical clock, on penalty of `ERR_VALIDATION`, and the report must be filed within 24 hours of awareness (`AE_REPORT_WINDOW_HOURS`); a filing that arrives later is rejected with `ERR_AE_REPORT_WINDOW_MISSED`. The reporter's identity lands in `reported_by_user_id`, and the event opens in `REPORTED`. A `ManufacturerMonitor` acknowledges receipt, moving a `REPORTED` event to the terminal `ACKNOWLEDGED`; an event in any other state cannot be acknowledged again, and transitions on the terminal event are rejected with `ERR_ALREADY_TERMINAL`.

Outcome reports close the loop with the payer. A `CaseManager` creates one by supplying `period_start` and `period_end` in `YYYY-MM-DD` form together with the concurrency guard `expected_enrollment_version`. The reporting period is half-open — it includes `period_start` and excludes `period_end`, and `period_end` must fall after `period_start`. Creation requires the enrollment to stand in `ACTIVE` or `DISCONTINUED`, with any other state rejected as `ERR_INVALID_TRANSITION`, and a successful creation increments the enrollment's `version` by one. At creation the system computes four metrics over the period. The `fills_delivered_count` counts the enrollment's `DELIVERED` shipments whose `delivered_date` falls within the period. The `adverse_event_count` counts the enrollment's events standing in `REPORTED` or `ACKNOWLEDGED` whose `awareness_at` date falls within the period. The `total_assistance_cents` sums `assistance_pay_cents` over that same delivered-shipment set. The `pdc_pct` is the confirmed-variant adherence evaluated with the period's end as the evaluation date, null when `therapy_start_date` is null or when the period end does not fall after `therapy_start_date`. Because the window is half-open, a delivery exactly on `period_end` is excluded from every metric. The creating manager's identity is recorded in `created_by_user_id`.

A new report begins in `DRAFT`. If its period overlaps the period of an existing `DRAFT` report for the same enrollment, that existing draft is superseded — moved `DRAFT` → `SUPERSEDED` — as part of the creation. If the period instead overlaps a `SUBMITTED` report for the enrollment, creation is rejected outright with `ERR_REPORT_PERIOD_CLOSED`. A `DRAFT` report may be submitted to the payer by a `CaseManager`, moving it `DRAFT` → `SUBMITTED`, which is terminal; since both `SUBMITTED` and `SUPERSEDED` are terminal states, any further transition on them is rejected with `ERR_ALREADY_TERMINAL`.

## 4. Endpoint Definitions

Operations that create a new resource — a program, pool, enrollment, investigation, authorization, assistance record, visit, shipment, adverse event, or outcome report — return a `201 Created` status code. Operations that modify an existing resource — decisions, appeals, releases, resolutions, shipment lifecycle actions, acknowledgements, submissions, discontinuation, and the clock capability — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hub/drug-programs` | Create a manufacturer drug program (configuration) | HubAdmin |
| POST | `/hub/foundation-pools` | Create a charitable foundation funding pool | HubAdmin |
| GET | `/hub/foundation-pools/{id}` | Read a foundation pool (balance visibility for reconciliation) | Any authenticated role |
| POST | `/hub/enrollments` | Enroll a patient into a drug program | CaseManager |
| GET | `/hub/enrollments/{id}` | Read one enrollment including computed adherence and OOP fields | Any authenticated role |
| GET | `/hub/enrollments` | List enrollments with optional filters and envelope pagination | Any authenticated role |
| POST | `/hub/enrollments/{id}/discontinue` | Discontinue a non-terminal enrollment; cascades release and cancellation | CaseManager |
| POST | `/hub/enrollments/{id}/benefits-investigation` | Record the benefits investigation (immutable once created) | CaseManager |
| GET | `/hub/enrollments/{id}/benefits-investigation` | Fetch the enrollment's benefits investigation (array of length 0 or 1) | Any authenticated role |
| POST | `/hub/enrollments/{id}/prior-authorization` | Create and submit a prior authorization | CaseManager |
| GET | `/hub/enrollments/{id}/prior-authorizations` | List prior authorizations for an enrollment | Any authenticated role |
| POST | `/hub/prior-authorizations/{id}/decision` | Record an APPROVED or DENIED payer decision | PayerReviewer |
| POST | `/hub/prior-authorizations/{id}/appeal` | Appeal a denied prior authorization | CaseManager |
| POST | `/hub/enrollments/{id}/copay-assistance/match` | Match copay card terms or a foundation grant (OCC-guarded) | FinancialCounselor |
| POST | `/hub/copay-assistances/{id}/release` | Manually release a non-terminal assistance | FinancialCounselor |
| GET | `/hub/enrollments/{id}/copay-assistances` | List copay assistance records for an enrollment | Any authenticated role |
| GET | `/hub/foundation-pools/{id}/copay-assistances` | List grants drawn from a foundation pool | Any authenticated role |
| POST | `/hub/enrollments/{id}/nurse-visits` | Schedule a nurse education / injection training visit | CaseManager |
| GET | `/hub/enrollments/{id}/nurse-visits` | List nurse visits for an enrollment | Any authenticated role |
| POST | `/hub/nurse-visits/{id}/resolve` | Assigned nurse resolves a scheduled visit | NurseEducator |
| POST | `/hub/enrollments/{id}/shipments` | Request a fill shipment | CaseManager |
| GET | `/hub/enrollments/{id}/shipments` | List shipments for an enrollment | Any authenticated role |
| POST | `/hub/shipments/{id}/ship` | Ship a scheduled shipment and apply the financial split | PharmacyPartner |
| POST | `/hub/shipments/{id}/deliver` | Confirm delivery; first delivery activates therapy | PharmacyPartner |
| POST | `/hub/shipments/{id}/spoil` | Report a shipped shipment spoiled; reverses disbursement and accrual | PharmacyPartner |
| POST | `/hub/enrollments/{id}/adverse-events` | Report an adverse event | CaseManager, NurseEducator |
| GET | `/hub/enrollments/{id}/adverse-events` | List adverse events for an enrollment | Any authenticated role |
| POST | `/hub/adverse-events/{id}/acknowledge` | Manufacturer acknowledges a reported adverse event | ManufacturerMonitor |
| POST | `/hub/enrollments/{id}/outcome-reports` | Create a draft outcomes report with computed metrics (OCC-guarded) | CaseManager |
| GET | `/hub/enrollments/{id}/outcome-reports` | List outcome reports for an enrollment | Any authenticated role |
| POST | `/hub/outcome-reports/{id}/submit` | Submit a draft outcomes report to the payer | CaseManager |
| POST | `/hub/_clock/set_current_utc` | Set the server's logical clock | HubAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DRUG_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_FOUNDATION_POOL_NOT_FOUND` | 404 Not Found |
| `ERR_PRIOR_AUTHORIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_COPAY_ASSISTANCE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_NURSE_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_ADVERSE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_OUTCOME_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_ENROLLMENT_DISCONTINUED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_READY_FOR_SHIPMENT` | 409 Conflict |
| `ERR_PA_NOT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_FOUNDATION` | 422 Unprocessable Entity |
| `ERR_TRAINING_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_COLD_CHAIN_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ADHERENCE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_REFILL_SPACING_VIOLATION` | 422 Unprocessable Entity |
| `ERR_VISIT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_VISIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AE_REPORT_WINDOW_MISSED` | 422 Unprocessable Entity |
| `ERR_REPORT_PERIOD_CLOSED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTY` | 403 Forbidden |
