# Waste Recycling Collection API — Product Requirements Document

## 1. Introduction

Municipal and commercial waste haulers operate on razor-thin margins where the difference between a profitable contract and a losing one comes down to two things: accurately billing the weight a customer actually throws away, and credibly demonstrating how much of that weight was diverted from the landfill. This API is the system of record for a pay-as-you-throw waste and recycling collection operation. It tracks the physical assets a customer is given (carts of different material streams and sizes), the cadence at which those carts are serviced (frequency plans), the daily route manifests that field crews drive, and the outcome of every individual pickup — completed with a weighed load, missed, or cancelled.

From those operational primitives the system derives money and accountability. Weighed loads roll up into tiered pay-as-you-throw charges; contaminated recycling loads accrue severity-based surcharges; carrier-fault misses generate goodwill credits; and each account's landfill-diversion performance is measured against a contractual floor that, when missed, levies a rebate penalty. The billing surface closes the loop with a dispute-and-revision invoice lifecycle so that disagreements are re-priced rather than abandoned.

The platform serves four operational constituencies whose duties rarely overlap: dispatchers who own the route and inventory lifecycle, drivers who record what happened in the field, a billing function that owns invoices, credits, and diversion accounting, and the residents and businesses themselves who self-serve a narrow slice of read and request operations. The remainder of this document specifies the contracts, invariants, and workflows that bind these roles together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The one exception is anonymous account self-registration, which may be performed without authentication.

The system recognizes exactly four roles, spelled precisely as follows: `ResidentAccount`, `Dispatcher`, `Driver`, and `Billing`. When a request is made under a role that is not authorized for the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The `ResidentAccount` role is **entity-backed**: when `X-User-Role` is `ResidentAccount`, the `X-User-ID` value is the `id` of the acting `ServiceAccount`. Ownership checks on any account-owned resource compare the resource's owning account reference to `X-User-ID`; a resident acting on a resource whose account is not its own is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check applies to the resident's self-service operations: disputing an invoice, requesting a special pickup, and cancelling a special pickup. It additionally guards a resident's read access to account-owned resources: fetching a single `Invoice`, `SpecialPickup`, or `MissedPickupCredit` that belongs to another account is likewise rejected with `ERR_NOT_RESOURCE_OWNER`, and the corresponding list endpoints (`GET /invoices`, `GET /special-pickups`, `GET /missed-pickup-credits`) are implicitly scoped for a resident to only the resources whose account is its own. Diversion-period reads are not ownership-scoped: any resident may fetch or list any account's `DiversionPeriod`.

The other three roles are operator roles whose identifiers are **opaque**. When `X-User-Role` is `Dispatcher`, `Driver`, or `Billing`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. In one place the server does record such an identifier: when a route's driver is assigned, the supplied `assigned_driver_id` is the `X-User-ID` of a `Driver` and is stored on the route as an opaque value, never resolved to a persisted entity.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with no value below 0 permitted. A `limit` outside the inclusive range of 1 through 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Most resources in the system carry a standard set of server-managed fields. The `id` is a server-minted UUID with no type prefix; it is identity only and is never accepted as a business-decision input. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp that is refreshed on every mutation of the resource, including mutations that arrive as cascaded side effects from operations on other resources. The `version` field is an integer that starts at 1 when the resource is created and increments by exactly one on every mutation; it doubles as the optimistic-concurrency token described in §2.7.

One entity is deliberately leaner: a `WeightTicket` is an immutable scale record and carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once recorded it is never mutated. Its `created_at` additionally serves as the chronological tie-break key when billing replays the tickets that fall within a billing period. Every other entity — `ServiceAccount`, `Cart`, `ServicePlan`, `Route`, `Stop`, `Pickup`, `ContaminationTag`, `Invoice`, `SpecialPickup`, `MissedPickupCredit`, and `DiversionPeriod` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Nested Resource Retrieval and Reference Resolution

A number of endpoints address a resource through a path that names a parent followed by a child collection. For any such path, the system validates the existence of each identifier from left to right and rejects the request with `ERR_NOT_FOUND` at the *first* path identifier that does not resolve to an existing resource. For example, when appending a stop to a route, the route in the path must exist before the system considers the stop body at all.

A second class of existence check guards the request body rather than the path. On any create endpoint that accepts a foreign-key identifier in its payload, every such referenced resource must exist; a body that names a non-existent resource is rejected with `ERR_REFERENCE_NOT_FOUND`. Path-id failures and body-reference failures are distinct: the path check fires first and yields `ERR_NOT_FOUND`, while a body reference to a missing resource yields `ERR_REFERENCE_NOT_FOUND`.

Beyond existence, every create and update endpoint requires its mandatory body fields to be present and requires every enum-typed field to carry a value within its declared domain; a request with a missing required field, or with an enum value outside its allowed set, is rejected with `ERR_INVALID_REQUEST`.

When several checks could fire on one request, they are evaluated in a fixed precedence so the earliest applicable failure is the one reported. Authentication comes first: missing or malformed headers (`ERR_UNAUTHENTICATED`) are caught before anything else, then role authorization (`ERR_FORBIDDEN_ROLE`), then — for a resident acting on an account-owned resource — ownership (`ERR_NOT_RESOURCE_OWNER`). Next come existence checks: path identifiers left-to-right (`ERR_NOT_FOUND`), then body foreign-key references (`ERR_REFERENCE_NOT_FOUND`). After existence comes request shape: required-field and enum-domain validation (`ERR_INVALID_REQUEST`), and on list endpoints the pagination check (`ERR_INVALID_PAGINATION`). Only once a request is authenticated, authorized, resolved, and well-formed does the system evaluate state and business rules: whether the requested transition is defined for the resource's current state (`ERR_INVALID_STATE`), the optimistic-concurrency version check (`ERR_STALE_VERSION`), and the domain-specific constraints described throughout §3. A consequence of this ordering is that, for example, a stale-version conflict surfaces only after the target resource has been confirmed to exist and to be in a transition-eligible state.

### 2.6. Monetary, Weight, and Percentage Precision

All money in the system is represented as integer cents — fields whose names end in `_cents` are whole-cent integers, never fractional. Weights are pounds expressed as numbers. Where a weight computation requires rounding, the net weight of a scale ticket is rounded to three decimal places using the round-half-up convention. Percentages — specifically the landfill-diversion rate — are rounded to two decimal places, also round-half-up.

The system pins the **order of rounding** independently for each money calculation, because rounding order changes the result. Two contrasting conventions appear in this domain and must not be conflated: the pay-as-you-throw weight charge sums all per-tier amounts and then rounds once at the end (sum-then-round), whereas the contamination surcharge rounds each per-pickup amount first and only then sums the rounded line items (round-per-line-item-then-sum). The specific evaluation order for each calculation is spelled out in §3 where that charge is described.

### 2.7. Optimistic Concurrency Control on Stale Parents

Two write operations are guarded by optimistic concurrency control against a parent entity's `version`. These are the only two endpoints that accept a version field; no other endpoint takes one.

Creating a draft invoice for an account requires the request body to carry `expected_account_version`, holding the `version` of the target `ServiceAccount` that the client last observed. If that value does not match the account's current `version` — for instance because a prior invoice issue, void, or credit cascade has since advanced the account's `version` and recomputed its balance — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The client must re-read the account before billing it again, so it never overwrites against a balance it has not seen.

Recording a completed pickup requires the request body to carry `expected_cart_version`, holding the `version` of the pickup's `Cart` that the driver last observed. If the cart's `version` has advanced since — because the cart was placed on hold or retired, or because another pickup already emptied and re-measured it — the completion is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the driver application to re-fetch the cart before recording the empty.

### 2.8. Cascades, Bubble-Ups, and Derived-Field Reconciliation

Several operations mutate more than one resource. Whenever a side effect mutates a resource, that resource's `updated_at` is refreshed and its `version` is incremented by one, exactly as a direct mutation would. Three families of propagation exist. **Cascades** flow downward from a parent: closing an account retires its carts and terminates its plans; cancelling a route skips its still-pending stops. **Bubble-ups** flow upward from a child: completing or missing a pickup advances its stop to a terminal state. **Reconciliations** keep a derived field consistent with the rows it summarizes: the `contaminated` flag on a pickup, the `account_balance_cents` on an account, and the `total_net_weight_lbs` on a route are all recomputed whenever an underlying row changes. The concrete trigger, direction, and resulting state for each propagation are described alongside the workflow that causes it in §3.

### 2.9. The Landfill-Diversion and Pay-As-You-Throw Accounting Principle

The economic spine of the system is the distinction between landfill-bound trash and diverted material. Only `TRASH`-stream weight is billable per pound under pay-as-you-throw; weight collected on `RECYCLE` and `ORGANICS` carts is treated as diversion and is recovered only through the flat base fee, never charged by the pound. The diverted-versus-landfill split of each weighed load is captured at the scale and later measured against a contractual diversion floor, with a rebate penalty assessed against accounts that fall short. The exact billable-weight tiers, surcharge tiers, credit amounts, diversion-rate computation, and penalty schedule are detailed in the workflow subsections of §3.

## 3. Business Logic & Workflows

### 3.1. Onboarding an Account: Carts, Plans, and Activation

A new customer relationship begins when a `ServiceAccount` is registered. Registration is open: a prospective resident may self-register without authentication, and a `Dispatcher` may also create accounts on a customer's behalf. The registrant supplies a `service_address` and a `rate_class`, and may optionally supply a `diversion_floor_pct`; when omitted the floor defaults to 0. The `rate_class` is one of `RESIDENTIAL`, `COMMERCIAL_SMALL`, or `COMMERCIAL_LARGE`, and it is fixed at registration as the input to every downstream weight charge. A freshly registered account begins in `PENDING_SETUP`.

Before service can run, the account is provisioned with physical and scheduling assets. A `Dispatcher` creates a `Cart` for the account by supplying its `account_id`, the material `stream` it collects (`TRASH`, `RECYCLE`, or `ORGANICS`), and its `size_gallons`, which must be one of 35, 65, or 96; an out-of-domain size is rejected with `ERR_VALIDATION`. The cart's `tare_weight_lbs` — the empty weight subtracted from every gross scale reading — may be supplied and defaults to 0. A cart is born `ASSIGNED`. From there a dispatcher may activate it to `ACTIVE`, place an `ACTIVE` cart `ON_HOLD`, return an `ON_HOLD` cart to `ACTIVE`, or retire a cart from any of `ASSIGNED`, `ACTIVE`, or `ON_HOLD` to the terminal `RETIRED` state.

In parallel the dispatcher defines one or more `ServicePlan` records, each created with an `account_id`, a `stream`, a service `frequency` of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`, and a `base_monthly_fee_cents` that must be an integer of at least 0; a non-integer or negative value is rejected with `ERR_INVALID_REQUEST`. A plan starts in `DRAFT`. Activating a plan — moving it from `DRAFT` to `ACTIVE`, or reviving a `PAUSED` plan back to `ACTIVE` — is permitted only when the plan's account owns a `Cart` whose `stream` equals the plan's `stream` and whose status is either `ASSIGNED` or `ACTIVE`; if no such cart exists the activation is rejected with `ERR_NO_MATCHING_CART`. An `ACTIVE` plan may be paused to `PAUSED`, and a plan in any of `DRAFT`, `ACTIVE`, or `PAUSED` may be terminated to the terminal `TERMINATED` state.

Account activation is the gate to live service. A `Dispatcher` activates a `PENDING_SETUP` account, transitioning it to `ACTIVE`, only once the account has at least one `Cart` in `ASSIGNED` or `ACTIVE` status and at least one `ServicePlan` in `ACTIVE` status. The same activation endpoint revives a `SUSPENDED` account back to `ACTIVE`. A `Billing` operator may suspend an `ACTIVE` account to `SUSPENDED`. Each of these transitions increments the account's `version`.

Closing an account is a `Billing` action and the source of a multi-step cascade. An account may be closed from either `ACTIVE` or `SUSPENDED`, but only when it has no `Invoice` in `ISSUED` or `DISPUTED` status — an open balance blocks closure with `ERR_OPEN_BALANCE`. On close, the account moves to the terminal `CLOSED` state, and the system cascades through the account's dependents: every `Cart` for the account in `ASSIGNED`, `ACTIVE`, or `ON_HOLD` is driven to `RETIRED`, and every `ServicePlan` for the account in `DRAFT`, `ACTIVE`, or `PAUSED` is driven to `TERMINATED`. Each cascaded cart and plan has its own `version` incremented and `updated_at` refreshed, and the account's `version` increments as well.

### 3.2. Building and Driving the Route Manifest

Daily field work is organized around a `Route`. A `Dispatcher` creates a route by supplying the `service_date` it will be driven and the material `stream` it collects, and may optionally name the `assigned_driver_id` — the opaque `X-User-ID` of the driver who will run it. A route starts `PLANNED`. While a route is still `PLANNED`, the dispatcher may assign or change its driver by updating the `assigned_driver_id`; this update increments the route's `version`.

The route's manifest is its ordered list of stops. A `Dispatcher` appends a `Stop` to a route by supplying the `account_id` serviced at that stop and a `sequence`, a 1-based ordinal position that must be an integer of at least 1 and must be unique within the route; a non-integer or below-1 `sequence` is rejected with `ERR_INVALID_REQUEST`, while a second stop claiming a `sequence` already present on the route is rejected with `ERR_DUPLICATE_SEQUENCE`. A new stop begins `PENDING`. Each stop records the `route_id` of the route it belongs to, and the stop list may be filtered by `route_id`, by `account_id`, or by `status`.

A route advances through a guarded linear lifecycle. A `Dispatcher` dispatches a `PLANNED` route, moving it to `DISPATCHED`, but only when the route has a non-null `assigned_driver_id` and at least one `Stop`; a dispatch attempt on a route lacking an assigned driver or having zero stops is rejected with `ERR_DRIVER_NOT_ASSIGNED`. The assigned `Driver` then starts a `DISPATCHED` route, moving it to `IN_PROGRESS`. When the field work is done, the driver completes the route, moving it from `IN_PROGRESS` to the terminal `COMPLETED` state — but only when every `Stop` on the route has reached a terminal stop state of `SERVICED` or `SKIPPED`; if any stop is still `PENDING` the completion is rejected with `ERR_STOPS_PENDING`. A dispatcher may instead cancel a route while it is `PLANNED` or `DISPATCHED`, transitioning it to the terminal `CANCELLED` state; cancellation cascades by driving every `Stop` on the route that is still `PENDING` to `SKIPPED`. Every one of these route transitions increments the route's `version`, and each cascaded stop's `version` increments too.

A stop is never transitioned by a direct client call. Its movement out of `PENDING` is always a system bubble-up driven by the pickup recorded against it (or, as above, a cascade from route cancellation): when a pickup at the stop completes, the stop bubbles up from `PENDING` to `SERVICED`; when a pickup at the stop is missed, the stop bubbles up from `PENDING` to `SKIPPED`. In both cases the stop's `version` is incremented.

### 3.3. Recording Pickup Outcomes in the Field

A `Pickup` represents one cart serviced at one stop. A `Dispatcher` schedules a pickup at a stop by supplying the `cart_id` of the cart to be emptied; the stop is named by the path, and the created pickup records that stop as its `stop_id`. The pickup list may be filtered by `stop_id`, by `cart_id`, or by `outcome`. The pickup is born `SCHEDULED`. The system enforces one active pickup per cart per stop: if the stop's route already has a non-`CANCELLED` pickup covering the same `cart_id` at that stop, the new pickup is rejected with `ERR_PICKUP_SLOT_TAKEN`. A `CANCELLED` pickup frees the slot, allowing a fresh pickup for the same cart at that stop.

From `SCHEDULED`, a pickup forks into three terminal outcomes, recorded in its `outcome` field. The `Driver` **completes** a pickup, setting `outcome` to `COMPLETED`, but only when the pickup is still `SCHEDULED`, the pickup's stop's route is `IN_PROGRESS`, and the pickup's cart is in `ASSIGNED` or `ACTIVE` status. Completion is additionally guarded by the cart optimistic-concurrency check of §2.7 (the `expected_cart_version` body field). On completion the pickup's stop bubbles up from `PENDING` to `SERVICED`, the cart's `version` is incremented (so the next read of that cart reflects the empty), and the pickup's own `version` is incremented. Completion does not by itself record a weight; the scale ticket is a separate step described in §3.4.

The `Driver` **misses** a pickup from `SCHEDULED`, setting `outcome` to `MISSED`, only when the pickup is `SCHEDULED`, its route is `IN_PROGRESS`, and a `miss_reason` is supplied. The `miss_reason` is one of `BLOCKED_ACCESS`, `NOT_OUT`, `TRUCK_FULL`, or `MISSED_BY_CREW`, and it is recorded on the pickup. Missing a pickup bubbles its stop up from `PENDING` to `SKIPPED` and increments the pickup's `version`. Crucially, the reason determines whether the customer is made whole: when the `miss_reason` is `MISSED_BY_CREW` or `TRUCK_FULL` — both carrier-fault reasons — the system automatically creates a `MissedPickupCredit` in `PENDING` status, with its `source_type` set to `PICKUP` and its `source_pickup_id` set to this pickup, and its amount computed as described in §3.7. When the `miss_reason` is `BLOCKED_ACCESS` or `NOT_OUT` — both customer-fault reasons — no credit is created. The dispatcher may also **cancel** a `SCHEDULED` pickup, setting `outcome` to `CANCELLED`, but only while the pickup's route is `PLANNED` or `DISPATCHED` (i.e., before it is in progress); this increments the pickup's `version` and creates no credit.

Any pickup-outcome transition attempted from a state other than `SCHEDULED`, or against a route or cart not in the required status, is rejected with `ERR_INVALID_STATE`.

### 3.4. Weighing the Load and Tagging Contamination

Once a pickup is `COMPLETED`, the `Driver` records its scale reading by creating a `WeightTicket` for the pickup; the ticket records the `pickup_id` of the pickup it measures, and is created by supplying the raw `gross_weight_lbs` read off the truck scale (which must be at least 0; a negative reading is rejected with `ERR_VALIDATION`) and the `diverted` boolean indicating whether the load went to recycling or organics (true) or to the landfill (false). A weight ticket may only be recorded for a pickup whose `outcome` is `COMPLETED`, and at most one ticket may exist per pickup; recording a ticket for a non-completed pickup, or a second ticket for a pickup that already has one, is rejected with `ERR_WEIGHT_TICKET_NOT_ALLOWED`. On creation the system computes the ticket's `net_weight_lbs` as the gross reading minus the tare weight of the pickup's cart, floored at 0 so it never goes negative — that is, the larger of 0 and the difference between `gross_weight_lbs` and the cart's `tare_weight_lbs` — rounded to three decimal places, round-half-up. Recording a ticket also recomputes the route's `total_net_weight_lbs`, which is the sum of `net_weight_lbs` across all weight tickets on `COMPLETED` pickups whose stop belongs to that route.

Contamination is recorded against a pickup independently of weighing. A `Driver` or `Dispatcher` may tag a pickup's load by creating a `ContaminationTag`, supplying a `severity` of `MINOR`, `MAJOR`, or `REJECT` and an optional free-text `note`. A new tag is born `OPEN`, and creating it reconciles the pickup's derived `contaminated` flag to true. A pickup's `contaminated` flag is true whenever at least one `OPEN` tag exists for it. A `Dispatcher` clears an `OPEN` tag, moving it to the terminal `CLEARED` state and incrementing the tag's `version`; clearing reconciles the pickup's `contaminated` flag back to false only if no other `OPEN` tag remains on that pickup. The `severity` recorded on a pickup's tags drives the contamination surcharge described in §3.6.

### 3.5. Special Pickups for Bulk and Hazardous Material

Outside the regular route cadence, an account may request a one-off `SpecialPickup`. A `ResidentAccount` (acting on its own account) or a `Dispatcher` creates the request by supplying the `kind` — either `BULK` or `HAZARDOUS` — a `requested_date`, and, when the kind is `HAZARDOUS`, a `hazard_class` of `FLAMMABLE`, `CORROSIVE`, `TOXIC`, or `EWASTE`. A hazardous request created without a `hazard_class` is rejected with `ERR_HAZARD_CLASS_REQUIRED`. A special pickup is born `REQUESTED`.

A `Dispatcher` reviews the request and the lifecycle forks. **Approval** moves a `REQUESTED` special pickup to `APPROVED`, but only when the requesting account is `ACTIVE` and — if the kind is `HAZARDOUS` — a `hazard_class` is present (otherwise `ERR_HAZARD_CLASS_REQUIRED`). Approval sets `quoted_fee_cents` per the fee schedule in §3.7. **Rejection** moves a `REQUESTED` special pickup to the terminal `REJECTED` state. An `APPROVED` special pickup may be **scheduled** by a dispatcher, moving it to `SCHEDULED`, and a `SCHEDULED` one is **completed** by a `Driver`, moving it to the terminal `COMPLETED` state. Each of these transitions increments the special pickup's `version`.

Cancellation is the resident's escape hatch and is shared with the dispatcher. A special pickup may be cancelled while it is `REQUESTED`, `APPROVED`, or `SCHEDULED`, moving it to the terminal `CANCELLED` state. The cancellation has a conditional financial consequence: if the special pickup was in `SCHEDULED` status at the moment of cancellation — meaning the carrier had already committed a collection slot — the system automatically creates a `MissedPickupCredit` in `PENDING` status with its `source_type` set to `SPECIAL_PICKUP` and its `source_special_pickup_id` set to this special pickup, with the amount computed as in §3.7. Cancelling a `REQUESTED` or `APPROVED` special pickup creates no credit. In all cases the special pickup's `version` increments.

### 3.6. Issuing Invoices and Computing Charges

Billing operates the `Invoice` lifecycle. A `Billing` operator creates a draft invoice for an account by supplying the billing period's `period_start` (inclusive) and `period_end` (exclusive); the `period_start` must be strictly before `period_end` or the request is rejected with `ERR_INVALID_PERIOD`. This create is guarded by the account optimistic-concurrency check of §2.7 (the `expected_account_version` body field). A new invoice is born `DRAFT`, and creating it advances the account's `version`.

Issuing a draft invoice is where money is computed. A `Billing` operator issues a `DRAFT` invoice, moving it to `ISSUED`, but only when the invoice's account is `ACTIVE` or `SUSPENDED`. At issue, the system computes five charge components and combines them in a pinned evaluation order to set `total_cents` and then `balance_cents`:

1. The `base_fee_cents` is the sum of `base_monthly_fee_cents` over the account's `ServicePlan` records that are in `ACTIVE` status.

2. The `weight_charge_cents` is the pay-as-you-throw weight charge. Its input is the set of `COMPLETED`-pickup weight tickets whose `created_at` falls within the half-open invoice window from `period_start` (inclusive) to `period_end` (exclusive), counting only loads collected on `TRASH`-stream carts; recycle and organics weight is excluded entirely from the per-pound charge. The billable pounds are the sum of `net_weight_lbs` over those trash tickets, reduced by the account's free allowance and floored at 0. The free allowance is 100 pounds for a `RESIDENTIAL` account and 0 pounds for both `COMMERCIAL_SMALL` and `COMMERCIAL_LARGE` accounts. The billable pounds are then charged at marginal stair-step rates across three tiers: the first 200 pounds at the tier-1 rate, the next portion above 200 pounds and up to 500 pounds at the tier-2 rate, and any pounds beyond 500 at the tier-3 rate. The per-pound rates in cents depend on the `rate_class`: for `RESIDENTIAL` the three tier rates are 5, 8, and 12; for `COMMERCIAL_SMALL` they are 7, 10, and 15; for `COMMERCIAL_LARGE` they are 6, 9, and 13. Each pound is billed at the rate of the tier it falls in. The three per-tier amounts are summed first, and the single round-half-up to whole cents is applied once to that sum (sum-then-round).

3. The `contamination_surcharge_cents` is the sum of per-pickup surcharges over the `COMPLETED` pickups in the same invoice window that carry at least one `ContaminationTag` of any status. For each such pickup, only the single highest-severity tag drives the surcharge (`REJECT` outranks `MAJOR`, which outranks `MINOR`); lower-severity tags on the same pickup are ignored and are not additive. That pickup's surcharge is the pickup's net billable weight multiplied by the severity's per-pound rate, plus the severity's flat amount, with the result rounded half-up to whole cents per pickup. The per-pound severity rates in cents are 2 for `MINOR`, 5 for `MAJOR`, and 10 for `REJECT`; the flat amounts in cents are 500 for `MINOR`, 1500 for `MAJOR`, and 4000 for `REJECT`. Each pickup's surcharge is rounded first, and only the rounded per-pickup amounts are then summed (round-per-line-item-then-sum) — the opposite order from the weight charge.

4. The `diversion_penalty_cents` is the rebate penalty for falling short of the contractual diversion floor. The system locates the `FINALIZED` `DiversionPeriod` for the account whose window `period_start` and `period_end` exactly equal the invoice's `period_start` and `period_end`; if no such finalized period exists, the penalty is 0. Otherwise the shortfall is the account's `diversion_floor_pct` minus that period's `diversion_rate_pct`, floored at 0. If the diversion rate meets or exceeds the floor the shortfall is 0 and so is the penalty — meeting the floor exactly is compliant. When the rate is below the floor, the penalty is the shortfall in percentage points multiplied by 100 cents per percentage point, rounded half-up to whole cents.

5. The `credit_cents` is the sum of `amount_cents` over the `MissedPickupCredit` records absorbed onto this invoice (those that become `APPLIED` against it, per §3.7).

The `total_cents` is then the sum of the four charge components — `base_fee_cents`, `weight_charge_cents`, `contamination_surcharge_cents`, and `diversion_penalty_cents` — minus `credit_cents`, with the result floored at 0. Credits are subtracted only after all charges are summed; a credit may drive the total to 0 but never negative, and any credit in excess of charges is lost on this invoice rather than carried forward. The subtraction and the floor are exact integer operations with no further rounding. On issue, `balance_cents` is set equal to `total_cents`.

### 3.7. Credits, the Account Ledger, and the Dispute Loop

The `MissedPickupCredit` is a customer-goodwill instrument with a polymorphic origin. Its `source_type` is `PICKUP` when it was generated by a carrier-fault missed pickup, or `SPECIAL_PICKUP` when it was generated by cancelling a carrier-committed special pickup; exactly one of `source_pickup_id` or `source_special_pickup_id` is populated to match. A credit's `amount_cents` is computed by variant: a `PICKUP`-sourced credit is a flat goodwill amount of 1500 cents regardless of weight or plan, while a `SPECIAL_PICKUP`-sourced credit is 50 percent of the originating special pickup's `quoted_fee_cents`, rounded half-up to whole cents. The `quoted_fee_cents` itself is set at special-pickup approval: a `BULK` request quotes a flat 3500 cents with no multiplier, while a `HAZARDOUS` request quotes 8000 cents scaled by the hazard-class multiplier — 1.5 for `FLAMMABLE`, 1.75 for `CORROSIVE`, 2.0 for `TOXIC`, and 1.25 for `EWASTE` — rounded half-up to whole cents.

A credit begins life `PENDING`. When an invoice is issued, the system absorbs each eligible `PENDING` credit for that invoice's account — that is, every `PENDING` credit whose `account_id` matches the invoice's account — moving it to `APPLIED` and setting its `applied_invoice_id` to the issued invoice; the credit's `version` increments. A `Billing` operator may also void a still-`PENDING` credit directly, moving it to the terminal `VOID` state. Each credit carries a `status` of `PENDING`, `APPLIED`, or `VOID` and, once applied, an `applied_invoice_id` pointing at the absorbing invoice.

Every account exposes a derived `account_balance_cents`, defined as the sum of `balance_cents` over the account's invoices in `ISSUED` or `DISPUTED` status, minus the sum of `amount_cents` over the account's credits in `APPLIED` status. This balance is recomputed on every invoice and credit mutation: invoice issue, invoice payment, invoice void, and credit void all trigger a recomputation.

The issued invoice supports a revision loop. A `ResidentAccount` (acting on its own invoice) may dispute an `ISSUED` invoice, moving it to `DISPUTED`. A `Billing` operator resolves a `DISPUTED` invoice by re-pricing it: all charge components and `total_cents` are recomputed in the same pinned order described in §3.6, `balance_cents` is reset to the new `total_cents`, and the invoice returns to `ISSUED`. Billing may pay an `ISSUED` invoice, moving it to the terminal `PAID` state with `balance_cents` reset to 0 and the account balance recomputed. Billing may also void an invoice from `DRAFT`, `ISSUED`, or `DISPUTED`, moving it to the terminal `VOID` state with `balance_cents` set to 0; voiding releases every `MissedPickupCredit` whose `applied_invoice_id` is this invoice back to `PENDING` status, clearing its `applied_invoice_id` and incrementing its `version`, and then the account balance is recomputed. Any invoice transition attempted from a status the transition is not defined for is rejected with `ERR_INVALID_STATE`.

### 3.8. Measuring Landfill Diversion

A `DiversionPeriod` is the measurement window against which an account's diversion performance is judged. A `Billing` operator opens a window for an account by supplying its `period_start` (inclusive) and `period_end` (exclusive); the start must be strictly before the end (`ERR_INVALID_PERIOD`), and the new window must not overlap any existing `OPEN` or `FINALIZED` diversion period for that account. Overlap is judged on half-open intervals, so two windows that merely touch at a shared endpoint do not overlap and are allowed; a genuine overlap is rejected with `ERR_PERIOD_OVERLAP`. A new window is born `OPEN`.

Finalizing a window is what produces the diversion rate. A `Billing` operator finalizes an `OPEN` period, moving it to the terminal `FINALIZED` state and computing three figures from the `COMPLETED`-pickup weight tickets whose `created_at` falls in the half-open window from `period_start` (inclusive) up to but not including `period_end`. A ticket whose `created_at` lands exactly on `period_end` is excluded, because the window is end-exclusive. The `diverted_weight_lbs` is the sum of `net_weight_lbs` over those tickets whose `diverted` flag is true; the `total_weight_lbs` is the sum of `net_weight_lbs` over all those tickets regardless of diversion. The `diversion_rate_pct` is then 100 multiplied by `diverted_weight_lbs` divided by `total_weight_lbs`, rounded half-up to two decimal places — except that when `total_weight_lbs` is 0 the rate is defined as exactly 0 rather than undefined, so the empty-window case never divides by zero. Finalizing increments the period's `version`. This finalized rate is what the diversion-penalty computation in §3.6 reads when an invoice for the matching window is issued or resolved.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (for example registering an account, creating a cart, appending a stop, or recording a weight ticket) return `201 Created`. Operations that modify an existing resource — every state transition, every reconciliation-bearing action, and the route driver patch — return `200 OK`. All endpoints require the authentication headers of §2.1 except where noted.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Register a new service account (anonymous self-registration) | ResidentAccount, Dispatcher |
| GET | `/accounts/{id}` | Fetch an account, including computed balance | ResidentAccount, Dispatcher, Billing, Driver |
| GET | `/accounts` | List accounts (filterable by status) | Dispatcher, Billing |
| POST | `/accounts/{id}/activate` | Activate a pending or suspended account | Dispatcher |
| POST | `/accounts/{id}/suspend` | Suspend an active account | Billing |
| POST | `/accounts/{id}/close` | Close an account; cascades cart retirement and plan termination | Billing |
| POST | `/carts` | Create a cart and assign it to an account | Dispatcher |
| GET | `/carts/{id}` | Fetch a cart | Dispatcher, Driver, Billing |
| GET | `/carts` | List carts; filter by account, status, stream | Dispatcher, Driver, Billing |
| POST | `/carts/{id}/activate` | Activate a cart | Dispatcher |
| POST | `/carts/{id}/hold` | Place an active cart on hold | Dispatcher |
| POST | `/carts/{id}/retire` | Retire a cart | Dispatcher |
| POST | `/service-plans` | Create a service-frequency plan for an account | Dispatcher |
| GET | `/service-plans/{id}` | Fetch a service plan | Dispatcher, Billing |
| GET | `/service-plans` | List service plans; filter by account, status | Dispatcher, Billing |
| POST | `/service-plans/{id}/activate` | Activate a draft or paused plan | Dispatcher |
| POST | `/service-plans/{id}/pause` | Pause an active plan | Dispatcher |
| POST | `/service-plans/{id}/terminate` | Terminate a plan | Dispatcher |
| POST | `/routes` | Create a route run for a service date and stream | Dispatcher |
| GET | `/routes/{id}` | Fetch a route, including computed total net weight | Dispatcher, Driver, Billing |
| GET | `/routes` | List routes; filter by status, stream | Dispatcher, Driver, Billing |
| PATCH | `/routes/{id}` | Assign or change the route's driver while planned | Dispatcher |
| POST | `/routes/{id}/dispatch` | Dispatch a planned route to its driver | Dispatcher |
| POST | `/routes/{id}/start` | Driver starts a dispatched route | Driver |
| POST | `/routes/{id}/complete` | Driver completes a route once all stops are terminal | Driver |
| POST | `/routes/{id}/cancel` | Cancel a planned or dispatched route; skips pending stops | Dispatcher |
| POST | `/routes/{id}/stops` | Append a stop to a route manifest | Dispatcher |
| GET | `/routes/{id}/stops` | List the manifest stops of a route | Dispatcher, Driver, Billing |
| GET | `/stops/{id}` | Fetch a stop | Dispatcher, Driver, Billing |
| GET | `/stops` | List stops; filter by account, route, status | Dispatcher, Driver, Billing |
| POST | `/stops/{id}/pickups` | Schedule a pickup at a stop for a given cart | Dispatcher |
| GET | `/pickups/{id}` | Fetch a pickup, including reconciled contaminated flag | Dispatcher, Driver, Billing |
| GET | `/pickups` | List pickups; filter by stop, cart, outcome | Dispatcher, Driver, Billing |
| POST | `/pickups/{id}/complete` | Driver records a completed pickup (OCC on the cart) | Driver |
| POST | `/pickups/{id}/miss` | Driver records a missed pickup; carrier-fault auto-credits | Driver |
| POST | `/pickups/{id}/cancel` | Cancel a scheduled pickup before the route is in progress | Dispatcher |
| POST | `/pickups/{id}/weight-ticket` | Record the scale weight for a completed pickup | Driver |
| GET | `/pickups/{id}/weight-ticket` | Fetch the weight ticket(s) for a pickup | Dispatcher, Driver, Billing |
| POST | `/pickups/{id}/contamination-tags` | Tag a pickup's load as contaminated | Driver, Dispatcher |
| GET | `/pickups/{id}/contamination-tags` | List a pickup's contamination tags | Dispatcher, Driver, Billing |
| GET | `/contamination-tags/{id}` | Fetch a contamination tag | Dispatcher, Driver, Billing |
| POST | `/contamination-tags/{id}/clear` | Clear a contamination tag | Dispatcher |
| POST | `/accounts/{id}/invoices` | Create a draft invoice for a billing period (OCC on the account) | Billing |
| GET | `/invoices/{id}` | Fetch an invoice with all computed charge components | Billing, ResidentAccount |
| GET | `/invoices` | List invoices; filter by account, status | Billing, ResidentAccount |
| POST | `/invoices/{id}/issue` | Issue a draft invoice; computes charges, absorbs credits | Billing |
| POST | `/invoices/{id}/dispute` | Account disputes an issued invoice | ResidentAccount |
| POST | `/invoices/{id}/resolve` | Re-price a disputed invoice and re-issue it | Billing |
| POST | `/invoices/{id}/pay` | Mark an issued invoice paid | Billing |
| POST | `/invoices/{id}/void` | Void an invoice; releases any applied credits | Billing |
| POST | `/accounts/{id}/special-pickups` | Request a bulk or hazardous special pickup | ResidentAccount, Dispatcher |
| GET | `/special-pickups/{id}` | Fetch a special pickup, including quoted fee | Dispatcher, Driver, Billing, ResidentAccount |
| GET | `/special-pickups` | List special pickups; filter by account, kind, status | Dispatcher, Driver, Billing, ResidentAccount |
| POST | `/special-pickups/{id}/approve` | Approve a requested special pickup; quotes the fee | Dispatcher |
| POST | `/special-pickups/{id}/reject` | Reject a requested special pickup | Dispatcher |
| POST | `/special-pickups/{id}/schedule` | Schedule an approved special pickup | Dispatcher |
| POST | `/special-pickups/{id}/complete` | Mark a scheduled special pickup completed | Driver |
| POST | `/special-pickups/{id}/cancel` | Cancel a special pickup; scheduled ones auto-credit | ResidentAccount, Dispatcher |
| GET | `/missed-pickup-credits/{id}` | Fetch a missed-pickup credit | Billing, ResidentAccount |
| GET | `/missed-pickup-credits` | List credits; filter by account, status, source, applied invoice | Billing, ResidentAccount |
| POST | `/missed-pickup-credits/{id}/void` | Void a pending credit | Billing |
| POST | `/accounts/{id}/diversion-periods` | Open a landfill-diversion measurement window | Billing |
| GET | `/diversion-periods/{id}` | Fetch a diversion period, including computed rate | Billing, ResidentAccount |
| GET | `/diversion-periods` | List diversion periods; filter by account, status | Billing, ResidentAccount |
| POST | `/diversion-periods/{id}/finalize` | Finalize a diversion window; computes rate | Billing |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_SEQUENCE` | 409 |
| `ERR_HAZARD_CLASS_REQUIRED` | 422 |
| `ERR_NO_MATCHING_CART` | 409 |
| `ERR_WEIGHT_TICKET_NOT_ALLOWED` | 409 |
| `ERR_INVALID_PERIOD` | 422 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_PICKUP_SLOT_TAKEN` | 409 |
| `ERR_OPEN_BALANCE` | 409 |
| `ERR_STOPS_PENDING` | 409 |
| `ERR_DRIVER_NOT_ASSIGNED` | 409 |
| `ERR_VALIDATION` | 422 |
