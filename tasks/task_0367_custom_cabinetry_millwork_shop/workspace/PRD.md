# Custom Cabinetry & Millwork Shop API — Product Requirements Document

## 1. Introduction

A custom cabinetry and millwork shop turns a measured kitchen, vanity run, or built-in library into delivered, installed casework. The work moves through a long chain of hands — a designer captures dimensions and prices a quote, a customer signs and pays a deposit, a production manager reserves sheet stock and schedules cut-and-build jobs on the shop's CNC and assembly machines, change orders are negotiated mid-build, and finally an install crew delivers, hangs, and walks the finished job before the books are closed. This API is the system of record for that entire journey. It exists because the shop's money, materials, and machine time are all finite and interdependent: a sheet of plywood reserved for one project is unavailable to another, a build job booked on a machine blocks that machine's calendar, and every dollar billed against a contract must reconcile against what was actually agreed and paid.

The platform models five working roles — designers, shop managers, the buying customer, install crews, and an operational administrator — each owning a slice of the workflow but sharing a single consistent picture of every project. The hardest problems the system solves are the ones that cross boundaries: pricing that depends simultaneously on margin policy, quantity tier, and finish; a material ledger that must stay conserved as sheets are reserved, committed, consumed, and released; a billing ledger that must never over-bill a contract even as approved change orders move the contract total; and a production calendar that must respect machine changeover buffers and the shop's daily install capacity. Because several actors may be reading and writing the same project, the system uses explicit version checks on the most contested operations so that a stale view cannot silently overwrite a contract or a change order.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `ShopAdmin`, `ShopManager`, `Designer`, `Customer`, and `Installer`. If either header is missing, or `X-User-Role` is not one of these five names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). If the headers are valid but the named role is not authorized for the requested operation (see the endpoint table in §4 for each operation's permitted roles), the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Four of the five roles are opaque operator identities. When `X-User-Role` is `ShopAdmin`, `ShopManager`, `Designer`, or `Installer`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it but does not compare it to any entity's `id`. `ShopAdmin` is the operational superset — it may perform every operation any other role can, plus the two administrative operations reserved to it: creating a shop and setting the shop test clock. `ShopManager` runs production — materials, machines, reservations, build scheduling, draw billing, change-order authoring, and the production milestones of marking a project ready, closing it, and cancelling it. `Designer` owns design and measure — creating customers and projects, authoring cabinet specs and finish selections, and driving the measure, quote, and revise milestones. `Installer` owns delivery and install — scheduling and running installations, walkthroughs, punch items, reopen, and completion.

The `Customer` role is different: it is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks compare the target resource's owning customer to `X-User-ID`. A customer may only act on projects, draws, and change orders that belong to their own customer record: a project is owned by the customer named in its `customer_id`, and a draw or change order is owned transitively through the project it hangs off. When an entity-backed customer attempts to contract a project, pay a draw, or approve, reject, or request revision on a change order that they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0, with no upper bound but a minimum of 0. A request whose `limit` falls outside the range of 1 through 100, or whose `offset` is negative, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 422).

Unless an endpoint explicitly states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the query before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and Resource Identity

Every entity in the system carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. All thirteen entity types in this system — shops, customers, projects, cabinet specs, materials, material reservations, machines, build jobs, finish selections, draws, change orders, installations, and punch items — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every mutation, and a `version`, an integer that starts at the resource's creation value and increments by one on every mutation of that resource. The `version` field is the basis for the optimistic-concurrency checks described in §2.7.

Foreign-key fields that tie a resource to its parents and cross-references — for example a customer's `shop_id`, a project's `customer_id` and `shop_id`, a spec's `project_id` and `material_id`, a reservation's `project_id` and `material_id`, a build job's `project_id` and `machine_id`, a finish selection's `project_id`, a draw's `project_id`, a change order's `project_id`, an installation's `project_id`, and a punch item's `installation_id` and `project_id` — are system-managed and appear on the resource's representation; they are populated from the URL path or the request body at creation time and are not subsequently editable by the client.

### 2.5. Nested Resource Retrieval and Path Validation

Most write operations and many reads address a resource through a nested path that names its ancestors — a shop, then a project, then a sub-resource such as a draw or an installation, and sometimes a fourth level such as a punch item under an installation. The system validates these path identifiers strictly left to right. It first confirms the shop exists, then the project within that shop, then the sub-resource within that project (and, where present, the grandchild within that sub-resource). The first identifier in the path that does not resolve to an existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404); later identifiers are not examined. Alongside the nested action paths, the API also exposes flat single-resource reads (for example reading a project, draw, or installation directly by its own identifier) and flat foreign-key-filtered list reads for each entity, so that every entity is reachable both through its ownership tree and by reverse lookup from its foreign keys.

### 2.6. Monetary Values, Sheet Counts, and Rounding

All monetary amounts in the system are integers denominated in cents — contract totals, deposit amounts, line prices, draw amounts, late fees, and change-order deltas. Percentages and rates are expressed in basis points (one basis point is one hundredth of one percent, so 10000 basis points equals 100%). Wherever a calculation multiplies a cent amount by a basis-point rate and divides by 10000, the result is rounded to a whole number of cents using the round-half-up convention (a fractional remainder of exactly one half rounds up to the next whole cent). The calculation rules in §3 name each individual step at which this rounding is applied; rounding happens at each pinned step, not only at the end.

Material quantities are whole sheets. Sheet requirements derived from panel areas are rounded up to the next whole sheet (ceiling), and this ceiling is applied per cabinet spec before the per-spec results are summed — the system never pools fractional sheet remainders across specs. Stock counts (`on_hand_sheets`, `reserved_sheets`, `available_sheets`) are always whole integers.

### 2.7. Optimistic Concurrency Control on Project-Mutating Writes

Three operations that mutate a project's contract state are guarded by an optimistic-concurrency check keyed on the project's `version`: accepting a contract, submitting a change order, and approving a change order. Each of these operations requires the request body to carry `expected_project_version`, the integer `version` of the `Project` that the client last observed. Before the operation proceeds, the server compares `expected_project_version` against the project's current `version`. If they do not match — meaning another writer has advanced the project since the client read it — the operation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state change or ledger movement occurs.

The change-order submit operation is the most consequential of the three. Submitting a change order recomputes its monetary delta from the project's current contract total, margin policy, and active finish, and folds the project into a change-pending posture. If another change order has already been approved and has thereby advanced the project's `version` (and its contract total) since the submitter last read it, the submitter's view is stale and the recomputed delta would be keyed off an out-of-date base. The version check on `expected_project_version` converts this into a deterministic stale-version rejection carrying `ERR_STALE_VERSION` and HTTP 412, rather than allowing a delta computed against a contract total the submitter never saw. Operations not in this guarded set do not accept a version field and are not subject to this check.

### 2.8. Hierarchical Consistency and Cascading Effects

Many operations in this system mutate more than one resource. When a build job completes, when a contract is accepted, when a change order is approved, or when an installation completes, the primary state change drives a chain of secondary effects across reservations, materials, draws, and the parent project's ledger. Each such cascade is described in full within the relevant workflow in §3; the governing principle here is that whenever a side effect mutates a resource, that resource's own `updated_at` is refreshed and its `version` is incremented, exactly as if a client had written it directly. Project-level ledger fields — `billed_to_date_cents`, `paid_to_date_cents`, `contract_total_cents`, `deposit_required_cents`, `estimate_total_cents`, and `open_change_delta_cents` — are computed aggregates kept continuously reconciled as the draws and change orders beneath the project move through their lifecycles. Likewise a material's `reserved_sheets` and `available_sheets` are recomputed from its reservations whenever a reservation is created, committed, consumed, or released.

### 2.9. The Material Stock Ledger

Each `Material` carries three sheet counts that together form a conserved stock ledger. `on_hand_sheets` is the physical count in the rack; it starts at zero on material creation, is increased by restocking, and is decremented only when committed reservations are consumed by a completing build job. `reserved_sheets` is the sum of `sheets` across that material's reservations whose status is `HELD` or `COMMITTED`. `available_sheets` is `on_hand_sheets` minus `reserved_sheets` — the quota a new reservation is allowed to draw against. The invariant the system maintains is that reservations bite against available quota when created and return it when released, while consumption permanently removes sheets from on-hand. The detailed reservation lifecycle, its over-reservation behavior, and the stock-availability check live in §3.

### 2.10. The Project Billing Ledger and Fiscal Guards

A project's billing position is tracked by `billed_to_date_cents` (the sum of `amount_cents` over the project's draws in `ISSUED` or `PAID` status) and `paid_to_date_cents` (the sum of `amount_cents` over the project's `PAID` draws). The customer-level `lifetime_paid_cents` aggregates `amount_cents` across all `PAID` draws on all of that customer's projects. Three fiscal guards protect this ledger. A customer flagged with `credit_hold` set to true may neither have a new draw issued nor accept a new contract; both attempts are rejected with `ERR_CUSTOMER_CREDIT_HOLD`. A draw whose computed `amount_cents` is zero cannot be issued, and the attempt is rejected with `ERR_EMPTY_DRAW`. And a project cannot enter production until its deposit is fully paid, as detailed in §3. The deliberate design point is that the billing ledger can never over-bill: the draw amount calculation in §3 caps every draw so cumulative billing never exceeds the contract total.

## 3. Business Logic & Workflows

### 3.1. Shop Setup, Materials, and Machines

A `ShopAdmin` establishes a `Shop` by supplying a display `name` and optionally a `currency` (an ISO currency code defaulting to `USD`) and a set of basis-point configuration fields. `tax_rate_bps` is the sales tax applied to the taxable contract subtotal, defaulting to 0 and bounded to the range 0 through 2000. `deposit_pct_bps` is the deposit percentage of the contract total used to compute the deposit draw, defaulting to 3000 and bounded 0 through 10000. `retainage_pct_bps` is the percentage withheld until install completion, defaulting to 1000 and bounded 0 through 5000. `rush_surcharge_bps` is the surcharge added to the contract total when a project is flagged rush, defaulting to 1500 and bounded 0 through 5000. `max_installs_per_day` is the shop-wide install-slot capacity per calendar day, defaulting to 2 and required to be at least 1. The `change_order_buffer_pct_bps` field is reserved for future goodwill discounting, is unused in pricing, and is kept at 0. A shop also carries `current_utc`, a test clock that begins null and is set only through the administrative clock endpoint; this clock is the system's `now()` for all scheduling and draw-due comparisons.

The shop test clock is set by a `ShopAdmin` through a dedicated test-driving capability that takes a `shop_id` naming the target shop and a `to_iso8601` instant; it writes that instant to the shop's `current_utc` and returns the shop. Until the clock is set, `current_utc` remains null.

A `Material` is a sheet-stock SKU created by a `ShopManager` or `ShopAdmin` with a `sku` (unique within the shop), a `sheet_area_mm2` (the usable area of one sheet in square millimeters, which must be greater than zero), and a `sheet_price_cents` (price per sheet, at least zero). A new material begins with `on_hand_sheets`, `reserved_sheets`, and `available_sheets` all at zero. Physical inventory is added through a restock capability that accepts a `sheets` count and adds it to `on_hand_sheets`, then recomputes `available_sheets`.

A `Machine` is a CNC or build station created by a `ShopManager` or `ShopAdmin` with a `name`, an optional `changeover_buffer_min` (the mandatory idle buffer in minutes required between two build jobs on that machine, defaulting to 30 and at least zero), and an optional `status` (`ONLINE` or `OFFLINE`, defaulting to `ONLINE`). A machine's status may later be toggled between `ONLINE` and `OFFLINE`; an `OFFLINE` machine refuses to start new build jobs as described in §3.6.

### 3.2. Customers and Project Intake

A `Customer` is created under a shop by a `ShopAdmin`, `ShopManager`, or `Designer` with a `full_name` and an `email` (unique within the shop). New customers start with `credit_hold` false and `lifetime_paid_cents` zero. A manager or admin may later toggle `credit_hold` on or off for a customer; while the hold is on, the fiscal guards in §2.10 block both draw issuance and contract acceptance for that customer's projects.

A `Project` is the central organizing entity. A designer, manager, or admin opens one under a customer by supplying a `title`, an optional `is_rush` flag (default false), an optional `install_address`, and an optional `margin_policy` of either `STANDARD` or `PREMIUM` (default `STANDARD`). The margin policy selects which margin-tier table the contract-total calculation draws from. A freshly created project begins in `DRAFT` status with all of its ledger fields — `estimate_total_cents`, `contract_total_cents`, `deposit_required_cents`, `billed_to_date_cents`, `paid_to_date_cents`, and `open_change_delta_cents` — set to zero. The project carries a `status` enumeration that moves through `DRAFT`, `MEASURED`, `QUOTED`, `CONTRACTED`, `IN_PRODUCTION`, `CHANGE_PENDING`, `READY_FOR_DELIVERY`, `INSTALLED`, `CLOSED`, and `CANCELLED`; `CLOSED` and `CANCELLED` are terminal. The `open_change_delta_cents` field is an informational running sum of the `delta_cents` of the project's change orders that are `APPROVED` but not yet folded.

### 3.3. Cabinet Specs, the Cut List, and Estimating

While a project's specs remain editable, a designer (or manager or admin) builds out its bill of cabinets by adding `CabinetSpec` rows. Each spec carries a `label`, the dimensions `width_mm`, `height_mm`, and `depth_mm` (each a positive integer in millimeters), a `quantity` of identical cabinets (at least one), a `base_unit_price_cents` (the pre-margin, pre-finish per-cabinet cost, at least zero), and a `material_id` naming the sheet stock the cabinet is cut from. On creation the system computes the spec's `panel_area_mm2`, the total flat-panel area of one cabinet, as two times the product of width and height, plus two times the product of height and depth, plus one times the product of width and depth. Each spec also carries a `lock_state` of `OPEN` or `LOCKED`, beginning `OPEN`; a spec may be added or deleted only while `OPEN`, and any attempt to add or delete a spec after the specs have been locked (which happens at contract acceptance, described in §3.4) is rejected with `ERR_SPECS_LOCKED`. Adding or deleting a spec recomputes the project's `estimate_total_cents`.

The cut list is a computed read available to designers and managers that reports, per material, how many sheets the project requires. For each cabinet spec, the system takes the spec's `panel_area_mm2` and multiplies it by the spec's `quantity` to get the total panel area for that line; it then inflates that area by a 12% saw-kerf and offcut waste uplift (that is, it multiplies the total panel area by 11200 and divides by 10000), divides the inflated area by the spec's material's `sheet_area_mm2`, and rounds that quotient up to the next whole sheet. These per-spec sheet counts are then summed within each material to yield the project's per-material requirement. The ceiling is applied to each spec individually before summing; the system does not pool fractional sheets across specs, so summing the ceilings of two specs can exceed the ceiling of their combined area. All specs are included in this computation regardless of their `lock_state`. The cut-list response reports each material together with its required `total_sheets`.

A project's forward-looking estimate is held in `estimate_total_cents` and recomputed whenever a spec is added or removed and at the measure and quote milestones. The estimate uses the estimate variant of the contract-total calculation defined in §3.4: it prices every cabinet spec regardless of `lock_state`, uses the active finish's upcharge if a finish has been selected (otherwise treating the finish as `RAW` with a zero upcharge), and does not apply the rush surcharge.

### 3.4. Pricing: Contract Total, Margin Tiers, and Finish

The contract-total calculation prices a project's cabinets and is the heart of the system's money math. It runs in two variants — an estimate variant that writes `estimate_total_cents`, and a final variant that writes `contract_total_cents` at contract acceptance — that share one pricing pipeline and differ only as noted below.

For each cabinet spec, the pipeline begins with a line base equal to `base_unit_price_cents` multiplied by `quantity`. It then selects a margin multiplier in basis points from a margin table, indexed first by the project's `margin_policy` and second by the spec's own quantity tier. The quantity tier is `SMALL` when `quantity` is at most 2, `MED` when `quantity` is 3 through 6, and `BULK` when `quantity` is 7 or more. Under the `STANDARD` policy the multipliers are 13500 basis points for `SMALL`, 13000 for `MED`, and 12500 for `BULK`; under the `PREMIUM` policy they are 16000 for `SMALL`, 15500 for `MED`, and 15000 for `BULK`. The margined line is the line base multiplied by the selected multiplier, divided by 10000, rounded half up to whole cents. Next, a finish upcharge is computed as the margined line multiplied by the finish's basis-point rate, divided by 10000, rounded half up to whole cents; the finish rates are 0 basis points for `RAW`, 800 for `STAIN`, 1200 for `PAINT`, and 2000 for `LACQUER`. The line total is the margined line plus the finish upcharge. Each line total is then clamped into the inclusive range from a minimum of 5000 cents to a maximum of 5000000 cents: any line below 5000 is raised to 5000, and any line above 5000000 is lowered to 5000000.

The subtotal is the sum of the clamped line totals across the included specs. In the final variant only, if the project's `is_rush` flag is true, a rush surcharge equal to the subtotal multiplied by the shop's `rush_surcharge_bps`, divided by 10000 and rounded half up, is added to the subtotal. Finally, tax is computed as the subtotal multiplied by the shop's `tax_rate_bps`, divided by 10000 and rounded half up to whole cents, and the total is the subtotal plus the tax. The estimate variant prices all specs regardless of `lock_state`, treats a missing finish as `RAW` at zero basis points, and never applies the rush surcharge. The final variant requires every spec to be `LOCKED` and a finish to be active, and applies the rush surcharge when `is_rush` is true; for an identical set of specs and finish, the final total is therefore at least the estimate and is strictly greater whenever the project is rush or a finish was chosen after the estimate was last taken.

### 3.5. The Design-to-Contract Lifecycle

A designer advances a `DRAFT` project to `MEASURED` once the design is captured. This measure step requires that at least one `CabinetSpec` exists on the project — otherwise it is rejected with `ERR_NO_SPECS` — and that every spec has positive `width_mm`, `height_mm`, and `depth_mm` and a `quantity` of at least one. As its side effect, the measure step recomputes `estimate_total_cents` over all cabinet specs using the estimate variant.

Finish is chosen by a designer through a finish selection. Each `FinishSelection` carries a `finish_code` of `RAW`, `STAIN`, `PAINT`, or `LACQUER`, an optional `sheen` of `MATTE`, `SATIN`, or `GLOSS` (default `SATIN`), and an `is_active` flag. Exactly one finish selection per project is active at a time: selecting a new finish sets the previously active selection's `is_active` to false and the new one's `is_active` to true, and recomputes `estimate_total_cents`.

Moving a `MEASURED` project to `QUOTED` requires that exactly one finish selection is active, failing with `ERR_FINISH_REQUIRED` otherwise; the quote step recomputes `estimate_total_cents` including the active finish's upcharge. From `QUOTED`, a designer may loop the project back to `DRAFT` to reopen spec editing; this revise step has no preconditions, and `estimate_total_cents` is left at its last computed value until the next measure. A project may cycle through `DRAFT`, `MEASURED`, `QUOTED`, and back to `DRAFT` any number of times before a contract is accepted.

Contract acceptance is performed by the owning `Customer` on a `QUOTED` project and is the system's pivotal commitment. It requires `expected_project_version` to match the project's `version` (otherwise `ERR_STALE_VERSION`, HTTP 412) and the customer's `credit_hold` to be false (otherwise `ERR_CUSTOMER_CREDIT_HOLD`). On success it performs a cascade: it sets `lock_state` to `LOCKED` on every cabinet spec; it computes `contract_total_cents` using the final variant of the contract-total calculation, including the rush surcharge when `is_rush` is true; it computes `deposit_required_cents` as the contract total multiplied by the shop's `deposit_pct_bps`, divided by 10000 and rounded half up; it creates one `DEPOSIT` draw in `PENDING` status as the first hop of the contract-lock chain; and it increments the project's `version` by one, moving the project from `QUOTED` to `CONTRACTED`.

### 3.6. Material Reservations and Production Build Jobs

Production draws sheet stock through material reservations. A `ShopManager` or `ShopAdmin` reserves stock by creating a `MaterialReservation` against a `material_id` for a given number of `sheets` (at least one); the reservation starts in `HELD` status. Reservation is forward-looking and provisional: the requested `sheets` are added to the material's `reserved_sheets` up front, which lowers `available_sheets`, even though the eventual build may consume fewer sheets. A reservation may be created only when its requested `sheets` does not exceed the material's `available_sheets` at create time; a request that would over-allocate is rejected with `ERR_INSUFFICIENT_STOCK`. A held reservation can be released, returning its `sheets` to the available quota, which restores the material's availability to its pre-hold value.

A reservation moves from `HELD` to `COMMITTED` through a commit action, which is permitted only while the project's status is `IN_PRODUCTION` or `CHANGE_PENDING`, failing otherwise with `ERR_INVALID_STATE`. A `HELD` reservation may be released at any time; a `COMMITTED` reservation may be released only while the project is not `IN_PRODUCTION`, and an attempt to release a committed reservation during production is rejected with `ERR_RESERVATION_LOCKED`. Releasing a reservation, whether held or committed, drops `reserved_sheets` by its `sheets` count as a compensating adjustment. A reservation reaches `CONSUMED` only as a system effect of a build completing, never by direct client action. A reservation's status enumeration is `HELD`, `COMMITTED`, `CONSUMED`, and `RELEASED`, the last two terminal.

Production work is scheduled as build jobs. A `ShopManager` or `ShopAdmin` schedules a `BuildJob` by naming a `machine_id`, a `start_utc` (inclusive), and an `end_utc` (exclusive), where `end_utc` must be strictly after `start_utc`. The referenced machine must belong to the same shop as the project — a material, machine, or project referenced from a different shop is rejected with `ERR_CROSS_SHOP_REFERENCE`, a check that also guards spec creation and reservation creation. A new build job's time interval, from `start_utc` up to but not including `end_utc`, must not collide with any other non-cancelled build job on the same machine, and the collision test extends the machine's `changeover_buffer_min` gap onto either side of the interval; a clash is rejected with `ERR_MACHINE_TIME_CONFLICT`. Crucially, scheduling the first build job on a `CONTRACTED` project is what moves the project to `IN_PRODUCTION`, and that transition is gated: the project's `paid_to_date_cents` must be at least its `deposit_required_cents`, otherwise the build job is refused with `ERR_DEPOSIT_UNPAID`. A new build job begins in `SCHEDULED` status.

A scheduled build job is started by a manager or admin, which requires the job's machine to be `ONLINE` (otherwise `ERR_MACHINE_OFFLINE`) and moves the job to `IN_PROGRESS`. Completing an in-progress job moves it to `COMPLETE` and triggers a consumption cascade: every `COMMITTED` reservation on the project transitions to `CONSUMED`, and for each, the material's `on_hand_sheets` is decremented by the reservation's `sheets` and its `reserved_sheets` drops correspondingly — so only committed reservations are consumed, while any reservation that is still merely `HELD` is not consumed even though it held quota. A scheduled job may instead be cancelled, moving it to `CANCELLED`. A build job's status enumeration is `SCHEDULED`, `IN_PROGRESS`, `COMPLETE`, and `CANCELLED`.

### 3.7. Change Orders and the Revision Loop

Once a project is `IN_PRODUCTION`, mid-build changes are handled through change orders. A `ShopManager` or `ShopAdmin` creates a `ChangeOrder` with a `description` and a `spec_price_delta_cents`, a signed pre-margin per-project subtotal change that may be negative. A new change order begins in `DRAFT` status with `revision_round` 1. The change order carries a computed `delta_cents` — the margin-, finish-, and tax-adjusted signed change to the contract total — that is set when the change order is submitted and frozen at approval. Its status enumeration is `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`, `REVISING`, and `CANCELLED`, of which `APPROVED`, `REJECTED`, and `CANCELLED` are terminal.

Submitting a draft change order is a manager action that requires the project to be `IN_PRODUCTION`, failing otherwise with `ERR_INVALID_STATE`, and requires `expected_project_version` to match the project's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.7. Submission computes `delta_cents` using the change-order delta calculation against the project's current margin policy and active finish, drives the project from `IN_PRODUCTION` to `CHANGE_PENDING`, and increments the project's `version` by one. While a change order sits in `SUBMITTED` or `REVISING`, the project is frozen for production scheduling.

The change-order delta calculation mirrors the contract-total pipeline but is always priced at the `BULK` margin tier. It takes the signed `spec_price_delta_cents`, multiplies it by the project's margin-policy `BULK` multiplier (12500 basis points under `STANDARD`, 15000 under `PREMIUM`), divides by 10000, and rounds half up to a margined figure that preserves the sign. It then computes a finish upcharge as the margined figure multiplied by the active finish's basis-point rate (0 for `RAW`, 800 for `STAIN`, 1200 for `PAINT`, 2000 for `LACQUER`), divided by 10000 and rounded half up. The line delta is the margined figure plus that finish upcharge. Tax is then computed as the line delta multiplied by the shop's `tax_rate_bps`, divided by 10000 and rounded half up, and `delta_cents` is the line delta plus that tax. The sign is preserved through every step, so a negative `spec_price_delta_cents` yields a negative `delta_cents` that reduces the contract.

The customer drives the change order's resolution. A submitted change order may be sent back by the customer for revision, moving it to `REVISING` while the project stays `CHANGE_PENDING` and its `delta_cents` is retained pending resubmit. A manager then resubmits a revising change order, which increments `revision_round` by one and recomputes `delta_cents`, returning it to `SUBMITTED`; a change order may bounce between `SUBMITTED` and `REVISING` over multiple rounds. A submitted change order may be approved by the customer, which requires `expected_project_version` to match the project's `version` (otherwise `ERR_STALE_VERSION`, HTTP 412). Approval freezes `delta_cents` and drives the project from `CHANGE_PENDING` back to `IN_PRODUCTION` with a ledger fold: the project's `contract_total_cents` is increased by `delta_cents`, `deposit_required_cents` is recomputed, a `PROGRESS` adjustment draw in `PENDING` status is created for the larger of zero and `delta_cents`, and the project's `version` is incremented by one. Alternatively the customer may reject a submitted change order, which drives the project from `CHANGE_PENDING` back to `IN_PRODUCTION` with no ledger change and increments the project's `version` by one. A draft change order that has not been submitted may be cancelled by a manager, moving it to `CANCELLED` with no effect on the project.

### 3.8. Draws, Billing, and Settlement

The project's money is billed in draws. Deposit and retainage draws are created automatically by the system as side effects of contract acceptance and install completion respectively, while progress draws are created on demand by a `ShopManager` or `ShopAdmin`. A `Draw` carries a `draw_type` of `DEPOSIT`, `PROGRESS`, or `RETAINAGE` that selects the amount formula variant, an optional `requested_pct_bps` used only for progress draws (and ignored for deposit and retainage draws), a computed `amount_cents` that is immutable once the draw is created, an optional `due_utc` used for late-fee tiering at payment time, a computed `late_fee_cents` defaulting to zero, and a `status` of `PENDING`, `ISSUED`, `PAID`, or `VOIDED`, where `PAID` and `VOIDED` are terminal.

A draw's `amount_cents` is computed by the draw-amount calculation, a waterfall that never lets cumulative billing exceed the contract. The calculation first determines the remaining billable amount as the project's `contract_total_cents` minus its `billed_to_date_cents`. It then computes a raw amount according to the draw type: for a `DEPOSIT` draw the raw amount is the contract total multiplied by the shop's `deposit_pct_bps`, divided by 10000 and rounded half up; for a `PROGRESS` draw it is the contract total multiplied by the request's `requested_pct_bps`, divided by 10000 and rounded half up; for a `RETAINAGE` draw it is the contract total multiplied by the shop's `retainage_pct_bps`, divided by 10000 and rounded half up. The draw's `amount_cents` is then the lesser of that raw amount and the remaining billable, and if that result is negative it is set to zero. Because the retainage draw is created last, after deposit and progress billing, its cap clears the remaining balance so that cumulative billing equals the contract total exactly.

A pending draw is issued by a manager. Issuing requires the customer's `credit_hold` to be false (otherwise `ERR_CUSTOMER_CREDIT_HOLD`) and the draw's `amount_cents` to be greater than zero (otherwise `ERR_EMPTY_DRAW`); on success the draw moves to `ISSUED` and its `amount_cents` is added to the project's `billed_to_date_cents`. An issued draw is paid by the owning customer, which moves it to `PAID`, computes its late fee per the settlement calculation below, and adds its `amount_cents` to both the project's `paid_to_date_cents` and the customer's `lifetime_paid_cents`. A draw may be voided by a manager from either `PENDING` or `ISSUED`; voiding a pending draw simply marks it `VOIDED`, while voiding an issued draw additionally subtracts its `amount_cents` back out of the project's `billed_to_date_cents`, leaving that ledger at its pre-issue value so that billing stays conserved under the issue-then-void pair.

The draw settlement calculation runs when an issued draw is paid and produces `late_fee_cents`. If the draw has no `due_utc`, or the shop's `current_utc` is at or before the `due_utc`, then the draw is not late and `days_late` is zero. Otherwise `days_late` is the whole number of days from `due_utc` to `current_utc`, computed by taking the elapsed time in seconds, dividing by 86400 seconds per day, and discarding any fractional remainder (floor to whole days). The late-fee rate is then selected by tier: if `days_late` is zero or fewer the rate is zero basis points; if `days_late` is from 1 through 30 inclusive the rate is 150 basis points; and if `days_late` is greater than 30 the rate is 400 basis points. The `late_fee_cents` is the draw's `amount_cents` multiplied by the selected rate, divided by 10000 and rounded half up. The settlement total a customer owes is the `amount_cents` plus the `late_fee_cents`, but note that only the principal `amount_cents` flows into `paid_to_date_cents` and `lifetime_paid_cents`; the late fee is recorded on the draw and is not counted toward the contract balance.

### 3.9. Delivery, Installation, and the Punch Loop

Once production is finished, a manager marks the project ready for delivery. Marking ready advances the project from `IN_PRODUCTION` to `READY_FOR_DELIVERY` and requires that every build job on the project is `COMPLETE` (otherwise `ERR_BUILD_INCOMPLETE`) and that no change order on the project is in `SUBMITTED` or `REVISING` status (otherwise `ERR_CHANGE_OPEN`).

Delivery and install are scheduled and run by an `Installer` (or a manager or admin). An `Installation` is scheduled with an `install_date` (a calendar date in YYYY-MM-DD form), a `window_start_utc` (the crew arrival window start, inclusive), and a `window_end_utc` (the window end, exclusive, strictly after the start). The `install_date` counts against the shop's `max_installs_per_day` aggregate daily capacity across the whole shop: if the number of non-cancelled installations already scheduled for that date is at the shop's limit, a new installation for that date is rejected with `ERR_INSTALL_CAPACITY_FULL`. A new installation begins in `SCHEDULED` status, with the enumeration `SCHEDULED`, `IN_PROGRESS`, `PUNCH_PENDING`, `COMPLETE`, and `CANCELLED`.

An installer starts a scheduled installation, which requires the project to be in `READY_FOR_DELIVERY` (otherwise `ERR_PROJECT_NOT_READY`) and moves it to `IN_PROGRESS`. After the work, the crew performs a walkthrough, moving the installation from `IN_PROGRESS` to `PUNCH_PENDING`. During and after the walkthrough, the crew logs defects as punch items. A `PunchItem` carries a `description`, a `severity` of `MINOR` or `MAJOR` (default `MINOR`), and a `status` of `OPEN` or `RESOLVED`, beginning `OPEN`; it is created under an installation and records both its `installation_id` and `project_id`. A punch item is resolved by the crew, moving it from `OPEN` to `RESOLVED`.

Completing an installation moves it from `PUNCH_PENDING` to `COMPLETE` and requires that no punch item on it has `severity` of `MAJOR` and `status` of `OPEN` — an open major defect blocks completion and is rejected with `ERR_MAJOR_PUNCH_OPEN`. If instead the crew needs to redo work, a `PUNCH_PENDING` installation may be reopened back to `IN_PROGRESS`, which requires that at least one punch item is still `OPEN` (otherwise `ERR_NOTHING_TO_REOPEN`); this forms the punch reopen loop in which an installation cycles `PUNCH_PENDING`, `IN_PROGRESS`, and back to `PUNCH_PENDING`. A scheduled installation may also be cancelled by an installer or manager. When an installation reaches `COMPLETE`, it bubbles up to the project: the system drives the project from `READY_FOR_DELIVERY` to `INSTALLED` and creates one `RETAINAGE` draw in `PENDING` status as the first hop of the install chain.

### 3.10. Closing and Cancelling Projects

A manager closes an `INSTALLED` project, moving it to `CLOSED`. Closing requires the project to be fully paid — `paid_to_date_cents` must be at least `contract_total_cents`, otherwise `ERR_BALANCE_OUTSTANDING` — and requires that no punch item on any of the project's installations is still `OPEN`, otherwise `ERR_PUNCH_OPEN`. On close, any remaining `HELD` material reservations are released back to stock.

A project may be cancelled by a manager from any non-terminal pre-install state. From `DRAFT`, `MEASURED`, or `QUOTED`, cancellation has no fiscal precondition and releases all of the project's non-terminal reservations — every `HELD` or `COMMITTED` reservation moves to `RELEASED`. From `CONTRACTED`, cancellation is allowed only if nothing has been paid yet: `paid_to_date_cents` must be zero, otherwise the cancel is rejected with `ERR_DEPOSIT_PAID_NO_CANCEL`; when permitted, it voids all `PENDING` and `ISSUED` draws and releases all non-terminal reservations. Cancellation drives the project to the terminal `CANCELLED` status.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource or list, or that modify or transition an existing resource (including all state-transition actions and configuration updates), return `200 OK`. Every operation is subject to the validation precedence the system applies uniformly: user-context authentication (`ERR_MISSING_OR_INVALID_USER_CONTEXT`, 401) is checked first; then role authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`, 403); then, for customer-actor endpoints, resource ownership (`ERR_NOT_RESOURCE_OWNER`, 403); then existence of every path-referenced resource left to right (`ERR_NOT_FOUND`, 404); then request-body validity such as required fields, enum ranges, positive dimensions and quantities, and basis-point bounds (`ERR_INVALID_REQUEST`, 422); then that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409); then cross-shop reference resolution (`ERR_CROSS_SHOP_REFERENCE`, 409); then the remaining domain checks — machine-online, machine time-conflict, install capacity, stock sufficiency, deposit-paid, credit-hold, empty-draw, build/change/punch/balance guards — and finally the optimistic-concurrency version check (`ERR_STALE_VERSION`, 412) on the three guarded project writes.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shops` | Create a shop | ShopAdmin |
| GET | `/shops/{shopId}` | Get a shop | ShopAdmin, ShopManager, Designer, Installer, Customer |
| POST | `/_clock/set_current_utc` | Set the shop test clock used as now() | ShopAdmin |
| POST | `/shops/{shopId}/materials` | Create a material SKU | ShopAdmin, ShopManager |
| GET | `/shops/{shopId}/materials/{materialId}` | Get a material with computed reserved/available | ShopAdmin, ShopManager, Designer |
| GET | `/shops/{shopId}/materials` | List materials in a shop | ShopAdmin, ShopManager, Designer |
| POST | `/shops/{shopId}/materials/{materialId}/restock` | Add physical sheets to on-hand | ShopAdmin, ShopManager |
| POST | `/shops/{shopId}/machines` | Create a CNC/build machine | ShopAdmin, ShopManager |
| GET | `/shops/{shopId}/machines/{machineId}` | Get a machine | ShopAdmin, ShopManager |
| PATCH | `/shops/{shopId}/machines/{machineId}` | Update machine status | ShopAdmin, ShopManager |
| POST | `/shops/{shopId}/customers` | Create a customer | ShopAdmin, ShopManager, Designer |
| GET | `/shops/{shopId}/customers/{customerId}` | Get a customer | ShopAdmin, ShopManager, Designer, Customer |
| PATCH | `/shops/{shopId}/customers/{customerId}` | Set or clear customer credit hold | ShopAdmin, ShopManager |
| GET | `/shops/{shopId}/customers` | List customers | ShopAdmin, ShopManager, Designer |
| POST | `/shops/{shopId}/customers/{customerId}/projects` | Create a project | ShopAdmin, ShopManager, Designer |
| GET | `/shops/{shopId}/projects/{projectId}` | Get a project with computed ledger fields | ShopAdmin, ShopManager, Designer, Installer, Customer |
| GET | `/shops/{shopId}/projects` | List projects, filterable | ShopAdmin, ShopManager, Designer, Installer, Customer |
| GET | `/shops/{shopId}/customers/{customerId}/projects` | List a customer's projects | ShopAdmin, ShopManager, Designer, Customer |
| GET | `/shops/{shopId}/projects/{projectId}/cut-list` | Computed per-material sheet requirements | ShopAdmin, ShopManager, Designer |
| POST | `/shops/{shopId}/projects/{projectId}/measure` | DRAFT to MEASURED; recompute estimate | Designer, ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/quote` | MEASURED to QUOTED; finalize estimate with finish | Designer, ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/revise` | QUOTED to DRAFT, revision loop | Designer, ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/contract` | QUOTED to CONTRACTED; lock specs, compute total, create deposit draw | Customer |
| POST | `/shops/{shopId}/projects/{projectId}/mark-ready` | IN_PRODUCTION to READY_FOR_DELIVERY | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/close` | INSTALLED to CLOSED | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/cancel` | Cancel a project from a non-terminal pre-install state | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/specs` | Add a cabinet spec while specs OPEN | Designer, ShopManager, ShopAdmin |
| GET | `/shops/{shopId}/projects/{projectId}/specs/{specId}` | Get a cabinet spec | ShopAdmin, ShopManager, Designer |
| GET | `/shops/{shopId}/projects/{projectId}/specs` | List specs | ShopAdmin, ShopManager, Designer |
| DELETE | `/shops/{shopId}/projects/{projectId}/specs/{specId}` | Remove a spec while OPEN | Designer, ShopManager, ShopAdmin |
| GET | `/shops/{shopId}/projects/{projectId}/specs-by-material` | List specs filtered by material | ShopAdmin, ShopManager, Designer |
| POST | `/shops/{shopId}/projects/{projectId}/finish-selections` | Select a finish, deactivating the prior | Designer, ShopManager, ShopAdmin |
| GET | `/shops/{shopId}/projects/{projectId}/finish-selections` | List finish selections | ShopAdmin, ShopManager, Designer |
| GET | `/shops/{shopId}/projects/{projectId}/finish-selections/{finishSelectionId}` | Get a finish selection | ShopAdmin, ShopManager, Designer |
| POST | `/shops/{shopId}/projects/{projectId}/material-reservations` | Reserve sheets from a material | ShopManager, ShopAdmin |
| GET | `/shops/{shopId}/projects/{projectId}/material-reservations/{reservationId}` | Get a reservation | ShopAdmin, ShopManager |
| GET | `/shops/{shopId}/projects/{projectId}/material-reservations` | List reservations for a project | ShopAdmin, ShopManager |
| GET | `/shops/{shopId}/material-reservations` | List reservations filtered by material | ShopAdmin, ShopManager |
| POST | `/shops/{shopId}/projects/{projectId}/material-reservations/{reservationId}/commit` | HELD to COMMITTED | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/material-reservations/{reservationId}/release` | HELD/COMMITTED to RELEASED | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/build-jobs` | Schedule a build job; first job moves project to IN_PRODUCTION | ShopManager, ShopAdmin |
| GET | `/shops/{shopId}/projects/{projectId}/build-jobs/{buildJobId}` | Get a build job | ShopAdmin, ShopManager |
| GET | `/shops/{shopId}/projects/{projectId}/build-jobs` | List build jobs for a project | ShopAdmin, ShopManager |
| GET | `/shops/{shopId}/build-jobs` | List build jobs filtered by machine | ShopAdmin, ShopManager |
| POST | `/shops/{shopId}/projects/{projectId}/build-jobs/{buildJobId}/start` | SCHEDULED to IN_PROGRESS | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/build-jobs/{buildJobId}/complete` | IN_PROGRESS to COMPLETE; consume committed reservations | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/build-jobs/{buildJobId}/cancel` | SCHEDULED to CANCELLED | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/change-orders` | Create a change order | ShopManager, ShopAdmin |
| GET | `/shops/{shopId}/projects/{projectId}/change-orders/{changeOrderId}` | Get a change order | ShopAdmin, ShopManager, Customer |
| GET | `/shops/{shopId}/projects/{projectId}/change-orders` | List change orders | ShopAdmin, ShopManager, Customer |
| POST | `/shops/{shopId}/projects/{projectId}/change-orders/{changeOrderId}/submit` | DRAFT to SUBMITTED; compute delta; project to CHANGE_PENDING | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/change-orders/{changeOrderId}/request-revision` | SUBMITTED to REVISING | Customer |
| POST | `/shops/{shopId}/projects/{projectId}/change-orders/{changeOrderId}/resubmit` | REVISING to SUBMITTED; bump revision; recompute delta | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/change-orders/{changeOrderId}/approve` | SUBMITTED to APPROVED; fold delta; create progress draw | Customer |
| POST | `/shops/{shopId}/projects/{projectId}/change-orders/{changeOrderId}/reject` | SUBMITTED to REJECTED; no ledger change | Customer |
| POST | `/shops/{shopId}/projects/{projectId}/change-orders/{changeOrderId}/cancel` | DRAFT to CANCELLED | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/draws` | Create a progress draw on demand | ShopManager, ShopAdmin |
| GET | `/shops/{shopId}/projects/{projectId}/draws/{drawId}` | Get a draw | ShopAdmin, ShopManager, Customer |
| GET | `/shops/{shopId}/projects/{projectId}/draws` | List draws | ShopAdmin, ShopManager, Customer |
| POST | `/shops/{shopId}/projects/{projectId}/draws/{drawId}/issue` | PENDING to ISSUED; bill to project ledger | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/draws/{drawId}/pay` | ISSUED to PAID; compute late fee; credit ledgers | Customer |
| POST | `/shops/{shopId}/projects/{projectId}/draws/{drawId}/void` | PENDING/ISSUED to VOIDED; compensate billed ledger if ISSUED | ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/installations` | Schedule a delivery/install | Installer, ShopManager, ShopAdmin |
| GET | `/shops/{shopId}/projects/{projectId}/installations/{installationId}` | Get an installation | ShopAdmin, ShopManager, Installer, Customer |
| GET | `/shops/{shopId}/projects/{projectId}/installations` | List installations | ShopAdmin, ShopManager, Installer, Customer |
| POST | `/shops/{shopId}/projects/{projectId}/installations/{installationId}/start` | SCHEDULED to IN_PROGRESS | Installer, ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/installations/{installationId}/walkthrough` | IN_PROGRESS to PUNCH_PENDING | Installer, ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/installations/{installationId}/reopen` | PUNCH_PENDING to IN_PROGRESS | Installer, ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/installations/{installationId}/complete` | PUNCH_PENDING to COMPLETE; bubble project to INSTALLED | Installer, ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/installations/{installationId}/cancel` | SCHEDULED to CANCELLED | Installer, ShopManager, ShopAdmin |
| POST | `/shops/{shopId}/projects/{projectId}/installations/{installationId}/punch-items` | Add a punch/touch-up item | Installer, ShopManager, ShopAdmin |
| GET | `/shops/{shopId}/projects/{projectId}/installations/{installationId}/punch-items/{punchItemId}` | Get a punch item | ShopAdmin, ShopManager, Installer, Customer |
| GET | `/shops/{shopId}/projects/{projectId}/installations/{installationId}/punch-items` | List punch items for an installation | ShopAdmin, ShopManager, Installer, Customer |
| GET | `/shops/{shopId}/projects/{projectId}/punch-items` | List punch items filtered by project | ShopAdmin, ShopManager, Installer, Customer |
| POST | `/shops/{shopId}/projects/{projectId}/installations/{installationId}/punch-items/{punchItemId}/resolve` | OPEN to RESOLVED | Installer, ShopManager, ShopAdmin |
| GET | `/customers/{customerId}` | Flat read of a customer | ShopAdmin, ShopManager, Designer, Customer |
| GET | `/customers` | Flat list of customers filtered by shop | ShopAdmin, ShopManager, Designer |
| GET | `/projects/{projectId}` | Flat read of a project | ShopAdmin, ShopManager, Designer, Installer, Customer |
| GET | `/projects` | Flat list of projects filtered by customer/shop/status | ShopAdmin, ShopManager, Designer, Installer, Customer |
| GET | `/specs/{specId}` | Flat read of a cabinet spec | ShopAdmin, ShopManager, Designer |
| GET | `/specs` | Flat list of specs filtered by project/material | ShopAdmin, ShopManager, Designer |
| GET | `/materials/{materialId}` | Flat read of a material | ShopAdmin, ShopManager, Designer |
| GET | `/materials` | Flat list of materials filtered by shop | ShopAdmin, ShopManager, Designer |
| GET | `/material-reservations/{reservationId}` | Flat read of a material reservation | ShopAdmin, ShopManager |
| GET | `/material-reservations` | Flat list of reservations filtered by project/material | ShopAdmin, ShopManager |
| GET | `/machines/{machineId}` | Flat read of a machine | ShopAdmin, ShopManager |
| GET | `/machines` | Flat list of machines filtered by shop | ShopAdmin, ShopManager |
| GET | `/build-jobs/{buildJobId}` | Flat read of a build job | ShopAdmin, ShopManager |
| GET | `/build-jobs` | Flat list of build jobs filtered by project/machine | ShopAdmin, ShopManager |
| GET | `/finish-selections/{finishSelectionId}` | Flat read of a finish selection | ShopAdmin, ShopManager, Designer |
| GET | `/finish-selections` | Flat list of finish selections filtered by project | ShopAdmin, ShopManager, Designer |
| GET | `/draws/{drawId}` | Flat read of a draw | ShopAdmin, ShopManager, Customer |
| GET | `/draws` | Flat list of draws filtered by project/type/status | ShopAdmin, ShopManager, Customer |
| GET | `/change-orders/{changeOrderId}` | Flat read of a change order | ShopAdmin, ShopManager, Customer |
| GET | `/change-orders` | Flat list of change orders filtered by project/status | ShopAdmin, ShopManager, Customer |
| GET | `/installations/{installationId}` | Flat read of an installation | ShopAdmin, ShopManager, Installer, Customer |
| GET | `/installations` | Flat list of installations filtered by project | ShopAdmin, ShopManager, Installer, Customer |
| GET | `/punch-items/{punchItemId}` | Flat read of a punch item | ShopAdmin, ShopManager, Installer, Customer |
| GET | `/punch-items` | Flat list of punch items filtered by installation/project/status | ShopAdmin, ShopManager, Installer, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_SHOP_REFERENCE` | 409 |
| `ERR_NO_SPECS` | 409 |
| `ERR_FINISH_REQUIRED` | 409 |
| `ERR_MACHINE_OFFLINE` | 409 |
| `ERR_MACHINE_TIME_CONFLICT` | 409 |
| `ERR_INSTALL_CAPACITY_FULL` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_DEPOSIT_UNPAID` | 409 |
| `ERR_CUSTOMER_CREDIT_HOLD` | 409 |
| `ERR_EMPTY_DRAW` | 409 |
| `ERR_BUILD_INCOMPLETE` | 409 |
| `ERR_CHANGE_OPEN` | 409 |
| `ERR_MAJOR_PUNCH_OPEN` | 409 |
| `ERR_PUNCH_OPEN` | 409 |
| `ERR_NOTHING_TO_REOPEN` | 409 |
| `ERR_BALANCE_OUTSTANDING` | 409 |
| `ERR_DEPOSIT_PAID_NO_CANCEL` | 409 |
| `ERR_RESERVATION_LOCKED` | 409 |
| `ERR_SPECS_LOCKED` | 409 |
| `ERR_PROJECT_NOT_READY` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION_PAGINATION` | 422 |
