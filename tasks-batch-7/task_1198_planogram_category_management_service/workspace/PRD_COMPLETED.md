# Planogram Category Management API — Product Requirements Document

## 1. Introduction

Shelf space is the scarcest asset a retailer controls, and the negotiation over who gets how much of it is rarely neutral. In the category-captain model, a retailer delegates assortment and shelf-layout authorship for a category to an outside agency — frequently the category's largest supplier — and then must police the obvious temptation: a captain who draws the map may quietly draw it in its own favor. This API is the operational backbone for that arrangement. It governs the full loop of category management: defining categories and their shelf footage, registering suppliers and appointing category captains, cutting new products in and discontinuing old ones, authoring planograms with per-cluster variants, and pushing those planograms through review, approval, and activation into stores.

Around that core loop the platform wraps three control systems. Store-level photo audits measure whether the shelf in the aisle actually matches the approved planogram, converting field photos into compliance scores that can trigger corrective resets. Supplier funding deals — the money that flows alongside captaincy — are screened for conflicts of interest so that a captain cannot fund its own shelf expansion or freeze a rival out of the layout without the platform noticing. And reset projects schedule the physical labor of tearing down and rebuilding shelves, with crews whose concurrency is capped and whose calendars cannot overlap. Because so much of this domain is time-driven — discontinuations taking effect, funding windows opening and closing, resets starting — the service maintains a logical clock that operators can advance to exercise every scheduled transition.

## 2. Global Specifications & System-Wide Principles

This section defines the platform-wide contract: identity, envelope shape, pagination, precision, concurrency, and the validation gauntlet every request must survive. Business behavior proper lives in §3; the endpoint table in §4 names the HTTP surfaces, and §5 catalogs every error identifier.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The platform recognizes seven roles with exact spellings: `PlatformAdmin`, `RetailerAdmin`, `CategoryManager`, `CategoryCaptain`, `FieldAuditor`, `AuditReviewer`, and `ResetCoordinator`. A request that arrives without these headers, or carrying a role the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED`. Beyond authentication, every endpoint carries an authorization matrix; a caller whose role is not permitted to invoke that endpoint is rejected with `ERR_UNAUTHORIZED`.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `CategoryCaptain`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on any resource that references a `Supplier` compare the resource's foreign-key field to `X-User-ID`. This entity-backed identity is what allows the platform to attribute planogram authorship to a specific supplier and to evaluate captain-conflict rules. For the remaining six roles — `PlatformAdmin`, `RetailerAdmin`, `CategoryManager`, `FieldAuditor`, `AuditReviewer`, and `ResetCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow calls for attribution but does not resolve it against any entity's `id`. One deliberate exception to that opacity exists: the segregation-of-duties guard on planogram approval compares the approving `CategoryManager`'s raw `X-User-ID` string against the supplier identifier recorded at submission time, as described in §3.5.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object (the 204 line-deletion response is the exception — it carries no body at all). Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a page returns; it defaults to 10 when omitted, and a caller may not ask for fewer than 1 or more than 100. The `offset` parameter says how many items to skip before the page begins and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order — oldest first — with ties (common under the logical clock, which does not move between explicit advances) broken by creation order.

The `meta` object of any list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. Common Resource Properties

Every resource the platform persists — retailer, category, supplier, product, planogram, planogram line, store, audit event, funding deal, reset project, reset crew, and reset assignment — carries the same four system-managed fields:

- `id` — a server-minted UUID string, with no type prefix of any kind.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 at creation and increments by one on every mutation, including mutations driven by derived-value recomputation or cascading side effects rather than by a direct client write.

That last point matters: when adding a planogram line causes the parent planogram's totals to be recomputed, the planogram itself is mutated — its `updated_at` refreshes and its `version` advances — and the same holds for any cascade described in §3.

### 2.5. Retailer Scoping and Nested Resource Retrieval

Every resource in the system belongs, directly or through its ancestors, to exactly one retailer, and every nested path is interpreted within that retailer's scope. When a request path contains several identifiers — for example a retailer, then a category, then a planogram, then a line — the platform resolves those identifiers strictly left to right. The first identifier that does not resolve to an existing resource inside its parent's scope terminates the request with `ERR_NOT_FOUND`; later segments are never consulted, so a request aimed at a line under a nonexistent planogram reports the planogram miss rather than the line miss. This scoping rule also means that an identifier that exists under a *different* retailer is treated as nonexistent here.

Alongside the nested paths, the platform exposes flat retrieval: every resource type can be fetched by its bare `id` through a top-level single-resource path, and every resource type has a flat collection path that supports filtering by foreign keys. The per-resource filter sets are described in the §3 subsections that own each resource.

### 2.6. Units, Precision, and Sentinel Values

Money is always represented as integer cents — funding amounts arrive in `amount_cents`, product costs in `unit_cost_cents`, and a category's baseline sales in `annual_sales_cents`. Shelf geometry mixes two units deliberately: a category's shelf footage is expressed in linear feet, while a product's width is expressed in inches, so every utilization computation converts feet to inches by multiplying by twelve.

Rounding discipline is fixed per derived quantity. Days-of-supply values are rounded half-up to two decimal places. Shelf-utilization percentages and reset labor estimates are rounded half-up to one decimal place. Space-to-sales shares and gaps are rounded half-up to two decimal places per line, and that per-line rounding happens before any aggregate consistency check is applied to the column. Compliance scores are never rounded — they are floored to an integer percent.

Two sentinel values encode results that would otherwise be undefined. A days-of-supply computation facing a product with zero weekly demand reports the sentinel 9999.0 rather than an infinite or missing value. An indexed space-to-sales ratio facing a line whose sales share is zero reports the sentinel 999.0. Both sentinels survive every subsequent rounding step unchanged.

### 2.7. Optimistic Concurrency Control

Four write operations in this API are guarded by optimistic concurrency control. Each requires a non-optional expected-version field in its request body, carrying the caller's last observed `version` of the entity the operation acts upon; if that value no longer matches the entity's current `version` on the server, the write is rejected with `ERR_STALE_VERSION` and HTTP status 412. The four guarded operations are:

- Activating a planogram (`POST /retailers/{id}/categories/{cid}/planograms/{pid}/activate`) requires `expected_category_version`, matched against the parent category's current `version`.
- Discontinuing a product (`POST /retailers/{id}/products/{pid}/discontinue`) requires `expected_product_version`, matched against the product's current `version`.
- Approving a funding deal (`POST /retailers/{id}/funding-deals/{fdid}/approve`) requires `expected_funding_deal_version`, matched against the deal's current `version`.
- Scheduling a reset project (`POST /retailers/{id}/categories/{cid}/reset-projects/{rpid}/schedule`) requires `expected_reset_project_version`, matched against the project's current `version`.

The rejected caller should re-read the entity, observe what changed — a superseding activation, a prior discontinue or cancel, a conflict-flag recompute, a cascade bump — and reissue against the fresh version if still appropriate. No endpoint other than these four accepts an expected-version field.

On these four writes the expected-version field is examined in two passes: a present, well-typed integer that no longer matches is rejected with `ERR_STALE_VERSION` at stage four of the §2.8 gauntlet, ahead of the state guard; a field that is absent or not an integer is reported as `ERR_INVALID_REQUEST` only after the state guard has passed — so a request that is both missing its expected-version field and aimed at an entity in the wrong state draws `ERR_INVALID_STATE`.

### 2.8. Validation Order and State Guards

Every request passes through a fixed evaluation gauntlet, and a failure at any stage short-circuits everything after it. First, the identity headers must be present and the role recognized, else `ERR_UNAUTHENTICATED`. Second, the role must be authorized for the endpoint, else `ERR_UNAUTHORIZED`. Third, path identifiers resolve left to right within the retailer scope, else `ERR_NOT_FOUND`. Fourth, on the four OCC-guarded writes the expected-version check runs, else `ERR_STALE_VERSION`. Fifth, the target entity must be in a state that permits the requested transition, else `ERR_INVALID_STATE`; the category-open guards on cut-in, planogram submission, and activation live at this stage too, surfacing as `ERR_CATEGORY_LOCKED`. Only then are the endpoint's business rules evaluated, in the relative order each §3 workflow states — so on planogram approval, for instance, the segregation-of-duties screen is evaluated before the understock screen, and a request failing both reports the self-approval error.

Two cross-cutting codes sit beneath this gauntlet. A malformed payload — wrong field types, or a required field absent — is rejected with `ERR_INVALID_REQUEST` before any business evaluation begins. And a business-rule violation that carries no more specific code anywhere in this document falls back to the generic `ERR_VALIDATION`.

### 2.9. The Logical Clock and Scheduled Transitions

The platform keeps a logical UTC clock rather than consulting wall-clock time. At server startup the clock reads 2026-05-01T00:00:00Z. A `PlatformAdmin` may advance it through a test-driving capability that accepts a target instant in the `to_iso8601` field and answers with the clock's new value in `current_utc`. The endpoint sets the clock to the given instant outright — no monotonicity check is applied — and then evaluates every scheduled transition against the new value. Advancing the clock is not a bookkeeping no-op: it fires every time-based transition whose moment has arrived. Products in `DISCONTINUING` whose effective date has been reached become `DELISTED`; funding deals in `APPROVED` whose window has opened become `ACTIVE`; funding deals in `ACTIVE` whose window has closed become `CLOSED`; and reset projects in `SCHEDULED` whose start has arrived become `IN_PROGRESS`. §3 describes each of these transitions, including their cascades, in the workflow that owns them.

## 3. Business Logic & Workflows

### 3.1. Retailer Onboarding and Category Definition

Everything begins when a `PlatformAdmin` registers a retailer, supplying a `name` and, optionally, a `compliance_threshold_pct` — the minimum audit compliance score the retailer considers acceptable, which defaults to 85 when omitted. A new retailer's `status` begins at `ACTIVE`; the field is enumerated as `ACTIVE` or `SUSPENDED`.

With a retailer in place, a `CategoryManager` defines its categories. Each category carries a `code` that is unique within the retailer, a strategic `role` drawn from `DESTINATION`, `ROUTINE`, `CONVENIENCE`, or `SEASONAL`, a baseline `annual_sales_cents` figure used later by space-to-sales analysis, and the `total_linear_feet` of shelf the category occupies per store. Every category starts life `OPEN`, and its `active_planogram_id` — the pointer to the planogram currently live on the shelf — starts empty and stays empty until the first `BASE`-variant activation fills it (§3.5).

A `CategoryManager` may lock a category, moving it from `OPEN` to `LOCKED`. Locking is a freeze: while a category is `LOCKED`, no new product may be cut in under it and no planogram may be submitted for review under it — any attempt at either is rejected with `ERR_CATEGORY_LOCKED`. Unlocking returns the category from `LOCKED` to `OPEN`. Archiving is heavier and final: a `CategoryManager` may move an `OPEN` category to `ARCHIVED` only when no planogram for the category remains in `DRAFT`, `IN_REVIEW`, `APPROVED`, or `ACTIVE`, and no reset project for the category remains in `PROPOSED`, `SCHEDULED`, or `IN_PROGRESS`; otherwise the archive is rejected with `ERR_CATEGORY_HAS_OPEN_WORK`. When an archive does proceed, every `LISTED` product in the category is swept into `DISCONTINUING` with its `discontinuation_effective_date` set to the current instant, a cascade that then lets the normal delisting machinery take over.

Anyone with a valid role may browse the catalog: categories can be listed under their retailer, and a flat collection offers the same listing filtered by `retailer_id`.

### 3.2. Supplier Registry and Category Captaincy

A `RetailerAdmin` maintains the retailer's supplier roster. Creating a supplier takes only a `name`; the record starts with `is_captain` set to false and `captain_category_id` empty. Captainship in this domain is data, not a lifecycle — a supplier has no status machine of its own, and the two captainship fields are the entire mechanism.

Appointing a captain is a `RetailerAdmin` action that takes a `category_id` and writes both fields on the supplier: `is_captain` becomes true and `captain_category_id` records the category. The platform enforces a single-captain invariant per category — if another supplier was captain of that category, the outgoing captain's `is_captain` reverts to false and its `captain_category_id` is cleared as part of the same action. Because captainship feeds the funding-conflict screen, an appointment also recomputes `coi_flag` on every `PROPOSED` or `APPROVED` funding deal in the affected category (§3.8 defines the flags).

Suppliers can be listed within their retailer, and the flat collection accepts `retailer_id` and `captain_category_id` as filters — the latter answers "who captains this category?" in one call.

### 3.3. Product Catalog and the Cut-In Lifecycle

Products enter the catalog through either a `CategoryManager` or a `CategoryCaptain`. Creation names the product's `category_id` and `supplier_id`, a `sku` that is unique within the retailer, the unit's shelf `width_in` in inches, a `unit_cost_cents`, and a baseline `weekly_demand_units`. A new product is a `CANDIDATE`: it exists, but it occupies no shelf and contributes to no capacity math.

Cut-in — moving a product from `CANDIDATE` to `LISTED` — is a `CategoryManager` decision and requires the owning category to be `OPEN`; against a `LOCKED` or `ARCHIVED` category the attempt fails with `ERR_CATEGORY_LOCKED`. A product that has run its course moves from `LISTED` to `DISCONTINUING` when a `CategoryManager` discontinues it. That write carries two inputs: `discontinuation_effective_date`, which must lie strictly in the future at the moment of the call — a past or present date is rejected with `ERR_DISCONTINUATION_DATE_PAST` — and the OCC guard `expected_product_version`, which rejects the write with `ERR_STALE_VERSION` when the product's `version` has advanced past the caller's observation, for example after a prior cut-in or an earlier cancel-discontinuation. A successful discontinue sets the status to `DISCONTINUING` and increments the product's `version` by one. Products already in flight get one mercy: a `CategoryManager` may cancel the discontinuation of any product still in `DISCONTINUING` — no comparison of the effective date against the logical clock is made — returning the product to `LISTED` and clearing `discontinuation_effective_date`.

Discontinuation also ripples into planogram drafts. Every planogram line referencing the product on a planogram still in `DRAFT` or `IN_REVIEW` has its `days_of_supply` and `dos_flag` recomputed per §3.4; since discontinuation itself does not alter the product's `weekly_demand_units`, this recompute derives from the unchanged demand snapshot and so leaves the line's figures unchanged in practice.

The terminal step belongs to the clock. Once the logical clock reaches a `DISCONTINUING` product's `discontinuation_effective_date`, the product becomes `DELISTED`, and two cascades fire: every planogram line referencing the product on a `DRAFT` or `IN_REVIEW` planogram is deleted outright, while lines on `ACTIVE` planograms are left in place untouched — the platform does not auto-edit a live shelf. Delisted is not necessarily forever: a `CategoryManager` may relist a `DELISTED` product, which returns it to `CANDIDATE` — not directly to the shelf — so the product must pass through the cut-in flow again before it can occupy a facing.

The product collection supports filtering by `category_id`, `supplier_id`, and `status`; the flat listing adds `retailer_id` to that set.

### 3.4. Authoring Planograms: Lines, Facings, and Shelf Geometry

A planogram is authored under a category by a `CategoryCaptain` or a `CategoryManager`, starting from a `name`, a `variant` — one of `BASE`, `CLUSTER_A`, or `CLUSTER_B`, each targeting the store cluster of the same name — and an optional author `version_note`. A fresh planogram sits in `DRAFT` with `total_facings`, `total_capacity_units`, and `shelf_utilization_pct` all at zero.

The draft is built up line by line. Each line carries a `product_id`, a `position_index` giving its left-to-right shelf position (unique within the planogram), a `facings` count, and a `capacity_units` count. Two guards protect line integrity, and the product-eligibility screen runs first: the referenced product must exist within the retailer and currently be `LISTED` or `DISCONTINUING`, else the write is rejected with `ERR_PRODUCT_NOT_LISTABLE`. Then the line's own numbers are checked — `facings` must be at least one, `capacity_units` must be at least the line's `facings`, and `position_index` must not collide with another line in the same planogram — with any violation rejected as `ERR_LINE_INVALID`. While a planogram remains in `DRAFT`, its author may also remove a line entirely; deletion answers with no content and, like every line mutation, triggers a full recomputation of the planogram's derived values.

Those derived values are the heart of the draft. Each line's `days_of_supply` answers "how long does the allocated shelf last at current demand?": the line's `capacity_units` is divided by the product's average daily demand, where average daily demand is the product's `weekly_demand_units` divided by seven, and the quotient is rounded half-up to two decimal places. A product whose `weekly_demand_units` is zero yields no finite answer, so the line instead reports the sentinel 9999.0. Only lines whose product is `LISTED` or `DISCONTINUING` contribute to this math — `CANDIDATE` and `DELISTED` products are excluded. While the planogram is in `DRAFT` or `IN_REVIEW`, this figure is provisional: computed from the current demand snapshot with no alignment to shelf-pack boundaries.

From each line's `days_of_supply` comes its `dos_flag`. A line lasting strictly less than 3.0 days is flagged `UNDERSTOCK`; one lasting strictly more than 21.0 days is flagged `OVERSTOCK`; everything between those poles is `OK`. The boundaries are inclusive of healthy: a line at exactly 3.0 days is `OK`, and so is a line at exactly 21.0 days.

The planogram header aggregates its lines continuously. `total_facings` is the sum of `facings` across the planogram's non-deleted lines, and `total_capacity_units` is the corresponding sum of `capacity_units`. `shelf_utilization_pct` measures footprint: it is one hundred times the total shelf inches consumed — the sum, across lines whose product is `LISTED` or `DISCONTINUING`, of each line's `facings` multiplied by its product's `width_in` — divided by the category's total shelf inches, which is its `total_linear_feet` multiplied by twelve; the result is rounded half-up to one decimal place. A category with zero shelf footage yields a `shelf_utilization_pct` of 0.0. Because these header values mutate whenever a line is added, changed, or removed — or whenever an underlying product's width or demand figure changes — each such recomputation refreshes the planogram's `updated_at` and advances its `version` per §2.4.

Planograms can be listed under their category with `variant` and `status` filters; lines are listed under their planogram. The flat planogram collection additionally filters by `category_id` and by `submitted_by_captain_supplier_id`, and the flat line collection filters by `planogram_id` and `product_id`.

### 3.5. Planogram Review, Approval, and Activation

When an author considers a draft complete, submission moves the planogram from `DRAFT` to `IN_REVIEW`. Submission is a `CategoryCaptain` action — the retailer deliberately delegates authorship — and the category must be `OPEN`, else `ERR_CATEGORY_LOCKED`. Three structural checks then gate the transition, all reporting `ERR_PLANOGRAM_INVALID`: the planogram must contain at least one line, its `shelf_utilization_pct` must not exceed one hundred percent, and no line may reference a `DELISTED` product. A successful submission also records provenance: the calling captain's supplier identifier, taken from the `X-User-ID` header, is written to the planogram's `submitted_by_captain_supplier_id`.

Review lands on a `CategoryManager`'s desk, and approval is guarded in a fixed order. The planogram must currently be `IN_REVIEW`, else `ERR_INVALID_STATE`. Next comes segregation of duties: if the approving manager's `X-User-ID` equals the recorded `submitted_by_captain_supplier_id`, the approval is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` — the same person may not wear both the captain and manager hats for one planogram. Only then does the assortment screen run: no line on the planogram may carry a `dos_flag` of `UNDERSTOCK` unless the category's `role` is `CONVENIENCE`, with violations rejected as `ERR_UNDERSTOCK_NOT_ALLOWED`; and no line may reference a `DELISTED` product, which the platform reports through the generic `ERR_VALIDATION`. Approval moves the planogram from `IN_REVIEW` to `APPROVED` and does two more things besides: every line's `days_of_supply` is recomputed into its finalized form — snapped down to the greatest half-day boundary that does not exceed the raw value, so a line's approved figure can be smaller than, but never larger than, its provisional one, with the 9999.0 sentinel preserved untouched — and every `PROPOSED` funding deal in the same category has its `coi_flag` recomputed against the newly approved layout. Rejection, also a `CategoryManager` action, moves an `IN_REVIEW` planogram to `REJECTED` with no further conditions.

Authors are not trapped by a single submission. A `CategoryCaptain` may return an `IN_REVIEW` planogram to `DRAFT` at will, and may likewise return an `APPROVED` planogram to `DRAFT` provided the planogram has never been `ACTIVE` — so the cycle `DRAFT` → `IN_REVIEW` → `DRAFT` can iterate indefinitely until the planogram is finally approved or rejected.

Activation is the point where a planogram meets the shelf. A `CategoryManager` activates an `APPROVED` planogram by supplying `expected_category_version`; if the category's `version` has advanced since the caller last read it — most commonly because another writer has just activated a different planogram of the same category and variant — the write is rejected with `ERR_STALE_VERSION`. The planogram must currently be `APPROVED`, else `ERR_INVALID_STATE`; the category must then be `OPEN`, else `ERR_CATEGORY_LOCKED`. A previously `ACTIVE` planogram of the same category and `variant` never blocks activation — it is superseded by the cascade below. A successful activation fires a three-deep cascade. The planogram becomes `ACTIVE` and the category's `version` increments by one; when the activated `variant` is `BASE`, the category's `active_planogram_id` is set to this planogram. The previously `ACTIVE` planogram of the same category and variant — if one exists — automatically becomes `SUPERSEDED`, and if the category's `active_planogram_id` had pointed at that superseded planogram, the pointer moves to the successor on the `BASE` variant. Finally, any reset project still referencing the superseded planogram in `PROPOSED` or `SCHEDULED` status is moved to `CANCELLED`, and every `ASSIGNED` crew assignment under those cancelled projects is released to `RELEASED` — a depth-two cascade that keeps labor commitments honest against a layout that no longer exists.

### 3.6. Space-to-Sales Analysis

On demand, a `CategoryManager`, `CategoryCaptain`, or `RetailerAdmin` may ask for the space-to-sales analysis of a category. The report is built from the category's `ACTIVE` planogram — one per `variant` — considering only lines joined to products whose status is `LISTED`, and returns one entry per line carrying the line's `planogram_line_id` and `product_id` plus three computed measures. The response `data` is a single object wrapping a `lines` array — the endpoint is not paginated — with entries ordered by planogram creation order and, within a planogram, by line creation order. If the total occupied inches or the total weekly demand across the report is zero, every line's corresponding share is 0.0.

`space_share_pct` is the line's slice of the shelf: one hundred times the line's occupied inches (`facings` multiplied by the product's `width_in`) divided by the total occupied inches across all lines in the report. `sales_share_pct` is the line's slice of demand: one hundred times the product's `weekly_demand_units` divided by the total weekly demand across all lines in the report. `gap_pct` is the signed percentage-point difference — space share minus sales share — so a positive gap marks a product holding more shelf than its demand justifies. Each per-line value is rounded half-up to two decimal places before any aggregate check is applied to the column.

A caller who supplies the query parameter `mode` with the value `indexed` receives a different fourth measure in place of the gap: `gap_ratio`, defined as `space_share_pct` divided by `sales_share_pct`, where 1.0 marks a perfectly balanced line; any other `mode` value — or none — yields `gap_pct`. When a line's sales share is zero the ratio is undefined, and the report emits the sentinel 999.0 for it instead.

### 3.7. Stores, Compliance Audits, and Photo Scoring

Stores are the terrain where planograms live. A `RetailerAdmin` creates each store with a `store_code` unique within the retailer and a `cluster` — `BASE`, `CLUSTER_A`, or `CLUSTER_B` — that binds the store to the planogram variant it executes. Stores can be listed under their retailer with a `cluster` filter, and the flat store collection filters by `retailer_id` and `cluster`.

Compliance begins in the aisle: a `FieldAuditor` photographs a store's shelf and submits an audit naming the `planogram_id` being audited and the photo's `photo_url`; the referenced planogram need only exist within the retailer — its status is not screened at submission. The new audit event starts in `SUBMITTED`, records the submitting role in `submitted_by_role` — always `FieldAuditor` here, since only that role may submit — and freezes a snapshot of the audited planogram's `total_facings` into `total_facings_expected` at submission time, so later edits to the planogram can never retroactively move the goalposts. `matched_facings`, `compliance_score_pct`, and `compliance_outcome` remain null until scoring.

Scoring belongs to a different pair of hands. An `AuditReviewer` scores a `SUBMITTED` audit by supplying `matched_facings`, the count of facings judged compliant in the photo; an audit in any other state cannot be scored (`ERR_INVALID_STATE`), a payload missing the count fails with `ERR_INVALID_REQUEST`, and the count itself must lie between zero and `total_facings_expected` inclusive, else `ERR_AUDIT_SCORE_RANGE`. A successful scoring moves the audit from `SUBMITTED` to `SCORED`. The audited planogram must also be `ACTIVE` or `SUPERSEDED` at scoring time — a scoring attempt against a planogram in any other status is rejected with the generic `ERR_VALIDATION`. From those inputs the platform computes `compliance_score_pct`: zero when `total_facings_expected` is zero, otherwise the floor — the greatest integer not exceeding the exact quotient — of one hundred times `matched_facings` divided by `total_facings_expected`. The score then becomes a `compliance_outcome` against the retailer's `compliance_threshold_pct`: a score greater than or equal to the threshold is a `PASS` (a score exactly equal to the threshold passes); a score below the threshold but greater than or equal to ten points under it is a `WARN`; anything lower is a `FAIL`.

A `FAIL` is not merely recorded. When the outcome is `FAIL` and the audited planogram is still `ACTIVE`, the platform automatically creates a new reset project in `PROPOSED` status for the store, the planogram's category, and that planogram, carrying a fourteen-day window that starts at 00:00:00Z on the day after the scoring and ends fourteen days later — the compliance loop closes by scheduling the labor that will fix the shelf. An `AuditReviewer` may instead reject a `SUBMITTED` audit outright, moving it to `REJECTED` with no scoring at all.

Audits can be listed under their store with a `status` filter; the flat audit collection filters by `store_id`, `planogram_id`, and `status`.

### 3.8. Supplier Funding and Conflict-of-Interest Screening

Funding is where the captain model's tension is sharpest, and the platform screens every deal the moment it is proposed. Either a `RetailerAdmin` or a `CategoryCaptain` may propose a deal, supplying the funded `category_id`, the funding `supplier_id`, the `amount_cents`, and the window bounds `starts_at` and `ends_at`. The deal begins in `PROPOSED`, and its `coi_flag` is computed immediately.

The conflict screen has three branches. When the funding supplier is the appointed captain of the very category the deal funds, the platform takes the most recently created `APPROVED`-or-`ACTIVE` planogram of that category and compares it against the most recently created prior `ACTIVE` planogram of the same category, splitting each planogram's lines into the captain's own products and rival suppliers' products and measuring each side's share of occupied shelf inches (`facings` × `width_in`, summed over all of the planogram's lines); if the captain's share has strictly increased while the rivals' share has strictly decreased, the deal is flagged `CAPTAIN_SELF_DEALING`, and otherwise `NONE`. When no `APPROVED`-or-`ACTIVE` planogram exists for the category, or no prior `ACTIVE` planogram exists to compare against, the flag is `NONE`. When the funding supplier captains some *other* category, the deal is simply `NONE` — captaincy elsewhere is no conflict here. When the funding supplier holds no captaincy at all, the platform asks whether the funded category has a captain whose layouts shut this supplier out: if a captain exists for the category and no line in any of the category's `APPROVED` or `ACTIVE` planograms references any product of the funding supplier, the deal is flagged `CAPTAIN_BLOCKING_RIVAL`, and otherwise `NONE`. The flag is recomputed on three occasions: when the deal is created, when a planogram in the same category is approved (which refreshes the flags of `PROPOSED` deals in that category), and when captainship of the category changes hands.

Approval of a deal is reserved for a `RetailerAdmin` — the funding supplier must of course exist within the retailer for the deal to be approvable — and is OCC-guarded by `expected_funding_deal_version` — a stale view, for example one taken before a planogram approval recomputed the flag and bumped the deal's `version`, is rejected with `ERR_STALE_VERSION`. A deal whose `coi_flag` stands at `CAPTAIN_BLOCKING_RIVAL` cannot be approved at all: the attempt is rejected with `ERR_CAPTAIN_CONFLICT`, and the deal must instead be walked down the rejection path. Notably, a `CAPTAIN_SELF_DEALING` flag does not by itself block approval — it is recorded for scrutiny, while only the rival-blocking case is hard-stopped. Approval moves the deal from `PROPOSED` to `APPROVED` and increments its `version` by one; rejection moves a `PROPOSED` deal to `REJECTED`. The clock takes it from there: when the logical clock reaches `starts_at`, an `APPROVED` deal becomes `ACTIVE`, and when the clock reaches `ends_at`, an `ACTIVE` deal becomes `CLOSED`.

Funding deals can be listed under their retailer with `category_id`, `supplier_id`, and `status` filters; the flat collection adds `retailer_id`.

### 3.9. Reset Projects, Crews, and Labor Scheduling

Tearing a shelf down and rebuilding it to a new planogram is a reset project. A `ResetCoordinator` — or a `CategoryManager` — creates one under a category by naming the `planogram_id` to install (the referenced planogram's status is not screened at creation — scheduling re-verifies it; the audit-driven cascade of §3.7 instead references the live `ACTIVE` planogram), the `store_id` where the work happens, and the window bounds `scheduled_start` and `scheduled_end`, which must already satisfy `scheduled_start` strictly earlier than `scheduled_end` at creation, else `ERR_RESET_WINDOW_CONFLICT`. The project starts in `PROPOSED`, and the platform immediately estimates its labor.

`labor_hours_estimated` blends two drivers. First the platform counts product changes: the number of lines on the target planogram whose `product_id` does not appear on the store's currently installed planogram for the category — the `ACTIVE` planogram of the category whose `variant` matches the store's `cluster` — or every line on the target planogram when the store has nothing installed yet. The raw estimate is then the target planogram's `total_facings` multiplied by 0.05 hours per facing, plus the product-change count multiplied by 0.25 hours per change, and the result is rounded half-up to one decimal place. While the project remains `PROPOSED`, the estimate stays live: any change to the target planogram's `total_facings` recomputes it.

Scheduling — moving a project from `PROPOSED` to `SCHEDULED` — belongs to the `ResetCoordinator` and is OCC-guarded by `expected_reset_project_version`, so a caller whose view predates a cancel or a cascade bump is rejected with `ERR_STALE_VERSION`. The window itself must be sound: `scheduled_start` strictly earlier than `scheduled_end`, and no overlap with any other project at the same store that is currently `SCHEDULED` or `IN_PROGRESS`. Overlap arithmetic is half-open — a project whose `scheduled_start` equals another's `scheduled_end` runs back-to-back without conflict — and any violation of these window rules is rejected with `ERR_RESET_WINDOW_CONFLICT`. Scheduling also re-verifies that the referenced planogram is `APPROVED` or `ACTIVE`; a project pointing at anything else is rejected with `ERR_VALIDATION`. From there the clock starts the work: when it reaches `scheduled_start`, a `SCHEDULED` project becomes `IN_PROGRESS`.

Completion requires evidence that someone actually showed up: a `ResetCoordinator` may complete an `IN_PROGRESS` project only when at least one crew assignment on it still stands in `ASSIGNED` status. Completion moves the project to `COMPLETED` and releases every `ASSIGNED` assignment on it to `RELEASED`. Cancellation is available from either `PROPOSED` or `SCHEDULED`: cancelling a `PROPOSED` project simply moves it to `CANCELLED`, while cancelling a `SCHEDULED` project additionally releases all of its `ASSIGNED` assignments.

The labor itself belongs to crews. A `ResetCoordinator` creates each crew with a `name` and an optional `max_concurrent_projects`, the crew's concurrency cap, which defaults to 1. Assigning a crew to a project is permitted only while the project is `PROPOSED` or `SCHEDULED`, else `ERR_INVALID_STATE`; the write takes the `crew_id` and a working window `assigned_start` to `assigned_end`, and the new assignment starts in `ASSIGNED`. Four constraints guard the write, all reported as `ERR_CREW_OVERLAP`: the assigned window must itself be sound — `assigned_start` strictly earlier than `assigned_end`; the assigned window must lie entirely inside its project's scheduled window; it must not overlap — again using half-open arithmetic, so back-to-back assignments are fine — any other `ASSIGNED` assignment belonging to the same crew; and at no instant may the count of `ASSIGNED` assignments sitting on a crew exceed that crew's `max_concurrent_projects`. A `ResetCoordinator` may also release an assignment early, moving it from `ASSIGNED` to `RELEASED` and freeing the crew's capacity before the project otherwise ends.

Reset projects can be listed under their category with `store_id` and `status` filters, and the flat collection adds `category_id` and `planogram_id`. Crews list under their retailer, with the flat collection filtering by `retailer_id`. Assignments list under their project, and the flat assignment collection filters by `reset_project_id`, `crew_id`, and `status`.

## 4. Endpoint Definitions

All paths below are relative to the service root. Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state transition — return `200 OK`; the single deletion operation in the API, removing a planogram line, returns `204 No Content`. The request and response payloads of each operation are defined by the §3 workflow narratives rather than by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/retailers` | Create retailer | PlatformAdmin |
| GET | `/retailers/{id}` | Get retailer | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| POST | `/retailers/{id}/categories` | Create category | CategoryManager |
| GET | `/retailers/{id}/categories` | List categories | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/retailers/{id}/categories/{cid}` | Get category | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| POST | `/retailers/{id}/categories/{cid}/lock` | Lock category | CategoryManager |
| POST | `/retailers/{id}/categories/{cid}/unlock` | Unlock category | CategoryManager |
| POST | `/retailers/{id}/categories/{cid}/archive` | Archive category | CategoryManager |
| GET | `/retailers/{id}/categories/{cid}/space-to-sales` | Space-to-sales analysis for category | CategoryManager, CategoryCaptain, RetailerAdmin |
| POST | `/retailers/{id}/suppliers` | Create supplier | RetailerAdmin |
| GET | `/retailers/{id}/suppliers` | List suppliers | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain |
| GET | `/retailers/{id}/suppliers/{sid}` | Get supplier | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain |
| POST | `/retailers/{id}/suppliers/{sid}/appoint-captain` | Appoint supplier as captain of a category | RetailerAdmin |
| POST | `/retailers/{id}/products` | Create product (CANDIDATE) | CategoryManager, CategoryCaptain |
| GET | `/retailers/{id}/products` | List products, optionally filtered by category, supplier, or status | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/retailers/{id}/products/{pid}` | Get product | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| POST | `/retailers/{id}/products/{pid}/list` | Cut in / list product | CategoryManager |
| POST | `/retailers/{id}/products/{pid}/discontinue` | Discontinue product (OCC on product) | CategoryManager |
| POST | `/retailers/{id}/products/{pid}/cancel-discontinuation` | Cancel discontinuation | CategoryManager |
| POST | `/retailers/{id}/products/{pid}/relist` | Re-list delisted product back to CANDIDATE | CategoryManager |
| POST | `/retailers/{id}/categories/{cid}/planograms` | Create planogram (DRAFT) | CategoryCaptain, CategoryManager |
| GET | `/retailers/{id}/categories/{cid}/planograms` | List planograms for category | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/retailers/{id}/categories/{cid}/planograms/{pid}` | Get planogram | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| POST | `/retailers/{id}/categories/{cid}/planograms/{pid}/submit` | Submit planogram for review | CategoryCaptain |
| POST | `/retailers/{id}/categories/{cid}/planograms/{pid}/approve` | Approve planogram (segregation of duties enforced) | CategoryManager |
| POST | `/retailers/{id}/categories/{cid}/planograms/{pid}/reject` | Reject planogram | CategoryManager |
| POST | `/retailers/{id}/categories/{cid}/planograms/{pid}/return-to-draft` | Return planogram to DRAFT for author iteration | CategoryCaptain |
| POST | `/retailers/{id}/categories/{cid}/planograms/{pid}/activate` | Activate planogram (OCC on category) | CategoryManager |
| POST | `/retailers/{id}/categories/{cid}/planograms/{pid}/lines` | Add line to planogram | CategoryCaptain, CategoryManager |
| GET | `/retailers/{id}/categories/{cid}/planograms/{pid}/lines` | List lines of planogram | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/retailers/{id}/categories/{cid}/planograms/{pid}/lines/{lid}` | Get planogram line | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| DELETE | `/retailers/{id}/categories/{cid}/planograms/{pid}/lines/{lid}` | Delete planogram line (DRAFT only) | CategoryCaptain, CategoryManager |
| POST | `/retailers/{id}/stores` | Create store | RetailerAdmin |
| GET | `/retailers/{id}/stores` | List stores | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/retailers/{id}/stores/{sid}` | Get store | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| POST | `/retailers/{id}/stores/{sid}/audits` | Submit audit event with photo | FieldAuditor |
| GET | `/retailers/{id}/stores/{sid}/audits` | List audits for store | PlatformAdmin, RetailerAdmin, CategoryManager, FieldAuditor, AuditReviewer |
| GET | `/retailers/{id}/stores/{sid}/audits/{aid}` | Get audit | PlatformAdmin, RetailerAdmin, CategoryManager, FieldAuditor, AuditReviewer |
| POST | `/retailers/{id}/stores/{sid}/audits/{aid}/score` | Score audit | AuditReviewer |
| POST | `/retailers/{id}/stores/{sid}/audits/{aid}/reject` | Reject audit | AuditReviewer |
| POST | `/retailers/{id}/funding-deals` | Propose funding deal | RetailerAdmin, CategoryCaptain |
| GET | `/retailers/{id}/funding-deals` | List funding deals | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain |
| GET | `/retailers/{id}/funding-deals/{fdid}` | Get funding deal | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain |
| POST | `/retailers/{id}/funding-deals/{fdid}/approve` | Approve funding deal (OCC on deal) | RetailerAdmin |
| POST | `/retailers/{id}/funding-deals/{fdid}/reject` | Reject funding deal | RetailerAdmin |
| POST | `/retailers/{id}/categories/{cid}/reset-projects` | Create reset project | ResetCoordinator, CategoryManager |
| GET | `/retailers/{id}/categories/{cid}/reset-projects` | List reset projects | PlatformAdmin, RetailerAdmin, CategoryManager, ResetCoordinator |
| GET | `/retailers/{id}/categories/{cid}/reset-projects/{rpid}` | Get reset project | PlatformAdmin, RetailerAdmin, CategoryManager, ResetCoordinator |
| POST | `/retailers/{id}/categories/{cid}/reset-projects/{rpid}/schedule` | Schedule reset project (OCC on project) | ResetCoordinator |
| POST | `/retailers/{id}/categories/{cid}/reset-projects/{rpid}/complete` | Complete reset project | ResetCoordinator |
| POST | `/retailers/{id}/categories/{cid}/reset-projects/{rpid}/cancel` | Cancel reset project | ResetCoordinator |
| POST | `/retailers/{id}/reset-crews` | Create reset crew | ResetCoordinator |
| GET | `/retailers/{id}/reset-crews` | List reset crews | PlatformAdmin, RetailerAdmin, ResetCoordinator |
| GET | `/retailers/{id}/reset-crews/{rcid}` | Get reset crew | PlatformAdmin, RetailerAdmin, ResetCoordinator |
| POST | `/retailers/{id}/categories/{cid}/reset-projects/{rpid}/assignments` | Assign crew to project | ResetCoordinator |
| GET | `/retailers/{id}/categories/{cid}/reset-projects/{rpid}/assignments` | List assignments on project | PlatformAdmin, RetailerAdmin, ResetCoordinator |
| GET | `/retailers/{id}/categories/{cid}/reset-projects/{rpid}/assignments/{raid}` | Get assignment | PlatformAdmin, RetailerAdmin, ResetCoordinator |
| POST | `/retailers/{id}/categories/{cid}/reset-projects/{rpid}/assignments/{raid}/release` | Release assignment early | ResetCoordinator |
| GET | `/categories` | List categories filtered by foreign key | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/suppliers` | List suppliers filtered by foreign key | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain |
| GET | `/products` | List products filtered by foreign key | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/planograms` | List planograms filtered by foreign key | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/planogram-lines` | List planogram lines filtered by foreign key | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/stores` | List stores filtered by foreign key | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/audit-events` | List audit events filtered by foreign key | PlatformAdmin, RetailerAdmin, CategoryManager, FieldAuditor, AuditReviewer |
| GET | `/funding-deals` | List funding deals filtered by foreign key | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain |
| GET | `/reset-projects` | List reset projects filtered by foreign key | PlatformAdmin, RetailerAdmin, CategoryManager, ResetCoordinator |
| GET | `/reset-crews` | List reset crews filtered by foreign key | PlatformAdmin, RetailerAdmin, ResetCoordinator |
| GET | `/reset-assignments` | List reset assignments filtered by foreign key | PlatformAdmin, RetailerAdmin, ResetCoordinator |
| GET | `/categories/{id}` | Get category by id (flat) | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/suppliers/{id}` | Get supplier by id (flat) | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain |
| GET | `/products/{id}` | Get product by id (flat) | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/planograms/{id}` | Get planogram by id (flat) | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/planogram-lines/{id}` | Get planogram line by id (flat) | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/stores/{id}` | Get store by id (flat) | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain, FieldAuditor, AuditReviewer, ResetCoordinator |
| GET | `/audit-events/{id}` | Get audit event by id (flat) | PlatformAdmin, RetailerAdmin, CategoryManager, FieldAuditor, AuditReviewer |
| GET | `/funding-deals/{id}` | Get funding deal by id (flat) | PlatformAdmin, RetailerAdmin, CategoryManager, CategoryCaptain |
| GET | `/reset-projects/{id}` | Get reset project by id (flat) | PlatformAdmin, RetailerAdmin, CategoryManager, ResetCoordinator |
| GET | `/reset-crews/{id}` | Get reset crew by id (flat) | PlatformAdmin, RetailerAdmin, ResetCoordinator |
| GET | `/reset-assignments/{id}` | Get reset assignment by id (flat) | PlatformAdmin, RetailerAdmin, ResetCoordinator |
| POST | `/retailers/{id}/_clock/set_current_utc` | Set logical clock (startup default 2026-05-01T00:00:00Z) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CATEGORY_LOCKED` | 409 Conflict |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_CAPTAIN_CONFLICT` | 422 Unprocessable Entity |
| `ERR_RESET_WINDOW_CONFLICT` | 422 Unprocessable Entity |
| `ERR_CREW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_LISTABLE` | 422 Unprocessable Entity |
| `ERR_PLANOGRAM_INVALID` | 422 Unprocessable Entity |
| `ERR_UNDERSTOCK_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_DISCONTINUATION_DATE_PAST` | 422 Unprocessable Entity |
| `ERR_CATEGORY_HAS_OPEN_WORK` | 422 Unprocessable Entity |
| `ERR_AUDIT_SCORE_RANGE` | 422 Unprocessable Entity |
| `ERR_LINE_INVALID` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
