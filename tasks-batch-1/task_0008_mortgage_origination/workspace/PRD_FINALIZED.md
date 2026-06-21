# Mortgage Origination API — Product Requirements Document

## 1. Introduction

Originating a residential mortgage means stewarding a single loan file through a sequence of independently regulated milestones — pre-qualification of the borrower, verification of income and assets, valuation of the subject property, examination of the title, locking of the interest rate, drafting and delivery of the federally mandated cost disclosures, and finally the closing itself — without ever losing track of which step's outcome has already shaped the next. The Mortgage Origination API exists to give a lender's operations staff, compliance reviewers, and the applicants themselves a single, ordered system of record for that journey.

The product is designed around three pressures that simultaneously act on every loan file. First, the **regulatory** pressure of the TILA-RESPA Integrated Disclosure rule and UDAAP enforcement: a closing cannot occur until specific federal waiting periods have elapsed since disclosures were delivered, and any compliance flag raised by a reviewer must be cleared before approval. Second, the **financial** pressure of a rate-lock contract: the lock has a duration, costs the lender money to extend, and may be invalidated by an unfavorable appraisal — meaning state changes ripple across more than one entity at once. Third, the **operational** pressure of segregation of duties: the loan officer who originates a file must not be the underwriter who approves it. The API encodes these pressures as first-class invariants rather than letting them live in human runbooks, so that two correctly-implemented clients of the same API exchange loan files with identical outcomes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity they are acting in. Requests missing either header are rejected with `ERR_UNAUTHENTICATED`. Requests whose `X-User-Role` is not one of the recognized role names, or whose role lacks permission for the requested endpoint, are rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly seven roles: `LoanOfficer`, `Underwriter`, `Closer`, `Appraiser`, `TitleAgent`, `ComplianceOfficer`, and `Applicant`. Six of these — `LoanOfficer`, `Underwriter`, `Closer`, `Appraiser`, `TitleAgent`, and `ComplianceOfficer` — are operator roles whose `X-User-ID` is an opaque operator identifier not tied to any persisted entity in the system; the server may record such an identifier in audit-style fields (for example, recording the originating `LoanOfficer`'s `X-User-ID` on the loan application at the moment of pre-qualification, which the segregation-of-duties rule later compares against), but it never reconciles the value against any entity's `id`. The seventh role, `Applicant`, is entity-backed: when `X-User-Role` is `Applicant`, the value of `X-User-ID` is the `id` of the acting `Applicant` record, and any ownership check on a resource that references an applicant compares the resource's `applicant_id` foreign key to `X-User-ID`.

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

Every list endpoint accepts two query parameters that control pagination. The `limit` parameter caps the number of items in the page and defaults to 10 when omitted; it must be at least 1 and at most 100. The `offset` parameter selects how many items to skip from the head of the result set and defaults to 0. List endpoints return their items sorted by `created_at` in ascending order unless an endpoint description explicitly says otherwise.

The response envelope's `meta` object on every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most top-level resources in the system — `Applicant`, `LoanApplication`, `IncomeVerification`, `AssetVerification`, `Appraisal`, `TitleSearch`, `RateLock`, and `Disclosure` — carry a shared set of system-managed fields. Each such resource has an `id`, which is a server-minted UUID with no domain-specific prefix; a `created_at` timestamp recorded when the resource is first stored; an `updated_at` timestamp refreshed on every successful mutation; and a `version` integer that begins at 1 (or at whatever the implementation chooses for a freshly created resource) and increments by exactly one on every successful mutation of that resource. All timestamps are written in ISO 8601 UTC with three fractional digits.

The `UDAAPCheck` resource is the single exception. It is an append-only audit record: once written, it is never edited. It therefore carries only `id` and `created_at`. It does not carry an `updated_at` field and does not carry a `version` field.

### 2.5. Optimistic Concurrency Control

Two endpoints in this API are gated by optimistic concurrency control against the parent `LoanApplication`'s `version`. Creating a new rate lock against a loan application requires the request body to carry `expected_application_version` as a non-optional field, set to the `version` the client last observed on the loan application. If the loan application's current `version` has advanced — for example, because another writer created a different rate lock that legitimately superseded the prior `ACTIVE` lock and thereby bumped the application's `version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Likewise, creating a new disclosure requires `expected_application_version` to match the loan application's current `version`; a stale value yields the same `ERR_STALE_VERSION` (HTTP 412). These rules are framed in stale-version terms rather than racing-writer terms: even with two strictly sequential requests, if the second request was prepared against a snapshot the first request has since invalidated, it is the second request that the server rejects.

No other endpoint in the API takes a version field. Endpoints not listed above accept no `expected_*_version` input and run without an OCC check.

### 2.6. Hierarchical Consistency and Cascading Mutations

A single user action frequently mutates more than one entity. When a side effect changes a parent or sibling resource — whether it is incrementing the parent loan application's `version`, refreshing its `updated_at`, transitioning a rate lock to `SUPERSEDED` because the closing has completed, or auto-denying a loan application because a freshly completed appraisal pushed the loan-to-value ratio over its ceiling — the system performs every leg of the cascade as part of the same operation, and each affected resource's `updated_at` and `version` are updated in lockstep with the state transition.

Two cascades are particularly load-bearing and are detailed in §3. The first is the **appraisal-LTV cascade**: a completion or reconsideration of the appraisal recomputes the loan's `ltv_ratio` against the appraised value, and if that recomputed ratio exceeds the conforming ceiling the loan application is auto-transitioned to `DENIED`, which in turn cancels any `ACTIVE` rate lock on the application — three entities mutating from a single appraiser action. The second is **rate-lock supersession**: creating a new rate lock on a loan application automatically transitions any prior `ACTIVE` lock on that application to `SUPERSEDED`, bumping both the prior lock's `version` and the parent application's `version`. Each cascade hop independently increments the affected entity's `version` and refreshes its `updated_at`.

### 2.7. Nested Resource Retrieval

Many endpoints carry an identifier in the URL path (and, for create endpoints, a foreign-key identifier in the request body). The system validates these identifiers left-to-right. If a path segment names a loan application that does not exist, the request is rejected with `ERR_APPLICATION_NOT_FOUND` (HTTP 404) before any sub-resource segment is examined. If a sub-resource segment — referring to an income verification, asset verification, appraisal, title search, rate lock, disclosure, or UDAAP check — does not exist, the request is rejected with `ERR_SUBRESOURCE_NOT_FOUND` (HTTP 404). A path segment on `GET /applicants/{id}` that names a non-existent applicant is rejected with `ERR_APPLICANT_NOT_FOUND` (HTTP 404), the same error_id used for missing applicant referents in request bodies. Foreign-key identifiers in the request body — the `applicant_id` on a loan application, or the `application_id` on any sub-resource — are validated the same way, and a missing referent is rejected with `ERR_APPLICANT_NOT_FOUND` (HTTP 404). Body-shape problems unrelated to existence (a missing required field, an enum value outside its declared set, an integer outside its declared range) are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Validation Priority Ordering

When a single request triggers multiple checks, the system applies them in a fixed priority order so that the same failure scenario always surfaces the same `error_id`. Authentication is evaluated first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of the path's primary resource (`ERR_APPLICATION_NOT_FOUND`), then the sub-resource path id (`ERR_SUBRESOURCE_NOT_FOUND`), then foreign-key existence in the body (`ERR_APPLICANT_NOT_FOUND`), then current-state legality (`ERR_INVALID_STATE`), then optimistic concurrency on the parent's `version` (`ERR_STALE_VERSION`), and only after all of the above succeed does the server evaluate business safety, business constraints, business temporal checks, business referential checks, and finally request shape (`ERR_INVALID_REQUEST`, which is last so that more meaningful business rejections are surfaced before generic shape complaints).

Within the business tier, the relative order is also fixed: the UDAAP gate on approval (`ERR_UDAAP_BLOCKED`) fires before the TRID waiting period check on close (`ERR_TRID_WAITING_PERIOD`), which fires before the front-end debt-to-income ceiling on pre-qualification (`ERR_DTI_FRONTEND_TOO_HIGH`), which fires before the rate-lock extension cap (`ERR_EXTENSION_CAP_EXCEEDED`), which fires before the validation of the extension day count (`ERR_INVALID_EXTEND_DAYS`). On the extension endpoint specifically, the temporal check that the lock has not already expired (`ERR_LOCK_EXPIRED`) fires ahead of the extension-count cap, and the ninety-day total-duration cap (`ERR_LOCK_DURATION_CAP_EXCEEDED`) is also a business-temporal rule on the same endpoint. The UDAAP-reasons shape check (`ERR_UDAAP_REASONS_INVALID`), the closing-disclosure re-disclosure gate (`ERR_CD_REDISCLOSE_REQUIRED`), and the segregation-of-duties check (`ERR_SOD_VIOLATION`) round out the business tier.

### 2.9. Monetary Precision, Ratio Precision, and Time Arithmetic

Monetary amounts are stored and exchanged in **integer cents**: every field whose name ends in `_cents` is a non-negative integer (or, for principal amounts, a strictly positive integer) representing whole cents. Internal arithmetic that produces a cents value rounds half-up to whole cents.

Ratios — front-end debt-to-income, back-end debt-to-income, and loan-to-value — are stored as decimal numbers to four decimal places using round half-up. APR is stored as a percentage to three decimal places using round half-up (for example, an APR of about six and seven-eighths percent is stored as the number 6.875).

Calendar arithmetic for TRID waiting periods and for rate-lock expiry and extension uses wall-clock UTC: "plus N calendar days" means adding exactly N times 86400 seconds, with no daylight-saving adjustments. Timestamps are stored to millisecond precision and serialized in ISO 8601 UTC with three fractional digits.

### 2.10. Test-Driving the Clock

Because the system's correctness depends on calendar arithmetic — TRID waiting periods, rate-lock expiry, the 90-day total-duration cap on a lock — the server exposes an admin-only test-driving capability that advances the logical clock to a supplied `to_iso8601` instant. The capability is accepted from every role so that automated test scripts running as any persona can move the clock forward to drive deterministic expiry and waiting-period behavior. It does not mutate any business entity.

## 3. Business Logic & Workflows

### 3.1. Applicants and the Origination of a Loan File

The system's foundation is the **Applicant** — the prospective borrower whose financial profile drives every downstream eligibility check. A `LoanOfficer` records a new applicant by supplying the applicant's `full_name`, a contact `email` whose uniqueness the system enforces across all non-archived applicants, the last four digits of the applicant's Social Security number as a four-digit string `ssn_last4` used as a soft-pull keying token, the applicant's stated `annual_income_cents` and `monthly_debt_cents` (both non-negative integer cents), a soft-pull `credit_score` that must be at least 300 and at most 850, and the USPS two-letter `state_code` of the applicant's residence.

With an applicant on file, the same `LoanOfficer` originates a **LoanApplication** by supplying the `applicant_id` of the borrower, the free-text `property_address` of the subject property, the property's USPS two-letter `property_state_code`, a `loan_purpose` that is either `PURCHASE` or `REFINANCE`, the borrower's `requested_loan_amount_cents` as a positive integer cents value, the stated `property_value_cents` (purchase price for `PURCHASE`, applicant's pre-appraisal estimate for `REFINANCE`), and a `loan_term_months` that must be either 180 or 360. The newly created loan application has its `status` set to `DRAFT`, and the system permanently records the originating `LoanOfficer`'s `X-User-ID` against the application for use by the later segregation-of-duties check at approval time.

`Applicant` is the only role in the system whose `X-User-ID` is an entity identifier; for all other roles the value is an opaque operator string the server does not reconcile against any record.

### 3.2. Pre-Qualification and the Auto-Branch to Denial

Pre-qualification is the gateway from `DRAFT` into the rest of the lifecycle. It is initiated by a `LoanOfficer` against an application that is still in `DRAFT` whose applicant carries a `credit_score` of at least 580 and whose `requested_loan_amount_cents` is at or below the conforming cap of four hundred million cents (four million dollars). The pre-qualification step computes three derived numbers on the loan application: `front_end_dti`, `back_end_dti`, and the provisional `ltv_ratio`.

The two debt-to-income figures share a single intermediate quantity. The applicant's gross monthly income, in cents, is derived by taking the applicant's `annual_income_cents` and dividing by 12, floored to whole cents before any further division. The housing payment is the monthly principal-and-interest payment computed from the standard amortization formula: the requested loan amount in cents is multiplied by the monthly rate, then divided by one minus the quantity (one plus the monthly rate) raised to the power of negative `loan_term_months`; the result is rounded half-up to whole cents and stored as the housing payment. The monthly rate is the locked interest rate in basis points divided by ten thousand and then by twelve when an `ACTIVE` rate lock exists on the application; otherwise it is the default underwriting rate of 700 basis points (7.00 percent) divided by ten thousand and then by twelve. Taxes and insurance are not modeled in this housing payment. The `front_end_dti` is then the housing payment divided by the monthly income, rounded half-up to four decimal places. The `back_end_dti` adds the applicant's `monthly_debt_cents` to the housing payment in the numerator and divides by the same monthly income, again rounded half-up to four decimal places. At pre-qualification the system uses only the applicant's stated `annual_income_cents`; the `verified_annual_income_cents` from any income verification does not feed pre-qualification.

The provisional `ltv_ratio` at this stage is the `requested_loan_amount_cents` divided by the applicant-stated `property_value_cents`, rounded half-up to four decimal places.

A front-end DTI strictly greater than 0.31 short-circuits pre-qualification with `ERR_DTI_FRONTEND_TOO_HIGH`, ahead of any approve/deny branching on back-end DTI or LTV — this is the front-end ceiling.

If the front-end check passes, the system evaluates the auto-branch: when the `back_end_dti` is at most 0.43 **and** the `ltv_ratio` is at most 0.95, the `prequal_decision` is set to `APPROVED` and the loan application transitions from `DRAFT` to `PREQUALIFIED`. When either threshold is exceeded — `back_end_dti` strictly greater than 0.43 or `ltv_ratio` strictly greater than 0.95 — the `prequal_decision` is set to `DENIED` and the loan application transitions from `DRAFT` directly to `DENIED` instead of `PREQUALIFIED`. Either outcome increments the loan application's `version` by one.

### 3.3. Verifying Income and Verifying Assets

Once the application is in `PREQUALIFIED`, the `LoanOfficer` collects supporting documentation. An **IncomeVerification** is created with its `application_id`, a `document_type` that is one of `W2`, `PAYSTUB`, `TAX_RETURN`, or `BANK_DEPOSITS`, and a `verified_annual_income_cents` value the underwriter will subsequently confirm. An **AssetVerification** is created with its `application_id`, an `asset_type` that is one of `CHECKING`, `SAVINGS`, `BROKERAGE`, or `RETIREMENT`, and a `verified_balance_cents` value. Both kinds of verification begin in `PENDING`.

An `Underwriter` reviews each verification while the parent loan application is in either `PREQUALIFIED` or `UNDER_REVIEW`. Accepting a verification transitions it from `PENDING` to `ACCEPTED` and increments its `version`. Rejecting a verification requires a non-empty `rejection_reason` in the request body; the system records that reason on the verification, transitions it from `PENDING` to `REJECTED`, and increments its `version`. A rejected verification's `rejection_reason` is otherwise `null`.

### 3.4. Appraisal, the LTV Re-Computation, and the Two-Hop Cascade

A `LoanOfficer` orders an **Appraisal** by supplying only the `application_id`; the appraisal is born in `ORDERED` with `appraised_value_cents` and `reconsideration_note` both `null`. An `Appraiser` reports completion by supplying a strictly positive `appraised_value_cents`, transitioning the appraisal from `ORDERED` to `COMPLETED`. If the borrower or loan officer contests the value, the `LoanOfficer` initiates a Reconsideration of Value by submitting both a non-empty `reconsideration_note` and a new strictly positive `new_appraised_value_cents`; the appraisal moves from `COMPLETED` to `RECONSIDERED`, the new value overwrites the prior `appraised_value_cents`, and the note is stored on the appraisal. The `Appraiser` may then confirm the reconsidered value, returning the appraisal from `RECONSIDERED` to `COMPLETED`. This `COMPLETED → RECONSIDERED → COMPLETED` loop may repeat any number of times while the parent loan application is non-terminal.

The appraisal interacts with the rest of the system through a recomputation of the loan-to-value ratio. On every `ORDERED → COMPLETED` and `COMPLETED → RECONSIDERED` transition, the system recomputes `ltv_ratio` for the loan application using the **lesser** of the applicant-stated `property_value_cents` and the appraisal's `appraised_value_cents` in the denominator — the requested loan amount divided by that minimum, rounded half-up to four decimal places.

If that recomputed `ltv_ratio` exceeds 0.95, a second cascade hop fires automatically: the loan application is auto-transitioned to `DENIED` from whichever non-terminal state it currently inhabits (either `PREQUALIFIED` or `UNDER_REVIEW`, symmetrically). The auto-denial is the second hop. The third hop follows immediately on the rate lock: if the application had an `ACTIVE` rate lock, that lock is transitioned to `CANCELLED` as a side effect of the auto-denial. The original appraiser action thus mutates three entities — the appraisal itself, the loan application, and the active rate lock — and increments three `version` counters; if the auto-deny hop fires, the loan application receives an additional `version` increment on top of the one from the recomputation. Every appraisal completion or reconsideration that does **not** push LTV over 0.95 still bumps the appraisal's `version` and the loan application's `version` once, but does not touch the rate lock.

### 3.5. Title Search

In parallel with the appraisal, the `LoanOfficer` orders a **TitleSearch** by supplying only the `application_id`; the title search is born in `ORDERED`. A `TitleAgent` then drives it to one of three states. Marking it clear transitions it from `ORDERED` to `CLEAR`. Reporting a defect requires a non-empty `exception_summary` in the request body and transitions the title search from `ORDERED` to `EXCEPTIONS_FOUND`, recording the summary on the resource. Curing a previously raised exception transitions the title search from `EXCEPTIONS_FOUND` to `CURED`. All three transitions are permitted only while the parent loan application is in `PREQUALIFIED` or `UNDER_REVIEW`, and each increments the title search's `version` by one. A title search in `CLEAR` or `CURED` is the form acceptable for approval; one still in `ORDERED` or `EXCEPTIONS_FOUND` is not.

### 3.6. Rate Locking and Lock Extension

A `LoanOfficer` creates a **RateLock** against a loan application by supplying the `application_id`, the locked interest rate as an integer in basis points (`locked_rate_bps`) — for example, a rate of 6.875 percent is recorded as 687 — and a `lock_term_days` that must be one of 30, 45, or 60. The request body must also carry `expected_application_version` matching the loan application's current `version`; this is the OCC gate described in §2.5. Creation stamps `locked_at` to the current UTC clock, derives `expires_at` as `locked_at + lock_term_days`, sets `extension_count` to 0 and `extension_fee_cents` to 0, and starts the lock in `ACTIVE`. If a prior `ACTIVE` rate lock exists on the same application, it is automatically transitioned to `SUPERSEDED` as a side effect, both the superseded lock's `version` and the loan application's `version` are bumped, and the new lock takes its place.

A `LoanOfficer` may extend an `ACTIVE` lock — a self-loop transition where the lock's `status` remains `ACTIVE`. The extension request supplies `extend_days`, which must be 7, 15, or 30. Several validations gate the extension and fire in a fixed order:

1. The lock must still be live: the system clock must be strictly less than the lock's `expires_at`. An extension request against a lock whose clock has reached or passed `expires_at` is rejected with `ERR_LOCK_EXPIRED`, and this temporal rejection is evaluated **before** the extension-count cap.
2. The lock must not have already reached the hard cap of two extensions: incrementing `extension_count` by one must still leave it at most two. A third extension attempt is rejected with `ERR_EXTENSION_CAP_EXCEEDED`.
3. The total live window of the lock must remain within 90 calendar days of `locked_at`: the proposed new expiry — the current `expires_at` plus `extend_days` — must not exceed `locked_at + 90 calendar days`. Exactly 90 days is allowed; 91 days is rejected with `ERR_LOCK_DURATION_CAP_EXCEEDED`.
4. The `extend_days` value itself must be one of 7, 15, or 30; any other value is rejected with `ERR_INVALID_EXTEND_DAYS`.

On a successful extension, the lock's `expires_at` is advanced by exactly `extend_days` calendar days, `extension_count` is incremented by one, and the cumulative `extension_fee_cents` is recomputed as follows. There is a per-tier fee schedule expressed in basis points of the requested loan amount: 5 basis points for a 7-day extension, 10 basis points for a 15-day extension, and 25 basis points for a 30-day extension. For the current extension, the unrounded per-extension fee in cents is the requested loan amount multiplied by the tier's basis-point factor and divided by ten thousand; this per-extension figure is rounded half-up to whole cents **before** anything is added. The lock's `extension_fee_cents` is then the sum of those per-extension rounded fees across every extension applied so far. The ordering is load-bearing: rounding each per-extension fee to whole cents and then summing the rounded values is required, and produces a different total than summing the unrounded fractional-cent values and rounding once at the end. The lock's `version` is incremented by one.

A rate lock is also terminated by non-extension events. An `ACTIVE` lock past its `expires_at` is treated as `EXPIRED` for every downstream precondition check; an implementation that does this lazily on read is acceptable, as long as no downstream caller ever sees an `ACTIVE` lock past expiry behave like a live lock. An `ACTIVE` lock is transitioned to `CANCELLED` whenever the parent loan application transitions to `WITHDRAWN` or to `DENIED` (including the auto-denial cascade from the appraisal-LTV path). Finally, an `ACTIVE` lock is transitioned to `SUPERSEDED` either when a new rate lock is successfully created on the same application or when the loan application transitions from `CLEAR_TO_CLOSE` to `CLOSED`; each terminal transition increments the lock's `version` by one.

### 3.7. Disclosures, APR Snapshots, and the TRID Timeline

The federally mandated disclosures are modeled as **Disclosure** records on the loan application. Each is born in `DRAFT` with the `LoanOfficer` supplying the `application_id`, the `disclosure_type` (one of `LOAN_ESTIMATE` or `CLOSING_DISCLOSURE`), and `expected_application_version` matching the application's current `version` (OCC; see §2.5). A `LoanOfficer` then delivers a `DRAFT` disclosure, transitioning it to `DELIVERED`. Delivery is allowed when the parent application is in `PREQUALIFIED`, `UNDER_REVIEW`, or `APPROVED`; a `CLOSING_DISCLOSURE` may only be delivered when the parent is in `UNDER_REVIEW` or `APPROVED` and the application already has at least one `DELIVERED` or `ACKNOWLEDGED` `LOAN_ESTIMATE` on file. Delivery has several side effects: `delivered_at` is stamped to the current UTC clock; the disclosure's `apr_at_issuance` is set to the loan application's `provisional_apr` for a `LOAN_ESTIMATE` and to its `final_apr` for a `CLOSING_DISCLOSURE`; the application's `earliest_consummation_at` is recomputed and a snapshot of it is stored on this disclosure as `earliest_consummation_at`; for a `CLOSING_DISCLOSURE` the re-disclosure check (described below) is evaluated and `change_requires_redisclose` is set accordingly; any prior `DELIVERED` or `ACKNOWLEDGED` disclosure of the **same** `disclosure_type` for this application is automatically transitioned to `SUPERSEDED` with its `version` bumped; both the disclosure's `version` and the loan application's `version` are incremented by one.

The `Applicant` acknowledges a `DELIVERED` disclosure — this is the one operation the borrower-as-user performs directly through the API. Acknowledgement is allowed only while the parent loan application is non-terminal. The disclosure's `acknowledged_at` is stamped to the current UTC clock, its `status` moves from `DELIVERED` to `ACKNOWLEDGED`, and its `version` is incremented by one.

**APR computation.** APR is snapshotted onto each disclosure at delivery time, using the loan application's `provisional_apr` (computed for a `LOAN_ESTIMATE`) or `final_apr` (computed for a `CLOSING_DISCLOSURE`). The two variants share the same core computation but differ in their treatment of the prepaid finance charge. The provisional APR treats the prepaid finance charge as zero — the loan estimate excludes any lock-extension fees that may have accumulated. The final APR uses the application's current `ACTIVE` rate lock's cumulative `extension_fee_cents` as the prepaid finance charge — so whenever extensions exist, the final APR will be strictly greater than the provisional. The computation proceeds as follows: the effective principal in cents is the requested loan amount in cents minus the prepaid finance charge in cents; the monthly rate as a decimal is the lock's `locked_rate_bps` divided by ten thousand and then by twelve; the number of payments `n` is the loan's `loan_term_months`; the monthly payment in cents is the requested loan amount in cents multiplied by the monthly rate, divided by one minus the quantity (one plus the monthly rate) to the power of negative `n`, rounded half-up to whole cents. The APR as a decimal is then the value of `apr_decimal` that solves the present-value identity in which the effective principal in cents equals the sum from k equals 1 through n of the monthly payment in cents divided by (one plus `apr_decimal` over twelve) raised to the power of k. The solver is Newton-Raphson seeded at `apr_decimal` equal to `locked_rate_bps` divided by ten thousand, iterated until the absolute value of the step is strictly less than one times ten to the negative eighth or until 50 iterations have elapsed, whichever comes first; the converged decimal is then rounded half-up to four decimal places and converted to a percentage (multiplied by 100) and rounded half-up to three decimal places for storage as `provisional_apr` or `final_apr` on the loan application and as `apr_at_issuance` on the disclosure.

**TRID timeline.** Each delivery (and the move to `CLEAR_TO_CLOSE`) recomputes the loan application's `earliest_consummation_at`. The system looks up the earliest `DELIVERED` `LOAN_ESTIMATE` for the application (ordered by `delivered_at` ascending, with `created_at` ascending as the tie-break, and id never used as a tie-break) and the latest `DELIVERED` `CLOSING_DISCLOSURE` for the application (ordered by `delivered_at` descending, with `created_at` descending as the tie-break). If either does not exist, `earliest_consummation_at` is `null`. Otherwise the system takes a 7-calendar-day floor — the loan estimate's `delivered_at` plus exactly seven times 86400 seconds — and a 3-calendar-day floor — the closing disclosure's `delivered_at` plus exactly three times 86400 seconds — and stores the maximum of the two as `earliest_consummation_at`. Acknowledgement timestamps are not inputs to this timeline; only `DELIVERED` disclosures count (drafts and superseded rows do not).

**Re-disclosure check on closing disclosures.** Each time a `CLOSING_DISCLOSURE` is delivered, the system compares its `apr_at_issuance` to that of the immediately prior `DELIVERED` or `SUPERSEDED` `CLOSING_DISCLOSURE` for the same application (ordered by `delivered_at` descending, with `created_at` descending as the tie-break, and id never used as a tie-break). If there is no prior CD, this is the first one and `change_requires_redisclose` is `false`. Otherwise the absolute difference of the two APR percentages is multiplied by 100 to convert percent to basis points, and `change_requires_redisclose` is set to true when that basis-point delta is strictly greater than 12.5. The boundary is sharp: a delta of exactly 12.5 basis points is **not** a re-disclosure trigger. When `change_requires_redisclose` lands as true, the disclosure is still delivered, but the loan application's subsequent move to `CLEAR_TO_CLOSE` is gated: it will be rejected with `ERR_CD_REDISCLOSE_REQUIRED` until a fresh `ACKNOWLEDGED` `CLOSING_DISCLOSURE` exists for the application whose `change_requires_redisclose` is false.

### 3.8. UDAAP Compliance Review

A `ComplianceOfficer` records UDAAP review outcomes by creating a **UDAAPCheck** for a loan application. The record carries the `application_id` of the application under review, a `review_outcome` of either `CLEARED` or `FLAGGED`, and — when the outcome is `FLAGGED` — a non-empty `flagged_reasons` array whose elements are drawn from the fixed set `HIDDEN_FEES`, `MISLEADING_RATE`, `STEERING`, and `PRESSURE_TACTICS`. The two halves of this rule are symmetric: `flagged_reasons` must be present and non-empty when the outcome is `FLAGGED`, and must be omitted or empty when the outcome is `CLEARED`; either deviation is rejected with `ERR_UDAAP_REASONS_INVALID`. On creation, the server captures the acting `ComplianceOfficer`'s `X-User-ID` and stores it as `reviewer_user_id` on the check.

`UDAAPCheck` records are append-only audit entries, so unlike the other top-level resources they carry only `id` and `created_at` — no `updated_at`, no `version` (see §2.4).

A UDAAP check governs approval via a "last-entry-wins" rule. When a `LoanOfficer` submits a loan application for review and an `Underwriter` later approves it, the system inspects the most recent UDAAPCheck for the application (ordered by `created_at` ascending, last entry wins). Approval requires that most-recent UDAAPCheck's `review_outcome` to be `CLEARED`; a `FLAGGED` most-recent UDAAPCheck blocks approval with `ERR_UDAAP_BLOCKED`. An earlier `CLEARED` check does not unblock approval if a later `FLAGGED` check has been recorded.

### 3.9. Submission, Approval, Denial, and Withdrawal

After pre-qualification, the `LoanOfficer` submits the application for full review. Submission is allowed when the application is in `PREQUALIFIED`, when the application already has at least one `DELIVERED` `LOAN_ESTIMATE` disclosure, and when the application has at least one `ACTIVE` rate lock. Submission transitions the application from `PREQUALIFIED` to `UNDER_REVIEW` and increments its `version` by one.

Approval is the underwriter's gateway from `UNDER_REVIEW` to `APPROVED` and aggregates the most demanding set of preconditions in the workflow. The application must currently be in `UNDER_REVIEW`. It must have at least one `IncomeVerification` in `ACCEPTED`. It must have at least one `AssetVerification` in `ACCEPTED`. It must have exactly one `Appraisal` whose status is either `COMPLETED` or `RECONSIDERED`. It must have at least one `TitleSearch` whose status is either `CLEAR` or `CURED`. The most recent `UDAAPCheck` on the application (per §3.8) must have `review_outcome` equal to `CLEARED` (failure here yields `ERR_UDAAP_BLOCKED`). And, critically, the **segregation-of-duties rule** applies: the underwriter approving the application must not be the same person who originated it. The system recorded the originating `LoanOfficer`'s `X-User-ID` against the application at creation time; an approval attempt whose `X-User-ID` matches that recorded value is rejected with `ERR_SOD_VIOLATION` (HTTP 403). A successful approval increments the loan application's `version` by one.

A `LoanOfficer` may withdraw an application from `DRAFT`, `PREQUALIFIED`, or `UNDER_REVIEW`; the application transitions to the terminal `WITHDRAWN` state, any `ACTIVE` rate lock on the application is auto-transitioned to `CANCELLED` as a side effect, and the application's `version` is incremented by one. An `Underwriter` may deny an application from `UNDER_REVIEW` by supplying a free-text `reason`; the application transitions to the terminal `DENIED` state, any `ACTIVE` rate lock is similarly auto-transitioned to `CANCELLED`, and the application's `version` is incremented by one.

### 3.10. Clear-to-Close and Closing

Once `APPROVED`, the application progresses to `CLEAR_TO_CLOSE` through an underwriter action. Three things must hold at the moment of that transition: the application is in `APPROVED`; the application has at least one `ACKNOWLEDGED` `CLOSING_DISCLOSURE`; and the application has an `ACTIVE` rate lock whose `expires_at` is at or beyond the current system clock. As described in §3.7, this transition is also gated by the closing-disclosure re-disclosure check: when the latest closing disclosure has `change_requires_redisclose` true, the transition is blocked with `ERR_CD_REDISCLOSE_REQUIRED` until a fresh acknowledged closing disclosure with `change_requires_redisclose` false exists. The successful transition stamps `clear_to_close_at` to the current UTC clock, recomputes `earliest_consummation_at` per the TRID timeline rules, and increments the loan application's `version` by one.

Closing is the closer's terminal action. A `Closer` advances the application from `CLEAR_TO_CLOSE` to `CLOSED` when the application is in `CLEAR_TO_CLOSE`, when the system clock has reached or passed the application's `earliest_consummation_at` (the TRID waiting period has elapsed — premature attempts are rejected with `ERR_TRID_WAITING_PERIOD`), and when the application still has an `ACTIVE` rate lock whose `expires_at` is at or beyond the current system clock. The successful transition auto-transitions the `ACTIVE` rate lock to `SUPERSEDED` as a side effect (its `version` is bumped), and increments the loan application's `version` by one. The loan file is then in its terminal closed state, and its state machine is complete.

## 4. Endpoint Definitions

Operations that create a new, addressable resource — a new applicant, a new loan application, a new verification, a new appraisal, a new title search, a new rate lock, a new disclosure, or a new UDAAP check — return `201 Created`. Operations that modify an existing resource, including all state transitions on existing resources, return `200 OK`. List and read endpoints likewise return `200 OK`. Where an endpoint description below points back to a section of §3, that section carries the request body, the side effects, and the failure modes.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/applicants`                                       | Create a new applicant                                                          | LoanOfficer |
| GET    | `/applicants/{id}`                                  | Read an applicant                                                               | LoanOfficer, Underwriter, ComplianceOfficer |
| GET    | `/applicants`                                       | List applicants with pagination                                                 | LoanOfficer, Underwriter, ComplianceOfficer |
| POST   | `/loan-applications`                                | Create a new loan application in DRAFT                                          | LoanOfficer |
| GET    | `/loan-applications/{id}`                           | Read a loan application                                                         | LoanOfficer, Underwriter, Closer, ComplianceOfficer |
| GET    | `/loan-applications`                                | List loan applications                                                          | LoanOfficer, Underwriter, Closer, ComplianceOfficer |
| POST   | `/loan-applications/{id}/prequalify`                | Run pre-qualification; auto-branches to PREQUALIFIED or DENIED                  | LoanOfficer |
| POST   | `/loan-applications/{id}/submit-for-review`         | Move application from PREQUALIFIED to UNDER_REVIEW                              | LoanOfficer |
| POST   | `/loan-applications/{id}/approve`                   | Move application from UNDER_REVIEW to APPROVED                                  | Underwriter |
| POST   | `/loan-applications/{id}/deny`                      | Move application from UNDER_REVIEW to DENIED                                    | Underwriter |
| POST   | `/loan-applications/{id}/clear-to-close`            | Move application from APPROVED to CLEAR_TO_CLOSE; set earliest_consummation_at  | Underwriter |
| POST   | `/loan-applications/{id}/close`                     | Move application from CLEAR_TO_CLOSE to CLOSED; supersedes active rate lock     | Closer |
| POST   | `/loan-applications/{id}/withdraw`                  | Withdraw the application from DRAFT, PREQUALIFIED, or UNDER_REVIEW              | LoanOfficer |
| POST   | `/income-verifications`                             | Create an income verification in PENDING                                        | LoanOfficer |
| GET    | `/income-verifications/{id}`                        | Read an income verification                                                     | LoanOfficer, Underwriter |
| GET    | `/income-verifications`                             | List income verifications                                                       | LoanOfficer, Underwriter |
| POST   | `/income-verifications/{id}/accept`                 | Mark income verification ACCEPTED                                               | Underwriter |
| POST   | `/income-verifications/{id}/reject`                 | Mark income verification REJECTED with reason                                   | Underwriter |
| POST   | `/asset-verifications`                              | Create an asset verification in PENDING                                         | LoanOfficer |
| GET    | `/asset-verifications/{id}`                         | Read an asset verification                                                      | LoanOfficer, Underwriter |
| GET    | `/asset-verifications`                              | List asset verifications                                                        | LoanOfficer, Underwriter |
| POST   | `/asset-verifications/{id}/accept`                  | Mark asset verification ACCEPTED                                                | Underwriter |
| POST   | `/asset-verifications/{id}/reject`                  | Mark asset verification REJECTED with reason                                    | Underwriter |
| POST   | `/appraisals`                                       | Order an appraisal for an application                                           | LoanOfficer |
| GET    | `/appraisals/{id}`                                  | Read an appraisal                                                               | LoanOfficer, Underwriter, Appraiser |
| GET    | `/appraisals`                                       | List appraisals                                                                 | LoanOfficer, Underwriter, Appraiser |
| POST   | `/appraisals/{id}/complete`                         | Appraiser reports completion with a value                                       | Appraiser |
| POST   | `/appraisals/{id}/reconsider`                       | LoanOfficer requests reconsideration of value                                   | LoanOfficer |
| POST   | `/appraisals/{id}/confirm-reconsideration`          | Appraiser confirms the reconsidered value                                       | Appraiser |
| POST   | `/title-searches`                                   | Order a title search for an application                                         | LoanOfficer |
| GET    | `/title-searches/{id}`                              | Read a title search                                                             | LoanOfficer, Underwriter, TitleAgent |
| GET    | `/title-searches`                                   | List title searches                                                             | LoanOfficer, Underwriter, TitleAgent |
| POST   | `/title-searches/{id}/mark-clear`                   | Mark the title search CLEAR                                                     | TitleAgent |
| POST   | `/title-searches/{id}/raise-exception`              | Report a title exception                                                        | TitleAgent |
| POST   | `/title-searches/{id}/cure`                         | Report the exception cured                                                      | TitleAgent |
| POST   | `/rate-locks`                                       | Create a new rate lock; OCC on application.version; supersedes prior active lock| LoanOfficer |
| GET    | `/rate-locks/{id}`                                  | Read a rate lock                                                                | LoanOfficer, Underwriter, Closer |
| GET    | `/rate-locks`                                       | List rate locks                                                                 | LoanOfficer, Underwriter, Closer |
| POST   | `/rate-locks/{id}/extend`                           | Extend the lock by extend_days                                                  | LoanOfficer |
| POST   | `/disclosures`                                      | Create a new disclosure in DRAFT; OCC on application.version                    | LoanOfficer |
| GET    | `/disclosures/{id}`                                 | Read a disclosure                                                               | LoanOfficer, Underwriter, Closer, Applicant |
| GET    | `/disclosures`                                      | List disclosures                                                                | LoanOfficer, Underwriter, Closer, Applicant |
| POST   | `/disclosures/{id}/deliver`                         | Deliver a DRAFT disclosure; recomputes APR, TRID timeline, redisclose flag      | LoanOfficer |
| POST   | `/disclosures/{id}/acknowledge`                     | Applicant acknowledges receipt of a delivered disclosure                        | Applicant |
| POST   | `/udaap-checks`                                     | Record a UDAAP compliance review outcome for an application                     | ComplianceOfficer |
| GET    | `/udaap-checks/{id}`                                | Read a UDAAP check                                                              | LoanOfficer, Underwriter, ComplianceOfficer |
| GET    | `/udaap-checks`                                     | List UDAAP checks                                                               | LoanOfficer, Underwriter, ComplianceOfficer |
| POST   | `/_clock/set_current_utc`                           | Test-only: advance the system clock to a fixed UTC timestamp                    | LoanOfficer, Underwriter, Closer, ComplianceOfficer, Appraiser, TitleAgent, Applicant |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code   |
| --------------------------------- | ------------------ |
| `ERR_UNAUTHENTICATED`             | 401 Unauthorized   |
| `ERR_UNAUTHORIZED`                | 403 Forbidden      |
| `ERR_APPLICATION_NOT_FOUND`       | 404 Not Found      |
| `ERR_APPLICANT_NOT_FOUND`         | 404 Not Found      |
| `ERR_SUBRESOURCE_NOT_FOUND`       | 404 Not Found      |
| `ERR_INVALID_STATE`               | 409 Conflict       |
| `ERR_STALE_VERSION`               | 412 Precondition Failed |
| `ERR_UDAAP_BLOCKED`               | 422 Unprocessable Entity |
| `ERR_TRID_WAITING_PERIOD`         | 422 Unprocessable Entity |
| `ERR_DTI_FRONTEND_TOO_HIGH`       | 422 Unprocessable Entity |
| `ERR_EXTENSION_CAP_EXCEEDED`      | 422 Unprocessable Entity |
| `ERR_INVALID_EXTEND_DAYS`         | 422 Unprocessable Entity |
| `ERR_LOCK_EXPIRED`                | 422 Unprocessable Entity |
| `ERR_LOCK_DURATION_CAP_EXCEEDED`  | 422 Unprocessable Entity |
| `ERR_UDAAP_REASONS_INVALID`       | 422 Unprocessable Entity |
| `ERR_CD_REDISCLOSE_REQUIRED`      | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION`               | 403 Forbidden      |
| `ERR_INVALID_REQUEST`             | 400 Bad Request    |
