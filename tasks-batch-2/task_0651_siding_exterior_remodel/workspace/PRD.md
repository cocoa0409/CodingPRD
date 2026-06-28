# Siding & Exterior Remodel API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Siding & Exterior Remodel API, the backend system that drives a James Hardie siding contractor's project workflow from the first on-site measurement through to warranty activation and financing. A remodel job is a long-running engagement: an estimator measures the home and selects a color, a project manager prices the scope and files for permits and homeowner-association clearance, materials are ordered and delivered, crews are scheduled around weather windows, change orders are negotiated and approved, and the homeowner is billed in progress draws as milestones complete.

The system is built around a single aggregate root — the **Project** — that simultaneously tracks two independent concerns: how far the physical build has progressed, and whether regulatory clearance (building permit plus, where applicable, HOA architectural approval) has been obtained. These two axes evolve separately, and several operations are gated on the state of both at once. Around the project sit the financial and operational concerns that make exterior remodeling distinctive: per-line waste factors that apply to siding but not to trim, retainage held back from each draw subject to a project-wide cap, weather thresholds that park crews on hold when wind is too high to install Hardie panels, and a strict separation between the manager who approves a draw and the finance officer who releases the cash.

This specification is the single source of truth for the implementation. It defines the data each resource carries, the precise calculations behind every dollar figure, the preconditions guarding each state transition, and the validation order that determines which error a malformed request receives.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. When either header is missing or malformed on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to invoke the endpoint under the access-control matrix of §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `Anonymous`, `Estimator`, `ProjectManager`, `HomeownerClient`, and `FinanceOfficer`.

`Anonymous` is an unauthenticated caller. Its `X-User-ID` is an opaque identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. An `Anonymous` caller may only self-register, through homeowner registration and staff registration; all other endpoints require an authenticated role.

The `Estimator`, `ProjectManager`, and `FinanceOfficer` roles are each backed by a `StaffMember`. When `X-User-Role` is `Estimator`, `ProjectManager`, or `FinanceOfficer`, the `X-User-ID` is the `id` of the acting `StaffMember`; any ownership or identity check on a resource that references a `StaffMember` compares that resource's staff foreign-key field to `X-User-ID`. In particular, when a draw is approved the approving manager's `X-User-ID` is stamped onto the draw as `approved_by_staff_id`, and at release time the releasing officer's `X-User-ID` is compared against that stored value.

The `HomeownerClient` role is backed by a `HomeownerClient` entity. When `X-User-Role` is `HomeownerClient`, the `X-User-ID` is the `id` of the acting `HomeownerClient`; ownership checks on any resource that references a homeowner (for example a project's `client_id` or a financing application's `client_id`) compare that foreign-key field to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. Requests whose pagination parameters fall outside these bounds are treated as malformed.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a system-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits, set when the resource is first created. All entities in this system additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed whenever any of the resource's fields change, and a `version` integer that starts at its initial value and increments by one on every mutation. No entity in this system is version-free; `updated_at` and `version` are present on all of them.

Recomputation of a derived field — for example refreshing a project's `contract_total_cents`, `retainage_held_cents`, or `amount_released_cents` — is itself a mutation: it refreshes `updated_at` and increments `version` on the resource it touches.

### 2.5. Optimistic Concurrency Control on the Project

Two write operations are guarded by optimistic concurrency control against the project's `version`, because both read the project's contract or cash figures and must not act on a stale view. Each such request must carry `expected_project_version`, a non-optional field carrying the version of the `Project` the caller last observed.

When a `FinanceOfficer` releases an approved progress draw, the request must include `expected_project_version` matching the target project's current `version`. If another writer has advanced the project's version since the officer last read it — for instance because a change order was just approved, legitimately advancing the contract total and bumping the version — the release is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), preventing the officer from releasing cash figures computed against a contract baseline they have not observed.

Likewise, when a `ProjectManager` approves a change order, the request must include `expected_project_version` matching the project's current `version`. If another change order has already been approved (legitimately adjusting `contract_total_cents` and bumping the project's `version`) since this approver last read the project, the approval is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), forcing the approver to refresh their view of the contract baseline first.

No other endpoint takes a version field; only draw release and change-order approval are version-checked. Project cancellation additionally requires `expected_project_version` to match (see §3.8), but its mismatch is reported through the cancellation guard rather than as a stale-version rejection.

### 2.6. Monetary Precision and Rounding

All money is stored and exchanged in integer cents. Where a calculation produces a fractional cent it is resolved with the round-half-up method to a whole cent. Measured areas (`gross_wall_sqft`, `opening_sqft`, `linear_trim_ft`, and the derived `net_siding_sqft`) are stored as numbers with two decimal places using round-half-up. The financing debt-to-income ratio `dti_ratio` is computed and stored to four decimal places, round-half-up, and the financing threshold comparison is performed on that rounded value. Material order quantities are rounded up to whole square feet, never down, because partial Hardie panels cannot be ordered.

A central rounding discipline governs estimate pricing: each line item is rounded to whole cents **before** any summation, the rounded line amounts are then summed into the subtotal, and tax is computed on that already-rounded subtotal. The system never sums raw floating-point line amounts and rounds once at the end. This per-line-then-sum-then-tax ordering is the canonical rounding order and is specified in detail in §3.3.

### 2.7. Nested Resource Retrieval and Existence

When an endpoint path contains more than one resource identifier, the identifiers are validated left to right, and the first one that does not resolve to an existing resource causes the request to fail with `ERR_NOT_FOUND` (HTTP 404) before any later identifier is examined. The same not-found rule applies to foreign keys supplied in a request body: if a referenced resource does not exist, the request is rejected with `ERR_NOT_FOUND`.

### 2.8. The Two Project Axes and Cascading Consistency

A `Project` carries two independent state fields. The `workflow_status` tracks build progress through the values `DRAFT`, `MEASURED`, `ESTIMATED`, `ORDERED`, `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED`, beginning at `DRAFT`. The `compliance_status` tracks regulatory clearance through `PENDING_CLEARANCE`, `PERMIT_FILED`, `CLEARED`, and `BLOCKED`, beginning at `PENDING_CLEARANCE`. These two axes advance on separate triggers; a project may, for example, reach `ESTIMATED` on the workflow axis while still `PENDING_CLEARANCE` on the compliance axis. Scheduling, however, is gated on both axes simultaneously, as described in §3.5.

The system maintains hierarchical consistency through cascades. When a parent resource is cancelled, dependent children are resolved automatically rather than left dangling — the project-cancellation cascade in §3.8 reaches three levels deep, and a material-order cancellation independently resolves the crew windows beneath it. Every such automatic transition is a mutation of the resource it touches and refreshes that resource's `updated_at` and `version` accordingly.

## 3. Business Logic & Workflows

### 3.1. Registration and Project Origination

Before any project work begins, the participants must exist. A homeowner self-registers as a `HomeownerClient` by supplying an `email`, a `full_name`, an `annual_income_cents` figure (self-reported annual gross income), and a `monthly_debt_cents` figure (self-reported total monthly debt obligations); the last two feed the financing gate later. The homeowner's `email` is the login identity and is unique across homeowners, compared case-insensitively after lowercasing. Staff self-register as a `StaffMember` with an `email` (likewise unique and lowercased before comparison), a `full_name`, and a `role_code` that is one of `ESTIMATOR`, `PROJECT_MANAGER`, or `FINANCE_OFFICER`. Both registration endpoints are public and return the newly created record.

A `ProjectManager` originates a remodel by creating a `Project`, supplying the `client_id` of the owning homeowner, the `project_manager_id` of the assigned manager (which must reference a `StaffMember` whose `role_code` is `PROJECT_MANAGER`), the `property_address` of the home, and an optional `hoa_required` flag indicating whether the property sits in an HOA whose architectural approval must be obtained before scheduling; `hoa_required` defaults to false when omitted. A new project starts with `workflow_status` of `DRAFT` and `compliance_status` of `PENDING_CLEARANCE`, and with its computed cash fields `contract_total_cents`, `retainage_held_cents`, and `amount_released_cents` all at zero. The `cancelled_reason` field remains null until the project is cancelled.

Projects can be listed (filtered by `client_id` or `project_manager_id`) and individually fetched, the latter exposing both status axes and the computed cash fields. A homeowner may read their own project.

### 3.2. Measurement and Net Sidable Area

An `Estimator` records the on-site measurement, which is the operation that advances a project from `DRAFT` to `MEASURED`. The estimator submits the `estimator_id` of the acting estimator (which must reference a `StaffMember` whose `role_code` is `ESTIMATOR`), the `gross_wall_sqft` (total measured exterior wall area before subtracting openings, which may not be negative), the `opening_sqft` (total square footage of windows, doors, and other openings to subtract, also non-negative), the `linear_trim_ft` (linear feet of trim such as corners, fascia, and window surrounds, non-negative), and the `color_code` (the selected James Hardie color or product SKU, for example `ARCTIC_WHITE_HZ10`). The measurement is tied to its project through the path, recorded as `project_id`.

Upon recording, the system computes `net_siding_sqft` as the gross wall area minus the opening area, with the result held at no less than zero — that is, if openings would exceed the gross wall area the net is zero rather than a negative number. Recording the first measurement requires the project to be in `DRAFT`; the side effect of a successful recording is to set the project's `workflow_status` to `MEASURED`. Measurements may be listed (filtered by `project_id` or `estimator_id`) and fetched individually.

### 3.3. Estimating: Line Items, Waste, and the Baseline

Pricing begins when an `Estimator` or `ProjectManager` creates an `Estimate` priced from a measurement, supplying the `project_id` and the `measurement_id` the pricing draws from, and an optional `waste_factor_pct` (a material waste/overage fraction, e.g. 0.10 for ten percent) that defaults to 0.10 and must be no less than zero and no greater than 0.50. An estimate begins in `DRAFT` status (the only other status is `BASELINE`). Its computed money fields `line_subtotal_cents`, `tax_cents`, and `estimate_total_cents` all begin at zero.

Scope is added one line at a time. Each `EstimateLineItem` belongs to its estimate (recorded as `estimate_id`) and prices a single `scope_kind`, which is one of `SIDING`, `TRIM`, or `WRAP`. The line carries a `quantity` (which must be strictly greater than zero, expressed in square feet for `SIDING` and `WRAP` and in linear feet for `TRIM`) and a `unit_price_cents` (price per unit in cents, which may not be negative). The system then computes the line's `extended_cents`. For a `SIDING` line, the effective quantity is the `quantity` multiplied by one plus the estimate's `waste_factor_pct` — waste applies to siding only. For a `TRIM` or `WRAP` line, the effective quantity is simply the `quantity`, with no waste multiplier. The `extended_cents` is the effective quantity multiplied by `unit_price_cents`, rounded half-up to a whole cent at the level of the individual line, before any summation.

Adding a line item recomputes the estimate's totals. The `line_subtotal_cents` is the sum of every `extended_cents` across all line items whose `estimate_id` is this estimate — line items have no lifecycle of their own, so no status filter applies. Sales tax is then computed on that already-per-line-rounded subtotal: the `tax_cents` is the subtotal multiplied by the sales tax rate of 8.25 percent (0.0825), rounded half-up to a whole cent. The `estimate_total_cents` is the `line_subtotal_cents` plus the `tax_cents`. This evaluation order is mandatory — round each line first, sum the rounded lines into the subtotal, then apply tax to that subtotal — and produces the canonical total; a raw float sum taxed once at the end is incorrect.

A `ProjectManager` promotes an estimate to the contract baseline, which advances the project from `MEASURED` to `ESTIMATED`. Baseline promotion requires the project to be in `MEASURED`, the estimate to hold at least one `EstimateLineItem` (an estimate with zero line items cannot become baseline and is rejected with `ERR_EMPTY_ESTIMATE`, HTTP 422), and no other `BASELINE` estimate to already exist for the project — a second baseline attempt is rejected with `ERR_BASELINE_EXISTS` (HTTP 409) rather than superseding the first. On success the estimate's `status` becomes `BASELINE`, the project's `workflow_status` becomes `ESTIMATED`, the project's `contract_total_cents` is set equal to this estimate's `estimate_total_cents`, and the system creates two `PENDING` warranty rows for the project — one per `warranty_kind`, namely `LIFETIME_MATERIAL` and `WORKMANSHIP`. Estimates and line items can be listed (estimates filtered by `project_id` or `measurement_id`, line items by `estimate_id`) and fetched individually.

### 3.4. Permits, HOA, and the Compliance Axis

Regulatory clearance advances on the compliance axis, driven by the `ProjectManager`. Filing a building permit moves the project's `compliance_status` from `PENDING_CLEARANCE` to `PERMIT_FILED`: the manager supplies the `project_id` and the `jurisdiction` (the issuing municipality or building department), and the system creates a `Permit` in `FILED` status. A permit's lifecycle runs `FILED`, `ISSUED`, `REJECTED`. Filing requires the project to currently be `PENDING_CLEARANCE`.

Issuing the permit advances the project to `CLEARED`. Issuance requires the project to be `PERMIT_FILED`, the permit itself to be `FILED`, and — only when the project's `hoa_required` is true — an `HOAApproval` in `APPROVED` status to already exist for the project. The manager supplies the municipality-assigned `permit_number` at issuance; on success the permit's `status` becomes `ISSUED`, the `permit_number` is recorded, and the project's `compliance_status` becomes `CLEARED`. Permits may be listed (filtered by `project_id`) and fetched.

The HOA review runs in parallel. A `ProjectManager` or `HomeownerClient` submits an `HOAApproval`, supplying the `project_id` and the `reviewed_color_code` (the color or product SKU presented to the association). The review begins in `SUBMITTED` status (lifecycle `SUBMITTED`, `APPROVED`, `DENIED`) and may be approved or denied. HOA approvals can be listed (filtered by `project_id`) and fetched.

The compliance axis can be blocked from either gate. Rejecting a permit (when the project is in `PENDING_CLEARANCE` or `PERMIT_FILED`) sets that permit's `status` to `REJECTED` and the project's `compliance_status` to `BLOCKED`. Symmetrically, denying an HOA review sets that approval's `status` to `DENIED` and likewise drives the project's `compliance_status` to `BLOCKED`. Both block transitions require the project's `compliance_status` to currently be either `PENDING_CLEARANCE` or `PERMIT_FILED`.

### 3.5. Material Ordering and Delivery

Once a baseline exists, a `ProjectManager` places the material order, which advances the project from `ESTIMATED` to `ORDERED`. The order is created against the project (`project_id`) and the `BASELINE` estimate (`estimate_id`) whose siding line drives the quantity. Placement requires the project to be `ESTIMATED` and a `BASELINE` estimate to exist. A `MaterialOrder` begins in `PLACED` status; its lifecycle is `PLACED`, `CONFIRMED`, `BACKORDERED`, `DELIVERED`, and `CANCELLED`.

At placement the system computes `ordered_sqft`: the net sidable area of the measurement linked to the baseline estimate, multiplied by one plus the estimate's `waste_factor_pct`, then rounded up to a whole square foot. The placement side effects are to create the order and set the project's `workflow_status` to `ORDERED`.

Confirmation, delivery, and backorder follow. Confirming a `PLACED` order requires a `delivery_eta_iso` (a promised delivery date and time as an ISO 8601 UTC instant) to be supplied; the order's `status` becomes `CONFIRMED` and the ETA is recorded. From `CONFIRMED`, the order may either be delivered or pushed to backorder. Backordering a confirmed order sets its `status` to `BACKORDERED` and pushes `delivery_eta_iso` to a revised date. Delivery — recordable from either `CONFIRMED` or `BACKORDERED` — sets the `status` to `DELIVERED`, but only when the server's current logical clock has reached or passed the promised `delivery_eta_iso`; recording delivery before that instant is rejected with `ERR_DELIVERY_TOO_EARLY` (HTTP 409). An order in `PLACED`, `CONFIRMED`, or `BACKORDERED` may be cancelled, which sets its `status` to `CANCELLED` and cascades to set every `PROPOSED` or `CONFIRMED` `WorkSchedule` for the project to `CANCELLED`. Material orders may be listed (filtered by `project_id` or `estimate_id`) and fetched.

### 3.6. Crews, Work Windows, and Weather

Crews and their work windows are the operational heart of scheduling. A `ProjectManager` first creates a `Crew` with a `name` (call sign) and an optional `max_wind_mph` threshold — the maximum forecast wind at which the crew will install Hardie panels — that defaults to 25 and must be strictly greater than zero. A `WorkSchedule` is then proposed for a project, naming the assigned `crew_id`, the `milestone` it represents (one of `WRAP_INSTALL`, `SIDING_INSTALL`, or `TRIM_FINISH`, which later governs draw eligibility), a `window_start_iso` and `window_end_iso` defining the crew's time window as a half-open interval (start inclusive, end exclusive), and the `forecast_wind_mph` (forecast peak wind for the window, non-negative). The window is tied to its project as `project_id` and starts in `PROPOSED` status; its lifecycle is `PROPOSED`, `CONFIRMED`, `COMPLETED`, `CANCELLED`, and `WEATHER_HOLD`.

Confirmation is the most heavily guarded transition in the system, and it is also weather-branching. When a `ProjectManager` confirms a `PROPOSED` window whose `forecast_wind_mph` exceeds the assigned crew's `max_wind_mph`, the window is not confirmed; instead its `status` is parked at `WEATHER_HOLD`. When the forecast wind is at or below the crew's `max_wind_mph` and all other gates pass, the window's `status` becomes `CONFIRMED`, and as an additional side effect, if the project's `workflow_status` is `ORDERED` it advances to `SCHEDULED`.

A confirmation that proceeds on acceptable wind must clear four further gates, each with its own rejection code:

- **Compliance gate.** The project's `compliance_status` must be `CLEARED`; otherwise the confirmation is rejected with `ERR_COMPLIANCE_NOT_CLEARED` (HTTP 409).
- **Material gate.** The project's `MaterialOrder` must be `DELIVERED`; otherwise the confirmation is rejected with `ERR_MATERIAL_NOT_DELIVERED` (HTTP 409).
- **Crew double-booking gate.** The window's half-open interval, from `window_start_iso` inclusive to `window_end_iso` exclusive, must not overlap any other `CONFIRMED` window for the same `crew_id`. Because the interval is half-open and carries no buffer, adjacency is permitted — one window ending exactly when the next begins does not collide. An overlap is rejected with `ERR_CREW_OVERLAP` (HTTP 409).
- **Site sequencing gate.** The window, expanded by a 24-hour buffer on each side and then treated as a closed interval, must not overlap or even touch any other `CONFIRMED` window for the same `project_id` — a single home site hosts only one trade crew at a time, with a mandatory 24-hour gap between trades. A conflict is rejected with `ERR_SITE_WINDOW_CONFLICT` (HTTP 409). Note the deliberate contrast with the crew gate: the crew gate is scoped to `crew_id`, uses half-open intervals, and allows adjacency with no buffer; the site gate is scoped to `project_id`, uses closed intervals, and expands each window by 24 hours on both sides so that even touching windows conflict.

A window parked at `WEATHER_HOLD` can be re-evaluated by the `ProjectManager` against a revised forecast: the manager supplies a new `forecast_wind_mph`, and if it is at or below the crew's `max_wind_mph` and all the same four gates above pass, the window updates its `forecast_wind_mph` and its `status` becomes `CONFIRMED` (again advancing the project from `ORDERED` to `SCHEDULED` as a side effect). Re-weathering a held window whose revised `forecast_wind_mph` is still greater than the crew's `max_wind_mph` is rejected with `ERR_WIND_EXCEEDS_LIMIT` (HTTP 409). The compliance, material, crew-overlap, and site-sequencing gates apply equally to the confirm and re-weather operations.

Once confirmed, a window can be started or completed. Starting a `CONFIRMED` window advances the project from `SCHEDULED` to `IN_PROGRESS` (the start requires the project to be `SCHEDULED` and the window `CONFIRMED`). Completing a window requires the window to be `CONFIRMED` and the project to be `IN_PROGRESS`, and sets the window's `status` to `COMPLETED`. A window in `PROPOSED`, `CONFIRMED`, or `WEATHER_HOLD` may be cancelled, setting its `status` to `CANCELLED`; this cascades to set any `ProgressDraw` on that window in `REQUESTED` or `APPROVED` status to `REJECTED`, and it frees the crew and site occupancy the window had held — a window that was previously blocking an overlapping candidate no longer does so once cancelled, so the candidate becomes confirmable again. Work schedules may be listed (filtered by `project_id` or `crew_id`) and fetched; crews may be fetched individually.

### 3.7. Change Orders and the Negotiation Cycle

A change order adjusts the contract after the baseline is set. A `ProjectManager` or `HomeownerClient` submits a `ChangeOrder` referencing the `project_id` it modifies, the `target_line_item_id` (the baseline `EstimateLineItem` it adjusts, a cross-aggregate reference), a signed `delta_cents` (cents added to the contract when positive, removed when negative), and an optional `supersedes_change_order_id` naming the prior change order this revision supersedes in a revision chain (null for an original). A change order begins in `SUBMITTED` status; its full set of states is `SUBMITTED`, `NEGOTIATING`, `APPROVED`, `REJECTED`, and `WITHDRAWN`, and it tracks two sign-off booleans, `pm_approved` and `client_approved`, both starting false.

The negotiation cycle is genuinely cyclic. From `SUBMITTED`, a `HomeownerClient` may move the change order into `NEGOTIATING`, provided the parent project's `workflow_status` is neither `COMPLETED` nor `CANCELLED`; entering negotiation resets both `pm_approved` and `client_approved` to false. From `NEGOTIATING`, a `ProjectManager` revises the proposal, supplying a new `delta_cents` and returning the change order to `SUBMITTED`; the loop may repeat any number of rounds. Sign-off is recorded by a self-loop on the `SUBMITTED` state that does not change the status: when a `ProjectManager` signs, `pm_approved` becomes true; when a `HomeownerClient` signs, `client_approved` becomes true. A `HomeownerClient` may withdraw a change order from either `SUBMITTED` or `NEGOTIATING`, setting its `status` to `WITHDRAWN`. A `ProjectManager` may reject a `SUBMITTED` change order, setting its `status` to `REJECTED`.

Approval is the consequential transition. A `ProjectManager` approves a `SUBMITTED` change order only when both `pm_approved` and `client_approved` are true — approving before both sign-offs are present is rejected with `ERR_DUAL_SIGNOFF_INCOMPLETE` (HTTP 409) — and only when the parent project's `workflow_status` is neither `COMPLETED` nor `CANCELLED`. Approval also carries the optimistic-concurrency requirement of §2.5: the request must supply `expected_project_version` matching the project's current `version`, failing with `ERR_STALE_PROJECT_VERSION` (HTTP 412) on a mismatch. On a successful approval the change order's `status` becomes `APPROVED`, the project's `contract_total_cents` is recomputed (see §3.9), the target `EstimateLineItem`'s `extended_cents` is adjusted by the `delta_cents`, and the project's `version` is incremented by one. Change orders may be listed (filtered by `project_id`, `target_line_item_id`, or `supersedes_change_order_id`) and fetched.

### 3.8. Project Completion and Cancellation

Completion is the terminal success state of the workflow axis. A `ProjectManager` marks a project `COMPLETED` only when the project is `IN_PROGRESS`, every `WorkSchedule` for the project is either `COMPLETED` or `CANCELLED`, and every `ProgressDraw` for the project is either `RELEASED` or `REJECTED` — none may remain `REQUESTED` or `APPROVED`. A completion attempt with any open window or open draw is rejected with `ERR_OPEN_MILESTONES` (HTTP 409). On success the project's `workflow_status` becomes `COMPLETED`, every `PENDING` warranty row is activated to `ACTIVE`, and the project's residual retainage is released: the still-held retainage amount is added to `amount_released_cents` and `retainage_held_cents` is then set back to zero.

Cancellation is the terminal abort, available while the project's `workflow_status` is none of `IN_PROGRESS`, `COMPLETED`, or `CANCELLED` (that is, while it is `DRAFT`, `MEASURED`, `ESTIMATED`, `ORDERED`, or `SCHEDULED`). The `ProjectManager` supplies a non-empty `cancelled_reason` and an `expected_project_version`; a cancellation attempt on an ineligible status, or one omitting the `cancelled_reason`, is rejected with `ERR_CANCEL_NOT_ALLOWED` (HTTP 409). Cancellation triggers a three-level cascade: the project's `workflow_status` becomes `CANCELLED`; every non-terminal material order (one in `PLACED`, `CONFIRMED`, or `BACKORDERED`) becomes `CANCELLED`; each such material-order cancellation in turn sets every `PROPOSED` or `CONFIRMED` work schedule for the project to `CANCELLED`; and each cancelled work schedule in turn sets any `REQUESTED` or `APPROVED` progress draw on it to `REJECTED`. Cancellation also voids every `PENDING` warranty row to `VOID` and increments the project's `version` by one.

### 3.9. The Contract Total and Its Evaluation Order

The realized contract total is the financial spine of the project. When an estimate becomes baseline, `contract_total_cents` is set to that estimate's `estimate_total_cents`. Thereafter, on every change-order approval, `contract_total_cents` is recomputed as the baseline estimate total plus the sum of `delta_cents` across every change order on the project whose `status` is `APPROVED`.

The evaluation order is pinned and matters for billing. The contract total is recomputed at the moment a change order is approved, before any subsequent draw approval reads it. A progress draw that is approved after a change-order approval prices its gross against the new contract total; a draw that was already approved before that change order keeps the gross amount frozen at its approval-time value. Later change orders never retroactively re-bill a draw that was already approved or released.

### 3.10. Progress Draws, Retainage, and the Cash Ledger

Progress draws bill the homeowner as milestones complete, and they are the most financially intricate workflow. A `ProjectManager` requests a `ProgressDraw` against a completed milestone window, supplying the `work_schedule_id` of that window (a cross-aggregate reference) and a `milestone_pct` — the percent of the contract this milestone bills, which must be strictly greater than zero and no greater than one. The draw is tied to the project as `project_id` and begins in `REQUESTED` status; its lifecycle is `REQUESTED`, `APPROVED`, `RELEASED`, `CLAWED_BACK`, and `REJECTED`. Its computed money fields `gross_amount_cents`, `retainage_cents`, and `net_released_cents` begin at zero, and `approved_by_staff_id` is null until approval.

A `ProjectManager` approves a `REQUESTED` draw only when the referenced `WorkSchedule` is `COMPLETED` (otherwise rejected with `ERR_MILESTONE_INCOMPLETE`, HTTP 409) and the project is `IN_PROGRESS`. Approval sets the draw's `status` to `APPROVED`, stamps `approved_by_staff_id` with the approving manager's `X-User-ID`, and computes the three cash figures as follows. The `gross_amount_cents` is the project's `contract_total_cents` multiplied by this draw's `milestone_pct`, rounded half-up to whole cents. A raw retainage of ten percent (the retainage rate, 0.10) of the gross is then computed, rounded half-up. Retainage is capped cumulatively across the project: the total retainage ever held may not exceed five percent (the retainage cap rate, 0.05) of the contract total. The cap total is therefore five percent of `contract_total_cents` rounded half-up; the headroom available to this draw is the cap total minus the project's current `retainage_held_cents`, held at no less than zero. The `retainage_cents` actually withheld on this draw is the smaller of the raw retainage and that headroom — earlier draws fill the cap first, and once the cap is full a later draw withholds nothing. The `net_released_cents` is the `gross_amount_cents` minus the `retainage_cents`. When the headroom comfortably covers the raw retainage, the full raw retainage is withheld; when it would not, only the remaining headroom is withheld and the rest flows through as released cash.

Release is segregated by duty and version-guarded. Only a `FinanceOfficer` releases an `APPROVED` draw, and the releasing officer's `X-User-ID` must not equal the draw's `approved_by_staff_id` — the officer who releases the cash may not be the manager who approved the draw; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The release request must carry `expected_project_version` matching the project's current `version` per §2.5, failing with `ERR_STALE_PROJECT_VERSION` (HTTP 412) on a mismatch. On release the draw's `status` becomes `RELEASED`, the project's `amount_released_cents` is increased by this draw's `net_released_cents`, its `retainage_held_cents` is increased by this draw's `retainage_cents`, and the project's `version` is incremented by one.

A released draw can be clawed back by a `FinanceOfficer`, which exactly reverses the release. Clawback requires the draw to be `RELEASED` and `expected_project_version` to match the project's current `version`; on success the draw's `status` becomes `CLAWED_BACK`, the project's `amount_released_cents` is decreased by the draw's `net_released_cents`, its `retainage_held_cents` is decreased by the draw's `retainage_cents`, and the project's `version` is incremented by one. A `ProjectManager` may instead reject a draw that is still `REQUESTED` or `APPROVED`, setting its `status` to `REJECTED`. Progress draws may be listed (filtered by `project_id` or `work_schedule_id`) and fetched, the latter exposing the computed gross, retainage, and net figures.

### 3.11. Warranties and Financing

Two warranty rows are created automatically when an estimate becomes baseline, one for each `warranty_kind`: `LIFETIME_MATERIAL` and `WORKMANSHIP`. Each `Warranty` is tied to its project as `project_id`, begins in `PENDING` status (lifecycle `PENDING`, `ACTIVE`, `VOID`), and carries a `workmanship_years` term in years used by the `WORKMANSHIP` warranty and ignored by `LIFETIME_MATERIAL`; `workmanship_years` defaults to zero. Warranties activate to `ACTIVE` when the project completes and are voided to `VOID` when the project is cancelled, as described in §3.8. Warranties may be listed (filtered by `project_id`) and fetched.

Financing closes the loop. A `HomeownerClient` or `ProjectManager` submits a `FinancingApplication` naming the `project_id` it would fund, the `client_id` of the applying homeowner, a `requested_amount_cents` loan principal (strictly greater than zero), and a `term_months` repayment term that must be one of 60, 120, or 180. The application begins in `SUBMITTED` status (lifecycle `SUBMITTED`, `APPROVED`, `DECLINED`) with computed `monthly_payment_cents` and `dti_ratio` both at zero. A `term_months` outside the allowed set, a `milestone_pct` outside its zero-to-one range, or a `waste_factor_pct` outside its zero-to-0.50 range are all numeric-range violations reported as `ERR_VALIDATION_RANGE` (HTTP 422).

A `FinanceOfficer` decides the application, computing first the monthly payment, then the debt-to-income ratio, then applying the gates. The monthly payment is a standard amortized payment at the APR tier selected by the term: the annual percentage rate is 5.99 percent (0.0599) for a 60-month term, 7.99 percent (0.0799) for a 120-month term, and 9.99 percent (0.0999) for a 180-month term. The monthly interest rate is that annual rate divided by twelve. When the monthly rate is zero, the `monthly_payment_cents` is the principal divided by the number of months, rounded up to whole cents. Otherwise the `monthly_payment_cents` is the principal multiplied by the monthly rate multiplied by the quantity one plus the monthly rate raised to the power of the number of months, all divided by the quantity one plus the monthly rate raised to the power of the number of months minus one; the lender rounds the result up to whole cents.

The `dti_ratio` is then computed: the homeowner's monthly income is the applicant's `annual_income_cents` divided by twelve, and the ratio is the sum of the applicant's `monthly_debt_cents` and the just-computed `monthly_payment_cents`, divided by that monthly income, rounded half-up to four decimal places. Two gates decide the outcome, both compared on the rounded ratio. The application is declined with `ERR_DTI_EXCEEDED` (HTTP 422) when the `dti_ratio` is strictly greater than the DTI maximum of 0.43; it is approved when the ratio is at or below 0.43. Independently, the application is declined with `ERR_PRINCIPAL_EXCEEDS_CONTRACT` (HTTP 422) when the `requested_amount_cents` exceeds the project's `contract_total_cents`. An application passing both gates moves to `APPROVED`; otherwise it moves to `DECLINED`. Financing applications may be listed (filtered by `project_id` or `client_id`) and fetched, the latter exposing the computed `monthly_payment_cents` and `dti_ratio`.

### 3.12. Validation Order and the Logical Clock

When several checks could reject a single request, they are evaluated in a fixed priority order, so the returned error is deterministic. Authentication of the headers comes first: a missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_UNAUTHENTICATED`. Role authorization comes next: a caller whose role is not permitted for the endpoint yields `ERR_FORBIDDEN_ROLE`. The segregation-of-duties check on draw release comes third, so that a same-person release is caught as `ERR_SEGREGATION_OF_DUTIES` before existence checks. Existence is then verified — path identifiers left to right and body foreign keys — yielding `ERR_NOT_FOUND`. Request well-formedness follows: a missing required field, a bad type, an enum value outside its set, or a numeric range violation yields `ERR_INVALID_REQUEST` (HTTP 400). State-machine admissibility comes next: a target resource not in a state from which the requested transition is allowed yields `ERR_INVALID_STATE` (HTTP 409). Only after all of these do the domain-specific business rules described throughout §3 apply — baseline uniqueness and emptiness, the compliance and material gates, the weather threshold, the crew and site interval rules, the delivery-timing rule, dual sign-off, milestone completeness, the financing DTI and principal gates, the stale-version check, the open-milestones completion gate, and the cancellation guard — each in the order their respective workflows imply.

To make the time-dependent gates deterministic, an authorized `ProjectManager` or `FinanceOfficer` may set the server's logical clock to an arbitrary UTC instant by supplying a `to_iso8601` value. The server's startup default clock reads exactly 2026-04-01T00:00:00Z; before any clock is set it holds that default and never falls back to real wall-clock time. The logical clock is what the delivery-timing gate compares `delivery_eta_iso` against in §3.5.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource — including every state transition and every action endpoint — return `200 OK`. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients/register` | Register a HomeownerClient | Anonymous |
| GET | `/clients/{id}` | Fetch a HomeownerClient | ProjectManager, FinanceOfficer, HomeownerClient |
| POST | `/staff/register` | Register a StaffMember | Anonymous |
| GET | `/staff/{id}` | Fetch a StaffMember | ProjectManager, FinanceOfficer, Estimator |
| POST | `/projects` | Create a remodel Project | ProjectManager |
| GET | `/projects` | List projects | ProjectManager, FinanceOfficer |
| GET | `/projects/{id}` | Fetch a Project with both status axes and cash fields | ProjectManager, FinanceOfficer, HomeownerClient |
| POST | `/projects/{id}/complete` | Complete a project; activate warranties, release residual retainage | ProjectManager |
| POST | `/projects/{id}/cancel` | Cancel a project (depth-3 cascade, OCC-guarded) | ProjectManager |
| POST | `/projects/{id}/measurements` | Record an on-site measurement | Estimator |
| GET | `/measurements/{id}` | Fetch a Measurement | ProjectManager, FinanceOfficer, Estimator |
| GET | `/measurements` | List measurements | ProjectManager, FinanceOfficer, Estimator |
| POST | `/estimates` | Create a DRAFT Estimate | Estimator, ProjectManager |
| GET | `/estimates/{id}` | Fetch an Estimate | ProjectManager, FinanceOfficer, Estimator, HomeownerClient |
| GET | `/estimates` | List estimates | ProjectManager, FinanceOfficer, Estimator |
| POST | `/estimates/{id}/line-items` | Add a scope line item; recompute totals | Estimator, ProjectManager |
| GET | `/line-items/{id}` | Fetch a single EstimateLineItem | ProjectManager, FinanceOfficer, Estimator |
| GET | `/line-items` | List line items | ProjectManager, FinanceOfficer, Estimator, HomeownerClient |
| POST | `/estimates/{id}/baseline` | Promote an estimate to BASELINE | ProjectManager |
| POST | `/permits` | File a building permit | ProjectManager |
| GET | `/permits/{id}` | Fetch a Permit | ProjectManager, FinanceOfficer |
| GET | `/permits` | List permits | ProjectManager, FinanceOfficer |
| POST | `/permits/{id}/issue` | Issue the permit; advance compliance to CLEARED | ProjectManager |
| POST | `/permits/{id}/reject` | Reject the permit; block compliance | ProjectManager |
| POST | `/hoa-approvals` | Submit an HOA architectural review | ProjectManager, HomeownerClient |
| GET | `/hoa-approvals/{id}` | Fetch an HOAApproval | ProjectManager, FinanceOfficer, HomeownerClient |
| GET | `/hoa-approvals` | List HOA approvals | ProjectManager, FinanceOfficer, HomeownerClient |
| POST | `/hoa-approvals/{id}/approve` | Approve the submitted color/scope | HomeownerClient, ProjectManager |
| POST | `/hoa-approvals/{id}/deny` | Deny the review; block compliance | HomeownerClient, ProjectManager |
| POST | `/material-orders` | Place a material order; advance to ORDERED | ProjectManager |
| GET | `/material-orders/{id}` | Fetch a MaterialOrder | ProjectManager, FinanceOfficer |
| GET | `/material-orders` | List material orders | ProjectManager, FinanceOfficer |
| POST | `/material-orders/{id}/confirm` | Confirm an order with a delivery ETA | ProjectManager |
| POST | `/material-orders/{id}/backorder` | Backorder a confirmed order with a revised ETA | ProjectManager |
| POST | `/material-orders/{id}/deliver` | Record delivery (clock-gated) | ProjectManager |
| POST | `/material-orders/{id}/cancel` | Cancel a non-delivered order; cascade schedules | ProjectManager |
| POST | `/change-orders` | Submit a change order | ProjectManager, HomeownerClient |
| GET | `/change-orders/{id}` | Fetch a ChangeOrder | ProjectManager, FinanceOfficer, HomeownerClient |
| GET | `/change-orders` | List change orders | ProjectManager, FinanceOfficer, HomeownerClient |
| POST | `/change-orders/{id}/sign` | Record a sign-off | ProjectManager, HomeownerClient |
| POST | `/change-orders/{id}/negotiate` | Move to NEGOTIATING; reset sign-offs | HomeownerClient |
| POST | `/change-orders/{id}/revise` | Propose a revised delta; return to SUBMITTED | ProjectManager |
| POST | `/change-orders/{id}/approve` | Approve a dual-signed change order (OCC-guarded) | ProjectManager |
| POST | `/change-orders/{id}/reject` | Reject a submitted change order | ProjectManager |
| POST | `/change-orders/{id}/withdraw` | Withdraw a change order | HomeownerClient |
| POST | `/crews` | Create a crew with a wind threshold | ProjectManager |
| GET | `/crews/{id}` | Fetch a Crew | ProjectManager, FinanceOfficer |
| POST | `/projects/{id}/work-schedules` | Propose a crew work window | ProjectManager |
| GET | `/work-schedules/{id}` | Fetch a WorkSchedule | ProjectManager, FinanceOfficer |
| GET | `/work-schedules` | List work schedules | ProjectManager, FinanceOfficer |
| POST | `/work-schedules/{id}/confirm` | Confirm a window (weather/overlap/compliance/material gates) | ProjectManager |
| POST | `/work-schedules/{id}/reweather` | Re-evaluate a WEATHER_HOLD window and confirm | ProjectManager |
| POST | `/work-schedules/{id}/start` | Start a confirmed window; advance to IN_PROGRESS | ProjectManager |
| POST | `/work-schedules/{id}/complete` | Complete a milestone window | ProjectManager |
| POST | `/work-schedules/{id}/cancel` | Cancel a window; cascade draws to REJECTED | ProjectManager |
| POST | `/projects/{id}/progress-draws` | Request a progress draw | ProjectManager |
| GET | `/progress-draws/{id}` | Fetch a ProgressDraw with computed gross/retainage/net | ProjectManager, FinanceOfficer |
| GET | `/progress-draws` | List progress draws | ProjectManager, FinanceOfficer |
| POST | `/progress-draws/{id}/approve` | Approve a draw; compute gross/retainage/net | ProjectManager |
| POST | `/progress-draws/{id}/release` | Release an approved draw (segregation + OCC) | FinanceOfficer |
| POST | `/progress-draws/{id}/clawback` | Claw back a released draw (OCC-guarded) | FinanceOfficer |
| POST | `/progress-draws/{id}/reject` | Reject a requested/approved draw | ProjectManager |
| GET | `/warranties/{id}` | Fetch a Warranty | ProjectManager, FinanceOfficer, HomeownerClient |
| GET | `/warranties` | List warranties | ProjectManager, FinanceOfficer, HomeownerClient |
| POST | `/financing-applications` | Submit a financing application | HomeownerClient, ProjectManager |
| GET | `/financing-applications/{id}` | Fetch a FinancingApplication with computed payment/DTI | FinanceOfficer, HomeownerClient, ProjectManager |
| GET | `/financing-applications` | List financing applications | FinanceOfficer, HomeownerClient, ProjectManager |
| POST | `/financing-applications/{id}/decide` | Decide the application; compute payment and DTI, apply gates | FinanceOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a UTC instant | ProjectManager, FinanceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BASELINE_EXISTS` | 409 |
| `ERR_EMPTY_ESTIMATE` | 422 |
| `ERR_COMPLIANCE_NOT_CLEARED` | 409 |
| `ERR_MATERIAL_NOT_DELIVERED` | 409 |
| `ERR_WIND_EXCEEDS_LIMIT` | 409 |
| `ERR_CREW_OVERLAP` | 409 |
| `ERR_SITE_WINDOW_CONFLICT` | 409 |
| `ERR_DELIVERY_TOO_EARLY` | 409 |
| `ERR_DUAL_SIGNOFF_INCOMPLETE` | 409 |
| `ERR_MILESTONE_INCOMPLETE` | 409 |
| `ERR_DTI_EXCEEDED` | 422 |
| `ERR_PRINCIPAL_EXCEEDS_CONTRACT` | 422 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_OPEN_MILESTONES` | 409 |
| `ERR_CANCEL_NOT_ALLOWED` | 409 |
| `ERR_VALIDATION_RANGE` | 422 |
