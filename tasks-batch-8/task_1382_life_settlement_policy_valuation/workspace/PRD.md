# Life Settlement Policy Valuation API — Product Requirements Document

## 1. Introduction

Life settlement providers operate at the intersection of insurance, capital markets, and regulation: they purchase in-force life insurance policies from policyholders (typically seniors), assume the ongoing premium obligation, and collect the death benefit when the insured passes away. Between a broker's first phone call and the final investor report, a single case touches eligibility screening, life-expectancy underwriting, multi-round price negotiation, regulated closing documentation, escrowed funding with a statutory rescission window, years of premium servicing, insured mortality tracking, death-claim adjudication, and portfolio valuation. Each of these steps carries its own regulatory and fiscal constraints, and several must be segregated across independent desks.

This document specifies the Life Settlement Policy Valuation API: a system of record for one provider's end-to-end pipeline. It tracks brokers, investors, insureds, policies, and the provider's state licenses; drives each `PolicyCase` from `DRAFT` through screening, underwriting, marketing, closing, and acquisition; manages the escrow waterfall and seller rescission; optimizes premium strategy on acquired policies; verifies insured death through multi-source tracking; and values portfolios with two distinct valuation methods and two distinct return metrics.

A design goal throughout is auditability. Screening runs are immutable records, negotiation rounds are numbered and versioned, compliance holds cascade from license suspension without human intervention, and treasury actions are segregated from compliance approval by explicit duty checks. All monetary values are integers of cents; all life-expectancy figures are integers of months; a provider-controlled logical clock — never wall-clock time — drives every temporal rule in the system.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, or the role value is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is recognized but does not appear in the endpoint's authorized role list, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The recognized roles, spelled exactly, are:

- `PlatformAdmin` — provider platform superuser; registers brokers and investors, drives the logical clock, and creates licenses.
- `Broker` — licensed settlement broker representing the seller; owns the cases it creates.
- `Underwriter` — provider underwriting desk; orders and delivers life-expectancy reports, renders pricing decisions, and negotiates offers on the provider side.
- `CaseManager` — provider operations; screening runs, disclosures, closing logistics, carrier confirmation, and insured tracking.
- `ComplianceOfficer` — compliance; license suspension and reinstatement, closing approval, rescission, tracking verification, and claim adjudication. Segregated from funding and release duties per case.
- `FinanceOfficer` — treasury; escrow funding and release plus disbursement and premium cash movements. Segregated from closing approval per case.
- `PortfolioManager` — portfolio desk; portfolio creation, case assignment, premium optimization, and valuation snapshots.
- `Investor` — external investor; read-only access to portfolios where it holds an allocation and their snapshots.

Identity semantics per role:

- When `X-User-Role` is `Broker`, `X-User-ID` is the `id` of the acting `Broker`; ownership checks on any resource that references a `Broker` (a case's `broker_id`, an insured's `created_by_broker_id`) compare that foreign-key field to `X-User-ID`. A violation is rejected with `ERR_NOT_CASE_OWNER` (HTTP 403).
- When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor`; reads of a portfolio or its snapshots are authorized only when the portfolio's `allocations` contain an entry whose `investor_id` equals `X-User-ID`. A violation is rejected with `ERR_INVESTOR_NOT_ALLOCATED` (HTTP 403).
- When `X-User-Role` is `PlatformAdmin`, `Underwriter`, `CaseManager`, `ComplianceOfficer`, `FinanceOfficer`, or `PortfolioManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `approved_by_user_id` on `ClosingPackage` or `released_by_user_id` on `EscrowAccount`) but does not compare it to any entity's `id` for ownership purposes — though the segregation-of-duties check described later does compare two such recorded identifiers against each other.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may be at most 100. `offset` defaults to 0. List results are always sorted by `created_at` ascending. The `meta` block of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every entity carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp. All entities except `EligibilityScreening` additionally carry `updated_at` and an integer `version` that starts at 1 and increments by 1 on every mutation of that entity. Timestamps are ISO 8601 UTC with three fractional digits. `EligibilityScreening` is an immutable record entity: it carries only `id` and `created_at`, has no update endpoints, no `updated_at`, and no `version`; re-running a screening creates a new row rather than mutating an old one.

All temporal logic in the system — age computation, contestability windows, offer expiry, license expiry, marketing deadlines, premium grace deadlines, LE-report validity, rescission windows — reads from a single logical clock, never from wall-clock time. The clock's startup default, before any call to set it, is exactly 2026-08-01T00:00:00Z. A `PlatformAdmin` may advance the clock through an admin-only test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value and returns `current_utc`. Setting the clock evaluates every automatic transition in the system: a `PENDING` or `COUNTERED` offer whose `expires_at` is earlier than the new clock becomes `EXPIRED`; a `DELIVERED` life-expectancy report whose `valid_through` is earlier than the new clock becomes `EXPIRED`; an `ACTIVE` or `SUSPENDED` license whose `expiry_date` is earlier than the new clock date becomes `EXPIRED`; a `SCHEDULED` premium payment whose `grace_deadline` is earlier than the new clock becomes `MISSED` (triggering the lapse cascade described in §3.7); and a `MARKETED` case whose `marketing_deadline` has passed with no `PENDING` or `COUNTERED` offers on it becomes `EXPIRED`.

### 2.5. Monetary Precision, Rounding, and Pricing Conventions

All money is represented as integer cents. Wherever a computed amount is not already integral, it is rounded half-up to the nearest cent at the step the rule specifies; where a rule says intermediate values remain unrounded until the final step, the final result alone is rounded half-up. Life expectancy is expressed in integer months; the per-report adjustment floors, and the cross-report blend rounds half-up. Return metrics are expressed in integer basis points, rounded half-up. Basis-point rates are converted by dividing by ten thousand; an annual rate becomes a monthly rate by dividing by twelve.

### 2.6. Optimistic Concurrency Control

Three write endpoints require the caller to supply the parent entity's version as last observed, and reject the write when that expectation no longer holds. No other endpoint takes a version field.

- Countering an offer requires `expected_offer_version` carrying the client's last observed `version` of the target offer. If the offer's version has advanced since that observation — for example because a re-offer response has already rewritten `amount_cents` and `round_number`, so the client's counter would be computed against superseded terms — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a premium schedule on a case requires `expected_case_version` matching the case's current `version`. Because creation supersedes the currently `ACTIVE` schedule, a supersede decision made against a stale case view must not silently succeed; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a valuation snapshot on a portfolio requires `expected_portfolio_version` matching the portfolio's current `version`. Because creation supersedes the current `DRAFT` snapshot and must price against the latest holdings and invested-capital state, a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Nested Resource Retrieval and Validation Order

Where a URL nests one resource under another, path identifiers are validated left to right: each id must exist before the next is examined, and the first missing id yields `ERR_NOT_FOUND` (HTTP 404). Body-supplied foreign keys (`policy_id`, `insured_id`, `portfolio_id`, and the investor ids inside `allocations`) are validated for existence the same way, also producing `ERR_NOT_FOUND` when absent.

Across all rules attached to an endpoint, evaluation follows a fixed priority order, and the first failure determines the response:

1. Header presence and role recognition (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role membership in the endpoint's authorized list (`ERR_FORBIDDEN_FOR_ROLE`).
3. Resource ownership — broker ownership of the case chain (`ERR_NOT_CASE_OWNER`) and investor allocation on portfolio and snapshot reads (`ERR_INVESTOR_NOT_ALLOCATED`).
4. Malformed body, missing required field, invalid enum member, negative amount, or invalid date (`ERR_INVALID_REQUEST`, HTTP 400).
5. Existence of path ids and body-supplied foreign keys (`ERR_NOT_FOUND`).
6. Terminal-state guard on the target resource: an action aimed at a resource already in a terminal state — countering an `EXPIRED` offer, paying a `PAID` payment, approving a `CLOSED` package — is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409).
7. From-state validity for the attempted trigger (`ERR_INVALID_STATE_TRANSITION`, HTTP 409, and its domain variants `ERR_CASE_NOT_MARKETED`, `ERR_CASE_HAS_ACTIVE_CLOSING`, `ERR_ESCROW_NOT_FUNDED`, `ERR_POLICY_NOT_ACQUIRED`).
8. Business-safety rules: `ERR_DISCLOSURES_INCOMPLETE`, `ERR_CASE_ON_COMPLIANCE_HOLD`, `ERR_STATE_LICENSE_NOT_ACTIVE`, `ERR_LICENSE_EXPIRING_SOON`, `ERR_SEGREGATION_OF_DUTIES`.
9. Business-temporal rules: `ERR_RESCISSION_WINDOW_ACTIVE`, `ERR_RESCISSION_WINDOW_EXPIRED`, `ERR_LE_REPORT_EXPIRED`, `ERR_LE_REPORT_REQUIRED`, `ERR_INVALID_PERIOD`, `ERR_VALUATION_INPUT_STALE`.
10. Business-constraint rules: `ERR_DUPLICATE_ACTIVE_CASE`, `ERR_POLICY_LOCKED_BY_ACTIVE_CASE`, `ERR_MAX_NEGOTIATION_ROUNDS_REACHED`, `ERR_COUNTER_INCREMENT_TOO_SMALL`, `ERR_CLOSING_DOCS_INCOMPLETE`, `ERR_VERIFICATION_SOURCES_INSUFFICIENT`, `ERR_LICENSE_WINDOW_OVERLAP`, `ERR_SNAPSHOT_PERIOD_OVERLAP`.
11. Business-referential: `ERR_PORTFOLIO_NOT_ASSIGNED`.
12. Business-fiscal: `ERR_ESCROW_FUNDS_MISMATCH`, `ERR_COMMISSION_CAP_EXCEEDED`, `ERR_PAYMENT_AMOUNT_MISMATCH`.
13. Stale-version OCC rejection: `ERR_STALE_VERSION`.

Because OCC is the lowest-priority check, a request carrying a stale `expected_offer_version` but also violating a higher-priority rule surfaces the higher-priority error, not the stale-version error.

### 2.8. Licensing Posture and the Compliance-Hold Cascade

The provider's authority to transact in a given state is represented by `StateLicense` rows, each defining a closed window from `effective_date` through `expiry_date`, both inclusive, created with a `state_code` and `license_number`. Two windows for the same state must be strictly disjoint: a new license's `effective_date` must fall strictly after the `expiry_date` of every existing row for that state — touching or overlapping an existing window is rejected with `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 409). A license's `status` is one of `ACTIVE`, `SUSPENDED`, or `EXPIRED`, starting at `ACTIVE`. A suspension or reinstatement is a compliance action and increments the license's `version`; expiry is automatic when the clock date passes `expiry_date`, from either `ACTIVE` or `SUSPENDED`.

Every `PolicyCase` carries a parallel compliance axis, `hold_status`, taking values `CLEAR` or `COMPLIANCE_HOLD` and evolving independently of the case's primary `status`. The governing license for a case is the `StateLicense` row whose `state_code` matches the case's insured's `state_code`, whose `status` is `ACTIVE`, and within whose window the current clock date falls. When that governing license transitions `ACTIVE` to `SUSPENDED` while the case is `MARKETED` or `IN_CLOSING`, the case's `hold_status` moves from `CLEAR` to `COMPLIANCE_HOLD` as a direct cascade of the suspension. When the suspended license is reinstated, the cases held by that suspension return to `CLEAR`. A case under `COMPLIANCE_HOLD` cannot accept an offer (directly or via counter-acceptance), cannot have its closing package approved, cannot have its escrow funded, and cannot have its escrow released; each of those attempts is rejected with `ERR_CASE_ON_COMPLIANCE_HOLD` (HTTP 409).

### 2.9. Registry Entities

Brokers are registered with a `name`, `license_number`, and resident `state_code`; a broker record's `status` is always `ACTIVE` — the registry keeps a single-state record. Investors are registered with a `name` and an `investor_type` of `INDIVIDUAL` or `FUND`; an investor's `status` likewise remains `ACTIVE`.

An `Insured` captures `full_name`, `date_of_birth` (an ISO date in YYYY-MM-DD form), `state_code`, `gender` (`M` or `F`), `smoker_status` (`TOBACCO`, `NON_TOBACCO`, or `UNKNOWN`), and `ssn_last4`. When a broker creates the insured, the system sets `created_by_broker_id` from the caller's `X-User-ID`; when a case manager creates the insured, `created_by_broker_id` is null. The insured's `status` begins at `LIVING` and becomes `DECEASED` only through the death-claim maturity cascade. Every read of an insured exposes the computed `age_years`: whole years from `date_of_birth` to the current logical clock date, where reaching the birthday increments the count — that is, the age is the clock year minus the birth year, reduced by one when the clock's month-and-day has not yet reached the birth month-and-day.

A `Policy` records its `insured_id`, the issuing `carrier_name`, the carrier's `policy_number`, `face_amount_cents`, a `policy_type` of `WHOLE_LIFE`, `UNIVERSAL_LIFE`, `VARIABLE`, `TERM_CONVERTIBLE`, or `TERM_NONCONVERTIBLE`, the `issue_date`, and the current `annual_premium_cents`. `cash_value_cents` and `policy_loan_cents` are optional at creation and default to 0. A policy's `status` begins at `IN_FORCE` and may later become `LAPSED` or `MATURED`. Every read exposes the computed `in_contestability`: true exactly when the current clock date falls earlier than twenty-four months after `issue_date`. A broker creating a policy must have created the insured it names — if the insured's `created_by_broker_id` does not equal the caller's `X-User-ID`, creation is rejected with `ERR_NOT_CASE_OWNER`.

A broker or case manager may amend a policy's financial fields — `face_amount_cents`, `annual_premium_cents`, `cash_value_cents`, `policy_loan_cents` — through the amendment endpoint, but only while no case of that policy is in `UNDERWRITING`, `MARKETED`, `IN_CLOSING`, or `ACQUIRED`; an amendment attempted under an active case in one of those states is rejected with `ERR_POLICY_LOCKED_BY_ACTIVE_CASE` (HTTP 409). A broker amending a policy must own the insured chain — the insured's `created_by_broker_id` must equal the caller's `X-User-ID`, otherwise `ERR_NOT_CASE_OWNER`.

### 2.10. Hierarchical Consistency on Mutation

Any mutation of an entity — whether by direct action or by cascade from a related entity — refreshes that entity's `updated_at` and increments its `version` by 1. Cascades therefore surface as observable version bumps on the affected entities: suspending a license increments the license's `version`; funding an escrow increments the escrow's `version`; assigning a case to a portfolio increments both the case's and the portfolio's `version`; paying a premium increments the payment's `version` and dirties the portfolio, which increments the portfolio's `version` as well. Case transitions triggered by accept, cancel, release, rescind, settle, or lapse are mutations of the case like any other and carry the same `updated_at`/`version` semantics.

## 3. Business Logic & Workflows

### 3.1. Opening a Case and Eligibility Screening

A broker originates a case by naming a `policy_id`; the new `PolicyCase` is created in `DRAFT` with its `broker_id` set from the caller's `X-User-ID`, its `hold_status` `CLEAR`, its `screening_failure_reasons` empty, and `portfolio_id`, `blended_le_months`, `reserve_price_cents`, `accepted_offer_id`, `broker_commission_bps`, `disclosures_delivered_at`, `marketed_at`, `marketing_deadline`, `acquired_at`, `purchase_price_cents`, and `matured_at` all unset; `disclosures_delivered` begins false. A policy may carry at most one case in a non-terminal status at a time; attempting to open a second case against a policy that already has one is rejected with `ERR_DUPLICATE_ACTIVE_CASE` (HTTP 409).

Submission by the owning broker moves the case from `DRAFT` to `SCREENING`; a broker who does not own the case — the case's `broker_id` does not equal the caller's `X-User-ID` — is rejected with `ERR_NOT_CASE_OWNER`. From `DRAFT`, and later from `SCREENING`, `SCREEN_FAILED`, `UNDERWRITING`, or `MARKETED`, the owning broker may also withdraw the case outright, landing it in `WITHDRAWN`. Withdrawal is never permitted while the case is `IN_CLOSING`; that attempt is always rejected with `ERR_CASE_HAS_ACTIVE_CLOSING` (HTTP 409). Withdrawal cascades: withdrawing from `UNDERWRITING` supersedes any `ORDERED` life-expectancy reports, and withdrawing from `MARKETED` withdraws every `PENDING` or `COUNTERED` offer on the case.

While a case is `SCREENING` (first run) or `SCREEN_FAILED` (rerun after the broker amends policy data), a case manager runs an eligibility screening. The run evaluates five checks, and the resulting `EligibilityScreening` record stores the per-check booleans in its `checks` object — `license_ok`, `face_ok`, `age_ok`, `contestability_ok`, `type_ok` — together with the `run_at` clock timestamp. The license check requires a governing `StateLicense` for the insured's `state_code` that is `ACTIVE` and whose window covers the current clock date. The face check requires the policy's `face_amount_cents` to be at least 10000000 — one hundred thousand dollars, inclusive. The age check requires the insured's `age_years` at the current clock to be at least 65, inclusive. The contestability check requires the current clock date to be at or past the policy's `issue_date` plus 24 months — that is, the policy must have aged out of its contestability window. The type check requires the policy's `policy_type` to be anything other than `TERM_NONCONVERTIBLE`.

The screening `result` is `PASSED` when all five checks are true, and `FAILED` otherwise. The record's `failure_reasons` lists the failed check codes in the fixed order LICENSE, FACE, AGE, CONTESTABILITY, TYPE. A `PASSED` result moves the case from `SCREENING` to `UNDERWRITING` and clears `screening_failure_reasons` to an empty list. A `FAILED` result moves the case from `SCREENING` to `SCREEN_FAILED` and copies the record's `failure_reasons` onto the case's `screening_failure_reasons` in the same order. A rerun from `SCREEN_FAILED` re-enters `SCREENING` and resolves within the same request, creating a fresh `EligibilityScreening` row each time; the older rows remain as an immutable audit trail.

### 3.2. Life-Expectancy Underwriting and Pricing

While a case is in `UNDERWRITING`, `MARKETED`, or `ACQUIRED`, an underwriter may order a life-expectancy report by supplying the `underwriter_tier` — `A` or `B`; the report begins in `ORDERED`. Ordering or delivering outside those three case states is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Delivery supplies `base_le_months`, the raw life expectancy in months, and `impairment_debits`, an array of decimal debits each between 0 and 0.9 inclusive. On delivery the report's `adjusted_le_months` is computed: start with `base_le_months`, multiply it by one minus each debit in turn (that is, by the product of all one-minus-debit factors), floor the result to a whole month, and floor the final figure at 1 so a heavily debited life still yields at least one month. The delivered report's `delivered_at` is set to the clock, and its `valid_through` to `delivered_at` plus 180 days; the report moves from `ORDERED` to `DELIVERED` and its `version` increments. Delivering a new report supersedes any other currently `DELIVERED` report on the same case carrying the same `underwriter_tier` — the older sibling moves to `SUPERSEDED`. Independently, a `DELIVERED` report becomes `EXPIRED` automatically once the clock passes its `valid_through`.

An underwriter's pricing decision on a case in `UNDERWRITING` takes a single `decision` value. When the decision is to decline, the case moves from `UNDERWRITING` to `UW_DECLINED`; all non-terminal offers on the case become `EXPIRED`, while non-terminal life-expectancy reports are left unchanged.

When the decision is to approve, the case must first have at least one eligible life-expectancy report: a report on the case in `DELIVERED` status whose `valid_through` has not yet passed at the current clock. If no report has ever been delivered for the case, the decision is rejected with `ERR_LE_REPORT_REQUIRED` (HTTP 422); if reports were delivered but every one has expired, the rejection is `ERR_LE_REPORT_EXPIRED` (HTTP 409). Given at least one eligible report, approval blends their adjusted expectancies. With exactly one eligible report, the case's `blended_le_months` is that report's `adjusted_le_months`. With several, each report is weighted by tier — a tier-`A` report weighs 3, a tier-`B` report weighs 1 — and the blend is the weighted sum of adjusted months divided by the sum of weights, rounded half-up to a whole month. Reports in `ORDERED`, `SUPERSEDED`, or `EXPIRED` never enter the blend.

The same approval computes the case's `reserve_price_cents`, the maximum supportable offer, from the policy's `face_amount_cents` and `annual_premium_cents` and the just-computed `blended_le_months`. Let k denote the blended expectancy in months. The monthly pricing rate is 1300 basis points — an annual 13 percent — divided by twelve, and the monthly discount factor v is the reciprocal of one plus that rate. The present value of the death benefit is the face amount multiplied by v raised to the k-th power. The present value of future premiums is one twelfth of the annual premium multiplied by the annuity-immediate factor over k months — that factor being one minus v-to-the-k, divided by the monthly rate. The expense load is a flat 250000 cents (twenty-five hundred dollars) plus the face amount times 150 basis points, the latter rounded half-up to cents. The raw reserve is the benefit present value minus the premium present value minus the expense load, with intermediate values carried unrounded until the final round. The reserve price is then the smaller of two bounds — the face amount times 8000 basis points (80 percent of face) rounded half-up, and the raw reserve rounded half-up — floored at zero so it can never go negative.

An approved case moves from `UNDERWRITING` to `MARKETED`; the system stamps `marketed_at` with the clock and sets `marketing_deadline` to `marketed_at` plus 90 days. A `MARKETED` case whose deadline passes with no `PENDING` or `COUNTERED` offers becomes `EXPIRED` automatically. If a marketed case's reports have all aged out and fresh underwriting is wanted, an underwriter may send the case from `MARKETED` back to `UNDERWRITING` through reunderwriting — but only while no offer on the case is `PENDING` or `COUNTERED`; with live offers the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`. Reunderwriting clears `blended_le_months`, `reserve_price_cents`, `marketed_at`, and `marketing_deadline` back to unset.

Before any offer on the case can be accepted, a case manager must record delivery of the disclosure packet to the seller, valid only while the case is in `UNDERWRITING` or `MARKETED` (otherwise `ERR_INVALID_STATE_TRANSITION`). The payload's `packet_types` must include every one of COMPENSATION, ALTERNATIVES, TAX, PRIVACY, and RESCISSION_RIGHTS; a missing type is rejected with `ERR_INVALID_REQUEST`. A valid delivery sets `disclosures_delivered` true and stamps `disclosures_delivered_at` with the clock.

### 3.3. Provider Bidding and Negotiation

On a `MARKETED` case, an underwriter creates a provider offer by supplying `amount_cents` and optionally `expires_in_days`; the offer starts `PENDING` with `round_number` 1. Its `expires_at` is the creation clock plus `expires_in_days` — defaulting to 10 days when omitted, and capped at 30 days; a request above 30 is rejected with `ERR_INVALID_REQUEST`. Offer creation on a case that is not `MARKETED` is rejected with `ERR_CASE_NOT_MARKETED` (HTTP 409). A `PENDING` or `COUNTERED` offer whose `expires_at` passes becomes `EXPIRED` automatically.

The negotiation alternates between the desks. The owning broker counters a `PENDING` offer by supplying `counter_amount_cents` plus the OCC field `expected_offer_version` described in §2.6. Countering requires the case to be `MARKETED` (`ERR_CASE_NOT_MARKETED`), the caller to own the case (`ERR_NOT_CASE_OWNER`), the supplied version to match (`ERR_STALE_VERSION`), the round ceiling to hold — `round_number` must be below 4, so at most four rounds of pricing are ever negotiated, with a fourth-round attempt rejected as `ERR_MAX_NEGOTIATION_ROUNDS_REACHED` (HTTP 409) — and the counter to clear a minimum increment: `counter_amount_cents` must be at least the offer's `amount_cents` multiplied by 101 and divided by 100, rounded half-up — a one-percent minimum bump — with anything less rejected as `ERR_COUNTER_INCREMENT_TOO_SMALL` (HTTP 422). A successful counter sets the offer's `counter_amount_cents`, increments `round_number` by 1, moves the offer from `PENDING` to `COUNTERED`, and increments the offer's `version`.

The underwriter responds to a `COUNTERED` offer with an `action`. `RE_OFFER` replaces the offer's `amount_cents` with a supplied payload amount that must be strictly greater than the previous `amount_cents` and no greater than the outstanding `counter_amount_cents` — an amount outside that band is rejected with `ERR_INVALID_REQUEST` — clears `counter_amount_cents` back to unset, increments `round_number` (the same round ceiling applies, with a fourth-round attempt rejected as `ERR_MAX_NEGOTIATION_ROUNDS_REACHED`), and returns the offer to `PENDING`. `REJECT` rejects the countered offer. `ACCEPT_COUNTER` accepts the broker's counter: it runs the full acceptance cascade described below, using `counter_amount_cents` as the price, and captures the case's `broker_commission_bps` from the response payload's optional `broker_commission_bps`, defaulting to 0 when omitted.

Acceptance — whether a broker accepts a `PENDING` offer outright with a `broker_commission_bps` payload, or an underwriter accepts a counter — is the pivotal transition of the pipeline, and its guard checks are evaluated in this order: the case must be `MARKETED` (`ERR_CASE_NOT_MARKETED`); for the direct accept the caller must own the case (`ERR_NOT_CASE_OWNER`); the case's `disclosures_delivered` must be true, since a seller cannot sign away a policy before receiving the statutory packet (`ERR_DISCLOSURES_INCOMPLETE`, HTTP 422); the case's `hold_status` must be `CLEAR` (`ERR_CASE_ON_COMPLIANCE_HOLD`); and, for the direct accept, the proposed `broker_commission_bps` must not exceed 600 — six percent of price, the fiscal cap — (`ERR_COMMISSION_CAP_EXCEEDED`, HTTP 422). On acceptance the offer's `effective_price_cents` is fixed: the `counter_amount_cents` when accepted from `COUNTERED`, otherwise the `amount_cents`; it stays unset until the offer reaches `ACCEPTED`. The accepted offer's `version` increments.

The acceptance cascade then fires in full: the case's `accepted_offer_id` is set to the accepted offer and its `purchase_price_cents` to the offer's `effective_price_cents`; the captured `broker_commission_bps` is stored on the case; the case moves from `MARKETED` to `IN_CLOSING`; every other offer on the same case in `PENDING` or `COUNTERED` moves to `REJECTED`; a `ClosingPackage` is created in `ASSEMBLED` with its document checklist; and the package's creation cascades to create the case's `EscrowAccount` in `OPEN` with `expected_funding_cents` pre-computed (§3.5). Offers may also end without acceptance: the owning broker may reject a `PENDING` or `COUNTERED` offer, the underwriter may withdraw a `PENDING` or `COUNTERED` offer, and an offer is withdrawn automatically when its case is withdrawn, its case's closing is cancelled, or its case is declined in underwriting (the decline expires non-terminal offers, as above).

### 3.4. The Closing Package and Change of Ownership

The closing package carries `case_id` and the `offer_id` of the accepted offer, a `documents` checklist, and space for `deficiency_notes`, `approved_by_user_id`, and `ownership_confirmed_at`. Each checklist row records a `doc_type`, whether it is `required`, whether it is `signed`, and `signed_at`. One row is state-dependent: STATE_SUPPLEMENT is required exactly when the insured's `state_code` is CA or NY.

A case manager moves the package from `ASSEMBLED` to `OUT_FOR_SIGNATURE`, then records signatures one document at a time by naming a `doc_type`; the name must match a checklist row (an unknown `doc_type` is rejected with `ERR_INVALID_REQUEST`), and signing an already-signed row is likewise rejected with `ERR_INVALID_REQUEST`. Submission for compliance review moves the package from `OUT_FOR_SIGNATURE` to `COMPLIANCE_REVIEW` and requires at least one document signed — completeness is deliberately not required at this gate, because completeness is enforced at approval instead; a submission with no signatures at all is rejected with `ERR_INVALID_STATE_TRANSITION`.

A compliance officer reviewing the package has two paths. A deficiency return names `deficient_doc_types` and optional `deficiency_notes`; every named type must correspond to a checklist row (otherwise `ERR_INVALID_REQUEST`); the named rows are reset to unsigned with `signed_at` cleared, the notes are stored, and the package returns from `COMPLIANCE_REVIEW` to `OUT_FOR_SIGNATURE`. Approval, by contrast, runs three checks in order. First, business safety: the case's `hold_status` must be `CLEAR` (`ERR_CASE_ON_COMPLIANCE_HOLD`). Second, license posture: a governing `StateLicense` for the insured's `state_code` must exist, be `ACTIVE`, and reach at least thirty days beyond the current clock date — a missing or suspended license is rejected with `ERR_STATE_LICENSE_NOT_ACTIVE` (HTTP 409), and one whose `expiry_date` falls within the thirty-day horizon is rejected with `ERR_LICENSE_EXPIRING_SOON` (HTTP 409). Third, completeness: every required document must be signed (`ERR_CLOSING_DOCS_INCOMPLETE`, HTTP 422). Approval stamps the package's `approved_by_user_id` with the caller's `X-User-ID` — the segregation-of-duties anchor referenced again at escrow release.

An approved package is submitted to the carrier, moving from `APPROVED` to `CARRIER_SUBMITTED`; this step requires the case's escrow account to be `FUNDED` already, and is rejected with `ERR_ESCROW_NOT_FUNDED` (HTTP 409) otherwise. When the carrier confirms the change of ownership and beneficiary, a case manager records the confirmation: the package moves from `CARRIER_SUBMITTED` to `OWNERSHIP_CONFIRMED` and stamps `ownership_confirmed_at`. The package then moves from `OWNERSHIP_CONFIRMED` to `CLOSED` as a side effect of the escrow release (§3.5).

Cancellation unwinds. A case manager may cancel a package in `ASSEMBLED`, `OUT_FOR_SIGNATURE`, or `COMPLIANCE_REVIEW`, but only while the case's escrow account is still `OPEN`; cancelling after funding is rejected with `ERR_INVALID_STATE_TRANSITION`. A manual cancellation moves the case from `IN_CLOSING` back to `MARKETED`, withdraws the accepted offer (which moves from `ACCEPTED` to `WITHDRAWN`), clears the case's `accepted_offer_id` and `purchase_price_cents`, and closes the still-`OPEN` escrow account. Packages in `APPROVED`, `CARRIER_SUBMITTED`, or `OWNERSHIP_CONFIRMED` can no longer be cancelled by hand; they reach `CANCELLED` only as a side effect of escrow rescission.

### 3.5. Escrow, the Rescission Window, and the Disbursement Waterfall

The escrow account created at acceptance holds the purchase funds. Its `expected_funding_cents` is the sum of three components: the accepted offer's effective price, a flat escrow fee of 75000 cents (seven hundred fifty dollars), and a servicing fee of the price times 25 basis points rounded half-up to cents. `funded_amount_cents`, `funded_at`, `releasable_at`, `released_at`, `released_by_user_id`, and `refund_cents` all begin unset, and `balance_cents` begins at 0.

Funding is a treasury action with four guards. The closing package must be `APPROVED` (otherwise `ERR_INVALID_STATE_TRANSITION`); the case's `hold_status` must be `CLEAR` (`ERR_CASE_ON_COMPLIANCE_HOLD`); the case must already carry a `portfolio_id` (`ERR_PORTFOLIO_NOT_ASSIGNED`, HTTP 422); and the deposited `amount_cents` must equal `expected_funding_cents` exactly (`ERR_ESCROW_FUNDS_MISMATCH`, HTTP 422). A valid funding stamps `funded_at` with the clock, sets `releasable_at` to `funded_at` plus 15 days — the seller's statutory rescission window — records `funded_amount_cents`, sets `balance_cents` to the funded amount, and moves the account from `OPEN` to `FUNDED` with a version increment. Funding also dirties the destination portfolio in one cascade: the portfolio's `invested_capital_cents` grows by the case's `purchase_price_cents`, its `holding_count` grows by 1, `nav_stale` becomes true, and the portfolio's `version` increments.

Release moves the account from `FUNDED` to `RELEASED` and runs the disbursement waterfall. Its guards, in evaluation order: the clock must have reached `releasable_at` — an earlier attempt is rejected with `ERR_RESCISSION_WINDOW_ACTIVE` (HTTP 409); the case's `hold_status` must be `CLEAR` (`ERR_CASE_ON_COMPLIANCE_HOLD`); the governing `StateLicense` must be `ACTIVE` (`ERR_STATE_LICENSE_NOT_ACTIVE`); the releasing finance officer's `X-User-ID` must differ from the closing package's `approved_by_user_id` — the segregation-of-duties check, rejected as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the same operator approved the package; and the closing package must be in `OWNERSHIP_CONFIRMED` (otherwise `ERR_INVALID_STATE_TRANSITION`).

The waterfall itself allocates the funds into exactly four `Disbursement` rows, each stamped with the account's `escrow_id` and a `bucket` value of ESCROW_FEE, SERVICING_FEE, BROKER_COMMISSION, or SELLER_NET, created `PENDING` in that fixed bucket order, and each bucket's `amount_cents` is rounded half-up to cents immediately, before the next bucket is computed — the rounding is per-bucket, never a single rounding of the total. The ESCROW_FEE row is the flat 75000 cents. The SERVICING_FEE row is the price times 25 basis points, rounded half-up. The BROKER_COMMISSION row is the smaller of the price times the case's stored `broker_commission_bps` (rounded half-up) and the policy's face amount times 600 basis points (rounded half-up); when a commission is payable, the row's `payee_broker_id` names the case's broker, and otherwise that field stays unset. The SELLER_NET row receives the price minus the commission — the seller's proceeds net of broker compensation — while the two fees are funded by the provider on top of price, so the four disbursements sum exactly to the funded amount and `balance_cents` lands at 0. Because the commission never exceeds 600 basis points of price, seller net always clears at least 94 percent of price and the bucket can never go negative. Release also stamps `released_at`, records `released_by_user_id`, increments the account's `version`, closes the closing package (`OWNERSHIP_CONFIRMED` → `CLOSED`), and moves the case from `IN_CLOSING` to `ACQUIRED`, stamping `acquired_at`.

Rescission is the mirror path: while the clock is still earlier than `releasable_at`, a compliance officer may rescind the funded escrow — at or after `releasable_at` the window has closed and the attempt is rejected with `ERR_RESCISSION_WINDOW_EXPIRED` (HTTP 409). Rescission refunds the provider's funding source in full: `refund_cents` equals `funded_amount_cents` with no fee retained, `balance_cents` returns to 0, and the account moves from `FUNDED` to `REVERSED`. The cascade closes the loop: the closing package moves to `CANCELLED` (from whichever of its post-approval states it occupies), the case moves from `IN_CLOSING` to `RESCINDED` with `purchase_price_cents` cleared while `accepted_offer_id` is kept for audit, and the portfolio reverses its funding-time entries — `invested_capital_cents` loses the purchase price that was added at funding, `holding_count` decrements, `nav_stale` becomes true, and the portfolio's `version` increments.

After release, a finance officer settles disbursement rows one at a time; settlement requires the account to be `RELEASED` (otherwise `ERR_INVALID_STATE_TRANSITION`), moves the row from `PENDING` to `SETTLED`, and leaves the account's `balance_cents` untouched since the debit already happened at release. When the last `PENDING` row settles, the escrow account closes automatically (`RELEASED` → `CLOSED`). An `OPEN` account reaches `CLOSED` only through manual package cancellation, as described in §3.4.

### 3.6. Portfolio Assignment and Holdings Accounting

A portfolio is created by a portfolio manager or platform admin with a `name`, a `valuation_method` of `PROSPECTIVE` or `INVESTMENT`, an `allocations` array, and an optional `discount_rate_bps` that defaults to 1200 (twelve percent annual). Each allocation entry pairs an `investor_id` — which must reference an existing `Investor` — with a positive integer `units`; `allocations` defaults to an empty array. The portfolio's computed holdings fields begin at zero: `holding_count`, `invested_capital_cents`; `cached_nav_cents` starts unset and `nav_stale` false.

Before escrow can be funded, a portfolio manager assigns the `IN_CLOSING` case to a portfolio via the case's `portfolio_id` — assignment outside `IN_CLOSING` is rejected with `ERR_INVALID_STATE_TRANSITION`, and the assignment increments both the case's and the portfolio's `version`. A portfolio's `holding_count` counts its cases that are either `IN_CLOSING` with a funded escrow or `ACQUIRED`. Its `invested_capital_cents` sums the `purchase_price_cents` of its funded-and-not-rescinded cases plus every `PAID` premium on those cases' schedules. A portfolio list read by an `Investor` caller shows only portfolios where that investor holds an allocation; a direct read of a portfolio or its snapshots by a non-allocated investor is rejected with `ERR_INVESTOR_NOT_ALLOCATED`.

### 3.7. Premium Optimization and Lapse

Once a case is `ACQUIRED`, the provider owes the policy's premiums, and a portfolio manager creates an optimized premium schedule — an action that requires the case to be `ACQUIRED` (otherwise `ERR_POLICY_NOT_ACQUIRED`, HTTP 409) and carries the OCC field `expected_case_version` per §2.6. Creating a schedule supersedes the case's currently `ACTIVE` schedule, which moves to `SUPERSEDED`; the superseded schedule's still-`SCHEDULED` payments remain on record but are no longer payable — attempting to pay one is rejected with `ERR_INVALID_STATE_TRANSITION`.

The optimizer evaluates three strategies and picks the one with the highest expected net value; ties break by the fixed priority PAY_AS_DUE first, then REDUCED_PAID_UP, then MINIMUM_FUNDING. All three share the same setup: the remaining expectancy k is the case's `blended_le_months` minus the whole 30-day months elapsed between the latest eligible life-expectancy report's `delivered_at` and the current clock (days divided by 30, floored), floored at 1; the monthly rate i is the portfolio's `discount_rate_bps` divided by ten thousand and then by twelve; v is the reciprocal of one plus i; and the annuity factor over k months is one minus v-to-the-k, divided by i. F denotes the policy's `face_amount_cents`, CV its `cash_value_cents`, and one twelfth of `annual_premium_cents` the unrounded monthly billed premium.

- **PAY_AS_DUE.** The monthly premium is the billed monthly premium rounded half-up. Expected net value is the face times v-to-the-k, minus the unrounded billed monthly premium times the annuity factor.
- **REDUCED_PAID_UP.** The present value of premiums is the unrounded billed monthly premium times the annuity factor. The reduced face is the face times CV divided by the sum of CV and that premium present value, rounded half-up — or 0 when that sum is not positive. Expected net value is the reduced face times v-to-the-k, and the monthly premium under this strategy is 0. The chosen `reduced_face_cents` is recorded on the schedule; under the other strategies it stays unset.
- **MINIMUM_FUNDING.** The monthly funding m is the smallest level amount that keeps the policy's cash value non-negative through month k, found by projecting the cash value month by month in order from month 1 through month k: each month's cost of insurance is the larger of zero and face minus the prior month's cash value, multiplied by a monthly rate of 0.006, rounded half-up; the month's ending cash value is the prior cash value grown at a monthly crediting rate of 0.0033333333333333335 and rounded half-up, plus m, minus the month's cost of insurance. The solving m is found by bisection over the interval from 0 to four times the billed monthly premium, using exactly 40 iterations, then rounded half-up. If the solved premium rounds to 0 — the cash value fully self-funds the coverage — MINIMUM_FUNDING is infeasible, because carriers require a positive modal premium, and it is excluded from the argmax. Its expected net value is the face times v-to-the-k minus the solved monthly premium times the annuity factor.

The created schedule records the case's `case_id`, the chosen `strategy`, the `optimized_monthly_premium_cents` for that strategy, `planned_months` equal to the remaining expectancy k, the `expected_net_value_cents` rounded half-up, and starts with `missed_payment_count` 0, `total_paid_cents` 0, and `status` `ACTIVE`. Creation also generates `PremiumPayment` rows — each carrying the schedule's `schedule_id` — one per planned month, capped at 360 rows, where rows of zero amount are never generated. Each row's `amount_cents` equals the schedule's `optimized_monthly_premium_cents`; the first `due_date` is the schedule's creation clock plus 30 days, and each subsequent row is 30 days after the previous; each row's `grace_deadline` is its `due_date` plus 31 days. The case's `version` increments on schedule creation.

A finance officer pays a `SCHEDULED` payment by supplying `amount_cents` equal to the payment's scheduled `amount_cents` — any other figure is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422) — and only while the parent schedule is still `ACTIVE` (otherwise `ERR_INVALID_STATE_TRANSITION`). A valid payment stamps `paid_at`, moves the row from `SCHEDULED` to `PAID` with a version increment, adds the amount to the schedule's `total_paid_cents`, and through the case's portfolio adds the amount to `invested_capital_cents`, sets `nav_stale` true, and increments the portfolio's `version`.

A payment left unpaid past its `grace_deadline` becomes `MISSED` automatically when the clock advances. Each miss increments the schedule's `missed_payment_count` by 1. When the count reaches 2, the lapse cascade fires: the schedule moves from `ACTIVE` to `TERMINATED`, the case moves from `ACQUIRED` to `LAPSED`, the policy's `status` becomes `LAPSED`, and the portfolio's `nav_stale` becomes true. A schedule also moves from `ACTIVE` to `TERMINATED` when its case matures.

### 3.8. Insured Tracking, Death Verification, and Claims

On an `ACQUIRED` case — and only there, otherwise `ERR_POLICY_NOT_ACQUIRED` — a case manager records tracking events on the insured. Each event carries an `event_type` of `WELLNESS_CALL`, `OBIT_SEARCH`, `DMF_MATCH`, `FAMILY_REPORT`, or `MEDICAL_RECORDS`; an `outcome` of `ALIVE_CONFIRMED`, `DEATH_INDICATED`, or `UNREACHABLE`; a `source_channel` of `CALL`, `OBIT`, `DMF`, `MEDICAL`, or `FAMILY`; and the ISO `event_date` of the observation. The record's `coverage_through` — the verification currency window — is the `event_date` plus 90 days, and its `status` begins at `RECORDED`. A compliance officer then verifies or rejects each event; verification moves it from `RECORDED` to `VERIFIED` and recomputes the `verification_source_count` on any `REPORTED` death claim of the case, while rejection moves it to `REJECTED`.

A death claim is opened on an `ACQUIRED` case by a compliance officer supplying the ISO `date_of_death`; opening requires at least one `VERIFIED` tracking event on the case with outcome `DEATH_INDICATED`, and is otherwise rejected with `ERR_VERIFICATION_SOURCES_INSUFFICIENT` (HTTP 422). The claim begins `REPORTED` with `verification_source_count` 0 and `certificate_received` false; its computed `in_contestability` is true exactly when the `date_of_death` falls earlier than twenty-four months after the case's `acquired_at` — the carrier's contest window on the ownership transfer.

Verifying a claim requires `certificate_received` to be true in the payload (otherwise `ERR_INVALID_REQUEST`) and at least two `VERIFIED` tracking events on the case with outcome `DEATH_INDICATED` whose `source_channel` values are pairwise distinct — the count of distinct channels among such events is exactly what `verification_source_count` tracks — with a shortfall rejected as `ERR_VERIFICATION_SOURCES_INSUFFICIENT`. Verification sets `certificate_received` true, recomputes `verification_source_count`, and moves the claim from `REPORTED` to `VERIFIED`. A case manager then files the verified claim with the carrier (`VERIFIED` → `FILED`).

Settlement by a compliance officer takes an `outcome`. Settling with `DENIED` moves a `FILED` or `CONTESTED` claim to `DENIED` with no further effects. Settling with `PAID` requires `gross_proceeds_cents` present and greater than zero (otherwise `ERR_INVALID_REQUEST`), and branches on contestability: when the claim's `in_contestability` is true and the payload's `contest_review_acknowledged` is not true, the claim moves from `FILED` to `CONTESTED` instead of paying — this is a branch, not an error; a contested claim pays out on a later settle that supplies `contest_review_acknowledged` true. When the payment path proceeds — from `FILED` outside the contest window, or from `CONTESTED` with acknowledgement — the claim's `net_proceeds_cents` is computed: the carrier's gross proceeds minus the policy's outstanding `policy_loan_cents` minus unpaid scheduled premiums, floored at zero. Unpaid scheduled premiums are the `amount_cents` of payments on the case's `ACTIVE` schedule in `SCHEDULED` or `MISSED` status whose `due_date` falls at or before the end of the `date_of_death` day in UTC.

A paid settlement fires the maturity cascade: the claim moves to `PAID`; the case moves from `ACQUIRED` to `MATURED` and stamps `matured_at`; the insured's `status` becomes `DECEASED`; the policy's `status` becomes `MATURED`; the case's `ACTIVE` premium schedule moves to `TERMINATED`; the portfolio's `nav_stale` becomes true and its `version` increments, with `invested_capital_cents` unchanged by the settlement itself; and every `DRAFT` valuation snapshot on the portfolio moves to `SUPERSEDED`.

### 3.9. Valuation and Investor Reporting

A portfolio manager values a portfolio by creating a valuation snapshot — a write carrying the OCC field `expected_portfolio_version` per §2.6 — with `period_start` and `period_end` as ISO dates delimiting a half-open window: `period_start` inclusive, `period_end` exclusive, and the exclusive end date is the as-of date for every valuation input. The end must be strictly later than the start, otherwise `ERR_INVALID_PERIOD` (HTTP 422). The new snapshot's window must not overlap any existing `FINALIZED` snapshot on the same portfolio — adjacency, where the new start equals another snapshot's end, is allowed; overlap is rejected with `ERR_SNAPSHOT_PERIOD_OVERLAP` (HTTP 409). Every `ACQUIRED` case in the portfolio must have at least one `DELIVERED` unexpired life-expectancy report at creation, otherwise `ERR_VALUATION_INPUT_STALE` (HTTP 422). Creation captures the portfolio's `valuation_method` into the snapshot's `method_used`, supersedes any existing `DRAFT` snapshot on the portfolio, increments the portfolio's `version`, and begins the snapshot in `DRAFT`.

The snapshot values each case assigned to the portfolio whose status is `ACQUIRED`, `MATURED`, or `LAPSED`, producing one `policy_valuations` row per case carrying `case_id`, `remaining_le_months`, and `value_cents`. For every case, `months_elapsed` is the whole 30-day months between the latest eligible report's `delivered_at` and the valuation date, and `remaining_le_months` is the case's `blended_le_months` minus that figure, floored at 1. The monthly premium input is the `optimized_monthly_premium_cents` of the case's `ACTIVE` schedule when one exists, otherwise one twelfth of the policy's `annual_premium_cents` unrounded. The value then depends on status and method. A `MATURED` case is valued at its claim's `net_proceeds_cents`; a `LAPSED` case is valued at 0. An `ACQUIRED` case under the `PROSPECTIVE` method — fair value — is the face times v-to-the-k minus the monthly premium times the annuity factor over the remaining k months, rounded half-up, where the rate comes from the portfolio's `discount_rate_bps`; this variant discounts the future death benefit net of future premiums. An `ACQUIRED` case under the `INVESTMENT` method — cost accretion — takes the case's `purchase_price_cents` plus the total `PAID` premium cents on its schedules, accretes that cost forward at the portfolio's annual discount rate compounded over the years held (the days between `acquired_at` and the valuation date divided by 365), rounds half-up, and caps the result at the face amount; this variant ignores life expectancy except through case status. All values are floored at 0. The snapshot's `nav_cents` is the sum of its rows' `value_cents`.

The snapshot also computes two return metrics over the half-open window from the portfolio's cash flows. Portfolio cash flows are the funding outflow — the case's `purchase_price_cents` negative, dated at the escrow's `funded_at` — and each premium payment's `amount_cents` negative, dated at its `paid_at`; death-claim proceeds are deliberately not cash flows here, because a matured case already enters the terminal NAV at `net_proceeds_cents`, and the fee overage funded beyond price is not a portfolio flow either. V0 is the invested capital strictly before `period_start` — funded purchase prices and paid premiums timestamped earlier than the start — and V1 is the snapshot's `nav_cents` at the period end; the window carries an initial flow of negative V0 at `period_start` when V0 is positive, and a terminal flow of positive V1 at `period_end`.

The money-weighted return, `money_weighted_return_bps`, is the internal rate that makes the discounted sum of all flows zero, where each flow is discounted at one-plus-r raised to the number of days from `period_start` to the flow's date, divided by 365. The rate is solved by bisection over the interval from negative 0.9999 to 10.0 using exactly 64 iterations, then multiplied by ten thousand and rounded half-up to integer basis points. The time-weighted return, `time_weighted_return_bps`, follows the Modified Dietz method: with D the days between `period_start` and `period_end`, and F the sum of external flows excluding the initial and terminal flows, the return is V1 minus V0 minus F, divided by V0 plus the day-weighted sum of external flows — each flow weighted by D minus its day offset, over D. When that denominator is zero the return is defined as 0; the result is multiplied by ten thousand and rounded half-up to integer basis points. The two metrics are algebraically different views of the same flows: the money-weighted figure is sensitive to cash-flow timing, while the Dietz figure weights each flow only by its day position.

Finalizing a `DRAFT` snapshot — a portfolio-manager action — re-checks the overlap rule against other `FINALIZED` snapshots on the portfolio (`ERR_SNAPSHOT_PERIOD_OVERLAP`), supersedes any prior `FINALIZED` snapshot on the same portfolio, writes the snapshot's `nav_cents` into the portfolio's `cached_nav_cents`, clears the portfolio's `nav_stale` to false, and increments the portfolio's `version`. A `FINALIZED` snapshot becomes `SUPERSEDED` only when a newer snapshot on the same portfolio is finalized; a `DRAFT` becomes `SUPERSEDED` when a newer draft is created on the portfolio or when the portfolio is dirtied by a death-claim settlement.

Reading a snapshot's detail derives per-investor shares of the finalized NAV. With `total_units` the sum of `units` across the portfolio's `allocations`, each allocation's share is the NAV multiplied by its `units` and divided by `total_units`, rounded half-up, processed in stored array order. The rounding drift — the NAV minus the sum of the rounded shares, a small integer possibly negative — is added to the share of the allocation holding the largest `units`; on a tie in units, the drift goes to the allocation whose investor's `created_at` is earliest.

## 4. Endpoint Definitions

New resources return 201 on creation; modifications and state transitions return 200. The clock endpoint returns 200 with the new `current_utc`. All endpoints are mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Set the logical clock; evaluates all automatic transitions | PlatformAdmin |
| POST | /api/brokers | Register a broker | PlatformAdmin |
| GET | /api/brokers/{id} | Get a broker | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/brokers/{id}/cases | List cases owned by a broker | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/brokers/{id}/insureds | List insureds created by a broker | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/brokers/{id}/disbursements | List commission disbursements payable to a broker | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/investors | Register an investor | PlatformAdmin |
| GET | /api/investors/{id} | Get an investor | PlatformAdmin, PortfolioManager, ComplianceOfficer, FinanceOfficer, Investor |
| POST | /api/insureds | Create an insured individual | Broker, CaseManager |
| GET | /api/insureds/{id} | Get an insured, including computed `age_years` at the current clock | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/insureds/{id}/policies | List policies of an insured | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/policies | Create a life insurance policy for an insured | Broker, CaseManager |
| GET | /api/policies/{id} | Get a policy, including computed `in_contestability` at the current clock | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| PATCH | /api/policies/{id} | Amend policy financial fields; blocked while an active case locks it | Broker, CaseManager |
| GET | /api/policies/{id}/cases | List cases for a policy | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/licenses | Create a state license window; closed-interval overlap rejected | PlatformAdmin, ComplianceOfficer |
| GET | /api/licenses | List licenses, optional `state_code` filter | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/licenses/{id} | Get a license | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/licenses/{id}/suspend | Suspend a license; cascades `COMPLIANCE_HOLD` to in-flight cases | ComplianceOfficer |
| POST | /api/licenses/{id}/reinstate | Reinstate a suspended license; clears cascading holds | ComplianceOfficer |
| POST | /api/cases | Create a `DRAFT` policy case; `broker_id` set from caller | Broker |
| GET | /api/cases | List cases with filters (`status`, `broker_id`, `portfolio_id`, `accepted_offer_id`) and pagination | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/cases/{id} | Get a case | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/cases/{id}/submit | Move `DRAFT` → `SCREENING` | Broker |
| POST | /api/cases/{id}/withdraw | Withdraw a case from any pre-closing status | Broker |
| POST | /api/cases/{id}/screenings | Run eligibility screening while `SCREENING` or `SCREEN_FAILED` | CaseManager |
| GET | /api/cases/{id}/screenings | List screening records for a case | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/cases/{id}/le-reports | Order a life-expectancy report (`ORDERED`) | Underwriter |
| GET | /api/cases/{id}/le-reports | List LE reports for a case | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/le-reports/{id}/deliver | Deliver an LE report with underwriting inputs | Underwriter |
| GET | /api/le-reports/{id} | Get an LE report | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/cases/{id}/uw-decision | Underwriting decision; approve computes blended LE and reserve price, moves to `MARKETED` | Underwriter |
| POST | /api/cases/{id}/reunderwrite | Move `MARKETED` → `UNDERWRITING` | Underwriter |
| POST | /api/cases/{id}/deliver-disclosures | Record delivery of the disclosure packet to the seller | CaseManager |
| POST | /api/cases/{id}/offers | Create a provider offer on a `MARKETED` case | Underwriter |
| GET | /api/cases/{id}/offers | List offers on a case, optional `status` filter | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/offers/{id} | Get an offer | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/offers/{id}/counter | Broker counters a `PENDING` offer (OCC on offer version) | Broker |
| POST | /api/offers/{id}/respond | Underwriter responds to a `COUNTERED` offer: `RE_OFFER`, `ACCEPT_COUNTER`, or `REJECT` | Underwriter |
| POST | /api/offers/{id}/accept | Broker accepts a `PENDING` offer | Broker |
| POST | /api/offers/{id}/reject | Broker rejects an offer | Broker |
| POST | /api/offers/{id}/withdraw | Underwriter withdraws an offer | Underwriter |
| GET | /api/cases/{id}/closing-package | Get the closing package for a case | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/closing-packages | List closing packages, optional `offer_id` filter | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/closing-packages/{id} | Get a closing package | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/closing-packages/{id}/send-for-signature | Move `ASSEMBLED` → `OUT_FOR_SIGNATURE` | CaseManager |
| POST | /api/closing-packages/{id}/record-signature | Mark one checklist document signed | CaseManager |
| POST | /api/closing-packages/{id}/submit-review | Move `OUT_FOR_SIGNATURE` → `COMPLIANCE_REVIEW` | CaseManager |
| POST | /api/closing-packages/{id}/return-deficiency | Return package to signature, resetting named documents | ComplianceOfficer |
| POST | /api/closing-packages/{id}/approve | Compliance approval of the closing package | ComplianceOfficer |
| POST | /api/closing-packages/{id}/submit-carrier | Move `APPROVED` → `CARRIER_SUBMITTED`; requires escrow `FUNDED` | CaseManager |
| POST | /api/closing-packages/{id}/confirm-ownership | Move `CARRIER_SUBMITTED` → `OWNERSHIP_CONFIRMED` | CaseManager |
| POST | /api/closing-packages/{id}/cancel | Cancel a closing package pre-funding; case returns to `MARKETED` | CaseManager |
| GET | /api/cases/{id}/escrow-account | Get the escrow account for a case | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/escrow-accounts/{id} | Get an escrow account | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/escrow-accounts/{id}/fund | Fund escrow at the exact expected amount | FinanceOfficer |
| POST | /api/escrow-accounts/{id}/release | Release escrow after the rescission window; runs the disbursement waterfall | FinanceOfficer |
| POST | /api/escrow-accounts/{id}/rescind | Seller rescission inside the window; full refund, case `RESCINDED` | ComplianceOfficer |
| GET | /api/escrow-accounts/{id}/disbursements | List disbursements in waterfall bucket order | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/disbursements/{id}/mark-paid | Settle a disbursement | FinanceOfficer |
| POST | /api/portfolios | Create a portfolio with investor allocations | PortfolioManager, PlatformAdmin |
| GET | /api/portfolios | List portfolios; investors see only portfolios where they hold an allocation | PlatformAdmin, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager, Investor |
| GET | /api/portfolios/{id} | Get a portfolio (investor must hold an allocation) | PlatformAdmin, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager, Investor |
| GET | /api/portfolios/{id}/cases | List cases assigned to a portfolio | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/cases/{id}/assign-portfolio | Assign an `IN_CLOSING` case to a portfolio | PortfolioManager |
| POST | /api/cases/{id}/premium-schedules | Create an optimized premium schedule on an `ACQUIRED` case (OCC on case version) | PortfolioManager |
| GET | /api/cases/{id}/premium-schedules | List premium schedules for a case | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/premium-schedules/{id} | Get a premium schedule | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/premium-schedules/{id}/payments | List payments of a schedule, ordered by `due_date` ascending, optional `status` filter | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/premium-payments/{id} | Get a premium payment | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/premium-payments/{id}/pay | Pay a scheduled premium at the exact scheduled amount | FinanceOfficer |
| POST | /api/cases/{id}/tracking-events | Record an insured tracking event on an `ACQUIRED` case | CaseManager |
| GET | /api/cases/{id}/tracking-events | List tracking events for a case | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/tracking-events/{id}/verify | Verify a tracking event | ComplianceOfficer |
| POST | /api/tracking-events/{id}/reject | Reject a tracking event | ComplianceOfficer |
| POST | /api/cases/{id}/death-claims | Open a death claim on an `ACQUIRED` case | ComplianceOfficer |
| GET | /api/death-claims/{id} | Get a death claim | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| GET | /api/cases/{id}/death-claims | List death claims for a case | PlatformAdmin, Broker, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager |
| POST | /api/death-claims/{id}/verify | Verify a death claim (two independent verified sources plus certificate) | ComplianceOfficer |
| POST | /api/death-claims/{id}/file | File a verified claim with the carrier | CaseManager |
| POST | /api/death-claims/{id}/settle | Settle a filed or contested claim; `PAID` triggers the maturity cascade | ComplianceOfficer |
| POST | /api/portfolios/{id}/valuation-snapshots | Create a `DRAFT` valuation snapshot (OCC on portfolio version) | PortfolioManager |
| GET | /api/portfolios/{id}/valuation-snapshots | List snapshots of a portfolio, optional `status` filter | PlatformAdmin, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager, Investor |
| GET | /api/valuation-snapshots/{id} | Get a snapshot including `policy_valuations` and per-investor shares | PlatformAdmin, Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer, PortfolioManager, Investor |
| POST | /api/valuation-snapshots/{id}/finalize | Finalize a `DRAFT` snapshot; supersedes the prior `FINALIZED` snapshot | PortfolioManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_CASE_OWNER | 403 |
| ERR_INVESTOR_NOT_ALLOCATED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_CASE_NOT_MARKETED | 409 |
| ERR_CASE_HAS_ACTIVE_CLOSING | 409 |
| ERR_DUPLICATE_ACTIVE_CASE | 409 |
| ERR_POLICY_LOCKED_BY_ACTIVE_CASE | 409 |
| ERR_DISCLOSURES_INCOMPLETE | 422 |
| ERR_CASE_ON_COMPLIANCE_HOLD | 409 |
| ERR_STATE_LICENSE_NOT_ACTIVE | 409 |
| ERR_LICENSE_EXPIRING_SOON | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_RESCISSION_WINDOW_ACTIVE | 409 |
| ERR_RESCISSION_WINDOW_EXPIRED | 409 |
| ERR_LE_REPORT_REQUIRED | 422 |
| ERR_LE_REPORT_EXPIRED | 409 |
| ERR_MAX_NEGOTIATION_ROUNDS_REACHED | 409 |
| ERR_COUNTER_INCREMENT_TOO_SMALL | 422 |
| ERR_CLOSING_DOCS_INCOMPLETE | 422 |
| ERR_ESCROW_NOT_FUNDED | 409 |
| ERR_PORTFOLIO_NOT_ASSIGNED | 422 |
| ERR_ESCROW_FUNDS_MISMATCH | 422 |
| ERR_COMMISSION_CAP_EXCEEDED | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_POLICY_NOT_ACQUIRED | 409 |
| ERR_VERIFICATION_SOURCES_INSUFFICIENT | 422 |
| ERR_INVALID_PERIOD | 422 |
| ERR_SNAPSHOT_PERIOD_OVERLAP | 409 |
| ERR_LICENSE_WINDOW_OVERLAP | 409 |
| ERR_VALUATION_INPUT_STALE | 422 |
| ERR_STALE_VERSION | 412 |
