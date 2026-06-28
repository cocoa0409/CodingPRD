# Cabinet Refacing & Kitchen Refresh API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Cabinet Refacing & Kitchen Refresh API, the operational backbone of a "Kitchen Tune-Up"-style home-improvement business. The platform carries a homeowner from a first lead all the way through an in-home measure, a door-and-finish selection, a priced quote, a material order with a realistic lead time, a scheduled installation by a certified crew, and finally a warranty window — with optional hardware and countertop add-ons, customer-initiated change orders, and consumer financing layered along the way.

Two pricing behaviors sit at the heart of the system and must not be conflated. When a project is first quoted, the sales team produces a deliberately coarse **provisional estimate** so the homeowner has a ballpark figure; when the quote is formally issued, the system replaces that with a fully itemized **firm quote** that accounts for door counts, finish materials, volume discounts, and approved add-ons. Layered on top is a web of cascading consequences: a customer-accepted change order re-prices the firm quote, which can push out the material lead time, which can in turn invalidate an already-scheduled installation window. Because several actors — sales, scheduling, the homeowner, and the install crew — touch the same project concurrently, the system uses a logical clock to drive every time-sensitive computation (lead times, quote expiry, warranty coverage, install gating) and optimistic concurrency control to protect the customer from approving or amending a price they never saw.

This specification is written for the engineers building the service. It describes the domain first and the mechanics second; every rule that governs behavior is stated in prose here, because this document is the single contract the implementation must satisfy.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user is acting. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles: `Customer`, `SalesRep`, `Scheduler`, `InstallCrew`, and `PlatformAdmin`.

- A `Customer` is the homeowner. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a project compare the project's `customer_id` to `X-User-ID`. A customer approves, declines, accepts, and rejects on their own project, applies for financing, and files warranty claims. A customer who attempts a customer-scoped action against a project they do not own is rejected with `ERR_NOT_PROJECT_OWNER` (HTTP 403).
- A `SalesRep` is the field salesperson who registers customers and projects, schedules and completes measures, drafts/issues/reopens quotes, and manages add-ons and change-order creation. When `X-User-Role` is `SalesRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- A `Scheduler` runs operations: placing and cancelling material orders, registering crews, scheduling and cancelling install jobs, and closing projects. When `X-User-Role` is `Scheduler`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- An `InstallCrew` is the field installer who starts and completes install jobs. When `X-User-Role` is `InstallCrew`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- A `PlatformAdmin` is the operator superset: it adjudicates warranty and financing decisions, operates the logical clock, and may perform any operation any other role may perform. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0.

Unless an endpoint states otherwise, every list is sorted by the resource's `created_at` timestamp in ascending order.

List responses report their pagination state in the `meta` object using the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every primary resource — `Customer`, `Project`, `Measure`, `Quote`, `AddOn`, `ChangeOrder`, `MaterialOrder`, `Crew`, `InstallJob`, `WarrantyClaim`, and `FinancingApplication` — carries a system-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Each of these resources also carries an `updated_at` timestamp (same format), refreshed on every mutation, and an integer `version` that begins at the resource's creation value and increments by one on every modification. The `id` is minted by the server; clients never supply it.

Because each of these entities carries the full common-field set, both `updated_at` and `version` are always present on each of them. There are no resources in this domain that omit `updated_at` or `version`.

### 2.5. State Propagation and Hierarchical Consistency

The `Project` entity is the spine of the domain, and its `status` field is computed: it is never written directly by a client but is derived from explicit transitions and from the states of its child entities. When a child operation satisfies a condition that should advance or revert the project, the server performs that change automatically as a side effect of the child operation — this is referred to throughout as a *bubble-up* (when the project advances) or a *revert* (when it falls back). Every such automatic change to a `Project` refreshes its `updated_at` and increments its `version`; the same is true for any entity the system mutates as a side effect. Mutations are committed immediately and consistently — there is no deferred or eventual reconciliation.

### 2.6. Nested Resource Retrieval and Left-to-Right Validation

Many endpoints address a resource through a path that names more than one identifier — for example, completing a measure names both a project and a measure, and placing a material order names a project. When a path carries multiple identifiers, the server validates them from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing entity. A measure-complete request whose project id does not exist therefore fails on the project before the measure is ever consulted. This existence check applies to every path identifier and to every resource id referenced in a request body.

### 2.7. Monetary Values, Precision, and Rounding

All monetary amounts are stored and returned as integer counts of cents. Wherever a computation produces a fractional cent, the result is rounded to the nearest whole cent using the round-half-up convention (a residual of exactly one half rounds away from zero, upward). Lead times and other day-based durations are whole integers of days; where a day count is derived from a fractional value, the rule for that specific computation (round up to the next whole day, or floor at zero) is stated alongside the computation in §3. The debt-to-income ratio used in financing is the sole non-cent decimal value and is rounded to four decimal places, again using round-half-up.

### 2.8. The Logical Clock

The system does not read wall-clock time. Instead it maintains a single logical clock that drives every time-sensitive computation: material-order ready dates, quote expiry, warranty coverage windows, and install-window gating. At server startup the clock reads exactly `2026-04-01T00:00:00Z`, and before any clock-setting call is made it remains at this default and never falls back to real time. A `PlatformAdmin` may move the clock by supplying a target instant in the `to_iso8601` field; this capability exists for test-driving and is the only way the clock changes. Whenever this document refers to "the current time" or "now," it means the value of this logical clock at the moment the request is processed.

### 2.9. Optimistic Concurrency Control on Quotes

Two customer-facing write operations against a `Quote` are guarded by optimistic concurrency control, because each can change the price the customer is committing to. Both require the request body to carry `expected_quote_version`, which is the `version` of the quote the client last observed. This field is mandatory on these two operations.

When a customer approves a quote, the request must carry `expected_quote_version` equal to the quote's current `version`. A quote that has been reopened and re-issued advances its `version` on each step and thereby changes its firm price; if the supplied `expected_quote_version` does not match the quote's current `version`, the approval is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412), so the customer never approves a price they did not see. Likewise, when a customer accepts a change order, the request must carry `expected_quote_version` equal to the current `version` of the change order's linked quote; if a prior accepted change order has already advanced that quote's `version` under the re-pricing cascade, the supplied value will no longer match and the acceptance is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412). In both cases the rejection is a stale-version rejection: the client is holding an out-of-date view of the quote. Operations not named here do not take a version field.

## 3. Business Logic & Workflows

### 3.1. Customers, Projects, and the Project Lifecycle

A `SalesRep` (or a `PlatformAdmin`) registers a homeowner by supplying their `email`, `full_name`, two-letter `state_code`, and self-reported `annual_income_cents`. The `email` must be non-empty and unique across all customers, the `state_code` must be two uppercase letters (it later affects financing eligibility), and `annual_income_cents` must be zero or greater. A project is then created for that homeowner by supplying the owning `customer_id` and the kitchen's `address_line`; a freshly created project begins life in the `LEAD` state.

The `Project` carries a small set of computed read-only fields that the rest of the workflow populates. Its `status` is one of `LEAD`, `MEASURED`, `QUOTED`, `SOLD`, `IN_PRODUCTION`, `INSTALLED`, `CLOSED`, or `CANCELLED`. The `active_quote_id` is a denormalized pointer to the single non-superseded quote that currently represents the project's price; it is null until the first quote is issued and is discoverable by listing the project's quotes filtered to the active ones. The `linear_feet` and `door_count` fields hold the cabinetry dimensions captured by the project's completed measure and remain null until a measure is completed.

A pre-sale project may be cancelled by a `SalesRep`: this is permitted only while the project's `status` is `LEAD`, `MEASURED`, or `QUOTED`, transitioning it `LEAD → CANCELLED` (the transition is defined out of the pre-sale states and lands the project in `CANCELLED`). Cancellation cancels every measure on the project that is still in the `SCHEDULED` state and marks any active quote as superseded. Cancellation is deliberately restricted to the pre-sale phase; once a project has reached `SOLD` or beyond, it can only be unwound by cancelling its material orders and install jobs (see §3.6 and §3.7). A `Scheduler` closes a project once the work is done: closing is permitted only when the project's `status` is `INSTALLED` and no warranty claim on the project is in either `SUBMITTED` or `APPROVED` status, after which the project moves `INSTALLED → CLOSED` and accepts no further quotes or orders. Listing projects supports optional filters on `customer_id` and `status` alongside the standard `limit` and `offset`.

### 3.2. The In-Home Measure

Before anything can be priced, a `SalesRep` schedules an in-home measure on a project by supplying the appointment instant in `scheduled_for`. A new measure carries the parent `project_id` and starts in `SCHEDULED`; a measure's `status` is one of `SCHEDULED`, `COMPLETED`, or `CANCELLED`. A scheduled measure may simply be cancelled by a `SalesRep`, moving it `SCHEDULED → CANCELLED` with no effect on the project's dimensions.

The decisive event is completing the measure. A `SalesRep` completes a still-`SCHEDULED` measure by submitting the captured `linear_feet`, `door_count`, `door_style`, and `finish_code`. The measure may be completed only when it is in `SCHEDULED`, when the submitted `linear_feet` is greater than zero and the submitted `door_count` is zero or greater, and when the parent project's `status` is `LEAD` or `MEASURED`. The `finish_code` records the selected finish/material family and must be one of `LAMINATE`, `THERMOFOIL`, `WOOD_VENEER`, `SOLID_WOOD`, or `PAINT`; the `door_style` is a free-form style code. On completion the measure transitions `SCHEDULED → COMPLETED`, its captured `linear_feet`, `door_count`, `door_style`, and `finish_code` are persisted, and the measured `linear_feet` and `door_count` are copied onto the parent project's `linear_feet` and `door_count`. If the project was in `LEAD`, completing the measure bubbles it up `LEAD → MEASURED`; this bubble-up increments the project's `version` by one. Measures for a project can be listed (with optional `status`, `limit`, and `offset` filters), and a single measure can be fetched on its own.

### 3.3. Drafting a Quote and the Provisional Estimate

With a completed measure in hand, a `SalesRep` drafts a quote on the project by supplying the `measure_id` of the completed measure and the chosen `scope`, which is one of `PAINT`, `REFACE`, or `REDOOR`. The referenced `measure_id` must belong to a measure whose `project_id` equals the project being quoted; a mismatch is rejected with `ERR_MEASURE_PROJECT_MISMATCH` (HTTP 422). A new quote carries the `project_id` and `measure_id`, starts in the `DRAFT` state, and has its `is_active` flag default to false. A quote's `status` is one of `DRAFT`, `QUOTED`, `REVISING`, `APPROVED`, `SUPERSEDED`, `EXPIRED`, or `DECLINED`.

At draft creation the system computes a deliberately coarse ballpark figure into `estimate_total_cents`. This **provisional estimate** is forward-looking and intentionally ignores both `door_count` and the finish multiplier — those enter only the firm quote. It is computed from the linked completed measure alone: a single blended per-linear-foot rate for the chosen scope is multiplied by the measure's `linear_feet`, and the product is rounded half-up to whole cents. The blended rate is 12,000 cents per linear foot for `PAINT`, 28,000 cents per linear foot for `REFACE`, and 45,000 cents per linear foot for `REDOOR`. The resulting `estimate_total_cents` is always zero or greater.

The firm price field `firm_total_cents`, the frozen `addons_total_cents` (which defaults to 0), and the `expires_at` instant remain unset on a draft and are populated only when the quote is issued. Quotes for a project may be listed (with optional `status`, `is_active`, `limit`, and `offset` filters), and quotes may also be listed across the system filterable by `measure_id` or `project_id`. Any of these read paths, as well as fetching a single quote, will lazily expire a quote (see §3.5).

### 3.4. Issuing the Firm Quote

A `SalesRep` issues a quote to turn the draft into a binding price. Issuance is the transition `DRAFT → QUOTED`, and it is also the transition `REVISING → QUOTED` that closes the revision loop described in §3.5. In either direction, issuance is permitted only when the linked measure's `status` is `COMPLETED`; an attempt to issue against a measure that is not completed is rejected with `ERR_MEASURE_NOT_COMPLETED` (HTTP 409). From `DRAFT`, issuance additionally requires that the quote currently be in `DRAFT` and that the project's `status` be `MEASURED` or `QUOTED`; from `REVISING`, it requires the quote to currently be in `REVISING`.

Issuance computes the **firm quote total** into `firm_total_cents` and pins its evaluation order precisely. First, a labor base is formed by multiplying the per-foot labor rate for the scope by the measure's `linear_feet`. Second, a door-labor amount is formed by multiplying the per-door labor rate for the scope by the measure's `door_count`. Third, those two are added to form a pre-finish subtotal. Fourth, the finish multiplier for the measure's `finish_code` is selected. Fifth, a materials charge is computed as the pre-finish subtotal multiplied by the finish multiplier minus one, rounded half-up to whole cents. Sixth, the subtotal is the pre-finish amount plus that materials charge. Seventh, a volume-discount percentage is selected from the subtotal tier. Eighth, the discount is the subtotal multiplied by that percentage, rounded half-up to whole cents. Ninth, `firm_total_cents` is the subtotal minus the discount, plus the quote's `addons_total_cents`. The rounding order is pinned: the materials charge (fifth step) and the discount (eighth step) are each rounded to whole cents independently before being combined — round per component, then sum, never a single rounding at the end. The resulting `firm_total_cents` is always zero or greater.

The per-foot labor rate is 9,000 cents for `PAINT`, 20,000 cents for `REFACE`, and 30,000 cents for `REDOOR`. The per-door labor rate is 1,500 cents for `PAINT`, 4,000 cents for `REFACE`, and 7,000 cents for `REDOOR`. The finish multiplier is 1.00 for `PAINT`, 1.10 for `LAMINATE`, 1.15 for `THERMOFOIL`, 1.25 for `WOOD_VENEER`, and 1.40 for `SOLID_WOOD`. The volume discount is zero when the subtotal is below 1,500,000 cents; it is 5 percent when the subtotal is at least 1,500,000 cents but below 3,000,000 cents; and it is 10 percent when the subtotal is at least 3,000,000 cents. Because the firm computation brings in the door term, the finish multiplier, the tiered discount, and approved add-ons, it will generally diverge from the provisional estimate even on identical measure data.

Issuance also has several bookkeeping effects. It sets `expires_at` to the current time plus the quote-validity window of 30 days. It marks this quote's `is_active` flag true and marks any prior active quote on the same project as `SUPERSEDED` with its `is_active` cleared to false. It sets the project's `active_quote_id` to this quote's `id`. If the project's `status` is `MEASURED`, issuance bubbles the project up `MEASURED → QUOTED`. Every issuance increments the quote's `version` by one. A re-issue from `REVISING` recomputes `firm_total_cents` by the same pinned procedure and resets `expires_at` to the current time plus 30 days.

### 3.5. The Approval, Decline, Reopen, and Expiry Cycle

A `Customer` who owns the project approves the active quote to commit to the work. Approval is the transition `QUOTED → APPROVED` and is permitted only when the quote is in `QUOTED`, its `is_active` flag is true, the current time is strictly before its `expires_at`, the acting customer owns the parent project, and the supplied `expected_quote_version` matches the quote's current `version` per §2.9. If the quote's `expires_at` has already passed, the quote is treated as expired and approval is rejected with `ERR_QUOTE_EXPIRED` (HTTP 409). On a successful approval the project bubbles up `QUOTED → SOLD`, the quote's `addons_total_cents` is frozen at the sum of the `APPROVED` add-ons currently attached to it, and the quote's `version` increments by one.

A `Customer` who owns the project may instead decline the active quote, moving it `QUOTED → DECLINED`; declining requires the quote to be in `QUOTED` and the acting customer to own the parent project. Declining clears the quote's `is_active` flag and clears the project's `active_quote_id` if it pointed at this quote.

A `SalesRep` reopens a `QUOTED` quote to revise it, moving it `QUOTED → REVISING`; reopening requires the quote to be in `QUOTED` with its `is_active` flag true and increments the quote's `version` by one. While in `REVISING` the salesperson edits scope or add-ons and then re-issues the quote (`REVISING → QUOTED` per §3.4), closing the revision loop. Because each reopen and each re-issue advances the quote's `version`, a customer who read the quote before a revision cycle and then tries to approve with the old version will be turned away on the stale-version check described in §2.9.

Quote expiry is evaluated lazily. A quote in `QUOTED` whose `expires_at` is at or before the current time is treated as `EXPIRED`: the system marks it `EXPIRED`, clears its `is_active` flag, and clears the project's `active_quote_id` if it pointed at this quote. This lazy expiry is applied whenever a quote is read — when fetching the project, when fetching the quote itself, or when listing quotes — and whenever a transition on the quote is attempted.

### 3.6. Add-Ons: Hardware and Countertops

A `SalesRep` proposes an add-on against a quote by supplying its `kind` — either `HARDWARE` or `COUNTERTOP` — together with a `unit_price_cents` and a `quantity`. For `HARDWARE` the unit price is per knob or pull and the quantity is the knob/pull count; for `COUNTERTOP` the unit price is per square foot and the quantity is the number of square feet. The `unit_price_cents` must be zero or greater and the `quantity` must be strictly greater than zero. A new add-on carries the parent `quote_id`, starts in the `PROPOSED` state, and has its extended `price_cents` computed immediately as the `unit_price_cents` multiplied by the `quantity`, rounded half-up to whole cents; this value is always zero or greater. An add-on's `status` is one of `PROPOSED`, `APPROVED`, or `REMOVED`.

A `SalesRep` approves a proposed add-on, moving it `PROPOSED → APPROVED`, so that it counts toward the firm quote total; an approved add-on's `price_cents` is folded into the quote's `addons_total_cents` the next time the quote is issued. A `SalesRep` may also remove an add-on, moving it to `REMOVED`. Add-ons for a quote can be listed with optional `status`, `limit`, and `offset` filters. Note that the quote's `addons_total_cents` is the already-rounded sum of the per-add-on extended prices, and that this sum is frozen onto the quote at approval time (§3.5).

### 3.7. Change Orders and the Re-Pricing Cascade

After a project is sold, scope can still shift. A `SalesRep` raises a change order against an `APPROVED` quote by supplying a signed `delta_linear_feet` (for example, +2.0 adds two feet of cabinetry; both deltas default to 0), a signed `delta_door_count`, and a `rush` flag (default false) indicating the customer is willing to pay a surcharge to compress the added lead time. A new change order carries the parent `quote_id` and starts in the `PENDING` state; its `status` is one of `PENDING`, `ACCEPTED`, or `REJECTED`. A `Customer` who owns the project may reject a pending change order, moving it `PENDING → REJECTED` with no price or lead-time change.

The consequential path is acceptance. A `Customer` who owns the project accepts a change order, moving it `PENDING → ACCEPTED`. Acceptance is permitted only when the change order is in `PENDING`, the linked quote's `status` is `APPROVED`, the project's `status` is `SOLD` or `IN_PRODUCTION`, the acting customer owns the parent project, and the supplied `expected_quote_version` matches the linked quote's current `version` per §2.9.

On acceptance the system computes the signed `price_delta_cents` and the non-negative `lead_time_delta_days` from the change order's deltas, priced at the same scope rates as the firm quote. The price delta is built as follows: a foot-delta amount is the per-foot labor rate for the quote's scope multiplied by `delta_linear_feet`; a door-delta amount is the per-door labor rate for the quote's scope multiplied by `delta_door_count`; those two are summed into a raw delta; the finish multiplier for the measure's `finish_code` is then applied to the raw delta; and `price_delta_cents` is that product rounded half-up to whole cents. This delta is applied on top of the already-discounted firm total — there is no re-discounting of the change-order delta.

The lead-time delta is built separately. Every positive linear-foot increment adds 2 days per foot, taking the larger of `delta_linear_feet` and zero, rounding that foot count up to a whole number, and multiplying by 2; a door-only change adds a flat 3 days when `delta_door_count` is greater than zero, and 0 otherwise. These two contributions are summed into a base lead amount. When `rush` is true, the added lead time is the base lead amount multiplied by the rush factor of 0.5 and then rounded up to a whole number of days, compressing the schedule impact at a rush surcharge; when `rush` is false, the added lead time is the base lead amount unchanged. The resulting `lead_time_delta_days` is floored at zero and is always a whole number of days. Rush affects only the lead time, never the price delta.

Acceptance then drives a three-hop cascade, each hop conditional on the prior one. **Hop one:** the accepted change order re-prices the quote — `price_delta_cents` is added to the project price by recomputing the quote's `firm_total_cents` — and the quote's `version` increments by one. **Hop two:** if a material order for this quote exists and is in `PLACED` or `READY`, the `lead_time_delta_days` is added to that order's `lead_extension_days` and its `ready_at` is recomputed. **Hop three:** if an install job references that material order, is in `SCHEDULED`, and its `window_start` falls before the newly recomputed `ready_at`, that install job is transitioned `SCHEDULED → CANCELLED` and the project is reverted `IN_PRODUCTION → SOLD`. Because acceptance advances the quote's `version`, a second acceptance still carrying the pre-cascade `expected_quote_version` operates on a stale view of the quote and is rejected on the version check with `ERR_STALE_QUOTE_VERSION` (HTTP 412); this version bump is the intended serialization point between successive change-order acceptances. Change orders for a quote can be listed with optional `status`, `limit`, and `offset` filters.

### 3.8. Placing and Progressing the Material Order

Once a project is `SOLD`, a `Scheduler` places a material order to start production, supplying the `quote_id` of the quote to fulfill. The referenced quote must be `APPROVED` and `is_active` on the same project; otherwise the request is rejected with `ERR_QUOTE_NOT_APPROVED` (HTTP 409). Placing the order requires the project's `status` to be `SOLD` and creates the material order in the `PLACED` state carrying the parent `project_id` and the `quote_id`. A material order's `status` is one of `PLACED`, `READY`, `RECEIVED`, or `CANCELLED`. Placement bubbles the project up `SOLD → IN_PRODUCTION` and increments the project's `version` by one.

At placement the system computes the order's `base_lead_time_days` from the finish family and scope plus a volume step. The base is keyed on the measure's `finish_code`: 7 days for `PAINT`, 14 days for `LAMINATE`, 21 days for `THERMOFOIL`, 28 days for `WOOD_VENEER`, and 42 days for `SOLID_WOOD`. A scope surcharge is added on top: 0 days for `PAINT`, 5 days for `REFACE`, and 10 days for `REDOOR`. Finally, a volume step of 7 days is added when the measure's `linear_feet` is at least 30 (large jobs ship in two batches), and 0 otherwise; `base_lead_time_days` is the sum of these three contributions and is always zero or greater. The order's `lead_extension_days` starts at 0 and accrues the accepted change-order lead deltas described in §3.7; it is always zero or greater. The `ready_at` instant — the earliest possible install date — is the clock value at placement plus `base_lead_time_days` plus `lead_extension_days`, added as whole UTC days, and is recomputed whenever the extension grows.

A `Scheduler` marks an order ready, moving it `PLACED → READY`, but only once the current time is at or after the order's `ready_at`; an attempt to mark ready before the lead time has elapsed is rejected with `ERR_LEAD_TIME_NOT_ELAPSED` (HTTP 409). A `Scheduler` marks a ready order received, moving it `READY → RECEIVED`. A `Scheduler` may cancel a `PLACED` order, moving it `PLACED → CANCELLED`, but only when no install job referencing this order is in `SCHEDULED`, `IN_PROGRESS`, or `DONE`; cancelling reverts the project `IN_PRODUCTION → SOLD` if it was in production. Material orders can be listed per project (optional `status`, `limit`, `offset`) and across the system filterable by `quote_id`.

### 3.9. Crews and Install Scheduling

A `Scheduler` registers an install crew with a display `name`, a `daily_job_capacity` (the maximum number of install jobs the crew can be booked for on a single calendar day, which must be at least 1), a non-empty `skill_finishes` array listing the `finish_code` values the crew is certified to install, and an optional `is_active` flag that defaults to true and controls whether the crew accepts new bookings. Crews can be fetched individually and listed with an optional `is_active` filter.

A `Scheduler` schedules an install job on a project by supplying the `material_order_id` whose `ready_at` gates scheduling, the `crew_id` of the assigned crew, and the install window bounded by `window_start` (inclusive) and `window_end` (exclusive). A new install job carries the parent `project_id` and starts in the `SCHEDULED` state; its `status` is one of `SCHEDULED`, `IN_PROGRESS`, `DONE`, or `CANCELLED`. The system derives an `install_day` — the calendar date in `YYYY-MM-DD` UTC form taken from `window_start` — which is used for crew day-capacity counting.

Scheduling enforces a series of checks. The assigned crew must be active and certified for the project's `finish_code` (that is, the measure's `finish_code` must appear in the crew's `skill_finishes`); a crew that is inactive or uncertified yields `ERR_CREW_NOT_CERTIFIED` (HTTP 422). The `window_start` must be at or after the linked material order's `ready_at` — installation cannot begin before materials arrive — and an earlier start yields `ERR_WINDOW_BEFORE_READY` (HTTP 409). The proposed window, treated as the half-open interval from `window_start` up to but not including `window_end`, must not overlap any non-`CANCELLED` install job already booked for the same crew; an overlap yields `ERR_CREW_WINDOW_CONFLICT` (HTTP 409). The number of non-`CANCELLED` install jobs already booked for that crew on the same `install_day` must remain below the crew's `daily_job_capacity` — once the count reaches capacity, the next booking is blocked with `ERR_CREW_DAY_FULL` (HTTP 409). Finally, `window_end` must be strictly greater than `window_start`, or the request is rejected with `ERR_INVALID_WINDOW` (HTTP 422). Install jobs can be listed per project (optional `status`, `limit`, `offset`) and across the system filterable by `crew_id` or `material_order_id`.

### 3.10. Running the Install and Reaching Installed

An `InstallCrew` starts a scheduled job, moving it `SCHEDULED → IN_PROGRESS`, which is permitted only when the job is in `SCHEDULED`, the linked material order is in `READY` or `RECEIVED`, and the current time is at or after the job's `window_start`. The crew then completes the job, moving it `IN_PROGRESS → DONE`, which is permitted only when the job is in `IN_PROGRESS`. Completion transitions the linked material order `READY → RECEIVED` if it is still in `READY`, bubbles the project up `IN_PRODUCTION → INSTALLED`, records the install-completion clock instant for the warranty window, and increments the project's `version` by one.

A `Scheduler` may cancel a scheduled job, moving it `SCHEDULED → CANCELLED`; cancellation is permitted only when the job is in `SCHEDULED` and reverts the project `IN_PRODUCTION → SOLD` if it was in production. (As noted in §3.7, the change-order cascade can also cancel a scheduled job and revert the project automatically.) A single install job can be fetched on its own.

### 3.11. Warranty Claims

Once a project is `INSTALLED`, the homeowner is under warranty. A `Customer`, `SalesRep`, or `PlatformAdmin` submits a warranty claim against a project by supplying a `description` of the defect. A claim may be submitted only for a project that is `INSTALLED` or `CLOSED`; an attempt against any other project state — or any warranty action invalid for the claim's current state — is rejected with `ERR_OUT_OF_WARRANTY` (HTTP 409). A new claim carries the parent `project_id`, starts in the `SUBMITTED` state, and records `filed_at` as the current logical-clock instant. Its `status` is one of `SUBMITTED`, `APPROVED`, `DENIED`, or `RESOLVED`. At submission the system sets the `covered` flag: a claim is covered when the current time is at or before the install-completion instant plus the warranty window of 90 days, and uncovered otherwise.

A `PlatformAdmin` adjudicates a submitted claim by supplying a `decision`. A decision to approve moves the claim `SUBMITTED → APPROVED` but is allowed only when the claim's `covered` flag is true; approving a claim whose `covered` flag is false (it falls outside the warranty window) is rejected with `ERR_WARRANTY_NOT_COVERED` (HTTP 409). A decision to deny moves the claim `SUBMITTED → DENIED`. A `PlatformAdmin` then resolves an approved claim, moving it `APPROVED → RESOLVED`. Recall from §3.1 that an open claim — one in `SUBMITTED` or `APPROVED` — blocks the project from being closed. Warranty claims can be listed per project (optional `status`, `limit`, `offset`) and fetched individually.

### 3.12. Consumer Financing

A `Customer`, `SalesRep`, or `PlatformAdmin` applies for financing on a project by supplying the applicant's `customer_id`, the requested `amount_cents`, and the requested `term_months`. The applicant must own the project; the `amount_cents` must be strictly greater than zero; and `term_months` must be one of 12, 24, 36, 48, or 60. A new application carries the parent `project_id` and the `customer_id`, and starts in the `SUBMITTED` state; its `status` is one of `SUBMITTED`, `APPROVED`, or `DECLINED`.

At submission the system computes the amortized `monthly_payment_cents` and the `dti_ratio`. The annual percentage rate is chosen by term: 3.99 percent for a 12-month term, 5.99 percent for 24 months, 7.99 percent for 36 months, 9.99 percent for 48 months, and 11.99 percent for 60 months. The monthly rate is that annual rate divided by twelve. When the monthly rate is zero, the monthly payment is the `amount_cents` divided by the number of months, rounded half-up to whole cents. Otherwise the standard amortization factor is computed — the monthly rate multiplied by one plus the monthly rate raised to the power of the term, divided by the quantity one plus the monthly rate raised to the power of the term minus one — and `monthly_payment_cents` is the `amount_cents` multiplied by that factor, rounded half-up to whole cents; it is always zero or greater. The `dti_ratio` is the `monthly_payment_cents` multiplied by twelve and divided by the applicant's `annual_income_cents`, rounded to four decimal places (round-half-up); it is always zero or greater.

A `PlatformAdmin` approves a submitted application, moving it `SUBMITTED → APPROVED`, but only when the `dti_ratio` is at most 0.20; an approval attempt where the `dti_ratio` exceeds 0.20 is rejected with `ERR_DTI_EXCEEDED` (HTTP 422). A `PlatformAdmin` may instead decline a submitted application, moving it `SUBMITTED → DECLINED`. Financing applications can be listed per project (optional `status`, `limit`, `offset`) and across the system filterable by `customer_id`.

### 3.13. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed order so that the most fundamental failures surface first. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then the role-permission check (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource id resolved left-to-right in the path (`ERR_NOT_FOUND`), then — for customer-scoped operations — project ownership (`ERR_NOT_PROJECT_OWNER`). Domain-specific referential and state checks follow: for quote creation, the measure-project match (`ERR_MEASURE_PROJECT_MISMATCH`) is checked; for any transition, that the target entity is in a state from which the transition is defined (`ERR_INVALID_STATE`); for issuance, that the measure is completed (`ERR_MEASURE_NOT_COMPLETED`); for approval, that the quote has not expired (`ERR_QUOTE_EXPIRED`); for material-order placement, that the quote is approved and active (`ERR_QUOTE_NOT_APPROVED`); for marking ready, that the lead time has elapsed (`ERR_LEAD_TIME_NOT_ELAPSED`). Install scheduling layers its own checks — crew certification (`ERR_CREW_NOT_CERTIFIED`), window-before-ready (`ERR_WINDOW_BEFORE_READY`), crew window conflict (`ERR_CREW_WINDOW_CONFLICT`), crew day-capacity (`ERR_CREW_DAY_FULL`), and window validity (`ERR_INVALID_WINDOW`). Warranty submission enforces the warranty window (`ERR_OUT_OF_WARRANTY`) and financing approval enforces the debt-to-income ceiling (`ERR_DTI_EXCEEDED`). General body-shape validation — required fields present, enum values in range, and numeric constraints such as `quantity` greater than zero and `term_months` in its allowed set — is reported as `ERR_INVALID_REQUEST` (HTTP 422). The optimistic-concurrency stale-version check on approval and change-order acceptance is reported as `ERR_STALE_QUOTE_VERSION` (HTTP 412), as described in §2.9.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify or transition an existing resource, including state-changing actions and the clock-setting capability, return `200 OK`. All endpoints are mounted at the API root. To reconstruct the full request body and side effects of any endpoint, refer to the workflow narratives in §3; the table below lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a homeowner | SalesRep, PlatformAdmin |
| GET | `/customers/{id}` | Fetch a customer | SalesRep, PlatformAdmin, Customer |
| POST | `/projects` | Create a kitchen-refresh project in LEAD | SalesRep, PlatformAdmin |
| GET | `/projects/{id}` | Fetch a project with computed posture and dimensions | SalesRep, Scheduler, PlatformAdmin, Customer |
| GET | `/projects` | List projects (paginated), optionally filtered by customer | SalesRep, Scheduler, PlatformAdmin |
| POST | `/projects/{id}/cancel` | Cancel a pre-sale project | SalesRep, PlatformAdmin |
| POST | `/projects/{id}/close` | Close an INSTALLED project | Scheduler, PlatformAdmin |
| POST | `/projects/{id}/measures` | Schedule an in-home measure appointment | SalesRep, PlatformAdmin |
| GET | `/projects/{id}/measures` | List measures for a project | SalesRep, Scheduler, PlatformAdmin, Customer |
| GET | `/measures/{id}` | Fetch a measure | SalesRep, Scheduler, PlatformAdmin, Customer |
| POST | `/projects/{id}/measures/{id}/complete` | Complete the measure with captured dimensions, style and finish | SalesRep, PlatformAdmin |
| POST | `/projects/{id}/measures/{id}/cancel` | Cancel a scheduled measure | SalesRep, PlatformAdmin |
| POST | `/projects/{id}/quotes` | Create a DRAFT quote with a provisional estimate | SalesRep, PlatformAdmin |
| GET | `/projects/{id}/quotes` | List quotes for a project | SalesRep, Scheduler, PlatformAdmin, Customer |
| GET | `/quotes` | List quotes, filterable by measure or project | SalesRep, Scheduler, PlatformAdmin |
| GET | `/quotes/{id}` | Fetch a quote with provisional and firm totals | SalesRep, Scheduler, PlatformAdmin, Customer |
| POST | `/quotes/{id}/issue` | Issue or re-issue the firm quote | SalesRep, PlatformAdmin |
| POST | `/quotes/{id}/reopen` | Reopen a QUOTED quote for revision | SalesRep, PlatformAdmin |
| POST | `/quotes/{id}/approve` | Customer approves the active QUOTED quote | Customer |
| POST | `/quotes/{id}/decline` | Customer declines the active QUOTED quote | Customer |
| POST | `/quotes/{id}/addons` | Propose a hardware or countertop add-on on a quote | SalesRep, PlatformAdmin |
| GET | `/quotes/{id}/addons` | List add-ons for a quote | SalesRep, Scheduler, PlatformAdmin, Customer |
| POST | `/addons/{id}/approve` | Approve a proposed add-on | SalesRep, PlatformAdmin |
| POST | `/addons/{id}/remove` | Remove an add-on | SalesRep, PlatformAdmin |
| POST | `/quotes/{id}/change-orders` | Raise a change order against an APPROVED quote | SalesRep, PlatformAdmin |
| GET | `/quotes/{id}/change-orders` | List change orders for a quote | SalesRep, Scheduler, PlatformAdmin, Customer |
| GET | `/change-orders/{id}` | Fetch a change order | SalesRep, Scheduler, PlatformAdmin, Customer |
| POST | `/change-orders/{id}/accept` | Customer accepts a change order | Customer |
| POST | `/change-orders/{id}/reject` | Customer rejects a change order | Customer |
| POST | `/projects/{id}/material-orders` | Place a material order against an APPROVED quote | Scheduler, PlatformAdmin |
| GET | `/projects/{id}/material-orders` | List material orders for a project | SalesRep, Scheduler, PlatformAdmin, Customer |
| GET | `/material-orders/{id}` | Fetch a material order with computed ready_at | SalesRep, Scheduler, PlatformAdmin, Customer |
| GET | `/material-orders` | List material orders, filterable by quote | SalesRep, Scheduler, PlatformAdmin |
| POST | `/material-orders/{id}/mark-ready` | Mark materials ready once lead time elapsed | Scheduler, PlatformAdmin |
| POST | `/material-orders/{id}/receive` | Mark materials received | Scheduler, PlatformAdmin |
| POST | `/material-orders/{id}/cancel` | Cancel a PLACED material order | Scheduler, PlatformAdmin |
| POST | `/crews` | Register an install crew | Scheduler, PlatformAdmin |
| GET | `/crews/{id}` | Fetch a crew | Scheduler, PlatformAdmin |
| GET | `/crews` | List crews | Scheduler, PlatformAdmin |
| POST | `/projects/{id}/install-jobs` | Schedule an install window with a crew | Scheduler, PlatformAdmin |
| GET | `/projects/{id}/install-jobs` | List install jobs for a project | SalesRep, Scheduler, PlatformAdmin, Customer |
| GET | `/install-jobs/{id}` | Fetch an install job | SalesRep, Scheduler, PlatformAdmin, Customer, InstallCrew |
| GET | `/install-jobs` | List install jobs, filterable by crew or material order | Scheduler, PlatformAdmin, InstallCrew |
| POST | `/install-jobs/{id}/start` | Crew starts the install | InstallCrew, PlatformAdmin |
| POST | `/install-jobs/{id}/complete` | Crew completes the install | InstallCrew, PlatformAdmin |
| POST | `/install-jobs/{id}/cancel` | Scheduler cancels a scheduled install | Scheduler, PlatformAdmin |
| POST | `/projects/{id}/warranty-claims` | Submit a warranty claim on an installed project | Customer, SalesRep, PlatformAdmin |
| GET | `/projects/{id}/warranty-claims` | List warranty claims for a project | Customer, SalesRep, Scheduler, PlatformAdmin |
| GET | `/warranty-claims/{id}` | Fetch a warranty claim | Customer, SalesRep, Scheduler, PlatformAdmin |
| POST | `/warranty-claims/{id}/adjudicate` | Approve or deny a submitted warranty claim | PlatformAdmin |
| POST | `/warranty-claims/{id}/resolve` | Mark an approved warranty claim resolved | PlatformAdmin |
| POST | `/projects/{id}/financing-applications` | Customer applies for financing on their project | Customer, SalesRep, PlatformAdmin |
| GET | `/projects/{id}/financing-applications` | List financing applications for a project | Customer, SalesRep, PlatformAdmin |
| GET | `/financing-applications/{id}` | Fetch a financing application with monthly payment and DTI | Customer, SalesRep, PlatformAdmin |
| GET | `/financing-applications` | List financing applications, filterable by customer | SalesRep, PlatformAdmin |
| POST | `/financing-applications/{id}/approve` | Approve a financing application | PlatformAdmin |
| POST | `/financing-applications/{id}/decline` | Decline a financing application | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_PROJECT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEASURE_PROJECT_MISMATCH` | 422 |
| `ERR_MEASURE_NOT_COMPLETED` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_QUOTE_NOT_APPROVED` | 409 |
| `ERR_STALE_QUOTE_VERSION` | 412 |
| `ERR_LEAD_TIME_NOT_ELAPSED` | 409 |
| `ERR_CREW_NOT_CERTIFIED` | 422 |
| `ERR_WINDOW_BEFORE_READY` | 409 |
| `ERR_CREW_WINDOW_CONFLICT` | 409 |
| `ERR_CREW_DAY_FULL` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_OUT_OF_WARRANTY` | 409 |
| `ERR_DTI_EXCEEDED` | 422 |
| `ERR_WARRANTY_NOT_COVERED` | 409 |
