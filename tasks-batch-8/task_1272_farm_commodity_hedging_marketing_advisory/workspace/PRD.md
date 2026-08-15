# Farm Hedging Advisory API — Product Requirements Document

## 1. Introduction

Grain marketing is the single largest unmanaged financial risk on a diversified row-crop operation. A grower who produces corn, soybeans, or wheat must decide — weeks or months before harvest — how many bushels to forward-sell, how many to hedge with futures or options, how much revenue protection to buy through crop insurance, and how much to hold in on-farm storage against a hoped-for price recovery. Each of those decisions consumes a share of one finite pool: the expected bushel production for the crop year. Overcommit that pool and the operation is speculating; undercommit it and the operation leaves basis and carry on the table.

This document specifies the Farm Hedging Advisory API, a platform operated by commodity marketing advisors on behalf of their grower clients. The system tracks an operation's production baseline and risk profile, carries a marketing plan with price-target rungs and hedge recommendations, records cash sales contracts across multiple buyers, administers a margin account for brokerage positions, interacts with crop-insurance claims, and produces benchmarking, fee, cash-flow, and storage-breakeven reports. The platform enforces disclosure acknowledgment before advisory activity begins, segregates the advisor who submits an agreement from the compliance officer who certifies it, and serializes all competing claims on the finite expected-bushel pool through a coverage-cap rule.

A note on temporal determinism: the platform maintains a logical clock that is independent of wall-clock time. At startup and before any administrative action, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `PlatformAdmin` may advance the logical clock through a test-driving capability that sets the server's logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc` value. Every `created_at` and `updated_at` stamp, every time-to-live rule, every window comparison, and every statement period derives from this logical clock, so time-dependent behavior is deterministic from an empty database.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. The system recognizes four roles, spelled exactly as follows: `PlatformAdmin`, `CommodityAdvisor`, `Grower`, and `ComplianceOfficer`. A request that omits either header, or carries a role value outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The `Grower` role is entity-backed: when `X-User-Role` is `Grower`, `X-User-ID` carries the `id` of the acting `GrowerOperation`. Every resource in the system that belongs to an operation stores that ownership reference in an `operation_id` field (either supplied at creation or copied from a parent at execution), and ownership checks on any such resource compare its `operation_id` to `X-User-ID`. A `Grower` request whose `X-User-ID` does not equal the operation id that owns the target resource is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403). The `PlatformAdmin`, `CommodityAdvisor`, and `ComplianceOfficer` roles are opaque operator identifiers: their `X-User-ID` values are not tied to any persisted entity, though the server may record them — for example, as `created_by_user_id` on a `HedgeRecommendation` or `submitted_by_user_id` and `certified_by_user_id` on an `AdvisoryAgreement` — for segregation-of-duties enforcement.

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

List endpoints accept `limit` and `offset` as query parameters. When `limit` is omitted it defaults to 10; the minimum accepted value is 1 and the maximum is 100. The `offset` parameter defaults to 0. List responses are sorted by `created_at` ascending unless otherwise specified, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, derived from the server's logical clock. The `version` field is an integer that increments with every mutation to the resource and provides the basis for optimistic concurrency control. Recomputing a derived counter or aggregate on a resource — for example, recomputing `hedged_bushels` or `committed_contract_bushels` on a `MarketingPlan`, or recomputing margin aggregates on a `MarginAccount` — is itself a mutation and therefore refreshes `updated_at` and increments `version`. One resource deviates from this convention: a `MarketTick` is an immutable price-feed record that carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. Optimistic Concurrency Control

Two write paths are guarded by explicit optimistic concurrency control, because a stale write on either would silently overwrite an intervening change.

Amending a marketing plan is the first guarded path. A request to amend a `MarketingPlan` must carry `expected_marketing_plan_version`, a non-optional field carrying the client's last observed `version` of the plan. If another amendment has advanced the plan's `version` since the client last read it — for example, a lowered `max_priced_pct` that the stale write would otherwise restore — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a change it has not observed.

Creating a production baseline is the second guarded path. Because a successful baseline creation supersedes the operation's existing non-superseded baseline, the create request must carry `expected_operation_version` matching the target `GrowerOperation`'s current `version`. If the operation's version has advanced since the client last observed it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412): the client's premise about which baseline it would supersede is stale.

No other endpoint accepts or requires a version field. Endpoints not listed here do not take `expected_marketing_plan_version`, `expected_operation_version`, or any other OCC field.

### 2.6. Validation Discipline and Check Ordering

Every request passes through a fixed validation cascade, and the order is observable when multiple violations coexist on one request. Authentication is checked first — missing or unknown headers surface as `ERR_UNAUTHENTICATED` before anything else is examined. Role authorization is checked second: a role not listed on the endpoint produces `ERR_FORBIDDEN_ROLE`, and an entity-backed `Grower` whose `X-User-ID` does not match the owning operation produces `ERR_RESOURCE_NOT_OWNED`. Field-level schema validation runs third — missing required fields, invalid enum values, out-of-range values, violated conditional-field rules, or window inversions produce `ERR_VALIDATION`. Fourth, every path identifier and every foreign-key reference in the request body must resolve to an existing resource, or the request fails with `ERR_NOT_FOUND`. Fifth, the OCC checks of §2.5 run, producing `ERR_STALE_VERSION` on a version mismatch. Sixth, the target resource must be in a from-state that permits the requested transition, producing `ERR_INVALID_STATE`. Seventh, compliance gates are evaluated — disclosure acknowledgment, disclosure staleness, and segregation of duties — producing `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, `ERR_DISCLOSURE_STALE`, or `ERR_SEGREGATION_OF_DUTIES`. Eighth, referential state requirements are checked: a referenced buyer must be `APPROVED`, a referenced baseline must be `CERTIFIED`, and a referenced agreement must be `ACTIVE`, producing `ERR_BUYER_NOT_APPROVED`, `ERR_BASELINE_NOT_CERTIFIED`, or `ERR_AGREEMENT_NOT_ACTIVE`. Ninth, the temporal interval rules of §2.8 run, producing `ERR_DELIVERY_WINDOW_OVERLAP`, `ERR_STORAGE_BIN_OVERLAP`, or `ERR_DELIVERY_OUTSIDE_WINDOW`. Tenth, capacity and consistency gates run — coverage caps, uncommitted-bushel sufficiency, over-sold tripwire, margin-account status gates, over-delivery tolerance, priced-before-confirm, and settlement-tick presence. Eleventh and last, the post-trade solvency checks run, producing `ERR_INSUFFICIENT_MARGIN_EQUITY`. A request failing an earlier check never reaches a later one, so the returned error always identifies the highest-priority violation present.

### 2.7. Numeric Precision and the Finite Bushel Pool

Two numeric conventions run through every calculation in the system. Dollar amounts are always carried to exactly two decimal places using round-half-up; per-bushel yields are two-decimal values; grain moisture is recorded to one decimal place; net bushel quantities on a delivery ticket are rounded to three decimal places using round-half-up; and quoted or settled market prices are carried to four decimal places. Bushel pools and bushel commitments are integers, and wherever a pool or guarantee is derived from a multiplication the result is floored to a whole bushel.

The central scarcity of the domain is the operation's expected bushel production for the crop year. Contracts, hedges, insurance guarantees, and storage decisions all compete for shares of that one pool. The coverage cap is the enforcement point: for a plan, the cap is the floor of the plan's frozen expected-bushel snapshot multiplied by the smaller of the plan's own `max_priced_pct` ceiling and a risk-profile ceiling that is 0.60 for a `CONSERVATIVE` operation, 0.80 for a `BALANCED` operation, and 1.00 for an `AGGRESSIVE` operation. Acceptance of a hedge recommendation is permitted only when the plan's currently hedged bushels plus the recommendation's bushels plus the plan's already-priced contract bushels is less than or equal to the cap — equality is allowed, so a recommendation that lands exactly on the cap is accepted, and one that would exceed the cap by even one bushel is rejected with `ERR_COVERAGE_CAP_EXCEEDED`. The same cap is consulted when a price target fires and when a flat-priced sales contract is recorded, as detailed in §3.

### 2.8. Temporal Rules: Windows, Buffers, and the Logical Clock

Three interval disciplines govern the calendar behavior of the system, all evaluated against the logical clock described in §1.

First, buyer delivery windows are half-open intervals: a contract's window includes `delivery_window_start` and excludes `delivery_window_end`. A delivery ticket whose `delivery_date` falls on the window start is accepted; one whose `delivery_date` falls on the window end is rejected with `ERR_DELIVERY_OUTSIDE_WINDOW`. Two contracts with the same buyer may not have overlapping windows while either is `OPEN` or `PARTIALLY_DELIVERED`: an overlap exists precisely when the new contract's start falls before the existing contract's end and the existing contract's start falls before the new contract's end; pure adjacency, where one window's end equals the other's start, is allowed. A violation is rejected with `ERR_DELIVERY_WINDOW_OVERLAP`.

Second, storage lots sharing one bin observe a seven-day buffer. A new lot in the same bin as an existing `STORED` lot is rejected with `ERR_STORAGE_BIN_OVERLAP` unless the new lot's `start_date` is at least seven days after the existing lot's `planned_end_date`, or the new lot's `planned_end_date` is at least seven days before the existing lot's `start_date`. Adjacency falling inside the buffer is rejected.

Third, time-to-live and window comparisons — recommendation expiry, default eligibility on a contract past its window, storage withdrawal dating — all read the logical clock rather than wall-clock time. The default logical clock instant at startup is `2026-05-01T00:00:00Z`, and a `PlatformAdmin` may advance it by setting the clock to a supplied `to_iso8601` value.

### 2.9. Compliance, Disclosure, and Segregation of Duties

Advisory activity is gated on a disclosure workflow. An `AdvisoryAgreement` carries a `disclosure_status` sub-state with values `NONE`, `REQUIRED`, `DELIVERED`, `ACKNOWLEDGED`, and `STALE`, evolving alongside the agreement's own `status`. Signing an agreement requires that the disclosure be `ACKNOWLEDGED` and that `acknowledged_agreement_version` equal the agreement's current `version`; an amendment to an `ACTIVE` agreement increments the agreement's `version` and flips an `ACKNOWLEDGED` disclosure to `STALE`, forcing re-delivery and re-acknowledgment before further advisory actions proceed. The agreement that governs an operation at any moment is the operation's most recently activated `ACTIVE` advisory agreement; if more than one exists, the tie is broken by greatest `created_at`.

Segregation of duties is enforced on the compliance certification: the `ComplianceOfficer` who certifies an agreement's disclosure package must not be the same person who submitted it. When the certifying officer's `X-User-ID` equals the agreement's `submitted_by_user_id`, the certification is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On success the agreement's `compliance_certified` flag becomes true and `certified_by_user_id` records the certifier's `X-User-ID`.

### 2.10. Margin Accounting Principles

Every operation may hold at most one `MarginAccount`. The account's `cash_balance` is the cumulative funding deposited, plus realized profit-and-loss from closed positions, minus option premiums debited at execution. `initial_margin_required` is the sum of `initial_margin_dollars` over the account's `OPEN` positions, and `maintenance_margin_required` is the sum of `maintenance_margin_dollars` over the same set. The account's `margin_equity` is its `cash_balance` plus the sum of `unrealized_pnl` over all `OPEN` positions. When the account enters `CALL_OUTSTANDING`, the `margin_call_amount` is frozen at issuance as `initial_margin_required` minus `margin_equity`; at all other times it is zero.

Per-bushel margin rates depend on the instrument. A `FUTURES_SHORT` position carries an initial margin of 0.30 dollars per bushel and a maintenance margin of 0.22 dollars per bushel. A `LONG_PUT` position carries an initial margin per bushel equal to the option's `premium_per_bushel` plus 0.05 dollars, and its maintenance margin equals its initial margin. All dollar amounts in margin accounting are rounded to two decimal places with round-half-up.

### 2.11. Price Feed and Settlement Marks

The price feed is a sequence of `MarketTick` records, each carrying a `commodity` (`CORN`, `SOYBEAN`, or `WHEAT`), a `contract_month` in `YYYY-MM` form, a `price` at four decimal places, a `kind` of either `QUOTE` or `SETTLEMENT`, and a `price_date`. Only `SETTLEMENT` ticks mark positions or fix entry and exit prices. Wherever the system needs "the latest settlement price" for a commodity and contract month, it selects the `SETTLEMENT` tick with the greatest `price_date`, breaking ties by `created_at` ascending. Operations that require a settlement mark — executing a recommendation, offsetting a position, computing a default penalty, computing a storage breakeven — are rejected with `ERR_NO_SETTLEMENT_PRICE` when no such tick exists.

### 2.12. Cascades and Hierarchical Consistency

Many actions mutate more than one entity, and the secondary mutations are as contractual as the primary one. A single market tick can fire price targets, mint recommendations, expire stale proposals, and re-mark every open position of the matching commodity and contract month. A single delivery-ticket confirmation updates the ticket, the contract's delivered bushels and settled value, the contract's fulfillment state, the plan's committed and uncommitted bushels, the agreement's billable accrual, and can auto-close the plan. A void of a previously confirmed ticket reverses each of those effects. Each recomputation on a parent entity is a mutation in the sense of §2.4: it refreshes `updated_at` and increments `version`. The full set of cascades is described with the workflows in §3; readers implementing any action should locate every side effect listed for that action before returning a response.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Operation and Its Production Baseline

A `CommodityAdvisor` begins an engagement by onboarding a `GrowerOperation` with the operation's legal `name`, its `primary_commodity` (exactly one of `CORN`, `SOYBEAN`, or `WHEAT` per operation), the marketing `crop_year`, its `risk_profile` (`CONSERVATIVE`, `BALANCED`, or `AGGRESSIVE`), and optionally a `yield_method` of `APH` or `TREND` which defaults to `APH` when omitted. The operation is created with `over_sold_flag` set to false.

With the operation registered, the advisor creates a `ProductionBaseline` carrying the `operation_id`, the `planted_acres` for the crop year, the `aph_yield_bushels` (the Actual Production History yield per acre, two decimal places), and the `trend_yield_bushels` (the county trend yield per acre, two decimal places). This create is one of the two OCC-guarded writes described in §2.5 and must carry `expected_operation_version`. From these inputs the server computes two expected-bushel variants. The `expected_bushels_aph` variant is the floor of `planted_acres` multiplied by `aph_yield_bushels`; it ignores the trend yield and the risk profile entirely. The `expected_bushels_trend` variant is the floor of `planted_acres` multiplied by `trend_yield_bushels` multiplied by a risk trend factor that is 0.98 for `CONSERVATIVE`, 1.00 for `BALANCED`, and 1.02 for `AGGRESSIVE`; identical inputs therefore produce a different `expected_bushels_trend` than the APH variant produces for the same baseline. The operative `expected_bushels` field then takes the APH variant when the operation's `yield_method` is `APH` and the trend variant when it is `TREND`.

A baseline starts `PROVISIONAL`. Certification is the grower's attestation: a `Grower` whose `X-User-ID` equals the baseline's `operation_id` may certify the baseline, moving it from `PROVISIONAL` to `CERTIFIED` and incrementing the baseline's `version` by one. Certification requires that no other `CERTIFIED` baseline already exist for the same operation — a prior certified baseline must already have been superseded. Creating a new baseline for an operation automatically supersedes that operation's existing non-`SUPERSEDED` baseline, whether that prior baseline is `PROVISIONAL` or `CERTIFIED`. A superseded baseline is excluded from all coverage, guarantee, and plan-activation calculations. Plans already `ACTIVE` keep their frozen `expected_bushels_snapshot` untouched, while `DRAFT` plans referencing the superseded baseline can no longer activate. The baseline create also increments the owning `GrowerOperation`'s `version` by one.

### 3.2. Crop Insurance and the Over-Sold Tripwire

An advisor may quote an `InsurancePolicy` for an operation by supplying the `operation_id`, a `baseline_id` referencing the production baseline, a `coverage_level_pct`, and a `projected_price` election at two decimal places. The coverage level must lie between 0.50 and 0.85 inclusive and move in steps of 0.05; any other value is a schema violation. The quoted policy starts in `QUOTED` status.

Binding is a grower action: a `Grower` whose `X-User-ID` equals the policy's `operation_id` may bind a `QUOTED` policy, moving it to `BOUND`. Binding requires that the policy's `baseline_id` refer to a `CERTIFIED` baseline; otherwise the bind is rejected with `ERR_BASELINE_NOT_CERTIFIED`. At bind time the policy's `guarantee_bushels` is computed once and frozen as the floor of the referenced baseline's operative `expected_bushels` multiplied by `coverage_level_pct`; later baseline supersedes do not retroactively change the frozen guarantee.

When harvest completes, the grower files a claim by supplying `actual_harvested_bushels` (which must be non-negative) and the `harvest_price` observed at claim (which must be positive, at two decimal places). Filing moves the policy from `BOUND` to the terminal `CLAIM_SETTLED` state. The `indemnity_dollars` are computed and frozen as the shortfall — the greater of zero and the guarantee minus the actual harvest — multiplied by the greater of `projected_price` and `harvest_price`, rounded to two decimal places half-up. Settling a claim also evaluates the operation's over-sold tripwire: if the sum of undelivered committed bushels — that is, `bushels` minus `delivered_bushels` taken over the operation's `OPEN` and `PARTIALLY_DELIVERED` sales contracts — exceeds the settled `actual_harvested_bushels`, the operation's `over_sold_flag` is set to true. While that flag is set, new sales contracts are rejected with `ERR_OVER_SOLD_POSITION` and hedge-recommendation acceptances are rejected with the same code, until undelivered commitments once again fit within marketable production.

### 3.3. The Marketing Plan and Its Price-Target Ladder

A `CommodityAdvisor` drafts a `MarketingPlan` by supplying the `operation_id`, a `baseline_id`, and the plan-level coverage ceiling `max_priced_pct`, a two-decimal value between 0.05 and 1.00 inclusive. The plan begins in `DRAFT` status.

Activation is the pivot on which the whole advisory workflow turns, and it enforces its preconditions in the fixed order of §2.6: the plan's `baseline_id` must reference a `CERTIFIED` baseline (otherwise `ERR_BASELINE_NOT_CERTIFIED`); the operation must have a governing `AdvisoryAgreement` in `ACTIVE` status (otherwise `ERR_AGREEMENT_NOT_ACTIVE`); that agreement's `disclosure_status` must be `ACKNOWLEDGED` (a `REQUIRED` or `DELIVERED` disclosure yields `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`); and the agreement's `acknowledged_agreement_version` must equal the agreement's current `version` (otherwise `ERR_DISCLOSURE_STALE`). On activation the plan's `expected_bushels_snapshot` is frozen from the referenced baseline's operative `expected_bushels`, and `coverage_cap_bushels` is computed per §2.7 from the snapshot and the smaller of `max_priced_pct` and the risk-profile cap. Later baseline supersedes do not mutate an `ACTIVE` plan's snapshot.

From `ACTIVE`, a plan may be suspended by either a `CommodityAdvisor` or a `ComplianceOfficer`, moving to `SUSPENDED`. While a plan is `SUSPENDED`, price-target triggers are skipped for that plan, and both sales-contract creation and recommendation acceptance against the plan are rejected with `ERR_INVALID_STATE`. Resuming is an advisor action returning the plan to `ACTIVE`; it requires that the governing agreement still be `ACTIVE` with a current `ACKNOWLEDGED` disclosure, failing with `ERR_DISCLOSURE_STALE` when the disclosure has gone stale. The cycle `ACTIVE` → `SUSPENDED` → `ACTIVE` is permitted without limit. Closing is an advisor action from either `ACTIVE` or `SUSPENDED` to the terminal `CLOSED` state, permitted only when no `OPEN` or `PARTIALLY_DELIVERED` sales contract and no `OPEN` brokerage position remains for the plan. A plan also closes itself automatically when a delivery-ticket confirmation leaves the plan with `uncommitted_bushels` equal to zero and every sales contract on the plan `DELIVERED`; in that event all remaining `PENDING` price targets of the plan move to `CANCELLED`, and the same target cancellation applies on an explicit close.

While `DRAFT` or `ACTIVE`, the advisor may amend the plan through the OCC-guarded amendment path of §2.5. The amendment request carries `expected_marketing_plan_version` and optionally a revised `max_priced_pct`. A successful amendment recomputes `coverage_cap_bushels` and increments the plan's `version` by one; a stale version is rejected with `ERR_STALE_VERSION`.

The plan's derived counters are contractual. `committed_contract_bushels` is the sum of `bushels` over the plan's sales contracts whose `fulfillment_status` is `OPEN`, `PARTIALLY_DELIVERED`, or `DELIVERED`; a `CANCELLED` contract releases its full commitment and a `DEFAULTED` contract releases its undelivered balance. `uncommitted_bushels` is the snapshot minus `committed_contract_bushels`. `hedged_bushels` is the sum of bushels over `OPEN` brokerage positions for the plan plus bushels over `ACCEPTED`-but-not-yet-`EXECUTED` hedge recommendations. `priced_contract_bushels` is the sum of `bushels` over the plan's contracts whose `pricing_status` is `PRICED` and whose `fulfillment_status` is `OPEN`, `PARTIALLY_DELIVERED`, or `DELIVERED`. `pending_recommendation_count` counts the plan's hedge recommendations in `PROPOSED` status.

Against an active plan, the advisor builds a ladder of `PriceTarget` rungs. Each target carries the `plan_id`, a `contract_month` in `YYYY-MM` form, a `target_price` at two decimal places, and an `increment_bushels` quantity to price when the target fires. A target starts `PENDING`. The advisor may cancel a pending target, moving it from `PENDING` to `CANCELLED`. Each target also carries a system-set `recommendation_id`, null until the target triggers, thereafter referencing the recommendation the trigger minted.

### 3.4. The Tick Cascade: Targets, Recommendations, and Margin Re-Marking

Recording a `MarketTick` is a `PlatformAdmin` action carrying `commodity`, `contract_month`, `price`, `kind`, and `price_date`. A single tick drives a three-hop cascade whose order is pinned.

On the first hop, eligible `PENDING` price targets fire. A target is eligible when the tick's commodity equals the operation's `primary_commodity` for the target's plan, the tick's `contract_month` equals the target's `contract_month`, the tick's `price` is greater than or equal to the target's `target_price`, and the target's plan is `ACTIVE`. Both `QUOTE` and `SETTLEMENT` ticks fire targets. Eligible targets fire in `target_price` ascending order with ties broken by `created_at` ascending. Each fired target moves from `PENDING` to `TRIGGERED` and mints a `PROPOSED` hedge recommendation whose `price_target_id` points back to the originating target, recording the minted recommendation's id in the target's `recommendation_id`. The minted recommendation's size is the smaller of the target's `increment_bushels` and the pending headroom, floored at zero. Pending headroom is the plan's `coverage_cap_bushels` minus `hedged_bushels` minus `priced_contract_bushels` minus the sum of bushels over the plan's currently `PROPOSED` recommendations — pending advice reserves capacity during one tick sweep so that a single tick cannot mint recommendations past the cap. When the pending headroom is zero or negative, the target goes `LAPSED` instead of `TRIGGERED` and no recommendation is minted.

On the second hop, recommendation expiry runs: any `PROPOSED` recommendation whose `created_at` is more than five days before the current logical clock moves to `EXPIRED`. Expiry decrements the plan's `pending_recommendation_count` by one and, when the recommendation's `price_target_id` is set, moves the originating target to `LAPSED`.

On the third hop, `SETTLEMENT` ticks re-mark every `OPEN` brokerage position whose commodity and contract month match the tick: each such position's `unrealized_pnl` is recomputed against the new settlement price, and the account's `margin_equity` is recomputed. When an account's `margin_equity` falls strictly below its `maintenance_margin_required`, the account moves from `FUNDED` to `CALL_OUTSTANDING` with `margin_call_amount` frozen at `initial_margin_required` minus `margin_equity` at issuance.

### 3.5. Hedge Recommendations: Authoring, Acceptance, Execution

A `CommodityAdvisor` may author a hedge recommendation directly against an `ACTIVE` plan by supplying the `plan_id`, an `instrument` of `FUTURES_SHORT` or `LONG_PUT`, a `contract_month`, the `bushels` to hedge, and optionally a free-text `rationale`. For a `LONG_PUT` recommendation, `strike_price` and `premium_per_bushel` are required, each at two decimal places; for `FUTURES_SHORT` they do not apply. An advisor-authored recommendation has a null `price_target_id`. Authoring records the advisor's `X-User-ID` in `created_by_user_id` and increments the plan's `pending_recommendation_count` by one. Auto-minted recommendations from §3.4 carry the same shape, with `price_target_id` set and `bushels` sized by coverage headroom.

Acceptance and rejection are grower decisions. A `Grower` whose `X-User-ID` equals the plan's `operation_id` may accept a `PROPOSED` recommendation. Acceptance enforces its checks in order: the plan must be `ACTIVE` (a `SUSPENDED` plan rejects with `ERR_INVALID_STATE`); the operation's `over_sold_flag` must be false (otherwise `ERR_OVER_SOLD_POSITION`); and the coverage-cap inequality of §2.7 must hold with equality allowed — the plan's `hedged_bushels` plus this recommendation's `bushels` plus `priced_contract_bushels` must be less than or equal to `coverage_cap_bushels`, where `hedged_bushels` here counts open positions and other accepted recommendations but excludes the `PROPOSED` recommendation being accepted, since acceptance converts it. A violation of the cap is rejected with `ERR_COVERAGE_CAP_EXCEEDED`. On acceptance the recommendation moves from `PROPOSED` to `ACCEPTED`, the plan's `pending_recommendation_count` decrements by one, and `hedged_bushels` is recomputed. Rejection moves a `PROPOSED` recommendation to `REJECTED`, decrements `pending_recommendation_count` by one, and — when `price_target_id` is set — moves the originating target to `LAPSED`.

Execution turns an `ACCEPTED` recommendation into a live position and is performed by a `CommodityAdvisor`. Execution enforces three gates. First, the operation's margin account must exist and be in `FUNDED` status: a `CALL_OUTSTANDING` account rejects with `ERR_MARGIN_CALL_OUTSTANDING`, and a `RESTRICTED` account rejects with `ERR_MARGIN_ACCOUNT_RESTRICTED`. Second, a `SETTLEMENT` tick must exist for the operation's `primary_commodity` and the recommendation's `contract_month` — otherwise `ERR_NO_SETTLEMENT_PRICE`. Third, the post-trade solvency check: after the position opens, the account's `cash_balance` must be at least the total `initial_margin_required` and the `margin_equity` must be at least the total `maintenance_margin_required`, otherwise the execution is rejected with `ERR_INSUFFICIENT_MARGIN_EQUITY`. On success the server mints a `BrokeragePosition` in `OPEN` status. The position copies `instrument`, `contract_month`, and `bushels` from the recommendation; its `operation_id` and `margin_account_id` are copied from the plan and the operation's account; its `entry_price` is the latest `SETTLEMENT` tick price for the commodity and contract month selected per §2.11. The position's `initial_margin_dollars` is `bushels` multiplied by the instrument's initial rate — for `LONG_PUT`, `bushels` multiplied by the sum of `premium_per_bushel` and 0.05 dollars — and its `maintenance_margin_dollars` is `bushels` multiplied by the instrument's maintenance rate, with a `LONG_PUT`'s maintenance equal to its initial margin. For a `LONG_PUT` execution the premium cost, `bushels` multiplied by `premium_per_bushel`, is debited from the account's `cash_balance`. The account's aggregates are then recomputed, the plan's `hedged_bushels` is recomputed, the recommendation moves to `EXECUTED`, and when `price_target_id` is set the originating target moves from `TRIGGERED` to `FILLED`.

A position's `unrealized_pnl` is re-marked on every matching settlement tick. For `FUTURES_SHORT` it is the entry price minus the latest settlement price, multiplied by `bushels`. For `LONG_PUT` it is the greater of zero and the strike price minus the latest settlement price, minus `premium_per_bushel`, all multiplied by `bushels`. Both forms are rounded to two decimal places half-up.

### 3.6. Margin Accounts, Funding, and Forced Liquidation

A `CommodityAdvisor` opens the operation's single `MarginAccount` by supplying the `operation_id` and an `initial_funding` amount; the account is created with `cash_balance` equal to `initial_funding` and status `FUNDED`. Funding is a grower action carrying an `amount`, which must be positive; funding adds the amount to `cash_balance` and re-evaluates the account status.

The account cycles without limit between `FUNDED` and `CALL_OUTSTANDING`. A settlement tick that drives `margin_equity` strictly below `maintenance_margin_required` moves the account to `CALL_OUTSTANDING` per §3.4. A funding deposit cures the call when the post-funding `margin_equity` is at least `initial_margin_required` — equality cures — returning the account to `FUNDED` and clearing `margin_call_amount` to zero; a deposit that does not reach that threshold leaves the account `CALL_OUTSTANDING` with a reduced `margin_call_amount`.

When the account is `CALL_OUTSTANDING` and the grower cannot cure, a `PlatformAdmin` may invoke forced liquidation; calling it while the account is not `CALL_OUTSTANDING` is rejected with `ERR_LIQUIDATION_NOT_REQUIRED`. Liquidation follows a pinned evaluation order so that its outcome is reproducible. First, every `OPEN` position is marked at its latest `SETTLEMENT` tick, and those prices are frozen for the whole run. Second, the deficit test is defined: the account is in deficit while `margin_equity` is strictly below `maintenance_margin_required`. Third, the candidate set is ordered by `initial_margin_dollars` descending, with ties broken by `created_at` ascending. Fourth, while the deficit test holds and candidates remain, the head candidate is liquidated: it moves from `OPEN` to `LIQUIDATED`, its `exit_price` is the frozen settlement mark, its `realized_pnl` is computed — for `FUTURES_SHORT`, the entry price minus the exit price multiplied by `bushels`; for `LONG_PUT`, the greater of zero and the strike minus the exit, minus `premium_per_bushel`, multiplied by `bushels` — the realized amount is applied to `cash_balance`, the position leaves the candidate set, and the aggregates are recomputed. Fifth, the loop stops as soon as the deficit test fails. The pinned order is observable: liquidating the largest margin contributor first can spare smaller positions that a smallest-first order would have closed. After the run, if positions remain and equity is at or above maintenance, the account returns to `FUNDED`; if no positions remain and equity is non-negative, the account is `FUNDED`; if no positions remain and equity is negative, the account moves to `RESTRICTED`. From `RESTRICTED`, a funding deposit that brings `cash_balance` to at least zero returns the account to `FUNDED`. Each liquidated position's plan has its `hedged_bushels` recomputed.

Separately, an advisor may offset an individual `OPEN` position at the latest settlement mark. Offsetting requires that a `SETTLEMENT` tick exist for the position's commodity and contract month, failing with `ERR_NO_SETTLEMENT_PRICE` otherwise. The position moves from `OPEN` to `OFFSET`, `exit_price` is set to the latest settlement tick, `realized_pnl` is computed by the same two instrument formulas as liquidation, the realized amount is added to `cash_balance`, margin aggregates are recomputed, the call status is re-evaluated — equity at or above the initial requirement returns the account to `FUNDED` — and the plan's `hedged_bushels` is recomputed.

### 3.7. Buyers and Cash Sales Contracts

Buyers are counterparties registered by a `CommodityAdvisor` with a legal `name`, a `buyer_type` of `ELEVATOR`, `PROCESSOR`, `EXPORTER`, or `ETHANOL`, and a `credit_rating` of `A`, `B`, or `C`. A buyer starts `PROVISIONAL`. A `ComplianceOfficer` approves a buyer, moving it from `PROVISIONAL` to `APPROVED`, and may suspend an `APPROVED` buyer, moving it to `SUSPENDED`; approval also lifts a `SUSPENDED` buyer back to `APPROVED`, so the approve/suspend cycle is permitted without limit. Suspending a buyer leaves existing contracts unaffected but causes new sales-contract creation naming that buyer to be rejected with `ERR_BUYER_NOT_APPROVED`.

A sales contract is recorded by either a `CommodityAdvisor` or a `Grower`, supplying the `operation_id`, the `plan_id`, the `buyer_id`, a `contract_type` of `FLAT_PRICE`, `HTA`, or `BASIS`, the contracted `bushels`, and the delivery window as `delivery_window_start` and `delivery_window_end`. Conditional fields apply by contract type and violations are schema errors: a `FLAT_PRICE` contract requires `fixed_price` at two decimal places and forbids the other pricing fields; a `BASIS` contract requires `basis_level` at two decimal places, which may be negative; an `HTA` contract requires a `contract_month` naming the futures month the fixation references. Creation enforces a chain of gates in the order of §2.6: the referenced plan must be `ACTIVE`; the referenced buyer must be `APPROVED`; the governing agreement's disclosure must be currently acknowledged; the delivery window must satisfy the half-open overlap rule of §2.8 against the same buyer's `OPEN` and `PARTIALLY_DELIVERED` contracts; the operation's `over_sold_flag` must be false; the contract's `bushels` must not exceed the plan's `uncommitted_bushels`, failing with `ERR_INSUFFICIENT_UNCOMMITTED_BUSHELS`; and for a `FLAT_PRICE` contract — which is born `PRICED` — the coverage cap must admit the new priced bushels, failing with `ERR_COVERAGE_CAP_EXCEEDED`. A `FLAT_PRICE` contract is created with `pricing_status` equal to `PRICED`; `HTA` and `BASIS` contracts start `UNPRICED`. Every contract starts with `fulfillment_status` equal to `OPEN`. Creation recomputes the plan's committed, uncommitted, and priced counters.

A contract's two state dimensions evolve independently. On the pricing dimension, fixing the price is an advisor action on an `UNPRICED` `HTA` or `BASIS` contract whose fulfillment is `OPEN` or `PARTIALLY_DELIVERED`, carrying a `fixation_price` at two decimal places. Calling fix-price on a `FLAT_PRICE` contract or on an already-`PRICED` contract is rejected with `ERR_PRICING_NOT_ALLOWED`. Fixing sets `fixation_price`, moves `pricing_status` from `UNPRICED` to `PRICED`, computes `effective_price` — for `HTA`, the fixation price itself; for `BASIS`, the fixation price plus `basis_level` — and recomputes the plan's `priced_contract_bushels`. The coverage cap is re-checked at fixation: if the newly priced bushels would push hedged-plus-priced past the cap, the fixation is rejected with `ERR_COVERAGE_CAP_EXCEEDED`. For `FLAT_PRICE` contracts the `effective_price` is simply the `fixed_price` from creation; while a contract is `UNPRICED` its `effective_price` is null.

On the fulfillment dimension, a contract progresses from `OPEN` to `PARTIALLY_DELIVERED` when a confirmed ticket leaves delivered bushels greater than zero but below the contract quantity, and from either state to `DELIVERED` when confirmed deliveries reach or exceed the contract quantity within the tolerance of §3.8. A `DELIVERED` contract stays committed to the plan — the plan's `committed_contract_bushels` is retained and `uncommitted_bushels` recomputed — and the confirmation that completes the last contract evaluates the plan auto-close of §3.3. Cancellation moves an `OPEN` contract with zero delivered bushels to `CANCELLED`, releasing the full commitment back to the plan's `uncommitted_bushels`, recomputing `priced_contract_bushels`, and re-evaluating the operation's `over_sold_flag`, clearing it when undelivered committed bushels once again fit marketable production. Default is an advisor action on an `OPEN` or `PARTIALLY_DELIVERED` contract once the logical clock date is past the `delivery_window_end` and delivered bushels fall short of the contract quantity. Defaulting moves the contract to `DEFAULTED`; when the contract is `PRICED` a `default_penalty_dollars` amount is computed as the undelivered balance — `bushels` minus `delivered_bushels` — multiplied by the greater of zero and the latest settlement price for the operation's `primary_commodity` minus the contract's `effective_price`, rounded to two decimal places half-up. The undelivered balance is released to the plan's `uncommitted_bushels` and the over-sold flag is re-evaluated. Both `CANCELLED` and `DEFAULTED` are terminal, as is `DELIVERED`.

### 3.8. Delivery Tickets: Recording, Confirmation, and Void Compensation

A delivery against a contract begins when a `Grower` records a `DeliveryTicket` carrying the `contract_id`, the `delivery_date`, the scale-ticket `gross_bushels`, and the grain `moisture_pct` at one decimal place. The delivery date must fall inside the contract's half-open window: on `delivery_window_start` is allowed, on `delivery_window_end` is rejected with `ERR_DELIVERY_OUTSIDE_WINDOW`. Recording against a contract that is already `DELIVERED` is rejected with `ERR_CONTRACT_FULLY_DELIVERED`. At recording, the server computes the moisture shrink: `shrink_pct` is the greater of zero and `moisture_pct` minus 15.0, multiplied by 0.012 — shrink applies only above the 15.0 percent moisture base. The `net_bushels` are then `gross_bushels` multiplied by one minus `shrink_pct`, rounded to three decimal places half-up. The ticket starts `RECORDED`.

Confirmation is an advisor action with three preconditions, evaluated in the §2.6 order. The contract's `fulfillment_status` must be `OPEN` or `PARTIALLY_DELIVERED` — confirming against a `DELIVERED` contract yields `ERR_CONTRACT_FULLY_DELIVERED`, and against a terminal `CANCELLED` or `DEFAULTED` contract yields `ERR_INVALID_STATE`. The contract's `pricing_status` must be `PRICED`, failing with `ERR_CONTRACT_NOT_PRICED`. And the confirmation must respect the over-delivery tolerance: the contract's delivered bushels after this ticket must not exceed the floor of the contract's `bushels` multiplied by 1.02 — equality is allowed — failing with `ERR_OVER_DELIVERY_EXCEEDED`. On confirmation the ticket's `ticket_value_dollars` is computed as `net_bushels` multiplied by the contract's `effective_price`, rounded to two decimal places half-up, and added into the contract's `settled_value_dollars`. The rounding order is pinned: each ticket's value is rounded first, then the per-ticket values are summed; summing net bushels and rounding once produces different cents and is not used. Confirmation adds the ticket's `net_bushels` to the contract's `delivered_bushels`, evaluates the fulfillment auto-transition of §3.7, adds `net_bushels` to the `billable_bushels_accrued` of the operation's governing `ACTIVE` advisory agreement, and runs the plan cascade — committed, uncommitted, and priced counters recomputed, and the auto-close rule of §3.3 evaluated.

Voiding is an advisor action available while a ticket is `RECORDED` or `CONFIRMED`, moving it to `VOIDED`. Voiding a `RECORDED` ticket has no compensating effects. Voiding a previously `CONFIRMED` ticket reverses every effect confirmation applied: the contract's `delivered_bushels` decrements by the ticket's `net_bushels`, the contract's `settled_value_dollars` decrements by the ticket's stored `ticket_value_dollars`, the agreement's `billable_bushels_accrued` decrements by `net_bushels`, the fulfillment state reverts — `DELIVERED` back to `PARTIALLY_DELIVERED`, or `PARTIALLY_DELIVERED` back to `OPEN`, as the resulting quantities dictate — and the plan is recomputed. A plan already `CLOSED` stays `CLOSED` through a void.

### 3.9. Storage Decisions and the Breakeven Calculation

A `Grower` places bushels into storage by creating a `StorageLot` with the `operation_id`, a `bin_id` identifying the elevator bin, the `bushels` stored, a `start_date`, a `planned_end_date`, a `cost_per_bushel_month` at two decimal places, and an `annual_interest_rate` opportunity-cost rate such as 0.06. Creation enforces the seven-day bin buffer of §2.8 against other `STORED` lots in the same bin, failing with `ERR_STORAGE_BIN_OVERLAP`. The lot starts `STORED`. Withdrawal is a grower action moving the lot from `STORED` to `WITHDRAWN` and stamping `actual_end_date` with the current logical clock date.

The breakeven computation is a read-time projection over a lot. The end reference is the lot's `actual_end_date` when it is `WITHDRAWN`, else its `planned_end_date`. The elapsed time is the calendar-day difference between the end reference and `start_date`, converted to months by dividing by 30 and rounding up — any part-month counts as a full month. The carry charge is `bushels` multiplied by `cost_per_bushel_month` multiplied by the month count, rounded to two decimals half-up. The interest charge is `bushels` multiplied by the harvest value per bushel, multiplied by `annual_interest_rate`, multiplied by the month count, divided by 12, rounded to two decimals half-up. The harvest value per bushel is the latest `SETTLEMENT` tick price for the operation's `primary_commodity`; when no settlement tick exists the computation is rejected with `ERR_NO_SETTLEMENT_PRICE`. The breakeven sale price is the sum of the harvest value of the lot — `bushels` multiplied by the harvest value per bushel — plus the carry plus the interest, divided by `bushels`, rounded to two decimals half-up. The computed read returns the `months` count, `carry_dollars`, `interest_dollars`, and `breakeven_sale_price`.

### 3.10. Advisory Agreements, Disclosure Workflow, and Fees

An engagement's commercial terms live on an `AdvisoryAgreement`, drafted by a `CommodityAdvisor` with the `operation_id`, a `fee_type` of `PER_BUSHEL` or `FLAT_ANNUAL`, and conditional fields: `rate_per_bushel` at two decimal places is required for `PER_BUSHEL`, `flat_annual_fee` at two decimal places is required for `FLAT_ANNUAL`, and an optional `annual_cap_dollars` places a hard cap on a single fee statement total. The agreement starts in `DRAFT` with `disclosure_status` equal to `NONE` and `compliance_certified` false. The agreement also carries `billable_bushels_accrued`, a cumulative count of net bushels on confirmed, non-voided delivery tickets for the operation since activation.

Submission moves the agreement from `DRAFT` to `PENDING_SIGNATURE`, flips the disclosure sub-state from `NONE` to `REQUIRED`, and records the submitting advisor's `X-User-ID` in `submitted_by_user_id`. The advisor then delivers the fee and risk disclosure, moving `disclosure_status` from `REQUIRED` — or later from `STALE` — to `DELIVERED`. The grower acknowledges the disclosure, moving `disclosure_status` from `DELIVERED` to `ACKNOWLEDGED` and pinning `acknowledged_agreement_version` to the agreement's current `version`. Signing is the grower's final act, moving the agreement from `PENDING_SIGNATURE` to `ACTIVE`; signing requires the disclosure to be `ACKNOWLEDGED`, failing with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` otherwise, and requires `acknowledged_agreement_version` to equal the agreement's current `version`, failing with `ERR_DISCLOSURE_STALE` on a stale pin.

Amendment is an advisor action on an `ACTIVE` agreement — a self-loop that leaves status `ACTIVE`. The amendment may revise `rate_per_bushel`, `flat_annual_fee`, or `annual_cap_dollars`. It increments the agreement's `version` by one and, when the disclosure was `ACKNOWLEDGED`, flips `disclosure_status` to `STALE`, so the grower must re-acknowledge before plan activations, resumes, signings, or contract creations proceed. The same amendment path carries an optional `status_change`; setting `status_change` to `TERMINATE` moves the agreement from `ACTIVE` to the terminal `TERMINATED` state, permitted only when no `ACTIVE` marketing plan references the operation, failing with `ERR_INVALID_STATE` otherwise. Version discipline is precise: only submission and amendment increment `version`; deliver-disclosure, acknowledge-disclosure, sign, and certify-compliance do not.

Compliance certification is the segregated control of §2.9: a `ComplianceOfficer` certifies the agreement's disclosure package, provided the officer's `X-User-ID` differs from `submitted_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES` otherwise. Certification sets `compliance_certified` to true and records `certified_by_user_id`.

The fee statement is a computed read over a statement period supplied as `period_start` and `period_end`. Billable bushels are the sum of `net_bushels` over confirmed, non-voided delivery tickets whose `delivery_date` falls within the period inclusive of both endpoints and whose contract belongs to the agreement's operation. Under the `PER_BUSHEL` variant the fee is the billable bushels multiplied by `rate_per_bushel`, rounded to two decimals half-up; it scales with delivered bushels. Under the `FLAT_ANNUAL` variant the fee is the `flat_annual_fee`, charged once per statement period regardless of bushels; identical delivery history under the two variants therefore yields different totals. When `annual_cap_dollars` is present, the fee is the smaller of the computed fee and the cap, and the response marks `capped` as true. The statement returns `billable_bushels`, `fee_dollars`, and `capped`.

### 3.11. Performance Benchmarking and Cash-Flow Projection

Two read-time computations support the advisory conversation at season's end and through the year.

The performance report compares the operation's realized pricing against a market benchmark. The priced components are the operation's sales contracts with `pricing_status` equal to `PRICED` and `fulfillment_status` among `OPEN`, `PARTIALLY_DELIVERED`, `DELIVERED`, or `DEFAULTED`. The `weighted_avg_sale_price` is the sum of `bushels` multiplied by `effective_price` over those contracts divided by the sum of `bushels`, rounded to four decimal places half-up, and null when the priced set is empty. The caller selects the benchmark variant through an optional `benchmark_method` parameter. Under `MARKETING_YEAR_AVG` — the default — the benchmark window runs from June 1 of the crop year through May 31 of the following year, inclusive, averaging every `SETTLEMENT` tick in the twelve-month marketing year. Under `HARVEST_WINDOW_AVG` the window runs from October 1 through October 31 of the crop year, inclusive, averaging only ticks inside the October harvest window; identical trades therefore benchmark against a different number under the two variants. The `benchmark_price` is the mean of `SETTLEMENT` tick prices for the operation's `primary_commodity` whose `price_date` falls inside the selected window, rounded to four decimal places half-up, and null when no such tick exists. The `outperformance_bps` is the weighted average sale price minus the benchmark price, divided by the benchmark price, multiplied by ten thousand, rounded half-up to a whole basis point, and null when either input is null. The report also returns `priced_contract_count` and `benchmark_tick_count`.

The cash-flow projection buckets events by calendar month, ascending from the earliest contributing event through an optional `through_date`. Each bucket's inflow accumulates the `ticket_value_dollars` of confirmed, non-voided delivery tickets whose `delivery_date` falls in that month. Each bucket's outflow accumulates two components: for every storage lot occupying the month — a lot occupies month m when its `start_date` is on or before the last day of m and its end reference is on or after the first day of m — the lot's `bushels` multiplied by its `cost_per_bushel_month`; and for every `LONG_PUT` position of the operation, whether `OPEN`, `OFFSET`, or `LIQUIDATED`, the premium cost of `bushels` multiplied by `premium_per_bushel` in the position's execution month. Within a bucket, `net_cash_flow` is inflow minus outflow, and `cumulative_cash_flow` runs in month order — the projection is order-sensitive: buckets are reported ascending, and events sharing a month aggregate before netting. The projection returns the `buckets` array plus `total_inflow`, `total_outflow`, and `net_cash_flow` across the whole horizon.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, amendments, computed mutations — return a `200 OK` status code. Computed read endpoints return `200 OK`. The table below is a summary only; request fields, response payloads, and side effects are specified by the narratives of §2 and §3.

Path variables are named consistently across the API: `operationId` identifies a `GrowerOperation`, `baselineId` a `ProductionBaseline`, `policyId` an `InsurancePolicy`, `planId` a `MarketingPlan`, `targetId` a `PriceTarget`, `recommendationId` a `HedgeRecommendation`, `positionId` a `BrokeragePosition`, `accountId` a `MarginAccount`, `buyerId` a `Buyer`, `contractId` a `SalesContract`, `ticketId` a `DeliveryTicket`, `lotId` a `StorageLot`, and `agreementId` an `AdvisoryAgreement`. Where a path contains a resource identifier, the system resolves it to an existing resource before any business rule is evaluated, failing with `ERR_NOT_FOUND` when the identifier does not resolve.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/advisory/operations` | Onboard a grower operation | CommodityAdvisor |
| GET | `/advisory/operations/{operationId}` | Read one operation | CommodityAdvisor, Grower, ComplianceOfficer, PlatformAdmin |
| GET | `/advisory/operations/{operationId}/performance-report` | Computed read: weighted average sale price vs benchmark (dual-variant) | CommodityAdvisor, Grower |
| GET | `/advisory/operations/{operationId}/cash-flow-projection` | Computed read: month-bucketed cash in/out for storage and marketing decisions | CommodityAdvisor, Grower |
| POST | `/advisory/production-baselines` | Create a baseline; supersedes the operation's existing non-superseded baseline (OCC on operation version) | CommodityAdvisor |
| GET | `/advisory/production-baselines/{baselineId}` | Read one baseline | CommodityAdvisor, Grower, ComplianceOfficer |
| GET | `/advisory/production-baselines` | List baselines | CommodityAdvisor, Grower, ComplianceOfficer |
| POST | `/advisory/production-baselines/{baselineId}/certify` | Grower attestation: `PROVISIONAL` → `CERTIFIED` | Grower |
| POST | `/advisory/insurance-policies` | Quote a crop-insurance policy | CommodityAdvisor |
| GET | `/advisory/insurance-policies/{policyId}` | Read one policy | CommodityAdvisor, Grower |
| GET | `/advisory/insurance-policies` | List policies | CommodityAdvisor, Grower |
| POST | `/advisory/insurance-policies/{policyId}/bind` | Bind the quote; freezes `guarantee_bushels` | Grower |
| POST | `/advisory/insurance-policies/{policyId}/file-claim` | File and settle a production claim; may raise `over_sold_flag` | Grower |
| POST | `/advisory/marketing-plans` | Create a marketing plan (`DRAFT`) | CommodityAdvisor |
| GET | `/advisory/marketing-plans/{planId}` | Read one plan | CommodityAdvisor, Grower, ComplianceOfficer |
| GET | `/advisory/marketing-plans` | List plans | CommodityAdvisor, Grower, ComplianceOfficer |
| PUT | `/advisory/marketing-plans/{planId}` | Amend plan parameters (OCC on plan version) | CommodityAdvisor |
| POST | `/advisory/marketing-plans/{planId}/activate` | `DRAFT` → `ACTIVE` (requires certified baseline and current acknowledged disclosure) | CommodityAdvisor |
| POST | `/advisory/marketing-plans/{planId}/suspend` | `ACTIVE` → `SUSPENDED` | CommodityAdvisor, ComplianceOfficer |
| POST | `/advisory/marketing-plans/{planId}/resume` | `SUSPENDED` → `ACTIVE` | CommodityAdvisor |
| POST | `/advisory/marketing-plans/{planId}/close` | `ACTIVE` or `SUSPENDED` → `CLOSED` when no open contracts or positions | CommodityAdvisor |
| POST | `/advisory/price-targets` | Add a price-target rung to a plan (`PENDING`) | CommodityAdvisor |
| GET | `/advisory/price-targets/{targetId}` | Read one target | CommodityAdvisor, Grower |
| GET | `/advisory/price-targets` | List targets | CommodityAdvisor, Grower |
| POST | `/advisory/price-targets/{targetId}/cancel` | `PENDING` → `CANCELLED` | CommodityAdvisor |
| POST | `/advisory/market-ticks` | Record a market price; processes target triggers, recommendation expiry, and margin re-marking | PlatformAdmin |
| POST | `/advisory/hedge-recommendations` | Advisor-authored recommendation (`PROPOSED`) | CommodityAdvisor |
| GET | `/advisory/hedge-recommendations/{recommendationId}` | Read one recommendation | CommodityAdvisor, Grower |
| GET | `/advisory/hedge-recommendations` | List recommendations | CommodityAdvisor, Grower |
| POST | `/advisory/hedge-recommendations/{recommendationId}/accept` | Grower accepts (coverage cap enforced, equality allowed) | Grower |
| POST | `/advisory/hedge-recommendations/{recommendationId}/reject` | Grower rejects | Grower |
| POST | `/advisory/hedge-recommendations/{recommendationId}/execute` | Open the brokerage position for an `ACCEPTED` recommendation | CommodityAdvisor |
| GET | `/advisory/brokerage-positions/{positionId}` | Read one position | CommodityAdvisor, Grower |
| GET | `/advisory/brokerage-positions` | List positions | CommodityAdvisor, Grower |
| POST | `/advisory/brokerage-positions/{positionId}/offset` | Close an `OPEN` position at the latest settlement price | CommodityAdvisor |
| POST | `/advisory/margin-accounts` | Open the operation's margin account (one per operation) | CommodityAdvisor |
| GET | `/advisory/margin-accounts/{accountId}` | Read one margin account | CommodityAdvisor, Grower |
| GET | `/advisory/margin-accounts` | List margin accounts | CommodityAdvisor, Grower |
| POST | `/advisory/margin-accounts/{accountId}/fund` | Deposit cash; cures a call when post-funding equity reaches initial margin | Grower |
| POST | `/advisory/margin-accounts/{accountId}/liquidate` | Forced liquidation per pinned order while `CALL_OUTSTANDING` | PlatformAdmin |
| POST | `/advisory/buyers` | Register a grain buyer (`PROVISIONAL`) | CommodityAdvisor |
| GET | `/advisory/buyers/{buyerId}` | Read one buyer | CommodityAdvisor, Grower, ComplianceOfficer |
| GET | `/advisory/buyers` | List buyers | CommodityAdvisor, Grower, ComplianceOfficer |
| POST | `/advisory/buyers/{buyerId}/approve` | `PROVISIONAL` or `SUSPENDED` → `APPROVED` | ComplianceOfficer |
| POST | `/advisory/buyers/{buyerId}/suspend` | `APPROVED` → `SUSPENDED` | ComplianceOfficer |
| POST | `/advisory/sales-contracts` | Record a cash contract with a buyer | CommodityAdvisor, Grower |
| GET | `/advisory/sales-contracts/{contractId}` | Read one contract | CommodityAdvisor, Grower, ComplianceOfficer |
| GET | `/advisory/sales-contracts` | List contracts | CommodityAdvisor, Grower, ComplianceOfficer |
| POST | `/advisory/sales-contracts/{contractId}/fix-price` | Fix the price on an `UNPRICED` `HTA` or `BASIS` contract | CommodityAdvisor |
| POST | `/advisory/sales-contracts/{contractId}/cancel` | Cancel an `OPEN` contract with zero deliveries | CommodityAdvisor, Grower |
| POST | `/advisory/sales-contracts/{contractId}/default` | Declare default on an undelivered contract past its window | CommodityAdvisor |
| POST | `/advisory/delivery-tickets` | Record a delivery against a contract (`RECORDED`) | Grower |
| GET | `/advisory/delivery-tickets/{ticketId}` | Read one ticket | CommodityAdvisor, Grower |
| GET | `/advisory/delivery-tickets` | List tickets | CommodityAdvisor, Grower |
| POST | `/advisory/delivery-tickets/{ticketId}/confirm` | Confirm a ticket; applies bushels and value, cascades to plan and agreement | CommodityAdvisor |
| POST | `/advisory/delivery-tickets/{ticketId}/void` | Void a ticket; voiding a confirmed ticket compensates all applied effects | CommodityAdvisor |
| POST | `/advisory/storage-lots` | Place bushels into a storage bin (seven-day buffer enforced) | Grower |
| GET | `/advisory/storage-lots/{lotId}` | Read one storage lot | CommodityAdvisor, Grower |
| GET | `/advisory/storage-lots` | List storage lots | CommodityAdvisor, Grower |
| POST | `/advisory/storage-lots/{lotId}/withdraw` | Withdraw the lot (`STORED` → `WITHDRAWN`) | Grower |
| GET | `/advisory/storage-lots/{lotId}/breakeven` | Computed read: breakeven sale price including carry and interest | CommodityAdvisor, Grower |
| POST | `/advisory/advisory-agreements` | Draft an advisory agreement (fee schedule) | CommodityAdvisor |
| GET | `/advisory/advisory-agreements/{agreementId}` | Read one agreement | CommodityAdvisor, Grower, ComplianceOfficer |
| GET | `/advisory/advisory-agreements` | List agreements | CommodityAdvisor, Grower, ComplianceOfficer |
| POST | `/advisory/advisory-agreements/{agreementId}/submit` | Submit for signature; disclosure becomes `REQUIRED` | CommodityAdvisor |
| POST | `/advisory/advisory-agreements/{agreementId}/deliver-disclosure` | Deliver the fee/risk disclosure | CommodityAdvisor |
| POST | `/advisory/advisory-agreements/{agreementId}/acknowledge-disclosure` | Grower acknowledges; pins `acknowledged_agreement_version` | Grower |
| POST | `/advisory/advisory-agreements/{agreementId}/sign` | Grower signs; requires current acknowledgment | Grower |
| PUT | `/advisory/advisory-agreements/{agreementId}` | Amend fee terms on an `ACTIVE` agreement; `status_change` of `TERMINATE` terminates | CommodityAdvisor |
| POST | `/advisory/advisory-agreements/{agreementId}/certify-compliance` | ComplianceOfficer certifies the disclosure package; certifier must differ from submitter | ComplianceOfficer |
| GET | `/advisory/advisory-agreements/{agreementId}/fee-statement` | Computed read: advisory fee for a period under both fee variants | CommodityAdvisor, Grower |
| POST | `/advisory/_clock/set_current_utc` | Set the server's logical clock (test-driving endpoint) | PlatformAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_NOT_OWNED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_DISCLOSURE_STALE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_BASELINE_NOT_CERTIFIED` | 409 Conflict |
| `ERR_BUYER_NOT_APPROVED` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STORAGE_BIN_OVERLAP` | 409 Conflict |
| `ERR_DELIVERY_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_OVER_DELIVERY_EXCEEDED` | 409 Conflict |
| `ERR_CONTRACT_FULLY_DELIVERED` | 409 Conflict |
| `ERR_CONTRACT_NOT_PRICED` | 409 Conflict |
| `ERR_PRICING_NOT_ALLOWED` | 409 Conflict |
| `ERR_COVERAGE_CAP_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_UNCOMMITTED_BUSHELS` | 409 Conflict |
| `ERR_OVER_SOLD_POSITION` | 409 Conflict |
| `ERR_MARGIN_CALL_OUTSTANDING` | 409 Conflict |
| `ERR_MARGIN_ACCOUNT_RESTRICTED` | 409 Conflict |
| `ERR_INSUFFICIENT_MARGIN_EQUITY` | 409 Conflict |
| `ERR_LIQUIDATION_NOT_REQUIRED` | 409 Conflict |
| `ERR_NO_SETTLEMENT_PRICE` | 409 Conflict |
