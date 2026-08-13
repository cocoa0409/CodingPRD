# Bank Capital Planning API — Product Requirements Document

## 1. Introduction

Bank finance teams operate under continuous supervisory scrutiny: every quarter closes into a call report, every call report fixes the capital ratios that drive prompt-corrective-action classification, and every dollar of dividends or buybacks must be defensible against a forward-looking stress projection. This document specifies the Bank Capital Planning API, the system of record for that entire cycle. The platform computes risk-weighted assets under both the standardized and advanced approaches, assembles the CET1 / Tier 1 / total capital stack with its regulatory caps and amortization haircuts, prepares and amends quarterly call reports with full edit-exception resolution, tracks filing deadlines and lateness, and monitors prompt-corrective-action thresholds as accepted ratios move the bank between capitalization buckets.

On top of that reporting spine, the API governs the discretionary side of capital management. Capital plans carry nine-quarter base-case and stressed projections through board review and supervisory adjudication; stress scenarios translate macroeconomic shocks into projected losses against the bank's live exposure inventory; dividend and buyback requests compete for a strictly computed maximum distributable amount; subordinated debt issuances are planned against a Tier 2 capacity cap; and ICAAP documents are prepared, attested, and filed under explicit segregation of duties between the analysts who prepare, the board members who approve, and the regulators who accept. A logical clock — never wall-clock time — drives every deadline, activation, expiry, and maturity in the system, so that the complete regulatory calendar is reproducible and auditable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two identity headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403); a role value outside the five recognized roles is treated the same way, as an authorization failure rather than a malformed header.

The system recognizes exactly five roles. `SystemOperator` is the operational superuser: it alone creates banks and advances the logical clock, and it can read everything. `CapitalAnalyst` is the bank finance analyst who prepares call reports, drafts capital plans, proposes distributions, manages the sub-debt lifecycle, and prepares ICAAP documentation. `RegulatorReviewer` is the supervisor who accepts call reports and rules on capital plans. `BoardApprover` is the bank board approver who approves capital plans and attests ICAAP documents, serving as the segregation-of-duties counterweight to `CapitalAnalyst`. `ExternalAuditor` is a read-only role for compliance review. All five roles may use every read endpoint; write privileges are enumerated per endpoint in §4.

For each of these roles — `SystemOperator`, `CapitalAnalyst`, `RegulatorReviewer`, `BoardApprover`, and `ExternalAuditor` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `prepared_by_user_id` on a call report or an ICAAP document, or as `board_attested_by_user_id` when a board member attests) and segregation-of-duties rules compare one operator's `X-User-ID` against another's, but it is never compared to any entity's `id`.

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

### 2.3. Pagination and List Filtering

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100; a supplied value outside those bounds is clamped into them rather than rejected, while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). `offset` sets the number of items to skip and defaults to 0, with negative values clamped up to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order with ties broken by insertion order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, list endpoints accept equality filters drawn from the fields of the resource they return. Banks filter by `charter_id` or by `pca_bucket_as_of_period_id` (the reverse-reachability filter from a reporting period back to the banks whose current bucket was set by it). Reporting periods filter by `status` and `period_year`; capital instruments by `instrument_class` and `status`; risk exposures by `exposure_class`, `obligor_grade`, and `reporting_period_id`; call reports by `status`, `reporting_period_id`, and `supersedes_call_report_id`; edit exceptions by `status`, `severity`, and `call_report_id`; stress scenarios by `status`; capital plans by `status`, `plan_year`, `baseline_period_id`, and `stress_scenario_id`; distribution requests by `capital_plan_id`, `reporting_period_id`, `status`, and `distribution_kind`; sub-debt issuances by `status` and `capital_instrument_id`; PCA threshold events by `metric`, `breached`, and `call_report_id`; and ICAAP documents by `status`, `document_year`, and `governing_capital_plan_id`. Filter values match on string equality against the field's serialized form — boolean fields such as `breached` match the strings `true`/`false` case-insensitively — and a filter never matches a resource whose field is null. The flat, top-level list endpoints carry each resource's full filter set and additionally accept `bank_id` so that every child collection remains discoverable from its owning bank — except the flat edit-exceptions list, which does not accept `bank_id`, edit exceptions being reachable through their call report rather than the bank directly. Nested and bank-scoped lists omit filters already pinned by the path, and certain reference filters are recognized only by the flat lists: `supersedes_call_report_id` on call reports, `baseline_period_id` and `stress_scenario_id` on capital plans, `capital_instrument_id` on sub-debt issuances, `call_report_id` on PCA threshold events, and `governing_capital_plan_id` on ICAAP documents; `obligor_grade` is recognized on the period-nested and flat exposure lists but not on the bank-scoped exposure list.

### 2.4. Common Resource Properties

Every primary resource — banks, reporting periods, capital instruments, risk exposures, call reports, edit exceptions, capital plans, stress scenarios, distribution requests, sub-debt issuances, and ICAAP documents — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits taken from the server wall clock at write time — the logical clock of §2.5 governs business instants such as `submitted_at` and `accepted_at`, not these audit timestamps — and `updated_at` follows the same format and is refreshed on every modification. The `version` field is an integer that starts at 1 and increments by one on every mutation of the resource; clients read it to drive optimistic concurrency where §2.8 applies. Derived-field maintenance counts as mutation: when the server recomputes a bank's `mdba_cents`, refreshes a plan's baseline snapshot, or cascades a PCA bucket change, the owning entity's `updated_at` moves and its `version` increments. The lone exception is a bare supervisory-status escalation: moving a bank to `UNDER_LETTER` for lateness refreshes its `updated_at` without incrementing its `version`.

One resource is deliberately lighter. A PCA threshold event is an immutable audit record written at the moment a threshold check fires; it carries `id` and `created_at` only — `updated_at` and `version` are absent, because an event is never modified after insertion.

### 2.5. The Logical Clock and Time-Driven Transitions

The system runs on a logical clock rather than wall-clock time. Before any operator interaction, the clock reads 2026-08-01T00:00:00Z. A `SystemOperator` advances it through a clock-driving capability that accepts a `to_iso8601` timestamp — a request missing `to_iso8601` or carrying an unparseable value is rejected with `ERR_INVALID_REQUEST` (HTTP 400); each supplied instant must be monotonically non-decreasing relative to the current logical time, an earlier instant being rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 409), and the clock never falls back to wall-clock once set. Reading the clock returns the current instant as `current_utc`, and the advance endpoint answers with the same `current_utc` object after applying the advance.

Advancing the clock fires every time-triggered transition whose moment has arrived: reporting periods move from `OPEN` to `FILING_DUE`, approved capital plans activate to `EFFECTIVE` on the first day of their plan year, approved-but-unpaid distributions lapse to `EXPIRED` once their payment window closes, and subordinated-debt instruments mature from `OUTSTANDING` to `MATURED`. The same advance recomputes every time-derived value — the `late_filing` flag on reporting periods, the bank's `supervisory_status`, and each instrument's amortization haircut — so that deadlines, escalations, and decays are all functions of one authoritative clock.

### 2.6. Monetary Units, Basis Points, and Rounding Conventions

All monetary amounts are carried as integer numbers of cents; fields such as `outstanding_amount_cents` and `exposure_at_default_cents` never hold fractional values. Rates, ratios, haircuts, and shocks are carried as integer basis points, where 10000 basis points equal 100 percent.

Three rounding disciplines recur throughout the computations in §3. First, aggregation is per-line, then sum: each exposure line, each instrument line, and each projected loss is rounded down — floored — to a whole cent before any summation, and division is never deferred to the aggregate. Second, cap arithmetic floors its intermediate results: the Additional Tier 1 cap, both Tier 2 caps, and the Tier 2 headroom computation each land on integer cents by rounding down. Third, every ratio is floored to integer basis points, and a ratio whose denominator is zero is null rather than zero. Durations measured in years are bucketed using a 365.25-day year, with the quotient rounded down to a whole year.

### 2.7. Prompt Corrective Action Buckets and Supervisory Posture

Every bank is classified into one of five prompt-corrective-action buckets, ordered from strongest to weakest: `WELL_CAPITALIZED`, `ADEQUATELY_CAPITALIZED`, `UNDERCAPITALIZED`, `SIGNIFICANTLY_UNDERCAPITALIZED`, and `CRITICALLY_UNDERCAPITALIZED`. The bank's `pca_bucket` is derived from the four ratios on its most recently accepted call report, and classification is by inclusive lower bound — a ratio sitting exactly on a threshold earns the higher bucket. For the CET1 ratio, at least 650 basis points is `WELL_CAPITALIZED`, at least 450 is `ADEQUATELY_CAPITALIZED`, at least 400 is `UNDERCAPITALIZED`, at least 300 is `SIGNIFICANTLY_UNDERCAPITALIZED`, and anything below 300 is `CRITICALLY_UNDERCAPITALIZED`. For the Tier 1 ratio the four floors are 800, 600, 500, and 400 basis points respectively. For the total capital ratio they are 1000, 800, 700, and 600. For the leverage ratio they are 500, 400, 350, and 300. A null ratio — possible only when its denominator was zero on the accepted report — classifies as `CRITICALLY_UNDERCAPITALIZED` for bucket purposes. The bank's bucket is the strictest — weakest — of the four metric classifications, and the bank records which period's accepted report set the current bucket in `pca_bucket_as_of_period_id`, null until a first report has been accepted. A newly created bank, having no accepted report, starts at `ADEQUATELY_CAPITALIZED`.

PCA posture is a hard gate on discretionary capital actions. A bank sitting in `UNDERCAPITALIZED`, `SIGNIFICANTLY_UNDERCAPITALIZED`, or `CRITICALLY_UNDERCAPITALIZED` may not approve or execute distributions, may not approve new subordinated-debt issuances, and may not call or redeem subordinated debt; the workflow-specific rejection codes are introduced in §3 alongside each guarded action.

Distinct from the bucket, a bank's `supervisory_status` tracks escalation posture as `NORMAL`, `UNDER_LETTER`, or `UNDER_MOU`. Lateness escalates it: a reporting period that passes its filing deadline without any submitted or accepted call report, or a report filed strictly after its deadline, moves the bank to `UNDER_LETTER` — an escalation that applies only from `NORMAL`, leaving a bank already `UNDER_MOU` untouched. A regulator's objection to a capital plan moves the bank to `UNDER_MOU`.

### 2.8. Bank Versioning and Optimistic Concurrency Control

The bank entity is the contention point of the system: its `version` increments by one on every capacity-affecting mutation, including distribution approvals, executions, withdrawals, and expiries, call-report submission and acceptance, PCA bucket changes, instrument creation, calls, and redemptions, sub-debt approvals and settlements, capital-plan regulatory submission, approval, objection, and amendment cascades, and ICAAP filings. A client that has read a bank and then acts against it may therefore be holding a stale view of `mdba_cents`, `pending_distribution_cents`, the PCA bucket, or the stress capital buffer.

Four write operations guard against exactly that staleness and require the request body to carry `expected_bank_version`, the client's last observed `version` of the parent bank: approving a distribution request, approving a sub-debt issuance, submitting a capital plan to the regulator, and filing an ICAAP document. On each, if the supplied `expected_bank_version` does not equal the bank's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no state changes. A missing or non-integer `expected_bank_version` on these four endpoints is an envelope-level failure rejected with `ERR_INVALID_REQUEST` (HTTP 400). A stale version on distribution approval means the capacity arithmetic behind the approval no longer reflects the bank's committed pool; on sub-debt approval it means the 2-percent-of-RWA cap the client computed against has moved; on regulatory plan submission it means the plan's capacity representation may have been invalidated by an intervening mutation; on ICAAP filing it means the document may describe a plan or baseline the bank no longer occupies. A version field sent to any endpoint other than these four is ignored rather than rejected.

### 2.9. Validation Order and Nested Resource Resolution

Nested URLs are validated left to right. When a path chains several identifiers — bank, then reporting period, then call report, then an edit exception beneath it — the server resolves each identifier in turn, within the scope of its parent, and the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404); deeper identifiers are never examined once an ancestor has failed. The same left-to-right discipline applies to creation and modification under a parent.

When several checks could reject the same request, they are evaluated in a fixed order, so that earlier failures mask later ones. First, the presence and well-formedness of the identity headers (a failure surfaces as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role authorization (`ERR_FORBIDDEN_FOR_ROLE`). Third, left-to-right path resolution (`ERR_NOT_FOUND`). Fourth, cross-bank referential integrity of body-supplied references — a `stress_scenario_id`, `capital_plan_id`, `baseline_period_id`, `reporting_period_id`, or `governing_capital_plan_id` that points at an entity owned by a different bank is rejected with `ERR_CROSS_BANK_REFERENCE` (HTTP 422). Fifth, whether the target entity's current state permits the requested transition (`ERR_INVALID_STATE_TRANSITION`, HTTP 409). Sixth, PCA posture gating. Seventh, segregation of duties (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`). Eighth, uniqueness and exclusivity invariants (`ERR_INVARIANT_VIOLATION`, and `ERR_SCENARIO_LIMIT` for the active-scenario cap). Ninth, temporal windows (`ERR_TEMPORAL_VIOLATION`). Tenth, capacity checks (`ERR_CAPACITY_EXCEEDED` as the generic capacity failure, alongside the workflow-specific codes named in §3). Eleventh, edit-exception gates on report submission and acceptance (`ERR_UNRESOLVED_EDITS`). Twelfth, edit-note requirements (`ERR_EDIT_NOTE_REQUIRED`). Thirteenth, the amendment lock (`ERR_AMENDMENT_LOCKED`). Fourteenth, the plan stress floor (`ERR_PLAN_FAILED_STRESS_FLOOR`). Fifteenth, ICAAP plan finality (`ERR_PLAN_NOT_FINAL`). Sixteenth, ICAAP section completeness (`ERR_SECTION_MISSING`). Seventeenth, risk-parameter bands (`ERR_INVALID_RISK_PARAMETER`). Eighteenth, instrument callability (`ERR_INSTRUMENT_NOT_CALLABLE`). Nineteenth and last, the optimistic-concurrency check of §2.8 (`ERR_STALE_VERSION`).

Independent of position in that ordering, two envelope-level checks accompany every request that carries a body: a malformed body, a missing required field, or a value failing its primitive type check is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and an enum field carrying a value outside its declared set — an unknown `exposure_class`, `period_quarter`, or `instrument_class`, for instance — is rejected with `ERR_INVALID_ENUM_VALUE` (HTTP 422). Body fields the endpoint does not define are ignored, not rejected.

## 3. Business Logic & Workflows

### 3.1. Bank Onboarding and the Capital Instrument Inventory

A `SystemOperator` onboards a bank by registering its `legal_name` and `charter_id`. The charter identifier is unique across banks: an attempt to register a second bank with an already-used `charter_id` is rejected with `ERR_DUPLICATE_CHARTER_ID` (HTTP 409). The registering operator may also declare the bank's `rwa_methodology`; omitted, it defaults to `STANDARDIZED`, while a declaration of `ADVANCED` represents an institution with supervisory approval to use the advanced approaches. From that declaration the server derives `is_advanced_approaches_bank`, true exactly when the methodology is `ADVANCED`, which gates the supplementary leverage ratio and parallel-run rules that attach to advanced-approaches institutions. A new bank begins life with its `pca_bucket` at `ADEQUATELY_CAPITALIZED` (a placeholder until its first accepted call report), `mdba_cents` and `pending_distribution_cents` at zero, `stressed_capital_buffer_bps` null, and `supervisory_status` at `NORMAL`.

Against the bank, a `CapitalAnalyst` builds the capital instrument inventory. Each instrument is created with an `instrument_class` of `CET1`, `AT1`, or `T2`, an `instrument_subtype` of `COMMON_STOCK`, `PREFERRED`, `TRUST_PREFERRED`, `SUBORDINATED_DEBT`, or `OTHER`, a positive `outstanding_amount_cents`, an `issuance_date`, and a `contractual_rate_bps` coupon or dividend rate (zero for common stock). A `maturity_date` is required for `SUBORDINATED_DEBT` and optional otherwise. A non-positive `outstanding_amount_cents`, a negative `contractual_rate_bps`, or a missing `maturity_date` on a `SUBORDINATED_DEBT` instrument is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Instruments enter as `OUTSTANDING`; creation computes the new instrument's own `regulatory_capital_cents`, measuring any sub-debt haircut against the current logical date (the reporting-period-end measurement of the next paragraph applies at call-report preparation), and the bank's `version` increments.

How much of an instrument counts toward regulatory capital depends on its proximity to maturity. For a subordinated-debt instrument, years to maturity are measured from the reporting period's end date using the 365.25-day year, rounded down: with five or more years remaining the instrument counts in full (`t2_haircut_pct` of 0); at four years the haircut is 20 percent; at three years, 40; at two, 60; at one, 80; and inside the final year the instrument counts for nothing, a 100 percent haircut. The resulting `regulatory_capital_cents` is the `outstanding_amount_cents` scaled by the un-haircut portion, floored to integer cents. Instruments that are not subordinated debt always count at their full outstanding amount. Because the haircut decays as the clock moves, the server recomputes it on each call-report preparation and whenever the logical clock carries the bank across a year boundary.

Analysts may call or redeem an eligible instrument. Only `PREFERRED`, `TRUST_PREFERRED`, and `SUBORDINATED_DEBT` subtypes are eligible; a `COMMON_STOCK` instrument can never be called or redeemed, and such an attempt is rejected with `ERR_INSTRUMENT_NOT_CALLABLE` (HTTP 409). For subordinated debt specifically, the bank must be `WELL_CAPITALIZED` or `ADEQUATELY_CAPITALIZED` and the post-call Tier 2 position must still satisfy the Tier 2 cap — otherwise the action fails with `ERR_PCA_BLOCKS_REDEMPTION` (HTTP 409). Calling moves an instrument to `CALLED` and redeeming moves it to `REDEEMED`; the two actions share their eligibility rules and their aftermath: `mdba_cents` is recomputed, the Tier 2 headroom on every open sub-debt proposal is recomputed, and the bank's `version` increments. Subordinated debt also matures on its own: once the logical clock reaches an instrument's `maturity_date`, it moves to `MATURED`, its `outstanding_amount_cents` remains on the books for historical record, and its `regulatory_capital_cents` drops to zero.

### 3.2. Reporting Periods, Risk Capture, and the Filing Calendar

Work on a quarter begins when a `CapitalAnalyst` opens a reporting period for the bank, supplying the `period_end_date` (an ISO calendar date), the `period_year`, and the `period_quarter` — one of `Q1`, `Q2`, `Q3`, or `Q4`. The server immediately computes the filing deadline: `filing_due_at` falls 35 days after the period end for first-, second-, and third-quarter periods and 40 days after for fourth-quarter periods, in both cases at exactly 17:00:00 UTC. The period opens in `OPEN` status.

The clock then works on the period. Once the logical clock reaches 00:00:00 UTC on the day after `period_end_date`, the period moves `OPEN` → `FILING_DUE`; if the clock subsequently passes `filing_due_at` while no call report for the period has reached `SUBMITTED` or `ACCEPTED`, the bank's `supervisory_status` escalates to `UNDER_LETTER`. The period's `late_filing` flag is set to true exactly when the first successful submission of the period's call report occurs strictly after `filing_due_at`.

While a period is `OPEN` or `FILING_DUE`, analysts record its risk exposures — an exposure cannot be recorded against a period in any later state, and such an attempt fails the state check of §2.9. Each exposure row names its `reporting_period_id`; the field may be omitted from the body, in which case the path period owns the row, but when supplied it must resolve to that very path period of the same bank — a value naming another period, another bank's period, or no period at all is rejected with `ERR_CROSS_BANK_REFERENCE`. The row also names its `exposure_class` (`SOVEREIGN`, `CORPORATE`, `RETAIL_MORTGAGE`, `RETAIL_OTHER`, `CRE`, `HVCRE`, `EQUITY`, `SECURITIZATION`, `OPERATIONAL_RISK`, or `MARKET_RISK`), a positive `exposure_at_default_cents`, a `risk_weight_bps` that must be non-negative (no tighter per-class band is enforced), and an `obligor_grade` of `INVESTMENT_GRADE`, `NON_INVESTMENT_GRADE`, or `DEFAULT`. A `collateral_haircut_bps` may be supplied, defaulting to 0, and must lie between 0 and 10000 inclusive. A non-positive exposure amount, a negative risk weight, or an out-of-range haircut is rejected with `ERR_INVALID_RISK_PARAMETER` (HTTP 422).

Every recorded exposure immediately carries two risk-weighted figures. The standardized line value, aggregated into `rwa_cents_standardized`, is the `exposure_at_default_cents` multiplied by the `risk_weight_bps` and divided by 10000, floored to a whole cent; the collateral haircut plays no part in it. The advanced line value, aggregated into `rwa_cents_advanced`, first reduces the exposure by its haircut — multiplying by (10000 minus `collateral_haircut_bps`) over 10000 and flooring — then applies the risk weight over 10000 and finally the advanced-approaches multiplier of 1.06 (that is, 10600 over 10000), flooring the line to a whole cent. Both are computed at record time, for every bank regardless of methodology, so that the later floor comparison and disclosures always have both variants at hand.

### 3.3. Call Report Preparation, Edit Resolution, and Regulatory Acceptance

The call report is the quarterly statement in which exposure lines and capital instruments harden into regulatory ratios. A `CapitalAnalyst` creates a draft report against a period; the first report for a period carries `amendment_sequence` 0, while a report created after the period already has an accepted filing is an amendment whose `amendment_sequence` is one greater than its predecessor and whose `supersedes_call_report_id` points back at it. Draft creation is not gated on the period's status: whatever the newest existing report for the period — draft, accepted, or superseded — a freshly created draft increments its `amendment_sequence` and names it in `supersedes_call_report_id`. Drafts sit in `DRAFT` status until prepared, with both `submitted_at` and `accepted_at` null until their respective transitions occur.

Preparation is the computational heart of the filing cycle. When the analyst prepares a report, the server first requires that at least one risk exposure exists for the period — preparing an exposure-less report is rejected with `ERR_NO_EXPOSURES` (HTTP 409) — and then recomputes the entire report. The capital stack is rebuilt from `OUTSTANDING` instruments: `cet1_cents` is the sum of `regulatory_capital_cents` over the bank's `CET1` rows; the raw Additional Tier 1 sum is capped at 1.5 percent of RWA (computed as `rwa_cents` multiplied by 150 and divided by 10000, floored), and `tier1_cents` is `cet1_cents` plus the smaller of the raw AT1 sum and that cap; the counted Tier 2 amount is the smallest of the raw `T2` sum, 2 percent of RWA (`rwa_cents` times 200 over 10000, floored), and 100 percent of `cet1_cents`, and `total_capital_cents` is `tier1_cents` plus that counted Tier 2. Both RWA variants are aggregated from the period's exposure rows exactly as recorded per line in §3.2 — `rwa_standardized_cents` and `rwa_advanced_cents` — and the report's `rwa_cents` is then selected by methodology: a `STANDARDIZED` bank reports the standardized figure, while an `ADVANCED` bank reports the larger of the two variants, so that advanced RWA can never fall below 100 percent of the standardized figure (the Collins floor). The report's `total_exposure_cents` is the methodology-independent sum of `exposure_at_default_cents` across the period's exposure rows.

From those amounts the ratios fall out. `cet1_ratio_bps` is `cet1_cents` times 10000 divided by `rwa_cents`, floored to integer basis points; `tier1_ratio_bps` and `total_ratio_bps` follow identically from `tier1_cents` and `total_capital_cents`; and `leverage_ratio_bps` is `tier1_cents` times 10000 divided by `total_exposure_cents`, floored. When `rwa_cents` is zero the three capital ratios are null; when `total_exposure_cents` is zero the leverage ratio is null.

Preparation finishes by running the regulator's edit checks against the freshly computed report. If a from-scratch recomputation of RWA diverges from the stored figure by more than one cent, an `EDIT_RWA_MISMATCH` exception is raised at `FATAL` severity. If the bank is advanced-approaches and its `rwa_advanced_cents` falls below its `rwa_standardized_cents`, an `EDIT_FLOOR_VIOLATION` is raised, also `FATAL`. If any ratio disagrees with recomputation by more than one basis point, an `EDIT_RATIO_ROUNDING` exception is raised at `QUALITY` severity. Every failed check becomes an `EditException` row on the report carrying its `edit_code`, its `severity` (`FATAL`, `QUALITY`, or `INFORMATIONAL`), and a human-readable `description`; the report's `edit_failures_open_count` tracks how many exceptions remain open and its `edit_failures_total_count` how many exist in total. Preparation also records the preparing analyst's identity on the report as its `prepared_by_user_id`, and the report moves from `DRAFT` to `PREPARED` — then, automatically and immediately, on to `VALIDATED` if no exceptions are open, or to `EDITS_OUTSTANDING` if any are.

Analysts clear open exceptions in either of two ways, each requiring the report to be in `PREPARED` or `EDITS_OUTSTANDING`. Resolving an exception moves it `OPEN` → `RESOLVED`; explaining one moves it `OPEN` → `EXPLAINED`. Explaining is reserved for lesser findings: a `QUALITY` edit may be explained, an `INFORMATIONAL` edit may be either explained or resolved, but a `FATAL` edit must be resolved — attempting to explain one is rejected as an illegal transition with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Both actions take a `resolution_note`; on resolution the note is mandatory whenever the severity is `FATAL` or `QUALITY` and optional for `INFORMATIONAL`, while an explanation always requires a non-empty note, and a missing note where one is required is rejected with `ERR_EDIT_NOTE_REQUIRED` (HTTP 422). Either action decrements the report's `edit_failures_open_count`, and when the last open exception closes against a report in `EDITS_OUTSTANDING`, the report auto-advances to `VALIDATED`.

Submission is a segregation-of-duties checkpoint: the analyst who submits a validated report must not be the analyst recorded as its `prepared_by_user_id`, and a matching identity is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 409). A report still carrying open exceptions cannot be submitted — the attempt is rejected with `ERR_UNRESOLVED_EDITS` (HTTP 409) — and submission requires the period to be `OPEN`, `FILING_DUE`, or `AMENDMENT_OPEN`, any other period state failing the state check with `ERR_INVALID_STATE_TRANSITION`. A successful submission moves the report `VALIDATED` → `SUBMITTED`, stamps `submitted_at` with the current logical time, sets the period's `late_filing` according to whether that instant is strictly after `filing_due_at`, escalates the bank to `UNDER_LETTER` when the filing is late, moves a period in `OPEN` or `FILING_DUE` on to `SUBMITTED` on this first successful submission, and increments the bank's `version`.

Acceptance belongs to the `RegulatorReviewer`. The reviewer may accept a report only when every edit exception on it has reached `RESOLVED` or `EXPLAINED`; any non-terminal exception blocks acceptance with `ERR_UNRESOLVED_EDITS`. Acceptance stamps `accepted_at`, moves the report `SUBMITTED` → `ACCEPTED`, moves the period `SUBMITTED` → `ACCEPTED`, and then fires the widest cascade in the system. The bank's `pca_bucket` is recomputed from the accepted ratios under the classification of §2.7, and for each of the four metrics — `CET1`, `TIER1`, `TOTAL`, and `LEVERAGE` — whose classification produces a bucket different from the bank's previous `pca_bucket`, a PCA threshold event is inserted. The bank's `mdba_cents` is recomputed under the waterfall of §3.6. Every distribution request still in `APPROVED_NOT_EXECUTED` has its `capacity_reserved_cents` re-evaluated against the new capacity — the smaller of the two §3.6 capacities, before subtracting `pending_distribution_cents` — and any whose reservation exceeds it is moved to `EXPIRED` with its reservation released. Every sub-debt issuance in `PROPOSED`, `APPROVED`, or `PRICED` has its `t2_capacity_headroom_cents` recomputed. Every capital plan in `DRAFT` or `BOARD_REVIEW` whose `baseline_period_id` is this period has its baseline snapshot refreshed from the newly accepted figures. And the bank's `version` increments by one.

### 3.4. Amendments and Orderly Period Close

An accepted filing is not necessarily final. A `CapitalAnalyst` may open an amendment on a period in `ACCEPTED`, provided no later-dated period of the same bank has already been `CLOSED` — the bank cannot reopen history deeper than its open book, and such an attempt is rejected with `ERR_AMENDMENT_LOCKED` (HTTP 409). Under the fixed validation order of §2.9 the state gate is evaluated before this lock, and since periods close only in chronological order a period that has a later-dated `CLOSED` period is necessarily `CLOSED` itself, so the rejection such a request actually receives is `ERR_INVALID_STATE_TRANSITION` from the state check rather than `ERR_AMENDMENT_LOCKED`. Opening an amendment moves the period `ACCEPTED` → `AMENDMENT_OPEN`, spins up a fresh report in `DRAFT` whose `amendment_sequence` increments the prior report's and whose `supersedes_call_report_id` references it, and moves the prior report to `AMENDED_SUPERSEDED`.

The amended report then walks the same gauntlet as an original: preparation, edit resolution, and validation. When the newest report for the period is `VALIDATED` with `edit_failures_open_count` at zero, an analyst submits it and the period moves `AMENDMENT_OPEN` → `RE_SUBMITTED` with the newest report's `submitted_at` stamped. A `RegulatorReviewer` then accepts the amendment while the newest report is `SUBMITTED`, moving the period to `RE_ACCEPTED`.

Accepting an amendment re-runs the acceptance cascade in a harsher mode. The PCA bucket is recomputed from the amended ratios — it may improve or deteriorate — with threshold events inserted for any bucket changes, and `mdba_cents` is recomputed. Every capital plan whose `baseline_period_id` is this period and whose status is anything but `SUPERSEDED` has its baseline fields refreshed and its projected and stressed ratios recomputed; if any projected ratio then falls below its applicable floor — for the stressed figure the regulator-approval floor of §3.5 (the greater of 700 basis points and the baseline-to-stressed drop), and for the base-case figure the 450-basis-point adequate-CET1 floor — that plan is moved to `SUPERSEDED`. Every distribution request still in `PROPOSED` or `APPROVED_NOT_EXECUTED` that is attached to a plan that has just been superseded is moved to `WITHDRAWN`, its reserved capacity released back into the bank's `mdba_cents`; requests already in a terminal state are untouched. The bank's `version` increments.

Books close in chronological order. A period may be closed only from `ACCEPTED` or `RE_ACCEPTED`, and only when every earlier-dated period of the same bank is already `CLOSED`; an out-of-order close is rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 409). Closure moves the period to `CLOSED`, its terminal state.

### 3.5. Stress Scenarios and the Capital Plan Lifecycle

Forward-looking capital adequacy begins with stress scenarios. A `CapitalAnalyst` authors a scenario by naming a `scenario_code` and five macroeconomic shocks, all in basis points: `gdp_shock_bps` (negative for contraction), `unemployment_peak_bps`, `hpi_shock_bps`, `cre_price_shock_bps`, and `market_shock_bps`. The scenario code must be unique among the bank's non-`RETIRED` scenarios; a collision is rejected with `ERR_INVARIANT_VIOLATION` (HTTP 409). New scenarios are `DRAFT`.

Activation turns a scenario into a computable loss engine. A bank may hold at most two scenarios in `ACTIVE` at once — activating a third is rejected with `ERR_SCENARIO_LIMIT` (HTTP 409). On activation the server computes the scenario's `projected_pre_tax_loss_cents` by walking the bank's current exposure inventory — every risk-exposure row attached to one of the bank's periods in `OPEN` or `FILING_DUE` — and assigning each row a base loss rate in basis points of its exposure at default according to its class. A `CORPORATE` exposure loses 200 basis points plus the absolute value of `gdp_shock_bps` multiplied by 30 and divided by 1000. A `CRE` exposure loses 150 plus the absolute value of `cre_price_shock_bps` times 25 over 1000, and an `HVCRE` exposure loses 300 plus the same shock times 40 over 1000. A `RETAIL_MORTGAGE` exposure loses 100 plus the absolute value of `hpi_shock_bps` times 20 over 1000, while a `RETAIL_OTHER` exposure loses 250 plus `unemployment_peak_bps` times 15 over 1000. A `SOVEREIGN` exposure loses nothing. An `EQUITY` exposure loses 500 plus the absolute value of `market_shock_bps` times 50 over 1000; a `SECURITIZATION` exposure loses 300 plus the absolute GDP shock times 20 over 1000 plus the absolute house-price shock times 10 over 1000; an `OPERATIONAL_RISK` exposure loses a flat 50; and a `MARKET_RISK` exposure loses 100 plus the absolute market shock times 30 over 1000. Each line's base rate is then scaled by an obligor-grade multiplier — three for `DEFAULT`, two for `NON_INVESTMENT_GRADE`, one for `INVESTMENT_GRADE` — applied against the exposure at default, divided by 10000, and floored to a whole cent; the projected pre-tax loss is the sum of those per-exposure losses. A scenario may be retired only while no capital plan in `BOARD_REVIEW`, `SUBMITTED`, `SUPERVISORY_REVIEW`, or `APPROVED` references it; retiring an in-use scenario is rejected with `ERR_SCENARIO_IN_USE` (HTTP 409).

A capital plan binds a `plan_year`, a `baseline_period_id`, and a `stress_scenario_id` — both references must resolve to entities owned by the same bank or creation fails with `ERR_CROSS_BANK_REFERENCE`. Creation seeds the plan's baseline snapshot from the baseline period's accepted call report: `baseline_cet1_cents`, `baseline_t1_cents`, `baseline_total_capital_cents`, and `baseline_rwa_cents`, the last using the methodology-appropriate RWA variant; when the baseline period has no accepted report yet, the four baseline fields remain null until a later refresh. A bank may have only one plan in flight at a time: neither creation nor board submission is permitted while another plan of the same bank sits in `BOARD_REVIEW`, `SUBMITTED`, `SUPERVISORY_REVIEW`, or `APPROVED`, and a violation is rejected with `ERR_INVARIANT_VIOLATION`. New plans are `DRAFT`.

Submitting a plan to the board is allowed once the baseline period has reached `ACCEPTED`, `RE_ACCEPTED`, or `CLOSED` and the referenced scenario is `ACTIVE`. The submission recomputes the baseline snapshot, projects the plan forward, captures the submitting analyst's identity as the plan's preparer, and moves the plan `DRAFT` → `BOARD_REVIEW`. Two projections result. The base-case figure `projected_cet1_bps_9q` applies no losses and no RWA growth: quarter q's base ratio is the baseline CET1 minus cumulative distributions, scaled by 10000 over the baseline RWA and floored, and `projected_cet1_bps_9q` is the minimum across the nine quarters. The stressed figure `stressed_min_cet1_bps_9q` applies the scenario: the `projected_pre_tax_loss_cents` is distributed across nine quarters by a fixed weighting profile that sums to exactly 10000 basis points — 800 in the first quarter, then 1000, 1200, 1400, 1300, 1200, 1100, 1100, and 900. Cumulative pre-tax losses are reduced by a 21 percent tax offset; the plan's full `proposed_distributions_cents` is treated as paid in every quarter, so cumulative distributions after quarter q equal q times that total; net income is assumed to be zero. Each quarter's stressed CET1 ratio is the baseline CET1 minus cumulative after-tax losses and cumulative distributions, scaled by 10000, divided by baseline RWA grown by half a percent for each quarter elapsed (50 basis points per quarter, so the third quarter divides by baseline RWA times 10150 over 10000), floored to integer basis points; the minimum across the nine quarters is `stressed_min_cet1_bps_9q`. Both projections remain null until they are computed at this step, and remain null when the baseline RWA is zero or unset.

Board approval is the second segregation-of-duties checkpoint: the `BoardApprover` who approves must not be the analyst who submitted the plan to the board, on pain of `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. The board also certifies capacity: the plan's `proposed_distributions_cents` — the sum of `distribution_amount_cents` over every attached distribution request in any state other than `REJECTED` or `WITHDRAWN` — must not exceed the bank's `mdba_cents` plus the sum of `t2_capacity_headroom_cents` across the bank's `APPROVED` sub-debt issuances, failing which approval is rejected with `ERR_PLAN_DISTRIBUTION_EXCEEDS_CAPACITY` (HTTP 409). A clean approval moves the plan `BOARD_REVIEW` → `SUBMITTED`.

An analyst then files the plan with the supervisor. Every distribution request attached to the plan must be in `PROPOSED` or `APPROVED_NOT_EXECUTED` at that moment — a request in any other state fails the state check with `ERR_INVALID_STATE_TRANSITION` (HTTP 409) — and the request must carry `expected_bank_version` per §2.8 — a stale read of the bank is rejected with `ERR_STALE_VERSION` (HTTP 412). Filing moves the plan `SUBMITTED` → `SUPERVISORY_REVIEW` and increments the bank's `version`.

The `RegulatorReviewer` rules on the plan. Approval applies the stress floor: `stressed_min_cet1_bps_9q` must be at least the adequate-capital CET1 floor of 450 basis points plus the applicable stress capital buffer, otherwise approval is refused with `ERR_PLAN_FAILED_STRESS_FLOOR` (HTTP 409). The buffer embedded in that floor is derived from the stress projection itself: it is the greater of 700 basis points — the 450-basis-point adequate-CET1 floor plus the 250-basis-point regulatory minimum, which holds regardless of stress performance — and the drop from the bank's baseline CET1 ratio to the stressed minimum, floored to integer basis points. Upon approval the server records the bank's `stressed_capital_buffer_bps` as the greater of 450 basis points and the stressed minimum CET1 ratio, minus 450 basis points; the plan moves `SUPERVISORY_REVIEW` → `APPROVED`; and the bank's `version` increments. The buffer value recorded at approval becomes operative when the plan activates: on the first day of the plan year, an `APPROVED` plan auto-advances to `EFFECTIVE` and the bank's `mdba_cents` is recomputed using the now-active buffer; if the first day of the plan year has already passed when approval lands, the plan advances to `EFFECTIVE` immediately upon approval. Until a bank's first plan is approved by the regulator, its `stressed_capital_buffer_bps` remains null.

Objection is the reviewer's other ruling. It moves the plan to `OBJECTED`, escalates the bank's `supervisory_status` to `UNDER_MOU`, moves every attached distribution request in `PROPOSED` or `APPROVED_NOT_EXECUTED` to `REJECTED` with reserved capacity released back to `mdba_cents`, and increments the bank's `version`. An objected plan is not terminal: an analyst's amend action reopens it to `DRAFT`, incrementing the plan's own `version` by one.

Plans are superseded by progress and by adverse news alike. An `APPROVED` plan moves to `SUPERSEDED` when a newer plan for the same bank reaches `APPROVED`, and an `EFFECTIVE` plan moves to `SUPERSEDED` when a newer plan reaches `EFFECTIVE`; both also fall to the amendment cascade of §3.4 when a re-accepted baseline report drags a projected ratio below its floor. Supersession withdraws every attached distribution request still in `PROPOSED` or `APPROVED_NOT_EXECUTED` — each moves to `WITHDRAWN`, with requests already in a terminal state untouched — and the reserved capacity of any withdrawn request is released back to the bank.

### 3.6. Distribution Requests and the Maximum Distributable Amount

Dividends and buybacks draw from a single competed pool. The bank's `mdba_cents` — its maximum distributable amount — is recomputed whenever the PCA bucket changes, the stress capital buffer changes, a distribution is approved, executed, withdrawn, or expires, an instrument is called or redeemed, or a sub-debt issuance settles. The computation is a waterfall of two capacities. PCA capacity applies only while the bank is `WELL_CAPITALIZED` or `ADEQUATELY_CAPITALIZED`: take the smallest of the four ratios on the latest accepted call report — null ratios are excluded from the minimum, and when no report has been accepted, or all four ratios are null, PCA capacity is zero — subtract the adequate-capital floor of the metric that achieves that minimum (450 basis points for CET1, 600 for Tier 1, 800 for total capital, 400 for leverage), multiply the resulting headroom in basis points by the accepted RWA, divide by 10000, and floor the result at zero. Stress-buffer capacity subtracts from the most recently activated `EFFECTIVE` plan's `stressed_min_cet1_bps_9q` the sum of the 450-basis-point adequate-CET1 floor and the bank's `stressed_capital_buffer_bps`, multiplies that headroom by the same latest-accepted RWA over 10000, and floors at zero; when no capital plan is `EFFECTIVE`, stress-buffer capacity is treated as zero and is therefore the binding constraint. The pool itself is the greater of zero and the smaller of the two capacities minus `pending_distribution_cents`, the sum of `distribution_amount_cents` over every distribution request of the bank currently in `APPROVED_NOT_EXECUTED`. In any of the three undercapitalized buckets, `mdba_cents` is zero outright.

A `CapitalAnalyst` proposes a distribution by naming the `capital_plan_id` it belongs to, the `reporting_period_id` of the period in which it would be paid, a `distribution_kind` of `DIVIDEND` or `BUYBACK`, a positive `distribution_amount_cents`, and a `proposed_payment_date`. Both references must belong to the same bank (else `ERR_CROSS_BANK_REFERENCE`), the plan must be in `DRAFT`, `BOARD_REVIEW`, `SUBMITTED`, `SUPERVISORY_REVIEW`, or `APPROVED`, and the payment date must fall within the calendar quarter implied by the chosen period's `period_year` and `period_quarter` and not precede the current date — a date outside that window is rejected with `ERR_TEMPORAL_VIOLATION`. A non-positive `distribution_amount_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A proposal enters as `PROPOSED` with `executed_amount_cents` at zero.

Approval is where capacity is reserved. The attached plan must have reached `APPROVED` — a plan that has since activated to `EFFECTIVE` has passed through `APPROVED` and likewise qualifies; the `proposed_payment_date` must still not precede the current date; the bank must be `WELL_CAPITALIZED` or `ADEQUATELY_CAPITALIZED`, failing which approval is rejected with `ERR_PCA_BLOCKS_DISTRIBUTION` (HTTP 409); and the amount must fit the uncommitted pool — `mdba_cents` minus `pending_distribution_cents` must be at least `distribution_amount_cents`, failing which the rejection is `ERR_DISTRIBUTION_EXCEEDS_MDBA` (HTTP 409). The request must also carry `expected_bank_version` per §2.8, since the capacity arithmetic is only as good as the client's last read of the bank; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). On approval the request moves `PROPOSED` → `APPROVED_NOT_EXECUTED`, its `capacity_reserved_cents` is set to the full `distribution_amount_cents`, that amount is added to the bank's `pending_distribution_cents`, and the bank's `version` increments.

Execution pays the distribution out. The logical clock must have reached the `proposed_payment_date` — an early execution is rejected with `ERR_DISTRIBUTION_NOT_YET_PAYABLE` (HTTP 409) — and must not have passed ten days beyond it, because the payment window is the payment date plus ten days and a request whose window has closed is instead moved to `EXPIRED` automatically; an execute attempted after the window has closed likewise moves the request to `EXPIRED` with its reservation released, and is then rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 409). The PCA gate is re-checked at execution time: a bank that has slipped below adequately capitalized since approval sees the execution rejected with `ERR_PCA_BLOCKS_DISTRIBUTION`. A successful execution moves the request `APPROVED_NOT_EXECUTED` → `EXECUTED`, records the full amount in `executed_amount_cents`, subtracts the amount from both `pending_distribution_cents` and `mdba_cents` — the capacity is now consumed, not merely reserved — and increments the bank's `version`.

Requests unwind in three ways. An analyst may reject a `PROPOSED` request, moving it to `REJECTED`; may withdraw an `APPROVED_NOT_EXECUTED` request, moving it to `WITHDRAWN`, subtracting its `capacity_reserved_cents` from `pending_distribution_cents`, zeroing the reservation, and incrementing the bank's `version`; and the clock itself expires an `APPROVED_NOT_EXECUTED` request once the payment window closes, with the same reservation release. Withdrawal and expiry are the mirror image of approval: capacity reserved against the pool flows back. The acceptance and amendment cascades of §3.3 and §3.4 can also force requests into `EXPIRED` or `WITHDRAWN` when capacity shrinks or their parent plan is superseded.

### 3.7. Subordinated Debt Issuance and Tier 2 Headroom

Subordinated debt is the planned route to Tier 2 capital. A `CapitalAnalyst` proposes an issuance with a positive `proposed_amount_cents`, a positive `proposed_rate_bps` coupon, a `maturity_years` term, and a `target_settlement_date` — a non-positive amount or rate is rejected with `ERR_INVALID_REQUEST` (HTTP 400); the proposal enters as `PROPOSED` and the server computes its initial `t2_capacity_headroom_cents`. That headroom is the bank's Tier 2 room under the cap: the cap is 2 percent of the bank's most recently accepted RWA — the `rwa_cents` of its latest `ACCEPTED` call report, treated as zero when no report has been accepted yet — computed as that RWA times 200 over 10000 and floored, and headroom is the greater of zero and the cap minus the sum of `regulatory_capital_cents` over the bank's `OUTSTANDING` `T2` instruments. Headroom is recomputed at proposal, at approval, on every RWA recomputation, and whenever a Tier 2 instrument is called, redeemed, or matures.

Approval of an issuance stacks four gates. The term must be at least five years for the debt to be Tier 2-eligible at issuance — a shorter `maturity_years` is rejected with `ERR_MATURITY_TOO_SHORT` (HTTP 409). The `proposed_amount_cents` must fit within the current `t2_capacity_headroom_cents`, else `ERR_T2_CAP_EXCEEDED` (HTTP 409). The bank must be `WELL_CAPITALIZED` or `ADEQUATELY_CAPITALIZED`, else `ERR_PCA_BLOCKS_ISSUANCE` (HTTP 409). And the request must carry `expected_bank_version` per §2.8, rejected on mismatch with `ERR_STALE_VERSION` (HTTP 412) — because headroom derives from RWA and outstanding Tier 2, a stale bank read means the 2-percent cap arithmetic the client relied on is no longer the server's. Approval recomputes the headroom, moves the issuance `PROPOSED` → `APPROVED`, and increments the bank's `version`.

An approved issuance is then priced, moving `APPROVED` → `PRICED`, and later settled. Settlement is possible only once the logical clock has reached the `target_settlement_date` — an early settlement is rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 409) — and it re-verifies the Tier 2 cap against freshly recomputed headroom — capacity may have shrunk since approval, and an issuance that no longer fits is rejected with `ERR_T2_CAP_EXCEEDED`. A clean settlement moves the issuance to `SETTLED`, creates the corresponding capital instrument with `instrument_class` `T2` and `instrument_subtype` `SUBORDINATED_DEBT`, `outstanding_amount_cents` equal to the proposed amount, `contractual_rate_bps` equal to the proposed coupon, the current date as its `issuance_date`, and a `maturity_date` exactly `maturity_years` after that date (a February 29 issuance matures on February 28 in a non-leap target year); the issuance's `capital_instrument_id` — null until this moment — is set to the new instrument, and the bank's `version` increments. An issuance still in `PROPOSED` or `APPROVED` may instead be withdrawn, moving it to `WITHDRAWN`.

### 3.8. Threshold Events and ICAAP Documentation

PCA threshold events are the audit trail of capitalization changes. Each event is written at the moment an accepted call report — original or amended — shifts the bank's classification, and records the `metric` concerned (`CET1`, `TIER1`, `TOTAL`, or `LEVERAGE`), the `ratio_bps_observed` at the moment of the check in basis points, the `bucket_before`, the `bucket_after`, and a `breached` flag that is true exactly when the new bucket is stricter than the old one. On each event, `bucket_before` carries the bank's previous overall `pca_bucket` and `bucket_after` the triggering metric's own classification under §2.7 — not the bank's newly computed overall bucket. Events reference both the owning bank and, through `call_report_id`, the accepted report that triggered the check. As §2.4 notes, these records are immutable: they carry `id` and `created_at` and nothing else of the common set.

The ICAAP document closes the governance loop. A `CapitalAnalyst` drafts one by naming the `document_year`, the `governing_capital_plan_id` of the plan it documents (a same-bank reference, on pain of `ERR_CROSS_BANK_REFERENCE`), and a `sections` array whose entries each pair a `section_code` with its `content`; entries are validated only for carrying a string `section_code` — a `sections` value that is not an array, or an entry without a string `section_code`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The drafting analyst's identity is captured as the document's `prepared_by_user_id`. Five sections are required — `GOVERNANCE`, `RISK_APPETITE`, `CAPITAL_ADEQUACY`, `STRESS_TESTING`, and `DISTRIBUTION_POLICY` — and submitting the document for review checks them all: a missing section is rejected with `ERR_SECTION_MISSING` (HTTP 422). Submission for review also requires the governing plan to have reached `APPROVED` or `EFFECTIVE`; otherwise the rejection is `ERR_PLAN_NOT_FINAL` (HTTP 409). A clean submission moves the document `DRAFT` → `REVIEW`.

Attestation is the third segregation-of-duties checkpoint. A `BoardApprover` attests a document in `REVIEW`, and the attester's `X-User-ID` must differ from the document's `prepared_by_user_id`, failing which the attestation is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Attestation records the attester in `board_attested_by_user_id` and moves the document `REVIEW` → `ATTESTED`.

Filing is the final act, and it is one of the four optimistic-concurrency writes of §2.8: the filing request must carry `expected_bank_version`, because a bank-level mutation since the client's last read may have superseded the very plan the document describes, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The governing plan must be `EFFECTIVE` at filing time — an `APPROVED`-but-not-yet-effective plan is no longer sufficient, and the rejection is again `ERR_PLAN_NOT_FINAL`. A successful filing moves the document `ATTESTED` → `FILED`, supersedes the bank's previous filed document (any earlier document still sitting in `DRAFT`, `REVIEW`, or `ATTESTED` is likewise superseded when a newer document of the same bank reaches `FILED`), and increments the bank's `version`.

## 4. Endpoint Definitions

Operations that create a new resource — a bank, a reporting period, an instrument, an exposure, a call report, a scenario, a plan, a distribution request, an issuance, or an ICAAP document — return `201 Created`. Operations that act on an existing resource (state-transition actions such as prepare, submit, accept, approve, settle, and the clock advance) return `200 OK`. All read endpoints are available to every role and are marked "Any" below; the full request and response shapes for each operation are defined by the workflows of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | SystemOperator |
| GET | `/_clock/current_utc` | Read the current logical clock time | Any |
| POST | `/banks` | Create a Bank | SystemOperator |
| GET | `/banks/{bankId}` | Get a Bank | Any |
| GET | `/banks` | List Banks, filterable by `charter_id` or `pca_bucket_as_of_period_id` | Any |
| POST | `/banks/{bankId}/reporting-periods` | Create a ReportingPeriod | CapitalAnalyst |
| GET | `/banks/{bankId}/reporting-periods/{periodId}` | Get a ReportingPeriod | Any |
| GET | `/banks/{bankId}/reporting-periods` | List ReportingPeriods for a bank | Any |
| POST | `/banks/{bankId}/reporting-periods/{periodId}/close` | Close a ReportingPeriod (books-closed) | CapitalAnalyst |
| POST | `/banks/{bankId}/capital-instruments` | Create a CapitalInstrument (issue CET1/AT1/T2) | CapitalAnalyst |
| GET | `/banks/{bankId}/capital-instruments/{instrumentId}` | Get a CapitalInstrument | Any |
| GET | `/banks/{bankId}/capital-instruments` | List CapitalInstruments | Any |
| POST | `/banks/{bankId}/capital-instruments/{instrumentId}/call` | Call a callable CapitalInstrument | CapitalAnalyst |
| POST | `/banks/{bankId}/capital-instruments/{instrumentId}/redeem` | Redeem a CapitalInstrument | CapitalAnalyst |
| POST | `/banks/{bankId}/reporting-periods/{periodId}/risk-exposures` | Create a RiskExposure for a period | CapitalAnalyst |
| GET | `/banks/{bankId}/reporting-periods/{periodId}/risk-exposures/{exposureId}` | Get a RiskExposure | Any |
| GET | `/banks/{bankId}/reporting-periods/{periodId}/risk-exposures` | List RiskExposures for a period | Any |
| GET | `/banks/{bankId}/risk-exposures` | List RiskExposures across periods | Any |
| POST | `/banks/{bankId}/reporting-periods/{periodId}/call-reports` | Create a draft CallReport for a period | CapitalAnalyst |
| GET | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}` | Get a CallReport | Any |
| GET | `/banks/{bankId}/reporting-periods/{periodId}/call-reports` | List CallReports for a period (all amendments) | Any |
| GET | `/banks/{bankId}/call-reports` | List CallReports across periods | Any |
| POST | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}/prepare` | Run RWA, capital, ratio, and edit-check computations | CapitalAnalyst |
| POST | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}/submit` | Submit a validated call report | CapitalAnalyst |
| POST | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}/accept` | Regulator accepts a submitted report | RegulatorReviewer |
| POST | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}/open_amendment` | Open an amendment on an accepted period | CapitalAnalyst |
| GET | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}/edit-exceptions` | List EditExceptions on a report | Any |
| GET | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}/edit-exceptions/{editId}` | Get an EditException | Any |
| POST | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}/edit-exceptions/{editId}/resolve` | Resolve an edit exception | CapitalAnalyst |
| POST | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}/edit-exceptions/{editId}/explain` | Explain a QUALITY or INFORMATIONAL edit | CapitalAnalyst |
| POST | `/banks/{bankId}/stress-scenarios` | Create a StressScenario | CapitalAnalyst |
| GET | `/banks/{bankId}/stress-scenarios/{scenarioId}` | Get a StressScenario | Any |
| GET | `/banks/{bankId}/stress-scenarios` | List StressScenarios | Any |
| POST | `/banks/{bankId}/stress-scenarios/{scenarioId}/activate` | Activate a stress scenario | CapitalAnalyst |
| POST | `/banks/{bankId}/stress-scenarios/{scenarioId}/retire` | Retire a stress scenario | CapitalAnalyst |
| POST | `/banks/{bankId}/capital-plans` | Create a CapitalPlan | CapitalAnalyst |
| GET | `/banks/{bankId}/capital-plans/{planId}` | Get a CapitalPlan | Any |
| GET | `/banks/{bankId}/capital-plans` | List CapitalPlans | Any |
| POST | `/banks/{bankId}/capital-plans/{planId}/submit_board` | Submit plan for board review | CapitalAnalyst |
| POST | `/banks/{bankId}/capital-plans/{planId}/board_approve` | Board approves plan | BoardApprover |
| POST | `/banks/{bankId}/capital-plans/{planId}/submit_regulator` | Submit plan to regulator | CapitalAnalyst |
| POST | `/banks/{bankId}/capital-plans/{planId}/regulator_approve` | Regulator approves plan | RegulatorReviewer |
| POST | `/banks/{bankId}/capital-plans/{planId}/regulator_object` | Regulator objects to plan | RegulatorReviewer |
| POST | `/banks/{bankId}/capital-plans/{planId}/amend` | Analyst amends an objected plan | CapitalAnalyst |
| POST | `/banks/{bankId}/distribution-requests` | Propose a dividend or buyback | CapitalAnalyst |
| GET | `/banks/{bankId}/distribution-requests/{requestId}` | Get a distribution request | Any |
| GET | `/banks/{bankId}/distribution-requests` | List distribution requests | Any |
| POST | `/banks/{bankId}/distribution-requests/{requestId}/approve` | Approve a distribution request | CapitalAnalyst |
| POST | `/banks/{bankId}/distribution-requests/{requestId}/execute` | Execute (pay) an approved distribution | CapitalAnalyst |
| POST | `/banks/{bankId}/distribution-requests/{requestId}/reject` | Reject a proposed distribution | CapitalAnalyst |
| POST | `/banks/{bankId}/distribution-requests/{requestId}/withdraw` | Withdraw an approved distribution | CapitalAnalyst |
| POST | `/banks/{bankId}/sub-debt-issuances` | Propose a T2 sub-debt issuance | CapitalAnalyst |
| GET | `/banks/{bankId}/sub-debt-issuances/{issuanceId}` | Get a sub-debt issuance | Any |
| GET | `/banks/{bankId}/sub-debt-issuances` | List sub-debt issuances | Any |
| POST | `/banks/{bankId}/sub-debt-issuances/{issuanceId}/approve` | Approve a sub-debt issuance | CapitalAnalyst |
| POST | `/banks/{bankId}/sub-debt-issuances/{issuanceId}/price` | Price an approved issuance | CapitalAnalyst |
| POST | `/banks/{bankId}/sub-debt-issuances/{issuanceId}/settle` | Settle a priced issuance (creates a CapitalInstrument) | CapitalAnalyst |
| POST | `/banks/{bankId}/sub-debt-issuances/{issuanceId}/withdraw` | Withdraw an issuance | CapitalAnalyst |
| GET | `/banks/{bankId}/pca-threshold-events` | List PCA threshold events for the bank | Any |
| GET | `/banks/{bankId}/pca-threshold-events/{eventId}` | Get a PCA threshold event | Any |
| POST | `/banks/{bankId}/icaap-documents` | Create an ICAAP document | CapitalAnalyst |
| GET | `/banks/{bankId}/icaap-documents/{docId}` | Get an ICAAP document | Any |
| GET | `/banks/{bankId}/icaap-documents` | List ICAAP documents | Any |
| POST | `/banks/{bankId}/icaap-documents/{docId}/submit_review` | Submit ICAAP for review | CapitalAnalyst |
| POST | `/banks/{bankId}/icaap-documents/{docId}/attest` | Board attests ICAAP | BoardApprover |
| POST | `/banks/{bankId}/icaap-documents/{docId}/file` | File an attested ICAAP | CapitalAnalyst |
| GET | `/reporting-periods/{periodId}` | Flat single-resource read on a ReportingPeriod | Any |
| GET | `/reporting-periods` | Flat filtered list of ReportingPeriods | Any |
| GET | `/capital-instruments/{instrumentId}` | Flat single-resource read on a CapitalInstrument | Any |
| GET | `/capital-instruments` | Flat filtered list of CapitalInstruments | Any |
| GET | `/risk-exposures/{exposureId}` | Flat single-resource read on a RiskExposure | Any |
| GET | `/risk-exposures` | Flat filtered list of RiskExposures | Any |
| GET | `/capital-plans/{planId}` | Flat single-resource read on a CapitalPlan | Any |
| GET | `/capital-plans` | Flat filtered list of CapitalPlans | Any |
| GET | `/stress-scenarios/{scenarioId}` | Flat single-resource read on a StressScenario | Any |
| GET | `/stress-scenarios` | Flat filtered list of StressScenarios | Any |
| GET | `/call-reports/{reportId}` | Flat single-resource read on a CallReport | Any |
| GET | `/call-reports` | Flat filtered list of CallReports | Any |
| GET | `/edit-exceptions/{editId}` | Flat single-resource read on an EditException | Any |
| GET | `/edit-exceptions` | Flat filtered list of EditExceptions | Any |
| GET | `/distribution-requests/{requestId}` | Flat single-resource read on a CapitalDistributionRequest | Any |
| GET | `/distribution-requests` | Flat filtered list of CapitalDistributionRequests | Any |
| GET | `/sub-debt-issuances/{issuanceId}` | Flat single-resource read on a SubordinatedDebtIssuance | Any |
| GET | `/sub-debt-issuances` | Flat filtered list of SubordinatedDebtIssuances | Any |
| GET | `/pca-threshold-events/{eventId}` | Flat single-resource read on a PCAThresholdEvent | Any |
| GET | `/pca-threshold-events` | Flat filtered list of PCAThresholdEvents | Any |
| GET | `/icaap-documents/{docId}` | Flat single-resource read on an ICAAPDocument | Any |
| GET | `/icaap-documents` | Flat filtered list of ICAAPDocuments | Any |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions under which each error fires are defined where the corresponding rule lives in §2 and §3, not here. Two framework-level outcomes sit outside the catalogue's business rules: a request whose path matches no route is rejected with `ERR_NOT_FOUND` (HTTP 404), a matched path called with the wrong method yields `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server failure yields `ERR_INTERNAL` (HTTP 500) — all in the standard error envelope.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM_VALUE` | 422 Unprocessable Entity |
| `ERR_INVALID_RISK_PARAMETER` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CROSS_BANK_REFERENCE` | 422 Unprocessable Entity |
| `ERR_PCA_BLOCKS_DISTRIBUTION` | 409 Conflict |
| `ERR_PCA_BLOCKS_ISSUANCE` | 409 Conflict |
| `ERR_PCA_BLOCKS_REDEMPTION` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 409 Conflict |
| `ERR_INVARIANT_VIOLATION` | 409 Conflict |
| `ERR_SCENARIO_LIMIT` | 409 Conflict |
| `ERR_SCENARIO_IN_USE` | 409 Conflict |
| `ERR_TEMPORAL_VIOLATION` | 409 Conflict |
| `ERR_MATURITY_TOO_SHORT` | 409 Conflict |
| `ERR_T2_CAP_EXCEEDED` | 409 Conflict |
| `ERR_DISTRIBUTION_EXCEEDS_MDBA` | 409 Conflict |
| `ERR_DISTRIBUTION_NOT_YET_PAYABLE` | 409 Conflict |
| `ERR_PLAN_DISTRIBUTION_EXCEEDS_CAPACITY` | 409 Conflict |
| `ERR_PLAN_FAILED_STRESS_FLOOR` | 409 Conflict |
| `ERR_PLAN_NOT_FINAL` | 409 Conflict |
| `ERR_SECTION_MISSING` | 422 Unprocessable Entity |
| `ERR_UNRESOLVED_EDITS` | 409 Conflict |
| `ERR_EDIT_NOTE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_AMENDMENT_LOCKED` | 409 Conflict |
| `ERR_NO_EXPOSURES` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INSTRUMENT_NOT_CALLABLE` | 409 Conflict |
| `ERR_DUPLICATE_CHARTER_ID` | 409 Conflict |
