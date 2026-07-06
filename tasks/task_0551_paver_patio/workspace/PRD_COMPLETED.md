# Hardscape Outdoor Living API — Product Requirements Document

## 1. Introduction

Building a paver patio, seat wall, fire pit, or full outdoor kitchen is a long engagement that runs through many hands: a design consultant who renders the space and prices it, a project manager who shepherds permits, materials, crews, and money, and the homeowner who approves the look and ultimately signs and pays. This API is the system of record for that entire journey — from the first 3D rendering and site measure, through municipal permit and homeowners-association review, into contracting, material ordering, phased construction, mid-project change orders, and finally warranty. It is styled after a Belgard-authorized contractor's back office, and every dollar it touches is tracked in whole cents.

The platform's central promise is that a project's financial ledger and its physical build stay consistent at all times. An estimate is computed from measured quantities and a catalog price book; a signed contract locks those prices; the as-built valuation trues up against what was actually installed; and every deposit, progress draw, refund, and retention release reconciles against the contract value. Because several actors touch the same project concurrently, the money-bearing operations are guarded by optimistic concurrency so that no writer can silently overwrite a ledger they have not observed. The sections that follow specify the global contract every endpoint honors, the business rules that govern each lifecycle stage, and the exact endpoint and error surfaces the implementation must expose.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (401). When both headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (403).

The system recognizes exactly four roles: `PlatformAdmin`, `DesignConsultant`, `ProjectManager`, and `Client`. The `PlatformAdmin` is the back-office authority-of-record clerk who maintains the Belgard product catalog and crew roster and records permit, HOA, and warranty decisions. A `DesignConsultant` handles sales and design: customers, projects, design revisions, site measurements, line items, and estimate generation. A `ProjectManager` runs operations: approvals submission, production, material ordering, crew scheduling, change orders, and draws. A `Client` is the homeowner.

Identity binds differently per role. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any project-scoped resource compare the owning project's `customer_id` to `X-User-ID`, and a `Client` acting on a project they do not own is rejected with `ERR_NOT_PROJECT_OWNER` (403). For the other three roles — `PlatformAdmin`, `DesignConsultant`, and `ProjectManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0 (its minimum is 0). Unless a specific endpoint says otherwise, list results are sorted by `created_at` in ascending order. The `meta` object of a list response reports `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Attributes and the Project Version Counter

Every resource in the system carries a server-minted `id` formatted as a bare UUID (no type prefix) and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entity types here are mutable and therefore also carry an `updated_at` timestamp — refreshed on every change to the resource — and an integer `version` that starts at 1 and increments by one on each mutation. These fields provide a consistent audit trail and, in the case of `version`, the basis for optimistic concurrency control.

The `Project` version counter deserves special emphasis because it anchors the financial ledger. `Project.version` increments by one on *every* mutation of any project field — whether that is a `status` transition or a change to any of its monetary, permit, HOA, or warranty fields — including mutations that arrive indirectly as a cascade from a child resource's transition (for example, an approved change order that recomputes the contract value, or a paid draw that credits the amount paid). Any operation that touches a project's ledger, even a change-order rejection that changes no dollar figure, is treated as a version-bumping ledger touch.

### 2.5. Request Handling Order and Validation Precedence

Every request is evaluated through a fixed precedence ladder. The first rung that fails determines the response, so a lower-priority failure never masks a higher-priority one. The order is:

1. **Authentication.** Both `X-User-ID` and `X-User-Role` must be present, or the request fails with `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The role must be permitted for the operation, or the request fails with `ERR_UNAUTHORIZED` (403).
3. **Request well-formedness.** Required fields must be present, types valid, enum members recognized, quantities strictly positive, and dates parseable; otherwise `ERR_INVALID_REQUEST` (422).
4. **Path existence.** Resources named in the URL path are resolved left to right, and the first identifier that resolves to nothing yields that entity's own not-found code — `ERR_PROJECT_NOT_FOUND`, `ERR_DESIGN_REVISION_NOT_FOUND`, `ERR_SITE_MEASUREMENT_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_HOA_SUBMISSION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_MATERIAL_ORDER_NOT_FOUND`, `ERR_WORK_PHASE_NOT_FOUND`, `ERR_DRAW_NOT_FOUND`, or `ERR_WARRANTY_CLAIM_NOT_FOUND` — all 404.
5. **Project ownership.** For the `Client`-only actions (approving or requesting a revision on a design, signing a contract, and filing a warranty claim), the caller must own the parent project, or `ERR_NOT_PROJECT_OWNER` (403).
6. **State precondition.** The target resource must sit in a state from which the transition is legal. A generic violation is `ERR_INVALID_STATE` (409); several transitions define their own, more specific 409 codes described in §3.
7. **Body foreign-key existence.** Identifiers carried in the body — `customer_id`, `product_id`, `add_product_id`, `crew_id`, `work_phase_id`, and every entry of `line_item_ids` or `covered_line_item_ids` — must resolve and belong where required, surfacing `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, or `ERR_LINE_ITEM_NOT_FOUND` (all 404).
8. **Compliance gates.** Permit and HOA approval gates apply here (detailed in §3), surfacing `ERR_PERMIT_NOT_APPROVED` or `ERR_HOA_NOT_APPROVED` (409).
9. **Temporal and capacity conflicts.** Crew double-booking, delivery daily capacity, and date-range ordering are checked here, surfacing `ERR_CREW_DOUBLE_BOOKED` (409), `ERR_DELIVERY_SLOT_FULL` (409), and `ERR_INVALID_DATE_RANGE` (422).
10. **Fiscal limits.** Deposit cap and progress-draw balance are checked here, surfacing `ERR_DEPOSIT_EXCEEDS_CAP` (422) and `ERR_DRAW_EXCEEDS_BALANCE` (422).
11. **Optimistic concurrency.** The supplied `expected_project_version` must match the project's current `version`, or the request fails with `ERR_STALE_VERSION` (412).

### 2.6. Money, Measurement, and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation multiplies by a rate or percentage and would produce a fractional cent, the result is rounded half up to the nearest whole cent. Where the rules below round pallet counts, they round up (ceiling) to the next whole pallet. Catalog prices, waste factors, and per-pallet coverage are inputs that preserve their given precision; only the derived money and pallet figures are rounded as described.

### 2.7. Guarding the Ledger: Optimistic Concurrency Control

Two create operations mutate the project's financial ledger and are therefore guarded against stale writes: creating a change order and creating a progress draw. Each such request must carry `expected_project_version`, holding the `version` of the target `Project` that the client last observed. If the project's current `version` has advanced past that value — because another change order, draw, payment, or refund has since touched the ledger — the create is rejected with `ERR_STALE_VERSION` (412), and no resource is created. This prevents a client from stacking a new financial record on top of a contract value or balance it has not yet seen. Endpoints that do not create ledger records do not take a version field.

### 2.8. Cascading Consistency Across the Project Hierarchy

A project owns many children — design revisions, site measurements, line items, permits, HOA submissions, change orders, material orders, work phases, progress draws, and warranty claims — and several operations propagate across that hierarchy. Three cascade patterns recur. First, when the final build phase completes, the project itself bubbles up to completion and runs its completion accounting. Second, when an approved change order raises a wall past the permit threshold, the project reverts to awaiting approvals and blocks the crews already committed to it. Third, when a project is cancelled, its live children are resolved in turn. In every case, each project field the cascade touches counts as a mutation that refreshes `updated_at` and increments `version`, and any crew released by a blocked or cancelled phase has its live booking count decremented. The concrete mechanics of each cascade are described in the relevant workflow subsection of §3.

### 2.9. The Server Logical Clock

The system runs on a logical clock rather than wall-clock time, so that warranty windows and claim timestamps are deterministic. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant and echoes the new value back as `current_utc`. On startup the clock reads `2026-05-01T00:00:00Z`, and it never falls back to real time. The clock governs a project's `warranty_start_date` and `warranty_end_date` and the `filed_at` stamp on warranty claims.

## 3. Business Logic & Workflows

### 3.1. Foundational Records: Homeowners, the Catalog, and Crews

Before any project exists, three kinds of reference records are established. A homeowner is captured as a `Customer` with a `full_name`, an `email` that must be unique across all customers, and optional `phone` and `billing_address`. A duplicate email is a well-formedness/uniqueness failure at request-validation time.

The Belgard product catalog is maintained by the `PlatformAdmin`. Each `Product` has a unique `sku` (a duplicate `sku` is a uniqueness failure rejected at request-validation time with `ERR_INVALID_REQUEST`), a display `name`, a `category` — one of `PAVER`, `WALL_BLOCK`, `FIRE_PIT`, or `OUTDOOR_KITCHEN` — and a `unit` — one of `SQFT`, `FACE_SQFT`, `EACH`, or `LINEAR_FT`. It carries a `unit_price_cents` (the current catalog price per unit, which may not be negative), a `waste_factor` (a fractional overage, at least zero and strictly below one, e.g. `0.10` for ten percent, applied to paver and wall-block quantities and left at its default of `0` for each/linear-foot goods), and a `coverage_per_pallet_sqft` (square feet covered by one pallet, defaulting to `0` and used only for square-foot goods). At creation the system also derives the read-only `is_feature` flag, which is true exactly when the product's `category` is `FIRE_PIT` or `OUTDOOR_KITCHEN`; this flag feeds per-feature labor pricing.

Install crews are also created by the `PlatformAdmin`. A `Crew` has a `name` and a `region_code` naming the region it serves. Its `active_booking_count` is a derived counter, starting at `0`, equal to the number of work phases assigned to that crew whose status is `SCHEDULED` or `IN_PROGRESS`; it rises by one when a phase is scheduled to the crew and falls by one whenever such a phase leaves those two states (by completing, blocking, or cancelling).

### 3.2. Originating a Project, Rendering the Design, and Measuring the Site

A `DesignConsultant` (or a `PlatformAdmin`) opens a `Project` by naming its `customer_id`, a `site_address`, a `region_code` used for crew matching and delivery scoping, and an optional `in_hoa` flag (default false) declaring whether the site sits inside a homeowners association. A new project starts in `DRAFT`. Its computed and financial fields — `permit_required`, `hoa_required`, `estimated_total_cents`, `prompt_pay_discount_cents`, `contract_value_cents`, `amount_paid_cents`, `balance_due_cents`, `final_billed_total_cents`, `warranty_start_date`, and `warranty_end_date` — are all zero, false, or null until later stages fill them in.

The design is worked through a `DesignRevision`, created against a `project_id` with optional `notes` and starting in `DRAFTING` at `revision_round` 1. The consultant produces a 3D rendering, which advances the revision from `DRAFTING` to `RENDERED` and populates `render_url` with the generated artifact URL, then submits it for review, moving `RENDERED` to `IN_REVIEW`. From `IN_REVIEW`, the homeowner — who must own the project — either approves it, advancing `IN_REVIEW` to `APPROVED`, or asks for changes, advancing `IN_REVIEW` to `REVISION_REQUESTED`. A revision-requested design is revised by the consultant back to `DRAFTING`; that `REVISION_REQUESTED → DRAFTING` step increments `revision_round` by one and clears `render_url`, re-entering the loop. `APPROVED` is terminal for a revision.

Site geometry is captured as one or more `SiteMeasurement` records, each tied to a `project_id` with a `zone_label` (for example "rear patio" or "seat wall"), a `measured_sqft` area (at least zero), and a `wall_height_in` giving the retaining or seat-wall height in inches for that zone (at least zero, defaulting to `0` where there is no wall). Material selections are captured as `LineItem` records, each linking a `project_id` and a `product_id` with a `measured_quantity` (strictly greater than zero) expressed in the product's own unit. At creation the line's `category` is denormalized from the product's category, its `origin` is set to `ORIGINAL`, and its `pinned_unit_price_cents` and `installed_quantity` remain null until, respectively, the contract is signed and a covering phase completes.

### 3.3. Turning a Design into a Quote: Generating the Estimate

A `DesignConsultant` generates the estimate, which advances the project from `DRAFT` to `QUOTED`. Three preconditions must hold, each with its own code: at least one design revision on the project must be `APPROVED` (else `ERR_DESIGN_NOT_APPROVED`), at least one site measurement must exist (else `ERR_NO_MEASUREMENT`), and at least one line item must exist (else `ERR_NO_LINE_ITEMS`), all 409.

Generating the estimate runs the **project valuation** in its estimate variant over every line item, following a pinned evaluation order that must be honored step for step, because later steps consume subtotals produced by earlier ones:

1. **Per-line material.** For each line, the billable quantity is its `measured_quantity` multiplied by one plus the product's `waste_factor`. The line's material charge is that billable quantity multiplied by the product's current `unit_price_cents`, rounded half up to whole cents.
2. **Material subtotal.** Sum the per-line material charges.
3. **Paver labor.** Let the total paver square footage be the sum of billable quantities across every line whose `category` is `PAVER`. A single labor rate is selected by which band that total falls into and then applied to the *entire* paver square footage — the rate is a flat per-square-foot rate for the whole area, not a graduated schedule: 700 cents per square foot when the total is 200 square feet or less, 600 cents per square foot when it is greater than 200 but no more than 500, and 525 cents per square foot when it exceeds 500. Base paver labor is that rate times the total paver square footage. Then, if any site measurement on the project records a `wall_height_in` of at least 48 inches, base paver labor is multiplied by 1.15 (a fifteen-percent complex-site uplift) and rounded half up to whole cents.
4. **Wall labor.** Sum the billable quantities across every `WALL_BLOCK` line and multiply by 900 cents per unit.
5. **Feature labor.** Count the lines whose product is a feature (`is_feature` true) and multiply that count by 25,000 cents ($250) each.
6. **Labor cost.** Add base paver labor, wall labor, and feature labor.
7. **Pre-tax subtotal.** Add the material subtotal and the labor cost.
8. **Prompt-pay discount.** If the pre-tax subtotal is at least 2,000,000 cents ($20,000), the discount is two percent of the pre-tax subtotal, rounded half up to whole cents; otherwise it is zero. This value is stored in `prompt_pay_discount_cents`.
9. **Tax.** Tax is 7.25 percent of the material subtotal only — labor and any permit fee are untaxed — rounded half up to whole cents.
10. **Permit fee.** Add 35,000 cents ($350) when the project requires a permit, and nothing otherwise.
11. **Total.** The estimated total is the pre-tax subtotal, minus the prompt-pay discount, plus tax, plus the permit fee.

That total is written to `estimated_total_cents`. Generating the estimate also sets `contract_value_cents` equal to `estimated_total_cents` and `balance_due_cents` equal to the contract value (nothing has been paid yet). In the same step, permit determination sets `permit_required` to true exactly when the largest `wall_height_in` across the project's site measurements is at least 48 inches (a wall of 47 inches does not require a permit; 48 does), and `hoa_required` is set equal to the project's `in_hoa` flag. Taken together, these field updates are a single version-bumping operation that increments the project `version` exactly once.

### 3.4. Approvals: Permits and Homeowners-Association Review

A `ProjectManager` submits the project for approvals, advancing `QUOTED` to `PENDING_APPROVALS`. As a side effect, if the project requires a permit, the system creates a `Permit` for it (the client never posts one directly); the new permit starts in `PREPARING` with `fee_cents` of 35,000. If the project requires HOA review, the system creates a `HoaSubmission` in `DRAFT`. Both are tied to the project by `project_id`.

The permit is a straight-line application. The manager submits it, advancing `PREPARING` to `SUBMITTED`. The `PlatformAdmin`, acting as authority of record, then either approves it — advancing `SUBMITTED` to `APPROVED` and assigning a `permit_number` — or denies it, advancing `SUBMITTED` to `DENIED` and recording the supplied `correction_notes`. Both `APPROVED` and `DENIED` are terminal.

The HOA architectural review is a fork-join. The manager submits the submission, advancing `DRAFT` to `SUBMITTED`; a submission that has come back `CONDITIONAL` may be submitted again, likewise advancing `CONDITIONAL` to `SUBMITTED`. From `SUBMITTED`, the `PlatformAdmin` records a decision by supplying an `outcome`. An `outcome` of `APPROVED` advances the submission to `APPROVED` and records `decision_notes`. An `outcome` of `CONDITIONAL` advances it to `CONDITIONAL`, recording both `conditions` and `decision_notes`; a conditional decision does not satisfy the contract gate, so signing remains blocked until a later `APPROVED`. An `outcome` of `REJECTED` advances it to `REJECTED` and records `decision_notes`. `APPROVED` and `REJECTED` are terminal.

### 3.5. Funding the Deposit and Signing the Contract

Before signing, the homeowner's deposit must be collected. Draws are described fully in §3.7; the relevant point here is that a deposit draw's amount is capped. The deposit cap is the smaller of two figures: ten percent of the project's current `contract_value_cents`, rounded half up to whole cents, and a flat ceiling of 100,000 cents ($1,000). A deposit whose `amount_cents` exceeds that cap is rejected with `ERR_DEPOSIT_EXCEEDS_CAP` (422).

The homeowner then signs the contract, advancing `PENDING_APPROVALS` to `CONTRACTED`. Signing is a `Client`-only action, permitted only to the project's owner. Two gates apply: a deposit draw (`draw_type` `DEPOSIT`) must already be `PAID`, or the request is rejected with `ERR_DEPOSIT_NOT_PAID` (409); and if the project requires HOA review, its submission must be `APPROVED`, or the request is rejected with `ERR_HOA_NOT_APPROVED` (409). Notably, permit approval is *not* required to sign — a project can be contracted while its permit is still working through the authority. On signing, the system locks pricing: every line item's `pinned_unit_price_cents` is set to its product's current `unit_price_cents`, and `contract_value_cents` is finalized at `estimated_total_cents`. The project version increments.

### 3.6. Ordering Materials and Entering Production

Once a project is contracted (or already in production), the `ProjectManager` assembles material orders. A `MaterialOrder` is created against a `project_id` with a `requested_delivery_date` (a `YYYY-MM-DD` calendar date), a non-empty `line_item_ids` array naming the lines it covers, and an optional `supplier_ref`; the order's `region_code` is denormalized from the project. Creating an order with an empty `line_item_ids` array is rejected with `ERR_NO_ORDERABLE_ITEMS` (422); a `line_item_ids` entry that names no line item, or one belonging to a different project, is an `ERR_LINE_ITEM_NOT_FOUND` (404). A new order starts in `DRAFT`.

Placing an order advances `DRAFT` to `PLACED`. Placement is allowed only while the project is `CONTRACTED` or `IN_PRODUCTION`, and only if fewer than two other material orders already in `PLACED` or `DELIVERED` share this order's region and `requested_delivery_date`; a third order for the same region and date is rejected with `ERR_DELIVERY_SLOT_FULL` (409). Placement computes the order's pallet figures via the pallet aggregation, whose rounding order is pinned: round each line to whole pallets first, then sum. Only covered lines whose product unit is `SQFT` or `FACE_SQFT` contribute pallets; `EACH` and `LINEAR_FT` lines contribute none, and a square-foot line whose `coverage_per_pallet_sqft` is zero likewise contributes no pallets and no ordered square footage. For each covered square-foot line, the billable quantity (its `measured_quantity` times one plus the product's `waste_factor`) is divided by the product's `coverage_per_pallet_sqft` and rounded up to the next whole pallet. `total_pallets` is the sum of those per-line pallet counts, and `total_sqft_ordered` is the sum, over the same lines, of each line's whole-pallet count multiplied by that product's coverage per pallet. Confirming delivery advances `PLACED` to `DELIVERED`.

A `ProjectManager` moves the project into production, advancing `CONTRACTED` to `IN_PRODUCTION`. This requires that at least one of the project's material orders is `DELIVERED` (else `ERR_MATERIAL_NOT_DELIVERED`, 409) and that at least one work phase is already `SCHEDULED` (else the generic `ERR_INVALID_STATE`, 409). The version increments.

### 3.7. Building the Job: Crews, Phases, and the Draw Ledger

Construction is organized into work phases. A `WorkPhase` is created against a `project_id` with a `phase_type` — one of `EXCAVATION`, `BASE_PREP`, `PAVER_SET`, `WALL_BUILD`, `FEATURE_INSTALL`, or `FINAL_GRADE` — plus an optional `covered_line_item_ids` array (defaulting to empty) naming the lines whose installed quantities this phase will record, an optional `sequence_index` ordering hint (default `0`), and an optional `is_final` flag (default false) marking the phase whose completion finishes the project. A new phase starts in `PLANNED`, with `crew_id`, `start_date`, and `end_date` null and its computed `requires_permit` false.

Scheduling a phase advances `PLANNED` to `SCHEDULED` and books a crew. The request supplies `crew_id`, `start_date`, and `end_date`. Scheduling is allowed only while the project is `CONTRACTED` or `IN_PRODUCTION`. The `crew_id` must reference an existing crew (else `ERR_CREW_NOT_FOUND`, 404). The `end_date` must be on or after the `start_date`, or the request fails with `ERR_INVALID_DATE_RANGE` (422). The crew must not already hold another phase in `SCHEDULED` or `IN_PROGRESS` whose `[start_date, end_date]` interval — treated as closed, so touching endpoints count as overlapping — intersects the requested interval; a clash is rejected with `ERR_CREW_DOUBLE_BOOKED` (409). If the `phase_type` is `WALL_BUILD` and the project requires a permit, the project's permit must be `APPROVED`, or the request fails with `ERR_PERMIT_NOT_APPROVED` (409). On success the system records `crew_id`, `start_date`, and `end_date`, sets `requires_permit` to true exactly when this is a `WALL_BUILD` phase on a permit-required project, and increments the crew's `active_booking_count` by one.

Starting a phase advances `SCHEDULED` to `IN_PROGRESS`; it is allowed only while the project is `IN_PRODUCTION`, and a permit-required `WALL_BUILD` phase again requires its permit to be `APPROVED` (else `ERR_PERMIT_NOT_APPROVED`). Completing a phase advances `IN_PROGRESS` to `COMPLETED`: the request carries an `installed_quantities` map from which each covered line's `installed_quantity` is recorded, and the crew's `active_booking_count` is decremented by one. If the completed phase is the final one, completion bubbles the project up from `IN_PRODUCTION` to `COMPLETED` (see §3.9).

The draw ledger tracks money. A `ProgressDraw` is created against a `project_id` with a `draw_type` of `DEPOSIT` or `PROGRESS`, an `amount_cents` (strictly positive), an optional `work_phase_id` tying a progress draw to a build milestone (which, when supplied, must reference a work phase on the same project, else `ERR_WORK_PHASE_NOT_FOUND`, 404), and `expected_project_version` for the concurrency guard of §2.7. (The `RETENTION_RELEASE` draw type is never client-posted; the system creates it at completion.) A new draw starts in `PENDING`. A `PROGRESS` draw's `amount_cents` may not exceed the project's current `balance_due_cents`, or it is rejected with `ERR_DRAW_EXCEEDS_BALANCE` (422); a `DEPOSIT` draw is bounded by the deposit cap of §3.5. Recording a payment advances a draw from `PENDING` to `PAID`, adds its `amount_cents` to the project's `amount_paid_cents`, recomputes `balance_due_cents` as `contract_value_cents` minus `amount_paid_cents`, and increments the project version. Refunding advances a `PAID` draw to `REFUNDED`, subtracts its `amount_cents` back out of `amount_paid_cents`, recomputes the balance the same way, and again increments the version. At all times, `amount_paid_cents` equals the sum of `amount_cents` over the project's draws that are `PAID`.

### 3.8. Change Orders, the Permit Revert, and Cancellation

Mid-project scope changes flow through change orders. A `ProjectManager` creates a `ChangeOrder` against a `project_id`, with an optional `description`, an `add_product_id` naming the product whose new line the change adds on approval, an `add_measured_quantity` (strictly positive) for that line, an optional `add_wall_height_in` (at least zero, default `0`) giving the added wall's height when the added product is a `WALL_BLOCK`, and `expected_project_version`. Creation is guarded by the concurrency rule of §2.7: if the project's `version` has advanced past `expected_project_version`, creation is rejected with `ERR_STALE_VERSION` (412). A new change order starts in `PROPOSED`, with `pricing_method` fixed to `RECOMPUTE` and `price_delta_cents` at `0`. Creating a change order is itself a ledger touch that increments the project version.

Approving a change order advances `PROPOSED` to `APPROVED` and is allowed only while the project is `CONTRACTED` or `IN_PRODUCTION`. Approval creates a new line item (`origin` `CHANGE_ORDER`) from `add_product_id` and `add_measured_quantity`, immediately setting that line's `pinned_unit_price_cents` to the product's current `unit_price_cents`. It then prices the change by the `RECOMPUTE` method: the system re-runs the estimate-variant project valuation of §3.3 over the full, enlarged set of line items — every existing line plus the newly added one — using each product's live catalog `unit_price_cents` and billable quantities (measured quantity plus waste), which re-tiers the paver labor across the entire, now-larger paver square footage. The `price_delta_cents` is that recomputed valuation minus the project's `contract_value_cents` as it stood before approval. The recomputed valuation becomes the new `contract_value_cents`, and `balance_due_cents` is recomputed as contract value minus amount paid. The project version increments. Rejecting a change order instead advances `PROPOSED` to `REJECTED`; this changes no dollar figure but still counts as a ledger touch that increments the project version.

Approval carries one further consequence. If the added line raises a wall — `add_wall_height_in` of at least 48 inches — and the project did not previously require a permit (`permit_required` was false before approval), the project reverts: it moves from `CONTRACTED` or `IN_PRODUCTION` back to `PENDING_APPROVALS`. The revert sets `permit_required` to true, creates a `PREPARING` permit if none exists, and cascades to the crews: every work phase currently in `SCHEDULED` or `IN_PROGRESS` on that project is moved to `BLOCKED`, and each such block decrements the holding crew's `active_booking_count` by one. The project version increments. This is the intended serialization point that forces re-permitting before newly-tall walls can proceed.

Cancellation is available to a `ProjectManager` from any non-terminal posture — that is, any status other than `COMPLETED` or `CANCELLED` — moving the project to `CANCELLED`. From `DRAFT`, `QUOTED`, or `PENDING_APPROVALS`, cancellation simply increments the version. From `CONTRACTED` or `IN_PRODUCTION`, cancellation also cascades down: every non-terminal material order moves to `CANCELLED`; every work phase in `PLANNED`, `SCHEDULED`, `IN_PROGRESS`, or `BLOCKED` moves to `CANCELLED`, releasing its crew (a phase that was `SCHEDULED` or `IN_PROGRESS` decrements that crew's `active_booking_count`, while phases that were `PLANNED` or `BLOCKED` release nothing further); and every `PENDING` progress draw moves to `VOID`. The version increments.

### 3.9. Completion, Retention Release, and Warranty

When the final work phase completes, the project bubbles from `IN_PRODUCTION` to `COMPLETED`, and the completion accounting runs. First, the project is valued in its as-built variant: the same eleven-step valuation of §3.3 is re-run, but each line's quantity is its actual `installed_quantity` (with no waste applied) and each line's price is its locked `pinned_unit_price_cents` rather than the live catalog price. The result is written to `final_billed_total_cents`; it diverges from the estimate whenever installed quantities differ from the billable ones. Second, the system creates a `RETENTION_RELEASE` progress draw in `PENDING` status whose `amount_cents` is five percent of `contract_value_cents`, rounded half up to whole cents. Third, `warranty_start_date` is set to the current logical-clock instant and `warranty_end_date` to 365 days after it. The version increments.

After completion, the homeowner may file warranty claims. Filing is a `Client`-only action, allowed only to the project's owner. A `WarrantyClaim` is created against a `project_id` with a `claim_category` of `WORKMANSHIP`, `MATERIAL`, or `SETTLEMENT`, and an optional `description`; the claim's `filed_at` is stamped from the logical clock, and it starts in `FILED`. The project must be `COMPLETED`, or the claim is rejected with `ERR_NOT_COMPLETED` (409); and the clock must not have passed the project's `warranty_end_date`, or filing is rejected with `ERR_WARRANTY_WINDOW_CLOSED` (409). The `PlatformAdmin` resolves a claim by supplying an `outcome` with optional `resolution_notes`: an `outcome` of `APPROVED` advances `FILED` to `APPROVED`, and `DENIED` advances `FILED` to `DENIED`. Both are terminal.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that drive a state transition or otherwise modify an existing resource return `200 OK`. The logical-clock capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | `PlatformAdmin` |
| POST | `/customers` | Create a homeowner | `DesignConsultant`, `PlatformAdmin` |
| POST | `/products` | Create a catalog product | `PlatformAdmin` |
| GET | `/products/{id}` | Read a catalog product | `PlatformAdmin`, `DesignConsultant`, `ProjectManager` |
| GET | `/products/{id}/line-items` | List line items referencing a product | `PlatformAdmin`, `DesignConsultant` |
| GET | `/products/{id}/change-orders` | List change orders adding a product | `PlatformAdmin`, `ProjectManager` |
| POST | `/crews` | Create an install crew | `PlatformAdmin` |
| GET | `/crews/{id}` | Read a crew, including active booking count | `PlatformAdmin`, `ProjectManager` |
| GET | `/crews/{id}/work-phases` | List work phases assigned to a crew | `PlatformAdmin`, `ProjectManager` |
| POST | `/projects` | Create a project (DRAFT) | `DesignConsultant`, `PlatformAdmin` |
| GET | `/projects` | List projects; filter by customer | `DesignConsultant`, `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/projects/{id}` | Read a project | `DesignConsultant`, `ProjectManager`, `PlatformAdmin`, `Client` |
| POST | `/projects/{id}/generate-estimate` | DRAFT → QUOTED; run valuation and permit determination | `DesignConsultant` |
| POST | `/projects/{id}/submit-approvals` | QUOTED → PENDING_APPROVALS; create permit/HOA as required | `ProjectManager` |
| POST | `/projects/{id}/sign-contract` | PENDING_APPROVALS → CONTRACTED; lock prices | `Client` |
| POST | `/projects/{id}/start-production` | CONTRACTED → IN_PRODUCTION | `ProjectManager` |
| POST | `/projects/{id}/cancel` | Non-terminal → CANCELLED with cascade | `ProjectManager` |
| POST | `/design-revisions` | Create a design revision (DRAFTING) | `DesignConsultant` |
| GET | `/design-revisions/{id}` | Read a design revision | `DesignConsultant`, `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/projects/{id}/design-revisions` | List a project's design revisions | `DesignConsultant`, `ProjectManager`, `PlatformAdmin`, `Client` |
| POST | `/design-revisions/{id}/render` | DRAFTING → RENDERED | `DesignConsultant` |
| POST | `/design-revisions/{id}/submit-review` | RENDERED → IN_REVIEW | `DesignConsultant` |
| POST | `/design-revisions/{id}/approve` | IN_REVIEW → APPROVED | `Client` |
| POST | `/design-revisions/{id}/request-revision` | IN_REVIEW → REVISION_REQUESTED | `Client` |
| POST | `/design-revisions/{id}/revise` | REVISION_REQUESTED → DRAFTING | `DesignConsultant` |
| POST | `/site-measurements` | Record a site measurement | `DesignConsultant` |
| GET | `/site-measurements/{id}` | Read a site measurement | `DesignConsultant`, `ProjectManager`, `PlatformAdmin` |
| GET | `/projects/{id}/site-measurements` | List a project's site measurements | `DesignConsultant`, `ProjectManager`, `PlatformAdmin` |
| POST | `/line-items` | Add a material selection line to a project | `DesignConsultant` |
| GET | `/line-items/{id}` | Read a line item | `DesignConsultant`, `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/projects/{id}/line-items` | List a project's line items | `DesignConsultant`, `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/permits/{id}` | Read a permit | `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/projects/{id}/permits` | List a project's permits | `ProjectManager`, `PlatformAdmin`, `Client` |
| POST | `/permits/{id}/submit` | PREPARING → SUBMITTED | `ProjectManager` |
| POST | `/permits/{id}/approve` | SUBMITTED → APPROVED | `PlatformAdmin` |
| POST | `/permits/{id}/deny` | SUBMITTED → DENIED | `PlatformAdmin` |
| GET | `/hoa-submissions/{id}` | Read an HOA submission | `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/projects/{id}/hoa-submissions` | List a project's HOA submissions | `ProjectManager`, `PlatformAdmin`, `Client` |
| POST | `/hoa-submissions/{id}/submit` | DRAFT/CONDITIONAL → SUBMITTED | `ProjectManager` |
| POST | `/hoa-submissions/{id}/decide` | SUBMITTED → APPROVED / CONDITIONAL / REJECTED | `PlatformAdmin` |
| POST | `/change-orders` | Create a change order (PROPOSED); OCC-guarded | `ProjectManager` |
| GET | `/change-orders/{id}` | Read a change order | `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/projects/{id}/change-orders` | List a project's change orders | `ProjectManager`, `PlatformAdmin`, `Client` |
| POST | `/change-orders/{id}/approve` | PROPOSED → APPROVED; recompute and possible revert | `ProjectManager` |
| POST | `/change-orders/{id}/reject` | PROPOSED → REJECTED | `ProjectManager` |
| POST | `/material-orders` | Create a material order (DRAFT) | `ProjectManager` |
| GET | `/material-orders/{id}` | Read a material order | `ProjectManager`, `PlatformAdmin` |
| GET | `/projects/{id}/material-orders` | List a project's material orders | `ProjectManager`, `PlatformAdmin` |
| POST | `/material-orders/{id}/place` | DRAFT → PLACED; pallet calc and capacity check | `ProjectManager` |
| POST | `/material-orders/{id}/confirm-delivery` | PLACED → DELIVERED | `ProjectManager` |
| POST | `/work-phases` | Create a build phase (PLANNED) | `ProjectManager` |
| GET | `/work-phases/{id}` | Read a work phase | `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/projects/{id}/work-phases` | List a project's work phases | `ProjectManager`, `PlatformAdmin`, `Client` |
| POST | `/work-phases/{id}/schedule` | PLANNED → SCHEDULED; book a crew | `ProjectManager` |
| POST | `/work-phases/{id}/start` | SCHEDULED → IN_PROGRESS | `ProjectManager` |
| POST | `/work-phases/{id}/complete` | IN_PROGRESS → COMPLETED; record installed quantities | `ProjectManager` |
| POST | `/draws` | Create a DEPOSIT or PROGRESS draw (PENDING); OCC-guarded | `ProjectManager` |
| GET | `/draws/{id}` | Read a draw | `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/projects/{id}/draws` | List a project's draws | `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/work-phases/{id}/draws` | List draws tied to a work phase | `ProjectManager`, `PlatformAdmin` |
| POST | `/draws/{id}/record-payment` | PENDING → PAID; credit amount paid | `ProjectManager` |
| POST | `/draws/{id}/refund` | PAID → REFUNDED; debit amount paid | `ProjectManager` |
| POST | `/warranty-claims` | File a warranty claim | `Client` |
| GET | `/warranty-claims/{id}` | Read a warranty claim | `ProjectManager`, `PlatformAdmin`, `Client` |
| GET | `/projects/{id}/warranty-claims` | List a project's warranty claims | `ProjectManager`, `PlatformAdmin`, `Client` |
| POST | `/warranty-claims/{id}/decide` | FILED → APPROVED / DENIED | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_PROJECT_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_DESIGN_REVISION_NOT_FOUND` | 404 Not Found |
| `ERR_SITE_MEASUREMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_HOA_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_MATERIAL_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_PHASE_NOT_FOUND` | 404 Not Found |
| `ERR_DRAW_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DESIGN_NOT_APPROVED` | 409 Conflict |
| `ERR_NO_MEASUREMENT` | 409 Conflict |
| `ERR_NO_LINE_ITEMS` | 409 Conflict |
| `ERR_DEPOSIT_NOT_PAID` | 409 Conflict |
| `ERR_HOA_NOT_APPROVED` | 409 Conflict |
| `ERR_PERMIT_NOT_APPROVED` | 409 Conflict |
| `ERR_MATERIAL_NOT_DELIVERED` | 409 Conflict |
| `ERR_NO_ORDERABLE_ITEMS` | 422 Unprocessable Entity |
| `ERR_DELIVERY_SLOT_FULL` | 409 Conflict |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_DRAW_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NOT_COMPLETED` | 409 Conflict |
| `ERR_WARRANTY_WINDOW_CLOSED` | 409 Conflict |
