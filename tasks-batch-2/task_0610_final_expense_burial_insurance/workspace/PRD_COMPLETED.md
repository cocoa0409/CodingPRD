# Final Expense & Burial Insurance API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a back-office API that administers final expense and burial insurance — the simplified-issue, small-face whole-life coverage marketed to older applicants who want a guaranteed way to pay for a funeral without a paramedical exam. Unlike fully underwritten life insurance, these products are sold on a short health questionnaire, an age-band rate card, and a benefit class that trades a lower entry bar for a delayed or graded payout in the first years. The system carries an applicant from a quote, through simplified-issue auto-adjudication, into an in-force policy, and ultimately to a death claim, a surrender, or a lapse.

The platform is a ledger-reconciliation engine at heart. A single death event can produce two very different payouts — the full face amount, or a refund of premiums plus interest — depending on the benefit class, how long the policy has been in force, and how the insured died. Cash value accrues on a vesting schedule and can be borrowed against; loans, premium reversals, and reinstatements all move a shared net-cash-value figure that several operations read concurrently. Every money or coverage event is recorded on an append-only ledger so that the carrier can reconstruct the financial state of a policy at any point. Compliance windows — the graded period and the contestability period — gate which payout fires and whether the carrier may rescind for misrepresentation.

Because real elapsed time drives nearly every rule (grace, graded payout, contestability, reinstatement, interest accrual), the system runs on an explicit **logical clock** rather than wall-clock time. Tests and operators advance this clock deliberately, and the server recomputes time-sensitive policy state whenever the clock moves. Four operator roles — underwriting, policy servicing, claims, and the policyholder — divide the surface between them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. A request missing or malformed in either header is rejected with `ERR_MISSING_AUTH`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `Underwriter`, `PolicyAdmin`, `ClaimsExaminer`, and `Policyholder`. The `Underwriter` owns the application and underwriting surface — creating applicants and applications, attaching questionnaires, submitting for adjudication, and manually approving, declining, or withdrawing referred applications. The `PolicyAdmin` owns policy servicing — issuing policies, lapsing and reinstating them, posting and reversing premiums, administering beneficiaries and funeral-home assignments, and administering loans. The `ClaimsExaminer` owns the claims surface — filing, reviewing, contesting, approving, and denying claims, and attaching death certificates. The `Policyholder` is the policy owner who pays premiums, manages beneficiaries, takes and repays loans, and surrenders coverage.

All four roles are opaque identities: `X-User-ID` is an operator identifier that is not tied to any persisted entity's `id`, and the server does not compare it against any entity's primary key. There is one important exception in *behavior* (not in identity binding): the `Policyholder`. When a policy is issued, the issuing request supplies a `policyholder_user_id`, and the server records that opaque value on the policy. Thereafter, on any owner-scoped mutation performed under the `Policyholder` role — surrendering a policy, disbursing a loan, or repaying a loan — the server compares the caller's `X-User-ID` against the policy's stored `policyholder_user_id`; if they differ, the request is rejected with `ERR_NOT_POLICY_OWNER`. The other three roles record their `X-User-ID` (for example, as actors on transitions) but the server never equates it with a stored entity identifier.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific workflow states otherwise, list endpoints return their items sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. The Logical Clock and Time-Driven Reconciliation

The server never reads wall-clock time. Instead it maintains a single logical clock that, before any call is made, reads the fixed startup default of `2026-01-01T00:00:00Z`. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant — returning a 200 response whose `data` is an empty object — and a companion read capability returns the current clock value as `data.current_utc`, an ISO 8601 UTC timestamp with three fractional digits. Every time-sensitive rule in the system — premium grace, the graded payout window, the contestability window, the reinstatement window, loan-interest accrual, and cash-value vesting — is measured against this logical clock, never against the real date.

Advancing the clock is itself a reconciling event. When the clock moves, the server re-evaluates the payment and coverage dimensions of every policy whose grace or lapse thresholds have now been crossed, applying the automatic transitions described in §3. A clock advance can therefore push a policy from `CURRENT` to `GRACE`, from `GRACE` to `DELINQUENT`, and — once the grace period has fully elapsed — from `ACTIVE` coverage to `LAPSED`. These recomputations happen in-request and atomically, consistent with the system's immediate-consistency model: there is no background job, and a read of a policy always reflects the clock as of the last time it was set.

### 2.5. Common Resource Properties and Append-Only Ledgering

Most resources in the system are "full" resources that carry a standard system-managed quartet. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation and `updated_at` is refreshed on every mutation. The `version` is an integer that starts at its initial value and increments by one on every mutation of the resource. The entities that carry this full quartet are `ProductPlan`, `Applicant`, `Application`, `Policy`, `Beneficiary`, `FuneralHomeAssignment`, `PremiumPayment`, `PolicyLoan`, and `Claim`.

Three entities are deliberately lightweight and carry only `id` and `created_at` — they have **no** `updated_at` and **no** `version`. These are the `HealthQuestionnaire` (the simplified-issue answers, immutable once attached), the `DeathCertificate` (the substantiating document, immutable once attached), and the `LedgerEntry`. The `LedgerEntry` is the backbone of the carrier's audit trail: it is an append-only money-and-coverage event log. Each entry records a signed `amount_cents` (credits positive, debits negative), the `balance_after_cents` net cash value immediately after the event, an `occurred_at` logical-clock timestamp, and an `entry_type` drawn from `PREMIUM_POSTED`, `PREMIUM_REVERSED`, `LOAN_DISBURSED`, `LOAN_REPAID`, `CASH_VALUE_ACCRUED`, `BENEFIT_PAID`, and `LOAN_OFFSET`. Ledger entries are never modified or deleted once written; corrections are made by appending compensating entries. Ledger entries are readable individually and listable, filterable by `policy_id` or `entry_type`.

### 2.6. Nested Resource Retrieval and Referential Validation

Several resources are addressed as children of a policy or a claim — for example a policy's beneficiaries, its funeral-home assignments, or a claim's death certificate. When a path carries more than one identifier, the server validates them left to right and rejects the request at the first identifier that does not resolve to an existing resource, returning `ERR_NOT_FOUND`. A request to revoke a beneficiary under a non-existent policy fails on the policy before the beneficiary is even consulted. The same left-to-right existence rule governs body references: any `applicant_id`, `product_plan_id`, `policy_id`, `application_id`, or `claim_id` named in a request body must resolve to a real resource, and a dangling reference yields `ERR_NOT_FOUND`. Existence is checked early, ahead of state and business rules, so that an invalid container never produces a misleading downstream error.

### 2.7. Monetary Precision and Rounding

All money is carried in integer cents; there are no fractional-cent representations stored on resources. Wherever a calculation produces a value that must be reduced to whole cents — a premium, a loan-interest figure, a surrender charge — the system rounds half up to the nearest cent. The point at which rounding is applied is significant and is pinned per calculation in §3: some figures are rounded exactly once at the very end, while others are rounded per component before being summed. Rates and factors supplied on a `ProductPlan` (for example `graded_refund_apr`, `loan_apr`, and `max_loan_to_cash_value_pct`) preserve their input precision and are not rounded. Any final payout or proceeds figure is floored at zero so that no resource ever reports a negative cash value or a negative net payout.

### 2.8. Optimistic Concurrency on Policy Cash Value

Disbursing a policy loan draws on the policy's shared net cash value — a figure that premium posts, premium reversals, reinstatements, and other loans all move. To prevent a writer from disbursing against a stale view of that figure, loan disbursement is guarded by optimistic concurrency control on the policy. A loan-disbursement request must carry `expected_policy_version`, a non-optional field holding the `version` of the target `Policy` that the client last observed. If that value does not match the policy's current `version` — because some other writer has advanced the policy since the client last read it — the disbursement is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412), and the client must re-read the policy before retrying. A successful disbursement increments the policy's `version` by one, so a second disbursement carrying the now-superseded version will itself be rejected until the client re-reads. No other endpoint takes a version field; optimistic concurrency applies only to loan disbursement.

### 2.9. Underwriting, Benefit Classes, and Compliance Windows

Three concepts cut across the whole product. First, **benefit class**: every `ProductPlan` declares a `benefit_type` of `GUARANTEED_ISSUE`, `GRADED_BENEFIT`, or `LEVEL_BENEFIT`, and this class — pinned onto the policy at issue — decides whether an early natural death pays full face or a graded refund. Second, the **graded period**: a window of `graded_period_months` measured from the policy's issue date during which a non-accidental death pays the graded benefit rather than the full face. Third, the **contestability period**: a window of `contestability_period_months` from issue during which the carrier may contest a claim and rescind the policy for material misrepresentation. Both windows are measured from the original issue date and are never reset by a lapse and reinstatement. Throughout the system, an accidental manner of death bypasses the graded period entirely and always pays full face.

## 3. Business Logic & Workflows

### 3.1. Configuring Products: Plans, Tiers, and Bands

Everything begins with a `ProductPlan`, created by a `PolicyAdmin`. A plan carries a display `name` and a `benefit_type` (`GUARANTEED_ISSUE`, `GRADED_BENEFIT`, or `LEVEL_BENEFIT`). It defines the eligible age range through `min_issue_age` (default 45) and `max_issue_age` (default 85); an applicant's attained age must fall at or above the minimum and at or below the maximum. The plan's `graded_period_months` (default 24) governs how long the graded payout applies — set to 0 for a level plan — and `contestability_period_months` (default 24) governs the rescission window. The `graded_refund_apr` (default 0.10) is the annual simple-interest rate paid on returned premiums when a graded-period natural death triggers the refund payout.

Pricing inputs live on the plan as well. The `base_monthly_rate_per_1000_cents` (default 400) is the base monthly premium, in cents, per $1000 of face before any age or class multiplier. The `face_tiers` array is an ordered list of face-amount tiers, each carrying a `tier_name`, a `min_face_cents`, a `max_face_cents`, and a `tier_load_pct`; the requested face selects which load applies. The `age_bands` array is an ordered list of bands, each carrying a `band_name`, a `min_age`, a `max_age`, and an `age_factor`, where both the minimum and the maximum age are inclusive bounds. Cash-value behavior is configured by `cash_value_factor_per_1000_cents` (default 1500, the guaranteed cash value accrued in cents per $1000 of face for each full policy-year in force past vesting) and `cash_value_vesting_years` (default 3, the number of whole policy-years that must elapse before any cash value vests; before that, loans and surrender are blocked). Loan terms come from `max_loan_to_cash_value_pct` (default 0.90), `loan_apr` (default 0.08), and `loan_cooldown_days` (default 30, the days that must pass after a loan is settled before a new one may be disbursed). The `surrender_charge_tiers` array is an ordered list keyed on gross cash value, each tier carrying a `min_gross_cents`, a `max_gross_cents`, and a `charge_pct`. Finally, `grace_period_days` (default 31) is how long a premium may go unpaid past its due date before lapse, and `reinstatement_window_days` (default 180) is how long after a lapse reinstatement remains possible. Plans are readable individually and listable, optionally filtered by `benefit_type`.

### 3.2. Applicants, Applications, and the Simplified-Issue Questionnaire

An `Underwriter` (or a `PolicyAdmin`) first records an `Applicant` — the proposed insured — with a `full_name`, a `date_of_birth` given as an ISO 8601 date, a `gender` of `MALE` or `FEMALE`, a `tobacco_use` flag, and a two-letter `state_code` of residence. They then open an `Application` against a chosen plan, supplying the `applicant_id`, the `product_plan_id`, and the `requested_face_amount_cents` — the death benefit being applied for. A new application begins in `DRAFT`.

Before an application can be adjudicated, the simplified-issue `HealthQuestionnaire` must be attached. The questionnaire references its `application_id` and answers four yes/no questions: `terminal_illness` (diagnosed terminal illness or hospice), `aids_hiv` (an AIDS or HIV diagnosis), `nursing_home_confined` (currently confined to a nursing home), and `major_condition_last_2y` (cancer, heart, or stroke treatment within the last two years). From the first three the system computes `knockout_triggered`, which is true when any one of `terminal_illness`, `aids_hiv`, or `nursing_home_confined` is true. The fourth answer is a soft flag that influences routing and rating rather than an automatic knockout. Questionnaires are retrievable individually and listable by `application_id`.

Applications are retrievable individually and listable, filterable by `applicant_id`, `product_plan_id`, or `status`. A `DRAFT` application may be withdrawn by an `Underwriter` or `PolicyAdmin` at any time, which moves it to the terminal `WITHDRAWN` state with no further effect.

### 3.3. Submitting and Adjudicating an Application

Submitting an application for adjudication is an `Underwriter` action that advances it from `DRAFT` to `SUBMITTED`. Submission requires that exactly one health questionnaire has been attached; with none present the submission is rejected with `ERR_QUESTIONNAIRE_MISSING`. At submission the system computes `attained_age` — the whole-year age of the applicant on the application's `created_at` date, derived from the applicant's `date_of_birth` — and then performs simplified-issue auto-adjudication, routing the application onward to one of three outcomes in the same request.

The system first tests for a hard decline. If `knockout_triggered` is true, or the attained age is below the plan's `min_issue_age` or above its `max_issue_age`, or the requested face falls outside every configured face tier, the application advances automatically from `SUBMITTED` to `DECLINED`. The `decline_reason` is set by checking these causes in a fixed order: a knockout takes precedence and yields `KNOCKOUT_CONDITION`; if there is no knockout but the age is out of band, the reason is `AGE_OUT_OF_BAND`; if neither of those but the face is out of range, the reason is `FACE_OUT_OF_RANGE`. This precedence is strict — knockout is evaluated before age, and age before face — so a candidate failing more than one test is declined for the first cause in that order.

If no hard decline fires, the system checks for a soft referral. When there is no knockout, the age is within band, the face is within range, and `major_condition_last_2y` is true **on a `LEVEL_BENEFIT` plan**, the application is routed automatically from `SUBMITTED` to `REFERRED` for manual underwriting, and no premium is quoted yet. Otherwise — no knockout, age in band, face in range, and not subject to the referral condition — the application is routed automatically from `SUBMITTED` to `APPROVED`. On reaching `APPROVED` the system computes the rating class and the premium: `rating_class` is `TOBACCO` when the applicant's `tobacco_use` is true and `STANDARD` otherwise, except that `major_condition_last_2y` on a `GRADED_BENEFIT` or `GUARANTEED_ISSUE` plan yields `SUBSTANDARD`. The `quoted_monthly_premium_cents` is then computed via the premium-rate calculation described in §3.4; it remains 0 until the application is approved. The fourth possible `rating_class` value, `DECLINE`, is reserved for declined applications.

A `REFERRED` application is resolved manually by an `Underwriter`. Approving it advances `REFERRED` to `APPROVED` and computes `rating_class` and `quoted_monthly_premium_cents` exactly as the clean auto-approval does; attempting to approve an application that is not in `REFERRED` is rejected with `ERR_INVALID_STATE`. Declining it advances `REFERRED` to the terminal `DECLINED` state, sets `decline_reason` to `KNOCKOUT_CONDITION`, and is likewise rejected with `ERR_INVALID_STATE` if the application is not `REFERRED`.

### 3.4. Pricing a Policy: The Premium Calculation

The monthly premium is computed when an application reaches `APPROVED`, whether through clean auto-approval at submission or through manual approval of a referral. The calculation works in pinned order from the single application being approved and the plan pinned by its `product_plan_id`.

First, the number of $1000 units of face is the requested face amount in cents divided by 100000. The age factor is the `age_factor` of the age band whose inclusive `min_age`-to-`max_age` range contains the attained age. The tier load is the `tier_load_pct` of the face tier whose `min_face_cents`-to-`max_face_cents` range (inclusive) contains the requested face. The class multiplier is 1.00 for a `STANDARD` rating class, 1.50 for `TOBACCO`, and 2.00 for `SUBSTANDARD`. The raw figure is the base monthly rate per $1000 multiplied by the number of face units multiplied by the age factor. The loaded figure is the raw figure multiplied by one plus the tier load. The final premium is the loaded figure multiplied by the class multiplier, rounded half up to whole cents. The evaluation order is pinned: compute raw, apply the tier load, apply the class multiplier, and round exactly once at the very end — never round an intermediate.

### 3.5. Issuing a Policy and the Coverage Lifecycle

Issuing a policy is a `PolicyAdmin` action that may be performed only on an `APPROVED` application; an attempt against any other state is rejected with `ERR_INVALID_STATE`. The request must supply `policyholder_user_id`, the opaque owner identifier; if it is absent the request is rejected with `ERR_VALIDATION`. Issuing advances the application to its terminal `ISSUED` state and, as a depth-2 cascade, creates a `Policy`. The new policy pins `face_amount_cents`, `monthly_premium_cents`, `benefit_type`, `applicant_id`, and `product_plan_id` from the application and plan, records the originating `application_id`, and stores the supplied `policyholder_user_id`. Its `issue_date` is set to the current logical clock, and both `paid_through_date` and `due_date` are initialized to the issue date. The policy is created with coverage status `PENDING` and payment status `CURRENT`, then immediately auto-advances its coverage from `PENDING` to `ACTIVE`. A first `LedgerEntry` of type `CASH_VALUE_ACCRUED` is appended with `amount_cents` 0 and `balance_after_cents` 0 to open the policy's ledger. Issuance responds with `201 Created` and returns the newly created `Policy` resource (not the application) in `data`.

A `Policy` carries two independent status dimensions. The coverage dimension, `coverage_status`, follows `PENDING` → `ACTIVE` → one of `LAPSED`, `TERMINATED`, or `SURRENDERED`, with the cyclic edge `LAPSED` → `ACTIVE` available through reinstatement; the terminal coverage states are `TERMINATED`, `SURRENDERED`, and `RESCINDED`. The payment dimension, `payment_status`, is one of `CURRENT`, `GRACE`, or `DELINQUENT` and moves independently of coverage. The policy also exposes several computed figures whenever it is read: `paid_through_date` (the exclusive upper bound of contiguous covered coverage, equal to `issue_date` when no premium has yet posted), `due_date` (the next premium due date, equal to `paid_through_date`, with grace running `grace_period_days` past it), `total_premiums_paid_cents`, `gross_cash_value_cents`, `outstanding_loan_balance_cents`, and `net_cash_value_cents`. Reading a policy recomputes these figures against the current clock. Policies are readable individually and listable, filterable by `application_id`, `product_plan_id`, `applicant_id`, `policyholder_user_id`, or `coverage_status`.

### 3.6. Premiums, Grace, and the Payment Dimension

A premium is posted by a `PolicyAdmin` or the `Policyholder` against a policy named by `policy_id`. The payment tenders an `amount_cents` and buys a coverage interval defined by a half-open `[coverage_start, coverage_end)` window — `coverage_start` inclusive, `coverage_end` exclusive. The request is rejected with `ERR_VALIDATION` if `coverage_start` is not strictly before `coverage_end`. It is rejected with `ERR_COVERAGE_PERIOD_OVERLAP` if the new interval overlaps the interval of any existing `POSTED` payment on the same policy; pure adjacency, where a prior payment's `coverage_end` exactly equals the new `coverage_start`, is permitted and is not an overlap. A successful post records `status` `POSTED` and a `posted_date` at the current clock, recomputes the policy's `paid_through_date`, `due_date`, and `total_premiums_paid_cents`, and appends a `PREMIUM_POSTED` ledger entry. If the policy's payment status was `GRACE` or `DELINQUENT` and the new `paid_through_date` now lies past the current clock, the payment status returns to `CURRENT`.

The payment dimension is otherwise driven entirely by the clock. When the clock advances past a policy's `due_date` but remains within the grace period — strictly after the due date and strictly before the due date plus `grace_period_days` — the payment status moves from `CURRENT` to `GRACE`, while coverage stays `ACTIVE` because the two dimensions are independent. When the clock reaches or passes the due date plus `grace_period_days`, the payment status moves from `GRACE` to `DELINQUENT`, and coverage remains `ACTIVE` until a lapse is actually fired. A payment that restores `paid_through_date` past the clock returns a `GRACE` policy to `CURRENT`, and the reinstatement back-premium flow returns a `DELINQUENT` policy to `CURRENT`.

A `PolicyAdmin` may reverse a `POSTED` premium as a compensating action; an attempt to reverse a payment that is not `POSTED` is rejected with `ERR_INVALID_STATE`. Reversal sets the payment's `status` to `REVERSED` and recomputes the policy's `total_premiums_paid_cents` and `paid_through_date` back to the values they held before the post, conserving the premiums-paid invariant, and appends a `PREMIUM_REVERSED` ledger entry. The conserved invariant is that `total_premiums_paid_cents` always equals the sum of `POSTED` premium amounts minus those that have been reversed. Premiums are readable individually and listable, filterable by `policy_id` or `status`.

### 3.7. Lapse, Reinstatement, and the Loan Call/Reinstate Cascade

A policy lapses for non-payment either automatically or by hand. The automatic path fires when the clock advances to or past the due date plus `grace_period_days` on a policy that was **already** `DELINQUENT` immediately before that advance. The payment-dimension reconciliation a clock advance performs is gated on the policy's payment status as it stood just before the advance: a single advance that crosses the due date plus `grace_period_days` while the policy was `CURRENT` or `GRACE` moves the payment status to `DELINQUENT` but leaves coverage `ACTIVE` — the automatic lapse does **not** fire on that same advance. The automatic lapse fires only on a *subsequent* advance that still finds the clock at or past the due date plus `grace_period_days` with the policy already `DELINQUENT`; coverage can otherwise be lapsed at any qualifying point through the manual path below. This clock-driven reconciliation runs only when the clock is set, and only over policies whose coverage is `ACTIVE`. The manual path is a `PolicyAdmin` action and requires that coverage is `ACTIVE` — otherwise `ERR_INVALID_STATE` — and, when fired by hand, that the current clock has reached or passed the due date plus `grace_period_days`; lapsing before grace has expired is rejected with `ERR_GRACE_NOT_EXPIRED`. A lapse sets coverage to `LAPSED` and payment status to `DELINQUENT`, opens a reinstatement window running from the lapse instant to the lapse instant plus `reinstatement_window_days`, and — as the second step of a depth-3 cascade — transitions every `ACTIVE` policy loan on the policy from `ACTIVE` to `CALLED`, because the loan is called due on lapse.

Reinstating a lapsed policy is a `PolicyAdmin` action that moves coverage from `LAPSED` back to `ACTIVE`. It requires that coverage is currently `LAPSED` — otherwise `ERR_INVALID_STATE` — that the current clock is at or before the lapse instant plus `reinstatement_window_days` — otherwise `ERR_REINSTATEMENT_WINDOW_CLOSED` — and that all back premiums have been posted so that `paid_through_date` reaches at least the current due cycle — concretely, the recomputed `paid_through_date` must be at or after the current logical clock — otherwise `ERR_BACK_PREMIUM_DUE`. On reinstatement coverage returns to `ACTIVE`, payment status returns to `CURRENT`, and every `CALLED` loan transitions from `CALLED` back to `ACTIVE`. Crucially, the graded and contestability windows are **not** reset on reinstatement — they continue to be measured from the original `issue_date`.

### 3.8. Beneficiaries and Funeral-Home Assignments

A policy's death benefit is directed by two kinds of designation, both writable by a `PolicyAdmin` or the `Policyholder`, and both permitted only while the policy's coverage is `ACTIVE` or `LAPSED` — a write against a terminal-coverage policy is rejected with `ERR_POLICY_NOT_DESIGNABLE`.

A `Beneficiary` is added with a `full_name`, a `relationship` of `SPOUSE`, `CHILD`, `SIBLING`, `PARENT`, `ESTATE`, or `OTHER`, and a whole-percent `share_pct` of the residual death benefit; it is created `ACTIVE` and references its `policy_id`. The `share_pct` must lie between 1 and 100 inclusive, and a value outside that range is an `ERR_VALIDATION`. Designation is incremental: after each write, the sum of `share_pct` across the policy's `ACTIVE` beneficiaries must not exceed 100, and a write that would push the running total above 100 is rejected with `ERR_SHARES_EXCEED_100`. A policy need not sum to exactly 100 as designations are added — any unallocated remainder defaults to the estate at payout — but exactly-100 is enforced separately at claim approval. A beneficiary may be revoked by a `PolicyAdmin` or `Policyholder`, moving its `status` from `ACTIVE` to `REVOKED`; a revoked beneficiary no longer counts toward the share total. Beneficiaries are listable on a policy, filterable by `status`.

A `FuneralHomeAssignment` directs a fixed dollar amount of the benefit to a named funeral home, paid first and off the top before the residual beneficiary split. It is created with a `funeral_home_name` and an `assigned_benefit_cents` amount, references its `policy_id`, and begins `ACTIVE`; its `status` can later become `RELEASED`. Like beneficiary designation it is blocked on a terminal-coverage policy with `ERR_POLICY_NOT_DESIGNABLE`. Funeral-home assignments are listable on a policy, filterable by `status`.

### 3.9. Cash Value, Loans, and Loan Interest

Cash value vests on a whole-year schedule. The policy's `gross_cash_value_cents` is the guaranteed cash value accrued from full policy-years in force past vesting and ignores any loans: it is the plan's `cash_value_factor_per_1000_cents` multiplied by the number of $1000 face units (face amount in cents divided by 100000) multiplied by the vested years, where vested years is the larger of zero and the whole policy-years in force minus `cash_value_vesting_years`. This gross-cash-value product is reduced to a whole cent by rounding to the nearest cent with ties resolved to the nearest even cent — distinct from the half-up rule of §2.7, which here applies only to the derived surrender charge — and the same gross-cash-value rounding is used in the surrender calculation of §3.10. The `outstanding_loan_balance_cents` is the sum of principal plus accrued interest across all `ACTIVE` loans, and `net_cash_value_cents` is the gross cash value minus the outstanding loan balance, floored at zero.

A `PolicyLoan` is disbursed by a `Policyholder` or `PolicyAdmin` against a policy named by `policy_id`, carrying `expected_policy_version` for the optimistic-concurrency guard of §2.8 and a `principal_cents` to be advanced. Disbursement is subject to several checks. A loan may only be taken once the policy is past its vesting threshold; a loan before `cash_value_vesting_years` whole policy-years have elapsed is rejected with `ERR_CASH_VALUE_NOT_VESTED`. The loan cooldown requires that a new loan's `disbursed_date` be at or after the prior settled loan's `settled_date` plus `loan_cooldown_days`; a disbursement inside that cooldown is rejected with `ERR_LOAN_COOLDOWN_OVERLAP`. The fiscal cap requires that the outstanding balance plus the new principal not exceed `max_loan_to_cash_value_pct` of the policy's net cash value, and that the policy be past vesting; a request that breaches the cap is rejected with `ERR_LOAN_EXCEEDS_CASH_VALUE`. A successful disbursement creates the loan `ACTIVE` with `disbursed_date` at the current clock and `repaid_principal_cents` initialized to 0, increments the policy's `version` by one, recomputes the policy's `outstanding_loan_balance_cents` and `net_cash_value_cents`, and appends a `LOAN_DISBURSED` ledger entry.

Interest on a loan is simple interest on the outstanding principal. The outstanding principal is `principal_cents` minus `repaid_principal_cents`. The number of days is the whole days from the loan's `disbursed_date` to the current clock, floored at zero. The `accrued_interest_cents` is the outstanding principal multiplied by `loan_apr` multiplied by the day count divided by 365, rounded half up to whole cents. The loan's running balance is the outstanding principal plus the accrued interest. Loans are readable individually — which recomputes `accrued_interest_cents` against the current clock — and listable, filterable by `policy_id` or `status`.

Repaying a loan in full is a `Policyholder` or `PolicyAdmin` action that supplies an `amount_cents`. Full repayment requires that the amount be at least the outstanding principal (principal minus already-repaid principal) plus the accrued interest; an amount short of that is rejected with `ERR_LOAN_UNDERPAID`. A successful repayment moves the loan to `SETTLED`, sets its `settled_date` to the current clock, recomputes the policy's `net_cash_value_cents` and `outstanding_loan_balance_cents` to restore the cash-value invariant, and appends a `LOAN_REPAID` ledger entry. The loan status machine runs `ACTIVE` to either `SETTLED` (on full repayment) or `CALLED` (on lapse), and `CALLED` to `SETTLED` (on repayment or on the claim-approval netting described in §3.10); `SETTLED` is terminal.

### 3.10. Surrender and the Net Surrender Value

A `Policyholder` or `PolicyAdmin` may surrender an `ACTIVE` policy for its cash value. Surrender requires that coverage is `ACTIVE` — otherwise `ERR_INVALID_STATE` — that the whole policy-years in force are at least `cash_value_vesting_years` — otherwise `ERR_CASH_VALUE_NOT_VESTED` — and that no claim is currently in progress on the policy, meaning no claim is in `FILED`, `UNDER_REVIEW`, or `CONTESTING`; a surrender while such a claim exists is rejected with `ERR_CLAIM_IN_PROGRESS`. When the acting role is `Policyholder`, the owner check of §2.1 also applies. Surrender moves coverage to `SURRENDERED`, computes the net surrender value, settles each `ACTIVE` loan to `SETTLED`, and appends a `BENEFIT_PAID` ledger entry for the surrender amount.

The net surrender value is computed in pinned order. Step one resolves the gross cash value independently of loans: the whole policy-years in force are the floored whole years from `issue_date` to the current clock, vested years are the larger of zero and those whole years minus `cash_value_vesting_years`, the number of $1000 face units is the face amount in cents divided by 100000, and the gross cash value is `cash_value_factor_per_1000_cents` multiplied by the face units multiplied by the vested years. Step two selects the surrender charge from the gross value: the applicable charge percentage is the `charge_pct` of the surrender-charge tier whose inclusive `min_gross_cents`-to-`max_gross_cents` range contains the gross cash value, the charge in cents is the gross cash value multiplied by that percentage rounded half up to whole cents, and the after-charge figure is the gross cash value minus the charge. The order is pinned: resolve the gross value first, select the tier by that gross value, then apply the charge — never select the tier from a post-charge figure. Step three nets out the loan balance: the net surrender proceeds are the after-charge figure minus the policy's `outstanding_loan_balance_cents`, floored at zero. The displayed `gross_cash_value_cents` on the policy is the step-one figure and ignores both the surrender charge and the loan balance; the surrender proceeds subtract both.

### 3.11. Filing and Reviewing a Death Claim

A `ClaimsExaminer` or `PolicyAdmin` files a death `Claim` against a policy named by `policy_id`, supplying the `date_of_death` as an ISO 8601 date and the `manner_of_death` of `NATURAL` or `ACCIDENTAL`. A claim may be filed only when the policy's coverage is in force — `ACTIVE`, or `LAPSED` still inside its reinstatement window — and never when coverage is `TERMINATED`, `SURRENDERED`, `RESCINDED`, or still `PENDING`; a filing against an out-of-force policy is rejected with `ERR_POLICY_NOT_IN_FORCE`. The date of death may not predate coverage: a `date_of_death` earlier than the policy's `issue_date` is rejected with `ERR_DEATH_BEFORE_ISSUE`. These two checks are ordered — the in-force coverage check is evaluated before the death-before-issue check — so a claim against a terminated policy surfaces `ERR_POLICY_NOT_IN_FORCE` rather than a date error. A new claim begins in `FILED`.

A `DeathCertificate` substantiates the claim. Attached by a `ClaimsExaminer` or `PolicyAdmin` to a claim named in the path, it carries a `certificate_number`, a `certified_cause` of `ILLNESS`, `ACCIDENT`, `HOMICIDE`, `SUICIDE`, or `UNDETERMINED`, and a `verified` flag indicating whether the examiner has confirmed the certificate authentic; it references its `claim_id`. Death certificates are readable individually and listable by `claim_id`.

A `ClaimsExaminer` starts review, advancing the claim from `FILED` to `UNDER_REVIEW`; this requires that a death certificate exists for the claim, otherwise `ERR_DEATH_CERTIFICATE_MISSING`. Starting review computes a provisional `gross_benefit_cents` and `payout_basis` via the payout calculation of §3.12. Reading a claim that is `UNDER_REVIEW` or `CONTESTING` likewise recomputes the provisional gross and net payout. Claims are readable individually and listable by `policy_id` or `status`.

### 3.12. The Dual-Variant Claim Payout

The death benefit takes one of two forms, and which one fires is decided first at start-review (provisionally) and again at approval (finally). The system measures `months_in_force` as the whole months from the policy's `issue_date` to the claim's `date_of_death`. A death falls within the graded variant when the policy's pinned `benefit_type` is graded-eligible — that is, `benefit_type` is either `GRADED_BENEFIT` or `LEVEL_BENEFIT` (there is no separate per-policy flag; every `LEVEL_BENEFIT` policy is graded-eligible by benefit type, and a `GUARANTEED_ISSUE` policy never is) — **and** the months in force are strictly less than the plan's `graded_period_months` **and** the manner of death is `NATURAL`. An accidental death always pays full face regardless of the graded window.

When the death is **not** within the graded variant, `payout_basis` is `FULL_FACE` and `gross_benefit_cents` is the policy's full `face_amount_cents` — the guaranteed full-face variant. This is the path taken for any accidental death, any death after the graded window, a `GUARANTEED_ISSUE` policy past the graded window, and a `LEVEL_BENEFIT` policy outside the graded window.

When the death **is** within the graded variant, `payout_basis` is `GRADED_REFUND` and the benefit is a refund of premiums paid plus simple interest — not the full face. The rounding order here is pinned and differs from a naive sum: interest is computed per payment and rounded before summing, never summed then rounded. For each `POSTED` premium payment on the policy, excluding any `REVERSED` ones, the day count is the whole days from that payment's `posted_date` to the claim's `date_of_death`, floored at zero; the per-payment interest is that payment's `amount_cents` multiplied by the plan's `graded_refund_apr` multiplied by the day count divided by 365, rounded half up to whole cents; and the running refund accumulates that payment's `amount_cents` plus its rounded interest. The `gross_benefit_cents` is the accumulated refund.

### 3.13. Contesting, Approving, and Denying a Claim

From `UNDER_REVIEW` a `ClaimsExaminer` may take three paths. Contesting moves the claim from `UNDER_REVIEW` to `CONTESTING` for a misrepresentation investigation, but is permitted only when the date of death falls within `contestability_period_months` of the policy's `issue_date` — that is, the whole months from `issue_date` to `date_of_death` are strictly less than `contestability_period_months`, so a death exactly at the boundary is outside; a contest of a death outside the contestability window is rejected with `ERR_OUTSIDE_CONTESTABILITY`.

Approving a claim finalizes the payout and is permitted from either `UNDER_REVIEW` or `CONTESTING`. Approval requires that the policy's coverage is still `ACTIVE`, otherwise `ERR_POLICY_NOT_IN_FORCE`, and that the attached death certificate's `verified` flag is true, otherwise `ERR_CERTIFICATE_NOT_VERIFIED`. On approval the system finalizes `gross_benefit_cents` and `payout_basis`, sets `loan_offset_cents` to the policy's `outstanding_loan_balance_cents`, and sets `net_payout_cents` to the gross benefit minus that offset, floored at zero. Approval is the first step of a depth-3 cascade: the policy transitions from `ACTIVE` to `TERMINATED`, which in turn settles each `ACTIVE` or `CALLED` loan to `SETTLED` with its balance netted against the death benefit as the loan offset. A `BENEFIT_PAID` ledger entry is appended, and when the offset is greater than zero a `LOAN_OFFSET` entry is appended as well. The net payout is then allocated across the policy's payees by the waterfall of §3.14.

Denying a claim is permitted from `UNDER_REVIEW` or `CONTESTING` and sets `net_payout_cents` to 0. A denial from `UNDER_REVIEW` takes its `denial_reason` from the request — one of `POLICY_NOT_IN_FORCE` or `EXCLUDED_CAUSE` — and a request that omits it or supplies any other value is rejected with `ERR_VALIDATION`. A denial from `CONTESTING` sets `denial_reason` to `MISREPRESENTATION`, and if the death falls within the contestability window the policy transitions from `ACTIVE` to the terminal `RESCINDED` state; rescission also fires automatically when a misrepresentation denial lands inside the contestability window. The fourth possible `denial_reason` value is null until a denial occurs. The claim's terminal states are `APPROVED` and `DENIED`.

### 3.14. Allocating the Death Benefit: The Payout Waterfall

When a claim is approved, the `net_payout_cents` pool is distributed by a waterfall. The first bucket is priority: the funeral home is paid off the top. The amount paid to funeral homes is the lesser of the pool and the sum of `assigned_benefit_cents` across all `ACTIVE` funeral-home assignments, and the residual is the pool minus that funeral-home payment. The second bucket distributes the residual across the policy's `ACTIVE` beneficiaries by `share_pct`. Each beneficiary's share is the residual multiplied by that beneficiary's `share_pct` divided by 100, rounded **down** to whole cents. Rounding down can leave a few cents unallocated; that remainder — the residual minus the sum of the floored shares — is then distributed one cent at a time to beneficiaries ordered by `created_at` ascending. The ordering is deterministic and is always by creation time, never by `id`. Exactly-100 across `ACTIVE` beneficiary shares is the rule enforced at this approval step; any shortfall not covered by active beneficiaries defaults to the estate.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state-transition actions, return `200 OK`. The two logical-clock utilities also return `200 OK`. Request bodies, response bodies, and side effects are not repeated here — they are specified in the §3 narratives and the §2 principles. Every list endpoint accepts the `limit` and `offset` pagination parameters of §2.3 in addition to the filters noted in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PolicyAdmin, Underwriter, ClaimsExaminer |
| GET | `/_clock` | Read the current logical clock | PolicyAdmin, Underwriter, ClaimsExaminer, Policyholder |
| POST | `/product-plans` | Create a ProductPlan | PolicyAdmin |
| GET | `/product-plans/{id}` | Get a ProductPlan | PolicyAdmin, Underwriter, ClaimsExaminer, Policyholder |
| GET | `/product-plans` | List ProductPlans | PolicyAdmin, Underwriter, ClaimsExaminer, Policyholder |
| POST | `/applicants` | Create an Applicant | Underwriter, PolicyAdmin |
| GET | `/applicants/{id}` | Get an Applicant | Underwriter, PolicyAdmin, ClaimsExaminer |
| POST | `/applications` | Create a DRAFT Application | Underwriter, PolicyAdmin |
| GET | `/applications/{id}` | Get an Application | Underwriter, PolicyAdmin, ClaimsExaminer |
| GET | `/applications` | List Applications | Underwriter, PolicyAdmin |
| POST | `/applications/{id}/questionnaire` | Attach the HealthQuestionnaire | Underwriter, PolicyAdmin |
| GET | `/health-questionnaires/{id}` | Get a HealthQuestionnaire | Underwriter, PolicyAdmin, ClaimsExaminer |
| GET | `/health-questionnaires` | List HealthQuestionnaires | Underwriter, PolicyAdmin, ClaimsExaminer |
| POST | `/applications/{id}/submit` | Submit an Application for adjudication | Underwriter |
| POST | `/applications/{id}/approve` | Approve a REFERRED Application | Underwriter |
| POST | `/applications/{id}/decline` | Decline a REFERRED Application | Underwriter |
| POST | `/applications/{id}/withdraw` | Withdraw a DRAFT Application | Underwriter, PolicyAdmin |
| POST | `/applications/{id}/issue` | Issue a Policy from an APPROVED Application | PolicyAdmin |
| GET | `/policies/{id}` | Get a Policy | PolicyAdmin, ClaimsExaminer, Policyholder, Underwriter |
| GET | `/policies` | List Policies | PolicyAdmin, ClaimsExaminer, Underwriter |
| POST | `/policies/{id}/lapse` | Lapse a Policy for non-payment | PolicyAdmin |
| POST | `/policies/{id}/reinstate` | Reinstate a LAPSED Policy | PolicyAdmin |
| POST | `/policies/{id}/surrender` | Surrender a vested Policy | Policyholder, PolicyAdmin |
| POST | `/policies/{id}/beneficiaries` | Add a Beneficiary to a Policy | PolicyAdmin, Policyholder |
| GET | `/policies/{id}/beneficiaries` | List a Policy's Beneficiaries | PolicyAdmin, Policyholder, ClaimsExaminer |
| POST | `/policies/{id}/beneficiaries/{beneficiaryId}/revoke` | Revoke a Beneficiary | PolicyAdmin, Policyholder |
| POST | `/policies/{id}/funeral-home-assignment` | Assign part of the benefit to a funeral home | PolicyAdmin, Policyholder |
| GET | `/policies/{id}/funeral-home-assignments` | List a Policy's FuneralHomeAssignments | PolicyAdmin, Policyholder, ClaimsExaminer |
| POST | `/premium-payments` | Post a PremiumPayment | PolicyAdmin, Policyholder |
| GET | `/premium-payments/{id}` | Get a PremiumPayment | PolicyAdmin, Policyholder, ClaimsExaminer |
| GET | `/premium-payments` | List PremiumPayments | PolicyAdmin, Policyholder, ClaimsExaminer |
| POST | `/premium-payments/{id}/reverse` | Reverse a POSTED PremiumPayment | PolicyAdmin |
| POST | `/policy-loans` | Disburse a PolicyLoan | Policyholder, PolicyAdmin |
| GET | `/policy-loans/{id}` | Get a PolicyLoan | PolicyAdmin, Policyholder, ClaimsExaminer |
| GET | `/policy-loans` | List PolicyLoans | PolicyAdmin, Policyholder, ClaimsExaminer |
| POST | `/policy-loans/{id}/repay` | Repay a PolicyLoan in full | Policyholder, PolicyAdmin |
| POST | `/claims` | File a death Claim | ClaimsExaminer, PolicyAdmin |
| GET | `/claims/{id}` | Get a Claim | ClaimsExaminer, PolicyAdmin, Policyholder |
| GET | `/claims` | List Claims | ClaimsExaminer, PolicyAdmin |
| POST | `/claims/{id}/death-certificate` | Attach a DeathCertificate | ClaimsExaminer, PolicyAdmin |
| GET | `/death-certificates/{id}` | Get a DeathCertificate | ClaimsExaminer, PolicyAdmin |
| GET | `/death-certificates` | List DeathCertificates | ClaimsExaminer, PolicyAdmin |
| POST | `/claims/{id}/start-review` | Start review of a Claim | ClaimsExaminer |
| POST | `/claims/{id}/contest` | Contest a Claim | ClaimsExaminer |
| POST | `/claims/{id}/approve` | Approve a Claim | ClaimsExaminer |
| POST | `/claims/{id}/deny` | Deny a Claim | ClaimsExaminer |
| GET | `/ledger-entries/{id}` | Get a single LedgerEntry | PolicyAdmin, ClaimsExaminer, Policyholder |
| GET | `/ledger-entries` | List a Policy's LedgerEntries | PolicyAdmin, ClaimsExaminer, Policyholder |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_POLICY_OWNER` | 403 |
| `ERR_QUESTIONNAIRE_MISSING` | 409 |
| `ERR_GRACE_NOT_EXPIRED` | 409 |
| `ERR_REINSTATEMENT_WINDOW_CLOSED` | 409 |
| `ERR_BACK_PREMIUM_DUE` | 409 |
| `ERR_CASH_VALUE_NOT_VESTED` | 409 |
| `ERR_CLAIM_IN_PROGRESS` | 409 |
| `ERR_POLICY_NOT_DESIGNABLE` | 409 |
| `ERR_SHARES_EXCEED_100` | 422 |
| `ERR_COVERAGE_PERIOD_OVERLAP` | 409 |
| `ERR_STALE_POLICY_VERSION` | 412 |
| `ERR_LOAN_EXCEEDS_CASH_VALUE` | 422 |
| `ERR_LOAN_COOLDOWN_OVERLAP` | 409 |
| `ERR_LOAN_UNDERPAID` | 422 |
| `ERR_POLICY_NOT_IN_FORCE` | 409 |
| `ERR_DEATH_BEFORE_ISSUE` | 422 |
| `ERR_DEATH_CERTIFICATE_MISSING` | 409 |
| `ERR_CERTIFICATE_NOT_VERIFIED` | 409 |
| `ERR_OUTSIDE_CONTESTABILITY` | 409 |
