# Rack Jobber Consignment API — Product Requirements Document

## 1. Introduction

Rack jobbing is a consignment business: the jobber owns the inventory sitting on the retailer's racks, services it on a route schedule, and gets paid only for what actually scans at the register. That single inversion — title stays with the supplier until the point of sale — creates a web of disputes that paper processes handle badly. Who absorbs the shrink between deliveries? Which promotion price applied to a given scan, and who funds the discount? Is the retailer owed its tiered margin uplift this period? Was the holiday set torn down on time? This document specifies the Rack Jobber Consignment API, the system of record for a scan-based trading program that answers those questions deterministically.

The API governs the full commercial lifecycle: a jobber administrator standing up programs, stores, and consignment agreements with explicit commercial terms; maintained retail prices and promotional windows; shelf-space allocation under facing-capacity and category-exclusivity rules; route service visits with counted restocks; point-of-sale scan ingestion resolved against price directives; independent shrink audits performed under segregation of duties; markdown and return-to-vendor authorizations; provisional-versus-final settlement statements with tiered retailer margins; and seasonal display sets with teardown penalties. Because the program is adjudicative by nature, the system runs on a logical clock rather than wall-clock time, records every monetary figure as integer cents, and applies optimistic concurrency control wherever a stale read could silently overwrite commercial terms a counterparty has already relied on.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 400). The system recognizes exactly five roles, spelled as follows: `JobberAdmin`, `RetailerManager`, `RouteDriver`, `FieldAuditor`, and `JobberFinance`. Each endpoint declares the roles authorized to invoke it; a request whose `X-User-Role` is not in the endpoint's role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The `JobberAdmin` is the rack jobber's operations administrator: it owns all master data, commercial terms, pricing, promotions, space, and seasonal programs; it certifies audits and approves settlements. The `RetailerManager` is the store-side manager. The `RouteDriver` is the jobber's route driver. The `FieldAuditor` is an independent shrink auditor who performs counts but may never certify them. The `JobberFinance` operator generates, finalizes, revises, and pays settlement statements but may never approve them. All five roles may read any resource.

Identity semantics differ by role. When `X-User-Role` is `RetailerManager`, `X-User-ID` is the `id` of the acting `Store`; ownership checks on any resource that references a `Store` — most importantly the agreement being acted on — compare the resource's store foreign-key field to `X-User-ID`. When `X-User-Role` is `JobberAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` on a `StoreAgreement` or `certified_by_user_id` on an `AuditCount`) but does not compare it to any entity's `id`. When `X-User-Role` is `RouteDriver`, `X-User-ID` is likewise an opaque operator identifier; visit execution checks compare it to the target route's `assigned_driver_id` string, never to an entity `id`. When `X-User-Role` is `FieldAuditor`, `X-User-ID` is an opaque operator identifier, recorded as `counted_by_user_id` on submitted audits. When `X-User-Role` is `JobberFinance`, `X-User-ID` is an opaque operator identifier, recorded as `created_by_user_id` on the settlement statements it generates.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. The `version` field is an integer that increments by one on every mutation and underpins the optimistic concurrency controls of §2.7. Path parameters that address a resource — denoted `{id}` in §4 — always carry this UUID.

One entity deliberately breaks this pattern. A `ScanEvent` is an append-only ledger entry: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent. Scan events are never updated or deleted after ingest; any correction happens exclusively through a compensating void event, as described in §3.6.

### 2.5. Money, Dates, and Rounding Conventions

All monetary amounts in the system — prices, costs, credits, charges, caps, and payouts — are integer cents. Every rounding performed anywhere in the system is round half-up, meaning a fractional remainder of exactly one half rounds away from zero. Where a rule in this document says a value is "rounded half-up", it refers to this convention applied to whole cents (or, where stated, to whole units).

Two date representations coexist. Calendar dates — settlement period boundaries, promotion windows, allocation windows, scheduled service dates — are ISO 8601 date strings in `YYYY-MM-DD` form. Instants — scan timestamps, price effectivity, certification moments — are ISO 8601 UTC datetimes with three fractional digits. Two interval conventions likewise coexist and must not be confused: allocation and settlement windows are half-open, including their start and excluding their end, while promotion windows and seasonal setup windows are closed, including both endpoints.

### 2.6. The Logical Clock and the Time Sweep

The system never consults wall-clock time. A logical clock governs every temporal decision — window membership, effectivity, expiry, and every recorded timestamp. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A `JobberAdmin` may advance it through a test-driving capability that accepts a target instant `to_iso8601` and responds with the resulting `current_utc` plus `swept_transitions`, a count of the automatic transitions the advance triggered.

Advancing the clock fires a time sweep across six families of resources. A scheduled service visit whose `scheduled_date` has passed without a check-in becomes `MISSED`. A scheduled promotion whose window now covers the clock date becomes `ACTIVE`, and an active or suspended promotion whose `end_date` has passed becomes `ENDED`. An approved markdown authorization still unapplied fourteen days after its approval becomes `EXPIRED`. An active-season seasonal set whose `teardown_deadline` has passed becomes `TEARDOWN_DUE`. A planned space allocation whose window has opened becomes `ACTIVE`, provided its agreement is `ACTIVE`. And a scheduled price directive whose `effective_from` has been reached becomes `EFFECTIVE`, superseding whatever directive was previously in force for the same agreement and product.

### 2.7. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control, each keyed to the `version` of a parent entity the client must have read before writing. Amending an agreement's commercial terms requires the request to carry `expected_store_agreement_version` equal to the agreement's current `version`. Creating a price directive likewise requires `expected_store_agreement_version`, because a creation supersedes the currently effective directive and bumps the agreement's version. Finalizing a settlement statement requires `expected_settlement_statement_version` equal to the statement's current `version`. Certifying an audit count requires `expected_audit_count_version` equal to the audit's current `version`. In all four cases the field is non-optional, and a mismatch — the parent entity's version has advanced since the client last observed it, for instance because a price-directive supersede or a shrink-ratio recompute intervened — is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client always acts on the state it actually verified. Endpoints not named above take no version field at all.

### 2.8. Validation Precedence

Every request is evaluated against a fixed precedence ladder, and the first failing check wins — a failure higher on the ladder masks every check below it. The ladder runs in this order:

1. Authentication context: the `X-User-ID` and `X-User-Role` headers must be present and non-empty, failing with `ERR_MISSING_AUTH_CONTEXT` (HTTP 400).
2. Role authorization: the presented role must appear in the endpoint's role list, failing with `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. Path existence: resource identifiers in the URL path must exist, validated strictly left-to-right so that the first missing identifier produces `ERR_NOT_FOUND` (HTTP 404).
4. Body references: foreign-key references in the request body — `program_id`, `store_id`, `product_id`, `route_id`, `store_agreement_id`, `void_of_event_id` — must resolve to existing resources, failing with `ERR_NOT_FOUND`.
5. Shape: required fields must be present and well-typed, failing with `ERR_INVALID_REQUEST` (HTTP 400).
6. Enumerations: enum fields must carry a declared member, failing with `ERR_INVALID_ENUM` (HTTP 422).
7. Numeric ranges: `quantity`, `facings`, and `units` must be at least 1; percentage fields must lie between 0 and 1 inclusive; promotion depth must be greater than 0 and at most 0.50; prices must be at least 1 cent. Violations fail with `ERR_RANGE_INVALID` (HTTP 422).
8. Ownership identity: a `RetailerManager` must match the acting agreement's store, failing with `ERR_STORE_MANAGER_MISMATCH` (HTTP 403); a `RouteDriver` must match the visit route's assigned driver, failing with `ERR_DRIVER_NOT_ASSIGNED` (HTTP 403).
9. From-state validity: the target resource must be in a state from which the requested transition exists, failing with `ERR_INVALID_STATE` (HTTP 409).
10. Terminality: an action addressed to a resource already in a terminal state fails with `ERR_ALREADY_TERMINAL` (HTTP 409).
11. Optimistic concurrency: the four OCC-guarded writes of §2.7 compare their expected version field to the parent's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412).
12. Segregation of duties: audit certification and settlement approval enforce the actor-separation rules of §2.9, failing with `ERR_SOD_CERTIFIER_IS_COUNTER` or `ERR_SOD_APPROVER_IS_CREATOR` (HTTP 403).

Only after all twelve universal stages pass do the domain rules evaluate, again in a fixed order. Temporal window rules come first: window endpoint ordering (`ERR_WINDOW_INVALID`, HTTP 422), day-of-visit check-in (`ERR_VISIT_WINDOW_CLOSED`, HTTP 409), seasonal setup windows (`ERR_SEASONAL_WINDOW_NOT_OPEN`, HTTP 409), settlement period closure (`ERR_SETTLEMENT_PERIOD_NOT_CLOSED`, HTTP 409), same-program space overlap (`ERR_SPACE_WINDOW_OVERLAP`, HTTP 409), and promotion minimum gaps (`ERR_PROMO_GAP_VIOLATION`, HTTP 409). Uniqueness constraints follow: one live agreement per program-and-store (`ERR_AGREEMENT_EXISTS`, HTTP 409), `sku` unique within a program (`ERR_SKU_EXISTS`, HTTP 409), `client_event_id` unique per agreement (`ERR_DUPLICATE_SCAN_EVENT`, HTTP 409), and one statement per agreement-and-period (`ERR_SETTLEMENT_ALREADY_EXISTS`, HTTP 409). Business constraints come next: cross-program category exclusivity (`ERR_CATEGORY_EXCLUSIVE_CONFLICT`, HTTP 409), facing capacity (`ERR_SPACE_CAPACITY_EXCEEDED`, HTTP 422), the retail price floor (`ERR_PRICE_BELOW_FLOOR`, HTTP 422), program membership of products (`ERR_PRODUCT_NOT_IN_PROGRAM`, HTTP 422), discontinued products (`ERR_PRODUCT_DISCONTINUED`, HTTP 409), route program alignment (`ERR_ROUTE_PROGRAM_MISMATCH`, HTTP 422), and seasonal allocation coverage (`ERR_SEASONAL_ALLOCATION_MISSING`, HTTP 409). Referential-state requirements follow those: the agreement must be active where required (`ERR_AGREEMENT_NOT_ACTIVE`, HTTP 409), finalization needs certified audits (`ERR_AUDIT_NOT_CERTIFIED`, HTTP 409), and void targets must be valid (`ERR_VOID_TARGET_INVALID`, HTTP 409). Fiscal caps close the ladder: the restock value cap (`ERR_RESTOCK_VALUE_CAP_EXCEEDED`, HTTP 409), the markdown credit cap (`ERR_MARKDOWN_CAP_EXCEEDED`, HTTP 409), and the minimum payout (`ERR_PAYOUT_BELOW_MINIMUM`, HTTP 409). So, for example, a price-directive creation carrying both a stale agreement version and a below-floor price is rejected with `ERR_STALE_VERSION`, because optimistic concurrency sits eleven rungs above the price floor.

### 2.9. Segregation of Duties

Two workflows are adjudicative and therefore separate the actor who produces a record from the actor who vouches for it. An audit count records the auditor who submitted it as `counted_by_user_id`; certification must come from a `JobberAdmin` whose `X-User-ID` differs from `counted_by_user_id`, failing with `ERR_SOD_CERTIFIER_IS_COUNTER` (HTTP 403). A settlement statement records its generator as `created_by_user_id`; approval must come from a `JobberAdmin` whose `X-User-ID` differs from `created_by_user_id`, failing with `ERR_SOD_APPROVER_IS_CREATOR` (HTTP 403). The role assignments themselves enforce the first half of the separation: a `FieldAuditor` can start and submit audits but holds no certification right anywhere in the API, and a `JobberFinance` operator can generate, finalize, revise, and pay statements but holds no approval right.

### 2.10. Atomic Cascades and Derived State

Several operations mutate more than one resource at once: certifying an audit rewrites inventory balances, accumulates agreement shrink counters, can suspend the agreement, and cancels the agreement's scheduled visits; terminating an agreement closes its allocations and cancels its visits; confirming a service visit rewrites balances and accumulates delivery counters on the agreement. All such side effects are atomic within the triggering request — a cascade either applies in full or the request fails outright. Every mutation, including each hop of a cascade, refreshes the mutated resource's `updated_at` and increments its `version` by one, which is precisely what allows the optimistic concurrency checks of §2.7 to observe cascades initiated by other actors. Derived fields — stock postures, cumulative ratios, frozen totals — are recomputed by the mutations that feed them and are never accepted as client input.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program: Programs, Stores, and the Consignment Agreement

A `JobberAdmin` begins by creating a **Program**, the commercial umbrella for a consignment relationship. A program carries a display `name` and three tunable policies: `promo_min_gap_days`, the minimum number of full days that must separate two non-cancelled promotions on the same program and product, defaulting to 1; `min_payout_cents`, the smallest net payable a settlement statement may reach and still be disbursable, defaulting to 5000; and `default_settlement_cadence`, one of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`, defaulting to `WEEKLY` and inherited by agreements that do not override it. A program is born `ACTIVE` and may later be archived, moving it to `ARCHIVED`; archiving is permitted only when no live agreements remain under the program.

Stores are the host locations. A **Store** is created with a display `name`, a `store_code` that must be unique across all stores, and `total_facings`, the store's total rack facing capacity, which must be at least 1. A store is born `ACTIVE` and may be closed, moving to `CLOSED`, only when no live agreements remain at the store.

The **StoreAgreement** is the junction that joins a program to a store and carries every commercial term of the relationship. A `JobberAdmin` creates one by supplying `program_id`, `store_id`, `base_margin_pct` (the retailer's base margin fraction, strictly between 0 and 1), `shrink_retailer_share_pct` (the retailer's share of chargeable shrink value, between 0 and 1 inclusive), and `restock_value_cap_cents` (the maximum jobber-cost value of restock merchandise a driver may submit in one service visit). A dozen further terms carry defaults and may be overridden at creation: `tier1_threshold_cents` (default 100000) with `tier1_uplift_pct` (default 0.01); `tier2_threshold_cents` (default 200000) with `tier2_uplift_pct` (default 0.02); the computed-margin floor `min_margin_pct` (default 0.15) and ceiling `max_margin_pct` (default 0.40); `free_allowance_pct` (default 0.01), the fraction of scanned units since the last audit that is forgiven before shrink is charged; `shrink_suspend_ratio` (default 0.02), the cumulative shrink ratio at which the agreement suspends itself; `shrink_valuation_mode`, either `JOBBER_COST` or `BLENDED_RETAIL`, defaulting to `JOBBER_COST`; `estimated_shrink_rate` (default 0.0), the provisional shrink estimate per scanned unit; `markdown_liability`, one of `JOBBER`, `RETAILER`, or `SHARED`, defaulting to `SHARED`; `markdown_jobber_share_pct` (default 0.5), which is forced to 1.0 when liability is `JOBBER` and to 0.0 when it is `RETAILER`; `markdown_cap_pct_of_gross` (default 0.08); `settlement_cadence` (default `WEEKLY`); and `service_frequency_days` (default 7). The system records the creator's header identity in `created_by_user_id`.

Uniqueness is enforced across the pair: at most one agreement for a given `program_id` and `store_id` may exist in `DRAFT`, `PENDING_ACCEPTANCE`, `ACTIVE`, or `SUSPENDED`; a second creation attempt against the same pair while one is live is rejected with `ERR_AGREEMENT_EXISTS`. An agreement is born `DRAFT`. Submission by a `JobberAdmin` moves `DRAFT` to `PENDING_ACCEPTANCE`. The retailer then decides: acceptance by a `RetailerManager` moves the agreement to `ACTIVE` and stamps `activated_at` with the logical clock — that instant anchors settlement period 0 — while rejection, which may carry an optional `reason`, moves it to `REJECTED`, a terminal state. Both decisions require the manager's `X-User-ID` to equal the agreement's `store_id`, failing with `ERR_STORE_MANAGER_MISMATCH`.

While `ACTIVE`, an agreement may be suspended by a `JobberAdmin`, moving to `SUSPENDED`; the same transition fires automatically when a certified audit pushes the cumulative shrink ratio to the threshold described in §3.7. Suspension cancels every still-`SCHEDULED` service visit of the agreement, moving each to `CANCELLED`. Resumption by a `JobberAdmin` returns a `SUSPENDED` agreement to `ACTIVE`. Termination by a `JobberAdmin` moves an `ACTIVE` or `SUSPENDED` agreement to `TERMINATED`, the other terminal state, but only when no settlement statement of the agreement sits in `PROVISIONAL`, `FINALIZED`, `DISPUTED`, or `APPROVED`, and no seasonal set sits in `PLANNED`, `SET_IN_PROGRESS`, `SET_COMPLETE`, `ACTIVE_SEASON`, or `TEARDOWN_DUE` — otherwise the termination is rejected with `ERR_INVALID_STATE`. Termination closes every `ACTIVE` space allocation of the agreement and cancels every `SCHEDULED` visit.

Commercial terms are not frozen at creation. A `JobberAdmin` may amend `base_margin_pct`, `shrink_retailer_share_pct`, `free_allowance_pct`, `estimated_shrink_rate`, `restock_value_cap_cents`, `markdown_jobber_share_pct`, or `shrink_suspend_ratio` on an existing agreement; the amendment is OCC-guarded under §2.7, so the request must carry `expected_store_agreement_version` matching the agreement's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`. Because price-directive creation and audit certification also advance the agreement's `version`, an amender who read the agreement before such an event must re-read before writing.

Three cumulative counters live on the agreement and are maintained by the workflows of §3.5 and §3.7: `cumulative_delivered_units`, the sum of restock units confirmed across all of the agreement's visits; `cumulative_shrink_units`, the sum of variance units posted by certified audits, counting all physical shrink including units later forgiven by the free allowance; and `cumulative_shrink_ratio`, the shrink units divided by the delivered units, defined as 0.0 while nothing has been delivered. Agreement listings may be filtered by `program_id`, `store_id`, or `status`.

### 3.2. Catalog and Price Maintenance: Products and Price Directives

Within a program, a `JobberAdmin` registers the **Product** catalog. Each product belongs to a `program_id` and carries a `sku` that must be unique within that program — a duplicate is rejected with `ERR_SKU_EXISTS` — plus a display `name`, the `jobber_cost_cents` unit cost that anchors restock caps and cost-based shrink valuation, the `min_retail_cents` retail price floor, and `units_per_facing`, the number of units that fit in one rack facing, which doubles as the reorder point for inventory balances. All three numeric fields must be at least 1. A product is born `ACTIVE`; a later update may revise `jobber_cost_cents` or `min_retail_cents`, or move `status` to `DISCONTINUED`. Product listings may be filtered by `program_id` or `status`.

Retail prices are maintained, not improvised. A **PriceDirective** binds a `store_agreement_id` and `product_id` to a `price_cents` that takes effect at `effective_from`. Creation is one of the OCC-guarded writes of §2.7: the request must carry `expected_store_agreement_version` equal to the agreement's current `version`, failing with `ERR_STALE_VERSION` otherwise. Beyond concurrency, creation requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the product to belong to the agreement's program (`ERR_PRODUCT_NOT_IN_PROGRAM` otherwise), the product to still be `ACTIVE` (`ERR_PRODUCT_DISCONTINUED` otherwise), and the price to meet or exceed the product's `min_retail_cents` (`ERR_PRICE_BELOW_FLOOR` otherwise).

A directive is created-with-supersede. When `effective_from` is at or before the logical clock, the new directive is born `EFFECTIVE` and whatever directive was previously `EFFECTIVE` for the same agreement and product moves to `SUPERSEDED`, stamped with a `superseded_at` equal to the clock. When `effective_from` lies in the future, the directive is born `SCHEDULED` and waits; the time sweep of §2.6 later moves it to `EFFECTIVE` once the clock reaches it, again superseding the incumbent. Either form of creation advances the agreement's `version` by one, which is why amending terms and setting prices serialize against each other through §2.7. Directive listings may be filtered by `store_agreement_id`, `product_id`, or `status`.

### 3.3. Promotions: Depth, Funding, and the Minimum Gap

A **Promotion** discounts a product's directive price for a closed calendar window. A `JobberAdmin` creates one with `program_id`, `product_id`, a display `name`, a `depth_pct` discount depth (greater than 0 and at most 0.50), a `jobber_funding_pct` declaring what share of the discount the jobber funds (between 0 and 1 inclusive; the remainder is retailer-absorbed), and `start_date` and `end_date`, both inclusive — a promotion window is a closed interval, and `start_date` after `end_date` is rejected with `ERR_WINDOW_INVALID`.

Creation also enforces gap discipline, and this check is deliberately stricter than the space-allocation overlap rule of §3.4. For every non-`CANCELLED` promotion already on the same program and product, the candidate window must clear the existing window by strictly more than `promo_min_gap_days` full days: either the candidate's `start_date` falls later than the existing window's `end_date` plus the gap, or the candidate's `end_date` falls earlier than the existing window's `start_date` minus the gap. A candidate that fails this separation against any such promotion is rejected with `ERR_PROMO_GAP_VIOLATION`. With the default one-day gap and an existing promotion ending on 2026-08-10, a candidate starting 2026-08-11 is rejected — one day of separation does not exceed the required one full day — while a start of 2026-08-12 is accepted.

A promotion is born `DRAFT`. Scheduling by a `JobberAdmin` moves `DRAFT` to `SCHEDULED`, refusing an inverted window with `ERR_WINDOW_INVALID`; when the window already covers the clock date at scheduling time, the promotion instead lands directly in `ACTIVE`. The time sweep moves `SCHEDULED` promotions to `ACTIVE` once the clock date falls within the window, and moves `ACTIVE` or `SUSPENDED` promotions to `ENDED` once the clock passes `end_date`. A `JobberAdmin` may suspend an `ACTIVE` promotion (`ACTIVE` to `SUSPENDED`) and resume it (`SUSPENDED` to `ACTIVE`); resumption is permitted only while the clock date still lies within the promotion window, failing with `ERR_WINDOW_INVALID` otherwise. Ending by a `JobberAdmin` moves `ACTIVE` or `SUSPENDED` to `ENDED`, and cancellation moves any of `DRAFT`, `SCHEDULED`, `ACTIVE`, or `SUSPENDED` to `CANCELLED`. Both `ENDED` and `CANCELLED` are terminal. Promotion listings may be filtered by `program_id`, `product_id`, or `status`.

### 3.4. Shelf Space, Category Exclusivity, and Seasonal Sets

Shelf space is allocated per agreement in category windows. A **SpaceAllocation** is created by a `JobberAdmin` with `store_agreement_id`, a `category` drawn from `SNACKS`, `BEVERAGES`, `IMPULSE`, `HOUSEWARES`, `SEASONAL`, or `PERSONAL_CARE`, a `facings` count of at least 1, and a half-open window from `window_start_date` (inclusive) to `window_end_date` (exclusive). At creation the system denormalizes `store_id` from the agreement onto the allocation, and that denormalized value drives every overlap and capacity check below. An inverted window — start not before end under the half-open convention — is rejected with `ERR_WINDOW_INVALID`. A window covering the clock date at creation lands `ACTIVE`; a future window lands `PLANNED` and is opened by the time sweep, provided the agreement is `ACTIVE` at that moment.

Three independent gates guard creation, evaluated in the precedence order of §2.8: same-program overlap first, cross-program exclusivity second, physical capacity third. Two half-open windows intersect when each starts before the other ends; windows that merely touch — one beginning on the very day the other ends — do not intersect. The overlap gate rejects a candidate whose window intersects another non-closed allocation of the same store, same category, and same program with `ERR_SPACE_WINDOW_OVERLAP`. The exclusivity gate enforces category exclusivity across programs: a candidate whose window intersects an allocation of the same store and same category owned by a different program is rejected with `ERR_CATEGORY_EXCLUSIVE_CONFLICT`. The capacity gate sums the `facings` of every overlapping allocation of the store in `PLANNED` or `ACTIVE` status, adds the candidate's `facings`, and rejects with `ERR_SPACE_CAPACITY_EXCEEDED` only when that committed total strictly exceeds the store's `total_facings` — a commitment exactly equal to capacity is allowed. An allocation in `PLANNED` or `ACTIVE` may be closed by a `JobberAdmin`, moving it to `CLOSED`; agreement termination closes `ACTIVE` allocations automatically. Allocation listings may be filtered by `store_agreement_id`, `category`, or `status`.

A **SeasonalSet** reserves a themed display against one of those allocations. A `JobberAdmin` plans one with `store_agreement_id`, a display `theme`, the `category` whose space the set occupies, `allocated_facings` of at least 1, a closed setup window from `set_window_start` to `set_window_end` (both inclusive; inverted windows fail with `ERR_WINDOW_INVALID`), and a `teardown_deadline`, the last grace-free day for removal. The set is born `PLANNED`. A `RouteDriver` begins setup — `PLANNED` to `SET_IN_PROGRESS` — only while the clock date lies within the closed setup window, failing with `ERR_SEASONAL_WINDOW_NOT_OPEN` otherwise, and completes setup — `SET_IN_PROGRESS` to `SET_COMPLETE` — only when an `ACTIVE` space allocation exists for the agreement in the set's category with facings at least equal to `allocated_facings`, failing with `ERR_SEASONAL_ALLOCATION_MISSING` otherwise. Activation by a `JobberAdmin` moves `SET_COMPLETE` to `ACTIVE_SEASON`.

Teardown is where money moves. Once the clock passes `teardown_deadline`, the sweep moves `ACTIVE_SEASON` to `TEARDOWN_DUE`. A `RouteDriver` tears the set down from either `ACTIVE_SEASON` or `TEARDOWN_DUE`, landing in `TORN_DOWN`; the system stamps `actual_teardown_date` with the clock date and computes `penalty_cents`. The penalty grants a two-day grace period: the days late are the calendar days between `teardown_deadline` and `actual_teardown_date`, minus two, floored at zero; the penalty is the days late multiplied by 2500 cents per day, capped at 100000 cents. A deadline of 2026-08-20 with teardown on 2026-08-25 is five days late, three after grace, and costs 7500 cents. Finally, reconciliation by a `JobberAdmin` moves `TORN_DOWN` to `RECONCILED`, the terminal state, at which point the penalty becomes eligible for the settlement statement whose window contains the reconciliation date — the mechanism by which §3.9 collects it. Seasonal set listings may be filtered by `store_agreement_id` or `status`.

### 3.5. Routes and the Service Visit Cycle

Field service runs on routes. A **Route** is created by a `JobberAdmin` under a `program_id`, with a display `name`, an `assigned_driver_id` (an opaque driver identifier — a `RouteDriver` whose `X-User-ID` equals it is the only identity permitted to execute the route's visits), and a nominal `service_frequency_days` cadence defaulting to 7. A route is born `ACTIVE` and may later be updated — driver reassignment, cadence change, or `status` moved to `INACTIVE`. Route listings may be filtered by `program_id` or `status`.

A **ServiceVisit** joins a route to an agreement on a date. Scheduling one takes `route_id`, `store_agreement_id`, and `scheduled_date`; the agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise) and must belong to the route's program (`ERR_ROUTE_PROGRAM_MISMATCH` otherwise). A visit is born `SCHEDULED`. Visit listings may be filtered by `route_id`, `store_agreement_id`, or `status`.

The visit cycle enforces day-of discipline. Check-in — `SCHEDULED` to `CHECKED_IN` — is performed by the assigned `RouteDriver`, requires the logical clock date to equal `scheduled_date` exactly (a visit attempted on any other day is rejected with `ERR_VISIT_WINDOW_CLOSED`), and requires the agreement to still be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise). A visit that is never checked in is swept to `MISSED` once the clock date passes its `scheduled_date`.

Once checked in, the driver submits counts: a `lines` payload of per-product entries, each naming a `product_id` with `counted_units` on the shelf and `restock_units` being delivered. Every product named must belong to the agreement's program (`ERR_PRODUCT_NOT_IN_PROGRAM` otherwise). Submission is gated by the agreement's fiscal cap: the sum, across lines, of each line's `restock_units` multiplied by its product's `jobber_cost_cents` may not exceed `restock_value_cap_cents`, and a submission that breaks the cap is rejected with `ERR_RESTOCK_VALUE_CAP_EXCEEDED`. A passing submission moves the visit to `COUNTS_SUBMITTED` and freezes the payload into `submitted_lines`, computing `total_counted_units` and `total_restock_units` as the line sums, `total_variance_units` as the sum over lines of counted units minus the book on-hand at submit (informational only — visits never charge shrink), and `applied_restock_value_cents` as the capped value just described.

The retailer then rules. Confirmation by the store's `RetailerManager` — `COUNTS_SUBMITTED` to `CONFIRMED`, a terminal state — requires the manager identity match and an `ACTIVE` agreement. Confirmation rewrites the inventory ledger: for each line, the balance for that agreement and product is created if absent, and its `on_hand_units` is set to `counted_units` plus `restock_units` — the physical count resets the book — while `lifetime_delivered_units` grows by the line's `restock_units` and the stock posture of §3.6 is recomputed. The agreement absorbs the delivery: `cumulative_delivered_units` grows by the visit's `total_restock_units`, `cumulative_shrink_ratio` is recomputed, and both the visit's and the agreement's versions advance. Alternatively, the manager may dispute — `COUNTS_SUBMITTED` to `DISPUTED`, with an optional `reason`. A disputed visit returns to the driver through recount — `DISPUTED` back to `CHECKED_IN` — which clears `submitted_lines` and every computed total so the driver may count and submit afresh. A `JobberAdmin` may cancel a `SCHEDULED` visit outright, and suspension or termination of the agreement cancels its `SCHEDULED` visits as a cascade; `MISSED` and `CANCELLED` are terminal alongside `CONFIRMED`.

### 3.6. Scan-Based Trading and the Inventory Ledger

Trading is settled from scans, not deliveries. The retailer's `RetailerManager` — whose identity must match the agreement's store — ingests a **ScanEvent** with `store_agreement_id`, `product_id`, an `event_type` of `SALE`, `RETURN`, or `VOID`, a `quantity` of at least 1, the POS timestamp `scanned_at`, and a `client_event_id` that serves as the retailer's idempotency key: a `client_event_id` already ingested for the same agreement is rejected with `ERR_DUPLICATE_SCAN_EVENT`. A `VOID` event additionally requires `void_of_event_id` referencing the scan it reverses, with `quantity` equal to the target's.

Ingest resolves synchronously. A scan lands `MATCHED` when all of the following hold: the agreement is `ACTIVE`, the product belongs to the agreement's program, and an `EFFECTIVE` price directive exists for the agreement and product with `effective_from` no later than `scanned_at`. If any of those conditions fails, the scan is still persisted but lands `UNMATCHED`: no price resolution occurs, `unit_price_cents` remains unset, `line_value_cents` and `jobber_funding_cents` carry no value, `is_promo_priced` is false, and nothing touches inventory. A `JobberAdmin` may later resolve an `UNMATCHED` scan once the master data has been fixed; resolution re-runs the match and, when the conditions now hold, applies exactly the same valuation, inventory, and reorder effects as a natively matched scan. The exception is the void family: a `VOID` whose target is missing, `UNMATCHED`, itself a `VOID`, on a different agreement, or of mismatched quantity is not persisted at all — it is rejected outright with `ERR_VOID_TARGET_INVALID`.

Price resolution for a matched scan proceeds as follows. The base price is the `price_cents` of the effective directive. The system then looks for a promotion on the scan's program and product that is `ACTIVE` with the `scanned_at` calendar date inside its closed window; when several match, the eligible one is the greatest `depth_pct`, breaking ties toward the earliest `start_date` and then the earliest `created_at`. When a promotion applies, the promo price is the base price multiplied by one minus `depth_pct`, rounded half-up to a whole cent, and the scan's `unit_price_cents` is the lesser of the base price and that promo price; `is_promo_priced` is true exactly when the resolved unit price lands below the base. With no promotion, the unit price is simply the base price and `is_promo_priced` is false. Line value follows the event type: a `SALE` contributes its unit price times `quantity` as positive `line_value_cents`; a `RETURN` contributes the same magnitude negated; a `VOID` copies its target's `unit_price_cents` and `is_promo_priced` verbatim and contributes the negation of the target's `line_value_cents`.

Promo funding is split per line, and the rounding order is pinned. For each promo-priced line, the per-unit discount is the directive price minus the resolved unit price; the line's `jobber_funding_cents` is that per-unit discount multiplied by the line `quantity` and by the promotion's `jobber_funding_pct`, rounded half-up to a whole cent. Settlement totals sum these already-rounded line figures. Summing raw discounts first and rounding once at the end is forbidden, because the orders genuinely diverge: at a directive price of 101 cents with depth 0.25 and half jobber funding, two quantity-1 lines fund 13 plus 13 — 26 cents — under the pinned order, where sum-then-round would yield 25.

A matched scan also moves the consignment ledger. The **InventoryBalance** for the scan's agreement and product is created on first use — the first confirmed restock or the first matched scan for the pair — and tracks `on_hand_units`, the consignment units the jobber still owns at the store, alongside lifetime counters: `lifetime_delivered_units` from confirmed restocks, `lifetime_scanned_units` from net matched sales, `lifetime_customer_return_units` from return scans put back on the shelf, `lifetime_shrink_units` posted by certified audits, and `lifetime_rma_units` pulled by vendor returns. The balance obeys one invariant: on hand equals delivered minus scanned plus customer returns minus shrink minus vendor returns, and it may legitimately go negative when unscanned shelf stock sells through. A `SALE` decrements on-hand by its `quantity` and adds to `lifetime_scanned_units`; a `RETURN` increments on-hand and adds to `lifetime_customer_return_units`; a `VOID` reverses its target's units and counters. Each balance's `reorder_point_units` equals its product's `units_per_facing`, and its derived `stock_posture` reads `DEPLETED` when on-hand is zero or below, `LOW` when on-hand is positive but no greater than the reorder point, and `NORMAL` above it. Balance listings may be filtered by `store_agreement_id`, `product_id`, or `stock_posture`; scan listings may additionally be filtered by `event_type`, `status`, `void_of_event_id`, or `settled_in_statement_id`.

The reorder cascade closes the loop from shelf to route. When a matched scan leaves a balance's `on_hand_units` at or below `reorder_point_units`, the system selects the agreement's `SCHEDULED` service visit with the earliest `scheduled_date` on or after the clock date, breaking ties toward the earliest visit `created_at`, and sets that visit's `auto_restock_flag` to true with `suggested_restock_units` equal to twice the reorder point minus the current on-hand, floored at zero — enough to restock to two full reorder points. When no scheduled visit qualifies, nothing is mutated and no error is raised; the visit mutation itself recomputes nothing further.

### 3.7. Shrink Audits: Counting, Certification, and the Suspension Cascade

Shrink is adjudicated by physical audit. A `JobberAdmin` schedules an **AuditCount** against a `store_agreement_id` with a `scope` of `FULL` or `CATEGORY`; a `category` from the six-value rack taxonomy is required exactly when the scope is `CATEGORY`. The audit is born `SCHEDULED`. A `FieldAuditor` starts it — `SCHEDULED` to `IN_PROGRESS`, requiring an `ACTIVE` agreement (`ERR_AGREEMENT_NOT_ACTIVE` otherwise) — and later submits it with a `counted_lines` payload of `product_id` and `counted_units` pairs. Submission moves the audit to `SUBMITTED` and freezes the evidentiary record: `counted_lines` is locked in, `counted_by_user_id` records the auditor's identity, and `submitted_at` records the logical clock.

Submission also freezes the unit side of the shrink computation. `scanned_units_since_last_audit` counts the matched `SALE` units of the audited products with `scanned_at` at or after the previous certified or locked audit's `submitted_at` — or at or after agreement activation when no prior audit exists — and strictly before this audit's `submitted_at`. `variance_units` is the sum over counted lines of book on-hand at submit minus counted units, so a positive value is shrink; products absent from `counted_lines` are never varianced. `free_allowance_units` is `scanned_units_since_last_audit` multiplied by the agreement's `free_allowance_pct`, rounded half-up to a whole unit — ordinary handling loss the jobber forgives. `chargeable_units` is the variance minus the free allowance, floored at zero.

The retailer may dispute a submitted audit — `SUBMITTED` to `DISPUTED`, with an optional `reason`, under the usual store-identity rule — and a `JobberAdmin` may then order a recount, returning `DISPUTED` to `IN_PROGRESS` and clearing the frozen lines, the counter identity, and every frozen computed field so the auditor counts afresh.

Certification is the adjudicative act, guarded by both optimistic concurrency and segregation of duties. The certifying `JobberAdmin` must carry `expected_audit_count_version` equal to the audit's current `version` — a stale value means a dispute-and-recount cycle replaced the frozen counts since the certifier last read them, and the request is rejected with `ERR_STALE_VERSION` — and the certifier's identity must differ from `counted_by_user_id`, failing with `ERR_SOD_CERTIFIER_IS_COUNTER`. Certification moves `SUBMITTED` to `CERTIFIED`, stamps `certified_at` and `certified_by_user_id`, and prices the variance. The valuation variant is selected by the agreement's `shrink_valuation_mode`: under `JOBBER_COST`, `valuation_unit_cents` is simply the product's `jobber_cost_cents`; under `BLENDED_RETAIL`, it is sixty percent of the jobber cost plus forty percent of the effective directive price for the agreement and product at certify time, rounded half-up to a whole cent — strictly higher whenever retail exceeds cost, so a cost of 100 cents with a directive price of 200 cents values at 100 under one variant and 140 under the other. `variance_value_cents` is `chargeable_units` multiplied by `valuation_unit_cents`, and `retailer_charge_cents` is that value multiplied by the agreement's `shrink_retailer_share_pct`, rounded half-up; the jobber absorbs the remainder.

Certification then cascades, atomically. First, each counted line rewrites its inventory balance: `on_hand_units` is set to the counted figure and `lifetime_shrink_units` grows by the book-minus-counted difference, floored at zero. Second, the agreement accumulates: `cumulative_shrink_units` grows by the audit's `variance_units`, floored at zero, `cumulative_shrink_ratio` is recomputed, and the agreement's `version` advances. Third, the suspension posture evaluates: when an `ACTIVE` agreement's recomputed ratio meets or exceeds its `shrink_suspend_ratio` — exactly equal suspends — the agreement moves from `ACTIVE` to `SUSPENDED`, which in turn cancels every still-`SCHEDULED` service visit. The audit's own `version` advances as well. Finally, a certified audit may be locked — `CERTIFIED` to `LOCKED`, the terminal state — either explicitly by a `JobberAdmin` or automatically when a settlement statement finalizes with the audit inside its window, as §3.9 describes. Audit listings may be filtered by `store_agreement_id` or `status`.

### 3.8. Markdown Authorizations and Vendor Returns

Price protection and stock removal run through a **MarkdownAuthorization**. A `JobberAdmin` requests one against a `store_agreement_id` and `product_id`, choosing an `auth_type` of `MARKDOWN` — a price-protection credit with no unit movement — or `RETURN_TO_VENDOR` — units pulled from the shelf with no credit. The request carries `units` of at least 1; for `MARKDOWN` it must also carry `markdown_price_cents`, the new clearance price, which may be zero but must sit strictly below the product's current maintained directive price. The authorization is born `REQUESTED`.

The retailer's `RetailerManager` rules on the request under the store-identity rule: approval moves `REQUESTED` to `APPROVED` and stamps `approved_at` with the clock; rejection, optionally carrying a `reason`, moves it to `REJECTED`, terminal. Approval starts a fourteen-day fuse — an approved authorization still unapplied when the clock date passes fourteen days after the `approved_at` date is swept to `EXPIRED`, also terminal.

Application by a `JobberAdmin` moves `APPROVED` to `APPLIED` and differs by type. For `MARKDOWN`, the credit is the gap between the directive price in force at apply time and `markdown_price_cents`, multiplied by `units` and by the jobber's share — 1.0 when the agreement's `markdown_liability` is `JOBBER`, 0.0 when `RETAILER`, and the agreement's `markdown_jobber_share_pct` when `SHARED` — rounded half-up to a whole cent into `credit_cents`. The credit is capped per period: it may not exceed the agreement's `markdown_cap_pct_of_gross` multiplied by the gross scanned sales of the settlement period containing the clock's current date, rounded half-up, and an application breaking the cap is rejected with `ERR_MARKDOWN_CAP_EXCEEDED`. No units move for a markdown. For `RETURN_TO_VENDOR`, the balance must physically cover the pull: `on_hand_units` below `units` is rejected with `ERR_RANGE_INVALID`; otherwise on-hand falls by `units`, `lifetime_rma_units` grows by `units`, and `credit_cents` is 0. Either way, `applied_at` records the clock and becomes the credit's settlement-window membership key. Markdown listings may be filtered by `store_agreement_id`, `product_id`, or `status`.

### 3.9. Settlement Statements: From Provisional to Paid

Settlement converts the period's scans, audits, markdowns, and penalties into a single payable. Periods anchor at the agreement's `activated_at` date: period length is 7 days under `WEEKLY`, 14 under `BIWEEKLY`, or one calendar month under `MONTHLY`; period `period_index` zero starts at the anchor, each period starts where the previous ends, and every window is half-open — `period_start` inclusive, `period_end` exclusive. With a weekly cadence anchored on 2026-08-01, period 0 runs from 2026-08-01 up to but not including 2026-08-08. A scan timestamped exactly at a period's end belongs to the next period.

A `JobberFinance` operator generates a **SettlementStatement** by naming `store_agreement_id` and a zero-based `period_index`, unique per agreement — a second statement for the same pair is rejected with `ERR_SETTLEMENT_ALREADY_EXISTS`. Generation requires an `ACTIVE` agreement (`ERR_AGREEMENT_NOT_ACTIVE`) and a period that has begun, its `period_start` no later than the clock date (`ERR_SETTLEMENT_PERIOD_NOT_CLOSED` otherwise). The statement is born `PROVISIONAL`, records the generator in `created_by_user_id`, and computes every money field under the `PROVISIONAL` variant, recorded in `variant_used`. Statement listings may be filtered by `store_agreement_id` or `status`.

The money fields evaluate in a pinned top-down order. First, `gross_scanned_sales_cents` sums `line_value_cents` over the matched scans whose `scanned_at` falls in the window. Second, `scanned_units` nets the window's unit movement — sales add, returns subtract, and voids reverse their target's quantity — and `promo_scan_units` counts the units scanned at promo price. Third, `promo_jobber_funding_cents` sums the window scans' per-line `jobber_funding_cents`, rounded per line at ingest per §3.6 and merely added here. Fourth, the markdown credit: the raw figure sums `credit_cents` of `MARKDOWN` authorizations applied in the window, and `markdown_credit_cents` is the lesser of that raw figure and the agreement's `markdown_cap_pct_of_gross` multiplied by the gross sales of step one, rounded half-up — the cap is keyed on gross, never on net. Fifth, `net_sales_cents` is gross minus the markdown credit. Sixth, the margin: when net sales reach or exceed `tier2_threshold_cents` the uplift is `tier2_uplift_pct`; otherwise, when they reach or exceed `tier1_threshold_cents`, it is `tier1_uplift_pct`; otherwise there is no uplift — the tiers replace rather than stack. The promo drag then applies: the promo share is `promo_scan_units` divided by `scanned_units`, taken as 0.0 when `scanned_units` is zero, and a share strictly greater than 0.30 subtracts a drag of 0.01. The resulting `margin_pct` is `base_margin_pct` plus the tier uplift minus the drag, clamped so it never falls below `min_margin_pct` nor exceeds `max_margin_pct`; it is held as an exact decimal, unrounded. Seventh, `retailer_margin_cents` is `net_sales_cents` multiplied by `margin_pct`, rounded half-up — and note the tier thresholds read net sales from step five, never gross. Eighth, the shrink charge, which is where the two variants diverge: the `PROVISIONAL` variant estimates — `scanned_units` multiplied by the agreement's `estimated_shrink_rate`, rounded half-up to a whole unit, multiplied by the window's average jobber cost, multiplied by `shrink_retailer_share_pct`, rounded half-up to a whole cent — where the average jobber cost is the sum over the window's scan lines of each line's `quantity` times its product's `jobber_cost_cents`, divided by `scanned_units`, rounded half-up, and taken as zero when `scanned_units` is zero; audits are ignored entirely. The `FINAL` variant instead sums `retailer_charge_cents` over the agreement's audits in `CERTIFIED` or `LOCKED` status whose `certified_at` falls in the window, ignoring `estimated_shrink_rate` — identical scan data therefore yields a different payable whenever the estimate disagrees with certified actuals. Ninth, `teardown_penalty_cents` sums the `penalty_cents` of seasonal sets reconciled in the window. Tenth, `net_payable_to_jobber_cents` is `net_sales_cents` minus `retailer_margin_cents` plus `shrink_retailer_charge_cents` minus `teardown_penalty_cents`.

Finalization converts the provisional view into the enforceable one. A `JobberFinance` operator finalizes a `PROVISIONAL` statement — the second OCC-guarded write on this entity — carrying `expected_settlement_statement_version` equal to the statement's current `version`, failing with `ERR_STALE_VERSION` when a revise cycle or another write has advanced it. Finalization further requires the period to be fully closed, the clock date no earlier than `period_end` (`ERR_SETTLEMENT_PERIOD_NOT_CLOSED` otherwise), and every audit of the agreement whose `submitted_at` falls in the window to be in `CERTIFIED` or `LOCKED` (`ERR_AUDIT_NOT_CERTIFIED` otherwise). On success the statement moves to `FINALIZED`, recomputes every money field under the `FINAL` variant, stamps `settled_in_statement_id` onto each matched scan it includes, and locks each included `CERTIFIED` audit into `LOCKED`.

From `FINALIZED`, the retailer's `RetailerManager` may dispute — `FINALIZED` to `DISPUTED`, optional `reason`, store-identity rule — and a `JobberFinance` revise returns `DISPUTED` to `PROVISIONAL`, recomputing the money fields under the `PROVISIONAL` variant so the cycle can run again. The approval gate belongs to a `JobberAdmin` who is not the statement's creator: an approver whose identity equals `created_by_user_id` is rejected with `ERR_SOD_APPROVER_IS_CREATOR`; a clean approval moves `FINALIZED` to `APPROVED` and records `approved_by_user_id`. Payment is the last step and carries the program's payout floor: a `JobberFinance` pay moves `APPROVED` to `PAID`, the terminal state, only when `net_payable_to_jobber_cents` is at least the program's `min_payout_cents` — a smaller payable is rejected with `ERR_PAYOUT_BELOW_MINIMUM` — and stamps `paid_at` with the clock.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including every lifecycle action, return `200 OK`, as do reads. The table below is a summary only — request bodies, response payloads, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and fire the time sweep | JobberAdmin |
| POST | `/programs` | Create a program | JobberAdmin |
| GET | `/programs` | List programs | All roles |
| GET | `/programs/{id}` | Get a program | All roles |
| POST | `/programs/{id}/archive` | Archive a program with no live agreements | JobberAdmin |
| POST | `/stores` | Create a store | JobberAdmin |
| GET | `/stores` | List stores | All roles |
| GET | `/stores/{id}` | Get a store | All roles |
| POST | `/stores/{id}/close` | Close a store with no live agreements | JobberAdmin |
| POST | `/agreements` | Create a store agreement with commercial terms | JobberAdmin |
| GET | `/agreements` | List agreements | All roles |
| GET | `/agreements/{id}` | Get an agreement | All roles |
| PATCH | `/agreements/{id}` | Amend commercial terms (OCC-guarded) | JobberAdmin |
| POST | `/agreements/{id}/submit` | Submit a draft agreement for retailer acceptance | JobberAdmin |
| POST | `/agreements/{id}/accept` | Accept a pending agreement | RetailerManager |
| POST | `/agreements/{id}/reject` | Reject a pending agreement | RetailerManager |
| POST | `/agreements/{id}/suspend` | Suspend an active agreement, cancelling scheduled visits | JobberAdmin |
| POST | `/agreements/{id}/resume` | Resume a suspended agreement | JobberAdmin |
| POST | `/agreements/{id}/terminate` | Terminate an active or suspended agreement | JobberAdmin |
| POST | `/products` | Create a product | JobberAdmin |
| GET | `/products` | List products | All roles |
| GET | `/products/{id}` | Get a product | All roles |
| PATCH | `/products/{id}` | Update cost or price floor, or discontinue | JobberAdmin |
| POST | `/space-allocations` | Allocate rack facings for a category window | JobberAdmin |
| GET | `/space-allocations` | List space allocations | All roles |
| GET | `/space-allocations/{id}` | Get a space allocation | All roles |
| POST | `/space-allocations/{id}/close` | Close a planned or active allocation | JobberAdmin |
| POST | `/price-directives` | Set a maintained retail price, superseding the incumbent | JobberAdmin |
| GET | `/price-directives` | List price directives | All roles |
| GET | `/price-directives/{id}` | Get a price directive | All roles |
| POST | `/promotions` | Create a promotion subject to the gap rule | JobberAdmin |
| GET | `/promotions` | List promotions | All roles |
| GET | `/promotions/{id}` | Get a promotion | All roles |
| POST | `/promotions/{id}/schedule` | Schedule a draft promotion | JobberAdmin |
| POST | `/promotions/{id}/suspend` | Suspend an active promotion | JobberAdmin |
| POST | `/promotions/{id}/resume` | Resume a suspended promotion within its window | JobberAdmin |
| POST | `/promotions/{id}/cancel` | Cancel a promotion | JobberAdmin |
| POST | `/promotions/{id}/end` | End an active or suspended promotion | JobberAdmin |
| GET | `/inventory-balances` | List consignment inventory balances | All roles |
| GET | `/inventory-balances/{id}` | Get an inventory balance | All roles |
| POST | `/routes` | Create a route with an assigned driver | JobberAdmin |
| GET | `/routes` | List routes | All roles |
| GET | `/routes/{id}` | Get a route | All roles |
| PATCH | `/routes/{id}` | Reassign driver, change cadence, or deactivate | JobberAdmin |
| POST | `/service-visits` | Schedule a route service visit | JobberAdmin |
| GET | `/service-visits` | List service visits | All roles |
| GET | `/service-visits/{id}` | Get a service visit | All roles |
| POST | `/service-visits/{id}/check-in` | Check in a scheduled visit, day-of only | RouteDriver |
| POST | `/service-visits/{id}/submit-counts` | Submit counted and restock lines | RouteDriver |
| POST | `/service-visits/{id}/confirm` | Confirm submitted counts, posting restock to inventory | RetailerManager |
| POST | `/service-visits/{id}/dispute` | Dispute submitted counts | RetailerManager |
| POST | `/service-visits/{id}/recount` | Return a disputed visit for recount | RouteDriver |
| POST | `/service-visits/{id}/cancel` | Cancel a scheduled visit | JobberAdmin |
| POST | `/scan-events` | Ingest a POS scan (sale, return, or void) | RetailerManager |
| GET | `/scan-events` | List scan events | All roles |
| GET | `/scan-events/{id}` | Get a scan event | All roles |
| POST | `/scan-events/{id}/resolve` | Resolve an unmatched scan after master-data repair | JobberAdmin |
| POST | `/audit-counts` | Schedule a shrink audit | JobberAdmin |
| GET | `/audit-counts` | List audit counts | All roles |
| GET | `/audit-counts/{id}` | Get an audit count | All roles |
| POST | `/audit-counts/{id}/start` | Start a scheduled audit | FieldAuditor |
| POST | `/audit-counts/{id}/submit` | Submit counted lines, freezing the unit-side variance | FieldAuditor |
| POST | `/audit-counts/{id}/dispute` | Dispute a submitted audit | RetailerManager |
| POST | `/audit-counts/{id}/order-recount` | Order a recount of a disputed audit | JobberAdmin |
| POST | `/audit-counts/{id}/certify` | Certify a submitted audit (OCC and SoD guarded) | JobberAdmin |
| POST | `/audit-counts/{id}/lock` | Lock a certified audit | JobberAdmin |
| POST | `/markdown-authorizations` | Request a markdown credit or vendor return | JobberAdmin |
| GET | `/markdown-authorizations` | List markdown authorizations | All roles |
| GET | `/markdown-authorizations/{id}` | Get a markdown authorization | All roles |
| POST | `/markdown-authorizations/{id}/approve` | Approve a requested authorization | RetailerManager |
| POST | `/markdown-authorizations/{id}/reject` | Reject a requested authorization | RetailerManager |
| POST | `/markdown-authorizations/{id}/apply` | Apply an approved authorization | JobberAdmin |
| POST | `/settlement-statements` | Generate a provisional statement for a period | JobberFinance |
| GET | `/settlement-statements` | List settlement statements | All roles |
| GET | `/settlement-statements/{id}` | Get a settlement statement | All roles |
| POST | `/settlement-statements/{id}/finalize` | Finalize a provisional statement (OCC-guarded) | JobberFinance |
| POST | `/settlement-statements/{id}/dispute` | Dispute a finalized statement | RetailerManager |
| POST | `/settlement-statements/{id}/revise` | Revise a disputed statement back to provisional | JobberFinance |
| POST | `/settlement-statements/{id}/approve` | Approve a finalized statement (SoD versus creator) | JobberAdmin |
| POST | `/settlement-statements/{id}/pay` | Pay an approved statement meeting the payout minimum | JobberFinance |
| POST | `/seasonal-sets` | Plan a seasonal display set | JobberAdmin |
| GET | `/seasonal-sets` | List seasonal sets | All roles |
| GET | `/seasonal-sets/{id}` | Get a seasonal set | All roles |
| POST | `/seasonal-sets/{id}/begin-setup` | Begin setup within the set window | RouteDriver |
| POST | `/seasonal-sets/{id}/complete-setup` | Complete setup with covering allocation | RouteDriver |
| POST | `/seasonal-sets/{id}/activate` | Activate a completed set for the season | JobberAdmin |
| POST | `/seasonal-sets/{id}/teardown` | Tear down a set, computing any penalty | RouteDriver |
| POST | `/seasonal-sets/{id}/reconcile` | Reconcile a torn-down set into settlement | JobberAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this table enumerates identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 422 Unprocessable Entity |
| `ERR_RANGE_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STORE_MANAGER_MISMATCH` | 403 Forbidden |
| `ERR_DRIVER_NOT_ASSIGNED` | 403 Forbidden |
| `ERR_SOD_CERTIFIER_IS_COUNTER` | 403 Forbidden |
| `ERR_SOD_APPROVER_IS_CREATOR` | 403 Forbidden |
| `ERR_AGREEMENT_EXISTS` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SKU_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_SCAN_EVENT` | 409 Conflict |
| `ERR_VOID_TARGET_INVALID` | 409 Conflict |
| `ERR_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_VISIT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SEASONAL_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_SEASONAL_ALLOCATION_MISSING` | 409 Conflict |
| `ERR_SETTLEMENT_PERIOD_NOT_CLOSED` | 409 Conflict |
| `ERR_SETTLEMENT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_AUDIT_NOT_CERTIFIED` | 409 Conflict |
| `ERR_PAYOUT_BELOW_MINIMUM` | 409 Conflict |
| `ERR_RESTOCK_VALUE_CAP_EXCEEDED` | 409 Conflict |
| `ERR_MARKDOWN_CAP_EXCEEDED` | 409 Conflict |
| `ERR_SPACE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CATEGORY_EXCLUSIVE_CONFLICT` | 409 Conflict |
| `ERR_SPACE_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROMO_GAP_VIOLATION` | 409 Conflict |
| `ERR_PRICE_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_IN_PROGRAM` | 422 Unprocessable Entity |
| `ERR_PRODUCT_DISCONTINUED` | 409 Conflict |
| `ERR_ROUTE_PROGRAM_MISMATCH` | 422 Unprocessable Entity |
