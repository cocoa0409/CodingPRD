# Pharmacy Claim Adjudication API — Product Requirements Document

## 1. Introduction

Pharmacy benefit managers sit at the intersection of clinical policy and financial settlement: every time a pharmacist fills a prescription, the PBM must decide — in real time, at the point of sale — whether the member is eligible, whether the drug is covered and under what utilization-management restrictions, how much the member owes after deductible and out-of-pocket accumulation, how much any manufacturer copay card contributes, and how much the plan will pay the dispensing pharmacy. This document specifies an API that performs that adjudication end to end, from benefit configuration through claim submission, reversal, and reprocessing, to retrospective pharmacy audit with clawback settlement.

The system is built around five peer roles. A PBM operations administrator configures plans, drugs, formulary entries, network pharmacies, and member enrollments. Pharmacists submit and manage claims on behalf of their own pharmacy and may dispute audits directed at it. Members request prior authorizations for themselves. Clinical reviewers decide those authorizations. Auditors open pharmacy audits, record findings, and close them with clawback computation. Throughout, the platform enforces a pinned adjudication pipeline whose edit order is observable in rejection responses, dual copay-assistance variants (accumulator versus maximizer) with materially different member-cost outcomes, drug utilization review screening with pharmacist override codes, and an automatic pharmacy debt-suspension regime driven by a per-pharmacy ledger.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The recognized roles are `PbmAdmin`, `Pharmacist`, `Member`, `ClinicalReviewer`, and `Auditor`, spelled exactly so. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Pharmacist`, `X-User-ID` is the `id` of the acting `Pharmacy`; ownership checks on any resource that references a pharmacy compare that resource's pharmacy foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_PHARMACY_MISMATCH` (HTTP 403). A `Pharmacist` header value that matches no registered pharmacy at all is treated as an unresolvable reference and rejected with `ERR_PHARMACY_NOT_FOUND` (HTTP 404). When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; a member requesting a prior authorization must pass their own `id` as the payload's `member_id`, and member reads of member or claim resources are checked against `X-User-ID`, with violations rejected as `ERR_MEMBER_MISMATCH` (HTTP 403).

The remaining three roles are opaque. When `X-User-Role` is `PbmAdmin`, `ClinicalReviewer`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `decided_by` on a prior authorization when a `ClinicalReviewer` approves or denies it — but it never compares the value to any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of returned items; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. A non-numeric or unparseable `limit` or `offset` is not an error: it silently falls back to its default (10 or 0), and out-of-range values are clamped into range rather than rejected. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. Common Resource Properties and Mutation Semantics

All primary resources — plans, drugs, formulary entries, pharmacies, members, prior authorizations, claims, and pharmacy audits — share a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix of any kind.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments by one on every mutation.

Any change to a resource — including system-driven changes such as cascade transitions and recomputed derived fields — is a mutation and therefore refreshes `updated_at` and increments `version`. DUR alert records are the deliberate exception: a DUR alert is an append-only screening record carrying only `id` and `created_at`; both `updated_at` and `version` are absent from it.

The consistency model is immediate: every mutation and every derived-field update caused by a request is fully applied and visible in that request's response. There are no eventually-consistent reads.

### 2.5. Money, Cents, and Rounding Discipline

All monetary values in the API are integer cents — plan deductibles, out-of-pocket maximums, copays, card balances, claim financials, pharmacy ledger balances, and audit clawbacks alike. Rounding is permitted at exactly two places. The first is the percentage-coinsurance step of claim pricing, where the tier copay base is computed from a percentage of the allowed amount and rounded up (ceiling) to the next whole cent — any fractional cent rounds up, so a product of 2020.2 cents becomes 2021 — before anything downstream consumes it. The second is extrapolated audit clawback, where each finding's extrapolated amount is individually rounded half-up to whole cents before the per-claim amounts are summed; summing first and rounding once is expressly forbidden. All other arithmetic on money is exact integer arithmetic with no rounding.

### 2.6. The Request Validation Pipeline and Its Fixed Ordering

Every request is screened against a fixed pipeline, and a request failing at any stage is rejected with that stage's error — later stages are never consulted for that request. The stages, in order, are:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is known, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization** — the role appears in the endpoint's authorized role list, else `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Entity-backed ownership** — a `Pharmacist` caller must own the target claim or audit (`ERR_PHARMACY_MISMATCH`, HTTP 403); a `Member` caller must be the member acted upon on prior-authorization creation and on member-scoped member and claim reads (`ERR_MEMBER_MISMATCH`, HTTP 403).
4. **Existence** — path identifiers, then body foreign keys, must resolve to existing rows, evaluated left to right across plans, drugs, members, pharmacies, claims, prior authorizations, audits, and formulary entries, each producing its specific 404 error; a `Pharmacist` `X-User-ID` matching no pharmacy fails here as `ERR_PHARMACY_NOT_FOUND`.
5. **State preconditions** — each stateful action verifies the source state of its state machine, and each failure maps to its specific 409 error (for example, reversing a claim that is not `PAID` yields `ERR_CLAIM_NOT_PAID`; a claim write from a `SUSPENDED` pharmacy yields `ERR_PHARMACY_SUSPENDED`).
6. **Optimistic concurrency** — the one OCC-guarded write in the system is checked here, with a stale expectation rejected as `ERR_STALE_VERSION` (HTTP 412); see §2.9.
7. **Request shape** — required fields are present, integers parse, enumerations are valid, quantities and day supplies are positive, dates are valid ISO dates with start not after end, and structure-conditional fields are present exactly when required; violations yield `ERR_INVALID_REQUEST` (HTTP 400).
8. **Uniqueness** — `ndc`, `external_ref`, and `ncpdp_id` uniqueness violations yield `ERR_INVALID_REQUEST` (HTTP 400); a duplicate formulary pairing yields `ERR_DUPLICATE_FORMULARY_ENTRY` (HTTP 409) and a duplicate active prior authorization yields `ERR_DUPLICATE_ACTIVE_PA` (HTTP 409).
9. **Domain temporal rules** — the audit-window overlap rule lives here, yielding `ERR_AUDIT_WINDOW_OVERLAP` (HTTP 422).
10. **Domain referential rules** — the audit-findings admissibility rule lives here, yielding `ERR_CLAIM_NOT_AUDITABLE` (HTTP 422).

Only after all ten general stages pass do claim-adjudication requests enter the eleven pinned adjudication edits described in §3.4, which are themselves evaluated in a fixed sequence and reject with HTTP 422. Within stage 5, paired checks also have a pinned internal order: plan activation checks the `DRAFT` state before it counts formulary entries (so a non-draft plan surfaces `ERR_PLAN_INVALID_STATE` rather than `ERR_PLAN_NO_FORMULARY_ENTRIES`), pharmacy reinstatement checks the `SUSPENDED` state before it examines the balance (so a non-suspended pharmacy surfaces `ERR_PHARMACY_NOT_SUSPENDED` rather than `ERR_PHARMACY_DEBT_OUTSTANDING`), and the three claim lifecycle actions each check the claim's source state before the dispensing pharmacy's suspension (so resubmitting a non-`REJECTED` claim from a suspended pharmacy surfaces `ERR_CLAIM_NOT_REJECTED`, reversing a non-`PAID` claim surfaces `ERR_CLAIM_NOT_PAID`, and reprocessing a non-`REVERSED` claim surfaces `ERR_CLAIM_NOT_REVERSED`, rather than `ERR_PHARMACY_SUSPENDED`).

### 2.7. Reference Resolution in a Flat Resource Space

All resources are top-level; there is no URL nesting anywhere in the API except the DUR-alert listing attached to a claim. Relationships are expressed through foreign keys carried in request bodies and stored on responses — a formulary entry names its `plan_id` and `drug_id`, a claim names its `member_id` and `drug_id`, and so on — never through path hierarchy. Consequently, existence resolution is a single flat pass over the identifiers the request supplies, performed left to right: path identifiers first, then body foreign keys. The first identifier that fails to resolve determines the error: an unknown plan yields `ERR_PLAN_NOT_FOUND`, an unknown drug (whether referenced as `drug_id`, `step_drug_id`, or `card_drug_id`) yields `ERR_DRUG_NOT_FOUND`, an unknown member yields `ERR_MEMBER_NOT_FOUND`, an unknown pharmacy yields `ERR_PHARMACY_NOT_FOUND`, an unknown claim yields `ERR_CLAIM_NOT_FOUND`, an unknown prior authorization yields `ERR_PA_NOT_FOUND`, an unknown audit yields `ERR_AUDIT_NOT_FOUND`, and an unknown formulary entry yields `ERR_FORMULARY_ENTRY_NOT_FOUND` — all HTTP 404.

### 2.8. The Pharmacy Ledger and Automatic Debt Suspension

Every pharmacy carries a plan-payable ledger, exposed as `balance_cents` and initialized to 0 at registration. Three kinds of business events post to it: when one of the pharmacy's claims is adjudicated `PAID`, the claim's `plan_paid_cents` is added to the balance; when a claim is reversed, that same claim's `plan_paid_cents` is subtracted; and when an audit closes with findings, the audit's `total_clawback_cents` is subtracted. A `PbmAdmin` may additionally post a manual settlement or adjustment carrying an `amount_cents` (positive for a settlement payment into the ledger, negative for a further debit) together with a free-text `reason`; the amount is added to `balance_cents` and the pharmacy's `version` increments.

After every balance mutation — claim payment, reversal, audit clawback, or manual adjustment — the system evaluates the pharmacy's debt tolerance. Each pharmacy is registered with an `auto_suspend_threshold_cents`, a strictly positive amount. If the mutation leaves `balance_cents` at or below the negation of that threshold — the boundary is inclusive, so a balance exactly equal to the negative threshold suspends — the pharmacy's `status` automatically transitions from `ACTIVE` to `SUSPENDED` without any explicit client call. A `SUSPENDED` pharmacy cannot perform any claim write (submission, resubmission, reversal, or reprocessing); such attempts are rejected with `ERR_PHARMACY_SUSPENDED` (HTTP 409). Reinstatement is a deliberate administrative act: a `PbmAdmin` reinstates a pharmacy only while it is `SUSPENDED` (otherwise `ERR_PHARMACY_NOT_SUSPENDED`, HTTP 409) and only once its balance has been restored to strictly above the negative threshold (otherwise `ERR_PHARMACY_DEBT_OUTSTANDING`, HTTP 409). Reinstatement returns the pharmacy to `ACTIVE` and increments its `version`.

### 2.9. Optimistic Concurrency Control on Formulary Terms

Exactly one endpoint in the system participates in optimistic concurrency control: the formulary-entry update, `PUT /formulary-entries/{id}`. Such a request must carry `expected_formulary_entry_version` as a non-optional field, holding the `version` of the formulary entry the client last observed; a request omitting the field or carrying a non-integer value is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and this check is evaluated before the staleness comparison. If that value no longer matches the entry's currently stored `version` — because any other writer has mutated the entry in the interim — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting terms such as tier, quantity limits, and copay structure from being overwritten on the basis of a stale read. A successful update increments the entry's `version` by one. The update is offered for entries in any status, `ACTIVE` or `INACTIVE` alike; no state precondition gates it. No other endpoint accepts a version field.

## 3. Business Logic & Workflows

### 3.1. Configuring the Benefit: Plans, Drugs, and Formulary Terms

Benefit configuration begins with the **Plan**. A `PbmAdmin` creates a plan by supplying a `name`, an annual individual `deductible_cents`, an annual `oop_max_cents`, a flat `dispensing_fee_cents` added to every claim's allowed amount, and the plan's copay-assistance posture: an `assistance_model` of either `ACCUMULATOR` or `MAXIMIZER`. Both assistance parameters are required on creation regardless of the model chosen — `member_min_pay_cents` (the floor the member must always pay per fill out of pocket under the accumulator variant) and `card_fill_cap_cents` (the most a copay card may pay per fill under the maximizer variant, where 0 means uncapped) are each mandatory non-negative integers on every plan; the parameter belonging to the other variant is stored but simply never consulted by pricing. All plan monetary inputs are non-negative. A plan is born in `DRAFT` status. Activation moves it to `ACTIVE` and is permitted only from `DRAFT` — otherwise `ERR_PLAN_INVALID_STATE` — and only when at least one formulary entry already exists for the plan, otherwise `ERR_PLAN_NO_FORMULARY_ENTRIES`. Retirement moves an `ACTIVE` plan to its terminal `RETIRED` state; retiring from any other state is again `ERR_PLAN_INVALID_STATE`.

Retirement is the system's broadest cascade. When a plan is retired, every formulary entry belonging to it flips from `ACTIVE` to `INACTIVE`, and every member enrolled in it flips from `ACTIVE` to the terminal `TERMINATED` state. Each member termination then causes its own follow-on cascade — not issued by the retire call directly but by the termination itself: every prior authorization of the terminated member that stands in `PENDING` or `APPROVED` is moved to `CANCELLED`. `DENIED` authorizations are already terminal and are untouched.

Drugs are registered independently of any plan. A `PbmAdmin` registers a **Drug** with its `ndc` (the National Drug Code, unique across all drugs — a duplicate is `ERR_INVALID_REQUEST`), a display `name`, the `therapeutic_class` label that later drives therapeutic-duplication screening, a strictly positive `unit_cost_cents` ingredient cost per unit, a strictly positive `max_daily_dose_units` ceiling used by the high-daily-dose screen, and an optional `is_specialty` flag (default false) marking the drug as restricted to specialty-channel dispensing.

A **FormularyEntry** attaches one drug to one plan with coverage terms. The administrator supplies the `plan_id` and `drug_id`, a `tier` label from 1 (preferred generic) through 4 (specialty), utilization-management flags `pa_required` and `step_therapy_required` (each defaulting to false), step-therapy parameters, quantity and days-supply ceilings, copay terms, and an optional `rebate_eligible` flag (default false). The pairing of plan and drug is unique across all statuses: adding a second entry for the same `plan_id` and `drug_id` is rejected with `ERR_DUPLICATE_FORMULARY_ENTRY` (HTTP 409), even if the first entry has since gone `INACTIVE`. When `step_therapy_required` is true, `step_drug_id` must identify the prerequisite drug and is rejected as `ERR_INVALID_REQUEST` when absent; when step therapy is not required, `step_drug_id` must be null. The `step_therapy_lookback_days` window is a strictly positive number of days and defaults to 180 when omitted. Coverage ceilings are `quantity_limit_per_fill` and `max_days_supply`, both strictly positive. Copay terms are discriminated by `copay_type`: under `FLAT`, `copay_flat_cents` is required (and may be 0); under `PERCENTAGE`, `copay_percentage` is required and must lie between 0 and 100 inclusive. Omitting the required copay field for the declared type is `ERR_INVALID_REQUEST`. The counterpart field of the other type is tolerated when supplied: it is stored as given and simply ignored by pricing, though if present it must itself be well-formed — a supplied `copay_percentage` must be numeric and lie between 0 and 100 inclusive, and a supplied `copay_flat_cents` must be a non-negative integer — else `ERR_INVALID_REQUEST`. An entry is born `ACTIVE` and becomes `INACTIVE` only through the plan-retirement cascade.

Formulary terms are mutable while in force, through the OCC-guarded update described in §2.9: the administrator may revise `tier`, `pa_required`, `step_therapy_required`, `step_drug_id`, `step_therapy_lookback_days`, `quantity_limit_per_fill`, `max_days_supply`, `copay_type`, `copay_flat_cents`, `copay_percentage`, or `rebate_eligible`, and the request must carry `expected_formulary_entry_version` matching the entry's current `version`, else it fails with `ERR_STALE_VERSION`. For browsing coverage, the formulary-entry list can be filtered by `plan_id`, by `drug_id`, or by `step_drug_id`, with the usual `limit` and `offset` pagination.

### 3.2. Network Pharmacies and Member Enrollment

A `PbmAdmin` registers each dispensing location as a **Pharmacy**, supplying its `ncpdp_id` provider identifier (unique; duplicates are `ERR_INVALID_REQUEST`), a `name`, a dispensing `channel` of `RETAIL`, `SPECIALTY`, or `MAIL_ORDER`, and the `auto_suspend_threshold_cents` debt tolerance described in §2.8. The pharmacy starts `ACTIVE` with `balance_cents` at 0.

Members are enrolled into a plan by the administrator with a `plan_id`, a plan-scoped `external_ref` identifier (unique; duplicates are `ERR_INVALID_REQUEST`), the member's `full_name`, and an inclusive eligibility window from `eligibility_start_date` through `eligibility_end_date` — both ISO dates, with the end date required to be on or after the start date, else `ERR_INVALID_REQUEST`. Enrollment may also establish a manufacturer copay card: `card_drug_id` names the drug the card covers (null, or omitted, means the member holds no card) and `card_balance_cents` seeds the card's remaining funds (defaulting to 0, never negative). A member is born `ACTIVE`; the computed accumulators `deductible_paid_cents` and `oop_paid_cents` start at 0, and `oop_max_reached` starts false. The member list can be filtered by `plan_id` or by `card_drug_id`; a `Member` caller reading a member record may read only their own, with anything else rejected as `ERR_MEMBER_MISMATCH`.

### 3.3. The Prior Authorization Cycle

When a formulary entry demands prior authorization, the member initiates the request themselves. A `Member` creates a **PriorAuthorization** naming themselves as `member_id` — any other value is `ERR_MEMBER_MISMATCH` — plus the `drug_id` being requested, a strictly positive `requested_quantity`, and an optional free-text `note`. At most one live authorization may exist per member-drug pair: if a `PENDING` or `APPROVED` authorization already exists for the same `member_id` and `drug_id`, the request is rejected with `ERR_DUPLICATE_ACTIVE_PA` (HTTP 409); `DENIED` and `CANCELLED` authorizations do not block a fresh request. The new authorization is born `PENDING`, with `approved_quantity`, `expires_at`, and `denial_reason` unset and `quantity_consumed` at 0.

Decision belongs to a `ClinicalReviewer`. Approval is permitted only from `PENDING` — otherwise `ERR_PA_NOT_PENDING` — and requires the payload's `approved_quantity` (a strictly positive integer) and `expires_at` (a valid ISO date; missing or malformed values are `ERR_INVALID_REQUEST`), recording both — `expires_at` is an inclusive bound: the authorization remains usable on any fill whose fill date is on or before `expires_at` — stamps `decided_by` with the reviewer's `X-User-ID`, moves the authorization to `APPROVED`, and increments its `version`. Denial is likewise restricted to `PENDING`, requires the payload's `denial_reason` (a non-empty string, else `ERR_INVALID_REQUEST`), records it, stamps `decided_by`, moves the authorization to `DENIED`, and increments `version`. `DENIED` is terminal; so is `CANCELLED`, which an authorization reaches only through the plan-retirement cascade of §3.1, from either `PENDING` or `APPROVED`. The authorization list supports filtering by `member_id`, `drug_id`, or `status`.

Consumption is tracked on the authorization itself. When a paid claim consumed an authorization — visible as the claim's `pa_id` — the claim's `quantity` is added to the authorization's `quantity_consumed`, and reversal of that claim subtracts the same quantity back out, returning consumption to its pre-claim value. The quantity still available to adjudication is the `approved_quantity` minus the `quantity_consumed`.

### 3.4. Point-of-Sale Adjudication: The Eleven Edits

Claim submission is the heart of the system. A `Pharmacist` submits a **Claim** with the `member_id`, the `drug_id`, the pharmacy-assigned `prescription_number`, the `fill_date` (an ISO date), a strictly positive `quantity` of units dispensed, and a strictly positive `days_supply`. The dispensing pharmacy is not a payload field: it is taken from the caller's `X-User-ID` and recorded as the claim's `pharmacy_id`, which is why the caller must resolve to a registered, `ACTIVE` pharmacy — an unknown pharmacy is `ERR_PHARMACY_NOT_FOUND` and a suspended one is `ERR_PHARMACY_SUSPENDED` before adjudication even begins. For this endpoint the existence pass resolves the caller's pharmacy first, then the body's `member_id`, then the body's `drug_id`; when several identifiers are simultaneously unresolvable, the first in that order determines the 404 error.

Adjudication then runs eleven edits in a pinned sequence, and the sequence is observable in responses. First, member eligibility: the member must be `ACTIVE` and the `fill_date` must fall within the inclusive window from `eligibility_start_date` to `eligibility_end_date`, else `ERR_MEMBER_INELIGIBLE`. Second, plan status: the member's plan must be `ACTIVE`, else `ERR_PLAN_NOT_ACTIVE`. Third, coverage: an `ACTIVE` formulary entry must exist pairing the member's plan with the claim's drug, else `ERR_DRUG_NOT_ON_FORMULARY`. Fourth, channel: if the drug's `is_specialty` flag is true, the dispensing pharmacy's `channel` must be `SPECIALTY`, else `ERR_SPECIALTY_CHANNEL_REQUIRED`. Fifth, prior authorization presence: if the entry's `pa_required` is true, an `APPROVED` authorization must exist for this member and drug, else `ERR_PRIOR_AUTH_REQUIRED`; when several approved authorizations exist, the system selects among them by earliest `expires_at` first, breaking ties by earliest `created_at` and then by creation order, and that selection is the one consumed. Sixth, authorization currency: the selected authorization must still be usable on the fill date — `expires_at` on or after `fill_date`, with equality counting as usable — and if every approved authorization has expired before the fill date the edit fails with `ERR_PA_EXPIRED`. Seventh, authorization quantity: the claim's `quantity` must not exceed the selected authorization's remaining quantity (its `approved_quantity` minus its `quantity_consumed`), else `ERR_PA_QUANTITY_EXCEEDED`. Eighth, step therapy: if the entry's `step_therapy_required` is true, there must exist a `PAID` claim of the same member for the entry's `step_drug_id` whose fill date lies within the inclusive lookback window ending on the new claim's `fill_date` and beginning `step_therapy_lookback_days` earlier — else `ERR_STEP_THERAPY_NOT_MET`; a step-drug fill exactly `step_therapy_lookback_days` before the new fill date satisfies the edit, and `REVERSED` or `REJECTED` claims never satisfy it. Ninth, quantity ceiling: the `quantity` must not exceed the entry's `quantity_limit_per_fill`, with a quantity exactly equal to the limit passing, else `ERR_QUANTITY_LIMIT_EXCEEDED`. Tenth, days-supply ceiling: the `days_supply` must not exceed the entry's `max_days_supply`, again with equality passing, else `ERR_DAYS_SUPPLY_EXCEEDED`. Eleventh, the DUR hard stop of §3.6: after this call's override codes are applied, no alert raised for this claim may remain `OPEN` at `HIGH` severity, else `ERR_DUR_HARD_STOP`.

The claim is always persisted, whatever the outcome. When all eleven edits pass, the claim is created with `status` `PAID`, the response is 201, pricing and posting proceed as §3.5 describes, and `reject_reasons` is empty. When any edit fails, the claim is still persisted — now with `status` `REJECTED` — and the response is HTTP 422 whose `error_id` is the first failed edit in the pinned order; the claim's `reject_reasons` array records every failed edit's error identifier, in that same pinned order. A rejected claim's financial fields — `allowed_cents`, `copay_base_cents`, `deductible_applied_cents`, `card_applied_cents`, `member_pays_cents`, and `plan_paid_cents` — are all 0, and its `rebate_tag` is `REBATE_INELIGIBLE`. Claims carry a `resubmit_count`, initially 0, an `audit_status` that begins `UNAUDITED`, and a `pa_id` that is null unless an authorization was consumed. Claim listings can be filtered by `member_id`, `pharmacy_id`, `drug_id`, `pa_id`, or `status`; `Pharmacist` callers see only their own pharmacy's claims and `Member` callers only their own, with the same scoping applied to single-claim reads (a member reading another member's claim is `ERR_MEMBER_MISMATCH`).

### 3.5. Pricing, Copay Assistance, and Accumulator Posting

Pricing runs once the non-pricing edits pass, on initial submission, on resubmission, and on reprocessing alike, and its evaluation order is pinned exactly as follows. The claim's `allowed_cents` is the drug's `unit_cost_cents` multiplied by the `quantity`, plus the plan's `dispensing_fee_cents`. The member's remaining deductible is the plan's `deductible_cents` minus the member's `deductible_paid_cents`, floored at zero, and `deductible_applied_cents` is the smaller of `allowed_cents` and that remaining deductible; the post-deductible remainder is `allowed_cents` minus `deductible_applied_cents`. The tier copay base, `copay_base_cents`, is `copay_flat_cents` when the entry's `copay_type` is `FLAT`, or — under `PERCENTAGE` — the `allowed_cents` multiplied by `copay_percentage` and divided by 100, rounded up (ceiling) to whole cents at this single rounding point, so any fractional cent rounds up to the next cent. The copay actually owed is the smaller of `copay_base_cents` and the post-deductible remainder. Patient responsibility before the out-of-pocket cap is `deductible_applied_cents` plus that copay owed; the member's remaining out-of-pocket room is the plan's `oop_max_cents` minus `oop_paid_cents`, floored at zero; and final patient responsibility is the smaller of the pre-cap responsibility and that remaining room. The plan's share, `plan_paid_cents`, is `allowed_cents` minus patient responsibility.

Copay-card assistance applies immediately after patient responsibility is known, and only when the member's `card_drug_id` equals the claim's drug and `card_balance_cents` is greater than zero. The two assistance variants then diverge. Under the `ACCUMULATOR` model, the card may cover patient responsibility only down to the plan's `member_min_pay_cents` floor: `card_applied_cents` is the smaller of the card balance and the amount by which patient responsibility exceeds `member_min_pay_cents` (floored at zero), so the member always pays at least that floor per fill unless the card balance runs short. Under the `MAXIMIZER` model there is no member floor: the card pays the smallest of the card balance, the full patient responsibility, and the plan's `card_fill_cap_cents` — with a cap of 0 meaning uncapped, so the cap term drops out and the card covers up to the balance or the full responsibility. Either way, `member_pays_cents` is patient responsibility minus `card_applied_cents`, and only `member_pays_cents` ever accumulates toward the member's deductible and out-of-pocket totals — card money never accumulates under either variant. The same inputs therefore produce different `member_pays_cents` and different accumulator growth under the two models.

Posting happens as the claim enters `PAID`. The deductible credit is the smaller of `member_pays_cents` and `deductible_applied_cents`, and it is added to the member's `deductible_paid_cents`; the full `member_pays_cents` is added to `oop_paid_cents`; and `oop_max_reached` is then recomputed as true exactly when `oop_paid_cents` is greater than or equal to the plan's `oop_max_cents` — the equality boundary counts as reached. When `card_applied_cents` is positive, the card is debited by subtracting it from `card_balance_cents`. When a prior authorization was consumed, the claim's `quantity` is added to its `quantity_consumed`. The pharmacy ledger posts `plan_paid_cents` and immediately runs the auto-suspension check of §2.8.

Rebate tagging rides the same transition. When a claim enters `PAID`, its `rebate_tag` is set to `REBATE_ELIGIBLE` if the governing formulary entry's `rebate_eligible` flag is true, and `REBATE_INELIGIBLE` otherwise. A claim rejected on any path is `REBATE_INELIGIBLE`. When a previously eligible claim is reversed or clawed back by audit, its tag moves from `REBATE_ELIGIBLE` to `REBATE_VOID`; a tag of `REBATE_INELIGIBLE` is unchanged by those events.

### 3.6. Drug Utilization Review, Overrides, and the Hard Stop

DUR screening runs on every adjudication — initial submission, resubmission, and reprocessing — after the formulary and utilization-management edits have passed, and it considers only the member's other claims that stand in `PAID`; `REJECTED` and `REVERSED` claims are excluded from the comparison set. Fill windows are half-open: a fill covers the interval from its `fill_date` up to but not including `fill_date` plus `days_supply`, so a new fill dated exactly on the day an earlier fill's supply runs out does not overlap it. Three alert types exist. An `EARLY_REFILL` alert fires at `MEDIUM` severity when another `PAID` claim of the same member for the same drug overlaps the new fill — overlap meaning the earlier claim's fill date is before the new fill date plus the new days supply, and the new fill date is before the earlier fill date plus its days supply. A `THERAPEUTIC_DUPLICATION` alert, also `MEDIUM`, uses the identical overlap predicate against `PAID` claims of the same member for a different drug whose `therapeutic_class` matches the new drug's. A `HIGH_DAILY_DOSE` alert fires at `HIGH` severity when the claim's `quantity` strictly exceeds the drug's `max_daily_dose_units` multiplied by its `days_supply`; a quantity exactly equal to that product raises no alert. Screening writes one **DurAlert** row per claim per `alert_type` — duplicates of the same type for the same claim are suppressed, where an existing alert of that type on the claim standing `OPEN` or `OVERRIDDEN` counts as live and suppresses the new row, while a `SUPERSEDED` one does not — each recording the `claim_id`, its `alert_type`, its `severity`, and a `status` born `OPEN`, with `override_code` unset. As append-only screening records, alerts carry `id` and `created_at` only.

Alerts are resolved by the dispensing pharmacist. A resubmission may carry `dur_overrides`, a list of entries each pairing an `alert_id` with an `override_code` drawn from `PROFESSIONAL_CONSULT`, `PRESCRIBER_CONFIRMED`, or `PATIENT_EDUCATED`. Each named alert must belong to the claim being resubmitted and the code must be a valid enumeration value, else the request fails shape validation with `ERR_INVALID_REQUEST`. Every override naming one of the claim's `OPEN` alerts moves that alert to `OVERRIDDEN` and records the code; overrides naming alerts that are no longer `OPEN` are simply ignored. The eleventh adjudication edit then evaluates what remains: if any of the claim's alerts is still `OPEN` with `HIGH` severity after this call's overrides are applied, adjudication fails with `ERR_DUR_HARD_STOP` — `MEDIUM` alerts never block payment on their own.

Reprocessing regenerates screening entirely. When a reversed claim is reprocessed with corrected values, every alert still `OPEN` on the claim is moved to `SUPERSEDED`, the screen is re-run against the corrected quantity, days supply, and fill date, and fresh `OPEN` alerts are written as the corrected facts dictate. The alerts attached to a claim can be listed through the claim's alert sub-resource, with the usual `limit` and `offset` pagination.

### 3.7. Reversal and Reprocessing

A paid claim can be backed out in full. Reversal is performed by the owning pharmacy's pharmacist — any other pharmacy is `ERR_PHARMACY_MISMATCH` — requires the claim to stand in `PAID` (otherwise `ERR_CLAIM_NOT_PAID`) and the pharmacy to be `ACTIVE` (otherwise `ERR_PHARMACY_SUSPENDED`), and must carry a free-text `reversal_reason`; a missing or non-string `reversal_reason` is `ERR_INVALID_REQUEST` (HTTP 400). Reversal is exact compensation against the claim's stored financial fields, so accumulators and ledgers return to their pre-claim values: the smaller of `member_pays_cents` and `deductible_applied_cents` is subtracted from `deductible_paid_cents`; the full `member_pays_cents` is subtracted from `oop_paid_cents`; `oop_max_reached` is recomputed on the same greater-than-or-equal boundary; any `card_applied_cents` is credited back to `card_balance_cents`; if `pa_id` names an authorization, the claim's `quantity` is subtracted from its `quantity_consumed`; the pharmacy's `balance_cents` is reduced by `plan_paid_cents`, followed as always by the auto-suspension check; and a `rebate_tag` of `REBATE_ELIGIBLE` becomes `REBATE_VOID`. The claim itself moves from `PAID` to `REVERSED`.

Reprocessing gives the pharmacy a corrective path from `REVERSED`. The pharmacist supplies corrected values — `quantity`, `days_supply`, or `fill_date`, each optional, with omitted fields (including fields explicitly set to null) keeping their stored values — and the claim is re-adjudicated on the corrected facts; the corrected values are stored on the claim whether or not the re-adjudication succeeds. The operation requires the claim to be `REVERSED` (otherwise `ERR_CLAIM_NOT_REVERSED`) and the pharmacy `ACTIVE`. All still-`OPEN` alerts are first `SUPERSEDED` and DUR screening re-runs on the corrected values. If every edit passes, the response is 200, all financial fields are recomputed from the corrected values, and the full posting cascade of §3.5 applies exactly as on a fresh payment, returning the claim to `PAID`. If any edit fails, the response is 422, the claim lands in `REJECTED` with `reject_reasons` recomputed in pinned edit order, and its financial fields are reset to 0 with `pa_id` cleared to null and `rebate_tag` set to `REBATE_INELIGIBLE`.

Resubmission is the parallel corrective path from `REJECTED`, open only while the claim stands in `REJECTED` (otherwise `ERR_CLAIM_NOT_REJECTED`) and only to the owning, non-suspended pharmacy. Each resubmission applies any `dur_overrides` carried in the payload, increments `resubmit_count` by one, and re-runs the full adjudication pipeline against the claim's stored quantity, days supply, and fill date — resubmission does not accept corrected values. When the edits now pass, `reject_reasons` is cleared, the response is 200, and the same payment cascade as a fresh adjudication posts — accumulators, card debit, authorization consumption, pharmacy ledger, and rebate tag — moving the claim to `PAID`. When edits still fail, the response is 422, the claim remains `REJECTED`, `reject_reasons` is recomputed in the pinned order, and the financial fields are held at 0 with `pa_id` null and `rebate_tag` `REBATE_INELIGIBLE`. Either way, the resubmission count and the alert overrides persist.

### 3.8. Pharmacy Audit, Dispute, and Clawback Settlement

Retrospective review begins when an `Auditor` opens a **PharmacyAudit** against a pharmacy, supplying the `pharmacy_id`, an inclusive closed window from `window_start_date` through `window_end_date` (the end must be on or after the start, else `ERR_INVALID_REQUEST`), and an `extrapolation_method` of `CLAIM_LEVEL` or `EXTRAPOLATED`. Windows may not collide: a new audit is rejected with `ERR_AUDIT_WINDOW_OVERLAP` (HTTP 422) when the same pharmacy already has an audit in `OPEN`, `FINDINGS_RECORDED`, or `DISPUTED` status whose closed window intersects the new one — and because both window bounds are inclusive, windows that merely touch (the new start equal to an existing end) count as overlapping. An audit is born `OPEN`, with `findings` empty, `sample_size` and `universe_paid_claims` at 0, `total_clawback_cents` at 0, and `dispute_reason` unset. Audit listings can be filtered by `pharmacy_id` or `status`.

Findings are recorded wholesale. The auditor submits a `findings` list of claim-and-amount pairs — each pairing a `claim_id` with a strictly positive `clawback_cents`, and an empty list is `ERR_INVALID_REQUEST` — from any of `OPEN`, `FINDINGS_RECORDED`, or `DISPUTED` status; from any other status the call is `ERR_AUDIT_INVALID_STATE` (HTTP 409). Every referenced claim must be auditable: it must exist, belong to the audit's pharmacy, stand in `PAID`, carry a `fill_date` inside the audit's closed window, and still be `UNAUDITED` — any violation is `ERR_CLAIM_NOT_AUDITABLE` (HTTP 422). The `UNAUDITED` requirement carries one carve-out: a claim already `FLAGGED` by this same audit's current finding set remains referenceable when findings are revised, so re-recording an overlapping set does not fail on its own prior flags. Each recording replaces the previous finding set in its entirety and recomputes `sample_size` as the count of findings. Claims newly referenced by the set move from `UNAUDITED` to `FLAGGED`, while claims dropped from the prior set return to `UNAUDITED`.

The audited pharmacy may contest the result: its own pharmacist disputes the audit with a `dispute_reason`, which is permitted only from `FINDINGS_RECORDED` — otherwise `ERR_AUDIT_INVALID_STATE` — and moves the audit to `DISPUTED`, recording the reason (the most recent dispute's reason is the one retained). The dispute cycle completes only when the auditor records revised findings, moving the audit back to `FINDINGS_RECORDED`; an audit standing in `DISPUTED` cannot be closed.

Closing takes one of two shapes. Closing an audit in `OPEN` — where no findings were ever recorded — yields `CLOSED_NO_FINDINGS` with `total_clawback_cents` fixed at 0. Closing from `FINDINGS_RECORDED` yields `CLOSED_WITH_FINDINGS` and triggers the clawback cascade. At close time the system measures `universe_paid_claims` as the count of the pharmacy's claims standing in `PAID` with `fill_date` inside the closed window. Under `CLAIM_LEVEL`, `total_clawback_cents` is simply the sum of the findings' `clawback_cents` and the universe size is irrelevant to the total. Under `EXTRAPOLATED`, each finding's clawback is scaled by the ratio of `universe_paid_claims` to `sample_size`, each scaled amount is rounded half-up to whole cents first, and only then are the per-claim amounts summed — summing first and rounding once is forbidden, so findings of 3333 and 1001 cents with a ratio of three-halves produce 5000 plus 1502, a total of 6502 cents, not 6501. Every claim named in the findings then moves from `FLAGGED` to `CLAWED_BACK`, any such claim whose `rebate_tag` was `REBATE_ELIGIBLE` is voided to `REBATE_VOID`, the pharmacy's `balance_cents` is reduced by `total_clawback_cents`, and the auto-suspension check runs on the resulting balance — which may tip the pharmacy from `ACTIVE` to `SUSPENDED` per §2.8. Both closed states are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Claim submission is the exception in shape, not spirit: it returns 201 when adjudication pays the claim, and HTTP 422 when any edit fails — with the claim nonetheless persisted in `REJECTED`. Resubmission and reprocessing likewise answer 200 on success and 422 on a still-failing edit.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a benefit plan (status `DRAFT`) | PbmAdmin |
| GET | `/plans/{id}` | Fetch one plan | PbmAdmin, Pharmacist, Member, ClinicalReviewer, Auditor |
| POST | `/plans/{id}/activate` | Move a plan from `DRAFT` to `ACTIVE`; requires at least one formulary entry | PbmAdmin |
| POST | `/plans/{id}/retire` | Move a plan from `ACTIVE` to `RETIRED`; cascades to entries, members, and authorizations | PbmAdmin |
| POST | `/drugs` | Register a drug (`ndc` unique) | PbmAdmin |
| GET | `/drugs/{id}` | Fetch one drug | PbmAdmin, Pharmacist, Member, ClinicalReviewer, Auditor |
| POST | `/formulary-entries` | Add a drug to a plan's formulary with tier, UM, and pricing terms | PbmAdmin |
| GET | `/formulary-entries` | List formulary entries; filterable by plan, drug, or step drug | PbmAdmin, Pharmacist, Member, ClinicalReviewer, Auditor |
| GET | `/formulary-entries/{id}` | Fetch one formulary entry | PbmAdmin, Pharmacist, Member, ClinicalReviewer, Auditor |
| PUT | `/formulary-entries/{id}` | Update formulary terms; requires `expected_formulary_entry_version` | PbmAdmin |
| POST | `/pharmacies` | Register a network pharmacy (`ncpdp_id` unique) | PbmAdmin |
| GET | `/pharmacies/{id}` | Fetch one pharmacy (balance and status) | PbmAdmin, Pharmacist, Auditor |
| POST | `/pharmacies/{id}/balance-adjustments` | Post a payment or adjustment of `amount_cents` to the pharmacy ledger | PbmAdmin |
| POST | `/pharmacies/{id}/reinstate` | Return a `SUSPENDED` pharmacy to `ACTIVE` once its balance is restored | PbmAdmin |
| POST | `/members` | Enroll a member into a plan, optionally with a copay card | PbmAdmin |
| GET | `/members` | List members; filterable by plan or card drug | PbmAdmin, ClinicalReviewer, Auditor |
| GET | `/members/{id}` | Fetch one member (accumulators, card balance); members read self only | PbmAdmin, Member, ClinicalReviewer, Auditor |
| POST | `/prior-authorizations` | Member requests a prior authorization for a drug | Member |
| GET | `/prior-authorizations` | List prior authorizations; filterable by member, drug, or status | PbmAdmin, Member, Pharmacist, ClinicalReviewer, Auditor |
| GET | `/prior-authorizations/{id}` | Fetch one prior authorization (consumption, expiry) | PbmAdmin, Member, Pharmacist, ClinicalReviewer, Auditor |
| POST | `/prior-authorizations/{id}/approve` | Approve a `PENDING` authorization with quantity and expiry | ClinicalReviewer |
| POST | `/prior-authorizations/{id}/deny` | Deny a `PENDING` authorization with a reason | ClinicalReviewer |
| POST | `/claims` | Submit a point-of-sale claim; runs the pinned adjudication pipeline | Pharmacist |
| GET | `/claims` | List claims; scoped for Pharmacist and Member callers | PbmAdmin, Pharmacist, Member, Auditor |
| GET | `/claims/{id}` | Fetch one claim (same ownership scoping) | PbmAdmin, Pharmacist, Member, Auditor |
| POST | `/claims/{id}/resubmit` | Re-adjudicate a `REJECTED` claim, optionally with DUR overrides | Pharmacist |
| POST | `/claims/{id}/reverse` | Reverse a `PAID` claim with full financial compensation | Pharmacist |
| POST | `/claims/{id}/reprocess` | Re-adjudicate a `REVERSED` claim with corrected values | Pharmacist |
| GET | `/claims/{id}/dur-alerts` | List the DUR alerts raised for a claim | PbmAdmin, Pharmacist, Auditor |
| POST | `/audits` | Open a pharmacy audit over a closed date window | Auditor |
| GET | `/audits` | List audits; filterable by pharmacy or status | PbmAdmin, Pharmacist, Auditor |
| GET | `/audits/{id}` | Fetch one audit (findings, totals) | PbmAdmin, Pharmacist, Auditor |
| POST | `/audits/{id}/findings` | Record or revise findings wholesale; referenced claims become `FLAGGED` | Auditor |
| POST | `/audits/{id}/dispute` | Contest recorded findings on behalf of the audited pharmacy | Pharmacist |
| POST | `/audits/{id}/close` | Close the audit with or without findings; triggers the clawback cascade | Auditor |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narrative of §2 and §3; this catalogue enumerates identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_PHARMACY_MISMATCH` | 403 |
| `ERR_MEMBER_MISMATCH` | 403 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_DRUG_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_PHARMACY_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_PA_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_FORMULARY_ENTRY_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PHARMACY_SUSPENDED` | 409 |
| `ERR_CLAIM_NOT_PAID` | 409 |
| `ERR_CLAIM_NOT_REVERSED` | 409 |
| `ERR_CLAIM_NOT_REJECTED` | 409 |
| `ERR_PA_NOT_PENDING` | 409 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_PLAN_NO_FORMULARY_ENTRIES` | 409 |
| `ERR_AUDIT_INVALID_STATE` | 409 |
| `ERR_PHARMACY_NOT_SUSPENDED` | 409 |
| `ERR_PHARMACY_DEBT_OUTSTANDING` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_FORMULARY_ENTRY` | 409 |
| `ERR_DUPLICATE_ACTIVE_PA` | 409 |
| `ERR_AUDIT_WINDOW_OVERLAP` | 422 |
| `ERR_CLAIM_NOT_AUDITABLE` | 422 |
| `ERR_MEMBER_INELIGIBLE` | 422 |
| `ERR_PLAN_NOT_ACTIVE` | 422 |
| `ERR_DRUG_NOT_ON_FORMULARY` | 422 |
| `ERR_SPECIALTY_CHANNEL_REQUIRED` | 422 |
| `ERR_PRIOR_AUTH_REQUIRED` | 422 |
| `ERR_PA_EXPIRED` | 422 |
| `ERR_PA_QUANTITY_EXCEEDED` | 422 |
| `ERR_STEP_THERAPY_NOT_MET` | 422 |
| `ERR_QUANTITY_LIMIT_EXCEEDED` | 422 |
| `ERR_DAYS_SUPPLY_EXCEEDED` | 422 |
| `ERR_DUR_HARD_STOP` | 422 |
