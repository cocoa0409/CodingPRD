# Employee-Benefits Brokerage API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for an employee-benefits brokerage and consulting practice. The platform is the system of record through which a brokerage carries an employer through the full benefits lifecycle: onboarding the employer and its workforce census, marketing coverage to carriers and collecting competing quotes, binding and activating the winning policy, negotiating annual renewals across multiple rounds, running open enrollment and capturing each employee's election, discharging ACA/5500/ERISA compliance obligations, and administering wellness and stop-loss recovery. Alongside these operational flows the system maintains a set of computed reporting figures — headcounts, applicable-large-employer status, an active-premium ledger, and year-to-date commission — that must stay consistent as the underlying records move through their state machines.

The domain is inherently a multi-party negotiation layered on top of a compliance-audit discipline. Brokers, carrier representatives, compliance officers, and employer HR contacts each touch a different slice of the same client record, so the service enforces role-segregated access and a strict separation between the officer who prepares a regulatory filing and the officer who certifies it. Money is tracked exclusively in integer cents, and every derived figure is produced by a precisely specified calculation so that two conforming implementations agree to the cent. Because several records evolve concurrently — a policy can be activated, renewed, and terminated over its life — the renewal flow is guarded by optimistic concurrency control so that a stale view of a policy cannot silently open a superseding negotiation.

The remainder of this document defines the global contract (authentication, response envelope, pagination, precision, concurrency, and validation ordering), then walks the business workflows entity by entity, and finally enumerates the endpoint surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. Users and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If `X-User-Role` is missing or is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are exactly five roles:

- **`BenefitsConsultant`** — the broker/consultant. This role onboards employer clients, manages the census, runs marketing campaigns, selects winning quotes, binds and activates and terminates policies, opens and settles renewals, schedules and runs enrollment windows, finalizes commissions, and sets up stop-loss coverage. When `X-User-Role` is `BenefitsConsultant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`CarrierRep`** — a carrier representative who submits quotes and proposes counter-offers during renewal negotiation. When `X-User-Role` is `CarrierRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`ComplianceOfficer`** — prepares, certifies, and files ACA/5500/ERISA filings. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does record it — a prepare records the acting `X-User-ID` as `prepared_by_user_id`, and a certify records it as `certified_by_user_id` on the `ComplianceFiling` — but it is never compared to any entity's `id`; it is only compared against the other officer's recorded id to enforce segregation of duties.
- **`ClientContact`** — an employer HR administrator acting on behalf of their own employer. This role creates, confirms, waives, and withdraws employee elections. When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`; ownership checks compare the owning `Client` of the affected resource to `X-User-ID`. Concretely, for any election operation the server resolves the election's enrollment window and compares that window's `client_id` to `X-User-ID`; if they differ, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).
- **`PlatformAdmin`** — an operational role that drives the logical clock and has read access.

All five roles may perform every `GET` read in the system. Write access is otherwise restricted as described throughout §3 and summarized in §4.

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

List endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has no explicit upper bound. Results are always returned sorted by `created_at` in ascending order (oldest first). The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the query before pagination is applied and `has_more` is true when records remain beyond the current page.

Several list endpoints additionally accept reverse-reachability filters that narrow the result to children of a given parent. These are: `client_id` on the census-member, campaign, policy, enrollment-window, filing, and stop-loss lists; `campaign_id` on the quote list; `quote_id` (in addition to `client_id`) on the policy list; `policy_id` on the renewal list; and `window_id`, `census_member_id`, and `policy_id` on the election list. Each of these filters is optional.

### 2.4. Resource Identity, Versioning, and Timestamps

Every resource carries a server-minted `id` that is a UUID with no type prefix. Every resource also carries a `created_at` timestamp, set once at creation. All entities in this system additionally carry an `updated_at` timestamp and an integer `version`: `updated_at` is refreshed on every mutation, and `version` starts at 1 and increments by one on every mutation of that resource. All timestamps are ISO 8601 UTC values with three fractional digits.

Nested-lookup semantics apply to any path that names more than one identifier: each path identifier is validated left to right, and if any id in the path — or any foreign-key id supplied in a request body — does not reference an existing row, the request is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Every calculation that produces a monetary figure rounds its final result to a whole number of cents using round-half-up (a fractional part of exactly one-half rounds away from zero, upward). Where a calculation sums several rounded terms, each term is rounded to whole cents first and the rounded terms are then summed; the alternative of summing unrounded products and rounding once at the end is never used. Count-valued figures (headcounts and full-time-equivalent counts) are exact integers.

### 2.6. Optimistic Concurrency Control on Policies

Opening a renewal is guarded by optimistic concurrency control against the target policy. The request that opens a renewal negotiation must include a non-optional `expected_policy_version` field carrying the client's last observed `version` of the target `Policy`. If `expected_policy_version` does not equal the policy's current `version` — because another writer (for example an activation, or an earlier renewal that already moved the policy on) has advanced the policy's version since the caller last read it — the request is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). This prevents a caller from opening a renewal cycle that would supersede the prior cycle on the basis of a policy view that is already out of date. No other endpoint in the system takes a version field.

### 2.7. Validation Ordering

When more than one validation could fire on a single request, checks are evaluated in the following fixed priority order, and the first failing check determines the error returned:

1. **Authentication** — `X-User-Role` is present and is a recognized role; otherwise `ERR_UNAUTHENTICATED` (401). Applies to all requests.
2. **Authorization** — the role is permitted to perform this operation; otherwise `ERR_FORBIDDEN` (403). Applies to all requests.
3. **Ownership** — for a `ClientContact` acting on an election operation, `X-User-ID` must equal the owning `Client.id` of the resource (resolved through the election's window `client_id`); otherwise `ERR_FORBIDDEN` (403).
4. **Existence** — every id in the path exists and every body foreign-key id references an existing row; otherwise `ERR_NOT_FOUND` (404). Applies to all requests.
5. **State** — the target resource is in a state from which the requested transition is defined; otherwise `ERR_INVALID_STATE` (409). This also covers two cross-entity preconditions: opening an election requires its enrollment window to be `OPEN`, and opening a renewal requires the referenced policy to be `ACTIVE`.
6. **Concurrency** — `expected_policy_version` matches the current policy `version` on a renewal open; otherwise `ERR_STALE_POLICY_VERSION` (412).
7. **Segregation of duties** — on filing certification, the certifier's `X-User-ID` differs from `prepared_by_user_id`; otherwise `ERR_SEGREGATION_OF_DUTIES` (409).
8. **Active-coverage referential** — on filing certification, the filing's client has at least one policy with `lifecycle_status` of `ACTIVE`; otherwise `ERR_NO_ACTIVE_COVERAGE` (409).
9. **Quote referential** — on policy bind, `quote_id` references a `CarrierQuote` in `SELECTED` status belonging to a campaign of the same `client_id`; otherwise `ERR_QUOTE_NOT_SELECTED` (409).
10. **Election client consistency** — on election create, the `policy_id`, `census_member_id`, and `window_id` all belong to the same client; otherwise `ERR_CLIENT_MISMATCH` (409).
11. **Enrollment-window overlap** — a new window's half-open `[opens_at, closes_at)` interval must not overlap another window for the same client; otherwise `ERR_WINDOW_OVERLAP` (409).
12. **Coverage overlap** — activating a policy must not create a closed `[effective_date, expiration_date]` overlap with another `ACTIVE` policy for the same client and coverage line; otherwise `ERR_COVERAGE_OVERLAP` (409).
13. **Clock gating** — opening a window requires the clock to have reached `opens_at` (else `ERR_WINDOW_NOT_YET_OPEN`, 409); finalizing a window requires the clock to have reached `closes_at` (else `ERR_WINDOW_NOT_CLOSED`, 409); a filing's on-time-versus-late outcome branches on `due_date`.
14. **Field shape** — field-shape constraints hold; otherwise `ERR_INVALID_FIELD` (422).
15. **Renewal floor** — a renewal acceptance's current offer is at or above the renewal floor; otherwise `ERR_PREMIUM_BELOW_FLOOR` (409).
16. **Duplicate EIN** — a client create's `ein` is not already in use; otherwise `ERR_DUPLICATE_EIN` (409).

Field-shape constraints (priority 14, `ERR_INVALID_FIELD`, HTTP 422) are checked before the duplicate-EIN check (priority 16) and cover: a policy's `expiration_date` must be strictly after its `effective_date`; a window's `closes_at` must be strictly after its `opens_at`; a quote's `monthly_premium_cents` must be at least 1; a quote's `commission_rate_pct` must be between 0 and 1 inclusive; a client's `fiscal_year_end_month` must be between 1 and 12 inclusive; and any required field being absent is itself a field-shape violation. A `Renewal`'s `initial_offer_premium_cents` and a `StopLossPolicy`'s `attachment_point_cents` must each be at least 1.

### 2.8. Ledger Invariants and Computed Reporting

Each `Client` exposes a set of computed reporting figures that are never written directly but are always kept consistent with the underlying records. Two of these behave as conserved ledgers, maintained by paired forward and compensating adjustments as records move through their lifecycles:

- **`active_premium_total_cents`** — the sum of `monthly_premium_cents` over the client's policies whose `lifecycle_status` is `ACTIVE`. Activating a policy adds that policy's `monthly_premium_cents` to the total; terminating an active policy subtracts it; and settling a renewal as agreed recomputes the total across the client's `ACTIVE` policies (because the agreed policy's premium changes).
- **`enrolled_headcount`** — the count of the client's elections in `CONFIRMED` status across all of the client's enrollment windows. Confirming an election adds one; withdrawing a confirmed election subtracts one; and finalizing a window confirms its still-`SELECTED` elections, each of which contributes one to the count.

Two further computed figures are pure aggregations recomputed on demand: **`ytd_commission_cents`** is the sum of `finalized_commission_cents` over the client's policies whose `commission_status` is `FINALIZED`, refreshed whenever a policy's commission is finalized; and the census-derived counts described in §3.1 (`employee_count`, `full_time_equivalent_count`, `is_ale`). At client creation all computed ledgers initialize to 0 and `is_ale` initializes to false.

### 2.9. The Logical Clock

The server maintains a logical clock used for all time-dependent decisions (window open/finalize gating, filing on-time/late determination, and elapsed-month commission math). Its startup default is `2026-07-01T00:00:00Z`; before any clock-set call the clock reads exactly this default and never falls back to wall-clock time. A `PlatformAdmin` may advance or rewind the clock by supplying a `to_iso8601` instant. This capability returns no resource body.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and the Workforce Census

A `BenefitsConsultant` onboards an employer by supplying its `legal_name`, its `ein` (a nine-digit employer identification number that must be unique across all clients), its `industry` (one of `RETAIL`, `MANUFACTURING`, `TECH`, `HEALTHCARE`, or `OTHER`), and its `fiscal_year_end_month` (the month, from 1 through 12, on which the plan/fiscal year ends). A create whose `ein` duplicates an existing client's is rejected with `ERR_DUPLICATE_EIN`. On success the client's computed figures — `full_time_equivalent_count`, `employee_count`, `is_ale`, `enrolled_headcount`, `active_premium_total_cents`, and `ytd_commission_cents` — all begin at their zero/false values.

The workforce is captured as census members. Adding a member records the `client_id` of the employer they belong to, their `full_name`, their `birth_date` (an ISO 8601 date), their `annual_salary_cents`, their `monthly_contribution_cents` (the member's required monthly contribution for the lowest-cost self-only plan), and their `employment_type` (`FULL_TIME` or `PART_TIME`). Every member begins with `status` of `ACTIVE`; the only lifecycle transition is `ACTIVE → TERMINATED`, performed when the consultant terminates the member.

Two headcount figures on the client are recomputed both when a member is added and when a member is terminated. `employee_count` is the number of that client's members whose `status` is `ACTIVE`. `full_time_equivalent_count` is the number of that client's members whose `status` is `ACTIVE` and whose `employment_type` is `FULL_TIME`. The client's `is_ale` (Applicable Large Employer) flag is true exactly when `full_time_equivalent_count` is at least 50. Terminating a member sets that member's `status` to `TERMINATED`, then decrements `employee_count`, recomputes `full_time_equivalent_count` if the terminated member was `FULL_TIME`, and recomputes `is_ale` from the new full-time-equivalent count.

Each member also carries two ACA affordability flags, recomputed when the member is created and on any field update. First, a rate-of-pay threshold is computed as 9.12% (the affordability percentage, 0.0912) of one-twelfth of the member's `annual_salary_cents`, rounded half-up to whole cents; the member's `affordable_rate_of_pay` is true exactly when `monthly_contribution_cents` is less than or equal to that threshold. Second, a federal-poverty-line threshold is computed as 9.12% of one-twelfth of the fixed federal-poverty-line annual figure of 1,506,000 cents (that is, $15,060 per year), rounded half-up to whole cents; the member's `affordable_fpl` is true exactly when `monthly_contribution_cents` is less than or equal to that threshold. The two safe harbors use different denominators — one scales with the member's own salary, the other uses the fixed poverty-line figure — so a member may qualify under one and not the other.

### 3.2. Plan Marketing and Carrier Quoting

To shop coverage, a `BenefitsConsultant` starts a marketing campaign for a client, supplying the `client_id`, the `coverage_line` being marketed (`MEDICAL`, `DENTAL`, `VISION`, or `LIFE`), and a `target_effective_date` for the intended coverage. A campaign begins in `DRAFT`. Opening the campaign advances it from `DRAFT` to `OPEN`, at which point it begins accepting carrier quotes.

A `CarrierRep` submits a quote against an open campaign, supplying the `campaign_id`, the `carrier_name`, the quoted composite `monthly_premium_cents` (which must be at least 1), and the carrier-offered `commission_rate_pct` expressed as a fraction between 0 and 1 inclusive (for example, 0.04 for four percent). A submitted quote begins in `SUBMITTED`.

When the consultant selects the winning quote, that quote advances from `SUBMITTED` to `SELECTED`. Selection is only permitted while the parent campaign is `OPEN`; attempting it otherwise yields `ERR_INVALID_STATE`. Selection cascades: the parent campaign advances from `OPEN` to `CLOSED`, and every sibling quote for that same campaign still in `SUBMITTED` is moved to `DECLINED`.

### 3.3. Binding, Activating, and Terminating Policies

Once a quote is selected, the consultant binds a policy from it, supplying the holder's `client_id`, the `quote_id` of the selected quote, an `effective_date` (coverage start, inclusive), and an `expiration_date` (coverage end, inclusive, which must be strictly later than the effective date). The bind is rejected with `ERR_QUOTE_NOT_SELECTED` unless the referenced quote is in `SELECTED` status and belongs to a campaign of the same client. On bind, the policy copies its `coverage_line` from the quote's campaign and its `carrier_name` and `commission_rate_pct` from the quote; its `original_premium_cents` and its `monthly_premium_cents` are both initialized from the quote's premium (the original premium anchors the renewal floor and never changes thereafter, while the monthly premium may later move on renewal). The new policy begins with `lifecycle_status` of `BOUND`, `commission_status` of `PENDING`, `renewal_status` of `NONE`, and `finalized_commission_cents` of 0.

At bind time — and again whenever a renewal is agreed — the policy's forward-looking `estimated_commission_cents` is computed as follows. The annualized premium is the policy's current `monthly_premium_cents` multiplied by 12. A base figure is that annualized premium multiplied by the policy's `commission_rate_pct`. A volume multiplier is then chosen by tier: it is 1.10 when the annualized premium is at least 12,000,000 cents ($120,000), otherwise 1.05 when the annualized premium is at least 6,000,000 cents ($60,000), otherwise 1.00. A line multiplier is chosen by coverage line: 1.00 for `MEDICAL`, 0.90 for `DENTAL`, 0.85 for `VISION`, and 0.95 for `LIFE`. The estimated commission is the base multiplied by the volume multiplier and then by the line multiplier, rounded half-up to whole cents.

Activating a bound policy advances its `lifecycle_status` from `BOUND` to `ACTIVE`. Activation is refused with `ERR_COVERAGE_OVERLAP` if it would create a closed-interval `[effective_date, expiration_date]` overlap with another `ACTIVE` policy for the same client and the same coverage line; endpoints that merely touch (one policy's expiration equal to another's effective date) do conflict. On successful activation the policy's `monthly_premium_cents` is added to the client's `active_premium_total_cents`. Terminating an active policy advances its `lifecycle_status` from `ACTIVE` to `TERMINATED` and subtracts that policy's `monthly_premium_cents` from the client's `active_premium_total_cents`.

### 3.4. Renewal Negotiation and Rate Settlement

A renewal is opened by a `BenefitsConsultant` against an active policy, supplying the `policy_id`, the concurrency guard `expected_policy_version`, and the carrier's opening `initial_offer_premium_cents` (which must be at least 1). Opening a renewal requires the referenced policy to be in `ACTIVE` lifecycle (otherwise `ERR_INVALID_STATE`) and requires `expected_policy_version` to match the policy's current `version` (otherwise `ERR_STALE_POLICY_VERSION`, as described in §2.6). On success the renewal begins in `OPEN` status with `current_offer_premium_cents` set to the initial offer, `proposing_side` of `CARRIER`, `round_count` of 0, and `agreed_premium_cents` of 0; opening the renewal also increments the policy's `version` by one and sets the policy's `renewal_status` to `RENEWING`.

Either a `BenefitsConsultant` or a `CarrierRep` may counter with a proposed premium, supplying `proposed_premium_cents`. The first counter advances the renewal from `OPEN` to `NEGOTIATING`. From `NEGOTIATING` a further counter keeps the renewal in `NEGOTIATING` (this is the negotiation cycle, `NEGOTIATING → NEGOTIATING`), but only if the acting side is not the side that made the standing offer — a side may not counter its own current offer, and an attempt to do so is rejected with `ERR_INVALID_STATE`. Every counter sets `current_offer_premium_cents` to the proposed premium, sets `proposing_side` to the acting side (`BROKER` when the actor is the consultant, `CARRIER` when the actor is the carrier representative), and increments `round_count` by one.

The consultant settles the renewal by supplying an `action` of either `ACCEPT` or `DECLINE`; settlement is available from both `OPEN` and `NEGOTIATING`. An `ACCEPT` is permitted only when the current offer is at or above the renewal floor, which is one-half of the policy's `original_premium_cents` (the renewal-floor percentage is 0.50), rounded half-up to whole cents; when the renewal is still `OPEN` the current offer equals the initial offer. An acceptance below that floor is rejected with `ERR_PREMIUM_BELOW_FLOOR`. On acceptance the renewal advances to `AGREED`, `agreed_premium_cents` is set to the current offer, the policy's `monthly_premium_cents` is set to that agreed premium, the policy's `renewal_status` is set to `RENEWED`, the policy's `estimated_commission_cents` is recomputed from the new premium (per §3.3), and the client's `active_premium_total_cents` is recomputed across its `ACTIVE` policies. A `DECLINE` advances the renewal to `DECLINED` and resets the policy's `renewal_status` to `NONE`, leaving the policy's `monthly_premium_cents` unchanged so no premium drift occurs.

### 3.5. Commission Finalization

Separately from the forward-looking estimate, a `BenefitsConsultant` finalizes actual commission on an active policy. Finalization is only available while the policy's `lifecycle_status` is `ACTIVE`. It computes the elapsed months between the policy's `effective_date` and the logical clock as the difference in calendar years times twelve plus the difference in calendar months (clock year minus effective-date year, times twelve, plus clock month minus effective-date month), and this months-elapsed value is floored at zero so it is never negative. The `finalized_commission_cents` is then the policy's current `monthly_premium_cents` multiplied by its `commission_rate_pct`, multiplied by that months-elapsed count, multiplied by the coverage-line multiplier (1.00 for `MEDICAL`, 0.90 for `DENTAL`, 0.85 for `VISION`, 0.95 for `LIFE`), rounded half-up to whole cents. Unlike the estimate, the finalized figure applies no volume-tier multiplier, so the two figures diverge for the same policy. Finalization advances `commission_status` from `PENDING` to `FINALIZED` and then recomputes the client's `ytd_commission_cents` as the sum of `finalized_commission_cents` over that client's policies whose `commission_status` is `FINALIZED`. Until a policy is finalized its `finalized_commission_cents` remains 0.

### 3.6. Open Enrollment and Employee Elections

A `BenefitsConsultant` schedules an open-enrollment window for a client, supplying the `client_id`, the `plan_year` (for example, 2027), and the window bounds `opens_at` (inclusive) and `closes_at` (exclusive, which must be strictly later than `opens_at`). A new window's half-open `[opens_at, closes_at)` interval must not overlap any existing window for the same client; a create that would overlap is rejected with `ERR_WINDOW_OVERLAP`, though adjacency — one window's `closes_at` equal to another's `opens_at` — is allowed. A window begins in `SCHEDULED`.

Opening the window advances it from `SCHEDULED` to `OPEN` and requires the logical clock to have reached `opens_at`; an attempt before that instant is rejected with `ERR_WINDOW_NOT_YET_OPEN`. While the window is `OPEN`, a `ClientContact` acting for the owning client enters elections. Creating an election records the `window_id`, the `census_member_id` of the electing member, the `policy_id` of the elected policy, and the `coverage_tier` (`EMPLOYEE_ONLY`, `EMPLOYEE_SPOUSE`, `EMPLOYEE_CHILD`, or `FAMILY`). An election may only be created while its window is `OPEN` (otherwise `ERR_INVALID_STATE`), and its window, member, and policy must all belong to the same client (otherwise `ERR_CLIENT_MISMATCH`). A new election begins in `SELECTED`.

The contact then either confirms or waives each selected election, or later withdraws a confirmed one. Confirming an election advances it from `SELECTED` to `CONFIRMED`; confirmation requires the parent window to be `OPEN` and the referenced policy to be in `ACTIVE` lifecycle (either failing precondition yields `ERR_INVALID_STATE`). On confirmation, the election's `monthly_cost_cents` is computed as the policy's `monthly_premium_cents` multiplied by the tier factor for the chosen tier — 1.00 for `EMPLOYEE_ONLY`, 2.00 for `EMPLOYEE_SPOUSE`, 1.75 for `EMPLOYEE_CHILD`, and 2.85 for `FAMILY` — rounded half-up to whole cents, and the client's `enrolled_headcount` is increased by one. Waiving an election advances it from `SELECTED` to `WAIVED` and requires the parent window to be `OPEN`; a waive makes no change to the client's `enrolled_headcount`. Withdrawing a confirmed election advances it from `CONFIRMED` to `WITHDRAWN` and decreases the client's `enrolled_headcount` by one.

Finalizing the window advances it from `OPEN` to `FINALIZED` and requires the logical clock to have reached `closes_at`; an attempt before that instant is rejected with `ERR_WINDOW_NOT_CLOSED`. Finalization confirms every election for that window still in `SELECTED` (moving each to `CONFIRMED`), and each such newly confirmed election increments the client's `enrolled_headcount` by one. The window's `total_confirmed_cents` is then computed by rounding each confirmed election's cost (policy monthly premium times its tier factor) to whole cents and summing those rounded per-election amounts; the per-election rounding always precedes the summation.

### 3.7. Compliance Filings and Segregation of Duties

A `ComplianceOfficer` opens a compliance filing for a client, supplying the `client_id`, the `filing_type` (`ACA_1094C`, `FORM_5500`, or `ERISA_SPD`), the `plan_year` the filing covers, and the regulatory `due_date`. A filing begins in `DRAFT`, with `prepared_by_user_id` and `certified_by_user_id` both null.

Preparing the filing advances it from `DRAFT` to `PREPARED` and records the acting officer's `X-User-ID` as `prepared_by_user_id`. Certifying it advances it from `PREPARED` to `CERTIFIED` and records the acting officer's `X-User-ID` as `certified_by_user_id`, subject to two guards. First, segregation of duties: the certifying officer's `X-User-ID` must differ from the `prepared_by_user_id`; if the same officer who prepared the filing attempts to certify it, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, active-coverage referential integrity: the filing's client must have at least one policy whose `lifecycle_status` is `ACTIVE`; otherwise the request is rejected with `ERR_NO_ACTIVE_COVERAGE`.

Filing a certified filing branches on the clock against the filing's `due_date`: the same file action advances the filing to `FILED` when the logical clock is at or before the due date (recorded on time), and to `LATE` when the logical clock is past the due date (recorded late). Both `FILED` and `LATE` are terminal.

### 3.8. Wellness and Stop-Loss Recovery

A `BenefitsConsultant` sets up a wellness/stop-loss policy for a self-funded client, supplying the `client_id`, the specific `attachment_point_cents` (the stop-loss deductible, at least 1, above which reimbursement begins), the `aggregate_limit_cents` used for reporting, and the `wellness_credit_pct` (a fraction between 0 and 1 inclusive, for example 0.05). The policy's `cumulative_claims_cents` starts at 0.

Recording a claim supplies a `claim_amount_cents`, which is added to the running `cumulative_claims_cents`. The service then recomputes three figures. The `reimbursed_cents` is the greater of zero and the cumulative claims minus the attachment point; the attachment threshold is strict, so cumulative claims exactly equal to the attachment point yield zero reimbursement, and reimbursement accrues only on the excess strictly above it. The `wellness_credit_cents` is the wellness-credit fraction multiplied by the cumulative claims, rounded half-up to whole cents. The `total_recovery_cents` is the sum of `reimbursed_cents` and `wellness_credit_cents`.

## 4. Endpoint Definitions

New-resource creation endpoints return HTTP 201; state-transition and other modification endpoints return HTTP 200; reads return HTTP 200. All request and response bodies follow the envelope of §2.2; the request payloads and side effects for each operation are described in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/clients` | Onboard an employer client | BenefitsConsultant |
| GET | `/clients/{id}` | Read a client with computed reporting ledgers | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/clients` | List clients | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/census-members` | Add a census member | BenefitsConsultant |
| GET | `/census-members/{id}` | Read a census member | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/census-members` | List census members | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/census-members/{id}/terminate` | Terminate a census member | BenefitsConsultant |
| POST | `/campaigns` | Start a plan-marketing campaign | BenefitsConsultant |
| GET | `/campaigns/{id}` | Read a campaign | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/campaigns` | List campaigns | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/campaigns/{id}/open` | Open a campaign for carrier quotes | BenefitsConsultant |
| POST | `/quotes` | Carrier submits a quote | CarrierRep |
| GET | `/quotes/{id}` | Read a quote | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/quotes` | List quotes | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/quotes/{id}/select` | Broker selects the winning quote | BenefitsConsultant |
| POST | `/policies` | Bind a policy from a SELECTED quote | BenefitsConsultant |
| GET | `/policies/{id}` | Read a policy | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/policies` | List policies | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/policies/{id}/activate` | Activate a bound policy | BenefitsConsultant |
| POST | `/policies/{id}/terminate` | Terminate an active policy | BenefitsConsultant |
| POST | `/policies/{id}/finalize-commission` | Finalize commission for an active policy | BenefitsConsultant |
| POST | `/renewals` | Open a renewal negotiation on an active policy | BenefitsConsultant |
| GET | `/renewals/{id}` | Read a renewal | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/renewals` | List renewals | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/renewals/{id}/counter` | Either side proposes a new premium | BenefitsConsultant, CarrierRep |
| POST | `/renewals/{id}/settle` | Broker accepts or declines the current offer | BenefitsConsultant |
| POST | `/enrollment-windows` | Schedule an open-enrollment window | BenefitsConsultant |
| GET | `/enrollment-windows/{id}` | Read a window | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/enrollment-windows` | List windows | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/enrollment-windows/{id}/open` | Open the window (clock-gated) | BenefitsConsultant |
| POST | `/enrollment-windows/{id}/finalize` | Finalize the window; confirm selected elections | BenefitsConsultant |
| POST | `/elections` | Member elects a policy during enrollment | ClientContact |
| GET | `/elections/{id}` | Read an election | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/elections` | List elections | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/elections/{id}/confirm` | Confirm an election | ClientContact |
| POST | `/elections/{id}/waive` | Waive an election | ClientContact |
| POST | `/elections/{id}/withdraw` | Withdraw a confirmed election | ClientContact |
| POST | `/filings` | Open a compliance filing | ComplianceOfficer |
| GET | `/filings/{id}` | Read a filing | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/filings` | List filings | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/filings/{id}/prepare` | Prepare a filing | ComplianceOfficer |
| POST | `/filings/{id}/certify` | Certify a prepared filing | ComplianceOfficer |
| POST | `/filings/{id}/file` | File a certified filing | ComplianceOfficer |
| POST | `/stop-loss-policies` | Set up a wellness/stop-loss policy | BenefitsConsultant |
| GET | `/stop-loss-policies/{id}` | Read a stop-loss policy | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| GET | `/stop-loss-policies` | List stop-loss policies | BenefitsConsultant, CarrierRep, ComplianceOfficer, ClientContact, PlatformAdmin |
| POST | `/stop-loss-policies/{id}/record-claim` | Record a claim; recompute reimbursement | BenefitsConsultant |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_POLICY_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_NO_ACTIVE_COVERAGE` | 409 |
| `ERR_QUOTE_NOT_SELECTED` | 409 |
| `ERR_CLIENT_MISMATCH` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_COVERAGE_OVERLAP` | 409 |
| `ERR_WINDOW_NOT_YET_OPEN` | 409 |
| `ERR_WINDOW_NOT_CLOSED` | 409 |
| `ERR_PREMIUM_BELOW_FLOOR` | 409 |
| `ERR_INVALID_FIELD` | 422 |
| `ERR_DUPLICATE_EIN` | 409 |
