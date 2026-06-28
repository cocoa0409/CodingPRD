# Residential EV-Charger Install API — Product Requirements Document

## 1. Introduction

Bringing a Level 2 EV charger to an existing home is deceptively involved: before a single conduit is run, someone must confirm the electrical panel can carry the new continuous load, scope a charger that fits the available circuit, secure both a building permit and a utility interconnection, dispatch a licensed electrician, and — only after the work is done — pair the homeowner's app and chase down the federal and utility incentive dollars. This API is the orchestration backbone behind that journey. It models the Qmerit/Treehouse-style coordination layer that ties a homeowner, their property, a catalog of charger products, and a roster of licensed electricians into a single auditable install pipeline.

The central artifact is the **install job**, which the system tracks along two independent dimensions at once: a *workflow* dimension that walks the job from creation through site assessment, quoting, scheduling, physical installation, app activation, and closure; and a *compliance* dimension that independently tracks regulatory clearance through permitting and utility interconnection. The two dimensions are deliberately decoupled — a job can be fully quoted and scheduled while its permit is still pending — and they meet at exactly one gate: an install may not be physically completed until regulatory clearance is in hand. Layered on top are dual-method panel-load calculations drawn from the National Electrical Code, a circular-looking quote pricing engine, a federal-versus-utility incentive calculator with anti-double-dipping stacking caps, and a panel-upgrade referral path that can block a job until the home's service is upgraded.

This document specifies the complete contract: the data model, the precise calculation rules, the validation ordering, the role-based access boundaries, and the full state machines for every entity in the system. It is written for the engineers who will implement the service and must be read as the single source of truth.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API — with the sole exception of anonymous homeowner self-registration — must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes five roles, spelled exactly: `Homeowner`, `Coordinator`, `Electrician`, `UtilityReviewer`, and `Anonymous`.

A `Homeowner` is the property owner who requests installs, accepts or rejects quotes, activates the charger, decides on panel-upgrade referrals, and raises warranty tickets. The `Homeowner` role is entity-backed: when `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Homeowner` record, and ownership checks on any resource that traces back to a `Homeowner` compare that resource's owning foreign key to `X-User-ID`. Concretely, a `Property` carries a `homeowner_id`, and an `InstallJob` references a property; ownership-scoped homeowner actions therefore resolve the job's property to its owning homeowner and require that homeowner to equal `X-User-ID`. An owner mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`.

An `Electrician` is the dispatched field technician who departs to the site, completes installs, and performs warranty diagnosis and repair. The `Electrician` role is entity-backed: when `X-User-Role` is `Electrician`, `X-User-ID` is the `id` of the acting `Electrician`, and ownership checks on a `DispatchAssignment` compare its `electrician_id` to `X-User-ID`. An electrician acting on an assignment that is not their own is rejected with `ERR_NOT_RESOURCE_OWNER`.

A `Coordinator` is the operations role that drives site assessments, quoting, permit filing and adjudication, interconnection filing, dispatch booking, incentive processing, panel-upgrade completion, and job closure. When `X-User-Role` is `Coordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but does not compare it to any entity's `id`.

A `UtilityReviewer` is the utility-side reviewer who advances and decides interconnection requests. When `X-User-Role` is `UtilityReviewer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to an entity `id`.

`Anonymous` is the unauthenticated caller, permitted only to self-register as a homeowner. The `Anonymous` identity is opaque and carries no ownership.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a standard set of server-managed fields. Every resource is assigned an `id` — a server-minted UUID with no type prefix. Every resource records a `created_at`, an ISO 8601 UTC timestamp with three fractional digits captured at creation. Most resources additionally carry an `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation) and a `version` (an integer that begins at its initial value and increments by one on every mutation).

There is one deliberate exception. The `ChargerProduct` catalog entry is immutable after creation: it carries only `id` and `created_at`, and has neither an `updated_at` nor a `version`. Every other entity — `Homeowner`, `Property`, `Electrician`, `InstallJob`, `SiteAssessment`, `Quote`, `PermitApplication`, `InterconnectionRequest`, `DispatchAssignment`, `IncentiveClaim`, `PanelUpgradeReferral`, and `WarrantyTicket` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

Whenever the server mutates a resource, it refreshes that resource's `updated_at` and increments its `version` by one. This includes mutations the server performs on its own initiative — for example, when a child permit approval bubbles a parent job to regulatory clearance, the parent job's `updated_at` and `version` advance even though no client touched the job directly.

### 2.5. Nested Resource Validation and Referential Integrity

This API uses a flat URL layout: resources are addressed directly by their own identifier rather than through nested ownership paths, and inter-entity relationships are expressed through foreign-key body fields. When a request carries a path identifier, the server first confirms that the path-referenced resource exists, rejecting with `ERR_RESOURCE_NOT_FOUND` when it does not. When a request body carries foreign-key fields — `charger_product_sku`, `property_id`, `install_job_id`, or `electrician_id` — the server validates that each referenced resource exists, rejecting a dangling reference with `ERR_FK_NOT_FOUND`. Where multiple references appear in a single request, they are validated left-to-right, and the first missing reference determines the rejection.

### 2.6. Monetary and Electrical Precision

All monetary amounts in this system are integer cents; there are no fractional-cent values stored or returned. Where a calculation introduces a fractional cent — applying a percentage, a tax rate, or a discount — the result is rounded half up to the nearest whole cent. Electrical load quantities are integer volt-amperes (VA); where a calculation produces a fractional VA, the fractional term is rounded half up to a whole VA. The specific points at which rounding is applied are spelled out alongside each calculation in §3, and the order of rounding relative to summation is significant and is stated explicitly where it matters.

### 2.7. Optimistic Concurrency Control on the Install Job

Two operations mutate an install job in ways that must not silently clobber an intervening change, and both are guarded by optimistic concurrency control keyed on the install job's `version`.

The first is quote acceptance. A request to accept a sent quote must include `expected_install_job_version`, carrying the install job `version` the client last observed. If that value does not equal the target install job's current `version`, the acceptance is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412). The canonical case this protects against: a second sent quote on the same job legitimately supersedes a prior accepted quote, but the first acceptance already advanced the job's `version`, so a later acceptance still carrying the older expected version is rejected because the client's view predates the intervening mutation.

The second is re-scoping the charger product. A request to change an install job's scoped charger before quote acceptance must include `expected_install_job_version`. If it does not equal the job's current `version`, the re-scope is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412), because a stale expected version indicates the client's view predates an intervening mutation. No other endpoint accepts or requires a version field; operations not named here perform their mutations without an OCC check.

### 2.8. The Two-Dimensional Install-Job State Model

The install job is unusual in that it carries two independent status fields that evolve separately on the same record. The `workflow_status` field drives the physical install pipeline and progresses through `CREATED`, `ASSESSED`, `QUOTED`, `SCHEDULED`, `INSTALLED`, `ACTIVATED`, and finally either `CLOSED` or `CANCELLED`. The `compliance_status` field independently tracks regulatory clearance through `PENDING_REVIEW`, `PERMIT_PENDING`, `CLEARED`, and `BLOCKED`. A freshly created job begins at `workflow_status` `CREATED` and `compliance_status` `PENDING_REVIEW`. The two dimensions advance on their own triggers and intersect at exactly one point, described in §3: physically completing an install requires the compliance dimension to have reached `CLEARED`.

### 2.9. Regulatory Clearance and Bubble-Up Reconciliation

Regulatory clearance is not set by a single action; it emerges when two independent children both reach approval. Whenever a permit application on a job reaches `APPROVED`, and whenever an interconnection request on a job reaches `APPROVED`, the server re-evaluates the parent job's clearance gate. If the job is in `compliance_status` `PERMIT_PENDING` and there now exists both an `APPROVED` permit application and an `APPROVED` interconnection request on that job, the server bubbles the job's `compliance_status` up to `CLEARED`, refreshing the job's `updated_at` and incrementing its `version`. This reconciliation is server-initiated; no client request targets the job directly.

### 2.10. Circuit-to-Panel Sizing Discipline

A charger may only be scoped onto a property whose main service panel can physically accommodate the charger's branch-circuit breaker. Each `ChargerProduct` declares a `required_circuit_amps`, and the property's `main_breaker_amps` determines the largest circuit the panel may host: a 200 A panel supports up to a 60 A circuit, a 150 A panel supports up to a 50 A circuit, and a 100 A panel supports up to a 40 A circuit. If the scoped charger's `required_circuit_amps` exceeds the band allowed for the property's panel, the operation is rejected with `ERR_CIRCUIT_EXCEEDS_PANEL` (HTTP 422). This check is enforced both when an install job is first created and whenever its charger is re-scoped.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Homeowners, Properties, Electricians, and the Charger Catalog

The system's reference data is established before any install job exists. A prospective customer self-registers as a homeowner with no prior authentication, supplying an `email` (which serves as the login and contact address and must be unique across all homeowners), a `full_name`, and a two-letter uppercase `state_code` for their billing address. A homeowner — or a coordinator acting on their behalf — then records a `Property`: the `homeowner_id` of the owning homeowner, an `address_line`, the property's two-letter uppercase `state_code`, the `utility_territory_code` that governs interconnection in that area, the rated `main_breaker_amps` of the existing main service breaker (one of 100, 150, or 200), and the conditioned `floor_area_sqft` as a positive integer. The nominal split-phase `service_voltage` at the panel may be supplied but, when omitted, defaults to 240; it must be 240.

A coordinator curates the charger catalog. Each `ChargerProduct` carries a unique `sku`, a display `name`, a `rated_amps` continuous output rating (one of 32, 40, or 48), the `required_circuit_amps` branch-circuit breaker size the unit demands (one of 40, 50, or 60, reflecting NEC's 125% continuous-load sizing), and an `msrp_cents` hardware list price in non-negative integer cents.

A coordinator also registers the electrician roster. Each `Electrician` is recorded with a `full_name`, a two-letter uppercase `license_state_code` naming the state in which they are licensed (only properties in that state are serviceable by them), and an optional `max_daily_jobs` cap that, when omitted, defaults to 2 and must be a positive integer. Each electrician carries a `status` that begins at `ACTIVE` and may be `ACTIVE` or `SUSPENDED`; a suspended electrician cannot be booked. For test-driving, an administrative capability lets a coordinator set an electrician's `status` directly so that suspension-gated paths are reachable from an empty database.

When request bodies for any of these create operations omit a required field, carry a value of the wrong type, or carry an enum value outside its permitted set, the request is rejected with `ERR_INVALID_REQUEST`. Numeric inputs that fall outside their declared bounds — a `main_breaker_amps` not in the permitted set, or a window minute outside its range — are rejected with `ERR_VALIDATION_LIMIT`.

### 3.2. Opening an Install Job and Assessing the Panel

A homeowner or coordinator opens an install job by supplying the `property_id` of the site being electrified and the `charger_product_sku` of the charger being scoped. The job is born with `workflow_status` `CREATED` and `compliance_status` `PENDING_REVIEW`. At creation time the circuit-to-panel sizing discipline of §2.10 is enforced against the property's panel, so a charger whose breaker is too large for the panel is rejected outright. The scoped charger remains mutable until a quote is accepted: a coordinator may re-scope it to a different `charger_product_sku`, which re-runs the same panel-sizing check and is guarded by the install-job OCC of §2.7.

Before the job can advance, a coordinator records a **site assessment** against it, naming the `property_id` and the `install_job_id` it feeds, and selecting an `assessment_method` of either `STANDARD_220_83` or `LOAD_STUDY_220_87`. The assessment also captures `declared_fixed_appliance_va`, the summed nameplate VA of fixed appliances such as the range, dryer, water heater, and HVAC (a non-negative integer used by the standard method), and `max_measured_demand_va`, the peak measured demand over the metering window (a non-negative integer that defaults to 0 and is used by the load-study method). A new assessment is born in `DRAFT` status.

Upon creation — and again whenever the assessment is re-read — the system computes the property's existing electrical demand and the panel's spare capacity, recording them on the assessment. First, the **panel capacity** is the property's `service_voltage` multiplied by its `main_breaker_amps` (for example, a 240-volt, 100-amp service yields 24,000 VA). The **existing demand**, stored as `existing_demand_va`, then depends on the chosen method:

- Under `STANDARD_220_83`, the system sums four load components: a general lighting load of the property's `floor_area_sqft` multiplied by 3 VA per square foot; a small-appliance load of two circuits at 1,500 VA each; a laundry load of 1,500 VA; and the `declared_fixed_appliance_va`. It then applies NEC 220.83(A) demand factors: the first 8,000 VA of that combined total counts at 100%, and the remainder above 8,000 VA counts at 40%. Concretely, `existing_demand_va` equals 8,000 plus the result of multiplying 0.40 by the amount of the combined total that exceeds 8,000, with that fractional term rounded half up to a whole VA.
- Under `LOAD_STUDY_220_87`, the system takes 125% of the metered peak: `existing_demand_va` equals 1.25 multiplied by `max_measured_demand_va`, rounded half up to a whole VA. Because the load-study method works from a single measured peak rather than summed nameplate loads, it tends to report a lower existing demand than the standard method — so the same property can be found to fit a charger under the load-study method yet not fit it under the standard method.

The **spare capacity**, stored as `spare_capacity_va`, is the panel capacity minus `existing_demand_va`. The system then computes the **charger's continuous draw**: 1.25 multiplied by the scoped `ChargerProduct`'s `rated_amps` multiplied by the property's `service_voltage`, rounded half up to a whole VA (the 125% continuous-load factor again). The boolean `charger_fits` is true exactly when `spare_capacity_va` is greater than or equal to that required continuous VA — the boundary is inclusive, so a spare capacity exactly equal to the required draw counts as fitting. This computation reads only the single assessment row, its property, and the install job's scoped charger product; it never aggregates across sibling assessments.

### 3.3. Accepting the Assessment, Panel-Upgrade Referrals, and the Compliance Block

A coordinator accepts a draft assessment to advance the job. Acceptance is permitted only when the install job is in `workflow_status` `CREATED` and the assessment in question belongs to that job and is itself in `DRAFT` status; otherwise the request is rejected with `ERR_INVALID_STATE`. On acceptance, the assessment moves to `ACCEPTED`, and any other assessment on the same job that was previously `ACCEPTED` is moved to `SUPERSEDED`. The job's `requires_panel_upgrade` flag is set to the logical negation of the accepted assessment's `charger_fits` — that is, it becomes true precisely when the chosen method reported insufficient spare capacity. Finally the job's `workflow_status` advances from `CREATED` to `ASSESSED`, refreshing `updated_at` and incrementing `version`.

When acceptance determines that a panel upgrade is required, a cascade fires: the system creates a `PanelUpgradeReferral` against the job (carrying its `install_job_id`, a `recommended_main_amps` of either 150 or 200, and a `status` of `OPEN`). The very act of creating that referral drives the job's compliance dimension: a job in `compliance_status` `PENDING_REVIEW` is moved to `BLOCKED`, again refreshing `updated_at` and incrementing `version`. A `BLOCKED` job cannot begin permitting, which is the intended serialization point between a capacity shortfall and any regulatory work.

The homeowner decides the referral's fate. From `OPEN`, the homeowner may accept it (moving it to `ACCEPTED`) or decline it (moving it to `DECLINED`, a terminal outcome). Once accepted, a coordinator marks the upgrade complete, which is permitted only when the referral is in `ACCEPTED` status and the job's `compliance_status` is `BLOCKED`. Completion moves the referral to `COMPLETED`, writes the referral's `recommended_main_amps` onto the property's `main_breaker_amps`, clears the job's `requires_panel_upgrade` back to false, and returns the job's `compliance_status` from `BLOCKED` to `PENDING_REVIEW`, refreshing `updated_at` and incrementing the job's `version`. Acting on a referral from a state in which the requested transition is undefined is rejected with `ERR_INVALID_STATE`. Coordinators and homeowners may read referrals, optionally filtered by `install_job_id`.

### 3.4. Pricing the Job: Quotes, Discounts, Tax, and the Permit Fee

A coordinator prepares a `Quote` for a job, supplying the `install_job_id`, a non-negative `labor_cents` line, and `parts_line_cents` — an ordered list of taxable parts line amounts, each a non-negative integer in cents. A new quote is born in `DRAFT` status, and its totals are computed immediately on creation, recomputed whenever the quote is revised, and recomputed on re-read.

The pricing reads only the single quote row and proceeds in a pinned order, because the figures appear circular at first glance — the total depends on the permit fee, the permit fee depends on the post-discount net, the net depends on the discount, and the discount depends on the subtotal:

1. The `base_subtotal_cents` is `labor_cents` plus the sum of all `parts_line_cents` entries.
2. A volume discount is keyed on that subtotal. When `base_subtotal_cents` is at least 200,000 the discount rate is 10%; otherwise, when it is at least 100,000 the discount rate is 5%; otherwise the discount rate is 0%. The `discount_cents` is the chosen rate multiplied by `base_subtotal_cents`, rounded half up. (The boundary is inclusive: a subtotal of exactly 200,000 selects the 10% tier, not the 5% tier.) The **net after discount** is `base_subtotal_cents` minus `discount_cents`.
3. The `permit_fee_cents` is keyed on that post-discount net: when the net is at least 150,000 the permit fee is 20,000; otherwise, when it is at least 90,000 the permit fee is 15,000; otherwise the permit fee is 12,000.
4. The sales tax, stored as `tax_cents`, is computed over the parts lines only — labor is never taxed. The order of operations is pinned: the tax rate of 8.25% (0.0825) is applied to each individual entry in `parts_line_cents`, each per-line result is rounded half up to whole cents, and only then are the rounded per-line amounts summed. Rounding per line before summing can differ from summing first and rounding once by a cent, and this system pins the per-line method.
5. The `quote_total_cents` is the net after discount plus `tax_cents` plus `permit_fee_cents`.

A coordinator sends a draft quote to the homeowner, which is permitted only when the quote is in `DRAFT` status and the job is in `workflow_status` `ASSESSED`; the quote moves from `DRAFT` to `SENT`. The homeowner then either accepts or rejects a sent quote. Acceptance — which requires `expected_install_job_version` and is guarded by the install-job OCC of §2.7 — is permitted only when the quote is `SENT` and the job is in `workflow_status` `ASSESSED`. On acceptance the quote moves to `ACCEPTED`, any other quote on the same job that was in `ACCEPTED` or `SENT` status is moved to `REJECTED`, and the job's `workflow_status` advances from `ASSESSED` to `QUOTED`, refreshing `updated_at` and incrementing `version`. Rejection of a sent quote moves it from `SENT` to `REJECTED`. A rejected quote is not dead: a coordinator may revise it, supplying a fresh `labor_cents` and/or `parts_line_cents`, which moves it from `REJECTED` back to `DRAFT` and recomputes all totals from the new inputs. This revision loop — `REJECTED` to `DRAFT` to `SENT` to `REJECTED` — may repeat. A quote acceptance whose `SENT` precondition is unmet is rejected with `ERR_INVALID_STATE`.

### 3.5. Permitting and Utility Interconnection — the Compliance Track

The compliance dimension runs in parallel with quoting and scheduling. A coordinator files a permit application against a job, supplying the `install_job_id` and the AHJ `jurisdiction_code`. Filing is permitted only when the job's `compliance_status` is `PENDING_REVIEW` and the job does not require a panel upgrade — a job whose `requires_panel_upgrade` is true (and is therefore `BLOCKED`) cannot start permitting and is rejected with `ERR_PANEL_UPGRADE_REQUIRED` (HTTP 409). A successful filing creates the permit in `SUBMITTED` status and advances the job's `compliance_status` from `PENDING_REVIEW` to `PERMIT_PENDING`, refreshing `updated_at` and incrementing `version`.

A submitted permit follows a corrections-capable cycle. A coordinator may approve it, moving it from `SUBMITTED` to `APPROVED` and triggering the bubble-up clearance re-evaluation of §2.9. Alternatively a coordinator may request corrections, which increments the permit's `correction_rounds` by one and moves it from `SUBMITTED` to `CORRECTIONS_REQUESTED`. From there a coordinator resubmits: if `correction_rounds` is fewer than 3, the permit returns to `SUBMITTED`; but if `correction_rounds` has reached 3 or more, the resubmission instead auto-rejects the permit, moving it to the terminal `REJECTED` state. The submitted-and-corrections cycle may repeat until that rejection threshold is crossed. Acting on a permit already in the terminal `REJECTED` state is rejected with `ERR_PERMIT_REJECTED_FINAL`, and any transition attempted from a state in which it is undefined is rejected with `ERR_INVALID_STATE`.

In parallel, a coordinator files an interconnection request, supplying the `install_job_id`, the `utility_territory_code` the request is filed with, and the `requested_load_amps` (the charger's continuous-rated amps being added to the service, a positive integer). The request is born in `FILED` status. A utility reviewer begins review, moving it from `FILED` to `UNDER_REVIEW`. From `UNDER_REVIEW` the reviewer either approves or denies it. Approval requires that the request's `utility_territory_code` equal the property's `utility_territory_code`; a mismatch is rejected with `ERR_TERRITORY_MISMATCH` (HTTP 422). A valid approval moves the request to `APPROVED` and triggers the bubble-up clearance re-evaluation of §2.9. Denial moves it from `UNDER_REVIEW` to the terminal `DENIED` state. As described in §2.9, the job reaches `compliance_status` `CLEARED` only once both an approved permit and an approved interconnection request coexist on it.

### 3.6. Booking the Electrician and Performing the Install

With the job quoted, a coordinator books a dispatch. Booking requires the job to be in `workflow_status` `QUOTED` and creates a `DispatchAssignment` carrying the `install_job_id`, the assigned `electrician_id`, the `window_date` (an ISO 8601 UTC date-time whose date portion is the booking day), the `window_start_minute` (the start offset in minutes from midnight UTC, in the range 0 through 1439), and the `window_end_minute` (the end offset in minutes from midnight UTC, in the range 1 through 1440, and strictly greater than `window_start_minute`; the window is the half-open interval from start up to but not including end). A `window_end_minute` that is not strictly greater than `window_start_minute` is rejected with `ERR_INVALID_REQUEST`, and a window minute outside its declared range is rejected with `ERR_VALIDATION_LIMIT`. A successful booking creates the assignment in `BOOKED` status and advances the job's `workflow_status` from `QUOTED` to `SCHEDULED`, refreshing `updated_at` and incrementing `version`.

Booking is gated by a sequence of constraints. The electrician must be `ACTIVE`; booking a `SUSPENDED` electrician is rejected with `ERR_ELECTRICIAN_SUSPENDED` (HTTP 409). The electrician's `license_state_code` must equal the property's `state_code`, since only properties in the licensed state are serviceable; a mismatch is rejected with `ERR_ELECTRICIAN_OUT_OF_TERRITORY` (HTTP 422). The new window must not overlap any non-cancelled assignment already held by the same electrician on the same `window_date`; overlap is evaluated on the half-open interval (two windows overlap when one starts before the other ends and vice versa, with a shared endpoint not counting as overlap), and a conflict is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409). Finally the electrician's daily capacity is checked: counting that electrician's assignments on the same `window_date` whose status is `BOOKED` or `EN_ROUTE`, the booking is allowed only when that count is strictly fewer than the electrician's `max_daily_jobs`. A count equal to the cap is at capacity and is rejected with `ERR_DAILY_CAPACITY_EXCEEDED` (HTTP 409); a count one below the cap is still allowed.

On the install day, the assigned electrician departs, moving the assignment from `BOOKED` to `EN_ROUTE`; this action is owner-scoped, so the acting electrician must be the assignment's own electrician. From `EN_ROUTE` the electrician completes the install. Completion is the single point where the two install-job dimensions intersect: it requires the assignment to be `EN_ROUTE` and the job's `compliance_status` to be `CLEARED`. If compliance has not cleared, completion is rejected with `ERR_COMPLIANCE_NOT_CLEARED` (HTTP 409). On a valid completion the assignment moves to `COMPLETED`, the system mints a one-time `activation_pairing_code` onto the job, and the job's `workflow_status` advances from `SCHEDULED` to `INSTALLED`, refreshing `updated_at` and incrementing `version`.

A booked assignment may be cancelled by a coordinator before departure: from `BOOKED` it moves to `CANCELLED`, and if the parent job is currently in `workflow_status` `SCHEDULED`, the job reverts from `SCHEDULED` back to `QUOTED`, refreshing `updated_at` and incrementing `version`. Transitions attempted from undefined states are rejected with `ERR_INVALID_STATE`.

### 3.7. Activation, Closure, and Cancellation of the Install Job

Once installed, the homeowner activates the job by pairing the app. Activation requires the job to be in `workflow_status` `INSTALLED` and the submitted `pairing_code` to equal the job's minted `activation_pairing_code`. On success the job advances from `INSTALLED` to `ACTIVATED`, refreshing `updated_at` and incrementing `version`. This action is owner-scoped to the job's homeowner.

A coordinator closes an activated job. Closure requires the job to be in `workflow_status` `ACTIVATED` and no warranty ticket on the job to be in `OPEN`, `DIAGNOSING`, or `AWAITING_PARTS` status; an unresolved warranty ticket blocks closure and is rejected with `ERR_OPEN_WARRANTY_BLOCKS_CLOSE`. A valid closure advances the job from `ACTIVATED` to the terminal `CLOSED` state, refreshing `updated_at` and incrementing `version`.

A homeowner may cancel a job while its `workflow_status` is `CREATED`, `ASSESSED`, `QUOTED`, or `SCHEDULED`. Cancellation cascades: any dispatch assignment on the job in `BOOKED` or `EN_ROUTE` status is moved to `CANCELLED`, and any quote on the job in `DRAFT` or `SENT` status is moved to `REJECTED`. The job's `workflow_status` then moves to the terminal `CANCELLED` state, refreshing `updated_at` and incrementing `version`. Attempting to cancel from a state outside the permitted set is rejected with `ERR_INVALID_STATE`.

### 3.8. Incentive Claims: Federal, Utility, and the Stacking Cap

After a job has been installed and activated, a coordinator may file incentive claims against it. A claim names the `install_job_id`, the `program_kind` (either `FEDERAL_45W` or `UTILITY_REBATE`), and the `eligible_cost_cents` cost basis (a non-negative integer). For utility claims it also carries a `utility_program_tier` (either `BASIC` or `PREMIUM`, defaulting to `BASIC`, and ignored for federal claims) and an `includes_panel_upgrade` boolean (defaulting to false) indicating whether the install included a panel upgrade. A claim is born in `DRAFT` status, and its `award_cents` is computed on creation and on every re-read.

A claim may only be submitted once the job has reached `workflow_status` `ACTIVATED` or `CLOSED`; submitting (or, equivalently, the analogous gate applied at claim creation) before the job is activated is rejected with `ERR_JOB_NOT_ACTIVATED`. From `DRAFT` a coordinator submits the claim (moving it to `SUBMITTED`), then marks it paid (moving it from `SUBMITTED` to `PAID`), and may later reverse a paid claim (moving it from `PAID` to the terminal `REVERSED` state). Reversal is a compensating action: the claim's `award_cents` is conceptually clawed back so that the conservation of awarded incentive across the job is preserved. Each of these transitions is undefined from any other state and is rejected with `ERR_INVALID_STATE` when attempted out of order.

The `award_cents` is computed in a pinned evaluation order — the federal branch first, then the utility branch, then the stacking cap:

- For a `FEDERAL_45W` claim, the award is 30% of the `eligible_cost_cents`, rounded half up, but never more than 100,000 cents (a one-thousand-dollar cap). The federal branch ignores the tier, the panel-upgrade adder, and the stacking cap entirely — it is simply the smaller of the rounded 30% figure and the 100,000-cent cap.
- For a `UTILITY_REBATE` claim, the system starts from a base: 50,000 cents when the `utility_program_tier` is `PREMIUM`, otherwise 25,000 cents for `BASIC`. It then adds a panel-upgrade adder of 30,000 cents when `includes_panel_upgrade` is true, and 0 otherwise. Call that sum the raw utility award. The stacking cap then protects against over-subsidizing: the system computes a cap of 80% of the `eligible_cost_cents`, rounded half up, and looks up the federal award already in play on this same job — that is, the `award_cents` of this job's `FEDERAL_45W` claim whose status is `SUBMITTED` or `PAID` (and if more than one qualifies, the earliest by `created_at`), treating it as 0 if none exists. If the existing federal award plus the raw utility award exceeds the cap, the federal award is protected and the utility award absorbs the entire reduction: the utility `award_cents` becomes the cap minus the existing federal award, but never below 0. Otherwise the utility `award_cents` is simply the raw utility award. Note that the very same utility inputs, evaluated without any qualifying federal sibling, yield the full raw utility award.

A utility claim is allowed to clamp down to a reduced award under the stacking cap, but a `UTILITY_REBATE` claim whose clamped award computes to exactly 0 is non-fundable and is rejected at creation with `ERR_INCENTIVE_FULLY_ABSORBED` (HTTP 422). A coordinator may read and list claims, optionally filtered by `install_job_id`.

### 3.9. Warranty Service After Activation

Once a job has reached `workflow_status` `ACTIVATED` or `CLOSED`, the homeowner may open a `WarrantyTicket` against it, supplying the `install_job_id` and a `summary` of the defect. Opening a ticket before the job has been activated is rejected with `ERR_JOB_NOT_ACTIVATED`. A ticket is born in `OPEN` status and tracks a `reopen_count` that begins at 0.

An electrician works the ticket through a diagnosis cycle. Diagnosis moves it from `OPEN` to `DIAGNOSING`, but only while the job remains in `ACTIVATED` or `CLOSED`. From `DIAGNOSING` the electrician may order parts (moving it to `AWAITING_PARTS`) and later record parts received (moving it back to `DIAGNOSING`); this diagnosing-and-awaiting-parts loop may repeat. From `DIAGNOSING` the electrician resolves the ticket, moving it to `RESOLVED`. A homeowner may reopen a resolved ticket, which is permitted only while `reopen_count` is fewer than 2; reopening increments `reopen_count` by one and moves the ticket from `RESOLVED` back to `OPEN`. A reopen attempted once the ticket has already been reopened twice is rejected with `ERR_REOPEN_LIMIT_REACHED`. Finally a coordinator closes a resolved ticket, moving it from `RESOLVED` to the terminal `CLOSED` state. Any of these transitions attempted from a state in which it is undefined is rejected with `ERR_INVALID_STATE`. Because an unresolved ticket blocks job closure (§3.7), warranty work is the natural tail of the job lifecycle.

### 3.10. Validation Ordering

When several checks could apply to a single request, they are evaluated in a fixed priority so that the rejection a client sees is deterministic. The order is: first, authentication — the presence of the `X-User-ID` and `X-User-Role` headers, failing with `ERR_UNAUTHENTICATED`; then role authorization for the operation, failing with `ERR_FORBIDDEN_ROLE`; then existence of every path- or body-referenced resource, validated left-to-right, failing with `ERR_RESOURCE_NOT_FOUND`; then existence of the specific foreign-key body fields on create endpoints (`charger_product_sku`, `property_id`, `install_job_id`, `electrician_id`), failing with `ERR_FK_NOT_FOUND`; then resource ownership for ownership-scoped actions (job activate, cancel, and close for the homeowner; dispatch depart and complete for the electrician), failing with `ERR_NOT_RESOURCE_OWNER`; then the requirement that the target be in a state from which the requested transition is defined, failing with `ERR_INVALID_STATE`; then the install-job OCC check on quote acceptance and re-scope, failing with `ERR_STALE_JOB_VERSION`; then the compliance-cleared gate on install completion, failing with `ERR_COMPLIANCE_NOT_CLEARED`; then the panel-upgrade gate on permit filing, failing with `ERR_PANEL_UPGRADE_REQUIRED`; then the electrician-active check on booking, failing with `ERR_ELECTRICIAN_SUSPENDED`; then the electrician-territory check on booking, failing with `ERR_ELECTRICIAN_OUT_OF_TERRITORY`; then the interconnection territory-match check on approval, failing with `ERR_TERRITORY_MISMATCH`; then the dispatch window-overlap check, failing with `ERR_WINDOW_OVERLAP`; then the daily-capacity check, failing with `ERR_DAILY_CAPACITY_EXCEEDED`; then the circuit-to-panel sizing check on job create and re-scope, failing with `ERR_CIRCUIT_EXCEEDS_PANEL`; then the fully-absorbed-incentive check, failing with `ERR_INCENTIVE_FULLY_ABSORBED`; and finally generic request-shape validation — required fields present, correct types and enums, and `window_end_minute` strictly greater than `window_start_minute` — failing with `ERR_INVALID_REQUEST`.

### 3.11. The Test-Driving Clock

The server runs on a logical clock used to evaluate any date-dependent rule. At startup the clock reads exactly `2026-04-01T00:00:00Z` and never falls back to wall-clock time. An administrative, coordinator-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant, which is the basis for date comparisons such as identifying same-day dispatch windows.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or transition an existing resource, and read operations, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Coordinator |
| POST | `/homeowners` | Register a homeowner | Anonymous |
| POST | `/properties` | Create a property owned by a homeowner | Homeowner, Coordinator |
| GET | `/properties/{id}` | Fetch a property | Homeowner, Coordinator |
| GET | `/properties` | List properties; filter by homeowner_id | Homeowner, Coordinator |
| POST | `/charger-products` | Create a charger catalog entry | Coordinator |
| GET | `/charger-products/{id}` | Fetch a charger product by sku | Homeowner, Coordinator |
| POST | `/electricians` | Register an electrician | Coordinator |
| GET | `/electricians/{id}` | Fetch an electrician | Coordinator, Electrician |
| POST | `/_electricians/{id}/set-status` | Test-driving: set an electrician's status | Coordinator |
| POST | `/install-jobs` | Create an install job for a property scoping a charger | Homeowner, Coordinator |
| GET | `/install-jobs/{id}` | Fetch an install job | Homeowner, Coordinator, Electrician |
| GET | `/install-jobs` | List install jobs; filter by property_id | Homeowner, Coordinator |
| PATCH | `/install-jobs/{id}/scope` | Re-scope the charger product before quote acceptance | Coordinator |
| POST | `/install-jobs/{id}/activate` | Pair the app and activate the job | Homeowner |
| POST | `/install-jobs/{id}/cancel` | Cancel a job | Homeowner |
| POST | `/install-jobs/{id}/close` | Close an activated job | Coordinator |
| POST | `/site-assessments` | Create a draft site assessment | Coordinator |
| GET | `/site-assessments/{id}` | Fetch a site assessment | Coordinator, Homeowner |
| GET | `/site-assessments` | List site assessments; filter by install_job_id or property_id | Coordinator, Homeowner |
| POST | `/site-assessments/{id}/accept` | Accept the assessment, advancing the job | Coordinator |
| POST | `/quotes` | Create a draft quote for a job | Coordinator |
| GET | `/quotes/{id}` | Fetch a quote | Coordinator, Homeowner |
| GET | `/quotes` | List quotes; filter by install_job_id | Coordinator, Homeowner |
| POST | `/quotes/{id}/send` | Send a draft quote to the homeowner | Coordinator |
| POST | `/quotes/{id}/accept` | Accept a sent quote (OCC on install job) | Homeowner |
| POST | `/quotes/{id}/reject` | Reject a sent quote | Homeowner |
| POST | `/quotes/{id}/revise` | Revise a rejected quote back to draft | Coordinator |
| POST | `/permit-applications` | File a permit for a job | Coordinator |
| GET | `/permit-applications/{id}` | Fetch a permit application | Coordinator |
| GET | `/permit-applications` | List permit applications; filter by install_job_id | Coordinator |
| POST | `/permit-applications/{id}/approve` | Approve a permit | Coordinator |
| POST | `/permit-applications/{id}/request-corrections` | Request corrections on a permit | Coordinator |
| POST | `/permit-applications/{id}/resubmit` | Resubmit a permit after corrections | Coordinator |
| POST | `/interconnection-requests` | File a utility interconnection request | Coordinator |
| GET | `/interconnection-requests/{id}` | Fetch an interconnection request | Coordinator, UtilityReviewer |
| GET | `/interconnection-requests` | List interconnection requests; filter by install_job_id | Coordinator, UtilityReviewer |
| POST | `/interconnection-requests/{id}/start-review` | Utility begins review | UtilityReviewer |
| POST | `/interconnection-requests/{id}/approve` | Utility approves the request | UtilityReviewer |
| POST | `/interconnection-requests/{id}/deny` | Utility denies the request | UtilityReviewer |
| POST | `/dispatch-assignments` | Book an electrician for a quoted job | Coordinator |
| GET | `/dispatch-assignments/{id}` | Fetch a dispatch assignment | Coordinator, Electrician |
| GET | `/dispatch-assignments` | List dispatch assignments; filter by install_job_id or electrician_id | Coordinator, Electrician |
| POST | `/dispatch-assignments/{id}/depart` | Electrician departs | Electrician |
| POST | `/dispatch-assignments/{id}/complete` | Electrician completes the install | Electrician |
| POST | `/dispatch-assignments/{id}/cancel` | Cancel a booked assignment | Coordinator |
| POST | `/incentive-claims` | Create an incentive claim | Coordinator |
| GET | `/incentive-claims/{id}` | Fetch an incentive claim | Coordinator |
| GET | `/incentive-claims` | List incentive claims; filter by install_job_id | Coordinator |
| POST | `/incentive-claims/{id}/submit` | Submit a draft claim | Coordinator |
| POST | `/incentive-claims/{id}/pay` | Mark a submitted claim paid | Coordinator |
| POST | `/incentive-claims/{id}/reverse` | Reverse a paid claim | Coordinator |
| GET | `/panel-upgrade-referrals/{id}` | Fetch a panel-upgrade referral | Coordinator, Homeowner |
| GET | `/panel-upgrade-referrals` | List panel-upgrade referrals; filter by install_job_id | Coordinator, Homeowner |
| POST | `/panel-upgrade-referrals/{id}/accept` | Homeowner accepts the referral | Homeowner |
| POST | `/panel-upgrade-referrals/{id}/decline` | Homeowner declines the referral | Homeowner |
| POST | `/panel-upgrade-referrals/{id}/complete` | Coordinator marks the upgrade complete | Coordinator |
| POST | `/warranty-tickets` | Open a warranty ticket against an activated/closed job | Homeowner |
| GET | `/warranty-tickets/{id}` | Fetch a warranty ticket | Homeowner, Coordinator, Electrician |
| GET | `/warranty-tickets` | List warranty tickets; filter by install_job_id | Homeowner, Coordinator, Electrician |
| POST | `/warranty-tickets/{id}/diagnose` | Begin diagnosis | Electrician |
| POST | `/warranty-tickets/{id}/order-parts` | Order parts | Electrician |
| POST | `/warranty-tickets/{id}/parts-received` | Record parts received | Electrician |
| POST | `/warranty-tickets/{id}/resolve` | Resolve the ticket | Electrician |
| POST | `/warranty-tickets/{id}/reopen` | Homeowner reopens a resolved ticket | Homeowner |
| POST | `/warranty-tickets/{id}/close` | Coordinator closes a resolved ticket | Coordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_JOB_VERSION` | 412 |
| `ERR_COMPLIANCE_NOT_CLEARED` | 409 |
| `ERR_PANEL_UPGRADE_REQUIRED` | 409 |
| `ERR_ELECTRICIAN_OUT_OF_TERRITORY` | 422 |
| `ERR_TERRITORY_MISMATCH` | 422 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_DAILY_CAPACITY_EXCEEDED` | 409 |
| `ERR_CIRCUIT_EXCEEDS_PANEL` | 422 |
| `ERR_INCENTIVE_FULLY_ABSORBED` | 422 |
| `ERR_ELECTRICIAN_SUSPENDED` | 409 |
| `ERR_PERMIT_REJECTED_FINAL` | 409 |
| `ERR_REOPEN_LIMIT_REACHED` | 409 |
| `ERR_JOB_NOT_ACTIVATED` | 409 |
| `ERR_OPEN_WARRANTY_BLOCKS_CLOSE` | 409 |
| `ERR_VALIDATION_LIMIT` | 422 |
