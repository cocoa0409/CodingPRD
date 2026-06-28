# Allergy & Immunotherapy Clinic API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Allergy & Immunotherapy Clinic API, a system that orchestrates the full clinical pipeline an allergy practice runs to take a patient from diagnosis to long-term desensitization therapy. The pipeline begins with diagnostic testing — skin and blood allergen panels that are scored into a severity tier — and proceeds through the authoring of an individualized immunotherapy plan, the compounding of allergy serum from manufacturer lots into patient-specific vials, the administration of in-office injection visits with mandatory post-injection observation, and the billing that attaches to both the antigen preparation and each injection.

The domain carries real patient-safety weight, so the API treats several concerns as first-class invariants rather than incidental bookkeeping. Serum is a perishable, lot-controlled pharmaceutical: vials expire, lots get recalled, and either event must propagate cleanly to every downstream patient board, dose schedule, and billing charge it touched. Dosing climbs a build-up ladder of increasing concentration and volume, but a systemic allergic reaction must immediately freeze the patient's therapy, reverse the disputed charge, and force a reduced, stepped-back re-entry dose once the clinician resumes care. Because several of these effects fire automatically off a logical clock — expiry, observation windows, refill thresholds — the system maintains an explicit, test-controllable clock rather than reading wall-clock time.

The remainder of this document defines the global contracts every endpoint shares (Section 2), the business logic and workflows that govern each clinical entity (Section 3), the endpoint catalogue (Section 4), and the error code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. A request missing either header, or carrying a malformed value for either, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles, spelled precisely as follows: `Allergist`, `Pharmacist`, `Nurse`, `Biller`, and `FrontDesk`. The `Allergist` is the physician who authors diagnostic panels, finalizes diagnoses, and authors, activates, resumes, completes, and discontinues immunotherapy plans. The `Pharmacist` compounds serum, manages lots and vials, and issues lot recalls. The `Nurse` administers shot visits, observes patients, and records reactions or releases. The `Biller` reviews billing entries and patient billing summaries. The `FrontDesk` registers and updates patients, schedules, and reads records.

All five roles are opaque operator identities. For each of `Allergist`, `Pharmacist`, `Nurse`, `Biller`, and `FrontDesk`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`, and ownership of a resource is never decided by matching `X-User-ID` against a stored field. Authorization is therefore decided purely by role membership against the operation, not by user-to-resource ownership.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. When an operation drives a transition or cascade that touches several resources, the resource returned is the one named by the endpoint's own path — the resource the path identifier resolves to — not any dependent resource mutated by the cascade. For example, recalling a lot returns the lot, discontinuing a plan returns the plan, and releasing or recording a reaction on a shot visit returns that shot visit, even though each of these also mutates dependent resources.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0. A `limit` or `offset` outside its permitted range, or otherwise malformed, is a bad request and is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order — oldest first.

Every list response carries, inside the `meta` object of the envelope, the four pagination fields `limit`, `offset`, `total_count`, and `has_more`. `total_count` is the count of all items matching the query before pagination is applied, and `has_more` is true when items remain beyond the current page.

### 2.4. Common Resource Properties

Every persisted entity carries a server-minted `id` that is a UUID with no type prefix; clients never supply it. Every entity also carries a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits, recorded when the resource is first created.

All of the system's primary entities — `Patient`, `DiagnosticPanel`, `AllergenTest`, `ImmunotherapyPlan`, `SerumLot`, `SerumVial`, `ShotVisit`, and `BillingEntry` — additionally carry an `updated_at` timestamp and a `version` integer. `updated_at` is an ISO 8601 UTC timestamp, formatted identically to `created_at`, that is refreshed on every mutation of the resource. `version` is an integer that begins at its initial value when the resource is created and increments by one on every mutation, including mutations to computed or derived fields. These two fields support optimistic concurrency control as described in Section 2.6. Because all entities in this domain carry the full set, none of them is restricted to only `id` and `created_at`.

Note that "mutation" here includes the reconciliation of derived fields. When the system recomputes a panel's composites, debits a vial's remaining volume, advances a plan's ladder, or reconciles a billing entry, the affected resource's `updated_at` is refreshed and its `version` is incremented, exactly as a direct edit would do.

### 2.5. Hierarchical Consistency and Cascading Effects

The clinical entities form a dependency chain — lots back vials, vials belong to plans, visits draw from vials, and billing entries attach to either a visit or a vial — and the system keeps that chain internally consistent without requiring the client to issue follow-up requests on each dependent resource. When a triggering event occurs on one entity, the system performs every dependent mutation as part of the same operation, refreshing `updated_at` and incrementing `version` on each entity it touches.

Three cascades are central to the domain and are described in full in their respective workflow narratives in Section 3: a lot recall propagates to its vials, their billing entries, and any plan left without a usable vial; discontinuing a plan discards its vials and reconciles their preparation charges; and a systemic reaction during a shot visit freezes the plan, reverses the injection charge, and updates the patient's reaction history. Each link in such a cascade is itself a mutation that bumps the affected entity's `version` and refreshes its `updated_at`.

For any request whose URL names nested resources, the system validates the path identifiers left to right. A request is rejected as soon as the first identifier in the path fails to resolve to an existing resource, returning `ERR_NOT_FOUND` for that identifier. For example, a request to add a test under a panel of a patient first confirms the patient exists, then the panel, before evaluating any body content; a non-existent patient is reported before the panel is ever consulted. Foreign-key targets supplied in a request body — such as `patient_id`, `panel_id`, `plan_id`, `vial_id`, `lot_id`, or `visit_id` — are validated separately, after path resolution, and a missing body target is rejected with `ERR_FK_NOT_FOUND`.

### 2.6. Optimistic Concurrency Control

Two write operations against an `ImmunotherapyPlan` are guarded by optimistic concurrency control, because both depend on the plan's current ladder position, which other operations may have advanced. Both guarded writes require the client to supply `expected_plan_version` as a non-optional field carrying the `version` of the plan the client last observed.

When the pharmacist mixes a new serum vial onto a plan, the request must carry `expected_plan_version` matching the target plan's current `version`. If the plan's `version` has advanced since the client last read it — because a prior vial mix advanced the ladder color, or a systemic-reaction cascade flipped the plan to `HELD` — the create is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), preventing the pharmacist from mixing against a stale view of which rung the plan needs.

Likewise, when the nurse administers a shot visit on a plan, the request must carry `expected_plan_version` matching the plan's current `version`. If the plan's `version` has moved since the nurse last read it — because a prior visit released and advanced the ladder, or a cascade put the plan in `HELD` — the administration is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), so the nurse cannot draw a dose computed against a step the plan has already left.

The resume operation on a held plan also accepts `expected_plan_version` and applies the same stale-version guard defensively: a mismatch between the supplied value and the plan's current `version` is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). No endpoint other than these three accepts or requires a version field.

### 2.7. The Logical Clock and Time-Driven Transitions

The system does not read wall-clock time. Instead it maintains a single logical clock that defaults, at server startup, to exactly `2026-01-01T00:00:00Z`; until the clock is explicitly set, every timestamp the system mints and every time comparison it makes uses this default, and it never falls back to real-world time. An administrative capability, available to any role, sets the logical clock to a supplied UTC instant carried in the `to_iso8601` field; the response echoes the resulting `current_utc` and the list of `expired_vial_ids` for the vials the advance expired.

Advancing the clock is itself a triggering event. Whenever the clock moves forward, the system inspects every vial still in use and, for any whose beyond-use date is at or before the new clock value, transitions that vial to `EXPIRED` and reconciles its provisional preparation charge to its final value. The clock-set response reports the identifiers of every vial expired by that advance.

### 2.8. Precision and Rounding

All computed quantities that are not exact literals are rounded to two decimal places using the round-half-up convention. This applies to panel composite scores, to the antigen units delivered at a visit, and to the reduced re-entry volume computed when a held plan resumes. Dose-ladder volumes are themselves two-decimal literals looked up from a fixed schedule and need no rounding. Monetary amounts are held as whole integer cents; dose-unit counts are whole integers obtained by rounding fractional millilitre figures up to the next whole number (ceiling), and the system never bills a fractional dose.

### 2.9. Concentration Tiers, Vial Colors, and the Build-Up Ladder

Serum concentration is organized into four color-coded rungs from most dilute to full strength: `GREEN`, `YELLOW`, `RED`, and `SILVER`. `SILVER` is the maintenance concentrate at full labeled strength; the others are progressive dilutions of it. The dilution factor relative to `SILVER` maintenance concentrate is fixed by color: `GREEN` is one one-thousandth (0.001), `YELLOW` is one one-hundredth (0.01), `RED` is one tenth (0.1), and `SILVER` is full strength (1.0). The build-up ladder climbs these colors in the order `GREEN → YELLOW → RED → SILVER`; reaction-driven reductions step back down them in the order `SILVER → RED → YELLOW → GREEN`, and `GREEN` is the floor below which the ladder cannot descend.

## 3. Business Logic & Workflows

### 3.1. Patients

A patient is registered with a legal `full_name` and a `date_of_birth` given as an ISO 8601 date in `YYYY-MM-DD` form. Registration may optionally declare `epinephrine_on_file`, a boolean recording whether the patient has a documented epinephrine auto-injector; when omitted it defaults to false. Patient demographics, the `epinephrine_on_file` flag, and the patient's `status` may later be updated. The `status` field is an enum that is either `ACTIVE` or `INACTIVE`, beginning at `ACTIVE` on registration. An `INACTIVE` patient may not have new panels, plans, or shot visits created against them; any such attempt is rejected with `ERR_PATIENT_INACTIVE`.

Each patient also carries a computed `prior_systemic_reaction` boolean, which starts false. It is flipped to true the first time any shot visit on that patient resolves to a systemic reaction, and once true it permanently widens that patient's post-injection observation windows, as described in Section 3.6. The `epinephrine_on_file` flag is safety-critical: it gates the highest-concentration injections and the resumption of a frozen plan, both detailed below.

Patients may be fetched individually or listed. The patient list may be filtered by `status`.

### 3.2. Diagnostic Panels and Allergen Testing

An `Allergist` opens a diagnostic panel for a patient by supplying a free-text `panel_name` (for example, a regional tree-and-grass label) and an optional `control_wheal_mm`, the negative-control wheal diameter in millimetres used as the skin-test baseline. When `control_wheal_mm` is omitted it defaults to 3. The panel records its owning `patient_id`, and its `status` begins at `OPEN`, the state in which it accepts test results; it later transitions to `FINALIZED`. A panel may not be opened for an `INACTIVE` patient.

While a panel is `OPEN`, the `Allergist` adds allergen test results to it. Each `AllergenTest` references its `panel_id` and carries an `allergen_code` identifying the allergen, a `method` enum that is either `SKIN` or `BLOOD`, and a `clinically_relevant` boolean (defaulting to false) by which the allergist marks the test for inclusion in the clinical composite. The two methods are mutually exclusive in their measurements: a `SKIN` test must carry `wheal_mm` (the skin wheal diameter in millimetres) and must not carry `specific_ige_ku`, while a `BLOOD` test must carry `specific_ige_ku` (specific IgE in kU/L) and must not carry `wheal_mm`. A test that supplies the wrong measurement for its method, or omits the required one, is rejected with `ERR_TEST_METHOD_MISMATCH`. Adding a test to a panel that is not `OPEN` is rejected with `ERR_PANEL_NOT_OPEN`.

Every test is scored on creation, and the panel's composites are recomputed at the same time. For a `SKIN` test the system first computes the difference between `wheal_mm` and the panel's `control_wheal_mm`; the test's `sensitization_index` is the greater of zero and that difference, and the test `is_positive` when that difference is at least 3 millimetres. For a `BLOOD` test the system maps `specific_ige_ku` to an IgE class on a 0-to-6 scale using six ascending boundaries — 0.35, 0.70, 3.5, 17.5, 50, and 100 kU/L: a value below 0.35 is class 0, a value at least 0.35 but below 0.70 is class 1, at least 0.70 but below 3.5 is class 2, at least 3.5 but below 17.5 is class 3, at least 17.5 but below 50 is class 4, at least 50 but below 100 is class 5, and a value at or above 100 is class 6. The blood test's `sensitization_index` is that IgE class, and it `is_positive` when the class is at least 1, equivalently when `specific_ige_ku` is at least 0.35.

The panel maintains two composite scores that differ only in which tests they include. The `screening_composite` is the mean of `sensitization_index` over all tests on the panel, rounded to two decimal places half-up. The `clinical_composite` is the mean of `sensitization_index` over only those tests whose `clinically_relevant` flag is true, rounded the same way; if the panel has no clinically-relevant test, the `clinical_composite` is 0. Because the screening variant divides by the full test count, it dilutes strong indices with weak ones and tends to yield a lower, more conservative figure; the clinical variant divides by only the relevant subset and is the one that drives therapy. From the `clinical_composite` the panel derives `recommended_tier`, an enum: a composite below 4 is `LOW`, a composite at least 4 but below 7 is `MODERATE`, and a composite of 7 or more is `HIGH`. The same panel can therefore land in different tiers under the two variants — for instance a panel whose screening composite is 3.67 reads conservatively while its clinical composite of 4.5 drives a `MODERATE` recommendation.

Finalizing a panel freezes it. The `Allergist` finalizes an `OPEN` panel; finalization requires that the panel hold at least one test and at least one test that is positive. A panel that is not `OPEN` cannot be finalized (`ERR_PANEL_NOT_OPEN`); a panel with zero tests is rejected with `ERR_PANEL_EMPTY`; and a panel that has tests but none positive is rejected with `ERR_NO_POSITIVE_TEST`. On finalization the panel transitions `OPEN → FINALIZED`, its `screening_composite`, `clinical_composite`, and `recommended_tier` are frozen, and no further tests are accepted. A panel must be `FINALIZED` before any immunotherapy plan may reference it.

A patient's panels may be listed, an individual panel fetched with its computed composites, and a panel's tests listed.

### 3.3. Authoring and Activating Immunotherapy Plans

An `Allergist` authors an immunotherapy plan from a finalized panel by supplying the `patient_id` and the `panel_id` of the `FINALIZED` panel that justifies it. A new plan begins in `DRAFT` status. At authoring time the plan's starting concentration is derived from the panel's `recommended_tier`: a `HIGH` tier starts at `GREEN`, a `MODERATE` tier starts at `YELLOW`, and a `LOW` tier starts at `RED`. This value is recorded as `starting_vial_color`, and the plan's `current_vial_color` — the color of the next scheduled dose — is initialized to the same color.

The plan also tracks `current_step_index`, the 1-based position within the active vial color's build-up step list (defaulting to 1); `phase`, an enum that is `BUILD_UP` while the plan climbs the ladder and `MAINTENANCE` once the top dose is reached and held (defaulting to `BUILD_UP`); and `last_dose_volume_ml`, the volume of the most recently released or reaction-resolved administration, which defaults to 0 and serves as the basis for reaction-driven reduction. The plan's `status` field is the enum `DRAFT`, `ACTIVE`, `HELD`, `COMPLETED`, or `DISCONTINUED`. A plan cannot be authored for an `INACTIVE` patient.

Activation moves a plan from `DRAFT` to `ACTIVE`. An `Allergist` activates a plan only when the plan is in `DRAFT` (otherwise `ERR_PLAN_NOT_DRAFT`), the referenced panel is `FINALIZED` (otherwise `ERR_PANEL_NOT_FINALIZED`), the patient is `ACTIVE` (otherwise `ERR_PATIENT_INACTIVE`), and at least one in-use serum vial whose color equals the plan's `starting_vial_color` already exists on this plan (otherwise `ERR_NO_STARTING_VIAL`). On activation the plan's `current_vial_color` is set to its `starting_vial_color`, `current_step_index` is set to 1, `phase` is set to `BUILD_UP`, and the plan's `version` increments by one.

Plans may be fetched individually with their computed ladder position and version, and listed with optional filters on `patient_id`, `panel_id`, and `status`.

### 3.4. Serum Lots and Recalls

A `Pharmacist` registers a manufacturer serum lot by supplying the `vial_color` rung the lot's concentrate serves, a `lot_number`, the `concentrate_potency_pnu_per_ml` (protein-nitrogen units per millilitre at the lot's labeled concentration), and a `received_at_iso` timestamp recording when the lot was received. The standard labeled potency in this domain is 10000 protein-nitrogen units per millilitre. A lot's `status` is the enum `AVAILABLE` or `RECALLED`, beginning at `AVAILABLE`. The `lot_number` must be unique among all lots that are not recalled; registering a lot whose number collides with an existing non-recalled lot is rejected with `ERR_DUPLICATE_LOT_NUMBER`.

Recalling a lot is a terminal, cascading action performed by a `Pharmacist`. The lot must be `AVAILABLE`; recalling a lot that is not available is rejected with `ERR_LOT_NOT_AVAILABLE`. On recall the lot transitions `AVAILABLE → RECALLED` and three cascade hops fire in sequence. First, every in-use serum vial backed by this lot transitions to `DISCARDED`. Second, each such discarded vial's provisional antigen-preparation billing entry is reconciled to its final value on the doses actually drawn from the vial. Third, any immunotherapy plan whose `current_vial_color` is left with no surviving in-use vial is moved from `ACTIVE` to `HELD`. Each entity touched by the cascade has its `updated_at` refreshed and its `version` incremented.

Lots may be fetched individually and listed, with the list filterable by `status` and by `vial_color`.

### 3.5. Mixing Serum Vials

A `Pharmacist` mixes a serum vial onto a plan's board by referencing the backing `lot_id` and supplying the `prepared_volume_ml`, the positive total millilitres drawn into the vial at mixing. The mix request also carries `expected_plan_version` and is rejected on a stale plan version as described in Section 2.6. The vial records its owning `plan_id` and its backing `lot_id`. Its `vial_color` is copied from the backing lot at mix time, and its `dilution_factor` is set from that color per the fixed schedule in Section 2.9. Mixing from a lot that is not `AVAILABLE` is rejected with `ERR_LOT_NOT_AVAILABLE`.

At mixing the system stamps `mixed_at_iso` with the current logical-clock instant and computes the vial's shelf life from its color: a `GREEN` vial lives 30 days, a `YELLOW` vial 90 days, a `RED` vial 180 days, and a `SILVER` vial 365 days, recorded as `shelf_life_days`. The vial's `beyond_use_date_iso` is its `mixed_at_iso` advanced by `shelf_life_days` days; a vial is considered expired once the logical clock is at or after that beyond-use date, inclusive. The vial's `status` is the enum `IN_USE`, `EXHAUSTED`, `EXPIRED`, or `DISCARDED`, beginning at `IN_USE`.

The vial's `remaining_volume_ml` is a derived figure: it is the `prepared_volume_ml` less the sum of administered volumes from all released or reaction-resolved shot visits drawn from this vial. The vial also carries `needs_refill`, a derived boolean that is true exactly when `remaining_volume_ml` is strictly less than 1.0 millilitre.

Mixing a vial posts a provisional antigen-preparation billing charge, described in Section 3.9, and increments the owning plan's `version` by one. Vials may be fetched individually — exposing `remaining_volume_ml` and `needs_refill` — and listed with filters on `plan_id`, `lot_id`, and `status`.

A vial may leave `IN_USE` along three paths, each of which reconciles its provisional preparation charge to final on the doses actually drawn. It becomes `EXHAUSTED` when a dose is attempted but its `remaining_volume_ml` is less than the requested draw; it becomes `EXPIRED` when the logical clock advances to or past its beyond-use date; and it becomes `DISCARDED` when its backing lot is recalled or its owning plan is discontinued.

### 3.6. Administering Shot Visits and the Build-Up Ladder

A `Nurse` administers an injection by creating a shot visit against a plan, referencing the `vial_id` drawn from and optionally supplying `injection_count` — the number of distinct allergen boards injected at the visit, which defaults to 1. The request carries `expected_plan_version` and is subject to the stale-plan-version guard of Section 2.6. The visit records its `plan_id` and `vial_id`, is created directly in `ADMINISTERED` status, and stamps `administered_at_iso` with the current logical-clock instant. The visit `status` is the enum `ADMINISTERED`, `RELEASED`, `REACTION_LOCAL`, or `REACTION_SYSTEMIC`.

Several preconditions guard administration. The plan must be `ACTIVE` — a non-active plan is rejected with `ERR_PLAN_NOT_ACTIVE`, and a held plan specifically with `ERR_PLAN_HELD`. The referenced vial must belong to the same plan named in the path, or the request is rejected with `ERR_VIAL_PLAN_MISMATCH`. The vial must be usable — in use, not expired, and not backed by a recalled lot — or the request is rejected with `ERR_VIAL_NOT_USABLE`. The vial's `remaining_volume_ml` must be at least the scheduled draw volume; if the scheduled draw exceeds what remains, the request is rejected with `ERR_VIAL_INSUFFICIENT_VOLUME` and the vial closes to `EXHAUSTED`. Finally, if the vial's color is `SILVER` — the maintenance concentration — the patient's `epinephrine_on_file` must be true, or the request is rejected with `ERR_EPINEPHRINE_NOT_ON_FILE`.

The dose itself is read off the build-up ladder. Each vial color owns an ordered list of step volumes in millilitres: `GREEN` and `YELLOW` each run `0.10, 0.20, 0.40`; `RED` runs `0.10, 0.20, 0.30, 0.40`; and `SILVER` runs `0.10, 0.20, 0.30, 0.40, 0.50`, where the last `SILVER` step of 0.50 millilitres is the maintenance top dose. The visit's `scheduled_dose_volume_ml` is the entry at position `current_step_index` (1-based) within the list for the plan's `current_vial_color`. The `administered_volume_ml` is the scheduled volume minus any reaction reduction applied at administration (the reduced re-entry dose described in Section 3.8); absent any reduction it equals the scheduled volume. While the plan is in `MAINTENANCE` phase, the scheduled dose is fixed at the maintenance top volume of 0.50 millilitres and the ladder does not advance further.

The visit computes `antigen_units_delivered` as the product of three factors — the `administered_volume_ml`, the vial's `dilution_factor`, and the backing lot's `concentrate_potency_pnu_per_ml` — with the rounding applied once, half-up to two decimal places, only after the full three-way product is formed; the factors are never rounded individually. Administration also debits the vial: `remaining_volume_ml` is provisionally reduced by `administered_volume_ml` and `needs_refill` is recomputed against the 1.0-millilitre threshold. A provisional injection billing charge is posted at the same time (Section 3.9), and the owning plan's `version` increments by one.

The visit's observation requirement is computed as `observation_window_min`. The window is the extended value of 45 minutes whenever the patient's `prior_systemic_reaction` is true or this dose escalated the ladder — that is, when the scheduled step volume is higher than the plan's `last_dose_volume_ml`; otherwise it is the standard value of 30 minutes. The standard window is 30 minutes and the extended window is 45 minutes.

After administration the visit resolves down exactly one of three branches, each terminal.

**Release (no reaction).** A `Nurse` releases the patient by supplying `released_at_iso`, the logical-clock instant of release, and optionally `reaction_grade`. Release is permitted only when the visit is `ADMINISTERED` (otherwise `ERR_VISIT_NOT_ADMINISTERED`) and the recorded grade is `NONE` — sending `LOCAL` or `SYSTEMIC` to release is rejected with `ERR_REACTION_GRADE_MISMATCH`. The release instant must be at least the administration instant plus the full `observation_window_min`; releasing before the window has fully elapsed is rejected with `ERR_OBSERVATION_NOT_ELAPSED`. On release the visit moves `ADMINISTERED → RELEASED`, the plan's `last_dose_volume_ml` is set to the `administered_volume_ml`, and the plan advances one build-up step. Advancing means: if `current_step_index` is below the last index of the current color's step list, it increments by one; otherwise the plan moves to the next color in the order `GREEN → YELLOW → RED → SILVER` and resets `current_step_index` to 1. When the plan is already at the top `SILVER` step and that step is released, the color does not change and the plan's `phase` becomes `MAINTENANCE` (this maintenance promotion bubbles up to the plan).

**Local reaction.** A `Nurse` records a reaction by supplying `reaction_grade` and optionally `epinephrine_administered`. When the grade is `LOCAL`, the visit must be `ADMINISTERED` (otherwise `ERR_VISIT_NOT_ADMINISTERED`) and the grade must indeed be `LOCAL` (otherwise `ERR_REACTION_GRADE_MISMATCH`). On a local reaction the visit moves `ADMINISTERED → REACTION_LOCAL`, the plan's `last_dose_volume_ml` is set to the `administered_volume_ml`, and the plan does not advance — `current_step_index` is left unchanged so the same step repeats on the next visit.

**Systemic reaction.** When the recorded `reaction_grade` is `SYSTEMIC`, the visit must be `ADMINISTERED` (otherwise `ERR_VISIT_NOT_ADMINISTERED`), the grade must be `SYSTEMIC` (otherwise `ERR_REACTION_GRADE_MISMATCH`), and `epinephrine_administered` must be true (otherwise `ERR_EPINEPHRINE_REQUIRED`). A systemic reaction triggers a three-hop cascade: the owning plan moves `ACTIVE → HELD`; this visit's provisional injection billing entry is reversed; and the patient's `prior_systemic_reaction` is set true, permanently widening that patient's future observation windows to the extended value. The plan's `last_dose_volume_ml` is set to the `administered_volume_ml` as the basis for the reduced re-entry dose computed on resume. The visit itself moves `ADMINISTERED → REACTION_SYSTEMIC`.

Shot visits may be fetched individually and listed, filterable by `plan_id`, `vial_id`, and `status`.

### 3.7. Completing and Discontinuing Plans

A held plan freezes therapy: while a plan is `HELD`, no new shot visit may be administered, and an attempt to do so is rejected with `ERR_PLAN_HELD`. An `Allergist` resumes a held plan to bring it back to `ACTIVE`. Resume requires the plan to be `HELD` (otherwise `ERR_PLAN_NOT_HELD`) and the patient's `epinephrine_on_file` to be true (otherwise `ERR_EPINEPHRINE_NOT_ON_FILE`). On resume the plan moves `HELD → ACTIVE`, the reaction-reduction described in Section 3.8 is applied, and the plan's `version` increments by one.

An `Allergist` completes a plan when therapy is finished. Completion requires the plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), the plan's `phase` to be `MAINTENANCE` (otherwise `ERR_NOT_AT_MAINTENANCE`), and no shot visit on the plan to remain in `ADMINISTERED` status (otherwise `ERR_OPEN_VISIT_EXISTS`). On completion the plan moves `ACTIVE → COMPLETED` with no further side effects beyond the version increment.

An `Allergist` discontinues a plan to end therapy early. Discontinuation is permitted only when the plan is `ACTIVE` or `HELD`; attempting it from any other state is rejected with `ERR_PLAN_NOT_DISCONTINUABLE`. On discontinuation the plan moves to `DISCONTINUED` and a cascade fires: every in-use serum vial on the plan is moved to `DISCARDED`, and each such discard reconciles its provisional antigen-preparation billing entry to final on the doses actually drawn. The plan's `version` increments by one. Both `COMPLETED` and `DISCONTINUED` are terminal plan states.

### 3.8. Reaction-Driven Dose Reduction

The build-up ladder and the reaction-reduction logic are two directions of the same dose subject: build-up escalates step by step, while a reaction reduces. Reduction is applied in two situations and behaves differently in each.

On resuming a plan that was held by a systemic reaction, the system computes the reduced re-entry volume as the plan's `last_dose_volume_ml` multiplied by one minus a 25-percent reduction — that is, 75 percent of the last administered volume — rounded half-up to two decimal places (so a last dose of 0.30 millilitres reduces to 0.23). This reduced volume overrides the ladder lookup for the first visit after resume. In the same step the ladder is moved back one rung: if `current_step_index` is greater than 1, it decreases by one; otherwise the plan steps its `current_vial_color` down one rung in the order `SILVER → RED → YELLOW → GREEN`, resetting `current_step_index` to 1, with `GREEN` as the floor that cannot be descended below.

On a local reaction, by contrast, no reduction is applied and the ladder does not move: the next visit simply repeats the current step's scheduled dose, because `current_step_index` was left unchanged when the local reaction was recorded.

### 3.9. Billing: Injection Codes and Antigen Preparation

Every billing entry records the `patient_id` it belongs to (denormalized for summary rollup) and carries a `cpt_code` enum, a computed `billed_dose_units` integer, a computed `charge_cents` integer, a `variant` enum that is `PROVISIONAL` or `FINAL`, and a `status` enum that is `POSTED`, `REVERSED`, or `RECONCILED` and begins at `POSTED`. There are two families of charge.

The first family is the per-visit injection code. When a shot visit is administered, the system posts a provisional injection charge whose `visit_id` is the visit and whose `vial_id` is null. The code depends on the visit's `injection_count`: a visit with two or more boards bills `CPT_95117` at a flat 3900 cents, and a visit with a single board bills `CPT_95115` at a flat 2600 cents. For injection codes `billed_dose_units` is 1. If the visit later resolves to a systemic reaction, this injection entry transitions `POSTED → REVERSED`: its `charge_cents` is retained for audit but excluded from the patient's billed total. Reversal applies only to a posted injection-code entry.

The second family is the antigen-preparation code, `CPT_95165`. When a vial is mixed, the system posts a provisional `CPT_95165` entry whose `vial_id` is the vial and whose `visit_id` is null. Its provisional `billed_dose_units` is the `prepared_volume_ml` rounded up to the next whole millilitre (ceiling), capped at a maximum of 10 doses. When the vial later closes — exhausted, expired, or discarded — the entry transitions `POSTED → RECONCILED`: its `billed_dose_units` is recomputed to the final figure, the sum of administered volumes actually drawn from the vial rounded up to the next whole number and capped at 10, its `charge_cents` is recomputed, and its `variant` is set to `FINAL`. Reconciliation applies only to a posted, provisional `CPT_95165` entry. The provisional variant optimistically bills the full board capacity, so a vial discarded early bills fewer doses than provisioned and the difference is credited.

For every billing entry `charge_cents` is `billed_dose_units` multiplied by the relevant unit price, except that the two injection codes are flat charges. The antigen-preparation unit price is 1450 cents per dose; the injection codes are flat at 2600 cents (`CPT_95115`) and 3900 cents (`CPT_95117`).

A billing entry may be fetched individually and entries may be listed, filterable by `visit_id`, `vial_id`, `patient_id`, `status`, and `cpt_code`. A patient billing summary is a computed read that returns the patient's `billed_total_cents` — the sum of `charge_cents` over the patient's billing entries whose status is not `REVERSED` — alongside the `reversed_total_cents` and a per-code breakdown in `by_cpt`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`. All endpoints require the authentication headers of Section 2.1, and access is restricted to the roles listed below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; auto-expires vials past their beyond-use date | Allergist, Pharmacist, Nurse, Biller, FrontDesk |
| POST | `/patients` | Register a patient | FrontDesk, Allergist |
| GET | `/patients/{patientId}` | Fetch a patient | FrontDesk, Allergist, Nurse, Biller, Pharmacist |
| GET | `/patients` | List patients (paginated) | FrontDesk, Allergist, Nurse, Biller, Pharmacist |
| PATCH | `/patients/{patientId}` | Update patient demographics, epinephrine status, or status | FrontDesk, Allergist |
| POST | `/patients/{patientId}/panels` | Open a diagnostic panel for a patient | Allergist |
| GET | `/patients/{id}/panels` | List a patient's diagnostic panels | Allergist, Nurse, FrontDesk |
| GET | `/panels/{panelId}` | Fetch a panel with computed composites | Allergist, Nurse, FrontDesk |
| POST | `/patients/{patientId}/panels/{panelId}/tests` | Add an allergen test to an OPEN panel | Allergist |
| GET | `/panels/{id}/tests` | List tests on a panel | Allergist, Nurse |
| POST | `/patients/{patientId}/panels/{panelId}/finalize` | Finalize a panel; freeze composites and tier | Allergist |
| POST | `/immunotherapy-plans` | Author a DRAFT plan from a FINALIZED panel | Allergist |
| GET | `/immunotherapy-plans/{planId}` | Fetch a plan with ladder position and version | Allergist, Nurse, Pharmacist, Biller, FrontDesk |
| GET | `/immunotherapy-plans` | List plans (filter by patient_id, panel_id, status) | Allergist, Nurse, Pharmacist, Biller, FrontDesk |
| POST | `/immunotherapy-plans/{planId}/activate` | Activate a DRAFT plan once a starting vial exists | Allergist |
| POST | `/immunotherapy-plans/{planId}/resume` | Resume a HELD plan; apply reduced, stepped-back dose | Allergist |
| POST | `/immunotherapy-plans/{planId}/complete` | Complete a plan at maintenance | Allergist |
| POST | `/immunotherapy-plans/{planId}/discontinue` | Discontinue a plan; discard vials and reconcile billing | Allergist |
| POST | `/serum-lots` | Register a manufacturer serum lot | Pharmacist |
| GET | `/serum-lots/{lotId}` | Fetch a lot | Pharmacist, Allergist, Nurse |
| GET | `/serum-lots` | List serum lots (filter by status, vial_color) | Pharmacist, Allergist, Nurse |
| POST | `/serum-lots/{lotId}/recall` | Recall a lot; cascade to vials, billing, plans | Pharmacist |
| POST | `/immunotherapy-plans/{planId}/vials` | Mix a serum vial onto a plan from a lot (OCC-guarded) | Pharmacist |
| GET | `/serum-vials/{vialId}` | Fetch a vial with remaining volume and refill flag | Pharmacist, Nurse, Allergist |
| GET | `/serum-vials` | List vials (filter by plan_id, lot_id, status) | Pharmacist, Nurse, Allergist |
| POST | `/immunotherapy-plans/{planId}/shot-visits` | Administer an injection on an ACTIVE plan (OCC-guarded) | Nurse |
| GET | `/shot-visits/{visitId}` | Fetch a shot visit | Nurse, Allergist, Biller, FrontDesk |
| GET | `/shot-visits` | List shot visits (filter by plan_id, vial_id, status) | Nurse, Allergist, Biller, FrontDesk |
| POST | `/shot-visits/{visitId}/release` | Release a patient after observation; advance ladder | Nurse |
| POST | `/shot-visits/{visitId}/record-reaction` | Record a LOCAL or SYSTEMIC reaction | Nurse |
| GET | `/billing-entries/{entryId}` | Fetch a billing entry | Biller, Allergist |
| GET | `/billing-entries` | List billing entries (filter by visit_id, vial_id, patient_id, status, cpt_code) | Biller, Allergist |
| GET | `/patients/{patientId}/billing-summary` | Computed billing total excluding reversed entries | Biller, Allergist |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_STALE_PLAN_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PANEL_NOT_OPEN` | 409 |
| `ERR_PANEL_EMPTY` | 422 |
| `ERR_NO_POSITIVE_TEST` | 422 |
| `ERR_PANEL_NOT_FINALIZED` | 409 |
| `ERR_PLAN_NOT_DRAFT` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_PLAN_HELD` | 409 |
| `ERR_PLAN_NOT_HELD` | 409 |
| `ERR_NOT_AT_MAINTENANCE` | 409 |
| `ERR_OPEN_VISIT_EXISTS` | 409 |
| `ERR_PLAN_NOT_DISCONTINUABLE` | 409 |
| `ERR_NO_STARTING_VIAL` | 422 |
| `ERR_PATIENT_INACTIVE` | 422 |
| `ERR_LOT_NOT_AVAILABLE` | 409 |
| `ERR_DUPLICATE_LOT_NUMBER` | 409 |
| `ERR_VIAL_NOT_USABLE` | 422 |
| `ERR_VIAL_INSUFFICIENT_VOLUME` | 422 |
| `ERR_VIAL_PLAN_MISMATCH` | 422 |
| `ERR_EPINEPHRINE_NOT_ON_FILE` | 422 |
| `ERR_EPINEPHRINE_REQUIRED` | 422 |
| `ERR_TEST_METHOD_MISMATCH` | 422 |
| `ERR_OBSERVATION_NOT_ELAPSED` | 422 |
| `ERR_REACTION_GRADE_MISMATCH` | 422 |
| `ERR_VISIT_NOT_ADMINISTERED` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
