# Public-Assistance Fraud & Recovery API — Product Requirements Document

## 1. Introduction

The Public-Assistance Fraud & Recovery Unit operates a regulated, tamper-evident workflow that carries an allegation of benefit fraud from an initial tip all the way through to the collection of recovered public funds. Investigators, hearing officers, recovery officers, and supervisors each own a distinct slice of that pipeline, and the integrity of the process depends on keeping their responsibilities separated: the person who investigates a case may not be the person who adjudicates the disqualification hearing that flows from it. This API is the system of record for that unit. It governs the intake and triage of referrals across the SNAP, TANF, and Medicaid programs; the opening and investigation of cases; the calculation of overpayment claims under both provisional (reported-income) and final (verified-income) methodologies; the imposition of intentional-program-violation disqualifications through administrative hearings; and the establishment, demand, and long-run recovery of the money owed.

Two accounting concerns dominate the design. The first is a strict separation between *provisional* figures produced early in a case and *finalized* figures affirmed once a claim is established, adjusted, and demanded. The second is a running principal-and-interest ledger against every established claim, where every payment, offset, or benefit recoupment is applied through a fixed waterfall and every reversal restores the ledger exactly. Because disqualification outcomes can retroactively reclassify a claim — turning an inadvertent-error claim into an intentional-violation claim and thereby changing its recoupment economics — the system must propagate such changes as controlled cascades across otherwise independent records. All timestamps that drive interest, penalties, and due dates are read from a server-controlled logical clock rather than wall-clock time, so that recovery timelines are reproducible and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint. Domain-specific workflow rules live in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's role. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are valid but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `Intake`, `Investigator`, `Adjudicator`, `RecoveryOfficer`, and `Supervisor`. `Intake` specialists register subjects and record and triage referrals. `Investigator` operators open cases, gather evidence, build overpayment claims, and propose disqualifications. `Adjudicator` operators schedule, hold, and decide administrative disqualification hearings. `RecoveryOfficer` operators issue demands, set up recovery plans, and post and void transactions. `Supervisor` operators hold the hierarchical override: they adjudicate cases, establish, adjust, and write off claims, rescind disqualifications, run reports, and control the logical clock. Every role may call all read and list endpoints.

For all five roles, `identity` is opaque: `X-User-ID` is an operator identifier that is not tied to any persisted entity and is never compared against any entity's `id`. The server does, however, record the acting operator's opaque identifier onto certain resources where the workflow demands an audit trail — the investigator assigned to a case is stored as `assigned_investigator_id`, the operator who submits an evidence item is stored as `submitted_by_user_id`, and the adjudicator who decides a hearing is stored as `decided_by_user_id`. These stored identifiers are later compared to one another (never to any entity `id`) to enforce the segregation-of-duties rule described in Section 3.5: when a hearing is decided, the acting adjudicator's `X-User-ID` must differ from the `assigned_investigator_id` of the case underlying the hearing, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` caps the number of items returned; it defaults to 10, has a minimum of 1, and a maximum of 100. `offset` is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range from 1 to 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties, Immutability, and Reference Validation

Most resources — Subjects, Referrals, Cases, Overpayments, Disqualifications, Hearings, Recovery Plans, and Recovery Transactions — carry a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation and `updated_at` advances on every mutation. `version` is an integer that begins at 1 and increments by exactly 1 on every mutation of the resource.

Two record types are append-only and immutable after creation, and therefore carry only `id` and `created_at` — they have neither `updated_at` nor `version`. Evidence items attached to a case are one; the per-month line items that make up an overpayment claim are the other. Once written, these records are never modified.

References passed in a request — whether a path identifier or a foreign-key field in the body — are validated left-to-right in the order they appear, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any later reference or business rule is evaluated. For example, when listing the evidence under a case, a non-existent case identifier surfaces `ERR_NOT_FOUND` before the evidence collection is consulted.

### 2.5. Monetary Precision, Rounding, and Derived-Field Reconciliation

All monetary amounts in the system are stored and returned as integer cents; there are no fractional cents and no floating-point money. Two rounding rules apply where a computation produces a non-integer intermediate value, and both use the round-half-up convention (a value exactly halfway between two integers rounds up to the larger magnitude). The first is the per-month interest charge described in Section 3.4, which is rounded to whole cents *for each month* before the months are summed — the sum is never computed from an unrounded product. The second is the percentage-of-allotment step of the recoupment formula in Section 3.6, which is rounded to whole cents before the floor and ceiling comparisons are applied. Priority scores are plain integers, and payoff-horizon projections are whole numbers of months produced by rounding up.

Several fields are derived rather than stored directly and are reconciled whenever the values they depend on change. A subject's `disqualification_status` and `disqualified_until`, an overpayment's `accrued_interest_cents`, `outstanding_principal_cents`, and `outstanding_interest_cents`, and a recovery plan's `projected_months_regulatory` and `projected_months_scheduled` are all recomputed from their inputs and the logical clock at read time. When a mutation changes a stored input that another resource derives from — for instance, reclassifying a claim's `claim_type` — the dependent resource is reconciled, its `updated_at` refreshed, and its `version` incremented.

### 2.6. The Logical Clock and Temporal Rules

The server maintains a single logical clock in UTC that is the authoritative "now" for every time-dependent computation: interest accrual, disqualification end dates, demand and due dates, and default eligibility. At startup the clock reads exactly `2026-05-01T00:00:00Z`; before any operator sets it, the clock stays at this default and never falls back to wall-clock time. A `Supervisor` may advance the clock to a supplied instant, passed as `to_iso8601`. The clock may only move forward: an attempt to set it to a value earlier than its current reading is rejected with `ERR_CLOCK_BACKWARDS` (HTTP 422).

Date and datetime inputs must be well-formed. A month affected by an overpayment is given as `benefit_month` in `YYYY-MM` form; plan and transaction dates are given as `YYYY-MM-DD`; scheduled hearing dates are ISO 8601 UTC datetimes. A value that does not match the expected pattern is rejected with `ERR_INVALID_MONTH_FORMAT` (HTTP 422); this format check applies to the creation of overpayment month line items, recovery plans, recovery transactions, and hearings.

### 2.7. Cascading State Propagation and Consistency

Several operations mutate more than one resource. When this happens, every downstream record is updated in the same operation and each independently has its `updated_at` refreshed and its `version` incremented (for resources that carry a version). Three cascade families exist and are specified in detail in Section 3: the imposition of a disqualification (which increments a subject's violation count, may reclassify a linked overpayment, and recomputes that overpayment's active recovery plan); the unsubstantiation of a case (which terminates a linked draft or calculated overpayment); and the full satisfaction or write-off of an overpayment (which completes or cancels its recovery plans). The system also bubbles a state change *upward*: when an overpayment's outstanding principal and outstanding interest both reach zero, the overpayment moves to `SATISFIED` and its active plans move to `COMPLETED` without a separate client request.

### 2.8. Optimistic Concurrency Control

Posting a fair-hearing adjustment against an overpayment is guarded by optimistic concurrency. The adjustment request must carry `expected_overpayment_version`, a non-optional field holding the `version` of the target overpayment that the client last observed. Because an adjustment recomputes the claim's finalized amount from the currently observed base, a client acting on a superseded base must not be allowed to overwrite work it has not seen. If `expected_overpayment_version` does not equal the overpayment's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the overpayment and retry against the fresh version. No other endpoint takes a version field or performs an OCC check.

### 2.9. Validation Ordering and Error Precedence

When multiple conditions could fail on a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN`), then existence of every path and foreign-key resource (`ERR_NOT_FOUND`). Next comes body well-formedness — required fields present and correctly typed (`ERR_VALIDATION`, HTTP 400) — followed by enum-membership checks (`ERR_INVALID_ENUM`, HTTP 422) and then date and month format checks (`ERR_INVALID_MONTH_FORMAT`). Pagination validity (`ERR_PAGINATION_INVALID`) is checked on list endpoints. Only after these do the state and business checks run: whether the target is in a valid non-terminal state for the requested transition (`ERR_INVALID_STATE`, HTTP 409), whether the transition was attempted from a terminal state (`ERR_ALREADY_TERMINAL`, HTTP 409), then the cross-entity state preconditions, the segregation-of-duties check, the domain-uniqueness constraints, the temporal constraints, the fiscal-threshold constraints, and finally the optimistic-concurrency check. In short: authentication before authorization before existence before shape before enum/format before pagination before state before cross-entity preconditions before segregation of duties before domain constraints before temporal before fiscal before concurrency.

## 3. Business Logic & Workflows

### 3.1. Subjects and the Referral Intake Pipeline

Everything begins with a **Subject** — a household member who may be the target of an allegation. An `Intake` specialist registers a subject with a `name`, the last four digits of a Social Security number in `ssn_last4` (retained purely for identity display and never used as a decision input), and a `primary_program` of `SNAP`, `TANF`, or `MEDICAID`. At creation the subject's `prior_ipv_count` is 0 and its `disqualification_status` is `NONE`. The subject exposes two derived fields on read: `disqualification_status`, which is one of `NONE`, `DISQUALIFIED`, or `PERMANENTLY_DISQUALIFIED`, computed from the subject's disqualification records and the logical clock; and `disqualified_until`, the latest end date across the subject's imposed, non-permanent disqualifications, which is null when the status is `NONE` or `PERMANENTLY_DISQUALIFIED`.

An `Intake` specialist then records a **Referral** against a subject by supplying `subject_id`, the `program` the allegation concerns (`SNAP`, `TANF`, or `MEDICAID`), the reporting `source` (`HOTLINE`, `DATA_MATCH`, `CASEWORKER`, or `PUBLIC`), and a free-text `allegation_summary`. A new referral enters `RECEIVED` status. At creation the system computes a triage `priority_score` by adding a program weight and a source weight: the program contributes 30 for `SNAP`, 20 for `TANF`, and 40 for `MEDICAID`; the source contributes 10 for `HOTLINE`, 25 for `DATA_MATCH`, 15 for `CASEWORKER`, and 5 for `PUBLIC`. The `priority_score` is the plain integer sum of those two weights — for example, a `MEDICAID` referral from a `DATA_MATCH` scores 65.

An `Intake` specialist triages a `RECEIVED` referral by supplying a `decision` with an optional `reason`. A decision of `ACCEPT` moves the referral from `RECEIVED` to `ACCEPTED`; a decision of `REJECT` moves it from `RECEIVED` to `REJECTED`, which is terminal. Referrals can be listed and filtered by `subject_id`, `status`, and `program`.

### 3.2. Opening and Investigating Cases

An `Investigator` opens a **Case** from an `ACCEPTED` referral by supplying its `referral_id`. The new case starts in `OPEN`, copies `subject_id` and `program` from the referral, and — as a cross-entity effect of opening the case — advances the source referral from `ACCEPTED` to `CONVERTED` (terminal). A referral that is not in `ACCEPTED` status cannot be converted. Cases can be listed and filtered by `referral_id`, `subject_id`, and `status`.

The investigative lifecycle then runs `OPEN → INVESTIGATION → PENDING_REVIEW`, with a supervisory review that may loop back. Assigning the case advances it from `OPEN` to `INVESTIGATION` and records the assigned investigator's opaque identifier in `assigned_investigator_id`; the acting operator may name a specific `investigator_user_id`, and when that field is omitted the acting `X-User-ID` is used. Throughout investigation, the assigned investigator attaches immutable **Evidence** items to the case, each with a `kind` of `DOCUMENT`, `INTERVIEW`, `DATA_MATCH`, or `SURVEILLANCE`, a `description`, and an optional external `document_ref`; the acting operator's identifier is stored as `submitted_by_user_id`, and the evidence carries `case_id`. Evidence for a case can be listed.

Submitting the case for review advances it from `INVESTIGATION` to `PENDING_REVIEW`, but only if at least one evidence item exists for the case; a submit-review attempt against a case with zero evidence is rejected with `ERR_NO_EVIDENCE` (HTTP 409). A `Supervisor` then adjudicates the `PENDING_REVIEW` case by supplying a `decision`. `RETURN` sends the case back from `PENDING_REVIEW` to `INVESTIGATION` for more work (the revision loop). `SUBSTANTIATE` advances it to `SUBSTANTIATED` (terminal), which is the precondition for establishing an overpayment and for referring a disqualification. `UNSUBSTANTIATE` advances it to `UNSUBSTANTIATED` (terminal) and cascades: any overpayment linked to this case (by `case_id`) that is still in `DRAFT` or `CALCULATED` is moved to `TERMINATED`, with its `updated_at` and `version` bumped. Because a recovery plan cannot exist until a claim is established and demanded — which itself requires a substantiated case — nothing further cascades from unsubstantiation.

### 3.3. Building the Overpayment Claim

An `Investigator` opens an **Overpayment** claim against a case by supplying `case_id` and a `claim_type` of `IPV` (intentional program violation), `IHE` (inadvertent household error), or `AE` (agency error). The claim begins in `DRAFT` with all amount fields at zero: `provisional_amount_cents`, `final_amount_cents`, `total_adjustments_cents`, `accrued_interest_cents`, `outstanding_principal_cents`, and `outstanding_interest_cents`. Overpayments can be listed and filtered by `case_id`, `status`, and `claim_type`.

The claim is built up from immutable per-month line items. Each **OverpaymentMonth** carries `overpayment_id`, a `benefit_month` in `YYYY-MM` form, and three integer-cent inputs: `benefits_issued_cents` (what was actually paid that month), `benefits_entitled_reported_cents` (what the household would have been entitled to using its reported income), and `benefits_entitled_verified_cents` (what it would have been entitled to using verified income). Two per-month over-issuance figures are computed and stored on the line item: `over_issuance_reported_cents` is the greater of zero and `benefits_issued_cents` minus `benefits_entitled_reported_cents`, and `over_issuance_verified_cents` is the greater of zero and `benefits_issued_cents` minus `benefits_entitled_verified_cents`. A given `benefit_month` may appear only once per claim; a duplicate is rejected with `ERR_DUPLICATE_MONTH` (HTTP 409). Month line items for a claim can be listed.

Calculating the claim advances it from `DRAFT` to `CALCULATED` and requires at least one month line item; a calculate attempt with zero months is rejected with `ERR_NO_OVERPAYMENT_MONTHS` (HTTP 422). Calculation produces both variants of the claim amount. The provisional figure, `provisional_amount_cents`, is the sum across all of the claim's months of each month's `over_issuance_reported_cents` — the reported-income variant, which excludes adjustments. The final figure, `final_amount_cents`, is the sum across all months of each month's `over_issuance_verified_cents` plus the running `total_adjustments_cents` — the verified-income variant. Because each month's over-issuance is clamped to a minimum of zero *before* the months are summed, a month in which the household was under-issued cannot offset over-issuance in another month. All month line items are included regardless of any status filter, because months are immutable.

### 3.4. Establishing, Demanding, Adjusting, and Writing Off Claims

Establishing a claim advances it from `CALCULATED` to `ESTABLISHED` and is performed by a `Supervisor`. Three preconditions apply. The claim must be in `CALCULATED`. The linked case must be `SUBSTANTIATED`, otherwise the request is rejected with `ERR_CASE_NOT_SUBSTANTIATED` (HTTP 409). And the claim's `final_amount_cents` must meet the establishment threshold for its `claim_type`: for an `IPV` claim the threshold is 0 cents, so any amount qualifies; for an `IHE` or `AE` claim the threshold is 12,500 cents (that is, $125.00). A final amount below the applicable threshold is rejected with `ERR_BELOW_ESTABLISHMENT_THRESHOLD` (HTTP 422). Establishment re-affirms `final_amount_cents` from the verified-income variant plus current adjustments.

A `RecoveryOfficer` then issues a demand, advancing the claim from `ESTABLISHED` to `DEMANDED`. Demand stamps `demand_date` with the current logical clock, sets `due_date` to `demand_date` plus 30 days, and anchors interest accrual. From the demand onward — while `outstanding_principal_cents` remains greater than zero — the claim accrues simple monthly interest on `final_amount_cents`. Interest is computed at read time as follows: let N be the number of full elapsed months between `demand_date` and the current logical clock, counting only whole monthly anniversaries and ignoring any partial final month; the per-month interest charge is `final_amount_cents` multiplied by the monthly rate of 0.01 (one percent), rounded half up to whole cents; and `accrued_interest_cents` is that per-month charge summed over the N months. The rounding order is fixed — round each month to whole cents, then sum — and this deliberately differs from multiplying the unrounded product by N. The interest base `final_amount_cents` is held constant across all N months.

A `Supervisor` may post a fair-hearing **adjustment** to a claim. The request carries an `adjustment_amount_cents` (a signed value that may raise or lower the claim), a `reason`, and the `expected_overpayment_version` described in Section 2.8. Posting an adjustment adds `adjustment_amount_cents` to the running `total_adjustments_cents`, recomputes `final_amount_cents` (the verified-income sum plus the new `total_adjustments_cents`), and increments the overpayment's `version` by 1. If `expected_overpayment_version` does not match the overpayment's current `version`, the post is refused with `ERR_STALE_VERSION` (HTTP 412) and nothing changes.

Two derived balances drive recovery. `outstanding_principal_cents` is `final_amount_cents` minus the sum of `applied_to_principal_cents` across the claim's posted recovery transactions, and `outstanding_interest_cents` is `accrued_interest_cents` minus the sum of `applied_to_interest_cents` across those same posted transactions. When both reach zero the claim bubbles up to `SATISFIED` and its active plans to `COMPLETED`, as described in Section 3.7. Alternatively, a `Supervisor` may write off an uncollectible claim, advancing it from `IN_RECOVERY` to `WRITTEN_OFF` with a `reason`; write-off is permitted only while `outstanding_principal_cents` is greater than zero, and it cancels every non-terminal recovery plan of the claim (moving each to `CANCELLED`).

### 3.5. Disqualification, ADH Referral, and Hearings

An `Investigator` proposes a **Disqualification** for a case's subject by supplying `case_id`; the new record enters `PROPOSED` and copies `subject_id` from the case. A proposal is refused with `ERR_SUBJECT_ALREADY_DISQUALIFIED` (HTTP 409) if the subject already carries an active imposed disqualification — that is, if the subject's `disqualification_status` is `DISQUALIFIED` or `PERMANENTLY_DISQUALIFIED`. Disqualifications can be listed and filtered by `case_id`, `subject_id`, and `status`. A disqualification exposes `penalty_months`, `is_permanent`, `imposed_at`, and its own `disqualified_until`, all of which remain null or unset until the disqualification is imposed.

The `Investigator` refers a `PROPOSED` disqualification to an Administrative Disqualification Hearing (ADH), advancing it from `PROPOSED` to `ADH_REFERRED`; this requires the linked case to be `SUBSTANTIATED`, otherwise the referral is rejected with `ERR_CASE_NOT_SUBSTANTIATED` (HTTP 409). An `Adjudicator` schedules a **Hearing** for an `ADH_REFERRED` disqualification by supplying `disqualification_id` and a `scheduled_date`; the hearing enters `SCHEDULED`. Scheduling against a disqualification that is not in `ADH_REFERRED` is rejected with `ERR_ADH_NOT_REFERRED` (HTTP 409). Hearings can be listed and filtered by `disqualification_id` and `status`. The `Adjudicator` then holds the hearing, advancing it from `SCHEDULED` to `HELD` and stamping `held_at` with the current logical clock.

Deciding a `HELD` hearing takes an `outcome` and records the deciding operator in `decided_by_user_id`. Before any branch runs, the segregation-of-duties rule is enforced: the acting `Adjudicator`'s `X-User-ID` must differ from the `assigned_investigator_id` of the case underlying the hearing, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). An `outcome` of `IPV` advances the hearing to `DECIDED_IPV`, sets `outcome` to `IPV`, and imposes the linked disqualification. An `outcome` of `NO_IPV` advances the hearing to `DECIDED_NO_IPV`, and an `outcome` of `DISMISSED` advances it to `DISMISSED`; both of these set the corresponding `outcome`, and both decline the linked disqualification — moving it from `ADH_REFERRED` to `DECLINED` with no penalty and no change to the subject or any overpayment.

Imposition is a three-hop cascade triggered when a hearing is decided `IPV`. First, the linked disqualification advances from `ADH_REFERRED` to `IMPOSED`. At that moment its penalty is computed from the subject's `prior_ipv_count` observed *before* the increment: a count of 0 yields `penalty_months` of 12 with `is_permanent` false; a count of 1 yields `penalty_months` of 24 with `is_permanent` false; a count of 2 or more yields a permanent (third-strike) ban, with `penalty_months` null and `is_permanent` true. `imposed_at` is set to the current logical clock, and `disqualified_until` is set to `imposed_at` plus `penalty_months` months (null for a permanent ban). The first cascade link then increments the subject's `prior_ipv_count` by 1 and recomputes the subject's `disqualification_status`. The second link, caused by the first, reclassifies the linked case's overpayment — if one exists and is non-terminal — by setting its `claim_type` to `IPV` and bumping its `updated_at` and `version`. The third link, caused by the second, recomputes that overpayment's active recovery plan: its `monthly_recoupment_cents` is re-derived using the `IPV` rate and floor, and its projections are refreshed.

A `Supervisor` may rescind an `IMPOSED` disqualification, advancing it from `IMPOSED` to `RESCINDED` with a `reason`. Rescission is a compensating action: it decrements the subject's `prior_ipv_count` by 1, recomputes the subject's `disqualification_status`, and clears the disqualification's `disqualified_until`.

### 3.6. Recovery Plans and the Recoupment Formula

A `RecoveryOfficer` creates a **RecoveryPlan** for a `DEMANDED` overpayment by supplying `overpayment_id`, a `method`, a `start_date`, an optional `end_date`, an optional `monthly_allotment_cents`, and an optional `scheduled_monthly_cents`. Creating the plan advances the overpayment from `DEMANDED` to `IN_RECOVERY`; a plan against an overpayment that is not `DEMANDED` is rejected with `ERR_OVERPAYMENT_NOT_DEMANDED` (HTTP 409). The plan enters `ACTIVE` and resolves its own `subject_id` by following the chain from the overpayment to its case to that case's subject. The `method` is `RECOUPMENT` (reducing the household's ongoing benefit allotment), `OFFSET` (a tax or other offset), or `COLLECTION` (cash installments). The `start_date` (in `YYYY-MM-DD`) is the inclusive lower bound of the recoupment period; the `end_date` (in `YYYY-MM-DD`) is the exclusive upper bound and is null for an open-ended `COLLECTION`. The `monthly_allotment_cents` is the current monthly benefit allotment and is required for a `RECOUPMENT` plan, since it is the basis of the recoupment-rate formula. A `RECOUPMENT` plan may not be created for a subject who already has an overlapping active recoupment plan whose `[start_date, end_date)` range intersects this one; such an overlap is rejected with `ERR_OVERLAPPING_RECOVERY_PLAN` (HTTP 409). Recovery plans can be listed and filtered by `overpayment_id`, `subject_id`, and `status`.

For a `RECOUPMENT` plan, `monthly_recoupment_cents` is computed from the claim's `claim_type`, the `monthly_allotment_cents`, and the current `outstanding_principal_cents`. The rate is 0.20 (twenty percent) when the `claim_type` is `IPV` and 0.10 (ten percent) for both `IHE` and `AE`. The floor is 2,000 cents ($20.00) when the `claim_type` is `IPV` and 1,000 cents ($10.00) for `IHE` and `AE`. The percentage amount is `monthly_allotment_cents` multiplied by the applicable rate, rounded half up to whole cents. The monthly recoupment is then the smaller of the outstanding principal and the larger of the applicable floor and that percentage amount — in other words, the recoupment is at least the floor but never more than what is still owed. This is exactly the figure re-derived by the third hop of the imposition cascade in Section 3.5 when a claim is reclassified to `IPV`.

A recovery plan also exposes two payoff-horizon projections, recomputed on read. `projected_months_regulatory` is `outstanding_principal_cents` divided by `monthly_recoupment_cents`, rounded up to a whole number of months — the horizon at the regulatory-minimum pace. `projected_months_scheduled` is `outstanding_principal_cents` divided by the agreed `scheduled_monthly_cents`, rounded up to a whole number of months — the horizon at the agreed-schedule pace, which is typically shorter because the scheduled amount is usually larger. A `RecoveryOfficer` may mark an `ACTIVE` plan `DEFAULTED`, advancing it from `ACTIVE` to `DEFAULTED`, but only when the logical clock is strictly past the overpayment's `due_date` and `outstanding_principal_cents` is still greater than zero.

### 3.7. Posting and Voiding Recovery Transactions

A `RecoveryOfficer` posts a **RecoveryTransaction** against a plan by supplying `recovery_plan_id`, an `amount_cents`, a `transaction_date` (in `YYYY-MM-DD`), and a `method` of `PAYMENT`, `OFFSET`, or `RECOUPMENT`. The posting resolves its `overpayment_id` from the plan, enters `POSTED`, and is applied to the overpayment ledger through a fixed interest-first waterfall: `applied_to_interest_cents` is the smaller of `amount_cents` and the overpayment's `outstanding_interest_cents` at the moment of posting, and `applied_to_principal_cents` is whatever of `amount_cents` remains after interest — that is, `amount_cents` minus `applied_to_interest_cents`. The `transaction_date` must be on or after the plan's `start_date`; an earlier date is rejected with `ERR_TRANSACTION_BEFORE_PLAN_START` (HTTP 422). The `amount_cents` may not exceed the overpayment's total outstanding balance (outstanding interest plus outstanding principal); an amount that exceeds it is rejected with `ERR_AMOUNT_EXCEEDS_BALANCE` (HTTP 422). Transactions can be listed for a single plan and, separately, across all of an overpayment's plans.

Posting reduces the overpayment's outstanding balances. When both `outstanding_principal_cents` and `outstanding_interest_cents` reach zero, the overpayment bubbles up from `IN_RECOVERY` to `SATISFIED` and each of its active plans moves to `COMPLETED`. A `RecoveryOfficer` may void a `POSTED` transaction with an optional `reason`, advancing it from `POSTED` to `VOIDED`; a void is a compensating reversal that removes the transaction's `applied_to_principal_cents` and `applied_to_interest_cents` from the overpayment's ledger sums, restoring `outstanding_principal_cents` and `outstanding_interest_cents`. Voids are only permitted while the overpayment is in `IN_RECOVERY`; if a previously satisfied overpayment would regain an outstanding balance, it is not automatically reopened. Voiding a transaction that is already `VOIDED` is rejected with `ERR_ALREADY_VOIDED` (HTTP 409).

### 3.8. Recovery Reporting

A `Supervisor` may run an aggregate recovery report across overpayments, optionally narrowed by `program` and by `claim_type`. The report returns five totals over the matching overpayments: `total_final_amount_cents`, `total_accrued_interest_cents`, `total_recovered_principal_cents`, `total_outstanding_cents`, and `overpayment_count`. Because the report reflects the same derived interest and outstanding balances defined in Sections 3.4 and 3.7, its figures are computed against the current logical clock at the time of the request.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return HTTP 201 Created. Operations that modify an existing resource — including state transitions and adjustments — return HTTP 200 OK, as do all read and list operations. The complete request and response semantics for each endpoint are described in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fraud-recovery/subjects` | Create a Subject | Intake |
| GET | `/fraud-recovery/subjects/{id}` | Fetch a Subject | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/referrals` | Create a Referral | Intake |
| GET | `/fraud-recovery/referrals/{id}` | Fetch a Referral | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| GET | `/fraud-recovery/referrals` | List/filter Referrals | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/referrals/{id}/decide` | Accept or reject a Referral | Intake |
| POST | `/fraud-recovery/cases` | Open a Case from an ACCEPTED Referral | Investigator |
| GET | `/fraud-recovery/cases/{id}` | Fetch a Case | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| GET | `/fraud-recovery/cases` | List/filter Cases | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/cases/{id}/assign` | Assign an Investigator; OPEN → INVESTIGATION | Investigator |
| POST | `/fraud-recovery/cases/{id}/submit-review` | Submit case for review; INVESTIGATION → PENDING_REVIEW | Investigator |
| POST | `/fraud-recovery/cases/{id}/adjudicate` | Substantiate, unsubstantiate, or return a case | Supervisor |
| POST | `/fraud-recovery/cases/{id}/evidence` | Attach an immutable Evidence item | Investigator |
| GET | `/fraud-recovery/cases/{id}/evidence` | List Evidence for a Case | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/overpayments` | Create a DRAFT Overpayment claim | Investigator |
| GET | `/fraud-recovery/overpayments/{id}` | Fetch an Overpayment | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| GET | `/fraud-recovery/overpayments` | List/filter Overpayments | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/overpayments/{id}/months` | Add an immutable OverpaymentMonth line item | Investigator |
| GET | `/fraud-recovery/overpayments/{id}/months` | List OverpaymentMonth line items | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/overpayments/{id}/calculate` | Compute provisional and final amounts | Investigator |
| POST | `/fraud-recovery/overpayments/{id}/establish` | Establish the claim; CALCULATED → ESTABLISHED | Supervisor |
| POST | `/fraud-recovery/overpayments/{id}/demand` | Issue demand; ESTABLISHED → DEMANDED | RecoveryOfficer |
| POST | `/fraud-recovery/overpayments/{id}/adjustments` | Post a fair-hearing adjustment (OCC-guarded) | Supervisor |
| POST | `/fraud-recovery/overpayments/{id}/write-off` | Write off an uncollectible claim | Supervisor |
| POST | `/fraud-recovery/disqualifications` | Propose an IPV disqualification | Investigator |
| GET | `/fraud-recovery/disqualifications/{id}` | Fetch a Disqualification | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| GET | `/fraud-recovery/disqualifications` | List/filter Disqualifications | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/disqualifications/{id}/refer-adh` | Refer to ADH; PROPOSED → ADH_REFERRED | Investigator |
| POST | `/fraud-recovery/disqualifications/{id}/rescind` | Rescind an imposed disqualification | Supervisor |
| POST | `/fraud-recovery/hearings` | Schedule an ADH | Adjudicator |
| GET | `/fraud-recovery/hearings/{id}` | Fetch a Hearing | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| GET | `/fraud-recovery/hearings` | List/filter Hearings | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/hearings/{id}/hold` | Mark the hearing held; SCHEDULED → HELD | Adjudicator |
| POST | `/fraud-recovery/hearings/{id}/decide` | Decide the hearing | Adjudicator |
| POST | `/fraud-recovery/recovery-plans` | Create a RecoveryPlan for a DEMANDED Overpayment | RecoveryOfficer |
| GET | `/fraud-recovery/recovery-plans/{id}` | Fetch a RecoveryPlan | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| GET | `/fraud-recovery/recovery-plans` | List/filter RecoveryPlans | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/recovery-plans/{id}/default` | Mark a plan DEFAULTED | RecoveryOfficer |
| POST | `/fraud-recovery/recovery-transactions` | Post a recovery transaction | RecoveryOfficer |
| GET | `/fraud-recovery/recovery-plans/{id}/transactions` | List transactions for a plan | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| GET | `/fraud-recovery/overpayments/{id}/transactions` | List transactions across an overpayment's plans | Intake, Investigator, Adjudicator, RecoveryOfficer, Supervisor |
| POST | `/fraud-recovery/recovery-transactions/{id}/void` | Void a posted transaction | RecoveryOfficer |
| GET | `/fraud-recovery/reports/recovery-summary` | Aggregate recovery report | Supervisor |
| POST | `/_clock/set_current_utc` | Advance the server logical clock | Supervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_MONTH_FORMAT` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_NO_EVIDENCE` | 409 |
| `ERR_CASE_NOT_SUBSTANTIATED` | 409 |
| `ERR_ADH_NOT_REFERRED` | 409 |
| `ERR_OVERPAYMENT_NOT_DEMANDED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SUBJECT_ALREADY_DISQUALIFIED` | 409 |
| `ERR_DUPLICATE_MONTH` | 409 |
| `ERR_OVERLAPPING_RECOVERY_PLAN` | 409 |
| `ERR_NO_OVERPAYMENT_MONTHS` | 422 |
| `ERR_BELOW_ESTABLISHMENT_THRESHOLD` | 422 |
| `ERR_AMOUNT_EXCEEDS_BALANCE` | 422 |
| `ERR_TRANSACTION_BEFORE_PLAN_START` | 422 |
| `ERR_CLOCK_BACKWARDS` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ALREADY_VOIDED` | 409 |
