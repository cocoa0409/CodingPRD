# Annuity 1035 Exchange Review API — Product Requirements Document

## 1. Introduction

A Section 1035 exchange lets a policyholder move the accumulated value of an existing annuity into a new annuity contract without triggering immediate taxation. The same mechanism, abused, is one of the oldest sources of conduct risk in the insurance industry: a producer who churns clients through repeated replacements harvests new commissions while the client absorbs surrender charges, loses valuable living-benefit riders, and is locked into a fresh multi-year surrender schedule. Carriers operating a suitability desk are expected to catch exactly this — to document why a replacement is in the client's interest, to quantify what the client gives up, and to watch for producers whose exchange activity patterns look like churning.

This document specifies the API for an annuity carrier's 1035 exchange and replacement review platform. The platform manages the full lifecycle of a replacement case: registration of producers, annuitant clients, and their in-force contracts; origination of an exchange case by a writing producer; collection and verification of replacement disclosure and suitability documentation; a quantitative comparison analysis covering surrender charges, rider benefit loss, bonus credits, tax-basis allocation, and break-even projection; a two-stage supervisory review with segregation of duties; carrier-to-carrier funds transfer with compensating actions; the client's free-look period and rescission; and continuous surveillance of producer exchange activity. Because so many rules are time-driven — cooling-off windows, anti-churn windows, free-look deadlines, rolling twelve-month counters — the platform runs on a logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request in which either header is missing or empty, or whose role value is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is declared but does not appear in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The platform declares exactly six roles, spelled as follows: `CarrierAdmin`, `Producer`, `SuitabilityReviewer`, `Principal`, `ComplianceOfficer`, and `OperationsDesk`.

Role identity semantics differ across roles and are contractual. When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of the acting Producer record; ownership checks on any resource that references a producer compare the resource's `producer_id` field to `X-User-ID`. When `X-User-Role` is `CarrierAdmin`, `SuitabilityReviewer`, `Principal`, `ComplianceOfficer`, or `OperationsDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `reviewed_by_id` or `approved_by_id` on a case, or as `reviewer_id` on a decision record — but never compares it to any entity's `id`.

`CarrierAdmin` is the carrier platform administrator: it registers producers, operates the logical clock, and acts as a rescission backstop alongside the owning producer. `Producer` is the licensed writing agent who originates exchange cases and submits disclosure documents. `SuitabilityReviewer` staffs the suitability desk: running comparison analyses, verifying documents, recommending or rejecting. `Principal` holds final approval authority and may not approve a case it reviewed. `ComplianceOfficer` handles producer discipline (suspension and reinstatement); churn flags themselves are system-set. `OperationsDesk` runs the transfer desk: funds requests, receipt or failure of transfers, delivery confirmation, and completion. Every role may call every read endpoint.

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

Requests to an undefined path, or to a defined path with an unsupported method, are answered with `ERR_NOT_FOUND` (HTTP 404). An unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500) in the same envelope.

### 2.3. Pagination

List endpoints accept two query parameters. `limit` controls page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many records are skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` object; `has_more` is true exactly when `offset` plus the number of records in the returned page is less than `total_count`. All lists are sorted by `created_at` in ascending order. No secondary sort key is applied: records that share the same `created_at` keep their relative creation order (the sort is stable).

### 2.4. The Logical Clock

All timestamps in the platform — ages, deadlines, window membership, event times — read from a server-held logical clock, never from wall-clock time. At startup, before any operator intervention, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own. A `CarrierAdmin`-only test-driving capability sets the clock: the caller supplies a `to_iso8601` instant and receives the new `current_utc` back. An unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); any parseable ISO-8601 instant is accepted, whether it moves the clock forward or backward. Setting the clock has a mandatory side effect: the producer churn evaluation described in §3.8 is re-run for every registered producer, because rolling-window membership may shift with the new "now".

### 2.5. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Most resources additionally carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and a `version`, an integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from a related operation. One exception is carved out for producer surveillance maintenance: recomputing a producer's rolling twelve-month counters and stamping `last_churn_eval_at` do not increment the producer's `version` (nor touch `updated_at`); a producer's `version` moves only on suspension, reinstatement, and flag set/clear transitions. Two audit entity types are deliberately leaner: review decision records and activity events carry only `id` and `created_at`; both `updated_at` and `version` are absent on them.

### 2.6. Monetary and Rate Conventions

All monetary amounts are integer cents; no fractional cents exist anywhere in the system. All percentages and rates — surrender schedule percentages, growth assumptions, fee rates, bonus rates, rescission rates — are integer basis points, where 10,000 basis points equal 100 percent. Percentage-of-amount arithmetic is always performed by multiplying the integer-cent amount by the integer basis-point rate and then dividing by 10,000 exactly once, rounding down (floor division). Ratios are never rounded to a decimal before multiplying. Projections that compound do so year by year with a rounding-down step at each year, never in closed form. Free-look boundaries are evaluated on whole UTC dates.

### 2.7. Optimistic Concurrency Control

Exactly one write is guarded by optimistic concurrency control: the creation of a comparison analysis against a case. That request must carry `expected_case_version`, a non-optional input field holding the case `version` the client last observed. If the value does not match the case's current `version` — because another writer has since created an analysis (which itself supersedes the prior final analysis) or otherwise mutated the case — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the case. No other endpoint takes a version field.

### 2.8. Validation Order and Error Precedence

Incoming requests are validated against a fixed precedence ladder, and the first failing rung determines the error returned. First, the user-context headers are checked (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the caller's role is checked against the endpoint's authorized roles (`ERR_FORBIDDEN_FOR_ROLE`). Third, resource existence is resolved left-to-right: every `id` in the path, then body foreign keys such as `client_id`, `existing_contract_id`, and `producer_id`, each resolving to an existing resource or failing with `ERR_NOT_FOUND` (HTTP 404). Fourth, for producer-role callers mutating a case, ownership is enforced (`ERR_CASE_NOT_OWNED_BY_PRODUCER`, HTTP 403). Fifth, request body shape is validated (`ERR_INVALID_REQUEST`, HTTP 400). Sixth, state legality of the requested transition is checked (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — or `ERR_CONTRACT_NOT_IN_FORCE` for the contract precondition on case submission). Seventh, on the one OCC-guarded write, the expected version is compared (`ERR_STALE_VERSION`). Only after all seven rungs pass do the domain business rules of §3 run, in the orders stated there. Two endpoint families reorder this ladder: on the creation endpoints (`POST /producers`, `/clients`, `/contracts`, `/cases`) body-shape validation (rung five) runs first, before body foreign keys are resolved (rung three) — and, on `POST /cases`, before the ownership rung as well, so a malformed body yields `ERR_INVALID_REQUEST` even when a foreign key would not resolve; and on `POST /cases/{id}/comparison-analyses` the state check (rung six) runs ahead of body-shape validation, immediately before the version rung, per §3.4.

### 2.9. Audit Records and Case History

Two append-only record types make the platform's activity auditable, and both are queryable. A **review decision record** captures a `case_id`, a `stage` of `SUITABILITY` or `PRINCIPAL`, the `reviewer_id` (the decider's `X-User-ID`), a `decision` of `APPROVE`, `REJECT`, or `REQUEST_INFO`, and the free-text `rationale` supplied with the decision; `REQUEST_INFO` is only ever recorded at the `SUITABILITY` stage. An **activity event** captures a `producer_id`, a `case_id` (null for producer-level events), an `event_type`, and the `event_at` logical-clock timestamp at which the event fired. The nine event types are `CASE_SUBMITTED`, `CASE_WITHDRAWN`, `CASE_REJECTED`, `EXCHANGE_COMPLETED`, `EXCHANGE_RESCINDED`, `PRODUCER_FLAGGED`, `PRODUCER_UNFLAGGED`, `PRODUCER_SUSPENDED`, and `PRODUCER_REINSTATED`. A producer's complete exchange-activity trail is listable with an optional `event_type` filter, as is the case-scoped slice of that trail attached to an individual case; a case's decision records are listable with an optional `stage` filter.

## 3. Business Logic & Workflows

### 3.1. Producers, Annuitants, and the In-Force Book

Before any case exists, the desk's book of business must be registered. A `CarrierAdmin` registers each producer with a `license_number` that is unique across all producers, a `full_name`, and a `home_state_code` giving the two-letter state of primary appointment. The `license_number` uniqueness comparison is exact (case-sensitive), and a colliding registration is rejected with `ERR_INVALID_REQUEST` (HTTP 400); the state code is stored as supplied, validated only as a non-empty string. A newly registered producer starts in `ACTIVE` status with all twelve-month counters at zero and `last_churn_eval_at` null until the first churn evaluation runs.

Clients — the annuitants whose contracts may be replaced — are registered by a `Producer` or `CarrierAdmin` with a `full_name`, a `date_of_birth` in ISO YYYY-MM-DD form, and a two-letter residence `state_code` (stored as supplied, again validated only as a non-empty string). From the logical clock the server derives `age_years`, the whole years between `date_of_birth` and the current clock date, and `is_senior`, which is true when the client is at least 65 years old and drives the extended free-look period described in §3.7. Both `age_years` and `is_senior` are computed once, at registration, and stored on the client record; later clock movements do not recompute them. A client's `last_rescinded_at` is null until that client's first rescission.

An in-force contract that a case may later replace is registered by a `Producer` or `CarrierAdmin` with its owning `client_id`, the ceding `carrier_name`, a `contract_number`, the `issue_date`, the current accumulation `account_value_cents`, and the cost `tax_basis_cents`; `account_value_cents` must be a positive integer and `tax_basis_cents` a non-negative integer. The contract's `surrender_schedule` is a non-empty ordered list of entries, each pairing a `contract_year` (an integer of at least 1) with a `pct_bps` (an integer from 0 to 10,000); the years must number consecutively 1, 2, 3, … with no gaps, duplicates, or reordering, and the entry for year Y applies to surrenders occurring inside contract year Y. Rider economics come in as `living_benefit_rider` — a required boolean — plus `rider_benefit_base_cents` and `rider_annual_fee_bps`, both optional non-negative integers defaulting to 0 whenever omitted (whether or not a rider is attached), with `rider_annual_fee_bps` capped at 10,000. A contract that was itself acquired via a completed exchange arrives with `last_exchange_completed_at` set — when supplied at registration it must be a non-empty string, and no timestamp parsing is applied to it at registration; it is null when the contract was never exchanged into. New contracts start `IN_FORCE`. The (`carrier_name`, `contract_number`) pair is unique case-insensitively across all registered contracts, and a colliding registration is rejected with `ERR_DUPLICATE_CONTRACT_NUMBER` (HTTP 409). A client's contracts are listable with an optional `status` filter.

Across all endpoints that accept a body, malformed payloads — a missing required field, an enum value outside its declared set, a non-positive integer where a positive one is required, an unparseable ISO date, a `surrender_schedule` whose years are not strictly ascending from 1 — are rejected with `ERR_INVALID_REQUEST`. For a case whose `exchange_type` is `PARTIAL`, a missing `exchange_amount_cents` is likewise a body-shape error.

### 3.2. Originating a Case and the Submission Gates

A `Producer` originates a replacement case by naming themselves via `producer_id` (which must equal the caller's `X-User-ID`, else `ERR_CASE_NOT_OWNED_BY_PRODUCER`, HTTP 403), the `client_id`, and the `existing_contract_id` of the contract being replaced, together with the replacement product's `new_product_code` and `new_product_surrender_years` (the length of the new product's own surrender schedule in years — a non-negative integer). The `exchange_type` is `FULL` or `PARTIAL`. For a `PARTIAL` exchange the gross `exchange_amount_cents` is required and must be a positive integer; for a `FULL` exchange the field is ignored and the system sets it to the contract's `account_value_cents`. The new product's economics arrive as `new_product_bonus_bps`, an up-front bonus in basis points of the amount received, and `new_product_annual_fee_bps`; both are optional integers bounded to [0, 10,000] and default to 0. A new case starts in `DRAFT`. The full lifecycle vocabulary is `DRAFT`, `SUBMITTED`, `SUITABILITY_REVIEW`, `INFO_REQUESTED`, `PENDING_PRINCIPAL`, `APPROVED`, `FUNDS_REQUESTED`, `FUNDS_RECEIVED`, `IN_FREE_LOOK`, `COMPLETED`, `REJECTED`, `WITHDRAWN`, and `RESCINDED`, with `COMPLETED`, `REJECTED`, `WITHDRAWN`, and `RESCINDED` terminal. The case book is listable with optional `producer_id`, `client_id`, `existing_contract_id`, and `status` filters.

Submitting a case — the `DRAFT` → `SUBMITTED` transition by the owning producer — is where the desk's protective gates run, and they run in a fixed order. First, ownership: a producer-role caller whose `X-User-ID` differs from the case's `producer_id` is rejected with `ERR_CASE_NOT_OWNED_BY_PRODUCER`. Second, the contract must be `IN_FORCE`, else `ERR_CONTRACT_NOT_IN_FORCE`. Third, the producer must not be `SUSPENDED`, else `ERR_PRODUCER_SUSPENDED`. Fourth, client cooling-off: if the client's `last_rescinded_at` is set and fewer than 30 days have elapsed since it, submission is rejected with `ERR_COOLING_OFF_ACTIVE`; a client who has never rescinded passes. Fifth, anti-churn: if the contract's `last_exchange_completed_at` is set and fewer than 365 days have elapsed, submission is rejected with `ERR_CONTRACT_EXCHANGED_WITHIN_12M`. Sixth, occupation: if any other case on the same contract is in a non-terminal status — anything other than `COMPLETED`, `REJECTED`, `WITHDRAWN`, or `RESCINDED` — submission is rejected with `ERR_CONTRACT_EXCHANGE_IN_PROGRESS`. Seventh, for `PARTIAL` exchanges, the `exchange_amount_cents` must be at least 100,000 cents (one thousand dollars), else `ERR_PARTIAL_BELOW_MINIMUM`, and must be strictly less than the contract's current `account_value_cents`, else `ERR_PARTIAL_AMOUNT_INVALID`.

A successful submission stamps `submitted_at` with the logical clock, bumps the case `version`, appends a `CASE_SUBMITTED` activity event for the producer, recomputes the producer's twelve-month counters, and runs the churn evaluation of §3.8.

A producer may withdraw a case — moving it to `WITHDRAWN` — at any point before funds are requested: from `DRAFT`, `SUBMITTED`, `SUITABILITY_REVIEW`, `INFO_REQUESTED`, `PENDING_PRINCIPAL`, or `APPROVED`. Ownership is always required. Withdrawal from `DRAFT` is silent (no activity event, since the case was never submitted); withdrawal from any of the later states appends `CASE_WITHDRAWN` and recomputes the producer counters.

### 3.3. Disclosure Documents and the Review Loop

Three document types constitute a complete replacement file: `REPLACEMENT_DISCLOSURE`, `SUITABILITY_FORM`, and `IN_FORCE_ILLUSTRATION`. The owning producer submits documents by `doc_type` while the case is in `DRAFT`, `SUBMITTED`, `SUITABILITY_REVIEW`, or `INFO_REQUESTED`; submission in any other case state is rejected with `ERR_INVALID_STATE_TRANSITION`, and a producer who does not own the case is rejected with `ERR_CASE_NOT_OWNED_BY_PRODUCER`. Each new document starts `SUBMITTED` at `revision` 1. A case's documents are listable with optional `doc_type` and `status` filters.

Review begins when a `SuitabilityReviewer` takes a `SUBMITTED` case into review, moving `SUBMITTED` → `SUITABILITY_REVIEW`. From there the reviewer adjudicates individual documents: verifying one moves it `SUBMITTED` → `VERIFIED`, while rejecting one moves it `SUBMITTED` → `REJECTED` and records the request's `rationale` in the document's `rejection_reason`. Both adjudications require the parent case to be in `SUITABILITY_REVIEW` or `INFO_REQUESTED`, failing with `ERR_INVALID_STATE_TRANSITION` otherwise; adjudicating a document that is not currently `SUBMITTED` likewise fails with `ERR_INVALID_STATE_TRANSITION`.

A rejected document is not the end of the road. The producer may resubmit the same `doc_type`, which moves the document `REJECTED` → `SUBMITTED`, increments its `revision` by exactly 1, and clears its `rejection_reason`; this correction loop may repeat any number of times. Only a `REJECTED` document is reopened in place: whenever no `REJECTED` document of that `doc_type` exists, the submission creates a fresh document at `revision` 1, even if another `SUBMITTED` document of the same `doc_type` is already on file. Whenever a document submission succeeds while the case sits in `INFO_REQUESTED` — whether a resubmission or a brand-new document — the case returns to `SUITABILITY_REVIEW` in the same operation; this is the producer's channel for answering the info request. Once a document reaches `VERIFIED` it is locked — resubmitting that `doc_type` is rejected with `ERR_DOCUMENT_LOCKED` (HTTP 409). The submission endpoint responds with HTTP 201 on both an initial submission and a resubmission (a resubmitted document keeps its original `id`).

When documentation is insufficient, the reviewer can bounce the case back to the producer: requesting info moves `SUITABILITY_REVIEW` → `INFO_REQUESTED` and appends a review decision at stage `SUITABILITY` with decision `REQUEST_INFO` and the request's `rationale`, which is a required field of the request body (a missing `rationale` is `ERR_INVALID_REQUEST`).

### 3.4. The Comparison Analysis

The quantitative heart of the review is the comparison analysis, created by a `SuitabilityReviewer` while the case is in `SUITABILITY_REVIEW` or `INFO_REQUESTED` — any other case state fails with `ERR_INVALID_STATE_TRANSITION`, and that state check precedes both request-body validation and the version check. The request carries two illustrated growth assumptions, `assumed_old_growth_bps` for the existing contract and `assumed_new_growth_bps` for the replacement product — both must be integers, with no range restriction (negative assumed rates are accepted) — plus the OCC field `expected_case_version` described in §2.7, which must be a non-negative integer (missing, non-integer, or negative values are `ERR_INVALID_REQUEST`); a version mismatch is rejected with `ERR_STALE_VERSION`. The analysis records its `analysis_date` from the logical clock at creation, and a new analysis always starts in `FINAL` status. Creating an analysis on a case that already has one flips the prior `FINAL` analysis to `SUPERSEDED`, points the new analysis's `supersedes_analysis_id` at it (null for the first), and increments the parent case's `version` by one. A case's analyses, both `FINAL` and `SUPERSEDED`, are listable with an optional `status` filter.

Every computed field below is populated at creation, in integer cents with rounding down.

The gross base to which the surrender charge applies, `exchange_base_cents`, is the contract's `account_value_cents` for a `FULL` exchange and the case's `exchange_amount_cents` for a `PARTIAL` one. Surrender percentages come from the contract's own `surrender_schedule` via anniversary arithmetic: the number of completed contract years at a given as-of date is the largest count of whole anniversaries of `issue_date` that fall on or before that date — the exact anniversary day itself counts as completed, and a contract issued on February 29 observes its anniversary on February 28 in non-leap years — and the applicable schedule year is that count plus one. The schedule entry whose `contract_year` equals that year supplies the percentage; when the year runs past the end of the schedule, the percentage is zero.

The analysis evaluates the schedule twice. The chronological variant reads the percentage as of the `analysis_date` itself, yielding `surrender_pct_bps_today`, and `surrender_charge_today_cents` is the `exchange_base_cents` multiplied by that percentage and divided by 10,000, rounded down. The forward-looking variant projects to the estimated carrier settlement date, 45 days after the `analysis_date`, yielding `surrender_pct_bps_at_settlement` and `surrender_charge_at_settlement_cents` by the same multiplication and single rounding-down division; an anniversary falling inside the 45-day settlement lag drops the charge into the next, lower schedule band, so the at-settlement charge is smaller than the today's charge whenever an anniversary intervenes.

From those, `amount_received_cents` is the `exchange_base_cents` minus the at-settlement charge. The `bonus_credit_cents` is the `amount_received_cents` multiplied by `new_product_bonus_bps` and divided by 10,000, rounded down — the bonus is computed on the net amount received, never on the gross base. The `benefit_loss_cents` is zero when the contract has no living-benefit rider; otherwise it is the amount by which `rider_benefit_base_cents` exceeds `account_value_cents`, floored at zero and capped at 2,000,000 cents. The `net_replacement_cost_cents` is then pinned to this exact evaluation order: the at-settlement surrender charge, plus the benefit loss, minus the bonus credit.

Tax basis follows the money. For a `FULL` exchange, `basis_transferred_cents` is the contract's entire `tax_basis_cents` and `basis_remaining_cents` is zero. For a `PARTIAL` exchange, `basis_transferred_cents` is the `tax_basis_cents` multiplied by `exchange_amount_cents` and then divided by `account_value_cents`, rounded down — the integer multiplication happens first and the division happens exactly once; the ratio itself must never be rounded to a decimal before multiplying, because the orders genuinely differ (8,000,000 cents of basis on a 3,333,333-cent partial out of a 10,000,000-cent contract yields 2,666,666 cents transferred by multiply-then-divide, but 2,666,400 cents if the ratio is first rounded to 0.3333). `basis_remaining_cents` is whatever basis stays with the old contract.

Finally, `break_even_years` projects both positions forward. The existing contract's net growth rate is `assumed_old_growth_bps` minus `rider_annual_fee_bps` when a rider is attached, or the unadjusted assumption when there is no rider; the replacement's net rate is `assumed_new_growth_bps` minus `new_product_annual_fee_bps`. Year zero starts the old balance at `account_value_cents` and the new balance at `amount_received_cents` plus `bonus_credit_cents`. Each subsequent year, each balance is multiplied by 10,000 plus its net rate and divided by 10,000, rounded down — compounding year by year rather than in closed form. The first year from 1 through 30 in which the new balance is greater than or equal to the old balance is the result; if the replacement never catches up inside the 30-year horizon, the analysis records 99.

### 3.5. Supervisory Recommendation and Principal Approval

With the file complete, the reviewer recommends the case: `SUITABILITY_REVIEW` → `PENDING_PRINCIPAL`. Recommendation enforces two checks, in this order: all three required document types must have a `VERIFIED` document, else `ERR_REQUIRED_DOCUMENTS_INCOMPLETE` (HTTP 409); then a comparison analysis in `FINAL` status must exist for the case, else `ERR_ANALYSIS_MISSING` (HTTP 409). A successful recommendation appends a review decision at stage `SUITABILITY` with decision `APPROVE` and the supplied `rationale`, and stamps the case's `reviewed_by_id` with the reviewer's `X-User-ID`.

Final authority rests with a `Principal`, whose approval moves `PENDING_PRINCIPAL` → `APPROVED`. Segregation of duties is enforced mechanically: the approving principal's `X-User-ID` must differ from the case's `reviewed_by_id`, and a principal who recommended the case is rejected with `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 409). Approval appends a review decision at stage `PRINCIPAL` with decision `APPROVE` and stamps `approved_by_id`.

Either stage can kill the case. The reviewer rejects from `SUITABILITY_REVIEW`, the principal from `PENDING_PRINCIPAL`; rejection moves the case to `REJECTED`, appends a review decision whose `stage` matches the rejecting role with decision `REJECT` and the supplied `rationale`, and appends a `CASE_REJECTED` activity event for the producer.

### 3.6. Funds Movement and Contract Surrender

Once a case is `APPROVED`, the `OperationsDesk` requests the carrier-to-carrier transfer, moving the case `APPROVED` → `FUNDS_REQUESTED` and creating a funds transfer record in `REQUESTED` status. The transfer's `amount_cents` — the cash the ceding carrier remits — is the exchange base minus the surrender charge recomputed under the at-settlement variant at request time, and `surrender_charge_cents` is the charge so withheld; `basis_transferred_cents` follows the allocation rules of §3.4. Critically, the transfer snapshots the contract's `account_value_cents` and `tax_basis_cents` into `pre_exchange_value_cents` and `pre_exchange_basis_cents` at request time, and stamps `requested_at`; these snapshots are what a later rescission restores from. In the same operation the contract moves `IN_FORCE` → `SURRENDER_PENDING` with its `version` bumped. A case's transfers are listable with an optional `status` filter.

When the ceding carrier's money arrives, the desk records receipt: the transfer moves `REQUESTED` → `RECEIVED` with `received_at` stamped, and this single mutation cascades. The parent case moves `FUNDS_REQUESTED` → `FUNDS_RECEIVED`; the contract moves `SURRENDER_PENDING` → `EXCHANGED`; and the contract's balances are reduced — for a `FULL` exchange `account_value_cents` and `tax_basis_cents` both become zero, while for a `PARTIAL` exchange the `exchange_amount_cents` is subtracted from the account value and the transfer's `basis_transferred_cents` is subtracted from the basis. Each mutated entity's `version` increments. Receipt is only legitimate while the case's transfer is `REQUESTED`; otherwise the call fails with `ERR_INVALID_STATE_TRANSITION`.

When the transfer fails, the desk records that instead: the transfer moves `REQUESTED` → `FAILED`, and the compensating cascade reverts the case `FUNDS_REQUESTED` → `APPROVED` and the contract `SURRENDER_PENDING` → `IN_FORCE`, again bumping each version. The compensation path leaves the case eligible to request funds again from `APPROVED`.

### 3.7. Delivery, Free Look, Completion, and Rescission

When the replacement policy is delivered to the client, the desk confirms delivery and the case moves `FUNDS_RECEIVED` → `IN_FREE_LOOK`. That instant stamps `free_look_started_at`, and the server computes `free_look_deadline_date` as the delivery date plus the free-look length: 30 days when the client's stored `is_senior` flag is true, 20 days otherwise. That flag is the one derived once at client registration (§3.1); it is not recomputed at delivery, so a client who turns 65 between registration and delivery still receives the standard 20-day period. The delivery date itself is day 0, and boundaries are evaluated on whole UTC dates.

Closing the case — `IN_FREE_LOOK` → `COMPLETED` — requires the current date to be strictly after `free_look_deadline_date`; attempting completion on or before that date is rejected with `ERR_FREE_LOOK_STILL_ACTIVE` (HTTP 409). Completion stamps `completed_at`, stamps the old contract's `last_exchange_completed_at` with the same instant (the anti-churn marker consulted at submission), appends an `EXCHANGE_COMPLETED` event for the producer, recomputes the producer counters, and runs the churn evaluation, which may set or clear `FLAGGED`.

Inside the window, the client may unwind everything. Rescission — `IN_FREE_LOOK` → `RESCINDED` — is performed by the owning producer (ownership enforced via `ERR_CASE_NOT_OWNED_BY_PRODUCER`) or by a `CarrierAdmin` as backstop, and requires the current date to be on or before `free_look_deadline_date`, the boundary inclusive; a later attempt is rejected with `ERR_FREE_LOOK_EXPIRED` (HTTP 409). Rescission is a synchronous transitive chain. The case stamps `rescinded_at` and becomes `RESCINDED`; the transfer moves `RECEIVED` → `RETURNED` with `returned_at` stamped; the contract moves `EXCHANGED` → `IN_FORCE` with its `account_value_cents` and `tax_basis_cents` restored verbatim from the transfer's `pre_exchange_value_cents` and `pre_exchange_basis_cents` snapshots; the restore stamps the client's `last_rescinded_at`; and an `EXCHANGE_RESCINDED` event fires for the producer, followed by counter recomputation and churn evaluation. Every entity touched along the chain has its `version` incremented.

### 3.8. Producer Surveillance and Discipline

Churn surveillance runs continuously. The full evaluation re-executes after case submission, completion, and rescission, after every reinstatement, and after every logical-clock set, and each of these runs stamps the producer's `last_churn_eval_at`; case rejection and withdrawal instead recompute only the rolling counters and rate variants, stamping neither `last_churn_eval_at` nor any flag change. The evaluation works over a trailing 365-day half-open window: activity events of that producer whose `event_at` is strictly more recent than 365 days before now and at or before now are in — an event exactly 365 days old is excluded, an event at exactly the current instant is included.

From that window three counters derive: `submitted_case_count_12m` counts `CASE_SUBMITTED` events, `completed_exchange_count_12m` counts `EXCHANGE_COMPLETED` events, and `rescinded_exchange_count_12m` counts `EXCHANGE_RESCINDED` events. Two rate variants follow. The completed-basis variant, `rescission_rate_completed_bps`, is 10,000 times the rescinded count divided by the completed count, rounded down — and zero when the producer has no completions in the window. The submitted-basis variant, `rescission_rate_submitted_bps`, applies the same formula over submissions and is zero when there are none; because some submitted cases never complete, the two variants give different numbers for identical event data. The producer record, readable by every role, exposes all of these computed counters.

The flag rule uses the completed-basis variant with inclusive thresholds: a producer is set to `FLAGGED` when `completed_exchange_count_12m` is at least 2 and `rescission_rate_completed_bps` is at least 5,000 basis points, and a later evaluation that finds the condition no longer holding automatically clears the producer back to `ACTIVE`. Flag transitions fire `PRODUCER_FLAGGED` and `PRODUCER_UNFLAGGED` events. A flag is advisory — it does not block submission.

Discipline is manual. A `ComplianceOfficer` suspends a producer from `ACTIVE` or `FLAGGED`, moving them to `SUSPENDED` with a `PRODUCER_SUSPENDED` event; a suspended producer cannot submit cases (§3.2's `ERR_PRODUCER_SUSPENDED`). Reinstatement moves `SUSPENDED` → `ACTIVE` with a `PRODUCER_REINSTATED` event and immediately re-runs the churn evaluation in the same request — so if the thresholds are still met, the producer lands on `FLAGGED` rather than `ACTIVE`.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; action endpoints that transition or mutate an existing resource, and all read endpoints, respond with HTTP 200. Request payloads, computed fields, side effects, and failure modes for each endpoint are specified in the §2 and §3 narratives; this table is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock; re-runs churn evaluation for all producers | CarrierAdmin |
| POST | /producers | Register a producer | CarrierAdmin |
| GET | /producers/{id} | Get a producer including computed churn counters | All roles |
| POST | /producers/{id}/suspend | Suspend a producer (from ACTIVE or FLAGGED) | ComplianceOfficer |
| POST | /producers/{id}/reinstate | Reinstate a suspended producer | ComplianceOfficer |
| GET | /producers/{id}/activity-events | List a producer's exchange activity events | All roles |
| POST | /clients | Register an annuitant client | Producer, CarrierAdmin |
| GET | /clients/{id} | Get a client | All roles |
| GET | /clients/{id}/contracts | List a client's existing contracts | All roles |
| POST | /contracts | Register an in-force contract | Producer, CarrierAdmin |
| POST | /cases | Create a DRAFT exchange case | Producer |
| GET | /cases/{id} | Get a case | All roles |
| GET | /cases | List cases with filters and pagination | All roles |
| POST | /cases/{id}/submit | Submit a DRAFT case for review | Producer |
| POST | /cases/{id}/withdraw | Withdraw a case before funds are requested | Producer |
| POST | /cases/{id}/start_review | Take a SUBMITTED case into suitability review | SuitabilityReviewer |
| POST | /cases/{id}/request_info | Request corrected or additional documentation | SuitabilityReviewer |
| POST | /cases/{id}/recommend | Recommend approval; requires verified docs and a FINAL analysis | SuitabilityReviewer |
| POST | /cases/{id}/reject | Reject the case (terminal) | SuitabilityReviewer, Principal |
| POST | /cases/{id}/approve | Approve; approver must not be the recommending reviewer | Principal |
| POST | /cases/{id}/request_funds | Request the carrier-to-carrier funds transfer | OperationsDesk |
| POST | /cases/{id}/confirm_delivery | Confirm policy delivery; starts the free-look period | OperationsDesk |
| POST | /cases/{id}/complete | Close the case after the free-look deadline | OperationsDesk |
| POST | /cases/{id}/rescind | Rescind inside the free-look window; returns funds and restores the contract | Producer, CarrierAdmin |
| POST | /cases/{id}/documents | Submit or resubmit a disclosure document | Producer |
| GET | /cases/{id}/documents | List a case's documents | All roles |
| POST | /documents/{id}/verify | Verify a submitted document | SuitabilityReviewer |
| POST | /documents/{id}/reject | Reject a submitted document | SuitabilityReviewer |
| POST | /cases/{id}/comparison-analyses | Create the comparison analysis (OCC-guarded) | SuitabilityReviewer |
| GET | /cases/{id}/comparison-analyses | List a case's analyses | All roles |
| GET | /cases/{id}/funds-transfers | List a case's funds transfers | All roles |
| POST | /transfers/{id}/mark_received | Record receipt of funds; cascades case and contract | OperationsDesk |
| POST | /transfers/{id}/mark_failed | Record transfer failure; compensates case and contract | OperationsDesk |
| GET | /cases/{id}/activity-events | List activity events attached to a case | All roles |
| GET | /cases/{id}/review-decisions | List a case's review/approval decision records | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_CASE_NOT_OWNED_BY_PRODUCER | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_CONTRACT_NOT_IN_FORCE | 409 |
| ERR_DUTY_SEGREGATION_VIOLATION | 409 |
| ERR_PRODUCER_SUSPENDED | 409 |
| ERR_REQUIRED_DOCUMENTS_INCOMPLETE | 409 |
| ERR_ANALYSIS_MISSING | 409 |
| ERR_COOLING_OFF_ACTIVE | 409 |
| ERR_CONTRACT_EXCHANGED_WITHIN_12M | 409 |
| ERR_CONTRACT_EXCHANGE_IN_PROGRESS | 409 |
| ERR_DUPLICATE_CONTRACT_NUMBER | 409 |
| ERR_DOCUMENT_LOCKED | 409 |
| ERR_PARTIAL_BELOW_MINIMUM | 409 |
| ERR_PARTIAL_AMOUNT_INVALID | 409 |
| ERR_FREE_LOOK_EXPIRED | 409 |
| ERR_FREE_LOOK_STILL_ACTIVE | 409 |
| ERR_INTERNAL | 500 |
