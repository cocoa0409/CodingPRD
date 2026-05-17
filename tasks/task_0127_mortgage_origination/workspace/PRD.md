# Mortgage Origination API — Product Requirements Document

## 1. Introduction

Originating a residential mortgage in the United States is a regulated, multi-party process in which a single application travels from intake through pre-qualification, income and asset verification, property appraisal, title search, underwriting, disclosure delivery, rate-lock management, and finally consummation at closing. Each stage is gated by federal compliance regimes — most notably TRID (the TILA-RESPA Integrated Disclosure rule) and UDAAP (Unfair, Deceptive, or Abusive Acts or Practices) — and each gate has hard temporal and financial thresholds that, if missed, expose the originator to regulatory action.

This document specifies the back-end API that orchestrates that workflow. The system is intended to be operated by three principal user populations: loan officers who originate and shepherd applications, compliance officers who perform independent UDAAP reviews, and borrowers who consume disclosures. An administrative role exists for environment housekeeping, including driving a logical clock used to simulate the passage of business days during integration testing. The API enforces TRID waiting periods, APR-tolerance re-disclosure, segregation of duties between origination and compliance, and the bookkeeping for rate locks (including extensions, expiry, and the 48-hour free-look refund) so that the calling application can present a thin user-experience layer on top of a correctly compliant back end.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that every endpoint observes.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the role under which the request is being made. If either header is missing or empty, the system rejects the request with `ERR_AUTH_REQUIRED`. If the supplied role string is not one of the four recognised roles, the request is rejected with `ERR_FORBIDDEN_ROLE`. The system recognises four roles, spelled exactly as follows: `LoanOfficer`, `ComplianceOfficer`, `Borrower`, and `Admin`.

When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower`; ownership checks on any resource that references a `Borrower` compare the resource's `borrower_id` to `X-User-ID`. A borrower may read only those `LoanApplication` records whose `borrower_id` equals their own `X-User-ID`, and they may read only their own `Borrower` record. When `X-User-Role` is `LoanOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (for example, as `assigned_loan_officer_id` on a `LoanApplication` when intake captures the assignment) but does not compare it to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier; the server records it as `compliance_reviewer_id` on the `LoanApplication` at the moment underwriting is opened, and as `reviewer_user_id` on each UDAAP review the operator submits. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier with no entity binding.

Endpoint-level authorisation is further restricted by role, as enumerated in §4. An authenticated request whose role is recognised but not authorised for the requested operation is rejected with `ERR_FORBIDDEN_ROLE`. A second, more specific authorisation rule governs the boundary between origination and compliance: on `underwrite-decision` and on `clear-to-close`, the actor's `X-User-ID` must not equal the `compliance_reviewer_id` recorded on the application. Violations are rejected with `ERR_UDAAP_SOD_VIOLATION`. The same segregation appears, mirrored, in the UDAAP-review endpoint: the actor's `X-User-ID` must equal the `compliance_reviewer_id` on the application — a compliance officer can only review the applications to which they have been assigned.

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

List endpoints accept two query parameters, `limit` and `offset`. When omitted, `limit` defaults to 10; the minimum accepted value is 1 and the maximum is 100. When omitted, `offset` defaults to 0. Results are sorted by their creation timestamp in ascending order, so that the oldest record appears first. Every list response includes four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifier Conventions

Every primary, top-level resource — `Borrower`, `LoanApplication`, `IncomeVerification`, `AssetVerification`, `Appraisal`, `TitleSearch`, `RateLock`, and `Disclosure` — carries a common set of system-managed fields:

- `id` (string): a server-minted UUID without any type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation and immutable thereafter.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a monotonically increasing counter that starts at 1 and increments by 1 on every mutation. It supports optimistic concurrency control (see §2.7).

Two entities omit `updated_at` and `version`: `RateLockExtension` and `UDAAPReview` are conceptually append-only records that, once written, are not modified — they expose only `id` and `created_at`. The `SystemClock` is a singleton and exposes only the `now` field; it does not carry the common envelope.

The `Disclosure` entity also carries a domain-level `version` field that is distinct from the OCC counter described above: this is a monotonically increasing, server-minted, per-application-per-`kind` integer that starts at 1 for the first `LOAN_ESTIMATE` (and again at 1 for the first `CLOSING_DISCLOSURE`) issued for the application. Clients may not supply a `version` in the disclosure-issuance body; the server mints the next number atomically. Attempting to issue a disclosure of a given `kind` with a `version` value that does not match the next monotonic number is rejected with `ERR_DISCLOSURE_VERSION_CONFLICT`.

### 2.5. Nested Resource Resolution

URL paths that contain multiple resource identifiers are validated left-to-right. The system first confirms that the `LoanApplication` referenced by the leftmost identifier exists; if it does not, the request is rejected with `ERR_APPLICATION_NOT_FOUND` before any further check. Only after the parent application is located does the system look for the nested resource (an `IncomeVerification`, `AssetVerification`, `Appraisal`, `TitleSearch`, `RateLock`, `Disclosure`, or `UDAAPReview`); if that nested record is absent or not parented to the resolved application, the response is `ERR_RESOURCE_NOT_FOUND`. The two errors are not interchangeable, and tests rely on the ordering.

### 2.6. Hierarchical State Consistency and Cascades

State changes on a `LoanApplication` can have downstream effects on its children — most prominently on `RateLock` and `Disclosure` — and changes on certain children (notably `Appraisal`) can have upstream effects on the application itself. Every such cascade is a real mutation: the affected resource has its `status` updated, `updated_at` is refreshed, and `version` is incremented by 1. Three cascades are particularly important:

- When a `LoanApplication` transitions to `DENIED`, every non-terminal `Disclosure` (those in `ISSUED` or `ACKNOWLEDGED`) is marked `VOIDED`, and if a `RateLock` exists in `LOCKED` or `EXTENDED`, it is cascaded to `CANCELLED` with the refund computation described in §3.5.
- When a `LoanApplication` transitions to `WITHDRAWN`, the same `RateLock` cascade applies (Disclosures are left alone, because they may still be subpoenaed; the system simply does not advance them further).
- When an `Appraisal` completes and its `appraised_value_cents` is below the application's `sale_price_cents`, the system recomputes `ltv_ratio` on the parent `LoanApplication` using the lower value-basis, and if the recomputed `ltv_ratio` is greater than 0.80 it sets `pmi_required` to true on the application. This is a transitive cascade: the appraisal's completion triggers an LTV recompute, which in turn flips the PMI flag.

### 2.7. Optimistic Concurrency Control

Endpoints that mutate an existing resource accept an optional `version` integer in the request body. When supplied, the value must equal the resource's current `version`; if it does not, the request is rejected with `ERR_VERSION_CONFLICT`. When the field is omitted, the server processes the mutation without an OCC check. This is the system's standard mechanism for preventing lost updates between two collaborating operators editing the same record.

### 2.8. Precision and Rounding

All ratio calculations — specifically `dti_ratio` and `ltv_ratio` on the `LoanApplication` — are rounded half-up to 4 decimal places. All monetary calculations — including `lock_fee_cents`, `extension_fee_paid_cents`, `fee_cents` on a `RateLockExtension`, `refund_cents`, and `cash_to_close_cents` — are rounded half-up to whole cents (the stored values are integers in cents). Where a calculation involves more than one rounding step (most notably the closing-cost computation), the rounding order is fixed by §3.6 and must be followed exactly; alternative orderings can produce off-by-cent results that fail tests.

### 2.9. Logical Clock and Time-Gated Logic

All time-sensitive logic in the system — TRID waiting periods, appraisal validity, rate-lock expiry, and the 48-hour free-look refund window — is evaluated against `SystemClock.now`, a singleton UTC instant the system maintains. The default starting value of `now` is `2026-01-01T00:00:00.000Z`. An admin-only test-driving capability advances the clock to a supplied `to` instant in ISO 8601 UTC, and a public read endpoint exposes the current `now`. The clock only ever moves forward in test scenarios; nothing in the business logic rewinds it.

### 2.10. Validation Ordering

When multiple validation failures could apply to the same request, the system evaluates them in this fixed precedence so that the returned error code is deterministic. Authentication and role checks come first: presence of `X-User-ID` and `X-User-Role` is checked before anything else, then membership of the role in the recognised set. After authentication, existence checks run in path order — first the parent `LoanApplication`, then any nested resource. State-machine checks (whether the source state matches the transition's `from`) precede business-rule checks. Among the business-safety rules, segregation-of-duties is checked before the UDAAP-review-required check, which is checked before TRID waiting-period evaluation, which is checked before appraisal-expiry, which is checked before rate-lock-expiry. Dependency-presence at submit-underwriting is grouped with this temporal cluster. Constraint checks — APR tolerance, extension cap, rate-lock overlap, appraisal overlap, counter-offer bounds, disclosure version monotonicity, and OCC — follow. Fiscal-ratio checks (DTI and LTV ceilings at the approve decision) are the lowest-priority business checks before generic body schema validation, which is last.

The practical consequence is that, for example, an `underwrite-decision` request from a user who is also the compliance reviewer surfaces as `ERR_UDAAP_SOD_VIOLATION` rather than as a downstream DTI/LTV failure, even if the DTI would also have failed.

## 3. Business Logic & Workflows

### 3.1. Borrower Intake and Application Creation

The pipeline begins with a `LoanOfficer` (or an `Admin` performing setup) creating a `Borrower` record. The borrower payload carries five intake fields: the borrower's `full_name`, the last four digits of their Social Security Number in `ssn_last4` (exactly four numeric characters), their stated `annual_income_cents` (a non-negative integer in cents), their tri-merge FICO `credit_score` at intake (which must lie between 300 and 850 inclusive), and the two-letter US `state_code` for the subject property's location.

With a borrower on file, the loan officer creates a `LoanApplication` by supplying the `borrower_id`, the full `property_address`, the `sale_price_cents` (a strictly positive integer), the `requested_loan_amount_cents` (also strictly positive and not exceeding `sale_price_cents`), the `loan_term_months` (one of 120, 180, 240, or 360), the `loan_purpose` (`PURCHASE` or `REFINANCE`), and an `assigned_loan_officer_id` recording the operator who owns intake and disclosures. A newly created application enters the lifecycle in `INTAKE`. The computed fields `counter_offered_amount_cents`, `dti_ratio`, `ltv_ratio`, `compliance_reviewer_id`, `trid_clock_started_at`, and `closing_eligible_at` are all null at creation; `pmi_required` defaults to false.

From `INTAKE`, two transitions are immediately available: pre-qualifying the application advances `status` to `PRE_QUALIFIED`, and withdrawing it sets `status` to `WITHDRAWN`. Withdrawal from `INTAKE` carries no cascades, because no rate lock can yet exist.

### 3.2. Pre-Qualification

Pre-qualifying an application by a `LoanOfficer` advances `status` from `INTAKE` to `PRE_QUALIFIED` once three conditions are satisfied: the borrower's `credit_score` is at least 620, the borrower's `annual_income_cents` is strictly greater than zero, and the `requested_loan_amount_cents` is no more than four times the borrower's `annual_income_cents` (a rough debt-to-income proxy that holds the requested principal to no more than four years of stated gross income). Failure of these state-machine preconditions surfaces as `ERR_INVALID_STATE` if the source state itself is wrong, or as an `ERR_VALIDATION` for body-shape issues.

At this transition, the system also computes a preliminary `dti_ratio` using the **pre-qualification** variant of the DTI calculation. Because no `IncomeVerification` records have been verified yet, this preliminary value falls back to the borrower's stated `annual_income_cents` as the income basis (see §3.7 for the full formula and the distinction between the pre-qualification and underwriting variants).

From `PRE_QUALIFIED`, the lifecycle branches: the application can be withdrawn (cascading any active rate lock to `CANCELLED` with the standard refund computation), or — once the prerequisites are in place — submitted into underwriting. A separate branch returns to `PRE_QUALIFIED` from `UNDERWRITING` when underwriting issues a counter-offer; in that case `counter_offered_amount_cents` is populated on the application and the latest `LOAN_ESTIMATE` is superseded.

### 3.3. Income and Asset Verification

Before underwriting can begin, the loan officer accumulates documentary evidence of the borrower's ability to pay. Two parallel verification streams exist, each beginning in `PENDING`.

An `IncomeVerification` is created against the application with a `source_type` (one of `W2`, `SELF_EMPLOYED`, or `OTHER`) and a `documented_annual_cents` figure (the verified annual income in cents, which must be non-negative). The record can be transitioned to `VERIFIED` only when `documented_annual_cents` is at least 80% of the borrower's stated `annual_income_cents` — i.e., the documented figure lies within 20% below the stated figure. On verification, the system stamps the actor's identifier into `verifier_user_id` and advances `status` to `VERIFIED`. The record can also be rejected unconditionally from `PENDING`, transitioning to `REJECTED`.

An `AssetVerification` is created similarly with an `asset_type` (one of `CHECKING`, `SAVINGS`, `INVESTMENT`, or `GIFT`) and a `balance_cents` (non-negative integer cents). It moves from `PENDING` to `VERIFIED` only when the `balance_cents` is at least 1,000 (the materiality floor — assets under ten dollars are not counted). On verification the actor is stamped into `verifier_user_id`. The record can be rejected from `PENDING` unconditionally, transitioning to `REJECTED`.

Both verification streams are `application_id`-scoped and addressed by their parent application identifier. Once at least one record on each stream has reached `VERIFIED`, that prerequisite for underwriting is satisfied.

### 3.4. Property Appraisal and Title Search

An `Appraisal` is ordered against the application with a single `report_date` (the date the appraisal report was finalised, in UTC), and enters the lifecycle in `ORDERED`. The system permits at most one `COMPLETED` `Appraisal` whose `valid_until` is greater than `SystemClock.now` per `LoanApplication` at any time; an attempt to order a second when an unexpired completed appraisal exists is rejected with `ERR_APPRAISAL_OVERLAP`.

When the appraisal completes, the loan officer supplies an `appraised_value_cents` (strictly positive). The system advances `status` to `COMPLETED`, computes `valid_until` as `report_date` plus 120 calendar days at 23:59:59.999 UTC, and then re-evaluates the parent application's `ltv_ratio` using the appraised value (see §3.7). If the completed appraisal value falls below the application's `sale_price_cents`, the new `ltv_ratio` may rise above the PMI threshold of 0.80, in which case the system also sets `pmi_required` on the application to true. An appraisal is also rejectable from `ORDERED` to `REJECTED` without further effect. If the system observes during a downstream state-advancing operation that an appraisal's `valid_until` has elapsed (`SystemClock.now` is strictly greater than `valid_until`), it lazily transitions the appraisal from `COMPLETED` to `EXPIRED` — and surfaces `ERR_APPRAISAL_EXPIRED` to the caller of that operation. The appraisal is considered valid for use as long as `SystemClock.now` is no later than `valid_until` (the boundary is inclusive).

A `TitleSearch` is similarly ordered against the application, with no input payload, starting in `ORDERED`. Completing a title search requires a `defects_found` array: if the array is empty, the title search advances to `CLEAR`; if it contains one or more defect descriptions, it advances to `ISSUES_FOUND`. A title search in `ISSUES_FOUND` can subsequently be resolved by the loan officer (typically after the curative work has been performed off-system), at which point `status` becomes `RESOLVED` and the system stamps `resolved_at` with `SystemClock.now`. Underwriting accepts either `CLEAR` or `RESOLVED` as a satisfactory title state.

### 3.5. The Rate Lock and Its Extensions

At any point during origination the loan officer can place a `RateLock` against the application by supplying a `locked_rate_bps` — an interest rate expressed in basis points, strictly positive and not exceeding 2,000 (i.e., 20%). The lock is created in `LOCKED`, with the system stamping `locked_at` to `SystemClock.now`, computing `lock_expires_at` as `locked_at` plus 45 days, and computing `lock_fee_cents` as 25 basis points (0.25%) of the application's `requested_loan_amount_cents`, rounded half-up to whole cents. The system permits at most one active `RateLock` — one whose `status` is `LOCKED` or `EXTENDED` — per `LoanApplication` at any time; attempting to place a second active lock is rejected with `ERR_RATE_LOCK_OVERLAP`. The `extension_fee_paid_cents` and `refund_cents` fields default to zero at creation.

Locks can be extended in tiers. Submitting an extension with an `extra_days` value of 7, 15, or 30 from `LOCKED` first verifies that `SystemClock.now` is no later than the current `lock_expires_at` (i.e., the lock has not yet expired at the moment of the request), and that the parent `LoanApplication.status` is not in `DENIED`, `WITHDRAWN`, or `CLOSED`. On success the system creates a `RateLockExtension` row with its own `rate_lock_id`, the requested `extra_days`, a computed `fee_cents`, and a `granted_at` timestamp; the parent lock's `lock_expires_at` is advanced by the requested number of days; `extension_fee_paid_cents` is incremented by `fee_cents`; and `status` is set to `EXTENDED`. The fee schedule is tiered on `extra_days`: 7 days costs 5 basis points of the `requested_loan_amount_cents`, 15 days costs 10 basis points, and 30 days costs 25 basis points; the raw product is rounded half-up to whole cents. A lock already in `EXTENDED` can be re-extended by the same mechanism (a self-loop on the state), subject to a cumulative cap: the sum of `extra_days` across all `RateLockExtension` rows on this lock must not exceed 60 days; an extension that would breach the cap is rejected with `ERR_EXTENSION_CAP_EXCEEDED`. The system serialises extension requests on the same lock: if two extension requests arrive concurrently, exactly one is granted and the second is rejected with `ERR_EXTENSION_IN_FLIGHT` before any `fee_cents` is computed (first-writer-wins on `RateLockExtension` creation per `rate_lock_id`).

If `SystemClock.now` advances past `lock_expires_at`, the lock is lazily transitioned to `EXPIRED` the next time a state-advancing operation reads it. The lock can also be cancelled — either explicitly by the loan officer, or implicitly when the parent application transitions to `DENIED` or `WITHDRAWN`. Cancellation sets `status` to `CANCELLED` and computes `refund_cents`: if the cancellation happens within 48 hours of `locked_at` (the free-look window — that is, `SystemClock.now` minus `locked_at` is no more than 48 hours), the refund is the sum of `lock_fee_cents` and `extension_fee_paid_cents`; otherwise the refund is zero. Finally, when the application closes, the lock is cascaded to `CONSUMED` (see §3.10).

At clear-to-close and at close, the lock must still be live: `SystemClock.now` must be no later than `lock_expires_at`. A clear-to-close or close attempt against an expired lock is rejected with `ERR_RATE_LOCK_EXPIRED`.

### 3.6. Disclosure Issuance, the TRID Clock, and APR Tolerance

The system issues two kinds of `Disclosure`: a `LOAN_ESTIMATE`, which is the early-stage cost projection, and a `CLOSING_DISCLOSURE`, which is the binding pre-consummation statement. Each issuance is a POST against the application's disclosures collection carrying a `kind`, an `apr_bps` (annual percentage rate in basis points, strictly positive and no greater than 2,500), a `total_loan_costs_cents` figure (the sum of origination, services-borrower-cannot-shop-for, and services-borrower-can-shop-for), and a `total_other_costs_cents` figure (taxes, prepaids, and escrow). The server mints the `version` (the per-application-per-`kind` monotonic integer), stamps `issued_at` to `SystemClock.now`, stamps `waiting_period_started_at` likewise, computes `cash_to_close_cents`, and — for a `CLOSING_DISCLOSURE` — computes `eligible_to_consummate_at`. For a `LOAN_ESTIMATE`, `eligible_to_consummate_at` is null. The initial `LOAN_ESTIMATE` issuance also stamps `trid_clock_started_at` on the parent `LoanApplication`.

**Cash-to-close calculation.** The `cash_to_close_cents` figure is computed in a pinned order so that the rounding behaviour is deterministic. First, the system splits `total_other_costs_cents` into per-line tax components and applies the state tax rate keyed on the borrower's `state_code` — California is 0.50%, New York is 1.25%, Texas is 0.75%, and any other state code uses the default of 1.00%. Each per-line tax amount is rounded half-up to whole cents *individually*, before any summation. The rounded per-line tax components are then summed and added to `total_other_costs_cents` to produce the taxed other-costs total. Next, the system computes the tiered origination fee on the application's `requested_loan_amount_cents`: if the principal is at most $417,000 (41,700,000 cents), the origination fee is 1.00% of the principal; otherwise if the principal is at most $766,000 (76,600,000 cents), the fee is 0.75%; and otherwise the fee is 0.50%. The boundaries are inclusive at the low end of each higher tier — a principal of exactly 41,700,000 cents uses the 1.00% rate, and a principal of exactly 76,600,000 cents uses the 0.75% rate. The origination fee is rounded half-up to whole cents. Finally, `cash_to_close_cents` is computed as `total_loan_costs_cents` plus the taxed other-costs total plus the origination fee minus the principal, and the result is rounded half-up to whole cents. The rounding order is non-negotiable: per-line tax round, then sum, then origination tier, then total. Round-then-sum versus sum-then-round can differ by up to the number of tax lines in cents.

**TRID waiting period.** For a `CLOSING_DISCLOSURE`, the system computes `eligible_to_consummate_at` by advancing `issued_at` forward by exactly 3 business days. A business day is any day whose weekday is Monday through Friday and whose date is not on the static 2026 federal-holiday list: New Year's Day (January 1, 2026), Independence Day observed (July 6, 2026), and Christmas Day (December 25, 2026). Saturdays, Sundays, and listed holidays are skipped without consuming a business-day count; only days that are both weekdays and non-holidays count. The resulting `eligible_to_consummate_at` is anchored at 00:00:00.000 UTC of the third such business day. Consummation is permitted when `SystemClock.now` is greater than or equal to `eligible_to_consummate_at` (the boundary is inclusive). An attempt to clear to close or close before that instant is rejected with `ERR_TRID_WAITING_PERIOD`.

**APR-tolerance re-disclosure.** When a `CLOSING_DISCLOSURE` is issued, the system compares its `apr_bps` to that of the latest `LOAN_ESTIMATE` on file (the most recent non-`VOIDED` `LOAN_ESTIMATE` by `version`, descending). If the absolute difference exceeds 12 basis points (i.e., 0.125%), the system rejects the issuance with `ERR_APR_TOLERANCE_EXCEEDED` and requires a fresh `LOAN_ESTIMATE` to be issued first, after which the CD may be re-attempted. The comparison is strict on the value 12: a delta of exactly 12 is accepted, a delta of 13 or more triggers re-disclosure. Cascading re-disclosure: when a new `LOAN_ESTIMATE` is issued whose `apr_bps` differs from the latest `CLOSING_DISCLOSURE` by more than 12 basis points, any `ACKNOWLEDGED` `CLOSING_DISCLOSURE` on the application is marked `SUPERSEDED` and a fresh CD becomes required.

**Disclosure lifecycle.** A new disclosure begins in `ISSUED`. A borrower can acknowledge a disclosure issued to their own application — the actor's `X-User-ID` must equal the application's `borrower_id` — moving `status` to `ACKNOWLEDGED` and stamping `acknowledged_at` with `SystemClock.now`. Issuing a new disclosure of the same `kind` for the same application supersedes the previous one (in both `ISSUED` and `ACKNOWLEDGED`), setting its `status` to `SUPERSEDED`. When the application transitions to `DENIED`, every non-terminal disclosure is forced to `VOIDED`. Concurrent issuance of two disclosures of the same `kind` for the same application is serialised: exactly one new version persists; the loser receives `ERR_DISCLOSURE_VERSION_CONFLICT`. A separate, related race surfaces if a new `LOAN_ESTIMATE` is issued while a clear-to-close request is being processed: because the TRID eligibility window is read fresh from the latest `CLOSING_DISCLOSURE`, the strict read causes the clear-to-close to fail with `ERR_TRID_WAITING_PERIOD`.

### 3.7. Underwriting: DTI, LTV, and the Submission Gate

Submitting an application to underwriting moves `status` from `PRE_QUALIFIED` to `UNDERWRITING`. The transition is gated on five preconditions: at least one `IncomeVerification` is `VERIFIED` for this application, at least one `AssetVerification` is `VERIFIED`, an `Appraisal` is `COMPLETED`, a `TitleSearch` is either `CLEAR` or `RESOLVED`, and an initial `LOAN_ESTIMATE` `Disclosure` exists in either `ISSUED` or `ACKNOWLEDGED`. If any of the five is missing, the request is rejected with `ERR_MISSING_DEPENDENCIES`. Because submission is a time-advancing step, the appraisal-validity check (`SystemClock.now` no later than the latest completed appraisal's `valid_until`) is also evaluated; a stale appraisal yields `ERR_APPRAISAL_EXPIRED`.

The submission payload carries one input: a `compliance_reviewer_id`, the opaque identifier of the `ComplianceOfficer` who will own the UDAAP review for this application. The supplied value must not equal the application's `assigned_loan_officer_id` — segregation of duties is enforced at this moment of assignment. The system then writes `compliance_reviewer_id` onto the application atomically. If two loan officers attempt to submit the same application concurrently and assign different compliance reviewers, exactly one assignment succeeds and the loser receives `ERR_COMPLIANCE_REVIEWER_CONFLICT` (first-writer-wins on `compliance_reviewer_id`).

Submission also recomputes `dti_ratio` and `ltv_ratio` on the application.

**DTI calculation.** The DTI calculation aggregates verified income and produces a ratio. The system first computes an effective annual income in cents by summing the `documented_annual_cents` of every `IncomeVerification` whose `status` is `VERIFIED` and whose `application_id` matches the application. The system then divides that effective annual figure by 12 to obtain a monthly income figure in cents. A simplified monthly payment is then estimated as the `requested_loan_amount_cents` multiplied by the rate-agnostic constant 0.0065 (a deliberately rough proxy that is intentionally not derived from the actual interest rate). The `dti_ratio` is then this approximate monthly payment divided by the monthly income, rounded half-up to 4 decimal places. The calculation has two variants:

- The **pre-qualification** variant is used at the `INTAKE` → `PRE_QUALIFIED` transition. Because no income verifications have been recorded yet, if the aggregated effective income is zero, the system falls back to the borrower's stated `annual_income_cents`. The variant exists precisely to allow a preliminary DTI to be computed before any verifications are in place.
- The **underwriting** variant is used at the `PRE_QUALIFIED` → `UNDERWRITING` transition and again as a gate at conditional approval. It does *not* fall back to the borrower's stated figure: if no `VERIFIED` `IncomeVerification` rows exist, the calculation fails and the transition is blocked.

**LTV calculation.** The LTV calculation produces `ltv_ratio` as the principal divided by the value basis. The value basis is the minimum of the application's `sale_price_cents` and the latest completed `Appraisal`'s `appraised_value_cents` — the lender treats the lower of contract price and appraised value as the secured value. The principal is the application's `counter_offered_amount_cents` if a counter-offer has been issued (i.e., the field is not null), otherwise the original `requested_loan_amount_cents`. The result is rounded half-up to 4 decimal places. The PMI threshold sits at 0.80: if the final `ltv_ratio` at clear-to-close exceeds 0.80, `pmi_required` becomes true on the application.

### 3.8. The Underwrite Decision

From `UNDERWRITING`, a `LoanOfficer` who is not the assigned `compliance_reviewer_id` issues an underwrite decision via a payload carrying a `decision` field that must be one of `APPROVE`, `COUNTER_OFFER`, or `DENY`. A `counter_offered_amount_cents` is required when the decision is `COUNTER_OFFER` and is otherwise absent.

The `APPROVE` branch advances the application to `CONDITIONAL_APPROVAL`. It requires three additional checks beyond state, role, and SoD: the application's `dti_ratio` must be no greater than 0.43 (else `ERR_DTI_EXCEEDED`), its `ltv_ratio` must be no greater than 0.97 (else `ERR_LTV_EXCEEDED`), and a `UDAAPReview` with `outcome` of `PASS` must exist against the latest `LOAN_ESTIMATE` `version`. On approval the system recomputes `pmi_required` as the truth of `ltv_ratio` strictly greater than 0.80.

The `COUNTER_OFFER` branch routes the application back to `PRE_QUALIFIED` so that the borrower can re-engage with revised terms. The supplied `counter_offered_amount_cents` must be strictly greater than zero and strictly less than `requested_loan_amount_cents`; violations are rejected with `ERR_INVALID_COUNTER_OFFER`. On a successful counter-offer the system stores `counter_offered_amount_cents` on the application and marks the latest `LOAN_ESTIMATE` `Disclosure` as `SUPERSEDED` — the borrower will receive a fresh estimate reflecting the counter terms before underwriting can resume.

The `DENY` branch advances the application to `DENIED`. It accepts any UDAAP outcome on file (or none) — a denial does not depend on a passing UDAAP. The denial cascades: all non-terminal `Disclosure` rows on the application are forced to `VOIDED`, and any `RateLock` in `LOCKED` or `EXTENDED` is cascaded to `CANCELLED` with the full `lock_fee_cents` plus `extension_fee_paid_cents` returned in `refund_cents` (this denial-driven refund is independent of the 48-hour free-look window — denial is treated as the lender's cause, not the borrower's).

### 3.9. UDAAP Review

In parallel with underwriting, the assigned `ComplianceOfficer` performs UDAAP reviews against the application. A UDAAP review is submitted with an `outcome` of `PASS`, `FLAG`, or `BLOCK`, an optional `notes` string (required when the outcome is `FLAG` or `BLOCK`), and the system stamps the review's `reviewer_user_id` from the actor's `X-User-ID`. The submitting actor's `X-User-ID` must equal the application's `compliance_reviewer_id` — this is the inverse of the segregation rule on underwriting: the compliance officer is the only person who may file the review, and they may not also have been the loan officer. The `application_id` is taken from the path.

Conditional approval requires a passing UDAAP on the latest `LOAN_ESTIMATE` version; clear-to-close requires a passing UDAAP on the latest `CLOSING_DISCLOSURE` version. Either gate failing surfaces as `ERR_UDAAP_REVIEW_REQUIRED`.

### 3.10. Clear-to-Close, Closing, and Withdrawal

Once an application is in `CONDITIONAL_APPROVAL`, the loan officer moves it to `CLEAR_TO_CLOSE` after five preconditions are met: a `CLOSING_DISCLOSURE` exists in `ISSUED` or `ACKNOWLEDGED`; `SystemClock.now` is no earlier than that disclosure's `eligible_to_consummate_at` (the TRID 3-business-day waiting period has elapsed); an active `RateLock` exists in `LOCKED` or `EXTENDED` whose `lock_expires_at` is strictly later than `SystemClock.now`; the `TitleSearch` is in `CLEAR` or `RESOLVED`; and a `UDAAPReview` with `outcome` of `PASS` exists on the latest `CLOSING_DISCLOSURE` `version`. On success the system sets `closing_eligible_at` on the application to the current `SystemClock.now`. Segregation of duties applies to clear-to-close in exactly the same way it applies to the underwrite decision: the acting `X-User-ID` must not equal `compliance_reviewer_id`. Failures cascade through the priority ordering described in §2.10, so an SoD violation surfaces as `ERR_UDAAP_SOD_VIOLATION` ahead of the TRID, appraisal, or rate-lock temporal checks; a missing or non-`PASS` UDAAP surfaces as `ERR_UDAAP_REVIEW_REQUIRED` ahead of TRID; and TRID surfaces ahead of appraisal expiry, which surfaces ahead of rate-lock expiry.

Closing the application transitions `status` from `CLEAR_TO_CLOSE` to `CLOSED`. The only precondition specific to this step is that `SystemClock.now` must still be no later than `RateLock.lock_expires_at` — if the lock has aged out since clear-to-close was issued, the close is rejected with `ERR_RATE_LOCK_EXPIRED` and a fresh extension is required. On a successful close the system cascades the `RateLock` to `CONSUMED` and ensures the latest `CLOSING_DISCLOSURE` has been marked `ACKNOWLEDGED` if it was not already.

Withdrawal from `INTAKE`, `PRE_QUALIFIED`, or `UNDERWRITING` is unconditional from the borrower-availability perspective and sets `status` to `WITHDRAWN`. A withdrawal from `PRE_QUALIFIED` or `UNDERWRITING` cascades any `LOCKED` or `EXTENDED` `RateLock` to `CANCELLED` with the standard refund computation: full refund (`lock_fee_cents` plus `extension_fee_paid_cents`) if the cancellation falls within the 48-hour free-look window from `locked_at`, otherwise zero. A withdrawal from `INTAKE` has no rate-lock to cascade, because no lock can have been placed before pre-qualification.

The application's terminal states are `CLOSED`, `DENIED`, and `WITHDRAWN`. No transition leaves any of them.

## 4. Endpoint Definitions

Endpoints that create a wholly new resource — a borrower, a loan application, a verification record, an appraisal order, a title order, a rate lock, a disclosure issuance, or a UDAAP review submission — respond with `201 Created`. Endpoints that modify the state of an existing resource — pre-qualifying, submitting to underwriting, completing or rejecting an appraisal, granting an extension, cancelling a lock, acknowledging a disclosure, advancing the clock, and so on — respond with `200 OK`. Every list endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/borrowers` | Create a Borrower | LoanOfficer, Admin |
| GET | `/borrowers/{id}` | Read a Borrower | LoanOfficer, ComplianceOfficer, Admin, Borrower |
| POST | `/loan-applications` | Create a LoanApplication in INTAKE | LoanOfficer, Admin |
| GET | `/loan-applications/{id}` | Read a LoanApplication | LoanOfficer, ComplianceOfficer, Admin, Borrower |
| GET | `/loan-applications` | List LoanApplications (paginated, filter by status, borrower_id) | LoanOfficer, ComplianceOfficer, Admin |
| POST | `/loan-applications/{id}/pre-qualify` | Transition INTAKE → PRE_QUALIFIED | LoanOfficer |
| POST | `/loan-applications/{id}/submit-underwriting` | Transition PRE_QUALIFIED → UNDERWRITING | LoanOfficer |
| POST | `/loan-applications/{id}/underwrite-decision` | Branching transition from UNDERWRITING to CONDITIONAL_APPROVAL, PRE_QUALIFIED (counter), or DENIED | LoanOfficer |
| POST | `/loan-applications/{id}/clear-to-close` | Transition CONDITIONAL_APPROVAL → CLEAR_TO_CLOSE | LoanOfficer |
| POST | `/loan-applications/{id}/close` | Transition CLEAR_TO_CLOSE → CLOSED | LoanOfficer |
| POST | `/loan-applications/{id}/withdraw` | Voluntary withdrawal from INTAKE, PRE_QUALIFIED, or UNDERWRITING | LoanOfficer |
| POST | `/loan-applications/{id}/income-verifications` | Create an IncomeVerification (PENDING) | LoanOfficer |
| POST | `/loan-applications/{appId}/income-verifications/{id}/verify` | Transition PENDING → VERIFIED | LoanOfficer |
| POST | `/loan-applications/{appId}/income-verifications/{id}/reject` | Transition PENDING → REJECTED | LoanOfficer |
| POST | `/loan-applications/{id}/asset-verifications` | Create an AssetVerification (PENDING) | LoanOfficer |
| POST | `/loan-applications/{appId}/asset-verifications/{id}/verify` | Transition PENDING → VERIFIED | LoanOfficer |
| POST | `/loan-applications/{appId}/asset-verifications/{id}/reject` | Transition PENDING → REJECTED | LoanOfficer |
| POST | `/loan-applications/{id}/appraisal` | Order an Appraisal (status ORDERED) | LoanOfficer |
| POST | `/loan-applications/{id}/appraisal/complete` | Transition ORDERED → COMPLETED with appraised_value_cents | LoanOfficer |
| POST | `/loan-applications/{id}/appraisal/reject` | Transition ORDERED → REJECTED | LoanOfficer |
| POST | `/loan-applications/{id}/title-search` | Order a TitleSearch (status ORDERED) | LoanOfficer |
| POST | `/loan-applications/{id}/title-search/complete` | Transition ORDERED → CLEAR or ISSUES_FOUND based on defects_found | LoanOfficer |
| POST | `/loan-applications/{id}/title-search/resolve` | Transition ISSUES_FOUND → RESOLVED | LoanOfficer |
| POST | `/loan-applications/{id}/rate-lock` | Place a new RateLock (status LOCKED) | LoanOfficer |
| POST | `/loan-applications/{id}/rate-lock/extend` | Extend an active RateLock by 7, 15, or 30 days | LoanOfficer |
| POST | `/loan-applications/{id}/rate-lock/cancel` | Cancel an active RateLock; refund per 48-hour free-look rule | LoanOfficer |
| GET | `/loan-applications/{id}/rate-lock` | Read the current RateLock for the application | LoanOfficer, ComplianceOfficer, Admin, Borrower |
| POST | `/loan-applications/{id}/disclosures` | Issue a Disclosure (LOAN_ESTIMATE or CLOSING_DISCLOSURE) | LoanOfficer |
| POST | `/loan-applications/{appId}/disclosures/{id}/acknowledge` | Borrower acknowledges receipt | Borrower |
| GET | `/loan-applications/{id}/disclosures` | List Disclosures for an application | LoanOfficer, ComplianceOfficer, Admin, Borrower |
| POST | `/loan-applications/{id}/udaap-reviews` | ComplianceOfficer submits a UDAAP review | ComplianceOfficer |
| GET | `/loan-applications/{id}/udaap-reviews` | List UDAAP reviews | ComplianceOfficer, Admin |
| POST | `/_clock/advance` | Advance SystemClock.now to a supplied ISO 8601 instant | Admin |
| GET | `/_clock` | Read SystemClock.now | Admin, LoanOfficer, ComplianceOfficer, Borrower |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_REQUIRED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_UDAAP_SOD_VIOLATION` | 403 Forbidden |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_UDAAP_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_TRID_WAITING_PERIOD` | 409 Conflict |
| `ERR_APPRAISAL_EXPIRED` | 409 Conflict |
| `ERR_RATE_LOCK_EXPIRED` | 409 Conflict |
| `ERR_MISSING_DEPENDENCIES` | 409 Conflict |
| `ERR_APR_TOLERANCE_EXCEEDED` | 409 Conflict |
| `ERR_EXTENSION_CAP_EXCEEDED` | 409 Conflict |
| `ERR_EXTENSION_IN_FLIGHT` | 409 Conflict |
| `ERR_RATE_LOCK_OVERLAP` | 409 Conflict |
| `ERR_APPRAISAL_OVERLAP` | 409 Conflict |
| `ERR_DISCLOSURE_VERSION_CONFLICT` | 409 Conflict |
| `ERR_COMPLIANCE_REVIEWER_CONFLICT` | 409 Conflict |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_DTI_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LTV_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INVALID_COUNTER_OFFER` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
