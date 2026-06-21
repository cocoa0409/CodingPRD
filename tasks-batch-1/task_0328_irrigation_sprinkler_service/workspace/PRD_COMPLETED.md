# Irrigation Sprinkler Service API — Product Requirements Document

## 1. Introduction

Residential and commercial irrigation contractors juggle a tangle of moving parts: a property may host several irrigation systems, each system fans out into dozens of zones, and every zone carries its own hydraulic profile. On top of that physical inventory sits a service business — install and repair quotes, seasonal start-ups and winterization blowouts, controller programming, leak and head repairs, recurring maintenance plans, regulatory backflow testing, and the daily logistics of routing technicians from job to job. This API is the system of record for all of it.

The platform is built for four kinds of users working in concert. Back-office **Dispatchers** own the inventory and the books — they register customers, properties, systems, and zones, draft and send quotes, open work orders, and build the daily routes. **Technicians** are the field workers who map zones, draft and activate controller schedules, and drive the work orders assigned to them. **Customers** review and decide on the quotes for the properties they own. A subset of technicians act as certified **BackflowTesters**, recording the regulatory inspections that determine whether a property is compliant. The design goals are uncompromising bookkeeping (committed costs and route capacity must never drift), defensible safety and compliance gates (no uncertified backflow tests, no winterized systems started up out of season), and a routing model that survives concurrent edits without silently overwriting capacity.

Because the domain is fundamentally relational but topologically flat, every collection in this API lives at the top level and references its neighbours by identifier carried in the request body or query string. There is no nested ownership chain in the URL space — a zone is not addressed beneath its system, and a route stop is not addressed beneath its route. Relationships are expressed through the data, and the workflows in Section 3 describe how they bind together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 401). The system recognizes exactly four roles, spelled precisely as follows: `Dispatcher`, `Technician`, `Customer`, and `BackflowTester`. When a syntactically valid user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two of these roles are back-office capacities not tied to any persisted entity. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier; the server may record it but does not compare it to any entity's `id`. The other three identities are entity-backed and drive ownership checks. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare against `X-User-ID` — specifically, a Customer may only act on a quote whose Property's `customer_id` resolves to a Property they own. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting Technician; ownership checks on a work order compare the work order's `assigned_technician_id` to `X-User-ID`. When `X-User-Role` is `BackflowTester`, `X-User-ID` is likewise the `id` of the acting Technician (a technician operating in their inspection capacity), not tied to a separate entity. A failed ownership comparison on an entity-backed actor — a Customer acting on a property they do not own, or a Technician acting on a work order not assigned to them — is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, every list is returned sorted by the `created_at` timestamp in ascending order. List responses surface the pagination state inside the `meta` object of the envelope through the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every resource in this system — Customers, Technicians, Properties, irrigation systems, Zones, controller programs, service quotes, work orders, maintenance plans, backflow tests, Routes, and route stops — carries a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix, used for identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, stamped when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 on creation and increments by exactly one on every mutation. All twelve entity types in this system carry the full set of common fields; none of them omit `updated_at` or `version`.

These conventions hold even when the only thing that changed was a derived value. Whenever the server recomputes a computed field on a resource — a system's `committed_cost_cents`, a route's `stops_used`, a property's `compliance_status`, and so on — that recomputation is itself a mutation: it refreshes the affected resource's `updated_at` and increments its `version`.

### 2.5. Referential Resolution and Validation Ordering

Most write operations name one or more foreign resources, either through a path identifier or through a foreign-key field in the body. The system resolves these identifiers strictly left to right, in the order they appear in the path followed by the order they appear in the body, and rejects the request at the first identifier that does not resolve to an existing row. Each entity type has its own not-found error: an unresolved Customer yields `ERR_CUSTOMER_NOT_FOUND`, a Technician `ERR_TECHNICIAN_NOT_FOUND`, a Property `ERR_PROPERTY_NOT_FOUND`, an irrigation system `ERR_SYSTEM_NOT_FOUND`, a Zone `ERR_ZONE_NOT_FOUND`, a controller program `ERR_PROGRAM_NOT_FOUND`, a service quote `ERR_QUOTE_NOT_FOUND`, a work order `ERR_WORKORDER_NOT_FOUND`, a maintenance plan `ERR_PLAN_NOT_FOUND`, a route `ERR_ROUTE_NOT_FOUND`, and a route stop `ERR_ROUTESTOP_NOT_FOUND` — each returned with HTTP 404. A backflow test, which is referenced only by its own path identifier on its read endpoint and never as a foreign key in a write body, similarly yields `ERR_BACKFLOWTEST_NOT_FOUND` (HTTP 404) when its `id` does not resolve.

Validation runs in a fixed priority order so that the same request always fails for the same reason. The presence and well-formedness of the authentication headers is checked first; a violation yields `ERR_MISSING_USER_CONTEXT`. Role authorization is checked next, yielding `ERR_FORBIDDEN_ROLE` when the role is not permitted. Existence of every referenced identifier is checked third, yielding the appropriate not-found error. Ownership for entity-backed actors is checked fourth, yielding `ERR_NOT_RESOURCE_OWNER`. State preconditions for the requested transition are checked fifth, yielding the state-specific conflict error described alongside each workflow. Then come the domain-specific business gates — the optimistic concurrency check, the backflow safety and device gates, the seasonal gates, the program and route structural gates, the temporal-overlap and capacity checks, and the empty-collection guards — followed last by generic field-level request validation. Generic request-shape problems — a missing required body field, a value of the wrong type, an enum value outside its allowed range, a negative quantity, or a time window whose end is at or before its start — are reported as `ERR_INVALID_REQUEST` (HTTP 422) and sit at the bottom of the priority order.

### 2.6. Monetary Precision and Rounding

Every monetary value in this system is stored and returned as an integer number of cents; no fractional cents ever arise in stored fields. Where a calculation introduces a fractional cent before it is stored — for example when an 8% tax multiplier is applied — the result is rounded half up to a whole cent at each rounding point the calculation specifies. Risk scores are integer points and route timing figures are integer minutes, seconds, or counts; these likewise carry no fractional component.

### 2.7. Computed Fields and Hierarchical Reconciliation

A handful of fields are never supplied by clients; the server derives them from the surrounding data and keeps them current as that data changes. An irrigation system exposes `zone_count` (the number of its zones that are mapped or active), `committed_cost_cents` (its outstanding work-order commitment), and the two winterization risk figures `provisional_winter_risk` and `assessed_winter_risk`. A controller program exposes `total_run_minutes`. A service quote exposes `estimated_total_cents` and `final_total_cents`. A maintenance plan exposes `annual_dues_cents`. A property exposes `compliance_status`. A route exposes `stops_used` and `minutes_committed`. The exact recomputation rule for each of these lives with the workflow that drives it in Section 3.

When one operation changes a resource that participates in a parent's derived state, the system propagates the change rather than waiting for an explicit request against the parent. Decommissioning a system, completing a work order, recording a backflow test, or scheduling a stop each ripples outward to the dependent resources described in Section 3, and every resource touched along the way independently has its `updated_at` refreshed and its `version` incremented. This propagation is immediate and is part of the same operation; there is no deferred or eventual reconciliation.

### 2.8. Optimistic Concurrency on Route Scheduling

Adding a stop to a route is the one operation in this system guarded by optimistic concurrency control, because a route's spare capacity is consumed by the very act of scheduling against it. Each accepted stop legitimately consumes slot and minute capacity and advances the route's `version`. A client that read the route before a stop was added, and then tries to add its own stop, is working from a stale picture of the route's remaining capacity.

To make that staleness detectable, the request that schedules a work order onto a route must carry `expected_route_version` as a required field, holding the `version` of the target Route the client last observed. The server compares `expected_route_version` to the route's current `version`. If they differ — because another writer has advanced the route's `version` since the client read it — the request is rejected with `ERR_STALE_ROUTE_VERSION` (HTTP 412), and no stop is created. This is the only endpoint that accepts a version field; no other write in the system takes one.

### 2.9. Seasonal and Compliance Cross-Cutting Gates

Two domain-specific safety gates cut across multiple workflows and are introduced here so the rules that enforce them in Section 3 read against a shared backdrop. The **seasonal gate** governs the relationship between a system's `season_state` and the work that may be done on it: a start-up cannot be scheduled onto a system that has not been winterized, and a controller program cannot be activated on a system that is not in its active growing season. The **compliance posture** of a property is a regulatory reflection of its backflow situation: a property is `COMPLIANT` only when every one of its irrigation systems that has not been decommissioned carries a `backflow_status` of `CERTIFIED`; if any such system is still `UNTESTED` or has `FAILED`, the property's `compliance_status` is `NON_COMPLIANT`. The mechanics of each gate, the exact error codes, and the cascades they trigger are detailed in the relevant Section 3 workflows.

## 3. Business Logic & Workflows

### 3.1. Accounts, Field Staff, and the Property Inventory

The customer base and the workforce are the two roots of the data model, and both are managed by a Dispatcher. A customer account is opened with a `company_name`, a `contact_email`, and a five-digit `billing_zip`; on creation its `status` is `ACTIVE`. A Dispatcher may later move a customer to `SUSPENDED` through the suspend action; the two values `ACTIVE` and `SUSPENDED` are the only states a customer occupies.

A technician is registered with a `full_name` and a daily shift expressed as two seconds-from-midnight integers: `shift_start_sec` and `shift_end_sec`, each in the range 0 through 86399, with the end required to be strictly greater than the start. The optional `backflow_certified` flag marks whether the technician is licensed to certify backflow tests and defaults to false when omitted. A new technician's `status` is `AVAILABLE`, and a Dispatcher may set it to `INACTIVE`; those are the only two technician states. Technicians can be listed and optionally filtered by their `backflow_certified` standing.

A property is registered under a customer by supplying that account's `customer_id` together with the `site_address` and the geographic `lat` and `lng` coordinates, which are retained because route ordering reasons over site location. A fresh property's `status` is `ACTIVE`, and its `compliance_status` begins at `NON_COMPLIANT`. Properties can be listed and filtered by `customer_id`. A property's `status` becomes `DECOMMISSIONED` only as a consequence of system-level decommissioning cascades, never by a direct property edit.

### 3.2. Systems, Zones, and Controller Programs

An irrigation system is registered against a property by supplying its `property_id`, the `controller_model` label, the measured static water pressure `static_psi` (an integer from 0 through 200), and the optional `has_backflow_device` flag (default false) indicating whether a backflow-prevention device is plumbed in. A new system starts with `season_state` of `DORMANT`, `backflow_status` of `UNTESTED`, and `lifecycle_state` of `OPERATIONAL`, with its `zone_count` and `committed_cost_cents` both at zero. The `season_state` field walks through `DORMANT`, `ACTIVE`, and `WINTERIZED` as start-up and winterization work orders complete; `backflow_status` moves among `UNTESTED`, `CERTIFIED`, and `FAILED` as tests are recorded; and `lifecycle_state` is either `OPERATIONAL` or the terminal `DECOMMISSIONED`. Systems may be listed and filtered by `property_id`.

Each zone is mapped onto a system by supplying the `system_id`, a `zone_number`, a `plant_type` of `TURF`, `SHRUB`, `DRIP`, or `ROTOR`, a `head_count` (at least 1), and a `gpm_per_head` value (at least 1) that records gallons-per-minute demand per head in integer tenths — so a stored value of 18 means 1.8 gallons per minute. The `zone_number` must be at least 1 and must be unique among the system's zones that are not archived; a collision is rejected with `ERR_DUPLICATE_ZONE_NUMBER`. A newly mapped zone enters `zone_state` of `MAPPED`; it advances to `ACTIVE` once it is incorporated into an activated program, and it is forced to `ARCHIVED` when its system is decommissioned. A system's `zone_count` reflects exactly those of its zones whose `zone_state` is `MAPPED` or `ACTIVE`. Zones may be listed and filtered by `system_id`.

A controller program is the daily watering schedule for a system. It is created in `DRAFT` against a `system_id` with an ordered array of `slots`, where each slot names a `zone_id`, a `start_sec` (seconds from midnight), and a `run_minutes` duration; a slot occupies the half-open interval that begins at its `start_sec` and ends at `start_sec` plus `run_minutes` times sixty seconds. On creation the program's `total_run_minutes` is computed as the sum of `run_minutes` across all of its slots. A program's `program_state` is `DRAFT`, `ACTIVE`, or the terminal `STALE`. Activating a draft program is a technician action and is gated by four preconditions evaluated together: the program must be in `DRAFT` (otherwise `ERR_PROGRAM_NOT_DRAFT`); its `slots` array must be non-empty (otherwise `ERR_EMPTY_PROGRAM`); the system's `season_state` must be `ACTIVE` (otherwise `ERR_SEASON_STATE_BLOCKS_PROGRAM`); and no two slots may conflict on the timeline (otherwise `ERR_PROGRAM_SLOT_OVERLAP`). When activation succeeds, the program moves `DRAFT → ACTIVE`, every zone referenced in its slots whose `zone_state` is `MAPPED` is promoted to `ACTIVE`, and the system's `zone_count` is recomputed accordingly. Programs may be listed and filtered by `system_id`.

The slot-conflict check uses buffered, gap-aware semantics rather than a plain overlap test. Sort the slots by `start_sec` ascending, breaking ties first by `run_minutes` ascending and then by the `created_at` of the referenced zone ascending (never by `id`). Then walk each adjacent pair in that order. For a pair where the earlier slot ends at or before the later one begins, a conflict exists when the gap between the earlier slot's end and the later slot's start is less than the valve-switch buffer of 120 seconds. Because the comparison is strictly less than the buffer, two slots placed exactly end-to-end with no gap at all are rejected, not merely those that physically overlap. The first adjacent pair that violates the buffer causes the activation to be rejected with `ERR_PROGRAM_SLOT_OVERLAP`. After activation, if a zone underlying an active program is later archived, that program is driven from `ACTIVE` to `STALE`.

### 3.3. Quoting Install and Repair Work

A service quote captures the price of a job before it begins. A Dispatcher drafts a quote against a property by supplying the `property_id`, a `quote_type` of either `INSTALL` or `REPAIR`, and an array of `line_items`, where each line item carries a `description`, a `quantity` (at least 1), and a `unit_rate_cents` (at least 0). A new quote is in `quote_state` of `DRAFT`, and its `estimated_total_cents` and `final_total_cents` both start at zero; `final_total_cents` remains zero until the quote's linked work order completes. The full set of quote states is `DRAFT`, `SENT`, `CHANGES_REQUESTED`, `APPROVED`, and `REJECTED`, with `APPROVED` and `REJECTED` terminal. Quotes may be listed and filtered by `property_id` or by `linked_work_order_id`.

A Dispatcher sends a quote to the customer, moving it `DRAFT → SENT`. Sending requires that the quote currently be in `DRAFT` (otherwise `ERR_QUOTE_NOT_DRAFT`) and that its `line_items` be non-empty (otherwise `ERR_EMPTY_QUOTE`, HTTP 422). On a successful send, the quote's `estimated_total_cents` is recomputed. The estimate is forward-looking and uses catalog rates: for each line item the per-line amount is its `quantity` multiplied by its `unit_rate_cents` — an exact integer-cents product — and these per-line amounts are summed into a subtotal. That whole subtotal is then multiplied by one plus the tax rate of 8% (a factor of 1.08), and the single resulting figure is rounded half up to whole cents to give `estimated_total_cents`. The estimate rounds exactly once, after the entire subtotal has been formed.

The customer who owns the quote's property then decides. They may request changes, moving the quote `SENT → CHANGES_REQUESTED`; this is permitted only when the quote is `SENT` (otherwise `ERR_QUOTE_NOT_SENT`) and only for the owning customer (otherwise `ERR_NOT_RESOURCE_OWNER`). From `CHANGES_REQUESTED`, the Dispatcher revises the quote by submitting a fresh `line_items` array, which replaces the prior list and moves the quote `CHANGES_REQUESTED → DRAFT`; this revision is permitted only when the quote is in `CHANGES_REQUESTED` (otherwise `ERR_QUOTE_NOT_REVISABLE`) and recomputes `estimated_total_cents` by the same estimated rule. This send-then-revise loop may cycle. Alternatively the owning customer may reject the quote outright, moving it `SENT → REJECTED`, again only when it is `SENT` (otherwise `ERR_QUOTE_NOT_SENT`) and only for the owner (otherwise `ERR_NOT_RESOURCE_OWNER`).

Approval is the consequential branch. The owning customer approves a `SENT` quote, moving it `SENT → APPROVED`, subject to three preconditions in turn: the quote must be `SENT` (otherwise `ERR_QUOTE_NOT_SENT`), the acting customer must own the quote's property (otherwise `ERR_NOT_RESOURCE_OWNER`), and the property's `status` must be `ACTIVE` (otherwise `ERR_PROPERTY_INACTIVE`). On approval the system spawns a work order on the property's first operational system, where "first" means the operational system with the earliest `created_at` (ties broken by creation order): a job whose `job_type` is `INSTALL` when the quote's `quote_type` is `INSTALL`, otherwise `LEAK_REPAIR`. The spawned work order begins with `completion_status` of `PENDING` and `dispatch_status` of `UNSCHEDULED`, takes its `estimated_cost_cents` from the quote's `estimated_total_cents`, is given an `estimated_minutes` of 1, and records the originating quote in its `origin_quote_id`. If the property happens to have no operational system, approval still succeeds and still spawns the work order, but the work order's `system_id` is left unset (null) and no system's `committed_cost_cents` is debited. The quote's `linked_work_order_id` is set to the new work order's `id`. As with any work order, creating this one debits the system's `committed_cost_cents` by the work order's `estimated_cost_cents`.

### 3.4. Work Orders: Two Independent Status Dimensions

A work order tracks a single field visit along two independent axes. The `dispatch_status` axis describes where the job sits in the logistics pipeline and walks `UNSCHEDULED → SCHEDULED → EN_ROUTE → ON_SITE`. The `completion_status` axis describes the work itself and walks `PENDING → IN_PROGRESS → COMPLETED` or `PENDING → IN_PROGRESS → FAILED`, and may also reach `CANCELLED`; the terminal completion states are `COMPLETED`, `FAILED`, and `CANCELLED`. The two axes evolve independently except where a precondition on one explicitly references the other.

A Dispatcher may create a work order directly by supplying the `system_id`, a `job_type` of `INSTALL`, `STARTUP`, `WINTERIZATION`, `LEAK_REPAIR`, `HEAD_REPAIR`, or `BACKFLOW_TEST`, an `estimated_minutes` of on-site duration (at least 1, which drives route capacity), and an `estimated_cost_cents` (at least 0). The new work order starts `UNSCHEDULED` and `PENDING`, with `assigned_technician_id` and `origin_quote_id` unset. Creating any work order immediately debits the serviced system's `committed_cost_cents` by the work order's `estimated_cost_cents`. A system's `committed_cost_cents` is, by definition, the sum of `estimated_cost_cents` over all work orders on that system whose `completion_status` is not yet one of `COMPLETED`, `FAILED`, or `CANCELLED`. The actual-cost fields `actual_labor_cents` and `actual_parts_cents` both default to zero at creation and are supplied later at completion. Work orders may be listed and filtered by `system_id`, by `assigned_technician_id`, or by `origin_quote_id`.

A work order's `dispatch_status` advances to `SCHEDULED` as a side effect of placing it onto a route, described in Section 3.6. The assigned technician then drives the dispatch axis forward. Departing for the job advances `SCHEDULED → EN_ROUTE`; this requires that `dispatch_status` be `SCHEDULED` (otherwise `ERR_WORKORDER_NOT_SCHEDULED`) and that the acting technician match the work order's `assigned_technician_id` (otherwise `ERR_NOT_RESOURCE_OWNER`). Arriving on site advances `EN_ROUTE → ON_SITE`; it requires `dispatch_status` to be `EN_ROUTE` (otherwise `ERR_WORKORDER_NOT_EN_ROUTE`) and the acting technician to be the assigned one (otherwise `ERR_NOT_RESOURCE_OWNER`). Arrival also has a cross-axis side effect: it automatically advances `completion_status` from `PENDING` to `IN_PROGRESS`.

Completing the job is the technician's settlement action and carries the system's heaviest cascade. The technician submits the `actual_labor_cents` and `actual_parts_cents` recorded on site. Completion requires `completion_status` to be `IN_PROGRESS` (otherwise `ERR_WORKORDER_NOT_IN_PROGRESS`), `dispatch_status` to be `ON_SITE` (otherwise `ERR_WORKORDER_NOT_ON_SITE`), and the acting technician to be the assigned one (otherwise `ERR_NOT_RESOURCE_OWNER`). On success the `completion_status` moves to `COMPLETED`, and four things follow. First, because the job is no longer an open commitment, the system's `committed_cost_cents` is credited back by this work order's `estimated_cost_cents`. Second, if the work order carries an `origin_quote_id`, the originating quote's `final_total_cents` is recomputed. Third, if the `job_type` is `WINTERIZATION`, the system's `season_state` is set to `WINTERIZED` and its `assessed_winter_risk` is recomputed. Fourth, if the `job_type` is `STARTUP`, the system's `season_state` is set to `ACTIVE`.

The final-total recomputation is deliberately chronological and rounds per line. The labor component is the `actual_labor_cents` multiplied by the 1.08 tax factor and rounded half up to whole cents; the parts component is the `actual_parts_cents` multiplied by the same 1.08 factor and rounded half up to whole cents; and `final_total_cents` is the sum of those two already-rounded components. Because each of the two lines is taxed and rounded before they are added, the final figure can differ by a cent from the estimate even when the underlying raw amounts coincide — the estimate rounds once after summing, the final rounds each line then sums.

Failing a job is the other terminal outcome of an in-progress work order. The assigned technician marks it `IN_PROGRESS → FAILED`; this requires `completion_status` to be `IN_PROGRESS` (otherwise `ERR_WORKORDER_NOT_IN_PROGRESS`) and the acting technician to be the assigned one (otherwise `ERR_NOT_RESOURCE_OWNER`). On failure the system's `committed_cost_cents` is credited back by this work order's `estimated_cost_cents`, just as on completion. A Dispatcher may instead cancel a work order that has not yet settled, moving its `completion_status` to `CANCELLED`; cancellation is permitted only while the `completion_status` is not already one of `COMPLETED`, `FAILED`, or `CANCELLED` (otherwise `ERR_WORKORDER_TERMINAL`). Cancellation credits the system's `committed_cost_cents` back by the `estimated_cost_cents`, and additionally drives any `SCHEDULED` route stop that references this work order to `REMOVED`, recomputing that stop's route `stops_used` and `minutes_committed`. The same cancellation path is taken automatically when a system is decommissioned, as described next.

### 3.5. Decommissioning a System and Recording Compliance

Decommissioning a system is a Dispatcher action and the deepest cascade in the platform. It is permitted only when the system's `lifecycle_state` is `OPERATIONAL` (otherwise `ERR_SYSTEM_ALREADY_DECOMMISSIONED`), after which the system moves to the terminal `DECOMMISSIONED`. The cascade then proceeds in hops. First, every zone of the system whose `zone_state` is not already `ARCHIVED` is moved to `ARCHIVED`. Second, each zone just archived that is referenced by the slots of an `ACTIVE` controller program forces that program from `ACTIVE` to `STALE`. Third, every work order on the system whose `completion_status` is not already one of `COMPLETED`, `FAILED`, or `CANCELLED` is cancelled — and each such cancellation runs the full work-order cancellation behaviour from Section 3.4, crediting the system's `committed_cost_cents` back by that work order's `estimated_cost_cents` and removing any `SCHEDULED` route stop that referenced it. Finally, the property's `compliance_status` is recomputed to reflect the system's removal from the compliant set.

A backflow test is the regulatory inspection that determines whether a system's device passes, and only a `BackflowTester` may record one. The test is created against a `system_id` with a `tester_technician_id`, a measured `relief_open_psi` (at least 0), and a measured `checkvalve_hold_psi` (at least 0). Two gates protect the record, evaluated tester-certification first then device: the technician named in `tester_technician_id` must be one whose `backflow_certified` is true (otherwise `ERR_TESTER_NOT_CERTIFIED`, HTTP 403); and the system must actually have a backflow device, that is its `has_backflow_device` must be true (otherwise `ERR_NO_BACKFLOW_DEVICE`, HTTP 409). When both fail, the tester-certification gate takes precedence and `ERR_TESTER_NOT_CERTIFIED` is returned. The record is append-only — its `result` is computed once at creation and never changes. The `result` is `PASS` when the `relief_open_psi` is at least the minimum relief pressure of 2 PSI and the `checkvalve_hold_psi` is at least the minimum hold differential of 1 PSI; if either measurement falls below its minimum, the `result` is `FAIL`. Note that a relief reading exactly equal to 2, or a hold reading exactly equal to 1, passes, because each comparison is "at least," not "greater than."

Recording the test bubbles a cascade up through the system and property. A `PASS` sets the system's `backflow_status` to `CERTIFIED`, then recomputes the property's `compliance_status` — which becomes `COMPLIANT` only if every non-decommissioned system on that property is now `CERTIFIED`. A `FAIL` sets the system's `backflow_status` to `FAILED` and recomputes the property's `compliance_status`, which necessarily remains `NON_COMPLIANT`.

### 3.6. Routing, Stops, and Capacity

A route is a single technician's plan for one service day. A Dispatcher opens a route by naming the `technician_id` who will drive it and the `route_date` (a `YYYY-MM-DD` calendar date). A new route is in `route_state` of `PLANNING`, with `stops_used` and `minutes_committed` both at zero; the full set of route states is `PLANNING`, `DISPATCHED`, and the terminal `CLOSED`. A route's `stops_used` is the count of its route stops whose `stop_state` is `SCHEDULED`, and its `minutes_committed` is the sum of `window_minutes` over those scheduled stops. Routes may be listed and filtered by `technician_id`.

Scheduling a work order onto a route creates a route stop and is the platform's busiest gate. The Dispatcher supplies the `route_id`, the `work_order_id` to perform at this stop, an `arrival_start_sec` (seconds from midnight, 0 through 86399), a `window_minutes` length (at least 1), and the `expected_route_version` for the concurrency check of Section 2.8. The stop occupies the half-open interval beginning at `arrival_start_sec` and ending at `arrival_start_sec` plus `window_minutes` times sixty seconds. A new stop's `stop_state` is `SCHEDULED`; a stop removed from a route becomes `REMOVED`, freeing the slot. Stops may be listed and filtered by `route_id` or by `work_order_id`.

A stop can be added only while its route is in `PLANNING` (otherwise `ERR_ROUTE_NOT_PLANNING`). Several further checks guard the stop. The work order's `completion_status` must be `PENDING` (otherwise `ERR_WORKORDER_NOT_PENDING`) and its `dispatch_status` must be `UNSCHEDULED` (otherwise `ERR_WORKORDER_ALREADY_SCHEDULED`). If the work order's `job_type` is `STARTUP`, the serviced system's `season_state` must be `WINTERIZED` (otherwise `ERR_SEASON_STATE_BLOCKS_STARTUP`) — a system can only be started up after it has been winterized. The new stop's window must not overlap the half-open window of any other `SCHEDULED` stop already on the same route (otherwise `ERR_ROUTESTOP_TIME_OVERLAP`). Finally the stop must fit the route's capacity. Capacity is breached, and the stop rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`, when either of two limits would be exceeded: the route's prospective stop count — its current `stops_used` plus one — would exceed the per-route maximum of 8 stops, or the route's prospective committed minutes — its current `minutes_committed` plus the new stop's `window_minutes` — would exceed the driving technician's shift length in minutes, computed as the technician's `shift_end_sec` minus `shift_start_sec`, that difference taken in whole minutes. The stop-count limit bites only when the prospective count is strictly greater than 8.

When a stop is accepted, the referenced work order's `dispatch_status` advances `UNSCHEDULED → SCHEDULED` and its `assigned_technician_id` is set to the route's `technician_id`. The route's `stops_used` and `minutes_committed` are recomputed, and the route's `version` is incremented by one — the very increment that the optimistic concurrency check of Section 2.8 protects against on subsequent stop additions.

Once at least one stop sits on a route, the Dispatcher dispatches it, moving `PLANNING → DISPATCHED`; this requires the route to be in `PLANNING` (otherwise `ERR_ROUTE_NOT_PLANNING`) and to carry at least one scheduled stop, that is `stops_used` of at least 1 (otherwise `ERR_EMPTY_ROUTE`). Later the Dispatcher closes the route, moving `DISPATCHED → CLOSED`, which requires the route to be `DISPATCHED` (otherwise `ERR_ROUTE_NOT_DISPATCHED`).

### 3.7. Recurring Maintenance Plans

A maintenance plan puts a property on a recurring service cadence. A Dispatcher creates a plan against a `property_id` with a `tier` of `BASIC`, `PLUS`, or `PREMIUM` and a `visits_per_year` count (at least 1). A new plan is in `plan_state` of `ACTIVE`; the full set of plan states is `ACTIVE`, `PAUSED`, and the terminal `CANCELLED`. Plans may be listed and filtered by `property_id`. A Dispatcher pauses an active plan, moving `ACTIVE → PAUSED` (permitted only when the plan is `ACTIVE`, otherwise `ERR_PLAN_NOT_ACTIVE`); resumes a paused plan, moving `PAUSED → ACTIVE` (permitted only when the plan is `PAUSED`, otherwise `ERR_PLAN_NOT_PAUSED`); and may cancel a plan from either the active or paused state, moving it to `CANCELLED` (permitted only when the plan is not already `CANCELLED`, otherwise `ERR_PLAN_TERMINAL`).

The plan's `annual_dues_cents` is computed once at creation, and its calculation is order-sensitive. The per-visit base rate is fixed by tier: 6000 cents for `BASIC`, 9000 cents for `PLUS`, and 13000 cents for `PREMIUM`. The gross is that per-visit rate multiplied by `visits_per_year`. The loyalty discount is then chosen from the gross — and the gross must be computed first before the discount tier can be selected: if the gross is at least 120000 cents the discount is 15%, otherwise if the gross is at least 60000 cents the discount is 8%, otherwise there is no discount. The `annual_dues_cents` is the gross multiplied by one minus that discount fraction, rounded half up to whole cents once at the end.

### 3.8. Winterization Risk and the Blowout Price Preview

Two winterization figures live on each system, and they answer different questions about the same zone inventory. Both reason only over the system's non-archived zones, and both weight each zone's exposure by its plant type: a `TURF` zone weighs 4, a `ROTOR` zone weighs 3, a `SHRUB` zone weighs 2, and a `DRIP` zone weighs 1, each weight multiplied by that zone's `head_count`. A pressure factor of 2 applies when the system's `static_psi` is at least the high-pressure threshold of 80 PSI, and a factor of 1 applies otherwise. The risk is capped at 1000 points.

The `provisional_winter_risk` is the forward-looking worst case, maintained while any non-terminal winterization or repair work order is open on the system. It assumes every non-archived zone still holds water: it sums the plant-type weight times `head_count` across all non-archived zones to form the exposure, multiplies that exposure by the pressure factor, and takes the smaller of that product and the 1000-point cap. The `assessed_winter_risk` is the settled figure, recomputed when a `WINTERIZATION` work order on the system reaches `COMPLETED`. It treats the zones as drained once the system has been blown out: if the system has no completed winterization work order, the drained exposure is the same plant-type-weighted sum over non-archived zones, but if the system does have a completed winterization work order, the drained exposure is zero. The `assessed_winter_risk` is then that drained exposure multiplied by the pressure factor, again capped at 1000. For an identical zone inventory the two figures diverge once the system has been winterized: the provisional figure still reflects full exposure while the assessed figure has fallen to zero.

The blowout price preview is a read-only pricing estimate for winterizing a system, available to Dispatchers and Customers; its response carries the `system_id`, the system's current `zone_count`, and the computed `blowout_price_cents`. Let the zone count be the system's non-archived `zone_count`. The per-zone rate is tiered by that count: when the count is 4 or fewer the rate is 1200 cents per zone; when the count is from 5 through 10 the rate is 1000 cents per zone; and when the count is 11 or more the rate is 850 cents per zone. A pressure surcharge is computed as the system's `static_psi` minus the high-pressure threshold of 80, multiplied by 50 cents per PSI, then floored at 0 and capped at 3000 cents — so it is zero when the pressure is at or below 80 and never exceeds 3000 cents. The `blowout_price_cents` is the base fee of 4500 cents, plus the per-zone rate times the zone count, plus the pressure surcharge. All amounts are exact integer cents.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource return `201 Created`. Endpoints that modify, transition, or act upon an existing resource — including state transitions, line-item revisions, and read operations — return `200 OK`. Request and response bodies, including which fields each operation accepts and the side effects it triggers, are described in the Section 3 workflows; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer account | Dispatcher |
| GET | `/customers/{id}` | Get a customer | Dispatcher, Customer |
| GET | `/customers` | List customers | Dispatcher |
| POST | `/customers/{id}/suspend` | Suspend a customer account | Dispatcher |
| POST | `/technicians` | Create a technician | Dispatcher |
| GET | `/technicians/{id}` | Get a technician | Dispatcher, Technician, BackflowTester |
| GET | `/technicians` | List technicians (filterable by certification) | Dispatcher |
| POST | `/properties` | Create a property under a customer | Dispatcher |
| GET | `/properties/{id}` | Get a property (includes computed compliance status) | Dispatcher, Customer |
| GET | `/properties` | List properties; filter by customer | Dispatcher, Customer |
| POST | `/irrigation-systems` | Register an irrigation system on a property | Dispatcher |
| GET | `/irrigation-systems/{id}` | Get a system (computed counts, costs, risks) | Dispatcher, Customer, Technician |
| GET | `/irrigation-systems` | List systems; filter by property | Dispatcher, Customer, Technician |
| GET | `/irrigation-systems/{id}/blowout-quote` | Compute the winterization (blowout) price preview | Dispatcher, Customer |
| POST | `/irrigation-systems/{id}/decommission` | Decommission a system (cascades to zones, programs, work orders) | Dispatcher |
| POST | `/zones` | Add a zone to a system | Dispatcher, Technician |
| GET | `/zones/{id}` | Get a zone | Dispatcher, Customer, Technician |
| GET | `/zones` | List zones; filter by system | Dispatcher, Customer, Technician |
| POST | `/controller-programs` | Create a draft controller program for a system | Dispatcher, Technician |
| GET | `/controller-programs/{id}` | Get a controller program | Dispatcher, Technician |
| GET | `/controller-programs` | List controller programs; filter by system | Dispatcher, Technician |
| POST | `/controller-programs/{id}/activate` | Activate a draft program | Technician |
| POST | `/service-quotes` | Create a draft install/repair quote | Dispatcher |
| GET | `/service-quotes/{id}` | Get a quote | Dispatcher, Customer |
| GET | `/service-quotes` | List quotes; filter by property or linked work order | Dispatcher, Customer |
| POST | `/service-quotes/{id}/send` | Send a quote to the customer | Dispatcher |
| PATCH | `/service-quotes/{id}/line-items` | Revise line items after a change request | Dispatcher |
| POST | `/service-quotes/{id}/request-changes` | Customer requests changes | Customer |
| POST | `/service-quotes/{id}/approve` | Customer approves a quote; spawns a work order | Customer |
| POST | `/service-quotes/{id}/reject` | Customer rejects a quote | Customer |
| POST | `/work-orders` | Create a work order directly | Dispatcher |
| GET | `/work-orders/{id}` | Get a work order (both status dimensions) | Dispatcher, Customer, Technician |
| GET | `/work-orders` | List work orders; filter by system, technician, or origin quote | Dispatcher, Customer, Technician |
| POST | `/work-orders/{id}/depart` | Technician departs for the job | Technician |
| POST | `/work-orders/{id}/arrive` | Technician arrives on site; work begins | Technician |
| POST | `/work-orders/{id}/complete` | Complete the job; record actuals | Technician |
| POST | `/work-orders/{id}/fail` | Mark the job failed | Technician |
| POST | `/work-orders/{id}/cancel` | Cancel a non-terminal work order | Dispatcher |
| POST | `/maintenance-plans` | Create a recurring maintenance plan | Dispatcher |
| GET | `/maintenance-plans/{id}` | Get a maintenance plan | Dispatcher, Customer |
| GET | `/maintenance-plans` | List maintenance plans; filter by property | Dispatcher, Customer |
| POST | `/maintenance-plans/{id}/pause` | Pause a plan | Dispatcher |
| POST | `/maintenance-plans/{id}/resume` | Resume a plan | Dispatcher |
| POST | `/maintenance-plans/{id}/cancel` | Cancel a plan | Dispatcher |
| POST | `/backflow-tests` | Record a backflow test; computes PASS/FAIL and certifies the system | BackflowTester |
| GET | `/backflow-tests/{id}` | Get a backflow test | Dispatcher, Customer, BackflowTester |
| GET | `/backflow-tests` | List backflow tests; filter by system or tester | Dispatcher, Customer, BackflowTester |
| POST | `/routes` | Create a daily route for a technician | Dispatcher |
| GET | `/routes/{id}` | Get a route (computed stop count and minutes) | Dispatcher, Technician |
| GET | `/routes` | List routes; filter by technician | Dispatcher, Technician |
| POST | `/routes/{id}/dispatch` | Dispatch a route | Dispatcher |
| POST | `/routes/{id}/close` | Close a route | Dispatcher |
| POST | `/route-stops` | Schedule a work order onto a route | Dispatcher |
| GET | `/route-stops/{id}` | Get a route stop | Dispatcher, Technician |
| GET | `/route-stops` | List route stops; filter by route or work order | Dispatcher, Technician |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_SYSTEM_NOT_FOUND` | 404 Not Found |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_WORKORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTESTOP_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_QUOTE_NOT_DRAFT` | 409 Conflict |
| `ERR_QUOTE_NOT_SENT` | 409 Conflict |
| `ERR_QUOTE_NOT_REVISABLE` | 409 Conflict |
| `ERR_EMPTY_QUOTE` | 422 Unprocessable Entity |
| `ERR_PROPERTY_INACTIVE` | 409 Conflict |
| `ERR_WORKORDER_NOT_PENDING` | 409 Conflict |
| `ERR_WORKORDER_ALREADY_SCHEDULED` | 409 Conflict |
| `ERR_WORKORDER_NOT_SCHEDULED` | 409 Conflict |
| `ERR_WORKORDER_NOT_EN_ROUTE` | 409 Conflict |
| `ERR_WORKORDER_NOT_ON_SITE` | 409 Conflict |
| `ERR_WORKORDER_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_WORKORDER_TERMINAL` | 409 Conflict |
| `ERR_SEASON_STATE_BLOCKS_STARTUP` | 409 Conflict |
| `ERR_SYSTEM_ALREADY_DECOMMISSIONED` | 409 Conflict |
| `ERR_PROGRAM_NOT_DRAFT` | 409 Conflict |
| `ERR_EMPTY_PROGRAM` | 409 Conflict |
| `ERR_PROGRAM_SLOT_OVERLAP` | 409 Conflict |
| `ERR_SEASON_STATE_BLOCKS_PROGRAM` | 409 Conflict |
| `ERR_DUPLICATE_ZONE_NUMBER` | 409 Conflict |
| `ERR_TESTER_NOT_CERTIFIED` | 403 Forbidden |
| `ERR_NO_BACKFLOW_DEVICE` | 409 Conflict |
| `ERR_ROUTE_NOT_PLANNING` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_EMPTY_ROUTE` | 409 Conflict |
| `ERR_ROUTESTOP_TIME_OVERLAP` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_STALE_ROUTE_VERSION` | 412 Precondition Failed |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_PAUSED` | 409 Conflict |
| `ERR_PLAN_TERMINAL` | 409 Conflict |
