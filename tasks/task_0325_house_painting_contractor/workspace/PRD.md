# House Painting Contractor API — Product Requirements Document

## 1. Introduction

The House Painting Contractor API is the operational backbone for a residential painting business that takes a job from a walk-through estimate all the way through to a touch-up warranty. A typical engagement begins when an estimator surveys a home, records each room or elevation as a paintable surface, picks the right paint product for each surface, and produces a square-foot-and-coat estimate that the homeowner can sign off on. From there the project moves into scheduling — booking painters and shared equipment against a weather forecast — then into active work, a final walkthrough, and finally a warranty period during which the homeowner may file touch-up claims.

This system has two distinct concerns that must never be confused. The first is **pricing**: the contract estimate is a frozen, contractual figure that the deposit is computed against, while the live project total moves whenever an approved change order alters the scope, and a separate final total is reconciled only at completion. The second is **logistics and money flow**: a project advances along a workflow axis and an independent payment axis at the same time, so that a homeowner can pay a deposit before any crew is scheduled, or a project can be fully painted yet still await final payment before it is considered complete. The API exists to keep these moving parts consistent — line items, project totals, deposits, balances, crew utilization, and warranty payouts — under concurrent edits and a strict role model that separates who may author scope, who may schedule and run the job, who pays and signs off, and who reports work in the field.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the entire API. All resources are served under the `/painting` mount.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which that user is acting. If either header is missing, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are valid but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles: `Estimator`, `ProjectManager`, `Customer`, and `CrewMember`.

- An `Estimator` authors scope — paint products, projects, surfaces, color proposals, the frozen estimate, and change orders.
- A `ProjectManager` runs the project lifecycle and all logistics: crew members, equipment, weather windows, scheduling, work start, walkthrough requests, cancellation, crew-assignment cancellation, walkthrough reopening, and warranty claim resolution.
- A `Customer` is the homeowner who approves or rejects colors and change orders, pays the deposit and final balance, passes or fails walkthroughs, and files warranty claims.
- A `CrewMember` is a field painter who reports assignment progress (beginning and completing assignments).

Every one of these four roles carries an **opaque** identity: when `X-User-Role` is any of `Estimator`, `ProjectManager`, `Customer`, or `CrewMember`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity's `id`. The server may record or compare such an identifier where a business rule calls for it — for example, a project carries a `customer_id` that is the opaque `X-User-ID` a homeowner authenticates with rather than a foreign key to any stored customer entity — but the server does not treat `X-User-ID` as the primary key of any entity, and there is no entity-backed ownership check that compares a resource's `id` to the caller. Role authorization is therefore purely a matter of whether the named role is permitted for the endpoint.

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

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation of the resource.
- `version` — a system-managed integer that begins at 1 on creation and increments by one with every mutation. It is the basis for the optimistic concurrency mechanism described in §2.7.

There is one deliberate exception. A `Payment` is an append-only ledger row: it carries only `id` and `created_at`. A `Payment` has neither an `updated_at` nor a `version`, because once captured a payment row is never mutated in place — a cancellation refunds it by changing its `status`, which is treated as a ledger event rather than an editable property for concurrency purposes. Every other resource carries the full quartet of common fields.

### 2.5. Derived Fields, Mutation, and Hierarchical Consistency

A large fraction of the data in this system is **computed** and read-only — clients never write these fields directly; the server derives them and keeps them consistent. Examples include a crew member's `scheduled_day_count`, a piece of equipment's `units_reserved`, a weather window's `exterior_suitable`, every monetary total on a project, a line item's `gallons_required`, `material_cost_cents`, `labor_hours`, `labor_cost_cents`, and `executed` flag, a surface's `color_locked` flag, a change order's `delta_total_cents` and `applied_project_version`, an assignment's `day_count`, and a warranty claim's `provisional_payout_cents` and `final_payout_cents`.

Because entities are flat sibling collections, parent–child relationships are expressed through foreign-key fields carried in request bodies rather than through nested URL paths. A surface names its `project_id`; a color selection names its `surface_id` and derives its `project_id` from that surface; a line item is bound to both its `project_id` and `surface_id`; change orders, crew assignments, payments, walkthroughs, and warranty claims all reference their `project_id`. Children are discovered through filtered list queries (for instance, listing surfaces by `project_id`, or color selections by `surface_id`), never through path nesting.

When any operation mutates a resource, that resource's `updated_at` is refreshed and its `version` is incremented. This applies equally to cascading effects: when an approved change order re-prices a project's live total, the project itself is mutated, so its `updated_at` and `version` move. The system performs server-driven transitions without an explicit client request on the affected resource where a business rule requires it — most notably, passing a walkthrough may automatically complete the parent project, and requesting a walkthrough automatically opens a `PENDING` walkthrough record.

### 2.6. Nested Identifier Resolution

Although the API uses flat collections, several write operations carry foreign-key identifiers in their path or body. The system validates identifiers in a sequential, left-to-right order: a path identifier is resolved before any body field, and where a path expresses a containment relationship the parent is confirmed before the child. The first identifier that does not resolve causes immediate rejection with the corresponding 404 error — `ERR_PROJECT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_COLOR_SELECTION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_WALKTHROUGH_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_CREW_MEMBER_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_PAINT_PRODUCT_NOT_FOUND`, or `ERR_WEATHER_WINDOW_NOT_FOUND` — as appropriate to the unresolved reference. This existence check (priority 3) runs after authentication (priority 1) and role authorization (priority 2) but before request-body validation and any state or business check.

### 2.7. Optimistic Concurrency on Project-Scoped Authoring

A change order is priced relative to a project's current surface set and its frozen estimate, so authoring one against a project whose scope has shifted underneath the author is dangerous. To guard against this, **authoring a change order requires the client to declare the project version it last observed.** The create-change-order request carries `expected_project_version`, which is a non-optional input field, and the server compares it to the target project's current `version`. If another change order has since been approved — legitimately superseding the prior surface set and advancing the project's `version` — the author's view is stale and the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). This is the system's only optimistic-concurrency-controlled write; no other endpoint takes a version field, and operations not creating a change order proceed without an OCC check.

### 2.8. Monetary Precision and Rounding

All money in this system is represented as integer cents — `price_per_gallon_cents`, `daily_rate_cents`, the project's estimate and total fields, `deposit_due_cents`, `amount_paid_cents`, `balance_due_cents`, every line item cost, `delta_total_cents`, payment `amount_cents`, and warranty payouts. Wherever a calculation produces a fractional cent, the result is rounded to a whole number of cents using the **round-half-up** convention (a raw value ending in exactly one half rounds up). Gallon counts are produced by rounding **up** to the next whole gallon. The exact rounding point matters: monetary rounding is always applied **per line item first, and only then are the whole-cent line totals summed** — never the reverse. Summing already-rounded integers avoids the drift that would result from summing raw fractional values and rounding once at the end.

### 2.9. Resource Utilization Accounting

Two shared resources track utilization through conserved, read-only counters. A crew member's `scheduled_day_count` is the total number of distinct scheduled days the member is committed to across assignments that are `SCHEDULED` or `IN_PROGRESS`. A piece of equipment's `units_reserved` reflects the peak number of identical units held at once by date-overlapping assignments that are `SCHEDULED` or `IN_PROGRESS`. Both counters are **conserved across the assignment lifecycle**: scheduling an assignment raises them, and any path that ends the commitment — completing the work or cancelling the assignment — releases the same quantity back, so the books always reconcile. The mechanics of when each counter rises and falls are described with the crew-scheduling workflow in §3.

## 3. Business Logic & Workflows

### 3.1. Catalog, Crew, Equipment, and Weather Setup

Before any project can be priced or scheduled, the contractor populates a catalog of reusable resources.

An estimator registers a **paint product** by supplying its catalog `name`, its `surface_kind` (one of `INTERIOR`, `EXTERIOR`, or `BOTH` — declaring which surface scopes the product may be applied to), its `finish_type` (one of `FLAT`, `EGGSHELL`, `SATIN`, `SEMI_GLOSS`, or `GLOSS`), its `price_per_gallon_cents` (the material unit price in cents per gallon, which must be at least 1), and its `coverage_sqft_per_gallon_per_coat` (the square feet a single gallon covers for one coat, also at least 1). A product may optionally be flagged `active`; when omitted, `active` defaults to true. An inactive product may not be chosen for new surfaces but remains referenceable by surfaces that already use it.

A project manager registers a **crew member** with a `full_name`, a `skill_level` (one of `APPRENTICE`, `JOURNEYMAN`, or `MASTER`), and a `daily_rate_cents` (the per-scheduled-day billing rate in cents, at least 1). An `active` flag (defaulting to true when omitted) governs whether the member may take new assignments. On creation the member's `scheduled_day_count` is initialized to 0.

A project manager also registers shared **equipment** with a `name`, an `equipment_kind` (one of `SPRAYER`, `SCAFFOLD`, or `LIFT`), and `total_units` — the number of identical physical units available for concurrent booking (at least 1). On creation the equipment's `units_reserved` is initialized to 0.

Finally, a project manager records daily **weather windows**. Each window is created with a `window_date` (an ISO date in `YYYY-MM-DD` form, which must be unique across all weather windows), a `forecast_temp_f` (forecast daytime temperature in Fahrenheit), and a `precipitation_pct` (forecast precipitation probability, an integer from 0 through 100 inclusive). Upon creation the system computes the read-only `exterior_suitable` flag: a window is suitable for exterior work exactly when its forecast temperature is at least 50 degrees Fahrenheit **and** its precipitation probability is at most 30 percent. A forecast of exactly 50 degrees is suitable; 49 is not. A precipitation probability of exactly 30 percent is suitable; 31 is not.

Paint products, crew members, equipment, and weather windows can all be listed and individually retrieved; the paint-product list accepts a `surface_kind` filter and the weather-window list accepts a `window_date` filter.

### 3.2. Founding a Project and Building Its Scope

An estimator opens a **project** by supplying the homeowner's `customer_id` (the opaque account identifier the customer will authenticate with), the `site_address` of the job, and the overall `scope` (one of `INTERIOR`, `EXTERIOR`, or `BOTH`). Two optional fields shape the money side: `deposit_pct`, the deposit percentage of the estimate total, an integer from 0 through 100 that defaults to 30; and `warranty_months`, the touch-up warranty length in months counted from completion, defaulting to 12. A freshly created project begins in `DRAFT` on its workflow axis and `UNPAID` on its payment axis, with every computed monetary total at 0 and `version` at 1.

Onto a `DRAFT` project the estimator attaches **surfaces** — one per room or elevation. A surface create carries the `project_id` it belongs to, a `label` (such as "Master Bedroom" or "North Elevation"), a `surface_kind` (here restricted to `INTERIOR` or `EXTERIOR`), an `area_sqft` (paintable area in square feet, at least 1), a `coats` count (from 1 through 4 inclusive), a `prep_level` (one of `LIGHT`, `STANDARD`, `HEAVY`, or `RESTORATION`), and a `paint_product_id` naming the product to use. The surface is created in `PLANNED` status with its `color_locked` flag false.

Two compatibility checks guard surface creation, both reported with `ERR_PRODUCT_SURFACE_MISMATCH` (HTTP 422). First, the chosen product's surface scope must admit the surface: a product whose `surface_kind` is `BOTH` may be used on either an `INTERIOR` or an `EXTERIOR` surface, an `INTERIOR` product may be used only on an `INTERIOR` surface, and an `EXTERIOR` product only on an `EXTERIOR` surface. Second, the surface's own kind must be compatible with the project's `scope`: an `INTERIOR`-scoped project admits only interior surfaces, an `EXTERIOR`-scoped project only exterior surfaces, and a `BOTH`-scoped project admits either. The same two checks apply when an approved change order adds or revises a surface.

Creating a surface immediately spawns exactly one **line item** for it (one line item per non-`REMOVED` surface) and computes that line item's estimate. The line item records its `project_id` and `surface_id`, and exposes the read-only quantities `gallons_required`, `material_cost_cents`, `labor_hours`, `labor_cost_cents`, and `executed` (which is false until the surface is executed). Surfaces and line items can be listed and retrieved; surfaces may be filtered by `project_id`, by `paint_product_id`, or by `status`, and line items may be filtered by `project_id` or `surface_id`.

The **material estimate** for a line item works from its surface and that surface's paint product. The gallons required is the surface's area in square feet multiplied by its number of coats, divided by the product's coverage per gallon per coat, with the quotient rounded up to the next whole gallon. The material cost in cents is that whole-gallon count multiplied by the product's price per gallon in cents. Because the gallon count is always a whole number and the price is in whole cents, the material cost is an exact integer.

The **labor estimate** is built from the same surface. The labor hours equal the surface's area in square feet multiplied by its coats and by a prep factor that depends on the surface's prep level, the product then divided by a fixed productivity of 160 square feet per hour. The prep factor is 1.0 for `LIGHT`, 1.25 for `STANDARD`, 1.6 for `HEAVY`, and 2.0 for `RESTORATION`. Labor hours are kept as an exact rational value. The labor cost in cents is the labor hours multiplied by a fixed labor rate of 6550 cents per hour, then rounded half-up to whole cents. (For example, a 120-square-foot, single-coat `LIGHT` surface yields raw labor of 4912.5 cents, which rounds to 4913.)

### 3.3. Finalizing the Estimate and Freezing the Contract

When the scope is complete, the estimator finalizes the estimate. This transition is permitted only when the project's `workflow_status` is `DRAFT`; otherwise it is rejected with `ERR_PROJECT_NOT_DRAFT`. The project must also have at least one surface in `PLANNED` status, failing which the transition is rejected with `ERR_NO_SURFACES`.

Finalizing recomputes every line item's material and labor estimate, then **freezes the estimate snapshot**. Summing per-line-item over the line items whose surface is `PLANNED` at that instant, the system sets `estimate_material_cents` to the sum of the line items' material costs, `estimate_labor_cents` to the sum of their labor costs (each labor cost having already been rounded to whole cents per line item before summing), and `estimate_total_cents` to the sum of those two components. These three figures form the contractual estimate and are **never recomputed afterward** — later change orders do not move them. The system simultaneously sets the live `revised_total_cents` equal to the frozen `estimate_total_cents`, so the live total starts out matching the contract.

The deposit is pinned at this moment. The system sets `deposit_due_cents` to the frozen `estimate_total_cents` multiplied by the project's `deposit_pct`, divided by 100, rounded half-up to whole cents — and this deposit figure is fixed for the life of the project, anchored to the frozen estimate rather than the moving live total. The balance, `balance_due_cents`, is set to the live `revised_total_cents` minus `amount_paid_cents` (zero at this point, so the balance equals the revised total). Finally `workflow_status` advances from `DRAFT` to `ESTIMATED`. The illustrative pinned-rounding point is worth restating: two `LIGHT` line items with raw labor of 4912.5 and 8187.5 round to 4913 and 8188 and sum to 13101, whereas summing the raw values to 13100.0 and rounding once would give 13100 — a one-cent difference that the per-line-item-then-sum rule deliberately avoids.

### 3.4. Color Proposal and Approval

Colors are proposed and then approved by the homeowner before a project can be scheduled. A color selection is proposed against a surface by supplying the `surface_id` and a manufacturer `color_code` (such as "SW-7005"); the selection's `project_id` is derived from the referenced surface, and it begins in `PROPOSED` status. Proposing a color is open to both the estimator and the customer; approval and rejection belong to the customer alone.

Approving a proposed color is allowed only when the selection is in `PROPOSED` status (otherwise `ERR_COLOR_NOT_PROPOSED`) and the parent surface is still `PLANNED` (otherwise `ERR_SURFACE_NOT_PLANNED`). On approval the selection moves to `APPROVED` and the parent surface's read-only `color_locked` flag becomes true. Rejecting a proposed color likewise requires `PROPOSED` status (`ERR_COLOR_NOT_PROPOSED`) and moves the selection to `REJECTED`, the terminal state of this short machine. Color selections can be listed (filtered by `project_id` or `surface_id`) and retrieved individually.

### 3.5. Scheduling Crew, Equipment, and Weather

A project manager moves a project from `ESTIMATED` to `SCHEDULED`, but only when a battery of preconditions holds. The project's `workflow_status` must be `ESTIMATED` (otherwise `ERR_PROJECT_NOT_ESTIMATED`). The payment axis must already show `DEPOSIT_PAID` or `PAID_IN_FULL` (otherwise `ERR_DEPOSIT_NOT_PAID`). Every `PLANNED` surface must have an `APPROVED` color selection (otherwise `ERR_COLOR_NOT_APPROVED`). And the project must have at least one crew assignment in `SCHEDULED` status (otherwise `ERR_NO_CREW_SCHEDULED`). When all hold, `workflow_status` advances to `SCHEDULED`.

The crew assignments those preconditions depend on are created beforehand by the project manager. A **crew assignment** booking carries the `project_id`, the `crew_member_id` to book, an optional `equipment_id` to reserve a shared resource for the window, a `start_date` and an `end_date` (inclusive, ISO `YYYY-MM-DD`, with the end on or after the start), and an optional `requires_exterior_weather` flag that defaults to false. The assignment is created in `SCHEDULED` status, and its read-only `day_count` is computed as the inclusive day span — the number of days from the start date through the end date inclusive (that is, the difference in days plus one). On creation the crew member's `scheduled_day_count` rises by this `day_count`, and if an equipment unit was reserved the equipment's `units_reserved` is recomputed to reflect the new peak overlap.

Several validations gate the booking, each carrying its own code. **Crew skill adequacy** (priority 8, `ERR_CREW_SKILL_INSUFFICIENT`, HTTP 422): the crew member's skill level must meet the minimum demanded by the heaviest prep level among the project's `PLANNED` surfaces — a `RESTORATION` surface requires a `MASTER`, a `HEAVY` surface requires at least a `JOURNEYMAN`, and surfaces no heavier than `STANDARD` or `LIGHT` may be served by any skill level. **Crew double-booking** (priority 9, `ERR_CREW_DOUBLE_BOOKED`, HTTP 409): the new window must neither overlap another `SCHEDULED` or `IN_PROGRESS` assignment of the same crew member nor sit immediately back-to-back with one; the system requires a gap of at least one clear day between two assignments of the same member, so adjacent windows are rejected. **Equipment capacity** (priority 10, `ERR_EQUIPMENT_OVERBOOKED`, HTTP 409): across `SCHEDULED` and `IN_PROGRESS` assignments holding the same `equipment_id`, the peak number of date-overlapping assignments must not exceed that equipment's `total_units`; here intervals are closed and adjacency is allowed with no buffer, so two assignments that merely touch at the boundary are counted by their actual date overlap only. **Exterior weather** (priority 11, `ERR_WEATHER_UNSUITABLE`, HTTP 422): when `requires_exterior_weather` is true, every date from the start through the end must have a recorded weather window whose `exterior_suitable` flag is true; a missing or unsuitable day fails the booking.

Crew assignments can be listed (filtered by `project_id`, `crew_member_id`, `equipment_id`, or `status`) and retrieved individually.

### 3.6. Running the Job: Work, Crew Progress, and the Walkthrough

Once a project is `SCHEDULED`, the project manager starts the work, advancing `workflow_status` from `SCHEDULED` to `IN_PROGRESS` (rejected with `ERR_PROJECT_NOT_SCHEDULED` if the project is not in `SCHEDULED`).

In the field, a crew member drives each assignment through its short lifecycle. Beginning an assignment moves it from `SCHEDULED` to `IN_PROGRESS`; this requires the assignment to be `SCHEDULED` (otherwise `ERR_ASSIGNMENT_NOT_SCHEDULED`) and — a cross-entity guard — the parent project to be `IN_PROGRESS` (otherwise `ERR_PROJECT_NOT_IN_PROGRESS`). Completing an assignment moves it from `IN_PROGRESS` to `DONE` (rejected with `ERR_ASSIGNMENT_NOT_IN_PROGRESS` if not in progress); on completion the assignment's days leave the crew member's `scheduled_day_count` and any reserved equipment units are released from `units_reserved`, because the work is finished. A project manager may instead cancel an assignment from either `SCHEDULED` or `IN_PROGRESS` (otherwise `ERR_ASSIGNMENT_NOT_CANCELLABLE`); cancellation moves it to `CANCELLED` and likewise subtracts its `day_count` from the crew member's `scheduled_day_count` and releases its equipment reservation. Whether an assignment ends by completion or by cancellation, the conserved counters return to their pre-assignment levels.

When the painting is finished, the project manager requests a walkthrough, moving the project from `IN_PROGRESS` to `WALKTHROUGH_PENDING`. This requires the project to be `IN_PROGRESS` (otherwise `ERR_PROJECT_NOT_IN_PROGRESS`) and every crew assignment to be `DONE` or `CANCELLED` (otherwise `ERR_CREW_NOT_DONE`). The transition has three effects: every non-`REMOVED` surface moves to `EXECUTED` and its line item's `executed` flag becomes true; the project's `workflow_status` becomes `WALKTHROUGH_PENDING`; and the system opens a fresh **walkthrough** record in `PENDING` status (its `project_id` is set by the system and its `punch_list_count` defaults to 0).

### 3.7. Walkthrough Outcome and Project Completion

The homeowner runs the walkthrough. Passing it requires the walkthrough to be `PENDING` (otherwise `ERR_WALKTHROUGH_NOT_PENDING`), the `punch_list_count` to be exactly 0 (otherwise `ERR_PUNCH_LIST_OPEN`, since open defects block a pass), and the parent project to be in `WALKTHROUGH_PENDING` (otherwise `ERR_PROJECT_NOT_IN_WALKTHROUGH`). The effect of a pass depends on the money axis: if the project's `payment_status` is already `PAID_IN_FULL`, passing cascades the project to `COMPLETED`; otherwise the walkthrough is recorded as passed and the project stays in `WALKTHROUGH_PENDING` awaiting final payment. Because completion additionally requires `PAID_IN_FULL`, an attempt to complete while a balance is outstanding surfaces as `ERR_BALANCE_OUTSTANDING`.

Failing a walkthrough requires it to be `PENDING` (otherwise `ERR_WALKTHROUGH_NOT_PENDING`) and moves it to `FAILED`. A failed walkthrough is not terminal: the project manager may reopen it, which requires the walkthrough to be `FAILED` (otherwise `ERR_WALKTHROUGH_NOT_FAILED`), resets `punch_list_count` to the value supplied in the reopen payload (defaulting to 0 when none is supplied), and returns the walkthrough to `PENDING` for another inspection. Walkthroughs may be listed (filtered by `project_id` or `status`) and retrieved individually.

The **completion transition** — whether reached by a pass under full payment or by a final payment arriving while a walkthrough already sits passed — does the final accounting. It computes `final_total_cents` as the sum, over the line items whose surface is `EXECUTED`, of each such line item's material plus labor cost (summing the per-line-item whole-cent figures). This final total diverges from the frozen `estimate_total_cents` whenever an approved change order added, removed, or revised scope after finalization. The transition also sets `warranty_expires_at` to the completion timestamp plus the project's `warranty_months` months, and advances `workflow_status` to `COMPLETED`.

### 3.8. The Money Axis: Deposit and Final Payment

The payment axis evolves independently of the workflow axis, subject only to the guards stated here. A homeowner records a payment by supplying the `project_id`, the `kind` (either `DEPOSIT` or `FINAL`), and the `amount_cents` captured (at least 1). Each payment is inserted as a row in `CAPTURED` status, the project's `amount_paid_cents` increases by the captured amount, and `balance_due_cents` is recomputed.

A **deposit** payment carries `kind` `DEPOSIT` and drives the axis from `UNPAID` to `DEPOSIT_PAID`. It is allowed only when `payment_status` is `UNPAID` (otherwise `ERR_DEPOSIT_ALREADY_PAID`) and the project's `workflow_status` is `ESTIMATED` (otherwise `ERR_PROJECT_NOT_ESTIMATED`), and the amount tendered must equal `deposit_due_cents` exactly (otherwise `ERR_DEPOSIT_AMOUNT_MISMATCH`, HTTP 402). On success the axis becomes `DEPOSIT_PAID`.

A **final** payment carries `kind` `FINAL` and drives the axis from `DEPOSIT_PAID` to `PAID_IN_FULL`. It is allowed only when `payment_status` is `DEPOSIT_PAID` (otherwise `ERR_FINAL_BEFORE_DEPOSIT`) and the project's `workflow_status` is `WALKTHROUGH_PENDING` (otherwise `ERR_PROJECT_NOT_IN_WALKTHROUGH`), and the amount tendered must equal the current `balance_due_cents` exactly (otherwise `ERR_FINAL_AMOUNT_MISMATCH`, HTTP 402). On success `amount_paid_cents` rises, `balance_due_cents` is recomputed to 0, and the axis becomes `PAID_IN_FULL`. Because completion requires both a passed walkthrough and `PAID_IN_FULL`, a final payment arriving after the walkthrough has already passed is itself what tips the project into `COMPLETED`. Throughout, `deposit_due_cents` is pinned to the frozen estimate while `balance_due_cents` tracks the live revised total, so a change order shifts the final payment without ever re-opening the deposit. Payments may be listed (filtered by `project_id` or `kind`) and retrieved individually.

### 3.9. Change Orders: Authoring, Approval, and Cascading Re-Pricing

Scope changes flow through **change orders**, the system's most intricate workflow. An estimator authors a change order by supplying the `project_id`, the `expected_project_version` (the project version the author last observed — see §2.7), a `reason` for the change, and an `action` that is one of `ADD_SURFACE`, `REMOVE_SURFACE`, or `REVISE_SURFACE`. A `target_surface_id` names the surface being removed or revised and is required for `REMOVE_SURFACE` and `REVISE_SURFACE` (defaulting to null and unused for `ADD_SURFACE`). The new-scope fields — `new_label`, `new_surface_kind`, `new_area_sqft`, `new_coats` (1 through 4 when present), `new_prep_level`, and `new_paint_product_id` — describe the surface to add (for `ADD_SURFACE`) or the revised values (for `REVISE_SURFACE`); each defaults to null. As established in §2.7, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) when `expected_project_version` does not match the project's current `version`. A new change order begins in `DRAFT` with its `delta_total_cents` at 0.

Submitting a draft change order computes its prospective price delta and moves it to `SUBMITTED`. Submission requires the order to be in `DRAFT` (otherwise `ERR_CHANGE_ORDER_NOT_DRAFT`) and the parent project's `workflow_status` to be one of `ESTIMATED`, `SCHEDULED`, or `IN_PROGRESS` (otherwise `ERR_PROJECT_NOT_CHANGEABLE`). The **delta** is computed as a signed change to the totals: for an `ADD_SURFACE`, the delta is the new surface's material cost plus its labor cost; for a `REMOVE_SURFACE`, the delta is the negative of the target surface's current material plus labor cost; for a `REVISE_SURFACE`, the delta is the revised surface's material plus labor cost minus the target surface's current material plus labor cost. The new or revised line-item costs are computed with the same material-estimate and labor-estimate rules of §3.2 over the new-scope fields and the referenced paint product.

Approval is performed by the homeowner and is where the deep cascade fires. Approval requires the order to be `SUBMITTED` (otherwise `ERR_CHANGE_ORDER_NOT_SUBMITTED`) and the parent project to be `ESTIMATED`, `SCHEDULED`, or `IN_PROGRESS` (otherwise `ERR_PROJECT_NOT_CHANGEABLE`). On approval the surface change is applied first: an `ADD_SURFACE` creates a new `PLANNED` surface from the new-scope fields together with its line item; a `REMOVE_SURFACE` sets the target surface's `status` to `REMOVED` and drops its line item from the live total; a `REVISE_SURFACE` overwrites the target surface's fields with the new-scope values and recomputes its line item. The surface and line-item mutation then re-derives the live `revised_total_cents` as the sum over all non-`REMOVED` line items of each line item's material plus labor cost, and `balance_due_cents` is recomputed from the new revised total. The frozen `estimate_total_cents` and the pinned `deposit_due_cents` are deliberately **not** touched. Finally the order records its `applied_project_version` as the project's `version` after the cascade, the project's `version` is incremented by one, and the order moves to `APPROVED`. This single approval therefore ripples three levels deep: surface mutation, line-item recompute, then revised-total and balance recompute.

Rejection and revision form a loop. A homeowner may reject a submitted order, which requires `SUBMITTED` status (otherwise `ERR_CHANGE_ORDER_NOT_SUBMITTED`) and moves it to `REJECTED`; crucially, a rejection performs no surface or total mutation, so `revised_total_cents` and `estimate_total_cents` are left exactly as they were. From `REJECTED`, the estimator may revise the order back to `DRAFT`, which requires `REJECTED` status (otherwise `ERR_CHANGE_ORDER_NOT_REJECTED`); revision overwrites the order's editable fields — any of `reason`, `action`, `target_surface_id`, `new_label`, `new_surface_kind`, `new_area_sqft`, `new_coats`, `new_prep_level`, and `new_paint_product_id` supplied in the revise payload — resets `delta_total_cents` to 0 (it is recomputed on the next submit), and returns the order to `DRAFT`. Change orders can be listed (filtered by `project_id`, `target_surface_id`, `new_paint_product_id`, or `status`) and retrieved individually.

### 3.10. Cancelling a Project

A project manager may cancel a project while it is `DRAFT`, `ESTIMATED`, or `SCHEDULED` (otherwise `ERR_PROJECT_NOT_CANCELLABLE`). Cancellation runs a compensating cascade: every crew assignment that is `SCHEDULED` or `IN_PROGRESS` moves to `CANCELLED`, releasing the corresponding crew `scheduled_day_count` and equipment `units_reserved`; every `CAPTURED` payment moves to `REFUNDED` and the project's `amount_paid_cents` is recomputed to 0; and the project's `workflow_status` becomes `CANCELLED`. Because the conserved utilization counters are released on cancellation just as they are on completion, the crew and equipment books return to their pre-project levels.

### 3.11. The Touch-Up Warranty

After completion, the homeowner may file **warranty claims** for touch-up work within the warranty window. Filing a claim carries the `project_id`, the `surface_id` of the surface needing touch-up, a `description` of the defect, and a client-supplied `filed_at` timestamp (ISO 8601 UTC). Two ordered checks gate filing: first, the parent project must be `COMPLETED` (otherwise `ERR_PROJECT_NOT_COMPLETED`, HTTP 409, checked before the window check); then `filed_at` must be no later than the project's `warranty_expires_at` (otherwise `ERR_WARRANTY_EXPIRED`, HTTP 409). The expiry is inclusive — a claim filed at the exact expiry instant is accepted, while one filed even a millisecond later is rejected. A filed claim begins in `FILED` status.

On filing, the system computes a **provisional payout**, an estimate of the rework cost. The `provisional_payout_cents` is the target surface's line-item labor cost multiplied by a touch-up labor fraction of 0.20 (twenty percent), rounded half-up to whole cents. This provisional figure stands as the estimate of rework scope until the claim is resolved.

A project manager triages each claim. Approving a filed claim requires `FILED` status (otherwise `ERR_CLAIM_NOT_FILED`) and moves it to `APPROVED`. Denying a filed claim likewise requires `FILED` status (otherwise `ERR_CLAIM_NOT_FILED`) and moves it to `DENIED`, a terminal outcome. Resolving an approved claim requires `APPROVED` status (otherwise `ERR_CLAIM_NOT_APPROVED`) and a supplied `logged_touchup_hours` value that must be present and at least 0 (otherwise `ERR_TOUCHUP_HOURS_REQUIRED`, HTTP 422). Resolution computes the **final payout**: `final_payout_cents` is the logged touch-up hours multiplied by the labor rate of 6550 cents per hour, rounded half-up to whole cents, and the claim moves to `RESOLVED`. The final payout is derived from the actual logged hours and therefore diverges from the provisional twenty-percent estimate whenever real rework differs from the estimate. Warranty claims can be listed (filtered by `project_id`, `surface_id`, or `status`) and retrieved individually.

### 3.12. Validation Ordering and the Test-Driving Clock

Across every write endpoint, validations are evaluated in a fixed priority order so that the same request always fails for the same reason. The order is: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT`, 401); (2) role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`, 403); (3) existence of every path identifier and body foreign key, resolved left-to-right (the matching 404 not-found code from §2.6); (4) request-body well-formedness — body present, types correct, enum values legal, required fields present, and numeric ranges honored, namely `area_sqft` at least 1, `coats` from 1 through 4, `deposit_pct` from 0 through 100, `precipitation_pct` from 0 through 100, `amount_cents` at least 1, and `end_date` on or after `start_date` (`ERR_INVALID_REQUEST`, 422); (5) state correctness for the requested transition (the relevant state code, 409); and (6) on change-order creation only, the optimistic-concurrency stale-version check (`ERR_STALE_PROJECT_VERSION`, 412). The domain checks that follow — product/surface compatibility, crew skill, double-booking, equipment capacity, weather, payment-amount equality, and the warranty checks — run after these foundational gates, in the order their respective sections describe; for crew-assignment creation specifically, skill adequacy is checked, then double-booking, then equipment capacity, then weather.

For deterministic testing of completion timestamps and warranty expiry, an administrative test-driving capability lets a project manager pin the server's current UTC clock to a supplied instant. The request supplies a `to_iso8601` value, and the server's notion of "now" returns that instant until the clock is set again. This pinned clock is what stamps a project's completion time and therefore its `warranty_expires_at`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state-transition actions and the test-driving clock — return `200 OK`. All endpoints are mounted under `/painting` except the administrative clock endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/painting/paint-products` | Create a paint product catalog entry | Estimator |
| GET | `/painting/paint-products` | List paint products; optional `surface_kind` filter | Estimator, ProjectManager, Customer, CrewMember |
| GET | `/painting/paint-products/{paintProductId}` | Get a paint product | Estimator, ProjectManager, Customer, CrewMember |
| POST | `/painting/crew-members` | Create a crew member | ProjectManager |
| GET | `/painting/crew-members` | List crew members | ProjectManager, Estimator |
| GET | `/painting/crew-members/{crewMemberId}` | Get a crew member | ProjectManager, Estimator |
| POST | `/painting/equipment` | Create a shared equipment resource | ProjectManager |
| GET | `/painting/equipment` | List equipment | ProjectManager, Estimator |
| GET | `/painting/equipment/{equipmentId}` | Get an equipment resource | ProjectManager, Estimator |
| POST | `/painting/weather-windows` | Record a daily weather forecast | ProjectManager |
| GET | `/painting/weather-windows` | List weather windows; optional `window_date` filter | ProjectManager, Estimator, CrewMember |
| GET | `/painting/weather-windows/{weatherWindowId}` | Get a weather window | ProjectManager, Estimator, CrewMember |
| POST | `/painting/projects` | Create a painting project in DRAFT/UNPAID | Estimator |
| GET | `/painting/projects` | List projects; optional `customer_id` filter | Estimator, ProjectManager, Customer |
| GET | `/painting/projects/{projectId}` | Get a project | Estimator, ProjectManager, Customer |
| POST | `/painting/projects/{projectId}/finalize-estimate` | Finalize and freeze the estimate; DRAFT to ESTIMATED | Estimator |
| POST | `/painting/projects/{projectId}/schedule` | Move ESTIMATED to SCHEDULED | ProjectManager |
| POST | `/painting/projects/{projectId}/start-work` | Move SCHEDULED to IN_PROGRESS | ProjectManager |
| POST | `/painting/projects/{projectId}/request-walkthrough` | Move IN_PROGRESS to WALKTHROUGH_PENDING; open a walkthrough | ProjectManager |
| POST | `/painting/projects/{projectId}/cancel` | Cancel a DRAFT/ESTIMATED/SCHEDULED project | ProjectManager |
| POST | `/painting/surfaces` | Add a PLANNED surface; auto-create its line item | Estimator |
| GET | `/painting/surfaces` | List surfaces; filter by `project_id`, `paint_product_id`, `status` | Estimator, ProjectManager, Customer |
| GET | `/painting/surfaces/{surfaceId}` | Get a surface | Estimator, ProjectManager, Customer |
| GET | `/painting/line-items` | List line items; filter by `project_id`, `surface_id` | Estimator, ProjectManager, Customer |
| GET | `/painting/line-items/{lineItemId}` | Get a line item | Estimator, ProjectManager, Customer |
| POST | `/painting/color-selections` | Propose a color for a surface | Estimator, Customer |
| GET | `/painting/color-selections` | List color selections; filter by `project_id`, `surface_id` | Estimator, ProjectManager, Customer |
| GET | `/painting/color-selections/{colorSelectionId}` | Get a color selection | Estimator, ProjectManager, Customer |
| POST | `/painting/color-selections/{colorSelectionId}/approve` | Customer approves a proposed color | Customer |
| POST | `/painting/color-selections/{colorSelectionId}/reject` | Customer rejects a proposed color | Customer |
| POST | `/painting/change-orders` | Author a change order against the project version (OCC) | Estimator |
| GET | `/painting/change-orders` | List change orders; filter by `project_id`, `target_surface_id`, `new_paint_product_id`, `status` | Estimator, ProjectManager, Customer |
| GET | `/painting/change-orders/{changeOrderId}` | Get a change order | Estimator, ProjectManager, Customer |
| POST | `/painting/change-orders/{changeOrderId}/submit` | Submit a DRAFT change order (compute delta) | Estimator |
| POST | `/painting/change-orders/{changeOrderId}/approve` | Customer approves; apply surface mutation and re-price | Customer |
| POST | `/painting/change-orders/{changeOrderId}/reject` | Customer rejects a submitted change order | Customer |
| POST | `/painting/change-orders/{changeOrderId}/revise` | Estimator revises a rejected order back to DRAFT | Estimator |
| POST | `/painting/crew-assignments` | Schedule a crew member (and optional equipment) for a window | ProjectManager |
| GET | `/painting/crew-assignments` | List crew assignments; filter by `project_id`, `crew_member_id`, `equipment_id`, `status` | ProjectManager, Estimator, CrewMember |
| GET | `/painting/crew-assignments/{assignmentId}` | Get a crew assignment | ProjectManager, Estimator, CrewMember |
| POST | `/painting/crew-assignments/{assignmentId}/begin` | Crew begins work (project must be IN_PROGRESS) | CrewMember |
| POST | `/painting/crew-assignments/{assignmentId}/complete` | Crew completes work | CrewMember |
| POST | `/painting/crew-assignments/{assignmentId}/cancel` | Cancel an assignment; release crew/equipment | ProjectManager |
| POST | `/painting/payments` | Record a deposit or final payment | Customer |
| GET | `/painting/payments` | List payments; filter by `project_id`, `kind` | Estimator, ProjectManager, Customer |
| GET | `/painting/payments/{paymentId}` | Get a payment | Estimator, ProjectManager, Customer |
| GET | `/painting/walkthroughs` | List walkthroughs; filter by `project_id`, `status` | Estimator, ProjectManager, Customer |
| GET | `/painting/walkthroughs/{walkthroughId}` | Get a walkthrough | Estimator, ProjectManager, Customer |
| POST | `/painting/walkthroughs/{walkthroughId}/pass` | Customer passes the walkthrough | Customer |
| POST | `/painting/walkthroughs/{walkthroughId}/fail` | Customer fails the walkthrough | Customer |
| POST | `/painting/walkthroughs/{walkthroughId}/reopen` | PM reopens a failed walkthrough | ProjectManager |
| POST | `/painting/warranty-claims` | File a touch-up warranty claim | Customer |
| GET | `/painting/warranty-claims` | List warranty claims; filter by `project_id`, `surface_id`, `status` | Estimator, ProjectManager, Customer |
| GET | `/painting/warranty-claims/{claimId}` | Get a warranty claim | Estimator, ProjectManager, Customer |
| POST | `/painting/warranty-claims/{claimId}/approve` | PM approves a filed claim | ProjectManager |
| POST | `/painting/warranty-claims/{claimId}/deny` | PM denies a filed claim | ProjectManager |
| POST | `/painting/warranty-claims/{claimId}/resolve` | PM resolves an approved claim with logged hours | ProjectManager |
| POST | `/_clock/set_current_utc` | Test-driving: pin the server clock | ProjectManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_SURFACE_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_COLOR_SELECTION_NOT_FOUND` | 404 Not Found |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_WALKTHROUGH_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PAINT_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_WEATHER_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_PROJECT_NOT_DRAFT` | 409 Conflict |
| `ERR_NO_SURFACES` | 409 Conflict |
| `ERR_PROJECT_NOT_ESTIMATED` | 409 Conflict |
| `ERR_DEPOSIT_NOT_PAID` | 409 Conflict |
| `ERR_COLOR_NOT_APPROVED` | 409 Conflict |
| `ERR_NO_CREW_SCHEDULED` | 409 Conflict |
| `ERR_PROJECT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_PROJECT_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_CREW_NOT_DONE` | 409 Conflict |
| `ERR_PROJECT_NOT_IN_WALKTHROUGH` | 409 Conflict |
| `ERR_BALANCE_OUTSTANDING` | 409 Conflict |
| `ERR_PROJECT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PROJECT_NOT_CHANGEABLE` | 409 Conflict |
| `ERR_DEPOSIT_ALREADY_PAID` | 409 Conflict |
| `ERR_FINAL_BEFORE_DEPOSIT` | 409 Conflict |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 402 Payment Required |
| `ERR_FINAL_AMOUNT_MISMATCH` | 402 Payment Required |
| `ERR_CHANGE_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_CHANGE_ORDER_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CHANGE_ORDER_NOT_REJECTED` | 409 Conflict |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_COLOR_NOT_PROPOSED` | 409 Conflict |
| `ERR_SURFACE_NOT_PLANNED` | 409 Conflict |
| `ERR_PRODUCT_SURFACE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_CREW_SKILL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_EQUIPMENT_OVERBOOKED` | 409 Conflict |
| `ERR_WEATHER_UNSUITABLE` | 422 Unprocessable Entity |
| `ERR_WALKTHROUGH_NOT_PENDING` | 409 Conflict |
| `ERR_WALKTHROUGH_NOT_FAILED` | 409 Conflict |
| `ERR_PUNCH_LIST_OPEN` | 409 Conflict |
| `ERR_CLAIM_NOT_FILED` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_TOUCHUP_HOURS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_PROJECT_NOT_COMPLETED` | 409 Conflict |
