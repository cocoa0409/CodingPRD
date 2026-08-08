# Medical Billing RCM Firm API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the back-office platform of an outsourced Medical Billing and Revenue Cycle Management (RCM) firm. The firm is engaged by independent medical practices to run their revenue cycle end to end: onboarding each client practice and negotiating its fee schedule, entering charges and running the coding scrub, submitting claims to payers through a clearinghouse, working denials and appeals, issuing patient statements and chasing collections, posting insurance payments and reconciling remittances, maintaining provider credentialing and payer enrollment, and reporting key performance indicators together with the firm's own commission.

At its core the platform is a ledger-reconciliation system layered over a compliance and audit workflow. Every dollar that moves through a claim — what the provider billed, what the payer contract allows, what the insurer paid, what the patient owes, and what was ultimately written off — must reconcile to an exact identity at all times, and the platform must never let those figures drift. Because the firm's own revenue is a percentage of what flows through its clients' claims, and because payers impose hard temporal deadlines on filing and appeals, the accuracy and traceability of every state transition is a first-class product concern. The workflows are deliberately segregated across specialized firm roles, so that the same operator can never both scrub and submit a claim, and each responsibility is auditable back to the acting user.

The remainder of this document defines the global contracts every endpoint honors (Section 2) and the business workflows that govern each entity's lifecycle (Section 3), followed by the endpoint catalogue (Section 4) and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply uniformly across the entire API. All endpoints are mounted under the `/rcm` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the declared role is not permitted to perform the requested operation according to the role matrix, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes seven roles, spelled exactly as follows: `AccountManager`, `Coder`, `Biller`, `DenialSpecialist`, `PaymentPoster`, `CredentialingSpecialist`, and `PracticeUser`.

Six of these are firm-staff roles and are treated as **opaque operator identifiers**. When `X-User-Role` is `AccountManager`, `Coder`, `Biller`, `DenialSpecialist`, `PaymentPoster`, or `CredentialingSpecialist`, the accompanying `X-User-ID` is an opaque staff identifier that is not tied to any persisted entity. The server may record it where a workflow calls for it — for example, it stores the scrubbing operator's identifier as `scrubbed_by_user_id` on the claim and the submitting operator's identifier as `submitted_by_user_id` — but it never compares these values to any entity's `id`. The one place `X-User-ID` carries decision weight for these roles is segregation of duties (see §2.7): the submit workflow compares the submitter's `X-User-ID` against the stored `scrubbed_by_user_id` to ensure they differ.

`PracticeUser` is the one entity-backed role: when `X-User-Role` is `PracticeUser`, `X-User-ID` is the `id` of the acting `Practice`. A `PracticeUser` has read-only visibility, and ownership checks on any resource that references a practice compare the resource's `practice_id` (or, when reading a practice directly, the practice's own `id`) to `X-User-ID`. A `PracticeUser` may read its own practice, that practice's claims, statements, KPI, and billing-fee figures, but performs no mutating operation.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the front of the result set and defaults to 0. Requests that supply values outside these bounds are treated as invalid input.

Unless a specific endpoint states otherwise, list results are sorted by the resource's `created_at` timestamp in ascending order, ties broken by ascending `id`. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` reports the full size of the matching collection and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification; it advances on every mutation. The `version` field is an integer that begins at 1 on creation and increments by one on every mutation, and it is the anchor for optimistic concurrency control (see §2.6).

Two resources are lightweight line items and deliberately omit the mutation-tracking fields: a `FeeScheduleLine` and a `ClaimLine` each carry only an `id` and a `created_at`. They have no `updated_at` and no `version`, because once written they are not independently mutated — a `ClaimLine`'s computed `allowed_amount_cents` is resolved as part of scrubbing its parent claim rather than through a direct edit of the line.

All timestamps the platform records — `created_at`, `updated_at`, `submission_date`, `submitted_date`, `first_sent_date`, `credentialing_expiration_date`, `effective_date`, `end_date`, `termination_date`, `service_date`, and `denial_date` — are expressed in the same ISO 8601 UTC format, and every time-dependent rule reads the logical clock described in §2.10 rather than the host wall-clock.

### 2.5. Monetary Values, Rates, and Rounding

All monetary amounts are stored and returned as integer counts of cents; field names carrying money end in `_cents` and never hold fractional cents. Rate inputs — a practice's `billing_fee_pct` and a claim's `coinsurance_pct` — are numbers between 0 and 1 and preserve their input precision.

Wherever a monetary result is produced by multiplying an amount by a rate, the product is rounded using the round-half-up convention to the nearest whole cent. This applies to the coinsurance portion of a claim's patient responsibility and to the firm's per-claim commission. The exact points at which rounding is applied, and whether rounding happens before or after a summation, are specified with each calculation in Section 3; the governing rule is that when many rounded figures are summed, each is rounded first and the rounded figures are then added, never the reverse. KPI rates are the sole exception to the cents convention: clean-claim rate, denial rate, and net-collection rate are fractional numbers rounded half-up to four decimal places.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource by echoing that parent's last observed `version`. In both cases a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

First, posting an ERA line against a claim requires the request to carry `expected_claim_version`, which must equal the target claim's current `version`. Because each successful posting advances the claim toward `PAID` and increments the claim's `version`, a stale `expected_claim_version` means another posting has already been applied and the poster's view of the claim balance is out of date; the create is rejected before it can double-count against a balance it never observed.

Second, activating a fee schedule requires the request to carry `expected_practice_version`, which must equal the owning practice's current `version`. Activation reshapes the practice's active-schedule set and advances `Practice.version`; a stale `expected_practice_version` means another activation has already altered that set since the client last read the practice, and the activation is rejected. No endpoint other than these two accepts a version field, and neither operation may be performed without it.

### 2.7. Segregation of Duties

The firm enforces a separation-of-duties control on claim submission: the operator who submits a claim to the clearinghouse must not be the same operator who scrubbed it. When a claim is scrubbed, the acting operator's `X-User-ID` is persisted as `scrubbed_by_user_id`. At submit time, if the submitting operator's `X-User-ID` equals the stored `scrubbed_by_user_id`, the submission is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This is why scrubbing and submitting are assigned to distinct roles (`Coder` and `Biller`) and why the platform records who performed each step.

### 2.8. Existence Validation and Nested Resource Retrieval

Every request that names resources — whether by path segment or by foreign key in the body — validates their existence before any business rule runs. Path identifiers are checked left to right, and body-referenced foreign keys are checked after the path. The request is rejected on the first identifier that does not resolve, using the not-found error specific to that resource type: `ERR_PRACTICE_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DENIAL_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_POSTING_NOT_FOUND`, or `ERR_STATEMENT_NOT_FOUND`, each carrying HTTP 404. For example, listing the appeals under a denial validates the denial's existence first; a posting create validates the parent remittance in the path and then the `claim_id` in the body.

### 2.9. Hierarchical Consistency, Derived Fields, and Ledger Reconciliation

The platform keeps parent aggregates in continuous agreement with their children. A claim's monetary figures — `billed_amount_cents`, `allowed_amount_cents`, `contractual_adjustment_cents`, `patient_responsibility_cents`, `expected_reimbursement_cents`, `insurance_paid_cents`, `write_off_cents`, and `outstanding_balance_cents` — are derived fields, recomputed whenever an event changes their inputs (scrubbing, each payment posting or reversal, and each patient-statement payment or write-off), following the reconciliation identity defined in §3.6. The `expected_reimbursement_cents` figure is the sole exception among these: it is computed once at scrub (§3.3) and is not among the fields re-derived by the §3.6 ledger recomputation, so it retains its scrub value unchanged across later posting, reversal, and patient-statement events. A practice's `ar_balance_cents` (the sum of `outstanding_balance_cents` across its non-terminal claims) and `collected_ytd_cents` (the cumulative total of insurance paid to its claims, with no calendar-year filter applied) are likewise derived, refreshed whenever a claim's ledger moves; this refresh advances the practice's `updated_at` only when one of those two values actually changes, and never increments the practice's `version`. A remittance's `allocated_amount_cents` and `unallocated_amount_cents` are recomputed on every posting create and reversal.

When an operation mutates a resource — whether a client-driven transition or a server-driven recomputation of a derived field — that resource's `updated_at` is refreshed and its `version` is incremented. Several operations cascade across entities: submitting an appeal moves the denial and its claim together; deciding an appeal moves the appeal, the denial, and the claim; a payment posting can drive its claim to `PAID` and simultaneously refresh the owning practice's collected and AR totals. Each such cascade is enumerated with its workflow in Section 3, and every entity touched has its own `updated_at` and `version` advanced independently.

### 2.10. The Logical Clock and Temporal Rules

Every deadline in the platform is measured against a logical clock, never the host wall-clock. Before any client sets it, the clock reads `2026-05-01T00:00:00Z`. An administrative test-driving capability sets the clock to a supplied instant, and all timely-filing, appeal-window, credentialing-expiry, and statement-aging rules read from it. Elapsed-day comparisons — days from a claim's `service_date`, days from a denial's `denial_date`, and days since a statement's `first_sent_date` — are computed against this clock, and the precise day-counting and boundary conventions for each rule are given with that rule in Section 3.

## 3. Business Logic & Workflows

This section describes the lifecycle of each entity and the rules that govern its transitions. Across every state-transition endpoint, if the target resource is not in a state from which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Validation across all endpoints follows a fixed precedence: authentication first, then authorization, then existence of referenced resources, then the target's state, then the business, safety, referential, temporal, and fiscal rules described below in that order. Malformed input — a missing required field, a wrong type, or an out-of-range value — is rejected with `ERR_VALIDATION` (HTTP 422); an enum field carrying a value outside its declared set is rejected with `ERR_INVALID_ENUM` (HTTP 422); and a monetary input supplied as a negative number is rejected with `ERR_NEGATIVE_AMOUNT` (HTTP 422).

### 3.1. Client Onboarding and Fee Schedules

An `AccountManager` brings a new client onto the platform by registering a `Practice` with its legal `name`, its ten-digit group `npi`, its `tax_id`, and the commission rate `billing_fee_pct` that the firm will charge this client. The commission rate must be strictly greater than 0 and strictly less than 1 (a value such as 0.06 represents a six-percent commission). A newly created practice begins in `PROSPECT` status. Its accounts-receivable figure `ar_balance_cents` and its year-to-date collections figure `collected_ytd_cents` both start at 0 and are maintained by the platform thereafter.

Before a practice can go live, it needs a priced fee schedule. An `AccountManager` creates a `FeeSchedule` for a practice by supplying the `practice_id`, an `effective_date` marking the inclusive start of the schedule's effective interval, and an optional `end_date` marking the inclusive end of that interval; when `end_date` is omitted the interval is open-ended. A new fee schedule starts in `DRAFT`. The manager then prices individual procedures by adding one or more `FeeScheduleLine` entries under that schedule, each carrying the `fee_schedule_id` of its owning schedule, a `cpt_code`, and a non-negative `allowed_amount_cents` that is the contractual allowed amount for that CPT under this schedule.

Activating a draft fee schedule moves it from `DRAFT` to `ACTIVE`. Activation is permitted only when the schedule is in `DRAFT`, has at least one `FeeScheduleLine` (a draft with no lines is rejected with `ERR_VALIDATION` (HTTP 422)), and when no other `ACTIVE` fee schedule for the same practice has an effective interval that overlaps this one; overlap is evaluated on the closed-closed `[effective_date, end_date]` intervals (an open-ended schedule extends without upper bound), and a collision is rejected with `ERR_FEE_SCHEDULE_OVERLAP` (HTTP 409). Activation also carries `expected_practice_version` and is subject to the optimistic-concurrency check of §2.6; the overlap check is evaluated before the optimistic-concurrency check, so an overlapping-interval activation is rejected with `ERR_FEE_SCHEDULE_OVERLAP` even when `expected_practice_version` is also stale. On success the schedule becomes `ACTIVE`; any prior `ACTIVE` fee schedule for the practice whose interval ends strictly before this one's `effective_date` — that is, whose non-null `end_date` is strictly less than this schedule's `effective_date` — transitions from `ACTIVE` to `SUPERSEDED`; the practice's `version` is incremented by one; and if the practice was still in `PROSPECT`, it is moved to `ONBOARDING` — the first fee-schedule activation is exactly what advances a prospect into onboarding. A draft that is never needed may instead be retired, moving from `DRAFT` to `RETIRED`; both `SUPERSEDED` and `RETIRED` are terminal for a fee schedule.

Practice onboarding status is advanced through the practice-activation capability, which an `AccountManager` uses to walk the practice through its lifecycle and may accept an optional `target_status` to disambiguate the intended move. When supplied, `target_status` must be one of `PROSPECT`, `ONBOARDING`, `ACTIVE`, `SUSPENDED`, or `TERMINATED` (any other value is rejected with `ERR_INVALID_ENUM`), and it must name exactly the status that the single transition defined from the practice's current status leads to; a `target_status` naming any other status, or a request from a status that defines no transition, is rejected with `ERR_INVALID_STATE`. A practice in `ONBOARDING` may be promoted to `ACTIVE`, but only once it has at least one fee schedule in `ACTIVE` status; this promotion increments the practice's `version` by one. An `ACTIVE` practice may be moved to `SUSPENDED`, which freezes new claim submission while existing claims continue to be worked, and a `SUSPENDED` practice may be returned to `ACTIVE`. `TERMINATED` is the terminal status for a practice. Any of these moves requested from a status that does not define it is rejected with `ERR_INVALID_STATE`.

### 3.2. Payers, Provider Credentialing, and Enrollment Linkage

Insurance payers are reference data an `AccountManager` maintains. A `Payer` is created with its `name`, a `payer_type` of `COMMERCIAL`, `MEDICARE`, or `MEDICAID`, a `timely_filing_days` value (at least 1) that bounds how many days after the date of service a claim may still be filed, and an `appeal_window_days` value (at least 1) that bounds how many days after a denial an appeal may still be lodged.

A `CredentialingSpecialist` registers a rendering `Provider` under a practice by supplying the `practice_id`, the provider's individual ten-digit `npi`, `first_name`, `last_name`, and `specialty`. A new provider begins with `credentialing_status` of `PENDING` and a null `credentialing_expiration_date`. The specialist submits the provider for credentialing, moving `credentialing_status` from `PENDING` to `SUBMITTED`. A submitted provider is then decided: an approve decision moves `credentialing_status` from `SUBMITTED` to `APPROVED` and records the supplied `expiration_date` onto `credentialing_expiration_date`, and is allowed only when that expiration instant is strictly after the current logical clock (an expiration at or before the clock is rejected with `ERR_VALIDATION` (HTTP 422)); a reject decision moves `credentialing_status` from `SUBMITTED` to `REJECTED`, which is terminal. The decision request carries a `decision` value that is exactly `APPROVE` or `REJECT` (any other value is rejected with `ERR_INVALID_ENUM`), and an `expiration_date` accompanies an approval.

Credentials do not last forever. When the logical clock reaches or passes a provider's `credentialing_expiration_date`, the provider is considered expired; this is evaluated at claim-submit time, and when it applies the provider's `credentialing_status` moves from `APPROVED` to `EXPIRED`. Re-credentialing is a cycle: an `EXPIRED` provider can be resubmitted, moving `credentialing_status` from `EXPIRED` back to `SUBMITTED`, and from there through the same decision path again.

Credentialing is what unlocks payer participation. A `CredentialingSpecialist` records a `PayerEnrollment` — the many-to-many linkage between a provider and a payer — by supplying the `provider_id`, the `payer_id`, an `effective_date` marking the inclusive start of the participation period, and an optional `termination_date` marking the exclusive end of that period (null means open-ended). A new enrollment starts in `PENDING`. Before the enrollment is written, the platform rejects it with `ERR_ENROLLMENT_PERIOD_OVERLAP` (HTTP 409) if any existing non-`TERMINATED` enrollment for the same provider-and-payer pair has a participation period that overlaps the new one, where overlap is evaluated on half-open `[effective_date, termination_date)` intervals. Activating an enrollment moves it from `PENDING` to `ACTIVE`, and is permitted only when the linked provider's `credentialing_status` is `APPROVED`; an activation attempted while the provider is not `APPROVED` is rejected with `ERR_INVALID_STATE` (HTTP 409). An `ACTIVE` enrollment can later be terminated, moving from `ACTIVE` to `TERMINATED` and stamping the supplied `termination_date`; `TERMINATED` is terminal.

### 3.3. Charge Entry and the Coding Scrub

A `Coder` opens a new claim as charge-entry work. Creating a `Claim` requires the `practice_id` of the billing client, the `provider_id` of the rendering provider, the responsible `payer_id`, the `service_date` on which care was delivered (this starts the timely-filing clock), and the patient's cost-share inputs: `deductible_remaining_cents` (the deductible not yet met at the time of service, non-negative), `coinsurance_pct` (the patient coinsurance rate applied after the deductible, between 0 and 1 inclusive), and `copay_cents` (a flat non-negative copay for the visit). A new claim starts in `DRAFT`, with `appeal_round` at 0 and every computed ledger figure — `billed_amount_cents`, `allowed_amount_cents`, `contractual_adjustment_cents`, `patient_responsibility_cents`, `expected_reimbursement_cents`, `insurance_paid_cents`, `write_off_cents`, and `outstanding_balance_cents` — at 0.

The coder itemizes the visit by adding one or more `ClaimLine` charge lines to the draft, each carrying a `cpt_code`, a `units` count of at least 1, and a non-negative `charge_amount_cents` representing the provider's gross list price for that line. Each line's `allowed_amount_cents` is left unresolved at entry and is filled in during the scrub.

Scrubbing moves a claim from `DRAFT` to `SCRUBBED` and is the point at which pricing and the patient split are computed and frozen. A scrub is allowed only from `DRAFT`. It then enforces three business checks in sequence: the claim must have at least one `ClaimLine`, or it is rejected with `ERR_NO_CLAIM_LINES` (HTTP 422); the owning practice must have an `ACTIVE` fee schedule whose `[effective_date, end_date]` interval covers the claim's `service_date`, or it is rejected with `ERR_NO_ACTIVE_FEE_SCHEDULE` (HTTP 422); and every `cpt_code` appearing on the claim's lines must be priced by that covering fee schedule, or it is rejected with `ERR_CPT_NOT_IN_FEE_SCHEDULE` (HTTP 422).

On a successful scrub the platform resolves each line's `allowed_amount_cents` as that line's `units` multiplied by the covering fee schedule's allowed amount for the line's `cpt_code`. It then freezes the claim's `billed_amount_cents` as the sum of the lines' `charge_amount_cents` and the claim's `allowed_amount_cents` as the sum of the lines' resolved `allowed_amount_cents`, and sets `contractual_adjustment_cents` to `billed_amount_cents` minus `allowed_amount_cents` — the write-down the payer contract mandates. It computes the provisional patient responsibility (below), sets `expected_reimbursement_cents` to the claim's `allowed_amount_cents` minus its `patient_responsibility_cents`, and computes `outstanding_balance_cents` per the reconciliation identity of §3.6. The acting operator's `X-User-ID` is stored as `scrubbed_by_user_id`, the claim moves to `SCRUBBED`, and the owning practice's `ar_balance_cents` is recomputed.

**Provisional patient responsibility.** At scrub, before any remittance has been posted, the patient's share is estimated from the claim inputs and the resolved allowed amounts. Let the total allowed be the sum of the lines' resolved `allowed_amount_cents`. The deductible actually applied is the smaller of that total allowed and the claim's `deductible_remaining_cents`. The amount remaining after the deductible is the total allowed minus the deductible applied. The coinsurance portion is that after-deductible amount multiplied by the claim's `coinsurance_pct`, rounded half-up to a whole cent — this is the only figure in the computation that is rounded. The provisional `patient_responsibility_cents` is then the smaller of two quantities: the sum of the deductible applied, the rounded coinsurance, and the claim's `copay_cents`; and the total allowed. In other words, the patient's provisional responsibility can never exceed the total allowed amount. This provisional figure is later replaced by the final ERA value during payment posting, as described in §3.6.

### 3.4. Submission to the Clearinghouse, Acceptance, and Closure

Submission is a `Biller`'s responsibility and moves a claim from `SCRUBBED` to `SUBMITTED`. Beyond requiring the `SCRUBBED` starting state, the submit workflow runs a series of gates in a fixed order. First it checks the rendering provider's credentialing: the provider must be `APPROVED` and not past expiration. If the provider is currently `APPROVED` but the logical clock has reached or passed the provider's `credentialing_expiration_date`, the provider is auto-expired — its `credentialing_status` moves from `APPROVED` to `EXPIRED` — and, together with any provider that is simply not `APPROVED`, the submission is rejected with `ERR_PROVIDER_NOT_CREDENTIALED` (HTTP 422). Next comes the segregation-of-duties gate of §2.7: if the submitting operator's `X-User-ID` equals the claim's stored `scrubbed_by_user_id`, the submission is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Then referential eligibility is checked: an `ACTIVE` `PayerEnrollment` must exist for the claim's provider-and-payer pair whose participation period covers the claim's `service_date`, or the submission is rejected with `ERR_ENROLLMENT_NOT_ACTIVE` (HTTP 422). Finally the timely-filing deadline is enforced: the number of whole days from the claim's `service_date` to the current logical clock must not exceed the payer's `timely_filing_days`, or the submission is rejected with `ERR_TIMELY_FILING_EXCEEDED` (HTTP 422). On success the platform stamps `submission_date` with the current clock, records the submitting operator's `X-User-ID` as `submitted_by_user_id`, sets the claim to `SUBMITTED`, and increments the claim's `version` by one.

Once a claim is on the wire, the `Biller` records the clearinghouse acknowledgement, moving the claim from `SUBMITTED` to `ACCEPTED` and incrementing its `version` by one; an optional `clearinghouse_ref` may accompany the acknowledgement. An `ACCEPTED` claim reaches `PAID` automatically when payment posting drives its balance to zero, as described in §3.6.

Claim closure is a single capability whose effect depends on the claim's current state, and the endpoint authorizes both `Biller` and `Coder` for every branch (the acting role is not further restricted by the claim's current state). A `Coder` or `Biller` may void an unsubmitted draft, moving a claim from `DRAFT` to `VOID`. Either may close a fully-paid claim, moving it from `PAID` to `CLOSED`. Either may also close out a fully-denied claim as a write-off: the claim moves from `DENIED` to `CLOSED`, its `write_off_cents` is set to its current `outstanding_balance_cents`, its `outstanding_balance_cents` is set to 0, any linked denial still in `OPEN` or `UPHELD` status moves to `WRITTEN_OFF`, and the owning practice's `ar_balance_cents` is recomputed. Both `CLOSED` and `VOID` are terminal for a claim.

### 3.5. Denial Management and the Appeal Cycle

When a payer denies a claim, a `DenialSpecialist` records a `Denial` against it. Recording a denial requires the `denial_code` (the CARC/RARC reason code), a non-negative `denied_amount_cents`, and the `denial_date` on which the payer issued the denial — this date starts the appeal-window clock. A denial may be recorded against a claim that is in either `SUBMITTED` or `ACCEPTED` status; the new denial is created in `OPEN`, the claim moves to `DENIED`, and the claim's `version` is incremented by one.

An appeal is worked in two steps. First, the `DenialSpecialist` drafts an `Appeal` against a denial, identifying the target denial by its `denial_id` and supplying an optional `level` (which defaults to 1 and must be either 1 for a first-level appeal or 2 for a second-level appeal) and a `narrative` justification. A drafted appeal starts in `DRAFT` with `recovered_amount_cents` at 0 and a null `submitted_date`. Drafting is refused with `ERR_APPEAL_LIMIT_EXCEEDED` (HTTP 422) if it would take the claim beyond the maximum of two appeal rounds.

Second, the specialist submits the appeal, moving it from `DRAFT` to `SUBMITTED`. Submission is allowed only when the appeal is in `DRAFT`, the underlying denial is in `OPEN`, and the number of whole days from the denial's `denial_date` to the current logical clock does not exceed the payer's `appeal_window_days`; exceeding that window is rejected with `ERR_APPEAL_WINDOW_EXCEEDED` (HTTP 422). A successful submission sets the appeal to `SUBMITTED`, stamps `submitted_date` with the current clock, moves the denial from `OPEN` to `APPEALED`, cascades the claim from `DENIED` to `APPEALED`, and increments the claim's `appeal_round` by one.

Deciding an appeal carries an `outcome` that is exactly `OVERTURN`, `UPHOLD`, or `WITHDRAW` (any other value is rejected with `ERR_INVALID_ENUM`) and, on a favorable result, an optional `recovered_amount_cents` that defaults to 0 when omitted. The three outcomes are treated with distinct and fully specified effects. An **overturn** outcome moves the appeal from `SUBMITTED` to `OVERTURNED`, records the `recovered_amount_cents` onto the appeal, moves the denial to `OVERTURNED`, and reopens the claim by cascading it from `APPEALED` back to `ACCEPTED`; the recovery reduces the claim's write-off and outstanding exposure accordingly, and both the claim ledger and the owning practice's `ar_balance_cents` are recomputed. An **uphold** outcome moves the appeal from `SUBMITTED` to `UPHELD`, moves the denial to `UPHELD`, and cascades the claim from `APPEALED` back to `DENIED`, leaving the denial standing — a divergent side-effect set from the overturn branch, with no recovery and no ledger restoration. A **withdraw** outcome applies to an appeal still in `DRAFT` and moves it to `WITHDRAWN`. The appeal states `OVERTURNED`, `UPHELD`, and `WITHDRAWN` are terminal.

The denial-and-appeal loop is cyclic. Because an uphold returns the claim to `DENIED`, a second appeal round (level 2) may then be drafted and submitted against that standing denial, carrying the claim through `DENIED → APPEALED` again, up to the two-round limit enforced by `ERR_APPEAL_LIMIT_EXCEEDED`. A denial's disposition therefore travels `OPEN → APPEALED` and then to either `OVERTURNED`, `UPHELD`, or, when a fully-denied claim is closed out as a write-off, `WRITTEN_OFF`.

### 3.6. Payment Posting, Remittance Reconciliation, and the Claim Ledger

Insurance payments arrive as remittances. A `PaymentPoster` creates a `RemittanceAdvice` from a payer's ERA/EOB by supplying the `payer_id`, the payer's `remittance_ref` (check or remittance reference), and the non-negative `total_amount_cents` of dollars on the remittance. A new remittance starts in `RECEIVED`, with `allocated_amount_cents` at 0 and `unallocated_amount_cents` equal to its total.

The poster then applies ERA lines as `PaymentPosting` records under the remittance. A posting supplies the `remittance_id` of the parent (from the path), the `claim_id` it pays, the `insurance_paid_cents` allocated to that claim, the `patient_responsibility_cents` reported for the patient on the ERA line, and the `adjustment_cents` contractual adjustment reported on the line — all three amounts non-negative — together with `expected_claim_version` for the optimistic-concurrency check of §2.6. Each posting is created in `POSTED`. The first posting under a remittance moves it from `RECEIVED` to `POSTING`. A posting is refused with `ERR_OVERALLOCATION` (HTTP 422) if it would push the remittance's allocated total above its `total_amount_cents`; this over-allocation check is evaluated before the `expected_claim_version` optimistic-concurrency check, so an over-allocating posting is rejected with `ERR_OVERALLOCATION` even when `expected_claim_version` is also stale.

**Remittance allocation.** A remittance's `allocated_amount_cents` is the sum of `insurance_paid_cents` across its non-reversed (`POSTED`) postings, and its `unallocated_amount_cents` is its `total_amount_cents` minus that allocated sum. These two figures are recomputed on every posting create and every reversal, and the conservation identity that `total_amount_cents` equals `allocated_amount_cents` plus `unallocated_amount_cents` holds at all times — a reversal restores the unallocated pool exactly.

**The claim ledger identity.** Whenever a claim is scrubbed, a posting is created or reversed against it, or a patient statement records a payment or write-off, the claim's ledger is recomputed in this exact, fixed order. First, `billed_amount_cents` is the sum of the lines' `charge_amount_cents`. Second, `allowed_amount_cents` is the sum of the lines' `allowed_amount_cents`. Third, `contractual_adjustment_cents` is `billed_amount_cents` minus `allowed_amount_cents`. Fourth, `insurance_paid_cents` is the sum of `insurance_paid_cents` across the claim's `POSTED` postings. Fifth, `patient_responsibility_cents` is the provisional figure computed at scrub only until a posting has ever been created against the claim — where "a posting exists" counts every posting the claim has ever had regardless of its current status, so a subsequently `REVERSED` posting still qualifies and never reverts the figure to the provisional estimate — after which it is the `patient_responsibility_cents` reported on the ERA line of the claim's most recently created posting, selected as the posting with the latest `created_at` (ties broken by the greater posting `id`), whether that posting is `POSTED` or `REVERSED`; the provisional scrub figure is used only when the claim has never had any posting created against it. Sixth, `write_off_cents` is the accumulated write-offs from denial closure and statement write-off. Seventh, `outstanding_balance_cents` is `billed_amount_cents` minus `contractual_adjustment_cents` minus `insurance_paid_cents` minus `patient_responsibility_cents` minus `write_off_cents`. This closes the invariant that `billed_amount_cents` equals the sum of `contractual_adjustment_cents`, `insurance_paid_cents`, `patient_responsibility_cents`, `write_off_cents`, and `outstanding_balance_cents`.

**Final patient responsibility.** The provisional patient split computed at scrub is a forecast. Once payment posting begins, the `patient_responsibility_cents` value reported on the ERA line (the posting's own `patient_responsibility_cents`) replaces the scrub estimate on the claim, and the resulting delta flows through the ledger recomputation above and is re-applied to any related `PatientStatement`.

When a posting drives a claim's `outstanding_balance_cents` to zero or below while the claim is `ACCEPTED`, the claim moves automatically from `ACCEPTED` to `PAID`. On reaching `PAID`, the platform recomputes the owning practice's `collected_ytd_cents` and `ar_balance_cents` and accrues the practice's commission (see §3.8). Every posting also increments the paid claim's `version` by one.

A posting can be reversed as a compensating action; the reversal request carries a `reason`. Reversing sets the posting's `status` to `REVERSED`, recomputes both the claim ledger and the remittance allocation, and, if removing the payment reopens a positive balance on a claim that had reached `PAID`, reverts that claim from `PAID` back to `ACCEPTED`; the owning practice's `collected_ytd_cents` and `ar_balance_cents` are recomputed as well. When the last remaining posting under a remittance is reversed — that is, once all of the remittance's postings are `REVERSED` — the remittance itself moves from `POSTING` to `REVERSED`.

A remittance is finalized once it is fully reconciled: finalizing moves it from `POSTING` to `POSTED`, and is allowed only when its `allocated_amount_cents` equals its `total_amount_cents`; an attempt to finalize an unbalanced remittance is rejected with `ERR_REMITTANCE_NOT_BALANCED` (HTTP 422). Both `POSTED` and `REVERSED` are terminal for a remittance.

### 3.7. Patient Statements, Aging, and Collections

The patient's share of a claim is billed through a `PatientStatement`. Either a `PaymentPoster` or an `AccountManager` may create one for a claim by supplying the `claim_id`; the statement copies the claim's `practice_id` into its own `practice_id` for practice-scoped queries, opens its `statement_amount_cents` at the claim's current `patient_responsibility_cents`, sets `amount_paid_cents` to 0, leaves `first_sent_date` null, and starts in `DRAFT` with `aging_bucket` of `CURRENT`.

A `PaymentPoster` sends the statement to the patient, moving it from `DRAFT` to `SENT`, which is permitted only when the `statement_amount_cents` is greater than 0 (a send attempted while `statement_amount_cents` is 0 or below is rejected with `ERR_INVALID_STATE` (HTTP 409)). Sending stamps `first_sent_date` with the current logical clock — this starts the aging clock — sets `aging_bucket` to `CURRENT`, and sets the status to `SENT`.

Patient payments are recorded against a statement in `SENT`, `PARTIAL`, or `COLLECTIONS` status; the request supplies an `amount_cents`. The recorded amount is added to `amount_paid_cents` and the claim ledger is recomputed; because a patient payment does not enter the claim's reconciliation identity, this recomputation leaves the claim's ledger figures unchanged and advances the claim's `updated_at` without incrementing its `version`. If the cumulative `amount_paid_cents` after the payment is still strictly less than the `statement_amount_cents`, the statement moves to `PARTIAL`. If the cumulative `amount_paid_cents` reaches or exceeds the `statement_amount_cents`, the statement moves to `PAID`, and the owning practice's collected totals are recomputed as part of that settlement. `PAID` is terminal.

**Statement aging.** A statement's `aging_bucket` is derived from how long it has been outstanding, measured as the number of whole days from its `first_sent_date` to the current logical clock, taking the floor of the elapsed time in days (each day being 86,400 seconds). While `first_sent_date` is null the bucket is `CURRENT`. Once sent, the bucket is `CURRENT` when the elapsed days are 30 or fewer, `DAYS_31_60` when they are 31 through 60, `DAYS_61_90` when they are 61 through 90, and `OVER_90` only when they strictly exceed 90 days. The bucket boundaries fall on the lower bucket: day 30 is still `CURRENT`, day 90 is still `DAYS_61_90`, and day 91 is the first day in `OVER_90`. This bucket is recomputed whenever the statement is fetched and whenever a move to collections is attempted.

When a statement has aged into the `OVER_90` bucket, a `PaymentPoster` may send it to collections, moving it from `SENT` or `PARTIAL` to `COLLECTIONS`; the move is allowed only when the current `aging_bucket` is `OVER_90`. Finally, an `AccountManager` may write off a statement that is in `COLLECTIONS`, moving it to `WRITTEN_OFF`: the remaining unpaid statement balance is added to the claim's `write_off_cents`, and both the claim ledger and the owning practice's `ar_balance_cents` are recomputed. `WRITTEN_OFF` is terminal.

### 3.8. Commission and KPI Reporting

The firm's commission on a practice can be computed two ways, and the billing-fee report returns both. Throughout, "wire claims" means claims that reached the clearinghouse — those whose status is `SUBMITTED`, `ACCEPTED`, `DENIED`, `APPEALED`, `PAID`, or `CLOSED`. The **charge-based** figure, `charge_based_fee_cents`, is computed by taking each wire claim, multiplying its `billed_amount_cents` by the practice's `billing_fee_pct`, rounding that product half-up to a whole cent, and summing those per-claim rounded amounts. The **collection-based** figure, `collection_based_fee_cents`, is computed the same way but over only the claims that have realized an insurance payment — those in `PAID` or `CLOSED` — multiplying each such claim's `insurance_paid_cents` by `billing_fee_pct`, rounding each product half-up per claim, and summing. In both variants the half-up rounding is applied to each claim's commission before the amounts are summed, never by summing first and rounding once. This same collection-based accrual is what the platform snapshots when a claim reaches `PAID`.

The practice KPI report returns four figures. The `total_claims` count is the number of the practice's claims whose status is neither `DRAFT` nor `VOID`. A claim is counted as "clean" when it reached `ACCEPTED` or `PAID` without ever entering `DENIED`, and a claim is counted as "denied" when it ever entered denial — meaning it is currently `DENIED` or `APPEALED`, or it has any `Denial` recorded against it. The `clean_claim_rate` is the count of clean claims divided by `total_claims`, rounded half-up to four decimal places, and is 0 when there are no counted claims. The `denial_rate` is the count of denied claims divided by `total_claims`, rounded half-up to four decimal places, and is 0 when there are no counted claims. The `net_collection_rate` is the total insurance paid across all of the practice's claims divided by the difference between the billed total across wire claims and the sum of their contractual adjustments, rounded half-up to four decimal places; when that denominator is 0 or negative the rate is 0.

An administrative test-driving capability lets an `AccountManager` set the logical clock to a supplied `to_iso8601` instant, returning the new `current_utc`. As described in §2.10, before this capability is first used the clock reads `2026-05-01T00:00:00Z`, and every timely-filing, appeal-window, credentialing-expiry, and statement-aging rule reads from this clock.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection (such as onboarding a practice, adding a fee-schedule line, or posting an ERA line) return `201 Created`. Operations that modify an existing resource — including every state transition and every read — return `200 OK`. Request and response bodies are not restated here; reconstruct them from the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rcm/practices` | Onboard a new client practice | AccountManager |
| GET | `/rcm/practices/{id}` | Fetch a practice | AccountManager, PracticeUser |
| GET | `/rcm/practices` | List practices | AccountManager |
| POST | `/rcm/practices/{id}/activate` | Advance practice onboarding status | AccountManager |
| GET | `/rcm/practices/{id}/kpi` | Compute practice KPI metrics | AccountManager, PracticeUser |
| GET | `/rcm/practices/{id}/billing-fee` | Compute firm commission both ways | AccountManager, PracticeUser |
| GET | `/rcm/practices/{id}/providers` | List providers for a practice | AccountManager, CredentialingSpecialist, PracticeUser |
| GET | `/rcm/practices/{id}/fee-schedules` | List fee schedules for a practice | AccountManager, PracticeUser |
| GET | `/rcm/practices/{id}/claims` | List claims for a practice | AccountManager, Coder, Biller, PracticeUser |
| GET | `/rcm/practices/{id}/statements` | List patient statements for a practice | AccountManager, PaymentPoster, PracticeUser |
| POST | `/rcm/payers` | Create an insurance payer | AccountManager |
| GET | `/rcm/payers/{id}` | Fetch a payer | AccountManager, Biller, CredentialingSpecialist |
| GET | `/rcm/payers/{id}/enrollments` | List enrollments for a payer | AccountManager, CredentialingSpecialist |
| GET | `/rcm/payers/{id}/remittances` | List remittances for a payer | AccountManager, PaymentPoster |
| GET | `/rcm/payers/{id}/claims` | List claims for a payer | AccountManager, Biller, DenialSpecialist |
| POST | `/rcm/providers` | Register a rendering provider under a practice | CredentialingSpecialist |
| GET | `/rcm/providers/{id}` | Fetch a provider | AccountManager, CredentialingSpecialist, Biller |
| GET | `/rcm/providers/{id}/enrollments` | List enrollments for a provider | AccountManager, CredentialingSpecialist |
| GET | `/rcm/providers/{id}/claims` | List claims for a provider | AccountManager, Biller, Coder |
| POST | `/rcm/providers/{id}/credentialing/submit` | Submit a provider for credentialing | CredentialingSpecialist |
| POST | `/rcm/providers/{id}/credentialing/decision` | Approve or reject a submitted credentialing | CredentialingSpecialist |
| POST | `/rcm/payer-enrollments` | Create a provider-payer enrollment | CredentialingSpecialist |
| GET | `/rcm/payer-enrollments/{id}` | Fetch an enrollment | AccountManager, CredentialingSpecialist |
| GET | `/rcm/payer-enrollments` | List/filter enrollments by provider and/or payer | AccountManager, CredentialingSpecialist |
| POST | `/rcm/payer-enrollments/{id}/activate` | Activate an enrollment | CredentialingSpecialist |
| POST | `/rcm/payer-enrollments/{id}/terminate` | Terminate an enrollment | CredentialingSpecialist |
| POST | `/rcm/fee-schedules` | Create a draft fee schedule for a practice | AccountManager |
| GET | `/rcm/fee-schedules/{id}` | Fetch a fee schedule | AccountManager, Coder, PracticeUser |
| POST | `/rcm/fee-schedules/{id}/lines` | Add a priced CPT line to a draft fee schedule | AccountManager |
| GET | `/rcm/fee-schedules/{id}/lines` | List lines of a fee schedule | AccountManager, Coder, PracticeUser |
| POST | `/rcm/fee-schedules/{id}/activate` | Activate a draft fee schedule (OCC on the practice) | AccountManager |
| POST | `/rcm/claims` | Create a draft claim (charge-entry header) | Coder |
| GET | `/rcm/claims/{id}` | Fetch a claim with its computed ledger fields | AccountManager, Coder, Biller, DenialSpecialist, PaymentPoster, PracticeUser |
| POST | `/rcm/claims/{id}/lines` | Add a charge line to a draft claim | Coder |
| GET | `/rcm/claims/{id}/lines` | List a claim's charge lines | AccountManager, Coder, Biller, PracticeUser |
| GET | `/rcm/claims/{id}/denials` | List a claim's denials | AccountManager, DenialSpecialist, Biller, PracticeUser |
| GET | `/rcm/claims/{id}/postings` | List postings applied to a claim | AccountManager, PaymentPoster, Biller, PracticeUser |
| GET | `/rcm/claims/{id}/statements` | List patient statements for a claim | AccountManager, PaymentPoster, PracticeUser |
| POST | `/rcm/claims/{id}/scrub` | Coding scrub of a draft claim | Coder |
| POST | `/rcm/claims/{id}/submit` | Submit a scrubbed claim to the clearinghouse | Biller |
| POST | `/rcm/claims/{id}/accept` | Record clearinghouse acknowledgement | Biller |
| POST | `/rcm/claims/{id}/close` | Close a paid claim, write off a denied claim, or void a draft | Biller, Coder |
| POST | `/rcm/claims/{id}/denials` | Record a payer denial against a claim | DenialSpecialist |
| GET | `/rcm/denials/{id}` | Fetch a denial | AccountManager, DenialSpecialist, Biller |
| GET | `/rcm/denials/{id}/appeals` | List appeals for a denial | AccountManager, DenialSpecialist |
| POST | `/rcm/denials/{id}/appeals` | Draft an appeal against a denial | DenialSpecialist |
| GET | `/rcm/appeals/{id}` | Fetch an appeal | AccountManager, DenialSpecialist |
| POST | `/rcm/appeals/{id}/submit` | Submit an appeal (enforces appeal window; cascades) | DenialSpecialist |
| POST | `/rcm/appeals/{id}/decision` | Decide an appeal: overturn, uphold, or withdraw | DenialSpecialist |
| POST | `/rcm/remittances` | Create a remittance advice from a payer | PaymentPoster |
| GET | `/rcm/remittances/{id}` | Fetch a remittance with allocation totals | AccountManager, PaymentPoster |
| POST | `/rcm/remittances/{id}/postings` | Post an ERA line to a claim (OCC on the claim) | PaymentPoster |
| GET | `/rcm/remittances/{id}/postings` | List postings under a remittance | AccountManager, PaymentPoster |
| POST | `/rcm/remittances/{id}/finalize` | Finalize a fully-reconciled remittance | PaymentPoster |
| GET | `/rcm/payment-postings/{id}` | Fetch a payment posting | AccountManager, PaymentPoster |
| POST | `/rcm/payment-postings/{id}/reverse` | Reverse a posting (compensation) | PaymentPoster |
| POST | `/rcm/patient-statements` | Create a patient statement for a claim | PaymentPoster, AccountManager |
| GET | `/rcm/patient-statements/{id}` | Fetch a statement with current aging bucket | AccountManager, PaymentPoster, PracticeUser |
| POST | `/rcm/patient-statements/{id}/send` | Send a statement to the patient | PaymentPoster |
| POST | `/rcm/patient-statements/{id}/record-payment` | Record a patient payment | PaymentPoster |
| POST | `/rcm/patient-statements/{id}/collections` | Send an aged statement to collections | PaymentPoster |
| POST | `/rcm/patient-statements/{id}/write-off` | Write off a collections statement | AccountManager |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | AccountManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_NEGATIVE_AMOUNT` | 422 |
| `ERR_PRACTICE_NOT_FOUND` | 404 |
| `ERR_PAYER_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_FEE_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_DENIAL_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_REMITTANCE_NOT_FOUND` | 404 |
| `ERR_POSTING_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_CLAIM_LINES` | 422 |
| `ERR_NO_ACTIVE_FEE_SCHEDULE` | 422 |
| `ERR_CPT_NOT_IN_FEE_SCHEDULE` | 422 |
| `ERR_PROVIDER_NOT_CREDENTIALED` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 422 |
| `ERR_TIMELY_FILING_EXCEEDED` | 422 |
| `ERR_APPEAL_WINDOW_EXCEEDED` | 422 |
| `ERR_APPEAL_LIMIT_EXCEEDED` | 422 |
| `ERR_FEE_SCHEDULE_OVERLAP` | 409 |
| `ERR_ENROLLMENT_PERIOD_OVERLAP` | 409 |
| `ERR_OVERALLOCATION` | 422 |
| `ERR_REMITTANCE_NOT_BALANCED` | 422 |
| `ERR_STALE_VERSION` | 412 |











