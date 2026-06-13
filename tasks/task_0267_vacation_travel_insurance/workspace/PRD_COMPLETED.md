# Vacation Travel Insurance API — Product Requirements Document

## 1. Introduction

The Vacation Travel Insurance API is the system of record for a travel insurer that sells trip-cost protection across tiered coverage plans and adjudicates the claims those plans give rise to. A traveler who has prepaid a non-refundable vacation buys a policy keyed to a published plan, names the people insured under it, pays the premium, and — once the underwriter issues the contract — holds coverage against four named perils: trip cancellation, emergency medical expense, travel delay, and lost or damaged baggage. When a loss occurs, the traveler files a claim, supplies documentation and itemized expenses, and an adjuster reviews, approves or denies, and ultimately disburses a payout that draws down the policy's finite aggregate limit.

This document specifies that lifecycle end to end. The business demands two properties above all. First, **ledger conservation**: every policy carries a fixed pool of payout capacity and a premium-collected balance, and each disbursement, reversal, refund, and refund-void must move those balances by exactly the right amount and never let them drift. Second, **compliance fidelity**: pre-existing-condition waivers, named-storm cutoffs, delay thresholds, filing deadlines, and free-look windows are eligibility gates whose boundaries are exact, one-sided where the regulation is one-sided, and evaluated in a defined order so that a safety failure is never masked by a fiscal one. The remainder of this document defines the global contract every endpoint honors (§2), the business workflows and their scattered rules (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH`; a header is malformed when `X-User-ID` is empty or whitespace-only, or when `X-User-Role` is not one of the six recognized role names below. Any of those six names — including `System` and `Any` — is accepted as a well-formed `X-User-Role` value at the authentication step (so supplying `System` or `Any` is never itself an `ERR_MISSING_AUTH`); when the headers are present and well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes the following roles, spelled exactly as shown: `CarrierAdmin`, `Underwriter`, `ClaimsAdjuster`, `Traveler`, `System`, and `Any`. The `CarrierAdmin` is the carrier operator who configures coverage plans, declares named storms, and drives the test clock. The `Underwriter` prices and issues policies, records premium payment, and completes or voids refunds. The `ClaimsAdjuster` adjudicates claims and manages payouts. The `Traveler` buys policies, manages the insured roster, files and resubmits claims, and cancels within the permitted windows. `System` denotes server-driven automation — clock-triggered expirations and the cascade-driven auto-denials and refund completions described in §3 — and is never a value a client supplies. `Any` denotes that any one of the authenticated roles may perform the operation; it is used exclusively for read and list endpoints.

The roles relate to persisted identity as follows. When `X-User-Role` is `Traveler`, `X-User-ID` is the `id` of the acting `Traveler`; ownership checks on any resource that references a `Traveler` compare the resource's foreign-key field to `X-User-ID` (for a policy, its `owner_traveler_id`; for a claim, the `owner_traveler_id` of the policy the claim is filed against). A `Traveler` who attempts to mutate a policy or claim they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `CarrierAdmin`, `Underwriter`, `ClaimsAdjuster`, `System`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow calls for it — for example, the uploader of a claim document is captured as `uploaded_by_traveler_id` on the `ClaimDocument` — but it is not compared to any entity's `id` for those roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list-based response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of items matching the query before pagination and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties

Most resources in this system carry a standard set of server-managed fields. The `id` is a unique, server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp, in the same format, recording the most recent modification; it is refreshed on every mutation, including mutations caused by a cascade rather than a direct request. The `version` field is an integer that begins at 1 and increments by one on every mutation of the resource, including cascade-driven mutations, and is the basis for optimistic concurrency control (§2.9).

One entity is an append-only audit record and therefore carries only `id` and `created_at`, with no `updated_at` and no `version`: the `ClaimDocument`. Once uploaded, a `ClaimDocument` is never modified, so it exposes only `id` and `created_at` alongside its content fields. Every other entity — `Plan`, `Traveler`, `Policy`, `InsuredTraveler`, `NamedStorm`, `Claim`, `ClaimExpense`, `Payout`, and `Refund` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Nested Resource Retrieval and Referential Validation

Several resources are addressed or filed beneath a parent — insured travelers, claim expenses, and claim documents all hang off a parent identified in the path or body. When an endpoint path carries more than one resource identifier (for example, an insured-traveler creation under a specific policy, or an expense added to a specific claim), the system validates each identifier in left-to-right order and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. The same `ERR_NOT_FOUND` governs foreign keys supplied in a request body: a `plan_id`, `owner_traveler_id`, `policy_id`, `insured_traveler_id`, `named_storm_id`, `traveler_id`, or `claim_id` that does not point at a live record causes the request to be rejected before any business rule runs. Existence checks always precede state and business checks.

### 2.6. Monetary Values, Precision, and Rounding

All monetary quantities are stored and returned as whole integer cents — there are no fractional cents and no floating-point currency in the system. Each calculation in §3 specifies its own rounding direction because the directions differ by calculation and the differences are deliberate: premium components round **up** to the next whole cent (ceiling) on each term independently; cancellation reimbursement and its CFAR percentage round **down** (floor); short-rate premium proration rounds **down** (floor); aggregate-limit pinning rounds **down** (floor); and per-item baggage depreciation rounds **half up**. Where a calculation sums several rounded terms, the rounding is applied to each term in the order the calculation names before the terms are combined; the order is never to be reversed. Day counts derived from timestamps are computed in whole days using the floor or ceiling the relevant calculation names.

### 2.7. Ledger Conservation and Cascading State

Two quantities on each `Policy` are conserved and must be recomputed synchronously inside every request that disturbs them. The first is payout capacity: `aggregate_limit_cents` is pinned at issuance and never changes thereafter, `amount_reimbursed_cents` is the running sum of disbursed payout amounts against the policy, and `remaining_aggregate_cents` is always `aggregate_limit_cents` minus `amount_reimbursed_cents`. The second is premium collected: `net_premium_collected_cents` is the premium recognized as collected net of completed refunds. These fields are never set by a client; they are derived, and any mutation that should move them does so in the same request that causes it.

Many operations touch more than one resource. A payout disbursement, a refund completion, a free-look cancellation, and a payout reversal each cascade: they advance one resource's state and, in the same transaction, mutate a parent policy's ledger fields and possibly its status, and may in turn auto-resolve sibling claims. Each resource a cascade touches has its own `updated_at` refreshed and its own `version` incremented. The specific cascades — what mutates what, in what order, and under what condition — are described with the workflows that trigger them in §3; this subsection establishes only that cascades are synchronous, conserve the ledgers, and version every resource they touch.

### 2.8. Parallel Policy State and the Claim Revision Cycle

A `Policy` carries two independent status axes that advance separately. The `payment_status` axis tracks premium settlement and takes the values `PENDING`, `PAID`, and `REFUNDED`. The `coverage_status` axis tracks the coverage lifecycle and takes the values `QUOTED`, `ACTIVE`, `EXPIRED`, `CANCELLED`, and `EXHAUSTED`. A newly quoted policy is `QUOTED` on the coverage axis and `PENDING` on the payment axis; a single operation may advance one axis while leaving the other unchanged — recording payment, for instance, moves `payment_status` from `PENDING` to `PAID` while `coverage_status` remains `QUOTED`. `CANCELLED`, `EXPIRED`, and `EXHAUSTED` are terminal coverage states.

A `Claim` follows a single status axis that is cyclic. It begins `SUBMITTED`, may be opened to `UNDER_REVIEW`, may be bounced to `INFO_REQUESTED` and resubmitted back to `UNDER_REVIEW` any number of times, and ultimately reaches `APPROVED`, `DENIED`, or `PAID`. `DENIED` and `PAID` are terminal.

### 2.9. Optimistic Concurrency Control

Premium settlement is the one client-driven mutation guarded by optimistic concurrency control. A request that records premium payment against a policy must carry `expected_policy_version`, and this field is mandatory on that request — it is not optional. The server compares `expected_policy_version` against the target policy's current `version`. If another writer has advanced the policy's `version` since the client last read it, the values no longer match and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because premium settlement legitimately succeeds against a policy whose `payment_status` is still `PENDING`, two strictly sequential settlement requests carrying the same observed version cannot be distinguished by state alone; the version check is what prevents the second from re-applying a settlement the client never observed completing. No other endpoint accepts or requires a version field; only premium settlement is OCC-guarded.

### 2.10. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. Authentication comes first: a missing or malformed header yields `ERR_MISSING_AUTH` (401) before anything else. Authorization comes second: a role not permitted for the endpoint yields `ERR_FORBIDDEN` (403). Existence comes third: any unresolved path identifier or foreign key yields `ERR_NOT_FOUND` (404), validated left-to-right per §2.5. Resource ownership comes fourth: a `Traveler` acting on a policy or claim they do not own yields `ERR_NOT_RESOURCE_OWNER` (403). Request well-formedness comes fifth: a missing required field, an invalid enum value, or a negative or zero integer where the field forbids it yields `ERR_INVALID_REQUEST` (422). State admissibility comes sixth: a resource not in a state that permits the requested transition yields `ERR_INVALID_STATE` (409). The OCC check comes seventh on premium settlement: a mismatched `expected_policy_version` yields `ERR_STALE_VERSION` (412). Beyond these, the claim-approval business gates run in the order §3 specifies, with safety and eligibility gates always preceding fiscal-capacity gates.

## 3. Business Logic & Workflows

### 3.1. Configuring Plans, Travelers, and Storm References

A `CarrierAdmin` builds the catalogue that every policy draws on. A coverage **plan** is created with a `code` that must be non-empty and unique among plans (a collision is rejected with `ERR_DUPLICATE_CODE`) and a `tier` that is one of `BASIC`, `STANDARD`, or `PREMIER`. The plan fixes how premiums are priced and how each peril pays out: `base_rate_bps` is the premium base rate expressed in basis points of insured trip cost and must be at least 1; `cancellation_limit_pct` is the trip-cancellation limit as a percentage of insured trip cost, between 1 and 100 inclusive; `medical_limit_cents` is the per-policy emergency-medical aggregate limit; `delay_block_cap_cents` is the reimbursement granted per completed delay block; `delay_limit_cents` is the per-policy travel-delay limit; `baggage_item_sublimit_cents` is the per-item baggage sublimit; `baggage_limit_cents` is the per-policy baggage limit; and `baggage_depreciation_bps` is the depreciation, in basis points between 0 and 10000 inclusive, applied to each baggage item before its sublimit. The plan also fixes the time windows and loadings: `waiver_window_days` is the number of days after the initial trip deposit within which issuance grants the pre-existing-condition waiver; `free_look_days` is the free-look window in days from issuance during which a full-premium refund is available; `claim_filing_window_days` is the number of days after a loss within which a claim must be filed and must be at least 1; `cfar_loading_bps` is the Cancel-For-Any-Reason premium loading in basis points of base premium; `cfar_reimbursement_pct` is the CFAR payout percentage of insured non-refundable trip cost, between 1 and 100 inclusive; `senior_loading_bps` is the senior premium loading in basis points of base premium; and `senior_age_threshold` is the insured age at or above which the senior loading applies, which is optional on creation and defaults to 70 when omitted. Each of `base_rate_bps`, `medical_limit_cents`, `delay_block_cap_cents`, `delay_limit_cents`, `baggage_item_sublimit_cents`, `baggage_limit_cents`, `cfar_loading_bps`, and `senior_loading_bps` must be non-negative (with `base_rate_bps` at least 1). A plan is created with `status` `ACTIVE` and may later be retired, moving `status` to `RETIRED` so that no new policies cite it; the only `status` values a plan takes are `ACTIVE` and `RETIRED`. Retirement is admissible only while the plan's `status` is `ACTIVE`; retiring a plan already `RETIRED` is rejected with `ERR_INVALID_STATE`.

A traveler account is registered with an `email` that must be non-empty and unique among travelers (a duplicate is rejected with `ERR_DUPLICATE_EMAIL`), a `full_name` holding the traveler's legal name, and a `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form used to derive age. Registration is open to both a `CarrierAdmin` and a `Traveler`.

A **named storm** is declared by a `CarrierAdmin` as the cutoff reference for storm-driven cancellation claims. It carries a `name` that must be non-empty and unique among named storms (a collision is rejected with `ERR_DUPLICATE_NAME`), a `basin` that is one of `ATLANTIC`, `EAST_PACIFIC`, `WEST_PACIFIC`, or `INDIAN`, and `named_at`, the timestamp at which the storm was officially named — this timestamp is the boundary that decides whether a storm-cancellation claim is covered. A storm is born `ACTIVE` and may be marked dissipated by a `CarrierAdmin`, advancing its `status` from `ACTIVE` to `DISSIPATED`; those are the only two `status` values a storm takes. Dissipation is admissible only while the storm's `status` is `ACTIVE`; dissipating a storm already `DISSIPATED` is rejected with `ERR_INVALID_STATE`.

The carrier also drives a logical clock for test purposes. An admin-only clock capability sets the server's current UTC instant to a supplied `to_iso8601` value. Advancing the clock is consequential: any policy whose `coverage_status` is `ACTIVE` and whose `trip_end_at` is at or before the new clock instant is transitioned to `EXPIRED`, incrementing that policy's `version`.

### 3.2. Quoting a Policy and Building the Insured Roster

A policy begins as a quote. Either an `Underwriter` or the `Traveler` themselves creates one against a plan by supplying `plan_id`, `owner_traveler_id`, `trip_cost_cents` (the total insured prepaid trip cost, at least 1), `initial_deposit_at` (the timestamp of the traveler's first trip deposit, from which the waiver window is measured), `trip_start_at` and `trip_end_at` (the scheduled departure and return instants in UTC, where `trip_end_at` must be strictly later than `trip_start_at`), and an optional `cfar_opted` flag indicating whether the Cancel-For-Any-Reason rider is purchased, defaulting to `false`. The new policy is born with `coverage_status` `QUOTED` and `payment_status` `PENDING`. At quote time the system computes `base_premium_cents` and `premium_cents`; with no insured travelers yet attached, the senior loading is zero until an insured of qualifying age is added.

The premium is computed as follows. The base premium is the insured trip cost multiplied by the plan's base rate in basis points, divided by ten thousand, rounded up to the next whole cent — that is, `base_premium_cents` is the ceiling of `trip_cost_cents` times `base_rate_bps` divided by 10000. A senior loading applies when any insured traveler with `status` `COVERED` has an `age_at_departure` at or above the plan's `senior_age_threshold`; when it applies, the senior loading is the ceiling of `base_premium_cents` times `senior_loading_bps` divided by 10000, and when no covered insured meets the threshold the senior loading is zero. A CFAR loading applies when the policy has `cfar_opted` set to `true`; when it applies, the CFAR loading is the ceiling of `base_premium_cents` times `cfar_loading_bps` divided by 10000, and when CFAR was not opted the CFAR loading is zero. Each of these three terms is rounded up to a whole cent independently, and `premium_cents` is their sum: base premium plus senior loading plus CFAR loading. This quote is recomputed in full whenever the covered roster changes while the policy is still `QUOTED`.

An insured traveler is added to a `QUOTED` policy by an `Underwriter` or the owning `Traveler`. The request supplies `traveler_id` (the underlying traveler record), `age_at_departure` (the insured's age as of `trip_start_at`, non-negative, which drives the senior loading), `covered_trip_cost_cents` (the portion of trip cost attributed to this insured, non-negative), and an optional `has_preexisting_condition` flag stating whether the insured declared a pre-existing medical condition, defaulting to `false`. The created roster entry records its `policy_id`, begins with per-insured `status` `COVERED`, and triggers a full recomputation of the policy's premium (so that adding an insured at or above the senior age threshold raises `premium_cents`), incrementing the policy's `version`. Adding an insured also enforces the coverage-overlap rule of §3.7. The per-insured `status` is either `COVERED` or `REMOVED`; an insured is moved to `REMOVED` only by the cancellation cascade described in §3.5.

### 3.3. Settling Premium and Issuing Coverage

Premium settlement moves the payment axis. A request to record payment, available to an `Underwriter` or the owning `Traveler`, carries `expected_policy_version` and is admissible only while `payment_status` is `PENDING` — a policy already `PAID` or `REFUNDED` is rejected with `ERR_INVALID_STATE`. When the version check of §2.9 passes, `payment_status` advances to `PAID`, `net_premium_collected_cents` is set equal to `premium_cents`, and the policy's `version` increments. While `payment_status` is `PENDING`, `net_premium_collected_cents` is zero.

Issuance moves the coverage axis from `QUOTED` to `ACTIVE` and is performed by an `Underwriter`. Four preconditions are checked. The coverage status must be `QUOTED`, or the request is rejected with `ERR_INVALID_STATE`. The premium must already be paid — `payment_status` must be `PAID`, otherwise the request is rejected with `ERR_PREMIUM_NOT_PAID`. There must be at least one insured traveler with `status` `COVERED`, otherwise `ERR_NO_INSURED_TRAVELER`. And the sum of `covered_trip_cost_cents` across all `COVERED` insured travelers must equal the policy's `trip_cost_cents` exactly, otherwise `ERR_TRIP_COST_MISMATCH`. Issuance also re-checks the coverage-overlap rule of §3.7.

Issuance pins the policy's economics and clocks. The server sets `issued_at` to the current clock instant and computes `free_look_ends_at` as `issued_at` plus the plan's `free_look_days`. It pins `aggregate_limit_cents` and seeds the ledger: the cancellation portion of the aggregate is the floor of `trip_cost_cents` times `cancellation_limit_pct` divided by 100, and `aggregate_limit_cents` is that cancellation portion plus `medical_limit_cents` plus `delay_limit_cents` plus `baggage_limit_cents`; `remaining_aggregate_cents` is then set equal to `aggregate_limit_cents` and `amount_reimbursed_cents` to zero. Issuance computes `preexisting_waiver_granted`: it is `true` if and only if the policy was issued within the waiver window and the full trip cost is insured. Concretely, let the days-to-issue be the floor of the difference between `issued_at` and `initial_deposit_at` measured in whole days; the waiver is granted when days-to-issue is less than or equal to the plan's `waiver_window_days` **and** the sum of `covered_trip_cost_cents` across `COVERED` insured travelers equals `trip_cost_cents`. Before issuance `issued_at` and `free_look_ends_at` are null. Issuance increments the policy's `version`.

### 3.4. Filing a Claim and Assembling Its Record

Only the owning `Traveler` files a claim, and only against a policy whose `coverage_status` is `ACTIVE` — a claim filed against a non-active policy is rejected with `ERR_POLICY_NOT_ACTIVE`. The filing supplies `policy_id`, `insured_traveler_id` (the insured the claim concerns, whose `policy_id` must be the same policy the claim is filed against — an insured-traveler record belonging to a different policy is treated as unresolved and rejected with `ERR_NOT_FOUND`), `incident_at` (the loss timestamp), and `peril`, which is one of `CANCELLATION`, `MEDICAL`, `DELAY`, or `BAGGAGE`. Several inputs are conditional on the peril: `named_storm_id` cites the storm for a storm-driven cancellation and is omitted otherwise; `cancellation_reason` accompanies a `CANCELLATION` claim and is one of `COVERED_REASON`, `CFAR`, or `NAMED_STORM`; `delay_hours` is the reported delay duration in whole hours for a `DELAY` claim, non-negative and defaulting to 0; and `involves_preexisting` states whether a `MEDICAL` loss stems from a pre-existing condition, defaulting to `false`. A new claim is born `SUBMITTED`.

The filing deadline is one-sided. A claim is on time when the current clock is at or before `incident_at` plus the plan's `claim_filing_window_days`; a claim filed after that deadline is rejected with `ERR_FILING_WINDOW_CLOSED`. The window is a lateness deadline only — a claim filed at or before `incident_at` is always within it, and there is no earliest-filing gate. This same deadline is re-checked at approval (§3.6). Filing a `DELAY` claim also enforces the delay-event de-duplication rule of §3.7.

At submission the system computes a `provisional_amount_cents`, an estimate on the documented-loss basis, and the basis is peril-specific. For a cancellation claim this provisional figure sums, over each prepaid-trip expense line, the smaller of that line's `documented_amount_cents` and its `prepaid_nonrefundable_cents`, then caps the sum at the cancellation peril cap and again at the policy's `remaining_aggregate_cents`, where the cancellation peril cap is the floor of `trip_cost_cents` times the plan's `cancellation_limit_pct` divided by 100. The provisional figure for a cancellation claim deliberately ignores supplier refunds and the CFAR percentage; those enter only at approval. For a medical claim the provisional figure sums each medical-bill expense line's `documented_amount_cents` (ignoring supplier refunds), then caps the sum at the plan's `medical_limit_cents` and again at `remaining_aggregate_cents`. For a delay claim and for a baggage claim the provisional figure is computed on exactly the same basis as the final reimbursement of §3.6 — the delay-block figure (floor of `delay_hours` divided by 12, times `delay_block_cap_cents`, capped at `delay_limit_cents` then `remaining_aggregate_cents`) and the per-item depreciated-and-sublimited baggage total (capped at `baggage_limit_cents` then `remaining_aggregate_cents`) respectively. A claim of any peril other than these four has a provisional figure of zero.

A traveler builds the claim's evidentiary record by adding expense lines and documents while the claim is `SUBMITTED` or `INFO_REQUESTED`. An **expense line** records its `claim_id` and a `category` that is one of `PREPAID_TRIP`, `MEDICAL_BILL`, `BAGGAGE_ITEM`, or `DELAY_EXPENSE`, a free-text `description`, and a `documented_amount_cents` (the documented loss for the line, non-negative). Three further amounts are line-kind specific and each defaults to 0: `prepaid_nonrefundable_cents` is the non-refundable prepaid portion used for the cancellation basis; `supplier_refund_received_cents` is any refund already received from the supplier for the line, subtracted only at approval; and `item_value_cents` is the original item value before depreciation, used for the baggage basis. Each added expense line triggers a recomputation of the claim's `provisional_amount_cents`. A **document** records its `claim_id`, a `doc_type` that is one of `RECEIPT`, `MEDICAL_REPORT`, `CARRIER_DELAY_LETTER`, `POLICE_REPORT`, or `OTHER`, a `file_ref` holding an opaque storage reference, and `uploaded_by_traveler_id`, which the server fills from the uploader's `X-User-ID`.

### 3.5. Cancelling, Expiring, and the Premium-Refund Calculations

Coverage may end before a loss in three ways, and each moves the ledgers differently.

**Free-look cancellation** is a traveler's right to a full refund inside the free-look window. It is admissible only while `coverage_status` is `ACTIVE` (else `ERR_INVALID_STATE`) and only while the current clock is at or before `free_look_ends_at` (else `ERR_FREE_LOOK_EXPIRED`); it is further blocked when the policy has any claim in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `APPROVED`, or `PAID` status, in which case it is rejected with `ERR_POLICY_HAS_CLAIMS`. When it proceeds, the `coverage_status` becomes `CANCELLED` and three cascading effects fire in sequence. First, the system auto-creates a refund of `refund_type` `FREE_LOOK` for the full `premium_cents` and immediately sets that refund's `status` to `COMPLETED` — free-look refunds are auto-completed, not left for underwriter review. Second, because a completed refund now exists, the policy's `payment_status` advances to `REFUNDED` and `net_premium_collected_cents` is recomputed as `premium_cents` minus the sum of `amount_cents` across the policy's `COMPLETED` refunds. Third, every insured traveler on the policy has its per-insured `status` set to `REMOVED`. The policy's `version` increments. The full-premium free-look refund applies no admin fee and no proration: its `amount_cents` equals the policy's `premium_cents`.

**Post-free-look cancellation** is the traveler's right to a short-rate refund after the free-look window but before the trip starts. It is admissible only while `coverage_status` is `ACTIVE`; if the current clock is still at or before `free_look_ends_at`, the request is rejected with `ERR_INVALID_STATE` because free-look cancellation is the correct operation inside the window. It is rejected with `ERR_COVERAGE_PERIOD_STARTED` if the current clock is at or after `trip_start_at`, and rejected with `ERR_POLICY_HAS_CLAIMS` if the policy has any claim in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `APPROVED`, or `PAID` status. When it proceeds, `coverage_status` becomes `CANCELLED`, the policy's `version` increments, and the system auto-creates a refund of `refund_type` `SHORT_RATE` in `PENDING` status — unlike the free-look refund, the short-rate refund is left pending for an underwriter to complete or void. The short-rate refund returns the unearned portion of premium less a flat administrative fee. The coverage-period length in whole days is the difference between `trip_end_at` and `issued_at`, rounded up to whole days; the elapsed length is the difference between the current clock and `issued_at`, rounded down to whole days; the unearned premium is the floor of `premium_cents` times the quantity (coverage-period days minus elapsed days) divided by coverage-period days; and the refund `amount_cents` is the larger of zero and that unearned premium minus a flat short-rate administrative fee of 2500 cents. A `refund_type` is always one of `FREE_LOOK` or `SHORT_RATE`.

**Expiration** is automatic. When the clock is advanced (§3.1) to an instant at or after a policy's `trip_end_at` while its `coverage_status` is `ACTIVE`, the coverage transitions to `EXPIRED` and the policy's `version` increments.

A pending refund is resolved by an `Underwriter`, or by the system in the free-look cascade. **Completing** a refund is admissible only while the refund's `status` is `PENDING`, and is also rejected with `ERR_INVALID_STATE` if the policy's `payment_status` has already been driven to `REFUNDED` by a prior completed refund. On completion the refund's `status` becomes `COMPLETED`, and as a cascade the policy's `payment_status` advances to `REFUNDED` while `net_premium_collected_cents` is recomputed as `premium_cents` minus the sum of `amount_cents` across the policy's `COMPLETED` refunds; the policy's `version` increments. **Voiding** a refund is admissible only while its `status` is `PENDING` and simply sets the refund's `status` to `VOIDED` with no premium returned and no ledger movement. A refund's `status` is one of `PENDING`, `COMPLETED`, or `VOIDED`.

### 3.6. Adjudicating Claims and Computing Reimbursement

A `ClaimsAdjuster` drives a claim through review. Opening review advances a claim from `SUBMITTED` to `UNDER_REVIEW`; this is admissible only while the claim is `SUBMITTED`, else `ERR_INVALID_STATE`. From `UNDER_REVIEW` the adjuster may request more information, advancing the claim to `INFO_REQUESTED` (admissible only from `UNDER_REVIEW`). The owning `Traveler` then resubmits, advancing the claim from `INFO_REQUESTED` back to `UNDER_REVIEW`; resubmission is admissible only from `INFO_REQUESTED`, requires that at least one document exist on the claim (else `ERR_DOCUMENTATION_MISSING`), and recomputes the claim's `provisional_amount_cents` from its current expense lines. A claim may cycle between `UNDER_REVIEW` and `INFO_REQUESTED` any number of times. The adjuster may also deny a claim from `UNDER_REVIEW`, which sets `denial_reason` from the request body — a non-empty `denial_reason` string is required, and its absence is rejected with `ERR_INVALID_REQUEST` — and moves the claim to `DENIED`.

Approval is the consequential decision and runs a battery of gates in a fixed order; **the safety and eligibility gates run before any fiscal computation.** The claim must be `UNDER_REVIEW`, else `ERR_INVALID_STATE`. The policy's `coverage_status` must be `ACTIVE`, else `ERR_POLICY_NOT_ACTIVE`. The filing deadline of §3.4 is re-evaluated at approval — the current clock must be at or before `incident_at` plus the plan's `claim_filing_window_days`, else `ERR_FILING_WINDOW_CLOSED`. For a `MEDICAL` claim whose `involves_preexisting` is `true`, the policy's `preexisting_waiver_granted` must be `true`, else `ERR_PREEXISTING_NOT_WAIVED`. For a `CANCELLATION` claim whose `cancellation_reason` is `NAMED_STORM`, the policy's `issued_at` must be strictly earlier than the cited storm's `named_at` — coverage purchased on or after the storm was named does not cover that storm — else `ERR_NAMED_STORM_CUTOFF`. For a `DELAY` claim, `delay_hours` must be at least 12, else `ERR_DELAY_BELOW_THRESHOLD`. And there must be at least one document on the claim, else `ERR_DOCUMENTATION_MISSING`. When every gate passes, the system computes the final `approved_amount_cents`, sets the claim's `status` to `APPROVED`, and increments the claim's `version`.

The final reimbursement is peril-specific, and in every case it is capped at the smaller of the peril's own cap and the policy's `remaining_aggregate_cents`.

For a **cancellation** claim, the raw figure sums over each prepaid-trip expense line the larger of zero and that line's `prepaid_nonrefundable_cents` minus its `supplier_refund_received_cents`. If the `cancellation_reason` is `CFAR`, that raw figure is then reduced to the floor of itself times the plan's `cfar_reimbursement_pct` divided by 100. The `approved_amount_cents` is the smallest of the resulting figure, the cancellation peril cap (the floor of `trip_cost_cents` times `cancellation_limit_pct` divided by 100), and `remaining_aggregate_cents`. This final basis differs from the provisional basis in two ways: it subtracts each line's supplier refund, and it applies the CFAR percentage for CFAR cancellations.

For a **medical** claim, the raw figure sums over each medical-bill expense line the larger of zero and that line's `documented_amount_cents` minus its `supplier_refund_received_cents`. The `approved_amount_cents` is the smallest of that raw sum, the plan's `medical_limit_cents`, and `remaining_aggregate_cents`.

For a **delay** claim, the number of completed delay blocks is the floor of `delay_hours` divided by 12 (a claim below 12 hours is not covered and is rejected by the threshold gate above). The raw figure is the number of blocks times the plan's `delay_block_cap_cents`. The `approved_amount_cents` is the smallest of that raw figure, the plan's `delay_limit_cents`, and `remaining_aggregate_cents`.

For a **baggage** claim, the rounding order is pinned and must not be reversed. For each baggage-item expense line, first compute the depreciated value as the item's `item_value_cents` times the quantity (10000 minus the plan's `baggage_depreciation_bps`) divided by 10000, rounded half up; then cap that depreciated value at the plan's `baggage_item_sublimit_cents` to get the line's covered amount. The total is the sum of the covered amounts across all baggage-item lines — depreciation is rounded and the sublimit applied per item *before* summation, never after. The `approved_amount_cents` is the smallest of that total, the plan's `baggage_limit_cents`, and `remaining_aggregate_cents`.

### 3.7. Coverage-Overlap and Delay-Event Guards

Two temporal guards protect against double coverage and double recovery.

The **coverage-overlap guard** prevents one traveler from holding two policies covering the same trip dates. When an insured traveler is added to a policy, and again when a policy is issued, the system checks the trip-coverage interval — the half-open interval from `trip_start_at` up to but not including `trip_end_at` — against that same underlying traveler's intervals on their other policies. Any overlap is rejected with `ERR_COVERAGE_OVERLAP`. Because the interval is half-open, two trips that merely touch at an endpoint (one's `trip_end_at` equal to the next's `trip_start_at`) do not overlap and are allowed.

The **delay-event guard** prevents two delay claims from being filed for what is really one disruption. When a `DELAY` claim is filed against a policy that already has a `DELAY` claim whose covered delay window falls within a six-hour buffer of the new one, the two are treated as the same event and the second is rejected with `ERR_DELAY_EVENT_OVERLAP`. A claim's covered delay window is the closed interval from its `incident_at` to `incident_at` plus its `delay_hours` (hours). The comparison is over those windows: the new claim's window is compared, as a closed interval extended by the six-hour merge buffer, against the window of each existing `DELAY` claim on the same policy (the existing claims are considered regardless of their current status). The two are the same event — and the new claim is rejected — when, after each closed window is extended by the six-hour buffer, the two windows touch or overlap; equivalently, when the new window's start is at or before the existing window's end plus six hours and the existing window's start is at or before the new window's end plus six hours (so that windows whose gap is at most six hours merge). Windows separated by a gap greater than six hours are distinct events and the new claim is allowed.

### 3.8. Payouts, Aggregate Exhaustion, and Compensating Reversal

Once a claim is approved, a `ClaimsAdjuster` creates a **payout** for it by supplying the `claim_id`. The payout is born `PENDING`; the server copies the claim's policy onto the payout's `policy_id` for ledger reconciliation and sets the payout's `amount_cents` equal to the claim's `approved_amount_cents`. A payout cannot be created against a claim that is not `APPROVED` — that is rejected with `ERR_CLAIM_NOT_APPROVED`. A payout's `status` is one of `PENDING`, `DISBURSED`, or `REVERSED`.

**Disbursement** is admissible only while the payout is `PENDING` (else `ERR_INVALID_STATE`), only while the linked claim is `APPROVED` (else `ERR_CLAIM_NOT_APPROVED`), and only when the payout's `amount_cents` does not exceed the policy's `remaining_aggregate_cents` (else `ERR_AGGREGATE_LIMIT_EXCEEDED`). On disbursement the payout's `status` becomes `DISBURSED` and a cascade fires: the policy's `amount_reimbursed_cents` increases by the payout's `amount_cents` and `remaining_aggregate_cents` is recomputed as `aggregate_limit_cents` minus `amount_reimbursed_cents`; the linked claim's `status` advances to `PAID`; and the policy's `version` increments. If after this debit the `remaining_aggregate_cents` has reached zero, the policy's `coverage_status` transitions to `EXHAUSTED`, and that exhaustion in turn auto-denies every sibling claim on the same policy still in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED`, setting each such claim's `denial_reason` to `AGGREGATE_EXHAUSTED`, moving each to `DENIED`, and incrementing each claim's `version`.

**Reversal** is the compensating action and behaves differently depending on the payout's current state. A payout still `PENDING` may be reversed, which simply moves its `status` to `REVERSED`. A payout already `DISBURSED` may also be reversed; in that case the cascade is undone: the policy's `amount_reimbursed_cents` decreases by the payout's `amount_cents` and `remaining_aggregate_cents` is recomputed as `aggregate_limit_cents` minus `amount_reimbursed_cents`, restoring the conserved aggregate; if the policy was `EXHAUSTED` and `remaining_aggregate_cents` is now greater than zero, the `coverage_status` returns to `ACTIVE`; the linked claim's `status` returns from `PAID` to `APPROVED`; and the policy's `version` increments. Reversing a disbursed payout is admissible only while its `status` is `DISBURSED`, and reversing a pending one only while its `status` is `PENDING`; either way `REVERSED` is terminal. The auto-denial of sibling claims on exhaustion is the intended serialization point: once capacity is gone, no open claim can still be approved against it, and a later reversal that restores capacity does not resurrect already-denied claims.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions and the clock-setting capability — return `200 OK`. All endpoints honor the global validation ordering of §2.10.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (advances trigger EXPIRED transitions) | CarrierAdmin |
| POST | `/plans` | Create a coverage plan | CarrierAdmin |
| GET | `/plans/{planId}` | Get a plan | Any |
| GET | `/plans` | List plans (filter by `tier`, `status`) | Any |
| POST | `/plans/{planId}/retire` | Retire a plan | CarrierAdmin |
| POST | `/travelers` | Register a traveler account | CarrierAdmin, Traveler |
| GET | `/travelers/{travelerId}` | Get a traveler | Any |
| POST | `/named-storms` | Declare a named storm | CarrierAdmin |
| GET | `/named-storms/{stormId}` | Get a named storm | Any |
| GET | `/named-storms` | List named storms (filter by `basin`, `status`) | Any |
| POST | `/named-storms/{stormId}/dissipate` | Mark a named storm dissipated | CarrierAdmin |
| POST | `/policies` | Create a QUOTED policy | Underwriter, Traveler |
| GET | `/policies/{policyId}` | Get a policy | Any |
| GET | `/policies` | List policies (filter by `plan_id`, `owner_traveler_id`, `coverage_status`, `payment_status`) | Any |
| POST | `/policies/{policyId}/insured-travelers` | Add an insured traveler to a QUOTED policy | Underwriter, Traveler |
| GET | `/policies/{policyId}/insured-travelers` | List insured travelers on a policy | Any |
| GET | `/insured-travelers/{insuredTravelerId}` | Get an insured-traveler record | Any |
| GET | `/insured-travelers` | List insured-traveler records (filter by `policy_id`, `traveler_id`, `status`) | Any |
| POST | `/policies/{policyId}/record-payment` | Record premium payment (OCC-guarded) | Underwriter, Traveler |
| POST | `/policies/{policyId}/issue` | Issue (activate) a paid policy | Underwriter |
| POST | `/policies/{policyId}/free-look-cancel` | Free-look cancellation within the window | Traveler |
| POST | `/policies/{policyId}/cancel` | Post-free-look cancellation before trip start | Traveler |
| POST | `/claims` | File a claim against an ACTIVE policy | Traveler |
| GET | `/claims/{claimId}` | Get a claim | Any |
| GET | `/claims` | List claims (filter by `policy_id`, `insured_traveler_id`, `named_storm_id`, `peril`, `status`) | Any |
| POST | `/claims/{claimId}/expenses` | Add an expense line to a claim | Traveler |
| GET | `/claims/{id}/expenses` | List expense lines on a claim | Any |
| POST | `/claims/{claimId}/documents` | Upload a supporting document to a claim | Traveler |
| GET | `/claims/{id}/documents` | List documents on a claim | Any |
| POST | `/claims/{claimId}/start-review` | Open review (SUBMITTED → UNDER_REVIEW) | ClaimsAdjuster |
| POST | `/claims/{claimId}/request-info` | Request more info (UNDER_REVIEW → INFO_REQUESTED) | ClaimsAdjuster |
| POST | `/claims/{claimId}/resubmit` | Resubmit after info request (INFO_REQUESTED → UNDER_REVIEW) | Traveler |
| POST | `/claims/{claimId}/approve` | Approve a claim and compute final reimbursement | ClaimsAdjuster |
| POST | `/claims/{claimId}/deny` | Deny a claim under review | ClaimsAdjuster |
| POST | `/payouts` | Create a PENDING payout for an APPROVED claim | ClaimsAdjuster |
| GET | `/payouts/{payoutId}` | Get a payout | Any |
| GET | `/payouts` | List payouts (filter by `claim_id`, `policy_id`, `status`) | Any |
| POST | `/payouts/{payoutId}/disburse` | Disburse a pending payout | ClaimsAdjuster |
| POST | `/payouts/{payoutId}/reverse` | Reverse a payout (compensating) | ClaimsAdjuster |
| GET | `/refunds/{refundId}` | Get a refund | Any |
| GET | `/refunds` | List refunds (filter by `policy_id`, `refund_type`, `status`) | Any |
| POST | `/refunds/{refundId}/complete` | Complete a pending refund | Underwriter |
| POST | `/refunds/{refundId}/void` | Void a pending refund | Underwriter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_NAME` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PREMIUM_NOT_PAID` | 409 |
| `ERR_NO_INSURED_TRAVELER` | 409 |
| `ERR_TRIP_COST_MISMATCH` | 409 |
| `ERR_FREE_LOOK_EXPIRED` | 409 |
| `ERR_COVERAGE_PERIOD_STARTED` | 409 |
| `ERR_POLICY_HAS_CLAIMS` | 409 |
| `ERR_COVERAGE_OVERLAP` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_FILING_WINDOW_CLOSED` | 409 |
| `ERR_PREEXISTING_NOT_WAIVED` | 409 |
| `ERR_NAMED_STORM_CUTOFF` | 409 |
| `ERR_DELAY_BELOW_THRESHOLD` | 409 |
| `ERR_DELAY_EVENT_OVERLAP` | 409 |
| `ERR_DOCUMENTATION_MISSING` | 409 |
| `ERR_CLAIM_NOT_APPROVED` | 409 |
| `ERR_AGGREGATE_LIMIT_EXCEEDED` | 409 |
