# Subcontractor Buyout & Contract Award API — Product Requirements Document

## 1. Introduction

This document specifies the Subcontractor Buyout & Contract Award API, the system of record a general contractor's project buyout team uses to convert an estimated construction budget into a portfolio of awarded, insured, and executable subcontracts. The workflow it governs is the single highest-leverage phase of a GC project's financial lifecycle: after bids close, the team levels the bids, hunts down scope gaps, negotiates allowance and alternate dispositions, decides bonding by trade risk, writes the schedule of values, and shepherds each subcontract through award, issuance, execution, and — when a subcontractor fails — default and replacement.

The system exists because buyout is a multi-party negotiation wrapped in a compliance audit. An estimator records bids against a deadline; a buyout lead levels them and negotiates; an operations manager awards, decides bonding, and acts on default; a vice president exercises waiver authority over allowance qualifications and insurance exclusions; a project manager and project executive approve change orders inside authority tiers; and a GC administrator owns the project's logical clock, which drives every time-sensitive rule in the domain. Without a single source of truth, buyout savings evaporate into scope gaps that were never priced, change orders that outran their approver's authority, and certificates of insurance that expired before anyone noticed.

Every rule in this document is written for the engineer implementing the API. State names, error identifiers, monetary precision, and concurrency mechanics are contractual; the narrative that surrounds them is deliberately distributed so that a complete implementation requires reading the whole document.

## 2. Global Specifications & System-Wide Principles

This section pins the cross-cutting contracts: who may call what, what every response looks like, how lists paginate, how time works, how money is counted, and how concurrent writers are kept honest.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's capacity. A request missing either header, or presenting a role string outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is well-formed but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes exactly eight roles, spelled as follows: `GCAdmin`, `BuyoutLead`, `OperationsManager`, `ProjectExecutive`, `ProjectManager`, `VicePresident`, `Estimator`, and `SupplierDiversity`. Their charters, in brief: a `GCAdmin` owns project lifecycle and the logical clock; a `BuyoutLead` levels bids, negotiates, recommends award, issues and executes subcontracts, and manages gaps and schedules of values; an `OperationsManager` awards subcontracts, records bonding decisions, declares default and replacement, approves schedules of values, and voids change orders; a `ProjectExecutive` approves change orders at an elevated authority tier; a `ProjectManager` initiates and approves change orders at a mid authority tier; a `VicePresident` holds waiver authority over allowance qualifications and insurance exclusions; an `Estimator` records bids during the bid window; and a `SupplierDiversity` officer may initiate change orders for compliance-driven scope adjustments.

For every one of these eight roles — `GCAdmin`, `BuyoutLead`, `OperationsManager`, `ProjectExecutive`, `ProjectManager`, `VicePresident`, `Estimator`, and `SupplierDiversity` alike — the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `decided_by_user_id` on a `BondDecision` or as `created_by_user_id` on a `ChangeOrder`) but never compares it to any entity's `id`. Segregation-of-duties checks on change-order approval compare `X-User-ID` against the change order's recorded `created_by_user_id`, not against any entity identifier.

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

A request whose body is not a valid JSON object, that omits a required field, or that supplies a value of the wrong type or outside an enumerated set is rejected with `ERR_VALIDATION` (HTTP 422). A request that resolves to no declared route — including an unsupported method on an existing path — is answered with `ERR_NOT_FOUND` (HTTP 404). Any unexpected server failure is answered with `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Values that are not integers, a `limit` below 1 or above 100, and a negative `offset` are rejected with `ERR_VALIDATION` (HTTP 422).

Unless a subsection says otherwise, every list endpoint returns its resources sorted by `created_at` ascending — oldest first.

Paginated list responses populate the `meta` object of the envelope with four fields: `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through the full result set; `has_more` is true exactly when `offset + limit` is less than `total_count`. Several list endpoints additionally accept a `status` query parameter filtering by lifecycle state — the trade-package, bid, gap, subcontract, insurance-certificate, and change-order lists — plus a `category` query parameter on the gap list and a `basis` query parameter on the computed reads (§2.11); a filter value that matches no resource simply yields an empty page.

### 2.4. The Project Logical Clock

Time in this system is not wall-clock time. Every `Project` carries a `current_time_utc` field — its logical clock — which is initialized at creation to `2026-05-01T00:00:00Z` and never moves on its own. Only a `GCAdmin` may advance it, via the dedicated clock-advance capability, supplying a `to_iso8601` instant that becomes the project's new `current_time_utc`. Each clock advance increments the project's `version` by 1.

Every temporal rule in the domain keys off this logical clock: whether a bid window is still open at publish, whether a bid arrived before its deadline, whether a certificate of insurance has expired. Advancing the clock re-evaluates certificate expiry across the project, so a single clock step can flip certificates from `ISSUED` to `EXPIRED` and change subcontract `insurance_status` values without any certificate ever being re-submitted.

### 2.5. Common Resource Properties

Every primary resource in the system — `Project`, `TradePackage`, `Bid`, `ScopeGap`, `Subcontract`, `InsuranceCertificate`, `BondDecision`, `ScheduleOfValues`, and `ChangeOrder` — carries four system-managed fields:

- `id` — a server-minted UUID rendered in its canonical dashed lowercase string form (five hexadecimal groups in an 8-4-4-4-12 pattern, for example `550e8400-e29b-41d4-a716-446655440000`), with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that starts at 1 and increments by 1 on every mutation of the resource.

The `created_at` and `updated_at` timestamps are server wall-clock UTC, not the project logical clock; the logical clock supplies only the explicitly logical stamps (`recorded_at`, `approved_at`, `default_recorded_at`). The one exception is the `NegotiationRound`, which is an append-only record: it carries `id` and `created_at` but no `updated_at` and no `version`, because a round is never modified once recorded.

Any cascade that mutates a parent — for example, a subcontract execution recomputing its package's `awarded_value_cents`, or a change-order approval bumping its subcontract's `contract_value_cents` — refreshes the parent's `updated_at` and increments its `version`, exactly as if the parent had been written directly.

### 2.6. Monetary Precision and Rounding

All money in the system is carried as integer cents — fields named with the `_cents` suffix are integers, never floats. Fractional multipliers (the buyout savings target percentage, the retainage band, bond premium rates, the subguard claim percentage) are applied to integer cents and the result is rounded half-up to the nearest cent at the point the calculation specifies. The composite trade risk score is an integer sum of integer point values and requires no rounding. The change-authority cumulative check compares a ratio in exact rational arithmetic, and the boundary is inclusive — a ratio exactly equal to the tier's `max_cumulative_pct` passes.

### 2.7. Optimistic Concurrency Control on Package Creation

One write endpoint in the system carries an optimistic-concurrency guard. When creating a `TradePackage` under a project, the request body must include `expected_project_version`, carrying the `version` of the parent `Project` as the client last observed it. If the project's current `version` has advanced since that read — because another writer opened the project, advanced the clock, or created another package, each of which increments `Project.version` by 1 — the create is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412), forcing the client to re-read the project before retrying. No other endpoint takes a version field; all other mutations proceed without an OCC check.

### 2.8. Hierarchical Consistency and Bubble-Up Recomputation

The aggregate hierarchy runs `Project` → `TradePackage` → `Subcontract` (with `Bid`, `ScopeGap` as package children, and `NegotiationRound`, `InsuranceCertificate`, `BondDecision`, `ScheduleOfValues`, `ChangeOrder` as subcontract children). Parent state is, in part, derived from child state, and the server maintains that derivation automatically. When the last piece of buyout work on a package settles — exactly one subcontract `EXECUTED` and every sibling in a terminal-or-replaced posture — the package bubbles up from `BUYOUT_IN_PROGRESS` to `AWARDED` without any client call against the package itself. When every package of a project is `AWARDED`, the project bubbles from `BUYOUT_OPEN` to `BUYOUT_COMPLETE`. The reverse direction also fires automatically: a default or replacement that strips a package of its last `EXECUTED` subcontract drops the package back to `BUYOUT_IN_PROGRESS`, and a project that was `BUYOUT_COMPLETE` reopens (`BUYOUT_COMPLETE → BUYOUT_OPEN`) the moment any package leaves `AWARDED`. Each such automatic reconciliation mutates the affected parent, refreshing `updated_at` and incrementing `version` per §2.5. This reconciliation is re-evaluated on every subcontract state mutation — execution, declare-default, replacement, and termination alike — so, for example, terminating a `DRAFT` sibling while exactly one `EXECUTED` subcontract remains and all others are terminal also bubbles the package to `AWARDED`.

### 2.9. Nested Resource Retrieval

Requests that address a nested resource validate the path left to right. For a URL of the form `/trade-packages/{id}/bids/{id}/withdraw`, the server first confirms the trade package exists, then confirms the bid exists within that package; the first identifier that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404) and no further segment is evaluated. The same ordering applies to deeper paths and to creation under a parent: the parent's existence is established before any child-scope rule runs.

### 2.10. Validation Priority Ordering

When a request fails several checks at once, the response carries the error from the highest-priority failing check, where priority runs as follows. Authentication context (§2.1) is checked first — a missing header beats every other failure — followed by role authorization. Resource existence along the path (§2.9) comes next. Syntactic payload validation — a body that is not a JSON object, a missing required field, a wrongly typed value, or a value outside an enumerated set, all surfaced as `ERR_VALIDATION` (HTTP 422) — runs after existence and before the optimistic-concurrency and state-validity checks. The optimistic-concurrency check on package creation (§2.7) follows existence. State-validity checks (from-state gates, derived-field gates such as the project being `BUYOUT_OPEN`, the negotiation round cap, terminal-subcontract protection, the approved-SOV precondition on change-order creation, the insurance and bonding gates at issue and execute, and the withdrawn-bid block on SOV submission) come after that. Within bid award specifically, the empty-candidate-set check fires before the target-bid status check, so a package with no `PLACED` or `AWARDED` bids surfaces `ERR_NO_AWARDABLE_BID` rather than `ERR_BID_NOT_AWARDABLE` regardless of which bid was named. The life-safety gap block outranks the fiscal checks. At subcontract award, the headline cap check (this subcontract's `contract_value_cents` alone exceeding the package budget plus remaining contingency, yielding `ERR_AWARD_EXCEEDS_BUDGET`) is evaluated before the projected-total check that yields `ERR_CONTINGENCY_EXCEEDED`. Negotiation completeness at recommend-award runs in its own fixed order: a payload that omits the disposition or selection arrays entirely for a bid that carries allowances or alternates fails with `ERR_NEGOTIATION_TERMS_INCOMPLETE`; a specific allowance lacking a disposition fails with `ERR_ALLOWANCE_UNRESOLVED`; a specific alternate lacking a selection fails with `ERR_ALTERNATE_UNRESOLVED`.

### 2.11. Dual Calculation Bases: PROVISIONAL and FINAL

Two read paths in the system — the per-package computed read and the project buyout summary — accept an optional `basis` selector of `PROVISIONAL` or `FINAL`, defaulting to `PROVISIONAL` when omitted. The basis governs which subcontracts count as awarded anchors when a package's `awarded_value_cents` is computed. Under the `PROVISIONAL` basis — the working view during buyout — only subcontracts in `EXECUTED` status anchor value. Under the `FINAL` basis — used for buyout close-out reporting — both `EXECUTED` and `PENDING_AWARD` subcontracts anchor value. Everything else about the computation (the contingency consumption, the savings subtraction, the posture thresholds) is identical between the two bases.

## 3. Business Logic & Workflows

This section walks the buyout lifecycle as the team lives it: standing up the project, shaping trade packages, running the bid window, leveling and gap analysis, the negotiation loop, the compliance gates (insurance and bonding), issuance and execution, the schedule of values and change orders under authority limits, and finally default and replacement. State names appear as exact uppercase strings; the state-pair notation (`DRAFT → PENDING_AWARD`) is the bridge back to the endpoint table in §4.

### 3.1. Standing Up the Project

A `GCAdmin` creates a `Project` by supplying its `name`, a `project_number` unique across all projects (a collision is rejected with `ERR_VALIDATION`, HTTP 422), the `estimated_budget_cents` for the whole job, and the `buyout_target_savings_pct` — a fraction (for example, 0.05) expressing how much of the estimate the buyout team is expected to save. A new project lands in `SETUP` with its logical clock at `2026-05-01T00:00:00Z`. While a project is in `SETUP`, no child mutations are possible: any attempt to create or mutate a trade package under it is rejected with `ERR_PACKAGE_NOT_OPEN`. Opening the project — a `GCAdmin` action — moves it `SETUP → BUYOUT_OPEN` (an open call against a project in any other state is rejected with `ERR_INVALID_STATE_TRANSITION`) and increments the project's `version` by 1.

Once `BUYOUT_OPEN`, the project admits trade packages — and it continues to admit them after `BUYOUT_COMPLETE`; only a project still in `SETUP` rejects package creation with `ERR_PACKAGE_NOT_OPEN`. A `BuyoutLead` (or `GCAdmin`) creates a `TradePackage` with a `trade_code` unique within the project (a collision is rejected with `ERR_VALIDATION`, HTTP 422; for example, `05-Steel`), a human `title`, the trade-level `estimated_budget_cents`, a `budgeted_contingency_cents` pool that later absorbs contingency-draw gap resolutions, an optional `spec_section` MasterFormat reference, an optional `bid_due_at` deadline, a `bonding_policy` of `REQUIRED`, `PER_TRADE_RISK`, or `WAIVED`, and the OCC guard field `expected_project_version` described in §2.7. A new package lands in `DRAFT` with `awarded_value_cents` at 0 and its `buyout_savings_cents` and `buyout_posture` already computed by the §3.9 formulas (savings initially equal to the package's `estimated_budget_cents`), records its parent linkage on the resource as `project_id`, and its creation increments the parent project's `version` by 1 — which is exactly why the OCC guard exists.

### 3.2. The Bid Window: Publish, Receive, Close

Publishing a package — a `BuyoutLead` action moving it `DRAFT → PUBLISHED` — is gated on two preconditions: the parent project must be `BUYOUT_OPEN` (else `ERR_PACKAGE_NOT_OPEN`), and the package's `bid_due_at` must be present and lie strictly after the project's `current_time_utc` (a missing deadline, or one not strictly in the future, yields `ERR_BID_WINDOW_INVALID`). A package whose deadline has already passed cannot be opened for bidding.

While a package is `PUBLISHED` or `UNDER_LEVELING`, a `BuyoutLead` or `Estimator` records a `Bid` with the `bidder_name`, a `contact_email`, the `base_bid_cents`, an optional list of `alternates` (each an `alternate_id` with its `price_delta_cents`), an optional list of `allowances` (each an `allowance_id` with its `amount_cents`), and the `bid_received_at` timestamp. The bid records its parent package on the resource as `trade_package_id`. The bid window is enforced inclusively: a bid whose `bid_received_at` is strictly after the package's `bid_due_at` is rejected with `ERR_BID_AFTER_DEADLINE`, while a bid arriving exactly at the deadline is accepted. A package created without a `bid_due_at` imposes no deadline check on bid receipt. Where several bid-creation checks fail at once, the package-state gate runs first, the duplicate-bidder check second, and the deadline check last. A package that is in neither `PUBLISHED` nor `UNDER_LEVELING` rejects bid creation with `ERR_TRADE_PACKAGE_NOT_ACCEPTING_BIDS`. The same bidder may not hold two live bids on one package: if another bid with the same `bidder_name` exists on the package in `PLACED` or `AWARDED` status, the submission is rejected with `ERR_DUPLICATE_BIDDER`. A successfully recorded bid lands in `PLACED` (the transitional `RECEIVED → PLACED` step fires on creation, and `RECEIVED` never persists on a created bid). At creation, before any negotiation round exists, the bid's `leveled_value_cents` simply equals its `base_bid_cents`.

Closing the bidding — a `BuyoutLead` action moving the package `PUBLISHED → UNDER_LEVELING` — requires that at least one bid on the package currently be `PLACED`; otherwise the call is rejected with `ERR_NO_BIDS_RECEIVED`. Withdrawal is available to a `BuyoutLead` or `OperationsManager` and moves a bid `PLACED → WITHDRAWN`; withdrawing a bid that is not `PLACED` fails with `ERR_INVALID_STATE_TRANSITION`. A `WITHDRAWN` bid remains queryable on the package's bid list but is ineligible for award, cannot source a new subcontract draft, and blocks schedule-of-values submission on any subcontract that was sourced from it (`ERR_BID_WITHDRAWN_SOV_BLOCKED`).

### 3.3. Leveling and Scope-Gap Analysis

Leveling is where the buyout team earns its fee. While a package is `PUBLISHED` or `UNDER_LEVELING`, a `BuyoutLead` or `OperationsManager` logs a `ScopeGap` with a `category` of `SCOPE`, `ALLOWANCE`, `ALTERNATE`, `INSURANCE_EXCLUSION`, or `LIFE_SAFETY`, a free-text `description`, and an optional `estimated_impact_cents` capturing the estimator's read of the cost exposure. Logging a gap against a package in any other state is rejected with `ERR_INVALID_STATE_TRANSITION`. A new gap lands `OPEN`.

A gap's `status` walks a small state machine over `OPEN`, `RESOLVED`, and `DEFERRED`, and the gap carries its parent linkage as `trade_package_id` on the resource itself. Gaps leave `OPEN` along three paths. Resolving a gap — available to a `BuyoutLead`, `OperationsManager`, or `VicePresident` — moves it `OPEN → RESOLVED` with a `resolution_kind` of `ALLOWANCE_WITH_QUALIFICATION`, `ALTERNATE_ACCEPT`, `CONTINGENCY_DRAW`, or `BID_CLARIFICATION`, plus an optional `note`. Two of these kinds carry extra obligations. `ALLOWANCE_WITH_QUALIFICATION` requires the payload's `waived_by_role` to be present and to name either `OperationsManager` or `VicePresident` — the waiver is a deliberate elevation, recorded on the gap. `CONTINGENCY_DRAW` requires `priced_amount_cents` to be present, and resolving it consumes that amount from the package's contingency pool: the package's consumed contingency increases by `priced_amount_cents`, which in turn reduces the headroom available to later award recommendations (§3.5). Deferring a gap — a `BuyoutLead` action moving it into the `DEFERRED` state (`OPEN → DEFERRED`) — is forbidden for `LIFE_SAFETY` gaps, which fail with `ERR_UNRESOLVED_LIFE_SAFETY_GAP`; a deferred gap can later be reopened (`DEFERRED → OPEN`) by a `BuyoutLead` when the team is ready to deal with it.

`LIFE_SAFETY` is the one category with hard blocking power. An `OPEN` gap of category `LIFE_SAFETY` on a package blocks three downstream operations — awarding a bid on that package, awarding a subcontract on that package, and issuing a subcontract on that package — each rejected with `ERR_UNRESOLVED_LIFE_SAFETY_GAP`. Gaps of the other four categories are advisory at award time; their bite comes earlier, at recommend-award, where outstanding allowance and alternate items on the source bid gate the negotiation-completeness check (§3.5).

### 3.4. Awarding the Bid and Drafting the Subcontract

Bid award is the leveling table's verdict. A `BuyoutLead` names the winning bid; the package must be `UNDER_LEVELING` (else `ERR_INVALID_STATE_TRANSITION`), and two checks then run in a fixed order. First, the eligible candidate set — bids on the package in `PLACED` or `AWARDED` status — must be non-empty; an empty set is rejected with `ERR_NO_AWARDABLE_BID` regardless of which bid was named. Only then is the named bid examined: if it is not `PLACED` (for example, already `WITHDRAWN`), the call fails with `ERR_BID_NOT_AWARDABLE`. On success the bid moves `PLACED → AWARDED`. For apparent-low-bidder reporting, the ranking over the candidate set orders by `leveled_value_cents` ascending, breaking ties by `bid_received_at` ascending and then by the bid's `created_at` ascending — but the award action itself never auto-picks; it awards exactly the bid the caller named. The life-safety block (§3.3) at bid award is evaluated after the candidate-set and target-bid checks, immediately before the bid flips to `AWARDED`.

Awarding a bid does not by itself create a subcontract. A `BuyoutLead` drafts a `Subcontract` on the package by naming the `subcontractor_name`, the `source_bid_id` of the leveled bid it stems from, the `flow_down_terms` clause text carried down from the prime contract, the `payment_terms` object (with `retainage_pct` and `pay_if_paid`), the ordered `change_authority_limits` tiers, and optionally an `insurance_requirements_snapshot` pinning the required limits. The retainage band is enforced at draft creation: a `payment_terms` whose `retainage_pct` falls outside the inclusive band from 0.05 to 0.10 is rejected with `ERR_RETAINAGE_OUT_OF_BAND` (HTTP 422). The package must be `UNDER_LEVELING` and show the competitive tension a real buyout requires — at least two bids on the package and at least one `WITHDRAWN` bid — otherwise the draft is rejected with `ERR_TRADE_PACKAGE_NOT_ACCEPTING_BIDS`. The source bid must be `PLACED` or `AWARDED` and must not already be referenced by a non-terminal subcontract; either failure yields `ERR_BID_NOT_AWARDABLE`. When several of these draft-creation checks fail at once, the package-state/competitive-tension gate runs first, then the source-bid checks (existence within the package, then `PLACED`/`AWARDED` status, then the no-non-terminal-reference rule), and the retainage band check runs last — a request failing both a source-bid check and the band check is rejected with `ERR_BID_NOT_AWARDABLE`, not `ERR_RETAINAGE_OUT_OF_BAND`.

A fresh subcontract draft lands in `DRAFT` with `contract_value_cents` at 0, `negotiation_round` at 0, `insurance_status` at `MISSING`, `cumulative_co_cents` at 0, `default_flag` false, and `bonding_requirement` at `PENDING_DECISION` — or directly at `NOT_REQUIRED` when the package's `bonding_policy` is `WAIVED`. The subcontract's `replaces_subcontract_id` and `replacement_subcontract_id` are both null at ordinary creation; they exist to carry the replacement chain described in §3.9.

### 3.5. The Negotiation Loop and Recommend-Award

Negotiation is a bounded cycle between `DRAFT` and `PENDING_AWARD`, and the bound is two: the system allows at most two `PENDING_AWARD → DRAFT` loops per subcontract. When a `BuyoutLead` or `OperationsManager` recommends award, the payload carries the negotiated `contract_value_cents` and, whenever the source bid carries allowances or alternates, the `allowance_dispositions` and `alternate_selections` arrays recording this round's dispositions. Each allowance disposition names an `allowance_id` and an `action` of `ACCEPT`, `REJECT`, or `REPRICE` — with `priced_cents` required exactly when the action is `REPRICE` — and each alternate selection names an `alternate_id` and a boolean `selected`. Recommend-award enforces four gates. First, the subcontract's `negotiation_round` must still be below the two-round cap; a third attempt is rejected with `ERR_NEGOTIATION_ROUND_EXCEEDED`. Second, `payment_terms.retainage_pct` must again sit within the inclusive 0.05-to-0.10 band (else `ERR_RETAINAGE_OUT_OF_BAND`). Third, negotiation completeness runs in the fixed order given in §2.10: missing disposition/selection arrays for a bid that has allowances or alternates yield `ERR_NEGOTIATION_TERMS_INCOMPLETE`, an individual allowance without a disposition yields `ERR_ALLOWANCE_UNRESOLVED`, and an individual alternate without a selection yields `ERR_ALTERNATE_UNRESOLVED`. Fourth, fiscal headroom: the package's projected total — its current `awarded_value_cents`, plus this subcontract's proposed `contract_value_cents`, plus the pinned values of every other subcontract sitting in `PENDING_AWARD` on the package — must not exceed the package's `estimated_budget_cents` plus its remaining contingency (the `budgeted_contingency_cents` less whatever has already been consumed by contingency draws); a breach is rejected with `ERR_CONTINGENCY_EXCEEDED`.

On a successful recommendation, three things happen: the subcontract moves `DRAFT → PENDING_AWARD`; its `contract_value_cents` is pinned at the negotiated figure; and a `NegotiationRound` is recorded against the subcontract with `round_index` equal to `negotiation_round + 1`, the submitted `proposed_value_cents`, the `allowance_dispositions` and `alternate_selections` arrays, an optional `note`, a `recorded_at` taken from the project logical clock, and the parent linkage carried on the round as `subcontract_id`. That round immediately re-levels the source bid: the bid's `leveled_value_cents` becomes its `base_bid_cents`, plus the `price_delta_cents` of every alternate marked selected in this round's selections, plus — for every allowance this round repriced — the difference between the disposition's `priced_cents` and the allowance's original `amount_cents`, minus the `amount_cents` of every allowance this round rejected. Allowances the round accepted contribute nothing, and any allowance or alternate left undispositioned contributes nothing. All of this is integer-cent arithmetic with no rounding.

When negotiation stalls, a `BuyoutLead` sends the subcontract back: `PENDING_AWARD → DRAFT`, with an optional `reason`. The loop increments `negotiation_round` by 1 and resets `contract_value_cents` to 0, ready for another attempt. A related compensating path exists one level down: if a bid was awarded but the linked subcontract is still in `PENDING_AWARD`, a `BuyoutLead` or `OperationsManager` may retract the bid award, moving the bid `AWARDED → PLACED` and dragging the linked subcontract back from `PENDING_AWARD` to `DRAFT` with its `contract_value_cents` reset to 0. If the linked subcontract has already left `PENDING_AWARD`, the retraction is rejected with `ERR_INVALID_STATE_TRANSITION`. If no subcontract has yet been drafted from the bid, the retraction simply returns the bid to `PLACED`; when several subcontracts reference the bid, the earliest-created one is the linked subcontract examined.

### 3.6. Formal Award and the Compliance Gates

Formal award belongs to the `OperationsManager`: it moves the subcontract `PENDING_AWARD → AWARDED`. Two gates guard it. The life-safety gate — no `OPEN` `LIFE_SAFETY` gap may exist on the trade package, else `ERR_UNRESOLVED_LIFE_SAFETY_GAP` — and the fiscal gate, which at this step runs in a specific order: first the headline check, where this subcontract's `contract_value_cents` alone exceeding the package's `estimated_budget_cents` plus remaining contingency is rejected with `ERR_AWARD_EXCEEDS_BUDGET`; then the projected-total check identical in shape to §3.5, whose breach yields `ERR_CONTINGENCY_EXCEEDED`. On award, if the package's `bonding_policy` is anything other than `WAIVED`, the subcontract's `bonding_requirement` becomes `PENDING_DECISION`, queueing the bonding determination of §3.7.

Issuance — the subcontract leaving `AWARDED → ISSUED` under a `BuyoutLead`'s hand — is the hard compliance gate, and it is also the transition that flips the package `UNDER_LEVELING → BUYOUT_IN_PROGRESS` if the package is still leveling. Three gates stand in front of it, evaluated in this order. First the insurance gate: the subcontract's `insurance_status` must be `COMPLIANT`, and each non-compliant posture maps to its own error — `MISSING` yields `ERR_INSURANCE_MISSING`, `NON_COMPLIANT` yields `ERR_INSURANCE_NON_COMPLIANT`, and `EXPIRED_CERT_ONLY` yields `ERR_INSURANCE_CERT_EXPIRED`. Then the bonding gate: unless the package policy is `WAIVED`, the `bonding_requirement` must have been resolved to one of `NOT_REQUIRED`, `SURETY_BOND`, or `SUBGUARD` with a recorded `BondDecision`; otherwise issuance fails with `ERR_BONDING_NOT_SATISFIED`. Finally the life-safety gate again (`ERR_UNRESOLVED_LIFE_SAFETY_GAP`).

Execution — recording the signed subcontract, `ISSUED → EXECUTED`, again by a `BuyoutLead` — repeats the insurance gate with the same error mapping, because time may have advanced between issuance and signature. Execution is the moment the package's numbers move: the package's `awarded_value_cents`, `buyout_savings_cents`, and `buyout_posture` are recomputed on the `PROVISIONAL` basis. If this execution leaves the package with exactly one `EXECUTED` subcontract and every sibling subcontract in `EXECUTED`, `REPLACED`, `DEFAULTED`, or `TERMINATED`, the package bubbles up `BUYOUT_IN_PROGRESS → AWARDED`; and if that was the last un-awarded package on the project, the project bubbles up `BUYOUT_OPEN → BUYOUT_COMPLETE`.

A draft subcontract that will never proceed can be terminated by an `OperationsManager` — `DRAFT → TERMINATED` with an optional `reason`. Operations against a subcontract that has reached `DEFAULTED`, `REPLACED`, or `TERMINATED` are rejected with `ERR_SUBCONTRACT_TERMINAL` — this protection covers the subcontract's own state-transition endpoints and the creation of child resources beneath it (insurance certificates, bond decisions, schedules of values, change orders), while review actions on already-created children (schedule reject, revise, and approve; change-order submit, approve, reject, and void) and all reads remain reachable — and any request for a transition the current state does not support is rejected with `ERR_INVALID_STATE_TRANSITION`.

### 3.7. Insurance Certificates and the Bonding Decision

Once a subcontract is `AWARDED`, `ISSUED`, or `EXECUTED`, a `BuyoutLead` registers an `InsuranceCertificate` against it — registration at any other subcontract state is rejected with `ERR_INVALID_STATE_TRANSITION`. The certificate carries a `certificate_number` unique per subcontract (a duplicate is rejected with `ERR_VALIDATION`, HTTP 422), the four liability limits `gl_occurrence_cents`, `gl_aggregate_cents`, `auto_cents`, and `umbrella_cents`, a `workers_comp` indicator of `STATUTORY` or `EXCESS_LIMIT`, three endorsement booleans — `ai_endorsed` for additional-insured, `wos_endorsed` for waiver-of-subrogation, `ptd_endorsed` for primary-and-noncontributory — an optional `pollution_cents` (0 when the policy carries no pollution coverage), the `expires_on` coverage-expiry date as a `YYYY-MM-DD` string, and an optional `evaluation_basis` that defaults to `FULL_ENDORSEMENTS` and selects which compliance variant the evaluation runs.

Evaluation compares the certificate against the subcontract's pinned `insurance_requirements_snapshot`, which holds the required `gl_occurrence_cents`, `gl_aggregate_cents`, `auto_cents`, `umbrella_cents`, `workers_comp`, and the required-endorsement flags `ai_required`, `wos_required`, `ptd_required`, `pollution_required`. Server defaults apply to any requirement omitted — or explicitly supplied as null — at draft time: each of the four required liability limits defaults to 0 cents, the required `workers_comp` defaults to `STATUTORY`, and each of the four required-endorsement flags defaults to false. A numeric failure is any of the four liability limits on the certificate falling below the corresponding required limit, or the certificate's `workers_comp` being anything other than `STATUTORY`. An endorsement failure is any required endorsement absent on the certificate — additional-insured required but not endorsed, waiver-of-subrogation required but not endorsed, primary-and-noncontributory required but not endorsed — or pollution coverage required while the certificate's `pollution_cents` is 0. An expiry failure occurs when the certificate's `expires_on` date is not strictly after the project logical clock's current date: coverage must outlive "today" on the project clock, and a certificate expiring exactly on the clock's date is already expired.

Under the default `FULL_ENDORSEMENTS` basis, the certificate's `compliance_verdict` is `COMPLIANT` only when there are no numeric failures, no endorsement failures, and no expiry failure; otherwise it is `NON_COMPLIANT`, and if the expiry check failed the certificate's own status moves `ISSUED → EXPIRED`. Under the `GAP_ANALYSIS` basis, endorsement failures — and only endorsement failures — can be excused: if the package carries a `RESOLVED` scope gap of category `INSURANCE_EXCLUSION` whose `waived_by_role` is `VicePresident`, the missing endorsements are waived and, when only excused endorsement failures remain, the verdict is `COMPLIANT_BY_GAP_ANALYSIS`. Numeric and expiry failures are never excused under either basis, and the `ISSUED → EXPIRED` status flip on an expiry failure applies under both bases.

The subcontract's `insurance_status` is then recomputed from its certificates in a fixed order: `COMPLIANT` if any certificate's verdict is `COMPLIANT` or `COMPLIANT_BY_GAP_ANALYSIS`; otherwise `EXPIRED_CERT_ONLY` if at least one certificate exists and every certificate has status `EXPIRED`; otherwise `NON_COMPLIANT` if any certificate evaluated `NON_COMPLIANT`; otherwise `MISSING` when no certificate is on file at all.

The bonding decision is the `OperationsManager`'s call, recorded once per subcontract — a second active `BondDecision` on the same subcontract is rejected with `ERR_BOND_DECISION_LOCKED` — and only while the subcontract is `AWARDED` (else `ERR_INVALID_STATE_TRANSITION`); the from-state gate is evaluated before the locked check. Recording the decision takes the subcontractor's declared `trade_history` of `CLEAN` or `CLAIMS` and an optional `decision_rationale`, computes the `trade_risk_score` (persisted on the `BondDecision` resource along with its parent `subcontract_id`), and derives both the `decision` and the quoted `premium_cents`. The score sums three components. The value component looks at the subcontract's `contract_value_cents`: below 5,000,000 cents it contributes 10 points; at or above 5,000,000 and at or below 10,000,000 cents it contributes 20; above 10,000,000 cents it contributes 35. The size component divides the subcontract's `contract_value_cents` by the package's `estimated_budget_cents`: a ratio at or below 0.25 contributes 0 points, and anything above contributes 25. If the package's `estimated_budget_cents` is not positive, the size component contributes 25 points whenever `contract_value_cents` is positive and 0 otherwise. The history component adds 10 points for a `CLEAN` record and 25 for `CLAIMS`. The sum is clamped into the 0-to-100 range. Under a package policy of `PER_TRADE_RISK`, the score selects the `decision`: 40 or below means `NOT_REQUIRED`, 41 through 60 means `SURETY_BOND`, and 61 or higher — through the clamped maximum of 100 — means `SUBGUARD`. Under a policy of `REQUIRED` the decision is `SURETY_BOND` regardless of score; under `WAIVED` it is `NOT_REQUIRED` regardless of score. The premium quote follows the decision: `NOT_REQUIRED` quotes 0 cents; `SURETY_BOND` quotes the `contract_value_cents` multiplied by 0.015; `SUBGUARD` quotes it multiplied by 0.010 — both rounded half-up to integer cents. Recording the decision sets the subcontract's `bonding_requirement` to the computed `decision`, stamps `decided_by_user_id` with the acting `OperationsManager`'s `X-User-ID`, and increments the subcontract's `version` by 1.

### 3.8. Schedule of Values and Change Orders Under Authority

With the subcontract issued or executed — submission at any other state is rejected with `ERR_INVALID_STATE_TRANSITION` — a `BuyoutLead` submits the `ScheduleOfValues` as an ordered list of `lines`, each line carrying a `wbs_code`, a `description`, and an integer `weight_numerator`. Submission is refused when the source bid has been `WITHDRAWN` (`ERR_BID_WITHDRAWN_SOV_BLOCKED`), and a subcontract carries at most one active (non-`REJECTED`) schedule at a time; a second active submission is rejected with `ERR_INVALID_STATE_TRANSITION`.

The allocation algorithm is pinned, and its order matters. Let the lines in submission order carry integer weights, and let W be their sum. The submission is rejected with `ERR_SOV_IMBALANCE` when W is zero or negative, or when any line's `weight_numerator` is less than 1. Otherwise the allocation proceeds by cumulative difference: for every line except the last, compute the cumulative weight through that line, multiply the subcontract's `contract_value_cents` by that cumulative weight divided by W, and round half-up to integer cents; each such line's `allocated_amount_cents` is the difference between its own cumulative rounded figure and the previous line's cumulative rounded figure (the first line's previous cumulative figure is 0). The final line absorbs the remainder: its `allocated_amount_cents` is the `contract_value_cents` minus the last computed cumulative rounded figure. Rounding each line's share independently and summing is expressly forbidden — that order drifts below the contract value on indivisible cent counts. When the allocation balances, the schedule transitions `DRAFT → BALANCED` on submission (or `REVISED → BALANCED` on a revise) and the subcontract's `sov_status` becomes `BALANCED`. Reads of a schedule return each line with its computed `allocated_amount_cents` alongside the submitted fields, plus the schedule's `revision_number`, starting at 0.

Review belongs to the `OperationsManager`. Rejecting a balanced schedule moves it `BALANCED → REJECTED` (with a mandatory `reason`) and sets the subcontract's `sov_status` to `REJECTED`. A `BuyoutLead` then revises it with a fresh `lines` list — validated and allocated exactly as at initial submission — moving it into the `REVISED` state (`REJECTED → REVISED`) and incrementing `revision_number` by 1; the revised submission re-runs the allocation, landing back in `BALANCED` with `sov_status` restored. Approval moves `BALANCED → APPROVED`, stamps `approved_at` from the project logical clock, and sets `sov_status` to `APPROVED`. Only an `APPROVED` schedule unlocks change-order work: creating a change order against a subcontract whose `sov_status` is anything else is rejected with `ERR_SOV_NOT_APPROVED`. The `EXECUTED`-state gate on the subcontract is evaluated before this schedule-of-values gate.

A change order is created — by a `BuyoutLead`, a `ProjectManager`, or a `SupplierDiversity` officer — against an `EXECUTED` subcontract (else `ERR_INVALID_STATE_TRANSITION`), carrying a `description`, a signed `amount_cents` (positive for additive changes), and an optional `initiating_role`. The server records the creator's `X-User-ID` as `created_by_user_id` for segregation of duties, and the order lands in `DRAFT`. A `BuyoutLead` submits it, moving the order into the `PENDING_APPROVAL` state (`DRAFT → PENDING_APPROVAL`). Approval is where the authority tiers bite, and the approver pool is `ProjectManager`, `ProjectExecutive`, and `OperationsManager`.

The subcontract's `change_authority_limits` is an ordered list of tiers, each tier naming a `max_value_cents`, a `max_cumulative_pct`, and the `roles` it extends to; a `max_value_cents` of -1 means unlimited per-order authority and a `max_cumulative_pct` of -1 means unlimited cumulative authority. At approval time the server first checks segregation of duties: if the approver's `X-User-ID` equals the order's `created_by_user_id`, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. Then the tiers the approver's role appears in are collected; if the approver's role appears in none, the approval is rejected with `ERR_CO_AUTHORITY_EXCEEDED`. Among the approver's tiers, the best tier is the one with the largest `max_value_cents`, where -1 sorts as unlimited; ties on `max_value_cents` break toward the tier appearing earliest in `change_authority_limits`. The per-order check follows: if the best tier's `max_value_cents` is not -1 and the order's `amount_cents` exceeds it, the rejection is `ERR_CO_AUTHORITY_EXCEEDED`. The cumulative check follows: if the best tier's `max_cumulative_pct` is not -1 and the ratio of the subcontract's `cumulative_co_cents` plus this order's `amount_cents` to its `contract_value_cents` exceeds the tier's `max_cumulative_pct` — compared in exact rational arithmetic, with a ratio exactly equal to the limit passing — the rejection is `ERR_CO_CUMULATIVE_LIMIT`. If the subcontract's `contract_value_cents` is not positive, a finite `max_cumulative_pct` is exceeded by any cumulative-plus-amount total strictly above zero. On approval, the order moves `PENDING_APPROVAL → APPROVED`, the approver's role is appended to `approval_roles_received`, and both the subcontract's `cumulative_co_cents` and its `contract_value_cents` increase by `amount_cents`. Rejection by any of the three approver roles moves the order `PENDING_APPROVAL → REJECTED`.

Voiding is the compensating action, reserved for the `OperationsManager`: an `APPROVED` order moves to `VOIDED` (`APPROVED → VOIDED`) with an optional `reason`, and the subcontract's `cumulative_co_cents` and `contract_value_cents` each decrease by the order's `amount_cents`, unwinding the approval's arithmetic.

### 3.9. Buyout Savings Tracking, Default, and Replacement

The package's buyout posture is a live read. On every package read, and at every subcontract execute, declare-default, and replace, the server recomputes three fields. Consumed contingency is the sum of `priced_amount_cents` across the package's `RESOLVED` gaps whose `resolution_kind` is `CONTINGENCY_DRAW`. Under the `PROVISIONAL` basis the `awarded_value_cents` is the sum of `contract_value_cents` over the package's `EXECUTED` subcontracts; under the `FINAL` basis it additionally counts subcontracts in `PENDING_AWARD`. The `buyout_savings_cents` is the package's `estimated_budget_cents` minus its `awarded_value_cents` minus the consumed contingency. The posture threshold converts the project's `buyout_target_savings_pct` into cents by multiplying it by the package's `estimated_budget_cents` and rounding half-up; the package's `buyout_posture` is then `FAVORABLE` when the savings meet or exceed that target, `NEUTRAL` when the savings are zero or better but below target, and `UNFAVORABLE` when the savings are negative. The project-level buyout summary rolls these per-package figures up into `total_estimated_cents`, `total_awarded_cents`, and `total_savings_cents` alongside the per-package array under the key `packages` — each entry the full serialized package with computed fields on the selected basis, ordered by `created_at` ascending — honoring the same `basis` selector.

Default is the `OperationsManager`'s instrument against a failing subcontractor, and it fires only from `EXECUTED`. Declaring default requires a `reason` and an `estimated_replacement_cost_cents`, and it is blocked outright when an `APPROVED` schedule of values exists on the subcontract — that path must go through replacement instead, and the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`. On declaration the subcontract moves `EXECUTED → DEFAULTED`, its `default_flag` becomes true, `default_recorded_at` is stamped from the project logical clock, and the estimated replacement cost is stored for exposure reporting. Because a `DEFAULTED` subcontract no longer counts as an awarded anchor, the package's awarded value, savings, and posture are recomputed; if no `EXECUTED` subcontract remains on the package, the package drops `AWARDED → BUYOUT_IN_PROGRESS`; and if the project had been `BUYOUT_COMPLETE`, it reopens (`BUYOUT_COMPLETE → BUYOUT_OPEN`). The declaration optionally carries a `replacement_subcontract_id`; when present, the referenced subcontract must exist, must be in `DRAFT`, and must live on the same package — otherwise the call is rejected with `ERR_REPLACEMENT_LINK_INVALID` — and its `replaces_subcontract_id` is set to the defaulted subcontract's id, stitching the replacement chain.

Replacement proper is the other exit from `EXECUTED`, again under the `OperationsManager`, and it requires the trade package to be in `UNDER_LEVELING` or `BUYOUT_IN_PROGRESS` (else `ERR_INVALID_STATE_TRANSITION`). It takes a `reason` and an `estimated_replacement_cost_cents`. On firing, the subcontract moves `EXECUTED → REPLACED` with `default_flag` true and `default_recorded_at` stamped; a fresh replacement subcontract is spawned on the same package in `DRAFT` with its `replaces_subcontract_id` pointing back, `negotiation_round` reset to 0, `insurance_status` at `MISSING`, and `contract_value_cents` at 0, with `cumulative_co_cents` reset to 0 and `sov_status` at `DRAFT`, copying `subcontractor_name`, `source_bid_id`, `flow_down_terms`, `insurance_requirements_snapshot`, `payment_terms`, and `change_authority_limits` from the replaced subcontract, and deriving `bonding_requirement` from the package's `bonding_policy` exactly as at ordinary draft creation; the replaced subcontract's `replacement_subcontract_id` is set to the new spawn and exposed on the response; and every insurance certificate on the replaced subcontract moves into the `SUPERSEDED` state (`ISSUED → SUPERSEDED`). The package recomputes exactly as in the default path, since a `REPLACED` subcontract no longer anchors awarded value. The replacement chain is queryable in both directions: from a subcontract to the list of replacements it spawned, and from a bid to the list of subcontracts it sourced.

Replacement exposure is reported per package. For every subcontract on the package whose `default_flag` is true, the analysis computes an exposure: the subcontract's estimated replacement cost minus its current `contract_value_cents`, floored at zero, plus — only when the subcontract's `bonding_requirement` is `SUBGUARD` — a subguard claim estimate equal to that same `contract_value_cents` multiplied by 0.20, rounded half-up to integer cents. Each defaulted or replaced subcontract contributes one item to the report's `items` array, ordered by the subcontract's `created_at` ascending, and each item carries `subcontract_id`, `bonding_requirement`, `contract_value_cents`, `estimated_replacement_cost_cents`, `subguard_claim_estimate_cents` (0 when no SUBGUARD claim applies), and `exposure_cents`.

## 4. Endpoint Definitions

Operations that create a new resource — a project, a trade package, a bid, a scope gap, a subcontract, an insurance certificate, a bond decision, a schedule of values, or a change order — return `201 Created`. Operations that modify an existing resource or trigger a state transition return `200 OK`. The table below is a navigation index only; request payloads, gating rules, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/projects` | Create a project | GCAdmin |
| GET | `/projects/{id}` | Get a project | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| POST | `/projects/{id}/open` | Open the project for buyout | GCAdmin |
| POST | `/projects/{id}/clock` | Advance the project logical clock | GCAdmin |
| GET | `/projects/{id}/buyout-summary` | Buyout savings roll-up across packages | GCAdmin, OperationsManager, VicePresident, BuyoutLead |
| POST | `/projects/{id}/trade-packages` | Create a trade package (OCC-guarded) | BuyoutLead, GCAdmin |
| GET | `/trade-packages/{id}` | Get a trade package with computed buyout fields | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| GET | `/projects/{id}/trade-packages` | List a project's trade packages | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| POST | `/trade-packages/{id}/publish` | Publish the package for bidding | BuyoutLead |
| POST | `/trade-packages/{id}/close-bidding` | Close bidding and enter leveling | BuyoutLead |
| GET | `/trade-packages/{id}/replacement-analysis` | Replacement cost exposure for the package | GCAdmin, OperationsManager, VicePresident, BuyoutLead |
| POST | `/trade-packages/{id}/bids` | Record a bid | BuyoutLead, Estimator |
| GET | `/trade-packages/{id}/bids` | List bids on a package | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| GET | `/bids/{id}` | Get a bid | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| POST | `/trade-packages/{id}/bids/{id}/withdraw` | Withdraw a bid | BuyoutLead, OperationsManager |
| POST | `/trade-packages/{id}/bids/{id}/award` | Award the package to a bid | BuyoutLead |
| POST | `/bids/{id}/un-award` | Retract a bid award before subcontract award | BuyoutLead, OperationsManager |
| POST | `/trade-packages/{id}/gaps` | Log a scope gap | BuyoutLead, OperationsManager |
| GET | `/trade-packages/{id}/gaps` | List gaps on a package | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| GET | `/gaps/{id}` | Get a scope gap | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| POST | `/gaps/{id}/resolve` | Resolve a gap with a priced disposition | BuyoutLead, OperationsManager, VicePresident |
| POST | `/gaps/{id}/defer` | Defer a gap | BuyoutLead |
| POST | `/gaps/{id}/reopen` | Reopen a deferred gap | BuyoutLead |
| POST | `/trade-packages/{id}/subcontracts` | Create a subcontract draft from a leveled bid | BuyoutLead |
| GET | `/subcontracts/{id}` | Get a subcontract | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| GET | `/trade-packages/{id}/subcontracts` | List subcontracts on a package | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| POST | `/subcontracts/{id}/recommend-award` | Recommend award with negotiated value | BuyoutLead, OperationsManager |
| POST | `/subcontracts/{id}/renegotiate` | Send a pending award back to draft | BuyoutLead |
| POST | `/subcontracts/{id}/award` | Formally award the subcontract | OperationsManager |
| POST | `/subcontracts/{id}/issue` | Issue the subcontract for signature | BuyoutLead |
| POST | `/subcontracts/{id}/execute` | Record the executed subcontract | BuyoutLead |
| POST | `/subcontracts/{id}/declare-default` | Declare subcontractor default | OperationsManager |
| POST | `/subcontracts/{id}/replace` | Replace an executed subcontract | OperationsManager |
| POST | `/subcontracts/{id}/terminate` | Terminate a draft subcontract | OperationsManager |
| GET | `/subcontracts/{id}/negotiation-rounds` | List negotiation rounds | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident |
| GET | `/subcontracts/{id}/schedule-of-values` | List schedules of values | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| GET | `/subcontracts/{id}/replacements` | List replacement subcontracts spawned from this one | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| GET | `/bids/{id}/subcontracts` | List subcontracts sourced from this bid | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| POST | `/subcontracts/{id}/insurance-certificates` | Register and evaluate a certificate of insurance | BuyoutLead |
| GET | `/subcontracts/{id}/insurance-certificates` | List certificates for a subcontract | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident |
| POST | `/subcontracts/{id}/bond-decision` | Record the bonding decision | OperationsManager |
| GET | `/subcontracts/{id}/bond-decisions` | List bond decisions | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident |
| POST | `/subcontracts/{id}/schedule-of-values` | Submit a schedule of values | BuyoutLead |
| GET | `/schedule-of-values/{id}` | Get a schedule of values with computed line allocations | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, Estimator, SupplierDiversity |
| POST | `/schedule-of-values/{id}/reject` | Reject a balanced schedule | OperationsManager |
| POST | `/schedule-of-values/{id}/revise` | Revise a rejected schedule | BuyoutLead |
| POST | `/schedule-of-values/{id}/approve` | Approve a balanced schedule | OperationsManager |
| POST | `/subcontracts/{id}/change-orders` | Create a change order | BuyoutLead, ProjectManager, SupplierDiversity |
| GET | `/subcontracts/{id}/change-orders` | List change orders | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, SupplierDiversity |
| GET | `/change-orders/{id}` | Get a change order | GCAdmin, BuyoutLead, OperationsManager, ProjectExecutive, ProjectManager, VicePresident, SupplierDiversity |
| POST | `/change-orders/{id}/submit` | Submit a change order for approval | BuyoutLead |
| POST | `/change-orders/{id}/approve` | Approve a change order under authority tiers | ProjectManager, ProjectExecutive, OperationsManager |
| POST | `/change-orders/{id}/reject` | Reject a pending change order | ProjectManager, ProjectExecutive, OperationsManager |
| POST | `/change-orders/{id}/void` | Void an approved change order | OperationsManager |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified in §2 and §3 where each guard lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_PACKAGE_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_PACKAGE_NOT_OPEN` | 409 |
| `ERR_BID_WINDOW_INVALID` | 409 |
| `ERR_BID_AFTER_DEADLINE` | 409 |
| `ERR_NO_BIDS_RECEIVED` | 409 |
| `ERR_DUPLICATE_BIDDER` | 409 |
| `ERR_TRADE_PACKAGE_NOT_ACCEPTING_BIDS` | 409 |
| `ERR_BID_NOT_AWARDABLE` | 409 |
| `ERR_NO_AWARDABLE_BID` | 409 |
| `ERR_UNRESOLVED_LIFE_SAFETY_GAP` | 409 |
| `ERR_ALLOWANCE_UNRESOLVED` | 409 |
| `ERR_ALTERNATE_UNRESOLVED` | 409 |
| `ERR_NEGOTIATION_TERMS_INCOMPLETE` | 409 |
| `ERR_NEGOTIATION_ROUND_EXCEEDED` | 409 |
| `ERR_CONTINGENCY_EXCEEDED` | 409 |
| `ERR_AWARD_EXCEEDS_BUDGET` | 409 |
| `ERR_INSURANCE_MISSING` | 409 |
| `ERR_INSURANCE_NON_COMPLIANT` | 409 |
| `ERR_INSURANCE_CERT_EXPIRED` | 409 |
| `ERR_BONDING_NOT_SATISFIED` | 409 |
| `ERR_BOND_DECISION_LOCKED` | 409 |
| `ERR_SOV_IMBALANCE` | 409 |
| `ERR_SOV_NOT_APPROVED` | 409 |
| `ERR_BID_WITHDRAWN_SOV_BLOCKED` | 409 |
| `ERR_CO_AUTHORITY_EXCEEDED` | 409 |
| `ERR_CO_CUMULATIVE_LIMIT` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_SUBCONTRACT_TERMINAL` | 409 |
| `ERR_REPLACEMENT_LINK_INVALID` | 409 |
| `ERR_RETAINAGE_OUT_OF_BAND` | 422 |
| `ERR_VALIDATION` | 422 |
| `ERR_INTERNAL` | 500 |
