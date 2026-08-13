# H-2A Labor Contractor API — Product Requirements Document

## 1. Introduction

Farm labor contractors operating under the H-2A temporary agricultural worker program carry a chain of regulated obligations that stretches from the first wage survey to the final payroll reconciliation: obtain a prevailing-wage determination, file a job order, recruit U.S. domestic workers under a statutory preference period, petition for visa beneficiaries, shepherd those workers through consular interviews, provide inspected housing and obligated transportation, and pay each worker the greater of piece-rate earnings or an hourly floor — all under a three-quarters-of-the-contract work guarantee. Every one of these steps is auditable, and every misstep exposes both the contractor and its grower clients to civil money penalties, suspension, or outright debarment from the program.

This document specifies an API that gives such a contractor a single system of record for that lifecycle. All endpoints are mounted under the `/h2a` prefix. The design separates duties deliberately: contractor staff run the operational pipeline, grower representatives consent to worker movements on their own operations, government reviewers certify orders and adjudicate petitions, independent inspectors certify housing, consular officers record interview outcomes, and Wage & Hour auditors run enforcement — while a test-harness administrator controls a deterministic logical clock so that every date-sensitive rule in the program can be exercised reproducibly.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly seven roles, spelled precisely as follows: `ContractorAdmin`, `GrowerRep`, `ProgramReviewer`, `HousingInspector`, `VisaOfficer`, `WageAuditor`, and `SystemAdmin`. Each endpoint admits a defined set of roles; a caller whose role is not admitted is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

`ContractorAdmin` is the farm labor contractor's operator staff and runs job orders, recruitment, petitions, consular scheduling, housing occupancy, work assignments, work logs, reconciliations, and transfer finalization. `GrowerRep` is the representative of one specific grower: it approves or rejects inbound worker transfers for that grower's orders, may itself request transfers away from its own orders, and may report abandonment on its own grower's orders. `ProgramReviewer` is the government-side reviewer (SWA/OFLC/USCIS): it publishes wage determinations, flags job-order deficiencies, certifies orders, and issues RFEs and adjudications on petitions. `HousingInspector` is an independent inspector who records housing inspections — a deliberate segregation of duties, since the contractor may never certify its own housing. `VisaOfficer` records consular interview outcomes. `WageAuditor` is the Wage & Hour Division auditor who opens enforcement cases, issues findings, assesses penalties, debars growers, and re-evaluates grower standing. `SystemAdmin` is the test-harness operator for the logical clock. All seven roles may call every read (GET) endpoint.

Identity semantics differ by role. When `X-User-Role` is `GrowerRep`, `X-User-ID` is the `id` of the acting `Grower`; ownership checks on any resource that references a grower compare the resource's foreign-key field (for example, a target job order's `grower_id`, or a transfer request's `requested_by_user_id`) to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` (HTTP 403). When `X-User-Role` is `ContractorAdmin`, `ProgramReviewer`, `HousingInspector`, `VisaOfficer`, `WageAuditor`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `requested_by_user_id` on a transfer request, which captures the caller's `X-User-ID` at creation) but never compares it to any entity's `id`.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and caps at 100. `offset` sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, each list endpoint accepts the optional equality-filter query parameters named with its resource in Section 3 — for example, `status` on growers, `grower_id` and `wage_determination_id` on job orders, `state_code`, `crop`, `activity`, and `effective_year` on wage determinations, `petition_id` on workers, `consulate_code` and `appointment_date` on consular appointments, `inspection_status` on housing units, `housing_unit_id`, `worker_id`, and `worker_assignment_id` on housing assignments, `job_order_id` on worker assignments and audit cases, and `from_assignment_id` and `to_job_order_id` on transfer requests. Every filter is optional; omitting a filter simply returns all rows.

### 2.4. The Server Logical Clock

All date-sensitive rules in this program — certification lead times, recruitment windows, transport thresholds, inspection validity, appointment due dates — evaluate against a server-maintained logical clock, never against wall-clock time. Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z, and the server must not fall back to wall-clock time under any circumstance. Throughout this document, the phrase "clock date" means the UTC calendar date of this logical clock.

A test-driving capability restricted to `SystemAdmin` sets the clock to a supplied `to_iso8601` instant and returns the new reading as `current_utc`. Advancing the clock mutates no entity; it simply changes the reference instant against which every temporal rule is subsequently evaluated.

### 2.5. Common Resource Properties and Mutation Semantics

Primary resources share a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp refreshed on any change to the resource's properties. `version` is a system-managed integer that increments with every modification, including modifications performed as side effects — when a penalty assessment suspends a grower, when a newly published wage determination flips its predecessor to `SUPERSEDED`, or when a withdrawal cascade touches dependent records, each mutated resource's `updated_at` refreshes and its `version` increments.

Two record types are immutable after creation: a housing inspection and a work log are append-only ledger entries. Both carry only `id` and `created_at`; `updated_at` and `version` are absent from them entirely, because neither resource can ever be modified once recorded.

### 2.6. Money, Dates, and the Workday Calendar

All monetary values are integer cents: wage rates are cents per hour, piece rates are cents per unit, transportation reimbursements and civil penalties are plain cents. Where a computation in this document produces a fractional cent, the result is rounded half up to a whole cent at exactly the step the rule specifies — never earlier, never later. Calendar dates are ISO 8601 calendar dates in YYYY-MM-DD form; timestamps are ISO 8601 UTC with three fractional digits.

The program's calendar arithmetic counts workdays on a Sunday-excluding calendar: the number of workdays between two dates is the count of dates from the first day through the last day, both endpoints included, whose weekday is not Sunday; when the end precedes the start, the count is zero. Hours are tracked in quarter-hour increments throughout — work logs record hours in multiples of one quarter hour, and the guarantee arithmetic in Section 3.7 operates on whole quarter-hours.

### 2.7. Nested Resource Retrieval

Requests that address nested resources are validated left-to-right through the path. The server confirms the existence of each path identifier in sequence and rejects the request immediately with a 404 carrying the error identifier of the first missing resource, before evaluating any later segment or any business rule. Each resource family has its own not-found identifier: `ERR_GROWER_NOT_FOUND`, `ERR_WAGE_DETERMINATION_NOT_FOUND`, `ERR_JOB_ORDER_NOT_FOUND`, `ERR_DOMESTIC_APPLICATION_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`, `ERR_VISA_PETITION_NOT_FOUND`, `ERR_CONSULAR_APPOINTMENT_NOT_FOUND`, `ERR_HOUSING_UNIT_NOT_FOUND`, `ERR_HOUSING_ASSIGNMENT_NOT_FOUND`, `ERR_WORKER_ASSIGNMENT_NOT_FOUND`, `ERR_TRANSFER_REQUEST_NOT_FOUND`, and `ERR_AUDIT_CASE_NOT_FOUND`. Identifiers referenced inside a request body are validated for existence the same way after the path itself resolves.

### 2.8. Optimistic Concurrency Control

Exactly one write operation in this API is version-guarded: updating a job order (`PATCH /h2a/job-orders/{jobOrderId}`) requires a non-optional `expected_job_order_version` field carrying the client's last observed `version` of that job order. If another writer has advanced the order's version since the client last read it — for instance, re-dating the contract period during a deficiency cure — the update is rejected with `ERR_STALE_JOB_ORDER_VERSION` (HTTP 412), so the client cannot overwrite an order it has not observed. No other endpoint accepts a version field.

### 2.9. Validation Priority Ordering

When a request would violate several rules at once, the server evaluates checks in a fixed priority order and reports the earliest failure. First, the presence of the two authentication headers is verified (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the caller's role is checked against the endpoint's admitted roles (`ERR_UNAUTHORIZED_ROLE`). Third, entity-backed ownership is enforced for the GrowerRep-scoped operations — transfer creation by a grower representative, transfer approval, rejection, and cancellation, and abandonment reporting (`ERR_FORBIDDEN_RESOURCE_OWNERSHIP`). Fourth, every referenced resource must exist, validated left-to-right (the not-found family of §2.7). Fifth, the target entity must be in a state that permits the operation — the `ERR_JOB_ORDER_INVALID_STATE`, `ERR_PETITION_INVALID_STATE`, `ERR_WORKER_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`, `ERR_APPOINTMENT_INVALID_STATE`, `ERR_TRANSFER_INVALID_STATE`, `ERR_AUDIT_CASE_INVALID_STATE`, `ERR_RECONCILIATION_INVALID_STATE`, `ERR_HOUSING_UNIT_INVALID_STATE`, and `ERR_HOUSING_ASSIGNMENT_INVALID_STATE` family, together with `ERR_GROWER_NOT_ACTIVE` and `ERR_WAGE_DETERMINATION_NOT_PUBLISHED`. Sixth, the safety rules of the program run: the domestic-worker preference guard (`ERR_DOMESTIC_PREFERENCE_VIOLATION`) and the housing-certification gate (`ERR_HOUSING_NOT_CERTIFIED`). Seventh, clock and date-window checks run (the temporal errors of Section 3, such as `ERR_CERTIFICATION_LEAD_TIME` and `ERR_ORDER_PERIOD_NOT_ENDED`). Eighth, cross-entity referential coherence is verified — grower matching, transfer-grower distinctness, worker-to-order and worker-to-petition linkage (`ERR_GROWER_MISMATCH`, `ERR_SAME_GROWER_TRANSFER`, `ERR_WORKER_ORDER_MISMATCH`, `ERR_WORKER_NOT_ON_PETITION`). Ninth, uniqueness, capacity, and guarded-transition constraints run (duplicates, ceilings, quotas, and the transition guards such as `ERR_UNDECIDED_APPLICATIONS_REMAIN`, `ERR_OPEN_ASSIGNMENTS_REMAIN`, `ERR_UNFINALIZED_RECONCILIATIONS_REMAIN`, and `ERR_OPEN_PETITIONS_EXIST`). Tenth and last come the field-domain and fiscal checks — malformed bodies, invalid enum values, non-positive amounts, invalid counts, invalid date ranges, invalid hours, invalid debarment terms, invalid findings, and the optimistic-concurrency version match — surfaced as `ERR_INVALID_REQUEST`, `ERR_INVALID_DATE_RANGE`, `ERR_INVALID_HOURS`, `ERR_INVALID_DEBARMENT_TERM`, `ERR_INVALID_FINDINGS`, or `ERR_STALE_JOB_ORDER_VERSION`. A request that fails both a structural or business rule and a field-domain rule always reports the business rule first.

## 3. Business Logic & Workflows

### 3.1. Grower Onboarding, Standing, and Wage Determinations

A `ContractorAdmin` registers each grower client by supplying the employer's `legal_name`, its `fein` (federal employer identification number), and the two-letter `state_code` of its primary state of operation. The `fein` is unique across growers; a registration repeating an existing one is rejected with `ERR_DUPLICATE_FEIN`. A newly registered grower starts in `ACTIVE` status, and its `debarment_ends_on` is null — that date exists only while the grower is `DEBARRED`.

Grower standing is a three-state affair — `ACTIVE`, `SUSPENDED`, `DEBARRED` — driven by enforcement rather than by direct edits. When an audit case is resolved with a penalty, the grower moves from `ACTIVE` to `SUSPENDED` and its `version` increments. When an audit case is resolved with debarment, the grower becomes `DEBARRED` and `debarment_ends_on` is set as described in §3.9. A `WageAuditor` may re-evaluate standing at any time through the grower's refresh capability: a `SUSPENDED` grower returns to `ACTIVE` once no audit case for that grower remains in `OPEN` or `FINDINGS_ISSUED`, and a `DEBARRED` grower returns to `ACTIVE` once the clock date has reached `debarment_ends_on` — reaching it exactly is sufficient — with `debarment_ends_on` cleared back to null. If neither rule applies, the refresh simply returns the grower unchanged with a 200 response.

Wage determinations are published by a `ProgramReviewer`. Each determination names the `state_code` whose survey it applies to, the `crop`, the `activity` (one of `HARVEST`, `PACKING`, `PLANTING`, `GENERAL`), and the `effective_year`, and it carries two mandatory rates — `aewr_hourly_cents`, the Adverse Effect Wage Rate, and `prevailing_hourly_cents`, the surveyed prevailing hourly wage, both of which must be positive — plus an optional `prevailing_piece_rate_cents_per_unit` with its `piece_unit_name`, both null when no piece rate was surveyed. A new determination is born `PUBLISHED`. Publishing a determination whose combination of state, crop, activity, and year matches an existing `PUBLISHED` row — with the crop compared case-insensitively — automatically flips the older row to `SUPERSEDED` and increments that row's `version`, so at most one determination per combination is ever `PUBLISHED`. Job orders that already submitted before the supersession keep their locked wage snapshots untouched; the pinning rules of §3.2 govern.

### 3.2. Drafting, Submitting, and Certifying the Job Order

The job order is the central artifact of the program. A `ContractorAdmin` drafts one for a grower by sending a payload containing the `grower_id` and the `wage_determination_id` it relies on, a `title`, the `crop` and `activity` (again one of `HARVEST`, `PACKING`, `PLANTING`, `GENERAL`), the two-letter `worksite_state`, the contract window as `work_start_date` and `work_end_date`, the `daily_standard_hours` per workday (an integer from 1 to 12, and the basis of the three-quarters guarantee), the total `workers_requested` across domestic and H-2A hires (at least 1), the employer-offered `offered_hourly_cents` (positive), an optional `offered_piece_rate_cents_per_unit` (null means no piece work is offered), and the per-worker transportation reimbursements `inbound_transport_cents` and `outbound_transport_cents` (each zero or greater). The order is created in `DRAFT` status with `deficiency_note` null and all three locked wage snapshots — `locked_aewr_hourly_cents`, `locked_prevailing_hourly_cents`, `locked_prevailing_piece_rate_cents_per_unit` — still null.

A draft order already exposes a full set of read-only derived terms, recomputed whenever the order is created, updated, or read. `total_calendar_days` counts the calendar days from the work start date through the work end date, both endpoints included. `total_workdays` counts the same window on the Sunday-excluding workday calendar of §2.6. `recruitment_cutoff_date` marks the midpoint of the contract: the system takes half of `total_calendar_days` (rounding down when the total is odd), subtracts one day, and advances `work_start_date` by that many days; `transport_threshold_date` is always the same date, the 50-percent point of the contract period. `required_hourly_floor_cents` is the greatest of four values: the determination's AEWR, the determination's prevailing hourly wage, the offered hourly wage, and the federal minimum wage of 725 cents per hour. `effective_piece_rate_cents_per_unit` is null when both the offered piece rate and the prevailing piece rate are null, and otherwise the greater of whichever of those two are non-null; ties resolve to the same value regardless of source. `domestic_hired_count` counts the order's domestic applications currently in `HIRED` status, and `visa_worker_ceiling` is `workers_requested` minus that count — the upper bound on beneficiaries a petition may request at filing time.

These derived terms read from different sources depending on where the order is in its lifecycle. While the order has never been submitted (still `DRAFT`, or in `DEFICIENCY` before its first submission), the wage-based terms read the live wage determination, so a superseding determination changes them. Once the order has been submitted at least once, the terms read the locked snapshots taken at submission, and superseding the determination afterwards leaves the order's terms unchanged.

While an order is in `DRAFT` or `DEFICIENCY`, a `ContractorAdmin` may update it; any other status makes the update inadmissible and is rejected with `ERR_JOB_ORDER_INVALID_STATE`. The update payload must carry `expected_job_order_version` per the optimistic-concurrency rule of §2.8, and may carry any of `work_start_date`, `work_end_date`, `daily_standard_hours`, `workers_requested`, `offered_hourly_cents`, `offered_piece_rate_cents_per_unit`, `inbound_transport_cents`, and `outbound_transport_cents`. A successful update increments the order's `version` by exactly one and recomputes the derived terms under the live-or-locked rule above. Note that `grower_id`, `wage_determination_id`, `title`, `crop`, `activity`, and `worksite_state` are fixed at creation and are not patchable.

Submitting the order moves it from `DRAFT` to `SUBMITTED`, and the same submission is also the cure leg of the deficiency cycle, moving a `DEFICIENCY` order back to `SUBMITTED`; from any other status the attempt is rejected with `ERR_JOB_ORDER_INVALID_STATE`. Three further preconditions guard submission, in the priority order of §2.9: the grower must be `ACTIVE` (else `ERR_GROWER_NOT_ACTIVE`), the referenced wage determination must still be `PUBLISHED` (else `ERR_WAGE_DETERMINATION_NOT_PUBLISHED` — a real risk after a supersession), and `work_end_date` must not fall before `work_start_date` (else `ERR_INVALID_DATE_RANGE`). On success the order snapshots `locked_aewr_hourly_cents`, `locked_prevailing_hourly_cents`, and `locked_prevailing_piece_rate_cents_per_unit` from the determination — re-taken fresh on every cure resubmission — and clears `deficiency_note` to null.

Review happens next. A `ProgramReviewer` who finds a problem flags a deficiency on a `SUBMITTED` order, which records the supplied `note` as the order's `deficiency_note` and moves it to `DEFICIENCY`; flagging from any other status is rejected with `ERR_JOB_ORDER_INVALID_STATE`. A `ProgramReviewer` may instead certify a `SUBMITTED` order, but only with adequate lead time: the clock date must be at least thirty days before `work_start_date` — a clock date exactly thirty days prior qualifies, one day later does not — otherwise the certification is rejected with `ERR_CERTIFICATION_LEAD_TIME`. Certification moves the order to `CERTIFIED`.

An order may be withdrawn from `DRAFT`, `SUBMITTED`, `DEFICIENCY`, `CERTIFIED`, `RECRUITING`, or `PETITIONING`; any other status is rejected with `ERR_JOB_ORDER_INVALID_STATE`. Withdrawal is blocked whenever the order has a petition in `FILED`, `RFE`, or `APPROVED` — rejected with `ERR_OPEN_PETITIONS_EXIST` — and this guard is precisely what blocks withdrawal once petitioning is genuinely underway. A successful withdrawal moves the order to `WITHDRAWN` and cascades: every petition of the order still in `DRAFT` moves to `WITHDRAWN`, each worker linked to such a petition in `PETITIONED` status reverts to `REGISTERED` with its `petition_id` cleared to null, and every domestic application still in `APPLIED` moves to `WITHDRAWN`. `CLOSED` and `WITHDRAWN` are the order's terminal states.

### 3.3. Domestic Recruitment and the Preference Period

Once certified, a `ContractorAdmin` opens the domestic recruitment period, moving the order from `CERTIFIED` to `RECRUITING`; from any other status the attempt is rejected with `ERR_JOB_ORDER_INVALID_STATE`.

While the order is `RECRUITING`, domestic (U.S. worker) applications are recorded against it, each carrying the `applicant_name` and `contact_phone` of the applicant; the server stamps each new application with `applied_on` set to the clock date at creation, stores the order reference from the path as its `job_order_id`, and starts it in `APPLIED` status with `qualification` and `decided_on` both null. Recording an application against an order that is not `RECRUITING` is rejected with `ERR_JOB_ORDER_INVALID_STATE`.

Deciding an application is a `ContractorAdmin` action that supplies a `decision` — `HIRE` or `REJECT` — and a `qualification` of `QUALIFIED` or `UNQUALIFIED`. The application must still be `APPLIED`; deciding an already decided or withdrawn application is rejected with `ERR_APPLICATION_INVALID_STATE`. A successful decision stamps `decided_on` with the clock date and records the supplied `qualification`.

The two decisions behave differently. Hiring moves the application to `HIRED`, but only while the order's `domestic_hired_count` is still below its `workers_requested`; hiring when the count has already reached that ceiling is rejected with `ERR_WORKER_CEILING_EXCEEDED`. Each hire immediately recomputes the parent's `domestic_hired_count` and therefore shrinks `visa_worker_ceiling`. Rejection moves the application to `REJECTED`, but the domestic-worker preference rule guards it: an applicant whose `applied_on` falls on or before the order's `recruitment_cutoff_date` is inside the preference window, and rejecting such an applicant whom the contractor has just marked `QUALIFIED` is forbidden — the decision is rejected with `ERR_DOMESTIC_PREFERENCE_VIOLATION` (HTTP 422). The boundary is inclusive: an application filed exactly on the cutoff date is still inside the window, while one filed the day after the cutoff is outside it.

Closing recruitment moves the order from `RECRUITING` to `PETITIONING`. Every application must be decided first — if any application for the order is still `APPLIED`, the close is rejected with `ERR_UNDECIDED_APPLICATIONS_REMAIN`. Once recruitment closes, the number of `HIRED` domestic workers is fixed, and with it the `visa_worker_ceiling` that constrains petition filing.

### 3.4. Workers, Visa Petitions, and Consular Processing

Foreign workers are registered by a `ContractorAdmin` with `full_name`, `passport_number`, `date_of_birth`, and `country_code`. Passport numbers are unique across workers; a duplicate is rejected with `ERR_DUPLICATE_PASSPORT`. A worker begins in `REGISTERED` status with `petition_id` null.

A visa petition is created against a job order — the order named in the path is stored on the petition as its `job_order_id` — and the order must be in `CERTIFIED`, `RECRUITING`, or `PETITIONING` (else `ERR_JOB_ORDER_INVALID_STATE`) with its grower `ACTIVE` (else `ERR_GROWER_NOT_ACTIVE`). The creation payload carries the petition's `receipt_code`, unique across all petitions (a repeat is rejected with `ERR_DUPLICATE_RECEIPT_CODE`), and `requested_worker_count`, the number of beneficiaries requested, which must be at least 1. A new petition starts in `DRAFT` with `rfe_count` at 0 and both `filed_on` and `approved_worker_count` null.

Filing the petition moves it from `DRAFT` to `FILED` and stamps `filed_on` with the clock date. Filing requires the parent order to have reached `PETITIONING` (else `ERR_JOB_ORDER_INVALID_STATE`) and requires `requested_worker_count` to fit within the order's `visa_worker_ceiling` — the count fixed by domestic hiring when recruitment closed — else the filing is rejected with `ERR_PETITION_EXCEEDS_VISA_CEILING`.

A `ContractorAdmin` links registered workers to a petition while the petition is in `DRAFT` or `FILED`; linking from any other petition status is rejected with `ERR_PETITION_INVALID_STATE`, and the worker must be `REGISTERED` (else `ERR_WORKER_INVALID_STATE`). Linking moves the worker to `PETITIONED` and sets the worker's `petition_id` to the petition. The number of linked workers may never exceed the petition's `requested_worker_count`; a link that would overflow it is rejected with `ERR_PETITION_WORKER_OVERFLOW`.

Adjudication is iterative. A `ProgramReviewer` may issue a Request for Evidence on a `FILED` petition, moving it to `RFE` and incrementing `rfe_count` by one; at most two RFEs may ever be issued against a petition, so issuing a third is rejected with `ERR_RFE_LIMIT_REACHED`, and after two RFEs the petition must be adjudicated. A `ContractorAdmin` responds to an RFE, moving the petition from `RFE` back to `FILED` with `rfe_count` unchanged; both the RFE and its response accept an optional `note`. Responding from any status other than `RFE` is rejected with `ERR_PETITION_INVALID_STATE`.

Final adjudication by a `ProgramReviewer` takes a `decision` of `APPROVE` or `DENY` and is admissible from either `FILED` or `RFE` (else `ERR_PETITION_INVALID_STATE`). Approval additionally requires an `approved_worker_count` input that must equal the number of workers currently linked to the petition — a mismatch is rejected with `ERR_APPROVED_COUNT_MISMATCH` — and must be at least 1 and no more than `requested_worker_count` (else `ERR_INVALID_REQUEST`). Approval moves the petition to `APPROVED` and records `approved_worker_count`. Denial moves the petition to `DENIED` and releases its people: every linked worker in `PETITIONED` status reverts to `REGISTERED` with `petition_id` cleared. `APPROVED`, `DENIED`, and `WITHDRAWN` are the petition's terminal states; the `WITHDRAWN` state is reached only through the job-order withdrawal and grower debarment cascades, never directly.

With an approved petition in hand, a `ContractorAdmin` schedules consular interviews. Each appointment payload names a `worker_id`, a `petition_id`, a `consulate_code` identifying the consulate, and an `appointment_date`. The petition must be `APPROVED`; the worker must be linked to that very petition (else `ERR_WORKER_NOT_ON_PETITION`) and in `PETITIONED` status (else `ERR_WORKER_INVALID_STATE`). The `appointment_date` must be strictly after the clock date at creation — same-day or past dates are rejected with `ERR_APPOINTMENT_DATE_NOT_FUTURE`. Each consulate processes at most six scheduled interviews per day: the server counts `SCHEDULED` appointments with the same `consulate_code` on the same `appointment_date` and accepts the booking only while that count is below six, so the sixth appointment of the day succeeds and the seventh is rejected with `ERR_CONSULATE_CAPACITY_FULL`; `CANCELLED` and `COMPLETED` appointments consume no slots. A worker may hold only one scheduled interview at a time — scheduling a second while one is still `SCHEDULED` is rejected with `ERR_WORKER_HAS_ACTIVE_APPOINTMENT`. A new appointment is `SCHEDULED` with `outcome` and `completed_on` null.

Recording the interview outcome is the exclusive duty of a `VisaOfficer`, and only for a `SCHEDULED` appointment (else `ERR_APPOINTMENT_INVALID_STATE`) whose `appointment_date` the clock date has reached (else `ERR_APPOINTMENT_NOT_YET_DUE`). The recorded `outcome` drives the worker: `ISSUED` moves the worker from `PETITIONED` to `VISA_ISSUED`; `REFUSED` sends the worker back to `REGISTERED` with `petition_id` cleared to null; `NO_SHOW` leaves the worker unchanged. The appointment itself moves to `COMPLETED` with `completed_on` set to the clock date. A `ContractorAdmin` may instead cancel a `SCHEDULED` appointment, moving it to `CANCELLED` and freeing its daily consular slot.

Activation is the order's gateway into field operations. Once at least one petition for the order is `APPROVED` (else `ERR_NO_APPROVED_PETITION`) and the clock date has reached `work_start_date` (else `ERR_ORDER_NOT_YET_STARTED`), a `ContractorAdmin` activates the order, moving it from `PETITIONING` to `ACTIVE`.

### 3.5. Housing: Inspection, Certification, and Occupancy

Employer-provided housing is registered per grower with the owning `grower_id`, a `name` serving as the unit's address label, and a `capacity` — the maximum number of simultaneous occupants, at least 1. A new unit's `inspection_status` is `UNINSPECTED` and its `certified_on` is null. Two read-only values complete the picture: `certification_valid_until`, which is `certified_on` advanced by 365 days and exists only while the unit is `CERTIFIED`, and `occupied_count`, the number of housing assignments of the unit currently in `OCCUPIED` status.

Inspections are recorded exclusively by a `HousingInspector` — the contractor cannot certify its own housing — and each inspection is an immutable record carrying the unit reference from the path as its `housing_unit_id`, the `inspected_on` date, the `result` (`PASS` or `FAIL`), and an optional list of `deficiency_codes`, which is ignored when the result is `PASS`. An `inspected_on` later than the clock date is rejected with `ERR_INSPECTION_DATE_IN_FUTURE` (HTTP 400). The result flips the unit's `inspection_status`: a `PASS` recorded against an `UNINSPECTED`, `FAILED`, or `EXPIRED` unit moves it to `CERTIFIED` and sets `certified_on` to the inspection's `inspected_on` — the latter two being the recertification legs of the cycle — while a `FAIL` moves an `UNINSPECTED` or `CERTIFIED` unit to `FAILED`, clearing `certified_on` to null when the unit had been certified.

Certifications age out. A `ContractorAdmin` may expire a unit, but only while its `inspection_status` is `CERTIFIED` (else `ERR_HOUSING_UNIT_INVALID_STATE`) and only once the clock date is strictly later than `certification_valid_until` — while the clock date is still on or before that date, the attempt is rejected with `ERR_HOUSING_CERTIFICATION_STILL_VALID`. A successful expiry moves the unit to `EXPIRED`, from which a fresh passing inspection recertifies it.

Moving a worker into housing is a `ContractorAdmin` action whose payload carries the `housing_unit_id`, the `worker_id`, the `worker_assignment_id` the stay is tied to, and the `move_in_date`. Two safety rules gate the move. First, the unit must be `CERTIFIED` at move-in and the clock date must not be past its `certification_valid_until`; otherwise the move is rejected with `ERR_HOUSING_NOT_CERTIFIED`. Second, the referenced worker assignment must be `ACTIVE` and the job order it belongs to must belong to the same grower that owns the unit; a cross-grower placement is rejected with `ERR_GROWER_MISMATCH`.

Occupancy is modeled with half-open windows: a stay runs from its `move_in_date` up to but not including its `move_out_date`, and while the assignment remains `OCCUPIED` the window is open-ended. Two windows overlap when each begins before the other ends; pure adjacency — one worker's move-in landing exactly on another's move-out — does not count as an overlap. Capacity enforcement is aggregate, not pairwise: the move-in is rejected with `ERR_HOUSING_CAPACITY_EXCEEDED` when the number of the unit's `OCCUPIED` assignments overlapping the new window, plus the new arrival, would exceed the unit's `capacity`. Independently, a worker may occupy only one bed: if the same worker already holds any other `OCCUPIED` housing assignment, in any unit, whose window overlaps the new one, the move-in is rejected with `ERR_WORKER_HOUSING_OVERLAP`. `VACATED` rows never overlap anything. A successful move-in creates the assignment in `OCCUPIED` status with `move_out_date` null and refreshes the unit's `occupied_count`.

Vacating is the mirror action: a `ContractorAdmin` ends an `OCCUPIED` stay — anything else is rejected with `ERR_HOUSING_ASSIGNMENT_INVALID_STATE` — by supplying a `move_out_date`, which must not fall before the `move_in_date` (else `ERR_INVALID_DATE_RANGE`). The stay moves to `VACATED` and the unit's `occupied_count` is recomputed. Vacating also happens automatically: whenever a worker assignment reaches `COMPLETED`, `TERMINATED`, or `TRANSFERRED_OUT`, every `OCCUPIED` housing assignment tied to it is vacated with `move_out_date` set to the assignment's `ended_on`.

### 3.6. Work Assignments and Daily Work Logs

Placing a worker onto an order creates a worker assignment from a payload carrying `worker_id` and `job_order_id`. The order must be `ACTIVE` (else `ERR_JOB_ORDER_INVALID_STATE`) and its grower must be `ACTIVE` (else `ERR_GROWER_NOT_ACTIVE`). The worker must be `VISA_ISSUED` (else `ERR_WORKER_INVALID_STATE`) and must have been petitioned to this very job order — the job order of the worker's petition must equal the order being assigned, otherwise `ERR_WORKER_ORDER_MISMATCH`; transfer-created assignments are the lone exemption from this petition-matching rule. One worker holds at most one live assignment: a worker who already has a `PLANNED` or `ACTIVE` assignment anywhere is rejected with `ERR_WORKER_ALREADY_ASSIGNED`. Finally, headcount is capped: the order's `domestic_hired_count` plus its count of `PLANNED` and `ACTIVE` assignments must remain within `workers_requested`, and a placement that would exceed it is rejected with `ERR_WORKER_CEILING_EXCEEDED`. A new assignment starts in `PLANNED` status with `started_on`, `ended_on`, and `end_reason` all null; its read-only `guarantee_eligible` flag reads true for as long as the assignment is non-terminal.

Starting work is allowed only from `PLANNED` (else `ERR_ASSIGNMENT_INVALID_STATE`) and only while the clock date has not passed the order's `work_end_date` (else `ERR_ORDER_PERIOD_ENDED`). Starting stamps `started_on` with the clock date, moves the assignment to `ACTIVE`, moves the worker from `VISA_ISSUED` to `WORKING`, and creates the assignment's one-to-one wage reconciliation in `OPEN` status with the provisional variant of §3.7 already computed.

Work logs are the payroll ledger's raw entries: one immutable row per assignment per day, recorded by a `ContractorAdmin` with the `worker_assignment_id`, the `work_date`, the `hours_worked`, and the `units_picked`. The assignment must be `ACTIVE`. The `work_date` must lie inside the window from the assignment's `started_on` through the earlier of the clock date and the order's `work_end_date`, both bounds included; anything outside is rejected with `ERR_WORK_LOG_DATE_OUT_OF_RANGE`, and a second row for the same assignment and date is rejected with `ERR_DUPLICATE_WORK_LOG`. `hours_worked` must be a multiple of one quarter hour, strictly greater than zero, and at most sixteen hours (else `ERR_INVALID_HOURS`). `units_picked` must be zero or greater, and it must be exactly 0 whenever the order's `effective_piece_rate_cents_per_unit` is null — piece counts are meaningless without a piece rate (violations surface as `ERR_INVALID_REQUEST`). Every work-log creation recomputes the assignment's `OPEN` reconciliation on the provisional variant.

Ending an assignment takes an `end_reason` and behaves per branch. From `ACTIVE`, the reason may be `COMPLETED` or `FOR_CAUSE` — any other reason, or an assignment not in `ACTIVE`, is rejected (`ERR_INVALID_REQUEST` or `ERR_ASSIGNMENT_INVALID_STATE` respectively) — and the clock date must be on or after `started_on`. A completion moves the assignment to `COMPLETED`; a for-cause termination moves it to `TERMINATED`. Both stamp `ended_on` with the clock date and record `end_reason`; `guarantee_eligible` becomes true for `COMPLETED` and false for `FOR_CAUSE`. Both cascade identically: every `OCCUPIED` housing stay of the assignment is vacated with `move_out_date` set to `ended_on`, the wage reconciliation is recomputed (it stays `OPEN`, its basis window now anchored at `ended_on`), and the worker moves to `DEPARTED` — but only when the worker holds no other `PLANNED` or `ACTIVE` assignment.

A `PLANNED` assignment that never started may still need clearing: ending it accepts only `FOR_CAUSE` (any other reason is rejected with `ERR_INVALID_REQUEST`), moves it to `TERMINATED` with `ended_on` set to the clock date and `guarantee_eligible` false, and leaves the worker untouched — still `VISA_ISSUED`, never having started. This escape hatch exists so a never-started assignment cannot block contract close-out.

Abandonment is reported by a `ContractorAdmin`, or by the `GrowerRep` of the grower that owns the assignment's order — a grower representative's `X-User-ID` must equal that order's `grower_id`, else `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`. The assignment must be `ACTIVE` (else `ERR_ASSIGNMENT_INVALID_STATE`), and the report accepts an optional `note`. Reporting abandonment moves the assignment to `TERMINATED` with `end_reason` `ABANDONED` and `guarantee_eligible` false, moves the worker from `WORKING` to `ABANDONED`, vacates housing exactly as a normal ending does, recomputes the reconciliation, and — critically — causes the system to open an audit case automatically: the case names the order's grower, is scoped to the order, carries `trigger_source` `ABANDONMENT`, and opens in `OPEN` status.

### 3.7. Wage Reconciliation, the Three-Quarters Guarantee, and Close-Out

Every started assignment owns exactly one wage reconciliation, created automatically at start; reading an assignment's reconciliation yields an array containing zero rows (before start) or one. The row's `status` is `OPEN` while it keeps recomputing and becomes `FINALIZED` when frozen, with `finalized_on` recording the clock date of that freeze and null before it. All of its monetary and arithmetic fields — `computed_through_date`, `total_units`, `piece_earnings_cents`, `hourly_floor_earnings_cents`, `makeup_pay_cents`, `guarantee_basis_workdays`, `guaranteed_quarters`, `worked_quarters`, `shortfall_quarters`, `guarantee_pay_cents`, `guarantee_applied`, `inbound_transport_owed_cents`, `outbound_transport_owed_cents`, and `total_due_cents` — are read-only and server-computed; `worker_assignment_id` ties the row to its assignment.

Earnings are computed per workweek. Workweeks are consecutive seven-day blocks anchored at the job order's `work_start_date`: the first workweek runs from the start date through the sixth day after it, the second covers the next seven dates, and so on, with the final partial block clipped to the contract end. For every workweek intersecting the assignment's accrual window — from `started_on` through `computed_through_date` — the weekly piece earnings are the sum of `units_picked` over the week's work logs multiplied by the order's `effective_piece_rate_cents_per_unit`, or zero when that rate is null. The weekly floor earnings are built day by day: each day's `hours_worked` (zero for days with no log) is multiplied by the order's `required_hourly_floor_cents`, and that per-day product is rounded half-up to a whole cent before the week's days are summed. The rounding order is pinned — round each day first, then sum within the week; summing hours first and rounding once produces different cents and is non-conformant. The week's make-up pay is the amount by which the weekly floor exceeds the weekly piece earnings, or zero when piece earnings meet or beat the floor. Across all intersecting weeks, the piece earnings sum to `piece_earnings_cents`, the floor earnings sum to `hourly_floor_earnings_cents`, and the make-up pay sums to `makeup_pay_cents`; `total_units` is simply the sum of `units_picked` over all of the assignment's logs.

The reconciliation's accrual horizon, `computed_through_date`, is the assignment's `ended_on` once the assignment is terminal — ended assignments stop accruing — and otherwise the earlier of the clock date and the order's `work_end_date`.

The three-quarters guarantee sits on top of the weekly math. Its basis window runs from the later of the order's `work_start_date` and the assignment's `started_on` through the earlier of the order's `work_end_date` and the reconciliation's `computed_through_date`, and `guarantee_basis_workdays` counts that window on the Sunday-excluding calendar (zero when the window is empty or inverted). The guaranteed quarter-hours, `guaranteed_quarters`, are the basis workdays multiplied by the order's `daily_standard_hours`, converted to quarter-hours, then scaled by three-quarters with the result rounded down to a whole quarter-hour — an odd quarter count truncates downward. `worked_quarters` sums, over the assignment's work logs dated inside the basis window, each day's hours converted to quarter-hours. The shortfall, `shortfall_quarters`, is the guaranteed quarter-hours minus the worked quarter-hours, floored at zero: when the worker has worked more than guaranteed, the shortfall is zero and there is never a negative clawback. `guarantee_pay_cents` prices the shortfall at the hourly floor — the shortfall quarter-hours multiplied by `required_hourly_floor_cents` and divided by four, rounded half-up to a whole cent — and is payable only when the guarantee applies; otherwise it is zero.

Whether the guarantee applies is carried by `guarantee_applied`: it is false only for a `FINALIZED` reconciliation whose assignment ended with `end_reason` `FOR_CAUSE` or `ABANDONED`, and true in every other case — while the row is `OPEN`, the provisional computation simply assumes eligibility.

Transportation reimbursements follow the contract's 50-percent point. `inbound_transport_owed_cents` equals the order's `inbound_transport_cents` once `computed_through_date` has reached the order's `transport_threshold_date` — reaching it exactly counts — provided the reconciliation is still `OPEN` or, if finalized, the assignment's `end_reason` is anything other than `ABANDONED`; in every other case it is zero. `outbound_transport_owed_cents` equals the order's `outbound_transport_cents` only for a `FINALIZED` reconciliation whose assignment ended `COMPLETED`, and is zero otherwise. The row's `total_due_cents` is the sum of piece earnings, make-up pay, guarantee pay, and the two transport amounts.

These rules produce two variants of the same row. While the reconciliation is `OPEN` — the provisional variant — it recomputes on every work-log creation and on assignment start, end, and transfer-finalization; it accrues through `computed_through_date`, assumes the guarantee applies, owes no outbound transport, and applies the inbound threshold rule to the current horizon. Finalizing — allowed only when the parent assignment has reached `COMPLETED`, `TERMINATED`, or `TRANSFERRED_OUT` and the row is still `OPEN`, with any other combination rejected as `ERR_RECONCILIATION_INVALID_STATE` — freezes the final variant: the horizon is pinned to `ended_on`, `guarantee_applied` is decided from the recorded `end_reason`, outbound transport is owed per the completion rule, the row moves to `FINALIZED`, and `finalized_on` is stamped with the clock date.

Close-out then rolls the order up. A `ContractorAdmin` closes the work period once the order is `ACTIVE` (else `ERR_JOB_ORDER_INVALID_STATE`), the clock date has reached `work_end_date` (else `ERR_ORDER_PERIOD_NOT_ENDED`), and every worker assignment of the order has reached `COMPLETED`, `TERMINATED`, or `TRANSFERRED_OUT` (else `ERR_OPEN_ASSIGNMENTS_REMAIN`); the order moves to `CLOSING`. Finalizing the order requires `CLOSING` (else `ERR_JOB_ORDER_INVALID_STATE`) and requires the wage reconciliation of every assignment of the order to be `FINALIZED` (else `ERR_UNFINALIZED_RECONCILIATIONS_REMAIN`); the order then reaches its terminal `CLOSED` state.

### 3.8. Inter-Grower Worker Transfers

A transfer moves a working H-2A worker from one grower's order to another grower's order without breaking the worker's employment. A `ContractorAdmin` or a `GrowerRep` files the request with the `worker_id`, the `from_assignment_id` of the source assignment, the `to_job_order_id` of the target order, and a `reason` of `CONTRACT_IMPOSSIBILITY`, `GROWER_REQUEST`, or `WORKER_REQUEST`. The source assignment must be `ACTIVE` (else `ERR_ASSIGNMENT_INVALID_STATE`); the target order must be `ACTIVE` (else `ERR_JOB_ORDER_INVALID_STATE`) and must belong to a different grower than the source — a same-grower transfer is rejected with `ERR_SAME_GROWER_TRANSFER`. A worker with another transfer still in `PENDING` or `GROWER_APPROVED` cannot be re-filed: that attempt is rejected with `ERR_DUPLICATE_ACTIVE_TRANSFER`. When a `GrowerRep` files, its `X-User-ID` must equal the source order's `grower_id` (else `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`). The request is created in `PENDING` status, and the server records the caller's `X-User-ID` as `requested_by_user_id` for the audit trail.

Consent comes from the receiving side. The target grower's representative approves the inbound transfer — moving it from `PENDING` to `GROWER_APPROVED` — or rejects it with an optional `note`, moving it to `REJECTED`. Both actions require the request to be `PENDING` (else `ERR_TRANSFER_INVALID_STATE`) and both are ownership-checked: the representative's `X-User-ID` must equal the target order's `grower_id`, else `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`.

Execution is a `ContractorAdmin` action on a `GROWER_APPROVED` request (else `ERR_TRANSFER_INVALID_STATE`), and it re-verifies the world at execution time: the source assignment must still be `ACTIVE` (else `ERR_ASSIGNMENT_INVALID_STATE`) and the target order must still be `ACTIVE` (else `ERR_JOB_ORDER_INVALID_STATE`). Finalizing is atomic. The transfer's effective date is the clock date. The source assignment moves from `ACTIVE` to `TRANSFERRED_OUT` with `end_reason` `TRANSFERRED_OUT`, its `ended_on` set to the day before the effective date, and `guarantee_eligible` true; its housing stays are vacated with `move_out_date` set to that `ended_on`; and its wage reconciliation is recomputed on the truncated basis window while remaining `OPEN`. Simultaneously, a brand-new worker assignment is created on the target order — already `ACTIVE` with `started_on` set to the effective date, exempt from the petition-matching rule of §3.6 — together with a fresh `OPEN` wage reconciliation computed on the provisional variant. The worker remains `WORKING` throughout, and the request itself lands in its terminal `APPROVED` state.

Either side may still walk away before execution: cancellation by a `ContractorAdmin` or `GrowerRep` works from `PENDING` or `GROWER_APPROVED` (else `ERR_TRANSFER_INVALID_STATE`) and moves the request to `CANCELLED`. A grower representative may cancel only a request it originally filed — its `X-User-ID` must equal the request's `requested_by_user_id`, else `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`. `APPROVED`, `REJECTED`, and `CANCELLED` are terminal.

### 3.9. Audit Cases, Penalties, and Debarment

Enforcement begins with an audit case. A `WageAuditor` opens one manually by naming the audited `grower_id`, an optional `job_order_id` scoping the case — which, when present, must belong to that grower (else `ERR_GROWER_MISMATCH`) — a `trigger_source` of `MANUAL`, `ABANDONMENT`, `HOUSING`, or `WAGE_DISCREPANCY`, and an optional free-text `note`. The system also opens cases itself: abandonment reports generate them with `trigger_source` `ABANDONMENT`, as §3.6 describes. A new case opens in `OPEN` status with `opened_on` stamped from the clock date, `findings` empty, and `provisional_exposure_cents`, `final_penalty_cents`, `debarment_years`, and `closed_on` all null.

Issuing findings moves a case from `OPEN` to `FINDINGS_ISSUED` (from any other status, `ERR_AUDIT_CASE_INVALID_STATE`). The `findings` payload is a non-empty list in which every entry carries a `violation_code`, a `count` of at least 1, and a `willful` flag; the recognized violation codes are `WAGE_UNDERPAYMENT`, `HOUSING_SUBSTANDARD`, `TRANSPORT_VIOLATION`, `RECRUITMENT_VIOLATION`, and `RECORDKEEPING`, and an empty list, an unknown code, or a count below 1 is rejected with `ERR_INVALID_FINDINGS`. Once findings are stored, the case's `provisional_exposure_cents` is computed as the sum over findings of each violation's base amount multiplied by its count: $1,500.00 (150,000 cents) per count of wage underpayment, $1,200.00 (120,000 cents) per count of substandard housing, $900.00 (90,000 cents) per count of transportation violation, $1,100.00 (110,000 cents) per count of recruitment violation, and $600.00 (60,000 cents) per count of recordkeeping. The provisional figure deliberately ignores the willful multiplier, the per-kind cap, and any discount.

From `FINDINGS_ISSUED`, the case has three exits. Closing with no action moves it to `CLOSED_NO_ACTION` and stamps `closed_on` with the clock date. Assessing a penalty takes a `good_faith` input and computes `final_penalty_cents` in a pinned evaluation order: for each violation kind present, the base amount is multiplied by the count and doubled when the finding is willful, and that per-kind total is then capped at $10,000.00 (1,000,000 cents) before any summation; the capped kind totals are summed; and only then, when `good_faith` is true, the sum is reduced by ten percent with the result rounded half-up to a whole cent, while a non-good-faith assessment keeps the sum unchanged. Any other evaluation order — discounting before capping, or capping after summation — yields different cents and is non-conformant. Assessment moves the case to `RESOLVED_PENALTY`, stamps `closed_on`, and suspends the grower: an `ACTIVE` grower moves to `SUSPENDED` with its `version` incremented, while a grower already `DEBARRED` remains `DEBARRED`.

Debarment is the heaviest exit. Debarring a `FINDINGS_ISSUED` case requires a `debarment_years` term of one, two, or three years — anything outside that range is rejected with `ERR_INVALID_DEBARMENT_TERM` — and moves the case to `RESOLVED_DEBARMENT` with the term recorded and `closed_on` stamped. The grower then becomes `DEBARRED`, whether it stood at `ACTIVE` or `SUSPENDED`, with `debarment_ends_on` set to the clock date plus the debarment term at 365 days per year. Debarment cascades through the grower's book of business: every job order of the grower in `DRAFT`, `SUBMITTED`, `DEFICIENCY`, `CERTIFIED`, or `RECRUITING` moves to `WITHDRAWN`, and each such withdrawal cascades exactly as a manual withdrawal does — the order's petitions in `DRAFT` move to `WITHDRAWN`, workers linked to those petitions in `PETITIONED` status revert to `REGISTERED` with `petition_id` cleared to null, and the order's domestic applications still in `APPLIED` move to `WITHDRAWN`.

Reinstatement runs through the grower refresh of §3.1: a `SUSPENDED` grower returns to `ACTIVE` once no case of its remains `OPEN` or `FINDINGS_ISSUED`, and a `DEBARRED` grower returns to `ACTIVE` once the clock date has reached `debarment_ends_on`, the boundary date itself included, with `debarment_ends_on` cleared. The case statuses `CLOSED_NO_ACTION`, `RESOLVED_PENALTY`, and `RESOLVED_DEBARMENT` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or re-evaluate standing return `200 OK`, as do all reads. The clock-setting capability also returns `200 OK`. Request payloads, response contents, and side effects for each endpoint are specified by the workflows of Section 3; this table is the addressable contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/h2a/_clock/set_current_utc` | Set the server logical clock | SystemAdmin |
| POST | `/h2a/growers` | Register a grower client | ContractorAdmin |
| GET | `/h2a/growers` | List growers | Any authenticated role |
| POST | `/h2a/growers/{growerId}/refresh-status` | Re-evaluate SUSPENDED/DEBARRED grower standing | WageAuditor |
| POST | `/h2a/wage-determinations` | Publish a wage determination, superseding any matching PUBLISHED row | ProgramReviewer |
| GET | `/h2a/wage-determinations` | List wage determinations | Any authenticated role |
| POST | `/h2a/job-orders` | Create a job order in DRAFT | ContractorAdmin |
| GET | `/h2a/job-orders` | List job orders | Any authenticated role |
| GET | `/h2a/job-orders/{jobOrderId}` | Get a job order | Any authenticated role |
| PATCH | `/h2a/job-orders/{jobOrderId}` | Update a DRAFT or DEFICIENCY job order (OCC-guarded) | ContractorAdmin |
| POST | `/h2a/job-orders/{jobOrderId}/submit` | Submit or cure-resubmit the order, locking wage snapshots | ContractorAdmin |
| POST | `/h2a/job-orders/{jobOrderId}/flag-deficiency` | Flag a deficiency on a submitted order | ProgramReviewer |
| POST | `/h2a/job-orders/{jobOrderId}/certify` | Certify the order (thirty-day lead time applies) | ProgramReviewer |
| POST | `/h2a/job-orders/{jobOrderId}/begin-recruitment` | Open the domestic recruitment period | ContractorAdmin |
| POST | `/h2a/job-orders/{jobOrderId}/close-recruitment` | Close recruitment; all applications must be decided | ContractorAdmin |
| POST | `/h2a/job-orders/{jobOrderId}/activate` | Activate the order once a petition is approved and the start date reached | ContractorAdmin |
| POST | `/h2a/job-orders/{jobOrderId}/close` | Close the work period; every assignment must be terminal | ContractorAdmin |
| POST | `/h2a/job-orders/{jobOrderId}/finalize` | Finalize the order; every reconciliation must be FINALIZED | ContractorAdmin |
| POST | `/h2a/job-orders/{jobOrderId}/withdraw` | Withdraw a pre-petitioning order, cascading to draft petitions and undecided applications | ContractorAdmin |
| POST | `/h2a/job-orders/{jobOrderId}/domestic-applications` | Record a domestic worker application | ContractorAdmin |
| GET | `/h2a/job-orders/{id}/domestic-applications` | List domestic applications for an order | Any authenticated role |
| POST | `/h2a/domestic-applications/{applicationId}/decide` | Hire or reject an application under the preference rules | ContractorAdmin |
| POST | `/h2a/workers` | Register a foreign worker | ContractorAdmin |
| GET | `/h2a/workers` | List workers | Any authenticated role |
| GET | `/h2a/workers/{workerId}` | Get a worker | Any authenticated role |
| POST | `/h2a/job-orders/{jobOrderId}/visa-petitions` | Create a petition in DRAFT | ContractorAdmin |
| GET | `/h2a/job-orders/{id}/visa-petitions` | List petitions for an order | Any authenticated role |
| GET | `/h2a/visa-petitions/{petitionId}` | Get a petition | Any authenticated role |
| POST | `/h2a/visa-petitions/{petitionId}/file` | File the petition within the visa ceiling | ContractorAdmin |
| POST | `/h2a/visa-petitions/{petitionId}/link-worker` | Link a REGISTERED worker to a DRAFT or FILED petition | ContractorAdmin |
| POST | `/h2a/visa-petitions/{petitionId}/issue-rfe` | Issue a Request for Evidence (at most two per petition) | ProgramReviewer |
| POST | `/h2a/visa-petitions/{petitionId}/respond-rfe` | Respond to an RFE, returning the petition to FILED | ContractorAdmin |
| POST | `/h2a/visa-petitions/{petitionId}/adjudicate` | Approve or deny the petition | ProgramReviewer |
| POST | `/h2a/consular-appointments` | Schedule a consular interview (daily per-consulate quota of six) | ContractorAdmin |
| GET | `/h2a/consular-appointments` | List consular appointments | Any authenticated role |
| GET | `/h2a/consular-appointments/{appointmentId}` | Get a consular appointment | Any authenticated role |
| POST | `/h2a/consular-appointments/{appointmentId}/complete` | Record the interview outcome | VisaOfficer |
| POST | `/h2a/consular-appointments/{appointmentId}/cancel` | Cancel a scheduled appointment, freeing the slot | ContractorAdmin |
| POST | `/h2a/housing-units` | Register employer-provided housing | ContractorAdmin |
| GET | `/h2a/housing-units` | List housing units | Any authenticated role |
| GET | `/h2a/housing-units/{unitId}` | Get a housing unit, including its occupied_count | Any authenticated role |
| POST | `/h2a/housing-units/{unitId}/inspections` | Record an immutable inspection, flipping the unit's status per result | HousingInspector |
| GET | `/h2a/housing-units/{id}/inspections` | List inspections of a unit | Any authenticated role |
| POST | `/h2a/housing-units/{unitId}/expire` | Flip a CERTIFIED unit to EXPIRED once its validity date has passed | ContractorAdmin |
| POST | `/h2a/housing-assignments` | Move a worker into certified housing within capacity | ContractorAdmin |
| GET | `/h2a/housing-assignments` | List housing assignments | Any authenticated role |
| GET | `/h2a/housing-assignments/{housingAssignmentId}` | Get a housing assignment | Any authenticated role |
| POST | `/h2a/housing-assignments/{housingAssignmentId}/vacate` | Vacate an occupied housing assignment | ContractorAdmin |
| POST | `/h2a/worker-assignments` | Assign a VISA_ISSUED worker to an ACTIVE order of the worker's petition | ContractorAdmin |
| GET | `/h2a/worker-assignments` | List worker assignments | Any authenticated role |
| GET | `/h2a/worker-assignments/{assignmentId}` | Get a worker assignment | Any authenticated role |
| POST | `/h2a/worker-assignments/{assignmentId}/start` | Start work; creates the OPEN wage reconciliation | ContractorAdmin |
| POST | `/h2a/worker-assignments/{assignmentId}/end` | End an assignment as COMPLETED or FOR_CAUSE | ContractorAdmin |
| POST | `/h2a/worker-assignments/{assignmentId}/report-abandonment` | Report abandonment; ends the assignment and opens an audit case | ContractorAdmin, GrowerRep |
| POST | `/h2a/work-logs` | Record one day's hours and units for an ACTIVE assignment | ContractorAdmin |
| GET | `/h2a/worker-assignments/{id}/work-logs` | List work logs of an assignment | Any authenticated role |
| GET | `/h2a/worker-assignments/{id}/reconciliation` | Fetch the assignment's wage reconciliation (array of zero or one) | Any authenticated role |
| POST | `/h2a/worker-assignments/{assignmentId}/finalize-reconciliation` | Freeze the final reconciliation variant for a terminal assignment | ContractorAdmin |
| POST | `/h2a/transfer-requests` | Request a worker transfer to another grower's ACTIVE order | ContractorAdmin, GrowerRep |
| GET | `/h2a/transfer-requests` | List transfer requests | Any authenticated role |
| GET | `/h2a/transfer-requests/{transferRequestId}` | Get a transfer request | Any authenticated role |
| POST | `/h2a/transfer-requests/{transferRequestId}/grower-approve` | Target grower approves the inbound transfer | GrowerRep |
| POST | `/h2a/transfer-requests/{transferRequestId}/grower-reject` | Target grower rejects the transfer | GrowerRep |
| POST | `/h2a/transfer-requests/{transferRequestId}/finalize` | Execute the approved transfer atomically | ContractorAdmin |
| POST | `/h2a/transfer-requests/{transferRequestId}/cancel` | Cancel a PENDING or GROWER_APPROVED transfer | ContractorAdmin, GrowerRep |
| POST | `/h2a/audit-cases` | Open an audit case manually | WageAuditor |
| GET | `/h2a/audit-cases` | List audit cases | Any authenticated role |
| GET | `/h2a/audit-cases/{auditCaseId}` | Get an audit case | Any authenticated role |
| POST | `/h2a/audit-cases/{auditCaseId}/issue-findings` | Record findings and compute the provisional exposure | WageAuditor |
| POST | `/h2a/audit-cases/{auditCaseId}/close-no-action` | Close the case without enforcement action | WageAuditor |
| POST | `/h2a/audit-cases/{auditCaseId}/assess-penalty` | Assess the final civil money penalty, suspending the grower | WageAuditor |
| POST | `/h2a/audit-cases/{auditCaseId}/debar` | Debar the grower, cascading withdrawals | WageAuditor |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` | 403 Forbidden |
| `ERR_GROWER_NOT_FOUND` | 404 Not Found |
| `ERR_WAGE_DETERMINATION_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_DOMESTIC_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_WORKER_NOT_FOUND` | 404 Not Found |
| `ERR_VISA_PETITION_NOT_FOUND` | 404 Not Found |
| `ERR_CONSULAR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_HOUSING_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_HOUSING_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_WORKER_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_INVALID_HOURS` | 400 Bad Request |
| `ERR_INVALID_DEBARMENT_TERM` | 400 Bad Request |
| `ERR_INVALID_FINDINGS` | 400 Bad Request |
| `ERR_GROWER_NOT_ACTIVE` | 409 Conflict |
| `ERR_WAGE_DETERMINATION_NOT_PUBLISHED` | 409 Conflict |
| `ERR_JOB_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_PETITION_INVALID_STATE` | 409 Conflict |
| `ERR_WORKER_INVALID_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_APPOINTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_TRANSFER_INVALID_STATE` | 409 Conflict |
| `ERR_AUDIT_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_RECONCILIATION_INVALID_STATE` | 409 Conflict |
| `ERR_HOUSING_UNIT_INVALID_STATE` | 409 Conflict |
| `ERR_HOUSING_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_CERTIFICATION_LEAD_TIME` | 409 Conflict |
| `ERR_ORDER_NOT_YET_STARTED` | 409 Conflict |
| `ERR_ORDER_PERIOD_NOT_ENDED` | 409 Conflict |
| `ERR_ORDER_PERIOD_ENDED` | 409 Conflict |
| `ERR_APPOINTMENT_DATE_NOT_FUTURE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_YET_DUE` | 409 Conflict |
| `ERR_WORK_LOG_DATE_OUT_OF_RANGE` | 409 Conflict |
| `ERR_INSPECTION_DATE_IN_FUTURE` | 400 Bad Request |
| `ERR_HOUSING_CERTIFICATION_STILL_VALID` | 409 Conflict |
| `ERR_DOMESTIC_PREFERENCE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_HOUSING_NOT_CERTIFIED` | 409 Conflict |
| `ERR_GROWER_MISMATCH` | 409 Conflict |
| `ERR_SAME_GROWER_TRANSFER` | 409 Conflict |
| `ERR_WORKER_ORDER_MISMATCH` | 409 Conflict |
| `ERR_WORKER_NOT_ON_PETITION` | 409 Conflict |
| `ERR_DUPLICATE_FEIN` | 409 Conflict |
| `ERR_DUPLICATE_PASSPORT` | 409 Conflict |
| `ERR_DUPLICATE_RECEIPT_CODE` | 409 Conflict |
| `ERR_DUPLICATE_WORK_LOG` | 409 Conflict |
| `ERR_CONSULATE_CAPACITY_FULL` | 409 Conflict |
| `ERR_HOUSING_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_WORKER_HOUSING_OVERLAP` | 409 Conflict |
| `ERR_WORKER_CEILING_EXCEEDED` | 409 Conflict |
| `ERR_PETITION_WORKER_OVERFLOW` | 409 Conflict |
| `ERR_PETITION_EXCEEDS_VISA_CEILING` | 409 Conflict |
| `ERR_RFE_LIMIT_REACHED` | 409 Conflict |
| `ERR_APPROVED_COUNT_MISMATCH` | 409 Conflict |
| `ERR_UNDECIDED_APPLICATIONS_REMAIN` | 409 Conflict |
| `ERR_OPEN_ASSIGNMENTS_REMAIN` | 409 Conflict |
| `ERR_UNFINALIZED_RECONCILIATIONS_REMAIN` | 409 Conflict |
| `ERR_OPEN_PETITIONS_EXIST` | 409 Conflict |
| `ERR_WORKER_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_WORKER_HAS_ACTIVE_APPOINTMENT` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_TRANSFER` | 409 Conflict |
| `ERR_NO_APPROVED_PETITION` | 409 Conflict |
| `ERR_STALE_JOB_ORDER_VERSION` | 412 Precondition Failed |
