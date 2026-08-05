# Mckinney-Vento School Transport API — Product Requirements Document

## 1. Introduction

The McKinney-Vento Homeless Assistance Act guarantees children experiencing homelessness — and those in foster care — the right to educational stability regardless of where they sleep at night. Translating that legal promise into day-to-day school operations means coordinating a surprising amount of machinery: a student must be enrolled immediately even before records arrive, a caseworker (the McKinney-Vento **liaison**) must verify eligibility, a school-of-origin bus route must be planned and paid for across two districts that share the cost, and the categorical meal and fee-waiver benefits that flow from an eligibility finding must be granted and later, if circumstances change, revoked.

This document specifies the REST API that ties those workflows together. The system is fundamentally a **ledger-reconciliation and compliance platform**: every transported ride books a signed charge against a serving district's running balance, every eligibility finding cascades into benefit grants and priority re-scoring, and every district's committed spend is reconciled against a funded budget ceiling before a plan may go live. Because several actors touch the same student and the same plan concurrently, the API layers optimistic-concurrency guards over the operations where a stale view could silently clobber a fresher one. The sections below define the global contract first, then walk the business logic entity by entity and workflow by workflow.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource paths are mounted under the `/mv` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles:

- `StateCoordinator` — the state-level McKinney-Vento coordinator responsible for oversight, reporting, dispute adjudication, and administrative setup. This role is a hierarchical superset that may perform essentially every operation in the system, and it exclusively owns district creation, liaison creation, the entire dispute-review adjudication path (beginning a review, requesting information, and resolving), and advancing the logical clock. When `X-User-Role` is `StateCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `Liaison` — the district McKinney-Vento liaison who manages a caseload, authors and finalizes eligibility determinations, files and resubmits disputes, opens and closes tutoring referrals, and revokes benefit links. When `X-User-Role` is `Liaison`, `X-User-ID` is the `id` of the acting `Liaison`; ownership checks on any resource that references a liaison compare the resource's `liaison_id` to `X-User-ID`.
- `TransportCoordinator` — the district transportation office that owns transportation plans, vehicles, trips, and cost-share agreements. When `X-User-Role` is `TransportCoordinator`, `X-User-ID` is the `id` of the acting `District`; ownership checks on any resource that references a district compare the resource's district foreign key to `X-User-ID`.
- `Registrar` — the district enrollment office that handles student intake, immediate enrollment, and withdrawal. When `X-User-Role` is `Registrar`, `X-User-ID` is the `id` of the acting `District`; ownership checks on any resource that references a district compare the resource's district foreign key to `X-User-ID`.

All four roles may perform every read (GET) operation.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint says otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation. It is the basis for optimistic concurrency control (§2.5).

The append-only ledger is the one exception. A `CostLedgerEntry` is an immutable event record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after it is written — a correction is expressed as a new, offsetting entry rather than an edit.

Timestamps generated by the server (for example `created_at`, `updated_at`, and the logical clock's readings) are rendered in UTC with a trailing `Z` and three fractional-second digits.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded against stale-view overwrites, and only those two carry a version-expectation field.

When a client creates a cost-share agreement, the request body must include `expected_transportation_plan_version` carrying the client's last observed `version` of the target `TransportationPlan`. If that value does not equal the plan's current `version` — meaning another writer advanced the plan since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A fresh agreement legitimately supersedes any prior agreement for the same plan, so a client working from an out-of-date plan view must be told to re-read rather than silently overwrite a newer agreement. A successful create increments the plan's `version` by one.

Likewise, when a client creates an eligibility determination for a student, the request body must include `expected_student_version` carrying the client's last observed `version` of the target `Student`. If it does not equal the student's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because a newly created determination supersedes any prior `DRAFT` for that student. A successful create increments the student's `version` by one.

No other endpoint accepts or requires a version-expectation field.

### 2.6. Monetary Values, Precision, and Rounding

All money in the system is stored and returned as **integer cents** — there are no fractional-cent balances persisted anywhere. Where a calculation multiplies a monetary amount by a fractional share, the product is rounded to the nearest whole cent using the **round-half-up** convention (a value ending in exactly half a cent rounds away from zero, upward).

Two rounding-order rules are pinned because they change results by a cent on fractional inputs:

- For a cost-share agreement's serving share, the fractional product is rounded to whole cents **first**, and the `SHARE_CAP_CENTS` ceiling is applied **after** that rounding.
- For an agreement's invoice, each completed trip's serving portion is rounded to whole cents **individually before** the portions are summed. Summing first and rounding once is explicitly not used and would differ by a cent on fractional half-cents.

### 2.7. Request Validation Order and Existence Resolution

When a request could fail more than one check, the checks are evaluated in a fixed priority order, and the first failure determines the error returned:

1. **Authentication** — headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for this operation, else `ERR_FORBIDDEN` (403).
3. **Existence** — every id in the path and every foreign-key reference in the body must resolve, validated left to right; the first unresolved reference returns that resource's specific not-found code (404). Each resource type has its own code: `ERR_DISTRICT_NOT_FOUND`, `ERR_LIAISON_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_BENEFIT_LINK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, and `ERR_LEDGER_ENTRY_NOT_FOUND`.
4. **Body well-formedness** — required fields present, enum values in range, all quantity integers non-negative, and any `scheduled_end` strictly after its `scheduled_start`; otherwise `ERR_VALIDATION` (422).
5. **Optimistic concurrency** — the version-expectation field, where required, matches the parent's current `version`, else `ERR_STALE_VERSION` (412).
6. **State** — the target resource is in a state that permits the transition, else a 409-class state error (see the workflow narratives in §3 for the specific code each transition raises).
7. **Referential, caseload, temporal, and fiscal business rules** — the remaining 409-class checks described throughout §3.

Because existence is resolved strictly left to right, a request naming a non-existent parent fails on the parent before the system ever looks for the child.

### 2.8. Derived-Field Reconciliation and Conserved-Quantity Invariants

Several fields are never written directly by a client; they are **reconciled** as a side effect of the operations that change their inputs, and each such reconciliation is itself a mutation that refreshes the affected resource's `updated_at` and increments its `version`.

A `District` carries three reconciled counters. Its `committed_cost_cents` is the sum of `serving_share_cents` across every cost-share agreement whose serving district is this district and whose plan is currently `ACTIVE` or `SUSPENDED`. Its `transport_balance_cents` is the running sum of the signed `amount_cents` of every ledger entry booked against it — trip charges add, reversals subtract. Its `categorical_eligible_count` is the number of `ACTIVE` benefit links naming this district. A `Liaison` carries `current_caseload`, the number of its assigned students that are eligible and not withdrawn. A `TransportationPlan` carries `actual_cost_cents`, and a `CostShareAgreement` carries its own `actual_cost_cents`; both accumulate from completed rides.

Several of these reconciliations are **conserved-quantity** pairs: an operation that adds to a counter has a compensating operation that removes exactly the same magnitude, restoring the counter to its earlier value. Revoking a benefit link decrements `categorical_eligible_count` by exactly the one it was incremented by at grant time. Voiding a completed trip books a reversal that subtracts exactly the magnitude the completion added to `transport_balance_cents`. Terminating a plan releases exactly the `serving_share_cents` that activation committed. These invariants are what let the ledger and the counters be trusted as the single source of truth.

### 2.9. The Logical Clock

Time in this system is driven by a logical clock rather than wall-clock time, so that time-dependent behavior is reproducible. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it, every read of "now" returns exactly that default — the server never falls back to real wall-clock time. A `StateCoordinator` may advance the clock by supplying a target instant as `to_iso8601`; the response reports the new `current_utc`. Timestamps such as `created_at` and `updated_at`, and any temporal comparison, are taken against this logical clock.

## 3. Business Logic & Workflows

### 3.1. Districts, Liaisons, and Caseload Management

A `District` is the administrative anchor of the system, created by a `StateCoordinator` with a `name`, a federal `nces_code` (the NCES LEA identifier), and a `transport_budget_cents` — the monthly ceiling this district is willing to fund in its role as a serving district. On creation its three reconciled counters — `committed_cost_cents`, `transport_balance_cents`, and `categorical_eligible_count` — all start at zero.

A `Liaison` is likewise created by a `StateCoordinator`, tied to an employing district via `district_id` and described by `full_name` and `email`. A liaison also has a `max_caseload`, the maximum number of eligible students it may carry; when the caller omits `max_caseload`, it defaults to 25. The liaison's `current_caseload` begins at zero and is thereafter recomputed as the count of students assigned to that liaison whose enrollment `status` is not `WITHDRAWN` and whose `eligibility_status` is `ELIGIBLE`.

Assigning a caseload liaison to a student — an action a `Liaison` or `StateCoordinator` performs by supplying the `liaison_id` — writes the student's `liaison_id` and recomputes the liaison's `current_caseload`. The assignment is rejected when it would push the liaison's caseload above its ceiling. The boundary is strict: a caseload of exactly `max_caseload` is allowed, and only an assignment that would make the count exceed `max_caseload` (that is, reach `max_caseload` plus one) is refused, with `ERR_LIAISON_CASELOAD_FULL`. Because the caseload counts only eligible, non-withdrawn students, a student who is not yet eligible does not consume a caseload slot at assignment time.

### 3.2. Student Intake, Immediate Enrollment, and Withdrawal

A student enters through intake, performed by a `Registrar` or `StateCoordinator`, who supplies `first_name`, `last_name`, `birthdate`, the `enrolled_district_id` of current enrollment, the `origin_district_id` of the school of origin (which may differ from the enrolled district), and the self-reported `living_situation`. Intake may optionally include a `self_declared_category` and a `records_received` flag; when omitted, `self_declared_category` defaults to `NONE` and `records_received` defaults to false. The `living_situation` is one of `SHELTER`, `UNSHELTERED`, `HOTEL_MOTEL`, `DOUBLED_UP`, `FOSTER_PLACEMENT`, or `HOUSED`; the `self_declared_category` is one of `HOMELESS`, `FOSTER`, or `NONE`. A freshly intaken student starts with enrollment `status` of `INTAKE`, `eligibility_status` of `UNDETERMINED`, an unset `liaison_id`, and a provisional priority score (§3.3).

Immediate enrollment is the heart of the McKinney-Vento right. A `Registrar` or `StateCoordinator` enrolls a student, moving `status` from `INTAKE` to `ENROLLED`. This succeeds regardless of whether `records_received` is true — arrival of prior-school records is deliberately **not** a precondition, so a homeless child is never blocked from enrolling for want of paperwork. Enrollment is only valid from `INTAKE`; attempting it from any other state raises `ERR_INVALID_STATE`.

Withdrawal, also a `Registrar` or `StateCoordinator` action, moves an `ENROLLED` student to the terminal `WITHDRAWN` state and triggers two cascades. First, every transportation plan for this student that is currently `APPROVED`, `ACTIVE`, or `SUSPENDED` is driven to `TERMINATED`, which in turn cancels that plan's `SCHEDULED` trips and, for any plan that had committed budget, releases the serving district's committed cost (see §3.5). Second, every `ACTIVE` benefit link for the student is driven to `REVOKED`, each revocation decrementing the enrolled district's `categorical_eligible_count`. Once a student is `WITHDRAWN`, mutating operations that target that student are refused; where a specific operation guards against this, it raises `ERR_STUDENT_WITHDRAWN`.

### 3.3. Eligibility Determinations, Finalization, and Priority Scoring

A student's `eligibility_status` and enrollment `status` evolve independently: eligibility is set only by determination finalization and dispute resolution, never by enrollment transitions. A `Liaison` or `StateCoordinator` opens an `EligibilityDetermination` for a student by supplying the `category` (`HOMELESS` or `FOSTER`), the verified `basis` (one of `NIGHT_TO_NIGHT`, `SHELTER`, `HOTEL_MOTEL`, `DOUBLED_UP`, `UNSHELTERED`, or `FOSTER`), the `decision` (`ELIGIBLE` or `INELIGIBLE`), and an `effective_date`. The create is guarded by optimistic concurrency: the request carries `expected_student_version`, and a mismatch with the student's current `version` is rejected with `ERR_STALE_VERSION` (§2.5). A new determination is born in `DRAFT` status and supersedes any prior draft for that student; a successful create increments the student's `version` by one.

Finalizing a determination — a `Liaison` or `StateCoordinator` action that moves it from `DRAFT` to the terminal `FINALIZED` state — is where the eligibility cascade fires. Finalization is permitted only from `DRAFT`; it additionally requires that the subject student not be `WITHDRAWN`, raising `ERR_STUDENT_WITHDRAWN` otherwise. On success, three hops execute in sequence. First, the student's `eligibility_status` is set to the determination's `decision`, and the student's `priority_score` is recomputed to its final variant with `priority_basis` set to `FINAL`. Second, if the decision was `ELIGIBLE` and the student currently has no `ACTIVE` benefit link, a new `BenefitLink` is created with `source` `AUTO_ELIGIBILITY`, `status` `ACTIVE`, and `district_id` equal to the student's `enrolled_district_id`. Third, that new benefit link increments the district's `categorical_eligible_count`. A benefit link grants the student categorical free meals and fee waivers.

The **priority score** exists in two variants, and which one a student's `priority_score` currently reflects is recorded in `priority_basis`. The provisional variant, computed at intake from the self-reported `living_situation`, assigns 50 points for `UNSHELTERED`, 40 for `SHELTER`, 35 for `FOSTER_PLACEMENT`, 30 for `HOTEL_MOTEL`, 20 for `DOUBLED_UP`, and 0 for `HOUSED`. The final variant, computed at finalization from the verified determination, assigns a base from the `basis` — 50 for `NIGHT_TO_NIGHT`, 50 for `UNSHELTERED`, 40 for `SHELTER`, 35 for `FOSTER`, 30 for `HOTEL_MOTEL`, and 20 for `DOUBLED_UP` — and then adds a 10-point bonus when the determination's `category` is `FOSTER`. Because the two variants read different inputs, the same student can move — for instance from a provisional 20 keyed on a self-reported `DOUBLED_UP` situation to a final 50 keyed on a verified `UNSHELTERED` basis — when the verified facts differ from what was self-reported at intake.

### 3.4. Disputes

A dispute lets a family contest an outcome. A `Liaison` or `StateCoordinator` files a `Dispute` for a student with a `dispute_type` (`ELIGIBILITY`, `ENROLLMENT`, or `TRANSPORT`) and a free-text `description`; it opens in `FILED` status with a null `outcome`. The adjudication path belongs exclusively to a `StateCoordinator`, except for one resubmission step reserved for the liaison.

Review is a cyclic workflow. A `StateCoordinator` begins review, moving the dispute from `FILED` to `UNDER_REVIEW`. From `UNDER_REVIEW` the coordinator may request more information, moving it to `INFO_REQUESTED`. From `INFO_REQUESTED`, a `Liaison` or `StateCoordinator` resubmits, returning the dispute to `FILED` so a fresh review round can start — this back-edge is what makes the machine cyclic. Each of these transitions is valid only from its named source state; an out-of-state attempt raises `ERR_INVALID_STATE`.

Resolution, from `UNDER_REVIEW`, is a `StateCoordinator` action that carries an `outcome`. When the `outcome` is `DENIED`, the dispute moves to `RESOLVED_DENIED` and records `outcome` `DENIED` with no further effect. When the `outcome` is `UPHELD`, the dispute moves to `RESOLVED_UPHELD`, records `outcome` `UPHELD`, and — if the student is not already `ELIGIBLE` — restores eligibility exactly as a favorable determination would: the student's `eligibility_status` is set to `ELIGIBLE`, and if the student has no `ACTIVE` benefit link, a new `BenefitLink` (`AUTO_ELIGIBILITY`, `ACTIVE`) is created and the district's `categorical_eligible_count` is incremented. Both terminal resolutions are reachable only from `UNDER_REVIEW`.

### 3.5. Transportation Plans and Cost Estimation

A `TransportCoordinator` or `StateCoordinator` drafts a `TransportationPlan` for a student, naming the transported `student_id`, the `origin_district_id` that bills a share, the `serving_district_id` that operates the route and bills the remaining share subject to its budget, and the one-way `route_miles`. On creation the plan computes its forward-looking estimates and starts in `DRAFT` with `actual_cost_cents` of zero. The `estimated_daily_cost_cents` is the route mileage multiplied by a per-mile rate of 155 cents plus a fixed per-trip base of 500 cents; the `estimated_monthly_cost_cents` is that daily estimate multiplied by 20 school days per month. These estimates are purely projective — they assume the route runs and do not depend on whether any ride has actually happened.

The plan then moves through a branching lifecycle, every transition driven by a `TransportCoordinator` or `StateCoordinator`. Submitting advances `DRAFT` to `PROPOSED`. From `PROPOSED`, the plan either advances to `APPROVED` or is denied to the terminal `DENIED`. Approval is gated by a cross-entity check: the student's `eligibility_status` must be `ELIGIBLE`, and if it is not the approval is refused with `ERR_STUDENT_NOT_ELIGIBLE`. From `APPROVED`, activation advances the plan to `ACTIVE`; from `ACTIVE`, suspension moves it to `SUSPENDED` and resumption moves it back to `ACTIVE`; from either `ACTIVE` or `SUSPENDED`, termination moves it to the terminal `TERMINATED`. Every transition is valid only from its named source state, raising `ERR_INVALID_STATE` otherwise.

**Activation** carries the fiscal weight. It is permitted only from `APPROVED` and enforces two ordered gates. First, a referential gate: a `CostShareAgreement` must already exist for the plan, else the activation is refused with `ERR_NO_COST_SHARE`. Second, a fiscal gate: the serving district's `committed_cost_cents` plus the agreement's `serving_share_cents` must not exceed the serving district's `transport_budget_cents`, else activation is refused with `ERR_BUDGET_EXCEEDED`. When both gates pass, activation commits budget by adding the agreement's `serving_share_cents` to the serving district's `committed_cost_cents`. **Termination**, conversely, cancels every `SCHEDULED` trip on the plan and releases the commitment by subtracting the agreement's `serving_share_cents` from the serving district's `committed_cost_cents`.

A plan's dual-variant cost picture is available as a computed read exposing `estimated_daily_cost_cents`, `estimated_monthly_cost_cents`, `actual_cost_cents`, and a `completed_trip_count`. The `actual_cost_cents` is the chronological sum of `trip_cost_cents` over the plan's trips that are `COMPLETED` and not voided; for a plan with zero completed trips it is zero even though the estimate is positive.

### 3.6. Cost-Share Agreements and Tiered Allocation

Two districts split the cost of a school-of-origin route, and a `CostShareAgreement` records that split. A `TransportCoordinator` or `StateCoordinator` creates one by naming the `transportation_plan_id` and supplying `expected_transportation_plan_version` for the optimistic-concurrency guard (§2.5); the agreement copies the plan's `origin_district_id` and `serving_district_id`, and a successful create increments the plan's `version` by one.

At creation the agreement snapshots the plan's `estimated_monthly_cost_cents` into `total_monthly_cents` and selects a tiered serving-share fraction, `serving_pct`, from the plan's one-way route mileage: a route of at most 10 miles takes a serving fraction of 0.50; a route of more than 10 but at most 25 miles takes 0.60; a route longer than 25 miles takes 0.75. The `serving_share_cents` is then the lesser of the `SHARE_CAP_CENTS` ceiling of 100,000 cents and the round-half-up of `total_monthly_cents` multiplied by `serving_pct` — with the rounding done first and the cap applied afterward (§2.6). The `origin_share_cents` is simply `total_monthly_cents` minus `serving_share_cents`. The agreement's own `actual_cost_cents` begins at zero and accumulates the serving portion of completed rides, tracking the sum of the trip-charge and reversal ledger amounts booked for this agreement.

### 3.7. Vehicles, Trips, and the Completion Ledger Cascade

A `Vehicle` is created by a `TransportCoordinator` or `StateCoordinator` with its owning `serving_district_id`, a `label` (its bus number), and a `capacity_students` seat count; it starts `IN_SERVICE`. Its status is changed by supplying a target `status`: `IN_SERVICE` and `OUT_OF_SERVICE` may toggle between each other, and from either of those a vehicle may be retired to the terminal `RETIRED`. Each move is valid only from its permitted source state, raising `ERR_INVALID_STATE` otherwise.

A `TripAssignment` represents one ride window. A `TransportCoordinator` or `StateCoordinator` creates it by naming the `transportation_plan_id` it fulfils, the `vehicle_id` to run it, and the `scheduled_start` and `scheduled_end` of the ride window, treated as the half-open interval from start up to but not including end. The trip copies its `serving_district_id` from the plan and opens in `SCHEDULED`. Trip creation enforces several gates in order: the plan must be `ACTIVE` (else `ERR_PLAN_NOT_ACTIVE`) and the vehicle must be `IN_SERVICE` (else `ERR_VEHICLE_NOT_IN_SERVICE`); `scheduled_end` must be strictly after `scheduled_start` (else `ERR_VALIDATION`). Two temporal capacity gates then apply. The new window must not overlap another non-terminal trip — one that is `SCHEDULED` or `COMPLETED` — on the **same vehicle** once each existing window is extended by the `VEHICLE_BUFFER_MINUTES` turnaround buffer of **30 minutes**; a conflict raises `ERR_VEHICLE_TIME_CONFLICT`. And the new window must not push the number of `SCHEDULED` trips whose half-open windows overlap it, counted across the **same serving district**, beyond the `DISTRICT_CONCURRENT_TRIP_CAP` of **3**; exceeding it raises `ERR_DISTRICT_CAPACITY`. For the district cap, two windows that merely touch — where one ends exactly when the next starts — do not overlap.

From `SCHEDULED`, a trip may be canceled to the terminal `CANCELED` with no financial effect, or completed. **Completion**, a `TransportCoordinator` or `StateCoordinator` action supplying the ride's `actual_miles`, moves the trip to `COMPLETED` and fires a depth-three ledger cascade. First, the trip's `trip_cost_cents` is computed as `actual_miles` multiplied by the 155-cent per-mile rate plus the 500-cent base. Second, the plan's `actual_cost_cents` increases by that `trip_cost_cents`, and the agreement's `actual_cost_cents` increases by the serving delta. Third, a `CostLedgerEntry` of `entry_type` `TRIP_CHARGE` is appended with `amount_cents` equal to the round-half-up of `trip_cost_cents` multiplied by the agreement's `serving_pct`, its `district_id` set to the serving district, and its `trip_assignment_id` referencing this trip. Finally, that entry increments the serving district's `transport_balance_cents` by its `amount_cents`.

**Voiding** a `COMPLETED` trip moves it to the terminal `VOIDED` and books the exact compensation. The plan's `actual_cost_cents` and the agreement's `actual_cost_cents` each decrease by the same serving delta the completion added; a `CostLedgerEntry` of `entry_type` `REVERSAL` is appended whose `amount_cents` is the negative of the round-half-up of `trip_cost_cents` times `serving_pct` (with `district_id` again the serving district); and the serving district's `transport_balance_cents` decreases by that magnitude, restoring it to its pre-completion value. Each ledger entry also records a human-readable `memo`. Because a voided trip is excluded from all actual-cost sums, the conserved-quantity invariant holds: a completion followed by a void leaves every balance exactly where it started.

### 3.8. Ledger Reads, Invoicing, Benefit Links, and Tutoring Referrals

Ledger entries are readable individually and as filtered lists, but they are never mutated after they are written; each entry carries its `cost_share_agreement_id`, `district_id`, `trip_assignment_id`, `entry_type`, signed `amount_cents`, and `memo`.

An agreement's **invoice** is a computed read reporting `serving_invoice_cents`, `origin_invoice_cents`, and `trip_count`. It considers only the `COMPLETED`, non-voided trips of the agreement's plan. For each such trip, the serving portion is the round-half-up of that trip's `trip_cost_cents` multiplied by the agreement's `serving_pct`; `serving_invoice_cents` is the sum of those per-trip rounded portions. The `origin_invoice_cents` is the sum, over the same trips, of each trip's `trip_cost_cents` minus that trip's rounded serving portion. The `trip_count` is the number of qualifying completed, non-voided trips. Crucially, each trip's serving portion is rounded to whole cents before summation — rounding per line, not once at the end (§2.6).

A `BenefitLink` is never created directly by a client; it is minted by the eligibility and dispute cascades described in §3.3 and §3.4, always with `source` `AUTO_ELIGIBILITY` and `status` `ACTIVE`, tying a `student_id` to the `district_id` of enrollment at link time. A `Liaison` or `StateCoordinator` may revoke an `ACTIVE` link, moving it to the terminal `REVOKED` and decrementing that district's `categorical_eligible_count` by one — the compensating counterpart to the increment at grant time. Revocation is valid only from `ACTIVE`, raising `ERR_INVALID_STATE` otherwise. Withdrawal of a student also revokes its active links through the same decrement (§3.2).

Finally, a `TutoringReferral` connects a student to academic support. A `Liaison` or `StateCoordinator` opens one for a `student_id` in a `subject` (`MATH`, `READING`, or `OTHER`); it starts `OPEN`. From `OPEN` it may be closed to the terminal `CLOSED` or canceled to the terminal `CANCELED`, each valid only from `OPEN` and otherwise raising `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Endpoints that create a new stand-alone resource return `201 Created`. Endpoints that modify an existing resource — including every state-transition action and the logical-clock control — return `200 OK`. Read endpoints return `200 OK`. The request and response bodies for each operation are described in the §3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | StateCoordinator |
| POST | `/mv/districts` | Create a district | StateCoordinator |
| GET | `/mv/districts/{districtId}` | Get a district | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/liaisons` | Create a liaison | StateCoordinator |
| GET | `/mv/liaisons/{liaisonId}` | Get a liaison | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/liaisons` | List liaisons | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/students` | Intake a student | Registrar, StateCoordinator |
| GET | `/mv/students/{studentId}` | Get a student | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/students` | List students | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/students/{studentId}/enroll` | Immediate enrollment | Registrar, StateCoordinator |
| POST | `/mv/students/{studentId}/withdraw` | Withdraw a student | Registrar, StateCoordinator |
| POST | `/mv/students/{studentId}/assign-liaison` | Assign a caseload liaison | Liaison, StateCoordinator |
| POST | `/mv/students/{studentId}/eligibility-determinations` | Create a draft eligibility determination | Liaison, StateCoordinator |
| GET | `/mv/eligibility-determinations/{determinationId}` | Get a determination | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/eligibility-determinations` | List determinations | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/eligibility-determinations/{determinationId}/finalize` | Finalize a determination | Liaison, StateCoordinator |
| POST | `/mv/transportation-plans` | Create a transportation plan | TransportCoordinator, StateCoordinator |
| GET | `/mv/transportation-plans/{planId}` | Get a plan | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/transportation-plans` | List plans | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/transportation-plans/{planId}/submit` | Submit a plan | TransportCoordinator, StateCoordinator |
| POST | `/mv/transportation-plans/{planId}/approve` | Approve a plan | TransportCoordinator, StateCoordinator |
| POST | `/mv/transportation-plans/{planId}/deny` | Deny a plan | TransportCoordinator, StateCoordinator |
| POST | `/mv/transportation-plans/{planId}/activate` | Activate a plan | TransportCoordinator, StateCoordinator |
| POST | `/mv/transportation-plans/{planId}/suspend` | Suspend a plan | TransportCoordinator, StateCoordinator |
| POST | `/mv/transportation-plans/{planId}/resume` | Resume a plan | TransportCoordinator, StateCoordinator |
| POST | `/mv/transportation-plans/{planId}/terminate` | Terminate a plan | TransportCoordinator, StateCoordinator |
| GET | `/mv/transportation-plans/{planId}/cost-summary` | Dual-variant cost read | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/cost-share-agreements` | Create a cost-share agreement | TransportCoordinator, StateCoordinator |
| GET | `/mv/cost-share-agreements/{agreementId}` | Get an agreement | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/cost-share-agreements` | List agreements | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/cost-share-agreements/{agreementId}/invoice` | Computed per-trip invoice | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/vehicles` | Create a vehicle | TransportCoordinator, StateCoordinator |
| GET | `/mv/vehicles/{vehicleId}` | Get a vehicle | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/vehicles` | List vehicles | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/vehicles/{vehicleId}/set-status` | Change vehicle status | TransportCoordinator, StateCoordinator |
| POST | `/mv/trip-assignments` | Create a trip | TransportCoordinator, StateCoordinator |
| GET | `/mv/trip-assignments/{tripId}` | Get a trip | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/trip-assignments` | List trips | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/trip-assignments/{tripId}/complete` | Complete a trip | TransportCoordinator, StateCoordinator |
| POST | `/mv/trip-assignments/{tripId}/cancel` | Cancel a scheduled trip | TransportCoordinator, StateCoordinator |
| POST | `/mv/trip-assignments/{tripId}/void` | Void a completed trip | TransportCoordinator, StateCoordinator |
| GET | `/mv/cost-ledger-entries/{ledgerEntryId}` | Get a ledger entry | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/cost-ledger-entries` | List ledger entries | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/benefit-links/{benefitLinkId}` | Get a benefit link | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/benefit-links` | List benefit links | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/benefit-links/{benefitLinkId}/revoke` | Revoke a benefit link | Liaison, StateCoordinator |
| POST | `/mv/disputes` | File a dispute | Liaison, StateCoordinator |
| GET | `/mv/disputes/{disputeId}` | Get a dispute | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/disputes` | List disputes | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/disputes/{disputeId}/begin-review` | Begin review | StateCoordinator |
| POST | `/mv/disputes/{disputeId}/request-info` | Request more info | StateCoordinator |
| POST | `/mv/disputes/{disputeId}/resubmit` | Resubmit info | Liaison, StateCoordinator |
| POST | `/mv/disputes/{disputeId}/resolve` | Resolve a dispute | StateCoordinator |
| POST | `/mv/tutoring-referrals` | Create a tutoring referral | Liaison, StateCoordinator |
| GET | `/mv/tutoring-referrals/{referralId}` | Get a referral | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| GET | `/mv/tutoring-referrals` | List referrals | StateCoordinator, TransportCoordinator, Liaison, Registrar |
| POST | `/mv/tutoring-referrals/{referralId}/close` | Close a referral | Liaison, StateCoordinator |
| POST | `/mv/tutoring-referrals/{referralId}/cancel` | Cancel a referral | Liaison, StateCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_DISTRICT_NOT_FOUND` | 404 |
| `ERR_LIAISON_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_DETERMINATION_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_TRIP_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_BENEFIT_LINK_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_LEDGER_ENTRY_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STUDENT_WITHDRAWN` | 409 |
| `ERR_STUDENT_NOT_ELIGIBLE` | 409 |
| `ERR_VEHICLE_NOT_IN_SERVICE` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_NO_COST_SHARE` | 409 |
| `ERR_LIAISON_CASELOAD_FULL` | 409 |
| `ERR_VEHICLE_TIME_CONFLICT` | 409 |
| `ERR_DISTRICT_CAPACITY` | 409 |
| `ERR_BUDGET_EXCEEDED` | 409 |
