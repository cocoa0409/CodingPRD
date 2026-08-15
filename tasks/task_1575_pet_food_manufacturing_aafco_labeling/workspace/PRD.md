# Pet Food Manufacturing & AAFCO Labeling API — Product Requirements Document

## 1. Introduction

Every package of pet food sold in the United States carries a nutritional adequacy statement, and that statement must be substantiated — either by formulating the product to meet an AAFCO nutrient profile or by passing a formal AAFCO feeding trial. For a co-manufacturer producing private-label product on behalf of many brand owners, substantiation is only the beginning of the compliance burden. Every ingredient must trace to a qualified supplier facility, every production run must carry a traceable lot code, every batch's laboratory results must hold up against the guaranteed analysis printed on the label, every state where the product is sold demands registration and label review, and every consumer complaint must be triaged along a defensible path that can culminate in a recall.

This document specifies the Pet Food Manufacturing & AAFCO Labeling API, the system of record for that end-to-end operation, with all resources mounted under `/petfood`. The API covers the registry of brand owners, supplier facilities, and ingredient masters; the qualification of supplier–ingredient pairings under segregation of duties; formula development with its two substantiation pathways (formulation versus feeding trial); lot-coded batch production with guaranteed-analysis verification; state registration with tiered fee assessment and annual expiry; and complaint intake with risk scoring that can escalate automatically into a recall cascade.

Two design commitments shape every workflow that follows. The first is auditability: every resource is versioned, every approval decision records the actor who made it, and every computed verdict — nutrient adequacy, label compliance, complaint risk — is produced by a deterministic calculation with pinned rounding behavior, so an auditor replaying the same inputs always reaches the same numbers. The second is containment: when something goes wrong — a revoked supplier pairing, a misbranded batch, an initiated recall — the platform cascades state changes outward so that dependent formulas, batches, lots, and registrations cannot silently drift out of alignment with reality.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. Nine roles are recognized: `PlatformAdmin`, `FormulationScientist`, `QAApprover`, `QualityAnalyst`, `TrialCoordinator`, `ProductionPlanner`, `LineOperator`, `RegulatoryAffairs`, and `StateRegulator`. A request that is missing either header, presents malformed headers, or names a role outside this declared set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The nine roles divide the work along strict segregation-of-duties lines. A `PlatformAdmin` is the co-manufacturer's platform operator: it bootstraps master data (registering brand owners and supplier facilities) and is the only role permitted to advance the logical clock. A `FormulationScientist` is the R&D owner of ingredient masters, formulas, and nutrient profiles. A `QAApprover` is the quality organization's decision maker — supplier approvals and suspensions, pairing decisions, formula revision requests, substantiation, locks and withdrawals, trial verdicts and aborts, complaint escalations, and every recall action; on segregation-of-duties-guarded operations the approver must differ from the user who submitted the request. A `QualityAnalyst` requests supplier–ingredient pairings, places and lifts batch holds, rejects held batches, records lab samples, generates guaranteed-analysis reports, and owns complaint intake, triage, investigation, and resolution. A `TrialCoordinator` runs feeding-trial protocols from creation through enrollment, trial start, and observation completion. A `ProductionPlanner` creates production batches and releases them to the floor. A `LineOperator` starts and completes runs and cuts lot codes. A `RegulatoryAffairs` specialist acts on behalf of a brand owner, submitting and resubmitting state registrations. A `StateRegulator` is the state feed-control official who accepts registrations for review and issues approval or rejection decisions.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `PlatformAdmin`, `FormulationScientist`, `QAApprover`, `QualityAnalyst`, `TrialCoordinator`, `ProductionPlanner`, `LineOperator`, or `StateRegulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `decided_by` on a supplier–ingredient pairing when a decision is written, where it later anchors segregation-of-duties comparisons — but it never compares the value to any entity's `id`. When `X-User-Role` is `RegulatoryAffairs`, `X-User-ID` is the `id` of the acting `BrandOwner`; ownership checks on any resource that references a `BrandOwner` compare the resource's foreign-key field, such as `brand_owner_id`, to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0; a negative offset is invalid. A `limit` outside the range of 1 to 100, or an `offset` below 0, is rejected with `ERR_PAGINATION` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

Several list endpoints additionally accept an optional `status` query parameter that filters results to a single exact lifecycle value, and the listing of supplier–ingredient pairings for a supplier accepts an optional `approval_state` filter with the same exact-match semantics.

### 2.4. Common Resource Properties

All fifteen resources in this API — brand owners, suppliers, ingredients, supplier–ingredient approvals, formulas, formula ingredient lines, nutrient profiles, feeding-trial protocols, production batches, batch lot codes, lab samples, guaranteed-analysis reports, state registrations, complaint cases, and recall actions — share one set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that starts at 1 and increments by exactly one on every mutation of the resource — including explicit state transitions, automatic cascades originating elsewhere, and recomputation of derived fields. Every state transition described in §3 therefore advances the transitioned resource's `version` by one, even where the narrative does not repeat that fact.

### 2.5. The Logical Clock and Time-Driven Transitions

All time-dependent behavior in the platform is governed by a server-side logical clock, never by wall-clock time. Before the clock has been explicitly set, it reads exactly 2026-08-01T00:00:00Z, and once set it never falls back to wall time. A `PlatformAdmin` advances the clock through the clock-setting capability at `POST /petfood/_clock/set_current_utc`, supplying the target instant in the `to_iso8601` field; the response echoes the resulting time as `current_utc`. Two kinds of behavior key off this clock: advancing it past a registration's annual, state-specific expiry date drives that registration from `APPROVED` to `EXPIRED` as an automatic system transition, and every windowed calculation in the complaint risk model — the trailing 90-day rollup window and the 30-day post-closure decay — evaluates its window against the logical clock's current reading.

### 2.6. Numeric Precision, Units, and Rounding

Numeric conventions are uniform unless a specific calculation states otherwise. All final persisted values are rounded using the round-half-up method. Nutrient percentages (guaranteed-analysis values, lab measurements, ingredient nutrient contributions) are expressed as as-fed percentages. Masses are expressed in kilograms. Registration fees are computed and stored as integer cents, with multiplication results rounded half up to whole cents. Metabolizable energy is stored at 1 decimal place. AAFCO compliance comparisons are made at 2 decimal places, with values rounded half up before comparison. Guaranteed-analysis composite contributions are rounded to 3 decimal places and the composites themselves to 2 decimal places. The deviation index, yield variance percentages, and complaint risk scores are kept at 2 decimal places. A feeding trial's `completion_ratio` is kept at 4 decimal places. Lot-code sequence numbers are integers zero-padded to three digits.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to declare the formula revision it last observed, protecting formula-dependent decisions against stale views. Creating a production batch against a formula requires a non-optional `expected_formula_version` field in the request body, carrying the formula `version` the client last read. Approving a state registration likewise requires a non-optional `expected_formula_version`. In both cases, if the supplied value does not match the formula's current `version` — because another writer has substantiated, locked, revised, withdrawn, or otherwise advanced the formula since the client last read it — the request is rejected with `ERR_STALE_FORMULA_VERSION` (HTTP 412). For batch creation this captures the case where the planner's view of the formula predates a substantiation or lock change; for registration approval it prevents a label approval issued against one formula revision from pinning the wrong substantiation baseline after the revision moved. No endpoint other than these two accepts a version field.

### 2.8. Hierarchical Consistency and Cascading State Changes

Formulas sit at the center of a dependency web — ingredient lines, nutrient profiles, trial protocols, batches, registrations, complaints, and recalls all hang off them — and the platform maintains consistency across that web automatically. When a parent resource's state change invalidates its dependents, the server cascades without requiring a client request on each dependent: superseding a `LOCKED` formula revokes its in-flight registrations and rejects its unreleased batches; withdrawing a locked formula revokes its approved registrations; revoking a supplier pairing pushes uncovered formulas under review back to draft; rejecting a held batch quarantines its active lots; initiating a recall moves in-scope batches and lots to `RECALLED`; terminating a recall compensates by returning those lots to `QUARANTINED` and those batches to `ON_HOLD`. Every resource touched by a cascade is itself mutated, refreshing `updated_at` and incrementing `version`.

Consistency also flows upward, from children into parents. Completing a batch increments the parent formula's `total_batch_count`. Approving or revoking a pairing recomputes the supplier's `approved_ingredient_count`. Recall activity maintains the formula's `open_recall_flag` and the brand owner's `open_recall_count`. Complaint activity maintains the brand owner's `complaint_score`. These rollups are part of the mutation that triggered them, never deferred.

### 2.9. Nested Resource Retrieval

Requests that target nested resources are validated strictly left to right along the path. Each identifier in the URL must resolve to an existing row before the next is examined, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve — a request addressing a batch under a non-existent formula fails on the formula identifier before the batch is ever looked up. The same rule governs foreign-key-valued fields in request bodies: any `brand_owner_id`, `formula_id`, `batch_id`, `supplier_id`, or `ingredient_id` that does not resolve to an existing row produces `ERR_NOT_FOUND`. Creation and modification of a child resource always validate the parent's existence first, so operations proceed only inside valid containers.

### 2.10. Validation Order and Error Precedence

Incoming requests are validated against a fixed, prioritized sequence, and a failure at any step halts further evaluation. First, authentication: both identity headers must be present and the role must be one of the nine declared roles, else `ERR_UNAUTHENTICATED`. Second, authorization: the role must be permitted for the endpoint, else `ERR_UNAUTHORIZED_ROLE`. Third, existence: every path identifier and foreign-key body field must resolve, checked left to right, else `ERR_NOT_FOUND`. Fourth, transition validity: the requested action must correspond to a transition that exists from the resource's current state, else `ERR_INVALID_STATE` (HTTP 409); a resource already in a terminal state accepts no further transitions at all and rejects them with `ERR_ALREADY_TERMINAL` (HTTP 409).

Business rules then evaluate in their declared priority, and where several guard the same operation their relative order matters. On pairing decisions, segregation of duties is checked before the supplier's own approval status. On submission of a formula for nutrient review, the ingredient-active check is evaluated before the inclusion-sum check. On substantiation, sourcing coverage is evaluated before the adequacy-basis gate. On batch release, the four guards fire in the order: open-recall gate, ingredient-active, sourcing coverage, line-schedule conflict. The remaining business guards — the best-by rule on lot cutting, the label-revision and complaint-score gates on registration approval, the yield-variance hold on batch completion, and the uniqueness constraints on resource creation — each guard their respective operations as described in §3. Independently of this ordering, structural request validity is always enforced: a missing required field, a wrong-typed value, or an enum value outside its declared set is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and out-of-bounds pagination parameters are rejected with `ERR_PAGINATION`.

## 3. Business Logic & Workflows

### 3.1. Master Data: Brand Owners, Suppliers, and the Ingredient Registry

Everything in the platform begins with master data. A `PlatformAdmin` registers each private-label **Brand Owner** with its `legal_name` (non-empty, at most 200 characters), its `fein` (a 9-digit federal employer identification string, unique across all brand owners), and a `contact_email` used as the primary regulatory contact. A brand owner's `status` begins at `ACTIVE` and its declared lifecycle domain is `ACTIVE`, `SUSPENDED`, and `TERMINATED`. Two computed counters ride on the brand record and start at zero: `open_recall_count`, the number of recall actions linked to the brand's formulas whose status is anything other than `CLOSED`, and `complaint_score`, the rolling weighted complaint score described in §3.8 that drives registration holds.

Supplier facilities are likewise registered by a `PlatformAdmin`, with a `supplier_name` (non-empty, at most 200 characters), an `fsma_facility_id` (the FDA food-facility registration number, unique across suppliers), a `country_code` in ISO-3166 alpha-2 form, and a `risk_tier` of `LOW`, `MEDIUM`, or `HIGH` assigned by QA. A new supplier's `approval_state` starts at `PROVISIONAL`; the full domain is `PROVISIONAL`, `APPROVED`, `SUSPENDED`, and `DISQUALIFIED`. A `QAApprover` approves a provisional supplier, moving it to `APPROVED`, and may later suspend an approved supplier, moving it to `SUSPENDED`; each such decision increments the supplier's `version`. The supplier record also carries `approved_ingredient_count`, a computed tally of its pairing rows currently in the `APPROVED` state.

The **Ingredient** registry belongs to the `FormulationScientist`. Each master record carries the `aafco_name` — the official AAFCO-defined ingredient name exactly as it must appear on a label, unique across the registry — plus an internal `ingredient_code` of 8 uppercase alphanumeric characters, also unique. The `nutrient_matrix` captures the ingredient's typical nutrient contribution per kilogram as-fed: an object keyed by AAFCO nutrient codes (for example `CRUDE_PROTEIN`, `CRUDE_FAT`, `CRUDE_FIBER`, `MOISTURE`, `CALCIUM`, `PHOSPHORUS`) mapping to numeric fractions between 0 and 1 inclusive (or kcal-per-kg figures), with a moisture entry mandatory. Each ingredient declares an `allergen_class` for change-control flagging — one of `NONE`, `POULTRY`, `BEEF`, `FISH`, `DAIRY`, `GRAIN`, or `OTHER` — and a `requires_coa` flag, defaulting to true, that determines whether every receiving lot and pairing review must carry a certificate of analysis. An ingredient's `status` starts at `ACTIVE` and may later become `RETIRED`, at which point it can no longer support formula submission or batch release.

Uniqueness is enforced platform-wide with `ERR_DUPLICATE_KEY` (HTTP 409): the `fein` across brand owners, the `fsma_facility_id` across suppliers, the `aafco_name` across ingredients, the `protocol_code` across feeding-trial protocols, the `formula_code` within each brand owner, and the `state_code` within each formula's registrations.

### 3.2. Supplier–Ingredient Qualification and Segregation of Duties

Before any formula can be substantiated or any batch released, every ingredient it uses must trace to at least one approved supplier. That trace is the **Supplier–Ingredient Approval** pairing. A `QualityAnalyst` requests a pairing by submitting the `supplier_id` of the facility under review, the `ingredient_id` it will supply, and a `coa_document_ref` pointing at the certificate of analysis presented for review; the reference is mandatory whenever the ingredient's `requires_coa` flag is true, and omitting a mandatory field is rejected with `ERR_INVALID_REQUEST`. Free-text `review_notes` may accompany the request and default to empty. A new pairing starts in `PENDING_REVIEW`.

Decision rights sit with a `QAApprover`, under segregation of duties. On both approval and rejection, the deciding user must not be the user who submitted the pairing request; a violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403), and this check is evaluated before any other business rule on the decision. Approval additionally requires that the supplier itself currently sits in `APPROVED` — otherwise `ERR_SUPPLIER_NOT_APPROVED` (HTTP 422) — and that the ingredient is still `ACTIVE`, otherwise `ERR_INGREDIENT_INACTIVE`. Every decision stamps the pairing's `decided_by` with the acting `X-User-ID` and `decided_at` with the decision timestamp. Approval moves the pairing to `APPROVED` and recomputes the supplier's `approved_ingredient_count`; rejection moves it to `REJECTED`. Both `REJECTED` and `REVOKED` are terminal for a pairing.

Revocation is the dangerous branch. A `QAApprover` may revoke a pairing currently in `APPROVED`, moving it to `REVOKED`; the decision stamps `decided_by` and `decided_at`, recomputes the supplier's `approved_ingredient_count`, and then cascades outward: every formula sitting in `NUTRIENT_REVIEW` that includes the revoked ingredient and is now left without any `APPROVED` pairing covering that ingredient is pushed back to `DRAFT`, with its `revision_number` incremented by one and its `version` advanced. Qualification debt, in other words, flows immediately back to the formula work in flight.

### 3.3. Formula Development, Nutrient Profiling, and Adequacy Substantiation

A **Formula** is created by a `FormulationScientist` under a brand owner — the brand's `id` in the path becomes the formula's `brand_owner_id` — with a brand-scoped `formula_code` (unique within that brand), the marketing `product_name` printed on the label, the target `species` (`DOG` or `CAT`), the AAFCO `life_stage` claim (`GROWTH`, `ADULT_MAINTENANCE`, `ALL_LIFE_STAGES`, or `GESTATION_LACTATION`), and the `adequacy_basis` declaring the substantiation pathway: `FORMULATION` or `FEEDING_TRIAL`. A formula starts in `DRAFT` with `revision_number` 1, `substantiation_locked_version` null, `total_batch_count` zero, and `open_recall_flag` false.

Revision is a first-class concept. A creation request may carry a `parent_formula_id` referencing an earlier formula; when that parent is `LOCKED`, creating the revision supersedes it — the parent moves from `LOCKED` to `SUPERSEDED`, and the cascade fires: every state registration of the parent sitting in `SUBMITTED` or `UNDER_REVIEW` moves to `REVOKED`, and every production batch of the parent sitting in `SCHEDULED` or `RELEASED_FOR_PRODUCTION` moves to `REJECTED`. `SUPERSEDED` and `WITHDRAWN` are the formula's terminal states.

While a formula is in `DRAFT`, the `FormulationScientist` builds its composition as **Formula Ingredient** lines. Each line names the included `ingredient_id`, an `inclusion_pct` expressing the ingredient's percentage of total batch mass — greater than 0 and at most 100 — and an optional free-text `processing_note` defaulting to empty. Adding a line mutates the formula and increments its `version`. The composition rule is enforced at submission time: the inclusion percentages across all of a formula's lines must total 100.00 within an absolute tolerance of 0.01 — totals from 99.99 to 100.01 inclusive pass — and a formula with no ingredient lines at all cannot be submitted.

Submission for nutrient review moves the formula from `DRAFT` to `NUTRIENT_REVIEW`. The guards evaluate in order: first, every referenced ingredient must still be `ACTIVE`, else `ERR_INGREDIENT_INACTIVE`; then the inclusion-sum rule, else `ERR_INCLUSION_SUM_INVALID` (HTTP 422). If a nutrient profile already exists for the formula at submission time, its metabolizable energy is recomputed as part of the transition.

The **Nutrient Profile** quantifies the guaranteed analysis. A `FormulationScientist` posts the profile with a `profile_basis` of `FORMULATION_CALC` (numbers rolled up from the theoretical ingredient matrix) or `LAB_ANALYSIS` (numbers from measured laboratory composites), together with the four label guarantees — `crude_protein_min_pct`, `crude_fat_min_pct`, `crude_fiber_max_pct`, `moisture_max_pct` — and optionally `calcium_min_pct` and `phosphorus_min_pct`, which default to 0. A profile may only exist for a formula whose `adequacy_basis` is `FORMULATION`; posting one for a `FEEDING_TRIAL`-basis formula is rejected with `ERR_PROFILE_BASIS_MISMATCH` (HTTP 422). A formula carries at most one current profile per basis: posting a new profile for a basis the formula already has replaces the earlier one as current, and the profile listing returns the latest profile per basis — an array of zero or one entries. Posting a profile triggers two computations immediately.

The first computation is metabolizable energy, stored as `metabolizable_energy_kcal_per_kg`, following the modified Atwater method. Gross energy per 100 grams is the crude protein percentage multiplied by 5.7, plus the crude fat percentage multiplied by 9.4, plus the carbohydrate percentage multiplied by 4.1 — where the carbohydrate percentage is whatever remains of 100 after subtracting the protein, fat, fiber, and moisture percentages and an assumed ash content of 7.0 percent. Percent digestibility is 87.8 minus the product of three terms: 0.88, the fiber percentage, and the ratio of 100 to the larger of two values (100 minus the moisture percentage, or 1.0). Metabolizable energy in kcal per kilogram is the gross energy per 100 grams multiplied by the digestibility expressed as a fraction, then multiplied by 10, rounded half up to 1 decimal place. When the profile's basis is `LAB_ANALYSIS`, the fiber coefficient inside the digestibility term is halved — 0.44 instead of 0.88 — reflecting measured energy density, so identical macro inputs yield a different energy figure than the `FORMULATION_CALC` variant.

The second computation is the AAFCO profile check, stored as `aafco_compliance` (default `PENDING`, resolving to `COMPLIANT` or `DEFICIENT`). Four nutrients are gated against AAFCO minimums keyed by the formula's species and life stage: protein, fat, calcium, and phosphorus. For an adult dog the floors are 18.0 percent protein, 5.5 percent fat, 0.6 percent calcium, and 0.5 percent phosphorus; for a growth-stage dog they are 22.5, 8.5, 1.0, and 0.8 percent respectively; for an adult cat 26.0, 9.0, 0.6, and 0.5; for a growth-stage cat 30.0, 9.0, 1.0, and 0.8. An `ADULT_MAINTENANCE` claim is evaluated against the adult floors, while `GROWTH`, `GESTATION_LACTATION`, and `ALL_LIFE_STAGES` claims are evaluated against the more demanding growth floors. Because AAFCO profiles are expressed per unit of energy, the floors are energy-normalized: whenever the computed metabolizable energy exceeds 4000 kcal per kilogram, each floor is scaled upward by the ratio of that energy figure to 4000 — and the energy figure used for normalization is the one matching the formula's declared basis, the formulation estimate or the lab-verified value, so identical nutrient percentages can flip the verdict between bases. Each comparison is made at 2 decimal places with values rounded half up before comparison. Fiber and moisture are label maximums, not AAFCO gates, and do not participate. The verdict is `COMPLIANT` only when every gated nutrient meets its possibly-normalized floor; any shortfall makes it `DEFICIENT`.

From `NUTRIENT_REVIEW` a `QAApprover` has three roads. Requesting a revision loops the formula back to `DRAFT` and increments its `revision_number` by one — the cyclic rework loop. Substantiation moves the formula to `SUBSTANTIATED` and is gated, in order, by two checks. First, sourcing coverage: for every ingredient line on the formula there must exist at least one supplier–ingredient pairing in the `APPROVED` state covering that ingredient, else `ERR_UNAPPROVED_INGREDIENT_SOURCE`. Second, the adequacy-basis gate, whose failure is `ERR_SUBSTANTIATION_UNMET` (HTTP 422): a `FORMULATION`-basis formula must have a nutrient profile whose `aafco_compliance` is `COMPLIANT`, while a `FEEDING_TRIAL`-basis formula must have a trial protocol whose status is `PASSED`. Successful substantiation pins `substantiation_locked_version` to the current `version` of the linked substantiation object — the nutrient profile or the feeding-trial protocol, according to basis — freezing the evidentiary baseline at approval time.

Locking moves a `SUBSTANTIATED` formula to `LOCKED`, the only state from which production may be scheduled. The gate is the formula's `open_recall_flag`: it must be false, else the request is rejected with `ERR_OPEN_RECALL` (HTTP 422). Withdrawal moves a `LOCKED` formula to `WITHDRAWN` and requires that every production batch of the formula already sits in a terminal state — `COMPLETED`, `REJECTED`, or `RECALLED`; withdrawal cascades by moving every registration of the formula in `APPROVED` to `REVOKED`.

### 3.4. Feeding-Trial Protocols

Brands that substantiate by feeding trial work through a **Feeding Trial Protocol**, created by a `TrialCoordinator` under the formula being tested. Creation is permitted only for a formula whose `adequacy_basis` is `FEEDING_TRIAL`; attempting to create a protocol for a `FORMULATION`-basis formula is rejected with `ERR_PROFILE_BASIS_MISMATCH`. Each protocol carries a `protocol_code` (the AAFCO protocol identifier, unique across all protocols), the planned `animal_count`, and the planned `duration_days`; for adult-maintenance protocols at least 8 animals must be planned and the duration must be at least 26 days. A new protocol starts in `PLANNED` with `enrolled_count` and `completed_count` at zero, and its `completion_ratio` — the `completed_count` divided by the `animal_count` — is kept at 4 decimal places.

Opening enrollment moves the protocol from `PLANNED` to `ENROLLING`. The formula must still have `FEEDING_TRIAL` as its basis and must be sitting in `DRAFT` or `NUTRIENT_REVIEW`. While the protocol is `ENROLLING`, the `TrialCoordinator` records enrollment events; each event carries an `enrolled_delta` that is added to the running `enrolled_count`.

Starting the trial moves the protocol from `ENROLLING` to `RUNNING` and requires full enrollment — the recorded `enrolled_count` must be at least the planned `animal_count`; otherwise the request is rejected with `ERR_TRIAL_NOT_FULLY_ENROLLED` (HTTP 422). When observation ends, the `TrialCoordinator` completes it, moving the protocol from `RUNNING` to `ANALYSIS`; the payload records the `completed_count` of animals finishing without a disqualifying event, and the `completion_ratio` is recomputed.

Verdicts belong to the `QAApprover`. Recording a verdict routes on the recomputed ratio: a `completion_ratio` of 0.75 or higher moves the protocol from `ANALYSIS` to `PASSED`, while a ratio below 0.75 moves it to `FAILED`. The failed branch is a routing outcome, not an error — the request succeeds either way. Only when the caller explicitly requests a pass against a ratio below 0.75 is the request rejected with `ERR_TRIAL_COMPLETION_LOW` (HTTP 422). Separately, a `QAApprover` may abort a protocol mid-run, moving it from `RUNNING` to `ABORTED`. `PASSED`, `FAILED`, and `ABORTED` are terminal.

### 3.5. Production Batches, Line Scheduling, and Lot Coding

Production begins when a `ProductionPlanner` creates a **Production Batch** under a formula. The formula must be `LOCKED`, and the request carries the `planned_kg` (greater than zero), the `line_id` of the production line, the `scheduled_start` timestamp in UTC, and the OCC field `expected_formula_version` described in §2.7 — a mismatch with the formula's current `version` is rejected with `ERR_STALE_FORMULA_VERSION` (HTTP 412). Creating a batch itself advances the formula's `version` by one, so a second planner working from a stale formula view is caught by the concurrency check on their own create. A new batch starts in `SCHEDULED` with `actual_kg` at zero.

Release to the floor — moving the batch from `SCHEDULED` to `RELEASED_FOR_PRODUCTION` — is the most heavily gated transition in the plant, and its guards evaluate in a fixed order. First, the formula's `open_recall_flag` must be false, else `ERR_OPEN_RECALL`. Second, every ingredient on the formula must still be `ACTIVE`, else `ERR_INGREDIENT_INACTIVE`. Third, sourcing coverage: for every ingredient line there must exist at least one `APPROVED` pairing whose supplier is itself currently `APPROVED`. When no approved pairing exists for an ingredient the rejection is `ERR_UNAPPROVED_INGREDIENT_SOURCE`; when approved pairings exist but the supplier behind them has been suspended, the rejection is `ERR_SUPPLIER_SUSPENDED` (HTTP 422) — a suspended supplier blocks release even though its pairings remain on file. Fourth, the line-schedule gate: the batch's production window is the half-open interval beginning at its `scheduled_start` and extending eight hours, and that window must not intersect the corresponding window of any other batch on the same `line_id` currently in `RELEASED_FOR_PRODUCTION` or `IN_PROCESS`; a conflict is rejected with `ERR_LINE_SCHEDULE_CONFLICT` (HTTP 409). Because the interval is half-open, back-to-back batches that merely touch at the boundary — one ending exactly when the other begins — are allowed.

On the floor, a `LineOperator` starts the run, moving the batch from `RELEASED_FOR_PRODUCTION` to `IN_PROCESS`. A `QualityAnalyst` may place a running batch on hold (`IN_PROCESS` to `ON_HOLD`) and later resume it (`ON_HOLD` back to `IN_PROCESS`). Rejection is the terminal quality action on a held batch: moving from `ON_HOLD` to `REJECTED` cascades to the batch's lots, pushing every lot in `ACTIVE` to `QUARANTINED`.

Run completion is reported by a `LineOperator` — or by a `QualityAnalyst` when an override situation arises — and moves the batch from `IN_PROCESS` to `COMPLETED`. The payload carries the recorded `actual_kg`, which must be greater than zero. Completion stores `actual_kg`, computes the batch's `yield_variance_pct` (the yield rule itself, including the override governance, is specified in §3.6), and increments the parent formula's `total_batch_count` by one. When the payload includes `lot_fields`, the first lot is cut automatically as part of the same completion. `COMPLETED`, `REJECTED`, and `RECALLED` are the batch's terminal states.

Lot cutting produces the **Batch Lot Code** records that make product traceable. A `LineOperator` cuts a lot from a batch by supplying the `packaged_units` (zero or more) and the `best_by_date` printed on packaging. The best-by date must fall strictly after the batch's production date; a best-by date equal to the production date — or earlier — is rejected with `ERR_BEST_BY_INVALID` (HTTP 422). The server mints each `lot_code` itself: the production date (taken from the parent batch's `scheduled_start` date, in UTC) rendered as an eight-digit calendar stamp, followed by the `line_id`, followed by a sequence number. The sequence is the 1-based position of the lot among all lots created for the same production date and line, ordered by creation time ascending, zero-padded to three digits; the logical clock's millisecond resolution makes creation-time ties impossible. A lot's `status` begins at `ACTIVE`, with a lifecycle domain of `ACTIVE`, `QUARANTINED`, `RELEASED`, and `RECALLED`.

### 3.6. Laboratory Sampling and Guaranteed-Analysis Compliance

Quality verification runs on **Lab Samples**. A `QualityAnalyst` records each sample against a batch with a `sample_type` marking its position in the sampling plan — `FIRST`, `MIDDLE`, `LAST`, or `COMPOSITE` — and the four as-fed measurements `measured_protein_pct`, `measured_fat_pct`, `measured_fiber_pct`, and `measured_moisture_pct`, which may carry up to 3 decimal places. Recording a sample computes its per-sample `verdict` immediately: when every measured value sits within the parent formula's label guarantees — protein and fat at or above their label minimums, fiber and moisture at or below their label maximums — the sample is `WITHIN_LABEL`; any shortfall on a minimum or excess over a maximum makes it `LABEL_VIOLATION`. The `PENDING` verdict is only the pre-computation default.

The **Guaranteed Analysis Report** aggregates a batch's samples into a label-compliance verdict. A `QualityAnalyst` generates the report; generation requires at least one recorded sample whose verdict is not `PENDING`, else `ERR_SAMPLE_PENDING` (HTTP 422). The composite for each nutrient — `composite_protein_pct`, `composite_fat_pct`, `composite_fiber_pct`, `composite_moisture_pct` — is a weighted average across the included samples: those whose verdict is `WITHIN_LABEL` or `LABEL_VIOLATION`, ordered by sampling position (`FIRST`, then `MIDDLE`, then `LAST`, then `COMPOSITE`), with ties on identical position broken by `created_at` ascending. Spot samples (`FIRST`, `MIDDLE`, `LAST`) each carry weight 1; a `COMPOSITE` sample carries weight 1.25. The rounding order is pinned and load-bearing: first, each sample's weighted contribution — its measured value multiplied by its weight — is rounded half up to 3 decimal places; then the rounded contributions are summed; then the sum is divided by the unrounded sum of the weights; finally the quotient is rounded half up to 2 decimal places. Reordering those steps changes answers — samples reading 38.236, 22.379, and a composite at 22.345 produce 27.24 under the pinned order but 27.25 when unrounded contributions are summed first. When no `COMPOSITE` sample exists, every weight is 1 and the composite is the plain mean of the spot readings.

From the composites, the report derives its `deviation_index`, a weighted magnitude of deviation from the label guarantees of the batch's formula. The protein deficit is the amount by which `composite_protein_pct` falls short of the label's `crude_protein_min_pct`, floored at zero — a composite at or above the guarantee contributes nothing; the fat deficit is the analogous shortfall against `crude_fat_min_pct`. The fiber excess is the amount by which `composite_fiber_pct` exceeds the label's `crude_fiber_max_pct`, floored at zero; the moisture excess is the analogous excess over `moisture_max_pct`. The index is three times the protein deficit, plus two times the fat deficit, plus one and a half times the fiber excess, plus one times the moisture excess, rounded half up to 2 decimal places, and it feeds the platform's downstream complaint-risk monitoring. The report's `label_compliance` — default `PENDING` — resolves to `MISBRANDED` when the deviation index is greater than zero, and to `COMPLIANT` when it is exactly zero.

This subsection is also the home of the yield-governance rule referenced at batch completion. A batch's `yield_variance_pct` is the difference between `actual_kg` and `planned_kg`, divided by `planned_kg`, expressed as a percentage and rounded half up to 2 decimal places. When its absolute value is strictly greater than 5.00 percent, the completion request must carry the `override` flag and be acted on by a `QualityAnalyst`; a completion breaching the threshold without the override is rejected with `ERR_YIELD_VARIANCE_HOLD` (HTTP 422). A variance of exactly 5.00 percent passes without an override — the threshold is strict. Overruns (actual mass above planned) and underruns (actual below planned) are judged on the same absolute-value basis, with the sign preserved in the stored figure.

### 3.7. State Registration, Label Review, and Fee Assessment

Selling a formula in a state requires a **State Registration**, submitted by a `RegulatoryAffairs` specialist acting for the brand. Submission is permitted only while the formula is `SUBSTANTIATED` or `LOCKED`; a submission against a formula in any other state is rejected with `ERR_INVALID_STATE`. The request names the `state_code` (exactly two uppercase letters, unique within the formula's registrations), the `label_revision_ref` — the `revision_number` of the formula label submitted for review — and the `tonnage_tier` declaring the brand's prior-year tonnage in that state. Submission stamps `submitted_at`, computes the `fee_cents` from the fee schedule, and lands the registration in `SUBMITTED`.

The annual registration fee is assessed in integer cents from a per-state base — 7500 cents for CA, 6000 cents for TX, 8000 cents for NY, and a default of 5000 cents for any other state — scaled by the declared tonnage tier. Tier boundaries are inclusive at their lower bound: below 5 tons pays the base fee; 5 tons up to but not including 50 tons pays one and a half times the base; 50 tons or more pays double. Multiplication results are rounded half up to whole cents.

A `StateRegulator` accepts a submission for review, moving it from `SUBMITTED` to `UNDER_REVIEW`; acceptance requires the formula to be `SUBSTANTIATED` or `LOCKED` and the formula's `open_recall_flag` to be false, else `ERR_OPEN_RECALL`. The approval decision — `UNDER_REVIEW` to `APPROVED` — carries the OCC field `expected_formula_version` per §2.7 and enforces two fiscal-regulatory gates: the `label_revision_ref` under review must still equal the formula's current `revision_number`, else `ERR_LABEL_REVISION_STALE` (HTTP 422), because an approval issued against a superseded label revision would pin the wrong baseline; and the brand owner's `complaint_score` must be below 70.0, else `ERR_COMPLAINT_SCORE_HOLD` (HTTP 422), holding registrations for brands whose complaint risk has crossed the regulatory threshold. Either decision stamps `decided_at`; rejection moves the registration to `REJECTED`.

Rejection is not terminal here. A `RegulatoryAffairs` specialist may resubmit a `REJECTED` registration, moving it back to `SUBMITTED`; resubmission requires the formula to be `SUBSTANTIATED` or `LOCKED`, carries a fresh `tonnage_tier`, and recomputes `fee_cents` from the fee schedule. Time acts on approvals: when the logical clock (§2.5) advances past a registration's state-specific annual expiry date, the system moves that registration from `APPROVED` to `EXPIRED` with no client action. `APPROVED`, `EXPIRED`, and `REVOKED` are terminal states for direct client transitions — though the formula-level cascades of §3.3 can still move registrations in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` to `REVOKED` when their formula is superseded or withdrawn.

### 3.8. Complaint Intake, Risk Scoring, and Recall Execution

A **Complaint Case** enters the platform through a `QualityAnalyst`, recording the `brand_owner_id` of the brand owning the product, the implicated `formula_id`, an optional `batch_id` (nullable when the batch is unknown), the reporter-assessed `severity` (`MINOR`, `SERIOUS`, `LIFE_THREATENING`, or `DEATH`), the `category` (`PALATABILITY`, `FOREIGN_MATERIAL`, `ILLNESS`, `LABEL_DEFECT`, or `PACKAGING`), and an `adverse_event_flag` (defaulting to false) marking alleged health events. Intake lands the case in `INTAKE` and computes a provisional `triage_score`.

The risk model is a weighted sum, kept at 2 decimal places with round-half-up. Severity contributes 5 points for `MINOR`, 20 for `SERIOUS`, 45 for `LIFE_THREATENING`, and 60 for `DEATH`. Category contributes 2 for `PALATABILITY`, 3 for `PACKAGING`, 8 for `LABEL_DEFECT`, 12 for `FOREIGN_MATERIAL`, and 15 for `ILLNESS`. A confirmed adverse event adds a further 10 points. The provisional score at intake omits the adverse-event bonus until the flag is confirmed; the final score at triage includes it whenever `adverse_event_flag` is true, so an identical severity–category pair scores lower provisionally than finally when an adverse event is confirmed.

Triage is performed by a `QualityAnalyst` whose payload carries `confirm_adverse_event_flag`. Triage computes the final `triage_score`, recomputes the brand's `complaint_score`, and then branches: ordinarily the case moves from `INTAKE` to `TRIAGED`, but when the final score reaches 60.0 or higher the case auto-escalates directly to `ESCALATED_RECALL` instead — the escalation fork is part of the triage transition itself. From `TRIAGED`, a `QualityAnalyst` opens an investigation, moving the case to `INVESTIGATING`, or closes it without action, moving it to `CLOSED_NO_ACTION`; closure without action is forbidden when the `adverse_event_flag` is true and is rejected with `ERR_ADVERSE_CLOSE_FORBIDDEN` (HTTP 422). From `INVESTIGATING`, a `QualityAnalyst` resolves the case (`RESOLVED`), which recomputes the brand's `complaint_score` with closure decay applied, while a `QAApprover` may instead escalate it to `ESCALATED_RECALL`. `RESOLVED`, `ESCALATED_RECALL`, and `CLOSED_NO_ACTION` are terminal.

The brand-level `complaint_score` is a weighted mean over recent casework: final triage scores of the brand's cases sitting in `TRIAGED` or `INVESTIGATING` within the trailing 90-day window ending at the logical clock, with cases still in `TRIAGED` contributing at half weight. Recently closed cases do not vanish immediately: for 30 days after a case reaches `RESOLVED` or `CLOSED_NO_ACTION`, it continues to contribute one quarter of its final score. The score's regulatory teeth are in §3.7 — a brand at or above 70.0 cannot win new registration approvals.

Escalated or otherwise substantiated problems become **Recall Actions**, initiated by a `QAApprover` with the `formula_id`, the FDA `recall_class` (`CLASS_I`, `CLASS_II`, or `CLASS_III`), a public `reason` statement, and the `scope_batch_ids` array listing the batches in scope; an empty array places every non-terminal batch of the formula in scope. An initiation that finds no in-scope batches or lots at all is rejected with `ERR_RECALL_SCOPE_EMPTY` (HTTP 422). Otherwise initiation cascades: every in-scope batch in `COMPLETED` or `ON_HOLD` moves to `RECALLED`; every lot of an in-scope batch in `ACTIVE`, `QUARANTINED`, or `RELEASED` moves to `RECALLED`; the recall's `affected_lot_count` records how many lots moved; the formula's `open_recall_flag` is set true; and the brand's `open_recall_count` increases by one. The recall starts in `INITIATED`.

Effectiveness checking follows the FDA pattern. Beginning the check moves the recall from `INITIATED` to `EFFECTIVENESS_CHECK` and requires the lot cascade to have actually executed — `affected_lot_count` greater than zero, else `ERR_RECALL_NO_LOTS` (HTTP 422). Recording effectiveness moves the recall to `COMPLETED` and stores the recovery figure supplied as `effectiveness_pct` — a field that sits at zero until recorded — which must lie between 0 and 100 inclusive, else `ERR_EFFECTIVENESS_RANGE` (HTTP 422). Closing a `COMPLETED` recall moves it to `CLOSED` and recomputes both the formula's `open_recall_flag` — false again once no other open recall remains — and the brand's `open_recall_count`.

A recall initiated in error can be unwound. Termination moves an `INITIATED` recall to `TERMINATED` with a compensating cascade: every lot this action had moved to `RECALLED` returns to `QUARANTINED`, and every batch it had moved to `RECALLED` returns to `ON_HOLD`, after which the formula's `open_recall_flag` and the brand's `open_recall_count` are recomputed. `COMPLETED`, `CLOSED`, and `TERMINATED` are the recall's terminal states. While any recall on a formula remains unclosed, the three downstream gates of §3.3, §3.5, and §3.7 — formula lock, registration acceptance, and batch release — stay shut with `ERR_OPEN_RECALL`.

## 4. Endpoint Definitions

Operations that create a new resource — a brand owner, supplier, ingredient, pairing, formula, ingredient line, nutrient profile, trial protocol, production batch, lot, lab sample, guaranteed-analysis report, state registration, complaint case, or recall action — return `201 Created`. Operations that modify an existing resource, including every state-transition action, return `200 OK`. All query endpoints return `200 OK`. The table below is a navigational summary only; the complete request and response semantics for each operation live in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/petfood/_clock/set_current_utc` | Set the logical clock; triggers the registration expiry sweep | PlatformAdmin |
| POST | `/petfood/brand-owners` | Register a private-label brand owner | PlatformAdmin |
| GET | `/petfood/brand-owners/{id}` | Fetch one brand owner | PlatformAdmin, RegulatoryAffairs, QualityAnalyst, QAApprover, FormulationScientist |
| GET | `/petfood/brand-owners` | List brand owners with pagination | PlatformAdmin, RegulatoryAffairs, QualityAnalyst, QAApprover, FormulationScientist |
| GET | `/petfood/brand-owners/{id}/complaint-cases` | List complaint cases for a brand | PlatformAdmin, QualityAnalyst, QAApprover |
| POST | `/petfood/suppliers` | Register a supplier facility (starts PROVISIONAL) | PlatformAdmin |
| POST | `/petfood/suppliers/{id}/approve` | Approve a PROVISIONAL supplier | QAApprover |
| POST | `/petfood/suppliers/{id}/suspend` | Suspend an APPROVED supplier | QAApprover |
| GET | `/petfood/suppliers/{id}` | Fetch one supplier | PlatformAdmin, QAApprover, QualityAnalyst, FormulationScientist, ProductionPlanner |
| GET | `/petfood/suppliers/{id}/ingredient-approvals` | List supplier–ingredient approvals for a supplier | PlatformAdmin, QAApprover, QualityAnalyst |
| POST | `/petfood/ingredients` | Create an ingredient master | FormulationScientist |
| GET | `/petfood/ingredients/{id}` | Fetch one ingredient | PlatformAdmin, FormulationScientist, QualityAnalyst, QAApprover, ProductionPlanner |
| GET | `/petfood/ingredients` | List ingredients | PlatformAdmin, FormulationScientist, QualityAnalyst, QAApprover, ProductionPlanner |
| POST | `/petfood/supplier-ingredient-approvals` | Request approval for a supplier+ingredient pairing | QualityAnalyst |
| POST | `/petfood/supplier-ingredient-approvals/{id}/approve` | Approve the pairing (approver must differ from requester) | QAApprover |
| POST | `/petfood/supplier-ingredient-approvals/{id}/reject` | Reject the pairing (rejecter must differ from requester) | QAApprover |
| POST | `/petfood/supplier-ingredient-approvals/{id}/revoke` | Revoke an APPROVED pairing; cascades uncovered in-review formulas back to DRAFT | QAApprover |
| GET | `/petfood/supplier-ingredient-approvals/{id}` | Fetch one pairing | PlatformAdmin, QualityAnalyst, QAApprover |
| POST | `/petfood/brand-owners/{id}/formulas` | Create a formula; an optional parent reference creates a revision and supersedes the LOCKED parent | FormulationScientist |
| GET | `/petfood/formulas/{id}` | Fetch one formula | PlatformAdmin, FormulationScientist, QualityAnalyst, QAApprover, RegulatoryAffairs, ProductionPlanner, StateRegulator |
| GET | `/petfood/formulas/{id}/ingredients` | List ingredient lines of a formula | PlatformAdmin, FormulationScientist, QualityAnalyst, QAApprover, ProductionPlanner |
| POST | `/petfood/formulas/{id}/ingredients` | Add an ingredient line to a DRAFT formula | FormulationScientist |
| POST | `/petfood/formulas/{id}/submit-nutrient-review` | Move a DRAFT formula into NUTRIENT_REVIEW | FormulationScientist |
| POST | `/petfood/formulas/{id}/request-revision` | Send a formula under review back to DRAFT, incrementing its revision | QAApprover |
| POST | `/petfood/formulas/{id}/substantiate` | Substantiate nutritional adequacy and pin the substantiation baseline | QAApprover |
| POST | `/petfood/formulas/{id}/lock` | Lock a substantiated formula for production | QAApprover |
| POST | `/petfood/formulas/{id}/withdraw` | Withdraw a LOCKED formula whose batches are all terminal | QAApprover |
| POST | `/petfood/formulas/{id}/nutrient-profiles` | Create or replace the nutrient profile of a formula; runs energy and AAFCO checks | FormulationScientist |
| GET | `/petfood/formulas/{id}/nutrient-profiles` | List nutrient profiles of a formula (latest per basis) | PlatformAdmin, FormulationScientist, QualityAnalyst, QAApprover |
| POST | `/petfood/formulas/{id}/feeding-trial-protocols` | Create a feeding trial protocol for a FEEDING_TRIAL-basis formula | TrialCoordinator |
| GET | `/petfood/feeding-trial-protocols/{id}` | Fetch one protocol | PlatformAdmin, TrialCoordinator, QAApprover, QualityAnalyst |
| GET | `/petfood/formulas/{id}/feeding-trial-protocols` | List protocols for a formula | PlatformAdmin, TrialCoordinator, QAApprover, QualityAnalyst |
| POST | `/petfood/feeding-trial-protocols/{id}/open-enrollment` | Move a protocol from PLANNED to ENROLLING | TrialCoordinator |
| POST | `/petfood/feeding-trial-protocols/{id}/enroll` | Record enrolled animals (additive) | TrialCoordinator |
| POST | `/petfood/feeding-trial-protocols/{id}/start-trial` | Move from ENROLLING to RUNNING once fully enrolled | TrialCoordinator |
| POST | `/petfood/feeding-trial-protocols/{id}/complete-observation` | Move from RUNNING to ANALYSIS, recording completions | TrialCoordinator |
| POST | `/petfood/feeding-trial-protocols/{id}/record-verdict` | Route ANALYSIS to PASSED or FAILED by completion ratio | QAApprover |
| POST | `/petfood/feeding-trial-protocols/{id}/abort` | Abort a RUNNING protocol | QAApprover |
| POST | `/petfood/formulas/{formula_id}/production-batches` | Create a batch against a LOCKED formula (formula-version OCC) | ProductionPlanner |
| GET | `/petfood/production-batches/{id}` | Fetch one batch | PlatformAdmin, ProductionPlanner, LineOperator, QualityAnalyst, QAApprover |
| GET | `/petfood/formulas/{id}/production-batches` | List batches of a formula | PlatformAdmin, ProductionPlanner, QualityAnalyst, QAApprover |
| POST | `/petfood/production-batches/{id}/release` | Release a SCHEDULED batch; enforces recall, ingredient, sourcing, and line-schedule gates | ProductionPlanner |
| POST | `/petfood/production-batches/{id}/start-run` | Move a released batch to IN_PROCESS | LineOperator |
| POST | `/petfood/production-batches/{id}/hold` | Place a running batch ON_HOLD | QualityAnalyst |
| POST | `/petfood/production-batches/{id}/resume` | Resume a held batch | QualityAnalyst |
| POST | `/petfood/production-batches/{id}/complete` | Complete a run; records actual mass, computes yield variance, optionally cuts the first lot | LineOperator, QualityAnalyst |
| POST | `/petfood/production-batches/{id}/reject` | Reject a held batch; quarantines its ACTIVE lots | QualityAnalyst |
| POST | `/petfood/production-batches/{id}/lots` | Cut a lot from a batch; the server assigns the lot code | LineOperator |
| GET | `/petfood/production-batches/{id}/lots` | List lots of a batch | PlatformAdmin, LineOperator, QualityAnalyst, QAApprover |
| POST | `/petfood/production-batches/{id}/lab-samples` | Record a lab sample and compute its per-sample verdict | QualityAnalyst |
| GET | `/petfood/production-batches/{id}/lab-samples` | List lab samples of a batch | PlatformAdmin, QualityAnalyst, QAApprover |
| POST | `/petfood/production-batches/{id}/ga-reports` | Generate the GA report: composites, deviation index, label compliance | QualityAnalyst |
| GET | `/petfood/production-batches/{id}/ga-reports` | List GA reports of a batch | PlatformAdmin, QualityAnalyst, QAApprover |
| POST | `/petfood/formulas/{id}/state-registrations` | Submit a state registration; computes the registration fee | RegulatoryAffairs |
| GET | `/petfood/state-registrations/{id}` | Fetch one registration | PlatformAdmin, RegulatoryAffairs, StateRegulator, QAApprover |
| GET | `/petfood/formulas/{id}/state-registrations` | List registrations of a formula | PlatformAdmin, RegulatoryAffairs, StateRegulator |
| POST | `/petfood/state-registrations/{id}/accept-for-review` | Move a registration from SUBMITTED to UNDER_REVIEW | StateRegulator |
| POST | `/petfood/state-registrations/{id}/approve` | Approve a registration (formula-version OCC; label-revision and complaint-score gates) | StateRegulator |
| POST | `/petfood/state-registrations/{id}/reject` | Reject a registration under review | StateRegulator |
| POST | `/petfood/state-registrations/{id}/resubmit` | Resubmit a REJECTED registration; recomputes the fee | RegulatoryAffairs |
| POST | `/petfood/complaint-cases` | Intake a complaint or adverse event; computes the provisional triage score | QualityAnalyst |
| GET | `/petfood/complaint-cases/{id}` | Fetch one complaint case | PlatformAdmin, QualityAnalyst, QAApprover |
| GET | `/petfood/formulas/{id}/complaint-cases` | List complaint cases implicating a formula | PlatformAdmin, QualityAnalyst, QAApprover |
| POST | `/petfood/complaint-cases/{id}/triage` | Triage a case; auto-escalates when the final score reaches the escalation threshold | QualityAnalyst |
| POST | `/petfood/complaint-cases/{id}/open-investigation` | Move a triaged case to INVESTIGATING | QualityAnalyst |
| POST | `/petfood/complaint-cases/{id}/resolve` | Resolve an investigated case; brand score decays | QualityAnalyst |
| POST | `/petfood/complaint-cases/{id}/escalate` | Escalate an investigated case to ESCALATED_RECALL | QAApprover |
| POST | `/petfood/complaint-cases/{id}/close-no-action` | Close a triaged case without action (forbidden for adverse events) | QualityAnalyst |
| POST | `/petfood/recall-actions` | Initiate a recall; cascades in-scope batches and lots to RECALLED | QAApprover |
| GET | `/petfood/recall-actions/{id}` | Fetch one recall | PlatformAdmin, QAApprover, QualityAnalyst |
| GET | `/petfood/formulas/{id}/recall-actions` | List recalls for a formula | PlatformAdmin, QAApprover, QualityAnalyst |
| POST | `/petfood/recall-actions/{id}/begin-effectiveness-check` | Begin effectiveness checking (requires recalled lots) | QAApprover |
| POST | `/petfood/recall-actions/{id}/record-effectiveness` | Record the effectiveness percentage and complete the check | QAApprover |
| POST | `/petfood/recall-actions/{id}/close` | Close a completed recall; recomputes formula flag and brand count | QAApprover |
| POST | `/petfood/recall-actions/{id}/terminate` | Terminate an initiated recall with a compensating cascade | QAApprover |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status. The conditions that trigger each error are specified in the narrative of §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_FORMULA_VERSION` | 412 Precondition Failed |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_SUPPLIER_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_SUPPLIER_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_OPEN_RECALL` | 422 Unprocessable Entity |
| `ERR_INGREDIENT_INACTIVE` | 422 Unprocessable Entity |
| `ERR_UNAPPROVED_INGREDIENT_SOURCE` | 422 Unprocessable Entity |
| `ERR_INCLUSION_SUM_INVALID` | 422 Unprocessable Entity |
| `ERR_SUBSTANTIATION_UNMET` | 422 Unprocessable Entity |
| `ERR_LINE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_BEST_BY_INVALID` | 422 Unprocessable Entity |
| `ERR_LABEL_REVISION_STALE` | 422 Unprocessable Entity |
| `ERR_COMPLAINT_SCORE_HOLD` | 422 Unprocessable Entity |
| `ERR_YIELD_VARIANCE_HOLD` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_TRIAL_NOT_FULLY_ENROLLED` | 422 Unprocessable Entity |
| `ERR_TRIAL_COMPLETION_LOW` | 422 Unprocessable Entity |
| `ERR_ADVERSE_CLOSE_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_RECALL_NO_LOTS` | 422 Unprocessable Entity |
| `ERR_RECALL_SCOPE_EMPTY` | 422 Unprocessable Entity |
| `ERR_EFFECTIVENESS_RANGE` | 422 Unprocessable Entity |
| `ERR_SAMPLE_PENDING` | 422 Unprocessable Entity |
| `ERR_PROFILE_BASIS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAGINATION` | 400 Bad Request |
