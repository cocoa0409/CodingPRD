# Payer Contract Underpayment API — Product Requirements Document

## 1. Introduction

Hospitals rarely collect exactly what their payer contracts promise. Rates are renegotiated, escalators kick in mid-year, implants and high-cost drugs are carved out of base pricing, stop-loss floors protect catastrophic cases — and somewhere in that machinery, payers systematically remit less than the contract entitles the hospital to. Industry experience puts recoverable underpayment leakage in the low single digits of net patient revenue, which for a mid-sized health system is measured in millions of dollars per year. Recovering it requires something most revenue-cycle teams lack: a deterministic engine that can recompute, claim by claim, what the payer actually owed, and a disciplined workflow that carries each shortfall from detection through appeals, mediation, and arbitration.

This document specifies the Payer Contract Modeling & Underpayment Recovery API, the system of record for that work. It covers contract term abstraction and rate loading; expected-reimbursement calculation per claim under both prospective and retrospective reading of the rate card; variance detection with a configurable underpayment queue; an appeal and escalation matrix governed by payer-specific filing deadlines; wrap-network and silent-PPO identification for claims no direct contract covers; renegotiation modeling that isolates rate effects from volume-mix effects; and a logical clock whose sweeps apply escalators, activate amendments, expire appeals and contracts, and raise term-expiration alerts. All resources are served under a single flat mount, `/api`; every workflow described below is reachable through the endpoints catalogued in §4.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API. Domain workflows in §3 assume everything stated here.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. The system recognizes exactly seven roles, spelled precisely as follows: `ContractAnalyst`, `ContractManager`, `RevenueIntegrityAnalyst`, `RecoveryManager`, `FinanceDirector`, `SystemAdmin`, and `Auditor`. A request missing either header, or presenting a role string outside that set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is valid but not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The identity model is uniform across the platform. When `X-User-Role` is `ContractAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` on a rate amendment) but never compares it to any entity's `id`. The same is true, role by role, for `ContractManager` (whose identifier may be recorded as `approved_by_user_id`), for `RevenueIntegrityAnalyst` and `RecoveryManager` (whose identifier may be recorded as `claimed_by_user_id` on an underpayment case), and for `FinanceDirector`, `SystemAdmin`, and `Auditor`. Ownership-style checks in this system — the segregation-of-duties rules of §2.9 — compare `X-User-ID` against those recorded operator fields, never against a persisted user resource, because none exists.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Calendar Conventions

The system keeps a single logical clock, a UTC datetime, which boots to exactly `2026-08-01T00:00:00Z` at server startup; the clock sweep described in §3.9 runs once at startup against that default. A `SystemAdmin`-only test-driving capability advances or rewinds the clock to a supplied `to_iso8601` instant and re-runs the full sweep on every invocation. Backward clock moves are permitted, and every sweep step is idempotent, so replaying the same instant never duplicates its effects.

All domain date fields on resources — coverage windows, stay dates, remittance dates, filing and response deadlines, alert trigger dates — are calendar dates in `YYYY-MM-DD` form. The word "today" throughout this document means the UTC calendar-date part of the logical clock. The word "anchor" means a claim's discharge date and is the reference date for every pricing window.

### 2.5. Common Resource Properties and Mutation Semantics

Every resource in the system — payers, contracts, terms, provisions, escalators, amendments, network agreements, claims, claim lines, remittances, underpayment cases, appeals, proposals, and alerts — carries four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation. `updated_at` is the same format, refreshed on every modification. `version` is an integer that increments by exactly one on every mutation of the resource. No entity in this API is exempt: all fifteen resource types carry the full quartet.

Mutations frequently cascade. When a single request or sweep step touches several resources — an amendment application that also bumps its contract, a remittance reversal that also restates a case — every affected resource's `version` increments and its `updated_at` refreshes as part of the same atomic mutation; the whole cascade commits or none of it does. Fields marked in §3 as computed are maintained by the server and are never accepted as client input. One computed field is special: a contract's `open_underpayment_cents` rollup is derived at read time, never stored, and its movement does not increment the contract's `version`.

### 2.6. Monetary Precision, Basis Points, and Rounding

All money is represented as integer cents; there are no fractional-cent amounts anywhere in the system, and API bodies carry amounts as integers. Percentages are expressed in basis points with a denominator of 10000 — so 100 basis points is one percent and 10000 basis points is one hundred percent.

Rounding is round half up to whole cents, applied at every pinned rounding point of a calculation rather than once at the end. Three pricing stages pin their rounding at line granularity: a percent-of-charge base rounds each claim line to cents before summing, carve-out pricing rounds each carved line to cents before summing, and wrap-network pricing rounds each line to cents before summing. Per-day proration under per-diem escalation rounds each day rate to cents before summing. Nowhere does the system sum raw amounts and round the total; the per-element-then-sum order is part of the contract.

### 2.7. Optimistic Concurrency Control

Two creation endpoints guard their parent contract with optimistic concurrency: creating a rate amendment, and creating a renegotiation proposal. Both request bodies must carry `expected_contract_version`, a non-optional field holding the `version` of the target `PayerContract` as the client last observed it. If that value does not equal the contract's current `version` — for example because another writer advanced the contract since the client last read it — the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). The guard exists because each successful create mutates contract state beyond the new child record: a successful amendment create voids the contract's prior pending amendment and bumps the contract version, and a successful proposal create withdraws the contract's prior open proposal and bumps the contract version. No endpoint other than those two creations takes a version field.

### 2.8. Validation Order and Error Precedence

Every request passes through a fixed ladder of checks, and the rungs are evaluated in the order below: when several checks could fail on the same request, the failure on the earliest rung is the one reported, and later rungs are never reached once a failure has fired.

1. **Authentication context** — `X-User-ID` and `X-User-Role` must be present and the role must be one of the seven declared roles, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Applies to every endpoint.
2. **Authorization** — the caller's role must appear in the endpoint's authorized-role list, else `ERR_FORBIDDEN_FOR_ROLE`. Applies to every endpoint.
3. **Request shape** — on every write endpoint: required fields present, enum values valid, integers in range (amounts at least zero, basis-point fields within their declared bounds), dates well-formed, `effective_date` not after `expiration_date`, `admission_date` not after `discharge_date`, neither `discharge_date` nor `remittance_date` after today, and unknown body fields rejected, else `ERR_INVALID_REQUEST`.
4. **Existence** — every resource id referenced in the path or body (payer, contract, term, provision, escalator, amendment, agreement, claim, case, appeal, proposal, alert) must exist, else `ERR_NOT_FOUND`.
5. **Optimistic concurrency** — on the two OCC-guarded creations, `expected_contract_version` must equal the contract's current `version`, else `ERR_STALE_CONTRACT_VERSION`.
6. **State validity** — the target entity must be in a valid from-state for the requested transition, and terminal states reject every action: a claim must be priced before a remittance posts against it; a case must be under review for a write-off or a first appeal; appeal and proposal guards apply as defined in §3; direct term, carve-out, and stop-loss creation requires a `DRAFT` contract (`ERR_CONTRACT_NOT_DRAFT`); escalator creation requires the contract `DRAFT` or `ACTIVE`; amendment creation requires the contract `ACTIVE` or `SUSPENDED`; amendment approval and proposal submission require the contract `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`); proposal submission and acceptance require a fresh model (`ERR_PROPOSAL_STALE`); activation and resume additionally require the contract's `expiration_date` to lie after today (`ERR_CONTRACT_WINDOW_INVALID`). State violations not covered by a more specific identifier are rejected as `ERR_INVALID_STATE_TRANSITION`.
7. **Segregation of duties** — the amendment approver must differ from its creator (`ERR_SOD_AMENDMENT_SELF_APPROVE`), and the write-off approver must differ from the user who claimed the case (`ERR_SOD_WRITE_OFF_SELF`).
8. **Cross-entity references** — payer active for claim creation, contract creation, and contract activation (`ERR_PAYER_INACTIVE`); renewal predecessor belonging to the same payer (`ERR_PRIOR_CONTRACT_MISMATCH`); superseded amendment belonging to the same contract (`ERR_AMENDMENT_SUPERSEDE_MISMATCH`); appeal level matching the level the case is eligible to file next (`ERR_APPEAL_LEVEL_MISMATCH`); the resolved contract carrying a term for the claim's service category (`ERR_NO_MATCHING_TERM`).
9. **Temporal windows** — amendment and escalator effective dates within the contract term (`ERR_AMENDMENT_EFFECTIVE_OUT_OF_TERM`, `ERR_ESCALATOR_OUT_OF_TERM`); same-payer contract window overlap rules (`ERR_CONTRACT_WINDOW_OVERLAP`); same-payer-and-network agreement overlap (`ERR_NETWORK_AGREEMENT_OVERLAP`); claim line dates inside the stay (`ERR_LINE_OUTSIDE_STAY`); appeal filing windows per level (`ERR_APPEAL_WINDOW_CLOSED`).
10. **Uniqueness and consistency** — `ERR_DUPLICATE_CONTRACT_CODE`, `ERR_DUPLICATE_SERVICE_CATEGORY`, `ERR_DUPLICATE_CLAIM_NUMBER`, `ERR_CASE_ALREADY_ACTIVE`, `ERR_APPEAL_ALREADY_OPEN`, `ERR_ESCALATOR_DATE_COLLISION`, `ERR_INVALID_RATE_PARAMETERS`, `ERR_MISSING_DRG_WEIGHT`, `ERR_CLAIM_HAS_NO_LINES`, `ERR_WRITE_OFF_AMOUNT_MISMATCH`, and `ERR_RECOVERY_AMOUNT_INVALID`, each fired by the specific rule named alongside it in §3.
11. **Money guards** — posting a remittance may not push the claim's posted total above its billed charges (`ERR_REMITTANCE_EXCEEDS_CHARGES`); a write-off may not exceed the director cap (`ERR_WRITE_OFF_CAP_EXCEEDED`); arbitration requires a minimum outstanding balance (`ERR_ESCALATION_MIN_NOT_MET`).
12. **Escalation evidence** — an appeal above level 1 requires a qualifying outcome on the most recent prior-level appeal, else `ERR_ESCALATION_BLOCKED`.

### 2.9. Segregation of Duties

Two write operations are deliberately fenced against self-dealing. A rate amendment must be approved by a different operator than the one who created it: approval compares `X-User-ID` against the amendment's recorded `created_by_user_id` and rejects a match with `ERR_SOD_AMENDMENT_SELF_APPROVE`. Symmetrically, an underpayment case may not be written off by the analyst who claimed it: the write-off compares `X-User-ID` against the case's `claimed_by_user_id` and rejects a match with `ERR_SOD_WRITE_OFF_SELF`. Both rejections carry HTTP 409 and sit on rung 7 of the validation ladder — they fire before referential, temporal, and uniqueness checks on the same request.

### 2.10. Resource Addressing and Nested Path Validation

The resource topology is flat: every collection lives directly under `/api`, and resources reference one another through foreign-key fields in their bodies rather than through deep URL hierarchies. The single exception is the claim line, which is addressed beneath its parent claim (`/api/claims/{id}/lines`). For any request whose path contains more than one identifier, existence is validated strictly left to right: the parent claim's id is resolved first, and only after it exists does the system consider anything nested beneath it. The first identifier that does not resolve yields `ERR_NOT_FOUND`, per rung 4 of the ladder, before any business rule is consulted.

## 3. Business Logic & Workflows

### 3.1. Payer Onboarding and the Contract Lifecycle

Everything begins with the payer. A `ContractManager` onboards a payer by supplying its legal `name`, a `payer_type` of `COMMERCIAL`, `MEDICARE_ADVANTAGE`, `MEDICAID_MCO`, or `WORKERS_COMP`, and optionally `appeal_deadline_days` — the number of days allowed to file each appeal level, measured from the triggering event date, defaulting to 45 when omitted. A payer is born `ACTIVE`. Deactivation by a `ContractManager` moves it to `INACTIVE`, its only terminal state, and from that moment forward any attempt to create a claim, create a contract, or activate a contract for that payer is rejected with `ERR_PAYER_INACTIVE`.

Contracts are drafted by a `ContractAnalyst`. The creation payload names the owning `payer_id` — the payer must be `ACTIVE`, again on pain of `ERR_PAYER_INACTIVE` — a human-readable `contract_code` that must be unique across all of that payer's contracts (`ERR_DUPLICATE_CONTRACT_CODE`), and the inclusive coverage window from `effective_date` through `expiration_date`. An optional `prior_contract_id` chains the contract to its renewal predecessor; the predecessor must belong to the same payer, or creation fails with `ERR_PRIOR_CONTRACT_MISMATCH`. Financial policy knobs ride along at creation: `payment_terms_days` defaults to 30, the absolute variance floor `underpayment_threshold_cents` defaults to 5000 cents (fifty dollars), the relative floor `underpayment_threshold_bp` defaults to 100 basis points of expected reimbursement (one percent), and an optional `volume_tiers` list carries entries pairing a `service_category` with a `min_annual_units` hurdle and a `rate_adjustment_bp` that must lie between -2000 and 2000 inclusive. Within each category the hurdles must be strictly increasing; incoherent tier definitions are rejected with `ERR_INVALID_RATE_PARAMETERS`.

One structural rule guards the payer's book of business: coverage windows of the same payer's contracts may not share any calendar date unless the two contracts are renewal-linked through `prior_contract_id`, in which case they may share at most one boundary date. Overlapping windows outside that allowance are rejected with `ERR_CONTRACT_WINDOW_OVERLAP`.

A contract is born `DRAFT`. Activation by a `ContractManager` requires the payer to be `ACTIVE` and the `expiration_date` to lie after today — a window that has already closed is rejected with `ERR_CONTRACT_WINDOW_INVALID`. Successful activation increments the contract's `version` and triggers the renewal cascade: if the newly activated contract's `prior_contract_id` references a contract currently `ACTIVE` or `SUSPENDED`, that predecessor transitions to `SUPERSEDED` with its own version increment. From `ACTIVE`, a manager may suspend the contract; suspension blocks amendment approval, escalator and term mutation, and proposal submission, yet claim pricing continues under suspended contracts. Resuming a `SUSPENDED` contract re-applies the expiration-window check before returning it to `ACTIVE`. Termination is available from both `ACTIVE` and `SUSPENDED`, and it is not a pricing death: claims whose anchor dates fall inside the term remain priceable under a terminated contract as runout. Finally, the clock sweep moves an `ACTIVE` contract to `EXPIRED` once today passes its `expiration_date`, raising a `TERM_EXPIRED` alert as it does. `EXPIRED`, `TERMINATED`, and `SUPERSEDED` are terminal — every further action against a contract in one of those states is rejected with `ERR_INVALID_STATE_TRANSITION`.

Each contract also exposes `open_underpayment_cents`, a read-time rollup that sums `current_outstanding_cents` across the contract's underpayment cases whose status is not `RECOVERED`, `DENIED_FINAL`, `WRITTEN_OFF`, or `WITHDRAWN`. The figure is derived on read, never stored, and its movement never increments the contract's `version`. List views support filtering payers by `status` and contracts by `payer_id`, `prior_contract_id`, or `status`.

### 3.2. Loading the Rate Architecture: Terms, Carve-Outs, Stop-Loss, and Escalators

Rate content is loaded while the contract is still `DRAFT`. Once the contract has left `DRAFT`, mid-term rate changes must flow through the amendment machinery of §3.3; direct creation of terms, carve-outs, or stop-loss provisions against a non-draft contract is rejected with `ERR_CONTRACT_NOT_DRAFT`.

A `ContractAnalyst` loads one rate term per service line by naming the `contract_id`, a `service_category` drawn from `INPATIENT_MEDICAL`, `INPATIENT_SURGICAL`, `OUTPATIENT_SURGERY`, `EMERGENCY`, `OBSERVATION`, `IMAGING`, or `LAB` — at most one term per category per contract, enforced as `ERR_DUPLICATE_SERVICE_CATEGORY` — and a `rate_model` of `PER_DIEM`, `CASE_RATE`, `PERCENT_OF_CHARGE`, or `DRG_BASE`. The rate fields must cohere with the chosen model: `base_rate_cents` carries the per-diem day rate, the case rate, or the DRG base rate and is required unless the model is `PERCENT_OF_CHARGE`, while `percent_of_charge_bp` carries basis points of billed charge and is required exactly when the model is `PERCENT_OF_CHARGE`. Mismatched rate-field combinations are rejected with `ERR_INVALID_RATE_PARAMETERS`.

Carve-out provisions pull designated revenue lines out of base pricing and pay them under their own formula. A provision names its `contract_id`, a `carve_type` of `IMPLANT`, `HIGH_COST_DRUG`, `TRANSPLANT`, or `NICU`, a non-empty `revenue_codes` list identifying the carved lines, and a `rate_model` of `PERCENT_OF_CHARGE` or `INVOICE_COST_PLUS`. Under `PERCENT_OF_CHARGE` the provision must carry `percent_bp`; under `INVOICE_COST_PLUS` it must instead carry `invoice_markup_bp`, and the wrong pairing is again `ERR_INVALID_RATE_PARAMETERS`. An optional `max_cap_cents` caps each carved line's priced amount after rounding.

Stop-loss and outlier provisions protect the extremes. Each names its `contract_id`, a `provision_type` — `STOP_LOSS`, a floor that pays a percent of total charges, or `OUTLIER`, a marginal add-on on charges above a threshold — plus a strictly positive `threshold_cents` trigger level and a `rate_bp`. For a stop-loss the rate is the percent of total charges paid when the trigger is met; for an outlier it is the marginal percent of charges above the threshold. An optional `service_category` scopes the provision to one category; omitting it makes the provision a wildcard for every category of the contract. Non-positive thresholds or out-of-range rates are rejected with `ERR_INVALID_RATE_PARAMETERS`.

Rate escalators are the one piece of rate content that may also be scheduled after activation: creation requires the contract to be `DRAFT` or `ACTIVE`, and any other status yields `ERR_INVALID_STATE_TRANSITION`. An escalator carries its `contract_id`, an `effective_date` that must lie inside the contract term (`ERR_ESCALATOR_OUT_OF_TERM`) and must be unique among the contract's escalators (`ERR_ESCALATOR_DATE_COLLISION`), a strictly positive `escalator_bp`, an optional `applies_to_category` (omitted means all categories), and a `compounding` flag that defaults to true. A new escalator is `SCHEDULED`. When the clock reaches its effective date the sweep moves it to `APPLIED` and stamps `applied_date`; application on its own does not reprice anything, because escalators bind to claims by service-date anchor at pricing time. A `ContractManager` may void an escalator from either `SCHEDULED` or `APPLIED`, moving it to `VOIDED`. Voiding a merely scheduled escalator is quiet, but voiding an `APPLIED` one reprices the past: every claim priced under that contract, in `PRICED` or `REPRICED` pricing status, whose discharge date falls on or after the escalator's `effective_date` is repriced retrospectively, each repriced claim recomputes its variance and remittance standing, and the underpayment queue absorbs the difference — active cases are restated and fresh cases are queued wherever variance crosses the threshold. Terms, carve-outs, stop-loss provisions, and escalators each offer list views — filterable by `contract_id` and, respectively, `service_category`, `carve_type`, `provision_type`, or escalator `status`.

### 3.3. Mid-Term Amendments and the Retroactive Reprice Cascade

Once a contract is live, rates move only through amendments. Either a `ContractAnalyst` or a `ContractManager` may create one against an `ACTIVE` or `SUSPENDED` contract — creation against any other contract status is rejected with `ERR_INVALID_STATE_TRANSITION`. The payload names the `contract_id`, an `effective_date` that must lie within the contract term (`ERR_AMENDMENT_EFFECTIVE_OUT_OF_TERM`), and a non-empty `term_overrides` list whose entries name a `service_category` plus the `base_rate_cents` or `percent_of_charge_bp` that replace the term's values; every category named must already exist as a term on the contract. An optional `retroactive_to_date` reaches the amendment's effect backward: claims anchored on or after that date are repriced when the amendment becomes effective, and the retroactive date may not sit after the amendment's `effective_date` nor before the contract's own `effective_date` (both are `ERR_AMENDMENT_EFFECTIVE_OUT_OF_TERM`). An optional `supersedes_amendment_id` chains the amendment to the prior amendment it replaces; the referenced amendment must belong to the same contract, else `ERR_AMENDMENT_SUPERSEDE_MISMATCH`.

Because amendment creation mutates the contract itself, the create is optimistic-concurrency guarded: the request must carry `expected_contract_version` equal to the contract's current `version`, and a stale value is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), as detailed in §2.7. A successful create stamps the amendment `DRAFT`, records the caller as `created_by_user_id`, voids the contract's prior pending amendment — any prior amendment still `DRAFT` or `APPROVED` moves to `VOIDED` with a version bump — and increments the contract's `version`. At most one pending amendment exists per contract at any time; creating a new one is exactly how the prior pending one dies.

Approval is a `ContractManager` act with two fences, evaluated in ladder order: the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), and segregation of duties forbids the creator from approving their own work (`ERR_SOD_AMENDMENT_SELF_APPROVE`). Approval records `approved_by_user_id` and moves the amendment to `APPROVED`. A manager may also void an amendment while it is `DRAFT` or `APPROVED`.

The clock sweep is what makes an amendment real. When an `APPROVED` amendment's `effective_date` is reached, the sweep moves it to `EFFECTIVE` — applying multiple due amendments oldest `effective_date` first, ties broken by earliest `created_at` — bumping both the amendment's and the contract's `version`. Each application supersedes the chain it names: any other `EFFECTIVE` amendment on the same contract reachable through this amendment's `supersedes_amendment_id` chain transitions to `SUPERSEDED` with its own version bump. Supersession never strips an effective amendment of its historical reach — it merely moves the "latest" marker. Each application also emits an `AMENDMENT_EFFECTIVE` contract alert, deduplicated per amendment, and when `retroactive_to_date` is set it fires the three-link reprice cascade: first, every claim priced under this contract in `PRICED` or `REPRICED` status with a discharge date on or after `retroactive_to_date` is repriced retrospectively; second, each repriced claim recomputes its variance and remittance standing; third, every variance flip either creates a fresh `QUEUED` underpayment case or restates the active case's original and current outstanding amounts.

When pricing looks up a rate, the effective rate for a contract and category at a given anchor date is the term's base values overridden field-by-field by the contract's `EFFECTIVE` amendments whose applicability date is on or before the anchor — the applicability date being `retroactive_to_date` when set, otherwise the amendment's `effective_date`. Fields an override leaves absent keep the term's value. If several effective amendments override the same category at the same date, the one with the greatest applicability date wins, with ties broken by earliest `created_at`. Escalators always layer on top of the amended base: amendment first, escalator second. Amendments may be listed filtered by `contract_id`, `supersedes_amendment_id`, or `status`.

### 3.4. Wrap Networks and Silent-PPO Surveillance

Not every claim is covered by a direct contract; some payers route claims through wrap or PPO networks. A `ContractAnalyst` registers a network agreement with the accessing `payer_id`, a `network_name`, the `wrap_rate_bp` the network pays in basis points of billed charge — strictly greater than zero and at most 10000 — a `precedence_rank` that breaks ties in favor of the lower rank, and an inclusive coverage window from `effective_date` through `expiration_date`. Two agreements for the same payer under the same `network_name` may not share even a single calendar date while both are non-retired; the overlap check uses closed-interval semantics and rejects with `ERR_NETWORK_AGREEMENT_OVERLAP`.

An agreement is born `REGISTERED`. Verification by a `ContractManager` moves it to `VERIFIED` from either `REGISTERED` or `FLAGGED_SUSPECT`. A `RevenueIntegrityAnalyst` who suspects a silent-PPO arrangement flags a `VERIFIED` agreement, moving it to `FLAGGED_SUSPECT`; flagging deliberately does not reprice history — claims already priced `WRAP_CONFIRMED` under the agreement keep their numbers, and only future pricing runs see the new status. Retirement by a `ContractManager` is available from `REGISTERED`, `VERIFIED`, or `FLAGGED_SUSPECT` and lands the agreement in its terminal `RETIRED` state. Agreements may be listed filtered by `payer_id` or `status`.

### 3.5. Claim Intake, Pricing Resolution, and the Expected-Reimbursement Chain

A `RevenueIntegrityAnalyst` ingests a claim by naming the adjudicating `payer_id` — which must reference an `ACTIVE` payer, else `ERR_PAYER_INACTIVE` — a `claim_number` unique within that payer's book (`ERR_DUPLICATE_CLAIM_NUMBER`), the hospital's `patient_account_number`, the `service_category` (the same seven-value enumeration the contract terms use), the stay's `admission_date` and `discharge_date`, and the UB-04 `total_billed_charges_cents`, a figure at least zero and deliberately independent of any line-item sum. A `drg_weight` with three decimal places may ride along and becomes mandatory later if the resolved term turns out to be `DRG_BASE`. A new claim starts `UNPRICED` on its pricing dimension and `AWAITING_REMITTANCE` on its remittance dimension, with `network_flag` set to `NONE`; `priced_contract_id`, `network_agreement_id`, `pricing_variant`, `expected_reimbursement_cents`, and `original_expected_cents` all remain null until the first successful pricing run, and the two dimensions evolve independently from that point on.

While the claim is `UNPRICED`, the analyst adds lines beneath it — attempting to add a line after pricing is rejected with `ERR_INVALID_STATE_TRANSITION`. Each line carries a UB-04 `revenue_code`, a `service_date` that must lie inside the stay from `admission_date` through `discharge_date` inclusive (`ERR_LINE_OUTSIDE_STAY`), a `charge_cents` of at least zero, a `units` count defaulting to 1 and never below 1, and an optional `invoice_cost_cents` acquisition cost that becomes mandatory at price time if the line is matched by an invoice-cost-plus carve-out. Two computed fields appear on the line after pricing: `is_carve_out`, true when the line's `revenue_code` matches a carve-out provision of the priced contract, and `priced_amount_cents`, the line's rounded priced amount from the most recent pricing run.

Pricing, performed by a `RevenueIntegrityAnalyst`, is the heart of the system. The claim must still be `UNPRICED`; per the ladder of §2.8 the pricing run then requires a matching term on the resolved contract (`ERR_NO_MATCHING_TERM`) before the payload-level guards fire — at least one claim line (`ERR_CLAIM_HAS_NO_LINES`) and, when the resolved term's model is `DRG_BASE`, a present `drg_weight` (`ERR_MISSING_DRG_WEIGHT`). A successful first pricing moves the claim to `PRICED` and stamps `pricing_variant` to `PROSPECTIVE`: it sets `expected_reimbursement_cents`, freezes the same figure into `original_expected_cents` — an immutable snapshot no later run may overwrite — records the full `pricing_trace`, and resolves which payment instrument covers the claim.

Resolution proceeds in strict order, and a direct contract always beats every network agreement. First, the contract path: candidates are the payer's contracts in any status other than `DRAFT` whose window contains the anchor date — which is how suspended, terminated, expired, and superseded contracts continue to price in-term runout claims. The winner is the contract with the latest `effective_date`, ties broken by earliest `created_at`; a contract winner sets `priced_contract_id`, leaves `network_agreement_id` null, and keeps `network_flag` at `NONE`. Second, only when no contract covers the anchor, the wrap path: the payer's `VERIFIED` network agreements whose window contains the anchor compete, ranked by highest `wrap_rate_bp`, then lowest `precedence_rank`, then earliest `created_at`; a wrap winner sets `network_agreement_id`, leaves `priced_contract_id` null, and flags the claim `WRAP_CONFIRMED`. Third, only when both of those are empty, the suspect path: if any agreement of the payer covers the anchor in `REGISTERED` or `FLAGGED_SUSPECT` status, the claim is flagged `SILENT_PPO_SUSPECT` and its expected amount is the full `total_billed_charges_cents`, because no discount is entitled. Fourth and finally, the claim is flagged `OUT_OF_NETWORK`, again with expected reimbursement equal to full billed charges.

On the contract path, expected reimbursement is built in five ordered stages. The **base** dispatches on the resolved term's `rate_model`. Under `PER_DIEM`, the covered days are the calendar-day difference between `discharge_date` and `admission_date`, with a floor of one day, and each day earns the term's `base_rate_cents` with escalation applied per day as described below. Under `CASE_RATE`, the base is the term's `base_rate_cents` once per claim. Under `DRG_BASE`, the base is the term's `base_rate_cents` multiplied by the claim's `drg_weight`, rounded half up to whole cents. Under `PERCENT_OF_CHARGE`, each non-carved line contributes its `charge_cents` multiplied by the term's `percent_of_charge_bp` and divided by 10000, rounded half up per line, and the base is the sum of those line amounts — the system rounds per line and then sums, never sums and then rounds. For the three claim-level models the base is a single claim-level amount and carve-outs add on top; for `PERCENT_OF_CHARGE` the carve-out-eligible lines are excluded from the base and priced separately.

Next, **escalation**. The applicable escalators are the resolved contract's `APPLIED` escalators whose `applies_to_category` is either unset or matches the claim's category, processed in ascending `effective_date` order. A running multiplier starts at 1; each compounding escalator multiplies it by one plus its `escalator_bp` divided by 10000, while each non-compounding escalator instead adds its `escalator_bp` divided by 10000 to the running multiplier. Per-diem stays prorate mid-stay effective dates: each calendar day from `admission_date` through the day before `discharge_date` gets its own multiplier, computed over only those escalators whose `effective_date` is on or before that day, and each day's rate — the per-diem rate times that day's multiplier — is rounded half up to whole cents before the day rates sum to the escalated base. For every other rate model, the escalated base is the claim-level base times the multiplier evaluated at the anchor date, rounded half up once.

Third, **volume tiers**. Among the contract's `volume_tiers` entries for the claim's category, the system measures trailing units over the window spanning from 364 days before the anchor through the anchor itself, inclusive, counting other claims priced under the same contract in the same category with `pricing_status` `PRICED` or `REPRICED` and discharge dates inside the window — excluding the claim currently being priced. Units follow the rate model: covered days for `PER_DIEM`, claim count for `CASE_RATE` and `DRG_BASE`, and summed `total_billed_charges_cents` for `PERCENT_OF_CHARGE`. The selected tier is the entry with the greatest `min_annual_units` that the trailing units reach or exceed — a trailing count exactly equal to a tier's minimum selects that tier — and when no tier qualifies there is no adjustment. A selected tier scales the escalated amount by one plus its `rate_adjustment_bp` divided by 10000, rounded half up to whole cents.

Fourth, **carve-outs**. Each line whose `revenue_code` appears in one of the resolved contract's carve-out provisions is priced per line: under `PERCENT_OF_CHARGE`, the line's `charge_cents` times the provision's `percent_bp` divided by 10000; under `INVOICE_COST_PLUS`, the line's `invoice_cost_cents` times one plus the provision's `invoice_markup_bp` divided by 10000 — and if that line has no `invoice_cost_cents`, pricing fails with `ERR_INVALID_REQUEST`. Each line amount is rounded half up to whole cents and then, if the provision sets `max_cap_cents`, capped at that cap per line; the carve-out total is the sum of the capped line amounts. A line matching multiple provisions prices under the earliest-created provision and is counted once.

Fifth, the **stop-loss and outlier overlay**, evaluated in a pinned order over the contract's provisions whose `service_category` is unset or matches the claim. Outlier first: at most one `OUTLIER` provision applies — a category-specific one beats the wildcard — and if `total_billed_charges_cents` reaches or exceeds its `threshold_cents`, the outlier amount is the excess of total charges over the threshold, multiplied by `rate_bp` and divided by 10000, rounded half up; otherwise the outlier amount is zero. The subtotal is then the tiered base plus the carve-out total plus the outlier amount. Stop-loss second: if the applicable `STOP_LOSS` provision — again category-specific beats wildcard — has its `threshold_cents` met or exceeded by `total_billed_charges_cents`, the floor is total charges times `rate_bp` divided by 10000, rounded half up, and the final expected amount is the greater of the subtotal and that floor; otherwise the final amount is the subtotal. Both triggers use inclusive boundaries.

On the wrap path, pricing is deliberately simpler: each line is priced at its `charge_cents` times the agreement's `wrap_rate_bp` divided by 10000, rounded half up per line, and the expected amount is the sum of the line amounts. No escalators, volume tiers, carve-outs, or stop-loss overlays apply to wrap claims.

Every pricing run leaves an audit trail in the claim's `pricing_trace`: the `resolution_path` taken, the winning `contract_id` and `term_id`, the `base_amount_cents`, the `escalated_amount_cents`, the applied `volume_tier_bp`, the `carve_out_cents`, `outlier_cents`, and `stop_loss_cents` overlays, the `wrap_rate_bp` on the wrap path, and the `final_expected_cents`.

Repricing — whether invoked by a `RevenueIntegrityAnalyst` or fired by the amendment and escalator-void cascades — moves the claim from `PRICED` to `REPRICED`, or keeps an already-`REPRICED` claim there, and runs with `pricing_variant` set to `RETROSPECTIVE`: the pricing chain executes against the current amendment chain, whose retroactive overrides reach back to their `retroactive_to_date`, and the current set of `APPLIED` escalators. A reprice overwrites `expected_reimbursement_cents` and refreshes `pricing_trace`, but never touches `original_expected_cents`; identical claim data yields a different number whenever the effective rate set changed between the two runs. Each reprice recomputes `variance_cents`, re-evaluates the remittance dimension — flips between `RECONCILED` and `VARIANCE_FLAGGED` are allowed — and flows into the queue: an active case is restated to the new variance with its outstanding recomputed, and if no active case exists while the variance reaches the queue threshold, a fresh `QUEUED` case is born. Claims may be listed filtered by `payer_id`, `priced_contract_id`, `network_agreement_id`, `pricing_status`, `remittance_status`, or `network_flag`.

### 3.6. Remittance Posting, Variance Detection, and Case Queuing

Remittances close the loop between expectation and reality. A `RevenueIntegrityAnalyst` posts a payer remittance against a claim that must already be `PRICED` or `REPRICED` — remitting against an `UNPRICED` claim is rejected with `ERR_INVALID_STATE_TRANSITION`. The payload carries the `claim_id`, a `paid_amount_cents` of at least zero (zero-payment denials are legitimate postings), a `remittance_date` that may not lie in the future, and an optional `adjustment_reason_code` of `CONTRACTUAL`, `DENIAL`, `SILENT_PPO_DISCOUNT`, `APPEAL_RECOVERY`, or `OTHER`, defaulting to `OTHER`. Manually posted remittances are born `POSTED` with `source` `REMITTANCE_835`; the system itself creates remittances with `source` `APPEAL_RECOVERY` when appeals pay, stamping those with the originating `appeal_id`. One money guard applies at posting: the resulting total of `POSTED` remittances may not exceed the claim's `total_billed_charges_cents`, else `ERR_REMITTANCE_EXCEEDS_CHARGES`.

Three computed figures track the claim's cash position. `paid_amount_cents` sums `paid_amount_cents` over `POSTED` remittances only — reversed ones stop counting. `variance_cents` is `expected_reimbursement_cents` minus `paid_amount_cents`, null until the claim is priced. The queue threshold is the greater of two legs: the contract's absolute floor `underpayment_threshold_cents`, and the relative floor computed as `expected_reimbursement_cents` times `underpayment_threshold_bp` divided by 10000, rounded half up to whole cents. Claims priced on the wrap, silent-PPO, or out-of-network paths have no contract to borrow thresholds from, so system defaults apply: 5000 cents and 100 basis points. A variance that reaches or exceeds the threshold — the boundary is inclusive — is an underpayment; anything below it, including a negative overpayment variance, reconciles the claim with no case.

The remittance dimension moves on its own machine. The first `POSTED` remittance lifts a claim from `AWAITING_REMITTANCE` to `REMITTANCE_POSTED`, but that state is a transient observation point: the same mutation immediately re-evaluates variance and lands the claim on `VARIANCE_FLAGGED` or `RECONCILED`. Landing on `VARIANCE_FLAGGED` — from `REMITTANCE_POSTED`, or later from `RECONCILED` when a reprice or reversal pushes variance back up to the threshold — has queue consequences: if no active case exists for the claim, one is created in `QUEUED` status with `original_variance_cents` set to the current variance, `queued_date` set to today, and `payer_id` and `contract_id` denormalized from the claim (the contract reference stays null for wrap and out-of-network claims); if an active case already exists it is restated instead, its `original_variance_cents` overwritten with the current variance and its outstanding recomputed. At most one non-terminal case may exist per claim — `ERR_CASE_ALREADY_ACTIVE` guards the system creation paths, and manual case creation is not offered at all. Landing on `RECONCILED` restates the active case, if any, but never auto-closes it. When every `POSTED` remittance has been reversed and none remain, the claim falls back to `AWAITING_REMITTANCE`; the active case is restated and, with variance recomputed against zero payments, its outstanding reflects the full expected amount.

Reversal is a `FinanceDirector` act that turns a `POSTED` remittance to `REVERSED`, with one guard: a remittance born of an appeal recovery may be reversed only while the linked appeal's case is still non-terminal, else `ERR_INVALID_STATE_TRANSITION`. The reversal cascade runs in three links — the claim's `paid_amount_cents` is recomputed over the remaining posted remittances; variance and the remittance dimension are re-evaluated; and the queue absorbs the result, restating the active case, or queuing a fresh `QUEUED` case when variance again reaches the threshold and no active case exists — including when the claim's prior case already closed `RECOVERED` — or dropping the claim back to `AWAITING_REMITTANCE` when nothing remains posted. Remittances may be listed filtered by `claim_id`, `appeal_id`, or `status`.

### 3.7. Working the Queue: Review, Write-Off, and the Four-Level Appeal Matrix

An underpayment case is the unit of recovery work. Beyond the fields set at queuing, a case tracks `recovered_to_date_cents` — the sum of `recovered_amount_cents` over its appeals whose outcome is `PAID_IN_FULL` or `PARTIAL_PAYMENT`, minus the paid amount of every `REVERSED` appeal-recovery remittance linked to those appeals, since a reversal cancels its recovery — a `write_off_amount_cents` that starts at zero, an `escalation_level` that starts at 0 and tracks the active appeal level 1 through 4, the `claimed_by_user_id` of whoever picked it up, and a computed `appeal_filing_deadline` equal to `queued_date` plus the payer's `appeal_deadline_days`. The case's money ledger obeys one invariant in every status: `original_variance_cents` always equals the sum of `current_outstanding_cents`, `recovered_to_date_cents`, and `write_off_amount_cents`, with the outstanding figure computed as the original variance minus recoveries minus write-offs.

A `RevenueIntegrityAnalyst` or `RecoveryManager` picks a `QUEUED` case up, moving it to `UNDER_REVIEW` and stamping `claimed_by_user_id`. Either role may withdraw a case from `QUEUED` or `UNDER_REVIEW`, landing it in terminal `WITHDRAWN`. Write-off belongs to the `FinanceDirector`, is available only from `UNDER_REVIEW`, and is fenced by three checks in ladder order: segregation of duties forbids the claimer from writing off their own case (`ERR_SOD_WRITE_OFF_SELF`); the supplied `amount_cents` must equal the case's full `current_outstanding_cents` — partial write-offs do not exist (`ERR_WRITE_OFF_AMOUNT_MISMATCH`); and the outstanding balance must not exceed the director cap of 250000 cents — twenty-five hundred dollars — else `ERR_WRITE_OFF_CAP_EXCEEDED`. A successful write-off records `write_off_amount_cents`, zeroes the outstanding balance, and moves the case to terminal `WRITTEN_OFF`; the director supplies a `reason` alongside the amount. Recovery, by contrast, needs no endpoint: a case in `UNDER_REVIEW` or at any appeal level — `APPEAL_L1`, `APPEAL_L2`, `MEDIATION`, or `ARBITRATION` — auto-transitions to `RECOVERED` the moment a payment or recovery drives `current_outstanding_cents` to zero, whether that payment arrives as a direct remittance before any appeal or as an appeal recovery at any level.

Appeals are the escalation engine. Creating an appeal — the act reserved for a `RevenueIntegrityAnalyst` or `RecoveryManager` — names the `case_id` and a `level` of 1, 2, 3, or 4. The new appeal is born `DRAFT` with outcome `PENDING` and `recovered_amount_cents` zero, its `channel` derived from the level: level 1 is an `INTERNAL_REVIEW`, level 2 a `FORMAL_APPEAL`, level 3 `MEDIATION`, and level 4 `ARBITRATION`. Creation is also what escalates the case: a level-1 appeal moves the case from `UNDER_REVIEW` to `APPEAL_L1`, and subsequent levels move it from `APPEAL_L1` to `APPEAL_L2`, then to `MEDIATION`, then to `ARBITRATION`, with `escalation_level` advancing to match on each progression.

Appeal creation carries the densest guard set in the system, evaluated in ladder order. The case must sit in a valid from-state for the requested level (`ERR_INVALID_STATE_TRANSITION`). The requested `level` must equal the case's current `escalation_level` plus one — progression — or equal the current `escalation_level` when the most recent appeal at that same level is `WITHDRAWN`, which is the only refile path; any other combination is `ERR_APPEAL_LEVEL_MISMATCH`. Filing windows come next: a level-1 appeal must be created on or before the case's `appeal_filing_deadline`, and a level-n appeal must be created on or before the prior level's `outcome_recorded_date` plus the payer's `appeal_deadline_days`; when no prior-level appeal has a recorded outcome the window check is vacuous and the evidence check below decides. Window violations are `ERR_APPEAL_WINDOW_CLOSED`. The case may not already hold an appeal in `DRAFT` or `FILED` (`ERR_APPEAL_ALREADY_OPEN`). Arbitration adds a size gate: the case's `current_outstanding_cents` must be at least 100000 cents — one thousand dollars — else `ERR_ESCALATION_MIN_NOT_MET`. Finally, the evidence rule: escalating to any level above 1 requires the case's most recent non-`WITHDRAWN` appeal at the prior level to have closed with outcome `DENIED`, `EXPIRED`, or `PARTIAL_PAYMENT`, else `ERR_ESCALATION_BLOCKED`.

Filing an appeal — available to either recovery role while the appeal is `DRAFT` — moves it to `FILED`, stamps `filed_date` with today, and starts the payer's response clock: `response_due_date` is the filed date plus 30 calendar days at levels 1 and 2, 45 days at level 3, and 60 days at level 4. If today passes `response_due_date` with no outcome recorded — the due date itself is still timely — the clock sweep expires the appeal: it moves to terminal `EXPIRED`, its `outcome` becomes `EXPIRED`, `outcome_recorded_date` is stamped, and a level-4 expiry additionally drives its case to `DENIED_FINAL`.

Recording the payer's response is a `RecoveryManager` act on a `FILED` appeal, moving it to terminal `CLOSED` and stamping `outcome_recorded_date` with today. Three paid-or-not outcomes branch here. `PAID_IN_FULL` sets the appeal's `recovered_amount_cents` to the case's outstanding balance at outcome time — the caller must not supply `recovered_amount_cents` for this outcome (`ERR_RECOVERY_AMOUNT_INVALID`) — creates an `APPEAL_RECOVERY` remittance on the claim for that amount, recomputes the claim's paid and variance figures, and drives the case's outstanding to zero and the case to `RECOVERED`. `PARTIAL_PAYMENT` takes the caller's `recovered_amount_cents`, which must be strictly greater than zero and strictly less than the case's `current_outstanding_cents` (`ERR_RECOVERY_AMOUNT_INVALID`); it likewise creates an `APPEAL_RECOVERY` remittance for the recovered amount, recomputes the claim, reduces the case's outstanding, and leaves the case at its current level for further work. `DENIED` creates no remittance; only at level 4 does it close the book, moving the case to `DENIED_FINAL`. Withdrawing an appeal — from `DRAFT` or `FILED`, by either recovery role — moves it to terminal `WITHDRAWN`, leaves the case at its current level, and preserves the option to file a fresh appeal at that same level under the refile rule above. Cases may be listed filtered by `claim_id`, `payer_id`, `contract_id`, `status`, or `escalation_level`; appeals by `case_id`, `level`, or `outcome`.

### 3.8. Renegotiation Proposals and Volume-Mix Modeling

When a contract approaches renewal, the modeling workflow begins. A `ContractAnalyst` creates a proposal against the contract being renegotiated, carrying the `contract_id`, a non-empty `proposed_terms` list whose entries each name a `service_category`, a `rate_model`, and the `base_rate_cents` or `percent_of_charge_bp` the model demands — every category must already exist as a term on the contract — and a `projected_volume_mix` list pairing each `service_category` with `annual_units`, where a unit means patient-days for `PER_DIEM`, cases for `CASE_RATE` and `DRG_BASE`, and charge cents for `PERCENT_OF_CHARGE`. Like amendment creation, proposal creation is optimistic-concurrency guarded by `expected_contract_version`, with staleness rejected as `ERR_STALE_CONTRACT_VERSION` (HTTP 412) per §2.7. A successful create opens the proposal in `DRAFT` with `round_number` 1, withdraws the contract's prior open proposal — any predecessor still `DRAFT`, `MODELED`, `SUBMITTED`, or `COUNTERED` moves to `WITHDRAWN` with a version bump — and increments the contract's `version`, which is precisely why the guard exists.

Running the model, an analyst act, moves the proposal from `DRAFT` to `MODELED` and pins `modeled_contract_version` to the contract's current `version`. The model looks back over the trailing window from 364 days before today through today inclusive and, for each service category that has a term on the contract, measures trailing units over claims priced under the contract with discharge dates in the window and pricing status `PRICED` or `REPRICED` — patient-days for `PER_DIEM`, claim counts for `CASE_RATE` and `DRG_BASE`, and summed billed charges for `PERCENT_OF_CHARGE`. Two unit rates are then computed per category: the current unit rate, being the rate effective at today — the term resolved through the amendment chain at an anchor of today with `APPLIED` escalators layered on, and `DRG_BASE` evaluated at the normalized weight 1.000 — and the proposed unit rate, being the `proposed_terms` entry for the category where one exists and the current rate where none does. The mix volume for a category is its `projected_volume_mix` entry where present, otherwise its trailing actuals.

Every model run computes and stores two variants side by side. The same-store variant holds volume at trailing actuals on both sides to isolate the pure rate effect: `baseline_same_store_cents` sums trailing units times current unit rates across categories, the modeled figure sums trailing units times proposed unit rates, and `delta_same_store_cents` is the modeled figure minus the baseline. The mix-shifted variant applies the projected volume mix on both sides, conflating rate and mix effects: `baseline_mix_shifted_cents` sums mix volumes times current unit rates, its modeled counterpart sums mix volumes times proposed unit rates, and `delta_mix_shifted_cents` is that modeled figure minus its baseline. Each per-category product is rounded half up to whole cents before the products are summed. The two variants run on identical inputs and are always both stored; they diverge exactly when the projected mix differs from trailing actuals.

A proposal's usefulness decays with contract drift: `is_stale` is true whenever a proposal in `MODELED`, `SUBMITTED`, or `COUNTERED` was modeled against a contract `version` that no longer matches the contract's current `version`. Submission by a `ContractManager` — from `MODELED`, and again from `COUNTERED` on resubmission — requires the contract to be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the proposal fresh (`ERR_PROPOSAL_STALE`); resubmission from `COUNTERED` also increments `round_number`. Recording a payer counter-offer, another manager act, moves a `SUBMITTED` proposal to `COUNTERED`. Acceptance belongs to the `FinanceDirector`, is allowed from `SUBMITTED` or `COUNTERED`, requires only that the proposal not be stale (`ERR_PROPOSAL_STALE`), and is the moment the deal becomes real: the system materializes the successor contract in `DRAFT`, taking `contract_code` from the supplied `successor_contract_code`, its window from `successor_effective_date` and `successor_expiration_date`, chaining `prior_contract_id` to the current contract, copying the current contract's `underpayment_threshold_cents`, `underpayment_threshold_bp`, and `volume_tiers`, and minting one contract term per `proposed_terms` entry. Rejection by a `ContractManager` moves a `SUBMITTED` or `COUNTERED` proposal to `REJECTED`; withdrawal by a `ContractManager` or `ContractAnalyst` — or by the system when a newer proposal supersedes it — moves any open proposal to `WITHDRAWN`. `ACCEPTED`, `REJECTED`, and `WITHDRAWN` are terminal. Proposals may be listed filtered by `contract_id` or `status`.

### 3.9. The Clock Sweep, Expirations, and Contract Alerts

The clock sweep is the system's heartbeat, running once at startup and again on every clock-setting invocation, and its five steps always execute in a pinned order, each completing before the next begins. Step one applies escalators: every `SCHEDULED` escalator whose `effective_date` is on or before today moves to `APPLIED` with `applied_date` stamped to today. Step two applies amendments: every `APPROVED` amendment whose `effective_date` is on or before today moves to `EFFECTIVE`, oldest `effective_date` first with ties broken by earliest `created_at`, each application superseding the amendments in its supersede chain, emitting its `AMENDMENT_EFFECTIVE` alert, and running the retroactive reprice cascade of §3.3 when `retroactive_to_date` is set. Step three expires appeals: every `FILED` appeal whose `response_due_date` has passed moves to `EXPIRED`, and a level-4 expiry drives its case to `DENIED_FINAL`. Step four expires contracts: every `ACTIVE` contract whose `expiration_date` has passed moves to `EXPIRED` and raises a `TERM_EXPIRED` alert. Step five generates the remaining alerts, deduplicated so the sweep never creates a second alert with the same key.

Three alert families come out of step five, each keyed for idempotency. `TERM_EXPIRING_90` fires for a contract in `ACTIVE` or `SUSPENDED` whose `expiration_date` lies between 0 and 90 days after today inclusive, keyed on the contract and alert type. `TERM_EXPIRING_30` fires on the same condition with a 30-day window, keyed identically — so a contract inside thirty days carries both alerts. `ESCALATOR_UPCOMING` fires for a `SCHEDULED` escalator whose `effective_date` lies between 0 and 30 days after today inclusive, keyed on contract, alert type, and escalator. The two step-internal alerts round out the catalog: `AMENDMENT_EFFECTIVE`, emitted in step two and keyed on contract, alert type, and amendment; and `TERM_EXPIRED`, emitted in step four and keyed on contract and alert type.

Every alert records its `contract_id`, the triggering `escalator_id` or `amendment_id` where one applies, its `alert_type`, and the `trigger_date` the sweep stamped. An alert is born `TRIGGERED`; a `ContractManager` may acknowledge it to `ACKNOWLEDGED` or dismiss it to `DISMISSED`, and an acknowledged alert may still be dismissed — both are terminal rest states for the alert. Alerts may be listed filtered by `contract_id`, `escalator_id`, `amendment_id`, `alert_type`, or `status`. The clock-setting capability itself answers with a sweep summary: the new `current_utc` plus the counts `escalators_applied`, `amendments_applied`, `appeals_expired`, `contracts_expired`, and `alerts_generated`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify an existing resource — including all state transitions and the clock sweep — return `200 OK`. Read endpoints are available to every declared role; the table denotes this as "All roles". Request payloads, preconditions, cascades, and computed fields are defined by the narratives in §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/api/payers` | Create a payer | ContractManager |
| GET    | `/api/payers/{id}` | Get a payer | All roles |
| GET    | `/api/payers` | List payers | All roles |
| POST   | `/api/payers/{id}/deactivate` | Deactivate a payer | ContractManager |
| POST   | `/api/payer-contracts` | Create a contract (DRAFT); window-overlap and renewal-link rules apply | ContractAnalyst |
| GET    | `/api/payer-contracts/{id}` | Get a contract | All roles |
| GET    | `/api/payer-contracts` | List contracts | All roles |
| POST   | `/api/payer-contracts/{id}/activate` | Activate a DRAFT contract; supersedes the renewal predecessor when ACTIVE or SUSPENDED | ContractManager |
| POST   | `/api/payer-contracts/{id}/suspend` | Suspend an ACTIVE contract (pricing continues; amendments and proposals blocked) | ContractManager |
| POST   | `/api/payer-contracts/{id}/resume` | Resume a SUSPENDED contract | ContractManager |
| POST   | `/api/payer-contracts/{id}/terminate` | Terminate an ACTIVE or SUSPENDED contract (in-term claims still price as runout) | ContractManager |
| POST   | `/api/contract-terms` | Load a rate term onto a DRAFT contract | ContractAnalyst |
| GET    | `/api/contract-terms/{id}` | Get a contract term | All roles |
| GET    | `/api/contract-terms` | List contract terms | All roles |
| POST   | `/api/carve-out-provisions` | Add a carve-out provision to a DRAFT contract | ContractAnalyst |
| GET    | `/api/carve-out-provisions/{id}` | Get a carve-out provision | All roles |
| GET    | `/api/carve-out-provisions` | List carve-out provisions | All roles |
| POST   | `/api/stop-loss-provisions` | Add a stop-loss or outlier provision to a DRAFT contract | ContractAnalyst |
| GET    | `/api/stop-loss-provisions/{id}` | Get a stop-loss provision | All roles |
| GET    | `/api/stop-loss-provisions` | List stop-loss provisions | All roles |
| POST   | `/api/rate-escalators` | Schedule a rate escalator (contract DRAFT or ACTIVE; effective date unique per contract) | ContractAnalyst |
| GET    | `/api/rate-escalators/{id}` | Get a rate escalator | All roles |
| GET    | `/api/rate-escalators` | List rate escalators | All roles |
| POST   | `/api/rate-escalators/{id}/void` | Void a SCHEDULED or APPLIED escalator; voiding an APPLIED one reprices affected claims | ContractManager |
| POST   | `/api/rate-amendments` | Create a rate amendment (OCC-guarded; voids the contract's prior pending amendment) | ContractAnalyst, ContractManager |
| GET    | `/api/rate-amendments/{id}` | Get a rate amendment | All roles |
| GET    | `/api/rate-amendments` | List rate amendments | All roles |
| POST   | `/api/rate-amendments/{id}/approve` | Approve a DRAFT amendment (contract must be ACTIVE; no self-approval) | ContractManager |
| POST   | `/api/rate-amendments/{id}/void` | Void a DRAFT or APPROVED amendment | ContractManager |
| POST   | `/api/network-agreements` | Register a wrap/PPO network agreement (closed-interval overlap rejected) | ContractAnalyst |
| GET    | `/api/network-agreements/{id}` | Get a network agreement | All roles |
| GET    | `/api/network-agreements` | List network agreements | All roles |
| POST   | `/api/network-agreements/{id}/verify` | Verify a REGISTERED or FLAGGED_SUSPECT agreement | ContractManager |
| POST   | `/api/network-agreements/{id}/flag_suspect` | Flag a VERIFIED agreement as suspected silent-PPO | RevenueIntegrityAnalyst |
| POST   | `/api/network-agreements/{id}/retire` | Retire a non-retired agreement | ContractManager |
| POST   | `/api/claims` | Ingest a claim (starts UNPRICED / AWAITING_REMITTANCE) | RevenueIntegrityAnalyst |
| GET    | `/api/claims/{id}` | Get a claim | All roles |
| GET    | `/api/claims` | List claims | All roles |
| POST   | `/api/claims/{id}/lines` | Add a claim line (only while UNPRICED) | RevenueIntegrityAnalyst |
| GET    | `/api/claims/{id}/lines` | List a claim's lines | All roles |
| POST   | `/api/claims/{id}/price` | Run PROSPECTIVE pricing: resolution, base, escalators, tiers, carve-outs, stop-loss/outlier | RevenueIntegrityAnalyst |
| POST   | `/api/claims/{id}/reprice` | Run RETROSPECTIVE pricing under the current amendment/escalator set | RevenueIntegrityAnalyst |
| POST   | `/api/remittances` | Post a payer remittance against a priced claim; evaluates variance and may queue a case | RevenueIntegrityAnalyst |
| GET    | `/api/remittances/{id}` | Get a remittance | All roles |
| GET    | `/api/remittances` | List remittances | All roles |
| POST   | `/api/remittances/{id}/reverse` | Reverse a POSTED remittance (appeal-recovery remittances only while their case is non-terminal) | FinanceDirector |
| GET    | `/api/underpayment-cases/{id}` | Get an underpayment case | All roles |
| GET    | `/api/underpayment-cases` | List underpayment cases (the work queue) | All roles |
| POST   | `/api/underpayment-cases/{id}/pick_up` | Claim a queued case for review | RevenueIntegrityAnalyst, RecoveryManager |
| POST   | `/api/underpayment-cases/{id}/write_off` | Write off the full outstanding balance (SoD vs claimer; director cap) | FinanceDirector |
| POST   | `/api/underpayment-cases/{id}/withdraw` | Withdraw a QUEUED or UNDER_REVIEW case | RevenueIntegrityAnalyst, RecoveryManager |
| POST   | `/api/appeals` | Open an appeal at the level the case is eligible for; moves the case into that level | RevenueIntegrityAnalyst, RecoveryManager |
| GET    | `/api/appeals/{id}` | Get an appeal | All roles |
| GET    | `/api/appeals` | List appeals | All roles |
| POST   | `/api/appeals/{id}/file` | File a DRAFT appeal; starts the payer response clock | RevenueIntegrityAnalyst, RecoveryManager |
| POST   | `/api/appeals/{id}/record_outcome` | Record the payer's response; paid outcomes create APPEAL_RECOVERY remittances | RecoveryManager |
| POST   | `/api/appeals/{id}/withdraw` | Withdraw a DRAFT or FILED appeal (case remains at its level) | RevenueIntegrityAnalyst, RecoveryManager |
| POST   | `/api/contract-proposals` | Create a renegotiation proposal (OCC-guarded; withdraws the contract's prior open proposal) | ContractAnalyst |
| GET    | `/api/contract-proposals/{id}` | Get a proposal | All roles |
| GET    | `/api/contract-proposals` | List proposals | All roles |
| POST   | `/api/contract-proposals/{id}/run_model` | Compute same-store and mix-shifted baselines/deltas; pins the modeled contract version | ContractAnalyst |
| POST   | `/api/contract-proposals/{id}/submit` | Submit a MODELED or COUNTERED proposal to the payer (blocked when stale) | ContractManager |
| POST   | `/api/contract-proposals/{id}/record_counter` | Record a payer counter-offer | ContractManager |
| POST   | `/api/contract-proposals/{id}/accept` | Accept the proposal; materializes the successor DRAFT contract with the proposed terms | FinanceDirector |
| POST   | `/api/contract-proposals/{id}/reject` | Reject the proposal | ContractManager |
| POST   | `/api/contract-proposals/{id}/withdraw` | Withdraw an open proposal | ContractManager, ContractAnalyst |
| GET    | `/api/contract-alerts/{id}` | Get a contract alert | All roles |
| GET    | `/api/contract-alerts` | List contract alerts | All roles |
| POST   | `/api/contract-alerts/{id}/acknowledge` | Acknowledge a TRIGGERED alert | ContractManager |
| POST   | `/api/contract-alerts/{id}/dismiss` | Dismiss a TRIGGERED or ACKNOWLEDGED alert | ContractManager |
| POST   | `/api/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC) and re-run the full clock sweep; backward moves permitted; sweep idempotent | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is the identifier-to-status reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_CONTRACT_NOT_DRAFT` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROPOSAL_STALE` | 409 Conflict |
| `ERR_SOD_AMENDMENT_SELF_APPROVE` | 409 Conflict |
| `ERR_SOD_WRITE_OFF_SELF` | 409 Conflict |
| `ERR_PAYER_INACTIVE` | 409 Conflict |
| `ERR_PRIOR_CONTRACT_MISMATCH` | 409 Conflict |
| `ERR_AMENDMENT_SUPERSEDE_MISMATCH` | 409 Conflict |
| `ERR_APPEAL_LEVEL_MISMATCH` | 409 Conflict |
| `ERR_NO_MATCHING_TERM` | 409 Conflict |
| `ERR_CONTRACT_WINDOW_INVALID` | 409 Conflict |
| `ERR_CONTRACT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AMENDMENT_EFFECTIVE_OUT_OF_TERM` | 409 Conflict |
| `ERR_ESCALATOR_OUT_OF_TERM` | 409 Conflict |
| `ERR_ESCALATOR_DATE_COLLISION` | 409 Conflict |
| `ERR_NETWORK_AGREEMENT_OVERLAP` | 409 Conflict |
| `ERR_LINE_OUTSIDE_STAY` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_APPEAL_ALREADY_OPEN` | 409 Conflict |
| `ERR_CASE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_CONTRACT_CODE` | 409 Conflict |
| `ERR_DUPLICATE_SERVICE_CATEGORY` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM_NUMBER` | 409 Conflict |
| `ERR_INVALID_RATE_PARAMETERS` | 422 Unprocessable Entity |
| `ERR_MISSING_DRG_WEIGHT` | 422 Unprocessable Entity |
| `ERR_CLAIM_HAS_NO_LINES` | 422 Unprocessable Entity |
| `ERR_WRITE_OFF_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RECOVERY_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_REMITTANCE_EXCEEDS_CHARGES` | 409 Conflict |
| `ERR_WRITE_OFF_CAP_EXCEEDED` | 409 Conflict |
| `ERR_ESCALATION_MIN_NOT_MET` | 409 Conflict |
| `ERR_ESCALATION_BLOCKED` | 409 Conflict |
