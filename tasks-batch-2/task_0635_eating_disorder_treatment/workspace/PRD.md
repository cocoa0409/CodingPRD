# Eating-Disorder Treatment API — Product Requirements Document

## 1. Introduction

Eating-disorder care is one of the most logistically and clinically demanding services a behavioral-health provider can offer. A single patient typically moves through several distinct levels of care — residential, partial-hospitalization (PHP), intensive-outpatient (IOP), and finally outpatient (OP) — while a multidisciplinary team of therapists, dietitians, and physicians coordinates supervised meals, treatment goals, family work, and insurance authorization in parallel. The Eating-Disorder Treatment API (the "platform") exists to make that coordination auditable and safe: it governs the finite supply of beds and cohort slots, the level-of-care assessment that decides where a patient belongs, the supervised-meal protocol that measures recovery, the insurance authorization and concurrent-review loop that pays for the stay, and the discharge and relapse-prevention plan that ends it.

This document specifies the platform's REST contract. The design treats the program as a quota-allocation system layered over a compliance regime: beds and cohort slots are scarce resources that are reserved, committed, and released as patients are admitted and discharged, while insurance authorization windows and medical-clearance rules gate every admission and step-down. Two independent dimensions evolve on each admission — a clinical lifecycle and an orthogonal level-of-care ladder — and several derived quantities (bed occupancy, nutritional risk, authorized-day balances) must stay continuously reconciled as events fire. Because the platform drives real clinical decisions, every cascade resolves atomically inside the request that triggers it, and stale-data writes are rejected rather than silently merged.

Throughout, time is governed by a **logical UTC clock** rather than wall-clock time. The server starts at `2026-01-01T00:00:00Z`; before any clock-set call, every timestamp the platform stamps reads exactly that default. Administrators advance the clock explicitly, which lets the platform deterministically re-evaluate authorization expiry and day consumption.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply across the entire API. All resource collections are mounted under the `/edt` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The platform recognizes five roles, spelled exactly: `Admin`, `Intake`, `Clinician`, `Dietitian`, and `UtilizationReviewer`. `Admin` operates facilities, programs, cohorts, the logical clock, administrative discharges, and waivers. `Intake` registers patients, creates admissions, and manages bed and cohort placement including waitlist promotion. `Clinician` owns the clinical surface: assessments, treatment plans, medical holds, step-downs, discharges, family-program enrollment, and discharge plans. `Dietitian` owns meal plans, supervised-meal events, and the nutrition discipline sign-off. `UtilizationReviewer` owns authorizations, concurrent-review decisions, appeals, expiry, and billing summaries.

Each of these five roles is an **opaque operator identity**. When `X-User-Role` is `Admin`, `Intake`, `Clinician`, `Dietitian`, or `UtilizationReviewer`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it, but it never compares `X-User-ID` to any entity's `id`, and there are no resource-ownership checks keyed to the caller's identity. Authorization is therefore purely role-based: what matters is whether the declared role is on the operation's permitted list, not which individual operator is acting.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless a specific endpoint states otherwise, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object so the caller can page deterministically.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the platform are full first-class records and carry four system-managed fields: an `id` (a server-minted UUID string with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) marking creation, an `updated_at` timestamp using the same format and refreshed on every mutation, and a `version` integer that begins at 1 and increments by one with each mutation. Facilities, programs, cohorts, patients, assessments, admissions, insurance authorizations, concurrent reviews, treatment plans, meal plans, family-program enrollments, and discharge plans all carry this full set.

One resource is an exception. A **meal event** is an append-only log row: once written it is never modified. A meal event therefore carries only `id` and `created_at`; it has no `updated_at` and no `version` field at all. Callers should not expect either field on a meal-event payload.

All timestamps the platform stamps onto records — including the clinical timestamps described in §3 — are read from the logical UTC clock, never from wall-clock time. The logical clock starts at `2026-01-01T00:00:00Z` and is moved only by an administrative clock-set capability that accepts a target instant in the `to_iso8601` field. Advancing the clock is itself a meaningful business event: it re-evaluates every authorization against its coverage window and may, as described in §3, drive authorizations into `EXPIRED` and cascade their admissions toward discharge.

### 2.5. Optimistic Concurrency Control

Two write operations require an optimistic-concurrency check against a parent record's `version`, and both carry their expected version as a mandatory field in the request body.

Finalizing an assessment is performed against a patient. The request must include `expected_patient_version`, carrying the `version` of the patient that the client last observed. The platform compares it to the patient's current `version`; if another finalize has already superseded the governing assessment and advanced the patient's version since the client read it, the values differ and the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from re-pointing the patient's active assessment based on a stale view of which assessment is in force. This check is evaluated before any state or business logic on the finalize.

Revising an active treatment plan is performed against the plan's admission. The request must include `expected_admission_version`, carrying the `version` of the admission the client last observed. The platform compares it to the admission's current `version`; if a clinical change — a step-down or a treatment-plan revision — has already advanced the admission since the client read it, the values differ and the revise is rejected with `ERR_STALE_VERSION` (HTTP 412). Both these expected-version fields are non-optional on their respective operations; no other endpoint accepts a version field, and endpoints that are not one of these two never perform an OCC check.

### 2.6. Validation Ordering

When several checks guard one operation, they are evaluated in a fixed priority order so that the most fundamental failure always surfaces first. The order is: (1) the user-context header check, yielding `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) the role-permission check, yielding `ERR_UNAUTHORIZED`; (3) existence of the resources named in the path, yielding the resource-specific not-found error; (4) existence of every foreign key referenced in the request body — `facility_id`, `patient_id`, `program_id`, `cohort_id`, `admission_id`, `authorization_id`, and `meal_plan_id` — again yielding the resource-specific not-found error; (5) the optimistic-concurrency check on `expected_patient_version` or `expected_admission_version` where supplied, yielding `ERR_STALE_VERSION`; (6) the legal-state check that the target resource is in a state from which the requested transition is allowed, yielding `ERR_INVALID_STATE`; then (7) and beyond, the business rules specific to the operation, evaluated in the order their workflows describe. Field-level request validation — enum membership, numeric ranges, non-empty strings, and the rule that a review's `window_end_iso` must be strictly after its `window_start_iso` — is applied to create and update endpoints; a malformed body yields `ERR_INVALID_REQUEST` (HTTP 400), and a missing or inverted review window specifically yields `ERR_INVALID_WINDOW` (HTTP 400). The admit operation, which carries the densest stack of business rules, is described end-to-end in §3 with its checks called out in their evaluation order.

### 2.7. Nested Resource Retrieval and Foreign-Key Reachability

The entity model is flat: collections are top-level under `/edt` and entities reference one another by foreign key carried in request bodies rather than by nesting in URL paths. When a path does name a resource by id, that id is validated for existence first, and a miss returns the resource-specific not-found error before any other processing. The resource-specific not-found errors are: `ERR_FACILITY_NOT_FOUND` for a facility, `ERR_PROGRAM_NOT_FOUND` for a program, `ERR_COHORT_NOT_FOUND` for a cohort, `ERR_PATIENT_NOT_FOUND` for a patient, `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_ADMISSION_NOT_FOUND` for an admission, `ERR_AUTHORIZATION_NOT_FOUND` for an insurance authorization, `ERR_REVIEW_NOT_FOUND` for a concurrent review, `ERR_TREATMENT_PLAN_NOT_FOUND` for a treatment plan, `ERR_MEAL_PLAN_NOT_FOUND` for a meal plan, `ERR_MEAL_EVENT_NOT_FOUND` for a meal event, `ERR_FAMILY_PROGRAM_NOT_FOUND` for a family-program enrollment, and `ERR_DISCHARGE_PLAN_NOT_FOUND` for a discharge plan. These same errors are returned when a foreign key carried in a create body — `facility_id`, `patient_id`, `program_id`, `cohort_id`, `admission_id`, `authorization_id`, or `meal_plan_id` — points at a record that does not exist. Because relationships are not expressed as nested paths, a parent's children are discovered by filtering the relevant list endpoint on a foreign-key query parameter — for example, the assessments governing a patient are found by listing assessments filtered by `patient_id`, and the programs in a facility by listing programs filtered by `facility_id`. The supported filters are described alongside each list endpoint in §4.

### 2.8. Bed Occupancy, Cohort Slots, and Capacity Postures

A program's bed accounting is derived, never directly written. A program is created with a fixed `bed_capacity` (which must be at least 1) representing physical beds for residential and PHP programs or virtual slots for IOP and OP. The platform maintains `beds_occupied` as the count of admissions occupying a bed in that program — that is, admissions whose `clinical_status` is `ADMITTED`, `MEDICAL_HOLD`, or `DISCHARGE_PENDING`. From these two it derives `beds_available` as the bed capacity minus the occupied count, floored at zero so it never goes negative. It also derives `occupancy_posture`: the posture is `FULL` when the occupied count is greater than or equal to the bed capacity, and `OPEN` otherwise. These three derived values are recomputed every time an admission enters or leaves a bed-occupying state.

A program also carries an operational `status` of `OPEN` or `CLOSED`; a `CLOSED` program rejects new promotions and admissions. Cohorts apply the same pattern at finer grain: a cohort is created with a `slot_capacity` (at least 1) and the platform maintains `slots_filled` as the count of admissions assigned to that cohort whose `clinical_status` is `ADMITTED`, `MEDICAL_HOLD`, or `DISCHARGE_PENDING`.

### 2.9. Precision, Rounding, and Boundary Conventions

Unless a calculation states otherwise, computed numeric values are rounded to two decimal places using the round-half-up convention. The meal-compliance rate is the single exception: it is carried to four decimal places, round-half-up. Patient-responsibility currency is computed in whole integer cents with round-half-up, and authorized-day quantities are whole integers computed with a per-window floor. Every threshold in the platform is an inclusive lower bound: a value "meets" a threshold when it is greater than or equal to it. This applies uniformly — the occupancy `FULL` boundary, the level-of-care assignment thresholds, the medical-stability posture thresholds, the meal-compliance floor, and the step-down readiness threshold all treat the boundary value itself as satisfying the condition.

## 3. Business Logic & Workflows

### 3.1. Facilities, Programs, and Cohorts: the Physical Substrate

Every clinical record ultimately hangs off a **facility**, created by an `Admin` with a `name` and an optional `timezone` label that defaults to `UTC`. The timezone is purely a display label; all clock math uses the logical UTC clock regardless of what is stored here.

Within a facility an `Admin` defines one or more **programs**, each created with a `facility_id`, a `level_of_care`, and a `bed_capacity`. The `level_of_care` is one of `RESIDENTIAL`, `PHP`, `IOP`, or `OP`. On creation a program starts with no beds occupied, all beds available, an `OPEN` occupancy posture, and an `OPEN` operational `status`. An `Admin` can later close a program to new intake, which moves its `status` to `CLOSED`; the derived bed counters are untouched by closing.

**Cohorts** subdivide a program into age-banded groups. Either an `Admin` or `Intake` creates a cohort with a `program_id`, a `facility_id`, a human-readable `name` (for example, "Adolescent AM"), an `age_band` of either `ADOLESCENT` or `ADULT`, and a `slot_capacity`. A new cohort begins with `slots_filled` at zero. The age band matters at admission time, where a patient may only be admitted into a cohort whose age band matches their own.

### 3.2. Patients and the Level-of-Care Assessment

`Intake` (or an `Admin`) registers a **patient** with a `facility_id`, a `full_name`, an `age_band` of `ADOLESCENT` or `ADULT`, and an intake `bmi` (a positive number). A freshly registered patient starts `STABLE`, with `version` at 1 and both nutritional-risk figures at zero. The patient also carries a computed `medical_stability_posture` (one of `STABLE`, `GUARDED`, or `UNSTABLE`), a reconciled `nutritional_risk_score`, a frozen `provisional_nutritional_risk_score`, and an `active_assessment_id` pointer that stays null until the first assessment is finalized. That pointer is a denormalized convenience holding the id of the single `FINALIZED` assessment currently governing the patient; the assessment itself is always discoverable by listing assessments filtered on the patient.

A `Clinician` opens a level-of-care **assessment** in `DRAFT` against a patient, supplying a `patient_id`, a `facility_id`, and four clinical ratings each on a 0-to-10 scale: `medical_severity` (vitals, electrolytes, bradycardia), `behavioral_severity` (purge-restrict behaviors), `psychiatric_severity` (comorbid suicidality, OCD), and `motivation_level` (insight, where more motivation reduces required intensity). At creation the platform computes a `composite_score` and a `recommended_level_of_care`.

The composite score is a weighted blend on a 0-to-100 scale. Each of the four ratings is first scaled to a 0-to-100 footing by multiplying it by ten. The medical contribution is forty percent of its scaled value, the behavioral contribution is thirty percent of its scaled value, and the psychiatric contribution is twenty percent of its scaled value; the motivation contribution is subtracted, at ten percent of its scaled value. In other words, take 0.40 times the medical rating scaled, plus 0.30 times the behavioral rating scaled, plus 0.20 times the psychiatric rating scaled, then subtract 0.10 times the motivation rating scaled. That sum is rounded half-up to two decimal places and then clamped to lie within 0 and 100 inclusive. The `recommended_level_of_care` reads off the clamped composite against three inclusive thresholds: `RESIDENTIAL` when the composite is at least 70; `PHP` when it is at least 50 but below 70; `IOP` when it is at least 30 but below 50; and `OP` when it is below 30.

An assessment is `DRAFT`, `FINALIZED`, or `SUPERSEDED`. Finalizing — described next — is the act that puts an assessment in force.

### 3.3. Finalizing an Assessment and Seeding Nutritional Risk

A `Clinician` finalizes a `DRAFT` assessment, which is legal only from `DRAFT`; finalizing anything else is rejected with `ERR_INVALID_STATE`. The finalize carries `expected_patient_version` and is subject to the optimistic-concurrency rule of §2.5. When it succeeds, several effects resolve atomically. If the patient already had an active assessment, that prior assessment moves to `SUPERSEDED`, and the patient's `active_assessment_id` is re-pointed to the assessment just finalized. The patient's nutritional risk is seeded from the **provisional** variant, and the patient's `version` increments by one.

The provisional nutritional-risk score is a fixed admission-time estimate derived from the now-governing assessment's `composite_score` plus a body-mass bonus. The bonus reflects medical acuity at low weight: it is 15 when the intake `bmi` is below 16, 7 when the `bmi` is at least 16 but below 18.5, and 0 otherwise. The provisional value is the composite score plus that bonus, clamped to lie within 0 and 100. The platform writes this number to both `provisional_nutritional_risk_score` and the running `nutritional_risk_score` at finalize. The provisional figure is then frozen: it is computed once and is never touched by meal events or holds for the rest of the stay.

Whenever the running nutritional-risk score changes, the patient's `medical_stability_posture` is recomputed from it against two inclusive thresholds: the posture is `UNSTABLE` when the score is at least 75, `GUARDED` when it is at least 50 but below 75, and `STABLE` when it is below 50. Because finalize changes the running score, it recomputes the posture as part of the same atomic operation.

### 3.4. Creating and Promoting Admissions; the Admit Gate

`Intake` creates an **admission** referencing a `patient_id`, a `facility_id`, a `program_id`, a `cohort_id`, and a `requested_length_of_stay_days` (a positive integer used by the forward-looking day projection). A new admission starts `WAITLISTED` on its clinical dimension. The admission carries two independent dimensions on the same row: a `clinical_status` lifecycle and an orthogonal `level_of_care` ladder. The clinical statuses are `WAITLISTED`, `PENDING_ADMISSION`, `ADMITTED`, `MEDICAL_HOLD`, `DISCHARGE_PENDING`, `DISCHARGED`, and `ADMINISTRATIVE_DISCHARGE`; the last two are terminal. The admission also carries system timestamps `admitted_at_iso`, `loc_entered_at_iso`, and `discharged_at_iso`, and a `waitlist_promoted` flag that starts false.

`Intake` promotes a `WAITLISTED` admission to `PENDING_ADMISSION`. Promotion is legal only from `WAITLISTED` — otherwise `ERR_INVALID_STATE` — and only while the program's `status` is `OPEN`; a closed program rejects promotion with `ERR_PROGRAM_CLOSED`. The same `WAITLISTED → PENDING_ADMISSION` transition also occurs automatically as part of a discharge cascade (described in §3.9); when it is the cascade that promotes the admission, the `waitlist_promoted` flag is set true.

Admitting a `PENDING_ADMISSION` admission is the most heavily gated operation in the platform, performed by `Intake`, and it advances the clinical status to `ADMITTED`. Its preconditions are evaluated in this order. First, the admission must be `PENDING_ADMISSION`, else `ERR_INVALID_STATE`. Then the cohort's `age_band` must equal the patient's `age_band`, else `ERR_COHORT_AGE_MISMATCH`. Then the patient's `medical_stability_posture` must be admissible for the program's level of care: an `UNSTABLE` patient may be admitted only into a `RESIDENTIAL` program, and an attempt to admit an unstable patient into any other level is rejected with `ERR_LOC_NOT_ADMISSIBLE`. Then the program must be `OPEN`, else `ERR_PROGRAM_CLOSED`. Then the program must have room — its occupancy posture must be `OPEN`, meaning the occupied bed count is strictly below the bed capacity — else `ERR_PROGRAM_AT_CAPACITY`. Then the cohort must have room — its filled slots strictly below its slot capacity — else `ERR_COHORT_FULL`. Finally, the admission must be financially covered: an insurance authorization for this admission must exist in `APPROVED` status with at least one day remaining, else `ERR_NO_ACTIVE_AUTHORIZATION` (HTTP 402).

When admit succeeds, the platform sets the admission's `level_of_care` from the program's level of care, stamps `admitted_at_iso` and `loc_entered_at_iso` to the current logical clock, increments the program's `beds_occupied` by one and recomputes the program's `beds_available` and `occupancy_posture`, and increments the cohort's `slots_filled` by one. Admit does not recompute nutritional risk or posture — those were already established at assessment finalize.

### 3.5. Medical Holds and the Reconciled Risk Trail

While a patient is admitted, a `Clinician` may place a **medical hold**, moving the clinical status from `ADMITTED` to `MEDICAL_HOLD`; this is legal only from `ADMITTED`, else `ERR_INVALID_STATE`. Placing a hold adds 10 to the patient's running `nutritional_risk_score` (the reconciled variant) and recomputes the `medical_stability_posture` from the new score. Each hold accumulates: two holds add 10 twice.

A `Clinician` clears a hold, moving the status back from `MEDICAL_HOLD` to `ADMITTED`; this is legal only from `MEDICAL_HOLD`, else `ERR_INVALID_STATE`. Clearing a hold deliberately does **not** reverse the risk bump — the 10 points stay on the score. The only mechanism that ever credits the running score back down is meal-plan reconciliation, described in §3.6. This makes the admitted state and the held state a non-linear cycle: a patient can move `ADMITTED → MEDICAL_HOLD → ADMITTED` repeatedly, with each hold ratcheting risk upward.

The reconciled `nutritional_risk_score` is the running figure that diverges from the frozen provisional figure over the stay. It begins at the provisional value set at finalize; every medical hold adds 10; and every meal-plan close credits it down. It is the reconciled score — not the provisional one — that always drives the recomputed `medical_stability_posture`.

### 3.6. Supervised Meals and the Compliance Rate

A `Dietitian` opens a **meal plan** for an admission with an `admission_id`, a `facility_id`, a `required_meals_per_day` (the number of supervised meals and snacks scheduled per day, between 1 and 6), and a `supervision_level` of `FULL` or `PARTIAL`. A new meal plan is `ACTIVE` with `meals_logged` at zero and a `meal_compliance_rate` of zero; it also tracks `completion_points`. A meal plan is either `ACTIVE` or `CLOSED`.

Either a `Dietitian` or a `Clinician` appends a **meal event** to a meal plan, supplying a `meal_plan_id`, an `admission_id`, a `meal_type` of `BREAKFAST`, `LUNCH`, `DINNER`, or `SNACK`, a `completion_fraction` between 0.0 and 1.0, and an optional `refused` flag that defaults to false. Meal events are append-only and stamped with a `logged_at_iso` instant from the logical clock; none are ever excluded from the rate. Each event's **effective fraction** is 0.0 when the event is `refused`, and otherwise is the `completion_fraction` clamped into the 0.0-to-1.0 range. Appending an event increments the plan's `meals_logged` by one and adds the effective fraction to `completion_points`.

The plan's `meal_compliance_rate` is then recomputed as the accumulated completion points divided by the number of events logged, rounded half-up to four decimal places; with no events the rate is zero. This rate feeds both the step-down readiness check and, at meal-plan close, the reconciliation credit.

A `Dietitian` closes a meal plan, moving it from `ACTIVE` to `CLOSED` (legal only from `ACTIVE`, else `ERR_INVALID_STATE`). Closing reconciles the patient's running nutritional risk: the meal-credit factor is 40, and the credit subtracted is 40 multiplied by the plan's meal-compliance rate, rounded half-up to two decimal places. The running `nutritional_risk_score` becomes its prior value minus that credit, clamped to lie within 0 and 100, after which the `medical_stability_posture` is recomputed from the new score. A meal plan also closes automatically as one hop of the discharge cascade described in §3.9, with the identical reconciliation effect.

### 3.7. The Multidisciplinary Treatment Plan: Fork and Join

A `Clinician` creates a **treatment plan** for an admission with an `admission_id`, a `facility_id`, and a `goals_total` (a positive integer count of treatment goals). A new plan is `DRAFT` with all three discipline flags — `therapy_signed`, `dietitian_signed`, and `medical_signed` — false and `goals_met` at zero. Treatment-plan statuses are `DRAFT`, `ACTIVE`, `REVISION`, `SUPERSEDED`, and `CLOSED`.

The plan requires three independent discipline sign-offs that fork from `DRAFT` and join before activation. Signing a discipline names the `discipline` to sign — `THERAPY`, `DIETITIAN`, or `MEDICAL`. Signing is legal while the plan is `DRAFT` or `REVISION`, else `ERR_INVALID_STATE`. The `THERAPY` and `MEDICAL` disciplines may be signed only by a `Clinician`, while the `DIETITIAN` discipline may be signed only by a `Dietitian`; signing with the wrong role is rejected with `ERR_UNAUTHORIZED`. A discipline that is already signed cannot be signed again — that is `ERR_DISCIPLINE_ALREADY_SIGNED`. Each successful sign sets the corresponding flag — `therapy_signed`, `dietitian_signed`, or `medical_signed` — to true.

A `Clinician` activates the plan. From `DRAFT`, activation is legal only when the plan is `DRAFT`, else `ERR_INVALID_STATE`, and only when all three flags are true — the join — else `ERR_DISCIPLINES_INCOMPLETE`; success moves the status to `ACTIVE`. The same activate operation also serves the revision loop: from `REVISION`, activation is legal only when the plan is `REVISION`, else `ERR_INVALID_STATE`, and again requires all three flags set, else `ERR_DISCIPLINES_INCOMPLETE`; success moves the status to `ACTIVE`. Both the from-`DRAFT` and from-`REVISION` activations apply the same all-three-signed join condition and the same target state.

A `Clinician` revises an `ACTIVE` plan, moving it to `REVISION` to begin a fresh sign-off round. Revision is legal only from `ACTIVE`, else `ERR_INVALID_STATE`, and carries `expected_admission_version` for the optimistic-concurrency check of §2.5. Revising clears all three sign-off flags (re-forking the disciplines) and increments the admission's `version` by one. A plan in `REVISION` must be re-activated through the join before it is active again.

A `Clinician` marks a treatment goal met, which increments `goals_met` by one but never lets it exceed `goals_total` (it is capped there). The relationship `goals_met` over `goals_total` feeds the step-down readiness calculation. Finally, an `ACTIVE`, `REVISION`, or `DRAFT` treatment plan is moved to `CLOSED` automatically by the discharge cascade; this system close is the only path into `CLOSED`.

### 3.8. Stepping Down the Level of Care

The `level_of_care` ladder runs `RESIDENTIAL → PHP → IOP → OP` and only ever moves one rung lower; it is orthogonal to the clinical status and never moves backward. A `Clinician` steps an admission down one rung. The admission's clinical status stays `ADMITTED` throughout — step-down only changes the level-of-care dimension. Its preconditions are: the admission must be `ADMITTED`, else `ERR_INVALID_STATE`; the current level of care must not already be `OP`, because a lower rung must exist, else `ERR_ALREADY_LOWEST_LOC`; a treatment plan for this admission must exist in `ACTIVE` status, else `ERR_TREATMENT_PLAN_NOT_ACTIVE`; the admission's meal plan must show a `meal_compliance_rate` of at least 0.80 with at least 3 meals logged, else `ERR_INSUFFICIENT_MEAL_COMPLIANCE`; and the computed step-down readiness must be at least 75, else `ERR_STEP_DOWN_NOT_READY`. When all preconditions hold, the level of care advances one rung down the ladder and `loc_entered_at_iso` is re-stamped to the current logical clock.

The **step-down readiness score** is a 0-to-100 blend of three factors. The goal ratio is `goals_met` divided by `goals_total`, or 0 when `goals_total` is zero. The meal factor is the meal-compliance rate, capped at 1.0. The stability factor is 1.0 when the patient is `STABLE`, 0.6 when `GUARDED`, and 0.0 when `UNSTABLE`. The readiness is 100 multiplied by the sum of 0.45 times the goal ratio, plus 0.35 times the meal factor, plus 0.20 times the stability factor; that result is rounded half-up to two decimal places and then constrained to lie within 0 and 100. Step-down is permitted only when this readiness is at least 75. Note that the meal-compliance floor of 0.80 with its 3-meal minimum and the readiness floor of 75 are two separate gates with two separate errors, and both must be satisfied.

### 3.9. Discharge, Cascades, and Waitlist Promotion

Discharge is a two-step clinical wind-down. A `Clinician` first begins discharge, moving an `ADMITTED` admission to `DISCHARGE_PENDING` (legal only from `ADMITTED`, else `ERR_INVALID_STATE`). The same `ADMITTED → DISCHARGE_PENDING` transition is also driven automatically by an authorization expiry or exhaustion cascade, described in §3.11.

A `Clinician` then discharges a `DISCHARGE_PENDING` admission, moving it to the terminal `DISCHARGED` state. Discharge is legal only from `DISCHARGE_PENDING`, else `ERR_INVALID_STATE`. It additionally requires a finalized exit plan and completed family work: a discharge plan for this admission must exist in `FINALIZED` status, else `ERR_DISCHARGE_PLAN_NOT_FINALIZED`, and the family-program enrollment must be in `COMPLETED` or `WAIVED` status, else `ERR_FAMILY_PROGRAM_INCOMPLETE`.

A successful discharge fires a multi-hop cascade, all atomic within the request. The admission's `discharged_at_iso` is stamped to the current logical clock. The program's `beds_occupied` decrements by one and its `beds_available` and `occupancy_posture` recompute; the cohort's `slots_filled` decrements by one. Any `ACTIVE` meal plan associated with the admission moves to `CLOSED` (cascade hop 1), that meal-plan close reconciles the patient's `nutritional_risk_score` from the compliance rate exactly as in §3.6 (hop 2), and the patient's `medical_stability_posture` is recomputed from the reconciled score (hop 3). Any treatment plan for the admission in `ACTIVE`, `REVISION`, or `DRAFT` status moves to `CLOSED`. Finally, if and only if the program's occupancy posture flips from `FULL` to `OPEN` as a result of releasing the bed, the platform promotes the earliest-created (by `created_at` ascending) `WAITLISTED` admission in that same program to `PENDING_ADMISSION` and sets that admission's `waitlist_promoted` flag true. This waitlist promotion is a distinct cascade from the meal-plan and treatment-plan closures and fires only on the `FULL → OPEN` flip.

An `Admin` may instead administratively discharge an admission that never occupied a bed. From either `WAITLISTED` or `PENDING_ADMISSION`, administrative discharge moves the admission to the terminal `ADMINISTRATIVE_DISCHARGE` state; it is legal only from those two states, else `ERR_INVALID_STATE`. Because the admission never held a bed or cohort slot, no bed or cohort counters change.

### 3.10. Family Program and Discharge Plan

A `Clinician` enrolls an admission in the **family program** with an `admission_id`, a `facility_id`, a `family_contact_name`, and a `sessions_required` count (zero or more). A new enrollment is `ENROLLED` with `sessions_completed` at zero. Family-program statuses are `ENROLLED`, `COMPLETED`, and `WAIVED`. A `Clinician` records a completed family session, which increments `sessions_completed` by one; once the completed count reaches or exceeds `sessions_required`, the status automatically advances to `COMPLETED`. Alternatively, a `Clinician` or `Admin` waives the requirement, moving the status to `WAIVED`. As noted in §3.9, discharge requires the enrollment to be `COMPLETED` or `WAIVED`.

A `Clinician` creates a **discharge plan** for an admission with an `admission_id`, a `facility_id`, an `aftercare_level_of_care` of `PHP`, `IOP`, `OP`, or `NONE`, a non-empty `relapse_warning_signs` free-text field, and a `relapse_plan_complete` boolean. A new discharge plan is `DRAFT`; statuses are `DRAFT` and `FINALIZED`. A `Clinician` finalizes the plan, moving it from `DRAFT` to `FINALIZED` (legal only from `DRAFT`, else `ERR_INVALID_STATE`); finalize requires `relapse_plan_complete` to be true, else `ERR_RELAPSE_PLAN_INCOMPLETE`. A finalized discharge plan is what satisfies the discharge precondition of §3.9.

### 3.11. Insurance Authorization and the Concurrent-Review Loop

A `UtilizationReviewer` creates an **insurance authorization** for an admission with an `admission_id`, a `facility_id`, a `payer_name`, a `daily_rate_cents` (a positive whole-cent contracted daily rate), and a `coinsurance_pct` (the patient's coinsurance fraction between 0.0 and 1.0 applied per covered day). A new authorization is `PENDING` with `days_authorized` and `days_consumed` at zero. The authorization also carries `days_remaining`, a `covered_through_iso` instant (null until the first approval), and a `status` that is one of `PENDING`, `APPROVED`, `DENIED`, `APPEALED`, `EXPIRED`, or `EXHAUSTED`; the last two are terminal.

A `UtilizationReviewer` renders a **concurrent review** against an authorization, supplying an `authorization_id`, a `facility_id`, a `decision` of `APPROVE` or `DENY`, and — required when the decision is `APPROVE` — a `window_start_iso` (inclusive start) and a `window_end_iso` (exclusive end) describing the half-open coverage window. The review records its own `approved_days`, which is the whole covered days granted on approval and zero on denial. An approval is legal when the authorization is `PENDING`, `APPROVED`, or `APPEALED`, else `ERR_INVALID_STATE`, and requires the window to be well-formed with `window_end_iso` strictly after `window_start_iso`, else `ERR_INVALID_WINDOW`.

The first approval on a `PENDING` authorization accepts any well-formed window because there is no prior coverage to abut. Each `approved_days` value is the whole number of days in the half-open window, computed as the floor of the window's duration in seconds divided by 86,400 seconds per day. On approval the platform adds `approved_days` to `days_authorized`, recomputes `days_remaining`, sets `covered_through_iso` to the window's end, and moves the status to `APPROVED`. A subsequent approval on an already-`APPROVED` authorization is an **extension** and carries two extra constraints: the new window must be contiguous with prior coverage — its `window_start_iso` must equal the current `covered_through_iso` with no gap — else `ERR_AUTH_WINDOW_NONCONTIGUOUS`, and it must not overlap any prior approved window, else `ERR_AUTH_WINDOW_OVERLAP`. An accepted extension again adds its `approved_days` to `days_authorized`, recomputes `days_remaining`, and advances `covered_through_iso` to the new window end.

A `DENY` decision is legal from `PENDING`, `APPROVED`, or `APPEALED` (else `ERR_INVALID_STATE`); it appends a concurrent-review row recording the denial, leaves `days_authorized` unchanged, and moves the authorization to `DENIED`. A `UtilizationReviewer` may appeal a `DENIED` authorization, moving it to `APPEALED` (legal only from `DENIED`, else `ERR_INVALID_STATE`); from `APPEALED` the negotiation can loop back to `APPROVED` or `DENIED` through further reviews.

The forward-looking and chronological day variants differ and both matter. The **forward-looking projection** is used for admission eligibility and step-down planning; it pessimistically reserves the whole requested stay by treating the projected remaining days as `days_authorized` minus `requested_length_of_stay_days`, as if the full requested stay will be consumed regardless of the clock. The **chronological consumption** variant is what `days_consumed` and `days_remaining` report on the authorization as the clock advances: `days_consumed` is the sum over every approved window of the elapsed whole days in that window up to the clock — for each window, the floor of (the earlier of the window end or the current clock, minus the window start) in seconds divided by 86,400, never less than zero — and `days_remaining` is `days_authorized` minus `days_consumed`, floored at zero. The two variants coincide only once the clock has passed every window's end.

A `UtilizationReviewer` (or `Admin`) may expire an authorization whose coverage has elapsed. Expiry is legal from `PENDING`, `APPROVED`, `DENIED`, or `APPEALED`, else `ERR_INVALID_STATE`, and requires the logical clock to have reached or passed `covered_through_iso`, else `ERR_AUTH_NOT_EXPIRABLE`. Expiry moves the authorization to `EXPIRED`, and if its parent admission is `ADMITTED`, it cascades that admission from `ADMITTED` to `DISCHARGE_PENDING`. The same expiry-and-cascade is also evaluated automatically whenever the logical clock is advanced past a covered-through instant. Separately, an authorization is driven to `EXHAUSTED` by the system when, while consuming days, `days_remaining` reaches zero at the boundary on an `APPROVED` authorization; reaching `EXHAUSTED` likewise cascades an `ADMITTED` parent admission to `DISCHARGE_PENDING`.

### 3.12. Billing Summary and Patient Responsibility

A billing summary is a computed read available to `Admin` and `UtilizationReviewer`. It reports, for an authorization, the `authorization_id`, the chronological `days_consumed`, the `days_remaining`, and the `patient_responsibility_cents`. The patient-responsibility figure is computed with the rounding order pinned: first compute the per-day cost share as the `daily_rate_cents` multiplied by the `coinsurance_pct`, rounded half-up to whole cents; then multiply that whole-cent per-day share by `days_consumed`. The per-day rounding happens before the multiplication — multiplying the unrounded share by the day count and rounding once at the end would yield a different total and is explicitly not the method used.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, sign-offs, goal increments, and the logical-clock set — return `200 OK`. All read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical UTC clock to a supplied instant | Admin |
| POST | `/edt/facilities` | Create a facility | Admin |
| GET | `/edt/facilities` | List facilities | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/facilities/{fid}` | Get a facility | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/programs` | Create a level-of-care program | Admin |
| GET | `/edt/programs` | List programs (filter by facility_id, level_of_care) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/programs/{pgid}` | Get a program | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/programs/{pgid}/close` | Close a program to new admissions | Admin |
| POST | `/edt/cohorts` | Create a cohort within a program | Admin, Intake |
| GET | `/edt/cohorts` | List cohorts (filter by program_id, facility_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/cohorts/{cid}` | Get a cohort | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/patients` | Register a patient | Intake, Admin |
| GET | `/edt/patients` | List patients (filter by facility_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/patients/{pid}` | Get a patient | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/assessments` | Create a DRAFT level-of-care assessment | Clinician |
| GET | `/edt/assessments` | List assessments (filter by patient_id, facility_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/assessments/{asid}` | Get an assessment | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/assessments/{asid}/finalize` | Finalize an assessment | Clinician |
| POST | `/edt/admissions` | Create a WAITLISTED admission | Intake |
| GET | `/edt/admissions` | List admissions (filter by patient_id, program_id, cohort_id, facility_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/admissions/{aid}` | Get an admission | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/admissions/{aid}/promote` | Promote a waitlisted admission | Intake |
| POST | `/edt/admissions/{aid}/admit` | Admit a pending admission | Intake |
| POST | `/edt/admissions/{aid}/medical-hold` | Place admission on medical hold | Clinician |
| POST | `/edt/admissions/{aid}/clear-hold` | Clear a medical hold | Clinician |
| POST | `/edt/admissions/{aid}/step-down` | Step the admission down one level of care | Clinician |
| POST | `/edt/admissions/{aid}/begin-discharge` | Move an admitted admission to discharge-pending | Clinician |
| POST | `/edt/admissions/{aid}/discharge` | Discharge; release bed/cohort, close plans, promote waitlist | Clinician |
| POST | `/edt/admissions/{aid}/admin-discharge` | Administratively discharge a never-admitted admission | Admin |
| POST | `/edt/authorizations` | Create a PENDING insurance authorization | UtilizationReviewer |
| GET | `/edt/authorizations` | List authorizations (filter by admission_id, facility_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/authorizations/{authId}` | Get an authorization | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/authorizations/{authId}/billing-summary` | Computed patient-responsibility read | Admin, UtilizationReviewer |
| POST | `/edt/reviews` | Render a concurrent-review decision | UtilizationReviewer |
| GET | `/edt/reviews` | List concurrent reviews (filter by authorization_id, facility_id) | Admin, UtilizationReviewer, Clinician |
| GET | `/edt/reviews/{rid}` | Get a concurrent review | Admin, UtilizationReviewer, Clinician |
| POST | `/edt/authorizations/{authId}/appeal` | Appeal a denied authorization | UtilizationReviewer |
| POST | `/edt/authorizations/{authId}/expire` | Expire an authorization whose window has passed | UtilizationReviewer, Admin |
| POST | `/edt/treatment-plans` | Create a DRAFT treatment plan | Clinician |
| GET | `/edt/treatment-plans` | List treatment plans (filter by admission_id, facility_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/treatment-plans/{tpId}` | Get a treatment plan | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/treatment-plans/{tpId}/sign` | Sign one discipline | Clinician, Dietitian |
| POST | `/edt/treatment-plans/{tpId}/goals/met` | Increment goals met by one | Clinician |
| POST | `/edt/treatment-plans/{tpId}/activate` | Activate a fully-signed plan | Clinician |
| POST | `/edt/treatment-plans/{tpId}/revise` | Revise an active plan | Clinician |
| POST | `/edt/meal-plans` | Create an ACTIVE supervised meal plan | Dietitian |
| GET | `/edt/meal-plans` | List meal plans (filter by admission_id, facility_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/meal-plans/{mpId}` | Get a meal plan | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/meal-plans/{mpId}/close` | Close a meal plan; reconcile risk | Dietitian |
| POST | `/edt/meal-events` | Append a supervised-meal event | Dietitian, Clinician |
| GET | `/edt/meal-events` | List meal events (filter by meal_plan_id, admission_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/meal-events/{meid}` | Get a meal event | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/family-programs` | Enroll an admission in the family program | Clinician |
| GET | `/edt/family-programs` | List family-program enrollments (filter by admission_id, facility_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/family-programs/{fpid}` | Get a family-program enrollment | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/family-programs/{fpid}/complete-session` | Record one completed family session | Clinician |
| POST | `/edt/family-programs/{fpid}/waive` | Waive the family-program requirement | Clinician, Admin |
| POST | `/edt/discharge-plans` | Create a DRAFT discharge plan | Clinician |
| GET | `/edt/discharge-plans` | List discharge plans (filter by admission_id, facility_id) | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| GET | `/edt/discharge-plans/{dpId}` | Get a discharge plan | Admin, Intake, Clinician, Dietitian, UtilizationReviewer |
| POST | `/edt/discharge-plans/{dpId}/finalize` | Finalize the discharge plan | Clinician |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_COHORT_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ADMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_TREATMENT_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_MEAL_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_MEAL_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_FAMILY_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_DISCHARGE_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_LOWEST_LOC` | 409 Conflict |
| `ERR_PROGRAM_CLOSED` | 409 Conflict |
| `ERR_TREATMENT_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_DISCIPLINE_ALREADY_SIGNED` | 409 Conflict |
| `ERR_DISCIPLINES_INCOMPLETE` | 409 Conflict |
| `ERR_DISCHARGE_PLAN_NOT_FINALIZED` | 409 Conflict |
| `ERR_FAMILY_PROGRAM_INCOMPLETE` | 409 Conflict |
| `ERR_RELAPSE_PLAN_INCOMPLETE` | 409 Conflict |
| `ERR_AUTH_NOT_EXPIRABLE` | 409 Conflict |
| `ERR_PROGRAM_AT_CAPACITY` | 409 Conflict |
| `ERR_COHORT_FULL` | 409 Conflict |
| `ERR_COHORT_AGE_MISMATCH` | 409 Conflict |
| `ERR_LOC_NOT_ADMISSIBLE` | 409 Conflict |
| `ERR_INSUFFICIENT_MEAL_COMPLIANCE` | 409 Conflict |
| `ERR_STEP_DOWN_NOT_READY` | 409 Conflict |
| `ERR_AUTH_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AUTH_WINDOW_NONCONTIGUOUS` | 409 Conflict |
| `ERR_NO_ACTIVE_AUTHORIZATION` | 402 Payment Required |
