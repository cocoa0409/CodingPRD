# Radiation Oncology API — Product Requirements Document

## 1. Introduction

A radiation oncology center lives and dies by a disciplined consult-to-fraction pipeline: a physician prescribes a course of treatment, a simulator visit fixes the patient's immobilization geometry, target volumes and organs-at-risk are contoured and peer-reviewed, a dosimetrist builds a plan against dose constraints, two independent physics checks gate the first fraction, and only then does the linear accelerator schedule fill with daily treatments. Along the way the center must absorb the messy realities of care — patients losing weight mid-course and triggering adaptive replanning, machines going down and forcing interruptions with clinical compensation strategies, weekly chart-round peer review gating further delivery — and must bill every simulation, plan, check, fraction, and no-show with audit-grade accuracy.

This document specifies the API for that pipeline. The API is mounted under `/oncology` and is the single system of record for patients, treatment courses, simulation appointments, contour sets, treatment plans and their dose constraints, physics checks, treatment machines, fraction sessions, treatment interruptions, chart reviews, and billing claims. The design centers on three commitments: clinical safety enforced as hard gates rather than warnings (dual physics checks, segregation of duties, a chart-review cadence gate), biologically meaningful dose accounting (two complementary biologically effective dose figures maintained on every course), and fiscal correctness under a claim model that separates a forward-looking provisional estimate from a finalized, discount-aware total.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are accepted, the role must be permitted for the specific operation; an otherwise-authenticated user attempting an operation outside their role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly seven roles, spelled as follows: `RadiationOncologist`, `MedicalDosimetrist`, `MedicalPhysicist`, `RadiationTherapist`, `Scheduler`, `BillingCoordinator`, and `SystemAdmin`. For every one of these seven roles — `RadiationOncologist`, `MedicalDosimetrist`, `MedicalPhysicist`, `RadiationTherapist`, `Scheduler`, `BillingCoordinator`, and `SystemAdmin` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow calls for attribution — for example as `created_by_user_id` or `reviewed_by_user_id` on a contour set, `planner_id`, `primary_checker_id`, or `secondary_checker_id` on a treatment plan, `checker_id` on a physics check, or `reviewer_id` on a chart review — and it compares those recorded identifiers against `X-User-ID` only where a segregation-of-duties rule demands it; it never compares `X-User-ID` to any entity's `id`.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` ascending. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`. Certain lists accept additional filters — for example, a course's fraction-session list may be narrowed by a `status` query parameter — but pagination behavior is uniform.

### 2.4. Common Resource Properties and the Course Lifecycle Alphabet

Most resources share a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix, rendered in the canonical hyphenated text form — five hyphen-separated hexadecimal groups in an 8-4-4-4-12 pattern, exactly as produced by `str(uuid.uuid4())`. `created_at` and `updated_at` are ISO 8601 UTC timestamps carrying three fractional digits, with `updated_at` refreshed on every mutation. `version` is an integer that increments on every mutation of the resource and anchors optimistic concurrency control (see §2.7). Three resource kinds are deliberately lighter: a physics check, a chart review, and a charge line each carry only `id` and `created_at` — both `updated_at` and `version` are absent from them, because they are immutable records written once and never edited. Wherever §3 describes a cascade (a course counter advancing, a plan being superseded, a claim auto-reopening), each affected resource independently refreshes its `updated_at` and increments its `version`.

The treatment course is the lifecycle spine of the product, and its `status` field ranges over twelve exact values: `CONSULT`, `SIMULATION_SCHEDULED`, `SIMULATED`, `CONTOURING`, `PLANNING`, `PHYSICS_REVIEW`, `TREATMENT_READY`, `ON_TREATMENT`, `ADAPTATION_REQUIRED`, `REPLANNING`, `COMPLETED`, and `DISCONTINUED`. The first nine are working states; `COMPLETED` and `DISCONTINUED` are terminal. Most course movement is automatic — the server advances the course when the relevant clinical event lands rather than asking clients to drive it — and §3 narrates each such trigger in the subsection where the event lives.

### 2.5. Validation Order and Nested Resource Retrieval

Every request that survives transport is validated in a fixed, system-wide priority order; when several checks could reject the same request, the earliest category in this cascade wins and produces the error:

1. **User context.** Header presence and role validity — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role permission.** Whether the declared role may perform the operation — `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Existence.** Every identifier in the URL path is validated left-to-right, and the first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404) before any later identifier is examined. Identifiers referenced in the request body — `machine_id`, `contour_set_id`, `plan_id`, and `supersedes_plan_id` where they appear — must likewise exist, on the same error.
4. **Request schema.** Required fields present, types correct, enum values within their declared domains, `end_time` strictly after `start_time`, and numeric ranges respected (doses and fraction counts positive, `missed_count` at least 1, weights positive) — `ERR_INVALID_REQUEST` (HTTP 400).
5. **Optimistic concurrency.** Where an endpoint carries an expected-version field, it must equal the parent's current `version` — `ERR_STALE_VERSION` (HTTP 412).
6. **State gates.** The target resource must be in the state the operation requires (course status gates, plan draft and check-pending gates, session and simulation scheduled gates, claim draft/finalized gates, interruption open, contour submitted/submittable, machine down/up gates, terminal-course lockouts) — the operation-specific 409 error named in §3.
7. **Segregation of duties.** The acting operator must not be on the wrong side of a segregated step — `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
8. **Chart-review gate.** Delivery is permitted only while the course's chart-review counter permits it — `ERR_CHART_REVIEW_OVERDUE` (HTTP 409).
9. **Dose-constraint sufficiency.** Plan submission requires at least one constraint, and every constraint must be satisfied — `ERR_NO_DOSE_CONSTRAINTS` and `ERR_DOSE_CONSTRAINT_VIOLATION` (HTTP 422).
10. **Cross-reference integrity.** Referenced plans, contour sets, and supersession targets must belong to the same course and satisfy lineage and dose-remainder rules — `ERR_PLAN_COURSE_MISMATCH`, `ERR_CONTOUR_NOT_APPROVED`, `ERR_SUPERSEDES_NOT_LATEST`, `ERR_REMAINING_DOSE_MISMATCH`, and `ERR_STALE_CONTOUR_SET`.
11. **Machine, claim, and patient constraints.** Referenced machines must be `OPERATIONAL` and of the right type for the usage; SBRT immobilization; weekend booking allowance; a single open claim per course; remaining-fraction availability; patient `mrn` uniqueness — `ERR_MACHINE_NOT_OPERATIONAL`, `ERR_MACHINE_TYPE_MISMATCH`, `ERR_IMMOBILIZATION_REQUIRED`, `ERR_WEEKEND_NOT_PERMITTED`, `ERR_CLAIM_ALREADY_OPEN`, `ERR_NO_REMAINING_FRACTIONS`, `ERR_DUPLICATE_MRN` (HTTP 422).
12. **Interval occupation.** Turnover-buffered overlap on treatment machines and half-open overlap on simulators — `ERR_MACHINE_SLOT_CONFLICT` and `ERR_SIMULATOR_SLOT_CONFLICT` (HTTP 409).
13. **Capacity and fiscal floors.** Plan fraction-count ceilings, simulator daily capacity, and non-empty claims at finalization — `ERR_FRACTION_COUNT_EXCEEDED`, `ERR_SIMULATOR_DAILY_CAPACITY`, `ERR_EMPTY_CLAIM` (HTTP 422).

### 2.6. Precision, Rounding, and Monetary Semantics

All money in the system is integer cents; no monetary field ever carries a fractional cent. Where a computed monetary value is not naturally an integer — the planning charge multiplier and the payer-tier discount are the two cases — the result is rounded half up to a whole cent, and the rounding is applied exactly once at the end of the computation. Dose quantities are integer centigray (cGy) wherever they are prescribed, allocated, or delivered; per-fraction division is rounded half up to a whole centigray under the pinned order described in §3.4. Biologically effective dose (BED) figures, by contrast, are expressed in gray with exactly three decimal places, rounded half up. One threshold in the system is deliberately exempt from rounding: the adaptation weight-loss percentage is computed at full floating-point precision and compared without any rounding, per §3.8.

### 2.7. Optimistic Concurrency Control

Two write operations guard against stale client views with mandatory expected-version fields. First, creating a treatment plan for a course requires the request to carry `expected_course_version`, the course `version` the client last observed. If another writer has advanced the course's version since that observation — the canonical case being an adaptation plan that legitimately superseded the prior plan and rewrote the course's planned-fraction accounting — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client re-reads rather than planning against a course it has not observed. Second, finalizing a billing claim requires `expected_claim_version` matching the claim's current `version`; because a prior finalize, or an auto-reopen that appended new charge lines, legitimately changes the claim's totals, a stale finalize is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; all other mutations proceed without an OCC check.

### 2.8. Logical Clock and Calendar Semantics

All scheduling fields (`start_time`, `end_time`) and all timestamps are ISO 8601 UTC. The server maintains its own logical clock rather than reading wall-clock time: at startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `SystemAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The logical clock is what the machine-down cascade in §3.8 consults to decide which scheduled sessions count as future. Calendar questions are answered in UTC: a fraction session is a weekend session when its `start_time` (UTC) falls on a Saturday or Sunday, and simulator daily capacity is counted per UTC calendar date.

### 2.9. Segregation of Duties

Three clinical checkpoints are structurally segregated so that no single operator can push work past its own review. The oncologist who created a contour set may not approve it or return it — the approving or returning `X-User-ID` must differ from the set's `created_by_user_id`. The dosimetrist who built a plan may not perform its primary physics check — the primary checker's `X-User-ID` must differ from the plan's `planner_id`. And the physicist who performed the primary check may not perform the second check — the second checker's identity must differ from the recorded `primary_checker_id`. Every violation of these three rules is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Patient Intake and Course Prescription

A `Scheduler` registers each patient with a medical record number `mrn`, the patient's legal `full_name`, and a `date_of_birth` given as an ISO calendar date. The `mrn` is unique across all patients: a registration colliding with an existing record is rejected with `ERR_DUPLICATE_MRN` (HTTP 422).

Against a registered patient, a `RadiationOncologist` opens a **treatment course** — the prescription. The prescribing payload carries a `diagnosis_code`, the treatment `intent` (exactly one of `CURATIVE` or `PALLIATIVE`), the delivery `technique` (exactly one of `THREE_DCRT`, `IMRT`, or `SBRT`), the `prescribed_total_dose_cGy` as a positive integer, and the `planned_fractions` count, also a positive integer. The new course anchors itself to its patient through `patient_id`, starts in `CONSULT`, and immediately computes its `dose_per_fraction_cGy` as the prescribed total divided by the planned fraction count, rounded half up to a whole centigray. Its delivery counters `delivered_fractions`, `delivered_dose_cGy`, and `fractions_since_chart_review` all start at zero, as do the operational counters `weekend_makeup_allowance` and `open_interruption_count`; `baseline_weight_kg` stays unset until the first completed simulation (§3.2).

Every course continuously carries two biologically effective dose figures, recomputed on every course mutation and on every read. The first, `bed_nominal_gy`, is the prescription-side variant and ignores delivery progress and elapsed time entirely: take the per-fraction dose in gray (the course's current `dose_per_fraction_cGy` divided by one hundred), and compute the planned fraction count multiplied by that gray figure, multiplied by the quantity one plus that same gray figure divided by ten — an alpha/beta ratio of 10 gray. The result is rounded half up to three decimal places. The delivery-side twin, `bed_actual_gy`, is defined over the sessions the patient has actually received and is specified where delivery lives, in §3.7. Both figures ride along whenever the course is read.

### 3.2. Simulation Scheduling and Immobilization

Before any planning can begin, the patient must be simulated. A `Scheduler` books a **simulation appointment** against a course — the new record anchors itself to that course through its `course_id` — supplying the `machine_id` of the simulator, the slot's `start_time` and `end_time`, the `immobilization_device`, and optionally a `purpose`. The referenced machine must exist, must have `machine_type` `CT_SIMULATOR` — booking a simulation on a `LINAC` is rejected with `ERR_MACHINE_TYPE_MISMATCH` — and must be `OPERATIONAL`, since a `DOWN` machine rejects new bookings with `ERR_MACHINE_NOT_OPERATIONAL`. The device is one of `NONE`, `THERMOPLASTIC_MASK`, `VACUUM_CRADLE`, or `BODY_FRAME`; courses prescribed with the `SBRT` technique accept only `THERMOPLASTIC_MASK` or `BODY_FRAME`, and any other device on an SBRT course is rejected with `ERR_IMMOBILIZATION_REQUIRED`. The `purpose` defaults to `INITIAL`; the alternative, `ADAPTATION`, is bookable only while the course sits in `ADAPTATION_REQUIRED` (the re-simulation path of §3.8).

Two scheduling rules protect the simulator. Interval occupation is pure half-open overlap: a new appointment conflicts with an existing `SCHEDULED` appointment on the same simulator only when each starts strictly before the other ends — so an appointment beginning exactly when another ends is permitted — and a violating booking is rejected with `ERR_SIMULATOR_SLOT_CONFLICT` (HTTP 409). Aggregate daily capacity caps the load: a simulator accepts at most eight appointments in `SCHEDULED` or `COMPLETED` status whose `start_time` values fall on the same UTC calendar date, and the ninth such booking is rejected with `ERR_SIMULATOR_DAILY_CAPACITY` (HTTP 422). `CANCELLED` and `NO_SHOW` appointments occupy neither the interval nor the daily count.

The first booking flips the course automatically from `CONSULT` to `SIMULATION_SCHEDULED`. An appointment is born `SCHEDULED` and reaches one of three terminal outcomes. A `RadiationTherapist` completes it, recording the measured `patient_weight_kg` — a required input of the completion action — and the appointment becomes `COMPLETED`. Completion is rejected with `ERR_SIMULATION_NOT_SCHEDULED` (HTTP 409) unless the appointment is `SCHEDULED`, and with `ERR_COURSE_TERMINAL` (HTTP 409) when the owning course is already `COMPLETED` or `DISCONTINUED`. When this is the course's first completed appointment, the course advances `SIMULATION_SCHEDULED → SIMULATED` and captures `baseline_weight_kg` from the recorded weight; later completions never overwrite the baseline, and when the completing appointment belongs to a course sitting in `ADAPTATION_REQUIRED`, the course stays `ADAPTATION_REQUIRED` rather than moving. Completion also bills: a `SIMULATION` charge line is appended to the course's claim while one exists in `DRAFT` status. Alternatively a `Scheduler` may cancel a `SCHEDULED` appointment, moving it to `CANCELLED`, or a `RadiationTherapist` may mark it `NO_SHOW`; both actions enforce the same scheduled-state gate (`ERR_SIMULATION_NOT_SCHEDULED`).

### 3.3. Contouring and Contour Peer Review

With imagery in hand, a `RadiationOncologist` authors a **contour set**: a human-readable `set_label`, a non-empty `target_volumes` array of target-volume name strings — whose length later drives the planning-charge multiplier of §3.5 — and an `oar_structures` array of organ-at-risk names, which may be empty. The creating operator's identity is captured in `created_by_user_id`. The first contour set created on a course moves it automatically from `SIMULATED` to `CONTOURING`. A contour set begins in `DRAFT` and cycles through a review loop: submission moves `DRAFT → SUBMITTED` (and likewise `RETURNED → SUBMITTED` on resubmission); approval by a *different* oncologist moves `SUBMITTED → APPROVED`; and returning for rework moves either `SUBMITTED → RETURNED` or `APPROVED → RETURNED`.

Submission from any state other than `DRAFT` or `RETURNED` is rejected with `ERR_CONTOUR_NOT_SUBMITTABLE` (HTTP 409). Approval and return require the set to be `SUBMITTED` — return additionally tolerates `APPROVED`, reopening an already-approved set — and violations surface as `ERR_CONTOUR_NOT_SUBMITTED` (HTTP 409); both actions enforce the segregation rule of §2.9 against `created_by_user_id`, and submission is further locked out on a terminal course with `ERR_COURSE_TERMINAL`. Approval records the reviewer in `reviewed_by_user_id` and, when the course is in `CONTOURING`, advances it to `PLANNING`. The return action accepts explanatory `return_notes`. Every mutation of a contour set bumps its `version`, which matters downstream: reopening an `APPROVED` set stales any plan that pinned the old version, and the pinned-version mechanism of §3.4 is what catches it.

### 3.4. Treatment Planning, Dose Constraints, and Dose Allocation

A `MedicalDosimetrist` builds a **treatment plan** against a course, naming the `contour_set_id` it is built on, the `target_total_dose_cGy` this plan intends to deliver, the `planned_fractions` it will deliver them over, and — for adaptation plans only — a `supersedes_plan_id`. Because planning mutates the course's accounting, the request must also carry `expected_course_version` under the OCC rule of §2.7, and the create increments the course's `version` by 1. Cross-reference checks run under priority 10 of §2.5: the contour set must belong to the same course and be `APPROVED`, else `ERR_CONTOUR_NOT_APPROVED` (HTTP 422); when `supersedes_plan_id` is present it must reference the highest-`plan_version` plan of the same course, else `ERR_SUPERSEDES_NOT_LATEST` (HTTP 422). Dose accounting is then verified: an initial plan (no supersession) requires the course to be in `PLANNING` — `ERR_COURSE_NOT_PLANNING` (HTTP 409) otherwise — and its target must equal the course's `prescribed_total_dose_cGy` exactly; an adaptation plan requires the course to be in `ADAPTATION_REQUIRED` — `ERR_COURSE_NOT_ADAPTING` (HTTP 409) otherwise — and its target must equal the prescribed total minus the already-`delivered_dose_cGy`. Either target violation is `ERR_REMAINING_DOSE_MISMATCH` (HTTP 422).

The server stamps each plan with a `plan_version` — 1 for the course's first plan, incrementing by 1 for each subsequent plan — records the creating dosimetrist in `planner_id`, and snapshots the contour set's current `version` into `pinned_contour_version`. Creating an adaptation plan (one with `supersedes_plan_id` set) moves the course automatically `ADAPTATION_REQUIRED → REPLANNING`, rewrites the course's `planned_fractions` to the sum of its `delivered_fractions` and the new plan's `planned_fractions`, and recomputes the course's `dose_per_fraction_cGy` over the new plan. Plans form a supersession chain: clients can list the plans whose `supersedes_plan_id` points at a given plan (its successors), the plans built on a given contour set, and the fraction sessions scheduled under a plan.

A plan's own `dose_per_fraction_cGy` is governed by the **fraction dose allocation** rule, the system's pinned division algorithm. Given the plan's target total dose and its number of remaining fractions, the base is the target divided by the fraction count, rounded half up to a whole centigray — and this is the value the plan's `dose_per_fraction_cGy` stores. Every fraction except the last is allocated the base; the final fraction carries the remainder, namely the target minus the base multiplied by one fewer than the fraction count. The rounding order is pinned and non-negotiable: the per-fraction rounding happens first, and the remainder is reconciled on the final fraction second. Summing exact quotients and rounding once at the end is forbidden — a 5,005 cGy target over four fractions must allocate 1251, 1251, 1251, and 1252, never a uniformly rounded series. The same rule re-runs when a dose-per-fraction-increase compensation lands on an `ACTIVE` plan, per §3.8.

While a plan is `DRAFT`, the dosimetrist attaches **dose constraints**, each naming a `structure_name`, a `constraint_type` of `MAX_DOSE` or `MEAN_DOSE`, a positive integer `limit_cGy`, and the dosimetry engine's `evaluated_value_cGy` (zero or more). The system derives `satisfied` as true exactly when the evaluated value is no greater than the limit — equality satisfies. Constraint creation on a plan that has left `DRAFT` is rejected with `ERR_PLAN_NOT_DRAFT` (HTTP 409).

### 3.5. Physics Plan Check and Second Check

No plan may treat a patient until two independent physicists have checked it. When the dosimetrist submits a plan for check, five gates hold under the ordering of §2.5: the plan must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`); at least one dose constraint must exist (`ERR_NO_DOSE_CONSTRAINTS`, HTTP 422); every constraint must have `satisfied` true (`ERR_DOSE_CONSTRAINT_VIOLATION`, HTTP 422); the pinned contour set must still be `APPROVED` with its current `version` still equal to `pinned_contour_version` — contour rework since plan creation breaks this and yields `ERR_STALE_CONTOUR_SET` (HTTP 409); and the course must not be terminal (`ERR_COURSE_TERMINAL`). A successful submission moves the plan `DRAFT → PENDING_PRIMARY_CHECK` and the course — whether it sat in `PLANNING` or `REPLANNING` — to `PHYSICS_REVIEW`.

A `MedicalPhysicist` then records **physics checks**, each with a `check_type` of `PRIMARY` or `SECOND`, an `outcome` of `PASS` or `FAIL`, and optional free-text `notes`; the checker's identity lands in `checker_id`. The check type must match the plan's awaiting state: a `PRIMARY` check is recordable only while the plan is `PENDING_PRIMARY_CHECK`, and a `SECOND` check only while `PENDING_SECOND_CHECK`; a mismatched check is rejected with `ERR_PLAN_NOT_AWAITING_CHECK` (HTTP 409). Both segregation rules of §2.9 apply here — the checker must differ from `planner_id`, and the second checker must differ from `primary_checker_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`.

Outcomes drive the machine automatically. A `PRIMARY` check with `PASS` moves the plan `PENDING_PRIMARY_CHECK → PENDING_SECOND_CHECK`, records `primary_checker_id`, and appends a `PHYSICS_CHECK` charge line to the course's claim while one exists in `DRAFT`. A `SECOND` check with `PASS` moves the plan `PENDING_SECOND_CHECK → APPROVED_FOR_DELIVERY`, records `secondary_checker_id`, moves the course `PHYSICS_REVIEW → TREATMENT_READY`, and appends two charge lines to a `DRAFT` claim if one exists: another `PHYSICS_CHECK` line, and the `PLANNING` line. The planning charge is tiered: take the number of target volumes on the plan's pinned contour set, form a multiplier of one plus one-quarter times the number of volumes beyond the first, and multiply it by the technique base — 90,000 cents for `THREE_DCRT`, 210,000 cents for `IMRT`, 300,000 cents for `SBRT`. An initial plan bills that product rounded half up to a whole cent; an adaptation plan (one whose `supersedes_plan_id` is set) bills half of it, likewise rounded half up once at the end.

A `FAIL` at either stage sends the plan to `CHECK_FAILED` and pushes the course back from `PHYSICS_REVIEW` to `PLANNING` — or to `REPLANNING` when the failed plan is an adaptation plan. The dosimetrist may then revise: the revision action returns a `CHECK_FAILED` plan to `DRAFT`, where its dose constraints can be corrected before a fresh submission; revision from any other state is rejected with `ERR_PLAN_NOT_REVISABLE` (HTTP 409). This `DRAFT → PENDING_PRIMARY_CHECK → PENDING_SECOND_CHECK → APPROVED_FOR_DELIVERY` pipeline, with its `CHECK_FAILED → DRAFT` loop, is the plan's full working cycle; `SUPERSEDED` and `COMPLETED` are its terminal states.

### 3.6. Machines, LINAC Scheduling, and Fraction Booking

A `SystemAdmin` registers each **treatment machine** with a `name`, a `machine_type` of `CT_SIMULATOR` or `LINAC`, and a `room`; machines start life `OPERATIONAL`. Machine availability is managed through a status action with a `status` input: setting `DOWN` requires the machine currently `OPERATIONAL` (`ERR_MACHINE_ALREADY_DOWN`, HTTP 409, otherwise) and triggers the cascade of §3.8; restoring `OPERATIONAL` requires the machine currently `DOWN` (`ERR_MACHINE_NOT_DOWN`). Schedule views expose each machine's fraction sessions and each simulator's appointments.

Once a course is treatment-ready, a `Scheduler` books **fraction sessions** against it, supplying the `plan_id` to treat under, the `machine_id` of the vault, the slot's `start_time` and `end_time`, and optionally `igrt_planned` (default false) to bill image guidance. The plan must belong to the course in the path — `ERR_PLAN_COURSE_MISMATCH` (HTTP 422) otherwise — and must be `APPROVED_FOR_DELIVERY` or `ACTIVE`. The machine must be a `LINAC` (`ERR_MACHINE_TYPE_MISMATCH` on a simulator) and `OPERATIONAL` (`ERR_MACHINE_NOT_OPERATIONAL`). Capacity is enforced per plan: the plan's sessions in `SCHEDULED` plus `DELIVERED` status must remain strictly below the plan's `planned_fractions`, and a booking that would meet or exceed that ceiling is rejected with `ERR_FRACTION_COUNT_EXCEEDED` (HTTP 422).

Two temporal rules shape the book. First, weekend treatment is rationed: a booking whose `start_time` falls on a UTC Saturday or Sunday — the session's derived `is_weekend` flag — requires the course's `weekend_makeup_allowance` to be greater than zero, failing with `ERR_WEEKEND_NOT_PERMITTED` (HTTP 422) otherwise, and creating such a session decrements the allowance by one. Second, the LINAC honors a ten-minute turnover buffer: a new session conflicts with an existing `SCHEDULED` or `DELIVERED` session on the same machine whenever the new start falls before the existing end plus ten minutes *and* the existing start falls before the new end plus ten minutes, producing `ERR_MACHINE_SLOT_CONFLICT` (HTTP 409). Back-to-back scheduling is therefore not permitted on a LINAC — a session beginning exactly when another ends still collides, because both buffered comparisons hold. `CANCELLED` and `NO_SHOW` sessions free the machine entirely.

Each session receives a per-course `fraction_number`, assigned as one more than the maximum `fraction_number` over all existing sessions of the course and never reused, even after cancellation. The derived `is_first_fraction` flag is true exactly when `fraction_number` is 1. A freshly booked session is `SCHEDULED`; its `dose_delivered_cGy` and `cancellation_reason` stay unset until delivery or cancellation respectively.

### 3.7. Fraction Delivery and Chart-Round Governance

Delivery is the clinical heartbeat. A `RadiationTherapist` delivers a `SCHEDULED` session, and four gates must hold, in the priority order of §2.5: the session must be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED`, HTTP 409 — the same gate guards cancellation and no-show marking); the course must be `TREATMENT_READY` or `ON_TREATMENT` (`ERR_COURSE_NOT_ON_TREATMENT`, HTTP 409) — at which point the session's plan is necessarily `APPROVED_FOR_DELIVERY` or `ACTIVE`, because supersession cancels a plan's scheduled sessions; the chart-review gate must be open; and the machine must be `OPERATIONAL` (`ERR_MACHINE_NOT_OPERATIONAL`).

The **chart-review gate** enforces weekly peer review as a hard stop. Delivery is permitted only while the course's `fractions_since_chart_review` is strictly less than five: the fifth delivery since the last passing review still succeeds and arms the gate, and the sixth is rejected with `ERR_CHART_REVIEW_OVERDUE` (HTTP 409) until a physicist records a review. A `MedicalPhysicist` records a **chart review** with an `outcome` of `PASS` or `FAIL` and optional `notes`; the reviewer is captured in `reviewer_id`, and the record snapshots `delivered_fractions_at_review` from the course at review time. A `PASS` resets `fractions_since_chart_review` to zero; a `FAIL` leaves the counter unchanged.

A successful delivery writes the session's `dose_delivered_cGy` from the plan's allocation for that delivery index (the base for every fraction but the last, per §3.4), and advances the course: `delivered_fractions` increments by one, `delivered_dose_cGy` grows by the delivered amount, and `fractions_since_chart_review` increments by one. The course's first delivered session is doubly significant — the course moves `TREATMENT_READY → ON_TREATMENT` and the treating plan moves `APPROVED_FOR_DELIVERY → ACTIVE`. Delivery also drives the delivery-side BED figure introduced in §3.1: `bed_actual_gy` is computed over the course's `DELIVERED` sessions only, taken in `start_time` order; for each, the delivered dose in gray (the recorded `dose_delivered_cGy` divided by one hundred) is multiplied by one plus that same gray figure divided by ten, and these per-session terms are summed. From the sum the system subtracts a repopulation penalty of 0.6 gray per whole day by which the whole-day span between the earliest and latest delivered session start times exceeds twenty-eight days (the span is zero when fewer than two sessions have been delivered). The result is floored at zero — a negative outcome renders as 0.000 — and rounded half up to three decimal places.

Delivery is also the busiest billing moment. If the course has a claim in `FINALIZED` status, delivery auto-transitions it back to `DRAFT` first; then, while a `DRAFT` claim exists, up to three charge lines are appended, each with quantity one: a `FRACTION_DELIVERY` line at the technique's rate — 18,000 cents for `THREE_DCRT`, 32,000 cents for `IMRT`, 55,000 cents for `SBRT`; an `IGRT` line of 7,500 cents when the session's `igrt_planned` is true; and a `FIRST_FRACTION_SETUP` line of 12,000 cents when `is_first_fraction` is true. A `Scheduler` may instead cancel a `SCHEDULED` session with a `reason` of `PATIENT` or `OTHER`, which records the `cancellation_reason`; the system itself cancels with `MACHINE_DOWN` or `ADAPTATION` under the cascades of §3.8. A `RadiationTherapist` may mark a `SCHEDULED` session `NO_SHOW`, which — again auto-reopening a `FINALIZED` claim first — appends a `NO_SHOW_FEE` line while a `DRAFT` claim exists.

### 3.8. Adaptation, Interruption, and Compensation

Mid-course change is normal, and the system treats it as first-class workflow. A `RadiationOncologist` evaluates the **adaptation trigger** by submitting the patient's `current_weight_kg` and, optionally, a `physician_override` flag. The course must be `ON_TREATMENT` (`ERR_COURSE_NOT_ON_TREATMENT`) and necessarily has its `baseline_weight_kg` set, since reaching `ON_TREATMENT` implies a completed simulation. The percentage weight loss is the baseline minus the current weight, divided by the baseline, multiplied by one hundred — computed at full floating-point precision with no rounding before comparison. Adaptation is required when the loss is at least 10.0 percent (a loss of exactly 10.00 percent triggers) or when `physician_override` is true; a current weight at or above baseline yields a loss at or below zero and never triggers. When the trigger fires, the course moves `ON_TREATMENT → ADAPTATION_REQUIRED`, its `ACTIVE` plan becomes `SUPERSEDED`, every `SCHEDULED` session of the superseded plan is `CANCELLED` with `cancellation_reason` `ADAPTATION` (delivered, no-show, and already-cancelled sessions are untouched), and a `FINALIZED` claim on the course auto-returns to `DRAFT` with its totals retained. From there the course re-simulates (an `ADAPTATION`-purpose booking per §3.2, whose completion leaves the course in `ADAPTATION_REQUIRED`) and replans (an adaptation plan per §3.4, whose creation moves the course `ADAPTATION_REQUIRED → REPLANNING` and rewrites the planned-fraction accounting).

Interruptions are tracked explicitly. A `RadiationOncologist` or `RadiationTherapist` records a **treatment interruption** with a `reason` of `MACHINE_DOWN`, `PATIENT_ILLNESS`, or `OTHER`, a `missed_count` of at least one, and the `start_date` and `end_date` bounding the gap, with the end no earlier than the start. The system derives `gap_days` as the whole-day difference between the two dates plus one, stamps the interruption `OPEN`, and increments the course's `open_interruption_count` by one. Compensation is the oncologist's decision, applied to an `OPEN` interruption (`ERR_INTERRUPTION_NOT_OPEN`, HTTP 409, otherwise) while the course is `ON_TREATMENT` (`ERR_COURSE_NOT_ON_TREATMENT`). The chosen `strategy` is recorded in `applied_strategy`, the interruption becomes `COMPENSATED`, `open_interruption_count` decrements by one, and one of three compensations lands: `ADD_FRACTIONS` adds the `missed_count` to both the course's `planned_fractions` and the `ACTIVE` plan's `planned_fractions`, leaving the per-fraction dose unchanged; `DOSE_PER_FRACTION_INCREASE` leaves planned counts untouched but reruns the §3.4 allocation over the `ACTIVE` plan's remainder — the plan's `target_total_dose_cGy` minus the dose already delivered under that plan, spread across its `planned_fractions` minus the count already delivered under it, with the same base-then-remainder rule — and requires at least one undelivered fraction remaining on that plan (`ERR_NO_REMAINING_FRACTIONS`, HTTP 422); `WEEKEND_MAKEUP` adds the `missed_count` to the course's `weekend_makeup_allowance`, funding the weekend bookings of §3.6.

The fleet itself can force interruptions. When a `SystemAdmin` sets a machine `DOWN`, every fraction session on that machine still `SCHEDULED` with a `start_time` at or after the current logical time is cancelled with `cancellation_reason` `MACHINE_DOWN`. Then, for each affected course, the system creates an interruption of its own: `reason` `MACHINE_DOWN`, `missed_count` set to the number of sessions cancelled for that course, `start_date` and `end_date` both equal to the date of the earliest cancelled session, status `OPEN` — and each such creation increments that course's `open_interruption_count` by one, queuing the course for the compensation decision above.

### 3.9. Billing, Claims, and Course Termination

A `BillingCoordinator` opens a **billing claim** on a course. A course may have only one open claim — one in `DRAFT` or `FINALIZED` status — and opening a second is rejected with `ERR_CLAIM_ALREADY_OPEN` (HTTP 422). Creation backfills charge lines for billable events that already occurred (simulations completed, checks passed, plans approved, fractions delivered, no-shows marked) and computes the claim's totals. Every **charge line** records its owning `claim_id`, a `code` drawn from `SIMULATION`, `PLANNING`, `PHYSICS_CHECK`, `FRACTION_DELIVERY`, `IGRT`, `FIRST_FRACTION_SETUP`, or `NO_SHOW_FEE`, a human-readable `description`, a `quantity` (always 1 for system-generated lines), the `unit_charge_cents` taken from the fee schedule, and the computed `amount_cents` — the quantity multiplied by the unit charge, exact integer cents with no rounding. The `event_ref_id` ties each line to the source event that generated it, and the triple of claim, code, and event reference is unique, which prevents double-charging when backfill and live appends interleave. The `gross_total_cents` is always the sum of `amount_cents` over the claim's lines, recomputed whenever lines change and on finalize and reopen; `gross_total_cents`, `discount_cents`, and `final_total_cents` all read zero on a freshly opened claim, the latter two remaining zero until a finalize computes them.

The claim also carries `provisional_total_cents`, a forward-looking estimate recomputed whenever the claim is read or its lines change, in any claim status: the sum of the amounts on existing lines, plus a projection equal to the number of undelivered planned fractions — the course's `planned_fractions` minus its `delivered_fractions`, floored at zero — multiplied by the bare `FRACTION_DELIVERY` rate for the course's technique. The projection deliberately excludes image guidance, setup, and no-show fees, applies no discount, and is not reduced by no-show sessions: only `DELIVERED` sessions shrink the undelivered count.

Finalization is the OCC-guarded act of §2.7: the claim must be `DRAFT` (`ERR_CLAIM_NOT_DRAFT`, HTTP 409), must hold at least one charge line (`ERR_EMPTY_CLAIM`, HTTP 422), and the request's `expected_claim_version` must match the claim's current `version` (`ERR_STALE_VERSION`, HTTP 412). Finalize computes the **claim discount** in a pinned evaluation order that resolves the total-versus-discount dependency: first, `gross_total_cents` is the sum over all charge lines; second, the payer tier is tested against that gross — the discount applies only when the gross is strictly more than 1,500,000 cents; third, the discount base is the sum over lines whose `code` is `FRACTION_DELIVERY` or `IGRT` and nothing else, so one-time lines (simulation, planning, physics check, first-fraction setup, no-show fee) are never discounted; fourth, `discount_cents` is five percent of that base, rounded half up to a whole cent — zero when the tier is not met; fifth, `final_total_cents` is the gross minus the discount. Finalizing also increments the claim's `version` by one. A `FINALIZED` claim can be reopened — explicitly by the coordinator, or automatically by the system when a charge-affecting clinical event (fraction delivery, no-show marking, adaptation trigger, discontinuation) lands — returning it to `DRAFT`; reopening from any other state is `ERR_CLAIM_NOT_FINALIZED` (HTTP 409). The monetary fields survive the round trip verbatim: `gross_total_cents`, `discount_cents`, and `final_total_cents` are retained exactly and recomputed only on the next finalize. Submission, the terminal step, requires a `FINALIZED` claim (`ERR_CLAIM_NOT_FINALIZED`) and a course that has reached `COMPLETED` or `DISCONTINUED` (`ERR_COURSE_NOT_TERMINAL`, HTTP 409), and moves the claim `FINALIZED → SUBMITTED`.

Courses terminate in two ways. Completion is the oncologist's declaration that treatment is finished: it requires the course `ON_TREATMENT` (`ERR_COURSE_NOT_ON_TREATMENT`; reaching `ON_TREATMENT` already implies at least one delivered fraction) and no session of the course still `SCHEDULED` (`ERR_OPEN_SESSIONS_EXIST`, HTTP 409); the course becomes `COMPLETED` and its `ACTIVE` plan becomes `COMPLETED` too. Discontinuation is available from `CONSULT`, `SIMULATION_SCHEDULED`, `SIMULATED`, `CONTOURING`, `PLANNING`, `PHYSICS_REVIEW`, `TREATMENT_READY`, `ADAPTATION_REQUIRED`, and `REPLANNING` — a course already `COMPLETED` or `DISCONTINUED` rejects the attempt with `ERR_COURSE_TERMINAL`, and a course that is `ON_TREATMENT` is not discontinuable directly. The discontinue action accepts a `reason` and runs the full teardown cascade: every `SCHEDULED` simulation appointment is cancelled (recorded as `OTHER`), every `SCHEDULED` fraction session is cancelled (likewise `OTHER`), any plan in `DRAFT`, `PENDING_PRIMARY_CHECK`, `PENDING_SECOND_CHECK`, `APPROVED_FOR_DELIVERY`, or `ACTIVE` becomes `SUPERSEDED`, and a `FINALIZED` claim auto-returns to `DRAFT`. Both termini leave the course's financial record ready for the claim submission above.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, completions, cancellations, finalization, and the clock — return `200 OK`. List and single-resource reads return `200 OK`. The table below is the HTTP contract only; request payloads, validation chains, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/oncology/patients` | Register a patient | Scheduler |
| GET | `/oncology/patients` | List patients (paginated) | All roles |
| GET | `/oncology/patients/{id}` | Get a patient | All roles |
| POST | `/oncology/patients/{id}/treatment-courses` | Open a treatment course (prescription) | RadiationOncologist |
| GET | `/oncology/patients/{id}/treatment-courses` | List a patient's courses | All roles |
| GET | `/oncology/treatment-courses/{id}` | Get a course (includes computed BED fields) | All roles |
| POST | `/oncology/treatment-courses/{id}/complete` | Complete a course | RadiationOncologist |
| POST | `/oncology/treatment-courses/{id}/discontinue` | Discontinue a course | RadiationOncologist |
| POST | `/oncology/treatment-courses/{id}/adaptation-checks` | Evaluate the adaptation trigger | RadiationOncologist |
| POST | `/oncology/treatment-courses/{id}/simulation-appointments` | Book a simulation slot with immobilization device | Scheduler |
| GET | `/oncology/treatment-courses/{id}/simulation-appointments` | List a course's simulation appointments | All roles |
| POST | `/oncology/simulation-appointments/{id}/complete` | Complete a simulation; records patient weight | RadiationTherapist |
| POST | `/oncology/simulation-appointments/{id}/cancel` | Cancel a simulation appointment | Scheduler |
| POST | `/oncology/simulation-appointments/{id}/mark-no-show` | Mark a simulation no-show | RadiationTherapist |
| POST | `/oncology/treatment-courses/{id}/contour-sets` | Create a contour set | RadiationOncologist |
| GET | `/oncology/treatment-courses/{id}/contour-sets` | List a course's contour sets | All roles |
| GET | `/oncology/contour-sets/{id}` | Get a contour set | All roles |
| POST | `/oncology/contour-sets/{id}/submit` | Submit contours for review (from DRAFT or RETURNED) | RadiationOncologist |
| POST | `/oncology/contour-sets/{id}/approve` | Approve contours (different oncologist than creator) | RadiationOncologist |
| POST | `/oncology/contour-sets/{id}/return` | Return contours for rework | RadiationOncologist |
| POST | `/oncology/treatment-courses/{id}/treatment-plans` | Create a treatment plan (initial or adaptation) | MedicalDosimetrist |
| GET | `/oncology/treatment-courses/{id}/treatment-plans` | List a course's plans | All roles |
| GET | `/oncology/treatment-plans/{id}` | Get a plan | All roles |
| GET | `/oncology/treatment-plans/{id}/successors` | List plans superseding this plan | All roles |
| GET | `/oncology/contour-sets/{id}/treatment-plans` | List plans built on this contour set | All roles |
| GET | `/oncology/treatment-plans/{id}/fraction-sessions` | List fraction sessions scheduled under this plan | All roles |
| POST | `/oncology/treatment-plans/{id}/dose-constraints` | Add a dose constraint (plan must be DRAFT) | MedicalDosimetrist |
| GET | `/oncology/treatment-plans/{id}/dose-constraints` | List a plan's dose constraints | All roles |
| POST | `/oncology/treatment-plans/{id}/submit-for-check` | Submit plan for physics check | MedicalDosimetrist |
| POST | `/oncology/treatment-plans/{id}/revise` | Return a CHECK_FAILED plan to DRAFT for revision | MedicalDosimetrist |
| POST | `/oncology/treatment-plans/{id}/physics-checks` | Record a physics check (PRIMARY then SECOND) | MedicalPhysicist |
| GET | `/oncology/treatment-plans/{id}/physics-checks` | List a plan's physics checks | All roles |
| POST | `/oncology/treatment-courses/{id}/fraction-sessions` | Book a fraction on a LINAC | Scheduler |
| GET | `/oncology/treatment-courses/{id}/fraction-sessions` | List a course's fraction sessions | All roles |
| POST | `/oncology/fraction-sessions/{id}/deliver` | Deliver a fraction | RadiationTherapist |
| POST | `/oncology/fraction-sessions/{id}/cancel` | Cancel a scheduled fraction | Scheduler |
| POST | `/oncology/fraction-sessions/{id}/mark-no-show` | Mark a fraction no-show | RadiationTherapist |
| POST | `/oncology/machines` | Register a treatment machine | SystemAdmin |
| GET | `/oncology/machines` | List machines | All roles |
| GET | `/oncology/machines/{id}` | Get a machine | All roles |
| PUT | `/oncology/machines/{id}/status` | Set machine status (DOWN cascades) | SystemAdmin |
| GET | `/oncology/machines/{id}/fraction-sessions` | List a machine's fraction sessions | All roles |
| GET | `/oncology/machines/{id}/simulation-appointments` | List a simulator's appointments | All roles |
| POST | `/oncology/treatment-courses/{id}/interruptions` | Record a treatment interruption | RadiationOncologist, RadiationTherapist |
| GET | `/oncology/treatment-courses/{id}/interruptions` | List a course's interruptions | All roles |
| POST | `/oncology/interruptions/{id}/compensate` | Apply a compensation strategy to an OPEN interruption | RadiationOncologist |
| POST | `/oncology/treatment-courses/{id}/chart-reviews` | Record a chart-round peer review | MedicalPhysicist |
| GET | `/oncology/treatment-courses/{id}/chart-reviews` | List a course's chart reviews | All roles |
| POST | `/oncology/treatment-courses/{id}/billing-claims` | Open a billing claim (backfills prior billable events) | BillingCoordinator |
| GET | `/oncology/treatment-courses/{id}/billing-claims` | List a course's claims | All roles |
| GET | `/oncology/billing-claims/{id}` | Get a claim | All roles |
| GET | `/oncology/billing-claims/{id}/charge-lines` | List a claim's charge lines | All roles |
| POST | `/oncology/billing-claims/{id}/finalize` | Finalize a claim (OCC-guarded) | BillingCoordinator |
| POST | `/oncology/billing-claims/{id}/submit` | Submit a finalized claim (requires terminal course) | BillingCoordinator |
| POST | `/oncology/billing-claims/{id}/reopen` | Reopen a finalized claim | BillingCoordinator |
| POST | `/oncology/_clock/set_current_utc` | Set the server's logical clock | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_MRN` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_COURSE_NOT_ON_TREATMENT` | 409 |
| `ERR_COURSE_TERMINAL` | 409 |
| `ERR_COURSE_NOT_TERMINAL` | 409 |
| `ERR_COURSE_NOT_PLANNING` | 409 |
| `ERR_COURSE_NOT_ADAPTING` | 409 |
| `ERR_OPEN_SESSIONS_EXIST` | 409 |
| `ERR_PLAN_NOT_DRAFT` | 409 |
| `ERR_PLAN_NOT_AWAITING_CHECK` | 409 |
| `ERR_PLAN_NOT_REVISABLE` | 409 |
| `ERR_SESSION_NOT_SCHEDULED` | 409 |
| `ERR_SIMULATION_NOT_SCHEDULED` | 409 |
| `ERR_CONTOUR_NOT_SUBMITTED` | 409 |
| `ERR_CONTOUR_NOT_SUBMITTABLE` | 409 |
| `ERR_CLAIM_NOT_DRAFT` | 409 |
| `ERR_CLAIM_NOT_FINALIZED` | 409 |
| `ERR_INTERRUPTION_NOT_OPEN` | 409 |
| `ERR_MACHINE_ALREADY_DOWN` | 409 |
| `ERR_MACHINE_NOT_DOWN` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CHART_REVIEW_OVERDUE` | 409 |
| `ERR_NO_DOSE_CONSTRAINTS` | 422 |
| `ERR_DOSE_CONSTRAINT_VIOLATION` | 422 |
| `ERR_PLAN_COURSE_MISMATCH` | 422 |
| `ERR_CONTOUR_NOT_APPROVED` | 422 |
| `ERR_SUPERSEDES_NOT_LATEST` | 422 |
| `ERR_REMAINING_DOSE_MISMATCH` | 422 |
| `ERR_STALE_CONTOUR_SET` | 409 |
| `ERR_MACHINE_NOT_OPERATIONAL` | 422 |
| `ERR_MACHINE_TYPE_MISMATCH` | 422 |
| `ERR_IMMOBILIZATION_REQUIRED` | 422 |
| `ERR_WEEKEND_NOT_PERMITTED` | 422 |
| `ERR_CLAIM_ALREADY_OPEN` | 422 |
| `ERR_NO_REMAINING_FRACTIONS` | 422 |
| `ERR_MACHINE_SLOT_CONFLICT` | 409 |
| `ERR_SIMULATOR_SLOT_CONFLICT` | 409 |
| `ERR_FRACTION_COUNT_EXCEEDED` | 422 |
| `ERR_SIMULATOR_DAILY_CAPACITY` | 422 |
| `ERR_EMPTY_CLAIM` | 422 |
