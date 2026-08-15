# Model Risk Management API — Product Requirements Document

## 1. Introduction

A bank's model risk group is accountable for every quantitative model that drives pricing, credit, capital, or compliance decisions — from the day a developer registers the model in the inventory to the day it is retired in favor of a replacement. Regulators expect the group to demonstrate, at any moment, that each model in production is properly documented, independently validated, monitored against breach thresholds, and carrying no unremediated critical findings. This document specifies the Model Risk Management (MRM) API, the system of record through which that accountability is enforced.

The API covers the full model risk lifecycle: inventory registration with composite risk tiering, development documentation standards with segregation-of-duties review, change control guarded by optimistic concurrency, independent validation engagements with a retest loop, findings with severity- and tier-driven remediation deadlines, ongoing monitoring with automatic breach escalation, vendor model transparency gates, and board and regulatory reporting. Because remediation deadlines, escalation grace periods, and vendor assessment expiries all depend on the passage of time, the server runs on a controllable logical clock rather than wall-clock time, and all time-based rules in this document are evaluated against that clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. A request missing either header, or whose role header does not name one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the role is valid but not authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `ModelOwner` — a business-unit model developer or owner. Registers models (becoming their owner), submits documentation packages and change requests, registers monitoring metrics and records readings, and resolves breach events — in each write case only on models they own.
- `ModelValidator` — the independent validation unit. Opens, completes, and reopens validation engagements, and raises findings. Validation must be independent of development, so a validator may never act on a model they own.
- `ModelRiskOfficer` — the head of model risk. Approves and retires models, decides documentation packages and change requests, closes and reopens findings, records vendor transparency assessments, and raises findings.
- `RegulatoryReporter` — the regulatory reporting liaison. Drafts and submits board and regulator reports.
- `PlatformAdmin` — the test-harness operator. Drives the logical clock and nothing else.

All four business roles (`ModelOwner`, `ModelValidator`, `ModelRiskOfficer`, `RegulatoryReporter`) may use every read endpoint; `PlatformAdmin` has no read or write access to business resources.

For every role — `ModelOwner`, `ModelValidator`, `ModelRiskOfficer`, `RegulatoryReporter`, and `PlatformAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on resources where workflows require attribution — as `owner_user_id` on a Model at registration, as `submitted_by_user_id` on documentation and change requests, as `validator_user_id` on engagements, as `decided_by_user_id` on decisions, and as `raised_by_user_id` on findings — but it is never compared against any entity's `id`. Ownership and segregation-of-duties checks compare these recorded attribution fields against the caller's `X-User-ID`, as detailed in §2.9.

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

All list endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more`. Lists are sorted by `created_at` in ascending order unless a more specific ordering is stated for the resource; metric readings are returned in chronological observation order. The optional filter parameters each list accepts (for example `status`, `risk_tier`, or `severity`) are introduced alongside the workflows that produce those resources in §3.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` — a UUID with no type prefix. Resources are stamped with `created_at` at creation and `updated_at` on every mutation, both ISO 8601 UTC timestamps with three fractional digits. Every resource except one also carries a `version`, an integer that increments on every mutation of that resource. The single exception is the metric reading: readings are an append-only event log and carry only `id` and `created_at`; both `updated_at` and `version` are absent, because a recorded reading is never modified.

### 2.5. The Logical Clock and Its Scheduled Sweeps

The server evaluates every temporal rule in this document against a logical clock, never against wall-clock time. At startup, before the clock has ever been set, the logical clock reads exactly 2026-08-01T00:00:00Z, and the server must not fall back to wall-clock time under any circumstance. A `PlatformAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Wherever this document says "now", it means the logical clock.

Advancing the clock triggers a sweep with three effects, each detailed with its workflow in §3: findings past their remediation deadline move from `OPEN` to `OVERDUE`; overdue findings past their escalation grace period move from `OVERDUE` to `ESCALATED`, which can cascade into model suspension and metric pausing; and vendor transparency assessments past their validity horizon flip from `CURRENT` to `EXPIRED`.

### 2.6. Optimistic Concurrency Control

Exactly one write is guarded by optimistic concurrency control: submitting a change request against a model. The request must carry `expected_model_version`, a non-optional field holding the model `version` the client last observed. If that value does not equal the model's current `version` — because another writer has advanced the model since the client read it — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client never acts on an outdated view of the model. Change requests are allowed to coexist: a second, sequential submission carrying a freshly observed version legitimately succeeds. The version check runs after resource existence has been established but before any state or business rule is evaluated. No other endpoint accepts a version field.

### 2.7. Numeric Precision, Rounding, and Comparison Conventions

Risk scores, findings penalties, finding counts, and remediation deadline day-counts are integer arithmetic with no rounding, except that the tier multiplication inside the remediation deadline calculation is rounded half-up to a whole number of days — and that rounding applies to the multiplication only. The inventory risk index on regulatory reports is expressed to exactly 2 decimal places, rounded half-up, with a single final rounding at the end of the computation and no intermediate rounding. Breach detection uses exact numeric comparison with no rounding: a reading equal to its metric's threshold is never a breach, regardless of direction. All timestamps are ISO 8601 UTC with three fractional digits.

### 2.8. Request Validation Pipeline

Every request passes through a fixed pipeline of validation stages, and a rejection at an earlier stage masks every later stage — the caller always sees the earliest applicable error. The stages, in order, are:

1. **Header context.** `X-User-ID` and `X-User-Role` must be present and the role must be declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Request-body shape.** Required fields must be present, types must be correct, and enum values must be in range; this stage also covers the engagement scope rule (at least one scope flag selected) and the period rule (period end strictly after period start). Violations yield `ERR_INVALID_REQUEST` (HTTP 400).
3. **Role authorization.** The role must appear in the endpoint's authorized list, else `ERR_FORBIDDEN_ROLE` (HTTP 403).
4. **Existence.** Path parameters — the model `id` first, then any nested child identifier such as `docId`, `crId`, or `fid` — are resolved strictly left to right; identifiers referenced in the request body, such as `replacement_model_id` or `metric_id`, are resolved at their own existence step. Any unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404).
5. **Version guard.** Where §2.6 applies, `expected_model_version` must equal the model's current `version`, else `ERR_STALE_VERSION` (HTTP 412) — before any state or business rule.
6. **Ownership.** Owner-scoped writes require the caller to own the model, else `ERR_NOT_MODEL_OWNER` (HTTP 403).
7. **State gates.** The target resource must be in a state that admits the operation, else the operation-specific state error (HTTP 409).
8. **Safety gates.** Segregation-of-duties, critical-findings, and vendor-transparency gates (`ERR_SOD_VALIDATION_INDEPENDENCE`, `ERR_SOD_DOCUMENTATION_APPROVAL` at HTTP 403; `ERR_OPEN_CRITICAL_FINDINGS`, `ERR_VENDOR_ASSESSMENT_NOT_CURRENT` per §5).
9. **Temporal gates.** Validation currency and reading chronology (`ERR_VALIDATION_OVERDUE`, `ERR_READING_OUT_OF_ORDER`).
10. **Referential gates.** Cross-entity evidence requirements (`ERR_NO_APPROVED_DOCUMENTATION`, `ERR_NO_COMPLETED_VALIDATION`, `ERR_RETEST_REQUIRED`, `ERR_REPLACEMENT_MODEL_NOT_APPROVED`).
11. **Constraint gates.** Window and period overlaps, self-replacement, vendor-only assessments, and documentation completeness (`ERR_VALIDATION_WINDOW_OVERLAP`, `ERR_REPORT_PERIOD_OVERLAP`, `ERR_SELF_REPLACEMENT`, `ERR_NOT_A_VENDOR_MODEL`, `ERR_DOCUMENTATION_INCOMPLETE`).

### 2.9. Segregation of Duties and Ownership

Two independence rules are enforced as safety gates. A validation engagement may only be opened by a `ModelValidator` whose `X-User-ID` differs from the model's `owner_user_id`; a validator acting on their own model is rejected with `ERR_SOD_VALIDATION_INDEPENDENCE` (HTTP 403). A documentation package may only be decided by a `ModelRiskOfficer` whose `X-User-ID` differs from the package's `submitted_by_user_id`; an officer deciding their own submission is rejected with `ERR_SOD_DOCUMENTATION_APPROVAL` (HTTP 403).

Five owner-scoped writes require the caller's `X-User-ID` to equal the owning model's `owner_user_id`, failing with `ERR_NOT_MODEL_OWNER` (HTTP 403) otherwise: submitting a documentation package, submitting a change request, registering a monitoring metric, recording a reading (ownership of the metric's model), and resolving a breach event. Ownership is evaluated after the version guard and before state gates, per the pipeline in §2.8.

## 3. Business Logic & Workflows

### 3.1. Model Registration and Initial Risk Tiering

A `ModelOwner` registers a model by supplying its `name`, `business_unit`, `declared_complexity` (one of `LOW`, `MEDIUM`, `HIGH`), `usage_scope` (one of `SINGLE_DESK`, `MULTI_DESK`, `ENTERPRISE`), and `exposure_amount` — the dollar exposure the model drives, an integer number of dollars of zero or more. An optional `is_vendor_model` flag, defaulting to false, marks the model as externally supplied. At registration the server records the caller's `X-User-ID` as `owner_user_id`, sets `status` to `REGISTERED`, and leaves `assessed_complexity`, `last_validated_at`, and `replaced_by_model_id` unset. Every child record later created under the model — documentation, change requests, engagements, findings, metrics, vendor assessments — carries a system-assigned `model_id` pointing back to it. The model list endpoint supports optional filtering by `status`, `risk_tier`, `owner_user_id`, and `replaced_by_model_id`.

Registration computes the first `risk_score` under the developer-declared variant. Complexity contributes points — `LOW` counts as one, `MEDIUM` as two, `HIGH` as three — as does usage scope: `SINGLE_DESK` counts as zero, `MULTI_DESK` as one, `ENTERPRISE` as two. Exposure points come from `exposure_amount`: one point when exposure is below one million dollars; two when it is at least one million but below ten million; three when it is at least ten million but below one hundred million; four when it is at least one hundred million. A findings penalty is added on top: ten points per open finding of severity `CRITICAL`, five per `HIGH`, two per `MEDIUM`, and one per `LOW`, where a finding counts as open while its status is `OPEN`, `OVERDUE`, or `ESCALATED`; `CLOSED` findings never contribute. The developer-declared score is then twenty times the complexity points of `declared_complexity`, plus ten times the scope points, plus ten times the exposure points, plus the findings penalty — and if that total exceeds the cap of 100, the score is 100.

Once any validation engagement completes, the validator-assessed variant applies from that moment forward: the computation is identical except that the complexity term is twenty-five times the complexity points of `assessed_complexity` rather than twenty times the declared figure, so the same model inputs can yield a different score and tier. Any change in the model's open-findings set — a finding created, closed, reopened, or transferred in — recomputes whichever variant is currently active. The model's `risk_tier` derives from the score: `TIER_1` when the score is at least 70, `TIER_2` when it is at least 40 but below 70, and `TIER_3` when it is below 40.

The tier drives the revalidation calendar. A model's `validation_due_at` is anchored to `last_validated_at` when set, otherwise to `created_at`, and equals the anchor plus the tier's revalidation interval: six months for `TIER_1`, twelve months for `TIER_2`, twenty-four months for `TIER_3`. The due date is recomputed whenever the tier changes and whenever a validation completes. A model's validation is overdue when the logical clock reads strictly after `validation_due_at`; at the exact due instant it is not yet overdue. A freshly registered model starts with `monitoring_posture` of `NORMAL` and an `open_findings_count` of zero.

### 3.2. Development Documentation Standards and Review Decisions

Documentation packages evidence the development standards behind a model. The owning `ModelOwner` submits a package carrying a free-form `version_label` and three evidence flags — `has_development_evidence`, `has_testing_evidence`, and `has_data_lineage` — all three of which must be present and true at creation; a package missing any of them is rejected with `ERR_DOCUMENTATION_INCOMPLETE` (HTTP 409). Submission is impossible on a retired model (`ERR_MODEL_ALREADY_RETIRED`), and the server records the submitter's `X-User-ID` as `submitted_by_user_id`. A new package starts in `SUBMITTED`.

Decisions belong to a `ModelRiskOfficer`, who supplies a `decision` of either `APPROVE` or `REJECT`. Two gates apply, in pipeline order: the package must still be `SUBMITTED` — deciding an already-decided package fails with `ERR_DOCUMENTATION_NOT_SUBMITTED` — and then the segregation-of-duties gate of §2.9 forbids the officer from deciding their own submission. Approval moves the package to `APPROVED` and, in the same operation, moves every other `APPROVED` package of the same model to `SUPERSEDED`, so at most one approved package exists per model at any time. Rejection moves the package to `REJECTED`. Both `REJECTED` and `SUPERSEDED` are terminal, and the deciding officer's identity is recorded as `decided_by_user_id`. The documentation list for a model can be filtered by `status`.

### 3.3. Change Control Under Version Guard

Materiality drives change control: the owning `ModelOwner` submits a change request with a `change_type` of `MINOR` or `MAJOR` and a free-text `description`. Because change requests must never be written against a stale view of the model, the submission also carries `expected_model_version` per §2.6; a mismatch with the model's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Submission is impossible on a retired model (`ERR_MODEL_ALREADY_RETIRED`). Each successfully created change request increments the model's `version` by one — which is precisely why a second submission carrying the same expected version fails: the first submission itself advanced the model. The request starts in `SUBMITTED` with `submitted_by_user_id` recorded; the change-request list can be filtered by `status`.

A `ModelRiskOfficer` decides a change request with a `decision` of `APPROVE` or `REJECT`. Only a `SUBMITTED` request is decidable; any second decision attempt fails with `ERR_CHANGE_REQUEST_ALREADY_DECIDED`. The officer's identity is recorded as `decided_by_user_id`, and the decision itself also increments the model's `version` by one. Approving a `MAJOR` request compresses the model's revalidation calendar: `validation_due_at` becomes the earlier of its current value and three months from the decision time, so a major change can bring revalidation forward but never push it out. Approving a `MINOR` request and rejecting either kind leave the calendar untouched.

### 3.4. Independent Validation Engagements and the Retest Loop

Independent validation begins when a `ModelValidator` opens an engagement against a model, choosing its scope through `scope_conceptual_soundness` and `scope_outcomes_analysis` — at least one of the two must be selected — and fixing a review window with `period_start` and `period_end`, where the end must be strictly after the start. Scope and period violations are request-shape failures (`ERR_INVALID_REQUEST`). Review windows are treated as half-open intervals: a window includes its `period_start` and excludes its `period_end`, so a new engagement whose start exactly equals an existing engagement's end does not overlap it; any true overlap with another engagement of the same model is rejected with `ERR_VALIDATION_WINDOW_OVERLAP`. Before the constraint gate, three earlier gates apply in pipeline order: the model must not be retired (`ERR_MODEL_ALREADY_RETIRED`), the validator must be independent of the owner (`ERR_SOD_VALIDATION_INDEPENDENCE`), and the model must have at least one `APPROVED` documentation package (`ERR_NO_COMPLETED_VALIDATION`'s sibling gate, `ERR_NO_APPROVED_DOCUMENTATION`). The creating validator's `X-User-ID` is stored as `validator_user_id`, and the engagement is born in `TESTING` with `outcome`, `assessed_complexity`, and `completed_at` unset.

Completing an engagement — allowed only while it is in `TESTING`, else `ERR_ENGAGEMENT_NOT_IN_TESTING` — records the validator's `outcome` (one of `EFFECTIVE`, `EFFECTIVE_WITH_FINDINGS`, or `INEFFECTIVE`) and `assessed_complexity` (`LOW`, `MEDIUM`, or `HIGH`), stamps `completed_at` with the logical-clock now, and moves the engagement to `COMPLETED`. Completion ripples into the model: the model's `assessed_complexity` takes the engagement's value, `last_validated_at` becomes the completion timestamp, `risk_score` is recomputed under the validator-assessed variant of §3.1, `risk_tier` is re-derived, and `validation_due_at` is reset to the completion time plus the new tier's revalidation interval.

Retesting is a first-class cycle rather than an exception. Reopening — allowed only from `COMPLETED`, else `ERR_ENGAGEMENT_NOT_COMPLETED` — returns the engagement to `TESTING` and clears `completed_at` and `outcome` back to unset, but deliberately does not revert the model: `last_validated_at`, `assessed_complexity`, and the derived `risk_score` all remain as the last completion left them. The engagement list of a model can be filtered by `status`.

### 3.5. Approval for Use and Vendor Transparency Gates

Approving a model moves it from `REGISTERED` to `APPROVED_FOR_USE` and is the most heavily gated transition in the system. A `ModelRiskOfficer` triggers it, and the gates fire in the pipeline order of §2.8: first the state gate — the model must be `REGISTERED`, else `ERR_MODEL_NOT_APPROVABLE`; then the safety gates — no finding on the model may be open (status `OPEN`, `OVERDUE`, or `ESCALATED`) with severity `CRITICAL`, else `ERR_OPEN_CRITICAL_FINDINGS`, and a vendor model must hold a current transparency assessment of sufficient completeness, else `ERR_VENDOR_ASSESSMENT_NOT_CURRENT`; then the temporal gate — the model's validation must still be current, meaning the logical clock reads on or before `validation_due_at`, else `ERR_VALIDATION_OVERDUE`; and finally the referential evidence gates — at least one `APPROVED` documentation package must exist, else `ERR_NO_APPROVED_DOCUMENTATION`, and at least one `COMPLETED` validation engagement whose `outcome` is not `INEFFECTIVE` must exist, else `ERR_NO_COMPLETED_VALIDATION`.

Vendor transparency is managed through assessments that a `ModelRiskOfficer` records with a `completeness_score` — an integer from 0 to 100 — and a `valid_months` validity period of at least one whole month. Assessments exist only for models registered with `is_vendor_model` true; recording one for any other model fails with `ERR_NOT_A_VENDOR_MODEL`. At recording, `assessed_at` is stamped with the logical-clock now, `valid_until` is computed as `assessed_at` plus `valid_months` months, and the assessment starts in `CURRENT`. The clock sweep flips an assessment to the terminal `EXPIRED` once the logical clock reads strictly after `valid_until`; at exactly `valid_until` the assessment is still current. The approval gate above is satisfied only by an assessment that is both `CURRENT` and carries a `completeness_score` of at least 70. The assessment list of a model can be filtered by `status`.

### 3.6. Findings: Remediation Deadlines, Escalation, and Closure

Findings are the remediation currency of the model risk group. A `ModelValidator` or `ModelRiskOfficer` raises one on any non-retired model by supplying a `severity` (`LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`) and a short `title`. A manually raised finding is stamped with `source` `VALIDATION` and the raiser's `X-User-ID` as `raised_by_user_id`, and starts in `OPEN`. (A second origin, the monitoring cascade of §3.7, stamps `source` `MONITORING` and the literal string 'system' as `raised_by_user_id`.) Raising a finding increments the model's `open_findings_count` — defined as the number of findings on the model whose status is `OPEN`, `OVERDUE`, or `ESCALATED` — by one and recomputes the model's `risk_score` and `risk_tier`, since the findings penalty of §3.1 has grown.

Every finding receives its `remediation_due_at` once, at creation. The computation starts from a base allowance by severity — ninety days for `LOW`, sixty for `MEDIUM`, thirty for `HIGH`, fourteen days (two weeks) for `CRITICAL` — then multiplies that base by a tier factor: one times for a `TIER_1` model, one and a half times for `TIER_2`, and double for `TIER_3`, with the product rounded half-up to a whole number of days. When the finding's `source` is `MONITORING`, five days are then deducted as an urgency adjustment. The result is clamped into a corridor: fewer than seven days becomes seven, more than three hundred sixty-five becomes three hundred sixty-five. The deadline is the finding's `created_at` plus that many days. Two pinning rules make deadlines stable: the tier used is the owning model's `risk_tier` at the moment of creation, evaluated before the new finding itself is counted into the model's findings penalty, so a finding never shifts the tier that sets its own deadline; and later tier changes never move an existing deadline.

The logical clock drives the escalation ladder. When a sweep finds an `OPEN` finding whose `remediation_due_at` is strictly in the past, the finding becomes `OVERDUE` — at exactly the due instant it is not yet overdue. When a sweep finds an `OVERDUE` finding whose deadline plus a grace of seven days is strictly in the past, the finding becomes `ESCALATED` and `escalated_at` is stamped — at exactly the deadline plus seven days it is not yet escalated. Escalation can cascade: when the escalating finding has severity `HIGH` or `CRITICAL`, and its model is `TIER_1`, and the model is currently `APPROVED_FOR_USE`, the model is immediately suspended and every `ACTIVE` monitoring metric on it is paused, as detailed in §3.8.

Closing a finding is a `ModelRiskOfficer` action available from `OPEN`, `OVERDUE`, or `ESCALATED`; closing one already `CLOSED` fails with `ERR_FINDING_NOT_CLOSABLE`. For `HIGH` and `CRITICAL` findings, closure additionally requires retest evidence: a `COMPLETED` validation engagement on the same model whose `completed_at` is after the finding's `created_at`, failing with `ERR_RETEST_REQUIRED` when none exists. Closure stamps `closed_at`, decrements `open_findings_count` by one, recomputes `risk_score` and `risk_tier` with the penalty reduced, and refreshes `validation_due_at` if the tier changed. Closure also triggers the auto-resume check of §3.8.

Reopening — a `ModelRiskOfficer` action allowed only from `CLOSED`, else `ERR_FINDING_NOT_OPEN` — returns the finding to `OPEN`, clears `closed_at` back to unset, and leaves `remediation_due_at` unchanged: the original deadline is preserved, not extended. The model's `open_findings_count` is incremented, `risk_score` and `risk_tier` are recomputed with the penalty restored, and `validation_due_at` is refreshed if the tier changed. If the preserved deadline already lies in the past, the next clock sweep moves the reopened finding straight to `OVERDUE` again. The findings list of a model can be filtered by `status` and by `severity`.

### 3.7. Ongoing Monitoring: Metrics, Readings, and Breach Events

Once a model is `APPROVED_FOR_USE`, its owner registers ongoing monitoring metrics. Each metric carries a `metric_name` (an identifier such as 'psi' or 'auc'), a `direction` of `ABOVE_IS_BREACH` or `BELOW_IS_BREACH`, and a numeric `threshold_value`. Registration on a retired model fails with `ERR_MODEL_ALREADY_RETIRED`; on a live model that is not `APPROVED_FOR_USE` it fails with `ERR_MODEL_NOT_APPROVED_FOR_USE`. A new metric starts `ACTIVE` with `consecutive_breach_count` zero.

Readings are recorded by the owner of the metric's model with a `value` and an `observed_at` timestamp, and each reading is stamped with the `metric_id` of its metric. Two admission gates apply in pipeline order: the metric must be `ACTIVE` — readings on a `PAUSED` or `DECOMMISSIONED` metric fail with `ERR_METRIC_NOT_ACTIVE` — and readings must arrive in chronological order, meaning `observed_at` must not precede the `observed_at` of the metric's most recent reading (equal timestamps are acceptable), failing with `ERR_READING_OUT_OF_ORDER` otherwise. Readings are append-only: per §2.4 they carry no `updated_at` and no `version`, and they are never modified after recording.

Breach evaluation happens at recording time with strict comparisons. For a metric whose `direction` is `ABOVE_IS_BREACH`, a reading breaches when its `value` is strictly greater than `threshold_value`; for `BELOW_IS_BREACH`, when `value` is strictly less than `threshold_value`. Equality is never a breach under either direction. The outcome is stored on the reading as `is_breach`. A breaching reading increments the metric's `consecutive_breach_count` by one and opens a `BreachEvent` in `OPEN` status, which snapshots the metric's `metric_name`, the breaching `breach_value`, and the `reading_id` of the causing reading for traceability. A non-breaching reading resets `consecutive_breach_count` to zero.

The third consecutive breach is the escalation point: when `consecutive_breach_count` reaches exactly three, the system auto-raises a finding on the metric's model — severity `HIGH`, `source` `MONITORING`, `raised_by_user_id` the literal string 'system', and a `title` of the form "AUTO: 3 consecutive breaches on " followed by the metric's `metric_name`. That finding flows through the standard machinery of §3.6, including the five-day monitoring urgency deduction in its deadline and the model risk recomputation. A fourth or further consecutive breach opens another `BreachEvent` but does not auto-raise another finding — the auto-raise fires only on the transition to exactly three. Breach events remain `OPEN` until the model's owner resolves them; resolving one that is already `RESOLVED` fails with `ERR_BREACH_EVENT_ALREADY_RESOLVED`, and resolution by anyone but the owner fails with `ERR_NOT_MODEL_OWNER`. The model's `monitoring_posture` is derived from breach events alone: it is `BREACHED` while at least one `OPEN` breach event exists on any metric of the model, and returns to `NORMAL` only when none remain — which is why every breach and every resolution recomputes it.

Metrics follow their model's fate, as §3.8 details: suspension moves every `ACTIVE` metric to `PAUSED`, resumption returns every `PAUSED` metric to `ACTIVE`, and retirement moves any `ACTIVE` or `PAUSED` metric to the terminal `DECOMMISSIONED`. The metric list and the breach-event list can each be filtered by `status`, and the readings list of a metric is returned in chronological observation order.

### 3.8. Suspension, Resumption, and Retirement with Replacement

Suspension is never manual: a model moves from `APPROVED_FOR_USE` to `SUSPENDED` only through the escalation cascade of §3.6 — a finding of severity `HIGH` or `CRITICAL` escalating on a `TIER_1` model that is currently `APPROVED_FOR_USE`. Suspension pauses the model's monitoring: every `ACTIVE` metric transitions to `PAUSED`, and a paused metric admits no new readings.

Resumption is likewise automatic. Immediately after any finding on a `SUSPENDED` model transitions to `CLOSED`, the auto-resume check runs: if no finding remains on the model with status `OPEN`, `OVERDUE`, or `ESCALATED` and severity `HIGH` or `CRITICAL`, the model returns to `APPROVED_FOR_USE` and every `PAUSED` metric returns to `ACTIVE`.

Retirement is a deliberate `ModelRiskOfficer` action that moves a model from `APPROVED_FOR_USE` or `SUSPENDED` to the terminal `RETIRED`. The request names a `replacement_model_id`, and the gates fire in the pipeline order of §2.8: first the body-referenced identifier must resolve to an existing model, else `ERR_NOT_FOUND` at the existence stage; then the state gate requires the retired model to be `APPROVED_FOR_USE` or `SUSPENDED`, else `ERR_MODEL_NOT_RETIRABLE`; then the referential gate requires the replacement itself to be `APPROVED_FOR_USE`, else `ERR_REPLACEMENT_MODEL_NOT_APPROVED`; and finally the constraint gate forbids naming the retired model as its own replacement, else `ERR_SELF_REPLACEMENT`.

Retirement rearranges the whole subgraph in one operation. The retired model's `status` becomes `RETIRED` and `replaced_by_model_id` is set to the replacement. Every metric of the retired model in `ACTIVE` or `PAUSED` status is decommissioned. Every finding of the retired model in `OPEN`, `OVERDUE`, or `ESCALATED` status is transferred to the replacement: its `model_id` is repointed, and its `remediation_due_at` is recomputed from its own `created_at` under the deadline formula of §3.6 — base days by severity, tier multiplication rounded half-up, the monitoring deduction when applicable, and the seven-to-three-hundred-sixty-five-day clamp — but evaluated against the replacement model's tier at transfer time, before the transferred findings are counted into the replacement's penalty. Finally, the retired model's `open_findings_count` drops to zero, while the replacement's `open_findings_count` is recomputed and its `risk_score` and `risk_tier` are recomputed as the transferred findings join its penalty — with `validation_due_at` refreshed if the replacement's tier moved.

### 3.9. Board and Regulatory Reporting

A `RegulatoryReporter` drafts a report by naming a `report_type` — `BOARD_QUARTERLY` or `REGULATOR_ANNUAL` — a reporting window with `period_start` and `period_end` (the end strictly after the start), and an `aggregation_method` of `EQUAL_WEIGHTED` or `EXPOSURE_WEIGHTED`. The report is created in `DRAFT`, and all of its snapshot fields are computed once at creation and never recomputed afterward, so a report is a frozen view of the inventory as it stood at creation time.

The snapshot's input set is every model whose `created_at` falls on or before the report's `period_end` and whose status is `REGISTERED`, `APPROVED_FOR_USE`, or `SUSPENDED`; `RETIRED` models are excluded. From that set the server derives: `total_models`, the count of models in the set; `tier_1_count`, those with `risk_tier` `TIER_1`; `open_findings_total`, the findings on input-set models with status `OPEN`, `OVERDUE`, or `ESCALATED`; `open_critical_count`, the same restricted to severity `CRITICAL`; `breach_event_count`, the `OPEN` breach events on metrics of input-set models; and `overdue_validation_count`, the input-set models whose `validation_due_at` lies before the report's creation time.

The headline figure is `inventory_risk_index`, computed per the chosen `aggregation_method` at exactly 2 decimal places, rounded half-up. Under `EQUAL_WEIGHTED` it is the plain arithmetic mean of the input set's `risk_score` values. Under `EXPOSURE_WEIGHTED` each model's `risk_score` is multiplied by its `exposure_amount`, the products are summed, and the total is divided by the sum of all `exposure_amount` values in the set. Rounding order is pinned: no intermediate rounding is applied anywhere — each product is kept at full precision, the division is performed once, and a single round-half-up to two decimal places happens at the very end; rounding each contribution before summing is a different, forbidden order. When the input set is empty, or when exposure weighting is requested and the set's total exposure is zero, the index is exactly 0.00.

Submitting a report — a `RegulatoryReporter` action allowed only from `DRAFT`, else `ERR_REPORT_ALREADY_SUBMITTED` — moves it to the terminal `SUBMITTED` and stamps `submitted_at` with the logical-clock now. Submission enforces a period-overlap rule within each `report_type`: no other `SUBMITTED` report of the same type may have a period that overlaps the new one. Report periods are closed intervals — both bounds inclusive — so overlap means the existing report's `period_start` falls on or before the new report's `period_end` and the new report's `period_start` falls on or before the existing report's `period_end`; two periods that merely touch at a boundary date are in conflict, unlike validation windows where adjacency is allowed. A conflicting submission is rejected with `ERR_REPORT_PERIOD_OVERLAP`. The report list can be filtered by `report_type` and by `status`.

## 4. Endpoint Definitions

All endpoints are mounted under the prefixes shown. Creating a new resource returns HTTP 201; reads, state transitions, decisions, and other modifications return HTTP 200. Request payloads, preconditions, and side effects for each endpoint are specified by the workflows in §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /mrm/models | Register a model in the inventory with its initial risk score and tier | ModelOwner |
| GET | /mrm/models | List models with optional filters | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| GET | /mrm/models/{id} | Retrieve a single model including computed fields | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| POST | /mrm/models/{id}/approve | Approve a REGISTERED model for production use | ModelRiskOfficer |
| POST | /mrm/models/{id}/retire | Retire a model, transferring open findings to an approved replacement | ModelRiskOfficer |
| POST | /mrm/models/{id}/documentations | Submit a documentation package for a model | ModelOwner |
| GET | /mrm/models/{id}/documentations | List documentation packages of a model | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| POST | /mrm/models/{id}/documentations/{docId}/decide | Approve or reject a SUBMITTED documentation package | ModelRiskOfficer |
| POST | /mrm/models/{id}/change-requests | Submit a version-guarded change request for a model | ModelOwner |
| GET | /mrm/models/{id}/change-requests | List change requests of a model | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| POST | /mrm/models/{id}/change-requests/{crId}/decide | Approve or reject a SUBMITTED change request | ModelRiskOfficer |
| POST | /mrm/models/{id}/validation-engagements | Open an independent validation engagement on a model | ModelValidator |
| GET | /mrm/models/{id}/validation-engagements | List validation engagements of a model | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| POST | /mrm/validation-engagements/{id}/complete | Complete a TESTING engagement with outcome and assessed complexity | ModelValidator |
| POST | /mrm/validation-engagements/{id}/reopen | Reopen a COMPLETED engagement for retesting | ModelValidator |
| POST | /mrm/models/{id}/findings | Raise a finding on a model | ModelValidator, ModelRiskOfficer |
| GET | /mrm/models/{id}/findings | List findings of a model with optional filters | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| POST | /mrm/models/{id}/findings/{fid}/close | Close a finding, with retest evidence required for HIGH and CRITICAL | ModelRiskOfficer |
| POST | /mrm/models/{id}/findings/{fid}/reopen | Reopen a CLOSED finding, preserving its original deadline | ModelRiskOfficer |
| POST | /mrm/models/{id}/monitoring-metrics | Register an ongoing monitoring metric on an approved model | ModelOwner |
| GET | /mrm/models/{id}/monitoring-metrics | List monitoring metrics of a model | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| GET | /mrm/monitoring-metrics/{id} | Retrieve a single monitoring metric including its breach counter | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| POST | /mrm/monitoring-metrics/{id}/readings | Record an append-only metric reading | ModelOwner |
| GET | /mrm/monitoring-metrics/{id}/readings | List readings of a metric in chronological order | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| GET | /mrm/monitoring-metrics/{id}/breach-events | List breach events of a metric | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| POST | /mrm/breach-events/{id}/resolve | Resolve an OPEN breach event | ModelOwner |
| POST | /mrm/models/{id}/vendor-assessments | Record a vendor transparency assessment | ModelRiskOfficer |
| GET | /mrm/models/{id}/vendor-assessments | List vendor transparency assessments of a model | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| POST | /mrm/regulatory-reports | Create a DRAFT report with its snapshot fields computed | RegulatoryReporter |
| GET | /mrm/regulatory-reports | List regulatory reports with optional filters | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| GET | /mrm/regulatory-reports/{id} | Retrieve a single report including its snapshot fields | ModelOwner, ModelValidator, ModelRiskOfficer, RegulatoryReporter |
| POST | /mrm/regulatory-reports/{id}/submit | Submit a DRAFT report, enforcing period-overlap exclusivity per type | RegulatoryReporter |
| POST | /_clock/set_current_utc | Set the logical clock and run the overdue, escalation, and expiry sweeps | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the workflows that raise them.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_NOT_MODEL_OWNER | 403 |
| ERR_SOD_VALIDATION_INDEPENDENCE | 403 |
| ERR_SOD_DOCUMENTATION_APPROVAL | 403 |
| ERR_MODEL_ALREADY_RETIRED | 409 |
| ERR_MODEL_NOT_APPROVABLE | 409 |
| ERR_MODEL_NOT_APPROVED_FOR_USE | 409 |
| ERR_MODEL_NOT_RETIRABLE | 409 |
| ERR_DOCUMENTATION_NOT_SUBMITTED | 409 |
| ERR_CHANGE_REQUEST_ALREADY_DECIDED | 409 |
| ERR_ENGAGEMENT_NOT_IN_TESTING | 409 |
| ERR_ENGAGEMENT_NOT_COMPLETED | 409 |
| ERR_FINDING_NOT_CLOSABLE | 409 |
| ERR_FINDING_NOT_OPEN | 409 |
| ERR_BREACH_EVENT_ALREADY_RESOLVED | 409 |
| ERR_REPORT_ALREADY_SUBMITTED | 409 |
| ERR_METRIC_NOT_ACTIVE | 409 |
| ERR_OPEN_CRITICAL_FINDINGS | 409 |
| ERR_VENDOR_ASSESSMENT_NOT_CURRENT | 403 |
| ERR_VALIDATION_OVERDUE | 409 |
| ERR_NO_APPROVED_DOCUMENTATION | 409 |
| ERR_NO_COMPLETED_VALIDATION | 409 |
| ERR_RETEST_REQUIRED | 409 |
| ERR_REPLACEMENT_MODEL_NOT_APPROVED | 409 |
| ERR_SELF_REPLACEMENT | 409 |
| ERR_VALIDATION_WINDOW_OVERLAP | 409 |
| ERR_REPORT_PERIOD_OVERLAP | 409 |
| ERR_READING_OUT_OF_ORDER | 409 |
| ERR_NOT_A_VENDOR_MODEL | 409 |
| ERR_DOCUMENTATION_INCOMPLETE | 409 |
