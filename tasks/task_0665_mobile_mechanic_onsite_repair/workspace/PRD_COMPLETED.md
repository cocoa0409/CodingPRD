# Mobile Mechanic & On-Site Auto Repair API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Mobile Mechanic & On-Site Auto Repair API, a platform in the spirit of services such as YourMechanic and Wrench. The system coordinates the full journey of an automotive repair that begins not in a shop but at the vehicle's own location: a customer describes a symptom, a mechanic diagnoses and quotes the work, a dispatcher assigns a qualified mechanic within the correct territory, and the repair is carried out either on-site in the field or after towing the vehicle back to a partner shop. Along the way the platform sources parts at a tiered markup, captures on-site inspection findings that the customer must approve before any extra work proceeds, settles payment either by card or against a fleet credit ledger, and honours a warranty window during which a free callback visit can be scheduled.

The central tension the platform manages is that a job's true cost is rarely known at the moment a customer agrees to the work. A quote is a forward-looking estimate built from anticipated labour hours and estimated parts; the final bill is reconstructed at completion from the hours actually logged, the parts actually installed, and any add-ons the customer approved mid-job. The platform must keep these two figures distinct, must let fleet customers operate against a credit limit that is checked both when work is approved and again before the invoice is cut, and must keep the work dimension of a visit (driving, working, finishing) cleanly separated from the money dimension (invoiced, settled, refunded). Five user roles — customers, mechanics, dispatchers, fleet managers, and platform administrators — each see a different slice of this lifecycle, and the API enforces both who may act and, for owner-scoped resources, on which records they may act.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity in which they are acting. Both headers must be present and well-formed on every request — including the catalog-part seeding endpoint and the logical-clock endpoint, which still require valid headers even though they are administrative. A request missing or malformed in either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognises exactly five roles: `Customer`, `Mechanic`, `Dispatcher`, `FleetManager`, and `PlatformAdmin`. Their identities relate to persisted records as follows:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` (for example a `ServiceRequest` through its `customer_id`) compare that foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Mechanic`, `X-User-ID` is the `id` of the acting `Mechanic`; ownership checks on any resource that references a `Mechanic` (for example a `JobVisit` through its `mechanic_id`) compare that foreign-key field to `X-User-ID`.
- When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of the acting `FleetAccount`; ownership checks on any resource that references a `FleetAccount` (for example a `Payment` through its `fleet_account_id`) compare that foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is used for seeding and clock operations and is not compared to any entity's `id`.

When an entity-backed user (a `Customer`, `Mechanic`, or `FleetManager`) targets a resource that they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Concretely, a `Customer` may act only on their own `ServiceRequest` records and their descendants, a `Mechanic` may drive only their own `JobVisit` records, and a `FleetManager` may settle only `Payment` records routed to a `FleetAccount` they own.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is drawn from the server's wall clock at the moment the response is built, independently of the logical clock that drives resource timestamps.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. When a single operation mutates several resources, the data field carries the primary resource the action is named for: sending a quote returns the new quote, approving/rejecting/requesting-revision-on a quote returns that quote, dispatching returns the newly created job visit, recording a finding returns that finding, resolving add-ons returns the service request, departing/starting-work/finishing/aborting a visit returns that job visit, settling/refunding returns that payment, and filing or acting on a warranty claim returns that claim. The logical-clock endpoint returns an empty object.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Out-of-range or non-integer pagination values are not rejected: a `limit` below 1 is clamped up to 1, a `limit` above 100 is clamped down to 100, a negative `offset` is clamped up to 0, and any value that cannot be parsed as an integer falls back to its default (10 for `limit`, 0 for `offset`).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created. It is stamped from the logical clock (§3.1), not the server's wall clock.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified, likewise read from the logical clock. It is refreshed on every change to the resource.
- `version` — an integer that begins at its initial value and increments by one with every mutation of the resource. It is the basis for optimistic concurrency control (see §2.11).

The `CatalogPart` resource is the sole exception: it is immutable after creation and therefore carries only `id` and `created_at`. It has neither an `updated_at` field nor a `version` field. Every other resource — `Customer`, `FleetAccount`, `Mechanic`, `ServiceRequest`, `Quote`, `JobVisit`, `PartLine`, `InspectionFinding`, `Payment`, and `WarrantyClaim` — carries the full set above.

### 2.5. Nested Resource Retrieval and Path Validation

Many endpoints address a resource by an identifier in the URL path, and several address resources through a parent path segment (for example, the part-lines, inspection-findings, quotes, payments, and warranty-claims collections hang beneath a specific service request). For any such request, identifiers are validated left to right: the system confirms the existence of the first path identifier before the second, and so on. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The same rule covers foreign-key references carried in a request body: if a body field names a `customer_id`, `mechanic_id`, `catalog_part_id`, `job_visit_id`, `recommended_part_id`, `service_request_id`, or `fleet_account_id` that does not resolve, the request is rejected with `ERR_NOT_FOUND`.

### 2.6. Service Zones and Territory

The platform divides its service area into nine declared zones identified by the codes `Z1`, `Z2`, `Z3`, `Z4`, `Z5`, `Z6`, `Z7`, `Z8`, and `Z9`. Each customer's `home_zone_code` and each mechanic's `zone_code` must be one of these nine codes. A service request inherits its `zone_code` from the customer at the moment it is created, and that zone is what dispatch must match: a mechanic can only be dispatched to a request whose zone equals the mechanic's territory. This territory matching is one of the dispatch safety constraints described in §3.4.

### 2.7. Precision, Rounding, and Monetary Representation

All monetary amounts are held as integer cents; the API exposes them as integers. Wherever a calculation produces a fractional cent — labour cost from hours multiplied by an hourly rate, a parts markup, or a fleet discount applied to a labour subtotal — the result is rounded to a whole number of cents using the round-half-up convention (a value whose fractional part is exactly one half rounds up to the next whole cent). The specific points at which rounding is applied, and the order in which sums and rounding interleave, are described with each calculation in §3; the governing rule everywhere is round-half-up to whole cents.

### 2.8. Hierarchical Consistency and Cascading Side Effects

A single operation in this system frequently mutates more than one resource, and the platform applies every such cascade immediately and atomically. When a job visit advances the work, it can also drive the parent service request forward; when a job is finished it simultaneously closes the visit, finalises the request's total, installs parts, opens a payment, and may debit a fleet ledger. Whenever a resource is mutated as part of such a cascade — whether directly or as a downstream effect — its `updated_at` is refreshed and its `version` is incremented by one. The detailed cascades are specified alongside the workflows that trigger them in §3; the principle here is that no secondary effect is optional, and each affected resource records its own version bump.

Compensation is the mirror image of cascade. Aborting a scheduled or en-route visit not only terminates that visit but also unwinds the dispatch that created it, returning the service request to a re-dispatchable state and clearing the routing choice. Refunding or settling a fleet-billed payment credits the fleet ledger to undo or balance the debit that the invoice created. These compensating mutations likewise bump the `version` and refresh `updated_at` of every resource they touch.

### 2.9. The Fleet Credit Ledger

A `FleetAccount` carries a running `outstanding_balance_cents` that is the single source of truth for how much unpaid work the fleet is currently carrying. It is a derived ledger field that starts at zero when the account is created. It is debited — increased — when a fleet-billed job is invoiced, and it is credited — decreased — when such a payment is settled or refunded. The ledger invariant is that at any moment the outstanding balance equals the sum of the `total_due_cents` of all that fleet's payments still in `INVOICED` status. Every debit at invoice time and every credit at settlement or refund time conserves this invariant, which is why settlement and refund each subtract exactly the amount the invoice originally added. The credit ledger constrains new work through the headroom check described in §3.7; a `SUSPENDED` fleet account additionally blocks new fleet-billed approvals and settlements as described in §3.3 and §3.8.

### 2.10. Validation Ordering

When an endpoint is guarded by several checks, they are evaluated in a fixed priority order so that the rejection a client receives is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorisation (`ERR_FORBIDDEN_ROLE`), then existence of every path identifier and body foreign key (`ERR_NOT_FOUND`), then resource ownership for entity-backed users (`ERR_NOT_RESOURCE_OWNER`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), and only then the structural validity of the request body (`ERR_INVALID_REQUEST`). Domain-specific business rules — zone matching, skill tier, scheduling overlap, warranty window, fleet credit, fleet suspension, optimistic-concurrency version, add-on resolution — are evaluated after these foundational checks. Where a single endpoint carries several of these domain rules, their relative ordering is called out in the workflow that owns them in §3 so that an earlier, more fundamental failure is never masked by a later check.

### 2.11. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control because both act on a `ServiceRequest` whose `version` may have advanced after the actor last read it. In each case the request body must carry `expected_service_request_version`, a non-optional integer holding the version of the target service request that the client last observed. Before the operation proceeds, the server compares that value against the service request's current `version`; if they differ, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no change is made.

The first guarded operation is quote approval. Because sending a replacement quote bumps the service request's version (superseding the prior quote), a client that read the request before a revision was sent holds a stale view; an approval carrying that old version is rejected on the stale-version check rather than on a state precondition, so that the newer, legitimate quote can still be approved on a fresh read. The second guarded operation is dispatch. A dispatch attempt carrying a service-request version older than the request's current `version` is rejected on stale version, leaving the dispatcher free to retry against the current request. In both operations the stale-version check is evaluated after the other domain-specific business rules of that operation — for quote approval after the fleet headroom and fleet-suspension checks, and for dispatch after the zone, skill-tier, and visit-overlap checks — so an earlier zone, skill, overlap, credit, or suspension failure takes precedence over a stale version. Endpoints other than these two do not take a version field and are not subject to this check.

## 3. Business Logic & Workflows

### 3.1. Seeding the Platform: Catalog, Fleets, Customers, and Mechanics

Before any repair can be priced, a `PlatformAdmin` seeds the reference data. A catalog part is defined by a unique, non-empty `sku`, a display `name`, and a `wholesale_cost_cents` that must be strictly greater than zero. Catalog parts are immutable reference records; once created they are never modified. The administrator also defines fleet accounts, each created in `ACTIVE` status with `company_name`, a `credit_limit_cents` of at least zero representing the maximum outstanding balance the fleet may carry, and a `labor_discount_pct` that is a fraction between 0 and 0.40 inclusive applied to labour subtotals for that fleet's requests. A fleet account begins with `outstanding_balance_cents` of zero. An administrator may later suspend a fleet account, moving its `status` to `SUSPENDED`, which bumps the account's version; suspension blocks new fleet-billed approvals and settlements but is otherwise independent of work already invoiced.

Customers are registered by the administrator with a login `email` that is stored lowercased and must be unique on a case-insensitive basis and non-empty, a `full_name`, and a `home_zone_code` drawn from the nine declared zones. A customer may optionally be tied to a fleet through `fleet_account_id`; when set, that customer's requests bill to the fleet ledger and earn the fleet labour discount, and when omitted it defaults to null for an ordinary retail customer. Every customer begins in `ACTIVE` status, the alternative being `SUSPENDED`. Mechanics are created with a `full_name`, a `zone_code` territory drawn from the nine zones, a `skill_tier`, and a `labor_rate_cents_per_hour` that must be strictly greater than zero. The skill tier is one of `TIER1`, `TIER2`, or `TIER3`: `TIER1` handles diagnostics and light repair, `TIER2` adds complex repair, and `TIER3` additionally is the only tier qualified to coordinate a tow-to-shop job. A mechanic begins `AVAILABLE`, the alternative status being `OFF_DUTY`.

The platform's notion of "now" is a logical clock rather than wall-clock time. At server startup the clock reads `2026-04-01T00:00:00Z`, and an administrator may advance or reset it to any supplied instant by providing a `to_iso8601` value; the clock never falls back to wall-clock time. Every warranty filing timestamp and every warranty-window comparison reads this logical clock.

### 3.2. Intake and the Quote Conversation

A customer opens the engagement by filing a service request, supplying their own `customer_id`, the vehicle's `vehicle_vin` which must be exactly 17 characters long, a free-text `symptom_text`, and an optional `severity`. Severity is one of `ROUTINE`, `URGENT`, or `EMERGENCY` and defaults to `ROUTINE`; it is recorded on the request as an advisory priority signal but does not by itself drive any automated mechanic selection or list ordering, since dispatch targets a mechanic the dispatcher names explicitly. At creation the request enters `INTAKE` status, its `zone_code` is copied from the customer's `home_zone_code`, and its `fleet_account_id` is snapshotted from the customer's `fleet_account_id` (null for a retail customer). The request's `routing_mode` is null until dispatch, and both `estimate_total_cents` and `final_total_cents` are null until they are computed.

A mechanic responds by sending a quote against the request. The quote send carries a `diagnosis_text` summary, an `estimated_labor_hours` value that must be strictly greater than zero, an `estimated_parts_cents` figure of at least zero representing parts cost already marked up, a `labor_rate_cents_per_hour` snapshot that must be strictly greater than zero, and an optional `tow_fee_cents` of at least zero that defaults to zero and is non-zero only when the job would be towed to a shop. Sending the first quote is permitted only when the service request is in `INTAKE` and the owning customer is `ACTIVE`; it creates a `Quote` in `SENT` status with its `quoted_total_cents` computed as described in §3.3, advances the request from `INTAKE` to `QUOTED`, and increments the request's `version`. A `Quote` is born internally in `DRAFT` and is published as `SENT` by the send action.

From `SENT`, the customer has three moves. They may approve the quote, they may reject it — which moves only that quote from `SENT` to `REJECTED` and bumps the quote's version while leaving the request in `QUOTED` — or they may request a revision. Requesting a revision is allowed only while the quote is `SENT` and the request is `QUOTED`; it moves the quote from `SENT` to `REVISION_REQUESTED` and bumps the quote's version, while the request stays in `QUOTED`. The mechanic then sends a replacement quote: sending a quote while the request is `QUOTED` and the prior quote sits in `REVISION_REQUESTED` supersedes that prior quote (moving it from `REVISION_REQUESTED` to `SUPERSEDED` and bumping its version), publishes the new quote in `SENT`, and increments the request's `version`. This revision loop may cycle `SENT → REVISION_REQUESTED → SENT` any number of rounds while the request remains in `QUOTED`. Any attempt to drive a quote or request from a state where the move is undefined is rejected with `ERR_INVALID_STATE`.

Approving a quote is the pivotal transition. It is permitted only when the request is in `QUOTED`, the target quote is in `SENT`, and — if the request carries a `fleet_account_id` — the referenced fleet account is `ACTIVE`. The approval carries `expected_service_request_version` for the optimistic-concurrency check of §2.11; an approval whose declared version does not match the request's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). For a fleet-billed request the fleet headroom check of §3.7 runs at this point using the estimate, and if the fleet account is suspended the approval is rejected with `ERR_FLEET_ACCOUNT_SUSPENDED` (HTTP 409). On success the quote moves `SENT → APPROVED` and its input fields are frozen (version-pinned) so the approved figures cannot later shift, the request copies the quote's `quoted_total_cents` into its own `estimate_total_cents`, the request advances `QUOTED → APPROVED`, and the request's `version` is incremented.

A customer may abandon a request before any mechanic has been dispatched. Cancellation is permitted only while the request is in `INTAKE`, `QUOTED`, or `APPROVED`. Cancelling moves any quote currently in `SENT` or `REVISION_REQUESTED` to `SUPERSEDED`, moves the request to `CANCELLED`, and increments the request's `version`. `CANCELLED` and `COMPLETED` are the two terminal states of a service request.

### 3.3. Pricing the Estimate

The provisional grand total stored on a quote, and later copied onto the request at approval, is built strictly from the quote's own input fields — never from any hours actually logged or any part lines actually sourced. First the labour figure is computed as the estimated labour hours multiplied by the quoted labour rate per hour, rounded half-up to whole cents. If the service request carries a fleet account, that labour figure is then multiplied by one minus the fleet account's `labor_discount_pct` and rounded half-up to whole cents; for a retail request the labour figure is used unchanged. The grand total is then the discounted (or undiscounted) labour figure plus the estimated parts cents plus the tow fee cents, each of the latter two added as-is without further rounding. This is the value stored as `quoted_total_cents` when the quote is sent and copied into `estimate_total_cents` when the quote is approved.

This estimate is deliberately distinct from the final bill. The estimate looks forward from estimated hours and estimated parts; the final total, described in §3.6, looks backward at the hours actually logged and the part lines actually installed, so the two figures generally diverge. The platform preserves both: the estimate as a promise made at approval, the final as the amount actually invoiced.

### 3.4. Dispatch and the On-Site / Tow-to-Shop Fork

Once a request is `APPROVED`, a dispatcher assigns a mechanic and chooses how the work will be delivered. The dispatch carries the `mechanic_id` of the chosen mechanic, a `routing_mode` of either `ON_SITE` or `TOW_TO_SHOP`, a planned `scheduled_start_utc` and `scheduled_end_utc` for the visit (the end must be strictly after the start), and `expected_service_request_version` for the optimistic-concurrency guard. A dispatch whose declared version does not match the request's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Dispatch is the most heavily guarded operation in the system, and its domain checks run in a definite order after the foundational checks of §2.10. The request must be in `APPROVED` status and the selected mechanic must be `AVAILABLE`, else the move is rejected as an invalid state. Next, the mechanic's `zone_code` must equal the request's `zone_code`; a territory mismatch is rejected with `ERR_ZONE_MISMATCH` (HTTP 409). Then, when the chosen routing is `TOW_TO_SHOP`, the mechanic's `skill_tier` must be exactly `TIER3`, since only that tier coordinates tows; a lesser tier is rejected with `ERR_INSUFFICIENT_SKILL_TIER` (HTTP 409). Finally, when the chosen routing is `ON_SITE`, the proposed visit interval must not overlap any existing non-terminal on-site visit already booked for that same mechanic. The interval is treated as half-open, spanning from the start instant up to but not including the end instant, so two visits that merely touch at a boundary do not conflict; a genuine overlap is rejected with `ERR_VISIT_OVERLAP` (HTTP 409).

On success the dispatch creates a `JobVisit` in `SCHEDULED` status bound to the selected mechanic, recording the visit's own `service_request_id`, `mechanic_id`, `scheduled_start_utc`, `scheduled_end_utc`, and `routing_mode`. The chosen routing is copied onto the request's `routing_mode`, the request advances `APPROVED → DISPATCHED`, and the request's `version` is incremented. This is the branch point of the whole workflow: an `ON_SITE` visit and a `TOW_TO_SHOP` visit diverge in their next steps but converge again at finish.

### 3.5. Driving the Visit: the Work Dimension

The job visit carries its own lifecycle in its `visit_status`, the work dimension, which runs independently of the money dimension carried by the eventual payment. A freshly dispatched visit is `SCHEDULED`. The assigned mechanic departs, which is permitted only while the visit is `SCHEDULED` and the mechanic is `AVAILABLE`; departing moves the visit `SCHEDULED → EN_ROUTE` and bumps the visit's version. From `EN_ROUTE` the mechanic starts work, and here the routing fork shows itself in the state machine: starting an `ON_SITE` visit moves it `EN_ROUTE → ON_SITE_WORKING`, while starting a `TOW_TO_SHOP` visit moves it `EN_ROUTE → AT_SHOP`. In both cases starting work also drives the parent request `DISPATCHED → IN_PROGRESS`, and both the visit's and the request's versions are incremented. Starting work is permitted only from `EN_ROUTE` and only when the visit's recorded `routing_mode` matches the branch being taken.

While work is in progress the mechanic may source parts and record inspection findings as described in §3.6. The visit ultimately reaches `FINISHED` through the finish action of §3.6, which is the only path from `ON_SITE_WORKING` or `AT_SHOP` to `FINISHED`. The two terminal states of a visit are `FINISHED` and `ABORTED`.

A dispatcher may abort a visit that has not yet begun working — that is, while it is `SCHEDULED` or `EN_ROUTE`. Aborting moves the visit to `ABORTED`, and as a compensation it unwinds the dispatch: the parent request reverts `DISPATCHED → APPROVED` so it can be dispatched afresh, and the request's `routing_mode` is reset to null. Both the visit's and the request's versions are incremented. A `logged_labor_hours` value is recorded on the visit only at finish time; until then it is null, and when set it must be at least zero.

### 3.6. Parts, Inspection Findings, and Add-On Approval

A mechanic sources parts for a request by naming a `catalog_part_id` and a `quantity` that must be strictly greater than zero. Sourcing creates a `PartLine` in `SOURCED` status whose `service_request_id` ties it to the request, snapshots the catalog part's wholesale cost into the line's `unit_cost_cents`, and computes the line's `unit_price_cents` and `line_total_cents` through the parts markup of §3.9. A directly sourced part is not an add-on, so its `is_addon` flag is false. A part line's lifecycle is `SOURCED`, then `INSTALLED` at finish, with `VOIDED` as the alternative terminal disposition.

On-site, a mechanic frequently discovers extra work, which is captured as an inspection finding. Recording a finding carries the `job_visit_id` of the visit during which it was observed, a `description`, an optional `recommended_part_id` naming a catalog part for the add-on repair, an optional `recommended_quantity` of at least zero defaulting to zero, and an optional `add_on_labor_hours` of at least zero defaulting to zero. A finding is created in `PROPOSED` status. Recording a finding is permitted only while the request is `IN_PROGRESS`, and the first proposed finding drives the request `IN_PROGRESS → AWAITING_ADDON_APPROVAL`, incrementing the request's `version`; this signals that the customer must now decide on the proposed add-ons before the job can finish. A finding's lifecycle is `PROPOSED`, then either `APPROVED` or `DECLINED`.

The customer resolves the add-ons in a single call carrying a `decisions` list. The decisions must cover exactly the findings currently in `PROPOSED`: no proposed finding may be omitted, and no decision may reference a finding that is not currently proposed or that belongs to another request. A decisions list that fails this exact-cover rule is rejected with `ERR_VALIDATION_PENDING` (HTTP 422). Resolving is permitted only while the request is in `AWAITING_ADDON_APPROVAL`, and the call must leave no finding for the request still in `PROPOSED`. Each finding is moved to `APPROVED` or `DECLINED` according to its decision; every approved finding that names a recommended part spawns a new `PartLine` with `is_addon` set to true, in `SOURCED` status, priced through the parts markup of §3.9, and contributes its `add_on_labor_hours` to the visit's add-on labour accumulator that feeds the final total. When no proposed findings remain, the request returns `AWAITING_ADDON_APPROVAL → IN_PROGRESS` and the request's `version` is incremented.

Finishing the visit is the mechanic's closing action and the moment the final bill is struck. The finish carries the `logged_labor_hours` actually worked and the `payment_method` for the invoice. It is permitted only when the request is `IN_PROGRESS`, when no inspection finding for the request remains in `PROPOSED` — an unresolved add-on is rejected with `ERR_ADDONS_UNRESOLVED` (HTTP 409) — and when `logged_labor_hours` has been provided. Finishing computes the request's `final_total_cents` through the final-total calculation of §3.6's companion in §3.10, moves every `SOURCED` part line for the request to `INSTALLED`, moves the visit `ON_SITE_WORKING → FINISHED` or `AT_SHOP → FINISHED` (which in turn drives the request `IN_PROGRESS → COMPLETED`), and creates a `Payment` in `INVOICED` status whose `total_due_cents` is copied from the request's `final_total_cents` and whose `method` is the supplied payment method, one of `CARD` or `FLEET_CREDIT`. For a fleet-billed request the headroom check of §3.7 is re-run at this point using the final figure before the ledger debit, and on success the payment's `fleet_account_id` is snapshotted from the request and the fleet account's `outstanding_balance_cents` is increased by the payment's `total_due_cents`. The visit's and the request's versions are both incremented. The payment's `status` lifecycle of `INVOICED → SETTLED` or `INVOICED → REFUNDED` runs in parallel to the visit's work dimension.

### 3.7. Fleet Credit Headroom

A fleet-billed request may only proceed when the fleet's projected outstanding balance after taking on the new charge would not exceed the fleet account's credit limit. The projected balance is the fleet account's current `outstanding_balance_cents` plus the charge being projected. The boundary is inclusive: a projected balance exactly equal to `credit_limit_cents` passes, while a projected balance of even one cent more fails. A failure is rejected with `ERR_FLEET_CREDIT_EXCEEDED` (HTTP 402).

This headroom check is applied at two distinct moments with two distinct projected charges. At quote approval the projected charge is the request's `estimate_total_cents`. At job finish, immediately before the ledger debit, the projected charge is the request's `final_total_cents`. Because the final total may exceed the estimate, a request that cleared the headroom check at approval can still fail it at finish.

### 3.8. Payment Settlement, Refund, and Warranty Callbacks

A payment is settled to close out its money dimension. Settlement is permitted only while the payment is `INVOICED`, and when the settlement method is `FLEET_CREDIT` the acting fleet manager must own the fleet account the payment is routed to. A fleet-billed settlement attempted while that fleet account is `SUSPENDED` is rejected with `ERR_FLEET_ACCOUNT_SUSPENDED` (HTTP 409). On success the payment moves `INVOICED → SETTLED`, and if the payment carries a fleet account the fleet's `outstanding_balance_cents` is decreased by the payment's `total_due_cents`, conserving the ledger invariant. The payment's version is incremented. A dispatcher may instead refund an invoiced payment, moving it `INVOICED → REFUNDED`; if the payment is fleet-billed the fleet ledger is likewise credited by `total_due_cents` to compensate the original invoice debit, and the payment's version is incremented. `REFUNDED` is the terminal state of a payment.

After a request reaches `COMPLETED`, the customer may file a warranty claim describing the recurring fault. Filing carries a `reason_text`; the claim is created in `UNDER_REVIEW` status with its `filed_at_utc` stamped from the logical clock. A claim's lifecycle supports a revision loop: a dispatcher may move it `UNDER_REVIEW → INFO_REQUESTED`, and the customer may then supply the requested information to move it back `INFO_REQUESTED → UNDER_REVIEW`, and this cycle may repeat any number of rounds. From `UNDER_REVIEW` a dispatcher may deny the claim, moving it to `DENIED`, or approve it. `APPROVED` and `DENIED` are the two terminal states.

Approving a warranty claim is the only action that produces a free callback. Approval carries a `mechanic_id`, a `scheduled_start_utc`, and a `scheduled_end_utc` for the callback visit. It is permitted only while the claim is `UNDER_REVIEW`, only when the referenced service request is `COMPLETED`, and only when the claim was filed within the warranty window of the request's completion: the elapsed time from the request's completion to the claim's `filed_at_utc` must be no more than thirty days. The request's completion instant for this comparison is the request's `updated_at` as it stands when the claim is approved (the logical-clock moment at which the request reached `COMPLETED`), and only the upper bound is enforced — a `filed_at_utc` at or before that completion instant is within the window. A claim filed beyond that window is rejected with `ERR_WARRANTY_WINDOW_EXPIRED` (HTTP 409). The callback slot is also protected against double-booking with a buffer: the proposed callback interval, extended by thirty minutes on each side, must not overlap any existing non-terminal visit for the same mechanic; a buffered conflict is rejected with `ERR_CALLBACK_SLOT_CONFLICT` (HTTP 409). On success the system creates a free callback `JobVisit` in `SCHEDULED` status with `ON_SITE` routing for the same mechanic and zone, records that visit's identifier in the claim's `callback_visit_id`, moves the claim to `APPROVED`, and increments the claim's `version`.

### 3.9. The Tiered Parts Markup

Every part line — whether sourced directly or spawned from an approved add-on finding — is priced by marking up the wholesale unit cost through a marginal, banded scheme. The markup is computed per single unit and then multiplied by the quantity; the per-unit markup is rounded before the multiplication, never after. The wholesale unit cost is divided into three bands. The first band covers the portion of the unit cost from zero up to and including 5,000 cents and is marked up at 45 percent. The second band covers the portion above 5,000 cents and up to and including 20,000 cents — that is, the next 15,000 cents of wholesale cost — and is marked up at 30 percent. The third band covers any portion of the unit cost above 20,000 cents and is marked up at 18 percent.

To price one unit, the system takes the lesser of the wholesale unit cost and 5,000 cents as the first-band amount, takes the portion of the unit cost falling between 5,000 and 20,000 cents (that is, the wholesale cost minus 5,000, floored at zero and capped at 15,000) as the second-band amount, and takes whatever remains above 20,000 cents as the third-band amount. The per-unit markup in cents is the first-band amount times 0.45, plus the second-band amount times 0.30, plus the third-band amount times 0.18, with that marginal sum rounded half-up to a whole number of cents. The unit price for the line is the wholesale unit cost plus that per-unit markup, stored as `unit_price_cents`, and the line total is the unit price multiplied by the quantity, stored as `line_total_cents`. Because each band is marked up at its own rate and the results summed, this is a true marginal computation and not a single blended rate applied to the whole cost.

### 3.10. Reconstructing the Final Bill

When a visit is finished the request's `final_total_cents` is rebuilt from actuals. The labour hours are the visit's `logged_labor_hours` plus the sum of `add_on_labor_hours` across only those inspection findings that ended in `APPROVED`. Those total hours are multiplied by the mechanic's own `labor_rate_cents_per_hour`, and the product is rounded half-up to whole cents — the hours are summed first and the single product is rounded once, not rounded per finding. If the request carries a fleet account, that rounded labour figure is then multiplied by one minus the fleet account's `labor_discount_pct` and rounded half-up again; for a retail request the labour figure stands unchanged. The parts component is the sum of `line_total_cents` over every part line for the request that is not `VOIDED` — that is, every line in `SOURCED` or `INSTALLED` status — where each line total was already rounded per unit at sourcing time, so the platform sums those already-rounded line totals without re-rounding. The tow component is the approved quote's `tow_fee_cents` when the request's `routing_mode` is `TOW_TO_SHOP`, and zero otherwise. The final total is the discounted (or undiscounted) labour figure plus the parts sum plus the tow component, and it is stored on the request and copied to the payment's `total_due_cents`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify or act upon an existing resource, and read operations, return a `200 OK` status code. The logical-clock endpoint, although it mutates server state, returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set or reset the logical clock to a supplied instant | PlatformAdmin |
| POST | `/catalog-parts` | Seed a catalog part with a wholesale cost | PlatformAdmin |
| GET | `/catalog-parts/{id}` | Fetch a catalog part | PlatformAdmin, Mechanic, Dispatcher |
| POST | `/fleet-accounts` | Create a fleet account | PlatformAdmin |
| GET | `/fleet-accounts/{id}` | Fetch a fleet account, including the computed outstanding balance | PlatformAdmin, FleetManager |
| POST | `/fleet-accounts/{id}/suspend` | Suspend a fleet account | PlatformAdmin |
| GET | `/fleet-accounts/{id}/payments` | List payments billed to a fleet account | PlatformAdmin, FleetManager |
| POST | `/customers` | Register a customer | PlatformAdmin |
| GET | `/customers/{id}` | Fetch a customer | PlatformAdmin, Customer |
| GET | `/customers/{id}/service-requests` | List a customer's service requests | PlatformAdmin, Customer |
| GET | `/customers` | List customers, optionally filtered by fleet | PlatformAdmin, FleetManager |
| POST | `/mechanics` | Create a mechanic | PlatformAdmin |
| GET | `/mechanics/{id}` | Fetch a mechanic | PlatformAdmin, Dispatcher, Mechanic |
| GET | `/mechanics/{id}/job-visits` | List a mechanic's job visits | PlatformAdmin, Dispatcher, Mechanic |
| POST | `/service-requests` | File a diagnostic/symptom service request | Customer |
| GET | `/service-requests/{id}` | Fetch a service request | PlatformAdmin, Customer, Mechanic, Dispatcher |
| GET | `/service-requests` | List service requests, optionally filtered by customer or fleet | PlatformAdmin, Dispatcher, FleetManager |
| POST | `/service-requests/{id}/quotes` | Send a quote (or a replacement after a revision request) | Mechanic |
| GET | `/service-requests/{id}/quotes` | List quotes for a request | PlatformAdmin, Customer, Mechanic, Dispatcher |
| POST | `/service-requests/{id}/dispatch` | Assign a mechanic and routing, creating a job visit | Dispatcher |
| POST | `/service-requests/{id}/part-lines` | Source a non-add-on part for the request | Mechanic |
| GET | `/service-requests/{id}/part-lines` | List part lines for a request | PlatformAdmin, Customer, Mechanic, Dispatcher |
| GET | `/part-lines/{id}` | Fetch a single part line | PlatformAdmin, Customer, Mechanic, Dispatcher |
| GET | `/part-lines` | List part lines, optionally filtered by catalog part or request | PlatformAdmin, Mechanic, Dispatcher |
| POST | `/service-requests/{id}/inspection-findings` | Record an on-site inspection finding (add-on proposal) | Mechanic |
| GET | `/service-requests/{id}/inspection-findings` | List inspection findings for a request | PlatformAdmin, Customer, Mechanic, Dispatcher |
| GET | `/inspection-findings/{id}` | Fetch a single inspection finding | PlatformAdmin, Customer, Mechanic, Dispatcher |
| GET | `/inspection-findings` | List inspection findings, optionally filtered by visit, recommended part, or request | PlatformAdmin, Mechanic, Dispatcher |
| POST | `/service-requests/{id}/resolve-addons` | Approve/decline all proposed findings in one call | Customer |
| POST | `/service-requests/{id}/cancel` | Cancel a pre-dispatch request | Customer |
| GET | `/quotes/{id}` | Fetch a quote | PlatformAdmin, Customer, Mechanic, Dispatcher |
| POST | `/quotes/{id}/approve` | Approve a sent quote (OCC-guarded; fleet checks) | Customer |
| POST | `/quotes/{id}/reject` | Reject a sent quote | Customer |
| POST | `/quotes/{id}/request-revision` | Request a revised quote | Customer |
| GET | `/job-visits/{id}` | Fetch a job visit | PlatformAdmin, Customer, Mechanic, Dispatcher |
| GET | `/job-visits` | List job visits, optionally filtered by request or mechanic | PlatformAdmin, Dispatcher, Mechanic |
| POST | `/job-visits/{id}/depart` | Depart to the job | Mechanic |
| POST | `/job-visits/{id}/start-work` | Begin work (on-site or at shop) | Mechanic |
| POST | `/job-visits/{id}/finish` | Finish the visit, finalise the bill, invoice the payment | Mechanic |
| POST | `/job-visits/{id}/abort` | Abort a scheduled or en-route visit and revert dispatch | Dispatcher |
| GET | `/payments/{id}` | Fetch a payment | PlatformAdmin, Customer, FleetManager, Dispatcher |
| GET | `/service-requests/{id}/payments` | List payments for a request | PlatformAdmin, Customer, FleetManager, Dispatcher |
| POST | `/payments/{id}/settle` | Settle an invoiced payment | FleetManager, Customer |
| POST | `/payments/{id}/refund` | Refund an invoiced payment | Dispatcher |
| POST | `/service-requests/{id}/warranty-claims` | File a warranty claim against a completed request | Customer |
| GET | `/service-requests/{id}/warranty-claims` | List warranty claims for a request | PlatformAdmin, Customer, Dispatcher |
| GET | `/warranty-claims/{id}` | Fetch a warranty claim | PlatformAdmin, Customer, Dispatcher |
| GET | `/warranty-claims` | List warranty claims, optionally filtered by callback visit or request | PlatformAdmin, Dispatcher |
| POST | `/warranty-claims/{id}/request-info` | Request more information on a claim | Dispatcher |
| POST | `/warranty-claims/{id}/supply-info` | Supply requested information on a claim | Customer |
| POST | `/warranty-claims/{id}/approve` | Approve a claim and schedule a free callback visit | Dispatcher |
| POST | `/warranty-claims/{id}/deny` | Deny a claim | Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ZONE_MISMATCH` | 409 Conflict |
| `ERR_INSUFFICIENT_SKILL_TIER` | 409 Conflict |
| `ERR_VISIT_OVERLAP` | 409 Conflict |
| `ERR_CALLBACK_SLOT_CONFLICT` | 409 Conflict |
| `ERR_WARRANTY_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_FLEET_CREDIT_EXCEEDED` | 402 Payment Required |
| `ERR_FLEET_ACCOUNT_SUSPENDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ADDONS_UNRESOLVED` | 409 Conflict |
| `ERR_VALIDATION_PENDING` | 422 Unprocessable Entity |
