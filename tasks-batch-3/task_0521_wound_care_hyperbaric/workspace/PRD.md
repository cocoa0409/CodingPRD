# Wound Care & Hyperbaric Center API — Product Requirements Document

## 1. Introduction

The Wound Care & Hyperbaric Center API coordinates the full arc of chronic-wound management at a specialty outpatient center: intake and referral triage, standardized wound staging and measurement, treatment planning, scheduled debridement, hyperbaric oxygen (HBO) therapy with dive logging, advanced-dressing and skin-graft supply procurement, photo-documented healing trajectories, payer coverage adjudication, escalation to acute care, and final outcome reporting. Each of these workflows is owned by a distinct clinical or administrative role, and each carries its own regulatory, safety, and fiscal obligations that the API must enforce with no ambiguity.

Two forces shape every rule in this document. The first is compliance: hyperbaric chambers cannot be double-booked, debridement must be performed by an appropriately credentialed clinician, the same person cannot both perform a debridement and initiate the patient's transfer to acute care, and coverage decisions must be traceable to a payer policy and its prior authorization. The second is financial reconciliation: supply spend is committed against a per-plan budget, HBO reimbursement is estimated provisionally and then finalized, and every credit and debit against a plan must leave the ledger internally consistent even as sessions are cancelled, plans are suspended, and authorizations are denied. This document specifies the data model, the state machines, the calculations, and the validation ordering that together guarantee both properties.

All resources live as peers under the `/wound-care` root; foreign-key references between them travel inside request bodies rather than in URL paths, and every collection exposes a filtered list endpoint so that any reference can be traced back to its owner.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing or invalid, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly five roles: `IntakeCoordinator`, `WoundClinician`, `HyperbaricTech`, `PayerLiaison`, and `AttendingPhysician`. `IntakeCoordinator` handles front-desk intake — creating centers, registering clinicians and chambers, creating patients, and driving referrals. `WoundClinician` owns clinical assessment and treatment: recording wound assessments and photos, creating and driving treatment plans, scheduling and resolving debridements, and submitting or cancelling supply orders. `HyperbaricTech` owns the HBO chamber floor: scheduling, completing, and cancelling hyperbaric sessions. `PayerLiaison` owns the payer relationship: payer policies, prior authorizations, and supply-order approvals and rejections. `AttendingPhysician` owns escalation: initiating, accepting, and cancelling acute transfers. Every role may call all read (GET) endpoints and may set the logical clock.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `WoundClinician`, `X-User-ID` is the `id` of the acting `Clinician`; likewise when `X-User-Role` is `HyperbaricTech`, `X-User-ID` is the `id` of the acting `Clinician`. Ownership or provenance checks that reference a clinician compare against this identifier — for example, the `performed_by_user_id` recorded when a debridement is completed is the completing `WoundClinician`'s `X-User-ID`. When `X-User-Role` is `IntakeCoordinator`, `PayerLiaison`, or `AttendingPhysician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, `initiated_by_user_id` on an `AcuteTransfer` captures the initiating `AttendingPhysician`'s `X-User-ID`) but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped from the front of the result set; when omitted it defaults to 0.

Unless a specific endpoint says otherwise, list results are sorted by `created_at` in ascending order. Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that starts at its initial value and increments by one on each mutation. Optimistic concurrency, described in §2.7, reads this `version`.

Two entities are append-only clinical records and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version` field: the `WoundAssessment` and the `PhotoDocument`. Once written, they are never mutated, so no version or update timestamp is maintained for them. Every other entity — `Center`, `Clinician`, `Chamber`, `PayerPolicy`, `Patient`, `Referral`, `TreatmentPlan`, `PriorAuthorization`, `DebridementProcedure`, `HboSession`, `SupplyOrder`, `AcuteTransfer`, and `OutcomeReport` — carries the full set of common fields.

### 2.5. The Logical Clock

The center operates against a logical clock rather than wall-clock time so that time-dependent behavior is deterministic and test-drivable. Each `Center` holds a `current_utc` value. On startup, and before any clock call is made, the clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to real wall-clock time. Any of the five roles may advance or set the clock by supplying the target `center_id` and a `to_iso8601` instant, which sets that center's `current_utc`. Timestamps that the system stamps from the clock — a wound assessment's `assessed_at` and a photo document's `captured_at` — are taken as the owning center's `current_utc` at the moment of the write.

### 2.6. Precision and Rounding

Monetary amounts are stored and returned in whole cents as integers. Where a monetary calculation produces a fractional cent, it is resolved by rounding half up to the nearest whole cent, following the per-line-then-sum ordering described in §3.6 for supply reimbursement. Wound area is expressed in square centimeters and rounded half up to two decimal places. Healing percentages are rounded half up to two decimal places. The wound severity score is an integer, produced by rounding half up to a whole number before the floor-and-ceiling clamp is applied. All rounding throughout the system uses the round-half-up convention.

### 2.7. Optimistic Concurrency on Treatment Plans

Two write operations are guarded by optimistic concurrency control against the parent `TreatmentPlan`'s `version`, because both consume plan-scoped state (chamber slots, coverage estimates, and the supply budget) that other operations advance concurrently.

Scheduling a new HBO session requires the request to include `expected_plan_version` carrying the client's last observed `version` of the target `TreatmentPlan`. If that value does not match the plan's current `version`, the schedule is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). Because a plan suspension (which cascades session cancellations) and a prior-authorization approval both advance the plan's `version`, a scheduler working from a stale view is turned away rather than booking a chamber slot against an out-of-date plan.

Submitting a supply order likewise requires `expected_plan_version` matching the target `TreatmentPlan`'s current `version`; a mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). This keeps the budget ledger consistent when, for instance, an earlier supply submission has already debited the covered budget or a prior-authorization denial has flipped coverage to `NOT_COVERED` since the client last read the plan. No other endpoint accepts or requires a version field.

### 2.8. Cross-Center Referential Integrity

Resources are anchored to a `Center`. Because chambers and clinicians are referenced across aggregate boundaries when work is scheduled, the system enforces that a referenced `chamber_id` or `clinician_id` belongs to the same center as the plan's patient. When scheduling a debridement, the referenced clinician's `center_id` must equal the `center_id` of the patient on the plan; when scheduling an HBO session, the referenced chamber's `center_id` must equal the `center_id` of the patient on the plan. Either mismatch is rejected with `ERR_CROSS_CENTER_REFERENCE`.

### 2.9. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order, and the first failure is the one reported. The order is: (1) header presence and validity, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role permission per the access-control matrix, failing with `ERR_INSUFFICIENT_PERMISSIONS`; (3) existence of every path- and body-referenced resource, failing with the applicable not-found code (the generic `ERR_NOT_FOUND` or a resource-specific code such as `ERR_PLAN_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_CENTER_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_AUTH_NOT_FOUND`, `ERR_PROC_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, or `ERR_POLICY_NOT_FOUND`); (4) the optimistic-concurrency version check of §2.7, failing with `ERR_STALE_PLAN_VERSION`; (5) the target resource being in the correct state for the requested transition, failing with the transition's state-specific code; (6) the cross-center referential check of §2.8, failing with `ERR_CROSS_CENTER_REFERENCE`; (7) the debridement clinician-role check, failing with `ERR_CLINICIAN_ROLE_MISMATCH`; (8) the segregation-of-duties check on transfers, failing with `ERR_SEGREGATION_OF_DUTIES`; (9) the chamber temporal-overlap check, failing with `ERR_CHAMBER_SLOT_CONFLICT`; (10) the clinician temporal-overlap check, failing with `ERR_CLINICIAN_SLOT_CONFLICT`; (11) the HBO coverage-active check, failing with `ERR_COVERAGE_NOT_ACTIVE`; (12) the supply budget check, failing with `ERR_SUPPLY_BUDGET_EXCEEDED`; and finally (13) field- and enum-level request validity, failing with `ERR_INVALID_REQUEST`. When a request would fail more than one of these, the lower-numbered check wins.

For endpoints whose URL carries a resource identifier, existence is validated before any state or business rule; a request naming a resource that does not exist is rejected with that resource's not-found code before the system evaluates whether the operation itself is legal.

### 2.10. Field Validity

Creation requests are subject to structural validation, failing with `ERR_INVALID_REQUEST` when violated. Enumerated fields must carry legal values: a wound assessment's `stage` must be one of `STAGE_1`, `STAGE_2`, `STAGE_3`, `STAGE_4`, or `UNSTAGEABLE`; its `tissue_type` must be one of `GRANULATION`, `EPITHELIAL`, `SLOUGH`, or `NECROTIC`; a supply order's `supply_kind` must be `ADVANCED_DRESSING` or `SKIN_GRAFT`; and a clinician's `role_kind` must be `WOUND`, `HYPERBARIC`, or `ATTENDING`. Wound `length_cm` and `width_cm` must each be greater than zero. A supply line's `coverage_rate` must fall within the inclusive range from zero to one. A chamber's `turnover_buffer_minutes` must be at least zero. A payer policy's `max_covered_hbo_sessions`, `per_session_cents`, and a plan's `debridement_supply_budget_cents` must each be at least zero. A prior authorization's `requested_hbo_sessions` must be at least one. For any scheduled interval, `window_end` must be strictly greater than `window_start`.

## 3. Business Logic & Workflows

### 3.1. Center Setup, Staffing, and Payer Configuration

Before any patient can be seen, an `IntakeCoordinator` stands up the operational backbone. A `Center` is created with a `name`; its `current_utc` begins at the startup default described in §2.5. Clinicians are then registered against the center by `center_id` with a `name`, a `role_kind`, and an optional `active` flag that defaults to true and marks whether the clinician is schedulable. Chambers are registered against the center by `center_id` with a `label` and an optional `turnover_buffer_minutes` that defaults to 30 minutes; this buffer is the mandatory decompression-and-turnover gap the floor must leave after each dive. A newly registered chamber begins with an `occupied_slot_count` of zero — a conserved count of that chamber's sessions currently in `SCHEDULED` status.

A `PayerLiaison` configures coverage by creating a `PayerPolicy` against a `center_id` with a `payer_name`, an optional `requires_prior_auth` flag defaulting to true that states whether HBO or graft coverage needs a prior authorization, a `max_covered_hbo_sessions` cap, a `per_session_cents` covered amount per HBO session, and an optional `min_healing_pct_threshold` that defaults to 50 and expresses the minimum actual percentage of wound-area reduction required to keep coverage active at reassessment.

### 3.2. Referral Intake and the Patient Record

A patient enters the system when an `IntakeCoordinator` creates a `Patient` under a `center_id` with an `mrn`, a `full_name`, and the `payer_policy_id` linking the patient to their coverage. A patient begins in `INTAKE` status; the patient status enumeration also includes `IN_CARE`, `DISCHARGED`, and `TRANSFERRED`. A patient carries a `latest_wound_area_cm2` that starts at zero and always mirrors the `area_cm2` of that patient's most recent wound assessment, ordered by `assessed_at` descending with ties broken by `created_at` descending — the resource `id` is never used to break the tie.

The referring provider's request is captured as a `Referral` against a `patient_id`, with the `source_provider` name and a free-text `reason`. A referral begins in `RECEIVED`. If intake needs more from the referring provider, the coordinator moves a referral that is in `RECEIVED` into `NEEDS_INFO`; a referral not in `RECEIVED` cannot make this move and is rejected with `ERR_REFERRAL_NOT_RECEIVED`. Once the missing information arrives, the coordinator returns a referral that is in `NEEDS_INFO` back to `RECEIVED`; a referral not in `NEEDS_INFO` is rejected with `ERR_REFERRAL_NOT_NEEDS_INFO`. This `RECEIVED` and `NEEDS_INFO` pair forms a revision loop that may cycle any number of times.

A referral is accepted only from `RECEIVED`; the attempt fails with `ERR_REFERRAL_NOT_RECEIVED` from any other state. Acceptance additionally requires that at least one `WoundAssessment` already exists on file for the patient, without which the accept is rejected with `ERR_NO_ASSESSMENT_ON_FILE`. When both conditions hold, the referral becomes `ACCEPTED` and, as a cross-entity side effect, the patient advances from `INTAKE` to `IN_CARE`. A referral may instead be declined from `RECEIVED`, moving it to `DECLINED`; a decline from any other state fails with `ERR_REFERRAL_NOT_RECEIVED`. Both `ACCEPTED` and `DECLINED` are terminal.

### 3.3. Wound Assessment, Scoring, and Photo Documentation

A `WoundClinician` records a `WoundAssessment` for a patient by `patient_id`, supplying the `stage`, the `length_cm`, the `width_cm`, the `tissue_type`, and an optional `infected` flag that defaults to false. The record is append-only. Its `assessed_at` is stamped from the owning center's `current_utc` at the moment of recording.

Two computed fields are derived at recording time. The wound's `area_cm2` is the product of `length_cm` and `width_cm`, rounded half up to two decimal places. The `severity_score` is a weighted clinical score built as follows. Each stage contributes base points: `STAGE_1` contributes 1, `STAGE_2` contributes 2, `STAGE_3` contributes 4, `STAGE_4` contributes 8, and `UNSTAGEABLE` contributes 10. The wound area (the raw product of length and width, before rounding) selects an area multiplier: an area of at most 4 square centimeters gives a multiplier of 1.0; an area greater than 4 but at most 16 square centimeters gives 1.5; and an area strictly greater than 16 square centimeters gives 2.0 — so an area of exactly 16 uses 1.5 while an area just above 16 uses 2.0. The tissue type contributes a bonus: `GRANULATION` contributes 0, `EPITHELIAL` contributes −1, `SLOUGH` contributes 2, and `NECROTIC` contributes 4. The raw score is the stage points multiplied by the area multiplier, plus 5 if the wound is infected (and 0 otherwise), plus the tissue bonus. That raw value is rounded half up to a whole number and then clamped so that it is never below a floor of 1 and never above a ceiling of 100.

Recording an assessment refreshes the patient's `latest_wound_area_cm2` to the new assessment's area. It may also drive an automatic healing transition described in §3.4. A `WoundClinician` may attach a `PhotoDocument` to an assessment, supplying the `wound_assessment_id`, the `patient_id`, and the `image_uri`; the photo is append-only, and its `captured_at` is stamped from the center's `current_utc` at upload.

### 3.4. Treatment Plans and the Healing Trajectory

A `WoundClinician` opens a `TreatmentPlan` for a patient by `patient_id`, naming the `baseline_assessment_id` — the earliest measurement that anchors the healing trajectory — and a `debridement_supply_budget_cents` ceiling for covered supply spend on this plan. A new plan starts with its `status` of `DRAFT` and its `coverage_status` of `PENDING`, `provisional_covered_cents` of 0, `provisional_hbo_covered_cents` of 0, and `finalized_hbo_covered_cents` of 0.

Activation moves a plan from `DRAFT` to `ACTIVE`. It is permitted only when the plan is in `DRAFT` (otherwise `ERR_PLAN_NOT_DRAFT`), the patient is `IN_CARE` (otherwise `ERR_PATIENT_NOT_IN_CARE`), and the plan's `coverage_status` is anything other than `NOT_COVERED` (a `NOT_COVERED` plan is rejected with `ERR_COVERAGE_DENIED`). Activation increments the plan's `version` by one.

An `ACTIVE` plan may be suspended, moving it to `SUSPENDED`; a suspend attempt on a plan that is not `ACTIVE` fails with `ERR_PLAN_NOT_ACTIVE`. Suspension cascades: every one of the plan's HBO sessions still in `SCHEDULED` status is cancelled, transitioning each to `CANCELLED`, and each such cancellation decrements that session's chamber's `occupied_slot_count` by one; the plan's `provisional_hbo_covered_cents` is then recomputed, and the plan's `version` is incremented by one. A `SUSPENDED` plan may be resumed back to `ACTIVE`, permitted only when the plan is `SUSPENDED` (otherwise `ERR_PLAN_NOT_SUSPENDED`) and the patient is `IN_CARE` (otherwise `ERR_PATIENT_NOT_IN_CARE`); resuming increments the plan's `version` by one. The `ACTIVE` and `SUSPENDED` states form a cycle that may repeat.

The healing trajectory over a plan's patient is computed from the ordered series of that patient's wound assessments, sorted by `assessed_at` ascending with ties broken by `created_at` ascending; the resource `id` is never a decision input. The baseline area is the `area_cm2` of the assessment named by the plan's `baseline_assessment_id`. The latest area is the `area_cm2` of the most recent assessment (by `assessed_at` descending, ties by `created_at` descending), and the previous area is the `area_cm2` of the second-most-recent assessment. The **actual healing percentage** is the baseline area minus the latest area, divided by the baseline area, multiplied by 100, and rounded half up to two decimal places. The **projected healing percentage** is a forward-looking four-week projection: first compute a weekly reduction rate as the previous area minus the latest area, divided by the number of days between the previous and latest assessments (a strictly positive span), multiplied by 7; then take that weekly rate, divide by the baseline area, multiply by 100, and multiply by 4, round half up to two decimal places, and cap the result at 100.0.

When a new assessment is recorded on a patient whose plan is `ACTIVE`, the system re-evaluates healing: if the resulting actual healing percentage reaches 100 or more, or the patient's `latest_wound_area_cm2` has reached zero, the system automatically transitions that `ACTIVE` plan to `HEALED` and increments its `version` by one. `HEALED` and `CLOSED` are the plan's terminal states.

### 3.5. Payer Coverage and Prior Authorization

Coverage adjudication runs through the `PriorAuthorization`, which a `PayerLiaison` submits against a `treatment_plan_id` with a `requested_hbo_sessions` count, a `clinical_justification` narrative, and — populated later by the payer — an `info_request_note`. An authorization begins in `SUBMITTED`.

From `SUBMITTED`, the liaison may request additional information, moving the authorization to `ADDITIONAL_INFO_REQUESTED` and setting its `info_request_note`; a request-info attempt on an authorization not in `SUBMITTED` fails with `ERR_AUTH_NOT_SUBMITTED`. From `ADDITIONAL_INFO_REQUESTED`, the liaison resubmits, returning the authorization to `SUBMITTED`; a resubmit on an authorization not in `ADDITIONAL_INFO_REQUESTED` fails with `ERR_AUTH_NOT_AWAITING_INFO`. This forms a resubmission loop between `SUBMITTED` and `ADDITIONAL_INFO_REQUESTED`.

Approval is permitted only from `SUBMITTED` (otherwise `ERR_AUTH_NOT_SUBMITTED`). Approving moves the authorization to `APPROVED` and, as cross-entity effects, flips the plan's `coverage_status` to `COVERED`, recomputes the plan's `provisional_hbo_covered_cents`, and increments the plan's `version` by one. Denial is likewise permitted only from `SUBMITTED` (otherwise `ERR_AUTH_NOT_SUBMITTED`). Denying moves the authorization to `DENIED` and cascades: the plan's `coverage_status` flips to `NOT_COVERED`; every one of the plan's supply orders still in `SUBMITTED` status is rejected, transitioning each to `REJECTED`; each such rejection credits its `covered_cents` back out of the plan's `provisional_covered_cents`; and the plan's `version` is incremented by one. `APPROVED` and `DENIED` are terminal.

The plan's `coverage_status` is thus a derived reflection of the authorization outcome against the payer policy: `PENDING` until adjudicated, `COVERED` on approval, and `NOT_COVERED` on denial.

### 3.6. Advanced-Dressing and Graft Supply

A `WoundClinician` submits a `SupplyOrder` against a `treatment_plan_id`, naming the `supply_kind` and providing `line_items`, a list where each line carries a `unit_price_cents`, a `qty`, and a `coverage_rate` between zero and one inclusive. The submission also carries `expected_plan_version` for the optimistic-concurrency check of §2.7. An order begins in `SUBMITTED`.

The order's `covered_cents` is computed by a rounding-order-sensitive aggregation. For each line, the covered amount is that line's `unit_price_cents` multiplied by its `qty` multiplied by its `coverage_rate`, rounded half up to whole cents. The order's `covered_cents` is the sum of those per-line rounded amounts — the rounding happens per line first and the whole-cent results are then summed, never the reverse. Before the order is accepted, the budget is checked: the new order's `covered_cents` added to the plan's existing `provisional_covered_cents` must not exceed the plan's `debridement_supply_budget_cents`; if it would, the order is rejected with `ERR_SUPPLY_BUDGET_EXCEEDED`. On acceptance, the order's `covered_cents` is added to the plan's `provisional_covered_cents`, and the plan's `version` is incremented by one. The plan's `provisional_covered_cents` therefore always equals the sum of `covered_cents` across that plan's supply orders whose status is `SUBMITTED` or `APPROVED`.

A `PayerLiaison` may approve a supply order that is in `SUBMITTED`, moving it to `APPROVED`; an approve on an order not in `SUBMITTED` fails with `ERR_ORDER_NOT_SUBMITTED`. A `PayerLiaison` may reject a `SUBMITTED` order, moving it to `REJECTED` and crediting its `covered_cents` back out of the plan's `provisional_covered_cents`; a `WoundClinician` may cancel a `SUBMITTED` order, moving it to `CANCELLED` and likewise crediting its `covered_cents` back out of `provisional_covered_cents`. Both reject and cancel require the order to be in `SUBMITTED`, failing otherwise with `ERR_ORDER_NOT_SUBMITTED`. `APPROVED`, `REJECTED`, and `CANCELLED` are terminal.

### 3.7. Debridement Scheduling and Completion

A `WoundClinician` schedules a `DebridementProcedure` against a `treatment_plan_id`, naming the performing clinician by `clinician_id` and the closed scheduling interval `window_start` through `window_end`. The procedure begins in `SCHEDULED`. Two guards apply at scheduling. The referenced clinician must belong to the same center as the plan's patient, or the request is rejected with `ERR_CROSS_CENTER_REFERENCE` (§2.8). The referenced clinician's `role_kind` must be `WOUND`, or the request is rejected with `ERR_CLINICIAN_ROLE_MISMATCH`.

Debridement intervals are treated as **closed** intervals with no turnover buffer. A new procedure for a given clinician is rejected when there exists another `SCHEDULED` procedure for the same `clinician_id` whose closed interval strictly overlaps — that is, the new start falls before the existing end and the existing start falls before the new end. Two procedures that merely touch at an endpoint (the new start equal to the existing end) do not overlap and adjacent booking is permitted. A true overlap is rejected with `ERR_CLINICIAN_SLOT_CONFLICT`.

Completing a debridement is permitted only when the procedure is in `SCHEDULED` (otherwise `ERR_PROC_NOT_SCHEDULED`), the governing plan is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), and the patient is `IN_CARE` (otherwise `ERR_PATIENT_NOT_IN_CARE`). On completion, the procedure moves to `COMPLETED` and records `performed_by_user_id` as the completing user's `X-User-ID` — the segregation-of-duties record consulted in §3.9. A `SCHEDULED` procedure may instead be cancelled to `CANCELLED`; a cancel on a procedure not in `SCHEDULED` fails with `ERR_PROC_NOT_SCHEDULED`. `COMPLETED` and `CANCELLED` are terminal.

### 3.8. Hyperbaric Oxygen Sessions and the Dive Log

A `HyperbaricTech` schedules an `HboSession` against a `treatment_plan_id`, naming the assigned `chamber_id`, the dive interval `window_start` through `window_end`, and the prescribed `treatment_pressure_ata`, which must be strictly greater than 1.0. The request also carries `expected_plan_version` for the optimistic-concurrency check of §2.7, and the session's `dive_log_entries` defaults to an empty list at scheduling. A session begins in `SCHEDULED`.

Scheduling is subject to several guards beyond the version check. The chamber must belong to the same center as the plan's patient, or the request is rejected with `ERR_CROSS_CENTER_REFERENCE` (§2.8). The plan's `coverage_status` must be `COVERED`, or the request is rejected with `ERR_COVERAGE_NOT_ACTIVE`. HBO dive intervals are **half-open** intervals of the form covering the start up to but not including the end, and each is padded on the right by the chamber's `turnover_buffer_minutes`. A new session on a chamber is rejected when there exists any `SCHEDULED` session on that same chamber such that, with each interval extended on the right by the buffer, they intersect — precisely, the new start falls before the existing end plus the buffer and the existing start falls before the new end plus the buffer. Because the mandatory turnover buffer pads the right edge, two dives that merely touch (the new start equal to the existing end) still collide unless the buffer is zero. A conflict is rejected with `ERR_CHAMBER_SLOT_CONFLICT`. On a successful schedule, the chamber's `occupied_slot_count` is incremented by one, the plan's `provisional_hbo_covered_cents` is recomputed, and the plan's `version` is incremented by one.

Completing a session is permitted only when the session is in `SCHEDULED` (otherwise `ERR_SESSION_NOT_SCHEDULED`), the plan is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), and the request supplies a non-empty `dive_log_entries` list — each entry a record of a `minute`, an `spo2`, and an `hr` vitals reading — without which completion fails with `ERR_EMPTY_DIVE_LOG`. Completion persists the supplied `dive_log_entries`, moves the session to `COMPLETED`, decrements the chamber's `occupied_slot_count` by one, and recomputes the plan's `provisional_hbo_covered_cents`. A `SCHEDULED` session may instead be cancelled to `CANCELLED` (a cancel on a session not in `SCHEDULED` fails with `ERR_SESSION_NOT_SCHEDULED`); cancellation releases the chamber slot by decrementing `occupied_slot_count` by one and recomputes the plan's `provisional_hbo_covered_cents`. `COMPLETED` and `CANCELLED` are terminal.

HBO reimbursement is estimated against the patient's payer policy, using its `max_covered_hbo_sessions` as the cap and its `per_session_cents` as the rate. The **provisional** estimate counts the plan's sessions currently in `SCHEDULED` or `COMPLETED` status, takes the smaller of that count and the cap, and multiplies by the rate to yield `provisional_hbo_covered_cents`; this provisional figure is recomputed on every HBO scheduling, completion, or cancellation event and on prior-authorization approval. The **finalized** figure, computed at outcome reporting, counts only the plan's `COMPLETED` sessions, takes the smaller of that count and the cap, and multiplies by the rate to yield `finalized_hbo_covered_cents`. Both figures are whole cents.

### 3.9. Escalation to Acute Care

When a patient must be moved to a higher level of care, an `AttendingPhysician` initiates an `AcuteTransfer` against a `patient_id`, naming the `destination_facility` and the `clinical_reason`. The transfer begins in `INITIATED` and records `initiated_by_user_id` as the initiating physician's `X-User-ID`.

A strict segregation of duties governs initiation: the `AttendingPhysician` initiating a transfer must not be the same user (`X-User-ID`) who completed any `DebridementProcedure` on the patient's plan. If the initiating user's identifier matches the `performed_by_user_id` recorded on any completed debridement for the patient's plan, the initiation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Initiating a transfer cascades through the patient and plan: the patient moves from `IN_CARE` to `TRANSFERRED`; the patient's `ACTIVE` treatment plan is suspended to `SUSPENDED`; that plan's `SCHEDULED` HBO sessions are cancelled to `CANCELLED`; and each cancelled session decrements its chamber's `occupied_slot_count` by one. A transfer may be accepted, moving it from `INITIATED` to `ACCEPTED`; an accept on a transfer not in `INITIATED` fails with `ERR_TRANSFER_NOT_INITIATED`. A still-unaccepted transfer may be cancelled, moving it from `INITIATED` to `CANCELLED` and reverting the patient's status from `TRANSFERRED` back to `IN_CARE`; a cancel on a transfer not in `INITIATED` likewise fails with `ERR_TRANSFER_NOT_INITIATED`. `ACCEPTED` and `CANCELLED` are terminal.

### 3.10. Closing the Plan and Outcome Reporting

A `WoundClinician` closes a plan by generating its `OutcomeReport`. Closing is permitted only when the plan is in `ACTIVE` or `SUSPENDED` (otherwise `ERR_PLAN_NOT_CLOSEABLE`) and no HBO session for the plan remains in `SCHEDULED` status (otherwise `ERR_OPEN_SESSIONS_EXIST`). Closing moves the plan to `CLOSED`, creates the `OutcomeReport` in its terminal `FINAL` status, computes the plan's `finalized_hbo_covered_cents` and copies it onto the plan, and increments the plan's `version` by one. An outcome report is generated exactly once per plan.

The `OutcomeReport` is created against the plan's `treatment_plan_id` and captures the final accounting: its `actual_healing_pct` is the chronological actual healing percentage of §3.4 (baseline versus latest measurement); its `projected_healing_pct` is the forward-looking four-week projection of §3.4; its `finalized_hbo_covered_cents` is the finalized HBO reimbursement snapshot of §3.8 (counting only `COMPLETED` sessions); and its `meets_coverage_threshold` is true exactly when the `actual_healing_pct` is at least the patient's payer policy `min_healing_pct_threshold`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions — return `200 OK`. The single exception among mutating transitions is closing a plan, which creates a new `OutcomeReport` and therefore returns `201 Created`. Read operations return `200 OK`. In the table below, "All roles" means `IntakeCoordinator`, `WoundClinician`, `HyperbaricTech`, `PayerLiaison`, and `AttendingPhysician`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock for a center | All roles |
| POST | `/wound-care/centers` | Create a center | IntakeCoordinator |
| GET | `/wound-care/centers` | List centers | All roles |
| GET | `/wound-care/centers/{centerId}` | Get a center | All roles |
| POST | `/wound-care/clinicians` | Register a clinician | IntakeCoordinator |
| GET | `/wound-care/clinicians` | List clinicians, optionally by center | All roles |
| GET | `/wound-care/clinicians/{clinicianId}` | Get a clinician | All roles |
| POST | `/wound-care/chambers` | Register a hyperbaric chamber | IntakeCoordinator |
| GET | `/wound-care/chambers` | List chambers, optionally by center | All roles |
| GET | `/wound-care/chambers/{chamberId}` | Get a chamber | All roles |
| POST | `/wound-care/payer-policies` | Create a payer policy | PayerLiaison |
| GET | `/wound-care/payer-policies` | List payer policies, optionally by center | All roles |
| GET | `/wound-care/payer-policies/{policyId}` | Get a payer policy | All roles |
| POST | `/wound-care/patients` | Create a patient | IntakeCoordinator |
| GET | `/wound-care/patients` | List patients, optionally by center or policy | All roles |
| GET | `/wound-care/patients/{patientId}` | Get a patient | All roles |
| POST | `/wound-care/referrals` | Create a referral | IntakeCoordinator |
| GET | `/wound-care/referrals` | List referrals, optionally by patient | All roles |
| GET | `/wound-care/referrals/{referralId}` | Get a referral | All roles |
| POST | `/wound-care/referrals/{referralId}/request-info` | Move a referral to NEEDS_INFO | IntakeCoordinator |
| POST | `/wound-care/referrals/{referralId}/resubmit` | Return a referral to RECEIVED | IntakeCoordinator |
| POST | `/wound-care/referrals/{referralId}/accept` | Accept a referral | IntakeCoordinator |
| POST | `/wound-care/referrals/{referralId}/decline` | Decline a referral | IntakeCoordinator |
| POST | `/wound-care/wound-assessments` | Record a wound assessment | WoundClinician |
| GET | `/wound-care/wound-assessments` | List wound assessments, optionally by patient | All roles |
| GET | `/wound-care/wound-assessments/{assessmentId}` | Get a wound assessment | All roles |
| POST | `/wound-care/photo-documents` | Attach a photo document | WoundClinician |
| GET | `/wound-care/photo-documents` | List photo documents, optionally by assessment or patient | All roles |
| GET | `/wound-care/photo-documents/{photoId}` | Get a photo document | All roles |
| POST | `/wound-care/treatment-plans` | Create a treatment plan | WoundClinician |
| GET | `/wound-care/treatment-plans` | List treatment plans, optionally by patient or baseline assessment | All roles |
| GET | `/wound-care/treatment-plans/{planId}` | Get a treatment plan | All roles |
| POST | `/wound-care/treatment-plans/{planId}/activate` | Activate a plan | WoundClinician |
| POST | `/wound-care/treatment-plans/{planId}/suspend` | Suspend a plan | WoundClinician |
| POST | `/wound-care/treatment-plans/{planId}/resume` | Resume a suspended plan | WoundClinician |
| POST | `/wound-care/treatment-plans/{planId}/outcome-report` | Close a plan and generate its outcome report | WoundClinician |
| POST | `/wound-care/prior-authorizations` | Submit a prior authorization | PayerLiaison |
| GET | `/wound-care/prior-authorizations` | List prior authorizations, optionally by plan | All roles |
| GET | `/wound-care/prior-authorizations/{authId}` | Get a prior authorization | All roles |
| POST | `/wound-care/prior-authorizations/{authId}/request-info` | Payer requests additional info | PayerLiaison |
| POST | `/wound-care/prior-authorizations/{authId}/resubmit` | Resubmit after providing info | PayerLiaison |
| POST | `/wound-care/prior-authorizations/{authId}/approve` | Approve the authorization | PayerLiaison |
| POST | `/wound-care/prior-authorizations/{authId}/deny` | Deny the authorization | PayerLiaison |
| POST | `/wound-care/debridement-procedures` | Schedule a debridement procedure | WoundClinician |
| GET | `/wound-care/debridement-procedures` | List debridement procedures, optionally by plan or clinician | All roles |
| GET | `/wound-care/debridement-procedures/{procId}` | Get a debridement procedure | All roles |
| POST | `/wound-care/debridement-procedures/{procId}/complete` | Complete a debridement | WoundClinician |
| POST | `/wound-care/debridement-procedures/{procId}/cancel` | Cancel a scheduled debridement | WoundClinician |
| POST | `/wound-care/hbo-sessions` | Schedule an HBO session | HyperbaricTech |
| GET | `/wound-care/hbo-sessions` | List HBO sessions, optionally by plan or chamber | All roles |
| GET | `/wound-care/hbo-sessions/{sessionId}` | Get an HBO session | All roles |
| POST | `/wound-care/hbo-sessions/{sessionId}/complete` | Complete an HBO session | HyperbaricTech |
| POST | `/wound-care/hbo-sessions/{sessionId}/cancel` | Cancel a scheduled HBO session | HyperbaricTech |
| POST | `/wound-care/supply-orders` | Submit a supply order | WoundClinician |
| GET | `/wound-care/supply-orders` | List supply orders, optionally by plan | All roles |
| GET | `/wound-care/supply-orders/{orderId}` | Get a supply order | All roles |
| POST | `/wound-care/supply-orders/{orderId}/approve` | Approve a supply order | PayerLiaison |
| POST | `/wound-care/supply-orders/{orderId}/reject` | Reject a supply order | PayerLiaison |
| POST | `/wound-care/supply-orders/{orderId}/cancel` | Cancel a supply order | WoundClinician |
| POST | `/wound-care/acute-transfers` | Initiate an acute transfer | AttendingPhysician |
| GET | `/wound-care/acute-transfers` | List acute transfers, optionally by patient | All roles |
| GET | `/wound-care/acute-transfers/{transferId}` | Get an acute transfer | All roles |
| POST | `/wound-care/acute-transfers/{transferId}/accept` | Accept a transfer | AttendingPhysician |
| POST | `/wound-care/acute-transfers/{transferId}/cancel` | Cancel an unaccepted transfer | AttendingPhysician |
| GET | `/wound-care/outcome-reports` | List outcome reports, optionally by plan | All roles |
| GET | `/wound-care/outcome-reports/{reportId}` | Get an outcome report | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CENTER_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_AUTH_NOT_FOUND` | 404 Not Found |
| `ERR_PROC_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_CHAMBER_NOT_FOUND` | 404 Not Found |
| `ERR_CLINICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |
| `ERR_REFERRAL_NOT_RECEIVED` | 409 Conflict |
| `ERR_REFERRAL_NOT_NEEDS_INFO` | 409 Conflict |
| `ERR_NO_ASSESSMENT_ON_FILE` | 409 Conflict |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_SUSPENDED` | 409 Conflict |
| `ERR_PLAN_NOT_CLOSEABLE` | 409 Conflict |
| `ERR_PATIENT_NOT_IN_CARE` | 409 Conflict |
| `ERR_COVERAGE_DENIED` | 409 Conflict |
| `ERR_OPEN_SESSIONS_EXIST` | 409 Conflict |
| `ERR_AUTH_NOT_SUBMITTED` | 409 Conflict |
| `ERR_AUTH_NOT_AWAITING_INFO` | 409 Conflict |
| `ERR_PROC_NOT_SCHEDULED` | 409 Conflict |
| `ERR_SESSION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ORDER_NOT_SUBMITTED` | 409 Conflict |
| `ERR_TRANSFER_NOT_INITIATED` | 409 Conflict |
| `ERR_CROSS_CENTER_REFERENCE` | 409 Conflict |
| `ERR_CLINICIAN_ROLE_MISMATCH` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_CHAMBER_SLOT_CONFLICT` | 409 Conflict |
| `ERR_CLINICIAN_SLOT_CONFLICT` | 409 Conflict |
| `ERR_COVERAGE_NOT_ACTIVE` | 409 Conflict |
| `ERR_SUPPLY_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_EMPTY_DIVE_LOG` | 409 Conflict |
