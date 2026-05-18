# Personal Tax Filing API — Product Requirements Document

## 1. Introduction

The Personal Tax Filing API powers a consumer-facing tax preparation product modelled on the TurboTax experience. The system guides an individual taxpayer from the moment they import their first wage statement through the final adjudication of their federal income tax return, and — when the IRS has spoken — through the corrective workflow for filing an amended 1040X. Along the way the same engine schedules quarterly estimated payments, evaluates eligibility for refundable and non-refundable credits, and exposes a safe-harbor advisory so taxpayers can avoid underpayment penalties.

Two distinct user populations meet inside this API. End-user taxpayers compose returns, import documents from a variety of payer sources, claim credits, and electronically submit. IRS adjudicators, on the other side of the line, are responsible for accepting or rejecting submissions and, when compliance issues surface, locking a taxpayer's account so further filings cannot proceed. The API must enforce strict separation between these two populations — a taxpayer must never adjudicate, an adjudicator must never file — while sharing a common audit and observability surface.

Because tax calculations are pinned to statute and small rounding differences compound across brackets, phase-outs, and credit waterfalls, the system represents every monetary value as integer cents and pins the evaluation order of every formula. Optimistic concurrency, a system-controlled virtual clock for deterministic quarterly-payment automation, and an append-only audit log round out the cross-cutting machinery on which all higher-level workflows depend.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` to identify the acting principal, and `X-User-Role` to declare its operational capacity. The system recognises exactly two roles: `Taxpayer` and `IRSAdjudicator`. A request that omits either header is rejected with `ERR_AUTH_REQUIRED`, and a request whose role is not authorised for the targeted operation is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `Taxpayer`, `X-User-ID` is the `id` of the acting `Taxpayer` entity. Ownership checks on any resource that references a `Taxpayer` (directly or transitively through its parent `TaxReturn`) compare the resource's `taxpayer_id` foreign-key field — or the `taxpayer_id` of the resource's owning return — to `X-User-ID`. A `Taxpayer` principal may only read and mutate resources whose ownership chain resolves to their own `id`.

When `X-User-Role` is `IRSAdjudicator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on the audit log (specifically, as `actor_id` on an `AuditLog` row written by an adjudicator-driven transition) but does not compare it to any entity's `id`. An `IRSAdjudicator` principal has cross-taxpayer read visibility on the resources their workflow requires (returns, filings, amendments, audit logs) but cannot initiate filings or amendments on behalf of any taxpayer.

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

Endpoints that return collections accept two query parameters. The `limit` parameter caps the number of items returned and defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the head of the result set and defaults to 0. All list endpoints sort their results by the resource's creation timestamp in ascending order unless documented otherwise. The `meta` envelope of every list response carries `limit`, `offset`, `total_count` (the total number of items that match the query before pagination is applied), and `has_more` (a boolean indicating whether further pages remain).

### 2.4. Common Resource Properties

Every primary resource — `Taxpayer`, `TaxReturn`, `IncomeDocument`, `Schedule`, `TaxCredit`, `AmendedReturn`, and `EstimatedTaxPayment` — exposes the following four system-managed fields:

- `id` (string): a unique, server-minted UUID. The identifier carries no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits captured when the resource is first persisted.
- `updated_at` (string): an ISO 8601 UTC timestamp with the same format, refreshed on every mutation of the resource's properties.
- `version` (integer): a monotonically increasing integer that starts at 1 on creation and increments by exactly 1 on every mutation. Used for optimistic concurrency control as described in §2.6.

The `EFiling` and `AuditLog` records are the exceptions. Both are append-style records that carry an `id` and a `created_at` timestamp; neither exposes `updated_at`, and neither exposes a `version` field, because once they are written they are not mutated by clients. Mutations the server makes to an `EFiling`'s `outcome`, `processed_at`, `rejection_code`, or `rejection_message` are part of the IRS adjudication side-effect cascade described in §3 and are not subject to client-supplied optimistic concurrency.

### 2.5. Monetary Values and Precision

Every monetary quantity exchanged with the API — wages, withholding, deductions, tax amounts, credits, payments, deltas — is represented as a non-negative or signed integer count of cents. The product is built this way to make every formula reproducible: the system never carries decimals through intermediate steps, and every rounding decision is pinned to a specific step in a specific formula. Each calculation rule in §3 specifies its own rounding behaviour explicitly, and the default rounding direction at any per-step integer ratio is truncation toward zero (floor division on non-negative inputs); thresholds for the safe-harbor advisory are computed with ceiling rounding because they represent a minimum the taxpayer must reach. The system never applies a final "half-up" rounding pass across formulas — once a step truncates, the truncated value is the input to the next step.

### 2.6. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When `version` is supplied, the server compares it to the current `version` of the targeted entity; a mismatch is rejected with `ERR_VERSION_CONFLICT` (HTTP 409) and the resource is left untouched. When `version` is omitted, the operation proceeds without an optimistic concurrency check. OCC is required reading for the compute pipeline: a `TaxReturn`'s computed values are derived from its children (`IncomeDocument`, `Schedule`, `TaxCredit`), and any mutation of a child bumps the parent `TaxReturn`'s `version` so a stale-version compute against the parent will be rejected.

Two specific race patterns deserve their own treatment. When two clients call the compute endpoint concurrently on the same return, only one wins the `version` compare-and-swap; the loser receives `ERR_VERSION_CONFLICT` and must re-read before retrying. When a `compute` and a child `PATCH` (for example, on an `IncomeDocument`) race, whichever request first commits its parent-version bump wins; the loser likewise receives `ERR_VERSION_CONFLICT`.

### 2.7. Hierarchical Consistency and Cascades

Mutations rarely live in isolation. Five cascade patterns govern most cross-entity behaviour and the implementer must enforce all of them as part of the same transaction as the triggering operation:

- **Child mutations re-open a ready return.** Any creation, update, or deletion of an `IncomeDocument`, `Schedule`, or `TaxCredit` belonging to a `TaxReturn` currently in `READY_TO_FILE` reverts the parent return to `DRAFT` and invalidates the computed numbers (`agi_cents`, `taxable_income_cents`, `regular_tax_cents`, `amt_cents`, `total_credits_cents`, and `balance_due_or_refund_cents` are reset to 0). The same applies when the return itself is patched while in `READY_TO_FILE`. The `deduction_method` election remains as the taxpayer last set it.
- **Reject-then-correct re-opens.** When a taxpayer asks to correct a previously rejected return, the return transitions from `REJECTED` back to `DRAFT` and the same computed-field invalidation runs.
- **IRS decisions cascade through filings.** When an `IRSAdjudicator` decides an `EFiling`, the linked `TaxReturn` is transitioned in the same operation — `FILED → ACCEPTED` when the outcome is `ACCEPTED` and `FILED → REJECTED` when the outcome is `REJECTED`. The return's `accepted_at` is set when accepted; the `EFiling`'s `processed_at` is set in both cases.
- **Amendment submission cascades to the original.** When an `AmendedReturn` is submitted, the original `TaxReturn` it references moves from `ACCEPTED` to `AMENDED` in the same transaction. When the amendment is later accepted by an adjudicator, the original return moves on to the terminal state `SUPERSEDED`; when the amendment is rejected, the original return reverts from `AMENDED` back to `ACCEPTED`.
- **Compliance locks cascade through payments.** When an `IRSAdjudicator` places a compliance lock on a taxpayer, every `EstimatedTaxPayment` belonging to that taxpayer that is currently in the `SCHEDULED` state is auto-cancelled in the same operation — its `status` is set to `CANCELLED` and its `cancelled_at` is set to the current virtual clock value.

Every entity mutation, whether triggered directly by a client request or as a downstream consequence of one of the cascades above, refreshes the mutated entity's `updated_at` and increments its `version`. The `version` field on the parent `TaxReturn` is bumped whenever any of its children mutate, which is the serialization point that allows OCC to detect stale compute attempts.

### 2.8. Nested Resource Resolution

Endpoints whose URL embeds more than one identifier — for example, an income-document or credit endpoint nested under a tax return — validate path identifiers in strict left-to-right order. A request whose `tax-returns/{id}` segment does not resolve fails with `ERR_RETURN_NOT_FOUND` before any child lookup is even attempted. Once the parent is known to exist, the child identifier is checked and produces `ERR_RESOURCE_NOT_FOUND` if it does not match. A `Taxpayer` referenced in a path that does not exist produces `ERR_TAXPAYER_NOT_FOUND`.

### 2.9. The Virtual Clock

To make scheduled-payment automation deterministic for tests and for offline scenarios, the system runs against a virtual clock rather than wall time. The clock can be inspected and advanced via two utility endpoints; both roles may call them. Advancing the clock to a supplied future instant — passed as the `to_iso_timestamp` field on the body — atomically runs any deferred transitions whose trigger time has now arrived. The primary deferred transition is the automatic confirmation of an `EstimatedTaxPayment`: when the virtual clock reaches or surpasses 00:00 UTC of the payment's `scheduled_pay_date`, a `SCHEDULED` payment whose owning `Taxpayer` is still `ACTIVE` is transitioned to `CONFIRMED` and `confirmed_at` is stamped with the new clock value. The response of the advance call enumerates every transition that fired, listing the affected entity, its `id`, and the `from`/`to` state pair.

### 2.10. Validation Ordering

A single request can fail against several rules at once, so the order in which validations run determines which `error_id` reaches the caller. The system evaluates checks in the following pinned priority order, returning the first violation encountered:

1. Header presence (`X-User-ID` and `X-User-Role`) → `ERR_AUTH_REQUIRED` (401).
2. Role permitted for the targeted operation → `ERR_FORBIDDEN` (403).
3. Referenced `Taxpayer` exists → `ERR_TAXPAYER_NOT_FOUND` (404).
4. Referenced `TaxReturn` exists → `ERR_RETURN_NOT_FOUND` (404).
5. Referenced child resource — `IncomeDocument`, `Schedule`, `TaxCredit`, `EFiling`, `AmendedReturn`, or `EstimatedTaxPayment` — exists → `ERR_RESOURCE_NOT_FOUND` (404).
6. For any mutating operation, the owning `Taxpayer` is in `account_status` `ACTIVE` → `ERR_TAXPAYER_LOCKED` (409).
7. The target entity is in a state valid for the requested operation (for example, compute requires the return to be in `DRAFT`; e-file requires `READY_TO_FILE`) → `ERR_INVALID_STATE` (409).
8. The original return referenced by an `AmendedReturn` is currently `ACCEPTED` → `ERR_AMENDMENT_NOT_ALLOWED` (409).
9. There is no other active `AmendedReturn` (with `status` in the set `DRAFT`, `SUBMITTED`) already open against the same original return → `ERR_AMENDMENT_ALREADY_OPEN` (409).
10. On a `1099_DIV` income document, `qualified_dividends_cents` does not exceed `ordinary_dividends_cents` → `ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY` (422).
11. On a `1099_B` income document, the `holding_period` is supplied (must be one of `SHORT_TERM` or `LONG_TERM`, not `NONE`) and `cost_basis_cents` does not exceed `proceeds_cents` by more than 100,000,000 cents (the loose sanity ceiling that prevents absurd entries) → `ERR_INCOME_DOC_INVALID` (422).
12. On a `Schedule` of type `A`, the input `itemized_salt_cents` does not exceed 1,000,000 cents (the $10,000 SALT cap on the input itself) → `ERR_SALT_CAP_EXCEEDED` (422).
13. On a `TaxReturn`, the `qualifying_children_under_17` count does not exceed `dependents_count` → `ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS` (422).
14. Claimed credits satisfy their structural eligibility inputs — see §3.6 for the AOTC and EITC ineligibility cases → `ERR_CREDIT_INELIGIBLE` (422).
15. The return does not already carry another `TaxCredit` with the same `credit_type` → `ERR_DUPLICATE_CREDIT` (409).
16. The return does not already carry another `Schedule` with the same `schedule_type` → `ERR_DUPLICATE_SCHEDULE` (409).
17. The scheduled-pay date of a new `EstimatedTaxPayment` is strictly after the current virtual clock value → `ERR_PAYMENT_DATE_PAST` (422).
18. The cancel request on an `EstimatedTaxPayment` is received strictly before its `scheduled_pay_date` → `ERR_PAYMENT_CANNOT_CANCEL` (409).
19. No other non-`DRAFT` `TaxReturn` exists for the same `taxpayer_id` and `tax_year` pair (the prior return's `status` would be one of `READY_TO_FILE`, `FILED`, `ACCEPTED`, `AMENDED`, or `SUPERSEDED`) → `ERR_DUPLICATE_RETURN` (409).
20. The client-supplied `version`, when present, equals the entity's current `version` → `ERR_VERSION_CONFLICT` (409).
21. Required input fields are present, well-formed, and within their supported range — for example `tax_year` falls in the inclusive interval from 2020 through 2025, and `filing_status` is one of the five valid enum values → `ERR_INVALID_INPUT` (422).

This priority order is observable: a request that fails several checks reports only the first one to fire. Implementers must not reorder the checks to optimise short-circuiting — the order is part of the contract.

### 2.11. Audit Logging

Several lifecycle moments cause the server to append an immutable `AuditLog` row. Each row carries the role and identifier of the actor that triggered the event (`actor_role` and `actor_id`), a stable action verb (`action`), the entity type and identifier acted upon (`target_entity` and `target_id`), and a structured `payload` carrying the relevant snapshot. Actions written by the system include, among others, `RETURN_FILED`, `RETURN_ACCEPTED`, `RETURN_REJECTED`, `RETURN_REOPENED`, `RETURN_AMENDED`, `RETURN_SUPERSEDED`, `AMENDMENT_ACCEPTED`, `AMENDMENT_REJECTED`, `COMPLIANCE_LOCK`, and `COMPLIANCE_UNLOCK`. The audit log is read-only and is exposed only to the `IRSAdjudicator` role, filterable by `actor_role`, `action`, `target_entity`, and `target_id`.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Taxpayer and Opening a Return

A taxpayer is brought into the system by a `Taxpayer`-role principal registering themselves, or by an `IRSAdjudicator` registering them on their behalf. Registration captures the taxpayer's `ssn_last4` (exactly four digits — the system never persists the full SSN), their `full_name` as it will appear on the return, the `date_of_birth` in `YYYY-MM-DD` form, and a `filing_address` object with street, city, state, and zip fields. The boolean `is_blind` flag, which has financial consequences for the standard deduction, may be supplied at registration and otherwise defaults to false. Every newly registered taxpayer starts with an `account_status` of `ACTIVE`.

Once a taxpayer exists, they open a return for the year they intend to file. The taxpayer supplies their own `taxpayer_id`, the `tax_year` (any integer in the inclusive range from 2020 through 2025), and a `filing_status` chosen from `SINGLE`, `MARRIED_JOINT`, `MARRIED_SEPARATE`, `HEAD_OF_HOUSEHOLD`, or `QUALIFYING_SURVIVING_SPOUSE`. Optionally they may declare a `dependents_count` and the subset that are `qualifying_children_under_17`; both default to zero, and the qualifying-children count may not exceed the dependents count (rejection with `ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS` when violated). The optional `deduction_method` election is captured at open time, defaulting to `STANDARD` and otherwise set to `ITEMIZED`. A return is born in the `DRAFT` state.

The system permits only one non-`DRAFT` return per `(taxpayer_id, tax_year)` pair. A second attempt to open a return for a year that already has a `READY_TO_FILE`, `FILED`, `ACCEPTED`, `AMENDED`, or `SUPERSEDED` return for the same taxpayer is rejected with `ERR_DUPLICATE_RETURN`. While the original is still `DRAFT`, however, the system tolerates an additional `DRAFT` for the same year so taxpayers can scratch and start over.

### 3.2. Importing Income Documents

The principal way taxes are computed accurately is by importing every payer document the taxpayer received. The system accepts five `doc_type` variants distinguished by IRS form code: `W2` for wage statements, `1099_NEC` for nonemployee compensation, `1099_INT` for interest, `1099_DIV` for dividends, and `1099_B` for brokerage proceeds. Each imported document records the payer's `payer_ein` and `payer_name`, and the moment of import is timestamped on `imported_at`.

Each variant carries a different payload. A `W2` import populates `wages_cents` (box 1) and `federal_withholding_cents` (box 2); the other amount fields default to zero. A `1099_NEC` import sets `nonemployee_comp_cents`. A `1099_INT` import populates `interest_income_cents`. A `1099_DIV` import sets `ordinary_dividends_cents` and `qualified_dividends_cents`, with the firm constraint that the qualified portion never exceeds the ordinary portion — a violation is rejected with `ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY`. A `1099_B` import provides `proceeds_cents`, `cost_basis_cents`, and a `holding_period` of either `SHORT_TERM` or `LONG_TERM`; the placeholder `NONE` is not acceptable as a holding period on a brokerage form, and a brokerage import that omits the holding period or that supplies cost basis greater than proceeds plus 100,000,000 cents is rejected with `ERR_INCOME_DOC_INVALID`. Federal withholding may be present on any 1099 variant that supports it.

Income documents can be corrected after import. A patch on a document carries any of the amount fields and optionally a `version` to assert which generation of the document the client has in hand. Documents can be removed entirely. Whenever a document is created, patched, or deleted on a return whose status is `READY_TO_FILE`, the parent return is automatically reverted to `DRAFT` per §2.7, because the previously-computed numbers are no longer trustworthy.

### 3.3. Schedules: Itemizing, Self-Employment, Capital Gains, and Rentals

Beyond the bare income documents, a return may attach up to one `Schedule` of each IRS schedule type identified by `schedule_type` — `A` for itemized deductions, `B` for interest and dividend summary, `C` for self-employment, `D` for capital gains, or `E` for rentals. A duplicate schedule attempt for a type already present on the return is rejected with `ERR_DUPLICATE_SCHEDULE`.

Schedule A is the input surface for itemized deductions. The taxpayer may declare `itemized_medical_cents`, `itemized_salt_cents`, `itemized_mortgage_interest_cents`, and `itemized_charity_cents`. The system also publishes a computed `total_itemized_deduction_cents` on Schedule A, which reflects the value used in tax computation after the AGI-dependent floors and caps are applied; this field is zero on schedules that are not of type `A`. The system rejects an `itemized_salt_cents` input larger than 1,000,000 cents (the $10,000 statutory SALT input cap) at write time with `ERR_SALT_CAP_EXCEEDED` — note that this is a check on the input itself, separate from the cap that the deduction formula applies internally.

Schedule B is purely computed: `schedule_b_interest_cents` mirrors the sum of `interest_income_cents` across every `1099_INT` document attached to the return, and `schedule_b_dividends_cents` mirrors the sum of `ordinary_dividends_cents` across every `1099_DIV` document. Both are refreshed by the compute step described in §3.5.

Schedule C captures self-employment activity through `schedule_c_gross_receipts_cents` and `schedule_c_expenses_cents`. The computed `schedule_c_net_profit_cents` is the gross receipts minus expenses, floored at zero so a net loss does not subtract from AGI (and so does not produce negative self-employment-tax adjustments).

Schedule D's two computed fields — `schedule_d_short_term_gain_cents` and `schedule_d_long_term_gain_cents` — are populated from the `1099_B` documents attached to the return. The system partitions each brokerage import into its short- or long-term bucket using the `holding_period` discriminator, and sums `proceeds_cents - cost_basis_cents` within each bucket. Both numbers may be negative (a net loss), and the combined Schedule D net gain or loss is one of the inputs to AGI as described in §3.5.

Schedule E captures rental real estate: the taxpayer provides `schedule_e_rental_income_cents` and `schedule_e_rental_expenses_cents`. The Schedule E net used downstream is income minus expenses, floored at zero for AGI purposes (a rental net loss does not depress AGI in this simplified model).

Schedules can be patched in place. As with income documents, any creation or patch on a `Schedule` belonging to a return in `READY_TO_FILE` reverts the parent to `DRAFT` per §2.7.

### 3.4. Claiming Credits

A taxpayer claims a credit by attaching a `TaxCredit` row to their return. The supported `credit_type` values are `EITC` (Earned Income Tax Credit), `CTC` (Child Tax Credit), and `AOTC` (American Opportunity Tax Credit). The taxpayer expresses what they are asking for via `requested_amount_cents`; the server treats this as an input and computes its own answer at compute time, never trusting the requested figure as authoritative. AOTC specifically requires two additional inputs — `aotc_student_count` (must be at least 1 to claim AOTC) and `aotc_qualified_expenses_cents` (must be strictly positive). For non-AOTC credits both fields default to zero.

Two structural eligibility checks fire at credit creation time. AOTC requires a non-zero student count and positive qualified expenses; a violation is rejected with `ERR_CREDIT_INELIGIBLE`. A return whose `filing_status` is `MARRIED_SEPARATE` cannot claim either `EITC` or `AOTC`, and an attempt to do so is also rejected with `ERR_CREDIT_INELIGIBLE`. Two credits of the same `credit_type` on the same return are blocked with `ERR_DUPLICATE_CREDIT`.

Until the return is computed, every `TaxCredit` row sits in `eligibility_status` `PENDING` with `approved_amount_cents` and `refundable_portion_cents` of zero and `ineligibility_reason` of null. Computing the return — see §3.5 and §3.6 — sets `eligibility_status` to either `ELIGIBLE` (with a computed approved amount and refundable portion) or `INELIGIBLE` (with a short `ineligibility_reason` explaining why and zeros for the amounts). A credit can be removed from the return entirely, which reverts the parent return to `DRAFT` if it had reached `READY_TO_FILE`.

### 3.5. Computing the Return: AGI, Deductions, Regular Tax, AMT

The compute operation is the heart of the system. A `Taxpayer` triggers it on a return that is in `DRAFT`; the return advances to `READY_TO_FILE`. Compute may itself accept an optional `version` for OCC. Before any arithmetic runs the system verifies several preconditions: the owning `Taxpayer` must be in `account_status` `ACTIVE` (a locked taxpayer is rejected with `ERR_TAXPAYER_LOCKED`); the return's `filing_status` must be set; the return must have at least one `IncomeDocument` attached, with the single exception that a return whose `deduction_method` is `STANDARD` and whose income is zero may compute with no income documents attached at all; every `Schedule` of type `A` on the return must satisfy the SALT input cap (`itemized_salt_cents` at or below 1,000,000 cents); and every `1099_DIV` income document must satisfy the qualified-dividends-cannot-exceed-ordinary rule. Once the preconditions pass, the operation is a sequence of pinned steps and the system must execute them in the order described below, because each step's output is the next step's input and the rounding rules of later steps depend on earlier integer outcomes.

**Step 1 — Adjusted Gross Income.** The system first totals raw income across all imported documents on the return: `total_income_cents` is the sum of `wages_cents` across every `W2`, plus `nonemployee_comp_cents` across every `1099_NEC`, plus `interest_income_cents` across every `1099_INT`, plus `ordinary_dividends_cents` across every `1099_DIV`. To this it adds the Schedule C net (gross receipts minus expenses on every Schedule C, summed and floored at zero), the Schedule E net (rental income minus rental expenses on every Schedule E, summed and floored at zero), and the combined Schedule D capital-gains net (short-term gain plus long-term gain), with the capital-gains contribution floored at negative 300,000 cents so a net capital loss is deductible against ordinary income up to a $3,000 ceiling and no further. This sum is the value stored on `total_income_cents`. The system then computes the deductible half of self-employment tax: it multiplies the Schedule C net by 9235 basis points and divides by 10,000 using integer floor division, then multiplies the result by 1530 basis points and again divides by 10,000 with floor division, producing the SE tax in integer cents; the deductible half is the SE tax divided by 2 using integer floor division. `agi_cents` is `total_income_cents` minus this half-SE adjustment.

**Step 2 — Taxable income.** The taxable income depends on the elected `deduction_method`. When the method is `STANDARD`, the system looks up the standard deduction from a filing-status table — 1,500,000 cents for `SINGLE` or `MARRIED_SEPARATE`, 3,000,000 cents for `MARRIED_JOINT` or `QUALIFYING_SURVIVING_SPOUSE`, and 2,225,000 cents for `HEAD_OF_HOUSEHOLD` — and adds a flat 150,000 cents (the blind add-on) when the taxpayer's `is_blind` flag is true. When the method is `ITEMIZED`, the system reads the Schedule A row attached to the return and applies, in this pinned order, a medical floor (multiply `agi_cents` by 750 basis points, divide by 10,000 using floor division, subtract the result from `itemized_medical_cents`, floor at zero), a SALT cap of 1,000,000 cents on `itemized_salt_cents`, no cap on `itemized_mortgage_interest_cents`, and a charity cap computed as 60 percent of `agi_cents` using integer floor division applied against `itemized_charity_cents`. The four allowed amounts are summed to form the itemized deduction. Whichever method is in effect, the deduction is subtracted from `agi_cents` and the result is floored at zero. That value is `taxable_income_cents`. The computed itemized total is also written back into `total_itemized_deduction_cents` on the Schedule A row.

**Step 3 — Regular tax.** The regular tax is the sum of the per-bracket tax slices over the appropriate progressive table. For filing statuses `SINGLE`, `MARRIED_SEPARATE`, and `HEAD_OF_HOUSEHOLD`, the system uses a single-style table: 10 percent (1000 basis points) on the slice from 0 up to 1,100,000 cents, 12 percent (1200 basis points) from 1,100,000 to 4,475,000, 22 percent (2200 basis points) from 4,475,000 to 9,537,500, 24 percent (2400 basis points) from 9,537,500 to 18,222,500, and 32 percent (3200 basis points) above 18,222,500. For filing statuses `MARRIED_JOINT` and `QUALIFYING_SURVIVING_SPOUSE`, the system uses a married-joint table: 10 percent up to 2,200,000 cents, 12 percent up to 8,950,000, 22 percent up to 19,075,000, and 24 percent above 19,075,000. For each bracket the system computes the slice (the portion of taxable income that falls inside that bracket's lower-to-upper window), multiplies the slice by the bracket's basis-point rate, divides by 10,000 using integer floor division, and accumulates that per-bracket integer into a running total. The order is pinned: floor each bracket's slice tax separately, then sum — never sum across brackets first and then floor. The final accumulator is stored as `regular_tax_cents`.

**Step 4 — Alternative Minimum Tax.** The system runs a parallel simplified AMT computation. The AMT income is taken to equal `agi_cents` in this simplified model (no preference adjustments). The exemption is looked up by filing status — 8,550,000 cents for `SINGLE` or `HEAD_OF_HOUSEHOLD`, 13,325,000 cents for `MARRIED_JOINT` or `QUALIFYING_SURVIVING_SPOUSE`, and 6,662,500 cents for `MARRIED_SEPARATE` — and subtracted from AMTI, with the result floored at zero to give the AMT base. The system then taxes the AMT base in two tiers: the slice from 0 up to and including 23,222,500 cents is taxed at 2600 basis points and the slice above 23,222,500 is taxed at 2800 basis points; each tier's tax is computed by multiplying its slice by the basis-point rate and dividing by 10,000 with floor division, and the two tier results are summed to give the tentative AMT. `amt_cents` is the tentative AMT minus `regular_tax_cents`, floored at zero — so when the regular tax already exceeds the tentative AMT the AMT add-on is exactly zero. The final tax used downstream in the credit waterfall is `regular_tax_cents + amt_cents`.

After Step 4 the system runs the credit waterfall described in §3.6, the balance reconciliation described in §3.7, and refreshes the Schedule B and Schedule D aggregates. The return then occupies `READY_TO_FILE`.

### 3.6. The Credit Waterfall

The credit pipeline runs as the final calculation step before balance reconciliation and is a strictly pinned three-stage waterfall: phase out and cap each individual credit, split each credit into a non-refundable and a refundable portion, and then apply the pool — non-refundable first against the final tax (clamped at zero, so excess non-refundable simply evaporates and does not become a refund), refundable afterward (which can drive the net tax negative and thus produce a refund).

**Per-credit phase-out and cap — CTC.** The Child Tax Credit's gross amount is `qualifying_children_under_17` multiplied by 200,000 cents (the $2,000 per child base). The phase-out threshold depends on filing status: 20,000,000 cents (an AGI of $200,000) for `SINGLE`, `MARRIED_SEPARATE`, and `HEAD_OF_HOUSEHOLD`, and 40,000,000 cents (an AGI of $400,000) for `MARRIED_JOINT` and `QUALIFYING_SURVIVING_SPOUSE`. The system computes the excess of `agi_cents` over the threshold, floored at zero, and rounds that excess up to the next multiple of 100,000 cents (the $1,000 step) by adding 99,999 and integer-dividing by 100,000 and then multiplying by 100,000 again. It then multiplies that rounded-up excess by 500 basis points and divides by 10,000 using floor division to produce the phase-out reduction. The CTC total is the gross amount minus the phase-out reduction, floored at zero. The refundable portion is the lesser of the CTC total and `qualifying_children_under_17 * 170,000` (the $1,700 per child refundable cap); the rest is non-refundable.

**Per-credit phase-out and cap — AOTC.** The American Opportunity Tax Credit is unavailable when `filing_status` is `MARRIED_SEPARATE` or when `aotc_student_count` is zero — both cases produce a total of zero. Otherwise the system computes a per-student qualified-expenses figure: divide `aotc_qualified_expenses_cents` by `aotc_student_count` and cap at 400,000 cents (the $4,000 ceiling per student). If that per-student amount is no more than 200,000 cents, the raw per-student credit equals the per-student amount itself; otherwise the raw per-student credit is 200,000 cents plus 25 percent (2500 basis points, divided by 10,000 with floor division) of the portion above 200,000 cents. The gross AOTC is the raw per-student credit multiplied by `aotc_student_count`. A linear phase-out then applies: the start of the phase-out range is 8,000,000 cents of AGI for `SINGLE` and `HEAD_OF_HOUSEHOLD`, 16,000,000 cents for `MARRIED_JOINT` and `QUALIFYING_SURVIVING_SPOUSE`, and effectively zero for `MARRIED_SEPARATE` (which is already ineligible). The width of the range is 1,000,000 cents for `SINGLE` and `HEAD_OF_HOUSEHOLD`, 2,000,000 cents for `MARRIED_JOINT` and `QUALIFYING_SURVIVING_SPOUSE`, and zero for `MARRIED_SEPARATE` (ineligible). When the excess of AGI over the start is at least the width, the AOTC total is zero; when the width is zero, the AOTC total is likewise zero; otherwise the system retains a fraction of the gross equal to 10,000 minus the excess multiplied by 10,000 and integer-floor-divided by the width — that retained basis-point value is then multiplied by the gross and floor-divided by 10,000 to give the AOTC total. The refundable portion is 40 percent of the AOTC total (multiply by 40, integer-floor-divide by 100); the rest is non-refundable.

**Per-credit phase-out and cap — EITC.** The Earned Income Tax Credit is zero when `filing_status` is `MARRIED_SEPARATE`. Otherwise the system clamps the number of qualifying children to 3 (any value at or above 3 uses the 3-child row of the simplified table). The maximum credit by clamp value is 60,000 cents for zero children, 400,000 cents for one, 660,000 cents for two, and 740,000 cents for three or more. The phase-out start is 1,000,000 cents of AGI for zero children and 2,200,000 cents for one, two, or three; the phase-out end is 1,882,000 cents for zero children, 4,949,000 for one, 5,535,000 for two, and 5,907,000 for three. When `agi_cents` is at or below the start, the EITC equals the maximum for the applicable clamp. When it is at or above the end, the EITC is zero. Between the two, the system retains a fraction equal to 10,000 minus the AGI excess over the start multiplied by 10,000 and integer-floor-divided by the phase-out width (end minus start); that retained basis-point value is then multiplied by the maximum and floor-divided by 10,000 to give the EITC total. The full EITC is refundable.

**Apply the pool.** Each `TaxCredit` row records its own `approved_amount_cents` (the total approved for that credit after phase-out and cap) and its own `refundable_portion_cents`. The system sums the non-refundable portions across every approved credit on the return to form the non-refundable pool, sums the refundable portions to form the refundable pool, and applies them as the pinned waterfall. The non-refundable pool reduces the final tax (`regular_tax_cents + amt_cents`) down to a floor of zero — any excess simply evaporates; the refundable pool is then subtracted from whatever remains (typically zero) to compute the net tax that feeds the balance reconciliation. The `total_credits_cents` field on the return is the sum of every approved credit's approved amount on the return — refundable and non-refundable combined.

Any credit that does not pass its eligibility rules at compute time records its `eligibility_status` as `INELIGIBLE` and writes a short explanation into `ineligibility_reason`; the corresponding `approved_amount_cents` and `refundable_portion_cents` are zero, and the row contributes nothing to the pools.

### 3.7. Balance Due or Refund

After the credits have been applied, the system reconciles the final balance. It first totals `total_withholding_cents` as the sum of `federal_withholding_cents` across every `IncomeDocument` attached to the return. It then totals `estimated_payments_applied_cents` as the sum of `amount_cents` across every `EstimatedTaxPayment` belonging to the same taxpayer and tax year whose `status` is `CONFIRMED`. The payments total is the sum of these two. The net tax is the residual after the credit waterfall — the final tax reduced by the non-refundable pool (clamped at zero) and then reduced by the refundable pool (allowed to go negative). `balance_due_or_refund_cents` is the payments total minus the net tax; a positive value is a refund owed to the taxpayer, and a negative value is a balance due to the IRS.

### 3.8. Electronic Filing and IRS Adjudication

Once a return is in `READY_TO_FILE`, the taxpayer submits it electronically. The submission is rejected with `ERR_INVALID_STATE` if the return is not in `READY_TO_FILE` or if any `TaxCredit` on the return still shows `eligibility_status` `PENDING` — every claimed credit must have been evaluated by a prior compute call. A locked taxpayer is rejected with `ERR_TAXPAYER_LOCKED`. The submission creates a new `EFiling` record carrying its `tax_return_id`, a system-minted `submission_id`, an `outcome` of `PENDING`, a `filed_at` timestamp set to the current virtual clock value, and a null `processed_at`. The owning return moves from `READY_TO_FILE` to `FILED`, its own `filed_at` is set to the clock value, and an `AuditLog` row with `action` `RETURN_FILED` is appended. If two clients race the e-file endpoint on the same return, exactly one wins the `READY_TO_FILE → FILED` transition; the loser sees the state already past `READY_TO_FILE` and is rejected with `ERR_INVALID_STATE`.

The IRS side of the workflow is the adjudication endpoint. Only an `IRSAdjudicator` may decide a filing, and only while the `EFiling`'s `outcome` is `PENDING`. The decision payload carries an `outcome` of `ACCEPTED` or `REJECTED`. An accept decision sets the filing's `outcome` to `ACCEPTED` and stamps `processed_at` with the current clock; in the same operation it cascades the linked `TaxReturn` from `FILED` to `ACCEPTED`, stamps the return's `accepted_at`, and appends an `AuditLog` row with `action` `RETURN_ACCEPTED`. A reject decision requires a `rejection_code` (and optionally a `rejection_message`) and sets the filing's `outcome` to `REJECTED`, stamps `processed_at`, cascades the return from `FILED` to `REJECTED`, and appends a `RETURN_REJECTED` audit row.

When a return has been rejected by the IRS, the taxpayer is permitted to reopen it for correction. The reopen operation requires that the return is currently in `REJECTED` and that the most recent `EFiling` for that return has an `outcome` of `REJECTED`; on success the return moves from `REJECTED` back to `DRAFT`, the computed numbers are invalidated per §2.7, and a `RETURN_REOPENED` audit row is appended. From there the normal compute-and-file cycle can begin again.

### 3.9. Amending an Accepted Return

A 1040X amendment is the corrective workflow once the IRS has accepted a return. The taxpayer creates an `AmendedReturn` by supplying the `original_return_id` (which must reference a `TaxReturn` currently in `ACCEPTED` — otherwise `ERR_AMENDMENT_NOT_ALLOWED`) and a non-empty `reason_summary` explaining what is being corrected. They may also supply restated input values: `restated_filing_status`, `restated_dependents_count`, `restated_qualifying_children_under_17`, and `restated_deduction_method`. The amendment's `form_code` is fixed at the literal string `"1040X"` by the system and is not taxpayer-controllable. The amendment is born in `DRAFT` with a null `submitted_at`, null `restated_return_snapshot`, and zeroes for `delta_agi_cents`, `delta_tax_cents`, and `delta_balance_due_or_refund_cents`.

Only one active amendment is permitted per original return: a second creation or submission attempt while another `AmendedReturn` with `status` `DRAFT` or `SUBMITTED` already references the same original is rejected with `ERR_AMENDMENT_ALREADY_OPEN`. This same error also serializes two concurrent submissions on the same original return — the first submission wins the `ACCEPTED → AMENDED` transition on the original and the second loses with `ERR_AMENDMENT_ALREADY_OPEN`.

Submitting an amendment from `DRAFT` to `SUBMITTED` re-runs the entire compute pipeline (AGI, taxable income, regular tax, AMT, credits, balance) against the amendment's restated inputs. The submission step requires that at least one restated field actually differs from the original snapshot; otherwise it is rejected with `ERR_INVALID_STATE`. The system stamps the amendment's `submitted_at` with the current clock, populates `restated_return_snapshot` with the freshly computed numbers, and computes the three delta fields: `delta_agi_cents` is the restated AGI minus the original AGI (signed; may be negative); `delta_tax_cents` is the restated final tax minus total credits, minus the original final tax minus its total credits (so a positive delta means more tax was owed after restatement); and `delta_balance_due_or_refund_cents` is the restated balance-due-or-refund minus the original balance-due-or-refund (positive means the taxpayer is owed more refund than originally settled, negative means they owe more). Because the original return's withholding and confirmed estimated payments are the same on both sides of the comparison, the balance delta is also the negative of the tax delta change adjusted for credits. Submission additionally cascades the original `TaxReturn` from `ACCEPTED` to `AMENDED` in the same operation and appends a `RETURN_AMENDED` audit row.

The IRS then decides the amendment via the same adjudication shape as for filings. An accept decision requires the amendment is currently `SUBMITTED`; it transitions the amendment to its terminal `ACCEPTED` state, cascades the original return from `AMENDED` to the terminal state `SUPERSEDED`, and appends an `AMENDMENT_ACCEPTED` audit row (and a `RETURN_SUPERSEDED` row for the original). A reject decision likewise requires `SUBMITTED` status and a `rejection_message`; it transitions the amendment to its terminal `REJECTED` state, reverts the original return from `AMENDED` back to `ACCEPTED` (so the taxpayer's previously accepted filing is restored), and appends an `AMENDMENT_REJECTED` audit row.

### 3.10. Quarterly Estimated Payments and the Safe-Harbor Advisory

A taxpayer schedules a quarterly estimated payment by attaching a payment to themselves (not to a specific return — payments live at the taxpayer level and apply to whichever return shares the year). The scheduling request carries the `taxpayer_id`, the `tax_year` the payment applies to, the `quarter` (one of `Q1`, `Q2`, `Q3`, or `Q4`), an `amount_cents` greater than zero, and a `scheduled_pay_date` in `YYYY-MM-DD` form. The pay date must be strictly after the current virtual clock value at creation time; a same-day or past pay date is rejected with `ERR_PAYMENT_DATE_PAST`. The payment is born in `SCHEDULED` with null `confirmed_at` and null `cancelled_at`.

A taxpayer may cancel a `SCHEDULED` payment before its pay date. The cancel operation requires that the current virtual clock is strictly less than the `scheduled_pay_date`; once the clock reaches 00:00 UTC of the pay date, cancel is no longer possible and the request is rejected with `ERR_PAYMENT_CANNOT_CANCEL`. A successful cancel transitions the payment to `CANCELLED` and stamps `cancelled_at` with the current clock. When the virtual clock is advanced past a payment's `scheduled_pay_date`, the system automatically transitions every `SCHEDULED` payment whose pay date has been reached to `CONFIRMED` (provided the owning taxpayer is `ACTIVE`) and stamps each one's `confirmed_at`. The race between an immediate cancel attempt and a clock-driven confirmation on the pay date itself is serialized first-writer-wins on the payment's `SCHEDULED → {CONFIRMED, CANCELLED}` transition; the loser receives `ERR_INVALID_STATE`. Confirmed payments are summed into `estimated_payments_applied_cents` on a matching return the next time that return is computed.

The system also exposes a safe-harbor advisory for taxpayers worried about underpayment penalties. The advisory computes the current-year final tax (`regular_tax_cents + amt_cents` on the current return) and the payments made so far (`total_withholding_cents + estimated_payments_applied_cents`), then compares the payments against two thresholds: the current-year threshold, computed as the current-year final tax multiplied by 90 percent with ceiling rounding (so the threshold is the smallest integer that is at least 90 percent of the current tax); and the prior-year threshold, computed by looking up the prior-year `TaxReturn` for the same taxpayer (specifically a return whose status is one of `ACCEPTED` or `SUPERSEDED` for `tax_year` equal to the current year minus 1) and taking either 110 percent of its final tax (with ceiling rounding) if the current `agi_cents` exceeds 15,000,000 cents (the $150,000 high-income threshold) or 100 percent of its final tax (with ceiling rounding) otherwise. When no prior-year accepted or superseded return exists, the prior threshold is treated as unreachable. The advisory reports `safe_harbor_met` as true if the payments meet or exceed either threshold, alongside the inputs (`current_tax_cents`, `payments_made_cents`, `threshold_current_cents`, `prior_threshold_cents`) that produced the verdict.

### 3.11. Compliance Locks

An `IRSAdjudicator` can place a compliance lock on a taxpayer they have reason to investigate. The lock transitions the taxpayer's `account_status` from `ACTIVE` to `LOCKED`. While locked, every mutating endpoint operating on resources owned by that taxpayer — including creating or editing returns, importing documents, editing schedules, claiming or removing credits, scheduling new estimated payments, computing, e-filing, and submitting amendments — is rejected with `ERR_TAXPAYER_LOCKED`. Returns that the taxpayer had in `DRAFT` remain in `DRAFT` but cannot advance to `READY_TO_FILE` while the lock is in place. In the same operation the lock places, every `EstimatedTaxPayment` belonging to the taxpayer that is currently `SCHEDULED` is cascaded to `CANCELLED` with `cancelled_at` set to the current clock, so the locked taxpayer's future-dated payments do not silently confirm while the investigation proceeds. The system appends an `AuditLog` row with `action` `COMPLIANCE_LOCK`. An `IRSAdjudicator` may pass an optional `reason` string on the lock request; the string is recorded in the audit row's `payload` for the lock event. An adjudicator releases the lock by transitioning the taxpayer from `LOCKED` back to `ACTIVE`, which appends a `COMPLIANCE_UNLOCK` audit row.

## 4. Endpoint Definitions

Operations that create a new resource (registering a taxpayer, opening a return, importing an income document, attaching a schedule, claiming a credit, scheduling a payment, opening an amendment, e-filing) return a `201 Created` status code. Operations that modify an existing resource — including patches, state transitions, adjudication decisions, compliance locks, and amendment/submit/decide — return a `200 OK`. Deletes return `204 No Content`.

| Method | Path                                                  | Description                                                                                                       | Authorized Role(s)             |
| ------ | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| POST   | `/taxpayers`                                          | Register a new taxpayer                                                                                           | Taxpayer, IRSAdjudicator       |
| GET    | `/taxpayers/{id}`                                     | Retrieve a taxpayer (Taxpayer: self only; IRSAdjudicator: any)                                                    | Taxpayer, IRSAdjudicator       |
| POST   | `/taxpayers/{id}/compliance-lock`                     | Place a compliance hold on a taxpayer                                                                             | IRSAdjudicator                 |
| POST   | `/taxpayers/{id}/compliance-unlock`                   | Release a compliance hold                                                                                         | IRSAdjudicator                 |
| POST   | `/tax-returns`                                        | Create a new tax return in DRAFT                                                                                  | Taxpayer                       |
| GET    | `/tax-returns`                                        | List tax returns (filter by `taxpayer_id`, `tax_year`, `status`; paginated)                                       | Taxpayer, IRSAdjudicator       |
| GET    | `/tax-returns/{id}`                                   | Retrieve a tax return                                                                                             | Taxpayer, IRSAdjudicator       |
| PATCH  | `/tax-returns/{id}`                                   | Update mutable inputs on a return                                                                                 | Taxpayer                       |
| POST   | `/tax-returns/{id}/compute`                           | Compute AGI, taxable income, regular tax, AMT, credits, and balance; advances DRAFT to READY_TO_FILE              | Taxpayer                       |
| POST   | `/tax-returns/{id}/efile`                             | Electronically file a READY_TO_FILE return                                                                        | Taxpayer                       |
| POST   | `/tax-returns/{id}/unlock-for-correction`             | Re-open a REJECTED return back to DRAFT                                                                           | Taxpayer                       |
| GET    | `/tax-returns/{id}/safe-harbor`                       | Compute the IRS safe-harbor advisory                                                                              | Taxpayer                       |
| POST   | `/tax-returns/{id}/income-documents`                  | Import a W-2/1099-NEC/INT/DIV/B document onto the return                                                          | Taxpayer                       |
| GET    | `/tax-returns/{id}/income-documents`                  | List imported income documents (filter by `doc_type`; paginated)                                                  | Taxpayer, IRSAdjudicator       |
| PATCH  | `/income-documents/{id}`                              | Correct a previously imported document                                                                            | Taxpayer                       |
| DELETE | `/income-documents/{id}`                              | Remove an imported document                                                                                       | Taxpayer                       |
| POST   | `/tax-returns/{id}/schedules`                         | Attach a Schedule (A/B/C/D/E) to the return                                                                       | Taxpayer                       |
| GET    | `/tax-returns/{id}/schedules`                         | List schedules on a return                                                                                        | Taxpayer, IRSAdjudicator       |
| PATCH  | `/schedules/{id}`                                     | Update a schedule's inputs                                                                                        | Taxpayer                       |
| POST   | `/tax-returns/{id}/credits`                           | Claim a credit (EITC/CTC/AOTC); eligibility is evaluated on compute                                               | Taxpayer                       |
| GET    | `/tax-returns/{id}/credits`                           | List credits on a return                                                                                          | Taxpayer, IRSAdjudicator       |
| DELETE | `/credits/{id}`                                       | Remove a claimed credit                                                                                           | Taxpayer                       |
| GET    | `/efilings/{id}`                                      | Retrieve a filing record                                                                                          | Taxpayer, IRSAdjudicator       |
| POST   | `/efilings/{id}/decide`                               | IRS decides on a filing (ACCEPTED or REJECTED)                                                                    | IRSAdjudicator                 |
| POST   | `/amendments`                                         | Create a 1040X amendment pointing at an ACCEPTED original return                                                  | Taxpayer                       |
| GET    | `/amendments/{id}`                                    | Retrieve an amendment                                                                                             | Taxpayer, IRSAdjudicator       |
| POST   | `/amendments/{id}/submit`                             | Submit the amendment (DRAFT → SUBMITTED); cascades the original return ACCEPTED → AMENDED and computes deltas     | Taxpayer                       |
| POST   | `/amendments/{id}/decide`                             | IRS decides on an amendment (ACCEPTED or REJECTED)                                                                | IRSAdjudicator                 |
| POST   | `/estimated-payments`                                 | Schedule a quarterly estimated tax payment                                                                        | Taxpayer                       |
| GET    | `/estimated-payments`                                 | List estimated payments (filter by `taxpayer_id`, `tax_year`, `quarter`, `status`; paginated)                     | Taxpayer, IRSAdjudicator       |
| POST   | `/estimated-payments/{id}/cancel`                     | Cancel a SCHEDULED payment before its pay-date                                                                    | Taxpayer                       |
| GET    | `/audit-logs`                                         | List audit events (filter by `actor_role`, `action`, `target_entity`, `target_id`; paginated)                     | IRSAdjudicator                 |
| POST   | `/_clock/advance`                                     | Advance the virtual clock and run any automatic transitions whose trigger time has arrived                        | Taxpayer, IRSAdjudicator       |
| GET    | `/_clock`                                             | Read the current virtual clock                                                                                    | Taxpayer, IRSAdjudicator       |

## 5. Error Code Catalogue

| Error ID                                  | HTTP Status Code |
| ----------------------------------------- | ---------------- |
| `ERR_AUTH_REQUIRED`                       | 401 Unauthorized |
| `ERR_FORBIDDEN`                           | 403 Forbidden    |
| `ERR_TAXPAYER_NOT_FOUND`                  | 404 Not Found    |
| `ERR_RETURN_NOT_FOUND`                    | 404 Not Found    |
| `ERR_RESOURCE_NOT_FOUND`                  | 404 Not Found    |
| `ERR_TAXPAYER_LOCKED`                     | 409 Conflict     |
| `ERR_INVALID_STATE`                       | 409 Conflict     |
| `ERR_AMENDMENT_NOT_ALLOWED`               | 409 Conflict     |
| `ERR_AMENDMENT_ALREADY_OPEN`              | 409 Conflict     |
| `ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY`      | 422 Unprocessable Entity |
| `ERR_INCOME_DOC_INVALID`                  | 422 Unprocessable Entity |
| `ERR_SALT_CAP_EXCEEDED`                   | 422 Unprocessable Entity |
| `ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS` | 422 Unprocessable Entity |
| `ERR_CREDIT_INELIGIBLE`                   | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CREDIT`                    | 409 Conflict     |
| `ERR_DUPLICATE_SCHEDULE`                  | 409 Conflict     |
| `ERR_DUPLICATE_RETURN`                    | 409 Conflict     |
| `ERR_PAYMENT_DATE_PAST`                   | 422 Unprocessable Entity |
| `ERR_PAYMENT_CANNOT_CANCEL`               | 409 Conflict     |
| `ERR_VERSION_CONFLICT`                    | 409 Conflict     |
| `ERR_INVALID_INPUT`                       | 422 Unprocessable Entity |
