# Bankruptcy Filing API — Product Requirements Document

## 1. Introduction

Personal bankruptcy is one of the most consequential financial proceedings a household can undertake, and the federal Bankruptcy Code orchestrates an unusually rich choreography of court officers, court-appointed administrators, debtors, and creditors around a single case file. This document specifies the requirements for a system that mediates that choreography for Chapter 7 (liquidation) and Chapter 13 (reorganization) cases. The API must shepherd a case from initial draft, through the means-test gate that decides which chapter the debtor is even permitted to pursue, through the 341 creditors' meeting at which claims are reviewed, and ultimately to either discharge, dismissal, or pre-filing withdrawal.

Two cross-cutting concerns dominate the design. The first is the **automatic stay** — the moment a case is filed, every creditor's right to attempt collection is immediately suspended for the duration of the bankruptcy, and the system must enforce this regardless of how creditors approach the API. The second is **fiscal feasibility under Chapter 13** — a reorganization plan must be funded sufficiently to satisfy the debtor's disposable monthly income obligation over a statutorily determined number of months, and only a judge may confirm a plan that meets that floor. The remaining narrative weaves these two concerns through the lifecycle of every supporting entity — claims, schedules, trustee payments, and creditor collection attempts.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and structural contracts that apply uniformly across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares the operational capacity in which they are acting. The system recognizes exactly four roles: `Debtor`, `Trustee`, `Creditor`, and `Judge`. A request missing the role header, or supplying any value outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted for the requested operation under the RBAC matrix is rejected with `ERR_FORBIDDEN` (HTTP 403).

The interpretation of `X-User-ID` is role-specific and central to ownership enforcement. When `X-User-Role` is `Debtor`, the `X-User-ID` value is the `id` of the acting `Debtor`; ownership checks on any case-scoped resource compare `Case.debtor_id` to `X-User-ID`, so debtors may only act on their own cases, schedules, plans, and case-scoped resources. When `X-User-Role` is `Creditor`, the `X-User-ID` value is the `id` of the acting `Creditor`; ownership checks compare `Claim.creditor_id` and `CollectionAction.creditor_id` to `X-User-ID`, so creditors may only file claims and attempt collection actions in their own name. When `X-User-Role` is `Trustee`, the `X-User-ID` value is an opaque court-appointed-administrator identifier not tied to any persisted entity — the server may record it for audit but does not compare it to any entity's `id`; trustees act on cases at large rather than on entities they own. When `X-User-Role` is `Judge`, the `X-User-ID` value is likewise an opaque court-officer identifier not tied to any persisted entity, used for the two judicial actions of plan confirmation and discharge.

The four roles are strictly segregated: a single principal must not simultaneously hold debtor and creditor capacity, nor can a trustee assume judicial authority. This segregation is enforced operation-by-operation through the per-endpoint role list in §4.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned and defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; values outside this range are rejected as malformed. The `offset` parameter is the number of items to skip from the start and defaults to 0. Unless an endpoint specifies otherwise, list responses are sorted by the resource's `created_at` timestamp in ascending order.

For every list response, the `meta` envelope carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the unfiltered total count of matching rows and `has_more` is `true` whenever further items exist beyond `offset + limit`.

### 2.4. Common Resource Properties

Each top-level entity carries a server-minted `id` formatted as a UUID with no type prefix and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. The mutable entities — `Debtor`, `Case`, `Creditor`, `Claim`, and `Plan` — additionally carry `updated_at` (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and `version` (an integer initialized to 1 and incremented by exactly one on every mutation). Mutations that are server-driven cascades (for example, an automatic claim transition triggered by conducting the 341 meeting) refresh `updated_at` and bump `version` on every affected row in the same way that a direct mutation would.

Four append-only or snapshot entities omit the mutable bookkeeping. `Schedule` rows are immutable snapshots written once and superseded by later snapshots rather than mutated in place, so each `Schedule` carries only `id` and `created_at`; `updated_at` and `version` are absent. `MeansTestResult` rows are immutable computation snapshots and likewise carry only `id` and `created_at`. `TrusteePayment` rows are append-only ledger entries and carry only `id` and `created_at`. `CollectionAction` rows are immutable attempt logs born in their final outcome and carry only `id` and `created_at` as their bookkeeping fields.

### 2.5. Nested Resource Validation and Lookup Order

The URL hierarchy is `/cases/{case_id}/...` for case-scoped resources, and `/cases/{case_id}/plans/{plan_id}/...` for plan-scoped resources beneath them. When a request targets a nested path, the server resolves each path-segment identifier left-to-right and rejects the request with `ERR_NOT_FOUND` against the first identifier that does not resolve to an existing row. A plan lookup against a non-existent `case_id` fails on the case, not the plan. A claim lookup against a non-existent `case_id` fails on the case, not the claim. Likewise a `creditor_id` or `debtor_id` path parameter that does not resolve must produce `ERR_NOT_FOUND`. Scope is enforced alongside existence: a `plan_id` that exists but belongs to a different `Case` than the path's `case_id` is treated as not-found for purposes of this request.

### 2.6. Validation Priority Order

When a single request would surface multiple validation failures, the server evaluates checks in a fixed precedence order and returns the first failure encountered. Authentication is checked first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is checked next: a known role that is not permitted for this endpoint yields `ERR_FORBIDDEN`. Path-segment existence is checked third: any unresolved id along the left-to-right path yields `ERR_NOT_FOUND`. State-machine eligibility is checked fourth: a target resource in a state from which the requested transition is undefined yields `ERR_INVALID_STATE`. The automatic stay check runs fifth, taking precedence over other business rules — debtor protection outranks creditor money rules — and any collection attempt against a case whose stay is active is recorded as a rejected attempt and the request returns `ERR_AUTOMATIC_STAY_VIOLATION`. Only after these five gates pass does the server evaluate the remaining business-referential, business-temporal, business-fiscal, and business-constraint rules in the order spelled out across §3.

### 2.7. The Automatic Stay

The automatic stay is the cornerstone of debtor protection. The boolean field `automatic_stay_active` on every `Case` records whether the stay is currently in force. The stay is `false` while the case is in `DRAFT` or has been withdrawn pre-file, flips to `true` the instant the case transitions from `DRAFT` to `FILED`, remains `true` throughout `FILED`, `MEETING_SCHEDULED`, `MEETING_HELD`, `PLAN_PROPOSED`, `PLAN_CONFIRMED`, and `IN_REPAYMENT`, and flips back to `false` the instant the case reaches `DISCHARGED` or `DISMISSED`.

While the stay is active, every collection attempt — whether of `action_kind` `GARNISH`, `LIEN`, `LAWSUIT`, or `DUNNING_LETTER` — is recorded but blocked: the `CollectionAction` row is still persisted (the immutable attempt log is the audit trail of creditor behaviour during stay), but its `outcome` is written as `REJECTED_STAY`, its `rejected_reason` is written as the string `AUTOMATIC_STAY_ACTIVE`, and the HTTP response is `409 ERR_AUTOMATIC_STAY_VIOLATION`. Only when the stay is inactive does the `CollectionAction` outcome become `PROCESSED` with a 201 response, and in that case `rejected_reason` is the empty string. The stay check evaluates `Case.automatic_stay_active` at insert time within the same transaction that persists the attempt: a creditor racing a filing transition will see whichever value was committed first, and the second-writer's attempt observes the stay flag the filing transition published.

### 2.8. Optimistic Concurrency Control

Operations that mutate a resource may include the resource's current `version` integer in the request body. If the included `version` does not match the row's current `version` on the server at the time the mutation commits, the request is rejected with `ERR_STALE_DATA` (HTTP 409). If the `version` field is omitted from the request body, the server processes the mutation without an OCC check. The check is supported uniformly across all mutating endpoints that target a specific resource by id.

### 2.9. Monetary Precision

All monetary values are persisted and exchanged as integer cents, never as floating-point dollars. Most aggregations on cents — sums, partitions, scalar multiplications — are exact integer operations and require no rounding. Two specific calculations introduce rounding because they involve division: the means-test averages six months of income by dividing the six-month sum by 6, and the trustee-payment waterfall computes a 10% administrative fee and pro-rata shares of the unsecured pool. Both use the half-up convention — that is, when the cent fraction to be discarded is exactly 0.5, the result is rounded away from zero. No other arithmetic in the system rounds, and no value is ever stored as a non-integer.

### 2.10. Cascading Mutations and Version Semantics

Several state transitions trigger cascades on dependent rows. When the 341 meeting is conducted, every claim still in `FILED` for that case auto-transitions to `ALLOWED`; each such claim mutation refreshes its `updated_at` and increments its `version` independently. When a case enters `DISCHARGED`, every claim still in `ALLOWED` is partitioned by `is_dischargeable` into `DISCHARGED` or `NON_DISCHARGEABLE_REMAINS`, and each affected claim row similarly refreshes `updated_at` and bumps `version`. When a Chapter 13 case is dismissed from `IN_REPAYMENT`, every claim still in `ALLOWED` is transitioned to `NON_DISCHARGEABLE_REMAINS` (dismissal does not discharge anything), the `Plan.status` flips to `DEFAULTED`, and `automatic_stay_active` on the case flips to `false`. When a Chapter 13 case is discharged from `IN_REPAYMENT`, the waterfall reconciliation runs across every applied trustee payment before the claim partition runs, then the stay lifts.

### 2.11. Plan and Payment Aggregates

Two aggregates on `Plan` are server-maintained from the underlying `TrusteePayment` rows. `Plan.paid_to_date_cents` is the sum of `amount_cents` across all `TrusteePayment` rows on this plan whose `status` is `APPLIED`. `Plan.missed_payment_count` is the count of `TrusteePayment` rows on this plan whose `status` is `MISSED`. Both recompute on every successful payment insert. `Plan.planned_total_cents` is fixed at plan creation as `proposed_monthly_payment_cents` multiplied by `plan_months`.

### 2.12. Unsecured Pool Aggregate

For every case, the server-maintained `total_unsecured_pool_cents` aggregate is the sum of `amount_cents` across every `Claim` on this case whose `claim_class` is `GENERAL_UNSECURED` and whose `status` is `ALLOWED`. The pool recomputes whenever a claim transitions into or out of `ALLOWED`. Since cents are integers and the formula is a pure sum, no rounding is performed.

## 3. Business Logic & Workflows

### 3.1. Registering Debtors, Creditors, and Opening a Case

A bankruptcy proceeding begins outside the courthouse, with the parties registering themselves. A prospective filer registers a `Debtor` profile by supplying their `full_name`, their `household_size` (which must be at least 1 and which drives the state-median-income lookup later), and a `state_code` consisting of exactly two uppercase letters identifying the state whose median table applies. The `total_cases_filed` field is server-maintained and counts the number of cases this debtor has filed whose status is anything other than the pre-file withdrawal state — it begins at zero on registration and increments as cases are opened.

A creditor — anyone holding a debt that may eventually be claimed — registers a `Creditor` profile by supplying a `name` and a `creditor_type` of `SECURED`, `PRIORITY`, or `GENERAL_UNSECURED`. The creditor type categorizes every claim the creditor will later file: when a claim is filed, its `claim_class` is copied from the creditor's `creditor_type` at the moment of creation and frozen on the claim row, and the two must match at submission time — supplying a `claim_class` that disagrees with the registered `creditor_type` is rejected with `ERR_CLAIM_CLASS_MISMATCH`.

A debtor opens a `Case` by submitting `debtor_id` and the desired `chapter_requested` (either `CHAPTER_7` or `CHAPTER_13`). The case begins in `DRAFT` status, with `automatic_stay_active` set to `false`, `chapter_effective` not yet computed, `filing_date` not yet set, and `schedule_completeness` initialized to the full ten-letter list `[A, B, C, D, E, F, G, H, I, J]`. Cases in `DRAFT` may be deleted entirely by the owning debtor, in which case the status transitions to `WITHDRAWN_PRE_FILE`; because no filing ever occurred, the stay is never engaged in this branch, and the withdrawal has no effect on creditors.

### 3.2. The Schedules A through J

Before a case may be filed, the debtor must complete the ten schedules of personal financial information traditionally lettered A through J. Each schedule is a snapshot uploaded under the debtor's case and is identified by `schedule_type` (taking exactly one of the ten enumerated values `A`, `B`, `C`, `D`, `E`, `F`, `G`, `H`, `I`, or `J`) and a `line_items` array, where each entry carries a `label` and an `amount_cents` integer. The system computes `total_cents` for the schedule by summing the `amount_cents` across the `line_items` entries.

Schedules are append-only snapshots, not editable in place. Resubmitting a schedule of a type that has already been submitted does not overwrite the prior row; instead the prior row's `superseded_by_id` is updated to point to the new row's `id`, and the new snapshot becomes the active one. For all downstream computations — schedule completeness, means-test inputs, claim allowance — only the most recent unsuperseded snapshot for each `schedule_type` participates.

The case's `schedule_completeness` field is server-computed: it is the sorted list of letters from the required set `{A, B, C, D, E, F, G, H, I, J}` that are not yet covered by an active (unsuperseded) snapshot. When this list is empty, all ten schedules have been submitted and the case is filing-ready with respect to schedules. The completeness field recomputes after every schedule submission.

### 3.3. The Means Test

The means test is the gate that determines whether a debtor may proceed under Chapter 7 and, if they instead end up under Chapter 13, what their minimum plan must look like. Running the means test consumes the most recent unsuperseded `Schedule` of type `I` (monthly income) and the most recent unsuperseded `Schedule` of type `J` (monthly expenses) for the case, and produces a `MeansTestResult` snapshot bound to the case via `case_id`. The snapshot is immutable; rerunning the test creates a new row, and the case's `means_test_result_id` is updated to point at the latest result.

The computation proceeds in cents throughout. From the active Schedule I, the system takes the income line items and sums the `amount_cents` over the most recent six months of those line items to obtain a raw six-month sum. The `current_monthly_income_cents` is the raw six-month sum divided by 6 and rounded half-up to the nearest whole cent — this is the only rounding step in the entire calculation. The `cmi_annualized_cents` is the `current_monthly_income_cents` multiplied by 12. The `state_median_annual_cents` is read directly from a fixed state-median table keyed by the debtor's `state_code` and `household_size`: for California a single-person household has a median of 6,500,000 cents (sixty-five thousand dollars) and a two-person household 8,500,000 cents (eighty-five thousand dollars), for Texas a single-person household has a median of 6,000,000 cents (sixty thousand dollars) and a two-person household 8,000,000 cents (eighty thousand dollars), and for any combination of `state_code` and `household_size` not enumerated the fallback is 6,000,000 cents for a single-person household and 8,000,000 cents for a two-person household.

The presumption-of-abuse flag `presumption_of_abuse` is `true` exactly when `cmi_annualized_cents` is strictly greater than `state_median_annual_cents` — the boundary case where the two are equal evaluates to `false`. From Schedule J, the system sums `amount_cents` across its line items to obtain `allowed_monthly_expenses_cents`. The `disposable_monthly_income_cents` is then the larger of zero and the result of subtracting `allowed_monthly_expenses_cents` from `current_monthly_income_cents` — when expenses exceed income, the disposable figure is clamped to zero rather than allowed to go negative. The `required_plan_months` is 36 when `presumption_of_abuse` is `false` and 60 when `presumption_of_abuse` is `true`. The `minimum_plan_total_cents` is the product of `disposable_monthly_income_cents` and `required_plan_months` and represents the floor a Chapter 13 plan must clear at confirmation.

The means test has two operational variants drawn from the same calculation. When the case is being filed under `chapter_requested` of `CHAPTER_7`, only the presumption-of-abuse flag is consulted at the filing gate; the disposable-income side of the calculation is ignored for that decision. When a plan is being confirmed under `chapter_effective` of `CHAPTER_13`, only the `minimum_plan_total_cents` floor is consulted; the presumption-of-abuse flag is ignored at confirmation.

### 3.4. Filing the Case and Engaging the Stay

Once schedules are complete and a means-test result exists, the debtor may file the case, transitioning it from `DRAFT` to `FILED`. The filing gate enforces three preconditions in turn: `schedule_completeness` must be the empty list (any missing letter yields `ERR_SCHEDULES_INCOMPLETE`); the case must have an active `MeansTestResult` referenced by `means_test_result_id` (absence yields `ERR_MEANS_TEST_NOT_RUN`); and, only when `chapter_requested` is `CHAPTER_7`, the means-test result's `presumption_of_abuse` must be `false` (a `true` value at this point yields `ERR_PRESUMPTION_OF_ABUSE` and the Chapter 7 filing is blocked).

When the three preconditions hold, the server commits four side effects atomically. The `filing_date` is set to the server's current clock. The `chapter_effective` is set to `CHAPTER_7` when the requested chapter was `CHAPTER_7` (the presumption check has already cleared) and to `CHAPTER_13` otherwise — note that a debtor who explicitly requested `CHAPTER_13` always ends up under that chapter regardless of presumption. The `automatic_stay_active` flag flips from `false` to `true`. And from this point forward, any `CollectionAction` inserted for this case is gated on the stay as described in §2.7. If two creditors race a `CollectionAction` against the exact instant of the `DRAFT → FILED` transition, the filing's update of the stay flag commits first, and every collection attempt that reads the case afterwards observes the active stay and is rejected with `ERR_AUTOMATIC_STAY_VIOLATION`.

### 3.5. The 341 Creditors' Meeting

After filing, the case enters the 341-meeting choreography conducted by the court-appointed trustee. Scheduling the meeting moves the case from `FILED` to `MEETING_SCHEDULED`; the trustee supplies a `meeting_date` value and the server records it on the case as `meeting_341_date`. The proposed `meeting_date` must be at least 21 days after `filing_date` — that is, the meeting date is no earlier than the filing date plus 21 days. A meeting scheduled too early is rejected with `ERR_MEETING_TOO_EARLY` (HTTP 422).

The meeting may then be conducted, transitioning the case from `MEETING_SCHEDULED` to `MEETING_HELD`. The system's logical clock must already have reached the scheduled `meeting_341_date`; attempting to conduct the meeting while the clock is still earlier than that date is rejected with `ERR_MEETING_DATE_NOT_REACHED`. Because tests need to drive the clock without waiting in wall-clock time, the system exposes an admin-only clock-advancement capability that accepts a `to_iso8601` parameter and sets the server clock to that instant; preconditions that test "the clock has reached X" may flip as a consequence.

Conducting the meeting also fires the claim-review cascade. Every `Claim` for this case still in `FILED` status auto-transitions to `ALLOWED` in the same transaction. Each such auto-transition refreshes that claim's `updated_at`, bumps its `version`, and triggers the recomputation of `Case.total_unsecured_pool_cents` (since claims of class `GENERAL_UNSECURED` becoming `ALLOWED` are exactly the rows that participate in that sum). A claim that was filed with a non-positive `amount_cents` cannot legally allow — the auto-transition refuses, and indeed `ERR_CLAIM_AMOUNT_INVALID` is enforced at claim creation so this state should not arise in practice.

If the trustee instead chooses to dismiss the case while it is still in `MEETING_SCHEDULED`, the case transitions to `DISMISSED`, the stay lifts, and the dismissal completes without further cascades. There is no precondition on this early-dismissal branch beyond authorization and the case being in `MEETING_SCHEDULED`.

### 3.6. Claim Filing and Allowance

Creditors file `Claim` rows against an open case by submitting `creditor_id`, `claim_class`, `amount_cents`, and `is_dischargeable`. The `creditor_id` must match the acting `X-User-ID`, the `claim_class` must equal the registered `creditor_type` of that creditor (otherwise `ERR_CLAIM_CLASS_MISMATCH`), and the `amount_cents` must be strictly greater than zero (a zero-or-negative value yields `ERR_CLAIM_AMOUNT_INVALID`). The `is_dischargeable` boolean is supplied at claim filing and records whether this debt will be erased on discharge: it is set to `false` for the exempt set (support obligations, certain taxes, criminal restitution, fraud-based debts) and `true` for ordinary dischargeable debts. A newly filed claim enters in `FILED` status and waits for the 341 meeting to be conducted before transitioning to `ALLOWED` via the cascade described in §3.5.

A trustee may disallow a `FILED` claim, identified by its `claim_id` path segment, while the case is still in `FILED` or `MEETING_SCHEDULED` — disallowance transitions the claim to `DISALLOWED` directly without passing through `ALLOWED`. Once the case has advanced past `MEETING_SCHEDULED`, claims are no longer in `FILED` state and disallowance via this route is not available; attempting it from any other case state is rejected with `ERR_INVALID_STATE`. Claims that are eventually `DISCHARGED`, `DISALLOWED`, or `NON_DISCHARGEABLE_REMAINS` are terminal.

### 3.7. The Chapter 7 Path to Discharge

A Chapter 7 case advances from `MEETING_HELD` directly to `DISCHARGED` by judicial order. The judge's discharge transition is permitted only when `chapter_effective` equals `CHAPTER_7` — a Chapter 13 case must complete its plan first and any attempt to discharge it from `MEETING_HELD` is rejected with `ERR_PLAN_NOT_COMPLETE`. On discharge, the system runs the exemption-partition pass: every claim still in `ALLOWED` is partitioned by `is_dischargeable` such that a `true` value transitions the claim to `DISCHARGED` and a `false` value transitions it to `NON_DISCHARGEABLE_REMAINS`. The partition is total — the sum of `amount_cents` across all claims that were `ALLOWED` immediately before the discharge equals the sum across the two terminal buckets after, with no claim left in `ALLOWED`. Discharge also flips `automatic_stay_active` to `false`, lifting the stay at the moment relief is granted.

### 3.8. The Chapter 13 Plan Lifecycle

A Chapter 13 case proceeds instead from `MEETING_HELD` to `PLAN_PROPOSED` when the debtor submits a reorganization `Plan`. Plan submission is permitted only when `chapter_effective` is `CHAPTER_13`; submitting a plan against a Chapter 7 case is rejected with `ERR_NOT_CHAPTER_13`. The plan payload carries the debtor's `proposed_monthly_payment_cents` (the amount the debtor commits to pay the trustee each month) and `plan_months` (the duration of the plan). The server computes `planned_total_cents` as the product of `proposed_monthly_payment_cents` and `plan_months` and freezes it on the plan row, and the plan begins in `PROPOSED` status with `paid_to_date_cents` and `missed_payment_count` both initialized to zero. At most one plan per case may exist in any of the active plan states (`PROPOSED`, `CONFIRMED`, or `IN_REPAYMENT`); a second plan insert while one of these is current is rejected with `ERR_PLAN_ALREADY_EXISTS`, which also serializes two debtors racing a plan submission so that exactly one of the two POSTs wins. The plan submission also requires `plan_months` to equal `MeansTestResult.required_plan_months`; a mismatch is rejected with `ERR_PLAN_MONTHS_MISMATCH`.

A `PROPOSED` plan may be withdrawn by the debtor while the case is still in `PLAN_PROPOSED`, in which case the plan's status transitions to `WITHDRAWN` and the case status reverts to `MEETING_HELD`. From `MEETING_HELD` the debtor may then submit a different plan — this cyclic shape allows iterative refinement of the reorganization proposal. Attempting to withdraw a plan when the case is not in `PLAN_PROPOSED` is rejected with `ERR_INVALID_STATE`.

Confirmation is the judicial act that locks the plan and advances the case to `PLAN_CONFIRMED`. Two preconditions guard the confirmation: `planned_total_cents` must be at least `MeansTestResult.minimum_plan_total_cents` (the floor inclusive; less yields `ERR_PLAN_UNDERFUNDED`), and `plan_months` must equal `MeansTestResult.required_plan_months` (a mismatch yields `ERR_PLAN_MONTHS_MISMATCH`). On confirmation, the plan's status moves to `CONFIRMED` and the case's status moves to `PLAN_CONFIRMED` in the same transaction.

### 3.9. Trustee Payments and Default Tracking

Once confirmed, the plan accepts monthly `TrusteePayment` rows recorded by either the debtor or the trustee. Each payment carries a `sequence_number` (the monthly index, unique per plan and in the range from 1 to the plan's `plan_months` inclusive), an `amount_cents`, and a `status` of either `APPLIED` (paid) or `MISSED` (recorded missed month). The server stamps `applied_at` with its current clock at the moment the row is recorded. Two payments racing the same `sequence_number` for the same plan serialize on the uniqueness constraint and the loser is rejected with `ERR_PAYMENT_SEQUENCE_DUPLICATE` (HTTP 409); the same error is returned for any duplicate-sequence insert outside the race condition. A `sequence_number` outside the valid range is similarly rejected with `ERR_PAYMENT_SEQUENCE_DUPLICATE`.

The first `APPLIED` payment with `sequence_number` 1 on a `CONFIRMED` plan advances the case from `PLAN_CONFIRMED` to `IN_REPAYMENT`. Every subsequent payment recomputes the plan's `paid_to_date_cents` aggregate (the sum of `amount_cents` across `APPLIED` rows) and `missed_payment_count` aggregate (the count of `MISSED` rows).

### 3.10. Chapter 13 Discharge and the Trustee-Payment Waterfall

When the debtor has fulfilled the plan, the judge may grant discharge from `IN_REPAYMENT`. Two preconditions apply: `paid_to_date_cents` must be at least `planned_total_cents` (any shortfall yields `ERR_PLAN_NOT_COMPLETE`) and `missed_payment_count` must be exactly zero (any missed payment along the way yields `ERR_PLAN_IN_DEFAULT`, even if the totals happen to add up). On discharge, the plan's status moves to `COMPLETED`, the waterfall reconciliation runs, then the claim-partition pass runs against the post-waterfall state, and finally `automatic_stay_active` flips to `false`.

The waterfall allocates the pool of paid funds across four buckets in a fixed order: administrative fee first, then priority claims, then secured arrears, then the general-unsecured pro-rata distribution. The pool to be allocated is the plan's `paid_to_date_cents`. The first bucket takes a 10% administrative fee: 10% of the pool, rounded half-up at this step, is set aside as the administrative fee, and the pool shrinks by that amount. The second bucket then pays priority claims (those whose `claim_class` is `PRIORITY` and whose `status` is `ALLOWED`) one at a time, iterating in ascending lexicographic order of `Claim.id`; each claim takes the smaller of the remaining pool and the claim's `amount_cents`, and the pool shrinks by that amount. The third bucket pays secured-arrears claims (`claim_class` is `SECURED`, `status` is `ALLOWED`) using the same shape: ascending `Claim.id` order, each claim takes the smaller of remaining pool and `amount_cents`, pool shrinks by that amount.

The fourth bucket distributes whatever remains pro-rata across the general-unsecured `ALLOWED` claims. The total unsecured amount is the sum of `amount_cents` across this set. Each unsecured claim's share is the remaining pool multiplied by that claim's `amount_cents`, divided by the total unsecured amount, rounded half-up at the per-claim step (not at the sum). The rounded shares are summed; if rounding drift leaves any cents unallocated (the remaining pool exceeds the sum of rounded shares), the residual cents are assigned to the unsecured claim whose `Claim.id` is smallest in ascending lexicographic order. The invariant maintained across the four buckets is that the administrative fee plus the priority takes plus the secured takes plus the unsecured shares equals exactly `Plan.paid_to_date_cents` — no cent is lost and none is invented.

After the waterfall, the claim-partition pass runs as in Chapter 7: every claim still in `ALLOWED` is moved to `DISCHARGED` when `is_dischargeable` is `true` and to `NON_DISCHARGEABLE_REMAINS` when it is `false`, and the partition sum invariant holds across the move. Finally the stay lifts.

### 3.11. Chapter 13 Dismissal from Repayment

When a Chapter 13 plan goes into prolonged default, the trustee may dismiss the case from `IN_REPAYMENT`. The single precondition is that `missed_payment_count` must be at least 3 — this is the strict three-strikes boundary, and a count of 1 or 2 missed payments is not enough to dismiss (`ERR_DISMISSAL_NOT_WARRANTED`). When the dismissal commits, the plan's status flips to `DEFAULTED`, `automatic_stay_active` flips to `false`, and every claim still in `ALLOWED` is transitioned to `NON_DISCHARGEABLE_REMAINS`. Crucially, dismissal does not discharge anything; the allowed-claim aggregate amount remains unchanged across the dismissal action — the partition merely renames `ALLOWED` claims as `NON_DISCHARGEABLE_REMAINS` while preserving total `amount_cents`. A debtor whose case is dismissed in this way faces the unchanged debt going forward.

A `PLAN_PROPOSED` case may likewise be dismissed by the trustee with no further precondition; the case moves to `DISMISSED` and the stay lifts. The same is true for dismissal from `MEETING_SCHEDULED`, as already noted.

### 3.12. Concurrency Edge Cases

Several races between concurrent operations resolve deterministically. When two debtor processes attempt to submit a second plan against the same case while a first plan is still active, the second insert violates the at-most-one-plan-per-case rule and is rejected with `ERR_PLAN_ALREADY_EXISTS`. When two duplicate trustee payments race the same `(plan_id, sequence_number)`, exactly one commits and the other is rejected with `ERR_PAYMENT_SEQUENCE_DUPLICATE`. When the trustee races a meeting-conduct against a dismissal from `MEETING_SCHEDULED`, exactly one commits — the loser observes that the case is no longer in `MEETING_SCHEDULED` and is rejected with `ERR_INVALID_STATE`. When a creditor races a collection action against a `DRAFT → FILED` transition, the filing commits the stay flip first within its transaction; the creditor's read of `automatic_stay_active` occurs inside the same transaction as the action insert, observes `true`, and the collection attempt is recorded as `REJECTED_STAY` with `rejected_reason` set to the string `AUTOMATIC_STAY_ACTIVE` and the response is `ERR_AUTOMATIC_STAY_VIOLATION`.

## 4. Endpoint Definitions

Creating a wholly new resource — a debtor, a creditor, a case, a schedule snapshot, a means-test result, a claim, a plan, a trustee payment, a collection action — returns `201 Created`. Modifications and state transitions on existing resources, including the file/dismiss/discharge transitions, plan withdrawal, claim disallowance, plan confirmation, the 341-meeting schedule and conduct calls, and the test-only clock-advance, return `200 OK`. Reads return `200 OK`. The table below summarizes the surface; the request bodies, response shapes, and side effects are specified in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/debtors` | Register a new Debtor | Debtor |
| GET | `/debtors/{debtor_id}` | Get a Debtor | Debtor, Trustee, Judge |
| POST | `/creditors` | Register a new Creditor | Creditor |
| GET | `/creditors/{creditor_id}` | Get a Creditor | Creditor, Trustee, Judge |
| POST | `/cases` | Create a Case in DRAFT for the calling Debtor | Debtor |
| GET | `/cases/{case_id}` | Get a Case | Debtor, Trustee, Creditor, Judge |
| DELETE | `/cases/{case_id}` | Withdraw a DRAFT case | Debtor |
| POST | `/cases/{case_id}/schedules` | Submit or replace a Schedule (A through J) | Debtor |
| POST | `/cases/{case_id}/means-test` | Run the Means Test | Debtor, Trustee |
| POST | `/cases/{case_id}/file` | File the case; activate the automatic stay | Debtor |
| POST | `/cases/{case_id}/schedule-341` | Schedule the 341 creditors' meeting | Trustee |
| POST | `/cases/{case_id}/conduct-341` | Conduct the 341 meeting | Trustee |
| POST | `/cases/{case_id}/dismiss` | Dismiss the case | Trustee |
| POST | `/cases/{case_id}/discharge` | Grant discharge | Judge |
| POST | `/cases/{case_id}/claims` | File a claim against the case | Creditor |
| GET | `/cases/{case_id}/claims/{claim_id}` | Get a Claim | Debtor, Trustee, Creditor, Judge |
| POST | `/cases/{case_id}/claims/{claim_id}/disallow` | Disallow a FILED claim | Trustee |
| POST | `/cases/{case_id}/plans` | Submit a Chapter 13 plan | Debtor |
| GET | `/cases/{case_id}/plans/{plan_id}` | Get a Plan | Debtor, Trustee, Judge |
| DELETE | `/cases/{case_id}/plans/{plan_id}` | Withdraw a PROPOSED plan | Debtor |
| POST | `/cases/{case_id}/plans/{plan_id}/confirm` | Confirm the Chapter 13 plan | Judge |
| POST | `/cases/{case_id}/plans/{plan_id}/payments` | Record a trustee payment | Debtor, Trustee |
| POST | `/collection-actions` | Attempt a collection action against a case | Creditor |
| GET | `/cases/{case_id}/collection-actions` | List collection actions for a case | Trustee, Judge, Creditor |
| POST | `/_clock/advance` | Advance the server clock (test-only) | Trustee |

## 5. Error Code Catalogue

The trigger conditions for each error are documented inline in §2 and §3 alongside the rule they enforce; the table below catalogues only the identifier and the HTTP status returned.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_BAD_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AUTOMATIC_STAY_VIOLATION` | 409 Conflict |
| `ERR_NOT_CHAPTER_13` | 409 Conflict |
| `ERR_MEETING_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_MEETING_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_SCHEDULES_INCOMPLETE` | 409 Conflict |
| `ERR_MEANS_TEST_NOT_RUN` | 409 Conflict |
| `ERR_PRESUMPTION_OF_ABUSE` | 409 Conflict |
| `ERR_PLAN_UNDERFUNDED` | 422 Unprocessable Entity |
| `ERR_PLAN_MONTHS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_COMPLETE` | 409 Conflict |
| `ERR_PLAN_IN_DEFAULT` | 409 Conflict |
| `ERR_DISMISSAL_NOT_WARRANTED` | 409 Conflict |
| `ERR_CLAIM_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_CLAIM_CLASS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAYMENT_SEQUENCE_DUPLICATE` | 409 Conflict |
| `ERR_PLAN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_STALE_DATA` | 409 Conflict |
