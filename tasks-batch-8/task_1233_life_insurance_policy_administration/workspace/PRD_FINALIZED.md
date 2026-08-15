# Life Insurance Policy Administration API — Product Requirements Document

## 1. Introduction

Life insurance carriers live and die by the accuracy of their policy administration. A single in-force policy may run for decades, passing through underwriting, issuance, years of premium billing, loans against cash value, dividend declarations, lapses, reinstatements, and eventually a terminal event such as surrender, conversion, or claim. Each of these events carries actuarially meaningful arithmetic — premiums derived from class-rated rate tables, cost-of-insurance charges drawn against a running cash-value ledger, loan interest that accrues daily, non-forfeiture values that must be computed to the cent under regulatory scrutiny. This document specifies a Policy Administration API that models that full lifecycle for a carrier's book of business, covering whole life (participating and non-participating), convertible term, and universal life products.

The system is built around two commitments. First, **auditability**: every movement of value into or out of a policy's cash value is recorded as an immutable ledger entry, every underwriting and issuance decision is attributable to a named operator, and segregation-of-duties rules prevent any single operator from both approving and consummating the same transaction. Second, **deterministic time**: all time-dependent behavior — grace periods, lapse, conversion windows, reinstatement windows, interest accrual, age calculations — is driven by a single logical clock under administrative control, never by wall-clock time, so that the book of business can be replayed, tested, and audited against a known timeline. The intended users are the carrier's agents, underwriters, policy-issuance specialists, platform administrators, and the policyholders themselves, each acting through a narrow, role-appropriate slice of the API.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts — authentication, response envelopes, pagination, time, precision, ledger discipline, concurrency control, and the global validation ordering — that apply uniformly to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly five roles, spelled as follows: `PlatformAdmin`, `Agent`, `Underwriter`, `PolicyIssuer`, and `Policyholder`. Each operation is restricted to a designated set of roles; a request whose role is not authorized for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `InsuredPerson`; ownership checks on any resource that references an `InsuredPerson` compare the resource's foreign-key field to `X-User-ID`. The same rule holds when `X-User-Role` is `Policyholder`: `X-User-ID` is the `id` of the acting `InsuredPerson`, and ownership checks — for example, whether the caller may originate a loan or elect a non-forfeiture option against a policy — compare the policy's insured-person reference to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `Underwriter`, or `PolicyIssuer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where an audit trail demands it (most notably in the segregation-of-duties checks of §2.11) but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

The system maintains a single logical clock, and that clock is the **only** source of time for all state machines and calculations: grace-period expiry, lapse, conversion and reinstatement windows, attained-age arithmetic, and loan-interest accrual all read it. At server startup the clock reads exactly `2026-05-01T00:00:00Z`. A `PlatformAdmin` may advance it by supplying a `to_iso8601` instant; the response echoes the resulting `current_utc`. Advancing the clock is never a passive act — every auto-transition whose trigger condition has come due fires as part of the advance: open billing cycles whose period has ended move into grace, grace periods whose end date has passed convert to lapse, lapsed policies with cash value receive their automatic non-forfeiture election, and all downstream cascades described in §3 run to completion within the same clock-set operation.

### 2.5. Common Resource Properties

Most resources share a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits. The `updated_at` timestamp follows the same format and refreshes on every mutation. The `version` is an integer that increments by one on every mutation of the resource and underpins the optimistic-concurrency rules of §2.10. Two resource families are deliberately append-only and carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from them: loan interest accrual rows and cash-value ledger entries. Any operation that mutates a policy's derived financial state — recording a payment, posting a dividend, electing a non-forfeiture option, approving a reinstatement — is a mutation of the `Policy` resource in the sense of this section: `updated_at` refreshes and `version` increments.

### 2.6. Monetary Precision and Rounding Discipline

All monetary amounts in the system are integer cents — face amounts, premiums, cash values, loan balances, dividends, charges, and payouts alike. Every calculation that produces a monetary result rounds **half-up to whole cents**, and several calculations pin the exact stage at which rounding occurs; where a rounding order is pinned in §3, rounding earlier or later is a specification violation, because alternative orderings diverge by real cents. Rates expressed in basis points (loan interest, surrender-charge percentages, substandard mortality loadings) are integers in ten-thousandths. Duration arithmetic uses a 365-day year everywhere, and attained ages are always whole years: the number of days elapsed since the insured's `date_of_birth`, divided by 365, rounded down.

### 2.7. The Cash Value Ledger

Every policy that builds value maintains an append-only cash value ledger. Each entry records its `policy_id`, an `entry_type`, a signed `amount_cents` (positive for credits, negative for debits), the `posting_date` on which the entry posts, and the `resulting_cash_value_cents` — the running balance of the policy's cash value immediately after the entry. Exactly eight entry types exist: `PREMIUM_CREDIT`, `COI_DEBIT`, `LOAN_DISBURSEMENT`, `LOAN_REPAYMENT_CREDIT`, `DIVIDEND_CREDIT`, `RIDER_PREMIUM_DEBIT`, `SURRENDER_DEBIT`, and `MONTHLY_FEE_DEBIT`. The ledger is the authoritative narrative of the policy's `cash_value_cents`: any operation that changes cash value writes the corresponding entry in the same act. Ledger listings are strictly chronological — entries are ordered by `created_at` ascending, and when two entries share a timestamp the tie is broken by their order of creation; ordering ties by `id` is expressly forbidden.

### 2.8. Dual Policy State Dimensions

A policy's posture is described by **two independent state dimensions**, never a single status. The `premium_payment_status` dimension tracks billing posture and takes the values `CURRENT`, `GRACE`, `LAPSED`, `REINSTATED_PENDING`, and `PAID_UP`. The `form_status` dimension tracks the policy's legal form and takes the values `IN_FORCE`, `REDUCED_PAID_UP`, `EXTENDED_TERM`, `CONVERTED`, `SURRENDERED`, and `DEATH_CLAIMED`. The two dimensions evolve in parallel: a policy may lapse (a billing event) while remaining `IN_FORCE` in form, and a reduced paid-up election changes both dimensions at once — form to `REDUCED_PAID_UP` and billing posture to `PAID_UP`. Rules in §3 always name the dimension they constrain. Terminal form states are `SURRENDERED`, `DEATH_CLAIMED`, and `CONVERTED`; operations targeting a resource that has already reached a terminal state are rejected with `ERR_ALREADY_TERMINAL`, while operations blocked by a non-terminal but incompatible state are rejected with `ERR_INVALID_STATE`.

### 2.9. Nested Resource Retrieval

Many resources are addressed as children of a policy within the URL hierarchy. For every such nested request the server validates path identifiers **sequentially, left to right**: the policy identifier is resolved first, and only then the child identifier (cycle, loan, rider, reinstatement request, conversion request, and so on). The request is rejected with the `404` error corresponding to the *first* identifier that does not resolve — `ERR_POLICY_NOT_FOUND` for the policy segment, then `ERR_CYCLE_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_RIDER_NOT_FOUND`, `ERR_REINSTATEMENT_NOT_FOUND`, or `ERR_CONVERSION_NOT_FOUND` for the respective child segments. Top-level lookups carry their own existence errors: `ERR_APPLICATION_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, and `ERR_INSURED_NOT_FOUND`. A request naming a valid child under a non-existent policy therefore always surfaces `ERR_POLICY_NOT_FOUND`, never the child error.

### 2.10. Optimistic Concurrency Control

Two policy write operations are protected by optimistic concurrency control, and both name the policy's `version` explicitly as an input.

- The premium-mode change operation requires the request to carry `expected_policy_version`, holding the `version` of the policy as the client last observed it. If the policy's current `version` does not equal `expected_policy_version` — because another writer has advanced the policy since that read, for example by recording a payment or applying a dividend — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is applied.
- The dividend-option change operation works identically: the request must carry `expected_policy_version` matching the policy's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not accept a version field; omitting `expected_policy_version` from either named operation is a request error, since the field is non-optional on both.

### 2.11. Segregation of Duties

Three transactions are two-person chains: the operator who performs the decisive second step must not be the operator who performed the first. At policy issuance, the issuing `PolicyIssuer`'s `X-User-ID` must differ from the approving underwriter's `X-User-ID`. At conversion approval, the approving underwriter's `X-User-ID` must differ from the requesting agent's. At reinstatement approval, the approving underwriter's `X-User-ID` must differ from the requesting agent's. A violation on any of these three operations is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).

### 2.12. Validation Priority Order

When a request would fail several checks, the error it surfaces is determined by a fixed evaluation order, applied uniformly across the API. The checks run in this sequence: **first**, the presence and well-formedness of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); **second**, role authorization for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`); **third**, existence of every path identifier, validated left to right as described in §2.9; **fourth**, whether the target resource's current state permits the operation (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` where the resource sits in a terminal state); **fifth**, segregation of duties on the three two-person chains of §2.11; **sixth**, clock-based windows — the five-year conversion window and the five-year reinstatement window (`ERR_WINDOW_EXPIRED`) — on conversion-request creation and reinstatement-request creation; **seventh**, referential compatibility of referenced entities (`ERR_INCOMPATIBLE_REFERENCE`) on conversion-request creation and rider creation; **eighth**, field-value constraints (`ERR_INVALID_REQUEST`) on all creating and modifying endpoints; **ninth**, underwriting-class consistency with the insured's tobacco flag (`ERR_CLASS_TOBACCO_MISMATCH`) on application approval; **tenth through twelfth**, the fiscal sufficiency checks — loan availability, non-forfeiture eligibility, and reinstatement-payment coverage (`ERR_INSUFFICIENT_CASH_VALUE` and `ERR_INSUFFICIENT_PAYMENT`); and **thirteenth**, optimistic-concurrency freshness (`ERR_STALE_VERSION`) on the two version-checked writes. Because earlier checks mask later ones, a request that fails both a header check and a business check always surfaces the header error, and a stale-version rejection is only ever observed on a request that has passed every other check.

## 3. Business Logic & Workflows

### 3.1. Insured Persons and Product Templates

Before any policy can exist, the carrier needs a person to insure and a product to sell. An `Agent` registers an insured person by supplying the person's `full_name`, their `date_of_birth` as an ISO calendar date, a boolean `tobacco_user` flag that will later drive underwriting-class assignment, and a `gender` of `MALE`, `FEMALE`, or `OTHER` — the gender value distinguishes which cost-of-insurance tables apply for products priced on gender-distinct mortality.

A `PlatformAdmin` authors the product catalogue. Each product template carries a unique `product_code` (carrier conventions such as `WL-PAR-001` for a participating whole life plan or `UL-FLEX-002` for a flexible universal life plan), a `product_type` of exactly one of `WHOLE_LIFE_PARTICIPATING`, `WHOLE_LIFE_NON_PARTICIPATING`, `TERM_CONVERTIBLE`, or `UNIVERSAL_LIFE`, a `participating` flag declaring whether the product pays dividends, and an `allows_policy_loans` flag marking products that build loanable cash value. Pricing is anchored by `base_monthly_premium_rate_per_thousand_cents` — the base monthly premium, in the template's rate units, per thousand dollars of face amount, quoted at the Preferred Non-Tobacco class for an insured aged 35 at issue — together with face-amount limits `min_face_amount_cents` and `max_face_amount_cents` that constrain what applications may request. Universal life templates additionally carry a `coi_rate_table`, an array pairing each `attained_age` key with a `monthly_rate_per_thousand_cents`; for non-universal-life products this table is an empty array. Universal life templates also carry a `surrender_charge_schedule`, an array pairing each `policy_year_min_inclusive` bracket boundary with a `surrender_charge_pct_bps` percentage in basis points; the schedule applies only to `UNIVERSAL_LIFE` products and is irrelevant to whole life.

### 3.2. The Application and Underwriting Workflow

An `Agent` opens the new-business pipeline by submitting an application that references the proposed insured through `insured_person_id` and the product through `product_template_id`, and states the `requested_face_amount_cents` and the desired `premium_mode` — one of `MONTHLY`, `QUARTERLY`, `SEMI_ANNUAL`, or `ANNUAL`. The requested face amount must fall within the template's `min_face_amount_cents` and `max_face_amount_cents`; a request outside that band, an unrecognized mode, or any other malformed field is rejected with `ERR_INVALID_REQUEST`. A new application's `status` stands in `SUBMITTED`.

An `Underwriter` takes up the file by beginning review, moving the application from `SUBMITTED` to `UNDER_REVIEW`. When the file lacks medical or financial evidence, the underwriter may send it from `UNDER_REVIEW` to `EVIDENCE_REQUIRED`; the agent then submits the evidence, returning the application from `EVIDENCE_REQUIRED` to `UNDER_REVIEW`. This request-and-submit cycle may repeat as many times as the underwriter requires. Alternatively, the underwriter may decline the file outright, moving it from `UNDER_REVIEW` to the terminal `DECLINED` state. `DECLINED` is the application's only terminal state: `ISSUED` is not terminal, so an operation attempted against an application in `ISSUED` (or any other state that does not permit the operation) is rejected with `ERR_INVALID_STATE`, never `ERR_ALREADY_TERMINAL`.

Approval is the consequential step. The underwriter approves an application in `UNDER_REVIEW` by assigning an `underwriting_class` in the request payload — one of `PREFERRED_NON_TOBACCO`, `STANDARD_NON_TOBACCO`, `PREFERRED_TOBACCO`, `STANDARD_TOBACCO`, `SUBSTANDARD_TABLE_B`, or `SUBSTANDARD_TABLE_D`. The assigned class must be consistent with the insured's `tobacco_user` flag: `PREFERRED_NON_TOBACCO` and `STANDARD_NON_TOBACCO` require a non-tobacco insured, while `PREFERRED_TOBACCO` and `STANDARD_TOBACCO` require a tobacco user; an inconsistent assignment is rejected with `ERR_CLASS_TOBACCO_MISMATCH` (HTTP 422). At approval the system also stamps the application's `substandard_extra_pct_bps`: zero for the four preferred and standard classes, 2500 basis points for `SUBSTANDARD_TABLE_B`, and 5000 basis points for `SUBSTANDARD_TABLE_D`. The approved application rests in `APPROVED`, awaiting issuance.

### 3.3. Issuance and the Modal Premium

Issuance is performed by a `PolicyIssuer` — never by the underwriter who approved the file, per the segregation rule of §2.11. Issuance is permitted only when two preconditions hold: the first billing cycle's premium has been fully received, meaning the first cycle stands in `PAID` or `WAIVED` status, and the product template referenced by the application is still valid. Issuance creates the `Policy` itself: the `application_id`, `insured_person_id`, and `product_template_id` are carried over from the application; `issue_date` is set; the policy begins with `form_status` of `IN_FORCE` and `premium_payment_status` of `CURRENT`; `paid_to_date` is initialized to the first cycle's `period_end_date`; and `attained_age_at_issue` is computed from the insured's `date_of_birth` as of the issue date. The carrier assigns a `policy_number` — an eight-digit, zero-padded string issued in sequence, ordered by policy creation time. The application's status advances to `ISSUED`, the first billing cycle is established, and an initial `PREMIUM_CREDIT` ledger entry posts the first modal premium. The new policy resource is returned with a `201 Created` status.

The policy's `modal_premium_cents` — the premium due each modal period — is computed at issuance from the face amount, the assigned underwriting class, the premium mode, and the attained age at issue, and the arithmetic is pinned exactly. Begin with the monthly rate: divide the policy's `face_amount_cents` by 100000 to express the face in thousands of dollars; multiply by the template's `base_monthly_premium_rate_per_thousand_cents`; multiply by the underwriting-class multiplier — 0.90 for `PREFERRED_NON_TOBACCO`, 1.00 for `STANDARD_NON_TOBACCO`, 1.50 for `PREFERRED_TOBACCO`, 1.80 for `STANDARD_TOBACCO`, 2.00 for `SUBSTANDARD_TABLE_B`, and 2.50 for `SUBSTANDARD_TABLE_D`; multiply by the substandard extra factor, which is one plus `substandard_extra_pct_bps` divided by 10000 (a factor of exactly 1 for non-substandard classes, 1.25 for Table B, 1.50 for Table D); and divide by 100. This monthly rate is rounded half-up to whole cents **before** any mode multiplication. The monthly rate is then multiplied by the mode factor — 1.00 for `MONTHLY`, 2.94 for `QUARTERLY`, 5.82 for `SEMI_ANNUAL`, and 11.52 for `ANNUAL` — and the product is rounded half-up to whole cents to yield `modal_premium_cents`. The rounding order is part of the contract: round the monthly rate first, then multiply by the mode factor, then round again. Computing an annual premium first and splitting it across modes is expressly rejected, because the two orderings differ by real cents.

### 3.4. Premium Billing, Grace, and Lapse

Coverage is billed in cycles. Each `PremiumBillingCycle` belongs to a policy through `policy_id`, carries a 1-based `cycle_index` counting cycles since issue, and spans a half-open coverage interval: `period_start_date` is inclusive, while `period_end_date` is exclusive. The cycle's `due_amount_cents` is the modal premium owed for the period, and `paid_amount_cents` tracks what has actually been received against it. A cycle's `status` moves among `OPEN`, `PARTIALLY_PAID`, `PAID`, `GRACE`, `LAPSED`, and `WAIVED`; `PAID`, `LAPSED`, and `WAIVED` are terminal.

An `Agent` records premium money by supplying an `amount_cents`. Allocation is strictly chronological over the cycles that already exist: the payment fills the oldest unpaid cycle first, walking existing cycles in ascending `cycle_index` order, topping each up to its `due_amount_cents` before any remainder flows to the next existing cycle. Recording a payment never creates new billing cycles — cycles beyond the first come into existence only through clock progression (§2.4); any portion of the payment left over after every existing unpaid cycle has been topped up is not allocated to any cycle, but the full `amount_cents` still posts as a single `PREMIUM_CREDIT` ledger entry for the amount paid, and on universal life policies the same posting also triggers the month's cost-of-insurance charge described in §3.5. A payment that leaves a cycle short moves that cycle from `OPEN` to `PARTIALLY_PAID` with `paid_amount_cents` incremented; a payment that brings a cycle's cumulative receipts to its due amount moves it to `PAID` — whether from `OPEN` in one stroke or from `PARTIALLY_PAID` by completing it. After allocation, the policy's `paid_to_date` is the latest `period_end_date` among cycles standing in `PAID`. When the policy sits in `GRACE`, a payment covering at least the grace cycle's remaining balance — its `due_amount_cents` minus its `paid_amount_cents` — moves that cycle from `GRACE` to `PAID` and lifts the policy's `premium_payment_status` from `GRACE` back to `CURRENT`.

When the logical clock advances past a cycle's `period_end_date` while the cycle is still `OPEN` or `PARTIALLY_PAID` — that is, paid less than due — the cycle moves to `GRACE` and the policy's `premium_payment_status` moves from `CURRENT` to `GRACE` with it. The policy's `grace_period_end_date` is set to the unpaid cycle's `period_end_date` plus 31 days. The grace-to-lapse boundary is strict: the policy lapses only when the current date is **strictly after** `grace_period_end_date`; when the current date equals `grace_period_end_date` exactly, the policy remains in `GRACE`, and lapse fires on the following day. At lapse, the cycle moves from `GRACE` to `LAPSED`, the policy's `premium_payment_status` moves from `GRACE` to `LAPSED`, and a three-part cascade runs: any outstanding policy loans are marked `FORECLOSED`, with their principal and accrued interest folded into the non-forfeiture arithmetic of §3.8; every active rider on the policy is `TERMINATED`; and if the policy holds non-forfeiture value — `cash_value_cents` greater than zero — and no explicit non-forfeiture election exists, the system automatically creates an election of type `EXTENDED_TERM` on the policyholder's behalf.

Cycles may also reach `WAIVED` without payment: an `OPEN` cycle is waived by the system when the policy goes reduced paid-up, extended term, or surrendered, or while an exercised waiver-of-premium rider is in effect, as detailed in §3.8 and §3.10.

A policyholder who wants to pay on a different cadence asks their `Agent` for a premium-mode change. The change supplies a new `premium_mode`; the system recomputes `modal_premium_cents` under the pinned arithmetic of §3.3 using the new mode's factor, applies the new modal premium to future cycles, and increments the policy's `version` by one. This is one of the two optimistic-concurrency-guarded writes of §2.10: the request must carry `expected_policy_version` equal to the policy's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`, since a mode change computed against an unobserved interim modification would rest on a stale premium basis.

### 3.5. Cash Value and Universal Life Cost-of-Insurance

The policy's `cash_value_cents` means different things by product line. On whole life products it is the scheduled cash value plus accumulated dividends; on `UNIVERSAL_LIFE` it is a true running ledger balance, credited by premiums and dividends and debited by charges, loans, and fees — each movement a ledger entry per §2.7.

Universal life carries a monthly cost-of-insurance charge, assessed on each policy's cycle anniversary and again whenever a premium payment posts, provided the policy's `form_status` is `IN_FORCE` and its `premium_payment_status` is anything other than `PAID_UP`. The charge is computed on the **net amount at risk**: the policy's `face_amount_cents` minus its `cash_value_cents`. When that difference is zero or negative, no charge is assessed at all. Otherwise, the insured's attained age in whole years at the charge date — days since `date_of_birth` divided by 365, rounded down — selects a rate from the template's `coi_rate_table`: the entry whose attained-age key is the largest key not exceeding the attained age, or, when the attained age exceeds every key in the table, the highest entry. The charge itself is the net amount at risk in cents divided by 100000, multiplied by the selected entry's `monthly_rate_per_thousand_cents`, multiplied by the policy's underwriting-class multiplier (the same multiplier table used at issuance in §3.3), divided by 100, and rounded half-up to whole cents. The charge debits the ledger as a `COI_DEBIT` entry whose `amount_cents` is negative. By default the charge is computed against the cash value **before** the current cycle's premium credit is applied; where a policy is configured with the `front_loaded_coi` flag, the basis instead uses the cash value after the current cycle's premium credit, which shrinks the net amount at risk and therefore the charge.

### 3.6. Policy Loans: Origination, Accrual, and Repayment

A `Policyholder` may borrow against a policy's cash value by requesting a loan of `requested_amount_cents`. Availability is strictly limited: the requested amount must not exceed the policy's `cash_value_cents` minus its aggregate `outstanding_loan_principal_cents` minus its aggregate `accrued_loan_interest_cents`; a larger request is rejected with `ERR_INSUFFICIENT_CASH_VALUE` (HTTP 402). A positive amount is required — zero or negative requests fail field validation with `ERR_INVALID_REQUEST`. At origination the loan stands `ACTIVE`, its `origination_date` is set, and its `annual_interest_rate_bps` is fixed carrier-wide at 500 basis points — five percent per annum. The policy's aggregate `outstanding_loan_principal_cents` increases by the requested amount, a `LOAN_DISBURSEMENT` debit entry posts to the ledger, and the policy's cash value is adjusted accordingly. The loan's own `outstanding_principal_cents` tracks what remains of the principal, its `accrued_interest_cents` tracks interest earned but not yet paid or capitalized, and its `last_accrual_date` marks how far interest has been brought forward.

Interest accrues chronologically. An accrual run walks from the loan's `last_accrual_date` forward to the as-of date, splitting the walk at each loan-anniversary boundary. Within each period the day count is taken, and the period's interest is the loan's outstanding principal multiplied by the annual rate of 500 basis points (that is, by 500 divided by 10000), multiplied by the day count, divided by 365, and rounded half-up to whole cents for that period. Under the default **non-capitalizing** treatment, each period's interest accumulates into `accrued_interest_cents` and the principal never changes, so every period computes interest on the same principal. When the product template is configured with the `capitalize_loan_interest` flag, each period's interest is instead added to the outstanding principal at the anniversary boundary, and later periods therefore compound. Every processed window is persisted as an accrual row recording the `loan_id`, the window's `accrual_period_start` (inclusive) and `accrual_period_end` (exclusive), the `principal_base_cents` on which interest was computed — including previously capitalized interest where the capitalizing variant applies — the `days_accrued`, and the `interest_accrued_cents` for the window. When the walk completes, the loan's `last_accrual_date` is set to the as-of date. Accrual runs fire on each loan anniversary, on every repayment, and at policy lapse; a `PlatformAdmin` may also force an accrual to the current clock, or to a supplied `as_of_date`, through an administrative capability.

Repayment follows a fixed waterfall. When the policyholder pays `amount_cents` against a loan, interest is first accrued up to the current date; the payment then satisfies accrued interest before touching principal. When cumulative repayments cover the loan's outstanding principal plus its accrued interest in full, the loan moves from `ACTIVE` to `REPAID`; the policy's aggregate `outstanding_loan_principal_cents` is decremented by the loan's outstanding principal and its aggregate `accrued_loan_interest_cents` by the loan's accrued interest, and a `LOAN_REPAYMENT_CREDIT` entry posts to the ledger. Attempting to repay a loan already in `REPAID` (or otherwise terminal) is rejected with `ERR_ALREADY_TERMINAL`. Loans do not survive their policy's distress: on lapse or on any non-forfeiture election, every outstanding loan is marked `FORECLOSED`, and its outstanding principal plus accrued interest is netted against cash value in the non-forfeiture arithmetic rather than collected.

### 3.7. Dividends on Participating Policies

Participating policies share the carrier's divisible surplus. Each such policy carries a `dividend_option` — one of `CASH`, `PREMIUM_REDUCTION`, `ACCUMULATE_AT_INTEREST`, or `PAID_UP_ADDITIONS` — which defaults to `CASH` and is meaningful only on participating products. The `Policyholder` may change the option at will, but that write is one of the two optimistic-concurrency-guarded operations of §2.10: the request must carry `expected_policy_version` equal to the policy's current `version`, and a stale value draws `ERR_STALE_VERSION`. A successful change increments the policy's `version` by one.

Only a `PlatformAdmin` may declare a dividend, supplying the `policy_year` to which the dividend applies — which must equal the policy's current `policy_year` (a 1-based number derived from the `issue_date` and the logical clock) — and a `declared_amount_cents` that must be greater than zero. Declaring against a non-participating product is rejected with `ERR_PRODUCT_NOT_PARTICIPATING` (HTTP 422). The declaration is born in `DECLARED` status and is applied immediately, provided the policy's `form_status` is `IN_FORCE`, `REDUCED_PAID_UP`, or `EXTENDED_TERM`; applying moves it to `APPLIED` and increments the policy's `version`. What "applied" means depends on the option in force, and the declaration's `applied_amount_cents` records the outcome:

- Under `CASH`, the full declared amount is paid to the policyholder out of band; `applied_amount_cents` equals `declared_amount_cents`, and no ledger entry and no cash-value movement occurs.
- Under `PREMIUM_REDUCTION`, the dividend offsets the next open cycle's `due_amount_cents`. The applied amount is the smaller of the declared amount and that next due amount, and a `PREMIUM_CREDIT` ledger entry posts for it; any remainder carries forward, reflected in the declaration as the difference between `declared_amount_cents` and `applied_amount_cents`.
- Under `ACCUMULATE_AT_INTEREST`, the full declared amount is applied: a `DIVIDEND_CREDIT` ledger entry posts and the policy's `dividend_accumulation_cents` increases by the applied amount.
- Under `PAID_UP_ADDITIONS`, the declared amount buys additional paid-up face using the same conversion schedule as the reduced paid-up calculation of §3.8 — the age-banded rate (0.30 below age 40, 0.40 for ages 40 through 49, 0.50 for ages 50 through 59, 0.65 at age 60 and above) plus the substandard loading — so the face addition is the declared amount divided by the adjusted rate, rounded half-up to whole cents. The full declared amount is applied into `dividend_accumulation_cents`, and the policy's `face_amount_cents` increases by the computed face addition.

A declaration is instead forfeited — moving from `DECLARED` to `FORFEITED` — when the policy lapses before the dividend can be applied, or when the option is `CASH` and the policy's form becomes `SURRENDERED`. Because applying a declaration mutates the policy and advances its `version`, a dividend-option change submitted against the pre-declaration version is rejected as stale — the intended serialization point between declaration and option change.

### 3.8. Non-Forfeiture Options

When a policyholder stops paying premiums on a policy that has built value, the law guarantees that the value is not lost; the carrier must offer three non-forfeiture routes. A `Policyholder` exercises one by creating a non-forfeiture election with an `election_type` of `CASH_SURRENDER`, `REDUCED_PAID_UP`, or `EXTENDED_TERM`. Eligibility requires a positive `cash_value_cents` and a positive net available value; a policy without sufficient value is rejected with `ERR_INSUFFICIENT_CASH_VALUE` (HTTP 402). The reduced paid-up route additionally requires the policy's `premium_payment_status` to be `CURRENT`, `GRACE`, or `LAPSED`, and that no previously approved non-forfeiture election exists on the policy.

Every election snapshot is preserved on the record: the `effective_date` (the day the policy lapsed, or the explicit surrender date), the `cash_value_at_election_cents` used in the arithmetic, the `outstanding_loan_offset_cents` — outstanding loan principal plus accrued interest at the election date — the `surrender_charge_cents` applied (universal life only; always zero for whole life), and the resulting `net_available_cents`, which is the cash value at election minus the loan offset minus the surrender charge. The surrender charge for a universal life policy comes from the template's `surrender_charge_schedule`: the applicable bracket is the entry whose `policy_year_min_inclusive` is the largest boundary not exceeding the policy's current `policy_year`, and the charge is the cash value multiplied by that bracket's `surrender_charge_pct_bps`, divided by 10000, rounded half-up to whole cents. Creating any election increments the policy's `version` by one and runs the shared cascade: outstanding loans move to `FORECLOSED`, active riders move to `TERMINATED`, and future billing cycles are `WAIVED`.

Under `CASH_SURRENDER`, the payout follows a waterfall: start from the gross cash value, subtract outstanding loan principal, subtract accrued loan interest, subtract the surrender charge, and pay the remainder as `payout_cents` — floored at zero should the subtractions overrun. The policy's `form_status` moves from `IN_FORCE` to `SURRENDERED`, its `premium_payment_status` becomes `PAID_UP`, and a `SURRENDER_DEBIT` ledger entry zeroes the cash value.

Under `REDUCED_PAID_UP`, the net available value is spent as a net single premium purchasing a smaller, fully paid policy. The conversion rate per dollar of paid-up face is banded by the insured's attained age at the election's `effective_date`: 0.30 below age 40, 0.40 for ages 40 through 49, 0.50 for ages 50 through 59, and 0.65 at age 60 and above. A substandard loading is added to the banded rate — `substandard_extra_pct_bps` divided by 10000 and then multiplied by 0.10, so a Table B rating adds 0.025 and a Table D rating adds 0.050. The `resulting_face_amount_cents` is the net available value divided by the adjusted rate, rounded half-up to whole cents; the policy's `face_amount_cents` is updated to that figure, its `premium_payment_status` moves to `PAID_UP`, and its `form_status` moves from `IN_FORCE` to `REDUCED_PAID_UP`. If the net available value is zero or negative, the election cannot be computed and is rejected with `ERR_INSUFFICIENT_CASH_VALUE`.

Under `EXTENDED_TERM`, the net available value purchases term coverage for the policy's full face amount, month by month. The monthly cost per dollar of face is banded identically by attained age: 0.0010 below age 40, 0.0020 for ages 40 through 49, 0.0040 for ages 50 through 59, and 0.0090 at age 60 and above. The monthly cost is the policy's `face_amount_cents` multiplied by the banded rate, rounded half-up to whole cents. The `resulting_term_months` is the net available value divided by that monthly cost, rounded down to a whole month, and capped at sixty months; the policy's `premium_payment_status` moves to `PAID_UP` and its `form_status` moves from `IN_FORCE` to `EXTENDED_TERM`. If the net available value cannot cover even one month's cost, the election is rejected with `ERR_INSUFFICIENT_CASH_VALUE`. This is also the election the system creates automatically on lapse when the policy holds positive cash value and no explicit election exists, as described in §3.4; for elections not of the corresponding type, the inapplicable result fields (`resulting_face_amount_cents`, `resulting_term_months`, `payout_cents`) are zero.

### 3.9. Reinstatement After Lapse

A lapsed policy is not necessarily dead. An `Agent` may request reinstatement of a policy whose `premium_payment_status` is `LAPSED`, provided the policy's `form_status` is still `IN_FORCE`, the request falls within five years of the lapse — the logical clock must not be later than five years after the lapse date, or the request is rejected with `ERR_WINDOW_EXPIRED` — and no earlier reinstatement request on the same policy still stands in `PENDING` or `EVIDENCE_REQUIRED`. Creating the request sets its `request_date`, computes the `back_premium_due_cents`, moves the policy's `premium_payment_status` from `LAPSED` to `REINSTATED_PENDING`, and stands the request in `PENDING` with its `underwriter_decision` likewise `PENDING`.

The back premium due is a chronological sum with interest. The lapse date is the policy's `paid_to_date` — the last date through which premiums were fully paid. Counting the modal periods falling due from the lapse date forward to the `request_date`, inclusive, each owed period contributes its modal premium plus reinstatement interest: for the *i*-th owed period, the due date is the lapse date advanced by *i* modal period lengths; the days overdue are the days from that due date to the request date, never less than zero; and the period's interest is the modal premium multiplied by six percent per annum, multiplied by the days overdue, divided by 365, rounded half-up per period. The `back_premium_due_cents` is the sum over all owed periods of premium plus interest.

The agent pays against the request by supplying `amount_cents`; a payment that does not cover the full `back_premium_due_cents` is rejected with `ERR_INSUFFICIENT_PAYMENT` (HTTP 402), while an accepted payment increments `back_premium_paid_cents`. Underwriting proceeds in parallel: the underwriter may move the request from `PENDING` to `EVIDENCE_REQUIRED`, and the agent's submission of evidence returns it from `EVIDENCE_REQUIRED` to `PENDING` with `evidence_of_insurability` set to true — a cycle that may repeat while the underwriter gathers what is needed. Approval requires all three of: `evidence_of_insurability` being true, `back_premium_paid_cents` covering at least `back_premium_due_cents`, and the segregation rule of §2.11 — the approving underwriter must not be the requesting agent. On approval the request's status and `underwriter_decision` become `APPROVED`; the policy's `premium_payment_status` returns to `CURRENT`; `paid_to_date` advances by the paid modal premiums; a `PREMIUM_CREDIT` ledger entry posts the back premium; the policy's `version` increments; and riders of type `WAIVER_OF_PREMIUM` that were terminated at lapse revert to `ACTIVE` if the approving underwriter specified `rider_reinstatement` as true. A declined request moves from `PENDING` to `DECLINED`, terminal.

### 3.10. Riders and Conversion

Riders bolt supplementary benefits onto an in-force policy. An `Agent` adds a rider by naming a `rider_type` — `WAIVER_OF_PREMIUM`, `ACCIDENTAL_DEATH_BENEFIT`, `TERM_CHILD`, or `GUARANTEED_INSURABILITY` — and a `rider_face_amount_cents`, which must be zero for `WAIVER_OF_PREMIUM` and `GUARANTEED_INSURABILITY` (they carry no independent face) and may not be negative for the others. The parent policy must be `IN_FORCE`; adding a rider to a policy in any other form is rejected with `ERR_INCOMPATIBLE_REFERENCE` (HTTP 422). The rider is born `ACTIVE`, and its `rider_monthly_premium_cents` — the additional monthly premium it adds — is computed at creation.

Termination is the common fate: an agent may terminate an active rider, and riders are also terminated wholesale by the lapse, non-forfeiture, and conversion cascades. Termination refunds the unused portion of the rider's premium, pro-rated by days, as a negative `RIDER_PREMIUM_DEBIT` ledger entry. Exercising a rider is reserved for the two exercisable types, and each has its own gate. Exercising `WAIVER_OF_PREMIUM` requires the policy's `premium_payment_status` to be `CURRENT`; while the rider stands `EXERCISED`, all current and future billing cycles are `WAIVED`. Exercising `GUARANTEED_INSURABILITY` requires the policy to have reached at least its third policy year; on exercise the policy's `face_amount_cents` increases by the rider's `rider_face_amount_cents` with no further underwriting. Attempting to exercise a rider of any other type is an invalid request, and operating on a rider already `TERMINATED` or `EXERCISED` — terminating an exercised rider, for instance — is rejected with `ERR_ALREADY_TERMINAL`.

Conversion lets a convertible term policy trade up to permanent coverage. An `Agent` files a conversion request against the source policy, naming the `target_product_template_id` and the `requested_face_amount_cents` for the new policy. Filing is gated by two rules: the logical clock must be within five years of the source policy's `issue_date` — later filings are rejected with `ERR_WINDOW_EXPIRED` — and the target template must exist and must not itself be `TERM_CONVERTIBLE`, else `ERR_INCOMPATIBLE_REFERENCE`. The request is born `PENDING`, and the insured's `attained_age_at_conversion` is computed for it.

An `Underwriter` then approves or declines. Approval re-verifies the full gate: the source policy's product must be `TERM_CONVERTIBLE`; the requested face amount must not exceed the source policy's `face_amount_cents`; the five-year window from `issue_date` must still be open; the target template must be valid and non-convertible; and the segregation rule of §2.11 must hold between requester and approver. On approval the request becomes `APPROVED` and a brand-new policy is issued from it: the new policy's `form_status` is `IN_FORCE`, its `attained_age_at_issue` is taken from the request's `attained_age_at_conversion`, its `underwriting_class` is inherited unchanged from the source policy, and the request's `new_policy_id` is populated to point at it. The source policy's `form_status` moves from `IN_FORCE` to `CONVERTED`, and its riders are `TERMINATED` in cascade. Decline simply moves the request from `PENDING` to `DECLINED`.

### 3.11. Reading the Book of Business

Every aggregate in the system is readable both in place and through flat, filterable listings. Policies may be listed with filters on `insured_person_id`, `form_status`, `premium_payment_status`, `application_id`, or `product_template_id`; applications may be filtered by `insured_person_id` or `product_template_id`. Flat collection listings exist for reverse reachability from a known foreign key: billing cycles, dividend declarations, non-forfeiture elections, reinstatement requests, riders, and cash-value ledger entries are each filterable by `policy_id`; policy loans by `policy_id`; loan interest accrual rows by `loan_id`; and conversion requests by `source_policy_id`, `target_product_template_id`, or `new_policy_id`. All of these listings follow the pagination and ordering contract of §2.3, and all read operations are available to every role.

## 4. Endpoint Definitions

Operations that create a new resource — an insured person, a product template, an application, an issued policy, a loan, an election, a declaration, a reinstatement request, a rider, or a conversion request — return `201 Created`. Operations that modify an existing resource, record money, or drive a state transition return `200 OK`. List endpoints accept the `limit` and `offset` query parameters of §2.3; the filter parameters available on specific listings (`insured_person_id`, `product_template_id`, `form_status`, `premium_payment_status`, `application_id`, `policy_id`, `loan_id`, `source_policy_id`, `target_product_template_id`, `new_policy_id`) are described in §3.11.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; fires all due auto-transitions | PlatformAdmin |
| POST | `/insured-persons` | Create an insured person | Agent |
| GET | `/insured-persons` | List insured persons | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/insured-persons/{id}` | Get one insured person | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/product-templates` | Create a product template | PlatformAdmin |
| GET | `/product-templates` | List product templates | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/product-templates/{id}` | Get one product template | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/applications` | Submit a policy application | Agent |
| GET | `/applications` | List applications | Agent, Underwriter, PolicyIssuer, PlatformAdmin |
| GET | `/applications/{id}` | Get one application | Agent, Underwriter, PolicyIssuer, PlatformAdmin |
| POST | `/applications/{id}/begin-review` | Move application from SUBMITTED to UNDER_REVIEW | Underwriter |
| POST | `/applications/{id}/request-evidence` | Move application from UNDER_REVIEW to EVIDENCE_REQUIRED | Underwriter |
| POST | `/applications/{id}/submit-evidence` | Submit evidence; return to UNDER_REVIEW | Agent |
| POST | `/applications/{id}/approve` | Approve with an assigned underwriting class | Underwriter |
| POST | `/applications/{id}/decline` | Decline the application | Underwriter |
| POST | `/applications/{id}/issue` | Issue the policy (segregated from approval) | PolicyIssuer |
| GET | `/policies` | List policies | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/policies/{id}` | Get one policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/policies/{id}/mode-change` | Change premium mode (optimistic concurrency on policy version) | Agent |
| POST | `/policies/{id}/dividend-option` | Change dividend option (optimistic concurrency on policy version) | Policyholder |
| GET | `/policies/{id}/billing-cycles` | List billing cycles for a policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/policies/{id}/premium-payments` | Record a premium payment, oldest unpaid cycle first | Agent |
| POST | `/policies/{id}/loans` | Originate a policy loan against cash value | Policyholder |
| GET | `/policies/{id}/loans` | List loans on a policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/policies/{id}/loans/{loanId}` | Get one loan | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/policies/{id}/loans/{loanId}/accrue-interest` | Trigger interest accrual to the clock or a given date | PlatformAdmin |
| POST | `/policies/{id}/loans/{loanId}/repayments` | Record a loan repayment | Policyholder |
| GET | `/policies/{id}/loans/{loanId}/accruals` | List interest accrual rows for a loan | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/policy-loans` | List all policy loans, filterable by policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/policy-loans/{id}` | Get one policy loan by id | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/loan-interest-accruals` | List all accrual rows, filterable by loan | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/loan-interest-accruals/{id}` | Get one accrual row by id | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/premium-billing-cycles` | List billing cycles, filterable by policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/premium-billing-cycles/{id}` | Get one billing cycle by id | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/dividend-declarations` | List dividend declarations, filterable by policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/dividend-declarations/{id}` | Get one dividend declaration | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/nonforfeiture-elections` | List non-forfeiture elections, filterable by policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/nonforfeiture-elections/{id}` | Get one election | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/reinstatement-requests` | List reinstatement requests, filterable by policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/reinstatement-requests/{id}` | Get one reinstatement request | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/riders` | List riders, filterable by policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/riders/{id}` | Get one rider | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/conversion-requests` | List conversion requests, filterable by source, target, or new policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/conversion-requests/{id}` | Get one conversion request | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/cash-value-ledger-entries` | List cash value ledger entries, filterable by policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| GET | `/cash-value-ledger-entries/{id}` | Get one ledger entry | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/policies/{id}/nonforfeiture-elections` | Create a non-forfeiture election (cash surrender, reduced paid-up, extended term) | Policyholder |
| GET | `/policies/{id}/nonforfeiture-elections` | List non-forfeiture elections on a policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/policies/{id}/dividend-declarations` | Declare a dividend on a participating policy | PlatformAdmin |
| GET | `/policies/{id}/dividend-declarations` | List dividend declarations on a policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/policies/{id}/reinstatement-requests` | Request reinstatement of a lapsed policy | Agent |
| GET | `/policies/{id}/reinstatement-requests` | List reinstatement requests on a policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/policies/{id}/reinstatement-requests/{rid}/payments` | Pay back premium against a reinstatement request | Agent |
| POST | `/policies/{id}/reinstatement-requests/{rid}/request-evidence` | Underwriter requests evidence | Underwriter |
| POST | `/policies/{id}/reinstatement-requests/{rid}/submit-evidence` | Agent submits evidence | Agent |
| POST | `/policies/{id}/reinstatement-requests/{rid}/approve` | Approve reinstatement (segregated from request) | Underwriter |
| POST | `/policies/{id}/reinstatement-requests/{rid}/decline` | Decline reinstatement | Underwriter |
| POST | `/policies/{id}/riders` | Add a rider to an in-force policy | Agent |
| GET | `/policies/{id}/riders` | List riders on a policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/policies/{id}/riders/{rid}/terminate` | Terminate an active rider | Agent |
| POST | `/policies/{id}/riders/{rid}/exercise` | Exercise a rider (waiver of premium or guaranteed insurability) | Agent |
| POST | `/policies/{id}/conversion-requests` | Request conversion of a convertible term policy | Agent |
| GET | `/policies/{id}/conversion-requests` | List conversion requests on a source policy | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |
| POST | `/policies/{id}/conversion-requests/{cid}/approve` | Approve conversion (segregated from request) | Underwriter |
| POST | `/policies/{id}/conversion-requests/{cid}/decline` | Decline conversion | Underwriter |
| GET | `/policies/{id}/cash-value-ledger` | List cash value ledger entries in posting order | Agent, Underwriter, PolicyIssuer, Policyholder, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_TEMPLATE_NOT_FOUND` | 404 Not Found |
| `ERR_INSURED_NOT_FOUND` | 404 Not Found |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_RIDER_NOT_FOUND` | 404 Not Found |
| `ERR_REINSTATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONVERSION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_INCOMPATIBLE_REFERENCE` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CLASS_TOBACCO_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CASH_VALUE` | 402 Payment Required |
| `ERR_INSUFFICIENT_PAYMENT` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PRODUCT_NOT_PARTICIPATING` | 422 Unprocessable Entity |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
