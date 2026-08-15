# Liquidity Stress Testing API — Product Requirements Document

## 1. Introduction

A bank's treasury and liquidity desk lives or dies by forward visibility: how much cash leaves under stress, what the high-quality liquid asset buffer is genuinely worth after haircuts, how concentrated wholesale funding has become, and whether early warning indicators are drifting toward territory that obliges the committee to act. Regulators and boards expect this visibility to be demonstrable — projections reproducible, contingency funding plans tested against real capacity, and breaches of board limits tracked from detection to remediation with segregation of duties enforced at every step.

This document specifies the Liquidity Stress Testing API, the system of record for that workflow. It covers stress scenario governance and cash-flow projection under two model variants; liquid asset inventory with pinned haircuts; borrowing lines, collateral pledges, and draws; funding concentration measurement; early warning indicators whose readings drive a four-level liquidity posture; board limits and the breach lifecycle they trigger; contingency playbooks that move from drafting through capacity testing, approval, posture-gated activation, execution, and closure; and intraday liquidity monitoring. Time inside the system is a logical clock rather than wall-clock time, so that settlement lags, reading cadence, and evaluation histories remain deterministic and auditable. Five operator roles — from desk analyst to committee — share the workspace under strict segregation of duties.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the operation — including the state-specific role rules called out in §3, such as escalated-breach remediation and posture de-escalation being reserved for the committee — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles exist:

- `TreasuryAnalyst` — the liquidity desk analyst: projection runs, funding data, EWI readings, and playbook drafting.
- `RiskOfficer` — the liquidity risk officer: scenario governance, EWI and board-limit configuration, capacity tests, playbook approvals, breach acknowledgment, line suspension, and posture evaluation along the escalation path.
- `TreasuryOps` — treasury operations: HQLA inventory, borrowing lines, collateral pledges, draws and repayments, playbook action execution, and intraday snapshots.
- `LiquidityCommittee` — the ALCO/committee authority: playbook activation, stand-down and completion, breach escalation, escalated remediation, and posture de-escalation.
- `PlatformAdmin` — the test-driving operator for the logical clock.

For each of these five roles — `TreasuryAnalyst`, `RiskOfficer`, `TreasuryOps`, `LiquidityCommittee`, and `PlatformAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires an audit anchor — as `created_by_user_id` and `approved_by_user_id` on a playbook, as `acknowledged_by_user_id` and `remediated_by_user_id` on a breach, and as `evaluated_by_user_id` on a posture snapshot — but it never compares `X-User-ID` to any entity's `id`. The segregation-of-duties checks in §3.7 and §3.9 are identity comparisons between these recorded fields and the caller's `X-User-ID`, not resource-ownership checks.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. The default sort order is `created_at` ascending. The posture snapshot history is the single exception: it is ordered by `snapshot_seq` ascending, so that evaluations replay in exactly the order they were appended. The resource filters described throughout §3 combine freely with pagination.

### 2.4. The Logical Clock

All timestamps that business logic reads — finalization instants, settlement due times, reading cadence checks, activation and execution stamps — come from a logical clock, never from wall-clock time. Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time afterward. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock mutates no entity; it only changes what time-dependent rules observe.

### 2.5. Resource Identity, Timestamps, and Versioning

Every persisted resource has an `id` — a server-minted UUID used for identity only, carrying no type prefix — and a `created_at` timestamp. Resources other than the three append-only event types also carry `updated_at` and an integer `version`. Server-stamped timestamps — every field the system itself writes from the logical clock, such as `created_at`, `updated_at`, `finalized_at`, `tested_at`, `activated_at`, and `executed_at` — are ISO 8601 UTC with three fractional digits. Caller-supplied datetime fields carried on a resource — the `observed_at` of a metric reading, the `snapshot_at` of an intraday snapshot, and the metric's derived `last_reading_at`, which copies the latest reading's `observed_at` — are echoed verbatim: the exact string from the request payload is stored and read back unchanged, without reformatting. On every mutation of a resource, whether a field edit or a state transition, `updated_at` refreshes and `version` increments by one.

The append-only event types — metric readings, posture snapshots, and intraday snapshots — carry only `id` and `created_at`. Both `updated_at` and `version` are absent from them, because an event, once recorded, is never modified.

### 2.6. Monetary Amounts, Percentages, and Rounding

Monetary amounts are integer cents carried in fields named with the `_cents` suffix; fractional cents are never retained. Percentages appear in two unit conventions: fields suffixed `_pct` carry whole percentage points from 0 to 100, while fields suffixed `_bps` carry basis points, where ten thousand basis points equal one hundred percent. An early warning metric's `unit` declares whether its readings and thresholds are basis points (`PCT_BPS`), days (`DAYS`), or cents (`CENTS`).

Every division in every calculation rounds down to the nearest integer at the point the division occurs. Where a calculation aggregates per-item values, the floor is applied per item before summing — the rounding order is pinned, because flooring items individually and then summing produces a different total than summing first and flooring once. No calculation rounds half-up or uses banker's rounding, and no reported figure is an estimate.

### 2.7. Optimistic Concurrency Control

Two write operations guard against stale views of a parent resource through a required expected-version field, and both reject mismatches with `ERR_STALE_VERSION` (HTTP 412):

- A `PATCH /liquidity/contingency-playbooks/{id}` request must carry `expected_playbook_version` equal to the playbook's current `version`. If another writer has advanced the playbook's version since the client last read it — for example through a successful edit of the same draft — the update is rejected, so the client cannot overwrite changes it has not observed.
- A `POST /liquidity/stress-scenarios/{id}/projection-runs` request must carry `expected_scenario_version` equal to the scenario's current `version`. Run creation legitimately discards any existing draft run for the same scenario and model variant and advances the scenario's version through `run_count`, so a writer holding a stale scenario version would otherwise silently discard a draft it never observed; the mismatch is rejected instead.

Endpoints not named here do not accept any expected-version field.

### 2.8. Reference Resolution and Nested Resources

Endpoints nested under a parent path validate path identifiers strictly from left to right, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). References supplied in request bodies — `scenario_id`, `asset_id`, `line_id`, `prerequisite_action_id`, and `ewi_metric_id` — must likewise resolve to existing records, on pain of the same 404. One reference is deliberately not an enforced foreign key: a breach's `source_id` is a polymorphic pointer to whichever reading, projection run, or intraday snapshot detected it, and it is null for breaches raised by funding evaluations.

### 2.9. Validation Order

Validation runs in a fixed order so that a request failing several checks always surfaces the earliest failure. First, authentication of the two identity headers (`ERR_UNAUTHENTICATED`). Second, role authorization for the endpoint, including state-specific role rules (`ERR_FORBIDDEN`). Third, existence of every referenced resource — path identifiers left to right, then body-supplied references (`ERR_NOT_FOUND`). Fourth, request shape: required fields present, types valid, enum membership respected, numeric ranges honored, and cross-field rules such as threshold coherence (`ERR_INVALID_REQUEST`, `ERR_THRESHOLD_CONFIG_INVALID`). Fifth, optimistic-concurrency version matching where the endpoint takes an expected-version field (`ERR_STALE_VERSION`). Sixth, state-machine admissibility of the requested transition on the addressed resource (`ERR_INVALID_STATE`). Seventh, business-safety gates: segregation of duties (`ERR_SOD_VIOLATION`), posture sufficiency (`ERR_POSTURE_INSUFFICIENT`), line availability (`ERR_LINE_SUSPENDED`), asset availability (`ERR_ASSET_NOT_PLEDGEABLE`, `ERR_ASSET_NOT_AVAILABLE`), scenario status (`ERR_SCENARIO_RETIRED`), and de-escalation conditions (`ERR_DEESCALATION_BLOCKED`). Eighth, temporal rules (`ERR_SETTLEMENT_NOT_DUE`, `ERR_READING_TOO_FREQUENT`, `ERR_SNAPSHOT_OUT_OF_ORDER`). Ninth, business constraints — the uniqueness and mutual-exclusion rules (`ERR_DUPLICATE_ACTIVE_SCENARIO`, `ERR_LAST_BASELINE_SCENARIO`, `ERR_SCENARIO_IN_USE`, `ERR_PLAYBOOK_ALREADY_ACTIVE`, `ERR_PREREQUISITE_ACTION_INCOMPLETE`, `ERR_ACTIONS_NOT_ALL_TERMINAL`, `ERR_LIMIT_STILL_BREACHED`). Tenth and last, fiscal bounds (`ERR_INSUFFICIENT_BORROWING_POWER`, `ERR_REPAY_EXCEEDS_DRAWN`).

### 2.10. Atomic Side Effects and Cascading State

Every request's side effects apply atomically within that request: either the entire cascade lands or the request fails, with nothing left partially applied. Several operations deliberately propagate beyond their primary target. Releasing collateral recomputes the borrowing line's position and can suspend the line, which in turn blocks pending drawdown actions (§3.4). A reading that turns a metric red appends a posture snapshot, and a snapshot entering severe or crisis territory escalates every open breach (§3.6 and §3.7). Playbook activation, stand-down, and revision each rewrite the states of the playbook's actions as part of the same request (§3.9). Implementations must not defer any of these effects to background processing.

## 3. Business Logic & Workflows

### 3.1. Stress Scenarios and Their Governance

A `RiskOfficer` defines a stress scenario by supplying a `name`, a `tier` of `BASELINE`, `MODERATE`, or `SEVERE`, and the behavioral parameters the projection models consume: `deposit_runoff_pct`, the percentage of retail deposit balances that runs off linearly across the horizon; `wholesale_renewal_pct`, the percentage of maturing wholesale funding that rolls over under the behavioral variant; `level2_addon_bps`, a stress haircut add-on in basis points applied only to `LEVEL_2A` and `LEVEL_2B` assets; and `horizon_days`, the projection horizon, from 1 to 365 days. Both percentage inputs range from 0 to 100, and the add-on ranges from 0 to 10000. A new scenario starts `ACTIVE` with its `run_count` at zero.

The desk keeps at most one `ACTIVE` scenario per tier: creating a scenario for a tier that already has an active one is rejected with `ERR_DUPLICATE_ACTIVE_SCENARIO`. The catalogue can be listed with `tier` and `status` filters, or fetched scenario by scenario.

Retirement moves a scenario from `ACTIVE` to `RETIRED` and is a `RiskOfficer` action with two guards. A `BASELINE` scenario cannot be retired while it is the last active baseline — at least one other `ACTIVE` scenario of tier `BASELINE` must exist, or the request fails with `ERR_LAST_BASELINE_SCENARIO`. Independently, a scenario that still has a projection run in `DRAFT` status cannot be retired at all (`ERR_SCENARIO_IN_USE`); finalized history does not block retirement. Once retired, a scenario refuses further modeling use: creating a new projection run against it, or finalizing an existing draft run of it, is rejected with `ERR_SCENARIO_RETIRED`. Retirement is terminal — a retired scenario never returns to `ACTIVE`.

### 3.2. Projection Runs and Cash-Flow Modeling

A `TreasuryAnalyst` opens a projection run under a scenario by naming the `model_variant` — `CONTRACTUAL` or `BEHAVIORAL` — and the `as_of_date` (in YYYY-MM-DD form) the projection is anchored to, and by presenting `expected_scenario_version` as specified in §2.7. The scenario must be `ACTIVE`, with `ERR_SCENARIO_RETIRED` greeting any attempt against a retired one. The run copies `horizon_days` from its scenario, starts in `DRAFT`, and carries zeros in all computed totals with `finalized_at` unset. Creation is superseding: any existing `DRAFT` run for the same scenario and the same variant becomes `DISCARDED` as part of the same request, so at most one draft ever exists per scenario-and-variant pair. Creation also advances the scenario's `run_count` by one and bumps the scenario's `version` by one. Runs are listed through their parent scenario and fetched individually.

Finalization — a `TreasuryAnalyst` action moving a run `DRAFT` → `FINALIZED` — is where the projection is actually computed, and it likewise requires the scenario to be `ACTIVE` (`ERR_SCENARIO_RETIRED` otherwise). The engine walks the days of the horizon, day 1 through the copied horizon length, and models outflows only: `total_inflows_cents` is always zero. Rounding is applied per funding source per day, each contribution floored to whole cents before any summing.

Under the `CONTRACTUAL` variant, each funding source pays out its full `balance_cents` on the day it contractually matures: the outflow on a given day is the sum of balances over every source whose `matures_in_days` equals that day number.

Under the `BEHAVIORAL` variant the picture diverges on identical inputs. Wholesale channels — `WHOLESALE_UNSECURED`, `WHOLESALE_SECURED`, and `BROKERED` — renew partially: each such source maturing on a given day contributes its balance multiplied by the non-renewing share (one hundred minus the scenario's `wholesale_renewal_pct`), divided by one hundred, and rounded down to whole cents. Retail demand deposits never formally mature, so `RETAIL_DEPOSIT` sources instead run off linearly: each retail source, whatever its `matures_in_days` — including sources with no maturity at all — contributes on every day of the horizon an amount equal to its balance times the scenario's `deposit_runoff_pct`, divided by one hundred, then divided by the number of days in the horizon, rounded down to whole cents. Sources maturing beyond the horizon, and non-maturity sources outside the retail runoff, contribute nothing to the outflows.

Each day's cumulative net position is the negation of all outflows through that day, inflows being zero. Finalization also captures `hqla_available_cents` — the STRESS-variant adjusted value, under this run's scenario, of every asset currently `UNENCUMBERED` (§3.3) — and derives `survival_days`: the earliest day on which the cumulative net position plus `hqla_available_cents` falls strictly below zero, or `horizon_days` itself when the buffer never runs out. The run's totals land as `total_outflows_cents` equal to the sum of all daily outflows, `total_inflows_cents` equal to zero, and `net_cumulative_gap_cents` equal to `total_inflows_cents` minus `total_outflows_cents`, while `finalized_at` records the logical clock at finalize.

Two further effects ride on finalization. Every previously `FINALIZED` run for the same scenario and the same variant becomes `SUPERSEDED`, keeping at most one current finalized run per pair. And breach detection runs immediately against every board limit whose subject is `SURVIVAL_DAYS`, attributing any new breach to `source_type` `PROJECTION_FINALIZE` with `source_id` pointing at this run.

### 3.3. Liquid Assets and HQLA Valuation

`TreasuryOps` registers each liquid asset with its `asset_class` — `LEVEL_1`, `LEVEL_2A`, or `LEVEL_2B` — an external `reference` identifier, and a strictly positive `market_value_cents`. The class determines the `haircut_bps` the system derives: zero for `LEVEL_1`, 1500 basis points (fifteen percent) for `LEVEL_2A`, and 2500 basis points (twenty-five percent) for `LEVEL_2B`. Assets arrive `UNENCUMBERED`, and the inventory list supports `asset_class` and `encumbrance_status` filters.

Valuation follows one pinned rule. Per asset, the adjusted value is the market value multiplied by the difference between ten thousand and the applicable total haircut in basis points, divided by ten thousand, and rounded down to whole cents — floored per asset before any summing begins. Two variants exist. The BASELINE variant applies the class haircut alone, with no add-on. The STRESS variant adds the referencing scenario's `level2_addon_bps` to the haircut of `LEVEL_2A` and `LEVEL_2B` assets only, so the same inventory values strictly lower whenever a Level 2 asset exists and the add-on is positive. A computed read returns both totals — `baseline_total_cents` and `stress_total_cents` — along with the `asset_count`, evaluated over exactly the `UNENCUMBERED` inventory under the scenario passed as `scenario_id`.

Market repricing by `TreasuryOps` replaces an asset's `market_value_cents`, bumps the asset's `version` by one, and feeds all future haircut computations. One figure is immune to repricing: a pledge's `pledged_value_cents` is pinned once, at pledge creation, to the BASELINE-variant adjusted value of the asset — that is, with the add-on at zero — and is never re-priced afterward, whatever the market does.

An asset's `encumbrance_status` cycles `UNENCUMBERED` → `PLEDGED` when a pledge referencing it is created, and returns `PLEDGED` → `UNENCUMBERED` when that pledge is released. Execution of an asset-sale playbook action moves an unencumbered asset to `SOLD`, which is terminal: a sold asset leaves the HQLA inventory and is excluded from every adjusted-value input set.

### 3.4. Borrowing Lines, Collateral Pledges, and Draws

`TreasuryOps` establishes a borrowing line with a `provider_name`, a `line_type` of `FED_DISCOUNT_WINDOW`, `FHLB`, or `REPO`, a strictly positive `total_capacity_cents`, and an `advance_rate_bps` between 1 and 10000. A new line starts `ACTIVE` with `pledged_value_cents`, `drawn_cents`, and `borrowing_power_cents` all at zero.

Borrowing power is always derived in the same pinned order, which resolves the apparently circular dependency between pledges and power. First, sum the `pledged_value_cents` of the line's `ACTIVE` pledges into the line's pledged total. Second, compute the collateral cap as that pledged total times the line's `advance_rate_bps`, divided by ten thousand and rounded down to whole cents — the floor happens at this step. Third, set `borrowing_power_cents` to the smaller of `total_capacity_cents` and the collateral cap, minus `drawn_cents`, but never below zero. The derived figure is recomputed on every pledge, release, draw, repayment, drawdown execution, and drawdown failure, and is what reads of the line return.

Pledging is a `TreasuryOps` act supplying `asset_id` and `line_id`. The asset must be `UNENCUMBERED` (`ERR_ASSET_NOT_PLEDGEABLE` otherwise) and the line must be `ACTIVE` (`ERR_LINE_SUSPENDED` otherwise). A successful pledge pins its `pledged_value_cents` per §3.3, flips the asset `UNENCUMBERED` → `PLEDGED`, starts the pledge itself `ACTIVE`, and triggers a line recompute. Release flips the pledge `ACTIVE` → `RELEASED`, returns the referenced asset to `UNENCUMBERED`, and recomputes the line once more — and this is where the cascade bites: if the recompute leaves `drawn_cents` above the smaller of total capacity and collateral cap while the line is still `ACTIVE`, the line suspends itself, and every `PENDING` or `READY` drawdown action referencing it becomes `BLOCKED` in the same request.

A `RiskOfficer` can also suspend an `ACTIVE` line manually, producing the same blocking cascade, and can later reinstate a `SUSPENDED` line — but only while the drawn balance sits within the smaller of total capacity and collateral cap, failing which the request is rejected with `ERR_INVALID_STATE`. Reinstatement wakes the line's `BLOCKED` actions: each returns to `READY` when its playbook is `ACTIVATED` or `EXECUTING`, and to `PENDING` otherwise.

Draws and repayments are `TreasuryOps` operations carrying `amount_cents`. A draw requires the line `ACTIVE` (`ERR_LINE_SUSPENDED`) and a positive amount not exceeding the current `borrowing_power_cents` — drawing exactly the full power is permitted — with violations rejected as `ERR_INSUFFICIENT_BORROWING_POWER`; the amount is added to `drawn_cents` and power recomputes. A repayment must be positive and no larger than the current `drawn_cents` (`ERR_REPAY_EXCEEDS_DRAWN`); it reduces the drawn balance and likewise recomputes power. Pledges are listable with `asset_id`, `line_id`, and `status` filters, and both pledges and lines are fetchable individually.

### 3.5. Funding Sources and Concentration Measurement

`TreasuryAnalyst` records each funding source with a `counterparty_name`, a `channel` of `RETAIL_DEPOSIT`, `WHOLESALE_UNSECURED`, `WHOLESALE_SECURED`, or `BROKERED`, a strictly positive `balance_cents`, and optionally `matures_in_days` — the days from a projection's as-of date until contractual maturity, zero or greater, or null for a non-maturity demand deposit. Funding sources carry no lifecycle of their own: every recorded source participates in every evaluation and every projection.

A `RiskOfficer` triggers a funding evaluation, which aggregates all sources point-in-time, without any window and without sensitivity to record order. The response reports `total_funding_cents`, the sum of every balance on record, and `wholesale_reliance_bps`: the combined balance of the three wholesale channels times ten thousand, divided by total funding, and rounded down to whole basis points — defined as zero when no funding exists at all. Counterparty concentration groups balances by `counterparty_name`; `top_counterparty_bps` is the largest such share, each counterparty's share floored the same way, and `top_counterparty_name` names the counterparty holding it, with ties broken by ascending lexicographic order of the name.

Detection rides along: the evaluation immediately runs breach detection against every board limit on `WHOLESALE_RELIANCE_PCT` and `TOP_COUNTERPARTY_PCT`, and the response's `breaches_created` counts how many new breaches were raised. Breaches from this pipeline carry `source_type` `FUNDING_EVALUATION` and a null `source_id`.

### 3.6. Early Warning Indicators and Liquidity Posture

A `RiskOfficer` configures each indicator with a `code` that must be unique across all configured metrics, a display `name`, the `unit` its values and thresholds use, a `direction` of `ABOVE_BREACHES` or `BELOW_BREACHES`, the `amber_threshold` and `red_threshold` band boundaries, and optionally `min_reading_interval_hours`, which defaults to zero and means no cadence rule. Threshold coherence depends on direction: `ABOVE_BREACHES` requires the red boundary strictly above the amber one, while `BELOW_BREACHES` requires red strictly below amber; an inconsistent pair is rejected with `ERR_THRESHOLD_CONFIG_INVALID` (HTTP 422). A new metric starts with `current_band` at `GREEN` and `last_reading_at` empty.

`TreasuryAnalyst` posts readings under a metric, each carrying `observed_at` and `value` and recording the `metric_id` of the metric it was posted under. Each reading computes and stores its own `band` with strict boundaries: for an `ABOVE_BREACHES` metric, a value strictly above `red_threshold` is `RED`, a value strictly above `amber_threshold` without reaching red is `AMBER`, and anything else is `GREEN`; for a `BELOW_BREACHES` metric the same logic mirrors below the thresholds — strictly below red is `RED`, strictly below amber without reaching red is `AMBER`, otherwise `GREEN`. A value landing exactly on a boundary never crosses into the worse band. The metric's `current_band` and `last_reading_at` then track the latest reading by `observed_at`, with ties between readings sharing an `observed_at` broken in favor of the one created later. Cadence is enforced whenever a previous reading exists: the new `observed_at` must be at least `last_reading_at` plus `min_reading_interval_hours` — exactly on that boundary is allowed — and anything earlier is rejected with `ERR_READING_TOO_FREQUENT`. A posting also runs breach detection against every `EWI_METRIC` board limit wired to this metric through `ewi_metric_id`, stamping `source_type` `METRIC_READING` with the new reading as `source_id`. Readings remain listable under their metric.

Whenever a posted reading makes a metric's `current_band` become `RED`, the system immediately evaluates posture and appends a snapshot with trigger `READING_AUTO`. Posture is a four-ordinal scale — `NORMAL` (ordinal 0) below `HEIGHTENED` (1) below `SEVERE` (2) below `CRISIS` (3) — computed from three counts taken at evaluation time: `red_count`, the number of metrics whose `current_band` is `RED`; `amber_count`, those at `AMBER`; and `open_breach_count`, the number of breaches standing `OPEN`. The raw level is `CRISIS` when at least two metrics are red; otherwise `SEVERE` when at least one is red; otherwise `HEIGHTENED` when at least three metrics are amber or at least two breaches are open; otherwise `NORMAL`. Automatic evaluations only escalate: the new level is the higher of the current posture and the raw level, so the automatic path never de-escalates.

Manual evaluations — available to `RiskOfficer` and `LiquidityCommittee` — move straight to the raw level whenever it equals or exceeds the current one. De-escalation below the current level is committee-only, so any other role attempting it is rejected with `ERR_FORBIDDEN`; it additionally requires `red_count` and `open_breach_count` both at zero (`ERR_DEESCALATION_BLOCKED` otherwise); and it moves exactly one ordinal step downward per evaluation, a hysteresis rule that prevents any single evaluation from dropping two levels at once.

Every evaluation, automatic or manual, appends a `PostureSnapshot` recording a monotone `snapshot_seq`, the new `level`, the `prior_level` (`NORMAL` when no prior snapshot exists), the three counts, the `trigger` (`READING_AUTO` or `MANUAL_EVALUATION`), and `evaluated_by_user_id` — the caller's `X-User-ID` for manual evaluations, the system origin for automatic ones. The current posture is the level of the snapshot with the highest `snapshot_seq`, and `NORMAL` before any snapshot exists. Entering `SEVERE` or `CRISIS` from a strictly lower level escalates every `OPEN` breach to `ESCALATED` automatically, leaving its `acknowledged_by_user_id` null. A dashboard read summarizes the moment — `posture_level`, `red_count`, `amber_count`, and the `metric_count` of configured indicators — while the snapshot history lists in `snapshot_seq` order.

### 3.7. Board Limits, Breach Detection, and Intraday Monitoring

A `RiskOfficer` defines board limits with a `subject` — `EWI_METRIC`, `WHOLESALE_RELIANCE_PCT`, `TOP_COUNTERPARTY_PCT`, `SURVIVAL_DAYS`, or `INTRADAY_NET_POSITION` — a `direction` of `ABOVE_BREACHES` or `BELOW_BREACHES`, a `limit_value` expressed in the subject's unit (the referenced metric's own unit for `EWI_METRIC`, basis points for the two percentage subjects, days for `SURVIVAL_DAYS`, and cents for `INTRADAY_NET_POSITION`), and a `severity` of `BOARD` or `REGULATORY`, an informational classification that does not alter detection behavior. The `ewi_metric_id` reference is required exactly when the subject is `EWI_METRIC` and forbidden for every other subject; either violation is a shape error under `ERR_INVALID_REQUEST`. Limits carry no lifecycle: every configured limit participates in detection from the moment it is created. The limit catalogue lists with `subject` and `ewi_metric_id` filters.

Four pipelines invoke the detection engine, each against its own subjects: metric readings against `EWI_METRIC` limits, funding evaluations against the two percentage subjects, projection finalization against `SURVIVAL_DAYS`, and intraday snapshots against `INTRADAY_NET_POSITION`. Boundary strictness is pinned. `ABOVE_BREACHES` breaches only when the observed value is strictly above the limit; `BELOW_BREACHES` breaches only when strictly below; an observed value exactly equal to the limit never breaches under either direction. Detection also deduplicates per limit: when a breach for the same limit already stands `OPEN`, `ACKNOWLEDGED`, or `ESCALATED`, no new breach is created, so only `REMEDIATED` history may coexist with a fresh breach. A new breach opens in `OPEN` status carrying the `limit_id` of the limit it tripped, the offending `detected_value`, a snapshot of the `limit_value` taken at detection, the copied `subject`, the invoking pipeline's `source_type` — one of `METRIC_READING`, `FUNDING_EVALUATION`, `PROJECTION_FINALIZE`, or `INTRADAY_SNAPSHOT` — and a polymorphic `source_id` naming the detecting reading, run, or snapshot, null for funding evaluations.

The breach lifecycle is a fork guarded by segregation of duties. A `RiskOfficer` acknowledges an `OPEN` breach, moving it to `ACKNOWLEDGED` and recording `acknowledged_by_user_id`. From `ACKNOWLEDGED`, a `LiquidityCommittee` member may escalate to `ESCALATED`. Remediation closes the loop but re-proves the numbers at remediate time: the current value of the breach's subject is re-evaluated against the limit — at or below `limit_value` for `ABOVE_BREACHES`, at or above it for `BELOW_BREACHES` — and if the breach still stands the request fails with `ERR_LIMIT_STILL_BREACHED`. From `ACKNOWLEDGED`, either a `RiskOfficer` or a `LiquidityCommittee` member may remediate; from `ESCALATED`, remediation is committee-only, and a `RiskOfficer` attempting that branch is rejected with `ERR_FORBIDDEN`. In both branches, when an `acknowledged_by_user_id` is recorded, the remediator's `X-User-ID` must differ from it (`ERR_SOD_VIOLATION`). A successful remediation records `remediated_by_user_id` together with the caller's free-text `remediation_note`. Breaches are listed under their limit and fetched individually.

Intraday monitoring is the fourth detection pipeline. `TreasuryOps` posts snapshots carrying a `business_date` bucket in YYYY-MM-DD form, a `snapshot_at` observation instant, the `opening_balance_cents`, and cumulative `payments_received_cents` and `payments_sent_cents` since the open — neither cumulative figure may be negative. The derived `net_position_cents` is the opening balance plus payments received minus payments sent. Ordering within a `business_date` bucket is strict: `snapshot_at` must be greater than every existing snapshot in that bucket, or the post is rejected with `ERR_SNAPSHOT_OUT_OF_ORDER`. Each accepted snapshot immediately runs detection against `INTRADAY_NET_POSITION` limits with `source_type` `INTRADAY_SNAPSHOT` and itself as `source_id`. Snapshots list with a `business_date` filter.

### 3.8. Contingency Playbook Construction and Capacity Testing

A `TreasuryAnalyst` drafts a contingency playbook with a `name`, the `scenario_id` supplying the stress context its capacity test will use, a `min_activation_posture` of `NORMAL`, `HEIGHTENED`, `SEVERE`, or `CRISIS`, and a strictly positive `target_capacity_cents` — the funding capacity the playbook must demonstrably cover. Creation stamps `created_by_user_id` from the caller's header, opens the playbook in `DRAFT`, and leaves `approved_by_user_id`, `tested_at`, and `activated_at` empty. The playbook list supports `scenario_id` and `status` filters.

While the playbook is `DRAFT`, the analyst may edit its header — any of `name`, `min_activation_posture`, or `target_capacity_cents` — presenting `expected_playbook_version` as §2.7 requires, and each accepted edit bumps the playbook's `version` by one. Actions are added under the same `DRAFT` condition, each carrying a `kind` of `ASSET_SALE` or `LINE_DRAWDOWN`, a positive `sequence_no` unique within its playbook, a strictly positive `estimated_proceeds_cents`, and a `settlement_lag_days` of zero or more. Cross-field rules pin the references: `asset_id` is required exactly when the kind is `ASSET_SALE`, `line_id` exactly when it is `LINE_DRAWDOWN`, and an optional `prerequisite_action_id` must reference another action of the same playbook with a strictly smaller sequence number — a dependency graph that is acyclic by construction. Breaching any of these rules surfaces `ERR_INVALID_REQUEST`. New actions start `PENDING` with `executed_at` unset. Actions are listed under their playbook, through a global list filterable by `playbook_id`, `prerequisite_action_id`, `line_id`, `asset_id`, and `status`, and fetched individually.

The capacity test is a `RiskOfficer` gate available while the playbook stands `DRAFT`, and it requires the playbook to have at least one action — an empty playbook fails shape validation with `ERR_INVALID_REQUEST`. Each action's realizable capacity is assessed as follows: an `ASSET_SALE` counts the STRESS-variant adjusted value of its referenced asset, computed with the playbook scenario's add-on per §3.3, when that asset is `UNENCUMBERED`, and zero otherwise; a `LINE_DRAWDOWN` counts its referenced line's current `borrowing_power_cents` when the line is `ACTIVE`, and zero otherwise. An action passes when its realizable capacity covers its `estimated_proceeds_cents`. Beyond the per-action checks, every referenced line faces an aggregate check: the summed `estimated_proceeds_cents` of all the playbook's drawdown actions on that line must not exceed the line's borrowing power. The result is `PASSED` exactly when every action passes, every per-line aggregate holds, and `total_estimated_cents` — the sum of estimated proceeds across all actions — reaches `target_capacity_cents`.

A passing test moves the playbook `DRAFT` → `TESTED` and stamps `tested_at` with the logical clock. A failing test leaves the playbook in `DRAFT` and returns the detail inline rather than as an error: the `result`, the `total_estimated_cents`, the `total_realizable_cents` — the sum, per action, of the smaller of its estimated proceeds and its realizable capacity — and the `failures` list.

### 3.9. Playbook Approval, Activation, Execution, and Closure

Every transition in this section is available only from its named from-state; invoking one against a playbook or action standing in any other status is rejected with `ERR_INVALID_STATE`.

Approval is a `RiskOfficer` act guarded by segregation of duties: the approver's `X-User-ID` must differ from the playbook's `created_by_user_id`, or the request fails with `ERR_SOD_VIOLATION`. A clean approval moves the playbook `TESTED` → `APPROVED` and records `approved_by_user_id`.

Activation belongs to the `LiquidityCommittee` and is doubly gated. The current posture's ordinal must be at least the ordinal of the playbook's `min_activation_posture` — `NORMAL` at 0, `HEIGHTENED` at 1, `SEVERE` at 2, `CRISIS` at 3 — with shortfalls rejected as `ERR_POSTURE_INSUFFICIENT`; and the desk runs at most one active playbook at a time, so when any other playbook holds `ACTIVATED` or `EXECUTING` the activation fails with `ERR_PLAYBOOK_ALREADY_ACTIVE`. Success moves the playbook `APPROVED` → `ACTIVATED`, stamps `activated_at` with the logical clock, and flips every `PENDING` action of the playbook to `READY`.

Execution belongs to `TreasuryOps` and works one `READY` action at a time, with the playbook standing `ACTIVATED` or `EXECUTING`. Prerequisites are enforced at execute time: an action naming a `prerequisite_action_id` cannot execute until that prerequisite stands `SETTLED`, failing which the request is rejected with `ERR_PREREQUISITE_ACTION_INCOMPLETE`. What execution books depends on the action's kind. An `ASSET_SALE` requires its referenced asset to be `UNENCUMBERED` (`ERR_ASSET_NOT_AVAILABLE` otherwise) and marks the asset `SOLD`. A `LINE_DRAWDOWN` requires its line `ACTIVE` (`ERR_LINE_SUSPENDED` otherwise) and its `estimated_proceeds_cents` within the line's current `borrowing_power_cents` — the full power may be drawn — with excess rejected as `ERR_INSUFFICIENT_BORROWING_POWER`; the proceeds are added to the line's `drawn_cents` and borrowing power recomputes. Either way, `executed_at` stamps the logical clock, and the playbook's first execution moves the playbook itself `ACTIVATED` → `EXECUTING`.

Settlement and failure close actions out. Settlement requires the logical clock to have reached `executed_at` plus the action's `settlement_lag_days` — landing exactly on that instant counts as due — and an early attempt is rejected with `ERR_SETTLEMENT_NOT_DUE`; a settled action mutates nothing further. Failing an `EXECUTING` action marks it `FAILED`, and for a drawdown the failure compensates the booking: the proceeds come back off the line's `drawn_cents` and borrowing power recomputes, because the funds never arrived.

Three moves wind a playbook down. Stand-down, a `LiquidityCommittee` act from `ACTIVATED` or `EXECUTING`, is refused while any action of the playbook stands `EXECUTING` (`ERR_INVALID_STATE`); otherwise the playbook moves to `STOOD_DOWN` and every `PENDING`, `READY`, or `BLOCKED` action becomes `SKIPPED`. Revision, a `TreasuryAnalyst` act from `STOOD_DOWN`, returns the playbook to `DRAFT`, clears both `tested_at` and `approved_by_user_id` so that re-testing and re-approval are required, and returns every `SKIPPED` action to `PENDING`. Completion, a `LiquidityCommittee` act from `EXECUTING`, requires every action of the playbook to stand in a terminal state — `SETTLED`, `FAILED`, or `SKIPPED` — with stragglers earning `ERR_ACTIONS_NOT_ALL_TERMINAL`, and lands the playbook in `COMPLETED`, its terminal state.

## 4. Endpoint Definitions

All endpoints are mounted under the `/liquidity` prefix. Operations that create a new resource return HTTP 201; reads, modifications, and state transitions return HTTP 200. Applying that rule to the two evaluation endpoints: `POST /liquidity/funding-evaluations` is a computed read that persists no resource of its own, so it returns HTTP 200 even though breach detection may ride along with it, while `POST /liquidity/posture-evaluations` appends and returns a `PostureSnapshot`, so it returns HTTP 201. Request and response bodies are deliberately omitted from the table — they are reconstructed from the narratives in §3 — and the table fixes only the method, the path, a summary, and the authorized roles.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /liquidity/_clock/set_current_utc | Set the logical clock (test-driving) | PlatformAdmin |
| POST | /liquidity/stress-scenarios | Create a stress scenario (ACTIVE) | RiskOfficer |
| GET | /liquidity/stress-scenarios | List stress scenarios | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/stress-scenarios/{id} | Get a stress scenario | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/stress-scenarios/{id}/retire | Retire an ACTIVE scenario | RiskOfficer |
| GET | /liquidity/stress-scenarios/{id}/projection-runs | List projection runs of a scenario | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/stress-scenarios/{id}/projection-runs | Create a projection run (OCC on scenario version) | TreasuryAnalyst |
| GET | /liquidity/projection-runs/{id} | Get a projection run | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/projection-runs/{id}/finalize | Finalize a DRAFT run | TreasuryAnalyst |
| POST | /liquidity/liquid-assets | Register a liquid asset | TreasuryOps |
| GET | /liquidity/liquid-assets | List liquid assets | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| PATCH | /liquidity/liquid-assets/{id} | Reprice an asset | TreasuryOps |
| GET | /liquidity/hqla-summary | HQLA adjusted totals under both haircut variants | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/funding-sources | Record a funding source | TreasuryAnalyst |
| POST | /liquidity/funding-evaluations | Run a funding concentration evaluation | RiskOfficer |
| POST | /liquidity/ewi-metrics | Configure an EWI metric | RiskOfficer |
| GET | /liquidity/ewi-metrics | List EWI metrics | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/ewi-metrics/{id} | Get an EWI metric | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/ewi-metrics/{id}/readings | Post a metric reading | TreasuryAnalyst |
| GET | /liquidity/ewi-metrics/{id}/readings | List readings of a metric | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/ewi-dashboard | EWI dashboard computed read | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/posture-evaluations | Manual posture evaluation | RiskOfficer, LiquidityCommittee |
| GET | /liquidity/posture-snapshots | List posture snapshots | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/contingency-playbooks | Create a contingency playbook | TreasuryAnalyst |
| GET | /liquidity/contingency-playbooks | List contingency playbooks | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/contingency-playbooks/{id} | Get a playbook | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| PATCH | /liquidity/contingency-playbooks/{id} | Edit a DRAFT playbook (OCC) | TreasuryAnalyst |
| POST | /liquidity/contingency-playbooks/{id}/actions | Add an action to a DRAFT playbook | TreasuryAnalyst |
| GET | /liquidity/contingency-playbooks/{id}/actions | List actions of a playbook | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/playbook-actions/{id} | Get a playbook action | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/playbook-actions | Filtered list of playbook actions | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/contingency-playbooks/{id}/capacity-test | Run the capacity test | RiskOfficer |
| POST | /liquidity/contingency-playbooks/{id}/approve | Approve a TESTED playbook | RiskOfficer |
| POST | /liquidity/contingency-playbooks/{id}/activate | Activate an APPROVED playbook | LiquidityCommittee |
| POST | /liquidity/contingency-playbooks/{id}/stand-down | Stand down an ACTIVATED or EXECUTING playbook | LiquidityCommittee |
| POST | /liquidity/contingency-playbooks/{id}/revise | Return a STOOD_DOWN playbook to DRAFT | TreasuryAnalyst |
| POST | /liquidity/contingency-playbooks/{id}/complete | Complete an EXECUTING playbook | LiquidityCommittee |
| POST | /liquidity/playbook-actions/{id}/execute | Execute a READY action | TreasuryOps |
| POST | /liquidity/playbook-actions/{id}/settle | Settle an EXECUTING action | TreasuryOps |
| POST | /liquidity/playbook-actions/{id}/fail | Fail an EXECUTING action | TreasuryOps |
| POST | /liquidity/borrowing-lines | Create a borrowing line | TreasuryOps |
| GET | /liquidity/borrowing-lines/{id} | Get a borrowing line | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/borrowing-lines/{id}/suspend | Suspend an ACTIVE line | RiskOfficer |
| POST | /liquidity/borrowing-lines/{id}/reinstate | Reinstate a SUSPENDED line | RiskOfficer |
| POST | /liquidity/borrowing-lines/{id}/draw | Draw against a line | TreasuryOps |
| POST | /liquidity/borrowing-lines/{id}/repay | Repay drawn balance | TreasuryOps |
| POST | /liquidity/collateral-pledges | Pledge an asset to a line | TreasuryOps |
| GET | /liquidity/collateral-pledges | Filtered list of pledges | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/collateral-pledges/{id} | Get a pledge | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/collateral-pledges/{id}/release | Release an ACTIVE pledge | TreasuryOps |
| POST | /liquidity/board-limits | Create a board limit | RiskOfficer |
| GET | /liquidity/board-limits | List board limits | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/board-limits/{id} | Get a board limit | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/board-limits/{id}/breaches | List breaches of a limit | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| GET | /liquidity/breaches/{id} | Get a limit breach | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |
| POST | /liquidity/breaches/{id}/acknowledge | Acknowledge an OPEN breach | RiskOfficer |
| POST | /liquidity/breaches/{id}/escalate | Escalate an ACKNOWLEDGED breach | LiquidityCommittee |
| POST | /liquidity/breaches/{id}/remediate | Remediate a breach | RiskOfficer, LiquidityCommittee |
| POST | /liquidity/intraday-snapshots | Post an intraday liquidity snapshot | TreasuryOps |
| GET | /liquidity/intraday-snapshots | List intraday snapshots | TreasuryAnalyst, RiskOfficer, TreasuryOps, LiquidityCommittee |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_THRESHOLD_CONFIG_INVALID | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_POSTURE_INSUFFICIENT | 409 |
| ERR_LINE_SUSPENDED | 409 |
| ERR_ASSET_NOT_PLEDGEABLE | 409 |
| ERR_ASSET_NOT_AVAILABLE | 409 |
| ERR_SCENARIO_RETIRED | 409 |
| ERR_DEESCALATION_BLOCKED | 409 |
| ERR_SETTLEMENT_NOT_DUE | 409 |
| ERR_READING_TOO_FREQUENT | 409 |
| ERR_SNAPSHOT_OUT_OF_ORDER | 409 |
| ERR_DUPLICATE_ACTIVE_SCENARIO | 409 |
| ERR_LAST_BASELINE_SCENARIO | 409 |
| ERR_SCENARIO_IN_USE | 409 |
| ERR_PLAYBOOK_ALREADY_ACTIVE | 409 |
| ERR_PREREQUISITE_ACTION_INCOMPLETE | 409 |
| ERR_ACTIONS_NOT_ALL_TERMINAL | 409 |
| ERR_LIMIT_STILL_BREACHED | 409 |
| ERR_INSUFFICIENT_BORROWING_POWER | 409 |
| ERR_REPAY_EXCEEDS_DRAWN | 409 |
