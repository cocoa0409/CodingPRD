# Cosmetics Contract Manufacturing API — Product Requirements Document

## 1. Introduction

Private-label beauty and personal-care brands rarely operate their own plants. They contract a manufacturer to compound bulk product, fill it into packaging, and certify it for market — while the brand itself may supply bespoke components such as custom bottles, caps, or cartons. That division of labor creates a dense web of obligations: formula intellectual property must be protected across competing brands sharing the same plant; in-process viscosity and pH checks decide whether a compounding batch may proceed to filling; preservative-efficacy and stability studies gate whether batches may be released; fragrance and color lots drift slightly from standard and need customer waivers; customer-supplied components arrive late or short, forcing negotiated reductions; and every filling-line changeover between product classes carries a cleaning cost that must be respected when runs are scheduled.

This document specifies the API through which the manufacturer runs that operation. Mounted under `/cosmfg`, it governs the full contract-manufacturing lifecycle: brand onboarding and commercial terms, formula authorship and revision lineage, INCI and label regulatory review, component and lot registration, production order placement under minimum-run and credit constraints, lot reservation and customer-supplied shortfall handling, compounding with scale-up authorization and in-process control, stability testing under chamber capacity limits, and filling-line scheduling under changeover discipline. Because lot expiry, study intervals, and schedule windows all depend on time, the platform evaluates every time-sensitive rule against a server-side logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts — authentication, response envelopes, pagination, identity fields, time, precision, concurrency, validation ordering, and confidentiality — that apply uniformly to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. The platform recognizes exactly six roles, spelled exactly as shown: `CustomerRep`, `FormulationChemist`, `RegulatoryAffairs`, `QAManager`, `ProductionPlanner`, and `PlantDirector`. A request with missing headers, or whose role is not one of these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's `customer_id` to `X-User-ID`, and a production order placed by a brand representative derives its `customer_id` directly from that header rather than from the request payload. When `X-User-Role` is `FormulationChemist`, `RegulatoryAffairs`, `QAManager`, `ProductionPlanner`, or `PlantDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where an action calls for attribution — for example as `reviewer_user_id` on a claimed regulatory review, as `recorded_by_user_id` on an in-process check or stability reading, or as `last_ipc_recorded_by_user_id` on a batch — but it never compares such a value to any entity's `id` for ownership purposes.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, list endpoints accept the optional filters their resource naturally supports: components filter by `customer_id` or `kind`; lots by `status`; formulas by `customer_id`, `base_formula_id`, or `status`; regulatory reviews by `review_scope`; production orders by `customer_id`, `formula_id`, or `status`; batches, shortfalls, filling runs, allocations, stability studies, and readings lists expose their documented filters — shortfalls by `production_order_id`, `component_id`, or `status`; allocations by `production_order_id`, `batch_id`, `lot_id`, or `status`; filling lines by `status` or `current_run_id`; in-process checks by `check_type`; and studies by `status`.

### 2.4. Resource Identity and Common Fields

Every primary resource in the system carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted UUID, formatted as a bare UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 and increments by one on every mutation — including system-driven cascade transitions, counter updates, and computed-field recomputation — providing the basis for optimistic concurrency control (§2.7).

Two kinds of records are append-only quality records and depart from this convention: an in-process check recorded against a batch, and a stability reading recorded against a study. Both carry only `id` and `created_at`; `updated_at` and `version` are absent from them entirely.

### 2.5. The Logical Clock

All time-dependent evaluation — most prominently whether a lot's `expires_at` instant still lies in the future — reads a server-side logical clock, never wall-clock time. At server startup, before any operator intervention, the logical clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time thereafter. Authorized operators (`PlantDirector`, `ProductionPlanner`, and `QAManager`) may advance it through the administration capability `POST /_clock/set_current_utc`, supplying `to_iso8601` as the new instant; the response echoes the clock's new value as `current_utc`.

### 2.6. Units, Monetary Precision, and Rounding

All monetary amounts in the system are expressed and stored as integer cents. Wherever a calculation produces a fractional cent, rounding is round-half-up. Two money calculations — the order quotation (§3.4) and the batch closure charge (§3.6) — round each ingredient or allocation line to whole cents first and only then sum the lines; summing unrounded values and rounding once at the end is a different, non-conforming algorithm whose results diverge by cents. Formula cost estimates (§3.2) are rounded half-up to whole cents per kilogram. A component's `standard_cost_per_kg_cents` and a lot's `unit_cost_per_kg_cents` are inputs and may themselves carry fractional cents. Fulfillable-unit projections (§3.5) round down to whole finished units. Changeover requirements (§3.8) are whole minutes. In-process quality comparisons (§3.6) are performed in raw measured units — centipoise or pH — with no rounding at all.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded against stale parent versions, and no other endpoint accepts a version field.

Creating a revision of a formula (`POST /cosmfg/formulas/{id}/revisions`) requires the non-optional input `expected_formula_version`, carrying the `version` of the parent formula as the client last observed it. Because a revision legitimately supersedes the parent's current tip, a writer holding a stale parent version must be refused rather than allowed to fork an outdated lineage: if the supplied value does not match the formula's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Updating an order's requested units (`PATCH /cosmfg/production-orders/{id}`) requires the non-optional input `expected_production_order_version`, matched against the order's current `version`. If another write — for example a shortfall escalation that reduced the order — has advanced the version since the client last read the order, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed.

### 2.8. Validation Order and Nested Resource Resolution

When a request fails several rules at once, the server reports the failure in a fixed evaluation order: first authentication of the headers (§2.1), then role authorization, then the segregation-of-duties actor check on batch release (§3.6), then existence of every identifier in the path and every referenced foreign identifier in the body (`formula_id`, `lot_id`, `line_id`, `batch_id`, `chamber_id`, `component_id`, and the like — any missing one yields `ERR_NOT_FOUND`, HTTP 404), then confidentiality and ownership scoping (§2.10), then optimistic-concurrency version matching (§2.7), then state-transition legality (`ERR_INVALID_STATE`, HTTP 409 — a transition attempted from a state that does not declare it, or from any terminal state, is rejected), then the domain safety, referential, and constraint rules of §3, then request-shape validation (`ERR_VALIDATION`, HTTP 400 — missing or invalid required fields, invalid enum members, or an ingredient list whose percentages fail to sum to 100 within one-hundredth of a point in either direction), and finally the fiscal rules, minimum run before credit (§3.4). Where several domain rules share one endpoint, §3 states their relative order explicitly.

Requests that address nested resources resolve their path identifiers strictly left to right. For a batch addressed beneath a production order, the server first confirms that the order exists and only then looks up the batch; the first identifier that does not resolve produces `ERR_NOT_FOUND` before any deeper check runs, so a request can never fail a business rule against a resource that does not exist.

### 2.9. State Transition Legality and Cascading Consistency

Every stateful resource moves only along the transitions declared for its lifecycle in §3; terminal states reject every further transition. Many transitions fan out across aggregates: a formula sent back for regulatory changes places its in-flight orders on hold and aborts their scheduled runs; a cancelled order releases its lot reservations, aborts its scheduled runs, voids its open shortfalls, and restores the customer's credit; a completing filling run consumes its batch and sends its line to cleaning. All cascades take effect immediately and atomically with the triggering operation — the platform follows an immediate-consistency model with no deferred reconciliation. Every cascade-mutated resource is a true mutation: its `updated_at` refreshes and its `version` increments, exactly as if the change had been requested directly.

### 2.10. Brand Segregation and Formula Confidentiality

A `CustomerRep` operates strictly inside their own brand's estate. They may read their own customer record, their own orders, their own customer's formulas, and the components and lots their brand owns; any attempt to access a resource whose `customer_id` belongs to a different brand is rejected with `ERR_CONFIDENTIALITY_VIOLATION` (HTTP 403).

Formula intellectual property is governed by two independent attributes set at authorship. `ownership` declares who holds the IP — `CUSTOMER_OWNED` or `MANUFACTURER_OWNED`. `confidentiality` declares how the formula may be reused — `STANDARD` or `EXCLUSIVE`. An `EXCLUSIVE` formula may never serve as the base formula for a different customer's formula; such a derivation is rejected with `ERR_CONFIDENTIALITY_VIOLATION`.

## 3. Business Logic & Workflows

### 3.1. Brand Onboarding and Component Supply Registration

A `PlantDirector` registers each brand owner as a customer, supplying a display `name`, a commercial `tier` of `STANDARD` or `PRESTIGE` — prestige brands earn a per-unit filling-fee discount at quotation time (§3.4) — a negotiated `minimum_run_units` of at least one unit, and a `credit_limit_cents` of zero or more. The customer's `outstanding_balance_cents` initializes to zero and thereafter tracks the sum of `quote_total_cents` over that customer's orders currently standing in `CONFIRMED`, `IN_PRODUCTION`, or `FILLING` status.

Components are registered by a `ProductionPlanner` with a `name`, a `kind` drawn from `RAW_MATERIAL`, `BULK_FRAGRANCE`, `COLORANT`, `PRIMARY_PACK`, or `SECONDARY_PACK`, a `supply_mode` of `MANUFACTURER_SUPPLIED` or `CUSTOMER_SUPPLIED`, and a `standard_cost_per_kg_cents` of zero or more, which may be fractional. When a component is customer-supplied, `customer_id` is required and names the owning brand; for manufacturer-supplied components, `customer_id` must be null.

Stock arrives as lots against a registered component. Receipt records a supplier `lot_code` that is unique per component, a strictly positive `quantity_received` — kilograms for the raw-material, fragrance, and colorant kinds, units for the pack kinds — and an `expires_at` instant; optionally the receipt also records the lot's actual `unit_cost_per_kg_cents` and a `sensorial_profile` flag, which defaults to `WITHIN_SPEC` and may instead be declared `MINOR_VARIANT` when a fragrance or color lot drifts from standard. At receipt, `quantity_available` initializes to `quantity_received` while `quantity_reserved` and `quantity_consumed` start at zero; `variant_waiver` initializes to `PENDING` for a `MINOR_VARIANT` lot and to `NOT_REQUIRED` otherwise; and the lot begins life `AVAILABLE`. Receiving a lot of a customer-supplied component immediately runs the shortfall waterfall described in §3.5 against the owning customer's open shortfalls.

A brand representative adjudicates each variant-flagged lot of their own components through a waiver decision. A `decision` of `WAIVED` moves `variant_waiver` from `PENDING` to `WAIVED` and makes the lot allocatable. A `decision` of `REJECTED` moves `variant_waiver` to `REJECTED` and drives the lot from `AVAILABLE` to `QUARANTINED`, releasing every `RESERVED` allocation that references it — each released quantity shifts back from the lot's `quantity_reserved` into its `quantity_available`. A waiver decision is only meaningful while the lot's `variant_waiver` stands `PENDING`.

Two system rules govern lot usability regardless of waivers. A lot is allocatable only while its `expires_at` lies strictly after the current logical clock (§2.5). And when reservation or consumption drives a lot's `quantity_available` to exactly zero, the lot transitions from `AVAILABLE` to `DEPLETED` on its own.

### 3.2. Formula Authorship, Derivation, and Cost Estimation

A `FormulationChemist` authors a formula for a brand, identified by `customer_id`, with a display `name`, the IP attributes `ownership` and `confidentiality` of §2.10, a `product_class` of `SKIN`, `HAIR`, `BABY`, or `SUN` — this classification drives the filling-line changeover matrix of §3.8 — and an `allergen_flag` that is true when the formula contains declared allergens and forces the strictest changeover class. The formula's physical contract comprises `bulk_mass_per_unit_kg` (strictly positive kilograms of bulk per finished unit), `viscosity_target_cps` (strictly positive), `viscosity_tolerance_pct` (greater than zero and at most fifty), `ph_target` (between 0 and 14 inclusive), and `ph_tolerance` (strictly positive). Its recipe is the `ingredients` list, each entry giving an `inci_name`, an optional `component_id`, and a `percentage`; the percentages must sum to exactly 100 within a tolerance of one-hundredth of a point in either direction, failing which the request is rejected with `ERR_VALIDATION`. A formula may additionally declare `required_components` — pairs of `component_id` and `units_per_product` enumerating the customer-supplied pack components each finished unit consumes; the list may be empty.

Every new formula begins in `DRAFT` with `version_seq` set to 1. Authorship may derive a new formula from an existing one through `base_formula_id`, which is null for original formulas: the base must be a non-`EXCLUSIVE` formula belonging to the same customer, or any `MANUFACTURER_OWNED` formula with `STANDARD` confidentiality; referencing another customer's `EXCLUSIVE` formula as a base is rejected with `ERR_CONFIDENTIALITY_VIOLATION`. Derivation is not a revision — the derived formula still begins at `version_seq` 1 and the base formula is left untouched.

True revisions are created through the revision action on a formula standing in `CHANGES_REQUESTED`, `APPROVED`, or `ACTIVE`. The child is created in `DRAFT` with `version_seq` equal to the parent's `version_seq` plus one, inheriting from the parent any field the request leaves unspecified; the request may carry a replacement `name`, `ingredients`, `required_components`, `viscosity_target_cps`, `viscosity_tolerance_pct`, `ph_target`, `ph_tolerance`, `product_class`, or `allergen_flag`. Creating the revision increments the parent formula's `version` by one, and because a revision supersedes the parent's current tip, the request must carry `expected_formula_version` matching the parent's current `version`; a stale value is refused with `ERR_STALE_VERSION` (HTTP 412) per §2.7.

Every formula carries two per-kilogram bulk-cost estimates, computed from the same ingredient list and differing only in the unit cost applied to each ingredient's component. The standard variant, `cost_estimate_standard_per_kg_cents`, prices every ingredient at its component's `standard_cost_per_kg_cents`. The current-lot variant, `cost_estimate_current_lot_per_kg_cents`, prices each ingredient at the quantity-weighted average of `unit_cost_per_kg_cents` across that component's lots currently standing `AVAILABLE`, weighted by each lot's `quantity_available`; lots without a recorded `unit_cost_per_kg_cents` are excluded from both the weighted sum and its divisor, and when a component has no priced available lots at all the estimate falls back to that component's standard cost. In both variants the per-kilogram figure is the sum over ingredients of each ingredient's `percentage` divided by one hundred, multiplied by the applicable unit cost, with the result rounded half-up to whole cents per kilogram. Both estimates are computed when a formula is created, when a revision is created, and when its ingredient list changes; a lot receipt additionally refreshes the current-lot variant.

### 3.3. Regulatory Review and the Compliance Hold Cascade

Submission begins the regulatory path: a `FormulationChemist` submits a formula standing in `DRAFT` — or in `CHANGES_REQUESTED`, resuming a review loop that was sent back — moving it to `IN_REVIEW` and incrementing the formula's `version` by one.

Reviews themselves are opened by the chemist against a formula standing in `IN_REVIEW` or `ACTIVE`, naming a `review_scope` of `INCI_LIST` (ingredient-nomenclature review) or `LABEL_ARTWORK` (packaging artwork review). A new review starts `SUBMITTED`. Only one open review — one standing `SUBMITTED`, `UNDER_REVIEW`, or `CHANGES_REQUESTED` — may exist per formula per scope; opening a duplicate is rejected with `ERR_REVIEW_ALREADY_OPEN` (HTTP 409).

A `RegulatoryAffairs` operator claims a `SUBMITTED` review, moving it to `UNDER_REVIEW` and recording the acting `X-User-ID` as `reviewer_user_id`. From there the review has two exits. Approving moves it to `APPROVED`, with two scope-dependent consequences: approval of an `INCI_LIST`-scope review moves a formula standing `IN_REVIEW` to `APPROVED`; approval of a `LABEL_ARTWORK`-scope review completes every `FILLING` production order of that formula whose recorded `filled_units` have already reached the order's `requested_units`, moving each such order to `COMPLETED` and decreasing its customer's `outstanding_balance_cents` by the order's `quote_total_cents`. Requesting changes moves the review to `CHANGES_REQUESTED` and records the reviewer's `comment`.

A request for changes is the plant's compliance tripwire. The formula — whether it stood `IN_REVIEW` or `ACTIVE`, the latter being the post-market re-audit path — moves to `CHANGES_REQUESTED`, and the hold cascade fires: every production order referencing the formula and standing in `CONFIRMED`, `IN_PRODUCTION`, or `FILLING` moves to `ON_HOLD` with its `hold_return_status` set to the status it just vacated, and every `SCHEDULED` filling run of each such order moves to `ABORTED`, releasing its line window. Held orders remain frozen until the formula recovers. The review loop closes when the chemist resubmits the formula to `IN_REVIEW` and then resubmits the `CHANGES_REQUESTED` review itself, returning the review to `SUBMITTED`; resubmission is refused while the referenced formula has not yet returned to `IN_REVIEW`.

Activation turns an approved formula into a production-eligible one. The chemist activates a formula standing `APPROVED`, moving it to `ACTIVE` and incrementing `version` by one — but only when the latest `INCI_LIST`-scope review for the formula stands `APPROVED`; otherwise activation is rejected with `ERR_INCI_REVIEW_NOT_APPROVED` (HTTP 409).

Retirement is the executive prerogative: a `PlantDirector` retires an `ACTIVE` formula, moving it to its terminal state `RETIRED`, incrementing `version`, and cancelling every `DRAFT` production order that still references it, with the full cancellation cascade of §3.5.

Resumption unwinds a hold once the formula recovers. A `ProductionPlanner` resumes an `ON_HOLD` order, and the order returns to whatever `hold_return_status` recorded — `CONFIRMED`, `IN_PRODUCTION`, or `FILLING` — with `hold_return_status` cleared on success. Resumption requires the referenced formula to stand in `IN_REVIEW`, `APPROVED`, or `ACTIVE`; if it does not, the request is rejected with `ERR_FORMULA_NOT_ACTIVE` (HTTP 409).

### 3.4. Quotation, Minimum Runs, Credit, and Order Confirmation

A brand's representative places a production order by naming a `formula_id` and the `requested_units` (at least one); the order's `customer_id` is taken from the acting representative's `X-User-ID`, never from the payload. Two referential gates apply at placement, evaluated in this order: the formula must belong to the ordering customer, failing with `ERR_FORMULA_CUSTOMER_MISMATCH` (HTTP 422), and the formula must stand `ACTIVE`, failing with `ERR_FORMULA_NOT_ACTIVE` (HTTP 409). The order begins in `DRAFT` with `forfeited_units` and `filled_units` at zero and `formula_version_seq` still null.

Quotation runs at placement, again on any change to `requested_units`, and again at confirmation, storing its result as `quote_total_cents`. The materials subtotal walks the formula's `ingredients` in list order: each ingredient's mass in kilograms is its `percentage` divided by one hundred, multiplied by the formula's `bulk_mass_per_unit_kg`, multiplied by the order's `requested_units`; each ingredient's line cost is that mass multiplied by its component's `standard_cost_per_kg_cents`, rounded half-up to whole cents; and the subtotal sums the rounded line costs — the rounding is pinned per line, never deferred to a single rounding at the end. The filling fee applies a per-unit rate read from `requested_units`: 50 cents per unit when the order is for at most 5,000 units, 40 cents when it is for at most 20,000, and 30 cents beyond 20,000. A customer whose `tier` is `PRESTIGE` takes 5 cents off the applicable rate, with the rate never driven below zero. The filling fee is the rate multiplied by `requested_units`, and the quoted total is the materials subtotal plus the filling fee.

Two projections of customer-supplied packaging coverage accompany every order from placement onward — `fulfillable_units_conservative` and `fulfillable_units_optimistic`, both defined in §3.5 — and the derived `open_units` reports the order's `requested_units` minus its `filled_units`. Because shortfall escalation subtracts forfeited volume from `requested_units` directly, the sum of `requested_units` and `forfeited_units` is conserved across escalation and filling.

While an order remains in `DRAFT`, its representative may revise `requested_units` by supplying `expected_production_order_version` matching the order's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.7, since an intervening write — a shortfall escalation, say — makes the writer's view of the order stale. A successful update recomputes the quote and both fulfillable projections and increments the order's `version` by one.

Confirmation converts a `DRAFT` order into a commitment. It requires the formula to stand `ACTIVE` (else `ERR_FORMULA_NOT_ACTIVE`), enforces the minimum run once more — `requested_units` must be at least the customer's `minimum_run_units`, with equality allowed, failing with `ERR_BELOW_MINIMUM_RUN` (HTTP 422) here just as at placement and at units update — and then applies the credit gate: the customer's `outstanding_balance_cents` plus the order's `quote_total_cents` must not exceed the customer's `credit_limit_cents`, failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). On confirmation the order pins `formula_version_seq` to the formula's current `version_seq` — later formula revisions never re-target a confirmed order — and the customer's outstanding balance rises by the quoted total.

From there the order walks a system-driven path. The order's first batch entering `MIXING` moves it from `CONFIRMED` to `IN_PRODUCTION`. The order's first filling run entering `IN_PROGRESS` moves it from `IN_PRODUCTION` to `FILLING`. And when a completing run brings the order's `filled_units` to at least its `requested_units`, the order moves from `FILLING` to `COMPLETED` — provided the formula's latest `LABEL_ARTWORK`-scope review stands `APPROVED`; if that label review has not yet been approved, the order remains `FILLING` until the approval lands and completes it per §3.3. Completion decreases the customer's `outstanding_balance_cents` by `quote_total_cents`. `COMPLETED` and `CANCELLED` are the order's terminal states.

### 3.5. Lot Reservation, Sensorial Variants, and Customer-Supplied Shortfalls

Reservations bind stock to an order. A `ProductionPlanner` reserves lots for an order standing `CONFIRMED` or `IN_PRODUCTION` by submitting `items`, each item naming a `lot_id` and a strictly positive `quantity`, with an optional `batch_id` for raw-material allocations feeding a specific batch — order-level pack reservations leave it null, and when present it must reference a batch belonging to the same order. Each item becomes a `RESERVED` allocation carrying the order's `production_order_id`. Reservation validates in a fixed order: the lot must be unexpired, its `expires_at` strictly after the current logical clock, failing with `ERR_LOT_EXPIRED` (HTTP 422); a lot of a `CUSTOMER_SUPPLIED` component may serve only orders of its owning customer, failing with `ERR_COMPONENT_OWNERSHIP_MISMATCH` (HTTP 422); a `MINOR_VARIANT` lot must already hold a `WAIVED` waiver, failing with `ERR_VARIANT_WAIVER_REQUIRED` (HTTP 422) while its waiver stands `PENDING` or `REJECTED`; and finally the lot must stand `AVAILABLE` with `quantity_available` covering the requested `quantity`, failing with `ERR_LOT_INSUFFICIENT_QUANTITY` (HTTP 422). Each successful reservation moves the quantity from the lot's `quantity_available` into its `quantity_reserved`, and a lot driven to exactly zero available becomes `DEPLETED`. A planner may also manually release a `RESERVED` allocation, which returns its `quantity` from `quantity_reserved` to `quantity_available`; releases also arrive system-side from order cancellation, shortfall escalation, and lot quarantine.

The two fulfillable projections reported on every order measure how many finished units its customer-supplied packaging can support. For each entry in the formula's `required_components`, the per-unit need is that entry's `units_per_product`, and the eligible lots are those of a component whose `supply_mode` is `CUSTOMER_SUPPLIED`, whose owning `customer_id` matches the ordering customer, whose lot status is `AVAILABLE`, and whose `expires_at` lies strictly after the current logical clock. The conservative pool for a component sums `quantity_available` over the eligible lots whose `sensorial_profile` is `WITHIN_SPEC` or whose `variant_waiver` stands `WAIVED`, and adds the reserved `quantity` of this order's own `RESERVED` allocations on those same lots, so stock already earmarked for the order counts toward it. The optimistic pool adds, on top of the conservative pool, `quantity_available` over eligible lots flagged `MINOR_VARIANT` whose waiver still stands `PENDING` — it assumes those waivers will be granted, and the two projections diverge exactly when such lots exist. Each projection divides its pool by the component's `units_per_product`, rounds the quotient down to a whole number of units, and lets the tightest component govern: `fulfillable_units_conservative` takes the smallest conservative result across all required components, `fulfillable_units_optimistic` the smallest optimistic one. When the formula declares no required components, both projections equal the order's `requested_units`. Both are recomputed at order placement, on any change to `requested_units`, on lot receipt, on allocation release, on a waiver decision, and on shortfall escalation.

When the conservative mathematics cannot cover an order, the planner declares a shortfall against it, naming a `component_id` — which must be `CUSTOMER_SUPPLIED` and owned by the order's customer — and the `required_quantity` the order needs in total. The system computes `allocatable_quantity` as the sum of `quantity_available` over the customer's `AVAILABLE`, unexpired lots of that component at declaration time, and `shortfall_quantity` as the difference; a declaration whose computed shortfall is zero or less is rejected with `ERR_NO_SHORTFALL` (HTTP 422). A valid case opens in `OPEN`. The brand's representative may then commit to deliver the shorted quantity, recording `committed_by_date` and moving the case from `OPEN` to `COMMITMENT_RECEIVED`.

Inbound stock heals shortfalls automatically. Receipt of a lot of a customer-supplied component distributes its `quantity_available` across that customer's shortfall cases for the same component standing `OPEN` or `COMMITMENT_RECEIVED`, oldest case first, ties broken by the parent order's creation time, earliest first. Each grant is the lesser of the case's still-uncovered `shortfall_quantity` and the lot's remaining quantity, and each grant creates a `RESERVED` allocation against the shortfall's parent order with no batch linkage. A case whose grants reach its full `shortfall_quantity` transitions to `CLOSED_RESOLVED`; any lot quantity left over stays `AVAILABLE`, and a zero-quantity remainder creates no allocation.

Unresolved cases escalate. From `OPEN` or `COMMITMENT_RECEIVED`, a `ProductionPlanner` escalates with a `resolution`, and the case moves to `ESCALATED`. Under `REDUCE_ORDER`, the order's `requested_units` shrink to its `fulfillable_units_conservative` and its `forfeited_units` grow by the surrendered delta; then, for every component in the formula's `required_components`, the order's excess `RESERVED` allocations are released newest-first — the most recently created allocation first — until that component's reserved quantity no longer exceeds the new `requested_units` multiplied by its `units_per_product`, and each release restores its lot's reserved and available counters. Under `CANCEL_ORDER`, the order is cancelled outright with the full cancellation cascade.

Cancellation is available to the brand's representative and the planner from any non-terminal order state — `DRAFT`, `CONFIRMED`, `IN_PRODUCTION`, `FILLING`, or `ON_HOLD` — and arrives system-side when a formula retirement cancels `DRAFT` orders. Cancelling releases the order's `RESERVED` allocations (each released lot's `quantity_reserved` falls and its `quantity_available` rises by the released amount), moves its `SCHEDULED` filling runs to `ABORTED`, voids its `OPEN` and `COMMITMENT_RECEIVED` shortfall cases to `CLOSED_VOID`, and — for orders that had passed confirmation — decreases the customer's `outstanding_balance_cents` by the order's `quote_total_cents`.

### 3.6. Compounding, Scale-Up Authorization, and In-Process Control

For an order standing `CONFIRMED` or `IN_PRODUCTION`, the planner plans a compounding batch by declaring `batch_size_kg`, a strictly positive bulk mass. The batch begins `PLANNED` with `failed_check_count` at zero, both `round_viscosity_result` and `round_ph_result` at `NONE`, `last_ipc_recorded_by_user_id` null, and `scale_up_approved` false; the system derives its `scale_up_factor` as the planned bulk mass divided by the fifty-kilogram laboratory reference mass.

Scale-up is an executive gate. When a batch's `scale_up_factor` exceeds ten, mixing may not begin until a `PlantDirector` approves scale-up for that batch, setting `scale_up_approved` to true; attempting to start without the approval is rejected with `ERR_SCALE_UP_APPROVAL_REQUIRED` (HTTP 422).

Starting mixing enforces, after the scale-up gate, the batch's mass balance: the total reserved `quantity` across the batch's `RESERVED` allocations whose lots are of the raw kinds — `RAW_MATERIAL`, `BULK_FRAGRANCE`, or `COLORANT` — must at least cover `batch_size_kg`, failing with `ERR_BATCH_UNDER_ALLOCATED` (HTTP 422). The parent order must also stand `CONFIRMED` or `IN_PRODUCTION`. When the order's first batch enters `MIXING`, the order itself moves from `CONFIRMED` to `IN_PRODUCTION`.

While a batch mixes, a `QAManager` records in-process checks, each carrying a `check_type` of `VISCOSITY` or `PH` and a `measured_value`. Every record is stamped with a `round_index` of one plus the batch's `failed_check_count` at record time, the `effective_tolerance` actually applied, the computed `result` of `PASS` or `FAIL`, and the recorder's identity as `recorded_by_user_id`; the batch's `last_ipc_recorded_by_user_id` follows the most recent recorder, and the check log is append-only. The applied tolerance tightens as failures accumulate: after a given number of failed rounds, the effective tolerance equals the base tolerance multiplied by the larger of one-half and the quantity one minus one-tenth times the number of failed rounds — each failure shrinks the band by ten percent of the base, never below half of it. For a `VISCOSITY` check, the band is the formula's `viscosity_target_cps` scaled by `viscosity_tolerance_pct` percent and then by the tightening factor, and the check passes when the absolute deviation of `measured_value` from `viscosity_target_cps` is within the band — a reading exactly at the band edge passes. For a `PH` check, the band is the formula's `ph_tolerance` scaled by the tightening factor, compared the same way against `ph_target` with the same inclusive edge. The batch leaves `MIXING` for `IPC_PASSED` only when both `round_viscosity_result` and `round_ph_result` stand `PASS` in the current round; any `FAIL` immediately moves the batch to `IPC_FAILED`, sets the failing check's round flag to `FAIL`, and increments `failed_check_count` by one.

An `IPC_FAILED` batch may be sent back to `MIXING` for adjustment by a `QAManager`, optionally annotated with an `adjustment_note`; both round flags reset to `NONE` and a new round begins. The retry budget is three failed rounds: once `failed_check_count` has reached three, adjustment is rejected with `ERR_IPC_ATTEMPTS_EXHAUSTED` (HTTP 422).

Release to filling is the quality organization's second signature. A `QAManager` releases an `IPC_PASSED` batch, subject to two gates evaluated in this order: segregation of duties — the releasing user's identity must differ from the batch's `last_ipc_recorded_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and study clearance — no stability study of the order's formula may stand `COMPLETED_FAIL`, failing with `ERR_STUDY_FAILED_BLOCKS_RELEASE` (HTTP 409). A released batch stands `RELEASED_TO_FILLING`.

A batch that cannot be salvaged is rejected by a `QAManager` from `MIXING` or `IPC_FAILED`, optionally recording a `reason`. Rejection moves the batch to `REJECTED` and consumes its materials as waste: every `RESERVED` allocation of the batch becomes `CONSUMED`, each referenced lot's `quantity_reserved` falls by the allocation's `quantity` while its `quantity_consumed` rises. The same consumption cascade runs when a batch is `CONSUMED` by a completing filling run (§3.8).

Closure prices the batch. When a batch reaches `CONSUMED` or `REJECTED`, its closure charges are computed in a pinned order. First, the materials subtotal sums one line per `CONSUMED` allocation: the allocation's `quantity` multiplied by the lot's effective cost — the lot's `unit_cost_per_kg_cents` when one was recorded at receipt, otherwise the component's `standard_cost_per_kg_cents` — with each line rounded half-up to whole cents before the lines are summed. Second, the surcharge rate is read from that pre-surcharge materials subtotal alone: two percent when the subtotal is below one million cents, five percent otherwise; the bracket is never read from the post-surcharge total. Third, the surcharge is the materials subtotal multiplied by the applicable rate, rounded half-up to whole cents. Finally, `batch_charge_cents` is the materials subtotal plus the surcharge. A parallel figure, `batch_charge_standard_cents`, is computed identically but prices every allocation at the component's standard cost, giving finance a variance view against actual lot costs; the two diverge whenever actual lot costs differ from standard. Both charge fields remain null until the batch closes.

### 3.7. Stability Studies and Chamber Capacity

Stability work is capacity-managed. A `QAManager` registers each chamber with a unique `chamber_code` and a `capacity_studies` limit of at least one; the chamber's `active_study_count` tracks how many studies currently occupy it.

A study is started for a formula standing `APPROVED` or `ACTIVE` by naming a `chamber_id` and a `study_type`. The type fixes the study's `required_intervals`, the day-indices at which pull points must be recorded: `PRESERVATIVE_EFFICACY` requires a single interval at day 28; `ACCELERATED` requires days 30, 60, and 90; `REAL_TIME` requires days 90, 180, and 365. The chamber must have free capacity — its count of in-progress studies below `capacity_studies` — failing with `ERR_CHAMBER_CAPACITY_EXCEEDED` (HTTP 409). A started study begins `IN_PROGRESS` with `recorded_interval_count` at zero, and the chamber's count rises by one.

Pull points arrive as readings. A `QAManager` records each reading with an `interval_index` and a `result` of `PASS` or `FAIL`. Readings must follow the required sequence exactly: the recorded `interval_index` must equal the next required day-index — the entry at position `recorded_interval_count` of the study's `required_intervals` — failing with `ERR_READING_INTERVAL_OUT_OF_ORDER` (HTTP 422). Each accepted reading increments `recorded_interval_count`, records the operator as `recorded_by_user_id` on the record scoped by `study_id`, and drives the study's outcome: a `FAIL` reading at any point ends the study as `COMPLETED_FAIL`, freeing one unit of chamber capacity and blocking all future batch releases for the formula per §3.6; a `PASS` recorded against the final required interval ends the study as `COMPLETED_PASS`, likewise freeing chamber capacity.

### 3.8. Filling Lines, Changeover Discipline, and Run Settlement

Filling lines cycle continuously. A `ProductionPlanner` registers each line with a unique `line_code`; the line begins `IDLE`, moves to `RUNNING` when a run starts on it — carrying that run's identifier as `current_run_id` — and moves to `CLEANING` when its in-progress run completes or is aborted, clearing `current_run_id`. Cleaning closes the cycle: the planner finishes cleaning explicitly, returning the line from `CLEANING` to `IDLE`.

Scheduling a run binds a batch, a line, and a time window. The planner names a `line_id`, a `batch_id` that must belong to the same production order — otherwise `ERR_BATCH_ORDER_MISMATCH` (HTTP 422) — a window running from `scheduled_start` inclusive to `scheduled_end` exclusive, with the end strictly after the start, and `planned_units` of at least one and at most the batch's `batch_size_kg` divided by the formula's `bulk_mass_per_unit_kg`, rounded down to a whole unit — otherwise `ERR_PLANNED_UNITS_EXCEED_BATCH` (HTTP 422). Scheduling evaluates its checks in a fixed order: batch-order matching first, then line occupancy, then the changeover gap, then the planned-units cap. Occupancy treats each window as half-open: the new window must not intersect any run on the same line standing `SCHEDULED` or `IN_PROGRESS`, but touching endpoints are allowed — a run that ends exactly when the next begins does not conflict; a genuine overlap is rejected with `ERR_LINE_OCCUPIED` (HTTP 409). A successfully scheduled run stands `SCHEDULED`.

Changeover discipline prices the gap behind the previous run. The previous run is the one on the same line, standing `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED`, whose `scheduled_end` falls at or before the new run's `scheduled_start`, taking the greatest such end and breaking ties toward the earliest-created run; when no such run exists, `changeover_minutes_required` is zero and no gap check applies. The base requirement is zero minutes when both runs use the same formula; 15 minutes when the two formulas share a `product_class` and neither carries an `allergen_flag`; 45 minutes when their product classes differ and neither is allergen-flagged; and 120 minutes whenever either formula is allergen-flagged. When the previous run's formula contains an ingredient whose component is of kind `BULK_FRAGRANCE` and the two runs use different formulas, 30 minutes of fragrance carryover are added to the base. The requirement never exceeds 180 minutes — base plus carryover, capped — and is stored on the new run as `changeover_minutes_required`. The new run's `scheduled_start` must fall at or after the previous run's `scheduled_end` plus the requirement, with a gap exactly equal to the requirement allowed; a smaller gap is rejected with `ERR_CHANGEOVER_GAP_VIOLATION` (HTTP 409).

Starting a run is a triple gate. The run must stand `SCHEDULED`; its referenced batch must stand `RELEASED_TO_FILLING`, failing with `ERR_BATCH_NOT_RELEASED` (HTTP 409); its line must stand `IDLE`, failing with `ERR_INVALID_STATE` (HTTP 409); and its order must stand `IN_PRODUCTION` or `FILLING`. Starting moves the run to `IN_PROGRESS`, drives the line from `IDLE` to `RUNNING` with `current_run_id` set, and — for the order's first in-progress run — moves the order from `IN_PRODUCTION` to `FILLING`.

Completion settles the run's output. The planner completes an in-progress run by recording `filled_units`, the good units produced — null on the run until this moment — and optionally `rejected_units`, the scrapped count, zero by default. Over-delivery is forbidden: the order's already-recorded `filled_units` plus the run's newly reported good units must not exceed the order's current `requested_units` — the originally requested quantity less any `forfeited_units`, escalation having already subtracted forfeited volume from `requested_units` itself — failing with `ERR_OVER_DELIVERY` (HTTP 422). A completing run cascades: its batch moves from `RELEASED_TO_FILLING` to `CONSUMED` with the allocation-consumption cascade of §3.6; the line moves from `RUNNING` to `CLEANING`; the order's `filled_units` rise by the run's good units; and when the order's `filled_units` reach at least its `requested_units` and the formula's latest `LABEL_ARTWORK` review stands `APPROVED`, the order completes per §3.4, otherwise it remains `FILLING` awaiting the label approval.

Abortion releases capacity without settling output. Aborting a `SCHEDULED` run moves it to `ABORTED` and releases its line window without any line state change. Aborting an `IN_PROGRESS` run moves it to `ABORTED`, sends its line from `RUNNING` to `CLEANING`, and leaves its batch standing `RELEASED_TO_FILLING`, unconsumed and available to a future run.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, validation preconditions, and side effects for every operation are specified in §2 and §3; this table is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cosmfg/customers` | Register a brand-owner customer | PlantDirector |
| GET | `/cosmfg/customers/{id}` | Get a customer (CustomerRep reads own record only) | PlantDirector, ProductionPlanner, QAManager, FormulationChemist, RegulatoryAffairs, CustomerRep |
| GET | `/cosmfg/customers` | List customers with pagination | PlantDirector, ProductionPlanner |
| POST | `/cosmfg/components` | Register a component (raw material or pack) | ProductionPlanner |
| GET | `/cosmfg/components/{id}` | Get a component | ProductionPlanner, QAManager, PlantDirector, FormulationChemist, CustomerRep |
| GET | `/cosmfg/components` | List components, filtered by owning customer or kind | ProductionPlanner, QAManager, PlantDirector, CustomerRep |
| POST | `/cosmfg/components/{id}/lots` | Receive a component lot (customer-supplied receipts trigger shortfall proration) | ProductionPlanner |
| GET | `/cosmfg/lots/{id}` | Get a component lot | ProductionPlanner, QAManager, PlantDirector, CustomerRep |
| GET | `/cosmfg/components/{id}/lots` | List lots of a component | ProductionPlanner, QAManager, PlantDirector, CustomerRep |
| POST | `/cosmfg/lots/{id}/waive-variant` | Waive or reject a MINOR_VARIANT fragrance/color lot | CustomerRep |
| POST | `/cosmfg/formulas` | Create a formula in DRAFT | FormulationChemist |
| GET | `/cosmfg/formulas/{id}` | Get a formula (CustomerRep: own customer's formulas only) | FormulationChemist, RegulatoryAffairs, QAManager, ProductionPlanner, PlantDirector, CustomerRep |
| GET | `/cosmfg/formulas` | List formulas with customer, base-formula, and status filters | FormulationChemist, RegulatoryAffairs, QAManager, ProductionPlanner, PlantDirector, CustomerRep |
| POST | `/cosmfg/formulas/{id}/submit` | Submit a DRAFT or CHANGES_REQUESTED formula for regulatory review | FormulationChemist |
| POST | `/cosmfg/formulas/{id}/activate` | Activate an APPROVED formula (requires APPROVED INCI_LIST review) | FormulationChemist |
| POST | `/cosmfg/formulas/{id}/retire` | Retire an ACTIVE formula; referencing DRAFT orders are cancelled | PlantDirector |
| POST | `/cosmfg/formulas/{id}/revisions` | Create a revision (child formula in DRAFT); OCC-guarded on the parent's version | FormulationChemist |
| GET | `/cosmfg/formulas/{id}/reviews` | List regulatory reviews of a formula | RegulatoryAffairs, FormulationChemist, PlantDirector |
| GET | `/cosmfg/formulas/{id}/stability-studies` | List stability studies of a formula | QAManager, PlantDirector |
| POST | `/cosmfg/formulas/{id}/reviews` | Open an INCI_LIST or LABEL_ARTWORK review for an IN_REVIEW or ACTIVE formula | FormulationChemist |
| GET | `/cosmfg/reviews/{id}` | Get a regulatory review | RegulatoryAffairs, FormulationChemist, PlantDirector |
| POST | `/cosmfg/reviews/{id}/claim` | Claim a SUBMITTED review | RegulatoryAffairs |
| POST | `/cosmfg/reviews/{id}/approve` | Approve an UNDER_REVIEW review | RegulatoryAffairs |
| POST | `/cosmfg/reviews/{id}/request-changes` | Send an UNDER_REVIEW review back; cascades formula, orders, and runs | RegulatoryAffairs |
| POST | `/cosmfg/reviews/{id}/resubmit` | Resubmit a CHANGES_REQUESTED review once the formula is back IN_REVIEW | FormulationChemist |
| POST | `/cosmfg/production-orders` | Place a production order (DRAFT) for an ACTIVE formula the customer owns | CustomerRep |
| GET | `/cosmfg/production-orders/{id}` | Get a production order (CustomerRep: own orders only) | CustomerRep, ProductionPlanner, QAManager, PlantDirector, FormulationChemist |
| GET | `/cosmfg/production-orders` | List production orders with filters | CustomerRep, ProductionPlanner, QAManager, PlantDirector |
| PATCH | `/cosmfg/production-orders/{id}` | Update requested_units of a DRAFT order; OCC-guarded on the order's version | CustomerRep |
| POST | `/cosmfg/production-orders/{id}/confirm` | Confirm a DRAFT order; pins formula_version_seq and debits credit exposure | CustomerRep |
| POST | `/cosmfg/production-orders/{id}/cancel` | Cancel a non-terminal order with allocation, run, shortfall, and credit cascades | CustomerRep, ProductionPlanner |
| POST | `/cosmfg/production-orders/{id}/resume` | Resume an ON_HOLD order once its formula has recovered | ProductionPlanner |
| GET | `/cosmfg/production-orders/{id}/batches` | List batches of an order | ProductionPlanner, QAManager, PlantDirector |
| GET | `/cosmfg/production-orders/{id}/allocations` | List allocations of an order | ProductionPlanner, QAManager, PlantDirector, CustomerRep |
| GET | `/cosmfg/production-orders/{id}/shortfalls` | List shortfall cases of an order | ProductionPlanner, CustomerRep, PlantDirector |
| GET | `/cosmfg/production-orders/{id}/filling-runs` | List filling runs of an order | ProductionPlanner, QAManager, PlantDirector |
| POST | `/cosmfg/production-orders/{id}/allocations` | Reserve component lots for a CONFIRMED or IN_PRODUCTION order | ProductionPlanner |
| POST | `/cosmfg/production-orders/{id}/batches` | Plan a compounding batch for a CONFIRMED or IN_PRODUCTION order | ProductionPlanner |
| GET | `/cosmfg/batches/{id}` | Get a batch | ProductionPlanner, QAManager, PlantDirector |
| GET | `/cosmfg/batches/{id}/filling-runs` | List filling runs drawing on a batch | ProductionPlanner, QAManager, PlantDirector |
| POST | `/cosmfg/batches/{id}/approve-scale-up` | Approve scale-up for a batch above the scale-up threshold | PlantDirector |
| POST | `/cosmfg/batches/{id}/start-mixing` | Start compounding a PLANNED batch (scale-up and mass-balance enforced) | ProductionPlanner |
| POST | `/cosmfg/batches/{id}/ipc-checks` | Record an in-process viscosity or pH measurement on a MIXING batch | QAManager |
| GET | `/cosmfg/batches/{id}/ipc-checks` | List IPC checks of a batch (append-only log) | QAManager, ProductionPlanner, PlantDirector |
| POST | `/cosmfg/batches/{id}/adjust` | Send an IPC_FAILED batch back to MIXING (retry budget enforced) | QAManager |
| POST | `/cosmfg/batches/{id}/release` | Release an IPC_PASSED batch to filling (segregation of duties enforced) | QAManager |
| POST | `/cosmfg/batches/{id}/reject` | Reject a MIXING or IPC_FAILED batch; reserved materials consumed as waste | QAManager |
| POST | `/cosmfg/production-orders/{id}/shortfalls` | Declare a customer-supplied component shortfall against an order | ProductionPlanner |
| GET | `/cosmfg/shortfalls/{id}` | Get a shortfall case | ProductionPlanner, CustomerRep, PlantDirector |
| GET | `/cosmfg/shortfalls` | List shortfall cases with filters | ProductionPlanner, CustomerRep, PlantDirector |
| POST | `/cosmfg/shortfalls/{id}/commit` | Customer commits to deliver the shorted quantity by a date | CustomerRep |
| POST | `/cosmfg/shortfalls/{id}/escalate` | Escalate an unresolved shortfall: reduce the order or cancel it | ProductionPlanner |
| GET | `/cosmfg/allocations/{id}` | Get a component allocation | ProductionPlanner, QAManager, PlantDirector |
| GET | `/cosmfg/allocations` | List allocations filtered by order, batch, or lot | ProductionPlanner, QAManager, PlantDirector |
| POST | `/cosmfg/allocations/{id}/release` | Manually release a RESERVED allocation back to its lot | ProductionPlanner |
| POST | `/cosmfg/stability-chambers` | Register a stability chamber with a study capacity | QAManager |
| GET | `/cosmfg/stability-chambers/{id}` | Get a stability chamber | QAManager, PlantDirector, ProductionPlanner |
| GET | `/cosmfg/stability-chambers/{id}/studies` | List studies occupying a chamber | QAManager, PlantDirector |
| POST | `/cosmfg/formulas/{id}/stability-studies` | Start a stability study for an APPROVED or ACTIVE formula | QAManager |
| GET | `/cosmfg/stability-studies/{id}` | Get a stability study | QAManager, PlantDirector |
| POST | `/cosmfg/stability-studies/{id}/readings` | Record the next interval reading of a study | QAManager |
| GET | `/cosmfg/stability-studies/{id}/readings` | List readings of a study | QAManager, PlantDirector |
| POST | `/cosmfg/filling-lines` | Register a filling line | ProductionPlanner |
| GET | `/cosmfg/filling-lines` | List filling lines, filtered by status or current run | ProductionPlanner, QAManager, PlantDirector |
| GET | `/cosmfg/filling-lines/{id}` | Get a filling line | ProductionPlanner, QAManager, PlantDirector |
| GET | `/cosmfg/filling-lines/{id}/runs` | List runs scheduled on a line | ProductionPlanner, PlantDirector, QAManager |
| POST | `/cosmfg/filling-lines/{id}/finish-cleaning` | Finish cleaning: CLEANING to IDLE | ProductionPlanner |
| POST | `/cosmfg/production-orders/{id}/filling-runs` | Schedule a filling run on a line (overlap and changeover-gap enforced) | ProductionPlanner |
| GET | `/cosmfg/filling-runs/{id}` | Get a filling run | ProductionPlanner, QAManager, PlantDirector |
| POST | `/cosmfg/filling-runs/{id}/start` | Start a SCHEDULED run (requires RELEASED_TO_FILLING batch and IDLE line) | ProductionPlanner |
| POST | `/cosmfg/filling-runs/{id}/complete` | Complete an IN_PROGRESS run, recording good and rejected units | ProductionPlanner |
| POST | `/cosmfg/filling-runs/{id}/abort` | Abort a SCHEDULED or IN_PROGRESS run | ProductionPlanner |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-05-01T00:00:00Z) | PlantDirector, ProductionPlanner, QAManager |

## 5. Error Code Catalogue

Trigger conditions for every error are specified in §2 and §3 alongside the workflows they guard; this catalogue enumerates only identifiers and status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CONFIDENTIALITY_VIOLATION` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LOT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SCALE_UP_APPROVAL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_IPC_ATTEMPTS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_STUDY_FAILED_BLOCKS_RELEASE` | 409 Conflict |
| `ERR_BATCH_UNDER_ALLOCATED` | 422 Unprocessable Entity |
| `ERR_COMPONENT_OWNERSHIP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_VARIANT_WAIVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_FORMULA_CUSTOMER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FORMULA_NOT_ACTIVE` | 409 Conflict |
| `ERR_INCI_REVIEW_NOT_APPROVED` | 409 Conflict |
| `ERR_REVIEW_ALREADY_OPEN` | 409 Conflict |
| `ERR_BATCH_ORDER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LINE_OCCUPIED` | 409 Conflict |
| `ERR_CHANGEOVER_GAP_VIOLATION` | 409 Conflict |
| `ERR_CHAMBER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_READING_INTERVAL_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_NO_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_LOT_INSUFFICIENT_QUANTITY` | 422 Unprocessable Entity |
| `ERR_OVER_DELIVERY` | 422 Unprocessable Entity |
| `ERR_PLANNED_UNITS_EXCEED_BATCH` | 422 Unprocessable Entity |
| `ERR_BATCH_NOT_RELEASED` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_BELOW_MINIMUM_RUN` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
