# SSDI Disability Application API — Product Requirements Document

## 1. Introduction

The Social Security Disability Insurance (SSDI) Disability Application API governs the end-to-end claim path that a working adult follows from the moment they first allege a disabling impairment until benefits begin paying, are reviewed for continuing eligibility, or — in adverse outcomes — are denied at quarter-of-coverage screening, denied by a state Disability Determination Services (DDS) examiner, denied at the Administrative Law Judge (ALJ) level, or terminated through a Continuing Disability Review. The system is the system of record for every step in that journey: claimant intake, work-credit history, the application itself, attached medical evidence, the DDS medical determination, the optional reconsideration and ALJ hearing track, the resulting benefit award, child auxiliary benefits attached to a primary award, the optional SSI supplemental cash benefit for concurrent filers, and the periodic CDR cycle that re-tests medical eligibility after award.

The API exists to make a notoriously paper-heavy, multi-actor adjudication legible to software. Five distinct operator roles — the claimant, a DDS examiner, an ALJ, a Benefits Administrator, and an SSA Administrator — each touch the record at well-defined points, and each step the system performs (computing quarters of coverage, deriving the Primary Insurance Amount, sizing Back Pay against the protective filing date, scheduling the next CDR by diary classification) carries statutory and fiscal weight. The product requirement is therefore not merely correctness on the happy path but disciplined refusal on the unhappy path: a claim with too few recent work credits must be denied at the QC stage rather than allowed to consume scarce medical-review capacity; a hearing scheduled with too little notice must be rejected before an ALJ slot is held; a child auxiliary that would push the household above the family-maximum cap must not be silently truncated.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply uniformly across every endpoint defined in §4.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares the role under which the call is being made. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (401). A request whose declared role is not authorised for the requested endpoint (per the per-endpoint allow-list in §4) is rejected with `ERR_FORBIDDEN` (403).

The system recognises exactly five roles, each spelled as shown: `Claimant`, `DDSExaminer`, `ALJ`, `BenefitsAdmin`, and `SSAAdmin`. The `Claimant` role is entity-backed: when `X-User-Role` is `Claimant`, the value of `X-User-ID` is the `id` of the acting `Claimant` resource, and ownership checks on any resource that ultimately references a `Claimant` compare that resource's `claimant_id` (directly, or transitively through an `Application`) to `X-User-ID`. In particular, a claimant who creates an `Application` may only do so for themselves: the supplied `claimant_id` must equal `X-User-ID`. The other four roles — `DDSExaminer`, `ALJ`, `BenefitsAdmin`, and `SSAAdmin` — are opaque operator identifiers: when `X-User-Role` is any of these, `X-User-ID` is not tied to any persisted entity and the server does not compare it to any entity's `id`. The server does, however, record those opaque identifiers where a scaffold transition writes one — for example, the DDS examiner's `X-User-ID` is stamped into `examiner_user_id` on a newly created `MedicalDeterminationDecision`, and the ALJ's `X-User-ID` is stamped into `alj_user_id` on a `HearingRequest` when that judge schedules the hearing.

The five roles are peers: the system does not arrange them into a strict hierarchy, and an operation that is exclusive to one role is not implicitly inherited by any other. Where multiple roles are authorised for the same endpoint, both are listed explicitly in §4.

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

List endpoints accept two query parameters to control paging. The `limit` parameter is optional and defaults to 10 when omitted; the minimum accepted value is 1 and the maximum is 100. The `offset` parameter is optional and defaults to 0. Regardless of the endpoint, list responses are returned in `created_at` ascending order — the oldest record first — unless explicitly stated otherwise on a specific endpoint. The four pagination fields `limit`, `offset`, `total_count`, and `has_more` are always populated inside the `meta` object of every list response.

### 2.4. Common Resource Properties

Every primary resource managed by the API — `Claimant`, `WorkCreditRecord`, `Application`, `MedicalDeterminationDecision`, `HearingRequest`, `BenefitAward`, `ChildAuxiliaryBenefit`, `SSISupplement`, and `CDRReview` — exposes a uniform set of system-managed properties: an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp following the same format that is refreshed on every mutation to the resource, and an integer `version` that begins at 1 on creation and increments by 1 on every subsequent mutation. The `version` field is the basis for the Optimistic Concurrency Control mechanism described in §2.7 and for the cross-aggregate cascade contracts in §2.6.

The `MedicalEvidence` resource is the single exception. It is treated as an immutable, append-only artifact: once posted, an evidence record is never amended, so it carries only `id` and `created_at`, and neither `updated_at` nor `version` is present on the resource.

### 2.5. Nested Resource Retrieval and Reference Validation

Several endpoints address a resource through a path that contains the parent's identifier — for example, the application-scoped evidence listing addresses both the parent application and (implicitly) the underlying claimant. Identifiers in the path are validated strictly left to right: the first identifier in the path that does not resolve to an extant resource causes the request to be rejected with `ERR_NOT_FOUND` (404), before any deeper identifier is consulted. The same principle extends to foreign-key identifiers carried in the request payload: any `claimant_id`, `application_id`, or `benefit_award_id` in a body must resolve to an existing resource, and a payload referencing a non-existent parent is rejected with `ERR_REFERENCE_NOT_FOUND` (404). Request bodies that are syntactically malformed — missing a required field, type mismatch, or carrying an unknown field — are rejected upstream of either of these checks with `ERR_INVALID_REQUEST` (400).

### 2.6. State Cascades, Hierarchical Consistency, and Versioning Semantics

Many transitions in this system mutate more than one resource. The convention is that every such mutation refreshes the touched resource's `updated_at` timestamp and increments its `version` by 1. When an operation cascades into a related resource — for example, when a Continuing Disability Review concludes in cessation and propagates terminal status downward through the award hierarchy, or when a benefit administrator suspends an award and the system terminates that award's child auxiliaries — the cascade is part of the same logical transaction: the parent transition and every dependent mutation are applied together, and the dependent resource's `status` change is observable on its next read. The exact mutations and their `version` increments are stated in the workflow sections of §3; the constant across all of them is that any field change is recorded by a refreshed `updated_at` and an incremented `version`.

### 2.7. Optimistic Concurrency Control

Two operations in this API require the client to pin the version of the parent resource against which they are operating, so that a request crafted against a now-superseded state cannot silently land.

A `POST` request that records a `MedicalDeterminationDecision` on an `Application` must include `expected_application_version` in its payload as a non-optional input field carrying the `version` the caller last observed on the parent `Application`. If that value does not match the `Application`'s current `version` at the moment the server processes the write, the request is rejected with `ERR_STALE_APPLICATION_VERSION` and HTTP status 412. This protects a DDS examiner who began drafting against an application that has since been amended (for example, the claimant submitted the draft, which itself bumps the application's `version`) from silently overwriting a state they did not observe.

A `POST` request that registers a `ChildAuxiliaryBenefit` against a `BenefitAward` must include `expected_benefit_award_version` in its payload as a non-optional input field carrying the `version` the caller last observed on the parent `BenefitAward`. A mismatch with the award's current `version` is rejected with `ERR_STALE_AWARD_VERSION` and HTTP status 412. This guards in particular against the case where another writer has suspended the award (which legitimately advances the award's `version` and terminates the existing auxiliaries) between the moment the client read the award and the moment it attempts to add a new auxiliary.

Endpoints not listed above do not take a version field. The framing of both rules is stale-version rejection, not race detection: the contract is purely about the parent resource's `version` having moved on, regardless of the time gap between the client's read and write.

### 2.8. Precision and Monetary Arithmetic

All monetary values exchanged by this API are integer cents. Claimant income (`monthly_income_cents`), countable resources (`countable_resources_cents`), reported yearly earnings (`earnings_cents`), the Primary Insurance Amount (`primary_insurance_amount_cents`), the monthly benefit (`monthly_benefit_cents`), retroactive Back Pay (`back_pay_cents`), the federal SSI supplement (`monthly_supplement_cents`), the state SSI supplement (`state_supplement_cents`), and a child auxiliary's monthly amount (`monthly_amount_cents`) are all stored, computed, and returned as integers. Quarter-of-coverage counts and the severity score on a piece of medical evidence are also pure integers; quarter-of-coverage arithmetic uses no decimals at any step. Where a calculation in §3 multiplies by a fractional rate (the bend-point rates for PIA, the 0.50 child rate, the 1.75 family-maximum multiplier), the rule is to round half up to the nearest whole cent at the point specified in that calculation. Where a calculation operates on calendar time (the next CDR scheduling, the entitlement-start window, the back-pay window), the resulting timestamp is computed at day resolution.

### 2.9. Validation Priority and the Order of Checks

When several validations could fire against the same request, the server evaluates them in a fixed priority order. Authentication (header presence) is checked first; only if both `X-User-ID` and `X-User-Role` are present does the server proceed to role authorisation against the endpoint. If the request is authorised, every identifier in the path template is resolved next, left to right; only if all path identifiers resolve does the server then resolve foreign-key identifiers carried in the body. Once existence is confirmed, the server evaluates state preconditions — that the target `Application`'s `status` matches the from-state of the requested transition, or that the target `HearingRequest`'s `status` matches the from-state of the hearing transition, or that a CDR's `scheduled_review_date` has fallen on or before the current server time. State precondition failures yield `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_HEARING_STATE`, or `ERR_CDR_NOT_DUE` as appropriate, each with HTTP status 409. Optimistic-concurrency stale-version checks (described in §2.7) come after state checks and before any business-safety or business-temporal rule. Only when all of the preceding gates pass does the server evaluate the domain-specific business rules — onset-date ordering, hearing lead time, reconsideration filing window, child age at creation, family-maximum headroom, SSI eligibility, and the per-claimant-year uniqueness of work-credit records.

This ordering matters because the further down the chain a rule sits, the more context the server has gathered. A request that should fail at authentication must not surface a "stale version" error, because the server has not yet decided that the caller is allowed to read the parent's version in the first place.

### 2.10. The Server Clock

A handful of operations in this system depend on the server's notion of "now": the QC lookback window closes at the application's `filing_date`, the reconsideration filing window expires sixty days after the underlying denial was recorded, an ALJ hearing cannot be marked as held before its `scheduled_date`, a Continuing Disability Review cannot be started before its `scheduled_review_date` has been reached, and a child auxiliary terminates automatically when the child crosses the age-eighteen boundary. For test purposes, an `SSAAdmin` may set the server's logical clock through an administrative test-driving capability that accepts a `to_iso8601` instant; this capability does not in itself fire any state machine — it only allows time-gated checks elsewhere to pass or fail relative to the new clock. A companion test-driving capability, also restricted to `SSAAdmin` and also taking `to_iso8601`, additionally re-evaluates the age of every still-active child auxiliary and terminates any whose child has now reached or passed age eighteen.

## 3. Business Logic & Workflows

This section walks the system's narrative end-to-end, organised by the lifecycle phase a typical claim moves through: claimant intake and work-history capture, application creation and quarter-of-coverage screening, evidence and medical determination, the appeals path through reconsideration and an ALJ hearing, benefit-award computation including Back Pay and SSI supplement, child auxiliary attachment, post-award administration, and the periodic CDR loop.

### 3.1. Claimant Intake and the Work-Credit Ledger

A claim begins with a `Claimant` record. The intake payload carries the claimant's `ssn_last4` — exactly four digits matching the regular pattern of four decimal digits — alongside their `full_name`, their `date_of_birth` (an ISO 8601 instant used by every age-bucket rule that follows), and their `filing_state` (a USPS two-letter uppercase state code, required to be in the recognised set; an unrecognised code is rejected with `ERR_INVALID_STATE_CODE`). Two optional fiscal inputs may also be captured at intake: `monthly_income_cents`, the claimant's countable monthly unearned income (defaulting to 0 cents if omitted), and `countable_resources_cents`, the dollar-equivalent of countable resources in cents (also defaulting to 0). These two fields are dormant for `SSDI_ONLY` filers but become decisive later for concurrent filers who request an SSI supplement. A claimant who self-registers does so under the `Claimant` role, in which case the new resource's `id` becomes the `X-User-ID` used on all subsequent calls; an `SSAAdmin` may also create a claimant on the claimant's behalf.

Independent of the claimant resource itself, the system maintains a `WorkCreditRecord` history — one row per (claimant, calendar `year`) pair. Each record states how many quarters of coverage were earned that year as `credits_earned` (constrained to between 0 and 4 inclusive) and the total reported `earnings_cents` for the year. The `year` field is itself constrained to the inclusive range 1990 through 2099. Posting work credits is exclusive to `SSAAdmin`: each posted record produces a 201 Created, and an attempt to post a second record for a `(claimant_id, year)` pair that already exists is rejected with `ERR_DUPLICATE_CREDIT_YEAR` (409). Work-credit records are immutable once posted; the QC counts a later application reads off this ledger reflect every record, regardless of when it was posted, so long as its `year` is on or before the application's filing year.

### 3.2. Filing an Application and the Quarter-of-Coverage Gate

A `Claimant` (or, on their behalf, an `SSAAdmin`) creates a new `Application` in `DRAFT` status by supplying the `claimant_id`, the `alleged_onset_date` (the date the claimant alleges their disability began, abbreviated AOD), an optional `protective_filing_date` (the PFD, which protects the back-pay window if the claimant signalled intent to file before the actual filing), and an optional `claim_type` of either `SSDI_ONLY` or `CONCURRENT_SSDI_SSI` (defaulting to `SSDI_ONLY`). The resource is created at `version` 1 with `status` of `DRAFT`, an `insured_status` of `PENDING`, a `medical_decision` of `PENDING`, and computed fields `total_qc_at_filing`, `recent_qc_in_lookback`, and `established_onset_date` initialised to a not-yet-computed state. The full set of values an application's `status` may take across its lifecycle is `DRAFT`, `QC_REVIEW`, `MEDICAL_REVIEW`, `DENIED_QC`, `DENIED_MEDICAL`, `APPROVED_INITIAL`, `RECONSIDERATION`, `ALJ_PENDING`, `ALJ_APPROVED`, `ALJ_DENIED`, `AWARDED`, `CDR_FROZEN`, `CESSATION`, and `CLOSED` (the last being reserved for administratively closed records that are not reachable through any transition described in this document). The new resource also carries a `back_pay_variant` placeholder on its eventual award — that variant is set when the award is created.

Submission is the gate. When the claimant submits a draft, the server stamps `filing_date` to the current time, defaults the `protective_filing_date` to `filing_date` if it was not provided at creation, and computes the two quarter-of-coverage tallies from the claimant's `WorkCreditRecord` history. The `total_qc_at_filing` is the sum of `credits_earned` across every `WorkCreditRecord` belonging to this claimant whose `year` is on or before the calendar year of the application's `filing_date`. The `recent_qc_in_lookback` is the sum of `credits_earned` across the same claimant's records restricted to the ten-year window that ends at the filing year inclusive — that is, records whose `year` lies in the inclusive range from filing-year minus ten through filing-year. Both tallies use integer arithmetic; there are no decimals.

Whether the claimant is "insured" turns on two thresholds. The first is the recent-work threshold: `recent_qc_in_lookback` must be at least 20 quarters — this corresponds to roughly five years of credited work inside a ten-year lookback. The second is the total-quarters threshold, which depends on the claimant's age at filing (computed from their `date_of_birth` and the application's `filing_date`). For a claimant under age 24, the required total is 6 quarters. For a claimant aged at least 24 and under 31, the required total is (age at filing minus 20) multiplied by 4 quarters. For a claimant at least 31 years old, the required total is capped at 40 quarters. A claimant is `INSURED` if and only if both the total-quarters tally is at least the age-adjusted required total AND the recent-quarters tally is at least 20; otherwise the claimant is `NOT_INSURED`. The submission transition is therefore branching: when `insured_status` resolves to `INSURED`, the server transitions the application from `DRAFT` through `QC_REVIEW` to `MEDICAL_REVIEW` in the same logical step and increments the application's `version`. When `insured_status` resolves to `NOT_INSURED`, the server transitions through `QC_REVIEW` to the terminal `DENIED_QC` state and increments the `version`. Submitting an application that is not in `DRAFT` is rejected with `ERR_INVALID_APPLICATION_STATE`.

### 3.3. Medical Evidence Collection

Once an application is in `MEDICAL_REVIEW`, both the `Claimant` and a `DDSExaminer` may attach `MedicalEvidence` records to it. Each piece of evidence is keyed to its parent through `application_id` and carries a `source_type` chosen from `TREATING_PHYSICIAN`, `CONSULTATIVE_EXAM`, `HOSPITAL_RECORD`, or `SPECIALIST_REPORT`, the `report_date` on which the medical report was produced, a `diagnosis_code` that may be either an ICD-10 code or an SSA Listing of Impairments reference, and a `severity_score` constrained to the inclusive integer range 0 through 100. Evidence is append-only: there is no edit endpoint and no `updated_at` or `version` on this resource, so the application's collected evidence is the immutable historical record by which the determination is later judged. The list-evidence endpoint scoped to an application returns the full set, and is readable by the claimant, the examiner, the ALJ, and an `SSAAdmin`.

### 3.4. The Medical Determination

The DDS examiner closes out the medical phase by recording a `MedicalDeterminationDecision` against the application. The payload carries `decision_type` (one of `LISTING_MET`, `RFC_DISABLED`, or `NOT_DISABLED`), the examiner's `established_onset_date` (EOD), and the OCC field `expected_application_version`; depending on the decision type, it also carries either `listing_reference` (a string referring to the SSA Listing of Impairments — required when `decision_type` is `LISTING_MET`) or `rfc_score` (the residual functional capacity score, an integer between 0 and 100 inclusive, required when `decision_type` is `RFC_DISABLED` or `NOT_DISABLED`). The newly created decision also records the examiner's `X-User-ID` server-side in `examiner_user_id`.

Before any state change occurs, several gates fire in priority order. The application must be in `MEDICAL_REVIEW`, otherwise the request is rejected with `ERR_INVALID_APPLICATION_STATE`. At least one `MedicalEvidence` record must already be attached to the application; an examiner who tries to decide an evidence-less application is rejected with `ERR_EVIDENCE_REQUIRED`. The OCC check then fires: `expected_application_version` is compared against the application's current `version`, and any mismatch is rejected with `ERR_STALE_APPLICATION_VERSION` (412), as described in §2.7. The examiner's `established_onset_date` must be on or after the application's `alleged_onset_date`; an EOD that precedes the AOD is rejected with `ERR_EOD_BEFORE_AOD` (422). Finally, a `LISTING_MET` decision must carry a non-null `listing_reference`; omitting it is rejected with `ERR_LISTING_REFERENCE_REQUIRED` (422).

If the decision is `NOT_DISABLED`, the server records the decision row, sets the application's `medical_decision` to `NOT_DISABLED`, transitions the application from `MEDICAL_REVIEW` to `DENIED_MEDICAL`, and increments the application's `version`. If the decision is `LISTING_MET` or `RFC_DISABLED`, the server records the decision row, sets the application's `medical_decision` and `established_onset_date` from the decision payload, transitions the application from `MEDICAL_REVIEW` to `APPROVED_INITIAL`, increments the `version`, and then performs three cascading writes in the same logical step: it creates a `BenefitAward` with `back_pay_variant` of `INITIAL_APPROVAL` (computing `primary_insurance_amount_cents`, `monthly_benefit_cents`, and `back_pay_cents` per §3.6); if the application's `claim_type` is `CONCURRENT_SSDI_SSI` it creates an `SSISupplement` (per §3.7); and it schedules the first `CDRReview` (per §3.9). A `CONCURRENT_SSDI_SSI` cascade that triggers without the claim type having been declared is rejected with `ERR_SSI_NOT_REQUESTED` (422) — that is, the SSI cascade may only fire when the application's `claim_type` is `CONCURRENT_SSDI_SSI`. Once the `BenefitAward` exists with `status` of `ACTIVE`, the system auto-transitions the application from `APPROVED_INITIAL` to `AWARDED` to reflect that the award is now live.

### 3.5. Reconsideration and the ALJ Hearing Track

A claimant who has been denied at the medical phase may appeal. Requesting reconsideration is permitted only while the application is in `DENIED_MEDICAL` (any other from-state yields `ERR_INVALID_APPLICATION_STATE`) and only within sixty days of the underlying `MedicalDeterminationDecision`'s `created_at` — measured as the current server time being on or before that decision's `created_at` plus sixty days. A request that arrives after the sixtieth day is rejected with `ERR_RECONSIDERATION_WINDOW_EXPIRED` (422). On a successful request, the application transitions from `DENIED_MEDICAL` to `RECONSIDERATION`, its `medical_decision` is reset to `PENDING`, and its `version` increments.

A claimant whose reconsideration is unproductive may escalate to an ALJ hearing. Requesting a hearing is exclusive to the claimant and requires the application to be in `RECONSIDERATION`; the request creates a new `HearingRequest` in `REQUESTED` status, server-stamps its `requested_date`, transitions the application from `RECONSIDERATION` to `ALJ_PENDING`, and increments the application's `version`. The newly created hearing's `scheduled_date` and `alj_user_id` are both null at this point.

Scheduling that hearing is exclusive to the `ALJ` role. The request supplies a `scheduled_date`. Two preconditions guard the call: the hearing must be in `REQUESTED` (otherwise `ERR_INVALID_HEARING_STATE`), and the supplied `scheduled_date` must be at least 75 days after the hearing's server-recorded `requested_date` — that is, `scheduled_date` is on or after `requested_date` plus 75 days. A `scheduled_date` that is earlier than that threshold is rejected with `ERR_HEARING_LEAD_TIME` (422). On success, the server sets the hearing's `status` to `SCHEDULED`, stamps the calling judge's `X-User-ID` into `alj_user_id`, persists the supplied `scheduled_date`, and increments the hearing's `version`. The application's state and version are not changed by mere scheduling.

Once the scheduled date has arrived, the assigned judge may record that the hearing was held. This call requires the hearing to be in `SCHEDULED` and the current server time to be on or after the hearing's `scheduled_date`; otherwise the request is rejected with `ERR_INVALID_HEARING_STATE`. On success, the hearing's `status` advances to `HELD` and its `version` increments. The hearing-held endpoint is purely administrative; it does not by itself produce an outcome.

The judge ultimately records an outcome by transitioning the hearing from `SCHEDULED` to either `APPROVED` or `DENIED`. An `APPROVED` outcome propagates upward: the application transitions from `ALJ_PENDING` through `ALJ_APPROVED`, its `medical_decision` is set to `RFC_DISABLED`, a `BenefitAward` is created (with `back_pay_variant` of `ALJ_APPROVAL` — see §3.6 for the variant difference), an `SSISupplement` is created if the application's `claim_type` is `CONCURRENT_SSDI_SSI`, the initial `CDRReview` is scheduled, and the application's `version` increments; the application subsequently auto-transitions from `ALJ_APPROVED` to `AWARDED` as soon as the award is observable in `ACTIVE` status. A `DENIED` outcome sets the application's `status` to `ALJ_DENIED` and increments its `version`. A claimant who changes their mind before the hearing is scheduled may cancel a `REQUESTED` hearing; the cancellation moves the hearing to `CANCELLED`, reverts the parent application from `ALJ_PENDING` to `RECONSIDERATION` so that the claimant retains the option to re-request, and increments the hearing's `version`.

### 3.6. The Benefit Award: PIA, Monthly Benefit, Back Pay, and the Two Variants

A `BenefitAward` is the financial centre of a successful claim. It begins life in `status` of `ACTIVE` and carries four computed monetary fields — `primary_insurance_amount_cents`, `monthly_benefit_cents`, `back_pay_cents`, and an `entitlement_start_date` — plus a `back_pay_variant` that records whether the award was created on the initial DDS approval path or via the ALJ hearing path.

The Primary Insurance Amount is computed by a simplified bend-point formula over the claimant's `WorkCreditRecord` history. The server first determines N as the smaller of 35 and the count of years in which the claimant had any credits at all (that is, years with `credits_earned` strictly greater than zero). It then picks the top N years for that claimant by `earnings_cents`, with ties broken by `year` ascending. The Average Indexed Monthly Earnings (AIME) in cents is the sum of `earnings_cents` across those N years, divided by N times 12, rounded to the nearest whole cent. Two bend points carve AIME into three tiers: the first tier is the portion of AIME up to and including 117400 cents (the first bend point, $1,174.00), the second tier is the portion of AIME above the first bend point up to and including 707900 cents (the second bend point, $7,079.00) — equivalently, capped at the difference between the two bend points, 590500 cents — and the third tier is the portion of AIME strictly above 707900 cents. The PIA in cents is the sum of three rounded tier contributions: 0.90 of the first tier rounded half up to the nearest cent, plus 0.32 of the second tier rounded half up to the nearest cent, plus 0.15 of the third tier rounded half up to the nearest cent. The rounding order is pinned: each tier is rounded individually before summing, never the other way round. The award's `monthly_benefit_cents` equals the computed PIA — for a primary insured the monthly cash benefit is the PIA itself.

Back Pay is the lump-sum payment for the months between the start of entitlement and the date the decision was reached. The entitlement-start date is computed from the medical examiner's `established_onset_date` plus a five-month statutory waiting period: it is the first day of the month that follows the EOD month by five months. SSDI law also caps the retroactive window at 12 months before the protective filing date: define the retroactive floor as the first day of the month obtained by stepping 12 months back from `protective_filing_date`. The effective start of the back-pay window is the later (the maximum) of the entitlement-start date and the retroactive floor — whichever of the two falls later on the calendar.

The two `back_pay_variant` values differ only in which decision date closes the window. For the `INITIAL_APPROVAL` variant — the path through `MEDICAL_REVIEW` to `APPROVED_INITIAL` — the closing date is the `created_at` of the `MedicalDeterminationDecision`. For the `ALJ_APPROVAL` variant — the path through `ALJ_PENDING` to `ALJ_APPROVED` — the closing date is the current server time at the moment the ALJ records the `APPROVED` outcome. In both variants, the count of retroactive months is the number of whole months between the effective start of the window and that variant-specific closing date, floored at zero (a negative count is treated as zero). The `back_pay_cents` value is the monthly benefit multiplied by the count of retroactive months. The same claimant with the same EOD, PFD, and PIA therefore typically receives a substantially larger `back_pay_cents` under `ALJ_APPROVAL` than under `INITIAL_APPROVAL`, because the ALJ path usually closes the window many months later — and may saturate against the 12-month-before-PFD cap.

### 3.7. SSI Supplemental Cash Benefit for Concurrent Filers

When the application's `claim_type` is `CONCURRENT_SSDI_SSI`, the system creates an `SSISupplement` resource alongside the `BenefitAward`. The supplement's lifecycle begins at `ACTIVE` but may be set to `INELIGIBLE_RESOURCES` at creation time if the claimant's countable resources are too high, or transitioned to `TERMINATED` later as part of a cascade. Two computed monetary fields live on the supplement: `monthly_supplement_cents` for the federal portion and `state_supplement_cents` for any state add-on.

The first gate is a resource test. If the claimant's `countable_resources_cents` is strictly greater than 200000 cents — the federal SSI resource limit of $2,000.00, applied with strict boundary precision — the supplement is created in `status` of `INELIGIBLE_RESOURCES`, both `monthly_supplement_cents` and `state_supplement_cents` are zeroed, and no further computation runs. A claimant whose countable resources are exactly 200000 cents passes the test.

If the resource test passes, the federal supplement is computed against the 2024 Federal Benefit Rate for a single individual, fixed at 94300 cents ($943.00). Countable income is the claimant's `monthly_income_cents` minus a general income exclusion of 2000 cents ($20.00 disregard), floored at zero — i.e., if the disregard exceeds the income, countable income is zero rather than negative. The federal `monthly_supplement_cents` is then the FBR minus countable income minus the SSDI monthly benefit, floored at zero — i.e., if the SSDI benefit alone already meets or exceeds the FBR less countable income, no federal SSI top-up is paid. Finally, `state_supplement_cents` is read from a lookup table keyed by the claimant's `filing_state`: California adds 2050 cents, New York adds 8700 cents, and every other state adds 0 cents.

### 3.8. Child Auxiliary Benefits and the Family Maximum

After an award is `ACTIVE`, either the claimant or a `BenefitsAdmin` may register a `ChildAuxiliaryBenefit` against it. The payload carries `child_full_name`, `child_date_of_birth`, a `relationship` chosen from `BIOLOGICAL`, `ADOPTED`, or `STEPCHILD`, and the OCC field `expected_benefit_award_version`. The new auxiliary begins life in `status` of `ACTIVE`.

Two business checks guard the creation. First, the child must be under 18 at the moment of creation: the difference between the current server time and `child_date_of_birth` must be strictly less than 18 years. A child who is 18 years old or older at creation is rejected with `ERR_CHILD_OVER_AGE` (422). Second, the proposed monthly amount must fit within the family-maximum headroom on the parent award. The base monthly auxiliary amount is half the primary insurance amount, computed as the award's `primary_insurance_amount_cents` multiplied by 0.50, rounded half up to the nearest cent. The family maximum is the award's `primary_insurance_amount_cents` multiplied by 1.75, rounded half up to the nearest cent. The headroom available for the new auxiliary is the family maximum minus the primary's `monthly_benefit_cents` minus the sum of `monthly_amount_cents` across every existing `ChildAuxiliaryBenefit` already attached to this award whose `status` is `ACTIVE` (processed in `created_at` ascending order, which is the same tie-break and processing order the system uses for the family-max accounting). If the headroom is zero or negative, the creation is rejected with `ERR_FAMILY_MAX_EXCEEDED` (422). Otherwise the auxiliary's `monthly_amount_cents` is the smaller of the base amount and the available headroom — so a late-arriving auxiliary may be paid less than half-PIA if earlier auxiliaries have already consumed most of the room. Creation also increments the parent award's `version` (so the next sibling registration must read the new version and pass it in `expected_benefit_award_version`, or be rejected with `ERR_STALE_AWARD_VERSION`).

A child auxiliary terminates under two distinct causes, each captured in a distinct terminal status. A child who reaches or passes age 18 is automatically moved to `TERMINATED_AGE`: when the server clock is advanced (via the test-driving capability described in §2.10), the system iterates every still-`ACTIVE` auxiliary and terminates any whose child-age (the difference between the new server time and `child_date_of_birth`) is at least 18 years. Termination caused by the primary award going down is recorded under a different terminal status: `TERMINATED_PARENT`. A `BenefitsAdmin` who suspends an `ACTIVE` award transitions that award to `SUSPENDED` and, in the same logical step, sets every still-`ACTIVE` `ChildAuxiliaryBenefit` attached to that award to `TERMINATED_PARENT`, refreshing those auxiliaries' `updated_at` and incrementing the award's `version`. Reinstating a `SUSPENDED` award transitions it back to `ACTIVE` and increments its `version`, but — by design — does not auto-reinstate the previously terminated auxiliaries: each terminated auxiliary must be re-created if the household wants the dependent benefit back.

### 3.9. Continuing Disability Review

When an award is first created (via either approval path), the system schedules an initial `CDRReview`. The schedule depends on the medical improvement diary classification: when `diary_classification` is `MIE` (Medical Improvement Expected), the next review is set to 18 months from the current server time; when it is `MIP` (Medical Improvement Possible), the next review is 36 months out (three years); when it is `MINE` (Medical Improvement Not Expected), the next review is 84 months out (seven years). On first scheduling the diary defaults to `MIE`. The computed instant is written to `scheduled_review_date` at day resolution, and the review begins life with `outcome` of `PENDING` and a null `completion_date`.

A CDR cannot be started until it is due: an `SSAAdmin` who attempts to start a review whose `scheduled_review_date` lies strictly in the future is rejected with `ERR_CDR_NOT_DUE` (409). Starting a due review requires the parent application to be in `AWARDED` and transitions the application to `CDR_FROZEN`, signalling that no benefit changes are accepted while the review is in flight; the application's `version` increments. Completing the review records its `outcome` (either `CONTINUED` or `CESSATION`) and stamps `completion_date` to the current server time.

A `CONTINUED` outcome returns the application from `CDR_FROZEN` to `AWARDED`, schedules the next CDR according to the same diary classification table, and increments the application's `version`. A `CESSATION` outcome is far more consequential: the application transitions from `CDR_FROZEN` to the terminal `CESSATION` state, the underlying `BenefitAward` is moved to `TERMINATED` (refreshing its `updated_at` and incrementing its `version`), every `ChildAuxiliaryBenefit` attached to that award is moved to `TERMINATED_PARENT`, and any associated `SSISupplement` is moved to `TERMINATED`. The cascade is a single logical step; the cessation of the primary award is the direct cause of the child loss and of the supplement termination.

## 4. Endpoint Definitions

Operations that create a new, standalone resource (a new `Claimant`, `WorkCreditRecord`, `Application`, `MedicalDeterminationDecision`, the `HearingRequest` produced when a claimant escalates to an ALJ, `MedicalEvidence`, or `ChildAuxiliaryBenefit`) return `201 Created`. Operations that modify an existing resource — submitting a draft, requesting reconsideration, scheduling, recording-held, deciding, or cancelling a hearing, suspending or reinstating an award, starting or completing a CDR, and the administrative clock endpoints — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/ssdi/claimants` | Register a new claimant | Claimant, SSAAdmin |
| GET | `/ssdi/claimants/{id}` | Fetch a claimant | Claimant, SSAAdmin, DDSExaminer, ALJ, BenefitsAdmin |
| GET | `/ssdi/claimants` | List claimants (paginated) | SSAAdmin |
| POST | `/ssdi/work-credits` | Post a year's work credits for a claimant | SSAAdmin |
| GET | `/ssdi/work-credits/{id}` | Fetch a single work credit record | SSAAdmin, Claimant |
| GET | `/ssdi/work-credits` | List work credit records | SSAAdmin, Claimant |
| POST | `/ssdi/applications` | Create a draft application | Claimant, SSAAdmin |
| GET | `/ssdi/applications/{id}` | Fetch an application | Claimant, SSAAdmin, DDSExaminer, ALJ, BenefitsAdmin |
| GET | `/ssdi/applications` | List applications | SSAAdmin, Claimant, DDSExaminer |
| POST | `/ssdi/applications/{id}/submit` | Submit a draft for QC review; auto-routes by insured status | Claimant |
| POST | `/ssdi/applications/{id}/medical-decision` | DDS examiner records the medical determination | DDSExaminer |
| POST | `/ssdi/applications/{id}/request-reconsideration` | Claimant appeals a medical denial | Claimant |
| POST | `/ssdi/applications/{id}/request-hearing` | Claimant escalates to ALJ | Claimant |
| POST | `/ssdi/applications/{id}/evidence` | Attach medical evidence to an application | Claimant, DDSExaminer |
| GET | `/ssdi/applications/{id}/evidence` | List evidence on an application | Claimant, DDSExaminer, ALJ, SSAAdmin |
| GET | `/ssdi/applications/{id}/decisions` | List medical determination decisions on an application | Claimant, DDSExaminer, ALJ, SSAAdmin |
| GET | `/ssdi/hearings/{id}` | Fetch a hearing request | Claimant, ALJ, SSAAdmin |
| GET | `/ssdi/hearings` | List hearings (filterable) | ALJ, SSAAdmin |
| POST | `/ssdi/hearings/{id}/schedule` | ALJ schedules a requested hearing | ALJ |
| POST | `/ssdi/hearings/{id}/record-held` | Mark a scheduled hearing as held | ALJ |
| POST | `/ssdi/hearings/{id}/decision` | ALJ records the hearing outcome | ALJ |
| POST | `/ssdi/hearings/{id}/cancel` | Claimant cancels a pending hearing request | Claimant |
| GET | `/ssdi/awards/{id}` | Fetch a benefit award | Claimant, BenefitsAdmin, SSAAdmin |
| GET | `/ssdi/awards` | List benefit awards (filterable) | BenefitsAdmin, SSAAdmin, Claimant |
| POST | `/ssdi/awards/{id}/suspend` | Suspend an active award | BenefitsAdmin |
| POST | `/ssdi/awards/{id}/reinstate` | Reinstate a suspended award | BenefitsAdmin |
| POST | `/ssdi/awards/{id}/child-auxiliaries` | Register a child auxiliary benefit | Claimant, BenefitsAdmin |
| GET | `/ssdi/awards/{id}/child-auxiliaries` | List child auxiliaries for an award | Claimant, BenefitsAdmin, SSAAdmin |
| GET | `/ssdi/ssi-supplements/{id}` | Fetch an SSI supplement | Claimant, BenefitsAdmin, SSAAdmin |
| GET | `/ssdi/ssi-supplements` | List SSI supplements (filterable) | BenefitsAdmin, SSAAdmin |
| GET | `/ssdi/cdr-reviews/{id}` | Fetch a CDR review | Claimant, SSAAdmin, BenefitsAdmin |
| GET | `/ssdi/cdr-reviews` | List CDR reviews (filterable) | SSAAdmin, BenefitsAdmin |
| POST | `/ssdi/cdr-reviews/{id}/start` | Begin a due CDR; freezes the application | SSAAdmin |
| POST | `/ssdi/cdr-reviews/{id}/complete` | Complete a CDR with a CONTINUED or CESSATION outcome | SSAAdmin |
| POST | `/ssdi/_clock/set_current_utc` | Set the server's current UTC time (test-only) | SSAAdmin |
| POST | `/ssdi/_clock/advance` | Advance the clock and re-evaluate age-derived child auxiliary terminations | SSAAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_INVALID_HEARING_STATE` | 409 |
| `ERR_CDR_NOT_DUE` | 409 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_STALE_AWARD_VERSION` | 412 |
| `ERR_EOD_BEFORE_AOD` | 422 |
| `ERR_LISTING_REFERENCE_REQUIRED` | 422 |
| `ERR_HEARING_LEAD_TIME` | 422 |
| `ERR_RECONSIDERATION_WINDOW_EXPIRED` | 422 |
| `ERR_CHILD_OVER_AGE` | 422 |
| `ERR_FAMILY_MAX_EXCEEDED` | 422 |
| `ERR_SSI_NOT_REQUESTED` | 422 |
| `ERR_DUPLICATE_CREDIT_YEAR` | 409 |
| `ERR_INVALID_STATE_CODE` | 422 |
| `ERR_EVIDENCE_REQUIRED` | 422 |
