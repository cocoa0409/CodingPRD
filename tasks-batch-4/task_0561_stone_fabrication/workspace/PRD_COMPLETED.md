# Stone Fabrication API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Stone Fabrication API, the operational backbone of a countertop shop that turns raw granite and quartz slabs into installed kitchen and bath surfaces. A single job begins as a sales estimate, hardens into a digitally measured template, is priced against a taxed invoice, consumes a physical slab on the cutting floor, and finally arrives at the customer's home as a scheduled install backed by a seal-and-repair warranty. The system exists to keep all of these moving parts honest: slab area is a finite, conserved resource that must be reserved, consumed, and released without leaking; money flows through deposits and balances that must never overpay or underpay; and a project's lifecycle posture gates which shop-floor operations are legal at any moment.

The API is used by four cooperating but distinct crews — sales and finance staff, shop-floor fabricators, field installers, and the shop manager who owns configuration and approvals. Each crew owns a disjoint slice of the workflow, yet every action ripples outward: approving a change order can reopen a finished template, cancel a scheduled cut, and release a reserved slab in a single cascade. The requirements below define those ripples precisely so that inventory, invoices, and schedules stay reconciled at every step. All routes are mounted at the server root.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. The system recognizes exactly four roles: `ShopManager`, `SalesRep`, `Fabricator`, and `Installer`. If `X-User-Role` is missing or names a role outside this set, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

For all four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any resource's `id`, and ownership of a resource is never inferred from it. `SalesRep` owns projects, quotes, payments and refunds, and change-order creation. `Fabricator` owns slab intake, templates, cutouts, template approval, and the full fabrication-order lifecycle. `Installer` owns install jobs and their lifecycle plus warranty claims and their resolution. `ShopManager` owns configuration (bays, crews, and slab intake) and change-order approval, and additionally acts as a hierarchical override that may perform any write operation belonging to the other three roles. All four roles may perform every read (GET) operation.

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

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. Every resource receives an `id`, a unique server-minted UUID with no type prefix, and a `created_at` timestamp — an ISO 8601 UTC value with three fractional digits recording when the resource was first created. Resources that can be modified after creation additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 and increments by one on each mutation. Projects, quotes, templates, slabs, fabrication orders, install jobs, payments, change orders, and warranty claims all carry the full set including `updated_at` and `version`.

Two entities are immutable snapshots and therefore carry only `id` and `created_at`, with no `updated_at` and no `version`: a `Cutout` (a sink, faucet, or cooktop opening recorded against a template) and a `Remnant` (leftover slab area). State the absence explicitly to implementers: these two never expose `updated_at` or `version`. The lightweight configuration resources — a `Bay` (fabrication bay) and a `Crew` (install team) — are likewise created once and never mutated, and therefore carry only `id`, `created_at`, and `name`, with no `updated_at` and no `version`.

Whenever the server recomputes a derived field on an entity — for example refreshing a project's `payment_status`, `balance_due_cents`, or `final_invoice_cents`, or a slab's `remaining_sqft` — that recomputation counts as a mutation of the owning entity: its `updated_at` is refreshed and its `version` increments. Cascades that touch several entities in one operation independently bump each affected entity's `version`.

### 2.5. Monetary Precision and Rounding

All money is held in integer cents. Wherever a monetary figure is produced by multiplying a rate by a quantity, or by applying tax, the result is rounded to a whole number of cents using the round-half-up convention (a fractional cent of exactly one half always rounds up). Slab-area figures — `nominal_sqft`, `reserved_sqft`, `remaining_sqft`, `actual_consumed_sqft`, `estimated_yield_sqft`, and `area_sqft` — are carried to two decimal places, likewise rounded half up. Each calculation below states precisely at which sub-term the rounding is applied, because rounding a sum differs from summing rounded terms; implementers must honor the stated evaluation order exactly.

### 2.6. Project Posture and Cascading Consistency

A project's `status` is a posture that gates which child operations are legal, and the server advances it automatically as work proceeds rather than by direct client request. A project is born in `INTAKE`. It advances to `IN_PRODUCTION`, may be pushed to `ON_HOLD` by a reopening change order, reaches `INSTALLED` when its install completes, and terminates in `CLOSED`. `CLOSED` is terminal.

Several operations mutate more than one entity at once, and every leg of such a cascade must be applied. The most consequential is the reopen cascade driven by applying a change order whose `reopens_template` is true: the project's currently `APPROVED` template is returned to `MEASURED`, that project's linked fabrication order is cancelled if it is still in a non-terminal state (releasing its reserved slab), and the project's `status` becomes `ON_HOLD`. Completing a fabrication order is a two-leg cascade of its own: the reserved slab becomes `CONSUMED` and a remnant is created from the leftover area. Because each leg mutates a distinct entity, each leg independently refreshes that entity's `updated_at` and increments its `version`, per §2.4.

### 2.7. Slab Inventory as a Conserved Quantity

A slab represents a finite sheet of stone, and its area is conserved through the inventory lifecycle. A slab enters as `IN_STOCK` with `reserved_sqft` of 0 and `remaining_sqft` equal to its full `nominal_sqft`. When a fabrication order allocates the slab it becomes `RESERVED`, its `reserved_sqft` is set to the order's computed consumption, and its `remaining_sqft` is reduced accordingly. If the allocating order is cancelled, the slab returns to `IN_STOCK` with `reserved_sqft` reset to 0 and `remaining_sqft` restored to the full `nominal_sqft`. When the allocating order completes, the slab becomes `CONSUMED` (a terminal state) and the unused area is spun off as a remnant. At every reserve, release, or consume transition, `remaining_sqft` is reconciled against `nominal_sqft` and `reserved_sqft` so that reserved-plus-remaining always equals nominal.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the parent `Project`, and both require the caller to supply `expected_project_version` as a non-optional field carrying the client's last observed `version` of that project. The first is quote creation: a request to add a quote to a project must present `expected_project_version` equal to the project's current `version`. If another writer has advanced the project's `version` since the client last read it — for instance by creating a newer quote that already superseded the prior active one — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the stale caller has not observed the supersede that already occurred. The second is change-order creation: a request to add a change order must likewise present `expected_project_version` matching the project's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a change order is priced against the project's current invoice basis and a stale version means the client's view of that basis is out of date. No other endpoint takes a version field.

### 2.9. Validation Ordering and Nested Resource Retrieval

Validation is applied in a fixed precedence so that a mid-flight failure surfaces the highest-priority reason. Authentication is checked first (`ERR_UNAUTHENTICATED`, 401), then authorization (`ERR_UNAUTHORIZED`, 403), then the existence of every resource referenced by the path or body. Existence is validated left-to-right along the URL: when a path names several resources, the first identifier that does not resolve determines the 404 that is returned (for example, a request for the templates of a non-existent project fails with `ERR_PROJECT_NOT_FOUND` before any template is considered). The relevant not-found codes are `ERR_PROJECT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, `ERR_SLAB_NOT_FOUND`, `ERR_BAY_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_FAB_ORDER_NOT_FOUND`, `ERR_INSTALL_JOB_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, and `ERR_WARRANTY_CLAIM_NOT_FOUND`. After existence, the server checks that any requested state transition is legal from the target's current state (`ERR_INVALID_TRANSITION`, 409) — this applies to every state-transition endpoint, including the fabrication, install, warranty, and change-order transitions, template approval, and payment refund. A missing required field, a value of the wrong type, or an invalid enum value is reported as `ERR_VALIDATION` (HTTP 400). Business-specific checks then run in the priority order described in the workflows of §3.

Separately, any mutating operation directed at a `CLOSED` project is rejected with `ERR_PROJECT_CLOSED` (HTTP 409); this guard applies to recording a payment, creating a quote, creating a change order, and recording a template on that project.

### 2.10. The Logical Clock

Time in this system is a server-held logical clock, never the wall clock. Before it is ever set, the clock reads `2026-05-01T00:00:00Z` and it never falls back to real time. A manager may advance it by supplying a `to_iso8601` instant. The clock is what stamps an install's `completed_at` and what the warranty window is measured against, so tests drive it explicitly.

## 3. Business Logic & Workflows

### 3.1. Project Intake and the Sales Quote

A job starts when a sales operator opens a **Project** by supplying the `customer_name`, the install-site `address`, and the `material_grade`, which is one of `STANDARD`, `PREMIUM`, or `EXOTIC`. A new project lands in `INTAKE` posture with `payment_status` of `UNPAID`. Its financial fields — `quoted_total_cents`, `final_invoice_cents`, `amount_paid_cents`, and `balance_due_cents` — are all derived; `amount_paid_cents` starts at 0 and `final_invoice_cents` remains null until an approved template is priced.

Pricing begins with a **Quote**. Creating a quote against a project supersedes whatever quote was previously `ACTIVE`: the prior active quote moves to `SUPERSEDED` and the newest quote becomes the single `ACTIVE`, authoritative one. Beyond the concurrency field `expected_project_version` described in §2.8, a quote captures `est_sqft` (estimated countertop area, which may not be negative), its own `material_grade`, the `edge_profile` (one of `EASED`, `BEVELED`, `BULLNOSE`, or `OGEE`), the finished `edge_linear_ft` (not negative), and three cutout counts — `sink_count`, `faucet_count`, and `cooktop_count`, each a non-negative integer.

The quote's price is built up in integer cents. The material charge is the per-square-foot material rate for the quote's grade multiplied by `est_sqft`, rounded half up — the rate is 4,500 cents for `STANDARD`, 6,500 for `PREMIUM`, and 9,500 for `EXOTIC`. The edge charge is the per-linear-foot edge rate for the chosen profile multiplied by `edge_linear_ft`, rounded half up — the rate is 0 cents for `EASED`, 800 for `BEVELED`, 1,200 for `BULLNOSE`, and 2,000 for `OGEE`. The cutout charge is `sink_count` times 15,000 cents, plus `faucet_count` times 3,500 cents, plus `cooktop_count` times 12,000 cents. The `subtotal_cents` is the sum of the material, edge, and cutout charges. The `quote_total_cents` is then the greater of `subtotal_cents` and a job floor of 80,000 cents, so that no quote is ever priced below the minimum job value. Each quote carries a `status` of `ACTIVE` or `SUPERSEDED`, and every quote records its parent through `project_id`. Whenever a quote is created, the project's `quoted_total_cents` becomes the `quote_total_cents` of its `ACTIVE` quote (0 if there is none) and its `balance_due_cents` is recomputed.

### 3.2. Payments, the Deposit Gate, and the Ledger

Money is recorded as **Payment** entries against a project, each naming its `project_id`, an `amount_cents`, and a `kind` of either `DEPOSIT` or `BALANCE`. A payment is `CAPTURED` when recorded. Before a payment is accepted, several checks run in order. The project must not be `CLOSED`. There must be an `ACTIVE` quote to price against, or the payment is rejected with `ERR_QUOTE_REQUIRED` (409). The `amount_cents` must be strictly greater than zero, or the payment is rejected with `ERR_INVALID_AMOUNT` (422). When the payment's `kind` is `DEPOSIT`, it must bring the cumulative captured total to at least the required deposit — the deposit required is the project's `quoted_total_cents` multiplied by 50 percent, rounded half up — and a deposit that leaves the cumulative captured amount short of that figure is rejected with `ERR_DEPOSIT_TOO_LOW` (422). Finally, no payment may push the total captured above the balance basis, which is the `final_invoice_cents` when one exists and otherwise the `quoted_total_cents`; a payment that would exceed that basis is rejected with `ERR_OVERPAYMENT` (422).

The project ledger is recomputed on every payment and every refund. The `amount_paid_cents` is the sum of `amount_cents` across payments whose `status` is `CAPTURED`; refunded payments are excluded. The `balance_due_cents` is the balance basis (the `final_invoice_cents` if present, else the `quoted_total_cents`) minus `amount_paid_cents`. The `payment_status` is `PAID_IN_FULL` when `amount_paid_cents` is at least the balance basis; otherwise it is `DEPOSIT_PAID` when `amount_paid_cents` is at least the required deposit (`quoted_total_cents` times 50 percent, rounded half up); otherwise it is `UNPAID`.

A captured payment may be reversed. Refunding is permitted only while the payment's `status` is `CAPTURED`; the payment then moves to `REFUNDED` and the project's `amount_paid_cents`, `balance_due_cents`, and `payment_status` are recomputed so that money is conserved. A refund attempted on a payment that is not `CAPTURED` is rejected as an illegal transition (`ERR_INVALID_TRANSITION`).

### 3.3. The Digital Measure: Templates, Cutouts, and the Final Invoice

Where a quote is an estimate, a **Template** is the actual digital measure. Recording a measure against a project creates a template directly in `MEASURED` status and moves any prior non-`SUPERSEDED` template on that project to `SUPERSEDED`. The measure captures `measured_sqft` (the actual measured area, not negative), the measured `edge_profile`, and the measured `edge_linear_ft`, and records its `project_id`. A template's `status` progresses through `DRAFT`, `MEASURED`, `APPROVED`, and `SUPERSEDED`; `DRAFT` is only the nominal pre-persistence state, and `SUPERSEDED` is terminal.

Openings are recorded as **Cutout** children of a template. Each cutout names its `template_id` and a `cutout_type` of `SINK`, `FAUCET`, or `COOKTOP`, and snapshots a `charge_cents` at creation equal to the per-cutout charge for that type (15,000 cents for `SINK`, 3,500 for `FAUCET`, 12,000 for `COOKTOP`).

Approving a measured template requires that its `measured_sqft` be greater than zero; approval of an empty measure is an illegal transition. On approval the template becomes `APPROVED` and the project's `final_invoice_cents` is priced, after which `balance_due_cents` is recomputed. The final invoice is assembled as an ordered list of base line items, each taxed individually before summing. The first line is the material base: the per-square-foot material rate for the project's `material_grade` multiplied by the template's `measured_sqft`. The second line is the edge base: the per-linear-foot edge rate for the template's `edge_profile` multiplied by its `edge_linear_ft`. Following those come one line per cutout on the approved template — the per-type cutout charge — taken in ascending `created_at` order, and then one line per applied change order carrying that order's signed delta, also in ascending `created_at` order. For each line in that order, multiply the base by one plus the tax rate of 0.0875 and round half up to whole cents; the `final_invoice_cents` is the sum of those per-line taxed amounts. The rounding is applied to each line before summation, and the line order is fixed as material, edge, cutouts by creation time, then change orders by creation time.

### 3.4. Slab Inventory and Remnants

Physical stone enters as a **Slab**, taken in with a `slab_label` (its warehouse bin id), a `material_grade`, and a `nominal_sqft` that must be strictly positive. A fresh slab is `IN_STOCK` with `reserved_sqft` of 0 and `remaining_sqft` equal to `nominal_sqft`, and its `status` moves through `IN_STOCK`, `RESERVED`, and `CONSUMED` as described in §2.7. For planning purposes a slab has an estimated usable yield: its `nominal_sqft` multiplied by the complement of a 15 percent standard waste factor — that is, `nominal_sqft` times 0.85 — rounded half up to two decimal places, surfaced as `estimated_yield_sqft`. This slab-intrinsic estimate is distinct from the job-specific `actual_consumed_sqft` computed when a fabrication order allocates the slab (see §3.5); the two are expected to diverge.

When a slab is finally consumed, the leftover becomes a **Remnant** child of the slab, recording its `slab_id` and an `area_sqft` equal to the slab's `nominal_sqft` minus the consuming order's `actual_consumed_sqft`. A remnant's `status` is `AVAILABLE`. Remnants can be listed back from their originating slab.

### 3.5. Fabrication Orders and the Cutting Floor

Bays and crews are lightweight configuration resources created by the manager, each identified simply by a `name`: a fabrication bay is a physical cutting station, and a crew is an install team. A **FabricationOrder** commits a slab, a bay, and a schedule to producing a project's pieces. Its creation payload references the `project_id`, the `template_id`, the `slab_id`, and the `bay_id`, gives a `scheduled_start` and `scheduled_end` (ISO 8601 UTC instants), and supplies `pieces` — a non-empty array of cut pieces, each an object with a `label` and a positive `sqft`. The order's `actual_consumed_sqft` is computed as the sum of every piece's `sqft` plus a kerf allowance of 0.10 square feet per piece (that is, 0.10 multiplied by the number of pieces), rounded half up to two decimal places.

Creating a fabrication order runs a sequence of guards in priority order. The referenced template must be `APPROVED`, or the create is rejected with `ERR_TEMPLATE_NOT_APPROVED` (409). The project's `payment_status` must be `DEPOSIT_PAID` or `PAID_IN_FULL`, or it is rejected with `ERR_DEPOSIT_NOT_PAID` (409). The `pieces` array must contain at least one piece, or it is rejected with `ERR_NO_PIECES` (422). The referenced slab must be `IN_STOCK`, or it is rejected with `ERR_SLAB_NOT_AVAILABLE` (409). The `scheduled_end` must be strictly after the `scheduled_start`, or it is rejected with `ERR_INVALID_INTERVAL` (422). Finally, the bay must be free for the requested window: the interval is treated as half-open, so the create is rejected with `ERR_BAY_UNAVAILABLE` (409) if any non-cancelled fabrication order on the same bay overlaps such that this order's start is before that order's end and that order's start is before this order's end — abutting intervals where one ends exactly when the other starts are allowed.

On successful creation the order's `actual_consumed_sqft` is computed, the referenced slab moves from `IN_STOCK` to `RESERVED` with its `reserved_sqft` set to that consumption and `remaining_sqft` recomputed, the project advances from `INTAKE` (or from `ON_HOLD` after a reopen) to `IN_PRODUCTION`, and the order lands in `SCHEDULED`. The first fabrication order that carries a project into `IN_PRODUCTION` from `INTAKE` additionally requires that the project already hold an `APPROVED` template and that its `payment_status` be `DEPOSIT_PAID` or `PAID_IN_FULL`; a fabrication order created after a reopen carries the project from `ON_HOLD` back to `IN_PRODUCTION` and requires only the `APPROVED` template.

The order's `status` walks through `SCHEDULED`, `CUTTING`, `RECUTTING`, `QC_PASSED`, `COMPLETE`, and `CANCELLED`. Beginning the cut advances `SCHEDULED` to `CUTTING`. A quality check carries a `result` of `PASS`, moving `CUTTING` to `QC_PASSED`, or `FAIL`, moving `CUTTING` to `RECUTTING`; from `RECUTTING`, beginning the cut again returns the order to `CUTTING`, forming the recut loop. Completing the order advances `QC_PASSED` to `COMPLETE`, at which point the reserved slab is consumed (moving it to `CONSUMED`) and a remnant is created from the leftover area, as in §2.6 and §3.4. Cancelling a fabrication order is permitted from any non-terminal state — `SCHEDULED`, `CUTTING`, `RECUTTING`, or `QC_PASSED` — and moves it to `CANCELLED` while releasing its slab back to `IN_STOCK` with `reserved_sqft` reset to 0 and `remaining_sqft` restored to `nominal_sqft`. `COMPLETE` and `CANCELLED` are terminal, and any transition attempted from a state that does not permit it is rejected as `ERR_INVALID_TRANSITION`.

### 3.6. Installation Scheduling

An **InstallJob** schedules a crew to fit a completed order at the customer's home. Its payload names the `project_id`, the `fabrication_order_id`, the `crew_id`, and an `install_date` given as a calendar date. The referenced fabrication order must be `COMPLETE`, or the create is rejected with `ERR_FAB_NOT_COMPLETE` (409). The crew must also be free around that date: because a crew needs a one-day travel buffer, two install jobs on the same crew must have install dates more than one day apart, so a create whose `install_date` falls within one day of another job on the same crew — that is, the absolute difference in days is one or less — is rejected with `ERR_CREW_UNAVAILABLE` (409).

An install job's `status` runs `SCHEDULED`, `IN_PROGRESS`, `DONE`. Starting the install advances `SCHEDULED` to `IN_PROGRESS`. Completing it advances `IN_PROGRESS` to `DONE`, stamps `completed_at` with the current logical-clock time, and advances the project: a project in `IN_PRODUCTION` becomes `INSTALLED`, or moves straight to `CLOSED` if its `payment_status` is already `PAID_IN_FULL` at that moment. If the project is not paid in full when the install reaches `DONE`, it stays `INSTALLED`, and a later `BALANCE` payment does not by itself close the project. `DONE` is terminal for the install job.

### 3.7. Change Orders and the Reopen Cascade

A **ChangeOrder** captures a mid-job scope change against a project. Its creation payload carries the concurrency field `expected_project_version` (see §2.8), a `description` of what is changing, a signed `delta_cents` to be added to the final invoice when the order is applied, and an optional `reopens_template` flag that defaults to true. A new change order records its `project_id` and lands in `DRAFT`. Creating a change order also counts as a mutation of the parent project even though no invoice line is applied yet: the project's `updated_at` is refreshed and its `version` increments by one, so any subsequent quote or change-order create must present the newly advanced `expected_project_version` or it will be rejected with `ERR_STALE_VERSION`.

Approving a change order applies it, and is permitted only while it is `DRAFT` and the project is not `CLOSED`; an approval attempted from any other change-order state is rejected as `ERR_INVALID_TRANSITION`, and one attempted on a closed project is rejected as `ERR_PROJECT_CLOSED`. On approval the order moves to `APPLIED`, the project's `final_invoice_cents` is recomputed to include the new delta line (taxed per line as in §3.3) and `balance_due_cents` is refreshed. When the applied order's `reopens_template` is true, the full reopen cascade fires: the project's `APPROVED` template returns to `MEASURED`, the project's linked fabrication order is cancelled if it is still in `SCHEDULED`, `CUTTING`, `RECUTTING`, or `QC_PASSED` (which releases its reserved slab back to `IN_STOCK` per §3.5), and the project's `status` becomes `ON_HOLD`. A reopened template can be re-approved, re-pricing the invoice, and a fresh fabrication order can then carry the project from `ON_HOLD` back into `IN_PRODUCTION`.

### 3.8. Warranty Claims and Their Resolution

After an install reaches `DONE`, the customer is covered by a warranty. A **WarrantyClaim** is filed against an install job, referencing its `install_job_id` and carrying a `claim_type` of `SEAL`, `CHIP`, or `CRACK` together with a free-text `description`. A claim may only be filed against a `DONE` install job and only within the warranty window: the claim is accepted only while the current logical-clock time is at or before the job's `completed_at` plus 365 days; a claim filed after that point is rejected with `ERR_WARRANTY_EXPIRED` (422). A claim filed against an install job that is not `DONE` (and therefore has no anchored `completed_at`) is rejected with that same `ERR_WARRANTY_EXPIRED` (422), rather than with a transition error. A new claim lands in `SUBMITTED`.

Resolving a claim carries a `resolution` and branches. A `resolution` of `SEAL_REPAIR` moves the claim to `RESOLVED`, records `resolution` as `SEAL_REPAIR`, and has no financial or install side effects — it is a simple seal touch-up. A `resolution` of `REPLACEMENT` also moves the claim to `RESOLVED` and records `resolution` as `REPLACEMENT`, but it reopens production by returning the project to `IN_PRODUCTION` so the piece can be refabricated. A `resolution` of `REJECT` moves the claim to `REJECTED`, records `resolution` as `REJECTED`, and likewise carries no financial or install effect. The `status` of a claim is `SUBMITTED`, `RESOLVED`, or `REJECTED`, with `RESOLVED` and `REJECTED` both terminal; a resolve attempted on a claim that is not `SUBMITTED` is rejected as `ERR_INVALID_TRANSITION`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state-transition actions and refunds — return `200 OK`. The clock control endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bays` | Create a fabrication bay | ShopManager |
| POST | `/crews` | Create an install crew | ShopManager |
| POST | `/slabs` | Intake a physical slab into inventory | ShopManager, Fabricator |
| GET | `/slabs/{id}` | Read a slab | ShopManager, SalesRep, Fabricator, Installer |
| GET | `/slabs/{id}/remnants` | List remnants cut from a slab | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/projects` | Create a project | SalesRep, ShopManager |
| GET | `/projects/{id}` | Read a project | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/projects/{id}/quotes` | Create a quote (supersedes prior active; OCC on project) | SalesRep, ShopManager |
| GET | `/projects/{id}/quotes` | List quotes for a project | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/projects/{id}/payments` | Record a captured payment | SalesRep, ShopManager |
| POST | `/payments/{id}/refund` | Refund a captured payment | SalesRep, ShopManager |
| GET | `/projects/{id}/payments` | List payments for a project | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/projects/{id}/change-orders` | Create a change order (OCC on project) | SalesRep, ShopManager |
| POST | `/change-orders/{id}/approve` | Approve and apply a change order | ShopManager |
| GET | `/projects/{id}/change-orders` | List change orders for a project | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/projects/{id}/templates` | Record a digital measure | Fabricator, ShopManager |
| GET | `/projects/{id}/templates` | List templates for a project | ShopManager, SalesRep, Fabricator, Installer |
| GET | `/templates/{id}` | Read a template | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/templates/{id}/cutouts` | Add a cutout to a template | Fabricator, ShopManager |
| GET | `/templates/{id}/cutouts` | List cutouts of a template | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/templates/{id}/approve` | Approve a measured template; price the final invoice | Fabricator, ShopManager |
| POST | `/fabrication-orders` | Create a fabrication order; reserve slab and bay | Fabricator, ShopManager |
| GET | `/fabrication-orders/{id}` | Read a fabrication order | ShopManager, SalesRep, Fabricator, Installer |
| GET | `/fabrication-orders` | List/filter fabrication orders (optional query filters: `project_id`, `template_id`, `slab_id`, `bay_id`) | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/fabrication-orders/{id}/start-cut` | Begin cutting | Fabricator, ShopManager |
| POST | `/fabrication-orders/{id}/qc` | Record a QC result | Fabricator, ShopManager |
| POST | `/fabrication-orders/{id}/complete` | Complete fabrication; consume slab; create remnant | Fabricator, ShopManager |
| POST | `/fabrication-orders/{id}/cancel` | Cancel an order; release slab | Fabricator, ShopManager |
| POST | `/install-jobs` | Schedule an install job | Installer, ShopManager |
| GET | `/install-jobs/{id}` | Read an install job | ShopManager, SalesRep, Fabricator, Installer |
| GET | `/install-jobs` | List/filter install jobs (optional query filters: `project_id`, `crew_id`, `fabrication_order_id`) | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/install-jobs/{id}/start` | Start an install | Installer, ShopManager |
| POST | `/install-jobs/{id}/complete` | Complete an install; anchor warranty; advance project | Installer, ShopManager |
| POST | `/install-jobs/{id}/warranty-claims` | File a warranty claim | Installer, ShopManager |
| GET | `/install-jobs/{id}/warranty-claims` | List warranty claims for an install job | ShopManager, SalesRep, Fabricator, Installer |
| POST | `/warranty-claims/{id}/resolve` | Resolve a warranty claim | Installer, ShopManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_TEMPLATE_NOT_FOUND` | 404 |
| `ERR_SLAB_NOT_FOUND` | 404 |
| `ERR_BAY_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_FAB_ORDER_NOT_FOUND` | 404 |
| `ERR_INSTALL_JOB_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_TRANSITION` | 409 |
| `ERR_PROJECT_CLOSED` | 409 |
| `ERR_TEMPLATE_NOT_APPROVED` | 409 |
| `ERR_FAB_NOT_COMPLETE` | 409 |
| `ERR_DEPOSIT_NOT_PAID` | 409 |
| `ERR_NO_PIECES` | 422 |
| `ERR_SLAB_NOT_AVAILABLE` | 409 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_BAY_UNAVAILABLE` | 409 |
| `ERR_CREW_UNAVAILABLE` | 409 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_DEPOSIT_TOO_LOW` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_QUOTE_REQUIRED` | 409 |
| `ERR_STALE_VERSION` | 412 |
