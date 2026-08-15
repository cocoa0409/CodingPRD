# Nutrition Labeling & Regulatory Review API — Product Requirements Document

## 1. Introduction

A food manufacturer shipping the same product into the United States and Canada answers to two labeling regimes at once: serving sizes derived from reference amounts customarily consumed, nutrient values substantiated either by recipe-to-database calculation or by laboratory assay, claims gated by per-serving disqualifiers and per-reference-amount thresholds, allergen and ingredient statements held to a canonical form, and nutrition panel formats constrained by the physical package. Consultancies that shepherd manufacturers through this process currently track it across spreadsheets, email threads, and artwork proofs — a workflow in which a reformulated recipe can silently invalidate an approved label, and nobody notices until a regulator or a retailer does.

This document specifies the Nutrition Labeling & Regulatory Review API, the system of record for that consultancy workflow. The platform covers client and product registration, ingredient nutrient databases, recipe formulation with lock-based change control, laboratory analysis review, nutrient panel computation under both the database and laboratory methods, serving-size determination per market, label drafting with regulatory review and release gating, on-pack claim eligibility, cross-market label variants, and scheduled artwork audits that score conformance between what is printed on the pack and what was approved. A central design commitment is freshness propagation: when the substantiation beneath a label changes — a recipe is superseded, a lab analysis is displaced, a panel goes stale — every dependent claim and label content flag is recomputed immediately, so that a stale label cannot be released by accident.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request with either header missing or malformed, or naming a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly six roles: `PlatformAdmin`, `ClientRep`, `LabelAnalyst`, `RegulatoryReviewer`, `QualityManager`, and `ComplianceAuditor`. Each operation in this document names the roles authorized to invoke it; a caller whose role is not authorized, or whose entity-backed identity does not own the resource chain being touched, is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The roles' identities resolve as follows. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform operator onboards clients and drives the logical clock. When `X-User-Role` is `ClientRep`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that belongs to a client compare the resource's client chain to `X-User-ID`, and a client representative may only register products, ingredients, recipes, and lab submissions for their own client. When `X-User-Role` is `LabelAnalyst`, `X-User-ID` is an opaque operator identifier; the server records it as `prepared_by` on each label version the analyst creates but does not compare it to any entity's `id`. When `X-User-Role` is `RegulatoryReviewer`, `X-User-ID` is likewise opaque; it is recorded as `reviewed_by` on lab analyses the reviewer decides and as `approved_by` on label versions the reviewer approves. When `X-User-Role` is `QualityManager`, `X-User-ID` is again the `id` of the acting `Client`, with the same client-chain ownership checks as `ClientRep`. When `X-User-Role` is `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier for the field auditor.

Read access is broad but scoped: all six roles may invoke every retrieval and listing operation, except that the two entity-backed roles — `ClientRep` and `QualityManager` — may only read resources inside their own client chain, and reads outside that chain are rejected with `ERR_FORBIDDEN_FOR_ROLE`. One further auth rule is wired to a single workflow: segregation of duties requires that the reviewer who approves a label be a different person than the analyst who prepared it, so the approving request's `X-User-ID` must differ from the label's `prepared_by`, failing which the approval is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

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

List endpoints paginate through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource type in the system — clients, products, ingredients, recipes, lab analyses, nutrient panels, RACC assignments, label versions, claim assessments, market variants, format checks, artwork audits, and audit findings — carries a uniform set of system-managed fields: an `id`, which is a server-minted UUID with no type prefix; a `created_at` timestamp in ISO 8601 UTC form with three fractional digits; an `updated_at` timestamp of the same form, refreshed on every mutation; and a `version` integer that increments by one on every mutation. No resource type in this system omits `updated_at` or `version`. Mutations performed by the system itself as cascade side effects — a recipe flipped to `SUPERSEDED`, a panel to `STALE`, a label version counter advanced during submit-review or release — count as mutations of the affected resource and therefore update its `updated_at` and increment its `version` just as a client-initiated change would.

### 2.5. Numeric Precision and the Rounding Discipline

Declared nutrient values throughout the system are rounded to exactly 2 decimal places using the round-half-up method, and are represented in responses as numbers, not strings. This applies to every per-100-gram value declared on a nutrient panel and to every compared value in claim evaluation. One ordering rule is pinned and non-negotiable: all downstream quantities — per-RACC claim inputs, per-serving declarations — are computed from the raw, unrounded per-100-gram values, never from the two-decimal declared values. Rounding first and then scaling can flip a declaration across a rounding-tier boundary; the raw path is authoritative in every such computation. Audit conformance scores are integers. Format-compliance tier boundaries and serving-size package ratios are compared as exact decimals, without tolerance.

### 2.6. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, both pinned to the parent `Product`: creating a label-version draft, and releasing a label version. Each of these requests must carry the field `expected_product_version`, holding the value of the product's `version` as the client last observed it. If another writer has advanced the product's version since that observation — for example because a draft was created that withdrew the prior draft, or a competing release superseded the prior release — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from acting on a product state it never saw. No other endpoint accepts a version field.

### 2.7. The Logical Clock and Time-Window Semantics

All time-dependent rules in the system read a logical clock rather than the wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any administrative set call, the clock continues to read this default and never falls back to wall-clock time. A `PlatformAdmin` may advance the logical clock through a test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`.

Two families of time windows build on this clock. Market-variant effective windows are half-open intervals: the window includes `effective_start`, excludes `effective_end`, and a missing `effective_end` means the window is open-ended; two windows that merely touch at a boundary do not overlap. Artwork-audit facility scheduling uses a one-day buffer: a new audit window at a facility must begin no earlier than 86,400 seconds after an existing window ends, or end no later than 86,400 seconds before the existing window begins, with equality at the boundary permitted.

### 2.8. Request Validation Order and Nested Resource Retrieval

Every request is validated against a fixed priority sequence, and the first failing check determines the error returned. Within a single priority level, the individual rules apply in the order this document lists them.

1. **User context.** The `X-User-ID` and `X-User-Role` headers are present, well-formed, and name a recognized role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Authorization.** The caller's role is authorized for the endpoint, entity-backed callers stay inside their own client chain (`ERR_FORBIDDEN_FOR_ROLE`), and — on label approval only — the approver differs from `prepared_by` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`).
3. **Existence, then body shape.** Path identifiers are resolved left to right, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve; the same error covers body-supplied references such as `racc_assignment_id`, `product_id`, or `label_version_id` that do not exist, and any recipe line whose `ingredient_id` does not exist within the client's ingredient scope. Only after existence is established is the body's well-formedness checked — required fields present, enum members valid, numbers positive where required, `yield_factor` inside its allowed band, recipe lines non-empty with distinct ingredient references — failing which the request is rejected with `ERR_INVALID_REQUEST`.
4. **State and concurrency.** Optimistic-concurrency mismatches (`ERR_STALE_VERSION`), from-state preconditions of every action (`ERR_INVALID_STATE_TRANSITION`), lab double-decision (`ERR_LAB_REVIEW_ALREADY_DECIDED`), recipe-lock requirements (`ERR_RECIPE_NOT_LOCKED`), panel currency (`ERR_PANEL_NOT_CURRENT`), review-state requirements (`ERR_LABEL_NOT_IN_REVIEW`, `ERR_LABEL_NOT_APPROVED`), and content readiness (`ERR_CONTENT_REVISION_REQUIRED`). Notably, the release operation evaluates its gates in a fixed order: approval state first (`ERR_LABEL_NOT_APPROVED`), then content readiness (`ERR_CONTENT_REVISION_REQUIRED`), then claim resolution (`ERR_CLAIMS_NOT_RESOLVED`), then format compliance (`ERR_FORMAT_CHECK_FAILED`).
5. **Statement safety.** The canonical allergen statement check (`ERR_ALLERGEN_STATEMENT_INCOMPLETE`) and the canonical ingredient-ordering check (`ERR_INGREDIENT_ORDER_VIOLATION`).
6. **Uniqueness and overlap.** Duplicate RACC assignment (`ERR_RACC_ALREADY_ASSIGNED`), duplicate market variant (`ERR_DUPLICATE_MARKET_VARIANT`), variant window overlap (`ERR_MARKET_WINDOW_OVERLAP`), and facility scheduling conflicts (`ERR_FACILITY_SCHEDULE_OVERLAP`).
7. **Temporal coherence.** Malformed windows (`ERR_WINDOW_INVALID`) and activation outside the effective window (`ERR_VARIANT_NOT_IN_WINDOW`).
8. **Referential and profile completeness.** Ingredient nutrient-profile completeness (`ERR_NUTRIENT_PROFILE_INCOMPLETE`), validated-lab availability (`ERR_NO_VALIDATED_LAB_ANALYSIS`), RACC category coverage (`ERR_RACC_CATEGORY_UNKNOWN`), serving-size resolvability (`ERR_SERVING_SIZE_UNRESOLVABLE`), RACC market alignment (`ERR_RACC_MARKET_MISMATCH`), distinct-market rule for variants (`ERR_SAME_MARKET_VARIANT`), and audit scope consistency (`ERR_AUDIT_SCOPE_INCONSISTENT`).

The left-to-right rule for nested paths deserves emphasis: a request targeting a resource beneath a parent that does not exist fails on the parent first, and the system never reports a missing child when an ancestor is already missing.

### 2.9. The Dual-Market Regulatory Model

The platform serves two markets, identified everywhere by the exact codes `US_FDA` and `CA_CFIA`. A client's `home_market_code` records its primary market, while individual serving-size determinations, label versions, and market variants each carry their own `market_code`. Both markets share the same reference-amount table: a `BAKED_GOOD` carries a reference amount of 55 grams, a `BEVERAGE` 240 grams, `CEREAL` 40 grams, `SNACK` 30 grams, `DAIRY` 170 grams, `SAUCE` 30 grams, `CONFECTION` 40 grams, and `FROZEN_DESSERT` 90 grams. The markets diverge in three places, each detailed where it applies: serving-size rounding is household-measure-first under `US_FDA` but metric-first under `CA_CFIA`; the claim types `SUGAR_FREE` and `LOW_CALORIE` are unregulated in the Canadian market; and a variant destined for the other market may carry a localized allergen statement.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Product Registration

A `PlatformAdmin` onboards each food manufacturer as a **Client**, supplying a display `name` and the client's `home_market_code`. Once onboarded, a `ClientRep` of that client registers each **Product** with a `name`, a `product_category` drawn from `BAKED_GOOD`, `BEVERAGE`, `CEREAL`, `SNACK`, `DAIRY`, `SAUCE`, `CONFECTION`, or `FROZEN_DESSERT`, and the physical facts that later drive compliance math: `net_weight_g` for the net contents, `total_surface_area_sq_in` for the total package surface, and `pdp_area_sq_in` for the principal display panel. All three quantities must be greater than zero. The category is not decorative — it selects the row of the RACC table used at serving-size determination, and a category absent from the target market's table will surface there as `ERR_RACC_CATEGORY_UNKNOWN`.

Two optional fields complete the product profile: `household_unit_name` names the familiar measure (a piece, a tablespoon) and `household_unit_weight_g` gives the gram weight of one such unit, which must be greater than zero when present. Both may be omitted at registration, but serving-size determination for any package that is not a single-serving package requires `household_unit_weight_g` to be present and positive, and the American panel conventionally expresses the serving in `household_unit_name` terms. The owning client is carried on the product as `client_id`, assigned by the system from the path under which the product was registered.

### 3.2. Ingredient Catalogue and Recipe Formulation

Before any formulation work, the `ClientRep` builds the client's **Ingredient** catalogue. Each ingredient carries a declaration `name`, an `allergen_tags` list that defaults to empty and may draw from `MILK`, `EGGS`, `FISH`, `SHELLFISH`, `TREE_NUTS`, `PEANUTS`, `WHEAT`, `SOYBEAN`, and `SESAME`, and a nine-part database nutrient profile expressed per 100 grams: `kcal_per_100g`, `fat_g_per_100g`, `satfat_g_per_100g`, `chol_mg_per_100g`, `sodium_mg_per_100g`, `carb_g_per_100g`, `fiber_g_per_100g`, `sugar_g_per_100g`, and `protein_g_per_100g`. Any nutrient field may be omitted at creation; doing so marks the profile incomplete, and the omission is not policed until a database-method panel computation actually needs the value.

A **Recipe** is created under a product with a formulation `name`, a `yield_factor`, and a `lines` array in which each line pairs an `ingredient_id` with a `quantity_g`. The yield factor — finished mass divided by raw mass — defaults to 1.0 and must be greater than 0 and at most 1.2. Every line quantity must be positive, the recipe needs at least one line, and the ingredient references must be distinct; violations of these shape rules are rejected with `ERR_INVALID_REQUEST`, while a line referencing an ingredient that does not exist in the client's catalogue is rejected with `ERR_NOT_FOUND`. A new recipe begins life in `DRAFT` status. The recipe records its parent product as `product_id`, and initially its `latest_validated_lab_analysis_id` is empty.

Locking is the pivotal act of formulation change control. A `ClientRep` locks a recipe that is currently `DRAFT` — locking from any other status is rejected with `ERR_INVALID_STATE_TRANSITION` — and the lock sets the recipe's `status` to `LOCKED` and increments its `version`. The cascade that follows is what makes the lock decisive: any sibling recipe of the same product that was `LOCKED` flips to `SUPERSEDED`, that superseded recipe's `CURRENT` nutrient panels flip to `STALE`, every claim assessment on that product's labels whose basis panel just went stale flips to `SUSPENDED`, and each affected label version's `content_status` is recomputed to `NEEDS_REVISION`. `SUPERSEDED` is terminal for a recipe; the same panel-and-claim staleness cascade applies whenever the system moves a recipe there.

Because statement drafting leans on the canonical formulation order, the platform exposes a computed statement capability for the product's currently `LOCKED` recipe. The canonical order sorts the recipe's lines by `quantity_g` descending, breaks ties by the ingredient's `created_at` ascending, and breaks any remaining tie by ingredient `name` ascending. The returned `ingredient_statement_text` is the comma-joined ingredient names in that order. The returned `contains_text` is built from the distinct allergen tags in the order they first appear along the canonical line order, rendered as the literal prefix `Contains: `, the comma-joined tags, and a closing period; when no line carries any allergen tag, the canonical statement is exactly `Contains: None.` A third returned element, `canonical_order`, exposes the ordered line sequence itself. String comparisons against these canonical forms are exact, performed after trimming outer whitespace.

### 3.3. Laboratory Substantiation of Nutrient Values

A client that prefers assayed values over database estimates submits a **LabAnalysis** against a recipe. The `ClientRep` supplies the external `lab_report_ref` and the nine measured values — `kcal_per_100g` (which may carry up to three decimal places), `fat_g_per_100g`, `satfat_g_per_100g`, `chol_mg_per_100g`, `sodium_mg_per_100g`, `carb_g_per_100g`, `fiber_g_per_100g`, `sugar_g_per_100g`, and `protein_g_per_100g` — and the analysis enters in `SUBMITTED` status, linked to its recipe through `recipe_id`.

Only a `RegulatoryReviewer` may decide an analysis, and the decision is expressed through an `outcome` of `VALIDATED` or `REJECTED`. A second decision attempt on an analysis that has already left `SUBMITTED` is rejected with `ERR_LAB_REVIEW_ALREADY_DECIDED`. Rejection is simple: the reviewer stamps the decision, `reviewed_by` records the reviewer's `X-User-ID`, and the analysis settles in `REJECTED`, a terminal state. Validation is conditional on the parent recipe being `LOCKED` — validating against an unlocked recipe is rejected with `ERR_RECIPE_NOT_LOCKED` — and it triggers the second of the platform's great cascades. The validating reviewer's identity lands in `reviewed_by`; the recipe's `latest_validated_lab_analysis_id` is repointed to this analysis; any other `VALIDATED` analysis of the same recipe is moved by the system to `SUPERSEDED`; every lab-method panel whose `basis_lab_analysis_id` names the superseded analysis flips to `STALE`; claim assessments whose `basis_panel_id` went stale flip to `SUSPENDED`; and every label version carrying a newly suspended claim has its `content_status` recomputed to `NEEDS_REVISION`. When the system later supersedes a validated analysis for any reason, its derived panels go stale in exactly the same way.

### 3.4. Nutrient Panel Computation and the Rounding Pipeline

A `LabelAnalyst` computes a **NutrientPanel** for a `LOCKED` recipe — any other recipe status is rejected with `ERR_RECIPE_NOT_LOCKED` — by naming a `method` of `DATABASE` or `LAB`. The panel is linked to its recipe via `recipe_id` and enters as `CURRENT`. Under the database method, the computation walks every line of the recipe: each nutrient's contribution from a line is the ingredient's per-100-gram value for that nutrient multiplied by the line's `quantity_g` and divided by 100; the contributions are summed across lines into a raw total per nutrient; the finished mass is the sum of all line quantities multiplied by the recipe's `yield_factor`; and each raw per-100-gram value is the nutrient's raw total divided by the finished mass and multiplied by 100. This path demands complete data — if any line ingredient has even one of its nine nutrient fields null, the computation is rejected with `ERR_NUTRIENT_PROFILE_INCOMPLETE`. Under the laboratory method, the panel adopts the recipe's most recently validated analysis exactly as measured, decimals and all; when the recipe has no validated analysis — `latest_validated_lab_analysis_id` empty — the request is rejected with `ERR_NO_VALIDATED_LAB_ANALYSIS`, and when one exists the panel records it in `basis_lab_analysis_id`. The two methods legitimately disagree: identical recipes yield different panel numbers depending on the method.

Whichever the method, the panel's declared per-100-gram fields — `kcal_per_100g`, `fat_g_per_100g`, `satfat_g_per_100g`, `chol_mg_per_100g`, `sodium_mg_per_100g`, `carb_g_per_100g`, `fiber_g_per_100g`, `sugar_g_per_100g`, `protein_g_per_100g` — are the raw values rounded half-up to two decimal places, while the unrounded vector remains the basis for everything downstream, per the pinned rounding discipline of §2.5. Per-serving declarations add a second, tiered rounding step applied to the raw value scaled by the serving size: calories below 5 declare as 0, calories at most 50 round to the nearest 5, and calories above 50 round to the nearest 10; sodium below 5 milligrams declares as 0, at most 140 rounds to the nearest 5, and above 140 rounds to the nearest 10; fat, fiber, and sugars below half a gram declare as 0, below 5 grams round to the nearest half gram, and at 5 grams or more round to the nearest whole gram. "Nearest" throughout means halves round up — equivalently, divide the value by the step, add one half, truncate down to a whole number, and multiply back by the step. Scaling first and tier-rounding second is the authoritative order; tier-rounding the two-decimal per-100-gram value instead can flip a declaration across a boundary.

Panel freshness propagates in both directions of time. A panel leaves `CURRENT` only for `STALE`, driven by the system when its basis lab analysis is superseded or its parent recipe is superseded, and that transition suspends every claim assessed against the panel and recomputes the content status of every label that pinned it. In the other direction, the arrival of a new `CURRENT` panel for a recipe and method is the trigger that re-evaluates claims previously suspended on labels using that recipe and nutrient basis, with each label's `content_status` recomputed from the outcome. Panels can be listed per recipe with an optional `method` filter, and a global panel listing accepts a `basis_lab_analysis_id` filter for reverse reachability from an analysis to the panels it substantiates. A companion listing of recipes accepts a `latest_validated_lab_analysis_id` filter, letting an auditor walk backward from a lab report to every recipe that currently rests on it.

### 3.5. Serving-Size Determination

Serving sizes are not typed in; they are determined. A `LabelAnalyst` requests a **RaccAssignment** for a product by naming the target `market_code`, and at most one assignment may exist per product and market — a second request for the same pair is rejected with `ERR_RACC_ALREADY_ASSIGNED`. The determination proceeds in a pinned order. First, the reference amount `racc_g` is read from the market's RACC table by the product's `product_category`; an unknown category is rejected with `ERR_RACC_CATEGORY_UNKNOWN`. Second, the package ratio is computed as `net_weight_g` divided by `racc_g` — deliberately against the reference amount, not against any serving size, because the serving size is what is being derived. Third, the ratio selects the `label_mode`: below 2.0 the package is `SINGLE_SERVING`; at least 2.0 and at most 3.0 it is `DUAL_COLUMN`; above 3.0 it is `STANDARD`.

The serving size itself then follows the market variant. A `SINGLE_SERVING` package declares `serving_size_g` equal to the whole `net_weight_g`, exactly 1 `serving_household_units`, and 1 `servings_per_container`, with no household-measure data required. Otherwise the `US_FDA` path works household-first: the raw unit count is `racc_g` divided by `household_unit_weight_g` — a missing or zero unit weight is rejected with `ERR_SERVING_SIZE_UNRESOLVABLE` — and `serving_household_units` is that raw count rounded to the nearest half unit with halves rounding up (double the raw count, add one half, truncate down to a whole number, then halve it); `serving_size_g` is then the rounded units multiplied by the unit weight, rounded half-up to two decimal places. The `CA_CFIA` path works metric-first: `serving_size_g` is the reference amount rounded to the nearest 5 grams when `racc_g` is at least 50 grams, or to the nearest 1 gram below that, halves rounding up in both cases; `serving_household_units` is then derived as the serving size divided by `household_unit_weight_g`, rounded half-up to two decimal places, with the same missing-or-zero guard producing `ERR_SERVING_SIZE_UNRESOLVABLE`. Because the two variants round in different orders, the same product can carry different serving sizes and container counts in the two markets.

Finally, `servings_per_container` for non-single-serving packages divides `net_weight_g` by the computed `serving_size_g` and rounds the count by band: below 2 it declares 1; at least 2 and at most 5 it rounds to the nearest half with halves up; above 5 it rounds to the nearest whole number with halves up. The assignment records the parent product as `product_id` and persists every derived quantity — `racc_g`, `label_mode`, `serving_size_g`, `serving_household_units`, and `servings_per_container` — for labels to pin.

### 3.6. Label Drafting, Regulatory Review, and Release

A **LabelVersion** is the unit of artwork change control. A `LabelAnalyst` creates a draft under a product, declaring the target `market_code`, the `nutrient_basis` (`DATABASE` or `LAB`) the panel will rest on, the `racc_assignment_id` pinning the serving-size determination, the `declared_format` (`STANDARD_VERTICAL`, `SIMPLIFIED`, `TABULAR`, or `LINEAR`), the smallest nutrient type size on the artwork as `declared_type_size_in` (which must be greater than zero), and the two drafted statements, `ingredient_statement_text` and `contains_text`. The pinned assignment must belong to the same product and target the same market, failing which creation is rejected with `ERR_RACC_MARKET_MISMATCH` — while an assignment id that does not exist at all fails earlier as `ERR_NOT_FOUND`. Creation is one of the two optimistic-concurrency points described in §2.6 and must carry `expected_product_version`. Because only one draft per product and market may be in flight, creating the draft withdraws any existing `DRAFT` label version for the same product and market, moving its `review_status` to `WITHDRAWN`. The new draft initializes with `review_status` `DRAFT`, `release_status` `NOT_RELEASED`, `review_round` 0, and `prepared_by` set to the creating analyst's `X-User-ID`; the product's `version` increments as part of the same write.

Submitting the draft for review is the moment of crystallization. The label must be in `DRAFT` review status — anything else is rejected with `ERR_INVALID_STATE_TRANSITION` — the product must have a currently `LOCKED` recipe (`ERR_RECIPE_NOT_LOCKED`), and a `CURRENT` panel must exist for that recipe whose method matches the label's `nutrient_basis` (`ERR_PANEL_NOT_CURRENT`). Two statement checks then run against the canonical forms of §3.2: a `contains_text` that does not equal the canonical allergen statement for the locked recipe's lines is rejected with `ERR_ALLERGEN_STATEMENT_INCOMPLETE`, and an `ingredient_statement_text` that does not equal the canonical descending-weight ordering is rejected with `ERR_INGREDIENT_ORDER_VIOLATION`. On success the submission pins `panel_snapshot_id` to the most recently created `CURRENT` panel of the recipe with the matching method, advances `review_round` by one, auto-creates a format check, recomputes `content_status`, moves `review_status` to `IN_REVIEW`, and increments the label's `version`.

The auto-created **FormatCheck** evaluates the artwork against the package registered on the product. The allowed format set comes from `total_surface_area_sq_in`: a package of at most 12.0 square inches may carry only `LINEAR`; a package greater than 12.0 and at most 40.0 square inches may carry `SIMPLIFIED`, `TABULAR`, or `STANDARD_VERTICAL`; a package greater than 40.0 square inches must carry `STANDARD_VERTICAL`. The minimum type size comes from `pdp_area_sq_in`: a principal display panel of at most 5.0 square inches requires 0.03125 inches, and a larger panel requires 0.0625 inches. A `declared_format` outside the allowed set records the violation `FORMAT_NOT_ALLOWED_FOR_PACKAGE`; a `declared_type_size_in` below the tier minimum records `TYPE_SIZE_BELOW_MIN`. The check persists its `allowed_formats`, `min_type_size_in`, and the `violations` list, and its `result` is `PASS` exactly when the violations list is empty, otherwise `FAIL`. Format failures never touch `content_status`; they gate the release step instead, and a label may accumulate several format checks across review rounds, each retrievable through the label's format-check listing.

Review concludes in one of two directions. Approval by a `RegulatoryReviewer` requires the label to be `IN_REVIEW` (`ERR_LABEL_NOT_IN_REVIEW` otherwise), requires the approver's `X-User-ID` to differ from `prepared_by` per the segregation-of-duties rule (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`), and requires `content_status` to be `READY` (`ERR_CONTENT_REVISION_REQUIRED`). Approval stamps `approved_by`, moves `review_status` to `APPROVED`, and increments `version`. Rejection moves the label from `IN_REVIEW` back to `DRAFT` — the same `ERR_LABEL_NOT_IN_REVIEW` guard applies — optionally recording a free-text `reason`, clearing `approved_by`, and deliberately leaving the declared content untouched: `ingredient_statement_text`, `contains_text`, `declared_format`, `declared_type_size_in`, and the pinned `panel_snapshot_id` all survive rejection unchanged, so the analyst can correct and resubmit without re-entering the artwork facts.

Release is a `QualityManager` act with a gauntlet of gates, evaluated in the fixed order of §2.8: the label must be `APPROVED` with `release_status` `NOT_RELEASED` (`ERR_LABEL_NOT_APPROVED`), `content_status` must be `READY` (`ERR_CONTENT_REVISION_REQUIRED`), every claim on the label must be `ELIGIBLE` or `NOT_REQUIRED` — a claim still `PENDING`, `SUSPENDED`, or `INELIGIBLE` blocks release with `ERR_CLAIMS_NOT_RESOLVED` — and the most recently created format check must be `PASS` (`ERR_FORMAT_CHECK_FAILED`). Release is the second optimistic-concurrency point: the request must carry `expected_product_version` matching the product's current `version`, failing which `ERR_STALE_VERSION` is returned. A successful release moves `release_status` to `RELEASED`, flips any other `RELEASED` label version of the same product and market to `SUPERSEDED` while stamping its `superseded_by_id` with the newly released label's id, and increments both the product's and the label's `version`. Withdrawal is the compensating mirror: a `QualityManager` withdraws a label that is `RELEASED` (any other release status is rejected with `ERR_INVALID_STATE_TRANSITION`), optionally supplying a `reason`; the label moves to `WITHDRAWN`, the label whose `superseded_by_id` points at the withdrawn one is restored to `RELEASED`, and again both the product's and the label's `version` increment. The same-product-and-market supersede chain means label listings support reverse lookups — the global label-version listing accepts `racc_assignment_id`, `panel_snapshot_id`, and `superseded_by_id` filters, so a reviewer can enumerate every label resting on a given assignment or panel snapshot, or walk the supersede chain directly.

### 3.7. Claim Eligibility and Content Freshness

An on-pack claim is declared by a `LabelAnalyst` as a **ClaimAssessment** under a label version, naming a `claim_type` of `LOW_FAT`, `FAT_FREE`, `LOW_SODIUM`, `HIGH_FIBER`, `SUGAR_FREE`, or `LOW_CALORIE`. Claims may only be added while the label's `review_status` is `DRAFT` or `IN_REVIEW`; attempts on labels in any other review state are rejected with `ERR_INVALID_STATE_TRANSITION`, and a product without a currently `LOCKED` recipe fails with `ERR_RECIPE_NOT_LOCKED`. Evaluation is synchronous at creation and always reads the most recent `CURRENT` panel of the label's locked recipe whose method equals the label's `nutrient_basis`, together with the `racc_g` and `serving_size_g` of the pinned RACC assignment. Two compared values are derived per nutrient, each rounded half-up to two decimals from the raw per-100-gram vector: the per-RACC value scales by `racc_g`, and the per-serving value scales by `serving_size_g`.

The evaluation order is pinned. First, market recognition: the Canadian market does not regulate `SUGAR_FREE` or `LOW_CALORIE`, so a claim of either type on a `CA_CFIA` label settles immediately as `NOT_REQUIRED`, leaving `evaluated_value_per_racc`, `threshold_value`, and `disqualified_by` empty. Second, disqualifiers on the per-serving values, checked in the fixed order fat, then saturated fat, then cholesterol, then sodium: total fat strictly above 13.0 grams, saturated fat strictly above 4.0 grams, cholesterol strictly above 60.0 milligrams, or sodium strictly above 480.0 milligrams per serving each disqualify, the first breach hit determines `disqualified_by` as `FAT`, `SATFAT`, `CHOL`, or `SODIUM`, and any breach renders the claim `INELIGIBLE`. Third, the claim's own threshold on the per-RACC value, identical in both markets where regulated: `FAT_FREE` requires fat below 0.5 grams; `LOW_FAT` fat at most 3.0 grams; `SUGAR_FREE` sugars below 0.5 grams; `LOW_SODIUM` sodium at most 140 milligrams; `HIGH_FIBER` fiber at least 5.0 grams; `LOW_CALORIE` at most 40 calories. Meeting the threshold settles the claim `ELIGIBLE`; missing it settles `INELIGIBLE`, with `disqualified_by` recorded as `NONE` when no disqualifier fired. Every evaluated claim persists `evaluated_value_per_racc`, the `threshold_value` that was applied, `disqualified_by`, and the `basis_panel_id` of the panel used.

A claim begins in `PENDING` and leaves it within the same request. Thereafter its health tracks its basis panel: when the panel goes `STALE` through either cascade of §3.2 and §3.3, an `ELIGIBLE` claim is suspended, and the owning label's `content_status` flips to `NEEDS_REVISION`. When a new `CURRENT` panel later appears for the label's recipe and nutrient basis, each suspended claim re-evaluates against it: a passing evaluation returns the claim to `ELIGIBLE` and repoints `basis_panel_id` to the new panel, while a failing evaluation settles it as `INELIGIBLE`; either way the label's content status is recomputed. That derived flag follows one rule everywhere: `content_status` is `NEEDS_REVISION` whenever any claim on the label is `SUSPENDED`, or the product's locked recipe has changed out from under the label's pinned basis, or the pinned panel snapshot has gone `STALE` — and it is `READY` when none of those hold. Format-check outcomes play no part in this flag; their only teeth are at the release gate. Claim listings per label are complemented by a global claim listing that accepts a `basis_panel_id` filter, tracing every assessment resting on a given panel.

### 3.8. Market Variants and Artwork Audits

When an approved label must ship into the other market, a `LabelAnalyst` creates a **MarketVariant** under the base label version, naming the target `market_code`, an `effective_start`, an optional `effective_end`, and an optional `translated_contains_text` carrying the localized allergen statement. The target market must differ from the base label's market — a same-market variant is rejected with `ERR_SAME_MARKET_VARIANT` — and only one non-retired variant may exist per base label and target market (`ERR_DUPLICATE_MARKET_VARIANT`). The effective window must be well-formed, with `effective_end`, when present, strictly after `effective_start` (`ERR_WINDOW_INVALID`), and it must not overlap the windows of other non-retired variants for the same product and market under the half-open semantics of §2.7 — adjacency is allowed, overlap is `ERR_MARKET_WINDOW_OVERLAP`. A new variant starts in `DRAFT` status.

Activation and retirement belong to the `QualityManager`. Activation requires the variant to be `DRAFT` (`ERR_INVALID_STATE_TRANSITION`), requires the base label's `review_status` to be `APPROVED` (`ERR_LABEL_NOT_APPROVED`), and requires the logical clock to read at or after `effective_start` and — when the window is bounded — strictly before `effective_end` (`ERR_VARIANT_NOT_IN_WINDOW`); the overlap check against sibling non-retired variants is re-run at this moment, so a window that became conflicting since creation is still caught with `ERR_MARKET_WINDOW_OVERLAP`. Activation moves the variant to `ACTIVE` and increments its `version`. Retirement moves an `ACTIVE` variant to `RETIRED` — again guarded by `ERR_INVALID_STATE_TRANSITION` — increments `version`, and frees its window for future variants.

The audit half of the platform verifies that what ships matches what was approved. A `ComplianceAuditor` schedules an **ArtworkAudit** under a client, naming the `product_id`, the `label_version_id` of the approved-artwork baseline, the `facility_code` where on-pack sampling occurs, a `scheduled_start` and `scheduled_end`, and optionally a `scoring_method` of `BINARY` or `WEIGHTED` that defaults to `WEIGHTED`. Scope is enforced before scheduling: the product must belong to the path client, and the label version must belong to that product and currently be `RELEASED`, failing which the request is rejected with `ERR_AUDIT_SCOPE_INCONSISTENT`; the scheduled window must end strictly after it begins (`ERR_WINDOW_INVALID`); and the facility itself is a contended resource — among audits still `SCHEDULED` or `FINDINGS_LOGGED` at the same `facility_code`, the new window must respect the one-day buffer of §2.7, failing which `ERR_FACILITY_SCHEDULE_OVERLAP` is returned. The audit opens in `SCHEDULED` status, with `conformance_score` and `result` empty until close. Audit listings accept `client_id`, `product_id`, and `label_version_id` filters.

Field work is recorded as **AuditFinding** entries under the audit, each linked to its parent through `audit_id` and carrying a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, a `field_ref` locating the discrepancy in `INGREDIENT_LIST`, `CONTAINS_STATEMENT`, `NUTRITION_VALUES`, `SERVING_SIZE`, `CLAIM_TEXT`, or `FORMAT`, and the two text exhibits: `on_pack_text` as observed on the physical pack and `approved_text` as it appears on the approved baseline. The first finding posted moves the audit from `SCHEDULED` to `FINDINGS_LOGGED` and increments its `version`; further findings may be posted while the audit remains `FINDINGS_LOGGED`. Closing the audit is permitted only from `FINDINGS_LOGGED` — closing straight from `SCHEDULED` with zero findings is rejected with `ERR_INVALID_STATE_TRANSITION` — and it is at close that scoring runs. Under `BINARY`, the `conformance_score` is 100 when the audit has no findings and 0 otherwise, and the `result` is `PASS` only at a score of 100. Under `WEIGHTED`, the score starts at 100, deducts 10 points per `CRITICAL` finding, 4 per `MAJOR`, and 1 per `MINOR`, floors at 0, and the `result` is `PASS` when the score is at least 90. The same finding set can therefore pass under the weighted method and fail under the binary one — the choice of `scoring_method` at scheduling time is a real compliance decision, and closing increments the audit's `version` one final time as `CLOSED`, its terminal state.

## 4. Endpoint Definitions

Operations that create a new resource — whether a stand-alone entity or a new member of a parent-scoped collection — return `201 Created`. Operations that act on an existing resource without creating a new one, including every state-transition action, return `200 OK`. All endpoints are mounted under the `/api` prefix. Retrieval endpoints are open to every role, subject to the client-chain scoping of §2.1 for `ClientRep` and `QualityManager`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/clients` | Onboard a client | PlatformAdmin |
| GET | `/api/clients/{id}` | Get a client | All roles |
| POST | `/api/clients/{id}/products` | Register a product for a client | ClientRep |
| GET | `/api/products/{id}` | Get a product | All roles |
| GET | `/api/clients/{id}/products` | List products of a client | All roles |
| POST | `/api/clients/{id}/ingredients` | Create an ingredient with its database nutrient profile | ClientRep |
| GET | `/api/clients/{id}/ingredients` | List ingredients of a client | All roles |
| POST | `/api/products/{id}/recipes` | Create a formulation whose lines reference the client's ingredients | ClientRep |
| GET | `/api/recipes/{id}` | Get a recipe | All roles |
| GET | `/api/products/{id}/recipes` | List recipes of a product | All roles |
| POST | `/api/recipes/{id}/lock` | Lock a DRAFT recipe; supersedes the previously LOCKED sibling and cascades staleness | ClientRep |
| GET | `/api/recipes/{id}/ingredient-statement` | Computed canonical ingredient and Contains statements for the product's LOCKED recipe | All roles |
| GET | `/api/recipes` | List recipes; optional filter `latest_validated_lab_analysis_id` | All roles |
| POST | `/api/recipes/{id}/lab-analyses` | Submit a lab assay for a recipe | ClientRep |
| GET | `/api/recipes/{id}/lab-analyses` | List lab analyses of a recipe | All roles |
| POST | `/api/lab-analyses/{id}/review` | Validate or reject a submitted lab analysis | RegulatoryReviewer |
| POST | `/api/recipes/{id}/nutrient-panels` | Compute a nutrient panel (DATABASE or LAB) for a LOCKED recipe | LabelAnalyst |
| GET | `/api/recipes/{id}/nutrient-panels` | List panels of a recipe; optional filter `method` | All roles |
| GET | `/api/nutrient-panels/{id}` | Get a nutrient panel | All roles |
| GET | `/api/nutrient-panels` | List panels; optional filter `basis_lab_analysis_id` | All roles |
| POST | `/api/products/{id}/racc-assignments` | Determine serving size for a market (one per product and market) | LabelAnalyst |
| GET | `/api/products/{id}/racc-assignments` | List RACC assignments of a product | All roles |
| POST | `/api/products/{id}/label-versions` | Create a label draft; withdraws the existing DRAFT for the same product and market | LabelAnalyst |
| GET | `/api/label-versions/{id}` | Get a label version | All roles |
| GET | `/api/products/{id}/label-versions` | List label versions of a product | All roles |
| GET | `/api/label-versions` | List label versions; optional filters `racc_assignment_id`, `panel_snapshot_id`, `superseded_by_id` | All roles |
| POST | `/api/label-versions/{id}/submit-review` | Submit a draft for regulatory review; pins the panel snapshot and auto-creates a format check | LabelAnalyst |
| POST | `/api/label-versions/{id}/approve` | Approve a label in review; approver must differ from the preparer | RegulatoryReviewer |
| POST | `/api/label-versions/{id}/reject` | Reject a label back to DRAFT; declared content is retained | RegulatoryReviewer |
| POST | `/api/label-versions/{id}/release` | Release an approved label; supersedes the prior release for the product and market | QualityManager |
| POST | `/api/label-versions/{id}/withdraw` | Withdraw a release; restores the label it superseded | QualityManager |
| POST | `/api/label-versions/{id}/claims` | Declare an on-pack claim; synchronously evaluated against the latest CURRENT panel | LabelAnalyst |
| GET | `/api/label-versions/{id}/claims` | List claims of a label version | All roles |
| GET | `/api/claims/{id}` | Get a claim assessment | All roles |
| GET | `/api/claims` | List claim assessments; optional filter `basis_panel_id` | All roles |
| POST | `/api/label-versions/{id}/market-variants` | Adapt a label to another market with an effective window | LabelAnalyst |
| GET | `/api/label-versions/{id}/market-variants` | List market variants of a label | All roles |
| POST | `/api/market-variants/{id}/activate` | Activate a variant inside its effective window; base label must be APPROVED | QualityManager |
| POST | `/api/market-variants/{id}/retire` | Retire an active variant, freeing its window | QualityManager |
| GET | `/api/label-versions/{id}/format-checks` | List format checks of a label | All roles |
| POST | `/api/clients/{id}/artwork-audits` | Schedule an on-pack versus approved-artwork audit | ComplianceAuditor |
| GET | `/api/artwork-audits/{id}` | Get an audit | All roles |
| GET | `/api/artwork-audits` | List audits; optional filters `client_id`, `product_id`, `label_version_id` | All roles |
| POST | `/api/artwork-audits/{id}/findings` | Log a discrepancy finding; the first finding moves the audit to FINDINGS_LOGGED | ComplianceAuditor |
| GET | `/api/artwork-audits/{id}/findings` | List findings of an audit | All roles |
| POST | `/api/artwork-audits/{id}/close` | Close an audit and compute its conformance score | ComplianceAuditor |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_RECIPE_NOT_LOCKED` | 409 Conflict |
| `ERR_LAB_REVIEW_ALREADY_DECIDED` | 409 Conflict |
| `ERR_NO_VALIDATED_LAB_ANALYSIS` | 422 Unprocessable Entity |
| `ERR_NUTRIENT_PROFILE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_RACC_CATEGORY_UNKNOWN` | 422 Unprocessable Entity |
| `ERR_RACC_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_RACC_MARKET_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SERVING_SIZE_UNRESOLVABLE` | 422 Unprocessable Entity |
| `ERR_PANEL_NOT_CURRENT` | 409 Conflict |
| `ERR_ALLERGEN_STATEMENT_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_INGREDIENT_ORDER_VIOLATION` | 422 Unprocessable Entity |
| `ERR_LABEL_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_LABEL_NOT_APPROVED` | 409 Conflict |
| `ERR_CONTENT_REVISION_REQUIRED` | 409 Conflict |
| `ERR_CLAIMS_NOT_RESOLVED` | 409 Conflict |
| `ERR_FORMAT_CHECK_FAILED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_DUPLICATE_MARKET_VARIANT` | 409 Conflict |
| `ERR_SAME_MARKET_VARIANT` | 422 Unprocessable Entity |
| `ERR_MARKET_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_VARIANT_NOT_IN_WINDOW` | 409 Conflict |
| `ERR_FACILITY_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_SCOPE_INCONSISTENT` | 422 Unprocessable Entity |
