# Emergency Board-Up & Property Securing API — Product Requirements Document

## 1. Introduction

When a fire guts a storefront, a storm peels back a roof, or vandals smash every window on the ground floor, the first twenty-four hours determine whether the property owner faces a contained loss or a cascading one. Insurers demand documented, promptly executed mitigation; municipalities increasingly demand permits and notifications; and the contractors willing to board up a building at 3 a.m. are a scarce, geographically fragmented resource. The Emergency Board-Up & Property Securing API is the operational backbone for a network operator that coordinates this work: it dispatches vetted subcontractors to damaged properties, tracks response times against per-market service-level agreements, enforces an independent safety assessment before any securing is declared complete, manages temporary power, lighting and security patrols while the property awaits permanent repair, and produces the documentation packages and provisional/final invoices that insurance billing requires.

The system is deliberately opinionated on a handful of cross-cutting concerns. Dispatch is a selector problem — the operator may pin a specific crew or let the platform rank the eligible pool by measured reliability. Safety is a segregation-of-duties problem — the subcontractor who performs the securing work may never be the one who assesses its hazards. Compliance is a clock problem — notification deadlines, offer expiries, and patrol windows all hinge on a single logical clock that the platform controls explicitly. And billing is a two-pass problem — a provisional invoice on planned quantities authorizes the work with the insurer, and a final invoice on actual measurements settles it. This document specifies all of these behaviors for the engineering team implementing the service.

## 2. Global Specifications & System-Wide Principles

This section defines the structural contract and the system-wide rules that apply uniformly across every resource and endpoint.

### 2.1. Roles, Identity, and Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly four operational roles — `PlatformAdmin`, `Dispatcher`, `Customer`, and `Subcontractor`. A fifth value, `Anonymous`, is recognized nowhere: it exists only as a marker for unauthenticated callers, and any request bearing it is rejected. A request missing either header, or bearing a role value outside the four recognized operational roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

`X-User-ID` is interpreted differently depending on the role, and this interpretation drives every ownership check in the system:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform does not compare it against any resource's `id`. Platform administrators configure markets, onboard subcontractors, grant coverage, register customers and properties, record municipal permit decisions, and drive the logical clock.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. Dispatchers run the 24/7 operational console: intake, dispatch, scope, services, permits, documentation, and billing.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a `Customer` compare the resource's `customer_id` field to `X-User-ID`; a mismatch on a customer-gated action (verifying a permanent repair, disputing an invoice) is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `Subcontractor`, `X-User-ID` is the `id` of the acting `Subcontractor` entity. Assignee checks compare the acting `id` to the `subcontractor_id` of the relevant assignment — or, for job-level crew actions, to the `subcontractor_id` of that job's currently accepted assignment — and a mismatch is rejected with `ERR_NOT_ASSIGNEE` (HTTP 403). For safety mitigation, authorship is checked the same way against the assessment's `assessor_subcontractor_id`, and a mismatch there is rejected with `ERR_FORBIDDEN`.

All read endpoints are shared: any of the four operational roles may call them. Mutating endpoints are role-segregated as described throughout §3 and summarized in §4.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order — oldest first. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — markets, subcontractors, coverage rows, customers, properties, jobs, assignments, safety assessments, scope items, temporary services, patrol visits, permit cases, document packages, and invoices — carries a uniform set of system-managed fields:

- `id` — a server-minted UUID, with no type prefix, generated at creation.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, taken from the platform's logical clock (§2.5).
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 and increments by exactly one on every mutation, whether the mutation was client-requested or the by-product of an automatic cascade.

The `version` field is the linchpin of optimistic concurrency control (§2.9). Because cascades routinely mutate a job as a side effect of actions on its children, clients should treat a parent resource's `version` as volatile and always read it fresh before issuing a version-guarded write.

### 2.5. The Logical Clock

All timestamps in the system — offers, arrivals, filings, deadlines, service windows — are taken from a single platform logical clock, never from server wall-clock time. Before any administrative intervention, the clock starts at exactly `2026-05-01T00:00:00Z` and must not fall back to wall-clock time under any circumstance. A `PlatformAdmin` may advance the clock through a dedicated test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock is not a passive act: it sweeps every still-`PENDING` municipal notification case whose deadline now lies in the past into `EXPIRED`, latching the affected job's compliance-breach flag as described in §3.7. The same expiry evaluation also happens lazily — when an individual case is read, and when an invoice submission needs to consult it — so behavior never depends on whether the clock endpoint was called recently.

### 2.6. Nested Resource Retrieval

Several endpoints address a child resource through its parent in the URL — a scope item beneath a job, a patrol visit beneath a temporary service. Path identifiers are validated strictly left to right: the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not correspond to an existing resource, before any deeper identifier is examined and before any body validation. References carried in the request body — for example a `property_id` on job intake, or the `subcontractor_id` and `market_id` on a coverage grant — are likewise verified to exist, with `ERR_NOT_FOUND` on a dangling reference.

### 2.7. Validation Order of Precedence

When several checks could reject the same request, the order in which they fire is part of the contract. The platform evaluates every request against the following stages, in this exact sequence, and surfaces the first failure encountered:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is recognized; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the role is permitted on the endpoint, and entity-backed ownership holds: a `Customer` must own the job (repair verification, invoice dispute), a `Subcontractor` must be the assignee of the targeted job or assignment (crew check-in, completing securing, installing scope, recording removal, patrol check-in) or the author of the assessment (recording mitigation). Failures surface as `ERR_FORBIDDEN` or `ERR_NOT_ASSIGNEE`.
3. **Request well-formedness** — required body fields are present and values are well-formed (`ERR_INVALID_REQUEST`, HTTP 400), and every enum field carries a member of its declared set (`ERR_INVALID_ENUM`, HTTP 400).
4. **Existence** — path identifiers exist, validated left to right, and body foreign-key references exist (`ERR_NOT_FOUND`).
5. **State eligibility** — an action against an entity already in a terminal state is always rejected with `ERR_ALREADY_TERMINAL` (HTTP 409); otherwise the entity must be in the action's expected from-state, failing with `ERR_INVALID_STATE` (HTTP 409).
6. **Safety and regulatory gates**, evaluated in this sub-order: (i) segregation of duties between assessor and assignee (`ERR_SEGREGATION_OF_DUTIES`); (ii) hazards cleared before securing is completed (`ERR_HAZARD_NOT_MITIGATED`); (iii) an approved permit before invoice submission in permit jurisdictions (`ERR_PERMIT_NOT_APPROVED`); (iv) the documentation package having reached completeness at least once before invoice submission (`ERR_DOCS_INCOMPLETE`); (v) artifacts accepted only on an unlocked package (`ERR_PACKAGE_LOCKED`).
7. **Temporal gates** — an offer answered within its expiry (`ERR_OFFER_EXPIRED`); a patrol check-in inside its window, and a missed-visit ruling only after the window has ended (`ERR_VISIT_NOT_DUE`); a newly scheduled visit window that is not already in the past (`ERR_VISIT_WINDOW_PAST`); invoice submission blocked while a required notification is still pending (`ERR_NOTIFICATION_PENDING`) or lapsed unfiled (`ERR_NOTIFICATION_DEADLINE_EXPIRED`).
8. **Structural constraints** — positive measurements appropriate to the scope kind (`ERR_INVALID_MEASUREMENT`); a non-empty scope before securing completes (`ERR_SCOPE_EMPTY`); every surviving scope line installed (`ERR_SCOPE_ITEMS_PENDING`); dispatch pool and capacity checks (`ERR_NO_COVERAGE`, `ERR_CAPACITY_FULL`); pinned coverage matching the job's market (`ERR_MARKET_MISMATCH`); the pinned subcontractor being active (`ERR_SUBCONTRACTOR_SUSPENDED`); uniqueness guards (`ERR_DUPLICATE_COVERAGE`, `ERR_DUPLICATE_PACKAGE`, `ERR_PERMIT_CASE_OPEN`, `ERR_INVOICE_OPEN_EXISTS`); invoice variant matching the job's lifecycle (`ERR_INVOICE_VARIANT_INVALID`); patrol visits only on patrol services (`ERR_SERVICE_NOT_PATROL`); visit-window overlap (`ERR_OVERLAP_CONFLICT`); generator pool capacity (`ERR_GENERATOR_POOL_EXHAUSTED`); services stood down before removal (`ERR_SERVICES_STILL_ACTIVE`).
9. **Fiscal gates** — the final-invoice variance cap (`ERR_VARIANCE_CAP_EXCEEDED`) and the all-invoices-paid precondition of job closure (`ERR_INVOICES_UNPAID`).
10. **Optimistic concurrency** — the version-guard fields of §2.9 are compared last of all, after every other check has passed; a mismatch surfaces as `ERR_STALE_VERSION` (HTTP 412).

The practical consequence: a dispatch attempted on a job that has already left `INTAKE` fails on stage 5 before any coverage pool is consulted, and a stale version field is never reported while a more fundamental problem would also have rejected the request.

### 2.8. Money, Quantities, and Rounding

All monetary amounts are integer cents — rates, fees, subtotals, discounts, and totals are never fractional. Wherever a multiplication would produce a fractional cent (a rate times a priority multiplier, a subtotal times a discount percentage, a patrol fee), the result is rounded half up to the nearest whole cent. Two ordering commitments are pinned: invoice work lines are each rounded to whole cents first and only then summed into the work subtotal, and patrol fees are rounded per visit at creation and only then summed onto a final invoice — rounding after summation produces a different number and is incorrect. Material quantities follow their own rules given in §3.5 (sheet and tarp quantities are rounded up to whole units; fence footage is kept exactly as measured). Subcontractor reliability scores are ratios carried to exactly four decimal places, rounded half up. Temporal durations are computed in whole units as specified per rule: response lateness floors to whole minutes, and service billing rounds partial days up.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency on their parent resource's `version`, and both guards are mandatory, non-optional request fields:

- **Adding a scope line to a job** (`POST /jobs/{id}/scope-items`). The request must carry `expected_job_version`, holding the `version` of the job as the client last observed it. Because every scope addition and every scope void legitimately advances the job's `version`, a client whose view predates another writer's scope change is working from a stale picture of the job's scope; if the supplied value does not equal the job's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Adding an artifact to a documentation package** (`POST /document-packages/{id}/artifacts`). The request must carry `expected_package_version`, holding the `version` of the `DocumentPackage` as the client last observed it. Each artifact addition advances the package's `version`, so a mismatch means the client's view of the package's completeness is stale; the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field — these two are the complete OCC surface.

### 2.10. Cross-Resource Consistency and Automatic Transitions

The platform treats the resource graph as one consistency boundary and will move resources without an explicit client request when an event elsewhere demands it. Three such machinery families recur throughout §3: the offer cascade (a declined, expired, or withdrawn offer automatically re-offers the job to the next eligible subcontractor, or regresses the job to `INTAKE` when the pool runs dry); the patrol-miss breach cascade (a missed patrol visit pauses its service, drops the secured job into `BREACH_HOLD`, and pauses every sibling service); and the suspension cascade (suspending a subcontractor cancels all its open assignments and coverage, which in turn can regress affected jobs). Document packages likewise lock and unlock themselves in step with invoice submission and dispute, and notification cases expire under clock advancement. Every such automatic mutation is a real mutation: it refreshes the affected resource's `updated_at` and increments its `version`, so clients holding a parent's `version` observe every cascade that touches it.

## 3. Business Logic & Workflows

### 3.1. Building the Response Network: Markets, Subcontractors, Coverage, Customers, and Properties

Everything starts with network configuration, owned by the `PlatformAdmin`. A **market** is the jurisdictional and commercial unit: it is created with a display `name` and a `code` that must be unique across all markets (e.g. `SEA`). The market carries the response-time SLA matrix — `sla_minutes_p1`, `sla_minutes_p2`, and `sla_minutes_p3`, the minutes within which a crew must arrive for a job of the corresponding priority — and the jurisdiction flags `permit_required` (the municipality requires a board-up permit before insurance billing) and `notification_required` (the municipality must be notified after a property is secured), together with `notification_deadline_hours`, the number of hours after securing within which that notification must be filed, and `late_notification_fee_cents`, the penalty billed once on the first invoice created after a late filing. The market also carries the full rate card: `board_rate_per_sheet_cents` per 4x8 plywood sheet installed, `tarp_rate_per_sqft_cents` per tarped square foot, `fence_rate_per_linear_ft_cents` per linear foot of temporary fence, `patrol_visit_fee_cents` as the base fee per patrol visit before the priority multiplier, `temp_power_daily_rate_cents` and `temp_lighting_daily_rate_cents` for temporary utility services, `generator_pool_units` as the aggregate number of generator units available market-wide (the hard cap on concurrent temporary power), and `removal_flat_fee_cents`, the flat fee billed on the final invoice for board-up removal.

Subcontractors are onboarded with just a `legal_name`. A new subcontractor starts with `status` set to `ACTIVE`, all three operational counters — `completed_job_count`, `breached_job_count`, `expired_offer_count` — at zero, and both reliability scores at 1.0000. The platform maintains `active_assignment_count`, the number of the subcontractor's own assignments currently in `ACCEPTED` or `ARRIVED` status, recomputed as assignments are accepted, completed, or cancelled. Two reliability variants are computed from the counters and kept in lockstep with them. The lenient score, `reliability_score_lenient`, is the ratio of `completed_job_count` to the sum of `completed_job_count` and `breached_job_count`, and measures only the punctuality of completed work — it is the score the dispatch selector ranks by. The strict score, `reliability_score_strict`, divides `completed_job_count` by the sum of all three counters, additionally penalizing offers that lapsed unanswered; it is surfaced on the subcontractor's profile for suspension review. For either variant, an empty denominator yields exactly 1.0000, both are rounded half up to four decimal places, and the strict variant never exceeds the lenient one whenever the subcontractor has at least one expired offer.

A `PlatformAdmin` may suspend or reinstate a subcontractor by patching its `status`. Suspension is deliberately violent: every assignment of that subcontractor in `OFFERED`, `ACCEPTED`, or `ARRIVED` status is cancelled, and each of those cancellations itself runs the offer cascade of §3.2, which may regress the affected job all the way back to `INTAKE`; notably, suspension-driven cancellations do not increment `expired_offer_count`. The subcontractor's coverage rows flip to `SUSPENDED` alongside. Reinstatement flips the coverage rows back to `ACTIVE` but never resurrects previously cancelled assignments — the work has already been re-offered.

**Coverage** is the many-to-many join between subcontractors and markets: granting coverage takes a `subcontractor_id`, a `market_id`, a `max_concurrent_jobs` cap on that subcontractor's simultaneously active assignments in that market, and a `rank` expressing dispatcher-pinned preference within the market, where a lower value is preferred. A coverage row for a pair that already exists is rejected with `ERR_DUPLICATE_COVERAGE`. A row's `status` is not independently managed — it mirrors the subcontractor's `status`, moving to `SUSPENDED` and back with it. The coverage ledger can be listed filtered by `subcontractor_id` or `market_id`.

Customers and properties complete the picture. A **customer** is registered with a `full_name`, an `email`, and a `kind` of either `OWNER` or `ADJUSTER` — property owners and the insurance adjusters who act on their behalf share the same entity. A **property** is registered for a customer in a market with an `address_line` and a `wind_zone` of `LOW` or `HIGH`; a `HIGH` wind zone doubles the plywood requirement of every boarded opening, as detailed in §3.5. Properties can be listed filtered by `customer_id` or `market_id`.

### 3.2. Job Intake, Dispatch, and the Offer Cycle

A `Dispatcher` opens a **job** by supplying the `property_id` of the damaged property, the `incident_type` (`FIRE`, `STORM`, or `VANDALISM`), and the `priority` (`P1`, `P2`, or `P3`). The priority is doubly load-bearing: it selects which of the market's SLA minute fields is snapshotted into the job's `sla_minutes` at creation, and it later selects the emergency multiplier applied to work rates and patrol fees. The job's `customer_id` is always derived from the property's owning customer — any client-supplied value is ignored. A new job enters `INTAKE` with `reported_at` stamped from the logical clock, `safety_cleared` and `compliance_breach` both false, and `total_planned_sheets` at zero. The job register can be listed filtered by `property_id`, `customer_id`, or `work_status`. Across its life a job's `work_status` walks the machine `INTAKE` → `DISPATCHED` → `ON_SITE` → `SECURED`, with `BREACH_HOLD` as a regression state, `READY_FOR_REMOVAL` and `REMOVED` as the wind-down states, and `CLOSED` as the sole terminal state; every transition, automatic or requested, increments the job's `version`.

Dispatching is the pivotal act, and it is gated before anything else on state: a dispatch attempted on a job not currently in `INTAKE` is rejected with `ERR_INVALID_STATE` — or `ERR_ALREADY_TERMINAL` for a `CLOSED` job — before any coverage pool is consulted. The dispatcher may pin a specific crew by supplying `subcontractor_id`, in which case three checks fire in order: the subcontractor must be `ACTIVE` (`ERR_SUBCONTRACTOR_SUSPENDED`), it must hold a coverage row in the job's market (`ERR_MARKET_MISMATCH`), and its `active_assignment_count` must be below that coverage row's `max_concurrent_jobs` (`ERR_CAPACITY_FULL`). When no `subcontractor_id` is supplied, the platform runs its selector over the market's pool: a candidate must be an `ACTIVE` subcontractor holding an `ACTIVE` coverage row in the market of the job's property, with `active_assignment_count` strictly below that row's `max_concurrent_jobs`; candidates are ranked by `reliability_score_lenient` descending, ties break toward the lower coverage `rank`, and any remaining tie falls back to the earlier `created_at` — an `id` is never used as a tie-break. An empty pool rejects the dispatch with `ERR_NO_COVERAGE`.

A successful dispatch creates the job's first **assignment** in `OFFERED` status and moves the job `INTAKE` → `DISPATCHED`, stamping `dispatched_at` from the clock; because a job can regress to `INTAKE` and be dispatched again, `dispatched_at` always reflects the most recent such transition. Each offer carries `offer_seq`, a per-job monotone sequence starting at 1 — every new offer, from dispatch or from the re-offer cascade, takes one more than the highest prior `offer_seq` of that job. The offer is stamped `offered_at` and given `offer_expires_at` exactly 30 minutes later. Dispatch returns the created assignment with a 201 status.

The offeree — and only the offeree, verified by comparing `X-User-ID` to the assignment's `subcontractor_id` (`ERR_NOT_ASSIGNEE`) — answers the offer with an `outcome` of `ACCEPT` or `DECLINE`, which stamps `responded_at`. Acceptance moves the assignment `OFFERED` → `ACCEPTED` and recomputes the subcontractor's `active_assignment_count` upward by one. Declining moves it `OFFERED` → `DECLINED` and triggers the auto re-offer cascade: the selector runs again for the job, now additionally excluding every subcontractor that already holds a `DECLINED`, `EXPIRED`, or `CANCELLED` offer on this job; on success the next `OFFERED` assignment is created and the job stays `DISPATCHED`, while an empty pool regresses the job `DISPATCHED` → `INTAKE`.

Offers lapse lazily: there is no background timer. Any respond or withdraw that arrives when the clock has passed `offer_expires_at` first flips the assignment `OFFERED` → `EXPIRED`, increments the subcontractor's `expired_offer_count`, fails the triggering call with `ERR_OFFER_EXPIRED`, and runs the same re-offer cascade as a decline. Answering at exactly the expiry instant still succeeds — the expiry check trips only strictly past the deadline. A `Dispatcher` may also withdraw an `OFFERED` or `ACCEPTED` assignment; withdrawal moves it to `CANCELLED`, recomputes the active count downward where the assignment had been accepted, excludes the withdrawn subcontractor from the retry, and runs the identical cascade — so withdrawing the last viable offer likewise sends the job back to `INTAKE`. One interaction is worth stating plainly: a suspended subcontractor never reaches the respond gate at all, because suspension has already cancelled its open offers, and acting on that terminal assignment fails with `ERR_ALREADY_TERMINAL`. Assignments terminate in `COMPLETED`, `DECLINED`, `EXPIRED`, or `CANCELLED`, and the register can be listed filtered by `job_id`, `subcontractor_id`, or `status`.

### 3.3. Crew Arrival and Response-Time Evaluation

When the assigned crew reaches the property, the assignee subcontractor checks the job in. The caller must be exactly the `subcontractor_id` of the job's currently `ACCEPTED` assignment (`ERR_NOT_ASSIGNEE`). Check-in moves that assignment `ACCEPTED` → `ARRIVED`, stamps `arrived_at`, moves the job `DISPATCHED` → `ON_SITE`, and performs the SLA evaluation. The response time, `response_minutes`, is the elapsed time between the job's `dispatched_at` and the assignment's `arrived_at`, expressed in whole minutes with partial minutes discarded. The flag `sla_breach` is set true only when `response_minutes` strictly exceeds the job's snapshotted `sla_minutes`; arriving in exactly the allotted minutes is compliant, not a breach. This flag is permanent and consequential: it decides, at securing completion, whether the subcontractor's `completed_job_count` or `breached_job_count` is incremented, which in turn feeds both reliability variants.

### 3.4. Safety Assessment and Hazard Clearance

No securing work may be declared complete until an independent set of eyes has cleared the structure. Any `ACTIVE` subcontractor other than the job's assignee may submit a **safety assessment** while the job is `ON_SITE` or in `BREACH_HOLD` (any other job state is rejected with `ERR_INVALID_STATE`). The creator's `X-User-ID` is recorded as the assessment's `assessor_subcontractor_id`; if that equals the job's assigned subcontractor, the submission is rejected with `ERR_SEGREGATION_OF_DUTIES` — the crew doing the work never grades its own site.

The assessment carries a `hazards` list whose members come from exactly five categories: `COLLAPSE`, `ELECTRICAL`, `GAS`, `WATER`, and `ASBESTOS`. Each category contributes a fixed weight to the structural risk score — collapse 45 points, electrical 25, gas 20, water 15, asbestos 10 — and the assessment's `structural_risk_score` is the sum of the weights of the listed hazards, capped at 100. The `hazard_level` derives from the score with inclusive lower bounds: `HIGH` at 70 or above, `MODERATE` at 30 or above but below 70, and `LOW` below 30. The flag `moderate_ppe_required` is true exactly when the level is `MODERATE`.

An assessment is born in `SUBMITTED` and is immediately and automatically reclassified: a score of 70 or more moves it to `MITIGATION_REQUIRED`, while anything below 70 moves it straight to `CLEARED`. Clearing sets the job's `safety_cleared` flag true, and if the job was sitting in `BREACH_HOLD`, that clearance is precisely what returns it `BREACH_HOLD` → `ON_SITE`. When mitigation is required, the original assessor — and only that assessor, else `ERR_FORBIDDEN` — later records completion with a `mitigation_note`, moving the assessment `MITIGATION_REQUIRED` → `CLEARED` with the same job-level effects. Assessments supersede one another: creating a new assessment for a job immediately moves any still-open prior assessment of that job — one in `SUBMITTED` or `MITIGATION_REQUIRED` — to `SUPERSEDED`. `CLEARED` and `SUPERSEDED` are the terminal states. The assessment register can be listed filtered by `job_id` or `assessor_subcontractor_id`.

### 3.5. Scoping the Work: Measurement and Material Quantities

The scope of work is a set of measured **scope items** added by a `Dispatcher`, permitted at any point until the job reaches `SECURED`. This is one of the two OCC-guarded writes in the system: the request must carry `expected_job_version` equal to the job's current `version`, or it is rejected with `ERR_STALE_VERSION` (see §2.9). Each item declares a `kind` — `BOARD`, `TARP`, or `FENCE` — and carries the measurement fields appropriate to that kind, each of which must be present and positive: `opening_count`, `width_in`, and `height_in` for board-up work, with `door_count` optional and defaulting to 0; `length_ft` and `width_ft` for tarping; and `linear_ft` for fencing. Missing or non-positive measurements for the item's kind are rejected with `ERR_INVALID_MEASUREMENT` (HTTP 422).

From these measurements the platform computes `planned_qty` and the `unit` it is expressed in. For `BOARD`, the total opening area is `opening_count` times `width_in` times `height_in` square inches, divided by 144 to obtain square feet; that area is divided by 32 — the coverage of one 4x8 plywood sheet — and rounded up to a whole number of base sheets; one additional framing sheet is added for each of the `door_count` door openings; if the property's `wind_zone` is `HIGH`, the total is doubled; and whenever at least one opening exists, the result is never allowed to fall below one sheet. Board items are expressed in `SHEETS`. For `TARP`, the damaged roof area `length_ft` times `width_ft` is multiplied by 1.25 to allow for overlap and anchoring, then rounded up to a whole square foot; tarp items are expressed in `SQFT`. For `FENCE`, `planned_qty` is simply `linear_ft` as measured, expressed in `LINEAR_FT`. New items are born in `PLANNED` status. Every scope addition advances the parent job's `version` by one, and the job's `total_planned_sheets` — the running sum of `planned_qty` over its `BOARD` items in `PLANNED` or `INSTALLED` status — is kept current as items are added, installed, or voided.

Installation is recorded by the assignee subcontractor, only while the parent job is `ON_SITE` (`ERR_INVALID_STATE` otherwise), by supplying the actual field measurements — the same optional measurement set accepted at planning time. The platform applies exactly the same quantity formula to the supplied measurements and records the result as `actual_qty`, moving the item `PLANNED` → `INSTALLED`. When a documentation package already exists for the job, its `required_photo_count` is recomputed at this moment (§3.8). A `Dispatcher` may void a `PLANNED` item — the compensating action for an erroneous add — while the job is in `INTAKE`, `DISPATCHED`, `ON_SITE`, or `BREACH_HOLD` (`ERR_INVALID_STATE` otherwise); voiding moves the item `PLANNED` → `VOIDED`, recomputes `total_planned_sheets` and the package's photo requirement when one exists, and advances the job's `version`. `INSTALLED` and `VOIDED` are terminal.

With every line installed, the assignee completes the securing. Four gates guard that declaration, in validation-precedence order: the caller must be the job's assignee subcontractor (`ERR_NOT_ASSIGNEE`); the job's `safety_cleared` flag must be true, meaning a cleared assessment is on file (`ERR_HAZARD_NOT_MITIGATED`); at least one scope item not in `VOIDED` status must exist (`ERR_SCOPE_EMPTY`); and every scope item not in `VOIDED` status must already be `INSTALLED` (`ERR_SCOPE_ITEMS_PENDING`). Success moves the job `ON_SITE` → `SECURED`, stamps `secured_at` from the clock — the instant that later anchors notification deadlines — and moves the crew's assignment `ARRIVED` → `COMPLETED`. At that moment the subcontractor's counters settle the SLA verdict rendered at check-in: `completed_job_count` grows by one when the assignment's `sla_breach` is false, otherwise `breached_job_count` does. Completing also resumes the job's temporary services — every service sitting in `PAUSED` returns to `ACTIVE` — which is what lifts a job out of the breach cycle described in §3.6 once it has been re-secured.

### 3.6. Temporary Power, Lighting, Patrols, and the Breach Cascade

Once a job is `SECURED`, a `Dispatcher` may stand up **temporary services** against it. Each service declares a `kind` of `POWER`, `LIGHTING`, or `PATROL`, and a requested window from `starts_at` to `ends_at`, the end strictly after the start. A `POWER` service draws `generator_units` — defaulting to 1 when omitted — from the market's generator pool: the sum of `generator_units` across all of the market's `POWER` services in `ACTIVE` or `PAUSED` status may never exceed the market's `generator_pool_units`, or creation is rejected with `ERR_GENERATOR_POOL_EXHAUSTED`. Power and lighting services snapshot their `daily_rate_cents` from the market's `temp_power_daily_rate_cents` or `temp_lighting_daily_rate_cents` at creation; patrol services carry a `daily_rate_cents` of 0 because patrols bill per visit instead. A service begins in `ACTIVE` status.

A `Dispatcher` deactivates a service from either `ACTIVE` or `PAUSED`, moving it to the terminal `COMPLETED` state and stamping `deactivated_at`. Billing is computed at that moment: the billable span runs from `starts_at` to whichever comes earlier of `ends_at` and `deactivated_at`; the span is converted to `billable_days` by rounding any partial day up to a whole day, with a hard floor of one day — exactly 24 hours bills one day, 25 hours bills two. Paused intervals do not subtract from the span: the equipment sits on site and the rental continues. The `service_total_cents` is then `billable_days` times the snapshotted `daily_rate_cents` — always zero for patrol.

**Patrol visits** are scheduled against a patrol service only — the new visit records the parent service's `temporary_service_id`, and scheduling one against a power or lighting service is rejected with `ERR_SERVICE_NOT_PATROL`. Each visit declares a half-open window from `window_start` to `window_end`; the end must be strictly after the start and strictly after the current clock at scheduling time, or the request is rejected with `ERR_VISIT_WINDOW_PAST`. Windows on the same service may not overlap: because the intervals are half-open, a new visit whose window merely touches an existing one — starting exactly when the other ends — is allowed, while any true overlap is rejected with `ERR_OVERLAP_CONFLICT`. At creation each visit is priced: its `fee_cents` is the market's `patrol_visit_fee_cents` multiplied by the parent job's priority multiplier (§3.8), rounded half up to whole cents, per visit, before any summation.

Visit outcomes are recorded by the assignee subcontractor of the parent job (`ERR_NOT_ASSIGNEE`). An `outcome` of `CHECKED_IN` is accepted only while the clock is inside the window — at or after `window_start` and strictly before `window_end` — and stamps `checked_in_at`; outside that window the call fails with `ERR_VISIT_NOT_DUE`. An `outcome` of `MISSED` is accepted only once the clock has reached or passed `window_end`, failing with `ERR_VISIT_NOT_DUE` before that. A missed visit starts the three-hop breach cascade: first the parent service moves `ACTIVE` → `PAUSED`; that pause drives the job `SECURED` → `BREACH_HOLD` and resets the job's `safety_cleared` to false, meaning a fresh safety assessment is required before the property can be re-secured; then every other service of the job still `ACTIVE` is paused as well. The platform also immediately spawns a replacement visit in `SCHEDULED` status whose window is the missed window shifted 24 hours later — both bounds moved by exactly one day — with its fee recomputed at creation. The cycle closes when the crew re-completes securing: that transition resumes every `PAUSED` service of the job back to `ACTIVE`. Visits terminate in `CHECKED_IN` or `MISSED`; services terminate only in `COMPLETED`.

### 3.7. Permits and Municipal Notification

Jurisdictional obligations are tracked as **permit cases**, opened by a `Dispatcher` with a `kind` of `PERMIT` or `NOTIFICATION`. Only one open case of each kind may exist per job — where open means `PENDING`, and additionally `FILED` for a permit awaiting a decision — and a second open case of the same kind is rejected with `ERR_PERMIT_CASE_OPEN`. A notification case may be opened only once the job is `SECURED`, because its `deadline_at` is anchored to that moment: the job's `secured_at` plus the market's `notification_deadline_hours`. A permit case carries no deadline; its `deadline_at` stays empty.

Filing is recorded by a `Dispatcher` supplying the municipal `confirmation_number`: the case moves `PENDING` → `FILED` with `filed_at` stamped, and its `is_late` flag is computed — true exactly when a notification was filed strictly after its `deadline_at`, always false for permits. A late filing is not a dead end: filing late clears the job's `compliance_breach` latch, but the market's `late_notification_fee_cents` remains billable, because the case's `penalty_billed` flag stays false until an invoice actually bills it (§3.8).

For permits, the authority's decision is recorded by a `PlatformAdmin` with a `decision` of `APPROVED` or `REJECTED` and an optional `decision_note`, moving the case `FILED` → `APPROVED` or `FILED` → `REJECTED`. Decisions exist for permits only — a notification's `FILED` state is terminal, and recording a decision against one is rejected with `ERR_INVALID_STATE`. A `REJECTED` permit is terminal for that case, but not for the job: once no open case of that kind remains, the dispatcher may open a replacement permit case.

Notifications that are never filed expire. When the logical clock passes a still-`PENDING` notification's `deadline_at` — swept proactively by the clock-set capability, and evaluated lazily when the case is read or when an invoice submission consults it — the case moves to `EXPIRED` and latches the job's `compliance_breach` flag true. That latch, per §3.8, blocks invoice submission until the late filing clears it. `FILED`, `APPROVED`, `REJECTED`, and `EXPIRED` are all terminal states.

### 3.8. Insurance Documentation and Invoicing

Every job has at most one **document package** — a second attempt is rejected with `ERR_DUPLICATE_PACKAGE` — created by a `Dispatcher` once the job has reached `SECURED` or any later state. The package aggregates the evidence insurers demand, tracked through three counters: `photo_count`, the number of `PHOTO` artifacts added; `authorization_signed`, true once an `AUTHORIZATION` artifact exists; and `measurement_sheet_recorded`, true once a `MEASUREMENT_SHEET` artifact exists. Alongside them sits `required_photo_count`, twice the number of the job's scope items currently in `INSTALLED` status, recomputed whenever a scope item is installed or voided. The package is born `INCOMPLETE` and promotes itself automatically to `COMPLETE` the moment all three conditions hold: the authorization is signed, the measurement sheet is recorded, and `photo_count` is at least `required_photo_count` — exactly meeting the photo requirement is sufficient. The zero-scope edge is deliberate: even when no scope items are installed and the photo requirement is therefore zero, the authorization and measurement sheet are still required before the package completes.

Artifacts are added by a `Dispatcher` naming the artifact `kind`, and this is the second OCC-guarded write: the request must carry `expected_package_version` equal to the package's current `version`, else it is rejected with `ERR_STALE_VERSION`. Artifacts are accepted only while the package is unlocked — once `LOCKED`, adds fail with `ERR_PACKAGE_LOCKED` — and each accepted artifact advances the package's `version` by one. The package's remaining lifecycle is slaved to billing: when an invoice of the parent job is submitted, the package moves `COMPLETE` → `LOCKED`; when that submitted invoice is disputed, it moves `LOCKED` → `AMENDED`, reopening it for corrective artifacts; and on resubmission it locks again, `AMENDED` → `LOCKED`.

**Invoices** are generated by a `Dispatcher` with a `variant` of `PROVISIONAL` or `FINAL`, and the variant must match the job's lifecycle: a `PROVISIONAL` requires the job to be `SECURED` and exists for insurance pre-authorization; a `FINAL` requires the job to be `REMOVED` and an existing `PROVISIONAL` invoice to serve as the variance baseline; any other combination is rejected with `ERR_INVOICE_VARIANT_INVALID`. Only one open invoice — one in `DRAFT`, `SUBMITTED`, or `DISPUTED` — may exist per job at a time (`ERR_INVOICE_OPEN_EXISTS`). A new invoice is born `DRAFT`, and every money field is computed once at creation and frozen into its `lines`, an array of snapshot objects each carrying a `label`, a `quantity`, a `unit`, a `rate_cents`, a `multiplier`, and a `line_cents`.

The computation follows a pinned evaluation order. First, the work lines: a provisional invoice bills every scope item not in `VOIDED` status at its `planned_qty`, while a final invoice bills only `INSTALLED` items at their `actual_qty`. Each line multiplies its quantity by the market rate for the item's kind (per sheet, per square foot, or per linear foot) and by the job's priority multiplier — 1.50 for `P1`, 1.25 for `P2`, 1.00 for `P3` — and the resulting `line_cents` is rounded half up to whole cents per line; the rounded lines are then summed into `work_subtotal_cents`. Second, the `service_subtotal_cents`: on a final invoice, the `service_total_cents` of every `COMPLETED` power or lighting service plus the sum of the per-visit `fee_cents` of all patrol visits in a terminal state (`CHECKED_IN` or `MISSED`); on a provisional invoice it is zero. Third, `removal_fee_cents`: the market's `removal_flat_fee_cents` on a final invoice, zero on a provisional. Fourth, `penalty_cents`: the market's `late_notification_fee_cents` whenever the job carries a late-`FILED` notification whose penalty has not yet been billed — billing it here flips that case's `penalty_billed` to true, so the penalty lands exactly once, on the first invoice created after the late filing — and zero otherwise. These four sum to `pre_discount_total_cents`. Fifth, the volume tier is looked up on that pre-discount total: at least 500,000 cents ($5,000.00) earns a 10% discount rate; at least 200,000 cents ($2,000.00) but below that earns 5%; below that, no discount. Sixth, `discount_cents` is the `work_subtotal_cents` multiplied by the tier percentage, rounded half up to whole cents — note the discount keys off the work subtotal even though the tier is keyed on the pre-discount total. Finally, `total_cents` is `pre_discount_total_cents` minus `discount_cents`.

Submission is the gate-laden step, and the gates run in the validation precedence of §2.7 — safety and regulatory before temporal before fiscal. In a market whose `permit_required` is set, an `APPROVED` permit case must exist on the job, else `ERR_PERMIT_NOT_APPROVED`. The job's document package must have reached completeness at least once — a package in `COMPLETE`, `LOCKED`, or `AMENDED` passes, and only a still-`INCOMPLETE` package fails with `ERR_DOCS_INCOMPLETE`. In a market whose `notification_required` is set, no notification case may still be `PENDING` (`ERR_NOTIFICATION_PENDING` — consulting the case at this point may lazily expire it first), and the job's `compliance_breach` latch must be clear (`ERR_NOTIFICATION_DEADLINE_EXPIRED`). Finally, for a `FINAL` invoice, its `work_subtotal_cents` may not exceed 120% of the provisional invoice's `work_subtotal_cents` — the provisional subtotal multiplied by 1.20 and rounded half up — unless the dispatcher supplies `variance_override` as true, else `ERR_VARIANCE_CAP_EXCEEDED`. A successful submission moves the invoice `DRAFT` → `SUBMITTED` (or, on resubmission, `DISPUTED` → `SUBMITTED`, re-running the identical gate set), stamps `submitted_at`, and locks the package (`COMPLETE` → `LOCKED`, or `AMENDED` → `LOCKED`).

The owning customer — `X-User-ID` must equal the job's `customer_id`, else `ERR_FORBIDDEN` — may dispute a submitted invoice, optionally supplying a `reason`; this moves the invoice `SUBMITTED` → `DISPUTED` and unlocks the package as `AMENDED`. Payment is recorded by a `Dispatcher` against a submitted invoice, moving it `SUBMITTED` → `PAID` and stamping `paid_at`. `PAID` is terminal.

### 3.9. Repair Verification, Removal, and Closure

The endgame begins when permanent repairs are done. The owning customer verifies the repair with an `outcome` of `VERIFIED`, moving the job `SECURED` → `READY_FOR_REMOVAL`; if the verification proves premature, the same customer retracts it with `REJECTED`, moving the job `READY_FOR_REMOVAL` → `SECURED` with the securing left in place. Both directions require `X-User-ID` to equal the job's `customer_id` (`ERR_FORBIDDEN` otherwise), and both advance the job's `version`.

Physical removal of the boards and tarps is then recorded by the assignee subcontractor (`ERR_NOT_ASSIGNEE`). Removal is blocked while any temporary service of the job is still `ACTIVE` or `PAUSED` — everything must be deactivated first, else `ERR_SERVICES_STILL_ACTIVE` — and success moves the job `READY_FOR_REMOVAL` → `REMOVED`. With the job `REMOVED`, the final invoice becomes issuable per §3.8. Closure is the last act and belongs to the `Dispatcher`: the job must carry at least one `FINAL` invoice, and every invoice of the job must be `PAID`, or the close is rejected with `ERR_INVOICES_UNPAID`. A successful close moves the job `REMOVED` → `CLOSED`, the job's terminal state.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a new resource to a collection — including dispatching a job (which creates the offer assignment) and generating an invoice — return `201 Created`. Operations that act on an existing resource without creating a new one — check-ins, completions, filings, decisions, submissions, disputes, payments, deactivations, withdrawals, verifications, and the clock — return `200 OK`. All read endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/markets` | Create a market with SLA matrix, jurisdiction flags, and rate card | PlatformAdmin |
| GET | `/markets/{id}` | Get a market | All authenticated roles |
| POST | `/subcontractors` | Onboard a subcontractor (status ACTIVE, counters 0, reliability scores 1.0000) | PlatformAdmin |
| GET | `/subcontractors/{id}` | Get a subcontractor including computed counters and both reliability variants | All authenticated roles |
| PATCH | `/subcontractors/{id}` | Suspend or reinstate a subcontractor; suspension cascades to open assignments and their jobs | PlatformAdmin |
| POST | `/coverages` | Grant a subcontractor coverage in a market | PlatformAdmin |
| GET | `/coverages/{id}` | Get a coverage row | All authenticated roles |
| GET | `/coverages` | List coverage rows, filterable by subcontractor or market | All authenticated roles |
| POST | `/customers` | Register a customer (property owner or insurance adjuster) | PlatformAdmin |
| GET | `/customers/{id}` | Get a customer | All authenticated roles |
| POST | `/properties` | Register a property for a customer in a market | PlatformAdmin |
| GET | `/properties/{id}` | Get a property | All authenticated roles |
| GET | `/properties` | List properties, filterable by customer or market | All authenticated roles |
| POST | `/jobs` | Intake a new emergency job; customer derived from the property, SLA snapshotted from the market | Dispatcher |
| GET | `/jobs/{id}` | Get a job | All authenticated roles |
| GET | `/jobs` | List jobs, filterable by property, customer, or work status | All authenticated roles |
| POST | `/jobs/{id}/dispatch` | Dispatch the job: pin a subcontractor or run the selector; creates the OFFERED assignment and moves INTAKE to DISPATCHED | Dispatcher |
| POST | `/jobs/{id}/check-in` | Assignee crew arrives on site; computes response minutes and SLA breach | Subcontractor |
| POST | `/jobs/{id}/complete-securing` | Assignee marks securing complete; gated by cleared safety and fully installed scope | Subcontractor |
| POST | `/jobs/{id}/verify-repair` | Owning customer verifies (VERIFIED) or retracts (REJECTED) permanent repair completion | Customer |
| POST | `/jobs/{id}/record-removal` | Assignee records board-up removal after permanent repair verification | Subcontractor |
| POST | `/jobs/{id}/close` | Close the job once removal is done and all invoices (including a FINAL) are paid | Dispatcher |
| GET | `/assignments/{id}` | Get an assignment | All authenticated roles |
| GET | `/assignments` | List assignments, filterable by job, subcontractor, or status | All authenticated roles |
| POST | `/assignments/{id}/respond` | Offeree accepts or declines; answering after expiry transitions the offer to EXPIRED and fails | Subcontractor |
| POST | `/assignments/{id}/withdraw` | Dispatcher cancels an OFFERED or ACCEPTED assignment | Dispatcher |
| POST | `/jobs/{id}/safety-assessments` | Submit a hazard assessment; creator must be an ACTIVE subcontractor other than the assignee; supersedes any open assessment | Subcontractor |
| GET | `/safety-assessments/{id}` | Get a safety assessment | All authenticated roles |
| GET | `/safety-assessments` | List safety assessments, filterable by job or assessor | All authenticated roles |
| POST | `/safety-assessments/{id}/mitigate` | Assessment author records mitigation completion | Subcontractor |
| POST | `/jobs/{id}/scope-items` | Add a measured scope line (OCC-guarded on the job version); allowed until the job is SECURED | Dispatcher |
| GET | `/jobs/{id}/scope-items` | List scope items of a job | All authenticated roles |
| POST | `/scope-items/{id}/install` | Assignee records actual installed measurements; actual quantity recomputed with the same formula | Subcontractor |
| POST | `/scope-items/{id}/void` | Void a PLANNED scope item (compensating action for an erroneous add) | Dispatcher |
| POST | `/jobs/{id}/temporary-services` | Start a temporary power, lighting, or patrol service on a SECURED job; POWER draws from the market generator pool | Dispatcher |
| GET | `/jobs/{id}/temporary-services` | List temporary services of a job | All authenticated roles |
| GET | `/temporary-services/{id}` | Get a temporary service | All authenticated roles |
| POST | `/temporary-services/{id}/deactivate` | End a service; computes billable days (rounded-up days, paused time still bills) and the service total | Dispatcher |
| POST | `/temporary-services/{id}/patrol-visits` | Schedule a patrol visit inside a half-open window on a PATROL service; overlap rejected, adjacency allowed | Dispatcher |
| GET | `/temporary-services/{id}/patrol-visits` | List patrol visits of a service | All authenticated roles |
| POST | `/patrol-visits/{id}/check-in` | Record a patrol outcome; MISSED starts the breach cascade and spawns a +24h replacement visit | Subcontractor |
| POST | `/jobs/{id}/permit-cases` | Open a PERMIT or NOTIFICATION case; NOTIFICATION requires the job SECURED; one open case per kind per job | Dispatcher |
| GET | `/jobs/{id}/permit-cases` | List permit cases of a job | All authenticated roles |
| POST | `/permit-cases/{id}/file` | Record municipal filing with confirmation number; late filing clears the breach latch but stays billable as a penalty | Dispatcher |
| POST | `/permit-cases/{id}/record-decision` | Record the authority's decision on a filed PERMIT (APPROVED or REJECTED) | PlatformAdmin |
| POST | `/jobs/{id}/document-packages` | Create the job's insurance documentation package (exactly one per job); requires job SECURED or later | Dispatcher |
| GET | `/jobs/{id}/document-packages` | List the job's document packages (array of length 0 or 1) | All authenticated roles |
| POST | `/document-packages/{id}/artifacts` | Add an artifact (PHOTO, AUTHORIZATION, or MEASUREMENT_SHEET) to an unlocked package (OCC-guarded on the package version) | Dispatcher |
| POST | `/jobs/{id}/invoices` | Generate an invoice: PROVISIONAL while SECURED, FINAL once REMOVED; FINAL requires an existing PROVISIONAL; one open invoice per job | Dispatcher |
| GET | `/jobs/{id}/invoices` | List invoices of a job | All authenticated roles |
| GET | `/invoices/{id}` | Get an invoice | All authenticated roles |
| POST | `/invoices/{id}/submit` | Submit for insurance billing: permit, documentation, notification, and variance gates run in validation priority order; locks the document package | Dispatcher |
| POST | `/invoices/{id}/dispute` | Owning customer disputes a submitted invoice; unlocks the package as AMENDED | Customer |
| POST | `/invoices/{id}/record-payment` | Record insurer payment | Dispatcher |
| POST | `/_clock/set_current_utc` | Set the logical clock; advancing it sweeps lapsed PENDING notification cases to EXPIRED and latches the job's breach flag | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_ASSIGNEE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_MEASUREMENT` | 422 |
| `ERR_MARKET_MISMATCH` | 422 |
| `ERR_SERVICE_NOT_PATROL` | 422 |
| `ERR_VISIT_WINDOW_PAST` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_VISIT_NOT_DUE` | 409 |
| `ERR_NOTIFICATION_PENDING` | 409 |
| `ERR_NOTIFICATION_DEADLINE_EXPIRED` | 409 |
| `ERR_PERMIT_NOT_APPROVED` | 409 |
| `ERR_DOCS_INCOMPLETE` | 409 |
| `ERR_PACKAGE_LOCKED` | 409 |
| `ERR_HAZARD_NOT_MITIGATED` | 409 |
| `ERR_SCOPE_EMPTY` | 422 |
| `ERR_SCOPE_ITEMS_PENDING` | 409 |
| `ERR_NO_COVERAGE` | 409 |
| `ERR_CAPACITY_FULL` | 409 |
| `ERR_SUBCONTRACTOR_SUSPENDED` | 409 |
| `ERR_DUPLICATE_COVERAGE` | 409 |
| `ERR_DUPLICATE_PACKAGE` | 409 |
| `ERR_PERMIT_CASE_OPEN` | 409 |
| `ERR_INVOICE_OPEN_EXISTS` | 409 |
| `ERR_INVOICE_VARIANT_INVALID` | 409 |
| `ERR_OVERLAP_CONFLICT` | 409 |
| `ERR_GENERATOR_POOL_EXHAUSTED` | 409 |
| `ERR_SERVICES_STILL_ACTIVE` | 409 |
| `ERR_VARIANCE_CAP_EXCEEDED` | 409 |
| `ERR_INVOICES_UNPAID` | 409 |
