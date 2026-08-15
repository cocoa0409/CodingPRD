# Legal Ops Matter Analytics API — Product Requirements Document

## 1. Introduction

Corporate legal departments increasingly run like businesses: they carry budgets, manage a panel of outside counsel firms, allocate in-house lawyers across a portfolio of matters, and answer to executives who expect the same analytical rigor that finance applies to its own books. This document specifies the Legal Ops Matter Analytics API, the system of record for a legal department's matter portfolio, spend ledger, and performance scorecard. All resources are mounted under the `/legal-ops` prefix.

The API covers the full operating cycle of the department. A taxonomy of practice areas and matter types gives every matter a clean classification, which is the foundation of data hygiene for all downstream reporting. Budgets are carved out per fiscal period at the practice-area or matter-type grain; outside counsel invoices flow through submission, approval, and payment against recorded accruals; and every payment posts to an immutable spend ledger from which all aggregates are derived. On top of this operational core sit the analytical surfaces leadership consumes: workload utilization per in-house counsel, an insource-versus-outsource cost model per matter, cycle-time benchmarking by matter type, spend reporting by practice area and by firm, a self-service deflection rate that tracks technology adoption, and a publishable executive dashboard whose frozen snapshots anchor annual planning.

The system is deliberately opinionated about fiscal discipline. Writes are gated by the state of the fiscal calendar, invoice payment cascades update matter, period, and budget aggregates immediately, budget posture is a derived signal driven by department-set thresholds, and a fixed validation order determines which error a premature or malformed request receives.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API. Business workflows live in §3; everything here is cross-cutting.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly three roles:

- `LegalOpsManager` — owns the taxonomy (practice areas, matter types), the fiscal calendar, budgets, the outside counsel firm lifecycle, dashboard publishing, invoice payment, and the logical clock; the segregation-of-duties counterpart to the analyst.
- `LegalOpsAnalyst` — the day-to-day operator: matters, assignments, accruals, invoices (submission, approval, rejection), period soft-close, and dashboard drafting. An analyst cannot pay invoices or manage the taxonomy.
- `LegalOpsExecutive` — a read-only consumer of dashboards, reports, and drill-downs, with no write operations of its own.

A request missing either header, or carrying malformed header values, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-authenticated request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

For all three roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against a resource's `id` for ownership purposes. The identifier resurfaces in exactly one place: when an analyst submits an invoice, the server records the submitter's `X-User-ID` as the invoice's creator, and the segregation-of-duties check at approval time compares the approver's `X-User-ID` against that recorded creator (see §3.5).

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
- Two transport-level rejections use the same envelope: a request to an undefined path yields `ERR_NOT_FOUND` (HTTP 404), and a defined path reached with an unsupported method yields `ERR_INVALID_REQUEST` with HTTP status 405.

---

### 2.3. Pagination

List endpoints accept two query parameters. `limit` sets the maximum number of items returned: when omitted it defaults to 10, and it may range from a minimum of 1 to a maximum of 100. `offset` sets how many items are skipped and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order; resources whose `created_at` timestamps coincide — common under the logical clock — fall back to creation (insertion) order.

Paginated list responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

All primary resources — departments, fiscal periods, practice areas, matter types, firms, counsel, matters, assignments, budgets, accruals, invoices, and dashboards — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by exactly one on every mutation — including mutations driven by cascade side effects, so an invoice payment that recomputes a matter's aggregates also bumps that matter's `version`.

Spend lines are the single exception. As immutable entries in an append-only ledger, a spend line carries only `id` and `created_at`; both `updated_at` and `version` are absent, because a posted ledger row is never modified.

### 2.5. Fiscal Calendar Discipline

The fiscal calendar governs which writes the department accepts. A fiscal period moves through `OPEN`, `SOFT_CLOSED`, `HARD_CLOSED`, and — when a hard-closed period is brought back — `REOPENED`. Operational writes against a period are accepted only while that period is `OPEN` or `REOPENED`. This gate covers eight operations: creating a matter in the period, creating an accrual in it, submitting an invoice into it, activating a matter, resuming a held matter, approving an invoice, paying an invoice, and releasing an accrual. Against a period in any other state, these writes fail with `ERR_PERIOD_CLOSED` (HTTP 409).

The legal department maintains `active_fiscal_period_id`, a computed pointer to the single period currently in `OPEN` status, or null when no period — or more than one period — is currently `OPEN`. Departments can be listed with an `active_fiscal_period_id` filter to locate the department attached to a given open period quickly.

### 2.6. The Logical Clock

The server runs on a logical clock rather than wall-clock time. At server start, the logical clock reads exactly 2026-08-01T00:00:00Z, and it must never silently fall back to the host's wall clock. A `LegalOpsManager` may set it through an administrative test-driving capability that accepts a target instant in the `to_iso8601` field and reports the resulting `current_utc`. All state-transition timestamps — including the activation and close timestamps from which a matter's `cycle_days` is derived — are taken from this logical clock, as is every other timestamp the server emits (the envelope's `api_request_timestamp`, `created_at`, and `updated_at`). A clock-set request whose `to_iso8601` is missing or unparseable is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a value supplied without an explicit offset is interpreted as UTC, and the response reports the resulting `current_utc` as an ISO 8601 UTC timestamp, with fractional seconds shown only when non-zero.

### 2.7. Budget Posture Governance

Every budget continuously derives a `posture` from the ratio of its `consumed_cents` to its `allocated_cents`, compared against the department's two thresholds (when several departments exist, the thresholds of the earliest-created department govern). The ratio is compared as an exact rational value — it is never rounded before comparison. When `allocated_cents` is zero and nothing has been consumed, the ratio is treated as zero; when the allocation is zero but consumption is positive, the ratio is treated as infinitely large. A ratio of at least 1.0 yields `EXCEEDED`; failing that, a ratio of at least `budget_critical_pct` yields `CRITICAL`; failing that, a ratio of at least `budget_warning_pct` yields `WARNING`; anything lower is `OK`. All three comparisons are inclusive at the boundary — an exact tie resolves toward the more severe posture.

Posture is re-derived after every spend-line insert, after every change to a budget's `allocated_cents`, and after any change to the department's threshold percentages. A consumption row matches a budget when the spend line is `POSTED`, sits in the budget's fiscal period, and — through the matter the line belongs to — resolves to the budget's practice area and matter type; a budget whose `matter_type_id` is null matches every matter type within its practice area.

Independently of posture, invoice payment is subject to a hard fiscal cap: payment may not push a matching budget's consumption past its allocation by more than a fixed overrun allowance of ten percent (see §3.5).

### 2.8. The Spend Ledger and Derived Aggregates

All money movement materializes as rows in an append-only spend ledger. A spend line records the `matter_id`, `fiscal_period_id`, and `firm_id` it belongs to, the `invoice_id` it was generated from, a `posting_date`, a positive `amount_cents`, a `source_status` of `POSTED` or `REVERSED`, and — for reversal entries — a `reversal_of_id` pointing at the line it reverses. Lines whose `source_status` is `REVERSED` are excluded from every aggregate in the system. The ledger is read-only through the API; rows can be listed and filtered by `matter_id`, `fiscal_period_id`, `firm_id`, `invoice_id`, `source_status`, or `reversal_of_id`.

Aggregates are derived from the ledger, never independently stored truths. A matter's `actual_spend_cents` sums posted ledger amounts for that matter; a period's `total_actual_spend_cents` sums posted lines whose `posting_date` falls within the period's inclusive date range; a budget's `consumed_cents` sums posted lines matching its grain. Accrual-side aggregates — a matter's `accrual_outstanding_cents` and a period's `total_accrual_cents` — sum only accruals still in `OUTSTANDING` status. Whenever a cascade recomputes one of these derived fields on a parent resource and the recomputed value differs from the stored one, that recomputation is itself a mutation of the parent: its `updated_at` refreshes and its `version` increments, per §2.4. A recomputation that arrives at the already-stored values performs no mutation, and the parent's `version` does not move.

### 2.9. Monetary Values, Percentages, and Rounding

All monetary amounts are integer cents. Fields such as `amount_cents`, `allocated_cents`, `budget_cents`, and `blended_hourly_rate_cents` carry whole numbers of cents, and integer arithmetic is used end to end — no rounding occurs anywhere in the money path.

Percentage-style outputs follow a pinned rounding order. `utilization_pct`, `budget_accuracy_pct`, and `deflection_rate_pct` are each computed as a fraction, multiplied by one hundred, rounded half-up to two decimal places, and then divided by one hundred — so the stored value is expressed as a fraction (0.95 means ninety-five percent) carrying at most two decimal places. `mean_cycle_days`, a day figure rather than a percentage, instead sums whole days first, divides once by the count of qualifying matters, and rounds the resulting quotient half-up to two decimal places. Threshold inputs such as `budget_warning_pct` are stored exactly as supplied, at input precision.

### 2.10. Nested Resource Retrieval

When an endpoint path contains multiple resource identifiers — for example a matter type beneath a practice area, or an assignment beneath a matter — the server validates the identifiers strictly left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. A request targeting an assignment under a matter that does not exist therefore reports the missing matter before the assignment is ever consulted. References supplied in a request body (the foreign keys of a creation payload) are validated for existence at the same stage, before any business rule runs.

### 2.11. Optimistic Concurrency Control

Three write operations let the caller prove it has observed the current state of the resource it modifies, by sending that resource's last-seen `version` in the request body. On all three the field is optional: when supplied it must equal the resource's current `version`, and when it is omitted no version comparison runs.

- Updating a budget's allocation accepts `expected_budget_version`. If it is supplied and does not equal the budget's current `version`, the update is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the serialization point against cascaded recomputes: an invoice payment can bump a budget's `version` between the client's read and its write, and the stale write must not silently overwrite that drift.
- Closing a matter accepts `expected_matter_version`, compared the same way against the matter's current `version`; a supplied mismatched value is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Publishing a dashboard accepts `expected_dashboard_version`, guarding against a peer having published a different snapshot for the same period in between — an event that would have cascaded this dashboard to `SUPERSEDED` and advanced its `version`. A supplied mismatched value is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint consults a version field — one supplied elsewhere is simply ignored; all remaining writes rely on state validation alone.

### 2.12. Validation Order

Every request is checked against a fixed pipeline, and the order is part of the contract:

1. Authentication — missing or malformed headers yield `ERR_UNAUTHENTICATED`.
2. Authorization — an unauthorized role yields `ERR_FORBIDDEN`.
3. Existence — path identifiers, validated left to right, and body-supplied references yield `ERR_NOT_FOUND`.
4. State eligibility — for the action endpoints (activate, hold, resume, close, reopen, archive, soft-close, hard-close, approve, pay, reject, release, publish), a target resource that is not in a state from which the requested transition is defined yields `ERR_INVALID_STATE` (HTTP 409).
5. Business rules, each in the rule-specific order given in §3 — for example, segregation of duties is evaluated before the period-write gate on invoice approval, and taxonomy consistency is evaluated before period status, entity activity, uniqueness, and amount checks on matter creation and update.
6. Optimistic-concurrency verification — `ERR_STALE_VERSION` — which runs after state and amount checks: a close attempted against an already-closed matter reports `ERR_INVALID_STATE` rather than `ERR_STALE_VERSION`, and a budget patch carrying a negative allocation reports `ERR_INVALID_AMOUNT` before any version comparison happens.
7. Payload shape — missing required fields, wrong scalar types, or malformed values yield `ERR_INVALID_REQUEST` (HTTP 400) as the final gate, so a request that fails a business rule never masquerades as a 400.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Department: Configuration, Taxonomy, and Rosters

A `LegalOpsManager` begins by creating the legal department itself, supplying a `name` of one to two hundred characters and, optionally, three governance percentages. `budget_warning_pct` defaults to 0.8 — when consumption reaches eighty percent of a budget's allocation, that budget's posture flips to `WARNING`. `budget_critical_pct` defaults to 0.95 and must sit strictly above the warning level; reaching it marks the budget `CRITICAL`. Both budget thresholds must be greater than zero and at most 1.0. `deflection_target_pct`, defaulting to 0.30, sets the department's self-service deflection goal — the share of matters the department aims to resolve without outside counsel, against which leadership compares the measured `deflection_rate_pct`; unlike the budget thresholds it may be set to zero, though it too may not exceed 1.0. Violating any of these threshold constraints — on creation or on later adjustment — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A manager may later adjust any of the three thresholds; doing so immediately re-derives the posture of every budget sitting in the department's fiscal periods, per §2.7. A threshold update that supplies any of the three fields bumps the department's `version` and triggers the re-derivation even when the supplied values equal the stored ones.

Next comes the taxonomy. A practice area carries a stable `code` — two to eight uppercase alphanumeric characters, unique across all practice areas — plus a human-readable `display_name`, and begins life `ACTIVE`. Beneath each practice area, matter types carry their own `code` (unique within the owning practice area), a `display_name`, and an optional `default_budget_cents`, used when a matter is created without an explicit budget and itself defaulting to zero; a negative `default_budget_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). When creating a matter type, the payload's `practice_area_id` must agree with the practice area named in the path; because uniqueness is checked earlier in the pipeline, a duplicated `code` within the practice area surfaces as `ERR_DUPLICATE` (HTTP 409), while a disagreement between body and path is rejected with `ERR_PARENT_MISMATCH` (HTTP 422). Practice areas can be listed filtered by `status`. Archiving a practice area flips it to `ARCHIVED`, after which it rejects new matters — existing matters are untouched.

Outside counsel firms are registered with a unique `name`, a benchmark `tier` of `TIER_1`, `TIER_2`, or `TIER_3` used to frame benchmark cohorts, and a `blended_hourly_rate_cents` of zero or more — a negative rate is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — that feeds the insource-versus-outsource model. Firms start `ACTIVE`; suspending one moves it to `SUSPENDED` — the only firm transition the API exposes — and a suspended firm can no longer receive new invoices. The firm roster can be listed filtered by `tier` or `status`.

In-house counsel join the roster with a `full_name`, a unique `email`, an `annual_capacity_hours` strictly greater than zero, and a `loaded_hourly_cost_cents` of zero or more used by the same cost model; a capacity of zero or less, or a negative cost, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Counsel begin `ACTIVE`, and the API exposes no counsel lifecycle transition; the roster can be listed filtered by `status`.

Uniqueness is enforced across the board at creation time with `ERR_DUPLICATE`: the department `name`, each practice-area `code`, each matter-type `code` within its practice area, each firm `name`, each counsel `email`, each matter `matter_number`, the pairing of `firm_id` and `invoice_number` on invoices, and the pairing of `fiscal_period_id` with `snapshot_label` on dashboards.

### 3.2. Opening the Fiscal Year

Fiscal periods are created by a `LegalOpsManager` with a human `label` such as FY2026, a `start_date`, and an `end_date`, both ISO calendar dates. The end date must fall strictly after the start date, and the new period's inclusive date range may not overlap any existing period's range — though periods may touch: one period ending the day before another begins is permitted. A violation is rejected with `ERR_PERIOD_OVERLAP` (HTTP 422). A fresh period starts `OPEN`, with `reopen_count` at zero and both aggregate totals — `total_actual_spend_cents` and `total_accrual_cents` — at zero. When the newly created period is the only one in `OPEN` status, the department's `active_fiscal_period_id` pointer is set to it; the pointer returns to null whenever no period — or more than one period — is open. Periods can be listed filtered by `status`. The period lifecycle itself — soft-close, hard-close, and reopening — is covered in §3.7, after the operational workflows it gates.

### 3.3. Matter Intake, Staffing, and Activation

A `LegalOpsAnalyst` opens a matter by supplying its `matter_number` — a unique business key in the format LGL-YYYY-NNNNN — along with a `title`, the `practice_area_id` and `matter_type_id` classifying it, the `fiscal_period_id` of the period in which it opens, and the `lead_counsel_id` of the responsible in-house lawyer. `primary_firm_id` is optional and stays null for fully insourced matters; `budget_cents` is likewise optional and, when omitted, is copied from the matter type's `default_budget_cents`. New matters are born in `INTAKE` with `actual_spend_cents` and `accrual_outstanding_cents` at zero and `cycle_days` null.

Creation is guarded, in order, by the taxonomy rule — the referenced matter type must belong to the referenced practice area, else `ERR_TAXONOMY_MISMATCH` (HTTP 422) — then by the calendar gate (`ERR_PERIOD_CLOSED` when the period is neither `OPEN` nor `REOPENED`), then by entity activity (`ERR_ENTITY_INACTIVE`, HTTP 422, when the practice area is not `ACTIVE`), then by uniqueness of `matter_number`, and finally by the amount rule: a negative `budget_cents` is `ERR_INVALID_AMOUNT` (HTTP 422). While a matter has not reached its terminal `ARCHIVED` state, an analyst may update its `title`, `budget_cents`, or `primary_firm_id`; the same taxonomy-consistency and amount rules apply to updates, and each successful update bumps the matter's `version`; an update that supplies none of the three mutable fields changes nothing and leaves the `version` untouched. An update attempted against an archived matter is rejected with `ERR_INVALID_STATE`. Matters can be listed filtered by `status`, `practice_area_id`, `matter_type_id`, `fiscal_period_id`, `primary_firm_id`, or `lead_counsel_id`.

Staffing happens through assignments. An analyst allocates hours to a matter by creating an assignment that names the `counsel_id` and the `allocated_hours` — zero or more, with a negative value rejected as `ERR_INVALID_REQUEST` (HTTP 400) — for the current fiscal period; the assignment starts `ACTIVE`. Capacity is enforced at write time: if the counsel's capacity-consuming load — hours committed through `ACTIVE` assignments sitting on matters that are `ACTIVE` or `ON_HOLD`, the same set the utilization read in §3.8 counts — plus the newly requested hours would exceed that counsel's `annual_capacity_hours`, creation is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422); landing exactly at capacity is allowed. An analyst may also release an active assignment manually while its matter is `ACTIVE` or `ON_HOLD`, moving it to `RELEASED` and bumping its `version`; releasing against a matter in any other state is rejected with `ERR_INVALID_STATE`. Assignments can be browsed per matter, or across the department filtered by `counsel_id`, `matter_id`, or `status`.

Activation moves a matter from `INTAKE` to `ACTIVE` and is the strictest gate in the intake flow. Evaluated after the generic state check, it requires the matter's fiscal period to be `OPEN` — activation in a merely `REOPENED` period is refused as `ERR_INVALID_STATE`, while a period that has closed entirely yields `ERR_PERIOD_CLOSED` — the practice area still `ACTIVE`, and the primary firm (when one is set) still `ACTIVE` — a lapsed practice area or firm blocks activation as `ERR_INVALID_STATE` — and at least one `ACTIVE` assignment row on the matter. A matter with no active staffing is rejected with `ERR_NO_ACTIVE_ASSIGNMENT` (HTTP 422). Once active, a matter can be placed `ON_HOLD` and later resumed back to `ACTIVE`; resumption is permitted while the period is `OPEN` or `REOPENED`, with a closed period producing `ERR_PERIOD_CLOSED`. Each of these transitions bumps the matter's `version`.

### 3.4. Budget Envelopes and Posture Tracking

A `LegalOpsManager` carves the period's money into budget envelopes, each naming a `fiscal_period_id`, a `practice_area_id`, optionally a `matter_type_id` — null means the envelope covers the whole practice area — and an `allocated_cents` amount that may be zero but never negative (`ERR_INVALID_AMOUNT`). No taxonomy-consistency check ties the matter type to the practice area: the pair is accepted as supplied. A new budget starts with `consumed_cents` at zero and `posture` `OK`.

From then on, posture follows the derivation in §2.7: every posted spend line whose matter resolves into the budget's grain raises `consumed_cents`, and every such insert re-derives the posture — as does any edit to the envelope and any change to the department's thresholds. Budgets can be listed filtered by `fiscal_period_id`, `practice_area_id`, `matter_type_id`, or `posture`.

Reallocating money is a manager action that updates `allocated_cents`. Because cascaded recomputes can advance a budget's `version` behind a client's back, the update may carry `expected_budget_version`; when supplied it must equal the budget's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The amount check — allocation at least zero — is evaluated before the version comparison, so a patch that fails both reports `ERR_INVALID_AMOUNT`. A successful update re-derives posture immediately and increments the budget's `version`.

### 3.5. Accruals and the Invoice Pipeline

Accruals record fees the department expects to owe. An analyst creates one at the grain of a matter, a period, and a firm — `matter_id`, `fiscal_period_id`, and `firm_id` — with an estimated `amount_cents` that may be zero but never negative (a negative amount is `ERR_INVALID_AMOUNT`, HTTP 422). The calendar gate is evaluated before the amount check, so an accrual aimed at a period that is neither `OPEN` nor `REOPENED` yields `ERR_PERIOD_CLOSED` rather than an amount error. A new accrual is `OUTSTANDING`, and its amount immediately raises both the matter's `accrual_outstanding_cents` and the period's `total_accrual_cents`. While its period remains `OPEN` or `REOPENED`, an analyst may release an outstanding accrual; release moves it from `OUTSTANDING` to `RELEASED`, subtracts its amount from both aggregates, and bumps the accrual's `version`. Accruals can be listed filtered by `matter_id`, `fiscal_period_id`, `firm_id`, or `status`. The two remaining exits from `OUTSTANDING` — matching and expiry — are system-driven and covered below and in §3.7.

Invoices arrive from outside counsel through an analyst, who submits the `matter_id`, `firm_id`, and `fiscal_period_id` the invoice posts to, the vendor's `invoice_number`, and an `amount_cents` that must be strictly greater than zero — a zero invoice is rejected with `ERR_INVALID_AMOUNT`. Submission is guarded, in order, by the calendar gate (`ERR_PERIOD_CLOSED`), by firm activity (`ERR_ENTITY_INACTIVE` when the firm is not `ACTIVE`), by the per-firm uniqueness of `invoice_number` (`ERR_DUPLICATE` when the same firm already carries that number), and finally by the amount rule (a non-positive `amount_cents` is `ERR_INVALID_AMOUNT`). An invoice is born `SUBMITTED` on its `payment_status` dimension and `UNMATCHED` on its `accrual_match_status` dimension — two parallel status dimensions that evolve independently — with `matched_accrual_id` null until a match is found. Invoices can be listed filtered by `matter_id`, `firm_id`, `fiscal_period_id`, `payment_status`, `accrual_match_status`, or `matched_accrual_id`.

Approval is an analyst action with a segregation-of-duties twist. The invoice must still be `SUBMITTED`, else `ERR_INVALID_STATE`. Then — before the calendar gate runs — the duty check fires: when `amount_cents` is at least 100000 (one thousand dollars), the approver's `X-User-ID` must differ from the identifier recorded at submission, and a self-approval is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Invoices below that threshold may be self-approved. Finally, the invoice's period must be `OPEN` or `REOPENED`, else `ERR_PERIOD_CLOSED`.

On approval the system runs the accrual match. It searches for accruals sharing the invoice's `matter_id`, `fiscal_period_id`, and `firm_id` that are still `OUTSTANDING`; when several qualify, the earliest-created one wins — ties on the same clock tick break in creation (insertion) order — so the selector returns at most one accrual. When a candidate is found, its `id` is recorded in `matched_accrual_id` and the match is classified by exact integer-cent comparison of the accrual's amount against the invoice's: equal amounts classify `FULLY_MATCHED`; an accrual larger than the invoice classifies `PARTIALLY_MATCHED`; an accrual smaller than the invoice classifies `OVER_BILLED`. When no outstanding accrual qualifies, `accrual_match_status` simply stays `UNMATCHED`. Approval bumps the invoice's `version`. Note the accrual itself does not change state at approval time — that happens at payment.

Rejection, also an analyst action, moves a `SUBMITTED` invoice straight to its terminal `REJECTED` state, bumping its `version`.

Payment is the manager's counterpart to approval and the system's biggest cascade. The invoice must be `APPROVED` and its period `OPEN` or `REOPENED`. Before anything posts, the fiscal cap runs: if paying would push any matching budget's `consumed_cents` past one hundred and ten percent of its `allocated_cents` — the fixed ten-percent overrun allowance of §2.7 — payment is refused with `ERR_BUDGET_OVERRUN_EXCEEDED` (HTTP 422). The comparison is exact integer arithmetic, and a payment landing exactly at the allowance boundary is permitted. On success the system writes a spend line whose `amount_cents` equals the invoice amount, whose `posting_date` is the posting period's `start_date`, and whose `source_status` is `POSTED`. When `matched_accrual_id` is set, the matched accrual transitions from `OUTSTANDING` to `MATCHED`. The matter's `actual_spend_cents` grows by the invoice amount and its `accrual_outstanding_cents` is recomputed; the period's `total_actual_spend_cents` grows likewise and its `total_accrual_cents` is recomputed; every matching budget recomputes `consumed_cents` and re-derives its `posture`; and the invoice's own `version` increments — with each recomputed parent also bumping its own `version` and refreshing its `updated_at`, per §2.8.

Spend lines are written in invoice-pay order. Lines whose `created_at` timestamps coincide are ordered by `posting_date` ascending and then by the generating invoice's `created_at` ascending; a spend line's own `id` is never used as a sort key.

### 3.6. Closing Matters and Measuring Cycle Time

Closing is an analyst action available from `ACTIVE` and, after a reopen, from `REOPENED`. Two housekeeping conditions guard it: no accrual on the matter may remain `OUTSTANDING`, and no invoice on the matter may linger in `SUBMITTED`; either violation is rejected as `ERR_INVALID_STATE`. The request may also carry `expected_matter_version`; when supplied it must match the matter's current `version`. The state checks run first, so a second close attempted against an already-closed matter reports `ERR_INVALID_STATE`, while a close against a matter whose `version` has drifted — for instance, because an invoice payment cascade bumped it — reports `ERR_STALE_VERSION`.

A successful close stamps `cycle_days` as the number of days between the matter's original `INTAKE` → `ACTIVE` transition timestamp and this close transition's timestamp, releases every still-`ACTIVE` assignment on the matter — each moving to `RELEASED` — and bumps the matter's `version`. For a matter closing out of `REOPENED`, `cycle_days` is recomputed the same way: from the original activation timestamp to this close timestamp, never from the reopen.

A `LegalOpsManager` may reopen a `CLOSED` matter while its period is `OPEN` or `REOPENED`; reopening moves the matter to `REOPENED`, resets `cycle_days` to null — erasing the matter from cycle-time statistics until it closes again — and bumps the `version`. A reopen attempted against a period that has moved past those states is rejected with `ERR_INVALID_STATE`. Once the matter's period has been hard-closed, the manager may archive the matter, moving it from `CLOSED` to its terminal `ARCHIVED` state; archiving against a period that is not yet `HARD_CLOSED` is rejected with `ERR_PERIOD_NOT_HARD_CLOSED` (HTTP 409). Both actions bump the matter's `version`.

### 3.7. Period Close, the Accrual Expiry Sweep, and Reopening

Soft close is an analyst action available from `OPEN` and from `REOPENED`. Out of `OPEN`, its precondition is that every matter in the period has moved past intake — a lingering `INTAKE` matter blocks the transition as `ERR_INVALID_STATE`. Out of `REOPENED`, the state check alone gates the transition. Either way, soft close triggers the accrual expiry sweep: every accrual still `OUTSTANDING` in the period transitions to `EXPIRED`, each affected matter's `accrual_outstanding_cents` is recomputed — to zero, since only outstanding accruals contribute — and the period's `total_accrual_cents` recomputes to zero alongside. The period's `version` increments.

Hard close is a manager action from `SOFT_CLOSED`, blocked when any invoice in the period is still `SUBMITTED` or any dashboard for the period is still `DRAFT`; the rejection is `ERR_PERIOD_NOT_CLOSABLE` (HTTP 422). Put positively: every invoice in the period must have reached `APPROVED`, `PAID`, or `REJECTED`, and every dashboard must have reached `PUBLISHED` or `SUPERSEDED` — the workflow reason dashboards exist, covered in the next section. A reopened period must pass through soft close again, with its sweep, before it can hard-close a second time. Hard close increments the period's `version`.

A hard-closed period is not necessarily final. A manager may reopen it — `HARD_CLOSED` → `REOPENED` — at most twice: the period's `reopen_count`, starting at zero, increments on each reopen, and a third attempt is rejected with `ERR_REOPEN_LIMIT` (HTTP 422). While `REOPENED`, the period once again accepts operational writes per §2.5, and matters within it may resume, close, or be reopened themselves; activation of new matters remains the exception noted in §3.3. Only a return to `HARD_CLOSED` re-enables matter archival. Each reopen increments the period's `version`.

### 3.8. Measuring the Department: Utilization, Cost Models, Reports, and Dashboards

Four read surfaces turn the operational record into management information.

**Counsel utilization.** A computed read per counsel reports `counsel_id`, `total_allocated_hours`, `annual_capacity_hours`, `utilization_pct`, and an `over_capacity` flag. The input set is precise: active assignments whose parent matter is `ACTIVE` or `ON_HOLD` consume capacity, while assignments sitting on `INTAKE`, `CLOSED`, `REOPENED`, or `ARCHIVED` matters do not. Utilization divides the allocated total by `annual_capacity_hours`, multiplies by one hundred, rounds half-up to two decimal places, and divides by one hundred, per §2.9. `over_capacity` is true only when the allocated total strictly exceeds capacity; the write-time check in §3.3 normally prevents this, so the flag exists for capacity reductions and edge reconciliations. The figure refreshes whenever an assignment is created or released, and is also available on demand.

**The insource-versus-outsource cost model.** Available on demand per matter, and recomputed when a matter closes, the model reads every assignment the matter has ever had — active and released alike. `insource_cost_cents` sums, across those assignments, each assignment's `allocated_hours` multiplied by its counsel's `loaded_hourly_cost_cents`. `modeled_outsource_cost_cents` multiplies the matter's total allocated hours — the same sum across all assignments — by the primary firm's `blended_hourly_rate_cents`; when the matter has no primary firm, this figure, `savings_cents`, and the `decision` are all null. `savings_cents` is the modeled outsource figure minus the insource figure: a positive value decides `INSOURCE_CHEAPER`, a negative value decides `OUTSOURCE_CHEAPER`, and exactly zero decides `BREAK_EVEN`. The `outsource_cost_cents` leg comes in two variants. While the matter is `INTAKE`, `ACTIVE`, or `ON_HOLD`, the read is provisional and uses `actual_spend_cents` plus `accrual_outstanding_cents` — a forward-looking view that counts fees still accruing. Once the matter is `CLOSED`, `REOPENED`, or `ARCHIVED`, the read is final and uses `actual_spend_cents` alone, ignoring accruals entirely. Alongside the three cost figures, `savings_cents`, and the `decision`, the response carries the `matter_id`. All figures are integer cents with no rounding.

**Spend and cycle-time reports.** Three paginated report reads each take a `fiscal_period_id` query parameter — a missing parameter yields `ERR_INVALID_REQUEST` (HTTP 400), an unknown one `ERR_NOT_FOUND` (HTTP 404) — and answer with `response_type` "object" whose `data` is `{"rows": [...]}`, the standard pagination fields carried in `meta`. Only `POSTED` spend lines in the period feed the spend reports, and only the period's matters currently `CLOSED` with a non-null `cycle_days` feed the benchmark. Spend per practice area resolves each line's practice area through its matter and returns rows of `practice_area_id`, `code`, `display_name`, and `total_spend_cents`, sorted by `total_spend_cents` descending with ties broken by `code` ascending. Spend per firm returns rows of `firm_id`, `name`, `tier`, and `total_spend_cents`, sorted by `total_spend_cents` descending with ties broken by `name` ascending. The cycle-time benchmark groups by matter type and returns rows of `matter_type_id`, `code`, `display_name`, `closed_count`, `mean_cycle_days`, `p50_cycle_days`, and `p90_cycle_days`, sorted by `code` ascending; the mean follows the rounding order of §2.9, and the percentiles use the nearest-rank method — over n ascending-sorted `cycle_days` values, the percentile value sits at rank max(1, ceil(p × n / 100)).

**The executive dashboard.** An analyst drafts a dashboard for a period by supplying its `fiscal_period_id` and a `snapshot_label`; the pairing must be unique (`ERR_DUPLICATE`), though a period may accumulate several snapshots over time. At creation the dashboard computes its full derived panel while still `DRAFT`. `total_matters_opened` counts the period's matters in `ACTIVE`, `ON_HOLD`, `CLOSED`, or `REOPENED`; `total_matters_closed` counts those currently `CLOSED`. `mean_cycle_days` averages `cycle_days` across the period's closed matters that have one — summing whole days first, dividing once, rounding half-up to two decimals — and is null when no closed matter qualifies; reopened matters are excluded because reopening reset their `cycle_days` to null. `total_actual_spend_cents` and `total_accrual_outstanding_cents` mirror the period's live totals. `budget_accuracy_pct` compares the period's total allocation across all of its budgets, regardless of posture, against its actual spend: when the total allocation is zero the figure is null; otherwise the absolute difference between allocation and actual spend is taken first, divided by the total allocation, the resulting fraction is subtracted from one, multiplied by one hundred, rounded half-up to two decimal places, and finally divided by one hundred. `deflection_rate_pct` divides the period's deflected matters — those with no primary firm whose status is `ACTIVE` or `CLOSED` — by `total_matters_opened`, applying the same multiply-round-divide order, and is null when no matters qualify for the denominator; `INTAKE` and `ARCHIVED` matters never count in either figure. A `DRAFT` dashboard is provisional: each read recomputes against live period totals, so values may drift between reads. Dashboards can be listed filtered by `fiscal_period_id` or `status`.

Publishing is a manager action requiring the dashboard to still be in `DRAFT` and the period to be `SOFT_CLOSED` or `HARD_CLOSED`; a period in any other state makes the transition undefined and is rejected with `ERR_INVALID_STATE`. The request may carry `expected_dashboard_version`, checked after the state gate; a supplied mismatch — typically because a peer's publish superseded this row and advanced its `version` — is rejected with `ERR_STALE_VERSION`. Publishing freezes the computed panel permanently: subsequent invoices, releases, and closes do not move a `PUBLISHED` (or later `SUPERSEDED`) dashboard's numbers. At most one dashboard per period is published at a time — every other `PUBLISHED` dashboard for the same period transitions to `SUPERSEDED` the moment a new one publishes, each such row incrementing its own `version` — and the freshly published row's `version` increments as well.

## 4. Endpoint Definitions

Endpoints that create a new, stand-alone resource return `201 Created`. All other successful operations — reads, updates, lifecycle transitions, and computed reads — return `200 OK`. The table below summarizes the HTTP contract only; request fields, side effects, and preconditions are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/legal-ops/departments` | Create the legal department with its governance thresholds | LegalOpsManager |
| GET | `/legal-ops/departments` | List departments, paginated, filterable by active period | All roles |
| GET | `/legal-ops/departments/{id}` | Fetch one department | All roles |
| PATCH | `/legal-ops/departments/{id}` | Update department thresholds; re-derives all budget postures | LegalOpsManager |
| POST | `/legal-ops/fiscal-periods` | Create a fiscal period | LegalOpsManager |
| GET | `/legal-ops/fiscal-periods` | List fiscal periods, paginated, filterable by status | All roles |
| GET | `/legal-ops/fiscal-periods/{id}` | Fetch one fiscal period | All roles |
| POST | `/legal-ops/fiscal-periods/{id}/soft-close` | Soft-close a period; sweeps outstanding accruals to expiry | LegalOpsAnalyst |
| POST | `/legal-ops/fiscal-periods/{id}/hard-close` | Hard-close a soft-closed period | LegalOpsManager |
| POST | `/legal-ops/fiscal-periods/{id}/reopen` | Reopen a hard-closed period (at most twice) | LegalOpsManager |
| POST | `/legal-ops/practice-areas` | Create a practice area | LegalOpsManager |
| GET | `/legal-ops/practice-areas` | List practice areas, paginated, filterable by status | All roles |
| GET | `/legal-ops/practice-areas/{id}` | Fetch one practice area | All roles |
| POST | `/legal-ops/practice-areas/{id}/archive` | Archive a practice area so it rejects new matters | LegalOpsManager |
| POST | `/legal-ops/practice-areas/{id}/matter-types` | Create a matter type under a practice area | LegalOpsManager |
| GET | `/legal-ops/practice-areas/{id}/matter-types` | List matter types under a practice area | All roles |
| GET | `/legal-ops/matter-types/{id}` | Fetch one matter type | All roles |
| POST | `/legal-ops/firms` | Register an outside counsel firm | LegalOpsManager |
| GET | `/legal-ops/firms` | List firms, paginated, filterable by tier and status | All roles |
| GET | `/legal-ops/firms/{id}` | Fetch one firm | All roles |
| POST | `/legal-ops/firms/{id}/suspend` | Suspend a firm so it rejects new invoices | LegalOpsManager |
| POST | `/legal-ops/in-house-counsel` | Register an in-house counsel | LegalOpsManager |
| GET | `/legal-ops/in-house-counsel` | List counsel, paginated, filterable by status | All roles |
| GET | `/legal-ops/in-house-counsel/{id}` | Fetch one counsel | All roles |
| GET | `/legal-ops/in-house-counsel/{id}/utilization` | Computed read: workload utilization for one counsel | All roles |
| POST | `/legal-ops/matters` | Create a matter in intake status | LegalOpsAnalyst |
| GET | `/legal-ops/matters` | List matters, paginated, with six filters | All roles |
| GET | `/legal-ops/matters/{id}` | Fetch one matter | All roles |
| PATCH | `/legal-ops/matters/{id}` | Update a matter's mutable fields while not terminal | LegalOpsAnalyst |
| POST | `/legal-ops/matters/{id}/activate` | Activate an intake matter | LegalOpsAnalyst |
| POST | `/legal-ops/matters/{id}/hold` | Place an active matter on hold | LegalOpsAnalyst |
| POST | `/legal-ops/matters/{id}/resume` | Resume a held matter | LegalOpsAnalyst |
| POST | `/legal-ops/matters/{id}/close` | Close an active or reopened matter (optimistic concurrency) | LegalOpsAnalyst |
| POST | `/legal-ops/matters/{id}/reopen` | Reopen a closed matter | LegalOpsManager |
| POST | `/legal-ops/matters/{id}/archive` | Archive a closed matter once its period is hard-closed | LegalOpsManager |
| GET | `/legal-ops/matters/{id}/cost-model` | Computed read: insource-versus-outsource cost model | All roles |
| POST | `/legal-ops/matters/{id}/assignments` | Allocate counsel hours to a matter | LegalOpsAnalyst |
| GET | `/legal-ops/matters/{id}/assignments` | List assignments for a matter | All roles |
| GET | `/legal-ops/matter-assignments` | List assignments, paginated, filterable by counsel, matter, or status | All roles |
| GET | `/legal-ops/matter-assignments/{id}` | Fetch one assignment | All roles |
| POST | `/legal-ops/matter-assignments/{id}/release` | Manually release an active assignment | LegalOpsAnalyst |
| POST | `/legal-ops/budgets` | Create a budget envelope at period, practice-area, and optional matter-type grain | LegalOpsManager |
| GET | `/legal-ops/budgets` | List budgets, paginated, filterable by period, practice area, matter type, or posture | All roles |
| GET | `/legal-ops/budgets/{id}` | Fetch one budget | All roles |
| PATCH | `/legal-ops/budgets/{id}` | Update a budget's allocation (optimistic concurrency) | LegalOpsManager |
| POST | `/legal-ops/accruals` | Record an accrual at the matter, period, and firm grain | LegalOpsAnalyst |
| GET | `/legal-ops/accruals` | List accruals, paginated, filterable by matter, period, firm, or status | All roles |
| GET | `/legal-ops/accruals/{id}` | Fetch one accrual | All roles |
| POST | `/legal-ops/accruals/{id}/release` | Manually release an outstanding accrual | LegalOpsAnalyst |
| POST | `/legal-ops/invoices` | Submit an invoice | LegalOpsAnalyst |
| GET | `/legal-ops/invoices` | List invoices, paginated, with six filters | All roles |
| GET | `/legal-ops/invoices/{id}` | Fetch one invoice | All roles |
| POST | `/legal-ops/invoices/{id}/approve` | Approve a submitted invoice; runs the accrual match | LegalOpsAnalyst |
| POST | `/legal-ops/invoices/{id}/pay` | Pay an approved invoice; posts the spend line and cascades aggregates | LegalOpsManager |
| POST | `/legal-ops/invoices/{id}/reject` | Reject a submitted invoice | LegalOpsAnalyst |
| GET | `/legal-ops/spend-lines` | List spend-ledger rows, paginated, with six filters | All roles |
| GET | `/legal-ops/spend-lines/{id}` | Fetch one spend-ledger row | All roles |
| POST | `/legal-ops/dashboards` | Draft a dashboard snapshot for a fiscal period | LegalOpsAnalyst |
| GET | `/legal-ops/dashboards` | List dashboards, paginated, filterable by period or status | All roles |
| GET | `/legal-ops/dashboards/{id}` | Fetch one dashboard | All roles |
| POST | `/legal-ops/dashboards/{id}/publish` | Publish a draft dashboard; supersedes prior published rows (optimistic concurrency) | LegalOpsManager |
| GET | `/legal-ops/reports/spend-by-practice-area` | Aggregated spend per practice area for a fiscal period | All roles |
| GET | `/legal-ops/reports/spend-by-firm` | Aggregated spend per firm for a fiscal period | All roles |
| GET | `/legal-ops/reports/cycle-time-benchmark` | Cycle-time statistics (mean, p50, p90) per matter type for a fiscal period | All roles |
| POST | `/legal-ops/_clock/set_current_utc` | Set the server's logical clock | LegalOpsManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PERIOD_CLOSED` | 409 Conflict |
| `ERR_PERIOD_NOT_HARD_CLOSED` | 409 Conflict |
| `ERR_PERIOD_OVERLAP` | 422 Unprocessable Entity |
| `ERR_TAXONOMY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PARENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ENTITY_INACTIVE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_BUDGET_OVERRUN_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_ASSIGNMENT` | 422 Unprocessable Entity |
| `ERR_PERIOD_NOT_CLOSABLE` | 422 Unprocessable Entity |
| `ERR_REOPEN_LIMIT` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
