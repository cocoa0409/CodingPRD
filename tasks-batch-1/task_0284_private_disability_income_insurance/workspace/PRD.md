# Private Disability Income Insurance API — Product Requirements Document

## 1. Introduction

Private disability income insurance replaces a portion of an insured person's earnings when illness or injury prevents them from working. Unlike a one-off indemnity payment, a disability contract pays out month after month, and each monthly installment must respect a web of contractual limits: the occupation class that priced the risk, the elimination (waiting) period before any benefit accrues, the maximum number of benefit months the contract will ever pay, and — for partial recoveries — the proportion of income actually lost. This API models that entire apparatus as an auditable ledger, where every benefit installment is a posted line, every offset from a third-party program (such as Social Security Disability Insurance or workers' compensation) is reconciled against the contractual benefit, and the running totals can always be reconstructed from the underlying records.

The system serves four distinct constituencies. Underwriters issue and administer policies, occupation classes, and policyholders, and they drive the premium lifecycle that keeps a policy in force. Claims adjudicators review filed claims, decide own-occupation versus any-occupation disability, accrue the monthly benefits, and manage the offsets that net those benefits down. Policyholders — the insured persons themselves — file claims against their own policies and keep them alive by submitting periodic continued-disability proofs and, where the claim is for a partial loss, income reports that establish how much earning capacity remains. A system operator advances a deterministic monthly clock so that elimination periods, proof cadences, and offset windows can be exercised reproducibly without depending on wall-clock time.

Because money flows are the heart of the product, the dominant design concern is conservation: a benefit that is reversed must return the consumed benefit months to the policy exactly, an offset that is voided must unwind the overpayment it created exactly, and the claim ledger must at all times equal the sum of its posted lines. The sections below specify the contract precisely where the API's shape is at stake, and narrate the business rules where an implementer must assemble behavior from the surrounding domain logic.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource paths are mounted under the `/disability` prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_AUTH_CONTEXT`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `Underwriter`, `Policyholder`, `ClaimsAdjudicator`, and `SystemOperator`. Every `GET` read is available to all four roles; the write operations are partitioned among them and described throughout §3.

Three of the four roles carry an **opaque** identity. When `X-User-Role` is `Underwriter`, `ClaimsAdjudicator`, or `SystemOperator`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The `Policyholder` role is **entity-backed**: when `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting `Policyholder` entity. Ownership checks on any resource that references a `Policyholder` compare the resource's policyholder back to `X-User-ID` — a policyholder may only file, submit, recertify income for, or attest continued disability on a claim whose policy belongs to them. A policyholder acting on a claim whose policy is owned by a different policyholder is rejected with `ERR_FORBIDDEN_ROLE`.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Deterministic Insurer Clock

Time in this system is not wall-clock time. Each `Insurer` carries a `current_month_index`, an integer month epoch that begins at 0 when the insurer program is created and advances only when a `SystemOperator` explicitly advances it. Advancing the clock accepts a `by_months` amount, which must be between 1 and 100000 inclusive, and adds that amount to `current_month_index`. Every month-valued field elsewhere in the system — a claim's disability onset, an income report's effective month, an offset window's bounds, a benefit period's coverage month — is expressed in these insurer month indices, and elimination satisfaction is judged against the insurer's `current_month_index` at the moment of approval. No other operation mutates the clock.

### 2.5. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, where `created_at` records first creation and `updated_at` records the most recent modification. The `version` is an integer that begins at 1 on creation and increments by one on every mutation of the resource; it underpins both the audit trail and the optimistic-concurrency mechanism of §2.7.

One entity is deliberately leaner. A `DisabilityProof` is an append-only, immutable attestation: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once submitted it is never modified. Every other entity — `Insurer`, `OccupationClass`, `Policyholder`, `Policy`, `Claim`, `IncomeReport`, `BenefitPeriod`, `OffsetAward`, and `ClaimLedger` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

When a derived or denormalized field changes as a side effect of some other operation — for example a policy's `benefit_months_consumed` shifting because a benefit installment accrued, or a claim ledger's totals being recomputed — that counts as a mutation of the affected resource: its `updated_at` is refreshed and its `version` increments.

### 2.6. Precision, Rounding, and Monetary Representation

Monetary amounts are stored as integer cents and never as fractional currency. Two computed ratios — a claim's income loss ratio and a benefit period's benefit fraction — are real numbers rounded to four decimal places using round-half-up. A policy's consumed benefit months is likewise a fractional quantity rounded to four decimal places, because partial (residual) months count fractionally toward the contract maximum.

Where a monetary figure is derived from a multiplication that yields a fractional cent, the result is rounded to the nearest whole cent using round-half-up. The COLA-adjusted benefit calculation in §3 applies this rounding independently at each of its two steps: first when the base monthly benefit is scaled by the cost-of-living multiplier, and again when that COLA-adjusted figure is scaled by the benefit fraction. All subsequent ledger arithmetic — summing benefit periods, subtracting offsets — is integer arithmetic on those already-rounded cent values.

### 2.7. Optimistic Concurrency on Income Recertification

Recording a residual income report is the one write in this system that is guarded by optimistic concurrency, because accepting a new income basis supersedes the prior one and silently changes how every future installment on the claim is priced. A request to record an income report on a claim must therefore carry an `expected_claim_version` field whose value is the client's last observed `version` of that `Claim`. The server compares it to the claim's current `version`: if another recertification or status transition has advanced the claim's version since the client last read it, the values no longer match and the create is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), preventing the client from layering a new income basis on top of a claim state it never saw. This check runs before any business logic on the income-report write. No other endpoint takes a version field; all other state transitions are guarded by their own from-state preconditions rather than by a client-supplied version.

### 2.8. Validation Ordering and Nested-Resource Resolution

When an endpoint path names a chain of resources, the system resolves them left to right and rejects the request at the first identifier that does not exist, returning the resource-specific not-found error for that identifier. The not-found family is per resource type: an unresolved insurer yields `ERR_INSURER_NOT_FOUND`, an unresolved occupation class yields `ERR_OCCUPATION_CLASS_NOT_FOUND`, an unresolved policyholder yields `ERR_POLICYHOLDER_NOT_FOUND`, an unresolved policy yields `ERR_POLICY_NOT_FOUND`, an unresolved claim yields `ERR_CLAIM_NOT_FOUND`, an unresolved benefit period yields `ERR_BENEFIT_PERIOD_NOT_FOUND`, and an unresolved offset award yields `ERR_OFFSET_AWARD_NOT_FOUND`. The same per-type not-found errors apply to foreign-key fields supplied in a create body that reference a non-existent resource — for example a create whose `insurer_id`, `policyholder_id`, `occupation_class_id`, `policy_id`, or `claim_id` does not resolve fails with the corresponding not-found error.

Across the API, validations are applied in a fixed priority order so that the same request always fails for the same reason. Authentication comes first: a missing or malformed header (`ERR_MISSING_AUTH_CONTEXT`, priority 1) is detected before role authorization (`ERR_FORBIDDEN_ROLE`, priority 2), which is detected before existence. Existence checks resolve path identifiers (priority 3) and then body foreign keys (priority 4). Only then do resource-specific gates apply: the optimistic-concurrency version check on income recertification (priority 5), the state-gate that the target resource — or, for an offset-award create, its parent claim — is in the correct status for the operation (priority 6), and finally the business rules particular to each workflow. The remaining business validations are ordered priority 7 through 13 and are described where the workflows that raise them appear in §3; in particular, for an offset-award create the parent-claim state gate (priority 6) is evaluated before the offset-window overlap check (priority 8), and field-shape validation (`ERR_INVALID_REQUEST`, priority 13) is the lowest-priority business check on create endpoints.

### 2.9. Field-Shape Validation on Create

Every create endpoint validates the shape of its payload, raising `ERR_INVALID_REQUEST` when any of the following hold: a required field is missing; an enum field carries a value outside its declared set; an integer falls outside its permitted range; a cost-of-living annual rate (`cola_annual_rate`) is greater than zero while the cost-of-living rider (`cola_rider`) is not attached; a policy's own-occupation window (`own_occ_window_months`) exceeds the occupation class's `own_occ_window_months_cap`; a policy's `elimination_period_days` is below the occupation class's `min_elimination_days`; or a policy's `benefit_period_months` exceeds the occupation class's `max_benefit_months`. These cross-entity caps are evaluated against the occupation class the policy references.

### 2.10. Cascades, Conservation, and Hierarchical Consistency

Several operations mutate more than one entity, and the system guarantees that the secondary effects are applied atomically with the primary one. When a policy lapses or terminates, its claims are swept into the appropriate status; when a claim is reversed, all of its posted benefit lines are unwound and the consumed-months counter on the policy is restored; when an offset is finalized or voided, every benefit period it covers is re-priced and the ledger overpayment balance moves to match. Each of these cascades is detailed in the relevant workflow narrative in §3. The governing invariant is conservation: a policy's `benefit_months_consumed` always equals the sum of `benefit_fraction` over the claim's still-active (`ACCRUED`) benefit periods, and the claim ledger's `overpayment_balance_cents` is a conserved quantity that returns exactly to its prior value when the triggering offset is undone. Whenever a cascade mutates a parent or sibling resource, that resource's `updated_at` and `version` advance per §2.5.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Book: Insurers, Occupation Classes, and Policyholders

The foundational records are created by an `Underwriter`. An insurer program is created with a `name`; the system initializes its `current_month_index` to 0 and returns the new `Insurer`. Reading an insurer exposes that month index so that any role can see where the deterministic clock currently stands.

An **occupation class** prices the risk of an insured occupation and bounds what policies written against it may declare. It belongs to an insurer via `insurer_id` and is identified by a `code` such as "1A" or "4A" that is unique per insurer and case-sensitive. Its `risk_tier` is one of `LOW`, `MEDIUM`, `HIGH`, or `DECLINE`; a class marked `DECLINE` may not back an activated policy. The class also declares three ceilings that constrain its policies: `max_benefit_months`, the largest benefit period (between 1 and 600) any policy may declare; `min_elimination_days`, the floor (zero or greater) on a policy's waiting period; and `own_occ_window_months_cap`, the longest own-occupation definition window (zero or greater) a policy may declare. Occupation classes can be listed for an insurer by supplying an optional `insurer_id` filter, and fetched individually.

A **policyholder** is the insured person, created against an insurer via `insurer_id` with their legal `full_name` and a `pre_disability_monthly_income_cents` — the baseline indemnity earnings, which must be strictly greater than zero, that serve as the denominator when measuring residual income loss. Policyholders may be listed (optionally filtered by `insurer_id`) and fetched individually.

### 3.2. Issuing and Activating a Policy

A policy ties a policyholder to an occupation class and fixes the contract terms. An `Underwriter` issues one by supplying `insurer_id`, `policyholder_id`, `occupation_class_id`, the contractual total-disability `monthly_benefit_cents` (strictly greater than zero), the `benefit_period_months` (between 1 and the occupation class's maximum benefit months, representing the most benefit months payable across all claims on the policy combined), the `elimination_period_days` (the waiting period in days, no less than the occupation class's minimum elimination days, before any benefit accrues), and the `occupation_definition`, which is either `OWN_OCC` or `ANY_OCC` and governs which disability test the adjudicator applies.

Two optional groups of fields tailor the contract. For an `OWN_OCC` policy, `own_occ_window_months` declares how many months the own-occupation test applies before the policy reverts to an any-occupation test; it defaults to 0, must not exceed the occupation class's own-occupation window cap, and is ignored for an `ANY_OCC` policy. The cost-of-living group consists of `cola_rider`, a boolean defaulting to false indicating whether the COLA rider is attached, and `cola_annual_rate`, the annual cost-of-living rate expressed as a decimal (for example 0.03) defaulting to 0 and bounded between 0 and 0.10 inclusive; when the rider is not attached the rate must be 0.

A freshly issued policy begins life with `lifecycle_status` equal to `PENDING`, `premium_status` equal to `CURRENT`, and `benefit_months_consumed` of 0. These are two genuinely independent state dimensions — the lifecycle dimension tracks whether the policy is in force, while the premium dimension tracks whether premiums are being paid — and §3.3 describes how they interact. Issuing the policy returns it; policies can also be listed (optionally filtered by `insurer_id`, `policyholder_id`, or `occupation_class_id`) and fetched individually, where a fetch surfaces `benefit_months_consumed` and both status dimensions.

Activation is the underwriter's act of putting a `PENDING` policy in force, transitioning `lifecycle_status` from `PENDING` to `ACTIVE`. The policy must currently be `PENDING`, or the request is rejected with `ERR_POLICY_NOT_PENDING`. The referenced occupation class must not be a `DECLINE` class — activating a policy backed by a declined class is rejected with `ERR_OCCUPATION_CLASS_DECLINED`. On success the lifecycle moves to `ACTIVE` and the policy's `version` increments.

### 3.3. The Premium Lifecycle and the Lapse Cascade

The premium dimension runs on its own axis and is driven entirely by the underwriter. Recording a missed premium on an `ACTIVE` policy whose `premium_status` is `CURRENT` advances it to `GRACE`; this first leg requires the policy to be `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`) and the premium status to be `CURRENT` (otherwise `ERR_PREMIUM_NOT_CURRENT`), and it increments the policy `version`. Paying the premium while in `GRACE` returns `premium_status` to `CURRENT`; this requires the status to be `GRACE` (otherwise `ERR_PREMIUM_NOT_IN_GRACE`) and increments `version`.

Recording a second missed premium while already in `GRACE` advances `premium_status` to `DEFAULT`; this leg requires the status to be `GRACE` (otherwise `ERR_PREMIUM_NOT_IN_GRACE`) and increments `version`. Entering `DEFAULT` is consequential: it triggers the **lapse cascade**, in which the policy's `lifecycle_status` moves from `ACTIVE` to `LAPSED` (incrementing `version` again for that lifecycle change), and every claim on the policy currently in `APPROVED` status is swept from `APPROVED` to `SUSPENDED` so that no new benefit installments may accrue while the policy is lapsed. Each such claim mutation increments that claim's `version`.

Termination is the underwriter's deliberate wind-down of an in-force policy, moving `lifecycle_status` from `ACTIVE` to `TERMINATED`. The policy must be `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`), and no claim on the policy may be in `UNDER_REVIEW` or `PENDING_INFO` — an open claim mid-adjudication blocks termination with `ERR_OPEN_CLAIM_EXISTS`. On success the lifecycle becomes `TERMINATED`, the policy `version` increments, and a closing cascade sweeps every `APPROVED` or `SUSPENDED` claim on the policy to `CLOSED`, each such transition incrementing the affected claim's `version`. The `TERMINATED` lifecycle state is terminal.

### 3.4. Filing a Claim and Computing Its Windows

A `Policyholder` files a **claim** against one of their own policies by supplying `insurer_id`, `policy_id`, the `disability_onset_month` (the insurer month index, zero or greater, on which disability began), and the `claimed_disability_type`, which is either `TOTAL` or `RESIDUAL`. The claim is created in `DRAFT` status.

At creation the system computes two month-index windows from the policy and onset. The **elimination satisfied month** is the onset month plus the elimination period converted to whole months, where the conversion divides `elimination_period_days` by 30 days per month and rounds up to the next whole month; this lands in the claim's `elimination_satisfied_month`. The **own-occupation expiry month** depends on the policy's disability test: for an `OWN_OCC` policy it is the elimination satisfied month plus the policy's `own_occ_window_months`, and for an `ANY_OCC` policy it equals the elimination satisfied month exactly; this lands in `own_occ_expiry_month`. A third computed field, `next_proof_due_month`, defaults to 0 at filing and is only set meaningfully on approval, as §3.6 describes. Fetching a claim surfaces these computed window months, `next_proof_due_month`, and the claim's `version`. Claims can be listed with optional `insurer_id` and `policy_id` filters.

For a `RESIDUAL` claim, the residual income basis must exist before the claim can be submitted: at least one income report must already be on the claim. This is the content of the residual-report requirement enforced at submission.

### 3.5. Adjudicating a Claim Through the Review Cycle

Submission is the policyholder's act of advancing a claim from `DRAFT` to `SUBMITTED`. The claim must be in `DRAFT` (otherwise `ERR_CLAIM_NOT_DRAFT`), the policy must be `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`), and if the claim's type is `RESIDUAL` there must be at least one income report on it (otherwise `ERR_RESIDUAL_INCOME_REPORT_REQUIRED`, a 422). Submission increments the claim `version`.

From here the `ClaimsAdjudicator` drives a review cycle. Beginning review moves a `SUBMITTED` claim to `UNDER_REVIEW` (requiring `SUBMITTED`, else `ERR_CLAIM_NOT_SUBMITTED`). While `UNDER_REVIEW`, the adjudicator may request further information, moving the claim to `PENDING_INFO` (requiring `UNDER_REVIEW`, else `ERR_CLAIM_NOT_UNDER_REVIEW`); resuming review then moves it from `PENDING_INFO` back to `UNDER_REVIEW` (requiring `PENDING_INFO`, else `ERR_CLAIM_NOT_PENDING_INFO`). This `UNDER_REVIEW → PENDING_INFO → UNDER_REVIEW` loop may repeat any number of times, and each leg increments the claim `version`.

From `UNDER_REVIEW` the adjudicator reaches a decision. Denial moves the claim to the terminal `DENIED` status (requiring `UNDER_REVIEW`, else `ERR_CLAIM_NOT_UNDER_REVIEW`) and increments `version`. Approval — described in §3.6 — also departs from `UNDER_REVIEW`. Every transition in this section increments the claim `version` by one.

### 3.6. Approval, Proof Cadence, and the Approved↔Suspended Cycle

Approving an `UNDER_REVIEW` claim is the gateway to benefit payment, and it enforces five conditions, each with its own rejection. The claim must be `UNDER_REVIEW` (`ERR_CLAIM_NOT_UNDER_REVIEW`). The policy's lifecycle must be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`). The policy's premium must not be in `DEFAULT` (`ERR_PREMIUM_IN_DEFAULT`). The insurer's `current_month_index` must have reached at least the claim's `elimination_satisfied_month` — that is, the current month index must be greater than or equal to the elimination satisfied month — or the approval is rejected with `ERR_ELIMINATION_NOT_SATISFIED`. And the policy's `benefit_months_consumed` must be strictly less than its `benefit_period_months`; if the contract's benefit months are already fully consumed, approval is rejected with `ERR_BENEFIT_PERIOD_EXHAUSTED`.

On success the claim moves from `UNDER_REVIEW` to `APPROVED` and its `version` increments. Two side effects accompany approval: a `ClaimLedger` is created for the claim if one does not already exist, with all its totals at 0; and `next_proof_due_month` is set to the elimination satisfied month plus the proof interval of three months. The proof interval governs the cadence at which continued-disability proofs keep the claim payable.

Continued-disability **proofs** are submitted by the `Policyholder` and are append-only. A proof carries an `attestation_month` (the insurer month index it attests to, no earlier than the claim's onset month) and a boolean `still_disabled`. The system computes the proof's `accepted` flag: a proof is accepted when `still_disabled` is true and its `attestation_month` is no greater than the claim's `next_proof_due_month` at the moment of submission. When a proof is accepted, the claim's `next_proof_due_month` advances by the three-month proof interval and the claim `version` increments. Proofs can be listed for a claim.

An approved claim can move between paid and paused states. Suspending an `APPROVED` claim moves it to `SUSPENDED` (requiring `APPROVED`, else `ERR_CLAIM_NOT_APPROVED`); this same `APPROVED → SUSPENDED` leg is also what the lapse cascade of §3.3 fires automatically. Reinstating a `SUSPENDED` claim moves it back to `APPROVED` (requiring `SUSPENDED`, else `ERR_CLAIM_NOT_SUSPENDED`, and additionally requiring the policy lifecycle to be `ACTIVE`, else `ERR_POLICY_NOT_ACTIVE`). Together these form the `APPROVED ↔ SUSPENDED` cycle; while suspended, no new benefit installments may accrue. Each leg increments the claim `version`.

Closing an `APPROVED` claim moves it to the terminal `CLOSED` status (requiring `APPROVED`, else `ERR_CLAIM_NOT_APPROVED`) and increments `version`; this is also the status the policy-termination cascade of §3.3 drives `APPROVED` and `SUSPENDED` claims into.

### 3.7. Reversing an Approved Claim: the Compensation Cascade

Reversing an `APPROVED` claim is the adjudicator's act of undoing a benefit determination entirely, moving the claim from `APPROVED` to the terminal `DENIED` status (requiring `APPROVED`, else `ERR_CLAIM_NOT_APPROVED`). It increments the claim `version` and triggers a full compensation cascade that must leave the books exactly as they were before any installment posted: every `ACCRUED` benefit period on the claim is moved to `REVERSED`; the claim ledger's `total_gross_paid_cents`, `total_net_paid_cents`, and `overpayment_balance_cents` are recomputed to 0; and the policy's `benefit_months_consumed` is decreased by the sum of the `benefit_fraction` values of the reversed periods, honoring the conserved-quantity invariant that consumed months track exactly the active installments.

### 3.8. Residual Income Reports and the Supersede Rule

For a `RESIDUAL` claim, the proportion of benefit payable depends on how much income the insured still earns, and that is established through **income reports**. A `Policyholder` records one against their claim by supplying an `effective_month` (the insurer month index this income basis takes effect, no earlier than the claim's `disability_onset_month`), a `current_monthly_income_cents` (earnings while disabled, zero or greater), and the `expected_claim_version` required by the optimistic-concurrency rule of §2.7.

The system computes the report's `income_loss_ratio` as the pre-disability monthly income minus the current monthly income, divided by the pre-disability monthly income, with any negative result floored at 0 and the quotient rounded to four decimal places. Accepting a new report recertifies the basis: it supersedes any prior report on the same claim that has a strictly lesser `effective_month` by setting that prior report's `is_superseded` flag to true, leaving the newest report as the live basis. The `is_superseded` flag is false by default and becomes true exactly when a later report with a strictly greater effective month is accepted. Recording an income report increments the claim `version`. Income reports can be listed for a claim.

A claim's `benefit_months_consumed` denominator lives on the policy, but the loss ratio's denominator is the policyholder's `pre_disability_monthly_income_cents`. Because recertification rewrites how every subsequent installment is priced, the create is the OCC-guarded write: a stale `expected_claim_version` is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412) before the income basis is touched.

### 3.9. Accruing a Benefit Installment

A benefit installment is posted by the `ClaimsAdjudicator` as a **benefit period** covering a single insurer month. The accrual request supplies a `coverage_month`, the one insurer month index this installment covers; each benefit period covers a half-open one-month interval running from its coverage month up to but not including the following month, so consecutive months touch but never overlap. On creation the system stamps the period's `policy_id` from the claim's policy, sets its `status` to `ACCRUED`, and computes its `benefit_fraction`, `gross_benefit_cents`, `offset_applied_cents`, and `net_benefit_cents` as described below and in §3.10.

Accrual is gated by a sequence of checks. The parent claim must be `APPROVED` (otherwise `ERR_CLAIM_NOT_PAYABLE`). The coverage month must lie within the payable window: it must be at least the claim's `elimination_satisfied_month` and no greater than the claim's `next_proof_due_month`, so that a benefit only accrues for months whose continued-disability proof is current — a coverage month before elimination satisfaction or beyond the proof-due horizon is rejected with `ERR_PROOF_NOT_CURRENT` (a 422). No other `ACCRUED` benefit period on the claim may already cover this coverage month; a duplicate is rejected with `ERR_COVERAGE_MONTH_OCCUPIED`. Finally, the accrual must not drive the policy's `benefit_months_consumed` beyond its `benefit_period_months`: a would-exceed accrual is rejected with `ERR_BENEFIT_PERIOD_WOULD_EXCEED` (a 422), where reaching exact equality is permitted and exhausts the contract rather than being rejected.

On a successful accrual the policy's `benefit_months_consumed` increases by this period's `benefit_fraction`, the claim ledger totals are recomputed, and if the consumed months reach or exceed the contract's `benefit_period_months` the claim transitions from `APPROVED` to the terminal `BENEFIT_EXHAUSTED` status (incrementing the claim `version`), after which no further benefit periods may accrue. Benefit periods can be listed for a claim, listed across the book with optional `policy_id` and `claim_id` filters, and fetched individually.

The **benefit fraction** is what proportion of the contractual monthly benefit this month pays. For a `TOTAL` claim it is always 1.0. For a `RESIDUAL` claim it derives from the loss ratio R, which is taken from the single income report that is in effect for the coverage month — namely the non-superseded report (its `is_superseded` is false) with the greatest `effective_month` that is no greater than the coverage month, breaking ties by earliest `created_at` and never by `id`; if no such report exists, R is treated as 0. Two variants then apply. Under the **proportionate** variant — which governs a `RESIDUAL` claim on an `ANY_OCC` policy, or a `RESIDUAL` claim whose coverage month is at or after the own-occupation expiry month — the fraction is 0.0 when R is below the minimum loss ratio of 0.20, is 1.0 (a presumptive total) when R is at or above the presumed-total ratio of 0.80, and otherwise equals R itself rounded to four decimal places. Under the **presumptive-total** variant — which governs a `RESIDUAL` claim on an `OWN_OCC` policy while the coverage month is strictly before the own-occupation expiry month — any qualifying loss pays in full: the fraction is 1.0 when R is at or above the minimum loss ratio of 0.20, and 0.0 otherwise, so the proportionate band between 0.20 and 0.80 collapses to full payment.

### 3.10. Pricing the Installment: COLA Adjustment and the Offset Waterfall

The gross benefit for a period applies any cost-of-living escalation to the contractual benefit before scaling by the benefit fraction, and the evaluation order is fixed: the benefit fraction is settled first, then the gross benefit, then the offset applied, then the net benefit.

The **COLA-adjusted gross** begins by determining how many full years have elapsed since elimination was satisfied: the coverage month minus the claim's `elimination_satisfied_month`, divided by 12 and rounded down to a whole number of years. When the policy carries no COLA rider, or when zero or fewer full years have elapsed, the cost-of-living multiplier is 1.0. Otherwise the multiplier compounds the annual rate over the elapsed years — one plus the policy's `cola_annual_rate`, raised to the power of the elapsed years — and is then capped at the maximum COLA multiplier of 2.0, so escalation can never more than double the base benefit. The COLA-adjusted cents are the policy's `monthly_benefit_cents` multiplied by that multiplier, rounded half-up to the nearest cent. The `gross_benefit_cents` is then that COLA-adjusted figure multiplied by the period's `benefit_fraction`, again rounded half-up to the nearest cent. The two roundings are applied independently and in that order.

The **offset applied** nets third-party benefits against the gross. The `offset_applied_cents` for a coverage month is the sum, over every non-`VOID` offset award on the claim whose closed window contains the coverage month, of each award's effective offset; for determinism the running sum adds `WORKERS_COMP` awards before `SSDI` awards, though the final total is independent of order. The `net_benefit_cents` is then the gross benefit minus the offset applied, floored at the offset floor of 0 so that a net benefit never goes negative. Whether an award's effective offset is its estimated or its reconciled figure depends on the award's status, as §3.11 explains: an `ESTIMATED` award contributes a provisional offset and a `FINALIZED` award contributes the reconciled offset, which is the source of the provisional-versus-final distinction in the net computation.

### 3.11. Offset Awards: Estimate, Finalize, and Void

A third-party offset — Social Security disability or workers' compensation — is recorded by the `ClaimsAdjudicator` as an **offset award** on a claim. The create supplies an `offset_source` of either `SSDI` or `WORKERS_COMP`, a `monthly_offset_cents` (the monthly third-party benefit to offset while estimated, zero or greater), and the inclusive bounds of the window: a `start_month` and an `end_month` no earlier than the start month, forming a closed interval that includes both endpoints. Creating an offset award requires the parent claim to be `APPROVED`; this parent-state gate is checked first, and a claim not in `APPROVED` is rejected with `ERR_CLAIM_NOT_APPROVED`. Only after that gate passes is the window checked for collision: the new window may not overlap any existing non-`VOID` offset award of the same `offset_source` on the claim, and because the interval is closed and carries a one-month no-touch buffer, two windows that merely touch (the end of one equal to the start of the other) collide and are rejected with `ERR_OFFSET_WINDOW_OVERLAP`. Distinct `offset_source` values never collide with each other.

On creation the award's `status` is `ESTIMATED`, its `estimated_offset_cents` is snapshotted from the supplied `monthly_offset_cents`, and its `effective_offset_cents` resolves to that monthly offset — the snapshot is retained precisely so that finalize can later compute the overpayment delta. Creating the award also recomputes `offset_applied_cents` and `net_benefit_cents` on every `ACCRUED` benefit period whose coverage month falls in the award's window, and recomputes the claim ledger's `total_net_paid_cents`. The award's `final_monthly_offset_cents` defaults to 0 until finalized. Offset awards can be listed for a claim and fetched individually.

**Finalizing** an offset award reconciles the estimate against the actual third-party determination. It requires the award to be `ESTIMATED` (otherwise `ERR_OFFSET_NOT_ESTIMATED`) and the parent claim to be `APPROVED` (otherwise `ERR_CLAIM_NOT_APPROVED`). The request may supply `final_monthly_offset_cents`; when omitted it defaults to the award's `estimated_offset_cents`. Finalize moves the award from `ESTIMATED` to `FINALIZED`, sets `final_monthly_offset_cents` to the supplied (or defaulted) value so that `effective_offset_cents` now resolves to the reconciled figure, and increments the award `version`. It then cascades: each `ACCRUED` benefit period whose coverage month lies in the award's window has its `offset_applied_cents` and `net_benefit_cents` recomputed, the claim ledger's `total_net_paid_cents` is recomputed, and the positive delta — the reconciled monthly offset minus the estimated snapshot, taken as zero when that difference is negative — accrues to the ledger's `overpayment_balance_cents` for each covered `ACCRUED` month.

**Voiding** an offset award removes its contribution entirely. It is permitted from either `ESTIMATED` or `FINALIZED` status; attempting to void an award already in `VOID` is rejected with `ERR_OFFSET_NOT_VOIDABLE`. Voiding moves the award to the terminal `VOID` status (where its `effective_offset_cents` resolves to 0), increments the award `version`, and compensates: every affected `ACCRUED` benefit period recomputes `offset_applied_cents` and `net_benefit_cents` excluding this award, and the ledger's `total_net_paid_cents` and `overpayment_balance_cents` return to their pre-finalize values — when a previously finalized award is voided, the exact overpayment delta that finalize added is subtracted back, honoring the conserved-quantity invariant.

### 3.12. Voiding a Benefit Period and Reading the Ledger

A single benefit installment can be reversed without unwinding the whole claim. The `ClaimsAdjudicator` voids an `ACCRUED` benefit period, moving it to the terminal `REVERSED` status; the period must be `ACCRUED` (otherwise `ERR_BENEFIT_PERIOD_NOT_ACCRUED`) and the parent claim must be in either `APPROVED` or `SUSPENDED` status (otherwise `ERR_CLAIM_NOT_PAYABLE`). Voiding increments the benefit period `version`, recomputes the claim ledger totals, and decreases the policy's `benefit_months_consumed` by that period's `benefit_fraction`, again preserving the conservation invariant that consumed months equal the sum over active periods.

The **claim ledger** is the denormalized running account of a claim, created at approval and read as a sub-resource of the claim. Its `claim_id` ties it to the claim. Its `total_gross_paid_cents` is the sum of `gross_benefit_cents` over the claim's `ACCRUED` benefit periods, and its `total_net_paid_cents` is the sum of `net_benefit_cents` over those same `ACCRUED` periods; both default to 0 and are recomputed whenever a benefit period accrues or is voided, whenever an offset award is finalized or voided, and whenever a claim is reversed. When summed, the contributing benefit periods are ordered by `coverage_month` ascending and then by `created_at` ascending, never by `id`. Its `overpayment_balance_cents`, also defaulting to 0, is the conserved overpayment quantity maintained incrementally: finalizing an offset adds, over the covered `ACCRUED` months, the positive excess of the reconciled monthly offset over the estimated snapshot, and voiding a previously finalized award subtracts exactly that same sum, so the balance returns to its prior value.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and the clock advance — return `200 OK`. All read operations return `200 OK`. Request and response payload details are specified in the §3 narratives; the table below lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/disability/insurers` | Create an insurer program | Underwriter |
| GET | `/disability/insurers/{insurerId}` | Get insurer (includes current month index) | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| POST | `/disability/insurers/{insurerId}/clock/advance` | Advance the deterministic clock | SystemOperator |
| POST | `/disability/occupation-classes` | Create an occupation/risk class | Underwriter |
| GET | `/disability/occupation-classes` | List occupation classes | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| GET | `/disability/occupation-classes/{occupationClassId}` | Get an occupation class | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| POST | `/disability/policyholders` | Register a policyholder | Underwriter |
| GET | `/disability/policyholders` | List policyholders | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| GET | `/disability/policyholders/{policyholderId}` | Get a policyholder | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| POST | `/disability/policies` | Issue a policy | Underwriter |
| GET | `/disability/policies` | List policies | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| GET | `/disability/policies/{policyId}` | Get a policy | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| POST | `/disability/policies/{policyId}/activate` | Activate a PENDING policy | Underwriter |
| POST | `/disability/policies/{policyId}/terminate` | Terminate an ACTIVE policy | Underwriter |
| POST | `/disability/policies/{policyId}/premium/miss` | Record a missed premium | Underwriter |
| POST | `/disability/policies/{policyId}/premium/pay` | Pay premium during grace | Underwriter |
| POST | `/disability/claims` | File a claim in DRAFT | Policyholder |
| GET | `/disability/claims` | List claims | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| GET | `/disability/claims/{id}` | Get a claim | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| POST | `/disability/claims/{id}/submit` | Submit a DRAFT claim | Policyholder |
| POST | `/disability/claims/{id}/begin-review` | Move a SUBMITTED claim to UNDER_REVIEW | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/request-info` | Move UNDER_REVIEW to PENDING_INFO | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/resume-review` | Move PENDING_INFO back to UNDER_REVIEW | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/approve` | Approve an UNDER_REVIEW claim | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/deny` | Deny an UNDER_REVIEW claim | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/suspend` | Suspend an APPROVED claim | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/reinstate` | Reinstate a SUSPENDED claim | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/reverse` | Reverse an APPROVED claim | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/close` | Close an APPROVED claim | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/income-reports` | Record/recertify residual income basis | Policyholder |
| GET | `/disability/claims/{id}/income-reports` | List income reports on a claim | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| POST | `/disability/claims/{id}/disability-proofs` | Submit a continued-disability proof | Policyholder |
| GET | `/disability/claims/{id}/disability-proofs` | List disability proofs on a claim | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| POST | `/disability/claims/{id}/benefit-periods` | Accrue a benefit installment for one coverage month | ClaimsAdjudicator |
| GET | `/disability/claims/{id}/benefit-periods` | List benefit periods on a claim | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| GET | `/disability/benefit-periods` | List benefit periods | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| GET | `/disability/benefit-periods/{benefitPeriodId}` | Get a benefit period | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| POST | `/disability/benefit-periods/{benefitPeriodId}/void` | Void an ACCRUED benefit period | ClaimsAdjudicator |
| POST | `/disability/claims/{id}/offset-awards` | Record an estimated offset window | ClaimsAdjudicator |
| GET | `/disability/claims/{id}/offset-awards` | List offset awards on a claim | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| GET | `/disability/offset-awards/{offsetAwardId}` | Get an offset award | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |
| POST | `/disability/offset-awards/{offsetAwardId}/finalize` | Finalize an estimated offset | ClaimsAdjudicator |
| POST | `/disability/offset-awards/{offsetAwardId}/void` | Void an offset award | ClaimsAdjudicator |
| GET | `/disability/claims/{id}/ledger` | Get the claim ledger | Underwriter, ClaimsAdjudicator, Policyholder, SystemOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INSURER_NOT_FOUND` | 404 Not Found |
| `ERR_OCCUPATION_CLASS_NOT_FOUND` | 404 Not Found |
| `ERR_POLICYHOLDER_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_BENEFIT_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_OFFSET_AWARD_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_STALE_CLAIM_VERSION` | 412 Precondition Failed |
| `ERR_POLICY_NOT_PENDING` | 409 Conflict |
| `ERR_POLICY_NOT_ACTIVE` | 409 Conflict |
| `ERR_OCCUPATION_CLASS_DECLINED` | 409 Conflict |
| `ERR_PREMIUM_NOT_CURRENT` | 409 Conflict |
| `ERR_PREMIUM_NOT_IN_GRACE` | 409 Conflict |
| `ERR_PREMIUM_IN_DEFAULT` | 409 Conflict |
| `ERR_OPEN_CLAIM_EXISTS` | 409 Conflict |
| `ERR_CLAIM_NOT_DRAFT` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_NOT_PENDING_INFO` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_CLAIM_NOT_SUSPENDED` | 409 Conflict |
| `ERR_CLAIM_NOT_PAYABLE` | 409 Conflict |
| `ERR_RESIDUAL_INCOME_REPORT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ELIMINATION_NOT_SATISFIED` | 409 Conflict |
| `ERR_BENEFIT_PERIOD_EXHAUSTED` | 409 Conflict |
| `ERR_BENEFIT_PERIOD_WOULD_EXCEED` | 422 Unprocessable Entity |
| `ERR_PROOF_NOT_CURRENT` | 422 Unprocessable Entity |
| `ERR_COVERAGE_MONTH_OCCUPIED` | 409 Conflict |
| `ERR_OFFSET_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OFFSET_NOT_ESTIMATED` | 409 Conflict |
| `ERR_OFFSET_NOT_VOIDABLE` | 409 Conflict |
| `ERR_BENEFIT_PERIOD_NOT_ACCRUED` | 409 Conflict |
