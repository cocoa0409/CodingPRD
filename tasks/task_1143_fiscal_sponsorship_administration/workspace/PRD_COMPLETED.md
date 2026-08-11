# Fiscal Sponsorship Administration API — Product Requirements Document

## 1. Introduction

A fiscal sponsor extends its own charitable tax status, financial controls, and compliance apparatus to externally organized projects that have not — or not yet — incorporated as independent entities. That arrangement concentrates accountability in one place: gifts are received under the sponsor's tax status and must be receipted against it; every dollar of project spending must trace back to a charitable purpose; worker classification carries employment-law exposure; and each project eventually either spins off into an independent successor or winds down under sponsor oversight. This document specifies the Fiscal Sponsorship Administration API, the system of record for that entire lifecycle.

The API governs seven intertwined concerns: application intake with a weighted mission-alignment scorecard; selection between two sponsorship models — comprehensive sponsorship and the pre-approved grant relationship — with features gated by the granted model; per-project fund accounting over an append-only ledger with model-dependent administrative fees; donation pledging, receipting, and refund handling; a multi-stage spending-approval pipeline with strict segregation of duties; engagement of project staff as employees or contractors with year-to-date tax reporting thresholds; compliance reviews and risk incidents that feed a computed oversight posture; and finally project exit — spin-off through a three-party-signed settlement waterfall, or termination at zero balance. All resources are mounted under `/fsa`, with one exception: an administrative logical-clock capability, described in §2.4, that makes every time-dependent rule deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly seven roles: `Applicant`, `ProjectLead`, `ProgramOfficer`, `ComplianceOfficer`, `FinanceOfficer`, `SponsorAdmin`, and `Donor`. A request missing either header, presenting a blank value, or naming a role outside this set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the target endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Where an operation is ownership-bound, a mismatch between `X-User-ID` and the resource's ownership anchor is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

Identity semantics differ by role, and each role's anchor is fixed. When `X-User-Role` is `ProjectLead`, `X-User-ID` is the `id` of the acting `Project`; ownership checks on any project-scoped write compare the target resource's `project_id` (or the path's project identifier) to `X-User-ID`. When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque external identifier not tied to any persisted entity's `id`; the server records it as `applicant_user_id` on the `ProjectApplication` at creation, and later ownership checks on submit, withdraw, and countersign compare the request's `X-User-ID` against that stored `applicant_user_id`. When `X-User-Role` is `ProgramOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier; the server may record it, for example as `compliance_approved_by_user_id` on a disbursement it approves, but never compares it to any entity's `id`. When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier, recorded for example as `paid_by_user_id` on the disbursements it pays. When `X-User-Role` is `SponsorAdmin`, `X-User-ID` is an opaque operator identifier, recorded for example as `sponsor_approved_by_user_id` on high-value approvals or as `signer_user_id` on exit-plan signoffs. When `X-User-Role` is `Donor`, `X-User-ID` is an opaque identifier not tied to any persisted entity's `id`; `Donor` is write-only on its two gift-related operations and is not authorized on any read endpoint.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; ties on `created_at` (common while the logical clock stands still) break by server insertion order, never by `id`. A `limit` below 1 or above 100 is clamped to the nearer bound, a non-numeric `limit` falls back to 10, and a negative or non-numeric `offset` falls back to 0 — malformed pagination never produces an error.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Money, Calendar Dates, and the Logical Clock

All monetary values in the system are integer cents — fields such as `amount_cents`, `fee_cents`, and `budget_estimate_cents` never carry fractional cents, and all monetary arithmetic is exact decimal arithmetic. Where a calculation requires rounding, the rounding method is round half up, applied at the granularity the calculation specifies; no calculation ever uses banker's rounding or truncation.

Date fields are ISO 8601 calendar dates in `YYYY-MM-DD` form unless the field name ends with the `_at` suffix, which denotes an ISO 8601 UTC datetime. The server never consults wall-clock time. Instead it runs on a logical clock whose startup value is exactly `2026-05-01T00:00:00Z`. A `SponsorAdmin`-only test-driving capability, posted to `/_clock/set_current_utc` with a `to_iso8601` instant in the request body, sets the logical clock to that instant — a backward jump is permitted as well as a forward one — and returns the resulting `current_utc`; it mutates no entity. An unparseable `to_iso8601` fails schema validation with `ERR_VALIDATION` (HTTP 400). The logical clock drives `received_at` and `refunded_at` on donations, the `tax_year` of issued receipts, the accumulation year behind contractor year-to-date totals, and a tranche's eligibility to close — every one of these reads the logical clock deterministically.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix; it serves identity only and is never an input to any business decision. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits. The `updated_at` timestamp refreshes on every modification. The `version` is an integer that starts at 1 and increments by exactly 1 on every mutation — including mutations caused by system cascades rather than direct client writes. A single request that mutates the same entity several times (for example a cascade that touches one project at multiple steps) still increments its `version` by exactly 1 for that request.

One entity is exempt from part of this convention: a `FundLedgerEntry` carries only `id` and `created_at`. Both `updated_at` and `version` are absent from ledger entries, because entries are immutable once posted.

### 2.6. Fund Accounting, the Ledger, and Conservation

Each approved project owns exactly one `FundAccount`, denominated in a fixed `currency` of `USD`. The account maintains a family of running totals, each with a precise meaning. `total_received_cents` accumulates the gross amounts of donations moved from `PLEDGED` to `RECEIVED`. `total_refunded_cents` accumulates approved refund amounts. `total_fees_charged_cents` accumulates per-receipt administrative fees, grant-model annual platform fees, and the exit fee. `total_fees_reversed_cents` accumulates fee reversals posted at period close. `total_disbursed_cents` accumulates the amounts of disbursements that reached `PAID`, including payouts settled during an exit. `total_adjustments_cents` is the signed sum of manual adjustments. `total_transferred_out_cents` accumulates the exit transfer to a successor entity and any termination sweep amounts. `committed_cents` is the sum of amounts on disbursement requests currently in `SUBMITTED`, `PENDING_SPONSOR`, or `APPROVED_FOR_PAYMENT`. `reserved_cents` holds the compliance reserve created at exit execution and is zero until then.

From these totals the account derives `available_cents`: total received, minus total refunded, minus total fees charged, plus total fees reversed, minus total disbursed, minus total transferred out, plus total adjustments, minus committed, minus reserved. A second derived figure, `forward_available_cents`, adds a pledge credit to the settled figure: eighty percent of the sum of `amount_cents` over the project's donations still in `PLEDGED`, with the credit rounded half up to whole cents once after aggregation. Both figures appear, alongside `committed_cents`, `reserved_cents`, `risk_score`, `oversight_posture`, `open_findings_count`, and `open_incident_count`, on the computed project summary read.

Every movement against a fund posts one or more `FundLedgerEntry` rows, and the ledger is the audit substrate behind the totals. Each entry records its owning `fund_account_id`, an `entry_type` drawn from `DONATION_CREDIT`, `FEE_DEBIT`, `DONATION_REFUND_DEBIT`, `FEE_REVERSAL_CREDIT`, `COMMITMENT_HOLD`, `COMMITMENT_RELEASE`, `DISBURSEMENT_DEBIT`, `ADJUSTMENT`, `RESERVE_HOLD`, or `EXIT_TRANSFER_DEBIT`, a signed `amount_cents` (credits positive, debits negative), a human-readable `memo`, and — when the entry is linked to a gift or a spend — the relevant `donation_id` or `disbursement_id`, each null otherwise. The conservation invariant follows from the definitions: after any posting, `available_cents` recomputed from the totals must equal its stored value, and the exit waterfall in §3.8 settles the fund to exactly zero available.

### 2.7. Sponsorship Models and Model-Gated Features

Two sponsorship models exist. Under `COMPREHENSIVE`, the sponsor folds the project fully into its own operations; under `PRE_APPROVED_GRANT`, the relationship is a grant of pre-approved funds released through tranches. An applicant states a `requested_model` (defaulting to `COMPREHENSIVE` when omitted), but the model actually granted is fixed at compliance approval and recorded as the application's `decided_model`, which may differ from the request; the resulting `SponsorshipAgreement` copies its `model` from that decision.

Four features are gated on the granted model. First, `EMPLOYEE` engagements are legal only under `COMPREHENSIVE`; proposing one — or approving one at classification review — under `PRE_APPROVED_GRANT` is rejected with `ERR_MODEL_FORBIDS_EMPLOYMENT`. Second, grant tranches exist only under `PRE_APPROVED_GRANT`; issuing one against a comprehensive agreement is rejected with `ERR_MODEL_MISMATCH`. Third, an agreement's `spending_basis` may be `FORWARD_LOOKING` only under `COMPREHENSIVE`; the value `SETTLED` is the default and is the only legal value under `PRE_APPROVED_GRANT`, and an amendment that would set `FORWARD_LOOKING` on a grant-model agreement is rejected with `ERR_MODEL_MISMATCH`. Fourth, the two models price administration differently: comprehensive receipts pay a tiered marginal fee with a per-donation minimum and receive proportional fee reversals for refunded gifts at period close, while grant-model receipts pay a flat percentage with no minimum and no refund reversal, instead settling an annual platform fee at period close (§3.3 and §3.7 give the full arithmetic).

### 2.8. Risk Scoring and the Oversight Posture Gate

Every project carries a computed `risk_score` and a derived `oversight_posture` of `NORMAL`, `RESTRICTED`, or `SEVERE`. The open incident set comprises the project's incidents in `REPORTED`, `TRIAGED`, or `MITIGATING`; `RESOLVED` and `DISMISSED` incidents are excluded, as are reviews in `OPEN` (no findings yet), `REMEDIATED`, or `CLOSED`. The score is the sum of severity weights over open incidents — 40 for `CRITICAL`, 20 for `HIGH`, 8 for `MEDIUM`, 3 for `LOW` — plus five points per open finding, where open findings are summed from `open_findings_count` across the project's reviews in `FINDINGS_ISSUED` or `ESCALATED`. The posture bands are inclusive at their lower edge: a score of exactly 50 or more is `SEVERE`, exactly 25 up to 49 is `RESTRICTED`, and below 25 is `NORMAL`.

The posture is an orthogonal gate, not a status. `RESTRICTED` blocks two operations: activating a staff engagement, and beginning exit due diligence. `SEVERE` blocks those same two and additionally blocks receiving a donation and submitting a disbursement. All four rejections carry `ERR_SEVERE_POSTURE_BLOCKS_SPEND` (HTTP 422).

### 2.9. Segregation of Duties

No single operator may shepherd money through more than one stage of the disbursement chain. The user who submits a request may not compliance-review it; sponsor approval of a high-value request requires a user distinct from both the submitter and the compliance approver; and payment requires a user distinct from the submitter, the compliance approver, and — when one was recorded — the sponsor approver. Each stage records its actor (`submitted_by_user_id`, `compliance_approved_by_user_id`, `sponsor_approved_by_user_id`, `paid_by_user_id`), and a violation at any of the three decision points is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

Exit governance applies the same principle to signoffs: a spin-off requires three distinct signoff parties whose signer user ids are pairwise distinct, as detailed in §3.8.

### 2.10. Optimistic Concurrency Control

Two write endpoints carry optimistic concurrency control, and no other endpoint accepts a version field. Posting a manual adjustment against a fund requires `expected_fund_account_version` in the request body, carrying the `FundAccount` `version` the client last observed; if another write has advanced the fund's version since, the adjustment is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412) rather than posting a signed amount against a balance view the client never saw. Amending an agreement requires `expected_agreement_version` against the `SponsorshipAgreement` `version`; a mismatch is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), because an amendment supersedes the prior terms as a whole and must be based on their current state. Both fields are non-optional on their respective endpoints. On each endpoint the version comparison runs after the resource's state guard, so a wrong-state agreement or fund surfaces its 409 state error before staleness is examined.

### 2.11. Validation Order and Path Resolution

Every request is checked against a fixed validation pipeline, and the relative order is normative because it determines which error surfaces when several problems coexist. First, body schema: required fields present — including conditionally required ones such as `sponsorship_model` on an approving compliance decision — JSON types correct, and integer-cent fields integral, else `ERR_VALIDATION` (HTTP 400). Calendar-date fields must parse as `YYYY-MM-DD` and instants as ISO 8601 under this same gate — an unparseable `spend_date`, `period_start`, `period_end`, `start_date`, `end_date`, or `to_iso8601` fails here with `ERR_VALIDATION`. Second, enum membership: every enum field must carry a declared member, else `ERR_INVALID_ENUM` (HTTP 400). Third, authentication per §2.1 (`ERR_UNAUTHENTICATED`). Fourth, role authorization (`ERR_UNAUTHORIZED_ROLE`). Fifth, ownership (`ERR_NOT_RESOURCE_OWNER`). Sixth, path identifiers are resolved left to right: the first path id that does not resolve to an existing resource produces that resource's not-found error — `ERR_APPLICATION_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_FUND_ACCOUNT_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_EXIT_PLAN_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, or `ERR_LEDGER_ENTRY_NOT_FOUND` (all HTTP 404) — before any later identifier is examined. Seventh, state-machine guards: the target resource must be in a from-state of the requested transition, else the per-machine state error — `ERR_APPLICATION_NOT_ACTIONABLE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_PROJECT_NOT_ACTIVE`, `ERR_FUND_NOT_ACTIVE`, `ERR_DONATION_STATE_INVALID`, `ERR_RECEIPT_ALREADY_VOIDED`, `ERR_DISBURSEMENT_STATE_INVALID`, `ERR_ENGAGEMENT_STATE_INVALID`, `ERR_REVIEW_STATE_INVALID`, `ERR_INCIDENT_STATE_INVALID`, `ERR_EXIT_STATE_INVALID`, or `ERR_TRANCHE_STATE_INVALID` (all HTTP 409). Creation endpoints under a project guard the project's state only where §3 says so: drafting a disbursement, proposing an engagement, opening a review, reporting an incident, and proposing an exit plan ask only that the project exist — pledging a donation is the exception, requiring an `ACTIVE` project per §3.3.

Only after those seven gates do the domain rules run, in this defined sequence: employment-classification legality (`ERR_MODEL_FORBIDS_EMPLOYMENT`), segregation of duties (`ERR_SOD_VIOLATION`), the open-critical-incident gate (`ERR_CRITICAL_INCIDENT_OPEN`), the open-compliance gate on exit due diligence (`ERR_OPEN_COMPLIANCE_BLOCKS_EXIT`), the oversight-posture gates (`ERR_SEVERE_POSTURE_BLOCKS_SPEND`), the mission-score threshold (`ERR_MISSION_SCORE_BELOW_THRESHOLD`), duplicate engagements (`ERR_DUPLICATE_ENGAGEMENT`), engagement-interval overlap (`ERR_ENGAGEMENT_OVERLAP`), tranche-period overlap (`ERR_TRANCHE_PERIOD_OVERLAP`), exit-plan uniqueness (`ERR_ACTIVE_EXIT_PLAN_EXISTS`), signoff party repetition (`ERR_SIGNOFF_PARTY_REPEATED`), signer reuse (`ERR_SIGNER_REUSED`), model-gated features (`ERR_MODEL_MISMATCH`), interval sanity (`ERR_TRANCHE_PERIOD_INVALID`, `ERR_ENGAGEMENT_DATES_INVALID`, `ERR_CLOSE_PERIOD_INVALID`), the staff-engagement reference (`ERR_STAFF_ENGAGEMENT_REQUIRED`), covering-tranche resolution (`ERR_NO_COVERING_TRANCHE`), amount minimums (`ERR_AMOUNT_BELOW_MINIMUM`), fund sufficiency (`ERR_INSUFFICIENT_FUNDS`), tranche budget (`ERR_TRANCHE_BUDGET_EXCEEDED`), refund bounds (`ERR_REFUND_EXCEEDS_REMAINING`), exit solvency (`ERR_EXIT_INSOLVENT`), zero-balance termination (`ERR_FUNDS_REMAIN`), and finally remediation bounds (`ERR_REMEDIATION_EXCEEDS_OPEN`). The trigger conditions for each appear in §3 beside the workflow they guard.

## 3. Business Logic & Workflows

### 3.1. From Application to Approval: Mission Alignment and the Compliance Decision

An engagement with the sponsor begins when an `Applicant` files a project application, providing `project_name`, `mission_statement`, `budget_estimate_cents` (a non-negative integer of cents estimating the annual budget), and `contact_email`, plus an optional `requested_model`. The application is born in `DRAFT` with `submit_count` at zero, `applicant_user_id` anchored to the filer, and `mission_score`, `decided_model`, `project_id`, `agreement_id`, and `fund_account_id` all unset. The application list supports filtering by `status` and `applicant_user_id`.

Submitting is the applicant's own act: the caller's `X-User-ID` must equal the application's `applicant_user_id`, otherwise `ERR_NOT_RESOURCE_OWNER`. Submission from `DRAFT` moves the application to `SUBMITTED` and increments `submit_count` by one. The same submission also serves the revision loop — an application in `RETURNED` may be resubmitted to `SUBMITTED` by its owner, again incrementing `submit_count`, with its prior mission scorecard points retained until a program officer re-scores them.

Once `SUBMITTED`, the application awaits a mission scorecard from a `ProgramOfficer`. The officer supplies four point inputs — `purpose_pts` for charitable purpose, `benefit_pts` for community benefit, `capacity_pts` for organizational capacity, and `risk_pts` where higher means riskier — each on a scale from 0 to 100 — a value outside that range fails schema validation with `ERR_VALIDATION` (HTTP 400) — together with an `action` of `ADVANCE` or `RETURN` and an optional `review_note`. The `mission_score` combines four weighted components: 0.335 times `purpose_pts`, 0.265 times `benefit_pts`, 0.215 times `capacity_pts`, and 0.185 times one hundred minus `risk_pts`. The rounding order is pinned: each component is individually rounded half up to two decimal places first, and the score is the sum of the four rounded components. Summing the raw components and rounding once is a rejected alternative — with inputs 73, 63, 61, and 67 the pinned order yields 60.39 while sum-first would yield 60.37. An `ADVANCE` action succeeds only when the resulting score is at least 70.00, the boundary inclusive; a lower score is rejected with `ERR_MISSION_SCORE_BELOW_THRESHOLD` (HTTP 422). A successful `ADVANCE` moves the application from `SUBMITTED` to `COMPLIANCE_REVIEW`; a `RETURN` moves it from `SUBMITTED` to `RETURNED`. Either way the computed `mission_score` is persisted.

A `ComplianceOfficer` then renders the compliance decision with a `decision` of `APPROVE`, `REJECT`, or `RETURN`, and an optional `rationale`. Approval additionally requires `sponsorship_model` in the request — it is conditionally required, and its absence is a schema failure under `ERR_VALIDATION`. A `sponsorship_model` sent alongside `REJECT` or `RETURN` must still name a declared model but is otherwise ignored; `decided_model` is set only on approval. On `APPROVE`, the application's `decided_model` is set from the request's `sponsorship_model` — it may differ from `requested_model` — and a single atomic cascade mints three resources: a `Project` in `PROPOSED` whose `name`, `mission_statement`, and `lead_user_id` are copied from the application's `project_name`, `mission_statement`, and `applicant_user_id`, with `source_application_id` pointing back; a `SponsorshipAgreement` in `PENDING_COUNTERSIGN` carrying the decided `model` and linked to the project; and a `FundAccount` in `PENDING` with every total at zero, linked to the project. The application's `project_id`, `agreement_id`, and `fund_account_id` are back-linked to the minted ids. On `REJECT` the application becomes `REJECTED`; on `RETURN` it goes back to `RETURNED` for another revision loop. In all cases the application's `review_note` reflects the note from the latest scorecard recording or compliance decision.

Withdrawal is available to the owning applicant from any non-terminal state — `DRAFT`, `SUBMITTED`, `RETURNED`, or `COMPLIANCE_REVIEW` — and moves the application to `WITHDRAWN`. `APPROVED`, `REJECTED`, and `WITHDRAWN` are terminal. For audit reachability, the projects minted from a given application can be listed (zero or one, since only approval mints a project).

### 3.2. Countersignature, Agreement Amendment, and Grant Tranches

Approval alone does not activate anything. The applicant countersigns the agreement — again an ownership-bound act, with `X-User-ID` compared to the source application's `applicant_user_id` — and only an agreement in `PENDING_COUNTERSIGN` accepts a countersignature (any other state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`). Countersignature fires a three-way activation: the agreement moves to `ACTIVE`, the project moves from `PROPOSED` to `ACTIVE`, and the fund moves from `PENDING` to `ACTIVE`.

Thereafter a `SponsorAdmin` may amend an `ACTIVE` agreement. The request must carry `expected_agreement_version` matching the agreement's current `version` under the optimistic-concurrency rule of §2.10 — a stale value is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). A successful amendment increments the agreement's `version` by one and updates the terms: `spending_basis` (`SETTLED` or, for `COMPREHENSIVE` agreements only, `FORWARD_LOOKING` — otherwise `ERR_MODEL_MISMATCH`), `effective_date`, and `amendment_note`, the last taken from the request's `note` field. Each term is applied only when present in the request — an amendment naming only `note` changes only `amendment_note`; omitted terms carry over unchanged. The agreement remains `ACTIVE` through an amendment; it later reaches `SUPERSEDED_BY_INDEPENDENCE` only via exit execution or `TERMINATED` only via project termination (§3.8).

Under the `PRE_APPROVED_GRANT` model, a `SponsorAdmin` issues grant tranches against the agreement, each with an `amount_cents` budget of at least one cent — a smaller budget fails schema validation with `ERR_VALIDATION` (HTTP 400) — a `period_start` (inclusive), a `period_end` (also inclusive — tranche periods use closed-interval semantics), and a restricted `purpose`. Issuance against a comprehensive agreement is rejected with `ERR_MODEL_MISMATCH`; beyond the model gate, issuance asks nothing of the agreement's lifecycle state, so a `PENDING_COUNTERSIGN` grant-model agreement accepts tranches. A `period_end` earlier than its `period_start` is rejected with `ERR_TRANCHE_PERIOD_INVALID`. Two tranches on the same agreement may not share a single calendar day: any overlap of their closed intervals against a tranche still in `ISSUED` is rejected with `ERR_TRANCHE_PERIOD_OVERLAP` (HTTP 409) — a `CLOSED` tranche's period no longer blocks new issuance — while pure adjacency — one tranche's `period_start` exactly one day after another's `period_end` — is legal. A new tranche is born `ISSUED` with `committed_cents` and `spent_cents` at zero. Once the logical clock's calendar date is strictly later than a tranche's `period_end`, a `SponsorAdmin` closes it with a mandatory `report_note`; closing earlier, or closing an already `CLOSED` tranche, is rejected with `ERR_TRANCHE_STATE_INVALID`. Closing is a reporting act only — the committed and spent totals remain as historical record.

### 3.3. Donation Intake, Tax Receipting, and Refunds

A `Donor` records a gift to an `ACTIVE` project — any other project state is rejected with `ERR_PROJECT_NOT_ACTIVE` — by supplying `amount_cents` (at least 100 cents, one dollar, else `ERR_AMOUNT_BELOW_MINIMUM`), `donor_name` for receipting under the sponsor's tax status, `donor_email`, an optional `donor_tax_id`, an `anonymous` flag (default false) that suppresses the donor's name on public listings, and a `payment_method` of `CARD`, `ACH`, `CHECK`, or `WIRE`. The gift is born `PLEDGED`, with its `fund_account_id` resolved from the project. Donation lists filter by `project_id`, `fund_account_id`, `status`, or `donor_email`.

Receipt of funds is a `FinanceOfficer` act guarded by four conditions: the project must be `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE`), the agreement `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), the fund `ACTIVE` (`ERR_FUND_NOT_ACTIVE`), and the project's posture must not be `SEVERE` (`ERR_SEVERE_POSTURE_BLOCKS_SPEND`). On receipt the donation moves from `PLEDGED` to `RECEIVED`, `received_at` is stamped from the logical clock, and the administrative fee is assessed and stored as `fee_cents`. Under `COMPREHENSIVE`, the fee walks the donation amount through marginal tiers of the fund's cumulative lifetime receipts, measured by `total_received_cents` immediately before this receipt: the portion falling within the fund's first 10,000,000 cents (one hundred thousand dollars) of cumulative receipts is charged eight percent; the portion falling between the 10,000,000-cent and 50,000,000-cent (five hundred thousand dollar) cumulative lines is charged six percent; any portion beyond 50,000,000 cents is charged four percent. Each segment's charge is rounded half up to whole cents before the segments are summed, and if the sum is below 50 cents it is raised to that per-donation minimum. Under `PRE_APPROVED_GRANT`, the fee is a flat three percent of the gift amount, rounded half up to whole cents, with no minimum and no reference to cumulative receipts; the grant model's annual platform fee is settled separately at period close (§3.7). Receipt then posts two ledger entries linked by `donation_id` — a `DONATION_CREDIT` for the gross amount and a `FEE_DEBIT` for the fee — and the fund's `total_received_cents` grows by the gift amount while `total_fees_charged_cents` grows by the fee.

A `FinanceOfficer` may then issue a tax receipt, moving the gift from `RECEIVED` to `RECEIPTED` provided the agreement is `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`). Issuance responds with the updated donation object; the minted receipt itself is read through the receipt endpoints. The minted `TaxReceipt` is born `ISSUED` with a `receipt_number` composed of the literal prefix `FS-`, the `tax_year` (the calendar year of the logical clock at issuance), and a hyphen-separated six-digit sequence assigned in issuance order within each tax year; its `amount_cents` equals the donation's full `amount_cents`. Receipt numbers are never reused, and a receipt in `VOIDED` state remains queryable — a donation's receipt history lists voided receipts alongside live ones and filters by `status`.

Refunds branch from either `RECEIVED` or `RECEIPTED`. A `Donor` or `FinanceOfficer` requests a refund with an `amount_cents` of at least one cent and at most the gift's remaining unrefunded balance — the original `amount_cents` minus the already-accumulated `refunded_cents` — otherwise `ERR_REFUND_EXCEEDS_REMAINING`; a `reason` accompanies the request. The gift moves to `REFUND_REQUESTED`, the frozen amount is recorded in `pending_refund_amount_cents`, and `status_before_refund` remembers whether the gift was `RECEIVED` or `RECEIPTED`.

The decision belongs to a `SponsorAdmin`, who supplies a `decision` of `APPROVE` or `REJECT` with an optional `note`. A rejection restores the gift to its `status_before_refund` state, clears `pending_refund_amount_cents` and `status_before_refund`, and moves no money. An approval behaves differently for partial and full refunds. A partial approval — the pending amount below the full remaining balance — restores the prior state (`RECEIVED` or `RECEIPTED`), adds the pending amount to the gift's `refunded_cents` and the fund's `total_refunded_cents`, posts a `DONATION_REFUND_DEBIT` ledger entry, clears `pending_refund_amount_cents`, and stamps `refunded_at` from the logical clock; when the gift had been receipted, the existing `ISSUED` receipt additionally transitions to `VOIDED` with `void_reason` `PARTIAL_REFUND` and a replacement receipt is issued whose `amount_cents` equals the gift amount minus total refunds, bearing a new `receipt_number`. A full approval — the pending amount covering the entire remaining balance — moves the gift to `REFUNDED`, sets `refunded_cents` to the full `amount_cents`, adds the pending amount to the fund's `total_refunded_cents`, posts the same `DONATION_REFUND_DEBIT` entry, stamps `refunded_at` from the logical clock, and transitions any `ISSUED` receipt to `VOIDED` with `void_reason` `FULL_REFUND` (no replacement is issued). Both approval paths clear `status_before_refund` to null once applied. Critically, fees are never reversed at refund time: the per-receipt fee stays charged against the fund until period close, where reversal applies only under the `COMPREHENSIVE` model (§3.7).

### 3.4. Spending Under Oversight: the Disbursement Pipeline

A `ProjectLead` drafts a spending request against their own project — `X-User-ID` must equal the project's `id`, else `ERR_NOT_RESOURCE_OWNER` — providing `amount_cents` (at least one cent, else `ERR_AMOUNT_BELOW_MINIMUM`), a charitable-purpose `purpose`, a `payee_type` of `VENDOR`, `STAFF`, or `OTHER`, a `payee_name`, the `spend_date` on which the spend is incurred, and, when the payee is staff, a `staff_engagement_id`. The reference is not validated at drafting: the draft records whatever was supplied — a non-`STAFF` draft may even carry the field, where it has no effect — and the requirement that a `STAFF` payee reference a resolvable engagement is enforced only at submission. The draft is born in `DRAFT`, its `fund_account_id` is resolved from the project, and its `high_value` flag is computed once: true when `amount_cents` reaches 1,000,000 cents (ten thousand dollars). Disbursement lists filter by `project_id`, `fund_account_id`, `staff_engagement_id`, `grant_tranche_id`, or `status`.

Submitting moves a draft from `DRAFT` to `SUBMITTED` and is where the fiscal guards concentrate, evaluated in the pipeline order of §2.11 — state guards before posture before referential and fiscal checks. The three resource state guards run first — the project must be `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE`), the agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), and the fund must be `ACTIVE` (`ERR_FUND_NOT_ACTIVE`) — and only then the posture gate: the posture must not be `SEVERE` (`ERR_SEVERE_POSTURE_BLOCKS_SPEND`). A `STAFF` payee must reference a `staff_engagement_id` that exists, belongs to this project, and is itself `ACTIVE`, else `ERR_STAFF_ENGAGEMENT_REQUIRED`. Under `PRE_APPROVED_GRANT`, exactly one `ISSUED` tranche whose closed period covers the `spend_date` must exist — the overlap rule of §3.2 guarantees uniqueness — and its id is resolved into the request's `grant_tranche_id` at this moment; absence of a covering tranche is `ERR_NO_COVERING_TRANCHE`. The amount must not exceed the spendable balance under the agreement's `spending_basis` variant from §2.6 — the settled figure under `SETTLED`, the pledge-credited figure under `FORWARD_LOOKING` — else `ERR_INSUFFICIENT_FUNDS`. Under the grant model, the covering tranche's remaining budget — its `amount_cents` minus `spent_cents` minus `committed_cents` — must be at least the request amount, else `ERR_TRANCHE_BUDGET_EXCEEDED`.

A successful submission takes a commitment: the fund's `committed_cents` grows by the amount and a `COMMITMENT_HOLD` ledger entry is posted with `disbursement_id` set; when a tranche was resolved, its `committed_cents` grows by the same amount. The submitter is recorded as `submitted_by_user_id`. The commitment is released on every exit from the pipeline other than payment: compliance return, rejection at either gate, cancellation from `SUBMITTED`, and the suspension cascade all subtract the amount from `committed_cents`, post a `COMMITMENT_RELEASE` entry, and release the tranche commitment when one was taken.

Review by a `ComplianceOfficer` takes a `decision` and an optional `note`, and the reviewer must not be the recorded submitter (`ERR_SOD_VIOLATION`). An `APPROVE` records `compliance_approved_by_user_id` and routes by `high_value`: ordinary requests move `SUBMITTED` to `APPROVED_FOR_PAYMENT`, while high-value ones detour to `PENDING_SPONSOR`. A `RETURN` sends the request back to `DRAFT` with the commitment released; a `REJECT` terminates it as `REJECTED` with the same release. High-value requests then face a `SponsorAdmin` decision from `PENDING_SPONSOR`: the sponsor approver must differ from both the submitter and the compliance approver (`ERR_SOD_VIOLATION`), an `APPROVE` records `sponsor_approved_by_user_id` and moves the request to `APPROVED_FOR_PAYMENT`, and a `REJECT` terminates it with the commitment released.

Payment is a `FinanceOfficer` act on requests in `APPROVED_FOR_PAYMENT`. The payer must differ from the submitter, the compliance approver, and — when set — the sponsor approver (`ERR_SOD_VIOLATION`), and no `CRITICAL` incident may be open on the project in `REPORTED`, `TRIAGED`, or `MITIGATING` (`ERR_CRITICAL_INCIDENT_OPEN`). Payment converts commitment to spend: `committed_cents` falls by the amount while `total_disbursed_cents` rises by it, a `COMMITMENT_RELEASE` and a `DISBURSEMENT_DEBIT` entry are posted, the covering tranche's `committed_cents` falls and its `spent_cents` rises when a tranche was charged, staff payees feed the contractor accumulation of §3.5, and `paid_by_user_id` is recorded. The request reaches `PAID`, a terminal state alongside `REJECTED` and `CANCELLED`.

Cancellation is the lead's own escape hatch: from `DRAFT` a cancel moves straight to `CANCELLED` with no ledger effect, while from `SUBMITTED` it additionally releases the commitment. Finally, whenever the project is suspended — manually or via the escalation cascade of §3.6 — every request in `SUBMITTED`, `PENDING_SPONSOR`, or `APPROVED_FOR_PAYMENT` is auto-rejected with `auto_reject_reason` set to `SUSPENSION` and its commitment released, after which the fund's available balance is recomputed.

### 3.5. Staff Engagements and Worker Classification

A `ProjectLead` proposes an engagement on their own project with the worker's `worker_name` and `worker_email` — the latter serving as the identity key for the duplicate and overlap rules — an `engagement_type` of `EMPLOYEE` or `CONTRACTOR`, a `compensation_type` of `HOURLY`, `SALARY`, or `FIXED`, a `rate_cents` of at least one cent (per hour, per period, or fixed, according to the compensation type; a smaller rate fails schema validation with `ERR_VALIDATION`, HTTP 400), a `start_date` treated as inclusive, and an optional `end_date` treated as exclusive, whose omission means open-ended. When provided, `end_date` must be strictly later than `start_date` (`ERR_ENGAGEMENT_DATES_INVALID`). Proposing an `EMPLOYEE` under a `PRE_APPROVED_GRANT` agreement is rejected with `ERR_MODEL_FORBIDS_EMPLOYMENT`. A worker may hold only one pipeline-stage engagement per project: if the same `worker_email` already has an engagement in `PROPOSED`, `VETTED`, or `CLASSIFICATION_REVIEW` on this project, the create is rejected with `ERR_DUPLICATE_ENGAGEMENT` (HTTP 409) — an existing `ACTIVE` engagement does not block proposing, because overlap is enforced at activation instead. The engagement is born `PROPOSED` with `classification_overridden` false, `ytd_year` unset until the first payment, and the engagement list filters by `status` or `worker_email`.

Classification is vetted by a `ComplianceOfficer`, who supplies an `approved_type` and a `rationale`. From `PROPOSED` — and equally from `CLASSIFICATION_REVIEW`, since re-vetting follows a misclassification flag — the engagement moves to `VETTED`, its `engagement_type` is set to the approved type, and `classification_overridden` records whether the approved type differs from the originally proposed type — the `engagement_type` supplied at creation, not whatever an earlier vetting left behind. Approving `EMPLOYEE` under the grant model is rejected here as well with `ERR_MODEL_FORBIDS_EMPLOYMENT`; this guard applies at both proposal and classification review.

Activation is the lead's act from `VETTED` and carries three guards: the agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`); the project's posture must be `NORMAL` — both `RESTRICTED` and `SEVERE` block activation with `ERR_SEVERE_POSTURE_BLOCKS_SPEND`; and the new engagement's half-open interval from `start_date` inclusive to `end_date` exclusive must not overlap any other `ACTIVE` engagement for the same `worker_email` on the same project (`ERR_ENGAGEMENT_OVERLAP`, HTTP 409). A null `end_date` is open-ended and overlaps everything from its start onward; intervals that merely touch — one's `end_date` equal to the other's `start_date` — do not overlap.

A `ComplianceOfficer` who suspects misclassification flags an `ACTIVE` engagement with a `reason`, moving it to `CLASSIFICATION_REVIEW`; the cycle `ACTIVE` to `CLASSIFICATION_REVIEW` to `VETTED` to `ACTIVE` may repeat, and each pass may flip `engagement_type`. Termination is available to the `ProjectLead` or a `ComplianceOfficer` from `ACTIVE`, `VETTED`, or `CLASSIFICATION_REVIEW`, moving the engagement to `TERMINATED`; an optional `reason` accompanies the request, and when terminating an `ACTIVE` engagement a provided `end_date` is recorded on it.

Contractor payments feed a calendar-year accumulation at the moment a staff disbursement reaches `PAID` (§3.4). When the payee's engagement type is `CONTRACTOR`, the accumulation year is the calendar year of the logical clock at payment time; if the engagement's `ytd_year` differs from that year, `contractor_ytd_cents` first resets to zero and `ytd_year` is set to the payment year, and only then is the disbursement's `amount_cents` added. The `requires_1099` flag is true exactly when `contractor_ytd_cents` is at least 60,000 cents (six hundred dollars) — the boundary is inclusive. `EMPLOYEE` engagements never accumulate; their pay runs on the W-2 path.

### 3.6. Compliance Reviews, Risk Incidents, and the Suspension Cascade

A `ComplianceOfficer` opens a review on a project with a `review_type` of `SCHEDULED` or `TRIGGERED` and an optional `note`; the review is born `OPEN` with `findings_count` and `open_findings_count` at zero, and review lists filter by `status`. Issuing findings requires a `findings_count` of at least one — a smaller count fails schema validation with `ERR_VALIDATION` (HTTP 400) — and a `severity_max` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`; the review moves from `OPEN` to `FINDINGS_ISSUED`, `open_findings_count` is set equal to `findings_count`, and the project's `risk_score` and `oversight_posture` recompute per §2.8.

Remediation proceeds in increments: each call supplies a `remediated_count` of at least one and at most the current `open_findings_count`, else `ERR_REMEDIATION_EXCEEDS_OPEN`. When the count leaves findings open, the review stays `FINDINGS_ISSUED` with `open_findings_count` reduced by that count; when the count exactly exhausts the open findings, `open_findings_count` becomes zero and the review moves to `REMEDIATED`. Either way the risk score recomputes. Closure is allowed from `OPEN` only while `findings_count` is zero, and from `REMEDIATED` without condition — a review with unremediated findings cannot close. Escalation, by contrast, takes a required `reason` string in the request body and moves a `FINDINGS_ISSUED` review to `ESCALATED`, which is terminal for the review, and fires the full suspension cascade: the project moves from `ACTIVE` to `SUSPENDED` with `suspension_reason` recorded as `ESCALATED_REVIEW`, the fund moves from `ACTIVE` to `FROZEN`, and every in-flight disbursement is auto-rejected with commitment release exactly as in §3.4. Project reinstatement after escalation is a separate manual act, never an automatic consequence of the review.

Manual suspension shares the same cascade. A `ComplianceOfficer` or `SponsorAdmin` suspends an `ACTIVE` project with a `reason`, which is recorded as `suspension_reason` — a field that is null while the project is `ACTIVE` and populated only by the latest suspension; the fund freezes and in-flight disbursements are auto-rejected with `auto_reject_reason` `SUSPENSION`. Reinstatement belongs to the `SponsorAdmin` alone and moves a `SUSPENDED` project back to `ACTIVE`, unfreezing the fund from `FROZEN` to `ACTIVE` — but only while no review of the project sits in `ESCALATED` and no `CRITICAL` incident remains open in `REPORTED`, `TRIAGED`, or `MITIGATING`. A blocked reinstatement — the project not `SUSPENDED`, an `ESCALATED` review present, or an open `CRITICAL` incident — is rejected with `ERR_PROJECT_NOT_ACTIVE` (HTTP 409); a successful reinstatement clears `suspension_reason` to null.

Risk incidents are reported by a `ComplianceOfficer` or the `ProjectLead` with a `category` of `LIABILITY`, `FINANCIAL`, `REPUTATIONAL`, `REGULATORY`, or `SAFETY`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and a `description`; the incident is born `REPORTED` and the project's risk score recomputes immediately, since `REPORTED` belongs to the open set. A `ComplianceOfficer` then drives the incident with an `action` and an optional `note`: `TRIAGE` moves `REPORTED` to `TRIAGED` (the score recomputes because open-set membership participates in the calculation), `MITIGATE` moves `TRIAGED` to `MITIGATING`, `RESOLVE` moves any of `REPORTED`, `TRIAGED`, or `MITIGATING` to `RESOLVED`, and `DISMISS` moves `REPORTED` or `TRIAGED` to `DISMISSED` — a mitigating incident cannot be dismissed, and any action from a state outside its from-set is rejected with `ERR_INCIDENT_STATE_INVALID`. Resolution and dismissal capture the request's `note` as `resolution_note` and recompute the risk score. Incident lists filter by `status` and `severity`.

### 3.7. Fund Administration: Adjustments, Period Close, and the Audit Ledger

A `FinanceOfficer` may post a manual signed adjustment to a fund, supplying `amount_cents` (positive or negative — zero is accepted too), a `memo`, and the optimistic-concurrency field `expected_fund_account_version`. A `CLOSED` fund rejects the posting with `ERR_FUND_NOT_ACTIVE` (HTTP 409); any other fund state accepts it. Per §2.10, a version mismatch is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412); a success posts an `ADJUSTMENT` ledger entry, folds the signed amount into `total_adjustments_cents`, increments the fund's `version` by one, and returns the updated fund account — derived balances included — with HTTP 200.

Period close reconciles the provisional per-receipt fees against what should finally have been charged. The `FinanceOfficer` closes a period with `period_start` and `period_end`, the end on or after the start (`ERR_CLOSE_PERIOD_INVALID`), producing a `FeeAssessment` in its only state, `FINAL` — assessments are append-only and never transition. A `CLOSED` fund rejects the close with `ERR_FUND_NOT_ACTIVE` (HTTP 409). Despite minting the assessment, the close returns HTTP 200 with the created `FeeAssessment` as its payload. The period's donations are those whose `received_at` calendar date falls within the closed interval from `period_start` to `period_end` inclusive, processed in `received_at` order with earlier `created_at` breaking ties; ids are never used for ordering. `provisional_fees_cents` is the sum of `fee_cents` over those donations. Under `COMPREHENSIVE`, each period donation with `refunded_cents` greater than zero keeps a final fee of its original `fee_cents` scaled by the ratio of its unrefunded remainder — `amount_cents` minus `refunded_cents` — to its full `amount_cents`, rounded half up to whole cents per donation; each such donation's reversal is its original fee minus its kept fee, and `refund_reversals_cents` is the sum of those per-donation reversals (per-donation rounding first, then summation), while `annual_platform_fee_cents` is zero. Under `PRE_APPROVED_GRANT` no refund reversals are computed — grant fees are not reversed — and instead `annual_platform_fee_cents` is 25,000 cents when this close produces the first `FINAL` assessment whose `period_end` falls in a calendar year during which the fund received at least one donation, and zero otherwise. The assessment's `final_fees_cents` is provisional minus refund reversals plus the annual platform fee, and `delta_cents` is final minus provisional. A negative delta posts a `FEE_REVERSAL_CREDIT` entry for the delta's absolute value; a positive delta posts a `FEE_DEBIT` for that amount as a negative signed entry; a zero delta posts no ledger entry. The fund's `total_fees_reversed_cents` grows by `refund_reversals_cents` and its `total_fees_charged_cents` grows by `annual_platform_fee_cents`.

The audit surface completes the picture. Fund account reads — the single fetch and the per-project listing alike — carry the derived `available_cents` and `forward_available_cents` alongside the stored totals. A fund's own ledger listing is chronological and filters by `entry_type`; a global ledger listing filters by `fund_account_id`, `donation_id`, `disbursement_id`, or `entry_type`; individual entries are fetchable. A fund's assessments list and individual assessments are likewise readable. The fund of a project is reachable in reverse (zero or one), and the computed project summary read exposes `available_cents`, `forward_available_cents`, `committed_cents`, `reserved_cents`, `risk_score`, `oversight_posture`, `open_findings_count`, and `open_incident_count` — the last counting incidents in `REPORTED`, `TRIAGED`, or `MITIGATING`.

### 3.8. Spin-Off and Termination: the Exit Settlement Waterfall

A project leaves the sponsor in one of two ways. The gentler path begins when a `ProjectLead` or `SponsorAdmin` proposes an exit plan with the `successor_entity_name` and `successor_ein` of the independent entity the project will spin into, plus a `reason`. The plan is born `PROPOSED` with an empty `signoffs` list and its four waterfall buckets (`committed_payout_cents`, `reserve_cents`, `exit_fee_cents`, `transfer_cents`) at zero, and a project may have at most one non-terminal plan — any plan in `PROPOSED`, `DUE_DILIGENCE`, or `APPROVED` blocks another create with `ERR_ACTIVE_EXIT_PLAN_EXISTS` (HTTP 409). Exit-plan lists filter by `status`.

Entering due diligence is a `SponsorAdmin` act guarded by three gates, in the pipeline order of §2.11: no `CRITICAL` incident may be open in `REPORTED`, `TRIAGED`, or `MITIGATING` (`ERR_CRITICAL_INCIDENT_OPEN`); no review of the project may sit in `OPEN` or `ESCALATED` (`ERR_OPEN_COMPLIANCE_BLOCKS_EXIT` — note that a `FINDINGS_ISSUED` review does not block, because its open findings are priced into the reserve bucket at execution); and the posture must be `NORMAL`, since `RESTRICTED` and `SEVERE` both block (`ERR_SEVERE_POSTURE_BLOCKS_SPEND`). Success moves the plan from `PROPOSED` to `DUE_DILIGENCE`.

Signoff collection is a fork-join over three distinct parties: `SPONSOR_BOARD`, `PROJECT_LEAD`, and `SUCCESSOR_REP`. Each signoff call names one `party` and is role-bound: the `PROJECT_LEAD` party requires the `ProjectLead` role with `X-User-ID` equal to the project's `id`, while `SPONSOR_BOARD` and `SUCCESSOR_REP` require the `SponsorAdmin` role. A caller whose role does not match the named party's binding is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). A party already present in `signoffs` is rejected with `ERR_SIGNOFF_PARTY_REPEATED`; a signer whose `X-User-ID` already appears as any entry's `signer_user_id` is rejected with `ERR_SIGNER_REUSED` — the three signers must be pairwise distinct users. Each accepted signoff appends an entry recording `party`, `signer_user_id`, and `signed_at`; the plan remains `DUE_DILIGENCE` through the first two, and the third distinct party joins the fork, moving the plan to `APPROVED`.

Execution is the point of no return, performed by a `SponsorAdmin` on an `APPROVED` plan, and it settles the fund through a waterfall whose evaluation order is normative. First, the gross position G is the fund's `available_cents` plus its `committed_cents` — the total net assets under sponsor control. Bucket one, `committed_payout_cents`, is the sum of committed amounts on requests in `PENDING_SPONSOR` or `APPROVED_FOR_PAYMENT`; requests still in `SUBMITTED` are auto-rejected with commitment release and `DRAFT` requests are auto-cancelled during the same execution, so neither participates — releasing a `SUBMITTED` commitment shifts the amount from committed back into available and leaves G unchanged whether the release lands before or after the measurement. Exit-execution auto-rejection leaves `auto_reject_reason` null; the `SUSPENSION` marker is reserved for the suspension cascade. Bucket two, `reserve_cents`, is 250,000 cents (twenty-five hundred dollars) multiplied by the total `open_findings_count` across the project's reviews in `FINDINGS_ISSUED` or `ESCALATED`. The base is G minus bucket one minus bucket two; a negative base rejects the execution with `ERR_EXIT_INSOLVENT` (HTTP 422). Bucket three, `exit_fee_cents`, is the greater of 50,000 cents and two percent of the base rounded half up to whole cents. Bucket four, `transfer_cents`, is the base minus the exit fee; a negative transfer likewise rejects with `ERR_EXIT_INSOLVENT`. The four buckets always sum to exactly G — the waterfall permits no drift.

Execution then posts the settlement. The bucket-one requests are paid with `exit_settled` marked true — it is false on every ordinary payment — and their amounts count into `total_disbursed_cents`; these payouts execute directly, bypassing the ordinary payment gates of §3.4 (segregation of duties and the open-critical-incident gate), and record no `paid_by_user_id`. A `RESERVE_HOLD` entry posts the reserve and the fund's `reserved_cents` is set to `reserve_cents`. A `FEE_DEBIT` posts the exit fee and `total_fees_charged_cents` grows by it. An `EXIT_TRANSFER_DEBIT` posts the transfer to the successor and `total_transferred_out_cents` grows by it. A zero reserve posts no `RESERVE_HOLD` entry and a zero transfer posts no `EXIT_TRANSFER_DEBIT` entry, though the totals are still set. The fund closes (its available balance lands at exactly zero, the reserve remaining held in `reserved_cents`), the agreement moves from `ACTIVE` to `SUPERSEDED_BY_INDEPENDENCE`, and the project moves from `ACTIVE` to `SPUN_OFF`, with the plan itself reaching `COMPLETED`. The plan's computed buckets — `committed_payout_cents`, `reserve_cents`, `exit_fee_cents`, and `transfer_cents` — record the settled waterfall. A plan may instead be abandoned by a `SponsorAdmin` or `ProjectLead` with a `reason` from `PROPOSED`, `DUE_DILIGENCE`, or `APPROVED`, moving it to `ABANDONED`.

Termination is the other exit: a `SponsorAdmin` winds a project down with a `reason`, from either `ACTIVE` or `SUSPENDED`, but only when the fund's `available_cents`, `committed_cents`, and `reserved_cents` are all exactly zero — otherwise `ERR_FUNDS_REMAIN`. Termination moves the project to `TERMINATED`, the agreement from `ACTIVE` to `TERMINATED`, and the fund to `CLOSED` (from `ACTIVE`, or from `FROZEN` when the project had been suspended). `SPUN_OFF` and `TERMINATED` are the project's terminal states, and a `CLOSED` fund accepts no further movement.

## 4. Endpoint Definitions

The eight collection-creation endpoints — creating an application, a grant tranche, a donation, a disbursement request, a staff engagement, a compliance review, a risk incident, or an exit plan — return `201 Created`; every other mutating endpoint returns `200 OK`, including those that mint records as side effects (compliance approval returns the updated application, receipt issuance the updated donation, an adjustment the updated fund account, period close the new `FeeAssessment`, exit execution the plan). Unless a row says otherwise, every GET endpoint below is authorized for all roles except `Donor` — that is, `Applicant`, `ProjectLead`, `ProgramOfficer`, `ComplianceOfficer`, `FinanceOfficer`, and `SponsorAdmin` — abbreviated in the table as "All read roles". Request bodies, response payloads, and side effects are specified by the narratives of §2 and §3 rather than by this table. List filters not enumerated in §3: the project list filters by `status`, the agreement list by `project_id` and `status`, and an agreement's tranche list by `status`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/fsa/applications` | Create a project application in `DRAFT` | Applicant |
| GET    | `/fsa/applications` | List applications | All read roles |
| GET    | `/fsa/applications/{id}` | Get one application | All read roles |
| POST   | `/fsa/applications/{id}/submit` | Submit or resubmit an application | Applicant |
| POST   | `/fsa/applications/{id}/mission-score` | Record the mission scorecard; advance or return | ProgramOfficer |
| POST   | `/fsa/applications/{id}/compliance-decision` | Compliance decision; approval mints project, agreement, and fund | ComplianceOfficer |
| POST   | `/fsa/applications/{id}/withdraw` | Withdraw a non-terminal application | Applicant |
| GET    | `/fsa/applications/{id}/projects` | List projects minted from an application (zero or one) | All read roles |
| GET    | `/fsa/projects` | List projects | All read roles |
| GET    | `/fsa/projects/{id}` | Get one project | All read roles |
| GET    | `/fsa/projects/{id}/summary` | Computed read: fund balances, posture, risk score, counts | All read roles |
| POST   | `/fsa/projects/{id}/suspend` | Suspend an `ACTIVE` project with the full cascade | ComplianceOfficer, SponsorAdmin |
| POST   | `/fsa/projects/{id}/reinstate` | Reinstate a `SUSPENDED` project | SponsorAdmin |
| POST   | `/fsa/projects/{id}/terminate` | Terminate a zero-balance project | SponsorAdmin |
| GET    | `/fsa/agreements` | List agreements | All read roles |
| GET    | `/fsa/agreements/{id}` | Get one agreement | All read roles |
| GET    | `/fsa/projects/{id}/agreements` | List the agreement of a project (zero or one) | All read roles |
| POST   | `/fsa/agreements/{id}/countersign` | Applicant countersigns; activates agreement, project, and fund | Applicant |
| POST   | `/fsa/agreements/{id}/amend` | Amend agreement terms (OCC on the agreement version) | SponsorAdmin |
| POST   | `/fsa/agreements/{id}/grant-tranches` | Issue a grant tranche (grant model only) | SponsorAdmin |
| GET    | `/fsa/agreements/{id}/grant-tranches` | List tranches of an agreement | All read roles |
| GET    | `/fsa/grant-tranches/{id}` | Get one tranche | All read roles |
| POST   | `/fsa/grant-tranches/{id}/close` | Close a tranche after its period ends; report required | SponsorAdmin |
| POST   | `/fsa/projects/{id}/donations` | Record a donation pledge | Donor |
| GET    | `/fsa/donations` | List and filter donations | All read roles |
| GET    | `/fsa/donations/{id}` | Get one donation | All read roles |
| POST   | `/fsa/donations/{id}/receive` | Mark a pledge received; assess the admin fee | FinanceOfficer |
| POST   | `/fsa/donations/{id}/issue-receipt` | Issue a tax receipt under the sponsor's tax status | FinanceOfficer |
| POST   | `/fsa/donations/{id}/request-refund` | Request a full or partial refund | Donor, FinanceOfficer |
| POST   | `/fsa/donations/{id}/decide-refund` | Approve or reject the open refund request | SponsorAdmin |
| GET    | `/fsa/receipts/{id}` | Get one tax receipt | All read roles |
| GET    | `/fsa/donations/{id}/receipts` | List receipts of a donation, voided included | All read roles |
| POST   | `/fsa/projects/{id}/disbursement-requests` | Draft a spending request | ProjectLead |
| GET    | `/fsa/disbursement-requests` | List and filter disbursement requests | All read roles |
| GET    | `/fsa/disbursement-requests/{id}` | Get one disbursement request | All read roles |
| POST   | `/fsa/disbursement-requests/{id}/submit` | Submit for review; commits funds | ProjectLead |
| POST   | `/fsa/disbursement-requests/{id}/compliance-review` | Compliance approve, return, or reject | ComplianceOfficer |
| POST   | `/fsa/disbursement-requests/{id}/sponsor-approve` | Sponsor decision on high-value requests | SponsorAdmin |
| POST   | `/fsa/disbursement-requests/{id}/pay` | Pay an approved request | FinanceOfficer |
| POST   | `/fsa/disbursement-requests/{id}/cancel` | Cancel a `DRAFT` or `SUBMITTED` request | ProjectLead |
| POST   | `/fsa/projects/{id}/staff-engagements` | Propose a staff engagement | ProjectLead |
| GET    | `/fsa/staff-engagements/{id}` | Get one engagement | All read roles |
| GET    | `/fsa/projects/{id}/staff-engagements` | List engagements of a project | All read roles |
| POST   | `/fsa/staff-engagements/{id}/classification-review` | Vet classification; may override the engagement type | ComplianceOfficer |
| POST   | `/fsa/staff-engagements/{id}/activate` | Activate a vetted engagement | ProjectLead |
| POST   | `/fsa/staff-engagements/{id}/flag-misclassification` | Re-open classification on an `ACTIVE` engagement | ComplianceOfficer |
| POST   | `/fsa/staff-engagements/{id}/terminate` | Terminate a non-terminal engagement | ProjectLead, ComplianceOfficer |
| POST   | `/fsa/projects/{id}/compliance-reviews` | Open a compliance review | ComplianceOfficer |
| GET    | `/fsa/compliance-reviews/{id}` | Get one review | All read roles |
| GET    | `/fsa/projects/{id}/compliance-reviews` | List reviews of a project | All read roles |
| POST   | `/fsa/compliance-reviews/{id}/issue-findings` | Issue findings; recomputes project risk posture | ComplianceOfficer |
| POST   | `/fsa/compliance-reviews/{id}/remediate` | Remediate findings; zero open findings remediates the review | ComplianceOfficer |
| POST   | `/fsa/compliance-reviews/{id}/close` | Close an `OPEN` (no findings) or `REMEDIATED` review | ComplianceOfficer |
| POST   | `/fsa/compliance-reviews/{id}/escalate` | Escalate; suspends the project with the full cascade | ComplianceOfficer |
| POST   | `/fsa/projects/{id}/risk-incidents` | Report a risk incident | ComplianceOfficer, ProjectLead |
| GET    | `/fsa/risk-incidents/{id}` | Get one incident | All read roles |
| GET    | `/fsa/projects/{id}/risk-incidents` | List incidents of a project | All read roles |
| POST   | `/fsa/risk-incidents/{id}/transition` | Triage, mitigate, resolve, or dismiss an incident | ComplianceOfficer |
| POST   | `/fsa/projects/{id}/exit-plans` | Propose a spin-off exit plan | ProjectLead, SponsorAdmin |
| GET    | `/fsa/exit-plans/{id}` | Get one exit plan | All read roles |
| GET    | `/fsa/projects/{id}/exit-plans` | List exit plans of a project | All read roles |
| POST   | `/fsa/exit-plans/{id}/begin-due-diligence` | Enter due diligence (gated on open compliance and risk) | SponsorAdmin |
| POST   | `/fsa/exit-plans/{id}/signoff` | Record one party signoff; the third distinct party approves | SponsorAdmin, ProjectLead |
| POST   | `/fsa/exit-plans/{id}/execute` | Run the settlement waterfall, transfer assets, and spin off | SponsorAdmin |
| POST   | `/fsa/exit-plans/{id}/abandon` | Abandon a non-terminal exit plan | SponsorAdmin, ProjectLead |
| GET    | `/fsa/fund-accounts/{id}` | Get one fund account | All read roles |
| GET    | `/fsa/projects/{id}/fund-accounts` | List the fund of a project (zero or one) | All read roles |
| POST   | `/fsa/fund-accounts/{id}/adjustments` | Post a manual signed adjustment (OCC on the fund version) | FinanceOfficer |
| POST   | `/fsa/fund-accounts/{id}/close-period` | Close a fee period; reconcile provisional and final fees | FinanceOfficer |
| GET    | `/fsa/fund-accounts/{id}/ledger-entries` | List a fund's ledger entries chronologically | All read roles |
| GET    | `/fsa/fund-ledger-entries` | Filtered ledger listing across funds | All read roles |
| GET    | `/fsa/fund-ledger-entries/{id}` | Get one ledger entry | All read roles |
| GET    | `/fsa/fund-accounts/{id}/fee-assessments` | List fee assessments of a fund | All read roles |
| GET    | `/fsa/fee-assessments/{id}` | Get one fee assessment | All read roles |
| POST   | `/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC) | SponsorAdmin |

## 5. Error Code Catalogue

Trigger conditions for every error live in the §2 and §3 narratives; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_FUND_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_DONATION_NOT_FOUND` | 404 |
| `ERR_RECEIPT_NOT_FOUND` | 404 |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_EXIT_PLAN_NOT_FOUND` | 404 |
| `ERR_TRANCHE_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_LEDGER_ENTRY_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_ACTIONABLE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_PROJECT_NOT_ACTIVE` | 409 |
| `ERR_FUND_NOT_ACTIVE` | 409 |
| `ERR_DONATION_STATE_INVALID` | 409 |
| `ERR_DISBURSEMENT_STATE_INVALID` | 409 |
| `ERR_ENGAGEMENT_STATE_INVALID` | 409 |
| `ERR_REVIEW_STATE_INVALID` | 409 |
| `ERR_INCIDENT_STATE_INVALID` | 409 |
| `ERR_EXIT_STATE_INVALID` | 409 |
| `ERR_TRANCHE_STATE_INVALID` | 409 |
| `ERR_MODEL_FORBIDS_EMPLOYMENT` | 422 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_CRITICAL_INCIDENT_OPEN` | 422 |
| `ERR_OPEN_COMPLIANCE_BLOCKS_EXIT` | 422 |
| `ERR_SEVERE_POSTURE_BLOCKS_SPEND` | 422 |
| `ERR_MISSION_SCORE_BELOW_THRESHOLD` | 422 |
| `ERR_DUPLICATE_ENGAGEMENT` | 409 |
| `ERR_ENGAGEMENT_OVERLAP` | 409 |
| `ERR_TRANCHE_PERIOD_OVERLAP` | 409 |
| `ERR_ACTIVE_EXIT_PLAN_EXISTS` | 409 |
| `ERR_SIGNOFF_PARTY_REPEATED` | 409 |
| `ERR_SIGNER_REUSED` | 409 |
| `ERR_MODEL_MISMATCH` | 422 |
| `ERR_TRANCHE_PERIOD_INVALID` | 422 |
| `ERR_ENGAGEMENT_DATES_INVALID` | 422 |
| `ERR_CLOSE_PERIOD_INVALID` | 422 |
| `ERR_STAFF_ENGAGEMENT_REQUIRED` | 422 |
| `ERR_NO_COVERING_TRANCHE` | 422 |
| `ERR_TRANCHE_BUDGET_EXCEEDED` | 422 |
| `ERR_AMOUNT_BELOW_MINIMUM` | 422 |
| `ERR_INSUFFICIENT_FUNDS` | 422 |
| `ERR_REFUND_EXCEEDS_REMAINING` | 422 |
| `ERR_EXIT_INSOLVENT` | 422 |
| `ERR_FUNDS_REMAIN` | 422 |
| `ERR_REMEDIATION_EXCEEDS_OPEN` | 422 |
| `ERR_STALE_FUND_VERSION` | 412 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
