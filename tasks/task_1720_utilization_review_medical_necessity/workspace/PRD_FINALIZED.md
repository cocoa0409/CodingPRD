# Utilization Review Medical Necessity API — Product Requirements Document

## 1. Introduction

Hospital utilization review sits at the intersection of clinical judgment, regulatory compliance, and payer relations. Every admission carries an implied question — does this patient require an inpatient level of care, or would observation status suffice? — and the answer determines not only reimbursement but also the hospital's exposure under Medicare's two-midnight rule. Utilization review teams must document medical necessity against published criteria, submit authorization requests to payers within contractual windows, track continued-stay approvals on a fixed cadence, and manage the adversarial cascade that begins whenever a payer renders an adverse determination. Each denial carries its own peer-to-peer scheduling window, its own appeal deadline, and its own downstream effect on certified bed days, and the whole process must withstand audit.

This document specifies a REST API supporting that workflow end to end. It covers payer policy configuration, physician registration, the opening of a utilization case at admission, the two-stage admission medical-necessity review, payer authorization submission and decision handling, concurrent continued-stay reviews on a payer-defined cadence, peer-to-peer conference scheduling on an adverse determination, the condition-code-44 inpatient-to-observation status change, avoidable-day tracking with tiered escalation, and the denial-to-appeal pipeline. A logical clock under administrative control drives every deadline, window, and cadence comparison, so that time-dependent behavior is fully testable. The system maintains a parallel two-axis lifecycle on each case — one axis for review progress and one for payer authorization — plus an append-only audit trail recording every material mutation with the acting role and identifier.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` identifying the acting user and `X-User-Role` naming their operational capacity. The system recognizes exactly seven roles: `URNurse`, `AttendingPhysician`, `PhysicianAdvisor`, `PayerReviewer`, `CaseManager`, `AppealsCoordinator`, and `URDirector`. A request missing either header, or carrying a role string other than these seven, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `AttendingPhysician`, `X-User-ID` is the `id` of the acting `Physician`; ownership checks on any resource that references a `Physician` — in practice, the attending-of-record anchor on a utilization case — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PhysicianAdvisor`, `X-User-ID` is likewise the `id` of the acting `Physician`, and segregation-of-duties checks compare it against the case's attending anchor. For the remaining five roles — `URNurse`, `PayerReviewer`, `CaseManager`, `AppealsCoordinator`, and `URDirector` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on each `AuditEvent` as `actor_id` (alongside `actor_role`, which captures the `X-User-Role` header of the mutating call) but does not compare it to any entity's `id`.

Four endpoints additionally enforce an attending-ownership check: scheduling, rescheduling, or cancelling a peer-to-peer conference, and recording attending concurrence on a condition-code-44 request. On those endpoints, the caller's `X-User-ID` must equal the parent case's `attending_physician_id`; a mismatch is rejected with `ERR_NOT_CASE_ATTENDING`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Case Identity, Dual Lifecycle Axes, and Hierarchical Consistency

The central organizing entity of the system is the **UtilizationCase**, one per patient stay, keyed by `patient_mrn` and anchored to a payer (`payer_id`) and an attending physician of record (`attending_physician_id`). The case carries two independent lifecycle axes rather than a single status field. The first axis, `review_status`, tracks the hospital-side review lifecycle: `INTAKE` at case opening, advancing to `ADMISSION_REVIEWED` when an admission review is submitted, then to `MONITORING` when any authorization request of the case is approved, and finally to `CLOSED` at discharge. The second axis, `auth_status`, tracks the payer-side authorization lifecycle independently: `AUTH_PENDING` at case opening, `AUTH_IN_PROGRESS` once the first authorization request is created, `AUTHORIZED` when an authorization request is approved, and `DENIED` on any payer denial; a `DENIED` case returns to `AUTHORIZED` when a peer-to-peer conference or appeal overturns the denial. Because the two axes are independent, a case may be simultaneously in `MONITORING` and `DENIED`, or in `ADMISSION_REVIEWED` and `AUTH_PENDING`, and readers must always evaluate both fields. Only `review_status` has a terminal value (`CLOSED`); the `auth_status` axis has no terminal state of its own.

Hierarchy is strict. Admission reviews, authorization requests, condition-code-44 requests, avoidable-day records, escalation cases, denial cases, and audit events are all children of a utilization case; concurrent reviews and peer-to-peer conferences are children of an authorization request; appeals are children of a denial case. Once a case is `CLOSED`, any attempt to create or mutate a child under it — a new review, a new authorization request, a concurrent review, an avoidable-day record — is rejected with `ERR_CASE_CLOSED`. The sole exception is the condition-code-44 flow: initiating one on a discharged case surfaces the domain-specific `ERR_CC44_POST_DISCHARGE` rather than the generic closure error, because CMS regulation frames CC44 as a pre-discharge process.

Every mutation of a case or one of its descendants that touches case-level computed state refreshes the case's `updated_at` and increments its `version` by exactly 1, so clients can always detect that a cascade has run by watching `version`.

### 2.5. Validation Order

Every request is evaluated against a fixed validation pipeline, and the order matters because it determines which error surfaces when several problems coexist. The pipeline runs:

1. **Authentication** — both headers present and the role recognized; failure yields `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the role is listed for the endpoint; failure yields `ERR_FORBIDDEN_ROLE`.
3. **Request-shape integrity** — required fields present, enum members valid, numeric ranges honored (including the conference-duration floor of at least 15 minutes with the end strictly after the start), and no client-supplied computed or system-managed fields; failure yields `ERR_VALIDATION_FAILED`.
4. **Path existence** — every path identifier resolves, checked left to right; failure yields `ERR_NOT_FOUND`.
5. **Attending ownership** — on the four attending-owned actions; failure yields `ERR_NOT_CASE_ATTENDING`.
6. **Case-open gate** — child mutations under a `CLOSED` case yield `ERR_CASE_CLOSED`.
7. **State-machine legality** — the target resource's current state permits the requested transition (repeated discharge, double decisions, writes against terminal states all fail here) with `ERR_INVALID_STATE`.
8. **Optimistic concurrency** — the two create-with-supersede writers check `expected_case_version`; a stale value yields `ERR_STALE_VERSION`.
9. **Domain-specific state and safety gates** — the post-discharge CC44 guard (`ERR_CC44_POST_DISCHARGE`), peer-to-peer eligibility (`ERR_P2P_NOT_ELIGIBLE`), denial finality (`ERR_DENIAL_NOT_FINAL`), clinical documentation completeness (`ERR_CLINICAL_DOC_INCOMPLETE`), segregation of duties (`ERR_SOD_ROLE_CONFLICT`), the two-midnight attestation gate (`ERR_TWO_MIDNIGHT_DOC_REQUIRED`), and the temporal gates (`ERR_P2P_WINDOW_EXPIRED`, `ERR_REVIEW_OVERDUE`, `ERR_APPEAL_DEADLINE_PASSED`).
10. **Business constraints** — at most one open CC44 per case (`ERR_CC44_ALREADY_OPEN`), avoidable-day uniqueness per calendar day and barrier (`ERR_AVOIDABLE_DAY_DUPLICATE`), advisor calendar clearance (`ERR_SCHEDULING_OVERLAP`), certified-interval overlap (`ERR_CERTIFIED_DAY_OVERLAP`), the reschedule cap (`ERR_P2P_RESCHEDULE_LIMIT`), and one appeal per denial (`ERR_APPEAL_ALREADY_FILED`).
11. **Referential and fiscal gates** — CC44 payer eligibility (`ERR_CC44_PAYER_INELIGIBLE`), CC44 clinical basis (`ERR_CC44_CRITERIA_STILL_MET`), physician-advisor reference (`ERR_NOT_PHYSICIAN_ADVISOR`), and the bed-day budget (`ERR_BED_DAY_BUDGET_EXCEEDED`).

A request that would trip two gates is reported against the earliest gate in this ordering — so, for instance, an unauthenticated caller with a malformed body receives `ERR_UNAUTHENTICATED`, and a stale-version create on a case that is also closed receives `ERR_CASE_CLOSED`.

### 2.6. Common Resource Properties

All primary resources — payers, physicians, utilization cases, admission reviews, authorization requests, concurrent reviews, peer-to-peer conferences, condition-code-44 requests, avoidable-day records, escalation cases, denial cases, and appeal cases — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any modification.
- `version` (integer): a system-managed counter that increments by 1 on every mutation of the resource.

The **AuditEvent** resource is the single exception: it is append-only and immutable, so it carries `id` and `created_at` only; both `updated_at` and `version` are absent. Each audit event records the `case_id` it belongs to, the machine-named `event_type` of the mutation (for example `CASE_OPENED`, `REVIEW_SUBMITTED`, `AUTH_APPROVED`, `AUTH_DENIED`, `P2P_COMPLETED`, `CC44_APPROVED`, `CC44_RESCINDED`, `APPEAL_DECIDED`), the `actor_role` and `actor_id` taken from the request headers, and a one-line `payload_summary` of the mutation and its primary side effects.

### 2.7. Monetary Values, Rounding, and Integer Arithmetic

The system deliberately minimizes floating-point exposure. Money is carried in whole cents (integer fields such as `charge_cents` and `rebill_estimate_cents`), and contracted rates are carried in milli-units (`rate_milli` — the contracted rate multiplied by 1000, so a 38.5% rate is transmitted as 385). The one monetary calculation in the system, the condition-code-44 rebill estimate, rounds **half-up to whole cents per service line first, then sums the rounded lines** to an exact integer total. The reverse order — summing raw millicent values across lines and rounding once at the end — is a documented trap variant and is not acceptable: whenever per-line fractions accumulate past a cent boundary, the two orders yield different totals, and only per-line-round-then-sum is correct. The medical-necessity score, the midnight counts, and all tier thresholds are pure integer arithmetic with no rounding at all.

### 2.8. The Two-Midnight Benchmark

Medicare's two-midnight rule is modeled as a computed benchmark on each utilization case with two variants. A **midnight count** between two timestamps is the number of calendar-date boundaries crossed — the whole-calendar-day difference between the two dates; the times of day are irrelevant. The benchmark is `MET` when the applicable count is at least 2 and `NOT_MET` otherwise; exactly two midnights is `MET`.

At case creation, the **PROVISIONAL** variant runs: `expected_midnight_count` is computed from `admit_at` and the physician-documented `expected_discharge_at`, `two_midnight_benchmark_met` is evaluated against that count, and `benchmark_basis` is set to `PROVISIONAL`. At discharge, the **FINAL** variant runs: `actual_midnight_count` is computed from `admit_at` and the actual `discharge_at`, the benchmark is re-evaluated against that count, and `benchmark_basis` flips to `FINAL`. A stay documented as two midnights can therefore end `NOT_MET` in the final accounting when actual discharge occurs earlier than expected, and the two variants genuinely differ whenever the expected and actual discharge dates differ. `actual_midnight_count` remains null until discharge.

### 2.9. Certified Day Intervals and the Bed-Day Budget

Payer approvals grant certified bed days as half-open intervals on a 1-based hospital-day index: an approval carries `certified_day_start` (inclusive) and a day count, and the granted interval ends at `certified_day_end` (exclusive), so the interval is the range from `certified_day_start` up to but not including `certified_day_end`. Intervals on the same case may be adjacent — a new interval starting exactly at an existing interval's end is allowed — but may never intersect; an overlapping grant is rejected with `ERR_CERTIFIED_DAY_OVERLAP`.

Each case aggregates three computed counters over its certified intervals: `certified_day_count` (the sum of all interval lengths, both levels of care), `certified_inpatient_day_count` (the sum over intervals tagged `INPATIENT`), and `certified_observation_day_count` (the sum over intervals tagged `OBSERVATION`). Every approval, partial approval, overturn restoration, CC44 approval, and CC44 rescission recomputes these counters. The payer's `bed_day_budget_per_case` caps cumulative certified days: any decision — initial authorization approval or concurrent-review approval or partial — that would push `certified_day_count` past the budget is rejected with `ERR_BED_DAY_BUDGET_EXCEEDED`, and the same cap applies to `requested_day_count` at authorization-request creation.

### 2.10. Optimistic Concurrency Control

Two write operations are create-with-supersede writers whose correctness depends on the caller having observed the current state of the parent case: creating an authorization request against a case, and initiating a condition-code-44 request against a case. Each of these requests must carry `expected_case_version`, a non-optional input field holding the caller's last observed `version` of the target utilization case. If the value does not equal the case's current `version` — because another writer has advanced the case since the caller last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from superseding requests or rewriting case-level status on a view it has not observed. Endpoints not named here do not take a version field.

### 2.11. The Logical Clock

All deadline, window, and cadence comparisons in the system — peer-to-peer windows, appeal deadlines, concurrent-review due timestamps, lazy expirations — read a server-side logical clock, never wall-clock time. The clock's startup default, before any administrative set call, is exactly `2026-08-01T00:00:00Z`. A `URDirector` may advance the clock to a supplied `to_iso8601` instant via an admin-only test-driving capability; monotonicity is not enforced, so tests may rewind. Timestamps recorded by state transitions (`submitted_at`, `decided_at`, `filed_at`, `effective_at`, `denied_at`) all read this same logical clock. Temporal comparisons against deadlines and windows are inclusive: submission at exactly the deadline instant is on time. Computed deadline and window timestamps — `review_due_at` (§3.4), `window_deadline_at` (§3.5), and `appeal_deadline_at` (§3.3, §3.4) — are rendered as ISO 8601 UTC strings in the same three-fractional-digit format used for `created_at` and `updated_at` (§2.6); a deadline that lands on a whole second therefore reads, for example, `2026-08-03T00:00:00.000Z`.

### 2.12. Nested Resource Retrieval

The API enforces strict left-to-right validation on nested paths. When an endpoint path contains multiple resource identifiers, the system validates each identifier's existence in path order, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that fails to resolve — before any later segment, state check, or business rule is evaluated.

## 3. Business Logic & Workflows

### 3.1. Configuring Payers and Physicians

Before any case can be opened, a `URDirector` registers the environment's policy and people. A **Payer** is created with a display `name`, a `plan_class` of `MEDICARE`, `MANAGED_MEDICARE`, `MEDICAID`, or `COMMERCIAL`, and a policy bundle: `requires_inpatient_auth` (defaulting to true), `concurrent_review_cadence_hours` (at least 1), `p2p_window_hours` (at least 1), `appeal_deadline_days` (at least 1), `bed_day_budget_per_case` (at least 1), and `avoidable_attribution_method`, which selects one of two attribution variants — `FIRST_CAUSE` (chronological) or `DOMINANT_CAUSE` (weighted) — for every case under that payer. The `plan_class` field matters well beyond display: `MEDICARE` and `MANAGED_MEDICARE` together form the Medicare family, which governs both condition-code-44 eligibility and the comorbidity weighting in the medical-necessity score. Payers may be listed — optionally filtered by `plan_class` — and fetched individually by any authenticated role.

A **Physician** is registered with a `full_name`, a `specialty`, and an `is_advisor` flag (defaulting to false) that marks the physician as eligible to act as a physician advisor: peer-to-peer medical-director counterpart, CC44 committee reviewer, and advisor second-level reviewer. Physicians may be listed — optionally filtered by `is_advisor` — and fetched individually. Two additional read surfaces support the physician's calendar and committee workload: one lists every peer-to-peer conference in which the physician serves as advisor or attendee, ordered by `scheduled_start_at` ascending and then `created_at` ascending; the other lists the condition-code-44 requests whose `committee_reviewer_id` is that physician.

### 3.2. Opening a Case and Reviewing the Admission

A `URNurse` opens a utilization case at admission by supplying the `patient_mrn`, the `payer_id`, the `attending_physician_id`, the `admit_at` timestamp, the physician-documented `expected_discharge_at`, and the physician's admission order as `requested_admission_status` — either `INPATIENT` or `OBSERVATION`. The server immediately initializes `current_admission_status` from `requested_admission_status`, sets `review_status` to `INTAKE` and `auth_status` to `AUTH_PENDING`, computes the PROVISIONAL two-midnight benchmark per §2.8, and appends a `CASE_OPENED` audit event. Cases may be listed with optional filters on `payer_id`, `attending_physician_id`, `review_status`, and `auth_status`.

With the case open, the nurse drafts an **AdmissionReview**, choosing the `criteria_set` edition (`INTERQUAL` or `MCG`) and recording three point inputs: `severity_of_illness_points` (0 to 20), `intensity_of_service_points` (0 to 20), and `comorbidity_count` (0 to 10), plus the physician's `two_midnight_attestation` that the stay is expected to span at least two midnights. The review is born in `DRAFT`, with `necessity_score`, `determination`, and `recommended_status` all unset; its `determination` reads `PENDING` while drafting. Reviews of a case list in `created_at` ascending order.

Submission is the pivotal act. When the nurse submits the review, the server computes the **medical necessity score** from the three point inputs and the case's payer plan class: severity points are capped at 12 and multiplied by 5; intensity points are capped at 12 and multiplied by 5; the comorbidity count is capped at 3 and multiplied by 4 when the payer is in the Medicare family (`MEDICARE` or `MANAGED_MEDICARE`) or by 2 otherwise; the three weighted components are summed and the total is capped at 100. All of this is integer arithmetic with no rounding. The `determination` is then `CRITERIA_MET` when the score reaches at least 60, and `CRITERIA_NOT_MET` below that threshold. The `recommended_status` is `INPATIENT` only when the determination is `CRITERIA_MET` **and** the case's current `two_midnight_benchmark_met` reads `MET`; in every other combination it is `OBSERVATION`. A documentation gate guards the combination of a favorable score and a missing attestation: when the computed recommendation would be `INPATIENT` but `two_midnight_attestation` is false, the submit is rejected with `ERR_TWO_MIDNIGHT_DOC_REQUIRED`. A successful submit stamps `submitted_at` from the logical clock, moves the review to `SUBMITTED`, advances the parent case's `review_status` from `INTAKE` to `ADMISSION_REVIEWED` — a no-op when the case is already in `MONITORING`, since a re-review during monitoring is free-standing and causes no axis transition — increments the case's `version`, and appends `REVIEW_SUBMITTED`.

A review whose determination came back `CRITERIA_NOT_MET` may receive a second-level **advisor review** by a `PhysicianAdvisor`, who supplies an `advisor_decision` and an optional `advisor_note`. Segregation of duties applies: the reviewing advisor's `X-User-ID` must differ from the case's `attending_physician_id`, on pain of `ERR_SOD_ROLE_CONFLICT`. On `REVERSE`, the determination is rewritten to `CRITERIA_MET` and the `recommended_status` is recomputed under the same rule as at submit; on `UPHOLD`, the determination stands. Either way the review reaches its terminal `ADVISOR_REVIEWED` state and an `ADVISOR_REVIEW_COMPLETED` event is appended. Advisor review is defined only for `SUBMITTED` reviews whose determination is `CRITERIA_NOT_MET`; any other combination fails state-machine legality.

### 3.3. Authorization Requests: Submission, Payer Decision, and Resubmission

Once a case exists, a `URNurse` submits a payer **AuthorizationRequest** — carrying the case reference as its `case_id` — with the `level_of_care` being authorized (`INPATIENT` or `OBSERVATION`), the `requested_day_count` (at least 1), and a `clinical_summary` narrative forming the clinical submission packet. This is one of the two OCC-guarded create-with-supersede writers described in §2.10: the payload must carry `expected_case_version` equal to the case's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`. Two content gates also apply at creation: the `requested_day_count` may not exceed the payer's `bed_day_budget_per_case` (`ERR_BED_DAY_BUDGET_EXCEEDED`), and the `clinical_summary` must be at least 50 characters long — the completeness gate, `ERR_CLINICAL_DOC_INCOMPLETE` on failure.

Creation is a superseding event: every existing authorization request of the case in `SUBMITTED` or `PENDED` status transitions to `SUPERSEDED` (each appending `AUTH_SUPERSEDED`), while the new request is born in `SUBMITTED` with `submission_round` set to 1. The case's `auth_status` axis moves from `AUTH_PENDING` to `AUTH_IN_PROGRESS` on the first request, the case `version` increments, and `AUTH_SUBMITTED` is appended. Requests list under their case in `created_at` ascending order, and each request exposes a read surface for its linked denial cases.

A `PayerReviewer` then renders the payer decision — a `decision` value of `APPROVE`, `PEND`, or `DENY` — against a `SUBMITTED` request. Approval requires `certified_day_start` and `certified_day_count` in the payload; the granted interval is stored on the request, tagged with the request's `level_of_care`, and must pass both the overlap rule and the budget rule of §2.9. Approval sets `decided_at`, flips the case's `auth_status` to `AUTHORIZED`, advances `review_status` from `ADMISSION_REVIEWED` to `MONITORING` when applicable — approval while the case is still in `INTAKE` (no admission review submitted) leaves the review axis untouched — recomputes the case's certified counters, increments the case `version`, and appends `AUTH_APPROVED`. A pend sets `decided_at`, moves the request to `PENDED`, and appends `AUTH_PENDED`; the payload may carry a `pend_reason`. The `SUBMITTED` → `PENDED` → `SUBMITTED` cycle may repeat without bound: a `URNurse` resubmits a `PENDED` request with a refreshed `clinical_summary` (the 50-character completeness gate applies again, and failing it yields `ERR_CLINICAL_DOC_INCOMPLETE`), which replaces the stored summary, increments `submission_round` by 1, and appends `AUTH_RESUBMITTED`. A nurse may also withdraw any request still in `SUBMITTED` or `PENDED`, moving it to terminal `WITHDRAWN` with an `AUTH_WITHDRAWN` event.

Denial is the consequential branch. The payer reviewer supplies a `denial_reason_code` — one of `CRITERIA_NOT_MET`, `DOC_INSUFFICIENT`, or `LEVEL_OF_CARE` — and the request moves to `DENIED` with `decided_at` set. The system immediately creates a **DenialCase** under the same case: `denial_type` is `INITIAL_AUTH`, `denied_day_count` equals the request's `requested_day_count`, `denied_at` stamps the decision, and the denial is born `OPEN`. The case's `auth_status` flips to `DENIED` (from either `AUTH_IN_PROGRESS` or `AUTHORIZED`), the case `version` increments, and `AUTH_DENIED` is appended. The denial's `appeal_deadline_at` is computed as `denied_at` plus the payer's `appeal_deadline_days` and is immutable thereafter — peer-to-peer scheduling does not extend it.

### 3.4. Concurrent Reviews: Continued Stay on a Cadence

An approved authorization is not the end of payer oversight; continued stay must be re-justified on the payer's cadence. A `URNurse` submits a **ConcurrentReview** against an `APPROVED` authorization request — the request's `id` becomes the review's `authorization_request_id` — with a `clinical_update` narrative and a `requested_additional_day_count` (at least 1). The server assigns `sequence_index` — the 1-based ordinal among reviews of the same authorization — stamps `submitted_at`, and computes `review_due_at` by the cadence rule: for the first review of the authorization the anchor is the parent authorization's `APPROVED`-transition `decided_at`, and for each subsequent review the anchor is the previous review's `decided_at`; the deadline is the anchor plus the payer's `concurrent_review_cadence_hours`. A new review may only be created once the previous review of the same authorization is decided, and only one `SUBMITTED` review may be outstanding on an authorization at a time — violating either condition is `ERR_INVALID_STATE`. Submission after the deadline fails: when logical now is past `review_due_at` the create is rejected with `ERR_REVIEW_OVERDUE`, with equality allowed — submission at exactly `review_due_at` is on time. A compliant create appends `CONCURRENT_REVIEW_SUBMITTED`.

The `PayerReviewer` decides each review with a `decision` of `APPROVE`, `PARTIAL`, or `DENY`. A full approval sets `approved_day_count` equal to `requested_additional_day_count`; a partial approval requires an `approved_day_count` strictly between 1 and the requested count; both grant an interval beginning at the payload's `certified_day_start`, tagged with the parent authorization's level of care, subject to the same overlap and budget rules as an initial approval. Either decision sets `decided_at`, recomputes the case's certified counters, increments the case `version`, and appends `CONCURRENT_REVIEW_APPROVED` or `CONCURRENT_REVIEW_PARTIAL`. A denial — again carrying one of the three `denial_reason_code` values — moves the review to `DENIED` with `approved_day_count` set to 0, creates a `DenialCase` with `denial_type` `CONCURRENT` and `denied_day_count` equal to `requested_additional_day_count`, flips the case's `auth_status` to `DENIED`, increments the case `version`, and appends `CONCURRENT_REVIEW_DENIED`. All three terminal states (`APPROVED`, `PARTIALLY_APPROVED`, `DENIED`) end the review's lifecycle. Reviews list under their authorization in `created_at` ascending order.

### 3.5. Peer-to-Peer Conferences on an Adverse Determination

When a payer denies an authorization, the attending physician of record may request a peer-to-peer conference with the payer's physician advisor. Scheduling is an `AttendingPhysician` action on the denied request — the attending-ownership check of §2.1 applies, so the caller must be the case's attending. The parent authorization must be in `DENIED` status; otherwise `ERR_P2P_NOT_ELIGIBLE`. The payload names the `advisor_physician_id`, which must resolve to a `Physician` whose `is_advisor` flag is true (`ERR_NOT_PHYSICIAN_ADVISOR` otherwise), plus the `scheduled_start_at` and `scheduled_end_at`. The end must be strictly after the start with a duration of at least 15 minutes — a shape failure caught as `ERR_VALIDATION_FAILED`.

The conference's `window_deadline_at` is computed as the denied request's `decided_at` (of the `DENIED` transition) plus the payer's `p2p_window_hours`. At scheduling, both the logical now and the `scheduled_start_at` must fall at or before that deadline; a violation is `ERR_P2P_WINDOW_EXPIRED`. The advisor's calendar is protected by a buffered-overlap rule: the new conference must leave at least 15 minutes of clearance on both sides from every `SCHEDULED` conference of the same advisor — exactly 15 minutes is allowed — and a conflict is rejected with `ERR_SCHEDULING_OVERLAP`. A successfully scheduled conference is born `SCHEDULED` with `reschedule_count` 0 and `outcome` `NONE`; the linked denial case moves from `OPEN` to `P2P_SCHEDULED` with its `appeal_deadline_at` unchanged; and `P2P_SCHEDULED` is appended to the audit trail. The server stamps the conference's `attending_physician_id` from the caller's `X-User-ID`.

The attending may reschedule — a self-loop that keeps the conference `SCHEDULED` — subject to three guards: `reschedule_count` must be below the hard cap of 2 (at the cap, `ERR_P2P_RESCHEDULE_LIMIT`); the window check re-applies against the new start (`ERR_P2P_WINDOW_EXPIRED`); and the advisor-calendar clearance check re-applies (`ERR_SCHEDULING_OVERLAP`). Each reschedule increments `reschedule_count` by 1 and appends `P2P_RESCHEDULED`. The attending may instead cancel outright: the conference moves to terminal `CANCELLED`, the linked denial returns from `P2P_SCHEDULED` to `OPEN` with its appeal deadline conserved — the schedule-then-cancel pair is a compensating invariant that never extends the clock — and `P2P_CANCELLED` is appended.

Completion belongs to the `PhysicianAdvisor`, who records an `outcome` of `UPHELD` or `OVERTURNED`. The completion must occur while the conference is still `SCHEDULED` and while logical now is at or before `scheduled_end_at`; a completion attempted after the scheduled end fails with `ERR_P2P_WINDOW_EXPIRED`. An `OVERTURNED` outcome fires the full restoration cascade: the linked authorization request moves from `DENIED` back to `APPROVED`, with a certified interval appended at the case frontier — starting at the highest existing certified end on the case (day 1 when the case has no certified intervals yet, since certified days live on a 1-based index per §2.9) and extending for the `certified_day_count` supplied in the completion payload; the linked denial case resolves to `RESOLVED_OVERTURNED` (from either `OPEN` or `P2P_SCHEDULED`), appending `DENIAL_OVERTURNED` for the denial's own resolution; the case's `auth_status` returns to `AUTHORIZED`; the certified counters are recomputed; the case `version` increments; and `P2P_COMPLETED` is appended. An `UPHELD` outcome merely returns the denial from `P2P_SCHEDULED` to `OPEN`, leaving the authorization denied and the appeal path available.

A conference left in `SCHEDULED` past its `window_deadline_at` does not sit forever: `EXPIRED` is materialized lazily whenever the conference is read or mutated while logical now exceeds the deadline. Expiration behaves like cancellation for the denial — the linked case returns to `OPEN` with the deadline unchanged — and appends `P2P_EXPIRED`. Conferences list under their authorization in `created_at` ascending order, and the lazy expiration applies to listed rows as well as to single-resource reads.

### 3.6. Condition Code 44: Inpatient-to-Observation Status Change

When a hospital determines, after admission, that an inpatient order should have been observation, the condition-code-44 process changes the patient's status before discharge with physician concurrence and committee approval. A `URNurse` initiates a **ConditionCode44Request** on a case with a `rationale` and a `service_lines` array — each line carrying a `description`, a `charge_cents` amount, and a `rate_milli` contracted rate. This is the second OCC-guarded writer of §2.10: `expected_case_version` must match the case's current `version`, else `ERR_STALE_VERSION`.

Three eligibility gates precede creation. The case must not be discharged — initiating a CC44 on a `CLOSED` case is rejected with `ERR_CC44_POST_DISCHARGE`. The case's payer must be in the Medicare family — a `plan_class` of `MEDICARE` or `MANAGED_MEDICARE`; any other plan class yields `ERR_CC44_PAYER_INELIGIBLE`. And the clinical basis must be present: the case's latest submitted-or-advisor-reviewed admission review — the last row of that set in `created_at` ascending order, with `created_at` ties (possible under the logical clock) resolving in favor of the most recently created review — must carry a determination of `CRITERIA_NOT_MET`; when the latest review still reads `CRITERIA_MET`, creation fails with `ERR_CC44_CRITERIA_STILL_MET`. Additionally, at most one CC44 request per case may be open at a time — one already in `CONCURRENCE_PENDING` or `COMMITTEE_PENDING` blocks a new initiation with `ERR_CC44_ALREADY_OPEN`.

At creation, the server computes `rebill_estimate_cents` from the service lines per the pinned rounding rule of §2.7 — each line's charge is multiplied by its milli-rate, divided by 1000, and rounded half-up to whole cents, and the rounded line values are then summed exactly. The request is born in `CONCURRENCE_PENDING` with `attending_concurrence` `PENDING`; the case `version` increments and `CC44_INITIATED` is appended. Requests of a case list in `created_at` ascending order.

Concurrence belongs to the attending of record — again an attending-ownership action. The attending supplies a `decision` of `CONCUR` or `DECLINE`, addressed to the target request by its `cc44Id` path identifier. On `CONCUR` (optionally with a `concurrence_note`), `attending_concurrence` is set to `CONCURRED`, the request advances to `COMMITTEE_PENDING`, and `CC44_CONCURRED` is appended. On `DECLINE`, `attending_concurrence` becomes `DECLINED`, the request closes to terminal `DECLINED_CLOSED`, the case is left entirely unchanged — this branch carries no flip side effects — and `CC44_DECLINED` is appended.

The committee step belongs to a `PhysicianAdvisor`, acting as the UR committee reviewer, with segregation of duties enforced: the reviewer's `X-User-ID` must differ from the case's `attending_physician_id` (`ERR_SOD_ROLE_CONFLICT`). The advisor's `decision` is `APPROVE` or `REJECT`. On `APPROVE` (with an optional `committee_note`), the `committee_reviewer_id` is set from the caller's `X-User-ID`, `effective_at` stamps the logical clock, and the full status-change cascade fires: the case's `current_admission_status` flips from `INPATIENT` to `OBSERVATION`; every authorization request of the case whose `level_of_care` is `INPATIENT` and whose status is `SUBMITTED` or `PENDED` moves to `WITHDRAWN`; every already-approved certified interval tagged `INPATIENT` is re-tagged `OBSERVATION` with its range unchanged, so the total `certified_day_count` is conserved and the inpatient/observation split moves one-for-one; the two per-level counters are recomputed; the case `version` increments; and `CC44_APPROVED` is appended. Approval requires `attending_concurrence` to be `CONCURRED` — which the state machine guarantees, since committee review is only reachable from `COMMITTEE_PENDING`. On `REJECT`, the `committee_reviewer_id` is set, the case is unchanged, the request reaches terminal `REJECTED`, and `CC44_REJECTED` is appended.

An approved CC44 can be undone before discharge by a `URDirector` supplying a `rescind_reason`: the request moves from `APPROVED` to terminal `RESCINDED`, the case's `current_admission_status` is restored from `OBSERVATION` to `INPATIENT`, the re-tagged certified intervals are restored to `INPATIENT` — total certified days again conserved across the approve-and-rescind pair — the per-level counters are recomputed, the case `version` increments, and `CC44_RESCINDED` is appended. Rescission on a discharged case is impossible because the case-closure gate rejects it; while the case is open, rescission from any state other than `APPROVED` fails state-machine legality.

### 3.7. Avoidable Days, Attribution, and Escalation

Delays that occupy a bed without clinical justification are tracked as **AvoidableDay** records. A `URNurse` or `CaseManager` records a barrier by `day_date` (a `YYYY-MM-DD` hospital calendar day), a `barrier_code` of `PLACEMENT_DELAY`, `PAYER_AUTH_DELAY`, `TRANSPORT_DELAY`, `FAMILY_DECISION`, or `PHYSICIAN_DELAY`, and a `barrier_weight` from 1 to 5 expressing acuity. The triple of case, `day_date`, and `barrier_code` is unique — a duplicate is rejected with `ERR_AVOIDABLE_DAY_DUPLICATE`. New records are born `OPEN`.

Attribution is computed per calendar day. For the set of a case's records sharing a `day_date` and not yet `OVERTURNED`, exactly one record owns the day: under the payer's `FIRST_CAUSE` method the owner is the earliest-created record, with ties broken by `barrier_code` in lexicographic order; under `DOMINANT_CAUSE` the owner is the record with the highest `barrier_weight`, with ties broken by earliest creation and then `barrier_code` lexicographic. The owner is flagged `is_attributed` true and all others in the group false; identical inputs yield different owners across the two variants whenever the earliest barrier is not the heaviest. Attribution re-runs whenever a record is created, mitigated, or overturned, and deterministic tie-breaks never consult a record's `id`.

The case surfaces two computed fields from its open records. `open_avoidable_day_count` counts the distinct `day_date` values having at least one `OPEN` record. `escalation_tier` maps that raw count through three thresholds: at least 6 open days yields tier 3, at least 4 yields tier 2, at least 2 yields tier 1, and fewer than 2 yields tier 0. When a create pushes the raw tier from 0 to at least 1 and no escalation case is currently `OPEN` or `ACKNOWLEDGED` for the case, the system creates an **EscalationCase** in `OPEN` with its `tier` set to the raw tier and `trigger_open_day_count` snapshotting the raw count at that moment; when an active escalation already exists and the raw tier has risen above its stored `tier`, the escalation's tier is upgraded — upgrades only, never automatic downgrades. The create appends `AVOIDABLE_DAY_RECORDED`, recomputes the case counters, and increments the case `version`.

A `CaseManager` mitigates an open record with a `mitigation_note`: the record moves `OPEN` → `MITIGATED`, the case's `open_avoidable_day_count` and `escalation_tier` are recomputed, any active escalation's `effective_tier` is recomputed, the case `version` increments, and `AVOIDABLE_DAY_MITIGATED` is appended. Records list under their case ordered by `day_date` ascending and then `created_at` ascending, with an optional `status` filter.

Escalations are worked by the `CaseManager`: acknowledging moves `OPEN` → `ACKNOWLEDGED` (`ESCALATION_ACKNOWLEDGED`), and resolving — from either `OPEN` or `ACKNOWLEDGED` — sets the `resolution_note` and closes the escalation `RESOLVED` (`ESCALATION_RESOLVED`). A `URDirector` may apply a mitigation credit with `credit_days`, which accumulates into the escalation's `director_credit_days` (starting from 0). The credit rule is deliberately pinned in evaluation order to break a circular-looking dependency: eligibility for a credit is evaluated against the **raw** tier — the tier computed from the raw open-day count before any credits — and only a raw tier of exactly 3 is eligible; once applied, the net count is the raw count minus cumulative `director_credit_days`, floored at zero, and `effective_tier` is the tier of that net count through the same thresholds; eligibility is not re-checked after crediting. Applying a credit appends `ESCALATION_CREDIT_APPLIED` and leaves the stored raw `tier` untouched.

### 3.8. Denials, Appeals, and the Overturn Cascade

Every denial — initial or concurrent — materializes a `DenialCase` as described in §3.3 and §3.4. The denial's `denial_is_final` flag reads true only while the denial is in `DENIED`-backed `OPEN` posture with no linked conference `SCHEDULED`; it is the gate on appeal filing. Denials list under their case in `created_at` ascending order, and both list and single-resource reads perform lazy materialization: a denial still `OPEN` after its `appeal_deadline_at` transitions to terminal `CLOSED_NO_APPEAL` on the first such read, appending `DENIAL_CLOSED_NO_APPEAL`. The materialization is confined to reads — write operations on a denial, appeal filing in particular, do not perform it; the filing path evaluates its preconditions against the still-`OPEN` denial, so a filing attempted against a still-`OPEN` denial after `appeal_deadline_at` surfaces `ERR_APPEAL_DEADLINE_PASSED` rather than a not-`OPEN` finality error.

Once a denial is final, an `AppealsCoordinator` files an **AppealCase** — referencing the denial by its `denial_id` — with an `appeal_level` (1 for internal, 2 for external) and an `argument_summary`. Filing enforces four preconditions: the denial must be `OPEN`; no linked conference may be `SCHEDULED` (filing while a peer-to-peer is still on the calendar is rejected with `ERR_DENIAL_NOT_FINAL`); logical now must be at or before `appeal_deadline_at` (`ERR_APPEAL_DEADLINE_PASSED`, equality allowed); and no prior appeal may exist for the denial — a second filing attempt, whether the denial sits in `APPEAL_FILED` or any resolved state, is rejected with `ERR_APPEAL_ALREADY_FILED`. A successful filing creates the appeal in `FILED` with `filed_at` stamped, moves the denial `OPEN` → `APPEAL_FILED`, and appends `APPEAL_FILED`. Appeals list under their denial in `created_at` ascending order.

The `PayerReviewer` records the appeal decision by posting a `decision` of `UPHELD`, `OVERTURNED`, or `PARTIAL`. Three terminal states exist, with sibling-symmetric structure and different restoration depths:

- **UPHELD**: the appeal moves to `DECIDED_UPHELD` with `decided_at` stamped and `overturned_day_count` set to 0; the denial resolves to `RESOLVED_UPHELD`; `APPEAL_DECIDED` is appended. No authorization restoration occurs.
- **OVERTURNED**: the appeal moves to `DECIDED_OVERTURNED`; `overturned_day_count` is set equal to the denial's `denied_day_count`; the denial resolves to `RESOLVED_OVERTURNED`; the linked authorization request moves `DENIED` → `APPROVED` with a certified interval appended at the case frontier covering the overturned days; every `OPEN` avoidable-day record of the case whose `day_date` falls on or after the denied window's start transitions to `OVERTURNED`, processed in order by `day_date` ascending and then `created_at` ascending (each appending `AVOIDABLE_DAY_OVERTURNED`); the case's `auth_status` returns to `AUTHORIZED`; certified counters are recomputed; the case `version` increments; and `APPEAL_DECIDED` is appended.
- **PARTIAL**: the appeal moves to `DECIDED_PARTIAL`; the payload must carry an `overturned_day_count` strictly between 1 and the denial's `denied_day_count`; the denial resolves to `RESOLVED_PARTIAL`; the linked authorization is restored with a certified interval appended for exactly the granted days; the earliest that-many `OPEN` avoidable days on or after the denied window's start — selected in the same `day_date`-then-`created_at` order — transition to `OVERTURNED`; the case's `auth_status`, counters, and version follow the same cascade; `APPEAL_DECIDED` is appended.

A denial reached through either overturn path — peer-to-peer or appeal — ends in `RESOLVED_OVERTURNED` (or `RESOLVED_PARTIAL` for partial appeals), and the compensation is always the same shape: authorization restored at the case frontier, avoidable days reclassified, the case's authorization axis returned to `AUTHORIZED`.

### 3.9. Discharge and Case Closure

Discharge is a `URNurse` action carrying the actual `discharge_at` timestamp, valid from any non-`CLOSED` review status — `INTAKE`, `ADMISSION_REVIEWED`, or `MONITORING`; repeating discharge against an already-closed case fails state-machine legality with `ERR_INVALID_STATE`. Discharge fires a coordinated closure cascade in a single request: the FINAL two-midnight variant of §2.8 runs (`actual_midnight_count` computed, `two_midnight_benchmark_met` re-evaluated, `benchmark_basis` set to `FINAL`); `review_status` moves to `CLOSED`; every authorization request still in `SUBMITTED` or `PENDED` is withdrawn (`AUTH_WITHDRAWN` for each); every escalation case still `OPEN` or `ACKNOWLEDGED` is resolved with `resolution_note` set to `auto: case discharged`; the case `version` increments; and `CASE_DISCHARGED` is appended. After closure, the child-mutation gate of §2.4 seals the case: nothing new attaches, and the CC44-specific post-discharge guard substitutes its own error for CC44 initiation attempts.

### 3.10. Audit Trail and Observability

Every material mutation described above appends an immutable `AuditEvent` to the case's trail — case opening and discharge, review submission and advisor review, authorization submission, supersession, decision, resubmission, and withdrawal, concurrent-review submission and decisions, peer-to-peer scheduling, rescheduling, completion, cancellation, and expiration, CC44 initiation, concurrence, committee decision, and rescission, avoidable-day recording, mitigation, and overturn, escalation acknowledgment, resolution, and credit, denial closure, and appeal filing and decision. The trail is append-only: audit events are never updated or deleted, and their resource shape (no `updated_at`, no `version`) reflects that. The trail of a case reads in `created_at` ascending order and is available to every authenticated role.

## 4. Endpoint Definitions

Operations that create new resources — a payer, a physician, a utilization case, an admission review, an authorization request, a concurrent review, a peer-to-peer conference, a condition-code-44 request, an avoidable-day record, or an appeal — return a `201 Created` status code. Operations that act on an existing resource without creating a new one — decisions, submissions, resubmissions, withdrawals, scheduling actions, acknowledgments, resolutions, credits, discharge, and the clock setter — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/payers` | Create a payer policy configuration | URDirector |
| GET | `/api/payers` | List payers (paginated; optional `plan_class` filter) | Any authenticated role |
| GET | `/api/payers/{id}` | Get one payer | Any authenticated role |
| POST | `/api/physicians` | Register a physician | URDirector |
| GET | `/api/physicians` | List physicians (paginated; optional `is_advisor` filter) | Any authenticated role |
| GET | `/api/physicians/{id}` | Get one physician | Any authenticated role |
| GET | `/api/physicians/{id}/peer-to-peer-conferences` | List conferences where the physician is advisor or attendee, by `scheduled_start_at` then `created_at` ascending | Any authenticated role |
| GET | `/api/physicians/{id}/condition-code-44-requests` | List CC44 requests reviewed by this physician as committee reviewer | Any authenticated role |
| POST | `/api/utilization-cases` | Open a utilization case at admission | URNurse |
| GET | `/api/utilization-cases` | List utilization cases (paginated; optional `payer_id`, `attending_physician_id`, `review_status`, `auth_status` filters) | Any authenticated role |
| GET | `/api/utilization-cases/{id}` | Get one utilization case with all computed fields current | Any authenticated role |
| POST | `/api/utilization-cases/{id}/discharge` | Discharge the case; computes the FINAL two-midnight benchmark and cascades closure | URNurse |
| POST | `/api/utilization-cases/{id}/admission-reviews` | Create an admission medical-necessity review in DRAFT | URNurse |
| GET | `/api/utilization-cases/{id}/admission-reviews` | List admission reviews of a case, by `created_at` ascending | Any authenticated role |
| GET | `/api/admission-reviews/{id}` | Get one admission review | Any authenticated role |
| POST | `/api/admission-reviews/{id}/submit` | Submit the review; computes necessity score, determination, and recommended status | URNurse |
| POST | `/api/admission-reviews/{id}/advisor-review` | PhysicianAdvisor second-level review of a CRITERIA_NOT_MET determination | PhysicianAdvisor |
| POST | `/api/utilization-cases/{id}/authorization-requests` | Create and submit a payer authorization request (OCC-guarded create-with-supersede) | URNurse |
| GET | `/api/utilization-cases/{id}/authorization-requests` | List authorization requests of a case, by `created_at` ascending | Any authenticated role |
| GET | `/api/authorization-requests/{id}` | Get one authorization request | Any authenticated role |
| POST | `/api/authorization-requests/{id}/payer-decision` | Payer decision: APPROVE (with certified interval), PEND, or DENY (creates DenialCase) | PayerReviewer |
| POST | `/api/authorization-requests/{id}/resubmit` | Resubmit a PENDED request with a refreshed clinical packet | URNurse |
| POST | `/api/authorization-requests/{id}/withdraw` | Withdraw a non-terminal authorization request | URNurse |
| GET | `/api/authorization-requests/{id}/denial-cases` | List denial cases linked to this authorization request | Any authenticated role |
| POST | `/api/authorization-requests/{id}/concurrent-reviews` | Submit a continued-stay concurrent review | URNurse |
| GET | `/api/authorization-requests/{id}/concurrent-reviews` | List concurrent reviews of an authorization request, by `created_at` ascending | Any authenticated role |
| POST | `/api/concurrent-reviews/{id}/payer-decision` | Payer decision on a continued-stay review: APPROVE, PARTIAL, or DENY | PayerReviewer |
| POST | `/api/authorization-requests/{id}/peer-to-peer-conferences` | Schedule a peer-to-peer conference on an adverse determination | AttendingPhysician |
| GET | `/api/authorization-requests/{id}/peer-to-peer-conferences` | List conferences of an authorization request, by `created_at` ascending (lazy EXPIRED applies) | Any authenticated role |
| GET | `/api/peer-to-peer-conferences/{id}` | Get one conference; reading after the window materializes EXPIRED | Any authenticated role |
| POST | `/api/peer-to-peer-conferences/{id}/reschedule` | Reschedule a conference (self-loop, max 2 reschedules, window and calendar checks re-applied) | AttendingPhysician |
| POST | `/api/peer-to-peer-conferences/{id}/complete` | Record the conference outcome; OVERTURNED restores the authorization | PhysicianAdvisor |
| POST | `/api/peer-to-peer-conferences/{id}/cancel` | Cancel a scheduled conference; the denial returns to OPEN with its deadline unchanged | AttendingPhysician |
| POST | `/api/utilization-cases/{id}/condition-code-44-requests` | Initiate a condition-code-44 status change (OCC-guarded; Medicare family only) | URNurse |
| GET | `/api/utilization-cases/{id}/condition-code-44-requests` | List CC44 requests of a case, by `created_at` ascending | Any authenticated role |
| POST | `/api/condition-code-44-requests/{cc44Id}/concurrence` | Attending concurrence step (CONCUR advances to committee; DECLINE closes) | AttendingPhysician |
| POST | `/api/condition-code-44-requests/{cc44Id}/committee-review` | UR committee decision; segregation of duties enforced | PhysicianAdvisor |
| POST | `/api/condition-code-44-requests/{cc44Id}/rescind` | Rescind an approved CC44 (restores INPATIENT status and interval tags) | URDirector |
| POST | `/api/utilization-cases/{id}/avoidable-days` | Record an avoidable-day barrier; triggers attribution and escalation-tier evaluation | URNurse, CaseManager |
| GET | `/api/utilization-cases/{id}/avoidable-days` | List avoidable days of a case, by `day_date` then `created_at` ascending (optional `status` filter) | Any authenticated role |
| POST | `/api/avoidable-days/{id}/mitigate` | Record mitigation of an open avoidable day | CaseManager |
| GET | `/api/utilization-cases/{id}/escalation-cases` | List escalation cases of a case, by `created_at` ascending | Any authenticated role |
| POST | `/api/escalation-cases/{id}/acknowledge` | Acknowledge an open escalation | CaseManager |
| POST | `/api/escalation-cases/{id}/resolve` | Resolve an escalation | CaseManager |
| POST | `/api/escalation-cases/{id}/apply-credit` | URDirector mitigation credit; eligibility evaluated against the raw (pre-credit) tier | URDirector |
| GET | `/api/utilization-cases/{id}/denial-cases` | List denial cases of a case, by `created_at` ascending (lazy CLOSED_NO_APPEAL applies) | Any authenticated role |
| GET | `/api/denial-cases/{id}` | Get one denial case (lazy CLOSED_NO_APPEAL applies) | Any authenticated role |
| POST | `/api/denial-cases/{id}/appeals` | File an appeal on a final denial | AppealsCoordinator |
| GET | `/api/denial-cases/{id}/appeals` | List appeals of a denial case, by `created_at` ascending | Any authenticated role |
| POST | `/api/appeals/{id}/decision` | Record the appeal decision; OVERTURNED/PARTIAL restore certified days and reclassify avoidable days | PayerReviewer |
| GET | `/api/utilization-cases/{id}/audit-events` | Append-only audit trail of the case, by `created_at` ascending | Any authenticated role |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving capability) | URDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_CASE_ATTENDING` | 403 |
| `ERR_VALIDATION_FAILED` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_CASE_CLOSED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CC44_POST_DISCHARGE` | 409 |
| `ERR_P2P_NOT_ELIGIBLE` | 409 |
| `ERR_DENIAL_NOT_FINAL` | 409 |
| `ERR_CLINICAL_DOC_INCOMPLETE` | 422 |
| `ERR_SOD_ROLE_CONFLICT` | 422 |
| `ERR_TWO_MIDNIGHT_DOC_REQUIRED` | 422 |
| `ERR_P2P_WINDOW_EXPIRED` | 422 |
| `ERR_REVIEW_OVERDUE` | 422 |
| `ERR_APPEAL_DEADLINE_PASSED` | 422 |
| `ERR_CC44_ALREADY_OPEN` | 409 |
| `ERR_AVOIDABLE_DAY_DUPLICATE` | 409 |
| `ERR_SCHEDULING_OVERLAP` | 409 |
| `ERR_CERTIFIED_DAY_OVERLAP` | 409 |
| `ERR_P2P_RESCHEDULE_LIMIT` | 409 |
| `ERR_APPEAL_ALREADY_FILED` | 409 |
| `ERR_CC44_PAYER_INELIGIBLE` | 422 |
| `ERR_CC44_CRITERIA_STILL_MET` | 422 |
| `ERR_NOT_PHYSICIAN_ADVISOR` | 422 |
| `ERR_BED_DAY_BUDGET_EXCEEDED` | 422 |
