# Retail Merchandising Reset Field Services API — Product Requirements Document

## 1. Introduction

Retail merchandising agencies live and die by the reset: a coordinated sweep through dozens or hundreds of stores in which shelves are torn down to the planogram, new items are cut over, fixtures are installed, and photographic proof is captured for the client who is paying for the work. The operational reality behind that sweep is messy — field reps who may be W-2 employees or 1099 contractors, mileage and travel-time pay that differ by worker classification, fixture and planogram shipments that must physically arrive before anyone may legally start work, photographic evidence that must be verified before the client can be billed, and rework visits that bill at zero when the first pass fails inspection.

This document specifies the Retail Merchandising & Reset Field Services API, mounted under `/retail-reset`. The system coordinates the full engagement lifecycle: a `ProjectManager` scopes a project and its store list for a client, schedules field reps against individual stores, tracks fixture shipments against fixture-install work, verifies or rejects photo evidence, and manages rework through client-authorized approvals. A `FieldRep` executes the visit — departing, checking in, uploading evidence, checking out — and files mileage and travel-time claims. A `PayrollAdmin` adjudicates those claims under the rep's worker-classification pay rules. A `BillingClerk` finalizes the invoice once every store has reached a terminal outcome and every exception is resolved. The `Client` role self-approves or denies rework requests for its own projects, subject to the project's escalation posture.

Two design commitments run through the whole specification. First, every monetary figure is an integer number of cents; rounding happens exactly once, at a pinned point in each calculation, and never again. Second, the system's notion of "now" is a server-managed logical clock — not wall-clock time — so that visit windows, shipment lateness, and rework-authorization expiry are fully deterministic. Before any clock-setting call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time; an admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant — any well-formed ISO 8601 instant is accepted and monotonic increase is not enforced — and returns the resulting `current_utc`.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID` to identify the acting party and `X-User-Role` to specify their operational capacity. The system recognizes five working roles plus one unauthenticated placeholder. The roles are spelled exactly as follows: `ProjectManager`, `FieldRep`, `Client`, `PayrollAdmin`, `BillingClerk`. The placeholder role `Anonymous` is reserved for negative authentication testing: it is not a declared working role, and any request that omits the headers or carries an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `FieldRep`, `X-User-ID` is the `id` of the acting `FieldRep` entity; ownership checks on any resource that references a field rep — an assignment's `rep_id`, a mileage log's `rep_id` — compare that foreign-key field to `X-User-ID`, and a rep acting on another rep's assignment is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` entity; ownership checks compare a project's `client_id` to `X-User-ID`, and a client acting on another client's project is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `ProjectManager`, `PayrollAdmin`, or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server does not compare it against any entity's `id`. `Anonymous`, being a placeholder, also carries an opaque identifier.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from wall-clock time rather than the logical clock of §2.10.
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
- An unexpected server-side fault is surfaced in the same envelope with `error_id` `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` below 1 or above 100, a negative `offset`, or a non-integer spelling of either parameter is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — Client, Project, Store, ProjectStore, FieldRep, Assignment, StoreVisit, FixtureShipment, ReworkAuthorization, MileageLog, and Invoice — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp indicating when the resource was last modified; refreshed on any mutation.
- `version` (integer): a system-managed integer that starts at 1 at creation, increments by exactly 1 with every modification to the resource, and is the basis for optimistic concurrency control.

Two evidence resources are deliberately lighter. A `PhotoEvidence` record and an `ExceptionReport` record carry only `id` and `created_at`; both `updated_at` and `version` are absent on these two entities, because they are immutable once filed (an exception's later `resolution` change is the one sanctioned mutation, and it does not imply a `version` field).

### 2.5. Nested Resource Retrieval and Cross-Entity Ownership

The API enforces strict, left-to-right validation on every request. When an endpoint path or request body references multiple resources, every path identifier and every body foreign-key reference must resolve to an existing entity, validated left to right; the first unresolvable reference is rejected with `ERR_NOT_FOUND` (HTTP 404). Only after existence is established does the system check business referential integrity: the store being scheduled must belong to the project named in the same request, and any rework authorization supplied on the scheduling path must name that same project and store row; the mileage log's assignment must belong to the claiming rep's own assignment set; a manually created rework authorization's store must belong to its project and its rejected visit must belong to that store row; a fixture shipment's destination store row must belong to the named project; an invoice's project must belong to the named client; and any photo or exception filing must name a store visit that exists. A violation of any of these cross-entity ownership rules is rejected with `ERR_CROSS_ENTITY_MISMATCH` (HTTP 422). This referential check guards seven operations: assignment creation, mileage-log submission, manual rework-authorization creation, fixture-shipment registration, invoice creation, photo upload, and exception filing.

### 2.6. Validation Order and Input Sanitization

Every request passes through a fixed validation cascade, and the order is observable because an earlier failure masks later ones. First, authentication: the presence of well-formed `X-User-Role` and `X-User-ID` headers with a declared role (failure: `ERR_UNAUTHENTICATED`). Second, authorization: the acting role must be permitted for the endpoint (failure: `ERR_UNAUTHORIZED`). Entity-ownership checks of §2.1 — a rep confined to its own assignments and mileage logs, a client confined to its own projects — are evaluated immediately after the target entity's existence is established and ahead of state legality. Third, existence: path identifiers and body foreign keys resolve left to right (failure: `ERR_NOT_FOUND`). Fourth, state legality: the target entity must be in a state from which the requested transition is defined (failure: `ERR_INVALID_STATE`, HTTP 409). Fifth, cross-entity ownership (failure: `ERR_CROSS_ENTITY_MISMATCH`). Sixth, temporal sanity (failure: `ERR_TEMPORAL_INVALID`, HTTP 422). Seventh, the domain business constraints — rep double-booking, store-list uniqueness, fixture-delivery gating, billing-model resolvability, open-exception gating, and workforce-classification rules — each with its own error code detailed in §3. Finally, raw input sanitization — required fields present and correctly typed, enums within their declared sets, non-negative integer fields at least 0, and an exception's `sku_count` at least 1 — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Optimistic-concurrency checks sit after input sanitization, so a stale write is reported only for an otherwise-valid request. One check sits at the very end of the cascade: on the rework scheduling path, the authorization-state check of §3.5 (`ERR_REWORK_NOT_AUTHORIZED`) is evaluated after even the optimistic-concurrency checks, so a malformed or otherwise-invalid rework request always surfaces its earlier error first.

### 2.7. Monetary Values, Integer Cents, and Pinned Rounding

Every monetary value in the system is an integer number of cents: negotiated rates such as `hourly_rate_cents` and `per_store_rate_cents` on a client, per-mile and per-minute pay rates such as `mileage_rate_cents` and `travel_minute_rate_cents` on a rep, computed amounts such as `mileage_pay_cents`, `travel_time_pay_cents`, and `billable_amount_cents`, and invoice figures such as `line_total_cents`, `adjustment_cents`, and `grand_total_cents`. Non-negative rate and quantity inputs must be at least 0. Rounding is pinned, not opportunistic: where a calculation produces a fractional cent, the rule is round-half-up to a whole cent, applied exactly at the point each calculation specifies, and never re-applied to figures that were already rounded upstream. In particular, travel-time pay rounds each tier to whole cents before the tiers are summed, and invoice line totals are exact integer sums of per-visit amounts that were already rounded at verification time — the sum itself is never re-rounded.

### 2.8. Optimistic Concurrency Control

Two write operations carry optimistic-concurrency guards, and only those two. No other endpoint takes a version field.

Scoping a project requires the request to carry `expected_project_version`, equal to the project's current `version` as the caller last observed it. If the project's version has advanced since that read — because another writer added or dropped store-list rows, changed the billing override, or otherwise mutated the project — the scoping request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). The caller must re-read the project and retry with the current version, so the scoping decision is never based on a stale store list.

Finalizing an invoice requires the request to carry `expected_invoice_version`, equal to the invoice's current `version` as the caller last observed it. If the invoice's version has advanced since that read — for example because a newly verified visit was folded into `line_total_cents` — the finalize request is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412), preventing the caller from locking an outdated grand total.

### 2.9. The Project Posture Ledger

Every project carries a `rework_penalty_score`, a monotonically accumulating integer that starts at 0 and never decrements. Six operational events feed it: rejecting a submitted visit adds 10; a client denying a rework authorization adds 5; a rework authorization expiring past the store's due date adds 7; a fixture shipment entering a delivery exception adds 3; a fixture shipment delivered after its promised date adds 5; and a fixture shipment declared lost adds 8. From the score the system derives the project's `posture`: `NORMAL` while the score is below 20, `WATCH` once the score reaches at least 20 but remains below 40, and `ESCALATED` once the score reaches at least 40. Posture is not merely cosmetic — an `ESCALATED` project blocks client self-approval of rework, forcing manual project-manager handling.

### 2.10. The Logical Clock and Temporal Rules

All server-stamped times — entity `created_at` and `updated_at` fields, a visit's `check_in_at` and `check_out_at`, scan-event lateness, authorization expiry — come from the logical clock described in §1. Every server-stamped timestamp is serialized as ISO 8601 in UTC with exactly three fractional digits (for example, `2026-08-05T09:30:00.000Z`). An assignment's `scheduled_end` must be strictly after its `scheduled_start`. A project-store row's `due_date` must not be earlier than the current logical date at the time the row is added. A photo's `captured_at` must fall inside the visit's window from check-in to the present, as detailed in §3.4. Violations of these temporal rules are rejected with `ERR_TEMPORAL_INVALID`.

## 3. Business Logic & Workflows

### 3.1. Clients, Stores, and the Field Workforce

A `ProjectManager` onboards a client organization by supplying its display `name` and an optional default `billing_model`, which must be one of `PER_STORE` or `HOURLY`. The negotiated rates travel with the client: `hourly_rate_cents` is required when the billing model is `HOURLY`, and `per_store_rate_cents` is required when the model is `PER_STORE`; both must be at least 0. A client's lifecycle `status` starts at `ACTIVE` and may move through `SUSPENDED` to `TERMINATED`; only an `ACTIVE` client may have its projects scoped. No endpoint in this API changes a client's `status` — the `SUSPENDED` and `TERMINATED` states are reserved, and a client remains `ACTIVE` for the life of the service.

Stores are retailer locations, registered by a `ProjectManager` with a retailer-assigned `store_number`, a display `name`, a street `address`, and an IANA `timezone` used for visit-window reasoning. Store numbers carry no system-enforced uniqueness of their own; the only uniqueness constraint is the project store-list duplicate rule of §3.2.

The field workforce is administered by a `PayrollAdmin`, who registers each rep with a `full_name`, an `employment_type` of either `W2` or `C1099`, a `mileage_policy` of either `HOME_BASED` or `FIRST_STOP`, and the pay parameters `home_base_commute_miles`, `mileage_rate_cents`, and `travel_minute_rate_cents`, each at least 0. The commute miles represent the rep's ordinary one-way commute and are used to offset reimbursable mileage for the home-based policy. The travel minute rate matters only for `W2` reps — a `C1099` rep is never paid travel time, regardless of what rate is on file. A rep's `status` starts at `ACTIVE` and may move through `SUSPENDED` to `TERMINATED`; only an `ACTIVE` rep may be scheduled. As with clients, no endpoint changes a rep's `status`, so a rep remains `ACTIVE` for the life of the service.

### 3.2. Project Setup: From Draft to Scoped to In-Field

A `ProjectManager` creates a project under a client by supplying the `client_id`, a `title` such as "Q4 cereal reset", and a `scope_type` of `RESET`, `NEW_ITEM_CUTOVER`, `AUDIT`, or `FIXTURE_INSTALL`, optionally overriding the client's billing model via `billing_model`. The project is born in `DRAFT` status. Its `effective_billing_model` is not yet resolved; its `rework_penalty_score` is 0, its `posture` is `NORMAL`, and its `completed_store_count` is 0.

The store list is built row by row: each row names a `project_id`, a `store_id`, and a `due_date` by which the reset must be completed at that store, and is born in `PENDING` status with `assigned_rep_id` unset. Rows may be added while the project is `DRAFT`, `SCOPED`, or `IN_FIELD`; adding a row to a `RECONCILING`, `COMPLETED`, or `CANCELLED` project is a state rejection with `ERR_INVALID_STATE`. Adding a store-list row is a mutation of the project for concurrency purposes — it increments the parent project's `version` by 1 alongside the new row's own creation. The list rejects duplicates: the same store may not appear twice on one project among rows that are not `DROPPED`, and such an attempt is rejected with `ERR_DUPLICATE_STORE` (HTTP 409). A row whose `due_date` falls before the current logical date is rejected with `ERR_TEMPORAL_INVALID`.

Scoping is the pivotal commitment. A `ProjectManager` scopes a `DRAFT` project, moving it to `SCOPED`, which requires three preconditions: at least one store-list row exists in `PENDING`; the owning client is `ACTIVE`; and a billing model is resolvable. Resolution takes the project's own `billing_model` override when set, otherwise the client's default `billing_model`; if neither is set, or if the resolved model's required rate is missing from the client (`hourly_rate_cents` for an hourly project, `per_store_rate_cents` for a per-store project), scoping is rejected with `ERR_BILLING_MODEL_UNRESOLVABLE` (HTTP 422). Each of the other precondition failures — the project not being `DRAFT`, no `PENDING` store-list row existing, or the client not being `ACTIVE` — is a state rejection with `ERR_INVALID_STATE` (HTTP 409). When scoping succeeds, the resolved value is frozen into `effective_billing_model` — later edits to the client's default do not retroactively re-price the project — and the project's `version` increments by 1. Because scoping freezes commercial terms against a store list the caller believes is current, the request must carry `expected_project_version` per §2.8.

A project leaves `DRAFT` in only two ways: scoping, or cancellation. Cancellation is permitted from `DRAFT` or `SCOPED` unconditionally, and from `IN_FIELD` provided no assignment of the project is currently `ON_SITE`. Cancelling from `DRAFT` or `SCOPED` drops every store-list row in `PENDING` or `ASSIGNED` to `DROPPED`. Cancelling from `IN_FIELD` drops every row in `PENDING`, `ASSIGNED`, `IN_PROGRESS`, or `REWORK_REQUIRED` to `DROPPED`, cancels every assignment in `SCHEDULED` or `EN_ROUTE`, and clears each affected store row's `assigned_rep_id`. Every cancellation increments the project's `version` by 1 and lands the project in the terminal `CANCELLED` state. Cancellation does not retire rework authorizations: any authorization still `REQUESTED` or `APPROVED` on a cancelled project remains so until the clock-driven expiry sweep of §3.5 moves it to `EXPIRED`.

The transition from `SCOPED` to `IN_FIELD` is not explicit — it fires automatically the moment the project's first assignment reaches `SCHEDULED`, incrementing the project's `version` by 1. From then on, field execution drives everything.

### 3.3. Scheduling and Executing Store Visits

A `ProjectManager` schedules a rep against a store-list row by supplying `project_id`, `project_store_id`, `rep_id`, and a `scheduled_start` and `scheduled_end` window. The new assignment is born `SCHEDULED` with `is_rework` false for an initial visit, the store row advances `PENDING` to `ASSIGNED` and records the rep in `assigned_rep_id`, and the store row's `version` increments by 1. Creation is refused unless the store row is `PENDING` (or `REWORK_REQUIRED` on the rework path of §3.5), the project is `SCOPED` or `IN_FIELD`, the rep is `ACTIVE`, and no existing assignment for that same store row sits in `SCHEDULED`, `EN_ROUTE`, or `ON_SITE` — a violation of any of these conditions is a state rejection with `ERR_INVALID_STATE`. Scheduling against a `REWORK_REQUIRED` row without supplying `rework_authorization_id` is likewise a state rejection with `ERR_INVALID_STATE`.

Three business constraints guard scheduling. The rep's calendar must not double-book: the new window may not overlap any existing `SCHEDULED`, `EN_ROUTE`, or `ON_SITE` assignment of the same rep, using half-open interval semantics in which one assignment's end exactly equal to another's start is not an overlap; a violation is rejected with `ERR_REP_DOUBLE_BOOKED` (HTTP 409). Worker classification restricts scope: a `C1099` rep may only be assigned to projects whose `scope_type` is not `FIXTURE_INSTALL`, because heavy-fixture work requires W-2 employees under client compliance rules; a violation is rejected with `ERR_CLASSIFICATION_FORBIDDEN` (HTTP 422). And the scheduling window must satisfy the temporal rule of §2.10.

Once scheduled, the rep drives the visit. Marking departure moves the assignment `SCHEDULED` to `EN_ROUTE`; only the rep named in the assignment's `rep_id` may do this. Checking in moves the assignment from either `SCHEDULED` or `EN_ROUTE` to `ON_SITE`, and is likewise restricted to the assigned rep. Check-in creates the visit itself: a store-visit record is born with `check_in_at` stamped from the logical clock, `check_out_at` unset, `on_site_minutes` 0 until checkout, `verification_status` `PENDING_REVIEW`, `billable_amount_cents` unset until verification, and `is_rework` copied from the assignment. The store row advances `ASSIGNED` to `IN_PROGRESS` with its `version` incremented by 1. A rep may hold at most one `ON_SITE` assignment at a time — check-in while the same rep has another assignment `ON_SITE` is rejected as a double-booking violation.

Fixture-install projects impose a delivery gate. Marking departure is blocked while any fixture shipment for the store sits in `LABEL_CREATED` or `IN_TRANSIT` with a `promised_date` on or before the current logical date. Checking in is blocked while any fixture shipment for the store sits in `LABEL_CREATED`, `IN_TRANSIT`, or `DELIVERY_EXCEPTION` — a delivered shipment lifts the gate, and no gate applies to other scope types. Either blocked attempt is rejected with `ERR_FIXTURES_NOT_DELIVERED` (HTTP 409).

Checking out requires the visit to already carry at least one `BEFORE` photo and at least one `AFTER` photo; attempting checkout without both is rejected with `ERR_INVALID_STATE`. A successful checkout stamps `check_out_at` from the logical clock, computes `on_site_minutes` as the whole minutes between check-in and check-out rounded down, and moves the assignment `ON_SITE` to `SUBMITTED`; the response carries the updated store-visit record.

A `ProjectManager` may cancel an assignment while it is `SCHEDULED` or `EN_ROUTE`. Cancellation moves the assignment to `CANCELLED`, reverts the store row from `ASSIGNED` back to `PENDING`, and clears the row's `assigned_rep_id`. If the cancelled assignment was the project's last non-terminal assignment and the project is `IN_FIELD` with zero verified visits, the project simply remains `IN_FIELD` — there is no reverse transition to `SCOPED`.

### 3.4. Photo Evidence and Exception Reporting

While an assignment is `ON_SITE` — the rep physically at the store — the rep uploads photo evidence against the open visit. Each photo carries a `photo_type` of `BEFORE`, `AFTER`, `POG_LABEL`, `FIXTURE`, or `VOID_AREA`, an `image_url` reference, and a client-reported `captured_at` timestamp. Uploads are accepted only while the owning assignment remains `ON_SITE`; after checkout the visit is frozen and further uploads are rejected with `ERR_INVALID_STATE`. While on site, a photo's `captured_at` must be at or after the visit's `check_in_at` and at or before the current logical clock time — a capture timestamp before check-in, or in the future, is rejected with `ERR_TEMPORAL_INVALID`. The comparison is at second-level precision, inclusive on both ends.

Exception reports document shelf-level problems found during the visit: an `exception_type` of `OUT_OF_STOCK`, `VOID`, `FIXTURE_MISSING`, `POG_MISSING`, or `PRICE_MISMATCH`; a `sku_count` of at least 1; and a `severity` of `LOW`, `MEDIUM`, or `HIGH`. Either the visiting `FieldRep` or a `ProjectManager` may file one against a visit, naming the `store_visit_id`; filing is not gated on the visit's or assignment's state — an exception may be filed against any existing visit. Every exception is born with `resolution` `OPEN`. A `ProjectManager` later settles an open exception by supplying a `resolution` of `RESOLVED` or `WAIVED`. Open exceptions are a billing blocker: while any exception on any visit of the project remains `OPEN`, the project's invoice cannot be finalized, and the attempt is rejected with `ERR_OPEN_EXCEPTIONS` (HTTP 409).

### 3.5. Verification, Rejection, and the Rework Loop

A submitted visit awaits a `ProjectManager`'s verdict. Verification requires the visit's `verification_status` to be `PENDING_REVIEW`, the visit's assignment to be `SUBMITTED`, and at least one `BEFORE` photo and one `AFTER` photo on file; each failure is a state rejection with `ERR_INVALID_STATE`. On verification the visit's `verification_status` becomes `VERIFIED`, its `billable_amount_cents` is computed per §3.7, the assignment moves `SUBMITTED` to `VERIFIED`, the store row moves `IN_PROGRESS` to `COMPLETED` with its `version` incremented, and the project's `completed_store_count` — the count of store-list rows whose latest visit is `VERIFIED` — is recomputed. If every store-list row of the project has now reached a terminal outcome (`COMPLETED` or `DROPPED`) with at least one `COMPLETED`, the project cascades from `IN_FIELD` to `RECONCILING`, recomputes its `completed_store_count`, increments its `version` by 1, and auto-creates an `OPEN` invoice for the client and project if no live (`OPEN` or `FINALIZED`) invoice exists.

Rejection requires that the visit still be `PENDING_REVIEW` and its assignment still be `SUBMITTED`. On rejection the visit's `verification_status` becomes `REJECTED`, the assignment moves `SUBMITTED` to `REJECTED`, the store row moves `IN_PROGRESS` to `REWORK_REQUIRED` with its `version` incremented, the project's `rework_penalty_score` increases by 10 with `posture` re-derived per §2.9, and — critically — a rework authorization is auto-created in `REQUESTED` status, bound to the project, the store row, and the rejected visit, with its `reason` unset.

Rework is client-authorized. The auto-created authorization — or one a `ProjectManager` creates manually with `project_id`, `project_store_id`, `rejected_store_visit_id`, and a free-text `reason` (manual creation imposes no state preconditions: the named entities must exist and chain together per §2.5, but the visit need not be `REJECTED` and the store row need not be `REWORK_REQUIRED`) — sits in `REQUESTED` until the client acts. The acting client must own the project (its `id` must equal the project's `client_id`). Approval moves the authorization `REQUESTED` to `APPROVED`, but only while the project's `posture` is not `ESCALATED`; an escalated project forces rework through a manual project-manager path, and client self-approval is rejected with `ERR_POSTURE_ESCALATED` (HTTP 409). Denial moves the authorization `REQUESTED` to `DENIED` and adds 5 to the project's `rework_penalty_score`, re-deriving `posture`.

An `APPROVED` authorization is consumed by scheduling: creating an assignment with `rework_authorization_id` supplied requires the authorization to be `APPROVED` and the store row to be `REWORK_REQUIRED`, failing which the request is rejected with `ERR_REWORK_NOT_AUTHORIZED` (HTTP 409). Consumption flips the authorization to `CONSUMED`, creates the new assignment with `is_rework` true, moves the store row `REWORK_REQUIRED` to `ASSIGNED`, and records the new rep in `assigned_rep_id`. Authorizations also expire: whenever the logical clock's date advances past the store row's `due_date` while an authorization for that store is still `REQUESTED`, or still `APPROVED` but unconsumed, the authorization moves to `EXPIRED` and the project's `rework_penalty_score` increases by 7, with `posture` re-derived. This expiry sweep runs when the logical clock is advanced.

A store can be removed from play at any time before the project terminates. Dropping a store-list row is permitted while the row is `PENDING`, `ASSIGNED`, or `REWORK_REQUIRED`, provided the project is neither `COMPLETED` nor `CANCELLED`; dropping from `ASSIGNED` additionally requires that no assignment of the store is currently `ON_SITE`. The row lands in `DROPPED`, its `assigned_rep_id` is cleared, its `version` increments by 1, any of its assignments in `SCHEDULED` or `EN_ROUTE` are cancelled, and — on the rework path — any of its open authorizations in `REQUESTED` or `APPROVED` are moved to `EXPIRED` (without the +7 penalty, which applies only to clock-driven expiry). A drop is also a store-list mutation of the project: it increments the parent project's `version` by 1, and if the drop leaves every store-list row at a terminal outcome with at least one `COMPLETED` while the project is `IN_FIELD`, the project cascades to `RECONCILING` exactly as at verification time, auto-creating an `OPEN` invoice if none is live.

### 3.6. Fixture and Planogram Shipment Coordination

Fixture-install and reset projects depend on physical materials arriving before work begins. A `ProjectManager` registers a shipment against a project and destination store with a `carrier`, a `tracking_number`, and a `promised_date`. The shipment is born `LABEL_CREATED`.

Carrier scan events, recorded by a `ProjectManager` via a `scan_result`, advance the shipment through its lifecycle. The `scan_result` field takes exactly one of four values — `IN_TRANSIT`, `EXCEPTION`, `DELIVERED`, or `LOST` — and any other value is rejected with `ERR_INVALID_REQUEST`; a scan whose transition is not defined from the shipment's current state is a state rejection with `ERR_INVALID_STATE`. A scan marking the shipment in transit moves it from `LABEL_CREATED`, `IN_TRANSIT`, or `DELIVERY_EXCEPTION` to `IN_TRANSIT`. A scan recording a delivery exception moves it from `LABEL_CREATED` or `IN_TRANSIT` to `DELIVERY_EXCEPTION` and adds 3 to the project's `rework_penalty_score`. A scan recording delivery moves it from `IN_TRANSIT` or `DELIVERY_EXCEPTION` to `DELIVERED`; when the delivery date falls after the `promised_date`, the late delivery adds 5 to the project's `rework_penalty_score`. A scan declaring the shipment lost moves it from `IN_TRANSIT` to `LOST` and adds 8 to the project's `rework_penalty_score`. Every penalty event re-derives the project's `posture` per §2.9, and every scan increments the shipment's `version` by 1. `DELIVERED` and `LOST` are terminal.

These shipment states feed the fixture-delivery gate of §3.3: a `FIXTURE_INSTALL` project's reps may not depart toward, or check in at, a store whose required materials have not arrived.

### 3.7. Billing: Visit Amounts and Invoice Finalization

Client billing is computed per verified visit, under the billing model frozen at scoping. A rework visit bills at exactly 0 — `billable_amount_cents` is 0 whenever `is_rework` is true, and stays unset while the visit awaits review. Under `PER_STORE`, a verified non-rework visit bills the client's flat `per_store_rate_cents` regardless of how long the rep was on site. Under `HOURLY`, a verified non-rework visit bills the on-site time prorated against the negotiated rate: the visit's `on_site_minutes` multiplied by the client's `hourly_rate_cents`, divided by 60, rounded half-up to a whole cent. Two visits of different durations therefore bill different amounts under `HOURLY` but identical amounts under `PER_STORE`.

Invoices aggregate a project's verified work. A `BillingClerk` may create an `OPEN` invoice manually with `client_id`, `project_id`, and an optional `adjustment_cents` (defaulting to 0); the invoice's `line_total_cents` is computed at creation from currently verified visits. Manual creation imposes no project-state precondition — an invoice may be opened before the project reaches `RECONCILING`. Only one live invoice may exist per project — manual creation while an `OPEN` or `FINALIZED` invoice already exists for the project is rejected with `ERR_DUPLICATE_INVOICE` (HTTP 409). When the project cascades into `RECONCILING`, an `OPEN` invoice is auto-created if none exists, as described in §3.5. While an invoice is `OPEN`, any further visit verification on the project recomputes `line_total_cents`.

The line total is an exact integer sum: the `billable_amount_cents` of every visit of the project whose `verification_status` is `VERIFIED` — `REJECTED` and `PENDING_REVIEW` visits are excluded, and rework visits contribute their 0. Because each line was already rounded to whole cents at verification, the sum is never re-rounded.

Finalization is the project's closing act. A `BillingClerk` finalizes an `OPEN` invoice, which requires the project to be `RECONCILING` and no exception on any visit of the project to remain `OPEN` — the latter violation is rejected with `ERR_OPEN_EXCEPTIONS`. The finalize request must carry `expected_invoice_version` per §2.8, and may carry a signed `adjustment_cents` to be folded into the bill; if the finalize request omits `adjustment_cents`, the invoice's existing adjustment is retained. On finalization the invoice's `line_total_cents` is recomputed, its `grand_total_cents` — unset while the invoice is `OPEN` — is set to the line total plus the adjustment, the invoice moves to `FINALIZED`, the project cascades `RECONCILING` to `COMPLETED`, and both the invoice's and the project's versions increment. An `OPEN` invoice may instead be voided by a `BillingClerk`, moving it to `VOID`; `FINALIZED` and `VOID` are terminal.

### 3.8. Mileage and Travel-Time Pay

Field reps claim vehicle and travel costs per assignment. A `FieldRep` submits a mileage log naming the `rep_id` and `assignment_id`, with `round_trip_miles`, `home_to_first_stop_miles`, and `drive_minutes`, each at least 0. The assignment must belong to the claiming rep, and a log whose assignment has not yet reached `SUBMITTED` or `VERIFIED` is refused at submission as a state rejection with `ERR_INVALID_STATE`. The log is born `SUBMITTED`, with `mileage_pay_cents` and `travel_time_pay_cents` already computed per the rules below; approval later recomputes and freezes them.

Mileage pay has two variants, driven by the rep's `mileage_policy`. Under `HOME_BASED` — the standard W-2 commute-offset policy — the payable miles are the log's `round_trip_miles` minus twice the rep's `home_base_commute_miles` (the ordinary round-trip commute is never billable), floored at 0. Under `FIRST_STOP` — the common 1099 first-stop policy — the payable miles are the `round_trip_miles` minus only the `home_to_first_stop_miles` leg, floored at 0; all subsequent inter-store and return miles are payable. In either variant, `mileage_pay_cents` is the payable miles multiplied by the rep's `mileage_rate_cents`, an exact integer-cent figure requiring no rounding.

Travel-time pay is tiered, and it is always 0 for a `C1099` rep regardless of minutes driven. For a `W2` rep, the log's `drive_minutes` are split into three tiers: the first tier covers the initial 60 minutes; the second tier covers the next 60 minutes beyond the first hour; the third tier covers every minute beyond 120. The first tier is paid straight at the rep's `travel_minute_rate_cents` per minute. The second tier is paid at one and a quarter times that rate, with the tier's amount rounded half-up to a whole cent. The third tier is paid at one and a half times that rate, likewise rounded half-up to a whole cent. The travel-time pay is the sum of the three per-tier amounts — each tier rounded to whole cents before summing, never after. As concrete anchors: a 45-minute day pays only first-tier minutes; a 90-minute day pays 60 first-tier minutes plus 30 second-tier minutes at the uplifted rate; a 150-minute day pays 60 first-tier, 60 second-tier, and 30 third-tier minutes.

A `PayrollAdmin` adjudicates each `SUBMITTED` log. Approval requires the log to be `SUBMITTED` and the owning rep to still be `ACTIVE`; it recomputes `mileage_pay_cents` and `travel_time_pay_cents` and freezes them, moving the log to `APPROVED`. Rejection moves a `SUBMITTED` log to `REJECTED`. An approved log is eventually marked `PAID`. Both `PAID` and `REJECTED` are terminal, and each adjudication step increments the log's `version` by 1.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — a client, store, rep, project, project-store row, assignment, shipment, rework authorization, mileage log, invoice — or add new sub-resources to a collection — a photo, an exception report — return a `201 Created` status code; check-in also returns `201 Created` because it creates the store-visit resource. Operations that modify an existing resource — scoping, cancelling, dropping, departing, checking out, verifying, rejecting, approving, denying, scanning, resolving, paying, finalizing, voiding — return a `200 OK` status code. List endpoints scope visibility to the caller before any query-string filter is applied: a `Client` listing projects, project-store rows, store visits, rework authorizations, fixture shipments, or invoices sees only rows tied to its own projects (and only its own invoices), and a `FieldRep` listing assignments, mileage logs, or project-store rows sees only rows naming it as `rep_id` or `assigned_rep_id`. Single-resource reads and per-visit sub-lists enforce ownership through the parent chain: a `FieldRep` may read only its own rep record, its own assignments and mileage logs, and the visits, photos, and exceptions tied to its own assignments — while stores, project-store rows, and fixture shipments remain readable by any `FieldRep` — and a `Client` may read only its own client record and resources whose project belongs to it. List endpoints also honor exact-match query-string filters on top of pagination: clients by `status`; reps by `employment_type` and `status`; projects by `client_id`, `status`, and `posture`; project-store rows by `project_id`, `store_id`, `status`, and `assigned_rep_id` (the per-project sub-list filters by `status`); assignments by `project_id`, `rep_id`, `project_store_id`, `status`, and `is_rework`; store visits by `assignment_id`, `verification_status`, and `is_rework`; photos by `photo_type`; exceptions by `resolution`; rework authorizations by `project_id`, `project_store_id`, `rejected_store_visit_id`, and `status`; fixture shipments by `project_id`, `project_store_id`, and `status`; mileage logs by `rep_id`, `assignment_id`, and `status` (the per-rep sub-list filters by `status`); and invoices by `client_id`, `project_id`, and `status` (the per-client sub-list filters by `status`). The store list accepts no filters.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/retail-reset/clients` | Create a client organization | ProjectManager |
| GET | `/retail-reset/clients` | List clients with pagination | ProjectManager, BillingClerk, PayrollAdmin |
| GET | `/retail-reset/clients/{id}` | Get a client | ProjectManager, BillingClerk, PayrollAdmin, Client |
| POST | `/retail-reset/stores` | Create a store | ProjectManager |
| GET | `/retail-reset/stores` | List stores with pagination | ProjectManager, FieldRep |
| GET | `/retail-reset/stores/{id}` | Get a store | ProjectManager, FieldRep, Client |
| POST | `/retail-reset/reps` | Create a field rep (W2 or C1099) | PayrollAdmin |
| GET | `/retail-reset/reps` | List field reps | ProjectManager, PayrollAdmin |
| GET | `/retail-reset/reps/{id}` | Get a field rep | ProjectManager, PayrollAdmin, FieldRep |
| POST | `/retail-reset/projects` | Create a project under a client | ProjectManager |
| GET | `/retail-reset/projects` | List projects | ProjectManager, BillingClerk, Client |
| GET | `/retail-reset/projects/{id}` | Get a project (includes computed posture, rework_penalty_score, completed_store_count) | ProjectManager, BillingClerk, Client, PayrollAdmin |
| POST | `/retail-reset/projects/{id}/scope` | Scope the project: freeze effective_billing_model; OCC-guarded by expected_project_version | ProjectManager |
| POST | `/retail-reset/projects/{id}/cancel` | Cancel a project; cascades to ProjectStore and Assignment rows | ProjectManager |
| POST | `/retail-reset/project-stores` | Add a store to a project's store list | ProjectManager |
| GET | `/retail-reset/project-stores` | List project-store rows; filterable | ProjectManager, Client, FieldRep |
| GET | `/retail-reset/project-stores/{id}` | Get a project-store row | ProjectManager, Client, FieldRep |
| POST | `/retail-reset/project-stores/{id}/drop` | Drop a store from the project list | ProjectManager |
| GET | `/retail-reset/projects/{id}/project-stores` | List store-list rows of a project (sub-resource reverse reachability) | ProjectManager, Client, FieldRep |
| POST | `/retail-reset/assignments` | Schedule a rep to a project store; with rework_authorization_id creates a rework visit | ProjectManager |
| GET | `/retail-reset/assignments` | List assignments | ProjectManager, FieldRep, PayrollAdmin |
| GET | `/retail-reset/assignments/{id}` | Get an assignment | ProjectManager, FieldRep, PayrollAdmin, Client |
| POST | `/retail-reset/assignments/{id}/depart` | Mark the rep en route to the store | FieldRep |
| POST | `/retail-reset/assignments/{id}/check-in` | Check in on site; creates the StoreVisit | FieldRep |
| POST | `/retail-reset/assignments/{id}/check-out` | Check out; computes on_site_minutes; requires BEFORE+AFTER photos already uploaded | FieldRep |
| POST | `/retail-reset/assignments/{id}/cancel` | Cancel a non-terminal assignment | ProjectManager |
| GET | `/retail-reset/store-visits` | List store visits | ProjectManager, Client, BillingClerk |
| GET | `/retail-reset/store-visits/{id}` | Get a store visit | ProjectManager, Client, BillingClerk, FieldRep |
| GET | `/retail-reset/assignments/{id}/store-visits` | List store visits of an assignment (sub-resource reverse reachability) | ProjectManager, Client, FieldRep |
| POST | `/retail-reset/store-visits/{id}/photos` | Upload photo evidence for a visit | FieldRep |
| GET | `/retail-reset/store-visits/{id}/photos` | List photo evidence of a visit | ProjectManager, Client, FieldRep |
| POST | `/retail-reset/store-visits/{id}/exceptions` | File an exception report (out-of-stock, void, etc.) against a visit | FieldRep, ProjectManager |
| GET | `/retail-reset/store-visits/{id}/exceptions` | List exception reports of a visit | ProjectManager, Client, FieldRep, BillingClerk |
| POST | `/retail-reset/exceptions/{id}/resolve` | Resolve or waive an open exception | ProjectManager |
| GET | `/retail-reset/exceptions/{id}` | Get an exception report | ProjectManager, Client, FieldRep, BillingClerk |
| POST | `/retail-reset/store-visits/{id}/verify` | Verify a submitted visit; computes billable_amount_cents; cascades project store completion and possibly project RECONCILING | ProjectManager |
| POST | `/retail-reset/store-visits/{id}/reject` | Reject a submitted visit; cascades rework penalty and creates ReworkAuthorization | ProjectManager |
| POST | `/retail-reset/rework-authorizations` | Manually create a rework authorization (alternative to auto-creation on reject) | ProjectManager |
| GET | `/retail-reset/rework-authorizations` | List rework authorizations | ProjectManager, Client |
| GET | `/retail-reset/rework-authorizations/{id}` | Get a rework authorization | ProjectManager, Client |
| POST | `/retail-reset/rework-authorizations/{id}/approve` | Client approves rework; blocked while the project's posture is ESCALATED | Client |
| POST | `/retail-reset/rework-authorizations/{id}/deny` | Client denies rework; adds penalty | Client |
| POST | `/retail-reset/fixture-shipments` | Register a fixture/POG shipment to a project store | ProjectManager |
| GET | `/retail-reset/fixture-shipments` | List fixture shipments | ProjectManager, Client, FieldRep |
| GET | `/retail-reset/fixture-shipments/{id}` | Get a fixture shipment | ProjectManager, Client, FieldRep |
| POST | `/retail-reset/fixture-shipments/{id}/scan` | Record a carrier scan event advancing the shipment state | ProjectManager |
| POST | `/retail-reset/mileage-logs` | Submit a mileage/travel claim for an assignment | FieldRep |
| GET | `/retail-reset/mileage-logs` | List mileage logs | PayrollAdmin, ProjectManager, FieldRep |
| GET | `/retail-reset/mileage-logs/{id}` | Get a mileage log | PayrollAdmin, ProjectManager, FieldRep |
| GET | `/retail-reset/reps/{id}/mileage-logs` | List mileage logs of a rep (sub-resource reverse reachability) | PayrollAdmin, ProjectManager, FieldRep |
| POST | `/retail-reset/mileage-logs/{id}/approve` | Approve a mileage claim; recomputes and freezes pay amounts | PayrollAdmin |
| POST | `/retail-reset/mileage-logs/{id}/reject` | Reject a mileage claim | PayrollAdmin |
| POST | `/retail-reset/mileage-logs/{id}/pay` | Mark an approved mileage claim paid | PayrollAdmin |
| POST | `/retail-reset/invoices` | Manually create an OPEN invoice for a project (auto-created on RECONCILING if absent) | BillingClerk |
| GET | `/retail-reset/invoices` | List invoices | BillingClerk, ProjectManager, Client |
| GET | `/retail-reset/invoices/{id}` | Get an invoice | BillingClerk, ProjectManager, Client |
| GET | `/retail-reset/clients/{id}/invoices` | List invoices of a client (sub-resource reverse reachability) | BillingClerk, ProjectManager, Client |
| POST | `/retail-reset/invoices/{id}/finalize` | Finalize an OPEN invoice; OCC-guarded by expected_invoice_version; cascades project RECONCILING to COMPLETED | BillingClerk |
| POST | `/retail-reset/invoices/{id}/void` | Void an OPEN invoice | BillingClerk |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the server's logical clock. Before any call, the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. | ProjectManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_TEMPORAL_INVALID` | 422 |
| `ERR_CROSS_ENTITY_MISMATCH` | 422 |
| `ERR_REP_DOUBLE_BOOKED` | 409 |
| `ERR_DUPLICATE_STORE` | 409 |
| `ERR_FIXTURES_NOT_DELIVERED` | 409 |
| `ERR_BILLING_MODEL_UNRESOLVABLE` | 422 |
| `ERR_OPEN_EXCEPTIONS` | 409 |
| `ERR_CLASSIFICATION_FORBIDDEN` | 422 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_STALE_INVOICE_VERSION` | 412 |
| `ERR_REWORK_NOT_AUTHORIZED` | 409 |
| `ERR_DUPLICATE_INVOICE` | 409 |
| `ERR_POSTURE_ESCALATED` | 409 |
| `ERR_INTERNAL` | 500 |
