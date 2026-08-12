# Captive Insurance Management API — Product Requirements Document

## 1. Introduction

Captive insurance companies operate under a distinctive regulatory and accounting regime: they exist to insure the risks of their parent group, yet they are supervised by a domicile regulator, capitalised under statute, audited annually, and taxed under specific elections (most notably the United States Internal Revenue Code section 831(b) micro-captive election). The firm that manages a captive must therefore weave together corporate formation paperwork, capital adequacy monitoring, program underwriting, premium allocation across the parent's operating units, third-party claims administration, actuarial reserving, board governance, and tax position analysis — all against strict segregation-of-duties requirements and a fully auditable trail of every material action.

This document specifies a REST API that powers a captive-management platform covering the full lifecycle: formation of a `CaptiveEntity`, domicile regulatory filing, capitalisation, activation, program design with optional fronting arrangements and collateral posting, premium allocation to operating units, claims handling and TPA oversight, actuarial reserve certification, annual statement preparation and board approval, and tax position analysis with risk distribution testing. Every rule stated below — every state transition, every threshold, every cascade — is a hard requirement: an implementation that misses any of them is non-conforming.

The audience is engineering. The product manager's intent is that an engineer reading this document alone can reconstruct the entire contract: roles, headers, envelopes, entity states, transitions, calculations, validations, endpoints, and errors. All endpoints are mounted under the `/api` prefix, with the single exception of a clock test-driving endpoint used by integration tests.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` (the acting user's identifier) and `X-User-Role` (the acting user's role). If either header is missing or fails validation, the server responds with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role supplied does not have permission to perform the requested operation, the server responds with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The recognised roles — spelled exactly as follows — are: `CaptiveManager`, `DomicileRegulator`, `Underwriter`, `Actuary`, `ClaimsAdjuster`, `BoardDirector`, `TaxAdvisor`.

All seven roles use an **opaque** identity model: `X-User-ID` is not tied to the `id` of any persisted entity. The server may record the value (for example, as `actor_id` on `AuditLog`, or as `certified_by` on `ActuarialReserve` where a transition writes the acting user) but it does not compare the value to any entity's `id`. Concretely: when `X-User-Role` is `CaptiveManager`, `DomicileRegulator`, `Underwriter`, `Actuary`, `ClaimsAdjuster`, `BoardDirector`, or `TaxAdvisor`, the `X-User-ID` header is an opaque operator identifier. The segregation-of-duties rules described later compare this opaque `X-User-ID` value between two requests (creation versus certification/approval) without ever resolving it against an entity record.

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

List endpoints accept two query parameters. The `limit` parameter defaults to `10`, must be at least `1`, and may not exceed `100`. The `offset` parameter defaults to `0` and is the zero-based starting index into the result set. Non-numeric `limit` or `offset` values fall back to the defaults, and out-of-range values are clamped rather than rejected (`limit` into the [1, 100] band, `offset` up to 0). The `meta` block on a successful list response echoes the effective `limit` and `offset`, and also reports `total_count` (the total number of records matching the filter, before pagination) and `has_more` (true when `offset + limit` is less than `total_count`). All list endpoints sort by `created_at` ascending.

### 2.4. Common Resource Properties, Hierarchy, and Concurrency Control

Every entity except `AuditLog` carries a common set of fields: `id` is a server-minted UUID with no type prefix, rendered in the canonical 36-character hyphenated form (for example `550e8400-e29b-41d4-a716-446655440000`); `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `version` is an integer starting at 1 and incremented by 1 on every mutation of the resource. `AuditLog` is append-only and carries only `id` and `created_at`; it has neither `updated_at` nor `version`. Certain internal bookkeeping fields are stored but never serialized in any response body: `created_by` on `PremiumAllocation` and `ActuarialReserve`, `minutes_drafted_by` on `BoardMeeting`, and the denormalized `program_id` and `captive_id` foreign keys on `CollateralPosting` are scrubbed from every response.

All nested resources live under their parent in the URL path, and the server validates path parameters left-to-right: for a request to `/api/captives/{captiveId}/programs/{programId}/claims/{claimId}`, the server first confirms the captive identified by `captiveId` exists (else `ERR_CAPTIVE_NOT_FOUND`, HTTP 404), then that the program identified by `programId` exists under that captive (else `ERR_PROGRAM_NOT_FOUND`), then that the claim identified by `claimId` exists under that program (else `ERR_CLAIM_NOT_FOUND`). Analogous not-found errors exist for every entity: `ERR_FILING_NOT_FOUND`, `ERR_FRONTING_NOT_FOUND`, `ERR_COLLATERAL_NOT_FOUND`, `ERR_OPERATING_UNIT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_TPA_NOT_FOUND`, `ERR_RESERVE_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_MEETING_NOT_FOUND`, `ERR_TAX_POSITION_NOT_FOUND`, and `ERR_AUDIT_LOG_NOT_FOUND`.

**Optimistic concurrency control.** Two write endpoints participate in optimistic concurrency control against the parent `CaptiveEntity`. Creating a new `InsuranceProgram` requires the request body to carry `expected_captive_version` — a non-optional integer equal to the captive's current `version` as last observed by the client. If the captive's actual `version` has advanced since (for example because another writer just triggered a solvency recalculation), the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Settling a claim is likewise guarded: the settle request body must carry `expected_captive_version` matching the captive's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Both of these writes also increment the captive's `version` by 1 on success. No other endpoint takes an OCC field. Unless a workflow in §3 states a precondition on a parent's status, creation endpoints accept the parent in any lifecycle status.

### 2.5. Money, Precision, and Rounding

All monetary quantities are stored and transmitted as integer cents in fields named with the `_cents` suffix (`capitalization_amount`, `capital_minimum_required`, `premium_budget_cents`, `aggregate_limit_cents`, `per_occurrence_limit_cents`, `attachment_point_cents`, `premium_allocated_cents`, `claims_incurred_cents`, `claims_paid_cents`, `claimed_amount_cents`, `reserved_amount_cents`, `paid_amount_cents`, `recoverable_amount_cents`, `net_incurred_cents`, `settlement_amount_cents`, `reserve_amount_cents`, `central_estimate_cents`, `low_estimate_cents`, `high_estimate_cents`, `carried_reserve_cents`, `collateral_required_cents`, `collateral_posted_cents`, `collateral_shortfall_cents`, `amount_cents`, `effective_value_cents`, `fronting_fee_amount_cents`, `authority_limit_cents`, `fee_amount_cents`, `provisional_amount_cents`, `allocated_amount_cents`, `final_amount_cents`, `adjustment_cents`, `total_premium_allocated_cents`, `total_claims_incurred_cents`, `total_premium_written`, `total_reserves_held`, `admitted_assets`, `total_assets_cents`, `total_liabilities_cents`, `policyholder_surplus_cents`, `net_premium_written_cents`, `net_losses_incurred_cents`, `underwriting_result_cents`, `investment_income_cents`, `filing_fee_cents`).

Ratios, percentages, and other non-cent quantities (`solvency_ratio`, `loss_ratio`, `combined_ratio`, `expense_ratio`, `rbc_ratio`, `fronting_fee_pct`, `reinsurance_ceded_pct`, `haircut_pct`, `sla_compliance_pct`, `performance_score`, `governance_score`, `risk_distribution_score`, `risk_weight`, `confidence_level_pct`, `development_factor`, `premium_deductibility_pct`, `third_party_premium_pct`) follow the precision rule attached to their owning calculation: ratios that compare two cent quantities (`solvency_ratio`, `loss_ratio`, `combined_ratio`, `expense_ratio`, `rbc_ratio`, `risk_distribution_score`, `premium_deductibility_pct`, `third_party_premium_pct`) are expressed to **2 decimal places, rounded half-up**; quantities that are themselves a cent amount or are inputs to cent amounts (`allocated_amount_cents`, `provisional_amount_cents`, `final_amount_cents`, `central_estimate_cents`, `low_estimate_cents`, `high_estimate_cents`, `carried_reserve_cents`, `effective_value_cents`, `fronting_fee_amount_cents`, `adjustment_cents`) are computed to **0 decimal places (integer cents), rounded half-up**.

### 2.6. Auditability and the Audit Log

Every state transition, every calculation trigger, every filing, every certification, every governance action, and every tax position change writes an `AuditLog` entry. The audit record carries `captive_id`, `action_type` (one of `STATE_CHANGE`, `CALCULATION_RUN`, `FILING_SUBMITTED`, `CERTIFICATION`, `GOVERNANCE_ACTION`, `TAX_POSITION_CHANGE`), `entity_type` (the name of the affected entity type), `entity_id` (the `id` of the affected record), `actor_role` (the `X-User-Role` of the actor), `actor_id` (the `X-User-ID` of the actor), `action_description` (a human-readable summary), `previous_state`, `new_state`, and `timestamp`. The audit log is append-only: there is no update or delete path.

### 2.7. Segregation of Duties

Certain pairs of operations on the same resource must be performed by different users, compared by their opaque `X-User-ID` values. The two segregated pairs are: (1) certifying an `ActuarialReserve` must be performed by an `Actuary` whose `X-User-ID` differs from the `X-User-ID` that created the reserve, and (2) approving the minutes of a `BoardMeeting` must be performed by a `BoardDirector` whose `X-User-ID` differs from the `X-User-ID` that drafted the minutes. Violation of either is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.8. Solvency Monitoring as a Cross-Cutting Concern

The captive's solvency is re-evaluated continuously. The `solvency_ratio` of a `CaptiveEntity` is the ratio of its `admitted_assets` to its `capital_minimum_required` (the regulator-published minimum for the chosen domicile), expressed as a percentage. The `admitted_assets` total rests on the captive's paid-in capital: it is computed as the captive's `capitalization_amount`, plus the sum of the `effective_value_cents` of every `CollateralPosting` whose `verification_status` is `VERIFIED`, plus the sum of the `allocated_amount_cents` of every `PremiumAllocation` whose `status` is `PROVISIONAL`, `AUDITED`, or `FINALIZED`, minus the sum of the `paid_amount_cents` of every `Claim` whose `claim_status` is `SETTLED`. The `solvency_status` is then derived from the ratio: when the ratio is at least `150` the status is `ADEQUATE`; when the ratio is at least `100` but strictly less than `150` the status is `WARNING`; when the ratio is strictly below `100` the status is `BREACH`. The ratio and the status are recomputed on every event that could move `admitted_assets` or the required capital — a claim settlement, a collateral posting or release, a premium allocation finalization, or a reserve certification. The same recomputation maintains two further ledger fields on the captive: `total_reserves_held` is the sum of the `carried_reserve_cents` of every `ActuarialReserve` in `CERTIFIED` or `FILED` status plus the `reserved_amount_cents` of every claim in `RESERVED` status, and `total_premium_written` is the sum of the `allocated_amount_cents` of every `PremiumAllocation` in `PROVISIONAL`, `AUDITED`, or `FINALIZED` status.

For captives with `tax_classification` equal to `MICRO_CAPTIVE_831B`, the admitted-assets computation uses **conservative haircuts**: every non-cash collateral haircut is multiplied by one and a half (so a `LETTER_OF_CREDIT` carries a 10% haircut instead of 5%, a `TRUST_ACCOUNT` carries 3% instead of 2%, a `SURETY_BOND` carries 15% instead of 10%, and `INVESTMENT_SECURITIES` carry 22.5% instead of 15%). For any other `tax_classification` (`STANDARD_831A` or `NON_ELECTING`), the standard haircut schedule applies. The standard schedule is: `LETTER_OF_CREDIT` 5%, `TRUST_ACCOUNT` 2%, `SURETY_BOND` 10%, `CASH_ESCROW` 0%, and `INVESTMENT_SECURITIES` 15% (a `CASH_ESCROW` posting therefore keeps its full value under both schedules).

A `CaptiveEntity` whose `solvency_status` is `BREACH` cannot be activated (see the activation transition), and a program cannot transition from `BOUND` to `IN_FORCE` while the captive's `solvency_status` is `BREACH`; both are rejected with `ERR_SOLVENCY_BREACH` (HTTP 403). The same `ERR_SOLVENCY_BREACH` rejection applies to a reinstatement attempt while the breach persists.

### 2.9. Governance Score as a Cross-Cutting Concern

Every captive carries a `governance_score` that starts at `100` upon creation. Governance events adjust the score: rejecting a domicile filing decrements the score by `10`; withdrawing an already-`SUBMITTED` filing decrements it by `5` (withdrawing a `DRAFT` filing carries no penalty); disputing a premium allocation decrements it by `3`; resolving a dispute restores `3`; a board approval of an annual statement adds `5`; amending a previously filed annual statement decrements it by `5`; and a tax-position challenge decrements it by `15`. The score is capped at `100` — recovery events cannot push it above the cap. There is no lower bound: penalties may drive the score below zero. A captive whose `governance_score` falls below `40` becomes eligible for suspension by the regulator, and a suspended captive cannot be reinstated until its `governance_score` is at least `40` (rejection code `ERR_GOVERNANCE_SCORE_TOO_LOW`, HTTP 403).

### 2.10. Test-Driving Endpoint

An administrative endpoint allows a `CaptiveManager` to set the server's logical clock to a supplied `to_iso8601` instant. The default startup logical time is `2026-05-01T00:00:00Z`. The logical clock is the source of `current_utc` used by every transition whose preconditions or side effects reference the current time. All server-generated timestamps — `api_request_timestamp`, `created_at`, `updated_at`, `filed_at`, `reported_date`, `certification_date`, and `review_deadline` — are rendered from this logical clock. The endpoint responds with HTTP 200 and an empty `data` object; a missing or unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Captive Formation and Domicile Filing

A `CaptiveManager` initiates the captive lifecycle by creating a `CaptiveEntity` with `captive_name`, `domicile_jurisdiction` (one of `VERMONT`, `BERMUDA`, `CAYMAN`, `GUERNSEY`, `LUXEMBOURG`), `formation_date`, `capitalization_amount` in cents, and an optional `tax_classification` (one of `MICRO_CAPTIVE_831B`, `STANDARD_831A`, `NON_ELECTING`; if omitted the captive defaults to `MICRO_CAPTIVE_831B`). The captive is born in `FORMATION_PENDING` status with `governance_score` set to `100`, `solvency_status` set to `ADEQUATE`, and `capital_minimum_required` looked up from the regulator-published schedule for the chosen domicile. The schedule values (in cents) are: `VERMONT` 25000000, `BERMUDA` 12000000, `CAYMAN` 10000000, `GUERNSEY` 10000000, `LUXEMBOURG` 3700000. The captive is also born with `admitted_assets` 0, `solvency_ratio` 100.0, `total_reserves_held` 0, `total_premium_written` 0, and `risk_distribution_score` 0.0; no solvency recomputation runs at creation.

The next step is preparing a `DomicileFiling`. A `CaptiveManager` creates the filing under the captive, naming a `filing_type` (one of `INITIAL_FORMATION`, `ANNUAL_RENEWAL`, `AMENDMENT`, `REDOMESTICATION`), a `jurisdiction` (the same enumeration as `domicile_jurisdiction`), and a `supporting_documents` array, where each entry names `document_type`, `document_url`, and `uploaded_at`. The filing is born in `DRAFT` status, and the `filing_fee_cents` is computed from a schedule keyed by jurisdiction and filing type: a per-jurisdiction base fee — `VERMONT` 600000, `BERMUDA` 750000, `CAYMAN` 850000, `GUERNSEY` 700000, `LUXEMBOURG` 900000 cents — multiplied by a per-type factor of `INITIAL_FORMATION` 1.0, `ANNUAL_RENEWAL` 0.5, `AMENDMENT` 0.25, or `REDOMESTICATION` 0.75, rounded to integer cents half-up. Submitting the filing transitions it `DRAFT → SUBMITTED`, stamps `filed_at` with the current UTC instant, computes the `review_deadline` as `filed_at` plus the jurisdiction's review-day count (30 days for `VERMONT`, 45 for `BERMUDA`, 60 for `CAYMAN` and `GUERNSEY`, 90 for `LUXEMBOURG`), and simultaneously transitions the parent captive `FORMATION_PENDING → DOMICILE_FILED`. Submission requires that the captive is still in `FORMATION_PENDING` (else `ERR_CAPTIVE_NOT_IN_FORMATION`), that the filing itself is in `DRAFT` (else `ERR_FILING_NOT_DRAFT`), and that at least one supporting document has been uploaded (else `ERR_NO_SUPPORTING_DOCUMENTS`, HTTP 400). A `CaptiveManager` may withdraw a filing while it is `DRAFT` or `SUBMITTED`; withdrawal from `DRAFT` carries no governance penalty, while withdrawal from `SUBMITTED` decrements the captive's `governance_score` by `5`. Withdrawal changes only the filing's status (to `WITHDRAWN`); it never alters the captive's status. Any other source state is rejected with `ERR_FILING_NOT_WITHDRAWABLE`.

A `DomicileRegulator` then picks up the submission. Acknowledging it transitions the filing `SUBMITTED → UNDER_REVIEW` and stamps `regulator_reference` with a system-generated regulator reference of the form `REG-` followed by 12 uppercase hexadecimal characters; acknowledgement from any other status is rejected with `ERR_FILING_NOT_SUBMITTED`. The regulator may then approve or reject. Approval requires the captive to be in `DOMICILE_FILED` (else `ERR_CAPTIVE_NOT_DOMICILE_FILED`), the filing to be `UNDER_REVIEW` (else `ERR_FILING_NOT_UNDER_REVIEW`), and the captive's `capitalization_amount` to be at least the domicile's `capital_minimum_required` (else `ERR_CAPITALIZATION_BELOW_MINIMUM`, HTTP 400). On approval, the filing transitions `UNDER_REVIEW → APPROVED`, the captive transitions `DOMICILE_FILED → CAPITALIZED`, the captive's `solvency_ratio` and `solvency_status` are recomputed, and an audit entry is written. Rejection transitions the filing `UNDER_REVIEW → REJECTED`, records the supplied `rejection_reason`, and decrements the captive's `governance_score` by `10`.

### 3.2. Activation, Suspension, Reinstatement, and Dissolution

Once the captive is `CAPITALIZED` and at least one `InsuranceProgram` has reached `BOUND` or any later state (`IN_FORCE`, `RUN_OFF`, `CLOSED`), a `CaptiveManager` may activate the captive. Activation transitions the captive `CAPITALIZED → ACTIVE`; attempting it while the captive is not `CAPITALIZED` is rejected with `ERR_CAPTIVE_NOT_CAPITALIZED`, attempting it with no bound program is rejected with `ERR_NO_BOUND_PROGRAM` (HTTP 409), and attempting it while the captive's `solvency_status` is `BREACH` is rejected with `ERR_SOLVENCY_BREACH`.

A `DomicileRegulator` may suspend an `ACTIVE` captive when either its `solvency_status` is `BREACH` or its `governance_score` has fallen below `40`. Suspension transitions the captive `ACTIVE → SUSPENDED`, cascades every `IN_FORCE` program to `RUN_OFF` (flipping each such program's `coverage_status` to `EXPIRED`), and cascades every `ACTIVE` `FrontingArrangement` to `TERMINATED` (releasing its `VERIFIED` collateral postings). Suspension from any other state is rejected with `ERR_CAPTIVE_NOT_ACTIVE`, and suspension without either ground is rejected with `ERR_NO_SUSPENSION_GROUNDS` (HTTP 400).

Reinstatement by a `DomicileRegulator` transitions a `SUSPENDED` captive back to `ACTIVE`. Reinstatement requires that the captive actually be `SUSPENDED` (else `ERR_CAPTIVE_NOT_SUSPENDED`), that `solvency_status` is no longer `BREACH` (else `ERR_SOLVENCY_BREACH`), and that the `governance_score` has been restored to at least `40` (else `ERR_GOVERNANCE_SCORE_TOO_LOW`).

Dissolution has two branches. A `CaptiveManager` dissolves an `ACTIVE` captive only when no program is in `IN_FORCE` or `BOUND` (else `ERR_ACTIVE_PROGRAMS_EXIST`), all claims are in terminal states (`SETTLED`, `DENIED`, or `CLOSED_WITHOUT_PAYMENT`; else `ERR_OPEN_CLAIMS_EXIST`), and all reserves are `FILED` (else `ERR_UNFILED_RESERVES_EXIST`). A `DomicileRegulator` may dissolve a `SUSPENDED` captive once all claims are in terminal states. The applicable branch is selected by the captive's current status, not by the requester's role — either authorized role may exercise either branch — and dissolution from any status other than `ACTIVE` or `SUSPENDED` is rejected with `ERR_CAPTIVE_NOT_ACTIVE` (HTTP 409). Both branches transition the captive to `DISSOLVED`, cascade all remaining programs to `CLOSED` (flipping their `coverage_status` to `EXPIRED`; programs already `CANCELLED` are left untouched), and cascade every collateral posting not already `RELEASED` to `RELEASED`.

### 3.3. Insurance Program Lifecycle and Policy Period Constraints

An `Underwriter` designs an `InsuranceProgram` under a captive. The create body carries `program_name`, `line_of_business` (one of `GENERAL_LIABILITY`, `WORKERS_COMP`, `PROPERTY`, `PROFESSIONAL_LIABILITY`, `CYBER`, `D_AND_O`), `policy_period_start`, `policy_period_end`, `aggregate_limit_cents`, `per_occurrence_limit_cents`, `attachment_point_cents`, `premium_budget_cents`, an optional `fronting_required` flag (default `false`), and the OCC field `expected_captive_version` described in §2.4. The policy period must satisfy `policy_period_end` strictly after `policy_period_start` (else `ERR_INVALID_POLICY_PERIOD`, HTTP 400), and the requested period must not overlap any existing program for the same `line_of_business` under the same captive (else `ERR_POLICY_PERIOD_OVERLAP`, HTTP 409); programs in `CLOSED` or `CANCELLED` status are ignored by the overlap check, and periods that merely touch at an endpoint (one ends exactly when the other begins) do not count as overlapping. A successful create lands the program in `DRAFT` status with `coverage_status` set to `UNBOUND`, and increments the captive's `version` by 1.

The program then walks a seven-state lifecycle. Quoting by an `Underwriter` moves it `DRAFT → QUOTED`; quoting requires the program to be `DRAFT` (else `ERR_PROGRAM_NOT_DRAFT`) and the captive to be either `CAPITALIZED` or `ACTIVE` (else `ERR_CAPTIVE_NOT_OPERATIONAL`). Quoting leaves `coverage_status` at `UNBOUND` and does not modify any premium allocation. Binding by an `Underwriter` moves the program `QUOTED → BOUND` and flips `coverage_status` to `BOUND`; binding requires the program to be `QUOTED` (else `ERR_PROGRAM_NOT_QUOTED`) and, when `fronting_required` is true, requires the associated `FrontingArrangement` to be in `COLLATERAL_POSTED` or any later state (else `ERR_FRONTING_NOT_READY`). Activating by an `Underwriter` moves the program `BOUND → IN_FORCE`; activation requires the program to be `BOUND` (else `ERR_PROGRAM_NOT_BOUND`), the captive to be `ACTIVE` (else `ERR_CAPTIVE_NOT_ACTIVE`), and the current UTC instant to be at or after `policy_period_start` (else `ERR_POLICY_PERIOD_NOT_STARTED` is not in the error catalogue — the activation simply requires the temporal condition as a precondition; the canonical failure for a too-early activation is `ERR_INVALID_REQUEST`, HTTP 400). Activation also synchronises the captive's `total_premium_written` ledger field.

Entering run-off by an `Underwriter` moves the program `IN_FORCE → RUN_OFF` and flips `coverage_status` to `EXPIRED`; run-off requires the program to be `IN_FORCE` (else `ERR_PROGRAM_NOT_IN_FORCE`); new premium allocations remain accepted against a program in any status, including `RUN_OFF`. Closing by an `Underwriter` moves the program `RUN_OFF → CLOSED`; closing requires the program to be `RUN_OFF` (else `ERR_PROGRAM_NOT_IN_RUNOFF`), requires all claims against the program to be in terminal states (else `ERR_OPEN_CLAIMS_EXIST`), and requires all reserves against the program to be `CERTIFIED`, `FILED`, or `SUPERSEDED` (else `ERR_UNFILED_RESERVES_EXIST`). On close, the premium-allocation reconciliation is finalised and the captive's `admitted_assets` are recomputed. An `Underwriter` may cancel a program while it is `DRAFT` or `QUOTED`; cancellation moves the program to `CANCELLED` and cascades every provisional premium allocation to `CANCELLED`. Cancelling from any other state is rejected with `ERR_PROGRAM_NOT_CANCELLABLE`.

### 3.4. Fronting Arrangements and Collateral

When a program's `fronting_required` flag is true, the program must be paired with a `FrontingArrangement` before it can be bound. An `Underwriter` creates the arrangement with `fronting_carrier_name`, `fronting_fee_pct` (a fraction between 0.01 and 0.15 of gross premium), and `reinsurance_ceded_pct` (a fraction between 0.0 and 1.0 of risk ceded back to the captive). The arrangement is born in `NEGOTIATING` status.

The arrangement walks `NEGOTIATING → TERMS_AGREED → COLLATERAL_POSTED → ACTIVE`. Agreeing terms by an `Underwriter` requires `NEGOTIATING` (else `ERR_FRONTING_NOT_NEGOTIATING`) and triggers computation of `collateral_required_cents`, which is the parent program's `aggregate_limit_cents` multiplied by the arrangement's `reinsurance_ceded_pct`, rounded to integer cents half-up. A `CaptiveManager` then posts collateral against the arrangement. Each `CollateralPosting` carries `collateral_type` (one of `LETTER_OF_CREDIT`, `TRUST_ACCOUNT`, `SURETY_BOND`, `CASH_ESCROW`, `INVESTMENT_SECURITIES`), `amount_cents`, `posted_date`, `expiry_date` (which must be strictly after `posted_date`, else `ERR_INVALID_COLLATERAL_DATES`, HTTP 400), and `issuing_institution`. The posting is born with `verification_status` set to `PENDING_VERIFICATION`, and its `haircut_pct` and `effective_value_cents` are computed from the haircut schedule (§2.8, with the conservative multiplier for micro-captives): `effective_value_cents` is `amount_cents` multiplied by one minus the haircut, rounded to integer cents half-up. A `CaptiveManager` then verifies the posting, which flips `verification_status` to `VERIFIED` (verification is accepted from any prior `verification_status`) and updates the parent arrangement's `collateral_posted_cents` and `collateral_shortfall_cents`. The `collateral_shortfall_cents` is the larger of zero and the difference between `collateral_required_cents` and `collateral_posted_cents`.

Posting collateral against the arrangement by a `CaptiveManager` transitions the arrangement `TERMS_AGREED → COLLATERAL_POSTED`. This requires the arrangement to be `TERMS_AGREED` (else `ERR_FRONTING_NOT_TERMS_AGREED`) and requires the cumulative `collateral_posted_cents` to be at least `collateral_required_cents` (else `ERR_INSUFFICIENT_COLLATERAL`, HTTP 400). Activating the arrangement by an `Underwriter` transitions it `COLLATERAL_POSTED → ACTIVE`; activation requires the arrangement to be `COLLATERAL_POSTED` (else `ERR_FRONTING_NOT_COLLATERAL_POSTED`) and the parent program to be `BOUND` (else `ERR_PROGRAM_NOT_BOUND`). Activation triggers the fronting-fee calculation: `fronting_fee_amount_cents` equals the parent program's `premium_allocated_cents` multiplied by the arrangement's `fronting_fee_pct`, rounded to integer cents half-up; the fee is recomputed whenever the premium allocation total changes.

An `Underwriter` may terminate an arrangement, which moves it `ACTIVE → TERMINATED`. Termination requires the arrangement to be `ACTIVE` (else `ERR_FRONTING_NOT_ACTIVE`) and is the only way an arrangement leaves `ACTIVE` outside the captive-suspension cascade; there is no automatic expiry when the logical clock passes the parent program's `policy_period_end`. Termination releases every `VERIFIED` collateral posting (flipping each to `RELEASED`), reduces the captive's `admitted_assets`, and — when the parent program has not yet reached `IN_FORCE` — reverts the program to `BOUND`.

### 3.5. Operating Units and Premium Allocation

A `CaptiveManager` registers each `OperatingUnit` of the parent group under the captive with `unit_name`, `unit_code` (an opaque string; uniqueness is not enforced), `exposure_basis` (one of `REVENUE`, `HEADCOUNT`, `PAYROLL`, `ASSET_VALUE`, `SQUARE_FOOTAGE`), and `exposure_amount` (a non-negative number expressed in the units matching the chosen `exposure_basis`). The unit is born `ACTIVE`. The API exposes no unit status transitions: a unit remains `ACTIVE` for its entire lifetime, and only `ACTIVE` units participate in premium allocation.

An `Underwriter` allocates premium from a program to a unit by creating a `PremiumAllocation` naming `operating_unit_id`, `allocation_method` (one of `EXPOSURE_PRO_RATA`, `EQUAL_SHARE`, `MANUAL`, `RISK_WEIGHTED`), `allocation_period_start`, `allocation_period_end`, and — for the `RISK_WEIGHTED` method — an optional `risk_weight` between 0.1 and 5.0 (default `1.0`). The unit identified by `operating_unit_id` must exist and must belong to the same captive as the program (else `ERR_OPERATING_UNIT_MISMATCH`, HTTP 400). The new allocation lands in `PROVISIONAL` status, and the system computes `provisional_amount_cents` and `allocated_amount_cents` from the chosen method. Creation also adds the computed amount to the unit's `total_premium_allocated_cents`.

The four allocation methods are computed as follows. Under `EXPOSURE_PRO_RATA`, the unit's share is the unit's `exposure_amount` divided by the sum of `exposure_amount` across every `ACTIVE` operating unit under the captive; the allocated amount is the program's `premium_budget_cents` multiplied by that share. Under `EQUAL_SHARE`, the allocated amount is the program's `premium_budget_cents` divided by the count of `ACTIVE` operating units. Under `MANUAL`, the allocated amount is the operator-supplied amount, validated against the budget. Under `RISK_WEIGHTED`, each unit's `weighted_exposure` is the unit's `exposure_amount` multiplied by the allocation's `risk_weight`; the allocated amount is the program's `premium_budget_cents` multiplied by the ratio of this unit's `weighted_exposure` to the sum of `weighted_exposure` across all `ACTIVE` units. In all four cases the result is rounded to integer cents, half-up (with the provisional round-up to the nearest 100 cents described below applied at creation). Two guards share the error `ERR_ALLOCATION_EXCEEDS_BUDGET` (HTTP 400): each individual allocation's computed amount may not exceed 50% of the program's `premium_budget_cents` (a per-allocation cap, not a cumulative per-unit cap), and a create that would push the total of `allocated_amount_cents` across the program's `PROVISIONAL`, `AUDITED`, and `FINALIZED` allocations above the budget is likewise rejected.

Provisional allocations use estimated exposure figures and round up to the nearest 100 cents for conservatism; final allocations use audited actual exposure and exact cent rounding. An `Actuary` audits a `PROVISIONAL` allocation, moving it `PROVISIONAL → AUDITED` and recomputing `allocated_amount_cents` using the audited figures; auditing from any other state is rejected with `ERR_ALLOCATION_NOT_PROVISIONAL`. An `Actuary` then finalises the `AUDITED` allocation by submitting the audited `final_amount_cents`, moving it `AUDITED → FINALIZED`. Finalisation requires `AUDITED` (else `ERR_ALLOCATION_NOT_AUDITED`) and requires that the computed final amount be present and valid (else `ERR_ALLOCATION_NOT_COMPUTED`, HTTP 409). On finalisation, the `adjustment_cents` is computed as `final_amount_cents` minus `provisional_amount_cents`, and the same adjustment is applied to the unit's `total_premium_allocated_cents`, the program's `premium_allocated_cents`, and the captive's `total_premium_written`.

A `CaptiveManager` may dispute a `PROVISIONAL` allocation, moving it `PROVISIONAL → DISPUTED` and decrementing the captive's `governance_score` by `3`. Resolving the dispute returns the allocation `DISPUTED → PROVISIONAL` and adds `3` back to the governance score (capped at `100`). Resolving from any state other than `DISPUTED` is rejected with `ERR_ALLOCATION_NOT_DISPUTED`. An `Underwriter` may cancel an allocation while it is `PROVISIONAL` or `DISPUTED`, moving it to `CANCELLED` and reducing the program's `premium_allocated_cents` (the unit's `total_premium_allocated_cents` is not adjusted); cancelling from any other state is rejected with `ERR_ALLOCATION_NOT_CANCELLABLE`.

### 3.6. Claims Handling and TPA Oversight

A `ClaimsAdjuster` reports a `Claim` against a program in any status (no program-status precondition is enforced), naming `operating_unit_id` (which must belong to the same captive, else `ERR_OPERATING_UNIT_MISMATCH`), `claimant_name`, `loss_date`, `claimed_amount_cents`, and an optional `tpa_assigned_id` referencing an existing `TPAAssignment`. The `loss_date` must fall within the program's policy period (else `ERR_LOSS_DATE_OUT_OF_PERIOD`, HTTP 400). On creation, the claim is stamped with a system-generated `claim_number` of the form `CLM-YYYYMMDD-NNNN` — where the date is the logical clock's current date and `NNNN` is a zero-padded four-digit per-day sequence starting at `0001` — lands in `REPORTED` status with `payment_status` set to `UNPAID` and `litigation_status` set to `NOT_LITIGATED`, and the system computes `coverage_confirmed` (true when the loss date falls within the policy period and the claimed amount exceeds neither the program's `per_occurrence_limit_cents` nor its `aggregate_limit_cents`).

Acknowledging a claim moves it `REPORTED → ACKNOWLEDGED`; acknowledgement requires `REPORTED` (else `ERR_CLAIM_NOT_REPORTED`) and requires `coverage_confirmed` to be true (else `ERR_COVERAGE_NOT_CONFIRMED`, HTTP 400). Acknowledgement does not create or modify any `TPAAssignment`; a `tpa_assigned_id` supplied at report time is simply stored as given. Beginning investigation moves the claim `ACKNOWLEDGED → UNDER_INVESTIGATION` (else `ERR_CLAIM_NOT_ACKNOWLEDGED`) and leaves `reserved_amount_cents` at zero. Setting the reserve by an `Actuary` moves the claim `UNDER_INVESTIGATION → RESERVED`; the body carries `reserve_amount_cents` which becomes the new `reserved_amount_cents`. Setting the reserve from any other state is rejected with `ERR_CLAIM_NOT_UNDER_INVESTIGATION`. The set-reserve transition also updates the captive's `total_reserves_held` and the program's `claims_incurred_cents`. A claim's `net_incurred_cents` is its `paid_amount_cents` plus `reserved_amount_cents` minus `recoverable_amount_cents`; a program's `claims_incurred_cents` is the sum of `net_incurred_cents` over its claims in `RESERVED`, `SETTLED`, `DENIED`, or `CLOSED_WITHOUT_PAYMENT` status, and the program's `loss_ratio` is that total divided by `premium_allocated_cents` times 100 (0 when no premium is allocated); a unit's `total_claims_incurred_cents` is the sum of `net_incurred_cents` over every claim naming the unit regardless of claim status, with the unit's `loss_ratio` computed analogously against the unit's `total_premium_allocated_cents`.

A `ClaimsAdjuster` settles a `RESERVED` claim by submitting `settlement_amount_cents` together with the OCC field `expected_captive_version` (§2.4). Settlement requires `RESERVED` (else `ERR_CLAIM_NOT_RESERVED`), requires the settlement to be no more than the program's `per_occurrence_limit_cents` (else `ERR_SETTLEMENT_EXCEEDS_LIMIT`, HTTP 400), and — when a TPA is assigned — requires the settlement to be no more than the TPA's `authority_limit_cents` (else `ERR_SETTLEMENT_EXCEEDS_TPA_AUTHORITY`, HTTP 400). On success the claim transitions to `SETTLED`, `paid_amount_cents` is set to `settlement_amount_cents`, `reserved_amount_cents` is reset to zero, and `payment_status` flips to `FULLY_PAID` when the settlement is at least the previously reserved amount, or to `PARTIALLY_PAID` otherwise. The captive's `admitted_assets` is reduced by the settlement, the program's `claims_paid_cents` is updated, the captive's `total_reserves_held` is reduced, and the captive's `version` is incremented.

Two sibling terminal transitions share `RESERVED` as their source. Denying the claim moves it `RESERVED → DENIED`, releases the reserve (setting `reserved_amount_cents` to zero), reduces the captive's `total_reserves_held`, and reduces the program's `claims_incurred_cents`. Closing without payment moves it `RESERVED → CLOSED_WITHOUT_PAYMENT` and applies the same three side effects, but additionally requires that `paid_amount_cents` is zero (else `ERR_CLAIM_HAS_PAYMENTS`, HTTP 409). Denial also requires `RESERVED` (else `ERR_CLAIM_NOT_RESERVED`); close-without-payment likewise requires `RESERVED` (else `ERR_CLAIM_NOT_RESERVED`).

TPA oversight is cyclic. A `CaptiveManager` creates a `TPAAssignment` on a claim by naming `tpa_firm_name`, `tpa_contact_email`, `authority_limit_cents`, `fee_structure` (one of `FLAT_FEE`, `PER_CLAIM`, `PERCENTAGE_OF_SAVINGS`), and `fee_amount_cents`. The assignment is born `ACTIVE` with `performance_score` set to `100`, `sla_compliance_pct` initialised to `100.0`, and `assignment_date` stamped with the current logical instant; creation also points the parent claim's `tpa_assigned_id` at the new assignment. A `CaptiveManager` may suspend an `ACTIVE` TPA when its `performance_score` has fallen below `60` or its `sla_compliance_pct` has fallen below `80`; suspension from any other state is rejected with `ERR_TPA_NOT_ACTIVE`, and suspension without either ground is rejected with `ERR_NO_SUSPENSION_GROUNDS`. Suspension changes only the TPA's status; the parent claim is not modified. A `CaptiveManager` may reinstate a `SUSPENDED` TPA back to `ACTIVE` (else `ERR_TPA_NOT_SUSPENDED`), and may terminate a TPA that is either `ACTIVE` or `SUSPENDED` (else `ERR_TPA_NOT_TERMINABLE`). Termination nulls the parent claim's `tpa_assigned_id` and leaves the claim in its current state, requiring a fresh TPA assignment before further settlement activity.

### 3.7. Actuarial Reserves and Certification

An `Actuary` creates an `ActuarialReserve` against a program by naming `reserve_type` (one of `CASE_RESERVE`, `IBNR_RESERVE`, `LAE_RESERVE`, `UNALLOCATED_EXPENSE`), `actuarial_method` (one of `CHAIN_LADDER`, `BORNHUETTER_FERGUSON`, `EXPECTED_LOSS_RATIO`, `BERQUIST_SHERMAN`), `valuation_date`, and an optional `confidence_level_pct` (between 50 and 95, default `75`). The reserve is born `PRELIMINARY`, and the system computes `central_estimate_cents`, `low_estimate_cents`, `high_estimate_cents`, and `development_factor` according to the chosen method.

The four methods are: under `CHAIN_LADDER`, `development_factor` is the published age-to-age factor for the program's line of business — `GENERAL_LIABILITY` 1.60, `WORKERS_COMP` 1.40, `PROPERTY` 1.20, `PROFESSIONAL_LIABILITY` 1.70, `CYBER` 1.30, `D_AND_O` 1.50 — and `central_estimate_cents` is the cumulative paid losses multiplied by one less than the development factor. Under `BORNHUETTER_FERGUSON`, the central estimate is the expected loss ratio multiplied by the program's `premium_allocated_cents` and then multiplied by one minus the reciprocal of the development factor. Under `EXPECTED_LOSS_RATIO`, the central estimate is the expected loss ratio multiplied by `premium_allocated_cents` minus the paid losses. The expected loss ratio used by these two methods is 0.65 for every line of business. Under `BERQUIST_SHERMAN`, the central estimate equals the chain-ladder result, with no further adjustment. For all four methods the `low_estimate_cents` is the central estimate multiplied by one minus the margin percentage (the default margin is 20%), the `high_estimate_cents` is the central estimate multiplied by one plus the margin, and the `carried_reserve_cents` is interpolated as `central + t × (high − central)` with `t = (confidence_level_pct − 50) / 45` clamped to the [0, 1] interval. All reserve figures are integer cents, rounded half-up; a minimum reserve floor of 10000 cents is applied to each of the central, low, and high estimates after rounding, and the carried reserve is finally clamped into the [low, high] band. When the program has a fronting arrangement, the central estimate is always netted — multiplied by one minus the arrangement's `reinsurance_ceded_pct` before the margin band is applied; otherwise the gross figure is used.

Reviewing by an `Actuary` moves the reserve `PRELIMINARY → REVIEWED` and recomputes the three estimates; reviewing from any other state is rejected with `ERR_RESERVE_NOT_PRELIMINARY`. Certifying by an `Actuary` moves the reserve `REVIEWED → CERTIFIED`. Certification requires `REVIEWED` (else `ERR_RESERVE_NOT_REVIEWED`), requires the supplied `carried_reserve_cents` to lie between `low_estimate_cents` and `high_estimate_cents` inclusive (else `ERR_RESERVE_OUT_OF_RANGE`, HTTP 400; a missing or non-numeric `carried_reserve_cents` is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and is subject to segregation of duties: the certifying `X-User-ID` must differ from the `X-User-ID` that created the reserve (else `ERR_SEGREGATION_OF_DUTIES`). On certification, `certified_by` is stamped with the acting user's `X-User-ID`, `certification_date` is stamped with the current UTC instant, and the captive's `total_reserves_held` is updated. Filing by a `CaptiveManager` moves the reserve `CERTIFIED → FILED` (else `ERR_RESERVE_NOT_CERTIFIED`); filing also updates the same-year `AnnualStatement`'s `total_liabilities_cents`. Creating a new reserve for the same program, same `reserve_type`, and a later `valuation_date` automatically marks the prior `CERTIFIED` reserve as `SUPERSEDED` and recomputes `total_reserves_held`.

### 3.8. Annual Statement, RBC, and Board Approval

A `CaptiveManager` opens an `AnnualStatement` for a captive by supplying `statement_year` and `investment_income_cents`. The statement is born `DRAFT`, and the system computes the regulatory `filing_deadline`, the `total_assets_cents`, `total_liabilities_cents`, `policyholder_surplus_cents` (the difference between assets and liabilities), `net_premium_written_cents`, `net_losses_incurred_cents`, `expense_ratio`, `combined_ratio` (the sum of the captive-level loss ratio — net losses incurred divided by net premium written, times 100 — and the expense ratio, expressed as a percentage), `underwriting_result_cents`, `rbc_ratio`, and `rbc_action_level`. The `filing_deadline` is May 31 of the year following `statement_year`. `total_assets_cents` is the captive's current `admitted_assets`; `total_liabilities_cents` is the sum of the `carried_reserve_cents` of the captive's `CERTIFIED` and `FILED` reserves plus the `reserved_amount_cents` of all of the captive's claims; `net_premium_written_cents` is the captive's `total_premium_written`; `net_losses_incurred_cents` is the sum of `net_incurred_cents` over all of the captive's claims; the `expense_ratio` is the total of `fee_amount_cents` across the captive's TPA assignments divided by net premium written, times 100 (0 when no premium is written); and `underwriting_result_cents` is net premium written minus net losses incurred minus total TPA fees — investment income is not part of the underwriting result. The `rbc_ratio` is the `policyholder_surplus_cents` divided by the authorised-control-level capital (a base of 50000000 cents), expressed as a percentage; the `rbc_action_level` is `NONE` when the ratio is at least 200, `COMPANY_ACTION` when at least 150 but strictly less than 200, `REGULATORY_ACTION` when at least 100 but strictly less than 150, `AUTHORIZED_CONTROL` when at least 70 but strictly less than 100, and `MANDATORY_CONTROL` when strictly below 70.

A `CaptiveManager` submits the statement for actuarial review, moving it `DRAFT → ACTUARIAL_REVIEW` and recomputing every computed field; submitting from any other state is rejected with `ERR_STATEMENT_NOT_DRAFT`. A `BoardDirector` then board-approves the statement, moving it `ACTUARIAL_REVIEW → BOARD_APPROVED`. Board approval requires the statement to be `ACTUARIAL_REVIEW` (else `ERR_STATEMENT_NOT_UNDER_REVIEW`), requires every `ActuarialReserve` whose `valuation_date` falls in the statement's year to be `CERTIFIED`, `FILED`, or `SUPERSEDED` (else `ERR_UNCERTIFIED_RESERVES`, HTTP 409), and requires a `BoardMeeting` in `MINUTES_APPROVED` status to exist for the approval (else `ERR_NO_BOARD_APPROVAL_MEETING`, HTTP 400). Board approval adds `5` to the captive's `governance_score`, capped at `100`. A `CaptiveManager` then files the approved statement, moving it `BOARD_APPROVED → FILED`; filing requires `BOARD_APPROVED` (else `ERR_STATEMENT_NOT_BOARD_APPROVED`) and requires the current UTC instant to be at or before the `filing_deadline` (else `ERR_FILING_DEADLINE_PASSED`, HTTP 400). A filed statement may be amended by a `CaptiveManager`; amendment moves it `FILED → AMENDED` (else `ERR_STATEMENT_NOT_FILED`), spawns a fresh `DRAFT` statement for the same `statement_year`, and decrements the captive's `governance_score` by `5`.

### 3.9. Board Meetings and Governance Documentation

A `BoardDirector` schedules a `BoardMeeting` with `meeting_date`, `meeting_type` (one of `ANNUAL`, `QUARTERLY`, `SPECIAL`, `EMERGENCY`), `directors_present`, and an `agenda_items` array where each entry carries `item_number`, `description`, and `resolution_required`. The meeting is born `SCHEDULED`, and the system sets `quorum_required` to 3 for every captive and computes `quorum_met` (true when `directors_present` is at least `quorum_required`).

Convening by a `BoardDirector` moves the meeting `SCHEDULED → IN_SESSION`; convening requires `SCHEDULED` (else `ERR_MEETING_NOT_SCHEDULED`) and requires `quorum_met` to be true (else `ERR_QUORUM_NOT_MET`, HTTP 400). Drafting minutes by a `BoardDirector` moves the meeting `IN_SESSION → MINUTES_DRAFTED` (else `ERR_MEETING_NOT_IN_SESSION`), and populates `resolutions_passed` — the request body may supply the array; when omitted, one entry per agenda item is auto-populated with `item_number` copied from the item, `resolution_text` copied from the item's `description`, and `vote_result` `PASSED` — together with the `minutes_document_url`. Approving minutes by a `BoardDirector` moves the meeting `MINUTES_DRAFTED → MINUTES_APPROVED`; approval requires `MINUTES_DRAFTED` (else `ERR_MINUTES_NOT_DRAFTED`) and is subject to segregation of duties against the drafting user (else `ERR_SEGREGATION_OF_DUTIES`). When `meeting_type` is `ANNUAL`, approving minutes also sets `annual_meeting_completed` to true. A `CaptiveManager` files the approved minutes, moving the meeting `MINUTES_APPROVED → FILED` (else `ERR_MINUTES_NOT_APPROVED`). A `BoardDirector` may cancel a `SCHEDULED` meeting, moving it to `CANCELLED`; cancelling from any other state is rejected with `ERR_MEETING_NOT_SCHEDULED`.

### 3.10. Tax Positions and Risk Distribution

A `TaxAdvisor` opens a `TaxPosition` for a captive with `tax_year`, `position_type` (one of `PREMIUM_DEDUCTIBILITY`, `RISK_DISTRIBUTION`, `MICRO_CAPTIVE_ELECTION`, `ARM_LENGTH_PRICING`, `EXCISE_TAX_EXEMPTION`), and `position_description`. The position is born `DRAFT`. Analysis by a `TaxAdvisor` moves it `DRAFT → ANALYZED` (else `ERR_TAX_POSITION_NOT_DRAFT`) and computes six fields.

The risk-distribution analysis walks three pillars. The entity pillar counts the `insured_entities_count` — the number of distinct `operating_unit_id` values appearing on any premium allocation (of any status) or claim whose program is `IN_FORCE` or `RUN_OFF` — and contributes 40 points when at least 12 units are insured, 20 points when at least 6 but fewer than 12 are insured, and 0 points otherwise. The third-party pillar computes `third_party_premium_pct` — the percentage of total allocated premium (the sum of `allocated_amount_cents` over the captive's `PROVISIONAL`, `AUDITED`, and `FINALIZED` allocations) attributed to units that do not belong to the captive; in practice this is always zero, since allocation creation requires the unit to belong to the same captive — and contributes 30 points when the percentage is at least 30, 15 points when it is at least 15 but strictly less than 30, and 0 points otherwise. The concentration pillar computes the largest single unit's share of total premium and contributes 30 points when that concentration is at most 50 percent, 15 points when it is greater than 50 but at most 75 percent, and 0 points above 75 percent. The `risk_distribution_score` is the sum of the three pillar scores; the `risk_distribution_test_result` is `PASS` when the score is at least 70, `MARGINAL` when the score is at least 40 but strictly less than 70, and `FAIL` when strictly below 40. Analysis also computes `insured_entities_count`, `third_party_premium_pct`, `premium_threshold_met` (true when total premium does not exceed the micro-captive 831(b) premium limit of 265000000 cents), `premium_deductibility_pct` (100.0 when the risk-distribution test is `PASS`, 50.0 when `MARGINAL`, 0.0 when `FAIL`), and `disclosure_required` (true when the captive is a `MICRO_CAPTIVE_831B` whose total premium exceeds the 265000000-cent limit, or when the risk-distribution test result is `FAIL`). When the captive's `tax_classification` is `MICRO_CAPTIVE_831B` and total premium exceeds 265000000 cents, analysis is rejected with `ERR_PREMIUM_THRESHOLD_EXCEEDED` (HTTP 400).

Issuing an opinion by a `TaxAdvisor` moves the position `ANALYZED → OPINION_ISSUED`; the body carries `reporting_position` (one of `MORE_LIKELY_THAN_NOT`, `SUBSTANTIAL_AUTHORITY`, `REASONABLE_BASIS`, `NO_POSITION`). Issuing from any other state is rejected with `ERR_TAX_POSITION_NOT_ANALYZED`, and issuing without a `reporting_position` value is rejected with `ERR_NO_REPORTING_POSITION` (HTTP 400). Both analysis and opinion issuance refresh the captive's `risk_distribution_score`. Filing by a `CaptiveManager` moves the position `OPINION_ISSUED → FILED` (else `ERR_TAX_POSITION_NOT_OPINION_ISSUED`). Challenging a filed position by a `TaxAdvisor` moves it `FILED → CHALLENGED` (else `ERR_TAX_POSITION_NOT_FILED`), decrements the captive's `governance_score` by `15`, and spawns a fresh `DRAFT` position for the same `tax_year` and `position_type`.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource or query resources respond with HTTP 200. All endpoints are mounted under `/api` except the clock test-driving endpoint. All list endpoints accept the optional `limit` and `offset` query parameters described in §2.3. Several nested list endpoints additionally accept exact-match query filters beyond those noted in the table below: premium allocations by `operating_unit_id`; claims by `operating_unit_id` and `claim_status`; reserves by `reserve_type` and `status`; board meetings by `meeting_type` and `status`; and tax positions by `tax_year` and `position_type`. Requests to unknown routes, or with unsupported methods, are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/captives | Create a new captive entity | CaptiveManager |
| GET | /api/captives | List all captive entities | CaptiveManager, DomicileRegulator, Underwriter, Actuary, ClaimsAdjuster, BoardDirector, TaxAdvisor |
| GET | /api/captives/{captiveId} | Get a specific captive entity | CaptiveManager, DomicileRegulator, Underwriter, Actuary, ClaimsAdjuster, BoardDirector, TaxAdvisor |
| POST | /api/captives/{captiveId}/activate | Activate a capitalized captive | CaptiveManager |
| POST | /api/captives/{captiveId}/suspend | Suspend an active captive | DomicileRegulator |
| POST | /api/captives/{captiveId}/reinstate | Reinstate a suspended captive | DomicileRegulator |
| POST | /api/captives/{captiveId}/dissolve | Dissolve a captive | CaptiveManager, DomicileRegulator |
| POST | /api/captives/{captiveId}/domicile-filings | Create a domicile filing | CaptiveManager |
| GET | /api/captives/{captiveId}/domicile-filings | List domicile filings for a captive | CaptiveManager, DomicileRegulator |
| GET | /api/captives/{captiveId}/domicile-filings/{filingId} | Get a specific domicile filing | CaptiveManager, DomicileRegulator |
| POST | /api/captives/{captiveId}/domicile-filings/{filingId}/submit | Submit a domicile filing | CaptiveManager |
| POST | /api/captives/{captiveId}/domicile-filings/{filingId}/acknowledge | Regulator acknowledges filing | DomicileRegulator |
| POST | /api/captives/{captiveId}/domicile-filings/{filingId}/approve | Approve a domicile filing | DomicileRegulator |
| POST | /api/captives/{captiveId}/domicile-filings/{filingId}/reject | Reject a domicile filing | DomicileRegulator |
| POST | /api/captives/{captiveId}/domicile-filings/{filingId}/withdraw | Withdraw a domicile filing | CaptiveManager |
| POST | /api/captives/{captiveId}/programs | Create an insurance program | Underwriter |
| GET | /api/captives/{captiveId}/programs | List programs for a captive | CaptiveManager, Underwriter, Actuary, ClaimsAdjuster |
| GET | /api/captives/{captiveId}/programs/{programId} | Get a specific program | CaptiveManager, Underwriter, Actuary, ClaimsAdjuster |
| POST | /api/captives/{captiveId}/programs/{programId}/quote | Quote a program | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/bind | Bind a quoted program | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/activate | Activate a bound program | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/enter-runoff | Enter run-off for a program | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/close | Close a program in run-off | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/cancel | Cancel a draft or quoted program | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/fronting | Create a fronting arrangement | Underwriter |
| GET | /api/captives/{captiveId}/programs/{programId}/fronting | List fronting arrangements for a program | CaptiveManager, Underwriter |
| GET | /api/captives/{captiveId}/programs/{programId}/fronting/{frontingId} | Get a specific fronting arrangement | CaptiveManager, Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/fronting/{frontingId}/agree-terms | Agree to fronting terms | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/fronting/{frontingId}/post-collateral | Post collateral for fronting | CaptiveManager |
| POST | /api/captives/{captiveId}/programs/{programId}/fronting/{frontingId}/activate | Activate fronting arrangement | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/fronting/{frontingId}/terminate | Terminate a fronting arrangement | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/fronting/{frontingId}/collateral | Post a collateral posting | CaptiveManager |
| GET | /api/captives/{captiveId}/programs/{programId}/fronting/{frontingId}/collateral | List collateral postings | CaptiveManager, Underwriter |
| GET | /api/captives/{captiveId}/programs/{programId}/fronting/{frontingId}/collateral/{collateralId} | Get a specific collateral posting | CaptiveManager, Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/fronting/{frontingId}/collateral/{collateralId}/verify | Verify a collateral posting | CaptiveManager |
| POST | /api/captives/{captiveId}/operating-units | Create an operating unit | CaptiveManager |
| GET | /api/captives/{captiveId}/operating-units | List operating units | CaptiveManager, Underwriter, Actuary |
| GET | /api/captives/{captiveId}/operating-units/{unitId} | Get a specific operating unit | CaptiveManager, Underwriter, Actuary |
| POST | /api/captives/{captiveId}/programs/{programId}/allocations | Create a premium allocation | Underwriter |
| GET | /api/captives/{captiveId}/programs/{programId}/allocations | List premium allocations for a program | CaptiveManager, Underwriter, Actuary |
| GET | /api/captives/{captiveId}/programs/{programId}/allocations/{allocId} | Get a specific premium allocation | CaptiveManager, Underwriter, Actuary |
| POST | /api/captives/{captiveId}/programs/{programId}/allocations/{allocId}/audit | Audit a provisional allocation | Actuary |
| POST | /api/captives/{captiveId}/programs/{programId}/allocations/{allocId}/finalize | Finalize an audited allocation | Actuary |
| POST | /api/captives/{captiveId}/programs/{programId}/allocations/{allocId}/dispute | Dispute a provisional allocation | CaptiveManager |
| POST | /api/captives/{captiveId}/programs/{programId}/allocations/{allocId}/resolve-dispute | Resolve a disputed allocation | CaptiveManager |
| POST | /api/captives/{captiveId}/programs/{programId}/allocations/{allocId}/cancel | Cancel a provisional or disputed allocation | Underwriter |
| POST | /api/captives/{captiveId}/programs/{programId}/claims | Report a new claim | ClaimsAdjuster |
| GET | /api/captives/{captiveId}/programs/{programId}/claims | List claims for a program | CaptiveManager, Underwriter, Actuary, ClaimsAdjuster |
| GET | /api/captives/{captiveId}/programs/{programId}/claims/{claimId} | Get a specific claim | CaptiveManager, Underwriter, Actuary, ClaimsAdjuster |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/acknowledge | Acknowledge a reported claim | ClaimsAdjuster |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/investigate | Start investigation on a claim | ClaimsAdjuster |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/set-reserve | Set reserve on a claim | Actuary |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/settle | Settle a reserved claim | ClaimsAdjuster |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/deny | Deny a reserved claim | ClaimsAdjuster |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/close-without-payment | Close a claim without payment | ClaimsAdjuster |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/tpa | Assign a TPA to a claim | CaptiveManager |
| GET | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/tpa | List TPA assignments for a claim | CaptiveManager, ClaimsAdjuster |
| GET | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/tpa/{tpaId} | Get a specific TPA assignment | CaptiveManager, ClaimsAdjuster |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/tpa/{tpaId}/suspend | Suspend a TPA | CaptiveManager |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/tpa/{tpaId}/reinstate | Reinstate a suspended TPA | CaptiveManager |
| POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/tpa/{tpaId}/terminate | Terminate a TPA | CaptiveManager |
| POST | /api/captives/{captiveId}/programs/{programId}/reserves | Create an actuarial reserve | Actuary |
| GET | /api/captives/{captiveId}/programs/{programId}/reserves | List reserves for a program | CaptiveManager, Underwriter, Actuary |
| GET | /api/captives/{captiveId}/programs/{programId}/reserves/{reserveId} | Get a specific reserve | CaptiveManager, Underwriter, Actuary |
| POST | /api/captives/{captiveId}/programs/{programId}/reserves/{reserveId}/review | Review a preliminary reserve | Actuary |
| POST | /api/captives/{captiveId}/programs/{programId}/reserves/{reserveId}/certify | Certify a reviewed reserve | Actuary |
| POST | /api/captives/{captiveId}/programs/{programId}/reserves/{reserveId}/file | File a certified reserve | CaptiveManager |
| POST | /api/captives/{captiveId}/annual-statements | Create an annual statement | CaptiveManager |
| GET | /api/captives/{captiveId}/annual-statements | List annual statements | CaptiveManager, Actuary, BoardDirector |
| GET | /api/captives/{captiveId}/annual-statements/{statementId} | Get a specific annual statement | CaptiveManager, Actuary, BoardDirector |
| POST | /api/captives/{captiveId}/annual-statements/{statementId}/submit-for-review | Submit annual statement for actuarial review | CaptiveManager |
| POST | /api/captives/{captiveId}/annual-statements/{statementId}/board-approve | Board approves annual statement | BoardDirector |
| POST | /api/captives/{captiveId}/annual-statements/{statementId}/file | File annual statement with regulator | CaptiveManager |
| POST | /api/captives/{captiveId}/annual-statements/{statementId}/amend | Amend a filed annual statement | CaptiveManager |
| POST | /api/captives/{captiveId}/board-meetings | Schedule a board meeting | BoardDirector |
| GET | /api/captives/{captiveId}/board-meetings | List board meetings | CaptiveManager, BoardDirector |
| GET | /api/captives/{captiveId}/board-meetings/{meetingId} | Get a specific board meeting | CaptiveManager, BoardDirector |
| POST | /api/captives/{captiveId}/board-meetings/{meetingId}/convene | Convene a scheduled board meeting | BoardDirector |
| POST | /api/captives/{captiveId}/board-meetings/{meetingId}/draft-minutes | Draft minutes for an in-session meeting | BoardDirector |
| POST | /api/captives/{captiveId}/board-meetings/{meetingId}/approve-minutes | Approve drafted minutes | BoardDirector |
| POST | /api/captives/{captiveId}/board-meetings/{meetingId}/file | File approved minutes | CaptiveManager |
| POST | /api/captives/{captiveId}/board-meetings/{meetingId}/cancel | Cancel a scheduled meeting | BoardDirector |
| POST | /api/captives/{captiveId}/tax-positions | Create a tax position | TaxAdvisor |
| GET | /api/captives/{captiveId}/tax-positions | List tax positions | CaptiveManager, TaxAdvisor |
| GET | /api/captives/{captiveId}/tax-positions/{positionId} | Get a specific tax position | CaptiveManager, TaxAdvisor |
| POST | /api/captives/{captiveId}/tax-positions/{positionId}/analyze | Analyze a tax position | TaxAdvisor |
| POST | /api/captives/{captiveId}/tax-positions/{positionId}/issue-opinion | Issue opinion on analyzed position | TaxAdvisor |
| POST | /api/captives/{captiveId}/tax-positions/{positionId}/file | File a tax position | CaptiveManager |
| POST | /api/captives/{captiveId}/tax-positions/{positionId}/challenge | Challenge a filed tax position | TaxAdvisor |
| GET | /api/captives/{captiveId}/audit-logs | List audit logs for a captive | CaptiveManager, DomicileRegulator |
| GET | /api/captives/{captiveId}/audit-logs/{logId} | Get a specific audit log | CaptiveManager, DomicileRegulator |
| GET | /api/domicile-filings/{filingId} | Get a specific domicile filing (flat) | CaptiveManager, DomicileRegulator |
| GET | /api/programs/{programId} | Get a specific program (flat) | CaptiveManager, Underwriter, Actuary, ClaimsAdjuster |
| GET | /api/fronting-arrangements/{frontingId} | Get a specific fronting arrangement (flat) | CaptiveManager, Underwriter |
| GET | /api/collateral-postings/{collateralId} | Get a specific collateral posting (flat) | CaptiveManager, Underwriter |
| GET | /api/operating-units/{unitId} | Get a specific operating unit (flat) | CaptiveManager, Underwriter, Actuary |
| GET | /api/premium-allocations/{allocId} | Get a specific premium allocation (flat) | CaptiveManager, Underwriter, Actuary |
| GET | /api/claims/{claimId} | Get a specific claim (flat) | CaptiveManager, Underwriter, Actuary, ClaimsAdjuster |
| GET | /api/tpa-assignments/{tpaId} | Get a specific TPA assignment (flat) | CaptiveManager, ClaimsAdjuster |
| GET | /api/actuarial-reserves/{reserveId} | Get a specific actuarial reserve (flat) | CaptiveManager, Underwriter, Actuary |
| GET | /api/annual-statements/{statementId} | Get a specific annual statement (flat) | CaptiveManager, Actuary, BoardDirector |
| GET | /api/board-meetings/{meetingId} | Get a specific board meeting (flat) | CaptiveManager, BoardDirector |
| GET | /api/tax-positions/{positionId} | Get a specific tax position (flat) | CaptiveManager, TaxAdvisor |
| GET | /api/audit-logs/{logId} | Get a specific audit log (flat) | CaptiveManager, DomicileRegulator |
| GET | /api/domicile-filings | List domicile filings (filtered by `captive_id`) | CaptiveManager, DomicileRegulator |
| GET | /api/programs | List programs (filtered by `captive_id`) | CaptiveManager, Underwriter, Actuary, ClaimsAdjuster |
| GET | /api/fronting-arrangements | List fronting arrangements (filtered by `program_id`, `captive_id`) | CaptiveManager, Underwriter |
| GET | /api/collateral-postings | List collateral postings (filtered by `fronting_arrangement_id`) | CaptiveManager, Underwriter |
| GET | /api/operating-units | List operating units (filtered by `captive_id`) | CaptiveManager, Underwriter, Actuary |
| GET | /api/premium-allocations | List premium allocations (filtered by `program_id`, `operating_unit_id`, `captive_id`) | CaptiveManager, Underwriter, Actuary |
| GET | /api/claims | List claims (filtered by `program_id`, `operating_unit_id`, `captive_id`, `tpa_assigned_id`) | CaptiveManager, Underwriter, Actuary, ClaimsAdjuster |
| GET | /api/tpa-assignments | List TPA assignments (filtered by `claim_id`) | CaptiveManager, ClaimsAdjuster |
| GET | /api/actuarial-reserves | List actuarial reserves (filtered by `program_id`, `captive_id`) | CaptiveManager, Underwriter, Actuary |
| GET | /api/annual-statements | List annual statements (filtered by `captive_id`) | CaptiveManager, Actuary, BoardDirector |
| GET | /api/board-meetings | List board meetings (filtered by `captive_id`) | CaptiveManager, BoardDirector |
| GET | /api/tax-positions | List tax positions (filtered by `captive_id`) | CaptiveManager, TaxAdvisor |
| GET | /api/audit-logs | List audit logs (filtered by `captive_id`, `entity_type`, `action_type`) | CaptiveManager, DomicileRegulator |
| POST | /_clock/set_current_utc | Set the logical clock to a specific UTC timestamp | CaptiveManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_POLICY_PERIOD | 400 |
| ERR_INVALID_COLLATERAL_DATES | 400 |
| ERR_CAPTIVE_NOT_FOUND | 404 |
| ERR_FILING_NOT_FOUND | 404 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_FRONTING_NOT_FOUND | 404 |
| ERR_COLLATERAL_NOT_FOUND | 404 |
| ERR_OPERATING_UNIT_NOT_FOUND | 404 |
| ERR_ALLOCATION_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_TPA_NOT_FOUND | 404 |
| ERR_RESERVE_NOT_FOUND | 404 |
| ERR_STATEMENT_NOT_FOUND | 404 |
| ERR_MEETING_NOT_FOUND | 404 |
| ERR_TAX_POSITION_NOT_FOUND | 404 |
| ERR_AUDIT_LOG_NOT_FOUND | 404 |
| ERR_CAPITALIZATION_BELOW_MINIMUM | 400 |
| ERR_INSUFFICIENT_COLLATERAL | 400 |
| ERR_ALLOCATION_EXCEEDS_BUDGET | 400 |
| ERR_SETTLEMENT_EXCEEDS_LIMIT | 400 |
| ERR_SETTLEMENT_EXCEEDS_TPA_AUTHORITY | 400 |
| ERR_RESERVE_OUT_OF_RANGE | 400 |
| ERR_PREMIUM_THRESHOLD_EXCEEDED | 400 |
| ERR_SOLVENCY_BREACH | 403 |
| ERR_CAPTIVE_NOT_IN_FORMATION | 409 |
| ERR_CAPTIVE_NOT_DOMICILE_FILED | 409 |
| ERR_CAPTIVE_NOT_CAPITALIZED | 409 |
| ERR_CAPTIVE_NOT_ACTIVE | 409 |
| ERR_CAPTIVE_NOT_SUSPENDED | 409 |
| ERR_CAPTIVE_NOT_OPERATIONAL | 409 |
| ERR_FILING_NOT_DRAFT | 409 |
| ERR_FILING_NOT_SUBMITTED | 409 |
| ERR_FILING_NOT_UNDER_REVIEW | 409 |
| ERR_FILING_NOT_WITHDRAWABLE | 409 |
| ERR_PROGRAM_NOT_DRAFT | 409 |
| ERR_PROGRAM_NOT_QUOTED | 409 |
| ERR_PROGRAM_NOT_BOUND | 409 |
| ERR_PROGRAM_NOT_IN_FORCE | 409 |
| ERR_PROGRAM_NOT_IN_RUNOFF | 409 |
| ERR_PROGRAM_NOT_CANCELLABLE | 409 |
| ERR_FRONTING_NOT_READY | 409 |
| ERR_FRONTING_NOT_NEGOTIATING | 409 |
| ERR_FRONTING_NOT_TERMS_AGREED | 409 |
| ERR_FRONTING_NOT_COLLATERAL_POSTED | 409 |
| ERR_FRONTING_NOT_ACTIVE | 409 |
| ERR_CLAIM_NOT_REPORTED | 409 |
| ERR_CLAIM_NOT_ACKNOWLEDGED | 409 |
| ERR_CLAIM_NOT_UNDER_INVESTIGATION | 409 |
| ERR_CLAIM_NOT_RESERVED | 409 |
| ERR_CLAIM_HAS_PAYMENTS | 409 |
| ERR_ALLOCATION_NOT_PROVISIONAL | 409 |
| ERR_ALLOCATION_NOT_AUDITED | 409 |
| ERR_ALLOCATION_NOT_DISPUTED | 409 |
| ERR_ALLOCATION_NOT_CANCELLABLE | 409 |
| ERR_ALLOCATION_NOT_COMPUTED | 409 |
| ERR_RESERVE_NOT_PRELIMINARY | 409 |
| ERR_RESERVE_NOT_REVIEWED | 409 |
| ERR_RESERVE_NOT_CERTIFIED | 409 |
| ERR_STATEMENT_NOT_DRAFT | 409 |
| ERR_STATEMENT_NOT_UNDER_REVIEW | 409 |
| ERR_STATEMENT_NOT_BOARD_APPROVED | 409 |
| ERR_STATEMENT_NOT_FILED | 409 |
| ERR_MEETING_NOT_SCHEDULED | 409 |
| ERR_MEETING_NOT_IN_SESSION | 409 |
| ERR_MINUTES_NOT_DRAFTED | 409 |
| ERR_MINUTES_NOT_APPROVED | 409 |
| ERR_TAX_POSITION_NOT_DRAFT | 409 |
| ERR_TAX_POSITION_NOT_ANALYZED | 409 |
| ERR_TAX_POSITION_NOT_OPINION_ISSUED | 409 |
| ERR_TAX_POSITION_NOT_FILED | 409 |
| ERR_TPA_NOT_ACTIVE | 409 |
| ERR_TPA_NOT_SUSPENDED | 409 |
| ERR_TPA_NOT_TERMINABLE | 409 |
| ERR_NO_BOUND_PROGRAM | 409 |
| ERR_ACTIVE_PROGRAMS_EXIST | 409 |
| ERR_OPEN_CLAIMS_EXIST | 409 |
| ERR_UNFILED_RESERVES_EXIST | 409 |
| ERR_NO_SUPPORTING_DOCUMENTS | 400 |
| ERR_POLICY_PERIOD_OVERLAP | 409 |
| ERR_LOSS_DATE_OUT_OF_PERIOD | 400 |
| ERR_FILING_DEADLINE_PASSED | 400 |
| ERR_QUORUM_NOT_MET | 400 |
| ERR_NO_BOARD_APPROVAL_MEETING | 400 |
| ERR_COVERAGE_NOT_CONFIRMED | 400 |
| ERR_OPERATING_UNIT_MISMATCH | 400 |
| ERR_NO_SUSPENSION_GROUNDS | 400 |
| ERR_GOVERNANCE_SCORE_TOO_LOW | 403 |
| ERR_NO_REPORTING_POSITION | 400 |
| ERR_UNCERTIFIED_RESERVES | 409 |
| ERR_STALE_VERSION | 412 |
