# Energy Supplier Brokerage API — Product Requirements Document

## 1. Introduction

In deregulated energy markets, a business or household may buy its electricity or gas supply from a competitive supplier rather than accepting the incumbent utility's default rate. Navigating that choice is hard: customers must authorize a broker to pull their usage history, suppliers must be invited to bid, offers must be compared on an apples-to-apples basis, and the resulting contract must survive utility enrollment, ongoing rate monitoring, and eventual renewal. This document specifies the API for an energy-supplier brokerage that intermediates the entire journey — from account onboarding and letter-of-authorization (LOA) signing, through a competitive request-for-proposal (RFP) solicitation, supplier quoting, award, customer acceptance, manager approval, and utility switch, all the way to commission accounting and demand-response participation.

The platform is fundamentally a **multi-party negotiation** engine wrapped around a **commission ledger**. A broker agent runs a solicitation; suppliers submit competing quotes; the agent shortlists and awards; a customer accepts; a manager approves within a fiscal limit; operations submits the switch to the utility and later confirms it. Every awarded deal accrues an estimated commission that is later reconciled ("trued-up") against metered actual usage, with a strict four-eyes segregation-of-duties control separating the manager who approves a commission from the one who trues it up. A logical clock drives all time-dependent behavior — LOA and contract expiry, renewal windows, and market-rate alerts — so that the system is fully deterministic and testable.

This specification is the single source of truth for implementers. It defines the resource model, the state machines that govern each entity's lifecycle, the calculation rules for commissions and incentives, the validation and authorization rules, and the complete endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles, spelled precisely as follows: `BrokerAgent`, `BrokerManager`, `Supplier`, `Customer`, and `OpsAdmin`.

Four of these roles are **entity-backed**, meaning `X-User-ID` must be the `id` of an existing persisted entity of the corresponding type, and ownership checks compare a resource's foreign-key field against that id:

- When `X-User-Role` is `BrokerAgent`, `X-User-ID` is the `id` of the acting `BrokerUser` (a staff member whose `staff_role` is `AGENT`); ownership checks on any resource that references a broker user compare the resource's `broker_agent_id` to `X-User-ID`.
- When `X-User-Role` is `BrokerManager`, `X-User-ID` is likewise the `id` of the acting `BrokerUser` (whose `staff_role` is `MANAGER`); the manager's own `approval_limit_cents` governs how large a commission that manager may approve.
- When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on a quote compare the quote's `supplier_id` to `X-User-ID`, so a supplier may withdraw only its own quote.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership of any account-bound resource is established by comparing the referenced `UtilityAccount`'s `customer_id` to `X-User-ID`. A customer may sign or revoke an LOA, or accept or reject a contract, only on an account they own; otherwise the request is rejected with `ERR_FORBIDDEN`.

The fifth role is **opaque**: when `X-User-Role` is `OpsAdmin`, `X-User-ID` is a back-office operator identifier that is not tied to any persisted entity. The server accepts it as an operational credential (utility-EDI proxy, market-data feed, scheduler, clock) but does not compare it to any entity's `id`.

For an entity-backed role, if `X-User-ID` does not correspond to an existing entity of the expected type, the request is treated as forbidden and rejected with `ERR_FORBIDDEN`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; a supplied value outside that range is clamped or rejected as a malformed request per the validation rules. The `offset` defaults to 0 and represents the number of leading records to skip. List results are always ordered by `created_at` in ascending order (oldest first) before pagination is applied. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of records matching the filter before pagination and `has_more` is true when records remain beyond the returned page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` — an opaque UUID with no type prefix — at creation time. Most resources also carry three common bookkeeping fields: `created_at`, an ISO 8601 UTC timestamp (three fractional digits) fixed at creation; `updated_at`, refreshed to the current logical instant on every mutation; and `version`, an integer that starts at 1 and increments by 1 on each mutation that changes the resource. The `Customer`, `BrokerUser`, `Supplier`, `UtilityAccount`, `Authorization`, `Rfp`, `Quote`, `Contract`, `CommissionStatement`, and `DemandResponseEnrollment` resources all carry these common fields.

The lone exception is `UsageRecord`, which is an immutable append-only fact: it carries only `id` and `created_at`. It has neither `updated_at` nor `version`, and it is never mutated after import.

Timestamps written by the system — such as an LOA's `signed_at`, a contract's `confirmed_switch_date`, or any expiry — are always drawn from the **logical clock** described in §2.8, never from wall-clock time.

### 2.5. Monetary Units, Precision, and Rounding

All money is expressed in whole integer **cents**; the API never emits fractional cents. Energy rates are expressed in **mills per kilowatt-hour**, where one mill is one-tenth of a cent (that is, $0.001). Because one mill applied to one kWh yields one-tenth of a cent, converting a mills-times-kWh product into cents requires dividing by ten; this divisor is fixed at 10 throughout the platform.

Wherever a calculation produces a non-integer cent amount, the result is rounded to whole cents using **round-half-up** (a value exactly halfway between two integers rounds up to the larger magnitude). Where a formula specifies an intermediate rounding step, that rounding is applied at the stated point and in the stated order — never deferred or reordered — because commission true-up in particular is sensitive to whether rounding happens before or after summation (see §3.5). Kilowatt quantities and their derived reserved-capacity sums are exact integers.

### 2.6. Request Validation Order and Error Precedence

When a single request could fail multiple checks, the checks are evaluated in a fixed priority order and the **first** failing check determines the error returned. Lower-numbered checks strictly precede higher-numbered ones:

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers must be present and well-formed, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization.** The role must be permitted for the endpoint per §2.1, and for an entity-backed role `X-User-ID` must resolve to an existing entity of that type and satisfy ownership; otherwise `ERR_FORBIDDEN` (HTTP 403).
3. **Existence.** All resources referenced by the path and body must exist, validated left-to-right in path order, else `ERR_NOT_FOUND` (HTTP 404).
4. **Well-formedness.** For any write, the body must have all required fields present, valid enum values, non-negative integers where integers are expected, and parseable dates, else `ERR_VALIDATION` (HTTP 422).
5. **State.** For a transition endpoint, the target resource must currently be in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409).
6. **Referential coherence.** Cross-entity linkage must be consistent (for example, at award the selected quote's RFP must belong to the named account, and a commission statement's contract linkage must match), else `ERR_REFERENTIAL_MISMATCH` (HTTP 409).
7. **Concurrency.** On quote submission the supplied RFP version must match the current one, else `ERR_STALE_RFP_VERSION` (HTTP 412) — see §2.7.
8. **Cross-entity state dependency.** Preconditions on related entities (account verified, LOA scope, supplier active, account enrolled) must hold, else the specific dependency error (HTTP 409).
9. **Segregation of duties.** The four-eyes control on commission true-up, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).
10. **Temporal windows.** Deadline, overlap, buffer, and renewal-window checks, else the specific temporal error (HTTP 409).
11. **Fiscal floors and ceilings.** Margin minimums, approval limits, and eligible-candidate checks, else the specific fiscal error (HTTP 409).

The specific trigger conditions for each error live in the workflow narratives of §3; this ladder governs only which of several simultaneous failures surfaces.

### 2.7. Optimistic Concurrency on RFP Rounds

An RFP's `version` is the concurrency token that tells a supplier whether the bidding round it priced against is still current. Several actions bump `version`: moving the RFP from `OPEN` to `BEST_AND_FINAL`, re-opening it from `BEST_AND_FINAL` back to `OPEN`, and every successful quote submission against it. Consequently, when a supplier submits a quote it must include `expected_rfp_version` carrying the RFP `version` the supplier last observed. If that value does not equal the RFP's current `version` — because the round advanced, the RFP re-opened, or another supplier's quote arrived in the interim — the submission is rejected with `ERR_STALE_RFP_VERSION` (HTTP 412), signalling that the supplier priced against a round that has since moved on and must re-read the RFP before bidding. A strictly sequential re-submission that carries the now-current `version` is a legitimate supersede of the supplier's own earlier quote and succeeds. This version field is required only on quote submission; no other endpoint accepts a version token.

### 2.8. The Logical Clock and Cascading State Propagation

The platform keeps a single **logical clock** that governs every time-dependent decision. On server startup the clock reads exactly `2026-05-01T00:00:00Z`; until it is explicitly set it never advances on its own and never reads wall-clock time. An operator may advance it to drive time-sensitive scenarios, and a separate scheduled-sweep capability reads it to expire LOAs and contracts, open renewal windows, and raise rate alerts.

Several operations trigger **cascades** that mutate more than one entity in a single request; each such secondary mutation refreshes the affected resource's `updated_at` and bumps its `version`. The two principal cascade chains are the LOA-revocation chain (a revoked or expired LOA can suspend an account, which in turn cancels the account's open solicitations and voids their live quotes) and the supplier-suspension chain (suspending a supplier withdraws its live quotes, which can revert a best-and-final RFP to open). These chains are specified in full where they are triggered, in §3.1, §3.2, and §3.6.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Customers, Staff, Suppliers, Accounts, and Authorizations

The brokerage's directory is seeded by three registration flows. A customer is registered with a `legal_name`, a contact `email`, a market `segment` (one of `RESIDENTIAL`, `SMALL_COMMERCIAL`, or `LARGE_COMMERCIAL`), and a `service_state` two-letter code; a newly registered customer begins with `status` `ACTIVE` and may later become `INACTIVE`. Broker staff are created by operations with a `full_name`, `email`, and a `staff_role` of either `AGENT` or `MANAGER`; a manager also carries an `approval_limit_cents` capping the commission size they may approve, and if that field is omitted it defaults to 0 (the appropriate value for an agent, who approves nothing). Each broker user additionally exposes a computed `pipeline_commission_cents` for reporting, described in §3.5. Suppliers are registered by operations with a `name`, a `commodity` of `ELECTRICITY` or `GAS`, and a `service_states` array of the two-letter state codes they are licensed in; a supplier starts `ACTIVE`.

A **utility account** is the anchor for all downstream activity. An agent creates one by supplying the owning `customer_id`, the owning `broker_agent_id`, the `utility_name`, the `account_number`, the `commodity`, the `state_code`, and the broker's `estimated_annual_usage_kwh`. A new account opens in `status` `PENDING_LOA` with its computed `reserved_dr_kw` at 0. Account numbers must be unique per utility: if the supplied `account_number` already exists under the same `utility_name`, creation is rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER`.

Before the broker may act on an account, the customer must grant a **letter of authorization**. An agent drafts an LOA against a target `account_id` with a `scope` of either `USAGE_ONLY` (permission to pull usage only) or `USAGE_AND_ENROLL` (permission to pull usage and to enroll the account with a supplier), plus an `expires_at` instant after which the authorization is no longer valid; the `expires_at` must lie in the future relative to the logical clock at draft time, else the request is rejected with `ERR_VALIDATION`. A freshly drafted LOA is in `DRAFT`. The owning customer then signs it, moving `DRAFT → SIGNED`; signing requires that the acting customer owns the referenced account (else `ERR_FORBIDDEN`) and that `expires_at` is strictly after the current logical clock (else `ERR_VALIDATION`), and it stamps `signed_at` with the current clock instant.

A signed LOA may later be revoked by the owning customer, moving `SIGNED → REVOKED`. Revocation opens the platform's most far-reaching cascade: the referenced account transitions to `SUSPENDED` (unless it is already in a terminal state), and that account suspension in turn cancels every one of the account's RFPs still in `DRAFT`, `OPEN`, or `BEST_AND_FINAL` (moving each to `CANCELLED`), and each such cancellation voids that RFP's quotes still in `SUBMITTED` or `SHORTLISTED` (moving each to `VOID`). Every entity touched along this chain has its `updated_at` and `version` refreshed.

Usage data is imported one month at a time. A usage record names its `account_id`, the `period_month` (a `YYYY-MM` string), the metered `usage_kwh`, an optional `source` of `UTILITY_EDI` or `BROKER_ESTIMATE` (defaulting to `UTILITY_EDI`), and an optional `is_actual` boolean (defaulting to true) that marks whether the row is a true metered actual eligible for commission true-up or merely an estimate. Usage records are immutable once written.

With a signed LOA and at least one usage record in hand, an agent **verifies** the account, moving it `PENDING_LOA → VERIFIED`. Verification requires that a `SIGNED`, non-expired `Authorization` exists for the account (else `ERR_LOA_NOT_SIGNED`) and that at least one `UsageRecord` exists for it (else `ERR_NO_USAGE_DATA`). An account later becomes `ENROLLED` automatically when one of its contracts goes live (§3.4), and it can be forced to `SUSPENDED` by the revocation or expiry cascades. `SUSPENDED` is terminal.

### 3.2. Solicitation: RFPs, Supplier Quotes, and the Bidding Cycle

To shop an account's supply, an agent drafts a **request for proposal** naming the `account_id`, the running `broker_agent_id`, the `term_months_requested`, an optional `green_pct_requested` renewable-content target from 0 to 100 (defaulting to 0), and a `due_at` bid deadline. A new RFP opens in `DRAFT` with `version` 1.

RFP advancement is driven by a single `action` field whose value is one of `OPEN`, `BEST_AND_FINAL`, `REOPEN`, or `CANCEL`. Opening the RFP for bidding (action `OPEN`) advances it `DRAFT → OPEN`, but only once the account is ready: the referenced account must be `VERIFIED` (else `ERR_ACCOUNT_NOT_VERIFIED`) and a `SIGNED` authorization whose `scope` is `USAGE_AND_ENROLL` must exist for the account (else `ERR_LOA_SCOPE_INSUFFICIENT`). A `USAGE_ONLY` LOA is insufficient to open a solicitation. Once open, the RFP accepts quotes.

A supplier bids by submitting a quote that names the target `rfp_id`, the supplier's own `supplier_id`, the offered `rate_mills_per_kwh`, the offered `term_months`, an optional `green_pct` (defaulting to 0), the `broker_adder_mills` margin the broker earns on top of the supplier rate, and the `expected_rfp_version` concurrency token. A quote submitted at or after the RFP's `due_at` is rejected with `ERR_RFP_CLOSED`. The offered `broker_adder_mills` must be at least the platform minimum of 2 mills, else the submission is rejected with `ERR_MARGIN_BELOW_MIN` — this floor is enforced both here at submission and again at contract approval. A quote begins in `SUBMITTED`, and each successful submission bumps the parent RFP's `version` by 1, which is precisely why the stale-version check of §2.7 protects the round.

An agent curates the field by **shortlisting** promising quotes, advancing each `SUBMITTED → SHORTLISTED`; shortlisting is permitted only while the parent RFP is in `OPEN` or `BEST_AND_FINAL`, else `ERR_INVALID_STATE`. When the agent is ready to tighten the competition, moving the RFP `OPEN → BEST_AND_FINAL` demands a best-and-final round; this requires at least one quote already in `SUBMITTED` or `SHORTLISTED` (else `ERR_NO_QUOTES`) and bumps the RFP `version`, staling every supplier's prior view. The RFP may then cycle back the other way, `BEST_AND_FINAL → OPEN`, to invite yet another round — a re-open that again bumps `version`. An agent may also cancel a solicitation outright, moving it to `CANCELLED` from either `OPEN` or `BEST_AND_FINAL`; cancellation voids every quote on that RFP still in `SUBMITTED` or `SHORTLISTED`.

A supplier may withdraw its own quote (verified by comparing the quote's `supplier_id` to the acting supplier, else `ERR_FORBIDDEN`). A `SUBMITTED` quote simply becomes `WITHDRAWN`. A `SHORTLISTED` quote also becomes `WITHDRAWN`, but with a twist: if that shortlisted quote was the anchor of a `BEST_AND_FINAL` RFP, its departure reverts that RFP `BEST_AND_FINAL → OPEN` so the round can be rebuilt. This same shortlisted-withdrawal reversion fires when a quote is withdrawn by the supplier-suspension cascade: suspending a supplier (§3.6) withdraws all of that supplier's quotes still in `SUBMITTED` or `SHORTLISTED`, and any such withdrawal of a shortlisted quote on a best-and-final RFP reverts that RFP to `OPEN`.

### 3.3. Award, Customer Decision, and Manager Approval

When the agent decides a winner, the award request names the `rfp_id` and the `account_id`, together with the `estimated_annual_usage_kwh` to pin as the commission basis, the `start_date` of the supply period, and the `requested_switch_date` to submit to the utility. The **server itself selects the winning quote** — the client does not name it. Before any winner selection the server first verifies the RFP is in an awardable state — namely `OPEN` or `BEST_AND_FINAL` — else the award fails with `ERR_INVALID_STATE`; per §2.6 this state check precedes the referential-coherence and eligible-candidate checks described below. The candidate set is every quote on that RFP currently in `SHORTLISTED`; if that set is empty the award fails with `ERR_NO_ELIGIBLE_QUOTES`. Among candidates the server computes each quote's all-in rate as its `rate_mills_per_kwh` plus its `broker_adder_mills`, and picks the lowest all-in rate. Ties are broken first by the lower `broker_adder_mills`, and if still tied by the earlier `created_at` (never by `id`); the first quote after this ordering wins. The award also checks referential coherence: the selected quote's RFP must belong to the named account, else `ERR_REFERENTIAL_MISMATCH`.

On a successful award a new **contract** is created in `PENDING_CUSTOMER`. The server copies the winning quote's `quote_id`, `supplier_id`, `term_months`, `rate_mills_per_kwh`, and `broker_adder_mills` onto the contract, sets `broker_agent_id` from the RFP that produced the quote, and copies the winning quote's `green_pct`. It computes `end_date` as the `start_date` advanced by `term_months` calendar months (an exclusive upper bound), leaves `confirmed_switch_date` null for now, and initializes `rec_adder_mills` at 0, `renewal_window_open` false, and `rate_alert` `NONE`. The winning quote transitions `SHORTLISTED → AWARDED`, and its RFP transitions to `AWARDED` (from either `OPEN` or `BEST_AND_FINAL`). A contract may also carry a `renewed_from_contract_id`, which is null for a contract born of a fresh award and set only on a renewal successor (§3.7). The contract's `latest_market_rate_mills` reflects the most recent market rate recorded for its commodity and state (§3.7).

The owning customer then renders a `decision` of either `ACCEPT` or `REJECT`. Accepting advances the contract `PENDING_CUSTOMER → PENDING_APPROVAL` (the acting customer must own the contract's account, else `ERR_FORBIDDEN`). Rejecting advances it `PENDING_CUSTOMER → REJECTED` and unwinds the award: the winning quote reverts `AWARDED → VOID` and its RFP reverts `AWARDED → BEST_AND_FINAL`, making the solicitation re-openable for a fresh award.

A manager then **approves** an accepted contract, advancing it `PENDING_APPROVAL → APPROVED`, subject to three fiscal and dependency checks. The winning quote's supplier must currently be `ACTIVE` (else `ERR_SUPPLIER_NOT_ACTIVE`); the contract's `broker_adder_mills` must again be at least the 2-mill minimum (else `ERR_MARGIN_BELOW_MIN`); and the estimated gross commission the deal would generate — computed by the estimated-commission rule of §3.5 from the pinned `estimated_annual_usage_kwh`, `broker_adder_mills`, and `term_months` — must not exceed the acting manager's own `approval_limit_cents` (else `ERR_APPROVAL_LIMIT_EXCEEDED`).

Before a contract is active, an agent may attach a **green/REC rider** to raise its renewable content. Doing so sets the contract's `rec_adder_mills` from the request and raises its effective `green_pct` to 100. This capability is available only while the contract is in `PENDING_APPROVAL` or `APPROVED`; attempting it in any other state yields `ERR_INVALID_STATE`.

### 3.4. Enrollment, the Switch, and the Supply Window

Once approved, an agent **submits the enrollment** to the utility, advancing the contract `APPROVED → ENROLLMENT_SUBMITTED` and pinning its `requested_switch_date`. This step guards against double-supplying an account: the new contract's supply interval, running from its `start_date` inclusive to its `end_date` exclusive, may not overlap the interval of any other contract on the same account that is currently `APPROVED`, `ENROLLMENT_SUBMITTED`, or `ACTIVE`. Because the interval is half-open, exact adjacency — where one contract's `start_date` equals another's `end_date` — is permitted; any true overlap is rejected with `ERR_CONTRACT_OVERLAP`. Submitting the enrollment also creates the contract's provisional commission statement, as detailed in §3.5.

Operations then posts the utility's result. Confirming advances the contract `ENROLLMENT_SUBMITTED → ACTIVE`, sets `confirmed_switch_date` to the current logical clock, and moves the account `VERIFIED → ENROLLED` — the moment the account is considered live on a competitive supply. Rejecting advances the contract `ENROLLMENT_SUBMITTED → DROPPED` and triggers the commission compensation of §3.5. The `result` field carries the utility's verdict, which is either `CONFIRM` or `REJECT`.

The **supply window** rule derives and maintains three time-sensitive properties on every contract. The `end_date` is always the `start_date` plus `term_months` calendar months, treated as an exclusive upper bound. The `renewal_window_open` flag is true exactly when the gap from the current logical clock to `end_date` is 60 days or fewer, with the boundary inclusive (at exactly 60 days out, the window is open). The `rate_alert` is set to `RATE_DROP` when a market rate has been observed for the contract's commodity and state (its `latest_market_rate_mills` is not null) and that observed rate is strictly below the contract's `rate_mills_per_kwh` reduced by 10 percent — that is, below the contract rate multiplied by nine-tenths and rounded half-up to a whole mill; otherwise `rate_alert` is `NONE`. These properties are (re)evaluated by the scheduled sweep of §3.7. An `ACTIVE` contract whose `end_date` the clock has reached or passed is expired by the sweep, moving it `ACTIVE → EXPIRED`.

### 3.5. The Commission Ledger: Estimation, Approval, and True-Up

Commission accounting is the platform's ledger backbone, and it is governed by a **forward-and-compensation invariant**: submitting an enrollment creates a provisional commission liability, and a subsequent utility rejection must exactly reverse it.

When a contract moves `APPROVED → ENROLLMENT_SUBMITTED`, the system creates a `CommissionStatement` in `PROVISIONAL` state with `basis` `ESTIMATED`, naming the parent `contract_id`. Its `gross_commission_cents` is computed by the **estimated-commission** rule and pinned at creation. That rule works in three steps. First, a base amount in cents is the contract's pinned `estimated_annual_usage_kwh` multiplied by its `broker_adder_mills`, divided by ten, rounded half-up. Second, a term multiplier is chosen from the requested term: it is 1.00 when `term_months` is 12 or fewer, 1.10 when `term_months` is between 13 and 24 inclusive, and 1.20 when `term_months` is 25 or more; the base amount is multiplied by this multiplier and rounded half-up to whole cents. Third, that tiered amount is clamped to lie between a floor of 5,000 cents ($50) and a ceiling of 5,000,000 cents ($50,000), taking the larger of the floor and the tiered amount, then the smaller of that and the ceiling — the multiplier is applied before the clamp. The resulting figure is the `gross_commission_cents`, and while the statement remains provisional or approved the `net_commission_cents` equals that gross. Creating the statement raises the brokering agent's `pipeline_commission_cents` by that amount. A statement's `actual_gross_cents`, `true_up_delta_cents`, and `settled` reconciliation figures remain null until true-up; its `clawback_cents` starts at 0. The `approved_by_manager_id` and `trued_up_by_manager_id` audit fields are unset until their respective steps.

If the utility later rejects the enrollment (contract `ENROLLMENT_SUBMITTED → DROPPED`), the **compensation** fires: the contract's provisional statement transitions `PROVISIONAL → VOIDED`, its `net_commission_cents` is set to 0, and the brokering agent's `pipeline_commission_cents` falls back to its pre-submission value.

A manager approves a provisional statement, advancing it `PROVISIONAL → APPROVED`, permitted only while the parent contract is `ACTIVE` (else `ERR_INVALID_STATE`); approval records the acting manager as `approved_by_manager_id`. Later, a **different** manager trues it up, advancing it `APPROVED → TRUED_UP`. Two preconditions guard the true-up: the acting manager's `X-User-ID` must differ from the recorded `approved_by_manager_id` (else `ERR_SEGREGATION_OF_DUTIES`), and at least one usage record with `is_actual` true must exist for the contract's account (else `ERR_NO_ACTUAL_USAGE`). True-up recomputes the commission on **actual metered usage** by the **actual-commission** rule and records the acting manager as `trued_up_by_manager_id`.

The actual-commission rule differs from the estimate in its input and, critically, in its rounding order. It gathers every usage record for the contract's account whose `is_actual` is true, ordered by `period_month` ascending. For each such month it computes that month's cents as the month's `usage_kwh` times the contract's `broker_adder_mills`, divided by ten, rounded half-up — and only then does it sum the already-rounded monthly figures. This per-month-then-sum order is mandatory; summing kilowatt-hours first and rounding once at the end is not permitted and would produce a different total. The summed cents are then multiplied by the same term multiplier (chosen from `term_months` by the same 12/24 boundaries) and rounded half-up, and finally clamped to the same $50 floor and $50,000 ceiling. The clamped figure becomes `actual_gross_cents`; the statement's `basis` becomes `ACTUAL`; `true_up_delta_cents` is the actual gross minus the originally pinned `gross_commission_cents` (it may be negative); `clawback_cents` is the amount by which the original gross exceeds the actual gross, or 0 if the actual meets or beats the original; and `net_commission_cents` is set to the `actual_gross_cents`.

Two reporting aggregates read this ledger. A broker user's `pipeline_commission_cents` is the sum of `net_commission_cents` across every commission statement on contracts that user brokered whose status is `PROVISIONAL`, `APPROVED`, or `TRUED_UP`; voided statements contribute 0 because their net is 0. The commission-summary report aggregates, for an optional `account_id` filter, the `total_net_commission_cents` and the `statement_count` over that account's non-voided statements.

### 3.6. Demand-Response Enrollment and Settlement

Independently of supply contracts, an account may participate in a **demand-response** program, pledging to curtail load during grid events in exchange for an incentive. An agent enrolls the account by naming its `account_id`, the `program_name`, the `season_start` and `season_end` bounding the DR season (a closed interval, both ends inclusive), the `committed_kw` of curtailment capacity pledged, and the `incentive_per_kw_cents` paid per committed kilowatt for the season. Enrollment opens the record in `ENROLLED`, pins its `provisional_incentive_cents` as the `committed_kw` multiplied by `incentive_per_kw_cents`, and raises the account's `reserved_dr_kw` by the `committed_kw`. A new season must not collide with the account's existing live DR seasons: for every DR enrollment on the account whose status is `ENROLLED`, `ACTIVE`, or `PERFORMED`, the new season must not overlap it and must additionally be separated from it by at least a 14-day buffer on either side; a season that overlaps or falls within 14 days of an existing live season is rejected with `ERR_DR_SEASON_CONFLICT`.

The account's `reserved_dr_kw` is a computed pool: it is the sum of `committed_kw` across the account's DR enrollments whose status is `ENROLLED`, `ACTIVE`, or `PERFORMED`. Enrollments that have `SETTLED` or `WITHDRAWN` are excluded from the pool.

Operations activates an enrollment, advancing it `ENROLLED → ACTIVE`, but only if the account is `ENROLLED` — that is, the account has a live supply contract (else `ERR_ACCOUNT_NOT_ENROLLED`). After a grid event, operations records the delivered curtailment, advancing the enrollment `ACTIVE → PERFORMED` and pinning `performed_kw` from the request; this may occur only once the logical clock has reached or passed `season_start` (else `ERR_DR_SEASON_NOT_STARTED`). A manager then settles it, advancing it `PERFORMED → SETTLED` and computing `settled_incentive_cents` by the **settlement** rule.

Settlement is the dual variant of the provisional incentive on the same enrollment. If `performed_kw` is at least `committed_kw`, the settled incentive equals `committed_kw` times `incentive_per_kw_cents` — delivery is capped at the commitment, with no bonus for over-delivery. If `performed_kw` falls short of `committed_kw`, the shortfall in kilowatts (the commitment minus the performance) draws a penalty of 2,000 cents ($20) per shortfall kilowatt: the settled incentive is the `performed_kw` times `incentive_per_kw_cents`, less the shortfall kilowatts times the $20-per-kW penalty, floored at 0 so it never goes negative.

An agent may withdraw a DR enrollment while it is still `ENROLLED` or `ACTIVE`, moving it to `WITHDRAWN`; withdrawal releases the pledge, so the account's `reserved_dr_kw` falls back by that enrollment's `committed_kw`. `SETTLED` and `WITHDRAWN` are terminal.

Suppliers are governed by their own lifecycle here too. Operations may suspend a supplier, moving it `ACTIVE → SUSPENDED`, or reinstate one, moving it `SUSPENDED → ACTIVE`; the requested `status` value in the set-status body selects the direction. Suspension cascades: every quote from that supplier still in `SUBMITTED` or `SHORTLISTED` is withdrawn, and — as noted in §3.2 — any shortlisted quote so withdrawn from a best-and-final RFP reverts that RFP to `OPEN`.

### 3.7. Scheduled Sweeps, Market Rates, Renewals, and the Clock

The platform's time-driven behavior is exercised through operations capabilities. An operator may record a **market rate** by naming a `commodity`, a `state_code`, and the observed `rate_mills`; the latest such observation per commodity/state is retained and later drives the rate-alert evaluation of §3.4. An operator may advance the **logical clock** by supplying a `to_iso8601` instant, which becomes the new current time and is echoed back as `current_utc`.

The **scheduled sweep** advances the whole system in one call and reports how much it changed. It expires every `SIGNED` LOA whose `expires_at` the clock has reached or passed, moving each `SIGNED → EXPIRED`; if such an expiry leaves an account that was `VERIFIED` or `ENROLLED` with no remaining `SIGNED` LOA, that account is suspended through the same cascade described in §3.1 (which in turn cancels the account's open RFPs and voids their live quotes). It expires every `ACTIVE` contract whose `end_date` the clock has reached or passed, moving each `ACTIVE → EXPIRED`. It opens the renewal window on every `ACTIVE` contract now within 60 days of its `end_date`, setting `renewal_window_open` true. And it raises `rate_alert` to `RATE_DROP` on every `ACTIVE` contract whose latest observed market rate has dropped materially below the contract rate per the §3.4 threshold. The sweep's response reports the counts `expired_loas`, `expired_contracts`, `renewal_windows_opened`, and `rate_alerts_raised`.

**Renewal** lets an agent roll an expiring deal forward. Renewing an `ACTIVE` contract is permitted only while its `renewal_window_open` is true (else `ERR_RENEWAL_WINDOW_CLOSED`); it moves the original `ACTIVE → RENEWED` and creates a successor contract in `PENDING_CUSTOMER` whose `renewed_from_contract_id` points back to the original. The renewal request carries the successor's `start_date`, `requested_switch_date`, and `estimated_annual_usage_kwh`, and the successor then re-enters the customer-decision, approval, and enrollment flow from the top. `REJECTED`, `DROPPED`, `EXPIRED`, and `RENEWED` are all terminal contract states.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201; retrievals, list reads, and state-transition or mutation actions on existing resources return HTTP 200. Errors follow the precedence ladder of §2.6 and the catalogue of §5. The request and response payloads for each endpoint are described in the §3 narratives, not repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/customers` | Register a customer | `BrokerAgent`, `OpsAdmin` |
| GET | `/customers/{customerId}` | Get a customer | `BrokerAgent`, `BrokerManager`, `Supplier`, `Customer`, `OpsAdmin` |
| POST | `/broker-users` | Create broker staff (agent or manager) | `OpsAdmin` |
| GET | `/broker-users/{brokerUserId}` | Get a broker user (exposes `pipeline_commission_cents`) | `BrokerAgent`, `BrokerManager`, `OpsAdmin` |
| POST | `/suppliers` | Register a supplier | `OpsAdmin` |
| GET | `/suppliers/{supplierId}` | Get a supplier | `BrokerAgent`, `BrokerManager`, `Supplier`, `Customer`, `OpsAdmin` |
| POST | `/suppliers/{supplierId}/set-status` | Suspend or reinstate a supplier | `OpsAdmin` |
| POST | `/accounts` | Create a utility account | `BrokerAgent` |
| GET | `/accounts/{accountId}` | Get a utility account (exposes `reserved_dr_kw`) | `BrokerAgent`, `BrokerManager`, `Supplier`, `Customer`, `OpsAdmin` |
| GET | `/accounts` | List utility accounts, optionally filtered by customer or agent | `BrokerAgent`, `BrokerManager`, `OpsAdmin` |
| POST | `/accounts/{accountId}/verify` | Verify an account | `BrokerAgent` |
| POST | `/authorizations` | Draft an LOA for an account | `BrokerAgent` |
| GET | `/authorizations/{authorizationId}` | Get an LOA | `BrokerAgent`, `BrokerManager`, `Customer`, `OpsAdmin` |
| GET | `/authorizations` | List LOAs, optionally filtered by account | `BrokerAgent`, `BrokerManager`, `Customer`, `OpsAdmin` |
| POST | `/authorizations/{authorizationId}/sign` | Customer signs the LOA | `Customer` |
| POST | `/authorizations/{authorizationId}/revoke` | Customer revokes a signed LOA (cascade) | `Customer` |
| POST | `/usage-records` | Import a monthly usage record | `BrokerAgent`, `OpsAdmin` |
| GET | `/usage-records/{usageRecordId}` | Get a usage record | `BrokerAgent`, `BrokerManager`, `OpsAdmin` |
| GET | `/usage-records` | List usage records, filtered by account | `BrokerAgent`, `BrokerManager`, `OpsAdmin` |
| POST | `/rfps` | Draft an RFP for an account | `BrokerAgent` |
| GET | `/rfps/{rfpId}` | Get an RFP | `BrokerAgent`, `BrokerManager`, `Supplier`, `Customer`, `OpsAdmin` |
| GET | `/rfps` | List RFPs, optionally filtered by account or agent | `BrokerAgent`, `BrokerManager`, `Supplier`, `OpsAdmin` |
| POST | `/rfps/{rfpId}/transition` | Advance an RFP (open, best-and-final, re-open, cancel) | `BrokerAgent` |
| POST | `/quotes` | Supplier submits a quote against an RFP | `Supplier` |
| GET | `/quotes/{quoteId}` | Get a quote | `BrokerAgent`, `BrokerManager`, `Supplier`, `OpsAdmin` |
| GET | `/quotes` | List quotes, optionally filtered by RFP and/or supplier | `BrokerAgent`, `BrokerManager`, `Supplier`, `OpsAdmin` |
| POST | `/quotes/{quoteId}/shortlist` | Shortlist a submitted quote | `BrokerAgent` |
| POST | `/quotes/{quoteId}/withdraw` | Supplier withdraws a quote | `Supplier` |
| POST | `/contracts` | Award: select the winning quote and create a contract | `BrokerAgent` |
| GET | `/contracts/{contractId}` | Get a contract | `BrokerAgent`, `BrokerManager`, `Supplier`, `Customer`, `OpsAdmin` |
| GET | `/contracts` | List contracts with optional filters | `BrokerAgent`, `BrokerManager`, `Supplier`, `Customer`, `OpsAdmin` |
| POST | `/contracts/{contractId}/customer-decision` | Customer accepts or rejects the awarded contract | `Customer` |
| POST | `/contracts/{contractId}/approve` | Manager approves a customer-accepted contract | `BrokerManager` |
| POST | `/contracts/{contractId}/submit-enrollment` | Agent submits the switch/enrollment to the utility | `BrokerAgent` |
| POST | `/contracts/{contractId}/enrollment-result` | Ops posts the utility's switch result | `OpsAdmin` |
| POST | `/contracts/{contractId}/add-rec-rider` | Add a green/REC rider to a not-yet-active contract | `BrokerAgent` |
| POST | `/contracts/{contractId}/renew` | Renew an active contract inside its renewal window | `BrokerAgent` |
| GET | `/commission-statements/{statementId}` | Get a commission statement | `BrokerAgent`, `BrokerManager`, `OpsAdmin` |
| GET | `/commission-statements` | List commission statements, filtered by contract | `BrokerAgent`, `BrokerManager`, `OpsAdmin` |
| POST | `/commission-statements/{statementId}/approve` | Manager approves the provisional commission | `BrokerManager` |
| POST | `/commission-statements/{statementId}/true-up` | A different manager trues-up commission (SoD) | `BrokerManager` |
| POST | `/dr-enrollments` | Enroll an account into a demand-response program | `BrokerAgent` |
| GET | `/dr-enrollments/{drId}` | Get a DR enrollment | `BrokerAgent`, `BrokerManager`, `OpsAdmin` |
| GET | `/dr-enrollments` | List DR enrollments, filtered by account | `BrokerAgent`, `BrokerManager`, `OpsAdmin` |
| POST | `/dr-enrollments/{drId}/activate` | Ops activates a DR enrollment | `OpsAdmin` |
| POST | `/dr-enrollments/{drId}/record-performance` | Ops records delivered curtailment kW | `OpsAdmin` |
| POST | `/dr-enrollments/{drId}/settle` | Manager settles the DR incentive | `BrokerManager` |
| POST | `/dr-enrollments/{drId}/withdraw` | Agent withdraws a DR enrollment | `BrokerAgent` |
| GET | `/reports/commission-summary` | Aggregate net commission across an account's statements | `BrokerAgent`, `BrokerManager`, `OpsAdmin` |
| POST | `/operations/record-market-rate` | Record the current market rate for a commodity/state | `OpsAdmin` |
| POST | `/operations/run-scheduled` | Advance system: expiries, renewal windows, rate alerts | `OpsAdmin` |
| POST | `/_clock/set_current_utc` | Test-driving: set the logical clock | `OpsAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_DUPLICATE_ACCOUNT_NUMBER` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REFERENTIAL_MISMATCH` | 409 |
| `ERR_STALE_RFP_VERSION` | 412 |
| `ERR_ACCOUNT_NOT_VERIFIED` | 409 |
| `ERR_LOA_SCOPE_INSUFFICIENT` | 409 |
| `ERR_SUPPLIER_NOT_ACTIVE` | 409 |
| `ERR_ACCOUNT_NOT_ENROLLED` | 409 |
| `ERR_LOA_NOT_SIGNED` | 409 |
| `ERR_NO_USAGE_DATA` | 409 |
| `ERR_NO_QUOTES` | 409 |
| `ERR_NO_ACTUAL_USAGE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_RFP_CLOSED` | 409 |
| `ERR_CONTRACT_OVERLAP` | 409 |
| `ERR_DR_SEASON_CONFLICT` | 409 |
| `ERR_DR_SEASON_NOT_STARTED` | 409 |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 |
| `ERR_MARGIN_BELOW_MIN` | 409 |
| `ERR_APPROVAL_LIMIT_EXCEEDED` | 409 |
| `ERR_NO_ELIGIBLE_QUOTES` | 409 |
