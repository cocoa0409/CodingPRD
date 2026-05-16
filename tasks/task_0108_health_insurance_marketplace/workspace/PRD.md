# Health Insurance Marketplace API — Product Requirements Document

## 1. Introduction

The Health Insurance Marketplace API is the back-end engine for a HealthCare.gov-style consumer enrollment platform. It guides a household from initial intake (declaring filers, dependents, projected incomes, and the U.S. state of residence) through eligibility determination, plan selection, and a year-long billing relationship with a commercial insurer. Three audiences depend on the same data: the consumer who needs an accurate premium quote before the Open Enrollment Period ends, the marketplace operator who must verify special-enrollment qualifying events and reconcile subsidy estimates against actual income at year-end, and the insurer who lists Bronze, Silver, Gold, and Platinum plans into the catalog.

The business logic is unusually rate-sensitive. The federal Advance Premium Tax Credit (APTC) is anchored to the Second-Lowest-Cost Silver Plan in the household's state for the chosen plan year, and the size of the credit depends on where the household's MAGI sits relative to the Federal Poverty Level (FPL). Small movements in declared income — for example, a household crossing 138% of FPL — flip the Cost-Sharing Reduction tier from CSR Plus to CSR_94, change which Silver variant the consumer is eligible to enroll in, and reshape the monthly bill. Because catalog premiums, FPL tables, and the household's income statement all shift over a coverage year, the system must distinguish the *forward-looking* estimated APTC pinned at eligibility-determination time from the *reconciled* APTC produced by year-end replay of the income ledger.

A second class of complexity comes from time itself. Most enrollments may only happen during the Open Enrollment Period, but a verified Special Enrollment Period (SEP) opens a 60-day window for households experiencing a qualifying life event (marriage, loss of coverage, the birth or adoption of a child, a move, an income change, the loss of Medicaid, or gaining U.S. citizenship). To make these date-gated rules testable, the API exposes a logical clock that operators may advance, so SEP windows can open and close, monthly invoices can age into delinquency, and the 90-day non-payment grace period can elapse.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers identifying the caller: `X-User-ID` and `X-User-Role`. A request that omits either header is rejected with `ERR_AUTH_REQUIRED`; a request whose `X-User-Role` is not authorized for the operation (per the §4 endpoint table) is rejected with `ERR_FORBIDDEN`.

Four roles exist in the system, and they must be spelled exactly as follows: `Applicant`, `MarketplaceAdmin`, `Insurer`, and `CustomerService`.

- When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque consumer identifier not tied to any persisted entity. The server records it on every `Application` the caller creates (as `applicant_id`), and ownership checks on `Application`-scoped writes compare the resource's `applicant_id` to `X-User-ID`. A mismatch is rejected with `ERR_NOT_APPLICATION_OWNER`.
- When `X-User-Role` is `MarketplaceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.
- When `X-User-Role` is `Insurer`, `X-User-ID` is the `id` of the acting `Insurer` row; ownership checks on plan-management operations compare the target `Plan.insurer_id` to `X-User-ID`.
- When `X-User-Role` is `CustomerService`, `X-User-ID` is an opaque support-operator identifier not tied to any persisted entity. The server may record it (for example, as an internal audit field) but does not compare it to any entity's `id`.

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

All list endpoints accept `limit` and `offset` query parameters. The default `limit` is 10 results per page, the minimum is 1, and the maximum is 100; a request that asks for more than 100 results is bounded back to 100. The default `offset` is 0. Results are ordered by `created_at` ascending unless an endpoint documents a different ordering (for instance, `GET /enrollments/{id}/premium-invoices` orders by `billing_month` ascending, then `id` ascending). The response `meta` object echoes the effective `limit` and `offset`, the unfiltered `total_count`, and a boolean `has_more` indicating whether further pages exist.

### 2.4. Common Resource Properties and Resource Lifecycle Fields

Every persisted resource carries an `id` which is a server-minted UUID with no type prefix (the type is determined by URL position, not by the identifier), and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Resources whose data evolves after creation — `Application`, `HouseholdMember`, `Plan`, `SEPEvent`, `Enrollment` — also carry an `updated_at` timestamp (same format) and an integer `version` field that begins at 1 and increments by exactly 1 on every successful mutation. Append-only resources — `IncomeRecord`, `Insurer`, `PlanVariant`, `PremiumInvoice` — carry only `id` and `created_at`; they have no `updated_at` field and no `version` field, because corrections are made by writing a new row rather than mutating an existing one. (For `IncomeRecord` this is what `superseded_by_id` records.)

The denormalized rollup fields on `Application` — `household_size`, `total_magi_cents`, `fpl_percentage`, `csr_eligibility`, `aptc_estimated_cents` — are not separately authored; they are recomputed by the server every time their inputs change and exposed in the `GET /applications/{id}` response. The `aptc_reconciled_cents` field starts as null and is populated only by the year-end reconciliation sweep.

### 2.5. Nested Resource Resolution

Several endpoints address resources by nested path — for instance, an income line under a household member under an application, or a SEP event under an application. Path parameters are validated left to right. Given a URL of the form `/applications/{id}/household-members/{member_id}/income-records`, the server first resolves the application `id`; if that fails, the response is `ERR_NOT_FOUND` and the inner `member_id` is never inspected. Once both ancestors resolve, the server confirms that the named `member_id` actually belongs to that application; a member belonging to a different application is reported as `ERR_NOT_FOUND` (the absence is from the perspective of the requested parent), not as a permission error.

### 2.6. Optimistic Concurrency Control

Mutating endpoints that target a versioned resource (e.g., the `PATCH` endpoints under `/applications/{id}/household-members/{member_id}` and `/plans/{id}`) accept an optional `version` field in the request body. When the caller supplies `version`, the server compares it to the stored `version` of the resource; if they differ, the request is rejected with `ERR_STALE_VERSION` and no mutation is applied. When the caller omits `version`, the optimistic concurrency check is skipped and the server proceeds with last-writer-wins semantics. Every successful mutation increments `version` by exactly 1 and refreshes `updated_at` to the current logical-clock time.

### 2.7. Precision, Rounding, and Currency

All monetary fields are integer cents (`base_monthly_premium_cents`, `monthly_premium_gross_cents`, `monthly_aptc_applied_cents`, `monthly_net_premium_cents`, `gross_amount_cents`, `aptc_amount_cents`, `net_amount_cents`, `amount_cents`, `out_of_pocket_max_cents`, `aptc_estimated_cents`, `aptc_reconciled_cents`, `total_magi_cents`, `member_magi_cents`); the API never accepts or returns fractional cents. The rounding mode throughout the system is half-up: a value whose fractional part equals exactly one half is rounded toward the larger magnitude. The `fpl_percentage` field is a number expressed to one decimal place, also rounded half-up; threshold comparisons against `fpl_percentage` are made at that one-decimal precision, so a value of 149.9 sits below the 150.0 boundary while 150.0 sits on it.

### 2.8. Version Pinning Against Catalog Drift

The plan catalog evolves continuously — insurers raise base premiums, withdraw products, and shift the benchmark Silver designation between coverage years. To prevent these post-hoc edits from retroactively changing a consumer's bill, two version snapshots are taken at decisive moments. When an application moves into the SUBMITTED state, the current FPL constants table is snapshotted onto `Application.pinned_fpl_table_version`; subsequent FPL-table revisions do not change the household's `fpl_percentage` until the application is amended back to draft. When an enrollment is created, the parent `Plan.catalog_version` at the moment of write is snapshotted onto `Enrollment.pinned_plan_catalog_version`; the insurer may continue to raise `base_monthly_premium_cents` afterward, and `Plan.catalog_version` will increment on each such change, but the existing enrollment retains its pinned version and its monthly bill until the application is redetermined.

### 2.9. Logical Clock

All "now" comparisons consult a server-managed logical clock rather than wall-clock time. The default clock value follows real time, but a marketplace operator may advance the clock to a fixed ISO 8601 timestamp through an admin-only test-driving capability that accepts a `to_timestamp` input. Advancing the clock cascades two side effects: every SEPEvent whose `window_closes_on` has passed and which is still in `VERIFIED` without an enrollment is transitioned to `EXPIRED`, and every active or grace-period enrollment has its payment-status rollup re-evaluated against the new logical present.

### 2.10. Cascade Semantics on Hierarchical Mutations

Many state transitions in this system fan out across multiple aggregates. Whenever a redetermination recomputes an application's eligibility, and the application has an active enrollment, the cascade walks three levels deep: the application's `fpl_percentage`, `csr_eligibility`, and `aptc_estimated_cents` are recomputed; the enrollment's `monthly_premium_gross_cents`, `monthly_aptc_applied_cents`, and `monthly_net_premium_cents` are recomputed; and a fresh premium invoice is issued for the next `billing_month`. Whenever an enrollment is cancelled by the applicant, the cascade walks two levels deep: the `coverage_end_date` is fixed at the last day of the current billing month, and every premium invoice whose `billing_month` lies strictly after the `coverage_end_date` is transitioned to `VOIDED`. Every cascade also bumps `updated_at` and `version` on each mutated row.

## 3. Business Logic & Workflows

### 3.1. Application Intake and Household Composition

An applicant begins by creating an application, supplying the `coverage_year` for which coverage is sought and the two-letter `filing_state` where the household resides. The system creates the application in `DRAFT` status, assigns the calling user's identifier to `applicant_id`, and records the creation time. The same applicant may not hold two non-terminal applications for the same coverage year; a second draft for an already-active coverage year is rejected.

While the application sits in `DRAFT`, the applicant builds out the household by adding members one at a time. Each `HouseholdMember` declares its `filer_type` (one of `PRIMARY_FILER`, `SPOUSE`, or `DEPENDENT`), its `date_of_birth` as an ISO 8601 calendar date, and two boolean flags that default to true: `include_in_household` controls whether the member counts toward `household_size`, and `include_in_magi` controls whether the member's income lines flow into the household's MAGI sum. A third boolean, `is_tobacco_user`, defaults to false and declares whether the member uses tobacco — relevant later for premium calculation. A dependent whose `date_of_birth` implies an age of 26 years or more at the start of the coverage year is rejected with `ERR_DEPENDENT_AGE_INVALID`. Exactly one member per application may carry `filer_type` of `PRIMARY_FILER`; submitting an application with zero or with two or more primary filers is rejected with `ERR_MISSING_PRIMARY_FILER`. While the application remains in `DRAFT`, members other than the `PRIMARY_FILER` may be deleted; the primary filer may not.

Each `HouseholdMember` carries its own append-only ledger of income lines. An `IncomeRecord` declares a `source_type` (one of `WAGES`, `SELF_EMPLOYMENT`, `SOCIAL_SECURITY`, `INTEREST_DIVIDEND`, `RETIREMENT`, `RENTAL`, or `OTHER`), an `amount_cents` (which may be negative to represent a business loss), and the `effective_date` from which the line applies. Corrections are made by writing a new income record whose `supersedes_id` input points to the prior row; the server then sets the prior row's `superseded_by_id` to the new row's `id`, so chronological replay can later tell which line was authoritative at any given moment. Per-member sums are accumulated into `member_magi_cents`, and the household-level `total_magi_cents` rolls those up across members whose `include_in_magi` flag is true; the household-level sum has a floor of zero, and any attempt to submit *or* redetermine an application whose household sum would otherwise be negative is rejected with `ERR_MAGI_NEGATIVE`. The `member_id` path parameter of the income-records endpoint must resolve to a member of the named application; mismatches surface as `ERR_NOT_FOUND`.

### 3.2. Submitting the Application and Anchoring the FPL Calculation

Submitting the application by the applicant transitions it from `DRAFT` to `SUBMITTED`. Three preconditions guard the transition: the application must have exactly one `PRIMARY_FILER` (otherwise `ERR_MISSING_PRIMARY_FILER`); every member whose `include_in_magi` is true must have at least one `IncomeRecord` on file; and the application's `coverage_year` must equal the current year or the current year plus one as measured by the logical clock (otherwise `ERR_COVERAGE_YEAR_INVALID`). When the transition succeeds, the server stamps `submitted_at`, snapshots the FPL constants table identifier into `pinned_fpl_table_version`, and computes the three rollup fields whose downstream eligibility depends on them: `household_size`, `total_magi_cents`, and `fpl_percentage`.

`household_size` is the count of `HouseholdMember` rows for the application where `include_in_household` is true. `total_magi_cents` is the sum of `IncomeRecord.amount_cents` across all rows that belong to members whose `include_in_magi` is true and whose `superseded_by_id` is still null (i.e., un-superseded). The FPL denominator is read from the pinned FPL table at the row for the household's size. For coverage year 2025 (version `v1`), those denominators are 1,525,500 cents at household size 1, 2,067,500 cents at size 2, 2,609,500 cents at size 3, 3,151,500 cents at size 4, 3,693,500 cents at size 5, and 4,235,500 cents at size 6, with each additional member beyond six adding 542,000 cents to the denominator. For coverage year 2026 (version `v2`), the corresponding denominators are 1,572,500 cents, 2,131,000 cents, 2,689,500 cents, 3,248,000 cents, 3,806,500 cents, and 4,365,000 cents, with each additional member beyond six adding 558,500 cents. The `fpl_percentage` field is then the household's MAGI divided by that denominator, multiplied by 100, and rounded half-up to one decimal place.

While an application sits in `SUBMITTED`, the applicant may revert it back to `DRAFT` by amending it; this clears `submitted_at`, `pinned_fpl_table_version`, `fpl_percentage`, and `total_magi_cents` (all set back to null) so that the household composition or income statement can be edited without contradiction. After an application has progressed past `SUBMITTED`, amendments are no longer available; corrections then require either a verified SEP or an admin-initiated redetermination.

### 3.3. Eligibility Determination — CSR Tiers, Medicaid, and the APTC Anchor

A marketplace operator advances a submitted application to `ELIGIBILITY_DETERMINED`. This is the moment at which three derived facts are pinned to the application: the household's cost-sharing reduction tier, each member's individual Medicaid eligibility, and the household's estimated annual APTC subsidy.

The CSR tier is read from a step function over `fpl_percentage`, with every band evaluated at one-decimal precision and using half-open intervals. A household whose `fpl_percentage` is strictly below 100.0 lies in Medicaid territory; its `csr_eligibility` is set to `NONE`, since the household ought to be served by Medicaid rather than by a Silver variant. A household at or above 100.0 and strictly below 138.0 is assigned `CSR_PLUS`, the very-low-income tier whose Silver variants carry an actuarial value of 97. A household at or above 138.0 and strictly below 150.0 is `CSR_94`; at or above 150.0 and strictly below 200.0 it is `CSR_87`; at or above 200.0 and strictly below 250.0 it is `CSR_73`. A household at or above 250.0 receives no CSR and `csr_eligibility` is `NONE`. Only Silver-tier `PlanVariant` rows honor these tiers; Bronze, Gold, and Platinum plans ignore the CSR field.

For each `HouseholdMember`, the server independently decides whether the member is itself eligible for Medicaid coverage outside the marketplace, writing the result to the member's `medicaid_eligible` flag. The member's age at the start of the coverage year is the gating fact, combined with the parent application's `filing_state` Medicaid-expansion status. A member under age 19 is Medicaid-eligible whenever the household-level `fpl_percentage` is strictly below 200.0, regardless of state expansion. A member of age 65 or older is treated as Medicare territory and is not Medicaid-eligible through the marketplace under any circumstance. An adult member (age 19 through 64 inclusive) is Medicaid-eligible if the household-level `fpl_percentage` is strictly below 138.0 when the filing state has expanded Medicaid (for example, CA, NY, and WA in the canonical reference table), and is Medicaid-eligible only when the household-level `fpl_percentage` is strictly below 50.0 when the filing state has not expanded Medicaid (for example, TX, FL, and GA in the canonical reference table). All 51 jurisdictions (the 50 states plus DC) carry an expansion flag in the system reference table.

The estimated APTC is forward-looking: it uses the current `total_magi_cents` and the current `household_size` at the moment of determination, and it ignores any later income mutations within the coverage year. First, the server looks up the household's applicable contribution percentage from a step function over `fpl_percentage`, again using half-open intervals at one-decimal precision: a percentage at or above 100.0 and strictly below 150.0 contributes 0.0% of MAGI (the applicable fraction is 0.0000); at or above 150.0 and strictly below 200.0, 2.0% (0.0200); at or above 200.0 and strictly below 250.0, 4.0% (0.0400); at or above 250.0 and strictly below 300.0, 6.0% (0.0600); at or above 300.0 and strictly below 400.0, 8.5% (0.0850); at or above 400.0 the applicable fraction is 1.0000, which collapses the APTC formula and means no subsidy is available. Households whose `fpl_percentage` is below 100.0 are redirected to the Medicaid evaluation above and their `aptc_estimated_cents` is set to zero. The expected annual household contribution in cents is then `total_magi_cents` multiplied by the applicable fraction, rounded half-up to the nearest cent. Second, the server locates the benchmark Silver plan for the household's `filing_state` and `coverage_year` — that is, the active `Plan` whose `is_benchmark_silver` flag is true, of which the catalog must contain exactly one per `(filing_state, coverage_year)` pair (if zero exist, eligibility determination is rejected with `ERR_NO_BENCHMARK_PLAN`). Third, the server computes the age-adjusted annual premium of that benchmark plan for the included household (see §3.6 for the age curve and tobacco surcharge construction). The estimated APTC, in cents, is the larger of zero and the annual benchmark premium minus the expected household contribution; the result is written into `aptc_estimated_cents`.

After the determination, the operator decides whether to approve or deny. Approval moves the application from `ELIGIBILITY_DETERMINED` to `APPROVED`, provided the application's `enrollment_window` is either `OEP` or `SEP` (not `CLOSED`) and at least one included member is *not* Medicaid-eligible; an attempt to approve a household every included member of which is Medicaid-eligible falls to the denial branch instead. Denial moves the application from `ELIGIBILITY_DETERMINED` to `DENIED` when either every included member is Medicaid-eligible or the `enrollment_window` is `CLOSED`. Denial accepts an optional `reason` to be recorded for audit purposes. The two branches are mirror images: where approval requires "at least one included member with `medicaid_eligible` false AND the window is open", denial requires the contrapositive ("every included member has `medicaid_eligible` true OR the window is closed"). `DENIED` is a terminal state. The `approved_at` timestamp is stamped when the approval transition fires.

### 3.4. Special Enrollment Periods, Effective Dates, and Window Arithmetic

Outside the Open Enrollment Period, an applicant may file a Special Enrollment Period claim under the application by submitting an `event_type` from the enumerated set `{LOSS_OF_COVERAGE, MARRIAGE, BIRTH_ADOPTION, MOVE, INCOME_CHANGE, MEDICAID_LOSS, GAINED_CITIZENSHIP}` together with the calendar `event_date` on which the qualifying event occurred. The SEPEvent is created in `SUBMITTED` state with `reported_at` stamped to the current logical-clock time. A marketplace operator then either verifies or rejects the claim. Verification requires that the `event_date` lie within 60 calendar days of the logical-clock present; an event whose `event_date` is more than 60 days in the past is rejected with `ERR_SEP_WINDOW_EXPIRED` at the verify step, and a verify call against an application whose `status` is `DENIED` (or any non-allowed state outside `{SUBMITTED, ELIGIBILITY_DETERMINED, APPROVED}`) is rejected with `ERR_INVALID_STATE`. Rejection records an optional `reason`; if the applicant believes the rejection was in error, a customer-service operator may appeal the rejected event back to `SUBMITTED`, provided the appeal is filed within 30 calendar days of the rejection.

When a SEPEvent is verified, the server computes three derived dates: `window_opens_on`, `window_closes_on`, and `effective_date`. The arithmetic varies by `event_type`. For `BIRTH_ADOPTION` and `MARRIAGE`, the effective date is retroactive to the qualifying event itself: `window_opens_on` equals `event_date` and `effective_date` equals `event_date`. For `LOSS_OF_COVERAGE` and `MEDICAID_LOSS`, the effective date is forward-looking: `window_opens_on` equals `event_date`, and `effective_date` equals the first day of the calendar month after the month containing `reported_at`. For `MOVE`, the window opens on `event_date`; the effective date is the first day of the calendar month after the month containing `reported_at`, except that if the report arrived more than 60 days after the move occurred, the effective date is instead capped at the first day of the month following the day exactly 60 days after `event_date`. For `INCOME_CHANGE`, the window opens on the first day of the calendar month after the month containing `reported_at`, and the effective date is also the first day of the calendar month after the month containing `reported_at`. For `GAINED_CITIZENSHIP`, `window_opens_on` equals `event_date` and `effective_date` equals the first day of the calendar month after the month containing `reported_at`. In every case, `window_closes_on` is exactly 60 calendar days after `window_opens_on`, and all date comparisons use strict-greater-than on month boundaries (e.g., "first day of the month after" means the next month even if `reported_at` itself lies on the first of its month).

Verification has two further side effects. It sets the parent application's `enrollment_window` to `SEP`. And when the qualifying event is `MARRIAGE`, `BIRTH_ADOPTION`, or `MEDICAID_LOSS`, and the parent application is already `APPROVED` with an active enrollment in place, the verification triggers a three-level cascade: the application is force-redetermined (reverting `APPROVED` to `ELIGIBILITY_DETERMINED` and recomputing `fpl_percentage`, `csr_eligibility`, and `aptc_estimated_cents`), the enrollment's monthly premium is recomputed, and a fresh premium invoice is issued for the next `billing_month`. Verifications of other event types do not force this cascade — the applicant is expected to amend the household or income statement explicitly if their facts have changed.

A verified SEPEvent transitions to `EXPIRED` when the logical clock advances past `window_closes_on` without an enrollment having been created during the window. If, at expiration time, the application has no other verified SEP whose window is still open and the application is not inside the OEP, the application's `enrollment_window` is set to `CLOSED`. Both `REJECTED` and `EXPIRED` are terminal states for the SEPEvent state machine.

When multiple SEPEvents under the same application race for governance of an enrollment's effective date, both verifications may succeed, but the application's `enrollment_window` remains `SEP` and only one SEP's `effective_date` governs the next enrollment. The earliest verified event — broken on `reported_at` ascending — wins. A later verification does not override an earlier one that is already governing an enrollment; an attempt by the system to apply a later SEP to an enrollment that an earlier one already anchors raises `ERR_SEP_CONFLICT`.

### 3.5. The Insurer Catalog: Insurers, Plans, and CSR Variants

The catalog is administered by `Insurer` and `MarketplaceAdmin` actors. An `Insurer` row is created with a `name`, a list of two-letter state codes in `filing_states` where the issuer offers products, and a `contact_phone` for customer service. A `Plan` belongs to an insurer (`insurer_id`), is offered for a single `coverage_year` in a single `filing_state` that must appear in the parent insurer's `filing_states` list, sits in one of the four metal tiers via `tier` (`BRONZE`, `SILVER`, `GOLD`, or `PLATINUM`), and carries a `base_monthly_premium_cents` representing the catalog premium for a reference adult age 21 before any age curve, tobacco surcharge, or APTC reduction. Each plan also carries an `is_benchmark_silver` flag — defaulting to false — that designates it as the Second-Lowest-Cost Silver Plan (SLCSP) for its state and year. The flag may be set true on at most one plan per `(filing_state, coverage_year)` combination; an attempt to set it true while another active plan already holds it is rejected with `ERR_BENCHMARK_CONFLICT`. A plan's lifecycle `status` is `ACTIVE` by default and may move to `WITHDRAWN`; withdrawn plans may not anchor new enrollments, but existing enrollments survive via the version-pinning rule in §2.8. Each plan also carries a `catalog_version` integer that increments every time `base_monthly_premium_cents` or `status` changes, providing the value pinned onto enrollments at creation.

A `PlanVariant` is the CSR overlay attached to a Silver-tier plan via `plan_id`; only Silver plans may carry variants. Each variant declares a `csr_level` from the enumeration `{STANDARD, CSR_73, CSR_87, CSR_94, CSR_PLUS}`, an `actuarial_value` (for example, 73 for `CSR_73`, 94 for `CSR_94`, and 97 for `CSR_PLUS`), and an `out_of_pocket_max_cents` cap. The `STANDARD` variant is the default and serves all Silver enrollments where the application's `csr_eligibility` is `NONE`. Variants are immutable once created; new variants are added by creating new rows.

When an insurer raises a plan's `base_monthly_premium_cents` or withdraws a plan while an applicant is mid-flight in writing an enrollment that names the same plan, both writes succeed: the insurer's update is recorded with the new `catalog_version`, and the in-flight enrollment snapshots the `catalog_version` that existed at the moment the enrollment write committed. If the insurer's plan-update request carries a stale `version` field in its body, however, the update itself is rejected with `ERR_STALE_VERSION`.

### 3.6. Enrollment, Premium Construction, and the Binder Payment

Once an application is `APPROVED`, the applicant binds it to a chosen plan variant by submitting an enrollment that names both the parent `application_id` and the chosen `plan_variant_id`. The system imposes a series of preconditions in priority order. The application must be the requester's own (otherwise `ERR_NOT_APPLICATION_OWNER`). The application's `enrollment_window` must be `OEP` or `SEP` rather than `CLOSED` (otherwise `ERR_OUTSIDE_ENROLLMENT_WINDOW`). The named `plan_variant_id` must resolve to a plan whose `filing_state` matches the application's `filing_state` and whose `coverage_year` matches the application's `coverage_year` (otherwise `ERR_PLAN_STATE_MISMATCH`). The variant's `csr_level` must align with the application's `csr_eligibility` — `STANDARD` when the household qualifies for no CSR (`csr_eligibility` is `NONE`), otherwise an exact match between `csr_level` and `csr_eligibility` (otherwise `ERR_CSR_VARIANT_MISMATCH`). The derived `coverage_start_date` must fall inside an open SEP window or the OEP window for the coverage year (otherwise `ERR_OUTSIDE_SEP_WINDOW`). And at most one enrollment may exist per `(application_id, coverage_year)` pair; a second concurrent submission is rejected with `ERR_ENROLLMENT_ALREADY_EXISTS`.

When enrollment creation succeeds, the server snapshots `Plan.catalog_version` into `pinned_plan_catalog_version` and derives the `coverage_start_date`. If the application is enrolling under a verified SEP, the start date is the governing SEP's `effective_date`; if the application is enrolling under the OEP, the start date is January 1 of the application's `coverage_year`. The enrollment is created in the parallel posture `coverage_status` = `PENDING_PAYMENT` and `payment_status` = `AWAITING_BINDER`, with `coverage_end_date` left null and `terminated_reason` left null. The first premium invoice is issued automatically as part of this same write.

Monthly premium construction follows a tiered age curve, with the rounding order pinned: per-member rounding to a whole cent happens first, then the rounded per-member amounts are summed. For each member where `include_in_household` is true, the server computes the member's age in years between their `date_of_birth` and the enrollment's `coverage_start_date`, then maps the age to a bracket multiplier from the age-curve table — 0.765 for ages 0 through 14, 0.833 for ages 15 through 20, 1.000 for ages 21 through 24, 1.061 for ages 25 through 29, 1.150 for ages 30 through 34, 1.181 for ages 35 through 39, 1.278 for ages 40 through 44, 1.444 for ages 45 through 49, 1.706 for ages 50 through 54, 2.040 for ages 55 through 59, 2.411 for ages 60 through 63, and 3.000 for ages 64 and above. The plan's `base_monthly_premium_cents` is multiplied by that age multiplier and rounded half-up to a whole cent. If the member is a tobacco user (`is_tobacco_user` is true) and their age at `coverage_start_date` is at least 21, the per-member amount is multiplied by the tobacco surcharge factor of 1.50 and rounded half-up to a whole cent a second time. Summing these rounded per-member amounts yields `monthly_premium_gross_cents`. The monthly APTC applied is the lesser of the annual `aptc_estimated_cents` divided by 12 (rounded half-up to a whole cent) and `monthly_premium_gross_cents`; it has a floor of zero and a ceiling at the gross premium, and is written to `monthly_aptc_applied_cents`. The consumer's monthly bill, `monthly_net_premium_cents`, is `monthly_premium_gross_cents` minus `monthly_aptc_applied_cents`.

The first invoice issued at enrollment time is the binder invoice. It carries the enrollment's `billing_month`, snapshots `monthly_premium_gross_cents` into `gross_amount_cents`, snapshots `monthly_aptc_applied_cents` into `aptc_amount_cents`, sets `net_amount_cents` to the difference, and sets `due_date` to the first day of the `billing_month`. When the binder invoice is paid and the logical clock has reached or passed `coverage_start_date`, the enrollment auto-promotes from `PENDING_PAYMENT` to `ACTIVE`. Specifically, when the binder is posted, `payment_status` flips from `AWAITING_BINDER` to `CURRENT`; combined with the date precondition, this triggers the transition that sets `coverage_status` to `ACTIVE`.

### 3.7. Billing, Payment Rollups, Grace Period, and Termination

Every billing month the enrollment issues a `PremiumInvoice` whose `enrollment_id` foreign-key points back to its parent enrollment. Each invoice begins in `ISSUED` state with `paid_at` null. When a payment of `amount_cents` is posted to the invoice, the system requires `amount_cents` to be at least `net_amount_cents` (otherwise `ERR_PAYMENT_INSUFFICIENT`); on success, `status` flips to `PAID` and `paid_at` is stamped to the current logical-clock time. An invoice whose `status` is no longer `ISSUED` at the moment of posting is rejected with `ERR_INVOICE_ALREADY_PAID` — this is the loser of a race between two simultaneous post-payment requests for the same invoice. A customer-service operator may instead waive an issued invoice (`ISSUED` to `WAIVED`) when the invoice's `net_amount_cents` equals zero (fully subsidized) or when documented hardship is on file; a waive accepts an optional `reason` and is treated as PAID for purposes of the payment rollup.

The payment rollup walks the enrollment's invoices in `billing_month` ascending order, breaking ties by `id` ascending, skipping any whose `status` is `VOIDED`. The server identifies the oldest invoice still in `ISSUED` state whose `due_date` has reached or passed the logical-clock present; this is the "oldest unpaid". If no such invoice exists, `payment_status` is `CURRENT`. If one exists, the server computes the days overdue as the logical-clock present minus a 30-day grace-start anchor (the first day of the oldest unpaid month plus 30 days). When the days overdue is zero or negative the enrollment is still inside the 30-day grace and `payment_status` remains `CURRENT`; when it is between 1 and 30 inclusive, `payment_status` becomes `DELINQUENT_M1`; between 31 and 60 inclusive, `DELINQUENT_M2`; and between 61 and 90 inclusive, `DELINQUENT_M3`. Day 91 of non-payment triggers termination. All day comparisons use UTC calendar days, inclusive at the lower bound and exclusive at the upper bound of each bucket.

The corresponding `coverage_status` machine evolves in lock-step with these payment-status transitions. When an active enrollment's payment status flips to `DELINQUENT_M1`, the coverage status moves from `ACTIVE` to `GRACE_PERIOD`. Bringing every open invoice (every invoice whose `due_date` has reached or passed the logical-clock present and is still `ISSUED`) back to `PAID` brings the enrollment from `GRACE_PERIOD` to `ACTIVE` and the payment status back to `CURRENT`. If the grace period continues to age and the payment status reaches `DELINQUENT_M3`, with the last paid invoice's `due_date` now more than 90 days in the past, the enrollment moves from `GRACE_PERIOD` to `TERMINATED` with `terminated_reason` set to `NON_PAYMENT`, `coverage_end_date` set to the last day of the last paid invoice's `billing_month`, and `payment_status` retained for audit. The parent application stays in `APPROVED` — terminated enrollments are kept for historical record.

An applicant who has been `ACTIVE` may voluntarily cancel coverage. This moves the enrollment to `TERMINATED` with `terminated_reason` set to `APPLICANT_CANCELLED`, the `coverage_end_date` set to the last day of the current billing month per the logical clock, and a depth-2 cascade that transitions every premium invoice whose `billing_month` lies strictly after `coverage_end_date` from `ISSUED` to `VOIDED`. Voided invoices are skipped by the payment-status rollup and are not redelivered to the consumer.

### 3.8. Year-End Reconciliation: Estimated vs Reconciled APTC

At year-end, the marketplace runs a reconciliation sweep against every approved application for the specified `coverage_year`. The sweep replays each application's `IncomeRecord` ledger chronologically, month by month, and produces `aptc_reconciled_cents` — the reconciled annual subsidy the household actually qualified for after all income shifts are taken into account. For each month in the coverage year, the server reconstructs `total_magi_cents` by summing the income records whose `effective_date` is on or before the first day of that month and which are still effective at that moment — that is, either `superseded_by_id` is null or the superseding record's own `effective_date` falls strictly after the first day of that month. The applicable percentage step function (§3.3) is then evaluated against the month's `fpl_percentage`, the month's allowed APTC is computed against the benchmark Silver plan, and the twelve monthly subsidies are summed to produce the reconciled annual figure.

The estimated and reconciled figures can legitimately diverge when corrective `IncomeRecord` rows arrive in mid-year. The estimated `aptc_estimated_cents` was pinned at the moment of eligibility determination using the household's then-current running totals; once a correction is posted, the estimated value at that moment of post-submission re-determination would see the corrective record. The reconciled value, by contrast, time-slices the ledger so the corrective record only affects the months on or after its `effective_date`. Both figures are kept on the application: `aptc_estimated_cents` (forward-looking, pinned, written at `ELIGIBILITY_DETERMINED`) and `aptc_reconciled_cents` (chronological replay, written by the sweep), with the latter remaining null until the sweep has run for that coverage year.

### 3.9. Cross-Cutting Validation Priorities and Concurrency Outcomes

When a request fails multiple checks at once, the rejection follows a fixed priority so that the failure mode the client sees is deterministic. Authentication is checked first — a request missing `X-User-ID` or `X-User-Role` is rejected with `ERR_AUTH_REQUIRED` before role authorization is consulted, and a request whose role is not authorized for the operation is rejected with `ERR_FORBIDDEN` before any path parameter is dereferenced. Path-parameter existence is checked next, left-to-right, and an unresolved id raises `ERR_NOT_FOUND` before any business rule fires. Applicant-ownership (`ERR_NOT_APPLICATION_OWNER`) is checked after existence and before state. State machine eligibility (`ERR_INVALID_STATE`) is checked next, before business preconditions on the request body. The business-constraint family follows, ordered as: a missing or duplicate primary filer at submit (`ERR_MISSING_PRIMARY_FILER`); an invalid `coverage_year` at submit (`ERR_COVERAGE_YEAR_INVALID`); a closed enrollment window at approve or enroll (`ERR_OUTSIDE_ENROLLMENT_WINDOW`); the cross-application plan mismatch (`ERR_PLAN_STATE_MISMATCH`); CSR variant mismatch (`ERR_CSR_VARIANT_MISMATCH`); enrollment coverage start outside any valid window (`ERR_OUTSIDE_SEP_WINDOW`); a household-level negative MAGI (`ERR_MAGI_NEGATIVE`); a missing benchmark Silver plan at determination time (`ERR_NO_BENCHMARK_PLAN`); the uniqueness constraint at enrollment (`ERR_ENROLLMENT_ALREADY_EXISTS`); insufficient payment amount (`ERR_PAYMENT_INSUFFICIENT`); the benchmark-flag conflict (`ERR_BENCHMARK_CONFLICT`); and the SEP-event verification age (`ERR_SEP_WINDOW_EXPIRED`). The optimistic concurrency check (`ERR_STALE_VERSION`) is evaluated last of the business checks, immediately before mutation. The dependent-age guard at member creation (`ERR_DEPENDENT_AGE_INVALID`) is enforced at the member-add endpoint as a body-validation check.

Five concurrency scenarios deserve explicit serialization guarantees:

- **Two operators race to approve and deny the same application.** Exactly one transition wins on `Application.status` first-writer-wins. The loser sees `ERR_INVALID_STATE` because the application has already left `ELIGIBILITY_DETERMINED`.
- **The applicant submits two enrollments under the same application and coverage year concurrently.** A uniqueness constraint on the `(application_id, coverage_year)` pair admits exactly one writer. The loser is rejected with `ERR_ENROLLMENT_ALREADY_EXISTS`.
- **An insurer raises `base_monthly_premium_cents` while the applicant is mid-enrollment against the same plan.** The enrollment pins the `catalog_version` that existed when the enrollment write committed. The insurer's update succeeds and does not affect the in-flight enrollment — *unless* the insurer's plan-update request carries a stale `version` body, in which case the patch itself loses and the loser sees `ERR_STALE_VERSION`.
- **Two post-payment requests race on the same invoice.** First-writer-wins on `PremiumInvoice.status`. Exactly one transitions `ISSUED` to `PAID`; the loser is rejected with `ERR_INVOICE_ALREADY_PAID`.
- **Two SEP verifications race on different SEPEvents under the same application during a CLOSED OEP window.** Both verifications may succeed, but only one SEP's `effective_date` governs the next enrollment — the earliest verified by `reported_at` ascending. A later verification does not override an earlier governing SEP; an attempt to apply a later one raises `ERR_SEP_CONFLICT`.

## 4. Endpoint Definitions

All endpoints accept and return the response envelope defined in §2.2. New-resource creation endpoints return HTTP 201; mutation endpoints that update existing resources return HTTP 200; delete operations return HTTP 204; read operations return HTTP 200. Authentication and authorization are evaluated per §2.1 and §3.9. Endpoints take their request and response bodies from the entities and rules described throughout §3 — this table is not a schema reference.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/applications` | Create a DRAFT application | `Applicant` |
| GET | `/applications/{id}` | Fetch one Application with denormalized rollups | `Applicant`, `MarketplaceAdmin`, `CustomerService` |
| GET | `/applications` | List applications (Applicant sees own; admins see all) | `Applicant`, `MarketplaceAdmin`, `CustomerService` |
| POST | `/applications/{id}/submit` | Transition DRAFT to SUBMITTED | `Applicant` |
| POST | `/applications/{id}/amend` | Revert SUBMITTED to DRAFT | `Applicant` |
| POST | `/applications/{id}/determine-eligibility` | Transition SUBMITTED to ELIGIBILITY_DETERMINED | `MarketplaceAdmin` |
| POST | `/applications/{id}/approve` | Transition ELIGIBILITY_DETERMINED to APPROVED | `MarketplaceAdmin` |
| POST | `/applications/{id}/deny` | Transition ELIGIBILITY_DETERMINED to DENIED | `MarketplaceAdmin` |
| POST | `/applications/{id}/redetermine` | Transition APPROVED to ELIGIBILITY_DETERMINED for re-evaluation after SEP | `MarketplaceAdmin` |
| POST | `/applications/{id}/household-members` | Add a HouseholdMember while parent is DRAFT | `Applicant` |
| PATCH | `/applications/{id}/household-members/{member_id}` | Update a HouseholdMember while parent is DRAFT | `Applicant` |
| DELETE | `/applications/{id}/household-members/{member_id}` | Remove a non-primary-filer HouseholdMember while parent is DRAFT | `Applicant` |
| POST | `/applications/{id}/household-members/{member_id}/income-records` | Append an IncomeRecord (corrections create new rows) | `Applicant` |
| POST | `/applications/{id}/sep-events` | File a SEP claim under an Application | `Applicant` |
| POST | `/applications/{app_id}/sep-events/{id}/verify` | Transition SEPEvent SUBMITTED to VERIFIED | `MarketplaceAdmin` |
| POST | `/applications/{app_id}/sep-events/{id}/reject` | Transition SEPEvent SUBMITTED to REJECTED | `MarketplaceAdmin` |
| POST | `/applications/{app_id}/sep-events/{id}/appeal` | Transition SEPEvent REJECTED back to SUBMITTED | `CustomerService` |
| POST | `/insurers` | Create an Insurer record | `MarketplaceAdmin` |
| GET | `/insurers` | List insurers (optionally filtered by `filing_state`) | `Applicant`, `MarketplaceAdmin`, `CustomerService`, `Insurer` |
| POST | `/plans` | Create a Plan in the catalog | `Insurer`, `MarketplaceAdmin` |
| PATCH | `/plans/{id}` | Update Plan (base premium, status, benchmark flag); bumps `catalog_version` | `Insurer`, `MarketplaceAdmin` |
| GET | `/plans` | List plans, filterable by state/year/tier/status | `Applicant`, `MarketplaceAdmin`, `CustomerService`, `Insurer` |
| POST | `/plans/{id}/variants` | Attach a CSR variant to a Silver plan | `Insurer`, `MarketplaceAdmin` |
| POST | `/enrollments` | Create an Enrollment binding an APPROVED Application to a PlanVariant | `Applicant` |
| GET | `/enrollments/{id}` | Fetch one Enrollment | `Applicant`, `MarketplaceAdmin`, `CustomerService`, `Insurer` |
| POST | `/enrollments/{id}/cancel` | Transition ACTIVE Enrollment to TERMINATED via applicant cancellation | `Applicant` |
| GET | `/enrollments/{id}/premium-invoices` | List invoices for an Enrollment in `billing_month` ascending, `id` ascending order | `Applicant`, `MarketplaceAdmin`, `CustomerService` |
| POST | `/premium-invoices/{id}/post-payment` | Transition ISSUED PremiumInvoice to PAID | `Applicant`, `CustomerService` |
| POST | `/premium-invoices/{id}/waive` | Transition ISSUED PremiumInvoice to WAIVED | `CustomerService` |
| POST | `/_clock/advance` | Advance the logical clock to a fixed timestamp | `MarketplaceAdmin` |
| POST | `/_sweep/age-invoices` | Walk Enrollments and apply payment-status thresholds and termination | `MarketplaceAdmin` |
| POST | `/_sweep/reconcile-aptc` | Year-end reconciliation: replay IncomeRecord history and write `aptc_reconciled_cents` | `MarketplaceAdmin` |

## 5. Error Code Catalogue

The following error identifiers are used in the `error_id` field of the error envelope. Trigger conditions are documented in §2 and §3 narratives — readers needing the precise condition for any code should consult the workflow text where the code is named.

| Error ID | HTTP Status |
|---|---|
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_APPLICATION_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 409 |
| `ERR_MISSING_PRIMARY_FILER` | 422 |
| `ERR_COVERAGE_YEAR_INVALID` | 422 |
| `ERR_OUTSIDE_ENROLLMENT_WINDOW` | 409 |
| `ERR_PLAN_STATE_MISMATCH` | 422 |
| `ERR_CSR_VARIANT_MISMATCH` | 422 |
| `ERR_OUTSIDE_SEP_WINDOW` | 422 |
| `ERR_MAGI_NEGATIVE` | 422 |
| `ERR_NO_BENCHMARK_PLAN` | 422 |
| `ERR_ENROLLMENT_ALREADY_EXISTS` | 409 |
| `ERR_PAYMENT_INSUFFICIENT` | 422 |
| `ERR_BENCHMARK_CONFLICT` | 409 |
| `ERR_SEP_WINDOW_EXPIRED` | 422 |
| `ERR_SEP_CONFLICT` | 409 |
| `ERR_INVOICE_ALREADY_PAID` | 409 |
| `ERR_DEPENDENT_AGE_INVALID` | 422 |
