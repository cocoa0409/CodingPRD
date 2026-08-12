# Craft Cidery API — Product Requirements Document

## 1. Introduction

A Northeast craft cidery runs on two calendars at once: the orchard's and the regulator's. Fruit arrives in irregular harvest lots against seasonal grower contracts, must be pressed inside a tightly scheduled press line, fermented under a chosen yeast program, aged, and back-blended for house consistency before it is ever packaged into cans, bottles, or kegs. Every one of those steps is shadowed by federal TTB and state liquor-authority obligations — one label approval per market, license volume caps, interstate shipping permits, and monthly excise reports that must reconcile to the liter.

This document specifies the Craft Cidery API, the system of record for that entire chain: apple varietal reference data and juice pressing schedules, fermentation tank allocation and yeast programs, licensing and excise reporting, packaging runs and label approval gating, and the split between tasting-room sales, club subscriptions, and wholesale distribution. The API is built around a strict segregation of duties — orchard, cellar, compliance, packaging, and sales staff each own a disjoint slice of the workflow — and around a deterministic logical clock so that time-dependent rules (aging minimums, approval expiries, return windows, reporting periods) behave identically in production and in test-driving. All endpoints are mounted under the `/cidery` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly six roles: `OrchardManager` (owns orchard contracts and harvest lot intake), `CellarLead` (owns pressing, fermentation, tank, and yeast operations), `ComplianceOfficer` (owns licensing, label approvals, products, and excise reports), `PackagingOperator` (owns packaging runs), `SalesRep` (owns sales orders), and `PlatformAdmin` (test-driving and audit access). A request with a missing or malformed `X-User-Role` or `X-User-ID` header is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted for the target endpoint per the matrix in §4 is rejected with `ERR_UNAUTHORIZED`.

For all six roles — `OrchardManager`, `CellarLead`, `ComplianceOfficer`, `PackagingOperator`, `SalesRep`, and `PlatformAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on audit events, or as the creator marker on a `PackagingRun` that the segregation-of-duties check later compares against), but it never compares `X-User-ID` to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource in the system carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. The `version` is a system-managed integer that increments by one on every mutation — state transitions, computed-field recomputations, and cascade-driven updates all count as mutations. This convention applies to `OrchardContract`, `HarvestLot`, `PressBatch`, `Tank`, `FermentationBatch`, `CiderProduct`, `LabelApproval`, `LicensePermit`, `PackagingRun`, `SalesOrder`, and `ExciseReport`.

Four record types are lighter-weight. An `AppleVariety`, a `YeastProgram`, a `BlendLine`, and a `ComplianceEvent` each carry only `id` and `created_at`; both `updated_at` and `version` are absent on these four, and no endpoint mutates them after creation.

### 2.5. The Logical Clock

All time-dependent behavior in the cidery — submission and approval timestamps, the minimum aging duration, license and label expiry, the sales return window, and excise period close — reads from a single server-side logical clock, never from the wall clock. Before any operator intervenes, the logical clock reads exactly 2026-05-01T00:00:00Z. A `PlatformAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `now_iso8601`; the server never falls back to wall-clock time under any circumstance. Whenever this document says "now", it means the logical clock.

### 2.6. Numeric Precision, Units, and Rounding

Measured and computed quantities follow fixed precision contracts so that cellar readings, fiscal totals, and regulator filings reconcile exactly. Weighted blend chemistry (`blend_brix`, `blend_tannin`) is expressed with 2 decimal places, rounded half up. The `press_yield_ratio` is expressed with 3 decimal places, rounded half up. Alcohol by volume (`abv_pct`) is rounded half up to the nearest tenth of a percent. Monetary amounts are integer cents throughout — `price_per_lb_cents`, `unit_price_cents`, `subtotal_cents`, `excise_tax_cents`, `total_cents`, `taxable_cents`, and the settlement penalty — with excise rounded half up to whole cents per order line before any summation, and the shortfall penalty computed in integer cents with a floor applied at each tier boundary. Packaged `units_produced` is an integer obtained by flooring. License volumes, tank capacities, and juice volumes are tracked as integer liters.

### 2.7. Nested Resources and Reference Resolution

Requests that target nested resources are validated left to right along the path. When an endpoint path contains several identifiers — for example a harvest lot addressed beneath its contract via `{contractId}` and `{lotId}`, a blend line beneath a press batch via `{batchId}`, or a label approval beneath a product via `{productId}` — the server confirms each identifier in sequence and rejects the request with `ERR_NOT_FOUND` at the first identifier, such as `{varietyId}`, `{tankId}`, or a bare `{id}`, that does not resolve to an existing resource. The same `ERR_NOT_FOUND` rejection applies to foreign-key references supplied in a request body (for example `variety_id`, `tank_id`, or `product_id`) that do not resolve.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each keyed to the `version` of a parent entity.

Activating an orchard contract requires the request to carry `expected_contract_version`, holding the `version` of the `OrchardContract` the client last observed. If the contract's current `version` does not match — because, for instance, another `OrchardManager` has edited `committed_weight_lbs` since the client read it — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a contract state it has not observed.

Completing a packaging run likewise requires `expected_batch_version`, holding the client-observed `version` of the target `FermentationBatch`. A mismatch with the batch's current `version` — for example because another operator has already drawn volume from the same batch — is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than these two do not accept a version field.

### 2.9. Validation Pipeline and Check Ordering

Every request is evaluated against a fixed validation pipeline, and the order matters because it determines which error a client sees when several problems exist at once. Authentication runs first (headers present and role in the declared set, else `ERR_UNAUTHENTICATED`), then authorization (role permitted for the endpoint, else `ERR_UNAUTHORIZED`), then resolution of path identifiers left to right (else `ERR_NOT_FOUND`), then resolution of foreign keys supplied in the body (again `ERR_NOT_FOUND`), then suitability of the target resource's state for the requested action (else `ERR_INVALID_STATE`). Only after those five gates pass do endpoint-specific business rules run, in the relative orders documented throughout §3 — licensing and labeling gates before readiness and volume checks on packaging, label gates before inventory checks on order confirmation, and so on. The stale-version check of §2.8 runs last on the two endpoints that carry it, after all state and business rules have passed.

### 2.10. The Compliance Audit Trail

Regulated operations leave behind an immutable audit line. A `ComplianceEvent` records `entity_type` (the name of the entity that mutated), `entity_id`, the actor's `actor_role` and `actor_id` taken from the request headers, the `action` performed, a `before_snapshot` and `after_snapshot` of the fields relevant to the change, and `event_at`, the server timestamp of the event. Events are emitted at the specific moments called out in §3 — contract activation and settlement, lot spoilage, yield anomalies, packaging leftovers, product activation, report filing and amendment, and late returns — and are readable only by `ComplianceOfficer` and `PlatformAdmin`. The audit collection is filterable by `entity_type`, `entity_id`, and `action`.

## 3. Business Logic & Workflows

### 3.1. Orchard Contracts and Harvest Intake

The sourcing season begins when an `OrchardManager` registers an **orchard contract** with a grower. Creation captures the `grower_name`, the orchard's two-letter `region_code` (NY, VT, MA, and so on), the `season_year` the contract covers, the total `committed_weight_lbs` the grower has pledged, and the negotiated `price_per_lb_cents`; an optional `shortfall_penalty_cents_per_lb` defaults to 0 when omitted. A new contract starts in `DRAFT` status with its `received_weight_lbs` tally at 0. The contract list supports optional `season_year` and `status` filters.

Activation moves a contract from `DRAFT` to `ACTIVE`. Two preconditions guard it: `committed_weight_lbs` must be greater than zero, and `season_year` must be at least the current calendar year — no back-dated activations. The activation is OCC-guarded per §2.8 via `expected_contract_version`, increments the contract's `version` by one, and emits a `CONTRACT_ACTIVATED` compliance event. A `DRAFT` contract that was opened in error can be voided, moving it to `VOIDED`, but only while no harvest lots are linked to it; `SETTLED` and `VOIDED` are terminal.

Fruit arrives against an `ACTIVE` contract as **harvest lots**. Receiving a lot records the `variety_id` of the apple (resolving to a reference variety created with its `code`, typical `tannin_g_per_l`, `brix_at_harvest`, `acidity_g_per_l`, and an `is_bittersweet` flag that defaults to false), the `received_at` timestamp of physical receipt at the presshouse, the delivered `weight_lbs`, and the measured-at-receipt `measured_brix` and `measured_tannin_g_per_l`, which may differ from the varietal typicals. A new lot starts in `RECEIVED` status, and its weight is added to the parent contract's `received_weight_lbs`. That tally is the cumulative received poundage across the contract's lots — counting lots in `RECEIVED` or `PRESSED` state, with partially pressed lots still counting — and each lot additionally tracks its `pressed_weight_lbs` (starting at 0) and a derived `unpressed_weight_lbs`, which is always the lot's `weight_lbs` minus its `pressed_weight_lbs`. Lots are listable per contract or across contracts, with optional `contract_id`, `variety_id`, and `status` filters on the flat collection.

When fruit degrades before pressing, a `CellarLead` marks the lot spoiled, moving it from `RECEIVED` to `SPOILED`. Spoilage is only permitted while the lot is still fully `RECEIVED` — no blend line may have consumed from it — and while the lot is not referenced by any press batch in `PLANNED` or `PRESSING`. Spoiled fruit does not count toward the grower's commitment: the lot's `weight_lbs` is subtracted from the contract's `received_weight_lbs`, and a `LOT_SPOILED` compliance event is emitted.

Once the season winds down, the `OrchardManager` settles an `ACTIVE` contract. Settlement requires every linked lot to be terminal — each in `PRESSED` or `SPOILED` — and an attempt to settle with open lots is rejected with `ERR_CONTRACT_HAS_OPEN_LOTS`. Settlement computes the **shortfall penalty**. The received figure sums `weight_lbs` across the contract's lots in `PRESSED` or `PARTIALLY_PRESSED` state — `SPOILED` lots are excluded. The shortfall is the amount by which `committed_weight_lbs` exceeds that received figure, floored at zero. The first slice of any shortfall is free: the free allowance is `committed_weight_lbs` times ten percent, rounded down to a whole pound. The next tier spans `committed_weight_lbs` times twenty percent, also rounded down. If the shortfall does not exceed the free allowance, the penalty is zero cents. Otherwise, the excess over the free allowance is charged tier by tier: the portion of the excess that fits inside the twenty-percent tier is charged at `shortfall_penalty_cents_per_lb` per pound, and any remaining pounds beyond that tier are charged at double that rate, with the total expressed in integer cents. A provisional variant of this calculation can be quoted at any time before settlement for preview, using the contract's current `received_weight_lbs`; the final variant is computed at the moment of settlement from the locked received figure, persists to the settlement record, and cannot be moved by any subsequent lot transition. Settling moves the contract to `SETTLED` and emits a `CONTRACT_SETTLED` event that includes the penalty.

### 3.2. Presshouse Scheduling: Press Batches and Blend Lines

Pressing is organized as **press batches**. A `CellarLead` plans a batch by supplying a `scheduled_press_date` (UTC), a `press_window_minutes` reservation of at least 30 and at most 480 minutes of press-line time, and an initial set of `blend_lines`. Each blend line draws `weight_lbs` pounds from a specific `harvest_lot_id`, and carries a `position` that fixes blend ordering — lower positions are milled first, and `position` serves as the tie-break. The fruit check is strict at both points where lines are attached: a line's `weight_lbs` may not exceed its lot's `unpressed_weight_lbs`, and a violation is rejected with `ERR_INSUFFICIENT_FRUIT` whether the line arrives in the initial `blend_lines` of a new batch or is added later to a `PLANNED` batch (adding to a batch in any other state is rejected with `ERR_INVALID_STATE`). A planned batch starts in `PLANNED` status, and its `target_juice_liters` — the projected juice yield, the sum of the blend lines' contributions at the theoretical rate of half a liter of juice per pound of fruit — is computed at creation and recomputed whenever lines are added. Blend lines are listable per batch, or across the cellar with `press_batch_id` and `harvest_lot_id` filters, and a single line is retrievable by its own `id`; press batches themselves filter by `status`.

Starting a batch moves it from `PLANNED` to `PRESSING` and is where the press-window discipline bites. The start requires at least one blend line, requires every referenced lot to be in `RECEIVED` or `PARTIALLY_PRESSED`, and requires the summed blend weight to be greater than zero; violations surface as `ERR_INVALID_STATE`. On top of those, the batch's reserved window — the half-open interval from its `scheduled_press_date` up to but not including that start plus `press_window_minutes` — must not overlap the window of any other batch currently `PRESSING`. Two windows conflict when the other batch's start falls before this window's end and the other batch's own end falls after this window's start; merely adjacent windows, where one ends exactly when the other begins, do not conflict. An overlapping start is rejected with `ERR_PRESS_WINDOW_CONFLICT`. When the start succeeds, consumption is applied lot by lot: each lot's `pressed_weight_lbs` increases by its blend-line `weight_lbs`, a lot consuming for the first time auto-advances from `RECEIVED` to `PARTIALLY_PRESSED`, a lot whose `unpressed_weight_lbs` reaches zero auto-advances to `PRESSED`, and a single line that consumes an entire lot moves it straight from `RECEIVED` to `PRESSED` with `pressed_weight_lbs` equal to `weight_lbs`. The affected contracts' `received_weight_lbs` is recomputed in the process and is unchanged in total — that fruit was already counted at receipt and still counts.

Pressing does not always run to plan. Pausing moves a `PRESSING` batch back to `PLANNED` with a `reason` logged (equipment failure, weather, and the like); every lot's `pressed_weight_lbs` is reversed by its blend-line weight, and lots that had auto-advanced may revert from `PARTIALLY_PRESSED` back to `RECEIVED`. This `PRESSING` → `PLANNED` → `PRESSING` loop permits re-attempts. Cancelling, by contrast, is only possible from `PLANNED`: the batch becomes `CANCELLED`, its blend lines are removed, and the lots are left untouched, still `RECEIVED`.

Completion moves a `PRESSING` batch to `COMPLETE` and requires the measured `actual_juice_liters`, which must be provided and greater than zero. At completion two things lock in. First, blend chemistry: `blend_brix` is the weight-weighted average of the lots' `measured_brix` — each line's `weight_lbs` times its lot's reading, summed across all blend lines and divided by the summed line weights — and `blend_tannin` is the same weighted average over `measured_tannin_g_per_l`; the input set is every blend line on the batch, considering only lots whose status is `PARTIALLY_PRESSED` or `PRESSED` after the start. Second, the `press_yield_ratio`: the `actual_juice_liters` divided by the theoretical yield, which is the total blend weight in pounds times half a liter per pound. A ratio below 0.55 or above 0.85 flags the batch for review — the batch still completes, but a `YIELD_ANOMALY` compliance event is emitted.

### 3.3. Cellar Operations: Tanks, Yeast Programs, and Fermentation

The cellar's physical plant is the **tank** fleet, registered by a `CellarLead` with a `code` (such as T-101), a `capacity_liters` working volume, a `material` of `STAINLESS`, `OAK`, `CONCRETE`, or `PLASTIC`, and a `temperature_controlled` flag — defaulting to false — for tanks with a glycol jacket. A new tank starts `EMPTY`; it may be reserved (`EMPTY` → `RESERVED`) ahead of a pitch and released again (`RESERVED` → `EMPTY`), and tanks may additionally be recorded as `CLEANING` or `MAINTENANCE` when out of rotation. A tank's `current_batch_id` names the fermentation batch occupying it, or null. The tank list filters by `status`.

Fermentation biology is captured in **yeast programs**: a strain `code` (EC-1118, WILDFERM), a `kind` of `CULTURED`, `WILD`, or `MIXED`, the expected `attenuation_pct` (90 means ninety percent), the fermentation temperature envelope `temp_min_f` and `temp_max_f` in Fahrenheit, and `nutrient_required`, defaulting to false, marking programs that demand a YAN nutrient addition.

Pitching yeast creates a **fermentation batch** from a `press_batch_id`, a `tank_id`, and a `yeast_program_id`. The referenced press batch must be `COMPLETE`. Tank eligibility follows a waterfall allocation policy: the tank must be `EMPTY` or `RESERVED`, its `capacity_liters` must be at least the juice volume requested, and it must be `temperature_controlled` whenever the yeast program's envelope dips below 55 °F or climbs above 75 °F. When several tanks qualify, the selector prefers the smallest capacity that still fits (best-fit), then temperature-controlled tanks over uncontrolled ones, then the earliest-created tank on a remaining tie. If no tank satisfies the eligibility rules the pitch is rejected with `ERR_NO_TANK_AVAILABLE`. A successful pitch moves the tank from `RESERVED` to `FERMENTING` — or directly from `EMPTY` to `FERMENTING` when it was never reserved — sets the tank's `current_batch_id`, inherits the batch's `original_gravity_brix` from the press batch's `blend_brix`, sets the initial `volume_liters` to the press batch's `actual_juice_liters`, stamps `started_at` at the pitch, and starts the batch in `PITCHED` status. Fermentation batches are filterable by `status`, `tank_id`, `press_batch_id`, `yeast_program_id`, and `back_blend_source_batch_id`.

Fermentation progress is tracked through gravity readings. Recording a reading supplies a `gravity_brix` that becomes the batch's `current_gravity_brix`, and the first reading below `original_gravity_brix` auto-advances the batch from `PITCHED` to `FERMENTING`. Every reading also recomputes `abv_pct`: the drop from `original_gravity_brix` to `current_gravity_brix`, multiplied by 0.55 and rounded half up to the nearest tenth. During `FERMENTING` this is the provisional variant, tracking whatever the latest reading says; at packaging time a final variant is recomputed from the final gravity reading and may differ from the provisional figure.

A batch moves from `FERMENTING` to `AGING` only once its gravity has fallen to terminal: `current_gravity_brix` at or below `original_gravity_brix` scaled by one minus the yeast program's `attenuation_pct` fraction, plus a half-degree Brix tolerance. The transition also moves the tank from `FERMENTING` to `AGING`. From `AGING`, a batch becomes `READY` only after an aging duration of at least 14 days, measured on the logical clock. `READY` is the hand-off to packaging: once the cumulative packaged volume across packaging runs equals the batch's original volume — that is, once `volume_liters` reaches zero — the batch auto-advances from `READY` to `PACKAGED`, and its tank returns to `EMPTY` with `current_batch_id` cleared.

Two cellar interventions cut across this flow. Back-blending draws `source_volume_liters` from another fermentation batch identified by `source_batch_id` into this one: the source's `volume_liters` decreases by the drawn amount and this batch's increases by it, this batch's `back_blend_source_batch_id` is set to the source, its `back_blend_pct` becomes the contributed volume divided by the batch's post-blend volume expressed as a percent, and `current_gravity_brix` is recomputed as the volume-weighted average of the two lots of liquid, with `abv_pct` recomputed from it. Dumping, which requires a `reason`, moves a batch from `PITCHED`, `FERMENTING`, or `AGING` to `DUMPED`, empties its tank back to `EMPTY` with `current_batch_id` cleared, and drives the batch's `volume_liters` to zero.

### 3.4. Products, Label Approvals, and Licenses

Everything the cidery sells descends from a **cider product**, registered by a `ComplianceOfficer` with a unique `sku` (a duplicate is rejected with `ERR_DUPLICATE_SKU`), a `name` such as "Orchard Reserve 2026", a `style` of `DRY`, `SEMI_DRY`, `SWEET`, `HOPPED`, or `FRUIT_INFUSED`, the labelled `target_abv_pct`, a `vintage_year`, and an optional `abv_tolerance_pct` that defaults to 0.3. A new product is `DRAFT`; the product list filters by `status`.

Activating a product moves it from `DRAFT` to `ACTIVE` and carries two preconditions: at least one label approval for the product must be `APPROVED` in the `FEDERAL_TTB` market, and `target_abv_pct` must sit inside the cider tax class — strictly greater than 0.5 and at most 8.5. Activation emits a `PRODUCT_ACTIVATED` compliance event. Retiring moves an `ACTIVE` product to `RETIRED` and is blocked while any packaging run for the product is `SCHEDULED` or any sales order for it sits in `DRAFT` or `CONFIRMED`. A retired product can be re-issued — `RETIRED` back to `ACTIVE` — provided its label approval is still `APPROVED` and unexpired.

**Label approvals** are per-product, per-market filings. The market is one of `FEDERAL_TTB`, `NY_SLA`, `VT_DLL`, or `MA_ABCC`, and exactly one approval may exist per product and market — a duplicate is rejected with `ERR_DUPLICATE_LABEL_MARKET`. Filing captures the `market`, the regulator's `application_number` (the COLA number for federal filings), and an `expires_at`; the record stamps `submitted_at` at filing and starts `SUBMITTED`. Approval requires a non-empty `application_number` and stamps `approved_at`; rejection moves the filing to `REJECTED`, and resubmission returns a `REJECTED` filing to `SUBMITTED` with an updated `application_number` and a fresh `submitted_at`. Approvals age out automatically: when the logical clock passes `expires_at` on any market other than `FEDERAL_TTB` — federal COLAs do not auto-expire — the approval moves from `APPROVED` to `EXPIRED`, and any `SCHEDULED` packaging runs still referencing it are cancelled. Label approvals are listable per product or across products, with `product_id`, `market`, and `status` filters.

**Licenses and permits** authorize production and sale. A license carries a `kind` of `TTB_BREWERS_NOTICE`, `NY_FARM_CIDERY`, `VT_MANUFACTURER`, `MA_FARMER_WINERY`, or `INTERSTATE_SHIPPER`, an issued `license_number`, `issued_at` and `expires_at` timestamps, a `scope_states` array of two-letter state codes the license authorizes, and an `annual_volume_cap_liters` — zero meaning uncapped. The license starts `ACTIVE` with `volume_used_liters` at 0, and that tally accumulates the packaged volume attributed to the license during the calendar year. A `ComplianceOfficer` may suspend an `ACTIVE` or `REINSTATED` license, moving it to `SUSPENDED` and blocking any new packaging run or interstate sales order that references it; reinstatement moves `SUSPENDED` to `REINSTATED`, and the license returns from `REINSTATED` to `ACTIVE` automatically at the next ops run. When the logical clock passes `expires_at`, an `ACTIVE` license becomes `EXPIRED`, blocking all operations that reference it. The license list filters by `status` and `kind`.

These two families of records gate the downstream workflows at well-defined points. Scheduling a packaging run and creating an interstate sales order both require the referenced license to be `ACTIVE` — a `SUSPENDED` or `EXPIRED` license is rejected with `ERR_LICENSE_NOT_ACTIVE` — and require the permit's expiry to lie in the future relative to the action, else `ERR_PERMIT_EXPIRED`. Scheduling a packaging run and confirming a sales order both require the applicable label approval to be `APPROVED`, else `ERR_LABEL_NOT_APPROVED`, and — for any market other than `FEDERAL_TTB` — require the approval to be unexpired, else `ERR_LABEL_EXPIRED`.

### 3.5. Packaging Runs

A **packaging run** draws finished cider from a `READY` fermentation batch into saleable containers. A `PackagingOperator` schedules a run by supplying the `product_id`, the `fermentation_batch_id`, a `package_format` of `CAN_12OZ`, `CAN_16OZ`, `BOTTLE_500ML`, `BOTTLE_750ML`, `KEG_5GAL`, or `KEG_15_5GAL`, the `volume_liters` to draw, the `label_approval_id` authorizing the target market, and the `license_id` authorizing the packaging. Container sizes are fixed: 0.355 liters for a 12-ounce can, 0.473 for a 16-ounce can, 0.500 and 0.750 liters for the two bottle formats, and 18.927 and 58.674 liters for the 5- and 15.5-gallon kegs. At scheduling, `units_produced` is computed as the run's `volume_liters` divided by the container size, floored to whole containers, and any leftover — the volume remaining after those whole containers are filled — that exceeds 0.1 liters triggers a `PACKAGING_LEFTOVER` compliance event while the run still proceeds. The scheduling operator's `X-User-ID` is recorded on the run for the segregation-of-duties check, and the run starts `SCHEDULED`. The run list filters by `status`, `product_id`, `fermentation_batch_id`, `label_approval_id`, and `license_id`.

Scheduling evaluates its gates in a fixed order. Reference resolution comes first: any supplied identifier that does not resolve yields `ERR_NOT_FOUND`. Then the licensing and labeling gates of §3.4 run in sequence — license status (`ERR_LICENSE_NOT_ACTIVE`), label approval (`ERR_LABEL_NOT_APPROVED`), label expiry for non-federal markets (`ERR_LABEL_EXPIRED`), and permit expiry (`ERR_PERMIT_EXPIRED`). Only then do the batch checks run: the referenced fermentation batch must be `READY` (else `ERR_BATCH_NOT_READY`), and its `volume_liters` must cover the run's draw (else `ERR_INSUFFICIENT_VOLUME`). Last comes the annual volume cap: a license with `annual_volume_cap_liters` of zero is uncapped and always passes; otherwise the projected total — the license's current `volume_used_liters` plus this run's `volume_liters` — is compared against the cap, and only a projection strictly greater than the cap is rejected with `ERR_LICENSE_CAP_EXCEEDED`, so landing exactly on the cap is allowed.

Completing a run moves it from `SCHEDULED` to `COMPLETED` and is the most heavily guarded write in the system. The run must still be `SCHEDULED` (else `ERR_INVALID_STATE`). Segregation of duties is then enforced: the operator completing the run must not be the same `X-User-ID` that scheduled it, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Next, ABV consistency is checked against the final gravity: the absolute difference between the batch's `abv_pct` — recomputed from the final gravity reading at packaging time — and the product's `target_abv_pct` must not exceed the product's `abv_tolerance_pct`; a strictly greater deviation is rejected with `ERR_ABV_OUT_OF_TOLERANCE`, while a deviation exactly equal to the tolerance passes. Finally, the OCC guard of §2.8 applies: the request carries `expected_batch_version`, and a mismatch with the batch's current `version` is rejected with `ERR_STALE_VERSION`.

A successful completion stamps `packaged_at`, draws the run's `volume_liters` out of the batch's `volume_liters`, adds the same volume to the license's `volume_used_liters`, and increments the batch's `version` by one. When the draw empties the batch — `volume_liters` reaching zero — the batch auto-advances from `READY` to `PACKAGED` and its tank returns to `EMPTY` with `current_batch_id` cleared. A `SCHEDULED` run may instead be cancelled outright, and recall from §3.4 that a label approval expiring under a non-federal market also cancels any `SCHEDULED` runs that reference it.

### 3.6. Sales Orders and Channel Fulfillment

Sales flow through **orders** created by a `SalesRep`. Creation captures the `channel` — `TASTING_ROOM`, `CLUB_SUBSCRIPTION`, or `WHOLESALE_DISTRIBUTION` — the buyer's two-letter `destination_state`, the `product_id`, the `packaging_run_id` supplying inventory, the number of `units` (which must be greater than zero), and the `unit_price_cents`; the order's `subtotal_cents` is the `units` multiplied by the `unit_price_cents`, and the order starts in `DRAFT`. For the two interstate channels, `CLUB_SUBSCRIPTION` and `WHOLESALE_DISTRIBUTION`, creation already enforces the licensing gates: an `ACTIVE` license whose `scope_states` includes the `destination_state` must exist — violations surface as `ERR_LICENSE_NOT_ACTIVE` — and the permit must be unexpired, else `ERR_PERMIT_EXPIRED`. The order list filters by `status`, `channel`, `destination_state`, `product_id`, and `packaging_run_id`.

Confirmation moves an order from `DRAFT` to `CONFIRMED` and evaluates its checks in order. The referenced packaging run must be `COMPLETED`, and the order itself must still be `DRAFT` — state failures yield `ERR_INVALID_STATE`. The label gates of §3.4 then apply to the product and the destination state's regulator market (`NY_SLA` for New York, `VT_DLL` for Vermont, `MA_ABCC` for Massachusetts): the approval must be `APPROVED`, else `ERR_LABEL_NOT_APPROVED`, and unexpired for non-federal markets, else `ERR_LABEL_EXPIRED`. For club and wholesale orders, an `ACTIVE` license scoped to the `destination_state` is again required. Inventory is checked last: the run's `units_produced` minus the units already committed by prior `SHIPPED` or `DELIVERED` orders against the same run must be at least this order's `units`, else `ERR_INSUFFICIENT_INVENTORY`.

Confirmation is also where excise attaches. The federal hard-cider rate is 22.6 cents per liter, applying to cider at or below 8.5 percent ABV — anything stronger is reclassified as apple wine and is out of scope, since products cannot activate above that ceiling. The order's volume in liters is its `units` times the container size of the run's `package_format`; the `excise_tax_cents` is that liter figure times 22.6, rounded half up to whole cents on the line, and because each order carries a single line, per-line rounding then summation are the same thing here — but at report time the rule stands: round each order's excise first, then sum, never sum liters and round once. The order's `total_cents` is the `subtotal_cents` plus the `excise_tax_cents`. Two channel variants color the calculation. Tasting-room orders carry the same federal rate, and a New York tasting-room sale may additionally owe a state on-premise tax, modeled as a flat four percent of the subtotal. Interstate orders — club or wholesale shipments crossing state lines — owe the federal rate, with destination-state excise treated as reciprocal under the `INTERSTATE_SHIPPER` permit.

From `CONFIRMED`, shipping moves the order to `SHIPPED` and stamps `shipped_at` on the logical clock; from that moment the order contributes to the current period's excise aggregates in chronological order. Delivery moves `SHIPPED` to `DELIVERED`. A `SHIPPED` order may be returned within 30 days of `shipped_at` — a later attempt is rejected with `ERR_RETURN_WINDOW_EXPIRED` — and a return moves the order to `RETURNED` with a fiscal echo: if the excise report covering the shipped period is still `OPEN`, the order's excise is subtracted from the report's `taxable_cents`, but if that report is already `FILED`, a `LATE_RETURN` compliance event is emitted instead to drive an amendment. An order in `DRAFT` or `CONFIRMED` may be cancelled, moving it to `CANCELLED`.

### 3.7. Excise Reporting, Filing, and Amendment

Excise liability is settled monthly per regulator through **excise reports**. A `ComplianceOfficer` opens a report with a `period_year`, a `period_month` from 1 to 12, and a `regulator` of `TTB`, `NY_SLA`, `VT_DLL`, or `MA_ABCC`; the report starts `OPEN` with `taxable_liters` and `taxable_cents` both at 0. Only one `OPEN` report may exist for a given year, month, and regulator — a duplicate is rejected with `ERR_DUPLICATE_REPORT`. The report list filters by `status` and `regulator`.

Aggregation is a chronological replay. While a report is `OPEN`, every order that ships accumulates into it, and the canonical figures replay all orders whose `shipped_at` falls inside the half-open period — from the period's start up to but not including its end — and whose status is `SHIPPED`, `DELIVERED`, or `RETURNED`. Replay order is `shipped_at` ascending, with ties broken by the order's `created_at` ascending, never by `id`. The `taxable_cents` sums each replayed order's `excise_tax_cents` — each already rounded to whole cents at confirmation — subtracting rather than adding for `RETURNED` orders; the `taxable_liters` likewise sums each order's `units` times its container size, subtracting for returns.

Filing moves an `OPEN` report to `FILED` and is only permitted once the period has closed — the logical clock must have reached the end of `period_month`, else the filing is rejected with `ERR_PERIOD_NOT_CLOSED`. Filing recomputes the aggregation one final time, stamps `filed_at`, and emits a `REPORT_FILED` compliance event. Corrections after filing take the form of an amendment, moving `FILED` to `AMENDED`: the request logs a `reason` and attaches the recomputed figures as `amended_taxable_cents` and `amended_taxable_liters`, and a `REPORT_AMENDED` event is emitted with the delta. Late-arriving returns against already-filed periods surface through the `LATE_RETURN` events of §3.6 and are worked off through this amendment path.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, readings, clock changes — and all reads return `200 OK`. Create and modify operations return the created or updated resource in the envelope's `data` field.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cidery/_clock/set_current_utc` | Set the logical clock (test-driving) | PlatformAdmin |
| POST | `/cidery/varieties` | Create an apple variety reference record | OrchardManager |
| GET | `/cidery/varieties/{varietyId}` | Get a variety | OrchardManager, CellarLead, ComplianceOfficer, SalesRep, PackagingOperator, PlatformAdmin |
| GET | `/cidery/varieties` | List varieties | OrchardManager, CellarLead, ComplianceOfficer, SalesRep, PackagingOperator, PlatformAdmin |
| POST | `/cidery/yeast-programs` | Create a yeast program reference | CellarLead |
| GET | `/cidery/yeast-programs/{id}` | Get a yeast program | CellarLead, ComplianceOfficer, PackagingOperator, PlatformAdmin |
| GET | `/cidery/yeast-programs` | List yeast programs | CellarLead, ComplianceOfficer, PackagingOperator, PlatformAdmin |
| POST | `/cidery/contracts` | Create an orchard contract | OrchardManager |
| GET | `/cidery/contracts/{contractId}` | Get a contract | OrchardManager, ComplianceOfficer, PlatformAdmin |
| GET | `/cidery/contracts` | List contracts | OrchardManager, ComplianceOfficer, PlatformAdmin |
| POST | `/cidery/contracts/{contractId}/activate` | Activate a contract (DRAFT → ACTIVE); OCC-guarded | OrchardManager |
| POST | `/cidery/contracts/{contractId}/settle` | Settle a contract and compute the shortfall penalty | OrchardManager |
| POST | `/cidery/contracts/{contractId}/void` | Void a DRAFT contract | OrchardManager |
| POST | `/cidery/contracts/{contractId}/harvest-lots` | Receive a harvest lot against an ACTIVE contract | OrchardManager |
| GET | `/cidery/harvest-lots/{lotId}` | Get a harvest lot | OrchardManager, CellarLead, ComplianceOfficer, PlatformAdmin |
| GET | `/cidery/contracts/{contractId}/harvest-lots` | List lots for a contract | OrchardManager, CellarLead, ComplianceOfficer, PlatformAdmin |
| GET | `/cidery/harvest-lots` | Filtered list of harvest lots | OrchardManager, CellarLead, ComplianceOfficer, PlatformAdmin |
| POST | `/cidery/harvest-lots/{lotId}/spoil` | Mark a lot spoiled | CellarLead |
| POST | `/cidery/press-batches` | Create a press batch with initial blend lines | CellarLead |
| GET | `/cidery/press-batches/{batchId}` | Get a press batch | CellarLead, ComplianceOfficer, PackagingOperator, PlatformAdmin |
| GET | `/cidery/press-batches` | List press batches | CellarLead, ComplianceOfficer, PackagingOperator, PlatformAdmin |
| GET | `/cidery/press-batches/{batchId}/blend-lines` | List blend lines for a press batch | CellarLead, ComplianceOfficer, PlatformAdmin |
| POST | `/cidery/press-batches/{batchId}/blend-lines` | Add a blend line to a PLANNED press batch | CellarLead |
| GET | `/cidery/blend-lines` | Filtered list of blend lines | CellarLead, ComplianceOfficer, PlatformAdmin |
| GET | `/cidery/blend-lines/{id}` | Get a single blend line | CellarLead, ComplianceOfficer, PlatformAdmin |
| POST | `/cidery/press-batches/{batchId}/start` | Start pressing (PLANNED → PRESSING) | CellarLead |
| POST | `/cidery/press-batches/{batchId}/pause` | Pause pressing (PRESSING → PLANNED), reversing lot consumption | CellarLead |
| POST | `/cidery/press-batches/{batchId}/complete` | Complete pressing (PRESSING → COMPLETE) | CellarLead |
| POST | `/cidery/press-batches/{batchId}/cancel` | Cancel a PLANNED press batch | CellarLead |
| POST | `/cidery/tanks` | Create a tank | CellarLead |
| GET | `/cidery/tanks/{tankId}` | Get a tank | CellarLead, PackagingOperator, ComplianceOfficer, PlatformAdmin |
| GET | `/cidery/tanks` | List tanks | CellarLead, PackagingOperator, ComplianceOfficer, PlatformAdmin |
| POST | `/cidery/tanks/{tankId}/reserve` | Reserve an EMPTY tank | CellarLead |
| POST | `/cidery/tanks/{tankId}/release` | Release a RESERVED tank | CellarLead |
| POST | `/cidery/fermentation-batches` | Pitch yeast into a tank with juice from a COMPLETE press batch | CellarLead |
| GET | `/cidery/fermentation-batches/{batchId}` | Get a fermentation batch | CellarLead, PackagingOperator, ComplianceOfficer, PlatformAdmin |
| GET | `/cidery/fermentation-batches` | List fermentation batches | CellarLead, PackagingOperator, ComplianceOfficer, PlatformAdmin |
| POST | `/cidery/fermentation-batches/{batchId}/readings` | Record a gravity reading | CellarLead |
| POST | `/cidery/fermentation-batches/{batchId}/age` | Move a batch to AGING | CellarLead |
| POST | `/cidery/fermentation-batches/{batchId}/ready` | Mark a batch READY after aging | CellarLead |
| POST | `/cidery/fermentation-batches/{batchId}/dump` | Dump a batch (PITCHED / FERMENTING / AGING → DUMPED) | CellarLead |
| POST | `/cidery/fermentation-batches/{batchId}/back-blend` | Back-blend another batch's volume into this one | CellarLead |
| POST | `/cidery/products` | Create a cider product SKU | ComplianceOfficer |
| GET | `/cidery/products/{productId}` | Get a product | ComplianceOfficer, SalesRep, PackagingOperator, PlatformAdmin |
| GET | `/cidery/products` | List products | ComplianceOfficer, SalesRep, PackagingOperator, PlatformAdmin |
| POST | `/cidery/products/{productId}/activate` | Activate a product (DRAFT or RETIRED → ACTIVE) | ComplianceOfficer |
| POST | `/cidery/products/{productId}/retire` | Retire a product (ACTIVE → RETIRED) | ComplianceOfficer |
| POST | `/cidery/products/{productId}/label-approvals` | Submit a label approval application for a market | ComplianceOfficer |
| GET | `/cidery/label-approvals/{id}` | Get a label approval | ComplianceOfficer, PackagingOperator, PlatformAdmin |
| GET | `/cidery/products/{productId}/label-approvals` | List label approvals for a product | ComplianceOfficer, PackagingOperator, SalesRep, PlatformAdmin |
| GET | `/cidery/label-approvals` | Filtered list of label approvals | ComplianceOfficer, PackagingOperator, SalesRep, PlatformAdmin |
| POST | `/cidery/label-approvals/{id}/approve` | Approve a label application | ComplianceOfficer |
| POST | `/cidery/label-approvals/{id}/reject` | Reject a label application | ComplianceOfficer |
| POST | `/cidery/label-approvals/{id}/resubmit` | Resubmit a REJECTED application | ComplianceOfficer |
| POST | `/cidery/licenses` | Create a license or permit | ComplianceOfficer |
| GET | `/cidery/licenses/{id}` | Get a license | ComplianceOfficer, PackagingOperator, SalesRep, PlatformAdmin |
| GET | `/cidery/licenses` | List licenses | ComplianceOfficer, PackagingOperator, SalesRep, PlatformAdmin |
| POST | `/cidery/licenses/{id}/suspend` | Suspend a license | ComplianceOfficer |
| POST | `/cidery/licenses/{id}/reinstate` | Reinstate a suspended license | ComplianceOfficer |
| POST | `/cidery/packaging-runs` | Schedule a packaging run | PackagingOperator |
| GET | `/cidery/packaging-runs/{id}` | Get a packaging run | PackagingOperator, ComplianceOfficer, SalesRep, PlatformAdmin |
| GET | `/cidery/packaging-runs` | List packaging runs | PackagingOperator, ComplianceOfficer, SalesRep, PlatformAdmin |
| POST | `/cidery/packaging-runs/{id}/complete` | Complete a packaging run (SCHEDULED → COMPLETED); OCC-guarded on the batch | PackagingOperator |
| POST | `/cidery/packaging-runs/{id}/cancel` | Cancel a SCHEDULED packaging run | PackagingOperator |
| POST | `/cidery/orders` | Create a sales order | SalesRep |
| GET | `/cidery/orders/{id}` | Get an order | SalesRep, ComplianceOfficer, PlatformAdmin |
| GET | `/cidery/orders` | List orders | SalesRep, ComplianceOfficer, PlatformAdmin |
| POST | `/cidery/orders/{id}/confirm` | Confirm an order (DRAFT → CONFIRMED), computing excise | SalesRep |
| POST | `/cidery/orders/{id}/ship` | Ship an order (CONFIRMED → SHIPPED) | SalesRep |
| POST | `/cidery/orders/{id}/deliver` | Mark an order delivered (SHIPPED → DELIVERED) | SalesRep |
| POST | `/cidery/orders/{id}/return` | Return a shipped order within 30 days | SalesRep |
| POST | `/cidery/orders/{id}/cancel` | Cancel a DRAFT or CONFIRMED order | SalesRep |
| POST | `/cidery/excise-reports` | Open an excise report for a year, month, and regulator | ComplianceOfficer |
| GET | `/cidery/excise-reports/{id}` | Get an excise report | ComplianceOfficer, PlatformAdmin |
| GET | `/cidery/excise-reports` | List excise reports | ComplianceOfficer, PlatformAdmin |
| POST | `/cidery/excise-reports/{id}/file` | File an OPEN report once its period has closed | ComplianceOfficer |
| POST | `/cidery/excise-reports/{id}/amend` | Amend a FILED report | ComplianceOfficer |
| GET | `/cidery/compliance-events` | List compliance audit events (filterable) | ComplianceOfficer, PlatformAdmin |
| GET | `/cidery/compliance-events/{id}` | Get a single compliance event | ComplianceOfficer, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_LICENSE_NOT_ACTIVE` | 409 |
| `ERR_LABEL_NOT_APPROVED` | 409 |
| `ERR_LABEL_EXPIRED` | 409 |
| `ERR_PERMIT_EXPIRED` | 409 |
| `ERR_PRESS_WINDOW_CONFLICT` | 409 |
| `ERR_RETURN_WINDOW_EXPIRED` | 409 |
| `ERR_NO_TANK_AVAILABLE` | 409 |
| `ERR_ABV_OUT_OF_TOLERANCE` | 409 |
| `ERR_INSUFFICIENT_FRUIT` | 409 |
| `ERR_BATCH_NOT_READY` | 409 |
| `ERR_INSUFFICIENT_VOLUME` | 409 |
| `ERR_LICENSE_CAP_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_CONTRACT_HAS_OPEN_LOTS` | 409 |
| `ERR_PERIOD_NOT_CLOSED` | 409 |
| `ERR_DUPLICATE_REPORT` | 409 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_DUPLICATE_LABEL_MARKET` | 409 |
