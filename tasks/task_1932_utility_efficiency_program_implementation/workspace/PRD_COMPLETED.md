# Utility Efficiency Program API — Product Requirements Document

## 1. Introduction

Demand-side energy-efficiency programs live or die on execution in the field. A utility's implementation partner must recruit a network of trade allies, route customer opportunities to the right firm, schedule installation work against real calendars, pay incentives to the correct party, and prove to regulators — through independent inspection and cost-effectiveness accounting — that ratepayer money bought verifiable savings. This document specifies the API for a program-implementation platform in the CLEAResult mold: it manages the full lifecycle from contractor onboarding and certification through lead distribution, work-order execution, quality inspection and remediation, incentive settlement, complaint handling, and Total Resource Cost reporting.

The platform is, at its core, a workflow orchestrator with strong compliance-audit characteristics. State changes on one resource routinely cascade into others: a failed inspection can suspend a contractor and expire its outstanding offers; an expired certification can quietly remove a firm from the distribution pool; a project approval commits program budget in the same atomic step that creates its payment shell. Four actor roles interact with the platform — program operations staff, the trade allies themselves, independent inspectors, and utility customers — with tightly segregated duties. A server-maintained logical clock drives every time-dependent behavior (certification expiry, remediation deadlines, complaint recency, reporting periods), so all temporal rules in this document are expressed against that clock rather than against wall time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The API recognizes exactly four roles: `ProgramManager`, `Contractor`, `Inspector`, and `Customer`. A request missing either header, or presenting an empty or whitespace-only value for one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the per-endpoint role assignments appear in §4.

Role identity resolves differently per role. When `X-User-Role` is `ProgramManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any resource's `id`. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting Contractor, and ownership checks on any resource that references a contractor — an assigned lead, a work order — compare the resource's contractor foreign-key field to `X-User-ID`. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting Inspector, compared against the inspector references on inspections and work-order inspection assignments. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer, compared against the customer references on complaints, projects, and payments. These entity-backed comparisons power the `ERR_NOT_RESOURCE_OWNER` rejections described throughout §3.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the server's logical clock (§2.5).
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

Requests that are malformed in ways no rule in §3 covers — a missing, unparsable, or non-object JSON body, a non-numeric `limit` or `offset`, or a missing or unparseable `to_iso8601` — are rejected with `ERR_INVALID_INSPECTION_PAYLOAD` (HTTP 400). A request to an undefined path, or with a method the path does not support, is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

List endpoints paginate via two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100 — out-of-range values are clamped rather than rejected (a `limit` below 1 is treated as 1, a `limit` above 100 as 100, and a negative `offset` as 0). The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order, with ties breaking toward the lowest `id`. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in this API — programs, contractors, certifications, customers, leads, projects, work orders, inspectors, inspections, incentive payments, complaints, and cost-effectiveness reports — carries the same four system-managed fields:

- `id`: a server-minted UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version`: an integer that starts at 1 at creation (with `updated_at` initially equal to `created_at`) and increments by one on every mutation of the resource.

Recomputing a derived field on a resource — a program's committed totals, a contractor's quality score, a payment's reconciliation delta — is a mutation of that resource: its `updated_at` refreshes and its `version` advances.

### 2.5. The Logical Clock

The server maintains its own logical UTC clock rather than consulting wall time. Before any explicit adjustment, the clock reads 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A ProgramManager-only capability (`POST /efficiency/_clock/set_current_utc`) moves the clock to a caller-supplied instant `to_iso8601` (the supplied instant is not required to be later than the current reading); the response reports the resulting `current_utc` and a count `certifications_expired` of certifications swept by the advance. Advancing the clock sweeps every certification whose `expires_on` falls at or before the new instant, moving it from `ACTIVE` to `EXPIRED` and applying the standing consequences described in §3.2 — each expiry decrements the owning contractor's `active_certification_count`, and when that count reaches zero on an `APPROVED` contractor, the contractor is automatically suspended. The logical clock also governs work-order start-date gating, remediation deadlines, the rolling complaint window, and reporting-period boundaries.

### 2.6. Request Validation Order and Resource Resolution

URL paths in this API carry a single resource identifier. When the path-referenced resource does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Separately, every foreign key referenced in a request body — `customer_id`, `contractor_id`, `program_id`, `lead_id`, `project_id`, `work_order_id`, `inspector_id`, or `payee_id` — must resolve to an existing resource, or the request is rejected with `ERR_REFERENCED_NOT_FOUND` (HTTP 404). Beyond the rules documented in this section and in §3, the API performs no field-presence or vocabulary validation on payloads: an omitted numeric field defaults to zero, an omitted list field to empty, any other omitted field is stored as null, and the parenthesized value vocabularies of §3 (sectors, measure types, source channels, categories, severities) are descriptive rather than enforced.

Validation on every request proceeds in a fixed global order, and an earlier failure masks all later checks. Authentication and role authorization come first (§2.1). Path-existence resolution follows, then body foreign-key resolution, then state-transition validity — a transition requested from a state that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409). Optimistic-concurrency checks come next (§2.7). Business rules run last, in their documented priority: the segregation-of-duties screen (§3.5–3.6) ahead of certification requirements, then program-active requirements, then caller ownership, then the calendar-overlap screen, then selector emptiness, then inspector availability, then the temporal rules (early start, expired remediation window, escalation severity), then the fiscal rules (budget headroom, reconciliation necessity), then inspection-payload shape, and finally the program-close and contractor-terminate guards. Where an endpoint's narrative in §3 documents a more specific check order, that endpoint-specific order governs.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each takes a mandatory expected-version field.

`POST /efficiency/projects/{project_id}/approve` requires the request to carry `expected_program_version`, holding the target program's `version` as the client last observed it. When the program's current `version` differs — because, for instance, another approval has since committed budget against the same program and the client's view of `committed_cents` is stale — the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), so a budget check is never evaluated against a baseline the client never saw.

`POST /efficiency/leads/{lead_id}/distribute` requires the request to carry `expected_lead_version`, holding the lead's `version` as the client last observed it. A mismatch — because, for instance, an earlier distribution already assigned the lead, leaving the client's view of `assigned_contractor_id` stale — is rejected with `ERR_STALE_LEAD_VERSION` (HTTP 412).

On both endpoints, omitting the expected-version field is treated as a version mismatch and draws the same 412 rejection. Endpoints other than these two do not accept an expected-version field.

### 2.8. Monetary Values and Numeric Precision

All monetary amounts in the API are integer cents. Incentive amounts are computed to whole cents, but the rounding direction depends on the variant: the provisional incentive computed at project approval rounds down (floor), while the final incentive computed at project completion rounds half up. Contractor quality scores are integer basis points between 0 and 10,000 inclusive, rounded half up when recomputed. Cost-effectiveness reporting keeps intermediate benefit figures at four decimal places (rounded half up) and rounds the resulting `trc_ratio` half up to four decimal places.

### 2.9. Program Budget Accounting

Each program behaves as a small ledger. The `budget_cents` field is the total incentive appropriation. The `committed_cents` field tracks incentive obligations across the program's post-approval project population — projects that are approved, scheduled, installed, under inspection, or completed — and moves only through two audited events: it grows by a project's incentive amount at approval, and it is released when an in-flight project is cancelled. The `paid_cents` field tracks money actually disbursed: it grows by the provisional amount when a payment is disbursed and is later trued up, positively or negatively, when that payment is reconciled, so that a fully reconciled payment has contributed exactly its final amount. Approval is refused whenever the commitment it would create exceeds the remaining appropriation (§3.4). Closing a program freezes `committed_cents` — no further approval can commit — while disbursement and reconciliation of already-authorized payments continue to adjust `paid_cents` after closure.

### 2.10. Contractor Standing Signals

Three computed signals summarize a trade ally's standing and are maintained continuously by the platform. The `qa_score_bps` field is a rolling quality score in basis points, recomputed from the contractor's most recent scored inspections (§3.6); a newly registered contractor starts at a perfect 10,000. The `complaint_count_90d` field counts the contractor's unresolved complaints inside a trailing 90-day window measured against the logical clock (§3.8). The `active_certification_count` field tracks how many of the contractor's certifications remain `ACTIVE`. These signals drive automated discipline: falling quality, a cluster of escalated complaints, or the loss of a last certification can each move a contractor to `SUSPENDED` without any human request.

## 3. Business Logic & Workflows

### 3.1. Program Definition and Lifecycle

A `ProgramManager` opens a program by supplying a `code` (for example, a residential HVAC program for the 2026 cycle), a human-readable `name`, the `sector` the program serves (`RESIDENTIAL`, `COMMERCIAL`, or `INDUSTRIAL`), the total incentive appropriation `budget_cents`, an annual savings goal `avoided_kwh_target`, and the cost-effectiveness bar `trc_threshold`. New programs are born in `DRAFT`, with `committed_cents`, `paid_cents`, and `avoided_kwh_actual` all at zero.

Activation moves a program `DRAFT` → `ACTIVE` and is allowed only when `budget_cents` is positive and `trc_threshold` has been configured (a `DRAFT` program failing either condition is refused with `ERR_INVALID_STATE`); an `ACTIVE` program is eligible for lead creation and project approval. Suspension moves a program `ACTIVE` → `SUSPENDED` and closes the intake valves: while suspended, the program accepts no new leads, no lead distributions, and no project approvals. Any operation requiring an active program — creating a lead, distributing a lead, approving a project — is rejected with `ERR_PROGRAM_NOT_ACTIVE` whenever the program is not `ACTIVE`, whether it sits in `DRAFT`, `SUSPENDED`, or `CLOSED`. A suspended program can be reactivated unconditionally (`SUSPENDED` → `ACTIVE`).

Closing is the terminal act: a program in `ACTIVE` or `SUSPENDED` may move to `CLOSED`, but only when none of its projects remains in flight — that is, when no project of the program sits in `PROPOSED`, `APPROVED`, `SCHEDULED`, `INSTALLED`, `INSPECTING`, or `REMEDIATION`. A close requested while such projects exist is rejected with `ERR_PROGRAM_HAS_OPEN_PROJECTS`. Closing freezes the program's `committed_cents` — already-authorized payments still disburse and reconcile against `paid_cents` afterward (§2.9) — and `CLOSED` is terminal. The program's attainment metric, `avoided_kwh_actual`, accumulates the `estimated_annual_kwh_savings` of each project as that project reaches `COMPLETED`, to be read against the `avoided_kwh_target` set at creation. Program lists may be filtered by `status` and `sector`.

### 3.2. Trade Ally Onboarding, Certification, and Network Standing

Registration of a trade ally is a `ProgramManager` act: the platform records the firm's `legal_name`, its state `license_number`, the `sector` it serves, and the `service_zip_codes` it covers. New contractors land in `APPLIED` with a pristine `qa_score_bps` of 10,000 basis points, a `qa_window_size` of ten inspections, and every counter — `active_certification_count`, `on_time_installs`, `late_installs`, `complaint_count_90d` — at zero.

Approval moves a contractor `APPLIED` → `APPROVED` and requires the firm to hold at least one `ACTIVE` certification; without one the approval is refused with `ERR_CERTIFICATION_MISSING`. The approval persists the certification-count refresh and the status change as separate mutations, so the contractor's `version` advances by two on approval. An approved contractor becomes eligible to receive lead distributions. Certifications themselves are issued by a `ProgramManager`, who names the `contractor_id`, the `measure_type` being certified (`HVAC`, `INSULATION`, `LIGHTING`, `WATER_HEATING`, or `SOLAR`), the `issued_on` date, and the `expires_on` date; a certification is born `ACTIVE` and its issuance increments the contractor's `active_certification_count`. Two forces end a certification. The logical clock expires it (`ACTIVE` → `EXPIRED`) once the clock reaches its `expires_on` (§2.5), and a `ProgramManager` may revoke it (`ACTIVE` → `REVOKED`). Either ending decrements `active_certification_count`, and when that decrement leaves an `APPROVED` contractor with zero active certifications, the contractor is automatically suspended — an automatic suspension carries exactly the consequences of a manual one, described below. Certification lists may be filtered by `contractor_id`, `measure_type`, and `status`.

Suspension moves a contractor `APPROVED` → `SUSPENDED`: the firm is excluded from future lead distribution, and every `OFFERED` lead currently assigned to it automatically expires (`OFFERED` → `EXPIRED`), clearing the lead's `assigned_contractor_id`. Reinstatement moves `SUSPENDED` → `APPROVED` and again requires at least one `ACTIVE` certification, failing with `ERR_CERTIFICATION_MISSING` otherwise. Termination is permanent: from `APPROVED` or `SUSPENDED` a contractor moves to `TERMINATED`, but the platform refuses with `ERR_CONTRACTOR_BUSY` while any of the firm's work orders remains `SCHEDULED` or `IN_PROGRESS`. On termination, every `NEW` or `OFFERED` lead assigned to the firm moves to `WITHDRAWN`, clearing any `assigned_contractor_id`. Contractor lists may be filtered by `status` and `sector`, and reading a single contractor record refreshes its `complaint_count_90d` against the current logical clock (§3.8).

### 3.3. Customer Intake and Lead Distribution

Before any lead can exist, a `ProgramManager` registers the customer with a `full_name`, an `email`, the `service_zip` where the work would occur, the customer's `sector`, and the `utility_account_id` from the utility's billing system.

A lead captures a qualified opportunity. A `ProgramManager` creates it by naming the `customer_id` and `program_id`, the proposed `measure_type`, the `estimated_annual_kwh_savings` of the proposed measure, and the `source_channel` through which the opportunity arrived (`WEB`, `CALL_CENTER`, `FIELD_AUDIT`, `REFERRAL`, or `UTILITY_REFERRAL`). The named program must be `ACTIVE`, or creation fails with `ERR_PROGRAM_NOT_ACTIVE`. A lead is born `NEW`, with `assigned_contractor_id` empty and `distribution_decision` null until distribution.

Distribution is the selector act that moves a lead `NEW` → `OFFERED`, and its checks fire in a fixed order. The lead must be `NEW` (otherwise `ERR_INVALID_STATE`), and the request must carry `expected_lead_version` matching the lead's current `version` (otherwise `ERR_STALE_LEAD_VERSION`, §2.7). The certification dimension is then screened: when the candidate pool fails specifically because no approved contractor carries an `ACTIVE` certification for the lead's `measure_type`, the rejection is `ERR_CERTIFICATION_MISSING`. The program must be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`). Only then does overall eligibility emptiness surface: when the full eligibility filter — contractor in `APPROVED` standing, contractor `sector` matching the program's sector, the customer's `service_zip` contained in the contractor's `service_zip_codes`, and an `ACTIVE` certification for the lead's `measure_type` — yields no candidate at all, the rejection is `ERR_NO_ELIGIBLE_CONTRACTOR`.

Among eligible candidates, the selector ranks by descending `qa_score_bps`; ties break toward the lowest `complaint_count_90d`, remaining ties toward the earliest contractor `created_at`, and any ties still unresolved — reachable when several contractors share the same logical-clock creation instant — break toward the lowest contractor `id`. The winner is written into the lead's `assigned_contractor_id`, the decision is journaled into the lead's `distribution_decision` object — recording `candidate_count`, the `ranking_key` that decided the outcome, and the `tie_break_used` — and the lead's `version` increments.

Acceptance belongs to the assigned firm: a contractor accepting an offered lead moves it `OFFERED` → `ACCEPTED`, but only when the caller is the contractor named in `assigned_contractor_id` (any other caller is refused with `ERR_NOT_RESOURCE_OWNER`) and the contractor still stands `APPROVED` (a caller no longer `APPROVED` is refused with `ERR_INVALID_STATE`). Expiry moves `OFFERED` → `EXPIRED` and clears `assigned_contractor_id`; it happens automatically when the assigned contractor is suspended, and a `ProgramManager` may also expire an offered lead manually. Withdrawal is a `ProgramManager` act from either `NEW` or `OFFERED` (→ `WITHDRAWN`); withdrawing an offered lead likewise clears `assigned_contractor_id`. `EXPIRED` and `WITHDRAWN` are terminal. Lead lists may be filtered by `status`, `program_id`, `contractor_id`, `customer_id`, and `assigned_contractor_id`.

### 3.4. Project Origination, Approval, and Budget Commitment

A project formalizes a lead into a contracted scope of work. Either a `ProgramManager` or a `Contractor` caller may create one — the lead need not be `ACCEPTED` at creation time, and a contractor caller is not required to be the contractor named on the project — supplying the `lead_id`, `customer_id`, `contractor_id`, and `program_id` it rolls up to, the `measure_type`, the total installed cost `measure_cost_cents`, the `estimated_annual_kwh_savings`, and the `incentive_recipient` — `CONTRACTOR` or `CUSTOMER` — naming who will ultimately be paid. A project is born `PROPOSED`, with `incentive_amount_cents` and `incentive_amount_provisional_cents` at zero and `approval_snapshot_contractor_qa_bps` null.

Approval is the most heavily guarded act in the platform, and its checks fire in a fixed order. First the project must be `PROPOSED` (any other state draws `ERR_INVALID_STATE`). Next the optimistic-concurrency check: the request must carry `expected_program_version` equal to the program's current `version`, or the approval is refused with `ERR_STALE_PROGRAM_VERSION` (§2.7). The certification requirement follows: the contractor must hold an `ACTIVE` certification for the project's `measure_type`, failing which the rejection is `ERR_CERTIFICATION_MISSING`; the contractor must also currently stand `APPROVED`, and the lead underpinning the project must have reached `ACCEPTED`; either failure is refused with `ERR_INVALID_STATE`. The program must be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`). Finally comes the fiscal check: the program's `committed_cents` plus this project's provisional incentive must not exceed the program's `budget_cents`, or the approval dies with `ERR_BUDGET_EXCEEDED`.

The provisional incentive is a two-tier marginal rate applied to the project's `estimated_annual_kwh_savings`: the first 2,000 kWh of annual savings earns 25 cents per kWh, and any savings above 2,000 kWh earns 12 cents per kWh; the two portions are summed, the total is clamped so it never exceeds 80,000 cents, and the provisional figure is floored to whole cents. A successful approval stores this result in the project's `incentive_amount_provisional_cents`, copies it into `incentive_amount_cents`, and freezes the contractor's current `qa_score_bps` into `approval_snapshot_contractor_qa_bps` for downstream reporting. The program's `committed_cents` grows by the incentive amount and the program's `version` increments. In the same atomic step, an incentive payment shell is created in `DRAFT`: its `payee_role` is taken from the project's `incentive_recipient`, its `payee_id` is set to the contractor's `id` when the recipient is `CONTRACTOR` and to the customer's `id` when it is `CUSTOMER`, its `amount_provisional_cents` equals the provisional incentive, and its `amount_cents` and `reconciliation_delta_cents` start at zero.

Cancellation releases commitments in proportion to how far the project progressed. From `PROPOSED` there is no financial footprint and nothing to unwind. From `APPROVED`, the draft payment is voided (`DRAFT` → `VOID`) and the program's `committed_cents` is decremented by the project's incentive amount. From `SCHEDULED`, the same payment voiding and budget release occur, and any of the project's work orders still in `SCHEDULED` or `DRAFT` cascade to `CANCELLED`. From `REMEDIATION`, the payment is voided whether it sits in `DRAFT` or `AUTHORIZED`, and the committed amount is released. Cancellation is not offered from `INSTALLED` or `INSPECTING` — such requests are refused with `ERR_INVALID_STATE`. `CANCELLED` and `COMPLETED` are the terminal states. Project lists may be filtered by `status`, `program_id`, `contractor_id`, `customer_id`, and `lead_id`.

### 3.5. Work Order Scheduling and Field Execution

With a project `APPROVED`, the performing contractor raises the project's first work order, supplying the `contractor_id`, the service date `scheduled_on` (midnight UTC of the service day), a planned `duration_hours`, and optionally `direct_install`, which defaults to `false` and marks work the implementer's own field crew performs rather than the contractor's calendar. The caller must be the contractor named on the project, and the `contractor_id` named in the request body must likewise be the caller (`ERR_NOT_RESOURCE_OWNER` otherwise). Creating this first order advances the project `APPROVED` → `SCHEDULED`. A conventional order is born directly in `SCHEDULED`; a direct-install order is born in `DRAFT`, awaiting crew assignment, and moves to `SCHEDULED` when the contractor later schedules it.

Calendar integrity is enforced for conventional orders: the platform refuses with `ERR_SCHEDULE_CONFLICT` any order whose working window — the half-open interval that begins at `scheduled_on` and runs for `duration_hours`, with the end instant itself excluded — would overlap another `SCHEDULED` or `IN_PROGRESS` work order for the same contractor on the same calendar date. Back-to-back bookings, where one window ends exactly as another begins, do not conflict. The screen runs when a conventional order is created and again when a `DRAFT` order is moved to `SCHEDULED`; direct-install orders are exempt in both places — and a direct-install order never counts as a conflicting booking against another order — because they book against the implementer's crew rather than the contractor's calendar.

Starting work moves an order `SCHEDULED` → `IN_PROGRESS`. The caller must own the order (`ERR_NOT_RESOURCE_OWNER`), and the logical clock's calendar date must equal the `scheduled_on` date — an attempt to start on any other day, earlier or later, is refused with `ERR_START_TOO_EARLY`.

Completion moves an order `IN_PROGRESS` → `COMPLETED`, and its checks fire in a fixed order: the order must be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`); the segregation-of-duties screen is applied to the inspector pool, excluding any inspector whose `excluded_contractor_ids` names this order's contractor; the caller's ownership is verified (`ERR_NOT_RESOURCE_OWNER`); and only then does inspector selection run, failing with `ERR_NO_INSPECTOR_AVAILABLE` when the screened pool is empty. A successful completion stamps `completed_on` with the current logical clock and re-sorts the contractor's track record: the order counts toward `on_time_installs` when `completed_on` falls at or before `scheduled_on`, and toward `late_installs` when it falls later. The project auto-advances `SCHEDULED` → `INSTALLED`, and the platform chooses the inspector — filtering to `ACTIVE` inspectors not excluded for this contractor, ranking candidates by earliest inspector `created_at` (ties break toward the lowest inspector `id`), and writing the winner into the order's `assigned_inspector_id`.

Cancellation belongs to the owning contractor and is permitted from `DRAFT` or `SCHEDULED` (→ `CANCELLED`). Work-order lists may be filtered by `project_id`, `contractor_id`, and `status`.

### 3.6. Quality Inspection, Scoring, and Remediation

Inspectors are registered by a `ProgramManager`, who records a `full_name`, a `license_number`, and an optional `excluded_contractor_ids` list — defaulting to empty — that encodes segregation-of-duties conflicts. An inspector begins `ACTIVE`. Inspector lists may be filtered by `status`.

Scheduling an inspection is performed by the assigned inspector, who names the `work_order_id`, the `project_id`, their own `inspector_id`, and the `scheduled_on` date, and its checks fire in a fixed order: the named `inspector_id` must be the caller (otherwise `ERR_NOT_RESOURCE_OWNER`); the project must be `INSTALLED` or `REMEDIATION` (otherwise `ERR_INVALID_STATE`); segregation of duties is enforced — an inspector whose `excluded_contractor_ids` contains the work order's contractor is refused with `ERR_INSPECTOR_CONFLICT`; the project must have at least one work order in `COMPLETED` (otherwise `ERR_INVALID_STATE`); and the acting inspector must match the `assigned_inspector_id` the platform wrote onto the project's most recently completed work order at completion time (otherwise `ERR_NOT_RESOURCE_OWNER`). The new inspection is born `SCHEDULED` with its `outcome` `PENDING`, its `score_bps` and `remediation_required_by` null, and its `failure_reasons` defaulting to empty, and the project moves `INSTALLED` → `INSPECTING`. When a project sits in `REMEDIATION`, the same scheduling act books the re-inspection and returns the project `REMEDIATION` → `INSPECTING` — but only on or before the `remediation_required_by` deadline recorded on the most recent failed inspection; a re-inspection requested after that deadline is refused with `ERR_REMEDIATION_WINDOW_EXPIRED`.

Recording an outcome is the pivotal judgment, and the request is screened in a fixed order before its payload is even examined: the inspection must be `SCHEDULED` (otherwise `ERR_INVALID_STATE`), the segregation rule is re-checked against the work order's contractor — screening the calling inspector's own `excluded_contractor_ids`, so a caller whose exclusion list names that contractor is refused even when it is not the inspection's assigned inspector — (`ERR_INSPECTOR_CONFLICT`), and the caller must be the inspection's own `inspector_id` (otherwise `ERR_NOT_RESOURCE_OWNER`). A valid recording payload carries an `outcome` of `PASS` or `FAIL`, a `score_bps` between 0 and 10,000 inclusive, and a `failure_reasons` list that must be non-empty exactly when the outcome is `FAIL` — missing or empty on a failure, or a non-empty list supplied on a pass, is malformed, as is any out-of-range score, and all such payloads draw `ERR_INVALID_INSPECTION_PAYLOAD` (HTTP 400). A successful recording moves the inspection `SCHEDULED` → `RECORDED` with the supplied outcome and score, and recomputes the contractor's `qa_score_bps` as the arithmetic mean of `score_bps` across the contractor's ten most recent `RECORDED` inspections (most recent by recording timestamp) — passing and failing inspections contribute alike, and when fewer than ten recorded inspections exist the mean is taken over all of them — rounded half up to integer basis points.

On a `PASS`, the project moves `INSPECTING` → `COMPLETED` and the money moves with it: the final incentive is computed (§3.7), the payment — when it still sits in `DRAFT` — advances `DRAFT` → `AUTHORIZED` (a payment already voided is left untouched), and the program's `avoided_kwh_actual` grows by the project's `estimated_annual_kwh_savings`. On a `FAIL`, the project moves `INSPECTING` → `REMEDIATION`, the inspection's `remediation_required_by` is set to the current logical clock plus the remediation window — a fixed 30 days — and the recomputed quality score already includes this failing grade. Should that recomputed `qa_score_bps` fall below 5,000 basis points, the contractor is automatically suspended, with the usual suspension consequences: removal from lead distribution and automatic expiry of the firm's outstanding `OFFERED` leads.

A `ProgramManager` may also void a `SCHEDULED` inspection (`SCHEDULED` → `VOID`), an act that deliberately leaves the project's state untouched. Inspection lists may be filtered by `project_id`, `work_order_id`, `inspector_id`, `outcome`, and `status`.

### 3.7. Incentive Settlement: Final Amounts, Disbursement, and Reconciliation

The final incentive, computed when a passing inspection completes the project, differs from the provisional in two ways. First, a cost-overrun adjustment: when the project's `measure_cost_cents` exceeds the measure-cost baseline of 500,000 cents, the eligible savings are scaled down by the ratio of that baseline to the actual installed cost — a factor strictly below one that shrinks the eligible savings in proportion to the overrun — while an installed cost at or below the baseline leaves the savings figure untouched. Second, the rounding: the final figure rounds half up to whole cents where the provisional floored. The same two-tier rate structure applies — 25 cents per kWh for the first 2,000 kWh of (adjusted) annual savings and 12 cents per kWh beyond — and the same 80,000-cent cap clamps the total. The computed final amount is written to the payment's `amount_cents` and replaces the provisional figure in the project's `incentive_amount_cents`, and the difference between final and provisional is journaled on the payment as `reconciliation_delta_cents` — positive when a top-up is owed, negative when money must come back.

Disbursement by a `ProgramManager` moves a payment `AUTHORIZED` → `PAID` and adds the provisional amount, `amount_provisional_cents`, to the program's `paid_cents` — the provisional is paid up front, with the delta settled afterward. Reconciliation moves a payment `PAID` → `RECONCILED` and exists only when there is something to settle: a reconcile requested on a payment whose `reconciliation_delta_cents` is zero is refused with `ERR_NOTHING_TO_RECONCILE`. A positive delta is added to the program's `paid_cents` as a top-up payment bringing the total to the final amount; a negative delta is subtracted in absolute terms as a clawback, again bringing the total to the final amount. Either way, a reconciled payment has contributed exactly its final `amount_cents` to the program, and `RECONCILED` is terminal.

Voiding is available to a `ProgramManager` while a payment sits in `DRAFT` or `AUTHORIZED` (→ `VOID`), and project cancellation voids the payment automatically as described in §3.4. A payment already `PAID` cannot be voided, and `VOID` is terminal. Payment lists may be filtered by `project_id`, `payee_role`, `payee_id`, and `status`.

### 3.8. Customer Complaints and Escalation Discipline

Complaints are filed by the customer or by a `ProgramManager` — a `Customer` caller files only for themself, the body's `customer_id` naming the caller (otherwise `ERR_NOT_RESOURCE_OWNER`), while a `ProgramManager` may file for any customer — and each carries a `customer_id`, the accused `contractor_id`, an optional `project_id` (omitted for general-service complaints that concern no particular job), a `category` (`WORKMANSHIP`, `SCHEDULING`, `BILLING`, `CONDUCT`, or `OTHER`), a `severity` (`LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`), and a free-text `description`. A complaint is born `OPEN`, and its creation refreshes the accused contractor's `complaint_count_90d`.

That counter is a rolling window, not a lifetime tally: it counts the contractor's complaints in `OPEN`, `IN_REVIEW`, or `ESCALATED` whose `created_at` falls at or after the instant 90 days before the current logical clock. Resolving a complaint drops it out of the count immediately, and complaints age out of the window as the clock advances. The count is recomputed on every complaint creation, resolution, and escalation, and on every read of an individual contractor record (list reads do not refresh it).

The workflow is a short one. A `ProgramManager` starts review, moving a complaint `OPEN` → `IN_REVIEW`. Resolution is terminal and is reachable from review (`IN_REVIEW` → `RESOLVED`) or after escalation (`ESCALATED` → `RESOLVED`). Escalation is reserved for serious matters: moving a complaint `OPEN` → `ESCALATED` or `IN_REVIEW` → `ESCALATED` requires a `severity` of `HIGH` or `CRITICAL`, and an escalation attempted on a lower-severity complaint is refused with `ERR_SEVERITY_TOO_LOW`. When a contractor holds three or more complaints currently in `ESCALATED` — counted without any time window — the contractor is automatically suspended, with the standard suspension consequences of §3.2. Complaint lists may be filtered by `customer_id`, `contractor_id`, `project_id`, `status`, and `severity`.

### 3.9. Cost-Effectiveness Reporting

Regulators judge a program by the Total Resource Cost test, and the platform produces that judgment as a report. A `ProgramManager` generates one by naming the `program_id`, a reporting window running from `period_start` (inclusive) to `period_end` (exclusive), and the administrative overhead `total_admin_cost_cents` allocated to the program for the period. The report is born `DRAFT` with its figures computed immediately; the same computation runs again at finalization, after which finalizing moves the report `DRAFT` → `FINAL` and locks its computed fields. `FINAL` is terminal.

The input set for the computation is precise: projects of the named program in state `COMPLETED` whose last-modified timestamp falls within the reporting window — on or after `period_start` and before `period_end` — together with those projects' payments in `PAID` or `RECONCILED`. From this population, `total_avoided_kwh` sums the projects' `estimated_annual_kwh_savings`, and `total_incentive_paid_cents` sums the payments' `amount_cents`.

The benefit side of the ratio prices the avoided energy at 11 cents per kWh and discounts it over a twelve-year measure life at a 4 percent annual rate with end-of-year discounting: for each year from the first through the twelfth, that year's avoided-cost value — the report's `total_avoided_kwh` multiplied by 11 cents — is divided by 1.04 raised to the power of the year number, and the twelve discounted terms are summed, with intermediate benefit figures kept at four decimal places. The denominator adds three terms: `total_incentive_paid_cents`, `total_admin_cost_cents`, and the aggregate customer incremental cost, where each completed project in the window contributes the positive part of its `measure_cost_cents` minus its incentive amount — zero whenever the incentive covers the full installed cost. The `trc_ratio` is the discounted benefit divided by this denominator, which must be greater than zero — a report whose denominator is not positive is refused with `ERR_INVALID_STATE` (HTTP 409) — and is rounded half up to four decimal places.

The `trc_flag` then compares the ratio to the program's `trc_threshold`: `PASS` when the ratio meets or exceeds the threshold; `MARGINAL` when the ratio falls below the threshold by no more than 0.10 — a ratio exactly 0.10 under the threshold still earns `MARGINAL`; and `FAIL` when the ratio falls more than 0.10 below the threshold. Report lists may be filtered by `program_id` and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource — including all state-transition actions — return `200 OK`. The table below is a navigational summary only: request payloads, response shapes, side effects, and the business preconditions of each operation are defined by the narratives of §2 and §3, which the reader must consult to reconstruct the complete contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/efficiency/_clock/set_current_utc` | Advance the logical clock; sweeps expired certifications | ProgramManager |
| POST | `/efficiency/programs` | Create a program in `DRAFT` | ProgramManager |
| GET | `/efficiency/programs` | List programs with pagination | ProgramManager, Contractor, Inspector, Customer |
| GET | `/efficiency/programs/{program_id}` | Get one program | ProgramManager, Contractor, Inspector, Customer |
| POST | `/efficiency/programs/{program_id}/activate` | Activate or reinstate a program | ProgramManager |
| POST | `/efficiency/programs/{program_id}/suspend` | Suspend a program | ProgramManager |
| POST | `/efficiency/programs/{program_id}/close` | Close a program with no open projects | ProgramManager |
| POST | `/efficiency/contractors` | Register a contractor in `APPLIED` | ProgramManager |
| GET | `/efficiency/contractors` | List contractors | ProgramManager, Inspector |
| GET | `/efficiency/contractors/{contractor_id}` | Get one contractor (refreshes `complaint_count_90d`) | ProgramManager, Contractor, Inspector |
| POST | `/efficiency/contractors/{contractor_id}/approve` | Approve a contractor holding an `ACTIVE` certification | ProgramManager |
| POST | `/efficiency/contractors/{contractor_id}/suspend` | Suspend a contractor; expires its `OFFERED` leads | ProgramManager |
| POST | `/efficiency/contractors/{contractor_id}/reinstate` | Reinstate a suspended contractor | ProgramManager |
| POST | `/efficiency/contractors/{contractor_id}/terminate` | Terminate a contractor with no in-flight work orders | ProgramManager |
| POST | `/efficiency/certifications` | Issue a certification to a contractor | ProgramManager |
| GET | `/efficiency/certifications` | List certifications | ProgramManager, Contractor, Inspector |
| GET | `/efficiency/certifications/{certification_id}` | Get one certification | ProgramManager, Contractor, Inspector |
| POST | `/efficiency/certifications/{certification_id}/revoke` | Revoke a certification; may cascade suspension | ProgramManager |
| POST | `/efficiency/customers` | Register a customer | ProgramManager |
| GET | `/efficiency/customers` | List customers | ProgramManager, Contractor |
| GET | `/efficiency/customers/{customer_id}` | Get one customer | ProgramManager, Contractor, Customer |
| POST | `/efficiency/leads` | Create a lead for a customer and program | ProgramManager |
| GET | `/efficiency/leads` | List leads | ProgramManager, Contractor |
| GET | `/efficiency/leads/{lead_id}` | Get one lead | ProgramManager, Contractor |
| POST | `/efficiency/leads/{lead_id}/distribute` | Run the selector and assign the lead (OCC-guarded) | ProgramManager |
| POST | `/efficiency/leads/{lead_id}/accept` | Assigned contractor accepts the offered lead | Contractor |
| POST | `/efficiency/leads/{lead_id}/expire` | Manually expire an `OFFERED` lead | ProgramManager |
| POST | `/efficiency/leads/{lead_id}/withdraw` | Withdraw a lead | ProgramManager |
| POST | `/efficiency/projects` | Create a project in `PROPOSED` | ProgramManager, Contractor |
| GET | `/efficiency/projects` | List projects | ProgramManager, Contractor, Customer |
| GET | `/efficiency/projects/{project_id}` | Get one project | ProgramManager, Contractor, Customer, Inspector |
| POST | `/efficiency/projects/{project_id}/approve` | Approve a project; computes the provisional incentive (OCC-guarded) | ProgramManager |
| POST | `/efficiency/projects/{project_id}/cancel` | Cancel a project; cascades and releases budget | ProgramManager |
| POST | `/efficiency/projects/{project_id}/work_orders` | Create a work order for an `APPROVED` project | Contractor |
| GET | `/efficiency/work_orders` | List work orders | ProgramManager, Contractor, Inspector |
| GET | `/efficiency/work_orders/{work_order_id}` | Get one work order | ProgramManager, Contractor, Inspector |
| POST | `/efficiency/work_orders/{work_order_id}/schedule` | Move a `DRAFT` work order to `SCHEDULED` | Contractor |
| POST | `/efficiency/work_orders/{work_order_id}/start` | Start work on the scheduled date | Contractor |
| POST | `/efficiency/work_orders/{work_order_id}/complete` | Complete a work order; advances the project and assigns an inspector | Contractor |
| POST | `/efficiency/work_orders/{work_order_id}/cancel` | Cancel a work order | Contractor |
| POST | `/efficiency/inspectors` | Register an inspector | ProgramManager |
| GET | `/efficiency/inspectors` | List inspectors | ProgramManager, Inspector |
| GET | `/efficiency/inspectors/{inspector_id}` | Get one inspector | ProgramManager, Inspector |
| POST | `/efficiency/inspections` | Schedule an inspection or re-inspection for a project | Inspector |
| GET | `/efficiency/inspections` | List inspections | ProgramManager, Contractor, Inspector |
| GET | `/efficiency/inspections/{inspection_id}` | Get one inspection | ProgramManager, Contractor, Inspector |
| POST | `/efficiency/inspections/{inspection_id}/record` | Record an inspection outcome (`PASS` or `FAIL`) | Inspector |
| POST | `/efficiency/inspections/{inspection_id}/void` | Void a scheduled inspection without project impact | ProgramManager |
| GET | `/efficiency/incentive_payments` | List incentive payments | ProgramManager, Contractor, Customer |
| GET | `/efficiency/incentive_payments/{payment_id}` | Get one incentive payment | ProgramManager, Contractor, Customer |
| POST | `/efficiency/incentive_payments/{payment_id}/disburse` | Disburse an `AUTHORIZED` payment | ProgramManager |
| POST | `/efficiency/incentive_payments/{payment_id}/reconcile` | Reconcile a `PAID` payment against its delta | ProgramManager |
| POST | `/efficiency/incentive_payments/{payment_id}/void` | Void a `DRAFT` or `AUTHORIZED` payment | ProgramManager |
| POST | `/efficiency/complaints` | File a complaint | Customer, ProgramManager |
| GET | `/efficiency/complaints` | List complaints | ProgramManager, Contractor, Customer |
| GET | `/efficiency/complaints/{complaint_id}` | Get one complaint | ProgramManager, Contractor, Customer |
| POST | `/efficiency/complaints/{complaint_id}/start_review` | Start review of an `OPEN` complaint | ProgramManager |
| POST | `/efficiency/complaints/{complaint_id}/resolve` | Resolve a complaint | ProgramManager |
| POST | `/efficiency/complaints/{complaint_id}/escalate` | Escalate a `HIGH`/`CRITICAL` complaint | ProgramManager |
| POST | `/efficiency/reports` | Generate a cost-effectiveness report for a program and period | ProgramManager |
| GET | `/efficiency/reports` | List reports | ProgramManager |
| GET | `/efficiency/reports/{report_id}` | Get one report | ProgramManager |
| POST | `/efficiency/reports/{report_id}/finalize` | Finalize a `DRAFT` report, locking its computed fields | ProgramManager |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier the API can return. Trigger conditions are defined where each rule lives in §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LEAD_VERSION` | 412 Precondition Failed |
| `ERR_INSPECTOR_CONFLICT` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_MISSING` | 422 Unprocessable Entity |
| `ERR_PROGRAM_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SCHEDULE_CONFLICT` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_CONTRACTOR` | 422 Unprocessable Entity |
| `ERR_NO_INSPECTOR_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_START_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_REMEDIATION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SEVERITY_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NOTHING_TO_RECONCILE` | 422 Unprocessable Entity |
| `ERR_INVALID_INSPECTION_PAYLOAD` | 400 Bad Request |
| `ERR_PROGRAM_HAS_OPEN_PROJECTS` | 422 Unprocessable Entity |
| `ERR_CONTRACTOR_BUSY` | 422 Unprocessable Entity |
