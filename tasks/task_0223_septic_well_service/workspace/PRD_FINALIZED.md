# Septic & Well Service API — Product Requirements Document

## 1. Introduction

Operators of septic and well field-service businesses juggle a deceptively wide range of moving parts: each customer account owns one or more physical sites, each site carries tanks and wells that must be pumped on a recurring cadence, inspected for compliance, and — when the county demands it — permitted before they can be returned to service. The work itself is scheduled onto technician routes that have to respect shift windows, certification rules, and the simple physical reality that one truck cannot be in two places at once. This API exists to make that whole operation legible and enforceable: it is the system of record for accounts, sites, assets, recurring service plans, work orders, routes, inspection reports, county permit filings, parts-and-labor lines, and the reminders that keep recurring service from slipping.

The product's central promise is that money, compliance, and scheduling never drift apart. A pumping visit's cost is estimated when it is scheduled and re-derived from measured volume when it is completed; an inspection's outcome feeds a site's compliance status and risk score, which a county permit decision then finalizes; an account placed on hold immediately stops new work and tears down the work already on the calendar. Because several of these flows touch the same site or route from different angles — dispatch, billing, compliance — the system enforces immediate consistency and exposes deterministic, recomputed counters and dates rather than letting clients infer them. This document specifies the full contract: the global response and access rules in Section 2, the business workflows and their scattered rules in Section 3, the endpoint surface in Section 4, and the error catalogue in Section 5.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they act. If either header is missing or invalid, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as `Dispatcher`, `FieldTech`, `ComplianceOfficer`, and `Customer`. The `Dispatcher` runs operations — creating accounts, sites, assets, service plans, routes, and work orders, and driving scheduling, dispatch, reverts, cancellations, invoicing, payments, account holds, and technician suspension and reinstatement. The `ComplianceOfficer` owns inspection reports and county permit filings. The `FieldTech` is the technician in the field who starts and completes their own dispatched work orders and records parts. The `Customer` is an account-facing, largely read-only persona who can also acknowledge reminders.

Two roles are opaque operator identities and two are entity-backed. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to an entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded if useful but never matched against an entity `id`. When `X-User-Role` is `FieldTech`, `X-User-ID` is the `id` of the acting `Technician`; any ownership check on a resource that references a `Technician` compares that resource's technician foreign key to `X-User-ID` — concretely, a field tech may start or complete only a work order whose `technician_id` equals their own `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's owning-account foreign key to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, and is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, every list is returned sorted by each resource's creation timestamp in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in the system are first-class records that carry a standard set of system-managed fields. The `id` is a server-minted UUID, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation that changes the resource; it underpins the optimistic concurrency mechanism described in §2.6.

One entity is deliberately leaner. A `Reminder` is an append-only event record: it carries only `id` and `created_at`. It has neither `updated_at` nor `version`, and acknowledging a reminder mutates only its own `status` field without participating in the versioning convention used by the other entities.

### 2.5. Derived Fields, Counters, and Reconciliation

Several fields are never written directly by clients; the server derives and re-derives them as upstream facts change, and any such recomputation that alters a resource is a mutation that refreshes `updated_at` and increments `version` (except on the version-less `Reminder`). On a `Site`, the `risk_score` and `next_pump_due_date` are computed; on a `WorkOrder`, the `estimated_cost_cents`, `final_cost_cents`, `invoice_total_cents`, and `window_end_minute` are computed; on a `Route`, the `assigned_stop_count`, `booked_minutes`, and `optimized_sequence` are computed; on a `RepairLine`, the `line_total_cents` is computed; and on an `Account`, the `outstanding_balance_cents` is system-maintained.

These derived values cascade. A single operation routinely mutates more than one entity, and when it does, every affected entity's counters are reconciled in the same operation and each such reconciliation independently bumps that entity's `version` and `updated_at`. The specific cascades — account-hold tear-down, completion-driven reminder emission, route counter recomputation — are detailed in the workflows of Section 3. The governing principle here is that the system never leaves a counter stale: if a work order leaves or enters the set that a route counts, that route's `assigned_stop_count` and `booked_minutes` are recomputed before the operation returns.

### 2.6. Optimistic Concurrency on Service-Plan Creation

Creating a service plan is the one write in this system guarded by optimistic concurrency control, because it supersedes whatever service plan was previously active on the site and therefore advances the site itself. A create request must carry `expected_site_version`, a non-optional field whose value is the `version` of the target `Site` that the client last observed. If `expected_site_version` does not equal the site's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412): another writer has already created a plan that legitimately superseded the prior one, so this writer's view of the site is stale and must be re-read before retrying. No other endpoint accepts or requires a version field; only service-plan creation participates in this check.

### 2.7. Monetary Precision and Rounding

All money in the system is held as integer cents — there are no fractional-cent amounts on any resource. Where a calculation introduces a fractional result that must be reduced to whole cents, the system rounds half up (a value exactly halfway between two integers rounds to the larger). This rounding rule governs the emergency surcharge on a work order's cost and the per-line tax computation on repair lines, both detailed in Section 3. The risk score is a separate, non-monetary integer constrained to the range 0 through 100 inclusive.

### 2.8. Nested Resource Retrieval and Foreign-Key Resolution

When an endpoint path names a resource by id, that id must resolve to an existing resource or the request is rejected with `ERR_NOT_FOUND`; where a path carries more than one identifier, they are validated left to right and the first one that does not resolve produces the rejection. Separately, when a request body names another resource by foreign key — for example an `account_id`, `site_id`, `work_order_id`, `inspection_report_id`, `technician_id`, or `route_id` — and that reference does not point to an existing resource, the create is rejected with `ERR_FK_NOT_FOUND`. Required body fields must be present and well-typed, and any enum value must fall within its allowed set, or the request fails with `ERR_INVALID_REQUEST`.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority so that the same bad request always yields the same error. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of path resources (`ERR_NOT_FOUND`), then foreign-key resolution of body references (`ERR_FK_NOT_FOUND`), then presence and typing of required body fields including enum membership (`ERR_INVALID_REQUEST`), and then field-range invariants (`ERR_VALIDATION`). Only after all of those structural checks pass does the system evaluate state-machine legality (`ERR_INVALID_STATE`) and the domain-specific business rules. Within scheduling, the business checks themselves are ordered; that ordering is spelled out in §3.4 so that, for example, an account-on-hold rejection surfaces ahead of a window-overlap rejection rather than being masked by it.

## 3. Business Logic & Workflows

### 3.1. Accounts, Sites, and the Asset Profile

The customer relationship begins with an **Account**, created by a `Dispatcher` with a `name` and a `billing_email`. A new account opens in `GOOD` standing and with an `outstanding_balance_cents` of 0. The `standing` field has exactly two values, `GOOD` and `HOLD`; `outstanding_balance_cents` is the running sum of the invoice totals of completed work that has been invoiced but not yet paid, and the system recomputes it as work is invoiced and paid (see §3.6).

Under an account, a `Dispatcher` registers one or more **Sites**, each carrying its owning `account_id`, a service street `address`, a `county_code` naming the permitting jurisdiction (for example `KING`), and an optional `service_minutes`. The `service_minutes` field is the default on-site duration used to size scheduling windows; it defaults to 60 minutes when omitted and must be at least 15 minutes — a value below 15 is rejected with `ERR_VALIDATION`. A site tracks a `compliance_status` that is one of `UNKNOWN`, `COMPLIANT`, `CONDITIONAL`, or `NON_COMPLIANT`, beginning at `UNKNOWN`; a `risk_score` integer that begins at 0; a `last_pumped_date` that is null until the first pumping visit completes; and a computed `next_pump_due_date`. How those last four evolve is the subject of §3.7, §3.8, and §3.9.

Each site holds physical **Assets**. A `Dispatcher` creates an asset with its `site_id`, an `asset_type` of either `SEPTIC_TANK` or `WELL`, a `capacity_gallons` that must be greater than zero (a non-positive capacity is rejected with `ERR_VALIDATION`), and an `install_year`. An asset's `status` is `ACTIVE` on creation and may become `DECOMMISSIONED`. Capacity is a tank measure; for a `WELL` it is recorded but not used in pricing.

### 3.2. Recurring Service Plans

A **ServicePlan** captures the recurring pumping cadence for a site. A `Dispatcher` creates one with the target `site_id`, a `frequency_months` cadence between 1 and 120 months, an `estimated_gallons` figure greater than zero used for cost estimation, and the `expected_site_version` required by the concurrency rule in §2.6. A plan's `status` is `ACTIVE` or `SUPERSEDED`, and a site may have only one `ACTIVE` plan at a time. Creating a new plan transitions the prior `ACTIVE` plan to `SUPERSEDED`, sets the new plan `ACTIVE`, recomputes the site's `next_pump_due_date`, and increments the site's `version` by one. Because the create both supersedes the prior plan and advances the site, it carries the `expected_site_version` guard: if that value does not match the site's current `version`, the create is rejected with `ERR_STALE_VERSION` and nothing changes.

The `next_pump_due_date` is a projection. When the site has an `ACTIVE` service plan and a non-null `last_pumped_date`, the due date is the `last_pumped_date` advanced forward by the active plan's `frequency_months` number of months; month arithmetic clamps to the end of the month where a target day would otherwise overflow. When the site has no active plan or has never been pumped, the `next_pump_due_date` is null.

### 3.3. The Work-Order Lifecycle

A **WorkOrder** is the unit of field work, and it tracks two parallel state axes on one record: an operational `status` and a billing `billing_status`. A `Dispatcher` creates a work order in `DRAFT` with the `site_id` to be serviced, a `work_type` of `PUMPING`, `INSPECTION`, `EMERGENCY`, or `REPAIR`, a `scheduled_date` (an ISO `YYYY-MM-DD` date), a `window_start_minute` giving the planned arrival as minutes after local midnight, and an optional `estimated_gallons`. At creation, `billing_status` is `UNBILLED`, and `emergency_surcharge_applies` is set true exactly when `work_type` is `EMERGENCY` and false otherwise. The `route_id` and `technician_id` foreign keys are not supplied at creation; they are populated and cleared by the scheduling and dispatch transitions below.

The operational `status` moves through `DRAFT`, `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal. Attempting any transition from a status that does not define it is rejected with `ERR_INVALID_STATE`, and attempting to mutate a terminal work order is rejected with `ERR_IMMUTABLE`. Scheduling (`DRAFT → SCHEDULED`) is covered in §3.4. Dispatching advances `SCHEDULED → DISPATCHED`: a `Dispatcher` performs it, the work order's `technician_id` is set from the route's `technician_id`, and route counters are unchanged because a `DISPATCHED` order is still counted. A `Dispatcher` may revert `DISPATCHED → SCHEDULED`, which clears `technician_id` and returns the order to the schedule; reverting is permitted only while the route is `OPEN`, and against a `LOCKED` route it is rejected with `ERR_ROUTE_LOCKED`.

From `DISPATCHED`, the assigned `FieldTech` starts the visit, advancing `DISPATCHED → IN_PROGRESS`; the actor's `Technician` `id` must equal the work order's `technician_id`. The same `FieldTech` then completes the visit, advancing `IN_PROGRESS → COMPLETED`; completion's cost, counter, and reminder consequences are detailed in §3.5 and §3.7. A `Dispatcher` may cancel a non-terminal order: cancellation is defined from `DRAFT`, `SCHEDULED`, and `DISPATCHED`. Cancelling from `DRAFT` simply terminates the order. Cancelling from `SCHEDULED` or `DISPATCHED` additionally clears the order's `route_id` and `technician_id` and recomputes the route's `assigned_stop_count` and `booked_minutes`, since the order has left the counted set. Cancellation from `SCHEDULED` or `DISPATCHED` is also the system action used by the account-hold cascade described in §3.10.

### 3.4. Scheduling onto a Route and the Conflict Checks

Scheduling is where the calendar constraints live. A `Dispatcher` schedules a `DRAFT` work order by supplying the `route_id` it should join, advancing `status` from `DRAFT` to `SCHEDULED`. On success the system sets `route_id`, computes `window_end_minute` as `window_start_minute` plus the site's `service_minutes` (a half-open occupation interval whose end minute is excluded), defaults `estimated_gallons` from the site's `ACTIVE` service plan's `estimated_gallons` when the field was omitted and the work type is `PUMPING`, computes `estimated_cost_cents` (see §3.5), and recomputes the route's `assigned_stop_count` and `booked_minutes`.

Several conditions guard scheduling, and because they share one endpoint they are evaluated in a defined order. First, the owning site's account must be in `GOOD` standing; scheduling against an account whose `standing` is `HOLD` is rejected with `ERR_ACCOUNT_ON_HOLD`. The supplied `route_id` must reference a route whose `status` is `OPEN`; a `LOCKED` route rejects the assignment with `ERR_ROUTE_LOCKED`. The technician's daily availability is then enforced three ways. The work order's half-open window `[window_start_minute, window_end_minute)` must not overlap any other `SCHEDULED` or `DISPATCHED` work order on the same technician and the same date; an overlap is rejected with `ERR_TECH_WINDOW_CONFLICT`. The window must also keep its distance from other work at the same site on the same date: between any two `SCHEDULED` or `DISPATCHED` work orders on the same site and date, the gap — measured as the later order's `window_start_minute` minus the earlier order's `window_end_minute`, with the windows treated as closed intervals — must be at least the site day-buffer; a gap smaller than the buffer (including windows that touch or sit adjacent within the buffer) is rejected with `ERR_SITE_BUFFER_CONFLICT`. The site day-buffer is two hours. Finally, the window must fall within the technician's shift: both `window_start_minute` and `window_end_minute` must lie within the technician's `shift_start_minute` through `shift_end_minute` bounds, and a window outside that shift is rejected with `ERR_OUTSIDE_SHIFT`. Among these scheduling checks the precedence runs account-standing first, then route-locked, then the technician window overlap, then the site buffer, then the shift-bounds check, so that a higher-priority condition is reported in preference to a lower one when more than one is violated.

A route is owned by a technician and dated. A `Dispatcher` creates a **Route** with the `technician_id` who will run it and a `route_date` (an ISO `YYYY-MM-DD` date); it opens with `status` `OPEN`, an `assigned_stop_count` of 0, `booked_minutes` of 0, and an empty `optimized_sequence`. The `assigned_stop_count` is the number of work orders whose `route_id` is this route and whose `status` is `SCHEDULED` or `DISPATCHED`. The `booked_minutes` is the sum, over that same set, of each order's window length (`window_end_minute` minus `window_start_minute`). A `Dispatcher` may lock a route, moving `status` to `LOCKED`; a locked route rejects assignment, revert, and optimize operations with `ERR_ROUTE_LOCKED`.

Optimizing a route computes its stop order. The `optimized_sequence` is the list of `work_order_id` values for the route's `SCHEDULED` and `DISPATCHED` work orders, ordered by `window_start_minute` ascending and breaking ties by `created_at` ascending; no other ordering key is used, and `created_at` is the only tie-break. When the route has no such work orders, the `optimized_sequence` is the empty list.

### 3.5. Work-Order Cost: Estimate and Final

A work order's cost is computed twice from the same tiered model: an estimate at scheduling and a final figure at completion. The model prices pumped volume in two tiers on top of a flat trip fee. The trip fee is 9000 cents. The first 1000 gallons (the base-included volume) are priced at 25 cents per gallon, and every gallon beyond 1000 is priced at 40 cents per gallon. Concretely, take the gallons for the run, charge the lesser of that figure and 1000 gallons at 25 cents each, charge any gallons above 1000 at 40 cents each, and add the 9000-cent trip fee to that pumping subtotal. If the emergency surcharge applies to the work order, increase the running total by an additional fifty percent of itself — that is, compute fifty percent of the current total (5000 basis points), round that addition half up to whole cents, and add it on. `INSPECTION` and `REPAIR` work orders pump no volume, so their gallons count is zero and their cost is just the trip fee (plus surcharge only if it applied, which it never does for those types). The emergency surcharge flag is false for `PUMPING` and true for `EMERGENCY`.

The two variants differ only in which gallons feed the model and which field they write. The **estimate** variant runs at scheduling: its gallons are the work order's `estimated_gallons` (taken from the request, or defaulted from the site's active service plan for `PUMPING` as described in §3.4), and it writes `estimated_cost_cents`. The **final** variant runs at completion: its gallons are the `measured_gallons` the field tech supplies, and it writes `final_cost_cents`. Because the final run uses actual measured volume, the overage tier can land differently than the estimate did, so the two figures may legitimately diverge.

Completion has its own precondition beyond the actor identity check in §3.3: for `PUMPING` and `EMERGENCY` work, the field tech must supply `measured_gallons`, and it must be present and at least zero; a completion of those types without `measured_gallons` is rejected with `ERR_MEASUREMENT_REQUIRED`. At completion the system computes `final_cost_cents`, then computes `invoice_total_cents` (§3.6), recomputes the route counters since the order has left the counted set, and — for `PUMPING` and `EMERGENCY` — applies the pump-completion site cascade of §3.7.

### 3.6. Parts, Invoicing, and Account Balance

Repair work accrues parts and labor as **RepairLine** records. A `Dispatcher` or a `FieldTech` adds a line to a `REPAIR` work order with the owning `work_order_id`, a `part_name` description, a `quantity` greater than zero (rejected with `ERR_VALIDATION` otherwise), a `unit_price_cents` of at least zero, and an optional `tax_rate_bps` tax rate in basis points that defaults to 0 and must lie between 0 and 2000. Each line's `line_total_cents` is computed as the quantity times the unit price, scaled up by the tax rate (one plus the basis-point rate divided by ten thousand), with that single result rounded half up to whole cents.

The invoice total aggregates parts onto the work-order cost with the rounding order pinned: each repair line is rounded to whole cents first, and only then are the already-rounded line totals summed — never sum-then-round. The work order's `invoice_total_cents` is its `final_cost_cents` plus the parts total, where the parts total is the sum of the `line_total_cents` of every repair line whose `work_order_id` is this work order, processed in `created_at` ascending order; a work order with no repair lines has a parts total of zero. The `invoice_total_cents` remains 0 until the order is invoiced.

Billing evolves on a second axis. A work order's `billing_status` runs `UNBILLED → INVOICED → PAID`, with `PAID` terminal. A `Dispatcher` may invoice a work order only once its operational `status` is `COMPLETED`; invoicing freezes `invoice_total_cents` onto the invoice and increases the owning account's `outstanding_balance_cents` by that amount. Recording payment advances `INVOICED → PAID` and decreases the owning account's `outstanding_balance_cents` by the same `invoice_total_cents`.

### 3.7. Pump Completion, Due Dates, and Reminders

Completing a `PUMPING` or `EMERGENCY` work order is the event that keeps recurring service on track, and it sets off a two-hop cascade. First, the site's `last_pumped_date` is set to the completed order's `scheduled_date`. Then the site's `next_pump_due_date` is recomputed using the projection rule of §3.2 — that is, the new `last_pumped_date` advanced by the active service plan's `frequency_months`, or null if there is no active plan. That recompute, in turn, emits a **Reminder** of `reminder_type` `PUMP_DUE` whose `due_date` is the freshly computed `next_pump_due_date`. A reminder is an append-only event with a `site_id`, the `reminder_type` (`PUMP_DUE` or `COMPLIANCE_OVERDUE`), the `due_date` it pertains to, and a `status` that opens `PENDING` and may move to `ACKNOWLEDGED` or `DISMISSED`. A `Dispatcher` or a `Customer` may acknowledge a pending reminder, setting its `status` to `ACKNOWLEDGED`.

### 3.8. Inspection Reports and Provisional Risk

Compliance begins after a `COMPLETED` `INSPECTION` work order. A `ComplianceOfficer` opens an **InspectionReport** against that work order by supplying its `work_order_id` and an optional `defect_count` (a count of observed defects, at least zero, defaulting to 0). The report opens in `DRAFT`. While it stays `DRAFT`, the compliance officer may edit its `result` and `defect_count`; the `result` is one of `PASS`, `CONDITIONAL`, or `FAIL`. Editing a report that is no longer `DRAFT` is rejected with `ERR_IMMUTABLE`.

Finalizing a report advances its `status` from `DRAFT` to `FINALIZED` and requires that a `result` be supplied and that the linked work order be `COMPLETED` with a `work_type` of `INSPECTION`. On finalize, the report's `finalized_at` timestamp is set, the site's `compliance_status` is derived from the result (`PASS` yields `COMPLIANT`, `CONDITIONAL` yields `CONDITIONAL`, and `FAIL` yields `NON_COMPLIANT`), and the site's `risk_score` is recomputed provisionally. A `FINALIZED` report is immutable and is what unlocks permit filing.

The **provisional** risk score is a weighted sum, clamped to the 0–100 range. Start from a base set by the report result — 0 for `PASS`, 30 for `CONDITIONAL`, and 60 for `FAIL`. Add a defect component equal to the report's `defect_count` multiplied by 8 per defect, but capped at 24 (so the defect contribution never exceeds 24 no matter how many defects). Add an age penalty of 15 when the site's newest active asset is old enough — specifically, when the current year minus the newest active asset's `install_year` is at least 25 years, where the newest active asset is the one with the greatest `install_year` among the site's assets whose `status` is `ACTIVE`; otherwise the age component is 0. Sum the base, the defect component, and the age component, then clamp the result to no less than 0 and no more than 100. The provisional variant uses the report alone and carries no permit-outcome term.

### 3.9. County Permit Filings and Final Risk

Once a report is finalized, a `ComplianceOfficer` opens a **PermitFiling** against it, supplying the `inspection_report_id` and the `site_id`. The filing opens in `DRAFT` with a `submission_count` of 0, and its `county_code` is copied from the site at creation. A filing's `status` cycles through `DRAFT`, `SUBMITTED`, `APPROVED`, and `REJECTED`, with `APPROVED` terminal; a rejected filing can return to `DRAFT` for another attempt.

Submitting a filing advances `DRAFT → SUBMITTED` and is guarded by three conditions. The linked inspection report must be `FINALIZED`, or the submit is rejected with `ERR_REPORT_NOT_FINALIZED`. The site's `compliance_status` must not be `NON_COMPLIANT`, or the submit is rejected with `ERR_SITE_NON_COMPLIANT`. And a cooling-off window must have elapsed: the server's current UTC clock must be at or past the report's `finalized_at` plus the cooling-off duration of 48 hours, or the submit is rejected with `ERR_COOLING_OFF`. On a successful submit the `submission_count` increments by one and, if not already set, the `county_code` is copied from the site.

The county then decides a `SUBMITTED` filing, supplying a `decision` and an optional `decision_reason`. An approve decision advances `SUBMITTED → APPROVED`, sets the site's `compliance_status` to `COMPLIANT`, and recomputes the site's `risk_score` to its final value. A reject decision advances `SUBMITTED → REJECTED`, stores the `decision_reason`, and recomputes the site's `risk_score` to its final value with a rejection penalty. A `ComplianceOfficer` may reopen a `REJECTED` filing, advancing `REJECTED → DRAFT` so it can be resubmitted — the resubmission loop that lets a filing pass through `REJECTED → DRAFT → SUBMITTED` again.

The **final** risk score takes the same weighted base, defect, and age computation as the provisional score and then folds in the permit outcome. On approval, the score is relieved by its result base — the score becomes the larger of 0 and the score minus the result-base relief (the same per-result base of 0 for `PASS`, 30 for `CONDITIONAL`, 60 for `FAIL`) — keeping the result at no less than 0. On rejection, a rejection penalty of 20 is added and the result is then clamped to the 0–100 range. In both cases the final figure stays an integer within 0 through 100 inclusive.

### 3.10. Account Holds and the Cancellation Cascade

When an account falls behind, a `Dispatcher` places it on hold, advancing `standing` from `GOOD` to `HOLD`, and this is the system's deepest cascade. Putting the account on hold cancels every work order belonging to the account's sites whose `status` is `DRAFT`, `SCHEDULED`, or `DISPATCHED`, driving each to `CANCELLED`. Each of those cancellations, where the order had a `route_id`, in turn triggers that route's counter recompute — its `assigned_stop_count` and `booked_minutes` are recalculated — which is the next hop of the cascade. Finally, the hold increments the account's `version` by one. Releasing a hold advances `standing` from `HOLD` back to `GOOD` and increments the account's `version` by one, but it does not auto-restore the previously cancelled work orders; once cancelled they stay cancelled.

### 3.11. Technician Status

A `Dispatcher` registers a **Technician** with a `name`, a `shift_start_minute`, a `shift_end_minute`, and an optional `certified_for_wells` flag that defaults to false. Both shift minutes are minutes from local midnight in the range 0 through 1440, and `shift_end_minute` must be strictly greater than `shift_start_minute`; a shift end at or before the shift start, or a minute value outside 0 through 1440, is rejected with `ERR_VALIDATION`. The `certified_for_wells` flag governs whether the technician may service `WELL` assets and well inspections. A technician's `status` is `ACTIVE` or `SUSPENDED`, starting `ACTIVE`.

Two cross-entity rules tie technicians to dispatch. Dispatching a work order requires that the work order's `technician_id` reference the route's `technician_id` and that that technician's `status` be `ACTIVE`; dispatching to a suspended technician is rejected with `ERR_TECH_SUSPENDED`. A well job — a `WELL` asset or well inspection — additionally requires the technician's `certified_for_wells` to be true at dispatch, and a well job dispatched to an uncertified technician is rejected with `ERR_TECH_NOT_CERTIFIED`.

Suspending a technician advances `status` from `ACTIVE` to `SUSPENDED` and reverts each of that technician's `DISPATCHED` work orders back to `SCHEDULED`, clearing each one's `technician_id`; route counters are unaffected because a `SCHEDULED` order is still counted. Reinstating a technician advances `status` from `SUSPENDED` back to `ACTIVE` with no further side effects.

### 3.12. Reading Across the System and the Logical Clock

Beyond the per-resource fetches, the system exposes reverse-reachability listings so clients can walk the foreign-key graph: the sites of an account, the assets, service plans, and reminders of a site, the work orders on a route, the routes of a technician, the repair lines and inspection reports of a work order, and filtered listings of work orders and permit filings. The work-order listing accepts optional `site_id`, `technician_id`, `route_id`, and `status` filters alongside the `limit` and `offset` pagination controls; the permit-filing listing accepts optional `site_id`, `inspection_report_id`, and `status` filters with the same pagination controls.

Because cooling-off windows and due dates depend on wall-clock time, the system provides an administrative test-driving capability that sets the server's current UTC clock to a supplied `to_iso8601` instant, making cooling-off and due-date logic deterministic. This capability is restricted to the `Dispatcher` and `ComplianceOfficer` roles.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify an existing resource — including all state transitions, acknowledgements, and the clock-setting capability — return `200 OK`. The request body, response shape, and side effects of each endpoint are described in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create an account | Dispatcher |
| GET | `/accounts/{id}` | Get an account | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| GET | `/accounts/{id}/sites` | List sites for an account | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/accounts/{id}/hold` | Put account on hold (cascade-cancels open work orders) | Dispatcher |
| POST | `/accounts/{id}/release-hold` | Release account hold | Dispatcher |
| POST | `/technicians` | Create a technician | Dispatcher |
| GET | `/technicians/{id}` | Get a technician | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/technicians/{id}/suspend` | Suspend a technician | Dispatcher |
| POST | `/technicians/{id}/reinstate` | Reinstate a technician | Dispatcher |
| GET | `/technicians/{id}/routes` | List routes for a technician | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/sites` | Create a site under an account | Dispatcher |
| GET | `/sites/{id}` | Get a site | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| GET | `/sites/{id}/assets` | List assets for a site | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| GET | `/sites/{id}/service-plans` | List service plans for a site | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| GET | `/sites/{id}/reminders` | List reminders for a site | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/assets` | Create an asset on a site | Dispatcher |
| GET | `/assets/{id}` | Get an asset | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/service-plans` | Create a recurring service plan (supersedes prior active; OCC on site version) | Dispatcher |
| GET | `/service-plans/{id}` | Get a service plan | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/work-orders` | Create a work order in draft | Dispatcher |
| GET | `/work-orders/{id}` | Get a work order | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| GET | `/work-orders` | List work orders (filterable) | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/work-orders/{id}/schedule` | Schedule a draft work order onto an open route | Dispatcher |
| POST | `/work-orders/{id}/dispatch` | Dispatch a scheduled work order to the route's technician | Dispatcher |
| POST | `/work-orders/{id}/revert` | Revert a dispatched work order back to scheduled | Dispatcher |
| POST | `/work-orders/{id}/start` | Field tech starts the visit | FieldTech |
| POST | `/work-orders/{id}/complete` | Complete the visit (supply measured gallons for pumping/emergency) | FieldTech |
| POST | `/work-orders/{id}/cancel` | Cancel a non-terminal work order | Dispatcher |
| POST | `/work-orders/{id}/invoice` | Invoice a completed work order | Dispatcher |
| POST | `/work-orders/{id}/pay` | Record payment of an invoiced work order | Dispatcher |
| GET | `/work-orders/{id}/repair-lines` | List repair lines on a work order | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| GET | `/work-orders/{id}/inspection-reports` | List inspection reports for a work order | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/repair-lines` | Add a parts/labor line to a repair work order | Dispatcher, FieldTech |
| POST | `/routes` | Create a route for a technician and date | Dispatcher |
| GET | `/routes/{id}` | Get a route | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| GET | `/routes/{id}/work-orders` | List work orders on a route | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/routes/{id}/optimize` | Compute optimized stop order for the route | Dispatcher |
| POST | `/routes/{id}/lock` | Lock a route | Dispatcher |
| POST | `/inspection-reports` | Open a draft inspection report against a completed inspection work order | ComplianceOfficer |
| GET | `/inspection-reports/{id}` | Get an inspection report | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| PATCH | `/inspection-reports/{id}` | Edit a draft report | ComplianceOfficer |
| POST | `/inspection-reports/{id}/finalize` | Finalize a report (sets site compliance and provisional risk) | ComplianceOfficer |
| POST | `/permit-filings` | Open a draft permit filing against a finalized report | ComplianceOfficer |
| GET | `/permit-filings/{id}` | Get a permit filing | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| GET | `/permit-filings` | List permit filings (filterable) | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/permit-filings/{id}/submit` | Submit a draft permit filing to the county | ComplianceOfficer |
| POST | `/permit-filings/{id}/decide` | County decides a submitted filing | ComplianceOfficer |
| POST | `/permit-filings/{id}/reopen` | Reopen a rejected filing back to draft | ComplianceOfficer |
| GET | `/reminders/{id}` | Get a reminder | Dispatcher, ComplianceOfficer, FieldTech, Customer |
| POST | `/reminders/{id}/acknowledge` | Acknowledge a pending reminder | Dispatcher, Customer |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | Dispatcher, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_IMMUTABLE` | 409 |
| `ERR_ROUTE_LOCKED` | 409 |
| `ERR_ACCOUNT_ON_HOLD` | 409 |
| `ERR_TECH_SUSPENDED` | 409 |
| `ERR_TECH_NOT_CERTIFIED` | 409 |
| `ERR_TECH_WINDOW_CONFLICT` | 409 |
| `ERR_SITE_BUFFER_CONFLICT` | 409 |
| `ERR_OUTSIDE_SHIFT` | 409 |
| `ERR_REPORT_NOT_FINALIZED` | 409 |
| `ERR_SITE_NON_COMPLIANT` | 409 |
| `ERR_COOLING_OFF` | 409 |
| `ERR_MEASUREMENT_REQUIRED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
