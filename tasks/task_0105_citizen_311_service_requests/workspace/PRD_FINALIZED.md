# Citizen 311 Service Requests API — Product Requirements Document

## 1. Introduction

Municipalities receive a continuous stream of non-emergency service requests from residents — potholes that need filling, streetlights that have gone dark, overflowing dumpsters, downed signage. The Citizen 311 Service Requests API is the system of record that carries each of these reports from the moment a citizen files it through triage, geographic routing, departmental work, resolution, and a closing satisfaction survey. Its purpose is to make the journey of every request auditable and deterministic: a report filed at a particular coordinate is assigned to exactly one jurisdiction and one department by well-defined rules, the clock against which service-level commitments are measured is explicit, and every state change a request undergoes leaves a notification trail behind it.

The platform serves four kinds of human actors and one automated sweep. Citizens file and reopen their own requests and answer surveys. Dispatchers staffing the 311 desk triage incoming reports, route them, cluster duplicates, manage work orders, and handle escalations. Departmental agents pick up and complete the work. A system administrator maintains the reference configuration — categories, jurisdictions, departments, service-level policies, agents, and maintenance/blackout windows — and drives the logical clock that the benchmark uses to simulate the passage of time. Because timeliness is the core promise of a 311 program, the system continuously measures each routed request against a service-level deadline derived from its category and priority, automatically escalating those that fall behind and surcharging departments whose backlog has grown congested.

This document specifies the complete behavioral contract: the response envelope every endpoint shares, the role model that gates access, the geometric and temporal calculations that drive routing and escalation, and the workflows through which requests, work orders, clusters, escalations, and surveys advance. Where a rule lives in a numeric threshold or a boundary-inclusivity choice, this document states it precisely, because the difference between "at the deadline" and "past the deadline" determines whether a citizen's request escalates.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to an authenticated endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. The system recognizes five role names, spelled exactly: `SystemAdmin`, `Dispatcher`, `Agent`, `Citizen`, and `Anonymous`. If either header is absent, or if `X-User-Role` is not one of these known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two endpoints are exempt from the authentication requirement in different ways. Citizen self-registration is an open operation invoked under the `Anonymous` role and requires no prior identity. The clock-control endpoints are reserved exclusively for `SystemAdmin`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Citizen`, `X-User-ID` is the `id` of the acting `Citizen`; ownership checks on any resource that references a `Citizen` compare the resource's `citizen_id` to `X-User-ID`. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent`; checks that an agent is acting within their own department compare the agent's `department_id` against the work order's `department_id`, and checks that an agent is the one assigned compare `X-User-ID` against the work order's `assigned_agent_id`. When `X-User-Role` is `SystemAdmin`, `Dispatcher`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as the `resolved_by_role` carried on an `Escalation`, which records the acting role string) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters that govern paging. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be no smaller than 1 and no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0 when omitted. A `limit` or `offset` outside its permitted range is a schema violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a specific endpoint states otherwise, list endpoints return their items sorted by `created_at` in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the size of the full filtered result set and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. Every resource is assigned an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional (millisecond) digits. Resources that may change after creation additionally carry an `updated_at` timestamp, refreshed to the current instant on every mutation, and a `version`, an integer that begins at its initial value and increments by one on every mutation. The following carry the full set — `id`, `created_at`, `updated_at`, and `version`: `ServiceCategory`, `Jurisdiction`, `Department`, `SlaPolicy`, `Citizen`, `Agent`, `ServiceRequest`, `DuplicateCluster`, `WorkOrder`, `SatisfactionSurvey`, and `ServiceWindow`.

Two entities are append-only audit records that never change after creation and therefore carry only `id` and `created_at`; they have no `updated_at` and no `version`. These are `StatusNotification` and `Escalation`. Because an `Escalation` has no `version`, it can never serve as the parent of an optimistic-concurrency check; its eventual resolution mutates only its own `status` and `resolved_by_role` fields, which is permitted on this otherwise-immutable record as the single defined transition.

A subtle but load-bearing consequence of versioning is that derived fields are mutations like any other. When the SLA sweep flips a request's `sla_breached`, when triage sets `priority` and `jurisdiction_id`, when routing populates `department_id`, `routed_at`, and `sla_deadline_at`, or when a reopen increments `reopen_count` and clears `resolved_at`, the affected `ServiceRequest` has its `updated_at` refreshed and its `version` incremented. The same holds for a `Department` whose `open_work_order_count` and `congested` are recomputed, and for a `DuplicateCluster` whose `member_count` is recomputed.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints carry one or more resource identifiers in their path, and several creation endpoints carry foreign-key identifiers in their body. The system validates the existence of every such identifier from left to right, returning `ERR_NOT_FOUND` (HTTP 404) on the first identifier that does not resolve to an existing resource before any deeper identifier or business rule is considered. For a reverse-reachability listing such as the agents of a department, the department in the path is verified to exist before the agent list is assembled. This existence pass sits at priority 3 in the validation order — after authentication and role authorization but before ownership, state, and all business-specific checks — so a request that names a nonexistent resource fails as not-found rather than, say, as forbidden-by-state.

### 2.6. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. The order is: (1) authentication of the `X-User-ID`/`X-User-Role` headers, yielding `ERR_UNAUTHENTICATED`; (2) role authorization for the endpoint, yielding `ERR_FORBIDDEN_ROLE`; (3) left-to-right existence of every path and body identifier, yielding `ERR_NOT_FOUND`; (4) citizen ownership of the target request or survey for citizen-scoped actions, yielding `ERR_NOT_RESOURCE_OWNER`; (5) an agent's membership in the work order's department, yielding `ERR_AGENT_WRONG_DEPARTMENT`; (6) that the target resource is in a state from which the requested transition is defined, yielding `ERR_INVALID_STATE`; (7) the optimistic-concurrency version check, yielding `ERR_STALE_VERSION`. Below these sit the business-constraint and temporal checks described throughout §3, and finally a general request-body schema check yielding `ERR_INVALID_REQUEST`. Where §3 describes a specific business rule, its position relative to these system-level checks follows this same ordering: authentication, authorization, and existence always precede ownership and state, which precede the concurrency check, which precedes domain business rules.

### 2.7. Optimistic Concurrency Control

Two write operations require the caller to prove it is acting on a fresh view of a parent resource by supplying that resource's last-observed `version`. These checks are framed entirely in terms of stale versions, not timing.

When a dispatcher creates a duplicate cluster, the create request must carry `expected_canonical_version`, and that value must equal the current `version` of the canonical `ServiceRequest` the cluster is anchored to. The canonical request may have legitimately moved on since the dispatcher last read it — it might have been triaged or attached elsewhere — advancing its `version`. If `expected_canonical_version` does not equal the canonical request's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the dispatcher to re-read before anchoring a cluster to an outdated snapshot.

When a dispatcher assigns an agent to a work order, the assign request must carry `expected_work_order_version`, and that value must equal the current `version` of the target `WorkOrder`. A prior assignment legitimately overwrites `assigned_agent_id` and advances the work order's `version`; a dispatcher acting on a stale snapshot must therefore re-read before reassigning. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field. Operations not named above proceed without any concurrency check.

### 2.8. The Logical Clock and Time

Rather than reading wall-clock time, the system maintains a single logical clock, referred to throughout as the current instant. A `SystemAdmin` can set this clock to an absolute UTC instant by supplying `to_iso8601`, and can advance it forward by a whole number of `hours`. Advancing the clock additionally runs the service-level breach sweep described in §3.7. All time-dependent computations — the SLA deadline, the reopen window, the breach test, and the maintenance/blackout window checks — read this logical clock, never the host's wall clock. Timestamps such as `routed_at`, `resolved_at`, `sla_deadline_at`, `starts_at`, and `ends_at` are stored and compared as UTC instants to millisecond precision.

### 2.9. Geographic Routing Principles

Two geometric computations underpin the system. The first places a reported coordinate into a jurisdiction. Each `Jurisdiction` defines an axis-aligned bounding box by its `min_lat`, `max_lat`, `min_lng`, and `max_lng`. A point `(lat, lng)` lies inside the box when its latitude is at least `min_lat` and strictly less than `max_lat`, and its longitude is at least `min_lng` and strictly less than `max_lng` — that is, the lower bound on each axis is inclusive and the upper bound is exclusive (a half-open box on both axes). Boxes are permitted to overlap. When a point falls inside more than one box, the system selects the jurisdiction with the smallest box area, where area is computed as `(max_lat - min_lat)` multiplied by `(max_lng - min_lng)`; this deliberately picks the tightest (most specific) jurisdiction rather than the first one created. Should two containing boxes have exactly equal area, the tie is broken by choosing the one with the earlier `created_at`. If the request has no latitude or no longitude, or if no box contains the point, the match yields no jurisdiction. Latitude and longitude values are compared exactly as supplied, without rounding.

The second computation measures the great-circle distance between two coordinates using the haversine formula with an Earth radius of 6,371,000 meters. Given two points, it converts the latitude and longitude differences to radians, forms the haversine term as the square of the sine of half the latitude difference plus the product of the cosines of the two latitudes and the square of the sine of half the longitude difference, and returns twice the radius multiplied by the arcsine of the smaller of 1 and the square root of that term. This distance, in meters, is used to decide cluster membership and is compared without any rounding before the comparison.

### 2.10. Departmental Backlog and Congestion

Each `Department` continuously tracks how much open work it carries. The `open_work_order_count` is the number of `WorkOrder` rows belonging to that department whose `status` is `OPEN`, `IN_PROGRESS`, or `REOPENED`; work orders in `COMPLETED` or `CANCELLED` do not count. This count is recomputed on every work-order status change that touches the department — creation, start, completion, reopen, and cancel. A department is `congested` exactly when its `open_work_order_count` is greater than or equal to its `backlog_threshold` (an inclusive comparison); `congested` is recomputed whenever `open_work_order_count` changes. The `backlog_threshold` is a positive integer of at least 1 supplied at department creation, and it is the count at or above which the department is treated as congested for the purposes of routing surcharges and auto-escalation tiers on newly breached requests.

### 2.11. Numeric Precision

Where the system computes an average, it produces a value rounded to exactly two decimal places using the round-half-up convention. This applies to the departmental satisfaction average, where a set of scores `{5, 5, 4}` averages to fourteen thirds and is reported as 4.67 rather than the truncated 4.66. Distances and coordinates are not rounded prior to their comparisons; counts and tier-hour thresholds are whole integers.

## 3. Business Logic & Workflows

### 3.1. Reference Configuration

Before any request can be filed, a `SystemAdmin` populates the reference configuration. A service category is created with a human-readable `name` (unique among categories) and a short stable `code` (unique, composed of uppercase letters A–Z and underscores) that routing rules key on. Each category carries a `default_priority` — one of `LOW`, `STANDARD`, `HIGH`, or `EMERGENCY`, defaulting to `STANDARD` — that is applied at triage when intake does not override it, and a `default_department_id` naming the department a request in this category routes to absent any jurisdiction-specific override. A category's `requires_geolocation` flag (default true) governs whether intake of a request in this category must carry coordinates. A category's `active` flag (default true) governs whether new intake referencing it is accepted; turning a category inactive blocks new intake but leaves existing requests untouched.

A jurisdiction is created with a unique `name` and the four bounding-box coordinates `min_lat`, `max_lat`, `min_lng`, and `max_lng`. A jurisdiction may optionally carry an `override_department_id`; when set, requests geolocated into this jurisdiction route to that department instead of the category default, and when null (the default) the jurisdiction imposes no override. A department is created with a unique `name` and a `backlog_threshold`; its `open_work_order_count` and `congested` flag are computed and not supplied. An SLA policy ties a `category_id` and a `priority` together — the pair is unique — and specifies a `resolution_sla_hours` (a whole number of hours, at least 1, allowed between routing and resolution before breach), an `escalation_tier1_hours` (whole hours past the deadline, at least 0, at which a tier-one escalation auto-fires), and an `escalation_tier2_hours` (whole hours past the deadline at which a tier-two escalation auto-fires, which must be strictly greater than `escalation_tier1_hours`). An agent is created against a `department_id` with a `full_name` and an optional `is_supervisor` flag (default false); a supervisor may resolve tier-two escalations and reassign work orders across the department. A citizen self-registers with a unique `email`, a `full_name`, and an optional `notify_channel` — one of `EMAIL`, `SMS`, or `NONE`, defaulting to `EMAIL` — which is stamped onto every notification synthesized for that citizen.

The configuration is richly cross-referenced, and several read endpoints expose those references in reverse: the SLA policies defined for a category, the jurisdictions whose override routes to a department, the agents belonging to a department, the maintenance windows on a department, and the blackout windows on a jurisdiction can each be listed against the parent resource.

### 3.2. Intake and Triage

A citizen files a request by supplying their `citizen_id`, the chosen `category_id`, and a free-text `description`; a dispatcher may file on a citizen's behalf. Coordinates `lat` and `lng` are optional at the schema level but become mandatory in context: if the chosen category has `requires_geolocation` set, both `lat` and `lng` must be present or the filing is rejected with `ERR_GEOLOCATION_REQUIRED` (HTTP 422). Intake against a category whose `active` is false is rejected with `ERR_CATEGORY_INACTIVE` (HTTP 409). A citizen may also include a `requested_priority` to nominate a non-default urgency. A successfully filed request is created in the `SUBMITTED` state with `priority`, `jurisdiction_id`, `department_id`, `cluster_id`, `sla_deadline_at`, `routed_at`, and `resolved_at` all still unset, `sla_breached` false, and `reopen_count` zero.

A dispatcher then triages a `SUBMITTED` request, which moves it `SUBMITTED → TRIAGED`. Triage requires that the request currently be `SUBMITTED`, that its category still be `active` (else `ERR_CATEGORY_INACTIVE`), and — for a geolocation-requiring category — that both `lat` and `lng` be present (else `ERR_GEOLOCATION_REQUIRED`); these same two business constraints guard both intake and triage. Triage performs three derivations. It sets the effective `priority`: if a `requested_priority` was supplied (either originally or as a triage-time override), that value becomes the priority; otherwise the category's `default_priority` is used. It sets `jurisdiction_id` by the smallest-box containment rule described in §2.9, leaving it null when the request has no coordinates or no box contains them. And it synthesizes a status notification recording the `SUBMITTED → TRIAGED` transition for the filing citizen. The request's `version` increments by one. Triage does not yet assign a department or an SLA deadline — those are set only at routing.

Every status notification the system synthesizes follows the same shape. Each carries the `request_id` of the request whose status changed, a `channel` copied from that request's citizen's `notify_channel` at the moment of synthesis (one of `EMAIL`, `SMS`, or `NONE`), the `from_status` (the request's status before the transition) and the `to_status` (its status after), and a templated human-readable `message` describing the transition. These records are append-only and immutable once written.

### 3.3. Routing and Service-Level Deadlines

A dispatcher routes a `TRIAGED` request, advancing it `TRIAGED → ROUTED`. Routing first resolves the destination department: if the request was geolocated into a jurisdiction that carries a non-null `override_department_id`, the request routes there; otherwise it routes to its category's `default_department_id`. The resolved `department_id` is written onto the request. Routing requires that an SLA policy exist for the pair of the request's `category_id` and its effective `priority`; if none exists, routing is rejected with `ERR_NO_SLA_POLICY` (HTTP 409). It also requires that no active maintenance or blackout window block the routing instant — see §3.8 — failing with `ERR_WINDOW_BLOCKS_ROUTING` (HTTP 409) when one does.

When routing succeeds, the system stamps `routed_at` with the current logical instant and computes `sla_deadline_at` as that instant plus the matching policy's `resolution_sla_hours`, added as an exact whole-hour offset and stored to millisecond precision. Routing then creates the request's work order in the `OPEN` state, copying the routed `department_id` onto it, which raises that department's `open_work_order_count` and recomputes its `congested` flag (§2.10). A status notification recording `TRIAGED → ROUTED` is synthesized for the citizen, and the request's `version` increments. Because a request has at most one work order — the `request_id` on a `WorkOrder` is unique — an attempt to route a request that already has a work order is rejected with `ERR_DUPLICATE_WORK_ORDER` (HTTP 409).

### 3.4. Work Order Execution

A work order begins life `OPEN`, carrying the `request_id` it fulfills, the `department_id` copied at routing, a null `assigned_agent_id`, a null `completion_note`, and `OPEN` status. A dispatcher assigns an agent by supplying the `assigned_agent_id` together with `expected_work_order_version`; this is a field-set action that leaves the work order's status at `OPEN` while populating the assigned agent, and it is guarded by the optimistic-concurrency check of §2.7. The agent named must belong to the work order's department, and only an agent of that department may later act on it; an agent acting outside their department is rejected with `ERR_AGENT_WRONG_DEPARTMENT` (HTTP 403).

An agent starts an assigned work order, moving it `OPEN → IN_PROGRESS`. Starting requires the work order to be `OPEN`, to have a non-null `assigned_agent_id`, and that the acting agent belong to the work order's `department_id`. Starting bubbles up across aggregates: the underlying request advances `ROUTED → IN_PROGRESS`, which synthesizes an `ROUTED → IN_PROGRESS` notification for the citizen and increments the request's `version`. The work order's own `version` increments as well.

The agent completes the work order, moving it `IN_PROGRESS → COMPLETED`. Completion requires the work order to be `IN_PROGRESS`, the acting agent to be the same agent recorded in `assigned_agent_id`, and a `completion_note` to be present in the body. On completion the system records the `completion_note`, decrements the department's `open_work_order_count` and recomputes `congested`, and bubbles up to the request, which advances `IN_PROGRESS → RESOLVED`. That cross-aggregate cascade does several things at once: it stamps the request's `resolved_at` with the current instant, synthesizes an `IN_PROGRESS → RESOLVED` notification, creates a satisfaction survey in the `SENT` state for the request if none exists yet, and resolves any still-open escalation on the request as a compensating side effect (each such `Escalation` moves `OPEN → RESOLVED` with `resolved_by_role` recorded as the system). The request's `version` and the work order's `version` each increment.

A dispatcher may cancel an `OPEN` work order, moving it `OPEN → CANCELLED`, when the underlying request is being marked a duplicate or otherwise withdrawn. Cancellation decrements the department's `open_work_order_count` and recomputes `congested`, and increments the work order's `version`. `COMPLETED` and `CANCELLED` are the work order's terminal states, except for the reopen loop described next.

### 3.5. Reopening Resolved Work

A citizen who owns a `RESOLVED` request may reopen it, moving it `RESOLVED → REOPENED`. Reopen is permitted only while the request is `RESOLVED`, only by the citizen who owns it (the acting `X-User-ID` must equal the request's `citizen_id`, else `ERR_NOT_RESOURCE_OWNER`), and only while the reopen window is still open — that is, the request's `resolved_at` plus the system-wide reopen window of 72 hours must be at or after the current instant; a reopen attempted after that window has elapsed is rejected with `ERR_REOPEN_WINDOW_CLOSED` (HTTP 409).

A successful reopen does several things in cascade. It increments the request's `reopen_count` by one and clears `resolved_at` back to null. It drives the request's work order through `COMPLETED → REOPENED` and then immediately `REOPENED → IN_PROGRESS`; the first leg raises the department's `open_work_order_count` and recomputes `congested`, and the second leg bubbles the request back up `REOPENED → IN_PROGRESS`. It expires the request's satisfaction survey if that survey is still in `SENT` (moving the survey `SENT → EXPIRED`). It synthesizes a `RESOLVED → REOPENED` notification, and — when the work order's re-activation bubbles the request to `IN_PROGRESS` — a further `REOPENED → IN_PROGRESS` notification. The request's `version` increments through these transitions.

### 3.6. Closing a Request

A dispatcher closes a `RESOLVED` request, moving it `RESOLVED → CLOSED`. Closing requires the request to be `RESOLVED` and to have no open escalation; a close attempted while an escalation remains open is rejected with `ERR_OPEN_ESCALATION_BLOCKS_CLOSE` (HTTP 409). Closing expires the request's satisfaction survey if it is still in `SENT` (moving it `SENT → EXPIRED`), synthesizes a `RESOLVED → CLOSED` notification, and increments the request's `version`. `CLOSED` is terminal: a closed request carries no further transitions, as does a request folded into a duplicate cluster as a `DUPLICATE`.

### 3.7. Duplicate Clustering

When several citizens report the same problem, a dispatcher consolidates them into a duplicate cluster. The cluster is created with a `category_id` that all members must share and a `canonical_request_id` naming the surviving request that members fold into; the create request must also carry `expected_canonical_version` for the optimistic-concurrency check of §2.7. On creation the cluster opens in `OPEN` status, copies the canonical request's coordinates into `center_lat` and `center_lng`, and begins with a `member_count` of zero. The canonical request's own status is left unchanged.

A dispatcher attaches a `SUBMITTED` request to an `OPEN` cluster as a duplicate member, moving that request `SUBMITTED → DUPLICATE`. Attachment requires that the request be `SUBMITTED`, that the cluster be `OPEN`, that the request's `category_id` equal the cluster's `category_id` (else `ERR_CLUSTER_CATEGORY_MISMATCH`, HTTP 409), and that the request lie within the cluster radius of the cluster's center. That radius is 150 meters, measured by the haversine distance of §2.9 from the candidate's `(lat, lng)` to the cluster's `(center_lat, center_lng)`; the boundary is inclusive, so a request lying exactly at 150 meters is eligible, and one farther than 150 meters is rejected with `ERR_OUTSIDE_CLUSTER_RADIUS` (HTTP 409). On a successful attach the request's `cluster_id` is set to the cluster, the cluster's `member_count` is recomputed as the number of requests whose `cluster_id` is this cluster and whose `status` is `DUPLICATE` (which excludes the canonical request), a `SUBMITTED → DUPLICATE` notification is synthesized for the member's citizen, and the request's `version` increments.

A dispatcher closes a cluster, moving it `OPEN → MERGED_CLOSED`, but only once the canonical request has itself reached `RESOLVED` or `CLOSED`; an attempt to close earlier is rejected with `ERR_CANONICAL_NOT_RESOLVED` (HTTP 409). Closing the cluster synthesizes, for each member request still in `DUPLICATE`, a `DUPLICATE → CLOSED` notification while leaving the member folded in `DUPLICATE`, and increments the cluster's `version`.

### 3.8. Maintenance and Blackout Windows

A `SystemAdmin` can declare service windows that suspend routing. A window carries a `window_type` of either `MAINTENANCE` or `BLACKOUT`, an inclusive `starts_at` instant, and an `ends_at` instant that must be strictly after `starts_at`. The two types differ in scope and in boundary semantics. A `MAINTENANCE` window attaches to a department: it supplies a non-null `department_id` and must leave `jurisdiction_id` null. A `BLACKOUT` window attaches to a jurisdiction: it supplies a non-null `jurisdiction_id` and must leave `department_id` null. A window whose scope is mismatched — a maintenance window missing its department or carrying a jurisdiction, or a blackout window missing its jurisdiction or carrying a department — is rejected with `ERR_WINDOW_SCOPE_INVALID` (HTTP 422).

A new window may not overlap an existing window of the same type and same scope, and the overlap test depends on the type. For two maintenance windows on the same department, the test treats both intervals as closed: they collide when the first starts at or before the second ends and the second starts at or before the first ends — touching endpoints therefore do collide. For two blackout windows on the same jurisdiction, the test treats both intervals as half-open: they collide when the first starts strictly before the second ends and the second starts strictly before the first ends — touching endpoints do not collide. A colliding create is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409).

These windows also gate routing (§3.3). A request cannot be routed when the routing instant falls inside an active window. For a maintenance window on the request's routed department, the instant is inside when it is at or after `starts_at` and at or before `ends_at` (closed on both ends). For a blackout window on the request's `jurisdiction_id`, the instant is inside when it is at or after `starts_at` and strictly before `ends_at` (half-open). Either condition blocks routing with `ERR_WINDOW_BLOCKS_ROUTING` (HTTP 409).

### 3.9. Escalations and the SLA Breach Sweep

Escalations arise two ways. A dispatcher may manually raise one against a request by supplying its `request_id`; this creates an `Escalation` of tier `MANUAL` in `OPEN` status with a `reason` recording it as a manual dispatcher escalation. The system also raises escalations automatically during the breach sweep. Each `Escalation` records the `request_id` it concerns, a `tier` of `TIER1`, `TIER2`, or `MANUAL`, a `reason`, a `status` of `OPEN` or `RESOLVED`, and — once resolved — the `resolved_by_role` of the actor who closed it.

Advancing the logical clock runs the breach sweep against the new clock value. The sweep walks every request whose `status` is `ROUTED`, `IN_PROGRESS`, or `REOPENED` and whose `sla_deadline_at` is set, processing them in `created_at` ascending order so that escalation identifiers are assigned deterministically. For each such request, if the current instant is strictly greater than `sla_deadline_at` — exactly at the deadline the request is not yet breached and no escalation fires — the request's `sla_breached` is set to true and stays true thereafter for breach accounting. The sweep then computes how many whole hours the request is overdue as the floor of the elapsed seconds since `sla_deadline_at` divided by 3600, looks up the policy for the request's `(category_id, priority)`, and applies idempotent auto-escalation: if the overdue hours are at least `escalation_tier2_hours` and the request has no open `TIER2` escalation, it creates a `TIER2` escalation whose `reason` notes the hours breached; otherwise, if the overdue hours are at least `escalation_tier1_hours` and the request has no open escalation at all, it creates a `TIER1` escalation with a similar reason. The advance response reports the new `clock_now`, the list of `breached_request_ids`, and the integer count of `escalations_created`.

An open escalation is resolved either by an appropriate actor or by the system cascade that fires when its request reaches `RESOLVED`. Resolution requires the escalation to be `OPEN` and moves it `OPEN → RESOLVED`, recording the acting role in `resolved_by_role`. Resolving a `TIER2` escalation is restricted: only a supervisor agent (an `Agent` whose `is_supervisor` is true) or an actor whose role is `Dispatcher` or `SystemAdmin` may do so; a non-supervisor agent attempting it is rejected with `ERR_TIER2_REQUIRES_SUPERVISOR` (HTTP 403). A regular agent may resolve a `TIER1` escalation.

### 3.10. Satisfaction Surveys

When a request first reaches `RESOLVED`, the system creates a satisfaction survey in the `SENT` state tied to that request by its `request_id`; there is at most one survey per request. The owning citizen responds by submitting an integer `score` from 1 to 5 inclusive and an optional free-text `comment`, which moves the survey `SENT → COMPLETED`. Responding requires the survey to be `SENT`, the acting citizen to own the surveyed request (`X-User-ID` equal to the request's `citizen_id`, else `ERR_NOT_RESOURCE_OWNER`), and the `score` to be an integer within 1 through 5; a score outside that range is rejected with `ERR_INVALID_SCORE` (HTTP 422). On a successful response the survey's `score` and `comment` are recorded and its `version` increments.

A survey that has not been completed is expired automatically when its request leaves the resolved state without a response — either on reopen or on close, where a still-`SENT` survey moves `SENT → EXPIRED`. The departmental satisfaction read aggregates only `COMPLETED` surveys whose request routed to the named department, reporting the round-half-up average of their scores to two decimal places as `avg_score` along with the `completed_count`; surveys in `SENT` or `EXPIRED` are excluded, and a department with no completed surveys reports a null `avg_score` and a `completed_count` of zero rather than a zero average.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return HTTP `201 Created`. Operations that modify an existing resource, drive a state transition, or perform a computed read return HTTP `200 OK`. Request and response bodies are not tabulated here; the fields each operation consumes and the side effects it triggers are described in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/categories` | Create a service category | SystemAdmin |
| GET | `/categories/{id}` | Fetch a service category | SystemAdmin, Dispatcher, Agent, Citizen |
| GET | `/categories` | List/filter service categories | SystemAdmin, Dispatcher, Agent, Citizen |
| GET | `/categories/{id}/sla-policies` | List SLA policies for a category | SystemAdmin, Dispatcher |
| POST | `/jurisdictions` | Create a jurisdiction bounding box | SystemAdmin |
| GET | `/jurisdictions/{id}` | Fetch a jurisdiction | SystemAdmin, Dispatcher |
| GET | `/jurisdictions/{id}/blackout-windows` | List blackout windows on a jurisdiction | SystemAdmin, Dispatcher |
| POST | `/departments` | Create a department | SystemAdmin |
| GET | `/departments/{id}` | Fetch a department incl. computed backlog | SystemAdmin, Dispatcher, Agent |
| GET | `/departments/{id}/satisfaction` | Computed average satisfaction for a department | SystemAdmin, Dispatcher |
| GET | `/departments/{id}/jurisdictions` | List jurisdictions whose override routes here | SystemAdmin, Dispatcher |
| GET | `/departments/{id}/agents` | List agents belonging to a department | SystemAdmin, Dispatcher, Agent |
| GET | `/departments/{id}/maintenance-windows` | List maintenance windows on a department | SystemAdmin, Dispatcher |
| POST | `/sla-policies` | Create an SLA policy for a (category, priority) | SystemAdmin |
| POST | `/citizens` | Self-register a citizen | Anonymous |
| POST | `/agents` | Create an agent in a department | SystemAdmin |
| POST | `/service-requests` | File a service request (intake) | Citizen, Dispatcher |
| GET | `/service-requests/{id}` | Fetch a service request | SystemAdmin, Dispatcher, Agent, Citizen |
| GET | `/service-requests` | List/filter service requests | SystemAdmin, Dispatcher, Agent, Citizen |
| POST | `/service-requests/{id}/triage` | Triage a request | Dispatcher |
| POST | `/service-requests/{id}/route` | Route a request | Dispatcher |
| POST | `/service-requests/{id}/reopen` | Reopen a resolved request | Citizen |
| POST | `/service-requests/{id}/close` | Close a resolved request | Dispatcher |
| GET | `/service-requests/{id}/notifications` | List notifications for a request | SystemAdmin, Dispatcher, Citizen |
| GET | `/service-requests/{id}/escalations` | List escalations for a request | SystemAdmin, Dispatcher, Agent |
| POST | `/duplicate-clusters` | Create a duplicate cluster | Dispatcher |
| GET | `/duplicate-clusters/{id}` | Fetch a cluster incl. member_count | SystemAdmin, Dispatcher |
| GET | `/duplicate-clusters` | List/filter clusters | SystemAdmin, Dispatcher |
| POST | `/duplicate-clusters/{id}/members` | Attach a request to a cluster as a duplicate | Dispatcher |
| POST | `/duplicate-clusters/{id}/close` | Close a cluster | Dispatcher |
| GET | `/work-orders/{id}` | Fetch a work order | SystemAdmin, Dispatcher, Agent |
| GET | `/work-orders` | List/filter work orders | SystemAdmin, Dispatcher, Agent |
| POST | `/work-orders/{id}/assign` | Assign an agent to a work order | Dispatcher |
| POST | `/work-orders/{id}/start` | Start a work order | Agent |
| POST | `/work-orders/{id}/complete` | Complete a work order | Agent |
| POST | `/work-orders/{id}/cancel` | Cancel an open work order | Dispatcher |
| POST | `/escalations` | Raise a manual escalation | Dispatcher |
| POST | `/escalations/{id}/resolve` | Resolve an escalation | Dispatcher, Agent, SystemAdmin |
| GET | `/surveys/{id}` | Fetch a survey | SystemAdmin, Dispatcher, Citizen |
| GET | `/surveys` | List/filter surveys | SystemAdmin, Dispatcher, Citizen |
| POST | `/surveys/{id}/respond` | Submit a satisfaction score | Citizen |
| POST | `/service-windows` | Create a maintenance or blackout window | SystemAdmin |
| POST | `/_clock/set` | Set the logical clock | SystemAdmin |
| POST | `/_clock/advance` | Advance the clock and run the SLA sweep | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_AGENT_WRONG_DEPARTMENT` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CATEGORY_INACTIVE` | 409 Conflict |
| `ERR_GEOLOCATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CLUSTER_CATEGORY_MISMATCH` | 409 Conflict |
| `ERR_OUTSIDE_CLUSTER_RADIUS` | 409 Conflict |
| `ERR_NO_SLA_POLICY` | 409 Conflict |
| `ERR_REOPEN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CANONICAL_NOT_RESOLVED` | 409 Conflict |
| `ERR_OPEN_ESCALATION_BLOCKS_CLOSE` | 409 Conflict |
| `ERR_TIER2_REQUIRES_SUPERVISOR` | 403 Forbidden |
| `ERR_INVALID_SCORE` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_WORK_ORDER` | 409 Conflict |
| `ERR_WINDOW_SCOPE_INVALID` | 422 Unprocessable Entity |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WINDOW_BLOCKS_ROUTING` | 409 Conflict |
