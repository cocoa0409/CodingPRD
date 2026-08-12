# Retirement Plan Loan & Hardship Withdrawal API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for a 401(k) recordkeeper's loan and hardship withdrawal processing API. Plan sponsors delegate to the recordkeeper the operational burden of two heavily regulated transaction families: participant loans, which must respect statutory borrowing ceilings, plan-level policy levers, level-payment amortization, and payroll-deduction repayment; and hardship withdrawals, which must satisfy a substantiation standard, mandatory withholding, post-distribution deferral suspensions, and multi-year documentation retention. Both families terminate in taxable events — deemed distributions, plan-loan offsets, and hardship distributions — that must be captured, accumulated per participant, and marked as reported on Form 1099-R.

The system is organized as a small set of interlocking obligations. Every plan carries its own loan and hardship policy, and every mutating operation is gated on the plan being in an operable posture. Approval authority follows per-plan, ordered approval chains with strict segregation of duties: no operator may decide two steps of the same subject, and no participant may decide a task on its own request. Repayment flows through a deterministic waterfall that allocates payroll remittances across installments in a pinned order, and every posting is reversible with exact restoration of prior state. A logical clock — never the wall clock — drives delinquency marking, cure-window expiry, deemed distributions, and suspension expiry, so that time-dependent compliance behavior is fully reproducible. Every mutation appends exactly one record to an append-only, plan-scoped audit trail.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `Participant`, `PlanSponsor`, `RecordkeeperAdmin`, `PayrollProvider`, and `Auditor`. A request with missing headers, or whose `X-User-Role` is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`. Access to specific operations is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_UNAUTHORIZED_ROLE`. A third authorization failure, `ERR_SEGREGATION_OF_DUTIES`, guards the approval pipeline and is described with the approval workflow in §3.4.

The five roles differ in how `X-User-ID` is interpreted. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a `Participant` compare the resource's participant foreign-key field — its `participant_id` — or the participant identifier in the path to `X-User-ID`, and a participant may act only on its own resources. When `X-User-Role` is `PlanSponsor`, `RecordkeeperAdmin`, `PayrollProvider`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `decided_by` on an `ApprovalTask` when a decision is rendered, and as `actor_id` on every `AuditEvent` — but does not compare it to any entity's `id` for ownership purposes.

`Participant` is the plan participant (employee) and may request loans, withdraw its own requests, upload hardship documents, manage its own deferral election, and read its own records. `PlanSponsor` is the employer plan administrator; it decides approval steps whose required role is `PLAN_SPONSOR` and manages plan posture. `RecordkeeperAdmin` is the recordkeeper operations administrator; it creates plans and participants, disburses and refinances loans, rebuilds schedules, reverses remittances, pays hardship distributions, marks tax events reported, drives the logical clock, and decides approval steps whose required role is `RECORDKEEPER_ADMIN`. `PayrollProvider` is the employer payroll integration that posts deduction remittances. `Auditor` is a read-only compliance auditor with no mutating operations.

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

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; resources sharing an identical creation timestamp retain the relative order in which they were created — the sort is stable and applies no secondary key such as `id`.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Primary resources — Plan, Participant, ContributionElection, Loan, PayrollRemittance, HardshipRequest, ApprovalTask, SuspensionRecord, and TaxEvent — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp recording the last modification; it refreshes on every change to the resource.
- `version` (integer): a system-managed integer that increments with every modification, serving as the basis for optimistic concurrency control.

Three resource kinds are narrower. A `LoanInstallment`, a `HardshipDocument`, and an `AuditEvent` each carry only `id` and `created_at`; both `updated_at` and `version` are absent on these resources, because installment rows are maintained by the server as schedule state, documents are immutable once uploaded, and audit events are never updated or deleted.

### 2.5. Monetary Representation, Interest Rates, and Rounding

All monetary amounts in the system are represented as integer cents — balances, principals, payments, fees, withholding, and taxable amounts alike. Interest rates and withholding rates are expressed in basis points: an `interest_rate_bps` of 500 denotes a five percent annual rate, and a `withholding_rate_bps` of 2000 denotes a twenty percent withholding rate. Wherever a calculation must round — the level payment of an amortization schedule, each installment's interest portion, a hardship gross-up, or its withholding — the result is rounded half up to a whole cent, and the rounding order pinned by each calculation in §3 is part of the contract. Date-valued quantities such as deadlines and suspension windows are computed at date granularity. Accordingly, the date stamps the server derives from the logical clock — `disbursed_on`, `deemed_on`, `cure_deadline_on`, `terminated_on`, `paid_on`, `starts_on`, `ends_on`, `retained_until`, `event_date`, installment `due_date`, `loan_eligibility_locked_until`, and the `current_utc` returned by the clock endpoint — are rendered as ISO 8601 UTC strings at whole-second precision, with no fractional digits (at the canonical midnight clock readings they appear as, for example, `2026-05-01T00:00:00Z`). The event timestamps `created_at`, `updated_at`, `decided_on`, `effective_on`, and the envelope's `api_request_timestamp` are rendered with three fractional digits.

### 2.6. The Logical Clock and Scheduled State Evaluation

The server maintains a logical clock that governs every time-dependent rule: due-date passage, cure-window expiry, suspension expiry, and the dating of system events. At startup the logical clock reads exactly `2026-05-01T00:00:00Z`; before any client sets it, every clock-dependent evaluation uses that default, and the server never falls back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock evaluates three families of scheduled transitions: installment `MISSED` marking and loan delinquency entry, cure-deadline expiry with its deemed-distribution cascade, and suspension-record `EXPIRED` transitions. System-assigned timestamps throughout this document — disbursement dates, termination defaults, decision timestamps, payment dates — are always read from this logical clock.

### 2.7. Plan Posture: The Active-Plan Gate

Every Plan carries a `status` of `ACTIVE`, `FROZEN`, or `TERMINATED`, beginning at `ACTIVE` upon creation. A `PlanSponsor` or `RecordkeeperAdmin` may freeze an `ACTIVE` plan, moving it to `FROZEN`, and may unfreeze a `FROZEN` plan back to `ACTIVE`; each posture change increments the plan's `version` by one and appends a `PLAN_FROZEN` or `PLAN_UNFROZEN` audit record. Plan termination is administrative and is not exposed as an endpoint in this version of the API; both `ACTIVE` and `FROZEN` plans may reach `TERMINATED` only through that administrative path.

Plan status is a posture gate: the plan must be `ACTIVE` for a loan request, disbursement, refinance, or schedule rebuild; for a remittance posting or reversal; for a hardship creation or payment; for an approval decision; and for an election restart. Against a `FROZEN` or `TERMINATED` plan, each of those operations is rejected with `ERR_PLAN_NOT_ACTIVE`.

### 2.8. The Validation Cascade

Every request is evaluated against a fixed cascade of check groups, applied in the priority order below; the first failing group determines the error response, and later groups are not consulted.

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is a declared role; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership.** The role is listed for the endpoint, and entity-backed ownership holds for the `Participant` role — `X-User-ID` must equal the participant id in the path or the `participant_id` of the target resource. Failures surface as `ERR_UNAUTHORIZED_ROLE`. The ownership comparison is evaluated when the target resource is loaded, so a request against a nonexistent target surfaces as the priority-5 not-found error rather than as an ownership failure.
3. **Segregation of duties.** On an approval decision, `X-User-ID` must differ from the `decided_by` of every other decided task on the same subject and from the subject's requesting participant id; otherwise `ERR_SEGREGATION_OF_DUTIES`.
4. **Request-body schema.** Required fields are present and types and enum members are valid — an unknown member of `reason_category`, `document_type`, `decision`, or any other enum field fails here — as does a `REQUEST_DOCS` decision on a `LOAN` subject; the error is `ERR_INVALID_REQUEST`.
5. **Path existence.** Path resources exist, validated left-to-right — plan, then participant, then loan, hardship request, remittance, task, or tax event — with the resource-specific not-found error named in §2.10.
6. **From-state validity.** The target resource is in a valid from-state for the requested transition. This group includes the specific rejections `ERR_TASK_ALREADY_DECIDED` (the task already stands `APPROVED`, `REJECTED`, or `CANCELLED`), `ERR_APPROVAL_OUT_OF_ORDER` (a lower-`step_order` task on the same subject is still `PENDING`), and `ERR_TAX_EVENT_ALREADY_REPORTED` (the tax event already stands `REPORTED`); all other from-state failures carry `ERR_INVALID_STATE`.
7. **Optimistic concurrency.** On a schedule rebuild, `expected_loan_version` must equal the loan's current `version`; on a policy update, `expected_plan_version` must equal the plan's current `version`. A mismatch is rejected with `ERR_STALE_VERSION`.
8. **Plan posture.** The plan is `ACTIVE` for the operations enumerated in §2.7; otherwise `ERR_PLAN_NOT_ACTIVE`.
9. **Hardship substantiation at final approval.** Under a `FULL_DOCUMENTATION` standard, at least one uploaded document must exist; under `SELF_CERTIFY`, the request's `attestation` must be true. Otherwise `ERR_SUBSTANTIATION_INCOMPLETE`.
10. **Temporal checks.** No `ACTIVE` SuspensionRecord may exist for the participant — checked at hardship creation, at loan creation, and re-checked at the final hardship approval — otherwise `ERR_SUSPENSION_OVERLAP`. A refinance must observe the plan's lookback period, otherwise `ERR_REFINANCE_LOOKBACK_VIOLATION`. An election restart requires every suspension to be expired, otherwise `ERR_SUSPENSION_STILL_ACTIVE`.
11. **Business constraints**, evaluated in exactly this order: the hardship `reason_category` is among the plan's `allowed_hardship_reasons` (otherwise `ERR_UNSAFE_HARBOR_REASON`); the participant's `employment_status` is `ACTIVE` for a new loan or hardship (otherwise `ERR_EMPLOYMENT_NOT_ACTIVE`); the logical clock has reached `loan_eligibility_locked_until` or that field is null (otherwise `ERR_LOAN_ELIGIBILITY_LOCKED`); the count of the participant's loans in `REQUESTED`, `APPROVED`, or `DISBURSED` is below the plan's `max_loans_outstanding` (otherwise `ERR_MAX_LOANS_OUTSTANDING`); the requested `principal_amount_cents` is at least the plan's `min_loan_amount_cents` (otherwise `ERR_LOAN_BELOW_MINIMUM`); the requested `term_months` does not exceed the plan's `max_term_months`; and, for a refinance, the plan's `allows_refinance` is true (otherwise `ERR_REFINANCE_NOT_ALLOWED`).
12. **Fiscal checks.** The requested principal — or, for a refinance, the new principal — must not exceed the computed maximum loan amount (otherwise `ERR_LOAN_LIMIT_EXCEEDED`); a hardship `amount_cents` must not exceed the participant's `vested_balance_cents` at creation (otherwise `ERR_INSUFFICIENT_VESTED_BALANCE`); under `FULL_DOCUMENTATION`, the uploaded documents' amounts must sum to at least the requested `amount_cents` at final approval (otherwise `ERR_HARDSHIP_AMOUNT_EXCEEDS_NEED`); an explicit remittance allocation must sum exactly to the remittance `amount_cents` (otherwise `ERR_REMITTANCE_AMOUNT_MISMATCH`); and at hardship payment the `gross_withdrawal_cents` must not exceed the vested balance (otherwise `ERR_INSUFFICIENT_VESTED_BALANCE`).

### 2.9. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and both name their expectation field explicitly.

Rebuilding a loan's amortization schedule requires the request to carry `expected_loan_version`, a non-optional field holding the `version` of the loan as the client last observed it. If another writer has advanced the loan's version since that read — a prior rebuild, a disbursement, or any other mutation — the rebuild is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the outstanding principal and remaining schedule is stale.

Updating a plan's policy requires the request to carry `expected_plan_version`, likewise non-optional, matched against the plan's current `version`. A policy update supersedes the prior policy revision that pending loan and hardship requests were validated against, so a stale expectation is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.10. Nested Resource Retrieval

The API enforces strict, hierarchical validation for requests that target nested resources. When a path contains multiple identifiers, the system validates existence sequentially, left to right — plan first, then participant, then the loan, hardship request, remittance, approval task, or tax event — and rejects the request immediately with the not-found error corresponding to the first identifier that does not resolve. The not-found errors are resource-specific: `ERR_PLAN_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND` (also used when the participant does not belong to the plan in the path), `ERR_LOAN_NOT_FOUND`, `ERR_HARDSHIP_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_APPROVAL_TASK_NOT_FOUND`, and `ERR_TAX_EVENT_NOT_FOUND`.

### 2.11. The Append-Only Audit Trail

Every mutating endpoint appends exactly one `AuditEvent`, scoped to the affected plan, before returning. An audit event records the `actor_role` (the `X-User-Role` of the mutating call), the `actor_id` (its `X-User-ID`), a machine action name in `action` — values such as `PLAN_CREATED`, `PLAN_POLICY_UPDATED`, `PLAN_FROZEN`, `PLAN_UNFROZEN`, `PARTICIPANT_ENROLLED`, `PARTICIPANT_TERMINATED`, `ELECTION_SET`, `ELECTION_RESTARTED`, `LOAN_REQUESTED`, `LOAN_APPROVED`, `LOAN_DISBURSED`, `LOAN_REFINANCED`, `LOAN_DEEMED`, `REMITTANCE_POSTED`, `REMITTANCE_REVERSED`, `HARDSHIP_REQUESTED`, `HARDSHIP_APPROVED`, `HARDSHIP_DOCUMENT_UPLOADED`, `HARDSHIP_PAID`, `APPROVAL_DECIDED`, and `TAX_EVENT_REPORTED` — plus the `subject_type` and `subject_id` of the entity the action affected, and a `detail` payload snapshot specific to the action. Audit events are never updated or deleted, and a plan's audit trail is listed in ascending `created_at` order — events stamped at the same clock reading appear in the order they were appended — to `RecordkeeperAdmin` and `Auditor` readers.

## 3. Business Logic & Workflows

### 3.1. Establishing a Plan: Policy Levers and Posture

A `RecordkeeperAdmin` establishes a retirement plan by supplying a `name` and, optionally, any subset of the plan's policy levers; every omitted lever takes its default. The loan policy levers are `max_loans_outstanding` (default 1), which caps how many of a participant's loans may simultaneously stand in `REQUESTED`, `APPROVED`, or `DISBURSED`; `min_loan_amount_cents` (default 100,000 cents — one thousand dollars); `max_loan_amount_cents` (default 5,000,000 cents); `max_term_months` (default 60); `interest_rate_bps` (default 500), the fixed annual loan rate; `day_count_convention`, either `THIRTY_360` (the default) or `ACT_360`; `allows_refinance` (default false); and `refinance_min_months_since_disbursement` (default 12), the minimum whole calendar months that must elapse between a loan's disbursement and its refinance. The hardship policy levers are `hardship_suspension_months` (default 6), the deferral-suspension length that follows a paid hardship distribution; `substantiation_standard`, either `FULL_DOCUMENTATION` (the default) or `SELF_CERTIFY`; `withholding_rate_bps` (default 2000), the mandatory withholding rate on hardship distributions; and `allowed_hardship_reasons`, the plan-permitted safe-harbor reason categories, defaulting to `MEDICAL`, `FUNERAL`, `EVICTION`, `TUITION`, `HOME_PURCHASE`, and `DISASTER`. Two further levers govern workflow rather than money: `loan_approval_chain` and `hardship_approval_chain` are ordered lists of approver roles, each defaulting to `PLAN_SPONSOR` followed by `RECORDKEEPER_ADMIN`, and each entry spawns one approval task per originating request.

Plan creation appends a `PLAN_CREATED` audit record. Thereafter a `RecordkeeperAdmin` may update the plan's policy; the update supersedes the prior revision and is protected by optimistic concurrency as described in §2.9. Policy changes are prospective only: each loan snapshots the plan's `interest_rate_bps` and `day_count_convention` at request time, so a later policy revision never alters the terms of loans already on the books. The policy update increments the plan's `version` by one and appends `PLAN_POLICY_UPDATED`. Posture changes — freeze and unfreeze — follow §2.7.

### 3.2. Participant Enrollment and Employment Termination

Enrollment is a `RecordkeeperAdmin` operation: within a plan, the administrator supplies the participant's `full_name` and current `vested_balance_cents`, with an optional `external_ref` carrying the employer's payroll or HR reference. The new participant is linked to its plan through `plan_id`, begins with `employment_status` of `ACTIVE`, a null `terminated_on`, a `contribution_status` of `NONE` (no election exists yet), a `ytd_taxable_distributions_cents` of zero, and a null `loan_eligibility_locked_until`. Enrollment appends `PARTICIPANT_ENROLLED`. Afterwards, custodian synchronization adjusts `vested_balance_cents` through the participant update operation; a participant may read only its own record, while `PlanSponsor`, `RecordkeeperAdmin`, and `Auditor` readers may read any.

Termination moves `employment_status` from `ACTIVE` to `TERMINATED` and is likewise performed by a `RecordkeeperAdmin`; attempting it on a participant already `TERMINATED` is rejected with `ERR_INVALID_STATE`. The supplied `terminated_on` is recorded, defaulting to the logical clock date when omitted, and the participant's `version` increments. Termination fires a multi-link cascade. First, each of the participant's loans standing `DISBURSED` with `outstanding_principal_cents` above zero is processed in ascending `created_at` order — loans stamped at the same clock reading are processed in the order they were created — and moved to `OFFSET`, and each offset loan's remaining `PENDING` and `MISSED` installments are `CLOSED`. Second, each offset transition itself creates a `TaxEvent` whose `source_type` is `LOAN_OFFSET`, whose taxable amount follows the offset variant described in §3.7 with its accrued-interest sum evaluated over the installment statuses standing at the offset transition — that is, before this cascade closes the loan's remaining installments — and whose `event_date` is `terminated_on`. Third, each created tax event adds its `taxable_amount_cents` into the participant's `ytd_taxable_distributions_cents` and sets `loan_eligibility_locked_until` to the later of its existing value and `terminated_on` plus twelve calendar months. The participant's contribution election, if `ACTIVE` or `SUSPENDED`, moves to `TERMINATED`, and `contribution_status` follows it to `TERMINATED`. Any `PENDING` approval tasks on the participant's open loan subjects are `CANCELLED`. Finally, the cascade appends `PARTICIPANT_TERMINATED`.

### 3.3. Deferral Elections and Post-Hardship Suspensions

Each participant holds at most one contribution election. The participant itself sets the election by supplying `deferral_pct`, the elective deferral percentage of pay, which must be greater than zero and at most sixty. Creation stamps `effective_on` with the logical clock date, starts the election `ACTIVE`, sets the participant's `contribution_status` to `ACTIVE`, and appends `ELECTION_SET`. While the election remains `ACTIVE`, the same operation may replace `deferral_pct`. Reading the election returns an array of zero or one records.

Two later transitions complete the election's cycle. When a hardship distribution is paid, a suspension record is created and the election moves from `ACTIVE` to `SUSPENDED`, dragging `contribution_status` to `SUSPENDED` with it. Attempting to replace the deferral percentage while the election is `SUSPENDED` is rejected with `ERR_INVALID_STATE` — the participant must instead restart. And when employment terminates, the election moves from `ACTIVE` or `SUSPENDED` to `TERMINATED` as part of the cascade in §3.2.

A `SuspensionRecord` records the window during which deferrals and new distributions are barred: its `starts_on` equals the paying hardship request's `paid_on`, its `ends_on` is `paid_on` plus the plan's `hardship_suspension_months` calendar months on the same day-of-month, and it links back to its cause through `hardship_request_id`. The window is half-open — it includes `starts_on` and excludes `ends_on` — so a new loan request or hardship request created while the current date falls within the window is rejected with `ERR_SUSPENSION_OVERLAP`. When the logical clock reaches `ends_on`, the record flips from `ACTIVE` to `EXPIRED`. Expiry does not by itself revive the election: restarting deferrals is an explicit participant action, permitted only once every suspension record for the participant has expired — the logical clock has reached each record's `ends_on` — and rejected with `ERR_SUSPENSION_STILL_ACTIVE` while any suspension remains `ACTIVE`. Restart additionally requires `employment_status` of `ACTIVE`, failing with `ERR_EMPLOYMENT_NOT_ACTIVE` otherwise. A successful restart moves the election from `SUSPENDED` back to `ACTIVE`, restores `contribution_status` to `ACTIVE`, and appends `ELECTION_RESTARTED`. A participant's suspension records may be listed, and the suspension record created by a particular hardship request may be read back from that request — again an array of zero or one.

### 3.4. Requesting a Loan: Eligibility, Limits, and Approval

A participant requests a loan against its own account by supplying `principal_amount_cents` and `term_months`. The request creates a `Loan` stamped with the requesting `participant_id` and the `plan_id` of the enclosing plan, with the plan's `interest_rate_bps` and `day_count_convention` snapshotted onto the loan at that moment; its `lifecycle_status` begins at `REQUESTED`, its parallel `delinquency_status` at `NONE`, and `disbursed_on`, `cure_deadline_on`, `deemed_on`, `scheduled_payment_cents`, and `refinances_loan_id` all begin null while `accrued_unpaid_interest_cents` begins at zero. Creation appends `LOAN_REQUESTED` and spawns the approval pipeline: one `ApprovalTask` per entry of the plan's `loan_approval_chain`, each carrying the plan's `plan_id`, a `subject_type` of `LOAN`, the loan's id as `subject_id`, a 1-based `step_order` reflecting the entry's position in the chain, the chain entry's role as `approver_role`, and an initial `status` of `PENDING`.

Before any of that, the request passes the cascade of §2.8: the temporal check rejects a participant with an unexpired suspension (`ERR_SUSPENSION_OVERLAP`), then the business-constraint checks run in their pinned order — `employment_status` must be `ACTIVE` (`ERR_EMPLOYMENT_NOT_ACTIVE`), the logical clock must have reached `loan_eligibility_locked_until` or that field must be null (`ERR_LOAN_ELIGIBILITY_LOCKED`), the number of loans standing in `REQUESTED`, `APPROVED`, or `DISBURSED` must be below `max_loans_outstanding` (`ERR_MAX_LOANS_OUTSTANDING`), the principal must be at least `min_loan_amount_cents` (`ERR_LOAN_BELOW_MINIMUM`), and the term must not exceed `max_term_months`. The fiscal check then caps the principal at the computed maximum loan amount, rejecting with `ERR_LOAN_LIMIT_EXCEEDED`.

That maximum is the smallest of three quantities: one half of the participant's `vested_balance_cents`, rounded down to a whole cent; the statutory ceiling of 5,000,000 cents (fifty thousand dollars), reduced by the amount — never below zero — by which the participant's trailing twelve-month high-water mark of outstanding principal exceeds their current outstanding total; and the plan's own `max_loan_amount_cents`. The current outstanding total is the sum of `outstanding_principal_cents` across the participant's loans standing in the `DISBURSED` lifecycle — with the further rule that loans which have been deemed, offset, refinanced, or repaid contribute to the historical high-water mark but not to the current total. The high-water mark is computed over the closed lookback window running from the day twelve calendar months before today through yesterday: for each calendar day in that window, the end-of-day sum of `outstanding_principal_cents` across all of the participant's loans is reconstructed chronologically from disbursement dates and remittance posting dates, breaking same-day ties by ascending `created_at`, and the largest such daily total is the mark. A participant who repaid or offset a loan within the trailing year therefore sees the statutory ceiling shrink below fifty thousand dollars by exactly the excess of that historical mark over what they still owe. The same computation backs the loan-eligibility read available to the participant and to `PlanSponsor`, `RecordkeeperAdmin`, and `Auditor` roles, which reports `eligible`, `max_loan_amount_cents`, `outstanding_loan_count`, and `loan_eligibility_locked_until`.

While a loan stands `REQUESTED`, the requesting participant may withdraw it — the ownership check compares `X-User-ID` to the loan's `participant_id` — moving it to `WITHDRAWN`, cancelling its `PENDING` approval tasks, and incrementing the loan's `version`.

The approval pipeline decides the request. Deciding a step takes a `decision` of `APPROVE`, `REJECT`, or `REQUEST_DOCS`, and the decider's role must equal the task's `approver_role` — a `PLAN_SPONSOR` step is decided by a `PlanSponsor`, a `RECORDKEEPER_ADMIN` step by a `RecordkeeperAdmin` — failing which the decision is rejected with `ERR_UNAUTHORIZED_ROLE`. Steps are strictly ordered: deciding step N while any lower-`step_order` task on the same subject is still `PENDING` fails with `ERR_APPROVAL_OUT_OF_ORDER`, and deciding a task that already stands `APPROVED`, `REJECTED`, or `CANCELLED` fails with `ERR_TASK_ALREADY_DECIDED`. Segregation of duties applies to every decision: the decider's `X-User-ID` must differ from the `decided_by` of every other decided task on the same subject, and from the requesting participant's id, else `ERR_SEGREGATION_OF_DUTIES`. A successful decision stamps `decided_by` with the caller's `X-User-ID` and `decided_on` with the logical clock, and appends `APPROVAL_DECIDED`. When the final chain step is approved, the subject loan moves from `REQUESTED` to `APPROVED` and appends `LOAN_APPROVED`. Any rejection moves the subject from `REQUESTED` to `DENIED` and cancels the sibling tasks still `PENDING`. Approval tasks for a loan subject can be listed in ascending `step_order`, and any task can be read individually by the `PlanSponsor`, `RecordkeeperAdmin`, and `Auditor` roles.

### 3.5. Disbursement and the Amortization Schedule

Disbursement is a `RecordkeeperAdmin` action on an `APPROVED` loan under an `ACTIVE` plan (a frozen plan rejects it with `ERR_PLAN_NOT_ACTIVE`). It stamps `disbursed_on` with the logical clock date, moves `delinquency_status` from `NONE` to `CURRENT`, increments the loan's `version`, appends `LOAN_DISBURSED`, and generates the amortization schedule: `scheduled_payment_cents` is fixed, and `term_months` installment rows are created, each `PENDING` with `paid_amount_cents` at zero. Installment rows carry a 1-based `installment_number`, a `due_date` falling monthly on the disbursement day-of-month with the first installment due one month after `disbursed_on`, and the scheduled split of `principal_portion_cents` and `interest_portion_cents` summing to `scheduled_amount_cents`. Each row references its loan through `loan_id`. The schedule is listable in ascending `installment_number` by the `RecordkeeperAdmin`, `PlanSponsor`, `Auditor`, `PayrollProvider`, and `Participant` roles.

The level payment is computed first and rounded exactly once: the monthly rate is the loan's `interest_rate_bps` divided by ten thousand and then by twelve; the raw payment equals the principal multiplied by the monthly rate, divided by the difference between one and the quantity one-plus-the-monthly-rate raised to the power of negative `term_months`; and `scheduled_payment_cents` is that raw payment rounded half up to a whole cent. The schedule then walks the balance installment by installment, in order. Each installment's interest portion is the outstanding balance multiplied by that installment's period rate, rounded half up to a whole cent. For every installment except the last, the principal portion is the level payment minus the interest portion and the scheduled amount equals the level payment. The final installment takes the entire remaining balance as its principal portion, and its scheduled amount is that principal plus its own interest portion — the final row thereby absorbs the accumulated rounding remainder, and the principal portions across the schedule sum to the original principal exactly. The period rate depends on the loan's day-count convention: under `THIRTY_360` every installment's period rate is the annual rate divided by twelve, while under `ACT_360` each installment's period rate is the annual rate multiplied by the actual number of days between the previous due date — the disbursement date for the first installment — and that installment's own due date, divided by 360. Identical inputs therefore yield different interest portions and a different final installment under the two conventions.

Two computed figures track a disbursed loan's position. `outstanding_principal_cents` is the original principal minus the principal applied by non-reversed remittances, where each installment's principal coverage is the portion of its `paid_amount_cents` exceeding its `interest_portion_cents`, never below zero. `accrued_unpaid_interest_cents` sums, over installments whose `due_date` has arrived by the evaluation date and whose status is `PENDING` or `MISSED`, each installment's `interest_portion_cents` reduced by the interest already covered by payments.

A `RecordkeeperAdmin` may later rebuild the schedule, re-amortizing the loan's outstanding principal over a newly supplied `term_months` under an `ACTIVE` plan. The rebuild request must carry `expected_loan_version` equal to the loan's current `version`; a stale expectation is rejected with `ERR_STALE_VERSION` as described in §2.9. On success, every still-`PENDING` installment is superseded to `REBUILT` — `MISSED`, `PAID`, and `CURED` rows are retained unchanged — a fresh set of `PENDING` rows is generated over the rebuild term by the same amortization calculation, and `scheduled_payment_cents` is recomputed. The new rows continue the sequence: their `installment_number` values resume from the prior maximum, and their due dates continue the monthly cadence from the last superseded row's `due_date`. The rebuild increments the loan's `version` by one.

### 3.6. Payroll Remittances and the Repayment Waterfall

Repayment arrives as payroll deduction remittances, posted by the `PayrollProvider` integration or a `RecordkeeperAdmin`. Each remittance carries `amount_cents` — the total deduction — and the `pay_date` of the payroll run it corresponds to, which is the date used for cure-deadline comparison. The remittance starts `POSTED`, references its participant through `participant_id`, and appends `REMITTANCE_POSTED`. A participant's remittance history is listable by the participant and by `RecordkeeperAdmin`, `PlanSponsor`, `Auditor`, and `PayrollProvider` readers.

When the posting omits `allocations`, the server allocates the funds itself by a deterministic waterfall. The eligible loans are the participant's loans standing `DISBURSED` whose delinquency has not reached `DEEMED`; loans already `REPAID`, `REFINANCED`, or `OFFSET` are out of scope, as are deemed loans. The candidate installments are every installment of those eligible loans whose status is `MISSED` or `PENDING` and whose `paid_amount_cents` still falls short of `scheduled_amount_cents`. Funds are applied in a pinned order: `MISSED` installments first, then `PENDING`; within each group by ascending `due_date`, then by the owning loan's ascending `created_at`, then by ascending `installment_number`. Each candidate receives the smaller of the remaining funds and its unpaid balance; within an installment, the covered interest is the smaller of the applied amount and the portion of `interest_portion_cents` not yet covered, and the remainder of the applied amount reduces principal. Because the candidate set spans every unpaid installment, the total coverable amount equals the full remaining scheduled balance — so if funds remain after every candidate is satisfied, the remittance overpays the schedule and the entire posting is rejected atomically with `ERR_REMITTANCE_AMOUNT_MISMATCH`, nothing applied at all. If there are no eligible loans or no candidate installments whatsoever, the posting is rejected with `ERR_INVALID_STATE`.

When the posting supplies explicit `allocations` — a list of loan-and-amount pairs — the amounts must sum exactly to `amount_cents`, failing which the posting is rejected with `ERR_REMITTANCE_AMOUNT_MISMATCH`; every referenced loan must belong to the eligible set just defined, failing which the rejection is `ERR_INVALID_STATE`. Explicit amounts are then applied to each referenced loan's installments in the same waterfall order. Either way, the server records the allocation outcome on the remittance as `applied_allocations`: an ordered list of application records, each naming the target `loan_id` and `installment_id` with the applied `amount_cents` split into `to_interest_cents` and `to_principal_cents`, preserving application order as the snapshot used for exact reversal.

Application re-evaluates the loan. An installment whose coverage reaches `scheduled_amount_cents` moves from `PENDING` to `PAID`; a covered `MISSED` installment becomes `CURED` provided the remittance's `pay_date` falls on or before `cure_deadline_on`, and when every missed installment is cured within that deadline the loan's delinquency returns from `DELINQUENT` to `CURRENT` and `cure_deadline_on` clears to null. When a posting drives `outstanding_principal_cents` to exactly zero, the loan moves from `DISBURSED` to `REPAID`, and its remaining `PENDING` installments are `CLOSED` while `MISSED` and `CURED` rows retain their history.

Reversal is the mirror image, performed by a `RecordkeeperAdmin` under an `ACTIVE` plan. Reversing a remittance that already stands `REVERSED` fails with `ERR_INVALID_STATE`; otherwise the remittance moves from `POSTED` to `REVERSED` and the server undoes `applied_allocations` exactly, decrementing each referenced installment's `paid_amount_cents` by its recorded amount. The loan's `outstanding_principal_cents` is recomputed, and a loan that had reached `REPAID` returns to `DISBURSED` when outstanding principal is restored above zero — in that case each `CLOSED` row whose `paid_amount_cents` again falls short of `scheduled_amount_cents` returns to `PENDING`. Installment statuses are then recomputed from the remaining non-reversed remittances against the current logical clock: an unpaid row whose `due_date` has passed becomes `MISSED` again, while a still-future unpaid row returns to `PENDING`. Delinquency re-evaluates with them — a cure may be undone, moving the loan from `CURRENT` back to `DELINQUENT` when a `MISSED` installment is again unpaid and the logical clock has not passed the recomputed `cure_deadline_on`. The reversal appends `REMITTANCE_REVERSED`.

### 3.7. Delinquency, Cure, and Deemed Distributions

Delinquency is a second, independent state dimension on the loan, meaningful only while the lifecycle stands `DISBURSED`. When the logical clock advances past an installment's `due_date` while its `paid_amount_cents` still falls short of `scheduled_amount_cents`, the installment moves from `PENDING` to `MISSED` and the loan's delinquency moves from `CURRENT` to `DELINQUENT`. At that entry the system fixes `cure_deadline_on`: take the earliest still-unpaid `MISSED` installment's `due_date`, find the calendar quarter containing it — quarters run January through March, April through June, July through September, and October through December — and set the deadline to the last day of the calendar quarter immediately following that quarter.

Cure is a remittance-driven return to good standing: when a posting leaves every `MISSED` installment with `paid_amount_cents` at least equal to `scheduled_amount_cents`, and the remittance's `pay_date` falls on or before `cure_deadline_on` — the boundary is inclusive — the cured installments move from `MISSED` to `CURED`, delinquency returns to `CURRENT`, and `cure_deadline_on` clears.

When instead the logical clock first advances to a date later than `cure_deadline_on` while any `MISSED` installment remains unpaid, the deemed distribution fires in four links. First, the loan's delinquency moves to `DEEMED` and `deemed_on` is stamped with the logical clock date; the loan leaves the remittance waterfall's input set and accepts no further remittance application, keeping its outstanding principal for recordkeeping. Second, the transition itself creates a `TaxEvent` whose `source_type` is `LOAN_DEEMED`, whose `event_date` is `deemed_on`, and whose taxable amount follows the deemed variant below. Third, the created event adds its `taxable_amount_cents` into the participant's `ytd_taxable_distributions_cents` and sets `loan_eligibility_locked_until` to `deemed_on` plus twelve calendar months. Fourth, while the logical clock remains earlier than that lock, any new loan request by the participant is rejected with `ERR_LOAN_ELIGIBILITY_LOCKED`. The cascade appends `LOAN_DEEMED`.

Both loan-derived taxable events share one formula with two cutoffs. The taxable amount is the loan's `outstanding_principal_cents` plus its accrued unpaid interest through a cutoff date, where accrued unpaid interest through a cutoff sums, over installments whose `due_date` falls on or before the cutoff and whose status is `PENDING` or `MISSED`, each installment's `interest_portion_cents` reduced by the interest already covered by non-reversed remittances. For the deemed variant the cutoff is `cure_deadline_on` — the quarter-end — regardless of the clock date on which the transition fires; for the offset variant the cutoff is the event posting date, `terminated_on`. Identical loan data and clock therefore produce different taxable amounts under the two variants whenever an installment due date falls between the two cutoffs. Each event's `tax_year` is the calendar year of its `event_date`.

### 3.8. Refinancing an Outstanding Loan

Where a plan permits it, a `RecordkeeperAdmin` may refinance a `DISBURSED` loan, supplying `cash_out_cents` for any additional cash the participant takes out. The refinance is gated in cascade order: the plan's `allows_refinance` must be true (`ERR_REFINANCE_NOT_ALLOWED`); the loan's delinquency must not stand `DEEMED` (`ERR_INVALID_STATE`); at least `refinance_min_months_since_disbursement` whole calendar months must have elapsed since the old loan's `disbursed_on` (`ERR_REFINANCE_LOOKBACK_VIOLATION`); and the new principal must not exceed the participant's computed maximum loan amount — high-water reduction included — (`ERR_LOAN_LIMIT_EXCEEDED`).

The new principal is the old loan's `outstanding_principal_cents` plus the accrued unpaid interest due through the logical clock date — computed exactly as the interest component of the taxable-amount formula with that cutoff — plus the supplied `cash_out_cents`, plus a flat refinance fee of 10,000 cents (one hundred dollars). The refinance continues the original terms: the new loan preserves the old loan's `term_months`, `interest_rate_bps`, and `day_count_convention`. The operation is atomic and a replacement rather than an addition: the old loan leaves the set counted by `max_loans_outstanding` at the same moment the new one enters it, so the refinance itself never breaches the multiple-loan policy. A conserved-quantity invariant pins the accounting — the sum of `outstanding_principal_cents` over the participant's loans after the refinance, minus the same sum before it, equals exactly `cash_out_cents` plus the refinance fee.

The side effects land in two links. The old loan's `outstanding_principal_cents` goes to zero, its remaining `PENDING` installments are `CLOSED`, its delinquency resets to `NONE`, and its lifecycle moves from `DISBURSED` to `REFINANCED`. The new loan is created already `DISBURSED`, with `refinances_loan_id` pointing at the loan it replaces, `disbursed_on` stamped with the logical clock date, delinquency `CURRENT`, and its amortization schedule generated by the calculation of §3.5. A `LOAN_REFINANCED` audit record is appended on both loans. Because the refinance creates a new resource, it answers with 201. The lineage is queryable: the refinances listing on a loan returns the loans whose `refinances_loan_id` points at it — an array of zero or one.

### 3.9. Hardship Withdrawals from Request to Payment

A participant opens a hardship withdrawal by supplying a `reason_category` — one of `MEDICAL`, `FUNERAL`, `EVICTION`, `TUITION`, `HOME_PURCHASE`, or `DISASTER` — together with `amount_cents` and, optionally, `amount_semantics` and `attestation`. The request is stamped with the `participant_id` and the plan's `plan_id`, begins `UNDER_REVIEW` with a null `paid_on`, appends `HARDSHIP_REQUESTED`, and spawns one approval task per entry of the plan's `hardship_approval_chain`, mirroring the loan pipeline with a `subject_type` of `HARDSHIP`. The cascade of §2.8 guards creation: the `reason_category` must appear in the plan's `allowed_hardship_reasons` (`ERR_UNSAFE_HARBOR_REASON`), employment must be `ACTIVE` (`ERR_EMPLOYMENT_NOT_ACTIVE`), no unexpired suspension may exist (`ERR_SUSPENSION_OVERLAP`), and the requested `amount_cents` must not exceed the participant's `vested_balance_cents` (`ERR_INSUFFICIENT_VESTED_BALANCE`).

Creation also computes and stores the distribution's economics, in an evaluation order that is pinned because the fee tier depends on the gross and the gross depends on the fee; let w denote the plan's `withholding_rate_bps` divided by ten thousand. Under the `NET` semantics — the participant must receive exactly `amount_cents` after withholding and fee — the provisional gross is `amount_cents` divided by the difference between one and w; `fee_cents` is then 5,000 cents when that provisional gross is at most 1,000,000 cents (ten thousand dollars) and 7,500 cents above it; `gross_withdrawal_cents` is the sum of `amount_cents` and `fee_cents`, divided by the difference between one and w, rounded half up to a whole cent; `withholding_cents` is the gross multiplied by w, rounded half up; and `net_disbursed_cents` is the gross minus the withholding minus the fee. Under the default `GROSS` semantics — `amount_cents` is the total distribution — `gross_withdrawal_cents` equals `amount_cents`; the same tier rule sets `fee_cents` at 5,000 cents when the gross is at most 1,000,000 cents and 7,500 cents above it; `withholding_cents` is the gross multiplied by w, rounded half up; and `net_disbursed_cents` is again the gross minus the withholding minus the fee. The same `amount_cents` therefore yields a larger `gross_withdrawal_cents` under `NET` than under `GROSS`.

Substantiation depends on the plan's `substantiation_standard`, and it is enforced at the final approval step. Under `FULL_DOCUMENTATION`, at least one uploaded document must exist, else the decision is rejected with `ERR_SUBSTANTIATION_INCOMPLETE`, and the uploaded documents' `amount_cents` values must sum to at least the requested `amount_cents`, else `ERR_HARDSHIP_AMOUNT_EXCEEDS_NEED`. Under `SELF_CERTIFY`, the request's `attestation` must be true, else `ERR_SUBSTANTIATION_INCOMPLETE`. The temporal re-check also runs at final approval: an unexpired suspension surfacing between creation and decision rejects with `ERR_SUSPENSION_OVERLAP`. When the final step approves, the request moves from `UNDER_REVIEW` to `APPROVED` and appends `HARDSHIP_APPROVED`; any rejection moves it to `DENIED` and cancels the sibling tasks still `PENDING`.

Evidence arrives as documents uploaded by the participant on its own request, each with a `document_type` of `INVOICE`, `MEDICAL_BILL`, `BANK_STATEMENT`, `ATTESTATION`, `EVICTION_NOTICE`, or `OTHER`, the expense `amount_cents` it evidences, and an optional free-text `description`; each document links back through `hardship_request_id` and carries a `retained_until` that stays null until the request is paid. An upload appends `HARDSHIP_DOCUMENT_UPLOADED`. An approver who needs more evidence decides the task with `REQUEST_DOCS` — valid only for `HARDSHIP` subjects; the same decision on a `LOAN` subject is rejected with `ERR_INVALID_REQUEST` — which moves the task to `DOCS_REQUESTED` and the request from `UNDER_REVIEW` to `PENDING_DOCUMENTS`. When the participant then uploads a document, the request returns to `UNDER_REVIEW` and the `DOCS_REQUESTED` task returns to `PENDING` with its `decided_by` and `decided_on` cleared: the step reopens for a fresh decision, and the earlier request-documents decision does not count toward segregation of duties. While `UNDER_REVIEW` or `PENDING_DOCUMENTS`, the participant may withdraw the request — ownership again compares `X-User-ID` to the request's `participant_id` — moving it to `WITHDRAWN`, cancelling its `PENDING` tasks, and incrementing its `version`. Documents are listable by the participant and by `RecordkeeperAdmin`, `PlanSponsor`, and `Auditor` readers.

Payment of an `APPROVED` request is a `RecordkeeperAdmin` action under an `ACTIVE` plan, and it requires the `gross_withdrawal_cents` to fit within the participant's current `vested_balance_cents`, else `ERR_INSUFFICIENT_VESTED_BALANCE`. Payment stamps `paid_on` with the logical clock date, debits `vested_balance_cents` by the gross withdrawal, and fires the suspension cascade: a `SuspensionRecord` is created with `starts_on` equal to `paid_on` and `ends_on` per the window rule of §3.3; that new `ACTIVE` suspension moves the participant's election from `ACTIVE` to `SUSPENDED`; and the election's suspension sets `contribution_status` to `SUSPENDED`. Payment also creates a `TaxEvent` whose `source_type` is `HARDSHIP_DISTRIBUTION`, whose `taxable_amount_cents` equals the `gross_withdrawal_cents` directly, and whose `event_date` is `paid_on`, adding the gross into `ytd_taxable_distributions_cents`; and it stamps `retained_until` as `paid_on` plus seven calendar years on every document of the request, fixing the retention deadline. The cascade appends `HARDSHIP_PAID`.

Every tax event — deemed, offset, or hardship — begins `PENDING` and is identifiable by its polymorphic `source_type` and `source_id`. A participant's events are listable, individually readable, by the participant and by `RecordkeeperAdmin` and `Auditor` readers, and both `PENDING` and `REPORTED` events count toward `ytd_taxable_distributions_cents`. Once the 1099-R has been filed, a `RecordkeeperAdmin` marks the event reported, moving it from `PENDING` to `REPORTED`, incrementing its `version`, and appending `TAX_EVENT_REPORTED`; marking an already-`REPORTED` event is rejected with `ERR_TAX_EVENT_ALREADY_REPORTED`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — a plan, a participant, a loan request, a remittance, a hardship request, an uploaded document — or that produce a new resource as their result — a refinance creating the replacement loan — return a `201 Created` status code. Operations that modify an existing resource or read data return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a retirement plan with loan/hardship policy | RecordkeeperAdmin |
| GET | `/plans/{id}` | Read a plan | RecordkeeperAdmin, PlanSponsor, Auditor |
| PUT | `/plans/{id}/policy` | Update plan policy (OCC via `expected_plan_version`) | RecordkeeperAdmin |
| POST | `/plans/{id}/freeze` | Freeze plan (posture gate) | PlanSponsor, RecordkeeperAdmin |
| POST | `/plans/{id}/unfreeze` | Unfreeze plan | PlanSponsor, RecordkeeperAdmin |
| GET | `/plans/{id}/participants` | List participants of a plan (paginated) | RecordkeeperAdmin, PlanSponsor, Auditor |
| GET | `/plans/{id}/loans` | List loans booked under a plan (paginated) | RecordkeeperAdmin, PlanSponsor, Auditor |
| GET | `/plans/{id}/hardship-requests` | List hardship requests under a plan (paginated) | RecordkeeperAdmin, PlanSponsor, Auditor |
| GET | `/plans/{id}/approval-tasks` | List approval tasks under a plan (paginated) | RecordkeeperAdmin, PlanSponsor, Auditor |
| GET | `/plans/{id}/audit-events` | List the plan's append-only audit trail, `created_at` ascending (paginated) | RecordkeeperAdmin, Auditor |
| POST | `/plans/{id}/participants` | Enroll a participant | RecordkeeperAdmin |
| GET | `/participants/{id}` | Read a participant (Participant role may read only itself) | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| PATCH | `/participants/{id}` | Custodian sync / termination; termination triggers the offset cascade | RecordkeeperAdmin |
| PUT | `/participants/{id}/contribution-election` | Create the participant's deferral election, or replace `deferral_pct` while `ACTIVE` | Participant |
| GET | `/participants/{id}/contribution-election` | Read the participant's election (array of 0 or 1) | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| POST | `/participants/{id}/contribution-election/restart` | Restart deferrals after suspension expiry | Participant |
| GET | `/participants/{id}/loan-eligibility` | Computed read of loan eligibility | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| POST | `/participants/{id}/loans` | Request a loan; snapshots plan terms; creates the approval chain | Participant |
| GET | `/participants/{id}/loans` | List a participant's loans (paginated) | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| GET | `/loans/{id}` | Read a loan | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| POST | `/loans/{id}/withdraw` | Participant withdraws a `REQUESTED` loan | Participant |
| POST | `/loans/{id}/disburse` | Disburse an `APPROVED` loan; generates the amortization schedule | RecordkeeperAdmin |
| POST | `/loans/{id}/refinance` | Refinance a `DISBURSED` loan into an atomically disbursed new loan | RecordkeeperAdmin |
| POST | `/loans/{id}/schedule/rebuild` | Re-amortize outstanding principal over a new term (OCC via `expected_loan_version`) | RecordkeeperAdmin |
| GET | `/loans/{id}/installments` | List the loan's amortization schedule rows, `installment_number` ascending (paginated) | RecordkeeperAdmin, PlanSponsor, Auditor, PayrollProvider, Participant |
| GET | `/loans/{id}/refinances` | List loans whose `refinances_loan_id` points at this loan (array of 0 or 1) | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| GET | `/loans/{id}/approval-tasks` | List approval tasks for a loan subject, `step_order` ascending | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| POST | `/participants/{id}/remittances` | Post a payroll deduction remittance; auto-allocates per waterfall when `allocations` is omitted | PayrollProvider, RecordkeeperAdmin |
| GET | `/participants/{id}/remittances` | List a participant's remittances (paginated) | RecordkeeperAdmin, PlanSponsor, Auditor, PayrollProvider, Participant |
| POST | `/remittances/{id}/reverse` | Reverse a `POSTED` remittance; restores loan/installment state exactly | RecordkeeperAdmin |
| POST | `/participants/{id}/hardship-requests` | Create a hardship withdrawal request; computes gross-up fields; creates the approval chain | Participant |
| GET | `/participants/{id}/hardship-requests` | List a participant's hardship requests (paginated) | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| GET | `/hardship-requests/{id}` | Read a hardship request | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| POST | `/hardship-requests/{id}/documents` | Upload substantiation evidence; while `PENDING_DOCUMENTS` this returns the request to review | Participant |
| GET | `/hardship-requests/{id}/documents` | List uploaded documents | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| POST | `/hardship-requests/{id}/withdraw` | Participant withdraws an open hardship request | Participant |
| POST | `/hardship-requests/{id}/pay` | Pay an `APPROVED` hardship distribution; fires the suspension cascade | RecordkeeperAdmin |
| GET | `/hardship-requests/{id}/approval-tasks` | List approval tasks for a hardship subject, `step_order` ascending | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| GET | `/hardship-requests/{id}/suspension-record` | Read the suspension record created by this hardship (array of 0 or 1) | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| GET | `/approval-tasks/{id}` | Read an approval task | RecordkeeperAdmin, PlanSponsor, Auditor |
| POST | `/approval-tasks/{id}/decide` | Decide an approval step: `APPROVE`, `REJECT`, or `REQUEST_DOCS` (hardship subjects only) | PlanSponsor, RecordkeeperAdmin |
| GET | `/participants/{id}/tax-events` | List a participant's taxable events (paginated) | RecordkeeperAdmin, Auditor, Participant |
| GET | `/tax-events/{id}` | Read a tax event | RecordkeeperAdmin, Auditor, Participant |
| POST | `/tax-events/{id}/mark-reported` | Mark a `PENDING` tax event as reported on Form 1099-R | RecordkeeperAdmin |
| GET | `/participants/{id}/suspension-records` | List a participant's suspension records (paginated) | RecordkeeperAdmin, PlanSponsor, Auditor, Participant |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; advancing it evaluates missed-installment marking, cure-deadline expiry, and suspension expiry | RecordkeeperAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_PARTICIPANT_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_HARDSHIP_NOT_FOUND` | 404 |
| `ERR_REMITTANCE_NOT_FOUND` | 404 |
| `ERR_APPROVAL_TASK_NOT_FOUND` | 404 |
| `ERR_TAX_EVENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_TASK_ALREADY_DECIDED` | 409 |
| `ERR_APPROVAL_OUT_OF_ORDER` | 409 |
| `ERR_TAX_EVENT_ALREADY_REPORTED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SUSPENSION_OVERLAP` | 422 |
| `ERR_SUSPENSION_STILL_ACTIVE` | 422 |
| `ERR_REFINANCE_LOOKBACK_VIOLATION` | 422 |
| `ERR_REFINANCE_NOT_ALLOWED` | 422 |
| `ERR_EMPLOYMENT_NOT_ACTIVE` | 422 |
| `ERR_LOAN_ELIGIBILITY_LOCKED` | 422 |
| `ERR_LOAN_BELOW_MINIMUM` | 422 |
| `ERR_LOAN_LIMIT_EXCEEDED` | 422 |
| `ERR_MAX_LOANS_OUTSTANDING` | 422 |
| `ERR_UNSAFE_HARBOR_REASON` | 422 |
| `ERR_SUBSTANTIATION_INCOMPLETE` | 422 |
| `ERR_HARDSHIP_AMOUNT_EXCEEDS_NEED` | 422 |
| `ERR_INSUFFICIENT_VESTED_BALANCE` | 422 |
| `ERR_REMITTANCE_AMOUNT_MISMATCH` | 422 |
