# Enterprise Risk Register API — Product Requirements Document

## 1. Introduction

A corporate Enterprise Risk Management (ERM) function lives or dies by the discipline of its register. Identification workshops surface raw risks that must be classified into a governed taxonomy; scoring committees need a defensible split between inherent exposure and the residual exposure that remains once controls are credited; the board expects appetite statements with hard tolerance lines, escalated breaches, and aggregation reports that reconcile to the same numbers every time they are opened. Spreadsheet registers fail precisely at these joints: scores drift out of date when a control is re-attested, tolerance breaches slip past unacknowledged, treatment budgets are silently double-allocated, and nobody can reconstruct which version of a risk a planner was looking at when they committed budget.

This document specifies the Enterprise Risk Register API, the system of record for that function. The API governs the full register lifecycle: a self-referential risk taxonomy with weighted categories; risk registration and a cyclic assessment workflow with dual inherent and residual scoring; a control library whose effectiveness ratings feed a diminishing-returns discount model; appetite statements with half-open effectiveness windows and tolerance-breach escalation; treatment plans with budget reservation, owner-driven execution, and bounded deadline extensions; key risk indicators whose observations drive a one-way alert ratchet across the register; scenario-scored emerging risks that can be promoted into first-class register entries; and board reporting in provisional and final variants with frozen, auditable snapshots. Cross-cutting concerns — segregation of duties between proposer and approver, optimistic concurrency on budget- and score-bearing writes, and a server-maintained logical clock that drives overdue and review-expiry sweeps — are specified once in §2 and referenced throughout the business workflows of §3.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts. The system recognizes exactly five roles, spelled precisely as follows: `RiskManager`, `RiskOwner`, `ControlOwner`, `BoardReporter`, and `InternalAuditor`. A request missing either header, or carrying a role value outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the `InternalAuditor` is a read-only assurance role, so every write attempt from an auditor fails this check.

The roles divide the register's duties. A `RiskManager` is the corporate ERM function lead: this role owns the taxonomy, appetite statements, key risk indicators, control-mapping approval, breach acceptance, emerging-risk triage, and the logical clock. A `RiskOwner` is a business-unit risk owner: this role registers risks, assesses them, proposes control mappings and treatment plans, and executes treatment work. A `ControlOwner` maintains the control library and attests control effectiveness. A `BoardReporter` compiles and finalizes board risk reports. An `InternalAuditor` reads everything and writes nothing.

For every one of the five roles — `RiskManager`, `RiskOwner`, `ControlOwner`, `BoardReporter`, and `InternalAuditor` alike — `X-User-ID` is an opaque operator identifier that is not the `id` of any persisted entity. The server records the identifier on the resources the operator creates — for example as `owner_user_id` on a Risk or a TreatmentPlan, as `proposer_user_id` on a TreatmentPlan, or as `created_by` on an AppetiteStatement — and ownership and segregation-of-duties checks compare those recorded fields against the caller's `X-User-ID`. They never compare `X-User-ID` against any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Time-Driven State Changes

All temporal rules in the system — effectiveness windows, due dates, observation spacing, review deadlines — are evaluated against a server-maintained **logical clock**, never against wall-clock time. Before any adjustment, the logical clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `RiskManager` advances the clock through a test-driving capability that accepts a target instant `to_iso8601` and responds with the new `current_utc`.

Advancing the clock triggers two sweeps across the register. First, every treatment plan in `IN_PROGRESS` whose `due_date` is now in the past moves to `OVERDUE`. Second, every tolerance breach in `ACCEPTED` whose `review_by` instant has been reached or passed re-opens to `OPEN`. The same two evaluations also happen lazily: reading an individual treatment plan re-evaluates whether it has slipped past its `due_date`, and reading an individual tolerance breach re-evaluates whether its `review_by` has been reached. A client can therefore observe these state changes on a plain read without any explicit write to the affected resource.

### 2.5. Common Resource Properties and Append-Only Event Records

Every resource carries an `id` — a unique, server-minted identifier formatted as a UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was first created.

All entities except the two append-only event records additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation, and `version`, a system-managed integer that increments by 1 with every modification to the resource and anchors the optimistic concurrency checks of §2.7.

The two exceptions are the RiskAssessment and the KRIObservation. Both are immutable event records: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent, because neither record can ever change after creation. Their immutability is what makes them a reliable audit trail for scoring and monitoring decisions.

The three-fractional-digit rendering is uniform across the API: every datetime-valued field in any response — entity instants such as `effective_from`, `effective_to`, `review_by`, `due_date`, `last_observation_at`, `observed_at`, `period_start`, and `period_end`, as well as the clock endpoint's `current_utc` and the envelope's `api_request_timestamp` — is an ISO 8601 UTC timestamp with exactly three fractional digits and a `Z` suffix, and a datetime field that has no value renders as null.

### 2.6. Scoring Scales, Bands, and Numeric Precision

Likelihood and impact are integers from 1 to 5 inclusive, and all risk scores derived from them are integers. The inherent score of a risk is the product of its likelihood and impact and therefore ranges from 1 to 25. Four severity bands apply uniformly — to the inherent view via `inherent_band`, to the residual view via `residual_band`, and to the board report's band tallies: a score from 1 to 4 inclusive is `LOW`, from 5 to 9 inclusive is `MEDIUM`, from 10 to 15 inclusive is `HIGH`, and from 16 to 25 inclusive is `CRITICAL`.

Precision rules are fixed per quantity. Monetary amounts — budgets, reservations, plan costs — are handled as exact integer numbers of cents with no fractional arithmetic. A treatment plan's `progress_pct` and every board-report heat value are carried at exactly two decimal places using round-half-up. The emerging-risk scenario score is a whole number produced by round-half-up at zero decimal places. A category's `weight_factor` may carry up to three decimal places and must be greater than 0 and at most 10. A control's `effectiveness_pct` and a mapping's `coverage_weight` are decimal fractions, each greater than 0 and at most 1.00.

Range violations on fields that §5 does not catalogue under a dedicated error — `coverage_weight` outside its fraction range, `weight_factor` outside its bounds or precision, a `max_mapped_risks` below 1, a `min_observation_interval_days` below 0, a `budget_cents` of 0 or less, a negative `treatment_budget_cents` — are rejected as malformed request bodies with `ERR_INVALID_REQUEST`.

### 2.7. Optimistic Concurrency Control on the Register

Two write operations on the risk register carry optimistic concurrency control, and both guard the same parent entity: the Risk. Creating a risk assessment and proposing a treatment plan under a risk each require a non-optional request-body field, `expected_risk_version`, carrying the risk's `version` as the client last observed it. If the risk's current `version` differs from `expected_risk_version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412); the client must re-read the risk and retry against the fresh version.

The rationale differs per write. A successful assessment creation supersedes the client's view of the risk's latest scores, so a writer carrying a stale observed version must re-read before writing. A treatment-plan proposal reads the risk's available treatment budget, and a stale observed version may double-allocate budget already reserved by a plan created after the client's last read. No endpoint other than these two accepts a version field in its request body.

### 2.8. Validation Precedence

When several rules could reject the same request, exactly one error is returned, determined by a fixed precedence ladder. From highest to lowest priority:

1. Authentication — both headers present and the role recognized (`ERR_UNAUTHENTICATED`).
2. Role authorization — the role is permitted on the endpoint (`ERR_FORBIDDEN`).
3. Request-body shape — required fields present, types valid, enum members in their declared sets, datetime fields parsing as ISO 8601 (`ERR_INVALID_REQUEST`).
4. Existence — path identifiers validated left to right, and foreign-key references in the body (`ERR_NOT_FOUND`).
5. Ownership — the caller's `X-User-ID` against the resource's owning `owner_user_id` field (`ERR_OWNER_MISMATCH`).
6. Stale-version concurrency control (`ERR_STALE_VERSION`).
7. State guards — the requested transition exists from the entity's current status, including the assessment-kind guard and the KRI-active guard (`ERR_INVALID_STATE`, `ERR_ASSESSMENT_KIND_NOT_ALLOWED`, `ERR_KRI_NOT_ACTIVE`).
8. Segregation of duties (`ERR_SOD_VIOLATION`).
9. Domain ranges and uniqueness — score ranges, tolerance ranges, KRI threshold ordering, duplicate mappings, taxonomy cycles, plan-extension limits, acceptance caps, promotion thresholds, action completeness (`ERR_SCORE_OUT_OF_RANGE`, `ERR_TOLERANCE_OUT_OF_RANGE`, `ERR_THRESHOLD_ORDER_INVALID`, `ERR_MAPPING_EXISTS`, `ERR_CATEGORY_CYCLE`, `ERR_PLAN_EXTENSION_LIMIT`, `ERR_ACCEPTANCE_CAP_EXCEEDED`, `ERR_EMERGING_SCORE_BELOW_THRESHOLD`, `ERR_INCOMPLETE_ACTIONS`).
10. Temporal rules — appetite window overlap, report period overlap, observation spacing and futurity, due dates and review dates (`ERR_WINDOW_OVERLAP`, `ERR_REPORT_PERIOD_OVERLAP`, `ERR_OBSERVATION_TOO_SOON`, `ERR_OBSERVATION_IN_FUTURE`, and `ERR_INVALID_REQUEST` for clock-relative date violations).
11. Referenced-entity state guards — control activation, remaining appetite coverage, breach-resolution maturity, blocking breaches and plans (`ERR_CONTROL_NOT_ACTIVE`, `ERR_NO_APPETITE_COVERAGE`, `ERR_BREACH_RESOLUTION_PREMATURE`, `ERR_OPEN_BREACH_BLOCKING`, `ERR_ACTIVE_PLAN_BLOCKING`).
12. Capacity and budget — always evaluated last (`ERR_CONTROL_CAPACITY_EXCEEDED`, `ERR_BUDGET_EXCEEDED`).

The ladder means earlier classes mask later ones: a stale-version rejection surfaces before any state-guard rejection, a state-guard rejection surfaces before a segregation-of-duties violation, and a segregation-of-duties violation surfaces before a budget shortfall. On mapping approval, the control-state check therefore reports before the capacity check.

### 2.9. Nested Paths and Referential Integrity

For any endpoint whose path nests one resource under another, path identifiers are validated from left to right, and the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404); segments further right are never examined. Foreign-key references supplied in request bodies — `category_id`, `control_id`, and `parent_category_id` — must likewise reference existing resources, or the request fails with `ERR_NOT_FOUND`.

### 2.10. Segregation of Duties

Two approval workflows enforce a strict separation between proposer and approver. A treatment plan may be approved or rejected only by a `RiskManager` whose `X-User-ID` differs from the plan's recorded `proposer_user_id` — the operator who created the plan can never decide its fate. An appetite statement may be approved only by a `RiskManager` whose `X-User-ID` differs from the statement's `created_by`. Either violation is rejected with `ERR_SOD_VIOLATION` (HTTP 422).

### 2.11. Cascading Recalculation Across the Register

Scores on the register are living values, and the system propagates every scoring-relevant change immediately. Approving or retiring a control mapping, attesting or retiring a control, recording a residual assessment, and completing an inherent reassessment each trigger a recomputation of the residual score of every affected risk, immediately followed by appetite-breach evaluation, which may open a new tolerance breach. Each entity touched by such a cascade — risk, control, or mapping — has its `version` incremented by 1 and its `updated_at` refreshed. Key-risk-indicator red breaches cascade outward in a different direction, raising alert flags on risks and ratcheting treatment-plan priorities (§3.6). Board reports are the deliberate exception: their aggregation snapshots are frozen at finalization and decoupled from later register movement (§3.8).

## 3. Business Logic & Workflows

### 3.1. The Risk Taxonomy and the Appetite Framework

The taxonomy is a self-referential tree of categories maintained by a `RiskManager`. Creating a category requires a display `name`; the optional `parent_category_id` places the category under an existing parent, and omitting it creates a root node. The parent chain of a category must never contain the category itself: any create or reparenting that would close such a loop is rejected with `ERR_CATEGORY_CYCLE`, and reparenting is likewise rejected when the proposed new parent is one of the category's own descendants. A successful reparenting increments the category's `version` by 1. Each category also carries a `weight_factor`, defaulting to 1.0, that scales its contribution to board-report heat (§3.8).

Every category exposes a `current_tolerance_score`: the `tolerance_score` of the `APPROVED` appetite statement whose effectiveness window contains the current logical clock, or null when no such statement exists. The value is recomputed whenever the set of approved statements for the category changes through approval or retirement. Browsing the taxonomy is possible in both directions — the direct children of a category are listed through its subcategories view, and each category exposes filtered collections of its risks (filterable by `status`), its appetite statements, its key risk indicators, and its emerging risks; the top-level category list itself can be filtered by `parent_category_id`.

An appetite statement is drafted by a `RiskManager` with its `category_id`, a `tolerance_score`, an `acceptance_cap_score`, and a half-open effectiveness window bounded by `effective_from` and `effective_to`. Both scores are integers from 1 to 25 inclusive, and the cap must be at least the tolerance; any violation of these ranges is rejected with `ERR_TOLERANCE_OUT_OF_RANGE`. The window must open before it closes — `effective_to` strictly after `effective_from`, otherwise `ERR_INVALID_REQUEST` — and it includes its start instant while excluding its end instant. Among `APPROVED` statements of the same category these half-open windows must never overlap, a rule enforced both when a statement is created and again when it is approved; adjacency, where one window's `effective_from` equals another's `effective_to`, is permitted. An overlap is rejected with `ERR_WINDOW_OVERLAP`. A new statement begins in `DRAFT`, with `created_by` recorded from the caller.

Approval moves a statement `DRAFT` → `APPROVED` and is subject to the segregation-of-duties rule of §2.10 and to a fresh window-overlap check at approval time. Retirement moves `APPROVED` → `RETIRED` and is guarded by coverage: retiring a statement is rejected with `ERR_NO_APPETITE_COVERAGE` when it would leave the category with no other `APPROVED` statement effective at the current logical clock. Both approval and retirement recompute the category's `current_tolerance_score`.

### 3.2. Risk Registration, Scoring, and the Assessment Loop

A `RiskOwner` opens a register entry by supplying the `category_id` that classifies it, a short `title`, the `owner_user_id` of the accountable owner, and optionally a free-text `description` and a `treatment_budget_cents` ceiling expressed in whole cents, never negative, defaulting to 0. A new risk begins in `DRAFT` with `kri_alert` false, `reserved_treatment_cents` at 0, and every score field null. The register supports filtered browsing: the risk list accepts `category_id`, `status`, and `residual_band` query parameters.

Submission moves a risk `DRAFT` → `IDENTIFIED` and is restricted to the risk's owner — the caller's `X-User-ID` must equal the recorded `owner_user_id`, or the request fails with `ERR_OWNER_MISMATCH`. Every subsequent risk transition and every assessment is likewise owner-only. Submission, like every risk transition described below, increments the risk's `version` by 1.

Assessment is where scores enter the register. The owner posts an assessment record carrying a `kind` of `INHERENT` or `RESIDUAL`, an optional `notes` commentary, and the concurrency field `expected_risk_version` (§2.7). For an `INHERENT` assessment, `likelihood` and `impact` are required — omitting either is a malformed request rejected with `ERR_INVALID_REQUEST` — and each must be an integer from 1 to 5 inclusive, or the request fails with `ERR_SCORE_OUT_OF_RANGE`. The `inherent_score` is the product of `likelihood` and `impact`, an integer from 1 to 25, and the `inherent_band` follows the band edges of §2.6. An `INHERENT` assessment is permitted only while the risk is `IDENTIFIED` or `REASSESSMENT`; attempted from any other status it is rejected with `ERR_ASSESSMENT_KIND_NOT_ALLOWED`. From `IDENTIFIED`, the assessment moves the risk to `ASSESSED` and sets `likelihood`, `impact`, `inherent_score`, and `inherent_band` on the risk. From `REASSESSMENT`, the assessment moves the risk to `MONITORING`, updates the same four fields, then recomputes the residual score against the currently qualifying control mappings using the new inherent base — the mappings themselves are untouched — and runs appetite-breach evaluation, which may open a tolerance breach in `OPEN` status.

A `RESIDUAL` assessment never changes the risk's lifecycle status: it is a self-transition permitted from `ASSESSED`, `TREATMENT`, `MONITORING`, and `REASSESSMENT`, and rejected from `DRAFT`, `IDENTIFIED`, or `CLOSED` with `ERR_ASSESSMENT_KIND_NOT_ALLOWED`. Any `likelihood` or `impact` supplied alongside a `RESIDUAL` assessment is ignored. Each residual assessment recomputes `residual_score` and `residual_band` under the discount model of §3.3 and runs appetite-breach evaluation. Every assessment creation, of either kind, increments the risk's `version` by 1.

Assessment records are append-only. Each record carries the `risk_id` it belongs to, its `kind`, and snapshots of the register after the event: `inherent_score` is captured for both kinds, while `residual_score` is captured only for a `RESIDUAL` assessment. The `breach_created` flag is true exactly when that assessment's residual recomputation opened a new tolerance breach. A risk's assessment history is listed in chronological order.

On the risk itself, `residual_score` and `residual_band` remain null until the first event that computes them — a residual assessment, a mapping approval or retirement, a control attestation or retirement, or an inherent reassessment. Until then the risk carries only its inherent view.

Beyond assessment, the owner steers the risk through the rest of its cyclic lifecycle. Entering treatment moves `ASSESSED` → `TREATMENT` and is guarded twice: the risk's `residual_score` must be present, meaning at least one residual assessment exists, and at least one of the risk's treatment plans must be `APPROVED`; failing either condition the request is rejected with `ERR_INVALID_STATE`. Moving to monitoring, `TREATMENT` → `MONITORING`, requires that no tolerance breach for the risk is `OPEN` or `ACKNOWLEDGED` (`ERR_OPEN_BREACH_BLOCKING`) and that every treatment plan of the risk has reached `COMPLETED`, `REJECTED`, or `CANCELLED` (`ERR_ACTIVE_PLAN_BLOCKING`). Sending a `MONITORING` risk to `REASSESSMENT` is unconditional — the reassessment loop exists so a watched risk can be re-scored whenever conditions change, returning it to `MONITORING` through the inherent assessment described above.

Closing a risk is possible from `IDENTIFIED`, `ASSESSED`, `MONITORING`, or `REASSESSMENT` — never from `DRAFT` or `TREATMENT` — and is guarded by the same two conditions as monitoring: no treatment plan in `PROPOSED`, `APPROVED`, `IN_PROGRESS`, or `OVERDUE` may exist for the risk (`ERR_ACTIVE_PLAN_BLOCKING`), and no tolerance breach in `OPEN` or `ACKNOWLEDGED` may exist (`ERR_OPEN_BREACH_BLOCKING`). An `ACCEPTED` breach does not block closure. A `CLOSED` risk can be reopened to `IDENTIFIED` without preconditions; an optional `reason` may accompany the reopening, and the risk's scores, control mappings, and `kri_alert` are all preserved as the lifecycle resumes at `IDENTIFIED`. A risk's treatment plans, control mappings, and tolerance breaches can each be listed as collections of the risk.

### 3.3. The Control Library and Risk-Control Mapping

A `ControlOwner` maintains the control library. Creating a control requires a `name` and an `effectiveness_pct` — a decimal fraction greater than 0 and at most 1.00, with out-of-range values rejected as `ERR_SCORE_OUT_OF_RANGE` — plus an optional `description` and an optional `max_mapped_risks` capacity, an integer of at least 1 defaulting to 10. A new control is `PROPOSED` with its `mapped_active_count` at 0. Activation moves it `PROPOSED` → `ACTIVE`; placing it under review moves `ACTIVE` → `UNDER_REVIEW`; attestation moves `UNDER_REVIEW` → `ACTIVE` and carries a revised `effectiveness_pct` in the same range (`ERR_SCORE_OUT_OF_RANGE` otherwise) — attestation is the only path by which a control's effectiveness is ever revised. Retirement moves `ACTIVE` → `RETIRED`. A control's `mapped_active_count` reports how many mappings in `ACTIVE` status currently reference it.

Attestation and retirement both cascade into the register. On attestation, for every `ACTIVE` mapping referencing the control whose risk already has an inherent score, the risk's residual score is recomputed and appetite-breach evaluation runs — which may open a tolerance breach in `OPEN` status — and each touched risk's `version` increments by 1. On retirement, every `ACTIVE` mapping for the control becomes `RETIRED`, `mapped_active_count` drops to 0, and for each affected risk with an inherent score the same recomputation and evaluation run, again incrementing each touched risk's `version`.

Mapping a control onto a risk starts with the risk's owner, who proposes the pairing with a `control_id` and a `coverage_weight` — the decimal fraction, greater than 0 and at most 1.00, of that control's effectiveness that applies to this risk. The risk must be in `IDENTIFIED`, `ASSESSED`, `TREATMENT`, `MONITORING`, or `REASSESSMENT` — proposals against a `DRAFT` or `CLOSED` risk are rejected with `ERR_INVALID_STATE` — and the referenced control must exist (`ERR_NOT_FOUND`). If a `PROPOSED` or `ACTIVE` mapping already exists for the same risk-and-control pair, the proposal is rejected with `ERR_MAPPING_EXISTS`. A new mapping begins in `PROPOSED`, carrying its `risk_id` and `control_id`.

Approval belongs to a `RiskManager` and is guarded in two stages, control state first: the control must be `ACTIVE` (`ERR_CONTROL_NOT_ACTIVE`), and only then is capacity checked — the control's `mapped_active_count` must be strictly below its `max_mapped_risks`, or the approval fails with `ERR_CONTROL_CAPACITY_EXCEEDED`. Approving a mapping moves it `PROPOSED` → `ACTIVE`, increments `mapped_active_count` by 1, increments the control's `version` by 1, and — when the risk's inherent score is present — recomputes the risk's residual score and runs appetite-breach evaluation, incrementing the risk's `version` by 1. Retiring a mapping, likewise a `RiskManager` decision, moves `ACTIVE` → `RETIRED`, decrements `mapped_active_count` by 1, increments the control's `version`, and runs the same residual recomputation and appetite evaluation on the risk, which may open a tolerance breach in `OPEN` status and increments the risk's `version`. An approval followed by the retirement of the same mapping leaves the control's `mapped_active_count` exactly unchanged. The mappings referencing a control can be listed from the control side as well.

The residual score measures exposure after controls and uses a diminishing-returns discount. Only mappings in `ACTIVE` status whose control is `ACTIVE` or `UNDER_REVIEW` qualify; `RETIRED` mappings and `RETIRED` controls are excluded entirely. Each qualifying mapping contributes the product of its control's `effectiveness_pct` and the mapping's `coverage_weight`. The contributions are applied in descending order, largest first, with ties broken by the mapping's creation time, earliest first. Starting from an accumulated discount of zero, each contribution in turn discounts only the still-undiscounted remainder: the accumulated discount grows by the contribution multiplied by one minus the accumulated discount so far. The total discount is capped at 0.90 — controls can never zero out a risk. The `residual_score` is then the `inherent_score` multiplied by one minus the final discount, rounded up to a whole number, with a value that is already whole left unchanged; if the result would be less than 1, the residual score is 1. When no qualifying mapping exists, the discount is zero and the residual score equals the inherent score. The `residual_band` applies the same four band edges as the inherent view. Because each further control discounts only what earlier controls left, the post-control residual view diverges from the pre-control inherent view whenever at least one `ACTIVE` mapping exists.

### 3.4. Tolerance Breaches: Escalation and Disposition

Appetite-breach evaluation runs after every residual-score recomputation, whatever triggered it. The evaluation locates the appetite statement for the risk's category that is `APPROVED` and whose half-open effectiveness window contains the current logical clock; when no such statement exists, no breach is possible. When one exists, the risk breaches appetite the moment its `residual_score` is greater than or equal to the statement's `tolerance_score` — equality with the tolerance is a breach. Provided no tolerance breach for the risk already exists in `OPEN`, `ACKNOWLEDGED`, or `ACCEPTED` status, the system then creates a ToleranceBreach in `OPEN` status, linked to the triggering statement through `appetite_statement_id` and to the risk through `risk_id`, and records the offending score in `residual_at_breach`. When the residual score is below the tolerance, no breach is created.

Disposition follows a strict chain. Acknowledging a breach, moving `OPEN` → `ACKNOWLEDGED`, belongs to the breached risk's owner — any other caller receives `ERR_OWNER_MISMATCH`. Resolving a breach, moving `ACKNOWLEDGED` → `RESOLVED`, likewise belongs to that owner and additionally requires the risk's `residual_score` at resolve time to be strictly below the linked statement's `tolerance_score`; a premature resolution is rejected with `ERR_BREACH_RESOLUTION_PREMATURE`. `RESOLVED` is terminal. Accepting a breach, moving `ACKNOWLEDGED` → `ACCEPTED`, is a `RiskManager` decision guarded by the acceptance cap: the risk's `residual_score` must be at most the linked statement's `acceptance_cap_score`, or the acceptance is rejected with `ERR_ACCEPTANCE_CAP_EXCEEDED`. Acceptance also requires a `rationale` and a `review_by` instant strictly after the current logical clock; a missing rationale or a `review_by` not in the future fails with `ERR_INVALID_REQUEST`.

Acceptance is never permanent. Once the logical clock reaches or passes `review_by`, an `ACCEPTED` breach automatically re-opens to `OPEN` — through the clock sweep and through lazy evaluation whenever the breach is read — with the `rationale` and `review_by` retained for audit. Breaches are visible in context: each risk exposes its own breach list, and each appetite statement exposes the breaches linked to it.

Open escalation blocks register hygiene. As §3.2 states, a tolerance breach in `OPEN` or `ACKNOWLEDGED` status blocks both the move to monitoring and closure of the risk with `ERR_OPEN_BREACH_BLOCKING`; an `ACCEPTED` breach blocks neither.

### 3.5. Treatment Plans, Actions, and Budget Reservations

Treatment planning begins when the risk's owner proposes a plan under a risk, supplying a `title`, a `budget_cents` amount in whole cents strictly greater than 0, a `due_date` strictly after the current logical clock (`ERR_INVALID_REQUEST` otherwise), the `owner_user_id` of the treatment owner who will execute the plan, and the concurrency field `expected_risk_version` (§2.7). The parent risk must be in `ASSESSED`, `TREATMENT`, `MONITORING`, or `REASSESSMENT`; proposing under any other risk status is rejected with `ERR_INVALID_STATE`. The creator's identifier is recorded as `proposer_user_id`, which anchors segregation of duties at decision time. A new plan is `PROPOSED` with `priority` `STANDARD`, `extension_count` 0, and `progress_pct` 0.00, and the parent risk's `version` increments by 1.

A `RiskManager` decides proposals. Approval moves `PROPOSED` → `APPROVED` under three guards evaluated in precedence order: the risk-state guard first (the parent risk must be in `ASSESSED`, `TREATMENT`, `MONITORING`, or `REASSESSMENT`, else `ERR_INVALID_STATE`), then segregation of duties (the approver must differ from `proposer_user_id`, else `ERR_SOD_VIOLATION`), and finally the budget guard, always last — the risk's `available_treatment_cents` must be at least the plan's `budget_cents`, or the approval fails with `ERR_BUDGET_EXCEEDED`. On approval the plan's `budget_cents` is added to the risk's `reserved_treatment_cents`, and the risk's `version` increments by 1. Rejection moves `PROPOSED` → `REJECTED`, requires only the segregation-of-duties guard, and accepts an optional `reason`. `COMPLETED`, `REJECTED`, and `CANCELLED` are the plan's terminal states.

Budget accounting is exact integer arithmetic on a reservation ledger. A risk's `reserved_treatment_cents` is always the sum of `budget_cents` over its plans in `APPROVED`, `IN_PROGRESS`, or `OVERDUE`, and its `available_treatment_cents` is `treatment_budget_cents` minus that reservation. Completion or cancellation releases the reservation by subtracting the plan's `budget_cents`; an approval followed by its compensating cancellation leaves `reserved_treatment_cents` and `available_treatment_cents` exactly unchanged. An `OVERDUE` plan remains reserved — slippage does not free budget.

Execution belongs to the plan's treatment owner, and every execution step requires the caller's `X-User-ID` to equal the plan's `owner_user_id` (`ERR_OWNER_MISMATCH`). Starting moves `APPROVED` → `IN_PROGRESS`. Completing moves `IN_PROGRESS` → `COMPLETED` and requires the plan to have at least one action with every action in `DONE` status; otherwise the completion is rejected with `ERR_INCOMPLETE_ACTIONS`. Completion releases the reservation and increments the risk's `version`. Cancellation moves a plan from `APPROVED`, `IN_PROGRESS`, or `OVERDUE` to `CANCELLED`, accepts an optional `reason`, releases the reservation, and increments the risk's `version`. When the logical clock passes a plan's `due_date` — through the sweep or through lazy evaluation on read — an `IN_PROGRESS` plan slips to `OVERDUE` with its reservation and `priority` untouched. Extending moves `OVERDUE` → `IN_PROGRESS` under two guards: the plan's `extension_count` must still be below 3, permitting at most three extensions and rejecting a fourth with `ERR_PLAN_EXTENSION_LIMIT`, and the supplied `new_due_date` must be strictly after the current logical clock (`ERR_INVALID_REQUEST`). A successful extension sets `due_date` to `new_due_date` and increments `extension_count` by 1.

Plans decompose into actions. The plan's owner adds an action by `title` while the plan is `APPROVED` or `IN_PROGRESS`; against any other plan status the addition is rejected with `ERR_INVALID_STATE`. Each new action is `PENDING` and carries the `plan_id` of its parent. Marking an action done, `PENDING` → `DONE`, requires the parent plan to be `IN_PROGRESS` (`ERR_INVALID_STATE` otherwise) and the caller to be the plan's owner (`ERR_OWNER_MISMATCH`). Both action creation and action completion recompute the plan's `progress_pct`: one hundred multiplied by the number of `DONE` actions divided by the total number of actions, rounded half-up to two decimal places — and exactly 0.00 when the plan has no actions at all. A plan's action list can be browsed independently.

### 3.6. Key Risk Indicators and Alert Cascades

A `RiskManager` registers a key risk indicator with its `category_id`, a `name`, a `direction` of `ABOVE` or `BELOW`, an `amber_threshold`, a `red_threshold`, and optionally a `min_observation_interval_days` (an integer of at least 0, defaulting to 1) and a free-text `unit` label. Threshold ordering depends on direction: an `ABOVE` indicator requires the amber threshold to be strictly below the red threshold, while a `BELOW` indicator requires amber strictly above red; either violation is rejected with `ERR_THRESHOLD_ORDER_INVALID`.

Every indicator carries two parallel state dimensions. The lifecycle dimension, `status`, is linear: `DRAFT` → `ACTIVE` on activation, and `ACTIVE` → `RETIRED` on retirement, both `RiskManager` decisions. The breach dimension, `current_breach_status`, is cyclic across `NORMAL`, `AMBER_BREACH`, and `RED_BREACH`, starts at `NORMAL`, and is driven solely by observations — it may change only while the indicator is `ACTIVE`, and retirement freezes it at its last value. Reading an indicator returns both dimensions along with `last_observation_at`, which is null until the first observation lands.

Recording an observation is a `RiskManager` act carrying an `observed_value` and an `observed_at` instant. Three guards apply, in precedence order: the indicator must be `ACTIVE` (`ERR_KRI_NOT_ACTIVE`), the observation must not lie in the future relative to the logical clock (`ERR_OBSERVATION_IN_FUTURE`), and `observed_at` must be strictly after `last_observation_at` with a gap of at least `min_observation_interval_days` days since that last observation (`ERR_OBSERVATION_TOO_SOON`). The stored observation is immutable, recording its `kri_id`, its inputs, and the computed `resulting_breach_status`; the indicator's `last_observation_at` advances to the new `observed_at`, and the indicator's observations are listed chronologically by `observed_at`.

Breach evaluation uses strict comparisons — equality with a threshold is never a breach of that band. For an `ABOVE` indicator, the result is `RED_BREACH` when the observed value is strictly greater than the red threshold, `AMBER_BREACH` when it is strictly greater than the amber threshold and at most the red threshold, and `NORMAL` otherwise. For a `BELOW` indicator, the result is `RED_BREACH` when the value is strictly less than the red threshold, `AMBER_BREACH` when it is strictly less than the amber threshold and at least the red threshold, and `NORMAL` otherwise. Red wins whenever both bands could match.

A red result fires the alert cascade: every risk in the indicator's category whose status is `ASSESSED`, `TREATMENT`, `MONITORING`, or `REASSESSMENT` has its `kri_alert` raised to true and its `version` incremented by 1, and every treatment plan of those risks in `APPROVED`, `IN_PROGRESS`, or `OVERDUE` ratchets its `priority` to `URGENT` with its `version` incremented by 1. A normal result clears `kri_alert` to false on those same risks — subject to the register-wide invariant that `kri_alert` is true while any `ACTIVE` indicator in the risk's category is in `RED_BREACH`, so the clear applies only when no other active indicator in the category remains red — but plan priorities are never lowered: the `URGENT` ratchet is one-way. An amber result changes nothing beyond the indicator's own breach dimension.

### 3.7. Emerging Risks and Scenario Analysis

Horizon scanning feeds the register through emerging risks, which either a `RiskManager` or a `RiskOwner` may register with a `category_id`, a `title`, a `scenario_severity` and a `scenario_probability` — each an integer from 1 to 5 inclusive, with out-of-range values rejected as `ERR_SCORE_OUT_OF_RANGE` — plus an optional `stress_factor` multiplier between 0.5 and 3.0 inclusive, defaulting to 1.0, and an optional `description` for the scan notes. Registration computes the `scenario_score`: severity multiplied by probability multiplied by the stress factor, rounded half-up to a whole number. A new emerging risk is `DRAFT`.

Triage belongs to a `RiskManager`. Validation moves `DRAFT` → `VALIDATED`. Dismissal moves either `DRAFT` or `VALIDATED` to `DISMISSED` and accepts an optional `reason`. Promotion moves `VALIDATED` → `PROMOTED` and is gated on the scenario analysis: the `scenario_score` must be at least 10, or the promoter must set `force` to true together with a non-empty `rationale`; a promotion that satisfies neither branch is rejected with `ERR_EMERGING_SCORE_BELOW_THRESHOLD`.

Promotion materializes the threat on the register: a new Risk is created in `DRAFT` status with its `category_id` and `title` copied from the emerging risk, its `owner_user_id` taken from the promotion payload, and its `source_emerging_risk_id` set to the promoted emerging risk's `id`. The created Risk — not the emerging risk — is the resource returned by the promotion. An emerging risk's promoted-from risks can be listed, and the list holds at most one entry.

### 3.8. Board Reporting and Aggregation

A `BoardReporter` compiles board risk reports. Creating a report requires a `period_start` and a `period_end` forming a closed interval — both boundary dates are included, and a `period_end` earlier than `period_start` is rejected with `ERR_INVALID_REQUEST` — plus a `variant` of `PROVISIONAL` or `FINAL` that is immutable once chosen. The new report is a `DRAFT` whose aggregation snapshot is computed at creation time. Creation also supersedes stale drafts: any older `DRAFT` report whose closed period overlaps the new report's closed period is automatically moved to `CANCELLED`, and because report periods are closed intervals, a shared boundary date counts as an overlap. The superseding draft is always created successfully; creating a report that overlaps a `FINALIZED` one is not rejected — that conflict is enforced at finalization instead.

Finalization, likewise a `BoardReporter` act, moves `DRAFT` → `FINALIZED` and is rejected with `ERR_REPORT_PERIOD_OVERLAP` when any other `FINALIZED` report's closed period overlaps this report's closed period, again counting a shared boundary date as overlap. On finalization the aggregation is recomputed authoritatively and then frozen: `heat_score_total`, `category_breakdown`, and `band_counts` never change afterward, no matter how the register moves.

Aggregation works as follows. Included risks are exactly those in `ASSESSED`, `TREATMENT`, `MONITORING`, or `REASSESSMENT`; `DRAFT`, `IDENTIFIED`, and `CLOSED` risks are excluded, and each included risk is counted under its own category. The per-risk metric depends on the variant: a `PROVISIONAL` report uses each risk's `inherent_score`, while a `FINAL` report uses each risk's `residual_score`, falling back to `inherent_score` when the residual is null. For each category containing at least one included risk, the metric values of the category's included risks are summed, the sum is multiplied by the category's `weight_factor`, and the product is rounded half-up to two decimal places to form that category's heat score — the per-category rounding happens first, before any summation across categories. The `heat_score_total` is then the sum of those already-rounded per-category heat scores, itself rounded half-up to two decimal places. The `category_breakdown` is a list with one object per contributing category carrying its `category_id`, its `risk_count` of included risks, and its `heat_score`, sorted by `heat_score` descending with ties broken by the category's `created_at`, earliest first. The `band_counts` tally the included risks per band — `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` — of the variant's metric using the standard band edges of §2.6. Because the two variants read different metrics, identical register data yields a different `heat_score_total` for the two variants whenever any mapped control is discounting a risk.

## 4. Endpoint Definitions

Operations that create a new resource — whether a top-level resource or a new member of a parent's collection, such as an assessment, an observation, a plan, an action, or a mapping — return a `201 Created` status code, as does emerging-risk promotion, which returns the newly created Risk. Operations that modify an existing resource in place, including all lifecycle transitions, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/categories` | Create a taxonomy category (root when `parent_category_id` omitted) | RiskManager |
| GET | `/categories` | List categories, filterable by `parent_category_id` (paginated) | All roles |
| GET | `/categories/{id}` | Get a category | All roles |
| PATCH | `/categories/{id}` | Reparent a category (rejected on self/descendant cycles) | RiskManager |
| GET | `/categories/{id}/subcategories` | List direct children of a category | All roles |
| GET | `/categories/{id}/risks` | List risks in a category, filterable by `status` | All roles |
| GET | `/categories/{id}/appetite-statements` | List appetite statements of a category | All roles |
| GET | `/categories/{id}/kris` | List KRIs of a category | All roles |
| GET | `/categories/{id}/emerging-risks` | List emerging risks of a category | All roles |
| POST | `/risks` | Create a risk (status `DRAFT`) | RiskOwner |
| GET | `/risks` | List risks, filterable by `category_id`, `status`, `residual_band` (paginated) | All roles |
| GET | `/risks/{id}` | Get a risk with computed fields | All roles |
| POST | `/risks/{id}/submit` | Move `DRAFT` → `IDENTIFIED` | RiskOwner |
| POST | `/risks/{id}/assessments` | Create an `INHERENT` or `RESIDUAL` assessment (OCC-guarded); may transition the risk and open a breach | RiskOwner |
| GET | `/risks/{id}/assessments` | List assessments of a risk (chronological) | All roles |
| POST | `/risks/{id}/enter-treatment` | Move `ASSESSED` → `TREATMENT` (requires residual score and an `APPROVED` plan) | RiskOwner |
| POST | `/risks/{id}/monitor` | Move `TREATMENT` → `MONITORING` (guarded by breaches and plans) | RiskOwner |
| POST | `/risks/{id}/reassess` | Move `MONITORING` → `REASSESSMENT` | RiskOwner |
| POST | `/risks/{id}/close` | Move `IDENTIFIED`/`ASSESSED`/`MONITORING`/`REASSESSMENT` → `CLOSED` (guarded) | RiskOwner |
| POST | `/risks/{id}/reopen` | Move `CLOSED` → `IDENTIFIED` | RiskOwner |
| GET | `/risks/{id}/treatment-plans` | List treatment plans of a risk | All roles |
| GET | `/risks/{id}/control-mappings` | List control mappings of a risk | All roles |
| GET | `/risks/{id}/tolerance-breaches` | List tolerance breaches of a risk | All roles |
| POST | `/risks/{id}/control-mappings` | Propose a control mapping for this risk | RiskOwner |
| POST | `/risks/{id}/treatment-plans` | Propose a treatment plan (OCC-guarded) | RiskOwner |
| POST | `/controls` | Create a control (status `PROPOSED`) | ControlOwner |
| GET | `/controls/{id}` | Get a control | All roles |
| POST | `/controls/{id}/activate` | Move `PROPOSED` → `ACTIVE` | ControlOwner |
| POST | `/controls/{id}/review` | Move `ACTIVE` → `UNDER_REVIEW` | ControlOwner |
| POST | `/controls/{id}/attest` | Move `UNDER_REVIEW` → `ACTIVE` with revised effectiveness; cascades residual recompute | ControlOwner |
| POST | `/controls/{id}/retire` | Move `ACTIVE` → `RETIRED`; retires all `ACTIVE` mappings and recomputes residuals | ControlOwner |
| GET | `/controls/{id}/control-mappings` | List mappings referencing a control | All roles |
| POST | `/control-mappings/{id}/approve` | Move `PROPOSED` → `ACTIVE` (capacity- and control-state-guarded) | RiskManager |
| POST | `/control-mappings/{id}/retire` | Move `ACTIVE` → `RETIRED` | RiskManager |
| POST | `/appetite-statements` | Create an appetite statement (`DRAFT`); window overlap vs `APPROVED` statements checked at create | RiskManager |
| GET | `/appetite-statements/{id}` | Get an appetite statement | All roles |
| POST | `/appetite-statements/{id}/approve` | Move `DRAFT` → `APPROVED` (segregation of duties + window re-check) | RiskManager |
| POST | `/appetite-statements/{id}/retire` | Move `APPROVED` → `RETIRED` (requires remaining effective coverage) | RiskManager |
| GET | `/appetite-statements/{id}/tolerance-breaches` | List breaches linked to an appetite statement | All roles |
| GET | `/treatment-plans/{id}` | Get a treatment plan (lazily evaluates overdue slippage) | All roles |
| POST | `/treatment-plans/{id}/approve` | Move `PROPOSED` → `APPROVED` (state, segregation-of-duties, budget guards) | RiskManager |
| POST | `/treatment-plans/{id}/reject` | Move `PROPOSED` → `REJECTED` (segregation of duties) | RiskManager |
| POST | `/treatment-plans/{id}/start` | Move `APPROVED` → `IN_PROGRESS` (owner only) | RiskOwner |
| POST | `/treatment-plans/{id}/complete` | Move `IN_PROGRESS` → `COMPLETED` (requires at least one action, all `DONE`) | RiskOwner |
| POST | `/treatment-plans/{id}/cancel` | Move `APPROVED`/`IN_PROGRESS`/`OVERDUE` → `CANCELLED` | RiskOwner |
| POST | `/treatment-plans/{id}/extend` | Move `OVERDUE` → `IN_PROGRESS` with a new due date (at most three extensions) | RiskOwner |
| POST | `/treatment-plans/{id}/actions` | Add an action to a plan (plan must be `APPROVED` or `IN_PROGRESS`) | RiskOwner |
| GET | `/treatment-plans/{id}/actions` | List actions of a plan | All roles |
| POST | `/treatment-actions/{id}/done` | Move `PENDING` → `DONE` (plan must be `IN_PROGRESS`) | RiskOwner |
| GET | `/tolerance-breaches/{id}` | Get a breach (lazily evaluates review expiry) | All roles |
| POST | `/tolerance-breaches/{id}/acknowledge` | Move `OPEN` → `ACKNOWLEDGED` (risk owner) | RiskOwner |
| POST | `/tolerance-breaches/{id}/resolve` | Move `ACKNOWLEDGED` → `RESOLVED` (residual must be below tolerance) | RiskOwner |
| POST | `/tolerance-breaches/{id}/accept` | Move `ACKNOWLEDGED` → `ACCEPTED` (capped; requires rationale and review date) | RiskManager |
| POST | `/kris` | Create a KRI (lifecycle `DRAFT`, breach dimension `NORMAL`) | RiskManager |
| GET | `/kris/{id}` | Get a KRI (both state dimensions) | All roles |
| POST | `/kris/{id}/activate` | Move `DRAFT` → `ACTIVE` | RiskManager |
| POST | `/kris/{id}/retire` | Move `ACTIVE` → `RETIRED` (freezes the breach dimension) | RiskManager |
| POST | `/kris/{id}/observations` | Record an observation; evaluates the breach dimension and fires the red cascade | RiskManager |
| GET | `/kris/{id}/observations` | List observations of a KRI (chronological by `observed_at`) | All roles |
| POST | `/reports` | Create a report (`DRAFT`) with a snapshot; an overlapping older draft is auto-cancelled | BoardReporter |
| GET | `/reports/{id}` | Get a report with its snapshot fields | All roles |
| POST | `/reports/{id}/finalize` | Move `DRAFT` → `FINALIZED`; recomputes and freezes the snapshot; closed-period overlap with finalized reports rejected | BoardReporter |
| POST | `/emerging-risks` | Register an emerging risk with scenario analysis (`DRAFT`) | RiskManager, RiskOwner |
| GET | `/emerging-risks/{id}` | Get an emerging risk | All roles |
| GET | `/emerging-risks/{id}/risks` | List register risks promoted from this emerging risk (0 or 1) | All roles |
| POST | `/emerging-risks/{id}/validate` | Move `DRAFT` → `VALIDATED` | RiskManager |
| POST | `/emerging-risks/{id}/promote` | Move `VALIDATED` → `PROMOTED`; creates a register Risk (`DRAFT`) | RiskManager |
| POST | `/emerging-risks/{id}/dismiss` | Move `DRAFT`/`VALIDATED` → `DISMISSED` | RiskManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; advancing sweeps overdue plans and re-opens lapsed accepted breaches | RiskManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNER_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ASSESSMENT_KIND_NOT_ALLOWED` | 409 |
| `ERR_KRI_NOT_ACTIVE` | 409 |
| `ERR_SOD_VIOLATION` | 422 |
| `ERR_SCORE_OUT_OF_RANGE` | 422 |
| `ERR_TOLERANCE_OUT_OF_RANGE` | 422 |
| `ERR_THRESHOLD_ORDER_INVALID` | 422 |
| `ERR_CATEGORY_CYCLE` | 422 |
| `ERR_MAPPING_EXISTS` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_NO_APPETITE_COVERAGE` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
| `ERR_OBSERVATION_TOO_SOON` | 409 |
| `ERR_OBSERVATION_IN_FUTURE` | 422 |
| `ERR_CONTROL_NOT_ACTIVE` | 409 |
| `ERR_CONTROL_CAPACITY_EXCEEDED` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_OPEN_BREACH_BLOCKING` | 409 |
| `ERR_ACTIVE_PLAN_BLOCKING` | 409 |
| `ERR_PLAN_EXTENSION_LIMIT` | 409 |
| `ERR_INCOMPLETE_ACTIONS` | 409 |
| `ERR_ACCEPTANCE_CAP_EXCEEDED` | 422 |
| `ERR_BREACH_RESOLUTION_PREMATURE` | 409 |
| `ERR_EMERGING_SCORE_BELOW_THRESHOLD` | 422 |
