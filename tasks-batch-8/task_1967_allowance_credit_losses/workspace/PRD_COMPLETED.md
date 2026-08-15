# CECL Allowance API — Product Requirements Document

## 1. Introduction

Under the current expected credit loss framework, a lender can no longer wait for losses to be incurred before recognizing them: the allowance for credit losses must reflect lifetime expected losses on the portfolio, estimated afresh every reporting quarter and defended before management, auditors, and regulators. That estimation is not one calculation but a chain of judgment-laden steps — segmenting the portfolio by shared risk characteristics, blending forward-looking economic scenarios into lifetime loss rates, layering documented qualitative overlays, carving out impaired exposures for individual analysis, reviewing and adjusting the result under strict segregation of duties, and finally rolling the allowance forward into a disclosure that survives audit. Each step leaves an evidential trail, and each number must be reproducible to the cent.

This document specifies the CECL Allowance API, the system that operationalizes that chain end to end. All resources are mounted under `/cecl`. Four segregated roles divide the work: analysts prepare portfolio data and quarterly runs, model validators govern the loss models and economic scenarios, the chief credit officer holds approval authority, and an external auditor signs off the resulting disclosure. The API also closes the loop on model risk management: every model is back-tested against observed outcomes, and repeated breaches force a governed model refresh that preserves full version lineage.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, formats, and conventions that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles: `CreditAnalyst`, `ModelValidator`, `ChiefCreditOfficer`, and `ExternalAuditor`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

For each of the four roles — `CreditAnalyst`, `ModelValidator`, `ChiefCreditOfficer`, and `ExternalAuditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires accountability (for example, as `executed_by_user_id` on a model run or `created_by_user_id` on a management adjustment) but never compares it against any entity's `id`.

The division of labor follows a segregation-of-duties model. A `CreditAnalyst` prepares portfolio data and quarterly runs: segments, loans, charge-offs and recoveries, qualitative factor drafting and documentation, run creation, execution and submission, individual evaluation preparation, management adjustment proposals, and disclosure preparation. A `ModelValidator` owns model governance: the loss model lifecycle, economic scenarios, back-testing, and model refresh. A `ChiefCreditOfficer` holds approval authority: qualitative factor approval and retirement, run approval, rework and finalization, evaluation review and reopen, and management adjustment decisions. An `ExternalAuditor` is read-only across the system except for disclosure sign-off and return-for-revision. All read endpoints are shared by all four roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Malformed or out-of-range pagination values are never rejected: a non-integer `limit` or `offset` falls back to its default, a `limit` below 1 is clamped to 1, a `limit` above 100 is clamped to 100, and a negative `offset` is clamped to 0. Every list endpoint returns its resources sorted by creation timestamp in ascending order, and the `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — loss models, portfolio segments, loans, economic scenarios, qualitative factors, model runs, individual evaluations, management adjustments, and disclosure reports — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on any change to the resource's properties, including server-initiated changes driven by cascades. The `version` is a system-managed integer that increments by one on every mutation of the resource and anchors the optimistic concurrency checks described in §2.7. At creation a resource's `version` is 1 and its `updated_at` equals its `created_at`.

Back-test results are the one exception: a back-test result carries only `id` and `created_at`. Both `updated_at` and `version` are absent from it, because a recorded back-test is an immutable observation that is never modified after creation.

### 2.5. Reporting Periods, Quarter Arithmetic, and Effective Windows

The system's calendar is the fiscal quarter. Any period string in the API — an `as_of_period`, an `effective_from_period`, an `effective_to_period`, a `backtest_period`, a `charge_off_period`, or a `recovery_period` — must match the format `YYYY-Qn` with the quarter number n between 1 and 4; a malformed period string is rejected with `ERR_INVALID_REQUEST` (HTTP 400). All chronological comparisons between periods are made by converting each period to its quarter index, defined as the year multiplied by four plus the quarter number minus one; "earlier", "later", and "between" in this document always refer to that index.

Two kinds of effective windows exist, and they differ in inclusivity. An economic scenario covers a half-open window: it applies to every quarter whose index is at least the index of its `effective_from_period` and strictly less than the index of its `effective_to_period`, and the `effective_to_period` must be strictly after the `effective_from_period`. A qualitative factor covers a closed window: both its `effective_from_period` quarter and its `effective_to_period` quarter are included. Because of this difference, two scenario windows that merely touch — one ending exactly where the other begins — never overlap, while two factor windows are considered adjacent only when one factor's last covered quarter immediately precedes the other's first covered quarter.

### 2.6. Monetary Amounts, Basis Points, and Rounding Discipline

All monetary amounts in the API are integers denominated in cents, and all rates are integers denominated in basis points — ten-thousandths of a whole, so that five hundred basis points mean 5.00 percent. Every rounding performed anywhere in the system is round half up: a fraction of exactly one half or greater rounds away from zero, anything smaller rounds toward zero.

Two rounding commitments deserve emphasis because audit reproduction depends on them. First, intermediate arithmetic is exact: scenario blending, reversion averaging, and present-value discounting are carried out with no intermediate rounding, and rounding happens only at the pinned steps named in §3. Second, run-level money totals are sums of components that have already been rounded to whole cents per segment or per evaluation; the sum itself is never re-rounded. A re-implementation that rounds at different points will produce different cents, and the system treats those cents as contractual.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each names its own version field and its own rejection error.

Proposing a management adjustment against a model run requires the request to carry `expected_model_run_version`, a non-optional input holding the run's `version` as the client last observed it. The check is exact equality: if the supplied value does not equal the run's current `version` — in practice because an execution, submission, approval, rework, finalization, or an earlier adjustment proposal or approval has mutated the run since the client last read it — the proposal is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot write against a run state it has not observed.

Updating an individual evaluation requires the request to carry `expected_evaluation_version`, a non-optional input holding the evaluation's `version` as the client last observed it. Here too the check is exact equality: if the supplied value does not equal the evaluation's current `version`, the update is rejected with `ERR_EVALUATION_STALE_VERSION` (HTTP 412).

Endpoints other than these two take no version field at all; optimistic concurrency applies exactly where listed and nowhere else.

### 2.8. Segregation of Duties and Recorded Operator Identity

Because every role's identity is opaque, accountability is enforced by recording the caller's `X-User-ID` on the resources they move and by comparing those recorded identifiers at approval time. Executing a model run records the acting analyst as the run's `executed_by_user_id`; approving that run requires a different operator — if the approver's `X-User-ID` equals the recorded `executed_by_user_id`, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) — and a successful approval records the approver as `approved_by_user_id`. The same discipline governs management adjustments: proposing one records the proposer as `created_by_user_id`, and the decision to approve it must come from a different operator, with the same `ERR_SEGREGATION_OF_DUTIES` rejection when the approver is the creator; whichever way a pending adjustment is decided, the decider is recorded as `resolved_by_user_id`. The comparison is always between the two header values themselves, never against any persisted entity.

### 2.9. Validation Order

Every request is checked against the same ordered ladder of validations, and when a request fails several rungs at once, the response always carries the error of the earliest rung it fails. Where §3 pins a more specific check order for a particular endpoint — loss-model creation, loan booking, and recovery recording — that endpoint-local order governs. The ladder is:

1. Authentication context: `X-User-ID` and `X-User-Role` are present and the role is one of the four declared roles, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorization: the caller's role is permitted on this endpoint, else `ERR_FORBIDDEN_FOR_ROLE`.
3. Path existence: every identifier in the request path is resolved against existing resources in left-to-right order, and the first identifier that does not resolve rejects the whole request with `ERR_NOT_FOUND` (HTTP 404) before any later identifier — or any body rule — is examined.
4. Request body shape: required fields are present, types are valid, enum members belong to their declared sets, and period strings match the quarterly format, else `ERR_INVALID_REQUEST`. Unknown fields and system-managed fields supplied in a request body are ignored rather than rejected. Identifiers carried in the request body rather than the path — a loan's or factor's `segment_id`, a run's `loss_model_id`, or a `scenario_id` entry inside `scenario_weights` — that do not resolve to an existing resource are likewise rejected here with `ERR_INVALID_REQUEST` (HTTP 400), not `ERR_NOT_FOUND`.
5. State-transition legality: the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Any transition attempted from a state other than its declared source state fails here.
6. Optimistic concurrency: on the two guarded writes of §2.7, the supplied expected version must equal the parent's current version, else `ERR_STALE_VERSION` or `ERR_EVALUATION_STALE_VERSION` as applicable.
7. Segregation of duties: the approver differs from the executor or creator, per §2.8, else `ERR_SEGREGATION_OF_DUTIES`.
8. Period-forward discipline: a new model run's period must be strictly later than every finalized run's period, else `ERR_PERIOD_NOT_FORWARD`.
9. Referenced configuration usability: the referenced loss model is active, the referenced segment is open, and every referenced scenario is active, else the corresponding `ERR_MODEL_NOT_ACTIVE`, `ERR_SEGMENT_NOT_OPEN`, or `ERR_SCENARIO_NOT_ACTIVE`.
10. Structural business rules: weight sums, window overlaps, reversion configuration, uniqueness of business identifiers, in-use gating, documentation minimums, and workflow gating, each carrying its own error identifier introduced in §3.
11. Fiscal amount sanity: charge-off, recovery, and adjustment amounts stay within their monetary bounds, else the corresponding amount error of §3.

The ordering is observable behavior: a doubly-invalid request — say, one with a stale version and a segregation-of-duties violation — surfaces the stale-version error, because rung six is evaluated before rung seven.

### 2.10. Cascading Consistency

Several operations deliberately mutate more than one resource, and the system treats each cascade as part of the same atomic operation. Recording a charge-off can ripple from a loan to its segment's cumulative counters, from there to the segment's watch status, and from there onto every draft model run's review flag — three hops from one client call. Executing a model run both snapshots segment-level computations and spawns a family of individual evaluations. Approving an adjustment re-derives the parent run's totals. Activating a loss model retires whichever other model was active. Finalizing a run spawns its disclosure report. Two principles govern all such cascades: every mutated resource, primary or collateral, has its `updated_at` refreshed and its `version` incremented; and derived totals are always re-derived from their current components rather than adjusted incrementally, so repeated operations cannot drift the totals away from the true sum of their parts.

## 3. Business Logic & Workflows

### 3.1. Loss Model Governance: Lifecycle, Back-Testing, and Refresh

A `ModelValidator` authors a loss model by supplying its `name`, its lifetime loss `method` — one of `LOSS_RATE`, `DISCOUNTED_CASH_FLOW`, or `VINTAGE` — and the forecasting configuration that shapes every run the model will drive. The `forecast_period_quarters` sets the reasonable and supportable forecast horizon and must be between one and eight quarters. The `reversion_method` declares how loss rates return to the historical anchor beyond that horizon: `IMMEDIATE` or `STRAIGHT_LINE`. The `reversion_period_quarters` completes the pair, and the three values are validated together: an `IMMEDIATE` method requires a reversion period of exactly zero, a `STRAIGHT_LINE` method requires a reversion period between one and four quarters, and the forecast horizon plus the reversion period together may never exceed eight quarters. A configuration violating any of these three rules is rejected with `ERR_INVALID_REVERSION_CONFIG` (HTTP 422); a `forecast_period_quarters` outside the one-to-eight range is rejected with the same error, as part of the same configuration validation. The `historical_lookback_quarters`, between one and forty, sets the window used for historical rate anchoring; it is validated after the reversion configuration — so a request failing both surfaces `ERR_INVALID_REVERSION_CONFIG` — and an out-of-range lookback on its own is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

A new model is born in `DRAFT` with `version_label` set to `v1`, `parent_model_id` null, `consecutive_backtest_breach_count` zeroed, and `refresh_required` false. Activation is the act that puts a model into production: a `ModelValidator` activates a `DRAFT` model, moving it to `ACTIVE`, and any other loss model that happens to be `ACTIVE` at that moment is automatically retired to `RETIRED` — at most one model is ever in production. Retiring a model outright moves it from `ACTIVE` to `RETIRED`, but only while no in-flight run references it: a run in `DRAFT`, `EXECUTED`, `UNDER_REVIEW`, or `APPROVED` blocks retirement with `ERR_MODEL_IN_USE` (HTTP 409), while `FINALIZED` runs, being settled history, do not.

Back-testing closes the governance loop. A `ModelValidator` records a back-test by supplying the `backtest_period` being examined and the observed `actual_loss_rate_bps` for that period, an integer between zero and ten thousand — an out-of-range rate is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The system then selects the run to test against: among this model's own runs that are `FINALIZED` and whose `as_of_period` quarter index is at most the back-test period's quarter index, the one with the greatest quarter index is selected; the period-forward rule of §3.6 guarantees that periods are unique among finalized runs, so no tie-break ever arises. When no run qualifies, the back-test is refused with `ERR_NO_FINALIZED_RUN` (HTTP 409). The recorded result carries the `loss_model_id`, the supplied `backtest_period` and `actual_loss_rate_bps`, the selected run's identifier as `backtested_run_id` — stored as plain data, not a managed reference — and three computed figures. The `predicted_loss_rate_bps` is the selected run's `total_allowance_cents` multiplied by ten thousand and divided by its `total_exposure_cents`, rounded half-up to a whole basis point; if the selected run's `total_exposure_cents` is zero, the predicted rate is zero. The `variance_bps` is the supplied `actual_loss_rate_bps` minus that predicted rate. The `outcome` is `BREACH` when the absolute value of the variance is strictly greater than one hundred fifty basis points; a variance of exactly one hundred fifty basis points in either direction is still a `PASS`.

Outcomes feed back into the model. On a `BREACH`, the model's `consecutive_backtest_breach_count` increments by one, and if the count thereby reaches two, the model's `refresh_required` flag is set true — the formal signal that the model can no longer be trusted without recalibration. On a `PASS`, the count resets to zero while `refresh_required` is left untouched. A model's recorded back-tests can be listed to reconstruct its track record.

Refresh is the remediation path, and it is gated: refresh is only possible from `ACTIVE` — refreshing a `DRAFT` or `RETIRED` model is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), a check that precedes the flag gate — and refreshing an `ACTIVE` model whose `refresh_required` flag is false is rejected with `ERR_REFRESH_NOT_REQUIRED` (HTTP 409). A refresh never mutates the old model's configuration; instead it creates a new loss model in `DRAFT` whose `parent_model_id` points back at the refreshed model, whose `version_label` increments the lineage — `v1` begets `v2`, `v2` begets `v3` — and whose configuration fields are copied from the parent. The refreshed model itself remains `ACTIVE`; its `refresh_required` flag clears to false and its `consecutive_backtest_breach_count` resets to zero. The model catalog can be listed with `status` and `parent_model_id` filters, which is how reviewers trace a refresh lineage across generations.

### 3.2. Portfolio Segmentation

Collective reserving begins with segmentation: loans that share risk characteristics are pooled so that one loss rate speaks for the pool. A `CreditAnalyst` creates a portfolio segment with a `segment_code` — a business identifier that must be globally unique, with duplicates rejected as `ERR_DUPLICATE_SEGMENT_CODE` (HTTP 409) — a display `name`, a `product_type` of `CREDIT_CARD`, `AUTO`, `MORTGAGE`, `SMALL_BUSINESS`, or `PERSONAL`, a `risk_rating_band` of `PRIME`, `NEAR_PRIME`, `SUBPRIME`, or `DEEP_SUBPRIME`, and the `vintage_year` of origination.

The risk band anchors the segment's economics: `base_loss_rate_bps` is a computed base annual lifetime loss rate of 50 basis points for `PRIME`, 150 for `NEAR_PRIME`, 400 for `SUBPRIME`, and 900 for `DEEP_SUBPRIME`. Riskier bands carry a base rate that is a fixed multiple of safer ones, and this rate is the starting point to which scenario multipliers and qualitative overlays are later applied.

Every segment also carries a running fiscal memory. The `origination_total_cents` accumulates the initial amortized cost of every loan ever booked into the segment and is never decremented, even by charge-offs, because it is the denominator against which loss experience is measured. The `ytd_gross_charge_offs_cents` and `ytd_recoveries_cents` counters track cumulative gross charge-offs and cumulative recoveries against prior charge-offs. From these three counters the system derives `charge_off_rate_bps`, the segment's observed loss intensity, per the rule in §3.3. A segment's `status` is `OPEN` when healthy and `WATCH` when its loss experience has crossed the watch threshold; the transition is always system-driven, never requested directly. The loans booked into a segment, and the qualitative factors attached to it, are each reachable as lists hanging off the segment.

### 3.3. Loan Intake, Charge-Offs, and Recoveries

A `CreditAnalyst` books a loan into a segment by supplying the target `segment_id`, a globally unique `loan_number` (duplicates are rejected with `ERR_DUPLICATE_LOAN_NUMBER`, HTTP 409), the current `amortized_cost_cents` — which must be greater than zero — and the loan's `risk_rating` of `PASS`, `SPECIAL_MENTION`, `SUBSTANDARD`, `DOUBTFUL`, or `LOSS`. Two optional inputs complete the picture: `delinquency_days`, the days past due, which defaults to zero and may never be negative, and `collateral_value_cents`, the appraised collateral value, which likewise defaults to zero and may never be negative. Booking is only possible into an `OPEN` segment; a segment sitting in `WATCH` refuses new loans with `ERR_SEGMENT_NOT_OPEN` (HTTP 409), and the `loan_number` uniqueness check is enforced before this segment-open gate, so a request failing both surfaces `ERR_DUPLICATE_LOAN_NUMBER`. Creation does two things atomically: the loan starts life `ACTIVE` with `charged_off_total_cents` and `recovered_total_cents` zeroed, and the segment's `origination_total_cents` grows by the loan's amortized cost. The segment's `charge_off_rate_bps` is recomputed at booking as well, per the rule below, so a growing origination denominator dilutes the observed rate.

At booking time the system also computes `individually_evaluated`, the flag that decides whether the loan will be reserved collectively or analyzed on its own. A loan is individually evaluated when its `risk_rating` is `SUBSTANDARD`, `DOUBTFUL`, or `LOSS`, or when its `amortized_cost_cents` is at least one hundred million cents — one million dollars. The boundary is inclusive: a loan whose amortized cost equals the threshold exactly is individually evaluated. Individually evaluated loans are excluded from the collective reserve and instead receive a per-loan analysis during each model run.

Credit events are recorded against the loan by a `CreditAnalyst`. A charge-off carries the `charge_off_amount_cents` and the `charge_off_period` the loss belongs to. The amount must be at least one cent and no more than the loan's current `amortized_cost_cents`; anything outside that range is rejected with `ERR_CHARGE_OFF_EXCEEDS_BALANCE` (HTTP 422). When the amount is less than the balance, the charge-off is partial: the loan stays `ACTIVE`, its `amortized_cost_cents` is reduced by the amount, and its `charged_off_total_cents` grows by the amount. When the amount equals the balance exactly, the charge-off is full: the amortized cost falls to zero and the loan transitions `ACTIVE` → `CHARGED_OFF`, which is terminal.

Either way, the charge-off then cascades beyond the loan. As the first hop, the segment's `ytd_gross_charge_offs_cents` grows by the charged-off amount. As the second hop, the segment's `charge_off_rate_bps` is recomputed as net charge-offs — `ytd_gross_charge_offs_cents` minus `ytd_recoveries_cents` — multiplied by ten thousand and divided by `origination_total_cents`, rounded half-up to a whole basis point, or zero outright when the segment's origination total is zero; if that recomputed rate is strictly greater than two hundred basis points and the segment is `OPEN`, the segment moves `OPEN` → `WATCH`. The comparison is strict: a rate of exactly two hundred basis points leaves an `OPEN` segment open. As the third hop, the moment a segment enters `WATCH`, every model run currently in `DRAFT` has its `needs_segmentation_review` flag set true — an informational warning that the segmentation those runs were drafted against has deteriorated — and every such run is touched by the cascade, its `updated_at` refreshed and its `version` incremented, whether or not its flag was already set.

Recoveries unwind the same machinery. A recovery carries the `recovery_amount_cents` — at least one cent, with a sub-one-cent amount rejected as `ERR_RECOVERY_EXCEEDS_CHARGE_OFF` (HTTP 422) — and the `recovery_period`. This amount floor is enforced first, before the nothing-to-recover state check and the cumulative cap that follow. On a `CHARGED_OFF` loan, the cap is cumulative: the loan's `recovered_total_cents` plus the new amount may not exceed its `charged_off_total_cents`, else the request is rejected with `ERR_RECOVERY_EXCEEDS_CHARGE_OFF` (HTTP 422). A recovery may also be recorded against an `ACTIVE` loan that was partially charged off; there is simply nothing to recover when the loan's `charged_off_total_cents` is zero, and such a request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), while the same cumulative cap applies otherwise. Recording the recovery grows the loan's `recovered_total_cents` by the amount, grows the segment's `ytd_recoveries_cents` by the amount, and recomputes the segment's charge-off rate exactly as above — this time in the healing direction: when the recomputed rate is two hundred basis points or less and the segment sits in `WATCH`, it returns `WATCH` → `OPEN`.

### 3.4. Economic Scenarios and the Forecast Multiplier

Scenarios are the forward-looking ingredient of the estimate. A `ModelValidator` authors an economic scenario with a `name`, a `scenario_type` of `BASELINE`, `ADVERSE`, or `OPTIMISTIC`, a forecast `unemployment_rate_bps`, a forecast `gdp_growth_bps` — which may be negative in a contraction — and the half-open effective window from `effective_from_period` to `effective_to_period`. A window whose end is not strictly after its start is rejected with `ERR_INVALID_REQUEST`. New scenarios are born `ACTIVE`.

The window discipline is what keeps the scenario library coherent: among `ACTIVE` scenarios of the same `scenario_type`, the half-open windows may never overlap, and any attempt to create one that does is rejected with `ERR_SCENARIO_WINDOW_OVERLAP` (HTTP 409). Touching is not overlapping — one scenario's `effective_to_period` may equal another's `effective_from_period`, because the first window stops just before the second begins. Scenarios of different types are free to cover the same quarters; that is how a baseline and its adverse twin coexist.

When a scenario outlives its usefulness, a `ModelValidator` archives it, moving it `ACTIVE` → `ARCHIVED`. Archiving is blocked while any in-flight run — one in `DRAFT`, `EXECUTED`, `UNDER_REVIEW`, or `APPROVED` — still references the scenario in its `scenario_weights`, and such an attempt is rejected with `ERR_SCENARIO_IN_USE` (HTTP 409). A `FINALIZED` run's references are settled history and never block archiving.

Each scenario drives a loss multiplier through a fixed sensitivity law. The multiplier in basis points starts from a neutral ten thousand. It then rises by twenty basis points for every basis point by which the scenario's `unemployment_rate_bps` exceeds the neutral unemployment anchor of five hundred basis points — a forecast below the anchor turns this term negative and pulls the multiplier down. It likewise rises by ten basis points for every basis point by which the neutral growth anchor of two hundred basis points exceeds the scenario's `gdp_growth_bps` — growth above the anchor turns this term negative. The result is clamped last, after both sensitivity terms are applied: the multiplier never falls below five thousand basis points, half the neutral level, and never exceeds thirty thousand basis points, three times the neutral level. All of this arithmetic is exact integer work in basis points; nothing is rounded.

### 3.5. The Qualitative Factor Framework

Quantitative output rarely captures everything a credit committee knows, so the framework allows documented, bounded overlays at the segment level. A `CreditAnalyst` drafts a qualitative factor by naming the target `segment_id`, a `factor_code` classifying the concern — `CONCENTRATION_RISK`, `POLICY_CHANGE`, `ECONOMIC_UNCERTAINTY`, `COLLATERAL_VALUATION`, or `MODEL_LIMITATION` — a signed `adjustment_bps` between negative two thousand and positive two thousand basis points that is never zero (a value outside the range or equal to zero is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and the closed effective window from `effective_from_period` through `effective_to_period`, both ends inclusive; the to-period may not precede the from-period — though it may equal it, making a single-quarter window — and an inverted window is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A `documentation_text` may be attached at drafting and defaults to empty. The new factor starts in `DRAFT`.

One structural rule keeps overlays auditable: within the same pairing of segment and factor code, the closed windows of factors that are not `RETIRED` may never overlap. Because the windows are closed, adjacency means one factor's last covered quarter immediately precedes the other's first covered quarter — that arrangement is allowed — but any true intersection is rejected with `ERR_FACTOR_WINDOW_OVERLAP` (HTTP 409). Factors with different codes, or attached to different segments, are unaffected by each other's windows.

A factor earns its influence through a documentation-and-approval chain. A `CreditAnalyst` moves a `DRAFT` factor to `DOCUMENTED` by attaching the supporting narrative: the supplied `documentation_text` must have a trimmed length of at least fifty characters, and a thinner rationale is rejected with `ERR_FACTOR_DOCUMENTATION_INSUFFICIENT` (HTTP 422); the accepted text is stored on the factor. A `ChiefCreditOfficer` then approves it, moving it `DOCUMENTED` → `APPROVED`, and only `APPROVED` factors ever enter a run's overlay. Retirement, also by a `ChiefCreditOfficer`, moves an `APPROVED` factor to `RETIRED`; retired factors are excluded from the qualitative adjustment of all future runs, though their historical effect on past finalized runs is untouched. A segment's factors can be listed with a `status` filter to survey what is in force.

### 3.6. The Quarterly Model Run

The model run is the quarter's estimation event. A `CreditAnalyst` opens one by naming the `as_of_period` being estimated, the `loss_model_id` of the model to drive it, and the `scenario_weights` — a list of entries, each pairing a `scenario_id` with a positive integer `weight_bps`, where the weights must sum to exactly ten thousand basis points. The same scenario may appear in more than one entry; each entry then participates in the blend independently. A list whose weights sum to anything else, or that contains a non-positive weight, is rejected with `ERR_WEIGHT_SUM_INVALID` (HTTP 422); the accepted weights are pinned at creation and do not drift thereafter. Three gates guard creation: the `as_of_period` must be strictly later than every `FINALIZED` run's `as_of_period`, else `ERR_PERIOD_NOT_FORWARD` (HTTP 409) — history is never re-estimated; the referenced model must be `ACTIVE`, else `ERR_MODEL_NOT_ACTIVE` (HTTP 409); and every scenario named in the weights must be `ACTIVE`, else `ERR_SCENARIO_NOT_ACTIVE` (HTTP 409). The run begins in `DRAFT` with all counters zeroed, an empty `segments_breakdown`, empty `rework_notes`, and `executed_by_user_id`, `approved_by_user_id`, and `model_version_label` all null; runs can be listed with `loss_model_id`, `status`, and `as_of_period` filters to survey the pipeline.

Execution is where the estimate is computed, performed by a `CreditAnalyst` moving the run `DRAFT` → `EXECUTED`; the referenced model must still be `ACTIVE` at that moment, else `ERR_MODEL_NOT_ACTIVE`. Execution first computes the per-segment quantitative reserve. For each segment, a blended scenario multiplier M is derived from the pinned weights. When the weights hold exactly one entry, M is that scenario's multiplier — computed per §3.4 — divided by ten thousand: an exact decimal with no weighting applied. When the weights hold two or more entries, each entry's `weight_bps` is multiplied by its scenario's multiplier, the products are summed, and the sum is divided by ten thousand and then by ten thousand again, again yielding M as an exact decimal; because the weights blend the multipliers, the same portfolio under a weighted blend produces a different rate than under a single scenario. The multiplier then reverts to the historical anchor, a neutral multiplier of exactly 1.0, across a remaining life of eight quarters. Under an `IMMEDIATE` reversion method, the effective horizon multiplier E averages the eight quarters of remaining life with the forecast multiplier holding for the horizon and neutral thereafter: E is the model's `forecast_period_quarters` times M, plus the product of eight minus the forecast horizon and exactly 1.0, all divided by eight. Under `STRAIGHT_LINE`, the multiplier steps down from M toward 1.0 in equal increments across the reversion period: during reversion quarter i, counting from one up to the model's `reversion_period_quarters`, the multiplier is M minus the following step-down amount: (M minus 1.0) multiplied by i and then divided by the reversion period plus one. E is then the forecast horizon times M, plus the sum of those reversion-quarter multipliers, plus the product of the quarters of the eight-quarter life covered by neither the forecast horizon nor the reversion period and exactly 1.0, all divided by eight. All intermediate arithmetic is exact; nothing is rounded until the pinned steps. The segment's `lifetime_loss_rate_bps` is its `base_loss_rate_bps` multiplied by E, rounded half-up to a whole basis point. Its collective exposure is the sum of `amortized_cost_cents` over its loans that are `ACTIVE` and not individually evaluated. Its quantitative reserve is that exposure multiplied by the lifetime loss rate and divided by ten thousand, rounded half-up to a whole cent. The rounding order is pinned: the rate is rounded to whole basis points first, and only then is the per-segment reserve rounded to whole cents.

The qualitative overlay is then applied per segment. The overlay in basis points is the sum of `adjustment_bps` over the segment's factors that are `APPROVED` and whose closed effective window covers the run's `as_of_period` — the from-quarter's index is at most the run's index, and the run's index is at most the to-quarter's index. The segment's qualitative adjustment in cents is its collective exposure multiplied by the overlay basis points and divided by ten thousand, rounded half-up to a whole cent. A floor then protects the segment: when the quantitative reserve plus the qualitative adjustment would be negative, the adjustment is set to the exact negative of the quantitative reserve, so the segment's allowance lands at zero and never below. The segment's allowance is its quantitative reserve plus its qualitative adjustment.

Execution records everything it did. The run's `segments_breakdown` snapshot holds one row per segment, in ascending segment creation order, each row carrying the segment's `segment_id`, its `exposure_cents`, the `base_loss_rate_bps` drawn from its band, the blended `scenario_mult_bps`, the post-reversion `effective_mult_bps`, the resulting `lifetime_loss_rate_bps`, the overlay `qualitative_bps`, and the rounded money figures `quantitative_reserve_cents`, `qualitative_adjustment_cents`, and `segment_allowance_cents`. The two snapshot multiplier figures are whole basis points: `scenario_mult_bps` is the single scenario's exact integer multiplier when the weights hold one entry, and the blended multiplier times ten thousand rounded half-up otherwise; `effective_mult_bps` is the post-reversion multiplier times ten thousand, rounded half-up. One individual evaluation is created for every `ACTIVE` loan whose `individually_evaluated` flag is true, in ascending loan creation order — each starting in `DRAFT` with method `COLLATERAL_FAIR_VALUE`, its `collateral_value_cents` copied from the loan, an empty `expected_quarterly_cash_flows_cents`, a null `discount_rate_bps`, empty `analysis_notes`, and its `specific_reserve_cents` computed immediately under the collateral method — and `individual_evaluation_count` records how many were created. The driving model's `version_label` is pinned onto the run as `model_version_label`, the executor's header identity is recorded as `executed_by_user_id`, and the run's `version` increments.

Run totals are assembled from the rounded parts, per the discipline of §2.6. The run's `quantitative_reserve_cents` is the sum of the per-segment quantitative reserves, each already rounded to whole cents before summing; `qualitative_adjustment_cents` is the corresponding sum of per-segment qualitative adjustments. The `individual_reserve_cents` is the sum of `specific_reserve_cents` across the run's evaluations, re-synced on every evaluation mutation. The `management_adjustment_cents` is the sum of `amount_cents` across the run's `APPROVED` adjustments. The `total_allowance_cents` is the sum of those four components, and `total_exposure_cents` is the sum of the per-segment collective exposures plus the amortized cost of every individually evaluated `ACTIVE` loan. An allowance-summary read exposes the run's `as_of_period`, `total_exposure_cents`, each of the four allowance components, the `total_allowance_cents`, and the full `segments_breakdown`, giving reviewers the complete bridge from exposure to allowance.

From `EXECUTED`, a `CreditAnalyst` submits the run for review, moving it `EXECUTED` → `UNDER_REVIEW`; every one of the run's individual evaluations must be `REVIEWED` at that point, else the submission is rejected with `ERR_EVALUATIONS_OUTSTANDING` (HTTP 409) — a run with zero evaluations satisfies this vacuously — and the run's `version` increments. A `ChiefCreditOfficer` then approves it, `UNDER_REVIEW` → `APPROVED`, subject to the segregation-of-duties rule of §2.8; the approver is recorded as `approved_by_user_id` and the version increments. Alternatively, the chief credit officer sends the run back, `UNDER_REVIEW` → `EXECUTED`, with `rework_notes` stored on the run for the analysts; this rework cycle can repeat as often as needed, and each pass increments the version.

### 3.7. Individual Evaluations and Management Adjustments

An individual evaluation is the per-loan counterpart to the collective reserve, joining one model run to one loan through its `run_id` and `loan_id`. While an evaluation is `DRAFT` or `SUBMITTED`, a `CreditAnalyst` may refine it: switching its `method` between `COLLATERAL_FAIR_VALUE` and `DISCOUNTED_CASH_FLOW`, adjusting the `collateral_value_cents`, supplying the `expected_quarterly_cash_flows_cents` and `discount_rate_bps` that the cash-flow method needs, or revising the `analysis_notes` narrative. Updated inputs must be non-negative: a negative `collateral_value_cents`, a negative `discount_rate_bps`, or a negative entry in `expected_quarterly_cash_flows_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every such update must carry the OCC guard `expected_evaluation_version` per §2.7, and every accepted update recomputes the evaluation's `specific_reserve_cents`, re-syncs the parent run's `individual_reserve_cents` and `total_allowance_cents`, and increments the evaluation's `version`. Choosing the `DISCOUNTED_CASH_FLOW` method makes its inputs mandatory: a `DISCOUNTED_CASH_FLOW` evaluation without a non-empty `expected_quarterly_cash_flows_cents` list and a `discount_rate_bps` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The inputs may be supplied in the same request as the method switch or retained from earlier updates; the requirement applies to the merged result.

The specific reserve follows the chosen method, and the two methods answer the same question — how much of the amortized cost is not expected to be recovered — with different evidence. Under `COLLATERAL_FAIR_VALUE`, the reserve is driven by liquidation value: the net collateral is the evaluation's `collateral_value_cents` minus a cost-to-sell haircut, where the haircut is the collateral value multiplied by one thousand basis points — ten percent — divided by ten thousand and rounded half-up to whole cents; the `specific_reserve_cents` is then the loan's `amortized_cost_cents` minus that net collateral, floored at zero. Under `DISCOUNTED_CASH_FLOW`, the reserve is driven by the present value of expected collections: the quarterly discount rate is the `discount_rate_bps` divided by ten thousand, and the present value is the sum, over each quarter t from one to the number of entries in `expected_quarterly_cash_flows_cents`, of that quarter's expected cash flow divided by one plus the quarterly rate raised to the power t; this sum is computed exactly and rounded half-up to whole cents once at the end, and the `specific_reserve_cents` is the loan's `amortized_cost_cents` minus that rounded present value, floored at zero. Identical loan data under the two methods yields different reserves; that divergence is intentional and is why the method choice is a documented judgment.

The evaluation's own workflow runs `DRAFT` → `SUBMITTED` → `REVIEWED`, with a reopen cycle back from `REVIEWED` to `SUBMITTED`, and every step is gated on the parent run still being workable — `EXECUTED` or `UNDER_REVIEW`; once the run has moved on, evaluation changes are rejected with `ERR_INVALID_STATE_TRANSITION`. Submission by a `CreditAnalyst` additionally requires the `analysis_notes` to be non-empty after trimming, else `ERR_ANALYSIS_DOCUMENTATION_REQUIRED` (HTTP 422); a successful submission re-syncs the run's individual reserve and total allowance. Review by a `ChiefCreditOfficer` recomputes the run's `reviewed_evaluation_count` — the number of the run's evaluations currently in `REVIEWED` — and re-syncs the same run totals. Reopening, also by a `ChiefCreditOfficer` and carrying a `reopen_reason` that must be non-empty after trimming — else `ERR_INVALID_REQUEST` (HTTP 400) — returns the evaluation to `SUBMITTED` and recomputes the reviewed count, so the count always reflects the live set. Every evaluation mutation — update, submission, review, or reopen — also increments the parent run's `version`. Evaluations can be listed with `run_id`, `loan_id`, and `status` filters, which is how an analyst inventories what a run still owes.

Management adjustments are the governed escape valve for judgment the model cannot express. A `CreditAnalyst` proposes one against a run while the run is `EXECUTED` or `UNDER_REVIEW` — a proposal against a run in any other status is rejected with `ERR_INVALID_STATE_TRANSITION` — supplying a signed `amount_cents` and a `rationale` that must be non-empty after trimming, with an empty or whitespace-only rationale rejected with `ERR_INVALID_REQUEST` (HTTP 400). The proposal is guarded twice: by OCC through `expected_model_run_version` per §2.7, and by a proportionality cap. The cap is computed from the parent run's current subtotal — its `quantitative_reserve_cents` plus `qualitative_adjustment_cents` plus `individual_reserve_cents` — as ten percent of that subtotal, rounded half-up to whole cents. An adjustment is accepted only when its absolute value is at least one cent and no more than the cap; a zero amount is rejected with `ERR_ZERO_ADJUSTMENT` (HTTP 422), and an amount whose absolute value exceeds the cap is rejected with `ERR_ADJUSTMENT_EXCEEDS_CAP` (HTTP 422), while an amount exactly equal to the cap is accepted. An accepted proposal starts `PENDING`, records its proposer as `created_by_user_id` with `resolved_by_user_id` null until decided, and — because it mutates the run — increments the run's `version`, so the next writer against that run must observe the new version. A run's adjustments can be listed with a `status` filter.

The decision rests with a `ChiefCreditOfficer`. Approval moves an adjustment `PENDING` → `APPROVED`, requires the parent run to be `EXECUTED` or `UNDER_REVIEW` else `ERR_INVALID_STATE_TRANSITION`, and enforces the segregation-of-duties rule of §2.8 against the recorded `created_by_user_id`. Approval re-syncs the run: the approved `amount_cents` flows into `management_adjustment_cents`, `total_allowance_cents` is recomputed, the run's `version` increments, and the decider is recorded as `resolved_by_user_id`. Rejection moves an adjustment `PENDING` → `REJECTED` and never touches the run's totals; precisely because it is fiscally inert, rejection remains available even after the run has reached `APPROVED` — where the parent-run gate widens to `EXECUTED`, `UNDER_REVIEW`, or `APPROVED` — so that a stale pending proposal can always be cleared out of the way of finalization. The rejecter is likewise recorded as `resolved_by_user_id`.

### 3.8. Finalization, Disclosure, and the Audit Cycle

Finalization seals the quarter. A `ChiefCreditOfficer` finalizes an `APPROVED` run, but only when no adjustment of the run remains `PENDING` — a lingering proposal blocks the transition with `ERR_ADJUSTMENTS_PENDING` (HTTP 409), which is what the widened rejection gate of §3.7 exists to clear. The finalization request carries the period's general-ledger actuals: `period_charge_offs_cents` and `period_recoveries_cents`, each zero or greater — a negative value for either is rejected with `ERR_INVALID_REQUEST` (HTTP 400), a check that precedes the state-transition check. Finalization moves the run `APPROVED` → `FINALIZED`, increments its `version`, and spawns the run's disclosure report — exactly one report per run, created in `PREPARED` and linked through its `run_id`. The finalization response carries the finalized run.

The report is the allowance roll-forward made public. Its `ending_allowance_cents` is the run's `total_allowance_cents` at finalization. Its `beginning_allowance_cents` is selected from settled history: among all `FINALIZED` runs whose `as_of_period` quarter index is strictly below the finalizing run's, the one with the greatest quarter index supplies its `total_allowance_cents`; when no such run exists — the first quarter ever finalized — the beginning allowance is zero. The `provision_cents` is then the ending allowance minus the beginning allowance plus the period's gross charge-offs minus the period's recoveries: the provision is whatever the income statement must absorb so that, after charge-offs and recoveries flow through, the allowance lands on the new estimate. The roll-forward identity always holds — the ending allowance equals the beginning allowance plus the provision minus net charge-offs, where net charge-offs are the period's gross charge-offs minus its recoveries — and auditors reconcile the report against it. The report also stores the supplied `period_charge_offs_cents` and `period_recoveries_cents`, and its `audit_reference` and `revision_notes` start empty.

The audit cycle belongs to the report's own lifecycle. A `CreditAnalyst` submits a `PREPARED` report, moving it `PREPARED` → `UNDER_AUDIT_REVIEW`. An `ExternalAuditor` then either signs it off or sends it back. Sign-off requires an `audit_reference` — the auditor's workpaper pointer — that is non-empty after trimming, and an empty or whitespace-only one is rejected with `ERR_INVALID_REQUEST`; an accepted sign-off stores the reference and moves the report `UNDER_AUDIT_REVIEW` → `RELEASED`, which is terminal. Return-for-revision requires `revision_notes` that are non-empty after trimming — again, empty or whitespace-only notes are rejected with `ERR_INVALID_REQUEST` — stores them on the report, and moves it `UNDER_AUDIT_REVIEW` → `PREPARED` so the cycle can repeat until the disclosure is released. A run's reports can be listed to retrieve the zero-or-one report it owns.

## 4. Endpoint Definitions

Operations that create a new resource — a loss model, a refresh successor model, a back-test result, a portfolio segment, a loan, an economic scenario, a qualitative factor, a model run, or a management adjustment — return `201 Created`. All other operations, including state transitions, computed reads, and single-resource or list reads, return `200 OK`. The narratives of §3 define each endpoint's request payload and side effects; this table is the routing summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cecl/loss-models` | Create a LossModel in `DRAFT` | ModelValidator |
| GET | `/cecl/loss-models` | List LossModels, filterable by `status` and `parent_model_id` | Any |
| GET | `/cecl/loss-models/{modelId}` | Get a LossModel | Any |
| POST | `/cecl/loss-models/{modelId}/activate` | Activate a `DRAFT` model; any other `ACTIVE` model is auto-retired | ModelValidator |
| POST | `/cecl/loss-models/{modelId}/retire` | Retire an `ACTIVE` model (blocked while in-flight runs reference it) | ModelValidator |
| POST | `/cecl/loss-models/{modelId}/refresh` | Refresh a breached model: creates a successor `DRAFT` model with `parent_model_id` lineage | ModelValidator |
| POST | `/cecl/loss-models/{modelId}/backtests` | Record a back-test of the model against its selected `FINALIZED` run | ModelValidator |
| GET | `/cecl/loss-models/{id}/backtest-results` | List back-test results for a model | Any |
| POST | `/cecl/portfolio-segments` | Create a PortfolioSegment in `OPEN` | CreditAnalyst |
| GET | `/cecl/portfolio-segments/{segmentId}` | Get a PortfolioSegment | Any |
| GET | `/cecl/portfolio-segments/{id}/loans` | List loans of a segment | Any |
| GET | `/cecl/portfolio-segments/{id}/qualitative-factors` | List qualitative factors of a segment, filterable by `status` | Any |
| POST | `/cecl/loans` | Create a Loan in a segment (segment must be `OPEN`) | CreditAnalyst |
| GET | `/cecl/loans/{loanId}` | Get a Loan | Any |
| POST | `/cecl/loans/{loanId}/charge_off` | Record a full or partial charge-off; cascades segment counters, `WATCH` status, and `DRAFT`-run flags | CreditAnalyst |
| POST | `/cecl/loans/{loanId}/record_recovery` | Record a recovery against prior charge-offs; may auto-clear segment `WATCH` | CreditAnalyst |
| POST | `/cecl/economic-scenarios` | Create an `ACTIVE` EconomicScenario | ModelValidator |
| GET | `/cecl/economic-scenarios/{scenarioId}` | Get an EconomicScenario | Any |
| POST | `/cecl/economic-scenarios/{scenarioId}/archive` | Archive a scenario (blocked while an in-flight run references it) | ModelValidator |
| POST | `/cecl/qualitative-factors` | Create a `DRAFT` QualitativeFactor | CreditAnalyst |
| GET | `/cecl/qualitative-factors/{factorId}` | Get a QualitativeFactor | Any |
| POST | `/cecl/qualitative-factors/{factorId}/document` | Attach documentation, moving the factor `DRAFT` → `DOCUMENTED` | CreditAnalyst |
| POST | `/cecl/qualitative-factors/{factorId}/approve` | Approve a `DOCUMENTED` factor | ChiefCreditOfficer |
| POST | `/cecl/qualitative-factors/{factorId}/retire` | Retire an `APPROVED` factor (excluded from future runs) | ChiefCreditOfficer |
| POST | `/cecl/model-runs` | Create a `DRAFT` ModelRun with pinned scenario weights | CreditAnalyst |
| GET | `/cecl/model-runs` | List ModelRuns, filterable by `loss_model_id`, `status`, and `as_of_period` | Any |
| GET | `/cecl/model-runs/{runId}` | Get a ModelRun | Any |
| POST | `/cecl/model-runs/{runId}/execute` | Execute the quarterly run: snapshot the segment breakdown, create IndividualEvaluations, pin totals | CreditAnalyst |
| POST | `/cecl/model-runs/{runId}/submit_for_review` | Submit an `EXECUTED` run for review (all evaluations must be `REVIEWED`) | CreditAnalyst |
| POST | `/cecl/model-runs/{runId}/approve` | Approve a run (segregation of duties: approver is not the executor) | ChiefCreditOfficer |
| POST | `/cecl/model-runs/{runId}/request_rework` | Send a run back to `EXECUTED` for rework | ChiefCreditOfficer |
| POST | `/cecl/model-runs/{runId}/finalize` | Finalize an `APPROVED` run; creates the DisclosureReport with the roll-forward | ChiefCreditOfficer |
| GET | `/cecl/model-runs/{runId}/allowance-summary` | Computed read: run-level totals plus the per-segment breakdown snapshot | Any |
| GET | `/cecl/individual-evaluations` | List IndividualEvaluations, filterable by `run_id`, `loan_id`, and `status` | Any |
| GET | `/cecl/individual-evaluations/{evaluationId}` | Get an IndividualEvaluation | Any |
| PATCH | `/cecl/individual-evaluations/{evaluationId}` | Update method, inputs, or notes while `DRAFT` or `SUBMITTED`; recomputes the specific reserve (OCC-guarded) | CreditAnalyst |
| POST | `/cecl/individual-evaluations/{evaluationId}/submit` | Submit a `DRAFT` evaluation (requires analysis notes) | CreditAnalyst |
| POST | `/cecl/individual-evaluations/{evaluationId}/review` | Mark a `SUBMITTED` evaluation `REVIEWED` | ChiefCreditOfficer |
| POST | `/cecl/individual-evaluations/{evaluationId}/reopen` | Reopen a `REVIEWED` evaluation back to `SUBMITTED` | ChiefCreditOfficer |
| POST | `/cecl/model-runs/{id}/management-adjustments` | Propose a management adjustment on an `EXECUTED` or `UNDER_REVIEW` run (OCC-guarded, cap-checked) | CreditAnalyst |
| GET | `/cecl/model-runs/{id}/management-adjustments` | List adjustments of a run, filterable by `status` | Any |
| POST | `/cecl/management-adjustments/{adjustmentId}/approve` | Approve a `PENDING` adjustment (segregation of duties: approver is not the creator); run totals re-sync | ChiefCreditOfficer |
| POST | `/cecl/management-adjustments/{adjustmentId}/reject` | Reject a `PENDING` adjustment (no run impact) | ChiefCreditOfficer |
| GET | `/cecl/model-runs/{id}/disclosure-reports` | List disclosure reports of a run (zero or one entries) | Any |
| GET | `/cecl/disclosure-reports/{reportId}` | Get a DisclosureReport | Any |
| POST | `/cecl/disclosure-reports/{reportId}/submit_for_audit` | Submit a `PREPARED` report for audit review | CreditAnalyst |
| POST | `/cecl/disclosure-reports/{reportId}/sign_off` | External auditor signs off, releasing the report | ExternalAuditor |
| POST | `/cecl/disclosure-reports/{reportId}/return_for_revision` | External auditor returns the report for revision | ExternalAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_EVALUATION_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_PERIOD_NOT_FORWARD` | 409 Conflict |
| `ERR_MODEL_NOT_ACTIVE` | 409 Conflict |
| `ERR_SEGMENT_NOT_OPEN` | 409 Conflict |
| `ERR_SCENARIO_NOT_ACTIVE` | 409 Conflict |
| `ERR_WEIGHT_SUM_INVALID` | 422 Unprocessable Entity |
| `ERR_SCENARIO_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_FACTOR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INVALID_REVERSION_CONFIG` | 422 Unprocessable Entity |
| `ERR_FACTOR_DOCUMENTATION_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_ANALYSIS_DOCUMENTATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ZERO_ADJUSTMENT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SEGMENT_CODE` | 409 Conflict |
| `ERR_DUPLICATE_LOAN_NUMBER` | 409 Conflict |
| `ERR_SCENARIO_IN_USE` | 409 Conflict |
| `ERR_MODEL_IN_USE` | 409 Conflict |
| `ERR_REFRESH_NOT_REQUIRED` | 409 Conflict |
| `ERR_EVALUATIONS_OUTSTANDING` | 409 Conflict |
| `ERR_ADJUSTMENTS_PENDING` | 409 Conflict |
| `ERR_NO_FINALIZED_RUN` | 409 Conflict |
| `ERR_CHARGE_OFF_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_RECOVERY_EXCEEDS_CHARGE_OFF` | 422 Unprocessable Entity |
| `ERR_ADJUSTMENT_EXCEEDS_CAP` | 422 Unprocessable Entity |
