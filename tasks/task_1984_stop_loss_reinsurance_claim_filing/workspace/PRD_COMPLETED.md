# Stop-Loss Reinsurance Claim Filing API — Product Requirements Document

## 1. Introduction

Self-funded employer health plans pay member medical and pharmacy claims out of their own assets, and stop-loss insurance is the financial backstop that keeps a handful of catastrophic claimants from destabilizing the plan's budget. Between the plan and the carrier sits a demanding operational workflow: per-member and plan-wide deductibles must be tracked continuously, claims must be accumulated against the correct contract under run-in and run-out windows, high-cost members must be reported to the carrier once their costs cross a contractual notice threshold, and reimbursement filings must be assembled, defended under carrier review, and reconciled against the wire that eventually arrives. Each of these steps carries real money, hard deadlines, and audit exposure.

This document specifies an API, mounted under `/stop-loss`, that operationalizes that workflow for third-party administrators, employer-side plan staff, and carrier-side reviewers and auditors. It governs the full stop-loss lifecycle — plan and contract setup, lasered member terms, claim adjudication and payment, specific and aggregate deductible accumulation, the fifty-percent notice obligation, filing assembly and submission, carrier review with disputes, reimbursement receipt and posting, eligibility audits with clawbacks, and the high-cost claimant forecasts that feed renewal underwriting. The consistency model is immediate: every claim mutation recomputes the affected accumulation ledgers before the response returns.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring their operational capacity. Six roles are recognized: `PlanAdministrator` (employer-side administrator covering plans, contracts, members, lasered terms, and audit resolution), `ClaimsExaminer` (TPA examiner covering claim intake, adjudication, payment, and reversal), `StopLossAnalyst` (TPA stop-loss analyst who builds and submits filings and resolves disputes), `CarrierReviewer` (carrier-side reviewer who reviews, disputes, approves, and denies filings), `PlanAccountant` (employer-side accountant who records and posts reimbursements), and `CarrierAuditor` (carrier-side auditor who opens audits and issues findings). A request missing either header, or carrying a role outside this list, is rejected with `ERR_UNAUTHENTICATED`. A well-authenticated request whose role is not permitted to invoke the endpoint is rejected with `ERR_FORBIDDEN`.

For each of the six roles — `PlanAdministrator`, `ClaimsExaminer`, `StopLossAnalyst`, `CarrierReviewer`, `PlanAccountant`, and `CarrierAuditor` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it (for example, the identifier of the user who submitted a filing is retained so that the segregation-of-duties rule in §2.11 can later compare it against the identifier of the user resolving an audit on that filing) but it is never compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every list endpoint sorts its results by `created_at` in ascending order unless otherwise specified; items sharing a `created_at` are ordered by insertion sequence. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

### 2.4. Common Resource Properties and Identity

Every top-level resource — plans, contracts, lasered terms, members, claims, accumulation rows, filings, reimbursements, forecasts, and audits — carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp is an ISO 8601 UTC value with three fractional digits recording when the resource was created. The `updated_at` timestamp, in the same format, is refreshed on every mutation. The `version` is a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation of the resource.

Filing line items are the single exception to this convention: a line item carries only `id` and `created_at`. Both `updated_at` and `version` are absent from line items.

### 2.5. Policy-Year Basis, Paid Basis, and the Accumulation Window

A stop-loss contract is written on one of two coverage bases, recorded at creation in `contract_basis` as either `POLICY_YEAR` or `PAID`. The basis decides which date makes a claim eligible to accumulate: under a `POLICY_YEAR` contract a claim belongs to the contract when its service date falls inside the accumulation window; under a `PAID` contract the same decision is made on the claim's paid date instead. The accumulation window itself runs from `run_in_days` before `policy_year_start` — the run-in tail that pulls earlier claims into the contract — up to but not including `run_out_days` after `policy_year_end` — the run-out tail that pulls later claims in. Both boundaries are half-open: the window includes its first instant and excludes its last.

Once the logical clock reaches a contract's `policy_year_end`, the contract expires. Expiry is a lifecycle label, not an accumulation barrier: the ledger rows of any contract that has been activated — `IN_FORCE`, `EXPIRED`, or `RENEWED` — continue to reflect their accumulation window, so a claim whose inclusion date falls inside the window still accumulates into the rows of an expired or renewed contract (the run-out tail exists precisely to pull such late claims in). Claims whose inclusion date falls outside the window never accumulate, and a `DRAFT` contract has no rows and accumulates nothing. A structural invariant protects the boundary between two consecutive contracts of the same plan: the run-in and run-out windows of two contracts must never both cover the same claim. This invariant is enforced at claim-payment time: every contract of the plan, whatever its lifecycle status, participates in the check, and a claim found inside the accumulation windows of two or more contracts is rejected with `ERR_CLAIM_WINDOW_AMBIGUITY` only when at least one of those contracts covers the claim through a run-in or run-out tail rather than through its bare policy-year window. Two contracts that cover the same claim solely through their core policy-year windows — for example, sibling contracts of the same plan written on different coverage bases over the same policy year — do not violate the invariant, and a claim covered by no contract's window at all pays without error and simply accumulates nowhere.

### 2.6. The Accumulation Ledgers

Accumulation against stop-loss deductibles is tracked in dedicated ledger rows rather than on the claims themselves. For each contract there is exactly one plan-wide row whose `scope` is `AGGREGATE` and whose `member_id` is null, plus one member-level row whose `scope` is `SPECIFIC` for every covered member. Each row carries `contract_id`, `member_id`, `scope`, the running `accumulated_cents` total, the derived `excess_cents` above the deductible, the `applicable_deductible_cents` currently in force for the row, and the `notice_triggered` flag. The flag is meaningful only on `SPECIFIC` rows; an `AGGREGATE` row's `notice_triggered` is always false. These rows are recomputed immediately on every claim payment or reversal that falls in the contract's window, whenever a lasered term is created or rescinded, when an audit resolution applies a clawback (§3.8), and — for the aggregate row — when a reimbursement is posted.

Two ledger rules are pinned system-wide. First, the per-member specific sweep always completes before the plan-wide aggregate sweep begins, so the aggregate computation always sees final per-member amounts even though the two appear to depend on one another. Second, each member's contribution to the aggregate is capped at the contract's `aggregating_specific_deductible_cents` when one is present, and otherwise at the contract's `specific_deductible_cents` — the mirroring rule, so named because no member may contribute more toward the aggregate deductible than the per-member deductible the contract mirrors. Caps are applied to each member as integer cents first and only then summed; there is no rounding after the summation.

### 2.7. Monetary Precision: Integer Cents and Half-Up Rounding

All monetary amounts in the API are represented as integer cents — deductibles, billed, allowed, and paid amounts, accumulation totals, filing amounts, reimbursements, forecast projections, and audit adjustments alike. The accumulation and filing sweeps perform no rounding at all: every figure they produce is an exact integer-cent value. The high-cost claimant forecast is the one computation that rounds: its intermediate credibility factor is carried to two decimal places (rounded half-up), and its final projected figures are rounded half-up to integer cents (and, for the projected member count, half-up to a whole member).

### 2.8. Optimistic Concurrency Control on Contract Terms

Two write operations are guarded by optimistic concurrency control against the contract they reference: creating a stop-loss filing, and creating a lasered member term. Each of these requests must carry `expected_contract_version`, a non-optional field holding the contract `version` the client last observed. If the value does not match the contract's current `version` — because activation, renewal, another laser creation, or another filing creation has advanced it since the client last read the contract — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents an analyst from building a filing, or an administrator from pricing a laser, against deductible terms they have not observed. Endpoints other than these two do not take a version field.

### 2.9. Validation Order and Nested Resource Resolution

Every request is validated in a fixed order. Authentication comes first: missing or malformed `X-User-Role` or `X-User-ID` headers fail with `ERR_UNAUTHENTICATED` (HTTP 401). Authorization follows: a role not permitted to invoke the endpoint fails with `ERR_FORBIDDEN` (HTTP 403). Existence comes third: every path identifier and every body foreign key must resolve to an existing entity, failing with `ERR_NOT_FOUND` (HTTP 404); for paths containing multiple identifiers, resolution proceeds left to right and rejects at the first identifier that does not exist. State eligibility comes fourth: the target entity's current state must permit the requested transition, failing with `ERR_INVALID_STATE` (HTTP 409). Business rules come last, applied in the order stated alongside each workflow in §3; when several business checks share one endpoint, the check whose category appears earlier in this document is evaluated first, so an earlier failure is never masked by a later one. Independently of this chain, a payload missing a required field or containing a malformed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A request whose path matches no route, or whose HTTP method the matched route does not support, is likewise rejected in the standard error envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.10. The Logical Clock and Contract Expiry

All evaluations of "the current instant" in this system — activation eligibility, accumulation windows, filing deadlines, forecast trailing periods, the `submitted_at` timestamp, and the forecast's `computed_at` timestamp — read a server-side logical clock, never the wall clock. Server-emitted bookkeeping timestamps — `created_at`, `updated_at`, and `meta.api_request_timestamp` — record real wall-clock time, not the logical clock. At startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. An administrator-only, test-driving capability sets the logical clock to any supplied `to_iso8601` instant, whether earlier or later than the current reading. When the new instant reaches or passes an `IN_FORCE` contract's `policy_year_end`, the contract's lifecycle transition from `IN_FORCE` to `EXPIRED` fires automatically as part of the same operation. Datetime values supplied in request payloads are normalized to UTC and echoed back in whole-second `YYYY-MM-DDTHH:MM:SSZ` form.

### 2.11. Segregation of Duties

Audit resolution is deliberately separated from filing submission. The operator who resolves an audit must not be the operator who submitted the filing under audit, compared by `X-User-ID`. A resolution attempted by the same operator identifier that submitted the underlying filing is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Establishing the Plan, Membership, and Contract Terms

A `PlanAdministrator` opens the book of business by creating a plan with its `plan_name` — the legal name of the self-funded employer health plan — and the sponsor's `sponsor_tax_id`. A plan's `status` begins as `ACTIVE`; the plan lifecycle also defines a `TERMINATED` state.

Members are enrolled under a plan through a payload carrying the `plan_id`, the TPA-assigned `member_external_id`, the member's `date_of_birth` as an ISO calendar date, and the `coverage_start` as an ISO 8601 datetime, which is inclusive. The optional `coverage_end`, likewise a datetime, is exclusive and stays null while coverage remains active; when both coverage dates are present, `coverage_start` must be strictly earlier than `coverage_end`, or enrollment fails with `ERR_INVALID_DATE_RANGE`. A new member starts with `status` set to `ACTIVE` and `notice_status` set to `NONE`. Enrollment has one ledger side effect: for each `IN_FORCE` contract that already exists for the plan (there may be one per `contract_basis`, per §3.2), the member's `SPECIFIC` accumulation row is materialized immediately as part of enrollment.

When coverage ends mid-book, a `PlanAdministrator` terminates the member, moving `status` from `ACTIVE` to the terminal `TERMINATED` state and recording the payload's `coverage_end` on the member. Termination is permitted only from `ACTIVE`. The payload's `coverage_end` is required and is recorded as supplied, without re-validating it against `coverage_start`. Termination touches nothing else: accumulation rows are left alone, and the terminated member's paid claims continue to accumulate and to contribute toward aggregate rows.

Contract drafting is also a `PlanAdministrator` task. The payload names the insured plan through `plan_id` and fixes the policy year with `policy_year_start` (inclusive) and `policy_year_end` (exclusive); the end must be strictly after the start, else creation fails with `ERR_INVALID_REQUEST`. Financial terms include the per-member `specific_deductible_cents` and the plan-wide `aggregate_deductible_cents`, plus the optional `aggregating_specific_deductible_cents` that caps per-member contributions toward the aggregate; all three accept any integer at creation — their zero-or-greater bound is enforced later, as an activation precondition (§3.2). Administrative terms include `filing_deadline_days` (at least 1), the `notice_threshold_pct` fraction that arms the fifty-percent notice obligation (greater than zero and at most one; canonically one-half), and the `run_in_days` and `run_out_days` tails (each zero or greater) described in §2.5; violations of these administrative-term bounds are rejected at creation with `ERR_INVALID_REQUEST`. The `contract_basis` chosen here — `POLICY_YEAR` or `PAID` — governs every accumulation decision for the life of the contract. A newly drafted contract sits in `DRAFT` and insures nothing yet.

### 3.2. Contract Activation, Expiry, and Renewal

Activation moves a contract from `DRAFT` to `IN_FORCE` and is the moment coverage actually binds. A `PlanAdministrator` may activate a contract only when four preconditions hold together: the current logical instant falls within the policy year — on or after `policy_year_start` and strictly before `policy_year_end`; both `specific_deductible_cents` and `aggregate_deductible_cents` are zero or greater; when an `aggregating_specific_deductible_cents` value is present it is at least as large as `specific_deductible_cents`; and no other contract for the same plan on the same `contract_basis` is already `IN_FORCE` — a `POLICY_YEAR` contract and a `PAID` contract for the same plan may be in force simultaneously. A request that fails any activation precondition — like any transition attempted from a state that does not permit it — is rejected with `ERR_INVALID_STATE`.

Activation materializes the ledgers described in §2.6. The system creates the single `AGGREGATE` accumulation row with `member_id` null and `accumulated_cents` at zero, and creates one `SPECIFIC` accumulation row for every member of the plan whose `status` is `ACTIVE` at that moment. The contract's `version` increments by one as part of the same mutation.

Expiry requires no action: when the logical clock reaches `policy_year_end`, the contract moves from `IN_FORCE` to `EXPIRED`. Per §2.5, expiry does not close the ledgers: claims whose inclusion date falls inside the accumulation window continue to accumulate into an `EXPIRED` contract's rows.

Renewal carries the book forward. A contract in `EXPIRED` — and only in `EXPIRED` — may be renewed by a `PlanAdministrator`, moving it to the terminal `RENEWED` state while the system creates a successor contract in `DRAFT` carrying the renewed terms. The renewal payload supplies `new_policy_year_start`, `new_policy_year_end`, `specific_deductible_cents`, `aggregate_deductible_cents`, the optional `aggregating_specific_deductible_cents`, `filing_deadline_days`, `notice_threshold_pct`, `run_in_days`, and `run_out_days`. The successor inherits the expiring contract's `plan_id` and `contract_basis`; the payload does not restate them. Continuity is mandatory: `new_policy_year_start` must equal the expiring contract's `policy_year_end` exactly, so the new policy year begins precisely where the old one ended; a continuity violation is rejected with `ERR_INVALID_STATE`. The renewal increments the expiring contract's `version` by one and responds with the newly created successor contract at 201.

### 3.3. Lasering: Member-Specific Deductible Overrides

Carriers manage known high-cost members by lasering them — raising that one member's specific deductible above the contract's base. A `PlanAdministrator` creates a lasered term with `contract_id`, `member_id`, the `lasered_specific_deductible_cents` override, and the applicability window from `effective_from` (inclusive) to `effective_to` (exclusive). A lasered term may be created against a contract in any status, including `DRAFT`. Creation runs its checks in a fixed order. First the member must belong to the plan the contract insures, else `ERR_CROSS_PLAN_REFERENCE`. Next the window must be well-formed, with `effective_from` strictly earlier than `effective_to`, else `ERR_INVALID_DATE_RANGE`. Then the laser-specific rules: `lasered_specific_deductible_cents` must be strictly greater than the contract's `specific_deductible_cents`, and no two `ACTIVE` lasers for the same contract and member may have overlapping half-open effective windows — both violations surface as `ERR_LASER_CONFLICT`. Finally the optimistic-concurrency check of §2.8 applies, so a stale `expected_contract_version` is rejected with `ERR_STALE_VERSION` only after the earlier checks have passed.

A laser takes effect in the ledger at once: creation recalculates the `SPECIFIC` accumulation row for that contract and member so that `applicable_deductible_cents` reflects the lasered override, and it increments the contract's `version` by one. The term begins in `ACTIVE`. The effective-window bounds constrain only the creation-time overlap check; they do not gate which claims the override applies to — whenever at least one `ACTIVE` laser exists for the contract and member, the one with the latest `effective_from` governs the row's applicable deductible. Rescinding a laser moves it from `ACTIVE` to `RESCINDED` and recalculates the same accumulation row with `applicable_deductible_cents` falling back to the override of any remaining `ACTIVE` laser for that contract and member, or to the contract's base specific deductible when none remains.

### 3.4. Claim Adjudication, Payment, Reversal, and the Accumulation Sweep

Claims enter through a `ClaimsExaminer`, who submits the `plan_id`, the `member_id`, the `service_date` (an ISO 8601 datetime, conventionally at UTC midnight, stored as supplied per the normalization rule of §2.10), the `billed_amount_cents` (zero or greater), and the `claim_type` — one of `MEDICAL` or `RX`. Two intake checks run in a fixed order: first the member must belong to the plan named on the claim, else `ERR_CROSS_PLAN_REFERENCE`; then the temporal check, under which the service date must not fall after the paid date, else `ERR_INVALID_DATE_RANGE` — since `paid_date` is still null at intake, the temporal check is vacuous at creation and is actually enforced at payment time. A new claim starts in `SUBMITTED`, with `allowed_amount_cents`, `paid_amount_cents`, and `paid_date` all remaining null until adjudication and payment fill them.

Adjudication moves the claim from `SUBMITTED` to `ADJUDICATED` and records the plan-allowed amount: the payload's `allowed_amount_cents` may not exceed `billed_amount_cents` (a violation is `ERR_AMOUNT_OUT_OF_RANGE`) and must be zero or greater (a negative value is `ERR_INVALID_REQUEST`). Payment then moves the claim from `ADJUDICATED` to `PAID`, recording `paid_amount_cents` and the `paid_date` under the same bounds against `allowed_amount_cents`. Payment's business checks run in a fixed order: first the temporal check (the service date must not fall after `paid_date`, else `ERR_INVALID_DATE_RANGE`), then the window-integrity check of §2.5 (a claim covered by the run-in or run-out windows of two contracts at once is rejected with `ERR_CLAIM_WINDOW_AMBIGUITY`, while a claim covered by no contract's window pays normally and accumulates nowhere), and finally the amount bound (`paid_amount_cents` may not exceed `allowed_amount_cents`, else `ERR_AMOUNT_OUT_OF_RANGE`).

The moment a claim is paid, the specific sweep runs for every activated contract of the claim's plan — `IN_FORCE`, `EXPIRED`, or `RENEWED`, never `DRAFT` — whose accumulation window covers it. The member's specific row sums the `paid_amount_cents` of all that member's claims in `PAID` status whose inclusion date — `service_date` under a `POLICY_YEAR` contract, `paid_date` under a `PAID` contract — falls within the window from `run_in_days` before `policy_year_start` up to but not including `run_out_days` after `policy_year_end`. Claims are considered in chronological order, by service date and then creation timestamp under a policy-year basis, or by paid date and then creation timestamp under a paid basis; the resulting `accumulated_cents` is the straight sum of those paid amounts. The `applicable_deductible_cents` for the row is the override of the member's governing `ACTIVE` laser under the contract when one exists — per §3.3, the laser with the latest `effective_from`, irrespective of how its window sits against any particular claim — and the contract's `specific_deductible_cents` otherwise. The row's `excess_cents` is the amount by which the accumulated total exceeds the applicable deductible, or zero when it does not.

Immediately after the specific sweep — never before, per the pinned order of §2.6 — the aggregate sweep runs. Each member's contribution is the lesser of that member's total eligible paid amount and the cap (`aggregating_specific_deductible_cents` when present, otherwise `specific_deductible_cents`); the capped integer-cent contributions are then summed into the aggregate row's `accumulated_cents`. The aggregate `excess_cents` is the amount by which that sum exceeds `aggregate_deductible_cents`, or zero. Reversal removes the claim's contribution by recomputing both sweeps without it.

Payment also arms the fifty-percent notice obligation. On every recompute of a `SPECIFIC` row, the `notice_triggered` flag compares `accumulated_cents` against the `notice_threshold_pct` fraction of `applicable_deductible_cents`; the boundary is inclusive, so a member whose accumulation equals exactly the threshold fraction of the deductible has triggered the obligation. The comparison is evaluated in rational arithmetic, both sides multiplied through so the test lands on integer cents and no floating-point approximation can blur the boundary. When the flag flips from false to true, the member's `notice_status` moves from `NONE` to `NOTICE_PENDING`. A `PlanAdministrator` then files the notice with the carrier — permitted only while an `IN_FORCE` contract exists for the member's plan — moving `notice_status` from `NOTICE_PENDING` to `NOTICE_FILED`. An attempt from any other `notice_status`, or while no `IN_FORCE` contract exists for the plan, fails with `ERR_INVALID_STATE`.

Reversal is the unwind path, moving a claim from `PAID` to `REVERSED`. A claim cannot be reversed while it appears as a line item under any filing whose status is `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, or `PAID` (a blocked reversal fails with `ERR_INVALID_STATE`); filings still in `DRAFT` or sitting in `DISPUTED` do not block the reversal. Reversal recomputes the accumulation sweeps but does not re-run any filing sweep; a `DRAFT` filing that still lists the reversed claim keeps its stored figures and is caught by the submission state gate instead. When a reversal pulls the member's accumulation back below the notice threshold and `notice_triggered` flips from true to false, a member still in `NOTICE_PENDING` is reset to `NONE` — but a member whose notice already reached `NOTICE_FILED` stays filed.

### 3.5. Assembling and Submitting a Stop-Loss Filing

A `StopLossAnalyst` assembles a filing against a contract by supplying `contract_id`, the `filing_scope` — `SPECIFIC` for a per-member filing or `AGGREGATE` for a whole-plan filing — the `member_id` (required on a `SPECIFIC` filing and null on an `AGGREGATE` one), the `claim_ids` to attach, and the OCC field `expected_contract_version` described in §2.8. The new filing starts in `DRAFT`. The member named on the filing must belong to the plan the contract insures (`ERR_CROSS_PLAN_REFERENCE`), and that cross-plan check runs before the stale-version check. The attached claims carry no scoping checks of their own: each `claim_ids` entry must only resolve to an existing claim (else `ERR_NOT_FOUND`), the claims need not belong to the filing's member or to the contract's plan and need not be in `PAID` status, and a duplicated identifier produces a duplicate line item. A filing may be assembled against a contract in any status, including `DRAFT`. Creation builds one filing line item per claim identifier, each line recording its `filing_id`, its `claim_id`, a computed `eligible_excess_cents`, and a `disputed` flag that starts false; per §2.4, line items carry `id` and `created_at` only. Creating the filing also increments the contract's `version` by one, so a laser created afterward against a previously observed contract version will fail its concurrency check.

The filing's `requested_amount_cents` comes out of the filing sweep, which runs over the attached claims in `PAID` status ordered by service date and then creation timestamp. The sweep maintains a running total initialized to zero and a requested total initialized to zero; the applicable deductible — the lasered or base specific deductible on a member-level filing, the aggregate deductible on a plan-level filing — serves only as the comparison threshold. For each line, the running total before the claim is remembered as the prior position, and the claim's `paid_amount_cents` is added to the running total. The line's `eligible_excess_cents` is then the excess of the new running total over the applicable deductible (zero when it does not exceed it) minus the excess the prior position already had over the applicable deductible (again zero when it did not) — that is, `max(0, running − deductible) − max(0, prior − deductible)` — so a claim that begins below the deductible contributes only its portion above it, while a claim that starts with the running total already above the deductible contributes its full paid amount. Lines whose claim is not in `PAID` status sit at `eligible_excess_cents` zero. Each line's eligible excess feeds the requested total, and the final requested total becomes `requested_amount_cents`. The sweep re-runs whenever the line items of a `DRAFT` filing change, and again when a dispute is resolved, keeping `eligible_excess_cents` and `requested_amount_cents` in step; since it runs only at creation and at dispute resolution, a claim that pays after the filing was assembled does not raise the filing's stored figures unless a later dispute resolution re-runs the sweep. Because creation itself runs the sweep as a further mutation, a filing created over already-paid claims yielding a positive requested amount is returned with `version` 2. Two filing fields stay null until their moment: `submitted_at` while the filing is in `DRAFT`, and `approved_amount_cents` until the filing reaches `APPROVED` or `PAID`.

Submission moves the filing from `DRAFT` to `SUBMITTED` and evaluates its gates in a fixed order, so an earlier gate is never masked by a later one. The state gate comes first: the filing must be in `DRAFT`, at least one line item must exist, and every line's claim must be in `PAID` status — violations surface as `ERR_INVALID_STATE`. Next comes the notice gate: a `SPECIFIC` filing may not be submitted for a member whose `notice_status` is still `NOTICE_PENDING`, because the fifty-percent notice must reach the carrier before any specific reimbursement filing; the rejection is `ERR_NOTICE_OUTSTANDING`. Then the fiscal gate: `requested_amount_cents` must be greater than zero, else `ERR_AMOUNT_OUT_OF_RANGE`. Last comes the deadline gate: the current logical instant must be on or before `policy_year_end` plus `filing_deadline_days`, with the final day itself still admissible; a later submission is rejected with `ERR_FILING_DEADLINE_PASSED`. A successful submission stamps `submitted_at` with the current logical instant and increments the filing's `version` by one.

### 3.6. Carrier Review, Disputes, and Settlement Decisions

Carrier review opens when a `CarrierReviewer` begins review, moving the filing from `SUBMITTED` to `UNDER_REVIEW`; the transition carries no side effects. From `UNDER_REVIEW` the reviewer has three exits.

The dispute path challenges individual charges. The reviewer supplies `disputed_line_item_ids`, and the system sets `disputed` to true on each listed line as the filing moves from `UNDER_REVIEW` to `DISPUTED`. Each listed identifier must resolve to a line item of this filing, else `ERR_NOT_FOUND`; the list may be empty, in which case no line is flagged but the filing still moves to `DISPUTED`. A `StopLossAnalyst` then works the dispute and resolves it: the request carries no line selection — every `disputed` flag on the filing's line items is cleared, `requested_amount_cents` is recomputed through the filing sweep, and the filing returns from `DISPUTED` to `UNDER_REVIEW`.

The approval path settles the claim. Approval is permitted only from `UNDER_REVIEW` and only while no line item under the filing still has `disputed` set to true; either violation is rejected with `ERR_INVALID_STATE`. The reviewer supplies `approved_amount_cents`, which must be zero or greater and may not exceed `requested_amount_cents` — an out-of-range value, including a negative one, is rejected with `ERR_AMOUNT_OUT_OF_RANGE` — and the value is recorded as the carrier-approved amount while the filing moves to `APPROVED`. The denial path is the reviewer's other terminal exit, moving the filing from `UNDER_REVIEW` to `DENIED` with no side effects.

A filing's terminal states are `PAID` and `DENIED`. `PAID` is never reached by a direct call: it is the system transition that fires when a reimbursement against the filing is posted, as §3.7 describes.

### 3.7. Reimbursement and Posting to the Plan Ledger

Once a filing is `APPROVED`, the carrier wires the settlement and a `PlanAccountant` records the receipt. The receipt payload carries the `filing_id`, the `received_amount_cents` actually wired (zero or greater), and the `received_at` UTC timestamp. Recording is not gated on the filing's status — a receipt may be recorded against a filing in any status and simply waits; the `APPROVED` requirement is enforced only at posting. A recorded reimbursement starts in `RECEIVED`.

Posting is the general-ledger moment and is deliberately strict. Moving a reimbursement from `RECEIVED` to `POSTED` requires the filing to still be in `APPROVED` — a filing in any other state is rejected with `ERR_INVALID_STATE` — and an exact match between `received_amount_cents` and the filing's `approved_amount_cents` — a short payment or an overpayment cannot post at all and is rejected with `ERR_REIMBURSEMENT_MISMATCH`. The filing-state check is evaluated before the amount match, so a stale filing state is never masked by a mismatched amount. Posting fires two side effects as one mutation: the filing transitions from `APPROVED` to `PAID`, and the plan's `AGGREGATE` accumulation row is recalculated to net the reimbursed excess out of the plan's unrecovered exposure. Concretely, the aggregate row's `accumulated_cents` is left unchanged by posting, and its `excess_cents` becomes `max(0, accumulated_cents − aggregate_deductible_cents − P)`, where `P` is the total `received_amount_cents` of all `POSTED` reimbursements recorded against filings of that contract.

### 3.8. Eligibility Audits and Clawbacks

A `CarrierAuditor` may open an eligibility audit on a filing at any point by supplying the `filing_id` and a free-text `reason`; the audit begins in `OPENED`. Issuing findings moves it from `OPENED` to `FINDINGS_ISSUED` without side effects.

Resolution belongs to the employer side: a `PlanAdministrator` resolves an audit in `FINDINGS_ISSUED`, moving it to the terminal `RESOLVED` state and recording the `adjustment_cents` from the payload. Segregation of duties, stated in §2.11, is enforced here — the resolving operator's `X-User-ID` must differ from the identifier that submitted the underlying filing, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`; on a filing that was never submitted there is no submitting operator to compare against, and the check does not fire. A negative adjustment is a clawback from the plan: when the filing has an approved amount recorded, its `approved_amount_cents` is reduced by the absolute value of the adjustment, and the affected accumulation rows — the filing member's `SPECIFIC` row for a `SPECIFIC` filing, and always the contract's `AGGREGATE` row — are recomputed. A zero or positive adjustment is simply recorded on the audit and leaves the filing untouched.

### 3.9. Renewal Underwriting and High-Cost Claimant Forecasting

Renewal pricing rests on the high-cost claimant forecast, which either a `PlanAdministrator` or a `StopLossAnalyst` may compute by supplying the `plan_id`, the `forecast_basis` — `PURE_EXPERIENCE` or `CREDIBILITY_WEIGHTED` — and the `next_year_specific_deductible_cents` under quote (zero or greater, else `ERR_INVALID_REQUEST`). The projection set is the plan's members whose `status` is `ACTIVE` and who have at least one `PAID` claim whose `paid_date` falls within the trailing twelve months — the half-open interval from 365 days before the computation instant up to but not including that instant; each such member's trailing paid total is the sum of those paid amounts, and the member count is the size of this projection set. The forecast row records the computed `projected_excess_cents` and `projected_member_count` together with the server's `computed_at` timestamp, which stamps the current logical instant.

Under `PURE_EXPERIENCE`, only the plan's own trailing claims speak. The `projected_excess_cents` is the sum over projection-set members of the amount by which each member's trailing paid total exceeds the next-year specific deductible, counting only members whose total exceeds it at all. The `projected_member_count` is the number of members whose trailing paid total reaches at least the next-year specific deductible.

Under `CREDIBILITY_WEIGHTED`, the plan's experience is blended with the manual rate through a credibility factor z: the member count divided by 500 — the membership size at which experience earns full credibility — capped at 1.0 and carried to two decimal places, rounded half-up. The manual side prices excess at 1,200,000 cents per member — a manual rate of $12,000 per member — so the manual-rate excess is the member count multiplied by that per-member rate. The projected excess is then z multiplied by the pure-experience projection, plus one-minus-z multiplied by the manual-rate excess, rounded half-up to integer cents. The projected count blends the same way: z multiplied by the pure-experience count, plus one-minus-z multiplied by the member count multiplied by the manual hit rate of 0.04 — four members per hundred — with the result rounded half-up to a whole member.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; this includes contract renewal, which creates the successor contract, and forecast computation, which creates the forecast row. Operations that modify an existing resource return `200 OK`. Readers should reconstruct request and response payloads from the workflows in §3; the table below is an index, not a schema. Where a list endpoint is marked filterable, the supported exact-match query parameters are: contracts — `plan_id`; members — `plan_id`; lasered-terms — `contract_id`, `member_id`; claims — `plan_id`, `member_id`, `status`; accumulations — `contract_id`, `member_id`, `scope`; filings — `contract_id`, `member_id`, `status`; the flat filing-line-items list — `filing_id`, `claim_id`; reimbursements — `filing_id`; forecasts — `plan_id`; audits — `filing_id`. The per-filing line-items route is paginated but takes no filters beyond its path.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/stop-loss/plans` | Create a self-funded plan | PlanAdministrator |
| GET | `/stop-loss/plans/{id}` | Fetch a plan | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/plans` | List plans (paginated) | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| POST | `/stop-loss/contracts` | Create a stop-loss contract in DRAFT | PlanAdministrator |
| GET | `/stop-loss/contracts/{id}` | Fetch a contract | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/contracts` | List contracts (paginated, filterable by plan_id) | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| POST | `/stop-loss/contracts/{id}/activate` | Activate: DRAFT to IN_FORCE; materializes accumulation rows | PlanAdministrator |
| POST | `/stop-loss/contracts/{id}/renew` | Renew: EXPIRED to RENEWED; creates successor DRAFT contract | PlanAdministrator |
| POST | `/stop-loss/members` | Enroll a member | PlanAdministrator |
| GET | `/stop-loss/members/{id}` | Fetch a member | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/members` | List members (paginated, filterable by plan_id) | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| POST | `/stop-loss/members/{id}/terminate` | Terminate coverage: ACTIVE to TERMINATED | PlanAdministrator |
| POST | `/stop-loss/members/{id}/file-notice` | Record the fifty-percent notice filing to the carrier | PlanAdministrator |
| POST | `/stop-loss/lasered-terms` | Create a lasered specific-deductible override (OCC-guarded on contract) | PlanAdministrator |
| POST | `/stop-loss/lasered-terms/{id}/rescind` | Rescind: ACTIVE to RESCINDED; accumulation falls back to any remaining laser or the base deductible | PlanAdministrator |
| GET | `/stop-loss/lasered-terms` | List lasered terms (paginated, filterable) | PlanAdministrator, StopLossAnalyst, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/lasered-terms/{id}` | Fetch a single lasered term | PlanAdministrator, StopLossAnalyst, CarrierReviewer, CarrierAuditor |
| POST | `/stop-loss/claims` | Submit a claim | ClaimsExaminer |
| GET | `/stop-loss/claims/{id}` | Fetch a claim | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/claims` | List claims (paginated, filterable) | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| POST | `/stop-loss/claims/{id}/adjudicate` | Adjudicate: SUBMITTED to ADJUDICATED | ClaimsExaminer |
| POST | `/stop-loss/claims/{id}/pay` | Pay: ADJUDICATED to PAID; accumulations recalculated | ClaimsExaminer |
| POST | `/stop-loss/claims/{id}/reverse` | Reverse: PAID to REVERSED; accumulations recomputed | ClaimsExaminer |
| GET | `/stop-loss/accumulations` | List accumulation rows (paginated, filterable) | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/accumulations/{id}` | Fetch one accumulation row | PlanAdministrator, StopLossAnalyst, ClaimsExaminer, PlanAccountant, CarrierReviewer, CarrierAuditor |
| POST | `/stop-loss/filings` | Create a DRAFT filing with line items (OCC-guarded on contract) | StopLossAnalyst |
| GET | `/stop-loss/filings/{id}` | Fetch a filing | PlanAdministrator, StopLossAnalyst, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/filings` | List filings (paginated, filterable) | PlanAdministrator, StopLossAnalyst, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/filings/{id}/line-items` | List line items of a filing | PlanAdministrator, StopLossAnalyst, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/filing-line-items` | Filtered list of filing line items (paginated) | PlanAdministrator, StopLossAnalyst, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/filing-line-items/{id}` | Fetch a single filing line item | PlanAdministrator, StopLossAnalyst, PlanAccountant, CarrierReviewer, CarrierAuditor |
| POST | `/stop-loss/filings/{id}/submit` | Submit: DRAFT to SUBMITTED (deadline and notice gates) | StopLossAnalyst |
| POST | `/stop-loss/filings/{id}/begin-review` | Begin review: SUBMITTED to UNDER_REVIEW | CarrierReviewer |
| POST | `/stop-loss/filings/{id}/dispute` | Dispute: UNDER_REVIEW to DISPUTED; flags line items | CarrierReviewer |
| POST | `/stop-loss/filings/{id}/resolve-dispute` | Resolve dispute: DISPUTED to UNDER_REVIEW; clears flags and recomputes | StopLossAnalyst |
| POST | `/stop-loss/filings/{id}/approve` | Approve: UNDER_REVIEW to APPROVED | CarrierReviewer |
| POST | `/stop-loss/filings/{id}/deny` | Deny: UNDER_REVIEW to DENIED | CarrierReviewer |
| POST | `/stop-loss/reimbursements` | Record a carrier wire against a filing (posting requires APPROVED) | PlanAccountant |
| GET | `/stop-loss/reimbursements/{id}` | Fetch a reimbursement | PlanAdministrator, StopLossAnalyst, PlanAccountant, CarrierReviewer, CarrierAuditor |
| GET | `/stop-loss/reimbursements` | List reimbursements (paginated, filterable by filing_id) | PlanAdministrator, StopLossAnalyst, PlanAccountant, CarrierReviewer, CarrierAuditor |
| POST | `/stop-loss/reimbursements/{id}/post` | Post: RECEIVED to POSTED; posts to the plan ledger | PlanAccountant |
| POST | `/stop-loss/forecasts` | Compute a high-cost claimant forecast under the requested basis | PlanAdministrator, StopLossAnalyst |
| GET | `/stop-loss/forecasts/{id}` | Fetch a forecast | PlanAdministrator, StopLossAnalyst, CarrierReviewer |
| GET | `/stop-loss/forecasts` | List forecasts (paginated, filterable by plan_id) | PlanAdministrator, StopLossAnalyst, CarrierReviewer |
| POST | `/stop-loss/audits` | Open an eligibility audit on a filing | CarrierAuditor |
| GET | `/stop-loss/audits/{id}` | Fetch an audit | PlanAdministrator, StopLossAnalyst, PlanAccountant, CarrierAuditor |
| GET | `/stop-loss/audits` | List audits (paginated, filterable by filing_id) | PlanAdministrator, StopLossAnalyst, PlanAccountant, CarrierAuditor |
| POST | `/stop-loss/audits/{id}/issue-findings` | Issue findings: OPENED to FINDINGS_ISSUED | CarrierAuditor |
| POST | `/stop-loss/audits/{id}/resolve` | Resolve: FINDINGS_ISSUED to RESOLVED; segregation of duties enforced | PlanAdministrator |
| POST | `/stop-loss/_clock/set_current_utc` | Test-driving endpoint: set the server's logical clock | PlanAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CROSS_PLAN_REFERENCE` | 422 Unprocessable Entity |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_AMBIGUITY` | 422 Unprocessable Entity |
| `ERR_NOTICE_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_LASER_CONFLICT` | 422 Unprocessable Entity |
| `ERR_AMOUNT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_FILING_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_REIMBURSEMENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
