# Hospital Revenue Cycle API — Product Requirements Document

## 1. Introduction

A hospital's revenue cycle is the financial spine of every patient encounter: it begins the moment a patient is registered for admission and does not end until the resulting account is either fully settled or formally written off. This API governs that entire arc — admission registration, insurance eligibility verification, charge capture, ICD-10 and CPT coding, payer clearance and adjudication, the computation of patient responsibility against deductible, coinsurance and out-of-pocket maximums, and the eventual bad-debt write-off of uncollectable balances. Each of these stages is performed by a different functional team, and the correctness of the whole depends on each team's work being recorded against a single, consistent account.

The system models that account as an **Encounter** and surrounds it with the supporting records a billing office needs: payers and their filing rules, patient master records, insurance policies and the benefit accumulators that track year-to-date spending, captured charges, coding assignments, submitted claims and their adjudicated lines, patient statements, payments, and write-offs. These records reference one another by identifier rather than nesting in a strict ownership tree, reflecting how a real billing system reconciles many peer ledgers into one financial picture.

Two properties dominate the design. First, **segregation of duties**: registration, coding, billing, and financial write-off approval are deliberately separated so that no single operator can both finalize what is owed and forgive it. Second, **financial determinism**: every monetary figure is reconciled the instant money or coverage moves, and concurrent writers are prevented from acting on stale views of an account. The remainder of this document specifies the global contract every endpoint shares (§2), the business workflows and their scattered rules (§3), the endpoint surface (§4), and the catalogue of error identifiers (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an opaque string identifying the individual operator, and `X-User-Role`, naming the operator's functional role. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Exactly four roles exist, spelled as follows: `Registrar`, `Coder`, `BillingSpecialist`, and `FinanceManager`. A `Registrar` handles front-desk registration, eligibility verification, charge capture, and discharge. A `Coder` assigns and finalizes diagnostic and procedure coding. A `BillingSpecialist` clears coding for billing, submits and adjudicates claims, bills patients, and posts payments. A `FinanceManager` approves bad-debt write-offs. All four roles may read any resource through the GET endpoints, and any of the four may set the test clock.

For all four roles — `Registrar`, `Coder`, `BillingSpecialist`, and `FinanceManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`. It may, however, record it where a workflow explicitly captures the acting operator: when a `Coder` finalizes a coding assignment the server writes the caller's `X-User-ID` into `finalized_by_user_id` on that `CodingAssignment`, and when a `FinanceManager` approves a write-off the server writes the caller's `X-User-ID` into `approved_by_user_id` on the resulting `WriteOff`. These recorded identifiers are later compared **to each other** — never to any entity `id` — to enforce the segregation-of-duties rule described in §2.4 and §3.

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

List endpoints accept two pagination parameters: `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. List results are returned in ascending order of `created_at` — that is, oldest first. The pagination envelope fields `limit`, `offset`, `total_count`, and `has_more` are reported inside `meta`: `total_count` is the count of all records matching the query before pagination, and `has_more` is true when records remain beyond the current page.

### 2.4. Common Resource Properties and Record Identity

Every resource carries a server-minted `id`, which is a UUID with no type prefix and serves as identity only. Every resource also carries a `created_at` timestamp, formatted as an ISO 8601 UTC instant with three fractional digits, recording when the record was first created.

Most resources are mutable accounts that additionally carry two fields: an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation, and a `version` integer that starts at 1 and increments by exactly 1 each time the resource is mutated. The `Payer`, `Patient`, `InsurancePolicy`, `BenefitAccumulator`, `Encounter`, `EligibilityCheck`, `Charge`, `CodingAssignment`, `Claim`, `ClaimLine`, and `PatientStatement` resources all carry `updated_at` and `version`. Two resources are immutable ledger entries once written — `Payment` and `WriteOff` — and these carry only `id` and `created_at`; they have no `updated_at` and no `version` field at all.

### 2.5. Monetary Precision and Reconciliation

All monetary amounts are stored and exchanged as integer **cents**. Aggregations such as a charge total are exact integer sums with no rounding. Where a percentage is applied — specifically the coinsurance computation — the product is rounded to whole cents using the round-half-up convention (a fractional cent of exactly one half rounds up). Several fields are **derived** rather than supplied: `total_charges_cents`, `patient_responsibility_cents`, and `account_balance_cents` on an encounter, the `deductible_met_cents` and `oop_met_cents` on a benefit accumulator, the `amount_cents` on a charge, the `line_paid_cents` on a claim line, and the `amount_due_cents`, `amount_paid_cents`, and `written_off_cents` on a statement are all computed and reconciled by the server whenever the underlying money or coverage moves. Clients never set these directly; the §3 workflows define exactly when each is recomputed.

### 2.6. Nested Resource Access and Reference Integrity

Many resources are addressed under a parent path — a charge under its encounter, a claim under its encounter, a payment under its statement. Path identifiers are validated left-to-right: the parent identifier is resolved before the child, and the first identifier in the path that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). Separately, any foreign key supplied in a request body — for example the `patient_id` and `payer_id` on a new policy, or the `payer_id` on a claim submission — must reference an existing record; a body reference that does not resolve yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 2.7. Request Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing or malformed header yields `ERR_UNAUTHENTICATED` (401). Role authorization is checked second: a role not permitted for the endpoint yields `ERR_FORBIDDEN_ROLE` (403). Third, path identifiers are resolved left-to-right, with any missing one yielding `ERR_NOT_FOUND` (404). Fourth, body foreign keys are resolved, with any missing one yielding `ERR_REFERENCE_NOT_FOUND` (404). Fifth, the request body itself is validated — required fields present, correct types, and enum values within their allowed sets — with violations yielding `ERR_INVALID_REQUEST` (400), and numeric fields outside their permitted range yielding `ERR_VALIDATION_OUT_OF_RANGE` (422). Sixth, the target resource's state is checked: if the requested transition is not defined from the resource's current state, the request yields `ERR_INVALID_STATE` (409). Only after all six of these structural gates pass are the domain-specific business rules of §3 — referential, safety, temporal, fiscal, and concurrency checks — evaluated. The practical consequence is that a structural failure (wrong role, missing resource, malformed body, wrong state) always surfaces before any business-rule failure such as a timely-filing or segregation-of-duties violation.

### 2.8. Optimistic Concurrency Control

Two write operations require the caller to declare the version of the parent record they believe they are acting on, so that a writer cannot silently overwrite changes made by another writer since the caller last read the record.

Submitting a claim against an encounter requires the request body to include `expected_encounter_version` carrying the client's last observed `version` of that `Encounter`. If this value does not match the encounter's current `version` — for instance because another writer's claim submission has already advanced the encounter to `BILLED` and bumped its version — the submission is rejected with `ERR_STALE_ENCOUNTER_VERSION` (HTTP 412), and no claim is created.

Approving a bad-debt write-off against a patient statement requires the request body to include `expected_patient_statement_version` carrying the client's last observed `version` of that `PatientStatement`. If this value does not match the statement's current `version` — for instance because a late patient payment has just been posted, advancing the statement and reducing the outstanding balance — the write-off is rejected with `ERR_STALE_STATEMENT_VERSION` (HTTP 412), and no write-off is recorded. These are the only two endpoints that accept a version field; no other write endpoint takes one.

### 2.9. Cascading Reconciliation and State Propagation

Several operations deliberately reach beyond the resource they target to keep the encounter account consistent. When such a propagation occurs, every record it touches has its `updated_at` refreshed and its `version` incremented by 1. Clearing a finalized coding assignment bubbles its encounter forward; adjudicating, denying, correcting, or appealing a claim mutates the encounter and may create or reverse a statement and advance a benefit accumulator; and settling or writing off a statement bubbles its encounter to closure. These cascades are not optional side notes — they are part of the operation's contract, and §3 enumerates each one. A cascade that should advance an encounter only fires when the encounter is in the precise predecessor state the transition requires.

## 3. Business Logic & Workflows

### 3.1. Registering Payers, Patients, and Policies

The reference data of the revenue cycle is established before any encounter can be billed. A payer record is created with a `name` (non-empty, at most 120 characters) and a `payer_type`, which must be one of `COMMERCIAL`, `MEDICARE`, `MEDICAID`, or `SELF_PAY`. A payer also carries the filing rules that later govern its claims: `timely_filing_days`, an integer between 1 and 365 defaulting to 90, is the number of days after discharge within which a claim must reach the payer; `appeal_window_days`, an integer between 1 and 180 defaulting to 30, is the number of days after a denial within which an appeal may be filed; and `active`, a boolean defaulting to true, indicates whether the payer is currently accepting new claims. Both a `Registrar` and a `BillingSpecialist` may create payers.

A patient master record is registered by a `Registrar` with a `full_name` (non-empty, at most 120 characters) and a `date_of_birth`, which is an ISO 8601 calendar date (YYYY-MM-DD) that must lie in the past. A patient also carries a `financial_class` describing how the account is expected to settle — one of `INSURED`, `SELF_PAY`, or `CHARITY`, defaulting to `INSURED`.

An insurance policy ties a patient to a payer and records the benefit terms. The `Registrar` supplies the `patient_id` of the covered patient, the `payer_id` of the paying insurer, a non-empty `member_number`, a `plan_year` (an integer between 2000 and 2100) naming the benefit year the terms apply to, and three monetary terms: `deductible_cents`, the annual individual deductible the patient must meet before coinsurance applies (an integer of at least 0); `coinsurance_pct`, the patient's coinsurance share applied to the allowed amount after the deductible is met, expressed as a fraction between 0.0 and 1.0 inclusive; and `oop_max_cents`, the annual out-of-pocket maximum. The `patient_id` and `payer_id` references are resolved first, ahead of the remaining body fields: a `patient_id` or `payer_id` that is absent or not a string yields `ERR_INVALID_REQUEST`, while one that is a string but does not resolve to an existing record yields `ERR_REFERENCE_NOT_FOUND` (`patient_id` is checked before `payer_id`). A `coinsurance_pct` outside the 0.0–1.0 range, a `deductible_cents` below 0, or an `oop_max_cents` that is less than `deductible_cents`, is rejected with `ERR_VALIDATION_OUT_OF_RANGE`. A newly created policy begins in `UNVERIFIED` status.

### 3.2. Policy Verification, Benefit Accumulators, and Termination

A policy does not become billable simply by existing; a `Registrar` must verify it. Verification is defined only from `UNVERIFIED` status and additionally requires that the referenced payer's `active` flag is true — an attempt to verify against an inactive payer is rejected with `ERR_PAYER_INACTIVE`. On success the policy transitions `UNVERIFIED → ACTIVE`, and the system simultaneously opens the policy's **benefit accumulator** for the policy's `plan_year`: a `BenefitAccumulator` record referencing the policy by `policy_id`, with `deductible_met_cents` initialized to 0 and `oop_met_cents` initialized to 0. The accumulator's `deductible_met_cents` tracks the year-to-date amount applied toward the deductible and never exceeds the policy's `deductible_cents`; its `oop_met_cents` tracks the year-to-date patient out-of-pocket (deductible plus coinsurance) and never exceeds the policy's `oop_max_cents`. Only an `ACTIVE` policy will clear eligibility.

A policy may later be terminated by a `Registrar`. Termination is defined only from `ACTIVE` status and is permitted only when no encounter referencing this policy is still open — that is, every encounter that references the policy must be in `CLOSED` status. If any referencing encounter is in any status other than `CLOSED`, termination is rejected with `ERR_POLICY_IN_USE`. On success the policy transitions `ACTIVE → TERMINATED`, which is terminal.

### 3.3. Admission, Charge Capture, and Discharge

Registration of an admission creates an **Encounter** — the central account around which the whole cycle revolves. A `Registrar` supplies the `patient_id` of the registered patient, an `admission_at` ISO 8601 UTC timestamp, and optionally a `policy_id` naming the insurance policy billed for this encounter; the `policy_id` is left null for self-pay encounters. A new encounter begins in `REGISTERED` status with a `discharge_at` of null while it remains open.

While the encounter is open, the `Registrar` captures charges against it. Each charge records a `cpt_code` — a five-character alphanumeric CPT or HCPCS procedure code — together with `units` (an integer of at least 1) and a `unit_price_cents` chargemaster price per unit (an integer of at least 0). The server computes the charge's `amount_cents` as `units` multiplied by `unit_price_cents`, and a new charge begins in `POSTED` status. A charge may be posted only while the encounter is in `REGISTERED` or `ELIGIBILITY_VERIFIED` status; charge capture closes at discharge, so an attempt to post a charge to an encounter in any later status is rejected with `ERR_CHARGES_CLOSED`. Whenever a charge is posted, the encounter's `total_charges_cents` is recomputed as the exact sum of `amount_cents` across that encounter's charges whose status is `POSTED` — voided charges are excluded from the total.

A posted charge may be voided by a `Registrar`, which transitions the charge `POSTED → VOIDED` and recomputes the encounter's `total_charges_cents` so that the voided charge no longer contributes.

When charge capture is complete, the `Registrar` discharges the encounter. Discharge is defined only from `ELIGIBILITY_VERIFIED` status and requires that at least one charge with status `POSTED` exists for the encounter; a discharge attempt with no posted charges is rejected with `ERR_NO_CHARGES`. On discharge the server sets the encounter's `discharge_at` to the current clock time, recomputes `total_charges_cents` from the posted charges, and advances the encounter `ELIGIBILITY_VERIFIED → CHARGES_CAPTURED`. The `discharge_at` timestamp later anchors the timely-filing computation for claims.

### 3.4. Eligibility Verification and the Forward-Looking Estimate

Before discharge, a `Registrar` verifies insurance eligibility for the encounter. This operation is defined only from `REGISTERED` status. It first requires that the encounter actually has insurance attached: an eligibility check against an encounter whose `policy_id` is null is rejected with `ERR_NO_POLICY_ON_ENCOUNTER`. It then inspects the referenced policy. If that `InsurancePolicy` is `ACTIVE`, the check succeeds: the system creates an `EligibilityCheck` record referencing the encounter by `encounter_id` and the policy by `policy_id`, sets its `result` to `ELIGIBLE`, stamps `checked_at` with the current clock time, advances the encounter `REGISTERED → ELIGIBILITY_VERIFIED`, and records a forward-looking estimate in `estimated_patient_responsibility_cents`. If instead the referenced policy is not `ACTIVE`, the operation does not advance the encounter: it is rejected with `ERR_POLICY_NOT_ACTIVE`, the encounter remains in `REGISTERED`, and the recorded eligibility result for such a case is `INELIGIBLE` rather than `ELIGIBLE`. On this rejection path the server nonetheless persists an `EligibilityCheck` record (referencing the encounter and the policy, with `result` set to `INELIGIBLE`, `estimated_patient_responsibility_cents` set to 0, and `checked_at` stamped with the current clock time) even though the request returns the error.

The estimate written into `estimated_patient_responsibility_cents` is computed as follows, using the encounter's expected charges and the policy's current accumulator state. The expected allowed amount is taken to be the encounter's current `total_charges_cents` over its posted charges — the estimate optimistically assumes the payer will allow the full billed charges, even though more charges may still be captured before discharge. The remaining deductible is the policy's `deductible_cents` minus the accumulator's `deductible_met_cents`, floored at 0. The deductible portion of the estimate is the smaller of the expected allowed amount and that remaining deductible. The amount remaining after the deductible is the expected allowed amount minus the deductible portion. The coinsurance portion is that after-deductible amount multiplied by the policy's `coinsurance_pct`, rounded half-up to whole cents. The raw patient figure is the deductible portion plus the coinsurance portion. Finally, the remaining out-of-pocket room is the policy's `oop_max_cents` minus the accumulator's `oop_met_cents`, floored at 0, and the estimate is the smaller of the raw patient figure and that remaining out-of-pocket room. Because this baseline reflects accumulator state *before* this encounter's own claim is ever adjudicated, the estimate and the later final figure can differ.

### 3.5. Coding the Encounter and the Compliance Risk Fork

Once charges are captured, a `Coder` creates the encounter's coding assignment — one coding assignment per encounter — supplying the `principal_icd10` diagnosis code (an ICD-10 code: a letter followed by two digits, optionally a dot and up to four further characters) and an optional `secondary_icd10` list of additional diagnosis codes, which defaults to an empty list. A new coding assignment begins in `DRAFT` status, with `finalized_by_user_id` null until it is finalized.

Finalizing the coding is the `Coder`'s next step and is defined only from `DRAFT` status; it additionally requires that the encounter is in `CHARGES_CAPTURED` status. At finalize time the server computes a **compliance risk score** and writes it to `compliance_risk_score`, records the finalizing operator by setting `finalized_by_user_id` to the caller's `X-User-ID`, and then forks: if the score is below the audit threshold the assignment transitions `DRAFT → FINALIZED`, but if the score reaches or exceeds the audit threshold the very same finalize operation instead routes the assignment to `DRAFT → AUDIT_HOLD`. The audit threshold is **50**, and the comparison is inclusive — a score of exactly 50 routes to `AUDIT_HOLD`.

The compliance risk score is the sum of three weighted factors, evaluated in this fixed order. First, an **unspecified principal diagnosis** carries documentation risk: if the `principal_icd10` contains no decimal point, or if it ends in ".9", the score gains 40 points. Second, an **excess of secondary codes** inflates the case weight: the score gains 10 points for each secondary code beyond the first three — concretely, 10 points multiplied by the count of entries in `secondary_icd10` minus 3, with that multiplier floored at 0 so that three or fewer secondary codes add nothing. Third, a **charge-to-code mismatch**: let the distinct count be the number of distinct `cpt_code` values across the encounter's posted charges; if that distinct count exceeds one plus the number of secondary codes, the score gains 35 points. The three contributions are summed to produce the final `compliance_risk_score`.

An assignment in `AUDIT_HOLD` is not a dead end. A `Coder` may return it for recoding, which is defined only from `AUDIT_HOLD` status; this clears `finalized_by_user_id` back to null and transitions the assignment `AUDIT_HOLD → DRAFT`, letting the coder amend the codes and finalize again. This revision loop means an encounter's coding may pass through finalize more than once before it clears.

### 3.6. Coding Clearance and the Encounter Bubble-Up

Coding becomes billable only once a `BillingSpecialist` clears it. Clearance is defined only from `FINALIZED` status and transitions the assignment `FINALIZED → CLEARED`. As a bubble-up side effect, clearing the coding advances the owning encounter from `CHARGES_CAPTURED` to `CODED`: the encounter only makes this `CHARGES_CAPTURED → CODED` transition as a consequence of its coding assignment reaching `CLEARED`. Because a claim may only be submitted once the encounter is `CODED`, an attempt to submit a claim before clearance — while the encounter is still short of `CODED` — is rejected with `ERR_CODING_NOT_CLEARED`.

### 3.7. Claim Submission and Payer Clearance

With the encounter `CODED`, a `BillingSpecialist` submits a claim to a payer. The submission supplies the `payer_id` of the target payer and the `expected_encounter_version` described in §2.8. The encounter must have insurance attached — a submission against an encounter whose `policy_id` is null is rejected with `ERR_NO_POLICY_ON_ENCOUNTER`. The target payer must be accepting claims; submission to a payer whose `active` flag is false is rejected with `ERR_PAYER_INACTIVE`. The submission must also satisfy timely filing: the claim must be submitted within the payer's `timely_filing_days` measured from the encounter's `discharge_at`, and a submission later than that window is rejected with `ERR_TIMELY_FILING_EXCEEDED`. The elapsed time is the fractional number of days between the current clock time and `discharge_at`, and the rejection fires only when that elapsed value is strictly greater than `timely_filing_days`; a submission whose elapsed time is exactly `timely_filing_days` is still timely. The check ordering places this timely-filing gate ahead of the §2.8 optimistic-concurrency check on `expected_encounter_version`. On a successful submission the server snapshots the claim's `billed_amount_cents` from the encounter's current `total_charges_cents`, stamps `submitted_at` with the current clock time, links the claim to its encounter by `encounter_id` and to the policy by `policy_id`, and places the claim in `SUBMITTED` status. Submission also advances the encounter's `version` by 1, which is why a second, stale submission against the same encounter is what the optimistic-concurrency check guards against.

### 3.8. Adjudication and the Final Patient Responsibility

A submitted claim is adjudicated by a `BillingSpecialist`. Adjudication may act on a claim in `SUBMITTED`, `CORRECTED`, or `APPEALED` status — the latter two arise from the revision loops described in §3.9. The caller supplies the payer-allowed total in `allowed_amount_cents` (an integer of at least 0) and a non-empty list of claim lines in `claim_lines`; each line names a five-character alphanumeric `cpt_code` and a `line_allowed_cents` payer-allowed amount for that line (an integer of at least 0). A missing or wrong-typed `allowed_amount_cents`, an `allowed_amount_cents` below 0, an empty or non-list `claim_lines`, or a malformed line is rejected with `ERR_INVALID_REQUEST`. The supplied lines must sum exactly to `allowed_amount_cents`; if they do not, adjudication is rejected with `ERR_CLAIM_LINES_MISMATCH`. On success the server records `allowed_amount_cents` on the claim and creates a `ClaimLine` row for each supplied line, each linked to the claim by `claim_id`.

The claim's final `patient_responsibility_cents` is then computed from the payer-allowed amount and the policy's accumulator state at adjudication time. The allowed amount is the claim's `allowed_amount_cents`. The remaining deductible is the policy's `deductible_cents` minus the accumulator's `deductible_met_cents`, floored at 0. The deductible applied is the smaller of the allowed amount and that remaining deductible. The amount after the deductible is the allowed amount minus the deductible applied. The raw coinsurance is that after-deductible amount multiplied by the policy's `coinsurance_pct`, rounded half-up to whole cents. The remaining out-of-pocket room is the policy's `oop_max_cents` minus the accumulator's `oop_met_cents`, floored at 0. The raw patient figure is the deductible applied plus the raw coinsurance, and the final `patient_responsibility_cents` is the smaller of that raw patient figure and the remaining out-of-pocket room — the out-of-pocket cap is applied only after the deductible and coinsurance are summed. Note that because this figure uses the payer-allowed amount rather than the billed charges, and uses accumulator state that may already reflect earlier claims adjudicated in the same plan year, an identical encounter can yield a different final number than the eligibility estimate of §3.4 whenever the allowed amount differs from the billed charges or the accumulator moved between verification and adjudication.

As a side effect of computing patient responsibility, the accumulator is advanced: its `deductible_met_cents` increases by the deductible applied, and its `oop_met_cents` increases by the final patient responsibility — and by construction neither is driven past its policy limit. For each adjudicated line, the server also derives `line_paid_cents` as the payer-paid portion of that line, namely the line's `line_allowed_cents` minus that line's share of patient responsibility. The patient-responsibility shares are allocated across the lines in proportion to each line's `line_allowed_cents` — each non-final line receives the floor of `patient_responsibility_cents × line_allowed_cents ÷ allowed_amount_cents`, and the final line receives whatever remainder is left so the shares sum exactly to `patient_responsibility_cents`; when patient responsibility or the allowed amount is 0 every line's share is 0.

Adjudication then forks on whether the patient owes anything. If the computed patient responsibility is 0 — the payer covers the allowed amount in full — the claim transitions to `PAID`, and the cascade advances the encounter `CODED → BILLED` with the encounter's `patient_responsibility_cents` set to 0; no patient statement is issued in this case. If instead the computed patient responsibility is greater than 0, the claim transitions to `PARTIALLY_PAID`, the cascade advances the encounter `CODED → BILLED` with the encounter's `patient_responsibility_cents` set to the claim's `patient_responsibility_cents`, the encounter's `account_balance_cents` is reconciled, and a `PatientStatement` is created for the encounter in `ISSUED` status. When the encounter reaches `BILLED` by either path, the server also recomputes the encounter's `account_balance_cents`.

### 3.9. Denial, Correction, Appeal, and Void

Rather than paying, a `BillingSpecialist` may deny a claim, supplying a `denial_reason` — one of `CODING_ERROR`, `NOT_COVERED`, `TIMELY_FILING`, or `DUPLICATE`. Denial may act on a claim in `SUBMITTED`, `CORRECTED`, or `APPEALED` status. On denial the server records the `denial_reason`, sets the claim to `DENIED`, and cascades: the encounter advances `CODED → BILLED` with `patient_responsibility_cents` set to the encounter's full `total_charges_cents` — on a denial the whole balance is billed to the patient — and a `PatientStatement` in `ISSUED` status is created for the encounter. The same coded encounter therefore forks across `PAID`, `PARTIALLY_PAID`, and `DENIED` with these divergent cascades.

A `DENIED` claim has two recovery paths, each gated on the denial reason. A denial whose reason is `CODING_ERROR` may be **corrected** by a `BillingSpecialist`: correction is defined only from `DENIED` status with reason `CODING_ERROR`, and a correction attempt on a denial with any other reason is rejected with `ERR_NOT_CORRECTABLE`. Correcting the claim transitions it `DENIED → CORRECTED` and runs a depth-three reversal cascade: the denial statement is reversed — its `amount_due_cents` is set to 0 and its status set to `PAID`, closing it with nothing owed — and the encounter is reverted from `BILLED` back to `CODED` with its `account_balance_cents` recomputed to 0. A `CORRECTED` claim rejoins the adjudicable set, so it can be re-adjudicated cleanly.

A denial whose reason is `NOT_COVERED` or `TIMELY_FILING` may instead be **appealed** by a `BillingSpecialist`. Appeal is defined only from `DENIED` status with one of those two reasons; an appeal attempt on a denial with any other reason is rejected with `ERR_NOT_APPEALABLE`. Appeal additionally requires that the current clock time is within the payer's `appeal_window_days` measured from the claim's `submitted_at`; an appeal filed after that window is rejected with `ERR_APPEAL_WINDOW_CLOSED`. As with timely filing, the elapsed time is the fractional number of days between the current clock time and `submitted_at`, and the rejection fires only when that elapsed value is strictly greater than `appeal_window_days`; an appeal whose elapsed time is exactly `appeal_window_days` is still within the window. Appealing transitions the claim `DENIED → APPEALED` and runs the same reversal cascade as correction — the denial statement's `amount_due_cents` is set to 0 and its status set to `PAID`, the encounter reverts `BILLED → CODED`, and `account_balance_cents` is recomputed to 0 — after which the `APPEALED` claim rejoins the adjudicable set for re-adjudication.

Finally, a duplicate claim is voided rather than reworked. Voiding is performed by a `BillingSpecialist` and is defined from a claim in `SUBMITTED` status, or from a `DENIED` claim whose `denial_reason` is `DUPLICATE`. Voiding transitions the claim to `VOID`, which is terminal.

### 3.10. Patient Statements, Payments, and Account Reconciliation

A patient statement bills the encounter's patient-owed balance. When issued — as a cascade of a `PARTIALLY_PAID` or `DENIED` adjudication — the statement references the encounter by `encounter_id`, snapshots `amount_due_cents` from the encounter's `patient_responsibility_cents` at issue time, begins with `amount_paid_cents` and `written_off_cents` at 0, is stamped with an `issued_at` timestamp from which bad-debt aging is measured, and starts in `ISSUED` status.

A `BillingSpecialist` posts a patient payment against a statement, supplying the payment `amount_cents` (an integer of at least 1) and a `method` — one of `CARD`, `CASH`, `CHECK`, or `EFT`. The payment is recorded as a `Payment` ledger entry referencing the statement by `statement_id` and stamped with a `posted_at` timestamp. A payment may not exceed the statement's outstanding balance — the statement's `amount_due_cents` minus its `amount_paid_cents` — and an overpayment is rejected with `ERR_OVERPAYMENT`. Posting a payment increases the statement's `amount_paid_cents` and recomputes the encounter's `account_balance_cents`. If the payment is strictly less than the outstanding balance, the statement moves to `PARTIALLY_PAID`; if the payment is greater than or equal to the outstanding balance, the statement moves to `PAID`. When a statement reaches `PAID`, the encounter bubbles up from `BILLED` to `CLOSED`. A statement already in `PARTIALLY_PAID` likewise moves to `PAID` once a further payment meets or exceeds the remaining outstanding balance, again closing the encounter.

The encounter's `account_balance_cents` is reconciled after every money movement as the encounter's `patient_responsibility_cents` minus the total of all payment `amount_cents` posted against its statement minus the statement's `written_off_cents`, with the result floored at 0 so the balance never goes negative.

### 3.11. Aging, Collections, and Segregated Bad-Debt Write-Off

An unpaid statement ages toward bad debt. A `BillingSpecialist` may send a statement to collections, which is permitted from `ISSUED` or `PARTIALLY_PAID` status but only once the statement has aged sufficiently: the current clock time must be at least 120 days after the statement's `issued_at`. A send-to-collections attempt before that aging threshold is rejected with `ERR_AGING_NOT_MET`. On success the statement moves to `IN_COLLECTIONS`.

Only a statement in `IN_COLLECTIONS` may be written off, and only a `FinanceManager` may approve the write-off. Two guards protect this final step. First, **segregation of duties**: the approving `FinanceManager`'s `X-User-ID` must not equal the `finalized_by_user_id` recorded on the encounter's coding assignment — the operator who finalized the coding may not be the one who forgives the resulting balance — and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, the optimistic-concurrency guard of §2.8: the request must carry `expected_patient_statement_version` matching the statement's current `version`, failing with `ERR_STALE_STATEMENT_VERSION` when a late payment has advanced the statement since the manager last read it. When both guards pass, the server creates a `WriteOff` ledger entry referencing the statement by `statement_id`, with its `amount_cents` set to the statement's `amount_due_cents` minus its `amount_paid_cents` at write-off time, a `reason` of `BAD_DEBT`, `CHARITY`, or `SMALL_BALANCE`, the approving operator captured in `approved_by_user_id`, and an `approved_at` timestamp. The statement's `written_off_cents` is set to the write-off amount, the statement moves to `WRITTEN_OFF`, the encounter's `account_balance_cents` is recomputed to 0, and the encounter bubbles up from `BILLED` to `CLOSED`.

### 3.12. Reading the Ledgers and the Test Clock

All four roles may read any resource. Single-resource reads return one record by its path `id`. Collection reads support filtering as well as pagination: insurance policies may be filtered by `patient_id` and `payer_id`; benefit accumulators by `policy_id`; encounters by `patient_id`, `policy_id`, and `status`; eligibility checks by `policy_id`; and claims by `policy_id`, `payer_id`, and `status`. Charges, eligibility checks, coding assignments, claims, claim lines, statements, payments, and write-offs may each also be listed under their parent record. Because temporal rules — timely filing, appeal windows, and bad-debt aging — depend on the current time, the system exposes an administrative test-driving capability that sets the server's current UTC clock to a supplied `to_iso8601` instant; all subsequent timestamp and temporal checks read from that clock. Any of the four roles may set it.

## 4. Endpoint Definitions

All endpoints share the envelope and authentication rules of §2. Creation endpoints that mint a new resource return HTTP 201; endpoints that modify, transition, or read an existing resource return HTTP 200. Request bodies, computed responses, and side effects are not repeated here — they are specified in the §3 workflow narratives; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/payers` | Create a payer | Registrar, BillingSpecialist |
| GET | `/payers/{id}` | Fetch a payer | Registrar, BillingSpecialist, Coder, FinanceManager |
| POST | `/patients` | Register a patient master record | Registrar |
| GET | `/patients/{id}` | Fetch a patient | Registrar, BillingSpecialist, Coder, FinanceManager |
| POST | `/insurance-policies` | Create an insurance policy for a patient | Registrar |
| GET | `/insurance-policies/{id}` | Fetch an insurance policy | Registrar, BillingSpecialist, FinanceManager |
| GET | `/insurance-policies` | List/filter insurance policies | Registrar, BillingSpecialist, FinanceManager |
| POST | `/insurance-policies/{id}/verify` | Verify a policy and open its benefit accumulator | Registrar |
| POST | `/insurance-policies/{id}/terminate` | Terminate an active policy | Registrar |
| GET | `/benefit-accumulators/{id}` | Fetch a benefit accumulator | Registrar, BillingSpecialist, FinanceManager |
| GET | `/benefit-accumulators` | List/filter benefit accumulators | Registrar, BillingSpecialist, FinanceManager |
| POST | `/encounters` | Register an admission (create encounter account) | Registrar |
| GET | `/encounters/{id}` | Fetch an encounter account | Registrar, BillingSpecialist, Coder, FinanceManager |
| GET | `/encounters` | List/filter encounters | Registrar, BillingSpecialist, Coder, FinanceManager |
| POST | `/encounters/{id}/discharge` | Discharge an encounter, closing charge capture | Registrar |
| POST | `/encounters/{id}/eligibility-checks` | Verify insurance eligibility and record an estimate | Registrar |
| GET | `/encounters/{id}/eligibility-checks` | List eligibility checks for an encounter | Registrar, BillingSpecialist, FinanceManager |
| GET | `/eligibility-checks/{id}` | Fetch an eligibility check | Registrar, BillingSpecialist, FinanceManager |
| GET | `/eligibility-checks` | List/filter eligibility checks | Registrar, BillingSpecialist, FinanceManager |
| POST | `/encounters/{id}/charges` | Capture a charge line on the encounter | Registrar |
| GET | `/encounters/{id}/charges` | List charges for an encounter | Registrar, BillingSpecialist, Coder, FinanceManager |
| GET | `/charges/{id}` | Fetch a charge | Registrar, BillingSpecialist, Coder, FinanceManager |
| POST | `/charges/{id}/void` | Void a posted charge | Registrar |
| POST | `/encounters/{id}/coding-assignment` | Create the coding assignment for an encounter | Coder |
| GET | `/encounters/{id}/coding-assignment` | List the coding assignment(s) for an encounter | Registrar, BillingSpecialist, Coder, FinanceManager |
| GET | `/coding-assignments/{id}` | Fetch a coding assignment | Registrar, BillingSpecialist, Coder, FinanceManager |
| POST | `/coding-assignments/{id}/finalize` | Finalize coding; fork FINALIZED vs AUDIT_HOLD | Coder |
| POST | `/coding-assignments/{id}/return-for-recode` | Return an audit-held coding to DRAFT | Coder |
| POST | `/coding-assignments/{id}/clear` | Clear finalized coding; advance encounter to CODED | BillingSpecialist |
| POST | `/encounters/{id}/claims` | Submit a claim for a coded encounter | BillingSpecialist |
| GET | `/encounters/{id}/claims` | List claims for an encounter | Registrar, BillingSpecialist, FinanceManager |
| GET | `/claims/{id}` | Fetch a claim | Registrar, BillingSpecialist, FinanceManager |
| GET | `/claims` | List/filter claims | Registrar, BillingSpecialist, FinanceManager |
| POST | `/claims/{id}/adjudicate` | Adjudicate a claim; compute responsibility, advance accumulators | BillingSpecialist |
| POST | `/claims/{id}/deny` | Deny a claim with a reason | BillingSpecialist |
| POST | `/claims/{id}/correct` | Correct a coding-error denial, re-opening the claim | BillingSpecialist |
| POST | `/claims/{id}/appeal` | Appeal a denied claim within the payer window | BillingSpecialist |
| POST | `/claims/{id}/void` | Void a duplicate or unsubmitted claim | BillingSpecialist |
| GET | `/claims/{id}/lines` | List adjudicated lines for a claim | Registrar, BillingSpecialist, FinanceManager |
| GET | `/encounters/{id}/patient-statements` | List patient statements for an encounter | Registrar, BillingSpecialist, FinanceManager |
| GET | `/patient-statements/{id}` | Fetch a patient statement | Registrar, BillingSpecialist, FinanceManager |
| POST | `/patient-statements/{id}/payments` | Post a patient payment against a statement | BillingSpecialist |
| POST | `/patient-statements/{id}/send-to-collections` | Send an aged statement to collections | BillingSpecialist |
| POST | `/patient-statements/{id}/write-off` | Approve a bad-debt write-off | FinanceManager |
| GET | `/patient-statements/{id}/payments` | List payments posted against a statement | Registrar, BillingSpecialist, FinanceManager |
| GET | `/patient-statements/{id}/write-offs` | List write-offs for a statement | Registrar, BillingSpecialist, FinanceManager |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock for deterministic tests | Registrar, BillingSpecialist, Coder, FinanceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_NO_POLICY_ON_ENCOUNTER | 409 |
| ERR_POLICY_NOT_ACTIVE | 409 |
| ERR_PAYER_INACTIVE | 409 |
| ERR_TIMELY_FILING_EXCEEDED | 409 |
| ERR_APPEAL_WINDOW_CLOSED | 409 |
| ERR_NOT_APPEALABLE | 409 |
| ERR_NOT_CORRECTABLE | 409 |
| ERR_AGING_NOT_MET | 409 |
| ERR_CHARGES_CLOSED | 409 |
| ERR_NO_CHARGES | 409 |
| ERR_CLAIM_LINES_MISMATCH | 422 |
| ERR_OVERPAYMENT | 422 |
| ERR_CODING_NOT_CLEARED | 409 |
| ERR_POLICY_IN_USE | 409 |
| ERR_STALE_ENCOUNTER_VERSION | 412 |
| ERR_STALE_STATEMENT_VERSION | 412 |
| ERR_VALIDATION_OUT_OF_RANGE | 422 |
