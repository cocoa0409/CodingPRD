# Resilient Flooring Plant Operations API — Product Requirements Document

## 1. Introduction

A luxury vinyl flooring plant is, in engineering terms, a chain of decisions in which every downstream commitment is only as trustworthy as the record of the upstream one. A compounder chooses how much vinyl resin, plasticizer, filler and stabilizer to dose, and that choice fixes both the cost of the compound and how the finished plank will resist a chair castor. A licensor grants the right to print a wood-look decor, and that grant carries a royalty rate, a territory list and a hard ceiling on how many square metres may ever be produced under it. A press or calender line forms the plank at a thickness it can physically handle, and the print-to-emboss registration achieved on that line determines whether the run is saleable or scrap. Years later a distributor files a warranty claim about a worn-through wear layer, and the only defensible answer comes from the batch record written on the day the run finished.

This document specifies the API that carries that chain. The system is a single plant-operations backend covering raw-material master data, compound formulation and technical review, print-film design licensing, finished-goods SKU definition, laboratory testing and certification, line scheduling and run execution, quality disposition, finished-stock batches, distributor allocations with substitution, and warranty adjudication. Its purpose is not to automate judgement — a technical director still decides whether a recipe is good enough, a QA technician still decides whether a run is released — but to make every judgement reproducible: the state that authorised it, the numbers that were current when it was taken, and the identity of the person who took it.

Two design commitments run through everything that follows. The first is **segregation of duties**: the plant deliberately refuses to let one person both author and approve, both measure and certify, both hold and release, both triage and adjudicate. The second is **deterministic time**: because licence terms expire, setup windows open a fixed number of minutes before a planned start, slip-resistance qualifications lapse, and warranties prorate over years, the server never reads a wall clock. It reads a logical clock that operators can advance explicitly, so that a multi-year warranty scenario is as reproducible as a unit test. Every collection in the API is mounted at the root path; there is no aggregate root, and resources reference one another by identifier rather than by URL nesting.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request — without exception, including reads — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user is acting. If either header is absent or empty, or if `X-User-Role` is not one of the seven role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once the caller is identified, the declared role must appear in the set of roles authorised for the addressed operation; otherwise the request fails with `ERR_UNAUTHORIZED` (HTTP 403).

The seven roles are `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician`, `ProductionPlanner`, `WarrantyAdjuster` and `Distributor`.

- A `PlantAdmin` owns master data and commercial administration: trading partners, raw materials and their status and cost, design grants, print films, press lines, SKU definition, the commercial dimension of a SKU, and the logical clock.
- A `Formulator` authors and revises compound recipes and may never approve one.
- A `TechnicalDirector` approves recipes, certifies SKUs, and amends or terminates design grants.
- A `QaTechnician` runs the laboratory, begins SKU testing, dispositions completed runs, and controls stock holds.
- A `ProductionPlanner` schedules and executes press and calender line runs.
- A `WarrantyAdjuster` triages, reviews and adjudicates warranty claims, and may also file them.
- A `Distributor` requests, fills and releases stock allocations and files warranty claims for its own account.

For six of the seven roles — `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician`, `ProductionPlanner` and `WarrantyAdjuster` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow demands an audit trail (for example as `authored_by_user_id`, `submitted_by_user_id` and `approved_by_user_id` on a recipe, `started_by_user_id` and `recorded_by_user_id` in the laboratory, `certified_by_user_id` on a SKU, `completed_by_user_id` on a run, `held_by_user_id` on a batch, and `assigned_adjuster_user_id` on a claim) but it never compares it to any entity's `id`.

When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting distributor row. Ownership checks on any resource that references a distributor compare the resource's `distributor_id` field to `X-User-ID`. A `Distributor` reading or acting on an allocation whose `distributor_id` differs from `X-User-ID` — filling it, releasing it, reading the allocation itself, reading its lines, or reading an individual warranty claim — is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The same code and status apply when a `Distributor` creates an allocation or files a warranty claim whose body carries a `distributor_id` other than its own. `PlantAdmin` and the other operator roles are not subject to this ownership narrowing.

One endpoint splits its authorisation by payload rather than by path: changing a design grant's status to `TERMINATED` is reserved to `TechnicalDirector`, while moving a grant to `ACTIVE` or `SUSPENDED` is reserved to `PlantAdmin`. Both roles are nominally authorised for the endpoint, so the mismatch surfaces as `ERR_UNAUTHORIZED` (HTTP 403) after the general role check rather than before it.

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

Every collection read accepts two optional query parameters. `limit` defaults to 10, may be no smaller than 1 and no larger than 100. `offset` defaults to 0 and may be no smaller than 0; it has no upper bound. A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

List results are ordered by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of rows matching the filters before the window is applied) and `has_more` (true when rows remain beyond the current window).

### 2.4. Resource Identity, Timestamps and the Plant Logical Clock

Every persisted resource carries a server-minted `id` in UUID form, with no type prefix and no client control over its value. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written.

Most resources additionally carry `updated_at`, in the same format, refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the caller did not directly request, such as a cascade reaching the row from a neighbouring entity. Whenever this document says that a cascade "touches" a row, it means the row's `updated_at` is refreshed and its `version` is advanced by one.

`TestResult` is the single exception. A laboratory measurement is immutable once recorded: a `TestResult` row carries only `id` and `created_at`. It has neither `updated_at` nor `version`, and no operation ever rewrites one.

Every timestamp the server stamps — `created_at`, `updated_at`, `approved_at`, `certified_at`, `snapshot_at` — and every comparison the server makes against "now" reads a **logical clock**, never the host wall clock. The clock starts at `2026-08-01T00:00:00Z` when the service boots. A `PlantAdmin` may move it by supplying a `current_utc` instant to the administrative clock-setting capability, which echoes back the resulting `current_utc`. This capability exists because design-grant expiry, the 120-minute setup lead window and multi-year warranty proration cannot be reached by composing business operations: no business operation accepts "now" as an input.

### 2.5. The Order in Which a Request Can Fail

Because a single request often breaks several rules at once, the server evaluates validations in a strict ascending order of fifteen bands and **stops at the first violation**; no later band is evaluated, and the response carries only that first rule's error. Two rules in the same band can never both be violated by one request. The bands, in order, are:

1. Authentication — the two identity headers.
2. Authorization — role against the endpoint, including the payload-dependent split on design-grant status changes.
3. Request shape — missing required fields, wrong JSON types, enum values outside their declared sets, numeric ranges and decimal-place limits, pagination bounds, and the cross-field shape rules described with the workflows they guard.
4. Path resource existence — the `{id}` (or `{component_id}`) segment must address an existing row of the collection named by its own segment; otherwise the not-found code for that entity is returned with HTTP 404. The twelve codes are `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_RAW_MATERIAL_NOT_FOUND`, `ERR_FORMULATION_NOT_FOUND`, `ERR_FORMULATION_COMPONENT_NOT_FOUND`, `ERR_DESIGN_LICENSE_NOT_FOUND`, `ERR_PRINT_FILM_NOT_FOUND`, `ERR_PRODUCT_SKU_NOT_FOUND`, `ERR_PRESS_LINE_NOT_FOUND`, `ERR_TEST_PANEL_NOT_FOUND`, `ERR_PRODUCTION_RUN_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` and `ERR_WARRANTY_CLAIM_NOT_FOUND`.
5. Body reference existence — every foreign key in the body must address an existing row, or that entity's not-found code from the list above is returned with HTTP 404: `formulation_id` and `supersedes_formulation_id` against recipes, `raw_material_id` against materials, `license_id` and `supersedes_license_id` against design grants, `print_film_id` against films, `sku_id` against SKUs, `press_line_id` against lines, `distributor_id` against distributors, `batch_id` against batches, and `production_run_id` against runs.
6. Resource ownership — the `Distributor` narrowing described in §2.1.
7. Own-entity state — the addressed row's own lifecycle state must admit the requested transition.
8. Optimistic concurrency — the stale-view checks of §2.7.
9. Segregation of duties — the four conflict-of-interest rules of §2.8.
10. Cross-entity state — the states of neighbouring rows the operation depends on.
11. Business safety — quality and qualification gates whose failure would put unsafe product into the market.
12. Business constraint — quantitative and uniqueness rules of the domain.
13. Business temporal — interval, window, lead-time and coverage-term rules.
14. Business referential — rules about the fitness of a referenced row rather than merely its existence.
15. Business fiscal — the licensed volume ceiling.

Four band interactions are worth stating explicitly, because each is a case where the more specific-sounding error is deliberately *not* the one returned:

- Filling an allocation that has already been released or cancelled against an empty candidate pool returns `ERR_INVALID_ALLOCATION_STATE` (band 7), not `ERR_NO_ELIGIBLE_BATCH` (band 14). Filling an allocation that has already drawn its full request against an empty candidate pool likewise returns `ERR_ALLOCATION_OVER_REQUEST` (band 12) rather than `ERR_NO_ELIGIBLE_BATCH`.
- Certifying a SKU that both lacks passing test coverage and whose recipe has been superseded returns `ERR_TEST_COVERAGE_INCOMPLETE` (band 11), not `ERR_FORMULATION_NOT_APPROVED` (band 14).
- Scheduling a run that both overlaps an existing window on the line and would break the licensed volume ceiling returns `ERR_PRESS_LINE_WINDOW_CONFLICT` (band 13), not `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (band 15).
- A recipe's own author reviewing a recipe that also contains a no-longer-active raw material returns `ERR_SEGREGATION_OF_DUTIES` (band 9), not `ERR_RAW_MATERIAL_NOT_ACTIVE` (band 14).

### 2.6. Money, Square Metres and Rounding Discipline

All monetary amounts are whole cents, held as integers; there are no fractional-cent fields anywhere in the system. All quantities in square metres are carried to two decimal places. Unless a specific rule states otherwise, every rounding operation is **round half up**.

Three rounding-order rules are part of the contract and not implementation freedom:

- **Round each component, then sum.** Where a total is assembled from named components — the seven components of a SKU standard cost, the per-line upgrade premiums of an allocation — each component is rounded to a whole cent on its own and the already-rounded integers are then added exactly. Summing unrounded components and rounding once at the end is a different, incorrect result.
- **Round per run, then accumulate.** A production run's royalty contribution is rounded to a whole cent on its own and only that rounded integer is added to the grant's royalty ledger. Two runs each computing 1060.50 cents contribute 1061 cents each, for a ledger total of 2122 cents — not the 2121 cents that accumulating first and rounding once would give.
- **Do not round intermediates that the specification carries at higher precision.** The three blend indices behind a recipe's performance score are each carried to six decimal places, and the score is rounded to two decimal places exactly once, after clamping. Rounding the indices to two decimals first is a different, incorrect result.

Percentage-like rates are expressed in basis points and divided by 10000 at the point of use: a royalty rate of 500 basis points is five percent, and a target margin of 3500 basis points is thirty-five percent.

### 2.7. Stale-View Protection on Revisions and Fills

Two write operations require the client to prove it is acting on a view of the world it has actually observed.

Creating a revision of a recipe requires `expected_formulation_version` in the request body as a non-optional field, carrying the client's last observed `version` of the recipe being revised. If that value does not equal the recipe's current `version`, the request is rejected with `ERR_STALE_FORMULATION_VERSION` (HTTP 412). This check cannot be replaced by a state precondition: the parent recipe remains `APPROVED` after a revision is created — only its `open_revision_count` and `version` move — so a second revision request is perfectly legitimate under the product semantics, and only the version comparison distinguishes a client that is working from an outdated view of the recipe it intends to supersede.

Filling an allocation requires `expected_allocation_version` in the request body as a non-optional field, carrying the client's last observed `version` of the allocation. A mismatch with the allocation's current `version` is rejected with `ERR_STALE_ALLOCATION_VERSION` (HTTP 412). Again a state precondition would not suffice: a partially filled allocation legitimately accepts a further fill, so nothing in the lifecycle rejects the second request. What the version check prevents is a client that computed its remaining requirement from an outdated `allocated_quantity_sqm` drawing stock it did not intend to draw.

No other endpoint in the system takes a version field. Amending a design grant, in particular, is deliberately not version-guarded, because the amended grant leaves `ACTIVE` as part of the amendment, so a second amendment is already refused on state grounds.

### 2.8. Segregation of Duties

Four operations refuse the acting user on the grounds that they already performed the conflicting step of the same workflow. All four return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and all four are evaluated in band 9 — after concurrency and before any cross-entity state check.

- A recipe review decision is refused when `X-User-ID` equals the recipe's `authored_by_user_id`. Authoring and approving are separated; submitting is not, so the same `Formulator` may author and submit.
- SKU certification is refused when `X-User-ID` equals the `recorded_by_user_id` of any test measurement that is being counted toward that SKU's required-type coverage. A technical director who personally took one of the qualifying readings may not certify on the strength of it.
- Releasing a batch hold is refused when `X-User-ID` equals the batch's `held_by_user_id`. The person who quarantined stock may not be the person who returns it to sale.
- Warranty adjudication is refused when `X-User-ID` equals the claim's `assigned_adjuster_user_id` — that is, the adjuster who triaged the claim may record its branch reviews but may not decide it.

### 2.9. Cascade Discipline and Ledger Compensation

Consistency in this system is immediate: when an operation's effects reach other entities, those effects land inside the same request, and a client reading any touched row immediately afterwards sees the settled state. Cascades in this plant run several hops deep — a restriction on a raw material can reach, in order, the recipes that dose it, the SKUs pinned to those recipes, the finished batches of those SKUs, the allocation lines drawn on those batches, and finally the allocations that own those lines. Every row a cascade reaches has its `updated_at` refreshed and its `version` advanced by one, in addition to whatever field the cascade rewrites.

Two cascade properties are deliberate and must not be "improved" by an implementation. First, **cascades are asymmetric**: reversing the cause does not reverse the effect. Reactivating a suspended design grant restores the print films it restricted, but it does not restore the SKUs those films put on commercial hold, and it does not release the batches those SKUs held. Second, **ledger movements are compensated exactly, using stored integers rather than recomputation**. When a run that reserved licensed volume is aborted, exactly the volume it reserved is released, leaving the reserved figure bit-identical to its pre-creation value. When a completed run is scrapped, the consumed volume it added is subtracted and the royalty it accrued is subtracted as the stored integer that was actually added, never as a fresh calculation that might round differently.

### 2.10. Reading Sub-Resources

Several reads address a child collection through its parent — a recipe's components, a raw material's component usages, a panel's results, a batch's allocation lines, an allocation's lines, a grant's utilization summary, a SKU's cost summary. Path parameters are validated strictly left to right. The parent identifier is resolved first, and if no row of the parent collection carries it, the response is that parent entity's not-found code with HTTP 404 — the child collection is never consulted. Only then is a second path segment — the `component_id` of a recipe component, written `{component_id}` in a path — resolved, and a component identifier that exists but belongs to a different recipe is treated exactly like one that does not exist at all: `ERR_FORMULATION_COMPONENT_NOT_FOUND` with HTTP 404.

Sub-resource list reads accept `limit` and `offset` on the same terms as top-level lists, and several accept additional filters described alongside their workflows.

### 2.11. Enumerations and Filter Vocabulary

Every enumerated value in this system is an exact uppercase string, and a value outside the declared set is a shape error (`ERR_INVALID_REQUEST`, HTTP 400) rather than a business error. The complete vocabulary:

- A distributor's `status` is `ACTIVE` or `SUSPENDED`.
- A raw material's `category` is `VINYL_RESIN`, `PLASTICIZER`, `FILLER` or `STABILIZER`; its `status` is `ACTIVE`, `RESTRICTED` or `DISCONTINUED`.
- A recipe's `status` is `DRAFT`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`, `SUPERSEDED` or `RETIRED`; its `cost_basis` is `LIVE` or `PINNED`; its `indentation_resistance_class` is `CLASS_23_31`, `CLASS_33_42` or `CLASS_34_43`.
- A design grant's `license_type` is `EXCLUSIVE`, `NON_EXCLUSIVE` or `INTERNAL`; its `status` is `ACTIVE`, `SUSPENDED`, `EXPIRED`, `SUPERSEDED` or `TERMINATED`.
- A print film's `status` is `AVAILABLE`, `RESTRICTED` or `WITHDRAWN`.
- A SKU's `construction_type` is `GLUE_DOWN`, `LOOSE_LAY`, `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC`; its `attached_underlayment_type` is `NONE`, `IXPE_1MM`, `EVA_1_5MM` or `CORK_2MM`; its `profile_family` is `NONE`, `UNILIN_5G`, `VALINGE_2G` or `DROP_LOCK`; its `certification_status` is `UNCERTIFIED`, `TESTING`, `PROVISIONAL`, `CERTIFIED`, `SUSPENDED` or `DECERTIFIED`; its `commercial_status` is `DEVELOPMENT`, `RELEASED`, `HOLD` or `DISCONTINUED`.
- A press line's `line_type` is `MULTI_DAY_PRESS` or `CALENDER`; its `status` is `AVAILABLE`, `MAINTENANCE` or `DOWN`.
- A test panel's `status` is `SCHEDULED`, `IN_TEST`, `PASSED`, `FAILED`, `RETEST_REQUIRED` or `VOIDED`. A measurement's `test_type` is `RESIDUAL_INDENTATION`, `DIMENSIONAL_STABILITY_HEAT`, `SLIP_RESISTANCE`, `PEEL_ADHESION_DELAMINATION` or `LOCK_SHEAR`, and its `outcome` is `PASS`, `MARGINAL` or `FAIL`.
- A production run's `run_status` is `PLANNED`, `SETUP`, `RUNNING`, `COMPLETED` or `ABORTED`; its `qc_disposition` is `PENDING`, `RELEASED`, `QUARANTINED` or `SCRAPPED`; its `auto_disposition_recommendation`, when set, is `RELEASED` or `QUARANTINED`.
- A batch's `status` is `IN_PRODUCTION`, `IN_STOCK`, `HELD` or `SCRAPPED`.
- An allocation's `status` is `OPEN`, `PARTIALLY_FILLED`, `FILLED`, `RELEASED` or `CANCELLED`; its `substitution_policy` is `STRICT_SKU`, `ALLOW_UNDERLAYMENT_UPGRADE` or `ALLOW_WEAR_LAYER_UPGRADE`. An allocation line's `substitution_kind` is `EXACT`, `UNDERLAYMENT_UPGRADE` or `WEAR_LAYER_UPGRADE`, its `status` is `ACTIVE` or `VOIDED`, and its `void_reason`, when set, is one of `ALLOCATION_RELEASED`, `ALLOCATION_CANCELLED`, `BATCH_HELD` or `BATCH_SCRAPPED`.
- A warranty claim's `claim_type` is `WEAR_LAYER_WEARTHROUGH`, `DELAMINATION`, `DIMENSIONAL_MOVEMENT` or `LOCK_FAILURE`; its `status` is `SUBMITTED`, `TRIAGE`, `ADJUDICATION_READY`, `APPROVED` or `DENIED`; each of `materials_review_outcome` and `field_review_outcome`, when set, is `DEFECT_CONFIRMED`, `NO_DEFECT` or `INCONCLUSIVE`; its `settlement_variant`, when set, is `PRORATED_STRAIGHT_LINE` or `STEPPED_SCHEDULE`.

Collection reads support equality filters drawn from the same vocabulary, combined with logical AND when more than one is supplied. Distributors filter on `status` and `territory_code`; raw materials on `category` and `status`; recipes on `status`, `supersedes_formulation_id` and `indentation_resistance_class`; design grants on `status`, `supersedes_license_id` and `license_type`; print films on `status` and `license_id`; SKUs on `certification_status`, `commercial_status`, `formulation_id`, `print_film_id` and `construction_type`; press lines on `status` and `line_type`; test panels on `status` and `sku_id`; panel results on `test_type`; production runs on `run_status`, `qc_disposition`, `sku_id` and `press_line_id`; batches on `status`, `sku_id` and `production_run_id`; batch allocation-line and allocation-line reads on `status`; allocations on `status`, `distributor_id` and `sku_id`; warranty claims on `status`, `batch_id`, `distributor_id` and `claim_type`.

## 3. Business Logic & Workflows

### 3.1. Compounding: Materials, Recipes and Technical Approval

The plant's material library is administered by a `PlantAdmin`. Each material is registered with a `material_code` that must be unique across the library (a repeat is `ERR_DUPLICATE_CODE`, HTTP 409), a trade `name`, a `category` naming its formulation role, a purchase cost held as `cost_per_kg_cents` in whole cents per kilogram of at least 1, and four technical properties: `indentation_index` and `thermal_stability_index`, both scored 0 to 100 with higher being better; `plasticizer_migration_index`, also 0 to 100 but with higher being *worse*; and `max_phr`, strictly greater than zero, the largest parts-per-hundred-resin dosage the material may ever take in a recipe. All three indices accept at most two decimal places. A material is created `ACTIVE` unless the creating request overrides `status`.

Recipes are authored by a `Formulator`, who supplies a `formulation_code` unique across recipes and, when the new recipe is intended to replace an existing approved one, the `supersedes_formulation_id` of that predecessor; for an original recipe the field is null. A newly created recipe is `DRAFT` with `revision` 1, `cost_basis` `LIVE`, `rejection_count` and `open_revision_count` both 0, and `authored_by_user_id` set to the acting `X-User-ID`. Its `submitted_by_user_id`, `approved_by_user_id` and `approved_at` are null.

Dosing a recipe means adding components. Each component names the `raw_material_id` being dosed and the `phr` dosed, strictly greater than zero with at most two decimal places. Adding a component is permitted while the recipe is `DRAFT` or `REJECTED`; from any other state the attempt is `ERR_INVALID_FORMULATION_STATE` (HTTP 409). The material being added must itself be `ACTIVE`; a `RESTRICTED` or `DISCONTINUED` material — or any material already on the recipe that has since left `ACTIVE` — makes the operation fail with `ERR_RAW_MATERIAL_NOT_ACTIVE` (HTTP 409). Two components on one recipe may not reference the same material: a duplicate dosage returns `ERR_DUPLICATE_CODE` (HTTP 409). And the dosage may not exceed the material's own ceiling — a `phr` greater than `max_phr` is `ERR_PHR_EXCEEDS_MATERIAL_MAX` (HTTP 422). Note that this ceiling is a stored-state comparison evaluated in band 12, not a shape rule: a syntactically valid dosage that happens to be too large for that particular material is a 422, never a 400. Removing a component is permitted from the same states and, like adding one, returns the recomputed parent recipe. Either edit applied to a `REJECTED` recipe returns it to `DRAFT`, closing the revision loop `DRAFT → UNDER_REVIEW → REJECTED → DRAFT`; the recipe's `rejection_count` is **not** reset by that return.

Every component edit, every submission, and every approval recomputes the recipe's seven derived blend figures. The four category subtotals — `resin_phr`, `plasticizer_phr`, `filler_phr` and `stabilizer_phr` — are the sums of the `phr` of the components whose material sits in the corresponding category, each rounded half up to two decimal places, and `total_phr` is the sum of `phr` across all components, likewise at two decimal places.

The blended compound cost, `blended_cost_per_kg_cents`, is a dosage-weighted average expressed in whole cents. For each component, multiply its `phr` by the per-kilogram cost that the recipe's cost basis dictates: while `cost_basis` is `LIVE`, that is the material's current `cost_per_kg_cents`; once `cost_basis` is `PINNED`, it is the component's own `material_cost_snapshot_cents`. Add those products together, divide the total by `total_phr`, and round half up to a whole cent.

The `performance_score` is built from three dosage-weighted blend indices, each carried to six decimal places and each computed as the sum over components of `phr` multiplied by the relevant material property, divided by `total_phr`: the blended indentation index uses `indentation_index` directly; the blended thermal index uses `thermal_stability_index` directly; and the blended migration-resistance index uses 100 minus the material's `plasticizer_migration_index`, so that a migration-prone plasticizer drags the blend down. Those three indices are weighted at forty percent, thirty-five percent and twenty-five percent respectively and added together. Two penalties are then subtracted. The softness penalty reads the plasticizer ratio — `plasticizer_phr` divided by `resin_phr`, rounded half up to four decimal places — and is 12 points when that ratio is greater than 0.35, 5 points when it is greater than 0.25 but not greater than 0.35, and zero otherwise. The brittleness penalty reads the filler ratio — `filler_phr` divided by `resin_phr`, also at four decimal places — and is 8 points when that ratio is at least 3.00, 3 points when it is at least 2.00 but below 3.00, and zero otherwise. The result is clamped to the range 0 through 100, taking whichever of the clamp bounds applies, and only then rounded half up to two decimal places. That single final rounding is the contract; the six-decimal indices must not be rounded to two decimals on the way.

The `indentation_resistance_class` is derived from the blended indentation index **alone**, never from `performance_score`: the class is `CLASS_34_43` when that index is at least 88.00, `CLASS_33_42` when it is at least 70.00 but below 88.00, and `CLASS_23_31` otherwise. Two recipes with an identical score can therefore land in different classes.

Two degenerate cases are specified. A recipe with no components has `total_phr` of 0.00 and every other derived figure null. A recipe whose `resin_phr` is 0 has a null plasticizer ratio and a null filler ratio, and both penalties are zero; such a recipe cannot be submitted for review.

A `PlantAdmin` may revalue a material by supplying a new `cost_per_kg_cents`. A revaluation is refused with `ERR_RAW_MATERIAL_NOT_ACTIVE` (HTTP 409) when the material is `RESTRICTED` — a restricted material can no longer be repriced. Otherwise, every recipe whose `cost_basis` is `LIVE` (that is, every recipe in `DRAFT`, `UNDER_REVIEW` or `REJECTED`) that doses the material has its blend figures recomputed and its `version` advanced; the material's own `version` advances too. Recipes whose `cost_basis` is `PINNED` are untouched, which means their `blended_cost_per_kg_cents` and every SKU standard cost stamped from them stay exactly as they were. That deliberate divergence is the whole point of the two cost bases, and it is what a cost summary exposes side by side.

Moving a material to `RESTRICTED` starts the plant's deepest cascade. Every recipe in `APPROVED` or `SUPERSEDED` that doses the material transitions to `RETIRED` (`APPROVED → RETIRED` or `SUPERSEDED → RETIRED`). Because those recipes are `RETIRED`, every SKU pinned to one of them whose `certification_status` is `TESTING`, `PROVISIONAL` or `CERTIFIED` moves to `SUSPENDED`, and every such SKU whose `commercial_status` is `RELEASED` moves to `HOLD`. Because those SKUs went on hold, each of their batches in `IN_STOCK` moves to `HELD` with `hold_reason` recorded as `SKU_ON_HOLD`. Because those batches were held, every `ACTIVE` allocation line drawn on them becomes `VOIDED` with `void_reason` `BATCH_HELD`, each line's `quantity_sqm` is added back to its batch's `available_quantity_sqm`, and each owning allocation recomputes `allocated_quantity_sqm` and `upgrade_cost_total_cents` and steps back from `FILLED` to `PARTIALLY_FILLED`, or from `PARTIALLY_FILLED` to `OPEN` when its last active line is gone. Every row in that five-hop chain is touched.

A material's component usages are readable in the reverse direction, so an administrator can see which recipes a candidate restriction would retire before issuing it.

Submission is the `Formulator`'s hand-off. It is permitted only from `DRAFT`, taking the recipe `DRAFT → UNDER_REVIEW`, and it stamps `submitted_by_user_id` with the acting user. Two business preconditions guard it. The recipe must have at least one component and its `resin_phr` must be exactly 100.00 — a recipe with no components, or one whose resin dosage is anything other than exactly 100.00, is refused with `ERR_RESIN_PHR_NOT_NORMALIZED` (HTTP 422). And every material on the recipe must still be `ACTIVE`, or the submission fails with `ERR_RAW_MATERIAL_NOT_ACTIVE`.

Review is the `TechnicalDirector`'s decision, expressed as a `decision` of either approve or reject, with an optional `review_note` recorded alongside a rejection. The recipe must be `UNDER_REVIEW`; from anything else the attempt is `ERR_INVALID_FORMULATION_STATE`. The acting user may not be the recipe's author, as described in §2.8. Rejection takes the recipe `UNDER_REVIEW → REJECTED` and increments `rejection_count` by one; nothing else moves, and the recipe remains editable, which is how the revision loop closes.

Approval is the heaviest single operation in the compounding workflow, and its preconditions are evaluated after the segregation check. Every material on the recipe must still be `ACTIVE`. The recipe's `performance_score` must be at least 60.00 — a score below that minimum is `ERR_PERFORMANCE_SCORE_BELOW_MINIMUM` (HTTP 422), and a score of exactly 60.00 is approvable because the threshold is inclusive. Its `indentation_resistance_class` must not be `CLASS_23_31`; the lowest class is `ERR_INDENTATION_CLASS_TOO_LOW` (HTTP 422). Those two constraints share a band and are evaluated in that order, so a recipe that clears the score but sits in the lowest class returns the class error rather than the score error.

On approval the recipe moves `UNDER_REVIEW → APPROVED` and four things are written. First, **cost pinning**: every component of the recipe receives `material_cost_snapshot_cents` set to its material's `cost_per_kg_cents` as of that instant, and `snapshot_at` set to the logical clock. Second, the recipe's `cost_basis` flips to `PINNED` and `blended_cost_per_kg_cents` is re-derived from those snapshots rather than from live material costs. Third, `approved_by_user_id` is set to the acting user and `approved_at` to the logical clock. Fourth, if the recipe carries a `supersedes_formulation_id`, the referenced predecessor moves `APPROVED → SUPERSEDED`, and because that predecessor became superseded, every SKU whose `formulation_id` points at it has `pin_stale` set to true. Both the newly approved recipe and the superseded predecessor have their `version` advanced, as does every SKU marked stale.

A `Formulator` may open a revision of an approved recipe by supplying a new `formulation_code` together with `expected_formulation_version` as described in §2.7. The recipe being revised must be `APPROVED`; a revision opened against a recipe in any other state is `ERR_INVALID_FORMULATION_STATE` (HTTP 409), checked before the version comparison. The new row is created in `DRAFT` with `revision` equal to the parent's `revision` plus one and `supersedes_formulation_id` pointing at the parent, and every component of the parent is copied across carrying its `phr` only — no cost snapshots travel with the copy, so the revision starts on a `LIVE` cost basis. The parent's `open_revision_count` is incremented and its `version` advanced, but the parent **stays** `APPROVED`; it only becomes `SUPERSEDED` when the revision is itself approved.

### 3.2. Design Rights and the Print Film Library

A design grant is registered by a `PlantAdmin` with a `license_code` unique across grants, the `licensor_name` granting the pattern rights, a `license_type`, a `royalty_rate_bps` between 0 and 2000 inclusive, an inclusive `valid_from` and an exclusive `valid_until` that must be strictly later than `valid_from` (otherwise `ERR_INVALID_REQUEST`, HTTP 400), a `term_volume_cap_sqm` strictly greater than zero at two decimal places, and a non-empty `territory_codes` array of two-letter uppercase codes. A new grant is `ACTIVE` with `reserved_volume_sqm`, `consumed_volume_sqm` and `accrued_royalty_cents` all zero, and with `supersedes_license_id` and `amendment_note` null.

Print films are the decor layer. Each is registered with a `design_code` unique across the library, the `license_id` of the grant that authorises it, longitudinal and transverse pattern repeats `pattern_repeat_mm_length` and `pattern_repeat_mm_width` (both strictly positive, in millimetres), a `registration_tolerance_mm` strictly greater than zero being the largest print-to-emboss drift the design will accept, the `emboss_plate_code` paired with the design and that plate's nominal `emboss_alignment_offset_mm`, and `master_roll_sets` of at least 1 — the number of physical roll sets, which caps how many runs may occupy overlapping windows on the design. A film may only be registered while its grant is `ACTIVE`; a grant in any other state yields `ERR_LICENSE_NOT_ACTIVE` (HTTP 409). New films are `AVAILABLE`.

Library curation is separate from licensing, and deliberately so: a damaged emboss plate or a licensor's informal hold on one design must be expressible without suspending an entire grant. A `PlantAdmin` may therefore drive a film's own status with a `to_status` of `RESTRICTED`, `AVAILABLE` or `WITHDRAWN`. `AVAILABLE → RESTRICTED` and `RESTRICTED → AVAILABLE` are both declared, `WITHDRAWN` is terminal and reachable from either `AVAILABLE` or `RESTRICTED`, and no self-transition is declared — asking for the state the film is already in is `ERR_INVALID_PRINT_FILM_STATE` (HTTP 409), as is any request against a `WITHDRAWN` film. Returning a film to `AVAILABLE` additionally requires its grant to be `ACTIVE`, and a request to do so while the grant is not `ACTIVE` also returns `ERR_INVALID_PRINT_FILM_STATE`. A film that is not `AVAILABLE` can found no new work — it blocks the start of SKU testing, the scheduling of a run and the starting of a run, each with `ERR_PRINT_FILM_NOT_AVAILABLE` (HTTP 409) — while runs already `PLANNED` keep their reserved windows.

A grant's own lifecycle is cyclic on one edge and terminal on three. `ACTIVE → SUSPENDED` is a `PlantAdmin` action and cascades three hops: every `AVAILABLE` film on the grant moves to `RESTRICTED`; because those films were restricted, every SKU on one of them whose `commercial_status` is `RELEASED` moves to `HOLD`; and because those SKUs went on hold, each of their `IN_STOCK` batches moves to `HELD` with `hold_reason` `SKU_ON_HOLD`. `SUSPENDED → ACTIVE` is the reverse edge, permitted only while the logical clock is strictly earlier than the grant's `valid_until`; it returns `RESTRICTED` films to `AVAILABLE` and stops there. The SKUs put on hold stay on hold and the batches held stay held — the asymmetry of §2.9 in its most visible form.

Termination is a `TechnicalDirector` action reachable from either `ACTIVE` or `SUSPENDED`, and it runs four hops. Every film on the grant moves to `WITHDRAWN`. Every SKU on a withdrawn film whose `commercial_status` is `RELEASED` moves to `HOLD`, and every such SKU whose `certification_status` is `PROVISIONAL` or `CERTIFIED` moves to `SUSPENDED`. Every `IN_STOCK` batch of those SKUs moves to `HELD` with `hold_reason` `SKU_ON_HOLD`. And every `ACTIVE` allocation line on those batches becomes `VOIDED` with `void_reason` `BATCH_HELD`, its `quantity_sqm` returning to the batch's `available_quantity_sqm`, with each owning allocation recomputing `allocated_quantity_sqm` and stepping `FILLED → PARTIALLY_FILLED` or `PARTIALLY_FILLED → OPEN`. Any status request against a grant that is already `TERMINATED`, `SUPERSEDED` or `EXPIRED` is `ERR_INVALID_LICENSE_STATE` (HTTP 409); those three states accept nothing.

Amending a grant is how commercial terms change without losing ledger continuity. A `TechnicalDirector` supplies the successor's `license_code` and `term_volume_cap_sqm`, optionally a new `valid_until`, a new `royalty_rate_bps` and an `amendment_note` recording the rationale. The grant being amended must be `ACTIVE`. The new cap may not be smaller than the volume the grant has already committed — that is, it must be at least the sum of `consumed_volume_sqm` and `reserved_volume_sqm` — and a smaller cap is refused with `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422). On success a successor grant is created `ACTIVE` with `supersedes_license_id` pointing at the amended one, carrying `reserved_volume_sqm`, `consumed_volume_sqm` and `accrued_royalty_cents` across unchanged; every film of the amended grant is repointed at the successor and has its `version` advanced; and the amended grant moves `ACTIVE → SUPERSEDED`.

Grants also expire, but lazily and against the logical clock rather than by a background sweep. When run scheduling, run starting, or the start of SKU testing consults a grant that is `ACTIVE` and finds the clock at or past its `valid_until`, the grant's `status` is first set to `EXPIRED` and its `version` advanced, and then the triggering request is rejected with `ERR_LICENSE_EXPIRED` (HTTP 409). The same code and status apply when a run is scheduled with a `planned_start_utc` at or after `valid_until`, or strictly earlier than `valid_from`. Because a grant that has left `ACTIVE` for any reason — suspension, supersession, termination — also fails the fitness check, an operation depending on a non-active grant that has not expired returns `ERR_LICENSE_NOT_ACTIVE` instead.

A grant's utilization is readable as a computed summary carrying `term_volume_cap_sqm`, `reserved_volume_sqm`, `consumed_volume_sqm`, the forward-looking `projected_volume_sqm` (consumed plus reserved), the `remaining_volume_sqm` left under the cap (the cap less the projection), the `accrued_royalty_cents` ledger, and `contributing_run_count`, the number of completed runs that have contributed royalty to it.

### 3.3. Finished-Goods SKUs: Construction, Milling and Warranty Terms

A finished-goods SKU is defined by a `PlantAdmin` and is where compound, decor and installation method meet. Required inputs are a `sku_code` unique across SKUs, the `formulation_id` of the core compound recipe, the `print_film_id` of the decor design, a `construction_type`, a `wear_layer_mil` in thousandths of an inch that must be greater than zero, no greater than 40, and carry at most one decimal place, an `overall_thickness_mm` greater than zero, no greater than 12, at most two decimals, and a `royalty_basis_price_cents_per_sqm` of at least 1. Optional inputs are `waterproof_rated` (false by default), `attached_underlayment_type` (`NONE` by default), `profile_family` (`NONE` by default), `tongue_thickness_target_mm`, `tolerance_plus_mm`, `tolerance_minus_mm`, `target_lock_shear_n_per_mm` (all null by default) and `target_margin_bps` (3500 by default, and constrained to the range 0 through 9000). An approved recipe is deliberately *not* required at this point; that requirement arrives when testing begins.

The four milling fields travel together with the profile family, and the pairing is a shape rule evaluated in band 3. If `profile_family` is anything other than `NONE`, all four of `tongue_thickness_target_mm`, `tolerance_plus_mm`, `tolerance_minus_mm` and `target_lock_shear_n_per_mm` must be present; if `profile_family` is `NONE`, all four must be absent; and a `construction_type` of `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC` may not be combined with a `profile_family` of `NONE`. Any of those three conditions returns `ERR_INVALID_REQUEST` (HTTP 400). Both tolerances, when present, must be strictly greater than zero.

Beyond mere presence, the tolerance band has to be physically buildable, and that is a business constraint rather than a shape rule. When `profile_family` is not `NONE`, `tolerance_minus_mm` must be strictly smaller than `tongue_thickness_target_mm` — a lower tolerance that would consume the whole tongue is nonsense — and the two tolerances added together may not exceed 0.50 millimetres, half a millimetre being the widest total band the milling heads can hold. Either violation is `ERR_TOLERANCE_BAND_INVALID` (HTTP 422).

Warranty terms are derived at creation from the wear layer and the construction, and they are the figures a warranty settlement years later will divide by. The residential term is 25 years when `wear_layer_mil` is at least 20, 20 years when it is at least 12 but below 20, 15 years when it is at least 6 but below 12, and 10 years otherwise. The light-commercial term over the same tiers is 15, 10, 5 and 0 years. A bonus of 5 years is added to both terms when — and only when — the SKU is both `waterproof_rated` and built on a `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC` construction; a waterproof `GLUE_DOWN` plank earns nothing. The residential result is then capped at 30 years and stored as `warranty_years`, and the light-commercial result is capped at 20 years and stored as `light_commercial_warranty_years`. All tier thresholds are inclusive, so a wear layer of exactly 20 mil takes the top tier and exactly 12 mil gives 20 residential and 10 light-commercial years.

A new SKU is created with `certification_status` `UNCERTIFIED` and `commercial_status` `DEVELOPMENT`; `pinned_formulation_version`, `pinned_print_film_version`, `standard_cost_cents_per_sqm`, `list_price_cents_per_sqm`, `certified_at` and `certified_by_user_id` are all null, and `pin_stale` is false.

**Standard cost.** The cost of a square metre is assembled from seven named components, each rounded half up to a whole cent on its own before any addition happens. The core-compound component is the compound's blended cost per kilogram multiplied by 1.90 — the specific gravity in kilograms per square metre per millimetre — multiplied by the SKU's `overall_thickness_mm`. The wear-layer component is `wear_layer_mil` multiplied by 3.5 cents per mil per square metre. The print-film component is a base of 18 cents plus a repeat surcharge determined by the larger of the design's two pattern repeats: 6 cents when that larger repeat is at least 1800 millimetres, 2 cents when it is at least 1200 but below 1800, and nothing below 1200. The underlayment component is 0 cents for `NONE`, 22 for `IXPE_1MM`, 17 for `EVA_1_5MM` and 41 for `CORK_2MM`. The waterproofing component is 9 cents when the SKU is `waterproof_rated` and zero otherwise. The conversion component is a base of 35 cents plus 12 cents of click-lock milling when `construction_type` is `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC`. The seventh component is the royalty: the SKU's `royalty_basis_price_cents_per_sqm` multiplied by the governing grant's `royalty_rate_bps` divided by 10000, rounded half up to a whole cent. The royalty is computed from the *published basis price*, an input field, and never from the derived list price — that is precisely what stops cost, price and royalty chasing one another in a circle. `standard_cost_cents_per_sqm` is the exact integer sum of those seven rounded integers, and `list_price_cents_per_sqm` is that standard cost multiplied by the quantity 10000 plus `target_margin_bps`, divided by 10000, rounded half up to a whole cent. A `target_margin_bps` of 0 therefore makes the list price equal the standard cost, and a grant with a `royalty_rate_bps` of 0 contributes a royalty component of exactly 0.

That assembly is evaluated on two different bases. The **pinned basis** takes the core-compound component from the per-component `material_cost_snapshot_cents` captured when the recipe was approved — equivalently, from a pinned recipe's `blended_cost_per_kg_cents`, which is what the SKU's `pinned_formulation_version` refers to. The **live basis** re-blends the core compound from the *current* `cost_per_kg_cents` of every component material, ignoring the snapshots entirely: it sums each component's `phr` multiplied by its material's current cost, divides by `total_phr`, and rounds half up to a whole cent before the thickness and specific-gravity multiplication. A material revaluation moves the live basis immediately, even for an approved recipe, and leaves the pinned basis bit-identical; the gap between the two is the plant's replacement-cost exposure.

Both bases are readable side by side as a SKU cost summary, which reports `live_basis_core_cost_cents` and `pinned_basis_core_cost_cents`, the two blended compound costs `live_basis_blended_cost_per_kg_cents` and `pinned_basis_blended_cost_per_kg_cents`, the five basis-independent components `wear_layer_cost_cents`, `print_film_cost_cents`, `underlayment_cost_cents`, `waterproof_cost_cents` and `conversion_cost_cents`, the `royalty_cost_cents`, the two totals `live_basis_standard_cost_cents_per_sqm` and `pinned_basis_standard_cost_cents_per_sqm`, their `basis_delta_cents_per_sqm`, the two derived prices `live_basis_list_price_cents_per_sqm` and `pinned_basis_list_price_cents_per_sqm`, and the SKU's current `pin_stale` flag. The summary is an indicative quote readable at any certification state, so it never writes anything to the SKU.

### 3.4. The Laboratory: Panels, Measurements and Retests

A test panel is a physical specimen of a SKU's construction, registered by a `QaTechnician` with a `panel_code` unique across panels and the `sku_id` it represents. A panel may only be created while the SKU's `certification_status` is `TESTING` or `PROVISIONAL`; from any other certification state the request is `ERR_INVALID_SKU_CERTIFICATION_STATE` (HTTP 409). A new panel is `SCHEDULED` with `attempt_no` 1, `retest_count` 0, `void_reason` and `started_by_user_id` null, and `required_test_types` derived from the SKU.

**Required coverage** is derived from the SKU's configuration, not chosen by the laboratory. Every panel requires `RESIDUAL_INDENTATION` and `DIMENSIONAL_STABILITY_HEAT`. A `waterproof_rated` SKU additionally requires `SLIP_RESISTANCE`. A SKU whose `attached_underlayment_type` is anything other than `NONE` additionally requires `PEEL_ADHESION_DELAMINATION`. A SKU whose `construction_type` is `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC` additionally requires `LOCK_SHEAR`. The resulting list is stored in the canonical order `RESIDUAL_INDENTATION`, `DIMENSIONAL_STABILITY_HEAT`, `SLIP_RESISTANCE`, `PEEL_ADHESION_DELAMINATION`, `LOCK_SHEAR`, regardless of the order in which the conditions fired. A glue-down, non-waterproof SKU with no attached underlayment therefore requires exactly two types, while a waterproof `CLICK_LOCK_WPC` SKU with `CORK_2MM` underlayment requires all five.

Starting a panel takes it `SCHEDULED → IN_TEST` or `RETEST_REQUIRED → IN_TEST`; the states `PASSED`, `FAILED` and `VOIDED` accept nothing, and a start from any of them is `ERR_INVALID_PANEL_STATE` (HTTP 409). The SKU must be in `TESTING` or `PROVISIONAL` at that moment too, or the start is refused with `ERR_INVALID_SKU_CERTIFICATION_STATE`. Starting stamps `started_by_user_id` with the acting user and **re-derives** `required_test_types` from the SKU's current configuration, so an edit to the SKU between attempts changes what the next attempt must cover. A restart from `RETEST_REQUIRED` additionally increments `attempt_no` by one; measurements recorded under earlier attempts remain immutable but no longer count toward coverage. A restart is refused with `ERR_RETEST_LIMIT_EXCEEDED` (HTTP 422) once `retest_count` has passed the two permitted retests — that is, once `retest_count` is greater than 2, which happens after three attempts have each ended marginal. A panel parked that way stays in `RETEST_REQUIRED`, and voiding is its only exit.

Recording a measurement is permitted only while the panel is `IN_TEST`, and the operation names a `test_type` and a `measured_value` of at least zero with at most four decimal places. The `test_type` must be a member of the panel's `required_test_types`, and no measurement of that type may already exist at the panel's current `attempt_no`; either violation is `ERR_INVALID_REQUEST` (HTTP 400), evaluated against stored state in band 12 rather than at shape time. A measurement is created carrying the panel's `test_panel_id`, the `attempt_no` in force when it was taken, the `recorded_by_user_id` of the acting technician, and three server-computed fields: `unit`, `spec_limit` and `outcome`.

The `unit` and the `spec_limit` follow from the test type and the SKU. `RESIDUAL_INDENTATION` is measured in `mm` and lower is better, with a limit of 0.10 when the SKU's recipe sits in `CLASS_34_43`, 0.20 for `CLASS_33_42` and 0.30 for `CLASS_23_31`. `DIMENSIONAL_STABILITY_HEAT` is measured in `PCT` and lower is better, with a limit of 0.15 for `CLICK_LOCK_SPC` and `CLICK_LOCK_WPC` constructions and 0.25 for every other construction. `SLIP_RESISTANCE` is measured in `DCOF` and higher is better, with a limit of 0.42 for a `waterproof_rated` SKU and 0.36 otherwise. `PEEL_ADHESION_DELAMINATION` is measured in `N_PER_25MM` and higher is better, with a limit of 35.0 for `IXPE_1MM`, 30.0 for `EVA_1_5MM` and 45.0 for `CORK_2MM`. `LOCK_SHEAR` is measured in `N_PER_MM`, higher is better, and its limit is simply the SKU's `target_lock_shear_n_per_mm`.

Grading uses a marginal band of 500 basis points — five percent — on the permissive side of the limit. For a lower-is-better test the marginal edge is the limit multiplied by 1.05, rounded half up to four decimal places; a `measured_value` no greater than the limit is `PASS`, a value above the limit but no greater than the marginal edge is `MARGINAL`, and anything larger is `FAIL`. For a higher-is-better test the marginal edge is the limit multiplied by 0.95, again at four decimal places; a value at least equal to the limit is `PASS`, a value below the limit but at least the marginal edge is `MARGINAL`, and anything smaller is `FAIL`. Both limits are inclusive, so a reading exactly on the limit passes, and a reading exactly on the marginal edge is `MARGINAL` while one increment beyond it fails.

Each recorded measurement leaves the panel `IN_TEST` while coverage of `required_test_types` at the current `attempt_no` is still incomplete. The instant coverage completes, the panel resolves in one of three ways, and a `FAIL` short-circuits the other two: any measurement graded `FAIL` takes the panel `IN_TEST → FAILED` immediately, without waiting for coverage. Otherwise, if coverage is complete and every outcome at that attempt is `PASS`, the panel moves `IN_TEST → PASSED`. If coverage is complete, no outcome is `FAIL`, and at least one is `MARGINAL`, the panel moves `IN_TEST → RETEST_REQUIRED` and `retest_count` is incremented by one — unconditionally, with no cap applied at this edge. A `MARGINAL` never fails a panel; the only cap in the retest loop lives on the restart, as described above.

Two of those resolutions reach the SKU. A panel that reaches `PASSED` whose coverage includes both `RESIDUAL_INDENTATION` and `DIMENSIONAL_STABILITY_HEAT` moves the SKU's certification `TESTING → PROVISIONAL`. A panel that reaches `FAILED` collapses the SKU's certification: `TESTING → UNCERTIFIED`, or `PROVISIONAL → SUSPENDED`, or `CERTIFIED → SUSPENDED`. Because the certification collapsed, every production run for that SKU whose `run_status` is `PLANNED` or `SETUP` is aborted with `abort_reason` recorded as `SKU_CERTIFICATION_LOST`, releasing each such run's licensed-volume reservation exactly as an operator abort would. A collapse from `CERTIFIED` additionally drags the commercial dimension `RELEASED → HOLD` on the same row, which in turn holds that SKU's `IN_STOCK` batches.

Voiding a panel is available from `SCHEDULED`, `IN_TEST` or `RETEST_REQUIRED` and requires a `void_reason`. Recorded measurements survive the void but stop qualifying for certification, because qualification requires a panel in `PASSED`.

A panel's measurements are readable as a sub-collection, filterable by `test_type`.

### 3.5. Certification, Cost Pinning and Commercial Release

A SKU carries two independent status dimensions, and keeping them independent is deliberate: `certification_status` records what the laboratory and the technical function have established, while `commercial_status` records what the business has decided to sell. They move on different operations and are coupled only at the two points named below.

Beginning testing is a `QaTechnician` action that takes `certification_status` `UNCERTIFIED → TESTING` or `SUSPENDED → TESTING`; from any other certification state it is `ERR_INVALID_SKU_CERTIFICATION_STATE` (HTTP 409). The SKU's `commercial_status` must not be `DISCONTINUED`, and no production run of the SKU may currently be in `SETUP` or `RUNNING` — a SKU cannot re-enter testing while the line is mid-run on it, and such an attempt is `ERR_SKU_NOT_PRODUCIBLE` (HTTP 409). Three referenced rows must be fit: the SKU's recipe must be `APPROVED`, or the request fails with `ERR_FORMULATION_NOT_APPROVED` (HTTP 409); the SKU's print film must be `AVAILABLE`, or `ERR_PRINT_FILM_NOT_AVAILABLE`; and the film's grant must be `ACTIVE` with the logical clock at or after `valid_from` and strictly before `valid_until`, failing which the request returns `ERR_LICENSE_NOT_ACTIVE` for a non-active grant or `ERR_LICENSE_EXPIRED` for a term that has run out — the latter also lazily flipping the grant to `EXPIRED` first. Entering testing wipes the certification record clean: `pin_stale` is set to false and `pinned_formulation_version`, `pinned_print_film_version`, `standard_cost_cents_per_sqm`, `list_price_cents_per_sqm`, `certified_at` and `certified_by_user_id` are all cleared.

Certification is a `TechnicalDirector` action reachable from `TESTING` or `PROVISIONAL` — `certification_status` `TESTING → CERTIFIED` and `PROVISIONAL → CERTIFIED` are treated identically. Its central precondition is complete coverage: for **every** test type in the SKU's required set there must exist a measurement graded `PASS` that was recorded at its panel's current `attempt_no`, on a panel belonging to this SKU whose `status` is `PASSED`. Any required type without such a qualifying measurement is `ERR_TEST_COVERAGE_INCOMPLETE` (HTTP 422), and as noted in §2.5 that error is returned even when the SKU's recipe has meanwhile been superseded. The acting director must not have recorded any of the qualifying measurements (§2.8). The SKU's recipe must be `APPROVED` and the grant behind its film must be `ACTIVE`.

On certification, the SKU pins what it was certified against and stamps its cost. `pinned_formulation_version` is set to the recipe's current `version` and `pinned_print_film_version` to the film's current `version`. `standard_cost_cents_per_sqm` is computed on the pinned basis described in §3.3 and stored, and `list_price_cents_per_sqm` is derived from it by the `target_margin_bps` gross-up. `pin_stale` is set to false, `certified_at` to the logical clock and `certified_by_user_id` to the acting user.

A pin goes stale on its own. Whenever the SKU's recipe moves to `SUPERSEDED` or `RETIRED`, or its `version` ceases to equal the SKU's `pinned_formulation_version`, `pin_stale` becomes true. That is how a certified SKU can lose the right to be sold without any commercial action being taken against it, and the cost summary reports the flag so that the loss is visible before anyone tries to act on it.

The commercial dimension is driven by a `PlantAdmin` supplying a `to_status`. `DEVELOPMENT → RELEASED` and `HOLD → RELEASED` are both declared, as is `RELEASED → HOLD`, giving a `RELEASED → HOLD → RELEASED` cycle; `DISCONTINUED` is reachable from `DEVELOPMENT`, `RELEASED` or `HOLD` and is terminal on this dimension. A `to_status` that is not reachable from the SKU's current `commercial_status` is `ERR_INVALID_COMMERCIAL_STATE` (HTTP 409). Reaching `RELEASED` is additionally guarded across the dimension boundary: the SKU's `certification_status` must be exactly `CERTIFIED` and its `pin_stale` must be false, and a violation of either is `ERR_SKU_NOT_PRODUCIBLE` (HTTP 409).

Going on hold cascades: every batch of the SKU whose `status` is `IN_STOCK` moves to `HELD` with `hold_reason` `SKU_ON_HOLD`. Coming back off hold does **not** release those batches; a held batch needs its own hold-release action. Discontinuation is the heavier ending. It forces `certification_status` to `DECERTIFIED` on the same row — the one place where a commercial decision overwrites the certification dimension — and it cancels every allocation for the SKU whose `status` is `OPEN` or `PARTIALLY_FILLED`, deliberately leaving `FILLED` allocations alone. Each cancelled allocation has every `ACTIVE` line voided with `void_reason` `ALLOCATION_CANCELLED`, and each voided line's `quantity_sqm` is added back to its batch's `available_quantity_sqm`.

### 3.6. Press and Calender Line Scheduling

A press line is registered by a `PlantAdmin` with a `line_code` unique across lines, a `line_type` naming its forming technology, a `min_thickness_mm` greater than zero and a `max_thickness_mm` strictly greater than it (otherwise `ERR_INVALID_REQUEST`, HTTP 400), a `changeover_minutes` allowance of at least zero, and a `curl_control_index` between 0 and 100 that sets how tight a curl band the line can hold. Lines are created `AVAILABLE` unless the request overrides `status`, and a `PlantAdmin` may later drive `status` with a `to_status` of `AVAILABLE`, `MAINTENANCE` or `DOWN`. A line that is not `AVAILABLE` blocks run scheduling, run setup and run starting with `ERR_PRESS_LINE_UNAVAILABLE` (HTTP 409), while windows already reserved on it stay reserved.

A `ProductionPlanner` schedules a run by supplying a `run_code` unique across runs, the `sku_id` to be formed, the `press_line_id` to occupy, an inclusive `planned_start_utc`, an exclusive `planned_end_utc` that must be strictly later than the start, and a `planned_quantity_sqm` greater than zero at two decimal places. The run is created with `run_status` `PLANNED` and `qc_disposition` `PENDING`, with `changeover_minutes_applied` null, `actual_quantity_sqm` 0, `royalty_accrued_cents` 0, and every measured and derived quality field null.

Scheduling is the most heavily guarded operation in the system, and its checks fall in the band order of §2.5. The SKU must be producible: its `certification_status` must be `TESTING`, `PROVISIONAL` or `CERTIFIED` and its `commercial_status` must not be `DISCONTINUED`, failing which the request is `ERR_SKU_NOT_PRODUCIBLE`. The line must be `AVAILABLE`. The SKU's `overall_thickness_mm` must lie within the line's forming range, at least `min_thickness_mm` and no greater than `max_thickness_mm`; outside that range the request is `ERR_THICKNESS_OUT_OF_LINE_RANGE` (HTTP 422). The film must be `AVAILABLE` and the grant must be `ACTIVE` with `planned_start_utc` at or after `valid_from` and strictly before `valid_until`.

Then come three interval rules, and their geometries deliberately differ.

**Line occupation** treats a run's window as half-open, from `planned_start_utc` inclusive to `planned_end_utc` exclusive. Two runs on the same line collide when the new run's start is strictly earlier than the other's end **and** the other's start is strictly earlier than the new run's end, counting only runs whose `run_status` is not `ABORTED`. Touching endpoints therefore do not collide: a run beginning exactly at another's `planned_end_utc` is disjoint and admissible. A collision is `ERR_PRESS_LINE_WINDOW_CONFLICT` (HTTP 409).

**The changeover buffer** goes beyond disjointness. The relevant predecessor is the run on the same line with the greatest `planned_end_utc` that is no later than the new run's `planned_start_utc` and whose `run_status` is not `ABORTED`, with ties broken by the earlier `created_at`; an aborted predecessor is skipped entirely, so the gap is measured against whatever ran before it. If no such predecessor exists the required gap is zero minutes. Otherwise, take the line's `changeover_minutes` and apply a relatedness multiplier: 0.50 when the predecessor's SKU shares this SKU's `formulation_id`, 0.75 when it instead shares this SKU's `print_film_id`, and 1.00 when it shares neither. The ladder is ordered, so a pair sharing both keys takes 0.50, not 0.75. Round the multiplied base **up** to a whole minute, and only then add a thickness surcharge: 30 minutes when the absolute difference between the two SKUs' `overall_thickness_mm` values is at least 2.0 millimetres, 10 minutes when that difference is at least 0.5 but below 2.0, and nothing below 0.5. The gap in whole minutes from the predecessor's `planned_end_utc` to the new run's `planned_start_utc` must be at least that required figure; equality passes, and a shortfall is `ERR_CHANGEOVER_GAP_INSUFFICIENT` (HTTP 409). A line with a `changeover_minutes` of 0 running unrelated SKUs across a 2.5-millimetre thickness step therefore still demands 30 minutes.

**Roll-set capacity** on the print film uses a *closed* interval — from `planned_start_utc` through `planned_end_utc` inclusive — because a roll set cannot be re-threaded instantaneously, so here touching endpoints *do* collide. It is also an aggregate capacity rule rather than a pairwise exclusion: count the runs on the same `print_film_id` whose closed windows intersect the new run's closed window and whose `run_status` is not `ABORTED`, and reject only when that count is at least the film's `master_roll_sets`. The rejection is `ERR_PRINT_FILM_ROLL_CAPACITY_EXCEEDED` (HTTP 409).

The last admission check is fiscal. The grant's projected volume is its `consumed_volume_sqm` plus its `reserved_volume_sqm` plus the new run's `planned_quantity_sqm`, and that projection may not exceed `term_volume_cap_sqm`; equality is admitted, and an excess is `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422). This is a forward-looking projection: volume merely reserved by runs in `PLANNED`, `SETUP` or `RUNNING` counts against the cap even though nothing has physically been produced, which is exactly what makes an admission fail on a grant that has produced nothing at all. On success, the run's `planned_quantity_sqm` is added to the grant's `reserved_volume_sqm` and the grant's `version` is advanced.

Setup takes the run `PLANNED → SETUP` and is where the changeover allowance is persisted. It requires the SKU's `certification_status` to be `PROVISIONAL` or `CERTIFIED` and its `commercial_status` to be `DEVELOPMENT` or `RELEASED` — the admission window narrows between scheduling and setup, and a SKU that has slipped outside it is `ERR_SKU_NOT_PRODUCIBLE`. The line must still be `AVAILABLE`. And the logical clock must have reached `planned_start_utc` minus 120 minutes: setup may not begin more than two hours before the planned start, and an early attempt is `ERR_SETUP_TOO_EARLY` (HTTP 409). The gap computation above is re-evaluated against the current predecessor and stored in `changeover_minutes_applied`.

Starting takes the run `SETUP → RUNNING`. The line must be `AVAILABLE`, the film must be `AVAILABLE`, and the grant must be `ACTIVE` with the logical clock strictly before its `valid_until`. One safety rule sits here and nowhere else: when the SKU is `waterproof_rated`, there must exist a test panel of that SKU whose `status` is `PASSED` that both holds a `SLIP_RESISTANCE` measurement graded `PASS` at that panel's `attempt_no` and whose `updated_at` is strictly later than the logical clock minus 180 days. A SKU that never qualified and a SKU whose slip qualification has aged out are both refused with `ERR_SLIP_RESISTANCE_NOT_QUALIFIED` (HTTP 422). Because the 180-day window is read at start time rather than at scheduling time, a run planned comfortably inside the window but started after it lapses is rejected, and the qualification must be repeated before the line can turn.

Completion takes the run `RUNNING → COMPLETED` and carries the shop-floor measurements: `actual_quantity_sqm`, `registration_drift_mm`, `curl_deviation_mm`, `emboss_alignment_offset_mm` and `wear_layer_measured_mil` are all required, and `measured_tongue_thickness_mm` is supplied only for a milled profile. Four things then happen in the same request.

First, the four QC gates and the pattern waste are computed. `pattern_waste_sqm` is the run's `actual_quantity_sqm` multiplied by the larger of the film's two pattern repeats, divided by 60000, multiplied by 0.35, rounded half up to two decimal places. `registration_within_tolerance` holds when the absolute value of `registration_drift_mm` is no greater than the film's `registration_tolerance_mm`. `emboss_within_tolerance` holds when the absolute difference between the run's `emboss_alignment_offset_mm` and the film's nominal `emboss_alignment_offset_mm` is no greater than 0.30 millimetres. The curl allowance is 2.00 millimetres multiplied by the quantity 100 minus the line's `curl_control_index`, divided by 100, rounded half up to two decimal places, and `curl_within_tolerance` holds when the absolute value of `curl_deviation_mm` is no greater than that allowance — so a better-controlled line permits less curl deviation, and a line with a `curl_control_index` of 100 permits none at all. `tongue_within_tolerance` is forced true when the SKU's `profile_family` is `NONE`, ignoring `measured_tongue_thickness_mm` entirely; otherwise it holds when `measured_tongue_thickness_mm` is at least `tongue_thickness_target_mm` minus `tolerance_minus_mm` and no greater than `tongue_thickness_target_mm` plus `tolerance_plus_mm`. All four comparisons are inclusive, so a measurement exactly on its tolerance passes. `auto_disposition_recommendation` is set to `RELEASED` when all four gates hold and `QUARANTINED` otherwise; it is advisory only.

Second, the licensed-volume ledger settles on an actual basis: the run's `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm` and the measured `actual_quantity_sqm` is added to its `consumed_volume_sqm`. The reservation is released at its *planned* size while the *measured* quantity is consumed, so when actual output differs from plan the two figures diverge — and the cap is deliberately not re-checked at completion, which means `consumed_volume_sqm` may end up above what the admission projection assumed.

Third, the run's royalty is accrued. The run's `actual_quantity_sqm` is multiplied by the SKU's `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps` divided by 10000, and the product is rounded half up to a whole cent. That integer is stored in the run's `royalty_accrued_cents` and added to the grant's `accrued_royalty_cents`, one run at a time, per the rounding-order rule of §2.6.

Fourth, provided `actual_quantity_sqm` is strictly greater than zero, exactly one batch is minted. A run that reports exactly zero output accrues zero royalty and mints no batch at all. The completing user is recorded in `completed_by_user_id`, and the run's `version` and the grant's `version` are both advanced.

Aborting is available from `PLANNED`, `SETUP` or `RUNNING` with an `abort_reason`, and it is an exact compensation: the run's `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`, restoring that figure to its pre-scheduling value bit for bit. No batch is minted and no royalty is accrued, so a schedule-then-abort pair leaves the ledger indistinguishable from never having scheduled. A run's `run_status` outside the declared from-set of the requested step is `ERR_INVALID_RUN_STATE` (HTTP 409).

### 3.7. QC Disposition, Batch Traceability and Stock Holds

A batch is the plant's unit of traceability, and it is never created by a client. When a run completes with positive output, the batch is minted with a `batch_code` formed as the producing run's `run_code` followed by the suffix `-B1`, a `production_run_id` pointing at that run, a `sku_id` denormalised from it for stock selection, a `quantity_sqm` equal to the run's `actual_quantity_sqm` that never changes thereafter, an `available_quantity_sqm` of 0, and a `wear_layer_measured_mil` copied from the run's measurement — the reading that will later serve as warranty defect evidence. Its `status` is `IN_PRODUCTION` and `hold_reason` and `held_by_user_id` are null.

The batch also carries an immutable `traceability_snapshot` captured at that instant, recording the recipe's `formulation_code` and revision number, the pinned `blended_cost_per_kg_cents`, the print film's design code, the grant's `license_code`, the press line's code, the run's `planned_start_utc` and `planned_end_utc`, and the SKU's specified wear-layer thickness. That snapshot is what makes a warranty claim adjudicable years later, and a batch without it cannot found a claim.

Quality disposition is a `QaTechnician` decision expressed as a `to_disposition`, with an optional `hold_reason`. It requires the run's `run_status` to be `COMPLETED`; a disposition against a run in any other execution state, or a `to_disposition` not reachable from the run's current `qc_disposition`, is `ERR_INVALID_QC_TRANSITION` (HTTP 409). `SCRAPPED` is terminal on this dimension.

`PENDING → RELEASED` and `QUARANTINED → RELEASED` both require all four QC gates to hold. A run with any of `registration_within_tolerance`, `emboss_within_tolerance`, `curl_within_tolerance` or `tongue_within_tolerance` false may not be released, and the attempt is `ERR_QC_GATES_NOT_MET` (HTTP 422). The advisory recommendation runs one way only: a technician may still quarantine a run whose gates all hold, but may not release one whose gates do not. Releasing moves the run's batch `IN_PRODUCTION → IN_STOCK` (or `HELD → IN_STOCK` when the batch was quarantined earlier) and sets `available_quantity_sqm` to the full `quantity_sqm`.

`PENDING → QUARANTINED` moves the batch `IN_PRODUCTION → HELD` with `hold_reason` `QC_QUARANTINE` and `held_by_user_id` set to the acting technician — which, by §2.8, means someone else must later release it.

`SCRAPPED` is reachable from `PENDING`, `QUARANTINED` or `RELEASED`, and it unwinds the completion exactly. The run's `actual_quantity_sqm` is subtracted from the grant's `consumed_volume_sqm`, and the run's stored `royalty_accrued_cents` is subtracted from the grant's `accrued_royalty_cents` before the run's own figure is set to 0 — the reversal uses the stored integer rather than a fresh computation. The run's batch moves to `SCRAPPED` with `available_quantity_sqm` set to 0. And because that batch was scrapped, every `ACTIVE` allocation line drawn on it becomes `VOIDED` with `void_reason` `BATCH_SCRAPPED`, with each owning allocation recomputing `allocated_quantity_sqm` and `upgrade_cost_total_cents` and stepping `FILLED → PARTIALLY_FILLED` or `PARTIALLY_FILLED → OPEN`. The run, the grant and the batch all have their `version` advanced.

Stock holds are the `QaTechnician`'s direct control over finished inventory, driven by an `action` of `HOLD`, `RELEASE_HOLD` or `SCRAP` with an optional `hold_reason`. Holding requires the batch to be `IN_STOCK`, releasing requires it to be `HELD`, and scrapping requires any non-`SCRAPPED` batch; a mismatch is `ERR_INVALID_BATCH_STATE` (HTTP 409).

`IN_STOCK → HELD` records `held_by_user_id` as the acting user — or the string `system` when the transition arrived through a SKU-hold cascade rather than an operator action — and voids every `ACTIVE` allocation line on the batch with `void_reason` `BATCH_HELD`, adding each line's `quantity_sqm` back to `available_quantity_sqm` and stepping the owning allocations back as above.

`HELD → IN_STOCK` closes the `IN_STOCK → HELD → IN_STOCK` cycle and carries three preconditions beyond the state check. The acting user may not be the batch's `held_by_user_id` (§2.8). The producing run's `qc_disposition` must be `RELEASED`, or the release is `ERR_RUN_NOT_RELEASED` (HTTP 409). And the batch's SKU must still be sellable: its `commercial_status` must not be `DISCONTINUED` and its `certification_status` must be neither `SUSPENDED` nor `DECERTIFIED`, failing which the release is `ERR_SKU_NOT_PRODUCIBLE`. Releasing clears `hold_reason` and `held_by_user_id` and recomputes `available_quantity_sqm` as `quantity_sqm` less the sum of the `ACTIVE` allocation-line quantities still drawn on the batch — not as the full quantity, because lines placed before the hold may still stand.

`SCRAP` from `IN_STOCK` or `HELD` sets `available_quantity_sqm` to 0 and voids every `ACTIVE` line with `void_reason` `BATCH_SCRAPPED`, recomputing each owning allocation. A batch's allocation lines are readable in the reverse direction, filterable by line `status`.

### 3.8. Distributor Allocations and Substitution Fills

Distributors are the plant's trading partners, registered by a `PlantAdmin` with an `account_code` unique across distributors and between 3 and 32 characters long, a legal `name`, a `territory_code` of exactly two uppercase letters naming the territory sold into, and an optional `certified_installer_program` flag (false by default) recording participation in the certified-installer scheme — the flag that later unlocks a labour allowance on warranty settlements. A distributor is created `ACTIVE` unless the request overrides `status`.

An allocation is a request for stock, created by a `Distributor` for its own account or by a `PlantAdmin` on a distributor's behalf. It carries an `allocation_code` unique across allocations, the `distributor_id` that owns it, the `sku_id` asked for, a `requested_quantity_sqm` greater than zero at two decimal places, and an optional `substitution_policy` that defaults to `STRICT_SKU`. The SKU must be `CERTIFIED` at creation time — an allocation may not be raised against a SKU that has never been certified or has lost certification, and the attempt is `ERR_SKU_NOT_PRODUCIBLE` (HTTP 409). A new allocation is `OPEN` with `allocated_quantity_sqm` and `upgrade_cost_total_cents` both 0.

Filling is the `Distributor`'s draw against finished stock, and it carries `expected_allocation_version` as described in §2.7. The allocation must not be `RELEASED` or `CANCELLED`; either is `ERR_INVALID_ALLOCATION_STATE` (HTTP 409). A `FILLED` allocation is deliberately *not* rejected on those state grounds — it is a legitimate fill target as far as the lifecycle is concerned — and is instead refused later, on the constraint that its `allocated_quantity_sqm` has already reached its `requested_quantity_sqm` and there is nothing left to draw: `ERR_ALLOCATION_OVER_REQUEST` (HTTP 422). The SKU must currently be `RELEASED` on its commercial dimension, or the fill is `ERR_SKU_NOT_PRODUCIBLE`.

The fill selector then runs in four ordered steps, and the order is part of the contract.

**Step one, eligibility.** A batch is a candidate only when its `status` is `IN_STOCK`, its `available_quantity_sqm` is strictly greater than zero, its producing run's `qc_disposition` is `RELEASED`, and its own SKU's `commercial_status` is not `DISCONTINUED`. Which SKUs qualify depends on the allocation's `substitution_policy`, and every policy admits an exact match plus at most one kind of upgrade. An `EXACT` candidate is one whose batch carries the requested `sku_id` itself. An `UNDERLAYMENT_UPGRADE` candidate is admissible only under the `ALLOW_UNDERLAYMENT_UPGRADE` policy, and only when the requested SKU's `attached_underlayment_type` is `NONE`, the candidate SKU's is not `NONE`, and the two SKUs agree exactly on `formulation_id`, `print_film_id`, `construction_type` and `wear_layer_mil`. A `WEAR_LAYER_UPGRADE` candidate is admissible only under the `ALLOW_WEAR_LAYER_UPGRADE` policy, and only when the candidate SKU's `wear_layer_mil` is strictly greater than the requested SKU's and the two agree exactly on `formulation_id`, `print_film_id`, `construction_type`, `attached_underlayment_type` and `waterproof_rated`. `STRICT_SKU` admits exact matches only. If the candidate set is empty, the fill is refused with `ERR_NO_ELIGIBLE_BATCH` (HTTP 409) and the allocation is left completely untouched.

**Step two, ranking.** Candidates are ordered by substitution kind first — exact matches ahead of underlayment upgrades, which are ahead of wear-layer upgrades — then by the batch's `created_at` ascending, then by `batch_code` ascending. An exact match therefore always outranks any upgrade batch, however much older the upgrade batch is. The ranking may **not** consult upgrade cost; the per-line premiums do not even exist until step four, and ranking cheapest-upgrade-first produces a different, incorrect line set.

**Step three, the waterfall.** The remaining requirement is the allocation's `requested_quantity_sqm` less its current `allocated_quantity_sqm`, rounded half up to two decimal places. Walking the candidates in rank order while the remaining requirement is strictly positive, each candidate contributes the smaller of the remaining requirement and its own `available_quantity_sqm`. One allocation line is created per drawn batch, carrying the `allocation_id` it fills, the `batch_id` drawn on, the `quantity_sqm` drawn, and its `substitution_kind`; the batch's `available_quantity_sqm` is decremented by that quantity and its `version` advanced, and the remaining requirement falls by the same amount. The first candidate is drained completely before the second is touched, even when the second alone would have covered the whole request.

**Step four, the upgrade premium.** Each line's `upgrade_cost_delta_cents` is 0 when its `substitution_kind` is `EXACT`. Otherwise, take the per-square-metre premium as the candidate SKU's `standard_cost_cents_per_sqm` less the requested SKU's, floored at zero so that a cheaper substitute contributes nothing rather than a credit, and treated as zero outright if either SKU's standard cost is null. Multiply that premium by the line's `quantity_sqm` and round half up to a whole cent. The allocation's `allocated_quantity_sqm` is then the sum of its `ACTIVE` lines' quantities at two decimal places, and its `upgrade_cost_total_cents` is the exact sum of those already-rounded per-line integers.

The allocation's resulting `status` follows from the arithmetic: `FILLED` when `allocated_quantity_sqm` has reached `requested_quantity_sqm`, `PARTIALLY_FILLED` when it is above zero but short of the request, and `OPEN` when it is zero. So `OPEN → PARTIALLY_FILLED`, `OPEN → FILLED` and `PARTIALLY_FILLED → FILLED` are all reachable from one fill, depending on how much stock the waterfall found.

The reverse edges are driven by cascades rather than by requests. When a batch is held or scrapped and voids one of an allocation's `ACTIVE` lines, the allocation recomputes `allocated_quantity_sqm` and `upgrade_cost_total_cents` and moves `FILLED → PARTIALLY_FILLED`; when the last `ACTIVE` line goes, both figures become 0 and the allocation moves `PARTIALLY_FILLED → OPEN`, completing the `OPEN → PARTIALLY_FILLED → FILLED → PARTIALLY_FILLED → OPEN` cycle.

Releasing an allocation is the `Distributor`'s clean withdrawal, available from `OPEN`, `PARTIALLY_FILLED` or `FILLED` and refused from `RELEASED` or `CANCELLED` with `ERR_INVALID_ALLOCATION_STATE`. Every `ACTIVE` line becomes `VOIDED` with `void_reason` `ALLOCATION_RELEASED` and its `quantity_sqm` is added back to its batch's `available_quantity_sqm`, restoring the stock ledger exactly; `allocated_quantity_sqm` and `upgrade_cost_total_cents` both become 0, and every touched batch has its `version` advanced. Releasing an allocation that never drew anything simply moves it to `RELEASED` with nothing to void. `CANCELLED` is not reachable by request at all: it arrives only from the discontinuation cascade of §3.5, and only for allocations that were `OPEN` or `PARTIALLY_FILLED`.

An allocation's lines are readable as a sub-collection, filterable by line `status`.

### 3.9. Warranty Claims: Triage, Branch Reviews and Settlement

A warranty claim is filed either by the `Distributor` on whose account the floor was sold or by a `WarrantyAdjuster` acting for them. It carries a `claim_code` unique across claims, the `batch_id` the flooring came from, the `distributor_id` filing it, a `claim_type` naming the failure mode, a `claimed_area_sqm` greater than zero at two decimal places, an `installed_on` date, a `reported_on` date that may not precede it, and an optional `installed_by_certified_installer` flag defaulting to false. A `reported_on` earlier than `installed_on` is refused with `ERR_CLAIM_DATES_INVALID` (HTTP 400). The batch must be traceable: a batch without a `traceability_snapshot`, or a batch still in `IN_PRODUCTION` — stock that never reached the market cannot found a field claim — is `ERR_BATCH_NOT_TRACEABLE` (HTTP 409). New claims are `SUBMITTED` with `required_reviews`, both review outcomes, `assigned_adjuster_user_id`, `elapsed_months`, `settlement_variant`, `replacement_value_cents`, `labor_allowance_cents`, `settlement_amount_cents` and `denial_reason` all unset.

Triage is a `WarrantyAdjuster` action taking the claim `SUBMITTED → TRIAGE`. The batch must still be traceable and must not be `SCRAPPED` — a scrapped batch is `ERR_INVALID_BATCH_STATE` (HTTP 409). Triage stamps `assigned_adjuster_user_id` with the acting adjuster and **forks** the investigation by setting `required_reviews`: a `DELAMINATION` or `LOCK_FAILURE` claim requires both a materials review and a field review, while a `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim requires the field review only.

Each branch is answered by recording a review: a `review_kind` naming which arm is being answered, an `outcome`, and an optional `note`. The claim must be in `TRIAGE`; from any other state the attempt is `ERR_INVALID_CLAIM_STATE` (HTTP 409). The `review_kind` must be a member of `required_reviews`, and the matching outcome field must still be unset — a second answer to an arm already answered, or an answer to an arm this `claim_type` did not fork, is `ERR_INVALID_REQUEST` (HTTP 400). The outcome is written into `materials_review_outcome` or `field_review_outcome` according to the arm. The claim stays in `TRIAGE` while any required arm is unanswered; the instant every required arm carries a non-null outcome, the claim joins `TRIAGE → ADJUDICATION_READY`.

Adjudication is the final decision, expressed as a `decision` of approve or deny with an optional `denial_reason` recorded on a denial. The claim must be `ADJUDICATION_READY`, and the acting adjuster may not be the one who triaged it (§2.8). A denial takes the claim `ADJUDICATION_READY → DENIED`, records `denial_reason` and leaves `settlement_amount_cents` null. An approval takes it `ADJUDICATION_READY → APPROVED` and requires two further things: every required review outcome must be `DEFECT_CONFIRMED`, and any arm answered `NO_DEFECT` or `INCONCLUSIVE` makes the approval `ERR_REVIEW_OUTCOME_CONFLICT` (HTTP 409); and the warranty coverage must not be exhausted.

Coverage is measured in whole calendar months. `elapsed_months` is the number of whole calendar months from `installed_on` to `reported_on`, floored, so a partial month does not count. The coverage term is the SKU's `warranty_years` multiplied by 12, and an approval whose `elapsed_months` has reached or passed that figure is refused with `ERR_WARRANTY_EXPIRED` (HTTP 409) before any settlement is computed — a claim at exactly the coverage boundary has no remaining months and is expired.

An approved settlement is then computed in four movements. The `replacement_value_cents` is the `claimed_area_sqm` multiplied by the SKU's `royalty_basis_price_cents_per_sqm`, rounded half up to a whole cent. The `labor_allowance_cents` is the `claimed_area_sqm` multiplied by 350 cents per square metre, rounded half up to a whole cent, when `installed_by_certified_installer` is true, and 0 otherwise.

The decay of the replacement value depends on the `claim_type`, and the chosen variant is recorded in `settlement_variant`. A `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim uses `PRORATED_STRAIGHT_LINE`: the remaining months — the coverage term less `elapsed_months`, floored at zero — divided by the coverage term, applied to the replacement value and rounded half up to a whole cent. A `DELAMINATION` or `LOCK_FAILURE` claim uses `STEPPED_SCHEDULE`: take the elapsed whole years as `elapsed_months` divided by twelve rounded down, then apply 100 percent when that figure is 1 or less, 80 percent when it is 2 or 3, 60 percent when it is 4 through 7, 40 percent when it is 8 through 12, and 20 percent beyond that, rounding the result half up to a whole cent. Identical inputs therefore settle differently under the two variants everywhere except inside the first step.

One override outranks both variants. A **manufacturing defect** is confirmed when the batch's `wear_layer_measured_mil` is strictly less than the SKU's specified `wear_layer_mil` minus 0.5 mil — the tolerance the plant accepts on wear-layer thickness. A measurement exactly equal to the specified thickness less 0.5 is *not* a defect, because the comparison is strict. When a defect is confirmed, the covered value is the full `replacement_value_cents` with no decay at all under either variant, so the variant becomes unobservable in the amount even though it is still recorded in `settlement_variant`. The `settlement_amount_cents` is the covered value plus the `labor_allowance_cents`, added as two already-rounded integers.

## 4. Endpoint Definitions

Every collection is mounted at the API root; there is no shared path prefix and no URL nesting for identity, only for sub-resource reads. Operations that create a new resource respond with HTTP 201; every other successful operation, including every state transition and every read, responds with HTTP 200. Successful responses return the created or affected resource in `data` unless the operation is a computed read, in which case `data` carries the computed shape described in §3. The table below is a routing index only: request bodies, response contents and side effects are specified in §2 and §3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| `POST` | `/distributors` | Register a trading partner | `PlantAdmin` |
| `GET` | `/distributors` | List trading partners | `PlantAdmin`, `ProductionPlanner`, `WarrantyAdjuster`, `Distributor` |
| `GET` | `/distributors/{id}` | Read one trading partner | `PlantAdmin`, `ProductionPlanner`, `WarrantyAdjuster`, `Distributor` |
| `POST` | `/raw-materials` | Register a raw material | `PlantAdmin` |
| `GET` | `/raw-materials` | List raw materials | `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician` |
| `GET` | `/raw-materials/{id}` | Read one raw material | `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician` |
| `GET` | `/raw-materials/{id}/formulation-components` | List the recipe components dosing this material | `PlantAdmin`, `Formulator`, `TechnicalDirector` |
| `POST` | `/raw-materials/{id}/status` | Drive procurement status; restriction starts the five-hop cascade | `PlantAdmin` |
| `POST` | `/raw-materials/{id}/cost` | Revalue purchase cost; recomputes live-basis recipes only | `PlantAdmin` |
| `POST` | `/formulations` | Author a compound recipe | `Formulator` |
| `GET` | `/formulations` | List recipes | `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician`, `ProductionPlanner` |
| `GET` | `/formulations/{id}` | Read one recipe | `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician`, `ProductionPlanner` |
| `GET` | `/formulations/{id}/components` | List a recipe's components | `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician` |
| `POST` | `/formulations/{id}/components` | Dose a material into a recipe | `Formulator` |
| `DELETE` | `/formulations/{id}/components/{component_id}` | Remove a dosage from a recipe | `Formulator` |
| `POST` | `/formulations/{id}/submit` | Submit a recipe for technical review | `Formulator` |
| `POST` | `/formulations/{id}/review-decision` | Approve or reject a recipe under review | `TechnicalDirector` |
| `POST` | `/formulations/{id}/revisions` | Open a draft revision of an approved recipe | `Formulator` |
| `POST` | `/design-licenses` | Register a design grant | `PlantAdmin` |
| `GET` | `/design-licenses` | List design grants | `PlantAdmin`, `TechnicalDirector`, `ProductionPlanner`, `Formulator` |
| `GET` | `/design-licenses/{id}` | Read one design grant | `PlantAdmin`, `TechnicalDirector`, `ProductionPlanner`, `Formulator` |
| `GET` | `/design-licenses/{id}/utilization` | Computed volume and royalty utilization of a grant | `PlantAdmin`, `TechnicalDirector`, `ProductionPlanner` |
| `POST` | `/design-licenses/{id}/amendments` | Amend a grant, creating a successor and superseding it | `TechnicalDirector` |
| `POST` | `/design-licenses/{id}/status` | Suspend, reactivate or terminate a grant | `PlantAdmin`, `TechnicalDirector` |
| `POST` | `/print-films` | Register a print film design | `PlantAdmin` |
| `GET` | `/print-films` | List print film designs | `PlantAdmin`, `TechnicalDirector`, `ProductionPlanner`, `QaTechnician` |
| `GET` | `/print-films/{id}` | Read one print film design | `PlantAdmin`, `TechnicalDirector`, `ProductionPlanner`, `QaTechnician` |
| `POST` | `/print-films/{id}/status` | Restrict, restore or withdraw a design | `PlantAdmin` |
| `POST` | `/product-skus` | Define a finished-goods SKU | `PlantAdmin` |
| `GET` | `/product-skus` | List SKUs | `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician`, `ProductionPlanner`, `Distributor` |
| `GET` | `/product-skus/{id}` | Read one SKU | `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician`, `ProductionPlanner`, `Distributor` |
| `GET` | `/product-skus/{id}/cost-summary` | Computed live-basis and pinned-basis cost breakdown | `PlantAdmin`, `TechnicalDirector`, `Formulator` |
| `POST` | `/product-skus/{id}/begin-testing` | Move certification into testing and clear the pins | `QaTechnician` |
| `POST` | `/product-skus/{id}/certify` | Certify a SKU, pinning versions and stamping cost | `TechnicalDirector` |
| `POST` | `/product-skus/{id}/commercial-status` | Release, hold or discontinue a SKU commercially | `PlantAdmin` |
| `POST` | `/press-lines` | Register a press or calender line | `PlantAdmin` |
| `GET` | `/press-lines` | List lines | `PlantAdmin`, `ProductionPlanner`, `QaTechnician` |
| `GET` | `/press-lines/{id}` | Read one line | `PlantAdmin`, `ProductionPlanner`, `QaTechnician` |
| `POST` | `/press-lines/{id}/status` | Drive line availability | `PlantAdmin` |
| `POST` | `/test-panels` | Register a laboratory panel for a SKU | `QaTechnician` |
| `GET` | `/test-panels` | List panels | `PlantAdmin`, `QaTechnician`, `TechnicalDirector`, `Formulator` |
| `GET` | `/test-panels/{id}` | Read one panel | `PlantAdmin`, `QaTechnician`, `TechnicalDirector`, `Formulator` |
| `GET` | `/test-panels/{id}/results` | List a panel's measurements | `PlantAdmin`, `QaTechnician`, `TechnicalDirector`, `Formulator` |
| `POST` | `/test-panels/{id}/start` | Start or restart a panel attempt | `QaTechnician` |
| `POST` | `/test-panels/{id}/results` | Record a graded measurement | `QaTechnician` |
| `POST` | `/test-panels/{id}/void` | Void a panel | `QaTechnician` |
| `POST` | `/production-runs` | Schedule a run and reserve licensed volume | `ProductionPlanner` |
| `GET` | `/production-runs` | List runs | `PlantAdmin`, `ProductionPlanner`, `QaTechnician`, `TechnicalDirector` |
| `GET` | `/production-runs/{id}` | Read one run | `PlantAdmin`, `ProductionPlanner`, `QaTechnician`, `TechnicalDirector` |
| `POST` | `/production-runs/{id}/setup` | Begin setup and charge the changeover allowance | `ProductionPlanner` |
| `POST` | `/production-runs/{id}/start` | Start the line | `ProductionPlanner` |
| `POST` | `/production-runs/{id}/complete` | Complete a run, settle the ledger and mint the batch | `ProductionPlanner` |
| `POST` | `/production-runs/{id}/abort` | Abort a run and release its reservation | `ProductionPlanner` |
| `POST` | `/production-runs/{id}/qc-disposition` | Release, quarantine or scrap a completed run | `QaTechnician` |
| `GET` | `/batches` | List finished batches | `PlantAdmin`, `ProductionPlanner`, `QaTechnician`, `WarrantyAdjuster`, `Distributor` |
| `GET` | `/batches/{id}` | Read one batch with its traceability evidence | `PlantAdmin`, `ProductionPlanner`, `QaTechnician`, `WarrantyAdjuster`, `Distributor` |
| `GET` | `/batches/{id}/allocation-lines` | List the allocation lines drawn on a batch | `PlantAdmin`, `ProductionPlanner`, `QaTechnician`, `Distributor` |
| `POST` | `/batches/{id}/hold-status` | Hold, release or scrap finished stock | `QaTechnician` |
| `POST` | `/allocations` | Raise a stock allocation request | `Distributor`, `PlantAdmin` |
| `GET` | `/allocations` | List allocations | `PlantAdmin`, `ProductionPlanner`, `Distributor` |
| `GET` | `/allocations/{id}` | Read one allocation | `PlantAdmin`, `ProductionPlanner`, `Distributor` |
| `GET` | `/allocations/{id}/lines` | List an allocation's lines | `PlantAdmin`, `ProductionPlanner`, `Distributor` |
| `POST` | `/allocations/{id}/fill` | Draw stock against an allocation | `Distributor` |
| `POST` | `/allocations/{id}/release` | Release an allocation and return its stock | `Distributor` |
| `POST` | `/warranty-claims` | File a warranty claim against a traceable batch | `Distributor`, `WarrantyAdjuster` |
| `GET` | `/warranty-claims` | List warranty claims | `PlantAdmin`, `WarrantyAdjuster`, `QaTechnician`, `Distributor` |
| `GET` | `/warranty-claims/{id}` | Read one warranty claim | `PlantAdmin`, `WarrantyAdjuster`, `QaTechnician`, `Distributor` |
| `POST` | `/warranty-claims/{id}/triage` | Triage a claim and fork its required reviews | `WarrantyAdjuster` |
| `POST` | `/warranty-claims/{id}/reviews` | Record a branch review outcome | `WarrantyAdjuster` |
| `POST` | `/warranty-claims/{id}/adjudicate` | Approve or deny a claim and settle it | `WarrantyAdjuster` |
| `POST` | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | `PlantAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CLAIM_DATES_INVALID` | 400 |
| `ERR_DISTRIBUTOR_NOT_FOUND` | 404 |
| `ERR_RAW_MATERIAL_NOT_FOUND` | 404 |
| `ERR_FORMULATION_NOT_FOUND` | 404 |
| `ERR_FORMULATION_COMPONENT_NOT_FOUND` | 404 |
| `ERR_DESIGN_LICENSE_NOT_FOUND` | 404 |
| `ERR_PRINT_FILM_NOT_FOUND` | 404 |
| `ERR_PRODUCT_SKU_NOT_FOUND` | 404 |
| `ERR_PRESS_LINE_NOT_FOUND` | 404 |
| `ERR_TEST_PANEL_NOT_FOUND` | 404 |
| `ERR_PRODUCTION_RUN_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_FORMULATION_STATE` | 409 |
| `ERR_INVALID_LICENSE_STATE` | 409 |
| `ERR_INVALID_SKU_CERTIFICATION_STATE` | 409 |
| `ERR_INVALID_COMMERCIAL_STATE` | 409 |
| `ERR_INVALID_PANEL_STATE` | 409 |
| `ERR_INVALID_RUN_STATE` | 409 |
| `ERR_INVALID_QC_TRANSITION` | 409 |
| `ERR_INVALID_BATCH_STATE` | 409 |
| `ERR_INVALID_PRINT_FILM_STATE` | 409 |
| `ERR_INVALID_ALLOCATION_STATE` | 409 |
| `ERR_INVALID_CLAIM_STATE` | 409 |
| `ERR_STALE_FORMULATION_VERSION` | 412 |
| `ERR_STALE_ALLOCATION_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SKU_NOT_PRODUCIBLE` | 409 |
| `ERR_PRESS_LINE_UNAVAILABLE` | 409 |
| `ERR_RUN_NOT_RELEASED` | 409 |
| `ERR_SLIP_RESISTANCE_NOT_QUALIFIED` | 422 |
| `ERR_QC_GATES_NOT_MET` | 422 |
| `ERR_TEST_COVERAGE_INCOMPLETE` | 422 |
| `ERR_PERFORMANCE_SCORE_BELOW_MINIMUM` | 422 |
| `ERR_INDENTATION_CLASS_TOO_LOW` | 422 |
| `ERR_RESIN_PHR_NOT_NORMALIZED` | 422 |
| `ERR_PHR_EXCEEDS_MATERIAL_MAX` | 422 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_THICKNESS_OUT_OF_LINE_RANGE` | 422 |
| `ERR_TOLERANCE_BAND_INVALID` | 422 |
| `ERR_RETEST_LIMIT_EXCEEDED` | 422 |
| `ERR_ALLOCATION_OVER_REQUEST` | 422 |
| `ERR_PRESS_LINE_WINDOW_CONFLICT` | 409 |
| `ERR_CHANGEOVER_GAP_INSUFFICIENT` | 409 |
| `ERR_PRINT_FILM_ROLL_CAPACITY_EXCEEDED` | 409 |
| `ERR_LICENSE_EXPIRED` | 409 |
| `ERR_SETUP_TOO_EARLY` | 409 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_FORMULATION_NOT_APPROVED` | 409 |
| `ERR_RAW_MATERIAL_NOT_ACTIVE` | 409 |
| `ERR_PRINT_FILM_NOT_AVAILABLE` | 409 |
| `ERR_LICENSE_NOT_ACTIVE` | 409 |
| `ERR_BATCH_NOT_TRACEABLE` | 409 |
| `ERR_NO_ELIGIBLE_BATCH` | 409 |
| `ERR_REVIEW_OUTCOME_CONFLICT` | 409 |
| `ERR_LICENSE_VOLUME_CAP_EXCEEDED` | 422 |
