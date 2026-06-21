# Ltc Insurance Administration API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Long-Term Care (LTC) Insurance Administration API, a back-office platform that carriers, regulators, and the insured share to administer the full lifecycle of an LTC policy. The domain is unusually demanding: a single policy must track two parallel realities at once — whether coverage is in force and whether premium is current — and the two evolve independently. Layered on top of that are benefit pools that grow with inflation riders, elimination periods that must be self-paid before any benefit is owed, clinical benefit triggers based on activities of daily living, and two structurally different ways of paying a claim (reimbursing actual charges versus paying a flat indemnity amount).

The platform's hardest problems are reconciliation problems. Every approved claim draws down a lifetime benefit pool, advances elimination-period satisfaction, and — for state-qualified partnership policies — shields an equal dollar of the insured's assets from Medicaid spend-down. A lapse can quietly convert into a paid-up, reduced-benefit policy rather than terminating coverage outright. Rate-increase filings must clear a regulator before they reprice future premiums. Because several of these operations race against each other on the same policy, the system relies on optimistic concurrency to keep two writers from clobbering each other's view of the benefit pool. This specification describes every entity, state machine, calculation, and guard rail that an implementation must honor so that the ledger always reconciles and no benefit is ever paid twice.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they act. If either header is missing or malformed — absent, empty (or whitespace-only), or, for `X-User-Role`, a value that is not one of the five recognized roles — the request is rejected with `ERR_UNAUTHENTICATED`. Only once both headers are well-formed (and the role is one of the five) but the declared role is not permitted to perform the requested operation is the request rejected with `ERR_UNAUTHORIZED`.

The system recognizes five roles, spelled exactly as follows: `Underwriter`, `ClaimsExaminer`, `CareAssessor`, `Regulator`, and `Policyholder`. The `Underwriter` is the carrier's administrative authority — it registers insured persons, creates and issues policies, files and withdraws rate increases, generates premium invoices, applies inflation anniversaries, and drives the test clock. The `ClaimsExaminer` adjudicates claims end to end and waives premium once a claim is active. The `CareAssessor` is the clinical and eligibility authority — it records benefit-trigger certifications, manages providers, and authors and activates plans of care. The `Regulator` adjudicates rate-increase filings. The `Policyholder` is the insured.

Four of these roles carry an opaque identity: when `X-User-Role` is `Underwriter`, `ClaimsExaminer`, `CareAssessor`, or `Regulator`, the accompanying `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier — for example, a benefit-trigger certification stores the assessing operator's identifier in `assessed_by_id`, and a care plan stores its author's identifier in `authored_by_id` — but it never compares that identifier to any entity's `id`. The `Policyholder` role is different: it is entity-backed. When `X-User-Role` is `Policyholder`, `X-User-ID` is understood to be the `id` of the acting `Policyholder` record. In practice, however, no endpoint performs a cross-resource ownership comparison: once a `Policyholder`-role request passes authentication and the role-based authorization for the operation, it is allowed to proceed regardless of whether the `X-User-ID` matches the policyholder that the target resource traces back to. The acting `X-User-ID` is therefore accepted as the policyholder's identity but is never validated against any resource's policyholder linkage.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the front of the result set and defaults to 0; its only bound is that it must be non-negative (there is no upper limit on `offset`). A request that supplies a `limit` or `offset` outside its permitted bounds — a `limit` below 1 or above 100, a negative `offset`, or either value that is not a parseable integer — is rejected with `ERR_VALIDATION_CONFLICT`.

Unless an endpoint explicitly states otherwise, list results are sorted by `created_at` in ascending order. The one deliberate exception is the listing of benefit-trigger certifications for a policy, which is ordered newest first so that the most recent assessment is read first.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in this system are mutable, system-managed records and carry a standard set of common fields. Such resources expose an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits, fixed at creation), an `updated_at` timestamp (same format, refreshed on every mutation), and a `version` (an integer that starts at 1 and increments by 1 on each mutation). The entities that carry this full set are `Policyholder`, `Policy`, `BenefitPool`, `PremiumInvoice`, `RateIncreaseFiling`, `Provider`, `CarePlan`, `Claim`, `ClaimLine`, and `PartnershipDisregard`.

Two entities are append-only event records and deliberately omit `updated_at` and `version` entirely: a `BenefitTriggerCertification` and a `BenefitLedgerEntry` each carry only an `id` and a `created_at`. They are never mutated after creation; corrections happen by appending a new record rather than editing an old one.

Whenever a mutation touches a resource that carries a `version`, the server refreshes that resource's `updated_at` and increments its `version`. This includes derived-field recomputations: when an approved claim drives a recalculation of the benefit pool, for instance, the affected `Policy` records the change through its `updated_at` and `version` just as a direct edit would.

### 2.5. Optimistic Concurrency on the Policy

Several writes against a `Policy` must guard against a stale read, because the policy's benefit pool and coverage posture can shift underneath a client between the moment it reads and the moment it writes. These writes carry a non-optional `expected_policy_version` field in their request body and are validated against the policy's current `version`.

The first guarded write is opening a claim. A claim-open request must carry `expected_policy_version` holding the client's last observed `version` of the target `Policy`. If another writer has advanced the policy's `version` since that read — for example, by approving a claim that drew down the benefit pool and possibly pushed coverage toward `EXHAUSTED` — the mismatch means the requesting client's view of the remaining pool and `coverage_status` is stale, and the open is rejected with `ERR_STALE_VERSION` at HTTP 412.

The same protection guards claim approval, claim denial, and rate-filing adjudication: each of these requests carries `expected_policy_version`, and each is rejected with `ERR_STALE_VERSION` (HTTP 412) when the supplied value does not equal the policy's current `version`. In the adjudication case, the staleness that matters is a competing filing that has already been approved and recomputed the same open invoices, leaving this regulator acting on an out-of-date premium baseline. Endpoints other than these four take no version field and perform no concurrency check.

### 2.6. Hierarchical Consistency and Cascades

Many operations in this domain mutate more than one entity in a single atomic request, and all such cascades complete inside the triggering request — there are no deferred or eventual updates. When a provider is suspended, every active plan of care that names it is closed, and every non-terminal claim drawing on one of those closed plans is voided, all within the suspend request. When a claim is approved, the benefit pool, the policy's elimination-period progress, and (where applicable) the partnership asset shield are all recomputed before the response is returned. When a premium lapses past its grace deadline, the policy's premium posture, the benefit pool, and the partnership accrual may all move together. Each entity touched by a cascade independently records the change through its `updated_at` and, where it carries one, its `version`. The specific cascades are described with the workflows that trigger them in Section 3.

### 2.7. Nested Resource Retrieval and Existence Ordering

Several read and write paths reference a parent resource by `id` and then a child collection beneath it — for instance, the service-day lines under a claim, or the trigger certifications under a policy. For any such request, identifiers are validated left to right along the path: the parent must be confirmed to exist before any child is considered. The first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND`. After the path is validated, any foreign-key identifiers supplied in the body are checked for existence in the same way, and a missing referent likewise yields `ERR_NOT_FOUND`.

### 2.8. Monetary Precision, Inflation Rounding, and Counts

All money in this system is stored and exchanged as integer cents — there are no fractional cents and no floating-point currency anywhere in a stored field or a response body. Benefit caps, billed charges, premiums, pool balances, and ledger deltas are all whole cents. Because charges and caps are integers, the claim payout calculation needs no rounding step at all; it works purely in integer cents.

Two calculations, however, do involve a percentage and therefore a rounding decision. Premium re-rating multiplies a base premium by a whole-percent factor and rounds the result half-up to the nearest cent in a single rounding step. Inflation growth is more delicate: it compounds year by year and rounds half-up to the nearest cent once per year, in ascending year order, before the next year's multiplication — never by summing first or rounding only at the end. Wherever this document refers to rounding, it means round half-up to the nearest integer cent.

Counts are integers: the number of distinct qualifying service days credited toward an elimination period is a whole-day count, never negative and never larger than the policy's configured elimination period; the count of distinct activity-of-daily-living deficiencies is likewise a whole number.

### 2.9. The Parallel Policy State Model

A `Policy` is unusual in that it tracks two independent state axes on the same record. The `coverage_status` axis describes whether and how coverage is in force, moving through `APPLIED`, `IN_FORCE`, `CLAIM_OPEN`, and the terminal states `EXHAUSTED` and `RESCINDED`. The `premium_status` axis describes the billing relationship, moving through `PENDING`, `PAID_CURRENT`, `GRACE`, and the outcomes `LAPSED`, `NONFORFEITURE_PAID_UP`, and `WAIVED`. The two axes evolve independently: paying a premium never changes coverage, and approving a claim never changes the premium posture. A policy is created with `coverage_status` of `APPLIED` and `premium_status` of `PENDING` simultaneously. The transitions that move each axis, and their preconditions, are detailed in Section 3.

### 2.10. Reimbursement Versus Indemnity

The single most consequential configuration choice on a policy is its `product_mode`, which is either `REIMBURSEMENT` or `INDEMNITY` and is immutable after issue. The two modes pay an identical claim line differently: an indemnity policy pays the full daily benefit ceiling for every qualifying day regardless of what the provider actually charged, letting the insured keep any difference, whereas a reimbursement policy pays only the lesser of the billed charge and the daily ceiling. This distinction is woven into the claim payout calculation in Section 3 and is the primary reason the same claim can settle for two very different amounts.

## 3. Business Logic & Workflows

### 3.1. Insured Persons, Policy Applications, and Issue

The chain begins with an insured person. An `Underwriter` registers a `Policyholder` by supplying the insured's legal name as `full_name`, the two-letter residence state as `state_code`, the `date_of_birth` as an ISO 8601 date, and an optional `medicaid_state_eligible` flag indicating whether the residence state runs a qualified LTC Partnership program; that flag defaults to false when omitted.

The same operator then files a policy application against an existing policyholder, supplying the `policyholder_id` of the insured, the `product_mode`, the per-service-day ceiling `daily_benefit_max_cents`, the per-calendar-month ceiling `monthly_benefit_max_cents`, the lifetime `initial_pool_cents`, the `inflation_rider`, the `elimination_period_days` that must be self-paid before benefits begin, and an optional `is_partnership_policy` flag that defaults to false. The `inflation_rider` is one of `NONE`, `COMPOUND_3PCT`, or `COMPOUND_5PCT`. A freshly created policy sits in `coverage_status` `APPLIED` and `premium_status` `PENDING`, with `inflation_years_elapsed` at 0. If the application is marked as a partnership policy, the system also creates a `PartnershipDisregard` record for it in `disregard_status` `ACCRUING` with `protected_asset_cents` at 0.

Issuing the policy advances `coverage_status` from `APPLIED` to `IN_FORCE`; it is restricted to an `Underwriter` and requires the policy to currently be in `APPLIED`, failing with `ERR_INVALID_STATE` otherwise. Issuing is also the moment the policy's lifetime ledger is born: the system creates the policy's `BenefitPool` with `lifetime_paid_cents` and `nonforfeiture_reduction_cents` both at 0, linked to the policy through its `policy_id`. The premium axis is untouched by issue and remains `PENDING`. Alternatively, an `Underwriter` may rescind a still-`APPLIED` policy, moving `coverage_status` from `APPLIED` to the terminal `RESCINDED`; rescission also requires the `APPLIED` state and otherwise fails with `ERR_INVALID_STATE`. Both issue and rescission increment the policy's `version`.

A policy read returns not only its stored configuration but its computed view: `inflated_daily_max_cents`, `inflated_monthly_max_cents`, the boolean `benefits_triggered`, and the integer `elimination_days_satisfied`, all derived as described below.

### 3.2. Inflation Growth and Anniversaries

Inflation protection grows the policy's three monetary bases — the daily ceiling, the monthly ceiling, and the lifetime pool — over time. The growth rate is governed by the rider: a `NONE` rider grows nothing (rate of 0), a `COMPOUND_3PCT` rider grows at three percent per year (rate of 0.03), and a `COMPOUND_5PCT` rider grows at five percent per year (rate of 0.05). The number of growth years applied is held in `inflation_years_elapsed`.

Growth is compounded one year at a time with rounding pinned to each step. Starting from a base in cents, the system multiplies by one plus the rate and rounds the product half-up to the nearest cent, then repeats that multiply-and-round for each elapsed year in turn, always rounding before the next year's multiplication. The grown daily ceiling is exposed as `inflated_daily_max_cents`, the grown monthly ceiling as `inflated_monthly_max_cents`, and the grown lifetime pool, less any nonforfeiture reduction, as `inflated_pool_cents` on the policy's `BenefitPool`. Summing across years first, or rounding only once at the very end, produces different cents and is incorrect.

An `Underwriter` advances inflation through an anniversary operation that adds exactly one to `inflation_years_elapsed`, recomputes the inflated maxima and pool, and appends an `INFLATION_GROWTH` entry to the benefit ledger whose `amount_cents` is the positive increase in the pool's `inflated_pool_cents` produced by this one year of growth (the after-growth `inflated_pool_cents` minus the before-growth value, or 0 when no `BenefitPool` exists yet); the policy's `version` is incremented. An anniversary may be applied only while `coverage_status` is `IN_FORCE` or `CLAIM_OPEN`; applying it to a policy in any other coverage state is rejected with `ERR_ANNIVERSARY_NOT_IN_FORCE`.

### 3.3. Benefit Triggers: The Two-of-Six Assessment

Before any claim can be approved or even opened, the policy's benefit trigger must be satisfied — the clinical determination that the insured genuinely needs long-term care. A `CareAssessor` records this determination as a `BenefitTriggerCertification` against a policy, supplying the `adl_deficiencies` array (the subset of the six activities of daily living the insured cannot perform), an optional `cognitive_impairment` flag defaulting to false, and an optional `supersedes_id` naming the prior certification this re-assessment replaces (null for the first). The recording operator's identifier is captured in `assessed_by_id`.

The six recognized activities of daily living are `BATHING`, `DRESSING`, `TOILETING`, `TRANSFERRING`, `CONTINENCE`, and `EATING`. The system counts the distinct valid activities present in `adl_deficiencies`, ignoring duplicates and any token outside that set of six. The resulting `decision` is `CERTIFIED` when that distinct count is at least two, or when `cognitive_impairment` is true; otherwise it is `NOT_CERTIFIED`. The threshold is inclusive at two: a single activity with no cognitive impairment yields `NOT_CERTIFIED`, while exactly two activities yield `CERTIFIED`. A policy's computed `benefits_triggered` flag is true precisely when the latest certification recorded for that policy carries a `decision` of `CERTIFIED`; recording a fresh certification recomputes that flag from the most recent record.

Certifications form an append-only history. They can be listed for a policy newest-first, read individually, or listed across the system filtered by `policy_id` and by `supersedes_id`.

### 3.4. Providers and Plans of Care

Care is delivered by a `Provider`, registered by a `CareAssessor` with a `name`, a `provider_type`, the licensing `state_code`, and an optional `license_active` flag defaulting to true. The provider type is one of `NURSING_HOME`, `ASSISTED_LIVING`, `HOME_HEALTH_AGENCY`, `ADULT_DAY_CARE`, or `INFORMAL_CAREGIVER`. A new provider begins in `eligibility_status` `PENDING`.

A `CareAssessor` certifies a provider, moving `eligibility_status` to `ELIGIBLE`. Certification is permitted from `PENDING` or from `SUSPENDED`, and in both cases requires that the provider's `license_active` be true; a certification attempt against a provider whose license is inactive is rejected with `ERR_PROVIDER_LICENSE_INACTIVE`, and an attempt from a state other than `PENDING` or `SUSPENDED` fails with `ERR_INVALID_STATE`. A `PENDING` provider may instead be rejected, moving it to the terminal `INELIGIBLE` (valid only from `PENDING`, else `ERR_INVALID_STATE`). An `ELIGIBLE` provider may be suspended back to `SUSPENDED` (valid only from `ELIGIBLE`, else `ERR_INVALID_STATE`); suspension carries a cascade described in Section 3.8.

A plan of care binds a policy to a provider. A `CareAssessor` authors a `CarePlan` against a `policy_id` and a `provider_id`, declaring a `care_setting` that is one of `NURSING_HOME`, `ASSISTED_LIVING`, `HOME_HEALTH`, `ADULT_DAY`, or `INFORMAL`. The authoring operator's identifier is stored in `authored_by_id`, and the plan begins in `status` `DRAFT`. Activating a plan moves it from `DRAFT` to `ACTIVE` and requires two business checks beyond the state itself: the named provider's `eligibility_status` must be `ELIGIBLE`, failing with `ERR_PROVIDER_NOT_ELIGIBLE`, and the plan's `care_setting` must be compatible with the provider's `provider_type`, failing with `ERR_CARE_SETTING_MISMATCH`. The compatibility pairing is one-to-one across the naming convention: `NURSING_HOME` setting with `NURSING_HOME` provider, `ASSISTED_LIVING` with `ASSISTED_LIVING`, `HOME_HEALTH` with `HOME_HEALTH_AGENCY`, `ADULT_DAY` with `ADULT_DAY_CARE`, and `INFORMAL` with `INFORMAL_CAREGIVER`. Activating a plan supersedes the policy's prior plan: any other plan for the same policy currently in `ACTIVE` is moved to the terminal `SUPERSEDED`. A `CareAssessor` may also close an `ACTIVE` plan directly, moving it to the terminal `CLOSED` (valid only from `ACTIVE`, else `ERR_INVALID_STATE`). Plans can be listed filtered by `policy_id` and by `provider_id`.

### 3.5. Opening a Claim and Adding Service Days

A claim represents one calendar month of care. A `ClaimsExaminer` opens a `Claim` by supplying the `policy_id`, the `care_plan_id` of the active plan authorizing the services, the `service_month` as an ISO 8601 year-month, and `expected_policy_version`. The service month must be unique for the policy — opening a second claim for a month already claimed on that policy is rejected with `ERR_DUPLICATE_SERVICE_PERIOD`, and this duplicate-month check is evaluated before the coverage-state check below, so re-opening an already-claimed month on a policy that is currently `CLAIM_OPEN` reports `ERR_DUPLICATE_SERVICE_PERIOD` rather than `ERR_INVALID_STATE`. Four further conditions then guard the open, in this fixed order: the policy's coverage must be `IN_FORCE`, else `ERR_INVALID_STATE`; the policy's `premium_status` must be one of `PAID_CURRENT`, `WAIVED`, or `NONFORFEITURE_PAID_UP` — a premium that is not current blocks the open with `ERR_PREMIUM_NOT_CURRENT`; the policy's `benefits_triggered` must be true, else `ERR_BENEFITS_NOT_TRIGGERED`; and finally `expected_policy_version` must match the policy's current `version`, else `ERR_STALE_VERSION`. The first claim opened against an in-force policy flips `coverage_status` from `IN_FORCE` to `CLAIM_OPEN`; the open increments the policy's `version`. A fresh claim begins in `status` `SUBMITTED` with `month_paid_cents` at 0 and `requires_reassessment` false.

Service days are then attached to a `SUBMITTED` claim as `ClaimLine` records. Each line carries the `service_date` of the single day it bills, the `billed_charge_cents` (the actual provider charge, used only in reimbursement mode), and an optional `is_qualifying_day` flag defaulting to true that marks the day as an eligible LTC service day. A line's `service_date` must fall inside the claim's `service_month` — that is, the date's year-month prefix must match — otherwise the line is rejected with `ERR_SERVICE_DATE_OUT_OF_MONTH`. The `service_date` must also be unique within the claim; a second line for the same day is rejected with `ERR_DUPLICATE_SERVICE_PERIOD`. Each line also exposes two computed fields that remain at their defaults until the claim is approved: `elimination_applied` (false) and `benefit_paid_cents` (0). Lines can be listed for a claim.

### 3.6. The Claim Review Cycle

A `ClaimsExaminer` drives a claim through review. Starting review moves the claim from `SUBMITTED` to `UNDER_REVIEW` and is gated by three conditions: the claim must currently be `SUBMITTED` (else `ERR_INVALID_STATE`), the referenced care plan's `status` must be `ACTIVE` (else `ERR_CARE_PLAN_NOT_ACTIVE`), and that care plan's provider must be `ELIGIBLE` (else `ERR_PROVIDER_NOT_ELIGIBLE`).

Review can loop. If the examiner needs a fresh clinical determination, they request a reassessment, moving the claim from `UNDER_REVIEW` to `PENDING_REASSESSMENT` and setting `requires_reassessment` to true (valid only from `UNDER_REVIEW`, else `ERR_INVALID_STATE`). The claim stays parked until a newer certification clears it. Resuming review moves the claim from `PENDING_REASSESSMENT` back to `UNDER_REVIEW` and clears `requires_reassessment` to false; it is valid only from `PENDING_REASSESSMENT` (else `ERR_INVALID_STATE`) and additionally requires that at least one `BenefitTriggerCertification` was recorded for the policy after the claim was sent for reassessment and that the latest such certification carries a `decision` of `CERTIFIED`, failing with `ERR_BENEFITS_NOT_TRIGGERED` otherwise — including the case where no certification at all has been recorded since the claim was parked. The request-reassessment and resume-review legs may repeat as many times as the examiner needs.

### 3.7. Approving and Denying a Claim: Payout and the Pool Cascade

Approval is the financial heart of the system. A `ClaimsExaminer` approves an `UNDER_REVIEW` claim, supplying `expected_policy_version`. Approval is gated by four conditions evaluated against the policy: the claim must be `UNDER_REVIEW` (else `ERR_INVALID_STATE`), `expected_policy_version` must match the policy's current `version` (else `ERR_STALE_VERSION`), the policy's `benefits_triggered` must be true (else `ERR_BENEFITS_NOT_TRIGGERED`), and the benefit pool's `remaining_pool_cents` must be greater than 0 before the payout runs (else `ERR_POOL_EXHAUSTED`).

When those conditions hold, the system runs the payout calculation over the claim's lines, processing them in ascending `service_date` order. It carries three running quantities: the elimination days still owed (the policy's `elimination_period_days` minus its `elimination_days_satisfied`, floored at 0); the amount already paid this `service_month` on prior approved claims of the same policy; and the pool remaining. For each line in date order, a non-qualifying day (where `is_qualifying_day` is false) is skipped with `benefit_paid_cents` set to 0 and `elimination_applied` set to false. While elimination days remain owed, each qualifying day is consumed by the elimination period: its `elimination_applied` is set to true, its `benefit_paid_cents` is 0 (self-paid), and the owed count drops by one. Once no elimination days remain owed, a qualifying day pays a benefit. The raw daily entitlement before caps depends on `product_mode`: under `INDEMNITY` it is the full `inflated_daily_max_cents` regardless of the billed charge; under `REIMBURSEMENT` it is the lesser of `billed_charge_cents` and `inflated_daily_max_cents`. That raw amount is then capped twice: it cannot exceed the remaining monthly headroom (`inflated_monthly_max_cents` minus the amount already paid this service month, floored at 0), and it cannot exceed the pool remaining. The line's `benefit_paid_cents` is the smallest of the raw entitlement, the monthly headroom, and the pool remaining; the month-running total and the pool remaining both decrease by that amount. The claim's `month_paid_cents` is the sum of `benefit_paid_cents` across all of its lines. All arithmetic is integer cents with no rounding.

Approval then cascades. The claim moves to `APPROVED`. A `CLAIM_PAYMENT` entry is appended to the benefit ledger with `amount_cents` equal to the negative of the claim's `month_paid_cents`. The benefit pool's `lifetime_paid_cents` is recomputed as the sum of all `CLAIM_PAYMENT` magnitudes, and its `remaining_pool_cents` is recomputed as `inflated_pool_cents` minus `lifetime_paid_cents`, floored at 0. The policy's `elimination_days_satisfied` is recomputed. If the policy is a partnership policy with an `ACCRUING` disregard, its `protected_asset_cents` is recomputed off the freshly updated `lifetime_paid_cents`. If the recomputed `remaining_pool_cents` reaches exactly 0, the policy auto-transitions `coverage_status` from `CLAIM_OPEN` to the terminal `EXHAUSTED` and every other non-terminal claim on the policy is voided to `VOID`. Otherwise, if no other non-terminal claim remains, coverage returns from `CLAIM_OPEN` to `IN_FORCE`. The policy's `version` is incremented.

Denial is the simpler sibling. A `ClaimsExaminer` denies an `UNDER_REVIEW` claim, supplying `expected_policy_version`; the claim must be `UNDER_REVIEW` (else `ERR_INVALID_STATE`) and the version must match (else `ERR_STALE_VERSION`). A denied claim moves to the terminal `DENIED`. As with approval, if no other non-terminal claim remains on the policy after the denial, coverage returns from `CLAIM_OPEN` to `IN_FORCE`. The policy's `version` is incremented. For both approval and denial, "non-terminal" means a claim in `SUBMITTED`, `UNDER_REVIEW`, or `PENDING_REASSESSMENT`; once the last such claim resolves, coverage leaves `CLAIM_OPEN`.

### 3.8. Provider Suspension and Its Reach

Suspending an `ELIGIBLE` provider is not an isolated act. The suspension moves the provider's `eligibility_status` to `SUSPENDED`, and in the same request every plan of care referencing that provider with `status` of `ACTIVE` is transitioned to the terminal `CLOSED`. The cascade then reaches one level further: every claim that draws on one of those just-closed plans and sits in a non-terminal status — `SUBMITTED`, `UNDER_REVIEW`, or `PENDING_REASSESSMENT` — is transitioned to `VOID`. This is a three-level chain from a single suspend: provider to plan to claim. A subsequent re-certification can later return the provider from `SUSPENDED` to `ELIGIBLE`.

### 3.9. Elimination-Period Progress and Partnership Asset Protection

The elimination period is the deductible expressed in days. The policy's `elimination_days_satisfied` is the count of distinct service dates across all of the policy's approved claims whose lines are marked `is_qualifying_day`, capped at the policy's `elimination_period_days`. A day counts toward satisfaction whether or not it was actually paid — the earliest qualifying days are consumed by the elimination period and self-paid (their `benefit_paid_cents` is 0 and their `elimination_applied` is true), yet they still advance the count. The value is never negative and never exceeds `elimination_period_days`.

Partnership policies earn Medicaid asset protection dollar for dollar. While a `PartnershipDisregard` is `ACCRUING`, its `protected_asset_cents` equals the policy's `BenefitPool.lifetime_paid_cents` exactly — every cent of LTC benefit paid out shields an equal cent of the insured's assets from Medicaid spend-down. This recomputation rides on each claim approval, immediately after `lifetime_paid_cents` is updated. The accrual is read by listing a policy's partnership-disregard record, and that read is shaped as a paginated list envelope (`response_type` of `array`): it carries the single disregard row when the policy is a partnership policy, or an empty array (with `total_count` 0) when it is not, rather than a bare object. The `disregard_status` freezes to `FROZEN` only in one circumstance, described next.

### 3.10. Premium Billing, Grace, Lapse, and Nonforfeiture

The premium axis runs in parallel with coverage. An `Underwriter` generates a `PremiumInvoice` for a billing period against a policy, supplying the `period_index` (a monotonic period number starting at 0 at issue, unique per policy), a `base_premium_cents` figure for the period, the `due_date`, and the `grace_deadline` after which non-payment lapses the policy. The invoice's stored `amount_cents` is computed from the base premium and any applicable approved rate increase, as described in Section 3.11, and the invoice begins in `status` `OPEN`.

A `Policyholder` pays an invoice. Paying the policy's first invoice while the policy is `IN_FORCE` moves `premium_status` from `PENDING` to `PAID_CURRENT` and sets the invoice's `status` to `PAID`; this first payment requires the policy's coverage to be `IN_FORCE` (else `ERR_INVALID_STATE`) and the invoice to be `OPEN` (else `ERR_INVOICE_NOT_OPEN`). Paying an invoice that is not `OPEN` is always rejected with `ERR_INVOICE_NOT_OPEN`, in any premium posture. Paying an additional `OPEN` invoice while the policy is already `PAID_CURRENT` (rather than `PENDING` or `GRACE`) simply marks that invoice `PAID` and leaves `premium_status` unchanged at `PAID_CURRENT`; the grace-deadline guard still applies, so such a payment is rejected with `ERR_GRACE_EXPIRED` when the clock has already passed that invoice's `grace_deadline`.

Time advances through a deterministic test clock, which starts unset (null) on boot and is read through the clock-read endpoint, whose `data` is an object carrying a single `now_iso8601` field holding the current clock instant (null until the first advance). An `Underwriter` advances the clock to a supplied ISO 8601 instant `to_iso8601` — the advance returns `200 OK` with an empty `data` object — and the advance drives premium auto-transitions for every policy with open invoices whose dates have passed. Both invoice dates (`due_date` and `grace_deadline`) are calendar dates, and the clock is compared against them by its calendar-date prefix (`YYYY-MM-DD`): a date is treated as "passed" exactly when the clock's date prefix is strictly greater than that date, so an invoice is neither in grace nor defaulted on the same calendar day its `due_date` or `grace_deadline` falls. When the clock passes an open invoice's `due_date` but not yet its `grace_deadline`, the policy's `premium_status` moves from `PAID_CURRENT` to `GRACE`; an invoice that is no longer `OPEN`, or a policy already on a terminal premium posture (`LAPSED`, `NONFORFEITURE_PAID_UP`, or `WAIVED`), is skipped by the advance. A policyholder may still pay within grace: paying an `OPEN` invoice while in grace moves `premium_status` from `GRACE` back to `PAID_CURRENT` and marks the invoice `PAID`, provided the clock has not yet passed the invoice's `grace_deadline` — a payment attempted after the grace deadline has passed is rejected with `ERR_GRACE_EXPIRED`.

When the clock passes an open invoice's `grace_deadline`, that invoice is marked `DEFAULTED` and the policy's premium posture resolves down one of two branches, and exactly one. The vested branch applies when the policy has nonforfeiture value — that is, when its `inflation_rider` is anything other than `NONE`, or its `BenefitPool.lifetime_paid_cents` is greater than 0. In that case `premium_status` is set to `NONFORFEITURE_PAID_UP` rather than `LAPSED`, a `NONFORFEITURE_REDUCTION` entry is written to the benefit ledger, the `BenefitPool.nonforfeiture_reduction_cents` is recomputed, and any `PartnershipDisregard` stays `ACCRUING`. The unvested branch applies when neither condition holds: `premium_status` is set to the terminal `LAPSED`, and any `PartnershipDisregard` for the policy freezes to `FROZEN`.

Nonforfeiture computes a shortened, paid-up pool. The paid-up pool is the greater of two figures — the total of all `PAID` premium `amount_cents` for the policy, and the benefits already paid (`BenefitPool.lifetime_paid_cents`) — but never more than the pre-reduction inflated pool. The `nonforfeiture_reduction_cents` is the pre-reduction inflated pool minus that paid-up pool, and it is floored at 0 (when the greater of premiums-paid and benefits-paid already meets or exceeds the pool, the reduction is 0). The split conserves the pool: the paid-up pool plus the reduction always equals the pre-reduction inflated pool. After the reduction, the pool's reported `inflated_pool_cents` reflects the grown pool less this reduction.

Premium may also be waived. A `ClaimsExaminer` waives premium on a policy whose benefits have triggered and which is on claim; this sets `premium_status` to `WAIVED` (typically from `PAID_CURRENT`) and sets every `OPEN` invoice for the policy to `WAIVED`. The waiver is gated only by the two checks that follow — there is no precondition on the current `premium_status` itself, so the waiver sets `WAIVED` from whatever premium posture the policy is in. The checks are evaluated in this order: `benefits_triggered` must be true (else `ERR_BENEFITS_NOT_TRIGGERED`), then the policy's `coverage_status` must be `IN_FORCE` or `CLAIM_OPEN` (else `ERR_INVALID_STATE`).

### 3.11. Rate-Increase Filings and Repricing

A carrier may seek to raise premiums. An `Underwriter` files a `RateIncreaseFiling` against a `policy_id`, naming the whole-percent `requested_increase_pct` and the `effective_period_index` — the first invoice period at which an approved increase would bite. A new filing carries `approved_increase_pct` at 0 and begins in `status` `FILED`. A carrier may withdraw a still-filed filing, moving it from `FILED` to the terminal `WITHDRAWN` (valid only from `FILED`, else `ERR_INVALID_STATE`).

A `Regulator` adjudicates a filing, supplying a `granted_pct` and `expected_policy_version`. Adjudication branches on the granted percentage. When the regulator grants the full request — `granted_pct` equal to `requested_increase_pct` — the filing moves from `FILED` to `APPROVED` and `approved_increase_pct` is set to the requested figure. When the regulator grants a strictly partial amount — `granted_pct` greater than 0 and strictly less than `requested_increase_pct` — the filing moves from `FILED` to `PARTIALLY_APPROVED` and `approved_increase_pct` is set to the granted figure. When the regulator grants nothing — `granted_pct` equal to 0 — the filing moves from `FILED` to the terminal `REJECTED`, `approved_increase_pct` stays 0, and no invoices are repriced. A negative `granted_pct` is rejected as a shape violation with `ERR_INVALID_REQUEST` before any state check. A filing not currently in `FILED` fails with `ERR_INVALID_STATE`, and this state check is evaluated before the upper-bound check; only for a filing that is in `FILED` is the upper bound then validated, so that a `granted_pct` greater than `requested_increase_pct` is rejected with `ERR_INVALID_REQUEST`. Both the approval and the partial-approval branches additionally require `expected_policy_version` to match the policy's current `version` (else `ERR_STALE_VERSION`), and both repricing branches increment the policy's `version`. The `granted_pct == 0` (rejection) branch performs no version check and leaves the policy's `version` unchanged.

On a full or partial approval, every `OPEN` invoice for the policy whose `period_index` is at or after the filing's `effective_period_index` has its `amount_cents` recomputed. Repricing an invoice works as follows. The single applicable approved increase is selected: among the policy's filings whose `status` is `APPROVED` or `PARTIALLY_APPROVED` and whose `effective_period_index` is at or before the invoice's `period_index`, the one with the largest `effective_period_index` wins, and if two filings tie on that index, the one created later (later `created_at`) wins; if none qualifies, the increase is 0. The invoice's `amount_cents` is then the `base_premium_cents` multiplied by the quantity one hundred plus the applicable `approved_increase_pct`, divided by one hundred, with that single result rounded half-up to the nearest cent. When no increase applies, the amount equals the base premium unchanged.

When a `Regulator` adjudicates a filing while another `FILED` filing exists for the same policy, the system's broader concern is that a new filing should not be opened while one is pending; an attempt to file a new rate increase while another `FILED` filing already exists for the policy is rejected with `ERR_RATE_FILING_PENDING`. Filings can be listed filtered by `policy_id` and read individually.

### 3.12. The Benefit Ledger and Pool as the Record of Truth

Every movement of pool value is recorded as a `BenefitLedgerEntry`, an append-only event carrying the `policy_id`, the `claim_id` that produced it (null for non-claim entries), a `source_kind`, and a signed `amount_cents`. The `source_kind` is one of `CLAIM_PAYMENT`, `NONFORFEITURE_REDUCTION`, or `INFLATION_GROWTH`. Sign follows the direction of value: `CLAIM_PAYMENT` and `NONFORFEITURE_REDUCTION` carry a negative `amount_cents` because they remove value from the pool, while `INFLATION_GROWTH` carries a positive `amount_cents`. The benefit pool record itself tracks the `policy_id`, the computed `inflated_pool_cents`, the running `lifetime_paid_cents`, the `nonforfeiture_reduction_cents`, and the derived `remaining_pool_cents`, which is `inflated_pool_cents` minus `lifetime_paid_cents` floored at 0. The pool is readable per policy — and that read is shaped as a paginated list envelope (`response_type` of `array`) carrying the single benefit-pool row (exactly one element once the pool has been created at issue), not a bare object. Ledger entries are listable per policy and individually, and the system-wide ledger listing can be filtered by `policy_id` and by `claim_id`.

### 3.13. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority so that the right error surfaces first. Authentication comes first: a missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. Existence follows: any path identifier, then any body foreign key, that does not resolve yields `ERR_NOT_FOUND`. Request-shape validation comes fourth: a body missing a required field, carrying an out-of-range enum, or carrying a negative integer where a non-negative one is required yields `ERR_INVALID_REQUEST`. State validity comes fifth: a target not in a state from which the requested transition is defined yields `ERR_INVALID_STATE`. The one bounds check that is deferred until after state validity is the rate-filing `granted_pct` upper-bound check (`granted_pct` greater than `requested_increase_pct`): although it too surfaces as `ERR_INVALID_REQUEST`, it is evaluated only after the filing has been confirmed to be in `FILED`, so a non-`FILED` filing reports `ERR_INVALID_STATE` even when the supplied `granted_pct` exceeds the requested percentage. A negative `granted_pct`, by contrast, is a standard non-negative-integer shape violation caught at this fourth step, ahead of the state check. Only after these structural checks do the domain-specific business rules described throughout Section 3 apply — care-setting compatibility, provider eligibility, benefit-trigger satisfaction, premium currency, grace expiry, duplicate service periods, service-date placement, pool exhaustion, and the optimistic-concurrency version check. In particular, on the claim writes that carry it, the `ERR_STALE_VERSION` check is the concurrency guard applied among these business rules; and where a care-setting and an eligibility check both apply to plan activation, the care-setting compatibility is checked alongside the eligibility check, both as business-referential rules after state validity.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and the clock advance — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/policyholders` | Register an insured person | Underwriter |
| GET | `/policyholders/{id}` | Read a policyholder | Underwriter, ClaimsExaminer, Policyholder |
| POST | `/policies` | Create a policy application | Underwriter |
| GET | `/policies` | List policies (filter by policyholder_id) | Underwriter, ClaimsExaminer, Regulator |
| GET | `/policies/{id}` | Read a policy with computed fields | Underwriter, ClaimsExaminer, Regulator, Policyholder |
| POST | `/policies/{id}/issue` | Issue an applied policy into force | Underwriter |
| POST | `/policies/{id}/rescind` | Rescind an applied policy | Underwriter |
| POST | `/policies/{id}/apply-anniversary` | Advance one inflation year | Underwriter |
| POST | `/policies/{id}/waive-premium` | Waive premium for a triggered, on-claim policy | ClaimsExaminer |
| GET | `/policies/{id}/benefit-pool` | Read the policy's benefit pool | Underwriter, ClaimsExaminer, Regulator, Policyholder |
| GET | `/policies/{id}/ledger-entries` | List ledger entries for the policy | Underwriter, ClaimsExaminer, Regulator |
| GET | `/ledger-entries/{id}` | Read a single ledger entry | Underwriter, ClaimsExaminer, Regulator |
| GET | `/ledger-entries` | List ledger entries (filter by policy_id, claim_id) | Underwriter, ClaimsExaminer, Regulator |
| GET | `/policies/{id}/partnership-disregard` | Read the partnership asset-disregard accrual | Underwriter, Regulator, Policyholder |
| POST | `/policies/{id}/premium-invoices` | Generate a premium invoice for a period | Underwriter |
| GET | `/premium-invoices` | List premium invoices (filter by policy_id) | Underwriter, ClaimsExaminer, Policyholder |
| GET | `/premium-invoices/{id}` | Read a premium invoice | Underwriter, ClaimsExaminer, Policyholder |
| POST | `/premium-invoices/{id}/pay` | Pay a premium invoice | Policyholder |
| POST | `/rate-filings` | File a premium rate increase | Underwriter |
| GET | `/rate-filings` | List rate filings (filter by policy_id) | Underwriter, Regulator |
| GET | `/rate-filings/{id}` | Read a rate filing | Underwriter, Regulator |
| POST | `/rate-filings/{id}/adjudicate` | Approve/partially-approve/reject a filing | Regulator |
| POST | `/rate-filings/{id}/withdraw` | Withdraw a filed rate filing | Underwriter |
| POST | `/policies/{id}/trigger-certifications` | Record a 2-of-6 ADL/cognitive assessment | CareAssessor |
| GET | `/policies/{id}/trigger-certifications` | List a policy's certifications, newest first | CareAssessor, ClaimsExaminer, Underwriter |
| GET | `/trigger-certifications/{id}` | Read a single trigger certification | CareAssessor, ClaimsExaminer, Underwriter |
| GET | `/trigger-certifications` | List certifications (filter by policy_id, supersedes_id) | CareAssessor, ClaimsExaminer |
| POST | `/providers` | Register a care provider | CareAssessor |
| GET | `/providers/{id}` | Read a provider | CareAssessor, ClaimsExaminer, Underwriter |
| POST | `/providers/{id}/certify` | Certify a provider eligible | CareAssessor |
| POST | `/providers/{id}/reject` | Reject a pending provider | CareAssessor |
| POST | `/providers/{id}/suspend` | Suspend an eligible provider (cascades) | CareAssessor |
| POST | `/care-plans` | Author a plan of care | CareAssessor |
| GET | `/care-plans` | List care plans (filter by policy_id, provider_id) | CareAssessor, ClaimsExaminer, Underwriter |
| GET | `/care-plans/{id}` | Read a care plan | CareAssessor, ClaimsExaminer, Underwriter |
| POST | `/care-plans/{id}/activate` | Activate a draft plan (supersedes prior) | CareAssessor |
| POST | `/care-plans/{id}/close` | Close an active plan | CareAssessor |
| POST | `/claims` | Open a claim for a service month | ClaimsExaminer |
| GET | `/claims` | List claims (filter by policy_id, care_plan_id) | ClaimsExaminer, Underwriter |
| GET | `/claims/{id}` | Read a claim | ClaimsExaminer, Underwriter, Policyholder |
| POST | `/claims/{id}/lines` | Add a service-day line to a submitted claim | ClaimsExaminer |
| GET | `/claims/{id}/lines` | List the claim's service-day lines | ClaimsExaminer, Underwriter |
| POST | `/claims/{id}/start-review` | Move a submitted claim under review | ClaimsExaminer |
| POST | `/claims/{id}/request-reassessment` | Send a claim back pending reassessment | ClaimsExaminer |
| POST | `/claims/{id}/resume-review` | Return a reassessed claim under review | ClaimsExaminer |
| POST | `/claims/{id}/approve` | Approve a claim; run payout and pool cascade | ClaimsExaminer |
| POST | `/claims/{id}/deny` | Deny a claim | ClaimsExaminer |
| POST | `/_clock/advance_to` | Advance the deterministic system clock | Underwriter |
| GET | `/_clock` | Read the current clock value | Underwriter, ClaimsExaminer, Regulator, Policyholder, CareAssessor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CARE_SETTING_MISMATCH` | 422 |
| `ERR_PROVIDER_NOT_ELIGIBLE` | 409 |
| `ERR_PROVIDER_LICENSE_INACTIVE` | 409 |
| `ERR_BENEFITS_NOT_TRIGGERED` | 409 |
| `ERR_PREMIUM_NOT_CURRENT` | 409 |
| `ERR_INVOICE_NOT_OPEN` | 409 |
| `ERR_GRACE_EXPIRED` | 409 |
| `ERR_DUPLICATE_SERVICE_PERIOD` | 409 |
| `ERR_SERVICE_DATE_OUT_OF_MONTH` | 422 |
| `ERR_POOL_EXHAUSTED` | 409 |
| `ERR_CARE_PLAN_NOT_ACTIVE` | 409 |
| `ERR_RATE_FILING_PENDING` | 409 |
| `ERR_ANNIVERSARY_NOT_IN_FORCE` | 409 |
| `ERR_VALIDATION_CONFLICT` | 422 |
