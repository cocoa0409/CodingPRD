# Performance Review & Compensation Planning API — Product Requirements Document

## 1. Introduction

Annual and semi-annual performance review seasons stretch a company's HR fabric thin. Direct managers must turn months of project context into defensible ratings, peers must contribute 360-degree feedback without becoming reviewers for their own files, HR business partners must run department-level calibration sessions that produce a defensible bell curve, and a separate set of compensation approvers must convert all of that into salary and equity decisions that fit a finite budget. The cost of getting any one stage wrong is high: a forgotten Performance Improvement Plan paperwork loop becomes a wrongful-termination claim; a careless approval over-spends the merit pool by six figures; a manager who quietly approves their own report's promotion vaporises the company's segregation-of-duties story to the auditors.

The Performance Review & Compensation Planning API is the single back-end of record that drives all four stages — goal-setting, 360 feedback, calibration, and compensation planning — through one cycle-scoped workflow. It treats each cycle as a durable container with its own bell-curve target, merit pool, and equity refresh pool; it routes every state change through a tightly scoped role model so that the manager who proposes never approves and the HR facilitator who calibrates never manages a case in the same session; and it pins every compensation decision to a specific review-case revision so that a late-arriving correction invalidates compensation work cleanly instead of silently rewriting history. The system is designed for deterministic auditability: an append-only ledger captures every cross-aggregate side effect — every cascade from a calibration commit, every budget debit at approval, every PIP transition — with the actor, payload digest, and server clock at the moment of action.

This document specifies the API's resource model, lifecycle, calculations, validation discipline, and HTTP surface. The intended reader is a backend engineer implementing the API from scratch; everything required to satisfy the conformance suite is stated here.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is absent the request is rejected with `ERR_AUTH_REQUIRED` and HTTP 401. If `X-User-Role` carries a value that is not one of `Admin`, `HRBP`, `Manager`, `Reviewer`, or `Approver`, the request is rejected with `ERR_INVALID_ROLE` and HTTP 401. When the role is valid but the endpoint is not authorised for that role under §4, the request is rejected with `ERR_ROLE_FORBIDDEN` and HTTP 403.

Five roles participate in this system. The `Admin` role is the platform operator: it manages employees, queries the audit log, and drives the logical clock for tests. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `actor_user_id` on the audit ledger) but does not compare it to any entity's `id`. The remaining four roles — `HRBP`, `Manager`, `Reviewer`, and `Approver` — are all entity-backed: when `X-User-Role` carries one of those four values, `X-User-ID` is the `id` of the acting `Employee`, and ownership checks on any resource that references an `Employee` (manager checks on a `ReviewCase`, reviewer checks on a `FeedbackRequest`, approver-vs-manager segregation checks on a `CompPlan`) compare the resource's foreign-key field to `X-User-ID`. `HRBP` owns the cycle lifecycle, calibration, and PIP processing. `Manager` is the direct manager of the subject under review and drives the review-case authoring flow. `Reviewer` submits 360 feedback. `Approver` finalises compensation and must be a different person from the case's manager.

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

List endpoints accept two optional query parameters, `limit` and `offset`. The default `limit` is 10; the minimum accepted value is 1, and the maximum accepted value is 100. The default `offset` is 0. List responses are sorted by `created_at` ascending. The `meta` object for list responses surfaces four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every persistent resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp set at insertion. The bulk of the domain — `Employee`, `Cycle`, `ReviewCase`, `Goal`, `CalibrationSession`, `PIPCase`, `CompPlan` — additionally carries `updated_at`, refreshed on every mutation, and `version`, a non-negative integer that starts at zero and increments by one on every mutation. `FeedbackRequest` and `AuditEvent`, on the other hand, are append-only ledgers: both carry only `id` and `created_at`, with no `updated_at` and no `version` (their lifecycle progresses through additive operations only). All timestamps are ISO 8601 UTC with three fractional digits.

### 2.5. Nested Resource Addressing

Resources are addressed through nested URLs that mirror the parent-child hierarchy: cycles contain review cases, calibration sessions, comp plans, and PIP cases; review cases contain goals and feedback requests. When a request carries multiple path parameters — for example a calibration session under a cycle — they are validated left-to-right. If `cycle_id` does not resolve to a known cycle, the response is `ERR_CYCLE_NOT_FOUND` with HTTP 404 and no further checks run. If the cycle exists but the `review_case_id` under it does not, the response is `ERR_REVIEW_CASE_NOT_FOUND` (HTTP 404). If the cycle exists but the `calibration_session_id` under it does not, the response is `ERR_CALIBRATION_SESSION_NOT_FOUND` (HTTP 404). For any other dangling path parameter — `comp_plan_id`, `pip_case_id`, `goal_id`, `feedback_request_id`, or `employee_id` — the response is the generic `ERR_NOT_FOUND` (HTTP 404). When a foreign key embedded in a request body (such as `manager_employee_id`, `subject_employee_id`, `reviewer_employee_id`, `triggering_review_case_id`, or `facilitator_employee_id`) refers to a record the server cannot find, the response is `ERR_REFERENCE_NOT_FOUND` with HTTP 404.

### 2.6. Optimistic Concurrency Control

Mutating endpoints — every `PATCH`, primarily — accept an optional `version` field in the request body. When the client omits `version`, the server performs the mutation without an equality check. When the client supplies a `version`, the server compares it against the current entity's `version`; if they differ, the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409) and no state changes. Every successful mutation increments the entity's `version` by one and refreshes its `updated_at`. This per-entity `version` is distinct from the version-pinning machinery on `CompPlan`, described in §2.10.

### 2.7. Validation Priority Order

When more than one rule could fail on the same request, the server evaluates rules in the following fixed order and emits the error from the first failing rule. Authentication runs first: header presence (`ERR_AUTH_REQUIRED`) precedes role-value validity (`ERR_INVALID_ROLE`), which precedes role-vs-endpoint authorisation (`ERR_ROLE_FORBIDDEN`). Existence checks come next, starting with the outer `cycle_id` and walking inward through nested path parameters as described in §2.5, and finally any body-level foreign key. State checks come after existence: the relevant `Cycle.status` gate runs before the per-entity transition state check. Business-safety rules — the PIP guard on promotion, the calibration facilitator conflict, the approver-is-manager conflict, the promotion step constraint — run before referential rules. The compensation pin-equality check on `pinned_review_case_version` is itself a referential rule and is positioned **above** the merit budget guard: when a proposed plan would both be stale and exceed budget, the server emits `ERR_PINNED_REVIEW_STALE` rather than `ERR_MERIT_BUDGET_EXCEEDED`. Likewise, the PIP-promotion safety guard sits **above** the budget guard: an `ON_PIP` employee whose draft plan also exceeds budget produces `ERR_PROMO_BLOCKED_BY_PIP`, not `ERR_MERIT_BUDGET_EXCEEDED`. Business-constraint rules (goal-weight closure, peer-feedback floor, revision cap, bell-curve compliance, calibration coverage, PIP ends-at gating, email uniqueness) follow. Fiscal rules (merit budget and equity pool) run after every other check has passed. Temporal-window and shape rules (review window inequality, bell-curve target shape) and finally the optimistic-concurrency check on `PATCH` close out the chain.

### 2.8. Cycle-Scoped Ledger Invariants

Two running totals on `Cycle` — `merit_budget_consumed_cents` and `equity_pool_consumed_units` — are the canonical record of how much of the cycle's authorised merit pool and equity refresh pool has already been committed. They start at zero, increase by `merit_increase_cents` and `equity_refresh_units` respectively when a `CompPlan` is approved, and decrease by the same amounts when an approved plan is later recalled while the cycle is still in compensation planning. For any approve/recall pair on the same plan, both totals must equal the values they held immediately before the approve — compensating release is exact, not lossy. The fiscal gate at approval is two-sided: a plan can only move to `APPROVED` if `merit_budget_consumed_cents` plus its own `merit_increase_cents` is less than or equal to `merit_budget_cents` (otherwise `ERR_MERIT_BUDGET_EXCEEDED`), and `equity_pool_consumed_units` plus its own `equity_refresh_units` is less than or equal to `equity_refresh_pool_units` (otherwise `ERR_EQUITY_POOL_EXHAUSTED`). Cycle closure additionally requires the two totals to remain within their authorised pools.

### 2.9. Precision and Rounding

All money figures are stored in integer cents. The merit calculation floors at each multiplication step, never accumulating fractional cents. The bell-curve compliance check floors observed bucket percentages before comparing them to the target. The weighted goal score is stored at two decimal places, rounded half-up. The equity refresh calculation applies its multiplier first and rounds the multiplied base to a whole number of units, half-up, before the promotion bump (itself an integer floor of a separate product) is added — the canonical order is "multiplier-then-round, then add the already-rounded bump", not "sum-then-round".

### 2.10. Version-Pinning on Compensation Plans

A `CompPlan` is created against a single `FINALIZED` `ReviewCase` and captures three snapshots at creation time: `pinned_review_case_id` (the case's `id`), `pinned_review_case_version` (the case's `version` at that instant), and `pinned_base_salary_cents` (the subject's current `base_salary_cents`). On both the propose and approve transitions the server compares the plan's `pinned_review_case_version` against the underlying `ReviewCase.version`; if they differ, the transition is rejected with `ERR_PINNED_REVIEW_STALE` (HTTP 409). This is the serialisation point between a late correction to a review case (which bumps the case's `version`) and a compensation decision that was drafted against the older state. Because §2.7 places this referential check above the fiscal check, a stale pin is surfaced before any budget conversation.

### 2.11. Segregation of Duties

Two non-overlap rules apply across roles. First, the calibration facilitator: a `CalibrationSession`'s `facilitator_employee_id` must not equal the `manager_employee_id` of any `ReviewCase` whose subject belongs to that session's `department`. Violations at session creation, start, or commit all surface as `ERR_FACILITATOR_CONFLICT` with HTTP 422. Second, the compensation approver: when an `Approver` acts on a `CompPlan` (approve, reject, or recall), the acting `X-User-ID` must not equal the `manager_employee_id` snapshotted on the plan's pinned `ReviewCase`; otherwise `ERR_APPROVER_IS_MANAGER` with HTTP 422.

### 2.12. Audit Trail

Every state-changing operation appends one record to the immutable audit ledger. Each record captures the `actor_role` and the `actor_user_id` at the moment of the action, the affected `entity_type` and `entity_id`, the verb `action` (for example `review_case.submit`, `calibration_session.commit`, `comp_plan.approve`), a SHA-256 `payload_hash` of the request body in hexadecimal, and the `occurred_at` server clock time. The ledger is queryable but never editable.

### 2.13. Logical Clock for Testability

The server exposes an admin-only test-driving capability that advances its logical clock to a supplied `to_datetime`. The clock only moves forward — earlier values are rejected. The clock is the source of truth for any check that compares the current time to a stored timestamp, in particular the PIP elapsed-time gate (`ends_at`).

## 3. Business Logic & Workflows

### 3.1. Employee Roster and Termination

An `Employee` enters the system through an Admin or HRBP creation call that supplies `full_name` (between 1 and 200 characters inclusive), `email`, `department`, `job_level` (an integer between 1 and 10 inclusive), an optional `manager_employee_id`, `base_salary_cents` (strictly positive), an optional `equity_units_outstanding` (defaulting to 0 and never negative), and `hire_date`. The new record begins with `status` set to `ACTIVE`. Email uniqueness is scoped to live employees: two employees may not share an `email` if both have `status` in the set `{ACTIVE, ON_PIP}`; a collision is reported as `ERR_EMAIL_TAKEN`. The `manager_employee_id` field is self-referential: it must point at an existing `Employee` whose status is `ACTIVE` or `ON_PIP`, and it may never equal the employee's own `id`.

Mutable employee fields — `department`, `manager_employee_id`, and `base_salary_cents` — can be edited by an Admin or HRBP through the employee patch endpoint, which also accepts the optional `version` for optimistic concurrency. Terminating an employee is a dedicated admin/HRBP capability that flips `status` to `TERMINATED`. Termination cascades into open performance work: any `ACTIVE` `PIPCase` for that subject in any cycle is force-closed via the withdraw transition (returning the employee briefly to `ACTIVE` before the termination overwrite), and any `DRAFT` or `PROPOSED` `CompPlan` for that subject in the cycle moves to `REJECTED`.

### 3.2. Cycle Lifecycle

A cycle is created in `OPEN` status by an HRBP or Admin, who supplies a display `name`, a `cadence` of either `ANNUAL` or `SEMI_ANNUAL`, the `review_window_start` and `review_window_end` instants (the end must be strictly after the start, otherwise `ERR_TIME_WINDOW_INVALID`), the `bell_curve_target`, the `merit_budget_cents`, and the `equity_refresh_pool_units`. The `bell_curve_target` is an object with exactly five keys — `OUTSTANDING`, `EXCEEDS`, `MEETS`, `NEEDS_IMPROVEMENT`, and `UNSATISFACTORY` — each holding an integer percentage between 0 and 100 inclusive, with the five values summing to exactly 100; any deviation produces `ERR_BELL_CURVE_TARGET_INVALID`. The `merit_budget_cents` must be at least zero, as must the `equity_refresh_pool_units`. At creation the two consumption totals `merit_budget_consumed_cents` and `equity_pool_consumed_units` are zero. Edits via the cycle patch endpoint may revise `name`, `bell_curve_target`, `merit_budget_cents`, `equity_refresh_pool_units`, `review_window_start`, and `review_window_end` (subject to the same shape and ordering rules), and may carry the optional `version` for concurrency.

The cycle is the gating posture for every child operation. While the cycle is `OPEN`, review-case authoring, goal editing, and feedback-request work are all permitted; once the cycle leaves `OPEN`, any further mutation on those child resources is rejected with `ERR_CYCLE_NOT_OPEN`. The cycle moves to `IN_CALIBRATION` when an HRBP locks reviews: this is permitted only while the cycle is `OPEN` and only when every `ReviewCase` under it is either in `SUBMITTED` or `RETURNED` (or has been waived); the cascade carries every `SUBMITTED` case to `LOCKED`, refreshes the cycle's `updated_at`, and bumps its `version`. Calibration commits flip the cycle into `COMP_PLANNING` once the last department's session has been committed; preconditions are that every `CalibrationSession` on the cycle has status `COMMITTED` (with no `SCHEDULED` or `IN_SESSION` sessions remaining) and that every locked case has received a `final_rating`. Finally, an HRBP closes the cycle, transitioning it to `CLOSED`, but only after every `CompPlan` on the cycle is in `APPROVED` or `REJECTED`, `merit_budget_consumed_cents` is at most `merit_budget_cents`, and `equity_pool_consumed_units` is at most `equity_refresh_pool_units`. Closure is itself a cascade: every `APPROVED` `CompPlan` with `merit_increase_cents` greater than zero adds that amount to the subject's `base_salary_cents`; every plan with `equity_refresh_units` greater than zero adds those units to the subject's `equity_units_outstanding`; every plan with `promotion_to_level` set rewrites the subject's `job_level` to that value. The cycle's `updated_at` is refreshed and its `version` incremented.

A locked-vs-still-open race must serialise cleanly. If a manager attempts to submit a case at the same moment an HRBP attempts to lock the cycle, exactly one of the two reaches `IN_CALIBRATION`: either the submit completes against an `OPEN` cycle and the lock then proceeds against the updated set, or the lock completes against the unchanged set and the submit fails with `ERR_CYCLE_NOT_OPEN` (HTTP 409). The system never produces a partial result.

### 3.3. Review-Case Authoring

A `ReviewCase` is opened by an HRBP or Manager. The creator supplies only `subject_employee_id`; the server pins `cycle_id` from the URL, snapshots the subject's current manager into the case's own `manager_employee_id`, and seeds the case in `DRAFT` status. Only one case may exist per `(cycle_id, subject_employee_id)`. The subject must be an `Employee` whose status is `ACTIVE` or `ON_PIP`. The case's other computed counters — `weighted_goal_score`, `peer_feedback_count`, and `revision_count` — all start at zero.

Goals are children of the review case. A Manager adds a `Goal` by supplying `title` (between 1 and 500 characters), `weight` (an integer between 1 and 100 inclusive), and optionally `self_score` and `manager_score` (each an integer between 1 and 5 inclusive). Goal edits may also be made by a Reviewer (only against the `self_score` of their own subject case); goal deletion is restricted to the Manager and is permitted only while the parent case is in `DRAFT` or `RETURNED`. Whenever a goal's `manager_score` or `weight` changes, the parent case's `weighted_goal_score` is recomputed: the score is the sum over all goals of each goal's `weight` multiplied by its `manager_score`, divided by 100, with the result rounded half-up to two decimal places, evaluating goals in ascending `created_at` order for determinism. The collected `self_score` is captured but does not appear in this canonical score. (When a draft case is viewed before every goal has its manager score, the system may surface a provisional variant of the score that substitutes `self_score` for any goal whose `manager_score` is null — same weight-by-score sum, same division by 100, same half-up two-decimal rounding — which will produce a different number from the canonical formula on any case with at least one unsubmitted manager score; this provisional figure is for in-progress visibility only.)

A Manager submits the case once it is complete. Submission requires every one of the following: the cycle is still `OPEN`, the case's `manager_rating` is set (a value from the set `{OUTSTANDING, EXCEEDS, MEETS, NEEDS_IMPROVEMENT, UNSATISFACTORY}`), the sum of `weight` across the case's goals equals 100 (otherwise `ERR_GOAL_WEIGHTS_INVALID`), every goal has both `self_score` and `manager_score` in the integer range 1 to 5, and the case has at least two `SUBMITTED` feedback requests as measured by `peer_feedback_count` (otherwise `ERR_PEER_FEEDBACK_INSUFFICIENT`). On a successful submit, `weighted_goal_score` is recomputed, `updated_at` is refreshed, and `version` is incremented; the case moves `DRAFT → SUBMITTED`. If two managers attempt the same submit simultaneously, exactly one wins; the loser sees `ERR_INVALID_STATE` (HTTP 409) because the case has already advanced.

An HRBP returns a submitted case to its author with the return transition; this is permitted only while the cycle is still `OPEN` and the case's `revision_count` is strictly less than 3. The transition advances the case `SUBMITTED → RETURNED`, increments `revision_count` by 1, refreshes `updated_at`, and bumps `version`. A fourth return is refused with `ERR_REVISION_LIMIT`. The Manager then reopens the case (`RETURNED → DRAFT`) — which requires the cycle to still be `OPEN`, refreshes `updated_at`, and bumps `version` — to make further edits. Up to three full return-reopen revision loops are therefore possible before the case must stand.

### 3.4. 360-Degree Feedback

A 360 feedback request is opened by the Manager or HRBP, who supplies `reviewer_employee_id` and `relation` (one of `PEER`, `UPWARD`, `DOWNWARD`, or `CROSS_FUNCTIONAL`). The request begins in `PENDING`. Self-review is forbidden: the `reviewer_employee_id` may not equal the parent case's `subject_employee_id`, and a violation yields `ERR_SELF_FEEDBACK_FORBIDDEN`. Because `FeedbackRequest` is an append-only ledger, it carries only `id` and `created_at`; the `submitted_at` field is null while pending or declined and is set to the server clock at the moment of submission.

A request advances to `SUBMITTED` only when the acting reviewer is the same person as the request's `reviewer_employee_id`, the parent case is in `DRAFT` or `RETURNED`, and the supplied `narrative` is at least 50 and at most 5000 characters in length. On submission, `submitted_at` is set to the current clock, the parent case's `peer_feedback_count` is incremented by 1, and the case's `updated_at` is refreshed and `version` incremented. A reviewer may instead decline; declining is permitted whenever the acting reviewer is the request's own `reviewer_employee_id`, leaves the request at `DECLINED` with no narrative captured, and emits an audit event without bumping the (absent) `version` of the request itself. If the same reviewer races their own submit against itself, exactly one reaches `SUBMITTED`; the second sees `ERR_INVALID_STATE` (HTTP 409).

### 3.5. Calibration Sessions

Once the cycle has been locked into `IN_CALIBRATION`, HRBPs run department-level calibration. An HRBP creates a `CalibrationSession` by supplying `department` and `facilitator_employee_id`; sessions are unique per `(cycle_id, department)` and begin in `SCHEDULED`. The chosen facilitator must not be the manager of any case whose subject sits in that department, or session creation fails with `ERR_FACILITATOR_CONFLICT`. The session's `proposed_ratings` array is empty at creation, the `bell_curve_distribution` is an object of five zero-valued buckets keyed by the five rating values, and `committed_at` is null.

As the calibration committee works, an HRBP pushes proposed ratings into the session through a full-replacement patch on the proposals resource. Each call replaces `proposed_ratings` in its entirety with an ordered list of `{review_case_id, proposed_rating}` pairs and immediately recomputes `bell_curve_distribution`: for each of the five buckets, the bucket count is the number of pairs whose `proposed_rating` equals that bucket. The session moves `SCHEDULED → IN_SESSION` on a dedicated start call (permitted only while the cycle is `IN_CALIBRATION` and only when the facilitator-conflict rule still holds).

Commit is the heart of the calibration system. Three preconditions must all hold: the cycle is still `IN_CALIBRATION`; every locked `ReviewCase` whose subject's `department` matches the session's `department` appears in `proposed_ratings` exactly once (otherwise `ERR_CALIBRATION_COVERAGE`); and the bell-curve compliance check passes (otherwise `ERR_BELL_CURVE_VIOLATED`). Compliance is evaluated by computing, for each of the five buckets, the observed percentage as the floor of 100 times the bucket's count divided by the total length of `proposed_ratings`, then comparing each observed percentage against the corresponding key in the cycle's `bell_curve_target`. Every bucket's absolute difference between observed and target percentage points must be at most 5; any bucket exceeding the 5-percentage-point tolerance fails compliance. Floor-based observation is canonical: 7 out of 24 is treated as 29 percent, 4 out of 24 is treated as 16 percent, and so on — implementations that round half-up before comparing will diverge from the canonical contract at the boundary.

A successful commit drives a three-hop cascade. First, each `ReviewCase` named in `proposed_ratings` transitions `LOCKED → FINALIZED` with its `final_rating` set to the proposed value; the case's `updated_at` is refreshed and `version` incremented. Second, any newly `FINALIZED` case whose `final_rating` is `NEEDS_IMPROVEMENT` or `UNSATISFACTORY` triggers automatic creation of a `PIPCase` in `ACTIVE` status for that subject. Third, the subject's `Employee.status` flips from `ACTIVE` to `ON_PIP`. The session's `committed_at` is set to the current server clock. When this commit is the last outstanding session on the cycle, the cycle itself transitions from `IN_CALIBRATION` to `COMP_PLANNING` as a consequence of the same request. An HRBP may instead abandon a session: from `SCHEDULED` while the cycle is `OPEN` or `IN_CALIBRATION`, abandonment removes the session from the calibration set so that its subjects fall through to a default rating equal to their `manager_rating` when locking next runs; from `IN_SESSION`, abandonment is unconditional and leaves the session at `ABANDONED` with no further side effects.

### 3.6. Performance Improvement Plans

A `PIPCase` is created (in `ACTIVE`) for any subject whose calibrated `final_rating` is `NEEDS_IMPROVEMENT` or `UNSATISFACTORY`. The triggering case's `id` is captured as `triggering_review_case_id`; the case must itself be in `FINALIZED` and its `final_rating` must indeed be one of those two values. Each PIP is unique per `(cycle_id, subject_employee_id)`: a second creation attempt against the same pair is rejected with `ERR_PIP_ALREADY_EXISTS` and HTTP 409. The PIP's duration is server-pinned by the triggering rating — 60 days when the triggering rating is `NEEDS_IMPROVEMENT`, and 30 days when it is `UNSATISFACTORY` — and stored as `duration_days`. The `starts_at` field is the server clock at PIP creation, and `ends_at` is `starts_at` plus `duration_days` multiplied by 86,400 seconds.

A PIP closes through one of three operator actions, each restricted to HRBP. Marking a PIP `PASSED` is permitted only after the logical clock has reached or passed `ends_at` (otherwise `ERR_PIP_NOT_ELAPSED`); the subject's `Employee.status` flips from `ON_PIP` back to `ACTIVE`, and an audit event is logged. Marking a PIP `FAILED` is also permitted only after `ends_at` has elapsed; the subject's status flips from `ON_PIP` to `TERMINATED`, and the failure additionally cascades into compensation work: any `DRAFT` or `PROPOSED` `CompPlan` for that subject in this cycle automatically transitions to `REJECTED`. The third option, withdrawal, is the inverse — it is permitted only while the clock has not yet reached `ends_at`; the subject's status flips from `ON_PIP` back to `ACTIVE`. The three closure operations are sibling branches and are policed by the same state precondition: the PIP must be in `ACTIVE`, with any out-of-state attempt returning `ERR_INVALID_STATE`.

### 3.7. Compensation Plans

Compensation planning runs against the cycle in `COMP_PLANNING`. A Manager or HRBP creates a `CompPlan` by supplying `subject_employee_id` and an optional `promotion_to_level`. The server identifies the `FINALIZED` `ReviewCase` whose `subject_employee_id` matches, pins it via `pinned_review_case_id` and `pinned_review_case_version` (the case's current `version` at this instant), pins the subject's current `base_salary_cents` into `pinned_base_salary_cents`, and computes `merit_increase_cents` and `equity_refresh_units` from the rules below. The plan begins in `DRAFT` with `approved_at` null. The plan is unique per `(cycle_id, subject_employee_id)`.

The merit increase is computed by table lookup followed by an optional promotion bump and a final PIP gate. The base merit percentage is drawn from a row chosen by `Cycle.cadence` and a column chosen by the pinned `ReviewCase.final_rating`. For `ANNUAL` cadence the base table is: `OUTSTANDING` returns 9 percent, `EXCEEDS` returns 6 percent, `MEETS` returns 3 percent, and both `NEEDS_IMPROVEMENT` and `UNSATISFACTORY` return 0 percent. For `SEMI_ANNUAL` cadence every cell of that table is divided by 2 using integer division of cents — that is, by taking the floor — so each cycle's effective base percentage is half of the annual figure rounded down. The raw merit amount in cents is the floor of `pinned_base_salary_cents` multiplied by the selected percentage divided by 100. If the plan carries a `promotion_to_level` set to exactly one above the subject's current `job_level` and the pinned rating is `OUTSTANDING` or `EXCEEDS`, an additional promotion bump is added to the raw amount: the floor of `pinned_base_salary_cents` multiplied by 5 divided by 100. Finally, the PIP gate overrides everything: if the subject's `Employee.status` is `ON_PIP` at the moment of propose or approve, `merit_increase_cents` is forced to zero regardless of rating, base salary, or promotion setting.

The equity refresh is computed from a level-banded base grant, a cadence multiplier, an optional promotion bump using the next level's grant, and the same PIP gate. The base grant table is keyed by the subject's `job_level` band and by the pinned `final_rating`. For job levels 1 through 3, the row is: `OUTSTANDING` 200 units, `EXCEEDS` 100 units, `MEETS` 50 units, `NEEDS_IMPROVEMENT` 0 units, `UNSATISFACTORY` 0 units. For job levels 4 through 6, the row is: `OUTSTANDING` 600, `EXCEEDS` 300, `MEETS` 150, `NEEDS_IMPROVEMENT` 0, `UNSATISFACTORY` 0. For job levels 7 through 10, the row is: `OUTSTANDING` 1500, `EXCEEDS` 800, `MEETS` 400, `NEEDS_IMPROVEMENT` 0, `UNSATISFACTORY` 0. The cadence multiplier is exactly 1.0 for `ANNUAL` and exactly 0.5 for `SEMI_ANNUAL`. The canonical evaluation order is: first multiply the looked-up base grant by the cadence multiplier and round that product to a whole number of units, half-up; then, if the plan carries a `promotion_to_level` set to current `job_level` plus one and the pinned rating is `OUTSTANDING` or `EXCEEDS`, compute the promotion bump as the floor of 0.25 times the next level's grant for the same rating (using the grant table row for `promotion_to_level`, not the current level), and add the already-rounded bump to the already-rounded base. Finally, if the subject's `Employee.status` is `ON_PIP`, the result is forced to zero. The "multiply then round, then add the bump" order is binding: any "sum then round" implementation produces a different number whenever the multiplier introduces a fractional half-unit (for example, level 4 with `EXCEEDS`, `SEMI_ANNUAL`, and a promotion bump yields a base contribution of 150 units and a promotion contribution of 75 units, for a canonical total of 225).

A Manager or HRBP can edit the plan's `promotion_to_level` while it is still in `DRAFT` (the patch endpoint accepts an optional `version` for concurrency); any such edit recomputes `merit_increase_cents` and `equity_refresh_units`. The promotion field is policed by two business-safety rules. First, it must equal the subject's current `job_level` plus exactly 1 — strictly one rung at a time, no skips — otherwise `ERR_PROMO_STEP_INVALID`. Second, it may not be set while the subject is `ON_PIP`, otherwise `ERR_PROMO_BLOCKED_BY_PIP`. Because the PIP-promotion guard is positioned above the budget guard in the validation order, an `ON_PIP` employee whose plan would also exceed budget surfaces `ERR_PROMO_BLOCKED_BY_PIP` rather than `ERR_MERIT_BUDGET_EXCEEDED`.

A Manager or HRBP proposes the plan (`DRAFT → PROPOSED`) once they are satisfied with the figures; this requires that the cycle is `COMP_PLANNING`, the subject's `Employee.status` is `ACTIVE` or `ON_PIP`, and the plan's pinned `ReviewCase.version` still matches the case's current `version`. Proposing recomputes `merit_increase_cents` and `equity_refresh_units`, refreshes `updated_at`, and bumps `version`.

Approval is performed by an `Approver` who is not the case's manager. Approval succeeds only when every one of the following holds: the cycle is still `COMP_PLANNING`; the pinned `ReviewCase.version` still equals the case's current `version`; the acting `X-User-ID` is not the `manager_employee_id` on the pinned `ReviewCase` (otherwise `ERR_APPROVER_IS_MANAGER`); if `promotion_to_level` is set, the subject's `Employee.status` is `ACTIVE` (a promotion cannot be approved while `ON_PIP`); the cycle's `merit_budget_consumed_cents` plus this plan's `merit_increase_cents` is less than or equal to `merit_budget_cents`; and the cycle's `equity_pool_consumed_units` plus this plan's `equity_refresh_units` is less than or equal to `equity_refresh_pool_units`. On success, `merit_budget_consumed_cents` increases by `merit_increase_cents`, `equity_pool_consumed_units` increases by `equity_refresh_units`, `approved_at` is set to the server clock, `updated_at` is refreshed, and `version` is incremented. Rejection from `PROPOSED` is the symmetric sibling: it is permitted whenever the cycle is `COMP_PLANNING`, refreshes `updated_at`, and bumps `version`, but it does not move the budget or pool. An already-approved plan can be recalled (`APPROVED → REJECTED`) by an `Approver` while the cycle is still `COMP_PLANNING` — never after closure — and recall is the exact compensating action: `merit_budget_consumed_cents` decreases by `merit_increase_cents`, `equity_pool_consumed_units` decreases by `equity_refresh_units`, and the plan's `updated_at` and `version` are refreshed. The approver-is-manager segregation check applies to all three actions — approve, reject, and recall — so a manager can never sneak a self-approval through any of those doors.

Two budget races are explicit. When two approves on different plans both compete for the last of `merit_budget_cents`, at most one succeeds; the loser is rejected with `ERR_MERIT_BUDGET_EXCEEDED` (HTTP 422), serialised on the monotonic guard `merit_budget_consumed_cents`. Symmetrically, when two approves compete for the last of `equity_refresh_pool_units`, at most one succeeds; the loser is rejected with `ERR_EQUITY_POOL_EXHAUSTED` (HTTP 422), serialised on `equity_pool_consumed_units`. A third race compares an approve against a concurrent return on the same case: the return bumps the case's `version`, and the approve evaluated against the now-stale pin is rejected with `ERR_PINNED_REVIEW_STALE` (HTTP 409). And a fourth race is on PIP creation itself: two attempts to create a PIP for the same `(cycle_id, subject_employee_id)` serialise to one winner, the loser receiving `ERR_PIP_ALREADY_EXISTS` (HTTP 409).

### 3.8. Audit Queries and Clock Control

An Admin or HRBP queries the audit ledger to reconstruct any history of side effects; queries may be filtered by `entity_type`, `entity_id`, `action`, or `actor_user_id`. Only Admin operators may advance the logical clock by supplying `to_datetime`; the clock only moves forward, and the post-advance value is returned to the caller. Clock advances are themselves logged.

## 4. Endpoint Definitions

Resource creation calls return HTTP 201; all other mutations and reads return HTTP 200, except for goal deletion which returns HTTP 204. Request bodies, response payloads, and side effects are described in §3 — implementers should refer to the narrative for the full request/response semantics; this table is a directory only.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST   | `/employees` | Create an Employee. | Admin, HRBP |
| GET    | `/employees` | List employees with status, department, and manager filters. | Admin, HRBP, Manager, Approver |
| GET    | `/employees/{employee_id}` | Read an Employee. | Admin, HRBP, Manager, Approver, Reviewer |
| PATCH  | `/employees/{employee_id}` | Update mutable Employee fields. | Admin, HRBP |
| POST   | `/employees/{employee_id}/terminate` | Terminate an Employee. | Admin, HRBP |
| POST   | `/cycles` | Create a Cycle. | HRBP, Admin |
| GET    | `/cycles` | List cycles. | HRBP, Admin, Manager, Approver |
| GET    | `/cycles/{cycle_id}` | Read a Cycle. | HRBP, Admin, Manager, Approver, Reviewer |
| PATCH  | `/cycles/{cycle_id}` | Edit mutable Cycle fields. | HRBP, Admin |
| POST   | `/cycles/{cycle_id}/lock-reviews` | Lock all submitted review cases and move the cycle to calibration. | HRBP |
| POST   | `/cycles/{cycle_id}/close` | Close the cycle and apply compensation cascades. | HRBP |
| POST   | `/cycles/{cycle_id}/review-cases` | Create a ReviewCase for a subject. | HRBP, Manager |
| GET    | `/cycles/{cycle_id}/review-cases` | List ReviewCases. | HRBP, Manager, Approver |
| GET    | `/cycles/{cycle_id}/review-cases/{review_case_id}` | Read a ReviewCase. | HRBP, Manager, Approver, Reviewer |
| PATCH  | `/cycles/{cycle_id}/review-cases/{review_case_id}` | Edit ReviewCase fields. | Manager |
| POST   | `/cycles/{cycle_id}/review-cases/{review_case_id}/submit` | Submit the case for review. | Manager |
| POST   | `/cycles/{cycle_id}/review-cases/{review_case_id}/return` | Return the case to its drafter. | HRBP |
| POST   | `/cycles/{cycle_id}/review-cases/{review_case_id}/reopen` | Reopen a returned case for further edits. | Manager |
| POST   | `/cycles/{cycle_id}/review-cases/{review_case_id}/goals` | Add a Goal to a ReviewCase. | Manager |
| PATCH  | `/cycles/{cycle_id}/review-cases/{review_case_id}/goals/{goal_id}` | Edit a Goal. | Manager, Reviewer |
| DELETE | `/cycles/{cycle_id}/review-cases/{review_case_id}/goals/{goal_id}` | Remove a Goal. | Manager |
| POST   | `/cycles/{cycle_id}/review-cases/{review_case_id}/feedback-requests` | Open a 360 feedback request. | Manager, HRBP |
| POST   | `/cycles/{cycle_id}/review-cases/{review_case_id}/feedback-requests/{feedback_request_id}/submit` | Submit feedback. | Reviewer |
| POST   | `/cycles/{cycle_id}/review-cases/{review_case_id}/feedback-requests/{feedback_request_id}/decline` | Decline feedback. | Reviewer |
| POST   | `/cycles/{cycle_id}/calibration-sessions` | Create a calibration session for a department. | HRBP |
| PATCH  | `/cycles/{cycle_id}/calibration-sessions/{calibration_session_id}/proposals` | Set or replace proposed ratings (full replacement). | HRBP |
| POST   | `/cycles/{cycle_id}/calibration-sessions/{calibration_session_id}/start` | Start the session. | HRBP |
| POST   | `/cycles/{cycle_id}/calibration-sessions/{calibration_session_id}/commit` | Commit the session and finalise every covered case. | HRBP |
| POST   | `/cycles/{cycle_id}/calibration-sessions/{calibration_session_id}/abandon` | Abandon the session. | HRBP |
| GET    | `/cycles/{cycle_id}/pip-cases` | List PIP cases. | HRBP, Admin, Manager |
| GET    | `/cycles/{cycle_id}/pip-cases/{pip_case_id}` | Read a PIP case. | HRBP, Admin, Manager |
| POST   | `/cycles/{cycle_id}/pip-cases/{pip_case_id}/pass` | Mark a PIP passed. | HRBP |
| POST   | `/cycles/{cycle_id}/pip-cases/{pip_case_id}/fail` | Mark a PIP failed. | HRBP |
| POST   | `/cycles/{cycle_id}/pip-cases/{pip_case_id}/withdraw` | Withdraw a PIP early. | HRBP |
| POST   | `/cycles/{cycle_id}/comp-plans` | Create a CompPlan against a finalized review case. | Manager, HRBP |
| GET    | `/cycles/{cycle_id}/comp-plans` | List CompPlans on a cycle. | HRBP, Approver, Manager |
| GET    | `/cycles/{cycle_id}/comp-plans/{comp_plan_id}` | Read a CompPlan. | HRBP, Approver, Manager |
| PATCH  | `/cycles/{cycle_id}/comp-plans/{comp_plan_id}` | Edit promotion target on a draft plan. | Manager, HRBP |
| POST   | `/cycles/{cycle_id}/comp-plans/{comp_plan_id}/propose` | Propose the plan. | Manager, HRBP |
| POST   | `/cycles/{cycle_id}/comp-plans/{comp_plan_id}/approve` | Approve the plan. | Approver |
| POST   | `/cycles/{cycle_id}/comp-plans/{comp_plan_id}/reject` | Reject the plan. | Approver |
| POST   | `/cycles/{cycle_id}/comp-plans/{comp_plan_id}/recall` | Recall an approved plan during comp planning. | Approver |
| GET    | `/audit-events` | Query the append-only audit log. | Admin, HRBP |
| POST   | `/_clock/advance` | Advance the logical clock to a supplied `to_datetime`. | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_INVALID_ROLE` | 401 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_REVIEW_CASE_NOT_FOUND` | 404 |
| `ERR_CALIBRATION_SESSION_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_PINNED_REVIEW_STALE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_PIP_ALREADY_EXISTS` | 409 |
| `ERR_GOAL_WEIGHTS_INVALID` | 422 |
| `ERR_PEER_FEEDBACK_INSUFFICIENT` | 422 |
| `ERR_REVISION_LIMIT` | 422 |
| `ERR_SELF_FEEDBACK_FORBIDDEN` | 422 |
| `ERR_FACILITATOR_CONFLICT` | 422 |
| `ERR_APPROVER_IS_MANAGER` | 422 |
| `ERR_PROMO_BLOCKED_BY_PIP` | 422 |
| `ERR_PROMO_STEP_INVALID` | 422 |
| `ERR_BELL_CURVE_VIOLATED` | 422 |
| `ERR_BELL_CURVE_TARGET_INVALID` | 422 |
| `ERR_CALIBRATION_COVERAGE` | 422 |
| `ERR_PIP_NOT_ELAPSED` | 422 |
| `ERR_EMAIL_TAKEN` | 422 |
| `ERR_MERIT_BUDGET_EXCEEDED` | 422 |
| `ERR_EQUITY_POOL_EXHAUSTED` | 422 |
| `ERR_TIME_WINDOW_INVALID` | 422 |
| `ERR_VALIDATION` | 400 |
