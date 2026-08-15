# Premium Audit API — Product Requirements Document

## 1. Introduction

Workers' compensation and general liability policies are sold on estimates: the premium charged at inception is a projection built from estimated payroll, and the carrier's true earned premium can only be known after the policy term ends and actual exposures are examined. The premium audit is that examination — a regulated, deadline-driven process in which the carrier selects expired policies, demands payroll and subcontractor records from the insured, sends auditors into the field (or accepts voluntary reports), verifies classification codes and certificates of insurance, and then bills or refunds the difference between estimated and earned premium. When the insured refuses to cooperate, the carrier needs a defensible estimated-audit path; when the insured disagrees with the outcome, the carrier needs a formal dispute and re-audit process; and when billing goes unpaid, the carrier needs a disciplined escalation that ends in cancellation.

This document specifies the Premium Audit API, the system of record for that entire lifecycle. The API governs audit selection runs, work orders, records requests, appointments, payroll allocations, subcontractor exposures and their certificates, audit results in two computation variants, billing transactions, disputes, re-audits, and experience-modification revisions. Three engineering commitments shape every workflow that follows. First, the system runs on a **logical clock** rather than wall-clock time, because statutory windows — fifteen days to produce records, thirty days to dispute, thirty days to pay — are the substance of the domain and must be drivable deterministically. Second, money and exposure figures are computed under two pinned variants (provisional at draft time, final at issuance) with rounding order fixed by rule, so two competent implementations cannot disagree by a cent. Third, the pipeline enforces segregation of duties: the manager who flags an insured as non-compliant may not approve the resulting estimated billing, and the manager who issued a result may not review its dispute.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly five roles: `Insured`, `Auditor`, `AuditManager`, `Underwriter`, and `BillingClerk`. A request with missing headers, or whose role value is not one of these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two of the five roles are *entity-backed*, and two sentences of identity semantics pin down what `X-User-ID` means for each:

- When `X-User-Role` is `Insured`, `X-User-ID` is the `id` of the acting **Policy**; ownership checks on any resource in a policy's audit graph compare the graph's policy reference to `X-User-ID`. An insured touching another policy's graph is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403). When an `Insured` lists work orders, a supplied `policy_id` filter must equal their `X-User-ID` (otherwise `ERR_FORBIDDEN_SCOPE`), and with no filter supplied only their own policy's orders are listed; likewise, an `Insured` listing policies sees only the policy whose `id` equals `X-User-ID`.
- When `X-User-Role` is `Auditor`, `X-User-ID` is the `id` of the acting **Auditor**; an auditor may only mutate child resources of work orders whose `assigned_auditor_id` equals `X-User-ID`, and violations are rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403).

When `X-User-Role` is `AuditManager`, `Underwriter`, or `BillingClerk`, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity. The server records these identifiers where a workflow requires an actor stamp — for example `marked_noncompliant_by_user_id` on a work order, `drafted_by_user_id` and `issued_by_user_id` on an audit result, and `reviewed_by_user_id` on a dispute — but never compares them to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp (`created_at`) in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Several list endpoints accept additional optional filters named in the workflows below: the policies list accepts `status` and `coverage_line`; the classification-code list accepts `state_code` and `coverage_line`; and the work-order list accepts `policy_id`, `selection_run_id`, `assigned_auditor_id`, and `status`.

### 2.4. The Logical Clock and Scheduled Sweeps

The server maintains a logical clock that governs every deadline in the domain. Before any client call, the clock reads exactly `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock time. An `AuditManager`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc` value.

Setting the clock is never a passive read: each set triggers three sweeps, applied against the new clock value. First, every records request still `OPEN` whose `due_at` is strictly before the new clock moves to `OVERDUE`; a request whose `due_at` equals the clock exactly remains `OPEN`. Second, every billing transaction still `ISSUED` whose `due_at` is strictly before the new clock moves to `PAST_DUE`. Third, any billing transaction that remains unpaid strictly more than thirty days past its `due_at` triggers the policy-cancellation cascade described in §3.8. All three sweeps use strict-greater comparisons at their boundaries.

### 2.5. Common Resource Properties and Immediate Consistency

Every resource in the API — policies, auditors, classification codes, selection runs, work orders, records requests, appointments, payroll allocations, subcontractor exposures, certificates, audit results, disputes, billing transactions, and mod revisions — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): starts at 1 and increments by one on every mutation of the resource.

Derived-field recomputation is a mutation: when a work order's `total_premium_base_dollars` is recomputed, or a subcontractor exposure's `included_dollars` changes, the owning resource's `updated_at` refreshes and, where the workflow states it, its `version` increments. All derived figures are recomputed **within the mutating request** — the consistency model is immediate, with no background settlement.

The resource graph is flat: every resource is addressed by its own top-level path, and relationships are expressed through foreign-key fields and reverse-reachability list endpoints (for example, listing the re-audit orders spawned from a work order, or the mod revisions of a policy). Wherever a request carries path identifiers or foreign-key references, the server validates existence from left to right, rejecting with the not-found code of the first unresolvable identifier.

### 2.6. Money, Exposure, and Rounding Conventions

Monetary amounts are integer cents throughout: premiums, billing amounts, and adjustments are never fractional. Exposure bases — payroll and subcontractor payments — are whole dollars. Manual rates are expressed as cents per one hundred dollars of exposure. Two rounding disciplines are pinned:

- **Round half up** is the only rounding method used for money and dollar figures. Per-class-code premiums are rounded half up to integer cents *before* summing; the order of operations is part of the contract (§3.7).
- **Day counts use closed intervals**: an audit period or certificate coverage window counts both its first and its last day. In contrast, an auditor's calendar treats appointment intervals as *half-open* — the start counts, the end does not — so back-to-back appointments never conflict.

Ratios used by the experience-modification revision are carried unrounded until the final step, where truncation toward zero and a final half-up rounding to two decimals apply (§3.9).

### 2.7. Optimistic Concurrency Control on Work-Order Writes

Exactly two write operations are protected by optimistic concurrency control, and both require the request to carry `expected_work_order_version` holding the client-side `version` of the parent work order as last observed: **scheduling an appointment** on a work order, and **creating a payroll allocation** on a work order. If the supplied value does not equal the work order's current `version` — because another write has advanced it since the client last read the resource — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before acting. Scheduling legitimately supersedes any prior active appointment, and each allocation shifts the work order's derived premium base, so these are precisely the two writes where acting on an unobserved version would silently discard someone else's work. No other endpoint accepts a version field.

### 2.8. Segregation of Duties

Two control points in the pipeline require that different human operators perform complementary steps. The `AuditManager` who approves an estimated (non-compliance) billing must not be the manager who flagged the work order non-compliant: the approver's `X-User-ID` must differ from the work order's `marked_noncompliant_by_user_id`. And the dispute reviewer must not be the issuer of the disputed result: starting review, upholding, or overruling a dispute all require the caller's `X-User-ID` to differ from the result's `issued_by_user_id`. A violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.9. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed order and returns the **first** matching failure:

1. **Authentication** — `X-User-ID` and `X-User-Role` present and the role declared; failure yields `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Request shape** — required fields present, types valid, enum members valid, date orderings respected (`effective_date` strictly before `expiration_date`; `scheduled_end` strictly after `scheduled_start`; `coverage_effective_date` at or before `coverage_expiration_date`; `period_start` strictly before `period_end`), amounts non-negative, `minimum_premium_cents` not exceeding `estimated_annual_premium_cents`, a WC policy's `experience_mod_factor` within the inclusive band from 0.75 to 1.50, a GL policy's `experience_mod_factor` exactly 1.00, and no undeclared fields; any failure yields `ERR_VALIDATION` (400). Applies to every mutating endpoint.
3. **Role authorization** — the caller's role appears in the endpoint's authorized list; failure yields `ERR_FORBIDDEN` (403).
4. **Ownership scoping** — entity-backed callers stay inside their scope as defined in §2.1; failure yields `ERR_FORBIDDEN_SCOPE` (403).
5. **Segregation of duties** — the two control points of §2.8; failure yields `ERR_SEGREGATION_OF_DUTIES` (403).
6. **Existence** — path identifiers and foreign-key inputs resolve, validated left to right; failure yields the matching one of `ERR_POLICY_NOT_FOUND`, `ERR_AUDITOR_NOT_FOUND`, `ERR_CLASS_CODE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_RECORDS_REQUEST_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SUB_EXPOSURE_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_AUDIT_RESULT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_BILLING_NOT_FOUND`, or `ERR_MOD_REVISION_NOT_FOUND` (all 404).
7. **State legality** — the target resource is in a from-state its state machine permits for the attempted transition, and terminal states reject everything; failure yields `ERR_INVALID_STATE_TRANSITION` (409).
8. **Optimistic concurrency** — the `expected_work_order_version` check of §2.7; failure yields `ERR_STALE_VERSION` (412).
9. **Time windows** — appointment placement within the post-term window and dispute filing within its deadline; failures yield `ERR_APPOINTMENT_OUTSIDE_WINDOW` or `ERR_DISPUTE_WINDOW_CLOSED` (both 409).
10. **Business constraints** — the remaining domain guards, each with its own code: `ERR_APPOINTMENT_OVERLAP`, `ERR_ALLOCATION_PERIOD_OVERLAP`, `ERR_OPEN_RECORDS_REQUESTS`, `ERR_DRAFT_ALLOCATIONS_PENDING`, `ERR_RESCHEDULE_LIMIT_EXCEEDED`, `ERR_CERT_INSUFFICIENT_COVERAGE`, `ERR_CERT_WINDOW_INSUFFICIENT`, `ERR_AUDITOR_TERRITORY_MISMATCH`, `ERR_NO_NONCOMPLIANCE_BASIS`, `ERR_DUPLICATE_RECORDS_REQUEST`, `ERR_DUPLICATE_POLICY_NUMBER`, and `ERR_DUPLICATE_CLASS_CODE` (all 409).
11. **Fiscal guard** — a recorded payment must not exceed the remaining balance of its billing transaction; failure yields `ERR_OVERPAYMENT` (422).

## 3. Business Logic & Workflows

### 3.1. Setting Up the Book: Policies, Classification Codes, and Auditors

An `Underwriter` onboards a policy by supplying its `policy_number` — unique across the carrier, with duplicates rejected by `ERR_DUPLICATE_POLICY_NUMBER` — the `insured_name`, the `coverage_line` (either `WC` for workers' compensation or `GL` for general liability), the two-letter `state_code` that governs territory and class-code jurisdiction, the `effective_date` and `expiration_date` bounding the term (the former strictly earlier than the latter), the `estimated_annual_premium_cents` charged at inception (greater than zero), the `minimum_premium_cents` floor on earned premium (greater than zero and no more than the estimated annual premium), and the `payroll_estimate_dollars` exposure estimate (greater than zero, whole dollars). The `experience_mod_factor` is optional and defaults to 1.00; on a WC policy it must sit within the inclusive band 0.75 to 1.50, while on a GL policy it must equal exactly 1.00. Finally, `class_code_ids` binds the classification codes in force at inception: every id must resolve to an existing classification code whose coverage line and state match the policy, and whose rate-effective window overlaps the policy term; an unresolvable id is rejected with `ERR_CLASS_CODE_NOT_FOUND`. A new policy begins life `ACTIVE`. Over its lifetime a policy's status moves through `AUDIT_PENDING` while an audit is open, reaches `AUDIT_FINALIZED` when the last open audit closes, and can fall to the terminal `CANCELLED` either by manual cancellation or by the billing-delinquency cascade of §3.8.

Classification codes are maintained by an `Underwriter` as well. Each carries its class-code digits in `code`, a human-readable `description`, the governing `state_code`, its `coverage_line` (`WC` or `GL`), a `rate_per_100_cents` manual rate (cents per hundred dollars of exposure, greater than zero), an optional `high_hazard` flag defaulting to false — high-hazard classes force a physical audit regardless of premium size — and a rate-effective window from `effective_from` (strictly earlier) to `effective_to`. The triple of code digits, state, and coverage line is unique; reusing it is rejected with `ERR_DUPLICATE_CLASS_CODE`.

An `AuditManager` registers field staff by creating auditors with a `full_name`, a non-empty `territory_states` array of two-letter state codes the auditor may serve, and a `level` of either `STAFF` or `SENIOR`.

### 3.2. Audit Selection Runs and Work Order Genesis

When an `AuditManager` triggers an audit selection run, the system scans the book for policies that are `ACTIVE` and whose `expiration_date` is at or before the current logical clock. Eligible policies are processed in a deterministic order — earliest `expiration_date` first, ties broken by `policy_number` ascending, never by resource id. A policy that already carries a work order in any state other than `CLOSED`, `SUPERSEDED_BY_REAUDIT`, or `CANCELLED` is skipped silently; it is not an error and produces no work order.

Each remaining policy is tiered. A policy is selected at the `PHYSICAL` tier when its `estimated_annual_premium_cents` is at least 1,000,000 cents (ten thousand dollars of estimated premium) **or** any classification code in its `class_code_ids` is flagged `high_hazard`. Failing that, a policy whose estimated annual premium is at least 500,000 cents (five thousand dollars) is selected at the `VOLUNTARY_REPORT` tier. Both thresholds are inclusive: a policy at exactly 1,000,000 cents is physical, and one at exactly 500,000 cents — and not otherwise physical — is voluntary-report. Everything else is exempt: no work order is created and the policy simply stays `ACTIVE`.

For each selected policy the system creates an **AuditWorkOrder** in the `SELECTED` state, stamped with the run via `selection_run_id`, linked to the policy via `policy_id`, carrying an `audit_type` of `PHYSICAL` or `VOLUNTARY_REPORT`, with `reaudit_of_work_order_id` null, `assigned_auditor_id` null, `no_show_count` zero, and `audit_period_start` and `audit_period_end` copied from the policy's term dates. Selecting a policy flips it from `ACTIVE` to `AUDIT_PENDING` and increments `Policy.version`. The run itself is persisted with the clock time in `run_at` and four counters: `evaluated_count` (policies scanned), `physical_count` and `voluntary_count` (work orders created at each tier), and `exempt_count` (evaluated policies exempted).

A work order's full state alphabet is `SELECTED`, `RECORDS_REQUESTED`, `APPOINTMENT_SCHEDULED`, `FIELD_WORK_DONE`, `RESULT_DRAFTED`, `BILLED`, `DISPUTED`, `NONCOMPLIANT_PENDING`, `ESTIMATED_BILLED`, and the three terminal states `CLOSED`, `SUPERSEDED_BY_REAUDIT`, and `CANCELLED`. Its `total_premium_base_dollars` — the running exposure base — is recomputed on every allocation or certificate mutation as the sum of `auditable_payroll_dollars` over the work order's `VERIFIED` payroll allocations plus the sum of `included_dollars` over all of its subcontractor exposures.

### 3.3. Assignment, Records Requests, and Intake

A freshly selected work order has no auditor. An `AuditManager` assigns one by supplying an `auditor_id`; assignment is permitted only while the work order is `SELECTED` or `RECORDS_REQUESTED` (any other state is rejected with `ERR_INVALID_STATE_TRANSITION`), and the auditor's `territory_states` must include the audited policy's `state_code`, failing which the assignment is rejected with `ERR_AUDITOR_TERRITORY_MISMATCH`. A successful assignment sets `assigned_auditor_id` and increments the work order's `version`.

Records intake begins when an `AuditManager` files the first records request against the work order, moving it `SELECTED → RECORDS_REQUESTED` and incrementing its `version`; further requests may be added while the order remains in either of those two states. Each request names a `request_type` — one of `PAYROLL_SUMMARY`, `TAX_FILINGS`, `SUBCONTRACTOR_LIST`, `CERTIFICATES_OF_INSURANCE`, or `SALES_LEDGER` — and at most one non-terminal request (`OPEN` or `OVERDUE`) of each type may exist per work order; a repeat is rejected with `ERR_DUPLICATE_RECORDS_REQUEST`. A new request is born `OPEN`, stamped `requested_at` with the logical clock, with `due_at` fixed at fifteen days after `requested_at`, and linked to its work order via `audit_work_order_id`. When the clock is later set strictly past `due_at`, the request flips to `OVERDUE`; sitting exactly at `due_at` leaves it `OPEN`.

Receipt is recorded by the assigned auditor — a caller who is not the work order's assigned auditor is rejected with `ERR_FORBIDDEN_SCOPE` — moving the request from `OPEN` or `OVERDUE` to `RECEIVED` and stamping `received_at` with the clock; late receipt from `OVERDUE` is explicitly permitted. An `AuditManager` may instead waive a request from `OPEN` or `OVERDUE`, moving it to `WAIVED`. Both `RECEIVED` and `WAIVED` are terminal. The insured's obligation is considered fulfilled for drafting purposes only when every request of the work order has reached one of those two states (§3.7).

### 3.4. Field Work: Appointments from Scheduling to Completion

Physical and re-audit work orders require a field appointment; voluntary-report orders skip field work entirely. The assigned auditor schedules an appointment while the work order is `RECORDS_REQUESTED` (first appointment) or `APPOINTMENT_SCHEDULED` (rescheduling after a no-show). The payload carries `scheduled_start`, `scheduled_end`, a `location_type` of `INSURED_PREMISES`, `VIRTUAL`, or `AUDITOR_OFFICE`, and the OCC token `expected_work_order_version` per §2.7. Scheduling is guarded by five checks beyond existence and role:

- The work order's `audit_type` must be `PHYSICAL` or `REAUDIT`; a voluntary-report order rejects the attempt with `ERR_INVALID_STATE_TRANSITION`.
- The caller must be the work order's assigned auditor (`ERR_FORBIDDEN_SCOPE` otherwise).
- The work order's `no_show_count` must still be below two; at two no-shows the insured has exhausted rescheduling and the attempt is rejected with `ERR_RESCHEDULE_LIMIT_EXCEEDED`.
- The appointment must sit in the post-term window: `scheduled_start` strictly after `audit_period_end` and no later than sixty days after it, with `scheduled_end` strictly after `scheduled_start`; violations are rejected with `ERR_APPOINTMENT_OUTSIDE_WINDOW`. The lower bound is strict, the upper inclusive.
- The auditor's calendar must be free: across **all** work orders of any policy, the auditor's `SCHEDULED` and `CONFIRMED` appointments are treated as half-open intervals, and a conflict exists exactly when the new appointment starts before an existing one ends while that existing one starts before the new one ends — back-to-back placement (the new start equal to an existing end) does **not** conflict. Conflicts are rejected with `ERR_APPOINTMENT_OVERLAP`.

On success the appointment is created `SCHEDULED` with its `auditor_id` copied from the work order's `assigned_auditor_id` and linked via `audit_work_order_id`; any prior appointment of the same work order in `SCHEDULED` or `CONFIRMED` is automatically moved to `CANCELLED` (the new appointment supersedes it); the work order moves to `APPOINTMENT_SCHEDULED` and its `version` increments by one.

From `SCHEDULED`, an appointment may be confirmed — moving it to `CONFIRMED` — either by the insured who owns the audited policy (an `Insured` caller whose `X-User-ID` equals the policy's `id`) or by the appointment's auditor; anyone else is rejected with `ERR_FORBIDDEN_SCOPE`. Completion is the auditor's act: from `SCHEDULED` or `CONFIRMED` the appointment's auditor marks it `COMPLETED`, which in the same request advances the parent work order `APPOINTMENT_SCHEDULED → FIELD_WORK_DONE` and increments the work order's `version`. If the insured fails to appear, the appointment's auditor records a no-show from `SCHEDULED` or `CONFIRMED`, moving the appointment to `NO_SHOW`, incrementing the parent work order's `no_show_count` by one, and incrementing its `version`. `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal for an appointment; cancellation itself is system-driven only — by supersession above or by the policy cascade of §3.8.

### 3.5. Payroll Allocations and the Auditable Base

Once records are flowing, the assigned auditor allocates payroll to classification codes. Allocation creation is accepted while the work order is `RECORDS_REQUESTED`, `APPOINTMENT_SCHEDULED`, `FIELD_WORK_DONE`, or `RESULT_DRAFTED` (any other state draws `ERR_INVALID_STATE_TRANSITION`), and it is an OCC-guarded write requiring `expected_work_order_version` (§2.7). The payload names the `class_code_id` — which must resolve (`ERR_CLASS_CODE_NOT_FOUND`) and whose coverage line must equal the audited policy's `coverage_line` (`ERR_VALIDATION` on mismatch) — the closed coverage period from `period_start` (strictly earlier) to `period_end`, the `gross_payroll_dollars` (zero or more), and four optional exclusion fields: `overtime_excess_dollars` (the half-time overtime premium portion, default 0), `overtime_documented` (whether payroll records separately evidence that excess, default false), `severance_dollars` (default 0), and `other_exclusions_dollars` (default 0). The allocation is linked to its work order via `audit_work_order_id`.

From these inputs the system derives `auditable_payroll_dollars`: start from gross payroll, subtract severance and other statutory exclusions always, subtract the overtime excess **only when** `overtime_documented` is true, and floor the result at zero. The figure is kept in whole dollars.

Within one work order, allocations to the *same* class code must not double-count a period: the closed intervals of all non-`REJECTED` allocations sharing a `class_code_id` are compared pairwise, and two periods conflict when each starts on or before the other's end — which means sharing a boundary day already conflicts and is rejected with `ERR_ALLOCATION_PERIOD_OVERLAP`. Allocations under different class codes may cover identical periods without conflict.

An allocation is born `DRAFT`. The assigned auditor later verifies it (`DRAFT → VERIFIED`) or rejects it (`DRAFT → REJECTED`) while the parent work order is in `RECORDS_REQUESTED`, `APPOINTMENT_SCHEDULED`, `FIELD_WORK_DONE`, or `RESULT_DRAFTED`; both outcomes are terminal, and either one recomputes the work order's `total_premium_base_dollars` as defined in §3.2. Draft allocations are provisional-only material: they feed the draft result (§3.7) but block issuance until resolved.

### 3.6. Subcontractor Exposures and Certificate Review

Uninsured subcontractors become the insured's exposure at audit. The assigned auditor registers a subcontractor exposure — again only while the work order is `RECORDS_REQUESTED`, `APPOINTMENT_SCHEDULED`, `FIELD_WORK_DONE`, or `RESULT_DRAFTED` — by supplying the `subcontractor_name`, the `payments_dollars` made to that subcontractor during the audit period (zero or more), and the `governing_class_code_id` under whose rate any included dollars will be priced. A new exposure starts `INCLUDED` at full value: `included_dollars` equals `payments_dollars`, and the work order's `total_premium_base_dollars` is recomputed immediately. The exposure is linked to its work order via `audit_work_order_id`.

The insured (owning the policy) or an auditor may then submit a certificate of insurance for the exposure — again within the same four-state work-order window — providing the `insurer_name`, two coverage flags `wc_coverage_present` and `gl_coverage_present`, and the certificate's closed coverage window from `coverage_effective_date` (at or before) to `coverage_expiration_date`. The certificate is born `SUBMITTED` and linked via `subcontractor_exposure_id`.

Certificate disposition is the assigned auditor's call. Verification requires two things: the coverage flag matching the policy's line must be present — a WC policy demands `wc_coverage_present`, a GL policy demands `gl_coverage_present`, and absence is rejected with `ERR_CERT_INSUFFICIENT_COVERAGE` — and the certificate's closed coverage interval must intersect the audit period, a fully disjoint window being rejected with `ERR_CERT_WINDOW_INSUFFICIENT`. Rejection instead takes a `reason` of `INSUFFICIENT_COVERAGE`, `EXPIRED`, or `OTHER`, which is recorded on the certificate as `rejection_reason`. `VERIFIED` and `REJECTED` are terminal.

Every verify or reject immediately recomputes the exposure's inclusion using closed-interval day counts (both endpoints counted). With an acceptable certificate in force, the overlap between the certificate's coverage window and the audit period is counted in days: if the certificate covers the entire audit period the exposure becomes `EXCLUDED` with `included_dollars` zero; if it covers only part, the exposure becomes `PARTIAL_INCLUDED` and `included_dollars` is the payments prorated to the *uncovered* share — payments multiplied by uncovered days and divided by total period days, rounded half up to whole dollars. With no acceptable certificate the exposure is (or returns to) `INCLUDED` at full `payments_dollars`. A later rejection that removes the last verified certificate therefore moves an `EXCLUDED` or `PARTIAL_INCLUDED` exposure back to `INCLUDED`, and subsequent certificate events recompute between `EXCLUDED` and `PARTIAL_INCLUDED` as coverage changes. Each recomputation also refreshes the work order's `total_premium_base_dollars`. By way of illustration: over a 212-day audit period, a certificate covering 153 of those days leaves 59 uncovered; on payments of 20,000 dollars the included amount is twenty thousand multiplied by fifty-nine and divided by two hundred twelve, rounded half up — 5,566 dollars.

Which certificates count as "acceptable" depends on the computation variant of §3.7: at draft time a `SUBMITTED` certificate is treated as if it were verified at full coverage, while at issuance only `VERIFIED` certificates count and a still-`SUBMITTED` certificate counts as no certificate at all.

### 3.7. Drafting and Issuing the Audit Result

With field work complete — or, for a voluntary-report order, with records in hand — the assigned auditor submits the draft result. A `PHYSICAL` or `REAUDIT` order drafts from `FIELD_WORK_DONE`; a `VOLUNTARY_REPORT` order drafts directly from `RECORDS_REQUESTED`, and attempting the wrong path is rejected with `ERR_INVALID_STATE_TRANSITION`. Every records request of the work order must first be `RECEIVED` or `WAIVED`; an `OPEN` or `OVERDUE` request blocks drafting with `ERR_OPEN_RECORDS_REQUESTS`. Submission creates the **AuditResult** — at most one ever exists per work order — in `PRELIMINARY` status with `variant` `STANDARD`, records the caller in `drafted_by_user_id`, links it via `audit_work_order_id`, moves the work order to `RESULT_DRAFTED`, and increments its `version`.

Both draft and issuance price the exposure the same way; only the input sets differ. The **manual premium** aggregates, per class code, the auditable payroll of the included allocations plus the included dollars of subcontractor exposures under each exposure's governing class code. For each class code the premium is that code's base multiplied by its `rate_per_100_cents` and divided by one hundred, **rounded half up to integer cents per class code first**, and only then summed into `manual_premium_cents`. The rounding order is pinned — summing the bases first and rounding once is forbidden, because the two orders disagree (two codes rated at 25 cents with bases of 150 dollars each yield 38 + 38 = 76 cents under the pinned order, versus 75 cents if summed first). The **earned premium** for the `STANDARD` variant multiplies the manual premium by the policy's current `experience_mod_factor`, rounds half up to integer cents, and then applies the minimum-premium floor: the result is the greater of the modified premium and the policy's `minimum_premium_cents`. The mod factor in force at computation time is captured on the result as `mod_factor_applied` and is never retroactively changed, and the exposure dollars that fed the manual premium are recorded as `total_payroll_dollars`.

The **provisional** variant, used at draft time, draws its input set from `DRAFT` and `VERIFIED` allocations alike and treats `SUBMITTED` certificates as full-coverage exclusions. The **final** variant, used at issuance, restricts the input set to `VERIFIED` allocations only and counts `VERIFIED` certificates only — a certificate still `SUBMITTED` counts as no certificate.

Issuance belongs to an `AuditManager`. It is blocked while any payroll allocation of the work order is still `DRAFT` (`ERR_DRAFT_ALLOCATIONS_PENDING`). On issuance the result is recomputed under the final variant with `mod_factor_applied` refreshed to the policy's current mod, moves `PRELIMINARY → ISSUED`, records `issued_by_user_id` and stamps `issued_at` with the clock, and computes `adjustment_cents` as earned premium minus the policy's `estimated_annual_premium_cents` — a signed figure, positive when more premium is due. Whenever the adjustment is non-zero, a **BillingTransaction** is created with its `type` set to `ADDITIONAL_PREMIUM_INVOICE` when the adjustment is positive and `RETURN_PREMIUM_CREDIT` when negative, with `amount_cents` equal to the absolute adjustment, `paid_cents` zero, `issued_at` at the clock, `due_at` thirty days after `issued_at`, and status `ISSUED`. A zero adjustment creates no billing at all. Issuance moves the work order `RESULT_DRAFTED → BILLED` and increments its `version`. For WC policies only, issuance also evaluates the payroll variance and may spawn a mod revision (§3.9). The evaluation order is pinned end to end: final payroll totals first, then manual premium, then earned premium with the *pre-revision* mod factor, then the billing adjustment, and only then the mod revision — the issued result always reflects the mod in force at issue time.

### 3.8. Non-Compliance, Estimated Billing, and Delinquency

When an insured stonewalls, the audit does not stall. An `AuditManager` may flag non-compliance while the work order is `RECORDS_REQUESTED` or `APPOINTMENT_SCHEDULED`, but only when at least one of its records requests stands `OVERDUE`; without that basis the flag is rejected with `ERR_NO_NONCOMPLIANCE_BASIS`. The flag moves the work order to `NONCOMPLIANT_PENDING`, records the caller in `marked_noncompliant_by_user_id`, and increments its `version`.

A *different* `AuditManager` then approves the estimated audit — the segregation-of-duties rule of §2.8 rejects the marker-turned-approver with `ERR_SEGREGATION_OF_DUTIES`. Approval creates the result directly in `ISSUED` (estimated results never pass through `PRELIMINARY`) with `variant` `ESTIMATED_NONCOMPLIANCE`: `earned_premium_cents` is the policy's `estimated_annual_premium_cents` multiplied by 1.25 and rounded half up to integer cents, **bypassing both the minimum-premium floor and the experience mod factor**. `drafted_by_user_id` stays null, `issued_by_user_id` and `issued_at` are set, the signed `adjustment_cents` is computed, and a billing transaction is created under the same invoice-or-credit rule with `due_at` thirty days out. The work order moves to `ESTIMATED_BILLED` with a version increment.

Settlement of any billing is the `BillingClerk`'s desk. Payments and credit applications may be recorded against a transaction in either `ISSUED` or `PAST_DUE` standing. Recording a payment (against an invoice) or a credit application (against a return premium) supplies `amount_cents`; the amount must not exceed the remaining balance — `amount_cents` minus `paid_cents` — or the recording is rejected with `ERR_OVERPAYMENT` (HTTP 422). Each accepted recording adds to `paid_cents`, and when the cumulative figure reaches the full amount an invoice becomes `PAID` and a credit becomes `APPLIED`; both are terminal, as is `CANCELLED`. Billing delinquency is clock-driven: strictly past `due_at` an `ISSUED` transaction becomes `PAST_DUE`, and a transaction still unpaid strictly more than thirty days past `due_at` cancels the policy outright.

Policy cancellation — whether entered manually by an `Underwriter` or fired by the delinquency sweep — moves the policy to terminal `CANCELLED` from `ACTIVE`, `AUDIT_PENDING`, or `AUDIT_FINALIZED`, increments `Policy.version`, and cascades: every work order of the policy in a non-terminal state moves to `CANCELLED`, every appointment of those work orders in `SCHEDULED` or `CONFIRMED` moves to `CANCELLED`, and every billing transaction of the policy's results in `ISSUED` or `PAST_DUE` moves to `CANCELLED`. From `AUDIT_FINALIZED` there are no open work orders left, so only the billing leg of the cascade applies. One fiscal invariant survives all of this: across all of a policy's work orders, the signed sum of non-cancelled billing amounts — invoices counting positive, credits negative — always equals the `adjustment_cents` of the policy's latest issued, non-superseded result.

### 3.9. Disputes, Re-Audit, Closure, and Experience Modification

An insured who disagrees with an issued result files a dispute, choosing `grounds` of `CLASSIFICATION_ERROR`, `PAYROLL_ERROR`, `SUBCONTRACTOR_INCLUSION`, `CERT_REVIEW_ERROR`, or `OTHER`. The result must be `ISSUED`, and the filing window is thirty days: the logical clock must be at or before `issued_at` plus thirty days — filing exactly at the deadline succeeds, one second later draws `ERR_DISPUTE_WINDOW_CLOSED`. Filing creates the **Dispute** `FILED` with `filed_at` at the clock and `audit_result_id` linking it to the result, moves the result `ISSUED → DISPUTED`, and moves the work order `BILLED → DISPUTED` (for a standard result) or `ESTIMATED_BILLED → DISPUTED` (for an estimated one), incrementing the work order's `version`.

Review is an `AuditManager` function under the segregation-of-duties rule of §2.8: starting review requires the caller to differ from the result's `issued_by_user_id` (`ERR_SEGREGATION_OF_DUTIES` otherwise), moves the dispute `FILED → UNDER_REVIEW`, and records the caller in `reviewed_by_user_id`. From `UNDER_REVIEW` there are two dispositions, both under the same segregation rule. **Overruling** moves the dispute to `OVERRULED`, returns the result `DISPUTED → ISSUED`, and returns the work order to `BILLED` or `ESTIMATED_BILLED` according to the result's variant, with a version increment. **Upholding** moves the dispute to `UPHELD`, moves the result `DISPUTED → SUPERSEDED` (terminal), cancels every billing of that result still `ISSUED` or `PAST_DUE` as compensation, moves the work order to terminal `SUPERSEDED_BY_REAUDIT` with a version increment, and spawns the corrective audit: a brand-new work order with `audit_type` `REAUDIT`, status `SELECTED`, `reaudit_of_work_order_id` pointing at the superseded order, `selection_run_id` null (re-audits are born of disputes, not selection runs), the audit period copied from the policy, and `assigned_auditor_id` null. The re-audit order then flows through the ordinary pipeline — assignment, records, appointment (re-audits take the physical path), allocations, draft, issuance — under all the same rules.

A billed audit is closed by an `AuditManager` once two conditions hold: every billing transaction of the work order's result stands `PAID` or `APPLIED` (or no billing exists because the adjustment was zero), and the logical clock has passed strictly beyond `issued_at` plus thirty days, so the dispute window has elapsed. Either failure is rejected with `ERR_INVALID_STATE_TRANSITION`. Closing moves the work order to `CLOSED` and increments its `version`; when no other work order of the same policy remains in a non-terminal state, the policy itself moves `AUDIT_PENDING → AUDIT_FINALIZED` with a `Policy.version` increment.

Finally, audit findings feed back into pricing. When a `STANDARD` result is issued for a WC policy, the system computes the payroll variance ratio — the audited payroll total minus `payroll_estimate_dollars`, divided by `payroll_estimate_dollars`, kept unrounded. If the ratio's absolute value is below 0.05 (five percent), nothing happens. Otherwise a **ModRevision** is created in `DRAFT`, linked by `policy_id` and `source_work_order_id`, recording the policy's then-current mod as `prior_mod_factor` and the ratio as `payroll_variance_ratio`. The `revised_mod_factor` multiplies the ratio by twenty — one hundredth of mod movement per full five percent of variance — truncates toward zero, adds those hundredths to the prior mod, rounds half up to two decimals, and clamps the outcome to the inclusive band 0.75 to 1.50. Truncation toward zero matters at the boundaries: a variance of −0.075 yields one downward step, not two, so a prior mod of 1.20 revises to 1.19 (a floor would have produced 1.18); a variance of exactly −0.05 yields one step as well, from 1.20 to 1.19; and a prior mod of 1.48 meeting a variance of +0.25 computes 1.53 but clamps to 1.50. A revision takes effect only when an `Underwriter` applies it: the revision moves `DRAFT → APPLIED`, the policy's `experience_mod_factor` becomes `revised_mod_factor`, and `Policy.version` increments — but a revision on a `CANCELLED` policy can no longer be applied and is rejected with `ERR_INVALID_STATE_TRANSITION`.

## 4. Endpoint Definitions

Operations that create a new resource — a policy, auditor, classification code, selection run, records request, appointment, payroll allocation, subcontractor exposure, certificate, draft result, or dispute — return `201 Created`. Operations that modify an existing resource in place — assignments, state transitions, receipts, verifications, issuance, payments, cancellations, and the clock set — return `200 OK`. Request and response payloads are not restated here; they are defined by the workflows of §3 and the envelope contract of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; runs overdue, past-due, and cancellation sweeps | AuditManager |
| POST | `/policies` | Create a policy (starts ACTIVE) | Underwriter |
| GET | `/policies` | List policies with pagination and optional filters | Insured, Auditor, AuditManager, Underwriter, BillingClerk |
| GET | `/policies/{id}` | Get a policy | Insured, Auditor, AuditManager, Underwriter, BillingClerk |
| POST | `/policies/{id}/cancel` | Cancel a policy and cascade to work orders, appointments, billings | Underwriter |
| GET | `/policies/{id}/mod-revisions` | List a policy's mod revisions | Insured, AuditManager, Underwriter |
| POST | `/auditors` | Create an auditor | AuditManager |
| GET | `/auditors` | List auditors | Auditor, AuditManager, Underwriter |
| GET | `/auditors/{id}` | Get an auditor | Auditor, AuditManager, Underwriter |
| GET | `/auditors/{id}/appointments` | List an auditor's appointments | Auditor, AuditManager |
| POST | `/classification-codes` | Create a classification code with rate | Underwriter |
| GET | `/classification-codes` | List classification codes with optional filters | Insured, Auditor, AuditManager, Underwriter, BillingClerk |
| GET | `/classification-codes/{id}` | Get a classification code | Insured, Auditor, AuditManager, Underwriter, BillingClerk |
| GET | `/classification-codes/{id}/payroll-allocations` | List payroll allocations referencing this class code | Auditor, AuditManager, Underwriter |
| GET | `/classification-codes/{id}/subcontractor-exposures` | List subcontractor exposures governed by this class code | Auditor, AuditManager, Underwriter |
| POST | `/audit-selection-runs` | Run audit selection over expired ACTIVE policies; creates work orders | AuditManager |
| GET | `/audit-work-orders` | List work orders with optional filters | Insured, Auditor, AuditManager, Underwriter, BillingClerk |
| GET | `/audit-work-orders/{id}` | Get a work order | Insured, Auditor, AuditManager, Underwriter, BillingClerk |
| GET | `/audit-work-orders/{id}/reaudits` | List re-audit work orders spawned from this work order | Insured, Auditor, AuditManager, Underwriter |
| GET | `/audit-work-orders/{id}/mod-revisions` | List mod revisions sourced from this work order | AuditManager, Underwriter |
| GET | `/audit-work-orders/{id}/records-requests` | List a work order's records requests | Insured, Auditor, AuditManager |
| GET | `/audit-work-orders/{id}/appointments` | List a work order's appointments | Insured, Auditor, AuditManager |
| GET | `/audit-work-orders/{id}/payroll-allocations` | List a work order's payroll allocations | Insured, Auditor, AuditManager |
| GET | `/audit-work-orders/{id}/subcontractor-exposures` | List a work order's subcontractor exposures | Insured, Auditor, AuditManager |
| GET | `/audit-work-orders/{id}/result` | Get the work order's audit result (array of zero or one) | Insured, Auditor, AuditManager, Underwriter, BillingClerk |
| POST | `/audit-work-orders/{id}/assign` | Assign an auditor (territory must cover the policy's state) | AuditManager |
| POST | `/audit-work-orders/{id}/records-requests` | Create a records request; first request starts intake | AuditManager |
| POST | `/audit-work-orders/{id}/appointments` | Schedule an appointment (OCC; supersedes any active appointment) | Auditor |
| POST | `/audit-work-orders/{id}/payroll-allocations` | Create a payroll allocation (OCC; per-class-code overlap check) | Auditor |
| POST | `/audit-work-orders/{id}/subcontractor-exposures` | Create a subcontractor exposure (initially fully included) | Auditor |
| POST | `/audit-work-orders/{id}/submit-draft` | Submit the draft audit result (provisional figures) | Auditor |
| POST | `/audit-work-orders/{id}/issue-result` | Issue the final result; creates billing and possibly a mod revision | AuditManager |
| POST | `/audit-work-orders/{id}/mark-noncompliant` | Flag non-compliance (requires an overdue records request) | AuditManager |
| POST | `/audit-work-orders/{id}/approve-estimated` | Approve an estimated audit at 125% of estimated premium | AuditManager |
| POST | `/audit-work-orders/{id}/close` | Close a billed work order once settled and past the dispute window | AuditManager |
| GET | `/records-requests/{id}` | Get a records request | Insured, Auditor, AuditManager |
| POST | `/records-requests/{id}/receive` | Mark a records request received (late receipt allowed) | Auditor |
| POST | `/records-requests/{id}/waive` | Waive a records request | AuditManager |
| GET | `/appointments/{id}` | Get an appointment | Insured, Auditor, AuditManager |
| POST | `/appointments/{id}/confirm` | Confirm a scheduled appointment | Insured, Auditor |
| POST | `/appointments/{id}/complete` | Complete an appointment; advances the work order to field-work-done | Auditor |
| POST | `/appointments/{id}/no-show` | Record an insured no-show | Auditor |
| GET | `/payroll-allocations/{id}` | Get a payroll allocation | Insured, Auditor, AuditManager |
| POST | `/payroll-allocations/{id}/verify` | Verify a draft allocation | Auditor |
| POST | `/payroll-allocations/{id}/reject` | Reject a draft allocation | Auditor |
| GET | `/subcontractor-exposures/{id}` | Get a subcontractor exposure | Insured, Auditor, AuditManager |
| POST | `/subcontractor-exposures/{id}/certificates` | Submit a certificate of insurance for the exposure | Insured, Auditor |
| GET | `/subcontractor-exposures/{id}/certificates` | List an exposure's certificates | Insured, Auditor, AuditManager |
| POST | `/certificates/{id}/verify` | Verify a certificate (coverage flag and window checks) | Auditor |
| POST | `/certificates/{id}/reject` | Reject a certificate with a reason | Auditor |
| GET | `/audit-results/{id}` | Get an audit result | Insured, Auditor, AuditManager, Underwriter, BillingClerk |
| POST | `/audit-results/{id}/disputes` | File a dispute against an issued result (30-day window) | Insured |
| GET | `/audit-results/{id}/disputes` | List a result's disputes | Insured, Auditor, AuditManager, Underwriter |
| GET | `/audit-results/{id}/billing-transactions` | List a result's billing transactions | Insured, AuditManager, Underwriter, BillingClerk |
| GET | `/disputes/{id}` | Get a dispute | Insured, AuditManager, Underwriter |
| POST | `/disputes/{id}/start-review` | Start reviewing a dispute (reviewer must not be the issuer) | AuditManager |
| POST | `/disputes/{id}/uphold` | Uphold: supersede the result, cancel its billings, spawn a re-audit | AuditManager |
| POST | `/disputes/{id}/overrule` | Overrule: result and work order return to their billed states | AuditManager |
| GET | `/billing-transactions/{id}` | Get a billing transaction | Insured, AuditManager, Underwriter, BillingClerk |
| POST | `/billing-transactions/{id}/record-payment` | Record a payment or credit application; overpayment rejected | BillingClerk |
| POST | `/mod-revisions/{id}/apply` | Apply a mod revision to the policy | Underwriter |

## 5. Error Code Catalogue

Trigger conditions for each code are specified where the guarded workflow appears in §2 and §3; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_VALIDATION` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_FORBIDDEN_SCOPE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_AUDITOR_NOT_FOUND` | 404 |
| `ERR_CLASS_CODE_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_RECORDS_REQUEST_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_SUB_EXPOSURE_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_AUDIT_RESULT_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_BILLING_NOT_FOUND` | 404 |
| `ERR_MOD_REVISION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_APPOINTMENT_OUTSIDE_WINDOW` | 409 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 |
| `ERR_APPOINTMENT_OVERLAP` | 409 |
| `ERR_ALLOCATION_PERIOD_OVERLAP` | 409 |
| `ERR_OPEN_RECORDS_REQUESTS` | 409 |
| `ERR_DRAFT_ALLOCATIONS_PENDING` | 409 |
| `ERR_RESCHEDULE_LIMIT_EXCEEDED` | 409 |
| `ERR_CERT_INSUFFICIENT_COVERAGE` | 409 |
| `ERR_CERT_WINDOW_INSUFFICIENT` | 409 |
| `ERR_AUDITOR_TERRITORY_MISMATCH` | 409 |
| `ERR_NO_NONCOMPLIANCE_BASIS` | 409 |
| `ERR_DUPLICATE_RECORDS_REQUEST` | 409 |
| `ERR_DUPLICATE_POLICY_NUMBER` | 409 |
| `ERR_DUPLICATE_CLASS_CODE` | 409 |
| `ERR_OVERPAYMENT` | 422 |
