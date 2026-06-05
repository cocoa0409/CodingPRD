# SNF-MDS API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the **Skilled Nursing Facility (SNF) Minimum Data Set (MDS)** management API. A skilled nursing facility operates at the intersection of clinical care, regulatory compliance, and Medicare reconciliation, and the friction between those three worlds is exactly what this system is built to absorb. A resident does not simply "arrive"; they must clear a Preadmission Screening and Resident Review (PASRR), be linked to a qualifying acute-hospital stay before Medicare Part A will pay, occupy one of a finite number of certified beds, and then be carried through a federally mandated MDS assessment schedule that drives Patient-Driven Payment Model (PDPM) case-mix pricing.

The API governs the full episode-of-care lifecycle: prospective registration, admission and PASRR gating, the MDS assessment schedule and its correction chains, therapy-minute capture, bed-hold leaves of absence, the care-plan review cycle, discharge, and the downstream claim that prices the stay and reconciles an estimate against a finalized chronological total. Layered on top of the per-resident workflow is a facility-level quality program: adverse-event quality measures roll up into a five-star rating that combines health-inspection, staffing, and quality-measure components.

The design goal is fidelity to the real regulatory mechanics — a stale assessment must not silently re-price a claim, an unpaid bed-hold day must drop out of the final amount, and a positive Level I mental-illness indicator must escalate before clearance — while exposing those mechanics through a disciplined, predictable REST contract. Every actor (admissions, MDS coordination, therapy, physician, billing, administration) owns a distinct slice of the workflow, and the system enforces those boundaries strictly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`. A role value that is non-empty but not one of the six recognized roles passes the authentication gate (both headers being present and non-empty) and is then treated as not-permitted for every operation, surfacing as `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly six roles, spelled precisely as follows: `Administrator`, `AdmissionsCoordinator`, `MdsCoordinator`, `Therapist`, `Physician`, and `BillingAnalyst`. These are **peer roles** — none is a superset of another. Each owns a distinct family of resources: `Administrator` configures facilities, PDPM rates, and quality measures; `AdmissionsCoordinator` registers residents, screenings, qualifying stays, admissions, and bed-holds; `MdsCoordinator` owns the MDS assessment lifecycle; `Therapist` logs therapy sessions; `Physician` owns the care-plan lifecycle and PASRR clinical clearance; and `BillingAnalyst` owns the claim lifecycle. Read access is shared more broadly, but write access is tightly scoped to the owning role, as enumerated in §4.

For all six roles, `X-User-Role` carries an **opaque operator identifier**. That is, when `X-User-Role` is `Administrator`, `AdmissionsCoordinator`, `MdsCoordinator`, `Therapist`, `Physician`, or `BillingAnalyst`, the accompanying `X-User-ID` is an opaque identifier that is not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`, and ownership of a resource is never determined by matching `X-User-ID` to a foreign key on that resource. Authorization is determined purely by whether the declared role is permitted for the operation.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip from the start of the result set and defaults to 0. A `limit` below 1 or above 100, a negative `offset`, or a non-integer value supplied for either parameter is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list response includes the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`. The `total_count` reflects the total number of matching resources before pagination is applied, and `has_more` is true when additional resources remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a standard set of system-managed fields. Each such resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. Resources that are mutable additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every modification (and set equal to `created_at` at creation), and a `version` — an integer that begins at 1 on creation and increments by one on every mutation of the resource. The `version` field is the basis for optimistic concurrency control described in §2.6.

Two entities are deliberately lightweight. A `QualifyingStay` carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field, reflecting that the prior acute-hospital stay it records is fixed once captured. Every other entity — `Facility`, `PdpmRate`, `Resident`, `PasrrScreening`, `Admission`, `MdsAssessment`, `TherapyLog`, `CarePlan`, `CarePlanGoal`, `BedHold`, `Claim`, and `QualityMeasure` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

Whenever a resource's stored or derived fields change — including server-driven recomputations such as a `Facility`'s `occupied_bed_count`, an `Admission`'s `covered_day_count`, or a `CarePlan`'s `open_goal_count` — that change is a mutation: the resource's `updated_at` is refreshed and its `version` is incremented. This holds even when the change is a side effect of an operation invoked against a different resource.

### 2.5. Hierarchical Consistency and Nested Retrieval

The entity model is a hybrid hierarchy. `Facility`, `PdpmRate`, `Resident`, `PasrrScreening`, and `QualifyingStay` are roots. An `Admission` is the central episode entity and references a `Resident`, a `Facility`, a `PasrrScreening`, and (for Medicare episodes) a `QualifyingStay`. Hanging off an `Admission` are its `MdsAssessment`, `TherapyLog`, `CarePlan`, `BedHold`, and `Claim` records; a `CarePlanGoal` hangs off a `CarePlan`; and a `QualityMeasure` hangs off a `Facility`.

For any request whose path contains more than one resource identifier, the server validates each identifier from left to right. The first identifier in the path that does not correspond to an existing resource causes immediate rejection with `ERR_NOT_FOUND`; the server does not proceed to evaluate identifiers further right, nor any business rule, until every referenced resource in the path has been confirmed to exist.

State changes propagate down the hierarchy. When a parent transition cascades into children — for example, an `Admission` reaching `DISCHARGED` closing its active care plans, which in turn discontinues their open goals — each affected resource is independently mutated, with its own `updated_at` refresh and `version` increment. These cascades are described in detail within the §3 workflows that trigger them; the governing principle is that the server performs these reconciliations automatically, without requiring a separate client request against each child.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control (OCC), and only these two. In each case the request body must carry an `expected_<parent>_version` field whose value is the client's last observed `version` of the targeted parent resource. The field is **not optional** on these operations.

The first guarded operation is opening a correcting assessment against an existing submitted assessment. The request must include `expected_assessment_version`, carrying the client's last observed `version` of the assessment being corrected. If another writer has advanced that assessment's `version` since the client read it — for instance by already opening a competing correction against it — the value will no longer match the assessment's current `version`, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from building a correction chain onto an assessment whose state it has not actually observed.

The second guarded operation is submitting a finalized claim. The request must include `expected_claim_version`, carrying the client's last observed `version` of the claim. The finalize step legitimately re-prices a claim and, in doing so, advances the claim's `version`; if a submit arrives carrying a stale `expected_claim_version` that no longer matches the claim's current `version`, it is rejected with `ERR_STALE_VERSION` (HTTP 412), ensuring a re-finalized claim is never submitted under an out-of-date amount.

No other endpoint accepts an `expected_<parent>_version` field; endpoints not named here perform no OCC check.

### 2.7. Validation Ordering

When a single request could fail several checks, the checks are evaluated in a fixed priority order, and the first failure is the one reported. The ordering is: first, authentication — both `X-User-Role` and `X-User-ID` must be present, else `ERR_UNAUTHENTICATED`. Second, authorization — the role must be permitted for the operation, else `ERR_FORBIDDEN_ROLE`. Third, existence — every resource referenced in the path must exist (validated left to right in the path), else `ERR_NOT_FOUND`. Fourth, request well-formedness — on write endpoints, the body must contain all required fields with valid types, enums, and ranges, else `ERR_INVALID_REQUEST`. Resources referenced by foreign-key fields in the request body are validated for existence only after the body has passed this well-formedness gate, and their non-existence likewise surfaces as `ERR_NOT_FOUND`. Fifth, state — on a transition endpoint, the target resource must be in a state from which the requested transition is legal, else `ERR_INVALID_STATE`. Only after all five of these structural gates pass does the system evaluate the operation-specific business rules described throughout §3. Within those business rules, the relative orderings noted in the workflows (for example, on admission activation, PASRR clearance is checked before the qualifying-stay requirement, which is checked before bed availability) are themselves significant and must be honored so that the correct error surfaces.

### 2.8. Numeric Precision and Monetary Handling

Monetary amounts are represented and stored as integer cents; the fields `base_rate_cents`, `estimated_amount_cents`, `final_amount_cents`, and `variance_cents` are all whole numbers of cents. Day counts — `midnights_count`, `covered_day_count`, `leave_day_count`, `paid_day_count`, `billed_day_count`, `target_day` — are integers. Therapy minutes (`minutes`, `individual_equivalent_minutes`) are integers. Star and point components (`health_inspection_rating`, `staffing_rating`, `quality_measure_rating`, `overall_star_rating`, `measure_points`) are integers.

PDPM pricing is the one place intermediate arithmetic involves non-integer factors. A `case_mix_index` is carried at up to four decimals, and the per-component case-mix indices and variable per-diem adjustment factors are applied as exact decimals. Rounding is deferred precisely as described in §3's claim-pricing narrative: each day's per-diem amount is rounded to the nearest cent using the round-half-up convention, and the rounded per-day amounts are then summed. Adverse-event rates used for quality scoring (`numerator` divided by `denominator`) are compared against threshold cut points using strict less-than comparisons, as detailed in §3.

### 2.9. Bed Capacity and the Census

A `Facility` is created with a `certified_bed_count` (at least 1). Its `occupied_bed_count` is a computed census: the number of residents whose `status` is either `ADMITTED` or `ON_LEAVE` and whose admission at this facility is itself in a live state — that is, the admission's `status` is `ACTIVE`, `NON_COVERED`, or `DISCHARGE_PLANNED` (a `PENDING` or `DISCHARGED` admission does not contribute). A resident on a bed-hold leave still counts against the census — the bed is held, not freed — which is why the count includes `ON_LEAVE`. Bed availability is enforced at admission activation: a pending admission may only activate while `occupied_bed_count` is strictly less than `certified_bed_count`; otherwise activation is rejected with `ERR_NO_BEDS_AVAILABLE`. The census is recomputed (and the facility mutated) whenever a resident is admitted, discharged, or converted from leave to discharge.

## 3. Business Logic & Workflows

### 3.1. Facility Setup, Rate Configuration, and the Five-Star Program

An `Administrator` stands up the operating environment. Creating a `Facility` requires its legal `name`, a `cms_certification_number` (the CMS certification number, which must be unique across all facilities; a duplicate is rejected with `ERR_INVALID_REQUEST`), and a `certified_bed_count` of at least 1. The two regulatory survey components, `health_inspection_rating` and `staffing_rating`, may be supplied on creation; each is a star value from 1 to 5 and each defaults to 3 when omitted. On creation, `occupied_bed_count` starts at 0, and the two computed star components, `quality_measure_rating` and `overall_star_rating`, are initialized through the five-star scoring baseline described below.

The `Administrator` also seeds the PDPM rate book. Each `PdpmRate` row prices one `component` — one of `PT`, `OT`, `SLP`, `NURSING`, or `NTA` — within a named `case_mix_group` (a group code such as `TA` or `TB`). A rate row carries a `case_mix_index` multiplier (strictly greater than 0, up to four decimals), a `base_rate_cents` federal per-diem base in cents (at least 0), an `effective_from` date (supplied and stored as an ISO 8601 datetime string, validated as such), and an `active` flag that defaults to true and determines whether the row participates in pricing. Rate rows are not deduplicated on creation: more than one row may share the same `component` and `case_mix_group`, and `effective_from` is not consulted during pricing selection — when several active rows match a component and group, the earliest-created active match is the one used.

Quality measurement drives the computed portion of the star rating. The `Administrator` records a `QualityMeasure` data point against a facility, supplying the `measure_code` — one of `FALLS_WITH_INJURY`, `PRESSURE_ULCER`, `ANTIPSYCHOTIC_USE`, or `REHOSPITALIZATION` — together with a `numerator` (count of adverse events in the period, at least 0), a `denominator` (eligible-resident denominator, at least 1), and a `reporting_period` label such as `2026Q1`. Each measure earns `measure_points` on a 1-to-100 scale, where a lower adverse-event rate earns more points. The adverse-event rate for a measure is its `numerator` divided by its `denominator`, and points are assigned by strict less-than threshold bands specific to the measure: for `FALLS_WITH_INJURY`, a rate below 0.01 earns 100, below 0.03 earns 75, below 0.05 earns 50, and anything else earns 25; for `PRESSURE_ULCER`, below 0.02 earns 100, below 0.05 earns 75, below 0.08 earns 50, else 25; for `ANTIPSYCHOTIC_USE`, below 0.10 earns 100, below 0.15 earns 75, below 0.20 earns 50, else 25; and for `REHOSPITALIZATION`, below 0.15 earns 100, below 0.20 earns 75, below 0.25 earns 50, else 25.

Recording a quality measure recomputes the facility's star rating and is therefore a mutation of the facility. The quality-measure total is the sum of the measure points across the four measure codes, taking, for each code, only its latest reporting period — where "latest" is determined by recording order, i.e., the most-recently-created `QualityMeasure` row for that code on this facility, not by parsing or comparing the `reporting_period` label string; any measure code for which the facility has no data point contributes a baseline of 50 points. The quality-measure star component, `quality_measure_rating`, is then assigned from the quality-measure total by these cut points: 5 stars when the total is at least 360, 4 stars when it is from 280 through 359, 3 stars when from 200 through 279, 2 stars when from 120 through 199, and 1 star otherwise. The `overall_star_rating` starts from the `health_inspection_rating`, then adds 1 if the `staffing_rating` is at least 4 and subtracts 1 if it is at most 2, then adds 1 if the `quality_measure_rating` is at least 4 and subtracts 1 if it is at most 2; the result is finally clamped to the range 1 through 5. Requesting a facility's star summary recomputes `quality_measure_rating` and `overall_star_rating` by this same procedure before returning the facility.

### 3.2. Resident Registration, PASRR Screening, and the Qualifying Stay

An `AdmissionsCoordinator` registers a prospective resident by providing the resident's `full_name`, a `medical_record_number` (unique across all residents; a duplicate is rejected with `ERR_INVALID_REQUEST`), a `date_of_birth`, and a `primary_facility_id` naming the facility the resident is registered against (an FK to an existing `Facility`, validated for existence). The `date_of_birth` is supplied and stored as an ISO 8601 datetime string and is validated as such. A newly registered resident begins in the `PROSPECTIVE` `status`; a resident's lifecycle status is one of `PROSPECTIVE`, `ADMITTED`, `ON_LEAVE`, or `DISCHARGED`.

Before a resident can be admitted, a PASRR screening must be on file and cleared. A screening is created against a resident with a `level` — `LEVEL_I` or `LEVEL_II` — and an optional `has_serious_mental_illness_indicator` flag that defaults to false and signals a positive Level I finding for serious mental illness, intellectual disability, or developmental disability that would require a Level II evaluation. A new screening begins in `PENDING`; its `status` is one of `PENDING`, `CLEARED`, `DENIED`, or `ESCALATED`. Resolving a screening carries a `resolution` directive (one of `CLEARED`, `DENIED`, or `ESCALATED`) and an optional `outcome_note` recording the clearance or denial rationale; the resolution drives the screening to `CLEARED`, `DENIED`, or `ESCALATED`, and the supplied `outcome_note`, when present, is stored on the screening. Resolution is legal only from `PENDING`; attempting to resolve a screening that is already `CLEARED`, `DENIED`, or `ESCALATED` is rejected with `ERR_INVALID_STATE`. There is a hard clinical guard here: a `LEVEL_I` screening whose `has_serious_mental_illness_indicator` is true may not be resolved directly to `CLEARED` — such a screening must first escalate to a Level II evaluation — and an attempt to clear it is rejected with `ERR_PASRR_LEVEL_II_REQUIRED`. Both an `AdmissionsCoordinator` and a `Physician` may resolve screenings, reflecting the clinical-clearance role physicians play.

For Medicare Part A coverage, the resident must have a prior qualifying acute-hospital stay. The coordinator records a `QualifyingStay` against the resident with the `hospital_admit_at` and `hospital_discharge_at` datetimes (UTC), where the discharge must be strictly after the admit. The system computes `midnights_count` as the number of calendar-date boundaries crossed between the two datetimes — that is, the UTC calendar date of the discharge minus the UTC calendar date of the admit, expressed in whole days. The stay `qualifies` (a computed boolean) precisely when `midnights_count` is at least 3. A consequence worth noting: if admit and discharge fall on the same UTC calendar date, `midnights_count` is 0 and the stay does not qualify regardless of how many hours elapsed.

### 3.3. Creating and Activating an Admission

The `Admission` is the spine of the episode. An `AdmissionsCoordinator` creates one in `PENDING` by supplying the `resident_id`, the `facility_id`, the `pasrr_screening_id` of the screening that gates this episode, the `payer_source`, and the `admit_at` datetime (UTC), which is day 1 of the PDPM stay. The `payer_source` is one of `MEDICARE_A`, `MEDICAID`, `PRIVATE`, or `MANAGED_CARE`. For non-Medicare payers the prior-stay link is optional, so `qualifying_stay_id` may be supplied or left null (it defaults to null). At creation the admission's `status` is `PENDING`, and `medicare_covered` and `covered_day_count` are initialized. An admission's lifecycle status is one of `PENDING`, `ACTIVE`, `NON_COVERED`, `DISCHARGE_PLANNED`, or `DISCHARGED`, and its `discharge_at` (set on discharge) is null until then.

Activation is the gated transition that brings both the admission and its resident to life, and it admits two outcomes. In all cases the linked screening must be `CLEARED`, or activation is rejected with `ERR_PASRR_NOT_CLEARED`; and the facility must have an open bed (its `occupied_bed_count` strictly below its `certified_bed_count`), or activation is rejected with `ERR_NO_BEDS_AVAILABLE`. These two checks are ordered: PASRR clearance is evaluated first, then the qualifying-stay requirement described next, then bed availability. The activation request carries an optional `allow_non_covered` flag.

The first outcome moves the admission from `PENDING` to `ACTIVE`. This is the normal path: either the payer is not `MEDICARE_A`, or the payer is `MEDICARE_A` and the linked qualifying stay both exists and qualifies. When the payer is `MEDICARE_A` and a qualifying stay is not met — that is, `qualifying_stay_id` is null or the linked stay's `qualifies` is false — and `allow_non_covered` was not set to true, activation is rejected with `ERR_QUALIFYING_STAY_NOT_MET`. On the `ACTIVE` outcome, `medicare_covered` is computed true exactly when the payer is `MEDICARE_A` and the linked qualifying stay's `qualifies` is true; the admission becomes `ACTIVE`, the resident moves from `PROSPECTIVE` to `ADMITTED`, and the facility's `occupied_bed_count` is recomputed.

The second outcome is the deliberate non-covered branch. When the payer is `MEDICARE_A` but the qualifying stay is not met, and the coordinator opts in by setting `allow_non_covered` to true (and PASRR is `CLEARED` and a bed is available), the admission moves from `PENDING` to `NON_COVERED`: `medicare_covered` is set false, the admission status becomes `NON_COVERED`, the resident moves to `ADMITTED`, and the facility census is recomputed. This branch lets a Medicare resident without a qualifying stay still be admitted as a self-pay episode.

### 3.4. The MDS Assessment Schedule and Correction Chains

The MDS assessment is the clinical instrument that drives case-mix pricing, and the `MdsCoordinator` owns its entire lifecycle. An assessment is scheduled against an admission with an `assessment_type` — one of `ADMISSION_5DAY`, `INTERIM_IPA`, or `DISCHARGE` — an `assessment_reference_date` (the ARD, the UTC look-back anchor), and the three clinical inputs that drive case-mix: `pt_function_score` (a Section GG functional score from 0 to 24), `slp_components_count` (a count of SLP components present, from 0 to 3), and `nta_comorbidity_points` (an NTA comorbidity score from 0 to 20). A scheduled assessment begins in `SCHEDULED` with its `corrects_assessment_id` left null and a computed `target_day` recording the stay-day the assessment is anchored to (for an `ADMISSION_5DAY`, day 5; for an `INTERIM_IPA` or `DISCHARGE`, which are not anchored to a fixed schedule day, `target_day` is null). An assessment's `status` is one of `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `SUBMITTED`, or `SUPERSEDED`.

Starting an assessment advances it from `SCHEDULED` to `IN_PROGRESS`, and is permitted only while the assessment itself is `SCHEDULED` and the parent admission is in `ACTIVE`, `NON_COVERED`, or `DISCHARGE_PLANNED`; a start attempt where either condition fails is rejected with `ERR_INVALID_STATE` (and the assessment-state gate is evaluated before the parent-admission-state gate). The parent-admission-state check, in turn, precedes both temporal guards. Two temporal guards apply at start. First, the `assessment_reference_date` must fall inside the ARD window for the assessment's type, or the start is rejected with `ERR_ARD_OUT_OF_WINDOW`. The windows are: for `ADMISSION_5DAY`, stay-days 1 through 8 inclusive (counting the admit day as day 1); for `INTERIM_IPA`, any day after the 5-day ARD — i.e., the ARD's 1-based stay-day index (its UTC date minus the admit UTC date plus 1) is strictly greater than 5; and for `DISCHARGE`, the window from two days before the discharge-planned moment through fourteen days after it. The discharge-planned moment is taken from the admission's `discharge_at` when that is set, and otherwise from the admission's current `updated_at` (the moment the admission last transitioned, which for a `DISCHARGE_PLANNED` admission is when planning occurred); the comparison is on UTC calendar dates, so the window is the discharge-planned date minus 2 days through that date plus 14 days, inclusive. Second, the ARD window of the assessment being started must not overlap the ARD window of another non-superseded assessment of the same `assessment_type` for the admission — only one open assessment per type-window is allowed — and because the windows are inclusive-closed, even adjacency at exactly a window boundary counts as a conflict; a violation is rejected with `ERR_ASSESSMENT_WINDOW_CONFLICT`. For conflict detection the per-type window is bounded as: `ADMISSION_5DAY` spans the admit date through the admit date plus 7 days; `INTERIM_IPA` is treated as a single-point window on its own ARD date (so two `INTERIM_IPA` assessments conflict only when their ARD dates coincide); and `DISCHARGE` spans the discharge-planned date minus 2 days through that date plus 14 days. An assessment opened as a correction never conflicts with the very assessment it directly corrects.

Completing an assessment advances it from `IN_PROGRESS` to `COMPLETED` and requires that `pt_function_score`, `slp_components_count`, and `nta_comorbidity_points` are all present. On completion the three case-mix groups are computed. The PT/OT case-mix group, `pt_ot_case_mix_group`, is selected from the function score by bands: a `pt_function_score` from 0 through 5 yields `TA`, from 6 through 9 yields `TB`, from 10 through 23 yields `TC`, and exactly 24 yields `TD`. The SLP case-mix group, `slp_case_mix_group`, is selected by component count: 0 yields `SA`, 1 yields `SB`, 2 yields `SC`, and 3 yields `SF`. The NTA case-mix group, `nta_case_mix_group`, is selected from comorbidity points in tiers: at least 12 yields `NA`, from 9 through 11 yields `NB`, from 6 through 8 yields `NC`, from 3 through 5 yields `ND`, and from 0 through 2 yields `NE`. These group codes carry fixed case-mix indices used later in pricing: for PT/OT, `TA` is 1.53, `TB` is 1.69, `TC` is 1.85, and `TD` is 1.00; for SLP, `SA` is 1.00, `SB` is 1.46, `SC` is 2.13, and `SF` is 2.98; for NTA, `NA` is 3.25, `NB` is 2.53, `NC` is 1.85, `ND` is 1.34, and `NE` is 0.96.

The schedule supports a correction loop. A completed assessment can be reopened back to `IN_PROGRESS`, which clears the three case-mix group fields so they are recomputed on the next completion. Reopening is blocked, however, if any claim driven by this assessment has reached `FINALIZED`, `SUBMITTED`, or `PAID` — in that case the assessment is locked and the reopen is rejected with `ERR_ASSESSMENT_LOCKED_BY_CLAIM`. From `COMPLETED`, an assessment may instead be submitted, advancing it to `SUBMITTED`; if that assessment carries a non-null `corrects_assessment_id`, the assessment it corrects is moved to `SUPERSEDED` at the moment of submission, completing the modification chain.

A formal correction creates a new assessment that supersedes an existing submitted one. Opening a correction targets a `SUBMITTED` assessment and is rejected with `ERR_INVALID_STATE` if the target is not `SUBMITTED`. The correction request supplies a fresh `assessment_type`, `assessment_reference_date`, `pt_function_score`, `slp_components_count`, and `nta_comorbidity_points`, plus the `expected_assessment_version` OCC field described in §2.6. A successful correction creates a new `SCHEDULED` assessment under the same admission — carrying that admission's `admission_id` — whose `corrects_assessment_id` points at the target, and it increments the corrected assessment's `version` by one. Assessments may be listed and filtered by their `admission_id`, by their `corrects_assessment_id` (to walk a correction chain), or by `status`. As specified in §2.6, if `expected_assessment_version` does not match the target's current `version`, the correction is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 3.5. Therapy Capture and the Group/Concurrent Cap

A `Therapist` logs each therapy session against an admission as a `TherapyLog` with a `discipline` (`PT`, `OT`, or `SLP`), a `mode` (`INDIVIDUAL`, `CONCURRENT`, or `GROUP`), the raw `minutes` delivered (at least 1), and a `session_date` (UTC). A session may only be logged while its `session_date` falls within the admission's stay window — on or after the admission's `admit_at` and not in the future — and while the admission is in `ACTIVE`, `NON_COVERED`, or `DISCHARGE_PLANNED`; a session outside the stay window or against an admission in a therapy-ineligible state is rejected with `ERR_THERAPY_OUT_OF_STAY`.

Each logged session is weighted toward an individual-equivalent measure on capture. The `individual_equivalent_minutes` for a row equal its raw `minutes` when the `mode` is `INDIVIDUAL`, the raw minutes divided by 2 and rounded down to a whole number when the mode is `CONCURRENT`, and the raw minutes divided by 4 and rounded down to a whole number when the mode is `GROUP`.

The therapy summary, requested for a single `discipline` supplied as a query parameter that must be present and one of `PT`, `OT`, or `SLP` (otherwise the request is rejected with `ERR_INVALID_REQUEST`), aggregates that discipline's sessions over the stay and reports a small computed object — itself returned as the `data` payload, not as a persisted resource — containing the `discipline`, the `total_raw` (the sum of raw `minutes` across the discipline's sessions), the `total_individual_equiv` (the sum of `individual_equivalent_minutes`), the `group_concurrent_pct`, and the `exceeds_group_cap` flag. The `group_concurrent_pct` is the sum of raw minutes from sessions whose mode is `GROUP` or `CONCURRENT` divided by `total_raw` (or 0 when `total_raw` is 0), and is reported as a JSON floating-point number (not a string or a rounded percentage). The `exceeds_group_cap` flag is true precisely when that percentage is strictly greater than 0.25 — i.e., when more than a quarter of delivered minutes came from group or concurrent sessions. One subtlety governs which rows the summary counts: any session whose `session_date` falls inside a bed-hold leave window — whether that bed-hold is currently `OPEN` or already `CLOSED` — is excluded from the summary aggregation.

### 3.6. Bed-Hold Leaves of Absence

When an admitted resident temporarily leaves the facility, the `AdmissionsCoordinator` opens a bed-hold against the active admission. The request supplies a `leave_reason` (`HOSPITAL`, `THERAPEUTIC`, or `OTHER`), a `leave_start_at` (UTC, the inclusive start of the leave window), and an `expected_return_at` (UTC, the exclusive end of the window), where the expected return must be strictly after the leave start. A bed-hold may only be opened while the admission is `ACTIVE` and while no other bed-hold for that admission is currently `OPEN`; an attempt while the admission is not `ACTIVE` or while another hold is already open is rejected with `ERR_BEDHOLD_ALREADY_OPEN`. Additionally, the new leave window, treated as the half-open interval from `leave_start_at` (inclusive) to `expected_return_at` (exclusive), must not overlap any existing bed-hold window for the same admission; touching endpoints are permitted (an end exactly equal to a start is not an overlap), but a true overlap is rejected with `ERR_BEDHOLD_OVERLAP`.

Opening a bed-hold creates a `BedHold` in `OPEN` status and moves the resident from `ADMITTED` to `ON_LEAVE`; the bed remains held, so the facility census is unchanged. A bed-hold's `status` is one of `OPEN`, `CLOSED`, or `CONVERTED_TO_DISCHARGE`. On creation the system provisionally computes the leave's day counts. The `leave_day_count` is the number of midnights occupied by the leave window — the UTC calendar date of the window end minus the UTC calendar date of `leave_start_at`, in whole days, treating the interval as half-open. While the hold is open the window end is the `expected_return_at`; on close it is recomputed against the `actual_return_at`. The `paid_day_count` is the subset of leave days the payer credits: it is the lesser of `leave_day_count` and the payer's paid bed-hold cap, where the caps are 10 days for `MEDICAID`, 0 days for `MEDICARE_A`, 7 days for `MANAGED_CARE`, and 30 days for `PRIVATE`. Because the Medicare cap is 0, every leave day on a Medicare-A admission is unpaid. The unpaid portion of a leave is the `leave_day_count` minus the `paid_day_count`.

Closing a bed-hold carries a `return_outcome` (one of `RETURNED` or `DID_NOT_RETURN`) and an `actual_return_at`. When the outcome is `RETURNED`, the `actual_return_at` is required (a `RETURNED` close that omits it is rejected with `ERR_INVALID_REQUEST`); when the outcome is `DID_NOT_RETURN`, the `actual_return_at` is ignored. When the outcome is `RETURNED`, the bed-hold moves from `OPEN` to `CLOSED`: the `actual_return_at` is set (it must be strictly after `leave_start_at`, else `ERR_INVALID_REQUEST`), and `leave_day_count` and `paid_day_count` are recomputed against the actual return; the resident moves from `ON_LEAVE` back to `ADMITTED`; and the admission's `covered_day_count` is reduced by the leave's unpaid portion (its `leave_day_count` minus its `paid_day_count`). When the outcome is `DID_NOT_RETURN`, the bed-hold moves from `OPEN` to `CONVERTED_TO_DISCHARGE` and the leave converts into a discharge: the resident moves to `DISCHARGED`; the admission moves to `DISCHARGED` with its `discharge_at` set to the bed-hold's `leave_start_at`; every care plan for that admission that is `ACTIVE` is closed to `CLOSED`, and every goal under those plans that is `OPEN` or `IN_PROGRESS` is moved to `DISCONTINUED`; and the facility census is recomputed downward by one. This did-not-return path is therefore a three-level cascade: the bed-hold conversion discharges the admission, which closes care plans, which discontinues goals.

### 3.7. The Care-Plan Review Cycle

A care plan organizes the resident's clinical goals and runs on a recurring review cadence. Both a `Physician` and an `MdsCoordinator` may create a draft `CarePlan` against an admission; the only input is an optional `review_interval_days`, the required number of days between reviews, which defaults to 90 and must be at least 1. A new plan begins in `DRAFT` with `open_goal_count` initialized to 0 and `last_reviewed_at` null. A care plan's `status` is one of `DRAFT`, `ACTIVE`, `UNDER_REVIEW`, or `CLOSED`. Goals are added under a plan with a `description` and a `target_date`; a new `CarePlanGoal` begins `OPEN`, carries the `care_plan_id` of its parent plan, and a goal's `status` is one of `OPEN`, `IN_PROGRESS`, `MET`, or `DISCONTINUED`. Listing the goals under a plan returns those whose `care_plan_id` is that plan. The plan's `open_goal_count` — the number of goals under it whose status is `OPEN` or `IN_PROGRESS` — is recomputed whenever a goal is added or its status is changed. A goal's status may be updated directly to any of `OPEN`, `IN_PROGRESS`, `MET`, or `DISCONTINUED` via a `status` field in the request body, with no from-state restriction on the transition; doing so recomputes the parent plan's `open_goal_count`.

A `Physician` drives the plan lifecycle. Activating a plan moves it from `DRAFT` to `ACTIVE`, but only when the plan is `DRAFT`, the parent admission is `ACTIVE` or `NON_COVERED`, and the plan has at least one goal that is `OPEN` (its `open_goal_count` is at least 1). A plan that is not `DRAFT`, or whose parent admission is in neither `ACTIVE` nor `NON_COVERED`, is rejected with `ERR_INVALID_STATE`; these two state checks are evaluated (plan-state first, then parent-admission-state) before the open-goal check, and an activation attempt that clears them but has no open goal is rejected with `ERR_GOAL_REQUIRED`. On activation, `last_reviewed_at` is set to the moment of the request. From `ACTIVE`, beginning a review moves the plan to `UNDER_REVIEW`; completing that review moves it back to `ACTIVE` and again sets `last_reviewed_at` to the moment of the request — this is the recurring review loop. From `ACTIVE`, a plan may also be closed to `CLOSED`, which cascades to every goal under it that is `OPEN` or `IN_PROGRESS`, moving each to `DISCONTINUED`. A plan may also be closed as a side effect of the admission's discharge, with the same goal cascade.

### 3.8. Discharge

Discharge is a two-step ritual. First, the `AdmissionsCoordinator` plans the discharge, moving the admission from `ACTIVE` (or from `NON_COVERED`) to `DISCHARGE_PLANNED`. Planning requires that the admission have at least one `ACTIVE` care plan, or it is rejected with `ERR_NO_ACTIVE_CARE_PLAN`; for an `ACTIVE` admission it additionally requires that no bed-hold for the admission is currently `OPEN`, and a violation of this requirement is rejected with `ERR_INVALID_STATE`. The active-care-plan requirement is checked before the open-bed-hold requirement. As a side effect of planning, every `DISCHARGE`-type assessment for the admission that is still `SCHEDULED` is moved to `IN_PROGRESS`, surfacing the discharge assessment work that must be finished before the resident can leave.

Second, the coordinator executes the discharge, moving the admission from `DISCHARGE_PLANNED` to `DISCHARGED` with the supplied `discharge_at`. Execution requires that every `DISCHARGE`-type assessment for the admission be `SUBMITTED` — an incomplete discharge assessment is rejected with `ERR_DISCHARGE_ASSESSMENT_INCOMPLETE` — and that every care plan for the admission be either `ACTIVE` or `CLOSED`, and the resident be `ADMITTED` rather than `ON_LEAVE`; a care plan in any other state, or a resident still `ON_LEAVE`, is rejected with `ERR_INVALID_STATE`. The discharge-assessment requirement is checked first, then the care-plan-state requirement, then the resident-not-on-leave requirement. On discharge the admission's `status` becomes `DISCHARGED` and its `discharge_at` is set, the resident moves to `DISCHARGED`, the facility census is recomputed downward, and a depth-three cascade fires: every `ACTIVE` care plan for the admission is closed to `CLOSED`, and every `OPEN` or `IN_PROGRESS` goal under those plans is moved to `DISCONTINUED`. There is also the alternate discharge path described in §3.6, where a bed-hold closing as did-not-return converts directly into a discharge with the same downstream cascade.

### 3.9. Claim Pricing, Reconciliation, and Adjudication

A `BillingAnalyst` prices the stay through a `Claim`, and the claim lifecycle is where the estimate-versus-final reconciliation lives. A draft claim is created against an admission with a `driving_assessment_id` (the submitted assessment whose case-mix groups price the claim), a `period_start_at`, and a `period_end_at` (both UTC, inclusive endpoints of the claim period). The driving assessment must belong to the same admission and be `SUBMITTED`, or creation is rejected with `ERR_ASSESSMENT_NOT_SUBMITTED`. The claim period must lie within the stay window — from the admission's `admit_at` through its `discharge_at` (or the present moment if not yet discharged) — and the period end must be on or after the period start; a malformed period is rejected with `ERR_CLAIM_PERIOD_INVALID`. A new claim begins in `DRAFT` with `billed_day_count`, `estimated_amount_cents`, and `final_amount_cents` initialized to 0. A claim's `status` is one of `DRAFT`, `ESTIMATED`, `FINALIZED`, `SUBMITTED`, `PAID`, or `REJECTED`, and it also carries a `variance_cents` reconciliation delta.

Per-day pricing is the engine underneath both the estimate and the final. For a given covered day, the day's unrounded rate is the sum across the five components `PT`, `OT`, `SLP`, `NTA`, and `NURSING` of each component's day amount, computed in a pinned order: first resolve each component's adjusted rate, then sum the components, then apply the day-index adjustment, then round. For each component, the active `PdpmRate` row is selected by component and by the case-mix group taken from the driving assessment — SLP, PT, and NTA use the assessment's resolved groups, OT reuses the PT group code, and NURSING uses a flat case-mix group coded `NURS`. That row's `base_rate_cents` multiplied by its `case_mix_index` gives the component base, and the component's day amount is the component base multiplied by a variable adjustment factor that depends on the component and the 1-based `stay_day_index` of the day within the stay. If no active rate row matches a component and its resolved group, that component simply contributes zero to the day's amount rather than failing the pricing. The variable adjustment works as follows: for `PT` and `OT`, the factor is 1.00 for stay-days 1 through 20, then steps down by 0.02 for each 7-day block beginning at day 21 (days 21 through 27 use 0.98, days 28 through 34 use 0.96, and so on); for `NTA`, the factor is 3.00 for stay-days 1 through 3 and 1.00 thereafter; and for `SLP` and `NURSING`, the factor is 1.00 for every day. The stay-day index for a calendar day is that day's UTC date minus the admission's `admit_at` UTC date, in whole days, plus 1.

The claim total rounds per day and then sums: for each billed covered day, the day's unrounded per-diem rate is rounded to the nearest cent using round-half-up, and those rounded per-day amounts are summed — never sum-then-round. Estimating a draft claim moves it from `DRAFT` to `ESTIMATED` and writes `estimated_amount_cents` using the forward-looking variant, in which the billed day set is every calendar day in the inclusive period projected as fully covered, with no bed-hold deductions; it also computes `billed_day_count`. Estimating requires that the driving assessment still be `SUBMITTED` (else `ERR_ASSESSMENT_NOT_SUBMITTED`) and that the parent admission's `medicare_covered` be true (else `ERR_NOT_MEDICARE_COVERED`); the driving-assessment-submitted check is evaluated before the medicare-covered check.

Finalizing an estimated claim moves it from `ESTIMATED` to `FINALIZED` and writes `final_amount_cents` using the chronological variant, in which the billed day set is the calendar days in the inclusive period minus any day that falls inside a closed or converted bed-hold's leave window beyond that hold's `paid_day_count` — that is, the unpaid bed-hold days are removed — with the same per-day pricing and rounding. For each `CLOSED` or `CONVERTED_TO_DISCHARGE` bed-hold, its midnight-days within `[leave_start_at, window-end)` are enumerated chronologically, the first `paid_day_count` of them count as paid, and the remaining (later) midnight-days are the unpaid days removed from the billed set. Finalizing also re-writes `billed_day_count` to the size of this final billed day set (so a finalize that removes unpaid days lowers `billed_day_count` below the estimate's count). The `variance_cents` is then set to the `final_amount_cents` minus the `estimated_amount_cents`; the two amounts diverge precisely when an unpaid bed-hold day overlaps the period. Finalizing is blocked while any bed-hold for the admission is still `OPEN` and overlaps the claim period (treating the period as the inclusive `[period_start_at, period_end_at]` and the hold window as `[leave_start_at, expected/actual return)`); such a block is rejected with `ERR_INVALID_STATE`.

Submitting a finalized claim moves it from `FINALIZED` to `SUBMITTED` and increments the claim's `version` by one; it requires the `expected_claim_version` OCC field, and a mismatch with the claim's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), as detailed in §2.6. Finally, a submitted claim is adjudicated with a `decision`, forking the outcome. When the decision is `PAID`, the claim moves to `PAID` and the admission's `covered_day_count` is increased by the claim's `billed_day_count`. When the decision is `REJECTED`, the claim moves to `REJECTED`, the driving assessment is left unchanged, and there is no change to `covered_day_count`. These two branches are otherwise symmetric — same precondition that the claim be `SUBMITTED` — but diverge entirely in their effect on the covered-day ledger.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that fetch a resource, list a collection, or drive a state transition on an existing resource return a `200 OK` status code. A request to a path that matches no defined route, or to a defined path with an HTTP method that path does not support, is answered with `ERR_NOT_FOUND` (HTTP 404); there is no distinct method-not-allowed error.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/snf/facilities` | Create a facility | Administrator |
| GET | `/snf/facilities/{id}` | Fetch a facility | Administrator, AdmissionsCoordinator, MdsCoordinator, BillingAnalyst, Physician, Therapist |
| GET | `/snf/facilities/{id}/star-summary` | Computed five-star summary for the facility | Administrator, BillingAnalyst |
| POST | `/snf/facilities/{id}/quality-measures` | Record a quality-measure data point | Administrator |
| GET | `/snf/facilities/{id}/quality-measures` | List quality measures for the facility | Administrator, BillingAnalyst |
| POST | `/snf/pdpm-rates` | Create a PDPM rate configuration row | Administrator |
| GET | `/snf/pdpm-rates` | List PDPM rate rows | Administrator, BillingAnalyst |
| POST | `/snf/residents` | Register a prospective resident | AdmissionsCoordinator |
| GET | `/snf/residents/{id}` | Fetch a resident | AdmissionsCoordinator, MdsCoordinator, Physician, BillingAnalyst, Therapist |
| GET | `/snf/residents` | List residents | AdmissionsCoordinator, MdsCoordinator |
| POST | `/snf/residents/{id}/qualifying-stays` | Record a prior acute-hospital qualifying stay | AdmissionsCoordinator |
| GET | `/snf/qualifying-stays/{id}` | Fetch a qualifying stay | AdmissionsCoordinator, BillingAnalyst |
| GET | `/snf/qualifying-stays` | List qualifying stays | AdmissionsCoordinator, BillingAnalyst |
| POST | `/snf/residents/{id}/pasrr-screenings` | Create a PASRR screening for a resident | AdmissionsCoordinator |
| POST | `/snf/pasrr-screenings/{id}/resolve` | Resolve a PASRR screening | AdmissionsCoordinator, Physician |
| GET | `/snf/pasrr-screenings/{id}` | Fetch a PASRR screening | AdmissionsCoordinator, Physician |
| GET | `/snf/pasrr-screenings` | List PASRR screenings | AdmissionsCoordinator, Physician |
| POST | `/snf/admissions` | Create a pending admission episode | AdmissionsCoordinator |
| GET | `/snf/admissions/{id}` | Fetch an admission | AdmissionsCoordinator, MdsCoordinator, BillingAnalyst, Physician, Therapist |
| GET | `/snf/admissions` | List admissions | AdmissionsCoordinator, BillingAnalyst |
| POST | `/snf/admissions/{id}/activate` | Activate a pending admission (ACTIVE or NON_COVERED) | AdmissionsCoordinator |
| POST | `/snf/admissions/{id}/plan-discharge` | Move admission to DISCHARGE_PLANNED | AdmissionsCoordinator |
| POST | `/snf/admissions/{id}/discharge` | Discharge a planned admission | AdmissionsCoordinator |
| POST | `/snf/admissions/{id}/assessments` | Schedule an original MDS assessment | MdsCoordinator |
| GET | `/snf/admissions/{id}/assessments` | List MDS assessments for an admission | MdsCoordinator, BillingAnalyst |
| POST | `/snf/admissions/{id}/bed-holds` | Open a bed-hold leave on an active admission | AdmissionsCoordinator |
| GET | `/snf/admissions/{id}/bed-holds` | List bed-holds for an admission | AdmissionsCoordinator, BillingAnalyst |
| POST | `/snf/admissions/{id}/therapy-logs` | Log a therapy session for an admission | Therapist |
| GET | `/snf/admissions/{id}/therapy-logs` | List therapy logs for an admission | Therapist, MdsCoordinator, BillingAnalyst |
| GET | `/snf/admissions/{id}/therapy-summary` | Computed therapy-minutes summary | Therapist, MdsCoordinator |
| POST | `/snf/admissions/{id}/claims` | Create a draft claim for an admission period | BillingAnalyst |
| GET | `/snf/admissions/{id}/claims` | List claims for an admission | BillingAnalyst |
| POST | `/snf/admissions/{id}/care-plans` | Create a draft care plan for an admission | Physician, MdsCoordinator |
| GET | `/snf/admissions/{id}/care-plans` | List care plans for an admission | Physician, MdsCoordinator |
| GET | `/snf/assessments/{id}` | Fetch an MDS assessment | MdsCoordinator, BillingAnalyst |
| GET | `/snf/assessments` | List MDS assessments | MdsCoordinator, BillingAnalyst |
| POST | `/snf/assessments/{id}/start` | Start an MDS assessment (validates ARD window) | MdsCoordinator |
| POST | `/snf/assessments/{id}/complete` | Complete an MDS assessment (computes case-mix groups) | MdsCoordinator |
| POST | `/snf/assessments/{id}/reopen` | Reopen a completed assessment for correction | MdsCoordinator |
| POST | `/snf/assessments/{id}/submit` | Submit a completed assessment | MdsCoordinator |
| POST | `/snf/assessments/{id}/correct` | Open a correcting MDS assessment (OCC on corrected version) | MdsCoordinator |
| GET | `/snf/care-plans/{id}` | Fetch a care plan | Physician, MdsCoordinator |
| POST | `/snf/care-plans/{id}/goals` | Add a goal to a care plan | Physician, MdsCoordinator |
| GET | `/snf/care-plans/{id}/goals` | List goals under a care plan | Physician, MdsCoordinator |
| POST | `/snf/care-plans/{id}/activate` | Activate a draft care plan | Physician |
| POST | `/snf/care-plans/{id}/begin-review` | Begin a care-plan review | Physician |
| POST | `/snf/care-plans/{id}/complete-review` | Complete a care-plan review | Physician |
| POST | `/snf/care-plans/{id}/close` | Close a care plan | Physician |
| PATCH | `/snf/goals/{id}` | Update a goal's status | Physician, MdsCoordinator |
| GET | `/snf/bed-holds/{id}` | Fetch a bed-hold | AdmissionsCoordinator, BillingAnalyst |
| POST | `/snf/bed-holds/{id}/close` | Close a bed-hold (returned or did-not-return) | AdmissionsCoordinator |
| GET | `/snf/claims/{id}` | Fetch a claim | BillingAnalyst |
| GET | `/snf/claims` | List claims | BillingAnalyst |
| POST | `/snf/claims/{id}/estimate` | Estimate a draft claim | BillingAnalyst |
| POST | `/snf/claims/{id}/finalize` | Finalize an estimated claim | BillingAnalyst |
| POST | `/snf/claims/{id}/submit` | Submit a finalized claim (OCC on claim version) | BillingAnalyst |
| POST | `/snf/claims/{id}/adjudicate` | Adjudicate a submitted claim (PAID or REJECTED) | BillingAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PASRR_NOT_CLEARED` | 409 |
| `ERR_QUALIFYING_STAY_NOT_MET` | 409 |
| `ERR_NO_BEDS_AVAILABLE` | 409 |
| `ERR_ARD_OUT_OF_WINDOW` | 422 |
| `ERR_BEDHOLD_OVERLAP` | 409 |
| `ERR_ASSESSMENT_WINDOW_CONFLICT` | 409 |
| `ERR_THERAPY_OUT_OF_STAY` | 422 |
| `ERR_ASSESSMENT_NOT_SUBMITTED` | 409 |
| `ERR_NOT_MEDICARE_COVERED` | 409 |
| `ERR_CLAIM_PERIOD_INVALID` | 422 |
| `ERR_NO_ACTIVE_CARE_PLAN` | 409 |
| `ERR_DISCHARGE_ASSESSMENT_INCOMPLETE` | 409 |
| `ERR_BEDHOLD_ALREADY_OPEN` | 409 |
| `ERR_ASSESSMENT_LOCKED_BY_CLAIM` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PASRR_LEVEL_II_REQUIRED` | 409 |
| `ERR_GOAL_REQUIRED` | 409 |
