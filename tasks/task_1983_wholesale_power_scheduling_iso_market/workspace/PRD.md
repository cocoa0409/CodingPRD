# Wholesale Power ISO Settlement API — Product Requirements Document

## 1. Introduction

This document specifies the Wholesale Power ISO Settlement API, a market-participant-facing system that models the full commercial lifecycle of a wholesale power operating day as seen by a scheduling coordinator serving a PJM/ERCOT-style independent system operator. The platform covers day-ahead offer submission and gate discipline, real-time metering and imbalance exposure, generator outage reporting and its effect on deliverability, congestion and loss component allocation, preliminary and final settlement statement issuance with a formal dispute window, capacity obligation performance with penalties and bonuses, ancillary service revenue, and the collateral ledger that keeps every participant's credit posture inside its posted security. All endpoints are mounted under `/market`.

Two properties shape the design. First, the same physical operating day is settled twice: a preliminary run on as-of telemetry and preliminary real-time prices, then a final run on corrected telemetry and final prices, with resettlement statements chaining off disputed statements. The ledger therefore treats every statement as a versioned, supersedable artifact rather than a one-shot invoice. Second, trading, settlement assurance, and treasury are segregated functions: the desk that submits offers is not the desk that disputes statements, and neither may move collateral. A single market authority operates the day-epoch machine, adjudicates outages and disputes, manages awards and obligations, and draws on defaulted collateral.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representation conventions, and cross-cutting mechanisms that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the caller and `X-User-Role` naming one of the four declared roles: `Trader`, `SettlementAnalyst`, `CreditOfficer`, and `IsoOperator`. A request whose headers are missing, malformed, or whose role is not one of these declared names is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Identity semantics tie the header to ownership. When `X-User-Role` is `Trader`, `SettlementAnalyst`, or `CreditOfficer`, `X-User-ID` is the `id` of the acting MarketParticipant; ownership checks on any resource that references a MarketParticipant — whether directly (a statement, a posting, a margin call) or through a chain (an offer through its generator, a dispute through its statement, an obligation through its generator) — compare the resource's owning participant `id` against `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403). When `X-User-Role` is `IsoOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and the operator is exempt from participant scoping.

Segregation of duties is strict: the three participant-side roles are disjoint functions and an organization must assign them to different operators. The `Trader` runs the participant's trading and operations desk — day-ahead offers, meter telemetry, outage reports, and generator decommissioning. The `SettlementAnalyst` validates statements and files or withdraws disputes, and may not trade or move collateral. The `CreditOfficer` posts and releases collateral, and may not trade or file disputes. The `IsoOperator` is the market authority: it registers participants and generators, runs the market and settlement epochs, adjudicates outages and disputes, manages awards, obligations and performance events, draws collateral, and sets the logical clock — and holds none of the participant-side functions. All read endpoints accept any of the four roles.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter caps the number of items returned: if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns rows ordered by `created_at` ascending — a stable order in which ties are broken by insertion sequence. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every gate, window, and deadline in this document — the day-ahead gate close, the telemetry window, the dispute window, the margin-call cure deadline, and outage coverage — reads a single logical clock maintained by the server. At startup the clock reads exactly 2026-08-01T00:00:00Z; until it is explicitly set, it holds this default and never falls back to wall-clock time. An `IsoOperator`-only test-driving capability advances the clock: the request carries a `to_iso8601` instant, and the response reports the new `current_utc`. Advancing the clock re-evaluates availability for every generator with approved outages whose windows the clock has entered or left, with the downstream obligation and credit consequences described in §3.4. Wherever this document says "now", it means the logical clock.

### 2.5. Common Resource Properties

Every resource in the system — MarketParticipant, GeneratorAsset, OperatingDay, PriceNode, DayAheadOffer, RealTimeTelemetry, OutageReport, SettlementStatement, SettlementLine, SettlementDispute, AncillaryServiceAward, CapacityObligation, CapacityPerformanceEvent, CollateralPosting, and MarginCall — carries the same four system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource; it backs the optimistic concurrency rules of §2.7.

System-driven mutations count as modifications: when a market run, an availability recompute, a credit evaluation, or a cascade changes a resource, that resource's `updated_at` refreshes and its `version` increments.

### 2.6. Monetary Units and Rounding Discipline

All monetary values are integer cents. Where a calculation produces fractional cents, rounding is always round half up, and the placement of the rounding step is part of the contract:

- Real-time imbalance energy and the congestion/loss allocations round every per-interval, per-component amount half up to whole cents first, and only then sum across the day's twenty-four intervals. Summing first and rounding once is not permitted — the two orders diverge whenever per-interval products carry fractional cents.
- Ancillary award revenue rounds half up exactly once, on the final per-award sum.
- Capacity performance penalties and bonuses each round half up to whole cents per obligation, and any rounding remainder in the bonus pool is assigned to the largest claim.
- Capacity obligation close-out rounds half up at the gross-revenue step and again at the stop-loss cap step.
- The offer-risk component of the collateral requirement rounds half up per offer before summing.

Megawatt quantities are exact numbers; availability derived from capacity times an integer derate percent needs no rounding, and the five-percent imbalance deadband is carried as an exact, unrounded quantity.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency, because each legitimately supersedes prior data and bumps a parent entity's `version` in the process:

- Creating a day-ahead offer against an operating day requires the request to carry `expected_operating_day_version`, holding the `version` of the OperatingDay the client last observed. Offer creation supersedes any prior `DRAFT` or `SUBMITTED` offer for the same generator-and-day slot and increments the day's `version` by one, so a client writing against a stale view of the day's offer stack must re-observe before writing. A mismatch with the day's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Submitting a telemetry batch against a generator requires `expected_generator_asset_version`, holding the `version` of the GeneratorAsset the client last observed. A batch supersedes prior readings for the same generator-day-interval and increments the generator's `version` by one, so a client correcting meter data on a stale view of the asset must re-observe before writing. A mismatch with the generator's current `version` is rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412).

No other endpoint takes a version field.

### 2.8. The Collateral Requirement and Credit Posture

The system continuously tracks each participant's collateral requirement and compares it against posted security. A participant's `posted_collateral_cents` is the sum of `amount_cents` over its own CollateralPosting rows in `POSTED` status. The raw requirement, stored on the participant as `collateral_requirement_cents`, aggregates three components:

- **Statement basis.** Every SettlementStatement of the participant whose `run_type` is `FINAL` or `RESETTLEMENT` and whose `status` is `ISSUED` or `UNDER_DISPUTE` contributes its `net_amount_cents` minus its `paid_cents`. Statements in any other run type or status — `PRELIMINARY`, `SUPERSEDED`, `CLOSED`, `PAID` — are excluded from the input set.
- **Offer risk.** Each of the participant's DayAheadOffers in `SUBMITTED` contributes its `offered_mw` times a reference price of 5000 cents per MWh (fifty dollars) times a risk factor of ten percent, rounded half up per offer before summing.
- **Capacity risk.** Each CapacityObligation of the participant's generators in `AT_RISK` contributes its `obligated_mw` times 50000 cents per MW (five hundred dollars).

Two exposure variants are selected by the participant's `credit_rating_tier`. A `BELOW_INVESTMENT_GRADE` participant is charged on gross exposure: the requirement is the sum of the absolute values of the per-statement remainders, plus offer risk, plus capacity risk — credit statements never offset debit statements. An `INVESTMENT_GRADE` participant is charged on net exposure: the signed statement remainders are summed across days and floored at zero, then offer and capacity risk are added — the same ledger yields a strictly smaller requirement whenever the statement set mixes signs. The tier also fixes `unsecured_allowance_cents`: 100000 cents (one thousand dollars) for `INVESTMENT_GRADE`, zero for `BELOW_INVESTMENT_GRADE`. The effective requirement is the raw requirement minus the unsecured allowance, floored at zero.

The requirement is recomputed whenever its inputs change: offer submit, withdraw, supersede, or clear; statement issuance; dispute resolution; obligation transitions into or out of `AT_RISK`; posting creation, release, or draw; and explicit operator evaluation. Every recompute is immediately followed by a credit posture evaluation, which also runs at final settlement and when a dispute is upheld. The evaluation compares posted collateral to the effective requirement. If posted collateral is at least the effective requirement, any `OPEN` margin call becomes `CURED` and a participant in `MARGIN_CALL` returns to `ACTIVE`. If posted collateral falls short and no margin call is currently `OPEN`, a MarginCall is issued with `required_additional_cents` equal to the shortfall, `due_at` twenty-four hours after issuance, and status `OPEN`, and the participant moves from `ACTIVE` to `MARGIN_CALL`. If an `OPEN` call's `due_at` is strictly in the past and posted collateral is still short of the effective requirement, that call becomes `DEFAULTED` and the participant moves to `SUSPENDED`; a cure landing at exactly `due_at` is accepted, and only a strictly later instant defaults. An open call's `required_additional_cents` is never updated in place by later re-evaluations, a `DEFAULTED` call never cures, and a `SUSPENDED` participant never auto-reinstates — only an explicit credit evaluation performed by the `IsoOperator`, permitted when posted collateral covers the effective requirement, moves a suspended participant back to `ACTIVE`.

### 2.9. Outage Windows and Availability Semantics

Outage windows are half-open: a report covers every instant at or after its `start_at` and strictly before its `end_at`, so a report that begins exactly when another ends does not overlap it. A generator's `availability_mw` is recomputed whenever an outage report is approved, cancelled, or resubmitted, and whenever the logical clock crosses a window boundary. If any `APPROVED` report of type `FULL` covers the current instant, availability is zero and the generator is `ON_OUTAGE`. Otherwise availability is `capacity_mw` reduced by the largest `derate_pct` among the covering `APPROVED` reports — overlapping partial derates do not stack; the maximum derate wins — and the generator is `AVAILABLE` unless it has been `DECOMMISSIONED`. Every availability change flows into the generator's open capacity obligations, and through them into the participant's credit posture, as detailed in §3.4 and §3.6.

### 2.10. The Settlement Ledger: Dual Variants and Line Emission

The same operating day is settled twice. The preliminary run prices imbalance, congestion, and losses off each node's `rt_prelim_energy_cents_per_mwh`, `rt_prelim_congestion_cents_per_mwh`, and `rt_prelim_loss_cents_per_mwh` components, against the telemetry set as it stands at that run. The final run re-prices off `rt_final_energy_cents_per_mwh`, `rt_final_congestion_cents_per_mwh`, and `rt_final_loss_cents_per_mwh` against the full corrected telemetry set, so an identical physical day yields different cents whenever final prices diverge from preliminary ones. Resettlement reuses the final variant.

A statement is generated for a participant-and-day pair only when the participant has at least one of: a `CLEARED` offer on that day, an ancillary award still `AWARDED` at settlement time, or a capacity charge from a performance event `COMPLETED` on that day. Telemetry alone — a metered generator with no cleared offer — produces no statement and is excluded from settlement.

Each statement's money decomposes into lines: one SettlementLine per generator-and-`charge_type` combination whose amount is non-zero; zero-amount components emit no line, and lines are ordered by `created_at` ascending. A line records its `settlement_statement_id` and `generator_asset_id`, a `charge_type` of `DA_ENERGY_CREDIT`, `RT_IMBALANCE`, `CONGESTION`, `LOSSES`, `ANCILLARY`, or `CAPACITY`, the `mw_quantity` basis of the line (cleared MW, deviation MW, awarded MW, or shortfall MW depending on the charge type), and a signed `amount_cents` in which positive is a charge to the participant and negative a credit.

The statement header aggregates its lines into `da_energy_credit_cents`, `imbalance_charge_cents`, `congestion_charge_cents`, `loss_charge_cents`, `ancillary_revenue_cents`, and `capacity_charge_cents`, with `net_amount_cents` equal to congestion plus losses plus imbalance plus capacity charges, minus the day-ahead energy credit, minus ancillary revenue; a positive net means the participant owes the ISO. `paid_cents` starts at zero and grows only through collateral draws. `issued_at` stamps the logical instant of issuance and `dispute_window_ends_at` sits exactly seventy-two hours later, bracketing the challenge window. `supersedes_statement_id` chains a resettlement statement to the statement it replaces and is null on any statement that replaces nothing.

### 2.11. Validation Order

When a request violates several rules at once, the rejection is deterministic: checks are evaluated in the following order and the first failure wins.

1. Header presence and role well-formedness — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorization for the endpoint — `ERR_FORBIDDEN_FOR_ROLE`.
3. Request shape: the body parses, every required input field is present, enum fields are within their declared value sets, numeric ranges are sane (amounts strictly positive, interval indices within one through twenty-four, starts before ends), and unknown fields are rejected — `ERR_INVALID_REQUEST`.
4. Existence: path identifiers are validated left to right — a request addressed under a non-existent parent fails on the parent before the child identifier is examined — followed by body-referenced identifiers such as `generator_asset_id`, `operating_day_id`, and `market_participant_id` — `ERR_NOT_FOUND`.
5. Participant scoping for the three participant-side roles (`IsoOperator` is exempt) — `ERR_OWNERSHIP_VIOLATION`.
6. Optimistic concurrency on the two guarded writes — `ERR_STALE_VERSION` and `ERR_STALE_ASSET_VERSION`.
7. The path-target resource's own state machine, including terminal-state lockdown, day-epoch ordering, and the single-open-dispute rule — `ERR_INVALID_STATE_TRANSITION` and `ERR_DISPUTE_ALREADY_OPEN`.
8. Cross-entity state preconditions: market epoch, generator availability, participant suspension, statement finality, margin-call presence, and decommission open commitments — `ERR_MARKET_NOT_OPEN`, `ERR_GENERATOR_NOT_AVAILABLE`, `ERR_PARTICIPANT_SUSPENDED`, `ERR_STATEMENT_NOT_FINAL`, `ERR_OPEN_MARGIN_CALL`, `ERR_POSTING_NOT_DRAWABLE`, and `ERR_GENERATOR_HAS_OPEN_COMMITMENTS`.
9. Structural references inside the payload, such as every disputed line belonging to the disputed statement — `ERR_LINE_NOT_IN_STATEMENT`.
10. Temporal gates against the logical clock — `ERR_DA_GATE_CLOSED`, `ERR_TELEMETRY_WINDOW_CLOSED`, `ERR_DISPUTE_WINDOW_CLOSED`.
11. Uniqueness, overlap, and capacity constraints — `ERR_OPERATING_DAY_EXISTS`, `ERR_OBLIGATION_DUPLICATE_PERIOD`, `ERR_OUTAGE_OVERLAP`, `ERR_EVENT_BUFFER_VIOLATION`, `ERR_AWARD_OVERLAPS_OUTAGE`, `ERR_OFFER_MW_EXCEEDS_AVAILABILITY`, `ERR_PRICE_DECK_INCOMPLETE`.
12. Fiscal credit gates — `ERR_CREDIT_HEADROOM_EXCEEDED` and `ERR_COLLATERAL_SHORTFALL`.

## 3. Business Logic & Workflows

### 3.1. Onboarding Participants, Generators, and Obligations

An `IsoOperator` registers a MarketParticipant by supplying its legal `company_name` and a `credit_rating_tier` of `INVESTMENT_GRADE` or `BELOW_INVESTMENT_GRADE`. A new participant starts `ACTIVE`, with `posted_collateral_cents` zero and `collateral_requirement_cents` zero, and its `unsecured_allowance_cents` fixed by tier per §2.8. The tier declared at registration selects both the exposure variant and the unsecured allowance used by every later credit evaluation.

The operator then registers each GeneratorAsset under its owning participant via `market_participant_id`, giving the unit a `unit_name`, the `pricing_node` used to look up price-node components (for example WEST_HUB), and a strictly positive `capacity_mw`. A new generator starts `AVAILABLE` with `availability_mw` equal to its `capacity_mw`.

A `Trader` may retire a generator by decommissioning it, but only while the unit is `AVAILABLE` and carries no open commitments: no day-ahead offer in `DRAFT` or `SUBMITTED`, no outage report in `SUBMITTED`, `ACKNOWLEDGED`, or `APPROVED`, and no capacity obligation in `ACTIVE` or `AT_RISK`. Any one of these rejects the decommission with `ERR_GENERATOR_HAS_OPEN_COMMITMENTS`. A successful decommission moves the unit to `DECOMMISSIONED`, a terminal state.

Capacity obligations are created by the `IsoOperator` for a generator, carrying `generator_asset_id`, a `delivery_period` in year-month form, a strictly positive `obligated_mw`, and a monthly `capacity_rate_cents_per_mw`. At most one obligation in `ACTIVE` or `AT_RISK` may exist for a given generator and delivery period; a second open obligation for the same pair is rejected with `ERR_OBLIGATION_DUPLICATE_PERIOD`. A new obligation starts `ACTIVE` with `accrued_penalty_cents` and `accrued_bonus_cents` both zero, and its `expected_output_mw` — always the smaller of `obligated_mw` and the generator's current `availability_mw` — is evaluated immediately: if the generator is already derated below its obligation, the new obligation moves to `AT_RISK` at once, with the credit consequences described in §3.4.

Treasury setup also happens here. A `CreditOfficer` posts collateral for a participant with a strictly positive `amount_cents` and an `instrument_type` of `CASH` or `LETTER_OF_CREDIT`. The posting starts `POSTED`, the participant's `posted_collateral_cents` increases by `amount_cents`, and credit posture is re-evaluated — a posting that closes a deficiency cures an open margin call per §2.8.

### 3.2. The Operating Day and the Day-Ahead Offer Cycle

An `IsoOperator` opens an operating day by supplying its `market_date` in year-month-day form and its `da_gate_close_at` instant; the day starts `DA_OPEN`. The market date is unique across all operating days — a duplicate is rejected with `ERR_OPERATING_DAY_EXISTS`. The gate instant is inclusive: submissions timestamped at exactly `da_gate_close_at` are accepted, and only strictly later submissions are turned away.

While the day is `DA_OPEN`, a `Trader` drafts offers against it. Creating an offer names the `generator_asset_id`, an `offered_mw` block greater than zero, and an `offer_price_cents_per_mwh` floor, and the request must carry `expected_operating_day_version` per §2.7. The day must still be `DA_OPEN` (`ERR_MARKET_NOT_OPEN`) and the referenced generator `AVAILABLE` (`ERR_GENERATOR_NOT_AVAILABLE`). Each generator keeps at most one live offer per day: creating an offer for a generator-and-day slot that already holds a `DRAFT` or `SUBMITTED` offer supersedes the incumbent — a superseded `DRAFT` simply moves to `SUPERSEDED`, while a superseded `SUBMITTED` offer also releases its risk from the participant's collateral requirement, which is recomputed — and the day's `version` increments by one. The new offer itself starts `DRAFT`.

Submitting is the moment risk attaches. A `Trader` submits a `DRAFT` offer, moving it `DRAFT` → `SUBMITTED`, only when all of the following hold: the day is `DA_OPEN` (`ERR_MARKET_NOT_OPEN`); the generator is `AVAILABLE` (`ERR_GENERATOR_NOT_AVAILABLE`); the owning participant is not `SUSPENDED` (`ERR_PARTICIPANT_SUSPENDED`); the logical clock has not passed `da_gate_close_at` (`ERR_DA_GATE_CLOSED`, with exactly-at-gate-close accepted); the `offered_mw` does not exceed the generator's current `availability_mw` (`ERR_OFFER_MW_EXCEEDS_AVAILABILITY`); and the participant's effective requirement including this offer's own risk stays within `posted_collateral_cents` (`ERR_CREDIT_HEADROOM_EXCEEDED`). On a successful submit, the participant's `collateral_requirement_cents` is recomputed with the offer-risk adder of §2.8 in force.

A submitted offer can be pulled back: withdrawing moves `SUBMITTED` → `DRAFT` while the day remains `DA_OPEN` (`ERR_MARKET_NOT_OPEN`), recomputing the requirement with the adder removed. The submit-and-withdraw cycle may repeat any number of times while the day stays open; `CLEARED`, `NOT_CLEARED`, `EXPIRED`, and `SUPERSEDED` are all terminal.

### 3.3. Gating the Day-Ahead Market and Metering Real Time

When the `IsoOperator` runs the day-ahead market, the request carries a `node_prices` deck — one entry per pricing node naming `node_name` and the three day-ahead components `da_energy_cents_per_mwh`, `da_congestion_cents_per_mwh`, and `da_loss_cents_per_mwh`. The deck must cover the `pricing_node` of every `SUBMITTED` offer on the day; if any submitted offer's node is missing, the run is rejected with `ERR_PRICE_DECK_INCOMPLETE`. On success, one PriceNode row per deck entry is created under the day (each `node_name` unique within the day), clearing runs, and the day advances `DA_OPEN` → `DA_GATED` with its `version` incremented by one.

Clearing walks the day's `SUBMITTED` offers in creation order, oldest first. For each offer, the day-ahead locational marginal price at the offering generator's node is the sum of that node's day-ahead energy, congestion, and loss components. An offer whose `offer_price_cents_per_mwh` is at or below this price clears — equality clears — moving to `CLEARED` with `cleared_mw` set to the full `offered_mw` and `da_lmp_cents_per_mwh` recording the observed price. An offer priced strictly above it moves to `NOT_CLEARED` with `cleared_mw` zero. Every offer still `DRAFT` at this point moves to `EXPIRED`. In all three outcomes the offer leaves the participant's requirement input set and the requirement is recomputed with the offer's risk removed. All amounts are integer cents; clearing involves no rounding.

Between gating and real-time close, the meter window is open. A `Trader` submits a telemetry batch for a generator by naming the `operating_day_id` and carrying `readings`, each reading holding an `interval_index` from one to twenty-four of the operating day and a non-negative `actual_mw` average for that hour, plus `expected_generator_asset_version` per §2.7. Batches are accepted only while the day is `DA_GATED`; at any other epoch the submission is rejected with `ERR_TELEMETRY_WINDOW_CLOSED`. Each batch writes new `RECORDED` rows, and any prior `RECORDED` row for the same generator, day, and interval moves to `SUPERSEDED` — superseded rows are ignored by settlement. The batch increments the generator's `version` by one and returns the `recorded_count` alongside the `telemetry_ids` of the rows written.

Closing real time stores the preliminary real-time components — `rt_prelim_energy_cents_per_mwh`, `rt_prelim_congestion_cents_per_mwh`, and `rt_prelim_loss_cents_per_mwh` from the `rt_node_prices_prelim` deck — onto the day's price nodes, shuts the telemetry window for the day, and advances the day `DA_GATED` → `RT_COMPLETE`, incrementing the day's `version` by one.

### 3.4. Outages, Derates, and the Availability Cascade

A `Trader` files an outage report for a generator with an `outage_type` of `FULL` or `PARTIAL`, a `derate_pct` (exactly one hundred for `FULL`, between one and ninety-nine for `PARTIAL`), a window from `start_at` to `end_at` with the start strictly before the end, and a free-text `reason`. The window is half-open per §2.9. The new report must not intersect any of the same generator's reports in `SUBMITTED`, `ACKNOWLEDGED`, or `APPROVED`: because windows are half-open, a report that starts exactly when another ends is permitted, while any true intersection is rejected with `ERR_OUTAGE_OVERLAP`. A filed report starts `SUBMITTED`.

The `IsoOperator` first acknowledges a submitted report, moving it `SUBMITTED` → `ACKNOWLEDGED`, and may then approve it. Approval fires a three-link cascade. Link one: the generator's `availability_mw` is recomputed per §2.9, and if the approved outage is `FULL` and its window covers the current logical instant the generator moves `AVAILABLE` → `ON_OUTAGE`; conversely, whenever no covering `APPROVED` `FULL` outage remains — the window has elapsed or the report was cancelled — the generator returns `ON_OUTAGE` → `AVAILABLE` with availability recomputed. Link two: every capacity obligation of the generator in `ACTIVE` or `AT_RISK` recomputes its `expected_output_mw` as the smaller of `obligated_mw` and the new `availability_mw`; an obligation whose expected output now falls short of its obligated MW moves `ACTIVE` → `AT_RISK`, and one fully covered again moves `AT_RISK` → `ACTIVE`. Link three: on every transition into `AT_RISK` the participant's requirement is recomputed with the capacity risk adder of §2.8 (five hundred dollars per obligated MW) and credit posture is evaluated — an approval can therefore issue a margin call and move the participant to `MARGIN_CALL` with no further action. Symmetrically, every return from `AT_RISK` to `ACTIVE` drops the adder and re-evaluates posture.

The operator may instead deny an acknowledged report, moving it `ACKNOWLEDGED` → `DENIED` and recording the request's `denial_reason` on the report. Denial is not terminal: a `Trader` may resubmit the report, optionally correcting `derate_pct`, `start_at`, `end_at`, or `reason`, which cycles it `DENIED` → `SUBMITTED`. The overlap rule is re-evaluated against the generator's live reports at resubmission (`ERR_OUTAGE_OVERLAP`), and the denial-and-resubmission cycle may repeat any number of times.

Cancellation by a `Trader` moves a report from `SUBMITTED`, `ACKNOWLEDGED`, or `APPROVED` to `CANCELLED`, which is terminal. Cancelling an unapproved report has no further effect. Cancelling an `APPROVED` report compensates the approval cascade: availability is recomputed without that outage, obligations whose expected output is restored to the obligated MW return from `AT_RISK` to `ACTIVE`, the capacity risk adder is removed from the requirement, and credit posture is re-evaluated — which may cure an open margin call.

### 3.5. Settlement Runs and Statement Anatomy

With the day `RT_COMPLETE`, the `IsoOperator` runs preliminary settlement. For every participant with settlement activity on the day (the input set of §2.10), the system issues a `PRELIMINARY` SettlementStatement together with its lines, computed on the preliminary price variant and the telemetry set as it stands. The day advances `RT_COMPLETE` → `PRELIM_SETTLED` with its `version` incremented by one, and every ancillary award still `AWARDED` on the day moves to `SETTLED` with its revenue computed per §3.6.

Each statement collects, per participant and day, the following aggregates. The day-ahead energy credit `da_energy_credit_cents` is the sum over that participant's `CLEARED` offers of twenty-four intervals times the offer's `cleared_mw` times the node's day-ahead energy component — a positive figure that is subtracted in the net. `imbalance_charge_cents`, `congestion_charge_cents`, and `loss_charge_cents` carry the real-time and allocation results below. `ancillary_revenue_cents` is also subtracted in the net, and `capacity_charge_cents` carries the performance results of §3.6.

The real-time energy imbalance is computed per cleared offer, interval by interval in ascending hour order across the day's twenty-four intervals. For each interval, the metered quantity is the `actual_mw` of the `RECORDED` telemetry row for that generator, day, and interval — a missing interval counts as zero — and the deviation is the metered quantity minus the cleared MW. A deadband of five percent of the cleared MW, carried as an exact number and never rounded, shields small errors: the portion of the deviation inside the deadband settles at the full real-time energy component at the generator's node, with short positions (metered below cleared) paying and long positions being credited — the settlement amount for that portion is the negated within-deadband deviation times the real-time energy price. When the deviation's absolute size exceeds the deadband, the excess is treated asymmetrically: a shortfall excess is charged at one hundred and ten percent of the real-time energy price, while a surplus excess is credited at only ninety percent. A deviation whose absolute size equals the deadband exactly carries no penalty portion — the entire deviation settles at the hundred-percent rate. Each interval's signed energy amount is rounded half up to whole cents, and the twenty-four rounded amounts are then summed into the signed `imbalance_charge_cents`; per §2.6, summing first and rounding once is not permitted. Telemetry for a generator with no `CLEARED` offer on that day is excluded from settlement entirely.

Congestion and loss allocations follow the same per-interval discipline for each cleared offer. Each interval charges the cleared MW times the node's day-ahead congestion component and, separately, the cleared MW times the day-ahead loss component — both positive charges. The real-time side re-prices the deviation: the negated deviation times the node's real-time congestion component, and the negated deviation times the real-time loss component, so a short interval pays real-time congestion and losses on its shortfall while a long interval is credited. Every per-interval component is rounded half up to whole cents first; the rounded congestion components are then summed into `congestion_charge_cents` and the rounded loss components into `loss_charge_cents`. Which real-time component set feeds these formulas follows the settlement run variant per §2.10.

Running final settlement while the day is `PRELIM_SETTLED` carries the `rt_node_prices_final` deck, stores the `rt_final_energy_cents_per_mwh`, `rt_final_congestion_cents_per_mwh`, and `rt_final_loss_cents_per_mwh` components onto the day's price nodes, supersedes every `PRELIMINARY` statement of the day (`ISSUED` → `SUPERSEDED`), and issues `FINAL` statements on the final variant against the full corrected telemetry set. Each final statement is stamped with `issued_at` at the current logical instant and `dispute_window_ends_at` exactly seventy-two hours later. Final settlement then evaluates credit posture for every participant per §2.8, which may issue margin calls and move participants to `MARGIN_CALL`. The day advances `PRELIM_SETTLED` → `FINAL_SETTLED`, its `version` incremented by one.

Closing the day moves it `FINAL_SETTLED` → `CLOSED` — a terminal epoch — and requires that no statement of the day remain `UNDER_DISPUTE`; while any dispute is open the close is rejected with `ERR_UNRESOLVED_DISPUTES`. On close, every statement still `ISSUED` moves to `CLOSED`, and the day's `version` increments once more. Independently of the day close, a statement may reach `PAID` through the collateral draw waterfall of §3.8, at which point it leaves the requirement input set and the participant's requirement is recomputed. `SUPERSEDED`, `CLOSED`, and `PAID` are the statement's terminal states.

### 3.6. Ancillary Awards and Capacity Performance

The `IsoOperator` awards ancillary services to a generator for a window of an operating day, naming the `generator_asset_id`, a `service_type` of `REGULATION`, `SYNC_RESERVE`, or `SUPPLEMENTAL_RESERVE`, a strictly positive `awarded_mw`, a `capacity_price_cents` per MW, and the closed interval from `start_interval` through `end_interval` — each within one through twenty-four, with the end not before the start. `REGULATION` awards additionally require `performance_price_cents` and a `mileage_ratio`; omitting either for a regulation award is rejected with `ERR_INVALID_REQUEST`. The day must be `DA_OPEN` or `DA_GATED` (`ERR_MARKET_NOT_OPEN`), and the award's closed window must not intersect — at interval granularity — any `APPROVED` outage window of the same generator on that day (`ERR_AWARD_OVERLAPS_OUTAGE`). A new award starts `AWARDED` with `revenue_cents` zero.

At either settlement run, each award still `AWARDED` on the settled day is scored and paid. Within the closed award window, an interval qualifies when a `RECORDED` telemetry row shows `actual_mw` of at least ninety percent of `awarded_mw`; an interval with no recorded telemetry counts as non-qualifying. The `performance_score` is the count of qualifying intervals divided by the window length in hours. A tier multiplier applies to the capacity side only: one hundred percent when the score is at least 0.95; eighty-five percent when the score is at least 0.75 but below 0.95 — a score of exactly 0.75 lands in the eighty-five-percent tier; fifty percent when the score is at least 0.50 but below 0.75; and zero when the score is below 0.50. The capacity component is `awarded_mw` times `capacity_price_cents` times the tier multiplier. A `REGULATION` award additionally earns a performance component of `awarded_mw` times `performance_price_cents` times `mileage_ratio` — notably not scaled by the tier multiplier — while other service types earn no performance component. The award's `revenue_cents` is the half-up-rounded sum of the two components, and the award moves `AWARDED` → `SETTLED`; `SETTLED` is terminal.

The operator may cancel an award while its day is still `DA_OPEN`, `DA_GATED`, or `RT_COMPLETE`; once preliminary settlement has run, cancellation is rejected with `ERR_INVALID_STATE_TRANSITION`. A cancelled award moves `AWARDED` → `CANCELLED` (terminal), keeps `revenue_cents` at zero, and is excluded from the settlement input set.

Capacity performance events are the enforcement arm behind the obligations of §3.1. The `IsoOperator` declares an event on an operating day with a closed `start_interval`-to-`end_interval` window; the declaration leaves the event `DECLARED`. The declaration is valid only if it preserves a one-hour buffer against every sibling event in `DECLARED`, `ACTIVE`, or `COMPLETED` on the same day: the new event's first interval must be at least two greater than the sibling's last interval, or the sibling's first interval at least two greater than the new event's last interval — one full gap hour is mandatory, and direct adjacency (one event ending at hour h, the next beginning at hour h+1) is a violation rejected with `ERR_EVENT_BUFFER_VIOLATION`. The operator then activates a declared event (`DECLARED` → `ACTIVE`) and later completes it; completion requires the event's day to be `DA_OPEN`, `DA_GATED`, or `RT_COMPLETE` — once preliminary settlement has run, completion is rejected with `ERR_INVALID_STATE_TRANSITION` — and moves the event `ACTIVE` → `COMPLETED`, which is terminal.

Completion runs the capacity performance charge over every obligation in `ACTIVE` or `AT_RISK` whose `delivery_period` matches the year-month of the event day's `market_date`. The event length in hours is `end_interval` minus `start_interval` plus one. For each in-scope obligation, expected output is the smaller of `obligated_mw` and the generator's `availability_mw`, and actual output is the mean of the `RECORDED` telemetry `actual_mw` values across the event window, with a missing interval counting as zero. The shortfall — expected minus actual, floored at zero — times 50000 cents per MWh (five hundred dollars) times the event length in hours, rounded half up to whole cents, is the obligation's penalty. Penalties pool: the event's `penalties_collected_cents` is the sum of all penalties assessed.

The pool is then redistributed to over-performers, revenue-neutral. Each obligation whose actual output exceeded its expected output holds a bonus claim equal to its surplus — actual minus expected — times the event length, in megawatt-hours. Each claimant receives the pool scaled by its share of the total claims, rounded half up per claimant, and any rounding remainder goes to the claimant with the largest claim, with ties broken by the obligation's earlier `created_at`. If no obligation over-performed, the market operator retains the pool and `bonuses_paid_cents` is zero; otherwise `bonuses_paid_cents` is the sum of the bonuses and equals the pool. Each obligation accrues its penalty into `accrued_penalty_cents` and its bonus into `accrued_bonus_cents`, and credit posture is evaluated for every affected participant. On the settlement statement of the event's day, a participant's `capacity_charge_cents` is the sum of penalties minus the sum of bonuses across that participant's obligations in scope of events completed on that day.

Closing an obligation — permitted from `ACTIVE` or `AT_RISK` — fixes its economics in a pinned evaluation order. First, `gross_revenue_cents` is computed as `obligated_mw` times `capacity_rate_cents_per_mw`, rounded half up to whole cents; this happens before any penalty offset and serves as the cap basis. Second, the stop-loss cap is one and a half times the gross revenue, rounded half up to whole cents. Third, `charged_penalty_cents` is the smaller of `accrued_penalty_cents` and the cap — an accrual exactly equal to the cap is charged in full. Fourth, `forgiven_penalty_cents` is the accrual minus the charged amount. The net capacity settlement is never fed back into `gross_revenue_cents`. Closing an obligation in `AT_RISK` additionally removes the capacity risk adder from the participant's requirement and re-evaluates credit; either close leaves the obligation `CLOSED`, which is terminal.

### 3.7. Disputes and Resettlement

A `SettlementAnalyst` challenges a statement by filing a dispute carrying a `dispute_reason` of `PRICE_ERROR`, `METER_DATA_ERROR`, `CALCULATION_ERROR`, or `MISSING_ANCILLARY_CREDIT`, plus a non-empty `disputed_line_ids` list in which every element must be a line belonging to the disputed statement — a line from any other statement is rejected with `ERR_LINE_NOT_IN_STATEMENT`. Only statements whose `run_type` is `FINAL` or `RESETTLEMENT` may be disputed; filing against a `PRELIMINARY` statement is rejected with `ERR_STATEMENT_NOT_FINAL`. A statement supports at most one open dispute: a second filing while another dispute of the same statement is `FILED` or `UNDER_REVIEW` is rejected with `ERR_DISPUTE_ALREADY_OPEN`. And the filing must land at or before `dispute_window_ends_at` — a filing at exactly the window end is accepted, a strictly later one rejected with `ERR_DISPUTE_WINDOW_CLOSED`. A successfully filed dispute starts `FILED`, and the statement moves `ISSUED` → `UNDER_DISPUTE`.

The `IsoOperator` takes a filed dispute into review, moving it `FILED` → `UNDER_REVIEW`, and then resolves it with an `outcome`. A `REJECTED` outcome returns the statement from `UNDER_DISPUTE` to `ISSUED` with its amounts unchanged, and the dispute is terminal. An `UPHELD` outcome supersedes the disputed statement — it moves from `UNDER_DISPUTE` to `SUPERSEDED` — and issues a `RESETTLEMENT` statement in its place: the new statement's `supersedes_statement_id` points at the disputed statement, its `issued_at` is the current logical instant, and its `dispute_window_ends_at` reopens seventy-two hours later. Every component field copies over from the disputed statement except that each component containing a disputed line is reduced by that line's `amount_cents`, and `net_amount_cents` becomes the disputed statement's net minus the sum of the disputed lines' amounts; `paid_cents` carries over unchanged. Because the superseded statement leaves the collateral requirement input set while the resettlement statement enters it, the participant's requirement is recomputed and credit posture re-evaluated — an upheld dispute that erases a deficiency cures the open margin call and returns the participant from `MARGIN_CALL` to `ACTIVE` per §2.8.

The filer may also withdraw a dispute while it is still `FILED`, moving it to `WITHDRAWN` and returning the statement from `UNDER_DISPUTE` to `ISSUED`. `UPHELD`, `REJECTED`, and `WITHDRAWN` are all terminal for the dispute, but the statement itself may be disputed again later within its window — the `ISSUED` ↔ `UNDER_DISPUTE` cycle can repeat.

### 3.8. Margin Calls, Collateral Draws, and Suspension

The margin machinery of §2.8 drives each participant through three credit postures. `ACTIVE` participants trade freely. When an evaluation finds posted collateral short of the effective requirement and no margin call is open, the participant moves `ACTIVE` → `MARGIN_CALL` and a MarginCall is issued `OPEN`, with `required_additional_cents` equal to the shortfall at issuance and `due_at` twenty-four hours later. Cure can arrive three ways — a new collateral posting, a shrinkage of the requirement (an offer withdrawn or cleared, an outage cancelled, an obligation closed or restored), or an upheld dispute reducing exposure — and any evaluation that finds posted collateral at or above the effective requirement at or before `due_at` marks the call `CURED` and returns the participant `MARGIN_CALL` → `ACTIVE`; a cure landing at exactly `due_at` is accepted. If the logical clock passes `due_at` with the deficiency still standing, the call becomes `DEFAULTED` and the participant moves `MARGIN_CALL` → `SUSPENDED`. Suspended participants cannot submit offers (`ERR_PARTICIPANT_SUSPENDED`) and never auto-reinstate: only an explicit credit evaluation by the `IsoOperator`, granted when posted collateral again covers the effective requirement, moves `SUSPENDED` → `ACTIVE`. `CURED` and `DEFAULTED` are terminal for the call.

A `CreditOfficer` may release a `POSTED` posting back to its participant, but only when the participant has no `OPEN` margin call (`ERR_OPEN_MARGIN_CALL`) and the release leaves `posted_collateral_cents` at or above the effective requirement — equality is allowed, while a release that would leave collateral strictly short is rejected with `ERR_COLLATERAL_SHORTFALL`. A successful release moves the posting `POSTED` → `RELEASED`, reduces the participant's `posted_collateral_cents` by the posting's `amount_cents`, leaves the requirement unchanged, and re-evaluates credit posture.

Once a participant holds a `DEFAULTED` margin call, the `IsoOperator` may draw on one of its `POSTED` postings; a draw attempted while the participant has no defaulted call is rejected with `ERR_POSTING_NOT_DRAWABLE`. The posting moves `POSTED` → `DRAWN`, the participant's `posted_collateral_cents` falls by `amount_cents`, and the drawn amount waterfalls across the participant's `ISSUED` statements whose `net_amount_cents` exceeds their `paid_cents`, oldest first — ordered by `issued_at` ascending, with ties broken by `created_at` ascending — raising each statement's `paid_cents` until the draw is exhausted. A statement with a positive net whose `paid_cents` reaches its `net_amount_cents` moves `ISSUED` → `PAID` and leaves the requirement input set, so the participant's requirement is recomputed. A draw amount larger than the total uncovered statement balance is rejected with `ERR_INVALID_REQUEST` — the residual beyond uncovered statements is never absorbed.

## 4. Endpoint Definitions

Operations that create a new resource — registering a participant, generator, or operating day, drafting an offer, submitting a telemetry batch, filing an outage report or a dispute, granting an award, creating an obligation, declaring a performance event, or posting collateral — return `201 Created`. Reads, state-transition actions, and market-run operations return `200 OK`. List endpoints accept optional filter parameters drawn from their resource's natural keys: generators filter by `market_participant_id` and `status`; offers by `operating_day_id`, `generator_asset_id`, and `status`; telemetry by `generator_asset_id`, `operating_day_id`, and `interval_index`; outages by `generator_asset_id` and `status`; statements by `market_participant_id`, `operating_day_id`, `status`, `run_type`, and `supersedes_statement_id`; lines by `settlement_statement_id`, `generator_asset_id`, and `charge_type`; disputes by `settlement_statement_id`, `market_participant_id`, and `status`; awards by `generator_asset_id`, `operating_day_id`, and `status`; obligations by `generator_asset_id` and `status`; events by `operating_day_id` and `status`; postings by `market_participant_id` and `status`; and margin calls by `market_participant_id` and `status`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/market/_clock/set_current_utc` | Set the logical clock used by every gate, window, and deadline rule | IsoOperator |
| POST | `/market/participants` | Register a market participant | IsoOperator |
| GET | `/market/participants/{participantId}` | Get a market participant | All roles |
| POST | `/market/participants/{participantId}/evaluate-credit` | Recompute the participant's requirement and run credit posture evaluation | IsoOperator |
| POST | `/market/generators` | Register a generator for a participant | IsoOperator |
| GET | `/market/generators/{generatorId}` | Get a generator | All roles |
| GET | `/market/generators` | List generators | All roles |
| POST | `/market/generators/{generatorId}/decommission` | Decommission an AVAILABLE generator with no open commitments | Trader |
| POST | `/market/operating-days` | Create an operating day | IsoOperator |
| GET | `/market/operating-days/{operatingDayId}` | Get an operating day | All roles |
| POST | `/market/operating-days/{operatingDayId}/run-day-ahead-market` | Gate the day, post the day-ahead price deck, and run clearing | IsoOperator |
| POST | `/market/operating-days/{operatingDayId}/close-real-time` | Close the telemetry window and post preliminary real-time prices | IsoOperator |
| POST | `/market/operating-days/{operatingDayId}/run-preliminary-settlement` | Generate PRELIMINARY settlement statements and settle awards | IsoOperator |
| POST | `/market/operating-days/{operatingDayId}/run-final-settlement` | Supersede preliminaries, issue FINAL statements, evaluate credit | IsoOperator |
| POST | `/market/operating-days/{operatingDayId}/close` | Close the operating day | IsoOperator |
| GET | `/market/operating-days/{id}/price-nodes` | List the price nodes of an operating day | All roles |
| POST | `/market/operating-days/{operatingDayId}/offers` | Create a DRAFT day-ahead offer; supersedes any live offer for the same generator and day; OCC-guarded on the day | Trader |
| POST | `/market/offers/{offerId}/submit` | Submit a DRAFT offer into the day-ahead market | Trader |
| POST | `/market/offers/{offerId}/withdraw` | Withdraw a SUBMITTED offer back to DRAFT | Trader |
| GET | `/market/offers/{offerId}` | Get an offer | All roles |
| GET | `/market/offers` | List offers | All roles |
| POST | `/market/generators/{generatorId}/telemetry` | Submit a batch of interval readings for one operating day; OCC-guarded on the generator | Trader |
| GET | `/market/telemetry/{telemetryId}` | Get a telemetry row | All roles |
| GET | `/market/telemetry` | List telemetry rows | All roles |
| POST | `/market/generators/{generatorId}/outages` | File an outage/derate report | Trader |
| GET | `/market/outages/{outageId}` | Get an outage report | All roles |
| GET | `/market/outages` | List outage reports | All roles |
| POST | `/market/outages/{outageId}/acknowledge` | Acknowledge a submitted outage report | IsoOperator |
| POST | `/market/outages/{outageId}/approve` | Approve an acknowledged report, firing the availability cascade | IsoOperator |
| POST | `/market/outages/{outageId}/deny` | Deny an acknowledged report | IsoOperator |
| POST | `/market/outages/{outageId}/resubmit` | Resubmit a DENIED report with corrections | Trader |
| POST | `/market/outages/{outageId}/cancel` | Cancel a report; cancelling APPROVED compensates the approval cascade | Trader |
| GET | `/market/statements/{statementId}` | Get a settlement statement | All roles |
| GET | `/market/statements` | List settlement statements | All roles |
| GET | `/market/statements/{statementId}/lines` | List the lines of a statement | All roles |
| GET | `/market/lines/{lineId}` | Get a settlement line | All roles |
| GET | `/market/lines` | List settlement lines | All roles |
| POST | `/market/statements/{statementId}/disputes` | File a dispute against a FINAL or RESETTLEMENT statement within its dispute window | SettlementAnalyst |
| GET | `/market/disputes/{disputeId}` | Get a dispute | All roles |
| GET | `/market/disputes` | List disputes | All roles |
| POST | `/market/disputes/{disputeId}/start-review` | Take a filed dispute into review | IsoOperator |
| POST | `/market/disputes/{disputeId}/resolve` | Resolve a dispute; UPHELD issues a RESETTLEMENT statement and re-evaluates credit | IsoOperator |
| POST | `/market/disputes/{disputeId}/withdraw` | Withdraw a FILED dispute | SettlementAnalyst |
| POST | `/market/operating-days/{operatingDayId}/awards` | Award an ancillary service to a generator for a window of the day | IsoOperator |
| GET | `/market/awards/{awardId}` | Get an award | All roles |
| GET | `/market/awards` | List awards | All roles |
| POST | `/market/awards/{awardId}/cancel` | Cancel an award before preliminary settlement | IsoOperator |
| POST | `/market/obligations` | Create a capacity obligation for a generator and delivery period | IsoOperator |
| GET | `/market/obligations/{obligationId}` | Get an obligation | All roles |
| GET | `/market/obligations` | List obligations | All roles |
| POST | `/market/obligations/{obligationId}/close` | Close an obligation, fixing its stop-loss economics | IsoOperator |
| POST | `/market/operating-days/{operatingDayId}/performance-events` | Declare a capacity performance event | IsoOperator |
| GET | `/market/events/{eventId}` | Get a performance event | All roles |
| GET | `/market/events` | List performance events | All roles |
| POST | `/market/events/{eventId}/activate` | Activate a declared event | IsoOperator |
| POST | `/market/events/{eventId}/complete` | Complete an active event and run the capacity performance charge | IsoOperator |
| POST | `/market/participants/{participantId}/postings` | Post collateral (cash or letter of credit) | CreditOfficer |
| GET | `/market/postings/{postingId}` | Get a posting | All roles |
| GET | `/market/postings` | List postings | All roles |
| POST | `/market/postings/{postingId}/release` | Release a posting back to the participant | CreditOfficer |
| POST | `/market/postings/{postingId}/draw` | Draw on a posting to cover a defaulted participant's ISSUED statements, oldest first | IsoOperator |
| GET | `/market/margin-calls/{marginCallId}` | Get a margin call | All roles |
| GET | `/market/margin-calls` | List margin calls | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ASSET_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 Conflict |
| `ERR_MARKET_NOT_OPEN` | 409 Conflict |
| `ERR_GENERATOR_NOT_AVAILABLE` | 409 Conflict |
| `ERR_PARTICIPANT_SUSPENDED` | 409 Conflict |
| `ERR_STATEMENT_NOT_FINAL` | 409 Conflict |
| `ERR_OPEN_MARGIN_CALL` | 409 Conflict |
| `ERR_POSTING_NOT_DRAWABLE` | 409 Conflict |
| `ERR_GENERATOR_HAS_OPEN_COMMITMENTS` | 409 Conflict |
| `ERR_UNRESOLVED_DISPUTES` | 409 Conflict |
| `ERR_DA_GATE_CLOSED` | 409 Conflict |
| `ERR_TELEMETRY_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_OPERATING_DAY_EXISTS` | 409 Conflict |
| `ERR_OBLIGATION_DUPLICATE_PERIOD` | 409 Conflict |
| `ERR_OUTAGE_OVERLAP` | 409 Conflict |
| `ERR_EVENT_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_AWARD_OVERLAPS_OUTAGE` | 409 Conflict |
| `ERR_OFFER_MW_EXCEEDS_AVAILABILITY` | 409 Conflict |
| `ERR_PRICE_DECK_INCOMPLETE` | 409 Conflict |
| `ERR_CREDIT_HEADROOM_EXCEEDED` | 409 Conflict |
| `ERR_COLLATERAL_SHORTFALL` | 409 Conflict |


