# SNAP / EBT Food Stamps API — Product Requirements Document

## 1. Introduction

The Supplemental Nutrition Assistance Program (SNAP) is the country's largest anti-hunger benefit, and the system described here is the back-office service that runs a state agency's day-to-day SNAP operation. The product is **not** a public-facing portal: its consumers are state caseworkers who certify households, head-of-household applicants who file paperwork and use the resulting electronic benefit transfer (EBT) card, SNAP-authorized retailers who settle purchases at point-of-sale, fraud investigators who open and adjudicate misuse cases, and state administrators who onboard merchants and declare disaster-period Emergency Allotments. Each constituency interacts with the same household record from a different angle, and the API must keep all of those angles consistent in real time.

Three pieces of domain complexity make this engagement substantive rather than CRUD-shaped. First, the **net-income / monthly-allotment computation** is a multi-step deduction chain whose intermediate rounding ordering changes the dollar outcome; this is where the program's eligibility cliff actually lives. Second, the **household-Application-EbtCard-BenefitLedger cascade** is a chain of side effects three levels deep — approving an application materializes a card and seeds the month's allotment as a ledger credit, with the card balance derived from the ledger sum. Third, the **ABAWD work-training waiver** and **Emergency Allotment** features overlay time-windowed rules (the 90-day fraud appeal window, the 24-hour transaction reversal window, the 12-month certification period, the rolling 30-day fraud score window) on top of the steady-state benefit machinery; a single clock-advance can move multiple resources into terminal states simultaneously.

This document is the engineering contract for that service. §2 specifies cross-cutting rules — authentication, response envelope, pagination, rounding, optimistic concurrency, and the structural invariants that hold across every resource. §3 walks the business workflows in narrative form. §4 enumerates the HTTP surface, and §5 catalogues every error identifier the system can return.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request — except the two test-driving endpoints under `/_clock/advance` and `/_sweep/run`, which are also gated but on a separate principal — must carry two headers: `X-User-ID` and `X-User-Role`. Both must be present and non-empty; missing either yields `ERR_AUTH_MISSING` with HTTP 401. Once the headers are present, the server checks whether the supplied role is permitted for the requested endpoint per the RBAC table in §4; a mismatch yields `ERR_FORBIDDEN` with HTTP 403.

There are six role names, used verbatim:

- **`Caseworker`** — a state-agency employee who runs the application lifecycle, manages members, administers cards, edits expense fields, and approves or rejects ABAWD waivers.
- **`HouseholdHead`** — the head of an applicant or recipient household; files applications, activates and replaces cards, and appeals fraud findings.
- **`Merchant`** — a SNAP-authorized retailer that submits purchase transactions and reverses them within the allowed window.
- **`FraudInvestigator`** — a state fraud-investigation officer who opens, assigns, substantiates, dismisses, appeals, reopens, and closes fraud cases, and may also suspend cards.
- **`StateAdministrator`** — a state-level administrator who onboards merchants, edits their authorization status, and creates and disburses Emergency Allotment declarations.
- **`SystemTest`** — a test-fixture principal used only by the clock-advance and sweep endpoints; it never appears in normal traffic.

Role identity binds to `X-User-ID` as follows. When `X-User-Role` is `HouseholdHead`, `X-User-ID` is the `id` of the acting `Household`; any ownership check on a household-scoped resource compares the resource's `household_id` to `X-User-ID`, and an attempt by a `HouseholdHead` to read or mutate another household's data yields `ERR_FORBIDDEN`. When `X-User-Role` is `Merchant`, `X-User-ID` is the `id` of the acting `Merchant`; a `Merchant` principal may only post or reverse transactions whose body `merchant_id` matches `X-User-ID`, and may only `GET` transactions and merchants tied to that same id. When `X-User-Role` is `Caseworker`, `FraudInvestigator`, `StateAdministrator`, or `SystemTest`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `investigator_user_id` on a `FraudCase` when a fraud officer assigns themselves a case) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). Values outside these ranges, or non-integer values, are rejected with `ERR_VALIDATION` (HTTP 400). Results are sorted by `created_at` ascending, and the response `meta` block carries `limit`, `offset`, `total_count`, and `has_more` populated against the filter set the request produced.

### 2.4. Common Resource Properties

Every resource that the scaffold marks as carrying common fields — `Household`, `Member`, `Application`, `EbtCard`, `Merchant`, `FraudCase`, `AbawdWaiver`, and `EmergencyAllotment` — exposes four shared properties. The `id` is a server-minted UUID with no type prefix and no embedded structure. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set on resource insertion and never changes, while `updated_at` is refreshed on every mutation (including indirect mutations driven by cascades from another entity). `version` is a non-negative integer that starts at 1 and increments by exactly 1 on every mutation that changes any persisted field on the entity. A pure `GET` does not bump `version`; a cascade-driven recompute that materially changes a field (for example, `Household.gross_monthly_income_cents` after a `Member` income edit) does bump it.

`BenefitLedger` and `Transaction` are append-only event records and do **not** carry `updated_at` or `version`; only `id` and `created_at` are present on those entities. The `Clock` singleton likewise has no `updated_at` or `version` — it is identified by the fixed id `GLOBAL_CLOCK` and exposes only `now` as a monotonic non-decreasing ISO 8601 UTC timestamp.

In addition, `Household` carries the public-facing identifier `case_number` minted by the server on creation, formatted as `SNAP-YYYY-NNNNNN` (the prefix `SNAP-`, four digits for the year, and six zero-padded sequence digits), and immutable thereafter.

### 2.5. Precision, Rounding, and the Per-Step vs. Sum-Then-Round Distinction

All monetary fields end in `_cents` and are stored as integer cents — there are no fractional-cent values on disk. Three computations introduce rounding, and the ordering is **load-bearing**:

- **Net-income calculation.** Each numbered deduction step that produces a non-integer intermediate (the 20% earned-income deduction and the half-of-adjusted-income value used in the excess-shelter test) is rounded half-up to a whole cent **before** being combined into the next step. Per-step rounding of the half-of-adjusted-income value, in particular, is applied **before** the subtraction that yields the raw excess-shelter amount.
- **Monthly-allotment calculation.** The expected-contribution figure (30% of net monthly income) is rounded half-up to a whole cent once, and that single rounded value is then subtracted from the household-size maximum.
- **Fraud score.** The three weighted signals are first **summed as raw real numbers**, and the **final sum** is rounded half-up to two decimal places. Rounding is applied **once, at the end** — never per signal — and this is the deliberate opposite of the net-income chain.

### 2.6. Optimistic Concurrency Control

All `PATCH` and `PUT` endpoints accept an optional `version` field in the request body. When the client supplies it, the server compares the supplied value against the current `version` of the target entity and the request only succeeds if they match; on success, `version` is incremented by 1 and the new value appears in the response. When supplied values disagree, the server returns `ERR_VERSION_CONFLICT` with HTTP 409 and applies no mutation. When the client omits `version` from the body entirely, the version check is skipped and the mutation proceeds against whatever value is current.

### 2.7. Nested Resource Retrieval and Path Validation

URL paths follow a strict left-to-right containment hierarchy: a `Member` lives under its `Household`, an `Application` lives under its `Household`, an `EbtCard` lives under its `Household`, an `AbawdWaiver` lives under its `Member` (which in turn lives under a `Household`), and so on. Path segments are validated in order, from outermost to innermost: if `/households/{id}/members/{memberId}` is requested with an unknown `id`, the response is `ERR_NOT_FOUND` against the household — the server does not "skip ahead" to the member id. Once the path is resolved, body-supplied foreign keys such as `household_id`, `member_id`, `card_id`, or `merchant_id` are validated next; references to nonexistent rows yield `ERR_REFERENCE_NOT_FOUND` (HTTP 422).

### 2.8. Cascades, `updated_at`, and `version` Propagation

Several operations in this domain mutate more than one entity in a single logical step. The general rule is: when an operation produces a side effect on a related entity, that entity's `updated_at` is refreshed and its `version` is incremented exactly once for the change. The principal cascades are:

- **Application approval** materializes a `REGULAR_ALLOTMENT` `BenefitLedger` credit for the current `benefit_month`, auto-issues an `EbtCard` (if none currently exists in `ISSUED`, `ACTIVE`, or `SUSPENDED`), and recomputes the card's `balance_cents`. The household's `certification_status`, `certification_period_end`, and `monthly_allotment_cents` are also refreshed.
- **EbtCard replacement** creates a new card in `ISSUED`, marks the old card's `replaced_by_card_id` to the new card's `id`, and posts two `ADJUSTMENT` ledger entries (a negative entry on the old card equal to its current `balance_cents`, a positive entry of the same magnitude on the new card) so the balance migrates atomically.
- **Application closing** (whether manually triggered or auto-closed by the sweep when `Clock.now` is at or past `certification_period_end_at`) transitions any `ACTIVE` `EbtCard` for that household into `CLOSED` and forfeits its remaining `balance_cents` to zero via an `ADJUSTMENT` entry.
- **Substantiating a fraud case** transitions every `ACTIVE` `EbtCard` of the affected household to `SUSPENDED`; upholding the household's appeal restores those same suspended cards back to `ACTIVE`.
- **Disbursing an Emergency Allotment** posts one `EMERGENCY_ALLOTMENT` `BenefitLedger` entry per qualifying household and recomputes each affected card's `balance_cents`.
- **Mutating any `Member` field that feeds the income aggregate** (`earned_income_cents`, `unearned_income_cents`, `is_disabled`, `is_pregnant`, `date_of_birth`, or the `status` toggle on deactivate) recomputes `Household.household_size`, `Household.gross_monthly_income_cents`, `Household.has_elderly_or_disabled`, `Household.net_monthly_income_cents`, and `Household.monthly_allotment_cents`, and refreshes the household's `updated_at`/`version` accordingly.

### 2.9. Ledger Invariant

`EbtCard.balance_cents` is **derived**, never stored independently of the ledger. At all times, `balance_cents` for a card equals the sum of `amount_cents` over every `BenefitLedger` entry whose `card_id` points to that card. Credit entry types (`REGULAR_ALLOTMENT`, `EMERGENCY_ALLOTMENT`, `REFUND`, positive `ADJUSTMENT`) are stored with positive `amount_cents`; debit entries (`PURCHASE`, negative `ADJUSTMENT`) are stored with negative `amount_cents`. The ledger is append-only — entries are never edited or deleted — so balance corrections are made by posting new offsetting rows, never by mutating history. Each entry carries a `benefit_month` (a `YYYY-MM` string) and an optional `reference_id` (the `Transaction.id` for `PURCHASE` and `REFUND` entries; null otherwise).

### 2.10. Time, Clock, and the Sweep

The server keeps a single logical clock at id `GLOBAL_CLOCK`. Its `now` value is monotonic non-decreasing — it can only stay the same or move forward, never backward. An admin-only test-driving capability advances this clock to a supplied `to_iso8601` instant; subsequent reads then re-evaluate any time-derived status (`Member.abawd_status` from the current age and waiver window, `Application` auto-close eligibility, `EbtCard` reversal-window eligibility, `FraudCase` appeal-window eligibility). A separate sweep capability performs the eager versions of those re-evaluations in one pass: every `Application` in `APPROVED` whose `certification_period_end_at` is at or before `Clock.now` transitions to `CLOSED` (cascading the card-close described in §2.8); every `AbawdWaiver` in `APPROVED` whose `effective_to` is at or before `Clock.now` transitions to `EXPIRED` (and the affected `Member.abawd_status` is recomputed, typically returning to `ABAWD_SUBJECT`); every `FraudCase` in `SUBSTANTIATED` whose `opened_at` is more than 90 days behind `Clock.now` transitions to `CLOSED`.

### 2.11. Enumerations

Several fields carry constrained enumerations; the exact spellings below are normative:

- `Household.state_code` and `EmergencyAllotment.state_code`: one of `CA`, `TX`, `NY`, `FL`, `IL`, `PA`, `OH`, `GA`, `NC`, `MI`.
- `Household.certification_status`: one of `PENDING`, `APPROVED`, `DENIED`, `CLOSED` (or `null` before any application has been filed).
- `Member.abawd_status`: one of `NOT_ABAWD`, `ABAWD_EXEMPT`, `ABAWD_WAIVED`, `ABAWD_SUBJECT`. `Member.status` is one of `ACTIVE` or `REMOVED`.
- `Application.state`: one of `DRAFT`, `SUBMITTED`, `PENDING_INTERVIEW`, `INTERVIEW_DONE`, `APPROVED`, `DENIED`, `CLOSED`. `Application.denial_reason`: one of `INCOME_OVER_LIMIT`, `INCOMPLETE_INFO`, `IDENTITY_FAILURE`, `OTHER` (nullable).
- `EbtCard.status`: one of `ISSUED`, `ACTIVE`, `SUSPENDED`, `REPLACED`, `CLOSED`.
- `BenefitLedger.entry_type`: one of `REGULAR_ALLOTMENT`, `EMERGENCY_ALLOTMENT`, `PURCHASE`, `REFUND`, `ADJUSTMENT`.
- `Transaction.status`: one of `PENDING`, `APPROVED`, `DECLINED`, `REVERSED`. `Transaction.decline_reason`: one of `INSUFFICIENT_FUNDS`, `CARD_NOT_ACTIVE`, `MERCHANT_NOT_AUTHORIZED`, `ALL_ITEMS_INELIGIBLE` (null when status is not `DECLINED`).
- `Transaction.line_items` entries carry an `item_category` that is one of `STAPLE`, `PRODUCE`, `DAIRY`, `MEAT`, `BREAD`, `COLD_PREPARED`, `HOT_PREPARED`, `NON_FOOD`, `ALCOHOL`, `TOBACCO`, plus `unit_price_cents` and `quantity`. A transaction must carry between 1 and 50 line items inclusive.
- `Merchant.snap_authorization_status`: one of `AUTHORIZED`, `SUSPENDED`, `REVOKED`.
- `FraudCase.state`: one of `OPEN`, `UNDER_REVIEW`, `SUBSTANTIATED`, `UNFOUNDED`, `APPEAL_PENDING`, `CLOSED`. `FraudCase.trigger_reason`: one of `TRAFFICKING_PATTERN`, `DUPLICATE_BENEFITS`, `IDENTITY_MISMATCH`, `MANUAL_REPORT`.
- `AbawdWaiver.state`: one of `REQUESTED`, `APPROVED`, `REJECTED`, `EXPIRED`. `AbawdWaiver.waiver_kind`: one of `WORK_TRAINING_ENROLLED`, `MEDICALLY_UNFIT`, `CAREGIVER`, `AREA_HIGH_UNEMPLOYMENT`. `AbawdWaiver.decision_reason`: one of `INSUFFICIENT_DOCS`, `INELIGIBLE_CATEGORY`, `OTHER`, nullable, required on `REJECTED`.
- `EmergencyAllotment.state`: one of `DRAFT`, `DECLARED`, `DISBURSED`, `CANCELLED`.

### 2.12. Validation Priority

When multiple validations apply to the same endpoint, they are evaluated in this order — earlier checks short-circuit later ones, so the error returned to the client is determined by the **first** failing check:

1. Header presence (`ERR_AUTH_MISSING`).
2. Role authorization (`ERR_FORBIDDEN`).
3. Path-resource existence, validated left-to-right (`ERR_NOT_FOUND`).
4. Body-supplied foreign-key existence (`ERR_REFERENCE_NOT_FOUND`).
5. Request-body schema (`ERR_VALIDATION`) — types, required fields, enum values, and pagination bounds.
6. Optimistic concurrency on `PATCH`/`PUT` (`ERR_VERSION_CONFLICT`).
7. Target-entity state compatibility with the requested transition (`ERR_INVALID_STATE`).
8. Domain-specific business rules — fraud holds, merchant authorization, ABAWD eligibility, income limits, balance checks, card uniqueness, EA disbursement uniqueness, reversal/appeal/waiver time windows, EA duplicate keys, and the all-items-ineligible edge — each with its dedicated `error_id`.

Within the domain-business band, the ordering described in §3 around each workflow is also normative — for example, the all-items-ineligible check fires **before** the insufficient-funds check on a purchase, so a zero-eligible cart against a zero-balance card returns `ERR_ALL_ITEMS_INELIGIBLE` rather than `ERR_INSUFFICIENT_FUNDS`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Household

The household record is the root of almost everything in this system, so the entry point — opening a new case — is intentionally narrow. A `Caseworker` creates the empty household by supplying the two-letter `state_code`, the 5-digit residential `address_zip`, and optionally seed values for `dependent_care_expense_cents` and `shelter_expense_cents` (both default to 0 and must be non-negative integer cents). The server mints the `case_number` in `SNAP-YYYY-NNNNNN` format using the current year and the next sequence number, and the value is immutable for the life of the case.

At creation there are no members, so the computed aggregates start at their identity values: `household_size` is 0, `gross_monthly_income_cents` is 0, `has_elderly_or_disabled` is false, `net_monthly_income_cents` is 0, `monthly_allotment_cents` is 0, and `certification_status` is null. The state of the household is "open file, not yet certified." A caseworker can adjust `state_code`, `address_zip`, `dependent_care_expense_cents`, and `shelter_expense_cents` later via a household update; if either expense field changes, the server immediately recomputes `net_monthly_income_cents` and `monthly_allotment_cents` so subsequent reads reflect current eligibility math.

### 3.2. Composing the Roster and Computing Income

Members are added one at a time under the household. A new `Member` requires `full_name` (1–100 characters) and `date_of_birth`; flags `is_disabled` and `is_pregnant` default to false, and `earned_income_cents` and `unearned_income_cents` default to 0. Every member starts with `status` = `ACTIVE` and remains so until a caseworker deactivates them, at which point `status` flips to `REMOVED`. Deactivated members are not removed from the database — the row persists for audit — but they no longer count toward the household.

The household's computed aggregates are derived strictly from members in `ACTIVE` status. The `household_size` is the count of those active members. The `gross_monthly_income_cents` is the sum of every active member's `earned_income_cents` plus `unearned_income_cents`. The `has_elderly_or_disabled` flag is true when at least one active member is age 60 or older at `Clock.now`, or has `is_disabled` set to true. All three values recompute whenever a member is added, edited, deactivated, or whenever any income/disability/dob field changes.

The **net monthly income** is the meaningful eligibility figure, derived from gross income by a fixed sequence of deductions whose intermediate rounding ordering is preserved verbatim. The computation runs as follows:

1. Compute `gross` as the sum of `earned_income_cents` plus `unearned_income_cents` over every active member. Compute `earned` as the sum of `earned_income_cents` alone over the same set.
2. Apply the **standard deduction** by household size, drawn from a fixed table: for households of size 1, 2, or 3, the deduction is 19,300 cents; for size 4 it is 20,600 cents; for size 5 it is 24,100 cents; for size 6 it is 27,600 cents. For any household of size 7 or larger, the size-6 row is used (the table is capped at 6).
3. Apply the **earned-income deduction**, computed as `earned` multiplied by twenty percent (0.20) and then rounded half-up to a whole cent. This rounded value is the deduction.
4. Apply the **dependent-care deduction**, which is the lesser of `dependent_care_expense_cents` and a fixed cap of 25,000 cents.
5. Form the **adjusted income** by subtracting the standard, earned-income, and dependent-care deductions from `gross` and flooring the result at zero (negative intermediates become 0).
6. Apply the **excess-shelter test** with per-step rounding pinned: first take half of the adjusted income (`adjusted_income` divided by 2) and round that half value half-up to a whole cent, **then** subtract that rounded half from `shelter_expense_cents` to produce a raw excess-shelter figure. If the raw figure is negative, the shelter deduction is 0; otherwise the deduction equals that raw figure subject to a cap: for households **without** an elderly or disabled member the cap is 67,200 cents (the lesser of the raw figure and 67,200 cents is taken), and for households **with** an elderly or disabled member the cap does not apply — the deduction is the full raw figure regardless of size.
7. The **net monthly income** equals the adjusted income minus the shelter deduction, again floored at zero.

This single calculation is the foundation of certification eligibility, the monthly allotment, and the gross/net cliffs that block approval; it recomputes on every input change that touches its inputs (member add, member edit on income/disability/dob/pregnancy, member deactivate, household expense edit, and as an inline precondition check at application approval time).

### 3.3. From Draft Application to Certified Household

A `HouseholdHead` or `Caseworker` opens an `Application` against the household; it begins in `DRAFT` with no other fields populated. The applicant or a caseworker then submits the draft, advancing the application from `DRAFT` to `SUBMITTED`. Submission requires at least one active member on the household roster and both `address_zip` and `state_code` to be present — without these the transition fails with `ERR_INVALID_STATE`. On success the server records `submitted_at` as `Clock.now` and bumps the household's `certification_status` to `PENDING`.

A caseworker then schedules the interview, transitioning the application from `SUBMITTED` to `PENDING_INTERVIEW`. The interview is later marked complete, transitioning from `PENDING_INTERVIEW` to `INTERVIEW_DONE` and recording `interview_completed_at`. If during the submitted phase the caseworker notices missing information, returning the application for correction reverts it from `SUBMITTED` back to `DRAFT`: `submitted_at` is cleared back to null, and the household's `certification_status` is set back to null **only** if no other approved application exists for this household.

Approval is the workflow's load-bearing decision. The transition runs from `INTERVIEW_DONE` to `APPROVED` and is allowed only when (a) `interview_completed_at` is non-null, (b) the gross-income test passes, and (c) the net-income test passes. The **gross-income test** is satisfied when `gross_monthly_income_cents` is at or below the gross-income limit for the household size, **or** when `has_elderly_or_disabled` is true — households with an elderly or disabled member bypass the gross test entirely. The gross limit is drawn from a fixed table at 130% of federal poverty level: 162,200 cents for size 1, 218,800 cents for size 2, 275,400 cents for size 3, 332,000 cents for size 4, 388,600 cents for size 5, and 445,200 cents for size 6; household sizes of 7 or larger use the size-6 row. A failure here yields `ERR_GROSS_INCOME_OVER_LIMIT`. The **net-income test** is satisfied when `net_monthly_income_cents` is at or below the net-income limit for the household size, drawn from the parallel 100%-of-FPL table: 124,800 cents for size 1, 168,300 cents for size 2, 211,800 cents for size 3, 255,400 cents for size 4, 298,900 cents for size 5, and 342,400 cents for size 6; sizes of 7 or larger again use the size-6 row. A failure here yields `ERR_NET_INCOME_OVER_LIMIT`. Both checks use **inclusive** comparisons — a household whose net income equals the limit exactly is approved, not rejected.

On a successful approval, the server performs the full cascade described in §2.8: `decision_at`, `certification_period_start_at` (equal to `decision_at`), and `certification_period_end_at` (exactly 12 months after `decision_at`) are stamped on the application; `Household.certification_status` becomes `APPROVED` and `Household.certification_period_end` is set to the new `certification_period_end_at`; the **monthly allotment** is recomputed; and if no `EbtCard` currently exists in `ISSUED`, `ACTIVE`, or `SUSPENDED`, a new one is auto-issued in `ISSUED` and a `REGULAR_ALLOTMENT` `BenefitLedger` entry is posted to it for the current `benefit_month` (the `YYYY-MM` string derived from `Clock.now`). The card's `balance_cents` is then recomputed from the ledger.

Denial runs from `INTERVIEW_DONE` to `DENIED` and requires the caseworker to supply a `denial_reason`; absent that, the request fails. On success `decision_at` is stamped and `Household.certification_status` becomes `DENIED`. Closing an approved application — either manually by a caseworker or automatically by the sweep at expiry — transitions it from `APPROVED` to `CLOSED`, flips `Household.certification_status` to `CLOSED`, and cascades any `ACTIVE` `EbtCard` into `CLOSED` (with its remaining balance forfeited to zero as described in §2.8).

The **monthly allotment** itself is a smaller computation. The household-size maximum is drawn from a fixed table — 29,100 cents for size 1, 53,500 cents for size 2, 76,600 cents for size 3, 97,300 cents for size 4, 115,500 cents for size 5, and 138,600 cents for size 6, with sizes of 7 or larger using the size-6 row. The **expected contribution** is 30% of `net_monthly_income_cents`, rounded half-up to a whole cent. The **raw allotment** equals the household-size maximum minus the expected contribution, floored at zero. A **minimum benefit floor** of 2,300 cents applies for households of size 1 or 2 only: if the raw allotment is below 2,300 cents for those sizes, the final allotment is lifted to 2,300 cents; otherwise the final allotment equals the raw allotment. For households of size 3 or larger, the floor never applies — a raw allotment below 2,300 cents is the final allotment for those households. This value is recomputed on application approval, on every change to `net_monthly_income_cents`, and on every change to `household_size`.

### 3.4. Card Lifecycle and Manual Issuance

A `Household` may hold **at most one** card whose `status` is `ISSUED`, `ACTIVE`, or `SUSPENDED` at any time. If a caseworker attempts to issue a card while another exists in any of those three statuses, the second issuance is rejected with `ERR_CARD_ALREADY_EXISTS`. The same uniqueness rule also defends against two parallel issuance calls racing — the first writer wins and the loser receives `ERR_CARD_ALREADY_EXISTS`. Cards in `REPLACED` or `CLOSED` are terminal for the purposes of this rule and do not block a new issuance. Additionally, when the household has any `FraudCase` currently in `SUBSTANTIATED`, new card issuance is blocked with `ERR_FRAUD_HOLD` — the same fraud-hold response surfaces on card resume (§3.4 above) and on Emergency Allotment disbursement (§3.9 below); these are the three operations the substantiated-fraud hold guards.

On creation, the card is in `ISSUED`, the server stamps `issued_at` to `Clock.now`, and `card_number_last4` is minted as four digits (the actual PAN is **never** stored). Activation, performed by the `HouseholdHead`, transitions the card from `ISSUED` to `ACTIVE` and stamps `activated_at` as `Clock.now`; activation requires the household's `certification_status` to be `APPROVED`. A caseworker (or fraud investigator) may suspend a card from `ACTIVE` to `SUSPENDED`; while suspended, any incoming transaction is declined with `ERR_CARD_NOT_ACTIVE`. A caseworker may resume the card from `SUSPENDED` back to `ACTIVE` only when no `FraudCase` for the same household is in `SUBSTANTIATED`; if a substantiated case exists, resume fails with `ERR_FRAUD_HOLD`.

Replacement is the operationally heaviest card transition. Either a `HouseholdHead` or a `Caseworker` may replace an `ACTIVE` card, transitioning it from `ACTIVE` to `REPLACED`. The cascade is: a new `EbtCard` row is created in `ISSUED` for the same household; the old card's `replaced_by_card_id` is set to the new card's `id`; and the balance is migrated atomically by posting two paired `ADJUSTMENT` entries to the ledger — a negative entry equal to the old card's `balance_cents` at the instant of replacement on the old card, and a positive entry of the same magnitude on the new card. After the cascade, the new card's recomputed `balance_cents` equals the old card's `balance_cents` at the replacement instant, and the old card's recomputed `balance_cents` is zero. Closing a card runs from `ACTIVE` to `CLOSED` (either by a caseworker directly or as a cascade from `APPROVED` to `CLOSED` on the application) and forfeits any remaining `balance_cents` to zero via an `ADJUSTMENT` entry.

### 3.5. Transactions: Eligible-Item Resolution, Settlement, and Reversal

A `Merchant` settles a purchase by posting a transaction. The body carries the target `card_id`, the merchant's own `merchant_id`, the `requested_amount_cents` (the total cart price the merchant attempts to charge, at least 1 cent), and the `line_items` array (1 to 50 entries, each with `item_category`, `unit_price_cents`, and `quantity`). The transaction is created in `PENDING` and inline-settled to either `APPROVED` or `DECLINED` before the response returns; it is never persisted in `PENDING` to the client.

The settlement runs through a fixed sequence. First the server resolves the eligible amount from the line items, applying a four-step rule:

1. Any line whose `item_category` is `NON_FOOD`, `ALCOHOL`, or `TOBACCO` is filtered out — these are never SNAP-eligible regardless of merchant or household.
2. Lines whose `item_category` is `HOT_PREPARED` or `COLD_PREPARED` are eligible **only** when the merchant's `hot_food_pilot` is true **and** the household's `has_elderly_or_disabled` is true (this is the Restaurant Meals Program path). When either condition fails, both `HOT_PREPARED` and `COLD_PREPARED` lines are treated as ineligible alongside the categorical exclusions in step 1.
3. For every surviving line, the line total is `unit_price_cents` multiplied by `quantity`, and the eligible amount is the integer-cent sum of those line totals.
4. The `ineligible_amount_cents` equals `requested_amount_cents` minus `eligible_amount_cents`.

Once the eligible amount is computed, the server runs the settlement checks **in order**, and the first failing check determines `decline_reason` and the response error:

- If the `EbtCard.status` is not `ACTIVE`, the transaction is declined with `decline_reason` = `CARD_NOT_ACTIVE` and the response is `ERR_CARD_NOT_ACTIVE`.
- If the merchant's `snap_authorization_status` is not `AUTHORIZED`, or `authorization_expires_at` is at or before `Clock.now`, the transaction is declined with `decline_reason` = `MERCHANT_NOT_AUTHORIZED` and the response is `ERR_MERCHANT_NOT_AUTHORIZED`.
- If `eligible_amount_cents` is zero, the transaction is declined with `decline_reason` = `ALL_ITEMS_INELIGIBLE` and the response is `ERR_ALL_ITEMS_INELIGIBLE`. This zero-eligible check **precedes** the balance check, so a cart of only `NON_FOOD` items against a zero-balance card returns `ERR_ALL_ITEMS_INELIGIBLE`, not `ERR_INSUFFICIENT_FUNDS`.
- If `eligible_amount_cents` is greater than the card's current `balance_cents`, the transaction is declined with `decline_reason` = `INSUFFICIENT_FUNDS` and the response is `ERR_INSUFFICIENT_FUNDS`. Note that a card balance of exactly the eligible amount **passes** this check (the comparison is "balance is at least the eligible amount").

Otherwise the transaction is approved: `status` becomes `APPROVED`, `posted_at` is set to `Clock.now`, a `PURCHASE` `BenefitLedger` entry with `amount_cents` equal to the negation of `eligible_amount_cents` is posted to the current `benefit_month` (derived from `Clock.now`), and the card's `balance_cents` is recomputed.

When two purchase attempts race for the same card and the combined eligible amounts exceed the available balance, the system serializes them per-card: the first writer's ledger insertion wins and is `APPROVED`, while the second writer's balance check fails on the now-reduced balance and is `DECLINED` with `decline_reason` = `INSUFFICIENT_FUNDS` and response `ERR_INSUFFICIENT_FUNDS`.

A `Merchant` may reverse an `APPROVED` transaction within 24 hours, transitioning it from `APPROVED` to `REVERSED`. The window is closed-on-the-equality: `Clock.now` at or below `posted_at` plus 24 hours is allowed, anything past that is rejected with `ERR_REVERSAL_WINDOW_EXPIRED`. On a successful reversal a `REFUND` ledger entry with `amount_cents` equal to the positive of the original `eligible_amount_cents` is posted, and the card's `balance_cents` is recomputed accordingly.

### 3.6. Merchant Onboarding

A `StateAdministrator` onboards a merchant by supplying `name` (1–100 characters), `authorization_expires_at`, and optionally `hot_food_pilot` (default false). Merchants are created with `snap_authorization_status` = `AUTHORIZED`. The administrator may subsequently edit `snap_authorization_status`, `authorization_expires_at`, and `hot_food_pilot` on the merchant; setting `snap_authorization_status` to `SUSPENDED` or `REVOKED`, or letting `authorization_expires_at` fall at or before `Clock.now`, causes all subsequent purchase attempts against this merchant to fail with `ERR_MERCHANT_NOT_AUTHORIZED` (as described in §3.5). `Merchant` principals may read their own record and their own transactions, but never another merchant's.

### 3.7. Fraud Investigation: Open, Substantiate, Appeal, Reopen, Close

Either a `Caseworker` or a `FraudInvestigator` opens a `FraudCase` for a household by supplying `household_id` and `trigger_reason`. The case is created in `OPEN`, `opened_at` is stamped to `Clock.now`, and the **suspicious score** is computed and stored.

The suspicious score is a weighted aggregation over the household's recent activity. The rolling window is **30 days** ending at `Clock.now`. Three signals are computed over that window:

- **Signal A — rapid-balance-depletion ratio.** For every `PURCHASE` `BenefitLedger` entry on this household within the window such that *some* `REGULAR_ALLOTMENT` or `EMERGENCY_ALLOTMENT` credit entry for the same household exists whose `created_at` is no more than 24 hours earlier than the purchase's `created_at`, sum the absolute value of the purchase `amount_cents`. The signal is that total divided by the larger of 1 and the household's `monthly_allotment_cents`, capped at 1.0.
- **Signal B — out-of-state merchant ratio.** Let `total_tx` be the count of `APPROVED` transactions for this household within the window; let `oos_tx` be the count of those whose merchant resolves to a state different from the household's `state_code`. The signal is `oos_tx` divided by `total_tx` when `total_tx` is at least 1, and is 0.0 when there are no transactions in the window.
- **Signal C — even-amount clustering ratio.** Over the same `total_tx`, count those whose `eligible_amount_cents` is a multiple of 10,000 (an even hundred-dollar amount). The signal is that count divided by `total_tx` when `total_tx` is at least 1, and is 0.0 otherwise.

The final score is `0.50` multiplied by Signal A, **plus** `0.30` multiplied by Signal B, **plus** `0.20` multiplied by Signal C — the three weighted terms are summed first, and the **final sum** is rounded half-up to two decimal places. This sum-then-round ordering is deliberate and is the opposite of the per-step rounding used in net-income computation. The result is the household's `suspicious_score` for this case, in the range 0.00 to 1.00 inclusive. The same calculation recomputes whenever a transaction is approved for the household and on each case reassessment.

A `FraudInvestigator` then assigns the case from `OPEN` to `UNDER_REVIEW` by supplying `investigator_user_id`; the supplied value is recorded on the case. From `UNDER_REVIEW`, the investigator can either substantiate or dismiss. Substantiating, which transitions `UNDER_REVIEW` to `SUBSTANTIATED`, requires `suspicious_score` to be **at least** 0.70 (a score of exactly 0.70 is accepted; anything below is rejected with `ERR_INVALID_STATE`). The substantiate cascade is non-trivial: every `ACTIVE` `EbtCard` on the affected household transitions from `ACTIVE` to `SUSPENDED`, and the household becomes ineligible for any new Emergency Allotment disbursement until either the case is overturned on appeal or the appeal is upheld. Dismissing the case transitions `UNDER_REVIEW` to `UNFOUNDED` with no cascade.

The household head may appeal a substantiated case, transitioning it from `SUBSTANTIATED` to `APPEAL_PENDING`. The appeal window is closed at exactly 90 days: `Clock.now` at or before `opened_at` plus 90 days is allowed; one nanosecond past that boundary is rejected with `ERR_APPEAL_WINDOW_EXPIRED`. From `APPEAL_PENDING`, the investigator may reopen the investigation (transitioning back to `OPEN` — this is the one cyclic branch in the fraud state machine, intended for a fresh round of evidence-gathering) or uphold the appeal (transitioning from `APPEAL_PENDING` to `UNFOUNDED` and cascading every `EbtCard` that was suspended by *this* case back from `SUSPENDED` to `ACTIVE`).

Closing terminates the case from one of two predecessor states. From `UNFOUNDED`, an investigator closes the case at any time; the transition stamps `closed_at` to `Clock.now`. From `SUBSTANTIATED`, an investigator can close the case **only** when the appeal window has elapsed — `Clock.now` strictly greater than `opened_at` plus 90 days — and the system sweep performs this same close automatically for any `SUBSTANTIATED` case whose appeal window has expired.

When two caseworkers race a `SUBMITTED` `Application` (one approving, the other denying) or two issue-card calls race on the same household, the system serializes per-entity: exactly one wins, and the loser receives `ERR_INVALID_STATE` (the application is no longer in `INTERVIEW_DONE` or `SUBMITTED` when the second writer's transition check runs) or `ERR_CARD_ALREADY_EXISTS` (a card now exists in `ISSUED`/`ACTIVE`/`SUSPENDED`) respectively.

### 3.8. ABAWD Status, Work-Training Waivers, and the Expiry Mechanic

Able-Bodied Adults Without Dependents (ABAWD) are subject to federal time-limited benefits, and this system computes each active member's `abawd_status` from a deterministic ladder. The first matching rule wins:

1. If the member's age (computed as `Clock.now` minus `date_of_birth`, truncated to whole years using 365.25 days per year) is outside the range 18 through 49 inclusive, the status is `NOT_ABAWD`.
2. Otherwise, if `is_disabled` or `is_pregnant` is true, the status is `ABAWD_EXEMPT`.
3. Otherwise, if any *other* active member of the same household has age under 18, the status is `ABAWD_EXEMPT` (because the member is acting as caregiver to a minor).
4. Otherwise, if an `AbawdWaiver` exists for this member in `APPROVED` whose `effective_from` is at or before `Clock.now` and whose `effective_to` is strictly after `Clock.now`, the status is `ABAWD_WAIVED`.
5. Otherwise, the status is `ABAWD_SUBJECT`.

This calculation recomputes on member create, on member edits that touch `is_disabled`, `is_pregnant`, or `date_of_birth`, on any change to household composition, on any waiver state transition, and lazily on read after a clock advance.

The waiver itself is requested by a `HouseholdHead` or a `Caseworker`, who supplies `waiver_kind` (one of the four enumerated kinds), `effective_from`, and `effective_to`. Two structural rules guard creation. First, the period must be valid: `effective_to` must be **strictly greater than** `effective_from`, and the duration must be **at most 12 months exact** — anything longer is rejected with `ERR_WAIVER_PERIOD_INVALID`. Second, the new interval must not overlap any existing waiver for the same member that is in `REQUESTED` or `APPROVED`; overlap detection uses **half-open** interval semantics, so `effective_to` of an existing waiver may equal `effective_from` of the new waiver (adjacency is allowed), but any open-interval overlap is rejected with `ERR_WAIVER_OVERLAP`. The duplicate-interval rule contrasts with the discrete-key duplicate rule used for Emergency Allotments (see §3.9): the waiver rule treats time as a continuous axis with interval geometry, while the EA rule treats the `(state_code, benefit_month)` pair as a discrete tuple where any second insertion of the same tuple is a conflict.

A `Caseworker` approves a `REQUESTED` waiver — transitioning it to `APPROVED` — only when all four eligibility checks pass at the **`effective_from`** instant: the member's age is between 18 and 49 inclusive, the member is not disabled, the member is not pregnant, and the household contains no other member under age 18. Any failure yields `ERR_ABAWD_NOT_ELIGIBLE`. On approval, the member's `abawd_status` is recomputed (it generally becomes `ABAWD_WAIVED` while the waiver is active), and `abawd_countable_months_used` is recomputed under the rule that months covered by an active waiver do not count toward the member's 3-month ceiling.

Rejection moves the waiver from `REQUESTED` to `REJECTED` and requires `decision_reason` to be set. Expiry is system-driven: when `Clock.now` reaches `effective_to`, the waiver transitions from `APPROVED` to `EXPIRED` (either lazily on a read of the member or eagerly during the sweep), and the member's `abawd_status` is recomputed (typically returning to `ABAWD_SUBJECT`).

### 3.9. Emergency Allotment: Declaration, Disbursement, and Cascade

A `StateAdministrator` creates an Emergency Allotment declaration with `state_code` (the state to which the declaration applies), `benefit_month` (a `YYYY-MM` string identifying the benefit month being funded), and `max_allotment_table_version` (an integer at or above 1 — accepted values are 1, 2, and 3; values outside this set fail at declare time). The declaration is created in `DRAFT`. A second creation attempt with the same `(state_code, benefit_month)` tuple is rejected with `ERR_EA_DUPLICATE` when the existing declaration's `state` is in `DRAFT`, `DECLARED`, or `DISBURSED`; only a `CANCELLED` predecessor permits a new declaration on the same tuple.

The administrator advances the declaration from `DRAFT` to `DECLARED` (which stamps `declared_at` to `Clock.now`) and then from `DECLARED` to `DISBURSED`. Disbursement is the load-bearing cascade. The server identifies every qualifying household — those with `state_code` matching the declaration, `certification_status` of `APPROVED`, and **no** `FraudCase` currently in `SUBSTANTIATED` — and posts one `EMERGENCY_ALLOTMENT` `BenefitLedger` entry per qualifying household. The `amount_cents` per entry is computed as follows: the household-size maximum (from the same table used in §3.3: 29,100 / 53,500 / 76,600 / 97,300 / 115,500 / 138,600 cents for sizes 1 through 6 inclusive, with sizes of 7 or larger using the size-6 row) **minus** the household's current `monthly_allotment_cents`, floored at zero, and then **lifted to a floor of 9,500 cents** while the declaration is active. In other words, the per-household EA amount is the larger of (a) zero or the household-size maximum minus the regular allotment, whichever is greater, and (b) the fixed floor of 9,500 cents. Each posted entry uses the declaration's `benefit_month`, and each affected `EbtCard`'s `balance_cents` is recomputed afterward. The declaration's `disbursed_at` is stamped to `Clock.now`.

The system serializes disbursement per-declaration: when two administrators simultaneously attempt to disburse the same `DECLARED` declaration, exactly one transition succeeds; the loser receives `ERR_EA_ALREADY_DISBURSED`. Likewise, an already-`DISBURSED` declaration cannot be disbursed again — a second attempt is rejected with the same error.

Cancellation is permitted only on a `DECLARED` declaration whose `disbursed_at` is still null; the transition runs from `DECLARED` to `CANCELLED` and stamps `cancelled_at` to `Clock.now`. A `DISBURSED` declaration cannot be cancelled.

### 3.10. Ledger Reading, Filters, and Card Detail

The household, member, card, and waiver lifecycles all leave their durable record on the ledger and on the various lifecycle resources, which the appropriate roles can list and read with filters. Reading a card returns the live recomputed `balance_cents`; reading the ledger for a card returns its entries, filterable by `entry_type` and `benefit_month` (with pagination via `limit` and `offset`). Listing transactions supports filters on `card_id`, `merchant_id`, and `status`. Listing fraud cases supports filters on `state` and `household_id`. Listing waivers under a member supports filter on `state`. Listing Emergency Allotments supports filters on `state_code`, `benefit_month`, and `state`. Listing households supports filters on `state_code` and `certification_status`. All list endpoints honor the standard `limit` and `offset` pagination from §2.3 and emit results in `created_at` ascending order.

## 4. Endpoint Definitions

All endpoints below follow these conventions: a successful creation of a new resource returns HTTP **201 Created**; a successful modification (state transition or update) of an existing resource returns HTTP **200 OK**; a successful read returns HTTP 200; validation, business-rule, and concurrency failures use the HTTP status codes catalogued in §5. The path prefix `/households` is the canonical root; cross-aggregate paths (`/transactions`, `/merchants`, `/fraud-cases`, `/emergency-allotments`, `/_clock/advance`, `/_sweep/run`) are top-level. Detailed request/response semantics and side effects are described in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/households` | Create a new Household (no members yet) | `Caseworker` |
| GET | `/households/{id}` | Fetch a Household with all computed fields up to date | `Caseworker`, `HouseholdHead`, `FraudInvestigator` |
| GET | `/households` | List Households with filters | `Caseworker`, `StateAdministrator`, `FraudInvestigator` |
| PATCH | `/households/{id}` | Update mutable Household fields | `Caseworker` |
| POST | `/households/{id}/members` | Add a Member to a Household | `Caseworker` |
| GET | `/households/{id}/members/{memberId}` | Fetch a Member | `Caseworker`, `HouseholdHead` |
| PATCH | `/households/{id}/members/{memberId}` | Update Member fields | `Caseworker` |
| POST | `/households/{id}/members/{memberId}/deactivate` | Remove Member from active roster | `Caseworker` |
| POST | `/households/{id}/applications` | Create a draft Application | `Caseworker`, `HouseholdHead` |
| POST | `/households/{id}/applications/{appId}/submit` | Submit a draft application | `HouseholdHead`, `Caseworker` |
| POST | `/households/{id}/applications/{appId}/schedule-interview` | Move SUBMITTED to PENDING_INTERVIEW | `Caseworker` |
| POST | `/households/{id}/applications/{appId}/complete-interview` | Move PENDING_INTERVIEW to INTERVIEW_DONE | `Caseworker` |
| POST | `/households/{id}/applications/{appId}/return-for-correction` | Revert SUBMITTED to DRAFT | `Caseworker` |
| POST | `/households/{id}/applications/{appId}/approve` | Move INTERVIEW_DONE to APPROVED; full cascade | `Caseworker` |
| POST | `/households/{id}/applications/{appId}/deny` | Move INTERVIEW_DONE to DENIED | `Caseworker` |
| POST | `/households/{id}/applications/{appId}/close` | Move APPROVED to CLOSED; cascade card close | `Caseworker` |
| POST | `/households/{id}/cards` | Manually issue a new EbtCard | `Caseworker` |
| POST | `/households/{id}/cards/{cardId}/activate` | Move ISSUED to ACTIVE | `HouseholdHead` |
| POST | `/households/{id}/cards/{cardId}/suspend` | Move ACTIVE to SUSPENDED | `Caseworker`, `FraudInvestigator` |
| POST | `/households/{id}/cards/{cardId}/resume` | Move SUSPENDED to ACTIVE | `Caseworker` |
| POST | `/households/{id}/cards/{cardId}/replace` | Move ACTIVE to REPLACED; mint new card; transfer balance | `HouseholdHead`, `Caseworker` |
| GET | `/households/{id}/cards/{cardId}` | Fetch a card with current balance | `Caseworker`, `HouseholdHead` |
| GET | `/households/{id}/cards/{cardId}/ledger` | List ledger entries for a card | `Caseworker`, `HouseholdHead` |
| POST | `/transactions` | Merchant submits a purchase; inline-settle to APPROVED or DECLINED | `Merchant` |
| GET | `/transactions/{txId}` | Fetch a transaction | `Caseworker`, `Merchant`, `HouseholdHead`, `FraudInvestigator` |
| GET | `/transactions` | List transactions with filters | `Caseworker`, `FraudInvestigator` |
| POST | `/transactions/{txId}/reverse` | Move APPROVED to REVERSED within 24-hour window | `Merchant` |
| POST | `/merchants` | Onboard a merchant | `StateAdministrator` |
| PATCH | `/merchants/{merchantId}` | Update merchant authorization/pilot status | `StateAdministrator` |
| GET | `/merchants/{merchantId}` | Fetch a merchant | `StateAdministrator`, `Merchant` |
| POST | `/fraud-cases` | Open a new FraudCase for a household | `FraudInvestigator`, `Caseworker` |
| POST | `/fraud-cases/{caseId}/assign` | Move OPEN to UNDER_REVIEW | `FraudInvestigator` |
| POST | `/fraud-cases/{caseId}/substantiate` | Move UNDER_REVIEW to SUBSTANTIATED; suspend cards | `FraudInvestigator` |
| POST | `/fraud-cases/{caseId}/dismiss` | Move UNDER_REVIEW to UNFOUNDED | `FraudInvestigator` |
| POST | `/fraud-cases/{caseId}/appeal` | Move SUBSTANTIATED to APPEAL_PENDING (within 90 days) | `HouseholdHead` |
| POST | `/fraud-cases/{caseId}/reopen-investigation` | Move APPEAL_PENDING to OPEN (cyclic) | `FraudInvestigator` |
| POST | `/fraud-cases/{caseId}/uphold-appeal` | Move APPEAL_PENDING to UNFOUNDED; restore cards | `FraudInvestigator` |
| POST | `/fraud-cases/{caseId}/close` | Move UNFOUNDED or expired-window SUBSTANTIATED to CLOSED | `FraudInvestigator` |
| GET | `/fraud-cases` | List fraud cases | `FraudInvestigator`, `Caseworker` |
| GET | `/fraud-cases/{caseId}` | Fetch a fraud case | `FraudInvestigator`, `Caseworker`, `HouseholdHead` |
| POST | `/households/{id}/members/{memberId}/abawd-waivers` | Request an ABAWD waiver | `HouseholdHead`, `Caseworker` |
| POST | `/households/{id}/members/{memberId}/abawd-waivers/{waiverId}/approve` | Move REQUESTED to APPROVED | `Caseworker` |
| POST | `/households/{id}/members/{memberId}/abawd-waivers/{waiverId}/reject` | Move REQUESTED to REJECTED | `Caseworker` |
| GET | `/households/{id}/members/{memberId}/abawd-waivers/{waiverId}` | Fetch a waiver | `Caseworker`, `HouseholdHead` |
| GET | `/households/{id}/members/{memberId}/abawd-waivers` | List waivers for a member | `Caseworker`, `HouseholdHead` |
| POST | `/emergency-allotments` | Create a draft EA declaration | `StateAdministrator` |
| POST | `/emergency-allotments/{eaId}/declare` | Move DRAFT to DECLARED | `StateAdministrator` |
| POST | `/emergency-allotments/{eaId}/disburse` | Move DECLARED to DISBURSED; cascade EA credits | `StateAdministrator` |
| POST | `/emergency-allotments/{eaId}/cancel` | Move DECLARED to CANCELLED (only if not yet disbursed) | `StateAdministrator` |
| GET | `/emergency-allotments/{eaId}` | Fetch an EA declaration | `StateAdministrator`, `Caseworker` |
| GET | `/emergency-allotments` | List EA declarations | `StateAdministrator`, `Caseworker` |
| POST | `/_clock/advance` | Advance the server clock (test fixture) | `SystemTest` |
| POST | `/_sweep/run` | Run the periodic sweep | `SystemTest` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_MISSING` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CARD_NOT_ACTIVE` | 422 |
| `ERR_FRAUD_HOLD` | 422 |
| `ERR_MERCHANT_NOT_AUTHORIZED` | 422 |
| `ERR_ABAWD_NOT_ELIGIBLE` | 422 |
| `ERR_GROSS_INCOME_OVER_LIMIT` | 422 |
| `ERR_NET_INCOME_OVER_LIMIT` | 422 |
| `ERR_INSUFFICIENT_FUNDS` | 422 |
| `ERR_ALL_ITEMS_INELIGIBLE` | 422 |
| `ERR_CARD_ALREADY_EXISTS` | 409 |
| `ERR_EA_ALREADY_DISBURSED` | 409 |
| `ERR_REVERSAL_WINDOW_EXPIRED` | 422 |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 |
| `ERR_WAIVER_PERIOD_INVALID` | 422 |
| `ERR_WAIVER_OVERLAP` | 422 |
| `ERR_EA_DUPLICATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
