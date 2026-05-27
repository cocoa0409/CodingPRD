# Snap-Ebt Food Stamps API — Product Requirements Document

## 1. Introduction

The Supplemental Nutrition Assistance Program (SNAP), historically known as Food Stamps, is the United States' largest food-assistance program. State agencies are responsible for certifying eligible households, computing the monthly allotment each household receives on its Electronic Benefit Transfer (EBT) card, and operating point-of-sale settlement against a federally curated list of eligible food categories. The work is consequential — under-issuing benefits leaves families short; over-issuing creates federal recoupment exposure — and it is also operationally demanding, because every change to a household's roster, income, or assistance flags can ripple into a different allotment for the very next benefit month.

This document specifies the SNAP/EBT benefit-administration API that backs caseworker tooling, the applicant portal, the issuing back office, the merchant settlement rail, and the state fraud-investigations unit. It covers household and member intake, application decisioning, ABAWD (Able-Bodied Adults Without Dependents) work-requirement waivers, monthly allotment computation under both standard and emergency-supplement regimes, EBT card lifecycle, purchase authorization and settlement, eligible-item enforcement, and the fraud-detection feedback loop that drives household suspension. Because the system spans several user populations with different blast radii — a caseworker can terminate a household, a merchant can settle a purchase, a fraud investigator can suspend a card — the access model and the cascade behaviour of each operation are described as carefully as the calculations themselves.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the SNAP API must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the role under which the call is made. Either header missing or empty yields `ERR_UNAUTHENTICATED` (HTTP 401). A header pair that fails the per-endpoint role check yields `ERR_FORBIDDEN` (HTTP 403).

The system recognises exactly seven roles, spelled as follows: `Caseworker`, `Applicant`, `Cardholder`, `BenefitIssuer`, `FraudInvestigator`, `Merchant`, and `PolicyAdmin`.

Two roles are entity-backed. When `X-User-Role` is `Applicant`, the value of `X-User-ID` is the `id` of the `Household` the applicant heads; ownership checks on any resource that references a `Household` compare the resource's `household_id` to `X-User-ID`. When `X-User-Role` is `Cardholder`, the value of `X-User-ID` is again the `id` of the `Household` the card belongs to, and the same `household_id`-to-`X-User-ID` comparison gates card activation, replacement, and read access. The remaining five roles — `Caseworker`, `BenefitIssuer`, `FraudInvestigator`, `Merchant`, and `PolicyAdmin` — are opaque operator identifiers not tied to any persisted entity. The server may record an opaque `X-User-ID` on a resource where a scaffold transition writes it (notably `Application.caseworker_id` when a caseworker approves or denies, and `FraudFlag.investigator_id` when an investigator claims a flag) but does not compare it to any entity's `id`.

A summary of which roles may invoke each endpoint is given in §4.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, takes a minimum of 1, and is capped at a maximum of 100. The `offset` parameter defaults to 0. Result rows are returned in ascending `created_at` order (oldest first). On every list response, the `meta` envelope carries the echoed `limit` and `offset`, a `total_count` of all matching rows ignoring pagination, and a `has_more` boolean that is true when more rows exist beyond the current page.

### 2.4. Common Resource Properties

Every resource other than `EligibleItemCategory` and `SystemClock` exposes four bookkeeping fields. The `id` is a server-minted UUID — emitted as a plain UUID string with no type prefix and assigned at creation. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, stamped once at creation and never updated. The `updated_at` field is an ISO 8601 UTC timestamp with three fractional digits, refreshed every time the resource itself is mutated, including mutations driven by cascades from other resources. The `version` field is an integer that begins at 1 and increments by exactly 1 on every mutation; it is the substrate for optimistic concurrency.

Two entities are deliberately lighter. `EligibleItemCategory` and `SystemClock` carry only `id` and `created_at`; they have no `updated_at` and no `version`. Categories are reference data that policy administrators add to, and the logical clock is a single test-only register whose value is meaningful only through its `current_utc` field.

### 2.5. Optimistic Concurrency Control

Two write endpoints require the client to pin the version of a parent entity before mutating it.

Issuing a monthly allotment requires `expected_household_version` in the request body. The value must match the target household's current `version`. If another writer — adding a household member, flipping `heap_recipient`, approving an application — has advanced the household's `version` since the issuer last read it, the issue request is rejected with `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412). This prevents the issuer from freezing an allotment amount computed against household inputs that have since changed (for example, the household just grew, so `gross_income_cents` and `net_income_cents` are different from what the issuer saw).

Substantiating a fraud flag requires `expected_fraudflag_version` in the request body. The value must match the target flag's current `version`. If a concurrent `/claim` or `/dismiss` by another investigator has advanced the flag's `version` since the substantiating investigator last read it, the substantiate is rejected with `ERR_STALE_FRAUDFLAG_VERSION` (HTTP 412). The investigator made a decision against an out-of-date case state, and the system refuses to apply it.

These are the only two endpoints that take a version field. No other write endpoint accepts `expected_*_version`, and supplying one elsewhere has no effect.

### 2.6. Nested Path Resolution

Every `{id}` segment that appears in a URL path must resolve, left to right, to a row in the corresponding entity table; the first segment that does not resolve yields `ERR_NOT_FOUND` (HTTP 404). Similarly, every foreign-key field in a POST body — `household_id` on a member, application, EBT card, allotment, or fraud flag; `household_member_id` on an ABAWD waiver; `ebt_card_id` on a purchase transaction — must reference an existing parent row, or the request is rejected with `ERR_PARENT_NOT_FOUND` (HTTP 404).

### 2.7. Money, Time, and Precision

All monetary fields on this API are integers expressed in cents — `monthly_earned_income_cents`, `monthly_unearned_income_cents`, `gross_income_cents`, `net_income_cents`, `standard_allotment_cents`, `emergency_supplement_cents`, `issued_total_cents`, `total_cents`, `min_supplement_cents`, and the line-item `amount_cents` all share this convention. Intermediate arithmetic inside the calculations of §3 is performed in integer cents; the few places where a fraction can arise (the earned-income deduction, the 30% of net income figure) are resolved by truncation toward zero, equivalent to a floor of the cent-valued product. No other rounding takes place in any calculation.

Timestamps on this API are ISO 8601 UTC strings with three fractional digits. The single logical wall clock the system uses for benefit issuance, certification expiry, and the 24-hour velocity window is the `current_utc` field of the `SystemClock` resource; tests advance it via an administrative endpoint described in §3.

### 2.8. Validation Priority and Evaluation Order

When several validation rules might reject the same request, they are evaluated in a fixed priority order so that the rejection a caller sees is the one closest to the root cause. The order is: (1) `X-User-Role` present and recognised, (2) `X-User-ID` present, (3) role authorised for the endpoint, (4) every URL-path `{id}` resolves, (5) every body foreign key resolves, (6) the entity is in a from-state listed for the requested transition (`ERR_INVALID_STATE`, HTTP 409), (7) the cross-entity host-state check (`ERR_HOUSEHOLD_NOT_ACTIVE`, HTTP 409, applies to card activation, card reinstatement, and allotment issuance), (8) the card-active check on settlement (`ERR_CARD_NOT_ACTIVE`, HTTP 409), (9) the claiming-investigator segregation check on `FraudFlag` substantiate and dismiss while under review (`ERR_NOT_CLAIMING_INVESTIGATOR`, HTTP 403), (10–13) the business-uniqueness checks for `case_number` on households, `(household_id, benefit_month)` on allotments, `(household_member_id, quarter)` on waivers, and `(state_code, benefit_month)` on proclamations, (14–15) the benefit-month-not-in-past and not-before-first-of-month temporal checks for allotments, (16) the ABAWD work-requirement check on application approve, (17) the income-limit check on application approve, (18–20) the all-items-ineligible, invalid-line-items, and out-of-state-blocking checks on purchase create, and finally (21) the optimistic-concurrency `expected_<parent>_version` check on allotment issue and fraud-flag substantiate. Earlier rules mask later ones: a missing role header is reported as `ERR_UNAUTHENTICATED` even when the body would also be malformed; a not-found URL segment is reported as `ERR_NOT_FOUND` even when a stale `expected_household_version` would also have been rejected.

### 2.9. Hierarchical Consistency and Cascades

Many of the state machines in §3 cascade into siblings or children. Whenever a request causes a resource to be mutated — its own state changes, one of its non-state fields is rewritten, or it is created as the side-effect of another operation — that resource's `updated_at` is refreshed and its `version` is incremented by 1. Cascaded mutations follow the same rule: a card that flips from `ACTIVE` to `SUSPENDED` because its household was suspended bumps the card's `updated_at` and `version`, not just the household's. The household-level `version` increments called out explicitly in §3 are listed because they are the OCC handle clients pin against; they are not the exhaustive list of resources whose `version` changes in a cascade.

### 2.10. Errors and Their Trigger Surfaces

Every error this API can return is enumerated by id and HTTP status in §5. The condition that causes a particular `error_id` to be returned is given in the prose of §2 or §3 that describes the relevant workflow — there is no separate "errors with conditions" table. Generic body-parse failures (missing required field, type or enum violation, malformed JSON) yield `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Household Intake and Member Roster

A new household enters the system through household creation by a `Caseworker`. The caseworker supplies a `case_number` — a string of the form two uppercase letters, a hyphen, and six digits, which must be unique across all households (a duplicate is rejected with `ERR_DUPLICATE_CASE_NUMBER`) — together with the issuing `state_code` (one of `CA`, `TX`, `NY`, `FL`, `IL`, `PA`, `OH`, `GA`, `NC`, `MI`), a free-text `address_line`, and an optional `heap_recipient` boolean. The household is born with `status` set to `PENDING`, `size` set to 0, and `heap_recipient` defaulting to false when not supplied. The boolean records whether the household received Low Income Home Energy Assistance Program benefits in the last 12 months; when true, a Standard Utility Allowance is admitted into the benefit-side net-income figure (see §3.4).

Members are attached one by one. Each `HouseholdMember` carries an immutable `household_id` foreign-key reference, a `full_name`, a `date_of_birth` (used downstream for elderly and ABAWD determinations), and a `relationship` enumerated as `HEAD`, `SPOUSE`, `CHILD`, `PARENT`, or `OTHER`. Income is captured as two integer-cent fields, `monthly_earned_income_cents` (wage income) and `monthly_unearned_income_cents` (Social Security, child support, and similar), each defaulting to 0 and required to be non-negative. A boolean `disabled` records whether the member is disabled per SSA criteria and defaults to false; a disabled member bypasses the ABAWD work requirement and qualifies for the elderly-or-disabled medical deduction. A member's lifecycle `status` is either `ACTIVE` or `REMOVED`. `ACTIVE` members count toward the household's `size` and feed all income aggregations; `REMOVED` is a soft delete that retains the row for audit but excludes it from every calculation.

Every member-roster change is reflected on the parent household synchronously. Adding or removing a member, or flipping a member's `status` between `ACTIVE` and `REMOVED` via a member update, recomputes the household's `size`, `gross_income_cents`, and `net_income_cents` (the latter via the calculation described in §3.4) and increments the household's `version` by 1. Updating a member's `monthly_earned_income_cents`, `monthly_unearned_income_cents`, or `disabled` likewise re-derives the household totals and increments the household's `version`. The household-level `gross_income_cents` is always the sum of the earned and unearned income figures of `ACTIVE` members; the `size` field is the count of `ACTIVE` members and is supported only up to 16. A `Caseworker` can also update a household directly to change `address_line` or flip `heap_recipient`; a `heap_recipient` flip triggers a `net_income_cents` recomputation (because the Standard Utility Allowance toggles) and bumps the household's `version`.

### 3.2. Application Lifecycle and Certification

Each `Application` represents one household's attempt to enter certification. An application is created in `DRAFT` by either a `Caseworker` or an `Applicant`, and it carries the `household_id` it certifies, an `applied_at` timestamp that is null until submission, a `caseworker_id` that is null while the application is in `DRAFT` or `SUBMITTED`, and a `decision_reason` that the caseworker fills in at approve or deny time.

Submitting a `DRAFT` application — submission can be performed by the `Applicant` themselves or a `Caseworker` acting on their behalf — advances the application from `DRAFT` to `SUBMITTED`, but only if the referenced household exists with `status` of `PENDING` and has at least one `ACTIVE` member (`size` of at least 1). On submission, `applied_at` is set to `SystemClock.current_utc` and the household's `updated_at` is refreshed.

Approval is a `Caseworker`-only action that moves the application from `SUBMITTED` to `APPROVED`. It enforces, in the order defined in §2.8: that the application is in `SUBMITTED` (otherwise `ERR_INVALID_STATE`), that the household has cleared its ABAWD work-requirement obligations (see §3.3, otherwise `ERR_ABAWD_REQUIREMENT_UNMET`), that the household's net income evaluated under the limit-check variant of the net-income calculation is at most `NET_INCOME_LIMIT_BY_SIZE` for the current `size` (see §3.4, otherwise `ERR_INCOME_LIMIT_EXCEEDED`), and that `decision_reason` is non-empty in the request body. On approval, several effects fire as one logical request: the household's `status` advances `PENDING → CERTIFIED → ACTIVE` — `CERTIFIED` is an intermediate state that auto-advances to `ACTIVE` before the response is returned, so callers always observe the household landing in `ACTIVE` — the household's `certification_end_date` is set to `SystemClock.current_utc` plus twelve months, an `EBTCard` for the household is created with `status` of `PENDING_ISSUE` (this is cascade link 1 of the approval cascade), the application's `caseworker_id` is set to the calling `X-User-ID`, and the household's `version` increments by 1.

Denial is the symmetric `Caseworker` action that moves the application from `SUBMITTED` to `DENIED`. It requires `decision_reason` to be non-empty. As a compensating action, the household's `status` is set to `TERMINATED`, the application's `caseworker_id` is set to the calling `X-User-ID`, and the household's `version` increments by 1.

A `SUBMITTED` application that has not been decided becomes `EXPIRED` automatically once `SystemClock.current_utc` reaches or passes `applied_at` plus 30 days. The transition is system-driven; no role is needed. When expiry fires, the household's `status` is set to `TERMINATED` because no certification was ever issued.

### 3.3. ABAWD Work Requirement and Waivers

A member is an Able-Bodied Adult Without Dependents (ABAWD) when their age, computed from `date_of_birth` against `SystemClock.current_utc`, is at least 18 and at most 49, when their `disabled` flag is false, and when no member of the same household is younger than 18. ABAWDs must either be working, in work training for the equivalent of at least 80 hours per month, or covered by a waiver that recognises a high-unemployment county.

An `ABAWDWaiver` is requested by either a `Caseworker` or an `Applicant` for the ABAWD member. The waiver record carries `household_member_id`, a `quarter` string in the form `YYYY-Qn` where `n` is 1 through 4 (the pair `(household_member_id, quarter)` is unique; a duplicate is rejected with `ERR_DUPLICATE_WAIVER_QUARTER`), a `county_unemployment_pct` recorded with two decimal places between 0.00 and 50.00 inclusive, a verified `monthly_work_hours` integer of at least 0, and a `decision_reason` that the caseworker fills in at approve or deny time. The waiver enters the system in `PENDING`.

A `Caseworker` can advance a `PENDING` waiver to `APPROVED` only if the county-unemployment percentage is at least 10.00 OR the member's verified monthly work hours are at least 80; `decision_reason` must be non-empty. A `PENDING` waiver may also be moved to `DENIED` with a non-empty `decision_reason`, and an `APPROVED` waiver may later be moved to `REVOKED`. `APPROVED`, `DENIED`, and `REVOKED` are terminal.

The work-requirement check fires at application-approve time. For each ABAWD member of the household, the system requires either an `APPROVED` `ABAWDWaiver` for the current calendar quarter (computed from `SystemClock.current_utc`) OR a `PENDING` `ABAWDWaiver` whose `monthly_work_hours` is at least 80. If any ABAWD member fails both arms of that test, the approval is rejected with `ERR_ABAWD_REQUIREMENT_UNMET`.

### 3.4. Net Income, Standard Allotment, and Emergency Supplements

All income arithmetic is performed in integer cents. The net-monthly-income calculation runs whenever a member is created, updated, or removed, whenever the household's `heap_recipient` flag is flipped, whenever an application is submitted, and whenever a monthly allotment is computed. It exists in two variants — a benefit-calculation variant whose result is stored in `Household.net_income_cents` and feeds the allotment formula, and a limit-check variant evaluated transiently inside the application-approve precondition described in §3.2. The two variants share their inputs and differ only in whether the Standard Utility Allowance is admitted.

The benefit-calculation variant proceeds as follows. First, gross income is the sum, over all `ACTIVE` members of the household, of each member's `monthly_earned_income_cents` plus their `monthly_unearned_income_cents`; this value is written to `Household.gross_income_cents`. Second, earned income — the sum of `monthly_earned_income_cents` alone over the same set — is multiplied by the earned-income deduction percentage of 20%, and the product is truncated toward zero (equivalent to the floor of the cent-valued product); the result is the earned-income deduction. Third, the standard deduction is read from a per-size tier table: for household size 1, 2, or 3 it is 19,800 cents ($198.00), for size 4 it is 21,300 cents ($213.00), for size 5 it is 24,900 cents ($249.00), and for size 6 or larger it is 28,500 cents ($285.00). Fourth, when `heap_recipient` is true, a Standard Utility Allowance of 6,700 cents ($67.00) is admitted; when `heap_recipient` is false, the allowance is 0. (Shelter deductions are not part of this version of the calculation.) Fifth, the total deductions are the sum of the earned-income deduction, the standard deduction, and the Standard Utility Allowance. Sixth, net income is the larger of 0 and gross income minus total deductions; this value is written to `Household.net_income_cents`. Apart from the single truncation step on the earned-income deduction, no other rounding occurs.

The limit-check variant differs in exactly one place: even when `heap_recipient` is true, the Standard Utility Allowance is omitted (treated as 0). Because admitting the allowance can only reduce net income, the limit-check figure for the same household and the same inputs is greater than or equal to the benefit-calculation figure; when `heap_recipient` is true it is strictly greater. The limit-check value is compared, inside application approve, against `NET_INCOME_LIMIT_BY_SIZE`: 117,500 cents for size 1, 158,900 cents for size 2, 200,300 cents for size 3, 241,700 cents for size 4, 283,100 cents for size 5, and 324,500 cents for size 6, with an additional 41,400 cents added per person beyond 6. A limit-check value at or below the size-indexed ceiling passes; a value above it fails with `ERR_INCOME_LIMIT_EXCEEDED`.

The monthly-allotment calculation runs on `MonthlyAllotment` create, on issue, and on adjust. Its standard variant is computed every time. First, the effective size is the larger of 1 and the household's `size`. Second, the maximum allotment is read from a per-size tier table — 29,100 cents for size 1, 53,500 cents for size 2, 76,600 cents for size 3, 97,300 cents for size 4, 115,500 cents for size 5, and 138,600 cents for size 6 — plus, for households larger than 6, an additional 21,100 cents per person beyond 6. Third, thirty percent of `Household.net_income_cents` is computed and truncated toward zero (equivalent to the floor of the cent-valued product); this is the benefit reduction. Fourth, the standard allotment is the maximum allotment minus the benefit reduction, but for households of size 1 or 2 it cannot drop below the minimum of 2,300 cents ($23.00). The result is written to `MonthlyAllotment.standard_allotment_cents`. The order is mandatory: the 30% product is truncated first, and the subtraction is performed second; truncating after subtraction would yield a different cent value and is not permitted.

The emergency variant only contributes when an `EmergencyAllotmentProclamation` whose `status` is `ACTIVE` exists for the matching `state_code` and `benefit_month`. In that case the supplement is the larger of two values: the proclamation's `min_supplement_cents` (defaulting to 9,500 cents, $95.00, the federally mandated floor) and the gap between the maximum allotment and the standard allotment just computed. The result is written to `emergency_supplement_cents`. When no `ACTIVE` proclamation matches, `emergency_supplement_cents` is 0. In either case, `issued_total_cents` is the sum of `standard_allotment_cents` and `emergency_supplement_cents`.

### 3.5. Monthly Allotment Issuance and Adjustment

A `MonthlyAllotment` is created in `DRAFT` by a `BenefitIssuer` (or a `Caseworker` acting jointly) with a body containing `household_id` and a `benefit_month` string in `YYYY-MM` form. The pair `(household_id, benefit_month)` is unique across all allotments; a duplicate is rejected with `ERR_DUPLICATE_ALLOTMENT_MONTH`. The `benefit_month` must be the current month (as `YYYY-MM` of `SystemClock.current_utc`) or any future month; a month that has already started in the past yields `ERR_BENEFIT_MONTH_IN_PAST`. On creation, `standard_allotment_cents` and `emergency_supplement_cents` are computed per §3.4; the allotment's `issued_at` is null and `issued_total_cents` reflects the current sum.

Issuance transitions the allotment from `DRAFT` to `ISSUED` and is exclusive to the `BenefitIssuer` role. The request body carries `expected_household_version` to satisfy the optimistic-concurrency rule described in §2.5. The transition requires that the allotment is in `DRAFT`, that the household is `ACTIVE` (otherwise `ERR_HOUSEHOLD_NOT_ACTIVE`), that the household has at least one EBT card in `ACTIVE` status, and that `SystemClock.current_utc` is on or after the first UTC day of `benefit_month` (otherwise `ERR_ISSUANCE_TOO_EARLY`). On success, the allotment's `standard_allotment_cents` and `emergency_supplement_cents` are recomputed one last time from the live §3.4 inputs and frozen, `issued_total_cents` is recomputed to the frozen sum, `issued_at` is stamped to `SystemClock.current_utc`, and the household's `version` increments by 1.

After an allotment is `ISSUED`, a new proclamation may take effect for the household's `(state_code, benefit_month)`. Adjustment, also exclusive to the `BenefitIssuer` role, advances the allotment from `ISSUED` to `ADJUSTED`. It requires that the allotment is in `ISSUED` and that an `EmergencyAllotmentProclamation` reached `ACTIVE` for the household's `state_code` and the allotment's `benefit_month` after the allotment's `issued_at` timestamp. On success, `emergency_supplement_cents` is re-derived from §3.4 (and can only increase, because a proclamation has been added) and `issued_total_cents` is recomputed; `standard_allotment_cents` is left as it was at issuance and is not re-derived.

`DRAFT` allotments for the current month are expunged as a side-effect of household suspension; future-dated allotments are expunged as a side-effect of household termination. The terminal states for the allotment lifecycle are `ISSUED`, `EXPUNGED`, and `ADJUSTED`.

### 3.6. EBT Card Lifecycle and Replacement

An EBT card is born with `status` of `PENDING_ISSUE` as a side-effect of application approval (cascade link 1 of the approval cascade described in §3.2). The card carries the `household_id` it serves, a `pan_last4` string that is empty until activation, and a `replaced_by_card_id` that is null unless the card has been replaced.

Activation is performed by the `Cardholder` (or, jointly, a `Caseworker`). It transitions the card from `PENDING_ISSUE` to `ACTIVE`. The card must be in `PENDING_ISSUE`, the host household must be `ACTIVE` (otherwise `ERR_HOUSEHOLD_NOT_ACTIVE`), and — because the `Cardholder` is `Household`-backed — the caller's `X-User-ID` must equal the `id` of the host household. On success, the server generates a `pan_last4` of exactly four numeric characters; the full PAN is never stored.

Suspension flips an `ACTIVE` card to `SUSPENDED`. It can be invoked directly by a `Caseworker` or a `FraudInvestigator`, and it also fires as cascade link 2 of the household-suspension cascade (see §3.7). The side effect of suspension is that every `AUTHORIZED` purchase transaction on the card is moved to `REVERSED` (cascade link 2 of the card-suspend cascade). Reinstatement, performed by a `Caseworker`, flips the card back from `SUSPENDED` to `ACTIVE`, but only when the household is itself `ACTIVE` (otherwise `ERR_HOUSEHOLD_NOT_ACTIVE`); it can also fire as a cascade from household reinstatement.

Replacement is performed by the `Cardholder` (or, jointly, a `Caseworker`) and moves the predecessor from `ACTIVE` to `REPLACED`. Both the card and its host household must be `ACTIVE`. On success, a fresh `EBTCard` is created with `status` of `ACTIVE` for the same `household_id`, and the predecessor's `replaced_by_card_id` is set to the new card's `id` (cascade link 2 of the replace cascade). If this is the third or later replacement of any card for the same household within a rolling 90-day window — the window endpoint being `SystemClock.current_utc` inclusive, looking back exactly 90 days — a `FraudFlag` with `trigger_rule` of `CARD_REPLACE_ABUSE` and `status` of `OPEN` is created (cascade link 3 of the replace cascade).

Cancellation is system-driven and fires only as a cascade from household termination. From any of `PENDING_ISSUE`, `ACTIVE`, or `SUSPENDED`, the card lands in `CANCELLED`. `REPLACED` and `CANCELLED` are terminal.

### 3.7. Household Lifecycle: Suspension, Reinstatement, Termination

Once a household has reached `ACTIVE` through the approval flow of §3.2, a `Caseworker` can suspend it, reinstate it, or terminate it.

Suspension transitions the household from `ACTIVE` to `SUSPENDED` and requires that at least one `FraudFlag` for the household has `status` of `SUBSTANTIATED`. The cascade fans out as follows: every `EBTCard` for the household with `status` of `ACTIVE` transitions to `SUSPENDED` (cascade link 2 of the fraud-driven household-suspend cascade), and every `MonthlyAllotment` for the household with `status` of `DRAFT` whose `benefit_month` equals the current month transitions to `EXPUNGED` (cascade link 3). The household's `version` increments by 1.

Reinstatement transitions the household from `SUSPENDED` back to `ACTIVE`. Every `EBTCard` for the household with `status` of `SUSPENDED` transitions back to `ACTIVE`, and the household's `version` increments by 1.

Termination is irreversible. From `ACTIVE` or `SUSPENDED`, the household lands in `TERMINATED`; the request must carry a `decision_reason`. Every `EBTCard` for the household transitions to `CANCELLED` regardless of its prior state, every `MonthlyAllotment` for the household whose `benefit_month` is later than the current month transitions to `EXPUNGED`, and the household's `version` increments by 1. `TERMINATED` is terminal.

The `ACTIVE` requirement re-appears in several cross-entity places: card activation, card reinstatement, and allotment issuance all reject with `ERR_HOUSEHOLD_NOT_ACTIVE` (HTTP 409) when the host household is not `ACTIVE`. This is the §2.8 priority-7 check.

### 3.8. Eligible Categories, Purchase Authorization, Settlement

Reference data for what can be bought with SNAP benefits is owned by `PolicyAdmin`. Each `EligibleItemCategory` carries a `code` (uppercase alphanumerics with underscores, of length 2 to 32, unique across categories), a human-readable `name`, and a boolean `eligible` flag. Categories such as `FRESH_PRODUCE`, `DAIRY`, `MEAT`, and `BREAD` are eligible; `TOBACCO`, `ALCOHOL`, `HOT_PREPARED`, and `NON_FOOD` are not. A category is created with all three fields, and reads can filter by `eligible` and `code`. `EligibleItemCategory` resources are reference data and, like the system clock, carry only `id` and `created_at`; they have no `updated_at` and no `version`.

A `PurchaseTransaction` is created by a `Merchant` with a body containing `ebt_card_id`, `merchant_id`, and a `line_items` array. Each entry of `line_items` is an object with `category_code`, `amount_cents` (an integer greater than 0), and `quantity` (an integer of at least 1). The card's `household_id` is copied from the EBT card onto the transaction. The transaction is born in `AUTHORIZED`. The `total_cents` field of the transaction is the sum of `amount_cents` over those `line_items` whose `category_code` resolves to an `EligibleItemCategory` with `eligible` of true; the `category_code` values of `line_items` whose category resolves to `eligible` of false are collected into the transaction's `ineligible_line_codes` array. Ineligible lines never contribute to `total_cents` and are recorded informationally only.

Three create-time rejections apply, evaluated after the standard parent and existence checks (see §2.8). If `line_items` is empty, or if any line's `category_code` does not name an existing category, the request fails with `ERR_INVALID_LINE_ITEMS`. If every line resolves to an ineligible category — so the computed `total_cents` would be 0 — the request fails with `ERR_ALL_ITEMS_INELIGIBLE`. If the household already has a prior fraud flag with `trigger_rule` of `OUT_OF_STATE` whose `status` is `OPEN`, `UNDER_REVIEW`, or `SUBSTANTIATED`, a new out-of-state purchase attempt (i.e., the merchant's location implied by `merchant_id` does not match the household's `state_code`) is blocked with `ERR_OUT_OF_STATE_BLOCKED`; the first such occurrence raises the flag rather than blocking, but every subsequent one is rejected.

Settlement, performed by a `Merchant`, transitions the transaction from `AUTHORIZED` to `SETTLED`. It requires that the transaction is in `AUTHORIZED` and that the underlying EBT card is in `ACTIVE` (otherwise `ERR_CARD_NOT_ACTIVE`). On success, `settled_at` is stamped to `SystemClock.current_utc`, and the velocity calculation in §3.9 is triggered. Reversal, performed by a `Merchant`, transitions the transaction from `AUTHORIZED` to `REVERSED` and can also fire as the cascade from card suspension described in §3.6. `SETTLED` and `REVERSED` are terminal.

### 3.9. Fraud Monitoring, Velocity Scoring, and Investigations

Each `FraudFlag` carries `household_id`, a `trigger_rule` enumerated as `VELOCITY_SPIKE`, `OUT_OF_STATE`, `DUPLICATE_HH_MEMBER`, or `CARD_REPLACE_ABUSE`, an `investigator_id` that is null while the flag is `OPEN`, and a `resolution_note` that is filled in at substantiate or dismiss time. A flag is born in `OPEN` either as a side effect of a system process (a velocity spike on settle, a card-replacement abuse during replacement, an out-of-state purchase, a duplicate household membership) or by direct creation: a `Caseworker` or a `FraudInvestigator` may file a manual referral with `household_id` and `trigger_rule`.

The velocity score is recomputed every time a `PurchaseTransaction` for the household transitions from `AUTHORIZED` to `SETTLED`. The order of operations is mandatory: first, the just-settled row's `status` is written to `SETTLED` and its `settled_at` is stamped to `SystemClock.current_utc`; second, the system re-queries the set of `SETTLED` transactions for the household whose `settled_at` falls in the 24-hour window ending at `SystemClock.current_utc` inclusive, so that the trigger row is included in that set; third, that set is sorted by `settled_at` ascending with `created_at` ascending as the tie-break (never by `id`); fourth, the total in cents of `total_cents` across that set is computed and the count of rows in that set is computed; fifth, the velocity score is the total plus the count multiplied by a per-transaction count penalty of 5,000 cents ($50). A flag is raised when the velocity score is at least 80,000 cents ($800) AND the count is at least 4. When both conditions hold, a `FraudFlag` with `trigger_rule` of `VELOCITY_SPIKE` and `status` of `OPEN` is created (cascade link 2 of the velocity cascade).

A `FraudInvestigator` claims an `OPEN` flag, transitioning it to `UNDER_REVIEW`; on the claim, `investigator_id` is set to the calling `X-User-ID`. From `UNDER_REVIEW`, the same investigator who claimed the flag — and only that investigator — may substantiate or dismiss it. Substantiate transitions the flag from `UNDER_REVIEW` to `SUBSTANTIATED`; the request body carries the OCC pin `expected_fraudflag_version` and a non-empty `resolution_note`. A mismatch on `expected_fraudflag_version` is rejected with `ERR_STALE_FRAUDFLAG_VERSION` as described in §2.5. Dismissal transitions the flag from `UNDER_REVIEW` to `DISMISSED`; it requires a non-empty `resolution_note`. A flag that is still `OPEN` (no investigator has claimed it) may also be dismissed directly, again with a non-empty `resolution_note`; in that case the claiming-investigator segregation check does not apply because there is no claimant yet. An attempt to substantiate or dismiss an `UNDER_REVIEW` flag by an investigator other than the one whose `X-User-ID` matches `investigator_id` is rejected with `ERR_NOT_CLAIMING_INVESTIGATOR`. `SUBSTANTIATED` and `DISMISSED` are terminal.

### 3.10. Emergency Allotment Proclamations and the Test Clock

An `EmergencyAllotmentProclamation` is created by a `PolicyAdmin` with `state_code` (drawn from the same enum as `Household.state_code`), a `benefit_month` in `YYYY-MM` form, and an optional `min_supplement_cents` that defaults to 9,500 cents ($95.00). The pair `(state_code, benefit_month)` is unique across all proclamations; a duplicate is rejected with `ERR_DUPLICATE_PROCLAMATION`. The proclamation enters in `DRAFT`. Activation, also by `PolicyAdmin`, transitions the proclamation from `DRAFT` to `ACTIVE` only if `benefit_month` is the current month or a future month relative to `SystemClock.current_utc`. As a side effect of activation, every already-`ISSUED` `MonthlyAllotment` matching the same `state_code` and `benefit_month` becomes eligible for an adjust call (see §3.5); activation does not itself adjust those allotments, only opens the door for the issuer to do so. A proclamation transitions from `ACTIVE` to `EXPIRED` automatically once `SystemClock.current_utc` passes the end of `benefit_month`.

The system's logical wall clock is represented by a `SystemClock` resource with a single `current_utc` field. A `PolicyAdmin` may set it via a test-driving capability that accepts a single `to_iso8601` value in the request body and sets `SystemClock.current_utc` to that instant; advancing the clock can also fire deferred system transitions (a `SUBMITTED` application reaching its 30-day cutoff lands in `EXPIRED`, and an `ACTIVE` proclamation past the end of its `benefit_month` lands in `EXPIRED`). The current clock value is also readable. These capabilities exist for testing benefit-month boundaries, certification expiry, and 24-hour velocity windows; they are not part of normal production traffic.

## 4. Endpoint Definitions

All endpoints are mounted under `/snap`. Successful creation operations (those that mint a new resource) return HTTP 201; successful modification, list, and read operations return HTTP 200. Error responses use the HTTP statuses enumerated in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/snap/households` | Create a new household record in `PENDING`. | `Caseworker` |
| GET | `/snap/households/{id}` | Read a single household. | `Caseworker`, `Applicant`, `FraudInvestigator`, `BenefitIssuer` |
| GET | `/snap/households` | List households; supports filtering by `case_number`, `status`, `state_code`. | `Caseworker`, `FraudInvestigator`, `BenefitIssuer` |
| PATCH | `/snap/households/{id}` | Update mutable household fields (`address_line`, `heap_recipient`). | `Caseworker` |
| POST | `/snap/households/{id}/suspend` | Suspend an `ACTIVE` household. | `Caseworker` |
| POST | `/snap/households/{id}/reinstate` | Reinstate a `SUSPENDED` household. | `Caseworker` |
| POST | `/snap/households/{id}/terminate` | Terminate a household (irreversible). | `Caseworker` |
| POST | `/snap/household-members` | Add a member to a household. | `Caseworker` |
| GET | `/snap/household-members/{id}` | Read a household member. | `Caseworker`, `Applicant`, `FraudInvestigator` |
| GET | `/snap/household-members` | List members; filter by `household_id` and `status`. | `Caseworker`, `Applicant`, `FraudInvestigator` |
| PATCH | `/snap/household-members/{id}` | Update member income, `disabled`, or `status`. | `Caseworker` |
| POST | `/snap/applications` | Create an application in `DRAFT`. | `Caseworker`, `Applicant` |
| GET | `/snap/applications/{id}` | Read an application. | `Caseworker`, `Applicant` |
| GET | `/snap/applications` | List applications; filter by `household_id` or `status`. | `Caseworker`, `Applicant` |
| POST | `/snap/applications/{id}/submit` | Submit a `DRAFT` application. | `Applicant`, `Caseworker` |
| POST | `/snap/applications/{id}/approve` | Approve a `SUBMITTED` application; cascades to household and EBT card creation. | `Caseworker` |
| POST | `/snap/applications/{id}/deny` | Deny a `SUBMITTED` application. | `Caseworker` |
| GET | `/snap/ebt-cards/{id}` | Read an EBT card. | `Caseworker`, `Cardholder`, `FraudInvestigator` |
| GET | `/snap/ebt-cards` | List EBT cards; filter by `household_id` and `status`. | `Caseworker`, `Cardholder`, `FraudInvestigator` |
| POST | `/snap/ebt-cards/{id}/activate` | Activate a `PENDING_ISSUE` card; mints `pan_last4`. | `Cardholder`, `Caseworker` |
| POST | `/snap/ebt-cards/{id}/suspend` | Suspend an `ACTIVE` card. | `Caseworker`, `FraudInvestigator` |
| POST | `/snap/ebt-cards/{id}/reinstate` | Reinstate a `SUSPENDED` card. | `Caseworker` |
| POST | `/snap/ebt-cards/{id}/replace` | Replace an `ACTIVE` card; mints a successor. | `Cardholder`, `Caseworker` |
| POST | `/snap/monthly-allotments` | Create a `DRAFT` monthly allotment for a household and `benefit_month`. | `BenefitIssuer`, `Caseworker` |
| GET | `/snap/monthly-allotments/{id}` | Read an allotment. | `BenefitIssuer`, `Caseworker`, `Applicant` |
| GET | `/snap/monthly-allotments` | List allotments; filter by `household_id`, `benefit_month`, `status`. | `BenefitIssuer`, `Caseworker`, `Applicant` |
| POST | `/snap/monthly-allotments/{id}/issue` | Freeze and issue a `DRAFT` allotment. | `BenefitIssuer` |
| POST | `/snap/monthly-allotments/{id}/adjust` | Recompute `emergency_supplement_cents` after a new proclamation takes effect. | `BenefitIssuer` |
| POST | `/snap/eligible-item-categories` | Create an item category. | `PolicyAdmin` |
| GET | `/snap/eligible-item-categories/{id}` | Read an item category by id. | `PolicyAdmin`, `Merchant`, `Caseworker` |
| GET | `/snap/eligible-item-categories` | List categories; filter by `eligible` and `code`. | `PolicyAdmin`, `Merchant`, `Caseworker` |
| POST | `/snap/purchase-transactions` | Create a purchase transaction in `AUTHORIZED`. | `Merchant` |
| GET | `/snap/purchase-transactions/{id}` | Read a purchase transaction. | `Merchant`, `Caseworker`, `FraudInvestigator` |
| GET | `/snap/purchase-transactions` | List purchase transactions; filter by `ebt_card_id`, `household_id`, `status`. | `Merchant`, `Caseworker`, `FraudInvestigator` |
| POST | `/snap/purchase-transactions/{id}/settle` | Settle an `AUTHORIZED` transaction; recomputes velocity. | `Merchant` |
| POST | `/snap/purchase-transactions/{id}/reverse` | Reverse an `AUTHORIZED` transaction. | `Merchant` |
| GET | `/snap/fraud-flags/{id}` | Read a fraud flag. | `FraudInvestigator`, `Caseworker` |
| GET | `/snap/fraud-flags` | List fraud flags; filter by `household_id`, `status`, `trigger_rule`. | `FraudInvestigator`, `Caseworker` |
| POST | `/snap/fraud-flags` | Manually raise a fraud flag (referral). | `Caseworker`, `FraudInvestigator` |
| POST | `/snap/fraud-flags/{id}/claim` | Claim an `OPEN` flag; sets `investigator_id`. | `FraudInvestigator` |
| POST | `/snap/fraud-flags/{id}/substantiate` | Substantiate an `UNDER_REVIEW` flag. | `FraudInvestigator` |
| POST | `/snap/fraud-flags/{id}/dismiss` | Dismiss an `OPEN` or `UNDER_REVIEW` flag. | `FraudInvestigator` |
| POST | `/snap/abawd-waivers` | Request a waiver for an ABAWD member. | `Caseworker`, `Applicant` |
| GET | `/snap/abawd-waivers/{id}` | Read a waiver. | `Caseworker`, `Applicant` |
| GET | `/snap/abawd-waivers` | List waivers; filter by `household_member_id`, `quarter`, `status`. | `Caseworker`, `Applicant` |
| POST | `/snap/abawd-waivers/{id}/approve` | Approve a `PENDING` waiver. | `Caseworker` |
| POST | `/snap/abawd-waivers/{id}/deny` | Deny a `PENDING` waiver. | `Caseworker` |
| POST | `/snap/abawd-waivers/{id}/revoke` | Revoke an `APPROVED` waiver. | `Caseworker` |
| POST | `/snap/emergency-allotments` | Create a `DRAFT` proclamation for a state and `benefit_month`. | `PolicyAdmin` |
| GET | `/snap/emergency-allotments/{id}` | Read a proclamation. | `PolicyAdmin`, `BenefitIssuer`, `Caseworker` |
| GET | `/snap/emergency-allotments` | List proclamations; filter by `state_code`, `benefit_month`, `status`. | `PolicyAdmin`, `BenefitIssuer`, `Caseworker` |
| POST | `/snap/emergency-allotments/{id}/activate` | Activate a `DRAFT` proclamation. | `PolicyAdmin` |
| POST | `/snap/_clock/set_current_utc` | Test-only: set the server's logical clock to a supplied `to_iso8601` instant. | `PolicyAdmin` |
| GET | `/snap/_clock` | Test-only: read the server's logical clock. | `PolicyAdmin`, `Caseworker`, `BenefitIssuer`, `FraudInvestigator` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PARENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_HOUSEHOLD_NOT_ACTIVE` | 409 |
| `ERR_CARD_NOT_ACTIVE` | 409 |
| `ERR_NOT_CLAIMING_INVESTIGATOR` | 403 |
| `ERR_DUPLICATE_CASE_NUMBER` | 409 |
| `ERR_DUPLICATE_ALLOTMENT_MONTH` | 409 |
| `ERR_DUPLICATE_WAIVER_QUARTER` | 409 |
| `ERR_DUPLICATE_PROCLAMATION` | 409 |
| `ERR_BENEFIT_MONTH_IN_PAST` | 422 |
| `ERR_ISSUANCE_TOO_EARLY` | 409 |
| `ERR_INCOME_LIMIT_EXCEEDED` | 409 |
| `ERR_ABAWD_REQUIREMENT_UNMET` | 409 |
| `ERR_ALL_ITEMS_INELIGIBLE` | 422 |
| `ERR_INVALID_LINE_ITEMS` | 422 |
| `ERR_OUT_OF_STATE_BLOCKED` | 409 |
| `ERR_STALE_HOUSEHOLD_VERSION` | 412 |
| `ERR_STALE_FRAUDFLAG_VERSION` | 412 |
