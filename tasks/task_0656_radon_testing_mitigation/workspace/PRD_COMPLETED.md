# Radon Testing & Mitigation API — Product Requirements Document

## 1. Introduction

Radon is a colorless, odorless radioactive gas that accumulates in dwellings and is regulated against a fixed action level of 4.0 picocuries per liter of air (pCi/L). This API coordinates the full operational arc that begins when a homeowner or real-estate party asks whether a property has a radon problem and ends, ideally, with a cleared property carrying a warranty and a recurring retest cadence. Along the way it must accommodate two physically different measurement techniques — a short-term 48-hour integrated test and a continuous electronic monitor — as well as the engineering and financial workflow of designing, quoting, permitting, and installing a sub-slab depressurization system, and the after-care obligations of post-mitigation retesting, guarantees, and warranty administration.

The platform exists because these activities are currently fragmented across inspectors, mitigation contractors, permitting authorities, and homeowners, with no shared source of truth for where a property stands. Of particular concern is the **real-estate transaction** path: when a property is mid-sale, the test-mitigate-clear cycle must be compressed against a hard closing deadline, and the system must surface rush pricing and tightened scheduling without sacrificing the regulatory and safety gates that protect every party. The remainder of this document specifies the global contracts that every endpoint honors (Section 2), the domain workflows and their scattered business rules (Section 3), the endpoint catalogue (Section 4), and the canonical error codes (Section 5).

All timekeeping in this system is governed by a **logical clock** rather than wall-clock time. At server start the clock reads exactly `2026-04-01T00:00:00Z`, and until an administrator explicitly advances it the clock remains at that value and never falls back to real time. Every "now" referenced below — placement instants, permit issuance, warranty start, retest due dates — is read from this logical clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes six roles, spelled exactly as follows: `PlatformAdmin`, `Inspector`, `MitigationDesigner`, `CrewLead`, `ComplianceOfficer`, and `ClientContact`. Their identities relate to persisted entities in three different ways. In every case `X-User-ID` is recorded but **not** compared against any resource's foreign key: authorization stops at the role check of this section, and no endpoint performs a per-resource ownership comparison, so any caller bearing a permitted role may act on any resource regardless of which inspector, crew, or property the resource references. The relationships below therefore describe what `X-User-ID` denotes for each role, not an enforced ownership gate.

- When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`; the server does not compare it to a resource's `inspector_id`, so any `Inspector` (for example) may retrieve, record, or void any test.
- When `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the acting `MitigationCrew`; the server does not compare it to a resource's `crew_id`.
- When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Property` (the homeowner or real-estate party is identified through the property they own); the server does not compare it to a resource's `property_id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. `PlatformAdmin` is an operator superuser permitted to register inspectors and crews, set the clock, and override voids, cancellations, and revocations.
- When `X-User-Role` is `MitigationDesigner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from real wall-clock time at the moment the response is built (it is the only timestamp in the system not governed by the logical clock).
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these ranges is rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order, ties broken by creation order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. The list endpoints accept optional exact-match filter query parameters, applied conjunctively, and silently ignore any unrecognized parameter: radon tests filter on `property_id`, `inspector_id`, `mitigation_job_id`, `purpose`, and `status`; mitigation jobs on `property_id`, `triggering_test_id`, `crew_id`, and `status`; payment records on `mitigation_job_id` and `kind`; permits on `mitigation_job_id` and `status`; warranties on `mitigation_job_id`, `property_id`, and `coverage_status`; retest schedules on `warranty_id`, `property_id`, and `status`. Properties accept no filter parameters.

### 2.4. Common Resource Properties and Identity

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field, also ISO 8601 UTC with three fractional digits, is refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it underpins the optimistic-concurrency mechanism described in §2.7.

Two resource types are deliberately leaner. A `PaymentRecord` is an append-only ledger entry: it carries only `id` and `created_at`, and has no `updated_at` and no `version` because it is never modified after it is written. The internal `ClockState` resource likewise carries only `id` and `created_at`; it has neither `updated_at` nor `version`.

Note that several datetime fields in this domain are recorded against the **logical clock**, not the wall clock: a test's `placement_start_utc`, a permit's `issued_at_utc`, a warranty's `started_at_utc`, a schedule's `next_due_utc` and `last_fired_utc`, and a payment's `recorded_at_utc` are all stamped from the logical clock value in force at the moment of the operation.

### 2.5. Nested Reference Resolution and Validation Ordering

Although all collections are addressed as flat top-level paths, many operations reference resources by identifier — either in the URL path or as foreign keys in the request body. Validation proceeds in a fixed priority order, and the first failing check determines the response. First, the user-context headers are checked (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the caller's role is checked against the operation's permitted roles (`ERR_FORBIDDEN_FOR_ROLE`). Third, every resource named in the URL path must exist, validated left to right — the property first, then the radon test or mitigation job, then any permit, warranty, or retest schedule — with a missing path resource yielding `ERR_NOT_FOUND`. Fourth, foreign-key fields supplied in the request body — `inspector_id`, `crew_id`, `triggering_test_id`, and `mitigation_job_id` — must reference existing resources, otherwise `ERR_REFERENCED_RESOURCE_NOT_FOUND`. Fifth, the target resource must be in a state from which the requested transition is legal, otherwise `ERR_INVALID_STATE`. Sixth, where optimistic concurrency applies, the supplied version must match (see §2.7). Only after these structural gates do the domain-specific business rules of §3 apply, and request-body well-formedness — yielding `ERR_INVALID_REQUEST` when a required field is absent, an enum value is invalid, a numeric is negative where it must not be, or the retrieval payload is inconsistent with the test kind — is otherwise the final, lowest-priority gate. One refinement governs where in the order body well-formedness actually falls: those body fields that the operation must read in order to perform a lookup (the foreign keys listed above, and on a creating request the other scalar fields parsed alongside them) are validated for presence, type, and enum membership up front, before the fourth (foreign-key existence) and fifth (state) gates — so a creating request that is malformed in such a field is rejected with `ERR_INVALID_REQUEST` even though a referenced resource is also missing or in a wrong state. For pure transition operations addressed only by URL path (such as retrieving a test), no body field feeds a lookup, so body well-formedness genuinely runs last, after the state and business-rule gates.

### 2.6. Compound Posture, Cascades, and Derived-Field Reconciliation

Several fields are not written directly by clients but are **derived** and reconciled by the server whenever an underlying event occurs. A `Property` exposes a computed `posture` (one of `OPEN`, `TESTING`, `MITIGATION_REQUIRED`, `MITIGATING`, `CLEARED`), a computed `latest_result_pci_l` (the `result_pci_l` of the most recent `RESULT_READY` test on that property, taken by `created_at` descending and, when two such tests share the same `created_at` instant — common under the logical clock — by later creation order, or null when none exists), and a computed `open_test_count` (the number of radon tests on the property not in a terminal state). When a child radon test or mitigation job changes state, the server recomputes these derived fields on the parent property in the same operation, refreshing the property's `updated_at` and incrementing its `version`. Likewise, a `MitigationJob` exposes a computed `retest_passed` flag that becomes true once a post-mitigation test on that job yields a no-action result. Whenever the server performs one of these automatic reconciliations or cascades, the affected resource is treated as mutated: its `updated_at` advances and its `version` increments, exactly as a client-initiated change would.

These cascades can run several levels deep. Recording a clearing retest result, for instance, flips the job to its cleared state, which itself issues a warranty, which in turn arms a retest schedule and flips the property posture — a single inbound request fanning out across four entities. Section 3 specifies each cascade in the narrative of the workflow that triggers it.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded against acting on stale parent state, and each requires a version-pin field in its request body.

Scheduling a mitigation job is guarded on its parent property. The schedule request must carry `expected_property_version`, the property `version` the caller last observed. A competing job for the same property that reaches its scheduled state flips the property posture to `MITIGATING` and advances `Property.version`; a scheduler still holding the pre-mutation version is therefore working from a stale view, and the schedule is rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP 412). The caller must re-read the property and retry with the current version. A new scheduled job legitimately changes the property's mitigation posture, so the second scheduler is required to re-read before scheduling.

Cancelling a warranty is guarded on the warranty itself. The cancel request must carry `expected_warranty_version`, the warranty `version` the caller last observed. Opening a claim, refreshing the warranty to expired, or any other parallel-dimension write advances `Warranty.version`; a cancel still carrying the pre-mutation version is rejected with `ERR_STALE_WARRANTY_VERSION` (HTTP 412), because the prorated refund would otherwise be computed against a coverage or claim state the caller never saw. No other endpoint takes a version-pin field, and endpoints that omit one are processed without an optimistic-concurrency check.

### 2.8. Monetary Precision and Rounding

All monetary amounts in this system are integers denominated in cents, and the fields that carry them end in `_cents`. Where a calculation multiplies by a percentage rate, the result of that percentage step is rounded **half up** to a whole cent. Where amounts are summed from ledger entries, the arithmetic is exact integer addition. Radon concentrations, by contrast, are expressed in pCi/L and carried to **one decimal place**, rounded half up; the 4.0 pCi/L action level and the warranty guarantee ceiling are compared against these one-decimal values.

### 2.9. Inspector, Crew, and Identifier Uniqueness

Inspectors and crews are operational actors registered by the platform. An `Inspector` carries a `full_name`, an `nrpp_license_id` (the National Radon Proficiency Program license identifier), and a `status` that is `ACTIVE` on registration and may become `SUSPENDED`. An `nrpp_license_id` must be unique among `ACTIVE` inspectors; a registration that would duplicate the license of another active inspector is rejected with `ERR_DUPLICATE_IDENTIFIER`. A `MitigationCrew` carries a `crew_name`, a `max_jobs_per_day` (the daily install capacity, defaulting to 2 and never below 1), and a `status` that is `ACTIVE` on registration and may become `SUSPENDED`. Only `ACTIVE` inspectors may be assigned to placements and retrievals, and only `ACTIVE` crews may be scheduled; suspension is the lever that takes an actor out of rotation without deleting their history.

## 3. Business Logic & Workflows

### 3.1. Properties and the Onset of Testing

The journey begins with a `Property`, created by a `ClientContact` or a `PlatformAdmin`. Creation captures the dwelling's `address_line`, its `foundation_type` (one of `SLAB`, `BASEMENT`, or `CRAWLSPACE`, which later drives both the quote base price and the suction-point geometry), and its conditioned `floor_area_sqft`, which must be a positive integer. The caller may also flag `is_real_estate_transaction`, which defaults to false; when it is true the property is mid-sale, and a `closing_deadline_utc` (an ISO 8601 UTC instant) must be supplied to anchor the rush handling described later. A freshly created property has its posture at `OPEN`, an `open_test_count` of 0, and a null `latest_result_pci_l`.

A property's `posture` is a **compound** state machine driven entirely by its children, never set directly by a client. While no tests exist it sits at `OPEN`. When the first radon test is placed and `open_test_count` rises from zero to a positive number, posture advances from `OPEN` to `TESTING`. Should an initial test ultimately read clean — its result reaching `RESULT_READY` with a no-action outcome and below the action level (`latest_result_pci_l` strictly less than 4.0) while no mitigation job is in a non-terminal state — the property moves directly from `TESTING` to `CLEARED`. If instead an initial test reaches `RESULT_READY` with an action-recommended outcome (`latest_result_pci_l` at least 4.0) and there is no job yet eligible for clearing, the posture advances from `TESTING` to `MITIGATION_REQUIRED`, which is the gate that makes the property eligible for a mitigation job. Once any mitigation job for the property reaches its scheduled, installed, retest-pending, or rework state, posture moves from `MITIGATION_REQUIRED` to `MITIGATING`. Finally, when a mitigation job for the property reaches its cleared state with `retest_passed` true, posture moves from `MITIGATING` to `CLEARED`.

### 3.2. Placing and Retrieving Radon Tests

A radon test device is placed by an `Inspector` against a property. The placement payload identifies the `property_id`, names the `inspector_id` of the inspector who will place and later retrieve the device, and selects a `test_kind` — either `SHORT_TERM_48HR` (a passive kit returning one integrated number) or `CONTINUOUS_MONITOR` (an electronic logger returning a stream of hourly readings). The caller may set a `purpose`, which defaults to `INITIAL` but may be `POST_MITIGATION` or `RECURRING`; a `mitigation_job_id` is required when and only when the purpose is `POST_MITIGATION`, and must be null otherwise. The placement may also override the `placement_window_hours` — the minimum exposure window in hours before retrieval is permitted, which defaults to 48 and may never be set below 48 — and the `warmup_hours_dropped`, the number of leading hourly readings to discard as device warm-up, which defaults to 4 and may not be negative. On a successful placement the device starts in `PLACED`, its `placement_start_utc` is stamped from the logical clock, the property's `open_test_count` is incremented, and a property still at `OPEN` advances to `TESTING`.

The assigned inspector must be `ACTIVE` at placement; a placement naming a `SUSPENDED` inspector is rejected with `ERR_INSPECTOR_SUSPENDED`. A `POST_MITIGATION` placement is additionally a retest against a specific job: the referenced job must be in its `INSTALLED` state, and that placement drives the job from `INSTALLED` to `RETEST_PENDING`. A `POST_MITIGATION` test placed against a job that is not `INSTALLED`, or a `mitigation_job_id` supplied on a test whose purpose is not `POST_MITIGATION`, is rejected with `ERR_RETEST_NOT_ALLOWED`.

Retrieval is the inspector's act of collecting the device and supplying its data, moving the test from `PLACED` to `RETRIEVED`. Retrieval is barred until the exposure window has fully elapsed: the difference between the current logical-clock instant and `placement_start_utc` must be at least `placement_window_hours` hours, otherwise the request is rejected with `ERR_PLACEMENT_WINDOW_NOT_ELAPSED`. The inspector assigned to the test — its `inspector_id` — must still be `ACTIVE`, or the retrieval is rejected with `ERR_INSPECTOR_SUSPENDED`; this is checked against the test's assigned inspector rather than the acting caller, and a test carrying no `inspector_id` (such as a `RECURRING` test armed by a fired schedule) satisfies the check vacuously. The data supplied depends on the test kind, and the two payload shapes are mutually exclusive. A `CONTINUOUS_MONITOR` retrieval supplies `hourly_readings`, an array of hourly pCi/L numbers, and the array must contain strictly more entries than `warmup_hours_dropped` (otherwise `ERR_INSUFFICIENT_READINGS`); for this kind `lab_integrated_pci_l` is null. A `SHORT_TERM_48HR` retrieval supplies a single `lab_integrated_pci_l` value that must be present and at least 0 (otherwise `ERR_INVALID_REQUEST`); for this kind `hourly_readings` is null. The retrieval payload is recorded on the test, and the property's `open_test_count` is unchanged because the test is still open until its result is recorded.

A placed test that will never be retrieved may be voided by any `Inspector` or by a `PlatformAdmin` (per §2.1 the acting inspector need not be the one who placed it, and no ownership is checked), moving it from `PLACED` to `VOIDED`. Voiding decrements the property's `open_test_count` and recompute the property posture. Both `RESULT_READY` and `VOIDED` are terminal; a test cannot leave either state, and re-testing means placing a fresh device.

### 3.3. Computing the Result and Classifying Against the Action Level

Recording the result moves a test from `RETRIEVED` to `RESULT_READY` and is where the two measurement variants diverge. The `result_pci_l` is computed according to the test's `test_kind`. For a `SHORT_TERM_48HR` test, the result is simply the supplied `lab_integrated_pci_l`, rounded half up to one decimal place. For a `CONTINUOUS_MONITOR` test, the result is the mean of the **valid** hourly readings: the first `warmup_hours_dropped` entries of `hourly_readings` are discarded as warm-up, the remaining readings are summed and divided by the count of those remaining readings, and that quotient is rounded half up to one decimal place. It is essential that only the post-warm-up readings enter the average — averaging every reading including the leading warm-up hours is incorrect, because elevated warm-up spikes can push the all-hours mean from below 4.0 (where the valid-hours mean sits) to at or above 4.0, flipping the outcome.

Immediately after the result is computed, the test's `action_outcome` is classified against the action level constant of 4.0 pCi/L. The boundary is inclusive: when `result_pci_l` is at least 4.0 the outcome is `ACTION_RECOMMENDED`, and when it is strictly below 4.0 (for example 3.9) the outcome is `NO_ACTION`. Recording the result decrements the property's `open_test_count` and recomputes both `latest_result_pci_l` and the compound posture.

The consequences then cascade by purpose. For an `INITIAL` test that lands on `ACTION_RECOMMENDED`, the property posture is set to `MITIGATION_REQUIRED`, which is the write that makes the property eligible for a mitigation job. For a `POST_MITIGATION` test linked to a job, a `NO_ACTION` result sets the job's `retest_passed` to true and drives the job's `RETEST_PENDING → CLEARED` transition (described in §3.5), while an `ACTION_RECOMMENDED` result drives the job's `RETEST_PENDING → REWORK` transition. A `RECURRING` test that reads high does not by itself rework a job, but it does raise the property's `latest_result_pci_l`, which is what later qualifies a warranty claim.

### 3.4. Designing and Quoting a Mitigation Job

Once a property requires mitigation, a `MitigationDesigner` opens a `MitigationJob` in the `DESIGN` state. The design payload names the `property_id` and the `triggering_test_id` — the action-recommended test that justifies the job — and may specify the engineering and commercial parameters: the `system_design` (defaulting to `SUB_SLAB_DEPRESSURIZATION`, with `SUB_MEMBRANE_DEPRESSURIZATION` as the alternative design class), the `num_suction_points` (defaulting to 1 and never below 1), and `has_sump_pump` (defaulting to false, indicating whether a sump-pit seal is required). The designer also pre-declares the after-care terms that will later be snapshotted into the warranty and schedule: `warranty_term_days` (defaulting to 1825, i.e. five years, and at least 1), `warranty_guarantee_ceiling_pci_l` (the guaranteed maximum radon level, defaulting to 2.0 and strictly positive), `warranty_refund_method` (`STRAIGHT_LINE` or `STEP_TIER`, defaulting to `STRAIGHT_LINE`), and `retest_interval_days` (the recurring cadence, defaulting to 730, i.e. two years, and at least 1). The designer may also flag `is_rush` (defaulting to false) for a real-estate-driven job.

Quoting moves the job from `DESIGN` to `QUOTED` and freezes its pricing. Quoting is only permitted when the property posture is `MITIGATION_REQUIRED` and the `triggering_test_id` resolves to a test whose `action_outcome` is `ACTION_RECOMMENDED`; otherwise the quote is rejected with `ERR_NO_ACTIONABLE_RESULT`. The evaluation order is fixed, because the rush surcharge keys off the resolved subtotal and must not be computed until the subtotal is final. First, a base price is selected by the property's `foundation_type`: a slab foundation bases at 150000 cents, a basement at 185000 cents, and a crawlspace at 240000 cents. Second, an extra-points charge is added: the number of suction points beyond the first — that is, `num_suction_points` minus 1, but never less than zero — multiplied by 45000 cents per additional point. Third, a sump-seal fee of 32000 cents is added when `has_sump_pump` is true, and zero otherwise. Fourth, a tiered area surcharge is added on the property's `floor_area_sqft`, with inclusive upper boundaries: an area of 1500 square feet or less adds nothing; an area greater than 1500 but at most 3000 square feet adds 50000 cents; an area greater than 3000 square feet adds 120000 cents. The sum of base, extra points, sump fee, and area surcharge is the `quote_subtotal_cents`.

The `rush_surcharge_cents` is then 15 percent of the subtotal, rounded half up, when `is_rush` is true, and zero when it is false. The `quote_total_cents` is the subtotal plus the rush surcharge. Finally the `deposit_required_cents` is 30 percent of the `quote_total_cents`, rounded half up. All four computed amounts are persisted on the job at quote time.

### 3.5. Scheduling, Permitting, Installing, and Clearing

Before a job can be scheduled, the deposit must be on hand. Payments flow through an append-only ledger of `PaymentRecord` entries, each naming a `mitigation_job_id`, a `kind` (`DEPOSIT`, `BALANCE`, or `REFUND`), and a signed `amount_cents` denominated in cents — positive for a deposit or balance, negative for a refund — and each stamped with a `recorded_at_utc` from the logical clock. From this ledger the job's `deposit_paid_cents` is recomputed as the sum of the amounts of its `DEPOSIT` entries, and its `balance_paid_cents` as the sum of the amounts of its `BALANCE` entries. These gating totals count only the positive deposit and balance rows, so they reflect money actually still held. Separately, the net recorded cash on a job is the sum of all entries across every kind, including the negative refunds; this net figure is what a compensating refund must drive back to its conserved value. The ledger is processed in order of `recorded_at_utc` ascending, with ties broken by `created_at` ascending.

Scheduling moves a job from `QUOTED` to `SCHEDULED` and is performed by a `MitigationDesigner`. The schedule payload supplies the `crew_id`, the install window `install_start_utc` and `install_end_utc` (both ISO 8601 UTC), and the `expected_property_version` discussed in §2.7. Several conditions must hold, and they are evaluated in the following fixed order, the first failure determining the response. First the deposit must be satisfied: `deposit_paid_cents` must be at least `deposit_required_cents`, else `ERR_DEPOSIT_NOT_SATISFIED`. Second the named crew must be `ACTIVE`, else `ERR_CREW_SUSPENDED`. Third the window must be well formed, with `install_start_utc` strictly earlier than `install_end_utc`, else `ERR_INVALID_WINDOW`. Fourth, when the job is a rush job, the window must not run past the property's closing deadline — `install_end_utc` must be at or before `closing_deadline_utc` — else `ERR_RUSH_DEADLINE_MISSED`; a rush job whose property carries no `closing_deadline_utc` at all also fails this check with `ERR_RUSH_DEADLINE_MISSED`. Fifth, the crew's calendar must accommodate the work: the crew's number of install windows on the install day — the UTC calendar date of `install_start_utc`, counting only the crew's other `SCHEDULED` jobs whose own window start falls on that same date and including the window being scheduled — must not exceed its `max_jobs_per_day`, and the new window must not overlap an existing `SCHEDULED` job's window for that same crew, where adjacency on a half-open interval (one window ending exactly as another begins) is allowed; either violation is rejected with `ERR_CREW_WINDOW_CONFLICT`. On success the job records its `crew_id`, `install_start_utc`, and `install_end_utc`, the property posture is set to `MITIGATING`, and the property's `version` increments by one.

Installation requires a permit. A `ComplianceOfficer` issues a `Permit` for a job by supplying the `mitigation_job_id`, a `jurisdiction_code` (the issuing authority's code), and a `permit_number` assigned by that authority. The permit begins in `ISSUED`, stamps its `issued_at_utc` from the logical clock, and the job's `permit_id` is set to point at it. A `permit_number` must be unique among `ISSUED` permits within a jurisdiction; a duplicate is rejected with `ERR_DUPLICATE_IDENTIFIER`. A `ComplianceOfficer` or `PlatformAdmin` may revoke an `ISSUED` permit, moving it to `REVOKED`, but only while the parent job is neither `INSTALLED` nor `CLEARED`; revoking after the install is complete is rejected with `ERR_PERMIT_LOCKED`. Revocation clears the job's `permit_id`, so the job once again lacks a permit and its install is blocked. When a job ultimately reaches its cleared state, its issued permit is automatically closed, moving from `ISSUED` to `CLOSED`.

Completing the install, performed by a `CrewLead`, moves the job from `SCHEDULED` to `INSTALLED`. Two gates apply: the job must have a `permit_id` pointing at a permit whose status is `ISSUED`, else `ERR_PERMIT_REQUIRED`; and the logical clock must have reached the window start, with the current instant at or after `install_start_utc`, else `ERR_INSTALL_NOT_DUE`. An installed job then awaits its post-mitigation retest, which is placed as described in §3.2 and §3.3 and drives the job into `RETEST_PENDING`.

Clearing is a system transition, not a client call: when the linked `POST_MITIGATION` test reaches `RESULT_READY` with a `NO_ACTION` outcome, the job moves from `RETEST_PENDING` to `CLEARED` — provided the final balance has been paid. Specifically, `balance_paid_cents` must be at least `quote_total_cents` minus `deposit_required_cents`, else the clearing is rejected with `ERR_BALANCE_NOT_SATISFIED`. This balance gate is checked atomically as part of recording the clearing retest result: when it fails the entire record-result request is rejected, so the post-mitigation test stays in `RETRIEVED` and is not advanced to `RESULT_READY`. Clearing sets `retest_passed` to true and, on the **first** time a job is cleared (the job has no warranty yet), fans out a depth-three cascade: it issues a `Warranty` (with `coverage_status` `ACTIVE` and `claim_status` `NONE`) that snapshots `covered_system_price_cents` from the job's `quote_total_cents`, `term_days` from `warranty_term_days`, `guarantee_ceiling_pci_l` from `warranty_guarantee_ceiling_pci_l`, and `refund_method` from `warranty_refund_method`, and stamps `started_at_utc` from the logical clock; warranty issuance in turn arms a `RetestSchedule` with `interval_days` taken from `retest_interval_days` and `next_due_utc` set to the warranty's `started_at_utc` plus `interval_days` days; and finally the property posture is set to `CLEARED`. If instead the linked post-mitigation test reads `ACTION_RECOMMENDED`, the job moves from `RETEST_PENDING` to `REWORK` and the property posture remains `MITIGATING`.

Rework re-enters the install loop. A `MitigationDesigner` schedules a job out of `REWORK` back to `SCHEDULED` using the same schedule action; the `expected_property_version` pin of §2.7 is still required and still checked, but the deposit and rush-deadline gates are skipped on the rework path, leaving the crew must be `ACTIVE` (else `ERR_CREW_SUSPENDED`), the window must be well formed (else `ERR_INVALID_WINDOW`), and the crew window must not overlap an existing `SCHEDULED` job for that crew (else `ERR_CREW_WINDOW_CONFLICT`). No additional deposit is required, because rework is free under the guarantee. This `RETEST_PENDING → REWORK → SCHEDULED` path is the re-mitigation loop, repeated until a retest finally clears.

A job still in `DESIGN` or `QUOTED` may be cancelled by a `MitigationDesigner` or `PlatformAdmin`, moving it to `CANCELLED`. Cancellation recomputes the property posture. If the job had already collected a deposit — `deposit_paid_cents` greater than zero — the cancellation appends a `REFUND` ledger entry for the negative of `deposit_paid_cents` and resets `deposit_paid_cents` to zero, so the total recorded cash on the job returns to zero. The job statuses form the sequence `DESIGN → QUOTED → SCHEDULED → INSTALLED → RETEST_PENDING → CLEARED`, with the `RETEST_PENDING → REWORK → SCHEDULED` rework cycle and the `CANCELLED` terminal exit from `DESIGN` or `QUOTED`; `CLEARED` and `CANCELLED` are the terminal states.

### 3.6. Warranty Coverage, Claims, and Refunds

A `Warranty` evolves along two independent dimensions on the same record: a `coverage_status` (one of `ACTIVE`, `EXPIRED`, `CANCELLED`) and a `claim_status` (one of `NONE`, `CLAIM_OPEN`, `CLAIM_RESOLVED`). The two advance separately. A warranty also retains pointers back to its origin via `mitigation_job_id` and `property_id`, and a `refund_paid_cents` that is computed only when the warranty is cancelled.

On the coverage dimension, a warranty begins `ACTIVE`. Refreshing it re-evaluates coverage against the clock: a `ComplianceOfficer` (or the system) refreshes a warranty whose `coverage_status` is `ACTIVE` (refreshing a warranty that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`), and when the current logical-clock instant is at or after `started_at_utc` plus `term_days` days, coverage moves from `ACTIVE` to `EXPIRED`, which cascades the associated retest schedule to `ENDED`. When the term has not yet elapsed the refresh is a successful no-op that returns `200 OK` with the warranty left `ACTIVE` and unmutated (its `version` does not advance). Alternatively a `ClientContact` or `PlatformAdmin` may cancel an `ACTIVE` warranty, moving coverage from `ACTIVE` to `CANCELLED` — but only when `claim_status` is not `CLAIM_OPEN`, since a warranty cannot be cancelled mid-claim, else `ERR_CLAIM_IN_PROGRESS`. Cancellation also requires the `expected_warranty_version` pin of §2.7. On cancel the prorated `refund_paid_cents` is computed over `covered_system_price_cents` (see below), a `REFUND` ledger entry for the negative of the refund is appended on the mitigation job, the retest schedule is cascaded to `ENDED`, and the warranty `version` increments.

The cancellation refund is computed by the warranty's `refund_method`. First the elapsed time is the number of whole days from `started_at_utc` to the current logical-clock instant, taking the floor of the day count; the remaining days are `term_days` minus the elapsed days, but never less than zero. Under `STRAIGHT_LINE`, the refund is `covered_system_price_cents` multiplied by remaining days divided by `term_days`, rounded half up to a whole cent. Under `STEP_TIER`, the elapsed fraction is the elapsed days divided by `term_days`, and a flat percentage is chosen by band: a fraction below 0.25 refunds 90 percent, a fraction below 0.50 refunds 60 percent, a fraction below 0.75 refunds 30 percent, and a fraction of 0.75 or greater refunds 0 percent; the refund is `covered_system_price_cents` multiplied by that chosen percentage, rounded half up. For the same elapsed days the two methods generally yield different cents.

On the claim dimension, which evolves independently of coverage, a warranty begins with `claim_status` `NONE`. A `ClientContact` opens a guarantee claim, moving `claim_status` from `NONE` to `CLAIM_OPEN`, provided the coverage is still live (`coverage_status` `ACTIVE`), the claim status is currently `NONE`, and a qualifying high retest exists — the property's `latest_result_pci_l` must be at least the warranty's `guarantee_ceiling_pci_l`, else `ERR_NO_QUALIFYING_RETEST`. Opening a claim leaves `coverage_status` untouched but sets the parent mitigation job to `REWORK`, because the guarantee triggers a free re-mitigation, and it advances the warranty `version`. When that rework job returns to `CLEARED` with a passing retest, the system moves `claim_status` from `CLAIM_OPEN` to `CLAIM_RESOLVED`, again leaving `coverage_status` untouched; because the job already carries a warranty, this second clearing reuses that existing warranty and does **not** issue a new one (nor a new retest schedule).

### 3.7. Recurring Retest Cadence

When a warranty is issued, the system arms a `RetestSchedule` that carries the `warranty_id`, the `property_id`, an `interval_days` (the days between recurring retests, defaulting to 730), a computed `next_due_utc`, a `last_fired_utc` (initially null), a `fired_count` (initially 0), and a `status` that begins `ARMED`. The schedule's first `next_due_utc` is the warranty's `started_at_utc` plus `interval_days` days.

Firing a due retest can be requested by a `ComplianceOfficer` (or triggered by the system once the clock advances past the due date). Firing is a self-loop that keeps the schedule `ARMED`. It requires the schedule to be `ARMED`, the current logical-clock instant to be at or after `next_due_utc` (else `ERR_RETEST_NOT_DUE`), and the parent warranty's `coverage_status` to be `ACTIVE` (else `ERR_WARRANTY_NOT_ACTIVE`). A fire creates a fresh `RECURRING` radon test on the property in the `PLACED` state — a `SHORT_TERM_48HR` test with `inspector_id` null, no `mitigation_job_id`, the default `placement_window_hours` of 48 and default `warmup_hours_dropped` of 4, its `placement_start_utc` stamped from the logical clock — increments `fired_count`, sets `last_fired_utc` to the current logical-clock instant, and advances `next_due_utc` by `interval_days` days. Crucially the cadence advances from the prior scheduled due date, not from the actual fire timestamp, so a late fire does not drift the schedule.

A `ClientContact` or `ComplianceOfficer` may pause an `ARMED` schedule, moving it to `PAUSED`, and resume a `PAUSED` schedule back to `ARMED`. When the parent warranty leaves `ACTIVE` — whether through expiry or cancellation — the schedule is cascaded to `ENDED`, which is terminal.

### 3.8. The Logical Clock and Test-Driving

Because every temporal gate in this system reads the logical clock, a `PlatformAdmin` can drive scenarios deterministically. An admin-only test-driving capability sets the logical clock to a supplied instant via the `to_iso8601` field, updating the `ClockState` resource's `current_utc`. Advancing the clock past a warranty term makes a refresh eligible to expire that warranty, advancing it past a retest schedule's due date makes a fire eligible, and advancing it past an install window's start makes an install eligible — exactly as those workflows above describe.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify or transition an existing resource, including list and get reads, return `200 OK`. Each endpoint is restricted to the roles listed below; a permitted role still passes through the validation ordering of §2.5 before its effect takes hold.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/inspectors` | Register an inspector | PlatformAdmin |
| POST | `/inspectors/{inspectorId}/suspend` | Suspend an inspector | PlatformAdmin |
| POST | `/crews` | Register a mitigation crew | PlatformAdmin |
| POST | `/crews/{crewId}/suspend` | Suspend a crew | PlatformAdmin |
| POST | `/properties` | Create a property record | PlatformAdmin, ClientContact |
| GET | `/properties/{propertyId}` | Get a property with computed posture and latest result | PlatformAdmin, ClientContact, Inspector, MitigationDesigner, CrewLead, ComplianceOfficer |
| GET | `/properties` | List properties (paginated) | PlatformAdmin, ClientContact |
| POST | `/radon-tests` | Place a radon test device (INITIAL, POST_MITIGATION, or RECURRING) | Inspector |
| GET | `/radon-tests/{testId}` | Get a radon test | PlatformAdmin, Inspector, MitigationDesigner, ClientContact, ComplianceOfficer |
| GET | `/radon-tests` | List radon tests (filtered) | PlatformAdmin, Inspector, MitigationDesigner, ClientContact, ComplianceOfficer |
| POST | `/radon-tests/{testId}/retrieve` | Retrieve the device and supply readings or lab value | Inspector |
| POST | `/radon-tests/{testId}/record-result` | Compute and record the averaged result and action outcome | Inspector |
| POST | `/radon-tests/{testId}/void` | Void a placed test that will not be retrieved | Inspector, PlatformAdmin |
| POST | `/mitigation-jobs` | Open a mitigation job design tied to an action-recommended test | MitigationDesigner |
| GET | `/mitigation-jobs/{jobId}` | Get a mitigation job with computed quote fields | PlatformAdmin, MitigationDesigner, CrewLead, ComplianceOfficer, ClientContact |
| GET | `/mitigation-jobs` | List mitigation jobs (filtered) | PlatformAdmin, MitigationDesigner, CrewLead, ComplianceOfficer, ClientContact |
| POST | `/mitigation-jobs/{jobId}/quote` | Compute and freeze the quote and deposit requirement | MitigationDesigner |
| POST | `/mitigation-jobs/{jobId}/schedule` | Assign a crew and install window; OCC-guarded on the parent property | MitigationDesigner |
| POST | `/mitigation-jobs/{jobId}/complete-install` | Mark the sub-slab depressurization install complete | CrewLead |
| POST | `/mitigation-jobs/{jobId}/cancel` | Cancel a job still in DESIGN or QUOTED; refunds any deposit | MitigationDesigner, PlatformAdmin |
| POST | `/payment-records` | Append a DEPOSIT, BALANCE, or REFUND ledger entry to a job | ClientContact, MitigationDesigner, PlatformAdmin |
| GET | `/payment-records/{recordId}` | Get a single ledger entry | PlatformAdmin, MitigationDesigner, ClientContact, ComplianceOfficer |
| GET | `/payment-records` | List ledger entries (filtered) | PlatformAdmin, MitigationDesigner, ClientContact, ComplianceOfficer |
| POST | `/permits` | Issue a sub-slab depressurization permit for a job | ComplianceOfficer |
| GET | `/permits/{permitId}` | Get a permit | PlatformAdmin, ComplianceOfficer, MitigationDesigner, CrewLead |
| GET | `/permits` | List permits (filtered) | PlatformAdmin, ComplianceOfficer, MitigationDesigner, CrewLead |
| POST | `/permits/{permitId}/revoke` | Revoke an issued permit (only before install complete) | ComplianceOfficer, PlatformAdmin |
| GET | `/warranties/{warrantyId}` | Get a warranty (coverage and claim status) | PlatformAdmin, ComplianceOfficer, ClientContact, MitigationDesigner |
| GET | `/warranties` | List warranties (filtered) | PlatformAdmin, ComplianceOfficer, ClientContact, MitigationDesigner |
| POST | `/warranties/{warrantyId}/refresh` | Re-evaluate coverage against the clock | ComplianceOfficer, PlatformAdmin |
| POST | `/warranties/{warrantyId}/cancel` | Cancel coverage and pay a prorated refund; OCC-guarded on the warranty | ClientContact, PlatformAdmin |
| POST | `/warranties/{warrantyId}/open-claim` | Open a guarantee claim; drives a free rework | ClientContact |
| GET | `/retest-schedules/{scheduleId}` | Get a retest schedule | PlatformAdmin, ComplianceOfficer, ClientContact |
| GET | `/retest-schedules` | List retest schedules (filtered) | PlatformAdmin, ComplianceOfficer, ClientContact |
| POST | `/retest-schedules/{scheduleId}/fire-due` | Fire a due recurring retest | ComplianceOfficer, PlatformAdmin |
| POST | `/retest-schedules/{scheduleId}/pause` | Pause a recurring schedule | ClientContact, ComplianceOfficer |
| POST | `/retest-schedules/{scheduleId}/resume` | Resume a paused schedule | ClientContact, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PROPERTY_VERSION` | 412 Precondition Failed |
| `ERR_STALE_WARRANTY_VERSION` | 412 Precondition Failed |
| `ERR_PLACEMENT_WINDOW_NOT_ELAPSED` | 409 Conflict |
| `ERR_INSUFFICIENT_READINGS` | 409 Conflict |
| `ERR_INSPECTOR_SUSPENDED` | 409 Conflict |
| `ERR_CREW_SUSPENDED` | 409 Conflict |
| `ERR_PERMIT_REQUIRED` | 409 Conflict |
| `ERR_PERMIT_LOCKED` | 409 Conflict |
| `ERR_RETEST_NOT_ALLOWED` | 409 Conflict |
| `ERR_NO_ACTIONABLE_RESULT` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 409 Conflict |
| `ERR_RUSH_DEADLINE_MISSED` | 409 Conflict |
| `ERR_CREW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_IDENTIFIER` | 409 Conflict |
| `ERR_RETEST_NOT_DUE` | 409 Conflict |
| `ERR_WARRANTY_NOT_ACTIVE` | 409 Conflict |
| `ERR_DEPOSIT_NOT_SATISFIED` | 409 Conflict |
| `ERR_BALANCE_NOT_SATISFIED` | 409 Conflict |
| `ERR_CLAIM_IN_PROGRESS` | 409 Conflict |
| `ERR_NO_QUALIFYING_RETEST` | 409 Conflict |
| `ERR_INSTALL_NOT_DUE` | 409 Conflict |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
