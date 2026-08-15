# Employee Offboarding API — Product Requirements Document

## 1. Introduction

When an employee separates from the company, four organizations must move in lockstep: HR determines the authoritative last working day and codes rehire eligibility, IT revokes system access in a safe order, payroll computes a final check that satisfies the wage-and-hour law of the employee's work state, and the benefits administrator hands off COBRA and plan-termination notices within statutory windows. A revocation that fires a day late is a security incident; a final check that arrives a day late accrues waiting-time penalties; a laptop that is never returned is a direct financial loss. Today these handoffs live in spreadsheets and inboxes, and the failure modes surface weeks later as audit findings.

This document specifies the Employee Offboarding API, mounted under `/offboarding`, which orchestrates that entire lifecycle as a single auditable **OffboardingCase**. A case aggregates ordered access-revocation tasks, tracked asset returns, exactly one final pay statement, exit interviews, a knowledge transfer plan, benefits notices, restrictive covenant acknowledgments, and a rehire eligibility review. A logical clock — never the wall clock — drives every scheduled transition, so the full timeline is deterministic and testable. Segregation of duties is enforced at four independent checkpoints so that no single operator can both perform and approve a sensitive step, and final-pay timing follows per-state legal variants across the eight supported work states.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, the logical clock, validation order, segregation of duties, monetary precision, concurrency control, and hierarchical consistency. Business workflows live in §3; the HTTP contract lives in §4.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's capacity. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes eleven roles. `PlatformAdmin` drives the logical clock and nothing else; it has no access to any business surface. `HRPartner` runs the case lifecycle — intake, approval, closure, voiding — and owns exit interviews and covenant acknowledgments. `HRReviewer` submits rehire eligibility recommendations. `HRDirector` finalizes or returns those reviews. `PayrollSpecialist` calculates, approves, and disburses final pay and marks overdue assets as defaulted. `ITOperator` executes and retries revocation tasks. `ITVerifier` verifies executed revocations, segregated from the executor. `ITManager` creates revocation tasks and waives them once retries are exhausted. `Manager` owns knowledge transfer plans and sessions and receives notifications. `AssetClerk` registers assets, records returns, and waives items. `BenefitsAdministrator` owns the benefits-notice handoff end to end.

Identity is uniform across all eleven roles: when `X-User-Role` is `PlatformAdmin`, `HRPartner`, `HRReviewer`, `HRDirector`, `PayrollSpecialist`, `ITOperator`, `ITVerifier`, `ITManager`, `Manager`, `AssetClerk`, or `BenefitsAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on certain resources — for example as `intake_hr_ref` on an OffboardingCase, as `calc_by_ref` on a FinalPayStatement, or as `verified_by` on an AccessRevocationTask — where a segregation-of-duties rule later compares it, but it is never compared to any entity's `id`. Of these recorded references, only `verified_by` and `reviewer_hr_ref` surface on serialized resources; `intake_hr_ref`, the intake approver reference, `calc_by_ref`, the executing-operator reference, task and asset waive reasons, and review return reasons are stored internally and never appear in response bodies.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10 and is clamped into the inclusive range 1–100 — a value below 1 is raised to 1, a value above 100 is lowered to 100, and a non-numeric value falls back to the default. The `offset` parameter skips a number of items from the start of the result set: it defaults to 0, a negative value is clamped up to 0, and a non-numeric value falls back to the default.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, with ties broken by insertion (creation) order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is still below `total_count`.

### 2.4. The Logical Clock and the System Scheduler

All time-dependent behavior in the system reads a single logical clock, never the process wall clock. A `PlatformAdmin` moves time through an admin-only test-driving capability whose payload carries `to_iso8601`, an ISO 8601 UTC instant; any parseable instant is accepted, with no monotonicity check. Both the set call and the companion read return the current value as `current_utc`, echoing the exact string supplied to the last set call rather than a re-normalized rendering. At startup, before any set call, the clock reads exactly `2026-08-01T00:00:00Z` and must not fall back to wall-clock time.

Advancing the clock is not a passive read change. Each set call fires every system-scheduler transition whose time predicate now holds, in one sweep: revocation tasks whose scheduled instant has arrived become executable (tasks belonging to a `CLOSED` or `VOIDED` case are skipped), interviews and knowledge transfer sessions whose end has passed are marked as no-shows, tracked assets past their return deadline become overdue, queued benefits notices past their send deadline flip to failed, covenant reminders whose reminder instant has arrived are dispatched, approved statements whose pay deadline has passed are marked late, both posture aggregates are recomputed, and any case-level automatic transition whose preconditions now hold fires as part of the same sweep.

### 2.5. Common Resource Properties

Every primary resource — OffboardingCase, AccessRevocationTask, AssetReturnItem, FinalPayStatement, ExitInterview, KnowledgeTransferPlan, KnowledgeTransferSession, BenefitsNotice, RestrictiveCovenantAck, and RehireEligibilityReview — carries a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version`** (integer): a system-managed integer that increments by one on every mutation, including mutations driven by cascades and automatic transitions.

One exception exists. A ManagerNotification is an append-only dispatch record: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

### 2.6. Request Evaluation Order

When several rules could reject the same request, the server evaluates them in a fixed priority order so that the returned error is deterministic. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the eleven declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization** — the authenticated role is permitted for this endpoint; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Existence** — every path-referenced resource resolves, checked left to right along the URL hierarchy; otherwise `ERR_NOT_FOUND` (HTTP 404).
4. **State legality** — the target resource is in a from-state the requested transition allows, including terminal-state lockdown and repeated-trigger attempts; otherwise `ERR_INVALID_STATE` (HTTP 409).
5. **Segregation of duties** — the actor differs from the recorded counterparty for the step; otherwise `ERR_SOD_VIOLATION` (HTTP 422).
6. **Temporal sanity** — dates and windows are internally coherent; otherwise `ERR_TEMPORAL_INVALID` (HTTP 422).
7. **Referential integrity** — referenced parents exist and unique-per-case constraints hold; otherwise `ERR_REFERENTIAL_INTEGRITY` (HTTP 422).
8. **Calendar overlap** — a new or rescheduled window does not collide with an existing scheduled window under the same parent; otherwise `ERR_SCHEDULE_OVERLAP` (HTTP 422).
9. **Retry, reschedule, and requeue caps** — the relevant counter is still below its cap; otherwise `ERR_RETRY_CAP_EXCEEDED` (HTTP 422).
10. **Revocation ordering gate** — lower-ranked revocation siblings are terminal, and waiver is only attempted after the retry cap; otherwise `ERR_SEQUENCE_GATE` (HTTP 422).
11. **Fiscal sanity** — wage, balance, cost, and wage inputs are in range; otherwise `ERR_FISCAL_INVALID` (HTTP 422).
12. **Legal deadline protection** — a benefits send has not missed its deadline and a close is not attempted without a finalized rehire review; otherwise `ERR_DEADLINE_MISSED` (HTTP 422).
13. **Payload shape** — required fields are present, enum values belong to their declared sets, and numeric ranges are honored; otherwise `ERR_INVALID_REQUEST` (HTTP 400).
14. **Optimistic concurrency** — where an endpoint takes an expected-version field, it matches the resource's current version; otherwise a stale-version rejection (HTTP 412) per §2.9.

### 2.7. Segregation of Duties

Four steps in the lifecycle are two-person operations. At each, the acting operator's `X-User-ID` is compared against an identifier recorded earlier on the resource, and a match is rejected with `ERR_SOD_VIOLATION` (HTTP 422):

- **SoD-1, intake approval.** The HR partner approving a case must differ from the `intake_hr_ref` recorded when the case was created.
- **SoD-2, statement approval.** The payroll specialist approving a final pay statement must differ from the `calc_by_ref` recorded when the statement was last calculated.
- **SoD-3, revocation verification.** The verifier confirming an executed revocation must differ from the operator who executed it.
- **SoD-4, rehire finalization.** The HR director finalizing a rehire review must differ from the `reviewer_hr_ref` recorded on the review.

Independently, the `reviewer_hr_ref` recorded on a rehire eligibility review must differ from the intake approver of the same case, keeping recommendation authority separate from case-approval authority.

### 2.8. Money, Precision, and Wage Protection

All monetary amounts are integer cents — wages, payouts, deductions, penalties, and replacement costs alike. Wherever a computed amount lands on a fractional cent, it is rounded half-up to a whole cent. Two input fields carry fractional precision of their own: `pto_balance_hours` and `tenure_years` are non-negative numbers conventionally supplied with two and one decimal places respectively; the server accepts any non-negative number and does not enforce the decimal-place count. Calendar results are pinned to explicit precisions: a determined last day is a date at midnight UTC, while deadlines, schedules, and dispatch timestamps are instants in ISO 8601 UTC. Like `created_at` (§2.5), every such stored calendar instant is rendered with exactly three fractional digits — a determined last day reads, for example, `2026-08-10T00:00:00.000Z`.

Rounding order is pinned for asset deductions: each item's deduction is computed and rounded to a whole cent first, and case-level totals then sum those integers. The system never sums unrounded values and rounds once at the end.

Fiscal sanity is validated at three points: case intake, asset registration, and statement calculation. The `hourly_wage_cents` must be greater than zero; `pto_balance_hours`, `replacement_cost_cents`, and `regular_wages_cents` may not be negative. A violation is rejected with `ERR_FISCAL_INVALID` (HTTP 422). One invariant sits above all arithmetic: deductions may never push an employee's net pay below zero, so the deduction applied to a statement is capped at gross pay (see §3.3).

### 2.9. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each naming a required expected-version field in its request body:

- Closing a case — `POST /offboarding/offboarding-cases/{id}/close` — requires `expected_offboarding_case_version`, carrying the caller's last observed `version` of the OffboardingCase. If the case's version has advanced since that read — for example because a revocation verification or an asset default cascaded into the case — the close is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412).
- Calculating a statement — `POST /offboarding/final-pay-statements/{id}/calculate` — requires `expected_final_pay_statement_version`. A mismatch with the statement's current `version` is rejected with `ERR_STALE_STATEMENT_VERSION` (HTTP 412), so a recalculation can never silently overwrite deduction values that an asset default cascade recomputed after the caller's last read.
- Recording an asset return — `POST /offboarding/asset-return-items/{id}/record-return` — requires `expected_asset_return_item_version`. A mismatch with the item's current `version` is rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412); the scheduler may have flipped the item to overdue in the meantime, changing which deduction variant applies.

Where no rule-specific identifier applies to a version mismatch, the generic `ERR_STALE_VERSION_GENERIC` (HTTP 412) is the fallback rejection. Endpoints not listed above do not take a version field.

### 2.10. Hierarchical Retrieval and Uniqueness Invariants

Requests that address nested resources resolve path identifiers strictly left to right: the case first, then the child within that case. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, and no later validation runs against a resource the path never reached. Child creation follows the same discipline — the referenced parent must exist, and a dangling reference is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). Sub-resource listings under a parent (`/offboarding-cases/{id}/...`, `/knowledge-transfer-plans/{id}/knowledge-transfer-sessions`) accept only the `status` query filter; the remaining collection filters documented in §3 apply to the top-level listings only.

Uniqueness invariants are enforced per case. A case admits exactly one FinalPayStatement, exactly one KnowledgeTransferPlan, and exactly one RehireEligibilityReview. Within a case, no two revocation tasks may share a `sequence_rank`, and no two asset items may share an `asset_tag`. Across the whole system, `employee_ref` is unique: no two cases may be opened for the same HRIS employee identifier. Violating any of these constraints is rejected with `ERR_REFERENTIAL_INTEGRITY`.

### 2.11. Posture Aggregation and Hierarchical Reconciliation

An OffboardingCase is reconciled against its children continuously, not at checkpoints. Every mutation of a revocation task recomputes the case's `revocation_posture`; every mutation of an asset item recomputes the case's `asset_posture`. When an aggregate crosses a threshold, the case itself transitions automatically — approval advances to revocation-in-progress, revocation completion advances toward payroll and clearance, and clearance completion advances to ready-to-close — without any client call on the case itself. Each such reconciliation is a real mutation of the case: `updated_at` is refreshed and `version` increments by one on every transition, automatic or client-driven; a single reconciliation pass that advances the case through more than one state in one call (for example, revocation completion landing directly in `READY_TO_CLOSE`) still increments `version` only once for the pass.

Cascades flow downward as well. Approval stamps return deadlines onto every tracked asset; reaching the payroll stage queues benefits notices and arms covenant reminders; closure expires still-open covenant acknowledgments; voiding a case waives its pending revocation work and tracked assets and voids an unapproved statement. §3 specifies each cascade next to the workflow that triggers it.

## 3. Business Logic & Workflows

### 3.1. Intake and Last-Day Determination

An offboarding begins when an `HRPartner` opens a case. The intake payload names the departing employee through `employee_ref`, an external HRIS identifier that must be unique across all cases; classifies the separation through `case_type` as one of `RESIGNATION`, `TERMINATION`, `MUTUAL_SEPARATION`, or `JOB_ABANDONMENT`; and fixes the governing jurisdiction through `work_state_code`, which must be one of the eight supported codes `CA`, `CO`, `IL`, `MA`, `TX`, `NY`, `WA`, or `FL`. The payload also records `notice_received_date` (when notice was given or the termination decision was made), the employee- or manager-proposed `requested_last_day`, the accrued `pto_balance_hours`, the completed `tenure_years`, and the final `hourly_wage_cents`, alongside `intake_hr_ref` identifying the recording HR partner. A requested last day earlier than the notice date is rejected with `ERR_TEMPORAL_INVALID` — both at creation and again at approval. At creation the server evaluates the intake rules in this order: date parseability and the requested-day ordering, `employee_ref` presence and cross-case uniqueness, wage and PTO fiscal sanity, and finally the enum and remaining required fields (`case_type`, `work_state_code`, `tenure_years`, `intake_hr_ref`). A new case starts in `INTAKE`, and its creation dispatches an `INTAKE_ALERT` notification to the manager. Cases can be listed and filtered by `status`, `work_state_code`, or `case_type`.

Approval is the pivotal step. A second `HRPartner` — never the recorder, per SoD-1 — approves a case that is still in `INTAKE`. Approval runs the last-day determination, and the rule has two variants. For a `RESIGNATION` or `MUTUAL_SEPARATION`, the employee's requested day is honored up to a statutory notice cap: the `determined_last_day` becomes the earlier of the `requested_last_day` and the date thirty days after the `notice_received_date`. For a `TERMINATION` or `JOB_ABANDONMENT`, the company controls the date: the `determined_last_day` becomes the later of the `notice_received_date` and the `requested_last_day`. Either way, if the result lands on a Saturday or Sunday it is moved — forward to the following Monday for resignation-type cases, backward to the preceding Friday for termination-type cases. The result is stored as a date at midnight UTC and remains null until approval.

The same approval computes the legal final-pay deadline and stores it on the case as `final_pay_due_at`, which likewise remains null until approval. The deadline rule is a total mapping over the eight supported states, with no gaps. In California, Colorado, and Massachusetts the rule runs on calendar time: a `TERMINATION` or `JOB_ABANDONMENT` is due at the determined last day itself, and so is a `RESIGNATION` or `MUTUAL_SEPARATION` where the employee gave at least seventy-two hours of notice, measured from the `notice_received_date` to the `requested_last_day`; a resignation-type case with less than seventy-two hours of notice is due seventy-two hours after the determined last day. In Illinois, New York, and Washington the rule runs on business days: payment is due the next business day after the determined last day, skipping Saturdays and Sundays. In Texas and Florida payment is due on the next regular payday after the determined last day, where regular paydays fall on the 15th and on the last day of each month at 17:00 UTC; because the determined last day is midnight, a payday at 17:00 UTC later that same calendar day counts as the next payday. Approval also auto-creates three child records if absent: a FinalPayStatement in `DRAFT` carrying the `state_law_variant` — `IMMEDIATE_ON_TERMINATION` for termination-type cases in the three calendar-day states, `WITHIN_FIXED_DAYS` for resignation-type cases in those states and for all cases in the three business-day states, and `NEXT_PAYDAY` for Texas and Florida — along with its `due_at`; a KnowledgeTransferPlan in `DRAFT` with a null `owner_manager_ref` and a `required_session_count` of zero; and a RehireEligibilityReview in `DRAFT` with `recommended_code` initialized to `ELIGIBLE` and a null `reviewer_hr_ref` and `rationale`. Every already-registered asset of the case is stamped with its return deadline, the manager receives a `LAST_DAY_CONFIRMED` notification unless deduplicated, and the case lands in `APPROVED` with its version incremented.

A case can be abandoned before work begins. Voiding from `INTAKE` or `APPROVED` requires a `void_reason` and cascades: every revocation task still `PENDING`, `READY`, or `RETRY_SCHEDULED` becomes `WAIVED`; every asset item still `TRACKED` becomes `WAIVED`; a statement still `DRAFT` or `CALCULATED` becomes `VOIDED`. Once revocation has actually begun — any task `EXECUTED` or `VERIFIED` — an approved case can no longer be voided; the attempt is rejected with `ERR_INVALID_STATE`. A voided case is terminal.

### 3.2. Revocation Task Sequencing and Verification

Access revocation is modeled as an ordered set of tasks. An `ITManager` creates each task against a case through a payload containing the `offboarding_case_id`, the target `system_name` — one of `EMAIL`, `VPN`, `ERP`, `CODE_REPO`, `BADGE`, `PAYROLL_SYSTEM`, `CRM`, or `CLOUD_STORAGE` — and a `sequence_rank`, a positive integer that orders execution; lower ranks revoke first, and two tasks of the same case may never share a rank. New tasks start `PENDING`. Scheduling anchors every task to 17:00 UTC on the case's determined last day, shifted by a per-system offset: `EMAIL`, `VPN`, and `CRM` fire at the anchor itself; `ERP` and `PAYROLL_SYSTEM` fire twenty-four hours later, so payroll integrations survive payroll close; `CODE_REPO` and `CLOUD_STORAGE` fire twenty-four hours earlier, protecting source and documents before the final day; and `BADGE` fires one hour after the anchor, at 18:00 UTC. The computed instant is stored as `scheduled_at`. Tasks created while the case is still in `INTAKE` carry a null `scheduled_at`; the schedule is computed for them when the case is approved, while tasks created against an already-approved case are scheduled at creation. Tasks are listed with filters on `offboarding_case_id`, `status`, and `system_name`, and a sub-resource listing under the case returns the same collection.

Release to `READY` is the scheduler's job. A pending task becomes executable when the logical clock reaches its `scheduled_at` and every sibling with a lower `sequence_rank` is already terminal — `VERIFIED` or `WAIVED`. An `ITOperator` then executes a ready task, which is permitted only while the parent case is `APPROVED` or `REVOCATION_IN_PROGRESS`. The execution call carries an `outcome`: on success the task becomes `EXECUTED` and is stamped with `executed_at`; an `outcome` of `FAILED` requires a non-empty `failure_reason` and moves the task to `FAILED` instead.

Verification is segregated. An `ITVerifier` reviews an `EXECUTED` task — never the same person who executed it, per SoD-3, with breaches rejected as `ERR_SOD_VIOLATION`. A confirming verification moves the task to `VERIFIED` and stamps `verified_by` with the verifier's `X-User-ID`; a rejection, submitted as an `outcome` of `REJECTED`, pushes the task back to `FAILED` and requires no `failure_reason` — the field is left untouched.

Failure handling is capped and ordered. An `ITOperator` may retry a `FAILED` task, which moves it to `RETRY_SCHEDULED`, increments `retry_count` by one, and reschedules it to the current time plus sixty minutes multiplied by the newly incremented count — so the first retry waits one hour, the second two hours, the third three. The scheduler releases a retry-scheduled task back to `READY` once its new instant arrives, under the same ordering gate as an initial release. Retrying is refused once `retry_count` has reached the cap of three, rejected with `ERR_RETRY_CAP_EXCEEDED`. At that point an `ITManager` may waive the task — from `FAILED` or from `RETRY_SCHEDULED` — by supplying a `waive_reason`; waiver attempted before the retry cap is reached is rejected with `ERR_SEQUENCE_GATE`, as is any execution attempt while a lower-ranked sibling is not yet terminal.

Every task mutation recomputes the case's `revocation_posture`, evaluated in a fixed precedence. The posture is `COMPLETE` when every task is `VERIFIED` or `WAIVED` and at least one task exists. Otherwise it is `BLOCKED` when any task sits in `FAILED` or `RETRY_SCHEDULED` with a `retry_count` that has reached three. Otherwise it is `IN_PROGRESS` when any task is `READY`, `EXECUTED`, or `RETRY_SCHEDULED`. Failing all three, it is `NOT_STARTED` — every task still `PENDING`, or no tasks at all. Two case-level consequences hang off this aggregate: the first task leaving `PENDING` for `READY` or `EXECUTED` flips the case from `APPROVED` to `REVOCATION_IN_PROGRESS` and notifies the manager with `REVOCATION_STARTED`; and the posture turning `COMPLETE` advances the case again, notifying the manager with `REVOCATION_COMPLETE`. That second advancement has two orders. In the revocation-first order the case moves to `PAYROLL_PENDING`, where it waits for payroll. In the payroll-first order — the statement already `APPROVED`, `DISBURSED`, or `LATE` when revocation completes — the case moves directly from `REVOCATION_IN_PROGRESS` to `CLEARANCE_IN_PROGRESS`. Both advancements queue the case's benefits notices and arm its covenant reminders, as §3.6 details.

### 3.3. Final Pay: Calculation, Approval, and Disbursement

Exactly one FinalPayStatement exists per case, created in `DRAFT` at intake approval. It opens with the unpaid `regular_wages_cents` still to be supplied by payroll, computed `pto_payout_cents`, `deduction_total_cents`, and `net_pay_cents` initialized to zero, the `state_law_variant` and `due_at` fixed at creation, and `late_penalty_cents` at zero. Statements are listed with filters on `offboarding_case_id` and `status`, and the case's sub-resource listing returns at most one element.

A `PayrollSpecialist` calculates a `DRAFT` statement, supplying the `regular_wages_cents` owed through the determined last day and the OCC guard `expected_final_pay_statement_version`; a version that no longer matches is rejected with `ERR_STALE_STATEMENT_VERSION` (HTTP 412). Calculation is only permitted while the parent case is `APPROVED`, `REVOCATION_IN_PROGRESS`, or `PAYROLL_PENDING`. It first computes the PTO payout, which always evaluates two methods and pays the greater. The state-law variant pays the full `pto_balance_hours` multiplied by `hourly_wage_cents` when the `work_state_code` is one of `CA`, `CO`, `IL`, or `MA`, and zero in the other four states. The company-policy variant caps payable hours by tenure — 40 hours when `tenure_years` is under two, 80 hours when it is at least two but under five, and 120 hours when it is five or more — takes the lesser of the balance and the cap, rounds the payable hours down to the nearest half hour, and multiplies by the wage. The `pto_payout_cents` stored on the statement is the greater of the two variants, rounded half-up to a whole cent. Calculation then runs the net-pay waterfall in its pinned order: gross pay is the `regular_wages_cents` plus the PTO payout; the deduction applied is the lesser of the case's `deduction_total_cents` and that gross, so deductions can never drive net pay below zero; and `net_pay_cents` is gross minus the applied deduction. The calculating specialist's `X-User-ID` is recorded as `calc_by_ref`, the statement becomes `CALCULATED`, and its version increments.

Approval separates calculator from approver. A `PayrollSpecialist` different from the recorded `calc_by_ref` approves a `CALCULATED` statement — SoD-2, with self-approval rejected as `ERR_SOD_VIOLATION` — again only while the case is `APPROVED`, `REVOCATION_IN_PROGRESS`, or `PAYROLL_PENDING`. Approval is the payroll gate of the case state machine: when the case sits in `PAYROLL_PENDING` (the revocation-first order), the approval cascades the case into `CLEARANCE_IN_PROGRESS`. When revocation is still running (the payroll-first order), the case instead advances to `CLEARANCE_IN_PROGRESS` through the automatic transition described in §3.2 once the revocation posture completes. If the numbers are wrong, a recalculation — again permitted only while the case is `APPROVED`, `REVOCATION_IN_PROGRESS`, or `PAYROLL_PENDING` — reverts a `CALCULATED` statement back through `DRAFT` and recomputes the payout, deduction, and net in one action, optionally accepting a replacement `regular_wages_cents`; the statement ends `CALCULATED` again with its version incremented.

Disbursement honors the legal deadline recorded in `due_at`. Only an `APPROVED` statement can be disbursed; a disburse attempt against a statement in any other status — including one the scheduler has already marked `LATE` — is rejected with `ERR_INVALID_STATE`. Disbursing an `APPROVED` statement at or before `due_at` lands it in `DISBURSED` and stamps `disbursed_at`. Disbursing an `APPROVED` statement after `due_at` is not rejected — the law is violated but the employee must still be paid — and instead lands the statement in `LATE`, stamping `disbursed_at` and computing a waiting-time penalty as of the disbursement instant. The scheduler also marks an approved statement `LATE` when its deadline passes undisbursed, computing the same waiting-time penalty as of the sweep instant. The penalty accrues at the employee's daily wage, defined as eight hours at the `hourly_wage_cents`, for each late calendar day with any fractional day rounded up to a full day, capped at thirty days. A disbursement exactly at `due_at` is on-time; one second past it is already one full day of penalty. `DISBURSED`, `LATE`, and `VOIDED` are terminal, and a statement in `DRAFT` or `CALCULATED` is swept to `VOIDED` if its parent case is voided.

### 3.4. Asset Recovery and Payroll Deductions

An `AssetClerk` registers each company asset the departing employee holds, through a payload containing the `offboarding_case_id`, an `asset_tag` unique within the case, the `asset_kind` — one of `LAPTOP`, `MONITOR`, `PHONE`, `KEYCARD`, `TOOLING`, `VEHICLE`, `UNIFORM`, or `OTHER` — the current `replacement_cost_cents`, and the `issued_date` that anchors depreciation. A new item is `TRACKED` with `deduction_status` `NONE` and `deduction_amount_cents` zero. When the case is approved, every tracked item's `return_due_at` is stamped as three days after the determined last day; an item registered while the case is still in `INTAKE` carries a null `return_due_at` until that stamping, while an item registered against an already-approved case is stamped at registration with the same three-days-after-the-determined-last-day deadline. Items are listed with filters on `offboarding_case_id`, `status`, and `deduction_status`.

Physical return is recorded by an `AssetClerk` supplying the `condition_on_return` — one of `GOOD`, `NORMAL_WEAR`, `DAMAGED`, or `DESTROYED` — together with the OCC guard `expected_asset_return_item_version`, where a stale read is rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412). Returns are accepted while the parent case is anywhere from `APPROVED` through `READY_TO_CLOSE`. The item is stamped with `returned_at` and becomes `RETURNED`. When the recorded condition is `DAMAGED` or `DESTROYED`, a damage-variant deduction is computed immediately: the deduction is half of the replacement cost for a damaged item and the full replacement cost for a destroyed one, rounded half-up to a whole cent, and the item's `deduction_status` becomes `COMPUTED`.

Time works against an unreturned item. Once the logical clock passes `return_due_at`, the scheduler moves a still-`TRACKED` item to `OVERDUE`. A late return is still recordable — the same return flow from `OVERDUE` — but the deduction gains a late component: when `returned_at` is later than `return_due_at`, a flat 2,500-cent late fee is added to the deduction after rounding, whatever the recorded condition — so a late return in `GOOD` or `NORMAL_WEAR` condition still yields a 2,500-cent deduction with `deduction_status` `COMPUTED`, while an on-time undamaged return leaves the deduction `NONE` at zero. Once the clock passes seven days beyond `return_due_at`, and the parent case has reached `PAYROLL_PENDING` or `CLEARANCE_IN_PROGRESS`, a `PayrollSpecialist` may mark the item `DEFAULTED`; a default attempted before that grace period has elapsed, or while the case is in any other state, is rejected with `ERR_INVALID_STATE`. Defaulting runs the depreciated-value variant of the deduction: the item's age is the whole number of days between `issued_date` and `return_due_at`, with any partial day discarded; depreciation accrues in basis points per day at a per-kind rate — 20 for a `LAPTOP`, 25 for a `PHONE`, and 10 for every other kind — capped at 7,000 basis points; the depreciated value is the replacement cost scaled by the share of ten thousand that remains after depreciation; and the deduction is that value rounded half-up to a whole cent. The item's `deduction_status` becomes `APPLIED`, and the default cascades: the case's `deduction_total_cents` is recomputed, and if the statement is `CALCULATED` or `APPROVED` its deduction total and `net_pay_cents` are recomputed in place under the §3.3 waterfall. An `AssetClerk` may also waive an item by supplying a `waive_reason`, but only while the item is `TRACKED` or `OVERDUE`; a waive attempt against an item in any other status — including `RETURNED` or `DEFAULTED` — is rejected with `ERR_INVALID_STATE`. A `TRACKED` or `OVERDUE` item's deduction is always still `NONE`, so waiver ordinarily leaves the deduction fields untouched; should a waived item's deduction be `COMPUTED` or `APPLIED`, the deduction moves to `WAIVED`, its amount is zeroed, and the case total is recomputed.

Two aggregates ride on these mutations. The case's `deduction_total_cents` is the sum of `deduction_amount_cents` across exactly those items whose `deduction_status` is `APPLIED`; items merely `COMPUTED` are excluded from the payroll total and instead surface as `projected_deduction_cents` on the case summary read. The case's `asset_posture` is evaluated in fixed precedence: `COMPLETE` when every item is `RETURNED` or `WAIVED` and at least one item exists; then `DEFAULTED` when any item is `DEFAULTED` or any item is `OVERDUE`; then `IN_PROGRESS` when at least one item exists; and `NOT_STARTED` when the case tracks no assets at all.

### 3.5. Exit Interviews and Knowledge Transfer

An `HRPartner` schedules an exit interview against a case through a payload containing the `offboarding_case_id`, the external `interviewer_ref`, and a window from `scheduled_start` to `scheduled_end`; an end that does not fall strictly after the start is rejected with `ERR_TEMPORAL_INVALID`. A new interview is `SCHEDULED`, and its window must not overlap any other `SCHEDULED` interview of the same case, measured as a half-open interval that includes the start instant and excludes the end instant — so one interview ending exactly when another begins is not a conflict. A violation is rejected with `ERR_SCHEDULE_OVERLAP`. Interviews are listed with filters on `offboarding_case_id` and `status`.

The reschedule cycle is deliberately bounded. Requesting a reschedule moves a `SCHEDULED` interview to `RESCHEDULE_REQUESTED` and increments `reschedule_count`; it is refused once the count has reached the cap of two, rejected with `ERR_RETRY_CAP_EXCEEDED`, and it is refused outright on a `CLOSED` or `VOIDED` case with `ERR_CASE_TERMINAL` (HTTP 409). Applying the new window — `scheduled_start` and `scheduled_end` — returns the interview to `SCHEDULED`, subject again to the same-case overlap rule and to a hard limit: the new end may not fall later than five days after the case's determined last day (evaluated only once the case has a determined last day). Completion requires the interview to be `SCHEDULED`, the logical clock to have reached `scheduled_start` (an earlier attempt is rejected with `ERR_INVALID_STATE`), and a `completion_notes_ref` pointing at the notes store; the employee may instead decline, which requires a `declined_reason`, and the interviewer may cancel outright — declining and cancelling are likewise accepted only from `SCHEDULED`. `COMPLETED`, `DECLINED`, and `CANCELLED` are terminal. An interview whose end passes while still `SCHEDULED` is marked `NO_SHOW` by the scheduler; one rehabilitation loop exists — rescheduling directly from `NO_SHOW` to `SCHEDULED` under the same overlap rule — which also consumes one tick of `reschedule_count`, since the cap of two applies across both loops combined. Completing, declining, or cancelling an interview re-evaluates the case's readiness gate in §3.7.

Knowledge transfer runs in parallel. The plan auto-created at approval is owned by a manager through `owner_manager_ref` and carries a `required_session_count` of zero or more; exactly one plan exists per case. A `Manager` activates a `DRAFT` plan — permitted while the case is `APPROVED`, `REVOCATION_IN_PROGRESS`, or `PAYROLL_PENDING` — moving it to `ACTIVE`; the activation payload may optionally carry the `owner_manager_ref` (a non-empty string) and a `required_session_count` (an integer zero or greater), which are recorded at that moment. Sessions are then scheduled under the plan through a payload containing the `knowledge_transfer_plan_id`, a `topic`, the `successor_ref` receiving the knowledge, and a `scheduled_start`/`scheduled_end` window. Session windows obey a stricter overlap rule than interviews: within one plan, a new session may not overlap another `SCHEDULED` session on a closed interval, and zero-minute adjacency is forbidden — a session starting exactly when another ends is already a conflict, rejected with `ERR_SCHEDULE_OVERLAP`. Scheduling is not gated on the plan's status — sessions may be created under a plan of any status so long as the case is non-terminal — but completion requires the plan to be `ACTIVE`. Sessions are listed with filters on `knowledge_transfer_plan_id` and `status`.

Session outcomes feed the plan. A `Manager` completes a `SCHEDULED` session once the clock has reached its start and the plan is `ACTIVE` — a completion attempted before the start, or under a non-`ACTIVE` plan, is rejected with `ERR_INVALID_STATE`; cancelling is also possible from `SCHEDULED`; and the scheduler marks a session `NO_SHOW` when its end passes. Every session mutation recomputes the plan's `completed_session_count` as the count of `COMPLETED` sessions, and the plan auto-completes — `ACTIVE` to `COMPLETE` — the moment that count reaches a `required_session_count` greater than zero. A plan requiring zero sessions never auto-completes; the `Manager` completes it explicitly, and an explicit completion attempted while `completed_session_count` still falls short of `required_session_count` is rejected with `ERR_INVALID_STATE`. A plan may instead be waived from `DRAFT` or `ACTIVE` with a `waived_reason` recorded — for example when the role itself is redundant. If the case reaches its ready-to-close gate while a plan is still `ACTIVE`, the system marks the plan `INCOMPLETE_AT_CLOSE`. Plan completion, waiver, and incompletion each re-evaluate the §3.7 readiness gate, and `COMPLETE`, `WAIVED`, and `INCOMPLETE_AT_CLOSE` are terminal.

### 3.6. Benefits Notices and Restrictive Covenant Reminders

Benefits handoff is modeled as notices with legal deadlines. A `BenefitsAdministrator` creates each notice in `DRAFT` against a case through a payload containing the `offboarding_case_id` and the `notice_kind` — one of `COBRA_ELECTION`, `BENEFITS_TERMINATION`, `RETIREMENT_PLAN`, or `LIFE_INSURANCE_CONVERSION`. Notices are listed with filters on `offboarding_case_id`, `status`, and `notice_kind`. When the case reaches `PAYROLL_PENDING` — in either advancement order of §3.2 — every `DRAFT` notice of the case is queued automatically and stamped with a `send_by` deadline measured in calendar days from the determined last day, landing at 17:00 UTC on the target date: forty-four days for a `COBRA_ELECTION`, thirty days for a `BENEFITS_TERMINATION`, thirty days for a `RETIREMENT_PLAN`, and thirty-one days for a `LIFE_INSURANCE_CONVERSION`. This queueing (like the covenant arming below) happens once, at that transition: a notice created after the case has already passed it remains `DRAFT` and is never auto-queued, and a covenant acknowledgment created afterwards keeps a null `remind_at` and is never reminded.

Dispatch is deadline-protected. Sending a `QUEUED` notice at or before `send_by` moves it to `SENT` and stamps `sent_at`; attempting to send after the deadline is rejected with `ERR_DEADLINE_MISSED` (HTTP 422) — the notice must instead be requeued — and a notice still `QUEUED` when the clock passes `send_by` is marked `FAILED` by the scheduler with its `failure_count` incremented. A `SENT` notice is either acknowledged, stamping `acknowledged_at`, or reported failed on vendor rejection, which also increments `failure_count`. Recovery is capped: a `FAILED` notice may be requeued while `failure_count` is below two — requeueing recomputes `send_by` from the current time using the same per-kind day counts, again landing at 17:00 UTC on the target date — and a requeue at the cap is rejected with `ERR_RETRY_CAP_EXCEEDED`; at the cap the administrator instead escalates the notice, landing it in `ESCALATED`, and an escalation attempted below the cap is rejected with `ERR_INVALID_STATE`. `ACKNOWLEDGED` and `ESCALATED` are terminal.

Restrictive covenants follow the departing employee beyond the last day. An `HRPartner` creates an acknowledgment requirement per covenant through a payload containing the `offboarding_case_id` and the `covenant_kind` — one of `NON_COMPETE`, `NON_SOLICIT_CLIENTS`, `NON_SOLICIT_EMPLOYEES`, `CONFIDENTIALITY`, or `IP_ASSIGNMENT`; covenant records are listed with filters on `offboarding_case_id` and `status`. New acknowledgments start `PENDING`. When the case reaches `PAYROLL_PENDING`, every pending acknowledgment is armed with a `remind_at` set to three days after the determined last day at 09:00 UTC; the scheduler fires the reminder once when that instant arrives — moving the record to `REMINDED` — and if the instant has already passed by the time the case reaches the payroll stage, the reminder fires on the next scheduler tick. The employee's acknowledgment, recorded by an `HRPartner` from either `PENDING` or `REMINDED`, requires the `acknowledgment_text_version` of the covenant text being acknowledged, stamps `acknowledged_at`, and is only accepted while the case is still open — acknowledgment after closure violates temporal sanity (`ERR_TEMPORAL_INVALID`), and any operation against a terminal case is rejected with `ERR_CASE_TERMINAL`. A covenant that genuinely does not apply may be marked `NOT_APPLICABLE`, but only while the case is still in `INTAKE` or `APPROVED`. At case closure, every acknowledgment still `PENDING` or `REMINDED` is swept to `EXPIRED`.

### 3.7. Rehire Eligibility and Case Closure

The rehire review is the last act of the case. The review auto-created at approval sits `DRAFT` until an `HRReviewer` submits it — permitted once the case has reached `CLEARANCE_IN_PROGRESS` or `READY_TO_CLOSE` — with a payload carrying the `recommended_code`, one of `ELIGIBLE`, `ELIGIBLE_WITH_CONDITIONS`, or `INELIGIBLE`, and a non-empty `rationale`, moving the review to `SUBMITTED`. An `HRDirector` then finalizes a `SUBMITTED` review, stamping `finalized_at` and landing it in `FINALIZED`; per SoD-4 the finalizer must differ from the `reviewer_hr_ref` on the review, and per §2.7 that reviewer must in turn differ from the case's intake approver. A director may instead return a `SUBMITTED` review with a `return_reason`, moving it to `RETURNED`, and the reviewer resubmits from `RETURNED` back to `SUBMITTED` with a fresh `rationale`; the return–submit loop may repeat. `FINALIZED` is terminal. Reviews are listed with filters on `offboarding_case_id` and `status`.

Readiness to close is an automatic verdict. A case in `CLEARANCE_IN_PROGRESS` advances to `READY_TO_CLOSE` when three conditions all hold: every tracked asset is settled, meaning the `asset_posture` is `COMPLETE` or `DEFAULTED` — a case tracking no assets at all satisfies this condition vacuously; no exit interview of the case remains `SCHEDULED` or `RESCHEDULE_REQUESTED`; and the knowledge transfer plan is `COMPLETE` or `WAIVED`. Every interview, session, plan, asset, and waiver mutation described above re-evaluates this gate.

Closure itself is deliberate and guarded. An `HRPartner` closes a `READY_TO_CLOSE` case, but only when the rehire review is `FINALIZED` — closing without it is rejected with `ERR_DEADLINE_MISSED` — when every benefits notice is `SENT`, `ACKNOWLEDGED`, or `ESCALATED`, and when the statement is `DISBURSED` or `LATE`; an unmet statement or notice precondition is rejected with `ERR_INVALID_STATE` (HTTP 409). The close payload carries the OCC guard `expected_offboarding_case_version`; a version that no longer matches is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). A successful close copies the review's `recommended_code` into the case's `rehire_code` — which remains null until this moment — stamps `closed_at`, notifies the manager with `CASE_CLOSED`, expires every covenant acknowledgment still `PENDING` or `REMINDED`, and increments the case version. `CLOSED` and `VOIDED` are the case's terminal states, and operations attempted against either are rejected with `ERR_CASE_TERMINAL`.

A computed summary read supports the close decision. For a case it returns the current `revocation_posture` and `asset_posture`, the applied `deduction_total_cents`, the `projected_deduction_cents` of items computed but not yet applied, a `net_pay_preview_cents` reflecting the current statement math — recomputed live from the statement's stored `regular_wages_cents` and `pto_payout_cents` against the case's current `deduction_total_cents` under the §3.3 waterfall, and zero when no statement exists — and a `ready_to_close` boolean mirroring the readiness gate above, evaluated live regardless of the case's current status.

### 3.8. Manager Notifications and the Deduplication Window

Managers are kept informed at five lifecycle moments, each producing a notification row addressed to `recipient_manager_ref` — persisted as null, since no intake field supplies a manager identity — and stamped with `sent_at` at dispatch: `INTAKE_ALERT` when the case is opened, `LAST_DAY_CONFIRMED` at intake approval, `REVOCATION_STARTED` when the first revocation task leaves pending, `REVOCATION_COMPLETE` when the revocation posture completes in either advancement order, and `CASE_CLOSED` at closure. The `notification_kind` distinguishes the five.

Dispatch is deduplicated so cascades cannot spam the manager. When a notification is created and an unsuppressed notification of the same kind already exists for the same case whose `sent_at` falls within the preceding sixty minutes — the window includes the earlier dispatch instant and excludes the instant exactly sixty minutes after it — the new row is still persisted but flagged `suppressed`, queryable yet never dispatched. Notifications are listed with filters on `offboarding_case_id`, `notification_kind`, and `suppressed`, and a sub-resource listing under the case returns the same collection. As noted in §2.5, these rows are append-only and carry no `updated_at` or `version`.

## 4. Endpoint Definitions

Endpoints that create a new resource — a case, a revocation task, an asset item, an interview, a session, a notice, or a covenant acknowledgment — return `201 Created`. Endpoints that modify an existing resource, including every state-transition action, return `200 OK`. Readers should reconstruct request payloads and side effects from §3; this table is only a locator.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/offboarding/_clock/set_current_utc` | Set the logical clock and fire all due scheduler transitions | PlatformAdmin |
| GET | `/offboarding/_clock/current_utc` | Read the logical clock | PlatformAdmin |
| POST | `/offboarding/offboarding-cases` | Intake: create an OffboardingCase in INTAKE | HRPartner |
| GET | `/offboarding/offboarding-cases` | List cases; filter by status, work_state_code, case_type | HRPartner, HRReviewer, HRDirector, PayrollSpecialist, ITOperator, ITVerifier, ITManager, Manager, AssetClerk, BenefitsAdministrator |
| GET | `/offboarding/offboarding-cases/{id}` | Fetch one case | HRPartner, HRReviewer, HRDirector, PayrollSpecialist, ITOperator, ITVerifier, ITManager, Manager, AssetClerk, BenefitsAdministrator |
| GET | `/offboarding/offboarding-cases/{id}/summary` | Computed read: postures, projected and applied deductions, net pay preview, readiness | HRPartner, HRDirector, PayrollSpecialist, Manager |
| POST | `/offboarding/offboarding-cases/{id}/approve` | Approve intake; determines last day and final-pay deadline, creates children | HRPartner |
| POST | `/offboarding/offboarding-cases/{id}/close` | Close the case with OCC guard | HRPartner |
| POST | `/offboarding/offboarding-cases/{id}/void` | Void a case in INTAKE or APPROVED | HRPartner |
| POST | `/offboarding/access-revocation-tasks` | Create a revocation task for a case | ITManager |
| GET | `/offboarding/access-revocation-tasks` | List revocation tasks; filter by case, status, system | ITOperator, ITVerifier, ITManager, HRPartner |
| GET | `/offboarding/access-revocation-tasks/{id}` | Fetch one task | ITOperator, ITVerifier, ITManager, HRPartner |
| GET | `/offboarding/offboarding-cases/{id}/access-revocation-tasks` | Sub-resource listing of a case's revocation tasks | ITOperator, ITVerifier, ITManager, HRPartner |
| POST | `/offboarding/access-revocation-tasks/{id}/execute` | Execute (or fail) a READY revocation task | ITOperator |
| POST | `/offboarding/access-revocation-tasks/{id}/verify` | Verify (or reject) an EXECUTED revocation task; SoD-3 | ITVerifier |
| POST | `/offboarding/access-revocation-tasks/{id}/retry` | Schedule a retry of a FAILED task with growing backoff | ITOperator |
| POST | `/offboarding/access-revocation-tasks/{id}/waive` | Waive a task after the retry cap is reached | ITManager |
| GET | `/offboarding/manager-notifications` | List notifications; filter by case, kind, suppressed | Manager, HRPartner, HRDirector |
| GET | `/offboarding/offboarding-cases/{id}/manager-notifications` | Sub-resource listing of a case's notifications | Manager, HRPartner, HRDirector |
| POST | `/offboarding/asset-return-items` | Register an asset to track for a case | AssetClerk |
| GET | `/offboarding/asset-return-items` | List asset items; filter by case, status, deduction status | AssetClerk, PayrollSpecialist, HRPartner, Manager |
| GET | `/offboarding/asset-return-items/{id}` | Fetch one asset item | AssetClerk, PayrollSpecialist, HRPartner, Manager |
| GET | `/offboarding/offboarding-cases/{id}/asset-return-items` | Sub-resource listing of a case's asset items | AssetClerk, PayrollSpecialist, HRPartner, Manager |
| POST | `/offboarding/asset-return-items/{id}/record-return` | Record physical return of an asset; OCC-guarded; may compute a deduction | AssetClerk |
| POST | `/offboarding/asset-return-items/{id}/mark-defaulted` | Mark an overdue asset defaulted; applies deduction and cascades to the statement | PayrollSpecialist |
| POST | `/offboarding/asset-return-items/{id}/waive` | Waive an asset item and any computed or applied deduction | AssetClerk |
| GET | `/offboarding/final-pay-statements` | List statements; filter by case, status | PayrollSpecialist, HRPartner, HRDirector |
| GET | `/offboarding/final-pay-statements/{id}` | Fetch one statement | PayrollSpecialist, HRPartner, HRDirector |
| GET | `/offboarding/offboarding-cases/{id}/final-pay-statements` | Sub-resource listing of a case's statements (0 or 1 element) | PayrollSpecialist, HRPartner, HRDirector |
| POST | `/offboarding/final-pay-statements/{id}/calculate` | Calculate PTO payout, deductions, and net pay; OCC-guarded | PayrollSpecialist |
| POST | `/offboarding/final-pay-statements/{id}/recalculate` | Recompute a CALCULATED statement through the DRAFT revision loop | PayrollSpecialist |
| POST | `/offboarding/final-pay-statements/{id}/approve` | Approve a CALCULATED statement; SoD-2; cascades the case toward clearance | PayrollSpecialist |
| POST | `/offboarding/final-pay-statements/{id}/disburse` | Disburse an APPROVED statement; past-due disbursement lands in LATE | PayrollSpecialist |
| POST | `/offboarding/exit-interviews` | Schedule an exit interview for a case | HRPartner |
| GET | `/offboarding/exit-interviews` | List interviews; filter by case, status | HRPartner, HRDirector, Manager |
| GET | `/offboarding/exit-interviews/{id}` | Fetch one interview | HRPartner, HRDirector, Manager |
| GET | `/offboarding/offboarding-cases/{id}/exit-interviews` | Sub-resource listing of a case's interviews | HRPartner, HRDirector, Manager |
| POST | `/offboarding/exit-interviews/{id}/request-reschedule` | Begin a reschedule cycle | HRPartner |
| POST | `/offboarding/exit-interviews/{id}/reschedule` | Apply a new window (from RESCHEDULE_REQUESTED or NO_SHOW) | HRPartner |
| POST | `/offboarding/exit-interviews/{id}/complete` | Complete an interview | HRPartner |
| POST | `/offboarding/exit-interviews/{id}/decline` | Record the employee declining the interview | HRPartner |
| POST | `/offboarding/exit-interviews/{id}/cancel` | Cancel an interview | HRPartner |
| GET | `/offboarding/knowledge-transfer-plans` | List plans; filter by case, status | Manager, HRPartner, HRDirector |
| GET | `/offboarding/knowledge-transfer-plans/{id}` | Fetch one plan | Manager, HRPartner, HRDirector |
| GET | `/offboarding/offboarding-cases/{id}/knowledge-transfer-plans` | Sub-resource listing of a case's plans (0 or 1 element) | Manager, HRPartner, HRDirector |
| POST | `/offboarding/knowledge-transfer-plans/{id}/activate` | Activate a DRAFT plan | Manager |
| POST | `/offboarding/knowledge-transfer-plans/{id}/complete` | Explicitly complete a plan (required when zero sessions are required) | Manager |
| POST | `/offboarding/knowledge-transfer-plans/{id}/waive` | Waive the plan | Manager |
| POST | `/offboarding/knowledge-transfer-sessions` | Schedule a knowledge transfer session under a plan | Manager |
| GET | `/offboarding/knowledge-transfer-sessions` | List sessions; filter by plan, status | Manager, HRPartner, HRDirector |
| GET | `/offboarding/knowledge-transfer-plans/{id}/knowledge-transfer-sessions` | Sub-resource listing of a plan's sessions | Manager, HRPartner, HRDirector |
| POST | `/offboarding/knowledge-transfer-sessions/{id}/complete` | Complete a session; bumps plan progress and may auto-complete the plan | Manager |
| POST | `/offboarding/knowledge-transfer-sessions/{id}/cancel` | Cancel a session | Manager |
| POST | `/offboarding/benefits-notices` | Create a notice in DRAFT for a case | BenefitsAdministrator |
| GET | `/offboarding/benefits-notices` | List notices; filter by case, status, kind | BenefitsAdministrator, HRPartner, HRDirector |
| GET | `/offboarding/benefits-notices/{id}` | Fetch one notice | BenefitsAdministrator, HRPartner, HRDirector |
| GET | `/offboarding/offboarding-cases/{id}/benefits-notices` | Sub-resource listing of a case's notices | BenefitsAdministrator, HRPartner, HRDirector |
| POST | `/offboarding/benefits-notices/{id}/send` | Send a QUEUED notice before its deadline | BenefitsAdministrator |
| POST | `/offboarding/benefits-notices/{id}/acknowledge` | Acknowledge a SENT notice | BenefitsAdministrator |
| POST | `/offboarding/benefits-notices/{id}/report-failure` | Report vendor rejection of a SENT notice | BenefitsAdministrator |
| POST | `/offboarding/benefits-notices/{id}/requeue` | Requeue a FAILED notice below the failure cap | BenefitsAdministrator |
| POST | `/offboarding/benefits-notices/{id}/escalate` | Escalate a FAILED notice at the failure cap | BenefitsAdministrator |
| POST | `/offboarding/restrictive-covenant-acks` | Create a covenant acknowledgment requirement for a case | HRPartner |
| GET | `/offboarding/restrictive-covenant-acks` | List covenant acknowledgments; filter by case, status | HRPartner, HRDirector, Manager |
| GET | `/offboarding/offboarding-cases/{id}/restrictive-covenant-acks` | Sub-resource listing of a case's covenant acknowledgments | HRPartner, HRDirector, Manager |
| POST | `/offboarding/restrictive-covenant-acks/{id}/acknowledge` | Record employee acknowledgment of post-employment obligations | HRPartner |
| POST | `/offboarding/restrictive-covenant-acks/{id}/mark-not-applicable` | Mark a covenant not applicable (INTAKE or APPROVED cases only) | HRPartner |
| GET | `/offboarding/rehire-eligibility-reviews` | List reviews; filter by case, status | HRReviewer, HRDirector, HRPartner |
| GET | `/offboarding/rehire-eligibility-reviews/{id}` | Fetch one review | HRReviewer, HRDirector, HRPartner |
| GET | `/offboarding/offboarding-cases/{id}/rehire-eligibility-reviews` | Sub-resource listing of a case's reviews (0 or 1 element) | HRReviewer, HRDirector, HRPartner |
| POST | `/offboarding/rehire-eligibility-reviews/{id}/submit` | Submit (or resubmit) a rehire review | HRReviewer |
| POST | `/offboarding/rehire-eligibility-reviews/{id}/finalize` | Finalize a submitted review; SoD-4 | HRDirector |
| POST | `/offboarding/rehire-eligibility-reviews/{id}/return` | Return a submitted review for rework | HRDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the rules that raise them; this table is only an index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SOD_VIOLATION` | 422 |
| `ERR_TEMPORAL_INVALID` | 422 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_SCHEDULE_OVERLAP` | 422 |
| `ERR_RETRY_CAP_EXCEEDED` | 422 |
| `ERR_SEQUENCE_GATE` | 422 |
| `ERR_FISCAL_INVALID` | 422 |
| `ERR_DEADLINE_MISSED` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION_GENERIC` | 412 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_STALE_STATEMENT_VERSION` | 412 |
| `ERR_STALE_ASSET_VERSION` | 412 |
| `ERR_CASE_TERMINAL` | 409 |
