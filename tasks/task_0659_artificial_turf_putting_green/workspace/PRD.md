# Turf Install API — Product Requirements Document

## 1. Introduction

The Turf Install API coordinates the end-to-end delivery of an artificial-turf and putting-green installation business, from the first visit a sales representative makes to a customer's yard through the final close-out of a fully paid, fully serviced job. A single installation is a long-lived engagement: someone measures the site, drafts one or more design layouts against a turf and infill catalog, prices the base preparation and drainage, issues a quote, collects a deposit, schedules a certified crew, completes the install, activates a warranty, and fields any post-install callbacks. Each of those steps has its own preconditions, its own money implications, and its own way of going wrong, and the business needs every one of them tracked precisely so that no job is scheduled before it is paid for, no crew is sent to a job it is not certified to perform, and no quote is accepted twice.

The organizing entity is the **Project**, which acts as the aggregate root for everything that happens on one installation address. A Project carries two independent status dimensions at the same time: a workflow dimension that tracks where the job sits in the operational pipeline, and a finance dimension that tracks the deposit-and-balance ledger lifecycle. These two dimensions advance on their own schedules — a job can be physically installed while its balance is still outstanding — and the system keeps both reconciled against the underlying child resources at all times. Four roles collaborate around the Project: a sales representative who owns the pre-sale pipeline, a scheduler who owns crews and installation, a customer who approves and pays on their own project, and an operations administrator who manages the catalog and holds operational override across the whole system.

This document specifies the global contracts that every endpoint shares (Section 2), the business logic and lifecycle workflows that make up the heart of the system (Section 3), the endpoint catalog (Section 4), and the error code catalog (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `OpsAdmin`, `SalesRep`, `Scheduler`, and `Customer`. When a role is authenticated but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The `OpsAdmin` role is the operational superuser. Its identity in `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and act on it but never compares it to any entity's `id`. An `OpsAdmin` exclusively controls catalog management, project close and cancel, payment settlement and failure, and the logical clock, and additionally inherits every operation available to the other three roles as an operational override.

The `SalesRep` role owns the pre-sale pipeline — customers, site measures, design layouts, base-prep scopes, quotes, and warranty plans. The `Scheduler` role owns crews, installation scheduling, and callback servicing. Both `SalesRep` and `Scheduler` carry an opaque `X-User-ID` that is an operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

The `Customer` role is different: its identity is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`, and ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `Customer` may act only on a project they own, where ownership means the project's `customer_id` equals the caller's `X-User-ID`. A `Customer` who targets a project that is not theirs is rejected with `ERR_NOT_PROJECT_OWNER`. This ownership rule governs the customer-facing operations — accepting a quote, recording a payment, opening or cancelling a callback, and reading the project, its ledger, quotes, payments, install jobs, warranty plans, and callbacks.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these bounds is rejected with `ERR_VALIDATION_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every primary resource carries a server-minted `id`, formatted as a UUID with no type prefix, used for identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created.

Most resources additionally carry an `updated_at` field — an ISO 8601 UTC timestamp refreshed on every mutation, including those caused by cascades — and a `version` field, a system-managed integer that starts at 1 and increases by one on every mutation. These two fields are present on `Project`, `Customer`, `SiteMeasure`, `DesignLayout`, `BasePrepScope`, `Quote`, `Crew`, `InstallJob`, `WarrantyPlan`, and `Callback`.

Three resource types are exceptions and carry only `id` and `created_at`, with no `updated_at` and no `version`: `TurfProduct`, `InfillProduct`, and `Payment`. A `TurfProduct` and an `InfillProduct` are catalog records, and a `Payment` is an immutable ledger entry whose only mutation is a one-way status change driven by the settlement and failure drivers; for these three, no `updated_at` or `version` is emitted.

### 2.5. Money, Areas, and Rounding Discipline

All monetary amounts in the system are stored and returned as integer counts of cents — there are no fractional cents and no floating-point money. Wherever a money value is derived by multiplying an area by a per-square-foot rate or by applying a percentage, the result is rounded using the round-half-up method to a whole number of cents.

The rounding discipline is strict about **order of operations**, and this matters most when several line items are summed. Whenever the specification calls for rounding per line item, each line is rounded to whole cents first and only then are the rounded lines added together; the system never sums raw products and rounds once at the end. Where the specification instead sums values that are already integers (as in the project ledger), no rounding occurs because integer addition is exact.

Areas are carried in square feet. The one derived area that is stored with fractional precision, `net_area_sqft`, is rounded half-up to two decimal places; the project's rolled-up `billable_area_sqft` likewise carries two decimals.

### 2.6. Parallel Status Dimensions and Cascade Consistency

A `Project` simultaneously tracks two independent status fields. The `workflow_status` field follows the operational pipeline through the values `DRAFT`, `MEASURED`, `DESIGNED`, `QUOTED`, `DEPOSIT_PAID`, `SCHEDULED`, `INSTALLED`, `CLOSED`, and `CANCELLED`, beginning at `DRAFT`. The `finance_status` field follows the ledger lifecycle through `UNBILLED`, `DEPOSIT_DUE`, `DEPOSIT_SETTLED`, `BALANCE_DUE`, `PAID_IN_FULL`, and `REFUNDED`, beginning at `UNBILLED`. The two dimensions advance independently: a workflow event such as completing an install can nudge the finance dimension, and a finance event such as a deposit settling can nudge the workflow dimension, but neither is a function of the other.

Many operations on a child resource ripple upward into the `Project`. When such a ripple occurs, the parent is genuinely mutated: its `updated_at` is refreshed and its `version` increments by one, exactly as for a direct edit. The rolled-up fields on `Project` — `billable_area_sqft`, `contract_total_cents`, `deposit_paid_cents`, `balance_paid_cents`, `amount_refunded_cents`, `outstanding_balance_cents`, and `open_callback_count` — are computed from the project's children rather than written directly, and they are recomputed whenever a relevant child changes. The `variant` field is similarly derived, copied from the accepted design.

### 2.7. Nested Resource Retrieval and Reference Resolution

Every resource that lives under a project is addressed by a path that names the project first and the child second, and each such child carries a `project_id` linking it back to its owning project. The system validates path identifiers left to right: the project is resolved before any child, and a missing identifier anywhere in the path produces `ERR_NOT_FOUND` for the first identifier that does not resolve. A request for a quote under a project that does not exist therefore fails on the project before the quote is ever consulted.

Reference resolution is separate from path resolution. When a request body names a foreign resource — a `turf_product_id`, `infill_product_id`, `site_measure_id`, `crew_id`, `design_layout_id`, `base_prep_scope_id`, or `warranty_plan_id` — and that referenced resource does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. This reference check applies to design-layout creation, base-prep-scope creation, quote creation, install-job creation, and callback creation.

### 2.8. Optimistic Concurrency on Quote Acceptance

Quote acceptance is the one write in the system that is guarded by optimistic concurrency control on the project. A customer accepting a sent quote must supply `expected_project_version` in the request body, carrying the `version` of the `Project` as the client last observed it. If that value does not match the project's current `version`, the acceptance is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP status 412.

This guard exists because two distinct quotes on the same project can each be a legitimate acceptance target at the same time. Accepting one quote voids the other sibling quotes and advances the project's finance dimension, which bumps the project's `version`. A client that read the project before that happened and then tries to accept a different quote is working from a stale view; the version check rejects that acceptance deterministically rather than letting it overwrite a decision the client never saw. No other endpoint takes a version field; quote acceptance is the sole OCC-protected write.

### 2.9. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the failure a client sees is always the most fundamental one. Authentication comes first: the presence of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`) is checked before anything else. Role permission for the operation (`ERR_FORBIDDEN_ROLE`) is checked next, followed by customer ownership of the project (`ERR_NOT_PROJECT_OWNER`). Existence of the path resources (`ERR_NOT_FOUND`) is then confirmed left to right, after which referenced foreign keys in the body are confirmed (`ERR_REFERENCE_NOT_FOUND`). Only then does the system check that the body is well-formed — required fields present and well-typed, enum values within their declared domain, and numeric ranges respected such as areas being greater than zero and `deposit_pct` lying within its allowed band (`ERR_INVALID_REQUEST`). Duplicate-resource checks (`ERR_DUPLICATE_RESOURCE`) follow. State validity for the requested transition (`ERR_INVALID_STATE`) comes next, then the optimistic-concurrency check on quote acceptance (`ERR_STALE_PROJECT_VERSION`). After those, the domain-specific business-safety, capacity, temporal, referential, and fiscal rules described throughout Section 3 apply. In short: authentication, then authorization, then ownership, then path existence, then reference existence, then request well-formedness, then duplicates, then state, then concurrency, then the remaining business rules.

## 3. Business Logic & Workflows

### 3.1. Opening a Project and Measuring the Site

A project begins when a `SalesRep` or `OpsAdmin` creates it, supplying the `customer_id` of the owning customer and the free-text `site_address` of the install site. A freshly created project starts with `workflow_status` of `DRAFT` and `finance_status` of `UNBILLED`, and every computed rollup — billable area, contract total, deposit and balance paid, refunded amount, outstanding balance, and open callback count — begins at zero, with `variant` and the contract figure unset until later milestones. Customers themselves are created independently by a `SalesRep` or `OpsAdmin` with a `full_name` and an `email`; the email is unique case-insensitively, and a collision is rejected with `ERR_DUPLICATE_RESOURCE`.

The first substantive step is the site measurement. A `SalesRep` records a measure against a `DRAFT` project, providing the measured `gross_area_sqft` (the gross area before waste, which must be greater than zero), an optional `obstruction_area_sqft` for non-turf cutouts such as trees and beds (which must be at least zero and defaults to zero), the `longest_run_ft` (the longest straight dimension, greater than zero), the `slope_pct` (the average grade percentage, at least zero), and an optional `soil_drains_freely` flag (defaulting to true). Each new measure is created with a `status` of `RECORDED`, and any measure previously in `RECORDED` status on the same project is moved to `SUPERSEDED` so that only the latest measure feeds the design. Recording the very first measure advances the project from `DRAFT` to `MEASURED` and increments the project's `version`.

### 3.2. Designing the Layout and Computing Waste

Once a project is `MEASURED`, a `SalesRep` drafts one or more design layouts. A design names the `site_measure_id` it draws from, the chosen `turf_product_id` and `infill_product_id`, and the `variant`, which is one of `STANDARD`, `PET`, `PLAYGROUND`, or `PUTTING_GREEN`. Each design is created in `DRAFT` status. The turf catalog entries carry a `sku`, a `name`, a `pile_height_mm` blade height, a `price_per_sqft_cents` material cost, a `roll_width_ft`, and the rating flags `pet_approved`, `playground_rated`, and `putting_rated`, along with an `active` flag; infill catalog entries carry a `sku`, a `name`, a `material` (one of `SILICA`, `ACRYLIC_COATED`, `ZEOLITE`, `RUBBER`, `CORK`), a `price_per_sqft_cents`, a `coverage_lbs_per_sqft` spread rate, the `antimicrobial` and `nonabrasive` flags, and an `active` flag.

At design creation the system computes the roll-waste percentage and the net area. The number of roll runs needed is the longest straight run dimension divided by the selected turf's roll width, rounded up to the next whole run. The waste factor `waste_factor_pct` is then assigned by tier: one run or fewer yields a 5.0 percent waste factor, exactly two runs yields 8.0 percent, three or four runs yields 12.0 percent, and five or more runs yields 15.0 percent. The `net_area_sqft` is the gross area minus the obstruction area, multiplied by one plus the waste factor expressed as a fraction (so a 12.0 percent factor multiplies by 1.12), and the result is rounded half-up to two decimal places. The inputs come from the latest `RECORDED` site measure for gross area, obstruction area, and longest run, together with the selected turf product's roll width.

Accepting a design is the gate that turns a drafted layout into the project's chosen build. A `SalesRep` accepts a design only while it is in `DRAFT` status and only when no other design on the project is already `ACCEPTED`; an attempt to accept a second design when one is already accepted is rejected with `ERR_DESIGN_ALREADY_ACCEPTED`. Acceptance also enforces product compatibility and product availability, described in Section 3.3. A successful acceptance moves the design's `status` from `DRAFT` to `ACCEPTED`; copies the design's `variant` onto the project's `variant`; recomputes the project's `billable_area_sqft` as the accepted design's net area; advances the project's workflow dimension from `MEASURED` to `DESIGNED`; and increments both the design's `version` and the project's `version`. Rejecting a design is the sibling branch: a `SalesRep` may reject a design while it is in `DRAFT` status, which moves its `status` from `DRAFT` to `REJECTED`, increments only the design's `version`, and makes no change at the project level — it is a pure branch divergence with none of the acceptance cascade.

### 3.3. Product Compatibility, Variant Surcharges, and Catalog Retirement

A design may only be accepted if the selected products are both rated for the variant and still active. The variant-compatibility rule, enforced at acceptance with `ERR_VARIANT_PRODUCT_MISMATCH`, is the following: a `PET` design requires that the turf has `pet_approved` set and that the infill has `antimicrobial` set; a `PLAYGROUND` design requires that the turf has `playground_rated` set and that the infill has `nonabrasive` set; and a `PUTTING_GREEN` design requires that the turf has `putting_rated` set. A `STANDARD` design carries no product-rating requirement. Separately, the selected turf and infill must both have `active` set to true; a design naming a retired turf or infill product is rejected with `ERR_PRODUCT_RETIRED`. A retired catalog product (with `active` false) is excluded from new design selection.

The variant a project carries also drives a pricing surcharge applied later at quote time, expressed as a percentage of the material subtotal: a `STANDARD` job adds no surcharge, a `PET` job adds 12 percent, a `PLAYGROUND` job adds 18 percent, and a `PUTTING_GREEN` job adds 25 percent. The surcharge amount is the material subtotal multiplied by the variant percentage, rounded half-up to whole cents, and recorded as `variant_surcharge_cents`; the variant itself is copied onto the quote as `variant_kind` from the priced design's variant.

### 3.4. Base Preparation, Drainage Tiering, and Cost Freezing

With an accepted design in hand, a `SalesRep` prices the ground work by creating a base-prep scope, supplying the `design_layout_id` it prices against and the aggregate `base_depth_in` base depth in inches (greater than zero). The scope is created in `DRAFT` status, and at creation the system computes both the drainage tier and the two cost components.

The drainage tier is a categorical decision driven by three inputs that interact non-linearly: the latest `RECORDED` site measure's `slope_pct` and `soil_drains_freely`, together with the design's variant. The decision is evaluated in this order. First, if the variant is `PUTTING_GREEN`, the `drainage_tier` is `DRAINAGE_PANEL` — putting greens are always panel-drained regardless of soil or slope. Otherwise, if the soil does not drain freely and the slope is below 2.0 percent, the tier is `DRAINAGE_PANEL` (a flat site with poor soil needs a panel). Otherwise, if the slope is at least 5.0 percent or the soil does not drain freely, the tier is `FRENCH_DRAIN`. In every remaining case the tier is `NONE`.

The two cost components are computed from the priced design's net area. The `excavation_cost_cents` is the net area multiplied by the base depth in inches multiplied by an excavation rate of 22 cents per square-foot-inch, rounded half-up to whole cents. The `drainage_cost_cents` depends on the tier: a `NONE` tier costs nothing, a `FRENCH_DRAIN` tier costs the net area multiplied by 180 cents per square foot rounded half-up, and a `DRAINAGE_PANEL` tier costs the net area multiplied by 320 cents per square foot rounded half-up.

A base-prep scope must be finalized before its costs can feed a quote that goes out the door. A `SalesRep` finalizes a scope only while it is in `DRAFT` status and only when the design layout it references is `ACCEPTED`; finalization moves the scope's `status` from `DRAFT` to `FINALIZED`, freezes the excavation and drainage cost figures at their finalize-time values, and increments the scope's `version`.

### 3.5. Quoting: Pricing, Discounts, the Minimum Floor, and the Deposit

A `SalesRep` creates a quote against a project by naming the `design_layout_id` and the `base_prep_scope_id` to price, with an optional `promo_code` and an optional `deposit_pct` deposit percentage that defaults to 0.30. A new quote is created in `DRAFT` status. The pricing assembles the contract figure in a pinned order.

First, the material subtotal. The turf line is the priced design's net area multiplied by the turf's per-square-foot price, rounded half-up to whole cents; the infill line is the net area multiplied by the infill's per-square-foot price, rounded half-up to whole cents; and `material_subtotal_cents` is the sum of those two already-rounded lines. Each line is rounded before the two are added — never the other way around. Second, the `base_prep_subtotal_cents` is the sum of the finalized scope's excavation cost and drainage cost. Third, the `variant_surcharge_cents` is the material subtotal multiplied by the variant percentage from Section 3.3 (zero for `STANDARD`, 12 percent for `PET`, 18 percent for `PLAYGROUND`, 25 percent for `PUTTING_GREEN`), rounded half-up.

The pre-discount figure is the sum of the material subtotal, the base-prep subtotal, and the variant surcharge. Two discounts are then computed against that pre-discount figure and recorded together as `discount_cents`. The volume discount is keyed on the design's net area: a net area of at least 2000 square feet earns 10 percent, a net area of at least 1000 but below 2000 square feet earns 5 percent, and anything below 1000 square feet earns nothing; the volume discount is the pre-discount figure multiplied by that percentage, rounded half-up. The promo discount depends on the `promo_code`: the code `SPRING50` yields 5 percent of the pre-discount figure rounded half-up, the code `FLAT20000` yields a flat 20000 cents, and any other code or no code yields nothing. The two discounts are each computed and then summed to form the total discount.

The `subtotal_cents` is the pre-discount figure minus the total discount. The `total_cents` is that subtotal or the minimum-job floor of 150000 cents, whichever is greater — no job is contracted below the floor. The `total_cents` is the contract figure recorded when the quote is accepted.

The quote price behaves differently depending on the quote's status. While a quote is still in `DRAFT` it is an **estimate**: it is computed from the design's net area as currently drafted and is recomputed if the design is edited before the quote is sent, so it is not frozen. Once a quote is `SENT` (and thereafter while `ACCEPTED`), its `total_cents` is a **final** figure frozen at send time from the then-current finalized scope and accepted design; later design edits do not change a sent quote's total.

The deposit figure is derived from the total. The supplied `deposit_pct` is first clamped into the band between a minimum of 0.10 and a maximum of 0.50 — values below 0.10 are raised to 0.10 and values above 0.50 are lowered to 0.50. The `deposit_amount_cents` is the total multiplied by the clamped percentage, rounded half-up to whole cents, and it is frozen at send time. A `deposit_pct` supplied outside the 0.10-to-0.50 band on input is itself a range violation rejected with `ERR_INVALID_REQUEST` before clamping is ever reached; the clamp governs the internal computation, and the range check governs the accepted input domain. The quote also records its computed `material_subtotal_cents`, `base_prep_subtotal_cents`, `variant_surcharge_cents`, `discount_cents`, and `subtotal_cents` alongside the total and deposit figures, and tracks `superseded_by_quote_id`, which is null until a revision supersedes it.

### 3.6. The Quote Lifecycle: Send, Revise, Accept, Expire

A quote moves through `DRAFT`, `SENT`, `ACCEPTED`, `REVISED`, `EXPIRED`, and `VOID` over its life. Sending is performed by a `SalesRep` on a `DRAFT` quote, and only if the quote's referenced base-prep scope is `FINALIZED`; an attempt to send a quote whose scope is not finalized is rejected with `ERR_SCOPE_NOT_FINALIZED`. Sending moves the quote from `DRAFT` to `SENT`, freezes the total as the final figure, advances the project's workflow dimension from `DESIGNED` to `QUOTED`, and increments the project's `version`.

Revising lets the sales side replace an outstanding quote with a fresh draft. A `SalesRep` revises a quote only while it is `SENT` and only when the project has no `ACCEPTED` quote. Revision moves the original quote from `SENT` to `REVISED`, creates a successor quote in `DRAFT` that clones the original's `design_layout_id` and `base_prep_scope_id` (and accepts an optional new `promo_code` and `deposit_pct`), and sets the original's `superseded_by_quote_id` to the successor's id — a cyclic loop back to a fresh `DRAFT` row. The original quote's `version` increments.

Accepting is the customer's decision and the moment the finance dimension begins to move. A `Customer` (or `OpsAdmin` acting on their behalf) accepts a quote that is `SENT`, on a project whose `finance_status` is `UNBILLED`, supplying `expected_project_version` that must match the project's current `version` as described in Section 2.8 — a mismatch is rejected with `ERR_STALE_PROJECT_VERSION`. Acceptance moves the quote from `SENT` to `ACCEPTED`; voids every other non-terminal quote on the project (any sibling quote in `DRAFT`, `SENT`, or `REVISED` moves to `VOID`); advances the project's `finance_status` from `UNBILLED` to `DEPOSIT_DUE`; and increments both the quote's `version` and the project's `version`. A quote that is in `DRAFT`, `SENT`, or `REVISED` is moved to `VOID` whenever another quote on the project is accepted or the project is cancelled.

Quotes also age out. A quote that has been `SENT` and not accepted expires once the logical clock reaches its creation time plus the quote time-to-live of 30 days; on that condition a `SENT` quote moves to `EXPIRED` and its `version` increments. Any state transition attempted against a quote that is not in the required starting state is rejected with `ERR_INVALID_STATE`.

### 3.7. Collecting the Deposit and Advancing the Ledger

Payments are recorded against a project and settled through an operations driver. A `Customer` or `OpsAdmin` records a payment by supplying its `kind` — one of `DEPOSIT`, `BALANCE`, or `REFUND` — and its `amount_cents`, which must be greater than zero. A refund is recorded as a positive amount and subtracted in the ledger. Every payment is created in `PENDING` status; only an `OpsAdmin`, through the settlement driver, moves a payment from `PENDING` to `SETTLED`, and only `SETTLED` payments count toward the ledger. Both the settlement driver and the fail driver identify their target by a `payment_id`, and the fail driver moves a `PENDING` payment to `FAILED` with no ledger effect. A balance payment cannot be recorded before the project's `finance_status` is `BALANCE_DUE`; recording a `BALANCE` payment earlier is rejected with `ERR_BALANCE_NOT_DUE`.

The project ledger is computed by replaying the project's `SETTLED` payments in ascending `created_at` order, with ties broken by an internal monotonically increasing sequence captured when each payment was created rather than by id. The `deposit_paid_cents` is the sum of the amounts of settled deposits, the `balance_paid_cents` is the sum of the amounts of settled balance payments, and the `amount_refunded_cents` is the sum of the amounts of settled refunds. The signed outstanding figure is the contract total minus the deposit paid minus the balance paid plus the refunded amount; the `outstanding_balance_cents` exposed for display is that signed figure or zero, whichever is greater, while the signed value is what the ledger conserves. Because these are sums of integers, no rounding is involved. The ledger also offers a forward-projected view that additionally folds in `PENDING` payments as projected, producing a different outstanding figure from the settled-only view whenever pending payments exist; that projected view is requested by setting `include_pending` to true on the ledger read.

When a deposit payment settles, the ledger is recomputed and the project's status may advance on both dimensions. If the settled deposit total reaches at least the accepted quote's `deposit_amount_cents`, the finance dimension advances from `DEPOSIT_DUE` to `DEPOSIT_SETTLED`, and the workflow dimension advances from `QUOTED` to `DEPOSIT_PAID`; at that crossing the project's `contract_total_cents` is copied from the accepted quote's `total_cents`. If a settled deposit leaves the total still short of the required deposit amount, the project remains `DEPOSIT_DUE`; the settlement of a deposit that leaves the cumulative settled deposit below the required amount is rejected with `ERR_DEPOSIT_INSUFFICIENT`. Settling a deposit increments the project's `version`.

### 3.8. Scheduling the Crew

Once a project reaches `DEPOSIT_PAID`, a `Scheduler` schedules the installation by creating an install job that names the `crew_id` and an install window defined by `scheduled_start` (inclusive) and `scheduled_end` (exclusive). The window is half-open: an install whose end exactly equals the next install's start does not overlap. Crews are peer resources created by a `Scheduler` or `OpsAdmin` with a `name`, a `daily_capacity_sqft` maximum installable area per day, the certification flags `certified_putting` and `certified_playground`, and an `active` flag.

Scheduling enforces several checks. The assigned crew must be certified for the project's variant — a `PUTTING_GREEN` project requires the crew's `certified_putting`, and a `PLAYGROUND` project requires the crew's `certified_playground` — and the crew must be active; a crew lacking the required certification or marked inactive is rejected with `ERR_CREW_NOT_CERTIFIED`. The crew's `daily_capacity_sqft` must be at least the project's `billable_area_sqft`; insufficient capacity is rejected with `ERR_CREW_CAPACITY_EXCEEDED`. The proposed window must not overlap another non-terminal install job — one in `SCHEDULED` or `IN_PROGRESS` status — already booked on the same crew, where overlap is judged on the half-open interval so that an adjacent end-equals-start pairing is allowed; an overlap is rejected with `ERR_CREW_DOUBLE_BOOKED`. The `scheduled_end` must be strictly after the `scheduled_start`; a non-positive window is rejected with `ERR_INVALID_WINDOW`. A successful scheduling creates the install job in `SCHEDULED` status, copies the project's `billable_area_sqft` onto the job's `install_area_sqft`, advances the project's workflow dimension from `DEPOSIT_PAID` to `SCHEDULED`, and increments the project's `version`.

### 3.9. Running the Install and Activating the Warranty

An install job moves through `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, and `ABORTED`. A `Scheduler` starts a job that is `SCHEDULED`, but only once the logical clock has reached the job's `scheduled_start`; starting moves the job from `SCHEDULED` to `IN_PROGRESS` and increments the job's `version`.

Completing a job that is `IN_PROGRESS` is the cascade that closes out the physical work and turns on the warranty. Completion moves the job's `status` from `IN_PROGRESS` to `COMPLETED` (the first cascade hop); bubbles the project's workflow dimension from `SCHEDULED` to `INSTALLED`; activates any `PENDING` warranty plan on the project by moving it from `PENDING` to `ACTIVE`, setting its `start_at` to the completed job's `scheduled_end` and its `expires_at` to the start plus its coverage window (the second cascade hop); nudges the project's `finance_status` to `BALANCE_DUE`; and increments both the install job's `version` and the project's `version`.

Aborting is the sibling branch of completion. A `Scheduler` may abort a job that is `SCHEDULED` or `IN_PROGRESS`, and the same abort happens to all of a project's `SCHEDULED` or `IN_PROGRESS` jobs as a system cascade when the project is cancelled. Aborting moves the job's `status` to `ABORTED` and releases the crew's interval so the overlap window is freed, incrementing the job's `version`; unlike completion, an abort activates no warranty and makes no finance change — it only frees the crew. A start, complete, or abort attempted against a job not in the required state is rejected with `ERR_INVALID_STATE`.

### 3.10. Warranty Coverage and Maintenance Cadence

A `SalesRep` authors a warranty and maintenance plan against a project by supplying its `tier`, one of `BASIC`, `PLUS`, or `PREMIUM`. The plan is created in `PENDING` status with both `start_at` and `expires_at` unset, and the tier drives two computed terms. A `BASIC` plan carries a coverage window of 12 months and zero maintenance visits per year; a `PLUS` plan carries 36 months of coverage and one maintenance visit per year; a `PREMIUM` plan carries 96 months of coverage and two maintenance visits per year. These are recorded as `coverage_months` and `maintenance_visits_per_year`.

A warranty plan stays `PENDING` until the install it backs completes, at which point — as described in Section 3.9 — it activates: its `status` becomes `ACTIVE`, its `start_at` is set to the completed install job's `scheduled_end`, and its `expires_at` is set to that start plus its coverage window in months. An active plan expires once the logical clock reaches its `expires_at`, moving from `ACTIVE` to `EXPIRED`. If a project is cancelled while the plan is still `PENDING`, the plan is voided from `PENDING` to `VOID` instead of ever activating. Every warranty status change increments the plan's `version`.

### 3.11. Callbacks, Warranty Claims, and Rework Billing

After an install, problems are tracked as callbacks. A `Customer`, `SalesRep`, or `OpsAdmin` opens a callback against an installed project, supplying a `reason` — one of `SEAM_LIFT`, `INFILL_MIGRATION`, `DRAINAGE`, `WRINKLE`, `PET_ODOR`, or `OTHER` — and optionally a `warranty_plan_id` naming the plan the callback claims against (left null for a paid, out-of-warranty callback). At creation the system decides whether the callback is `billable` and what it will `charge_cents`, the callback is created in `OPEN` status, the project's `open_callback_count` is recomputed, and the project's `version` increments.

The coverage decision works as follows. A callback is **covered** (and therefore not billable) only when it names a warranty plan whose `status` is `ACTIVE`, the logical clock is before that plan's `expires_at`, and the reason qualifies. The workmanship reasons `SEAM_LIFT`, `WRINKLE`, and `DRAINAGE` always qualify under an active plan. The pet reasons `PET_ODOR` and `INFILL_MIGRATION` qualify only when the project's `variant` is `PET` and the plan's tier is `PLUS` or `PREMIUM`. A callback that is not covered is billable. When a callback is billable its `charge_cents` is a flat callback fee of 12500 cents plus a per-square-foot rework charge of 35 cents multiplied by the project's `billable_area_sqft`, rounded half-up to whole cents; when it is not billable the charge is zero.

A callback runs through `OPEN`, `IN_PROGRESS`, `RESOLVED`, and `CANCELLED`, all serviced by a `Scheduler`. Starting work moves a callback from `OPEN` to `IN_PROGRESS`. Resolving moves an `IN_PROGRESS` callback to `RESOLVED`, recomputes the project's `open_callback_count`, and — if the callback is billable — creates a `BALANCE` payment for its `charge_cents` in `PENDING` status; resolving increments the project's `version`. Cancelling moves a callback that is `OPEN` or `IN_PROGRESS` to `CANCELLED` and recomputes the project's `open_callback_count`; a `Customer` may also cancel a callback. The `open_callback_count` is the number of callbacks on the project whose status is `OPEN` or `IN_PROGRESS`. Every callback status change increments the callback's `version`.

### 3.12. Closing and Cancelling a Project

Closing is the clean ending. An `OpsAdmin` closes a project that is `INSTALLED`, but only when its `finance_status` is `PAID_IN_FULL` and its `open_callback_count` is zero; a close attempted while the project is not fully paid or still has open callbacks is rejected with `ERR_PROJECT_NOT_CLOSEABLE`. A successful close moves the workflow dimension to `CLOSED` and increments the project's `version`. The finance dimension reaches `PAID_IN_FULL` on its own when a balance payment settles: when the project is `BALANCE_DUE` and the settled deposit plus settled balance together reach at least the contract total, settlement advances the finance dimension from `BALANCE_DUE` to `PAID_IN_FULL` and increments the project's `version`.

Cancelling is the unwind. An `OpsAdmin` cancels a project whose `workflow_status` is anything other than `INSTALLED`, `CLOSED`, or `CANCELLED`. Cancellation moves the workflow dimension to `CANCELLED` and triggers a cascade: every `SCHEDULED` or `IN_PROGRESS` install job is aborted, releasing its crew window; every `DRAFT`, `SENT`, or `REVISED` quote is voided; any `PENDING` warranty plan is voided; and if the project has any settled deposit (its `deposit_paid_cents` is greater than zero), a `REFUND` payment for the full settled deposit amount is created in `PENDING` status. The cancel itself increments the project's `version`. When that refund later settles, the project's `finance_status` moves to `REFUNDED` — the finance dimension reaches `REFUNDED` from `DEPOSIT_DUE`, `DEPOSIT_SETTLED`, or `BALANCE_DUE` once a refund payment for the project has settled. Refund settlement increments the project's `version`.

### 3.13. The Logical Clock

Several transitions are time-driven — quote expiry, warranty expiry, and the gate that an install job may not start before its `scheduled_start`. Time in this system is a logical clock that an `OpsAdmin` can set to a supplied instant, passed as `to_iso8601`, for testing and operations. At server startup the clock reads exactly 2026-04-01T00:00:00Z and never falls back to wall-clock time before it is first set. Advancing the clock may cause sent quotes to expire and active warranty plans to expire on the next read of the affected rows.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions and the payment and clock drivers — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | OpsAdmin, SalesRep |
| GET | `/customers/{customer_id}` | Get a customer | OpsAdmin, SalesRep |
| POST | `/turf-products` | Create a turf product (catalog) | OpsAdmin |
| GET | `/turf-products` | List turf products (filter by active) | OpsAdmin, SalesRep |
| GET | `/turf-products/{turf_product_id}` | Get a turf product | OpsAdmin, SalesRep |
| POST | `/infill-products` | Create an infill product (catalog) | OpsAdmin |
| GET | `/infill-products` | List infill products (filter by active) | OpsAdmin, SalesRep |
| GET | `/infill-products/{infill_product_id}` | Get an infill product | OpsAdmin, SalesRep |
| POST | `/crews` | Create an install crew | OpsAdmin, Scheduler |
| GET | `/crews/{crew_id}` | Get a crew | OpsAdmin, Scheduler |
| GET | `/crews/{crew_id}/install-jobs` | List install jobs assigned to a crew | OpsAdmin, Scheduler |
| POST | `/projects` | Create a project | OpsAdmin, SalesRep |
| GET | `/projects/{project_id}` | Get a project (computed rollups included) | OpsAdmin, SalesRep, Scheduler, Customer |
| GET | `/projects` | List projects (filter by customer_id / workflow_status) | OpsAdmin, SalesRep, Scheduler |
| GET | `/projects/{project_id}/ledger` | Computed project ledger (settled; include_pending for projected) | OpsAdmin, SalesRep, Customer |
| POST | `/projects/{project_id}/close` | Close an installed, paid project with no open callbacks | OpsAdmin |
| POST | `/projects/{project_id}/cancel` | Cancel a non-installed project (cascade) | OpsAdmin |
| POST | `/projects/{project_id}/site-measures` | Record a site measurement | SalesRep, OpsAdmin |
| GET | `/projects/{project_id}/site-measures` | List site measures for a project | SalesRep, OpsAdmin |
| POST | `/projects/{project_id}/design-layouts` | Create a design layout | SalesRep, OpsAdmin |
| GET | `/projects/{project_id}/design-layouts` | List design layouts for a project | SalesRep, OpsAdmin |
| GET | `/projects/{project_id}/design-layouts/{design_layout_id}` | Get a design layout | SalesRep, OpsAdmin |
| POST | `/projects/{project_id}/design-layouts/{design_layout_id}/accept` | Accept a design | SalesRep, OpsAdmin |
| POST | `/projects/{project_id}/design-layouts/{design_layout_id}/reject` | Reject a design | SalesRep, OpsAdmin |
| POST | `/projects/{project_id}/base-prep-scopes` | Create a base prep & drainage scope | SalesRep, OpsAdmin |
| GET | `/projects/{project_id}/base-prep-scopes` | List base prep scopes for a project | SalesRep, OpsAdmin |
| POST | `/projects/{project_id}/base-prep-scopes/{base_prep_scope_id}/finalize` | Finalize a base prep scope | SalesRep, OpsAdmin |
| POST | `/projects/{project_id}/quotes` | Create a quote | SalesRep, OpsAdmin |
| GET | `/projects/{project_id}/quotes` | List quotes for a project | SalesRep, OpsAdmin, Customer |
| GET | `/projects/{project_id}/quotes/{quote_id}` | Get a quote | SalesRep, OpsAdmin, Customer |
| POST | `/projects/{project_id}/quotes/{quote_id}/send` | Send a quote | SalesRep, OpsAdmin |
| POST | `/projects/{project_id}/quotes/{quote_id}/revise` | Revise a sent quote (spawns successor) | SalesRep, OpsAdmin |
| POST | `/projects/{project_id}/quotes/{quote_id}/accept` | Customer accepts a sent quote (OCC) | Customer, OpsAdmin |
| POST | `/projects/{project_id}/payments` | Record a payment | OpsAdmin, Customer |
| GET | `/projects/{project_id}/payments` | List payments for a project | OpsAdmin, SalesRep, Customer |
| POST | `/_payments/settle` | Settle a pending payment (driver) | OpsAdmin |
| POST | `/_payments/fail` | Fail a pending payment (driver) | OpsAdmin |
| POST | `/projects/{project_id}/install-jobs` | Schedule an install job on a crew | Scheduler, OpsAdmin |
| GET | `/projects/{project_id}/install-jobs` | List install jobs for a project | Scheduler, OpsAdmin, Customer |
| POST | `/projects/{project_id}/install-jobs/{install_job_id}/start` | Start an install | Scheduler, OpsAdmin |
| POST | `/projects/{project_id}/install-jobs/{install_job_id}/complete` | Complete an install (cascade) | Scheduler, OpsAdmin |
| POST | `/projects/{project_id}/install-jobs/{install_job_id}/abort` | Abort an install | Scheduler, OpsAdmin |
| POST | `/projects/{project_id}/warranty-plans` | Create a warranty & maintenance plan | SalesRep, OpsAdmin |
| GET | `/projects/{project_id}/warranty-plans` | List warranty plans for a project | SalesRep, OpsAdmin, Customer |
| POST | `/projects/{project_id}/callbacks` | Open a callback | OpsAdmin, SalesRep, Customer |
| GET | `/projects/{project_id}/callbacks` | List callbacks for a project | OpsAdmin, SalesRep, Customer |
| POST | `/projects/{project_id}/callbacks/{callback_id}/start` | Start working a callback | Scheduler, OpsAdmin |
| POST | `/projects/{project_id}/callbacks/{callback_id}/resolve` | Resolve a callback | Scheduler, OpsAdmin |
| POST | `/projects/{project_id}/callbacks/{callback_id}/cancel` | Cancel a callback | Scheduler, OpsAdmin, Customer |
| POST | `/_clock/set_current_utc` | Set the logical clock (driver) | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_PROJECT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_VARIANT_PRODUCT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRODUCT_RETIRED` | 422 Unprocessable Entity |
| `ERR_DESIGN_ALREADY_ACCEPTED` | 409 Conflict |
| `ERR_CREW_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_CREW_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_SCOPE_NOT_FINALIZED` | 409 Conflict |
| `ERR_DEPOSIT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_BALANCE_NOT_DUE` | 409 Conflict |
| `ERR_PROJECT_NOT_CLOSEABLE` | 409 Conflict |
| `ERR_VALIDATION_PAGINATION` | 422 Unprocessable Entity |
