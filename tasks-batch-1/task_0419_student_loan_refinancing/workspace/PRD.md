# Student Loan Refi API — Product Requirements Document

## 1. Introduction

This document specifies the backend service that powers a digital student-loan refinancing product in the spirit of consumer lenders such as SoFi and Earnest. A borrower arrives carrying outstanding education debt held by one or more prior servicers, and wants a single new loan at a better rate. The platform must take that borrower from a self-reported application all the way through a soft-credit prequalification, a grid of rate-and-term offers, an offer lock with autopay and member-benefit discounts baked in, an underwriting decision, the funding of a new loan, the payoff of the prior servicers, and finally the long tail of servicing — payments, interest accrual, hardship forbearance, delinquency, charge-off, and the eventual release of any cosigner.

The product is deliberately a multi-party affair. A refinance often hinges on a cosigner, and both the borrower and the cosigner must affirmatively act before a loan can be locked and funded. Underwriting is regulated, so the platform enforces a strict segregation of duties: the person who approves an application can never be the person who funds it and remits money to the prior servicers. Every funded loan must be tagged into an asset-backed securitization (ABS) pool whose eligibility rules constrain which loans it may hold, and the act of funding is audited end to end. Because the system models interest accrual, offer expiry, and on-time-payment determination against wall-clock time, the service exposes a test-driving clock so that time-dependent behavior is deterministic.

The sections that follow define the global contract every endpoint obeys (Section 2), the business logic and lifecycle of each entity and workflow (Section 3), the endpoint catalogue (Section 4), and the canonical error codes (Section 5). Section 3 is where the substance lives: the rules that govern pricing, accrual, the payment waterfall, cosigner release, and pool selection are described in the narrative of the workflow they belong to rather than collected into schema tables.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the request is made. If either header is missing, or if `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). A narrow set of bootstrap operations — registering a borrower, creating an ABS pool, and creating a rate-grid entry — are exempted from the authentication requirement during bootstrapping, though role authorization still governs who may call them in practice.

There are exactly six roles, spelled precisely as follows: `Borrower`, `Cosigner`, `Underwriter`, `DisbursementOfficer`, `ServicingAgent`, and `PlatformAdmin`.

A `Borrower` is the refinance applicant. It is an entity-backed role: when `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower`, and ownership checks on any resource that references a `Borrower` compare the resource's borrower foreign key to `X-User-ID`. A `Cosigner` is likewise entity-backed: when `X-User-Role` is `Cosigner`, `X-User-ID` is the `id` of the acting `Cosigner`, and ownership checks on a resource that references a `Cosigner` compare the resource's cosigner foreign key to `X-User-ID`. The `Borrower` creates applications, runs prequalification, locks offers, invites and releases cosigners, withdraws applications, and posts payments on its own loans. The `Cosigner` consents to or declines a cosigning invitation.

The remaining four roles are opaque operator identities not tied to any persisted entity. When `X-User-Role` is `Underwriter`, `X-User-ID` is an opaque operator identifier; the server records it (for example, as `approved_underwriter_id` on the `Application` when an `Underwriter` approves) but does not compare it to any entity's `id`. When `X-User-Role` is `DisbursementOfficer`, `X-User-ID` is an opaque operator identifier; the server records it on audit events and compares it against the stored `approved_underwriter_id` for the segregation-of-duties rule, but does not resolve it to a persisted entity. When `X-User-Role` is `ServicingAgent`, `X-User-ID` is an opaque operator identifier the server may record on audit events without comparing it to any entity's `id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier used to bootstrap pools and the rate grid, run offer-expiry sweeps, drive the test clock, and read audit, again without resolution to any entity.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` defaults to 0 and must be at least 0. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400). Results are always sorted by `created_at` in ascending order. Every list response surfaces `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` is the number of matching records before paging and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Common Resource Properties and Identifiers

Every resource is assigned a server-minted `id`, which is an opaque UUID carrying no type prefix. Most resources also carry three managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 on creation and increments by 1 on every mutation of that resource. The entities that carry the full set of common fields are `Borrower`, `AbsPool`, `Application`, `Offer`, `Cosigner`, `Loan`, `Disbursement`, `Payment`, and `ForbearancePlan`.

Two entities are deliberately lighter. A `RateGridEntry` and an `AuditEvent` are append-style records that carry only `id` and `created_at`; they have no `updated_at` and no `version`, because they are never mutated after creation. Implementations must not expose `updated_at` or `version` for those two entity types.

### 2.5. Foreign-Key Reachability and Resource Existence

References are validated left to right. When a request names a resource through a path identifier or through a foreign-key field in the body, each referenced resource must resolve to an existing record, checked in order of appearance; the first reference that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404). List endpoints expose reverse reachability along foreign keys through optional filter parameters: offers can be listed by `application_id`, cosigners by `application_id`, loans by `application_id` and by `abs_pool_id`, payments and forbearance plans and disbursements by their `loan_id`, applications by `borrower_id`, and audit events by `subject_type` and `subject_id`. These filters, along with status filters such as `status`, `repayment_status`, `rate_type`, `term_months`, and `min_fico_band`, narrow the result set but never change the sort order or the envelope.

### 2.6. State Validation and Transition Ordering

Each operation that drives a state machine is defined only from specific source states. If the target resource is not in a state from which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Validation is applied in a fixed priority order so that the error a caller receives is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource (`ERR_NOT_FOUND`), then that the target is in a legal source state for the transition (`ERR_INVALID_STATE`), then optimistic-concurrency staleness on offer lock (`ERR_STALE_APPLICATION_VERSION`), and only then the business rules specific to each operation. Where several business rules guard the same operation, their relative ordering is called out in the workflow narrative in Section 3. Malformed bodies — a missing required field, a wrong type, an invalid enum value, or a non-positive amount where a positive one is required — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Monetary Precision, Basis Points, and Rounding

All money is expressed in integer cents; no field stores a fractional cent. All annual percentage rates are expressed in integer basis points, where 100 basis points equal one percent. Wherever a computation produces a fractional cent — interest accrual and the estimated monthly payment used for the debt-to-income calculation — the result is rounded half up to the nearest whole cent. The debt-to-income ratio (`dti_ratio`) is the one non-integer quantity the system stores; it is rounded half up to exactly four decimal places. Pricing computations that operate purely in basis points (the estimated and locked APR) are integer arithmetic and require no rounding, though the locked APR applies a floor clamp as its final step, described in Section 3.

### 2.8. Optimistic Concurrency on Offer Lock

Locking an offer is the one operation guarded by optimistic concurrency control. The request to lock an offer must include `expected_application_version`, carrying the client's last observed `version` of the parent `Application`; this field is required, not optional. The server compares it to the `Application`'s current `version`. If the two do not match — for instance, because another writer has already locked a sibling offer on the same application, which legitimately supersedes the remaining presented offers and advances the application into `UNDER_REVIEW`, thereby advancing the application's `version` beyond what this client last read — the lock is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412). The rejection prevents the client from locking against a view of the application it has not observed. No other endpoint accepts or requires a version field.

### 2.9. The Test-Driving Clock

The service maintains a single logical UTC clock that governs every time comparison: offer expiry, the on-time determination on a payment, and the day count used for daily interest accrual. An administrative test-driving capability sets this clock to a supplied instant carried in the `to_iso8601` field, after which all subsequent comparisons use the new value. Unless the clock has been set, the system uses real UTC time. This clock is the authority for "now" throughout Section 3.

## 3. Business Logic & Workflows

### 3.1. Bootstrapping the Catalogue: Borrowers, Pools, and the Rate Grid

Before any application can be priced, the platform must be seeded. A borrower is registered with an `email`, a `full_name`, a self-reported `annual_income_cents`, and a self-reported `fico_band`. The `email` must be non-empty and unique across borrowers; a duplicate is rejected with `ERR_DUPLICATE_KEY`. Income in cents must be at least 0. The `fico_band` is one of `SUBPRIME`, `NEAR_PRIME`, `PRIME`, or `SUPER_PRIME`. Every new borrower starts at `member_tier` `NONE`; the loyalty tier, which governs member-benefit perks, is system-managed and one of `NONE`, `SILVER`, `GOLD`, or `PLATINUM`, and it is only ever upgraded by the funding workflow described later.

A `PlatformAdmin` seeds securitization pools. An ABS pool is created with a `pool_code` (non-empty and unique; a collision is rejected with `ERR_DUPLICATE_KEY`), a `max_principal_cents` aggregate capacity that must be greater than 0, a `min_fico_band` naming the lowest borrower band eligible for inclusion (one of the four credit bands), and an `allowed_rate_type` constraining which products the pool may hold — `FIXED`, `VARIABLE`, or `ANY`. On creation, a pool's `committed_principal_cents` — the running sum of the original principal of every loan tagged into it — is initialized to 0, and its `status` is `OPEN`. A pool may be closed to new loans, which sets its `status` to `CLOSED`; only `OPEN` pools are candidates at funding time.

The pricing catalogue is a rate-and-term grid. Each `RateGridEntry` names a `rate_type` (`FIXED` or `VARIABLE`), a `term_months` (one of 60, 84, 120, 180, or 240), the `min_fico_band` this row prices (the lowest of the four bands the row covers), a `base_apr_bps` that must be greater than 0, and an `index_apr_bps`. The index is the current floating component added on top for variable products and must be at least 0; for fixed rows it is 0 and may be omitted on creation, defaulting to 0.

### 3.2. Application Intake and the Prequalification Pull

A `Borrower` opens a refinance by creating an application against its own borrower record, supplying the `borrower_id`, the `requested_principal_cents` it wants to refinance (which must be greater than 0), a `requested_term_months` (one of 60, 84, 120, 180, or 240), and a `requested_rate_type` (`FIXED` or `VARIABLE`). The application begins in status `DRAFT`. Its lifecycle states are `DRAFT`, `PREQUALIFIED`, `UNDER_REVIEW`, `APPROVED`, `DECLINED`, `EXPIRED`, and `WITHDRAWN`, of which `DECLINED`, `EXPIRED`, and `WITHDRAWN` are terminal. At intake, `soft_pull_fico_band`, `dti_ratio`, and `approved_underwriter_id` are all unset.

Prequalification moves the application from `DRAFT` to `PREQUALIFIED` and is the heart of intake. It is defined only from `DRAFT`; a request from any other state is rejected with `ERR_INVALID_STATE`. Three computations run in sequence. First, the soft-credit pull replaces the self-reported band with a hard-data correction stored in `soft_pull_fico_band`. The pull is deterministic, not random: order the bands as `SUBPRIME`, `NEAR_PRIME`, `PRIME`, `SUPER_PRIME` at positions zero through three, find the borrower's self-reported band's position, and move one notch toward the center. A borrower at position zero or one is moved up one position (so `SUBPRIME` becomes `NEAR_PRIME` and `NEAR_PRIME` becomes `PRIME`); a borrower at position two or three is moved down one position (so `PRIME` becomes `NEAR_PRIME` and `SUPER_PRIME` becomes `PRIME`).

Second, the debt-to-income ratio is computed and stored in `dti_ratio`; at prequalification no cosigner income is included, which is the borrower-only variant. The estimated monthly payment is the requested principal multiplied by a flat amortization factor keyed on the requested term, rounded half up to whole cents. The amortization factor is 0.0188 for a 60-month term, 0.0142 for 84 months, 0.0110 for 120 months, 0.0080 for 180 months, and 0.0065 for 240 months. The annualized debt service is that estimated monthly payment multiplied by 12. The combined income at prequalification is just the borrower's `annual_income_cents`. The ratio is the annual debt service divided by the combined income, rounded half up to four decimal places.

Third, the offer grid is generated. The system finds every `RateGridEntry` whose `rate_type` equals the application's `requested_rate_type`, whose `term_months` equals the `requested_term_months`, and whose `min_fico_band` is no stricter than the application's `soft_pull_fico_band` (that is, the row's band is at or below the borrower's post-pull band in the four-band ordering). If no row matches, prequalification is rejected with `ERR_NO_MATCHING_RATE` (HTTP 422) and no offers are created. Otherwise one `Offer` is created per matching row. Each offer copies its `term_months` and `rate_type` from the grid row, records which cell it came from in `rate_grid_entry_index`, links back through `application_id`, starts in status `PRESENTED`, and is stamped with an `expires_at` of the current clock instant plus the offer time-to-live of 48 hours. Each offer's `estimated_apr_bps` is computed as the prequal estimate: the grid cell's `base_apr_bps`, plus the cell's `index_apr_bps` if the offer's rate type is `VARIABLE` (otherwise zero), plus a band surcharge keyed on the application's `soft_pull_fico_band`. The band surcharge is 300 basis points for `SUBPRIME`, 150 for `NEAR_PRIME`, 50 for `PRIME`, and 0 for `SUPER_PRIME`. No autopay or member discount is applied at this stage. Prequalification finishes by recording an audit event for the application.

### 3.3. Bringing a Cosigner Aboard

A refinance may carry at most one cosigner. A `Borrower` invites a cosigner against an application by supplying the `application_id`, the `cosigner_email` under which the cosigner will act (non-empty), and the `cosigner_annual_income_cents` (at least 0). The cosigner begins in `consent_status` `INVITED`; its lifecycle states are `INVITED`, `CONSENTED`, `DECLINED`, and `RELEASED`, of which `DECLINED` and `RELEASED` are terminal. Its `on_time_streak` — the count of consecutive on-time payments on the eventual funded loan — starts at 0. Inviting a second cosigner to an application that already has one is rejected with `ERR_COSIGNER_ALREADY_ATTACHED` (HTTP 409).

A `Cosigner` consents by moving from `INVITED` to `CONSENTED`. Consent is defined only from `INVITED`, and only while the parent application is still in `DRAFT` or `PREQUALIFIED`; outside those parent states or from a non-`INVITED` consent status the transition is rejected with `ERR_INVALID_STATE`. Consent recomputes the parent application's `dti_ratio` using the with-cosigner variant: the combined income becomes the borrower's `annual_income_cents` plus the consenting cosigner's `cosigner_annual_income_cents`, and the rest of the debt-to-income computation is identical — estimated monthly payment from principal and amortization factor, times 12, divided by the now-larger combined income, rounded half up to four decimal places. Because the denominator grows, the ratio falls, which can flip an otherwise-failing application to within limit at the boundary. Consent records a cosigner audit event. A `Cosigner` may instead decline from `INVITED` to `DECLINED`, which is also defined only from `INVITED` and records a cosigner audit event but changes no income.

### 3.4. Locking an Offer

When the borrower is satisfied with a presented offer, it locks that offer, which both finalizes the rate and advances the application from `PREQUALIFIED` to `UNDER_REVIEW`. The lock is defined only when the application is in `PREQUALIFIED`; otherwise `ERR_INVALID_STATE` applies. Several guards then run. The lock request must carry `expected_application_version` matching the parent application's current `version`; a mismatch is the stale-version rejection `ERR_STALE_APPLICATION_VERSION` (HTTP 412) described in Section 2.8. The target offer must itself be in status `PRESENTED`, and it must not be expired — its `expires_at` must be strictly greater than the current clock; a lock attempted at or after expiry is rejected with `ERR_OFFER_EXPIRED` (HTTP 409). If a cosigner is attached to the application, that cosigner's `consent_status` must be `CONSENTED`; a lock attempted while the attached cosigner is `INVITED`, `DECLINED`, or otherwise not consented is rejected with `ERR_COSIGNER_NOT_CONSENTED` (HTTP 409).

The borrower may set `autopay_elected` on the lock request; it defaults to false. Electing autopay affects the discount applied to the final rate. On a successful lock, the offer's final `locked_apr_bps` is computed from the offer's `estimated_apr_bps` in a pinned order: first subtract the autopay discount of 25 basis points if and only if `autopay_elected` is true, then from that running value subtract the member-tier discount keyed on the borrower's `member_tier` — 0 basis points for `NONE`, 10 for `SILVER`, 25 for `GOLD`, and 50 for `PLATINUM`. The result is finally clamped so it never falls below the APR floor of 200 basis points; the floor is applied last, after both discounts. Skipping autopay leaves the locked APR higher by the 25-basis-point autopay discount unless the floor clamp absorbs the difference.

Locking has three further side effects. The offer's `status` becomes `LOCKED`. Every sibling offer on the same application still in `PRESENTED` is set to `SUPERSEDED`. The application moves to `UNDER_REVIEW` and its `version` is incremented by 1 — this is precisely the increment that makes a concurrent lock against a stale `expected_application_version` fail. The lock records an application audit event.

### 3.5. Underwriting: Approve and Decline

An `Underwriter` decides an application that is in `UNDER_REVIEW`. Approval is defined only from `UNDER_REVIEW`; from any other state `ERR_INVALID_STATE` applies. Two business guards run, in this order: first, exactly one offer on the application must be in status `LOCKED` — zero locked offers or more than one locked offer is rejected with `ERR_NO_LOCKED_OFFER` (HTTP 409); then the application's `dti_ratio` must be at most the maximum allowed ratio of 0.4300, and a ratio strictly above that limit is rejected with `ERR_DTI_EXCEEDED` (HTTP 422). On success the application moves to `APPROVED`, the acting underwriter's `X-User-ID` is stored in `approved_underwriter_id` for the later segregation-of-duties check, and an application audit event is recorded.

An `Underwriter` may instead decline an application in `UNDER_REVIEW`, which is also defined only from `UNDER_REVIEW`. Declining moves the application to the terminal `DECLINED` state, sets the `LOCKED` offer (if any) to `SUPERSEDED`, and records an application audit event.

### 3.6. Withdrawal and Offer Expiry

A `Borrower` may withdraw an application while it is in `DRAFT`, `PREQUALIFIED`, or `UNDER_REVIEW`; from any other state the withdrawal is rejected with `ERR_INVALID_STATE`. Withdrawal moves the application to the terminal `WITHDRAWN` state, expires every non-terminal offer on the application by setting it to `SUPERSEDED`, and records an application audit event.

Offers carry their own time-to-live, and a `PlatformAdmin` runs the sweep that retires a prequalified application whose offers have all aged out. The sweep is defined only when the application is in `PREQUALIFIED` and only when every offer on the application has an `expires_at` at or before the current clock. When both hold, every offer still in `PRESENTED` is set to `EXPIRED`, the application moves to the terminal `EXPIRED` state, and an application audit event is recorded. If any offer is still live, the application remains `PREQUALIFIED`.

### 3.7. Funding the Loan and Pool Selection

Funding is performed by a `DisbursementOfficer` against an `APPROVED` application and produces a new `Loan`. The funding workflow first selects the ABS pool the loan will be tagged into. The candidate set is every pool whose `status` is `OPEN`, whose `min_fico_band` is no stricter than the application's `soft_pull_fico_band` (the pool's band at or below the borrower's post-pull band in the four-band ordering), whose `allowed_rate_type` is either `ANY` or equal to the locked offer's `rate_type`, and whose `committed_principal_cents` plus the application's `requested_principal_cents` is at most the pool's `max_principal_cents`. If that candidate set is empty, funding is rejected with `ERR_NO_ELIGIBLE_POOL` (HTTP 422) and no loan is created. Otherwise the pool is chosen by best fit: the candidate with the smallest remaining capacity wins, where remaining capacity is `max_principal_cents` minus `committed_principal_cents` (tightest fit first). Ties on remaining capacity are broken by the earliest `created_at` — never by `id`.

Once the pool is chosen, a `Loan` is created. It links to its `application_id` and to the locked `offer_id`, and is tagged with the chosen pool in `abs_pool_id`. Its `original_principal_cents` is copied from the application's requested principal, and the chosen pool's `committed_principal_cents` is increased by that same original principal. The loan's `principal_balance_cents` starts equal to the original principal, its `accrued_interest_cents` starts at 0, its `locked_apr_bps` and `term_months` are copied from the locked offer, and its `last_accrual_at` — the window start for daily interest accrual — is set to the funding instant on the clock. The loan carries two independent status dimensions. The repayment dimension, `repayment_status`, begins `CURRENT` and ranges over `CURRENT`, `FORBEARANCE`, `DELINQUENT`, `PAID_OFF`, and `CHARGED_OFF`, with `PAID_OFF` and `CHARGED_OFF` terminal. The cosigner-release dimension, `cosigner_release_status`, ranges over `PENDING`, `ELIGIBLE`, `RELEASED`, and `NOT_APPLICABLE`; it begins `PENDING` when a `CONSENTED` cosigner exists on the application and `NOT_APPLICABLE` otherwise. Funding also delivers a member benefit: if the borrower's `member_tier` is currently `NONE`, it is upgraded to `SILVER` (a higher tier is left untouched). Finally a loan audit event is recorded for the funding.

### 3.8. Scheduling and Remitting Payoffs to Prior Servicers

With a loan funded, the `DisbursementOfficer` schedules the payoffs that retire the borrower's prior debt. A disbursement is created against a `loan_id`, naming the `prior_servicer_name` to be paid (non-empty) and the `payoff_amount_cents` to remit (greater than 0). It begins in status `SCHEDULED`; its lifecycle is `SCHEDULED`, `SENT`, `CONFIRMED`, and `RETURNED`, with `CONFIRMED` and `RETURNED` terminal. The sum of `payoff_amount_cents` across all disbursements scheduled against a loan must not exceed that loan's `original_principal_cents`; a scheduling request that would push the running total past the original principal is rejected with `ERR_PAYOFF_EXCEEDS_PRINCIPAL` (HTTP 422).

Sending a payoff moves a disbursement from `SCHEDULED` to `SENT`, and is the operation where segregation of duties bites. The transition is defined only from `SCHEDULED`, and only while the parent loan's `repayment_status` is `CURRENT`. Crucially, the acting `DisbursementOfficer`'s `X-User-ID` must differ from the `approved_underwriter_id` recorded on the parent application when it was approved; if the officer sending the payoff is the same principal who approved the application, the send is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful send records a disbursement audit event. From `SENT`, a payoff may be confirmed by the servicer, moving it to `CONFIRMED` with a disbursement audit event, or marked returned, moving it to `RETURNED` with a disbursement audit event; both are defined only from `SENT`.

### 3.9. Servicing: Payments, Accrual, and the Waterfall

Payments are posted by a `ServicingAgent` or by the `Borrower` against a loan. A payment supplies an `amount_cents` (greater than 0) and a `due_date`, and may optionally supply `paid_at`; when `paid_at` is omitted the system stamps it with the current clock. Posting a payment runs a fixed chain: accrue interest, run the waterfall, determine on-time status and update the streak, then evaluate release eligibility and the repayment-status transitions.

Interest accrues daily-simple from the loan's `last_accrual_at` to the payment's `paid_at`. The number of days is the count of whole UTC days between those two instants, taking the floor. The daily rate is the loan's `locked_apr_bps` divided by 10,000 (to convert basis points to a fraction) and then divided by 365 days per year. The newly accrued interest is the loan's `principal_balance_cents` at the start of the window multiplied by that daily rate multiplied by the number of days, and that single product is rounded half up to whole cents — the rounding happens once, after multiplying by the day count, not per day. The new interest is added to `accrued_interest_cents`. The loan's `last_accrual_at` advances to this payment's `paid_at`.

The payment is then allocated interest-first in a pinned order. The `interest_portion_cents` is the smaller of the payment's `amount_cents` and the refreshed `accrued_interest_cents`. The remainder is the payment amount minus that interest portion. The `principal_portion_cents` is the smaller of that remainder and the loan's `principal_balance_cents`. The interest portion is subtracted from `accrued_interest_cents` and the principal portion is subtracted from `principal_balance_cents`. Any payment amount left over after interest and the full principal are covered is simply dropped: balances never go negative and there is no escrow. Because allocation operates on integer cents already produced by the accrual rounding, no further rounding is needed.

On-time status is then determined and stored in `on_time`. A payment is on time if and only if its `paid_at` is at or before its `due_date` plus a grace window of 5 days; a payment whose `paid_at` falls exactly on the due date plus 5 days is on time, while one second past that boundary is late. When the payment is on time and the loan's `repayment_status` is `CURRENT`, and a `CONSENTED` cosigner exists, that cosigner's `on_time_streak` is incremented by 1. A late payment, or any payment posted while the loan is not `CURRENT`, resets the `on_time_streak` to 0.

The payment chain can drive two state transitions. If after the waterfall the loan was `DELINQUENT`, a posted payment cures it and the `repayment_status` returns to `CURRENT`, recording a loan audit event. If after the waterfall the loan's `principal_balance_cents` reaches 0 and `accrued_interest_cents` is also 0 while the loan was `CURRENT`, the loan transitions to the terminal `PAID_OFF` state; at payoff, if `cosigner_release_status` is still `PENDING`, it is set to `NOT_APPLICABLE`, and a loan audit event is recorded.

### 3.10. Cosigner Release Eligibility and Release

The cosigner-release dimension advances on its own track, independent of the repayment dimension, and is evaluated inside the payment-post side-effect chain. After a payment posts, if the loan's `cosigner_release_status` is `PENDING`, a `CONSENTED` cosigner exists for the loan's application, the loan's `repayment_status` is `CURRENT`, and the cosigner's `on_time_streak` has reached at least the release threshold of 3 consecutive on-time payments, the release dimension advances from `PENDING` to `ELIGIBLE` and a loan audit event marking release eligibility is recorded. This is a system transition triggered by the streak crossing the threshold, not a separate request.

Eligibility can be lost. Marking a loan delinquent (Section 3.11) resets the cosigner's `on_time_streak` to 0 and, if the release dimension was `ELIGIBLE`, reverts it to `PENDING`. Once the loan is genuinely release-eligible, the `Borrower` may release the cosigner. Release is defined only when the cosigner's `consent_status` is `CONSENTED` and only when the funded loan's `cosigner_release_status` is `ELIGIBLE`; a release attempted while the loan is not eligible is rejected with `ERR_RELEASE_NOT_ELIGIBLE` (HTTP 409). On success the cosigner moves to the terminal `RELEASED` consent status, the loan's `cosigner_release_status` is set to `RELEASED`, and a cosigner audit event is recorded.

### 3.11. Hardship Forbearance, Delinquency, and Charge-Off

A `ServicingAgent` handles distressed loans. Placing a loan into hardship forbearance is defined only when the loan's `repayment_status` is `CURRENT` and only when no `ACTIVE` forbearance plan already exists for the loan. The request supplies a `reason_code` — one of `JOB_LOSS`, `MEDICAL`, `NATURAL_DISASTER`, or `OTHER` — and a `months_requested` that must be between 1 and 12 inclusive; a value outside that range is rejected with `ERR_FORBEARANCE_TERM_INVALID` (HTTP 422). If a forbearance is requested while an `ACTIVE` plan already exists, it is rejected with `ERR_FORBEARANCE_ALREADY_ACTIVE` (HTTP 409). On success a `ForbearancePlan` is created in status `ACTIVE` with `interest_capitalized_cents` at 0, the loan's `repayment_status` moves from `CURRENT` to `FORBEARANCE`, and a loan audit event is recorded. This touches only the repayment dimension; the cosigner-release dimension is untouched.

Ending forbearance is defined only when the loan's `repayment_status` is `FORBEARANCE` and the loan has an `ACTIVE` forbearance plan. At end, all interest that accrued during the hardship is capitalized: `interest_capitalized_cents` on the plan is set to the loan's current `accrued_interest_cents`, that amount is folded into `principal_balance_cents` by adding it, the loan's `accrued_interest_cents` is reset to 0, the plan's `status` becomes `ENDED`, the loan's `repayment_status` returns to `CURRENT`, and a loan audit event is recorded.

Marking a current loan delinquent is defined only from `repayment_status` `CURRENT` and moves it to `DELINQUENT`. As a side effect it resets the cosigner's `on_time_streak` to 0 if a `CONSENTED` cosigner exists, and if `cosigner_release_status` was `ELIGIBLE` it reverts to `PENDING`; a loan audit event is recorded. A delinquent loan can be cured by a posted payment as described in Section 3.9, or charged off. Charge-off is defined only from `repayment_status` `DELINQUENT` and moves the loan to the terminal `CHARGED_OFF` state, sets `cosigner_release_status` to `NOT_APPLICABLE`, and records a loan audit event.

### 3.12. The Audit Trail

Every consequential transition appends an `AuditEvent`. Each record names its polymorphic `subject_type` — one of `APPLICATION`, `LOAN`, `COSIGNER`, or `DISBURSEMENT` — and the `subject_id` of the subject it concerns, an `action` string describing what happened (for example, the application being prequalified, an offer being locked, an application being approved, declined, withdrawn, or expired, a loan being funded, a cosigner consenting, declining, or being released, the cosigner becoming release-eligible, a loan entering or leaving forbearance, going delinquent, curing, paying off, or charging off, and a disbursement being sent, confirmed, or returned), the `actor_role` that performed it, and the `actor_user_id` carrying the `X-User-ID` of that actor. Audit events are append-only and are read back filtered by `subject_type` and `subject_id`.

## 4. Endpoint Definitions

All endpoints share the response envelope from Section 2.2 and the authorization rules from Section 2.1. Endpoints that create a brand-new resource return HTTP 201; endpoints that read or that modify an existing resource (including state-transition actions) return HTTP 200. The request body, the computed response, and the side effects of each endpoint are described in the Section 3 narratives, not in this table.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/borrowers` | Register a borrower | `Borrower`, `PlatformAdmin` |
| GET | `/borrowers/{id}` | Fetch a borrower | `Borrower`, `PlatformAdmin`, `Underwriter`, `ServicingAgent` |
| POST | `/abs-pools` | Create an ABS securitization pool | `PlatformAdmin` |
| GET | `/abs-pools/{id}` | Fetch an ABS pool with its committed principal | `PlatformAdmin`, `Underwriter`, `DisbursementOfficer` |
| POST | `/abs-pools/{id}/close` | Close a pool to new loans | `PlatformAdmin` |
| POST | `/rate-grid-entries` | Create a rate/term grid cell | `PlatformAdmin` |
| GET | `/rate-grid-entries` | List rate grid cells (filterable) | `PlatformAdmin`, `Borrower`, `Underwriter` |
| POST | `/applications` | Create a draft refinance application | `Borrower` |
| GET | `/applications/{id}` | Fetch an application | `Borrower`, `Underwriter`, `ServicingAgent`, `PlatformAdmin` |
| GET | `/applications` | List applications, filterable by borrower | `Underwriter`, `PlatformAdmin` |
| POST | `/applications/{id}/prequalify` | Run soft-credit pull, compute DTI, generate offers | `Borrower` |
| POST | `/applications/{id}/approve` | Approve the application | `Underwriter` |
| POST | `/applications/{id}/decline` | Decline the application | `Underwriter` |
| POST | `/applications/{id}/withdraw` | Withdraw the application | `Borrower` |
| POST | `/applications/{id}/expire-offers` | Sweep: expire all offers and the application | `PlatformAdmin` |
| POST | `/applications/{id}/fund` | Fund an approved application; create the loan | `DisbursementOfficer` |
| GET | `/offers/{id}` | Fetch an offer | `Borrower`, `Underwriter`, `PlatformAdmin` |
| GET | `/offers` | List offers, filterable by application | `Borrower`, `Underwriter`, `PlatformAdmin` |
| POST | `/offers/{id}/lock` | Lock an offer; supersede siblings; advance application | `Borrower` |
| POST | `/cosigners` | Invite a cosigner to an application | `Borrower` |
| GET | `/cosigners/{id}` | Fetch a cosigner | `Borrower`, `Cosigner`, `Underwriter`, `PlatformAdmin` |
| GET | `/cosigners` | List cosigners, filterable by application | `Borrower`, `Underwriter`, `PlatformAdmin` |
| POST | `/cosigners/{id}/consent` | Cosigner consents; recompute parent DTI | `Cosigner` |
| POST | `/cosigners/{id}/decline` | Cosigner declines | `Cosigner` |
| POST | `/cosigners/{id}/release` | Release a cosigner on a release-eligible loan | `Borrower` |
| GET | `/loans/{id}` | Fetch a loan with balances and both status dimensions | `Borrower`, `ServicingAgent`, `DisbursementOfficer`, `PlatformAdmin` |
| GET | `/loans` | List loans, filterable by application and pool | `ServicingAgent`, `DisbursementOfficer`, `PlatformAdmin` |
| POST | `/loans/{id}/payments` | Post a payment; accrue, allocate, update streak | `ServicingAgent`, `Borrower` |
| GET | `/loans/{id}/payments` | List payments for a loan | `Borrower`, `ServicingAgent`, `PlatformAdmin` |
| POST | `/loans/{id}/forbearance` | Place loan into hardship forbearance | `ServicingAgent` |
| POST | `/loans/{id}/mark-delinquent` | Mark a current loan delinquent | `ServicingAgent` |
| POST | `/loans/{id}/charge-off` | Charge off a delinquent loan | `ServicingAgent` |
| GET | `/forbearance-plans/{id}` | Fetch a forbearance plan | `ServicingAgent`, `Borrower`, `PlatformAdmin` |
| GET | `/forbearance-plans` | List forbearance plans, filterable by loan | `ServicingAgent`, `Borrower`, `PlatformAdmin` |
| POST | `/forbearance-plans/{id}/end` | End forbearance; capitalize interest | `ServicingAgent` |
| POST | `/disbursements` | Schedule a payoff disbursement to a prior servicer | `DisbursementOfficer` |
| GET | `/disbursements/{id}` | Fetch a disbursement | `DisbursementOfficer`, `ServicingAgent`, `PlatformAdmin` |
| GET | `/disbursements` | List disbursements, filterable by loan | `DisbursementOfficer`, `ServicingAgent`, `PlatformAdmin` |
| POST | `/disbursements/{id}/send` | Send a payoff (segregation of duties) | `DisbursementOfficer` |
| POST | `/disbursements/{id}/confirm` | Confirm a sent payoff | `DisbursementOfficer` |
| POST | `/disbursements/{id}/return` | Mark a sent payoff returned | `DisbursementOfficer` |
| GET | `/audit-events` | List audit events, filterable by subject | `PlatformAdmin`, `Underwriter` |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_COSIGNER_NOT_CONSENTED` | 409 |
| `ERR_RELEASE_NOT_ELIGIBLE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_NO_MATCHING_RATE` | 422 |
| `ERR_NO_LOCKED_OFFER` | 409 |
| `ERR_DTI_EXCEEDED` | 422 |
| `ERR_NO_ELIGIBLE_POOL` | 422 |
| `ERR_PAYOFF_EXCEEDS_PRINCIPAL` | 422 |
| `ERR_FORBEARANCE_TERM_INVALID` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_COSIGNER_ALREADY_ATTACHED` | 409 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_FORBEARANCE_ALREADY_ACTIVE` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
