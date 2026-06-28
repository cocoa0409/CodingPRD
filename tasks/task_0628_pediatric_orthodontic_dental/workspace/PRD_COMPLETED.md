# Ortho Dental Office API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Ortho Dental Office API, the back-office platform that runs a combined pediatric and orthodontic practice offering traditional braces and clear-aligner therapy. The practice must coordinate four very different concerns at once: the clinical record (panoramic and cephalometric growth films that gate when treatment may begin), the multi-phase treatment plan and its phased fee, the monthly financing contract with auto-pay and delinquency handling, and the patient's orthodontic insurance — a lifetime-maximum benefit pool that must be drawn down precisely and never double-spent.

The system's hardest job is reconciling two views of the same money. At the moment a guardian approves a plan, the practice produces a *forward-looking* estimate of what insurance will pay, assuming the whole net fee is billable and the full remaining lifetime maximum is available. Later, as real claims are submitted and approved over time, the practice draws the benefit pool down *chronologically* — so the actual benefit a plan ultimately collects can be smaller than the estimate if earlier emergency claims have already consumed the pool. The platform must keep estimates, financed balances, family discounts, and remaining lifetime maximums mutually consistent at every step, applying every cascade atomically inside the request that triggers it.

A practice runs on a calendar, so the API is backed by a logical clock rather than wall-clock time. Every due-date, scheduling, check-in, and delinquency rule reads this clock. On startup the clock reads exactly `2026-01-01T00:00:00.000Z` and never falls back to real time until an administrator advances it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation — or an ownership-scoped role targets a resource it does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles: `FrontDesk`, `Orthodontist`, `BillingSpecialist`, `Guardian`, and `ClinicAdmin`.

- A `FrontDesk` user handles family accounts, patient registration, and the full appointment desk workflow (scheduling, check-in, cancel, no-show). When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- An `Orthodontist` is the clinician who authors growth records, treatment plans, and phases, drives plan proposal and revision, debonds and completes plans, completes appointments, and replaces retainers. When `X-User-Role` is `Orthodontist`, `X-User-ID` is the `provider_user_id` of the acting `Provider`; the server may record it but does not compare it to any resource's provider foreign key. Orthodontist operations are gated by role alone: any authenticated `Orthodontist` may act on any plan, phase, growth record, retainer, or appointment regardless of which `Provider` the resource references, so completing another provider's appointment is permitted and no provider-ownership `ERR_FORBIDDEN` is raised for this role.
- A `BillingSpecialist` manages insurance policies and claims, contracts, installment charges, and payments and their reversals. When `X-User-Role` is `BillingSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- A `Guardian` is the parent or guardian who owns a `FamilyAccount`: they approve (activate) plans, co-sign contracts, make payments, and read records scoped to their own family. When `X-User-Role` is `Guardian`, `X-User-ID` is the `guardian_user_id` stamped on the owning `FamilyAccount`; ownership checks on any resource that traces back to a `FamilyAccount` compare that account's `guardian_user_id` to `X-User-ID`.
- A `ClinicAdmin` is the operational administrator who manages providers, chairs, and the logical clock, and holds broad create/read access across the system. When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, and its accepted range is a minimum of 1 and a maximum of 100. A supplied `limit` outside that range is clamped into it (values below 1 become 1, values above 100 become 100) rather than rejected. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0, and a negative `offset` is clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their `created_at` timestamp in ascending order.

List responses always include `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource carries a server-minted `id` formatted as a bare UUID with no type prefix, together with a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Resources that may change after creation additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at 1 and increments by one with every mutation to the resource. All entities in this system are mutable and therefore carry the full set: `id`, `created_at`, `updated_at`, and `version`.

Time in this system is governed by a logical clock, never the host's wall clock. The clock reads exactly `2026-01-01T00:00:00.000Z` from startup and holds that value until an administrator advances it by supplying a new instant in the `to_iso8601` field. Every reference to "now" in scheduling, due-date evaluation, check-in windows, debond timing, and delinquency rules resolves against this logical clock.

### 2.5. Monetary Values, Discount Ceiling, and Rounding

All monetary amounts in this system are integer counts of cents — fees, balances, benefits, payments, and lifetime maximums alike. Wherever a rule multiplies a cents amount by a fraction (a modality multiplier, a discount percentage, an insurance coverage percentage), the product is rounded to a whole number of cents using the round-half-up method (a value exactly halfway between two whole cents rounds up to the larger). Because amounts are already integer cents, this is equivalent to two-decimal-place precision on the underlying dollar figure. The orthodontic coverage percentage `ortho_coverage_pct` is a fraction; a value outside the closed interval from 0 to 1 is semantically invalid and rejected with `ERR_VALIDATION` (HTTP 422) even though it is shape-valid.

One ceiling applies to family discounts across the whole system: the discount actually subtracted from a plan's gross fee can never exceed 75000 cents (that is, 750 dollars), regardless of how large a percentage the family qualifies for.

### 2.6. Derived-Field Reconciliation and Conserved Pools

Several fields are computed and must stay mutually consistent. Two conserved pools anchor the system. The first is the orthodontic lifetime maximum on each `InsurancePolicy`: at all times `remaining_max_cents` equals `lifetime_max_cents` minus the sum of `benefit_cents` across that policy's claims in `APPROVED` or `PAID` status. The second is the financed balance on each `Contract`: `balance_remaining_cents` equals `financed_amount_cents` minus the sum of `amount_cents` across that contract's payments in `POSTED` status, so a `POSTED` payment later `REVERSED` nets back to zero effect. Whenever a derived value changes on a resource, that change is itself a mutation: it refreshes the resource's `updated_at` and increments its `version`.

### 2.7. Hierarchical Consistency and the Delinquency Cascade

When a parent resource changes state, the system propagates the consequences to its dependents atomically, inside the same request, before responding. The signature example is the delinquency cascade. When an autopay charge fails on or after an installment's due date, that installment becomes `MISSED` (cascade origin); the owning contract's `billing_status` flips from `CURRENT` to `DELINQUENT`; the owning treatment plan moves from `ACTIVE` to `SUSPENDED`; and every future appointment of that plan that is still `SCHEDULED` with a start strictly after the current clock value is transitioned to `CANCELLED`. The cure runs the cascade in reverse: when the last `MISSED` installment is paid so that no `MISSED` installment remains, the contract returns to `CURRENT` and the plan, if `SUSPENDED`, returns to `ACTIVE`. Each leg that mutates a resource refreshes its `updated_at` and increments its `version`.

### 2.8. Nested and Path Parameter Validation

When a request addresses a resource by an identifier in its path — for example a `{id}` path parameter on a get-by-id or a state-transition endpoint — the system validates that identifier first. Any path identifier or foreign-key reference in the body that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404). Where multiple references exist, they are validated left to right, so the first unresolved reference determines the 404. Existence is checked before any state or business rule is evaluated.

### 2.9. Optimistic Concurrency on Contract Creation

Contract creation is guarded by optimistic concurrency on the treatment plan it finances. A request to create a contract must carry `expected_plan_version`, a non-optional field holding the `version` of the target `TreatmentPlan` the client last observed. If that value does not equal the plan's current `version` at the moment the create is processed, the request is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). A contract legitimately supersedes any prior contract for the same plan, and because creating a contract itself increments the plan's `version`, a client that observed the plan before another writer created the first contract (or before the plan was revised or re-activated) is working from a stale view; refusing the create prevents it from overwriting a contract it never saw. Contract creation is the only endpoint that takes a version field; no other endpoint accepts or requires one.

### 2.10. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role and ownership authorization (`ERR_FORBIDDEN`), then existence of all path and foreign-key references (`ERR_NOT_FOUND`), then request-body well-formedness — required fields present, enum values legal, an appointment's end strictly after its start, a contract term of at least one month, and all supplied amounts non-negative (`ERR_INVALID_REQUEST`). Only after those structural gates does the optimistic-concurrency check on contract creation run (`ERR_STALE_PLAN_VERSION`), followed by the state-machine legality check that the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). After legality, cross-entity state preconditions are evaluated (`ERR_CROSS_ENTITY_STATE`), then records-completeness for plan activation (`ERR_RECORDS_INCOMPLETE`), then the chair temporal-overlap check (`ERR_CHAIR_CONFLICT`), then the provider temporal-overlap check (`ERR_PROVIDER_CONFLICT`), then the not-yet-due guard on installment charges (`ERR_NOT_YET_DUE`), then the down-payment fiscal guard on contract creation (`ERR_DOWN_PAYMENT_EXCEEDS`), and finally the overpayment fiscal guard on payments (`ERR_OVERPAYMENT`). Earlier checks mask later ones: a request that fails authorization never reaches the state check.

## 3. Business Logic & Workflows

### 3.1. Families, Patients, and the People Who Treat Them

The account root is the **family account**, created by front-desk staff or an administrator with a `family_name`, a `billing_email`, and the `guardian_user_id` of the guardian who will own it. At creation the family's computed `discount_tier_pct` and `active_plan_count` both start at zero; both are maintained automatically as the family's plans move in and out of treatment (see §3.5).

Each **patient** is registered under a family by supplying `family_account_id`, the patient's `full_name`, the `date_of_birth`, and a boolean `is_minor` flagging pediatric patients. A patient also carries a computed `records_complete` flag, which starts false and becomes true only once the patient has the required growth films on file (see §3.2). Patients can be listed and optionally narrowed to one family.

Two operational resources support scheduling. A **provider** record represents an orthodontist and is created by an administrator with the clinician's `provider_user_id`, `full_name`, and `npi` (National Provider Identifier); the boolean `active` flag defaults to true and marks whether the provider currently accepts appointments. A **chair** (operatory) is created with a `label`, an integer `turnover_buffer_minutes` that defaults to 10 and reserves cleanup time after each appointment in that chair before it is free again, and an `active` flag defaulting to true.

### 3.2. Growth Records and the Clinical Gate

Before a treatment plan may be activated, the practice requires a complete set of growth films. A **growth record** is created by a clinician or administrator against a patient via its `patient_id`, with a `record_type` that is either `PANO` (panoramic) or `CEPH` (cephalometric) and a `taken_at` timestamp recording when the film was captured. A new record begins in `DRAFT` and may be listed or fetched, optionally filtered by patient.

A clinician finalizes a record, moving its `status` from `DRAFT` to `FINALIZED`. Finalization is only legal from `DRAFT`; attempting it from any other state is rejected with `ERR_INVALID_STATE`. Finalization carries two side effects. First, if a `FINALIZED` growth record of the same `record_type` already exists for that patient, that prior record is transitioned to `SUPERSEDED` — only the newest film of each type stays current. Second, the patient's `records_complete` flag is recomputed: it is true exactly when the patient now holds one `FINALIZED` `PANO` and one `FINALIZED` `CEPH`, and false otherwise. The system may also drive a `FINALIZED` record to `SUPERSEDED` on its own when a newer same-type record is finalized; whenever that happens the patient's `records_complete` is recomputed as well.

### 3.3. Authoring a Treatment Plan and Its Phases

A clinician (or administrator) opens a **treatment plan** for a patient by supplying `patient_id`, an optional `policy_id` naming the insurance policy whose ortho benefit estimate will apply (left absent for a self-pay plan), a `modality` of either `BRACES` or `INVISALIGN`, and an optional `planned_visit_interval_weeks` that defaults to 6 and records the nominal number of weeks between recurring adjustment visits. A fresh plan is created in `DRAFT` with `version` 1. Plans can be fetched with their computed fees and listed, optionally filtered by patient or by policy.

The fee is built from **treatment phases**. Each phase is added to a `DRAFT` plan with `plan_id`, a 1-based `sequence_no` ordering it within the plan, a `label` such as "Phase I expansion", and a `phase_fee_cents` amount. Phases can be fetched individually and listed, optionally filtered by plan.

The plan's computed money fields — `gross_fee_cents`, `discount_pct_applied`, `net_fee_cents`, `estimated_insurance_benefit_cents`, and `estimated_patient_responsibility_cents` — remain unpinned while the plan is in flux and are all locked in atomically when the guardian activates the plan (see §3.4 and §3.5).

### 3.4. Proposal, Revision, Activation, and the Plan Lifecycle

A clinician advances a `DRAFT` plan to `PROPOSED`, presenting it to the family. Proposal is legal only from `DRAFT`, and only when the plan has at least one treatment phase; a plan with no phases is rejected with `ERR_NO_PHASES`. Proposal increments the plan's `version`.

If the family declines, the clinician sends the plan back from `PROPOSED` to `DRAFT` for edits — the revision loop — which is legal only from `PROPOSED` and likewise increments the `version`. The loop may repeat as often as needed.

The guardian who owns the family activates a `PROPOSED` plan, transitioning it to `ACTIVE`. Activation is legal only from `PROPOSED`, and only when the patient's `records_complete` is true; otherwise the activation is rejected with `ERR_RECORDS_INCOMPLETE`. Activation is the pinning moment, and it performs the following, all within the one request: it pins `gross_fee_cents`, then `discount_pct_applied`, then `net_fee_cents`, then `estimated_insurance_benefit_cents` and `estimated_patient_responsibility_cents` (computed as described in §3.5); it recomputes the family's `active_plan_count` and `discount_tier_pct` counting this plan as in-treatment; and it increments the plan's `version`.

From `ACTIVE`, the plan can travel two further legal paths driven by a clinician. Debonding moves the plan from `ACTIVE` to `RETENTION` and is legal only from `ACTIVE`; it requires either that a completed `DEBOND` appointment already exists for the plan, or that the debond request itself supplies a `retainer_type` so the retainer can be issued inline. When neither condition holds — no completed `DEBOND` appointment exists and no `retainer_type` is supplied — the request is rejected with `ERR_INVALID_REQUEST` (this check runs after the state-machine legality check). A supplied `retainer_type` outside `HAWLEY`, `CLEAR`, or `FIXED` is likewise rejected with `ERR_INVALID_REQUEST`; when a completed `DEBOND` appointment satisfies the requirement and no `retainer_type` is supplied, the issued retainer defaults to `HAWLEY`. Debonding issues a retainer for the plan in `ISSUED` status with `issued_at` set to the current clock value, recomputes the family discount, and increments the plan's `version`. Later the clinician completes the plan, moving it from `RETENTION` to `COMPLETED`; completion is legal only from `RETENTION`, closes the owning contract by moving its `lifecycle_status` to `CLOSED`, recomputes the family discount, and increments the plan's `version`.

A clinician may also cancel a plan that has not yet begun treatment: cancellation is legal from `DRAFT` or from `PROPOSED` (and from no other state), moving the plan to `CANCELLED` and incrementing its `version`. `COMPLETED` and `CANCELLED` are terminal.

Two further plan transitions are never requested directly — the system drives them as part of the delinquency cascade. When the owning contract becomes `DELINQUENT`, an `ACTIVE` plan is driven to `SUSPENDED`; as it does so it cancels the plan's future still-`SCHEDULED` appointments whose start is strictly after the current clock value, recomputes the family discount, and increments the plan's `version`. When the contract returns to `CURRENT`, a `SUSPENDED` plan is driven back to `ACTIVE`, recomputing the family discount and incrementing the `version`. The plan's status therefore cycles `ACTIVE → SUSPENDED → ACTIVE` across delinquency and cure.

### 3.5. Family Discount, Plan Fee, and the Forward-Looking Estimate

The family discount tier is a function of how many of a family's *distinct patients* are currently in treatment, counting a plan as in-treatment when its status is `ACTIVE` or `RETENTION`. Two distinct fields are tracked. The count `active_plan_count` is the number of the family's plans in those two states (so two in-treatment plans on the same child count as two plans here). The discount tier, however, is keyed to the number of distinct patients in the family that hold at least one in-treatment plan — two in-treatment plans on the same child count as one patient for the tier, while plans on different children stack. When that distinct-patient count is fewer than two, `discount_tier_pct` is 0; when it equals exactly two, it is 0.05 (five percent); and when it is three or more, it is 0.10 (ten percent). Both `active_plan_count` and the tier are recomputed whenever any of the family's plans enters or leaves the in-treatment set, and crucially the tier is evaluated *including the plan being activated* — at activation the plan under activation is counted as `ACTIVE`, contributing its patient to the distinct-patient count for the purpose of choosing the tier.

At activation the plan's fee is built in a pinned order. First, the gross fee: the system sums the `phase_fee_cents` of every phase on the plan and multiplies that sum by the modality multiplier — 1.15 for `INVISALIGN`, or 1.00 for `BRACES` — rounding the product half-up to whole cents to yield `gross_fee_cents`. Second, the discount fraction `discount_pct_applied` is locked from the family discount tier just computed. Third, the raw discount is the gross fee multiplied by `discount_pct_applied`, rounded half-up to whole cents; the discount actually applied is the smaller of that raw discount and the 75000-cent ceiling; and `net_fee_cents` is the gross fee minus that applied discount.

The forward-looking insurance estimate is then pinned from the net fee. If the plan has no `policy_id`, or the named policy's `ortho_rider` is false, the estimated benefit is 0. Otherwise the system projects a benefit equal to `net_fee_cents` multiplied by the policy's `ortho_coverage_pct`, rounded half-up to whole cents, and then takes the smaller of that projection and the policy's `remaining_max_cents` as it stands at activation — the estimate optimistically assumes the entire net fee is billable to the rider in one shot and that the full remaining lifetime maximum is available to this plan. The resulting `estimated_insurance_benefit_cents` is pinned, and `estimated_patient_responsibility_cents` is set to `net_fee_cents` minus `estimated_insurance_benefit_cents`.

### 3.6. Insurance Policies, Claims, and the Chronological Drawdown

A billing specialist (or administrator) records an **insurance policy** for a patient with `patient_id`, a `carrier_name`, the boolean `ortho_rider` flag, the `ortho_coverage_pct` fraction of billed ortho charges the rider covers (ignored entirely when there is no rider), and the `lifetime_max_cents` orthodontic maximum. A new policy starts `ACTIVE` with `remaining_max_cents` initialized equal to `lifetime_max_cents`. Policies can be fetched and listed, optionally filtered by patient. A billing specialist may terminate a policy, moving its `status` from `ACTIVE` to `TERMINATED`; termination is legal only from `ACTIVE` and additionally is refused while any claim on that policy is in `APPROVED` status, since an approved-but-unpaid claim has already drawn benefit that would be stranded — that refusal carries `ERR_POLICY_HAS_OPEN_CLAIMS`. A `TERMINATED` policy accepts no new claim activity.

A **claim** is submitted by a billing specialist against a policy via `policy_id`, naming the plan whose treatment it bills through `plan_id` and the `billed_amount_cents` charged to the carrier. A new claim is `SUBMITTED` with `benefit_cents` of 0. Claims can be fetched and listed, optionally filtered by policy or by plan.

Approving a claim moves it from `SUBMITTED` to `APPROVED` and is where the lifetime maximum is actually drawn down. Approval is legal only from `SUBMITTED`; it additionally requires that the owning policy is `ACTIVE` (otherwise `ERR_POLICY_TERMINATED`) and that the policy carries an ortho rider (otherwise `ERR_NO_ORTHO_RIDER`). On approval the awarded `benefit_cents` is the smaller of two quantities: the `billed_amount_cents` multiplied by the policy's `ortho_coverage_pct` rounded half-up to whole cents, and the policy's `remaining_max_cents` as it stands at the instant of this approval. The policy's `remaining_max_cents` is then reduced by that awarded benefit. Because claims consume the pool in order of their `created_at` ascending, a plan's later claim may find the pool already partly spent by earlier emergency claims — which is exactly why the chronological actual benefit collected can total less than the forward-looking estimate pinned on the plan. An `APPROVED` claim can be marked paid, moving it to `PAID` with no further pool effect (legal only from `APPROVED`). A claim still in `SUBMITTED` can be denied, moving it to `DENIED` (legal only from `SUBMITTED`).

Voiding is the compensating reversal. An `APPROVED` claim can be voided, moving it to `VOID` (legal only from `APPROVED`); voiding restores the policy's `remaining_max_cents` by the claim's `benefit_cents` and then resets that claim's `benefit_cents` to 0, preserving the invariant that `lifetime_max_cents` always equals `remaining_max_cents` plus the sum of `benefit_cents` over the policy's `APPROVED` and `PAID` claims. `PAID`, `DENIED`, and `VOID` are terminal.

### 3.7. Contracts, the Installment Schedule, and Auto-Pay

Once a plan is activated and its patient responsibility is known, a billing specialist or the guardian signs a **contract** to finance it. Creating a contract supplies `plan_id`, the `expected_plan_version` for the concurrency guard described in §2.9, a `down_payment_cents` amount paid up front, a `term_months` count of monthly installments that must be at least 1, and an optional `autopay_enabled` flag that defaults to true and governs whether monthly installments auto-charge on their due date. The target plan must be `ACTIVE` for the contract to be created; financing a plan in any other status (`DRAFT`, `PROPOSED`, `SUSPENDED`, `RETENTION`, `COMPLETED`, or `CANCELLED`) is the state-machine legality failure of §2.10 and is rejected with `ERR_INVALID_STATE`. The financed amount `financed_amount_cents` is the plan's `estimated_patient_responsibility_cents` minus `down_payment_cents`; this must be at least zero, so a down payment exceeding the plan's estimated patient responsibility is rejected with `ERR_DOWN_PAYMENT_EXCEEDS`. A new contract starts with `billing_status` `CURRENT` and `lifecycle_status` `ACTIVE`, with `balance_remaining_cents` initialized equal to `financed_amount_cents`. Successful creation also increments the owning plan's `version`. Contracts can be fetched and listed, optionally filtered by plan.

Creating the contract builds the **installment** schedule in one pass. The per-month amount is the financed amount divided by the term and rounded down to whole cents (floored). Installments with `sequence_no` 1 through the term minus one each take that floored per-month amount; the final installment takes whatever remains — the financed amount minus the per-month amount multiplied by the count of earlier installments — so the installment amounts sum to the financed amount exactly with no rounding drift. Each installment's `due_at` is the contract's `created_at` advanced by its index times one month, where one month is 30 days; that is, the k-th installment falls due 30·k days after the contract was created, measured against the logical clock. Each installment carries `contract_id`, its `sequence_no`, the computed `due_at`, the computed `amount_cents`, and a `status` that starts `SCHEDULED`. Installments can be fetched and listed, optionally filtered by contract.

A billing specialist drives the autopay charge for an installment by submitting an `outcome` string that is either a success (`SUCCEEDED` or `SUCCESS`, case-insensitive) or a failure (`FAILED` or `FAILURE`, case-insensitive); a missing `outcome` or any other value is rejected with `ERR_INVALID_REQUEST`. A successful charge creates a `POSTED` payment for the installment's `amount_cents`, moves the installment to `PAID`, and reduces the contract's balance; it is legal only when the installment is `SCHEDULED` or `MISSED` and only while the contract's `lifecycle_status` is `ACTIVE` — otherwise it is rejected with `ERR_INVALID_STATE`. A failed charge is legal only when the installment is `SCHEDULED`; it sets the installment to `MISSED`, but only when the logical clock has reached or passed the installment's `due_at`; a failed charge attempted before the due date is rejected with `ERR_NOT_YET_DUE`. When an installment becomes `MISSED`, it ignites the delinquency cascade of §2.7. An installment moves to `PAID` either from `SCHEDULED` (an on-time charge or a covering payment) or from `MISSED` (a late cure), and an installment charge to `PAID` is only honored while the contract's `lifecycle_status` is `ACTIVE`.

### 3.8. Payments, Reversals, and Payoff

A **payment** is recorded by a billing specialist or guardian against a contract with `contract_id`, an optional `installment_id` naming the installment it satisfies (absent for an ad-hoc payoff), an `amount_cents`, and a `method` of `AUTOPAY`, `CARD`, `CASH`, or `CHECK`. When an `installment_id` is supplied it must belong to the named contract; an installment that exists but whose `contract_id` differs is treated as an unresolved reference and rejected with `ERR_NOT_FOUND`. A payment may not exceed the contract's `balance_remaining_cents` (an amount exactly equal to the balance is allowed); an overpayment is rejected with `ERR_OVERPAYMENT`. A new payment is `POSTED`, which reduces `balance_remaining_cents` by its amount. If the payment covers an installment, that installment moves to `PAID`; if it was the last `MISSED` installment so that none remains `MISSED`, the contract returns to `CURRENT` and a `SUSPENDED` owning plan returns to `ACTIVE`. If the payment brings `balance_remaining_cents` to zero, the contract's `lifecycle_status` moves to `CLOSED`. Payments can be fetched and listed, optionally filtered by contract or by installment.

A billing specialist may reverse a payment, moving its `status` from `POSTED` to `REVERSED`; reversal is legal only from `POSTED` and only while the contract's `lifecycle_status` is `ACTIVE` (a reversal against a closed contract is rejected with `ERR_CONTRACT_CLOSED`). Reversal increases `balance_remaining_cents` back by the payment's `amount_cents`, preserving the conservation rule that the financed amount equals the remaining balance plus the sum of `POSTED` payment amounts. If the covered installment had been `PAID` and the logical clock is now at or past that installment's `due_at`, reversal returns the installment to `MISSED`, which may re-fire the delinquency cascade.

A contract's `lifecycle_status` also closes on its own when the owning plan reaches `COMPLETED`, or when `balance_remaining_cents` reaches zero. Once `CLOSED`, any installments still scheduled remain on record but no further autopay fires against the contract.

### 3.9. Appointments: Chair, Provider, and Visit Scheduling

Front-desk staff (or an administrator) schedule an **appointment** by supplying `patient_id`, `provider_id`, `chair_id`, an optional `plan_id` naming the plan the visit advances, a `visit_type`, and the `starts_at` and `ends_at` bounds of the visit. The end must be strictly after the start, or the request fails with `ERR_INVALID_REQUEST`. The `visit_type` is one of `BONDING`, `ADJUSTMENT`, `EMERGENCY`, or `DEBOND`, where `ADJUSTMENT` is the recurring scheduled visit and `EMERGENCY` covers broken brackets and urgent triage; a `plan_id` is required for `ADJUSTMENT`, `BONDING`, and `DEBOND` visits and may be omitted only for `EMERGENCY` new-patient triage. A new appointment is `SCHEDULED`. Appointments can be fetched and listed, optionally filtered by patient, provider, chair, plan, or by `status`.

Scheduling enforces a cross-entity precondition and two temporal-overlap rules, in that order. The cross-entity precondition requires that, for each of the three plan-required visit types — `ADJUSTMENT`, `BONDING`, and `DEBOND` — the referenced plan is `ACTIVE`; a referenced plan in any other status is rejected with `ERR_CROSS_ENTITY_STATE`. An `EMERGENCY` visit carries no plan-state precondition: even when an `EMERGENCY` request supplies a `plan_id`, the plan's status is not checked. The chair check then guards against double-booking an operatory: the requested interval extended by the chair's `turnover_buffer_minutes` — that is, the half-open interval that runs from the appointment's start up to but not including its end plus the buffer — must not overlap any non-terminal appointment already booked in that chair; an overlap is rejected with `ERR_CHAIR_CONFLICT`. The provider check guards the clinician's calendar with no buffer: the requested half-open interval from start up to but not including end must not overlap any non-terminal appointment for the same provider, though exact adjacency where one appointment's end equals the next one's start is permitted; an overlap is rejected with `ERR_PROVIDER_CONFLICT`.

Front-desk staff check a patient in, moving the appointment from `SCHEDULED` to `CHECKED_IN`; check-in is legal only from `SCHEDULED` and only once the logical clock has reached the window that opens 60 minutes before `starts_at` — an attempt more than 60 minutes early is rejected with `ERR_TOO_EARLY_CHECKIN`. A clinician completes a checked-in visit, moving it from `CHECKED_IN` to `COMPLETED` (legal only from `CHECKED_IN`). Front-desk staff may cancel a still-scheduled visit, moving it from `SCHEDULED` to `CANCELLED` (legal only from `SCHEDULED`); the same `CANCELLED` outcome is what the delinquency cascade applies to a plan's future scheduled visits. Front-desk staff may also mark a no-show from either `SCHEDULED` or `CHECKED_IN`, moving the appointment to `NO_SHOW`, but only once the logical clock has reached `starts_at`; marking a no-show before the start is rejected with `ERR_TOO_EARLY_NOSHOW`. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal.

### 3.10. Retention and Retainers

When a plan is debonded into `RETENTION`, a **retainer** is issued for it as described in §3.4. A retainer carries `plan_id`, a `retainer_type` of `HAWLEY`, `CLEAR`, or `FIXED` (defaulting to `HAWLEY`), an `issued_at` timestamp set to the clock value at the moment of issue, and a `status` that starts `ISSUED`. Retainers can be fetched and listed, optionally filtered by plan.

If a retainer breaks, a clinician replaces it, moving the old retainer's `status` from `ISSUED` to `REPLACED` (legal only from `ISSUED`) and issuing a fresh retainer for the same plan in `ISSUED` status with `issued_at` set to the current clock value; the replacement may carry its own `retainer_type`, and when none is supplied the new retainer inherits the old retainer's `retainer_type`. The replace endpoint returns the old (now `REPLACED`) retainer in `data`, not the newly issued one. `REPLACED` is terminal for the old retainer.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state transitions and the clock-setting capability — return `200 OK`. All list and get-by-id reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ClinicAdmin |
| POST | `/family-accounts` | Create a family/billing account | FrontDesk, ClinicAdmin |
| GET | `/family-accounts/{id}` | Get a family account | FrontDesk, ClinicAdmin, BillingSpecialist, Guardian |
| POST | `/patients` | Register a patient under a family | FrontDesk, ClinicAdmin |
| GET | `/patients/{id}` | Get a patient | FrontDesk, ClinicAdmin, BillingSpecialist, Orthodontist, Guardian |
| GET | `/patients` | List patients, filterable by family | FrontDesk, ClinicAdmin, BillingSpecialist, Orthodontist, Guardian |
| POST | `/providers` | Create an orthodontist/provider | ClinicAdmin |
| GET | `/providers/{id}` | Get a provider | FrontDesk, ClinicAdmin, Orthodontist |
| POST | `/chairs` | Create an operatory/chair | ClinicAdmin |
| GET | `/chairs/{id}` | Get a chair | FrontDesk, ClinicAdmin, Orthodontist |
| POST | `/growth-records` | Create a pano/ceph growth record | Orthodontist, ClinicAdmin |
| GET | `/growth-records/{id}` | Get a growth record | Orthodontist, ClinicAdmin, FrontDesk |
| GET | `/growth-records` | List growth records, filterable by patient | Orthodontist, ClinicAdmin, FrontDesk |
| POST | `/growth-records/{id}/finalize` | Finalize a growth record | Orthodontist |
| POST | `/insurance-policies` | Create an insurance policy | BillingSpecialist, ClinicAdmin |
| GET | `/insurance-policies/{id}` | Get an insurance policy | BillingSpecialist, ClinicAdmin |
| GET | `/insurance-policies` | List policies, filterable by patient | BillingSpecialist, ClinicAdmin |
| POST | `/insurance-policies/{id}/terminate` | Terminate a policy | BillingSpecialist |
| POST | `/treatment-plans` | Create a treatment plan | Orthodontist, ClinicAdmin |
| GET | `/treatment-plans/{id}` | Get a treatment plan with computed fees | Orthodontist, ClinicAdmin, BillingSpecialist, Guardian |
| GET | `/treatment-plans` | List plans, filterable by patient or policy | Orthodontist, ClinicAdmin, BillingSpecialist, Guardian |
| POST | `/treatment-plans/{id}/propose` | Move a plan DRAFT to PROPOSED | Orthodontist |
| POST | `/treatment-plans/{id}/revise` | Move a plan PROPOSED to DRAFT | Orthodontist |
| POST | `/treatment-plans/{id}/activate` | Activate a plan; pins fees and discount | Guardian |
| POST | `/treatment-plans/{id}/debond` | Move a plan ACTIVE to RETENTION; issue retainer | Orthodontist |
| POST | `/treatment-plans/{id}/complete` | Move a plan RETENTION to COMPLETED | Orthodontist |
| POST | `/treatment-plans/{id}/cancel` | Cancel a DRAFT/PROPOSED plan | Orthodontist |
| POST | `/treatment-phases` | Add a phase to a DRAFT plan | Orthodontist, ClinicAdmin |
| GET | `/treatment-phases/{id}` | Get a treatment phase | Orthodontist, ClinicAdmin, BillingSpecialist |
| GET | `/treatment-phases` | List phases, filterable by plan | Orthodontist, ClinicAdmin, BillingSpecialist |
| POST | `/contracts` | Create a monthly auto-pay contract | BillingSpecialist, Guardian |
| GET | `/contracts/{id}` | Get a contract | BillingSpecialist, ClinicAdmin, Guardian |
| GET | `/contracts` | List contracts, filterable by plan | BillingSpecialist, ClinicAdmin, Guardian |
| GET | `/installments/{id}` | Get an installment | BillingSpecialist, ClinicAdmin, Guardian |
| GET | `/installments` | List installments, filterable by contract | BillingSpecialist, ClinicAdmin, Guardian |
| POST | `/installments/{id}/charge` | Attempt the autopay charge for an installment | BillingSpecialist |
| POST | `/payments` | Record a payment against a contract/installment | BillingSpecialist, Guardian |
| GET | `/payments/{id}` | Get a payment | BillingSpecialist, ClinicAdmin, Guardian |
| GET | `/payments` | List payments, filterable by contract or installment | BillingSpecialist, ClinicAdmin, Guardian |
| POST | `/payments/{id}/reverse` | Reverse a posted payment | BillingSpecialist |
| POST | `/insurance-claims` | Submit a claim against a policy for a plan | BillingSpecialist |
| GET | `/insurance-claims/{id}` | Get a claim | BillingSpecialist, ClinicAdmin |
| GET | `/insurance-claims` | List claims, filterable by policy or plan | BillingSpecialist, ClinicAdmin |
| POST | `/insurance-claims/{id}/approve` | Approve a claim; draws down lifetime-max | BillingSpecialist |
| POST | `/insurance-claims/{id}/deny` | Deny a submitted claim | BillingSpecialist |
| POST | `/insurance-claims/{id}/mark-paid` | Mark an approved claim paid | BillingSpecialist |
| POST | `/insurance-claims/{id}/void` | Void an approved claim; restores remaining-max | BillingSpecialist |
| POST | `/appointments` | Schedule an appointment | FrontDesk, ClinicAdmin |
| GET | `/appointments/{id}` | Get an appointment | FrontDesk, ClinicAdmin, Orthodontist, Guardian |
| GET | `/appointments` | List appointments, filterable by patient/provider/chair/plan/status | FrontDesk, ClinicAdmin, Orthodontist, Guardian |
| POST | `/appointments/{id}/check-in` | Move an appointment SCHEDULED to CHECKED_IN | FrontDesk |
| POST | `/appointments/{id}/complete` | Move an appointment CHECKED_IN to COMPLETED | Orthodontist |
| POST | `/appointments/{id}/cancel` | Cancel a scheduled appointment | FrontDesk |
| POST | `/appointments/{id}/no-show` | Mark an appointment a no-show | FrontDesk |
| GET | `/retainers/{id}` | Get a retainer | Orthodontist, ClinicAdmin, Guardian |
| GET | `/retainers` | List retainers, filterable by plan | Orthodontist, ClinicAdmin, Guardian |
| POST | `/retainers/{id}/replace` | Replace a retainer; issues a fresh one | Orthodontist |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_PLAN_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_ENTITY_STATE` | 409 |
| `ERR_NO_PHASES` | 409 |
| `ERR_RECORDS_INCOMPLETE` | 409 |
| `ERR_NO_ORTHO_RIDER` | 409 |
| `ERR_POLICY_TERMINATED` | 409 |
| `ERR_POLICY_HAS_OPEN_CLAIMS` | 409 |
| `ERR_CHAIR_CONFLICT` | 409 |
| `ERR_PROVIDER_CONFLICT` | 409 |
| `ERR_NOT_YET_DUE` | 409 |
| `ERR_TOO_EARLY_CHECKIN` | 409 |
| `ERR_TOO_EARLY_NOSHOW` | 409 |
| `ERR_DOWN_PAYMENT_EXCEEDS` | 409 |
| `ERR_OVERPAYMENT` | 409 |
| `ERR_CONTRACT_CLOSED` | 409 |
| `ERR_VALIDATION` | 422 |
