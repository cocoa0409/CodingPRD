# Bariatric Weight-Loss Surgery Program API — Product Requirements Document

## 1. Introduction

A bariatric surgery program is a long, tightly regulated patient journey: a candidate must clear medical, behavioral, and nutritional gates, satisfy payer-specific supervised-diet requirements, complete a fixed pre-operative education curriculum, and only then reach the operating room — after which a structured series of post-operative follow-ups tracks weight-loss outcomes for a full year. This API is the system of record for that journey. It manages the candidacy math (BMI and ideal-body-weight computations, comorbidity-driven qualification), the insurance-versus-self-pay branching that governs which clearances are mandatory, the surgical scheduling engine (surgeon credentialing, operating-room turnover, and conflict detection), and the financial machinery for self-pay patients (case-bundle pricing, financing schedules, and cancellation refunds).

The platform is used by six distinct staff roles, each owning a slice of the workflow: coordinators drive the program lifecycle, dietitians and behavioral-health clinicians supply clearances, surgeons perform cases and manage complications, billing specialists build financing plans, and system administrators configure payers, rooms, and surgeons. Because a single clinical event — completing a surgery, logging a readmission-triggering complication, recording the twelve-month visit — can cascade across several records at once, the system emphasizes deterministic state propagation, optimistic concurrency on the program aggregate, and an outcome registry that remains internally consistent at every step. This document specifies the complete contract: entities and their fields, the state machines that govern each lifecycle, the calculation rules, the validation ordering, and the full endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the caller's role. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The six recognized roles are `ProgramCoordinator`, `Dietitian`, `BehavioralHealthClinician`, `BillingSpecialist`, `Surgeon`, and `SystemAdmin`. A `ProgramCoordinator` owns patient registration, the program lifecycle (candidacy review, clearance opening and finalization), education milestones, and surgery scheduling and cancellation. A `Dietitian` owns supervised-diet visits, nutrition clearances, and the recording of post-operative follow-up weights. A `BehavioralHealthClinician` owns psychological evaluations and their decisions and re-evaluations. A `BillingSpecialist` owns self-pay financing plans. A `Surgeon` performs surgery and manages complications. A `SystemAdmin` manages configuration — insurance plans, operating rooms, and surgeons — and drives the test logical clock. Every role may issue any GET read; the write operations are partitioned exclusively as described above.

Most roles carry an **opaque** identity: when `X-User-Role` is `ProgramCoordinator`, `Dietitian`, `BehavioralHealthClinician`, `BillingSpecialist`, or `SystemAdmin`, the `X-User-ID` value is an operator identifier that is not tied to any persisted entity; the server does not compare it against any record's `id`. The `Surgeon` role is the sole exception and is **entity-backed**: when `X-User-Role` is `Surgeon`, `X-User-ID` is the `id` of the acting `Surgeon` record. Ownership checks on surgeon-restricted actions compare the target `SurgeryCase`'s `surgeon_id` to `X-User-ID`; a surgeon acting on a case whose `surgeon_id` differs from their own `X-User-ID` is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

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

All list (array) endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100; the `offset` defaults to 0 and must be at least 0. List results are ordered by `created_at` in ascending order (oldest first), with ties broken by creation order (server insertion sequence). The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records beyond the current page remain).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` — an opaque UUID with no type prefix — assigned at creation and never reused. Each resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, stamped when the resource is first created and never altered thereafter. Ordering for list endpoints is always by this `created_at` value.

All entities in this system carry the full common-field set: in addition to `id` and `created_at`, every resource exposes an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. The `version` begins at 1 when a resource is created and increments by exactly 1 on every mutation of that resource; `updated_at` is refreshed to the current server time on each such mutation. Reads never change either value.

Path parameters are validated from left to right. When an endpoint's URL nests one identifier under another, each identifier is resolved in order and the first that does not resolve produces that resource's not-found error before any deeper resource is considered. For example, an operation addressed at a follow-up visit under a program resolves the program identifier first; a body foreign key is only checked once the path resources have all resolved.

### 2.5. Optimistic Concurrency Control

The `Program` aggregate is the concurrency anchor for the one write path that can legitimately be repeated against the same program state: financing-plan creation. A request that creates a financing plan for a program must carry `expected_program_version`, a non-optional field whose value must equal the target program's current `version`. Because a new financing plan is allowed to supersede a prior active plan from the same program state, this write cannot be gated by a state precondition alone; the stale-version check is what prevents a client from building a plan against a program whose `version` has since advanced. If `expected_program_version` does not match the program's current `version` — for instance, because an earlier plan creation already bumped the version after the client last read it — the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). Surgery-case scheduling likewise carries `expected_program_version` and is rejected with the same `ERR_STALE_PROGRAM_VERSION` (HTTP 412) on a mismatch. No other endpoint accepts a version field.

### 2.6. Numeric Precision and Rounding

All monetary amounts are stored and returned as integer cents; there are no fractional-cent values anywhere in the system. Where a monetary calculation multiplies by a fractional factor (for example, a BMI surcharge), the result is rounded half-up to a whole number of cents at the point specified for that calculation, and nowhere else. BMI values are stored to one decimal place using half-up rounding; ideal body weight is stored to three decimal places using half-up rounding. Each weight-loss outcome percentage is rounded half-up to one decimal place, independently of the other. Counts (readmissions, active complications, distinct diet months, re-evaluations) are exact integers.

### 2.7. The Logical Clock and Temporal Reasoning

All "now"-relative reasoning in the system is anchored to a server-maintained logical clock rather than wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z` and holds that value until it is first set; it never falls back to real time. A `SystemAdmin` may advance or replace the clock by supplying a `to_iso8601` instant, and the response reports the resulting `current_utc`. The logical clock governs two things: the rejection of surgeries scheduled in the past, and the date arithmetic that generates the post-operative follow-up series (which is dated from the surgery completion date as read from the clock at completion time). All other timestamps — every resource's `created_at` and `updated_at`, and each response's `api_request_timestamp` — are stamped from the server's real wall-clock UTC time (three fractional digits, `Z`-suffixed) and are unaffected by the logical clock.

### 2.8. Validation Order and Error Precedence

When a request could fail more than one check, the checks are evaluated in a fixed priority order, and the first failure determines the response. Authentication is evaluated first: a missing or unknown-role header pair yields `ERR_UNAUTHENTICATED` (401). Authorization is second: a recognized role that is not permitted for the operation yields `ERR_UNAUTHORIZED` (403). Third, each resource named in the URL path is resolved left to right, and an unresolved path id yields the corresponding not-found error (404). The `Surgeon`-ownership check is a special case of authorization that necessarily runs after path resolution — it compares the resolved target case's `surgeon_id` to the caller's `X-User-ID` — so a `Surgeon` acting on a case they do not own yields `ERR_UNAUTHORIZED` (403) evaluated after the role check and after the path-id 404s, but before body validation. Fourth, the request body is checked for structural validity — required fields present, enum values in range, correct types, and numeric constraints honored — with `ERR_VALIDATION` (400) on any violation. Fifth, body foreign keys (`patient_id`, `insurance_plan_id`, `operating_room_id`, `surgeon_id`, `program_id`, `surgery_case_id`) are resolved, with the corresponding not-found error (404) when any does not reference an existing row.

Each resource type has its own 404 code, used for both path-id and body-foreign-key resolution: an unresolved patient yields `ERR_PATIENT_NOT_FOUND`, a program `ERR_PROGRAM_NOT_FOUND`, an insurance plan `ERR_INSURANCE_PLAN_NOT_FOUND`, an operating room `ERR_OPERATING_ROOM_NOT_FOUND`, a surgeon `ERR_SURGEON_NOT_FOUND`, a surgery case `ERR_SURGERY_CASE_NOT_FOUND`, a psychological evaluation `ERR_PSYCH_EVALUATION_NOT_FOUND`, a complication `ERR_COMPLICATION_NOT_FOUND`, and a follow-up visit `ERR_FOLLOW_UP_VISIT_NOT_FOUND` — each with HTTP status 404.

Only after those universal tiers pass are the operation-specific rules considered — pathway/plan coherence, state preconditions, business constraints (credentialing, room status, uniqueness), temporal rules, fiscal limits, and finally the optimistic-concurrency check. The domain-specific ordering among those latter rules is described alongside each workflow in Section 3; where a single endpoint enforces several of them, the section spells out which check takes precedence.

### 2.9. Cascading State Propagation and Aggregate Consistency

Several operations mutate more than one record in a single request, and the program aggregate is the hub through which those cascades flow. Whenever a program transitions state or one of its system-maintained counters changes, the program's `version` increments by 1 and its `updated_at` refreshes. A surgery completion is the deepest cascade in the system: completing a case moves the case to `COMPLETED`, bubbles the owning program from `SURGERY_SCHEDULED` to `POST_OP`, and — as part of entering `POST_OP` — auto-generates the entire follow-up-visit series and enrolls the program's outcome-registry baseline. Logging a readmission-triggering complication both advances the program to `READMITTED` and adjusts its counters. Resolving the last open complication compensates that readmission by returning the program to `POST_OP`. Recording the twelve-month follow-up finalizes the program. Each of these is described in full in Section 3; the invariant to hold everywhere is that these secondary effects are applied atomically with the primary transition, and every touched record's `version` and `updated_at` move together.

## 3. Business Logic & Workflows

### 3.1. Configuration Prerequisites and Patient Intake

Before any program can advance, a `SystemAdmin` seeds the shared configuration. An insurance plan carries a `plan_name` and a short `payer_code`, the number of consecutive attended supervised-diet months the payer demands via `required_supervised_diet_months`, two boolean flags — `requires_psych_clearance` and `requires_nutrition_clearance`, both defaulting to true — that record whether the payer treats a cleared psychological evaluation and a cleared nutrition clearance as mandatory, the candidacy floors `bmi_floor_no_comorbidity` (defaulting to 40.0) and `bmi_floor_with_comorbidity` (defaulting to 35.0), and the `qualifying_comorbidities` the payer accepts. An operating room carries a `room_code`, a `turnover_buffer_minutes` value, and an availability `status`. A surgeon carries a `full_name`, an `npi` (National Provider Identifier), and the list of `credentialed_procedures` they are authorized to perform. These configuration records are created by the administrator and read by every role.

The journey begins when a `ProgramCoordinator` registers a patient. A patient record captures the medical record number `mrn`, the `full_name`, the `date_of_birth` (an ISO 8601 calendar date), the biological `sex` (either `MALE` or `FEMALE`), the standing `height_cm`, and the intake `baseline_weight_kg`. Both `height_cm` and `baseline_weight_kg` must be greater than zero. The `sex` value selects which ideal-body-weight formula variant applies later, and the height serves as the denominator of both the body-mass-index and ideal-weight computations.

Enrolling that patient into a bariatric program is also a coordinator action. A program creation payload names the `patient_id`, the `payment_pathway` (either `INSURANCE` or `SELF_PAY`), the documented `comorbidities` (a possibly-empty subset of `TYPE_2_DIABETES`, `HYPERTENSION`, `OSA`, `NAFLD`, `DYSLIPIDEMIA`, `GERD`, and `OSTEOARTHRITIS`), and — only for the insurance pathway — the `insurance_plan_id`. Pathway and plan must be coherent: an `INSURANCE` program must supply an `insurance_plan_id` that resolves to a plan, and a `SELF_PAY` program must omit it (leaving it absent or null). A mismatch on this rule — an insurance program with no plan, or a self-pay program that supplies one — is rejected with `ERR_PATHWAY_PLAN_MISMATCH` (HTTP 422).

At creation the system snapshots several computed values onto the program so that later math is stable against subsequent edits to the patient. It computes `baseline_bmi` from the referenced patient's height and weight: the height in centimetres is divided by 100 to yield metres, and the baseline weight in kilograms is divided by the square of that height in metres; the result is stored to one decimal place, rounded half-up. It snapshots `baseline_weight_kg` from the patient's intake weight, to serve as the reference point for later weight-loss percentages. And it computes `ideal_body_weight_kg` by the Devine method: take the patient's height in centimetres, divide by 2.54 to obtain inches, subtract 60 to obtain the inches over sixty (which may be negative for short patients); for a `MALE` patient the ideal weight is 50.0 kilograms plus 2.3 kilograms for each such inch, and for a `FEMALE` patient it is 45.5 kilograms plus 2.3 kilograms per inch. This ideal weight is stored to three decimal places, rounded half-up, and later serves as one of the denominators for excess-weight-loss reporting. A fresh program begins in `SCREENING`, with `candidacy_status` at `UNDETERMINED` and `qualifying_reason` still null; its `clearances_complete` gate is false, and its counters — `readmission_count`, `active_complication_count`, `amount_collected_cents`, `amount_refunded_cents`, and `amount_forfeited_cents` — all begin at zero.

### 3.2. Candidacy Determination

Once a program exists, the coordinator triggers candidacy review. This action is permitted only while the program is in `SCREENING`; attempting it from any other state is rejected with `ERR_INVALID_PROGRAM_STATE` (HTTP 409). Candidacy review runs a determination over three inputs — the program's snapshotted `baseline_bmi`, its documented `comorbidities`, and a pair of BMI floors together with a set of accepted comorbidities — and both records the result and advances the lifecycle in the same request.

The floors and the accepted-comorbidity set depend on the payment pathway. For an `INSURANCE` program, the system uses the linked plan's `bmi_floor_no_comorbidity`, its `bmi_floor_with_comorbidity`, and its `qualifying_comorbidities` set. For a `SELF_PAY` program there is no plan, so the system uses default floors of 40.0 (no comorbidity) and 35.0 (with comorbidity) and a default accepted set of `TYPE_2_DIABETES`, `HYPERTENSION`, `OSA`, `NAFLD`, and `DYSLIPIDEMIA`. Note that `GERD` and `OSTEOARTHRITIS` are deliberately excluded from the default accepted set, so a self-pay patient whose only comorbidity is one of those two is treated as having no qualifying comorbidity.

The determination proceeds in tiers. If the program's `baseline_bmi` is at or above the no-comorbidity floor, the program qualifies outright: `candidacy_status` becomes `QUALIFIED` and `qualifying_reason` becomes `BMI_40_PLUS`. Otherwise, if the `baseline_bmi` is at or above the with-comorbidity floor and the intersection of the program's documented comorbidities with the accepted set is non-empty, the program qualifies on the comorbidity tier: `candidacy_status` becomes `QUALIFIED` and `qualifying_reason` becomes `BMI_35_PLUS_COMORBIDITY`. If neither tier is satisfied, `candidacy_status` becomes `NOT_QUALIFIED` and `qualifying_reason` becomes `NOT_MET`. Both floor comparisons are inclusive — a BMI exactly equal to a floor meets it — and are performed against the stored one-decimal `baseline_bmi`. In the same request, the program moves out of `SCREENING`: a `QUALIFIED` result advances the program through `CANDIDACY_REVIEW` to `ELIGIBLE`, while a `NOT_QUALIFIED` result advances it to the terminal `INELIGIBLE` state, from which it cannot proceed to clearance. Every candidacy review increments the program's `version`.

### 3.3. Opening and Assembling Clearances

An `ELIGIBLE` program does not immediately accept clearance artifacts; the coordinator must first request clearance, which opens the clearance window by moving the program from `ELIGIBLE` to `CLEARANCE_IN_PROGRESS` and increments its `version`. This transition is permitted only from `ELIGIBLE`; from any other state it is rejected with `ERR_INVALID_PROGRAM_STATE` (HTTP 409). Only while the program sits in `CLEARANCE_IN_PROGRESS` do the four kinds of clearance artifact accept new entries. A POST of a supervised-diet visit, psychological evaluation, nutrition clearance, or education milestone against a program in any other state is rejected with `ERR_INVALID_PROGRAM_STATE` (HTTP 409); this state check is applied after the request body has been validated but before any uniqueness check (such as duplicate diet month or duplicate milestone code).

**Supervised-diet visits.** A `Dietitian` logs a supervised-diet visit against the program, recording the `month_index` it satisfies (a 1-based integer, at least 1), the `visit_date`, the `weight_kg` recorded that day (greater than zero), and whether the patient `attended` (defaulting to true). Only one visit may claim any given `month_index` for a program; a second visit reusing an existing `month_index` is rejected with `ERR_DUPLICATE_DIET_MONTH` (HTTP 409). Insurance payers require a run of consecutive attended monthly visits before they will authorize surgery; the plan states how many via `required_supervised_diet_months` (an integer of zero or more). The diet requirement is met when the number of distinct `month_index` values — counted only among visits that were attended and whose `month_index` falls between 1 and the required count inclusive — is at least the required count. A program that is one qualifying month short does not meet the requirement. For a `SELF_PAY` program the required count is treated as zero, so the diet requirement is vacuously satisfied.

**Psychological evaluations.** A `BehavioralHealthClinician` opens a psychological evaluation against the program; it may carry an optional `clinician_note` and starts in `PENDING`. The clinician then renders a decision on a `PENDING` evaluation, supplying a `decision` that is either `CLEARED` or `DEFERRED`; a `DEFERRED` decision also records a `deferral_reason`. A decision is only valid on an evaluation currently in `PENDING`; applying it to an evaluation in any other state is rejected with `ERR_INVALID_PSYCH_STATE` (HTTP 409). A deferred evaluation is not a dead end: the clinician may re-open it, moving it from `DEFERRED` back to `PENDING`, which increments its `reevaluation_count` and clears the stored `deferral_reason`. Re-evaluation is valid only from `DEFERRED`; from any other state it is rejected with the same `ERR_INVALID_PSYCH_STATE` (HTTP 409). Both the decision and the re-evaluation recompute the owning program's clearance gate. An evaluation counts as satisfying the psychological requirement only once it reaches `CLEARED`.

**Nutrition clearances.** A `Dietitian` records a nutrition clearance whose `decision` — either `CLEARED` or `NOT_CLEARED` — is set at creation, supported by a `diet_readiness_score` between 0 and 100 inclusive. The nutrition requirement is satisfied when the program has a nutrition clearance whose `decision` is `CLEARED`. Recording a clearance recomputes the program's clearance gate.

**Education milestones.** A `ProgramCoordinator` records pre-operative education milestones, one per `milestone_code`, drawn from `NUTRITION_CLASS`, `EXERCISE_ORIENTATION`, `SURGERY_RISKS_CONSENT`, and `POST_OP_DIET_EDUCATION`. Each carries a `completed` flag (defaulting to false) and an optional `completed_date`. A given `milestone_code` may be recorded only once per program; a duplicate code is rejected with `ERR_DUPLICATE_MILESTONE` (HTTP 409). The education requirement is met only when all four milestone codes exist for the program and each is marked `completed`. Recording a milestone recomputes the clearance gate.

**The clearance gate and finalization.** The derived `clearances_complete` gate is true exactly when all four conditions hold at once: the program has a `CLEARED` psychological evaluation, it has a `CLEARED` nutrition clearance, every one of the four required education milestones exists and is completed, and — for an `INSURANCE` program — the supervised-diet-month requirement is met (for a `SELF_PAY` program this diet condition is automatically true). When the coordinator finalizes clearance, the system recomputes this gate and, if it holds, moves the program from `CLEARANCE_IN_PROGRESS` to `CLEARED`, incrementing its `version`. Finalization is permitted only from `CLEARANCE_IN_PROGRESS`; attempting it from another state is rejected with `ERR_INVALID_PROGRAM_STATE` (HTTP 409). If the program is in `CLEARANCE_IN_PROGRESS` but the gate is not satisfied, finalization is rejected with `ERR_CLEARANCES_INCOMPLETE` (HTTP 409).

### 3.4. Scheduling a Surgery Case

Once a program is `CLEARED`, the coordinator schedules its surgery. The scheduling payload names the `operating_room_id`, the `surgeon_id`, the `procedure_type` (one of `SLEEVE_GASTRECTOMY`, `GASTRIC_BYPASS`, or `ADJUSTABLE_BAND`), the booking's `scheduled_start` and `scheduled_end` (ISO 8601 UTC instants), and `expected_program_version`. A successful schedule creates a surgery case in `SCHEDULED`, computes its `estimated_bundle_cents`, moves the program from `CLEARED` to `SURGERY_SCHEDULED`, and increments the program's `version`.

Scheduling enforces a sequence of gates, and the first to fail determines the rejection. The program must be in `CLEARED`; if it is not, the request is rejected with `ERR_PROGRAM_NOT_CLEARED` (HTTP 409). The named surgeon must be credentialed for the requested procedure — that is, the `procedure_type` must appear in the surgeon's `credentialed_procedures` — otherwise the request is rejected with `ERR_SURGEON_NOT_CREDENTIALED` (HTTP 409). The target operating room must have `status` of `OPEN`; scheduling into a room whose `status` is `CLOSED` is rejected with `ERR_ROOM_CLOSED` (HTTP 409). The booking window must be valid: `scheduled_end` must be strictly after `scheduled_start`, or the request is rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 422). The booking must not be in the past: `scheduled_start` must be at or after the current logical-clock instant, or the request is rejected with `ERR_SURGERY_IN_PAST` (HTTP 422).

Two overlap checks then guard the shared resources, and they use deliberately different rules. The operating room is protected by a buffer-extended, symmetric window: the room carries a `turnover_buffer_minutes` value (defaulting to 30) representing mandatory cleaning time between cases, and a new booking conflicts with any non-cancelled case already in that room when the new start falls before the existing case's end extended forward by the buffer, and the existing start falls before the new booking's end extended forward by the buffer. In other words, two cases in the same room must be separated by at least the room's turnover buffer; any closer and the request is rejected with `ERR_OR_ROOM_CONFLICT` (HTTP 409). The surgeon is protected by a stricter but bufferless rule: a new booking conflicts with any non-cancelled case for the same surgeon when the two intervals strictly overlap — the new start falls before the existing end and the existing start falls before the new end — with back-to-back adjacency (one case ending exactly when the next begins) explicitly allowed. A surgeon overlap is rejected with `ERR_SURGEON_CONFLICT` (HTTP 409). Finally, the optimistic-concurrency check applies: `expected_program_version` must equal the program's current `version`, failing which the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412).

The provisional price stamped onto the new case as `estimated_bundle_cents` is the self-pay case-bundle estimate for the chosen procedure at the program's snapshotted BMI. Take the procedure's base price in cents — 1,800,000 for `SLEEVE_GASTRECTOMY`, 2,500,000 for `GASTRIC_BYPASS`, and 1,500,000 for `ADJUSTABLE_BAND` — and apply a BMI surcharge multiplier: 15% when the program's `baseline_bmi` is at or above 50, otherwise 8% when it is at or above 40, otherwise no surcharge. The estimate is the base multiplied by one plus that surcharge fraction, rounded half-up to whole cents. For an `INSURANCE` program the estimated bundle is recorded as 0, since the payer, not the patient, bears the cost.

### 3.5. Completing or Cancelling a Case, and the Final Bundle

The assigned surgeon completes a scheduled case. Completion is restricted to the surgeon whose `id` matches the case's `surgeon_id`; another surgeon attempting it is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The case must be in `SCHEDULED`; completing a case in any other state is rejected with `ERR_INVALID_SURGERY_STATE` (HTTP 409). The completion payload supplies `actual_or_minutes` (a non-negative integer), from which the system computes and stores `final_bundle_cents`. The final bundle starts from the same estimate — base times one plus the BMI surcharge, rounded half-up — and then adds operating-room overtime: any minutes of `actual_or_minutes` beyond the procedure's standard allotment (90 minutes for `SLEEVE_GASTRECTOMY`, 150 for `GASTRIC_BYPASS`, 60 for `ADJUSTABLE_BAND`) are billed at 25,000 cents per minute. Overtime is the greater of zero and the actual minutes minus the standard allotment, so a case that runs within its standard time adds nothing and the final bundle equals the estimate. This overtime term is added after the surcharge rounding, not folded into it. For an `INSURANCE` program the `final_bundle_cents` is recorded as 0 — mirroring the zero estimate, since the payer bears the cost — while the supplied `actual_or_minutes` is still stored on the case.

Completing a case is the origin of the system's deepest cascade. The case moves to `COMPLETED`; the owning program bubbles from `SURGERY_SCHEDULED` to `POST_OP`; and entering `POST_OP` auto-generates the post-operative follow-up series and enrolls the program's outcome-registry baseline (its already-snapshotted `baseline_weight_kg` and `ideal_body_weight_kg`). The program's `version` increments as part of this cascade. The follow-up series is described in the next subsection.

A coordinator may instead cancel a scheduled case. Cancellation is valid only while the case is in `SCHEDULED`; cancelling a case in any other state is rejected with `ERR_INVALID_SURGERY_STATE` (HTTP 409). Cancellation records an optional `cancellation_reason`, moves the case to `CANCELLED`, and releases both the operating-room and surgeon time so the slot no longer participates in future overlap checks. The owning program falls back from `SURGERY_SCHEDULED` to `CLEARED` so a replacement case can be scheduled, and its `version` increments. When the program is `SELF_PAY` and it has already collected money — that is, its `amount_collected_cents` is greater than zero — cancellation also runs a refund: the clinic retains a fixed cancellation fee of 100,000 cents, forfeiting the smaller of that fee and the amount collected, and refunds the remainder. The forfeited amount is added to `amount_forfeited_cents` and the refunded amount to `amount_refunded_cents`, and together they always sum back to the amount that had been collected. The `amount_collected_cents` counter itself is left unchanged by cancellation; only `amount_forfeited_cents` and `amount_refunded_cents` accumulate.

### 3.6. The Post-Operative Follow-Up Series and Weight-Loss Outcomes

The moment a program enters `POST_OP`, the system generates a fixed five-visit follow-up series so that the outcome registry has a complete schedule from day one. Each visit carries an `interval_code` — `WEEK_2`, `WEEK_6`, `MONTH_3`, `MONTH_6`, and `MONTH_12` — and a `scheduled_date` computed from the surgery completion date (read from the logical clock at completion) plus a fixed offset in days: 14 days for `WEEK_2`, 42 days for `WEEK_6`, 90 days for `MONTH_3`, 180 days for `MONTH_6`, and 365 days for `MONTH_12`. Each generated visit starts in `SCHEDULED` with a null `recorded_weight_kg` and null outcome percentages. These auto-created visits are discoverable only by listing a program's follow-up visits; they are not created by any direct client call.

A `Dietitian` records the weight at a scheduled follow-up, supplying `recorded_weight_kg` (greater than zero). Recording is valid only while the visit is in `SCHEDULED`; recording against a visit in any other state is rejected with `ERR_INVALID_FOLLOWUP_STATE` (HTTP 409). Recording moves the visit to `COMPLETED` and computes two excess-weight-loss percentages against different reference weights, storing each to one decimal place rounded half-up and independently of the other. Both share the same numerator: the program's snapshotted `baseline_weight_kg` minus the newly recorded weight. The `ewl_pct_ibw` variant divides that numerator by the gap between the baseline weight and the program's `ideal_body_weight_kg`, then multiplies by 100. The `ewl_pct_bmi25` variant divides the same numerator by the gap between the baseline weight and the BMI-25 reference weight — computed as 25.0 multiplied by the square of the patient's height in metres (the height in centimetres divided by 100) — then multiplies by 100. Because the BMI-25 reference weight is larger than the Devine ideal weight, its denominator gap is smaller, so the two percentages differ.

Recording the `MONTH_12` visit is the program's natural finish line: when the visit being recorded has an `interval_code` of `MONTH_12` and the program is currently in `POST_OP`, the program transitions to `COMPLETED`, its outcome registry is finalized, and its `version` increments. Recording any of the earlier-interval visits completes only that visit and leaves the program in `POST_OP`.

### 3.7. Complications and the Readmission Cycle

After a case is completed, its assigned surgeon may log complications against it. Logging is restricted to the surgeon who owns the case (whose `id` equals the case's `surgeon_id`); another surgeon is rejected with `ERR_UNAUTHORIZED` (HTTP 403). A complication records its `complication_type` (one of `LEAK`, `BLEEDING`, `STRICTURE`, `INFECTION`, `DVT`, or `OTHER`), its `severity` (`MINOR`, `MODERATE`, or `SEVERE`), the `requires_readmission` flag, and the `onset_date`. Every new complication starts in `OPEN` and increments the owning program's `active_complication_count`, and the program's `version` moves with it. When `requires_readmission` is true, the program's `readmission_count` also increments; and if the program is currently in `POST_OP`, that readmission-triggering complication moves it from `POST_OP` to `READMITTED`.

The `active_complication_count` is a conserved quantity: it counts exactly the program's complications currently in `OPEN`. The assigned surgeon resolves an open complication, which is valid only while the complication is in `OPEN`; resolving one in any other state is rejected with `ERR_INVALID_COMPLICATION_STATE` (HTTP 409). Resolution moves the complication to `RESOLVED` and decrements the program's `active_complication_count`. Resolution is also the compensation for a readmission: when the program is in `READMITTED` and this resolution brings the `active_complication_count` down to zero, the program transitions from `READMITTED` back to `POST_OP`. Any resolution touching the program increments the program's `version`.

### 3.8. Self-Pay Financing

A `BillingSpecialist` builds a financing plan for a self-pay patient. Financing is available only when the program's `payment_pathway` is `SELF_PAY`; requesting a plan on an insurance program is rejected with `ERR_NOT_SELF_PAY` (HTTP 409). The plan payload names the `procedure_type` being financed, the `down_payment_cents` collected up front (zero or more), the number of monthly installments `term_months` (at least 1), the annual percentage rate `apr_bps` expressed in basis points (1,200 basis points is 12%, and it must be zero or more), and `expected_program_version`. A new plan starts in `ACTIVE`.

From these inputs the system derives the schedule. The `bundle_price_cents` is the self-pay case-bundle estimate for the chosen procedure at the program's `baseline_bmi` — computed exactly as the scheduling estimate is: the procedure's base price times one plus the BMI surcharge (15% at or above BMI 50, 8% at or above BMI 40, none below), rounded half-up to whole cents. The collected down payment may not exceed this bundle price; a `down_payment_cents` greater than the computed `bundle_price_cents` is rejected with `ERR_DOWN_PAYMENT_EXCEEDS_BUNDLE` (HTTP 422). The financed principal is the bundle price minus the down payment. The rounding order here is fixed and must not be shortcut: `interest_cents` is computed once over the whole principal — the principal multiplied by the APR as a fraction (basis points divided by 10,000) multiplied by the term expressed in years (`term_months` divided by 12) — and that single product is rounded half-up to whole cents. The financed total is the principal plus that rounded interest. The per-installment amount, `installment_cents`, is the financed total divided by the number of months and rounded down to whole cents (the floor); it applies to installments 1 through the second-to-last. The `final_installment_cents` absorbs the rounding remainder and is the financed total minus the per-installment amount times the count of all-but-the-last installments. Per-installment amounts are never rounded before summing; interest is rounded exactly once.

Creating a financing plan supersedes any prior plan and updates the program's collected total. Because re-financing from the same program state is legitimate, the create is guarded by optimistic concurrency rather than a state precondition: `expected_program_version` must equal the program's current `version`, and a mismatch — for instance when an earlier plan creation already advanced the version after the client's last read — is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). On success the program's previously `ACTIVE` financing plan, if any, flips to `SUPERSEDED`, the new plan becomes the `ACTIVE` one, the program's `amount_collected_cents` is set to this plan's `down_payment_cents`, and the program's `version` increments. This collected amount is what a later self-pay cancellation refunds against.

### 3.9. Outcome Registry Summary

At any point a caller may pull an outcome-registry summary for a program — a computed read that assembles the headline metrics in one place. The summary reports the `program_id`, the current program `status`, the snapshotted `baseline_bmi`, the `candidacy_status`, the latest recorded excess-weight-loss percentages as `latest_ewl_pct_ibw` and `latest_ewl_pct_bmi25` (taken from the most recently recorded follow-up visit, or null when none has been recorded), the cumulative `readmission_count`, and the current `active_complication_count`. The summary is a read-only projection and does not itself change any state or version.

## 4. Endpoint Definitions

The table below lists every endpoint with its authorized roles. Successful creation of a new resource returns HTTP 201; successful reads and state-changing actions on existing resources return HTTP 200. Request and response bodies are not repeated here — reconstruct them from the workflow narratives in Section 3. "All roles" denotes `ProgramCoordinator`, `Dietitian`, `BehavioralHealthClinician`, `BillingSpecialist`, `Surgeon`, and `SystemAdmin`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/insurance-plans` | Create an insurance plan (candidacy floors + clearance requirements) | `SystemAdmin` |
| GET | `/insurance-plans/{id}` | Fetch an insurance plan | All roles |
| POST | `/operating-rooms` | Create an operating room with turnover buffer | `SystemAdmin` |
| GET | `/operating-rooms/{id}` | Fetch an operating room | All roles |
| POST | `/surgeons` | Create a surgeon with credentialed procedures | `SystemAdmin` |
| GET | `/surgeons/{id}` | Fetch a surgeon | All roles |
| POST | `/_clock/set_current_utc` | Set the server logical clock | `SystemAdmin` |
| POST | `/patients` | Register a patient | `ProgramCoordinator` |
| GET | `/patients/{id}` | Fetch a patient | All roles |
| POST | `/programs` | Create a bariatric program; computes baseline BMI and ideal body weight | `ProgramCoordinator` |
| GET | `/programs` | List programs filtered by patient or plan | All roles |
| GET | `/programs/{id}` | Fetch a program | All roles |
| POST | `/programs/{id}/candidacy-review` | Run candidacy determination; advance to ELIGIBLE or INELIGIBLE | `ProgramCoordinator` |
| POST | `/programs/{id}/request-clearance` | Open the clearance window | `ProgramCoordinator` |
| POST | `/programs/{id}/finalize-clearance` | Verify clearances and move to CLEARED | `ProgramCoordinator` |
| GET | `/programs/{id}/summary` | Outcome-registry summary (computed read) | All roles |
| POST | `/programs/{id}/diet-visits` | Log a supervised-diet visit | `Dietitian` |
| GET | `/programs/{id}/diet-visits` | List a program's supervised-diet visits | All roles |
| POST | `/programs/{id}/psych-evaluations` | Create a psychological evaluation | `BehavioralHealthClinician` |
| GET | `/programs/{id}/psych-evaluations` | List a program's psych evaluations | All roles |
| POST | `/psych-evaluations/{id}/decision` | Decide a pending evaluation: CLEARED or DEFERRED | `BehavioralHealthClinician` |
| POST | `/psych-evaluations/{id}/reevaluate` | Re-open a deferred evaluation | `BehavioralHealthClinician` |
| POST | `/programs/{id}/nutrition-clearances` | Record a nutrition clearance decision | `Dietitian` |
| GET | `/programs/{id}/nutrition-clearances` | List a program's nutrition clearances | All roles |
| POST | `/programs/{id}/milestones` | Record/complete a pre-op education milestone | `ProgramCoordinator` |
| GET | `/programs/{id}/milestones` | List a program's education milestones | All roles |
| POST | `/programs/{id}/surgery-cases` | Schedule a surgery case for a CLEARED program | `ProgramCoordinator` |
| GET | `/surgery-cases` | List surgery cases filtered by program, room, or surgeon | All roles |
| GET | `/surgery-cases/{id}` | Fetch a surgery case | All roles |
| POST | `/surgery-cases/{id}/complete` | Mark a scheduled case completed (assigned surgeon only) | `Surgeon` |
| POST | `/surgery-cases/{id}/cancel` | Cancel a scheduled case; release room/surgeon and refund self-pay deposit | `ProgramCoordinator` |
| POST | `/surgery-cases/{id}/complications` | Log a complication on a completed case (assigned surgeon only) | `Surgeon` |
| GET | `/surgery-cases/{id}/complications` | List a case's complications | All roles |
| POST | `/complications/{id}/resolve` | Resolve an open complication (assigned surgeon only) | `Surgeon` |
| GET | `/programs/{id}/follow-up-visits` | List a program's follow-up visits | All roles |
| POST | `/follow-up-visits/{id}/record` | Record weight at a scheduled follow-up; compute %EWL; MONTH_12 completes the program | `Dietitian` |
| POST | `/programs/{id}/financing-plan` | Create/replace a self-pay financing plan (OCC on program version) | `BillingSpecialist` |
| GET | `/programs/{id}/financing-plan` | List a program's financing plans | All roles |

## 5. Error Code Catalogue

The conditions that trigger each error are described in the relevant narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_INSURANCE_PLAN_NOT_FOUND` | 404 |
| `ERR_OPERATING_ROOM_NOT_FOUND` | 404 |
| `ERR_SURGEON_NOT_FOUND` | 404 |
| `ERR_SURGERY_CASE_NOT_FOUND` | 404 |
| `ERR_PSYCH_EVALUATION_NOT_FOUND` | 404 |
| `ERR_COMPLICATION_NOT_FOUND` | 404 |
| `ERR_FOLLOW_UP_VISIT_NOT_FOUND` | 404 |
| `ERR_PATHWAY_PLAN_MISMATCH` | 422 |
| `ERR_INVALID_PROGRAM_STATE` | 409 |
| `ERR_INVALID_PSYCH_STATE` | 409 |
| `ERR_INVALID_SURGERY_STATE` | 409 |
| `ERR_INVALID_COMPLICATION_STATE` | 409 |
| `ERR_INVALID_FOLLOWUP_STATE` | 409 |
| `ERR_PROGRAM_NOT_CLEARED` | 409 |
| `ERR_CLEARANCES_INCOMPLETE` | 409 |
| `ERR_SURGEON_NOT_CREDENTIALED` | 409 |
| `ERR_ROOM_CLOSED` | 409 |
| `ERR_DUPLICATE_MILESTONE` | 409 |
| `ERR_DUPLICATE_DIET_MONTH` | 409 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_SURGERY_IN_PAST` | 422 |
| `ERR_OR_ROOM_CONFLICT` | 409 |
| `ERR_SURGEON_CONFLICT` | 409 |
| `ERR_NOT_SELF_PAY` | 409 |
| `ERR_DOWN_PAYMENT_EXCEEDS_BUNDLE` | 422 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |
