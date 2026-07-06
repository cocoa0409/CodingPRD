# Copyright Registration & Licensing API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Copyright Registration & Licensing API, a back-office system modeled on the workflows of a national copyright office. The system manages the full life of a creative work as it moves through the registration pipeline: an author or claimant records the work, files an electronic (eCO-style) application, submits a deposit copy, pays the statutory filing fee, and then works with an examiner through examination and correspondence until the office either grants a registration certificate or refuses the claim.

Beyond initial registration, the platform administers the downstream regulated activities that flow from a registered work. It records transfers of ownership (recordation of the chain of title), tracks exclusive and non-exclusive licenses, accrues and distributes royalties through period-based statements, handles statutory termination of transfers, and processes DMCA takedown notices together with their counter-notices and restoration windows. Because these workflows are tightly coupled — a recorded transfer can ripple through active licenses and their royalty statements, and an effectuated termination unwinds an escrow — the system's value lies in enforcing the cross-entity consistency rules precisely and deterministically rather than in the raw number of endpoints it exposes.

All time-sensitive behavior in the system is governed by a **logical clock** rather than wall-clock time, so that statutory windows (renewal, termination, DMCA restoration, correspondence deadlines) can be exercised deterministically. Every actor authenticates through HTTP headers, and every monetary quantity is tracked in integer cents so that fees, royalties, and escrow balances remain exact.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers. Each request must include `X-User-ID`, an opaque identifier for the acting user, and `X-User-Role`, which declares the operational capacity of that user. If the `X-User-Role` header is missing or names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `RightsHolder`, `Examiner`, `Complainant`, and `Admin`.

- A `RightsHolder` is an author, claimant, or rights owner. This role registers works, files and submits applications, supplies deposit copies, pays fees, responds to examiner correspondence, renews certificates, grants licenses, manages royalty statements, files counter-notices, and serves terminations.
- An `Examiner` is a copyright office registration specialist. This role begins examinations, issues correspondence, registers or refuses applications, accepts or rejects deposits, records transfers of ownership, processes and restores DMCA takedowns, and effectuates terminations.
- A `Complainant` is a DMCA complaining party. This role files and withdraws takedown notices.
- An `Admin` is an operational role that controls the logical clock and, like all roles, may read any resource.

All four roles share read access: every `GET` (retrieve and list) endpoint is available to `RightsHolder`, `Examiner`, `Complainant`, and `Admin` alike.

The identity semantics of every role are **opaque**. For each of `RightsHolder`, `Examiner`, `Complainant`, and `Admin`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares `X-User-ID` to any entity's `id`. The server does, however, **record** the acting `X-User-ID` on resources at creation time so that ownership can later be checked: when a `RightsHolder` creates a work the value is stored as `owner_user_id` on the `Work`; when a `RightsHolder` files an application it is stored as `applicant_user_id` on the `Application`; when a `RightsHolder` grants a license it is stored as `licensor_user_id` on the `License`; when a `Complainant` files a takedown it is stored as `complainant_user_id` on the `DmcaTakedown`; and when a `RightsHolder` files a counter-notice it is stored as `subscriber_user_id` on the `CounterNotice`.

Certain owner-scoped application actions require that the acting user be the original applicant. For submitting an application, paying its fee, responding to its correspondence, and withdrawing it, the acting `X-User-ID` must equal the `applicant_user_id` recorded on that `Application`; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

All list endpoints accept two pagination query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and must be zero or greater. A request whose `limit` falls outside the range of 1 through 100, or whose `offset` is negative, is rejected with `ERR_INVALID_PAGINATION`.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` reflects the total number of matching resources before the page window is applied and `has_more` indicates whether further pages remain. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries four common properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, captured from the logical clock; `created_at` is set when the resource is first persisted, and `updated_at` is refreshed on every mutation. The `version` is an integer that begins at 1 when a resource is created and increases by 1 on each subsequent mutation of that resource. Every entity in this system — `Work`, `Application`, `Deposit`, `Certificate`, `Recordation`, `License`, `RoyaltyStatement`, `DmcaTakedown`, `CounterNotice`, and `Termination` — carries all four of these properties.

Because entities are stored as independent top-level collections that reference one another by identifier, retrieval of a resource by its path identifier fails with `ERR_NOT_FOUND` when no resource with that `id` exists, and any create or action request that names a foreign resource which does not exist likewise fails with `ERR_NOT_FOUND`.

### 2.5. The Logical Clock

The system keeps a single logical clock that supplies every system timestamp — `created_at`, `updated_at`, and all of the domain timestamps such as `submitted_at`, `fee_paid_at`, `accepted_at`, `registered_at`, `recorded_at`, `effective_at`, `countered_at`, `forwarded_at`, and `renewed_at`. On server startup the clock reads exactly `2026-05-01T00:00:00Z`; before any clock-setting call is made it holds precisely this default and never falls back to real wall-clock time.

An `Admin` may advance or set the clock by supplying a target instant in the `to_iso8601` field; the response reports the new value as `current_utc`. If the supplied value is not a valid ISO 8601 datetime, the request is rejected with `ERR_CLOCK_INVALID`.

### 2.6. Order of Request Validation

Requests are validated in a fixed priority order, and the first failing check determines the error returned. This ordering matters because several checks could apply to the same request, and a later check must never mask an earlier one.

1. **Authentication.** The `X-User-Role` header must be present and name a known role, otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role must be permitted for the endpoint per the access rules of §2.1, otherwise `ERR_FORBIDDEN`.
3. **Request well-formedness.** For write endpoints, the body must be well-formed: all required fields present, enumerated values valid, integer amounts non-negative, an `owner_shares` list whose `share_bps` values sum to exactly 10000, and a `publication_date` present whenever the work is published. A violation yields `ERR_VALIDATION`. For list endpoints, out-of-range pagination yields `ERR_INVALID_PAGINATION`, and for the clock endpoint a bad datetime yields `ERR_CLOCK_INVALID`.
4. **Existence.** The path resource and every referenced foreign entity must exist, otherwise `ERR_NOT_FOUND`.
5. **Ownership.** For the owner-scoped application actions, the acting user must own the application, otherwise `ERR_NOT_RESOURCE_OWNER`.
6. **Concurrency.** For a recordation create, the optimistic-concurrency check on the work's version is applied, otherwise `ERR_STALE_VERSION`.
7. **State and business rules.** State-transition validity and the remaining business, temporal, and fiscal constraints are evaluated last, in the order in which the business narrative of §3 describes them.

Within the final band, when a single operation carries more than one business precondition the checks are ordered from the most fundamental to the most specific. In particular, when an examiner begins an examination, the state check that the application is `SUBMITTED` is evaluated first, then the requirement that an accepted deposit exists (`ERR_DEPOSIT_NOT_ACCEPTED`), and only then the requirement that the full fee has been paid (`ERR_FEE_NOT_PAID`).

### 2.7. Monetary Amounts, Basis Points, and Rounding

All monetary quantities — filing fees, fee payments, refunds, gross revenue, deductions, accrued royalties, distributions, and escrow balances — are tracked as integer numbers of cents; a fee stated as forty-five dollars is stored as 4,500 cents. Filing-fee arithmetic is exact and requires no rounding.

Royalty rates are expressed in basis points, where 10000 basis points represent one hundred percent. Whenever a royalty amount is derived by applying a basis-point rate to a monetary amount, the raw product is divided by 10000 and the result is rounded to the nearest whole cent using round-half-up (a fractional cent of exactly one-half rounds up). Royalty distribution across multiple owners does not round each owner's share; it floors each share and then allocates the leftover cents deterministically, as detailed in §3.6, so that the distributed total always equals the accrued total exactly.

### 2.8. Optimistic Concurrency on the Chain of Title

Recording a transfer of ownership is guarded by optimistic concurrency control on the target work. A request to record a transfer must carry `expected_work_version`, and this is a required input, not an optional one. The value must equal the current `version` of the `Work` named by `work_id`. If a prior transfer has already been recorded against that work since the client last read it — a legitimate chain-of-title supersession that advances the work's `version` — then the client's view is stale, and the recordation is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a writer from recording a transfer on top of a work state it never observed. Recordation is the only write in the system that carries a version-expectation field; no other endpoint takes one.

### 2.9. Cascading Consistency and Conserved Quantities

Several operations mutate more than one entity, and every such cascade is intended to keep the model internally consistent. Whenever a work's registration state or ownership changes, whenever a certificate is minted, and whenever a license or its royalty statements change state, the affected resources have their `updated_at` refreshed and their `version` incremented as part of the same operation. The specific cascades — a recorded transfer rippling through licenses and their statements, and an effectuated termination unwinding an escrow — are described within the relevant workflows in §3.

Two quantities are conserved by design. For each application, `net_fee_cents` always equals `fee_paid_cents` minus `fee_refunded_cents`; when an application is refused or withdrawn, the full paid fee is refunded and this net returns to zero. For each license, `escrow_balance_cents` always equals the sum of `accrued_cents` across that license's `POSTED` royalty statements; posting adds to the balance, and distributing, reversing, or terminating removes from it.

## 3. Business Logic & Workflows

### 3.1. Registering a Work and Opening an Application

The lifecycle begins when a `RightsHolder` registers a **work** — the metadata describing a creative work. Creation requires a `title`, a `work_type`, the `year_of_creation`, the `author_name`, and an `owner_shares` list. The `work_type` is one of `LITERARY`, `MUSICAL`, `SOUND_RECORDING`, `VISUAL_ARTS`, `DRAMATIC`, `ARCHITECTURAL`, or `MOTION_PICTURE`. The `owner_shares` list enumerates ownership as objects of the form name and `share_bps`, where the `share_bps` are integers that must sum to exactly 10000; this split later drives royalty distribution. A work may optionally be marked with `is_published`, which defaults to false; when a work is published, a `publication_date` must be supplied, and its absence is a malformed body.

At creation the server records the acting user as `owner_user_id`, sets the work's `registration_status` to `UNREGISTERED`, and initializes the computed `current_owner_name` to the `author_name`. The `current_owner_name` is thereafter the `transferee_name` of the most recent transfer recorded against the work that has not been superseded, falling back to `author_name` when no transfer stands.

To pursue registration, the `RightsHolder` files an **application** naming the work through `work_id`. The application declares a `filing_basis` of either `SINGLE_AUTHOR_SINGLE_WORK` or `STANDARD`, and may declare a `claimant_count` (defaulting to 1, and never less than 1) and an `is_expedited` flag (defaulting to false). A newly filed application is created in `DRAFT`, and the acting user is recorded as `applicant_user_id`. The system permits only one non-terminal application per work at any time: because the terminal application states are `REGISTERED`, `REFUSED`, and `WITHDRAWN`, an attempt to file a second application for a work that already has one in any other state is rejected with `ERR_DUPLICATE_ACTIVE_APPLICATION`.

The work's `registration_status` is a compound value derived from the life of its application. It is recomputed on each application transition: it becomes `PENDING` when the application is submitted, `REGISTERED` when the application is registered, and returns to `UNREGISTERED` when the application is refused or withdrawn. Each of these recomputations increments the work's `version` by 1.

### 3.2. Deposits and the Filing Fee

Before examination can begin, two independent prerequisites must be satisfied: an accepted deposit copy and a fully paid fee.

A `RightsHolder` submits a **deposit** against an application by naming it through `application_id` and providing a `deposit_type` of `ELECTRONIC` or `PHYSICAL` together with a `copy_count`. A deposit is created in `SUBMITTED`. An `Examiner` reviews it: accepting the deposit advances it from `SUBMITTED` to `ACCEPTED` and stamps `accepted_at` with the clock, while rejecting it moves it from `SUBMITTED` to `DEFICIENT`. Acceptance enforces a minimum number of copies that depends on the type — the count must be at least `DEPOSIT_MIN_COPIES_ELECTRONIC` for an electronic deposit and at least `DEPOSIT_MIN_COPIES_PHYSICAL` for a physical one; a deposit whose `copy_count` falls below the applicable minimum cannot be accepted and is rejected with `ERR_DEPOSIT_INSUFFICIENT_COPIES`. Both accept and reject require the deposit to still be `SUBMITTED`, otherwise `ERR_INVALID_STATE`.

Submitting the application is what fixes the fee. When a `RightsHolder` submits a `DRAFT` application — advancing it from `DRAFT` to `SUBMITTED` — the system computes `fee_due_cents`, stamps `submitted_at` from the clock, and moves the work's `registration_status` to `PENDING`. Submission is only valid from `DRAFT` (otherwise `ERR_INVALID_STATE`), must be performed by the owning applicant (otherwise `ERR_NOT_RESOURCE_OWNER`), and, when the work is published, requires that the work's `publication_date` be present. If the declared basis is `SINGLE_AUTHOR_SINGLE_WORK`, that basis is only valid when `claimant_count` equals 1 and the work is not published; a `SINGLE_AUTHOR_SINGLE_WORK` filing that names more than one claimant or a published work is rejected with `ERR_FILING_BASIS_INVALID`.

The fee itself is computed as follows. When the basis is `SINGLE_AUTHOR_SINGLE_WORK`, the `claimant_count` is 1, and the work is not published, the base fee is the single-work base of 4,500 cents ($45.00). Otherwise the base is the standard base of 6,500 cents ($65.00), to which an additional-claimant surcharge is added: for each claimant beyond the first — that is, the `claimant_count` minus one, or zero if there is only one claimant — an extra 1,500 cents ($15.00) is added; this surcharge applies only under the standard base. Finally, if `is_expedited` is true, an expedite surcharge of 80,000 cents ($800.00) is added on top. The resulting amount is stored as `fee_due_cents`.

Payment is exact. When a `RightsHolder` pays the fee, the request supplies `amount_cents`, which must equal `fee_due_cents` exactly; any other amount is rejected with `ERR_FEE_AMOUNT_MISMATCH`. A successful payment sets `fee_paid_cents` to the amount received, recomputes `net_fee_cents` as `fee_paid_cents` minus `fee_refunded_cents`, and stamps `fee_paid_at` from the clock. The paying user must be the owning applicant, otherwise `ERR_NOT_RESOURCE_OWNER`. The `fee_paid_cents`, `fee_refunded_cents`, and `net_fee_cents` values all begin at zero on a fresh application.

### 3.3. Examination, Correspondence, and the Registration Decision

An `Examiner` moves a `SUBMITTED` application into examination, advancing its `status` from `SUBMITTED` to `UNDER_EXAMINATION`. This step depends on both prerequisites from §3.2: an `ACCEPTED` deposit must exist for the application (otherwise `ERR_DEPOSIT_NOT_ACCEPTED`) and the amount paid must cover the amount due, meaning `fee_paid_cents` is at least `fee_due_cents` (otherwise `ERR_FEE_NOT_PAID`). Attempting this from any status other than `SUBMITTED` yields `ERR_INVALID_STATE`.

Examination and correspondence form a cycle. An `Examiner` may open a correspondence request, moving the application from `UNDER_EXAMINATION` to `CORRESPONDENCE`; this requires an `issue_code` and a `message`, sets `correspondence_open` to true, sets the `correspondence_deadline` to the clock time plus `CORRESPONDENCE_DAYS` days, and increments `correspondence_rounds` by 1. The applicant then responds, supplying a `message`, which moves the application from `CORRESPONDENCE` back to `UNDER_EXAMINATION` and clears `correspondence_open` to false. The response must arrive on or before the `correspondence_deadline`; a response after that instant is rejected with `ERR_CORRESPONDENCE_EXPIRED`, and the responder must be the owning applicant (otherwise `ERR_NOT_RESOURCE_OWNER`). Because the examiner may open correspondence again after each response, `correspondence_rounds` accumulates one per cycle.

The examination ends in one of three ways, each valid only while examination is genuinely in progress.

- **Registration.** An `Examiner` grants registration, advancing the application from `UNDER_EXAMINATION` to `REGISTERED`. This transition is only valid from `UNDER_EXAMINATION`; in particular, it is invalid while a correspondence round is open (that is, while the application sits in `CORRESPONDENCE`), and such an attempt is rejected with `ERR_INVALID_STATE`. Granting registration mints a new **certificate** (see below), stamps `registered_at` from the clock, and moves the work's `registration_status` to `REGISTERED`, incrementing the work's `version`.
- **Refusal.** An `Examiner` refuses the application, advancing it from `UNDER_EXAMINATION` to `REFUSED` and optionally attaching a `reason`. Refusal refunds the full paid fee: `fee_refunded_cents` increases by `fee_paid_cents`, so that `net_fee_cents` returns to zero, and the work's `registration_status` returns to `UNREGISTERED`, incrementing the work's `version`.
- **Withdrawal.** The owning `RightsHolder` may withdraw an application while it is still `DRAFT` or `SUBMITTED`, advancing it to `WITHDRAWN`. Like refusal, withdrawal refunds the full paid fee — `fee_refunded_cents` increases by `fee_paid_cents` and `net_fee_cents` returns to zero — and returns the work's `registration_status` to `UNREGISTERED`, incrementing the work's `version`. Withdrawal from any status other than `DRAFT` or `SUBMITTED` is an invalid transition, and a withdrawal by someone other than the owning applicant is rejected with `ERR_NOT_RESOURCE_OWNER`.

The **certificate** created at registration is a one-to-one companion of the registered application, linked by `application_id`. The system mints a `registration_number`, sets `decision_date` to the registration decision instant (the same clock value as `registered_at`), and computes the `effective_date`. Following the receipt-completion rule, the `effective_date` is the latest of three calendar dates: the date of `submitted_at`, the date the accepted deposit's `accepted_at` was stamped, and the date of `fee_paid_at` — all compared at calendar-day granularity. (The `decision_date` records the later registration-decision date separately and is not itself the effective date.) The certificate is created with `status` `ISSUED`. It also fixes its renewal window: the `renewal_deadline` is the `effective_date` plus `RENEWAL_TERM_YEARS` years, and the `renewal_window_start` is that same deadline moved earlier by `RENEWAL_WINDOW_SPAN_YEARS` years (equivalently, `effective_date` plus `RENEWAL_TERM_YEARS` minus `RENEWAL_WINDOW_SPAN_YEARS` years).

A `RightsHolder` may renew a certificate, advancing it from `ISSUED` to `RENEWED` and stamping `renewed_at` from the clock. Renewal is only valid while the certificate is `ISSUED`, and only when the clock is on or after `renewal_window_start` and on or before `renewal_deadline`; a renewal attempt outside that inclusive window is rejected with `ERR_RENEWAL_WINDOW`.

### 3.4. Recordation of Transfer and the Chain of Title

An `Examiner` records a transfer of ownership against a work by naming it through `work_id` and supplying the `transferor_name`, the `transferee_name`, the `execution_date` on which the transfer document was executed, and the `expected_work_version` required by the concurrency rule of §2.8. A recordation is created directly in `RECORDED` and stamps `recorded_at` from the clock; the office is recording an already-executed document, so there is no separate approval step.

Recording a transfer sets off a three-link cascade. First (link A), any prior transfer that is still `RECORDED` for the same work is moved to `SUPERSEDED`, the work's `current_owner_name` is set to the new `transferee_name`, and the work's `version` is incremented. Second (link B), because ownership has changed, every `License` on that work that is currently `ACTIVE` is moved to `UNDER_REVIEW`. Third (link C), for each license so moved, every royalty statement under it that is still in `DRAFT` is moved to `VOIDED`. Each link is caused by the one before it: the ownership change drives the licenses under review, and the licenses under review drive the draft statements void.

A recordation may also be superseded later: when a newer transfer for the same work is recorded, the standing one transitions from `RECORDED` to `SUPERSEDED` as part of the cascade above.

### 3.5. Licensing a Registered Work

Once a work is registered, its `RightsHolder` may grant a **license**. Creating a license requires the `work_id`, a `licensee_name`, a `license_type` of `EXCLUSIVE` or `NON_EXCLUSIVE`, a `right_type` of `REPRODUCTION`, `DISTRIBUTION`, `PERFORMANCE`, `DERIVATIVE`, or `PUBLIC_DISPLAY`, a `territory` of `US`, `EU`, or `WORLD`, the term bounds `start_date` and `end_date`, the `grant_date` on which the grant was executed, a `royalty_rate_bps`, and a `royalty_basis` of `GROSS` or `NET`. A license is created in `ACTIVE`, records the acting user as `licensor_user_id`, and starts with an `escrow_balance_cents` of zero.

A license may only be created for a work whose `registration_status` is `REGISTERED`; a license against an unregistered or merely pending work is rejected with `ERR_WORK_NOT_REGISTERED`. The license term is a half-open interval that runs from `start_date` inclusive to `end_date` exclusive, and `start_date` must fall strictly before `end_date`, otherwise `ERR_INVALID_DATE_RANGE`. Exclusivity is protected: a new `EXCLUSIVE` license must not overlap an existing `EXCLUSIVE` license — one that is `ACTIVE` or `UNDER_REVIEW` — that covers the same work, the same `right_type`, and the same `territory`, where overlap is measured over the half-open `start_date`-to-`end_date` interval. A conflicting exclusive grant is rejected with `ERR_EXCLUSIVE_CONFLICT`.

### 3.6. Royalty Statements: Accrual, Distribution, and Reversal

Royalties are reported one accounting period at a time through a **royalty statement**. A `RightsHolder` creates a statement by naming the license through `license_id` and supplying the `period_start` and `period_end` bounds, the `gross_revenue_cents` for the period, and an optional `deduction_cents` (defaulting to zero, and used only under a net basis). A statement's period is a closed interval running from `period_start` inclusive through `period_end` inclusive, and `period_start` must fall strictly before `period_end`, otherwise `ERR_INVALID_DATE_RANGE`. Two statements for the same license may not cover overlapping periods: a new period that overlaps an existing statement of the same license which is neither `REVERSED` nor `VOIDED`, measured over the closed period interval, is rejected with `ERR_PERIOD_OVERLAP`. A statement is created in `DRAFT`; its computed fields `accrued_cents`, `distributed_cents`, and `distribution` all begin empty or zero.

**Posting** a statement moves it from `DRAFT` to `POSTED` and computes the accrual. Posting is only allowed while the parent license is `ACTIVE`; a post against a license that is not `ACTIVE` is rejected with `ERR_LICENSE_NOT_ACTIVE`. The accrual depends on the license's `royalty_basis`. Under a `GROSS` basis, the accrued amount is the `gross_revenue_cents` multiplied by the `royalty_rate_bps`, divided by 10000, and rounded half-up to the nearest whole cent; the `deduction_cents` is ignored. Under a `NET` basis, the `deduction_cents` is first subtracted from the `gross_revenue_cents`, and that net amount is then multiplied by the `royalty_rate_bps`, divided by 10000, and rounded half-up to the nearest whole cent. The resulting `accrued_cents` is added to the parent license's `escrow_balance_cents`.

**Distributing** a statement moves it from `POSTED` to `DISTRIBUTED` and splits the accrual across the work's owners. The distribution follows a deterministic waterfall over the work's `owner_shares`. For each owner, a base amount is computed as the `accrued_cents` multiplied by that owner's `share_bps`, divided by 10000, and then floored to a whole cent. The remainder — the `accrued_cents` minus the sum of all floored base amounts, which is at least zero and less than the number of owners — is then distributed one cent at a time to owners taken in order of descending `share_bps`, breaking ties by the owner's position in the `owner_shares` list (earliest position first, never by any identifier), until the remainder is exhausted. The resulting per-owner list is stored as `distribution`, a list of name and `amount_cents` pairs, and `distributed_cents` is set to the sum, which by construction equals `accrued_cents`. Distribution then removes the accrued amount from the license's `escrow_balance_cents`.

**Reversing** a statement moves it from `POSTED` to `REVERSED` and removes its accrued amount from the license's `escrow_balance_cents`. Reversal is a compensating action: a statement that is posted and then reversed leaves the escrow balance exactly as it was before posting. Posting, reversing, and distributing all require the statement to be in the appropriate source state (`DRAFT` for posting, `POSTED` for distributing or reversing), otherwise `ERR_INVALID_STATE`. Finally, a `DRAFT` statement is moved to `VOIDED` automatically when its parent license enters `UNDER_REVIEW` as part of the recordation cascade of §3.4. At all times a license's `escrow_balance_cents` equals the sum of `accrued_cents` across its `POSTED` statements.

### 3.7. Termination of a Transfer

An author or heir may serve a statutory **termination** against a license grant. Serving a termination names the license through `license_id` and supplies the `terminating_party_name`, the `notice_served_date`, and the requested `effective_date`; the termination is created in `NOTICE_SERVED`. At creation the system computes the statutory window from the license's `grant_date`: the `window_earliest_date` is the `grant_date` plus 35 years, and the `window_latest_date` is that earliest date plus a further 5 years. These bounds are calendar-year arithmetic and both ends are inclusive.

An `Examiner` then effectuates the termination, advancing it from `NOTICE_SERVED` to `EFFECTIVE`. This is only permitted when the requested `effective_date` falls on or after `window_earliest_date` and on or before `window_latest_date`; an effective date outside that inclusive window is rejected with `ERR_TERMINATION_WINDOW`. Effectuation drives a three-link cascade: the parent license is moved to `TERMINATED` (link A, from either `ACTIVE` or `UNDER_REVIEW`); every royalty statement under that license which is `POSTED` is moved to `REVERSED` (link B, because the license terminated); and the license's `escrow_balance_cents` is driven to zero (link C, because those statements were reversed).

### 3.8. DMCA Takedowns, Counter-Notices, and Restoration

A `Complainant` files a **DMCA takedown** against a work by naming it through `work_id` and supplying a `complainant_name` and the `infringing_url` of the allegedly infringing material; the acting user is recorded as `complainant_user_id`, and the notice is created in `FILED`. An `Examiner` processes the notice, advancing it from `FILED` to `EFFECTIVE` and stamping `effective_at` from the clock — at which point the material is treated as removed. A `Complainant` may withdraw the notice while it is either `FILED` or `EFFECTIVE`, moving it to `WITHDRAWN`.

A `RightsHolder` (the subscriber) may contest an effective takedown by filing a **counter-notice**, naming the takedown through `takedown_id` and supplying a `subscriber_name` and a good-faith `statement`; the acting user is recorded as `subscriber_user_id`. A counter-notice may only be filed while the takedown is `EFFECTIVE`; filing against a takedown in any other state is rejected with `ERR_TAKEDOWN_NOT_EFFECTIVE`. At most one counter-notice may exist per takedown, and a second attempt is rejected with `ERR_COUNTER_NOTICE_EXISTS`. Filing a counter-notice creates it in `FORWARDED`, stamps `forwarded_at` from the clock, and forwards it to the complainant: as a side effect the takedown moves from `EFFECTIVE` to `COUNTERED`, its `countered_at` is stamped from the clock, and its restoration window is fixed — `restoration_earliest_date` becomes the clock time plus `RESTORE_MIN_DAYS` days and `restoration_latest_date` becomes the clock time plus `RESTORE_MAX_DAYS` days.

Finally, an `Examiner` restores the material, advancing the takedown from `COUNTERED` to `RESTORED`. Restoration is bounded by the window fixed at counter-notice time: the clock must be on or after `restoration_earliest_date`, otherwise the restore is rejected with `ERR_RESTORE_TOO_EARLY`, and on or before `restoration_latest_date`, otherwise it is rejected with `ERR_RESTORE_WINDOW_EXPIRED`. Restoring a takedown also moves its counter-notice from `FORWARDED` to `COMPLETE`. State-transition attempts made from the wrong source state — processing something that is not `FILED`, restoring something that is not `COUNTERED`, and so on — are rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource return HTTP 201; endpoints that read a resource or modify an existing one return HTTP 200. All list endpoints accept the `limit` and `offset` pagination parameters described in §2.3, and the list filters shown below (such as `work_id`, `status`, `application_id`, `license_id`, `takedown_id`, `work_type`, and `registration_status`) are optional. Request bodies, response shapes, and side effects are intentionally omitted here; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/copyright/_clock/set_current_utc` | Set the logical clock | Admin |
| POST | `/copyright/works` | Register a work record | RightsHolder |
| GET | `/copyright/works/{id}` | Get a work | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/works` | List works | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/applications` | File an eCO application for a work | RightsHolder |
| GET | `/copyright/applications/{id}` | Get an application | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/applications` | List/filter applications | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/applications/{id}/submit` | Submit a draft application | RightsHolder |
| POST | `/copyright/applications/{id}/pay-fee` | Pay the filing fee | RightsHolder |
| POST | `/copyright/applications/{id}/begin-examination` | Move a submitted application into examination | Examiner |
| POST | `/copyright/applications/{id}/issue-correspondence` | Open a correspondence request | Examiner |
| POST | `/copyright/applications/{id}/respond-correspondence` | Respond to correspondence | RightsHolder |
| POST | `/copyright/applications/{id}/register` | Grant registration and mint a certificate | Examiner |
| POST | `/copyright/applications/{id}/refuse` | Refuse registration and refund the fee | Examiner |
| POST | `/copyright/applications/{id}/withdraw` | Withdraw a draft or submitted application | RightsHolder |
| POST | `/copyright/deposits` | Submit a deposit copy for an application | RightsHolder |
| GET | `/copyright/deposits/{id}` | Get a deposit | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/deposits` | List/filter deposits | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/deposits/{id}/accept` | Accept a deposit | Examiner |
| POST | `/copyright/deposits/{id}/reject` | Mark a deposit deficient | Examiner |
| GET | `/copyright/certificates/{id}` | Get a certificate | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/certificates` | List/filter certificates | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/certificates/{id}/renew` | Renew a certificate within the renewal window | RightsHolder |
| POST | `/copyright/recordations` | Record a transfer of ownership | Examiner |
| GET | `/copyright/recordations/{id}` | Get a recordation | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/recordations` | List/filter recordations | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/licenses` | Create a licensing record for a registered work | RightsHolder |
| GET | `/copyright/licenses/{id}` | Get a license | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/licenses` | List/filter licenses | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/royalty-statements` | Create a royalty statement for a license period | RightsHolder |
| GET | `/copyright/royalty-statements/{id}` | Get a royalty statement | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/royalty-statements` | List/filter royalty statements | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/royalty-statements/{id}/post` | Post a draft statement (accrue into escrow) | RightsHolder |
| POST | `/copyright/royalty-statements/{id}/distribute` | Distribute a posted statement to owners | RightsHolder |
| POST | `/copyright/royalty-statements/{id}/reverse` | Reverse a posted statement | RightsHolder |
| POST | `/copyright/dmca-takedowns` | File a DMCA takedown notice | Complainant |
| GET | `/copyright/dmca-takedowns/{id}` | Get a DMCA takedown | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/dmca-takedowns` | List/filter DMCA takedowns | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/dmca-takedowns/{id}/process` | Process a takedown (material removed) | Examiner |
| POST | `/copyright/dmca-takedowns/{id}/restore` | Restore material after the counter-notice window | Examiner |
| POST | `/copyright/dmca-takedowns/{id}/withdraw` | Withdraw a takedown | Complainant |
| POST | `/copyright/counter-notices` | File a counter-notice against an effective takedown | RightsHolder |
| GET | `/copyright/counter-notices/{id}` | Get a counter-notice | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/counter-notices` | List/filter counter-notices | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/terminations` | Serve a termination of transfer against a license | RightsHolder |
| GET | `/copyright/terminations/{id}` | Get a termination | RightsHolder, Examiner, Complainant, Admin |
| GET | `/copyright/terminations` | List/filter terminations | RightsHolder, Examiner, Complainant, Admin |
| POST | `/copyright/terminations/{id}/effectuate` | Effectuate a termination within the statutory window | Examiner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_VALIDATION | 422 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_FILING_BASIS_INVALID | 409 |
| ERR_TAKEDOWN_NOT_EFFECTIVE | 409 |
| ERR_LICENSE_NOT_ACTIVE | 409 |
| ERR_WORK_NOT_REGISTERED | 409 |
| ERR_DEPOSIT_NOT_ACCEPTED | 409 |
| ERR_DUPLICATE_ACTIVE_APPLICATION | 409 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_TERMINATION_WINDOW | 409 |
| ERR_RESTORE_TOO_EARLY | 409 |
| ERR_RESTORE_WINDOW_EXPIRED | 409 |
| ERR_RENEWAL_WINDOW | 409 |
| ERR_CORRESPONDENCE_EXPIRED | 409 |
| ERR_EXCLUSIVE_CONFLICT | 409 |
| ERR_PERIOD_OVERLAP | 409 |
| ERR_COUNTER_NOTICE_EXISTS | 409 |
| ERR_DEPOSIT_INSUFFICIENT_COPIES | 409 |
| ERR_FEE_AMOUNT_MISMATCH | 409 |
| ERR_FEE_NOT_PAID | 409 |
| ERR_INVALID_PAGINATION | 422 |
| ERR_CLOCK_INVALID | 422 |
