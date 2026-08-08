# Dental Insurance Verification & Billing API — Product Requirements Document

## 1. Introduction

Dental practices lose a great deal of revenue in the gap between the chair and the carrier: benefits are quoted verbally and never captured, claims go out without the attachments a payer demands, coordination-of-benefits math is done by hand, and patient balances drift out of sync with what insurance actually paid. This document specifies the requirements for a Dental Insurance Verification & Billing service that closes those gaps. The system is a ledger-and-workflow platform that carries a course of treatment from the front desk through to a reconciled balance: it snapshots plan breakdowns at verification time, estimates the insurer's share before service, orchestrates pre-authorizations and claims through their review loops, posts explanation-of-benefits (EOB) payments, and keeps each patient's running balance and each coverage's remaining benefit pool continuously correct.

Two engines sit at the heart of the platform. The first is a **reconciliation ledger**: every adjudication, patient payment, membership charge, and reversal is a bookkeeping event that immediately re-derives coverage benefit pools and patient balances, and every reversal exactly undoes the event it compensates. The second is a **workflow orchestrator**: claims, pre-authorizations, and memberships are state machines with non-linear revision loops — a denied claim can be appealed and re-adjudicated, a pended pre-authorization can be resubmitted, and a past-due membership can be brought current again. Because operational duties are split across front-office, billing, and management staff, the platform also enforces a segregation-of-duties rule so that the person who submits a claim can never be the person who posts its insurance payment.

All time-sensitive behavior — verification expiry, claim aging, frequency windows, and membership overdue calculations — is driven by a server-controlled logical clock rather than wall-clock time, so that test and billing scenarios are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes four roles: `FrontOffice`, `Biller`, `BillingManager`, and `Patient`.

- When `X-User-Role` is `FrontOffice`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. Front-desk staff register patients, build coverages, run benefit verifications, upload attachments, and enroll patients in memberships.
- When `X-User-Role` is `Biller`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. When a Biller submits a claim, the server records that identifier as the claim's `submitted_by_user_id`, but it is never compared to any entity's `id`; it exists only to anchor the later segregation-of-duties check.
- When `X-User-Role` is `BillingManager`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity, recorded as `submitted_by_user_id` when a manager submits a claim.
- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`. Ownership checks on any resource that references a patient compare the resource's `patient_id` to `X-User-ID`. A Patient may read and act only on resources they own; an attempt to read or pay against another patient's coverage, claim, payment, or membership is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership rule governs Patient-scoped reads and Patient-initiated patient-portion and membership-dues payments.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific workflow states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object.

### 2.4. Common Resource Properties and the Logical Clock

Most resources are "common-field" resources and carry a standard system-managed set: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits recording first creation; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and an integer `version` that starts at 1 and increments by one on each mutation. The `Attachment` resource is the sole exception: it is immutable after creation and therefore carries only `id` and `created_at` — it has neither `updated_at` nor `version`.

All time-sensitive evaluations — verification expiry, claim aging, frequency windows, and membership overdue boundaries — are measured against a **logical clock** rather than real wall-clock time. Before any clock is set, the server's clock reads `2026-05-01T00:00:00Z`. A billing manager may advance the clock to any instant by supplying a `to_iso8601` value; from that point on, every deadline, expiry, aging, and overdue computation uses the logical clock's value.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as whole integer cents. Where a calculation produces a fractional cent — for example when a coinsurance percentage or a monthly share of an annual fee is applied — the result is rounded half up to the nearest whole cent. The benefit estimate is deliberately computed **per line and then summed**: each procedure line's benefit is rounded half up before it is added into the running total, rather than summing exact values and rounding once at the end. Amounts sourced directly as integers (for example the paid amounts on an EOB) are used as supplied and require no rounding.

### 2.6. Existence and Left-to-Right Validation

Every referenced resource must exist. When a request names resources both in its path and in its body, the server validates them left to right — path identifiers first, in the order they appear, then body-referenced foreign keys — and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. For example, a request to create a verification under a coverage validates the coverage in the path before considering the body. Well-formedness of the body itself — required fields present, enum values legal, and integer amounts not negative — is checked with `ERR_INVALID_REQUEST` on any write endpoint.

### 2.7. Validation Ordering

When several checks guard a single endpoint, they are evaluated in a fixed priority order, and the first failing check determines the error returned. Across every endpoint the ordering is: (1) user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role permission (`ERR_FORBIDDEN_FOR_ROLE`); (3) existence of all referenced resources (`ERR_NOT_FOUND`); (4) Patient ownership (`ERR_NOT_RESOURCE_OWNER`); (5) body well-formedness (`ERR_INVALID_REQUEST`); then endpoint-specific business rules in the order described in their workflows.

For claim submission specifically, the business rules that follow well-formedness are evaluated in this order: coverage active (`ERR_COVERAGE_INACTIVE`), a verification record exists on the coverage (`ERR_VERIFICATION_REQUIRED`), the latest verification is not expired (`ERR_VERIFICATION_EXPIRED`), per-code frequency limits (`ERR_FREQUENCY_LIMIT_EXCEEDED`), required narrative present (`ERR_MISSING_NARRATIVE`), required attachment present (`ERR_MISSING_ATTACHMENT`), a secondary claim's primary is adjudicated (`ERR_PRIMARY_CLAIM_NOT_ADJUDICATED`), and remaining annual maximum available (`ERR_ANNUAL_MAXIMUM_EXCEEDED`). This means a coverage that has never been verified surfaces `ERR_VERIFICATION_REQUIRED`, while a coverage that was verified but whose snapshot has since lapsed surfaces `ERR_VERIFICATION_EXPIRED` — the two are distinct conditions with distinct precedence.

### 2.8. State Transition Guards

Every state-driven operation first confirms that its target resource is in a state from which the requested transition is legal. When a resource is not in an appropriate state — for instance, reversing a payment that is already reversed, or deciding a pre-authorization that is not currently under review — the request is rejected with `ERR_INVALID_STATE`. State enumeration values are exact uppercase strings and are used verbatim throughout this document.

### 2.9. Optimistic Concurrency on Coverage Verification

Creating a benefit verification against a coverage is guarded by optimistic concurrency control on the coverage. A verification create must carry `expected_coverage_version`, a non-optional field carrying the client's last observed `version` of the target coverage. A newly created verification supersedes the coverage's prior benefit snapshot — the plan breakdown is re-pulled — and this legitimately advances the coverage's `version` by one. If another writer has advanced the coverage's `version` since the client last read it, so that `expected_coverage_version` no longer equals the coverage's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from stacking a verification on top of a snapshot it never observed. Verification creation is the only endpoint that takes a version field; no other operation carries or checks one.

### 2.10. The Benefit Pool and Patient Balance Ledgers

Two running ledgers are kept continuously consistent. On each coverage, `benefits_used_cents` accumulates the insurer-paid amounts attributed to that coverage in the current benefit year, and `deductible_met_cents` accumulates the deductible satisfied so far; both are incremented when a claim is adjudicated and restored when the underlying payment is reversed. On each patient, `balance_cents` is the total patient responsibility owed, and it is re-derived — never blindly incremented in isolation — whenever a claim is adjudicated, denied, or closed, whenever a patient or membership payment posts, whenever a payment is reversed, and whenever membership billing runs. A patient's `status` is a direct function of that balance.

Every reversal is **compensating**: reversing an insurance payment restores the coverage's benefit pool and deductible to their pre-posting values and rolls the claim back, and reversing a patient payment restores the dues or portion it had cleared. The net effect of an appeal-driven re-adjudication is that the coverage's benefit pool reflects only the most recent EOB, not the sum of the original and the correction.

### 2.11. Claim Aging

While a claim is submitted and not yet closed, its age is tracked. The `aging_days` value is the whole number of days between the claim's `submitted_at` and the current logical clock (the fractional remainder is dropped); it is 0 before a claim is submitted and for a closed claim. From that, an `aging_bucket` is derived: `CURRENT` when `aging_days` is 30 or fewer; `DAYS_31_60` when it is between 31 and 60 inclusive; `DAYS_61_90` when it is between 61 and 90 inclusive; and `DAYS_90_PLUS` when it is 91 or more. Aging is recomputed on read of a non-closed claim and refreshed system-wide whenever a billing run executes.

## 3. Business Logic & Workflows

### 3.1. Catalog and Party Setup

Before any billing can occur, the practice configures its reference data and registers its parties. A **Patient** is registered with a `full_name`, a `date_of_birth` (an ISO date in `YYYY-MM-DD` form), and a contact `email`. A new patient begins with `status` of `ACTIVE` and a `balance_cents` of 0; both are computed thereafter and are never supplied by the client. A patient's `status` becomes `COLLECTIONS` whenever the derived `balance_cents` rises above the collections threshold of 50,000 cents, and returns to `ACTIVE` when it falls back to that threshold or below.

A billing manager configures the carriers' plans. An **InsurancePlan** carries a `payer_name` and a `plan_name`, plus the benefit structure: `annual_maximum_cents` (the per-benefit-year ceiling, defaulting to 150000), `deductible_cents` (defaulting to 5000), and `deductible_applies_to` — the set of benefit categories the deductible applies to, drawn from `PREVENTIVE`, `BASIC`, and `MAJOR` and defaulting to `BASIC` and `MAJOR`. The plan's payment percentages are `preventive_coinsurance_pct` (default 100), `basic_coinsurance_pct` (default 80), and `major_coinsurance_pct` (default 50); each is the whole-number percent the plan pays for that category. Finally, `cob_method` governs how the plan coordinates when it is the secondary payer and is either `STANDARD` (the default) or `NON_DUPLICATION`.

The clinical catalog is a set of **Procedure** entries. Each is keyed by a `cdt_code` (a CDT procedure code, unique across the catalog) and carries a human `description`, a `category` of `PREVENTIVE`, `BASIC`, or `MAJOR`, and a `ucr_fee_cents` — the usual-and-customary allowed fee that serves as the plan-allowed amount. A procedure may declare a `frequency_limit_per_year` (the maximum number of submitted occurrences permitted in a rolling window; when null, occurrences are unlimited), a `requires_narrative` flag (default false), and a `requires_attachment` flag (default false).

The practice's in-house plans are **MembershipPlan** entries, each with a `name`, an `annual_fee_cents`, a `billing_period` of `MONTHLY` (the default) or `ANNUAL`, a `discount_pct` (default 0) applied to included procedures, and an `included_cdt_codes` list (default empty) naming the CDT codes the membership covers.

### 3.2. Coverage, Coordination of Benefits, and Verification

A patient's relationship to a carrier is recorded as a **Coverage**, which links a patient to an insurance plan and is created with a `patient_id`, an `insurance_plan_id`, a coordination `priority` of `PRIMARY` or `SECONDARY`, the `subscriber_id` held with the carrier, an optional `relationship` describing the patient's tie to the subscriber (`SELF` — the default — `SPOUSE`, `CHILD`, or `OTHER`), an inclusive `effective_date`, and an inclusive `term_date`. A coverage's `status` is computed against the logical clock: it is `ACTIVE` when the clock falls on or between the effective and term dates, and `TERMINATED` otherwise. Each coverage keeps its own benefit-year ledger fields `benefits_used_cents` and `deductible_met_cents`, both starting at 0. A patient may hold both a primary and a secondary coverage, which is how coordination of benefits is expressed. Creating a coverage that would overlap an existing active coverage for the same patient and plan is rejected with `ERR_COVERAGE_OVERLAP`; overlap here is judged on closed intervals, so two coverages that merely touch at a shared boundary date count as overlapping.

Benefits must be verified before they can be billed. Running a verification against a coverage snapshots the plan breakdown at that moment into a **Verification** record: `verified_annual_maximum_cents`, `verified_deductible_cents`, `verified_preventive_pct`, `verified_basic_pct`, and `verified_major_pct` are captured from the plan, along with the `coverage_id` the snapshot belongs to. The server stamps `verified_at` with the logical clock at creation and computes `expires_at` as 30 days after `verified_at`. A verification's `status` is `VERIFIED` while the clock is at or before `expires_at`, and `EXPIRED` once the clock passes it. Creating a verification supersedes any prior snapshot for that coverage and advances the coverage's `version`, and is subject to the optimistic-concurrency rule in §2.9: the caller must present `expected_coverage_version` equal to the coverage's current `version`, or the request is rejected with `ERR_STALE_VERSION`.

### 3.3. Pre-Authorization Lifecycle

Before performing costly work, a biller may seek a carrier pre-authorization. A **PreAuthorization** is created in `DRAFT` with a `patient_id`, a `coverage_id`, a list of `procedures`, and an optional `narrative`. Each entry in `procedures` is a line object naming a `cdt_code`, an optional `tooth`, and a `billed_fee_cents`. On creation the pre-authorization starts with `attachment_count` of 0; that count reflects the number of attachments whose target is this pre-authorization.

Submitting a pre-authorization advances it from `DRAFT` to `SUBMITTED`. Submission requires that `procedures` be non-empty, and that if any line's procedure requires an attachment, at least one attachment is present (`attachment_count` of 1 or more), failing which the submission is rejected with `ERR_MISSING_ATTACHMENT`. On a successful submission the system computes `estimated_benefit_cents` — the projected insurer benefit over the pre-authorization's lines, using the same benefit-estimate logic that governs claims (§3.5) — and stamps `submitted_at` with the logical clock on the first submission.

Once submitted, the carrier's response is recorded as a decision carrying an `outcome`. An `APPROVED` outcome moves the pre-authorization to the terminal `APPROVED` state and sets `approved_amount_cents` equal to the current `estimated_benefit_cents`. A `DENIED` outcome moves it to the terminal `DENIED` state. A `PENDED` outcome moves it to `PENDED`, signaling the carrier needs more information. A pended pre-authorization forms a revision loop: after the biller adds the missing documentation, resubmitting moves it back from `PENDED` to `SUBMITTED` (again requiring an attachment when any line demands one, else `ERR_MISSING_ATTACHMENT`) and recomputes `estimated_benefit_cents`. Deciding a pre-authorization that is not currently `SUBMITTED`, or submitting from a state other than `DRAFT` or `PENDED`, is rejected with `ERR_INVALID_STATE`.

### 3.4. Attachments

Clinical documentation is uploaded as an **Attachment**, which is deliberately polymorphic: it may hang off either a claim or a pre-authorization, but never both and never neither. An attachment carries exactly one of `claim_id` or `preauth_id` to name its target, a `kind` drawn from `XRAY`, `PERIO_CHART`, `NARRATIVE`, `PHOTO`, or `OTHER`, a `filename`, and an optional `note`. If neither target is supplied, or both are, the upload is rejected with `ERR_ATTACHMENT_TARGET_REQUIRED`. A successful upload increments the `attachment_count` of its target pre-authorization (or, for a claim, contributes to the attachment total the claim's submit-time checks consult). Attachments are immutable once created and therefore carry no `updated_at` or `version`.

### 3.5. Claim Creation, Estimation, and Submission

A **Claim** is the core billing artifact. It is created in `DRAFT` with a `patient_id`, the `coverage_id` it bills against, a list of `procedures` (each line an object with a `cdt_code`, an optional `tooth`, and a `billed_fee_cents`), a `service_date` (the ISO date of service, which drives both the frequency window and aging), and optionally a `narrative`, a `preauth_id` linking a prior pre-authorization, and a `primary_claim_id`. On creation the system computes `total_billed_cents` as the sum of the line `billed_fee_cents` values. The `primary_claim_id` is set only on a secondary-coverage claim and points at the corresponding primary claim; it is how a self-referential coordination-of-benefits chain is expressed.

Submitting a claim advances it from `DRAFT` to `SUBMITTED` and is where the platform's verification, frequency, and fiscal gates fire, in the order given in §2.7. The billing coverage must be `ACTIVE`, or the submission is rejected with `ERR_COVERAGE_INACTIVE`. The coverage must have at least one verification record on file, or the submission is rejected with `ERR_VERIFICATION_REQUIRED`; and that latest verification must not be expired at the current clock, or it is rejected with `ERR_VERIFICATION_EXPIRED`. For each line whose procedure declares a `frequency_limit_per_year`, the system counts prior occurrences of the same `cdt_code` across that patient's claims whose `status` is `SUBMITTED`, `ADJUDICATED`, `APPEALED`, or `CLOSED`, whose `service_date` falls within the 365-day window ending on this claim's `service_date` (the window is inclusive and this claim is not counted); if that prior count is already at or above the limit, the submission is rejected with `ERR_FREQUENCY_LIMIT_EXCEEDED`. In other words, the occurrence numbered equal to the limit is permitted and the next one past it is refused. If any line's procedure requires a narrative, a non-empty `narrative` must be present, or the submission is rejected with `ERR_MISSING_NARRATIVE`. If any line's procedure requires an attachment, at least one attachment naming this claim must be present, or it is rejected with `ERR_MISSING_ATTACHMENT`. When `primary_claim_id` is set, the referenced primary claim must already be `ADJUDICATED`, `DENIED`, or `CLOSED`, or the submission is rejected with `ERR_PRIMARY_CLAIM_NOT_ADJUDICATED`.

On a successful submission the system records `submitted_by_user_id` as the acting `X-User-ID` (the segregation-of-duties anchor) and stamps `submitted_at` with the logical clock, then computes the forward-looking estimate. The **benefit estimate** is produced from the coverage's verified snapshot and the claim's own lines, processed in the exact order supplied. The system first sets a running remaining maximum to `verified_annual_maximum_cents` minus the coverage's `benefits_used_cents`, and a running remaining deductible to the greater of 0 and `verified_deductible_cents` minus the coverage's `deductible_met_cents`. It then walks each line: the line's allowed amount is the lesser of its `billed_fee_cents` and the procedure's `ucr_fee_cents`; the applicable percentage is the verified preventive, basic, or major percent according to the procedure's `category`. If the procedure's category is among the plan's `deductible_applies_to` set, the system takes a deductible bite equal to the lesser of the remaining deductible and the allowed amount, and reduces the remaining deductible by that bite; otherwise no deductible is applied to that line. The line's benefit is the allowed amount minus its deductible bite, multiplied by the applicable percent, divided by 100, and rounded half up to whole cents — this rounding happens per line, before summing. That per-line benefit is then capped at the current remaining maximum, the remaining maximum is reduced by the (capped) benefit, and the benefit is added into the running `estimated_insurance_cents`. After all lines, `estimated_patient_portion_cents` is `total_billed_cents` minus `estimated_insurance_cents`. The default plan percentages, absent a more specific verified value, are 100 for preventive, 80 for basic, and 50 for major.

The annual-maximum gate is distinct from the per-line cap. Submission is refused with `ERR_ANNUAL_MAXIMUM_EXCEEDED` only when the coverage has **no remaining benefit at all** — that is, when `verified_annual_maximum_cents` minus `benefits_used_cents` is 0 or negative. When some benefit remains but it is smaller than the uncapped estimate, the estimate is simply capped at what remains and the claim is allowed through; only the fully-exhausted case is rejected.

When a claim bills a secondary coverage (its `primary_claim_id` is set), the estimate uses **coordination of benefits** instead of the plain estimate. The system first computes the normal benefit — the ordinary per-line estimate over the secondary plan's snapshot. It then reads the primary claim's `paid_insurance_cents`, and computes an allowed basis as the sum over the secondary claim's lines of the lesser of each line's `billed_fee_cents` and its procedure's `ucr_fee_cents`. The patient's post-primary remainder is that allowed basis minus what the primary paid. If the secondary plan's `cob_method` is `STANDARD`, the secondary benefit is the lesser of the normal benefit and the post-primary remainder. If it is `NON_DUPLICATION`, the secondary benefit is the greater of 0 and the normal benefit minus what the primary already paid — which is frequently 0. The resulting secondary benefit becomes the claim's `estimated_insurance_cents`.

### 3.6. Adjudication, Denial, and Appeal

A claim is adjudicated by posting the carrier's EOB as an insurance payment (§3.7), which moves it from `SUBMITTED` to `ADJUDICATED`. At that point the system records the **final settlement**: `paid_insurance_cents` becomes the sum of the paid amounts on the EOB lines, `adjudicated_at` is stamped with the clock, and `final_patient_portion_cents` becomes `total_billed_cents` minus `paid_insurance_cents`. Because the final settlement uses the carrier's actual paid amounts rather than the pre-service forecast, `final_patient_portion_cents` generally differs from the earlier `estimated_patient_portion_cents`. Adjudication then cascades: the patient's `balance_cents` is re-derived to fold in the newly opened patient portion, the patient's `status` is recomputed (`COLLECTIONS` above 50,000 cents, else `ACTIVE`), and — in parallel — the billing coverage's `benefits_used_cents` is increased by the paid amount and its `deductible_met_cents` by the total deductible applied across the EOB lines.

A denial is posted the same way but flagged, moving the claim from `SUBMITTED` to `DENIED`. On a denial, `paid_insurance_cents` is 0, `adjudicated_at` is stamped, and `final_patient_portion_cents` becomes the full `total_billed_cents`; the patient's balance is re-derived to reflect that the entire billed amount is now their responsibility.

Both a denied claim and an under-paid adjudicated claim can be **appealed**, moving the claim to `APPEALED` and incrementing `appeal_count` by one. Appeals are capped: a claim may be appealed only while it is `DENIED` or `ADJUDICATED` and only while its `appeal_count` is below the limit of 2; an attempt outside those conditions is rejected with `ERR_APPEAL_NOT_ALLOWED`. An appealed claim is resolved by posting a fresh insurance payment, which closes the revision loop: a non-denial posting moves it from `APPEALED` back to `ADJUDICATED`, and a denial posting moves it from `APPEALED` to `DENIED`. Re-adjudication is compensating — the system first reverses the coverage benefit-pool, deductible, and patient-balance deltas of the prior settlement, then applies the new EOB, so the coverage's `benefits_used_cents` ends up reflecting only the latest EOB rather than the sum of both. After re-adjudication `final_patient_portion_cents` and the patient's `balance_cents` are recomputed; a denial on appeal sets `paid_insurance_cents` back to 0 and `final_patient_portion_cents` back to the full `total_billed_cents`.

### 3.7. Posting and Reversing Payments

A **Payment** records money moving in the system and carries a `patient_id`, a `payer_type` of `INSURANCE` or `PATIENT`, an `amount_cents`, and — for insurance and for claim-directed patient payments — a `claim_id`. Every payment begins `POSTED` and is stamped with `posted_at` at the logical clock. A payment's `claim_id`, when present, must name a claim that is in a postable state and whose patient and coverage match the payment; otherwise the posting is rejected with `ERR_PAYMENT_CLAIM_MISMATCH`.

An **insurance** payment carries the EOB as `eob_lines`, a list of objects each naming a `cdt_code`, an `allowed_cents`, a `paid_cents`, and a `deductible_applied_cents`, and may set `is_denial`. A normal insurance posting (`is_denial` false) adjudicates the claim per §3.6, deriving `paid_insurance_cents` from the sum of the line `paid_cents` and driving the coverage and patient cascades; a denial posting (`is_denial` true) records a full denial with zero paid and drives the claim to `DENIED`. Insurance postings are governed by **segregation of duties**: the posting user's `X-User-ID` must differ from the claim's `submitted_by_user_id`, or the posting is rejected with `ERR_SEGREGATION_OF_DUTIES` — the person who submitted a claim may never post its insurance payment.

A **patient** payment applies against the patient's responsibility. When it names a claim, `amount_cents` added to the claim's existing `patient_paid_cents` may not exceed the claim's `final_patient_portion_cents`, or the payment is rejected with `ERR_OVERPAYMENT`. A valid patient payment increases the claim's `patient_paid_cents` by `amount_cents` and decreases the patient's `balance_cents` by the same; when the accumulated `patient_paid_cents` reaches the `final_patient_portion_cents` exactly, the claim moves to `CLOSED`. A patient may pay against either an `ADJUDICATED` or a `DENIED` claim, and either can transition to `CLOSED` once its patient portion is fully paid.

Any posted payment may be **reversed** by a billing manager, which moves it from `POSTED` to `REVERSED`; reversing a payment that is not `POSTED` is rejected with `ERR_INVALID_STATE`. Reversal is fully compensating. Reversing an insurance payment restores the coverage's `benefits_used_cents` and `deductible_met_cents` to their pre-posting values, reverts the claim's `paid_insurance_cents` and `final_patient_portion_cents`, returns the claim to `SUBMITTED`, and restores the patient's `balance_cents`. Reversing a patient payment subtracts its `amount_cents` back out of the claim's `patient_paid_cents` and adds it back to the patient's `balance_cents`, and if the claim had been `CLOSED` by that payment it returns to its prior adjudicated state.

### 3.8. Membership Enrollment and Billing

Independently of insurance, a patient may enroll in an in-house **Membership**. Enrollment names a `patient_id` and a `membership_plan_id` and defines the active period with a `period_start` (inclusive ISO date) and a `period_end` (exclusive ISO date — the interval is half-open). A new membership starts `ACTIVE`, is stamped with `enrolled_at` at the clock, and sets its `paid_through_date` to the `period_start`. Its `next_billing_date` is the `paid_through_date` advanced by one billing period, its `balance_cents` is the outstanding dues owed, and its `past_due_periods` counter starts at 0. A new membership may not overlap an existing non-cancelled membership for the same patient; overlap here is judged on half-open intervals, so two memberships that meet exactly at a boundary date are allowed, but any true overlap is rejected with `ERR_MEMBERSHIP_OVERLAP`.

Membership dues are charged by a billing run. For each non-cancelled membership, the period fee is the full `annual_fee_cents` when the plan bills annually, or the `annual_fee_cents` divided by 12 and rounded half up when it bills monthly. A membership is considered overdue only once the clock is strictly past its `paid_through_date` plus a 15-day grace window — being exactly at the end of grace is not yet overdue. When a run finds an overdue membership, it adds one period fee to the membership's `balance_cents`, increments `past_due_periods` by one, moves the membership to `PAST_DUE`, and cascades the same dues amount into the patient's `balance_cents`. If that increment brings `past_due_periods` to 2 or more, the membership is moved to the terminal `CANCELLED` state.

A past-due membership is brought current by paying dues, which requires a positive `balance_cents` and a non-cancelled membership; a payment against a membership with no balance (or a cancelled one) is rejected with `ERR_MEMBERSHIP_NOT_PAYABLE`. A dues payment of `amount_cents` reduces the membership's `balance_cents`, advances its `paid_through_date`, resets `past_due_periods` to 0, moves the membership from `PAST_DUE` back to `ACTIVE`, and reduces the patient's `balance_cents` by the amount paid.

### 3.9. Balances, Aging, and the Billing Run

A patient's `balance_cents` is always the sum of two streams: across the patient's `ADJUDICATED` and `DENIED` claims, the still-open patient portion of each (the `final_patient_portion_cents` not yet covered by `patient_paid_cents`, never counted below zero); plus the outstanding dues `balance_cents` across the patient's memberships. Whenever that sum exceeds the collections threshold of 50,000 cents the patient's `status` is `COLLECTIONS`, and otherwise it is `ACTIVE`. This balance is re-derived on every event that can move it — claim adjudication, denial, or closure; patient or membership payment; payment reversal; and membership billing.

The billing run is an administrative, system-driven sweep with no request body: it charges every lapsed membership period (moving memberships to `PAST_DUE` or `CANCELLED` as described in §3.8), recomputes claim aging across all non-closed claims so that `aging_days` and `aging_bucket` reflect the current clock, and re-derives affected patient balances. The clock itself is moved by a separate administrative capability that advances the logical clock to a supplied instant, after which every subsequent expiry, aging, frequency, and overdue evaluation reads from the new clock value.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource, run a system process, or set the clock return `200 OK`. All list and get operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | BillingManager |
| POST | `/billing/run` | Run membership billing and aging recompute | BillingManager |
| POST | `/patients` | Create a Patient | FrontOffice, BillingManager |
| GET | `/patients/{patientId}` | Get a Patient with computed balance and status | FrontOffice, Biller, BillingManager, Patient |
| POST | `/insurance-plans` | Create an InsurancePlan | BillingManager |
| POST | `/procedures` | Create a Procedure catalog entry | BillingManager |
| POST | `/membership-plans` | Create a MembershipPlan | BillingManager |
| POST | `/coverages` | Create a Coverage | FrontOffice, BillingManager |
| GET | `/coverages/{coverageId}` | Get a Coverage | FrontOffice, Biller, BillingManager, Patient |
| GET | `/coverages` | List or filter Coverages | FrontOffice, Biller, BillingManager, Patient |
| POST | `/coverages/{coverageId}/verifications` | Create a benefit Verification snapshot (OCC on Coverage) | FrontOffice, BillingManager |
| GET | `/verifications/{verificationId}` | Get a Verification | FrontOffice, Biller, BillingManager |
| GET | `/verifications` | List or filter Verifications | FrontOffice, Biller, BillingManager |
| POST | `/preauthorizations` | Create a DRAFT PreAuthorization | Biller, BillingManager |
| GET | `/preauthorizations/{preauthId}` | Get a PreAuthorization | FrontOffice, Biller, BillingManager |
| GET | `/preauthorizations` | List or filter PreAuthorizations | FrontOffice, Biller, BillingManager |
| POST | `/preauthorizations/{preauthId}/submit` | Submit or resubmit a PreAuthorization | Biller, BillingManager |
| POST | `/preauthorizations/{preauthId}/decision` | Record the carrier decision | Biller, BillingManager |
| POST | `/attachments` | Upload an attachment to one of a Claim or PreAuthorization | FrontOffice, Biller, BillingManager |
| GET | `/attachments/{attachmentId}` | Get an Attachment | FrontOffice, Biller, BillingManager |
| GET | `/attachments` | List or filter Attachments | FrontOffice, Biller, BillingManager |
| POST | `/claims` | Create a DRAFT Claim | Biller, BillingManager |
| GET | `/claims/{claimId}` | Get a Claim with aging and estimate/final fields | Biller, BillingManager, Patient |
| GET | `/claims` | List or filter Claims | Biller, BillingManager, Patient |
| POST | `/claims/{claimId}/submit` | Submit a Claim, running validations and estimate | Biller, BillingManager |
| POST | `/claims/{claimId}/appeal` | Appeal a DENIED or ADJUDICATED Claim | Biller, BillingManager |
| POST | `/payments` | Post an INSURANCE EOB payment or a PATIENT-portion payment | Biller, BillingManager, Patient |
| GET | `/payments/{paymentId}` | Get a Payment | Biller, BillingManager, Patient |
| GET | `/payments` | List or filter Payments | Biller, BillingManager, Patient |
| POST | `/payments/{paymentId}/reverse` | Reverse a POSTED payment | BillingManager |
| POST | `/memberships` | Enroll a Patient in a MembershipPlan | FrontOffice, BillingManager, Patient |
| GET | `/memberships/{membershipId}` | Get a Membership | FrontOffice, BillingManager, Patient |
| GET | `/memberships` | List or filter Memberships | FrontOffice, BillingManager, Patient |
| POST | `/memberships/{membershipId}/pay` | Pay membership dues | Patient, FrontOffice, BillingManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ATTACHMENT_TARGET_REQUIRED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PAYMENT_CLAIM_MISMATCH` | 409 Conflict |
| `ERR_PRIMARY_CLAIM_NOT_ADJUDICATED` | 409 Conflict |
| `ERR_COVERAGE_INACTIVE` | 409 Conflict |
| `ERR_VERIFICATION_REQUIRED` | 409 Conflict |
| `ERR_VERIFICATION_EXPIRED` | 409 Conflict |
| `ERR_FREQUENCY_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_MISSING_NARRATIVE` | 422 Unprocessable Entity |
| `ERR_MISSING_ATTACHMENT` | 422 Unprocessable Entity |
| `ERR_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_MEMBERSHIP_OVERLAP` | 409 Conflict |
| `ERR_ANNUAL_MAXIMUM_EXCEEDED` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_APPEAL_NOT_ALLOWED` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_PAYABLE` | 409 Conflict |
