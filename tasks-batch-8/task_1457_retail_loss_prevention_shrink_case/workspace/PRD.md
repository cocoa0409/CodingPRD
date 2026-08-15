# Retail Loss Prevention & Shrink Case Management API — Product Requirements Document

## 1. Introduction

A multi-store retailer's Loss Prevention department lives between two clocks that never stop: the point-of-sale feed that surfaces suspicious transaction exceptions register by register, and the accounting calendar that closes inventory periods and books shrink. Between those clocks sits a casework pipeline — alerts triaged into investigations, interviews conducted under labor-rules scrutiny, civil demands issued and collected, evidence preserved under chain-of-custody, and repeat offenders linked across stores into organized-retail-crime groups. Today this work is scattered across spreadsheets, DVR exports, and email, which makes it nearly impossible to prove who knew what when, to keep an interviewer from adjudicating their own interview, or to reconcile a physical count against losses already attributed to cases.

This document specifies an API that runs that pipeline end to end. The system ingests POS exception events and aggregates them into scored alerts; converts alerts (or manual referrals, or inventory-variance breaches) into cases; walks each case through assignment, evidence-gated advancement, interviews, and adjudication under strict segregation of duties; issues and collects civil demands through a tiered statutory penalty schedule and a waterfall allocation of payments; retains or purges evidence under per-class retention horizons and legal holds; links cases into ORC groups whose escalation automatically raises case priority; and reconciles physical inventory counts into shrink accruals reported on a case-posted basis with a sales-ratio estimate exposed alongside. All rollups are immediate and reversible: a reopened case unwinds its loss posting from the shrink period, the store totals, and the employee's history in one consistent step.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, wire contracts, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly six roles, spelled exactly as follows: `LPAnalyst` (store-level loss-prevention analyst who triages alerts, builds cases, conducts interviews, drafts demands and referral packets, and records payments), `LPManager` (regional LP manager who assigns and adjudicates external-subject cases, issues demands, confirms ORC links, manages groups, and submits referrals), `HRPartner` (human-resources partner who owns the employee registry and adjudicates employee-subject cases), `LPAdmin` (LP system administrator who manages the store registry, shrink periods and counts, reconciliation, retention sweeps, and the logical clock), `Auditor` (read-only oversight), and `PosFeed` (the machine account that ingests POS exception events). A request with either header missing or malformed, or whose role value is not one of these six, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted for the target endpoint — including the subject-type routing on adjudication, where an `EMPLOYEE`-subject case may be adjudicated only by `HRPartner` and an `EXTERNAL`-subject case only by `LPManager` — is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

For every one of the six roles — `LPAnalyst`, `LPManager`, `HRPartner`, `LPAdmin`, `Auditor`, and `PosFeed` — `X-User-ID` is an opaque operator identifier not tied to the `id` of any persisted entity. The server records it where a workflow stamps an actor (for example as `created_by` on a case or civil demand, `assigned_analyst_id` on a case, `interviewer_id` on an interview, `adjudicated_by` on an adjudicated case, `sealed_by` on an evidence item, or `actor_id` on a custody event), and ownership checks compare `X-User-ID` against those recorded fields; it is never compared to any entity's `id`.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10 when omitted, and any value below 1 or above 100 is rejected with `ERR_INVALID_REQUEST`. `offset` sets the number of items skipped; it defaults to 0 and must be at least 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — stores, employees, exception events, alerts, cases, interviews, evidence items, civil demands, restitution payments, ORC groups, case links, shrink periods, and referral packets — carries a standard system-managed quartet:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): a system-managed integer that increments by one with every mutation to the resource. Recomputation of derived fields — for instance a store's rollup totals or a demand's outstanding balance — counts as a mutation and therefore refreshes `updated_at` and increments `version` on the owning resource.

Custody events are the single exception: because a custody entry is immutable once appended to the chain, it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock and Server-Stamped Timestamps

All timestamps this document describes as stamped "from the logical clock" read from a server-maintained logical clock, never from wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z, and until it is explicitly set it continues to read that default; there is no silent fallback to real time. An `LPAdmin` drives the clock through a test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`; the capability mutates no entity.

The logical clock stamps `conducted_at` when an interview outcome is recorded, `documented_at` when documentation is filed, `adjudicated_at` and `closed_at` at adjudication or early closure, `issued_at` at demand issuance, `submitted_at` at packet submission, and `counted_at` at each accepted physical count. Every duration comparison in the system — the 72-hour documentation staleness check, the 30-day reopen window, the 60-day demand-issue window, and the evidence retention horizons — is evaluated against this clock.

### 2.6. Money, Precision, and Rounding

All monetary values are integer cents; there are no fractional-cent amounts anywhere in the system. Where a computation requires rounding, the method is always round half up: an alert's `score` is carried to 2 decimal places; a shrink period's `variance_pct` is carried to 4 decimal places; the percentage portions inside the statutory penalty tiers, the statutory penalty after its prior-offense multiplier, and the sales-basis accrual are each rounded half up to whole cents. Duration and timestamp comparisons (retention expiry, the documentation SLA) are evaluated at second precision.

### 2.7. Validation Order and Nested Resource Resolution

Every request passes through a single ordered validation pipeline, and the first failing check produces the response — later checks are not evaluated. The order is fixed:

1. Header presence and validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role permission for the endpoint, including subject-type routing on adjudication (`ERR_FORBIDDEN_FOR_ROLE`).
3. Ownership: the actor must equal the case's `assigned_analyst_id` on assignee-scoped operations — case advancement, evidence attachment, interview scheduling, demand drafting, packet drafting, packet sealing, and packet revision — failing with `ERR_NOT_CASE_ASSIGNEE`; and the actor must equal the interview's `interviewer_id` on outcome recording and documentation, failing with `ERR_INTERVIEWER_MISMATCH`.
4. Request well-formedness: required fields present, types correct, enum values within their declared domains, amounts positive where required, `scheduled_end` strictly after `scheduled_start`, `period_end` on or after `period_start`, `limit` inside its permitted range, `offset` at least 0 (`ERR_INVALID_REQUEST`).
5. Existence of every referenced resource (`ERR_NOT_FOUND`).
6. The target entity's own state machine must permit the requested transition (`ERR_INVALID_STATE_TRANSITION`, or `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is not payable).
7. Cross-entity state guards: the store must be `ACTIVE` (`ERR_STORE_CLOSED`), the employee must not be `TERMINATED` (`ERR_EMPLOYEE_NOT_ACTIVE`), shrink-period locking (`ERR_PERIOD_LOCKED`), group linkability (`ERR_GROUP_NOT_LINKABLE`), packet acknowledgement for referral-dependent actions (`ERR_CASE_NOT_REFERRABLE`), and the case-state gates on interview scheduling, evidence attachment, demand drafting, and packet drafting (`ERR_INVALID_STATE_TRANSITION`).
8. Optimistic-concurrency version equality (`ERR_STALE_CASE_VERSION`, `ERR_STALE_PERIOD_VERSION`).
9. Segregation-of-duties and evidence-compliance rules (`ERR_SOD_INTERVIEWER_ADJUDICATOR`, `ERR_SOD_CASE_CREATOR`, `ERR_SOD_DEMAND_ISSUER`, `ERR_EVIDENCE_SEALED_IMMUTABLE`, `ERR_LEGAL_HOLD_ACTIVE`, `ERR_CUSTODY_GAP`).
10. Temporal rules (`ERR_INTERVIEW_OVERLAP`, `ERR_PERIOD_OVERLAP`, `ERR_INTERVIEW_DOC_STALE`, `ERR_DEMAND_WINDOW_CLOSED`, `ERR_REOPEN_WINDOW_CLOSED`).
11. Referential and aggregate gates (`ERR_DUPLICATE_STORE_NUMBER`, `ERR_DUPLICATE_EMPLOYEE_REF`, `ERR_DUPLICATE_GROUP_NAME`, `ERR_LINK_EXISTS`, `ERR_SUBJECT_MISMATCH`, `ERR_SUBJECT_UNRESOLVED`, `ERR_NO_ACTIVE_EVIDENCE`, `ERR_DEMAND_REQUIRED`, `ERR_PACKET_NOT_READY`, `ERR_COUNT_REQUIRED`, `ERR_CASE_HAS_PAYMENTS`, `ERR_GROUP_HAS_PROPOSED_LINKS`, `ERR_MERGE_NOT_ALLOWED`, `ERR_NO_OPEN_PERIOD`, `ERR_EVIDENCE_UNSEALED`).
12. Fiscal rules, always last (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`, `ERR_WRITE_OFF_CAP_EXCEEDED`, `ERR_RECOVERED_EXCEEDS_LOSS`, `ERR_BASIS_NOT_ALLOWED`).

Existence validation (step 5) proceeds left to right: path identifiers are validated first, in the order they appear in the URL, and then body-referenced foreign keys in their declared input order. A request naming a non-existent case in the path therefore fails with `ERR_NOT_FOUND` before any body reference is examined.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry an optimistic-concurrency field, and on both it is non-optional.

Drafting a civil demand requires the request to carry `expected_case_version` equal to the target case's current `version`. If the case's version has advanced since the client last observed it — for instance because an earlier draft already superseded and cancelled a prior draft — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). Because a fresh draft legitimately supersedes a prior `DRAFT` (the prior draft is automatically cancelled), a second request carrying the now-current version succeeds; only a stale `expected_case_version` fails.

Recording a physical count requires the request to carry `expected_shrink_period_version` equal to the shrink period's current `version`. A mismatch is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412). A recount on a `COUNTED` period legitimately supersedes the prior count, so a request carrying the current version succeeds; only a stale `expected_shrink_period_version` fails.

No other endpoint accepts a version field.

### 2.9. Segregation of Duties

Three separation walls keep any one operator from controlling an outcome end to end. The operator adjudicating a case must not be the `interviewer_id` of any `DOCUMENTED` interview on that case (`ERR_SOD_INTERVIEWER_ADJUDICATOR`), and must not be the analyst recorded as the case's `created_by` (`ERR_SOD_CASE_CREATOR`). Independently, the manager issuing a civil demand must not be the analyst recorded as that demand's `created_by` (`ERR_SOD_DEMAND_ISSUER`). Case assignment is deliberately exempt: the assignee need not differ from the case's creator, because the segregation checks bite at adjudication, not at assignment.

### 2.10. The Loss Ledger: Linked Rollups Across Case, Period, and Store

Consistency is immediate: every operation applies its full cascade before responding. A substantiated adjudication posts the case's loss into exactly one shrink period (raising that period's `known_loss_posted_cents`, which in turn moves the case-basis accrual) and raises the store's `total_adjudicated_loss_cents` by the same amount; a reopen reverses all of those steps and resets the case's posted loss to zero. Posting or returning a restitution payment moves the demand's balances, the case's `restitution_status`, and the store's `restitution_collected_cents` in the same transaction. Dismissing an alert releases its member events back to `UNAGGREGATED` so they can aggregate again; merging a case re-points its alerts, re-parents its evidence, and folds its manual and recovered values into the surviving case. Each of these mutations refreshes `updated_at` and increments `version` on every resource it touches.

## 3. Business Logic & Workflows

### 3.1. Store and Employee Registry

An `LPAdmin` opens the registry by creating a store with a public `store_number`, a display `name`, and a `region_code` used later for cross-store ORC analysis. The `store_number` is unique across the enterprise — a duplicate is rejected with `ERR_DUPLICATE_STORE_NUMBER` — and a new store starts `ACTIVE` with `total_adjudicated_loss_cents` and `restitution_collected_cents` both zero. Stores can be listed with `region_code` and `status` filters, and a single store is read by its `store_id`. When a banner closes, the same administrator closes the store; the close is refused with `ERR_PERIOD_LOCKED` while any shrink period of that store is still `OPEN` or `COUNTED`, and with `ERR_INVALID_STATE_TRANSITION` when the store is not `ACTIVE`. Once a store reaches `CLOSED`, it refuses all new child records: registering an employee, ingesting an exception event, creating a case, or opening a shrink period against a closed store fails with `ERR_STORE_CLOSED`.

An `HRPartner` registers each associate with the employee's home `store_id`, an enterprise-unique `employee_ref` (duplicates fail with `ERR_DUPLICATE_EMPLOYEE_REF`), and a `full_name`. A new employee starts `ACTIVE` with `prior_substantiated_count` zero. Suspension moves an `ACTIVE` employee to `SUSPENDED`, and reinstatement moves a `SUSPENDED` employee back to `ACTIVE`; either action against an employee in the wrong state fails with `ERR_INVALID_STATE_TRANSITION`. There is no operator-driven termination endpoint: an employee reaches `TERMINATED` only as a system side effect of a substantiated adjudication that directs `employment_action` TERMINATE, and this applies whether the employee was `ACTIVE` or `SUSPENDED` at the time. Once `TERMINATED`, the employee can no longer be the subject of a new employee-subject case nor be scheduled into a new interview — such attempts fail with `ERR_EMPLOYEE_NOT_ACTIVE`. A `SUSPENDED` employee is not blocked this way. Employees can be listed with `store_id` and `status` filters, or read individually by `employee_id`.

### 3.2. Exception Intake and Alert Aggregation

The `PosFeed` machine account ingests one exception event at a time, supplying `store_id`, `register_ref`, `txn_ref`, an `exception_type` drawn from `REFUND_NO_RECEIPT`, `HIGH_VALUE_VOID`, `PRICE_OVERRIDE`, `NO_SALE_DRAWER`, `SUSPEND_CANCEL`, `SWEETHEART_SCAN`, and `SELF_CHECKOUT_MISMATCH`, the exception value `amount_cents` (which must be greater than zero), the feed-provided `occurred_at` timestamp, and optionally `employee_id` — left null for self-checkout or otherwise unattributed events. Every event is born `UNAGGREGATED`, and the moment it lands, the weighted scoring algorithm runs.

Scoring works like this. Each event contributes its type weight — ten points for `REFUND_NO_RECEIPT`, fourteen for `HIGH_VALUE_VOID`, eight for `PRICE_OVERRIDE`, six for `NO_SALE_DRAWER`, eight for `SUSPEND_CANCEL`, twelve for `SWEETHEART_SCAN`, and nine for `SELF_CHECKOUT_MISMATCH` — multiplied by an amount band: 1.0 when `amount_cents` is below 5000, 1.5 when it is at least 5000 but below 20000, and 2.0 when it is at least 20000. The score is the sum of those weighted contributions, rounded half up to two decimal places.

What happens next depends on the grouping key, which is the pair of `store_id` and `employee_id`. When the group already has an alert in `OPEN` or `ESCALATED` status — at most one such alert exists per group by construction — the new event attaches to that alert instead of forming a new one, the alert's score is recomputed over all member events including the newcomer, and the escalation check below runs again. When no open alert exists for the group, the system builds a candidate set: every `UNAGGREGATED` event of the same group whose `occurred_at` falls within the window from thirty days before the new event's `occurred_at` up to and including that instant. A new alert is created if and only if the candidate set's score is at least 40.00; creation aggregates the candidate events into the alert, flipping each member to `AGGREGATED`.

An alert carries its `store_id` and (possibly null) `employee_id` from the group, a derived `subject_type` that reads `EMPLOYEE` when `employee_id` is set and `UNKNOWN` otherwise, the computed `score`, the `event_count` of member events, their summed `total_amount_cents`, and `window_start` / `window_end` spanning the earliest and latest member `occurred_at`. Whenever a score — computed at creation or recomputed on attach — reaches 75.00 or more, the alert escalates: the boundary is inclusive, so exactly 75.00 escalates, while anything below stays `OPEN`. Escalation has two consequences: dismissing that alert now requires an `LPManager` rather than an analyst, and any case later converted from it is born with `priority` HIGH.

Dismissal is the ordinary way to clear noise. An `OPEN` alert may be dismissed by an `LPAnalyst` or an `LPManager`; an `ESCALATED` alert can be dismissed only by an `LPManager`. Either way the caller supplies a `reason`, which is recorded as the alert's `dismiss_reason`, the alert becomes `DISMISSED`, and every member event reverts from `AGGREGATED` to `UNAGGREGATED`, released for re-aggregation into some future candidate set. Dismissing an alert in any other state fails with `ERR_INVALID_STATE_TRANSITION`. `CONVERTED` and `DISMISSED` are terminal.

Conversion is how an alert becomes a case, and only an `LPAnalyst` performs it. The alert must be `OPEN` or `ESCALATED` (`ERR_INVALID_STATE_TRANSITION` otherwise), its store must still be `ACTIVE` (`ERR_STORE_CLOSED`), and the payload declares a `subject_type`. Declaring `EMPLOYEE` requires that the alert's `employee_id` is non-null, that the payload `employee_id` equals it exactly, and that the employee is not `TERMINATED` — mismatches fail with `ERR_SUBJECT_MISMATCH`, a terminated employee with `ERR_EMPLOYEE_NOT_ACTIVE`. The payload may also bundle `additional_alert_ids`: each must be an `OPEN` or `ESCALATED` alert of the same store, and each converts alongside, pointing at the new case. Conversion creates the case with `source` ALERT, inherits the alert's `store_id`, stamps `case_id` back onto every converted alert, and keeps the member events `AGGREGATED` — they now feed the case's loss computation. A case converted from an `ESCALATED` alert starts with `priority` HIGH. Alerts support list filtering by `store_id`, `employee_id`, `case_id`, `status`, `subject_type`, and `min_score`, and a detail read by `alert_id`; events likewise list by `store_id`, `employee_id`, `status`, and `exception_type`, with a detail read by `event_id`.

### 3.3. Case Intake, Assignment, and Evidence-Gated Advancement

Cases arrive through three doors. Conversion from alerts was covered above. An `LPAnalyst` may also open a manual case directly, supplying `store_id`, a `subject_type` of `EMPLOYEE`, `EXTERNAL`, or `UNKNOWN`, an `employee_id` that is required when — and only when — the subject type is `EMPLOYEE` and must be null for the other two (`ERR_SUBJECT_MISMATCH`), plus an optional `manual_loss_cents` analyst estimate; naming a `TERMINATED` employee fails with `ERR_EMPLOYEE_NOT_ACTIVE`. The third door is the shrink-variance auto-case described in §3.9. Every case is stamped with `created_by` from the caller's `X-User-ID`, receives a server-minted display `case_number` of the form "LP-" followed by the store's `store_number` and a zero-padded per-store sequence, and starts in `OPEN`. Its `source` records which door it came through — `ALERT`, `MANUAL`, or `SHRINK_VARIANCE`.

The case's headline figure, `total_loss_cents`, is always derived the same way: take the sum of `amount_cents` over every exception event aggregated into alerts whose `case_id` points at this case, add `manual_loss_cents` (zero for alert-sourced cases, the variance magnitude for shrink auto-cases), subtract `recovered_value_cents`, and floor the result at zero. A computed summary read accompanies the detail read and reports the case's `case_id`, current `total_loss_cents`, `evidence_count`, `sealed_evidence_count`, `documented_interview_count`, `demand_outstanding_cents`, `confirmed_link_count`, and `restitution_status`. Cases can be listed with filters on `store_id`, `employee_id`, `status`, `subject_type`, `source`, `merged_into_case_id`, `loss_posted_period_id`, and `priority`.

Work begins when an `LPManager` assigns the case: the request names an `analyst_id`, the case records it as `assigned_analyst_id`, and the case moves from `OPEN` to `INVESTIGATING` — attempting this on a case in any other state yields `ERR_INVALID_STATE_TRANSITION`. The assignee is not required to differ from the case's creator; segregation of duties is enforced at adjudication, not at assignment.

From `INVESTIGATING`, the assigned analyst advances the case to `READY_FOR_INTERVIEW`. Advancement is assignee-scoped — any other actor fails with `ERR_NOT_CASE_ASSIGNEE` — and gated on evidence: at least one evidence item of the case must be in `ACTIVE` or `SEALED` status, else `ERR_NO_ACTIVE_EVIDENCE`. The advance request may record a `recovered_value_cents` figure for recovered merchandise, which must not exceed the member-alert event sum plus `manual_loss_cents` (`ERR_RECOVERED_EXCEEDS_LOSS`); the value is stored and `total_loss_cents` recomputed. There is deliberately no advancement out of `READY_FOR_INTERVIEW` through this capability — only the interview pipeline, described next, moves the case past that point.

While a case is `INVESTIGATING` or `READY_FOR_INTERVIEW`, an `LPManager` may resolve or correct its subject, updating `subject_type` and `employee_id` without any status change. The same subject-consistency and employment rules as at creation apply — an `EMPLOYEE` subject requires a non-terminated employee reference, the other subject types require it null (`ERR_SUBJECT_MISMATCH`, `ERR_EMPLOYEE_NOT_ACTIVE`). This is how an `UNKNOWN`-subject shrink auto-case becomes adjudicable.

Evidence attaches throughout the active life of a case: the assigned analyst supplies `case_id`, an `evidence_type` of `VIDEO_CLIP`, `TRANSACTION_LOG`, `PHOTO`, `WRITTEN_STATEMENT`, or `AUDIO`, the `captured_at` instant, and a `retention_class` of `STANDARD`, `EXTENDED`, or `CASE_HOLD`. Attachment is permitted only while the case is `INVESTIGATING`, `READY_FOR_INTERVIEW`, `INTERVIEWED`, or `ADJUDICATING` (otherwise `ERR_INVALID_STATE_TRANSITION`), and only by the assignee (`ERR_NOT_CASE_ASSIGNEE`). A new item starts `ACTIVE`, with its `retention_until` computed per §3.7 and `legal_hold` false.

### 3.4. Interviews and the Documentation SLA

Interviews are scheduled by the case's assigned analyst, who names the `case_id`, the `interviewer_id` of the analyst who will conduct it, a `scheduled_start`, a `scheduled_end` that must be strictly later than the start (`ERR_INVALID_REQUEST`), and — on employee-subject cases — the `subject_employee_id` of the employee being interviewed, subject to the same consistency rules as case creation. The case must be `INVESTIGATING` or `READY_FOR_INTERVIEW` (`ERR_INVALID_STATE_TRANSITION` otherwise). One employee cannot be double-booked: the new half-open window — including its start, excluding its end — must not overlap the window of any other `SCHEDULED` or `HELD` interview for the same employee, though windows that merely touch at an endpoint are allowed; violations fail with `ERR_INTERVIEW_OVERLAP`. A new interview starts `SCHEDULED`.

When the meeting happens, the interviewer alone — `ERR_INTERVIEWER_MISMATCH` for anyone else — records the outcome from `SCHEDULED`. An `outcome` of `ADMITTED`, `DENIED`, or `PARTIAL` moves the interview to `HELD` and stamps `conducted_at` from the logical clock. An `outcome` of `NO_SHOW` instead moves it straight to `NO_SHOW`, a terminal state, with no conduct timestamp stamped. An interview can also be cancelled while `SCHEDULED`, either explicitly by an analyst or automatically because its source case was merged; `CANCELLED` is likewise terminal.

Documentation completes the loop. The interviewer files `notes` against a `HELD` interview, which stamps `documented_at` from the logical clock, computes the `doc_stale` flag, and moves the interview to `DOCUMENTED`. The flag is true when the gap between `documented_at` and `conducted_at` is strictly greater than 72 hours — a gap of exactly 72 hours and 0 seconds is not stale. If the parent case is sitting in `READY_FOR_INTERVIEW`, documenting the interview advances the case to `INTERVIEWED`; this system-driven transition is the only road out of `READY_FOR_INTERVIEW`. Interviews list with `case_id`, `interviewer_id`, `subject_employee_id`, and `status` filters, and a single interview is read by `interview_id`.

### 3.5. Adjudication, Closure, Reopening, and Merging

With at least one documented interview in hand, the assigned analyst advances the case from `INTERVIEWED` to `ADJUDICATING`. Because `INTERVIEWED` is reachable only through a documented interview, the documentation gate is structural. One further gate applies here: the case's `subject_type` must by then be `EMPLOYEE` or `EXTERNAL` — advancing a still-`UNKNOWN` case fails with `ERR_SUBJECT_UNRESOLVED`.

Adjudication is role-routed and walled. An `EMPLOYEE`-subject case can be adjudicated only by an `HRPartner`; an `EXTERNAL`-subject case only by an `LPManager`; the wrong role draws `ERR_FORBIDDEN_FOR_ROLE`. Whoever adjudicates must not be the `interviewer_id` of any `DOCUMENTED` interview on the case (`ERR_SOD_INTERVIEWER_ADJUDICATOR`) and must not be the analyst who created it (`ERR_SOD_CASE_CREATOR`). The latest `DOCUMENTED` interview must also be fresh — `doc_stale` false — unless the caller explicitly passes `documentation_override` true (`ERR_INTERVIEW_DOC_STALE`).

A `decision` of SUBSTANTIATED carries one more precondition and a wide cascade. Unless the caller passes `restitution_waived` true, a civil demand for the case must already exist in `DRAFT`, `ISSUED`, `PARTIALLY_PAID`, or `PAID_IN_FULL` status (`ERR_DEMAND_REQUIRED`). On success the case stamps `adjudicated_at`, `adjudicated_by`, and `closed_at` from the logical clock; sets `loss_posted_cents` — which every case carries at zero until this moment — equal to the current `total_loss_cents`; and posts that amount into the store's shrink period whose closed `[period_start, period_end]` interval contains the current logical date and whose status is `OPEN` or `COUNTED`. If no such period exists, the adjudication fails with `ERR_NO_OPEN_PERIOD`. The chosen period's `known_loss_posted_cents` rises by the posted amount, its case-basis accrual recomputes, the case records the target in `loss_posted_period_id`, and the store's `total_adjudicated_loss_cents` rises by the same amount. For an `EMPLOYEE` subject the employee's `prior_substantiated_count` increases by one, and the payload's `employment_action` — TERMINATE or SUSPEND — moves the employee to `TERMINATED` or `SUSPENDED` respectively. Finally, `restitution_status` becomes `OUTSTANDING`, or `NONE` when restitution was waived. The case lands in `CLOSED_SUBSTANTIATED`.

A `decision` of UNSUBSTANTIATED applies the same role routing, the same two segregation walls, and the same documentation-staleness gate, then stamps `adjudicated_at`, `adjudicated_by`, and `closed_at`, cancels any `DRAFT` civil demand on the case, and lands the case in `CLOSED_UNSUBSTANTIATED`. Separately, an `LPManager` may close a still-early investigation for insufficient evidence: dismissing an `INVESTIGATING` case moves it directly to `CLOSED_UNSUBSTANTIATED`, stamps `closed_at`, and requires neither an interview nor a demand; the request carries a `reason`.

Closure is not always final. Within thirty days of `closed_at` — the check passes when the current instant is on or before `closed_at` plus 30 days, else `ERR_REOPEN_WINDOW_CLOSED` — an `LPManager` may reopen a `CLOSED_SUBSTANTIATED` or `CLOSED_UNSUBSTANTIATED` case back to `INVESTIGATING`. Reopen is refused when the case's `loss_posted_period_id` names a period no longer `OPEN` or `COUNTED` (`ERR_PERIOD_LOCKED`), and when any demand of the case holds a `POSTED` payment (`ERR_CASE_HAS_PAYMENTS`). Reopening a substantiated case unwinds the ledger: the period's `known_loss_posted_cents` falls by `loss_posted_cents`, the case-basis accrual recomputes, the store's `total_adjudicated_loss_cents` falls by the same amount, and the case's `loss_posted_cents` resets to zero. For an employee subject, `prior_substantiated_count` decreases by one. Any `DRAFT` demand is cancelled, while `ISSUED` and `PARTIALLY_PAID` demands survive; `closed_at` is cleared and `restitution_status` recomputed. Reopening an unsubstantiated case performs the same steps minus the loss reversal, since nothing was posted.

Once a substantiated case's referral packet has been acknowledged, an `LPManager` may move it from `CLOSED_SUBSTANTIATED` to `CLOSED_REFERRED`; without an `ACKNOWLEDGED` packet the attempt fails with `ERR_CASE_NOT_REFERRABLE`. `CLOSED_REFERRED` is terminal.

Duplicate investigations are consolidated by merge. An `LPManager` merges a source case that is `INVESTIGATING` or `READY_FOR_INTERVIEW` into a surviving target named by `target_case_id`; the merge is refused with `ERR_MERGE_NOT_ALLOWED` when the source is in any other state, when the target does not exist, equals the source, or is terminal or already `MERGED`. The merge stamps the source's `merged_into_case_id` to the target, re-points the source's alerts so their `case_id` names the target, re-parents the source's evidence items onto the target, cancels the source's `SCHEDULED` interviews (its `HELD` and `DOCUMENTED` interviews stay on the source for audit), and cancels its `DRAFT` demands. The target absorbs the source's `manual_loss_cents` and `recovered_value_cents` into its own and recomputes `total_loss_cents`. Because the advance-time gate guarantees each case's recovered value never exceeds its event sum plus manual loss, every case's raw figure is non-negative, so the merge conserves loss exactly: the target's total afterwards equals the sum of the two cases' totals beforehand. The source ends in `MERGED`, a terminal state, and from then on contributes to ORC exposure only through its surviving target.

### 3.6. Civil Demands and Restitution Recovery

A civil demand is drafted by the case's assigned analyst while the case is `INTERVIEWED` or `ADJUDICATING` (otherwise `ERR_INVALID_STATE_TRANSITION`, and non-assignees draw `ERR_NOT_CASE_ASSIGNEE`). The payload carries `case_id`, a `basis` of `STATUTORY` or `ACTUAL_LOSS`, the optimistic-concurrency field `expected_case_version` (per §2.8), and optionally `priors_offense_count` (default 0) and `recovery_cost_cents` (default 0). `ACTUAL_LOSS` is the only basis allowed on an `EMPLOYEE`-subject case — choosing `STATUTORY` there fails with `ERR_BASIS_NOT_ALLOWED` — while external-subject cases may elect either. Drafting supersedes: any existing `DRAFT` demand on the case is automatically `CANCELLED`, the new demand starts in `DRAFT` with `created_by` stamped, and the case's `version` increments by one, which is exactly what makes a second drafter's stale `expected_case_version` fail.

Issuance is a manager's act, and the issuer must differ from the analyst who drafted the demand (`ERR_SOD_DEMAND_ISSUER`). Only a `DRAFT` demand can be issued, and only while its case is `INTERVIEWED` or `ADJUDICATING`; moreover, once the case carries an `adjudicated_at`, issuance must happen no later than sixty days after that instant (`ERR_DEMAND_WINDOW_CLOSED`). At issuance the money fields are snapshotted and never change afterwards: `merchandise_loss_cents` takes the case's `total_loss_cents` at that instant, and `statutory_penalty_cents` is computed from the tier schedule — zero when the basis is `ACTUAL_LOSS`.

The statutory tier schedule runs on the snapshotted merchandise loss. A loss of at most 50000 cents draws a flat tier penalty of 10000 cents. A loss above 50000 and at most 150000 cents draws 25000 cents plus ten percent of the portion above 50000, that percentage rounded half up to whole cents. A loss above 150000 cents draws 50000 cents plus twenty percent of the portion above 150000 — likewise rounded half up — with the tier result capped at 100000 cents. The tier penalty is then multiplied by a prior-offense multiplier: one plus one-half times the number of priors counted, where at most four priors count and the multiplier itself is capped at 3.0. The priors counted are the employee's `prior_substantiated_count` at the issuance instant for employee subjects, or the demand's recorded `priors_offense_count` for external subjects. `statutory_penalty_cents` is that product rounded half up to whole cents — the rounding happens after the multiplication, since each tier value is already integral. The demand's `amount_due_cents` is `merchandise_loss_cents` plus `statutory_penalty_cents` plus `recovery_cost_cents`; on the `ACTUAL_LOSS` basis the penalty term is zero, so the amount due is merchandise loss plus recovery cost only. Issuance stamps `issued_at` and flips the case's `restitution_status` to `OUTSTANDING`.

Payments arrive in two steps. An analyst first records a payment with `demand_id`, an `amount_cents` greater than zero, and a `method` of `CASH`, `CARD`, `MONEY_ORDER`, or `PAYROLL_DEDUCT`; the payment starts `RECEIVED`. Posting is the committing step: the payment must be `RECEIVED`, its demand must be `ISSUED` or `PARTIALLY_PAID` (`ERR_DEMAND_NOT_PAYABLE` otherwise), and `amount_cents` must not exceed the demand's `outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING` — overpayment is impossible by construction). Posting allocates the amount across three buckets in a fixed waterfall order: first toward unpaid NSF fees, then toward the unpaid statutory penalty, then toward the unpaid merchandise-loss-plus-recovery-cost bucket, each bucket receiving the lesser of the remaining payment and that bucket's unpaid balance. The allocations land in the payment's `applied_fees_cents`, `applied_penalty_cents`, and `applied_merch_cents`. The demand's `paid_to_date_cents` rises by the posted amount and `outstanding_cents` recomputes; after every post and every return the invariant holds that `outstanding_cents` equals `amount_due_cents` plus `fees_incurred_cents` minus `paid_to_date_cents`. The demand's status follows the balance: a posting that leaves paid-to-date strictly between zero and the full due-plus-fees total flips `ISSUED` to `PARTIALLY_PAID`, and a posting that drives `outstanding_cents` to exactly zero flips the demand to `PAID_IN_FULL` — including a first payment that covers the full amount in one shot, moving straight from `ISSUED`. When a demand reaches `PAID_IN_FULL`, the case's `restitution_status` becomes `SETTLED` provided no other issued demand on the case still has `outstanding_cents` above zero. The store's `restitution_collected_cents` rises by the posted amount.

A payment later dishonored — the NSF path — is returned: only a `POSTED` payment can be returned, and returning it adds a 2500-cent fee to the demand's `fees_incurred_cents`, subtracts the payment's amount from `paid_to_date_cents`, subtracts that payment's bucket allocations back out of each paid counter, and recomputes `outstanding_cents`. The demand's status unwinds in kind: `PAID_IN_FULL` falls back to `PARTIALLY_PAID`, and a `PARTIALLY_PAID` demand whose paid-to-date returns to zero falls back to `ISSUED`. The case's `restitution_status` recomputes to `OUTSTANDING`, and the store's `restitution_collected_cents` falls by the returned amount.

Managers close out demand lifecycle manually in two ways. A write-off moves an `ISSUED` or `PARTIALLY_PAID` demand to `WRITTEN_OFF`, but only when `outstanding_cents` is at most 50000 cents (`ERR_WRITE_OFF_CAP_EXCEEDED`); the case's `restitution_status` then recomputes, becoming `NONE` if that was the last collectible demand. A manual cancel moves a `DRAFT` demand to `CANCELLED`; the system also cancels drafts on supersession by a newer draft, on unsubstantiated adjudication, on merge, and on reopen. A case's `restitution_status` reads `NONE` when no issued demand exists or restitution was waived, and is otherwise derived from demand outstanding balances — `OUTSTANDING` while collectible balance remains, `SETTLED` once none does. Demands list with `case_id`, `status`, and `basis` filters and are read by `demand_id`; payments list with `demand_id`, `status`, and `method` filters and are read by `payment_id`.

### 3.7. Evidence Custody, Retention, and Referral Packets

Every movement of an evidence item is chronicled by appending a custody event naming the `evidence_id`, an `action` of `COLLECTED`, `SEALED`, `ACCESSED`, `TRANSFERRED`, `RELEASED_TO_LE`, or `RETURNED_FROM_LE`, and an optional free-text `note`; the server stamps `actor_id` from the caller's `X-User-ID`. Custody entries are immutable — per §2.4 they carry only `id` and `created_at` — and two actions are forbidden while the item is `SEALED`: recording `ACCESSED` or `TRANSFERRED` against sealed evidence fails with `ERR_EVIDENCE_SEALED_IMMUTABLE`. The chain can be read back as a list filtered by `evidence_id` and `action`, or entry by entry via `custody_event_id`.

Sealing preserves an item for litigation. An analyst seals an `ACTIVE` item — anything else draws `ERR_INVALID_STATE_TRANSITION` — but only after the chain shows a `COLLECTED` custody event for it; sealing an item with no collection record fails with `ERR_CUSTODY_GAP`. Sealing stamps `sealed_by` and automatically appends a `SEALED` custody event. A manager may unseal a `SEALED` item back to `ACTIVE`, except while `legal_hold` is true (`ERR_LEGAL_HOLD_ACTIVE`). Releasing evidence to law enforcement is also a manager's act: the item must be `SEALED`, and the case must carry an `ACKNOWLEDGED` referral packet (`ERR_CASE_NOT_REFERRABLE`); the item becomes `RELEASED` and a `RELEASED_TO_LE` custody event is appended automatically. `RELEASED` is terminal.

Retention follows the item's `retention_class`. A `STANDARD` item's `retention_until` is its `captured_at` plus 90 days; an `EXTENDED` item's is `captured_at` plus 365 days; a `CASE_HOLD` item's is the parent case's `closed_at` plus 30 days, and such an item is not eligible for expiry at all while its case is not closed — the horizon is recomputed when the case closes and again if it reopens. An administrator runs the retention sweep, which executes two phases inside a single call: first, every item already `EXPIRED` at the sweep's start is purged to `PURGED` — logically destroyed, custody log retained — and second, every eligible `ACTIVE` item expires to `EXPIRED`. An item expiring in a given sweep is never purged in that same sweep; it waits for a later one. Expiry eligibility requires all of the following at once: status `ACTIVE`; the current instant strictly greater than `retention_until` — at the exact `retention_until` second the item is retained; the parent case in `CLOSED_SUBSTANTIATED`, `CLOSED_UNSUBSTANTIATED`, or `CLOSED_REFERRED`; and `legal_hold` false. The sweep reports `purged_count` and `expired_count`.

The referral packet is the case's bridge to law enforcement. The assigned analyst drafts one with `case_id` and a `jurisdiction_code`, but only for a `CLOSED_SUBSTANTIATED` case (`ERR_INVALID_STATE_TRANSITION` otherwise); the packet starts in `DRAFT`. Sealing the packet — again the assignee — requires that every evidence item of the case still in `ACTIVE` status be sealed first (`ERR_EVIDENCE_UNSEALED`); items already `EXPIRED` or `PURGED` are simply excluded from the packet. Every `SEALED` item going in must also show a `COLLECTED` custody event (`ERR_CUSTODY_GAP`). Sealing snapshots `packet_exposure_cents` from the case's `total_loss_cents` and moves the packet to `SEALED`.

Submission belongs to the manager: the packet must be `SEALED`, the case must be `CLOSED_SUBSTANTIATED`, and no civil demand of the case may still be in `DRAFT` — the latter two failures surface as `ERR_PACKET_NOT_READY`. Submission stamps `submitted_at`, moves the packet to `SUBMITTED`, and sets `legal_hold` true on every `SEALED` or `ACTIVE` evidence item of the case, which blocks both unsealing and retention expiry until the hold clears. Law enforcement's response is recorded by a manager through acknowledgement: an `outcome` of `ACKNOWLEDGED` moves the packet to its terminal `ACKNOWLEDGED` state, keeps `legal_hold` in place, and makes sealed evidence releasable; an `outcome` of `RETURNED` moves it to `RETURNED`, records the supplied `return_reason`, and clears `legal_hold` on all of the case's evidence. A `RETURNED` packet is not a dead end — the assigned analyst may revise it back to `DRAFT`, correct it, and run the cycle again; the loop from `DRAFT` through `SEALED`, `SUBMITTED`, and `RETURNED` back to `DRAFT` is allowed without limit. Packets list with `case_id` and `status` filters and are read by `packet_id`; evidence items list with `case_id`, `status`, `evidence_type`, and `retention_class` filters and are read by `evidence_id`.

### 3.8. Organized Retail Crime Groups and Case Linkage

When incidents across stores share a modus operandi, a manager registers an ORC group with an enterprise-unique `name` (`ERR_DUPLICATE_GROUP_NAME` on collision) and an optional free-text `description`; the group starts `IDENTIFIED` with all counters at zero. Analysts then propose links: a case link names a `case_id`, an `orc_group_id`, and a `link_score` expressing analyst confidence from 0 to 100. The target group must be `IDENTIFIED` or `ACTIVE_MONITORING` — linking into a `DISRUPTED` or `DISMISSED` group fails with `ERR_GROUP_NOT_LINKABLE` — and at most one non-`REJECTED` link may exist for a given case-and-group pair (`ERR_LINK_EXISTS`). A fresh link starts `PROPOSED`.

Confirmation is a manager's call. The link must be `PROPOSED` and its case must be non-terminal and not `MERGED` (both failures surface as `ERR_INVALID_STATE_TRANSITION`); on success the link becomes `CONFIRMED` and the group's three counters recompute over its confirmed links: `confirmed_case_count` counts `CONFIRMED` links, `distinct_store_count` counts the distinct stores among the confirmed-linked cases, and `exposure_cents` sums those cases' `total_loss_cents` — remembering that a `MERGED` case contributes only through its surviving target. The escalation rule then evaluates all three conjuncts together, each boundary inclusive: at least 3 confirmed cases, spanning at least 2 distinct stores, with combined exposure of at least 500000 cents. When all three hold, the group escalates from `IDENTIFIED` to `ACTIVE_MONITORING`, and every confirmed-linked case's `priority` recomputes to HIGH. Escalation can also unwind: when a confirmed-linked case is merged into another case and the recomputed counters leave at least one conjunct false, the group de-escalates back to `IDENTIFIED`, and each still-confirmed-linked case recomputes its `priority` — HIGH only if some other `ACTIVE_MONITORING` group links it or one of its source alerts is `ESCALATED`, `STANDARD` otherwise. That is the standing priority rule for every case: HIGH when any source alert is `ESCALATED` or any confirmed link points at an `ACTIVE_MONITORING` group, and `STANDARD` otherwise.

Rejecting a link is the symmetric manager action: a `PROPOSED` link becomes `REJECTED`, and the group's counters are unaffected because the link was never counted. Two manager actions retire a group. Disrupting an `ACTIVE_MONITORING` group moves it to `DISRUPTED` and automatically rejects all of its `PROPOSED` links, while confirmed links are retained for audit. Dismissing a group — from `IDENTIFIED` or `ACTIVE_MONITORING` — requires that no `PROPOSED` links remain (`ERR_GROUP_HAS_PROPOSED_LINKS`) and that the confirmed-case count is zero (`ERR_GROUP_NOT_LINKABLE`), landing the group in `DISMISSED`. Both `DISRUPTED` and `DISMISSED` are terminal. Groups list with a `status` filter and are read by `group_id`; links list with `case_id`, `orc_group_id`, and `status` filters and are read by `link_id`.

### 3.9. Shrink Periods, Physical Counts, and Reconciliation

Each store's inventory calendar is a chain of shrink periods. An `LPAdmin` opens one with `store_id`, a `period_start` at the closed interval's start, a `period_end` at the closed interval's end that must be on or after the start (`ERR_INVALID_REQUEST`), the merchandising feed's `book_inventory_cents` (greater than zero), and `period_sales_cents` (zero or more). Periods of the same store must be strictly disjoint: because the intervals are closed on both ends, even touching at an endpoint conflicts, and an overlapping or abutting new period fails with `ERR_PERIOD_OVERLAP`. A new period starts `OPEN` with `known_loss_posted_cents` at zero; that figure then moves only when a case adjudication posts loss into the period or a reopen reverses one (§2.10).

Two accrual bases are exposed side by side on every period. The case-posted basis, `accrual_case_basis_cents`, simply equals `known_loss_posted_cents`; it is the officially reported accrual while the period is `OPEN` or `COUNTED`, and it moves only with case activity. The sales-ratio basis, `accrual_sales_basis_cents`, is the period's net sales multiplied by 0.0125 and rounded half up to whole cents; it is a comparative estimate, never the reported figure.

The physical count is recorded by an administrator carrying `counted_inventory_cents` and the optimistic-concurrency field `expected_shrink_period_version` (per §2.8). Recording against an `OPEN` period moves it to `COUNTED`; recording against a `COUNTED` period is a recount that supersedes the prior count in place. Either way `counted_at` is stamped from the logical clock and the period's `version` increments by one. A period already `RECONCILED` or `CLOSED` refuses the count with `ERR_PERIOD_LOCKED`.

Reconciliation is the point of no return. Reconciling an `OPEN` period — one with no count yet — fails with `ERR_COUNT_REQUIRED`; reconciling a `COUNTED` period snapshots two figures: `variance_cents`, the counted inventory minus the loss-adjusted book (that is, `book_inventory_cents` minus `known_loss_posted_cents`), and `variance_pct`, the variance divided by `book_inventory_cents` rounded half up to four decimal places. The snapshot uses the period's live `known_loss_posted_cents` at the instant of the reconcile call. When the absolute value of `variance_pct` is at least 0.0200 — the boundary is inclusive — the system auto-creates a shrink-investigation case with `source` SHRINK_VARIANCE, `subject_type` UNKNOWN, `manual_loss_cents` set to the negation of `variance_cents` when the variance is negative and to zero otherwise, and status `OPEN`, and records it on the period as `auto_case_id`. That auto-case then flows through the ordinary pipeline: assignment, evidence, interview, subject resolution, adjudication. The evaluation order is pinned to break the apparent circularity — first the variance snapshot reads the live posted-loss figure, then the period transitions to `RECONCILED` and stops accepting loss postings, and the auto-case's eventual adjudication posts its loss to whichever period contains the adjudication date in `OPEN` or `COUNTED` status, never retroactively to this reconciled period. Finally, an administrator closes a `RECONCILED` period to `CLOSED`; remember from §3.1 that a store cannot close while any of its periods is `OPEN` or `COUNTED`. Periods list with `store_id`, `status`, and `auto_case_id` filters and are read by `period_id`.

## 4. Endpoint Definitions

Operations that create a new resource — a store, an employee, an exception event, a case (manual or by conversion), an interview, an evidence item, a custody event, a civil demand, a restitution payment, an ORC group, a case link, a shrink period, or a referral packet — return `201 Created`. Operations that modify an existing resource in place — state transitions such as assign, advance, adjudicate, reopen, merge, seal, submit, post, return, record-count, reconcile, and the logical-clock setter — return `200 OK`, as do all read endpoints. Request payloads, gating conditions, and side effects for each operation are specified in §2 and §3; this table is only the index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | LPAdmin |
| POST | `/ops/retention-sweep` | Run the two-phase evidence retention sweep | LPAdmin |
| POST | `/stores` | Create a store | LPAdmin |
| GET | `/stores` | List stores | All six roles |
| GET | `/stores/{store_id}` | Get a store | All six roles |
| POST | `/stores/{store_id}/close` | Close a store (requires no OPEN/COUNTED shrink periods) | LPAdmin |
| POST | `/employees` | Register an employee | HRPartner |
| GET | `/employees` | List employees | All six roles |
| GET | `/employees/{employee_id}` | Get an employee | All six roles |
| POST | `/employees/{employee_id}/suspend` | Suspend an ACTIVE employee | HRPartner |
| POST | `/employees/{employee_id}/reinstate` | Reinstate a SUSPENDED employee | HRPartner |
| POST | `/exception-events` | Ingest a POS exception event and run alert aggregation | PosFeed |
| GET | `/exception-events` | List exception events | All six roles |
| GET | `/exception-events/{event_id}` | Get an exception event | All six roles |
| GET | `/alerts` | List alerts | All six roles |
| GET | `/alerts/{alert_id}` | Get an alert | All six roles |
| POST | `/alerts/{alert_id}/dismiss` | Dismiss an alert (LPAnalyst for OPEN; LPManager for OPEN or ESCALATED) | LPAnalyst, LPManager |
| POST | `/alerts/{alert_id}/convert` | Convert an alert (optionally bundling same-store alerts) into a new case | LPAnalyst |
| POST | `/cases` | Create a manual case | LPAnalyst |
| GET | `/cases` | List cases | All six roles |
| GET | `/cases/{case_id}` | Get a case | All six roles |
| GET | `/cases/{case_id}/summary` | Computed case read: totals and evidence/interview/demand/link rollups | All six roles |
| POST | `/cases/{case_id}/assign` | Assign an analyst; OPEN -> INVESTIGATING | LPManager |
| POST | `/cases/{case_id}/advance` | Step the case forward (INVESTIGATING -> READY_FOR_INTERVIEW, INTERVIEWED -> ADJUDICATING) | LPAnalyst |
| POST | `/cases/{case_id}/dismiss` | Early closure: INVESTIGATING -> CLOSED_UNSUBSTANTIATED | LPManager |
| POST | `/cases/{case_id}/adjudicate` | Adjudicate an ADJUDICATING case (HRPartner for EMPLOYEE subjects, LPManager for EXTERNAL) | LPManager, HRPartner |
| POST | `/cases/{case_id}/reopen` | Reopen a closed case within 30 days | LPManager |
| POST | `/cases/{case_id}/merge` | Merge this case into a surviving target case | LPManager |
| POST | `/cases/{case_id}/resolve-subject` | Set or correct subject_type/employee_id without a status change | LPManager |
| POST | `/cases/{case_id}/close-referred` | Close a substantiated case as referred after packet acknowledgement | LPManager |
| POST | `/interviews` | Schedule an interview (assignee only) | LPAnalyst |
| GET | `/interviews` | List interviews | All six roles |
| GET | `/interviews/{interview_id}` | Get an interview | All six roles |
| POST | `/interviews/{interview_id}/record-outcome` | Record interview outcome (interviewer only) | LPAnalyst |
| POST | `/interviews/{interview_id}/document` | File documentation for a HELD interview (interviewer only) | LPAnalyst |
| POST | `/interviews/{interview_id}/cancel` | Cancel a SCHEDULED interview | LPAnalyst |
| POST | `/evidence-items` | Attach evidence to a case (assignee only) | LPAnalyst |
| GET | `/evidence-items` | List evidence items | All six roles |
| GET | `/evidence-items/{evidence_id}` | Get an evidence item | All six roles |
| POST | `/evidence-items/{evidence_id}/seal` | Seal evidence (requires a prior COLLECTED custody event) | LPAnalyst |
| POST | `/evidence-items/{evidence_id}/unseal` | Unseal evidence (blocked while legal hold) | LPManager |
| POST | `/evidence-items/{evidence_id}/release` | Release sealed evidence to law enforcement | LPManager |
| POST | `/evidence-items/{evidence_id}/custody-events` | Append a custody event | LPAnalyst, LPManager |
| GET | `/custody-events` | List custody events | All six roles |
| GET | `/custody-events/{custody_event_id}` | Get a custody event | All six roles |
| POST | `/civil-demands` | Draft a civil demand (assignee only; OCC on case version; supersedes any existing DRAFT) | LPAnalyst |
| GET | `/civil-demands` | List civil demands | All six roles |
| GET | `/civil-demands/{demand_id}` | Get a civil demand | All six roles |
| POST | `/civil-demands/{demand_id}/issue` | Issue a DRAFT demand (issuer must differ from drafter) | LPManager |
| POST | `/civil-demands/{demand_id}/write-off` | Write off an issued demand with outstanding at or under the cap | LPManager |
| POST | `/civil-demands/{demand_id}/cancel` | Cancel a DRAFT demand | LPManager |
| POST | `/restitution-payments` | Record a payment against a demand | LPAnalyst |
| GET | `/restitution-payments` | List restitution payments | All six roles |
| GET | `/restitution-payments/{payment_id}` | Get a restitution payment | All six roles |
| POST | `/restitution-payments/{payment_id}/post` | Post a RECEIVED payment (waterfall allocation) | LPAnalyst |
| POST | `/restitution-payments/{payment_id}/return` | Return a POSTED payment (NSF; adds fee, reverses allocations) | LPAnalyst |
| POST | `/orc-groups` | Create an ORC group | LPManager |
| GET | `/orc-groups` | List ORC groups | All six roles |
| GET | `/orc-groups/{group_id}` | Get an ORC group | All six roles |
| POST | `/orc-groups/{group_id}/disrupt` | Mark an ACTIVE_MONITORING group disrupted | LPManager |
| POST | `/orc-groups/{group_id}/dismiss` | Dismiss a group with no PROPOSED and zero CONFIRMED links | LPManager |
| POST | `/case-links` | Propose a link between a case and an ORC group | LPAnalyst |
| GET | `/case-links` | List case links | All six roles |
| GET | `/case-links/{link_id}` | Get a case link | All six roles |
| POST | `/case-links/{link_id}/confirm` | Confirm a PROPOSED link; recomputes group counters and escalation | LPManager |
| POST | `/case-links/{link_id}/reject` | Reject a PROPOSED link | LPManager |
| POST | `/shrink-periods` | Create a shrink period for a store | LPAdmin |
| GET | `/shrink-periods` | List shrink periods | All six roles |
| GET | `/shrink-periods/{period_id}` | Get a shrink period | All six roles |
| POST | `/shrink-periods/{period_id}/record-count` | Record or supersede the physical count (OCC on period version) | LPAdmin |
| POST | `/shrink-periods/{period_id}/reconcile` | Reconcile a COUNTED period; snapshots variance; may auto-create a shrink case | LPAdmin |
| POST | `/shrink-periods/{period_id}/close` | Close a RECONCILED period | LPAdmin |
| POST | `/referral-packets` | Draft a law-enforcement referral packet for a case (assignee only) | LPAnalyst |
| GET | `/referral-packets` | List referral packets | All six roles |
| GET | `/referral-packets/{packet_id}` | Get a referral packet | All six roles |
| POST | `/referral-packets/{packet_id}/seal` | Seal a DRAFT packet (all case evidence sealed with complete custody) | LPAnalyst |
| POST | `/referral-packets/{packet_id}/submit` | Submit a SEALED packet; sets legal hold on case evidence | LPManager |
| POST | `/referral-packets/{packet_id}/acknowledge` | Record the law-enforcement response (ACKNOWLEDGED or RETURNED) | LPManager |
| POST | `/referral-packets/{packet_id}/revise` | Return a RETURNED packet to DRAFT for corrections (assignee only) | LPAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_CASE_ASSIGNEE` | 403 Forbidden |
| `ERR_INTERVIEWER_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_DEMAND_NOT_PAYABLE` | 409 Conflict |
| `ERR_STORE_CLOSED` | 409 Conflict |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_PERIOD_LOCKED` | 409 Conflict |
| `ERR_GROUP_NOT_LINKABLE` | 409 Conflict |
| `ERR_CASE_NOT_REFERRABLE` | 409 Conflict |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PERIOD_VERSION` | 412 Precondition Failed |
| `ERR_SOD_INTERVIEWER_ADJUDICATOR` | 409 Conflict |
| `ERR_SOD_CASE_CREATOR` | 409 Conflict |
| `ERR_SOD_DEMAND_ISSUER` | 409 Conflict |
| `ERR_EVIDENCE_SEALED_IMMUTABLE` | 409 Conflict |
| `ERR_LEGAL_HOLD_ACTIVE` | 409 Conflict |
| `ERR_CUSTODY_GAP` | 409 Conflict |
| `ERR_INTERVIEW_OVERLAP` | 409 Conflict |
| `ERR_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_INTERVIEW_DOC_STALE` | 409 Conflict |
| `ERR_DEMAND_WINDOW_CLOSED` | 409 Conflict |
| `ERR_REOPEN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DUPLICATE_STORE_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_EMPLOYEE_REF` | 409 Conflict |
| `ERR_DUPLICATE_GROUP_NAME` | 409 Conflict |
| `ERR_LINK_EXISTS` | 409 Conflict |
| `ERR_SUBJECT_MISMATCH` | 409 Conflict |
| `ERR_SUBJECT_UNRESOLVED` | 409 Conflict |
| `ERR_NO_ACTIVE_EVIDENCE` | 409 Conflict |
| `ERR_DEMAND_REQUIRED` | 409 Conflict |
| `ERR_PACKET_NOT_READY` | 409 Conflict |
| `ERR_COUNT_REQUIRED` | 409 Conflict |
| `ERR_CASE_HAS_PAYMENTS` | 409 Conflict |
| `ERR_GROUP_HAS_PROPOSED_LINKS` | 409 Conflict |
| `ERR_MERGE_NOT_ALLOWED` | 409 Conflict |
| `ERR_NO_OPEN_PERIOD` | 409 Conflict |
| `ERR_EVIDENCE_UNSEALED` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 409 Conflict |
| `ERR_WRITE_OFF_CAP_EXCEEDED` | 409 Conflict |
| `ERR_RECOVERED_EXCEEDS_LOSS` | 409 Conflict |
| `ERR_BASIS_NOT_ALLOWED` | 409 Conflict |
