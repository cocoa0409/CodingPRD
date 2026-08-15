# DOT Compliance & Carrier Safety Rating API — Product Requirements Document

## 1. Introduction

Motor carriers live under continuous regulatory measurement: every roadside inspection, every cited violation, every crash, and every drug or alcohol test feeds a public safety profile that determines whether the carrier keeps its operating authority, what it pays for insurance, and how much enforcement attention it attracts. The safety department's job is to keep that data accurate, to challenge it where it is wrong, and to translate it into corrective action before an auditor does it for them.

This document specifies the DOT Compliance & Carrier Safety Rating API, the system of record for a motor carrier's safety department. It covers safety measurement categories and violation trend monitoring, roadside inspection review with DataQs challenges, driver coaching and corrective action, drug and alcohol program administration, the accident register with preventability review, new-entrant and compliance-review audits with safety rating changes and rating upgrades, document retention, insurance premium impact modeling, and the monthly measurement epoch that recomputes all of it. All temporal behavior is evaluated against a controllable logical clock, so regulatory windows, retention deadlines, and measurement cycles behave deterministically.

## 2. Global Specifications & System-Wide Principles

The rules in this section apply uniformly across the API. All resources are served under the `/safety` URL prefix, with the single exception of the logical-clock endpoint described in §2.5.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request missing either header, carrying an empty value, or naming an unknown role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). A request whose role is not listed among the endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Six roles exist. `SafetyAdmin` is the platform-side administrator: carrier registration, category configuration, audit scheduling and findings, DataQs adjudication acting as the agency proxy, and control of the logical clock. `SafetyDirector` is the carrier safety executive: audit close, rating upgrade adjudication, and preventability determination. `SafetyManager` is the day-to-day safety department operator and also the drug/alcohol designated employer representative: drivers, inspections, violations, coaching, test records, accidents, documents, testing periods, and upgrade filings. `ComplianceAnalyst` is the data analyst: the inspection review workflow, DataQs filing and resubmission, and operation of the measurement cycle. `MedicalReviewOfficer` is the independent MRO who verifies laboratory results, segregated from the recording representative by the segregation-of-duties rule. `InsuranceAnalyst` builds, quotes, rebases, and binds premium impact models. All six roles may call every read endpoint.

All six roles use opaque operator identities. When `X-User-Role` is `SafetyAdmin`, `SafetyDirector`, `SafetyManager`, `ComplianceAnalyst`, `MedicalReviewOfficer`, or `InsuranceAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on the resources the operator creates or decides — for example as `filed_by_user_id` on a challenge, `assigned_by_user_id` on a coaching assignment, `recorded_by_user_id` on a test record, `verified_by_user_id` at verification, `registered_by_user_id` on an accident, and `preventability_determined_by` at preventability determination — and the segregation-of-duties checks in §2.10 compare those recorded values against the caller's `X-User-ID`. It is never compared to any entity's `id`.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a bare UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon every change to the resource's properties.
- `version` (integer): starts at 1 at creation and increments by one on every mutation of the resource, including mutations caused by cascades from operations on other resources.

**Measurement snapshots are the exception.** A measurement snapshot is an immutable epoch artifact: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock

All temporal rules in this document — occurrence windows, cooling-off periods, retention deadlines, measurement epochs — are evaluated against a server-side logical clock, never against wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own.

A `SafetyAdmin` may advance the clock through a test-driving capability that accepts a target instant `to_iso8601` and responds with the resulting `current_utc`. The clock moves strictly forward: a `to_iso8601` equal to or earlier than the current logical clock is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409).

### 2.6. Request Evaluation Pipeline

Every request is validated against the following stages, evaluated in the order given; a request that fails several checks receives the error from the earliest failing stage.

1. **Authentication context.** Both headers are present and non-empty — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400).
2. **Authorization.** The role is a declared role and is permitted on the endpoint — otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Request shape.** Required fields are present — including the conditional requirements that `safety_audit_due_date` accompanies `is_new_entrant` and that `accident_id` accompanies a `POST_ACCIDENT` `test_type` — enum members are valid, and numeric ranges hold (`fleet_size` at least 1, `severity_weight` between 1 and 10, `inspection_level` between 1 and 3, counts at least 0, `policy_period_end` later than `policy_period_start`). Violations surface as `ERR_INVALID_REQUEST`, `ERR_MISSING_ACCIDENT_LINK`, `ERR_INVALID_FLEET_SIZE`, `ERR_INVALID_SEVERITY_WEIGHT`, or `ERR_INVALID_DATE_RANGE` (all HTTP 400).
4. **Existence.** Path identifiers are resolved first, from left to right; then body foreign-key identifiers are resolved in their declared input order. Each missing resource yields its own 404: `ERR_CARRIER_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_CHALLENGE_NOT_FOUND`, `ERR_COACHING_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_ACCIDENT_NOT_FOUND`, `ERR_AUDIT_CASE_NOT_FOUND`, `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_PREMIUM_MODEL_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_TESTING_PERIOD_NOT_FOUND`, or `ERR_SNAPSHOT_NOT_FOUND`.
5. **State eligibility.** The target entity and the entities it references must be in a state that permits the operation — the from-state of the intended transition, a driver in the required employment status, an inspection not yet finalized, a premium model in the required status, and so on. Violations surface as the state-specific 409 errors cited throughout §3.
6. **Optimistic concurrency.** On the two endpoints that declare an expected-version field, the supplied value must equal the parent entity's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412). See §2.7.
7. **Segregation of duties.** The MRO verifier must differ from the test recorder, and the preventability determiner must differ from the accident registrar — otherwise `ERR_SOD_VERIFIER_IS_RECORDER` or `ERR_SOD_PREVENTABILITY_SAME_USER` (both HTTP 409). See §2.10.
8. **Temporal gates.** Occurrence timestamps must not lie in the future of the logical clock, post-accident collection windows must be met, cooling-off periods must have elapsed, a new-entrant audit must not be scheduled past its due date, field work must not begin before its scheduled date, a testing period closes only after its program year ends, and the logical clock only moves forward. Violations surface as `ERR_FUTURE_OCCURRENCE`, `ERR_POST_ACCIDENT_WINDOW_MISSED`, `ERR_COOLING_OFF_ACTIVE`, `ERR_AUDIT_SCHEDULED_PAST_DUE`, `ERR_AUDIT_BEFORE_SCHEDULED_DATE`, `ERR_PERIOD_NOT_ENDED`, or `ERR_CLOCK_REGRESSION` (all HTTP 409).
9. **Uniqueness, overlap, and limits.** Duplicate identifiers, singleton open records, overlapping windows, the remand limit, verdict-to-result consistency, the one-cycle-per-day rule, driver-to-carrier membership, and audit-type applicability. Violations surface as the `ERR_DUPLICATE_DOT_NUMBER`, `ERR_DUPLICATE_CATEGORY_CODE`, `ERR_DUPLICATE_REPORT_NUMBER`, or `ERR_DUPLICATE_TESTING_PERIOD` uniqueness errors, or as `ERR_OPEN_UPGRADE_REQUEST_EXISTS`, `ERR_AUDIT_WINDOW_OVERLAP`, `ERR_POLICY_PERIOD_OVERLAP`, `ERR_REMAND_LIMIT_REACHED`, `ERR_VERDICT_RESULT_MISMATCH`, `ERR_CYCLE_ALREADY_RUN_TODAY`, `ERR_DRIVER_CARRIER_MISMATCH`, or `ERR_AUDIT_TYPE_NOT_APPLICABLE` (all HTTP 409).
10. **Cross-entity holds.** Finalization blocked by open challenges, purge blocked by an open audit, field work gated on audit readiness, reinstatement gated on suspension holds, and rating upgrade eligibility. Violations surface as `ERR_OPEN_CHALLENGES_BLOCK_FINALIZE`, `ERR_AUDIT_HOLD_ACTIVE`, `ERR_AUDIT_READINESS_INCOMPLETE`, `ERR_REINSTATE_REQUIREMENTS_UNMET`, or `ERR_RATING_NOT_UPGRADABLE` (all HTTP 409).

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and on both the expected-version field is a mandatory, non-optional input.

Creating a coaching assignment (`POST /safety/coaching-assignments`) requires `expected_driver_version`, carrying the client's last observed `version` of the coached driver. Updating a carrier's profile (`PATCH /safety/carriers/{id}`) requires `expected_carrier_version`, carrying the client's last observed `version` of the carrier. When the supplied value does not equal the parent entity's current `version` — because the driver or carrier has advanced through changes the client has not observed — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.8. Version Cascades and Premium Staleness

A carrier's `version` advances on profile updates, safety rating changes, audit closes, upgrade decisions, and every measurement cycle run for it. A driver's `version` advances on coaching creation and escalation, on suspension by a verified test result, on termination, and on reinstatement. These version counters are the staleness currency for insurance modeling.

An insurance premium model in `QUOTED` status is swept to `STALE` — a derived-field reconciliation marker — whenever any of the following occurs for its carrier: the carrier profile is updated, the carrier's safety rating changes by audit close or upgrade approval, a new-entrant audit fails, a measurement cycle runs for the carrier, or one of the carrier's drivers changes `risk_tier`. Models in `DRAFT` are not eagerly swept; instead, both quoting and binding require the model's `carrier_version_at_compute` to equal the carrier's current `version`, and a model whose inputs have moved underneath it is rejected with `ERR_PREMIUM_INPUT_STALE` (HTTP 409). The recovery path for a stale draft is recomputation, which re-reads current carrier data and refreshes `carrier_version_at_compute` (see §3.9).

### 2.9. Precision, Rounding, and Calendar Arithmetic

Category measures are carried to exactly 2 decimal places using round-half-up. Percentiles are whole numbers produced by rounding down (floor), capped at 100. Risk scores, crash points, weighted points, and testing quotas are integers; quota requirements round up to a whole number (ceiling), and exact multiples do not round up. Premium amounts are integer cents with round-half-up applied exactly once, at the final step of the premium formula — no intermediate rounding occurs anywhere before it. Rating factors are exact decimals: 1.05, 1.00, 1.25, and 1.60.

All month arithmetic is calendar-month arithmetic with day-of-month clamping: when the target month has no such day, the result lands on that month's last day. For example, 2026-08-31 minus six months is 2026-02-28, while 2024-02-29 plus twelve months is 2025-02-28 and 2026-01-31 plus twelve months is 2027-01-31.

### 2.10. Segregation of Duties

Two adjudications are deliberately segregated from the people who recorded the underlying data. The `MedicalReviewOfficer` who verifies a drug or alcohol test must not be the operator who recorded the collection: when the verifier's `X-User-ID` equals the test's `recorded_by_user_id`, verification is rejected with `ERR_SOD_VERIFIER_IS_RECORDER` (HTTP 409). Symmetrically, the `SafetyDirector` who determines the preventability of an accident must not be the `SafetyManager` who registered it: when the determiner's `X-User-ID` equals the accident's `registered_by_user_id`, the determination is rejected with `ERR_SOD_PREVENTABILITY_SAME_USER` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Carrier Onboarding and Measurement Categories

A `SafetyAdmin` registers a **carrier** with its `dot_number`, `legal_name`, and `fleet_size` — the number of power units, which must be at least 1, failing with `ERR_INVALID_FLEET_SIZE` otherwise. The `dot_number` is unique across all carriers, and a duplicate is rejected with `ERR_DUPLICATE_DOT_NUMBER`. A carrier in the new-entrant safety assurance program is registered with `is_new_entrant` set to true (it defaults to false), and `safety_audit_due_date` — the deadline for the new-entrant safety audit — is required if and only if `is_new_entrant` is true; a registration that violates this conditional requirement is rejected with `ERR_INVALID_REQUEST`.

A new carrier starts with `safety_rating` `NONE`, `posture` `NORMAL`, `rating_cooling_off_until` null, `last_cycle_date` null, and `version` 1; its `new_entrant_status` is `PENDING_AUDIT` when registered as a new entrant and `NOT_NEW_ENTRANT` otherwise. The rating ladder ranks `SATISFACTORY` above `CONDITIONAL` above `UNSATISFACTORY`, with `NONE` as the unrated starting point; this ordering is what makes a rating change a downgrade. A `SafetyAdmin` may later update `legal_name` or `fleet_size` under optimistic concurrency (§2.7); each successful update increments the carrier's `version` and sweeps its `QUOTED` premium models to `STALE` (§2.8). The carrier list supports filtering by `safety_rating` and `posture`.

The measurement framework itself is configured through **violation categories**. A `SafetyAdmin` defines each category with a unique `category_code` — one of `UNSAFE_DRIVING`, `HOURS_OF_SERVICE`, `DRIVER_FITNESS`, `CONTROLLED_SUBSTANCES_ALCOHOL`, `VEHICLE_MAINTENANCE`, `HAZMAT`, or `CRASH_INDICATOR`, with reuse of a code rejected as `ERR_DUPLICATE_CATEGORY_CODE` — plus a `display_name`, an `intervention_threshold` (the percentile, from 1 to 100, at or above which the category is alerted), and a `benchmark_measure`, the measure value in points per power unit that maps to the 100th percentile, which must be greater than 0. The `measure_window_months` look-back used by the time-weight rule defaults to 24 and is pinned to 24 for every category in this benchmark.

### 3.2. The Driver Roster and the Risk Score

A `SafetyManager` adds a **driver** to a carrier roster by supplying the employing `carrier_id`, the driver's `cdl_number`, `full_name`, and `hire_date`. A new driver starts `ACTIVE` with `risk_score` 0, `risk_tier` `LOW`, and `coaching_strikes` 0. The driver list can be filtered by `carrier_id`, `employment_status`, and `risk_tier`.

The `risk_score` aggregates everything currently counting against the driver: the sum of `weighted_points` over the driver's violations in `ACTIVE` or `CHALLENGED` status whose current time-weight multiplier is greater than zero, plus the sum of `crash_points` multiplied by the accident's time weight over the driver's accidents that are both `PREVENTABLE` and DOT-reportable and whose time weight is positive, minus a coaching credit of two points for each coaching assignment the driver has `COMPLETED` whose `completed_at` falls within the trailing twenty-four months. The score is floored at zero — it never goes negative. The `risk_tier` derives from it: `LOW` below 10, `MEDIUM` from 10 through 19, and `HIGH` at 20 or above. The score is recomputed whenever a violation is created, overturned, or upheld, whenever preventability is determined, whenever coaching is completed, and at every measurement cycle.

**Suspension holds.** A driver carries a suspension hold under either of two conditions: (a) any coaching assignment of the driver is in `ESCALATED` status, or (b) there exists an `MRO_VERIFIED` test of the driver with `mro_verdict` `VERIFIED_POSITIVE` or `VERIFIED_REFUSAL` for which no later `MRO_VERIFIED` `RETURN_TO_DUTY` test exists with `mro_verdict` `VERIFIED_NEGATIVE` and a `collected_at` strictly after the positive or refusal test's `verified_at`. Reinstatement — manual or automatic — succeeds only when the hold count is zero.

Termination moves a driver from `ACTIVE` or `SUSPENDED` to terminal `TERMINATED`, cancels every coaching assignment of the driver still in `ASSIGNED`, `IN_PROGRESS`, `OVERDUE`, or `ESCALATED`, and increments the driver's `version`; a driver who is already `TERMINATED` cannot be terminated again and the attempt is rejected with `ERR_DRIVER_NOT_ACTIVE`. An assignment that was `ESCALATED` when cancelled by this cascade triggers no reinstatement evaluation — the driver simply remains `TERMINATED`. Reinstatement by a `SafetyManager` moves a `SUSPENDED` driver back to `ACTIVE` and increments `version`; it is rejected with `ERR_DRIVER_NOT_SUSPENDED` when the driver is not `SUSPENDED`, and with `ERR_REINSTATE_REQUIREMENTS_UNMET` while any suspension hold remains.

### 3.3. Roadside Inspection Intake and Review

A `SafetyManager` imports a **roadside inspection** with the inspected `carrier_id` and `driver_id`, the state-issued `report_number`, the `inspection_date`, the `inspection_level` (an integer from 1 to 3), and the two-letter `state_code` where the inspection occurred. The named driver must belong to the named carrier, otherwise the import is rejected with `ERR_DRIVER_CARRIER_MISMATCH`. The `report_number` is unique per carrier (`ERR_DUPLICATE_REPORT_NUMBER`), and the `inspection_date` may not lie in the future of the logical clock (`ERR_FUTURE_OCCURRENCE`). A fresh inspection lands in `IMPORTED` with `total_weighted_points` 0. The inspection list can be filtered by `carrier_id`, `driver_id`, and `review_status`.

Review proceeds under a `ComplianceAnalyst`: beginning review moves `IMPORTED` → `UNDER_REVIEW`, and finalizing moves `UNDER_REVIEW` → `FINALIZED`; either action attempted from the wrong state is rejected with `ERR_INSPECTION_NOT_REVIEWABLE`. Finalization is additionally blocked while any violation of the inspection carries an open challenge — one in `SUBMITTED`, `UNDER_REVIEW`, or `REMANDED` status — surfacing as `ERR_OPEN_CHALLENGES_BLOCK_FINALIZE`. `FINALIZED` is terminal: recording a new violation on a finalized inspection, or filing a challenge against one of its violations, is rejected with `ERR_INSPECTION_FINALIZED`.

Violations are recorded by a `SafetyManager` against an inspection, supplying `inspection_id`, the measurement `category_id`, the regulation `violation_code` (for example 392.2 or 395.8), a `severity_weight` from 1 to 10 (anything outside that range is rejected with `ERR_INVALID_SEVERITY_WEIGHT`), and the `occurred_at` timestamp, which may not be later than the logical clock (`ERR_FUTURE_OCCURRENCE`). The cited `driver_id` is optional on input and defaults to the inspection's driver; the cited driver must be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`). Each new violation starts in `ACTIVE` status. The violation list can be filtered by `inspection_id`, `category_id`, `driver_id`, and `status`.

**Time weighting.** Every violation carries a computed `time_weight_multiplier`, evaluated against the logical clock at creation and refreshed by every measurement cycle. Multiplier 3 applies when the violation occurred no more than six calendar months before the current instant — a violation exactly six months old is included, as is one occurring exactly at the current instant. Multiplier 2 applies when it occurred more than six but no more than twelve months ago, with exactly twelve months old included. Multiplier 1 applies when it occurred more than twelve but no more than twenty-four months ago, with exactly twenty-four months old included. Anything strictly older than twenty-four months takes multiplier 0 and drops out of every measure and every risk score. The violation's `weighted_points` are its `severity_weight` multiplied by that multiplier, recomputed whenever the multiplier is refreshed. Recording a violation also recomputes the parent inspection's `total_weighted_points` — the sum of `weighted_points` over its violations in `ACTIVE` or `CHALLENGED` status, with `REMOVED` always excluded — and the cited driver's `risk_score`; when that recomputation changes the driver's `risk_tier`, the carrier's `QUOTED` premium models go `STALE` (§2.8).

### 3.4. The DataQs Challenge Loop

When the carrier believes a violation record is wrong, a `ComplianceAnalyst` files a **DataQs challenge** carrying the target `violation_id`, a `reason_code` of `INCORRECT_DATA`, `WRONG_CARRIER`, `WRONG_DRIVER`, `DUPLICATE_REPORT`, or `OTHER`, and a free-text `evidence_note`. Filing requires the violation to be `ACTIVE` (`ERR_VIOLATION_NOT_ACTIVE` otherwise); because filing moves the violation `ACTIVE` → `CHALLENGED`, this same state check structurally enforces the one-open-challenge-per-violation rule, rejecting any second challenge while the first is in flight. The parent inspection must not be `FINALIZED` (`ERR_INSPECTION_FINALIZED`). The server stamps the challenge with the filer's identity as `filed_by_user_id`, sets `remand_count` to 0, and places it in `SUBMITTED`. A `CHALLENGED` violation still counts toward the official measure but is excluded from the provisional one — the carrier's optimistic view while adjudication is pending (§3.10). The challenge list can be filtered by `violation_id` and `status`.

Adjudication is performed by a `SafetyAdmin` acting as the agency proxy. Starting review moves `SUBMITTED` → `UNDER_REVIEW`, and from any other state is rejected with `ERR_CHALLENGE_NOT_SUBMITTED`. The decision call takes an `outcome` and requires the challenge to be `UNDER_REVIEW`; from any other state — including a second decision on a challenge that has already reached a terminal state — it is rejected with `ERR_CHALLENGE_NOT_UNDER_REVIEW`. Three outcomes exist:

- `UPHELD` closes the challenge and returns the violation `CHALLENGED` → `ACTIVE`. The inspection's `total_weighted_points` and the driver's `risk_score` are both recomputed but remain numerically unchanged, since a `CHALLENGED` violation was already counted in each — the compensating invariant that keeps official figures stable through adjudication. The challenge's `decided_at` is stamped with the clock.
- `OVERTURNED` closes the challenge and moves the violation `CHALLENGED` → `REMOVED`, which is terminal. The inspection's `total_weighted_points` drops by the removed violation's `weighted_points`, the driver's `risk_score` is recomputed, and if the driver's `risk_tier` changes, every `QUOTED` premium model of the carrier goes `STALE`. The challenge's `decided_at` is stamped with the clock.
- `REMANDED` sends the challenge back for more evidence: `remand_count` increments by one, `decided_at` is stamped with the clock, and the violation remains `CHALLENGED`. A challenge may be remanded at most twice — deciding `REMANDED` when `remand_count` has already reached 2 is rejected with `ERR_REMAND_LIMIT_REACHED`.

A remanded challenge can be re-filed by a `ComplianceAnalyst` with a fresh `evidence_note`, moving `REMANDED` → `SUBMITTED`; from any other state resubmission is rejected with `ERR_CHALLENGE_NOT_REMANDED`. From `SUBMITTED` the loop begins again. `UPHELD` and `OVERTURNED` are terminal for the challenge.

### 3.5. Coaching Assignments and Corrective Action

A `SafetyManager` assigns **coaching** to a driver with `driver_id`, a `coaching_type` of `VERBAL_WARNING`, `TRAINING_COURSE`, or `PROBATION`, a `due_date` completion deadline, and optionally the `source_violation_id` that triggered the assignment. The driver must be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`). Creation requires the driver's expected version under optimistic concurrency (§2.7), and it legitimately supersedes an existing open assignment of the same driver and `coaching_type`: when one in `ASSIGNED`, `IN_PROGRESS`, `OVERDUE`, or `ESCALATED` exists, the prior assignment moves to `SUPERSEDED`, and if the superseded assignment was `ESCALATED` the driver's suspension holds are re-evaluated, returning a `SUSPENDED` driver to `ACTIVE` if and only if zero holds remain. Because a second creation issued after another manager's creation still sees an `ACTIVE` driver and would pass on state grounds alone, the stale `expected_driver_version` is what reveals that the client's basis is out of date. Creation increments the driver's `version`, stamps `assigned_by_user_id` with the creator's identity, and lands the new assignment in `ASSIGNED`. The coaching list can be filtered by `driver_id`, `status`, and `source_violation_id`.

Starting work moves `ASSIGNED` → `IN_PROGRESS`. Completion, submitted with a `completion_note`, moves an assignment from `ASSIGNED`, `IN_PROGRESS`, `OVERDUE`, or `ESCALATED` to `COMPLETED`; either action attempted from an ineligible state — including the terminal states `COMPLETED`, `SUPERSEDED`, and `CANCELLED` — is rejected with `ERR_COACHING_NOT_OPEN`. Completion stamps `completed_at` with the clock, recomputes the driver's `risk_score` (the two-point completion credit described in §3.2), and, when the completed assignment was previously `ESCALATED`, re-evaluates the driver's suspension holds and automatically moves a `SUSPENDED` driver back to `ACTIVE` if and only if zero holds remain.

When a measurement cycle finds an assignment in `ASSIGNED` or `IN_PROGRESS` whose `due_date` lies before the current logical clock, it marks the assignment `OVERDUE`. A `SafetyManager` may then escalate it: escalation requires the assignment to be `OVERDUE` (`ERR_COACHING_NOT_OVERDUE` from any other state) and the driver still `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`), and it moves the assignment to `ESCALATED`, suspends the driver (`ACTIVE` → `SUSPENDED`), adds one to the driver's `coaching_strikes`, and increments the driver's `version`.

`COMPLETED`, `SUPERSEDED`, and `CANCELLED` are terminal. The termination cascade that cancels a driver's open assignments is described in §3.2.

### 3.6. Drug and Alcohol Program Administration

A `SafetyManager`, acting as the designated employer representative, records a **test collection** with `driver_id`, a `test_type` of `PRE_EMPLOYMENT`, `RANDOM`, `POST_ACCIDENT`, `REASONABLE_SUSPICION`, `RETURN_TO_DUTY`, or `FOLLOW_UP`, a `substance` of `DRUG` or `ALCOHOL`, and the `collected_at` specimen timestamp, which may not lie in the future of the logical clock (`ERR_FUTURE_OCCURRENCE`). Most test types require the driver to be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`); the exceptions are `RETURN_TO_DUTY` and `FOLLOW_UP`, which require the driver to be `SUSPENDED` and are rejected with `ERR_DRIVER_NOT_SUSPENDED` otherwise. A `POST_ACCIDENT` test must carry the `accident_id` of the crash that prompted it, and an `accident_id` supplied on any other test type is likewise invalid — both directions surface as `ERR_MISSING_ACCIDENT_LINK`. A post-accident collection must fall within the federal testing window measured from the accident's `occurred_at`: no more than 8 hours after the accident for an `ALCOHOL` test and no more than 32 hours for a `DRUG` test, with a later collection rejected as `ERR_POST_ACCIDENT_WINDOW_MISSED`, and it must never precede the accident itself (`ERR_INVALID_DATE_RANGE`). A new record starts in `COLLECTED` with `lab_result` `PENDING` and `mro_verdict` `NONE`, and the recorder's identity is stamped as `recorded_by_user_id`. The test list can be filtered by `driver_id`, `test_type`, `status`, and `accident_id`.

The laboratory report, recorded by a `SafetyManager` through a `lab_result` payload, moves a `COLLECTED` test to `LAB_REPORTED` when the payload is `NEGATIVE`, `POSITIVE`, or `REFUSAL`, or to terminal `CANCELLED` when the payload is `CANCELLED_BY_LAB`; a test in any other state is rejected with `ERR_TEST_NOT_COLLECTED`. The payload value is stored on the record.

Verification belongs exclusively to the `MedicalReviewOfficer`, who submits a `verdict` on a `LAB_REPORTED` test (`ERR_TEST_NOT_LAB_REPORTED` from any other state). Segregation of duties applies (§2.10): the verifier must differ from the operator who recorded the collection (`ERR_SOD_VERIFIER_IS_RECORDER`). The verdict must be consistent with the laboratory result — `NEGATIVE` maps to `VERIFIED_NEGATIVE`, `POSITIVE` to `VERIFIED_POSITIVE`, and `REFUSAL` to `VERIFIED_REFUSAL` — and any other pairing is rejected with `ERR_VERDICT_RESULT_MISMATCH`. A consistent verdict moves the test to terminal `MRO_VERIFIED`, stamping `mro_verdict`, `verified_by_user_id`, and `verified_at` with the clock. Alternatively the MRO may return the verdict `CANCELLED`, which is not subject to the result-consistency mapping and moves the test to terminal `CANCELLED` with `mro_verdict` `CANCELLED` and `verified_at` stamped. When a test is verified `VERIFIED_POSITIVE` or `VERIFIED_REFUSAL` and the driver is `ACTIVE`, the driver is immediately suspended and the driver's `version` increments; from that moment a suspension hold (§3.2) stands until a verified negative return-to-duty test clears it. Random-testing completion counters are not mutated by verification — they are recomputed live on read, as described below.

**Random testing quotas.** A `SafetyManager` opens an annual **random testing period** with `carrier_id`, the `program_year`, and the `avg_driver_count` of the random pool, which must be at least 1. Only one period may exist per carrier per calendar year; a duplicate is rejected with `ERR_DUPLICATE_TESTING_PERIOD`. The required counts are computed at creation: `required_drug_tests` is one quarter of `avg_driver_count` rounded up to a whole number, and `required_alcohol_tests` is one tenth of it rounded up the same way; exact multiples do not round up, so eight drivers require exactly two drug tests. The `completed_drug_tests` and `completed_alcohol_tests` counters are computed live on read rather than stored: each counts tests of the carrier's drivers whose `substance` matches the counter, whose `test_type` is `RANDOM`, whose status is `MRO_VERIFIED` with `mro_verdict` one of `VERIFIED_NEGATIVE`, `VERIFIED_POSITIVE`, or `VERIFIED_REFUSAL`, and whose `collected_at` falls within the program year — January 1 of `program_year` inclusive through January 1 of the following year exclusive. The period list can be filtered by `carrier_id` and `status`.

A period in `OPEN` may be closed by a `SafetyManager` once the clock has reached midnight UTC on January 1 of the year following `program_year`; closing earlier is rejected with `ERR_PERIOD_NOT_ENDED`, and closing a period that is not `OPEN` is rejected with `ERR_PERIOD_NOT_OPEN`. The close verdict is automatic: when both completed counters meet or exceed their required counts — equality is compliant — the period closes `CLOSED_COMPLIANT`; any shortfall in either counter closes it `CLOSED_DEFICIENT`. Both closed states are terminal.

### 3.7. The Accident Register and Preventability Review

A `SafetyManager` registers an **accident** with the `carrier_id` holding the register, the involved `driver_id` (which must belong to that carrier, otherwise `ERR_DRIVER_CARRIER_MISMATCH`), the `occurred_at` timestamp (not in the future of the logical clock, otherwise `ERR_FUTURE_OCCURRENCE`), the `fatalities` count, the `injuries` count of people treated immediately away from the scene (both counts at least 0), whether any vehicle was towed from the scene (`tow_away`), and whether hazardous materials were released (`hazmat_release`, defaulting to false). Two derived values are computed at registration. `dot_reportable` is true when at least one fatality occurred, at least one injury occurred, or any vehicle was towed. `crash_points` sum the severity: four points when at least one fatality occurred, two more when at least one injury occurred, and one more when a vehicle was towed — a range of 0 to 7. The registrar's identity is stamped as `registered_by_user_id`, and the record enters `PENDING_REVIEW`. The register list can be filtered by `carrier_id`, `driver_id`, and `preventability_status`.

Preventability is adjudicated by a `SafetyDirector` submitting a `determination` of `PREVENTABLE` or `NOT_PREVENTABLE`. The record must still be in `PENDING_REVIEW` — a second determination is rejected with `ERR_PREVENTABILITY_ALREADY_DETERMINED` — and segregation of duties forbids the registrar from determining their own record (`ERR_SOD_PREVENTABILITY_SAME_USER`, §2.10). Either determination stamps `preventability_determined_by` with the determiner's identity and is terminal. A `PREVENTABLE` determination additionally recomputes the driver's `risk_score`, because the accident's crash points — weighted by the accident's age under the time-weight rule of §3.3 — now count against the driver; if the driver's `risk_tier` changes, the carrier's `QUOTED` premium models go `STALE` (§2.8).

### 3.8. Compliance Audits, Safety Ratings, and Upgrade Requests

A `SafetyAdmin` schedules an **audit case** with `carrier_id`, an `audit_type` of `NEW_ENTRANT` or `COMPLIANCE_REVIEW`, a `scheduled_date` marking the start of the field-work window, and optionally `field_work_duration_days`, the window length in days (defaulting to 14, and at least 1). The window is half-open: it covers `scheduled_date` inclusive up to but excluding `scheduled_date` plus the duration, and it may not intersect the window of any other non-closed audit case for the same carrier (`ERR_AUDIT_WINDOW_OVERLAP`). A `NEW_ENTRANT` audit may be created only for a carrier that is a new entrant whose `new_entrant_status` is `PENDING_AUDIT` (`ERR_AUDIT_TYPE_NOT_APPLICABLE`), and its `scheduled_date` may not fall after the carrier's `safety_audit_due_date` (`ERR_AUDIT_SCHEDULED_PAST_DUE`). The case starts `SCHEDULED`. The audit list can be filtered by `carrier_id`, `audit_type`, and `status`.

Field work begins at a `SafetyAdmin`'s hand, but only once three gates pass: the case is `SCHEDULED` (`ERR_AUDIT_INVALID_STATE`), the clock has reached `scheduled_date` (`ERR_AUDIT_BEFORE_SCHEDULED_DATE`), and the carrier's computed audit-readiness summary reports `ready` as true (`ERR_AUDIT_READINESS_INCOMPLETE`). That summary — available to every role — returns `ready`, `missing_dq_driver_count`, `accident_register_gap`, `purge_eligible_document_count`, and `open_audit_case_count`. Starting field work moves `SCHEDULED` → `FIELD_WORK`.

Findings are issued by a `SafetyAdmin` from `FIELD_WORK` (`ERR_AUDIT_INVALID_STATE` otherwise) by supplying the `acute_count` and `critical_count` of violations found, moving the case `FIELD_WORK` → `FINDINGS_ISSUED`. The `proposed_outcome` is computed at this point. For a `NEW_ENTRANT` audit the outcome is `FAIL` when at least one acute violation or at least three critical violations were found, and `PASS` otherwise. For a `COMPLIANCE_REVIEW` the outcome is `UNSATISFACTORY` when at least two acute or at least four critical violations were found; otherwise `SATISFACTORY` when no acute and at most one critical violation were found; otherwise `CONDITIONAL`. The boundaries are inclusive exactly as stated — a single acute violation routes a compliance review to `CONDITIONAL`, three critical violations yield `CONDITIONAL`, and four yield `UNSATISFACTORY`.

When the proposed outcome is adverse — `FAIL`, `CONDITIONAL`, or `UNSATISFACTORY` — a `SafetyManager` may move the case `FINDINGS_ISSUED` → `CORRECTIVE_ACTION_PHASE`; when it is `PASS` or `SATISFACTORY` there is nothing to correct and the request is rejected with `ERR_CORRECTIVE_ACTION_NOT_APPLICABLE`. From any state other than `FINDINGS_ISSUED` the request fails with `ERR_AUDIT_INVALID_STATE`.

Closing the audit belongs to the `SafetyDirector` and is permitted from either `FINDINGS_ISSUED` or `CORRECTIVE_ACTION_PHASE` — from anywhere else, including the terminal states, it is rejected with `ERR_AUDIT_INVALID_STATE`. A `PASS` or `SATISFACTORY` outcome closes the case as `CLOSED_PASSED`; a `FAIL`, `CONDITIONAL`, or `UNSATISFACTORY` outcome closes it as `CLOSED_FAILED`. The close applies the outcome to the carrier. A new-entrant `PASS` moves the carrier's `new_entrant_status` from `PENDING_AUDIT` to `PASSED`, recomputes its posture, and increments its `version`. A new-entrant `FAIL` moves it to `FAILED`, forces the carrier's `posture` to `OUT_OF_SERVICE_PROPOSED`, sweeps its `QUOTED` premium models to `STALE`, and increments `version`. A compliance review writes the `proposed_outcome` into the carrier's `safety_rating` — from whatever rating it held before, including `NONE` — increments `version`, recomputes posture, sweeps `QUOTED` premium models to `STALE`, and, when the new rating ranks worse than the old one on the `SATISFACTORY`-above-`CONDITIONAL`-above-`UNSATISFACTORY` ladder, sets `rating_cooling_off_until` to 180 days after the current clock. Both closed states are terminal.

A carrier rated `CONDITIONAL` or `UNSATISFACTORY` may seek rehabilitation through a **rating upgrade request**, filed by a `SafetyManager` with `carrier_id`, a `requested_rating` of `SATISFACTORY` or `CONDITIONAL`, and a `justification_note` summarizing the corrective-action evidence. Filing is rejected with `ERR_RATING_NOT_UPGRADABLE` when the carrier's current rating is `NONE` or `SATISFACTORY`, or when the requested rating does not rank strictly above the current one. While the carrier's `rating_cooling_off_until` lies in the future of the clock, filing is rejected with `ERR_COOLING_OFF_ACTIVE`; an approval clears that field back to null. Only one open request — one in `SUBMITTED` or `UNDER_REVIEW` — may exist per carrier at a time (`ERR_OPEN_UPGRADE_REQUEST_EXISTS`). A new request starts `SUBMITTED`, and the list can be filtered by `carrier_id` and `status`.

Adjudication belongs to the `SafetyDirector`. Starting review moves `SUBMITTED` → `UNDER_REVIEW`; the decision takes an `outcome` of `APPROVED` or `DENIED` and requires `UNDER_REVIEW`. Either action from the wrong state — including a decision on an already `APPROVED` or `DENIED` request — is rejected with `ERR_UPGRADE_INVALID_STATE`. An approval writes the `requested_rating` into the carrier's `safety_rating`, clears `rating_cooling_off_until` to null, recomputes posture, sweeps the carrier's `QUOTED` premium models to `STALE`, increments the carrier's `version`, and stamps the request's `decided_at`. A denial sets `rating_cooling_off_until` to 90 days after the current clock, increments the carrier's `version`, and stamps `decided_at`. `APPROVED` and `DENIED` are both terminal.

### 3.9. Insurance Premium Modeling

An `InsuranceAnalyst` models the premium impact of a policy period by creating an **insurance premium model** with `carrier_id`, the `policy_period_start` and `policy_period_end` bounding the period as a closed interval on both ends, the `base_rate_cents_per_unit` (the base premium rate in cents per power unit per policy period, at least 1), and a `scenario` of `BASELINE` or `PROJECTED`. The end must be later than the start, otherwise creation fails with `ERR_INVALID_DATE_RANGE`. Because the interval is closed, policy periods of the same carrier may not intersect among models in `DRAFT`, `QUOTED`, or `BOUND` — touching endpoints already count as overlap — and a conflicting model is rejected with `ERR_POLICY_PERIOD_OVERLAP`; `STALE` models no longer participate in the overlap check. The model list can be filtered by `carrier_id`, `status`, and `scenario`.

A `PROJECTED` model answers "what if" through three overrides that apply only to that scenario: `assume_rating` (one of `NONE`, `SATISFACTORY`, or `CONDITIONAL` — `UNSATISFACTORY` is not modelable), which replaces the carrier's current rating factor; `assume_cleared_category_codes`, the list of category codes treated as below their intervention threshold; and `assume_removed_preventable_accidents`, the number of preventable accidents treated as removed from the in-window count. A `BASELINE` model uses the carrier's current `safety_rating`, the current alerted set, and the current preventable-accident count.

The premium itself is computed in a fixed evaluation order, and rounding happens exactly once, at the final step:

1. The base amount is the carrier's `fleet_size` multiplied by `base_rate_cents_per_unit`.
2. The rating factor is 1.05 for `NONE`, 1.00 for `SATISFACTORY`, 1.25 for `CONDITIONAL`, and 1.60 for `UNSATISFACTORY`; a `PROJECTED` model carrying `assume_rating` substitutes the assumed rating's factor. The factor applied is recorded as `rating_factor_used`.
3. `score_loading_pct` is three percentage points per category flagged `alerted_official` in the carrier's latest measurement cycle, capped at fifteen; a `PROJECTED` model first removes the codes listed in `assume_cleared_category_codes` from the alerted set. Before any cycle has run for the carrier, the alerted set is empty.
4. `crash_loading_pct` is five percentage points per accident on the carrier's register that is `PREVENTABLE`, DOT-reportable, and occurred within the thirty-six calendar months up to and including the computation instant, capped at twenty-five; a `PROJECTED` model subtracts `assume_removed_preventable_accidents` from that count, floored at zero.
5. `driver_loading_pct` is two percentage points per driver of the carrier whose `employment_status` is `ACTIVE` and whose `risk_tier` is `HIGH`, capped at ten — identical in both scenarios.
6. `computed_premium_cents` is the base amount multiplied by the rating factor and by one plus the sum of the three loading percentages divided by one hundred, rounded half-up to a whole cent. This is the only rounding in the computation.

Creation records the computed `computed_premium_cents`, the three loadings, and `carrier_version_at_compute` — the carrier's `version` at the moment of computation — and the model lands in `DRAFT`.

Quoting moves `DRAFT` → `QUOTED` and is rejected from any other status with `ERR_PREMIUM_MODEL_NOT_DRAFT`. Because drafts are not eagerly swept (§2.8), quoting is where the freshness gate fires for a draft whose inputs moved: when `carrier_version_at_compute` no longer equals the carrier's current `version`, the quote is rejected with `ERR_PREMIUM_INPUT_STALE`. Recomputation is the recovery path — and the refresh path for a still-valid draft: it is permitted from `STALE` or `DRAFT` (rejected from `QUOTED` or `BOUND` with `ERR_PREMIUM_MODEL_NOT_STALE`), re-validates the policy-period overlap excluding the model itself (`ERR_POLICY_PERIOD_OVERLAP`), recomputes the premium and loadings from current carrier data and the scenario overrides, refreshes `carrier_version_at_compute` to the carrier's current `version`, and leaves the model in `DRAFT`. Binding moves `QUOTED` → `BOUND`, requires the same freshness check (`ERR_PREMIUM_INPUT_STALE`), and is rejected from any status other than `QUOTED` with `ERR_PREMIUM_MODEL_NOT_QUOTED`. `BOUND` is terminal.

### 3.10. Document Retention and the Measurement Epoch

A `SafetyManager` files a **compliance document** with `carrier_id`, a `document_type` of `INSPECTION_REPORT`, `DQ_FILE`, `DRUG_TEST_RECORD`, `ALCOHOL_TEST_RECORD`, `ACCIDENT_REGISTER_ENTRY`, or `TRAINING_CERTIFICATE`, the `filed_at` date on which the retention clock starts, and optionally a subject `driver_id`, which must belong to the same carrier (`ERR_DRIVER_CARRIER_MISMATCH`). Retention is derived from the document type: `retention_months` is 12 for `INSPECTION_REPORT`; 36 for `DQ_FILE`, `ACCIDENT_REGISTER_ENTRY`, and `TRAINING_CERTIFICATE`; and 60 for `DRUG_TEST_RECORD` and `ALCOHOL_TEST_RECORD`. The `retention_until` deadline is `filed_at` advanced by that many calendar months, with the day-of-month clamped to the target month's last day when it does not exist — 2024-02-29 plus twelve months yields 2025-02-28, while 2026-01-31 plus twelve months yields 2027-01-31. A new document is `RETAINED`. The document list can be filtered by `carrier_id`, `driver_id`, `document_type`, and `status`.

Once the logical clock reaches a document's `retention_until` — equality is eligible — the next measurement cycle marks the document `PURGE_ELIGIBLE`. A `SafetyManager` may then purge it to terminal `PURGED`. Purging a document still `RETAINED` is rejected with `ERR_RETENTION_NOT_EXPIRED`, and purging one already `PURGED` with `ERR_DOCUMENT_ALREADY_PURGED`. Purge is additionally blocked while any audit case of the carrier is open — in `SCHEDULED`, `FIELD_WORK`, `FINDINGS_ISSUED`, or `CORRECTIVE_ACTION_PHASE` — surfacing as `ERR_AUDIT_HOLD_ACTIVE`.

**The measurement epoch.** A `ComplianceAnalyst` runs the measurement cycle for one carrier at a time by supplying its `carrier_id`. At most one cycle may run per carrier per UTC calendar date; a second run on the same date is rejected with `ERR_CYCLE_ALREADY_RUN_TODAY`. The cycle executes synchronously and performs all of the following: it refreshes every violation's `time_weight_multiplier` and `weighted_points` against the cycle's as-of instant (the time-weight rule of §3.3); it emits one measurement snapshot per category for the carrier; it recomputes each of the carrier's drivers' `risk_score` and `risk_tier`; it marks coaching assignments in `ASSIGNED` or `IN_PROGRESS` whose `due_date` has passed as `OVERDUE`; it marks `RETAINED` documents whose `retention_until` has been reached as `PURGE_ELIGIBLE`; it recomputes the carrier's `posture`; it stamps the carrier's `last_cycle_date` with the cycle's UTC date and increments the carrier's `version`; and it sweeps the carrier's `QUOTED` premium models to `STALE`. The cycle responds with a summary object carrying `cycle_date`, `carrier_id`, `snapshots_created`, `overdue_coaching_marked`, `documents_marked_purge_eligible`, `premiums_marked_stale`, `posture_before`, and `posture_after`.

Each **measurement snapshot** records the snapshot's `carrier_id` and `category_id`, the `cycle_date` (the UTC calendar date of the producing cycle), and the `as_of` logical-clock instant the cycle computed against. For its carrier and category, the cycle recomputes each violation's time weight against `as_of` and sums the `weighted_points` of violations in the category whose recomputed multiplier is greater than zero — the official variant includes violations in `ACTIVE` or `CHALLENGED` status, while the provisional variant counts only `ACTIVE` ones, and `REMOVED` violations are excluded from both. For the `CRASH_INDICATOR` category only, the sum additionally includes, for each of the carrier's DOT-reportable accidents, the accident's `crash_points` multiplied by the time weight of its `occurred_at`, regardless of preventability and identically in both variants because crashes cannot be challenged. Each measure — points per power unit — is the resulting total divided by the carrier's `fleet_size`, rounded half-up to two decimal places, and is stored as `official_measure` or `provisional_measure`.

Each measure is then converted to a percentile: one hundred times the measure divided by the category's `benchmark_measure`, rounded down to a whole number, and capped at 100 — stored as `official_percentile` and `provisional_percentile`. A category is alerted when its percentile reaches the category's `intervention_threshold`, with equality alerting; the flags are stored as `alerted_official` and `alerted_provisional`. Snapshots are immutable once written and can be listed with filters on `carrier_id`, `category_id`, and `cycle_date`.

The carrier's **posture** derives from the latest cycle's official alert flags and the carrier's rating state, evaluated as an ordered ladder where the first matching rule wins: (1) if `safety_rating` is `UNSATISFACTORY` or `new_entrant_status` is `FAILED`, the posture is `OUT_OF_SERVICE_PROPOSED`; (2) otherwise, if at least two categories carry `alerted_official` in the latest cycle, or the `CONTROLLED_SUBSTANCES_ALCOHOL` category carries it, the posture is `INTERVENTION_PRIORITY`; (3) otherwise, if exactly one category carries `alerted_official`, the posture is `INTERVENTION_WATCH`; (4) otherwise the posture is `NORMAL`. The alerted set always comes from the latest measurement cycle's snapshots; before any cycle has run for the carrier, it is empty. Posture is recomputed at every measurement cycle, at every audit close, and at every rating upgrade decision.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state transition, recomputation, sweep-triggering update, and the clock advance — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/safety/carriers` | Register a carrier | SafetyAdmin |
| GET | `/safety/carriers` | List carriers | All roles |
| GET | `/safety/carriers/{id}` | Get one carrier | All roles |
| PATCH | `/safety/carriers/{id}` | Update carrier profile under optimistic concurrency | SafetyAdmin |
| GET | `/safety/carriers/{id}/audit-readiness` | Computed audit-readiness summary | All roles |
| POST | `/safety/drivers` | Add a driver to a carrier roster | SafetyManager |
| GET | `/safety/drivers` | List drivers | All roles |
| GET | `/safety/drivers/{id}` | Get one driver | All roles |
| POST | `/safety/drivers/{id}/terminate` | Terminate a driver | SafetyManager |
| POST | `/safety/drivers/{id}/reinstate` | Reinstate a suspended driver | SafetyManager |
| POST | `/safety/violation-categories` | Define a measurement category | SafetyAdmin |
| GET | `/safety/violation-categories` | List categories | All roles |
| GET | `/safety/violation-categories/{id}` | Get one category | All roles |
| POST | `/safety/roadside-inspections` | Import a roadside inspection | SafetyManager |
| GET | `/safety/roadside-inspections` | List inspections | All roles |
| GET | `/safety/roadside-inspections/{id}` | Get one inspection | All roles |
| POST | `/safety/roadside-inspections/{id}/begin-review` | Move an inspection into review | ComplianceAnalyst |
| POST | `/safety/roadside-inspections/{id}/finalize` | Finalize a reviewed inspection | ComplianceAnalyst |
| POST | `/safety/inspection-violations` | Record a violation on an inspection | SafetyManager |
| GET | `/safety/inspection-violations` | List violations | All roles |
| GET | `/safety/inspection-violations/{id}` | Get one violation | All roles |
| POST | `/safety/dataqs-challenges` | File a DataQs challenge against a violation | ComplianceAnalyst |
| GET | `/safety/dataqs-challenges` | List challenges | All roles |
| GET | `/safety/dataqs-challenges/{id}` | Get one challenge | All roles |
| POST | `/safety/dataqs-challenges/{id}/start-review` | Open adjudication on a challenge | SafetyAdmin |
| POST | `/safety/dataqs-challenges/{id}/decide` | Adjudicate a challenge | SafetyAdmin |
| POST | `/safety/dataqs-challenges/{id}/resubmit` | Resubmit a remanded challenge with new evidence | ComplianceAnalyst |
| POST | `/safety/coaching-assignments` | Assign coaching to a driver | SafetyManager |
| GET | `/safety/coaching-assignments` | List coaching assignments | All roles |
| GET | `/safety/coaching-assignments/{id}` | Get one coaching assignment | All roles |
| POST | `/safety/coaching-assignments/{id}/start` | Mark coaching in progress | SafetyManager |
| POST | `/safety/coaching-assignments/{id}/complete` | Complete a coaching assignment | SafetyManager |
| POST | `/safety/coaching-assignments/{id}/escalate` | Escalate an overdue assignment, suspending the driver | SafetyManager |
| POST | `/safety/drug-alcohol-tests` | Record a drug or alcohol test collection | SafetyManager |
| GET | `/safety/drug-alcohol-tests` | List tests | All roles |
| GET | `/safety/drug-alcohol-tests/{id}` | Get one test | All roles |
| POST | `/safety/drug-alcohol-tests/{id}/report-lab-result` | Record the laboratory result | SafetyManager |
| POST | `/safety/drug-alcohol-tests/{id}/verify` | MRO verification of a lab result | MedicalReviewOfficer |
| POST | `/safety/accident-records` | Register an accident | SafetyManager |
| GET | `/safety/accident-records` | List accident register entries | All roles |
| GET | `/safety/accident-records/{id}` | Get one accident record | All roles |
| POST | `/safety/accident-records/{id}/determine-preventability` | Determine accident preventability | SafetyDirector |
| POST | `/safety/compliance-audit-cases` | Schedule an audit | SafetyAdmin |
| GET | `/safety/compliance-audit-cases` | List audit cases | All roles |
| GET | `/safety/compliance-audit-cases/{id}` | Get one audit case | All roles |
| POST | `/safety/compliance-audit-cases/{id}/start-field-work` | Open the field-work window | SafetyAdmin |
| POST | `/safety/compliance-audit-cases/{id}/issue-findings` | Issue audit findings and compute the outcome | SafetyAdmin |
| POST | `/safety/compliance-audit-cases/{id}/begin-corrective-action` | Enter the corrective action phase | SafetyManager |
| POST | `/safety/compliance-audit-cases/{id}/close` | Close the audit and apply the outcome to the carrier | SafetyDirector |
| POST | `/safety/rating-upgrade-requests` | File a safety-rating upgrade request | SafetyManager |
| GET | `/safety/rating-upgrade-requests` | List upgrade requests | All roles |
| GET | `/safety/rating-upgrade-requests/{id}` | Get one upgrade request | All roles |
| POST | `/safety/rating-upgrade-requests/{id}/start-review` | Open review on an upgrade request | SafetyDirector |
| POST | `/safety/rating-upgrade-requests/{id}/decide` | Decide an upgrade request | SafetyDirector |
| POST | `/safety/insurance-premium-models` | Model a policy premium | InsuranceAnalyst |
| GET | `/safety/insurance-premium-models` | List premium models | All roles |
| GET | `/safety/insurance-premium-models/{id}` | Get one premium model | All roles |
| POST | `/safety/insurance-premium-models/{id}/quote` | Quote a draft model | InsuranceAnalyst |
| POST | `/safety/insurance-premium-models/{id}/recompute` | Recompute a stale or draft model | InsuranceAnalyst |
| POST | `/safety/insurance-premium-models/{id}/bind` | Bind a quoted model | InsuranceAnalyst |
| POST | `/safety/document-records` | File a compliance document | SafetyManager |
| GET | `/safety/document-records` | List documents | All roles |
| GET | `/safety/document-records/{id}` | Get one document | All roles |
| POST | `/safety/document-records/{id}/purge` | Purge a purge-eligible document | SafetyManager |
| POST | `/safety/random-testing-periods` | Open an annual random testing period | SafetyManager |
| GET | `/safety/random-testing-periods` | List testing periods | All roles |
| GET | `/safety/random-testing-periods/{id}` | Get one testing period | All roles |
| POST | `/safety/random-testing-periods/{id}/close` | Close a testing period | SafetyManager |
| POST | `/safety/measurement-cycles` | Run the measurement epoch for one carrier | ComplianceAnalyst |
| GET | `/safety/measurement-snapshots` | List measurement snapshots | All roles |
| GET | `/safety/measurement-snapshots/{id}` | Get one snapshot | All roles |
| POST | `/_clock/set_current_utc` | Advance the logical clock | SafetyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MISSING_ACCIDENT_LINK` | 400 Bad Request |
| `ERR_INVALID_FLEET_SIZE` | 400 Bad Request |
| `ERR_INVALID_SEVERITY_WEIGHT` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_CARRIER_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_FOUND` | 404 Not Found |
| `ERR_CATEGORY_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_VIOLATION_NOT_FOUND` | 404 Not Found |
| `ERR_CHALLENGE_NOT_FOUND` | 404 Not Found |
| `ERR_COACHING_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_ACCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_UPGRADE_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_PREMIUM_MODEL_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TESTING_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_ACTIVE` | 409 Conflict |
| `ERR_DRIVER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_INSPECTION_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_INSPECTION_FINALIZED` | 409 Conflict |
| `ERR_VIOLATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_CHALLENGE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CHALLENGE_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CHALLENGE_NOT_REMANDED` | 409 Conflict |
| `ERR_COACHING_NOT_OPEN` | 409 Conflict |
| `ERR_COACHING_NOT_OVERDUE` | 409 Conflict |
| `ERR_TEST_NOT_COLLECTED` | 409 Conflict |
| `ERR_TEST_NOT_LAB_REPORTED` | 409 Conflict |
| `ERR_PREVENTABILITY_ALREADY_DETERMINED` | 409 Conflict |
| `ERR_AUDIT_INVALID_STATE` | 409 Conflict |
| `ERR_UPGRADE_INVALID_STATE` | 409 Conflict |
| `ERR_PREMIUM_MODEL_NOT_DRAFT` | 409 Conflict |
| `ERR_PREMIUM_MODEL_NOT_QUOTED` | 409 Conflict |
| `ERR_PREMIUM_MODEL_NOT_STALE` | 409 Conflict |
| `ERR_PREMIUM_INPUT_STALE` | 409 Conflict |
| `ERR_RETENTION_NOT_EXPIRED` | 409 Conflict |
| `ERR_DOCUMENT_ALREADY_PURGED` | 409 Conflict |
| `ERR_PERIOD_NOT_OPEN` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_VERIFIER_IS_RECORDER` | 409 Conflict |
| `ERR_SOD_PREVENTABILITY_SAME_USER` | 409 Conflict |
| `ERR_FUTURE_OCCURRENCE` | 409 Conflict |
| `ERR_POST_ACCIDENT_WINDOW_MISSED` | 409 Conflict |
| `ERR_COOLING_OFF_ACTIVE` | 409 Conflict |
| `ERR_AUDIT_SCHEDULED_PAST_DUE` | 409 Conflict |
| `ERR_AUDIT_BEFORE_SCHEDULED_DATE` | 409 Conflict |
| `ERR_PERIOD_NOT_ENDED` | 409 Conflict |
| `ERR_CLOCK_REGRESSION` | 409 Conflict |
| `ERR_DUPLICATE_DOT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_CATEGORY_CODE` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_TESTING_PERIOD` | 409 Conflict |
| `ERR_OPEN_UPGRADE_REQUEST_EXISTS` | 409 Conflict |
| `ERR_AUDIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_POLICY_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_REMAND_LIMIT_REACHED` | 409 Conflict |
| `ERR_VERDICT_RESULT_MISMATCH` | 409 Conflict |
| `ERR_CYCLE_ALREADY_RUN_TODAY` | 409 Conflict |
| `ERR_DRIVER_CARRIER_MISMATCH` | 409 Conflict |
| `ERR_OPEN_CHALLENGES_BLOCK_FINALIZE` | 409 Conflict |
| `ERR_AUDIT_HOLD_ACTIVE` | 409 Conflict |
| `ERR_AUDIT_READINESS_INCOMPLETE` | 409 Conflict |
| `ERR_REINSTATE_REQUIREMENTS_UNMET` | 409 Conflict |
| `ERR_AUDIT_TYPE_NOT_APPLICABLE` | 409 Conflict |
| `ERR_RATING_NOT_UPGRADABLE` | 409 Conflict |
| `ERR_CORRECTIVE_ACTION_NOT_APPLICABLE` | 409 Conflict |
