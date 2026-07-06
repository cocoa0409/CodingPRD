# Foundation Repair API — Product Requirements Document

## 1. Introduction

This document specifies the Foundation Repair & Structural Stabilization API, the system of record for a residential foundation-repair contractor. The business runs a long, multi-party pipeline: a free inspection and soil/crack assessment, an engineered scope that fixes pier and anchor counts, a priced quote with financing, permitting and crew scheduling, the physical install and lift adjustment, a transferable lifetime warranty with an annual re-tightening visit, and finally the callback/claim path that can spawn a remediation job. Each stage is owned by a different operational role, and the money, the schedule, and the structural-safety guarantees all have to stay consistent as work moves down the line.

The API exists to make that consistency mechanical rather than manual. Pricing is computed twice — once as an estimate when a quote is sent and once as a final figure when the install completes — and the two variants must agree except where the crew installed a different number of piers than engineered. Warranties, maintenance visits, financing balances, and crew utilization are all derived quantities that the server maintains through cascading side effects, so that a single "complete the install" action correctly activates a warranty, books the first maintenance visit, and updates the homeowner's outstanding financed balance without any of those being a separate client call. Because so many rules depend on the passage of time (quote expiry, visit spacing, overdue visits), the server runs on an explicit logical clock rather than wall-clock time, making every temporal rule deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. All resources are peer collections mounted under the shared `/foundation` prefix; there is no deep URL nesting, and entity relationships are carried by foreign-key fields rather than nested paths.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the call is made. A request missing `X-User-Role`, or presenting a value that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly six roles: `SalesAgent`, `FieldEngineer`, `OpsCoordinator`, `ClaimsAdjuster`, `Customer`, and `Admin`. When a recognized role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN`.

Each role owns a distinct slice of the pipeline. A `SalesAgent` owns lead intake, inspection booking, quote creation, quote sending, and quote revision. A `FieldEngineer` completes inspections and authors and finalizes engineered scopes. An `OpsCoordinator` manages permits, crew scheduling, the install lifecycle, and maintenance visits. A `ClaimsAdjuster` reviews, decides, and resolves warranty claims. A `Customer` is the homeowner and acts only on quote acceptance/rejection, claim filing, claim resubmission, and warranty transfer. An `Admin` performs operational overrides: crew management, warranty voiding, and advancing the logical clock. All six roles may perform any GET read.

Five of the six roles carry an **opaque** identity: when `X-User-Role` is `SalesAgent`, `FieldEngineer`, `OpsCoordinator`, `ClaimsAdjuster`, or `Admin`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it but never compares it to any entity's `id`. The `Customer` role is **entity-backed**: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Lead`. Ownership is then enforced on every customer-scoped mutation — the caller's `X-User-ID` must equal the `Lead.id` that owns the target resource. For a quote that is the quote's `lead_id`; for a warranty that is the warranty's `lead_id`; for a claim it is resolved through the claim's warranty to that warranty's `lead_id`. A customer acting on a resource belonging to a different lead is rejected with `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is clamped to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped to 0, and a `limit` or `offset` that is not a valid integer is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every entity in this system is a top-level resource and carries the standard system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every subsequent mutation of the resource. `version` is an integer that starts at 1 on creation and increments by one on every mutation; it is the basis for optimistic concurrency control (see §2.7). Every entity here — `Lead`, `Inspection`, `EngineeringScope`, `Quote`, `Job`, `Crew`, `Permit`, `Warranty`, `MaintenanceVisit`, and `Claim` — exposes all four of these fields.

Each entity that runs a lifecycle state machine exposes its current state in a `status` field — this applies to `Inspection`, `EngineeringScope`, `Quote`, `Permit`, `Warranty`, `MaintenanceVisit`, and `Claim`. The one exception is `Job`, which tracks two independent state dimensions in separate `fulfillment_status` and `permit_status` fields instead of a single `status`.

A resource's `version` and `updated_at` advance not only on direct client mutations but also on server-driven ones. When a cascade or a compensating adjustment writes a derived field — for example refreshing a `Lead`'s `financing_balance_cents`, a `Crew`'s `booked_minutes`, or a `Warranty`'s `remediation_count` — that write is itself a mutation of the affected resource and bumps its `version` and `updated_at`.

### 2.5. The Logical Clock and Temporal Determinism

Every time-dependent rule in this system is evaluated against a server-maintained **logical clock**, never against wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client advances it the clock continues to read that default. An `Admin` may move the clock to any supplied `to_iso8601` instant; doing so is the mechanism by which quote expiry, visit-spacing buffers, and overdue-visit rules become observable. Advancing the clock past a sent quote's `expires_at` means that quote is treated as expired for the purposes of acceptance. All timestamps the system stamps (`created_at`, `updated_at`, `activated_at`, and any computed instant such as `expires_at`) are drawn from this logical clock.

### 2.6. Resource Resolution and Reverse Lookups

Requests are validated left to right. Any identifier that appears in the URL path — a `lead_id`, `inspection_id`, `scope_id`, `quote_id`, `job_id`, `crew_id`, `permit_id`, `warranty_id`, `visit_id`, or `claim_id` — and any foreign-key identifier supplied in a request body must resolve to an existing resource; the first identifier that does not resolve causes the request to be rejected with `ERR_NOT_FOUND` before any business rule runs.

Because the topology is flat, cross-entity navigation is done through reverse-lookup list filters rather than nested paths. Leads may be filtered by `region_code`; inspections by `lead_id`; scopes by `lead_id` or `inspection_id`; quotes by `lead_id` or `scope_id`; jobs by `lead_id`, `quote_id`, `crew_id`, or `source_claim_id`; crews by `region_code`; permits by `job_id`; warranties by `lead_id` or `job_id`; maintenance visits by `warranty_id` or `crew_id`; and claims by `warranty_id` or `remediation_job_id`.

### 2.7. Optimistic Concurrency on Scope Creation

Creating an engineered scope is the one write in this system guarded by optimistic concurrency control, because a new scope legitimately supersedes any prior scope on the same lead and therefore advances the lead's `version`. A scope-creation request must carry `expected_lead_version`, and this field is required — it is not optional. The server compares it against the target `Lead`'s current `version`. If another writer has already created a superseding scope (and thereby advanced the lead's `version`) since this client last read the lead, the supplied `expected_lead_version` no longer matches the lead's current `version`, the caller's view is stale, and the creation is rejected with `ERR_STALE_VERSION` at HTTP 412. No other endpoint accepts or requires a version field.

### 2.8. Cascading State Propagation and Compensation

Several operations mutate more than one resource, and the secondary effects are as much a part of the contract as the primary transition. The system applies these consistently and immediately.

Accepting a quote creates a `Job`, adds that quote's `total_cents` to the owning lead's `financing_balance_cents`, and increments the lead's `version`. Creating an engineering scope supersedes any prior non-terminal scope for the same lead and increments the lead's `version`. Completing an install job runs a three-hop cascade: it activates a `Warranty`, warranty activation books the first `MaintenanceVisit`, and creating that visit increments the lead's `active_visit_count`. Approving a claim runs a two-hop cascade: it creates a remediation `Job` and that creation increments the source warranty's `remediation_count`. Opening a permit sets the parent job's `permit_status` to `PENDING`, and deciding the permit bubbles the decision up onto the job's `permit_status`.

Compensating adjustments run in reverse when work is undone. Cancelling a job releases the crew minutes it had booked (when it was scheduled) and credits back the financed balance it had debited (when it originated from an accepted quote). Completing or missing a maintenance visit decrements the lead's `active_visit_count`. Each such adjustment independently mutates its target resource and refreshes that resource's `updated_at` and `version`.

### 2.9. Monetary Precision and Rounding Discipline

All monetary amounts are stored and returned as integer cents. Every rounding step uses the round-half-up convention. Two rounding orders are pinned and must be honored exactly, because a different order yields a different cent figure:

- In pier pricing, the per-pier amount is rounded to a whole cent **first**, and only then multiplied by the pier count. The count is never multiplied in before rounding.
- In financing, the volume discount and the financing fee are each rounded to a whole cent at the point they are computed, in the evaluation order given in §3.3.

Non-monetary aggregates follow their own natural units: `booked_minutes` is an integer number of minutes, and counts such as `active_visit_count`, `transfer_count`, and `remediation_count` are integers.

### 2.10. Validation Ordering

When a single request could fail multiple checks, the checks are evaluated in a fixed priority order and the first failure is the one returned. The canonical order is: (1) authentication of the role header, yielding `ERR_UNAUTHENTICATED`; (2) authorization and customer ownership, yielding `ERR_FORBIDDEN`; (3) existence of path and body references, yielding `ERR_NOT_FOUND`; (4) request-body schema validity — required fields present, enum values in range, numbers well-typed — yielding `ERR_VALIDATION`; (5) the optimistic-concurrency version check on scope creation, yielding `ERR_STALE_VERSION`; (6) the legal-state check for the requested transition, yielding `ERR_INVALID_STATE`; then the domain-specific business rules in this order: (7) quote-not-expired `ERR_QUOTE_EXPIRED`, (8) unstable-soil-unmitigated `ERR_UNSAFE_SOIL_UNMITIGATED`, (9) crew-double-booked `ERR_CREW_DOUBLE_BOOKED`, (10) visit-too-soon `ERR_VISIT_TOO_SOON`, (11) permit-not-approved `ERR_PERMIT_NOT_APPROVED`, (12) scope-not-engineered `ERR_SCOPE_NOT_ENGINEERED`, (13) warranty-not-active `ERR_WARRANTY_NOT_ACTIVE`, (14) crew-region-mismatch `ERR_CREW_REGION_MISMATCH`, (15) pier-count-mismatch `ERR_PIER_COUNT_MISMATCH`, (16) no-piers-on-finalize `ERR_NO_PIERS`, (17) invalid-schedule-window `ERR_SCHEDULE_WINDOW_INVALID`, (18) visit-date-in-past `ERR_VISIT_DATE_IN_PAST`, (19) visit-not-due `ERR_VISIT_NOT_DUE`, (20) remediation-not-complete `ERR_REMEDIATION_NOT_COMPLETE`, and (21) financing-limit-exceeded `ERR_FINANCING_LIMIT_EXCEEDED`. On any given endpoint only the applicable subset applies, but their relative order always follows this list. For example, scheduling an install checks legal state, then unstable soil, then crew double-booking, then permit approval, then crew-region match, then window validity, in exactly that sequence.

## 3. Business Logic & Workflows

### 3.1. Lead Intake and the Free Inspection

The pipeline begins when a `SalesAgent` registers a homeowner as a **Lead**, supplying the `customer_name`, the `property_address`, the homeowner `contact_email`, and a `region_code` drawn from `NORTH`, `SOUTH`, `EAST`, or `WEST`. The region matters later: a crew can only be booked for an install if the crew serves the lead's region. A freshly created lead starts with a `financing_balance_cents` of 0 and an `active_visit_count` of 0; both are derived figures the system maintains, never client inputs. The `financing_balance_cents` is the sum of `total_cents` across the lead's accepted quotes whose resulting job has not been cancelled, and `active_visit_count` is the running number of the lead's maintenance visits currently in `SCHEDULED` status across all of the lead's warranties.

A `SalesAgent` then books a free **Inspection** against a lead, providing the `lead_id` of the target lead and a `scheduled_at` instant for the visit. The inspection opens in `SCHEDULED`. A `SalesAgent` may cancel a still-scheduled inspection, moving it from `SCHEDULED` to `CANCELLED` with no further effect. A `FieldEngineer` completes the inspection, transitioning it from `SCHEDULED` to `COMPLETED`; completion requires that the assessment be recorded — the `soil_class`, the `crack_severity`, the `max_crack_width_mm`, and the `settlement_inches` must all be provided, and their absence is a schema failure (`ERR_VALIDATION`). The `soil_class` is one of `STABLE`, `EXPANSIVE`, or `UNSTABLE`; `crack_severity` is an integer severity index from 0 to 5, and a value outside that inclusive range (or a non-integer) is rejected as `ERR_VALIDATION`; `max_crack_width_mm` is the widest observed crack in millimetres; and `settlement_inches` is the observed differential settlement in inches. Completing an inspection persists these assessment fields and unlocks scope creation for the lead. An attempt to complete or cancel an inspection that is not in `SCHEDULED` is rejected with `ERR_INVALID_STATE`.

### 3.2. Engineering the Scope

Once an inspection is complete, a `FieldEngineer` authors an **EngineeringScope**. The creation payload carries the `lead_id`, the `inspection_id` of the source assessment, the engineered `pier_count`, the engineered `anchor_count`, the `avg_pier_depth_ft` (average engineered pier depth in feet, which selects the depth pricing tier), the `access_difficulty` (`EASY`, `MODERATE`, or `HARD`, a site-access multiplier), and the required `expected_lead_version` for the concurrency check described in §2.7. The payload may also carry `supplemental_engineering`, a boolean that defaults to false when omitted and indicates that a supplemental stabilization design is attached. The referenced inspection must be in `COMPLETED` status, or the creation is rejected with `ERR_INVALID_STATE`. A new scope opens in `DRAFT`.

Creating a scope has two side effects beyond persisting the new row: any prior `EngineeringScope` for the same lead that is currently in `DRAFT` or `ENGINEERED` is transitioned to the terminal `SUPERSEDED` state, and the lead's `version` is incremented by one. This is the reason scope creation is version-guarded — the increment is exactly what a competing writer would observe as a stale `expected_lead_version`.

A `FieldEngineer` finalizes a draft scope, moving it from `DRAFT` to `ENGINEERED`; finalization requires that `pier_count` be at least 1, and a scope with no piers is rejected with `ERR_NO_PIERS`. Only an `ENGINEERED` scope is eligible to back an accepted quote. Attempting to finalize a scope that is not in `DRAFT` is an `ERR_INVALID_STATE`. A scope in `DRAFT` or `ENGINEERED` also moves to `SUPERSEDED` automatically, without any client call, whenever a newer scope is created for the same lead.

### 3.3. Quoting, Pricing, and Financing

A `SalesAgent` drafts a **Quote** by referencing the `lead_id`, the `scope_id` being priced, and a `financing_plan` of `CASH`, `PLAN_12`, or `PLAN_60`. The quote opens in `DRAFT`. Sending the quote transitions it from `DRAFT` to `SENT` (and re-sending a revised quote transitions it from `REVISED` back to `SENT`); in both cases sending recomputes the pricing and financing figures and sets the expiry. A sent quote may be pushed back into a revision loop: revising it transitions it from `SENT` to `REVISED`, optionally updating the `financing_plan`, and leaves its pricing stale until it is sent again. The valid window is thirty days: on each send, `expires_at` is set to the current logical clock instant plus `QUOTE_VALID_DAYS` (30 days).

**Pier-and-anchor subtotal.** Sending a quote computes `subtotal_cents` using the estimate variant of the pier-pricing rule, which projects the engineered pier count. First the depth tier is selected from `avg_pier_depth_ft`: a depth below 15 feet takes the tier-1 base of 120,000 cents (`PIER_TIER1_CENTS`); a depth of at least 15 feet but below 25 feet takes the tier-2 base of 165,000 cents (`PIER_TIER2_CENTS`); and a depth of 25 feet or more takes the tier-3 base of 210,000 cents (`PIER_TIER3_CENTS`). That base is multiplied by the soil multiplier keyed on the source inspection's `soil_class` — 1.00 for `STABLE`, 1.15 for `EXPANSIVE`, 1.30 for `UNSTABLE` — and by the access multiplier keyed on the scope's `access_difficulty` — 1.00 for `EASY`, 1.10 for `MODERATE`, 1.25 for `HARD`. The product is rounded half-up to a whole cent to yield the per-pier amount. The per-pier amount is then multiplied by the pier count (the engineered `pier_count` in the estimate variant), giving the pier portion of the subtotal. The anchor portion is the scope's `anchor_count` multiplied by 45,000 cents per anchor (`ANCHOR_UNIT_CENTS`). The subtotal is the sum of the pier portion and the anchor portion. The rounding order is fixed: round the per-pier amount before multiplying by the count.

**Financing figures.** Sending also computes `financing_fee_cents` and `total_cents` from the subtotal, in a pinned order. Take the gross subtotal just computed. If the gross subtotal is at least 2,000,000 cents (`VOLUME_DISCOUNT_THRESHOLD_CENTS`), a volume discount equal to the gross subtotal times 0.05 (`VOLUME_DISCOUNT_RATE`), rounded half-up to a whole cent, is applied; otherwise the discount is zero. The discount tier is keyed on the gross subtotal, not on the total. The financed principal is the gross subtotal minus that discount. The financing fee is the financed principal times the plan rate for the quote's `financing_plan` — 0.00 for `CASH`, 0.05 for `PLAN_12`, 0.12 for `PLAN_60` — rounded half-up to a whole cent; the fee is computed on the financed principal, not on the gross subtotal. Finally, `total_cents` is the financed principal plus the financing fee. These `subtotal_cents`, `financing_fee_cents`, `total_cents`, and `expires_at` fields are all server-computed and refreshed on every send.

### 3.4. Acceptance, the Financing Limit, and Job Creation

A `Customer` accepts a sent quote, transitioning it from `SENT` to `ACCEPTED`, or rejects it, transitioning it from `SENT` to `REJECTED`. A `SENT` quote is also moved to `EXPIRED` automatically once the logical clock passes its `expires_at`; there is no explicit expire call. Acceptance runs three preconditions in order. First, the current logical clock must be at or before the quote's `expires_at`, otherwise the accept is rejected with `ERR_QUOTE_EXPIRED`. Second, the quote's referenced `EngineeringScope` must be in `ENGINEERED` status, otherwise the accept is rejected with `ERR_SCOPE_NOT_ENGINEERED`. Third, the financed principal derived from the quote's pricing must not exceed 5,000,000 cents (`FINANCING_LIMIT_CENTS`); a financed principal above that ceiling is rejected with `ERR_FINANCING_LIMIT_EXCEEDED` at HTTP 402.

Rejection sets the quote to `REJECTED` and has no downstream effect. Acceptance, in contrast, spawns work: it creates a **Job** with `fulfillment_status` of `UNSCHEDULED`, `permit_status` of `NOT_STARTED`, its `quote_id` set to the accepted quote and its `lead_id` copied from the quote, and its `source_claim_id` left null. Acceptance also increases the lead's `financing_balance_cents` by the quote's `total_cents` and increments the lead's `version` by one. Attempting any of these transitions from a non-`SENT` state is an `ERR_INVALID_STATE`.

### 3.5. Permits, Crews, and Install Scheduling

Two independent things must be true before an install can be scheduled: a permit must be approved, and a crew must be available. These evolve on the `Job` as two parallel dimensions. The `fulfillment_status` dimension runs `UNSCHEDULED` → `SCHEDULED` → `IN_PROGRESS` → `COMPLETED`, with `UNSCHEDULED` or `SCHEDULED` able to move to `CANCELLED`. The `permit_status` dimension runs `NOT_STARTED` → `PENDING` → `APPROVED` or `REJECTED` and simply mirrors the latest permit decision. The two dimensions advance without ordering constraints between them, except that scheduling reads `permit_status`.

An `Admin` maintains the roster of install **Crews**, each created with a `crew_name` and the `region_code` it serves; a new crew starts with `booked_minutes` of 0. A crew's `booked_minutes` is a derived aggregate: the sum, over the crew's jobs whose `fulfillment_status` is `SCHEDULED` or `IN_PROGRESS`, of the window length in minutes between each job's `scheduled_start` and `scheduled_end`. The booking window is treated as half-open — it spans from `scheduled_start` up to but not including `scheduled_end`.

An `OpsCoordinator` opens a **Permit** for a job by supplying the `job_id` and a `permit_type` of `STANDARD`, `STRUCTURAL`, or `ENGINEERED`; the permit opens in `PENDING` and sets the parent job's `permit_status` to `PENDING`. Opening a permit against a job whose `fulfillment_status` is `CANCELLED` is rejected with `ERR_INVALID_STATE`. The coordinator then decides the permit by supplying a `decision` of `APPROVE` or `REJECT`. An approval moves the permit from `PENDING` to `APPROVED` and sets the parent job's `permit_status` to `APPROVED`; a rejection moves the permit from `PENDING` to `REJECTED` and sets the parent job's `permit_status` to `REJECTED`. Both are bubble-up effects onto the job.

An `OpsCoordinator` schedules an install by moving the job from `UNSCHEDULED` to `SCHEDULED`, supplying a `crew_id`, a `scheduled_start`, and a `scheduled_end`. Scheduling enforces a battery of checks in priority order. If the job's source inspection recorded a `soil_class` of `UNSTABLE`, then the backing scope must have `supplemental_engineering` set to true; unstable soil without that mitigation is rejected with `ERR_UNSAFE_SOIL_UNMITIGATED`. The chosen crew must not already have a job in `SCHEDULED` or `IN_PROGRESS` whose half-open window overlaps the requested `[scheduled_start, scheduled_end)` — abutting windows that merely touch at an endpoint are allowed, but any true overlap is rejected with `ERR_CREW_DOUBLE_BOOKED`. The job's `permit_status` must be `APPROVED`, or the request is rejected with `ERR_PERMIT_NOT_APPROVED`. And the crew's `region_code` must equal the lead's `region_code`, or the request is rejected with `ERR_CREW_REGION_MISMATCH`. Finally, the window must be valid — `scheduled_end` strictly after `scheduled_start` — or the request fails with `ERR_SCHEDULE_WINDOW_INVALID`. On success the server records the `crew_id`, `scheduled_start`, and `scheduled_end` on the job and increases the crew's `booked_minutes` by the window's minutes. Scheduling from any state other than `UNSCHEDULED` is an `ERR_INVALID_STATE`.

Once scheduled, an `OpsCoordinator` starts the install, moving the job from `SCHEDULED` to `IN_PROGRESS` with no additional preconditions.

### 3.6. Install Completion and Warranty Activation

An `OpsCoordinator` completes an install, moving the job from `IN_PROGRESS` to `COMPLETED` and recording the actual `piers_installed` and the achieved `adjustment_inches` (the lift in inches). For an install job — one that carries a non-null `quote_id` — completion enforces that the actual `piers_installed` deviates from the backing scope's `pier_count` by no more than 2 (`PIER_TOLERANCE`); that is, the absolute difference between `piers_installed` and `pier_count` must be at most 2, and a larger deviation is rejected with `ERR_PIER_COUNT_MISMATCH`. Completing a job that is not `IN_PROGRESS` is an `ERR_INVALID_STATE`.

For an install job, completion recomputes pricing with the **final** variant and then runs the warranty cascade. The final variant of pier pricing is identical to the estimate variant except that the pier count used is the actual `piers_installed` rather than the engineered `pier_count`; it writes `final_subtotal_cents`, and the two figures diverge exactly when `piers_installed` differs from `pier_count`. The financing rule then runs on that final subtotal — same pinned steps of volume discount, financed principal, financing fee, and sum — to produce `final_total_cents`. The cascade then proceeds in three hops: first, a `Warranty` is created in `ACTIVE` status with its `holder_name` set to the lead's `customer_name`, its `covered_pier_count` copied from the job's `piers_installed`, and its `activated_at` set to the current logical clock; second, activating that warranty books the warranty's first `MaintenanceVisit` in `SCHEDULED` status, dated at `activated_at` plus `VISIT_INTERVAL_DAYS` (365 days); third, creating that visit increments the owning lead's `active_visit_count` by one. A remediation job (one with a null `quote_id`) does not run the pier-count tolerance check, does not recompute final pricing, and does not activate a warranty.

An `OpsCoordinator` may cancel a job that is still `UNSCHEDULED` or `SCHEDULED`, moving it to `CANCELLED`. Cancellation compensations depend on the state it leaves. Cancelling from `UNSCHEDULED`: if the job carries a `quote_id`, the lead's `financing_balance_cents` is decreased by that accepted quote's `total_cents`. Cancelling from `SCHEDULED`: the crew's `booked_minutes` is decreased by the job's window minutes, and, if the job carries a `quote_id`, the lead's `financing_balance_cents` is likewise decreased by the quote's `total_cents`. Cancelling from any other state is an `ERR_INVALID_STATE`.

### 3.7. The Transferable Lifetime Warranty and Annual Re-Tightening Visits

A **Warranty** produced by an install is a transferable lifetime guarantee with no expiry. It records the `lead_id` and the producing `job_id`, the current `holder_name`, the `activated_at` instant, a `covered_pier_count`, and two derived counters: `transfer_count`, the number of ownership transfers performed, and `remediation_count`, the number of approved claims that spawned a remediation job. A `Customer` transfers a warranty to a new owner by supplying a `new_holder_name`; the transfer keeps the warranty in `ACTIVE` (an `ACTIVE`-to-`ACTIVE` self-transition), sets `holder_name` to the supplied `new_holder_name`, and increments `transfer_count` by one. An `Admin` may void a warranty, moving it from `ACTIVE` to `VOID`; any already-`SCHEDULED` maintenance visit is left as it stands, but a voided warranty accepts no new claims or visits.

The warranty carries an annual re-tightening obligation. An `OpsCoordinator` schedules a **MaintenanceVisit** by supplying the `warranty_id`, a `scheduled_date`, and optionally a `crew_id` for the crew assigned to the re-tightening. A visit opens in `SCHEDULED`. Three preconditions apply. The referenced warranty must be `ACTIVE`, or the request is rejected with `ERR_WARRANTY_NOT_ACTIVE`. The `scheduled_date` must be strictly in the future relative to the current logical clock, or the request is rejected with `ERR_VISIT_DATE_IN_PAST`. And the `scheduled_date` must be at least `MIN_VISIT_GAP_DAYS` (300 days) away from every other visit already on that warranty; a date closer than that buffer to any existing visit is rejected with `ERR_VISIT_TOO_SOON`. Scheduling a visit increments the lead's `active_visit_count` by one.

An `OpsCoordinator` completes a scheduled visit by supplying the `tightening_turns` applied, moving it from `SCHEDULED` to `COMPLETED` and decrementing the lead's `active_visit_count` by one. Alternatively, when a visit goes unattended, the coordinator marks it missed, moving it from `SCHEDULED` to `MISSED`; marking missed requires that the current logical clock be strictly past the visit's `scheduled_date`, otherwise the request is rejected with `ERR_VISIT_NOT_DUE`. Marking a visit missed also decrements the lead's `active_visit_count` by one, and a missed visit later reduces the coverage percentage on any claim settlement for that warranty. Attempting either terminal transition on a visit that is not `SCHEDULED` is an `ERR_INVALID_STATE`.

### 3.8. Callbacks, Claims, and Remediation

When a homeowner reports a new problem, a `Customer` files a **Claim** against a warranty, supplying the `warranty_id`, a free-text `description`, and the `reported_settlement_inches` of newly observed settlement. The referenced warranty must be `ACTIVE`, or the filing is rejected with `ERR_WARRANTY_NOT_ACTIVE`. The claim opens in `FILED`. A `ClaimsAdjuster` begins review, moving it from `FILED` to `UNDER_REVIEW`. Review may enter an information loop: the adjuster requests more information, moving it from `UNDER_REVIEW` to `NEEDS_INFO`, and a `Customer` resubmits, moving it from `NEEDS_INFO` back to `UNDER_REVIEW`. From `UNDER_REVIEW` the adjuster reaches a terminal-track decision: approving it moves it to `APPROVED`, and denying it moves it to `DENIED`. A denial has no downstream effect. Any of these transitions attempted from an illegal source state is an `ERR_INVALID_STATE`.

Approving a claim computes the settlement and spawns remediation. The number of piers needed is the `reported_settlement_inches` divided by 0.5 inches per pier (`INCHES_PER_PIER`), rounded up to the next whole pier. The full cost is that pier count multiplied by 150,000 cents per remediation pier (`REMEDIATION_PIER_CENTS`). The coverage percentage starts at 1.00 and is reduced by 0.10 (`MISSED_PENALTY`) for each maintenance visit on the warranty that is in `MISSED` status, but never falls below a floor of 0.50 (`COVERAGE_FLOOR`) — that is, the coverage percentage is the larger of 0.50 and the quantity one minus 0.10 times the count of missed visits. The `settlement_cents` is the full cost multiplied by that coverage percentage, rounded half-up to a whole cent. The `coverage_variant` records which path applied: when there are no missed visits the coverage percentage is 1.00, the settlement equals the full cost, and the variant is `FULL`; when there is at least one missed visit the reduced-and-floored percentage applies and the variant is `PRORATED`. Approval then runs a two-hop cascade: it creates a remediation `Job` with a null `quote_id`, its `source_claim_id` set to this claim, its `lead_id` copied from the warranty's `lead_id`, and `fulfillment_status` of `UNSCHEDULED`; creating that job increments the warranty's `remediation_count` by one; and the claim's `remediation_job_id` is set to point at the new job.

Finally, a `ClaimsAdjuster` resolves an approved claim, moving it from `APPROVED` to `RESOLVED`; resolution requires that the spawned remediation job have reached `COMPLETED` fulfillment, and an attempt to resolve before the remediation job completes is rejected with `ERR_REMEDIATION_NOT_COMPLETE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify or transition an existing resource, and all read operations, return `200 OK`. Request bodies, response bodies, and side effects are described in the workflow narratives of §3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/foundation/leads` | Create a Lead | SalesAgent |
| GET | `/foundation/leads/{lead_id}` | Get a Lead | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/leads` | List Leads | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/inspections` | Book a free inspection | SalesAgent |
| POST | `/foundation/inspections/{inspection_id}/complete` | Record soil/crack assessment | FieldEngineer |
| POST | `/foundation/inspections/{inspection_id}/cancel` | Cancel a scheduled inspection | SalesAgent |
| GET | `/foundation/inspections/{inspection_id}` | Get an Inspection | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/inspections` | List Inspections | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/scopes` | Create an engineered scope | FieldEngineer |
| POST | `/foundation/scopes/{scope_id}/finalize` | Finalize scope to ENGINEERED | FieldEngineer |
| GET | `/foundation/scopes/{scope_id}` | Get an EngineeringScope | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/scopes` | List scopes | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/quotes` | Create a Quote | SalesAgent |
| POST | `/foundation/quotes/{quote_id}/send` | Send/re-send quote; compute pricing | SalesAgent |
| POST | `/foundation/quotes/{quote_id}/accept` | Accept a sent quote; spawn Job | Customer |
| POST | `/foundation/quotes/{quote_id}/reject` | Reject a sent quote | Customer |
| POST | `/foundation/quotes/{quote_id}/revise` | Send quote back to REVISED | SalesAgent |
| GET | `/foundation/quotes/{quote_id}` | Get a Quote | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/quotes` | List quotes | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/jobs/{job_id}/schedule` | Schedule install & book crew | OpsCoordinator |
| POST | `/foundation/jobs/{job_id}/start` | Start a scheduled install | OpsCoordinator |
| POST | `/foundation/jobs/{job_id}/complete` | Complete install; activate warranty | OpsCoordinator |
| POST | `/foundation/jobs/{job_id}/cancel` | Cancel an unscheduled/scheduled job | OpsCoordinator |
| GET | `/foundation/jobs/{job_id}` | Get a Job | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/jobs` | List jobs | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/crews` | Create an install crew | Admin |
| GET | `/foundation/crews/{crew_id}` | Get a Crew | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/crews` | List crews | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/permits` | Open a permit for a job | OpsCoordinator |
| POST | `/foundation/permits/{permit_id}/decide` | Approve or reject a permit | OpsCoordinator |
| GET | `/foundation/permits/{permit_id}` | Get a Permit | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/permits` | List permits | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/warranties/{warranty_id}/transfer` | Transfer warranty to a new holder | Customer |
| POST | `/foundation/warranties/{warranty_id}/void` | Void a warranty | Admin |
| GET | `/foundation/warranties/{warranty_id}` | Get a Warranty | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/warranties` | List warranties | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/maintenance-visits` | Schedule an annual re-tightening visit | OpsCoordinator |
| POST | `/foundation/maintenance-visits/{visit_id}/complete` | Complete a re-tightening visit | OpsCoordinator |
| POST | `/foundation/maintenance-visits/{visit_id}/mark-missed` | Mark an overdue visit missed | OpsCoordinator |
| GET | `/foundation/maintenance-visits/{visit_id}` | Get a MaintenanceVisit | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/maintenance-visits` | List visits | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/claims` | File a callback/claim | Customer |
| POST | `/foundation/claims/{claim_id}/review` | Begin review | ClaimsAdjuster |
| POST | `/foundation/claims/{claim_id}/request-info` | Request more info | ClaimsAdjuster |
| POST | `/foundation/claims/{claim_id}/resubmit` | Resubmit info | Customer |
| POST | `/foundation/claims/{claim_id}/approve` | Approve claim; spawn remediation job | ClaimsAdjuster |
| POST | `/foundation/claims/{claim_id}/deny` | Deny claim | ClaimsAdjuster |
| POST | `/foundation/claims/{claim_id}/resolve` | Resolve an approved claim | ClaimsAdjuster |
| GET | `/foundation/claims/{claim_id}` | Get a Claim | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| GET | `/foundation/claims` | List claims | SalesAgent, FieldEngineer, OpsCoordinator, ClaimsAdjuster, Customer, Admin |
| POST | `/foundation/_clock/set_current_utc` | Set the server logical clock | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_SCOPE_NOT_ENGINEERED` | 409 |
| `ERR_UNSAFE_SOIL_UNMITIGATED` | 422 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_CREW_REGION_MISMATCH` | 409 |
| `ERR_PERMIT_NOT_APPROVED` | 409 |
| `ERR_SCHEDULE_WINDOW_INVALID` | 422 |
| `ERR_PIER_COUNT_MISMATCH` | 422 |
| `ERR_NO_PIERS` | 422 |
| `ERR_FINANCING_LIMIT_EXCEEDED` | 402 |
| `ERR_WARRANTY_NOT_ACTIVE` | 409 |
| `ERR_VISIT_TOO_SOON` | 409 |
| `ERR_VISIT_DATE_IN_PAST` | 422 |
| `ERR_VISIT_NOT_DUE` | 409 |
| `ERR_REMEDIATION_NOT_COMPLETE` | 409 |
