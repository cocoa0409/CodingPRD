# Employment Background Screening API — Product Requirements Document

## 1. Introduction

This document specifies the Employment Background Screening API, a vendor-management platform for an employer's HR screening program. The system orchestrates the full lifecycle of pre-employment background checks — from the moment a hiring manager opens a screening order against a candidate and a position, through consent capture under FCRA's standalone-disclosure requirement, dispatch to a third-party screening vendor, report delivery, adjudication against a configurable matrix, adverse-action notice timing, candidate dispute and re-investigation, and ultimately vendor accuracy auditing with automated re-screen sweeps.

The business problem is threefold. First, compliance: ban-the-box ordinances, jurisdiction-specific lookback limits, FCRA pre-adverse waiting periods, and the EEOC's individualized-assessment guidance all impose rules that vary by work location and risk tier, and getting any of them wrong exposes the employer to litigation. Second, vendor accountability: screening vendors are paid per order, breach turnaround SLAs, and occasionally deliver inaccurate reports, so the platform must measure accuracy in a pooled, auditable way and automatically trigger re-screening at a different vendor when measured quality falls below threshold. Third, segregation of duties: the adjudicator who initiates an adverse action must never be the operator who issues the final notice, and the system enforces that split structurally rather than by policy memo.

The API is built around a flat topology of peer resources — vendors, accuracy audits, packages, jurisdiction rules, adjudication matrices, positions, candidates, screening orders, consent records, reports with findings, individualized assessments, adverse-action cases, and disputes — joined by foreign-key references rather than deep URL nesting. Every mutation is atomically visible in the response that performs it. All time-derived rules (SLA deadlines, consent freshness windows, dispute windows, adverse-action waiting periods) read a single logical clock; wall-clock time is never consulted.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, envelope formats, and cross-cutting concerns that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. A request missing either header, or carrying an unrecognized role name, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes seven roles, spelled exactly as follows:

- `HRAdmin` — the HR program administrator; configures vendors, screening packages, positions, and the candidate registry, and may escalate overdue orders.
- `HiringManager` — the requisition-side owner of the screening workflow; creates, dispatches, cancels, and escalates orders, but never adjudicates.
- `Candidate` — the screened individual.
- `VendorAgent` — a screening vendor's operations agent.
- `Adjudicator` — the adjudication reviewer; evaluates reports, records individualized assessments, and initiates adverse action, but may never issue the final adverse-action notice.
- `ComplianceOfficer` — the compliance owner; authors jurisdiction rules and adjudication matrices, suspends and reinstates vendors, and issues final adverse-action notices.
- `Auditor` — the independent accuracy auditor; opens and finalizes vendor accuracy audits and holds no other write power.

Two roles are **entity-backed**: when `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate` record, and any ownership check on a resource that references a candidate (an order, a consent record, a dispute, a withdrawal) compares the resource's candidate foreign key to `X-User-ID`. When `X-User-Role` is `VendorAgent`, `X-User-ID` is the `id` of the acting `ScreeningVendor`, and ownership checks on reports and disputes compare the resource's vendor foreign key to `X-User-ID`. The remaining five roles — `HRAdmin`, `HiringManager`, `Adjudicator`, `ComplianceOfficer`, and `Auditor` — carry an **opaque** `X-User-ID`: an operator identifier not tied to any persisted entity. The server may record it (for example, as `captured_by_user_id` on a consent record, `adjudicator_user_id` on an individualized assessment, `adverse_initiated_by_user_id` on an order, `initiated_by_user_id` or `final_notice_issuer_user_id` on an adverse-action case) but never compares it to any entity's `id` for these roles.

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

List endpoints accept two query parameters: `limit`, the maximum number of items returned, defaulting to 10 with a minimum of 1 and a maximum of 100; and `offset`, the number of items skipped, defaulting to 0. Out-of-range values are clamped into range rather than rejected, and a non-integer value falls back to its default. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` ascending, with ties broken by creation order. The `meta` envelope of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. The Logical Clock and Business-Time Arithmetic

The platform never reads wall-clock time. All timestamps that drive compliance rules — consent freshness, SLA due instants, dispute windows, adverse-action waiting periods — read a single logical clock. That clock is set through a test-driving capability, restricted to `HRAdmin` and `ComplianceOfficer`, which accepts a `to_iso8601` instant and sets the clock to that instant unconditionally — including to an earlier time — returning `200 OK` with a `data` object carrying `current_utc`, the new logical time; the startup default, before any such call, is exactly `2026-08-01T00:00:00Z`.

Two time conventions pervade every calculation. A **business day** is Monday through Friday in UTC, with no holiday calendar. A **business window** on each business day runs from 09:00:00Z to 17:00:00Z — eight business hours per business day. Elapsed-time questions ("how long did this report take?") are answered by summing the overlap of the elapsed interval with those business windows across every UTC calendar day from the start date through the end date inclusive, and the result is expressed in hours rounded to two decimal places, round half up. Deadline-projection questions ("when is this SLA due?") are answered by walking forward day by day from a starting instant, consuming business-window hours and skipping weekends and non-window hours, until the contracted number of business hours has elapsed; a dispatch on a Saturday begins counting at 09:00:00Z the following Monday.

A separate date-granularity operation adds a count of business days to a starting timestamp: the send day itself is excluded from the count, each subsequent Monday-through-Friday day increments the counter, and the result is pinned to 00:00:00Z on the Nth following business day.

### 2.5. Common Resource Properties

Every primary resource carries a system-managed `id` — a server-minted UUID with no type prefix — plus `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits, and an integer `version` — starting at 1 at creation — that increments by one on every mutation of the resource. Any change to a resource, including computed-field refreshes driven by cascades, counts as a mutation for `updated_at` and `version` purposes. All fourteen top-level entity types in this domain — vendors, audits, packages, jurisdiction rules, matrices, positions, candidates, orders, consent records, reports, findings, assessments, adverse-action cases, and disputes — carry the full common-field set; none are exempt.

### 2.6. Monetary Values, Precision, and Rounding

All monetary quantities are integer cents (`fee_cents`, `surcharge_cents`, `provisional_fee_cents`, `final_fee_cents`, `annual_salary_cents`, `lookback_exemption_salary_cents`). The single fractional-money operation in the system — the 10% SLA credit subtracted from a provisional fee — computes the credit by integer floor before subtraction, so no fractional cents ever arise. Turnaround times are the only non-integer computed quantity and are rounded half-up to two decimal places, serialized as JSON numbers. Vendor accuracy is expressed as integer basis points with a single round-half-up applied after pooling; intermediate rounding of per-audit values before pooling is forbidden because it produces different results.

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control. Updating a `DRAFT` screening package requires the request body to carry `expected_package_version`, holding the package `version` the client last observed; if the package's current `version` has advanced since that observation, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's edits to fee, turnaround, or check list were computed against a stale package definition and the server refuses to silently overwrite the newer state. Patching a `DRAFT` jurisdiction rule requires `expected_jurisdiction_rule_version` under the same rule: a mismatch against the rule's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), since lookback or wait-day edits against a stale rule would silently drop an intervening compliance change. A successful OCC-guarded write increments the resource's `version` by one. No other endpoint takes a version field.

### 2.8. Validation Ordering and Left-to-Right Existence Checks

Every request passes through a fixed pipeline of validation categories, evaluated in this order. First, authentication: the two headers must be present and the role recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, authorization: the role must be permitted for the endpoint, and entity-backed ownership — candidate-as-self, vendor-as-self — must hold (`ERR_FORBIDDEN`). Third, existence: every resource id appearing in the path or body must resolve, checked left-to-right, with the first unresolvable id producing `ERR_NOT_FOUND` (HTTP 404). Fourth, concurrency: on the two OCC-guarded writes, the expected version must match (`ERR_STALE_VERSION`). Fifth, request shape: required fields present, enum members valid, and structural constraints such as `mismatches_found` not exceeding `sample_size`, `period_end` strictly after `period_start`, a non-empty `check_types` array, non-empty `corrected_findings` when an outcome of `AMENDED` is supplied, and candidate `email` uniqueness — all rejected as `ERR_INVALID_REQUEST` (HTTP 400). A malformed or absent JSON body is treated as an empty object for shape-validation purposes, while a body that parses to a non-object JSON value is itself a shape error. Sixth, state preconditions: the target entity must be in the state the operation requires, rejected with the appropriate `ERR_*_NOT_*` error (HTTP 409). Seventh, business-safety rules (ban-the-box gating, standalone disclosure, consent-not-in-future, credit-check prohibition, segregation of duties, adverse-path gating, individualized-assessment requirement) in their own pinned relative order detailed in §3. Eighth, uniqueness and referential constraints. Ninth, temporal rules. Tenth, fiscal constraints such as vendor capacity and vendor active status.

Where several endpoints nest beneath a parent resource — consent records and individualized assessments beneath an order, findings beneath a report — the parent's id is validated before any child id, so a request against a non-existent parent yields `ERR_NOT_FOUND` for the parent before the child is even located.

### 2.9. Parallel State Dimensions and Hierarchical Cascades

A screening order carries two independent status dimensions: `fulfillment_status` (`DRAFT`, `CONSENT_CAPTURED`, `DISPATCHED`, `REPORT_RECEIVED`, `CLOSED`, `CANCELLED`) and `adjudication_status` (`NOT_STARTED`, `PENDING_REVIEW`, `CLEARED`, `PRE_ADVERSE_PENDING`, `FINAL_ADVERSE`, `DISPUTE_HOLD`, `VOIDED`). The two evolve in parallel: a candidate dispute moves only `adjudication_status` to `DISPUTE_HOLD` while fulfillment stays at `REPORT_RECEIVED`. Cascades flow downward from order-level events: cancelling an order aborts any non-terminal adverse-action case, voids any decided individualized assessment, and — when the order was `DISPATCHED` — decrements the vendor's `active_order_count` and voids the provisional fee. The same compensation chain fires when consent is revoked, when a candidate withdraws, and when a vendor is decertified, guaranteeing that the vendor's `active_order_count` invariant — at all times equal to the count of that vendor's orders with `fulfillment_status` `DISPATCHED` — holds after every mutation.

## 3. Business Logic & Workflows

### 3.1. Configuring the Screening Catalog: Vendors, Packages, Rules, and Matrices

Before any order can flow, an `HRAdmin` registers at least one screening vendor by supplying the vendor's legal `name`, its contracted `base_tat_business_hours` (informational turnaround in business hours; any integer is accepted, with no minimum enforced), a `max_concurrent_orders` capacity cap of at least one, and an optional per-order `surcharge_cents` defaulting to zero (likewise any integer). A new vendor begins `ACTIVE` with `active_order_count` and `consecutive_sla_breaches` at zero and both accuracy measures — `accuracy_bps_finalized` and `accuracy_bps_including_draft` — at 10000 basis points, representing perfect accuracy in the absence of audit evidence.

The same administrator authors screening packages. Each package has a `name`, a `risk_tier` of `TIER_1_STANDARD`, `TIER_2_ELEVATED`, or `TIER_3_HIGH_RISK`, a non-empty `check_types` array drawn from `CRIMINAL_COUNTY`, `CRIMINAL_STATE`, `CRIMINAL_FEDERAL`, `SSN_TRACE`, `EMPLOYMENT_VERIFY`, `EDUCATION_VERIFY`, `MVR`, `CREDIT_CHECK`, and `GLOBAL_SANCTIONS`, a `tat_business_hours` SLA baseline of at least one business hour, and a non-negative `fee_cents` vendor charge per order. Packages are born `DRAFT`; activation moves one to `ACTIVE` (attempting to activate a non-draft package is rejected with `ERR_PACKAGE_NOT_DRAFT`), and only an `ACTIVE` package may be referenced by a position. While a package remains `DRAFT`, the administrator may revise its `name`, `check_types`, `tat_business_hours`, or `fee_cents` through the OCC-guarded update described in §2.7; the update applies only the fields present in the request body, leaving omitted fields unchanged. Retirement moves an `ACTIVE` package to `RETIRED`, but only when no non-terminal order references it — neither directly through a position still pointing at the package nor through a pinned snapshot; any such reference blocks retirement with `ERR_PACKAGE_IN_USE`, and attempting to retire a package that is not `ACTIVE` is rejected with `ERR_PACKAGE_NOT_ACTIVE`.

Compliance geography is owned by the `ComplianceOfficer` through jurisdiction rules. A rule carries a `jurisdiction_code` such as US-CA or US-NY-NYC; a `screening_gate_stage` of `POST_CONDITIONAL_OFFER` (the ban-the-box pattern) or `ANYTIME`; a non-negative `lookback_years_limit` defining how far back convictions count; an `arrest_records_considerable` boolean; a `lookback_exemption_salary_cents` threshold defaulting to zero, where a positive value exempts positions whose salary meets or exceeds it from the lookback limit; a non-negative `pre_adverse_wait_business_days` jurisdictional floor on the adverse-action waiting period; an `individualized_assessment_required` flag; and a `credit_check_allowed` flag. Rules are born `DRAFT` and are patched, while still draft, through the OCC-guarded patch carrying `expected_jurisdiction_rule_version`; the patch may revise any rule field except `jurisdiction_code` and applies only the fields present in the body, leaving omitted fields unchanged. Activation requires `DRAFT` status (otherwise `ERR_RULE_NOT_DRAFT`) and enforces one `ACTIVE` rule per `jurisdiction_code`: if another rule with the same code is already active, activation is rejected with `ERR_JURISDICTION_RULE_ALREADY_ACTIVE`.

Adjudication matrices, also authored by the `ComplianceOfficer`, translate report findings into recommended outcomes. A matrix is scoped to a single `risk_tier` and holds an ordered `rules` array of at least one entry; each entry pairs an `offense_category` with a `min_severity` of `LOW`, `MEDIUM`, or `HIGH`, a non-negative `max_recency_years` integer, and an `action` of `CLEAR`, `IA_REQUIRED`, or `ADVERSE_ELIGIBLE`. Rules are evaluated first-match-wins in declared array order, so array order is significant. A matrix is born `DRAFT`; activation requires `DRAFT` (`ERR_MATRIX_NOT_DRAFT`) and rejects when another matrix is already `ACTIVE` for the same tier (`ERR_MATRIX_ALREADY_ACTIVE`). Retirement moves an `ACTIVE` matrix to `RETIRED` (a non-active matrix rejects with `ERR_MATRIX_NOT_ACTIVE`) without disturbing any order that already pinned it — pinned evaluations survive retirement — but future report deliveries for that tier will then fail for lack of an active matrix: any report delivery for a position whose risk tier has no `ACTIVE` matrix is rejected with `ERR_MATRIX_NOT_ACTIVE` (HTTP 409).

### 3.2. Positions, Candidates, and Opening an Order

A position binds the catalog together. An `HRAdmin` creates one with a `title`, a `department`, a `risk_tier`, a `package_id` referencing an existing package, a `jurisdiction_code` naming the work-location jurisdiction, and a non-negative `annual_salary_cents` that will later be compared against the jurisdiction's lookback exemption. Creation enforces three referential guards: the package must exist (missing references produce `ERR_NOT_FOUND`); the package must be `ACTIVE`, else `ERR_PACKAGE_NOT_ACTIVE`; and an `ACTIVE` jurisdiction rule must exist for the supplied code, else `ERR_JURISDICTION_RULE_NOT_ACTIVE`. A fourth, safety-shaped guard fires when the jurisdiction rule has `credit_check_allowed` set false: any referenced package whose `check_types` contains `CREDIT_CHECK` is rejected with `ERR_CREDIT_CHECK_PROHIBITED` (HTTP 422).

Candidates enter the system through the `HRAdmin` as well, with a `full_name`, an `email` unique across all candidates (duplicates are rejected with `ERR_INVALID_REQUEST`), and an informational `home_jurisdiction_code` — screening law follows the position's jurisdiction, not the candidate's residence. A candidate is `ACTIVE` at registration and remains so until the candidate personally withdraws.

A `HiringManager` opens a screening order by supplying a `candidate_id` and a `position_id`. The candidate must be `ACTIVE` (`ERR_CANDIDATE_NOT_ACTIVE`) and the position must exist (`ERR_NOT_FOUND`). Uniqueness constrains the pair: at most one non-terminal `INITIAL` order may exist per (candidate, position) combination; a duplicate is rejected with `ERR_DUPLICATE_ACTIVE_ORDER`. The ban-the-box gate runs here, before any consent exists: when the position's active jurisdiction rule declares `screening_gate_stage` of `POST_CONDITIONAL_OFFER`, the request must carry `conditional_offer_extended_at` and that timestamp must not be in the future; a missing or future-dated value is rejected with `ERR_BAN_THE_BOX_GATE` (HTTP 403). When the rule declares `ANYTIME`, the field is not required. The creation gates are evaluated in this pinned order: id existence (`candidate_id`, then `position_id`), the ban-the-box gate, the duplicate-order uniqueness check, and finally the candidate-`ACTIVE` check. A new order begins with `fulfillment_status` `DRAFT` and `adjudication_status` `NOT_STARTED`, its `order_type` set to `INITIAL`, and its `rescreen_of_order_id`, `vendor_id`, `dispatched_at`, `sla_due_at`, fee fields, and pinned snapshots all null; `escalation_level` starts at zero.

### 3.3. Consent Capture: The Standalone-Disclosure Gate

Only the candidate may capture consent, and only for their own order: the acting candidate's identity must equal the order's `candidate_id`, otherwise `ERR_FORBIDDEN`. The capture payload carries the `disclosure_form_id` of the standalone disclosure document presented, a `contains_extraneous_terms` boolean, and the `authorization_signed_at` instant at which the candidate signed. Two FCRA-shaped safety checks guard capture, evaluated after state checks: `contains_extraneous_terms` must be false — a disclosure bundled with liability waivers or other terms violates the standalone-document requirement and is rejected with `ERR_DISCLOSURE_NOT_STANDALONE` (HTTP 422) — and `authorization_signed_at` must not lie in the future of the logical clock, else `ERR_CONSENT_IN_FUTURE` (HTTP 422). Capture requires the order's fulfillment to be `DRAFT`, or — one recovery path — `CONSENT_CAPTURED` whose latest consent has already flipped to `EXPIRED`; any other state is rejected with `ERR_ORDER_NOT_OPEN`.

A successful capture creates a `ConsentRecord` in `CAPTURED` status, stamps `captured_by_user_id` with the acting candidate's identity, links the record to its order through `order_id`, and advances the order's fulfillment from `DRAFT` to `CONSENT_CAPTURED`. Consent freshness is measured from `authorization_signed_at`: a consent remains fresh for ninety days after that instant. The candidate may revoke a `CAPTURED` consent at any time through the revocation capability; revoking a consent not in `CAPTURED` status is rejected with `ERR_CONSENT_NOT_ACTIVE`, and the same candidate-ownership check applies. Revocation cascades exactly like an order cancellation, described in §3.8.

### 3.4. Dispatch, the SLA Clock, and Vendor Capacity

Dispatch is the `HiringManager`'s act of committing an order to a vendor, and it is the system's most heavily gated transition. The order's fulfillment must be `CONSENT_CAPTURED`, else `ERR_ORDER_NOT_CONSENT_CAPTURED`. The body carries a `vendor_id` that must reference an existing vendor (`ERR_NOT_FOUND`) whose status is `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`) and whose `active_order_count` is strictly below its `max_concurrent_orders` (`ERR_VENDOR_CAPACITY_EXCEEDED`). The position's package must still be `ACTIVE` at dispatch time (`ERR_PACKAGE_NOT_ACTIVE`).

Consent freshness is checked at dispatch, not at capture: for an `INITIAL` order, the order's latest consent record must be `CAPTURED` with the current logical time no later than ninety days after `authorization_signed_at`. A stale consent flips to `EXPIRED` as a side effect of the check itself, and the dispatch is rejected with `ERR_CONSENT_EXPIRED`; the order remains `CONSENT_CAPTURED` and may capture a fresh consent. For a `RESCREEN` order, no new consent record is ever created — consent is inherited — and the freshness check instead runs against the original order's latest consent, reached through the rescreening order's `rescreen_of_order_id`. Rescreening orders carry one further guard: the target vendor must differ from the original order's vendor, because sending the re-screen back to the audited vendor defeats the audit's purpose; violations are rejected with `ERR_RESCREEN_SAME_VENDOR` (HTTP 422). The dispatch gates are evaluated in this pinned order: fulfillment `CONSENT_CAPTURED`; the rescreen same-vendor guard; consent freshness; the package-still-`ACTIVE` check; vendor capacity; and finally vendor `ACTIVE` status.

A successful dispatch stamps `dispatched_at` with the current logical time, computes `sla_due_at` by walking forward from the dispatch instant through business windows until the package's `tat_business_hours` have elapsed, snapshots `pinned_package_id` and `pinned_package_version` from the position's package, freezes `provisional_fee_cents` as the package's `fee_cents` plus the vendor's `surcharge_cents`, sets the order's `vendor_id`, and increments the vendor's `active_order_count` by one. Fulfillment becomes `DISPATCHED`. From dispatch until delivery, reads of the order expose the provisional fee; no SLA credit can be known yet.

When a dispatched order runs past its `sla_due_at`, the `HiringManager` or an `HRAdmin` may escalate it. Escalating an order whose fulfillment is not `DISPATCHED` is rejected with `ERR_ORDER_NOT_DISPATCHED`, a state check evaluated before the temporal gate. Escalation requires the current logical time to be strictly later than `sla_due_at`; an attempt before or exactly at the due instant is rejected with `ERR_SLA_NOT_BREACHED`. Each successful escalation increments `escalation_level` by one.

### 3.5. Report Delivery: SLA Accounting, Considerability, and the Adjudication Recommendation

Only the vendor assigned to an order may deliver its report: the acting `VendorAgent`'s identity must equal the order's `vendor_id`, else `ERR_FORBIDDEN`, and the order's fulfillment must be `DISPATCHED`, else `ERR_ORDER_NOT_DISPATCHED`. The submission payload carries the `order_id` and a `findings` array, which may be empty; every finding's `check_type` must be a member of the pinned package's `check_types`, and any out-of-package finding rejects the whole submission with `ERR_FINDING_CHECK_TYPE_NOT_IN_PACKAGE` (HTTP 422). Each finding also carries an `offense_category` — one of `VIOLENT_FELONY`, `NONVIOLENT_FELONY`, `MISDEMEANOR`, `INFRACTION`, `ARREST_NO_CONVICTION`, `EMPLOYMENT_DISCREPANCY`, `EDUCATION_DISCREPANCY`, or `SANCTIONS_HIT` — a `severity` of `LOW`, `MEDIUM`, or `HIGH`, an `offense_date` whose time component is ignored (treated as midnight UTC), and a `disposition` of `CONVICTION`, `DISMISSED`, `PENDING`, or `ARREST_ONLY`.

Delivery computes several things at once. The report is created in `DELIVERED` status with `delivered_at` stamped from the logical clock and `vendor_id` copied from the order. Every finding row carries its parent linkage through `report_id`. `turnaround_business_hours` is the business-window overlap between `dispatched_at` and `delivered_at`, rounded half-up to two decimals. `sla_breached` is true exactly when the turnaround is strictly greater than the package's `tat_business_hours` — delivery at exactly the due boundary is on time. The vendor's `active_order_count` decrements by one. A breached SLA increments `consecutive_sla_breaches`; an on-time delivery resets the counter to zero; and when the counter reaches three on an `ACTIVE` vendor, the vendor automatically transitions to `PROBATION` — the third consecutive breach is the boundary.

Fees finalize at delivery into `final_fee_cents`. For a `RESCREEN` order the final fee is zero — the employer does not pay the new vendor through this order for an audit-mandated re-screen. For an `INITIAL` order delivered in breach, the final fee is the provisional fee minus a ten-percent SLA credit, the credit computed by integer floor of one-tenth of the provisional amount, with the result floored at zero; an on-time delivery simply carries the provisional amount forward. The provisional fee remains visible for the in-flight window between dispatch and delivery and persists on the order after delivery alongside `final_fee_cents`.

Each finding's `considerable` flag and `matched_action` are computed against the position's active jurisdiction rule and the active matrix for the position's risk tier. Considerability excludes two classes of finding: any finding with `disposition` `ARREST_ONLY` when the jurisdiction has `arrest_records_considerable` set false, and any `CONVICTION` whose `offense_date` falls strictly before the lookback cutoff — the date of delivery minus the jurisdiction's `lookback_years_limit`, computed by calendar anniversary (a February 29 date clamping to February 28) — unless the salary exemption applies (the jurisdiction's `lookback_exemption_salary_cents` is positive and the position's `annual_salary_cents` meets or exceeds it). A conviction dated exactly on the cutoff remains considerable; the comparison is strictly-before. All other findings are considerable.

For each considerable finding, the matrix's ordered rules are scanned in declared array order and the first rule whose `offense_category` equals the finding's, whose `min_severity` is at or below the finding's severity on the `LOW` < `MEDIUM` < `HIGH` scale, and whose `max_recency_years` is at least the finding's recency — full calendar years between the offense date and the delivery date by the anniversary method — supplies the finding's `matched_action`. A finding that matches no rule defaults its `matched_action` to `CLEAR`, as does any non-considerable finding. The order's `recommended_outcome` is the worst `matched_action` across considerable findings, with `ADVERSE_ELIGIBLE` outranking `IA_REQUIRED` outranking `CLEAR`; an order whose considerable set is empty recommends `CLEAR`. Delivery also pins `pinned_matrix_id` and `pinned_matrix_version` from the active matrix at that instant — a snapshot that every later re-evaluation reuses even if the matrix is subsequently retired — and advances fulfillment to `REPORT_RECEIVED` while adjudication moves from `NOT_STARTED` to `PENDING_REVIEW`.

### 3.6. Adjudication: Individualized Assessment and the Adverse-Action Decision

With a report delivered, an `Adjudicator` may record an individualized assessment on an order whose adjudication is `PENDING_REVIEW` (any other state rejects with `ERR_ORDER_ADJUDICATION_NOT_REVIEWABLE`). The assessment captures the three EEOC Green factors as `green_factor_nature_gravity`, `green_factor_time_elapsed`, and `green_factor_job_relatedness` — each `LOW`, `MODERATE`, or `HIGH` — an `evidence_considered` boolean recording whether candidate-submitted evidence was weighed, and a `decision` of `PROCEED_ADVERSE` or `CLEAR_CANDIDATE`. The record is born `DECIDED` and stamps `adjudicator_user_id` with the acting adjudicator's identity. A `CLEAR_CANDIDATE` decision immediately moves the order's adjudication to `CLEARED` and its fulfillment to `CLOSED`; a `PROCEED_ADVERSE` decision leaves adjudication in `PENDING_REVIEW`, arming the subsequent adverse-action decision without itself advancing the order.

The adjudication decision itself is also the `Adjudicator`'s act and likewise requires adjudication `PENDING_REVIEW`. Two decisions exist. `CLEAR_CANDIDATE` closes the order: adjudication becomes `CLEARED`, fulfillment becomes `CLOSED`. `INITIATE_ADVERSE` moves adjudication to `PRE_ADVERSE_PENDING` and is gated by two safety checks applied in order. First, the order's `recommended_outcome` must not be `CLEAR` — initiating adverse action against a clean recommendation is rejected with `ERR_ADVERSE_NOT_RECOMMENDED` (HTTP 409). Second, whenever `recommended_outcome` is `IA_REQUIRED` or the jurisdiction's `individualized_assessment_required` flag is true, a decided individualized assessment with decision `PROCEED_ADVERSE` must already exist on the order; its absence is rejected with `ERR_IA_REQUIRED` (HTTP 409).

A successful `INITIATE_ADVERSE` stamps `adverse_initiated_by_user_id` with the acting adjudicator's identity and atomically creates the one-to-one `AdverseActionCase`. The pre-adverse notice is sent as part of the same atomic act: `pre_notice_sent_at` is stamped with the current logical time, `wait_business_days_required` is set to the greater of five business days — the FCRA baseline — and the jurisdiction's `pre_adverse_wait_business_days`, `total_hold_business_days` starts at zero, and `earliest_final_notice_at` is computed by adding the required wait to the pre-notice date under business-day arithmetic: the send day is excluded from the count, and the result is pinned to 00:00:00Z on the Nth following business day. The case begins in `WAITING_PERIOD`; `hold_started_at`, `final_notice_sent_at`, and `final_notice_issuer_user_id` are null. For either adjudication decision, the endpoint's response carries the updated order.

### 3.7. The Adverse-Action Waiting Period and the Final Notice

The waiting-period case advances lazily: whenever the case is read or a transition is attempted and the current logical time has reached `earliest_final_notice_at`, the case moves from `WAITING_PERIOD` to `ELIGIBLE_FOR_FINAL`. Issuing the final notice is the `ComplianceOfficer`'s exclusive act, guarded by segregation of duties and by time — in that order. The segregation check runs first: the acting officer's identity must differ from the case's `initiated_by_user_id`, and a match is rejected with `ERR_SOD_ADVERSE_NOTICE_MISMATCH` (HTTP 403) regardless of how much time has passed. Only then does the temporal gate apply: the current logical time must be at or after `earliest_final_notice_at`, else `ERR_ADVERSE_WAIT_NOT_ELAPSED` (HTTP 409). A case not in `WAITING_PERIOD` or `ELIGIBLE_FOR_FINAL` rejects both operations with `ERR_CASE_NOT_AWAITING_FINAL`.

A successful final notice stamps `final_notice_sent_at` and `final_notice_issuer_user_id`, moves the case to `FINAL_NOTICE_SENT`, and cascades to the order: adjudication becomes `FINAL_ADVERSE`, fulfillment becomes `CLOSED`. The same segregation-of-duties reference that gates the notice — `initiated_by_user_id` on the case, mirroring `adverse_initiated_by_user_id` on the order — is what structurally prevents the initiating adjudicator from completing the action they started.

A waiting case may also be aborted manually by a `ComplianceOfficer` while in `WAITING_PERIOD` or `ELIGIBLE_FOR_FINAL` (otherwise `ERR_CASE_NOT_AWAITING_FINAL`), which moves the case to `ABORTED` (clearing any `hold_started_at` to null) and returns the order's adjudication from `PRE_ADVERSE_PENDING` to `PENDING_REVIEW`.

### 3.8. Cancellation, Revocation, and Withdrawal Cascades

A `HiringManager` may cancel an order while its fulfillment is `DRAFT`, `CONSENT_CAPTURED`, or `DISPATCHED`; any other state rejects with `ERR_ORDER_NOT_CANCELLABLE`. Cancellation is a compensated event. If the order was `DISPATCHED`, the vendor's `active_order_count` decrements by one and `provisional_fee_cents` is voided to null. In all cases, a non-terminal adverse-action case cascades to `ABORTED`, a `DECIDED` individualized assessment cascades to `VOID`, and the order's adjudication becomes `VOIDED` while fulfillment becomes `CANCELLED`.

The identical compensation chain fires through two other doors. When a candidate revokes their consent — moving the consent record from `CAPTURED` to `REVOKED` — the parent order is cancelled with the full chain: capacity released if dispatched, provisional fee voided, case aborted, assessment voided, adjudication `VOIDED`. And when a candidate withdraws from the process entirely — requiring the candidate to be `ACTIVE`, else `ERR_CANDIDATE_NOT_ACTIVE`, and the acting identity to be the candidate themself — the candidate's status becomes `WITHDRAWN` and every non-terminal order they hold (any fulfillment other than `CLOSED` or `CANCELLED`, including `REPORT_RECEIVED`) is cancelled with the same compensation.

### 3.9. Disputes and Re-Investigation

A candidate who believes a report is inaccurate may file a dispute, acting only on their own order (`ERR_FORBIDDEN`). Filing requires an existing report in `DELIVERED` or `AMENDED` status for the order — otherwise `ERR_REPORT_NOT_ACTIONABLE` — and the order's adjudication must be `PENDING_REVIEW` or `PRE_ADVERSE_PENDING`, else `ERR_ORDER_ADJUDICATION_TERMINAL`. Only one open dispute per order is permitted: the uniqueness rule rejects a filing that would leave a second `UNDER_REINVESTIGATION` dispute on the same order with `ERR_DISPUTE_ALREADY_OPEN`. That uniqueness rule is evaluated after the state preconditions above, per the §2.8 pipeline, and within those state preconditions the report-actionability check runs before the adjudication-state check; because an open dispute has already moved the report to `DISPUTED` and the order's adjudication to `DISPUTE_HOLD`, a second filing while one is `UNDER_REINVESTIGATION` fails the report-actionability precondition first and is rejected with `ERR_REPORT_NOT_ACTIONABLE`. The dispute window is thirty calendar days: filing is permitted only while the current logical time is no later than `delivered_at` plus thirty days, else `ERR_DISPUTE_WINDOW_CLOSED`. The payload carries the `order_id`, a free-text `reason` of at least ten characters, and an optional `finding_ids` list identifying the contested findings — each supplied id must reference an existing finding, checked left-to-right (else `ERR_NOT_FOUND`), though membership of those findings in the order's own report is not verified; an absent or empty list disputes the whole report, and an absent list is stored as null.

Filing creates the dispute in `UNDER_REINVESTIGATION` with `filed_at` stamped, `candidate_id` copied from the order, `resolved_at` and `outcome` null, and `overdue` false, moves the report to `DISPUTED`, and moves the order's adjudication to `DISPUTE_HOLD` while fulfillment stays unchanged at `REPORT_RECEIVED`. If an adverse-action case exists in `WAITING_PERIOD` or `ELIGIBLE_FOR_FINAL`, it moves to `DISPUTE_HOLD` with `hold_started_at` stamped — the waiting period freezes.

Re-investigation concludes in one of three ways. The assigned vendor — the acting `VendorAgent`'s identity must equal the report's `vendor_id` — may resolve the dispute as `UPHELD`, requiring the dispute to be `UNDER_REINVESTIGATION` (else `ERR_DISPUTE_NOT_OPEN`). Upholding returns the report from `DISPUTED` to `UPHELD`, returns the order's adjudication from `DISPUTE_HOLD` to `PENDING_REVIEW`, stamps the dispute's `resolved_at`, and — if a case was on hold — moves it back to `WAITING_PERIOD` while extending the deadline: the business days spanned by the hold, counting from the day after the hold-start date through the resolution date inclusive, are added into `total_hold_business_days`, `hold_started_at` clears to null, and `earliest_final_notice_at` is recomputed from `pre_notice_sent_at` using the required wait plus the accumulated hold days. The evaluation order is pinned: hold days are computed from stored timestamps first, added to the base wait, and only then is the deadline recomputed — compositionally equivalent to shifting the prior deadline by the hold's length.

Alternatively the vendor may resolve as `AMENDED`, which additionally requires a non-empty `corrected_findings` payload (empty or absent rejects with `ERR_INVALID_REQUEST`). Amendment replaces the report's findings with the corrected set — each validated for shape only, with no re-check of `check_type` membership against the pinned package — and re-computes every finding's `considerable` flag and `matched_action` against the currently active jurisdiction rule but — critically — against the order's pinned matrix, the `pinned_matrix_id` and `pinned_matrix_version` frozen at delivery, even if that matrix has since been retired, using the report's original `delivered_at` as the delivery date for lookback-cutoff and recency arithmetic; the order's `recommended_outcome` is re-derived from the amended findings under the same worst-of precedence. The report becomes `AMENDED`, and because the evidentiary basis has changed, any held adverse-action case cascades to `ABORTED` — the pre-adverse process must restart on the amended report — while the order's adjudication returns to `PENDING_REVIEW`.

Finally, the filing candidate may withdraw the dispute (ownership-checked; a non-open dispute rejects with `ERR_DISPUTE_NOT_OPEN`). Withdrawal moves the dispute to `WITHDRAWN`, returns the report from `DISPUTED` to `DELIVERED`, returns adjudication to `PENDING_REVIEW`, and applies the same hold-extension arithmetic to a held case as an upheld resolution does. In every resolution path, `resolved_at` is stamped and the dispute's `overdue` flag is computed: true when `resolved_at` falls later than thirty calendar days after `filed_at` — late re-investigation is permitted but flagged. The dispute's `outcome` records `UPHELD` or `AMENDED` and remains null until resolution — a withdrawal records no outcome, so it stays null — while the dispute's own status lands in the corresponding terminal state: `RESOLVED_UPHELD` after an upheld re-investigation, `RESOLVED_AMENDED` after an amended one, and `WITHDRAWN` after candidate withdrawal. An amended report may be disputed once more: the report state machine permits `AMENDED` back to `DISPUTED` on a fresh filing.

### 3.10. Vendor Lifecycle: Suspension, Probation, and Decertification

A `ComplianceOfficer` may suspend an `ACTIVE` vendor (any other status rejects with `ERR_VENDOR_NOT_ACTIVE`). Suspension blocks new dispatches to the vendor but does not cancel in-flight `DISPATCHED` orders, which continue to completion. Reinstatement returns a `SUSPENDED` or `PROBATION` vendor to `ACTIVE` without resetting `consecutive_sla_breaches`; any other status rejects with `ERR_VENDOR_NOT_SUSPENDED_OR_PROBATION`.

Probation and decertification, by contrast, are system-driven. Two automatic triggers move an `ACTIVE` vendor to `PROBATION`: the third consecutive SLA breach described in §3.5, and finalization of an accuracy audit whose failure threshold is exceeded, described next. When a second failing audit is finalized against a vendor already on `PROBATION`, the vendor transitions to `DECERTIFIED` — terminal — and every order currently `DISPATCHED` to that vendor is cancelled with the standard compensation chain: capacity released, provisional fees voided, cases aborted, assessments voided.

### 3.11. Accuracy Audits and the Re-Screen Sweep

An `Auditor` opens an accuracy audit for a vendor by supplying `vendor_id`, a `period_start` (inclusive), a `period_end` (exclusive for overlap purposes), a `sample_size` of at least one, and a `mismatches_found` count that may not exceed the sample. At creation the audit's `mismatch_rate_bps` is computed: the mismatch count divided by the sample size, scaled by 10000 basis points, rounded half-up. The audit is born `DRAFT`. Two audits for the same vendor may not overlap: a new half-open interval intersects an existing one whenever the new start falls before the existing end and the new end falls after the existing start, and any such intersection is rejected with `ERR_AUDIT_PERIOD_OVERLAP` — pure adjacency, where one audit's end equals the next's start, is allowed.

Vendor accuracy is pooled, never averaged per-audit. Two variants are maintained on the vendor. The finalized variant, `accuracy_bps_finalized`, pools only `FINALIZED` audits; it is the default view and the only input to probation and decertification decisions. The provisional variant, `accuracy_bps_including_draft`, pools `DRAFT` and `FINALIZED` audits together and diverges from the finalized variant whenever a draft audit exists; opening a draft audit recomputes it. Both variants apply one formula: 10000 times one minus the ratio of summed `mismatches_found` to summed `sample_size` across the variant's audit set, rounded half-up exactly once after pooling; an empty set yields 10000.

Finalization, the `Auditor`'s second exclusive act, requires `DRAFT` status (else `ERR_AUDIT_NOT_DRAFT`) and moves the audit to `FINALIZED`. The finalized accuracy variant is recomputed to include the newly finalized evidence. Failure is strictly threshold-based: a `mismatch_rate_bps` strictly greater than 200 fails; exactly 200 passes. A failing audit against an `ACTIVE` vendor moves the vendor to `PROBATION`; against a `PROBATION` vendor, to `DECERTIFIED` with the in-flight cancellation cascade; a `SUSPENDED` vendor's status is unchanged by audit failure.

Every failing audit also triggers the re-screen sweep. The sweep selects every report by this vendor whose status is `DELIVERED`, whose `delivered_at` falls within the closed interval from `period_start` through `period_end` inclusive on both ends, whose order's fulfillment is `REPORT_RECEIVED`, and whose order's `recommended_outcome` is `IA_REQUIRED` or `ADVERSE_ELIGIBLE`. For each selected report, in order of `delivered_at` ascending with ties broken by report `created_at` ascending — never by id — the sweep creates a new screening order: `order_type` `RESCREEN`, `rescreen_of_order_id` pointing at the original order, `candidate_id`, `position_id`, and `conditional_offer_extended_at` copied, fulfillment starting at `CONSENT_CAPTURED` (consent is inherited from the original order; no new consent record exists), adjudication `NOT_STARTED`, and all dispatch, fee, and pinning fields null with `escalation_level` zero. The audit's `rescreen_order_ids` collects the created order ids in creation order, defaulting to an empty array when the sweep selects nothing or the audit passes.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or trigger a state transition return `200 OK`. Request and response bodies are as described in §3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z) | HRAdmin, ComplianceOfficer |
| POST | `/vendors` | Register a screening vendor | HRAdmin |
| GET | `/vendors/{id}` | Get a vendor with computed counters and both accuracy variants | Any role |
| POST | `/vendors/{id}/suspend` | Suspend a vendor (blocks new dispatch; in-flight orders continue) | ComplianceOfficer |
| POST | `/vendors/{id}/reinstate` | Reinstate a SUSPENDED or PROBATION vendor to ACTIVE | ComplianceOfficer |
| POST | `/vendor-accuracy-audits` | Open an accuracy audit (DRAFT) for a vendor over a half-open period | Auditor |
| GET | `/vendor-accuracy-audits` | List audits, filterable by `vendor_id` | Any role |
| GET | `/vendor-accuracy-audits/{id}` | Get one audit | Any role |
| POST | `/vendor-accuracy-audits/{id}/finalize` | Finalize an audit: recompute accuracy, apply probation/decertification, run the re-screen sweep | Auditor |
| POST | `/screening-packages` | Create a screening package (DRAFT) | HRAdmin |
| GET | `/screening-packages/{id}` | Get a package | Any role |
| PUT | `/screening-packages/{id}` | Update a DRAFT package (OCC-guarded via `expected_package_version`) | HRAdmin |
| POST | `/screening-packages/{id}/activate` | Activate a DRAFT package | HRAdmin |
| POST | `/screening-packages/{id}/retire` | Retire an ACTIVE package with no non-terminal order references | HRAdmin |
| POST | `/jurisdiction-rules` | Create a jurisdiction rule (DRAFT) | ComplianceOfficer |
| GET | `/jurisdiction-rules/{id}` | Get a jurisdiction rule | Any role |
| PATCH | `/jurisdiction-rules/{id}` | Patch a DRAFT rule (OCC-guarded via `expected_jurisdiction_rule_version`) | ComplianceOfficer |
| POST | `/jurisdiction-rules/{id}/activate` | Activate a DRAFT rule; one ACTIVE rule per jurisdiction code | ComplianceOfficer |
| POST | `/adjudication-matrices` | Create an adjudication matrix (DRAFT) for a risk tier | ComplianceOfficer |
| GET | `/adjudication-matrices/{id}` | Get a matrix | Any role |
| POST | `/adjudication-matrices/{id}/activate` | Activate a DRAFT matrix; one ACTIVE matrix per risk tier | ComplianceOfficer |
| POST | `/adjudication-matrices/{id}/retire` | Retire an ACTIVE matrix; pinned evaluations unaffected | ComplianceOfficer |
| POST | `/positions` | Create a position bound to an ACTIVE package and ACTIVE jurisdiction rule | HRAdmin |
| GET | `/positions` | List positions, filterable by `package_id` | Any role |
| GET | `/positions/{id}` | Get a position | Any role |
| POST | `/candidates` | Register a candidate | HRAdmin |
| GET | `/candidates/{id}` | Get a candidate | Any role |
| POST | `/candidates/{id}/withdraw` | Candidate withdraws; cascades cancellation of all non-terminal orders | Candidate |
| POST | `/screening-orders` | Create an INITIAL screening order (DRAFT); ban-the-box gate enforced | HiringManager |
| GET | `/screening-orders` | List orders with filters (`candidate_id`, `position_id`, `vendor_id`, `fulfillment_status`, `adjudication_status`, `rescreen_of_order_id`, `pinned_package_id`, `pinned_matrix_id`) | Any role |
| GET | `/screening-orders/{id}` | Get an order | Any role |
| POST | `/screening-orders/{id}/consents` | Capture candidate consent with standalone disclosure | Candidate |
| GET | `/screening-orders/{id}/consents` | List consent records of an order | Any role |
| POST | `/screening-orders/{id}/dispatch` | Dispatch the order to a vendor; starts the SLA clock and pins the package | HiringManager |
| POST | `/screening-orders/{id}/cancel` | Cancel a non-terminal order with full compensation | HiringManager |
| POST | `/screening-orders/{id}/escalate` | Escalate a dispatched order past its SLA due instant | HiringManager, HRAdmin |
| POST | `/screening-orders/{id}/individualized-assessments` | Record an individualized assessment (EEOC Green factors) | Adjudicator |
| GET | `/screening-orders/{id}/individualized-assessments` | List individualized assessments of an order | Any role |
| POST | `/screening-orders/{id}/adjudication-decision` | Record the adjudication decision (clear or initiate adverse action) | Adjudicator |
| POST | `/consents/{id}/revoke` | Candidate revokes consent; cascades full order cancellation | Candidate |
| POST | `/screening-reports` | Vendor delivers a report with findings; computes SLA, fees, considerability, recommended outcome | VendorAgent |
| GET | `/screening-reports` | List reports, filterable by `order_id` or `vendor_id` | Any role |
| GET | `/screening-reports/{id}` | Get a report | Any role |
| GET | `/screening-reports/{id}/findings` | List findings of a report (considerable + matched_action computed) | Any role |
| GET | `/adverse-action-cases` | List adverse action cases, filterable by `order_id` | Any role |
| GET | `/adverse-action-cases/{id}` | Get a case | Any role |
| POST | `/adverse-action-cases/{id}/send-final-notice` | Issue the final adverse notice after the waiting period; segregation of duties enforced | ComplianceOfficer |
| POST | `/adverse-action-cases/{id}/abort` | Abort a waiting case; returns the order to PENDING_REVIEW | ComplianceOfficer |
| POST | `/disputes` | Candidate disputes report accuracy; freezes adjudication and any adverse waiting period | Candidate |
| GET | `/disputes` | List disputes, filterable by `order_id`, `candidate_id`, `status` | Any role |
| GET | `/disputes/{id}` | Get a dispute | Any role |
| POST | `/disputes/{id}/resolve` | Vendor completes re-investigation: UPHELD resumes with extension; AMENDED replaces findings and aborts any case | VendorAgent |
| POST | `/disputes/{id}/withdraw` | Candidate withdraws the dispute; report returns to DELIVERED, case resumes with extension | Candidate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ORDER_NOT_OPEN` | 409 |
| `ERR_ORDER_NOT_CONSENT_CAPTURED` | 409 |
| `ERR_ORDER_NOT_DISPATCHED` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_ORDER_ADJUDICATION_NOT_REVIEWABLE` | 409 |
| `ERR_ORDER_ADJUDICATION_TERMINAL` | 409 |
| `ERR_PACKAGE_NOT_DRAFT` | 409 |
| `ERR_PACKAGE_NOT_ACTIVE` | 409 |
| `ERR_PACKAGE_IN_USE` | 409 |
| `ERR_RULE_NOT_DRAFT` | 409 |
| `ERR_JURISDICTION_RULE_ALREADY_ACTIVE` | 409 |
| `ERR_JURISDICTION_RULE_NOT_ACTIVE` | 409 |
| `ERR_MATRIX_NOT_DRAFT` | 409 |
| `ERR_MATRIX_ALREADY_ACTIVE` | 409 |
| `ERR_MATRIX_NOT_ACTIVE` | 409 |
| `ERR_AUDIT_NOT_DRAFT` | 409 |
| `ERR_AUDIT_PERIOD_OVERLAP` | 409 |
| `ERR_CASE_NOT_AWAITING_FINAL` | 409 |
| `ERR_DISPUTE_NOT_OPEN` | 409 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_CONSENT_NOT_ACTIVE` | 409 |
| `ERR_CANDIDATE_NOT_ACTIVE` | 409 |
| `ERR_VENDOR_NOT_ACTIVE` | 409 |
| `ERR_VENDOR_NOT_SUSPENDED_OR_PROBATION` | 409 |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 |
| `ERR_BAN_THE_BOX_GATE` | 403 |
| `ERR_DISCLOSURE_NOT_STANDALONE` | 422 |
| `ERR_CONSENT_IN_FUTURE` | 422 |
| `ERR_CREDIT_CHECK_PROHIBITED` | 422 |
| `ERR_SOD_ADVERSE_NOTICE_MISMATCH` | 403 |
| `ERR_ADVERSE_NOT_RECOMMENDED` | 409 |
| `ERR_IA_REQUIRED` | 409 |
| `ERR_CONSENT_EXPIRED` | 409 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 |
| `ERR_ADVERSE_WAIT_NOT_ELAPSED` | 409 |
| `ERR_SLA_NOT_BREACHED` | 409 |
| `ERR_RESCREEN_SAME_VENDOR` | 422 |
| `ERR_DUPLICATE_ACTIVE_ORDER` | 409 |
| `ERR_FINDING_CHECK_TYPE_NOT_IN_PACKAGE` | 422 |
| `ERR_REPORT_NOT_ACTIONABLE` | 409 |
