# Endowment Investment & Spending Policy API — Product Requirements Document

## 1. Introduction

A university endowment is not a bank account; it is a perpetual contract between donors, the board, and future generations of students. Gifts arrive restricted by purpose, corpus must be preserved against inflation and market cycles, and annual spending must be generous enough to fund today's programs without starving tomorrow's. When markets fall below a fund's historic gift value, trustees face a legal and ethical minefield: spend anyway and risk violating donor intent, or freeze spending and strand the scholarship program the endowment exists to serve. The endowment office runs this balancing act on spreadsheets today, reconciling unitization math by hand at quarter end and chasing paper trails whenever a donor asks why their fund's payout shrank.

This document specifies the Endowment Investment & Spending Policy API, the system of record for a university's pooled endowment. It tracks fund establishment and donor restrictions, runs pooled unitization with quarterly unit valuation, computes spending distributions under a smoothed spending-rate formula with band constraints, governs underwater funds through a formal policy-exception workflow, supervises external investment managers through performance-driven watchlists, and produces the annual donor and board reports that close the loop. All monetary values are integer cents; unit quantities are integer micro-units; unit prices are integer millicents. Every mutating operation is attributed to an acting user, and every approval gate is segregated from its proposal stage so that no single operator can move money unchallenged.

The API is mounted under the `/endowment` path prefix and exposes a flat topology of peer collections — pools, policies, valuations, donors, funds, gifts, distributions, exceptions, payouts, allocations, managers, manager reports, annual reports, and ledger entries — cross-linked by foreign keys carried in request bodies rather than by nested URL hierarchies.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting user and `X-User-Role` naming that user's role. A request missing either header, or carrying an empty or whitespace-only value for either, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Five roles exist, spelled exactly as follows: `EndowmentAdmin`, `InvestmentOfficer`, `DevelopmentOfficer`, `BoardMember`, `ProgramManager`.

- The `EndowmentAdmin` is the endowment office operations lead and owns pool lifecycle and target allocations: creating pools, suspending and resuming them, and bulk-replacing the target allocation set.
- The `InvestmentOfficer` is the investment office operator and owns valuations, manager oversight, performance filings, policy proposals, exception endorsement, and distribution payout execution.
- The `DevelopmentOfficer` is the advancement office operator and owns donors, funds, gifts, spending proposals, underwater exception requests, and program payout allocation.
- The `BoardMember` is the board or committee approver and adopts policies, approves spending, adjudicates exceptions, terminates managers and funds, redeems corpus, acknowledges allocation drift, and publishes reports.
- The `ProgramManager` represents a receiving university program and reports cumulative spending against disbursed payouts.

For all five roles — `EndowmentAdmin`, `InvestmentOfficer`, `DevelopmentOfficer`, `BoardMember`, and `ProgramManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on created or transitioned records (for example, as `proposed_by_user_id` on a `SpendingPolicyVersion`, `created_by_user_id` on a `UnitValuation`, `Fund`, or `AnnualReport`, `requested_by_user_id` on a `PolicyException`, or `approved_by_user_id` on a distribution or exception), but it never compares `X-User-ID` to any entity's `id`.

Because these identities are opaque, segregation of duties is enforced by comparing recorded user identifiers, not role assignments: adopting a policy requires the adopter's `X-User-ID` to differ from the policy's `proposed_by_user_id`; endorsing an exception requires the endorser to differ from its `requested_by_user_id`; approving an exception requires the approver to differ from both `requested_by_user_id` and `endorsed_by_user_id` (a three-person rule); approving a distribution requires the approver to differ from the distribution's `proposed_by_user_id`; and publishing a report requires the publisher to differ from the report's `created_by_user_id`. Any breach of these rules is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).

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
- Two transport-level failures also use this envelope: an unsupported HTTP method on a defined path is rejected with `error_id` `ERR_NOT_FOUND` at HTTP 405, and an unexpected server failure surfaces as `error_id` `ERR_INVALID_REQUEST` at HTTP 500.

### 2.3. Pagination

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, accepts a minimum of 1 and a maximum of 100, and the `offset` parameter defaults to 0 and must be at least 0. A `limit` or `offset` that does not parse as an integer, or a `limit` outside 1..100, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are sorted by `created_at` in ascending order, with ties broken by insertion order (earliest-created first). The filter query parameters named in §4 are exact-match equality filters on the same-named record field, combine conjunctively when several are supplied, and a numeric filter whose value does not parse as an integer matches no records. The `meta` block of a list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Monetary Conventions

Every entity carries a server-minted `id` as a UUID with no type prefix. All entities except `UnitLedgerEntry` additionally carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and an integer `version` that starts at 1 at creation and increments by 1 on every mutation of that record, with `updated_at` refreshed on each such mutation. `UnitLedgerEntry` is append-only and immutable: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

Money is always integer cents. Unit quantities are integer micro-units, where one unit equals one million micro-units. Unit prices are integer millicents, where one cent equals one thousand millicents, so a fund's value in cents is its micro-unit balance multiplied by the pool's price in millicents and divided by one billion. All division and averaging in the system rounds half up to the target integer precision, and every calculation's rounding points are pinned in the prose below; rounding at a different point, or aggregating before rounding where per-item rounding is specified, produces a non-conformant result.

### 2.5. Pool Epochs, Quarters, and the Inception Price

An `EndowmentPool` is born `ACTIVE` with `current_quarter_index` equal to 0 and `current_unit_price_millicents` equal to the inception price of 100000 millicents — exactly one dollar per unit. Quarters are numbered globally from 1; the **open quarter** at any moment is always `current_quarter_index` + 1. Fiscal years are derived from the pool's `inception_fiscal_year` (which must lie between 2000 and 2100 inclusive): fiscal year *k* offset from inception covers quarters 4k+1 through 4k+4, where *k* equals the fiscal year minus `inception_fiscal_year`. The current fiscal year is therefore the inception year plus the whole number of times 4 divides into `current_quarter_index`. Every quarter is treated as exactly 90 days for all return mathematics.

The pool's `total_units_outstanding_micro` is the exact integer sum of every fund's `units_held_micro`, maintained by construction, and `total_market_value_cents` is the finalized pool market value of the most recent `FINAL` valuation — 0 before any finalize.

### 2.6. Pool Posture as a Global Gate

Suspending a pool (an `EndowmentAdmin` action moving `pool_status` from `ACTIVE` to `SUSPENDED`) and resuming it (`SUSPENDED` back to `ACTIVE`) each increment the pool's `version` by 1. While a pool is `SUSPENDED`, every value-moving child operation is rejected with `ERR_POOL_SUSPENDED` (HTTP 409). The blocked set is exactly: gift receive; valuation create, finalize, and supersede; distribution create, propose, repropose, approve, and distribute; payout create and disburse; manager engage; manager-quarter-report filing; allocation bulk replacement; policy create and adopt; and fund activate and corpus redemption. A pool with zero funds qualifies for termination; terminating a pool (a `BoardMember` action, allowed from either `ACTIVE` or `SUSPENDED` only when every fund of the pool has reached `TERMINATED`, failing which the request is rejected with `ERR_NOT_TERMINABLE`) moves `pool_status` to `TERMINATED`, increments the pool's `version` by 1, and renders the pool read-only — all remaining non-terminal gift records of the pool's funds are rejected going forward, and a `TERMINATED` pool rejects every pool-scoped mutation with `ERR_POOL_SUSPENDED` (HTTP 409), the same error as the suspension gate.

### 2.7. Optimistic Concurrency Control on the Pool

Three write operations take an optimistic-concurrency token because they commit against a pool configuration the client previously observed: finalizing a valuation, superseding a valuation, and adopting a spending policy. Each such request must carry `expected_pool_version` as a non-optional field holding the pool's `version` as the client last read it. If the pool's current `version` has advanced since that read — for example because a suspend/resume cycle or another finalize intervened — the request is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412). Endpoints not in this list do not accept a version field.

### 2.8. Validation Evaluation Order

When several checks could fail on the same request, the server evaluates them in a fixed priority order and reports the earliest failure. The order is: (1) presence of the context headers, failing as `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`; (2) role authorization, failing as `ERR_FORBIDDEN_ROLE`; (3) segregation-of-duties comparisons, failing as `ERR_SEGREGATION_OF_DUTIES_VIOLATION`; (4) request body shape — well-formed JSON object body, required fields present, enums valid, integer ranges respected — failing as `ERR_INVALID_REQUEST`; (5) existence of referenced resources, validated left-to-right along the path and then the body, failing as `ERR_NOT_FOUND`; (6) lifecycle-state permission for the requested transition, failing as `ERR_INVALID_STATE_TRANSITION`; (7) the pool posture gate, failing as `ERR_POOL_SUSPENDED`; (8) the OCC version comparison, failing as `ERR_STALE_POOL_VERSION`; (9) donor-restriction compliance on payouts, failing as `ERR_PURPOSE_MISMATCH`; (10) the underwater spending lock, failing as `ERR_UNDERWATER_SPENDING_BLOCKED`; (11) the exception-on-non-underwater-fund rejection, failing as `ERR_FUND_NOT_UNDERWATER`; (12) corpus inviolability, failing as `ERR_CORPUS_INVIOLABLE`; (13) uniqueness constraints, failing as `ERR_DUPLICATE_RECORD`; (14) temporal window rules, failing as `ERR_WINDOW_CONFLICT`; (15) valuation sequencing, failing as `ERR_VALUATION_OUT_OF_ORDER`; (16) the valuation consumption lock, failing as `ERR_VALUATION_LOCKED`; (17) fiscal-year completeness for reports, failing as `ERR_INCOMPLETE_FISCAL_YEAR`; (18) the drift acknowledgement gate, failing as `ERR_DRIFT_NOT_ACKNOWLEDGED`; (19) the fund activation minimum, failing as `ERR_MINIMUM_FUNDING_NOT_MET`; (20) policy parameter ranges, failing as `ERR_POLICY_PARAM_OUT_OF_RANGE`; (21) the allocation sum rule, failing as `ERR_ALLOCATION_SUM_INVALID`; (22) the manager-report completeness gate at finalize, failing as `ERR_MANAGER_REPORT_MISSING`; (23) the pool market-value reconciliation at finalize, failing as `ERR_POOL_MV_MISMATCH`; (24) manager report continuity, failing as `ERR_MV_CONTINUITY_BREAK`; (25) the exception amount cap, failing as `ERR_EXCEPTION_AMOUNT_EXCEEDS_REQUESTED`; (26) the payout aggregate cap, failing as `ERR_ALLOCATION_EXCEEDS_DISTRIBUTION`; (27) spending report monotonicity, failing as `ERR_INVALID_SPENT_AMOUNT`; (28) redemption unit coverage, failing as `ERR_INSUFFICIENT_UNITS`; (29) the applicable-policy lookup, failing as `ERR_NO_APPLICABLE_POLICY`; and (30) termination eligibility, failing as `ERR_NOT_TERMINABLE`.

### 2.9. Uniqueness and Duplicate Detection

Create endpoints reject duplicates with `ERR_DUPLICATE_RECORD` (HTTP 409). The uniqueness keys are: the pair of `fund_id` and `external_ref` among all non-`CANCELLED` gifts of a fund; the pair of `pool_id` and `fund_code` (fund codes are case-sensitive) for funds; the pair of `pool_id` and `asset_class` for allocations; the pair of `manager_id` and `quarter_index` for manager reports; the pair of `fund_id` and `fiscal_year` among non-`CANCELLED` distributions; the pair of `fund_id` and `fiscal_year` among non-terminal exceptions; and the quadruple of `pool_id`, `fund_id`, `fiscal_year`, and `report_type` for annual reports.

## 3. Business Logic & Workflows

### 3.1. Establishing Pools, Funds, and Donor Restrictions

An `EndowmentAdmin` begins by creating a pool with a display `pool_name` and an `inception_fiscal_year`; the pool starts `ACTIVE` at quarter 0 with the inception unit price. Donors enter the system through a `DevelopmentOfficer` who records `donor_name`, a `donor_type` of `INDIVIDUAL`, `FOUNDATION`, `CORPORATION`, or `ESTATE`, and an optional `contact_email` that may be null. Each donor accumulates a `total_contributed_cents` total, computed as the sum of `amount_cents` over that donor's gifts whose `gift_status` is `RECEIVED` or `UNITIZED`, starting from 0.

A `DevelopmentOfficer` then establishes funds against a pool, supplying a `fund_code` unique within the pool, a display `fund_name`, an `endowment_class`, and a `purpose_restriction`. The endowment class is one of `TRUE_ENDOWMENT`, `QUASI_ENDOWMENT`, or `TERM_ENDOWMENT`; a term endowment must carry a `term_end_quarter_index` of at least 1, while the other two classes must leave it null, and a malformed combination is rejected with `ERR_INVALID_REQUEST`. The purpose restriction is one of `UNRESTRICTED`, `SCHOLARSHIP`, `PROFESSORSHIP`, `RESEARCH`, or `CAPITAL_PROJECTS`. A new fund starts in `DRAFT` lifecycle (`fund_status`) with a `spending_posture` of `NORMAL` — two parallel, independent dimensions — with `historic_gift_value_cents`, `pledged_corpus_cents`, `units_held_micro`, and `market_value_cents` all at 0, `is_underwater` false, and `activated_quarter_index` null until activation.

Activation moves a fund from `DRAFT` to `ACTIVE`. The fund's `pledged_corpus_cents` — the sum of `amount_cents` over its `CORPUS` gifts in `PLEDGED`, `RECEIVED`, or `UNITIZED` status, i.e. every non-`CANCELLED`, non-`RETURNED` corpus gift — must reach the statutory minimum of 5000000 cents ($50,000.00) before activation; because pledges count, a fund can activate on signed pledges before cash arrives, and an activation below the minimum is rejected with `ERR_MINIMUM_FUNDING_NOT_MET`. Activation also requires the pool to be `ACTIVE` and, for term endowments, that `term_end_quarter_index` is set. On success, `activated_quarter_index` is stamped with the open quarter index, namely the pool's `current_quarter_index` + 1.

Terminating a fund is a `BoardMember` action from `ACTIVE` to `TERMINATED`, permitted only when the fund holds zero units (`units_held_micro` is 0), has no gift in `PLEDGED` or `RECEIVED`, has no distribution in `PROJECTED`, `PROPOSED`, `REVISION_REQUESTED`, or `APPROVED`, and has no payout in `SCHEDULED` or `DISBURSED`; any shortfall is rejected with `ERR_NOT_TERMINABLE`. Termination forces the fund's `spending_posture` back to `NORMAL`.

### 3.2. Gifts: Pledges, Receipts, and the Provisional Estimate

A `DevelopmentOfficer` records a gift against a fund by supplying `fund_id`, `donor_id`, a client-chosen `external_ref` deduplication key, a `gift_type` of `CORPUS` or `EXPENDABLE`, and an `amount_cents` that must be strictly greater than 0. The fund may be `DRAFT` or `ACTIVE` at recording time; recording a gift against a `TERMINATED` fund is rejected with `ERR_INVALID_STATE_TRANSITION`. The gift is born `PLEDGED`. Recording a `CORPUS` gift immediately adds its `amount_cents` to the fund's `pledged_corpus_cents`, which is how signed pledges feed the activation minimum. Cancelling a `PLEDGED` gift moves it to `CANCELLED` and, for corpus gifts, subtracts `amount_cents` from `pledged_corpus_cents`, exactly compensating the create step.

Receiving a gift moves it from `PLEDGED` to `RECEIVED`; it requires the fund to be `ACTIVE` and the pool to be `ACTIVE`. Receipt stamps `received_quarter_index` with the open quarter (`current_quarter_index` + 1) — this stamp decides which quarter's `FINAL` price will unitize the gift — and computes an advisory `provisional_units_estimate_micro` as the gift's `amount_cents` multiplied by one billion and divided by the pool's `current_unit_price_millicents`, rounded half up. Receipt also adds `amount_cents` to the donor's `total_contributed_cents`. A received gift may be rescinded, moving from `RECEIVED` to `RETURNED`; rescission after unitization is impossible because the transition only exists from `RECEIVED`. Rescinding a corpus gift subtracts `amount_cents` from the fund's `pledged_corpus_cents` (compensating the create) and subtracts `amount_cents` from the donor's `total_contributed_cents` (compensating the receive).

The timing rule matters: a gift catches the price of the quarter it was received in. It must reach `RECEIVED` strictly before that quarter's finalize to ride its price; a gift received one request after the finalize catches the next quarter's price instead. Receive, cancel, and rescind all address the gift by its `gift_id`.

### 3.3. Spending Policy Versions and the Half-Open Window Rule

An `InvestmentOfficer` proposes spending policy versions against a pool, supplying `pool_id`, an annual `spending_rate_bps` between 100 and 2000 inclusive (1.00% to 20.00%), a `smoothing_window_quarters` between 4 and 20 inclusive, a `band_floor_bps` and `band_cap_bps` each between 0 and 10000 inclusive, and an `effective_from_fiscal_year`. Parameters outside these ranges are rejected with `ERR_POLICY_PARAM_OUT_OF_RANGE`. The new policy starts in `DRAFT` with `proposed_by_user_id` set to the creator's `X-User-ID` and `adopted_by_user_id` null.

Adoption is a `BoardMember` action requiring the pool to be `ACTIVE` and carrying the OCC token `expected_pool_version` (§2.7). Two window rules apply, both failing as `ERR_WINDOW_CONFLICT`: no already-`ADOPTED` policy of the same pool may share the candidate's `effective_from_fiscal_year`, and the candidate's effective year must be strictly greater than every other `ADOPTED` policy's effective year for that pool, so the adopted policies form a strictly increasing sequence of half-open windows [effective year of policy *i*, effective year of policy *i*+1). The adopter must not be the user recorded in `proposed_by_user_id`. When adoption succeeds, the pool's previously latest `ADOPTED` policy, if any, transitions from `ADOPTED` to `SUPERSEDED` — its window closes but it still governs its past fiscal years for historical lookups — the new policy records `adopted_by_user_id`, and the pool's `version` increments by 1. An `InvestmentOfficer` may also withdraw a `DRAFT` policy, moving it to `WITHDRAWN`.

When any computation needs the policy applicable to a fiscal year, it selects the policy with the greatest `effective_from_fiscal_year` not later than that fiscal year among the pool's `ADOPTED` or `SUPERSEDED` policies; if none qualifies, the operation is rejected with `ERR_NO_APPLICABLE_POLICY`. This lookup guards distribution creation, propose, repropose, and approve alike, and the selected policy is captured into the distribution's `policy_id` at each computation.

### 3.4. Quarterly Valuation: Preliminary Price, Finalize, and the Close Pipeline

Each quarter the `InvestmentOfficer` opens a valuation for the pool, supplying `pool_id` and an unaudited `estimated_pool_market_value_cents` of at least 0. The valuation's `quarter_index` is assigned as the pool's open quarter, and only the open quarter may be valued; creating a valuation for any other quarter — or when a `PRELIMINARY` or `FINAL` valuation already exists for the open quarter — is rejected with `ERR_VALUATION_OUT_OF_ORDER`. The new record is `PRELIMINARY`, with `created_by_user_id` recorded, `finalized_by_user_id`, `final_unit_price_millicents`, and `final_pool_market_value_cents` null, and `supersedes_valuation_id` null. Its `preliminary_unit_price_millicents` is computed immediately: when the pool's `total_units_outstanding_micro` is 0 the price is the inception price of 100000 millicents; otherwise it is the estimated market value multiplied by one billion and divided by the outstanding micro-units, rounded half up, floored at 1 millicent.

Finalization converts the open `PRELIMINARY` valuation to `FINAL`. The request carries `final_pool_market_value_cents` (at least 0) and `expected_pool_version`. Before any computation, three reconciliation gates must pass: every investment manager of the pool whose coverage interval contains the quarter (a `coverage_start_quarter` no later than the quarter, and a `coverage_end_quarter` either null or no earlier than the quarter) and whose `engagement_status` is neither `PROSPECT` nor `DECLINED` must have filed a report for that quarter, else `ERR_MANAGER_REPORT_MISSING`; the supplied `final_pool_market_value_cents` must exactly equal the sum of `ending_mv_cents` across those eligible reports, else `ERR_POOL_MV_MISMATCH`; and the pool's allocation targets must sum to exactly 10000 basis points, else `ERR_ALLOCATION_SUM_INVALID`.

A successful finalize runs the **quarter close pipeline** in a pinned nine-step order, each step observing only the outputs of earlier steps:

1. **Price.** The `final_unit_price_millicents` is computed from `final_pool_market_value_cents` and the pool's total units outstanding measured *before* any gift unitization or redemption of this close: when that pre-flow unit count is 0 the price is the inception price of 100000 millicents, otherwise it is the final value multiplied by one billion and divided by the pre-flow units, rounded half up and floored at 1 millicent.
2. **Lapse sweep.** Each payout whose unspent balance has aged out is closed and reinvested (§3.7).
3. **Unitization.** Every gift in `RECEIVED` whose `received_quarter_index` equals the quarter being finalized — donor gifts and the sweep reinvestments created in step 2 alike — is unitized at the step-1 price, processed in ascending `created_at` order with ties broken by ascending `external_ref` (never by `id`). Each gift's `units_purchased_micro` is its `amount_cents` multiplied by one billion and divided by the `final_unit_price_millicents`, rounded half up per gift — never aggregated and then rounded. The gift's `unitized_quarter_index` is set to the finalized quarter, its status becomes `UNITIZED`, the fund's `units_held_micro` and the pool's `total_units_outstanding_micro` both increase by exactly `units_purchased_micro`, and a `UnitLedgerEntry` of type `GIFT_UNITIZE` is emitted — or `REINVEST_UNITIZE` when the gift's `source_payout_id` is set.
4. **HGV refresh.** For each `CORPUS` gift unitized in step 3, the fund's `historic_gift_value_cents` increases by the gift's `amount_cents`. Expendable gifts unitize without touching historic gift value.
5. **Market value and underwater refresh.** Each fund's `market_value_cents` is recomputed as its post-unitization `units_held_micro` multiplied by the new `current_unit_price_millicents` and divided by one billion, rounded half up, and `is_underwater` is set to true exactly when `market_value_cents` is strictly less than `historic_gift_value_cents` — equality is not underwater.
6. **Posture transitions.** Funds whose refresh shows them underwater and non-exempt move `spending_posture` from `NORMAL` to `SPENDING_SUSPENDED`; funds no longer underwater — or newly exempt by term maturity — move from `SPENDING_SUSPENDED` back to `NORMAL`. Each such move increments the fund's `version` by 1.
7. **Exception expiry.** `APPROVED` exceptions whose fiscal year's last quarter is the quarter just finalized expire (§3.6).
8. **Allocation drift.** Each allocation row's `actual_pct_bps` and `drift_status` are recomputed (§3.9).
9. **Epoch advance.** The pool's `current_quarter_index` becomes the finalized quarter, `current_unit_price_millicents` and `total_market_value_cents` are stored from this valuation, and the pool's `version` increments by 1.

The circular-looking dependency — the sweep's reinvestment units depend on the step-1 price, while the price must not include step-3's new units — is resolved by the pinned order: the price uses pre-flow units only, and all gifts unitize at that already-fixed price. Recomputing the price after unitization is forbidden.

Restatement is possible but tightly locked. Superseding a valuation requires it to be `FINAL` and to cover the pool's current quarter — only the latest finalized quarter may be restated, anything older is `ERR_VALUATION_OUT_OF_ORDER` — and its request carries a `revised_pool_market_value_cents` of at least 0 alongside the OCC token `expected_pool_version`. The consumption lock rejects the supersede with `ERR_VALUATION_LOCKED` when any gift has `unitized_quarter_index` equal to that quarter, any payout was swept in that quarter, any manager report exists for that quarter, or any distribution reached `DISTRIBUTED` after that finalize; in practice only quarters of a zero-manager pool with no unitizing gifts qualify. A successful supersede moves the valuation to `SUPERSEDED`, rolls the pool back to the end of the prior quarter — `current_quarter_index` decremented, `current_unit_price_millicents` and `total_market_value_cents` restored to the prior quarter's `FINAL` values (the inception price and 0 when the superseded quarter was quarter 1), and allocation drift restored to its pre-finalize values; no unit flows are touched because the lock guarantees none consumed the quarter, and each fund's `market_value_cents` and `is_underwater` are refreshed at the restored price — then creates a corrective `PRELIMINARY` valuation for the same quarter with `supersedes_valuation_id` pointing at the superseded record and `estimated_pool_market_value_cents` taken from the request's `revised_pool_market_value_cents`. The pool's `version` increments by 1, and the response is the corrective valuation at HTTP 201. Throughout these operations a valuation is addressed by its `valuation_id`.

### 3.5. Spending Distributions: Smoothing, Bands, and the Underwater Gate

A `DevelopmentOfficer` projects a fund's annual spending by creating a distribution with `fund_id` and `fiscal_year`; the fund must be `ACTIVE`, and the fiscal year must lie between the pool's `inception_fiscal_year` and one past the current fiscal year inclusive, where the current fiscal year is the inception year plus the whole number of times 4 divides into `current_quarter_index` — out-of-range years are `ERR_WINDOW_CONFLICT`. The new distribution is born `PROJECTED` and immediately runs the full computation against the latest finalized data, populating `smoothed_base_cents`, `raw_amount_cents`, `prior_year_distribution_cents`, `band_adjusted_amount_cents`, `was_underwater_at_proposal`, `final_amount_cents`, and `policy_id`, with `distributed_amount_cents` at 0 and `units_redeemed_micro`, `applied_exception_id`, `proposed_by_user_id`, and `approved_by_user_id` null.

The **smoothed base** averages the fund's quarter-end market values over the trailing window of finalized quarters named by the applicable policy's `smoothing_window_quarters`, ending at the pool's `current_quarter_index` and considering only quarters in which the fund actually held units. Units held at the end of a quarter are derived by replaying the fund's `UnitLedgerEntry` rows with `quarter_index` up to that quarter. For each eligible quarter, the fund's market value is its end-of-quarter units multiplied by that quarter's `final_unit_price_millicents` and divided by one billion, rounded half up to cents *first*; the average of these per-quarter values over the eligible-quarter count is then taken and rounded half up to cents *second*. The rounding order is pinned — per-quarter round, then average, then round — and averaging unrounded products first is a rejected order. Quarters before the fund's first unitization are excluded from the denominator. If the fund held units in no finalized quarter of the window, the base falls back to the fund's current `market_value_cents`.

The **raw amount** is the smoothed base multiplied by the policy's `spending_rate_bps` and divided by 10000, rounded half up. The **band clamp** then applies when the fund has a `DISTRIBUTED` distribution for the prior fiscal year: `prior_year_distribution_cents` holds that distribution's `final_amount_cents` and is null when none exists, which disables the clamp. With a prior value, the cap is the prior amount multiplied by 10000 plus `band_cap_bps` and divided by 10000, rounded half up; the floor is the prior amount multiplied by 10000 minus `band_floor_bps` and divided by 10000, rounded half up; and `band_adjusted_amount_cents` is the raw amount first clamped to at most the cap and then raised to at least the floor — the cap is evaluated first, then the floor. Without a prior, `band_adjusted_amount_cents` equals `raw_amount_cents`.

The **final amount** applies the underwater gate. A fund is exempt from the gate when its `endowment_class` is `QUASI_ENDOWMENT`, or when it is a `TERM_ENDOWMENT` whose `term_end_quarter_index` has been reached — that is, the pool's `current_quarter_index` is at least `term_end_quarter_index`. When the fund is underwater and not exempt, `final_amount_cents` is 0 unless an `APPROVED` exception exists for the fund and fiscal year, in which case it is the smaller of that exception's `approved_amount_cents` and `band_adjusted_amount_cents`. Otherwise `final_amount_cents` equals `band_adjusted_amount_cents`. The fund's `is_underwater` at computation time is snapshot into `was_underwater_at_proposal`.

The review loop runs `PROJECTED` → `PROPOSED` (propose by a `DevelopmentOfficer`, requiring an `ACTIVE` pool and fund, recomputing every derived amount against current data and stamping `proposed_by_user_id`), then `PROPOSED` → `REVISION_REQUESTED` (a `BoardMember` requesting revision) → back to `PROPOSED` via repropose by a `DevelopmentOfficer`, which recomputes identically and refreshes `proposed_by_user_id`; the propose/request-revision/repropose loop may iterate without bound. Approval (`PROPOSED` → `APPROVED`) is a `BoardMember` action on an `ACTIVE` pool: the approver's `X-User-ID` must differ from `proposed_by_user_id`, and when the fund is underwater and non-exempt, an `APPROVED` exception for the fund and fiscal year must exist, failing which the approval is rejected with `ERR_UNDERWATER_SPENDING_BLOCKED`. Approval recomputes all derived amounts, sets `final_amount_cents` per the gate (0 when underwater without exception; the exception-capped minimum with one; otherwise the band-adjusted amount), records `applied_exception_id` when an exception is used, and stamps `approved_by_user_id`.

Distribution (`APPROVED` → `DISTRIBUTED`) is an `InvestmentOfficer` action requiring an `ACTIVE` pool, a `final_amount_cents` strictly greater than 0 (a zero `final_amount_cents` is rejected with `ERR_INVALID_STATE_TRANSITION`), and sufficient units: the redemption burns `units_redeemed_micro` computed as `final_amount_cents` multiplied by one billion and divided by the pool's `current_unit_price_millicents`, rounded half up, and that quantity must not exceed the fund's `units_held_micro`, failing which the request is rejected with `ERR_INSUFFICIENT_UNITS`. The redemption is dollar-denominated: the cash settled equals `final_amount_cents` exactly and any per-unit rounding dust stays in the fund's remaining units. On success the fund's `units_held_micro` and the pool's `total_units_outstanding_micro` decrease by the redeemed amount, `market_value_cents` and `is_underwater` are refreshed, `distributed_amount_cents` is set to `final_amount_cents`, a `UnitLedgerEntry` of type `DISTRIBUTION_REDEEM` is emitted, and — when `applied_exception_id` is set — that exception transitions from `APPROVED` to `EXERCISED` and the fund's posture leaves `EXCEPTION_ACTIVE` for `SPENDING_SUSPENDED` if it remains underwater (a later finalize may move it to `NORMAL`).

Cancellation covers two sibling branches with different guards. Either authorized role — `DevelopmentOfficer` or `BoardMember` — may cancel a distribution in `PROJECTED`, `PROPOSED`, or `REVISION_REQUESTED`; a distribution in `DISTRIBUTED` or `CANCELLED` cannot be cancelled at all (`ERR_INVALID_STATE_TRANSITION`). Only a `BoardMember` may cancel an `APPROVED` distribution — a `DevelopmentOfficer` attempting it is rejected with `ERR_INVALID_STATE_TRANSITION` — a board-level withdrawal before any disbursement, permitted only when no payout referencing that distribution exists in any status; and when the cancelled `APPROVED` distribution carried an `applied_exception_id` whose exception is still `APPROVED`, that exception transitions to `RESCINDED` and the fund's posture reverts from `EXCEPTION_ACTIVE` to `SPENDING_SUSPENDED`.

### 3.6. Underwater Policy Exceptions

When a fund is underwater, a `DevelopmentOfficer` may request a board exception authorizing limited spending, supplying `fund_id`, `fiscal_year`, a `requested_amount_cents` strictly greater than 0, and a free-text `justification` for the board. The fund must be `ACTIVE` and actually underwater at request time; requesting an exception for a fund that is not underwater is rejected with `ERR_FUND_NOT_UNDERWATER`. The new record is `REQUESTED` with `requested_by_user_id` stamped and `endorsed_by_user_id` and `approved_by_user_id` null.

Endorsement (`REQUESTED` → `ENDORSED`) is an `InvestmentOfficer` action whose actor must differ from `requested_by_user_id`; it stamps `endorsed_by_user_id`. A `BoardMember` may reject from either `REQUESTED` or `ENDORSED`, landing in `REJECTED`. Approval (`ENDORSED` → `APPROVED`) is a `BoardMember` action carrying `approved_amount_cents`, which must be strictly greater than 0 and no greater than `requested_amount_cents` — an excess is rejected with `ERR_EXCEPTION_AMOUNT_EXCEEDS_REQUESTED`. Three-person segregation applies: the approver must differ from both `requested_by_user_id` and `endorsed_by_user_id`. The fund must still be underwater at approval, else `ERR_FUND_NOT_UNDERWATER`. Approval stamps `approved_by_user_id` and flips the fund's `spending_posture` from `SPENDING_SUSPENDED` to `EXCEPTION_ACTIVE` — this approval is what flips the fund.

An approved exception leaves `APPROVED` by one of three exits, each with its own cascade. **Exercise:** when the distribution carrying `applied_exception_id` equal to this exception reaches `DISTRIBUTED`, the exception becomes `EXERCISED` and the fund's posture returns from `EXCEPTION_ACTIVE` to `SPENDING_SUSPENDED` while it remains underwater. **Expiry:** when a valuation finalize closes the last quarter of the exception's fiscal year — the quarter whose index equals 4 times (fiscal year minus `inception_fiscal_year` plus 1) — while the exception is still unused, it becomes `EXPIRED`; any distribution holding `applied_exception_id` equal to this exception in status `APPROVED` reverts from `APPROVED` to `PROPOSED` with `applied_exception_id` and `approved_by_user_id` cleared and `final_amount_cents` recomputed (0 while the fund remains underwater), and the fund's posture returns to `SPENDING_SUSPENDED`. **Rescission:** a `BoardMember` may rescind an `APPROVED` exception, which applies the same distribution-reversion cascade — linked `APPROVED` distributions revert to `PROPOSED` with recomputed `final_amount_cents` — and returns the fund's posture from `EXCEPTION_ACTIVE` to `SPENDING_SUSPENDED`. In both the expiry and rescission cases, if the fund is no longer underwater the next finalize moves its posture onward to `NORMAL`. Endorse, approve, reject, and rescind all address the exception by its `exception_id`.

### 3.7. Program Payouts and the Lapse Sweep

Once a distribution has reached `DISTRIBUTED`, a `DevelopmentOfficer` allocates its cash to university programs by creating payouts with `distribution_id`, a `program_code`, a `program_purpose`, and an `allocated_amount_cents` strictly greater than 0. Donor-restriction compliance is enforced at this point: the payout's `program_purpose` — one of `SCHOLARSHIP`, `PROFESSORSHIP`, `RESEARCH`, or `CAPITAL_PROJECTS` — must equal the fund's `purpose_restriction` unless that restriction is `UNRESTRICTED`, failing which the create is rejected with `ERR_PURPOSE_MISMATCH`. The sum of `allocated_amount_cents` over the distribution's non-cancelled payouts, including the new one, must not exceed the distribution's `distributed_amount_cents`, failing which the create is rejected with `ERR_ALLOCATION_EXCEEDS_DISTRIBUTION`. A new payout is `SCHEDULED`, with `spent_amount_cents` at 0, `unspent_amount_cents` equal to `allocated_amount_cents`, `disbursed_quarter_index` null, and `swept_gift_id` null.

Disbursement (`SCHEDULED` → `DISBURSED`) is a `DevelopmentOfficer` action requiring an `ACTIVE` pool and a distribution still in `DISTRIBUTED`; it stamps `disbursed_quarter_index` with the open quarter (`current_quarter_index` + 1) — the anchor for lapse aging — and sets `unspent_amount_cents` to `allocated_amount_cents` minus `spent_amount_cents`.

A `ProgramManager` reports cumulative program spending by submitting `spent_amount_cents`, which must be at least the currently recorded value and at most `allocated_amount_cents` — a decrease or an over-allocation report is rejected with `ERR_INVALID_SPENT_AMOUNT`. A partial report (greater than the current value, less than the allocation) keeps the payout in `DISBURSED` and shrinks `unspent_amount_cents` to the remaining difference. A report reaching exactly the full allocation closes the payout as `CLOSED_FULLY_SPENT` with `unspent_amount_cents` set to 0.

Payouts that sit unspent are swept back to the fund. During step 2 of the quarter close pipeline, any payout still `DISBURSED` whose age — the finalized quarter index minus `disbursed_quarter_index` — is at least 4 quarters lapses: an age of exactly 4 sweeps. Payouts are swept in ascending `created_at` order. The sweep computes the unspent remainder as `allocated_amount_cents` minus `spent_amount_cents`, closes the payout as `CLOSED_RETURNED` with `unspent_amount_cents` zeroed, and creates a system gift on the fund: `gift_type` `EXPENDABLE`, `gift_status` `RECEIVED` in the finalized quarter, `amount_cents` equal to the unspent remainder, `donor_id` null (the only case where a gift's donor may be null), `source_payout_id` pointing at the swept payout, `external_ref` formed as the literal prefix `SWEEP-` followed by the payout's id, and a `provisional_units_estimate_micro` computed from the pool's pre-close `current_unit_price_millicents` exactly as a donor receipt's is. The payout's `swept_gift_id` is set to the new gift. Conservation holds exactly per payout: `allocated_amount_cents` equals `spent_amount_cents` plus the swept remainder. The reinvestment gift then unitizes at the new price in step 3 of the same close pipeline, emitting a `REINVEST_UNITIZE` ledger entry. Disbursement and spending reports address the payout by its `payout_id`.

### 3.8. Corpus Redemption and Fund Solvency

Beyond spending distributions, a `BoardMember` may redeem corpus units for cash by specifying an `amount_cents` that must be a positive integer (at least 1); the fund must be `ACTIVE`, failing which the request is rejected with `ERR_INVALID_STATE_TRANSITION`. Corpus is inviolable for `TRUE_ENDOWMENT` funds and for `TERM_ENDOWMENT` funds whose `term_end_quarter_index` has not yet been reached; redemption on either is rejected with `ERR_CORPUS_INVIOLABLE`. Only `QUASI_ENDOWMENT` funds and matured term funds may redeem corpus. The burn follows the same unit math as distribution redemption: the redeemed micro-units are `amount_cents` multiplied by one billion and divided by the pool's `current_unit_price_millicents`, rounded half up, and must not exceed `units_held_micro` (`ERR_INSUFFICIENT_UNITS` otherwise). The fund's `historic_gift_value_cents` decreases by `amount_cents`, floored at 0 — the only operation besides corpus gift unitization that moves historic gift value, which is never moved by market swings or spending — `market_value_cents` and `is_underwater` are refreshed, the pool's `total_units_outstanding_micro` decreases, and a `UnitLedgerEntry` of type `CORPUS_REDEEM` is emitted.

### 3.9. Target Allocations and Drift Governance

The pool's investment policy statement lives in its asset-class target allocation. An `EndowmentAdmin` replaces the entire target set atomically by submitting `pool_id` and an `items` array whose elements each carry `asset_class`, `target_pct_bps`, and `rebalance_band_bps`. The asset class enum is `US_EQUITY`, `DEVELOPED_INTL_EQUITY`, `EMERGING_MARKETS`, `FIXED_INCOME`, `REAL_ASSETS`, `PRIVATE_EQUITY`, or `CASH`; duplicates within `items` are rejected with `ERR_DUPLICATE_RECORD`, rows absent from `items` are deleted, matching rows are updated (a row whose `target_pct_bps` and `rebalance_band_bps` are both unchanged is left untouched), and new rows are created with `actual_pct_bps` 0, `drift_status` `IN_BAND`, and `drift_acknowledged` false. Each `target_pct_bps` lies between 0 and 10000 inclusive, each `rebalance_band_bps` between 1 and 5000 inclusive, and the targets must sum to exactly 10000 basis points — both at replacement time and again at every finalize, failing as `ERR_ALLOCATION_SUM_INVALID`. The replacement responds with HTTP 200 and `response_type` `array`, carrying the pool's full post-replacement allocation rows in `created_at` ascending order; its `meta` block carries no pagination fields.

At every finalize (pipeline step 8), each allocation's `actual_pct_bps` is recomputed: the quarter's `ending_mv_cents` is summed across manager reports whose manager's `asset_class` matches the row, and when the pool's final market value is 0 the actual percentage is 0, otherwise it is the class value multiplied by 10000 and divided by the final pool market value, rounded half up. A row's `drift_status` becomes `BREACHED` when the absolute difference between `actual_pct_bps` and `target_pct_bps` is strictly greater than `rebalance_band_bps` — equality stays in band — and returns to `IN_BAND` when the difference is no greater than the band. Either flip resets `drift_acknowledged` to false. A `BoardMember` may acknowledge a breached allocation, setting `drift_acknowledged` true, which is valid only while the row is `BREACHED`; the acknowledgement gates board-investment report publication (§3.11). Reading or acknowledging a single allocation addresses it by its `allocation_id`.

### 3.10. Investment Managers, Coverage Intervals, and Performance Streaks

An `InvestmentOfficer` registers an external manager with `pool_id`, `manager_name`, an `asset_class` drawn from the same enum as allocations, a `benchmark_code`, and a `coverage_start_quarter` of at least 1. The manager starts as `PROSPECT` with `coverage_end_quarter` null and both streaks at 0. Declining a prospect moves it to `DECLINED`.

Engagement (`PROSPECT` → `ENGAGED`) requires an `ACTIVE` pool and enforces a coverage-exclusivity rule per pool and asset class, failing as `ERR_WINDOW_CONFLICT`: the candidate's coverage interval — `coverage_start_quarter` onward, open-ended — must not intersect the interval of any other manager of the same pool and asset class whose status is not `PROSPECT` or `DECLINED`. Engaged-family managers occupy their start onward indefinitely, while `TERMINATED` managers occupy the closed historical interval from their start to their `coverage_end_quarter`. Intervals are inclusive at both ends, so the candidate's start must be strictly greater than any terminated predecessor's end; adjacency — starting exactly one quarter after a predecessor's end — is allowed. Historical quarters may never be double-covered.

Each quarter, an `InvestmentOfficer` files a manager's report with `manager_id`, `quarter_index`, `beginning_mv_cents`, `ending_mv_cents`, a `flows` array, and `benchmark_return_bps`. The manager must be `ENGAGED`, `WATCHLIST`, or `PROBATION`; the quarter must equal the pool's open quarter and be no earlier than `coverage_start_quarter` (violations are `ERR_WINDOW_CONFLICT`); and market-value continuity requires `beginning_mv_cents` to equal the manager's prior-quarter `ending_mv_cents` whenever a prior report exists (`ERR_MV_CONTINUITY_BREAK`). Both market values must be at least 0. Each entry in `flows` carries a `day_offset` between 0 and 89 inclusive and a non-zero `amount_cents` — positive for contributions, negative for distributions — and the array may be empty or omitted entirely (an omitted `flows` defaults to an empty array); `benchmark_return_bps` may be negative.

Two return figures are computed at filing. The official **Modified Dietz** return `return_bps`: let sumF be the sum of all flow amounts, and the Dietz denominator be `beginning_mv_cents` times 90 plus the sum over flows of (90 minus the flow's `day_offset`) times the flow's amount, weighting each flow by the fraction of the 90-day quarter it was invested — a mid-quarter inflow halves its weight. When the denominator is 0 the return is 0; otherwise it is 10000 times (`ending_mv_cents` minus `beginning_mv_cents` minus sumF) times 90, divided by the denominator, rounded half up, evaluated in exact integer arithmetic with multiplication before division. The **flow-blind** comparator `simple_return_bps`: 0 when `beginning_mv_cents` is 0, otherwise 10000 times (`ending_mv_cents` minus `beginning_mv_cents` minus sumF) divided by `beginning_mv_cents`, rounded half up. Identical inputs yield a different basis-point figure from the Dietz value whenever `flows` is non-empty. Finally `excess_bps` is `return_bps` minus `benchmark_return_bps`, and its sign drives the streaks.

Streak bookkeeping updates immediately after each filing: a negative `excess_bps` increments `neg_excess_streak` by 1 and resets `nonneg_excess_streak` to 0; a non-negative `excess_bps` — zero counts as non-negative and resets the negative streak — increments `nonneg_excess_streak` by 1 and resets `neg_excess_streak` to 0. Immediately after the streak update, auto-transitions fire on exact-equality thresholds: an `ENGAGED` manager whose `neg_excess_streak` reaches exactly 3 drops to `WATCHLIST`; a `WATCHLIST` manager reaching exactly 6 drops to `PROBATION`; a `WATCHLIST` manager whose `nonneg_excess_streak` reaches exactly 2 recovers to `ENGAGED`; a `PROBATION` manager reaching exactly 2 recovers to `WATCHLIST`. The `WATCHLIST` ↔ `PROBATION` loop is unbounded — a manager oscillates as streaks flip.

Termination is a `BoardMember` governance action available only from `WATCHLIST` or `PROBATION`; an `ENGAGED` manager may not be terminated and the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`. Termination sets `coverage_end_quarter` to the pool's `current_quarter_index`, and the manager still owes reports for every quarter from `coverage_start_quarter` through `coverage_end_quarter` inclusive — a finalize covering those quarters requires them. A filed manager-quarter report is read back by its `report_id`.

### 3.11. Annual Reporting and the Publication Gates

A `DevelopmentOfficer` or `InvestmentOfficer` authors an annual report with `pool_id`, a `report_type` of `DONOR_FUND`, `BOARD_INVESTMENT`, or `SPENDING_COMPLIANCE`, and a `fiscal_year`. A `DONOR_FUND` report must carry `fund_id`; the other two types must leave it null — a mismatch is `ERR_INVALID_REQUEST`. A supplied `fund_id` must reference a fund of the report's pool, failing which the create is likewise rejected with `ERR_INVALID_REQUEST`. The fiscal year must already be complete: 4 times (fiscal year minus `inception_fiscal_year` plus 1) must not exceed the pool's `current_quarter_index`, failing which creation is rejected with `ERR_INCOMPLETE_FISCAL_YEAR`. The new report is `DRAFT` with `created_by_user_id` stamped and `published_by_user_id` null.

The review loop runs `DRAFT` → `UNDER_REVIEW` (submit-review by either authoring role) → back to `DRAFT` when a `BoardMember` returns it for revision, and the loop may iterate. Publication (`UNDER_REVIEW` → `PUBLISHED`) is a `BoardMember` action with four gates beyond state: the publisher's `X-User-ID` must differ from `created_by_user_id`; the fiscal-year completeness check is re-applied; every distribution in the report's scope for that fiscal year — the fund's distributions for `DONOR_FUND`, the whole pool's otherwise — must be in a terminal state, `DISTRIBUTED` or `CANCELLED`, else `ERR_INCOMPLETE_FISCAL_YEAR`; and for `BOARD_INVESTMENT` reports only, every allocation of the pool must be `IN_BAND` or have `drift_acknowledged` true, else `ERR_DRIFT_NOT_ACKNOWLEDGED`. Publication stamps `published_by_user_id`, and `PUBLISHED` is terminal. Submit-review, return-for-revision, and publish all address the annual report by its `report_id`.

### 3.12. The Unit Ledger as the System of Record

Every unit movement lands in the append-only `UnitLedgerEntry` log: `GIFT_UNITIZE` for donor gift unitizations, `REINVEST_UNITIZE` for lapse-sweep reinvestments, `DISTRIBUTION_REDEEM` for spending redemptions, and `CORPUS_REDEEM` for corpus redemptions. Each entry records its `fund_id`, the `quarter_index` it belongs to (the quarter being finalized, or the open quarter for out-of-band redemptions), its `entry_type`, the signed `units_delta_micro` movement, the signed `amount_cents` cash value, and a polymorphic `reference_id` holding the id of the record that caused the entry — the `GiftContribution` for `GIFT_UNITIZE`, the swept `ProgramPayout` for `REINVEST_UNITIZE`, the `SpendingDistribution` for `DISTRIBUTION_REDEEM`, and the `Fund` itself for `CORPUS_REDEEM` — an identity reference only, never used for ordering, since entries order by `created_at`. The ledger is the projection source for the smoothed spending base: a fund's units at the end of any quarter are derived by replaying its entries with `quarter_index` up to that quarter. A single entry is read by its `entry_id`.

## 4. Endpoint Definitions

All endpoints are mounted under `/endowment`. Creating a new resource returns HTTP 201; operations that modify an existing resource (including state transitions) return HTTP 200; reads return HTTP 200. Request and response bodies follow the envelope of §2.2, and list endpoints follow the pagination of §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /endowment/pools | Create an endowment pool (status ACTIVE, quarter 0, inception unit price) | EndowmentAdmin |
| GET | /endowment/pools | List pools with pagination; filterable by `pool_status` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/pools/{pool_id} | Read one pool (its `version` feeds OCC) | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/pools/{pool_id}/suspend | ACTIVE → SUSPENDED; blocks value-moving child operations | EndowmentAdmin |
| POST | /endowment/pools/{pool_id}/resume | SUSPENDED → ACTIVE | EndowmentAdmin |
| POST | /endowment/pools/{pool_id}/terminate | Terminate the pool; requires every fund TERMINATED | BoardMember |
| POST | /endowment/policies | Propose a spending policy version (DRAFT) | InvestmentOfficer |
| GET | /endowment/policies | List policies; filterable by `pool_id`, `policy_status` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/policies/{policy_id} | Read one policy | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/policies/{policy_id}/adopt | Board adopts a DRAFT policy; supersedes the prior latest ADOPTED; OCC on pool version | BoardMember |
| POST | /endowment/policies/{policy_id}/withdraw | Withdraw a DRAFT policy | InvestmentOfficer |
| POST | /endowment/valuations | Open a PRELIMINARY valuation for the pool's open quarter; computes the preliminary price | InvestmentOfficer |
| GET | /endowment/valuations | List valuations; filterable by `pool_id`, `valuation_status`, `supersedes_valuation_id` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/valuations/{valuation_id} | Read one valuation | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/valuations/{valuation_id}/finalize | Finalize the open quarter; runs the quarter close pipeline; OCC on pool version | InvestmentOfficer |
| POST | /endowment/valuations/{valuation_id}/supersede | Restate the latest FINAL quarter when nothing consumed it; rolls the pool back and spawns a corrective PRELIMINARY | InvestmentOfficer |
| POST | /endowment/donors | Register a donor | DevelopmentOfficer |
| GET | /endowment/donors | List donors; filterable by `donor_type` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/donors/{donor_id} | Read one donor | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/funds | Establish a fund with its donor restriction record (DRAFT until activated) | DevelopmentOfficer |
| GET | /endowment/funds | List funds; filterable by `pool_id`, `fund_status`, `spending_posture` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/funds/{fund_id} | Read one fund | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/funds/{fund_id}/activate | DRAFT → ACTIVE once pledged corpus meets the $50,000 minimum | DevelopmentOfficer |
| POST | /endowment/funds/{fund_id}/terminate | ACTIVE → TERMINATED when fully redeemed and clear of open items | BoardMember |
| POST | /endowment/funds/{fund_id}/redeem_corpus | Redeem corpus units for cash (QUASI or matured TERM only); reduces historic gift value | BoardMember |
| POST | /endowment/gifts | Record a gift or pledge (PLEDGED); CORPUS gifts immediately count toward pledged corpus | DevelopmentOfficer |
| GET | /endowment/gifts | List gifts; filterable by `fund_id`, `donor_id`, `source_payout_id`, `gift_status`, `gift_type` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/gifts/{gift_id} | Read one gift | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/gifts/{gift_id}/receive | PLEDGED → RECEIVED; stamps the open quarter and the provisional unit estimate | DevelopmentOfficer |
| POST | /endowment/gifts/{gift_id}/cancel | PLEDGED → CANCELLED; CORPUS pledges decrement pledged corpus | DevelopmentOfficer |
| POST | /endowment/gifts/{gift_id}/rescind | RECEIVED → RETURNED; compensates pledged corpus and donor totals | DevelopmentOfficer |
| POST | /endowment/distributions | Project a fund's spending distribution for a fiscal year (PROJECTED; full computation against latest FINAL data); fund must be ACTIVE | DevelopmentOfficer |
| GET | /endowment/distributions | List distributions; filterable by `fund_id`, `policy_id`, `applied_exception_id`, `fiscal_year`, `distribution_status` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/distributions/{distribution_id} | Read one distribution | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/distributions/{distribution_id}/propose | PROJECTED → PROPOSED with recomputation | DevelopmentOfficer |
| POST | /endowment/distributions/{distribution_id}/request_revision | PROPOSED → REVISION_REQUESTED (board review loop) | BoardMember |
| POST | /endowment/distributions/{distribution_id}/repropose | REVISION_REQUESTED → PROPOSED with recomputation (review loop) | DevelopmentOfficer |
| POST | /endowment/distributions/{distribution_id}/approve | PROPOSED → APPROVED; underwater funds need an APPROVED exception; segregation of duties vs proposer | BoardMember |
| POST | /endowment/distributions/{distribution_id}/distribute | APPROVED → DISTRIBUTED; redeems units at the latest FINAL price | InvestmentOfficer |
| POST | /endowment/distributions/{distribution_id}/cancel | Cancel a non-terminal distribution (board may cancel APPROVED before any payout exists) | DevelopmentOfficer, BoardMember |
| POST | /endowment/exceptions | Request an underwater-spending exception for (fund, fiscal_year) | DevelopmentOfficer |
| GET | /endowment/exceptions | List exceptions; filterable by `fund_id`, `exception_status`, `fiscal_year` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/exceptions/{exception_id} | Read one exception | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/exceptions/{exception_id}/endorse | REQUESTED → ENDORSED (investment office); endorser ≠ requester | InvestmentOfficer |
| POST | /endowment/exceptions/{exception_id}/approve | ENDORSED → APPROVED (board); three-person segregation; flips fund posture to EXCEPTION_ACTIVE | BoardMember |
| POST | /endowment/exceptions/{exception_id}/reject | REQUESTED or ENDORSED → REJECTED | BoardMember |
| POST | /endowment/exceptions/{exception_id}/rescind | APPROVED → RESCINDED; cascades revert dependent distributions and fund posture | BoardMember |
| POST | /endowment/payouts | Allocate part of a DISTRIBUTED distribution to a program (SCHEDULED) | DevelopmentOfficer |
| GET | /endowment/payouts | List payouts; filterable by `distribution_id`, `swept_gift_id`, `payout_status` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/payouts/{payout_id} | Read one payout | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/payouts/{payout_id}/disburse | SCHEDULED → DISBURSED; stamps the open quarter for lapse aging | DevelopmentOfficer |
| POST | /endowment/payouts/{payout_id}/report_spending | Program reports cumulative spending; reaching the full allocation closes the payout | ProgramManager |
| POST | /endowment/allocations/bulk_upsert | Atomically replace the pool's target allocation set; targets must sum to exactly 10000 bps | EndowmentAdmin |
| GET | /endowment/allocations | List allocations; filterable by `pool_id`, `asset_class`, `drift_status` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/allocations/{allocation_id} | Read one allocation | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/allocations/{allocation_id}/acknowledge_drift | Board acknowledges a BREACHED allocation (gates BOARD_INVESTMENT report publish) | BoardMember |
| POST | /endowment/managers | Register a manager (PROSPECT) with inclusive coverage from `coverage_start_quarter` | InvestmentOfficer |
| GET | /endowment/managers | List managers; filterable by `pool_id`, `asset_class`, `engagement_status` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/managers/{manager_id} | Read one manager | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/managers/{manager_id}/engage | PROSPECT → ENGAGED; inclusive coverage interval must not intersect same-class engaged-family managers | InvestmentOfficer |
| POST | /endowment/managers/{manager_id}/decline | PROSPECT → DECLINED | InvestmentOfficer |
| POST | /endowment/managers/{manager_id}/terminate | WATCHLIST/PROBATION → TERMINATED (board governance; ENGAGED managers cannot be terminated) | BoardMember |
| POST | /endowment/manager-quarter-reports | File a manager's quarter report; computes Dietz + simple returns and drives watchlist streaks | InvestmentOfficer |
| GET | /endowment/manager-quarter-reports | List manager reports; filterable by `manager_id`, `quarter_index` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/manager-quarter-reports/{report_id} | Read one manager report | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/reports | Author an annual report (DRAFT); fiscal year must be complete | DevelopmentOfficer, InvestmentOfficer |
| GET | /endowment/reports | List reports; filterable by `pool_id`, `fund_id`, `report_type`, `fiscal_year`, `report_status` | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/reports/{report_id} | Read one report | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| POST | /endowment/reports/{report_id}/submit_review | DRAFT → UNDER_REVIEW | DevelopmentOfficer, InvestmentOfficer |
| POST | /endowment/reports/{report_id}/return_for_revision | UNDER_REVIEW → DRAFT (board review loop) | BoardMember |
| POST | /endowment/reports/{report_id}/publish | UNDER_REVIEW → PUBLISHED; completeness gates + drift acknowledgement + segregation of duties | BoardMember |
| GET | /endowment/ledger-entries | List ledger entries; filterable by `fund_id`, `entry_type`, `quarter_index`; ordered by `created_at` ascending | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |
| GET | /endowment/ledger-entries/{entry_id} | Read one ledger entry | EndowmentAdmin, InvestmentOfficer, DevelopmentOfficer, BoardMember, ProgramManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_SEGREGATION_OF_DUTIES_VIOLATION | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_POOL_SUSPENDED | 409 |
| ERR_STALE_POOL_VERSION | 412 |
| ERR_PURPOSE_MISMATCH | 422 |
| ERR_UNDERWATER_SPENDING_BLOCKED | 422 |
| ERR_FUND_NOT_UNDERWATER | 422 |
| ERR_CORPUS_INVIOLABLE | 422 |
| ERR_DUPLICATE_RECORD | 409 |
| ERR_WINDOW_CONFLICT | 409 |
| ERR_VALUATION_OUT_OF_ORDER | 409 |
| ERR_VALUATION_LOCKED | 409 |
| ERR_INCOMPLETE_FISCAL_YEAR | 422 |
| ERR_DRIFT_NOT_ACKNOWLEDGED | 422 |
| ERR_MINIMUM_FUNDING_NOT_MET | 422 |
| ERR_POLICY_PARAM_OUT_OF_RANGE | 422 |
| ERR_ALLOCATION_SUM_INVALID | 422 |
| ERR_MANAGER_REPORT_MISSING | 422 |
| ERR_POOL_MV_MISMATCH | 422 |
| ERR_MV_CONTINUITY_BREAK | 422 |
| ERR_EXCEPTION_AMOUNT_EXCEEDS_REQUESTED | 422 |
| ERR_ALLOCATION_EXCEEDS_DISTRIBUTION | 422 |
| ERR_INVALID_SPENT_AMOUNT | 422 |
| ERR_INSUFFICIENT_UNITS | 422 |
| ERR_NO_APPLICABLE_POLICY | 422 |
| ERR_NOT_TERMINABLE | 422 |
