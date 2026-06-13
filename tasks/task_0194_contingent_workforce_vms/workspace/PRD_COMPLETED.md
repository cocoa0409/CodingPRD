# Contingent Workforce VMS API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Contingent Workforce Vendor Management System (VMS) API — the system of record an MSP (Managed Service Provider) uses to run a client's contract-labour program end to end. A program brings together staffing suppliers, the requisitions and statements of work they bid against, the candidates they submit, and the assignments, timesheets, expenses, and milestone deliverables that follow once a candidate is engaged. The API exists to keep all of that coordinated under one consistent set of rules so that the people running the program, the suppliers feeding it, the hiring managers selecting talent, and the finance team paying for it all act against the same shared state.

The hard problems the system must solve are the ones that span more than one record. A worker's co-employment tenure is not a property of any single assignment — it is the cumulative engaged time that worker has accrued across every assignment in the program, and it governs whether that worker may be hired or resumed at all. The bill rate a client pays is the product of a supplier's submitted pay rate and a program-level markup ceiling. The order in which suppliers may bid on a requisition is a clock-gated waterfall driven by their distribution tier. Hiring is a race for a finite number of openings, guarded by optimistic concurrency so two managers cannot both believe a seat is still open. The sections that follow describe these workflows in business terms; the implementer should treat the prose as the authoritative contract and reconstruct the data model and rules from it.

Time in this system is explicit and program-scoped. Each program carries its own logical clock, which never advances on its own — it moves only when an operator advances it, and several important behaviours (supplier release, timesheet auto-approval, tenure escalation) fire as side effects of that advance. The system favours immediate consistency: every cascade described below completes within the request that triggered it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly four roles, spelled precisely as follows: `ProgramManager`, `HiringManager`, `Supplier`, and `Finance`. When a caller's role is well-formed but not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The roles divide ownership of the domain cleanly. A `ProgramManager` is the MSP operator who owns the program itself, its suppliers, its requisitions and statements of work, the distribution and hiring decisions, the assignment lifecycle, and the program clock. A `HiringManager` is the client-side decision-maker who shortlists, interviews, counters rates, extends offers, and accepts or rejects deliverables, timesheets, and expenses. A `Supplier` is the staffing vendor that submits candidates, proposes rates, enters timesheets and expenses, and drives milestone progress. A `Finance` user handles accounts payable and billing, invoicing approved timesheets and expenses and accepted milestones.

Three of these roles are operator identities not tied to any persisted entity. When `X-User-Role` is `ProgramManager`, `X-User-ID` is an opaque operator identifier; the server may record it but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `HiringManager` and when `X-User-Role` is `Finance`: in both cases `X-User-ID` is opaque and is not matched against any entity. The `Supplier` role is different. When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting `Supplier` entity, and ownership checks apply: on any resource that traces back to a supplier — a `Submittal`, a `StatementOfWork` whose `supplier_id` names that supplier, or a `Timesheet`, `Expense`, or `Milestone` reachable through one of those — the resource's supplier linkage is compared to `X-User-ID`. A `Supplier` acting on a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0. A `limit` or `offset` outside its allowed range is rejected with `ERR_VALIDATION_LIMIT`.

Unless a specific endpoint says otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Program Clock

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. All entities in this system are mutable record types, so each also carries an `updated_at` timestamp — an ISO 8601 UTC value refreshed on every mutation — and a `version`, an integer that starts at its initial value of 1 and increments by one on each mutation. The `version` field underpins the optimistic-concurrency mechanism described in §2.7.

Time is modelled per program. Each `Program` holds a logical clock, `current_clock`, expressed as a UTC datetime. A freshly created program's clock starts at `1970-01-01T00:00:00.000Z`. The clock never moves by itself: it advances only when a `ProgramManager` explicitly advances it to a supplied target instant — provided as the `to_iso8601` field in the request body — or when the test-driving clock-set capability seeds it directly to that same `to_iso8601` instant. Advancing the clock is the trigger for every time-gated behaviour in the system — supplier release in the distribution waterfall, automatic timesheet approval, and the escalation of worker tenure — all of which are detailed in §3. The clock-set capability, by contrast, moves `current_clock` to an exact instant without firing any of those sweeps; it exists purely to seed test scenarios.

### 2.5. Nested Reachability and Left-to-Right Resolution

The resource topology is flat: every collection is addressed directly, and cross-entity links travel as foreign-key fields in request bodies rather than as nested URL segments. Even so, several endpoints reference a target resource by an identifier in the path, and many write operations name related resources by id in the body. When a request names resources, the system validates their existence before applying any business rule, and any referenced resource that does not exist yields `ERR_NOT_FOUND`. For requests that carry several identifiers, resolution proceeds left to right and the first unresolved identifier is the one reported.

List endpoints accept filter parameters so callers can reach resources by their relationships rather than by remembering ids. Suppliers, workers, requisitions, statements of work, and assignments can each be filtered by `program_id`; distributions and submittals by `requisition_id` and `supplier_id`; submittals and assignments additionally by `worker_profile_id`; assignments by `submittal_id`; timesheets and expenses by `assignment_id`; and milestones by `statement_of_work_id`. Most list endpoints also accept a `status` filter, assignments accept `engagement_status` and `compliance_status` filters, and expenses accept a `category` filter.

### 2.6. Monetary Precision and Rounding

All money in the system is held as whole integer cents — pay rates, bill rates, timesheet amounts, expense amounts, milestone amounts, and SOW values are never fractional cents. Wherever a calculation produces a non-integer cent figure (for example, multiplying an hourly rate by a fractional number of hours, or deriving a bill rate from a markup), the result is rounded to the nearest whole cent using the round-half-up convention: a result whose fractional part is exactly one-half rounds up to the next cent. Markup percentages are fractions (for instance, 0.45 represents 45%) and, where a calculation compares a markup against a ceiling, the comparison is performed on the exact unrounded ratio, as detailed in §3.4. Each calculation section in §3 states precisely where rounding is applied and in what order.

### 2.7. Optimistic Concurrency on the Hiring Race

Filling a requisition is a competition for a finite number of openings, and the system guards it with optimistic concurrency so that no manager can hire into a seat that has already been taken on the basis of a stale view. The hire operation against an `OFFERED` submittal requires the field `expected_requisition_version` in its request body, carrying the `version` of the parent `Requisition` that the client last observed. This field is mandatory for hiring; it is not an optional check. If `expected_requisition_version` does not equal the requisition's current `version`, the hire is rejected with `ERR_STALE_VERSION`, which returns HTTP 412. A version advances every time the requisition is distributed and every time a candidate is hired against it, so if another writer has hired a different candidate since the client last read the requisition, that client's `expected_requisition_version` will no longer match and its hire is refused — preventing it from filling a seat it never saw consumed. No other endpoint in the system takes a version field; only the hire operation participates in this concurrency check.

### 2.8. Hierarchical Consistency and Automatic Cascades

Many operations in this system mutate more than the resource named in the request. When a requisition fills, when a milestone is invoiced, when a clock advance crosses a release boundary or a tenure threshold — in each case the system propagates the consequence to every affected record within the same request, immediately and atomically. Each such secondary mutation is a real mutation: the affected resource's `updated_at` is refreshed and its `version` increments, exactly as if it had been changed directly. The specific cascades — distribution revocation when a requisition fills, sibling-submittal rejection, SOW auto-completion when its last milestone is invoiced, and the cross-dimension safety stop when a worker breaches tenure — are described in the §3 workflows where they belong. The governing principle is uniform: a state change is never left half-applied, and a parent or child may be transitioned by the system, without a direct client request on that resource, whenever the rules below demand it.

### 2.9. Program, Supplier, and Worker Eligibility

Several operations require their surrounding context to be in good standing. A `Program` carries a `status` of `ACTIVE`, `SUSPENDED`, or `CLOSED`; it begins `ACTIVE`. Operations that require an active program — distributing a requisition and activating a statement of work — are rejected with `ERR_PROGRAM_NOT_ACTIVE` when the program is not `ACTIVE`. A `Supplier` carries a `status` of `ACTIVE` or `SUSPENDED`, beginning `ACTIVE`; a `SUSPENDED` supplier may neither receive a distribution nor create submittals, and operations that require an eligible supplier — one that is `ACTIVE` and belongs to the program in question, and that was actually listed for the distribution or named on the SOW — fail with `ERR_SUPPLIER_NOT_ELIGIBLE`. A `WorkerProfile` is unique within its program by `national_id_hash`: attempting to register a second worker with a `national_id_hash` already used in the same program is rejected with `ERR_DUPLICATE_WORKER`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program and Its Suppliers

A `ProgramManager` creates a program by supplying a display `name`, the end-client's `client_name`, and the program's governing parameters: a `default_markup_pct` and a `max_markup_pct` (each a markup fraction that must be at least 0 and no greater than 2.0), a `coemployment_tenure_limit_days` (the maximum cumulative engaged calendar days any one worker may serve across all assignments before a mandatory break, which must be at least 2), and a `tenure_warning_threshold_days` (the cumulative-day mark at which an active assignment begins flagging, which must be at least 1 and strictly less than `coemployment_tenure_limit_days`). The caller may also supply `timesheet_approval_window_days`, the number of days a submitted timesheet may sit before it auto-approves; when omitted it defaults to 7, and any supplied value must be at least 1. On creation the program's `status` is `ACTIVE` and its `current_clock` is set to `1970-01-01T00:00:00.000Z`. If `tenure_warning_threshold_days` is not strictly less than `coemployment_tenure_limit_days`, creation is rejected with `ERR_THRESHOLD_INVALID`. A `ProgramManager` may later suspend a program, moving its `status` to `SUSPENDED`.

Within a program, the `ProgramManager` registers suppliers. A `Supplier` is created with the owning `program_id`, a `name`, and a distribution `tier` — an integer of at least 1 where a lower number means the supplier is released earlier in the distribution waterfall, so tier 1 is the primary tier released first. A supplier registered with a `tier` below 1 is rejected with `ERR_TIER_INVALID`. A newly registered supplier's `status` is `ACTIVE`. The `ProgramManager` may suspend a supplier, setting its `status` to `SUSPENDED`.

Worker profiles may be created by either a `ProgramManager` or a `Supplier`. A `WorkerProfile` is created with its `program_id`, the worker's `full_name`, and a `national_id_hash` — an opaque hashed identifier that lets the system recognize the same human across different submittals and assignments, and which must be unique within the program. A new profile starts with `cumulative_engaged_days` of 0 and a `tenure_status` of `CLEAR`; both of those are computed fields that the system maintains as assignments accrue, never client inputs.

### 3.2. Requisitions and the Distribution Waterfall

A requisition is the headcount request suppliers bid against. A `ProgramManager` or `HiringManager` creates one with the owning `program_id`, a role `title`, an `openings` count (the number of seats to fill, at least 1), and a `max_pay_rate_cents` ceiling (the per-hour pay rate, in cents, that a supplier may submit, at least 1). The creator may also set `tier_release_interval_hours`, the number of hours each supplier tier is held exclusive before the next distinct tier opens; it must be at least 0 and defaults to 24 when omitted. A new requisition has `status` of `DRAFT` and a `filled_count` of 0.

Distribution opens the requisition to suppliers. A `ProgramManager` distributes a `DRAFT` requisition by supplying `supplier_ids`, a list of at least one supplier. The program must be `ACTIVE`, or the request fails with `ERR_PROGRAM_NOT_ACTIVE`; every listed supplier must be `ACTIVE` and belong to this program, or the request fails with `ERR_SUPPLIER_NOT_ELIGIBLE` — and a listed `supplier_id` that does not resolve to any supplier is likewise treated as ineligible and reported as `ERR_SUPPLIER_NOT_ELIGIBLE` rather than `ERR_NOT_FOUND`. On success the requisition moves from `DRAFT` to `DISTRIBUTED`, its `version` increments by one, and the system creates one `Distribution` per listed supplier. Each `Distribution` records the `requisition_id` and `supplier_id` it links, snapshots the supplier's current `tier` into `tier_at_distribution`, and is assigned a `released_at` instant by the waterfall calculation below. Re-distributing an already-`DISTRIBUTED` requisition is not idempotent and is rejected with `ERR_INVALID_STATE`.

The **distribution waterfall** computes each `Distribution.released_at` and thereby its `status` (`PENDING`, `RELEASED`, or `REVOKED`). Take the distinct `tier_at_distribution` values among the distributions created by this one distribute call and sort them in ascending order. The distribution clock for the call is the program's `current_clock` at the moment of distribution. A tier's release offset is its zero-based position in that sorted list of distinct tiers, multiplied by the requisition's `tier_release_interval_hours`. Each distribution's `released_at` is the distribution clock plus its tier's release offset, measured in whole hours. Concretely, the lowest distinct tier sits at position zero, so its offset is zero and its distributions are `RELEASED` immediately at distribution time; the next distinct tier releases one interval after the lowest, the third distinct tier two intervals after the lowest, and so on — each distinct tier is offset from the distribution clock by its position times the interval, not chained off any wall-clock release event. Distributions that share a tier share the same offset and the same `released_at`. A distribution whose `released_at` is at or before the current clock is `RELEASED`; one whose `released_at` is still in the future is `PENDING`.

Time releases the later tiers. When a `ProgramManager` advances the clock, the system sweeps every `PENDING` distribution whose `released_at` is at or before the new clock and flips it to `RELEASED`; the owning requisition remains `DISTRIBUTED` throughout. A supplier may create a submittal only once its distribution for that requisition is `RELEASED`; attempting to submit while the distribution is still `PENDING` — that is, while its `released_at` is after the current clock — is rejected with `ERR_DISTRIBUTION_NOT_RELEASED`.

A `ProgramManager` may close or cancel a requisition. Closing a `DISTRIBUTED` requisition moves it to `CLOSED`, revokes every non-terminal distribution (setting their `status` to `REVOKED`), and rejects every non-terminal submittal on it (setting their `status` to `REJECTED`). Cancelling moves the requisition to `CANCELLED`: a `DRAFT` requisition cancels cleanly with no side effects, while cancelling a `DISTRIBUTED` requisition is permitted only when no `HIRED` submittal exists against it — otherwise the cancel is refused with `ERR_REQUISITION_HAS_HIRES` — and, when allowed, likewise revokes all non-terminal distributions and rejects all non-terminal submittals. `CLOSED` and `CANCELLED` are terminal requisition states.

### 3.3. Submittals and the Rate-Negotiation Loop

A `Supplier` submits a candidate against a requisition by providing the `requisition_id`, the supplier's own `supplier_id`, the `worker_profile_id` of the candidate, a `pay_rate_cents` (the per-hour rate paid to the worker, at least 1), and optionally a `bill_rate_cents` (the per-hour rate billed to the client). The submittal is created with `status` of `SUBMITTED` and a `rounds` count of 0. The supplier's distribution for this requisition must be `RELEASED` first, as described in §3.2. A worker may hold only one live submittal per requisition from a given supplier: if that same worker already has a non-terminal submittal on this requisition from this supplier, the new submittal is rejected with `ERR_DUPLICATE_SUBMITTAL`. The bill rate and markup are derived at creation by the calculation in §3.4, which also governs the rate-ceiling checks.

A submittal advances through a hiring funnel driven mostly by the `HiringManager`. Shortlisting moves it from `SUBMITTED` to `SHORTLISTED`, and is permitted only while the parent requisition is `DISTRIBUTED`; attempting it otherwise yields `ERR_INVALID_STATE`. Starting an interview moves it from `SHORTLISTED` to `INTERVIEWING`. From `INTERVIEWING`, the `Supplier` may propose a new rate (see §3.4), which moves the submittal to `RATE_PROPOSED`. From `RATE_PROPOSED` the `HiringManager` has two onward moves. The first is to counter the rate, which returns the submittal from `RATE_PROPOSED` to `INTERVIEWING` for another round and increments `rounds` by one; this counter is permitted only while `rounds` is below 5, and a counter attempted once `rounds` has already reached 5 is rejected with `ERR_NEGOTIATION_ROUNDS_EXCEEDED`. The second is to extend an offer, moving the submittal from `RATE_PROPOSED` to `OFFERED`; an offer is permitted only while the requisition still has seats, that is while `filled_count` is below `openings`, and is otherwise rejected with `ERR_REQUISITION_FULL`. The `INTERVIEWING` ⇄ `RATE_PROPOSED` pair is the cyclic negotiation loop, and it is capped at 5 rounds.

A submittal may exit to a terminal state at several points. The `HiringManager` may reject a submittal that is in `SUBMITTED`, `SHORTLISTED`, `INTERVIEWING`, or `RATE_PROPOSED`, moving it to `REJECTED`. The `Supplier` may withdraw a submittal from any of those same four states, moving it to `WITHDRAWN`. `HIRED`, `REJECTED`, and `WITHDRAWN` are the terminal submittal states; the hire transition itself is covered in §3.5.

### 3.4. Bill-Rate Derivation and the Markup Ceiling

The **bill-rate-and-markup** calculation runs whenever a submittal is created and again whenever a supplier proposes a new rate. It resolves what looks like a circular dependency between the bill rate and the markup by pinning the evaluation order. First, the bill rate is settled: if the request supplies `bill_rate_cents`, that value is used exactly as given; otherwise the bill rate is derived as the worker's `pay_rate_cents` multiplied by one plus the program's `default_markup_pct`, with the product rounded half-up to whole cents. Second, the `effective_markup_pct` is computed as the bill rate divided by the pay rate, minus one. This markup is kept as an exact ratio — it is deliberately not re-rounded before the ceiling comparison.

Two checks then guard the rate, and both apply identically at submittal creation and at rate proposal. The pay rate may not exceed the requisition's `max_pay_rate_cents`; a `pay_rate_cents` greater than that ceiling is rejected with `ERR_PAY_RATE_EXCEEDS_MAX`. The effective markup may not exceed the program's `max_markup_pct`; an `effective_markup_pct` greater than that ceiling is rejected with `ERR_MARKUP_EXCEEDS_MAX`. Both ceilings are inclusive: a pay rate exactly equal to `max_pay_rate_cents` is accepted, and an effective markup exactly equal to `max_markup_pct` is accepted — only values strictly above the ceiling are refused. When a supplier proposes a rate, the new `pay_rate_cents`, `bill_rate_cents`, and `effective_markup_pct` replace the prior values on the submittal once both checks pass.

### 3.5. Hiring, Assignment Creation, and the Fill Cascade

Hiring is the `ProgramManager`'s act of converting an `OFFERED` submittal into a live engagement, and it carries the system's only optimistic-concurrency guard. The hire request supplies `expected_requisition_version`, a `start_date`, and a `planned_end_date`. Four preconditions are checked. First, `expected_requisition_version` must equal the requisition's current `version`, or the hire is rejected with `ERR_STALE_VERSION` (HTTP 412), as specified in §2.7. Second, the requisition must still have an open seat — `filled_count` below `openings` — or the hire fails with `ERR_REQUISITION_FULL`. Third, the candidate's worker must not be in tenure breach: if the `WorkerProfile.tenure_status` is `BREACH`, the hire is refused with `ERR_TENURE_LIMIT_REACHED`. Fourth, the new engagement window must not collide with the worker's existing commitments: the closed interval from `start_date` through `planned_end_date` must not overlap the closed interval (from its own `start_date` through its `planned_end_date`) of any non-`ENDED` assignment already held by the same worker — and because both intervals are closed, a shared endpoint counts as an overlap — otherwise the hire is rejected with `ERR_WORKER_DOUBLE_BOOKED`.

On a successful hire the submittal moves to `HIRED` and the system creates an `Assignment`. The assignment records its `program_id`, the originating `submittal_id`, and the `worker_profile_id`, all set by the system, and copies the agreed `pay_rate_cents` and `bill_rate_cents` from the hired submittal. It stores the supplied `start_date` and `planned_end_date`; its `actual_end_date` is left null until offboarding, and its `engaged_days` is maintained by the tenure rollup of §3.7 — it is not stored as a fixed 0 but always reflects the live inclusive day count per §3.7 (which, on the hire day with `start_date` at or before the current clock, is already at least 1, and is floored at 0 when `start_date` is still in the future). The new assignment starts with `engagement_status` of `ACTIVE` and a `compliance_status` seeded from the worker's current `tenure_status` under the name mapping `CLEAR`→`CLEAR`, `WARNING`→`TENURE_WARNING`, `BREACH`→`TENURE_BREACH`. The hire then increments the requisition's `filled_count` by one and increments the requisition's `version` by one. If that increment brings `filled_count` up to `openings`, the requisition is driven from `DISTRIBUTED` to `FILLED`; on that transition the system revokes every still-`PENDING` or `RELEASED` distribution (status to `REVOKED`) and rejects every remaining non-terminal submittal on the requisition (status to `REJECTED`).

### 3.6. The Assignment's Two Dimensions: Engagement and Compliance

An assignment tracks two independent dimensions on one record. The `engagement_status` describes the working relationship and takes the values `ACTIVE`, `ON_HOLD`, or `ENDED`, with `ENDED` the only terminal engagement state. The `compliance_status` describes co-employment standing and takes the values `CLEAR`, `TENURE_WARNING`, or `TENURE_BREACH`; it evolves on its own, driven by the worker's accumulating tenure, and keeps updating right up until the engagement reaches `ENDED`.

The `ProgramManager` drives the engagement dimension directly. Placing an assignment on hold moves `engagement_status` from `ACTIVE` to `ON_HOLD`, and is permitted only when the assignment is currently `ACTIVE`, otherwise yielding `ERR_INVALID_STATE`. Resuming moves it from `ON_HOLD` back to `ACTIVE`, and is permitted only when the assignment is currently `ON_HOLD` — attempting to resume an assignment that is not `ON_HOLD` is rejected with `ERR_INVALID_STATE`; additionally, a resume is refused with `ERR_TENURE_LIMIT_REACHED` when the assignment's `compliance_status` is `TENURE_BREACH`, since a breached worker cannot be returned to active service. Offboarding ends the engagement, moving `engagement_status` from either `ACTIVE` or `ON_HOLD` to `ENDED`; it is blocked while any timesheet or expense on the assignment is still in `SUBMITTED` (awaiting approval), in which case it is rejected with `ERR_OPEN_APPROVALS_PENDING`. On a successful offboard the system sets `actual_end_date` to the current program clock date, freezes `engaged_days` at the inclusive day count, and recomputes the worker's tenure via the rollup of §3.7.

The compliance dimension is driven entirely by the system during clock advances, never by a direct request, and is detailed alongside the tenure rollup in §3.7.

### 3.7. Co-Employment Tenure: Rollup and Escalation

Co-employment tenure measures elapsed engaged calendar time, not hours worked, and it rolls up across every assignment a worker holds in the program. Each assignment's `engaged_days` is an inclusive calendar-day count: for an assignment whose `engagement_status` is `ENDED`, it is the number of days from `start_date` through `actual_end_date` counting both endpoints; for an assignment that is still `ACTIVE` or `ON_HOLD`, it is the number of days from `start_date` through the program's current clock date, again counting both endpoints (and floored at 0 should the current clock date precede `start_date`). Crucially, an `ON_HOLD` assignment still accrues calendar tenure — putting a worker on hold does not pause the co-employment clock, because co-employment is about elapsed engaged time rather than time actually worked.

The **worker tenure rollup** runs as a side effect of offboarding and again on every clock advance. For a given worker it sums `engaged_days` across all of that worker's assignments in the program — those that are `ACTIVE`, those that are `ON_HOLD`, and those that are `ENDED` alike — processing them in ascending `start_date` order and, for ties, ascending `created_at` order, and stores the total in the worker's `cumulative_engaged_days`. The worker's `tenure_status` is then derived from that total against the program's thresholds: a cumulative total at or above `coemployment_tenure_limit_days` yields `BREACH`; otherwise a total at or above `tenure_warning_threshold_days` yields `WARNING`; otherwise `CLEAR`.

When the clock advances, the system recomputes every non-`ENDED` worker's `cumulative_engaged_days` and `tenure_status`, then propagates the result onto that worker's active assignments' `compliance_status`. An assignment whose engagement has not yet ended escalates as tenure climbs: from `CLEAR` to `TENURE_WARNING` once the worker's `cumulative_engaged_days` reaches at least `tenure_warning_threshold_days` while still below `coemployment_tenure_limit_days`; and to `TENURE_BREACH` once the worker's `cumulative_engaged_days` reaches at least `coemployment_tenure_limit_days`. A large clock jump may carry a worker straight past the warning band: when the cumulative total goes from below the warning mark directly to at or above `coemployment_tenure_limit_days` and the prior `compliance_status` was `CLEAR`, the assignment moves directly from `CLEAR` to `TENURE_BREACH`, skipping `TENURE_WARNING`. The breach carries a cross-dimension safety stop: at the moment an assignment reaches `TENURE_BREACH`, if its `engagement_status` is `ACTIVE` the system forces it to `ON_HOLD`. This is the single point in the system where the compliance dimension forces an engagement change; the warning escalation, by contrast, touches only `compliance_status` and leaves `engagement_status` untouched.

### 3.8. Timesheets: Entry, Approval, and Billing

A `Supplier` opens a timesheet against an assignment by supplying the `assignment_id`, a `week_start_date` (the Monday of the reported week at UTC midnight), the `regular_hours` for that week (at least 0 and no more than 168), and optionally `overtime_hours` (at least 0 and no more than 168, defaulting to 0). The timesheet is created in `DRAFT` with `submitted_at` null and both `pay_amount_cents` and `bill_amount_cents` at 0 until the amounts calculation runs at approval. Each assignment may hold only one timesheet per weekly bucket: if another timesheet on the same assignment already occupies the exact same `week_start_date`, the new one is rejected with `ERR_DUPLICATE_WEEK`. The collision is an exact match on the week bucket — adjacent weeks do not collide, only an identical `week_start_date` does.

Submitting a timesheet moves it from `DRAFT` to `SUBMITTED`, and is allowed only while the parent assignment's `engagement_status` is `ACTIVE`; submitting against a non-active assignment is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`. The timesheet must also report some work — the sum of `regular_hours` and `overtime_hours` must be greater than 0, or the submit is rejected with `ERR_EMPTY_TIMESHEET`. On submit the system stamps `submitted_at` with the current program clock time.

A submitted timesheet reaches `APPROVED` by either of two paths. A `HiringManager` may approve it directly. Alternatively, the system auto-approves it on a clock advance once the approval window has elapsed — that is, once the clock reaches at or beyond `submitted_at` plus the program's `timesheet_approval_window_days`. Either path runs the **timesheet-amounts** calculation. That calculation uses an overtime multiplier of 1.5 and is computed component-by-component with rounding applied to each component before summing — the four money components are never summed before rounding, and hours are never summed before multiplying. Specifically: the regular pay component is `regular_hours` times the assignment's `pay_rate_cents`, rounded half-up to whole cents; the overtime pay component is `overtime_hours` times the assignment's `pay_rate_cents` times 1.5, rounded half-up to whole cents; and `pay_amount_cents` is the sum of those two rounded components. In parallel, the regular bill component is `regular_hours` times the assignment's `bill_rate_cents`, rounded half-up; the overtime bill component is `overtime_hours` times the assignment's `bill_rate_cents` times 1.5, rounded half-up; and `bill_amount_cents` is the sum of those two rounded components.

A `HiringManager` may instead reject a `SUBMITTED` timesheet, moving it to `REJECTED`. From `REJECTED`, the `Supplier` may reopen it, which returns it to `DRAFT` for correction and clears `submitted_at`. This reject-then-reopen path is the timesheet rework loop. Finally, `Finance` invoices an `APPROVED` timesheet, moving it to `INVOICED`; invoicing a timesheet that is not `APPROVED` is rejected with `ERR_INVALID_STATE`. `INVOICED` is the terminal timesheet state.

### 3.9. Expenses: Entry, Approval, and Per-Category Caps

A `Supplier` records an expense against an assignment by supplying the `assignment_id`, a `category` drawn from `TRAVEL`, `LODGING`, `MEALS`, `EQUIPMENT`, or `OTHER`, an `amount_cents` (the submitted amount, at least 1), and optionally a `billable` flag (whether the cost is passed through to the client, defaulting to true). The expense starts in `DRAFT` with `reimbursable_amount_cents` at 0 until the reimbursement calculation runs at approval. Submitting it moves it from `DRAFT` to `SUBMITTED`, allowed only while the parent assignment's `engagement_status` is `ACTIVE`, otherwise rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`.

A `HiringManager` approves a `SUBMITTED` expense, moving it to `APPROVED` and running the **expense-reimbursement** calculation. Reimbursement applies a per-category cap and sets `reimbursable_amount_cents` to the smaller of the submitted `amount_cents` and the cap for that category. The caps, in cents, are 50000 for `TRAVEL`, 30000 for `LODGING`, 7500 for `MEALS`, 100000 for `EQUIPMENT`, and 20000 for `OTHER`. The cap is inclusive: a submitted amount exactly equal to its category cap reimburses in full, while an amount one cent above the cap is reimbursed only up to the cap. The `billable` flag has no bearing on `reimbursable_amount_cents` — a non-billable expense is still reimbursed to the worker at the same capped figure; `billable` only governs whether the cost is later passed through to the client's bill.

A `HiringManager` may instead reject a `SUBMITTED` expense, moving it to `REJECTED`; from `REJECTED` the `Supplier` may reopen it back to `DRAFT`, the expense rework loop. `Finance` invoices an `APPROVED` expense, moving it to `INVOICED`; invoicing an expense that is not `APPROVED` is rejected with `ERR_INVALID_STATE`. `INVOICED` is the terminal expense state.

### 3.10. Statements of Work and Milestone Deliverables

A statement of work governs fixed-price deliverable engagements alongside the time-and-materials assignment flow. A `ProgramManager` creates a `StatementOfWork` with its `program_id`, the responsible `supplier_id`, a `title`, and a `total_value_cents` — a not-to-exceed contract value, at least 1, that the sum of accepted and invoiced milestone amounts may never exceed. A new SOW starts in `DRAFT` with `invoiced_value_cents` of 0. The `ProgramManager` adds milestones to a `DRAFT` SOW; each `Milestone` carries its `statement_of_work_id`, a deliverable `name`, a `milestone_amount_cents` (the fixed payment for that milestone, at least 1), and a `sequence` (its ordering index within the SOW, at least 1). Milestones begin in `PENDING`.

Activating a SOW moves it from `DRAFT` to `ACTIVE` and is performed by a `ProgramManager`. Activation has four preconditions: the program must be `ACTIVE`, or it fails with `ERR_PROGRAM_NOT_ACTIVE`; the named supplier must be `ACTIVE` and in this program, or it fails with `ERR_SUPPLIER_NOT_ELIGIBLE`; at least one milestone must exist under the SOW, or it fails with `ERR_SOW_NO_MILESTONES`; and the sum of `milestone_amount_cents` over all milestones must not exceed `total_value_cents`, or it fails with `ERR_SOW_VALUE_EXCEEDED`.

Each milestone runs its own deliverable lifecycle, driven by the `Supplier` and the `HiringManager`. The `Supplier` starts a milestone, moving it from `PENDING` to `IN_PROGRESS`, which requires the SOW to be `ACTIVE` (otherwise `ERR_INVALID_STATE`). The `Supplier` then submits the deliverable, moving it from `IN_PROGRESS` to `SUBMITTED`; submission enforces ordering — every lower-`sequence` milestone in the same SOW must already be `ACCEPTED` or `INVOICED`, or the submit is rejected with `ERR_MILESTONE_SEQUENCE_VIOLATION`. The `HiringManager` then either accepts or rejects the submitted milestone. Acceptance moves it from `SUBMITTED` to `ACCEPTED`, but only if the not-to-exceed ceiling still holds: the SOW's current `invoiced_value_cents`, plus the `milestone_amount_cents` of milestones in the SOW that are already `ACCEPTED`, plus this milestone's own `milestone_amount_cents`, must not exceed `total_value_cents`, or the accept is rejected with `ERR_SOW_VALUE_EXCEEDED`. Rejection moves the milestone from `SUBMITTED` to `REJECTED`; from `REJECTED` the `Supplier` may start it again, returning it to `IN_PROGRESS` (again requiring the SOW to be `ACTIVE`) — the milestone rework loop.

`Finance` invoices an `ACCEPTED` milestone, moving it from `ACCEPTED` to `INVOICED`; invoicing a milestone that is not `ACCEPTED` is rejected with `ERR_INVALID_STATE`. Invoicing increments the SOW's `invoiced_value_cents` by that milestone's `milestone_amount_cents`. If, after that increment, every milestone under the SOW is `INVOICED`, the system drives the SOW from `ACTIVE` to `COMPLETED` — a parent state that the system derives automatically from its children rather than from any direct request. `INVOICED` is the terminal milestone state.

A `ProgramManager` may close or cancel a SOW. A `COMPLETED` SOW may be closed, moving it to `CLOSED`. An `ACTIVE` SOW may also be closed, but only when no milestone is sitting in `SUBMITTED` awaiting acceptance; a close attempted while a submitted milestone is still pending acceptance is rejected with `ERR_OPEN_APPROVALS_PENDING`. A `DRAFT` SOW may be cancelled, moving it to `CANCELLED`. `CLOSED` and `CANCELLED` are the terminal SOW states.

### 3.11. Request-Body Validity and the Order of Checks

Beyond the rules already stated, every write endpoint validates the shape of its request body: enum fields must carry recognized members, amounts that must be positive must be positive, hour fields must fall within their 0-to-168 range, required fields must be present, a markup fraction must lie between 0 and 2.0 inclusive, and a program's warning threshold must be strictly below its tenure limit. A body that violates any of these field-level rules is rejected with `ERR_INVALID_REQUEST`.

When several checks could apply to one request, they are evaluated in a fixed priority order so that the reported error is deterministic. The user-context header check comes first; a request lacking valid `X-User-ID` or `X-User-Role` headers is rejected before anything else. Role authorization comes next, so a caller whose role is not permitted is turned away before any resource is touched. Existence of path-referenced resources is checked third, left to right. Supplier resource-ownership — that an acting `Supplier` owns the submittal, SOW-supplier relationship, timesheet, expense, or milestone it is mutating — is checked fourth. The state-machine precondition (that the target is in a state from which the requested transition is defined) is checked fifth. Domain rules follow in this order: distribution-release timing, then the co-employment tenure safety stop, then milestone sequencing, then the negotiation-rounds cap, then remaining-openings, then the pay-rate ceiling, then the markup ceiling, then the SOW not-to-exceed ceiling, then the open-approvals block on offboard and close, then worker double-booking on hire, then timesheet week uniqueness. Field-level body validity is the last check applied. This ordering matters because an earlier failure masks a later one: for example, a caller acting without permission sees `ERR_FORBIDDEN_FOR_ROLE` even if the body is also malformed.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and clock operation — return a `200 OK` status code. All paths are mounted under the `/vms` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vms/programs` | Create a Program | ProgramManager |
| GET | `/vms/programs/{id}` | Get a Program | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/programs` | List Programs | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/programs/{id}/advance_clock` | Advance the program clock; fire time-gated sweeps | ProgramManager |
| POST | `/vms/programs/{id}/_clock/set` | Set the clock without firing sweeps (seed helper) | ProgramManager |
| POST | `/vms/programs/{id}/suspend` | Suspend a Program | ProgramManager |
| POST | `/vms/suppliers` | Register a Supplier in a program | ProgramManager |
| GET | `/vms/suppliers/{id}` | Get a Supplier | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/suppliers` | List Suppliers | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/suppliers/{id}/suspend` | Suspend a Supplier | ProgramManager |
| POST | `/vms/workers` | Create a WorkerProfile | ProgramManager, Supplier |
| GET | `/vms/workers/{id}` | Get a WorkerProfile | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/workers` | List WorkerProfiles | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/requisitions` | Create a Requisition | ProgramManager, HiringManager |
| GET | `/vms/requisitions/{id}` | Get a Requisition | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/requisitions` | List Requisitions | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/requisitions/{id}/distribute` | Distribute a DRAFT requisition to suppliers | ProgramManager |
| POST | `/vms/requisitions/{id}/close` | Close a distributed requisition | ProgramManager |
| POST | `/vms/requisitions/{id}/cancel` | Cancel a requisition | ProgramManager |
| GET | `/vms/distributions/{id}` | Get a Distribution | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/distributions` | List Distributions | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/submittals` | Submit a candidate with a pay/bill rate | Supplier |
| GET | `/vms/submittals/{id}` | Get a Submittal | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/submittals` | List Submittals | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/submittals/{id}/shortlist` | Shortlist a submittal | HiringManager |
| POST | `/vms/submittals/{id}/start_interview` | Begin interviewing | HiringManager |
| POST | `/vms/submittals/{id}/propose_rate` | Propose a new pay/bill rate | Supplier |
| POST | `/vms/submittals/{id}/counter_rate` | Counter; return to interviewing | HiringManager |
| POST | `/vms/submittals/{id}/offer` | Extend an offer | HiringManager |
| POST | `/vms/submittals/{id}/hire` | Hire an offered candidate (OCC; creates Assignment) | ProgramManager |
| POST | `/vms/submittals/{id}/reject` | Reject a submittal | HiringManager |
| POST | `/vms/submittals/{id}/withdraw` | Withdraw a submittal | Supplier |
| GET | `/vms/assignments/{id}` | Get an Assignment | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/assignments` | List Assignments | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/assignments/{id}/hold` | Place an assignment ON_HOLD | ProgramManager |
| POST | `/vms/assignments/{id}/resume` | Resume an ON_HOLD assignment | ProgramManager |
| POST | `/vms/assignments/{id}/offboard` | Offboard (end) an assignment | ProgramManager |
| POST | `/vms/timesheets` | Create a DRAFT timesheet | Supplier |
| GET | `/vms/timesheets/{id}` | Get a Timesheet | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/timesheets` | List Timesheets | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/timesheets/{id}/submit` | Submit a timesheet for approval | Supplier |
| POST | `/vms/timesheets/{id}/approve` | Approve a timesheet; compute amounts | HiringManager |
| POST | `/vms/timesheets/{id}/reject` | Reject a timesheet | HiringManager |
| POST | `/vms/timesheets/{id}/reopen` | Reopen a rejected timesheet to DRAFT | Supplier |
| POST | `/vms/timesheets/{id}/invoice` | Invoice an approved timesheet | Finance |
| POST | `/vms/expenses` | Create a DRAFT expense | Supplier |
| GET | `/vms/expenses/{id}` | Get an Expense | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/expenses` | List Expenses | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/expenses/{id}/submit` | Submit an expense for approval | Supplier |
| POST | `/vms/expenses/{id}/approve` | Approve an expense; compute reimbursable amount | HiringManager |
| POST | `/vms/expenses/{id}/reject` | Reject an expense | HiringManager |
| POST | `/vms/expenses/{id}/reopen` | Reopen a rejected expense to DRAFT | Supplier |
| POST | `/vms/expenses/{id}/invoice` | Invoice an approved expense | Finance |
| POST | `/vms/statements-of-work` | Create a SOW (DRAFT) | ProgramManager |
| GET | `/vms/statements-of-work/{id}` | Get a SOW | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/statements-of-work` | List SOWs | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/statements-of-work/{id}/activate` | Activate a SOW | ProgramManager |
| POST | `/vms/statements-of-work/{id}/close` | Close a SOW | ProgramManager |
| POST | `/vms/statements-of-work/{id}/cancel` | Cancel a DRAFT SOW | ProgramManager |
| POST | `/vms/milestones` | Add a Milestone to a DRAFT SOW | ProgramManager |
| GET | `/vms/milestones/{id}` | Get a Milestone | ProgramManager, HiringManager, Supplier, Finance |
| GET | `/vms/milestones` | List Milestones | ProgramManager, HiringManager, Supplier, Finance |
| POST | `/vms/milestones/{id}/start` | Start (or restart after rejection) a milestone | Supplier |
| POST | `/vms/milestones/{id}/submit` | Submit a milestone deliverable | Supplier |
| POST | `/vms/milestones/{id}/accept` | Accept a submitted milestone | HiringManager |
| POST | `/vms/milestones/{id}/reject` | Reject a submitted milestone | HiringManager |
| POST | `/vms/milestones/{id}/invoice` | Invoice an accepted milestone | Finance |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_SUPPLIER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_DISTRIBUTION_NOT_RELEASED` | 409 Conflict |
| `ERR_PAY_RATE_EXCEEDS_MAX` | 409 Conflict |
| `ERR_MARKUP_EXCEEDS_MAX` | 409 Conflict |
| `ERR_NEGOTIATION_ROUNDS_EXCEEDED` | 409 Conflict |
| `ERR_REQUISITION_FULL` | 409 Conflict |
| `ERR_REQUISITION_HAS_HIRES` | 409 Conflict |
| `ERR_TENURE_LIMIT_REACHED` | 409 Conflict |
| `ERR_MILESTONE_SEQUENCE_VIOLATION` | 409 Conflict |
| `ERR_SOW_VALUE_EXCEEDED` | 409 Conflict |
| `ERR_SOW_NO_MILESTONES` | 409 Conflict |
| `ERR_OPEN_APPROVALS_PENDING` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_EMPTY_TIMESHEET` | 409 Conflict |
| `ERR_DUPLICATE_WEEK` | 409 Conflict |
| `ERR_WORKER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_DUPLICATE_WORKER` | 409 Conflict |
| `ERR_DUPLICATE_SUBMITTAL` | 409 Conflict |
| `ERR_VALIDATION_LIMIT` | 400 Bad Request |
| `ERR_TIER_INVALID` | 400 Bad Request |
| `ERR_THRESHOLD_INVALID` | 400 Bad Request |
