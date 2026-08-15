# Performance Improvement Plan API — Product Requirements Document

## 1. Introduction

Progressive discipline is among the most legally sensitive processes an HR organization runs. When informal coaching fails to correct a performance problem, the business needs a defensible, auditable path: a documented concern backed by a coaching record, a measurable improvement plan with a fixed timeline and weighted goals, cadenced check-ins supported by adjudicated evidence, legal risk assessment before any termination, and an outcome process that withstands both employee rebuttal and cross-case consistency scrutiny. Done inconsistently, the process exposes the company to retaliation and discrimination claims; done opaquely, it loses the trust of every employee who watches it happen.

This API is the system of record for that process inside an HR business-partner organization. It governs the complete pipeline — org units and their logical clocks, employees and their reporting chains, coaching log entries, performance concerns, plan templates, improvement plans and their goals, check-ins and evidence, legal reviews, outcome decisions, employee rebuttals, rating cycles, and post-hoc consistency reviews. Two commitments shape every rule that follows: strict segregation of duties, so that no individual can both author and ratify the same step, and a fully logical clock per org unit, so that every time-driven transition is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to the entire API. All resources are mounted under the `/hr-org-units` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes six roles: `HRSystemAdmin`, `Manager`, `HRBusinessPartner`, `LegalCounsel`, `HRDirector`, and `Employee`.

When `X-User-Role` is `HRSystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it against any entity's `id`. For the other five roles — `Manager`, `HRBusinessPartner`, `LegalCounsel`, `HRDirector`, and `Employee` — `X-User-ID` is the `id` of the acting Employee record, and every ownership or designated-actor check in §3 (the concern's author, the plan's issuing HRBP, the assigned counsel, the subject employee, and so on) compares the relevant foreign-key field on the resource against `X-User-ID`.

Beyond authentication, each operation is restricted to specific roles, enumerated per endpoint in §4. A caller whose role is not permitted for an endpoint — or who is not the designated actor for that step, such as the wrong manager, the wrong HRBP, the wrong counsel, or the wrong employee — is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints paginate through two query parameters. The `limit` parameter caps how many items a response returns; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including mutations driven by derived-field reconciliation, and underpins the optimistic concurrency control described in §2.8.

Three append-only record types — coaching log entries, evidence items, and rating-cycle outcome links — are immutable after creation and therefore carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.5. The Logical Clock and Time-Driven Transitions

Each org unit runs on its own logical clock, exposed as the field `current_utc`. When an org unit is created, its clock reads 2026-08-01T00:00:00Z, and it never advances on its own. An `HRSystemAdmin` moves time forward through an admin-only clock-setting capability that accepts a `to_iso8601` instant; the supplied value must be monotonically non-decreasing relative to the current reading.

Advancing the clock is the sole driver of time-based system behavior. Issued plans whose start date has been reached activate on their own; scheduled check-ins left unheld more than three days past their scheduled instant are swept to missed; extended plans re-enter their active window; and approved outcomes whose rebuttal window has lapsed finalize the plan's closure. Every business rule that compares against "now" reads this logical clock, never wall-clock time.

### 2.6. Hierarchical Addressing, Validation Order, and Flat Read Paths

Most resources are addressed through deep nesting — org unit, then employee, then the concern, plan, or template, then check-in, evidence item, legal review, outcome decision, or rebuttal. Path identifiers are validated strictly left to right: the first identifier that does not resolve to an existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404), and deeper identifiers are never consulted. When every identifier exists but a child does not belong to its declared parent — a plan under the wrong employee, an evidence item under the wrong check-in — the request fails with `ERR_PARENT_MISMATCH` (HTTP 404).

When several rules could reject the same request, the evaluation order is fixed so the surfaced error is deterministic. Header authentication runs first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role permission (`ERR_FORBIDDEN`), then left-to-right existence (`ERR_NOT_FOUND`), then parent ownership (`ERR_PARENT_MISMATCH`), then the optimistic-concurrency check of §2.8 (`ERR_STALE_VERSION`) — which is evaluated before any business rule on the plan-mutating endpoints that carry it — then target-state validity (`ERR_INVALID_STATE`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and only then the business, temporal, referential, and constraint rules detailed throughout §3.

Alongside the nested hierarchy, every child resource is also reachable through a flat collection path — for example, `/hr-org-units/pips/{pipId}` or `/hr-org-units/evidence-items` — provided as a reverse-reachability utility. Each flat list accepts the resource's foreign-key fields as optional filters: the plan list narrows by `employee_id`, `concern_id`, `template_id`, `issuing_hrbp_id`, or `status`; the evidence list by `check_in_id`, `pip_goal_id`, `submitted_by_id`, `admissibility_decided_by_id`, `admissibility`, or `source`; the concern list by `employee_id`, `raised_by_manager_id`, `decided_by_hrbp_id`, `status`, or `category`; the check-in and goal lists by `pip_id`; analogous foreign-key filters exist for the remaining collections, all in addition to the standard `limit` and `offset` parameters.

### 2.7. Segregation of Duties

No individual may author and ratify the same step of the process. Concretely: the HRBP deciding a concern must not be the manager who raised it; the HRBP proposing an outcome must not be the plan's issuing HRBP while the plan still runs under the policy version in force at its issuance; the director approving an outcome must not be its proposer; the counsel assigned to a legal review must be neither the issuing HRBP nor the raising manager; evidence submitted by the issuing HRBP must be adjudicated by a different HRBP; the HRBP reviewing a rebuttal must be neither the issuing HRBP nor the outcome's proposer; and the director adjudicating a consistency review must not be the HRBP who opened it. Every violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The exact actor constraint for each step appears alongside its workflow in §3.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field. Issuing a plan requires the request body to carry `expected_pip_version`, holding the `version` of the plan the client last observed; if the plan's current `version` has since advanced — because another writer mutated the plan after the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Approving an outcome decision carries the identical requirement: the body must contain `expected_pip_version` matching the plan's current `version`, and a mismatch is rejected with the same `ERR_STALE_VERSION` and HTTP 412, preventing a client from pinning final state onto a plan it has not observed. On both endpoints the stale-version check runs before any business rule, per the ordering in §2.6.

### 2.9. Numeric Precision and Rounding

All attainment and review scores exposed by the API — `provisional_attainment_ratio`, `final_attainment_ratio`, `outcome_disparity_score`, and `rating_alignment_score` — are rounded half-up to exactly 4 decimal places, with rounding applied once at the end of each computation and never to intermediate per-goal values. The legal `risk_score` is an integer; multiplicative steps in its computation are floored to whole numbers. Calendar arithmetic on plan windows works in whole days: a plan extension adds half the template's duration, rounded down to a whole number of days.

## 3. Business Logic & Workflows

### 3.1. Org Units, Employees, and Rating Cycles

An `HRSystemAdmin` onboards a new org unit by supplying its `name`; creation initializes the unit's logical clock per §2.5 and sets `pip_policy_version` to 1. That policy version is monotonically increasing — every template publication in the unit bumps it — and each plan snapshots it so that later policy changes never retroactively alter an in-flight plan.

Employees are provisioned into an org unit by the admin with a `full_name`, a work `email` unique within the org unit, a `job_family` of `ENGINEERING`, `SALES`, `OPERATIONS`, `SUPPORT`, or `FINANCE`, and a numeric `job_level` grade from 1 to 10; both `job_family` and `job_level` later drive cohort matching in consistency reviews. An optional `manager_id` points at another employee — the reporting chain is self-referential and nullable at the top of the chain. Every employee record carries `hr_org_unit_id` tying it to its unit. New employees start with `employment_status` of `ACTIVE`; the full lifecycle vocabulary also includes `ON_NOTICE`, `TERMINATED`, and `RESIGNED`, and a termination stamps `terminated_at`. A computed `active_pip_id` points at the employee's single in-flight plan, or is null when none exists; the server reconciles it whenever a plan enters or leaves its in-flight states.

Rating cycles give the organization its review calendar. An HRBP opens a cycle with a `label` (for example, "2026-H1"), an inclusive `window_start`, and an exclusive `window_end`; the cycle begins `OPEN`. Moving a cycle from `OPEN` to `CALIBRATION` is an HRBP action permitted only once the window has closed — a clock reading earlier than `window_end` is rejected with `ERR_CYCLE_STILL_OPEN`. From `CALIBRATION`, an HRDirector publishes the cycle, moving it to `PUBLISHED`. Archival (`PUBLISHED` → `ARCHIVED`) is also a director action, permitted only once the clock has reached at least 365 days past `window_end`; earlier attempts fail with `ERR_CYCLE_TOO_RECENT`. Any transition attempted against a cycle not in the required state fails with `ERR_INVALID_STATE`.

### 3.2. Documenting Performance Concerns and the Coaching Record

Before any formal process begins, managers build the paper trail. A `Manager` appends entries to a direct report's coaching log, and the acting user's identity must match the employee's `manager_id` — anyone else is turned away with `ERR_FORBIDDEN`. Each entry records when the conversation `occurred_at`, a `category` of `QUALITY`, `VELOCITY`, `ATTENDANCE`, `CONDUCT`, or `COLLABORATION`, a `severity` of `INFORMAL`, `DOCUMENTED`, or `ESCALATED`, and a free-text `narrative` of at least 40 characters; shorter narratives fail with `ERR_INVALID_REQUEST`. The entry's `author_manager_id` is taken from the acting user's header and its `employee_id` from the path, while `concern_id` stays empty until the entry is cited by a formal concern.

When informal coaching stalls, the employee's direct manager raises a performance concern with a `category`, a `summary` of at least 20 characters, and the `coaching_log_entry_ids` that substantiate it. The manager's identity is recorded as `raised_by_manager_id`, the concern opens in `DRAFT`, and each referenced coaching entry has its `concern_id` populated to point back at the concern.

Submitting the concern moves it `DRAFT` → `SUBMITTED` and stamps `submitted_at`. Four gates guard submission, each with its own rejection: the concern must still be `DRAFT` (`ERR_INVALID_STATE`); the acting manager must be the concern's author (`ERR_FORBIDDEN`); at least two coaching entries must be referenced (`ERR_INSUFFICIENT_COACHING_HISTORY`); every referenced entry must resolve to a coaching entry owned by the concern's own employee (`ERR_COACHING_ENTRY_MISMATCH`); and every referenced entry must carry `DOCUMENTED` or `ESCALATED` severity, since informal conversations do not substantiate a formal case (`ERR_COACHING_ENTRY_NOT_FORMAL`).

An HRBP then adjudicates the submission — and it must be an HRBP other than the manager who raised it (`ERR_SEGREGATION_OF_DUTIES`). Acceptance moves the concern `SUBMITTED` → `ACCEPTED` and additionally requires the employee to still be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); it stamps `decided_at` and `decided_by_hrbp_id` and, as a cascade, escalates every linked coaching entry's severity to `ESCALATED`. Rejection moves the concern `SUBMITTED` → `REJECTED_INSUFFICIENT`, records the same decision fields, and terminates the concern. An accepted concern then remains on file until a plan citing it is issued, at which point the concern automatically becomes `SUPERSEDED_BY_PIP` (§3.3).

### 3.3. Plan Templates and PIP Issuance

Templates keep plans consistent across the org unit. An HRBP authors a template with a `name`, a `category`, between one and five `goal_blueprints` — each blueprint a `metric_key`, `target_value`, `unit`, and `weight`, with the weights summing to exactly 100 — a `duration_days` between 30 and 180, and a `check_in_cadence_days` between 7 and 30 that must divide the duration evenly. These geometry rules are enforced at authoring and re-checked at publication: a weight-sum or range failure surfaces `ERR_TEMPLATE_WEIGHT_SUM`, and a duration that is not an even multiple of the cadence surfaces `ERR_TEMPLATE_CADENCE_MISMATCH`. A new template's `template_status` is `DRAFT`.

Publication moves a template `DRAFT` → `PUBLISHED`: the geometry checks above must pass, `published_at` is stamped from the clock, the org unit's `pip_policy_version` increments by one, and the template's `published_version` is pinned to that post-increment value. Retirement moves a `PUBLISHED` template to `RETIRED`, but is refused while any plan in `DRAFT`, `ISSUED`, `ACTIVE`, or `EXTENDED` still references it (`ERR_TEMPLATE_IN_USE`). Either transition attempted from the wrong state fails `ERR_INVALID_STATE`.

With an accepted concern and a published template in hand, an HRBP creates the plan itself by passing `concern_id`, `template_id`, and `start_date`. The referenced concern must be `ACCEPTED` and not already bound to another non-terminal plan, and the referenced template must be `PUBLISHED` — template-state failures are rejected with `ERR_TEMPLATE_NOT_PUBLISHED`, while body references that resolve but fail their state filters are rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). The employee must be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`) and must not already carry a plan in `ISSUED`, `ACTIVE`, or `EXTENDED` — the single-active-plan invariant, enforced as `ERR_ACTIVE_PIP_EXISTS`. Creation records the acting HRBP as `issuing_hrbp_id`, pins `template_published_version` from the template and `policy_version_at_issuance` from the org unit, copies the template's cadence into `check_in_interval_days`, and computes `end_date` as `start_date` plus the template's duration in days, with `end_date` itself exclusive. One goal per blueprint is materialized at creation — each stamped with the plan's `pip_id`, its `metric_key`, `target_value`, `unit`, and `weight` copied from the blueprint, `current_value` starting at 0, `goal_status` starting `PENDING`, and the weights across a plan always summing to 100 — and the plan opens in `DRAFT`.

Issuance, moving the plan `DRAFT` → `ISSUED`, is the HRBP's commitment step and is concurrency-guarded per §2.8: the request must carry `expected_pip_version`, and a stale reading is rejected with `ERR_STALE_VERSION` before any business check runs. The issuer must be the plan's own `issuing_hrbp_id` (`ERR_FORBIDDEN`); the plan must be `DRAFT` (`ERR_INVALID_STATE`); every goal must have been materialized from the template; the concern must still be `ACCEPTED` (`ERR_CONCERN_NOT_ACCEPTED`); the employee must still be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); and the single-active-plan invariant is re-checked (`ERR_ACTIVE_PIP_EXISTS`). Issuance cascades outward: the concern flips to `SUPERSEDED_BY_PIP`, the employee's `active_pip_id` is set to the plan, and the plan's `version` increments.

Activation requires no further action. Once the clock reaches `start_date` and at least one check-in stands `SCHEDULED` for the plan, the plan moves `ISSUED` → `ACTIVE` on its own.

Withdrawal is the early exit, available to the plan's issuing HRBP while the plan is `ISSUED` or `ACTIVE` — any other state fails `ERR_INVALID_STATE`, any other actor fails `ERR_FORBIDDEN` — and only while no outcome decision for the plan stands in `PROPOSED` or `APPROVED` (`ERR_OUTCOME_ALREADY_PROPOSED`). Withdrawal closes the plan as `CLOSED_WITHDRAWN`, stamps `closed_at`, clears the employee's `active_pip_id`, and flips every still-`SCHEDULED` check-in to `CANCELLED`.

### 3.4. Check-Ins, Evidence, and Attainment Tracking

Check-ins pace the plan. An HRBP schedules each one with a `scheduled_for` instant that must land no earlier than the plan's `start_date` and strictly before its `end_date`; a scheduling request outside the window is rejected with `ERR_CHECKIN_TOO_EARLY`. Adjacent check-ins must be exactly `check_in_interval_days` apart, and the 1-based `sequence_index` values must be contiguous — breaking the cadence fails with `ERR_CHECKIN_CADENCE_VIOLATION`. Each new check-in opens `SCHEDULED`.

Holding a check-in is the plan's data-collection event, performed by an HRBP. The check-in must still be `SCHEDULED` (`ERR_INVALID_STATE`), the plan must be `ACTIVE` or `EXTENDED` (`ERR_PIP_NOT_ACTIVE`), the clock must have reached `scheduled_for` (`ERR_CHECKIN_TOO_EARLY`), both `manager_attended` and `hrbp_attended`, each defaulting to false when omitted, must be true — a one-sided meeting is no check-in (`ERR_CHECKIN_QUORUM`) — and `notes` of at least 20 characters are required (`ERR_INVALID_REQUEST`). A successful hold moves the check-in `SCHEDULED` → `HELD`, stamps `held_at`, and rewrites the plan's scoreboard: for each goal, `current_value` becomes the `observed_value` of the most recent admissible evidence attached to that check-in (the latest `submitted_at` wins, ties broken by `created_at` descending), each `goal_status` is recomputed, and the plan's `provisional_attainment_ratio` is recalculated.

A check-in still unheld more than three days past `scheduled_for` is swept to `MISSED` automatically when the clock advances, and the provisional ratio is recomputed with the missed interval counting as zero progress. Withdrawal cancels any surviving scheduled check-ins per §3.3.

Goal health follows fixed thresholds. A goal whose `current_value` reaches at least its full `target_value` is `MET`; at least 70 percent of target is `ON_TRACK` — the boundary is inclusive, so exactly 0.70 maps to `ON_TRACK` while 0.6999 maps to `AT_RISK`; at least 40 percent of target is `AT_RISK`; and anything below that is `NOT_MET`. Goals begin `PENDING`, and a goal may also be `WAIVED`, which the attainment math treats specially.

Evidence attaches to check-ins. A manager or an HRBP submits an item naming the `pip_goal_id` it speaks to, the `observed_value` measured, and a `source` of `MANAGER_OBSERVATION`, `SYSTEM_REPORT`, `PEER_FEEDBACK`, or `SELF_REPORT`; the goal must belong to the same plan as the check-in, failing which the submission is rejected with `ERR_REFERENTIAL_INTEGRITY`. Each item records its `check_in_id`, the acting user as `submitted_by_id`, and the clock reading as `submitted_at`, and lands in `PENDING_REVIEW`.

Admissibility is adjudicated by an HRBP while the check-in remains `SCHEDULED` — once the check-in stands `HELD`, adjudication attempts fail with `ERR_CHECKIN_ALREADY_HELD`. Admission flips the item to `ADMISSIBLE`; exclusion flips it to `INADMISSIBLE`; either records `admissibility_decided_by_id`. When the submitting user is the plan's own issuing HRBP, a different HRBP must perform the adjudication (`ERR_SEGREGATION_OF_DUTIES`), and an item not in `PENDING_REVIEW` rejects the attempt with `ERR_INVALID_STATE`.

The attainment ratio itself is a weighted score. Each non-waived goal's attainment is its `current_value` divided by its `target_value`, clamped so it never drops below 0 or rises above 1; a waived goal counts as fully attained. The ratio is the sum of every goal's attainment multiplied by its `weight`, divided by the summed weights of the non-waived goals only, and if every goal is waived the ratio is defined as 1.0. While the plan runs, the figure is provisional: only goals backed by admissible evidence contribute their measured value, and goals without admissible evidence contribute zero attainment — although their weight still counts in the denominator. Rounding happens exactly once, half-up to 4 decimal places, after the weighted sum is formed.

### 3.5. Legal Risk Review

Before a termination outcome can be entertained, employment counsel must weigh in. An HRBP requests a legal review for a plan by naming an `assigned_counsel_id`; the assignee must be someone other than the plan's issuing HRBP and other than the manager who raised the underlying concern (`ERR_SEGREGATION_OF_DUTIES`). The request records the acting HRBP as `requested_by_hrbp_id` and the review opens in `REQUESTED`.

The assigned counsel — and only that counsel (`ERR_FORBIDDEN`) — claims the review, moving it `REQUESTED` → `IN_REVIEW`, and later submits the assessment from `IN_REVIEW`. The submission carries a set of `risk_factors` drawn from `PROTECTED_CLASS`, `RECENT_LEAVE`, `WHISTLEBLOWER_HISTORY`, `PRIOR_COMPLAINT`, `RETALIATION_WINDOW`, and `DOCUMENTATION_GAP`; a `recommendation` of `PROCEED`, `PROCEED_WITH_CAUTION`, `HOLD`, or `REJECT`; and a `rationale` of at least 40 characters. Missing any of the three fails with `ERR_INVALID_REQUEST`, and acting from the wrong state fails with `ERR_INVALID_STATE`.

Submission computes the composite `risk_score`. Each factor contributes a fixed weight: 20 for `PROTECTED_CLASS`, 15 for `RECENT_LEAVE`, 30 for `WHISTLEBLOWER_HISTORY`, 10 for `PRIOR_COMPLAINT`, 25 for `RETALIATION_WINDOW`, and 0 for `DOCUMENTATION_GAP`. The base score is the sum of the listed factors' weights. If a documentation gap is among the factors, the base is doubled — a multiplicative interaction floored to a whole number. If the resulting base is at least 50 and whistleblower history is present, a further 10 points are added as a compound trigger. The final score is clamped so it never falls below 0 or rises above 100. Submission also stamps `submitted_at`, and a `REJECT` recommendation cascades: any outcome decision still `PROPOSED` on the plan flips to `SUPERSEDED`.

An HRDirector may override counsel, but only a `SUBMITTED` review whose recommendation is `REJECT` — overriding any other recommendation fails with `ERR_LEGAL_OVERRIDE_NOT_ALLOWED`, and acting against a review in another state fails `ERR_INVALID_STATE`. An override moves the review to `OVERRIDDEN` and records the director as `decided_by_director_id`.

### 3.6. Outcome Decisions and Plan Closure

When the plan has run its course, an HRBP proposes the outcome: a `proposed_outcome` of `SUCCESS`, `EXTENSION`, or `TERMINATION`, accompanied by a `rationale` of at least 40 characters. The proposer is recorded as `proposed_by_hrbp_id` and must differ from the plan's issuing HRBP whenever the plan still runs under the policy version in force at its issuance — once the org unit's policy version has advanced past the plan's `policy_version_at_issuance`, that restriction relaxes and the issuing HRBP may propose. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Proposing a new decision also supersedes any decision still standing `PROPOSED` on the same plan, and the new decision opens in `PROPOSED`.

Proposal freezes the final attainment figure: the plan's `final_attainment_ratio` — null until this moment — is computed and snapshot into the decision's `final_attainment_ratio_at_decision`. The final variant counts every goal regardless of evidence admissibility — a goal whose latest evidence is inadmissible or absent falls back to its most recent held check-in's value if one exists, else 0 — and each missed check-in contributes a flat one-half attainment factor for its interval's goals, with the total capped so it never exceeds 1.0. Three guards attach at proposal time and again at approval: a `SUCCESS` outcome requires a final attainment ratio of at least 0.80 (`ERR_ATTAINMENT_BELOW_THRESHOLD`); an `EXTENSION` requires the plan's `extension_count` — the count of extension cycles already consumed, starting at zero — to still be below its single allowance of one (`ERR_EXTENSION_LIMIT_EXCEEDED`); and a `TERMINATION` requires a completed legal review — one in `SUBMITTED` or `OVERRIDDEN` — whose recommendation is not `REJECT`, unless that review was itself overridden (`ERR_LEGAL_REVIEW_REQUIRED`).

Approval belongs to an `HRDirector` and is concurrency-guarded per §2.8: the request carries `expected_pip_version`, and a mismatch with the plan's current `version` is rejected with `ERR_STALE_VERSION` before any business check. The decision must stand `PROPOSED` (`ERR_INVALID_STATE`), the director must not be the proposer (`ERR_SEGREGATION_OF_DUTIES`), the plan must be `ACTIVE` or `EXTENDED` (`ERR_PIP_NOT_ACTIVE`), the clock must have reached the plan's `end_date` (`ERR_PLAN_STILL_RUNNING`), and the three outcome guards above are re-applied. Approval stamps `decided_at` and `decided_by_director_id`, opens the employee's rebuttal window by setting `rebuttal_window_closes_at` to five days after `decided_at`, and increments the plan's `version`. Director rejection — under the same state and segregation checks — simply terminates the decision as `REJECTED`, recording the same two decision fields.

What approval does to the plan depends on the outcome, and every close defers to a pending rebuttal (§3.7). An approved `SUCCESS` closes the plan `CLOSED_SUCCESS` once the rebuttal window lapses with no rebuttal pending. An approved `EXTENSION` moves the plan through `EXTENDED` — a transient marker under which the plan immediately re-enters `ACTIVE` for the extension window — pushing `end_date` out by half the template's duration rounded down to whole days and incrementing `extension_count`; should an approved extension exceed the single-extension allowance, the plan instead closes `CLOSED_FAILED`. An approved `TERMINATION` closes the plan `CLOSED_TERMINATED` after the rebuttal window resolves, cascading the employee's `employment_status` to `TERMINATED` and stamping `terminated_at`. Success and termination closures additionally clear the employee's `active_pip_id`, stamp `closed_at`, and write a rating-cycle outcome link for every rating cycle in the same org unit whose window — `window_start` inclusive to `window_end` exclusive — overlaps the plan's own window and whose status is `OPEN`, `CALIBRATION`, or `PUBLISHED`. Each link records the `rating_cycle_id`, the `employee_id`, a `pip_outcome_at_link` copied from the approved decision (one of `SUCCESS`, `EXTENSION`, or `TERMINATION`), a `rating_cycle_status_at_link` snapshot of the cycle's status at link time, and the `link_created_at` instant.

### 3.7. Employee Rebuttals and Outcome Reversal

An approved outcome is not the last word. The plan's subject employee — and only that employee, with the acting identity compared against the plan's own employee (`ERR_REBUTTAL_NOT_SUBJECT`, HTTP 403) — may file a rebuttal naming the contested `outcome_decision_id` and a `body` of at least 100 characters; shorter bodies fail with `ERR_INVALID_REQUEST`. Filing must land inside the window: the clock reading at or before five days after the decision's `decided_at`, failing which the submission is rejected with `ERR_REBUTTAL_WINDOW_CLOSED`. The rebuttal records `submitted_by_employee_id` and opens in `SUBMITTED`. While any rebuttal stands `SUBMITTED` or `UNDER_REVIEW`, the plan's closure is deferred until the rebuttal resolves.

Review begins when an HRBP moves the rebuttal `SUBMITTED` → `UNDER_REVIEW`; that HRBP must be neither the plan's issuing HRBP nor the outcome decision's proposer (`ERR_SEGREGATION_OF_DUTIES`) and is recorded as `reviewed_by_hrbp_id`. Resolution belongs to that same reviewing HRBP — anyone else fails with `ERR_FORBIDDEN` — and requires a `resolution` of `UPHELD` or `OVERRULED` together with a `resolution_rationale` of at least 40 characters (`ERR_INVALID_REQUEST`).

Resolution can reverse the plan's outcome. Upholding an approved `SUCCESS` lets the plan proceed to `CLOSED_SUCCESS`. Overruling an approved `SUCCESS` reverses the plan to `CLOSED_FAILED`. Overruling an approved `TERMINATION` rescinds the termination: the plan closes `CLOSED_FAILED` and the employee's `employment_status` remains `ACTIVE`.

### 3.8. Consistency Review and Rating-Cycle Correlation

After plans close, HR audits whether similar cases ended similarly. An HRBP opens a consistency review by naming a `target_pip_id`; the review records the acting HRBP as `opened_by_hrbp_id` and opens in `OPEN`. At creation the server computes the comparison cohort into `cohort_pip_ids`: plans in the same org unit, built from a template of the same `category` as the target's, belonging to an employee of the same `job_family` whose `job_level` differs from the target employee's by at most one grade, in a closed state of `CLOSED_SUCCESS`, `CLOSED_FAILED`, or `CLOSED_TERMINATED`, and whose outcome was decided within the 365 days trailing the target's decision date — ordered by the cohort decisions' `decided_at` ascending, with ties broken by `created_at` ascending. The `cohort_size` field is the cohort's count, and creation requires at least three comparable closed plans (`ERR_COHORT_TOO_SMALL`); with an empty cohort the disparity score is undefined and creation fails the same way.

Two scores quantify the comparison, each rounded half-up to 4 decimal places. The `outcome_disparity_score` compares outcome distributions: take the share of the cohort whose approved outcome matches the target plan's approved outcome, and the share of the cohort whose approved outcome is `TERMINATION`; the score is the absolute difference between the cohort's termination share and an indicator that is 1 when the target's own outcome is `TERMINATION` and 0 otherwise, plus one-half of the complement of the matching-outcome share. The `rating_alignment_score` correlates the plan with the rating calendar: over the target plan's rating-cycle outcome links, it is the share of links whose cycle stood `PUBLISHED` at link time — as recorded on `rating_cycle_status_at_link` — out of all links, and 0.0 when the target has no links at all.

Adjudication is an `HRDirector` call with two symmetric branches: an `adjudication` of `CONSISTENT` closes the review as `ADJUDICATED_CONSISTENT`, while `INCONSISTENT` closes it as `ADJUDICATED_INCONSISTENT`. Either branch requires the review to still be `OPEN` (`ERR_INVALID_STATE`), a director other than the opening HRBP (`ERR_SEGREGATION_OF_DUTIES`), a cohort of at least three re-verified at adjudication time (`ERR_COHORT_TOO_SMALL`), and `adjudication_notes` of at least 40 characters (`ERR_INVALID_REQUEST`); both branches record the deciding director as `adjudicated_by_director_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (for example, an org unit, an employee, a plan, or a review request) return `201 Created`. Operations that modify an existing resource — state transitions, adjudications, clock advancement — return `200 OK`. Request payloads, response shapes, preconditions, and side effects are defined by the narratives in §2 and §3; this table is the routing and authorization index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hr-org-units` | Create an HR org unit | HRSystemAdmin |
| GET | `/hr-org-units/{ouId}` | Get an org unit | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| POST | `/hr-org-units/{ouId}/_clock/set_current_utc` | Set the org unit's logical clock (test-driving) | HRSystemAdmin |
| POST | `/hr-org-units/{ouId}/employees` | Create an employee | HRSystemAdmin |
| GET | `/hr-org-units/{ouId}/employees/{empId}` | Get an employee | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/{ouId}/employees` | List employees | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| POST | `/hr-org-units/{ouId}/employees/{empId}/coaching-log-entries` | Append a coaching log entry (author must be the employee's direct manager) | Manager |
| GET | `/hr-org-units/{ouId}/employees/{empId}/coaching-log-entries` | List coaching entries for an employee | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| POST | `/hr-org-units/{ouId}/employees/{empId}/performance-concerns` | Raise a performance concern | Manager |
| GET | `/hr-org-units/{ouId}/employees/{empId}/performance-concerns` | List concerns for an employee | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| GET | `/hr-org-units/{ouId}/employees/{empId}/performance-concerns/{concernId}` | Get a concern | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| POST | `/hr-org-units/{ouId}/employees/{empId}/performance-concerns/{concernId}/submit` | Submit a DRAFT concern for HR review | Manager |
| POST | `/hr-org-units/{ouId}/employees/{empId}/performance-concerns/{concernId}/accept` | HRBP accepts a SUBMITTED concern | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/employees/{empId}/performance-concerns/{concernId}/reject` | HRBP rejects a SUBMITTED concern as insufficient | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/pip-templates` | Create a PIP template | HRBusinessPartner |
| GET | `/hr-org-units/{ouId}/pip-templates` | List templates | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/{ouId}/pip-templates/{templateId}` | Get a template | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| POST | `/hr-org-units/{ouId}/pip-templates/{templateId}/publish` | Publish a template (bumps org-unit policy version) | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/pip-templates/{templateId}/retire` | Retire a PUBLISHED template | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips` | Create a PIP (in DRAFT) bound to an ACCEPTED concern and a PUBLISHED template | HRBusinessPartner |
| GET | `/hr-org-units/{ouId}/employees/{empId}/pips` | List PIPs for an employee | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}` | Get a PIP | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/goals` | List goals for a PIP | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/issue` | Issue a DRAFT PIP (OCC-guarded) | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/withdraw` | Withdraw an ISSUED/ACTIVE PIP | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/check-ins` | Schedule a check-in | HRBusinessPartner |
| GET | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/check-ins` | List check-ins for a PIP | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/check-ins/{checkInId}/mark-held` | Mark a check-in held (triggers goal update + attainment recompute) | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/check-ins/{checkInId}/evidence` | Submit evidence against a goal for a check-in | Manager, HRBusinessPartner |
| GET | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/check-ins/{checkInId}/evidence` | List evidence for a check-in | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/check-ins/{checkInId}/evidence/{evidenceId}/admit` | HRBP adjudicates evidence ADMISSIBLE | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/check-ins/{checkInId}/evidence/{evidenceId}/exclude` | HRBP adjudicates evidence INADMISSIBLE | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/legal-reviews` | Request a legal review for a PIP | HRBusinessPartner |
| GET | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/legal-reviews` | List legal reviews for a PIP | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/legal-reviews/{reviewId}/claim` | Assigned counsel claims the review | LegalCounsel |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/legal-reviews/{reviewId}/submit` | Counsel submits risk assessment | LegalCounsel |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/legal-reviews/{reviewId}/override` | HR Director overrides a REJECT recommendation | HRDirector |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/outcome-decisions` | Propose an outcome for a PIP | HRBusinessPartner |
| GET | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/outcome-decisions` | List outcome decisions for a PIP | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/outcome-decisions/{decisionId}/approve` | HR Director approves an outcome (OCC-guarded) | HRDirector |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/outcome-decisions/{decisionId}/reject` | HR Director rejects an outcome | HRDirector |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/rebuttals` | Employee submits a rebuttal within the 5-day window | Employee |
| GET | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/rebuttals` | List rebuttals | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/rebuttals/{rebuttalId}/start-review` | HRBP starts review (must not be issuing HRBP or outcome proposer) | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/rebuttals/{rebuttalId}/resolve` | HRBP resolves the rebuttal | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/rating-cycles` | Create a rating cycle | HRBusinessPartner |
| GET | `/hr-org-units/{ouId}/rating-cycles` | List rating cycles | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| POST | `/hr-org-units/{ouId}/rating-cycles/{cycleId}/calibrate` | Move cycle to CALIBRATION | HRBusinessPartner |
| POST | `/hr-org-units/{ouId}/rating-cycles/{cycleId}/publish` | Publish cycle ratings | HRDirector |
| POST | `/hr-org-units/{ouId}/rating-cycles/{cycleId}/archive` | Archive a PUBLISHED cycle | HRDirector |
| GET | `/hr-org-units/{ouId}/employees/{empId}/pips/{pipId}/rating-cycle-outcome-links` | List PIP<->rating-cycle links (system-generated) | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| POST | `/hr-org-units/{ouId}/consistency-reviews` | Open a consistency review against a closed PIP | HRBusinessPartner |
| GET | `/hr-org-units/{ouId}/consistency-reviews` | List consistency reviews | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel |
| GET | `/hr-org-units/{ouId}/consistency-reviews/{reviewId}` | Get a consistency review | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel |
| POST | `/hr-org-units/{ouId}/consistency-reviews/{reviewId}/adjudicate` | HR Director adjudicates | HRDirector |
| GET | `/hr-org-units/employees/{empId}` | Flat read of an employee by id (alternative to nested path) | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/employees` | Flat list of employees with FK filters (reverse-reachability utility) | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/rating-cycles/{cycleId}` | Flat read of a rating cycle by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/rating-cycles` | Flat list of rating cycles with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/coaching-log-entries/{entryId}` | Flat read of a coaching log entry by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| GET | `/hr-org-units/coaching-log-entries` | Flat list of coaching log entries with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| GET | `/hr-org-units/performance-concerns/{concernId}` | Flat read of a concern by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| GET | `/hr-org-units/performance-concerns` | Flat list of concerns with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| GET | `/hr-org-units/pip-templates/{templateId}` | Flat read of a PIP template by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/pip-templates` | Flat list of PIP templates with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/pips/{pipId}` | Flat read of a PIP by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/pips` | Flat list of PIPs with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/pip-goals/{goalId}` | Flat read of a PIP goal by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/pip-goals` | Flat list of PIP goals with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/check-ins/{checkInId}` | Flat read of a check-in by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/check-ins` | Flat list of check-ins with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/evidence-items/{evidenceId}` | Flat read of an evidence item by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| GET | `/hr-org-units/evidence-items` | Flat list of evidence items with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager |
| GET | `/hr-org-units/legal-reviews/{reviewId}` | Flat read of a legal review by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel |
| GET | `/hr-org-units/legal-reviews` | Flat list of legal reviews with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel |
| GET | `/hr-org-units/outcome-decisions/{decisionId}` | Flat read of an outcome decision by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/outcome-decisions` | Flat list of outcome decisions with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/rebuttals/{rebuttalId}` | Flat read of a rebuttal by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/rebuttals` | Flat list of rebuttals with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/consistency-review-items/{reviewId}` | Flat read of a consistency review by id (alternate path) | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel |
| GET | `/hr-org-units/consistency-review-items` | Flat list of consistency reviews with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel |
| GET | `/hr-org-units/rating-cycle-outcome-links/{linkId}` | Flat read of a rating-cycle outcome link by id | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |
| GET | `/hr-org-units/rating-cycle-outcome-links` | Flat list of rating-cycle outcome links with FK filters | HRSystemAdmin, HRBusinessPartner, HRDirector, LegalCounsel, Manager, Employee |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the §2 and §3 narratives; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PARENT_MISMATCH` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_COACHING_ENTRY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COACHING_ENTRY_NOT_FORMAL` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_COACHING_HISTORY` | 422 Unprocessable Entity |
| `ERR_CONCERN_NOT_ACCEPTED` | 409 Conflict |
| `ERR_TEMPLATE_WEIGHT_SUM` | 422 Unprocessable Entity |
| `ERR_TEMPLATE_CADENCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TEMPLATE_IN_USE` | 409 Conflict |
| `ERR_TEMPLATE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_ACTIVE_PIP_EXISTS` | 409 Conflict |
| `ERR_PIP_NOT_ACTIVE` | 409 Conflict |
| `ERR_OUTCOME_ALREADY_PROPOSED` | 409 Conflict |
| `ERR_CHECKIN_TOO_EARLY` | 409 Conflict |
| `ERR_CHECKIN_QUORUM` | 422 Unprocessable Entity |
| `ERR_CHECKIN_ALREADY_HELD` | 409 Conflict |
| `ERR_CHECKIN_CADENCE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_PLAN_STILL_RUNNING` | 409 Conflict |
| `ERR_ATTAINMENT_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_EXTENSION_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_LEGAL_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_LEGAL_OVERRIDE_NOT_ALLOWED` | 409 Conflict |
| `ERR_REBUTTAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_REBUTTAL_NOT_SUBJECT` | 403 Forbidden |
| `ERR_COHORT_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_CYCLE_STILL_OPEN` | 409 Conflict |
| `ERR_CYCLE_TOO_RECENT` | 409 Conflict |
