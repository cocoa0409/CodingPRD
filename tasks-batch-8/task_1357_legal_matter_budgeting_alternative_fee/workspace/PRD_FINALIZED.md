# Legal Matter Budgeting & Alternative Fee Arrangements API — Product Requirements Document

## 1. Introduction

Law firms increasingly price litigation work under alternative fee arrangements — flat fees, capped fees, success fees, and collared arrangements — while corporate clients simultaneously demand disciplined accrual reporting and continuous visibility into budget consumption. The pricing office that administers these arrangements operates under constant tension: partners want freedom to staff matters and concede fees, while finance needs a defensible, auditable record of who approved what, within which authority, and against which budget baseline.

This document specifies the Legal Matter Budgeting & Alternative Fee Arrangements API, mounted under `/firms`, which serves as the system of record for that pricing office. The API governs the full commercial lifecycle of a legal matter: establishment of phase- and task-code-level budgets keyed by litigation stage, drafting and activation of fee arrangements, capture and approval of time entries, actual-versus-budget variance alerting with revised forecasts, write-down approval under segregation of duties, scope-change budget amendments, client accrual reporting, matter close-out and reopening, and the year-end true-up that settles collared arrangements.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract-level formats, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Six roles are recognized, spelled exactly as follows:

- `FirmAdmin` — firm administrator; manages the firm record, clients, the timekeeper roster, fiscal-period advancement, and book closing. Identity: when `X-User-Role` is `FirmAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `PricingAnalyst` — pricing-office analyst; drafts fee arrangements, phase budgets, and budget amendments. Identity: when `X-User-Role` is `PricingAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `BillingPartner` — partner with billing responsibility; approves time, activates arrangements, decides write-downs within authority. Identity: entity-backed — when `X-User-Role` is `BillingPartner`, `X-User-ID` is the `id` of the acting `Timekeeper`; ownership checks on any resource that references a `Timekeeper` compare the resource's foreign-key field (for example `responsible_partner_id` on a matter or `timekeeper_id` on a time entry) to `X-User-ID`.
- `ManagingPartner` — senior partner with elevated authority; decides escalated write-downs and large amendments, waives true-ups, reopens matters. Identity: when `X-User-Role` is `ManagingPartner`, `X-User-ID` is the `id` of the acting `Timekeeper`, with the same foreign-key comparison rule as `BillingPartner`.
- `Timekeeper` — attorney or paralegal recording time. Identity: when `X-User-Role` is `Timekeeper`, `X-User-ID` is the `id` of the acting `Timekeeper`, with the same foreign-key comparison rule.
- `ClientContact` — external client contact; acknowledges or disputes accrual reports, with read access scoped to matters belonging to their client. Identity: when `X-User-Role` is `ClientContact`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Where the system records who requested or decided a governed action, the acting user's `X-User-ID` is captured verbatim — for instance into `requested_by_user_id` or `decided_by_user_id` — and those captured values drive the segregation-of-duties checks described in §2.8.

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

List endpoints accept `limit` and `offset` query parameters. `limit` specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies the number of items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. Because the logical clock stands still between explicit settings, many resources share an identical `created_at`; ties are broken by an internal monotonic sequence the server assigns at creation and refreshes on every modification of the resource, so the ordering is always total and deterministic — among equal `created_at` values, a more recently created-or-modified resource sorts after a less recently one. This internal sequence is server bookkeeping only and never appears in any response payload. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

List endpoints additionally accept resource-appropriate filter parameters. Timekeepers filter by `firm_id`, `status`, and `role_title`; clients by `firm_id` and `status`; matters by `firm_id`, `client_id`, `responsible_partner_id`, `fee_arrangement_id`, `status`, and `litigation_stage`; fee arrangements by `firm_id`, `matter_id`, `supersedes_arrangement_id`, `status`, and `arrangement_type`; phase budgets by `firm_id`, `matter_id`, `status`, `litigation_stage`, and `task_code`; time entries by `firm_id`, `matter_id`, `timekeeper_id`, `status`, `task_code`, and `period_index`; write-down requests by `firm_id`, `matter_id`, and `status`; budget amendments by `firm_id`, `matter_id`, `phase_budget_id`, `supersedes_amendment_id`, and `status`; accrual reports by `firm_id`, `matter_id`, `status`, and `period_index`; collar true-ups by `firm_id`, `matter_id`, `fee_arrangement_id`, and `status`. Sub-resource listings scoped to a parent accept the corresponding subset of these filters — for example, a client's matter listing filters by `status` and `litigation_stage`, and a phase budget's amendment listing paginates with `limit` and `offset` only.

### 2.4. Common Resource Properties

Every resource in the system — Firm, Client, Matter, FeeArrangement, PhaseBudget, TimeEntry, Timekeeper, WriteDownRequest, BudgetAmendment, AccrualReport, and CollarTrueUp — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource and underpins optimistic concurrency control.

Recomputation of a derived aggregate on a matter — for example `budget_total_cents` or `variance_cents` — is itself a mutation of the matter and therefore refreshes `updated_at` and increments `version`.

### 2.5. Money, Time, and Rounding Conventions

All monetary amounts are integer cents; no floating-point money appears anywhere in the API. Worked time is recorded in milli-hours: `hours_worked_milli` is the number of hours multiplied by one thousand, so a value of 1500 records one and a half hours. Percentages that must be exact are expressed in basis points, where 10000 basis points equal one hundred percent.

Rounding rules are pinned per calculation and never left to implementation discretion. Time-entry billing rounds down to a whole cent at line level. Variance percentages and realization rates round half up to the nearest basis point. Collar true-up amounts and fee-quote figures round half up to the nearest cent. Write-down allocation floors each line and distributes leftover cents through a deterministic waterfall. The precise rules appear with their owning workflows in §3.

### 2.6. The Fiscal Calendar: Periods, Book-Closing, and the Logical Clock

Each firm declares `fiscal_year_start_month`, an integer from 1 to 12 naming the month its fiscal year begins, and its fiscal year is divided into monthly fiscal periods. Fiscal periods coincide with calendar months, and the period indexes are anchored to the logical clock's startup reading: period 0 is the calendar month containing 2026-08-01 — that is, August 2026 — and each calendar month steps the index by one (September 2026 is period 1, July 2026 is period −1, and so on); this anchoring is fixed and does not move when the logical clock is later set. `fiscal_year_start_month` does not shift period boundaries; it only determines the fiscal-year label of each period: a period whose calendar month is month m of calendar year y belongs to the fiscal year labeled y when m is greater than or equal to `fiscal_year_start_month`, and to the fiscal year labeled y − 1 otherwise. The fiscal year labeled Y runs from (Y, `fiscal_year_start_month`, 1) up to but not including (Y + 1, `fiscal_year_start_month`, 1), and it has ended once the logical clock reaches (Y + 1, `fiscal_year_start_month`, 1). The firm tracks a monotonic `current_period_index`, initialized to 0 when the firm is created, and a `closed_through_period_index`, initialized to -1 to indicate that no period has been closed. These two counters drive period attribution, accrual cycles, the closed-period guards, and the collar true-up calendar.

Advancing the fiscal period — a `FirmAdmin` capability — increments `current_period_index` by one. Each advancement also regenerates a fresh `DRAFT` accrual report for the new period on every matter whose client mandates accrual reporting (and refreshes the amounts on reports still in `DRAFT`, per §3.8). Period advancement performs no collar processing: a `COLLAR` arrangement becomes eligible for the year-end true-up of §3.9 once the fiscal year identified by its `fiscal_year_index` has ended under the rule above. Closing the books — a capability shared by `FirmAdmin` and `ManagingPartner` — sets `closed_through_period_index` to one less than `current_period_index`; if it already equals that value, the request is rejected with `ERR_INVALID_STATE_TRANSITION`.

A time entry's `period_index` is computed, never supplied: it is the index of the fiscal period — the calendar month — containing the entry's `entry_date` under the anchoring above; the day of month plays no role. Actions that would write into a period at or before `closed_through_period_index` are rejected with `ERR_PERIOD_CLOSED`, as detailed per workflow in §3. Matters with any activity in closed periods cannot be retroactively amended into those periods.

For testing and simulation, the platform exposes a `FirmAdmin`-only logical-clock capability accepting a `to_iso8601` instant. At startup the logical clock reads 2026-08-01T00:00:00Z; after it is set, all derived date and period computations across the API use this clock. The capability returns the effective instant as `current_utc`.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it has observed the current state of the parent matter before writing, and both take the same proof field:

- Activating a fee arrangement requires the request to carry `expected_matter_version`, the matter `version` the client last observed.
- Deciding (approving or rejecting) a budget amendment likewise requires `expected_matter_version`.

If the supplied value does not match the matter's current `version` — because another writer has advanced the matter's version since the client last read it, for instance by activating a competing arrangement or by having an amendment approved — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no state change occurs. Endpoints other than these two do not accept a version field.

### 2.8. Segregation of Duties and Approval Authority

The API separates drafting authority from decision authority: `PricingAnalyst` drafts fee arrangements, phase budgets, and budget amendments, while partner roles decide them. On governed approval workflows the user who requested an action may not also decide it. Whenever a decision is recorded, the captured `decided_by_user_id` must differ from `requested_by_user_id`; a matching pair is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). This rule applies both to write-down decisions and to budget-amendment decisions.

Decision authority is further bounded by amount, using two firm-wide authority thresholds. A `BillingPartner` may decide a write-down only when `requested_amount_cents` is at most `PARTNER_WRITE_DOWN_AUTHORITY_CENTS`; a write-down above that threshold is automatically escalated and must be decided by a `ManagingPartner`. For budget amendments, a `BillingPartner` may approve only when the amendment's magnitude is at most `PARTNER_AMENDMENT_AUTHORITY_CENTS`; a larger amendment decided by a `BillingPartner` is rejected with `ERR_AMENDMENT_AUTHORITY_EXCEEDED` (HTTP 403) and requires a `ManagingPartner`. Write-down approvals are all-or-nothing in this version: on approval, the approved amount always equals the requested amount, and partial approval is not supported.

### 2.9. Guard Evaluation Order

When several guards apply to one request, they are evaluated in a fixed priority order so the surfaced error is deterministic:

1. Presence and shape of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role permission for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`).
3. Existence of path identifiers within the firm scope and of references supplied in the body (`ERR_NOT_FOUND`).
4. Generic state-transition legality (`ERR_INVALID_STATE_TRANSITION`).
5. The matter-open gate (`ERR_MATTER_NOT_OPEN`).
6. The client-active gate (`ERR_CLIENT_NOT_ACTIVE`).
7. The closed-period guard (`ERR_PERIOD_CLOSED`).
8. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).
9. Arrangement field completeness (`ERR_ARRANGEMENT_FIELDS_INCOMPLETE`).
10. Arrangement uniqueness per matter (`ERR_ARRANGEMENT_ALREADY_ACTIVE`).
11. Task-code budget coverage (`ERR_TASK_CODE_NOT_BUDGETED`).
12. Write-down entry validity (`ERR_WRITE_DOWN_ENTRIES_INVALID`, with the state-specific refinement `ERR_WRITE_DOWN_ENTRY_STATE` applied at submission).
13. Write-down amount validity (`ERR_WRITE_DOWN_AMOUNT_INVALID`).
14. Amendment non-negativity (`ERR_AMENDMENT_NEGATIVE_BUDGET`).
15. Amendment authority (`ERR_AMENDMENT_AUTHORITY_EXCEEDED`).
16. Amendment supersede validity (`ERR_AMENDMENT_SUPERSEDE_INVALID`).
17. The matter-close battery (`ERR_MATTER_HAS_OPEN_WIP`, `ERR_MATTER_HAS_PENDING_WRITE_DOWNS`, `ERR_MATTER_HAS_PENDING_AMENDMENTS`, `ERR_MATTER_COLLAR_UNSETTLED`, `ERR_MATTER_ACCRUAL_OUTSTANDING`).
18. The client-close guard (`ERR_CLIENT_HAS_OPEN_MATTERS`).
19. The reopen-window guard (`ERR_REOPEN_WINDOW_CLOSED`).
20. The phase-void guards (`ERR_PHASE_HAS_ACTUALS`, `ERR_PHASE_HAS_PENDING_AMENDMENT`).

Where two listed guards both apply to the same endpoint, the earlier-numbered guard fires first; the per-workflow orderings in §3 refine this sequence wherever several business gates stack on a single action.

### 2.10. Hierarchical Consistency and Derived-Value Reconciliation

Resources form a strict hierarchy: a firm owns clients, timekeepers, and — transitively — every matter artifact; a client owns matters; a matter owns fee arrangements, phase budgets, time entries, write-down requests, budget amendments, accrual reports, and collar true-ups. Every child also records its `firm_id`, and matter-scoped children record their `matter_id`, so any resource remains addressable within firm scope.

Consistency is immediate, not eventual. When a time entry is approved, a write-down is applied, a budget amendment is approved, or a phase budget is activated or voided, the matter's derived aggregates — `budget_total_cents`, `actual_fees_cents`, `write_down_total_cents`, `variance_cents`, `variance_pct_bp`, `variance_alert_level`, `revised_forecast_cents`, and `realization_rate_bp` — are recomputed as part of the same operation. Some transitions are performed by the system itself rather than by any user: a matter advances from `OPEN` to `ACTIVE` when a fee arrangement on it activates; a phase budget moves from `ACTIVE` to `AMENDED` when an amendment against it is approved; a time entry moves to `WRITTEN_DOWN` when a write-down covering it is applied; an arrangement moves from `ACTIVE` to `SUPERSEDED` when its successor activates. Each such reconciliation or system-driven transition mutates the owning resource, refreshing `updated_at` and incrementing `version` as described in §2.4.

### 2.11. Nested Resource Retrieval

Requests that address nested resources are validated left to right along the path: the system confirms the firm first, then each successive identifier, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist within the enclosing scope, without examining later identifiers. References supplied in request bodies — for example a `phase_budget_id` on a budget amendment — are likewise resolved within the firm scope, and an unresolvable reference is rejected with `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Firm Setup, the Timekeeper Roster, and Client Intake

Everything begins with the firm. A `FirmAdmin` creates it with a display `name` and the `fiscal_year_start_month` that anchors its fiscal calendar; the new firm starts life with `current_period_index` at 0 and `closed_through_period_index` at -1, meaning no period has yet been closed.

The same administrator onboards the timekeeper roster. Each timekeeper is registered with a `full_name`, a `bar_number` unique within the firm, a `role_title` of `ASSOCIATE`, `PARTNER`, `OF_COUNSEL`, or `PARALEGAL`, and a `standard_rate_cents` default billing rate. New timekeepers arrive in `ACTIVE` status; `INACTIVE` is the roster's other status value.

Clients are created by a `FirmAdmin` or a `BillingPartner`, each with a `display_name` and a `client_number` unique within the firm. Two optional flags govern the client's accrual obligations: `accrual_reporting_required`, defaulting to false, records whether the client mandates periodic accrual reports, and `accrual_reporting_cadence_periods`, defaulting to 1, records every how many fiscal periods a report must reach the client — a value of 1 means every period, that is, monthly. A client starts `ACTIVE`; the administrator may later suspend it (`ACTIVE` → `SUSPENDED`), reactivate it (`SUSPENDED` → `ACTIVE`), or close it from either `ACTIVE` or `SUSPENDED` into the terminal `CLOSED` state. Closing is permitted only once every matter belonging to the client has reached `CLOSED`; otherwise the request is rejected with `ERR_CLIENT_HAS_OPEN_MATTERS`.

### 3.2. Opening Matters and Papering the Fee Arrangement

A `FirmAdmin` or `BillingPartner` opens a matter under a client by supplying a `matter_number` unique within that client, a `title`, the `litigation_stage` at which work begins — one of `INTAKE`, `PLEADINGS`, `DISCOVERY`, `PRETRIAL`, `TRIAL`, or `APPEAL` — and the `responsible_partner_id` of the timekeeper accountable for the budget and its write-downs. The matter is born `OPEN`, with its `fee_arrangement_id` empty until an arrangement is activated.

Commercial papering is the pricing office's craft. A `PricingAnalyst` drafts a fee arrangement by choosing an `arrangement_type` — `FLAT_FEE`, `CAPPED_FEE`, `SUCCESS_FEE`, or `COLLAR` — and supplying the fields that type demands. The type-specific requirements are strict and exclusive: a `FLAT_FEE` arrangement must carry `flat_fee_cents`, which is null for every other type; a `CAPPED_FEE` arrangement must carry `capped_fee_cents`, the ceiling on billable fees; a `SUCCESS_FEE` arrangement must carry `success_fee_uplift_pct_bp`, the uplift in basis points applied on a successful outcome; and a `COLLAR` arrangement must carry all three of `collar_lower_bound_cents` (below which the firm absorbs the downside), `collar_upper_bound_cents` (above which the firm rebates the excess), and `collar_share_pct_bp` (the basis-point share of any out-of-band amount passed through to the client, the remainder being absorbed or retained by the firm). Every arrangement also records the `fiscal_year_index` it applies to — the fiscal year whose end triggers the collar true-up — and may optionally name a `supersedes_arrangement_id` to re-paper an existing arrangement. A matter carries at most one arrangement in `ACTIVE` or `PENDING_APPROVAL` at any moment; attempting to create a second such arrangement, or to submit toward one, is rejected with `ERR_ARRANGEMENT_ALREADY_ACTIVE`.

Submission by the `PricingAnalyst` moves the arrangement `DRAFT` → `PENDING_APPROVAL`. The submission guard checks two things: the type-specific fields must be complete, or the request fails with `ERR_ARRANGEMENT_FIELDS_INCOMPLETE` (HTTP 422); and the one-active-or-pending rule just described must hold. On submission the arrangement stamps the firm's current period into `submitted_period_index`.

Activation is a partner act — `BillingPartner` or `ManagingPartner` — and it is one of the two OCC-guarded writes in the API: the request must carry `expected_matter_version` matching the matter's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.7. The matter must be `OPEN`, `ACTIVE`, or `REOPENED`; otherwise activation fails with `ERR_MATTER_NOT_OPEN`. When the arrangement names a `supersedes_arrangement_id`, the referenced arrangement must currently be `ACTIVE`, and activation pushes that prior arrangement into `SUPERSEDED`. A successful activation stamps `activated_period_index` with the firm's current period, points the matter's `fee_arrangement_id` at the newly active arrangement, increments the matter's `version` by one, and — when the matter was still `OPEN` — automatically advances the matter to `ACTIVE`. A pending arrangement may instead be rejected by either partner role, moving it `PENDING_APPROVAL` → `REJECTED`. `SUPERSEDED` and `REJECTED` are the arrangement's terminal states; an `ACTIVE` arrangement leaves that state only through supersession by a successor.

### 3.3. Phase Budgets: Baselines, Activation, and Estimate-to-Complete

Beneath the arrangement, the budget itself is structured phase by phase. A `PricingAnalyst` or `BillingPartner` creates a phase budget with the `litigation_stage` it covers, a UTBMS-style `task_code` such as L110 or L210, the `original_budget_cents` baseline, and an optional `etc_cents` estimate-to-complete that defaults to 0. The phase budget is born `DRAFT` with `version_in_force` at 1, and while it remains `DRAFT` it contributes nothing to the matter's budget totals.

Activation — again by `PricingAnalyst` or `BillingPartner` — requires the matter to be `OPEN`, `ACTIVE`, or `REOPENED` (failing that, `ERR_MATTER_NOT_OPEN`) and requires `original_budget_cents` to be a positive amount (failing that, `ERR_INVALID_REQUEST`). Once `ACTIVE`, the phase's `current_budget_cents` enters the matter's `budget_total_cents`, and its `task_code` becomes a valid destination for time capture (see §3.4). From then on, the phase's `actual_to_date_cents` accumulates the `billable_amount_cents` of the matter's time entries in `APPROVED` or `BILLED` status whose `task_code` matches the phase's.

Voiding removes a phase from the budget landscape. A `DRAFT` phase budget may be voided freely, moving to the terminal `VOIDED` state. An `ACTIVE` phase budget may be voided only by a `BillingPartner`, and only when two guards pass, evaluated in order: its `actual_to_date_cents` must be zero, or the void is rejected with `ERR_PHASE_HAS_ACTUALS`; and no budget amendment in `DRAFT` or `PENDING_REVIEW` may reference it, or the void is rejected with `ERR_PHASE_HAS_PENDING_AMENDMENT`. A voided phase is excluded from the matter's `budget_total_cents`, which is recomputed immediately upon the void.

Finally, the pricing office maintains forward-looking estimates directly on the phase: updating `etc_cents` on an active phase budget — a capability shared by `PricingAnalyst` and `BillingPartner` — immediately refreshes the matter's `revised_forecast_cents` per the forecast rule in §3.5.

### 3.4. Capturing Time: From Draft Entry to Billed Revenue

Time capture starts with a draft. A `Timekeeper` — or a `BillingPartner` acting on the matter — records an entry with the `timekeeper_id` of the worker, the `task_code` and `litigation_stage` the work belongs to, `hours_worked_milli`, the `hourly_rate_cents` applied, and the `entry_date` on which the work occurred. At creation the system computes `billable_amount_cents` as `hours_worked_milli` multiplied by `hourly_rate_cents` and divided by one thousand, rounded down to a whole cent — this line-level floor rounding is pinned at creation and never recomputed later — and derives the entry's `period_index` as the fiscal period containing `entry_date` (see §2.6). The entry is born `DRAFT`.

Submission by the timekeeper or a billing partner moves the entry `DRAFT` → `SUBMITTED` and passes through four guards in a fixed order. First, the matter must be `ACTIVE` or `REOPENED`; an `OPEN`, `SUSPENDED`, or `CLOSED` matter rejects the submission with `ERR_MATTER_NOT_OPEN`. Second, the client must be `ACTIVE`; a `SUSPENDED` or `CLOSED` client rejects it with `ERR_CLIENT_NOT_ACTIVE`. Third, the entry's `period_index` must be strictly later than the firm's `closed_through_period_index`; an entry dated into a closed period is rejected with `ERR_PERIOD_CLOSED`. Fourth, the entry's `task_code` must match an `ACTIVE` phase budget on the matter, or the submission is rejected with `ERR_TASK_CODE_NOT_BUDGETED`.

Approval is exclusively a `BillingPartner` act and moves the entry `SUBMITTED` → `APPROVED`. Approval lands financially: the entry's `billable_amount_cents` is added to the matter's `actual_fees_cents`; the variance trio `variance_cents`, `variance_pct_bp`, and `variance_alert_level` is recomputed; and the matter's `last_activity_period_index` — the period of its most recent time-entry, write-down, or amendment activity, consulted by the closed-period guard on amendments — is set to the firm's current period. From `APPROVED`, the billing partner marks the entry billed, moving it `APPROVED` → `BILLED`. A billing partner may instead reject an entry, moving it from `DRAFT` or `SUBMITTED` into the terminal `REJECTED` state. The remaining transition — into the terminal `WRITTEN_DOWN` state — is never manual: it occurs only when an approved write-down covering the entry is applied, as described in §3.6, and it can be reached from either `APPROVED` or `BILLED`.

### 3.5. Variance Alerting, Forecasting, Realization, and Fee Quotes

The matter's financial posture is continuously derived. Its `budget_total_cents` is the sum of `current_budget_cents` over its phase budgets in `ACTIVE` or `AMENDED` status — draft and voided phases never count. Its `actual_fees_cents` is the sum of `billable_amount_cents` over entries in `APPROVED`, `BILLED`, or `WRITTEN_DOWN`, with one caveat: a `WRITTEN_DOWN` entry contributes its post-write-down remainder — its original amount minus its allocated write-down share — rather than its original amount. The signed `variance_cents` is `actual_fees_cents` minus `budget_total_cents`. When `budget_total_cents` is zero, `variance_pct_bp` is null; otherwise it is ten thousand times `variance_cents`, divided by `budget_total_cents`, rounded half-up to the nearest basis point. Two readings of variance exist: the gross reading, used for early-warning alerting, counts `WRITTEN_DOWN` entries at their original `billable_amount_cents`; the net reading, used for reporting and realization, counts their post-write-down remainder.

Alerting is threshold-driven, and the thresholds are boundary-pinned — a value exactly on a threshold escalates. The alerting value is the gross variance percentage: ten thousand times the gross variance — the gross-reading actuals, which count `WRITTEN_DOWN` entries at their original `billable_amount_cents`, minus `budget_total_cents` — divided by `budget_total_cents`, rounded half-up to the nearest basis point; `variance_cents` and `variance_pct_bp` themselves remain on the net reading. When `budget_total_cents` is zero — equivalently, when `variance_pct_bp` is null — `variance_alert_level` is `NONE`. Otherwise a gross variance percentage of at least 2000 basis points — twenty percent over budget — raises `BREACH`; a value of at least 1000 basis points, ten percent, raises `WARNING`; a value of at least 500 basis points, five percent, raises `WATCH`; anything lower, including any negative value, is `NONE`. A dedicated variance snapshot capability returns the matter's `variance_cents`, `variance_pct_bp`, `variance_alert_level`, `revised_forecast_cents`, and `realization_rate_bp` on demand.

Forecasting looks forward rather than backward. `revised_forecast_cents`, the estimate at completion, is the matter's `actual_fees_cents` plus the sum of `etc_cents` across its phases in `ACTIVE` or `AMENDED`. The evaluation order is pinned to avoid any circular reading: actuals are taken exactly as recorded, then the per-phase estimates-to-complete are added; `etc_cents` is an input maintained by the pricing office and must never be derived back from the forecast itself, so no recursion exists. Two analytical readings are recognized. The optimistic reading assumes every `DRAFT` and `SUBMITTED` entry will be rejected, so actuals comprise only `APPROVED`, `BILLED`, and `WRITTEN_DOWN` entries at their post-write-down remainder. The pessimistic reading assumes all `DRAFT` and `SUBMITTED` entries will be approved, counting them at their full `billable_amount_cents`.

Realization is computed in basis points and has two legitimate legal-finance readings, with the selection pinned by rule. When the matter has no applied write-downs — `write_down_total_cents` is zero — the collected reading applies, and `realization_rate_bp` is exactly 10000, one hundred percent, regardless of outstanding accruals. Once at least one write-down has been applied, the billing reading applies: `realization_rate_bp` is ten thousand times `actual_fees_cents`, divided by the sum of `actual_fees_cents` and `write_down_total_cents`, rounded half-up to the nearest basis point. The `write_down_total_cents` figure itself is the sum of `approved_amount_cents` over the matter's write-down requests in `APPLIED` state.

Before papering a deal, the pricing office can request a phase-level fee quote for a candidate `arrangement_type`. For each of the matter's phases in `ACTIVE` or `AMENDED` — taken in ascending `created_at` order with ties broken per §2.3, which is also the order of the returned `phase_quotes` array — the phase quote starts from the phase's `current_budget_cents`; under `CAPPED_FEE` each phase quote is the smaller of that phase's `current_budget_cents` and the arrangement's `capped_fee_cents`, applied per phase; under `FLAT_FEE`, `SUCCESS_FEE`, and `COLLAR` the per-phase figure remains `current_budget_cents`. Each phase quote is rounded half-up to a whole cent first, and only then are the rounded phase quotes summed — this per-phase-first rounding order is pinned, because summing first and rounding once would yield different cents. The total, returned as `total_quote_cents` alongside the `phase_quotes` array, is then determined by type: under `FLAT_FEE` the total is exactly `flat_fee_cents`, replacing the phase sum entirely; under `SUCCESS_FEE` the summed phase quotes are multiplied by one plus `success_fee_uplift_pct_bp` ten-thousandths, with the product rounded half-up to a whole cent; under `CAPPED_FEE` and `COLLAR` the total is the sum of the rounded phase quotes, the collar itself being resolved only at year-end (see §3.9).

### 3.6. Write-Down Requests and the Authority Ladder

When billed or approved work must be conceded, a `BillingPartner` drafts a write-down request naming the target `time_entry_ids`, the total `requested_amount_cents` to concede across them, and a `reason_code` of `CLIENT_RELATIONS`, `BILLING_ERROR`, `SCOPE_DISPUTE`, `COLLECTIBILITY`, or `COURT_ORDER`. The request is born `DRAFT`, and the creator's user id is captured into `requested_by_user_id` at that moment. Already at creation, every listed entry must exist, belong to the matter, and be in `APPROVED` or `BILLED` — violations are rejected with `ERR_WRITE_DOWN_ENTRIES_INVALID` (HTTP 422) — and `requested_amount_cents` must be greater than zero and no more than the sum of the listed entries' `billable_amount_cents`, or creation is rejected with `ERR_WRITE_DOWN_AMOUNT_INVALID` (HTTP 422). A draft that will not be pursued may be cancelled, moving `DRAFT` → `CANCELLED`, but only by the same user who requested it; anyone else's attempt is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

Submitting the request re-validates it, because the underlying entries may have moved since drafting: existence or matter-ownership failures again surface as `ERR_WRITE_DOWN_ENTRIES_INVALID`; entries no longer in `APPROVED` or `BILLED` surface as `ERR_WRITE_DOWN_ENTRY_STATE`; and an amount that no longer satisfies the positive-and-within-sum bound surfaces as `ERR_WRITE_DOWN_AMOUNT_INVALID`. Submission also routes the request by amount. When `requested_amount_cents` is at most the partner authority threshold `PARTNER_WRITE_DOWN_AUTHORITY_CENTS`, the request moves `DRAFT` → `PENDING_PARTNER`; above that threshold the system automatically escalates it, moving it to `PENDING_MANAGING_PARTNER` instead.

Decisions follow the segregation-of-duties rule of §2.8: the decider's id, recorded into `decided_by_user_id`, must differ from `requested_by_user_id`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. The `decision` payload carries the approve-or-reject outcome. A request waiting at partner tier is decided by a `BillingPartner`; an escalated request waiting at `PENDING_MANAGING_PARTNER` is decided by a `ManagingPartner`. Approval moves the request to `APPROVED`, stamps `approved_amount_cents` equal to `requested_amount_cents` — there is no partial approval in this version — and records the firm's current period into `decided_period_index`. Rejection moves the request to the terminal `REJECTED` state from either tier.

An approved write-down has no financial effect until a `BillingPartner` or `ManagingPartner` applies it. Application requires the matter to be `ACTIVE` or `REOPENED`, failing which it is rejected with `ERR_MATTER_NOT_OPEN`. On application, `approved_amount_cents` is allocated across the listed entries proportionally to their `billable_amount_cents`: each entry's raw share is the approved amount multiplied by that entry's `billable_amount_cents` and divided by the total of `billable_amount_cents` across the listed entries; each share is rounded down to a whole cent; and the leftover cents — always fewer than the number of listed entries — are distributed one cent at a time to entries in ascending `created_at` order (entries sharing an identical `created_at` are ordered by the internal sequence described in §2.3) until none remain. Every listed entry then transitions to `WRITTEN_DOWN`, and the request itself moves `APPROVED` → `APPLIED`, which is terminal. The matter's books absorb the concession in the same operation: `actual_fees_cents` is reduced by each entry's allocated share, `write_down_total_cents` grows by the allocated shares, and `variance_cents`, `variance_pct_bp`, `variance_alert_level`, and `realization_rate_bp` are all recomputed.

### 3.7. Scope Change: Budget Amendments and Revision Chains

Scope evolves, and the budget moves with it through amendments. A `PricingAnalyst` drafts a budget amendment naming the target `phase_budget_id`, a signed `delta_cents` — negative reduces the budget — a free-text `scope_change_reason`, and optionally a `supersedes_amendment_id` linking the new amendment onto a revision chain; the requester's user id is captured into `requested_by_user_id`, and the amendment is born `DRAFT`. Two guards already apply at creation: if `supersedes_amendment_id` is set, the referenced amendment must be in `REJECTED` or `SUPERSEDED`, or creation fails with `ERR_AMENDMENT_SUPERSEDE_INVALID`; and the proposed delta must not drive the target phase's `current_budget_cents` below zero, or creation fails with `ERR_AMENDMENT_NEGATIVE_BUDGET` (HTTP 422).

Submission by the pricing analyst moves the amendment `DRAFT` → `PENDING_REVIEW` and re-checks a six-part battery in order: the target phase budget must be `ACTIVE` or `AMENDED`, else `ERR_PHASE_NOT_AMENDABLE`; the matter must be `ACTIVE` or `REOPENED`, else `ERR_MATTER_NOT_OPEN`; a set `supersedes_amendment_id` must still reference a `REJECTED` or `SUPERSEDED` amendment, else `ERR_AMENDMENT_SUPERSEDE_INVALID`; `delta_cents` must not be zero, else `ERR_INVALID_REQUEST`; the resulting `current_budget_cents` must remain non-negative, else `ERR_AMENDMENT_NEGATIVE_BUDGET`; and the matter's `last_activity_period_index` must be strictly later than the firm's `closed_through_period_index`, else `ERR_PERIOD_CLOSED` — a matter cannot be retroactively amended into a closed period.

The decision is the second OCC-guarded write in the API: the deciding partner's request carries the `decision` together with an `expected_matter_version` matching the matter's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.7. Two further checks then follow in order. Segregation of duties comes first — the recorded `decided_by_user_id` must differ from `requested_by_user_id`, else the decision fails with `ERR_SEGREGATION_OF_DUTIES` — so a self-approval surfaces before any authority question is examined. Then authority: a `BillingPartner` may approve only when the amendment's magnitude — the absolute value of `delta_cents` — is at most `PARTNER_AMENDMENT_AUTHORITY_CENTS`; a larger magnitude requires a `ManagingPartner`, and a `BillingPartner` attempting it is rejected with `ERR_AMENDMENT_AUTHORITY_EXCEEDED` (HTTP 403).

Approval lands immediately on the phase and the matter. The target phase's `current_budget_cents` increases by `delta_cents`, its `version_in_force` increments by one, and its status becomes `AMENDED` — or stays `AMENDED` when a subsequent amendment lands on an already-amended phase. If the amendment named a `supersedes_amendment_id`, the referenced amendment moves to `SUPERSEDED`. On the matter, `budget_total_cents`, the variance trio, and `revised_forecast_cents` are recomputed, and the matter's `version` increments by one. Rejection moves the amendment `PENDING_REVIEW` → `REJECTED` with no financial effect. `APPROVED` and `REJECTED` are the amendment's terminal states, with `SUPERSEDED` reachable when a later approved amendment re-papers it.

### 3.8. Client Accrual Reporting

Clients who mandate accrual reporting receive a report per matter on the cadence declared at intake: every `accrual_reporting_cadence_periods` fiscal periods, a report for the matter must reach `SUBMITTED`. Each period advancement regenerates a fresh `DRAFT` accrual report covering the new period on every such matter, and a matter carries at most one report per `period_index`.

Two amounts are computed from the matter's time entries. `accrued_fees_cents` sums `billable_amount_cents` over entries in `APPROVED` or `BILLED` whose `period_index` equals the report's period — period attribution follows the entry's own `entry_date`. `unbilled_wip_cents` sums `billable_amount_cents` over entries in `DRAFT`, `SUBMITTED`, or `APPROVED` whose `period_index` is at or before the report's period, inclusive through the period's end. Entries in `WRITTEN_DOWN` are excluded from both figures, having already been realized net. While a report remains in `DRAFT` these two amounts are live rather than frozen: every period advancement recomputes them from the matter's then-current entries on every report still in `DRAFT`, and submission and resubmission each recompute them as well; once a report has left `DRAFT`, later advancements leave its amounts untouched.

Submission is a `BillingPartner` act moving the report `DRAFT` → `SUBMITTED`, permitted while the matter is `ACTIVE`, `REOPENED`, or `SUSPENDED` — otherwise `ERR_MATTER_NOT_OPEN`. Submission freezes two snapshots onto the report: `forecast_at_complete_cents` takes the matter's `revised_forecast_cents` as of that moment, and `variance_at_submission_cents` takes the matter's `variance_cents`; the firm's current period is recorded into `submitted_period_index`. From `SUBMITTED`, a `ClientContact` acknowledges the report — moving it to the terminal `ACKNOWLEDGED` state — or disputes it, moving it to `DISPUTED`. A disputed report returns to `SUBMITTED` when a `BillingPartner` resubmits it, at which point the two snapshot fields are recomputed from the matter's current state.

### 3.9. Closing the Loop: Matter Close-Out, Reopening, and Year-End Collar True-Up

Mid-flight, a `BillingPartner` or `ManagingPartner` may suspend an `ACTIVE` matter (`ACTIVE` → `SUSPENDED`) and later resume it (`SUSPENDED` → `ACTIVE`); a suspended matter accepts no time submissions but still permits accrual reporting, per §3.8.

Closing a matter is a gated act, available to `BillingPartner` or `ManagingPartner` from `ACTIVE`, `SUSPENDED`, or `REOPENED`, with the same five-part battery evaluated in each case, in this order. First, no time entry may remain in `DRAFT`, `SUBMITTED`, or `APPROVED`, else the close is rejected with `ERR_MATTER_HAS_OPEN_WIP`. Second, no write-down request may remain in `DRAFT`, `PENDING_PARTNER`, or `PENDING_MANAGING_PARTNER`, else `ERR_MATTER_HAS_PENDING_WRITE_DOWNS`. Third, no budget amendment may remain in `DRAFT` or `PENDING_REVIEW`, else `ERR_MATTER_HAS_PENDING_AMENDMENTS`. Fourth, when the matter's arrangement is a `COLLAR` whose fiscal year has ended, its true-up must be `SETTLED` or `WAIVED`, else `ERR_MATTER_COLLAR_UNSETTLED`. Fifth, when the client mandates accrual reporting, the matter's latest accrual report must be `SUBMITTED` or `ACKNOWLEDGED`, else `ERR_MATTER_ACCRUAL_OUTSTANDING`. A matter that has never left `OPEN` has no defined close transition and cannot be closed; `CLOSED` is the matter's terminal state.

A closed matter can be brought back — by a `ManagingPartner` only — within a bounded reopen window: the closure must fall within `closed_through_period_index` plus two periods. Outside that window the attempt is rejected with `ERR_REOPEN_WINDOW_CLOSED`. A successful reopen moves the matter to `REOPENED`, which behaves as `ACTIVE` for billing purposes — time submission, write-down application, amendment submission, and the other matter-open gates all accept it — and closing from `REOPENED` repeats the same five-part battery.

The year-end collar true-up settles collared arrangements. Once the fiscal year identified by an arrangement's `fiscal_year_index` has ended, a `BillingPartner` or `ManagingPartner` runs the true-up for the matter; running it against a non-`COLLAR` arrangement, or before the arrangement's fiscal year has ended, is rejected with `ERR_INVALID_STATE_TRANSITION`. Each run computes and persists a new true-up record in `COMPUTED` status, one per arrangement for the year being trued up, carrying three computed figures. `actual_year_fees_cents` is the sum of `billable_amount_cents` over the matter's `BILLED` entries in that fiscal year. `true_up_amount_cents` and `direction` follow the three-band collar rule, with strict boundaries: when actual fees are strictly below `collar_lower_bound_cents`, the shortfall is the lower bound minus the actual fees, the client compensates the firm for the `collar_share_pct_bp` share of that shortfall — the share taken as a fraction of ten thousand — rounded half-up to the nearest cent, `true_up_amount_cents` is that amount as a negative figure, and `direction` is `COLLECT_FROM_CLIENT`; when actual fees are strictly above `collar_upper_bound_cents`, the excess is the actual fees minus the upper bound, the firm rebates the same share of that excess rounded half-up to the nearest cent, `true_up_amount_cents` is that amount as a positive figure, and `direction` is `REBATE_TO_CLIENT`; and when actual fees sit between the bounds — exactly equal to either bound included — `true_up_amount_cents` is zero and `direction` is `IN_BAND`. A positive amount always means the firm owes the client a rebate; a negative amount always means the client owes the firm. Settlement of a computed true-up (`COMPUTED` → `SETTLED`) is shared by both partner roles, while waiving it (`COMPUTED` → `WAIVED`) is reserved to the `ManagingPartner`; both are terminal.

Only when every matter is finally `CLOSED` may the `FirmAdmin` close the client itself, as described in §3.1.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code — this includes firms, timekeepers, clients, matters, fee arrangements, phase budgets, time entries, write-down requests, budget amendments, and the collar true-up run, which persists a new true-up record. Operations that modify or transition an existing resource, and all reads, return a `200 OK` status code. Request and response payloads for each operation are defined by the narratives in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/firms` | Create a Firm (tenant root) | FirmAdmin |
| GET | `/firms/{firmId}` | Get Firm | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, Timekeeper, ClientContact |
| POST | `/firms/{firmId}/advance_period` | Advance fiscal period; triggers auto-transitions, snapshot updates, collar true-up scheduling | FirmAdmin |
| POST | `/firms/{firmId}/close_books` | Close books through current period | FirmAdmin, ManagingPartner |
| POST | `/firms/{firmId}/timekeepers` | Onboard a Timekeeper | FirmAdmin |
| GET | `/firms/timekeepers/{timekeeperId}` | Get Timekeeper (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, Timekeeper |
| GET | `/firms/timekeepers` | List Timekeepers (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, Timekeeper |
| POST | `/firms/{firmId}/clients` | Create Client | FirmAdmin, BillingPartner |
| GET | `/firms/clients/{clientId}` | Get Client (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, ClientContact |
| GET | `/firms/clients` | List Clients (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, ClientContact |
| POST | `/firms/{firmId}/clients/{clientId}/suspend` | Suspend a client | FirmAdmin |
| POST | `/firms/{firmId}/clients/{clientId}/activate` | Reactivate a suspended client | FirmAdmin |
| POST | `/firms/{firmId}/clients/{clientId}/close` | Close a client | FirmAdmin |
| POST | `/firms/{firmId}/clients/{clientId}/matters` | Create Matter | FirmAdmin, BillingPartner |
| GET | `/firms/matters/{matterId}` | Get Matter (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, Timekeeper, ClientContact |
| GET | `/firms/matters` | List Matters (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, ClientContact |
| GET | `/firms/clients/{clientId}/matters` | List Matters for Client (sub-resource) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, ClientContact |
| POST | `/firms/{firmId}/matters/{matterId}/suspend` | Suspend a matter | BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/matters/{matterId}/resume` | Resume a suspended matter | BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/matters/{matterId}/close` | Close a matter | BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/matters/{matterId}/reopen` | Reopen a closed matter (moves to REOPENED) | ManagingPartner |
| GET | `/firms/{firmId}/matters/{matterId}/quote` | Compute phase-level fee quote for a given arrangement_type | PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/{firmId}/matters/{matterId}/variance` | Get actual-vs-budget variance snapshot | PricingAnalyst, BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/matters/{matterId}/fee_arrangements` | Create FeeArrangement (DRAFT) | PricingAnalyst |
| GET | `/firms/fee_arrangements/{arrangementId}` | Get FeeArrangement (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/fee_arrangements` | List FeeArrangements (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/matters/{matterId}/fee_arrangements` | List FeeArrangements for Matter (sub-resource) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/fee_arrangements/{arrangementId}/submit` | Submit for approval | PricingAnalyst |
| POST | `/firms/{firmId}/fee_arrangements/{arrangementId}/activate` | Activate arrangement (requires OCC expected_matter_version) | BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/fee_arrangements/{arrangementId}/reject` | Reject a pending arrangement | BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/matters/{matterId}/phase_budgets` | Create PhaseBudget (DRAFT) | PricingAnalyst, BillingPartner |
| GET | `/firms/phase_budgets/{phaseBudgetId}` | Get PhaseBudget (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/phase_budgets` | List PhaseBudgets (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/matters/{matterId}/phase_budgets` | List PhaseBudgets for Matter (sub-resource) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/phase_budgets/{phaseBudgetId}/activate` | Activate PhaseBudget | PricingAnalyst, BillingPartner |
| POST | `/firms/{firmId}/phase_budgets/{phaseBudgetId}/void` | Void a PhaseBudget | BillingPartner |
| PATCH | `/firms/phase_budgets/{phaseBudgetId}` | Update ETC (estimate-to-complete) on an active phase budget | PricingAnalyst, BillingPartner |
| POST | `/firms/{firmId}/matters/{matterId}/time_entries` | Create a draft TimeEntry | Timekeeper, BillingPartner |
| GET | `/firms/time_entries/{entryId}` | Get TimeEntry (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, Timekeeper |
| GET | `/firms/time_entries` | List TimeEntries (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, Timekeeper |
| GET | `/firms/matters/{matterId}/time_entries` | List TimeEntries for Matter (sub-resource) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, Timekeeper |
| POST | `/firms/{firmId}/time_entries/{entryId}/submit` | Submit a time entry | Timekeeper, BillingPartner |
| POST | `/firms/{firmId}/time_entries/{entryId}/approve` | Approve a submitted entry | BillingPartner |
| POST | `/firms/{firmId}/time_entries/{entryId}/mark_billed` | Mark approved entry as billed | BillingPartner |
| POST | `/firms/{firmId}/time_entries/{entryId}/reject` | Reject a draft/submitted entry | BillingPartner |
| POST | `/firms/{firmId}/matters/{matterId}/write_down_requests` | Create a write-down request | BillingPartner |
| GET | `/firms/write_down_requests/{requestId}` | Get WriteDownRequest (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/write_down_requests` | List WriteDownRequests (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/matters/{matterId}/write_down_requests` | List WriteDownRequests for Matter (sub-resource) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/write_down_requests/{requestId}/submit` | Submit for approval (auto-escalates to managing partner if above authority) | BillingPartner |
| POST | `/firms/{firmId}/write_down_requests/{requestId}/decide` | Approve or reject (segregation of duties enforced) | BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/write_down_requests/{requestId}/apply` | Apply an approved write-down to its time entries | BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/write_down_requests/{requestId}/cancel` | Cancel a draft (by requester only) | BillingPartner |
| POST | `/firms/{firmId}/matters/{matterId}/budget_amendments` | Create a BudgetAmendment | PricingAnalyst |
| GET | `/firms/budget_amendments/{amendmentId}` | Get BudgetAmendment (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/budget_amendments` | List BudgetAmendments (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/matters/{matterId}/budget_amendments` | List BudgetAmendments for Matter (sub-resource) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/phase_budgets/{phaseBudgetId}/budget_amendments` | List Amendments for a PhaseBudget (reverse reachability) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/budget_amendments/{amendmentId}/submit` | Submit amendment for review | PricingAnalyst |
| POST | `/firms/{firmId}/budget_amendments/{amendmentId}/decide` | Approve or reject (OCC on Matter.version; segregation of duties) | BillingPartner, ManagingPartner |
| GET | `/firms/accrual_reports/{reportId}` | Get AccrualReport (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, ClientContact |
| GET | `/firms/accrual_reports` | List AccrualReports (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, ClientContact |
| GET | `/firms/matters/{matterId}/accrual_reports` | List AccrualReports for Matter (sub-resource) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner, ClientContact |
| POST | `/firms/{firmId}/accrual_reports/{reportId}/submit` | Submit accrual report to client | BillingPartner |
| POST | `/firms/{firmId}/accrual_reports/{reportId}/acknowledge` | Client acknowledges accrual report | ClientContact |
| POST | `/firms/{firmId}/accrual_reports/{reportId}/dispute` | Client disputes accrual report | ClientContact |
| POST | `/firms/{firmId}/accrual_reports/{reportId}/resubmit` | Resubmit a disputed report with recomputed snapshot | BillingPartner |
| POST | `/firms/{firmId}/matters/{matterId}/run_year_end_collar_true_up` | Run year-end collar true-up; computes and persists a CollarTrueUp | BillingPartner, ManagingPartner |
| GET | `/firms/collar_true_ups/{trueUpId}` | Get CollarTrueUp (flat) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/collar_true_ups` | List CollarTrueUps (flat, filterable) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| GET | `/firms/matters/{matterId}/collar_true_ups` | List CollarTrueUps for Matter (sub-resource) | FirmAdmin, PricingAnalyst, BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/collar_true_ups/{trueUpId}/settle` | Settle a computed true-up | BillingPartner, ManagingPartner |
| POST | `/firms/{firmId}/collar_true_ups/{trueUpId}/waive` | Waive a computed true-up (managing partner only) | ManagingPartner |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set logical clock. Default startup time is 2026-08-01T00:00:00Z. After set, all derived date/period computations use this clock. | FirmAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; the table below is an index of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MATTER_NOT_OPEN` | 409 Conflict |
| `ERR_CLIENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PERIOD_CLOSED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_ARRANGEMENT_FIELDS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_ARRANGEMENT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_TASK_CODE_NOT_BUDGETED` | 409 Conflict |
| `ERR_WRITE_DOWN_ENTRIES_INVALID` | 422 Unprocessable Entity |
| `ERR_WRITE_DOWN_ENTRY_STATE` | 422 Unprocessable Entity |
| `ERR_WRITE_DOWN_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_AMENDMENT_NEGATIVE_BUDGET` | 422 Unprocessable Entity |
| `ERR_AMENDMENT_AUTHORITY_EXCEEDED` | 403 Forbidden |
| `ERR_AMENDMENT_SUPERSEDE_INVALID` | 409 Conflict |
| `ERR_MATTER_HAS_OPEN_WIP` | 409 Conflict |
| `ERR_MATTER_HAS_PENDING_WRITE_DOWNS` | 409 Conflict |
| `ERR_MATTER_HAS_PENDING_AMENDMENTS` | 409 Conflict |
| `ERR_MATTER_COLLAR_UNSETTLED` | 409 Conflict |
| `ERR_MATTER_ACCRUAL_OUTSTANDING` | 409 Conflict |
| `ERR_CLIENT_HAS_OPEN_MATTERS` | 409 Conflict |
| `ERR_REOPEN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_PHASE_HAS_ACTUALS` | 409 Conflict |
| `ERR_PHASE_HAS_PENDING_AMENDMENT` | 409 Conflict |
| `ERR_PHASE_NOT_AMENDABLE` | 409 Conflict |
