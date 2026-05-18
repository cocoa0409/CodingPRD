# HELOC Servicing API — Product Requirements Document

## 1. Introduction

A Home Equity Line of Credit (HELOC) is a revolving credit instrument secured by a borrower's primary residence in a second-lien position behind an existing senior mortgage. Unlike a single-disbursement home-equity loan, a HELOC carries the operational complexity of a long-lived obligation: an extended draw window during which the borrower may pull funds against an interest-only minimum, followed by a multi-year amortizing repayment window, and a variable interest rate that is repriced from time to time against a published Prime Rate plus a fixed margin.

This document specifies the HELOC Servicing API, which governs the full lifecycle of these accounts from origination through draws, payments, rate resets, fee assessment, default cascades, and final closure. The API exists to enforce — uniformly and auditably — three categories of obligation that human servicing teams routinely mishandle when left to ad-hoc spreadsheets: lien-position and collateral checks at origination, periodic and lifetime rate-cap mechanics on every reset, and the multiple cascading default triggers (delinquency, lapsed property insurance, defaulted senior lien, borrower bankruptcy) that can render an account non-performing without any direct action by the borrower. A deliberate segregation of duties between an originating role and a servicing role mirrors the operational risk controls expected of a regulated lender.

Because the system models real-world calendar time (10-year draw period, 365-day fee anniversaries, 1095-day early-closure window, 90-day delinquency horizon), the API also exposes a small set of administrative testing endpoints that advance a logical server clock and run periodic sweeps, so that downstream automated test harnesses can reach every state without waiting wall-clock years.

## 2. Global Specifications & System-Wide Principles

This section establishes the contracts that apply uniformly to every endpoint: authentication, response envelope, pagination, common resource attributes, precision, concurrency, and the cross-cutting safety and consistency principles that govern HELOC lifecycle management.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying their operational capacity. If either header is missing or empty, the request is rejected with `ERR_MISSING_AUTH`. If `X-User-Role` is supplied but is not one of the four recognized values, the request is rejected with `ERR_UNKNOWN_ROLE`. The four recognized roles are `Originator`, `Servicer`, `Borrower`, and `PlatformAdmin`.

When the acting role is `Borrower`, the value of `X-User-ID` is the `id` of the acting `Borrower`; any borrower-scoped read (such as fetching a borrower, property, senior lien, HELOC, or any of its child collections) compares the resource's owning borrower chain to `X-User-ID` and rejects mismatches with `ERR_FORBIDDEN`. When the acting role is `Originator`, `Servicer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record or log it, but does not compare it to any entity's `id`.

The system additionally enforces a strict segregation of duties. The `Originator` role is responsible only for onboarding (registering borrowers, properties, and senior liens, creating `PENDING` HELOCs, and activating them) and is forbidden from performing in-life servicing such as posting rate resets, closing accounts, or recording insurance, bankruptcy, or senior-lien default events. The `Servicer` role handles in-life servicing but may not originate new HELOCs. The `Borrower` role acts only on its own resources, and may take draws, make payments, and close its own HELOC. The `PlatformAdmin` role is a superuser that may invoke any endpoint, including the administrative clock-advance and sweep capabilities used by automated test harnesses. Any attempt by a non-authorized role to invoke an endpoint outside its grant is rejected with `ERR_FORBIDDEN`, and any attempt by an `Originator` to invoke an operation reserved to the `Servicer` (or any equivalent crossing of the originate/service boundary) yields the more specific `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints accept two query parameters that control the returned page. The `limit` parameter caps the number of items in the response; if omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless an endpoint specifies otherwise, list results are ordered by the resource's creation timestamp in ascending order. Paginated responses include the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

The primary top-level resources — `Borrower`, `Property`, `SeniorLien`, and `Heloc` — carry a standard set of system-managed fields. The `id` is a server-minted UUID (no type prefix) that uniquely identifies the resource. The `created_at` timestamp is an ISO 8601 UTC string with three fractional digits, captured at the moment the resource is persisted. The `updated_at` timestamp follows the same format and is refreshed on every mutation to the resource, including any derived-field mutation driven by another action (for example, a rate reset bumps the affected HELOC's `updated_at`). The `version` field is an integer that begins at 1 on creation and increments by exactly one with every mutation to the resource.

The ledger-style child resources of a HELOC — `Draw`, `Payment`, `RateReset`, `Fee`, `DefaultEvent` — and the audit-log entities `InsuranceEvent`, `SeniorLienDefaultEvent`, and `BankruptcyEvent` are written-once and immutable after creation. Each of these still carries an `id` (server-minted UUID) and a `created_at` timestamp, but they do not carry `updated_at` or `version` — both fields are absent from their responses because no in-place mutation is ever performed on them.

### 2.5. Optimistic Concurrency Control

Operations that modify a HELOC may include the current `version` of the HELOC in the request body to opt into optimistic concurrency control. When `version` is supplied, the server compares it to the HELOC's persisted `version`; if the two are not equal the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted from the request body, no concurrency check is performed and the mutation proceeds against whatever the current state happens to be. This optional field is accepted on activation, draws, payments, rate resets, and close.

### 2.6. Monetary Values, Rates, and Precision

All monetary amounts in the system — credit limits, draws, payments, accrued interest, principal balances, fees, and any derived sums — are represented as integer cents. No floating-point money values cross the API boundary; every amount field uses the `_cents` suffix and is a whole number. Interest rates and rate caps are likewise represented as integer basis points (one basis point equals one hundredth of one percent), using the `_bps` suffix. Because both money and rates are integer-valued at the API surface, arithmetic that combines them is performed in decimal and any cent-valued result is rounded half-up to the nearest whole cent before being persisted. Rate-clamping arithmetic in the rate-reset calculation involves only integer basis points and therefore requires no rounding.

### 2.7. Nested Resource Retrieval

When an endpoint URL contains a chain of resource identifiers — for instance, a path that targets a senior lien beneath a property, or a draw beneath a HELOC — the server validates each identifier in left-to-right order. The first identifier in the path that does not match an existing resource immediately yields `ERR_RESOURCE_NOT_FOUND`, and validation does not continue past that point. The same `ERR_RESOURCE_NOT_FOUND` is also returned when a foreign-key identifier supplied in a request body (such as a `borrower_id`, `property_id`, or `heloc_id`) does not refer to an existing resource; this body-level existence check applies on HELOC creation, property and senior-lien registration, and all child-collection writes (draws, payments, rate resets).

### 2.8. Hierarchical Consistency and Cascades

The system maintains immediate consistency between parent and child resources. When a parent-level event renders a HELOC non-performing — a recorded bankruptcy on the borrower, a declared default on the senior lien, or a recorded insurance lapse on the property — every HELOC reachable from that parent that is currently in `DRAW` or `REPAY` is transitioned to `DEFAULT` in the same logical operation, the HELOC's `defaulted_at` is set to the server clock at the time of the cascade, and a `DefaultEvent` is written with the corresponding `trigger` and `source_event_id`. Any cascade that drives a HELOC to `DEFAULT` is itself a mutation on that HELOC and therefore refreshes its `updated_at` and increments its `version`. Each such cascaded default further suppresses any future `ANNUAL` fee that would otherwise have been assessed on that HELOC — the cascade is a two-hop side effect: first the HELOC moves to `DEFAULT`, and then annual-fee accrual on that HELOC is silenced.

When a default cascade originates from a senior lien default, the senior lien itself transitions from `CURRENT` to `DEFAULTED` and its `defaulted_at` is set. When the cascade originates from an insurance lapse, the property's `insurance_status` flips from `ACTIVE` to `LAPSED` and the property's `insurance_lapsed_at` is set. If the same property's insurance is subsequently reinstated, the `insurance_status` returns to `ACTIVE` and `insurance_lapsed_at` is cleared to null, but any HELOC that was already cascaded to `DEFAULT` because of the lapse is *not* automatically reactivated: once a HELOC enters `DEFAULT`, that state is sticky regardless of the underlying trigger being subsequently cured.

### 2.9. The Default-Trigger Priority

A HELOC may be exposed to more than one default trigger at the same logical moment — a borrower might file bankruptcy on the same day a sweep finds the account 90 days delinquent. When the system records the cause of a transition into `DEFAULT`, it uses a fixed priority ordering on the `default_trigger` enumeration: `BANKRUPTCY` is recorded ahead of `SENIOR_LIEN_DEFAULT`, which is recorded ahead of `INSURANCE_LAPSE`, which is recorded ahead of `DELINQUENCY_90`. The value stored on the HELOC's `default_trigger` and on the corresponding `DefaultEvent.trigger` is always the highest-priority condition that is true at the moment the transition is committed.

### 2.10. Validation Ordering Across an Endpoint

When an endpoint is subject to multiple validation rules, the server evaluates them in a fixed order so that the returned `error_id` reflects the most fundamental violation. Authentication checks come first: missing or empty headers (`ERR_MISSING_AUTH`) are caught before unknown-role checks (`ERR_UNKNOWN_ROLE`), which are caught before role-authorization checks (`ERR_FORBIDDEN`), which are themselves caught before the segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`). After authentication, the server resolves the URL path left-to-right and then verifies any body-supplied foreign keys (both yielding `ERR_RESOURCE_NOT_FOUND` on the first missing reference). Only after existence is established does the server evaluate state preconditions, then business-safety rules (occupancy, lien position, bankruptcy gate, CLTV), then business-temporal rules (the payment-minimum check), then referential rules (the borrower-property match), and finally fiscal/capacity rules (available-credit checks, balance-zero checks at close, rate-bound configuration checks, and the optimistic-concurrency `version` check). Within the state group, more specific state errors take precedence over generic ones — for example, an attempt to take a draw against a `DEFAULT` HELOC returns `ERR_HELOC_DEFAULTED` rather than the generic `ERR_INVALID_STATE`, an attempt to take a draw against a HELOC already in `REPAY` returns `ERR_DRAW_PERIOD_ENDED`, and any mutation attempted against a `CLOSED` HELOC returns `ERR_HELOC_CLOSED`.

### 2.11. The Logical Server Clock and Sweep Endpoints

Because HELOC mechanics are time-driven, the system maintains a single logical server clock that is the source of all `*_at` timestamps and is also the basis for the time comparisons in the periodic sweeps. A `PlatformAdmin`-only test capability advances this logical clock by a supplied number of `seconds` and returns the new `current_time` as an ISO 8601 string; advancing the clock by itself does not trigger any sweep or any state transition — it only makes future server-clock reads return later values.

Two further `PlatformAdmin`-only sweep capabilities perform the actual time-driven work. The billing-cycle sweep is idempotent per `(heloc_id, cycle_index)` pair and, on each invocation, advances every HELOC currently in `DRAW` or `REPAY` by one 30-day cycle. The annual-fee sweep is idempotent per `(heloc_id, anniversary_index)` and assesses any due `ANNUAL` fee that has not yet been recorded for that HELOC's anniversary index. Both sweeps return a small JSON summary (the billing-cycle sweep returns the number of cycles processed and the number of default transitions it triggered; the annual-fee sweep returns the number of fees created).

### 2.12. Field-Shape Validation

Generic body-shape validation — a required field is missing, a string is supplied where an integer was expected, a cents-valued amount is supplied as a negative number, an enum-typed field is supplied with a value outside its declared set, or `event_type` is not one of `LAPSE`/`REINSTATE` — is rejected with `ERR_VALIDATION_FAILED` and an HTTP 400 status. Domain-specific bound checks (such as the rate-configuration check that drives `ERR_RATE_BOUND_INVALID`) are handled separately as described in §3.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Borrowers, Properties, and Senior Liens

The onboarding flow begins with the `Originator` (or a `PlatformAdmin` acting in the same capacity) registering a `Borrower`. The borrower record carries a `full_name` between 1 and 200 characters and an `email` shaped as an RFC-5322 address that is unique across all borrowers. Two system-managed flags travel with the borrower: a `bankruptcy_flag` that begins as `false` and a `bankruptcy_filed_at` timestamp that begins as `null`. These two values are never edited directly through the borrower endpoint — they change only as a side effect of recording a bankruptcy filing (see §3.6).

Once a borrower exists, the `Originator` registers a `Property` owned by that borrower. The property request carries the owning `borrower_id`, an `address` between 1 and 300 characters, an `appraised_value_cents` of at least `100000` (one thousand dollars in cents), and an optional `occupancy` of `PRIMARY`, `SECONDARY`, or `INVESTMENT` (defaulting to `PRIMARY` when omitted). Two computed fields, `insurance_status` and `insurance_lapsed_at`, are initialized at creation to `ACTIVE` and `null` respectively; both change only as a side effect of insurance events (see §3.6).

Because a HELOC is a second-lien instrument, the property must also have an existing senior mortgage on record before any HELOC may be opened against it. The `Originator` registers a `SeniorLien` by supplying the `property_id` it secures, the senior lienholder's `holder_name` (1 to 200 characters, informational), and the senior lien's outstanding `principal_balance_cents` (a non-negative integer). The senior lien begins with `status` set to `CURRENT` and `defaulted_at` of `null`.

### 3.2. HELOC Origination and Activation

With borrower, property, and senior lien in place, the `Originator` opens a HELOC by submitting the owning `borrower_id`, the collateral `property_id`, and a configuration of monetary and rate parameters: a `credit_limit_cents` between `1000000` and `50000000` (ten thousand to five hundred thousand dollars), a `margin_bps` between 0 and 1000 inclusive that will be added to the Prime Rate on every reset, a `periodic_cap_bps` greater than 0 and at most 500 that bounds how much the fully-indexed rate may move between consecutive resets, a `lifetime_cap_bps` that must be strictly greater than `initial_rate_bps + periodic_cap_bps` and at most 2500, a `lifetime_floor_bps` that is non-negative and strictly less than `initial_rate_bps`, a `repayment_term_years` between 10 and 20 inclusive, an `annual_fee_cents` between 0 and 25000 inclusive, an optional `annual_fee_waived_first_year` boolean (defaulting to `false`), and an `early_closure_fee_cents` between 0 and 50000 inclusive. If any of these configured rate or cap bounds violate the ordering constraints — for example, `lifetime_cap_bps` is not strictly greater than `initial_rate_bps + periodic_cap_bps`, or `lifetime_floor_bps` is not strictly less than `initial_rate_bps` — the request is rejected with `ERR_RATE_BOUND_INVALID`.

Origination enforces a suite of safety gates evaluated in the order described in §2.10. The property's `occupancy` must equal `PRIMARY` or the request is rejected with `ERR_OCCUPANCY_NOT_PRIMARY`. There must be at least one existing `SeniorLien` on the same property whose `status` equals `CURRENT`, or the request is rejected with `ERR_NO_SENIOR_LIEN` (this enforces the second-lien position). The owning borrower's `bankruptcy_flag` must equal `false` or the request is rejected with `ERR_BORROWER_BANKRUPT`. The combined loan-to-value at origination must not exceed 100 percent: the property's `appraised_value_cents` must be strictly greater than the senior lien's `principal_balance_cents` plus the requested `credit_limit_cents`, or the request is rejected with `ERR_CLTV_EXCEEDED`. Finally, the property's `borrower_id` must match the HELOC's `borrower_id` so that the borrower owns the collateral they are pledging; a mismatch yields `ERR_BORROWER_PROPERTY_MISMATCH`. A successfully created HELOC lands in the `PENDING` status with zero `principal_balance_cents`, zero `accrued_interest_cents`, and zero `delinquency_days`.

Activation, the only transition out of `PENDING`, is performed by the `Originator` and requires a supplied `prime_rate_bps` (and, optionally, the current `version` for the concurrency check). Activation requires the HELOC to be in `PENDING` — any other state yields `ERR_INVALID_STATE` — and re-evaluates the CLTV gate so that an in-flight change to the senior lien's balance cannot slip past the origination check; failure here likewise yields `ERR_CLTV_EXCEEDED`. The activation sets `origination_date` to the current server clock, computes `draw_period_end_date` as exactly 3650 days (ten years) after `origination_date`, computes `repayment_period_end_date` as `draw_period_end_date` plus `repayment_term_years` multiplied by 365 days, computes `initial_rate_bps` as the sum of the supplied `prime_rate_bps` and the HELOC's `margin_bps` clamped to the closed interval bounded below by `lifetime_floor_bps` and above by `lifetime_cap_bps`, sets `current_rate_bps` equal to `initial_rate_bps`, sets `available_credit_cents` equal to `credit_limit_cents`, and transitions the HELOC's `status` from `PENDING` to `DRAW`. If two activations of the same `PENDING` HELOC are submitted simultaneously, the first to commit wins; the loser observes that the HELOC is no longer in `PENDING` and is rejected with `ERR_INVALID_STATE`.

### 3.3. Drawing Against the Line During the Draw Period

While the HELOC is in `DRAW`, the `Borrower` (or a `PlatformAdmin` acting on their behalf) may take a draw by supplying an `amount_cents` of at least `10000` (one hundred dollars) along with an optional `version`. The HELOC's `status` must be `DRAW`: an attempt against a `DEFAULT` HELOC is rejected with the specific `ERR_HELOC_DEFAULTED`; an attempt against a HELOC already rolled into `REPAY` is rejected with `ERR_DRAW_PERIOD_ENDED`; an attempt against a `CLOSED` HELOC is rejected with `ERR_HELOC_CLOSED`. The requested `amount_cents` must additionally be no greater than the HELOC's current `available_credit_cents` at request time, or the request is rejected with `ERR_INSUFFICIENT_AVAILABLE_CREDIT`. A successfully recorded draw is an immutable ledger entry containing the originating `heloc_id`, the `amount_cents`, and a server-clock `drawn_at` timestamp; it adds `amount_cents` to the HELOC's `principal_balance_cents` and subtracts `amount_cents` from its `available_credit_cents`, bumping the HELOC's `version` and refreshing `updated_at`.

The available-credit deduction is atomic. When two draws on the same `DRAW` HELOC arrive simultaneously, where each draw alone would fit within `available_credit_cents` but together they would exceed it, exactly one draw succeeds; the second is rejected with `ERR_INSUFFICIENT_AVAILABLE_CREDIT`.

### 3.4. Posting Payments

A `Borrower`, a `Servicer`, or a `PlatformAdmin` may post a `Payment` by supplying an `amount_cents` along with an optional `version`. Payments are accepted while the HELOC is in `DRAW`, `REPAY`, or `DEFAULT`; they are not accepted on a `CLOSED` HELOC, which yields `ERR_HELOC_CLOSED`. The supplied `amount_cents` must be at least the HELOC's `minimum_payment_due_cents` computed at request time, or the request is rejected with `ERR_PAYMENT_BELOW_MINIMUM`.

When a payment is accepted, the system applies a waterfall allocation that settles accrued interest before principal. The `interest_component_cents` is the smaller of the payment's `amount_cents` and the HELOC's `accrued_interest_cents` immediately before the payment; the `principal_component_cents` is the payment's `amount_cents` minus the `interest_component_cents`. The HELOC's `accrued_interest_cents` is reduced by the interest component, and its `principal_balance_cents` is reduced by the principal component but never permitted to drop below zero: if the principal component would otherwise drive the balance negative, the balance is clamped to zero. Both components, along with the originating `heloc_id` and a server-clock `posted_at`, are stored as an immutable `Payment` ledger entry. The payment is a mutation on the HELOC and so refreshes the HELOC's `updated_at` and bumps its `version`. All amounts are integer cents and the waterfall is performed on integer inputs, so no rounding is required.

The minimum-payment computation behind the `minimum_payment_due_cents` field, surfaced on the HELOC's read response and used as the payment floor, depends on the HELOC's current `status`. When the HELOC is in `DRAW`, the minimum is exactly the `accrued_interest_cents` carried since the last billing-cycle reset — the draw period requires nothing more than interest service. When the HELOC is in `REPAY`, the minimum is the standard amortizing monthly payment-and-interest combined with the carried `accrued_interest_cents`: the system computes a `months_remaining` value by taking the number of days between the current clock time and the `repayment_period_end_date`, dividing by the canonical 30-day month and rounding up to the next whole month; if that value is zero or negative, the minimum collapses to the full outstanding `principal_balance_cents` plus `accrued_interest_cents`; otherwise the system derives a monthly decimal rate by taking `current_rate_bps`, dividing by 10000 to convert basis points to a decimal annual rate, and dividing by 12 to convert to a monthly rate. When that monthly rate is exactly zero, the principal-and-interest component is simply `principal_balance_cents` divided by `months_remaining`; when the monthly rate is non-zero, the principal-and-interest component is `principal_balance_cents` multiplied by the monthly rate, divided by the quantity one minus the monthly factor (one plus the monthly rate) raised to the negative power of `months_remaining` — the standard mortgage amortization formula. The result is added to the carried `accrued_interest_cents` and rounded half-up to whole cents. When the HELOC is in `DEFAULT`, the minimum is the full payoff demand: `principal_balance_cents` plus `accrued_interest_cents`. When the HELOC is in `PENDING` or `CLOSED`, the minimum is zero.

### 3.5. Rate Resets and the Cap Mechanism

A `Servicer` records a rate reset by supplying a quoted `prime_rate_bps` between 0 and 3000 inclusive, along with an optional `version`. Rate resets are accepted while the HELOC's `status` is in `DRAW`, `REPAY`, or `DEFAULT`; attempts while the HELOC is in `PENDING` or `CLOSED` are rejected with `ERR_INVALID_STATE` (an attempt while `CLOSED` returns the more specific `ERR_HELOC_CLOSED`).

The reset computation produces three values that are persisted on the new `RateReset` ledger entry alongside the originating `heloc_id` and a server-clock `reset_at`. The `requested_rate_bps` is the supplied `prime_rate_bps` plus the HELOC's `margin_bps`, with no clamping. The `applied_rate_bps` is the same value after two successive clamps. The first clamp is the periodic cap: the difference between `requested_rate_bps` and the HELOC's `current_rate_bps` immediately before the reset is compared to `periodic_cap_bps`; if the difference is strictly greater than `periodic_cap_bps`, the periodic-clamped value is `current_rate_bps + periodic_cap_bps`; if the difference is strictly less than the negative of `periodic_cap_bps`, the periodic-clamped value is `current_rate_bps - periodic_cap_bps`; otherwise the periodic-clamped value is exactly the `requested_rate_bps`. The second clamp is the lifetime bound: the periodic-clamped value is then bounded below by `lifetime_floor_bps` and above by `lifetime_cap_bps` to produce `applied_rate_bps`. Note that the periodic cap is applied against the HELOC's *current* rate, not its initial rate — a long sequence of resets can therefore migrate the rate well past its initial value, one periodic step at a time.

The resulting `applied_rate_bps` becomes the HELOC's new `current_rate_bps`, bumping `version` and refreshing `updated_at`. The clamping is silent: if the periodic or lifetime bounds were active, the persisted `RateReset.applied_rate_bps` will simply differ from the `requested_rate_bps`, and no validation error is raised against the request — the reset still succeeds and the difference is the audit trail. Two simultaneous rate resets on the same HELOC are serialized by the HELOC's `version`; both records ultimately persist, but the loser of the optimistic-concurrency race is rejected with `ERR_VERSION_CONFLICT` and must retry against the updated `current_rate_bps` so that its own periodic-clamp computation reflects the winner's outcome. Inputs and outputs are entirely in integer basis points and the computation requires no rounding.

### 3.6. Cross-Entity Default Triggers

A HELOC can be driven into `DEFAULT` by four distinct triggers, modeled as the `default_trigger` enumeration values `DELINQUENCY_90`, `INSURANCE_LAPSE`, `SENIOR_LIEN_DEFAULT`, and `BANKRUPTCY`. Three of these are cross-entity events recorded against the borrower, the property, or the senior lien; the fourth is found by the periodic billing-cycle sweep.

A `Servicer` records a bankruptcy filing against a borrower whose `bankruptcy_flag` is currently `false` (attempts against a borrower already flagged bankrupt are rejected with `ERR_ALREADY_BANKRUPT`). The recorded event is an immutable `BankruptcyEvent` carrying the originating `borrower_id` and a server-clock `recorded_at`. The borrower's `bankruptcy_flag` is flipped to `true`, the `bankruptcy_filed_at` timestamp is set to the server clock, and every HELOC with that `borrower_id` whose `status` is in `DRAW` or `REPAY` is cascaded into `DEFAULT` with `default_trigger` of `BANKRUPTCY` and a `DefaultEvent` whose `source_event_id` is the `id` of the `BankruptcyEvent` just recorded. The `bankruptcy_flag` and `bankruptcy_filed_at` never reset to their prior values.

A `Servicer` records an insurance change against a property by supplying an `event_type` of `LAPSE` or `REINSTATE`. A `LAPSE` event is only valid when the property's `insurance_status` is `ACTIVE`; a `REINSTATE` event is only valid when `insurance_status` is `LAPSED`; either mismatch is rejected with `ERR_INVALID_STATE`. The persisted `InsuranceEvent` carries the originating `property_id`, the `event_type`, and a server-clock `recorded_at`. A `LAPSE` flips the property's `insurance_status` to `LAPSED`, sets `insurance_lapsed_at` to the server clock, and cascades every HELOC on that property whose `status` is in `DRAW` or `REPAY` into `DEFAULT` with `default_trigger` of `INSURANCE_LAPSE` and a `DefaultEvent.source_event_id` pointing at the `InsuranceEvent`. A `REINSTATE` flips `insurance_status` back to `ACTIVE` and clears `insurance_lapsed_at` to `null`, but per §2.8 it does not reactivate any HELOC that had already been cascaded into `DEFAULT`.

A `Servicer` records a senior-lien default against a senior lien whose `status` is `CURRENT` (any other state yields `ERR_INVALID_STATE`). The persisted `SeniorLienDefaultEvent` carries the originating `senior_lien_id` and a server-clock `recorded_at`. The senior lien's `status` flips to `DEFAULTED`, its `defaulted_at` is set, and every HELOC on the same property whose `status` is in `DRAW` or `REPAY` is cascaded into `DEFAULT` with `default_trigger` of `SENIOR_LIEN_DEFAULT` and `DefaultEvent.source_event_id` pointing at the senior-lien-default event.

The fourth trigger, `DELINQUENCY_90`, is observed during the billing-cycle sweep rather than recorded as a discrete event. For a `DefaultEvent` produced by the delinquency sweep, the `source_event_id` is `null` because there is no source event to point at — the trigger is sweep-derived.

In every cascade, each affected HELOC receives a primary side effect (status moves to `DEFAULT`, `defaulted_at` is set, `default_trigger` is recorded per the §2.9 priority, a `DefaultEvent` is written, `updated_at` is refreshed, `version` is bumped) and a secondary side effect: any future `ANNUAL` fee that would otherwise be assessed on that HELOC is suppressed. Once a HELOC is in `DEFAULT`, no further `Draw` may be created against it — attempts return `ERR_HELOC_DEFAULTED`.

### 3.7. Billing Cycles, Interest Accrual, and Delinquency

The billing-cycle sweep is the periodic engine that ages every active HELOC by one 30-day cycle per invocation, starting from the HELOC's `last_cycle_end_date` (which is initialized at activation to the HELOC's `origination_date`). On each invocation, for every HELOC whose `status` is in `DRAW` or `REPAY`, the sweep performs a fixed sequence of steps.

It first computes the interest accrual for the cycle as the HELOC's `principal_balance_cents` multiplied by `current_rate_bps`, divided by 10000 to convert basis points to a decimal annual rate, then multiplied by 30 (one cycle's days) and divided by 365 (the canonical accrual year), with the result rounded half-up to whole cents before being added into `accrued_interest_cents`. It then recomputes the `minimum_payment_due_cents` for the new cycle using the same per-status formulae described in §3.4. It then sums the `amount_cents` of every `Payment` whose `posted_at` falls in the half-open interval beginning at the prior `last_cycle_end_date` and ending exactly 30 days later. If that sum is at least the prior cycle's `minimum_payment_due_cents`, the HELOC's `delinquency_days` is reset to zero; otherwise, `delinquency_days` is incremented by 30. The HELOC's `last_cycle_end_date` is then advanced by 30 days.

After the cycle's accrual and delinquency update, the sweep evaluates the delinquency trigger: if `delinquency_days` is at least 90 and the HELOC's `status` is still in `DRAW` or `REPAY`, the system records a `DefaultEvent` with `trigger` of `DELINQUENCY_90` (and `source_event_id` of `null`), transitions the HELOC to `DEFAULT`, and suppresses any future `ANNUAL` fee on that HELOC. Finally, regardless of the delinquency outcome, the sweep evaluates the period rollover: if the HELOC's `status` is still `DRAW` and the current clock time has reached or passed `draw_period_end_date`, the HELOC transitions from `DRAW` to `REPAY`. In `REPAY`, no further `Draw` may be taken; subsequent payments are evaluated against the amortizing variant of the minimum-payment formula rather than the interest-only variant.

Within a single sweep invocation, all eligible HELOCs are processed deterministically in ascending order of `id`. The sweep is idempotent per `(heloc_id, cycle_index)` pair, so re-running the sweep without advancing the clock does not double-accrue interest or double-increment delinquency.

### 3.8. Annual Fees and the First-Year Waiver

Annual fees are likewise driven by a sweep rather than charged interactively. The annual-fee sweep is idempotent per `(heloc_id, anniversary_index)`: for each HELOC, if the current clock time has reached or passed `origination_date` plus 365 days times the anniversary index, and no `Fee` record with `fee_type` of `ANNUAL` has yet been written for that `(heloc_id, anniversary_index)` pair, the sweep inserts one.

For each candidate assessment, if the HELOC's `status` is `DEFAULT` or `CLOSED`, the assessment is suppressed and no `Fee` is written at all. Otherwise, on the very first anniversary (anniversary index equal to 1), the behavior depends on `annual_fee_waived_first_year`: when that flag is `true`, a `Fee` is created with `fee_type` of `ANNUAL`, `amount_cents` of zero, and `status` of `WAIVED`; otherwise, and on every subsequent anniversary regardless of the flag, the `Fee` is created with `fee_type` of `ANNUAL`, `amount_cents` equal to the HELOC's configured `annual_fee_cents`, and `status` of `ASSESSED`. Every `Fee` record carries the originating `heloc_id` and a server-clock `assessed_at`. The `WAIVED` status is reserved exclusively for the first-anniversary waiver path.

### 3.9. Closure and the Early-Closure Fee

A `Servicer`, the `Borrower`, or a `PlatformAdmin` may close a HELOC by invoking the closure operation, optionally supplying the current `version` for the concurrency check. Closure is permitted from `DRAW`, `REPAY`, or `DEFAULT` and is rejected from `PENDING` or `CLOSED` with `ERR_INVALID_STATE` (an attempt against a HELOC already in `CLOSED` returns the more specific `ERR_HELOC_CLOSED`). Both balance buckets must be flat: the HELOC's `principal_balance_cents` and `accrued_interest_cents` must each be zero, or the closure is rejected with `ERR_BALANCE_NOT_ZERO`. On success the HELOC's `status` moves to `CLOSED` and `closed_at` is set to the current server clock.

The early-closure fee is then evaluated as a side effect of the transition. The tenure of the account is the whole-day difference between `closed_at` and `origination_date`. If that tenure is strictly less than 1095 days (three years) and the HELOC's `early_closure_fee_cents` is strictly greater than zero, the system inserts a `Fee` with `fee_type` of `EARLY_CLOSURE`, `amount_cents` equal to `early_closure_fee_cents`, `status` of `ASSESSED`, and a server-clock `assessed_at`. Otherwise no early-closure fee is written. Because `REPAY` only begins after `draw_period_end_date` has passed and `draw_period_end_date` is exactly 3650 days after `origination_date`, an early-closure fee is structurally impossible on a `REPAY → CLOSED` transition; it remains possible on `DRAW → CLOSED` and on `DEFAULT → CLOSED`.

Closure races interact with the rest of the system in two specific ways. When a close commits simultaneously with a payment that would push the balance back above zero, exactly one operation succeeds: if the close commits first, the payment is rejected with `ERR_HELOC_CLOSED`; if the payment commits first, the close is rejected with `ERR_BALANCE_NOT_ZERO`. When a close commits simultaneously with one of the cross-entity default cascades (an insurance lapse, a senior-lien default, a bankruptcy filing) or with a sweep-discovered 90-day delinquency, if the default cascade commits first the close still succeeds from `DEFAULT` (the `DEFAULT → CLOSED` transition is declared), but the early-closure window is evaluated against the later `closed_at` timestamp; if the close commits first, the cascade no-ops on this HELOC because its `status` is already `CLOSED`, and the loser of that race receives `ERR_HELOC_CLOSED`.

### 3.10. Borrower-Scoped Reads and Owner Identity

The read capabilities on borrowers, properties, senior liens, HELOCs, and HELOC child collections (draws, payments, rate resets, fees, default events) are shared across the `Originator`, `Servicer`, `Borrower`, and `PlatformAdmin` roles. When the acting role is `Borrower`, however, the server additionally enforces the identity rule from §2.1: the borrower's `X-User-ID` must match the resource's owning `borrower_id`, traversing the chain from the resource back to its owning borrower (a HELOC's draw rolls up through the HELOC's `borrower_id`; a property rolls up directly through its `borrower_id`). A borrower reading another borrower's resource is rejected with `ERR_FORBIDDEN`.

The HELOC list capability accepts optional `borrower_id`, `property_id`, and `status` query parameters in addition to the standard `limit` and `offset` page controls, and returns the filtered, paginated set of HELOCs. The single-HELOC read response includes the standard fields described in §2.4 as well as the computed `minimum_payment_due_cents`, the current `available_credit_cents`, and the current `current_rate_bps`, all evaluated against the present state of the account.

## 4. Endpoint Definitions

The table below lists every endpoint, the URL path, a short description, and the roles authorized to invoke it. Operations that create a new resource — including a HELOC, a child ledger entry, or an event record — return `201 Created` on success. Operations that modify an existing resource — including activation, close, the clock advance, and the periodic sweeps — return `200 OK`. The shapes of the request bodies, the field-by-field validation rules, and the side effects that fire on success are specified in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/borrowers` | Register a borrower. | Originator, PlatformAdmin |
| GET | `/borrowers/{id}` | Fetch a borrower. | Originator, Servicer, Borrower, PlatformAdmin |
| POST | `/borrowers/{id}/bankruptcy-events` | Record a bankruptcy filing for the borrower; cascades to default any DRAW/REPAY HELOCs. | Servicer, PlatformAdmin |
| POST | `/properties` | Register a property owned by a borrower. | Originator, PlatformAdmin |
| GET | `/properties/{id}` | Fetch a property. | Originator, Servicer, Borrower, PlatformAdmin |
| POST | `/properties/{id}/insurance-events` | Record an insurance status change (LAPSE or REINSTATE); LAPSE cascades to default any DRAW/REPAY HELOCs on the property. | Servicer, PlatformAdmin |
| POST | `/senior-liens` | Register a senior lien against a property. | Originator, PlatformAdmin |
| GET | `/senior-liens/{id}` | Fetch a senior lien. | Originator, Servicer, Borrower, PlatformAdmin |
| POST | `/senior-liens/{id}/default-events` | Declare the senior lien in default; cascades to default any DRAW/REPAY HELOCs on the same property. | Servicer, PlatformAdmin |
| POST | `/helocs` | Create a HELOC in PENDING status. Validates 2nd-lien, occupancy, CLTV, bankruptcy gates. | Originator, PlatformAdmin |
| GET | `/helocs/{id}` | Fetch a HELOC including computed minimum_payment_due_cents, available_credit_cents, and current_rate_bps. | Originator, Servicer, Borrower, PlatformAdmin |
| GET | `/helocs` | List HELOCs filtered by borrower_id, property_id, status (any combination). | Originator, Servicer, PlatformAdmin |
| POST | `/helocs/{id}/activate` | Activate a PENDING HELOC into DRAW state using a supplied prime_rate_bps. | Originator, PlatformAdmin |
| POST | `/helocs/{id}/close` | Close a HELOC; assesses an early-closure Fee if within 1095 days of origination. | Servicer, Borrower, PlatformAdmin |
| POST | `/helocs/{id}/draws` | Take a draw against the line (only while status == DRAW). | Borrower, PlatformAdmin |
| GET | `/helocs/{id}/draws` | List draws on a HELOC. | Originator, Servicer, Borrower, PlatformAdmin |
| POST | `/helocs/{id}/payments` | Apply a payment; allocated interest-first then principal (waterfall). | Borrower, Servicer, PlatformAdmin |
| GET | `/helocs/{id}/payments` | List payments on a HELOC. | Originator, Servicer, Borrower, PlatformAdmin |
| POST | `/helocs/{id}/rate-resets` | Record a rate reset given a quoted prime_rate_bps; periodic/lifetime caps applied silently. | Servicer, PlatformAdmin |
| GET | `/helocs/{id}/rate-resets` | List rate resets on a HELOC. | Originator, Servicer, Borrower, PlatformAdmin |
| GET | `/helocs/{id}/fees` | List fees (ANNUAL, EARLY_CLOSURE) on a HELOC. | Originator, Servicer, Borrower, PlatformAdmin |
| GET | `/helocs/{id}/default-events` | List default events on a HELOC. | Originator, Servicer, Borrower, PlatformAdmin |
| POST | `/_clock/advance` | Advance the server's logical clock by N seconds. | PlatformAdmin |
| POST | `/_sweep/billing-cycle` | Run one 30-day billing cycle for all HELOCs in {DRAW, REPAY}: accrue interest, recompute delinquency, fire DELINQUENCY_90 defaults, and roll DRAW->REPAY when draw_period_end_date has passed. | PlatformAdmin |
| POST | `/_sweep/annual-fees` | Assess any due ANNUAL fees on all HELOCs. Suppressed on HELOCs in {DEFAULT, CLOSED}; first anniversary records WAIVED if annual_fee_waived_first_year=true. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_UNKNOWN_ROLE` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_HELOC_DEFAULTED` | 409 Conflict |
| `ERR_HELOC_CLOSED` | 409 Conflict |
| `ERR_DRAW_PERIOD_ENDED` | 409 Conflict |
| `ERR_ALREADY_BANKRUPT` | 409 Conflict |
| `ERR_BALANCE_NOT_ZERO` | 422 Unprocessable Entity |
| `ERR_OCCUPANCY_NOT_PRIMARY` | 422 Unprocessable Entity |
| `ERR_NO_SENIOR_LIEN` | 422 Unprocessable Entity |
| `ERR_BORROWER_BANKRUPT` | 422 Unprocessable Entity |
| `ERR_CLTV_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BORROWER_PROPERTY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAYMENT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_RATE_BOUND_INVALID` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_AVAILABLE_CREDIT` | 422 Unprocessable Entity |
| `ERR_VALIDATION_FAILED` | 400 Bad Request |
