# Hospital Revenue Cycle API — Product Requirements Document

## 1. Introduction

Hospital Revenue Cycle Management (HRCM) is the end-to-end financial workflow that begins the moment a patient is admitted and concludes only when the service has been adjudicated by the payer, billed to the patient, and either paid in full or written off as bad debt. For a hospital business office, the cost of getting this wrong is concrete and irreversible: an eligibility check missed at the registration desk surfaces as a denied claim weeks later; a charge that is captured but never posted leaves the encounter under-billed; a coding mismatch between captured charges and submitted diagnoses triggers a payer rejection that must be re-worked manually; and an OOP-maximum miscalculation overcharges the member and exposes the hospital to compliance findings.

This document specifies the Hospital Revenue Cycle API, the system of record that drives that workflow. The API governs eight collaborating record types — patients, insurance policies, encounters, charge items, coding records, payer clearance decisions, patient payments, and bad-debt write-offs — across four operational personas (registration, charge capture, coding, and billing). It enforces the deductible / coinsurance / out-of-pocket-maximum waterfall used by every commercial U.S. payer, the strict ordering between clinical coding and payer adjudication, and the 90-day aging gate that separates an actively-billed account from a bad-debt write-off. A test-only clock-advance capability is provided so the time-gated transitions can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers. `X-User-ID` identifies the acting user and `X-User-Role` declares the operational capacity under which the request is being made. A request that omits either header is rejected with `ERR_AUTH_MISSING`. A request whose `X-User-Role` is not authorized for the endpoint in question is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five role names, spelled as written here: `RegistrationClerk`, `ChargeCaptureClerk`, `Coder`, `Biller`, and `TestHarness`. When `X-User-Role` is `RegistrationClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit (for example, in fields a transition writes) but does not compare it to any entity's `id`. When `X-User-Role` is `ChargeCaptureClerk`, `X-User-ID` is likewise an opaque operator identifier with no entity backing. When `X-User-Role` is `Coder`, `X-User-ID` is again opaque; in particular, the `coder_id` written on a `CodingRecord` is supplied in the request body and need not match `X-User-ID`. When `X-User-Role` is `Biller`, `X-User-ID` is opaque. When `X-User-Role` is `TestHarness`, `X-User-ID` is opaque and the role exists solely to drive the clock-advance capability in tests.

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

List endpoints expose two query parameters that control the page window. The `limit` parameter caps the number of items returned and, when omitted, defaults to 10; the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and, when omitted, defaults to 0.

Unless an endpoint description states otherwise, every list endpoint sorts its results by `created_at` in ascending order. The response envelope's `meta` block on a list response carries `limit`, `offset`, `total_count`, and `has_more` so the caller can paginate forward without re-counting.

### 2.4. Nested Resource Retrieval and Existence Validation

Several endpoints address resources nested beneath an `Encounter` (charges, coding records, payments, and so on). For any path that carries multiple identifiers — for example, the path that targets a single charge line under an encounter via `encounter_id` and `charge_id` — the server validates the existence of each segment in left-to-right order. The first identifier that does not resolve causes the request to fail immediately with `ERR_NOT_FOUND`; nested lookups are not attempted past the first miss. The same rule applies to foreign-key references inside request bodies: when admitting a patient the supplied `policy_id` must point at an existing `InsurancePolicy` and the supplied `patient_id` must point at an existing `Patient`, otherwise the request is rejected with `ERR_NOT_FOUND` before any business validation runs. This existence sweep covers admission, policy attachment, charge creation, and the coding-record submission.

### 2.5. Common Resource Properties

Every resource the API persists carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp formatted as an ISO 8601 UTC string with three fractional digits (for example, `2025-05-24T10:30:00.123Z`).

The `Patient`, `InsurancePolicy`, `Encounter`, `ChargeItem`, and `CodingRecord` resources additionally carry an `updated_at` ISO 8601 UTC timestamp that is refreshed on every mutation of the resource, and an integer `version` that begins at 1 on creation and is incremented by exactly one on each subsequent mutation. Computed-field refreshes on an `Encounter` — `total_charges_cents`, `payer_responsibility_cents`, `patient_responsibility_cents`, `estimated_patient_responsibility_cents`, and `write_off_cents` — are mutations in this sense: they bump `version` and refresh `updated_at` on the `Encounter`.

The `ClearanceDecision`, `PatientPayment`, and `BadDebtRecord` resources are immutable audit records once written. They carry `id` and `created_at` but they do not carry `updated_at` and they do not carry `version`. Their own internal "when did this happen" timestamps — `decided_at` on a clearance decision, `posted_at` on a payment, `written_off_at` on a bad-debt record — are server-set on creation and never change afterward.

### 2.6. Optimistic Concurrency Control

Mutations that target an existing `Encounter` by its identifier may supply the resource's current `version` in the request body to opt into optimistic concurrency control. The system reads the persisted `version`, compares it to the supplied value, and rejects mismatches with `ERR_VERSION_CONFLICT`. Omitting the `version` field skips the check, in which case the mutation proceeds against whatever the current state happens to be. This OCC contract attaches in particular to the encounter-metadata update path used to swap an encounter's `policy_id` while it is still in `REGISTERED`.

### 2.7. Monetary Precision and the Coinsurance Rounding Pin

Every monetary value handled by the system is an integer count of cents. Sums of cents are exact and require no rounding. The single arithmetic step that does require rounding is the computation of the coinsurance bucket inside the patient-responsibility waterfall (see §3.5): the raw coinsurance amount is produced by multiplying the post-deductible billable cents by the coinsurance basis points and dividing by ten thousand, and that single intermediate value is rounded to the nearest whole cent using half-up rounding **once**, after the multiplication and division have been performed. Rounding is never applied per line item, and rounding is never applied to the deductible bucket or to the OOP-cap step — those are pure integer subtractions and minimums. The constant divisor used in the basis-points conversion is ten thousand.

The coinsurance rate itself is stored in basis points via `coinsurance_rate_bps` and is constrained to lie between 0 and 10000 inclusive (so 2000 represents twenty percent and 10000 represents one hundred percent). The annual deductible `deductible_cents` must be at least 0. The annual out-of-pocket maximum `oop_max_cents` must be at least as large as `deductible_cents`. The accumulators `deductible_met_cents` and `oop_accumulated_cents` are server-managed, default to 0, and are clamped so that `deductible_met_cents` never exceeds `deductible_cents` and `oop_accumulated_cents` never exceeds `oop_max_cents`.

### 2.8. The Patient Ledger Principle

The Encounter is the ledger unit. From the moment an encounter is admitted, every cents-denominated mutation — a charge posting, a charge void, the recording of an adjudicated payer decision, a patient payment, a refund, or a bad-debt write-off — is reconciled back into the encounter's derived totals before the response is returned. There are five derived totals: `total_charges_cents` summarises the active charge ledger, `estimated_patient_responsibility_cents` is the forward-looking pre-adjudication estimate, `payer_responsibility_cents` and `patient_responsibility_cents` are the post-clearance authoritative splits, and `write_off_cents` records the amount taken as bad debt if and when the encounter is written off. The current outstanding balance and any overpayment are computed on read via the chronological payments walk described in §3.7.

When the system runs the patient-responsibility waterfall in its `final` variant — the variant invoked exactly once per encounter, on the transition out of `CODED` — it also reconciles two policy-level accumulators back to the `InsurancePolicy`: the portion of the billable that fell into the deductible bucket is added to `deductible_met_cents`, and the final member-payable amount (after the OOP cap) is added to `oop_accumulated_cents`. Both increments occur after the member-payable amount has been determined, and both accumulators are clamped to their respective caps. The `estimate` variant of the same waterfall — invoked at eligibility verification, after each charge state change that affects `total_charges_cents`, and at discharge — does **not** touch either accumulator.

### 2.9. Hierarchical State Propagation and Cascading Refresh

State changes on a child resource that affect the encounter's derived totals propagate immediately to the parent encounter. Posting a `ChargeItem` from `PENDING` to `POSTED`, voiding a `POSTED` charge back to `VOIDED`, finalizing a `CodingRecord`, recording a `ClearanceDecision`, posting a `PatientPayment` or `REFUND`, and writing the encounter off all refresh the relevant derived totals on the parent encounter, bump the encounter's `version`, and update its `updated_at`. Voiding a `PENDING` charge does not change `total_charges_cents` (pending charges are not counted) and therefore does not trigger an estimate refresh.

Each calculation re-derivation is itself a mutation: when `charge_total_aggregation` refreshes `total_charges_cents`, when `patient_responsibility_calc` (variant `estimate`) refreshes `estimated_patient_responsibility_cents`, and when the `final` variant writes `patient_responsibility_cents` alongside `payer_clearance_calc` writing `payer_responsibility_cents`, the encounter's `version` advances by one in each case and `updated_at` is refreshed.

### 2.10. Validation Ordering

When more than one validation rule could fire on a single request, the system evaluates them in a fixed priority order so that the response surfaces the most diagnostic failure first. The order is: authentication headers (`ERR_AUTH_MISSING`) first, then role authorization (`ERR_FORBIDDEN`), then path-segment existence checks left-to-right (`ERR_NOT_FOUND`), then foreign-key existence checks for identifiers inside the request body (`ERR_NOT_FOUND`), then the state-machine guard for the target operation (`ERR_INVALID_STATE`), then domain-specific business validations. Within the domain group, business-referential checks (such as the `policy_id`/`patient_id` ownership check on admission) run before time-gated checks (such as the plan-year-equals-current-year check on eligibility verification), which run before structural format checks on coding payloads (ICD-10 pattern, CPT exact-five-digits), which run before cross-resource referential checks (such as the CPT-set match between coding record and active charges), which run before payload-internal constraint checks (such as the clearance allowed-amount-versus-charges check and the DENIED-payload internal consistency check), which run before fiscal/temporal gates on discharge, write-off, and payment posting. Concurrency conflicts (`ERR_VERSION_CONFLICT`) are reported as the final layer on PATCH operations after all earlier checks have passed.

### 2.11. Test Clock

A test-only clock-advance capability accepts a target ISO 8601 instant via the `to_timestamp` field and pins the server's notion of "now" to that instant. Two time-gated rules depend on it: the eligibility check requires the policy's `plan_year` to equal the current calendar year derived from the clock, and the bad-debt write-off requires that the elapsed time since `billed_at` reach the 90-day floor. The capability is available to `TestHarness`, `Biller`, and `RegistrationClerk`.

## 3. Business Logic & Workflows

### 3.1. Patient Registration and Policy Attachment

A `RegistrationClerk` opens a new patient record by supplying the patient's Medical Record Number `mrn`, the patient's legal `full_name`, and their `date_of_birth` formatted as an ISO 8601 calendar date. The `mrn` must be unique across all patients and must be between 8 and 12 alphanumeric characters in length. A newly created patient record is in the `ACTIVE` status; the only other terminal status the patient record may reach is `ARCHIVED`.

Insurance policies are attached to a patient as a separate resource. Attaching a policy requires the `RegistrationClerk` to supply the payer's name in `payer_name`, the payer-issued `policy_number`, the benefit-year integer `plan_year`, the annual deductible in cents via `deductible_cents`, the member coinsurance rate after deductible (in basis points) via `coinsurance_rate_bps`, and the annual out-of-pocket maximum in cents via `oop_max_cents`. The path encodes the owning patient via `patient_id`, and the same `patient_id` is stamped onto the resulting policy. A newly attached policy is created in the `UNVERIFIED` status with `deductible_met_cents` initialised to 0, `oop_accumulated_cents` initialised to 0, and `verified_at` initialised to null. A policy may end up in either of two other statuses: `ELIGIBLE` if a later verification succeeds, or `INELIGIBLE` if a later verification reports the policy is not eligible. `INELIGIBLE` is terminal — once a policy reaches it, no further eligibility transitions are possible on that policy.

### 3.2. Admission and the Encounter Lifecycle

The encounter is the unit of work. A `RegistrationClerk` admits a patient by supplying the `patient_id` and the `policy_id` that will be the encounter's billing policy. On creation, the server stamps `admission_at` to the current clock instant, sets `discharge_at` to null, sets the encounter's `status` to `REGISTERED`, and initialises all five computed totals (`total_charges_cents`, `payer_responsibility_cents`, `patient_responsibility_cents`, `estimated_patient_responsibility_cents`, and `write_off_cents`) to 0. Before the encounter is persisted, the system verifies that the policy referenced by `policy_id` belongs to the patient referenced by `patient_id`; if the policy's `patient_id` does not match the encounter's `patient_id`, the admission is rejected with `ERR_POLICY_PATIENT_MISMATCH`.

While the encounter remains in `REGISTERED`, the `RegistrationClerk` may update its metadata — most importantly, swapping the `policy_id` if registration discovers the wrong policy was attached. Updates supply the current `version` (or omit it to skip the OCC check) and only `policy_id` is modifiable through this path. Outside `REGISTERED`, the metadata-update path is closed.

The encounter then advances through a fixed sequence of statuses: `REGISTERED` → `ELIGIBILITY_VERIFIED` → `CHARGES_CAPTURED` → `CODED` → `CLEARED` → `BILLED`, and from `BILLED` to one of two terminal statuses, `RESOLVED` (the balance was paid off) or `WRITTEN_OFF` (the balance aged past the bad-debt threshold). Each transition is driven by an explicit operator action described below.

### 3.3. Insurance Eligibility Verification

Eligibility verification is the bridge between admission and charge capture. A `RegistrationClerk` triggers the check by supplying `policy_eligible` as a boolean — `true` if the payer's eligibility response is positive and `false` otherwise — along with an optional `denial_code` when `policy_eligible` is `false`. Regardless of branch, `verified_at` on the underlying policy is set to the request instant.

When the payer reports the policy as eligible (the `policy_eligible=true` branch), the policy transitions from `UNVERIFIED` to `ELIGIBLE` and the encounter transitions from `REGISTERED` to `ELIGIBILITY_VERIFIED`. The estimate variant of the patient-responsibility waterfall runs on the pre-service `total_charges_cents` (which is 0 at this point), so the encounter's `estimated_patient_responsibility_cents` is seeded to 0. From this point onward, each charge mutation that affects `total_charges_cents` refreshes the estimate (see §3.5 and §3.9). When the payer reports the policy as not eligible (the `policy_eligible=false` branch), the policy transitions from `UNVERIFIED` to `INELIGIBLE` — a terminal status for the policy — and the encounter remains in `REGISTERED` so that registration can re-route to a different policy via the metadata update.

Two preconditions guard both branches. First, the encounter must be in the `REGISTERED` status — verifying eligibility on an encounter that has already advanced is rejected with `ERR_INVALID_STATE`. Second, the policy's `plan_year` must equal the current calendar year derived from the server clock; a stale plan-year produces `ERR_PLAN_YEAR_EXPIRED`. Concurrency: when two `RegistrationClerk` operators race to verify eligibility on the same encounter, the first call wins and the second observes the encounter no longer in `REGISTERED`, receiving `ERR_INVALID_STATE`.

### 3.4. Charge Capture

Once the encounter is in `ELIGIBILITY_VERIFIED`, a `ChargeCaptureClerk` begins recording individual services. Each new charge line is created with a 5-digit CPT procedure code `cpt_code`, a human-readable `description`, a unit count `quantity` of at least 1, and a per-unit `unit_price_cents` of at least 0. The server pins the line's `amount_cents` on creation as the product of `quantity` and `unit_price_cents`; this value is immutable thereafter. A `cpt_code` that is not exactly five digits long is rejected with `ERR_INVALID_CPT`. The freshly created line begins in the `PENDING` status with `posted_at` null and the parent `encounter_id` recorded.

Two further transitions are available to the `ChargeCaptureClerk`. **Posting** a pending charge — advancing it from `PENDING` to `POSTED` — stamps the line's `posted_at` and is permitted only while the encounter is in `ELIGIBILITY_VERIFIED`; an attempt to post a line whose pinned `amount_cents` is not strictly greater than zero is rejected with `ERR_INVALID_STATE` (the same error reported for any other state-machine violation). Posting triggers `charge_total_aggregation` to refresh the encounter's `total_charges_cents` (now including this newly posted line) and triggers the estimate variant of `patient_responsibility_calc` to refresh `estimated_patient_responsibility_cents`. **Voiding** a charge — sending it from either `PENDING` or `POSTED` to `VOIDED` — is permitted while the encounter is in `ELIGIBILITY_VERIFIED` or `CHARGES_CAPTURED`. Voiding a previously-`POSTED` line additionally requires that no `FINALIZED` coding record exist for the encounter — once coding has been locked, the charge ledger is locked too. When voiding a `POSTED` line, both `charge_total_aggregation` and the estimate refresh run; when voiding a `PENDING` line, neither runs because pending lines were never counted in the aggregate.

`VOIDED` is the terminal status for a charge line; it cannot be resurrected.

### 3.5. The Patient-Responsibility Waterfall

The patient-responsibility waterfall is the heart of the pricing engine. It runs in two flavours that share the same arithmetic but read different inputs and trigger different side effects.

The arithmetic, in order:

**Step 1 — Deductible bucket.** The waterfall reads the snapshot values of the policy's `deductible_cents` and `deductible_met_cents` at the start of the calculation. The deductible remaining is the policy's `deductible_cents` minus its starting `deductible_met_cents`, with negative results clamped to zero. The deductible portion of the current calculation is the smaller of the billable input and that remaining deductible.

**Step 2 — Coinsurance bucket.** The post-deductible billable is the billable input minus the deductible portion. The raw coinsurance amount is that post-deductible billable multiplied by the policy's `coinsurance_rate_bps` and divided by ten thousand. That single intermediate value is then rounded to the nearest whole cent using half-up rounding **once** — never per line item, never before the multiplication, never after any further arithmetic. The rounded result is the coinsurance portion.

**Step 3 — Uncapped member side.** The member's uncapped responsibility is the deductible portion plus the coinsurance portion.

**Step 4 — Out-of-pocket cap.** The waterfall reads the snapshot values of the policy's `oop_max_cents` and `oop_accumulated_cents` at the start of the calculation. The OOP remaining is `oop_max_cents` minus the starting `oop_accumulated_cents`, with negative results clamped to zero. The member-payable amount is the smaller of the uncapped member responsibility and that OOP remaining.

**Step 5 — Outputs and accumulator updates.** The member-payable amount becomes the calculation's output: `patient_responsibility_cents` for the final variant or `estimated_patient_responsibility_cents` for the estimate variant.

The two variants diverge on three points. The **estimate** variant uses `total_charges_cents` as its billable input, writes `estimated_patient_responsibility_cents`, and does **not** mutate either of the policy accumulators. It runs on the successful branch of eligibility verification, after every `ChargeItem` state change that affects `total_charges_cents` (posting a charge and voiding a previously-posted charge), and again at discharge so that the estimate reflects the locked-in ledger. The **final** variant uses `ClearanceDecision.allowed_amount_cents` as its billable input, writes `patient_responsibility_cents`, and after the member-payable amount has been computed, adds the **deductible portion** (from Step 1) to the policy's `deductible_met_cents` and adds the **member-payable amount** (from Step 4) to the policy's `oop_accumulated_cents`. Both accumulator updates are clamped to their respective caps so neither can exceed `deductible_cents` or `oop_max_cents`. The final variant runs exactly once per encounter: on the transition out of `CODED`, immediately after the clearance decision is persisted and immediately after the payer-clearance calculation.

### 3.6. Discharge, Coding, and Clearance

When charge capture is complete, a `RegistrationClerk` discharges the encounter, advancing it from `ELIGIBILITY_VERIFIED` to `CHARGES_CAPTURED` and stamping `discharge_at` to the request instant. Discharge requires that at least one charge line exist in `POSTED` and that zero charge lines remain in `PENDING`; either condition failing produces `ERR_CHARGES_NOT_READY`. Discharge re-runs `charge_total_aggregation` and re-runs the estimate variant of `patient_responsibility_calc` so that the locked-in ledger snapshot is reflected in `estimated_patient_responsibility_cents` going into coding.

A `Coder` then prepares the coding record. The submission supplies a primary ICD-10 diagnosis code via `primary_icd10`, an optional list of secondary ICD-10 codes via `secondary_icd10` (defaulting to an empty list if absent), the full list of CPT procedure codes for the encounter via `cpt_codes`, the coder's identifier via `coder_id`, and a `finalize` boolean indicating whether the submission should also lock the record. The `primary_icd10` value must match the ICD-10-CM format — a single uppercase letter, two digits, and optionally a period followed by up to four alphanumeric characters — otherwise the submission is rejected with `ERR_INVALID_ICD10`. Every CPT entry in `cpt_codes` must be exactly five digits long or the submission is rejected with `ERR_INVALID_CPT`. At most one coding record may exist per encounter; if `finalize` is true and no draft record exists yet, the call creates and finalizes the record in one shot, while if a `DRAFT` record already exists the call finalizes that record. A second concurrent coding submission against the same encounter is rejected with `ERR_DUPLICATE_CODING_RECORD` — uniqueness is enforced on the `encounter_id` of `CodingRecord`, and only one finalize call wins. A new coding record is created in the `DRAFT` status; finalizing it transitions it to `FINALIZED`, the terminal status, and as a side effect transitions the encounter from `CHARGES_CAPTURED` to `CODED`. On finalize, the multiset of `cpt_codes` on the coding record must be exactly the multiset of `cpt_code` values across all non-`VOIDED` charge lines for this encounter; the codes may be in any order, but every CPT on the encounter must appear on the coding record with the correct multiplicity and vice versa. A mismatch produces `ERR_CODING_CPT_MISMATCH`. Finalization also re-runs `charge_total_aggregation` to guarantee the encounter total agrees with the locked ledger.

A `Biller` then submits the payer's adjudication decision. The submission carries the `decision` (one of `APPROVED`, `PARTIAL`, or `DENIED`), the payer-allowed amount in cents via `allowed_amount_cents`, and a payer reason code via `denial_reason_code` where applicable. The system stamps `decided_at` to the request instant and persists the resulting `ClearanceDecision` with the supplied `encounter_id`. The encounter must already have a `FINALIZED` coding record. The supplied `allowed_amount_cents` must satisfy zero as the minimum, must not exceed the encounter's current `total_charges_cents` (over-allowance is rejected with `ERR_ALLOWED_EXCEEDS_CHARGES`), and must be exactly 0 when `decision` is `DENIED`. A `denial_reason_code` is required when `decision` is `DENIED` and is also required when `decision` is `PARTIAL`; missing or inconsistent payloads — including a `DENIED` decision with a non-zero `allowed_amount_cents` — are rejected with `ERR_INVALID_CLEARANCE_PAYLOAD`. The transition from `CODED` to `CLEARED` runs the payer-clearance calculation and then the final variant of the patient-responsibility waterfall.

The payer-clearance calculation works as follows. When `decision` is `DENIED`, `payer_responsibility_cents` is set to 0. When `decision` is `APPROVED` or `PARTIAL`, `payer_responsibility_cents` is set to `allowed_amount_cents` minus the member-payable amount produced by running the final variant of the patient-responsibility waterfall against `allowed_amount_cents` — so `payer_responsibility_cents` plus `patient_responsibility_cents` equals `allowed_amount_cents` exactly. The unallowed portion of the bill — `total_charges_cents` minus `allowed_amount_cents`, which equals `total_charges_cents` entirely when the decision is `DENIED` — is treated as a contractual write-down and is **not** billed to the patient, with one specific exception: when `denial_reason_code` equals one of the patient-responsibility reason codes (`PR-1`, `PR-2`, or `PR-3`), the unallowed portion bypasses the deductible / coinsurance / OOP waterfall entirely and flows into `patient_responsibility_cents` in full. This exception applies only when the reason code is one of those three exact strings.

### 3.7. Billing, Payments, and the Outstanding-Balance Calculation

Once `payer_responsibility_cents` and `patient_responsibility_cents` have been written, a `Biller` issues the bill, advancing the encounter from `CLEARED` to `BILLED` and stamping `billed_at` to the request instant. The outstanding balance becomes due at this moment.

Subsequent patient payments are posted as a separate immutable audit record. Each posting supplies the payment amount in cents via `amount_cents` (which must be at least 1) and the payment instrument via `method`, where `method` is one of `CASH`, `CARD`, `CHECK`, or `REFUND`. A `REFUND` represents money flowing back to the patient and is accounted for as a positive contribution to the running balance (it un-pays prior payments); the three other methods represent money flowing in and reduce the running balance. The server stamps `posted_at` on the payment record at the moment of creation.

The outstanding balance and any overpayment are derived on read by walking the encounter's payments in chronological order. The walk starts from a running balance equal to `patient_responsibility_cents`. Each `PatientPayment`, processed in ascending order of `posted_at` with `id` ascending as the tie-breaker, is applied to the running balance: when the payment's `method` is `REFUND`, the payment's `amount_cents` is added to the running balance; otherwise the payment's `amount_cents` is subtracted from the running balance. After every payment has been applied, `outstanding_balance_cents` is the running balance clamped to a minimum of zero. If the running balance is strictly less than zero, `overpayment_cents` is the absolute value of that negative balance; otherwise `overpayment_cents` is zero. The same calculation is invoked when the encounter is fetched and on every payment post.

For non-`REFUND` postings, `amount_cents` must additionally be no greater than the current `outstanding_balance_cents` at the moment the post arrives. A payment that would push the running balance below zero on a non-`REFUND` method is rejected with `ERR_PAYMENT_AMOUNT_INVALID`. The same error covers a payment whose `amount_cents` is below 1.

If the running balance reaches exactly zero after a non-`REFUND` payment is applied, the encounter transitions from `BILLED` to `RESOLVED` — a terminal status. `RESOLVED` is final: any subsequent attempt to post a payment on the same encounter is rejected with `ERR_INVALID_STATE`. When two payment posts race against each other while the balance is one payment away from zero, both `PatientPayment` records persist (they are immutable records of fact), only one transition to `RESOLVED` occurs, and any payment that arrives after the transition is rejected with `ERR_INVALID_STATE`.

### 3.8. The Bad-Debt Write-Off

If an encounter sits in `BILLED` with a non-zero balance for too long, a `Biller` may write the account off to bad debt. The write-off is gated by three conditions that must all hold. First, the elapsed time since `billed_at` must be at least 90 days — measured by taking the difference between the current clock instant and `billed_at` in milliseconds, dividing by the number of milliseconds in one day (86,400,000), and taking the floor of the result; the boundary is inclusive, so a day count of exactly 90 passes and a day count of 89 does not. The lower bound on the day count is 90. Failing this gate produces `ERR_WRITE_OFF_TOO_EARLY`. Second, the encounter's current outstanding balance (computed via the chronological payments walk in §3.7) must be strictly greater than zero; an encounter that has already been paid off cannot be written off, and the attempt is rejected with `ERR_WRITE_OFF_NO_BALANCE`. Third, no `BadDebtRecord` may already exist for the encounter; a second write-off submission is rejected with `ERR_DUPLICATE_WRITE_OFF` (uniqueness is enforced on the `encounter_id` of `BadDebtRecord`, and only one write-off attempt wins under contention).

When all three gates pass, the system creates a new `BadDebtRecord` whose `write_off_cents` is set to the encounter's outstanding balance at write-off time (as produced by the chronological payments walk), whose `days_since_billed` is set to the floor of the day count computed above (captured for audit), and whose `written_off_at` is stamped to the request instant. The encounter's `write_off_cents` is set equal to the bad-debt record's `write_off_cents`, and the encounter transitions from `BILLED` to `WRITTEN_OFF` — the second terminal status for an encounter.

### 3.9. The Cascade of Estimate Refreshes

The estimate variant of the patient-responsibility waterfall is the most frequently re-derived calculation in the system because it feeds the patient's pre-service expectation. It runs at four moments. **At eligibility verification** (the successful branch), the estimate runs on the pre-service `total_charges_cents` (which is 0), seeding `estimated_patient_responsibility_cents` to 0. **At each charge state change that affects `total_charges_cents`** — that is, on the `PENDING` → `POSTED` transition and on the `POSTED` → `VOIDED` transition, but not on the `PENDING` → `VOIDED` transition — the system first re-runs `charge_total_aggregation` to refresh `total_charges_cents` and then re-runs the estimate variant against that new total. **At discharge**, the system re-runs the same pair so the estimate reflects the locked-in ledger going into coding. **At coding finalization**, the system re-runs `charge_total_aggregation` to confirm the encounter total. The estimate is never refreshed by clearance, by payment posting, or by write-off — once `patient_responsibility_cents` is written by the final variant on the `CODED` → `CLEARED` transition, it is the authoritative member figure and the estimate is no longer touched.

Every estimate refresh and every aggregate refresh is itself a mutation of the parent encounter: the encounter's `version` advances by one and its `updated_at` is refreshed. Tests that pin a stale version against the encounter immediately after a charge mutation will therefore observe `ERR_VERSION_CONFLICT` on a subsequent metadata update that supplied the pre-mutation `version`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource (admitting an encounter, attaching a policy, adding a charge line, submitting a coding record, recording a clearance decision, posting a payment, writing off to bad debt) return `201 Created`. Operations that modify an existing resource — including state transitions and the metadata-update path — return `200 OK`. Read-only operations also return `200 OK`.

| Method | Path                                                            | Description                                                                                  | Authorized Role(s)                                       |
| ------ | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| POST   | `/patients`                                                     | Register a new patient record.                                                               | RegistrationClerk                                        |
| GET    | `/patients/{patient_id}`                                        | Fetch a patient by id.                                                                       | RegistrationClerk, ChargeCaptureClerk, Coder, Biller     |
| GET    | `/patients`                                                     | List patients (paginated, optional `mrn` filter).                                            | RegistrationClerk, ChargeCaptureClerk, Coder, Biller     |
| POST   | `/patients/{patient_id}/policies`                               | Attach an insurance policy to a patient.                                                     | RegistrationClerk                                        |
| GET    | `/patients/{patient_id}/policies`                               | List policies for a patient.                                                                 | RegistrationClerk, Biller                                |
| POST   | `/encounters`                                                   | Admit a patient and open an encounter.                                                       | RegistrationClerk                                        |
| GET    | `/encounters/{encounter_id}`                                    | Fetch an encounter (includes computed totals and outstanding balance).                       | RegistrationClerk, ChargeCaptureClerk, Coder, Biller     |
| GET    | `/encounters`                                                   | List encounters (paginated, optional `status`/`patient_id` filter).                          | RegistrationClerk, Biller                                |
| PATCH  | `/encounters/{encounter_id}`                                    | Update encounter metadata while still in `REGISTERED` (e.g., swap `policy_id`).              | RegistrationClerk                                        |
| POST   | `/encounters/{encounter_id}/verify-eligibility`                 | Run insurance eligibility check; flips the encounter to `ELIGIBILITY_VERIFIED` on success.   | RegistrationClerk                                        |
| POST   | `/encounters/{encounter_id}/discharge`                          | Mark the encounter discharged; locks charge capture.                                         | RegistrationClerk                                        |
| POST   | `/encounters/{encounter_id}/charges`                            | Add a `PENDING` charge line item.                                                            | ChargeCaptureClerk                                       |
| POST   | `/encounters/{encounter_id}/charges/{charge_id}/post`           | Post a `PENDING` charge item (`PENDING` → `POSTED`).                                         | ChargeCaptureClerk                                       |
| POST   | `/encounters/{encounter_id}/charges/{charge_id}/void`           | Void a `PENDING` or `POSTED` charge.                                                         | ChargeCaptureClerk                                       |
| GET    | `/encounters/{encounter_id}/charges`                            | List charges for an encounter.                                                               | ChargeCaptureClerk, Coder, Biller                        |
| POST   | `/encounters/{encounter_id}/coding`                             | Create or finalize the coding record for an encounter.                                       | Coder                                                    |
| GET    | `/encounters/{encounter_id}/coding`                             | Fetch the coding record for an encounter.                                                    | Coder, Biller                                            |
| POST   | `/encounters/{encounter_id}/clearance`                          | Submit payer clearance decision.                                                             | Biller                                                   |
| POST   | `/encounters/{encounter_id}/issue-bill`                         | Mark a `CLEARED` encounter as billed.                                                        | Biller                                                   |
| POST   | `/encounters/{encounter_id}/payments`                           | Record a patient payment or refund against an encounter.                                     | Biller                                                   |
| GET    | `/encounters/{encounter_id}/payments`                           | List patient payments for an encounter.                                                      | Biller                                                   |
| POST   | `/encounters/{encounter_id}/write-off`                          | Write off an aged `BILLED` encounter to bad debt.                                            | Biller                                                   |
| POST   | `/_clock/advance`                                               | Test-only: advance the server clock to a fixed ISO 8601 instant via `to_timestamp`.          | TestHarness, Biller, RegistrationClerk                   |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_AUTH_MISSING`                | 401              |
| `ERR_FORBIDDEN`                   | 403              |
| `ERR_NOT_FOUND`                   | 404              |
| `ERR_INVALID_STATE`               | 409              |
| `ERR_VERSION_CONFLICT`            | 409              |
| `ERR_POLICY_PATIENT_MISMATCH`     | 422              |
| `ERR_PLAN_YEAR_EXPIRED`           | 422              |
| `ERR_INVALID_ICD10`               | 422              |
| `ERR_INVALID_CPT`                 | 422              |
| `ERR_CODING_CPT_MISMATCH`         | 422              |
| `ERR_ALLOWED_EXCEEDS_CHARGES`     | 422              |
| `ERR_INVALID_CLEARANCE_PAYLOAD`   | 422              |
| `ERR_CHARGES_NOT_READY`           | 422              |
| `ERR_WRITE_OFF_TOO_EARLY`         | 422              |
| `ERR_WRITE_OFF_NO_BALANCE`        | 422              |
| `ERR_PAYMENT_AMOUNT_INVALID`      | 422              |
| `ERR_DUPLICATE_CODING_RECORD`     | 409              |
| `ERR_DUPLICATE_WRITE_OFF`         | 409              |
