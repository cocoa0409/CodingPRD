# Smart Home Integration API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Smart Home Integration platform, a back-office system that orchestrates the full delivery lifecycle of a custom residential and commercial smart-home and home-theater build in the style of a Control4-class integrator. A single engagement begins as a design conversation with a client, moves through an equipment proposal and its acceptance, the physical provisioning of a rack and its network devices, the programming of automation scenes, the scheduling of low-voltage install crews, and finally the standing-up of a remote-support service contract. Long after the install is commissioned, the same engagement continues to absorb firmware updates, warranty returns, and signed change orders.

The platform exists because each of these stages carries constraints that ripple into the others, and the cost of an integrator getting them wrong is a truck roll, a contractual dispute, or an unbookable crew. A proposal's pricing depends on the client's billing posture and the region the crew must serve; a device cannot come online before its firmware is current; a commission cannot complete until every device is online and at least one scene is live; a project cannot go active until its service contract is paid up and no change orders are left dangling. The API encodes these dependencies as state machines, derived counters, and guarded transitions so that the business rules are enforced uniformly rather than left to operator memory.

The intended readers of this document are the engineers who will implement the service. The narrative is organized so that the global contract — authentication, response shape, pagination, precision, concurrency, and the cross-cutting invariants — is stated once and precisely in Section 2, while the per-workflow behavior is developed in Section 3. The endpoint and error tables in Sections 4 and 5 are deliberately terse; the conditions that trigger each status code and error live in the prose, not in the tables.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The whole API is mounted at the root path.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly six roles, spelled precisely as follows: `PlatformAdmin`, `SystemsDesigner`, `ProjectManager`, `LowVoltageTech`, `SupportEngineer`, and `Client`.

The five operator roles — `PlatformAdmin`, `SystemsDesigner`, `ProjectManager`, `LowVoltageTech`, and `SupportEngineer` — are all opaque-identity roles. When `X-User-Role` is any of these, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`, and ownership of resources is never inferred from it. `PlatformAdmin` is the operational super-user who onboards clients and crew, drives the logical test clock, and may read every resource. `SystemsDesigner` owns design, equipment proposals, and automation scene programming. `ProjectManager` owns the project lifecycle, install scheduling, crew assignment, and change-order application. `LowVoltageTech` is the low-voltage crew that provisions devices and executes install and commission visits. `SupportEngineer` owns service and remote-support contracts, firmware updates, and warranty/RMA handling.

`Client` is an entity-backed role. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` entity; ownership checks on any resource that references a `Client` compare the resource's owning `client_id` (resolved through the project the resource belongs to) against `X-User-ID`. A `Client` may accept or reject proposals and approve or reject change orders only on projects they own; an ownership failure on those operations is reported as `ERR_NOT_OWNER`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id` formatted as a UUID, with no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created. All entities in this system are mutable and therefore additionally carry an `updated_at` timestamp (same ISO 8601 UTC format) and an integer `version`. The `updated_at` field is refreshed on every mutation, and `version` begins at the value assigned on creation and increments by one on every subsequent mutation, including mutations driven by reconciliation of derived fields rather than by a direct client request on that resource.

Resource identifiers in request bodies and URL paths are referenced by their natural names. Throughout the API a client account is identified by `client_id`, a project by its id, a proposal by `proposalId` (or `proposal_id` as a foreign key on its children), a line item by `lineItemId`, a scene by `sceneId`, a visit by `visitId`, an assignment by `assignmentId`, a crew member by `crewMemberId`, a change order by `coId`, an RMA by `rmaId`, and a firmware update by `updateId`. Foreign-key fields that appear on resources — `project_id`, `rack_id`, `device_id`, `contract_id`, `visit_id`, `crew_member_id`, `replacement_device_id`, and `accepted_proposal_id` — all hold the `id` of the referenced resource.

### 2.5. Nested Resource Retrieval and Path Validation

Many resources are addressed through nested paths that name a project before naming the proposal, line item, scene, visit, assignment, contract, or change order beneath it. For any such request, the system validates the existence of each path identifier in strict left-to-right order and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing in-scope resource. A request for a visit under a non-existent project fails on the project before the visit is ever consulted, and a request for a line item whose `proposalId` does not belong to the named project fails as out-of-scope. Several resources are also reachable in a flat form addressed only by their own id — proposals, visits, devices, crew members, and RMA tickets each have a top-level retrieval — and these resolve the single identifier directly.

### 2.6. Hierarchical Consistency and Derived Counters

The platform maintains immediate consistency between parent and child resources. Several fields on the `Project` are computed counters that the system keeps reconciled rather than accepting from clients. `provisioned_device_count` is the number of `Device` records on the project's rack that are currently in `PROVISIONED` or `ONLINE` state. `open_change_order_count` is the number of `ChangeOrder` records on the project that are in `SUBMITTED` or `APPROVED` state — that is, neither `APPLIED` nor `REJECTED`. `contract_balance_cents` mirrors the `balance_cents` of the project's currently `ACTIVE` (or `SUSPENDED`) contract, and is 0 when the project has no such contract. Each of these recomputes whenever an event that could change it occurs, and every such recomputation is a mutation of the `Project` that refreshes its `updated_at` and increments its `version`.

State changes frequently cascade. When a parent resource transitions in a way that invalidates its children, the system propagates the change downward automatically and reconciles the affected counters. Likewise, certain child-resource events bubble a parent forward through its lifecycle without an explicit request on the parent. These cascades and bubble-ups are described in full alongside the workflows that trigger them in Section 3; the governing principle here is that the server may transition a parent or child on its own when the criteria are met, and each such transition independently bumps that resource's `version` and `updated_at`.

### 2.7. Monetary Values, Counts, and Precision

All monetary amounts in this system are stored and returned as integer cents — `unit_price_cents`, `equipment_subtotal_cents`, `discount_cents`, `labor_cost_cents`, `tax_cents`, `grand_total_cents`, `hourly_rate_cents`, `balance_cents`, `contract_balance_cents`, and `delta_cents`. Wherever a calculation produces a fractional cent before storage, the result is rounded to a whole number of cents using the round-half-up method, applied at each individual rounding step described in Section 3 rather than only once at the end. Counts such as `provisioned_device_count`, `open_change_order_count`, `rack_units_total`, `rack_units_used`, `ip_pool_size`, `qty`, `action_count`, `crew_size_required`, `assigned_crew_count`, and `daily_visit_cap` are integers. Hour-valued fields — `prepaid_hours`, `consumed_hours`, `labor_hours_estimate`, and `added_labor_hours` — are stored as numbers and are not themselves cents.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control against the version of a parent entity. Each such request must carry the parent's expected version as a non-optional body field, and if that value does not equal the parent's current `version` the write is rejected with `ERR_STALE_VERSION` (HTTP 412). The semantics are stale-version rejection: when another writer has advanced the parent's version since the client last read it, the client's view is out of date and the write must not proceed on that stale basis.

First, creating a new proposal carries `expected_project_version`, which must match the current `version` of the project named in the path; this guards against a superseding proposal or a status change having already mutated the project so that the writer's notion of which `DRAFT` proposal it would supersede is stale. Second, creating a visit assignment carries `expected_visit_version`, which must match the current `version` of the visit being staffed; this guards against the visit's staffing having already changed so that the `assigned_crew_count` the writer reasoned about — and the capacity re-check that depends on it — is stale. Third, applying a change order carries `expected_project_version`, which must match the project's current `version`; this guards against a prior change order having already been applied and moved the running grand total, so that a delta computed against a stale total would corrupt the running total. Operations other than these three do not take a version field and are not subject to this check.

### 2.9. Validation Ordering

When a single request could fail multiple checks, the checks are evaluated in a fixed priority order, and the first failure determines the error returned. Authentication is checked first: missing or unknown-role headers yield `ERR_UNAUTHENTICATED`. Authorization is checked next: a role not permitted for the endpoint yields `ERR_UNAUTHORIZED`. Existence of every path-referenced resource is checked third, left-to-right, yielding `ERR_NOT_FOUND`. Ownership for the entity-backed `Client` on the ownership-gated proposal and change-order decisions is checked fourth, yielding `ERR_NOT_OWNER`. Body well-formedness — required fields present and well-typed, enums in range, and the numeric bounds described throughout Section 3 — is checked fifth, yielding `ERR_INVALID_REQUEST`. Foreign-key referential integrity is checked sixth, yielding `ERR_REFERENTIAL_INTEGRITY`. The state precondition for a transition is checked seventh, yielding `ERR_INVALID_STATE` when the target is not in a state from which the requested transition is defined.

After those come the domain-specific checks, still in priority order: temporal clock gates for visit start and no-show and firmware newness; the visit time-conflict check on visit creation; crew assignability (active and region) on assignment creation; the crew time-overlap check on assignment creation; the capacity and quota limits (crew daily cap, rack units, IP pool, and visit staffing at confirm); the fiscal gates for project activation and contract activation; and finally the optimistic-concurrency version check. The specific trigger conditions and their distinct error identifiers are stated within the relevant workflow in Section 3.

### 2.10. The Logical Clock

All temporal reasoning in the system is performed against a server-maintained logical clock rather than wall-clock time. At server startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call is made it remains at that default and never falls back to wall-clock time. An administrative test-driving capability lets `PlatformAdmin` set the logical clock to a supplied instant, provided as the `to_iso8601` field. The clock is the reference for the visit start gate, the no-show gate, and the timestamp written into a change order's `applied_at`.

## 3. Business Logic & Workflows

### 3.1. Clients, Projects, and the Project Lifecycle

A smart-home engagement is rooted in a `Client` account, registered with the client's `full_name`, a contact `email` that must be unique across all clients, and an optional `billing_tier` that is one of `RESIDENTIAL` or `COMMERCIAL` and defaults to `RESIDENTIAL`. The billing tier is consequential: it drives the labor rate applied to proposals and the tax treatment of equipment, as developed in the pricing rules below.

A **Project** is the central organizing entity and is created in `DRAFT` state with a `client_id` naming its owning client, a `site_address` for the physical install, and a `region_code` that is one of `NORTH`, `SOUTH`, `EAST`, or `WEST`. The region matters because the install crew assigned to the project's visits must serve that same region. A project advances through a long lifecycle: `DRAFT` to `PROPOSED` to `ACCEPTED` to `PROVISIONING` to `SCHEDULED` to `INSTALLING` to `COMMISSIONED` to `ACTIVE`, with `CANCELLED` reachable from several early states. Three of its fields — `provisioned_device_count`, `open_change_order_count`, and `contract_balance_cents` — are computed counters initialized to 0 at creation, and `accepted_proposal_id` is initially absent until a proposal is accepted.

Moving an `ACCEPTED` project into `PROVISIONING` is the project manager's signal that physical work may begin; this start-of-provisioning transition requires that `accepted_proposal_id` has been set and that a rack already exists for the project, failing otherwise with `ERR_INVALID_STATE` when no proposal is pinned and with `ERR_RACK_REQUIRED` when no rack has been created. Once in `PROVISIONING`, devices may be registered against the rack. The project then advances largely by bubble-up from its install visits, as described in the visit workflow: the first confirmed install visit moves a `PROVISIONING` project to `SCHEDULED`, an install visit starting moves a `SCHEDULED` project to `INSTALLING`, and a completed commission visit attempts to move an `INSTALLING` project to `COMMISSIONED`. That commission attempt is guarded: it succeeds only when every non-`RETIRED` device on the project's rack is `ONLINE` and at least one scene program is `DEPLOYED`, and otherwise the project remains `INSTALLING` and the guard surfaces as `ERR_DEVICES_NOT_ONLINE` or `ERR_NO_DEPLOYED_SCENE` respectively.

Bringing a `COMMISSIONED` project to `ACTIVE` is a deliberate project-manager action and the final fiscal gate of the build. It requires that a contract for the project is `ACTIVE`, failing with `ERR_CONTRACT_NOT_ACTIVE` otherwise, and that `open_change_order_count` is exactly zero, failing with `ERR_OPEN_CHANGE_ORDERS` otherwise. Once a project is `ACTIVE`, service visits and RMA tickets become permissible.

A project manager may cancel a project from `DRAFT`, `ACCEPTED`, `PROVISIONING`, or `SCHEDULED`, moving it to the terminal `CANCELLED` state. Cancelling a `DRAFT` project supersedes any open `DRAFT` or `SENT` proposal. Cancelling from `ACCEPTED`, `PROVISIONING`, or `SCHEDULED` cascades downward: every non-terminal visit on the project moves to `CANCELLED` (which in turn releases each visit's `ACTIVE` assignments), and every non-`RETIRED` device on the project's rack moves to `RETIRED`, releasing its rack units and management IP. Listing projects supports filtering by `client_id`, by `accepted_proposal_id`, and by `status`.

### 3.2. The Equipment Proposal and Its Pricing

Design work is captured as a **Proposal**, which a `SystemsDesigner` creates against a project. A proposal carries a `project_id`, a monotone `revision` number that starts at 1 and increases with each superseding proposal, a `status`, and a designer-supplied `labor_hours_estimate` giving the estimated low-voltage labor hours for the install. The remaining money fields — `equipment_subtotal_cents`, `discount_cents`, `labor_cost_cents`, `tax_cents`, and `grand_total_cents` — are computed and begin at 0. Creating a proposal requires the `expected_project_version` concurrency field described in §2.8; upon creation the new proposal takes `revision` equal to one more than the highest existing revision on the project, starts in `DRAFT`, supersedes any currently open `DRAFT` or `SENT` proposal (moving each to `SUPERSEDED`), and increments the project's `version` by one. A proposal in `DRAFT` that is open when a higher-revision proposal is created is closed as `SUPERSEDED`; a `SENT` proposal is likewise superseded in favor of a new revision when a superseding proposal is created after a rejection has returned the project to `DRAFT`.

A proposal is itemized through **proposal line items**, each created on a `DRAFT` proposal with a `proposal_id`, a `sku` catalog code that references the vendor equipment catalog, a `category` that is one of `CONTROLLER`, `AUDIO`, `VIDEO`, `NETWORK`, `LIGHTING`, or `ACCESSORY`, a `qty` that must be at least 1, and a `unit_price_cents` list price per unit. A line item also carries a system-managed `removed` flag, false by default; a designer may soft-remove a line item from a `DRAFT` proposal, which sets `removed` to true and excludes it from the equipment subtotal. Line items are listable both beneath their proposal and through the proposal's flat line-item collection.

A proposal lifecycle runs `DRAFT` to `SENT` to one of `ACCEPTED`, `REJECTED`, or `SUPERSEDED`. Sending a proposal is a `SystemsDesigner` action permitted only while the proposal has at least one line item with `removed` false — otherwise `ERR_EMPTY_PROPOSAL` — and only while the owning project is in `DRAFT`, otherwise `ERR_INVALID_STATE`. Sending freezes the line items against further edits, recomputes the full pricing, and moves the project from `DRAFT` to `PROPOSED`.

The pricing computation, run at send time, proceeds in a fixed order because each step depends on the previous. **First**, `equipment_subtotal_cents` is the sum, over every line item whose `removed` flag is false, of that item's `qty` multiplied by its `unit_price_cents`. **Second**, a discount rate is selected from a volume tier on that subtotal: a subtotal below 5,000 dollars (that is, below 500,000 cents) earns no volume discount; a subtotal from 500,000 cents up to but not including 2,000,000 cents earns a rate of 0.05; a subtotal of 2,000,000 cents or more earns a rate of 0.10. If the client's `billing_tier` is `COMMERCIAL`, an additional loyalty rate of 0.02 is added to the volume rate. The combined discount rate is then capped at 0.12, so it may never exceed that ceiling. `discount_cents` is the equipment subtotal multiplied by the final discount rate, rounded half up to whole cents. **Third**, `labor_cost_cents` is `labor_hours_estimate` multiplied by the labor rate for the project's `region_code` and the client's `billing_tier`, rounded half up to whole cents. The per-hour labor rates, in cents, are: for `RESIDENTIAL`, 12,000 in `NORTH`, 10,000 in `SOUTH`, 13,000 in `EAST`, and 11,000 in `WEST`; for `COMMERCIAL`, 15,000 in `NORTH`, 13,000 in `SOUTH`, 16,000 in `EAST`, and 14,000 in `WEST`. **Fourth**, the taxable base is the equipment subtotal minus the discount — labor is never taxed — and the tax rate is 0 for a `COMMERCIAL` client and 0.0825 for a `RESIDENTIAL` client; `tax_cents` is the taxable base multiplied by the applicable tax rate, rounded half up to whole cents. **Fifth**, `grand_total_cents` is the equipment subtotal minus the discount, plus the labor cost, plus the tax.

### 3.3. Acceptance, Rejection, and the Change-Order Cycle

Only the owning `Client` may decide a `SENT` proposal, and only while the project is in `PROPOSED`. Accepting requires that no other proposal of the same project is already `ACCEPTED`, failing otherwise with `ERR_PROPOSAL_ALREADY_ACCEPTED`; acceptance pins the project's `accepted_proposal_id` to this proposal, moves the proposal to `ACCEPTED`, and moves the project from `PROPOSED` to `ACCEPTED`, at which point a rack becomes auto-creatable for the build. Rejecting a `SENT` proposal returns the project from `PROPOSED` to `DRAFT` so that the designer may issue a superseding revision. An ownership failure on either decision is `ERR_NOT_OWNER`, and acting on a project not in `PROPOSED` is `ERR_INVALID_STATE`.

After acceptance, scope changes flow through **change orders**. A `ProjectManager` or `SystemsDesigner` submits a change order against the project with a `description` of what is changing, a signed `delta_cents` that adjusts the project grand total and may be negative for a credit, and an optional `added_labor_hours` that defaults to 0 and must not be negative. A change order is created in `SUBMITTED` state with a system-managed `applied_at` that is absent until the order is applied, and submitting it recomputes `open_change_order_count`. The owning `Client` approves a `SUBMITTED` change order — permitted only while the project is in one of `ACCEPTED`, `PROVISIONING`, `SCHEDULED`, `INSTALLING`, or `COMMISSIONED`, otherwise `ERR_INVALID_STATE` — moving it to `APPROVED`. The `Client` may also reject a change order from either `SUBMITTED` or `APPROVED`, moving it to the terminal `REJECTED` state and recomputing `open_change_order_count`; both approval and rejection are ownership-gated with `ERR_NOT_OWNER`.

Applying an `APPROVED` change order is a `ProjectManager` action that carries the `expected_project_version` concurrency field and requires the project's `accepted_proposal_id` to be set, otherwise `ERR_INVALID_STATE`. Applying it adjusts the accepted proposal's totals: the applied `delta_cents` is added to the accepted proposal's `grand_total_cents`, and this applied delta is authoritative for the running total — the equipment subtotal, discount, and tax are not re-summed. The change order's `added_labor_hours` is added to the proposal's `labor_hours_estimate`, and `labor_cost_cents` is recomputed from the new labor hours purely for record-keeping; the recomputed labor cost is not re-added into the grand total, because the delta already accounts for any labor impact. Application sets `applied_at` to the current logical clock instant, moves the change order to `APPLIED`, recomputes `open_change_order_count`, and increments the project's `version` by one. Multiple applied change orders accumulate: each adds its own `delta_cents` to the running `grand_total_cents` in application order.

### 3.4. The Rack, Its Network, and IP Allocation

Each project has exactly one **Rack**, created by a `ProjectManager` or `SystemsDesigner` with a `rack_units_total` capacity in rack units and a `subnet_cidr` management subnet such as `10.20.0.0/24` that bounds the addresses assignable to devices. The rack carries a computed `rack_units_used`, which begins at 0, and a computed `ip_pool_size`. The IP pool size is derived once from the subnet at rack creation: taking the prefix length after the slash in `subnet_cidr`, the pool size is two raised to the power of thirty-two minus that prefix length, then reduced by two to exclude the network address and the broadcast address. The rack is retrievable as the project's rack collection, which returns an array of zero or one rack.

`rack_units_used` is kept reconciled as the sum of the `rack_units` of every device on the rack whose status is `REGISTERED`, `PROVISIONED`, `ONLINE`, or `FAULTED`; devices that have been `RETIRED` release their rack units and are excluded from the sum. This recomputation runs on device provisioning, device retirement, and any device status change into or out of the live set.

When a device is provisioned, the system assigns it a management IP from the rack's subnet by a deterministic lowest-free-address allocation, with no randomness. Walking the host addresses of `subnet_cidr` in ascending numeric order — starting at the first host offset above the network address and stopping before the broadcast address — the system assigns the lowest host address that is not already held by any non-`RETIRED` device on the same rack. If every host address in the pool is already taken, provisioning fails with `ERR_IP_POOL_EXHAUSTED`.

### 3.5. Devices: Registration, Provisioning, and Commissioning

A **Device** is registered against a rack by a `LowVoltageTech` or `ProjectManager` with a `rack_id`, a `sku` that should match an accepted line item's SKU, a `category` from the same enumeration used by line items (`CONTROLLER`, `AUDIO`, `VIDEO`, `NETWORK`, `LIGHTING`, `ACCESSORY`), and an optional `rack_units` that defaults to 1 and must be at least 0, since non-rack accessories occupy zero units. A device begins in `REGISTERED` state with a `mgmt_ip` and a `firmware_version` both initially absent, and a computed `is_controller` flag that is true exactly when the device's `category` is `CONTROLLER`; scenes require an online controller, as developed below. Devices are listable filtered by `rack_id` and by `status`.

A device advances `REGISTERED` to `PROVISIONED` to `ONLINE`, may go to `FAULTED` from `ONLINE` and back to `ONLINE`, and reaches the terminal `RETIRED` from several states. Provisioning a registered device is a `LowVoltageTech` action requiring that the owning project is in `PROVISIONING` or a later non-terminal state, otherwise `ERR_INVALID_STATE`; that the rack has free capacity, meaning `rack_units_used` plus the device's `rack_units` does not exceed `rack_units_total`, otherwise `ERR_RACK_CAPACITY_EXCEEDED`; and that the management subnet has a free host address, otherwise `ERR_IP_POOL_EXHAUSTED`. Provisioning assigns the device its `mgmt_ip` by the lowest-free rule, then recomputes the rack's `rack_units_used` and the project's `provisioned_device_count`.

Bringing a device online, also a `LowVoltageTech` action, moves it from `PROVISIONED` to `ONLINE` or recovers it from `FAULTED` to `ONLINE`; either way it requires that the device's `firmware_version` has been set by an applied firmware update, otherwise `ERR_FIRMWARE_REQUIRED`, and it recomputes the project's `provisioned_device_count`. A `SupportEngineer` may mark an `ONLINE` device `FAULTED`; doing so triggers a cross-entity cascade in which every `DEPLOYED` scene program whose `device_ids` includes this device is de-deployed back to `VALIDATED`, and the project's `provisioned_device_count` is recomputed.

Retiring a device is a `LowVoltageTech` action reachable from `REGISTERED`, `PROVISIONED`, or `ONLINE` (and also reached by cascade from project cancellation), and it is blocked while the device is referenced by an RMA ticket in `OPENED`, `AUTHORIZED`, or `SHIPPED` state, failing with `ERR_DEVICE_HAS_OPEN_RMA`. Retiring a registered device releases its rack units and recomputes `rack_units_used`. Retiring a provisioned device additionally releases its `mgmt_ip` and recomputes both `rack_units_used` and `provisioned_device_count`. Retiring an online device does all of that and, like faulting, de-deploys any `DEPLOYED` scene program containing the device back to `VALIDATED`. A faulted device is also retired by cascade when an RMA ticket on it reaches `SHIPPED` under a return-for-repair resolution, releasing its `mgmt_ip` and rack units and recomputing the counters.

### 3.6. Automation Scene Programming

A **Scene Program** captures an automation scene such as a "Movie Night" preset. A `SystemsDesigner` creates a scene on a project with a `name` that must be unique among the project's non-`ARCHIVED` scenes, an ordered `device_ids` list naming the devices the scene controls (each of which must belong to this project's rack), and an `action_count` giving the number of programmed device actions, which must be at least 1. A scene runs `DRAFT` to `VALIDATED` to `DEPLOYED`, with `ARCHIVED` as the terminal state and a revise path back to `DRAFT`.

Validating a `DRAFT` scene is a `SystemsDesigner` action with three preconditions: `action_count` must be at least 1, otherwise `ERR_EMPTY_SCENE`; every device in `device_ids` must belong to this project's rack, otherwise `ERR_SCENE_DEVICE_MISMATCH`; and at least one device in `device_ids` must be a controller (its `is_controller` true), otherwise `ERR_NO_CONTROLLER_IN_SCENE`. Deploying a `VALIDATED` scene, also a designer action, requires that every device in `device_ids` is currently `ONLINE`, otherwise `ERR_SCENE_DEVICE_NOT_ONLINE`. A designer may revise a `VALIDATED` scene back to `DRAFT` to re-open it for editing, and may archive a scene from either `DRAFT` or `VALIDATED`. Beyond these explicit designer actions, a `DEPLOYED` scene is automatically de-deployed back to `VALIDATED` by the system whenever one of its member devices goes `FAULTED` or `RETIRED`, as noted in the device workflow. A deployed scene is what satisfies the project's commission gate.

### 3.7. Install Scheduling: Visits and Crew Assignment

Physical work is scheduled as **Visits**. A `ProjectManager` creates a visit on a project with a `window_start` and a `window_end` (ISO 8601 UTC instants, where the end must be strictly after the start), a `visit_kind` of `INSTALL`, `COMMISSION`, or `SERVICE`, and a `crew_size_required` that must be at least 1. The visit copies its `region_code` from the project at creation and carries a computed `assigned_crew_count` that starts at 0. A visit may be created only while the project is in one of `ACCEPTED`, `PROVISIONING`, `SCHEDULED`, `INSTALLING`, `COMMISSIONED`, or `ACTIVE`, otherwise `ERR_INVALID_STATE`. At creation, the new visit's window may not overlap any non-terminal (`PLANNED`, `CONFIRMED`, or `IN_PROGRESS`) visit of the same project, and this conflict check uses closed-interval semantics on `[window_start, window_end]`: two visits that merely touch at an endpoint — where one visit's `window_end` equals another's `window_start` — do conflict and the creation is rejected with `ERR_VISIT_TIME_CONFLICT`. Visits run `PLANNED` to `CONFIRMED` to `IN_PROGRESS` to `COMPLETED`, with `CANCELLED` and `NO_SHOW` as the other terminal outcomes. Visits are retrievable both nested under their project and flatly by id, and are listable filtered by `visit_kind` and `status`.

The visit_kind governs how a visit drives the project: an install visit drives the project from `PROVISIONING` to `SCHEDULED` and from `SCHEDULED` to `INSTALLING`, while a commission visit drives the project from `INSTALLING` to `COMMISSIONED`. Concretely, confirming an install visit while the project is in `PROVISIONING` bubbles the project to `SCHEDULED`; starting an install visit while the project is in `SCHEDULED` bubbles it to `INSTALLING`; and completing a commission visit attempts the guarded project commission. A service visit is the kind permitted once the project is `ACTIVE` and does not bubble the project's lifecycle.

Crew is supplied by **Crew Members**, registered by a `PlatformAdmin` or `ProjectManager` with a `full_name`, a `region_code` the member serves (`NORTH`, `SOUTH`, `EAST`, or `WEST`), a `cert_level` of `APPRENTICE`, `JOURNEYMAN`, or `MASTER`, an optional `daily_visit_cap` that defaults to 2, and an optional `active` flag that defaults to true and indicates whether the member is assignable. Assigning a crew member to a visit is a `ProjectManager` action that creates a **Visit Assignment** carrying a `visit_id` and a `crew_member_id`, beginning in `ACTIVE` state. The create carries the `expected_visit_version` concurrency field described in §2.8.

The assignment-creation checks run in a defined order. First, referential integrity: the `crew_member_id` must name a real crew member. Then crew assignability: the assigned crew member must be active, otherwise `ERR_CREW_INACTIVE`, and the member's `region_code` must equal the visit's `region_code`, otherwise `ERR_CREW_REGION_MISMATCH`. Then a crew time-overlap check: the member's other `ACTIVE` assignments' visit windows may not overlap the target visit's window, evaluated with half-open `[window_start, window_end)` semantics, so adjacency that merely touches at an endpoint — one window's `window_end` equal to another's `window_start` — does not conflict; an overlap is rejected with `ERR_CREW_TIME_CONFLICT`. Finally a daily-cap check: the member's load for the target visit's UTC calendar day is the number of their `ACTIVE` assignments whose visit's `window_start` falls on that same UTC date; if that load plus one would exceed the member's `daily_visit_cap`, the assignment is rejected with `ERR_CREW_DAILY_CAP_EXCEEDED`. The boundary is strict on the cap: when the existing load already equals the cap, the next assignment is rejected, and when the load is one below the cap, the assignment is accepted. A successful assignment recomputes the visit's `assigned_crew_count` and increments the visit's `version` by one.

A project manager may release an assignment, moving it from `ACTIVE` to the terminal `RELEASED` state; a released assignment frees the crew member's capacity so it no longer counts toward `assigned_crew_count`, the daily load, or the crew time-overlap check, and the visit's `assigned_crew_count` is recomputed. Assignments are also released by cascade whenever their parent visit transitions to `CANCELLED`, `NO_SHOW`, or `COMPLETED`. Assignments are listable beneath a visit, beneath a crew member, and through the flat visit-assignments collection, filtered by `status`.

### 3.8. Executing Visits Against the Clock

Confirming a `PLANNED` visit is a `ProjectManager` action with two staffing gates: the visit's `assigned_crew_count` must be at least its `crew_size_required`, otherwise `ERR_UNDERSTAFFED_VISIT`; and if the visit_kind is `COMMISSION`, at least one `ACTIVE` assignee must have a `cert_level` of `JOURNEYMAN` or `MASTER`, otherwise `ERR_CERT_TOO_LOW`. As noted above, confirming an install visit may bubble the project from `PROVISIONING` to `SCHEDULED`.

Starting a `CONFIRMED` visit is a `LowVoltageTech` action gated on the logical clock: it is permitted only when the logical clock is at or after the visit's `window_start`, otherwise `ERR_VISIT_NOT_DUE`. Starting an install visit may bubble the project from `SCHEDULED` to `INSTALLING`. Completing an `IN_PROGRESS` visit, also a `LowVoltageTech` action, releases the visit's `ACTIVE` assignments and, if the visit_kind is `COMMISSION`, attempts the guarded project transition from `INSTALLING` to `COMMISSIONED` (which requires all non-`RETIRED` devices `ONLINE` and at least one `DEPLOYED` scene). A project manager may cancel a `PLANNED` or `CONFIRMED` visit, moving it to `CANCELLED` and releasing its `ACTIVE` assignments, and may mark a `CONFIRMED` visit `NO_SHOW` only once the logical clock is at or after the visit's `window_end`, otherwise `ERR_VISIT_NOT_DUE`; the no-show likewise releases the visit's `ACTIVE` assignments.

### 3.9. Service Contracts and Remote-Support Balance

Each project may have one **Contract** governing remote support, created by a `SupportEngineer` or `ProjectManager` with a `plan` of `BASIC`, `PLUS`, or `PREMIER` (which sets the monthly fee and the remote-support SLA), a `prepaid_hours` bundle of support hours that must not be negative, and an `hourly_rate_cents` overage rate per hour. A contract begins in `PENDING` with `consumed_hours` at 0 and `balance_cents` at 0, and runs `PENDING` to `ACTIVE`, with an `ACTIVE`-to-`SUSPENDED`-and-back cycle and a terminal `CANCELLED`. The contract is retrievable as the project's contract collection, an array of zero or one.

Activating a `PENDING` contract is a `SupportEngineer` action requiring that the project is `COMMISSIONED` or `ACTIVE`, otherwise `ERR_INVALID_STATE`, and that no other contract of the project is already `ACTIVE` or `SUSPENDED`, otherwise `ERR_CONTRACT_ALREADY_ACTIVE`. Activation computes the contract's `balance_cents` and mirrors it onto the project's `contract_balance_cents`. The balance is computed as follows: the remaining hours are `prepaid_hours` minus `consumed_hours`; if the remaining hours are zero or less, the balance is 0; otherwise the balance is the remaining hours multiplied by `hourly_rate_cents`, rounded half up to whole cents. The balance is floored at 0 and never goes negative, so overage hours beyond the prepaid bundle do not push the balance below zero. At activation, before any consumption, this reduces to `prepaid_hours` multiplied by `hourly_rate_cents`, rounded half up.

A support engineer may record a remote-support session that consumes hours: the supplied `hours` are added to the contract's `consumed_hours`, and both `balance_cents` and the project's `contract_balance_cents` are recomputed by the same draw-down formula. A support engineer may suspend an `ACTIVE` contract — which blocks remote-support sessions and new RMA authorizations while suspended — and resume a `SUSPENDED` contract back to `ACTIVE`. Cancelling a contract from either `ACTIVE` or `SUSPENDED` is permitted only when no RMA ticket on the contract is in `OPENED`, `AUTHORIZED`, or `SHIPPED`, otherwise `ERR_CONTRACT_HAS_OPEN_RMA`; cancellation drives the project's `contract_balance_cents` to 0.

### 3.10. Firmware Updates and Rollback

Firmware is managed per device as a **Firmware Update**, staged by a `SupportEngineer` with a `device_id` and a `target_version` semver such as `3.5.0`. A firmware update begins in `STAGED` and carries a system-managed `prior_version` that is absent until the update is applied. Firmware updates run `STAGED` to one of `APPLIED`, `ROLLED_BACK`, or `FAILED`, and are listable per device filtered by `status`.

Applying a staged update is a `SupportEngineer` action permitted only while the device is in `PROVISIONED`, `ONLINE`, or `FAULTED`, otherwise `ERR_INVALID_STATE`, and only when the `target_version` is strictly greater by semver than the device's current `firmware_version`, or the device has no firmware version yet, otherwise `ERR_FIRMWARE_NOT_NEWER`. Applying captures the device's current `firmware_version` (which may be absent) into the update's `prior_version`, then sets the device's `firmware_version` to the `target_version`. A support engineer may instead fail a staged update, which leaves the device's firmware unchanged. Rolling back an applied update is permitted only when it is the most recently applied firmware update for that device, otherwise `ERR_NOT_LATEST_FIRMWARE`; rollback is a compensation that restores the device's `firmware_version` to the exact `prior_version` captured at staging.

### 3.11. Warranty Returns and RMA

When a device fails under warranty, a `SupportEngineer` opens an **RMA Ticket** referencing the faulted `device_id` and the authorizing `contract_id`, with a `fault_code` of `HARDWARE`, `FIRMWARE`, `NETWORK`, or `POWER`, and a `resolution` of `RETURN_REPAIR` or `ADVANCE_REPLACE` that defaults to `RETURN_REPAIR`. The referenced device and contract must belong to the same project, enforced as referential integrity. An RMA carries a system-managed `replacement_device_id`, absent unless an advance replacement is minted. The ticket runs `OPENED` to `AUTHORIZED` to `SHIPPED` to `CLOSED`, with `DENIED` reachable from `OPENED`, and RMA tickets are listable filtered by `device_id`, by `replacement_device_id`, by `contract_id`, and by `status`.

Authorizing an opened ticket is a `SupportEngineer` action requiring that the contract is `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`, and that the device is `FAULTED`, otherwise `ERR_DEVICE_NOT_FAULTED`. If the resolution is `ADVANCE_REPLACE`, authorization performs a cross-aggregate cascade: it mints a new `REGISTERED` device on the same rack carrying the faulted device's `sku`, `category`, and `rack_units`, and records that new device's id in `replacement_device_id`. A support engineer may instead deny an opened ticket. Shipping an authorized ticket is permitted from `AUTHORIZED`; if the resolution is `RETURN_REPAIR`, shipping cascades the faulted device from `FAULTED` to `RETIRED`, releasing its `mgmt_ip` and rack units. A shipped ticket is finally closed by a support engineer.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify or transition an existing resource, and list and retrieval operations, return a `200 OK` status code. To reconstruct the complete request body, response payload, and side effects of any operation below, refer to the corresponding workflow narrative in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Register a client account | PlatformAdmin |
| GET | `/clients/{clientId}` | Get a client | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, Client |
| POST | `/projects` | Create a project | ProjectManager, SystemsDesigner |
| GET | `/projects/{id}` | Get a project with computed counters | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, LowVoltageTech, Client |
| GET | `/projects` | List projects (filter by client_id, accepted_proposal_id, status) | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, Client |
| POST | `/projects/{id}/start-provisioning` | Move an ACCEPTED project to PROVISIONING | ProjectManager |
| POST | `/projects/{id}/activate` | Move a COMMISSIONED project to ACTIVE | ProjectManager |
| POST | `/projects/{id}/cancel` | Cancel a project (cascades to visits and devices) | ProjectManager |
| POST | `/projects/{id}/rack` | Create the project's rack | ProjectManager, SystemsDesigner |
| GET | `/projects/{id}/rack` | Get the project's rack | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, LowVoltageTech, Client |
| POST | `/projects/{id}/proposals` | Create a proposal revision (OCC-guarded on project version) | SystemsDesigner |
| GET | `/projects/{id}/proposals` | List proposals of a project | PlatformAdmin, SystemsDesigner, ProjectManager, Client |
| GET | `/projects/{id}/proposals/{proposalId}` | Get a proposal (nested) with computed totals | PlatformAdmin, SystemsDesigner, ProjectManager, Client |
| GET | `/proposals/{id}` | Get a proposal by id (flat) | PlatformAdmin, SystemsDesigner, ProjectManager, Client |
| GET | `/proposals/{id}/line-items` | List a proposal's line items | PlatformAdmin, SystemsDesigner, ProjectManager, Client |
| POST | `/projects/{id}/proposals/{proposalId}/line-items` | Add a line item to a DRAFT proposal | SystemsDesigner |
| GET | `/projects/{id}/proposals/{proposalId}/line-items` | List line items of a proposal | PlatformAdmin, SystemsDesigner, ProjectManager, Client |
| POST | `/projects/{id}/proposals/{proposalId}/line-items/{lineItemId}/remove` | Soft-remove a line item from a DRAFT proposal | SystemsDesigner |
| POST | `/projects/{id}/proposals/{proposalId}/send` | Send a proposal (freezes and totals it) | SystemsDesigner |
| POST | `/projects/{id}/proposals/{proposalId}/accept` | Accept a SENT proposal | Client |
| POST | `/projects/{id}/proposals/{proposalId}/reject` | Reject a SENT proposal | Client |
| POST | `/devices` | Register a device against a rack | LowVoltageTech, ProjectManager |
| GET | `/devices/{id}` | Get a device | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, LowVoltageTech, Client |
| GET | `/devices` | List devices (filter by rack_id, status) | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, LowVoltageTech, Client |
| POST | `/devices/{id}/provision` | Provision a device (allocate mgmt_ip and RU) | LowVoltageTech |
| POST | `/devices/{id}/bring-online` | Bring a PROVISIONED or FAULTED device ONLINE | LowVoltageTech |
| POST | `/devices/{id}/mark-faulted` | Mark an ONLINE device FAULTED | SupportEngineer |
| POST | `/devices/{id}/retire` | Retire a device | LowVoltageTech |
| POST | `/devices/{id}/firmware-updates` | Stage a firmware update | SupportEngineer |
| GET | `/devices/{id}/firmware-updates` | List firmware updates of a device | PlatformAdmin, SupportEngineer, LowVoltageTech, ProjectManager |
| POST | `/devices/{id}/firmware-updates/{updateId}/apply` | Apply a staged firmware update | SupportEngineer |
| POST | `/devices/{id}/firmware-updates/{updateId}/fail` | Mark a staged firmware update FAILED | SupportEngineer |
| POST | `/devices/{id}/firmware-updates/{updateId}/rollback` | Roll back the latest applied firmware update | SupportEngineer |
| POST | `/projects/{id}/scenes` | Create a scene program | SystemsDesigner |
| GET | `/projects/{id}/scenes` | List scenes of a project | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, Client |
| GET | `/projects/{id}/scenes/{sceneId}` | Get a scene program | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, Client |
| POST | `/projects/{id}/scenes/{sceneId}/validate` | Validate a DRAFT scene | SystemsDesigner |
| POST | `/projects/{id}/scenes/{sceneId}/deploy` | Deploy a VALIDATED scene | SystemsDesigner |
| POST | `/projects/{id}/scenes/{sceneId}/revise` | Re-open a VALIDATED scene to DRAFT | SystemsDesigner |
| POST | `/projects/{id}/scenes/{sceneId}/archive` | Archive a DRAFT or VALIDATED scene | SystemsDesigner |
| POST | `/projects/{id}/visits` | Create a visit | ProjectManager |
| GET | `/projects/{id}/visits` | List visits of a project (filter by visit_kind, status) | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, LowVoltageTech, Client |
| GET | `/projects/{id}/visits/{visitId}` | Get a visit (nested) | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, LowVoltageTech, Client |
| GET | `/visits/{id}` | Get a visit by id (flat) | PlatformAdmin, SystemsDesigner, ProjectManager, SupportEngineer, LowVoltageTech, Client |
| GET | `/visits/{id}/assignments` | List a visit's assignments | PlatformAdmin, ProjectManager, LowVoltageTech |
| GET | `/crew-members/{id}/assignments` | List a crew member's assignments | PlatformAdmin, ProjectManager, LowVoltageTech |
| POST | `/projects/{id}/visits/{visitId}/assignments` | Assign a crew member (OCC-guarded on visit version) | ProjectManager |
| GET | `/projects/{id}/visits/{visitId}/assignments` | List assignments of a visit | PlatformAdmin, ProjectManager, LowVoltageTech |
| POST | `/projects/{id}/visits/{visitId}/assignments/{assignmentId}/release` | Release a crew assignment | ProjectManager |
| POST | `/projects/{id}/visits/{visitId}/confirm` | Confirm a PLANNED visit | ProjectManager |
| POST | `/projects/{id}/visits/{visitId}/start` | Start a CONFIRMED visit | LowVoltageTech |
| POST | `/projects/{id}/visits/{visitId}/complete` | Complete an IN_PROGRESS visit | LowVoltageTech |
| POST | `/projects/{id}/visits/{visitId}/cancel` | Cancel a PLANNED or CONFIRMED visit | ProjectManager |
| POST | `/projects/{id}/visits/{visitId}/no-show` | Mark a CONFIRMED visit NO_SHOW | ProjectManager |
| POST | `/crew-members` | Register a crew member | PlatformAdmin, ProjectManager |
| GET | `/crew-members/{crewMemberId}` | Get a crew member | PlatformAdmin, ProjectManager, LowVoltageTech |
| POST | `/projects/{id}/contract` | Create the service contract | SupportEngineer, ProjectManager |
| GET | `/projects/{id}/contract` | Get the project's contract(s) | PlatformAdmin, SupportEngineer, ProjectManager, Client |
| POST | `/projects/{id}/contract/activate` | Activate the PENDING contract | SupportEngineer |
| POST | `/projects/{id}/contract/suspend` | Suspend an ACTIVE contract | SupportEngineer |
| POST | `/projects/{id}/contract/resume` | Resume a SUSPENDED contract | SupportEngineer |
| POST | `/projects/{id}/contract/cancel` | Cancel a contract | SupportEngineer |
| POST | `/projects/{id}/contract/consume` | Record a remote-support session consuming hours | SupportEngineer |
| POST | `/rma-tickets` | Open an RMA ticket | SupportEngineer |
| GET | `/rma-tickets/{rmaId}` | Get an RMA ticket | PlatformAdmin, SupportEngineer, ProjectManager |
| GET | `/rma-tickets` | List RMA tickets (filter by device_id, replacement_device_id, contract_id, status) | PlatformAdmin, SupportEngineer, ProjectManager |
| POST | `/rma-tickets/{rmaId}/authorize` | Authorize an OPENED RMA | SupportEngineer |
| POST | `/rma-tickets/{rmaId}/deny` | Deny an OPENED RMA | SupportEngineer |
| POST | `/rma-tickets/{rmaId}/ship` | Ship an AUTHORIZED RMA | SupportEngineer |
| POST | `/rma-tickets/{rmaId}/close` | Close a SHIPPED RMA | SupportEngineer |
| POST | `/projects/{id}/change-orders` | Submit a change order | ProjectManager, SystemsDesigner |
| GET | `/projects/{id}/change-orders` | List change orders of a project | PlatformAdmin, ProjectManager, SystemsDesigner, Client |
| GET | `/projects/{id}/change-orders/{coId}` | Get a change order | PlatformAdmin, ProjectManager, SystemsDesigner, Client |
| POST | `/projects/{id}/change-orders/{coId}/approve` | Approve a SUBMITTED change order | Client |
| POST | `/projects/{id}/change-orders/{coId}/reject` | Reject a SUBMITTED or APPROVED change order | Client |
| POST | `/projects/{id}/change-orders/{coId}/apply` | Apply an APPROVED change order (OCC-guarded on project version) | ProjectManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EMPTY_PROPOSAL` | 409 |
| `ERR_PROPOSAL_ALREADY_ACCEPTED` | 409 |
| `ERR_RACK_REQUIRED` | 409 |
| `ERR_RACK_CAPACITY_EXCEEDED` | 409 |
| `ERR_IP_POOL_EXHAUSTED` | 409 |
| `ERR_FIRMWARE_REQUIRED` | 409 |
| `ERR_FIRMWARE_NOT_NEWER` | 409 |
| `ERR_NOT_LATEST_FIRMWARE` | 409 |
| `ERR_EMPTY_SCENE` | 409 |
| `ERR_SCENE_DEVICE_MISMATCH` | 422 |
| `ERR_NO_CONTROLLER_IN_SCENE` | 409 |
| `ERR_SCENE_DEVICE_NOT_ONLINE` | 409 |
| `ERR_UNDERSTAFFED_VISIT` | 409 |
| `ERR_CERT_TOO_LOW` | 409 |
| `ERR_VISIT_NOT_DUE` | 409 |
| `ERR_CREW_TIME_CONFLICT` | 409 |
| `ERR_VISIT_TIME_CONFLICT` | 409 |
| `ERR_CREW_DAILY_CAP_EXCEEDED` | 409 |
| `ERR_CREW_REGION_MISMATCH` | 422 |
| `ERR_CREW_INACTIVE` | 422 |
| `ERR_DEVICES_NOT_ONLINE` | 409 |
| `ERR_NO_DEPLOYED_SCENE` | 409 |
| `ERR_DEVICE_NOT_FAULTED` | 409 |
| `ERR_DEVICE_HAS_OPEN_RMA` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_CONTRACT_ALREADY_ACTIVE` | 409 |
| `ERR_CONTRACT_HAS_OPEN_RMA` | 409 |
| `ERR_OPEN_CHANGE_ORDERS` | 409 |
| `ERR_STALE_VERSION` | 412 |
