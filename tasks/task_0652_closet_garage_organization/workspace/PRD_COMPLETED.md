# Closet & Garage Organization API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Closet & Garage Organization platform — a system that orchestrates the full journey of a custom-built storage installation, from the first in-home design consultation through 3D rendering, space measurement, component configuration, quoting, deposit, manufacture, install scheduling, change orders, warranty service, and consumer financing. The business resembles a premium build-to-order operation (in the style of California Closets): a customer's space is measured, a designer fits a configuration of shelves, drawers, rods, cabinets, panels, and accessories to that space, a priced estimate is produced, and — once a deposit is paid — the order is manufactured to a promised lead time and installed by a regional crew.

The platform must reconcile two distinct concerns that pull in opposite directions. On one side is a strict workflow: a project advances through a compound lifecycle that is *auto-derived* from the states of its children, so that issuing a quote, capturing a deposit, completing manufacturing, or finishing an install each nudge the parent project forward without a separate client request on the project itself. On the other side is a pricing-and-accounting engine: quotes are priced through tiered material multipliers, volume discounts, stacked promotions, and regional tax; deposits, financing, change orders, and install completion each trigger a recomputation of what the customer still owes. Because several actors (customers, designers, schedulers, manufacturing operators, and platform administrators) act on overlapping resources, the system uses optimistic concurrency control at two sensitive write points to prevent a stale view from overwriting an advance it never observed.

The remainder of this document defines the global contract (authentication, response envelopes, pagination, concurrency, precision, and cross-cutting consistency rules) in Section 2, the domain workflows and business logic in Section 3, the endpoint surface in Section 4, and the catalogue of error codes in Section 5.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request other than customer self-registration must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The single exception is customer registration, which is performed anonymously and requires no headers.

The system recognizes six roles, spelled exactly as follows: `Anonymous`, `Customer`, `Designer`, `Scheduler`, `ManufacturingOps`, and `PlatformAdmin`. Once a request is authenticated, the platform checks that the acting role is permitted to perform the requested operation; if it is not, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The `Customer` role is **entity-backed**: when `X-User-Role` is `Customer`, the value of `X-User-ID` is the `id` of the acting `Customer` record. Ownership checks on any resource that ultimately belongs to a project compare the project's `customer_id` to `X-User-ID`; if the acting customer does not own the target project, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership rule guards the customer-only operations — cancelling a project, accepting a quote, requesting an install reschedule, submitting a financing application, opening a financing application, and (when a `Customer` rather than a `PlatformAdmin` is acting) creating a deposit — as well as any read on a resource the customer owns.

The remaining roles all carry **opaque** identities. When `X-User-Role` is `Designer`, `Scheduler`, `ManufacturingOps`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The one place such an identifier is recorded is the `designer_user_id` captured on a design consult: when a designer schedules a consult, the operator id who runs it is written onto that record, but it is stored, never matched against a `Customer` or any other entity. The `Anonymous` role is likewise opaque and may only register a customer.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. Unless a specific endpoint says otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order, with ties (records sharing the same `created_at`) broken by `id` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. All of the platform's entities — `Customer`, `Project`, `DesignConsult`, `SpaceMeasure`, `ComponentConfig`, `Quote`, `Deposit`, `ManufactureOrder`, `Crew`, `InstallJob`, `ChangeOrder`, `WarrantyClaim`, and `FinancingApplication` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. The `version` begins at its initial value of 1 when the resource is created and increments by one on every mutation of that resource, including mutations driven indirectly by a cascade rather than by a direct client request. Whenever a derived field such as a project's `status` or `balance_due_cents` is recomputed, that recomputation is a mutation of the owning resource: it refreshes `updated_at` and increments `version`.

### 2.5. Hierarchical Consistency and Compound Project State

A `Project` is a **compound** resource: its `status` is not set directly by clients but auto-advances as its children change state. The lifecycle runs `LEAD` → `DESIGNING` → `QUOTED` → `DEPOSIT_PAID` → `IN_MANUFACTURE` → `READY_TO_INSTALL` → `INSTALLING` → `COMPLETED`, with `CANCELLED` as an alternate terminal outcome. Each auto-advance is itself a mutation of the project that refreshes its `updated_at` and increments its `version`. The specific child events that drive each advance — the first design consult, the first issued quote, the deposit capture, the manufacture start and complete, the install start and complete — are detailed in Section 3, and each is recorded there alongside the precise side effects it triggers on the project.

Several operations cascade across more than one entity in a single call. When such a cascade fires, every affected entity is mutated, and each mutation independently refreshes that entity's `updated_at` and increments its `version`. The deepest cascades in the system run three entities deep — for example, completing an install resolves the install job, then the manufacture order, then the project. The complete set of cascades and their secondary effects is specified in the workflows of Section 3; the governing rule here is simply that no cascade is silent: each touched resource is versioned.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many endpoints address resources through a path that contains a parent identifier followed by a child collection — for example, the design consults, space measures, component configs, and quotes that hang off a specific project. For any such request, identifiers are resolved left to right: the parent in the path is verified first, and only then is the child or collection resolved within it. The first identifier in the path that does not resolve causes the request to fail with `ERR_RESOURCE_NOT_FOUND` (HTTP 404). The same existence check applies to foreign-key references supplied in a request body; path identifiers are validated before body references. Existence checking follows the authentication and authorization checks described in Section 2.1.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation calls for rounding, the system uses the **round half up** method, applied to the nearest whole cent. Several pricing formulas round at more than one intermediate step; the *order* in which those rounding steps occur is significant and is pinned in the formula descriptions in Section 3 — implementers must round at exactly the points described and not defer rounding to the end. Lead-time figures are whole integer days, unit counts are whole integers, and warranty coverage is computed as a boolean over UTC day arithmetic.

### 2.8. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, because each acts against a parent whose `version` may have advanced — legitimately, via another operator's action — since the client last read it.

Applying an approved change order accepts an `expected_project_version` field in the request body carrying the client's last observed `version` of the target `Project`. When that field is present and its value does not equal the project's current `version`, the apply is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412); when the field is omitted (or null), the optimistic-concurrency check is skipped and the apply proceeds. This protects against applying a change order on top of a project whose accepted quote or balance has already moved — for instance, a prior change-order apply, a deposit capture, or a financing funding event will have bumped the project's `version`, making the current applier's view stale; the client must re-read the project before re-applying.

Capturing a deposit accepts an `expected_quote_version` field in the request body carrying the client's last observed `version` of the `Quote` being deposited against. When that field is present and its value does not equal the quote's current `version`, the capture is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412); when the field is omitted (or null), the optimistic-concurrency check is skipped and the capture proceeds. A change-order apply may have moved the quote from `ACCEPTED` to `SUPERSEDED` in the interim, so a capture that carries the prior quote version is operating on a stale view and must be refused.

No other endpoint takes a version field; concurrency control is confined to these two operations.

### 2.9. Regional Bucketing

Every customer is assigned to one of four regions — `NORTH`, `SOUTH`, `EAST`, or `WEST` — derived from the first digit of their `zip_code`. A first digit of 0, 1, or 2 maps to `NORTH`; 3 or 4 maps to `SOUTH`; 5 or 6 maps to `EAST`; and 7, 8, or 9 maps to `WEST`. This region drives two downstream rules: the tax rate applied to a quote, and the requirement that an install crew serve the same region as the project. The region is captured on the customer as `install_region` and copied onto each project at creation, also as `install_region`.

### 2.10. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication is checked first: presence and validity of the headers (`ERR_UNAUTHENTICATED`), then role permission for the operation (`ERR_FORBIDDEN_ROLE`), then, for customer-owned operations, resource ownership (`ERR_NOT_RESOURCE_OWNER`). Next, the existence of every referenced resource is confirmed, path identifiers before body foreign keys (`ERR_RESOURCE_NOT_FOUND`). Then the target resource's current state is checked against the requested transition (`ERR_INVALID_STATE`), followed by the optimistic-concurrency version checks on the two guarded writes (`ERR_STALE_PROJECT_VERSION`, then `ERR_STALE_QUOTE_VERSION`). Only after these structural checks pass does the system evaluate the domain-specific business rules — region matching, measure confirmation, lead-time gates, scheduling-window validity, quote expiry, crew capacity, warranty coverage and branch matching, deposit floors, financing limits, configuration finalization, and change-target validity — with malformed-body schema validation (`ERR_VALIDATION`) as the final family. Where two business rules could both apply to a request, the body-shape and target-validity checks are considered before the conflict-state business checks they depend on; the per-operation narratives in Section 3 state the relevant conditions alongside the workflow they guard.

## 3. Business Logic & Workflows

### 3.1. Customers, Projects, and the Compound Lifecycle

A customer joins the platform through self-registration, supplying an `email`, a `full_name`, and a `zip_code`. The `email` must be non-empty and unique without regard to letter case, and the `zip_code` must be a five-digit string. From the `zip_code`, the system computes the customer's `install_region` using the regional bucketing rule of Section 2.9.

With a customer on file, a project is opened by supplying the `customer_id` of the owning customer and a `room_type`, which is one of `REACH_IN_CLOSET`, `WALK_IN_CLOSET`, `GARAGE`, `PANTRY`, or `HOME_OFFICE`. A new project starts in status `LEAD`, copies the customer's region into its own `install_region`, and begins with `accepted_quote_id` and `financing_application_id` both null and `balance_due_cents` at zero. The project's `accepted_quote_id` is later set to the quote whose deposit is captured; its `financing_application_id` is set when a financing application is funded; and its `balance_due_cents` is the live amount the customer still owes, recomputed on deposit, financing, change-order, and install-completion events as described throughout this section.

The project's `status` advances automatically as work proceeds. Scheduling the first design consult for a project that is still `LEAD` advances it to `DESIGNING`. Issuing the project's first quote, while the project is `DESIGNING`, advances it to `QUOTED`. Capturing the deposit on the accepted quote, while the project is `QUOTED`, advances it to `DEPOSIT_PAID`. Starting production on the manufacture order, while the project is `DEPOSIT_PAID`, advances it to `IN_MANUFACTURE`. Completing the manufacture order, while the project is `IN_MANUFACTURE`, advances it to `READY_TO_INSTALL`. Starting the install, while the project is `READY_TO_INSTALL`, advances it to `INSTALLING`. Completing the install, while the project is `INSTALLING`, advances it to `COMPLETED`. Each of these advances increments the project's `version` by one. A project that has reached `COMPLETED` is terminal.

A customer may cancel their own project, but only before any deposit is captured: cancellation is permitted while the project is in `LEAD`, `DESIGNING`, or `QUOTED`, and is not available once the project has reached `DEPOSIT_PAID` or any later state — an attempt against a project in any other state is rejected with `ERR_INVALID_STATE`. Cancellation moves the project to `CANCELLED` and cascades: every non-terminal `DesignConsult` of the project (those in `SCHEDULED` or `RENDERED`) transitions to `CANCELLED`, and every `Quote` of the project that is in `DRAFT` or `ISSUED` transitions to `VOID`. Each consult and quote so affected has its own `version` incremented, and the project's `version` is incremented as well. Because cancellation is owner-only, the acting customer must own the project, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

Reading a project, listing its quotes, or reading a quote directly triggers a quote-expiry sweep, described in Section 3.4. Projects may be listed and filtered by `customer_id`, `accepted_quote_id`, `financing_application_id`, or `status`. A dedicated balance read recomputes and returns the project's current `balance_due_cents` breakdown on demand.

### 3.2. Design Consults, Space Measures, and Component Configuration

A `Designer` schedules a design consult against a project by supplying a `designer_user_id` (the opaque operator running the consult), a `scheduled_start`, and a `scheduled_end`; the `scheduled_end` must be strictly after the `scheduled_start`. A consult begins in `SCHEDULED` status with a null `rendering_url`. If the project was still `LEAD`, creating this first consult advances the project to `DESIGNING` and increments the project's `version`. The consult lifecycle is `SCHEDULED` → `RENDERED` → `COMPLETED`, with `CANCELLED` reachable from `SCHEDULED`. Attaching a 3D rendering moves a `SCHEDULED` consult to `RENDERED`; this requires a `rendering_url` to be supplied, which is written onto the consult, and increments the consult's `version`. A `RENDERED` consult may then be completed, moving it to `COMPLETED` and incrementing its `version`. A consult that is still `SCHEDULED` may instead be cancelled, moving it to `CANCELLED` and incrementing its `version`. Consults can be listed under their project.

A space measurement is recorded against a project by a designer, capturing `wall_count` (at least 1), `linear_feet` (greater than zero), and `ceiling_height_in` (at least 84). A measure carries a `confirmed` flag that starts false; it becomes true only when a component configuration is finalized against it, which locks the measure. Space measures can be listed under their project.

A `Designer` builds a component configuration against a project by supplying the `space_measure_id` of the measure it is fitted to, a `material_grade` — one of `MELAMINE`, `LAMINATE`, `WOOD`, or `PREMIUM_WOOD` — and an array of `line_items`. Each line item names a `component_type` drawn from `SHELF`, `DRAWER`, `ROD`, `CABINET`, `PANEL`, or `ACCESSORY`, a `quantity` of at least 1, and a `unit_price_cents` of at least 0. At creation the `line_items` array may be empty (the non-empty requirement is enforced only at finalize, below); each line item that is present is validated against these per-item constraints. A configuration begins in `DRAFT` status with `total_units` at zero. The config lifecycle is `DRAFT` → `FINALIZED`, with `FINALIZED` → `SUPERSEDED` reached later via a change order; `SUPERSEDED` is terminal. Configurations can be fetched individually, listed under their project (optionally filtered by `status`), or listed across the platform filtered by `space_measure_id`.

Finalizing a configuration is the act that prepares it for pricing. It is permitted only when the configuration is in `DRAFT`, its `line_items` are non-empty, and the backing space measure is not yet confirmed. If the measure is already confirmed — meaning some other configuration has already been finalized against it — the finalize is rejected with `ERR_MEASURE_ALREADY_CONFIRMED`, enforcing the rule that a single space measure may back at most one finalized configuration. On a successful finalize, the system recomputes the configuration's `total_units`, sets the backing measure's `confirmed` flag to true (locking it), and increments the `version` of both the configuration and the measure. The `total_units` figure is the sum of the `quantity` of every line item **except** those whose `component_type` is `ACCESSORY`: accessories are priced like any other item but do not count toward the unit total, which means they have no effect on the volume discount tier or on crew capacity consumption.

### 3.3. Quote Pricing

A `Designer` creates a draft quote against a project by supplying the `component_config_id` of the configuration to be priced and an optional `promo_code`. A quote begins in `DRAFT` status with `subtotal_cents`, `discount_cents`, `tax_cents`, and `total_cents` all at zero and `issued_at` and `expires_at` both null. The referenced configuration must be `FINALIZED`; creating a quote that references a configuration which is not finalized is rejected with `ERR_CONFIG_NOT_FINALIZED`. The quote lifecycle is `DRAFT` → `ISSUED` → `ACCEPTED`, with `SUPERSEDED`, `EXPIRED`, and `VOID` as the terminal outcomes.

Issuing a quote moves it from `DRAFT` to `ISSUED`, but only if the quote is in `DRAFT` and its referenced configuration is `FINALIZED`; otherwise the issue is rejected with `ERR_CONFIG_NOT_FINALIZED`. Issuing prices the quote, stamps `issued_at` to the current time, sets `expires_at` to `issued_at` plus the quote validity window of 30 days, and increments the quote's `version`. If this is the project's first issued quote and the project is `DESIGNING`, issuing also advances the project to `QUOTED` and increments the project's `version`.

Pricing proceeds in a strict, pinned order. First, the **pre-multiplier subtotal** is the sum, over every line item of the finalized configuration, of that item's `quantity` multiplied by its `unit_price_cents`. Second, a **material multiplier** is selected by the configuration's `material_grade`: `MELAMINE` multiplies by 1.00, `LAMINATE` by 1.15, `WOOD` by 1.40, and `PREMIUM_WOOD` by 1.80. The pre-multiplier subtotal is multiplied by this material multiplier and the result is rounded half up to whole cents — this rounding happens *after* the multiply, and the rounded figure is the value stored as the quote's `subtotal_cents`. Third, a **volume discount rate** is selected by the configuration's `total_units`: a `total_units` of 1 through 19 earns a rate of 0.00 (no discount), 20 through 49 earns 0.05, and 50 or more earns 0.10. The volume discount is the stored subtotal multiplied by this rate, rounded half up to whole cents. Fourth, a **promotional discount** stacks after the volume discount: if a recognized `promo_code` was supplied, its rate is applied — `SPRING10` is 0.10 and `VIP15` is 0.15; any unrecognized or absent code yields a rate of 0.00. The promotional discount is computed as the stored subtotal minus the volume discount, multiplied by the promo rate, rounded half up to whole cents, and then capped so it never exceeds 200000 cents (the lesser of the rounded figure and the cap is used). The quote's `discount_cents` is the sum of the volume discount and the promotional discount. Fifth, the **taxable base** is the stored subtotal minus `discount_cents`, and `tax_cents` is that taxable base multiplied by the project region's tax rate, rounded half up to whole cents; the regional tax rates are 0.0725 for `NORTH`, 0.0650 for `SOUTH`, 0.0800 for `EAST`, and 0.0925 for `WEST`. Finally, `total_cents` is the stored subtotal minus `discount_cents` plus `tax_cents`. This `total_cents` is the estimate the customer sees.

A `Customer` accepts an issued quote, moving it from `ISSUED` to `ACCEPTED` and incrementing its `version`. Acceptance is permitted only while the quote is `ISSUED` and the current time is at or before its `expires_at`; if the quote has passed `expires_at`, acceptance is rejected with `ERR_QUOTE_EXPIRED`. Because acceptance is an owner operation, the acting customer must own the project. Quotes can be fetched individually, listed under their project, or listed across the platform filtered by `project_id`, `component_config_id`, or `status`.

### 3.4. Quote Expiry Sweep

An issued quote is valid for a bounded window: its `expires_at` is exactly 30 days after `issued_at`. Rather than relying on a background timer, the system expires quotes lazily on read. Whenever a project is read, a project's quotes are listed, or a quote is read directly, the system sweeps the relevant quotes: any quote that is `ISSUED` and whose `expires_at` is now in the past — that is, the current time is strictly greater than `expires_at` — is transitioned to `EXPIRED`, and its `version` is incremented. A quote sitting exactly at `expires_at` has not yet expired; only a time strictly past it triggers the sweep. The 30-day window is anchored at issue time and is not extended by reads.

### 3.5. Deposit, Manufacture, and Lead Time

Once a quote is accepted, a deposit can be created against it. A deposit is opened by supplying the `project_id`, the `quote_id` of the accepted quote, and an `amount_cents`. A deposit begins in `PENDING` status. The deposit must be at least the **required deposit floor**, which is the accepted (or target) quote's `total_cents` multiplied by a room-type percentage, rounded half up to whole cents: the percentage is 0.30 for `REACH_IN_CLOSET`, 0.35 for `WALK_IN_CLOSET`, 0.25 for `GARAGE`, 0.30 for `PANTRY`, and 0.35 for `HOME_OFFICE`. An `amount_cents` greater than or equal to this floor is acceptable; an amount below the floor is rejected with `ERR_DEPOSIT_BELOW_MINIMUM`. This floor is checked both when the deposit is created and when it is captured. The deposit lifecycle is `PENDING` → `CAPTURED` → `REFUNDED`, with `REFUNDED` terminal. Deposits can be fetched individually and listed filtered by `project_id` or `quote_id`.

Capturing a deposit is a `PlatformAdmin` operation that pivots the project into production. It requires the deposit to be `PENDING`, the deposit's quote to be `ACCEPTED`, the project to be `QUOTED`, and the deposit `amount_cents` to meet the required floor. Capture is guarded by optimistic concurrency: the request carries `expected_quote_version`, and a mismatch with the quote's current `version` is rejected with `ERR_STALE_QUOTE_VERSION` as described in Section 2.8. On success, the deposit moves to `CAPTURED`; the project's `accepted_quote_id` is set to the deposit's `quote_id`; a new `ManufactureOrder` in status `QUEUED` is created for that project and quote; the project's `balance_due_cents` is recomputed; the project advances from `QUOTED` to `DEPOSIT_PAID`; and the `version` of the deposit, the project, and the quote are each incremented. A captured deposit may later be refunded by a `PlatformAdmin`, permitted only while the deposit is `CAPTURED` and the project is `DEPOSIT_PAID`; refund moves the deposit to `REFUNDED`, recomputes the project's `balance_due_cents` (restoring the balance to its pre-deposit value), and increments the deposit's and the project's `version`.

A manufacture order references its `project_id` and `quote_id` and begins in `QUEUED` with `lead_time_days` at zero and `started_at` and `promised_ready_date` null. Manufacture orders can be fetched individually and listed filtered by `project_id`, `quote_id`, or `status`. A `ManufacturingOps` operator starts production, which is permitted only while the order is `QUEUED` and the project is `DEPOSIT_PAID`. Starting computes the lead time, stamps `started_at` to the current time, sets `promised_ready_date` to `started_at` plus `lead_time_days` calendar days, advances the project from `DEPOSIT_PAID` to `IN_MANUFACTURE`, and increments the `version` of both the order and the project.

The lead time is computed from the accepted quote's finalized configuration and the project region. A **base lead** is selected by the configuration's `total_units`: 14 days for 1 through 19 units, 21 days for 20 through 49 units, and 35 days for 50 or more units. A **material addition** is selected by `material_grade`: 0 days for `MELAMINE`, 3 for `LAMINATE`, 7 for `WOOD`, and 14 for `PREMIUM_WOOD`. A **region addition** is selected by the project's `install_region`: 0 days for `NORTH`, 2 for `SOUTH`, 4 for `EAST`, and 6 for `WEST`. The `lead_time_days` is the sum of the base lead, the material addition, and the region addition.

Completing a manufacture order moves it from `IN_PRODUCTION` to `READY`, permitted only while the order is `IN_PRODUCTION` and the project is `IN_MANUFACTURE`, and subject to the **lead-time gate**: the current time must be at or after the order's `promised_ready_date`. An attempt to complete before the promised ready date — that is, when the current time is earlier than `promised_ready_date` — is rejected with `ERR_LEAD_TIME_NOT_ELAPSED`; the boundary is inclusive, so completing exactly at `promised_ready_date` is allowed. Completion advances the project from `IN_MANUFACTURE` to `READY_TO_INSTALL` and increments the `version` of both the order and the project. The manufacture order reaches its terminal `INSTALLED` state later, when the corresponding install job is completed, at which point its `version` is incremented again.

### 3.6. Crews, Install Scheduling, and Capacity

A crew is registered with a `crew_name`, a `region` (one of `NORTH`, `SOUTH`, `EAST`, or `WEST`), a `daily_capacity_units` of at least 1, and an `active` flag that defaults to true. The `daily_capacity_units` is the maximum number of configuration units the crew can install in a single calendar day. Crews are shared resources: one crew serves many install jobs. A crew can be fetched, and its install jobs listed (optionally filtered by `sched_status`).

An install job is proposed by a `Scheduler` against a ready manufacture order, supplying the `project_id`, the `manufacture_order_id`, the `crew_id`, a `window_start`, and a `window_end`. An install job carries two parallel dimensions that evolve independently: a scheduling dimension `sched_status` (`PROPOSED`, `BOOKED`, `RESCHEDULING`, or `CANCELLED`) starting at `PROPOSED`, and a completion dimension `completion_status` (`NOT_STARTED`, `IN_PROGRESS`, or `DONE`) starting at `NOT_STARTED`. It also carries `units_booked`, starting at zero, which is the number of configuration units this job consumes against crew capacity. At proposal time the manufacture order's state is not gated, so a job may be proposed while the order is still `QUEUED` (its `promised_ready_date` not yet stamped). The window-before-ready check at proposal time fires only once the order has a non-null `promised_ready_date`: the `promised_ready_date` check is evaluated first (when present), before window validity. So the `window_start` must be at or after the manufacture order's `promised_ready_date`, and a window starting before the order is promised ready is rejected with `ERR_WINDOW_BEFORE_READY`; if the order's `promised_ready_date` is still null, this `ERR_WINDOW_BEFORE_READY` check is skipped (it does not fire regardless of `window_start`, though the window-validity check below still applies). The window must then be valid: `window_end` must be strictly after `window_start`, and both must fall on the same UTC calendar day; a window that violates either condition is rejected with `ERR_INVALID_WINDOW`. Install jobs can be fetched individually and listed filtered by `project_id`, `manufacture_order_id`, or `crew_id`.

Booking a proposed job moves its `sched_status` from `PROPOSED` to `BOOKED`. Booking requires that the job's `sched_status` is `PROPOSED`, the job's manufacture order is `READY`, the crew is active, the crew's `region` equals the project's `install_region`, the `window_start` is at or after the manufacture order's `promised_ready_date`, and the crew has sufficient daily capacity for the window's day. A crew whose region does not match the project's region is rejected with `ERR_CREW_REGION_MISMATCH`. The capacity check works on the UTC calendar date of `window_start`: the system sums the `units_booked` of every install job on the same crew with `sched_status` of `BOOKED` whose `window_start` falls on that same calendar day, and the booking is allowed only if that already-booked total plus this job's units is at most the crew's `daily_capacity_units`; if the sum would exceed the capacity, the booking is rejected with `ERR_CREW_CAPACITY_EXCEEDED`. The boundary is inclusive: a total exactly equal to `daily_capacity_units` is permitted, and only a total strictly greater than it is refused. On a successful booking, `units_booked` is set to the accepted configuration's `total_units` (the same unit count that drives volume pricing and lead time), the crew/day capacity is held, and the job's `version` is incremented.

A `Customer` may request a reschedule of their booked job, moving its `sched_status` from `BOOKED` to `RESCHEDULING`. This is permitted only while the job's `sched_status` is `BOOKED` and its `completion_status` is `NOT_STARTED`; it frees the crew/day capacity the job was holding and increments the job's `version`. From `RESCHEDULING`, a `Scheduler` rebooks the job with a new `window_start` and `window_end`, moving it back to `BOOKED`. Rebooking requires the job to be `RESCHEDULING`, the new `window_start` to be at or after the manufacture order's `promised_ready_date`, and the capacity check on the new window's day to pass; the new window is also subject to the same validity rule (`window_end` strictly after `window_start`, same UTC calendar day) and the same region check as an initial booking, with the corresponding rejections. Rebooking sets the new `window_start` and `window_end`, re-holds the crew/day capacity, and increments the job's `version`. Alternatively, a `Scheduler` may cancel a booked job, permitted only while its `sched_status` is `BOOKED` and its `completion_status` is `NOT_STARTED`; cancellation frees the crew/day capacity and increments the job's `version`. `CANCELLED` is the terminal scheduling state.

The completion dimension advances independently. A `Scheduler` starts the install, moving `completion_status` from `NOT_STARTED` to `IN_PROGRESS`; this is permitted only while the job's `sched_status` is `BOOKED`, its `completion_status` is `NOT_STARTED`, the project is `READY_TO_INSTALL`, and the current time is at or after `window_start`; an attempt while any of these conditions is unmet — including a current time strictly before `window_start` — is rejected with `ERR_INVALID_STATE`. Starting advances the project from `READY_TO_INSTALL` to `INSTALLING` and increments the `version` of both the job and the project. The `Scheduler` then completes the install, moving `completion_status` from `IN_PROGRESS` to `DONE`, permitted only while `completion_status` is `IN_PROGRESS`. Completion is the deepest cascade in the system: it drives the manufacture order from `READY` to `INSTALLED`, advances the project from `INSTALLING` to `COMPLETED`, recomputes the project's `balance_due_cents`, and increments the `version` of the install job, the manufacture order, and the project.

### 3.7. Change Orders

After a quote is accepted and the project has entered production, a customer or designer may submit a change order against that accepted quote, supplying the `project_id`, the `base_quote_id` of the accepted quote being modified, a `change_type`, and — when applicable — a `revised_config_id`. The `change_type` is polymorphic: a `CONFIG_REVISION` changes the configuration being built and therefore the price, while a `SCHEDULE_CHANGE` alters only the install window and leaves the price unchanged. A `CONFIG_REVISION` requires a `revised_config_id` that names a `FINALIZED` configuration; a `SCHEDULE_CHANGE` must not supply one. A change order that supplies the wrong combination — a `CONFIG_REVISION` missing or naming a non-finalized `revised_config_id`, or a `SCHEDULE_CHANGE` that supplies a `revised_config_id` — is rejected with `ERR_CHANGE_TARGET_INVALID`. A change order begins in `SUBMITTED` status with `delta_cents` at zero. Its lifecycle is `SUBMITTED` → `APPROVED` → `APPLIED`, with `REJECTED` as an alternate terminal outcome; a rejected change can be resubmitted as a brand-new change order. Change orders can be fetched individually and listed filtered by `project_id`, `base_quote_id`, `revised_config_id`, or `status`.

A `Designer` approves a submitted change order, moving it from `SUBMITTED` to `APPROVED`. Approval is permitted only while the change order is `SUBMITTED`, its base quote is `ACCEPTED`, and the project is in `DEPOSIT_PAID` or `IN_MANUFACTURE`. Approval computes the change's `delta_cents` and increments the change order's `version`. The delta is signed: for a `CONFIG_REVISION`, it is the price of the revised configuration (computed by the same quote-pricing formula of Section 3.3, applied to the revised configuration's line items and unit total) minus the base quote's `total_cents`, and may be negative for a downgrade; for a `SCHEDULE_CHANGE`, the delta is zero because the price does not change. When the revised configuration is repriced, the original quote's `promo_code` is **not** carried over — pricing recomputes without a promo unless one is supplied again — so the same line items can yield a different total than the base quote. Alternatively, a `Designer` rejects a submitted change order, moving it from `SUBMITTED` to `REJECTED` and incrementing its `version`.

A `Designer` applies an approved change order, moving it from `APPROVED` to `APPLIED`. Apply is permitted only while the change order is `APPROVED`, and for a `CONFIG_REVISION` the `revised_config_id` must name a `FINALIZED` configuration. Apply is guarded by optimistic concurrency: the request carries `expected_project_version`, and a mismatch with the project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION` as described in Section 2.8. The apply cascades. For a `CONFIG_REVISION`, the system creates a new `ACCEPTED` quote priced from the revised configuration, drives the base quote from `ACCEPTED` to `SUPERSEDED`, drives the prior `FINALIZED` configuration to `SUPERSEDED`, and sets the project's `accepted_quote_id` to the new quote's id. For both change types, the system recomputes the project's `balance_due_cents` (applying the delta) and increments the change order's `version`; the project's `version` and, where a new quote is created, the new and superseded quotes' `version` values are incremented as part of the cascade.

### 3.8. Balance Reconciliation

A project's `balance_due_cents` is recomputed on each deposit capture, deposit refund, financing funding, change-order apply, and install completion. The balance is the project's accepted-quote total (taken from the quote referenced by `accepted_quote_id`, or zero if none is set yet) minus the sum of the `amount_cents` of every deposit of the project whose status is `CAPTURED`, minus the financed amount. The financed amount is the project's financing application's `approved_amount_cents` when that application is `FUNDED`, and zero otherwise. The result is floored at zero — if the deposits and financing together exceed the accepted total, the balance is reported as zero rather than a negative number. In practice the balance is first computed provisionally at deposit capture, before any financing is funded, so at that point the financed component is zero and the balance reflects the accepted total less captured deposits only; once financing is funded, the recomputation subtracts the approved financed amount, yielding a lower balance for the same deposits.

### 3.9. Financing

A `Customer` opens a financing application against an accepted quote, supplying the `project_id`, the `quote_id` of the accepted quote, a `requested_amount_cents` (greater than zero), and a `term_months` that is one of 12, 24, 36, or 48. An application begins in `DRAFT` status with `approved_amount_cents` and `monthly_payment_cents` both at zero. Its lifecycle is `DRAFT` → `SUBMITTED` → `APPROVED` → `FUNDED`, with `DECLINED` as an alternate terminal outcome. Financing applications can be fetched individually and listed filtered by `project_id`, `quote_id`, or `status`.

The customer submits the application, moving it from `DRAFT` to `SUBMITTED`; this is permitted only while the application is `DRAFT`, its quote is `ACCEPTED`, and the `requested_amount_cents` is at most the quote's `total_cents`. A request to finance more than the quote total is rejected with `ERR_FINANCE_EXCEEDS_TOTAL`. Submission increments the application's `version`. Because submission is an owner operation, the acting customer must own the project.

A `PlatformAdmin` relays the lender's decision through a decision webhook that names the `financing_application_id` and a `decision` of either `APPROVE` or `DECLINE`. The application must be `SUBMITTED`. An `APPROVE` decision moves it to `APPROVED`, computes the approved principal and the monthly payment, and increments its `version`; a `DECLINE` decision moves it to `DECLINED` and increments its `version`. On approval, the **approved amount** is the smaller of the `requested_amount_cents` and an approval cap equal to the quote's `total_cents` multiplied by the maximum loan-to-value of 0.80, rounded half up to whole cents; `approved_amount_cents` is set to this smaller value. The **monthly payment** is then computed from the approved amount, the term, and an APR selected by `term_months`: a 12-month term carries an APR of 0.0000, a 24-month term 0.0599, a 36-month term 0.0899, and a 48-month term 0.1199. For the interest-bearing terms (24, 36, and 48 months), the monthly interest rate is the APR divided by 12, and the monthly payment is the approved amount multiplied by the monthly rate, divided by one minus the quantity (one plus the monthly rate) raised to the power of the negative term length in months, with the final figure rounded half up to whole cents. For the 12-month term, where the APR is zero and the monthly rate would make that amortization formula divide by zero, the monthly payment is instead simply the approved amount divided by 12, rounded half up to whole cents. The evaluation order is pinned: the approved amount is computed first, then the monthly payment from it.

A `PlatformAdmin` funds an approved application, moving it from `APPROVED` to `FUNDED`. Funding is permitted only while the application is `APPROVED` and the project is in `DEPOSIT_PAID`, `IN_MANUFACTURE`, or `READY_TO_INSTALL`. Funding sets the project's `financing_application_id` to the application's id, recomputes the project's `balance_due_cents` (so the approved financed amount reduces the balance), and increments the `version` of both the application and the project. A project may hold only one funded financing application; attempting to fund when the project already carries a funded `financing_application_id` is rejected with `ERR_FINANCE_ALREADY_LINKED`.

### 3.10. Warranty Claims and Adjustments

After a project is `COMPLETED`, a `Customer` may file a warranty claim against the completed install, supplying the `project_id`, the `install_job_id` of the completed install being claimed against, and a `defect_type` — one of `HARDWARE`, `FINISH`, `FIT`, or `STRUCTURAL`; filing against a project that is not yet `COMPLETED` is rejected with `ERR_INVALID_STATE`. A claim begins in `FILED` status. At filing, the system computes the claim's `covered` flag: the claim is covered when it is filed within the warranty window of 365 days of the install's completion **and** the `defect_type` is among the covered defects, which are `HARDWARE`, `FINISH`, `FIT`, and `STRUCTURAL`. The window uses the install job's completion timestamp — the moment its `completion_status` became `DONE` — and runs on UTC day arithmetic; a claim filed exactly at the completion moment plus 365 days is still within the window, because the boundary is inclusive. Warranty claims can be fetched individually and listed filtered by `project_id`, `install_job_id`, or `status`.

A `ManufacturingOps` operator adjudicates the claim. The claim lifecycle is `FILED` → `APPROVED`, then either `APPROVED` → `ADJUSTMENT_SCHEDULED` or `APPROVED` → `REPLACEMENT_ORDERED`, then `RESOLVED`; `REJECTED` is an alternate terminal outcome from `FILED`. Approving a claim moves it from `FILED` to `APPROVED` and requires `covered` to be true; approving a claim whose `covered` flag is false is rejected with `ERR_WARRANTY_NOT_COVERED`. Approval increments the claim's `version`. Alternatively, a filed claim may be rejected, moving it from `FILED` to `REJECTED` and incrementing its `version`.

From `APPROVED`, the claim forks by defect class into two parallel branches with divergent handling. The **adjustment branch** schedules an on-site adjustment, moving the claim from `APPROVED` to `ADJUSTMENT_SCHEDULED`, and is permitted only when the `defect_type` is `FIT` or `FINISH`. The **replacement branch** orders a replacement, moving the claim from `APPROVED` to `REPLACEMENT_ORDERED`, and is permitted only when the `defect_type` is `HARDWARE` or `STRUCTURAL`. Requesting an adjustment for a defect that is not `FIT` or `FINISH`, or a replacement for a defect that is not `HARDWARE` or `STRUCTURAL`, is rejected with `ERR_WARRANTY_BRANCH_MISMATCH`. Each branch transition increments the claim's `version`. From either `ADJUSTMENT_SCHEDULED` or `REPLACEMENT_ORDERED`, the operator resolves the claim, moving it to the terminal `RESOLVED` state and incrementing its `version`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`; operations that modify an existing resource — including all state-transition operations — return `200 OK`. The test-driving and webhook endpoints likewise return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer; derives install region from zip code | Anonymous |
| GET | `/customers/{id}` | Fetch a customer | Customer, Designer, Scheduler, ManufacturingOps, PlatformAdmin |
| POST | `/projects` | Create a project for a customer | Customer, Designer |
| GET | `/projects/{id}` | Fetch a project (triggers quote-expiry sweep) | Customer, Designer, Scheduler, ManufacturingOps, PlatformAdmin |
| GET | `/projects` | List projects (filter by customer, accepted quote, financing, status) | Designer, Scheduler, ManufacturingOps, PlatformAdmin |
| POST | `/projects/{id}/cancel` | Cancel a project before deposit (cascades) | Customer |
| GET | `/projects/{id}/balance` | Read current balance breakdown | Customer, Designer, PlatformAdmin |
| POST | `/projects/{id}/design-consults` | Schedule a design consult | Designer |
| GET | `/projects/{id}/design-consults` | List a project's design consults | Customer, Designer, PlatformAdmin |
| POST | `/design-consults/{id}/render` | Attach a 3D rendering | Designer |
| POST | `/design-consults/{id}/complete` | Complete a consult | Designer |
| POST | `/design-consults/{id}/cancel` | Cancel a consult | Designer |
| POST | `/projects/{id}/space-measures` | Record a space measurement | Designer |
| GET | `/projects/{id}/space-measures` | List a project's space measures | Customer, Designer, PlatformAdmin |
| POST | `/projects/{id}/component-configs` | Create a component configuration | Designer |
| GET | `/projects/{id}/component-configs` | List a project's component configs | Customer, Designer, PlatformAdmin |
| GET | `/component-configs/{id}` | Fetch a component config | Customer, Designer, PlatformAdmin |
| GET | `/component-configs` | List component configs (filter by space measure) | Designer, PlatformAdmin |
| POST | `/component-configs/{id}/finalize` | Finalize a config; locks the space measure | Designer |
| POST | `/projects/{id}/quotes` | Create a draft quote | Designer |
| GET | `/projects/{id}/quotes` | List a project's quotes (triggers expiry sweep) | Customer, Designer, PlatformAdmin |
| GET | `/quotes/{id}` | Fetch a quote (triggers expiry sweep) | Customer, Designer, PlatformAdmin |
| GET | `/quotes` | List quotes (filter by project, config, status) | Customer, Designer, PlatformAdmin |
| POST | `/quotes/{id}/issue` | Issue and price a quote | Designer |
| POST | `/quotes/{id}/accept` | Accept an issued quote | Customer |
| POST | `/deposits` | Create a pending deposit | Customer, PlatformAdmin |
| GET | `/deposits/{id}` | Fetch a deposit | Customer, PlatformAdmin |
| GET | `/deposits` | List deposits (filter by project, quote) | Customer, PlatformAdmin |
| POST | `/deposits/{id}/capture` | Capture a deposit; creates manufacture order, advances project | PlatformAdmin |
| POST | `/deposits/{id}/refund` | Refund a captured deposit | PlatformAdmin |
| GET | `/manufacture-orders/{id}` | Fetch a manufacture order | ManufacturingOps, Scheduler, Designer, PlatformAdmin |
| GET | `/manufacture-orders` | List manufacture orders (filter by project, quote, status) | ManufacturingOps, Scheduler, PlatformAdmin |
| POST | `/manufacture-orders/{id}/start` | Start production; compute lead time | ManufacturingOps |
| POST | `/manufacture-orders/{id}/complete` | Mark order ready (lead-time gate) | ManufacturingOps |
| POST | `/crews` | Register an install crew | Scheduler, PlatformAdmin |
| GET | `/crews/{id}` | Fetch a crew | Scheduler, PlatformAdmin |
| GET | `/crews/{id}/install-jobs` | List a crew's install jobs | Scheduler, PlatformAdmin |
| POST | `/install-jobs` | Propose an install job | Scheduler |
| GET | `/install-jobs/{id}` | Fetch an install job | Customer, Scheduler, PlatformAdmin |
| GET | `/install-jobs` | List install jobs (filter by project, order, crew) | Customer, Scheduler, PlatformAdmin |
| POST | `/install-jobs/{id}/book` | Book a proposed job (capacity & region checks) | Scheduler |
| POST | `/install-jobs/{id}/request-reschedule` | Request a reschedule; frees capacity | Customer |
| POST | `/install-jobs/{id}/rebook` | Rebook a new window | Scheduler |
| POST | `/install-jobs/{id}/cancel` | Cancel a booked job; frees capacity | Scheduler |
| POST | `/install-jobs/{id}/start` | Start install; advances project to installing | Scheduler |
| POST | `/install-jobs/{id}/complete` | Complete install; cascades to order and project | Scheduler |
| POST | `/change-orders` | Submit a change order | Customer, Designer |
| GET | `/change-orders/{id}` | Fetch a change order | Customer, Designer, PlatformAdmin |
| GET | `/change-orders` | List change orders (filter by project, base quote, revised config, status) | Customer, Designer, PlatformAdmin |
| POST | `/change-orders/{id}/approve` | Approve a change order; compute delta | Designer |
| POST | `/change-orders/{id}/reject` | Reject a change order | Designer |
| POST | `/change-orders/{id}/apply` | Apply an approved change order (OCC on project) | Designer |
| POST | `/warranty-claims` | File a warranty claim | Customer |
| GET | `/warranty-claims/{id}` | Fetch a warranty claim | Customer, ManufacturingOps, PlatformAdmin |
| GET | `/warranty-claims` | List warranty claims (filter by project, install job, status) | Customer, ManufacturingOps, PlatformAdmin |
| POST | `/warranty-claims/{id}/approve` | Approve a covered claim | ManufacturingOps |
| POST | `/warranty-claims/{id}/reject` | Reject a claim | ManufacturingOps |
| POST | `/warranty-claims/{id}/schedule-adjustment` | Schedule an on-site adjustment | ManufacturingOps |
| POST | `/warranty-claims/{id}/order-replacement` | Order a replacement | ManufacturingOps |
| POST | `/warranty-claims/{id}/resolve` | Resolve a claim | ManufacturingOps |
| POST | `/financing-applications` | Create a draft financing application | Customer |
| GET | `/financing-applications/{id}` | Fetch a financing application | Customer, PlatformAdmin |
| GET | `/financing-applications` | List financing applications (filter by project, quote, status) | Customer, PlatformAdmin |
| POST | `/financing-applications/{id}/submit` | Submit a financing application | Customer |
| POST | `/financing-applications/{id}/fund` | Fund an approved application; reduces balance | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a UTC instant | PlatformAdmin |
| POST | `/_financing/decision` | Lender decision webhook (approve or decline) | PlatformAdmin |

The logical-clock endpoint is an administrative test-driving capability that sets the server's logical clock to a supplied `to_iso8601` instant. The server's logical clock defaults to `2026-04-01T00:00:00Z` at startup; before any set call the clock reads exactly this default and never falls back to wall-clock time. All "current time" comparisons in this document — quote expiry, the manufacture lead-time gate, the install start window check, and the warranty window — read this logical clock.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_STALE_QUOTE_VERSION` | 412 |
| `ERR_CREW_REGION_MISMATCH` | 409 |
| `ERR_MEASURE_ALREADY_CONFIRMED` | 409 |
| `ERR_LEAD_TIME_NOT_ELAPSED` | 409 |
| `ERR_WINDOW_BEFORE_READY` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 |
| `ERR_WARRANTY_NOT_COVERED` | 409 |
| `ERR_WARRANTY_BRANCH_MISMATCH` | 409 |
| `ERR_DEPOSIT_BELOW_MINIMUM` | 422 |
| `ERR_FINANCE_EXCEEDS_TOTAL` | 422 |
| `ERR_CONFIG_NOT_FINALIZED` | 409 |
| `ERR_CHANGE_TARGET_INVALID` | 422 |
| `ERR_VALIDATION` | 422 |
| `ERR_FINANCE_ALREADY_LINKED` | 409 |
