# Multifamily Preventive Maintenance Program API — Product Requirements Document

## 1. Introduction

Operators of multifamily housing portfolios live and die by their preventive maintenance (PM) program. Every HVAC unit, water heater, and in-unit appliance carries an installation date, a manufacturer warranty, and an expected service life; every insurer and housing regulator expects documented proof that filters were swapped, detectors tested, and batteries replaced on schedule; and every occupied apartment is protected by resident-notice rules that constrain when maintenance staff may lawfully enter. When a technician does find something wrong — a corroded flue, a failing compressor — the finding must travel a disciplined path from deficiency record to funded corrective work order, with an independent auditor confirming that the work was actually performed and that no one certified their own labor.

This document specifies an API that runs that entire program. It maintains the per-property asset register with age and warranty tracking, a library of recurring PM task templates, batched unit-entry scheduling with enforced resident-notice lead times, evidence capture for compliance-sensitive consumables, conversion of deficiencies into corrective work orders with commit-and-settle budget accounting on an append-only ledger, completion audits under strict segregation of duties, and capital replacement forecasting driven by the very condition data the program collects. All temporal rules — notice windows, due dates, forecast horizons — are evaluated against a server-maintained logical clock rather than wall-clock time, so behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply to every endpoint. All business resources are served under the `/pm` prefix; a separate test-driving capability governs the logical clock.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly three roles, spelled precisely as follows: `PropertyManager`, `Technician`, and `ComplianceAuditor`. Each write endpoint admits a specific set of roles (see §4); an authenticated caller whose role is not admitted is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). All read endpoints are shared: any of the three roles may issue any GET operation in this document.

Identity is opaque for all three roles, and each role is named individually here. When `X-User-Role` is `PropertyManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any resource's `id`. When `X-User-Role` is `Technician`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; however, technician-scoped execution actions additionally compare `X-User-ID` against the assigned-technician field recorded on the target resource — `technician_id` on a visit, `assigned_technician_id` on a work order — and a mismatch is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. When `X-User-Role` is `ComplianceAuditor`, `X-User-ID` is again opaque and never compared to any entity's `id`; the server records it (for example, as `auditor_id` on an audit or `recorded_by` on an evidence row) purely as an audit trail.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

Every temporal rule in this document — resident-notice lead times, batch windows, due-date arithmetic, forecast horizons — is evaluated against a server-maintained **logical clock**, never against wall-clock time. Before any client has set it, the logical clock reads exactly `2026-08-01T00:00:00Z`; the server must not silently fall back to wall-clock time at any point.

A `PropertyManager` advances the logical clock through a test-driving capability that accepts a target instant `to_iso8601` and responds with the new reading as `current_utc`. Each clock move is a system event in its own right: the `compliance_status` of every asset in every property is recomputed against the new reading, so due-soon and overdue transitions fire as time advances.

Scheduling datetimes (`window_start`, `window_end`, `scheduled_start`) are ISO 8601 UTC values at minute precision. System-generated timestamps (`created_at`, `updated_at`, `notice_sent_at`, `audited_at`, `computed_at`) are ISO 8601 UTC with three fractional digits.

### 2.5. Common Resource Properties

Primary resources — Property, Building, Unit, Asset, PMTaskTemplate, PMPlan, EntryBatch, PMVisit, Deficiency, and CorrectiveWorkOrder — carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at its initial value on creation and increments by one on every mutation, including mutations caused by system cascades.

Four record types are append-only and carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from them: ComplianceEvidence, BudgetLedgerEntry, CapitalForecastSnapshot, and CompletionAudit.

Mutations frequently cascade. Adding a visit to a batch increments the batch's `version` by one, because the visit roster is part of the batch's mutable state. Triaging a deficiency, or attaching a work order to it, increments the deficiency's `version` by one. Publishing a batch increments the batch's `version` by one. Any such mutation also refreshes the owning resource's `updated_at`.

### 2.6. Request Validation Pipeline and Nested Resource Retrieval

Every request passes through a single ordered validation pipeline. Stages are evaluated in the priority order below, and a failure at an earlier stage masks every later stage — the client always receives the error from the first failing stage.

1. **Authentication context.** `X-User-ID` and `X-User-Role` must be present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400).
2. **Authorization.** The role must be admitted for the endpoint per §4; for the technician-scoped execution actions (visit start, complete, and no-access; work-order submit-review, start, and complete), `X-User-ID` must additionally equal the assigned technician on the target resource (`ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403).
3. **Existence.** Every identifier in the path, validated left to right, and then every resource referenced in the request body, in declared input order, must exist. The 404 family maps one code per identifier: `property_id` → `ERR_PROPERTY_NOT_FOUND`, `building_id` → `ERR_BUILDING_NOT_FOUND`, `unit_id` → `ERR_UNIT_NOT_FOUND`, `asset_id` → `ERR_ASSET_NOT_FOUND`, `template_id` → `ERR_TEMPLATE_NOT_FOUND`, `plan_id` → `ERR_PLAN_NOT_FOUND`, `batch_id` → `ERR_BATCH_NOT_FOUND`, `visit_id` → `ERR_VISIT_NOT_FOUND`, `deficiency_id` → `ERR_DEFICIENCY_NOT_FOUND`, and `wo_id` → `ERR_WORK_ORDER_NOT_FOUND`. A `template_id` that is retired in a context requiring a current template also raises `ERR_TEMPLATE_NOT_FOUND`.
4. **Property active.** The owning property must be `ACTIVE`; any mutation of an `ARCHIVED` property or of anything beneath it is rejected (`ERR_PROPERTY_ARCHIVED`, HTTP 409).
5. **State legality.** The target resource must be in a state from which the requested transition is declared (`ERR_INVALID_STATE`, HTTP 409).
6. **Optimistic concurrency.** On the two guarded writes, the expected-version field must equal the parent entity's current `version` (`ERR_STALE_VERSION`, HTTP 412 — see §2.9).
7. **Visit timing.** The too-early check is evaluated before the notice-lead check (`ERR_VISIT_TOO_EARLY`, then `ERR_NOTICE_LEAD_VIOLATION`, both HTTP 409).
8. **Window and batch mutability.** Batch windows must still be in the future at publish, visit start times must sit inside their batch window, and the relevant batch must still be mutable (`ERR_WINDOW_IN_PAST`, `ERR_VISIT_OUTSIDE_WINDOW`, `ERR_BATCH_NOT_MUTABLE`, all HTTP 409).
9. **Unit entry overlap.** A unit may not host two overlapping visits (`ERR_UNIT_ENTRY_OVERLAP`, HTTP 409).
10. **Referential coherence.** Component types must match, all references must live in one property, and a deficiency must name the visit's own asset (`ERR_COMPONENT_MISMATCH`, `ERR_CROSS_PROPERTY_REFERENCE`, `ERR_DEFICIENCY_ASSET_MISMATCH`, all HTTP 422).
11. **Evidence requirement.** An evidence-requiring task cannot complete without evidence (`ERR_EVIDENCE_REQUIRED`, HTTP 422).
12. **Segregation of duties and emergency handling.** Auditors may never certify their own work, and emergency deficiencies may not be waived (`ERR_SEGREGATION_OF_DUTIES`, `ERR_EMERGENCY_NOT_WAIVABLE`, both HTTP 422).
13. **Fiscal gate.** Plan adoption is checked before budget headroom (`ERR_PLAN_NOT_ADOPTED`, then `ERR_BUDGET_EXCEEDED`, both HTTP 402).
14. **Lifecycle constraints.** Plans with open work cannot close, a second adopted plan for the same property and year is forbidden, and assets with open work cannot be decommissioned (`ERR_PLAN_HAS_OPEN_WORK`, `ERR_DUPLICATE_ACTIVE_PLAN`, `ERR_ASSET_HAS_OPEN_WORK`, all HTTP 409).
15. **Field shape.** Required fields present, enum values within their declared sets, integers positive or non-negative where constrained, `window_end` strictly after `window_start`, forecast horizon within range, and `property_code` unique (`ERR_INVALID_REQUEST`, HTTP 400). Field-shape checks run last, after every business rule above.

Nested retrieval follows the same discipline: for a path such as one addressing evidence beneath a visit, the system validates identifiers strictly left to right, so a request addressing evidence under a non-existent visit fails with `ERR_VISIT_NOT_FOUND` before any evidence consideration, and a plan's ledger under a non-existent plan fails with `ERR_PLAN_NOT_FOUND` before any ledger consideration.

### 2.7. Money, Labor, and Rounding Conventions

All monetary values are integers denominated in cents: property labor rates (`default_labor_rate_cents_per_hour`), plan budgets (`budget_cents`), visit costs (`visit_cost_cents`), work-order estimates (`estimated_cost_cents`) and actuals (`actual_cost_cents`), ledger amounts (`amount_cents`), and forecast outputs. Labor itself is measured in minutes — estimates as `estimated_labor_minutes` on a template, actuals as `actual_minutes` on a completed visit — with plan-level roll-ups expressed as described in §3.2.

Two rounding rules govern every monetary figure. First, each individual monetary event is rounded **half-up to a whole cent at the moment it is computed**; second, totals are always sums of those already-rounded events — the system never sums unrounded values and rounds the total. The cost of a completed visit is the technician's recorded `actual_minutes` multiplied by the property's `default_labor_rate_cents_per_hour`, divided by 60, rounded half-up to a whole cent; the same formula with `estimated_labor_minutes` in place of `actual_minutes` produces the estimated cost committed at publish time. Plan-level planned labor is rounded **up** to whole hours (§3.2), and the portfolio compliance percentage is rounded half-up to two decimal places (§3.7).

### 2.8. The Plan Budget Ledger

Every PMPlan carries four computed aggregates — `planned_labor_hours`, `actual_labor_minutes`, `committed_cents`, and `spent_cents` — and every monetary movement against a plan is recorded as an immutable **BudgetLedgerEntry**. A ledger entry bears an `entry_kind` drawn from exactly six values — `VISIT_COMMIT`, `VISIT_SETTLE`, `VISIT_RELEASE`, `WO_COMMIT`, `WO_SETTLE`, `WO_RELEASE` — a signed `amount_cents` (positive amounts commit or settle money against the plan; negative amounts release it), a `source_visit_id` set when the kind begins with `VISIT_` and null otherwise, a `source_work_order_id` set when the kind begins with `WO_` and null otherwise, and a system-generated `memo` describing the event.

The ledger rows of each lifecycle are fixed. For a visit: batch publish writes a `VISIT_COMMIT` for the positive estimated cost; cancellation or no-access writes a `VISIT_RELEASE` for exactly the negative of that estimate, so the pair cancels to zero; completion writes a `VISIT_RELEASE` for the negative of the estimate followed by a `VISIT_SETTLE` for the positive actual cost. For a work order: approval writes a `WO_COMMIT` for the positive `estimated_cost_cents`; completion writes a `WO_RELEASE` for the negative of that estimate followed by a `WO_SETTLE` for the positive `actual_cost_cents`; a failed verification writes a `WO_RELEASE` for the negative of the actual cost — a clawback of settled spend.

The plan's derived balances follow directly. `committed_cents` is the sum of `amount_cents` over all `VISIT_COMMIT` and `WO_COMMIT` rows together with the negative release rows that release a commit — every `VISIT_RELEASE`, and those `WO_RELEASE` rows whose `memo` marks them as a release-of-commit; settle rows never touch `committed_cents`. `spent_cents` is the sum of `amount_cents` over all `VISIT_SETTLE` and `WO_SETTLE` rows plus the negative fail-verification `WO_RELEASE` rows, whose `memo` marks them as a release-of-settle. The release-of-commit versus release-of-settle distinction recorded in `memo` is what keeps the two balances correct when the same `WO_RELEASE` kind is used for both purposes.

Two conserved invariants hold at all times. Per visit, the committed contribution returns to exactly zero after cancellation, no-access, or completion, and `spent_cents` gains exactly the actual cost on completion. Per work order, `spent_cents` gains exactly `actual_cost_cents` on completion and loses exactly that amount on a failed verification — a complete-then-fail round trip leaves net recognized spend unchanged.

Ledger history is retrievable from three directions: the entries of a plan (optionally filtered by `entry_kind`), the entries sourced from a single visit, and the entries sourced from a single work order.

### 2.9. Optimistic Concurrency Control

Exactly two writes are guarded by optimistic concurrency. Creating a corrective work order requires the request to carry `expected_deficiency_version` holding the client-last-observed `version` of the deficiency being converted; if another writer has advanced the deficiency's `version` since then — for example by converting the same deficiency first, which legitimately supersedes the stale intent because a deficiency converts to at most one work order — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Publishing an entry batch requires the request to carry `expected_batch_version` holding the client-last-observed `version` of the batch; because every visit creation bumps the batch's `version`, a publisher working from a roster read before another manager added a visit is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), and must re-read the batch before re-attempting. No endpoint other than these two accepts any version field.

### 2.10. Hierarchical Consistency, Cascades, and Property Archival

A property is the root of everything beneath it: buildings, units, assets, task templates, plans, batches, and the work orders denormalized to it. While a property is `ACTIVE`, all mutations proceed subject to the pipeline of §2.6; once a `PropertyManager` archives it, its `status` becomes `ARCHIVED` and every mutation of the property or of any descendant is rejected with `ERR_PROPERTY_ARCHIVED` (HTTP 409) — a check performed before any state or business rule, immediately after existence. Reads of an archived property and its descendants remain available to all roles.

The server keeps the hierarchy aligned without waiting for explicit client calls on every affected resource. When the last open visit of a batch reaches a terminal state, the batch transitions itself to `EXECUTED`. When a visit completes, the serviced asset's `condition_score` and `compliance_status` are updated in the same act, and the plan's aggregates recompute. When a corrective work order starts, completes, or fails verification, the serviced asset's `operational_status` and the originating deficiency's `status` move with it. Each such cascade is a real mutation of the affected resource: `updated_at` refreshes and `version` increments wherever the resource carries those fields.

## 3. Business Logic & Workflows

### 3.1. Building the Portfolio: Properties, Buildings, Units, and the Asset Register

Everything begins with a **Property**. A `PropertyManager` registers one with a `property_code` (a human-readable code such as "MAPLE-01", unique across all properties and immutable after creation), a `display_name`, a `notice_lead_hours` stating the minimum hours of resident notice required before any unit entry (at least 24), and a `default_labor_rate_cents_per_hour` — the blended labor rate, in cents per hour and greater than zero, from which every visit cost at the property is computed. New properties are `ACTIVE`.

Within a property, a `PropertyManager` registers buildings by supplying the owning `property_id`, a `building_label` such as "A" or "Tower 2", and a `floors` count of at least one. Within a building, units are registered with the owning `building_id`, a `unit_number` unique within that building, and an `occupancy_status` of `OCCUPIED` or `VACANT`. Occupancy is not cosmetic: a `VACANT` unit skips resident-notice lead-time enforcement at entry and is granted a shorter due-soon window in the compliance mapping of §3.7. Buildings of a property and units of a building are listed through their parent-scoped collections.

The **asset register** is the heart of the program. Registering an asset names the `unit_id` it is installed in, a `component_type` of `HVAC`, `WATER_HEATER`, or `APPLIANCE`, the `installed_on` date, a `warranty_months` length of zero or more, an `expected_life_months` that is positive and at least `warranty_months`, and a `replacement_cost_cents` estimate greater than zero. A newly registered asset enters `IN_SERVICE`, and its `compliance_status` is initialized by the same next-due computation that governs it thereafter — `COMPLIANT` whenever no template exists for its component type or no overdue window has yet opened. Its `condition_score` stays null until the first completed PM visit records one; once set, it is always an integer between 1 and 5 inclusive, where 5 means like new. The asset list accepts the optional filters `unit_id`, `property_id`, `superseded_by_asset_id`, `component_type`, `compliance_status`, and `operational_status`.

Two computed fields are derived on read against the logical clock. `age_months` is the number of whole calendar months elapsed between `installed_on` and the clock's current date: a whole month counts only once the clock date's day-of-month has reached the day-of-month of `installed_on`; before that day in the current month, one fewer month is counted. `warranty_active` is true only while `age_months` is strictly less than `warranty_months` — the asset is covered through the end of the last covered month and ceases to be covered from the first day of the month numbered `warranty_months`.

A `PropertyManager` may move an asset between `IN_SERVICE` and `OUT_OF_SERVICE` at will by supplying `target_status`; `DECOMMISSIONED` is never reachable through that action — it is reached only by explicit decommissioning or by completion of a replacement work order. Decommissioning is terminal and guarded: if any corrective work order in `OPEN`, `IN_REVIEW`, `APPROVED`, or `IN_PROGRESS` references the asset, the request is rejected with `ERR_ASSET_HAS_OPEN_WORK`. A decommissioned asset is excluded from all future PM scheduling and from the input set of every capital forecast. When a replacement does occur, the retired asset's `superseded_by_asset_id` points at its successor — a self-referential link on the register that remains null for assets never replaced.

### 3.2. The Task Library and the Annual Plan

Each property maintains its own **PM task library**. A `PropertyManager` creates a template with the owning `property_id`, the `component_type` the task applies to, a human-readable `task_name` such as "Replace HVAC filter", a `frequency_days` interval of at least one day between required completions, an `estimated_labor_minutes` standard duration greater than zero, a `requires_evidence` flag, and an `effective_from` date recording when this template version applies. While current, a template's `retired_at` is null. Retiring a template is a soft delete: `retired_at` is stamped with the current logical clock, the template disappears from the default library listing (the listing accepts an optional `component_type` filter, and retired rows surface only when `include_retired` is true), history keeps its references intact, and using a retired template where a current one is required fails with `ERR_TEMPLATE_NOT_FOUND`. When `requires_evidence` is true, any visit completing that task must carry at least one compliance-evidence row — the enforcement lives at visit-completion time in §3.4.

Funding runs through annual **PM plans**. Creating one names the `property_id`, the `plan_year` it covers, and a `budget_cents` total greater than zero; a new plan is `DRAFT` with `planned_labor_hours`, `actual_labor_minutes`, `committed_cents`, and `spent_cents` all zero. A `PropertyManager` adopts a `DRAFT` plan to fund work — adopting a plan that is no longer in `DRAFT` fails with `ERR_INVALID_STATE` — and at most one plan per property and year may be `ADOPTED` at a time: adopting while another plan for the same property and year is already `ADOPTED` is rejected with `ERR_DUPLICATE_ACTIVE_PLAN`. Plans of a property are listed with optional `status` and `plan_year` filters.

Closing a plan is terminal and allowed only when nothing is in flight: no work order under the plan in `OPEN`, `IN_REVIEW`, `APPROVED`, or `IN_PROGRESS`; no visit under the plan in `SCHEDULED`, `NOTIFIED`, or `IN_PROGRESS`; and `committed_cents` exactly zero. Any violation is rejected with `ERR_PLAN_HAS_OPEN_WORK`. A closed plan moves to `CLOSED`.

The plan's two labor aggregates deliberately measure different things. `planned_labor_hours` is the forward-looking figure: the `estimated_labor_minutes` of every visit under the plan in `SCHEDULED`, `NOTIFIED`, `IN_PROGRESS`, or `COMPLETED` are summed, divided by 60, and rounded **up** to a whole number of hours. `actual_labor_minutes` is the backward-looking figure: the raw sum of technician-recorded `actual_minutes` across `COMPLETED` visits only, and zero when none have completed. Planned labor therefore includes open visits and rounds up to hours; actual labor counts only finished work in exact minutes.

### 3.3. Scheduling Unit Entries: Batches and Visits

Unit entries are organized into **entry batches**. A `PropertyManager` creates a batch with the owning `property_id`, a `batch_label` such as "June HVAC sweep", and a half-open entry window from `window_start` (inclusive) to `window_end` (exclusive, and strictly after `window_start`). A new batch is `DRAFT` with `notice_sent_at` still null. Batches of a property are listed with an optional `status` filter.

Visits are added one at a time to a `DRAFT` batch, each creation naming `batch_id`, `unit_id`, `template_id`, `asset_id`, `plan_id`, `scheduled_start`, and the `technician_id` of the technician who will perform the entry. The new visit is `SCHEDULED`, and the batch's `version` increments by one because its roster changed. Three referential rules guard every addition: the `scheduled_start` must lie within the batch window — on or after `window_start` and strictly before `window_end` — or the request fails with `ERR_VISIT_OUTSIDE_WINDOW`; the asset's `component_type` must equal the template's, or the request fails with `ERR_COMPONENT_MISMATCH`; and the batch, unit, template, asset, and plan must all belong to one and the same property, or the request fails with `ERR_CROSS_PROPERTY_REFERENCE`. Adding a visit while the batch is `LOCKED`, `EXECUTED`, or `CANCELLED` is rejected with `ERR_BATCH_NOT_MUTABLE`. A unit may never hold two non-`CANCELLED` visits whose occupied intervals intersect — each visit occupies the span from its `scheduled_start` through its `scheduled_start` plus its template's `estimated_labor_minutes`, with the end instant itself excluded, so visits that merely touch at an endpoint are allowed; any intersection, regardless of which batches the visits belong to, is rejected with `ERR_UNIT_ENTRY_OVERLAP`. Visits are listed with the optional filters `batch_id`, `unit_id`, `template_id`, `asset_id`, `plan_id`, and `visit_status`.

**Publishing** is the act that makes a batch real. The publish request must carry `expected_batch_version` equal to the batch's current `version` under the optimistic-concurrency rule of §2.9; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Publishing a batch with zero non-`CANCELLED` visits fails with `ERR_EMPTY_BATCH`; a batch whose `window_start` is no longer in the future fails with `ERR_WINDOW_IN_PAST`; and every visit's `scheduled_start` is re-checked against the window, failing with `ERR_VISIT_OUTSIDE_WINDOW` on any violation. The fiscal gate then applies per affected plan: each visit's plan must be `ADOPTED` — checked first, failing with `ERR_PLAN_NOT_ADOPTED` — and only then is headroom checked, with each plan's `committed_cents` plus the newly committed estimates required not to exceed its `budget_cents` (a sum exactly equal to the budget is permitted), failing with `ERR_BUDGET_EXCEEDED`.

A successful publish stamps `notice_sent_at` with the current logical clock, increments the batch's `version`, and moves every `SCHEDULED` visit in the batch to `NOTIFIED` — a visit in `NOTIFIED` means its residents were notified as of the batch's `notice_sent_at`. For each non-`CANCELLED` visit, the ledger writes a `VISIT_COMMIT` for the estimated visit cost — the template's `estimated_labor_minutes` multiplied by the property's `default_labor_rate_cents_per_hour`, divided by 60, rounded half-up to a whole cent — charged to that visit's `plan_id`, and each affected plan's `planned_labor_hours` and `committed_cents` recompute.

Once published, a batch may be **locked** as its window approaches: locking is legal once the logical clock has reached the instant one hour before `window_start`, and attempting it earlier fails with `ERR_INVALID_STATE`. A `LOCKED` batch refuses all visit cancellations and all rescheduling into or within it, each rejected with `ERR_BATCH_NOT_MUTABLE`. Thereafter the batch waits on its visits: the moment every non-`CANCELLED` visit in a `PUBLISHED` or `LOCKED` batch has reached a terminal state — `COMPLETED` or `NO_ACCESS` — the batch transitions itself to `EXECUTED`.

A `DRAFT` batch may instead be cancelled outright. Cancelling moves the batch to `CANCELLED` and every `SCHEDULED` visit in it to `CANCELLED`; because no ledger entries exist while a batch is `DRAFT`, nothing needs to be released.

### 3.4. Executing the Visit: Entry, Evidence, and Completion

A visit's working life begins when the assigned technician starts it. Starting is legal only from `NOTIFIED` — attempting to start a `SCHEDULED` visit fails with `ERR_INVALID_STATE` — and only for the technician whose `X-User-ID` equals the visit's `technician_id`, with mismatches rejected as `ERR_INSUFFICIENT_PERMISSIONS` at the authorization stage. Two timing checks then apply, the too-early check always evaluated first: the logical clock must have reached the visit's `scheduled_start`, failing with `ERR_VISIT_TOO_EARLY`; and when the unit is `OCCUPIED`, the clock must also have reached the batch's `notice_sent_at` plus the property's `notice_lead_hours` — an arrival exactly at that instant is permitted — failing with `ERR_NOTICE_LEAD_VIOLATION`. A `VACANT` unit carries no notice-lead check at all. A started visit is `IN_PROGRESS`.

While on site, the technician documents compliance-sensitive consumables by recording **evidence rows** on the visit: an `evidence_type` of `FILTER_REPLACEMENT`, `DETECTOR_TEST`, or `BATTERY_REPLACEMENT`; the `serial_or_lot` of the consumable installed or tested; and an optional free-text `notes` that defaults to an empty string. Each row stamps `recorded_by` with the recording technician's `X-User-ID`. The visit's evidence rows are listed through the visit-scoped evidence collection, readable by all roles.

**Completion** is the visit's settlement event. The technician supplies `actual_minutes` greater than zero and a `condition_score_recorded` between 1 and 5 inclusive; malformed payloads fail with `ERR_INVALID_REQUEST`. If the visit's template has `requires_evidence` true and not a single evidence row exists for the visit, completion is rejected with `ERR_EVIDENCE_REQUIRED`. On success the visit becomes `COMPLETED`, the recorded minutes and score are persisted, and the visit's `visit_cost_cents` — zero until this moment — is computed per §2.7. The ledger releases the committed estimate and settles the actual cost as a compensating pair on the visit's `plan_id`. The serviced asset's `condition_score` is set to `condition_score_recorded`, and its `compliance_status` is recomputed, because the asset's last-completed date for that template has just advanced. The plan's `actual_labor_minutes`, `spent_cents`, and `committed_cents` all recompute. And if this completion leaves every non-`CANCELLED` visit in the batch terminal, the batch moves itself to `EXECUTED`.

Not every knock is answered. When the assigned technician cannot gain entry, they record a failed entry on a `NOTIFIED` visit — the same technician-identity match applies, and the clock must have reached `scheduled_start` or the attempt fails with `ERR_VISIT_TOO_EARLY` — and the visit becomes `NO_ACCESS`. A failed entry charges nothing: the ledger releases the committed estimate in full.

A `NO_ACCESS` visit can be brought back through **rescheduling** by a `PropertyManager`, who supplies a `target_batch_id` and a `new_scheduled_start`. The new start must lie within the target batch's window, on or after its `window_start` and strictly before its `window_end`, failing with `ERR_VISIT_OUTSIDE_WINDOW`; the target batch must be `DRAFT` or `PUBLISHED` — `LOCKED`, `EXECUTED`, and `CANCELLED` targets fail with `ERR_BATCH_NOT_MUTABLE`; and the unit-overlap rule of §3.3 applies anew, failing with `ERR_UNIT_ENTRY_OVERLAP`. The visit's `batch_id` and `scheduled_start` are rewritten, and its landing state depends on the target: rescheduling into a `PUBLISHED` batch lands the visit directly in `NOTIFIED` and immediately commits the estimated cost to the ledger, while rescheduling into a `DRAFT` batch lands it in `SCHEDULED`, where it waits to commit at that batch's publish. The loop from `NOTIFIED` to `NO_ACCESS` and back to `NOTIFIED` may repeat as often as operations demand, each pass releasing and re-committing the estimate.

Finally, a `PropertyManager` may cancel a visit while it is `SCHEDULED` or `NOTIFIED`, provided its containing batch is not `LOCKED`, `EXECUTED`, or `CANCELLED` — otherwise `ERR_BATCH_NOT_MUTABLE`. The visit becomes `CANCELLED`; when it had been committed (that is, its batch had been published), the ledger releases the committed estimate and the plan's `committed_cents` recomputes.

### 3.5. Deficiencies and Corrective Work

Findings surface as **deficiencies**. During a visit that is `IN_PROGRESS` or `COMPLETED` — recording against any other visit state fails with `ERR_INVALID_STATE` — the technician records a deficiency naming the `asset_id` observed, which must equal the visit's own `asset_id` or the request fails with `ERR_DEFICIENCY_ASSET_MISMATCH`; a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `EMERGENCY`; and a free-text `description`. A new deficiency is `RECORDED`, its `work_order_id` null, and deficiencies are listed with the optional filters `visit_id`, `asset_id`, and `status`.

A `PropertyManager` triages a `RECORDED` deficiency, moving it to `TRIAGED` and incrementing its `version`. Alternatively, a deficiency in `RECORDED` or `TRIAGED` may be waived — but never one whose `severity` is `EMERGENCY` (`ERR_EMERGENCY_NOT_WAIVABLE`), and never while a corrective work order in `OPEN`, `IN_REVIEW`, `APPROVED`, or `IN_PROGRESS` references it (`ERR_INVALID_STATE`); a waived deficiency rests terminally in `WAIVED`.

Conversion turns a `TRIAGED` deficiency into a funded **corrective work order**. The `PropertyManager` supplies the `deficiency_id`, the `plan_id` the work will charge against, an `estimated_cost_cents` greater than zero, the `assigned_technician_id` who will perform it, an optional `replace_asset` flag that defaults to false, and — under the optimistic-concurrency rule of §2.9 — `expected_deficiency_version` equal to the deficiency's current `version`, with a stale value rejected as `ERR_STALE_VERSION` (HTTP 412). The new work order opens in `OPEN`; the deficiency's `work_order_id` is set to it and the deficiency's `version` increments, yet the deficiency's `status` deliberately remains `TRIAGED` — it is the work order's completion, not its creation, that converts the deficiency. A deficiency converts to at most one work order. The work order's own `property_id` and `asset_id` are denormalized at creation from the deficiency's chain through its visit and batch, so work orders can be listed directly with the optional filters `property_id`, `deficiency_id`, `plan_id`, `asset_id`, and `status`.

Review follows a strict doorway. The assigned technician submits an `OPEN` work order for review, moving it to `IN_REVIEW` — the caller's `X-User-ID` must equal `assigned_technician_id`, else `ERR_INSUFFICIENT_PERMISSIONS`. A `PropertyManager` then has three exits. Approval is legal only from `IN_REVIEW` — approving an `OPEN` work order fails with `ERR_INVALID_STATE` — and passes the fiscal gate: the plan must be `ADOPTED`, checked first (`ERR_PLAN_NOT_ADOPTED`), and then the plan's `committed_cents` plus the work order's `estimated_cost_cents` must not exceed `budget_cents`, with an exact match to the budget permitted (`ERR_BUDGET_EXCEEDED`); on approval the ledger writes a `WO_COMMIT` for the estimate and the plan's `committed_cents` recomputes. Returning the work order for rework sends it back from `IN_REVIEW` to `OPEN` and increments its `revision_count`, which tallies how many times the rework cycle has turned. Rejection is terminal: the work order becomes `REJECTED` and the originating deficiency falls back to `TRIAGED` for re-handling.

Execution belongs to the assigned technician. Starting an `APPROVED` work order — again with the `X-User-ID` identity match — moves it to `IN_PROGRESS` and cascades across the register: the serviced asset's `operational_status` becomes `OUT_OF_SERVICE`. Completing the work requires `actual_cost_cents` of zero or more in the payload (`ERR_INVALID_REQUEST` otherwise), and when `replace_asset` is true the payload must also carry a `new_asset_id` referencing an existing asset that is `IN_SERVICE` in the same unit — a missing asset fails with `ERR_ASSET_NOT_FOUND`, while one that is not in service or belongs to another unit fails with `ERR_INVALID_STATE`. Completion settles the money as a release of the estimate plus a settle of the actual on the ledger, recomputing the plan's `committed_cents` and `spent_cents`; it resolves the asset — with `replace_asset` the old asset becomes `DECOMMISSIONED` and its `superseded_by_asset_id` is set to `new_asset_id`, otherwise the asset returns to `IN_SERVICE`; and it moves the originating deficiency to `CONVERTED`, terminal for the deficiency unless verification later reopens it.

### 3.6. Independent Audit and Verification

Compliance work is worthless if the person who did the work also certifies it, so auditing is segregated. A `ComplianceAuditor` records a **completion audit** on a visit that is `COMPLETED`; auditing a visit in any other state fails with `ERR_INVALID_STATE`, and because exactly one audit may exist per visit, a second audit on the same visit also fails with `ERR_INVALID_STATE`. The audit carries an `outcome` of `PASS` or `FAIL`, with `fail_reason` required whenever the outcome is `FAIL`. The server stamps `auditor_id` from the caller's `X-User-ID` and `audited_at` from the logical clock, and enforces segregation of duties: an auditor whose `X-User-ID` equals the visit's `technician_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Reading a visit's audit returns an array of zero or one entries.

Audit outcomes move the register. A `FAIL` outcome drops the serviced asset's `compliance_status` to `NON_COMPLIANT` regardless of where the due-date mapping would otherwise place it. Redemption comes only from fresh work: when a later visit for the same asset and the same template completes and its audit passes, the asset leaves `NON_COMPLIANT` and re-enters the ordinary mapping of §3.7 — landing `OVERDUE` when the clock has already passed the new next-due instant.

Completed work orders face the same independent scrutiny. A `ComplianceAuditor` verifies a `COMPLETED` work order with an `outcome`; an auditor whose `X-User-ID` equals the work order's `assigned_technician_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `PASS` outcome moves the work order to `VERIFIED`, terminal. A `FAIL` outcome unwinds the settlement: the work order returns to `IN_PROGRESS`, the ledger writes a release-of-settle `WO_RELEASE` for the full `actual_cost_cents` (clawing the settled spend back out of `spent_cents`, with `committed_cents` and `spent_cents` recomputed), the asset returns to `OUT_OF_SERVICE`, and the originating deficiency reopens to `TRIAGED`. The cycle from `IN_PROGRESS` through `COMPLETED` and back to `IN_PROGRESS` may repeat until verification passes; each completion moves the deficiency to `CONVERTED` again, and each failed verification reopens it.

### 3.7. Compliance Status, Due-Date Arithmetic, and Capital Forecasting

An asset's `compliance_status` is a system-maintained reading of its PM schedule against the logical clock, recomputed whenever a visit for it completes, when the asset is created, when the clock moves, and when an audit lands. For the asset's component type and that component's current template, the **last-completed date** is the latest `scheduled_start` among the asset's `COMPLETED` visits for that template; when no such visit exists, the asset's `installed_on` stands in, and when no template exists for the asset's component type at all, the asset simply remains `COMPLIANT`. The **next-due instant** is the last-completed date plus the template's `frequency_days`.

The status mapping is evaluated in strict order. First, if a failed audit is outstanding on the latest completed visit for that asset and template, the asset is `NON_COMPLIANT`. Otherwise, if the clock has reached or passed the next-due instant — an exact arrival at the boundary counts — the asset is `OVERDUE`. Otherwise, if the clock sits inside the due-soon window and no `SCHEDULED`, `NOTIFIED`, or `IN_PROGRESS` visit exists for that asset and template, the asset is `DUE`: the due-soon window opens seven days before the next-due instant for a unit that is `OCCUPIED`, and only one day before for a `VACANT` unit — the overdue rule itself is identical for both. Anything else is `COMPLIANT`.

The portfolio-level reading is the compliance summary. For a given `property_id`, the assessed set is every asset of the property in `IN_SERVICE` or `OUT_OF_SERVICE` — decommissioned assets drop out entirely. The response reports `assessed_count` (the size of that set), `compliant_count` (how many of them are `COMPLIANT`), and `compliance_rate_pct`: the compliant count multiplied by 10000, divided by the assessed count, rounded half-up, then divided by 100 — a percentage rendered with two decimal places. By convention, a property whose asset register is entirely empty yields exactly 100.00 rather than an error.

**Capital forecasting** turns PM findings into a replacement plan. A `PropertyManager` computes a snapshot by supplying the `property_id`, a `horizon_years` between 1 and 10 inclusive, and a `variant` of `AGE_BASED` or `CONDITION_BASED`; the snapshot is persisted append-only with `computed_at` stamped from the logical clock, and snapshots of a property are listed with an optional `variant` filter. The input set is every asset of the property that is not `DECOMMISSIONED`. Each asset's **effective life** depends on the variant: `AGE_BASED` uses the asset's `expected_life_months` unchanged and ignores condition entirely, while `CONDITION_BASED` multiplies `expected_life_months` by a condition factor — 0.60 for a `condition_score` of 1, 0.80 for 2, 1.00 for 3, 1.15 for 4, and 1.30 for 5 — so a score of 5 defers replacement to 130 percent of nominal life and a score of 1 accelerates it to 60 percent; an asset that has never been serviced, whose `condition_score` is still null, is treated as a score of 3 with factor 1.00. The scaled figure is rounded down to a whole number of months before any date arithmetic.

The asset's replacement date is `installed_on` plus its effective life in months. Forecast years are indexed from zero: year zero covers the half-open interval from the current clock to one year out, and each subsequent year covers the next one-year interval, end-exclusive. A replacement date already before the clock buckets into year zero; otherwise the date falls into the year whose interval contains it, and dates at or beyond the end of the horizon are not projected at all. The snapshot's `per_year_cents` is an array of exactly `horizon_years` integers, each the sum of `replacement_cost_cents` over the assets bucketed to that year; `total_projected_cents` is the sum of that array; and `asset_count_projected` is the number of assets bucketed anywhere within the horizon.

## 4. Endpoint Definitions

Operations that create a new resource — a property, building, unit, asset, template, plan, batch, visit, evidence row, deficiency, audit, work order, or forecast snapshot — return `201 Created`. Operations that modify an existing resource, drive a state transition, perform a read, or set the logical clock return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving); recomputes all asset compliance statuses | PropertyManager |
| POST | `/pm/properties` | Create a property | PropertyManager |
| GET | `/pm/properties/{property_id}` | Get a property | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/properties/{property_id}/archive` | Archive a property (blocks all child mutations) | PropertyManager |
| POST | `/pm/buildings` | Create a building in a property | PropertyManager |
| GET | `/pm/buildings/{building_id}` | Get a building | PropertyManager, Technician, ComplianceAuditor |
| GET | `/pm/properties/{property_id}/buildings` | List buildings of a property | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/units` | Create a unit in a building | PropertyManager |
| GET | `/pm/buildings/{building_id}/units` | List units in a building | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/assets` | Register an asset in a unit | PropertyManager |
| GET | `/pm/assets/{asset_id}` | Get one asset with computed `age_months` and `warranty_active` | PropertyManager, Technician, ComplianceAuditor |
| GET | `/pm/assets` | List assets with filters | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/assets/{asset_id}/operational-status` | Move an asset between `IN_SERVICE` and `OUT_OF_SERVICE` | PropertyManager |
| POST | `/pm/assets/{asset_id}/decommission` | Decommission an asset (terminal) | PropertyManager |
| POST | `/pm/pm-task-templates` | Create a PM task template | PropertyManager |
| GET | `/pm/properties/{property_id}/pm-task-templates` | List templates of a property; retired excluded unless `include_retired` | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/pm-task-templates/{template_id}/retire` | Retire a template (soft delete) | PropertyManager |
| POST | `/pm/plans` | Create a PM plan for a year | PropertyManager |
| GET | `/pm/plans/{plan_id}` | Get a plan with computed aggregates | PropertyManager, Technician, ComplianceAuditor |
| GET | `/pm/properties/{property_id}/plans` | List plans of a property | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/plans/{plan_id}/adopt` | Adopt a plan | PropertyManager |
| POST | `/pm/plans/{plan_id}/close` | Close a plan (terminal) | PropertyManager |
| GET | `/pm/plans/{plan_id}/ledger` | List budget ledger entries of a plan | PropertyManager, ComplianceAuditor |
| POST | `/pm/batches` | Create an entry batch | PropertyManager |
| GET | `/pm/batches/{batch_id}` | Get a batch | PropertyManager, Technician, ComplianceAuditor |
| GET | `/pm/properties/{property_id}/batches` | List batches of a property | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/batches/{batch_id}/publish` | Publish a batch (resident notices, `SCHEDULED` → `NOTIFIED` cascade, budget commits); OCC-guarded | PropertyManager |
| POST | `/pm/batches/{batch_id}/lock` | Lock a published batch shortly before entry | PropertyManager |
| POST | `/pm/batches/{batch_id}/cancel` | Cancel a `DRAFT` batch and its visits | PropertyManager |
| POST | `/pm/visits` | Add a visit to a `DRAFT` batch | PropertyManager |
| GET | `/pm/visits/{visit_id}` | Get a visit | PropertyManager, Technician, ComplianceAuditor |
| GET | `/pm/visits` | List visits with filters | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/visits/{visit_id}/start` | Technician starts a `NOTIFIED` visit | Technician |
| POST | `/pm/visits/{visit_id}/complete` | Technician completes an `IN_PROGRESS` visit | Technician |
| POST | `/pm/visits/{visit_id}/no-access` | Technician records a failed entry on a `NOTIFIED` visit | Technician |
| POST | `/pm/visits/{visit_id}/reschedule` | Reschedule a `NO_ACCESS` visit into a target batch | PropertyManager |
| POST | `/pm/visits/{visit_id}/cancel` | Cancel a `SCHEDULED` or `NOTIFIED` visit | PropertyManager |
| POST | `/pm/visits/{visit_id}/evidence` | Record compliance evidence on a visit | Technician |
| GET | `/pm/visits/{visit_id}/evidence` | List compliance evidence of a visit | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/visits/{visit_id}/deficiencies` | Record a deficiency found during a visit | Technician |
| GET | `/pm/deficiencies` | List deficiencies with filters | PropertyManager, Technician, ComplianceAuditor |
| GET | `/pm/deficiencies/{deficiency_id}` | Get a deficiency | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/deficiencies/{deficiency_id}/triage` | Triage a `RECORDED` deficiency | PropertyManager |
| POST | `/pm/deficiencies/{deficiency_id}/waive` | Waive a deficiency (non-`EMERGENCY`, no open work order) | PropertyManager |
| POST | `/pm/visits/{visit_id}/audit` | Compliance audit of a `COMPLETED` visit; at most one per visit | ComplianceAuditor |
| GET | `/pm/visits/{visit_id}/audit` | Get the audit of a visit (array of 0 or 1) | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/work-orders` | Convert a `TRIAGED` deficiency into a corrective work order; OCC-guarded | PropertyManager |
| GET | `/pm/work-orders/{wo_id}` | Get a corrective work order | PropertyManager, Technician, ComplianceAuditor |
| GET | `/pm/work-orders` | List work orders with filters | PropertyManager, Technician, ComplianceAuditor |
| POST | `/pm/work-orders/{wo_id}/submit-review` | Technician submits an `OPEN` work order for review | Technician |
| POST | `/pm/work-orders/{wo_id}/approve` | Approve an `IN_REVIEW` work order (budget check) | PropertyManager |
| POST | `/pm/work-orders/{wo_id}/return-rework` | Return an `IN_REVIEW` work order to `OPEN` | PropertyManager |
| POST | `/pm/work-orders/{wo_id}/reject` | Reject an `IN_REVIEW` work order (terminal) | PropertyManager |
| POST | `/pm/work-orders/{wo_id}/start` | Technician starts an `APPROVED` work order | Technician |
| POST | `/pm/work-orders/{wo_id}/complete` | Technician completes an `IN_PROGRESS` work order | Technician |
| POST | `/pm/work-orders/{wo_id}/verify` | Auditor verifies a `COMPLETED` work order | ComplianceAuditor |
| GET | `/pm/visits/{visit_id}/ledger-entries` | List ledger entries sourced from a visit | PropertyManager, ComplianceAuditor |
| GET | `/pm/work-orders/{wo_id}/ledger-entries` | List ledger entries sourced from a work order | PropertyManager, ComplianceAuditor |
| POST | `/pm/capital-forecasts` | Compute a capital replacement forecast snapshot | PropertyManager |
| GET | `/pm/properties/{property_id}/capital-forecasts` | List forecast snapshots of a property | PropertyManager, ComplianceAuditor |
| GET | `/pm/compliance-summary` | Computed compliance rate across a property's asset register | PropertyManager, Technician, ComplianceAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_BUILDING_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSET_NOT_FOUND` | 404 Not Found |
| `ERR_TEMPLATE_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_DEFICIENCY_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROPERTY_ARCHIVED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VISIT_TOO_EARLY` | 409 Conflict |
| `ERR_NOTICE_LEAD_VIOLATION` | 409 Conflict |
| `ERR_WINDOW_IN_PAST` | 409 Conflict |
| `ERR_VISIT_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_BATCH_NOT_MUTABLE` | 409 Conflict |
| `ERR_EMPTY_BATCH` | 409 Conflict |
| `ERR_UNIT_ENTRY_OVERLAP` | 409 Conflict |
| `ERR_COMPONENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CROSS_PROPERTY_REFERENCE` | 422 Unprocessable Entity |
| `ERR_DEFICIENCY_ASSET_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_EMERGENCY_NOT_WAIVABLE` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_ADOPTED` | 402 Payment Required |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |
