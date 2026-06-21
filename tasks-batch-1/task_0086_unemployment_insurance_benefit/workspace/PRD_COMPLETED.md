# Unemployment Insurance Benefit API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Unemployment Insurance Benefit API, a back-office system that administers the full life of an unemployment claim: from the moment a separated worker files, through the monetary determination that establishes how much they may collect, the weekly certifications that release individual benefit payments, the charging of those payments back to the employers whose wages funded the claim, and the recovery of any benefits paid in error. The domain is fundamentally a ledger-reconciliation problem dressed in administrative-law clothing. Every dollar that leaves the trust fund must be traceable to a qualifying week, charged proportionally to the employers who built the claimant's wage base, and — when paid in error — recovered to the cent. The system must therefore keep several derived balances continuously reconciled against the events that drive them, never letting a claim's remaining balance, an employer's reserve, or an overpayment's recovered total drift away from the sum of the transactions behind it.

Layered on top of the money is a compliance-and-audit spine. Determinations can be appealed; appeals can be remanded, withdrawn, dismissed, or decided; and a reversal on appeal can reach back across entity boundaries to restore a claim that was previously denied. Crucially, the operator who issued a determination may never sit in judgment of the appeal against it — a segregation-of-duties rule the API enforces structurally. The design also anticipates emergency programs (the kind stood up during a pandemic) that extend the number of compensable weeks and, in some cases, waive the ordinary work-search obligation. The remainder of this document fixes the precise contract for these behaviors so that an implementation can be validated against a single, unambiguous specification.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Section 3 then narrates the business workflows in detail.

### 2.1. User and Role-Based Access Control

Every request (other than the explicitly anonymous-permitted creates described below) must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header (absent or blank) on a protected endpoint is rejected with `ERR_UNAUTHENTICATED`; a request whose `X-User-Role` is present but is not one of the eight recognized role strings is likewise rejected with `ERR_UNAUTHENTICATED`, before any role-permission check. When both headers are present and the declared role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes eight roles, spelled exactly as follows: `Anonymous`, `ProgramAdmin`, `Claimant`, `Adjudicator`, `BenefitPaymentOfficer`, `Employer`, `AppealsClerk`, and `Referee`.

The relationship between `X-User-ID` and persisted entities differs by role:

- When `X-User-Role` is `Claimant`, `X-User-ID` is the `id` of the acting `Claimant`; ownership checks on any resource that references a `Claimant` compare the resource's claimant foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Employer`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an `Employer` compare the resource's employer foreign-key field to `X-User-ID`. In particular, an employer may only protest an `EmployerCharge` whose `employer_id` equals its own `X-User-ID`.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque public identifier not tied to any persisted entity; the anonymous capacity exists only to permit self-registration of a claimant.
- When `X-User-Role` is `ProgramAdmin`, `Adjudicator`, `BenefitPaymentOfficer`, `AppealsClerk`, or `Referee`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for it — for example, the issuing adjudicator's operator id is stored as `issuing_adjudicator_id` on a `Determination`, and a referee's operator id is stored as `assigned_referee_id` on an `Appeal` — but it is never compared to any entity's `id` for ownership.

Two creation endpoints accept an `Anonymous` caller: registering a claimant may be performed anonymously or by a `ProgramAdmin`. All other operations require an authenticated, role-appropriate caller. The authorization table in Section 4 lists the permitted roles for each operation; the narrative in Section 3 names the acting role for each workflow step.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0. Requests supplying a `limit` below 1 or above 100 are malformed input.

Unless a specific endpoint states otherwise, every list is returned sorted by the resource's `created_at` timestamp in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Audit Trail

Most top-level resources — `Employer`, `Claimant`, `Claim`, `Determination`, `WeeklyCertification`, `EmployerCharge`, `Overpayment`, `OverpaymentRecovery`, `Appeal`, and `EmergencyExtensionProgram` — carry a uniform set of system-managed fields. Each such resource exposes an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits), an `updated_at` timestamp in the same format that is refreshed on every mutation, and an integer `version` that begins at its initial value and is incremented by exactly one on each mutation. The `version` field is the basis for the optimistic-concurrency mechanism described in Section 2.6.

Two entities are deliberately leaner. A `WageRecord` and a `WorkSearchContact` are immutable ledger lines: each carries only an `id` and a `created_at`. Neither exposes `updated_at` and neither exposes `version`, because once written they are never mutated in place.

Whenever a write touches a resource — whether a client-driven action or a server-initiated cascade — the system refreshes that resource's `updated_at` and increments its `version`. This applies equally to mutations of computed fields: when a paid week debits a claim's `remaining_balance_cents`, or a relieved charge credits an employer's `reserve_account_balance_cents`, the affected `Claim` or `Employer` is itself mutated, and its `updated_at` and `version` move accordingly.

### 2.5. Nested Resource Retrieval and Referential Integrity

Endpoint paths that nest one resource under another (for example, the recoveries that belong to an overpayment, or the work-search contacts that belong to a weekly certification) are validated left to right. The system confirms the existence of each path segment in order and rejects the request with `ERR_NOT_FOUND` against the first identifier in the path that does not resolve to an existing resource. Only once the full path resolves does the system evaluate the body.

Existence checking proceeds in a fixed priority. First, any resource named in the path or referenced by a foreign key in the body must exist at all; a missing target yields `ERR_NOT_FOUND`. Next, a foreign key that resolves to a resource of the wrong type — for instance, a `claim_id` that actually names some other kind of record, or a `WorkSearchContact` whose `employer_id` does not name a real `Employer` — is rejected with `ERR_INVALID_REFERENCE`. These referential checks precede the field-shape and business checks described next.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by mandatory optimistic-concurrency checks because each one legitimately supersedes a balance the client must have observed first.

Applying an emergency extension to a claim requires the request to carry `expected_claim_version`, holding the client's last observed `version` of the target `Claim`. If that value does not equal the claim's current `version` — because another writer has since applied an extension or a paid week has recomputed the balance — the apply is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), so the client cannot double-grant weeks on top of a claim state it never saw.

Recording a recovery against an overpayment requires the request to carry `expected_overpayment_version`, holding the client's last observed `version` of the target `Overpayment`. If that value does not equal the overpayment's current `version` — because another writer already applied a recovery and advanced `recovered_cents` — the recovery is rejected with `ERR_STALE_OVERPAYMENT_VERSION` (HTTP 412), so the client cannot over-apply past `total_assessed_cents` against a balance it never observed.

Both of these `expected_claim_version` and `expected_overpayment_version` fields are required, non-optional inputs on their respective operations. Other endpoints may accept an optional `expected_claim_version`, `expected_claimant_version`, `expected_weekly_certification_version`, `expected_employer_charge_version`, `expected_overpayment_version`, or `expected_appeal_version` field; when such a field is supplied and does not match the targeted resource's current `version`, the request is rejected with the generic `ERR_STALE_VERSION` (HTTP 412), and when it is omitted the mutation proceeds without a concurrency check. Endpoints that take no version field perform no concurrency check.

### 2.7. Monetary Values, Cents, and Rounding

All money in the system is represented as integers denominated in cents; there are no fractional cents and no floating-point currency fields in any payload. Where a calculation introduces a fraction — for example, a percentage of a benefit amount — the result is resolved to whole cents using round-half-up before it participates in any further arithmetic, and the document states the rounding point explicitly at each calculation in Section 3. Sums of integer cents need no rounding. Where the specification calls for rounding to a whole dollar, that means rounding to the nearest multiple of 100 cents, again half-up. The employer's `experience_rate` is the one field that is a decimal fraction rather than cents; it is carried as supplied and is used only as descriptive context for an employer's account, never as a multiplier against any benefit.

### 2.8. Derived-Balance Reconciliation

Several fields are not free inputs but running totals the system must keep equal to the transactions behind them. A claim's `remaining_balance_cents` always equals its `maximum_benefit_amount_cents` less the sum of the `payable_amount_cents` of its paid weeks. An employer's `reserve_account_balance_cents` always equals its `reserve_opening_balance_cents` less the `charge_amount_cents` of every `EmployerCharge` against it that is currently `POSTED`, with relieved charges credited back. An overpayment's `recovered_cents` always equals the sum of `amount_cents` over its `APPLIED` recoveries, and its `total_assessed_cents` is the conserved target that recovery must drive that running total toward. An employer's `charge_protest_count` always equals the number of its charges currently in `PROTESTED` status. These invariants are not advisory: every transaction that moves money or status must update the relevant derived field in the same operation, and the corresponding state transitions in Section 3 fire off precisely these reconciliations.

### 2.9. Segregation of Duties and Operator Identity

The integrity of the appeals process rests on a single structural rule: the operator who decides an appeal must not be the operator who issued the determination under appeal. When a determination is issued, the issuing operator's `X-User-ID` is recorded as `issuing_adjudicator_id`. When an appeal of that determination is assigned a referee, the `assigned_referee_id` supplied must differ from that recorded `issuing_adjudicator_id`; an attempt to assign the same operator is rejected with `ERR_SEGREGATION_OF_DUTIES`. This rule is detailed alongside the appeals workflow in Section 3.

### 2.10. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed order so that the returned error is predictable. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every path- and body-referenced resource (`ERR_NOT_FOUND`), then the type-correctness of body foreign keys (`ERR_INVALID_REFERENCE`), then the presence and well-formedness of input fields (`ERR_INVALID_REQUEST`), then uniqueness constraints (`ERR_DUPLICATE_RESOURCE`), then whether the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after all of those pass does the system evaluate the operation-specific business rules — timeliness, segregation of duties, work-search sufficiency, availability, waiver eligibility, over-recovery, balance sufficiency, remand limits, and extension windows — and finally the optimistic-concurrency check. Wherever Section 3 describes a business rule, this ordering tells you which earlier failures would have been surfaced first.

## 3. Business Logic & Workflows

### 3.1. Registering Parties, Wages, and Programs

The system begins with the parties. A `ProgramAdmin` registers an `Employer` by supplying its `legal_name`, its `state_account_number`, its `experience_rate`, and its `reserve_opening_balance_cents`. The `state_account_number` must be unique across all employers; a collision is rejected with `ERR_DUPLICATE_RESOURCE`. The `experience_rate` is a decimal fraction that must be at least 0.0 and at most 0.12. On creation the system seeds the employer's `reserve_account_balance_cents` equal to the supplied `reserve_opening_balance_cents` and sets `charge_protest_count` to 0.

A `Claimant` may be self-registered by an anonymous caller or created by a `ProgramAdmin`, supplying `full_name`, `ssn_last4`, `date_of_birth`, and optionally `is_able_and_available`. The `ssn_last4` must be exactly four numeric characters, and — unlike employers — claimant uniqueness is not enforced, so two claimants may share the same last four SSN digits. The `is_able_and_available` attestation defaults to true and gates weekly eligibility later; a claimant or `ProgramAdmin` may later update this attestation, which increments the claimant's `version` by one, and may supply an optional `expected_claimant_version` for a concurrency check.

Wages enter through `WageRecord` lines, reported by an `Employer` or a `ProgramAdmin`. Each line names the `claimant_id` it credits, the `employer_id` that paid the wages, the `calendar_quarter` in which they were earned, and the `gross_wages_cents` amount, with an optional `is_disputed` flag. The `calendar_quarter` must match the pattern of a four-digit year, a hyphen, the letter Q, and a quarter number 1 through 4 (for example, 2025-Q1); `gross_wages_cents` must be at least 0. The `is_disputed` flag defaults to false; a disputed wage record is excluded from every base-period calculation. An employer or admin may later toggle a wage record's dispute flag, changing which wages count toward a claim.

Emergency programs are configured by a `ProgramAdmin`. An `EmergencyExtensionProgram` is created with a `program_code`, the number of `extra_weeks` it grants, a `trigger_start_date`, a `trigger_end_date`, an optional `waives_work_search` flag, and an optional `is_active` flag. The `program_code` is unique across all programs (a collision is `ERR_DUPLICATE_RESOURCE`); `extra_weeks` must be greater than 0 and at most 53. The `waives_work_search` and `is_active` flags both default appropriately — programs default to active, and to not waiving work search — and a `ProgramAdmin` may later toggle the `is_active` switch. A program that is not active cannot be applied to any claim.

### 3.2. Filing a Claim and the Monetary Determination

A `Claimant` (or a `ProgramAdmin` acting on their behalf) opens a `Claim` by supplying the `claimant_id` and the `filed_date`. The `filed_date` is the ISO date of the Sunday on which the benefit year begins and is the anchor for the base period. A new claim is created in `DRAFT` status with its monetary fields at their defaults: `base_period_method` unset, `weekly_benefit_amount_cents`, `maximum_benefit_amount_cents`, and `remaining_balance_cents` all 0, `emergency_extension_id` null, and `extension_weeks_granted` 0.

Submitting a draft claim advances it from `DRAFT` to `MONETARY_PENDING`. Submission is permitted only while the claim is `DRAFT`, requires that the referenced claimant exist, and requires that at least one non-disputed `WageRecord` exists for that claimant; a submission with no qualifying wages is rejected with `ERR_NO_QUALIFYING_WAGES`. No monetary fields change at submission — the claim merely awaits adjudication — and the claim's `version` increments by one. The submit action accepts an optional `expected_claim_version`.

The monetary determination is the heart of qualification. An `Adjudicator` issues a `Determination` by supplying the `claim_id` and a `determination_type` of either `MONETARY` or `NONMONETARY`. A `MONETARY` determination is permitted only when the claim is in `MONETARY_PENDING`, and it runs the full base-period calculation described below. A `NONMONETARY` determination is subject to no claim-state precondition (it may be issued against a claim in any status), runs no base-period calculation, leaves both wage figures at 0, performs no claim transition, and is created with `outcome` `PENDING`. The determination records its result in `outcome` (one of `PENDING`, `ALLOWED`, `DENIED`, `REVERSED`), stamps the issuing operator's id into `issuing_adjudicator_id`, and computes `base_period_total_wages_cents` and `high_quarter_wages_cents` (both 0 for a `NONMONETARY` determination). It also computes an `appeal_deadline_date` (always set on creation, for both determination types) and sets `is_appealable` to true on creation regardless of outcome; thereafter `is_appealable` is true while the outcome is `ALLOWED`, `DENIED`, or a still-`PENDING` `NONMONETARY` determination and the determination has not been reversed, and becomes false only when the determination is reversed on appeal.

**Choosing the base period.** Quarters are ordered chronologically by `calendar_quarter` — first by year, then by quarter number. The "completed" quarters are those strictly before the quarter that contains the claim's `filed_date`. From the completed quarters, take the five most recent. The **standard base period** is the first four of those five — that is, the five most recent completed quarters with the single most recent one dropped. The **alternate base period** is the four most recent completed quarters — the same window of five with its oldest dropped. For a chosen quarter set, a wage record is included only if its `calendar_quarter` falls in that set and its `is_disputed` flag is false. The base-period total for a set is the sum of `gross_wages_cents` over the included records, and the high-quarter figure is the largest single-quarter sum of `gross_wages_cents` among those included records (0 if none). Because the two sets differ by one quarter, they generally produce a different total and a different high quarter from the very same wage records.

**Monetary qualification.** A quarter set qualifies only when all three of the following hold: the base-period total is at least 260,000 cents; the high-quarter figure is at least 130,000 cents; and the base-period total is at least one-and-a-half times the high-quarter figure. To avoid any floating-point ambiguity, the third test is evaluated by comparing twice the base-period total against three times the high-quarter figure — the set passes when twice the total is at least three times the high quarter. The third test guards against a wage history concentrated in a single quarter. The selection order is pinned: the system tries the standard base period first, and if it qualifies, that method is selected and the alternate is never evaluated for selection; only if the standard set fails is the alternate set tested; if the alternate qualifies, it is selected. The selected method is recorded in `base_period_method` as `STANDARD` or `ALTERNATE`.

When a method qualifies, the determination's `outcome` is `ALLOWED` and the parent claim transitions `MONETARY_PENDING → MONETARILY_ELIGIBLE`. The system computes the weekly and maximum benefit amounts from the **selected** method's figures (see Sections 3.3 and 3.4), sets the claim's `weekly_benefit_amount_cents` and `maximum_benefit_amount_cents`, sets `remaining_balance_cents` equal to the maximum benefit amount, and increments the claim's `version`. When neither method qualifies — the standard set fails and the alternate set also fails all three sub-tests — the determination's `outcome` is `DENIED`, the claim transitions `MONETARY_PENDING → MONETARILY_INELIGIBLE`, `base_period_method` is set to `NONE`, the weekly and maximum benefit amounts remain 0, and the claim's `version` increments. `MONETARILY_INELIGIBLE` is a terminal claim state except for one cross-entity reversal path described in Section 3.7.

### 3.3. Deriving the Weekly Benefit Amount

The weekly benefit amount (the per-week ceiling on what a claimant can collect) is derived from the high-quarter wages of the selected base period. Take `high_quarter_wages_cents` and divide it by 26. Round that raw figure to the nearest whole dollar using round-half-up — that is, divide by 100, round half-up to an integer number of dollars, and multiply back by 100 cents. Then clamp the rounded dollar figure into the inclusive range whose floor is 4,000 cents and whose ceiling is 60,000 cents: if the rounded figure is below 4,000 cents the weekly benefit amount becomes exactly 4,000 cents, and if it is above 60,000 cents it becomes exactly 60,000 cents regardless of how far it exceeded. The rounding happens before the clamp, and the clamp does not re-round. The result is stored as the claim's `weekly_benefit_amount_cents`.

### 3.4. Deriving the Maximum Benefit Amount

A claim's `maximum_benefit_amount_cents` is the lesser of two caps. The **duration cap** is the weekly benefit amount multiplied by 26 — that is, 26 full weeks of benefits. The **wage-percentage cap** is fifty percent of the base-period total wages, floored down to a whole dollar (a whole multiple of 100 cents). The base maximum benefit amount is the smaller of those two caps: when 26 weeks of the weekly benefit amount is at most half the base-period total wages, the duration cap binds and the claimant has a full 26 weeks of entitlement; when half the base-period total wages is the smaller figure, the wage-percentage cap binds and the claimant has fewer than 26 full weeks. When an emergency extension is later applied (Section 3.6), the maximum benefit amount is recomputed as the base maximum plus the product of `extension_weeks_granted` and the weekly benefit amount, added without any re-rounding.

### 3.5. Weekly Certification, Work Search, and Payment

Once a claim is `MONETARILY_ELIGIBLE`, the claimant certifies each compensable week. A `Claimant` or `ProgramAdmin` files a `WeeklyCertification` by supplying the `claim_id`, the `week_ending_date`, optionally the `reported_earnings_cents` for that week, and optionally a `work_search_waived` override flag (a boolean that defaults to false and is persisted and returned on the certification as supplied). The `week_ending_date` must be a Saturday and must be unique per claim — a second certification for the same claim and week is rejected with `ERR_DUPLICATE_RESOURCE`. A new certification starts with `adjudication_status` of `PENDING` and `payment_status` of `UNPAID`. Its `reported_earnings_cents` defaults to 0 and must be at least 0; its `payable_amount_cents` is 0 until the week is both adjudicated eligible and paid.

A certification carries two **independent** status axes. The `adjudication_status` axis (the eligibility decision) runs `PENDING → ELIGIBLE`, `PENDING → INELIGIBLE`, or `PENDING → HELD`, and a held week can later go `HELD → ELIGIBLE` or `HELD → INELIGIBLE`. The `payment_status` axis (the disbursement state) runs `UNPAID → PAID`, then `PAID → OFFSET` when its benefit is later recouped, or `UNPAID → DENIED` when adjudication finds the week ineligible. These two axes move on different operations and are not coupled except where stated below.

**Work-search requirement.** When a certification is filed, the system computes `work_search_required`. It is true unless the week is exempt — exempt either because the claim carries an active emergency extension whose program waives work search, or because the operator marked the week with `work_search_waived`. When work search is required, the claimant must log activity. A `Claimant` or `ProgramAdmin` records a `WorkSearchContact` against the week by supplying its `contact_type` (one of `EMPLOYER_APPLICATION`, `INTERVIEW`, `JOB_FAIR`, or `REEMPLOYMENT_WORKSHOP`), the `contact_date`, and an optional `employer_id` naming the employer contacted (left null when the contact type is not an employer application). The `contact_date` must fall within the certification week — on or after the Sunday that opens the week and on or before the `week_ending_date` — and a contact dated outside that window is rejected with `ERR_UNTIMELY`.

**Adjudicating a week.** An `Adjudicator` adjudicates the eligibility axis by supplying a `decision` of `ELIGIBLE` or `INELIGIBLE`, optionally with `expected_weekly_certification_version`. Adjudication is permitted only when the week is in `PENDING` or `HELD`. Deciding a week `ELIGIBLE` requires three conditions, evaluated in this order: the parent claim must be `MONETARILY_ELIGIBLE`; the claimant must currently attest `is_able_and_available` true, failing which the decision is rejected with `ERR_NOT_ABLE_AVAILABLE`; and, when `work_search_required` is true, the number of `WorkSearchContact` rows logged for the week must be at least three, failing which the decision is rejected with `ERR_WORK_SEARCH_INSUFFICIENT`. A successful eligible decision sets `adjudication_status` to `ELIGIBLE` and increments the certification's `version`. Deciding a week `INELIGIBLE` (permitted from either `PENDING` or `HELD`) sets `adjudication_status` to `INELIGIBLE` and additionally sets `payment_status` to `DENIED`, then increments the `version`. Separately, an `Adjudicator` may place a `PENDING` week on hold pending a separation or availability investigation, which moves it `PENDING → HELD` and increments the `version`; the hold action accepts an optional `expected_weekly_certification_version`.

**Paying a week.** A `BenefitPaymentOfficer` disburses an eligible week, moving its `payment_status` from `UNPAID → PAID`. Payment is permitted only when the week's `payment_status` is `UNPAID`, its `adjudication_status` is `ELIGIBLE`, and the parent claim is `MONETARILY_ELIGIBLE`; the pay action accepts an optional `expected_weekly_certification_version`. At pay time the system computes the week's `payable_amount_cents` (Section 3.5.1). It additionally enforces that the claim is not already exhausted: paying a week against a claim whose `remaining_balance_cents` is 0 is rejected with `ERR_BALANCE_EXHAUSTED`. On success the system sets `payment_status` to `PAID`, debits the claim's `remaining_balance_cents` by the computed `payable_amount_cents`, allocates employer charges (Section 3.5.2), and increments the certification's `version`. If that debit drives `remaining_balance_cents` to exactly 0, the claim transitions `MONETARILY_ELIGIBLE → EXHAUSTED`, recomputing its balance (now 0) and incrementing the claim's `version`; a payment that leaves the balance above 0 keeps the claim `MONETARILY_ELIGIBLE`. The exhausted transition fires only at exactly 0.

#### 3.5.1. The Payable Amount and Earnings Disregard

A week's `payable_amount_cents` accounts for any wages the claimant earned that week through an earnings disregard. First compute the disregard: it is the larger of 5,000 cents and twenty-five percent of the claim's `weekly_benefit_amount_cents`, with that percentage resolved to whole cents using round-half-up. Next compute the countable earnings: the claimant's `reported_earnings_cents` for the week less the disregard, but never below 0. The gross payable is the `weekly_benefit_amount_cents` less the countable earnings, again never below 0. Finally, cap the gross payable by the claim's current `remaining_balance_cents`, so that a final partial week pays only what is left: `payable_amount_cents` is the smaller of the gross payable and the remaining balance. When the gross payable is at most the remaining balance, the week pays the gross payable in full; when the gross payable exceeds the remaining balance, the week pays exactly the remaining balance and that payment is what drives the claim to `EXHAUSTED`.

#### 3.5.2. Allocating Employer Charges

Paying a week charges the benefit back to the employers who built the claim's wage base. The system allocates the week's `payable_amount_cents` across the distinct base-period employers — the distinct `employer_id` values over the included base-period wage records of the claim's selected method (the same quarter set, non-disputed only) — in proportion to each employer's share of those non-disputed base-period wages. For each such employer, its raw share is the `payable_amount_cents` multiplied by that employer's wages divided by the total base-period wages; the integer floor of each raw share is the employer's provisional charge in whole cents. The cents left over — the `payable_amount_cents` less the sum of the floored shares — are distributed one cent at a time using the largest-remainder method, in this tie-break order: first to the employers with the largest fractional remainders, descending; then, among equal remainders, to the employer with the larger base-period wages, descending; and finally, among still-equal employers, to the one with the earlier `created_at`, ascending (never by `id`). Each leftover cent raises one employer's charge by one, so the sum of all `charge_amount_cents` equals the `payable_amount_cents` exactly. When there is only a single base-period employer, that employer is charged the full `payable_amount_cents` with no remainder step.

For each allocated employer the system creates an `EmployerCharge` naming the `employer_id` charged and the `weekly_certification_id` that generated it, with the computed `charge_amount_cents`, in `POSTED` status and with `relief_reason` null. The charges are created in a deterministic order — by the charged employer's `created_at` ascending, then by employer insertion order for any tie — so the charges' own `created_at` stamps (and hence the default `created_at`-ascending ordering of any list of them) follow that same employer order. Posting a charge debits that employer's `reserve_account_balance_cents` by the `charge_amount_cents`.

### 3.6. Exhaustion, Emergency Extensions, and Closing a Claim

When a claim reaches `EXHAUSTED`, its regular entitlement is spent. An emergency program can restore balance. An `Adjudicator` applies an extension to an exhausted claim by supplying the `program_id` and the required `expected_claim_version`. The apply is permitted only when the claim is `EXHAUSTED`, when the claim's `emergency_extension_id` is still null (a claim that already has an extension applied is rejected with `ERR_EXTENSION_ALREADY_APPLIED`), and when the candidate program covers the claim. A program covers the claim only when the program's `is_active` is true and the claim's `filed_date` falls on or after the program's `trigger_start_date` and on or before its `trigger_end_date` — both boundaries inclusive, so a `filed_date` falling exactly on either trigger date still qualifies, while a `filed_date` one day outside either boundary, or a program that is not active, is rejected with `ERR_EXTENSION_WINDOW`.

A successful apply sets the claim's `emergency_extension_id` to the program and `extension_weeks_granted` to the program's `extra_weeks`, recomputes `maximum_benefit_amount_cents` by adding the product of `extension_weeks_granted` and the weekly benefit amount to the base maximum, recomputes `remaining_balance_cents` (now above 0 again), and transitions the claim `EXHAUSTED → MONETARILY_ELIGIBLE` so further weeks can be paid. The claim's `version` increments. Because an extension supersedes the claim's prior balance baseline, this operation is protected by the mandatory `expected_claim_version` concurrency check of Section 2.6, and weeks on a claim carrying a work-search-waiving extension have their `work_search_required` computed as false.

An `Adjudicator` may also close a claim, transitioning it to `CLOSED`. Closing is permitted from `MONETARILY_ELIGIBLE` or `EXHAUSTED`, but only when no `WeeklyCertification` on the claim is currently in `adjudication_status` `HELD` — an outstanding held week blocks closure. The close action accepts an optional `expected_claim_version` and increments the claim's `version`. `CLOSED` is terminal.

### 3.7. Appeals and the Reversal Cascade

Any determination that is appealable may be appealed. A `Claimant`, `Employer`, or `ProgramAdmin` files an `Appeal` by supplying the `determination_id`, the `filed_by` party (`CLAIMANT` or `EMPLOYER`), and the `filed_date`. The appeal is timely only when its `filed_date` is on or before the determination's `appeal_deadline_date`, which the system computed as the determination's creation date plus 30 days; an appeal filed after that deadline is rejected with `ERR_UNTIMELY`. A new appeal is created in `SUBMITTED` status with `remand_count` 0 and `assigned_referee_id` null.

The appeal then moves through a docketing and review cycle. An `AppealsClerk` assigns a referee, supplying the `assigned_referee_id`; this moves the appeal `SUBMITTED → UNDER_REVIEW` (and is also the move that brings a remanded appeal `REMANDED → UNDER_REVIEW`). Assignment is permitted only from `SUBMITTED` or `REMANDED`, and the supplied `assigned_referee_id` must differ from the `issuing_adjudicator_id` of the appealed determination; assigning the issuing adjudicator is rejected with `ERR_SEGREGATION_OF_DUTIES`. An `AppealsClerk` may instead dismiss a submitted appeal, moving it `SUBMITTED → DISMISSED`; dismissal is the disposition for an appeal whose `filed_date` is after the determination's `appeal_deadline_date`. Both assign and dismiss accept an optional `expected_appeal_version`.

A `Referee` works an appeal that is under review. The referee may remand it for further fact-finding, moving it `UNDER_REVIEW → REMANDED`, incrementing `remand_count` by one; an appeal may be remanded at most twice, so a remand attempted when `remand_count` already equals 2 is rejected with `ERR_REMAND_LIMIT`. The referee decides an appeal under review by supplying a `ruling` of `AFFIRM` or `REVERSE`. Affirming moves it `UNDER_REVIEW → DECIDED_AFFIRMED` and leaves the appealed determination's outcome unchanged. Reversing moves it `UNDER_REVIEW → DECIDED_REVERSED`, sets the appealed determination's `outcome` to `REVERSED` and its `is_appealable` to false. An appeal may also be withdrawn — by a `Referee`, a `Claimant`, or an `Employer` — from either `SUBMITTED` or `UNDER_REVIEW`, moving it to `WITHDRAWN`. Each of these transitions increments the appeal's `version`, and the remand, decide, and withdraw actions accept an optional `expected_appeal_version`. The states `DECIDED_AFFIRMED`, `DECIDED_REVERSED`, `WITHDRAWN`, and `DISMISSED` are terminal.

**The reversal cascade.** A `DECIDED_REVERSED` ruling can reach across entity boundaries. When the reversed determination was a `MONETARY` determination that had been `DENIED`, reversing it flips the parent claim back to eligibility: the claim transitions `MONETARILY_INELIGIBLE → MONETARILY_ELIGIBLE`, the monetary calculations are re-run to set the claim's `weekly_benefit_amount_cents`, `maximum_benefit_amount_cents`, and `remaining_balance_cents`, the appealed determination's `outcome` becomes `REVERSED` with `is_appealable` false, and the claim's `version` increments. When the reversed determination was instead a `NONMONETARY` determination, the reversal does not automatically re-pay any week — an operator must re-adjudicate the affected weeks — though the determination is still marked `REVERSED` and no longer appealable.

### 3.8. Overpayments and Recovery

When benefits are paid in error, an `Adjudicator` establishes an `Overpayment` against a claim by supplying the `claim_id`, the `cause` (`FRAUD` or `NONFRAUD`), and the `principal_cents` (which must be greater than 0). At establishment the system computes the penalty: for a `FRAUD` overpayment, `penalty_cents` is fifteen percent of the `principal_cents`, resolved to whole cents using round-half-up; for a `NONFRAUD` overpayment, `penalty_cents` is 0. The `total_assessed_cents` is the `principal_cents` plus the `penalty_cents` — strictly greater than the principal for fraud, and equal to the principal for non-fraud. A new overpayment is created in `ESTABLISHED` status with `recovered_cents` 0.

A `BenefitPaymentOfficer` records recoveries that chip away at the balance. An `OverpaymentRecovery` is created against an overpayment by supplying the `overpayment_id` of the target overpayment, the `recovery_method` (`OFFSET` or `CASH`), the `amount_cents` (which must be greater than 0), the required `expected_overpayment_version`, and — for an offset — the `weekly_certification_id` of the paid week whose benefit is being recouped (left null for a cash repayment). The `weekly_certification_id` is required when `recovery_method` is `OFFSET`; its absence on an offset is rejected with `ERR_INVALID_REQUEST`. Whenever a `weekly_certification_id` is supplied (under either method), it must name an existing `WeeklyCertification` or the request is rejected with `ERR_NOT_FOUND`. A recovery is created with its `status` field at `APPLIED`, the only value a recovery's `status` ever takes; the recovery ledger is append-only and carries no reversal action. Each applied recovery adds its `amount_cents` to the overpayment's `recovered_cents`. A recovery whose `amount_cents` would push `recovered_cents` above `total_assessed_cents` is rejected with `ERR_OVER_RECOVERY` — recoveries may bring the running total up to the assessed total exactly, but never past it.

The overpayment's status follows the running balance. The first recovery against an `ESTABLISHED` overpayment that leaves `recovered_cents` still below `total_assessed_cents` moves it `ESTABLISHED → RECOVERING`; subsequent recoveries that still leave a balance keep it `RECOVERING → RECOVERING`. A recovery that brings `recovered_cents` to exactly `total_assessed_cents` moves the overpayment to `SATISFIED` — whether that satisfying recovery arrives from `ESTABLISHED` (a single recovery equal to the whole assessed total) or from `RECOVERING`. Satisfaction requires hitting the assessed total exactly; combined with the over-recovery rule, this means the ledger is driven to balance to the cent. When the recovery's `recovery_method` is `OFFSET`, the referenced `WeeklyCertification` has its `payment_status` cascaded `PAID → OFFSET` (its adjudication axis stays `ELIGIBLE` — the two axes move independently). Every recovery increments the overpayment's `version`, and because each one supersedes the prior recovered total, the operation is guarded by the mandatory `expected_overpayment_version` check of Section 2.6.

Alternatively, an `Adjudicator` may waive an overpayment, moving it `ESTABLISHED → WAIVED`. Waiver is permitted only when the overpayment's `cause` is `NONFRAUD` and its `recovered_cents` is 0 — a fraud overpayment can never be waived, and one with any recovery already applied can no longer be waived; either condition is rejected with `ERR_WAIVER_NOT_ALLOWED`. The waive action accepts an optional `expected_overpayment_version`. `SATISFIED` and `WAIVED` are terminal.

### 3.9. Employer Charges: Protest and Relief

An employer that disagrees with a charge can protest it. The owning `Employer` — the one whose `employer_id` matches the charge and whose `X-User-ID` equals that `employer_id` — protests a posted charge, moving it `POSTED → PROTESTED`. A protest by an `Employer` whose `X-User-ID` does not equal the charge's `employer_id` is rejected with `ERR_FORBIDDEN_ROLE`, evaluated after the charge's existence (`ERR_NOT_FOUND`) but before the `POSTED` state check. Protesting increments that employer's `charge_protest_count` by one and increments the charge's `version`; the protest action accepts an optional `expected_employer_charge_version`. An `Adjudicator` then relieves a protested charge by supplying a `relief_reason` (one of `QUIT_WITHOUT_CAUSE`, `MISCONDUCT_DISCHARGE`, or `CONTINUING_WORK`), moving it `PROTESTED → RELIEVED`. Relief records the `relief_reason`, credits the employer's `reserve_account_balance_cents` back by the charge's `charge_amount_cents` — reversing the original posting debit so the reserve returns to exactly its pre-charge value — decrements the employer's `charge_protest_count` by one, and increments the charge's `version`; the relieve action accepts an optional `expected_employer_charge_version`. `RELIEVED` is terminal.

### 3.10. Administrative Test-Driving Capabilities

Two administrative capabilities exist to make otherwise long-running fixtures tractable, both restricted to a `ProgramAdmin`. A balance-setting capability directly sets a `MONETARILY_ELIGIBLE` claim's `remaining_balance_cents` to a supplied target by accepting a `claim_id` and a `remaining_balance_cents` value; the target must be at least 0 (a negative value is malformed input, `ERR_INVALID_REQUEST`) and at most the claim's `maximum_benefit_amount_cents` (a target exceeding the maximum is rejected with `ERR_INVALID_REQUEST`). The claim must be `MONETARILY_ELIGIBLE` — a call against a claim in any other status is rejected with `ERR_INVALID_STATE`, and that state check is applied after the `remaining_balance_cents` field-shape check but before the at-most-maximum check. This capability does not change the claim's status or its version-gated monetary fields, but it does increment the claim's `version`. A clock-setting capability sets the server's notion of "now" in UTC by accepting a `to_iso8601` instant; all subsequent `created_at` and `updated_at` stamps and all date-derived computed fields — notably a determination's `appeal_deadline_date`, which is its creation date plus 30 days — use that instant until it is reset, defaulting to wall-clock time when never set.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state-transition actions and PATCH updates — return `200 OK`. The clock-setting capability returns `200 OK` with an empty data object. Refer to Section 3 for the request body, computed effects, and cascades of each operation; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ui/employers` | Register an employer with an opening reserve balance | ProgramAdmin |
| GET | `/ui/employers/{id}` | Fetch an employer | ProgramAdmin, Adjudicator, Employer |
| GET | `/ui/employers` | List employers | ProgramAdmin, Adjudicator |
| GET | `/ui/employers/{id}/charges` | List charges for an employer | ProgramAdmin, Adjudicator, Employer |
| GET | `/ui/employers/{id}/wage-records` | List wage records reported under an employer | ProgramAdmin, Adjudicator |
| GET | `/ui/employers/{id}/work-search-contacts` | List work-search contacts naming an employer | ProgramAdmin, Adjudicator |
| POST | `/ui/claimants` | Register a claimant | Anonymous, ProgramAdmin |
| GET | `/ui/claimants/{id}` | Fetch a claimant | ProgramAdmin, Adjudicator, Claimant |
| GET | `/ui/claimants/{id}/wage-records` | List a claimant's wage records | ProgramAdmin, Adjudicator, Claimant |
| PATCH | `/ui/claimants/{id}` | Update claimant able-and-available attestation | ProgramAdmin, Claimant |
| POST | `/ui/wage-records` | Report quarterly wages | ProgramAdmin, Employer |
| GET | `/ui/wage-records` | List wage records (filter by claimant_id and/or employer_id) | ProgramAdmin, Adjudicator |
| PATCH | `/ui/wage-records/{id}` | Mark a wage record disputed/undisputed | ProgramAdmin, Employer |
| POST | `/ui/claims` | Open a draft claim | Claimant, ProgramAdmin |
| GET | `/ui/claims/{id}` | Fetch a claim | ProgramAdmin, Adjudicator, Claimant |
| GET | `/ui/claims` | List claims (filter by claimant_id and/or emergency_extension_id) | ProgramAdmin, Adjudicator |
| POST | `/ui/claims/{id}/submit` | Submit a draft claim for adjudication | Claimant, ProgramAdmin |
| POST | `/ui/claims/{id}/apply-extension` | Apply an emergency extension to an exhausted claim | Adjudicator |
| POST | `/ui/claims/{id}/close` | Close a claim | Adjudicator |
| POST | `/ui/determinations` | Issue a determination on a claim | Adjudicator |
| GET | `/ui/determinations/{id}` | Fetch a determination | ProgramAdmin, Adjudicator, Claimant, Employer |
| GET | `/ui/claims/{id}/determinations` | List determinations for a claim | ProgramAdmin, Adjudicator, Claimant |
| POST | `/ui/weekly-certifications` | File a weekly certification | Claimant, ProgramAdmin |
| GET | `/ui/weekly-certifications/{id}` | Fetch a weekly certification | ProgramAdmin, Adjudicator, Claimant, BenefitPaymentOfficer |
| GET | `/ui/claims/{id}/weekly-certifications` | List weekly certifications for a claim | ProgramAdmin, Adjudicator, Claimant, BenefitPaymentOfficer |
| POST | `/ui/weekly-certifications/{id}/work-search-contacts` | Log a work-search contact | Claimant, ProgramAdmin |
| GET | `/ui/weekly-certifications/{id}/work-search-contacts` | List work-search contacts for a week | ProgramAdmin, Adjudicator, Claimant |
| POST | `/ui/weekly-certifications/{id}/adjudicate` | Adjudicate the eligibility axis of a week | Adjudicator |
| POST | `/ui/weekly-certifications/{id}/hold` | Place a pending week on hold | Adjudicator |
| POST | `/ui/weekly-certifications/{id}/pay` | Disburse benefit for an eligible week | BenefitPaymentOfficer |
| GET | `/ui/employer-charges/{id}` | Fetch an employer charge | ProgramAdmin, Adjudicator, Employer |
| GET | `/ui/weekly-certifications/{id}/employer-charges` | List charges generated by a paid week | ProgramAdmin, Adjudicator, Employer |
| POST | `/ui/employer-charges/{id}/protest` | Protest a posted charge | Employer |
| POST | `/ui/employer-charges/{id}/relieve` | Relieve a protested charge | Adjudicator |
| POST | `/ui/overpayments` | Establish an overpayment against a claim | Adjudicator |
| GET | `/ui/overpayments/{id}` | Fetch an overpayment | ProgramAdmin, Adjudicator, Claimant, BenefitPaymentOfficer |
| GET | `/ui/claims/{id}/overpayments` | List overpayments for a claim | ProgramAdmin, Adjudicator, Claimant, BenefitPaymentOfficer |
| POST | `/ui/overpayments/{id}/recoveries` | Apply a recovery toward an overpayment | BenefitPaymentOfficer |
| GET | `/ui/overpayments/{id}/recoveries` | List recoveries for an overpayment | ProgramAdmin, Adjudicator, BenefitPaymentOfficer |
| GET | `/ui/weekly-certifications/{id}/recoveries` | List recoveries that offset a paid week | ProgramAdmin, Adjudicator, BenefitPaymentOfficer |
| POST | `/ui/overpayments/{id}/waive` | Waive a non-fraud overpayment | Adjudicator |
| POST | `/ui/appeals` | File an appeal of a determination | Claimant, Employer, ProgramAdmin |
| GET | `/ui/appeals/{id}` | Fetch an appeal | ProgramAdmin, Adjudicator, Referee, AppealsClerk, Claimant, Employer |
| GET | `/ui/determinations/{id}/appeals` | List appeals of a determination | ProgramAdmin, Adjudicator, Referee, AppealsClerk |
| POST | `/ui/appeals/{id}/assign` | Assign a referee to an appeal | AppealsClerk |
| POST | `/ui/appeals/{id}/dismiss` | Dismiss an untimely appeal | AppealsClerk |
| POST | `/ui/appeals/{id}/remand` | Remand an appeal under review | Referee |
| POST | `/ui/appeals/{id}/withdraw` | Withdraw an appeal | Referee, Claimant, Employer |
| POST | `/ui/appeals/{id}/decide` | Decide an appeal (affirm or reverse) | Referee |
| POST | `/ui/extension-programs` | Create an emergency extension program | ProgramAdmin |
| GET | `/ui/extension-programs/{id}` | Fetch an extension program | ProgramAdmin, Adjudicator |
| PATCH | `/ui/extension-programs/{id}` | Toggle a program's active flag | ProgramAdmin |
| POST | `/_ledger/set_claim_balance` | Test hook: set a claim's remaining balance | ProgramAdmin |
| POST | `/_clock/set_current_utc` | Test hook: set the server clock | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REFERENCE` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_UNTIMELY` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_WORK_SEARCH_INSUFFICIENT` | 422 |
| `ERR_NOT_ABLE_AVAILABLE` | 422 |
| `ERR_WAIVER_NOT_ALLOWED` | 422 |
| `ERR_OVER_RECOVERY` | 422 |
| `ERR_BALANCE_EXHAUSTED` | 422 |
| `ERR_REMAND_LIMIT` | 422 |
| `ERR_EXTENSION_WINDOW` | 422 |
| `ERR_EXTENSION_ALREADY_APPLIED` | 409 |
| `ERR_NO_QUALIFYING_WAGES` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_STALE_OVERPAYMENT_VERSION` | 412 |
