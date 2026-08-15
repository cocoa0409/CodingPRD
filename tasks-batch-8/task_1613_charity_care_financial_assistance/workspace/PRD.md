# Charity Care & Financial Assistance API — Product Requirements Document

## 1. Introduction

Nonprofit hospitals carry a statutory obligation under IRC Section 501(r) to screen patients for financial assistance before pursuing extraordinary collection actions, and to maintain a written financial assistance policy whose discount tiers, notification windows, and application periods are applied consistently to every account. In practice, eligibility teams juggle paper applications, third-party presumptive scoring feeds, and fragmented ledger systems, while billing and collections staff must hold enforcement activity the moment a patient signals intent to apply. When a policy is superseded mid-year, or a determination is reversed after accounts have been written off, the reconciliation burden falls on auditors who must reconstruct what was owed, what was refunded, and which reporting-year totals must be amended.

This document specifies the requirements for the Charity Care & Financial Assistance API, a system that governs the complete lifecycle of financial assistance: policy definition and activation, patient and account registration, statement issuance, application intake with household composition and document verification, presumptive eligibility screening for patients who do not respond, discount determination with segregation of duties, per-account write-offs and retroactive refunds, the 501(r) notification and extraordinary-collection-action gating framework, and community benefit reporting with an amendment cycle. The API is mounted under `/charity-care` and is designed for a segregated-duties operating model in which intake staff, determination reviewers, ledger staff, collections staff, and compliance officers hold disjoint authorities, and in which a server-side logical clock — not wall-clock time — drives every temporal gate.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts and cross-cutting rules that apply to every resource and workflow described later in this document.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the user's operational capacity. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Independently of authorization, any request that is malformed at the payload level — a required input field absent, a value of the wrong type, or an enum value outside the declared set for that field — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The system recognizes six roles, spelled exactly as follows: `Patient`, `FinancialCounselor`, `AssistanceReviewer`, `BillingAdministrator`, `CollectionsAgent`, and `ComplianceOfficer`.

When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's patient reference to `X-User-ID`. Specifically, on every patient-scoped endpoint the presented `X-User-ID` must equal the `patient_id` of the targeted resource — directly for accounts and applications, and transitively for documents (via their owning application) and determinations (via their owning application). A mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403). The five staff roles are exempt from this ownership comparison: for each of `FinancialCounselor`, `AssistanceReviewer`, `BillingAdministrator`, `CollectionsAgent`, and `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `verified_by_user_id` on a verified document, `screened_by_user_id` on a screening, `decided_by_user_id` on a finalized determination, or `initiated_by_user_id` on a collection action — but it does not compare the value to any entity's `id` for ownership purposes. It is, however, compared for segregation of duties as described in §2.8.

Role capabilities in brief: a `Patient` creates, submits, and withdraws their own applications, adds their own household members and documents, posts payments to their own accounts, and reads their own data. A `FinancialCounselor` is intake staff — shepherding applications through review, requesting documents, verifying or rejecting uploads, running presumptive screenings, and registering patients — but may never create or finalize a determination. An `AssistanceReviewer` is the determination authority — creating and finalizing determinations and sharing reversal authority with compliance — but may not touch documents or screenings. A `BillingAdministrator` owns the ledger: creating accounts, issuing the first statement and staff-issued notices, posting payments and account adjustments. A `CollectionsAgent` initiates and completes extraordinary collection actions and shares posture-evaluation rights. A `ComplianceOfficer` owns policies, halts collection actions, runs the community benefit report lifecycle, drives the logical clock, and shares determination-reversal and patient-registration rights.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items are skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

All temporal reasoning in the system — statement windows, document deadlines, notification gates, reporting-year membership, and every recorded timestamp described as "now" — reads a server-side logical clock, never wall-clock time. Before any operator interaction the logical clock stands at exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `ComplianceOfficer`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc` value. Every state machine side effect that says "logical clock now" — `submitted_at`, `first_statement_at`, `doc_response_deadline`, `finalized_at`, `reversed_at`, `initiated_at`, `halted_at`, `filed_at`, `issued_at` — stamps from this clock.

### 2.5. Common Resource Properties

Most resources in the system — `FinancialAssistancePolicy`, `Patient`, `PatientAccount`, `AccountPayment`, `AssistanceApplication`, `VerificationDocument`, `DiscountDetermination`, `AccountAdjustment`, and `CollectionAction` — share a standard set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by 1 on every mutation of the resource, including mutations caused by cascades from other entities.

Three resources are intentionally lighter. `HouseholdMember`, `PresumptiveScreening`, and `NotificationRecord` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, and nothing in the API reads or writes a version for these types.

Cascades respect the same bookkeeping: whenever one entity's operation mutates another entity (for example, a document verification bumping its owning application, or a determination finalization bumping both the determination and the application), the mutated entity's `updated_at` is refreshed and its `version` incremented exactly as if the change had been made directly.

### 2.6. Monetary Values, Percentages, and Precision

Every monetary quantity in the system is an integer number of cents — charges, payments, refunds, write-offs, FPL amounts, asset limits, and report totals alike. Percentages and scores are decimal numbers with pinned precision: FPL percentages are carried to 4 decimal places using round-half-up; discount percentages and propensity scores are carried to 2 decimal places using round-half-up. Wherever a rule in this document says "rounded half-up to N decimal places," that is the only permitted rounding, and it applies exactly once at the point named by the rule. Integer-cent computations (verified financial aggregation, refund waterfall grants, report sweeps) perform no rounding at all.

### 2.7. Policy Windows, Pinning, and Supersession

A `FinancialAssistancePolicy` defines an effective window as a half-open interval that includes `effective_from` and excludes `effective_to`. The window is internally sane only when `effective_from` is strictly earlier than `effective_to`; otherwise creation or activation is rejected with `ERR_INVALID_PERIOD` (HTTP 422). At activation time the candidate window is also checked against the window of every other policy whose status is `ACTIVE` or `SUPERSEDED`: a conflict exists when the candidate's `effective_from` is strictly earlier than the existing policy's `effective_to` and the existing policy's `effective_from` is strictly earlier than the candidate's `effective_to`. Two windows that merely touch — the candidate's `effective_from` equal to the existing window's `effective_to` — do not conflict. A detected conflict is rejected with `ERR_POLICY_WINDOW_OVERLAP` (HTTP 409).

Exactly one policy is `ACTIVE` at a time. Applications pin the active policy's identity and version integer at submit (`policy_id` and `policy_version`), and every calculation for that application — FPL percentage, tier thresholds, deadlines, retroactive windows — must use that pinned snapshot even if the policy is later superseded. Supersession never rewrites a pinned snapshot.

### 2.8. Segregation of Duties

Determination authority is deliberately separated from evidence handling. When an `AssistanceReviewer` finalizes a determination, the reviewer's `X-User-ID` must differ from the `verified_by_user_id` of every `VERIFIED` verification document on the application and from the `screened_by_user_id` of the application's presumptive screening. A finalize attempt by anyone who touched the evidence is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The same separation is reflected in role capabilities: `FinancialCounselor` staff verify documents and run screenings but cannot create or finalize determinations, while `AssistanceReviewer` staff decide determinations but cannot touch documents or screenings.

### 2.9. The 501(r) Notification and ECA Framework

An account's path toward extraordinary collection actions is gated by two temporal windows anchored on `first_statement_at`, both read from the policy that is `ACTIVE` at evaluation time. The notification period requires that the logical clock have reached `first_statement_at` plus `notification_period_days`; the boundary is inclusive, so a clock exactly at that instant satisfies the gate. The warning-notice requirement demands that an `ECA_WARNING` notice exist for the account whose `issued_at` is at least `eca_notice_days` before the current logical-clock instant — that is, `issued_at` less than or equal to now minus `eca_notice_days`, again inclusive. Both gates together form the ECA clearance window; failure of either yields `ERR_ECA_NOTIFICATION_WINDOW_UNMET` (HTTP 422). The clearance window is consulted both when collections staff evaluate an account's posture and when a collection action is initiated.

Separately, a retroactive application window governs refunds: an application submitted within `retroactive_window_days` after an account's `first_statement_at` entitles that account to refunds of excess payments (see §3.7). If the account has no first statement yet, the window has not started and the account is always retro-eligible.

While any application of the patient is open — in `SUBMITTED`, `UNDER_REVIEW`, or `PENDING_DOCUMENTS` — posture evaluation and collection-action initiation for that patient's accounts are frozen, surfacing `ERR_ASSISTANCE_HOLD_ACTIVE` (HTTP 409).

### 2.10. Nested Resource Retrieval

Requests whose paths contain multiple resource identifiers are validated strictly left to right. The existence of each path variable is confirmed in path order, and the request is rejected immediately with the not-found error of the first identifier that does not resolve — for example, an unknown account id yields `ERR_ACCOUNT_NOT_FOUND` before any payment, adjustment, notice, or collection-action identifier beneath it is even examined. The family of not-found errors is `ERR_PATIENT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ACTION_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, and `ERR_PAYMENT_NOT_FOUND`, each carrying HTTP 404.

### 2.11. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency against their parent entity's version; no other endpoint takes a version field.

Creating a determination requires the request to carry `expected_application_version`, the client-observed `version` of the target application. If the application's current `version` has advanced since the client last read it — for instance because a document was verified, a determination was created or finalized, or any other mutation bumped it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a second determination from silently stacking onto an application the client has not observed.

Posting an account adjustment requires the request to carry `expected_account_version`, the client-observed `version` of the target account. Payments, statement issuance, and prior adjustments all advance the account's `version`; a mismatch against the account's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) so that no write-off posts against a ledger the client has not observed.

### 2.12. Derived Ledger Fields and Reconciliation Order

Every `PatientAccount` carries four derived ledger quantities, always computed in this exact order because they form a chain of dependencies. First, `adjusted_balance_cents` is the account's creation-fixed `patient_responsibility_cents` minus the sum of `amount_cents` over all of the account's `POSTED` write-off adjustments. Second, `effective_payments_cents` is the sum of `amount_cents` minus `refunded_cents` over every payment row of the account regardless of status — a fully refunded payment therefore contributes zero. Third, `overpayment_cents` is the amount by which effective payments exceed the adjusted balance, floored at zero. Fourth, `amount_outstanding_cents` is the amount by which the adjusted balance exceeds effective payments, also floored at zero. Refunds mutate `refunded_cents` and therefore shift `effective_payments_cents`, but they never change `adjusted_balance_cents`, so evaluating the four quantities in this order terminates in a single pass. An account whose `amount_outstanding_cents` is zero holds the collection posture `RESOLVED`.

## 3. Business Logic & Workflows

### 3.1. Policy Authoring and Activation

A `ComplianceOfficer` authors a financial assistance policy by supplying its `policy_code` — which must be unique across all policies, with duplicates rejected as `ERR_DUPLICATE_POLICY_CODE` (HTTP 409) — together with the full parameter set: `fpl_base_cents` (the federal poverty guideline annual income for a household of one, in integer cents), `fpl_increment_cents` (the additional FPL amount per additional household member), `full_discount_max_fpl_pct` (the FPL percentage at or below which a 100% discount applies, boundary inclusive), `partial_discount_max_fpl_pct` (the FPL percentage strictly above which an applicant is ineligible — exactly equal still eligible), `partial_discount_floor_pct` (the discount percentage granted at exactly the partial ceiling, the sliding-scale floor), `asset_limit_cents` (the countable liquid asset cap), `retroactive_window_days` (240 in the standard 501(r) configuration), `notification_period_days` (120, boundary inclusive), `eca_notice_days` (30, boundary inclusive), `doc_response_days` (30 days an applicant has to supply requested documents), the two presumptive score thresholds `presumptive_partial_score_threshold` and `presumptive_full_score_threshold`, and the effective window `effective_from` / `effective_to`. A new policy is born with `status` `DRAFT`.

Activation by a `ComplianceOfficer` requires the policy to be in `DRAFT` (otherwise `ERR_POLICY_NOT_DRAFT`, HTTP 409) and runs the window checks of §2.7: the internal sanity check (`ERR_INVALID_PERIOD`) and the half-open overlap check against `ACTIVE` and `SUPERSEDED` policies (`ERR_POLICY_WINDOW_OVERLAP`). On success the policy moves `DRAFT → ACTIVE`, and any other policy that was `ACTIVE` is transitioned to `SUPERSEDED` by the same operation; both the activated policy's `version` and the superseded policy's `version` increment by 1, and both records refresh `updated_at`. `SUPERSEDED` is terminal.

### 3.2. Patients, Accounts, and the First Statement

Patient registration, performed by a `FinancialCounselor` or `ComplianceOfficer`, captures `full_name`, `date_of_birth` (an ISO 8601 `YYYY-MM-DD` date), `ssn_last4` (exactly four numeric characters), `mrn` (the medical record number, unique across the system with duplicates rejected as `ERR_DUPLICATE_MRN`, HTTP 409), and an optional `contact_email`.

A `BillingAdministrator` opens a patient account for an encounter by providing the `patient_id`, the `encounter_date`, `total_charges_cents` (strictly positive integer cents), and `insurance_paid_cents` (integer cents that must be at least zero and must not exceed `total_charges_cents`; a violation is `ERR_INSURANCE_EXCEEDS_CHARGES`, HTTP 422). At creation the account fixes `patient_responsibility_cents` as total charges minus insurance paid; this figure never changes afterward and is the basis for all later write-off math. If insurance covers the entire charge, `amount_outstanding_cents` is zero from birth and the account enters `RESOLVED` immediately; otherwise it begins in `NOT_IN_COLLECTIONS`.

The 501(r) clock starts when the `BillingAdministrator` issues the account's first billing statement. That operation requires `first_statement_at` to still be null — a second issuance attempt is rejected with `ERR_FIRST_STATEMENT_ALREADY_ISSUED` (HTTP 409) — and on success it stamps `first_statement_at` with the logical-clock now, creates a `FIRST_STATEMENT` `NotificationRecord` against the account with `is_plain_language` true, moves the account's posture `NOT_IN_COLLECTIONS → NOTICE_PERIOD`, and increments the account's `version`. The `FIRST_STATEMENT`, `DETERMINATION_LETTER`, and `DOC_REQUEST` notice types are system-created; staff-issued notices are limited to `PLAIN_LANGUAGE_SUMMARY` and `ECA_WARNING`, which a `BillingAdministrator` issues against an account by supplying `notice_type` and an optional `delivery_channel` (one of `MAIL`, `PORTAL`, `EMAIL`), producing a `NotificationRecord` whose `issued_at` stamps the logical clock. The `PLAIN_LANGUAGE_SUMMARY` notice type is also created by the system at application submit (see §3.4), always with `is_plain_language` true, as are `FIRST_STATEMENT` and `DETERMINATION_LETTER` records. Account notices carry `account_id` and leave `application_id` null; application letters (`DOC_REQUEST`, `DETERMINATION_LETTER`) do the reverse. Each notice's `issued_at` matters downstream — most critically, an `ECA_WARNING`'s `issued_at` drives the 30-day ECA gate of §2.9.

### 3.3. Application Intake and Household Composition

A `Patient` (for themselves) or a `FinancialCounselor` (on their behalf) opens an assistance application in `DRAFT` by naming the `patient_id`, the `screening_source` (`STANDARD` for a patient-initiated, document-verified path, or `PRESUMPTIVE` for a hospital-initiated non-responder path), and the self-reported figures `reported_annual_income_cents` and `reported_liquid_assets_cents` (both integer cents, at least zero). A patient may have at most one open application — that is, one application in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `PENDING_DOCUMENTS` — and a second attempt is rejected with `ERR_DUPLICATE_OPEN_APPLICATION` (HTTP 409).

While the application is in `DRAFT`, household composition is built up member by member: each member carries `full_name`, a `relationship` of `SELF`, `SPOUSE`, `CHILD`, or `OTHER_DEPENDENT`, and an `age` between 0 and 130 inclusive. Adding a member to a non-draft application is rejected as a terminal-state violation (`ERR_APPLICATION_TERMINAL`). The application exposes `household_size` as the count of its member rows, recomputed as members are added. Exactly one `SELF` row is required before the application can be submitted.

### 3.4. Submission: Policy Pinning and the Collections Freeze

Submission — by the `Patient` themselves or a `FinancialCounselor` — enforces three checks: the application must be in `DRAFT` (`ERR_APPLICATION_NOT_DRAFT`, HTTP 409), at least one household member with `relationship` `SELF` must exist (`ERR_HOUSEHOLD_SELF_REQUIRED`, HTTP 422), and a policy with status `ACTIVE` must exist (`ERR_NO_ACTIVE_POLICY`, HTTP 409). These checks are evaluated in the order given: the state check first, then household composition, then policy existence.

A successful submission moves `DRAFT → SUBMITTED` and performs four side effects at once. It pins `policy_id` and `policy_version` to the currently `ACTIVE` policy — the snapshot all later math must use, immune to later supersession. It stamps `submitted_at` from the logical clock; this timestamp later drives retroactive-window eligibility for each covered account. It creates a `PLAIN_LANGUAGE_SUMMARY` `NotificationRecord` with `application_id` set and `is_plain_language` true. And it freezes collections: every account of this patient whose posture is `NOTICE_PERIOD`, `ECA_ELIGIBLE`, or `ECA_ACTIVE` transitions to `ASSISTANCE_HOLD`. The application's `version` increments by 1.

Withdrawal is available to the `Patient` (own) or a `FinancialCounselor` from any non-terminal state — `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `PENDING_DOCUMENTS` — optionally carrying a `reason`; attempting it on a terminal application is rejected with `ERR_APPLICATION_TERMINAL` (HTTP 409). Withdrawal moves the application to `WITHDRAWN` and releases the freeze: every account of the patient in `ASSISTANCE_HOLD` returns to `NOTICE_PERIOD`.

### 3.5. Document Review and the Evidence Cycle

A `FinancialCounselor` begins review of a `SUBMITTED` application, moving it to `UNDER_REVIEW` (a begin-review on anything else is `ERR_APPLICATION_NOT_SUBMITTED`). While under review, the counselor may formally request documents, supplying `required_doc_types`; this moves `UNDER_REVIEW → PENDING_DOCUMENTS` (anything else is `ERR_APPLICATION_NOT_UNDER_REVIEW`), copies the request list into `requested_doc_types`, sets `doc_response_deadline` to the logical-clock now plus the pinned policy's `doc_response_days`, and creates a `DOC_REQUEST` `NotificationRecord` against the application.

Documents themselves are uploaded by the `Patient` or a `FinancialCounselor` onto a non-terminal application — targeting a `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `PENDING_DOCUMENTS` application is fine; `APPROVED`, `DENIED`, `EXPIRED`, or `WITHDRAWN` yields `ERR_APPLICATION_TERMINAL`. Each upload names a `doc_type` (`PAY_STUB`, `TAX_RETURN`, `BENEFIT_LETTER`, `BANK_STATEMENT`, or `IDENTITY`), a `period_start` and `period_end` forming a closed interval (`period_end` earlier than `period_start` is `ERR_INVALID_PERIOD`, HTTP 422), an `amount_cents`, and an optional `household_member_id` identifying which member the document evidences — required semantics vary by type, and an `IDENTITY` document for the applicant may omit it. If a `household_member_id` is supplied it must belong to the same application, else `ERR_MEMBER_APPLICATION_MISMATCH` (HTTP 422). The `amount_cents` semantics differ per type: per-period income for `PAY_STUB` (biweekly), `BENEFIT_LETTER` (monthly), and `TAX_RETURN` (annual); statement balance for `BANK_STATEMENT`; zero for `IDENTITY`. A new document starts in `SUBMITTED` status with `rejection_reason` null.

Verification is performed by a `FinancialCounselor`. Both verification and rejection require the document to be in `SUBMITTED` (`ERR_DOCUMENT_NOT_SUBMITTED`, HTTP 409) and the owning application to be in `SUBMITTED`, `UNDER_REVIEW`, or `PENDING_DOCUMENTS` (`ERR_APPLICATION_TERMINAL`). Verification carries one additional guard: for a `BANK_STATEMENT` document with `household_member_id` set, no other already-`VERIFIED` bank statement for the same member may have a closed-period overlap — a conflict exists when the new statement's `period_start` is on or before the existing statement's `period_end` and the existing statement's `period_start` is on or before the new statement's `period_end`, with touching dates counting as overlap — and a conflict is rejected with `ERR_DOC_PERIOD_OVERLAP` (HTTP 409). A successful verification moves `SUBMITTED → VERIFIED`, stamps `verified_by_user_id` with the acting counselor's `X-User-ID` (later consumed by the segregation-of-duties check), recomputes the application's verified financials per §3.6, and increments both the document's `version` and the owning application's `version` by 1.

Rejection by a `FinancialCounselor` records the supplied `rejection_reason` and moves `SUBMITTED → REJECTED`. Rejection is also the first link of a cascade: if the owning application is `UNDER_REVIEW`, the rejection forces it back to `PENDING_DOCUMENTS` — the rejected document's `doc_type` is unioned into `requested_doc_types` (deduplicated), `doc_response_deadline` is reset to now plus the pinned policy's `doc_response_days` on each rejection, and a fresh `DOC_REQUEST` notice is created. Both the document and the application increment their `version` by 1.

Resuming review moves `PENDING_DOCUMENTS → UNDER_REVIEW` and requires two things: the application must actually be in `PENDING_DOCUMENTS` (`ERR_APPLICATION_NOT_PENDING_DOCUMENTS`), and for every doc type listed in `requested_doc_types` at least one document of this application with that type must be `VERIFIED` (`ERR_DOCS_OUTSTANDING`, HTTP 422). Success clears `requested_doc_types` to empty and nulls `doc_response_deadline`.

If the applicant never responds, a `FinancialCounselor` may expire the application. Expiry requires `PENDING_DOCUMENTS` status (`ERR_APPLICATION_NOT_PENDING_DOCUMENTS`) and requires the logical clock to be strictly later than `doc_response_deadline` (`ERR_DOC_DEADLINE_NOT_REACHED`, HTTP 422) — at the deadline instant itself expiry is not yet permitted. A successful expiry moves the application to `EXPIRED` and releases every account of the patient from `ASSISTANCE_HOLD` back to `NOTICE_PERIOD`.

### 3.6. Verified Financials and the FPL Percentage

Each time a document of the application is verified, the system recomputes two aggregate figures. The `annualized_verified_income_cents` is the sum, over the application's `VERIFIED` documents of type `PAY_STUB`, `BENEFIT_LETTER`, or `TAX_RETURN`, of each document's `amount_cents` multiplied by its annualization factor — 26 for a biweekly pay stub, 12 for a monthly benefit letter, 1 for an annual tax return. The `verified_liquid_assets_cents` is the plain sum of `amount_cents` over the application's `VERIFIED` bank statements. Only `VERIFIED` rows feed these aggregates; `SUBMITTED` and `REJECTED` documents are excluded entirely. Both figures are integer cents with no rounding.

At determination creation on the verified path (see §3.8), these aggregates combine with the pinned policy to produce `fpl_pct_snapshot`. The FPL guideline amount for the household is the pinned policy's `fpl_base_cents` plus the household size minus one, times the policy's `fpl_increment_cents`. The FPL percentage itself is the application's `annualized_verified_income_cents` multiplied by 100 and divided by that guideline amount, rounded half-up to 4 decimal places, and frozen on the determination record at creation.

### 3.7. Presumptive Screening for Non-Responders

For a hospital-initiated application (`screening_source` `PRESUMPTIVE`), a `FinancialCounselor` runs a presumptive screening supplying any subset of five factor scores: `income_band_score`, `payment_history_score`, `utilization_score`, `public_benefit_score`, and `housing_stability_score`, each an integer from 0 to 100, each nullable — a null marks the factor unavailable. The screening is one-to-one with its application; a second attempt is rejected with `ERR_SCREENING_ALREADY_EXISTS` (HTTP 409).

The scoring rule works as follows. The factor weights are 0.35 for income band, 0.25 for payment history, 0.15 for utilization, 0.15 for public benefit, and 0.10 for housing stability — which for a complete file sum to exactly 1.00. If fewer than three factor scores are present, the screening is rejected outright with `ERR_INSUFFICIENT_FACTORS` (HTTP 422). Otherwise the raw score is the sum over present factors of each factor's weight times its score. When all five factors are present (`thin_file` false), the `propensity_score` is that raw sum rounded half-up to 2 decimal places. When only three or four factors are present (`thin_file` true), the raw sum is divided by the sum of the weights of the present factors only — a renormalization that yields a different score than treating absent factors as zero — and that quotient is rounded half-up to 2 decimal places. `present_factor_count` records how many factors were non-null.

The screening's `outcome` compares the `propensity_score` against the pinned policy's thresholds: a score at or above `presumptive_full_score_threshold` yields `ELIGIBLE_FULL`; a score at or above `presumptive_partial_score_threshold` (but below the full threshold) yields `ELIGIBLE_PARTIAL`; anything below yields `NOT_ELIGIBLE`. The screening also records `screened_by_user_id` from the acting counselor's `X-User-ID` (consumed by the segregation-of-duties check at finalize) and the constant `model_version` string `PRES-V1`.

### 3.8. Determinations: Creation, Finalization, Reversal

An `AssistanceReviewer` creates a determination by supplying the `application_id`, a `basis` of `VERIFIED_APPLICATION` or `PRESUMPTIVE_SCORE`, the list `covered_account_ids`, and — per §2.11 — the `expected_application_version`. The application must be in `UNDER_REVIEW` (`ERR_APPLICATION_NOT_UNDER_REVIEW`), and every entry of `covered_account_ids` must belong to the application's patient (`ERR_ACCOUNT_PATIENT_MISMATCH`, HTTP 422). At least one covered account must have `adjusted_balance_cents` greater than zero, else `ERR_NO_COLLECTIBLE_BALANCE` (HTTP 422). Two basis-specific evidence gates apply: a `VERIFIED_APPLICATION` basis requires at least one `VERIFIED` income document (`PAY_STUB`, `TAX_RETURN`, or `BENEFIT_LETTER`) and at least one `VERIFIED` `IDENTITY` document on the application (`ERR_VERIFIED_DOCS_REQUIRED`, HTTP 422); a `PRESUMPTIVE_SCORE` basis requires a presumptive screening whose `outcome` is not `NOT_ELIGIBLE` (`ERR_PRESCREEN_BELOW_THRESHOLD`, HTTP 422).

Tier assignment happens at creation: the `tier` and `discount_pct` are computed once and frozen on the `PRELIMINARY` record. On the verified path, the asset test is consulted first: if the application's `verified_liquid_assets_cents` is strictly greater than the pinned policy's `asset_limit_cents`, the tier is `INELIGIBLE` with `discount_pct` 0.00 — exactly equal to the limit passes the asset test. Otherwise, if `fpl_pct_snapshot` is at or below `full_discount_max_fpl_pct`, the tier is `TIER_FULL` with `discount_pct` 100.00. Otherwise, if the FPL percentage is at or below `partial_discount_max_fpl_pct`, the tier is `TIER_PARTIAL` and the discount percentage is the sliding-scale interpolation: the policy's `partial_discount_floor_pct` plus the product of (the partial ceiling minus the actual FPL percentage) and (100 minus the floor), divided by (the partial ceiling minus the full ceiling), the whole rounded half-up to 2 decimal places. Above the partial ceiling the tier is `INELIGIBLE` with `discount_pct` 0.00. On the presumptive path the determination consults only the screening outcome: `ELIGIBLE_FULL` yields `TIER_FULL` at a flat 100.00, `ELIGIBLE_PARTIAL` yields `TIER_PARTIAL` at a flat 50.00, and `NOT_ELIGIBLE` yields `INELIGIBLE` — income, assets, and household size are not consulted, so identical accounts can receive a different discount under the two bases. For the presumptive basis `fpl_pct_snapshot` is null. The determination copies `policy_id` and `policy_version` from the application's pinned snapshot. Creating the determination also bumps the owning application's `version` by 1.

Finalization by an `AssistanceReviewer` requires the determination to be `PRELIMINARY` (`ERR_DETERMINATION_NOT_PRELIMINARY`, HTTP 409), the application to still be `UNDER_REVIEW` (`ERR_APPLICATION_NOT_UNDER_REVIEW`), and the segregation-of-duties check of §2.8 (`ERR_SEGREGATION_OF_DUTIES`). On success the determination moves `PRELIMINARY → FINAL`, it stamps `decided_by_user_id` and `finalized_at`, creates a `DETERMINATION_LETTER` `NotificationRecord` against the application with `is_plain_language` true, and resolves the application: with any tier other than `INELIGIBLE` the application moves `UNDER_REVIEW → APPROVED`, while an `INELIGIBLE` tier moves it `UNDER_REVIEW → DENIED` and releases every account of the patient from `ASSISTANCE_HOLD` back to `NOTICE_PERIOD`. Both the determination's and the application's `version` increment by 1. Note that on approval the covered accounts remain in `ASSISTANCE_HOLD`; each account leaves the hold only when its own write-off adjustment posts.

Reversal of a `FINAL` determination — available to an `AssistanceReviewer` or a `ComplianceOfficer`, optionally carrying a `reason` — requires `FINAL` status (`ERR_DETERMINATION_NOT_FINAL`, HTTP 409), moves the determination `FINAL → REVERSED`, and triggers a three-link cascade. First, every `POSTED` write-off adjustment of this determination moves to `REVERSED` with `reversed_at` stamped; refund adjustments are left `POSTED`. Second, each affected account recomputes its `adjusted_balance_cents`, and any account that had been `RESOLVED` but now shows `amount_outstanding_cents` greater than zero transitions back to `NOTICE_PERIOD`. Third, if a community benefit report in `FILED` status exists whose `reporting_year` contains this determination's `finalized_at`, that report moves to `REOPENED` with `totals_stale` set true. The application itself returns `APPROVED → UNDER_REVIEW` for re-determination — the revision loop that makes determinations legitimately supersede one another, and the reason creation is OCC-guarded. Both the determination's and the application's `version` increment by 1.

### 3.9. Payments and the Account Ledger

A `BillingAdministrator` or the `Patient` themselves posts a payment against an account with `amount_cents` (strictly positive integer cents — zero or negative is `ERR_NONPOSITIVE_AMOUNT`, HTTP 422), a `paid_at` timestamp (which later drives refund waterfall ordering), and a `method` of `CARD`, `CHECK`, `ACH`, or `CASH`. Payments are a fiscal write, so the target account must not be `RESOLVED` (`ERR_ACCOUNT_RESOLVED`, HTTP 409). A new payment starts `POSTED` with `refunded_cents` at 0, and posting it recomputes the account's `effective_payments_cents`, `amount_outstanding_cents`, and `overpayment_cents` per §2.12 and increments the account's `version` by 1. If the payment brings `amount_outstanding_cents` to zero, the account's posture moves to `RESOLVED` and every `INITIATED` collection action on the account is halted with `halt_reason` `ACCOUNT_RESOLVED`.

### 3.10. Adjustments: Write-Offs, Refunds, and the Retroactive Waterfall

Once a determination is `FINAL`, a `BillingAdministrator` posts adjustments account by account, supplying the `determination_id` and — per §2.11 — the `expected_account_version`. The determination must exist (`ERR_DETERMINATION_NOT_FOUND`), must be `FINAL` (`ERR_DETERMINATION_NOT_FINAL`), must cover the target account (`ERR_ACCOUNT_NOT_COVERED`, HTTP 422), and the account must show `adjusted_balance_cents` greater than zero (`ERR_NO_COLLECTIBLE_BALANCE`). A duplicate guard rejects the operation if any other `POSTED` write-off adjustment already exists for the same account-and-determination pair (`ERR_DUPLICATE_ADJUSTMENT`, HTTP 409).

The write-off leg rounds per account first, then sums — this order is pinned. Each covered account's write-off amount is its creation-fixed `patient_responsibility_cents` (never the current `adjusted_balance_cents`) multiplied by the determination's `discount_pct` and divided by 100, rounded half-up to whole integer cents. The determination's total write-off is the sum of those already-rounded per-account integers, with no second rounding pass. The forbidden alternative — summing patient responsibilities first and rounding once — differs whenever per-account fractional cents cross an integer boundary in aggregate and must not be used. Posting the write-off creates an `AccountAdjustment` of `adjustment_type` `WRITE_OFF` in `POSTED` status with the rounded `amount_cents`, recomputes the account's `adjusted_balance_cents`, and increments the account's `version` by 1.

The refund leg follows for retro-eligible accounts. An account is retro-eligible when the application's `submitted_at` is at or before the account's `first_statement_at` plus the pinned policy's `retroactive_window_days`; if `first_statement_at` is still null the window has not started and the account is always eligible. The refund due is the account's post-write-off `overpayment_cents` computed per §2.12 — for a non-eligible account the refund due is zero, though the write-off still applies to the balance. When a refund is due, the waterfall consumes payments newest-first: the account's payments are walked in descending `paid_at` order with ties broken by ascending `created_at`; each visited payment yields room equal to its `amount_cents` minus its `refunded_cents` (a `FULLY_REFUNDED` payment therefore yields zero room); the grant for each payment is the smaller of its room and the remaining refund due; the grant is added to `refunded_cents`; the payment's status becomes `FULLY_REFUNDED` when `refunded_cents` reaches `amount_cents` and `PARTIALLY_REFUNDED` otherwise; and a `REFUND` `AccountAdjustment` is created recording the grant amount, the `payment_id` it drew from, and the determination. The walk stops when the remaining refund due reaches zero. A proportional-allocation alternative is expressly rejected: identical inputs must produce identical per-payment refunds, which only the chronological newest-first rule guarantees.

After both legs, the account's posture resolves: if `amount_outstanding_cents` is now zero, an account in `ASSISTANCE_HOLD` moves to `RESOLVED` and every `INITIATED` collection action on it is halted with `halt_reason` `ACCOUNT_RESOLVED`; if a balance remains, the account moves from `ASSISTANCE_HOLD` back to `NOTICE_PERIOD`.

Adjustments are durable with one asymmetry: a `WRITE_OFF` can be reversed only through reversal of its owning determination (§3.8), which stamps `reversed_at` and recomputes the account's `adjusted_balance_cents`; a `REFUND` adjustment is never reversible, and any reversal attempt against one is rejected with `ERR_REFUND_NOT_REVERSIBLE` (HTTP 409).

### 3.11. Collections Under 501(r): Posture, ECAs, Halts

An account's `collection_posture` walks a guarded path: `NOT_IN_COLLECTIONS → NOTICE_PERIOD → ECA_ELIGIBLE → ECA_ACTIVE`, with `ASSISTANCE_HOLD` as a freeze state and `RESOLVED` as the paid-off resting state. Beyond the statement issuance of §3.2, posture advances through evaluation: a `CollectionsAgent`, `BillingAdministrator`, or `ComplianceOfficer` may evaluate an account in `NOTICE_PERIOD` or `ASSISTANCE_HOLD` (any other posture is `ERR_POSTURE_NOT_EVALUABLE`, HTTP 409). The evaluation enforces the ECA clearance window of §2.9 — the notification period elapsed and an `ECA_WARNING` at least `eca_notice_days` old, both boundaries inclusive, else `ERR_ECA_NOTIFICATION_WINDOW_UNMET` — and confirms no open application exists for the patient (`ERR_ASSISTANCE_HOLD_ACTIVE`). When the gates pass, the account moves to `ECA_ELIGIBLE` and its `version` increments by 1.

Only an `ECA_ELIGIBLE` account may receive an extraordinary collection action; initiating against any other posture is rejected with `ERR_ACCOUNT_NOT_ECA_ELIGIBLE` (HTTP 409), and the clearance window is re-checked at initiation (`ERR_ECA_NOTIFICATION_WINDOW_UNMET`). A `CollectionsAgent` initiates the action by naming an `action_type` of `CREDIT_REPORT`, `LAWSUIT`, `WAGE_GARNISHMENT`, `LIEN`, or `SALE_TO_AGENCY`; the target must also show `amount_outstanding_cents` greater than zero (`ERR_NO_COLLECTIBLE_BALANCE`). Initiation creates the `CollectionAction` in `INITIATED` status with `initiated_at` and `initiated_by_user_id` stamped, moves the account `ECA_ELIGIBLE → ECA_ACTIVE`, and increments the account's `version` by 1.

An `INITIATED` action has two exits. Completion by a `CollectionsAgent` requires the action to be `INITIATED` and the owning account to be in `ECA_ACTIVE` or `ECA_ELIGIBLE` (`ERR_ACTION_NOT_INITIATED` and `ERR_ACCOUNT_NOT_IN_COLLECTIONS` respectively, both HTTP 409), moving the action to `COMPLETED`. A halt moves `INITIATED → HALTED`, stamps `halted_at`, and records a `halt_reason`: a `ComplianceOfficer` halts explicitly and may supply a free-text `reason`, while the system halts automatically — with `halt_reason` `ACCOUNT_RESOLVED` — when the account becomes `RESOLVED` through payment or write-off, as described in §3.9 and §3.10. Halting an action that is not `INITIATED` is rejected with `ERR_ACTION_NOT_INITIATED`.

### 3.12. Community Benefit Reporting

A `ComplianceOfficer` opens a community benefit report for a calendar `reporting_year`, unique across all reports (`ERR_REPORT_YEAR_DUPLICATE`, HTTP 409). Creation computes the initial totals immediately and leaves the report `OPEN` with `totals_stale` false.

The aggregation sweeps `POSTED` adjustments only — `REVERSED` rows are excluded — whose determination's `finalized_at` falls in the half-open year window from January 1 of the reporting year up to (but excluding) January 1 of the following year; `finalized_at` is thus the membership key for the reporting year. Within that sweep, `total_write_offs_cents` sums `amount_cents` over `WRITE_OFF` rows, `total_standard_write_offs_cents` restricts the same sum to determinations with `basis` `VERIFIED_APPLICATION`, `total_presumptive_write_offs_cents` restricts it to `basis` `PRESUMPTIVE_SCORE`, `total_refunds_cents` sums `amount_cents` over `REFUND` rows, and `accounts_assisted_count` counts the distinct account ids having at least one `POSTED` write-off in the window. All figures are integer cents with no rounding.

Filing by a `ComplianceOfficer` requires the report to be `OPEN` or `REOPENED` (`ERR_REPORT_NOT_FILEABLE`, HTTP 409) and requires `totals_stale` to be false (`ERR_REPORT_TOTALS_STALE`, HTTP 409); a successful file stamps `filed_at` from the logical clock. A `FILED` report may be reopened explicitly by a `ComplianceOfficer` (reopening anything else is `ERR_REPORT_NOT_FILED`, HTTP 409), and is also reopened automatically when a determination reversal touches its reporting year per §3.8 — either path sets `totals_stale` true, blocking refiling. Recompute is the only way to clear the flag: it re-runs the full aggregation from the `POSTED` adjustment ledger and sets `totals_stale` false, after which the report may be filed again. The amendment cycle is `OPEN → FILED → REOPENED → FILED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource in place, drive a state transition, or run an evaluation return `200 OK`. All endpoints are mounted under `/charity-care`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/charity-care/_clock/set_current_utc` | Set the server logical clock | ComplianceOfficer |
| POST | `/charity-care/policies` | Create a FinancialAssistancePolicy in DRAFT | ComplianceOfficer |
| GET | `/charity-care/policies/{id}` | Fetch one policy | FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| POST | `/charity-care/policies/{id}/activate` | Activate a DRAFT policy; supersedes the currently ACTIVE policy | ComplianceOfficer |
| POST | `/charity-care/patients` | Register a patient | FinancialCounselor, ComplianceOfficer |
| GET | `/charity-care/patients/{id}` | Fetch one patient | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| GET | `/charity-care/patients/{id}/accounts` | List accounts of a patient | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| GET | `/charity-care/patients/{id}/applications` | List applications of a patient | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| POST | `/charity-care/accounts` | Create a patient account (encounter charges) | BillingAdministrator |
| GET | `/charity-care/accounts/{id}` | Fetch one account | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| POST | `/charity-care/accounts/{id}/statements` | Issue the FIRST_STATEMENT notice exactly once | BillingAdministrator |
| POST | `/charity-care/accounts/{id}/payments` | Post a patient payment | BillingAdministrator, Patient |
| GET | `/charity-care/accounts/{id}/payments` | List payments of an account | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| POST | `/charity-care/accounts/{id}/adjustments` | Post the write-off (and refund waterfall) for a FINAL determination | BillingAdministrator |
| GET | `/charity-care/accounts/{id}/adjustments` | List adjustments of an account | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| POST | `/charity-care/accounts/{id}/notices` | Issue a PLAIN_LANGUAGE_SUMMARY or ECA_WARNING notice | BillingAdministrator |
| GET | `/charity-care/accounts/{id}/notices` | List notices of an account | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| POST | `/charity-care/accounts/{id}/collection-actions` | Initiate an extraordinary collection action | CollectionsAgent |
| GET | `/charity-care/accounts/{id}/collection-actions` | List collection actions of an account | FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| POST | `/charity-care/accounts/{id}/evaluate-posture` | Evaluate temporal gates toward ECA_ELIGIBLE | CollectionsAgent, BillingAdministrator, ComplianceOfficer |
| POST | `/charity-care/collection-actions/{id}/halt` | Compliance halt of an INITIATED collection action | ComplianceOfficer |
| POST | `/charity-care/collection-actions/{id}/complete` | Mark an INITIATED collection action completed | CollectionsAgent |
| POST | `/charity-care/applications` | Create an assistance application in DRAFT | Patient, FinancialCounselor |
| GET | `/charity-care/applications` | List applications with pagination and filters | FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| GET | `/charity-care/applications/{id}` | Fetch one application | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| POST | `/charity-care/applications/{id}/submit` | Submit a DRAFT application; pins policy snapshot; freezes ECA posture | Patient, FinancialCounselor |
| POST | `/charity-care/applications/{id}/withdraw` | Withdraw a non-terminal application | Patient, FinancialCounselor |
| POST | `/charity-care/applications/{id}/begin-review` | Move SUBMITTED to UNDER_REVIEW | FinancialCounselor |
| POST | `/charity-care/applications/{id}/request-documents` | Move UNDER_REVIEW to PENDING_DOCUMENTS with doc list and deadline | FinancialCounselor |
| POST | `/charity-care/applications/{id}/resume-review` | Move PENDING_DOCUMENTS to UNDER_REVIEW when docs are verified | FinancialCounselor |
| POST | `/charity-care/applications/{id}/expire` | Expire a PENDING_DOCUMENTS application past its deadline | FinancialCounselor |
| POST | `/charity-care/applications/{id}/members` | Add a household member to a DRAFT application | Patient, FinancialCounselor |
| GET | `/charity-care/applications/{id}/members` | List household members of an application | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| POST | `/charity-care/applications/{id}/documents` | Upload a verification document | Patient, FinancialCounselor |
| GET | `/charity-care/applications/{id}/notices` | List notices of an application | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| POST | `/charity-care/applications/{id}/presumptive-screening` | Run presumptive eligibility scoring (1:1 per application) | FinancialCounselor |
| GET | `/charity-care/applications/{id}/presumptive-screening` | Fetch the screening of an application | FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| GET | `/charity-care/documents/{id}` | Fetch one verification document | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| GET | `/charity-care/documents` | List documents filtered by application and/or household member | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| POST | `/charity-care/documents/{id}/verify` | Verify a SUBMITTED document | FinancialCounselor |
| POST | `/charity-care/documents/{id}/reject` | Reject a SUBMITTED document | FinancialCounselor |
| POST | `/charity-care/determinations` | Create a PRELIMINARY determination (OCC-guarded) | AssistanceReviewer |
| GET | `/charity-care/determinations` | List determinations | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| GET | `/charity-care/determinations/{id}` | Fetch one determination | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| POST | `/charity-care/determinations/{id}/finalize` | Finalize a PRELIMINARY determination | AssistanceReviewer |
| POST | `/charity-care/determinations/{id}/reverse` | Reverse a FINAL determination | AssistanceReviewer, ComplianceOfficer |
| GET | `/charity-care/determinations/{id}/adjustments` | List adjustments spawned by a determination | FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| GET | `/charity-care/adjustments/{id}` | Fetch one adjustment | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| GET | `/charity-care/adjustments` | List adjustments filtered by account / determination / payment | Patient, FinancialCounselor, AssistanceReviewer, BillingAdministrator, ComplianceOfficer |
| POST | `/charity-care/community-benefit-reports` | Create an OPEN report for a reporting year | ComplianceOfficer |
| GET | `/charity-care/community-benefit-reports/{id}` | Fetch one report | FinancialCounselor, AssistanceReviewer, BillingAdministrator, CollectionsAgent, ComplianceOfficer |
| POST | `/charity-care/community-benefit-reports/{id}/file` | File an OPEN or REOPENED report | ComplianceOfficer |
| POST | `/charity-care/community-benefit-reports/{id}/reopen` | Reopen a FILED report for amendment | ComplianceOfficer |
| POST | `/charity-care/community-benefit-reports/{id}/recompute` | Recompute totals and clear the stale flag | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_DETERMINATION_NOT_FOUND` | 404 |
| `ERR_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_ACTION_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_APPLICATION_NOT_DRAFT` | 409 |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 |
| `ERR_APPLICATION_NOT_UNDER_REVIEW` | 409 |
| `ERR_APPLICATION_NOT_PENDING_DOCUMENTS` | 409 |
| `ERR_APPLICATION_TERMINAL` | 409 |
| `ERR_DOCUMENT_NOT_SUBMITTED` | 409 |
| `ERR_DETERMINATION_NOT_PRELIMINARY` | 409 |
| `ERR_DETERMINATION_NOT_FINAL` | 409 |
| `ERR_POLICY_NOT_DRAFT` | 409 |
| `ERR_POSTURE_NOT_EVALUABLE` | 409 |
| `ERR_ACCOUNT_NOT_ECA_ELIGIBLE` | 409 |
| `ERR_ASSISTANCE_HOLD_ACTIVE` | 409 |
| `ERR_ACCOUNT_RESOLVED` | 409 |
| `ERR_ACTION_NOT_INITIATED` | 409 |
| `ERR_ACCOUNT_NOT_IN_COLLECTIONS` | 409 |
| `ERR_REPORT_NOT_FILEABLE` | 409 |
| `ERR_REPORT_NOT_FILED` | 409 |
| `ERR_REPORT_TOTALS_STALE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ECA_NOTIFICATION_WINDOW_UNMET` | 422 |
| `ERR_DOC_DEADLINE_NOT_REACHED` | 422 |
| `ERR_INVALID_PERIOD` | 422 |
| `ERR_POLICY_WINDOW_OVERLAP` | 409 |
| `ERR_DOC_PERIOD_OVERLAP` | 409 |
| `ERR_DUPLICATE_MRN` | 409 |
| `ERR_DUPLICATE_POLICY_CODE` | 409 |
| `ERR_REPORT_YEAR_DUPLICATE` | 409 |
| `ERR_DUPLICATE_OPEN_APPLICATION` | 409 |
| `ERR_SCREENING_ALREADY_EXISTS` | 409 |
| `ERR_FIRST_STATEMENT_ALREADY_ISSUED` | 409 |
| `ERR_HOUSEHOLD_SELF_REQUIRED` | 422 |
| `ERR_NO_ACTIVE_POLICY` | 409 |
| `ERR_DOCS_OUTSTANDING` | 422 |
| `ERR_INSUFFICIENT_FACTORS` | 422 |
| `ERR_MEMBER_APPLICATION_MISMATCH` | 422 |
| `ERR_ACCOUNT_PATIENT_MISMATCH` | 422 |
| `ERR_VERIFIED_DOCS_REQUIRED` | 422 |
| `ERR_PRESCREEN_BELOW_THRESHOLD` | 422 |
| `ERR_ACCOUNT_NOT_COVERED` | 422 |
| `ERR_DUPLICATE_ADJUSTMENT` | 409 |
| `ERR_INSURANCE_EXCEEDS_CHARGES` | 422 |
| `ERR_NONPOSITIVE_AMOUNT` | 422 |
| `ERR_NO_COLLECTIBLE_BALANCE` | 422 |
| `ERR_REFUND_NOT_REVERSIBLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
