# Value-Based Contract Settlement API — Product Requirements Document

## 1. Introduction

This document specifies the **Value-Based Contract (VBC) Settlement & Quality Withhold API**, the system of record a payer organization uses to administer its value-based care arrangements with contracted provider groups. The platform spans the full commercial lifecycle of a value-based contract: modeling upside-only and two-sided risk terms together with quality gates, attributing covered members to practices, measuring risk-adjusted cost against a negotiated benchmark, scoring clinical quality measures against a decile catalog, computing the quality-gated shared savings or shared losses that constitute the final settlement, accruing and releasing a per-claim quality withhold, adjudicating group-initiated disputes inside a regulated timeline, and distributing funds down to individual practices before a contract can be renewed, terminated, or archived.

The workload is adversarial in a way ordinary claims platforms are not. Attribution populations are re-opened and re-locked after measurement has begun. Risk scores are restated by actuaries after benchmarks have been computed. Claims arrive, are paid, and are voided mid-reconciliation. Interim estimates must coexist with final true-ups without double-counting. A quality measure reported but not yet locked can flip the final multiplier. A group that disagrees with the settlement must be able to force a recalculation without letting the certifying officer judge their own work, and the window in which disputes are admissible is contractually fixed. Every one of these pressures surfaces as an explicit rule in this document, and each rule is anchored to a deterministic calculation so that two independent implementations given the same event stream produce the same cent-level settlement.

The API is rooted at `/vbc`. A small number of cross-cutting concerns (the logical clock, optimistic concurrency on long-lived aggregates, segregation of duties between certifying and adjudicating officers, and the cascade contract by which a late claim or a restated risk score propagates into previously published reports and previously finalized settlements) are stated once in §2 and referenced throughout §3, where they are worked into the entity narratives that give them operational meaning.

## 2. Global Specifications & System-Wide Principles

This section pins down the contracts that apply across every entity and every endpoint: identity and access, response envelope, pagination, the logical clock that drives all date-stamping, common resource properties, precision and rounding, optimistic concurrency, and the validation cascade every request traverses.

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory HTTP headers. `X-User-ID` identifies the acting operator; `X-User-Role` names the operational capacity in which they are acting. The system recognizes eleven roles, spelled exactly as follows: `PayerAdmin`, `ContractManager`, `AttributionAnalyst`, `ActuaryAnalyst`, `QualityAnalyst`, `ClaimsProcessor`, `SettlementOfficer`, `DisputeAdjudicator`, `PaymentOps`, `Auditor`, and `PracticeGroupRep`. A request missing either header, or presenting an `X-User-Role` value that does not match one of these eleven names, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but which is not authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Ten of the eleven roles have an **opaque** identity: `X-User-ID` is an operator identifier not tied to any persisted entity, and although the server may record it on resources it mutates (for example, as `finalized_by_user_id` on a `Settlement` or `resolved_by_user_id` on a `SettlementDispute`), it is never compared against any entity's `id` for the purposes of ownership. The opaque-identity roles are `PayerAdmin`, `ContractManager`, `AttributionAnalyst`, `ActuaryAnalyst`, `QualityAnalyst`, `ClaimsProcessor`, `SettlementOfficer`, `DisputeAdjudicator`, `PaymentOps`, and `Auditor`.

The remaining role is entity-backed. When `X-User-Role` is `PracticeGroupRep`, `X-User-ID` is the `id` of the acting `PracticeGroup`; ownership checks on any resource that references a `PracticeGroup` compare the resource's foreign-key field to `X-User-ID`. A `PracticeGroupRep` caller attempting to read or mutate a settlement or a dispute whose underlying contract is owned by a different `PracticeGroup` is rejected with `ERR_FORBIDDEN_GROUP_SCOPE` (HTTP 403); this scope check is applied to settlement and dispute GET endpoints and to the dispute create and withdraw actions whenever the caller's role is `PracticeGroupRep`.

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

List endpoints accept two optional query parameters. `limit` caps the number of items returned; it defaults to 10, has a minimum of 1, and has a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` block of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All date and timestamp decisions in the system — stamping `paid_on` when a claim is marked paid, stamping `filed_on` when a dispute is filed, deciding whether the dispute window on a finalized settlement has closed, deciding whether the measurement period has ended, deciding whether the reconciliation runout has elapsed — read from a single **logical clock**, never from wall-clock time. At server startup, before any operator action, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `PayerAdmin` may advance the clock via the test-driving capability that accepts a `to_iso8601` timestamp and returns the new `current_utc`; once set, the clock reads the value supplied by the most recent call. No code path may fall back to wall-clock time.

### 2.5. Common Resource Properties

Every top-level resource in the system (`Program`, `PracticeGroup`, `Practice`, `Member`, `EligibilitySpan`, `Contract`, `PerformanceYear`, `AttributionRun`, `AttributionRecord`, `RiskScore`, `ClaimRecord`, `QualityMeasureResult`, `InterimReport`, `Settlement`, `SettlementDispute`, `DistributionRemittance`, `RenewalAnalysis`) carries the same four system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer starting at 1, incremented by exactly 1 on every mutation.

A mutation is any change to any field of the resource, including changes to derived or computed fields performed by the server. When a side effect of an operation on entity A mutates entity B (for example, a risk-score finalize that recomputes a year's `benchmark_cost_cents`), B's `updated_at` is refreshed and B's `version` is incremented, in addition to any change on A. Year-lifecycle transitions on a `PerformanceYear` (lock-attribution, begin-measurement, begin-reconciliation, reopen-attribution, mark-settled) each increment the year's `version` by exactly 1, as do settlement transitions on a `Settlement` (finalize, recalculate, authorize-distribution) and the parent-bumping cascades named in §2.7.

### 2.6. Precision, Rounding, and Sign Conventions

All monetary amounts are integer cents. All rates and scores are integers of fixed scale: basis-point rates are integers between 0 and 10000 inclusive; risk scores are integer milli-units (a score of 1250 represents 1.250); quality composites are integer points in 0..100. Two rounding rules are used throughout and are named precisely:

- **Round half up** — fractions of exactly one-half round away from zero. Applied to per-record benchmark contributions, per-claim withhold amounts, estimated annualization and completion-factor figures, quality composite points, the sliding-scale gate multiplier, shared savings and shared losses before capping, quality-adjusted savings, withhold release amounts, the reserve accrual, and interim estimated net payable. Every multiplication-and-division step that produces cents or basis points is rounded half-up to a whole cent or whole basis point at the step where it is named.
- **Truncation toward zero** — applied only where named: the savings rate in basis points on a settlement and the realized savings rate on a renewal analysis. A negative gross truncated toward zero rounds toward zero (so -1234.7 becomes -1234).

Two division operations use **floor** semantics rather than round-half-up: the member-month-weighted mean risk score in milli (floor division of the weighted sum by the total member months) and the per-practice allocation floor inside the largest-remainder waterfall. The order of operations matters wherever rounding is involved: per-record or per-claim rounding happens **before** summation, never after. Sum-then-round is forbidden because it produces different cents.

### 2.7. Optimistic Concurrency Control on Long-Lived Aggregates

Three creation endpoints are guarded by optimistic concurrency against their parent aggregate. The guard is always expressed as a required request field of the form `expected_<parent>_version` carrying the client's last observed `version` of the parent entity. If the parent's current `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

- Creating an attribution run against a `PerformanceYear` requires `expected_performance_year_version` matching that year's current `version`. The guarded endpoint is the attribution-run create nested under the year.
- Creating an interim report against a `PerformanceYear` requires `expected_performance_year_version` matching that year's current `version`. The guarded endpoint is the interim-report create.
- Creating a renewal analysis against a `Contract` requires `expected_contract_version` matching that contract's current `version`. The guarded endpoint is the renewal-analysis create nested under the contract.

Endpoints not listed above do not take a version field. The OCC rule exists so that a writer who has just observed a year or contract cannot silently overwrite a sibling run, report, or analysis that another writer legitimately created and which has already superseded the client's view.

### 2.8. The Validation Cascade

Every request traverses a fixed priority cascade; the first failing rule wins and produces the response. Lower-priority checks are not evaluated once a higher-priority check has failed.

1. **Auth context** — `X-User-ID` and `X-User-Role` headers are present and the role names a declared role; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization** — the caller's role is listed in the endpoint's authorized roles; otherwise `ERR_FORBIDDEN_FOR_ROLE` (403).
3. **Existence** — path resource identifiers are validated left-to-right; the first missing id produces `ERR_NOT_FOUND` (404). Body foreign-key references are also validated here.
4. **PracticeGroupRep scope** — when the caller's role is `PracticeGroupRep` and the target is a settlement, a dispute, or the dispute create/withdraw action, `X-User-ID` must equal the `id` of the `PracticeGroup` that owns the contract behind the targeted resource; otherwise `ERR_FORBIDDEN_GROUP_SCOPE` (403).
5. **Request shape** — required fields present, no unknown fields, types valid, enum values in their declared domain, scalar ranges satisfied (`birth_year` between 1900 and 2026 inclusive, `score_milli` between 1 and 10000 inclusive, `months_elapsed` between 1 and 11 inclusive); otherwise `ERR_INVALID_REQUEST` (400).
6. **State preconditions** — the target resource is in a from-state of the invoked transition; failures produce `ERR_INVALID_STATE_TRANSITION` or one of the more specific state-family errors listed in §5 (all 409).
7. **Segregation and pinning** — on dispute resolve, the caller's `X-User-ID` must differ from the settlement's `finalized_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, 409); on risk-score create, the payload's `model_used` must equal the contract's pinned `risk_model` (`ERR_RISK_MODEL_MISMATCH`, 409).
8. **Temporal and window rules** — dispute filing within the dispute window (`ERR_DISPUTE_WINDOW_CLOSED`), mark-settled and authorize-distribution only after the dispute window (`ERR_DISPUTE_WINDOW_OPEN`), dispute resolve within the resolution window (`ERR_DISPUTE_RESOLUTION_WINDOW_ELAPSED`), dispute expire only after it (`ERR_DISPUTE_NOT_EXPIRABLE`), begin-reconciliation at or after `period_end` (`ERR_MEASUREMENT_PERIOD_NOT_ENDED`), settlement finalize at or after `period_end` plus the reconciliation runout (`ERR_RECONCILIATION_RUNOUT_INCOMPLETE`), year window contained in the contract term (`ERR_YEAR_OUTSIDE_TERM`), claim `service_date` inside the year window (`ERR_CLAIM_OUTSIDE_PERIOD`). All 409.
9. **Overlap rules** — a new performance year's half-open window must not intersect an existing year of the same contract (`ERR_PERIOD_OVERLAP`); a new eligibility span's closed interval must not share any calendar date with another span of the same member (`ERR_SPAN_OVERLAP`). Both 409.
10. **Referential integrity for attribution** — on attribution-record create, the practice must belong to the contract's group (`ERR_PRACTICE_GROUP_MISMATCH`), the practice must be `ACTIVE` (`ERR_PRACTICE_INACTIVE`), the member must belong to the contract's program (`ERR_MEMBER_PROGRAM_MISMATCH`), the member must be `ELIGIBLE` (`ERR_MEMBER_DISENROLLED`), and the member must have at least one mid-month-eligible month within the year window (`ERR_MEMBER_NO_ELIGIBLE_MONTHS`). All 409. This step also guards dispute create's referential preconditions.
11. **Uniqueness** — `tin` globally (`ERR_DUPLICATE_TIN`), `npi` globally (`ERR_DUPLICATE_NPI`), `member_ref` within a program (`ERR_DUPLICATE_MEMBER_REF`), `contract_ref` within a program (`ERR_DUPLICATE_CONTRACT_REF`), `year_label` within a contract (`ERR_DUPLICATE_YEAR_LABEL`), `claim_ref` within a year (`ERR_DUPLICATE_CLAIM_REF`), one non-`SUPERSEDED` `RiskScore` per (member, year, `model_used`) (`ERR_DUPLICATE_RISK_SCORE`), one non-`EXCLUDED` `QualityMeasureResult` per (year, `measure_code`) (`ERR_DUPLICATE_MEASURE_RESULT`), at most one non-`VOID` `Settlement` per year (`ERR_SETTLEMENT_EXISTS`), and the reported `measure_code` must exist in the contract's `quality_measures` catalog (`ERR_UNKNOWN_MEASURE_CODE`). All 409.
12. **Fiscal and rate sanity** — `benchmark_pmpm_cents` strictly positive; all basis-point rates in 0..10000 inclusive; a `TWO_SIDED` contract must carry `shared_loss_rate_bp` and `loss_cap_bp`; `quality_gate_floor_points` strictly less than `quality_gate_excellence_points` with both in 0..100; every entry in `quality_measures` has a positive weight and exactly 9 strictly ascending decile thresholds. Violations of this family produce `ERR_INVALID_RATE_CONFIG` (422). `paid_amount_cents` and `claimed_adjustment_cents` must be strictly positive (`ERR_INVALID_AMOUNT`, 422). Start dates must be strictly before end dates on span, contract, and year creation (`ERR_INVALID_DATE_RANGE`, 422).
13. **Quality math guards** — `numerator_count` must not exceed `denominator_count` (`ERR_NUMERATOR_EXCEEDS_DENOMINATOR`, 422); validate requires `denominator_count` at least 1 (`ERR_EMPTY_DENOMINATOR`, 422); begin-reconciliation requires `total_member_months` strictly positive (`ERR_EMPTY_POPULATION`, 422).
14. **OCC** — on the three guarded creates enumerated in §2.7, the supplied `expected_<parent>_version` must equal the parent's current `version` (`ERR_STALE_VERSION`, 412).

### 2.9. Nested Resource Retrieval

For endpoints whose path nests one resource beneath another (for example, the attribution-record create beneath an attribution run, or the dispute create beneath a settlement), path identifiers are validated in left-to-right order. The first path identifier that does not correspond to an existing resource produces the 404; subsequent segments are not consulted. Body foreign keys are validated after path identifiers, at the same priority tier.

### 2.10. Cross-Aggregate Consistency and the `needs_recompute` Contract

A settlement is a snapshot over four year-level rollups (`total_member_months`, `actual_cost_cents`, `benchmark_cost_cents`, `withhold_pool_cents`), the year's locked quality results, and the contract's terms. Because claims, risk scores, and attribution records can all change after a settlement has been drafted, the system maintains a single boolean flag on each `Settlement` named `needs_recompute`, defaulting to `false`. Any post-finalize data mutation that touches the year — a claim being marked paid or voided, a risk score being finalized or superseded, an attribution record being excluded or reinstated, a quality measure result being excluded — sets `needs_recompute` to `true` on the year's settlement when that settlement is in `PROVISIONAL` or `FINALIZED`. A settlement in `PROVISIONAL` with `needs_recompute` set can be brought back into agreement with the data via the recalculate action, which recomputes every computed field from current data and clears the flag; a settlement with the flag set cannot be finalized (the attempt is rejected with `ERR_SETTLEMENT_STALE`). Once a settlement has advanced past `FINALIZED` into `DISPUTED`, `RECALCULATING`, `AUTHORIZED`, or `DISTRIBUTED`, the flag is no longer consulted.

A companion cascade handles the year's interim reports. Whenever the year's `actual_cost_cents`, `withhold_pool_cents`, or the underlying population rollups mutate — through claim mark-paid or void, attribution exclude or reinstate, or risk-score finalize or supersede — every `PUBLISHED` `InterimReport` of the year transitions to `STALE`. The year's `accrued_reserve_cents` is not retroactively adjusted by this transition; it remains at the value posted by the most recently published report until a newer report is published or the year settles.

### 2.11. Risk-Model Pinning

When a contract transitions from `DRAFT` to `ACTIVE`, its `risk_model` becomes immutable: there is no endpoint that modifies it. The pinned value selects which variant of the risk-score population is authoritative for the benchmark rollup. Any subsequent attempt to ingest a `RiskScore` whose `model_used` differs from the pinned `risk_model` is rejected with `ERR_RISK_MODEL_MISMATCH`. The pinned value is one of `PROSPECTIVE` or `CONCURRENT`.

## 3. Business Logic & Workflows

This section walks the operational lifecycle from program setup through renewal, in the order a payer typically runs it. State names appear as exact UPPERCASE strings; where two states are named with an arrow between them the arrow denotes a transition the API exposes.

### 3.1. Programs, Provider Groups, and Practices

A `PayerAdmin` begins by registering a `Program`, supplying a `program_name` and a `line_of_business` drawn from `MEDICARE_ADVANTAGE`, `MEDICAID_MANAGED_CARE`, or `COMMERCIAL_ACO`. The program's `program_status` field is set to `DRAFT` at creation and transitions `DRAFT → ACTIVE` when the admin activates it. Activation has no preconditions; archiving does. The transition `ACTIVE → ARCHIVED` is rejected with `ERR_PROGRAM_HAS_OPEN_CONTRACTS` if any `Contract` of the program is currently in `DRAFT` or `ACTIVE`. `ARCHIVED` is terminal.

Provider-side, the admin registers a `PracticeGroup` with a `group_name` and a federal `tin` that must be unique across all groups regardless of status. The group's `group_status` is created as `ACTIVE`. From `ACTIVE` the admin may suspend the group (`ACTIVE → SUSPENDED`), supplying a free-text `reason` that is recorded verbatim on the group's `suspension_reason`; from `SUSPENDED` the admin may reinstate (`SUSPENDED → ACTIVE`), which clears `suspension_reason` back to null. Termination is the terminal transition and is available from both `ACTIVE` and `SUSPENDED` (`ACTIVE → TERMINATED` and `SUSPENDED → TERMINATED`); either branch is rejected with `ERR_GROUP_HAS_OPEN_CONTRACTS` when any `Contract` naming this group is in `DRAFT` or `ACTIVE`.

Within a group the admin registers individual `Practice` sites, each carrying a `practice_group_id`, a `practice_name`, and a National Provider Identifier `npi` that must be unique across all practices in the system. The practice's `practice_status` is created as `ACTIVE` and may be deactivated (`ACTIVE → INACTIVE`), with `INACTIVE` terminal; deactivation has no preconditions but does constrain future attribution, as §3.5 describes.

### 3.2. Members and Eligibility Spans

Each covered life is a `Member`, registered by a `PayerAdmin` with the `program_id` of the covering program, a payer-external `member_ref` unique within that program, and a `birth_year` between 1900 and 2026 inclusive. A member's `member_status` is created as `ELIGIBLE`. The disenroll action transitions `ELIGIBLE → DISENROLLED` with no preconditions, with `DISENROLLED` terminal; a disenrolled member cannot be added to any new attribution record (an attempt is rejected with `ERR_MEMBER_DISENROLLED`), but existing attribution records and existing claims naming the member are unaffected and continue to drive the rollups they were already contributing to.

Eligibility over time is captured by `EligibilitySpan` records. Each span is created with a `member_id`, an inclusive `start_date`, and an inclusive `end_date` — the interval is **closed** at both ends. A span's `span_status` is created as `ACTIVE` and may be closed (`ACTIVE → CLOSED`); once closed, the span no longer counts toward member-months on any subsequent attribution compute. Because the interval is closed, two spans of the same member may not share even a single calendar date; an overlapping create is rejected with `ERR_SPAN_OVERLAP`. This is stricter than the half-open rule that governs performance years, where adjacency is permitted; §3.4 contrasts the two.

### 3.3. Contract Terms and Activation

A `ContractManager` drafts a `Contract` by supplying the `program_id`, the contracted `practice_group_id`, a `contract_ref` unique within the program, an inclusive `effective_start`, an exclusive `effective_end` (the term is half-open), and the financial terms. The `risk_track` is either `ONE_SIDED_UPSIDE` or `TWO_SIDED`. The `risk_model` — `PROSPECTIVE` or `CONCURRENT` — selects which risk-score variant will be authoritative for the benchmark; it is captured at activation and pinned thereafter. The `benchmark_pmpm_cents` is the per-member-per-month benchmark cost in cents and must be strictly positive. `shared_savings_rate_bp` is the basis-point share of gross savings paid to the group and must lie between 0 and 10000 inclusive. `shared_loss_rate_bp` plays the symmetric role on the downside and is required if and only if the contract is `TWO_SIDED`. `min_savings_rate_bp` is the minimum savings rate (MSR) in basis points of benchmark that must be reached before any shared savings are paid; the comparison is greater-than-or-equal. `min_loss_rate_bp` is the minimum loss rate (MLR) in basis points of benchmark that losses must exceed before shared losses are owed; the comparison on the signed rate is less-than-or-equal to the negated threshold. `savings_cap_bp` caps shared savings as a percentage of the risk-adjusted benchmark; `loss_cap_bp` does the same for shared losses and is meaningful only on `TWO_SIDED` contracts. `stop_loss_cents` is a per-member annual claims truncation applied during cost measurement. `withhold_rate_bp` is the quality withhold applied per paid claim. `quality_gate_floor_points` and `quality_gate_excellence_points` (both integers in 0..100, with the floor strictly less than the excellence point) define the sliding scale: at or above excellence the multiplier is 10000 basis points; at or above the floor but below excellence the multiplier interpolates; below the floor it is zero. `estimate_method` selects the authoritative interim estimate variant — `ANNUALIZATION` or `COMPLETION_FACTOR`. Finally `quality_measures` is the catalog of measures against which quality results will be reported; each entry supplies a `measure_code`, a positive `weight_bp`, and exactly 9 strictly ascending integers in `decile_thresholds_bp`. Weights across the catalog are not required to sum to 10000.

A contract's `contract_status` is created as `DRAFT`. Activation (`DRAFT → ACTIVE`) is performed by a `ContractManager` and is guarded by two preconditions evaluated in cascade order: the program must be in `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`) and the contracted group must be in `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`). Activation pins `risk_model` as described in §2.11.

From `ACTIVE` the contract may move to `EXPIRED` or to `TERMINATED`. Expiry (`ACTIVE → EXPIRED`) requires that the logical clock date be at or after `effective_end` (`ERR_CONTRACT_TERM_NOT_ENDED` otherwise) and that every performance year of the contract be in `CLOSED` (`ERR_YEARS_NOT_CLOSED` otherwise). Termination (`ACTIVE → TERMINATED`) requires that no performance year of the contract is currently in any of `ATTRIBUTION_OPEN`, `ATTRIBUTION_LOCKED`, `MEASURING`, `RECONCILING`, or `SETTLED`; an in-flight year produces `ERR_YEARS_IN_FLIGHT`. From `EXPIRED` the contract may be renewed (`EXPIRED → RENEWED`) once a renewal analysis recommends it; §3.13 covers that flow. Both `TERMINATED` and `RENEWED` are terminal.

### 3.4. Performance Years and Their Windows

Each contract is measured one calendar-aligned `PerformanceYear` at a time. A `PayerAdmin` creates a year by supplying the `contract_id`, an integer `year_label` (unique within the contract), an inclusive `period_start`, and an exclusive `period_end`; the year's `year_status` is set to `SETUP`. The window is half-open: a claim or span contributes to the year only when its date lies on or after `period_start` and strictly before `period_end`. Two years of the same contract may not have intersecting windows; adjacency is permitted, so a new year whose `period_start` equals an existing year's `period_end` is allowed. An intersecting create is rejected with `ERR_PERIOD_OVERLAP`.

The year walks a cyclic state machine. From `SETUP` the admin opens attribution (`SETUP → ATTRIBUTION_OPEN`); this requires the contract to be in `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the year window to be contained within the contract term — `period_start` on or after `effective_start` and `period_end` on or before `effective_end` (`ERR_YEAR_OUTSIDE_TERM`). From `ATTRIBUTION_OPEN` the admin locks attribution (`ATTRIBUTION_OPEN → ATTRIBUTION_LOCKED`); this requires exactly one `AttributionRun` of the year to be in `LOCKED` status (`ERR_NO_LOCKED_ATTRIBUTION_RUN` if there is none; the run lock itself enforces at-most-one). The side effect is significant: the year records the run as its `locked_run_id`, then recomputes `total_member_months`, `risk_adjustment_factor_milli`, and `benchmark_cost_cents` per the attribution rollup described in §3.6.

From `ATTRIBUTION_LOCKED` the admin begins measurement (`ATTRIBUTION_LOCKED → MEASURING`), which computes `actual_cost_cents` and `withhold_pool_cents` per §3.7. From `MEASURING` the admin begins reconciliation (`MEASURING → RECONCILING`); this is gated by three preconditions evaluated together — the logical clock date must be at or after `period_end` (`ERR_MEASUREMENT_PERIOD_NOT_ENDED`), the year's `total_member_months` must be strictly positive (`ERR_EMPTY_POPULATION`), and every `QualityMeasureResult` of the year must be in either `LOCKED` or `EXCLUDED` (`ERR_QUALITY_RESULTS_UNLOCKED`).

Two exits exist from `RECONCILING`. The admin may reopen attribution (`RECONCILING → ATTRIBUTION_OPEN`) provided the year's settlement, if one exists, is still in `PROVISIONAL` (`ERR_SETTLEMENT_BEYOND_PROVISIONAL` once it has advanced). The reopen performs a coordinated reset: the currently `LOCKED` attribution run is moved to `SUPERSEDED` (a `LOCKED → SUPERSEDED` transition on the run), the year's `locked_run_id` is cleared to null, the `PROVISIONAL` settlement is moved to `VOID` (a `PROVISIONAL → VOID` transition on the settlement), and the rollups are zeroed — `total_member_months` to 0, `benchmark_cost_cents` to 0, `risk_adjustment_factor_milli` to null, `actual_cost_cents` to 0, and `withhold_pool_cents` to 0. The other exit is taken by a `SettlementOfficer` who marks the year settled (`RECONCILING → SETTLED`); this requires a settlement in `FINALIZED`, `AUTHORIZED`, or `DISTRIBUTED` (`ERR_SETTLEMENT_NOT_FINAL` otherwise) and requires the logical clock date to be strictly greater than the settlement's `finalized_on` plus the dispute window (`ERR_DISPUTE_WINDOW_OPEN` otherwise). Marking settled releases the reserve: `accrued_reserve_cents` is set to 0. Finally, an `Auditor` closes the year (`SETTLED → CLOSED`); this requires the settlement to be in `DISTRIBUTED` (`ERR_SETTLEMENT_NOT_DISTRIBUTED`).

Each of the five year transitions performed by an operator — open-attribution, lock-attribution, begin-measurement, begin-reconciliation, reopen-attribution, and mark-settled — increments the year's `version` by exactly 1.

### 3.5. Attribution Runs and Records

Attribution is computed in runs. An `AttributionAnalyst` creates an `AttributionRun` against a year by supplying a `run_label`; the run's `run_status` is created as `DRAFT` and the run is assigned a `run_seq` equal to one more than the highest existing `run_seq` for that year, starting at 1. Creating a run against a year that is not in `ATTRIBUTION_OPEN` is rejected with `ERR_YEAR_NOT_OPEN`. Creation is OCC-guarded against the year per §2.7 — the request must carry `expected_performance_year_version`. Creating a new run supersedes the previous run: any prior run of the same year in `DRAFT` is moved to `SUPERSEDED` (a `DRAFT → SUPERSEDED` transition), and any prior run in `COMPUTED` is moved to `SUPERSEDED` (a `COMPUTED → SUPERSEDED` transition); records of a superseded run remain queryable but never again drive rollups. A `LOCKED` run is not superseded by run creation; only the reopen-attribution cascade of §3.4 moves a `LOCKED` run to `SUPERSEDED`.

Within a `DRAFT` run, the analyst adds `AttributionRecord` entries by supplying the `member_id` and the attributed `practice_id`; each record's `record_status` is created as `PROVISIONAL`. Adding a record to a run not in `DRAFT` is rejected with `ERR_RUN_NOT_DRAFT`. Records are unique per member per run: the same member cannot appear twice in one run. Record creation enforces a five-part referential check in cascade order — the practice must belong to the contract's group (`ERR_PRACTICE_GROUP_MISMATCH`), the practice must be in `ACTIVE` (`ERR_PRACTICE_INACTIVE`), the member must belong to the contract's program (`ERR_MEMBER_PROGRAM_MISMATCH`), the member must be in `ELIGIBLE` (`ERR_MEMBER_DISENROLLED`), and the member must have at least one mid-month-eligible month within the year window (`ERR_MEMBER_NO_ELIGIBLE_MONTHS`).

The mid-month rule determines member-months. For each calendar month intersecting the half-open year window, the system looks at the 15th of that month (the mid-month day). If the 15th lies on or after `period_start` and strictly before `period_end`, and if the member has at least one `ACTIVE` `EligibilitySpan` whose inclusive `start_date` is on or before the 15th and whose inclusive `end_date` is on or after the 15th, the month counts as one member-month. `CLOSED` spans are ignored entirely. The sum across all intersecting months is the record's `member_months`. This is computed at run compute.

The analyst computes the run (`DRAFT → COMPUTED`). Compute re-evaluates `member_months` for every record per the mid-month rule, transitions every record from `PROVISIONAL` to `CONFIRMED` (a `PROVISIONAL → CONFIRMED` transition on each record), and stamps `attributed_member_count` with the number of `CONFIRMED` records. The analyst then locks the run (`COMPUTED → LOCKED`). Locking requires the year to be in `ATTRIBUTION_OPEN` (`ERR_YEAR_NOT_OPEN`) and requires that no other run of the same year is currently in `LOCKED` (`ERR_RUN_ALREADY_LOCKED`).

After a run is locked, individual records may still be excluded and reinstated. Exclusion (`CONFIRMED → EXCLUDED`) and reinstatement (`EXCLUDED → CONFIRMED`) are both performed by an `AttributionAnalyst` and both require the run to be in `LOCKED` (`ERR_RUN_NOT_LOCKED`) and the year to be in any status other than `SETTLED` or `CLOSED` (`ERR_YEAR_LOCKED`). Exclusion triggers a two-link cascade: first, the year's `total_member_months` and `benchmark_cost_cents` are recomputed without this record; second, the year's settlement, if it is in `PROVISIONAL` or `FINALIZED`, has its `needs_recompute` set to `true` — this is the serialization point between attribution edits and downstream settlement. Reinstatement restores the record and recomputes the year rollups with the record back in scope; the compensating invariant is that an exclude followed by a reinstate leaves `total_member_months` identical to its pre-exclude value.

### 3.6. Risk Scores and the Attribution Rollup

An `ActuaryAnalyst` ingests a `RiskScore` by supplying the `member_id`, the `performance_year_id`, a `model_used` of `PROSPECTIVE` or `CONCURRENT`, and a `score_milli` between 1 and 10000 inclusive. The payload's `model_used` must equal the contract's pinned `risk_model` (`ERR_RISK_MODEL_MISMATCH`). At most one non-`SUPERSEDED` score exists per (member, year, `model_used`) triple; a duplicate is rejected with `ERR_DUPLICATE_RISK_SCORE`. A score's `score_status` is created as `PRELIMINARY`. The analyst may finalize it (`PRELIMINARY → FINAL`) with no further preconditions, or supersede it (`PRELIMINARY → SUPERSEDED`) with no preconditions. A `FINAL` score may also be superseded (`FINAL → SUPERSEDED`) provided the year is not in `SETTLED` or `CLOSED` (`ERR_YEAR_LOCKED`); the side effect is that the year rollups are recomputed without this score, with the missing `FINAL` score falling back to the default of 1000 milli (a neutral 1.000 risk factor), and the year's settlement has `needs_recompute` set when in `PROVISIONAL` or `FINALIZED`.

Finalizing a score when the year's rollups have already been computed (that is, the year is in `ATTRIBUTION_LOCKED` or later) recomputes `benchmark_cost_cents` and `risk_adjustment_factor_milli`, and likewise sets `needs_recompute` on the year's settlement when in `PROVISIONAL` or `FINALIZED`.

The attribution rollup, which fires on lock-attribution and again on every record exclude or reinstate and every risk-score finalize or supersede, is defined as follows. The population is the set of `AttributionRecord` entries whose `attribution_run_id` equals the year's `locked_run_id` and whose `record_status` is `CONFIRMED`; records of superseded runs and records in `EXCLUDED` are never counted. The year's `total_member_months` is the sum of `member_months` over the population. For each record, the member's authoritative risk score is the `FINAL` `RiskScore` whose `model_used` equals the contract's pinned `risk_model`; if no such score exists, the default of 1000 milli is used. The year's `risk_adjustment_factor_milli` is the floor of the weighted mean — the sum over the population of each record's `member_months` multiplied by its authoritative `score_milli`, divided by the sum of `member_months`, with floor division to an integer milli. The year's `benchmark_cost_cents` is the sum over the population of a per-record term: the contract's `benchmark_pmpm_cents` multiplied by the record's `member_months` multiplied by the record's authoritative `score_milli`, divided by 1000, rounded half-up to a whole cent per record, and only then summed. Per-record rounding followed by summation is pinned; the reverse order produces different cents and is forbidden.

The same weighted-mean formula is in fact evaluated twice — once over `FINAL` scores with `model_used` `PROSPECTIVE` and once over `FINAL` scores with `model_used` `CONCURRENT` — and the contract's pinned `risk_model` selects which variant drives `benchmark_cost_cents`. The other variant is observational only and is used in reporting and in renewal analysis. Identical populations can yield different benchmarks under the two variants because the underlying score sets differ.

### 3.7. Claims, Cost Measurement, and the Withhold Pool

A `ClaimsProcessor` ingests a `ClaimRecord` by supplying the `performance_year_id`, the `member_id`, a payer-side `claim_ref` unique within the year, a `service_date`, and a strictly positive `paid_amount_cents`. The `service_date` must lie on or after the year's `period_start` and strictly before its `period_end` (`ERR_CLAIM_OUTSIDE_PERIOD`). A claim's `claim_status` is created as `RECEIVED`. From `RECEIVED` the processor may mark it paid (`RECEIVED → PAID`), which stamps `paid_on` with the logical clock date, or deny it (`RECEIVED → DENIED`). From `PAID` the processor may void it (`PAID → VOIDED`) provided the year is not in `SETTLED` or `CLOSED` (`ERR_YEAR_LOCKED`).

Cost measurement is recomputed at begin-measurement, at every claim mark-paid or void, and at settlement finalize or recalculate. The input set is the year's claims in `PAID` status whose `service_date` lies within the half-open year window and whose `member_id` belongs to the attributed population (that is, the member has a `CONFIRMED` record in the locked run). Claims in `RECEIVED`, `DENIED`, or `VOIDED` never count; claims of unattributed or excluded members never count. For each attributed member, the allowed cost is the lesser of the sum of that member's `paid_amount_cents` over the input set and the contract's `stop_loss_cents`. The year's `actual_cost_cents` is the sum of per-member allowed costs.

The withhold pool is computed over the same claim set, evaluated **before** stop-loss truncation. For each claim in the set, the per-claim withhold is the claim's `paid_amount_cents` multiplied by the contract's `withhold_rate_bp` and divided by 10000, rounded half-up to a whole cent. The year's `withhold_pool_cents` is the sum of these per-claim amounts. Rounding is pinned at the per-claim level; sum-then-round is forbidden.

A claim mark-paid that occurs when the year is past `MEASURING` (that is, in `RECONCILING` or later) recomputes both `actual_cost_cents` and `withhold_pool_cents`, transitions every `PUBLISHED` `InterimReport` of the year to `STALE`, and sets `needs_recompute` on the year's settlement when in `PROVISIONAL` or `FINALIZED`. A claim void triggers the same three-link cascade — recompute the two year totals, stale the published interim reports, and flag the settlement.

### 3.8. Quality Measure Reporting and Scoring

A `QualityAnalyst` reports a `QualityMeasureResult` by supplying the `performance_year_id`, a `measure_code` that must exist in the year's contract `quality_measures` catalog (`ERR_UNKNOWN_MEASURE_CODE`), a `numerator_count`, and a `denominator_count`. The numerator must not exceed the denominator (`ERR_NUMERATOR_EXCEEDS_DENOMINATOR`), and the denominator must be at least 1 by the time the result is validated (`ERR_EMPTY_DENOMINATOR`). At most one non-`EXCLUDED` result exists per (year, `measure_code`); a duplicate is rejected with `ERR_DUPLICATE_MEASURE_RESULT`. A result's `result_status` is created as `REPORTED`.

Validation (`REPORTED → VALIDATED`) computes two derived fields. The `rate_bp` is the result's `numerator_count` multiplied by 10000 and divided by `denominator_count`, rounded half-up to a whole basis point. The `achievement_points` is the count of the measure's nine decile thresholds from the contract catalog that the `rate_bp` meets or exceeds — an integer from 0 to 9, with the comparison pinned as greater-than-or-equal. From `VALIDATED` the analyst may return the result for correction (`VALIDATED → REPORTED`), which clears `rate_bp` and `achievement_points` back to null; this is permitted while the year is in `SETUP`, `ATTRIBUTION_OPEN`, `ATTRIBUTION_LOCKED`, or `MEASURING` (`ERR_YEAR_LOCKED` once it has advanced past those). Also from `VALIDATED`, the analyst may lock the result (`VALIDATED → LOCKED`), permitted while the year is in `ATTRIBUTION_OPEN`, `ATTRIBUTION_LOCKED`, or `MEASURING` (`ERR_YEAR_LOCKED` outside that window). Exclusion is a terminal action available from any of `REPORTED`, `VALIDATED`, or `LOCKED` (transitions `REPORTED → EXCLUDED`, `VALIDATED → EXCLUDED`, and `LOCKED → EXCLUDED`), provided the year is not in `SETTLED` or `CLOSED` (`ERR_YEAR_LOCKED`). Excluding a `LOCKED` result additionally flags the year's settlement with `needs_recompute` when in `PROVISIONAL` or `FINALIZED`, because the composite on which the settlement was computed may now be stale; exclusion from `REPORTED` or `VALIDATED` applies the same flag for consistency.

### 3.9. Interim Reports and Reserve Accrual

During measurement, an `ActuaryAnalyst` publishes `InterimReport` estimates so that finance can accrue a reserve against the likely final settlement. Creation requires the analyst to supply the `performance_year_id` and a `months_elapsed` between 1 and 11 inclusive; the request is OCC-guarded against the year via `expected_performance_year_version` per §2.7. A new report's `report_status` is created as `DRAFT`, the report is assigned a `report_seq` one higher than the previous report of the year (starting at 1), and its creation supersedes any prior `DRAFT` report of the same year (that report moves `DRAFT → SUPERSEDED`).

Each report carries two estimate variants side by side, computed from the same year-to-date paid total. The YTD paid total is the sum of `paid_amount_cents` over the year's `PAID` claims whose `paid_on` is on or before the logical clock date and whose member is attributed per the currently locked run. The **annualization** variant, stored on `est_actual_annualization_cents`, is the YTD total multiplied by 12 and divided by `months_elapsed`, rounded half-up. The **completion-factor** variant, stored on `est_actual_completion_cents`, is the YTD total multiplied by 1000 and divided by a per-month completion factor in milli, rounded half-up; the completion factors by month are: 150 for month 1, 320 for month 2, 480 for month 3, 620 for month 4, 740 for month 5, 850 for month 6, 910 for month 7, 950 for month 8, 970 for month 9, 985 for month 10, and 995 for month 11. The contract's `estimate_method` selects which of the two variants is authoritative: `ANNUALIZATION` selects the annualization variant, `COMPLETION_FACTOR` selects the completion-factor variant. Identical YTD data yields different estimates under the two variants.

The selected estimate is then fed through the same shared-savings-and-loss logic that §3.10 defines, with the benchmark taken from the year's current `benchmark_cost_cents` and the actual taken from the estimated figure. The quality gate multiplier is applied using the **interim** variant of the composite, which includes results in `VALIDATED` as well as `LOCKED`. The estimated net payable is the round-half-up of shared savings times the multiplier divided by 10000, plus the round-half-up of the YTD withhold pool times the multiplier divided by 10000, minus shared losses; this figure is stored on `est_net_payable_cents`. The reserve accrual, stored on `reserve_accrual_cents`, is the round-half-up of the positive part of the estimated net payable multiplied by `months_elapsed` and divided by 12. If the estimated net payable is zero or negative, the reserve accrual is zero.

Publication (`DRAFT → PUBLISHED`) is permitted only while the year is in `MEASURING` or `RECONCILING` (`ERR_YEAR_NOT_MEASURING`). Publishing supersedes any other `PUBLISHED` report of the year (that report moves `PUBLISHED → SUPERSEDED`), posts the new report's `reserve_accrual_cents` onto the year's `accrued_reserve_cents`, and stamps `published_on` with the logical clock date. The stale transition (`PUBLISHED → STALE`) is system-driven and fires whenever the year rollups mutate per §2.10; the reserve accrual on the year is not retroactively adjusted by staleness and persists until a newer report publishes or the year settles.

### 3.10. Settlement Computation and Finalization

Once the year is in `RECONCILING`, a `SettlementOfficer` creates a `Settlement` against it by supplying the `performance_year_id`. Creating a settlement against a year not in `RECONCILING` is rejected with `ERR_YEAR_NOT_RECONCILING`. At most one non-`VOID` settlement exists per year (`ERR_SETTLEMENT_EXISTS`). The settlement's `settlement_status` is created as `PROVISIONAL`, and the settlement is assigned `settlement_seq` starting at 1 for the first non-`VOID` settlement of the year.

The settlement computation is a pinned eight-step chain, evaluated in order. First the year rollups are read: `benchmark_cost_cents`, `actual_cost_cents`, and `withhold_pool_cents`. Second, shared savings and shared losses are derived. The gross, stored on `gross_savings_cents`, is `benchmark_cost_cents` minus `actual_cost_cents` and may be negative. The savings rate in basis points, stored on `savings_rate_bp`, is the gross multiplied by 10000 and divided by `benchmark_cost_cents`, truncated toward zero. As a guard reachable only via interim estimates computed before attribution lock, if `benchmark_cost_cents` is zero the rate is zero and both shared savings and shared losses are zero. When gross is non-negative, the savings branch applies: if `savings_rate_bp` is greater than or equal to the contract's `min_savings_rate_bp`, the uncapped shared savings is the round-half-up of gross multiplied by `shared_savings_rate_bp` and divided by 10000, and the cap is the round-half-up of `benchmark_cost_cents` multiplied by `savings_cap_bp` and divided by 10000; `shared_savings_cents` is the lesser of the two, with the minimum applied **after** both sides have been rounded. If the rate falls below the MSR, `shared_savings_cents` is zero. `shared_losses_cents` is zero on this branch. When gross is negative, the loss branch applies and `shared_savings_cents` is zero; if the contract's `risk_track` is `TWO_SIDED` and the `savings_rate_bp` is less than or equal to the negation of the contract's `min_loss_rate_bp`, the uncapped shared loss is the round-half-up of the absolute gross multiplied by `shared_loss_rate_bp` and divided by 10000, the cap is the round-half-up of `benchmark_cost_cents` multiplied by `loss_cap_bp` and divided by 10000, and `shared_losses_cents` is the lesser of the two. Otherwise `shared_losses_cents` is zero. Between the MSR and the negative MLR lies the zero corridor in which neither savings nor losses are paid.

Third, the **official** quality composite is computed over the year's `LOCKED` quality results. The numerator is the sum over each result of its `achievement_points` multiplied by the `weight_bp` of its measure in the contract catalog; the denominator is the sum of the `weight_bp` values over the same results. If the denominator is zero — no locked results, or all weights somehow zero — the composite is zero. Otherwise the composite, stored on `quality_composite_points`, is the round-half-up of the numerator multiplied by 100 and divided by nine times the denominator, yielding an integer in 0..100. The official variant uses only `LOCKED` results; the interim variant used by §3.9 includes both `VALIDATED` and `LOCKED` results, so identical measure data can yield a different composite under the two variants whenever a result is validated but not yet locked.

Fourth, the quality gate multiplier is derived from the composite. If the composite is greater than or equal to the contract's `quality_gate_excellence_points`, the multiplier is 10000. If the composite is greater than or equal to the `quality_gate_floor_points` but below excellence, the multiplier is 5000 plus the round-half-up of the composite-minus-floor, multiplied by 5000, divided by the excellence-minus-floor gap. If the composite is below the floor, the multiplier is zero. Boundary behavior is pinned: a composite exactly equal to the floor yields the sliding branch and a multiplier of 5000; a composite exactly equal to excellence yields 10000; a composite one below the floor yields zero. The multiplier is stored on `quality_multiplier_bp`.

Fifth, `quality_adjusted_savings_cents` is the round-half-up of `shared_savings_cents` multiplied by `quality_multiplier_bp` and divided by 10000. Sixth, `withhold_released_cents` is the round-half-up of `withhold_pool_cents` multiplied by `quality_multiplier_bp` and divided by 10000, and `withhold_forfeited_cents` is `withhold_pool_cents` minus `withhold_released_cents`. Seventh, `net_payable_cents` is `quality_adjusted_savings_cents` plus `withhold_released_cents` minus `shared_losses_cents` and may be negative. Eighth, `undistributed_balance_cents` is the positive part of `net_payable_cents` minus the sum of `amount_cents` over the settlement's remittances in `SCHEDULED`, `APPROVED`, or `PAID`.

Finalization (`PROVISIONAL → FINALIZED`) is performed by a `SettlementOfficer` and is gated by two preconditions: the logical clock date must be at or after the year's `period_end` plus the reconciliation runout (`ERR_RECONCILIATION_RUNOUT_INCOMPLETE`), and `needs_recompute` must be `false` (`ERR_SETTLEMENT_STALE` while it is true). Finalization recomputes every computed field from current data using the **final** variant — actuals only, with no completion factor or annualization applied — and stamps `finalized_on` with the logical clock date and `finalized_by_user_id` with the calling officer's `X-User-ID`. The latter is the segregation-of-duties anchor consulted at dispute resolve.

A `PROVISIONAL` settlement whose `needs_recompute` is true can be brought current via the recalculate action, which performs a full recompute against current data, clears `needs_recompute` to `false`, and leaves the settlement in `PROVISIONAL` with `settlement_seq` unchanged. Recalculate is the only way to clear the flag; finalize refuses to run while it is set.

From `FINALIZED` the settlement advances in one of two ways. If no dispute is filed inside the dispute window, an officer may authorize distribution (`FINALIZED → AUTHORIZED`) once the logical clock date is strictly greater than `finalized_on` plus the dispute window (`ERR_DISPUTE_WINDOW_OPEN`); §3.12 covers the remittance waterfall this triggers. If a dispute is filed inside the window, the settlement moves `FINALIZED → DISPUTED`; §3.11 covers that flow.

### 3.11. Disputes and Recalculation

A `PracticeGroupRep` whose group owns the contract behind a finalized settlement may file a `SettlementDispute` by supplying a `dispute_ref` unique within the settlement, a `reason_code` drawn from `ATTRIBUTION_ERROR`, `CLAIMS_MISSING`, `RISK_SCORE_ERROR`, `QUALITY_DATA_ERROR`, or `BENCHMARK_ERROR`, and a strictly positive `claimed_adjustment_cents`. The new dispute's `settlement_id` is the id of the targeted settlement. Filing requires the settlement to be in `FINALIZED` (`ERR_SETTLEMENT_NOT_FINAL`) and requires the logical clock date to be on or before `finalized_on` plus the dispute window (`ERR_DISPUTE_WINDOW_CLOSED`). Filing transitions the settlement `FINALIZED → DISPUTED` and stamps `filed_on` with the logical clock date. The dispute's `dispute_status` is created as `FILED`.

A `DisputeAdjudicator` begins review (`FILED → UNDER_REVIEW`), which stamps `review_started_on`. From `UNDER_REVIEW` the adjudicator resolves the dispute by supplying an `outcome` of `UPHELD` or `OVERRULED`. Resolution is gated by two preconditions applied in cascade order: the logical clock date must be on or before `filed_on` plus the dispute-resolution window (`ERR_DISPUTE_RESOLUTION_WINDOW_ELAPSED`), and the caller's `X-User-ID` must differ from the settlement's `finalized_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). The resolve transition writes `resolved_on` from the clock, writes `resolved_by_user_id` from the header, and writes `resolution_outcome` to the supplied outcome.

The two outcomes diverge sharply on the settlement side. An `UPHELD` resolution (`UNDER_REVIEW → UPHELD`) cascades the settlement `DISPUTED → RECALCULATING` and then, in the same request, automatically recalculates the settlement from the corrected data, moving it `RECALCULATING → PROVISIONAL` with all computed fields refreshed, `settlement_seq` unchanged, and `needs_recompute` cleared to `false`. An `OVERRULED` resolution (`UNDER_REVIEW → OVERRULED`) cascades the settlement `DISPUTED → FINALIZED` with amounts unchanged.

Two non-resolution exits exist. The owning `PracticeGroupRep` may withdraw (`FILED → WITHDRAWN` or `UNDER_REVIEW → WITHDRAWN`); the scope check of §2.1 enforces ownership (`ERR_FORBIDDEN_GROUP_SCOPE`), and withdrawal cascades the settlement `DISPUTED → FINALIZED`. A `DisputeAdjudicator` may expire the dispute (`FILED → EXPIRED` or `UNDER_REVIEW → EXPIRED`) once the logical clock date is strictly greater than `filed_on` plus the resolution window (`ERR_DISPUTE_NOT_EXPIRABLE`); expiry likewise cascades the settlement `DISPUTED → FINALIZED`. When a dispute exits via `OVERRULED`, `WITHDRAWN`, or `EXPIRED`, the settlement returns to `FINALIZED` with `finalized_on` unchanged — the original dispute-window anchor is preserved, so the mark-settled and authorize-distribution windows continue to be measured from the first finalization, not from any dispute resolution.

### 3.12. Distribution Remittances and the Largest-Remainder Waterfall

Authorize-distribution (`FINALIZED → AUTHORIZED`) creates one `DistributionRemittance` per practice that has at least one cent allocated. The allocation pool is the positive part of `net_payable_cents`. The practice weights are computed from the population of the locked run: for each distinct `practice_id` appearing on a `CONFIRMED` record, the practice's weight is the sum of `member_months` over its `CONFIRMED` records; the total weight is the year's `total_member_months`. If the pool is zero or the total weight is zero, no remittances are created. Otherwise, for each practice, the exact share is the pool multiplied by the practice's weight and divided by the total weight; the practice's `amount_cents` is the floor of that exact share. The remainder — the pool minus the sum of the floored amounts, which is always non-negative and strictly less than the number of practices — is then distributed as one additional cent per practice, ordered by descending fractional part (exact share minus floored share), with ties broken by ascending `Practice.created_at` and never by id. Each practice receives at most one additional cent. Conservation holds: the sum of allocated `amount_cents` equals the pool exactly. Practices whose allocated amount is zero receive no remittance.

Each remittance's `remittance_status` is created as `SCHEDULED`, with its `practice_member_months` weight recorded. The authorize-distribution side effect sets `undistributed_balance_cents` to the positive part of `net_payable_cents` minus the sum of remittance amounts. A special case: if `net_payable_cents` is zero or negative, no remittances are created and the settlement transitions directly from `FINALIZED` to `DISTRIBUTED` without pausing in `AUTHORIZED`.

A `PaymentOps` operator approves a remittance (`SCHEDULED → APPROVED`); approval requires the settlement to be in `AUTHORIZED` (`ERR_SETTLEMENT_NOT_AUTHORIZED`) and the practice's owning group to be in `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`). From `APPROVED` the operator may mark it paid (`APPROVED → PAID`), which stamps `paid_on` from the logical clock; when every remittance of the settlement has reached `PAID`, the settlement automatically transitions `AUTHORIZED → DISTRIBUTED`. Alternatively, the operator may return a remittance (`APPROVED → RETURNED`); the `RETURNED` amount is released back into the settlement's `undistributed_balance_cents`, which is recomputed. A returned remittance may be requeued (`RETURNED → SCHEDULED`), which again requires the settlement to be in `AUTHORIZED` (`ERR_SETTLEMENT_NOT_AUTHORIZED`) and again recomputes `undistributed_balance_cents`. Return-then-requeue is the compensating invariant that lets a payment operation recover from a bad instruction without disturbing the rest of the distribution.

### 3.13. Renewal Analysis and Contract Renewal

Once a contract has at least one closed year and has itself reached `EXPIRED`, a `ContractManager` creates a `RenewalAnalysis` against it. Creation requires the contract to be in `EXPIRED` (attempting to create one against a contract in another status is rejected with `ERR_INVALID_STATE_TRANSITION`) and requires at least one `CLOSED` performance year on the contract (`ERR_YEARS_NOT_CLOSED` if none). The request is OCC-guarded against the contract via `expected_contract_version` per §2.7. The new analysis's `analysis_status` is created as `DRAFT`, with `analysis_seq` assigned one higher than the previous analysis of the contract (starting at 1); creating a new analysis supersedes any prior `DRAFT` analysis of the same contract (`DRAFT → SUPERSEDED`).

Completion (`DRAFT → COMPLETE`) computes the recommendation. Let the contract's closed years be ordered by `year_label`; the earliest is the one with the smallest `year_label` and the latest is the one with the largest. The `realized_savings_rate_bp` is computed across all closed years: the sum of `benchmark_cost_cents` minus the sum of `actual_cost_cents`, multiplied by 10000, divided by the sum of `benchmark_cost_cents`, and truncated toward zero. The `quality_trend_points` is the official composite stored on the latest closed year's settlement minus the official composite stored on the earliest closed year's settlement. The `risk_growth_milli` is the latest closed year's `risk_adjustment_factor_milli` minus the earliest closed year's `risk_adjustment_factor_milli`. The `recommendation` is then derived: if the realized savings rate is at least 100 basis points **and** the quality trend has not dropped by more than 5 points (that is, `quality_trend_points` is greater than or equal to -5), the recommendation is `RENEW_AS_IS`. Otherwise, if the realized savings rate is at least zero, the recommendation is `RENEW_RENEGOTIATE`. Otherwise the recommendation is `DO_NOT_RENEW`. Both comparisons are pinned as greater-than-or-equal.

A `ContractManager` renews an expired contract (`EXPIRED → RENEWED`) only when a `COMPLETE` analysis exists for that contract whose `recommendation` is not `DO_NOT_RENEW` (`ERR_RENEWAL_NOT_RECOMMENDED` otherwise). Renewal creates a successor contract in `DRAFT` that copies all terms of the expiring contract, sets its `contract_ref` to the original `contract_ref` with the suffix `-R` appended, and sets `renewed_from_contract_id` to the id of the contract being renewed. The response body is the newly created successor, not the renewed original, and the create returns 201.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`. Operations that modify an existing resource, including state transitions and cascade-triggering actions, return `200 OK`. The clock endpoint returns `200 OK`. Reads return `200 OK`. All responses use the envelope defined in §2.2 and list endpoints honor the pagination contract of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vbc/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z) | PayerAdmin |
| POST | `/vbc/programs` | Create a program in DRAFT | PayerAdmin |
| GET | `/vbc/programs` | List programs | Any |
| GET | `/vbc/programs/{id}` | Get a program | Any |
| POST | `/vbc/programs/{id}/activate` | Activate a program (DRAFT to ACTIVE) | PayerAdmin |
| POST | `/vbc/programs/{id}/archive` | Archive a program (ACTIVE to ARCHIVED) | PayerAdmin |
| POST | `/vbc/practice-groups` | Create a practice group in ACTIVE | PayerAdmin |
| GET | `/vbc/practice-groups` | List practice groups | Any |
| GET | `/vbc/practice-groups/{id}` | Get a practice group | Any |
| POST | `/vbc/practice-groups/{id}/suspend` | Suspend a group (ACTIVE to SUSPENDED) | PayerAdmin |
| POST | `/vbc/practice-groups/{id}/reinstate` | Reinstate a group (SUSPENDED to ACTIVE) | PayerAdmin |
| POST | `/vbc/practice-groups/{id}/terminate` | Terminate a group (ACTIVE or SUSPENDED to TERMINATED) | PayerAdmin |
| POST | `/vbc/practices` | Create a practice in ACTIVE | PayerAdmin |
| GET | `/vbc/practices` | List practices | Any |
| GET | `/vbc/practices/{id}` | Get a practice | Any |
| POST | `/vbc/practices/{id}/deactivate` | Deactivate a practice (ACTIVE to INACTIVE) | PayerAdmin |
| POST | `/vbc/members` | Create a member in ELIGIBLE | PayerAdmin |
| GET | `/vbc/members` | List members | Any |
| GET | `/vbc/members/{id}` | Get a member | Any |
| POST | `/vbc/members/{id}/disenroll` | Disenroll a member (ELIGIBLE to DISENROLLED) | PayerAdmin |
| POST | `/vbc/eligibility-spans` | Create an eligibility span in ACTIVE (closed interval) | PayerAdmin |
| GET | `/vbc/eligibility-spans` | List eligibility spans | Any |
| GET | `/vbc/eligibility-spans/{id}` | Get an eligibility span | Any |
| POST | `/vbc/eligibility-spans/{id}/close` | Close a span (ACTIVE to CLOSED) | PayerAdmin |
| POST | `/vbc/contracts` | Create a contract in DRAFT | ContractManager |
| GET | `/vbc/contracts` | List contracts | Any |
| GET | `/vbc/contracts/{id}` | Get a contract | Any |
| POST | `/vbc/contracts/{id}/activate` | Activate a contract and pin risk_model (DRAFT to ACTIVE) | ContractManager |
| POST | `/vbc/contracts/{id}/expire` | Expire a contract after term end with all years CLOSED | ContractManager |
| POST | `/vbc/contracts/{id}/terminate` | Terminate a contract with no in-flight years | ContractManager |
| POST | `/vbc/contracts/{id}/renew` | Renew an expired contract; returns the DRAFT successor | ContractManager |
| POST | `/vbc/performance-years` | Create a performance year in SETUP | PayerAdmin |
| GET | `/vbc/performance-years` | List performance years | Any |
| GET | `/vbc/performance-years/{id}` | Get a performance year | Any |
| POST | `/vbc/performance-years/{id}/open-attribution` | SETUP to ATTRIBUTION_OPEN | PayerAdmin |
| POST | `/vbc/performance-years/{id}/lock-attribution` | ATTRIBUTION_OPEN to ATTRIBUTION_LOCKED; pins run, computes rollups | PayerAdmin |
| POST | `/vbc/performance-years/{id}/begin-measurement` | ATTRIBUTION_LOCKED to MEASURING; computes cost and withhold pool | PayerAdmin |
| POST | `/vbc/performance-years/{id}/begin-reconciliation` | MEASURING to RECONCILING after period end with quality locked and non-empty population | PayerAdmin |
| POST | `/vbc/performance-years/{id}/reopen-attribution` | RECONCILING to ATTRIBUTION_OPEN; supersedes run, voids settlement, resets rollups | PayerAdmin |
| POST | `/vbc/performance-years/{id}/mark-settled` | RECONCILING to SETTLED after dispute window; releases reserve | SettlementOfficer |
| POST | `/vbc/performance-years/{id}/close` | SETTLED to CLOSED once settlement DISTRIBUTED | Auditor |
| POST | `/vbc/performance-years/{id}/attribution-runs` | Create an attribution run in DRAFT; supersedes prior DRAFT/COMPUTED runs; OCC-guarded | AttributionAnalyst |
| GET | `/vbc/attribution-runs` | List attribution runs | Any |
| GET | `/vbc/attribution-runs/{id}` | Get an attribution run | Any |
| POST | `/vbc/attribution-runs/{id}/compute` | DRAFT to COMPUTED; computes member_months, confirms records | AttributionAnalyst |
| POST | `/vbc/attribution-runs/{id}/lock` | COMPUTED to LOCKED (year must be ATTRIBUTION_OPEN; one LOCKED per year) | AttributionAnalyst |
| POST | `/vbc/attribution-runs/{id}/records` | Add an attribution record in PROVISIONAL to a DRAFT run | AttributionAnalyst |
| GET | `/vbc/attribution-records` | List attribution records | Any |
| GET | `/vbc/attribution-records/{id}` | Get an attribution record | Any |
| POST | `/vbc/attribution-records/{id}/exclude` | CONFIRMED to EXCLUDED; rollups recomputed, settlement flagged | AttributionAnalyst |
| POST | `/vbc/attribution-records/{id}/reinstate` | EXCLUDED to CONFIRMED; rollups recomputed | AttributionAnalyst |
| POST | `/vbc/risk-scores` | Create a risk score in PRELIMINARY; model_used must equal pinned risk_model | ActuaryAnalyst |
| GET | `/vbc/risk-scores` | List risk scores | Any |
| GET | `/vbc/risk-scores/{id}` | Get a risk score | Any |
| POST | `/vbc/risk-scores/{id}/finalize` | PRELIMINARY to FINAL; recomputes year rollups when locked | ActuaryAnalyst |
| POST | `/vbc/risk-scores/{id}/supersede` | PRELIMINARY or FINAL to SUPERSEDED; recomputes rollups | ActuaryAnalyst |
| POST | `/vbc/claims` | Create a claim in RECEIVED; service_date inside the year window | ClaimsProcessor |
| GET | `/vbc/claims` | List claims | Any |
| GET | `/vbc/claims/{id}` | Get a claim | Any |
| POST | `/vbc/claims/{id}/mark-paid` | RECEIVED to PAID; stamps paid_on, recomputes year totals | ClaimsProcessor |
| POST | `/vbc/claims/{id}/deny` | RECEIVED to DENIED | ClaimsProcessor |
| POST | `/vbc/claims/{id}/void` | PAID to VOIDED; cascades to year totals, interim staleness, settlement flag | ClaimsProcessor |
| POST | `/vbc/quality-measure-results` | Report a measure result in REPORTED | QualityAnalyst |
| GET | `/vbc/quality-measure-results` | List quality measure results | Any |
| GET | `/vbc/quality-measure-results/{id}` | Get a quality measure result | Any |
| POST | `/vbc/quality-measure-results/{id}/validate` | REPORTED to VALIDATED; computes rate_bp and achievement_points | QualityAnalyst |
| POST | `/vbc/quality-measure-results/{id}/return-for-correction` | VALIDATED to REPORTED; clears computed scoring | QualityAnalyst |
| POST | `/vbc/quality-measure-results/{id}/lock` | VALIDATED to LOCKED (year must be pre-reconciliation) | QualityAnalyst |
| POST | `/vbc/quality-measure-results/{id}/exclude` | REPORTED/VALIDATED/LOCKED to EXCLUDED while year not settled | QualityAnalyst |
| POST | `/vbc/interim-reports` | Create an interim report in DRAFT; supersedes prior DRAFT; OCC-guarded; computes both estimate variants and reserve accrual | ActuaryAnalyst |
| GET | `/vbc/interim-reports` | List interim reports | Any |
| GET | `/vbc/interim-reports/{id}` | Get an interim report | Any |
| POST | `/vbc/interim-reports/{id}/publish` | DRAFT to PUBLISHED; supersedes prior PUBLISHED; posts reserve to the year | ActuaryAnalyst |
| POST | `/vbc/settlements` | Create a settlement in PROVISIONAL for a RECONCILING year; computes the full chain | SettlementOfficer |
| GET | `/vbc/settlements` | List settlements | Any |
| GET | `/vbc/settlements/{id}` | Get a settlement (PracticeGroupRep scoped to own group) | Any |
| POST | `/vbc/settlements/{id}/finalize` | PROVISIONAL to FINALIZED after runout; recomputes from current data | SettlementOfficer |
| POST | `/vbc/settlements/{id}/recalculate` | Recompute a PROVISIONAL settlement with needs_recompute set; clears the flag | SettlementOfficer |
| POST | `/vbc/settlements/{id}/authorize-distribution` | FINALIZED to AUTHORIZED after the dispute window; creates remittances | SettlementOfficer |
| POST | `/vbc/settlements/{id}/disputes` | File a dispute in FILED on a FINALIZED settlement within the dispute window | PracticeGroupRep |
| GET | `/vbc/settlement-disputes` | List disputes | Any |
| GET | `/vbc/settlement-disputes/{id}` | Get a dispute | Any |
| POST | `/vbc/settlement-disputes/{id}/begin-review` | FILED to UNDER_REVIEW | DisputeAdjudicator |
| POST | `/vbc/settlement-disputes/{id}/resolve` | UNDER_REVIEW to UPHELD or OVERRULED within the resolution window; segregation of duties enforced | DisputeAdjudicator |
| POST | `/vbc/settlement-disputes/{id}/withdraw` | FILED or UNDER_REVIEW to WITHDRAWN by the owning group | PracticeGroupRep |
| POST | `/vbc/settlement-disputes/{id}/expire` | FILED or UNDER_REVIEW to EXPIRED after the resolution window | DisputeAdjudicator |
| GET | `/vbc/distribution-remittances` | List remittances | Any |
| GET | `/vbc/distribution-remittances/{id}` | Get a remittance | Any |
| POST | `/vbc/distribution-remittances/{id}/approve` | SCHEDULED to APPROVED; group must be ACTIVE | PaymentOps |
| POST | `/vbc/distribution-remittances/{id}/mark-paid` | APPROVED to PAID; settlement to DISTRIBUTED when all paid | PaymentOps |
| POST | `/vbc/distribution-remittances/{id}/return` | APPROVED to RETURNED; amount released back | PaymentOps |
| POST | `/vbc/distribution-remittances/{id}/requeue` | RETURNED to SCHEDULED | PaymentOps |
| POST | `/vbc/contracts/{id}/renewal-analyses` | Create a renewal analysis in DRAFT; contract EXPIRED with at least one CLOSED year; supersedes prior DRAFT; OCC-guarded | ContractManager |
| GET | `/vbc/renewal-analyses` | List renewal analyses | Any |
| GET | `/vbc/renewal-analyses/{id}` | Get a renewal analysis | Any |
| POST | `/vbc/renewal-analyses/{id}/complete` | DRAFT to COMPLETE; computes recommendation | ContractManager |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflow that raises them.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_GROUP_SCOPE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_HAS_OPEN_CONTRACTS` | 409 Conflict |
| `ERR_GROUP_NOT_ACTIVE` | 409 Conflict |
| `ERR_GROUP_HAS_OPEN_CONTRACTS` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_TERM_NOT_ENDED` | 409 Conflict |
| `ERR_YEARS_NOT_CLOSED` | 409 Conflict |
| `ERR_YEARS_IN_FLIGHT` | 409 Conflict |
| `ERR_RENEWAL_NOT_RECOMMENDED` | 409 Conflict |
| `ERR_YEAR_NOT_OPEN` | 409 Conflict |
| `ERR_YEAR_LOCKED` | 409 Conflict |
| `ERR_YEAR_NOT_MEASURING` | 409 Conflict |
| `ERR_YEAR_NOT_RECONCILING` | 409 Conflict |
| `ERR_NO_LOCKED_ATTRIBUTION_RUN` | 409 Conflict |
| `ERR_RUN_NOT_DRAFT` | 409 Conflict |
| `ERR_RUN_NOT_LOCKED` | 409 Conflict |
| `ERR_RUN_ALREADY_LOCKED` | 409 Conflict |
| `ERR_SETTLEMENT_EXISTS` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_FINAL` | 409 Conflict |
| `ERR_SETTLEMENT_STALE` | 409 Conflict |
| `ERR_SETTLEMENT_BEYOND_PROVISIONAL` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_DISTRIBUTED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_RISK_MODEL_MISMATCH` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_OPEN` | 409 Conflict |
| `ERR_DISPUTE_RESOLUTION_WINDOW_ELAPSED` | 409 Conflict |
| `ERR_DISPUTE_NOT_EXPIRABLE` | 409 Conflict |
| `ERR_MEASUREMENT_PERIOD_NOT_ENDED` | 409 Conflict |
| `ERR_QUALITY_RESULTS_UNLOCKED` | 409 Conflict |
| `ERR_RECONCILIATION_RUNOUT_INCOMPLETE` | 409 Conflict |
| `ERR_YEAR_OUTSIDE_TERM` | 409 Conflict |
| `ERR_CLAIM_OUTSIDE_PERIOD` | 409 Conflict |
| `ERR_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_SPAN_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_TIN` | 409 Conflict |
| `ERR_DUPLICATE_NPI` | 409 Conflict |
| `ERR_DUPLICATE_MEMBER_REF` | 409 Conflict |
| `ERR_DUPLICATE_CONTRACT_REF` | 409 Conflict |
| `ERR_DUPLICATE_YEAR_LABEL` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM_REF` | 409 Conflict |
| `ERR_DUPLICATE_RISK_SCORE` | 409 Conflict |
| `ERR_DUPLICATE_MEASURE_RESULT` | 409 Conflict |
| `ERR_UNKNOWN_MEASURE_CODE` | 409 Conflict |
| `ERR_PRACTICE_GROUP_MISMATCH` | 409 Conflict |
| `ERR_PRACTICE_INACTIVE` | 409 Conflict |
| `ERR_MEMBER_PROGRAM_MISMATCH` | 409 Conflict |
| `ERR_MEMBER_DISENROLLED` | 409 Conflict |
| `ERR_MEMBER_NO_ELIGIBLE_MONTHS` | 409 Conflict |
| `ERR_INVALID_RATE_CONFIG` | 422 Unprocessable Entity |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_NUMERATOR_EXCEEDS_DENOMINATOR` | 422 Unprocessable Entity |
| `ERR_EMPTY_DENOMINATOR` | 422 Unprocessable Entity |
| `ERR_EMPTY_POPULATION` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
