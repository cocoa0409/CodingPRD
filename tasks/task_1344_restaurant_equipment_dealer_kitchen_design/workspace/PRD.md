# Restaurant Equipment Dealer API — Product Requirements Document

## 1. Introduction

A restaurant equipment dealer operating in the TriMark mold does far more than sell boxes off a catalog page. Each engagement begins with a kitchen design — a CAD-backed layout annotated with an equipment schedule — and ends months later when the last warranty registration is filed, the punch list is closed, and the dealer releases the retainage it withheld against final acceptance. Between those two bookends live freight and installation pricing, long-lead custom fabrication tracked against shop drawings, health-department and fire-marshal permit packages, rigging crews threading a 2,000-pound range through a second-story doorway, factory-authorized startup technicians running operator demos, and service-agency handoffs that determine who answers the phone when the fryer dies on a Friday night.

This document specifies the REST API that backs that dealer's design-build workflow. It defines the entities (customers, projects, kitchen layouts, equipment items, fabrication orders, quotes, permit filings, delivery jobs, startup sessions, service agencies, service assignments, and punch-list items), the state machines each one follows, the pricing engine that turns an equipment schedule into a freight-inclusive grand total, and the optimistic-concurrency and credit-exposure guardrails that keep two writers from corrupting the same deal. The intended audience is the engineering team implementing the service; every rule stated here is authoritative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. When either header is missing or malformed the request fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the supplied role is not authorized for the attempted operation the request fails with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Request bodies that fail general shape or type validation — a missing required key, a string where an integer is expected — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The platform recognizes ten roles, spelled exactly as follows: `PlatformAdmin`, `ProjectManager`, `KitchenDesigner`, `SalesRep`, `Customer`, `PermitCoordinator`, `FabricationLead`, `LogisticsCoordinator`, `StartupTechnician`, and `ServiceManager`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. For every other role — `PlatformAdmin`, `ProjectManager`, `KitchenDesigner`, `SalesRep`, `PermitCoordinator`, `FabricationLead`, `LogisticsCoordinator`, `StartupTechnician`, and `ServiceManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as an actor stamp on the resource being mutated) but does not compare it to any entity's `id`.

`PlatformAdmin` is the back-office operator: it alone creates and suspends customers and drives the test-only logical clock, and it shares read access across all resources. `ProjectManager` is the dealer-side PM and owns project creation, project cancellation, punch-list close, project completion, layout approval and return-for-revision, shop-drawing approval, and punch-item verification and voiding; it shares punch-item creation with `Customer` and reads broadly. `KitchenDesigner` authors layouts and submits them for review, and shares equipment-item creation with `SalesRep`. `SalesRep` owns quote creation and presentation. `Customer` accepts or rejects quotes and raises punch-list items. `PermitCoordinator` owns the permit-filing lifecycle end to end. `FabricationLead` starts production on approved fabrication orders and completes them. `LogisticsCoordinator` plans, dispatches, completes, and cancels delivery jobs. `StartupTechnician` schedules, completes, and voids startup sessions. `ServiceManager` registers service agencies (an operation shared with `PlatformAdmin`) and closes or transfers service assignments.

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

### 2.3. Pagination

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Results are sorted by `created_at` ascending unless a subsection states otherwise.

### 2.4. Common Resource Properties

Every entity in this specification carries a common set of properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is stamped at creation and `updated_at` refreshes on every mutation. `version` is an integer starting at its initial value on creation and incrementing by exactly 1 on every mutation of the owning resource; it is the backbone of the optimistic-concurrency rules in §2.6. Because all entities here follow this convention, none is exempt from `updated_at` or `version`.

Several properties are server-computed and read-only — clients never supply them in a request body. On `Customer`, `outstanding_exposure_cents` starts at 0 and `status` starts as `ACTIVE`. On `Project`, `quote_baseline_cents` and `retainage_held_cents` start at 0, `warranty_registered_count` starts at 0, and `status` starts as `DESIGN`. On `KitchenLayout`, `revision_no` starts at 1 and `status` starts as `DRAFT`. On `EquipmentItem`, `warranty_status` starts as `UNREGISTERED` and `status` starts as `SCHEDULED`. On `FabricationOrder`, `final_fab_cost_cents` is null until reconciliation at completion, and `status` starts as `PENDING_SHOP_DRAWING`. On `Quote`, all five monetary fields are computed, `variant` starts as `PROVISIONAL`, `revision_no` starts at 1, and `status` starts as `DRAFT`. On `PermitFiling`, `review_cycle_no` starts at 0 and `status` starts as `DRAFT`; `submitted_at` is stamped only when the filing first enters `SUBMITTED`. On `DeliveryJob`, `status` starts as `PLANNED`. On `StartupSession`, `warranty_registered` starts false and `status` starts as `SCHEDULED`. On `ServiceAgency`, `open_assignment_count` starts at 0 and `status` starts as `ACTIVE`. On `ServiceAssignment`, `opened_at` is stamped at creation and `status` starts as `OPEN`. On `PunchListItem`, `status` starts as `OPEN`.

### 2.5. Money, Precision, and the Quote's Two Variants

All monetary values are integer cents. Wherever a calculation in this document produces a non-integer intermediate, the result is rounded half-up to whole cents (zero decimal places) at the point the section specifies — some formulas round once at the end, others round per line before summing, and the distinction is load-bearing.

Every quote exists in one of two pricing **variants**, recorded on the quote as `variant`. A quote in the `PROVISIONAL` variant is priced off the layout snapshot as it existed when the quote was created — the per-line equipment prices, item kinds, and counts are read once and frozen into the quote's monetary fields at creation and again at presentation without re-reading current item prices. A quote that flips to the `FINAL` variant at acceptance is fully recomputed against the current `unit_price_cents`, `item_kind`, and item composition at the moment the acceptance call runs. A quote's `revision_no` is a monotonic counter within its project; each newly created quote supersedes prior revisions by carrying the next number, and acceptance of one quote supersedes its open siblings (see §3.3).

### 2.6. Optimistic Concurrency Control on Project-Mutating Writes

Two write operations declare an explicit optimistic-concurrency field, `expected_project_version`, as a non-optional request-body input: the customer-facing quote-acceptance operation and the project-manager-facing punch-list closure. In each case the caller supplies the `version` of the `Project` it last observed. If the supplied value does not equal the project's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) and no state changes are applied. On acceptance this guard captures the case where another writer has already accepted a sibling quote — which legitimately supersedes the current quote under the quote state machine — leaving the current writer's view of the project stale. On punch-list closure the guard protects the retainage release, which mutates both `retainage_held_cents` and the customer's exposure ledger; a stale version would mask those deltas. Endpoints not named here do not take a version field.

### 2.7. Nested Resource Resolution

Several resources are addressed through their parent in the URL — a layout beneath its project, an equipment item beneath its layout and project, and so on. The path-template variables used throughout the API are `id` for the parent project, plus `customerId`, `layoutId`, `itemId`, `quoteId`, `fabId`, `filingId`, `jobId`, `sessionId`, `agencyId`, and `assignmentId` for the resource they name. Path identifiers are validated left to right: the project segment is resolved first, then the layout segment within that project, then the item segment within that layout. A failure at any segment returns the not-found error for that segment's resource type (`ERR_PROJECT_NOT_FOUND`, `ERR_LAYOUT_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, or `ERR_CUSTOMER_NOT_FOUND`), each with HTTP 404. In addition to the nested forms, every child resource is also reachable through a top-level path keyed by its own `id`, with list forms supporting foreign-key filters (`project_id`, `layout_id`, `equipment_item_id`, `agency_id`) so that cross-project reachability never requires guessing a parent.

### 2.8. Validation Order Across a Request

When multiple checks guard the same endpoint, the server evaluates them in a fixed priority order and surfaces the first failure. Authentication context is checked first (missing or malformed headers, then role authorization), then path-existence resolution left to right, then state-machine legality for the target resource, then permit and health-compliance rules, then structural business constraints, then referential-integrity rules, then fiscal guardrails, and finally the optimistic-concurrency version check. The practical consequence: a caller presenting a quote against a non-existent layout sees `ERR_LAYOUT_NOT_FOUND` before any state error; a caller accepting a quote with a stale project version and an over-limit customer sees the credit failure (`ERR_CREDIT_LIMIT_EXCEEDED`) before the version failure (`ERR_STALE_PROJECT_VERSION`), because fiscal checks outrank the concurrency check in the fixed order.

### 2.9. The Logical Clock

The server maintains a logical clock used for every `created_at`, `updated_at`, and `submitted_at` stamp. Before any test-driving call, the clock reads 2026-08-01T00:00:00Z. A `PlatformAdmin`-only capability advances the clock to a supplied instant via `to_iso8601`; once advanced, the clock never falls back to wall-clock time, and all subsequent stamps use the new logical time. Fabrication schedule overruns are measured against this same clock (see §3.4).

## 3. Business Logic & Workflows

### 3.1. Standing Up the Account and the Project

An engagement begins when a `PlatformAdmin` registers the buying organization as a `Customer`, supplying the customer's `legal_name`, a primary `contact_email`, and an approved `credit_limit_cents` that must be zero or greater. The new customer starts with `status` of `ACTIVE`, an `outstanding_exposure_cents` of 0, and the usual common fields. Should the account deteriorate, the same admin can suspend it; suspension flips `status` to `SUSPENDED` and, as described in §3.3, blocks any further quote acceptances with `ERR_CUSTOMER_SUSPENDED` until lifted. Listing customers supports filtering by `status` in addition to the standard pagination parameters.

With a customer on file, a `ProjectManager` opens a `Project` by supplying the owning `customer_id`, a human-readable `project_name` such as "Downtown Bistro Build-Out", the `site_address`, and the `health_jurisdiction` — one of exactly `CITY_HEALTH`, `COUNTY_HEALTH`, or `STATE_HEALTH` — which later drives both the installation uplift in §3.3 and the service-agency eligibility filter in §3.6. The PM may also set `retainage_pct`, the fraction of the eventual contract value withheld until punch-list closure; when omitted it defaults to 0.10, and in all cases it must be greater than 0 and at most 0.20. A new project starts in `DESIGN` with `quote_baseline_cents` 0, `retainage_held_cents` 0, and `warranty_registered_count` 0. Project listings accept `customer_id` and `status` filters.

### 3.2. Designing the Kitchen: Layouts and the Equipment Schedule

Design work belongs to the `KitchenDesigner`, who creates a `KitchenLayout` under the project with a `layout_label` (for example "Rev-A"), a `drawing_ref` pointing at the CAD drawing, and an optional `hood_required` flag declaring whether the design calls for a Type-I hood; the flag defaults to false. Each layout is born in `DRAFT` with `revision_no` 1.

The designer — or a `SalesRep` helping spec the job — then populates the layout with equipment. Adding an `EquipmentItem` requires the manufacturer `model_no`, an `item_kind` of exactly `STOCK` or `CUSTOM_FABRICATION`, a `quantity` of at least 1, a per-unit `unit_price_cents` of at least 0, and the manufacturer's `lead_time_days` of at least 0. The `requires_hood` flag (default false) records that health code demands this item sit under a hood. Every item starts in `SCHEDULED` with `warranty_status` `UNREGISTERED`, and each row carries both its parent `layout_id` and a denormalized `project_id` so the project-wide filtered list can answer "all fryers across all revisions" without walking layouts. Item listings support `status` and `item_kind` filters on the nested form, and `layout_id` plus `status` on the project-wide form.

When the designer believes a draft is ready, submitting it moves the layout from `DRAFT` to `SUBMITTED`. Three checks guard the transition. The layout must currently be `DRAFT`, or the call fails with `ERR_LAYOUT_NOT_DRAFT`. It must reference at least one equipment item, or the call fails with `ERR_LAYOUT_EMPTY`. And if `hood_required` is true, at least one item on the layout must carry `requires_hood` true — a hood design with nothing under it is a spec error, rejected with `ERR_HOOD_SPEC_INCONSISTENT`. State legality is evaluated before the structural checks, per the fixed order in §2.8.

Review is the `ProjectManager`'s call. Approving a `SUBMITTED` layout moves it to `APPROVED` and immediately supersedes every sibling layout on the same project that is currently `SUBMITTED` or `APPROVED` — at most one layout is ever live for pricing. If the layout is not in `SUBMITTED`, the approval fails with `ERR_LAYOUT_NOT_SUBMITTED`. Alternatively the PM can return a `SUBMITTED` layout for revision: it drops back to `DRAFT`, its `revision_no` increments by 1, and the design loop repeats — the same not-submitted guard (`ERR_LAYOUT_NOT_SUBMITTED`) applies. Layout listings accept a `status` filter, and the top-level layout list additionally accepts `project_id`.

### 3.3. Pricing the Job: Quotes, the Four-Charge Engine, and Acceptance

Quoting is how a layout becomes a contract. A `SalesRep` creates a `Quote` against a specific layout revision by passing `layout_id`; the referenced layout must be `APPROVED` or creation fails with `ERR_LAYOUT_NOT_APPROVED`. The quote is born in `DRAFT` with `variant` `PROVISIONAL`, the next `revision_no` within the project, and all five monetary fields computed from the pricing engine below.

**Equipment subtotal.** `equipment_subtotal_cents` sums every equipment item on the referenced layout whose status is not `CANCELLED`, where each line contributes its `quantity` multiplied by its `unit_price_cents`, with that per-line product first rounded half-up to whole cents and only then summed. Rounding per line before summing — rather than summing raw products and rounding once — is pinned, because the two orders diverge whenever a per-unit product is non-integral across lines.

**Freight.** `freight_cents` is a marginal tier calculation on the equipment subtotal, followed by a flat fabrication surcharge. The tiers are: subtotals up to and including $50,000 (5,000,000 cents) are charged entirely at 6 percent; the portion of a subtotal above $50,000 and up to and including $250,000 (25,000,000 cents) is charged at 4.5 percent on top of the full first-tier charge; and any portion above $250,000 is charged at 3 percent on top of both lower-tier charges. Tier bounds are inclusive at the bottom and exclusive at the top of each band — a subtotal of exactly $50,000 is charged entirely at the 6-percent rate. The marginal sum is rounded half-up once to whole cents. After rounding, if any non-cancelled item on the layout has `item_kind` `CUSTOM_FABRICATION`, a flat $1,500 (150,000 cents) custom-fabrication surcharge is added; otherwise the freight equals the rounded tier amount.

**Installation.** `installation_cents` starts from a base of $2,500 (250,000 cents) per quote, plus $450 (45,000 cents) per unit of total equipment `quantity` across non-cancelled items, plus a $1,200 (120,000 cents) premium for each non-cancelled item whose `requires_hood` is true. When — and only when — the project's `health_jurisdiction` is exactly `COUNTY_HEALTH`, the summed base is multiplied by 1.10 (a 10 percent county uplift) and the result rounded half-up once to whole cents; `CITY_HEALTH` and `STATE_HEALTH` projects pay the un-uplifted base.

**Startup and demo.** `startup_cents` is a flat $1,800 (180,000 cents) per project plus $300 (30,000 cents) per non-cancelled equipment item on the layout; both factors are integers, so no rounding arises. The `grand_total_cents` is then the sum of `equipment_subtotal_cents`, `freight_cents`, `installation_cents`, and `startup_cents`.

Presenting the quote to the customer is the `SalesRep`'s second act, and it is where the project first moves. Three preconditions apply, in the fixed validation order: the quote must be in `DRAFT` (`ERR_QUOTE_NOT_DRAFT`); the referenced layout must be `APPROVED` (`ERR_LAYOUT_NOT_APPROVED`); and the project must still be in `DESIGN` (`ERR_PROJECT_NOT_IN_DESIGN`). On success the quote's pricing fields are recomputed under the `PROVISIONAL` variant (still reading the creation-time layout snapshot, not current item prices), the quote moves `DRAFT` → `PRESENTED`, and the project moves `DESIGN` → `QUOTED`.

Acceptance belongs to the `Customer` and is the most heavily guarded transition in the system. The request body must carry `expected_project_version`, and per §2.6 a mismatch against the project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) — the classic case being a second writer who accepted a sibling quote in the meantime. Before the version check is even reached, the quote must be in `PRESENTED` (`ERR_QUOTE_NOT_PRESENTED`), the project must be in `QUOTED` (`ERR_PROJECT_NOT_QUOTED`), the customer's `status` must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`, HTTP 402), and the credit guard must pass: the customer's current `outstanding_exposure_cents` plus this quote's `grand_total_cents` must be less than or equal to `credit_limit_cents`, otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Fiscal checks outrank the version check, so an over-limit acceptance with a stale version surfaces the credit error.

A successful acceptance fires a broad cascade. The quote's `variant` flips from `PROVISIONAL` to `FINAL` and every monetary field is recomputed against current item state at that instant. The quote becomes `ACCEPTED`; every sibling quote on the project in `DRAFT` or `PRESENTED` becomes `SUPERSEDED`. The project freezes `quote_baseline_cents` to the final `grand_total_cents`, computes `retainage_held_cents` as the baseline multiplied by `retainage_pct` rounded half-up to whole cents, and moves from `QUOTED` to `CONTRACTED`, incrementing the project's `version` by 1. Every equipment item on the referenced layout moves from `SCHEDULED` to `ORDERED`, and for each item whose `item_kind` is `CUSTOM_FABRICATION` the system spawns a `FabricationOrder` in `PENDING_SHOP_DRAWING` referencing that item. The customer's `outstanding_exposure_cents` reflects the newly accepted net balance plus the withheld retainage across all of that customer's non-terminal projects.

A customer who dislikes the numbers can reject instead: rejection moves a quote in `DRAFT` or `PRESENTED` to `REJECTED`; any other starting state fails with `ERR_QUOTE_NOT_OPEN`. Quote listings support `status` and `variant` filters, and the top-level quote list additionally accepts `project_id` and `layout_id`.

### 3.4. Building the Custom Pieces: Fabrication Orders

Custom work is where schedules slip, so the system tracks it explicitly. A fabrication order is never created directly — it appears, in `PENDING_SHOP_DRAWING`, as a side effect of quote acceptance for each `CUSTOM_FABRICATION` item. The order records the `equipment_item_id` it builds, a `shop_drawing_ref` supplied through the approval flow, and the `quoted_fab_cost_cents` of at least 0 captured at intake; `final_fab_cost_cents` stays null until completion.

The `ProjectManager` approves the shop drawing, moving the order from `PENDING_SHOP_DRAWING` to `SHOP_DRAWING_APPROVED`. The order must actually be in `PENDING_SHOP_DRAWING` (`ERR_FAB_NOT_PENDING_DRAWING`), and `shop_drawing_ref` must be non-empty (`ERR_SHOP_DRAWING_MISSING`). Production is then the `FabricationLead`'s responsibility: starting production requires the order to be in `SHOP_DRAWING_APPROVED` (`ERR_FAB_NOT_APPROVED`) and the project to be in `CONTRACTED` or `FABRICATION` (`ERR_PROJECT_NOT_READY_FOR_FABRICATION`). When the first order on a `CONTRACTED` project enters `IN_PRODUCTION`, the project itself cascades upward from `CONTRACTED` to `FABRICATION`.

Completing fabrication moves the order from `IN_PRODUCTION` to `FAB_COMPLETE` (a non-`IN_PRODUCTION` start state fails with `ERR_FAB_NOT_IN_PRODUCTION`) and reconciles cost. The reconciliation compares the quoted cost `quoted_fab_cost_cents` against schedule performance: the allowance is the linked item's `lead_time_days` plus a 30-day schedule allowance, measured against the actual calendar days elapsed between the shop-drawing approval and fabrication completion on the logical clock. Every day of overrun beyond that allowance accrues a penalty of 4 percent of the quoted cost; the accrued penalty is capped at 40 percent of the quoted cost, with the cap applied after the per-day accrual. The final fabrication cost is the quoted cost plus the capped penalty, rounded half-up once at the very end to whole cents, and stored in `final_fab_cost_cents`. Completing the order also moves the linked equipment item from `ORDERED` to `RECEIVED`. A project-level cancellation cancels any fabrication order still in `PENDING_SHOP_DRAWING`, `SHOP_DRAWING_APPROVED`, or `IN_PRODUCTION`. Fabrication-order listings accept `status` and `equipment_item_id` filters; the top-level list adds `project_id`.

### 3.5. Permits: Health, Building, and Fire Filings

No kitchen opens without the authorities' signatures. A `PermitCoordinator` creates a `PermitFiling` under the project by naming the `layout_id` being submitted and the filing `authority` — exactly one of `HEALTH_DEPT`, `BUILDING_DEPT`, or `FIRE_MARSHAL`. The filing starts in `DRAFT` with `review_cycle_no` 0.

Submitting a filing moves it from `DRAFT` to `SUBMITTED` and requires the filing to be in `DRAFT` (`ERR_FILING_NOT_DRAFT`) and the referenced layout to be `APPROVED` (`ERR_LAYOUT_NOT_APPROVED`). Submission increments `review_cycle_no` by 1 and stamps `submitted_at` from the logical clock. The authority's decision is recorded through a single operation taking a `decision` field: recording `APPROVED` moves a `SUBMITTED` filing to `APPROVED`, recording `REJECTED` moves it to `REJECTED`, and either call against a filing not in `SUBMITTED` fails with `ERR_FILING_NOT_SUBMITTED`. `APPROVED` is terminal.

Rejection is not the end. A `REJECTED` filing can be resubmitted, cycling back to `SUBMITTED`, provided the filing is in `REJECTED` (`ERR_FILING_NOT_REJECTED`) and the review cycle has not been exhausted: resubmission is allowed only while `review_cycle_no` is below the maximum of 3 review cycles, and a filing that has already consumed 3 cycles fails with `ERR_REVIEW_CYCLE_LIMIT_REACHED`. Each successful resubmission again increments `review_cycle_no` and restamps `submitted_at`. Filing listings accept `status` and `authority` filters; the top-level list adds `project_id` and `layout_id`. The health-department filing in particular gates project closeout, as §3.8 describes.

### 3.6. Wheels on the Ground: Delivery and Rigging

Logistics turns fabricated and stocked goods into an installed kitchen. A `LogisticsCoordinator` plans a `DeliveryJob` by supplying a delivery window — `scheduled_start` and `scheduled_end`, both ISO 8601 UTC, with the end strictly after the start or creation fails with `ERR_INVALID_JOB_WINDOW` — plus an optional `rigging_required` flag (default false) and, when rigging is required, a `rigging_crew_size` of at least 2; the crew size is ignored when rigging is not required. A new job is `PLANNED`.

Dispatching a job (the `PLANNED` → `DISPATCHED` move) carries three guards. The job must be `PLANNED` (`ERR_JOB_NOT_PLANNED`). The project must be in `FABRICATION`, or in `CONTRACTED` with every `CUSTOM_FABRICATION` item already `RECEIVED` — otherwise dispatch fails with `ERR_FABRICATION_INCOMPLETE`. And the new job must not collide with another non-cancelled job on the same project: overlap is permitted only when the two jobs differ in `rigging_required` or their windows are disjoint with at least a 2-hour buffer between them; otherwise dispatch fails with `ERR_DELIVERY_WINDOW_CONFLICT`. On dispatch, every `STOCK` item the job covers moves immediately from `ORDERED` to `RECEIVED`.

When the crew finishes rigging equipment into the space, marking the job site-complete requires `DISPATCHED` (`ERR_JOB_NOT_DISPATCHED`) and moves the job to `SITE_COMPLETE`. Every equipment item the job covers advances from `RECEIVED` to `INSTALLED`. If this was the last non-cancelled delivery job on the project and every fabrication order is in `FAB_COMPLETE` or `CANCELLED`, the project bubbles up from `FABRICATION` to `DELIVERED`. A coordinator may also cancel a job in `PLANNED` or `DISPATCHED` (any other state fails with `ERR_JOB_NOT_CANCELLABLE`); cancelling a dispatched job leaves items it had marked `RECEIVED` but not yet installed in `RECEIVED`. Delivery listings accept a `status` filter; the top-level list adds `project_id`.

### 3.7. Startup, Demo, and the Warranty Ledger

Startup is a per-item ceremony performed by a `StartupTechnician`. Scheduling a `StartupSession` requires the `equipment_item_id` being commissioned, the `technician_name` of the factory-authorized tech, and `demo_minutes` for the operator demonstration. The session is born `SCHEDULED` with `warranty_registered` false.

Completing the session is guarded three ways: the session must be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED`), the linked item must be `INSTALLED` (`ERR_ITEM_NOT_INSTALLED`), and `demo_minutes` must be at least 15 — a shorter demo does not count and fails with `ERR_DEMO_TOO_SHORT`. Completion fires a three-level cascade. The session moves to `COMPLETE` and its `warranty_registered` flips true. The linked item moves from `INSTALLED` to `STARTED`, its `warranty_status` flips from `UNREGISTERED` to `REGISTERED`, and the project's `warranty_registered_count` increments by 1. And when every non-cancelled equipment item on the project has reached `STARTED` with a `REGISTERED` warranty, the project bubbles from `DELIVERED` to `COMMISSIONED` — which in turn triggers the service-agency handoff below. A technician may instead void a `SCHEDULED` session (same not-scheduled guard), moving it to `VOID` with no item effects. Session listings accept `status` and `equipment_item_id` filters; the top-level list adds `project_id`.

**The service-agency handoff.** The moment a project reaches `COMMISSIONED`, the system selects a warranty service agency automatically. Eligibility requires the agency's `status` to be `ACTIVE`, the project's `health_jurisdiction` to appear in the agency's `covered_jurisdictions`, and the agency's `open_assignment_count` to be strictly below its `capacity`. Among eligible agencies the least-loaded wins — lowest `open_assignment_count` first — with ties broken by the oldest `created_at`; the `id` is never used as a tiebreaker. The winner gains a new `ServiceAssignment` in `OPEN` stamped with `opened_at`, and its `open_assignment_count` increments by 1. If no agency qualifies, the project simply remains in `DELIVERED`: the bubble-up to `COMMISSIONED` is deferred until a qualifying agency becomes available, and no error is raised.

Agencies themselves are managed by a `ServiceManager` (or `PlatformAdmin`), who registers each with an `agency_name`, the array of `covered_jurisdictions` it serves, and a `capacity` of at least 1; a new agency starts `ACTIVE` with `open_assignment_count` 0, and an agency's `status` may later stand at `INACTIVE`, which removes it from the selection pool. Once an assignment exists, the `ServiceManager` may close it — moving it from `OPEN` to `CLOSED` and decrementing the agency's `open_assignment_count` by 1 — or transfer it. Transfer requires the assignment to be `OPEN` (`ERR_ASSIGNMENT_NOT_OPEN` applies to both close and transfer) and the target agency, named by `target_agency_id`, to be `ACTIVE` with `open_assignment_count` below `capacity` (`ERR_AGENCY_AT_CAPACITY`, HTTP 402). A transfer moves the original assignment to `TRANSFERRED`, decrements the original agency's count, creates a new assignment in `OPEN` referencing the target agency, and increments the target agency's count. Assignment listings accept `status` and `agency_id` filters; the top-level list adds `project_id`. Agency listings accept a `status` filter.

### 3.8. Closeout: Punch List, Retainage, and Completion

Closeout starts once the project is `COMMISSIONED`. Anyone on the dealer side with `ProjectManager` authority — or the `Customer` — can raise a `PunchListItem` with a free-text `description` and a `severity` of exactly `COSMETIC`, `FUNCTIONAL`, or `LIFE_SAFETY`; items start `OPEN`. The `ProjectManager` verifies a resolved item, moving it to `VERIFIED`, or voids an open one, moving it to `VOID`. Punch listings accept `status` and `severity` filters; the top-level list adds `project_id`.

Closing the punch list is the retainage event, and it is one of the two optimistic-concurrency endpoints: the request must carry `expected_project_version` matching the project's current `version`, or it fails with `ERR_STALE_PROJECT_VERSION` (HTTP 412) per §2.6. The remaining guards, evaluated ahead of the version check in the fixed order, are: the project must be in `COMMISSIONED` (`ERR_PROJECT_NOT_COMMISSIONED`); no punch item may be `OPEN` with severity `FUNCTIONAL` or `LIFE_SAFETY` (`ERR_OPEN_BLOCKING_PUNCH_ITEMS`); and the project's `HEALTH_DEPT` permit filing must be `APPROVED` (`ERR_HEALTH_PERMIT_NOT_APPROVED`). On success the project moves to `PUNCH_CLOSED`, every still-`OPEN` `COSMETIC` punch item is voided, `retainage_held_cents` drops to 0, the released retainage amount is debited from the customer's `outstanding_exposure_cents`, and the project's `version` increments by 1.

Final completion requires the project to be in `PUNCH_CLOSED` (`ERR_PROJECT_NOT_PUNCH_CLOSED`) and every service assignment to be in `CLOSED` or `TRANSFERRED` (`ERR_OPEN_SERVICE_ASSIGNMENT`). Completion moves the project to `COMPLETED` and debits `quote_baseline_cents` from the customer's `outstanding_exposure_cents`, closing the account's exposure for the job.

### 3.9. Cancellation: Tearing Down a Live Project

A `ProjectManager` can cancel a project from any non-terminal state — `DESIGN`, `QUOTED`, `CONTRACTED`, `FABRICATION`, `DELIVERED`, or `COMMISSIONED`. The only precondition is that the project is not already terminal: cancelling a `COMPLETED` (or already `CANCELLED`) project fails with `ERR_PROJECT_ALREADY_TERMINAL`. The cascade is total. Every non-terminal quote becomes `SUPERSEDED`; every non-terminal fabrication order becomes `CANCELLED`; every non-terminal delivery job becomes `CANCELLED`; every non-terminal equipment item becomes `CANCELLED`; every `OPEN` punch item becomes `VOID`; every `OPEN` service assignment becomes `CLOSED`. Any retainage being held is released — `retainage_held_cents` drops to 0 — and the customer's `outstanding_exposure_cents` is reduced by this project's contribution, unwinding the exposure the deal had accumulated.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; all other successful operations, including state transitions, return HTTP 200. All request and response bodies follow the envelope defined in §2.2, and all list endpoints follow the pagination contract in §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | PlatformAdmin |
| POST | `/customers` | Create a Customer | PlatformAdmin |
| GET | `/customers` | List Customers | PlatformAdmin, ProjectManager, SalesRep |
| GET | `/customers/{customerId}` | Get a Customer | PlatformAdmin, ProjectManager, SalesRep, Customer |
| POST | `/customers/{customerId}/suspend` | Suspend a Customer (blocks quote acceptance) | PlatformAdmin |
| POST | `/design-build-projects` | Create a Project | ProjectManager |
| GET | `/design-build-projects` | List Projects | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer |
| GET | `/design-build-projects/{id}` | Get a Project | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer, PermitCoordinator, LogisticsCoordinator, FabricationLead, StartupTechnician, ServiceManager |
| POST | `/design-build-projects/{id}/cancel` | Cancel a Project and cascade to children | ProjectManager |
| POST | `/design-build-projects/{id}/close-punch-list` | Close the punch list, void OPEN COSMETIC items, release retainage | ProjectManager |
| POST | `/design-build-projects/{id}/complete` | Mark Project COMPLETED | ProjectManager |
| POST | `/design-build-projects/{id}/layouts` | Create a KitchenLayout | KitchenDesigner |
| GET | `/design-build-projects/{id}/layouts` | List KitchenLayouts for a Project | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer |
| GET | `/design-build-projects/{id}/layouts/{layoutId}` | Get a KitchenLayout | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer |
| POST | `/design-build-projects/{id}/layouts/{layoutId}/submit` | Submit a layout for review | KitchenDesigner |
| POST | `/design-build-projects/{id}/layouts/{layoutId}/approve` | Approve a layout; supersedes siblings | ProjectManager |
| POST | `/design-build-projects/{id}/layouts/{layoutId}/return-for-revision` | Return a SUBMITTED layout to DRAFT (revision loop) | ProjectManager |
| POST | `/design-build-projects/{id}/layouts/{layoutId}/equipment-items` | Add an EquipmentItem to a layout | KitchenDesigner, SalesRep |
| GET | `/design-build-projects/{id}/layouts/{layoutId}/equipment-items` | List EquipmentItems on a layout | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer, FabricationLead, StartupTechnician |
| GET | `/design-build-projects/{id}/equipment-items` | List EquipmentItems across all layouts of a project | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer, FabricationLead, StartupTechnician |
| GET | `/design-build-projects/{id}/equipment-items/{itemId}` | Get an EquipmentItem | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer, FabricationLead, StartupTechnician |
| POST | `/design-build-projects/{id}/quotes` | Create a Quote (PROVISIONAL) against an APPROVED layout | SalesRep |
| GET | `/design-build-projects/{id}/quotes` | List Quotes on a Project | PlatformAdmin, ProjectManager, SalesRep, Customer |
| GET | `/design-build-projects/{id}/quotes/{quoteId}` | Get a Quote | PlatformAdmin, ProjectManager, SalesRep, Customer |
| POST | `/design-build-projects/{id}/quotes/{quoteId}/present` | Present a Quote to the Customer | SalesRep |
| POST | `/design-build-projects/{id}/quotes/{quoteId}/accept` | Customer accepts a Quote (OCC on Project.version) | Customer |
| POST | `/design-build-projects/{id}/quotes/{quoteId}/reject` | Customer rejects a Quote | Customer |
| GET | `/design-build-projects/{id}/fabrication-orders` | List FabricationOrders on a Project | PlatformAdmin, ProjectManager, FabricationLead |
| GET | `/design-build-projects/{id}/fabrication-orders/{fabId}` | Get a FabricationOrder | PlatformAdmin, ProjectManager, FabricationLead |
| POST | `/design-build-projects/{id}/fabrication-orders/{fabId}/approve-shop-drawing` | Approve shop drawing | ProjectManager |
| POST | `/design-build-projects/{id}/fabrication-orders/{fabId}/start-production` | Begin fabrication | FabricationLead |
| POST | `/design-build-projects/{id}/fabrication-orders/{fabId}/complete` | Complete fabrication; reconcile final cost | FabricationLead |
| POST | `/design-build-projects/{id}/permit-filings` | Create a PermitFiling against an APPROVED layout | PermitCoordinator |
| GET | `/design-build-projects/{id}/permit-filings` | List PermitFilings on a Project | PlatformAdmin, ProjectManager, PermitCoordinator |
| GET | `/design-build-projects/{id}/permit-filings/{filingId}` | Get a PermitFiling | PlatformAdmin, ProjectManager, PermitCoordinator |
| POST | `/design-build-projects/{id}/permit-filings/{filingId}/submit` | Submit filing to authority | PermitCoordinator |
| POST | `/design-build-projects/{id}/permit-filings/{filingId}/record-decision` | Record authority decision (APPROVED or REJECTED) | PermitCoordinator |
| POST | `/design-build-projects/{id}/permit-filings/{filingId}/resubmit` | Resubmit a REJECTED filing (cyclic revision) | PermitCoordinator |
| POST | `/design-build-projects/{id}/delivery-jobs` | Plan a DeliveryJob | LogisticsCoordinator |
| GET | `/design-build-projects/{id}/delivery-jobs` | List DeliveryJobs on a Project | PlatformAdmin, ProjectManager, LogisticsCoordinator |
| GET | `/design-build-projects/{id}/delivery-jobs/{jobId}` | Get a DeliveryJob | PlatformAdmin, ProjectManager, LogisticsCoordinator |
| POST | `/design-build-projects/{id}/delivery-jobs/{jobId}/dispatch` | Dispatch a planned delivery | LogisticsCoordinator |
| POST | `/design-build-projects/{id}/delivery-jobs/{jobId}/mark-site-complete` | Mark delivery rigged into space | LogisticsCoordinator |
| POST | `/design-build-projects/{id}/delivery-jobs/{jobId}/cancel` | Cancel a DeliveryJob | LogisticsCoordinator |
| POST | `/design-build-projects/{id}/startup-sessions` | Schedule a startup/demo session for an INSTALLED EquipmentItem | StartupTechnician |
| GET | `/design-build-projects/{id}/startup-sessions` | List StartupSessions on a Project | PlatformAdmin, ProjectManager, StartupTechnician |
| GET | `/design-build-projects/{id}/startup-sessions/{sessionId}` | Get a StartupSession | PlatformAdmin, ProjectManager, StartupTechnician |
| POST | `/design-build-projects/{id}/startup-sessions/{sessionId}/complete` | Complete the startup; registers warranty | StartupTechnician |
| POST | `/design-build-projects/{id}/startup-sessions/{sessionId}/void` | Void a scheduled session | StartupTechnician |
| POST | `/service-agencies` | Register a ServiceAgency | ServiceManager, PlatformAdmin |
| GET | `/service-agencies` | List ServiceAgencies | PlatformAdmin, ProjectManager, ServiceManager |
| GET | `/service-agencies/{agencyId}` | Get a ServiceAgency | PlatformAdmin, ProjectManager, ServiceManager |
| GET | `/design-build-projects/{id}/service-assignments` | List ServiceAssignments on a Project | PlatformAdmin, ProjectManager, ServiceManager |
| GET | `/design-build-projects/{id}/service-assignments/{assignmentId}` | Get a ServiceAssignment | PlatformAdmin, ProjectManager, ServiceManager |
| POST | `/design-build-projects/{id}/service-assignments/{assignmentId}/close` | Close an OPEN assignment | ServiceManager |
| POST | `/design-build-projects/{id}/service-assignments/{assignmentId}/transfer` | Transfer an OPEN assignment to a different agency | ServiceManager |
| POST | `/design-build-projects/{id}/punch-list-items` | Add a punch-list item | ProjectManager, Customer |
| GET | `/design-build-projects/{id}/punch-list-items` | List PunchListItems on a Project | PlatformAdmin, ProjectManager, Customer |
| GET | `/design-build-projects/{id}/punch-list-items/{itemId}` | Get a PunchListItem | PlatformAdmin, ProjectManager, Customer |
| POST | `/design-build-projects/{id}/punch-list-items/{itemId}/verify` | Verify a punch item (resolution confirmed) | ProjectManager |
| POST | `/design-build-projects/{id}/punch-list-items/{itemId}/void` | Void an OPEN punch item | ProjectManager |
| GET | `/kitchen-layouts/{layoutId}` | Get a KitchenLayout by id (top-level) | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer, PermitCoordinator |
| GET | `/kitchen-layouts` | List KitchenLayouts with FK filters | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer, PermitCoordinator |
| GET | `/equipment-items/{itemId}` | Get an EquipmentItem by id (top-level) | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer, FabricationLead, StartupTechnician |
| GET | `/equipment-items` | List EquipmentItems with FK filters | PlatformAdmin, ProjectManager, SalesRep, KitchenDesigner, Customer, FabricationLead, StartupTechnician |
| GET | `/fabrication-orders/{fabId}` | Get a FabricationOrder by id (top-level) | PlatformAdmin, ProjectManager, FabricationLead |
| GET | `/fabrication-orders` | List FabricationOrders with FK filters | PlatformAdmin, ProjectManager, FabricationLead |
| GET | `/quotes/{quoteId}` | Get a Quote by id (top-level) | PlatformAdmin, ProjectManager, SalesRep, Customer |
| GET | `/quotes` | List Quotes with FK filters | PlatformAdmin, ProjectManager, SalesRep, Customer |
| GET | `/permit-filings/{filingId}` | Get a PermitFiling by id (top-level) | PlatformAdmin, ProjectManager, PermitCoordinator |
| GET | `/permit-filings` | List PermitFilings with FK filters | PlatformAdmin, ProjectManager, PermitCoordinator |
| GET | `/delivery-jobs/{jobId}` | Get a DeliveryJob by id (top-level) | PlatformAdmin, ProjectManager, LogisticsCoordinator |
| GET | `/delivery-jobs` | List DeliveryJobs with FK filters | PlatformAdmin, ProjectManager, LogisticsCoordinator |
| GET | `/startup-sessions/{sessionId}` | Get a StartupSession by id (top-level) | PlatformAdmin, ProjectManager, StartupTechnician |
| GET | `/startup-sessions` | List StartupSessions with FK filters | PlatformAdmin, ProjectManager, StartupTechnician |
| GET | `/service-assignments/{assignmentId}` | Get a ServiceAssignment by id (top-level) | PlatformAdmin, ProjectManager, ServiceManager |
| GET | `/service-assignments` | List ServiceAssignments with FK filters | PlatformAdmin, ProjectManager, ServiceManager |
| GET | `/punch-list-items/{itemId}` | Get a PunchListItem by id (top-level) | PlatformAdmin, ProjectManager, Customer |
| GET | `/punch-list-items` | List PunchListItems with FK filters | PlatformAdmin, ProjectManager, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_LAYOUT_NOT_FOUND | 404 |
| ERR_ITEM_NOT_FOUND | 404 |
| ERR_QUOTE_NOT_FOUND | 404 |
| ERR_FILING_NOT_FOUND | 404 |
| ERR_JOB_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_AGENCY_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_PROJECT_NOT_IN_DESIGN | 409 |
| ERR_PROJECT_NOT_QUOTED | 409 |
| ERR_PROJECT_NOT_COMMISSIONED | 409 |
| ERR_PROJECT_NOT_PUNCH_CLOSED | 409 |
| ERR_PROJECT_ALREADY_TERMINAL | 409 |
| ERR_PROJECT_NOT_READY_FOR_FABRICATION | 409 |
| ERR_LAYOUT_NOT_DRAFT | 409 |
| ERR_LAYOUT_NOT_SUBMITTED | 409 |
| ERR_LAYOUT_NOT_APPROVED | 409 |
| ERR_LAYOUT_EMPTY | 422 |
| ERR_HOOD_SPEC_INCONSISTENT | 422 |
| ERR_QUOTE_NOT_DRAFT | 409 |
| ERR_QUOTE_NOT_PRESENTED | 409 |
| ERR_QUOTE_NOT_OPEN | 409 |
| ERR_FILING_NOT_DRAFT | 409 |
| ERR_FILING_NOT_SUBMITTED | 409 |
| ERR_FILING_NOT_REJECTED | 409 |
| ERR_REVIEW_CYCLE_LIMIT_REACHED | 422 |
| ERR_JOB_NOT_PLANNED | 409 |
| ERR_JOB_NOT_DISPATCHED | 409 |
| ERR_JOB_NOT_CANCELLABLE | 409 |
| ERR_INVALID_JOB_WINDOW | 422 |
| ERR_DELIVERY_WINDOW_CONFLICT | 422 |
| ERR_SESSION_NOT_SCHEDULED | 409 |
| ERR_ITEM_NOT_INSTALLED | 409 |
| ERR_DEMO_TOO_SHORT | 422 |
| ERR_FAB_NOT_PENDING_DRAWING | 409 |
| ERR_FAB_NOT_APPROVED | 409 |
| ERR_FAB_NOT_IN_PRODUCTION | 409 |
| ERR_FABRICATION_INCOMPLETE | 422 |
| ERR_SHOP_DRAWING_MISSING | 422 |
| ERR_ASSIGNMENT_NOT_OPEN | 409 |
| ERR_AGENCY_AT_CAPACITY | 402 |
| ERR_OPEN_BLOCKING_PUNCH_ITEMS | 409 |
| ERR_OPEN_SERVICE_ASSIGNMENT | 409 |
| ERR_HEALTH_PERMIT_NOT_APPROVED | 422 |
| ERR_CUSTOMER_SUSPENDED | 402 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_STALE_PROJECT_VERSION | 412 |
