# Pt Rehab API — Product Requirements Document

## 1. Introduction

Outpatient physical therapy clinics juggle a tangle of responsibilities that rarely fit cleanly into a single information system: initial evaluations and periodic re-evaluations, pre-authorized unit-hour pools, home exercise programs, Medicare MIPS quality reporting, formal discharge assessments, VA-issued veteran referrals, and the federally mandated Capped Plan of Care annual dollar limit. The interplay of these concerns is the system's true complexity — a single visit being finalized for billing touches the visit itself, its authorization grant's running unit consumption, its parent plan of care's cumulative billed dollars, and that plan's posture against its capped dollar limit, while simultaneously requiring the billing clerk to demonstrate that they have observed the most recent revision of the plan.

This document specifies the REST API that governs that workflow end-to-end. The audience is the engineering team building the service: every patient, therapist, plan of care, evaluation, authorization grant, visit, home exercise program, MIPS quality measure, discharge assessment, and veteran referral the system manages — together with their lifecycles, calculations, validation rules, role authorizations, and concurrency guarantees — is described below.

## 2. Global Specifications & System-Wide Principles

The principles that follow apply across every endpoint defined in §4. They are deliberately written as cross-cutting rules so that the workflow narratives in §3 can focus on business logic without restating envelope, auth, and concurrency mechanics for each operation.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which uniquely identifies the acting principal, and `X-User-Role`, which names that principal's operational capacity. Either header missing — or both — causes the request to be rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A call whose role is not on the endpoint's authorized list (see §4) is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles, spelled as written: `PlatformAdmin`, `CaseManager`, `Therapist`, `BillingClerk`, and `VAReferralCoordinator`. Their identity semantics differ in a way that matters for ownership checks.

`Therapist` is an **entity-backed** role: when `X-User-Role` is `Therapist`, the value of `X-User-ID` must be the `id` of an existing `Therapist` record. If it is not, the request is rejected with `ERR_FORBIDDEN`. Ownership checks on any resource that references a `Therapist` (for example, a `Visit` whose `therapist_id` names the delivering clinician, or an `Evaluation` whose `therapist_id` names the performer) compare that resource's foreign-key field to `X-User-ID`.

`PlatformAdmin`, `CaseManager`, `BillingClerk`, and `VAReferralCoordinator` are **opaque** roles: when `X-User-Role` is any of those four, `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server may log the value for audit but does not compare it to the `id` of any record.

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

List endpoints are paginated through two query-string parameters. The `limit` parameter sets the maximum page size; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless an endpoint's prose says otherwise, list endpoints return rows sorted by `created_at` ascending. Each list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted entity in this system — `Patient`, `Therapist`, `VeteranReferral`, `PlanOfCare`, `Evaluation`, `AuthorizationGrant`, `Visit`, `HomeExerciseProgram`, `MIPSQualityMeasure`, and `DischargeAssessment` — carries four system-managed fields in addition to its domain attributes:

- `id` is a server-minted UUID. The value is plain — there is no type prefix.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits captured when the row is first written.
- `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation of the row.
- `version` is an integer that starts at 1 on creation and increments by one with every mutation. It is the basis for the optimistic concurrency contract described in §2.6.

Every entity in this system declares `common_fields: true` in the underlying model, which means none of them is exempt from `updated_at` or `version`. There are no immutable-after-creation resources here.

### 2.5. Nested Resource Retrieval and Path Validation

Many of the API's paths interpolate a resource identifier — for instance the visit lifecycle endpoints all hang off a `{id}` segment that names a `Visit`. The server validates such path segments strictly **left to right**. If the identifier in any position does not name an existing row, the request is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) for that segment, before any later segment or any body field is inspected. The same `ERR_RESOURCE_NOT_FOUND` is also raised when any foreign-key identifier present in the request body — `patient_id`, `primary_therapist_id`, `veteran_referral_id`, `plan_of_care_id`, `therapist_id`, `authorization_grant_id`, `prescribed_by_therapist_id`, `reporting_therapist_id`, `assessing_therapist_id` — names a row that does not exist.

### 2.6. Optimistic Concurrency on Plans of Care

The `PlanOfCare` aggregate is the single concurrency root in this system. Two write operations carry an optimistic-concurrency contract against `PlanOfCare.version`:

1. **Recertifying a plan.** A recertification request must include `expected_plan_of_care_version` in its body. The value must match the current `version` of the target `PlanOfCare` exactly. If another writer (typically a visit-finalize on the same plan, which silently advances `version` through the cumulative-billed cascade) has bumped the plan's `version` since the client last read it, the recertification is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). The client must re-read the plan, recompute its decision against the fresh `version`, and try again.
2. **Finalizing a visit.** A visit-finalize request must include `expected_plan_of_care_version` in its body, where the value is the client's last-observed `version` of the parent `PlanOfCare` (reached through the visit's `authorization_grant_id` → grant's `plan_of_care_id`). When another finalize, or a recertification, has already advanced `PlanOfCare.version` since the client read it, this finalize is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412) — preventing two billing clerks from racing each other to push a plan past its capped dollar limit on the basis of stale `cumulative_billed_cents`.

These are the only two endpoints that take `expected_plan_of_care_version`. No other write endpoint in the API accepts a version field; every other mutation succeeds without an OCC pin.

### 2.7. Capped Plan of Care — the Fiscal Backbone

Each `PlanOfCare` is governed by a Capped Plan of Care annual dollar limit. The limit is denominated in integer cents on the field `capped_dollar_limit_cents`, and it is **pinned once** at the moment the plan moves out of draft. The cap depends on the patient's `insurance_type` at activation: a `MEDICARE` plan is capped at twenty thousand cents (two hundred dollars), a `COMMERCIAL` plan at fifty thousand cents (five hundred dollars), a `MEDICAID` plan at ten thousand cents (one hundred dollars), a `VA_TRICARE` plan at thirty thousand cents (three hundred dollars), and a `SELF_PAY` plan at one hundred thousand cents (one thousand dollars). Pinning is one-shot: a subsequent change to the patient's `insurance_type` does not retroactively rewrite the plan's `capped_dollar_limit_cents`.

Running against the cap is the integer-cent field `cumulative_billed_cents`, the sum of `billed_cents` over every `FINALIZED` visit reachable through any authorization grant of the plan. Each visit finalize refreshes that sum, then the system re-evaluates the plan's `capped_status` posture. The posture is one of three exact strings: `UNDER_CAP` when `cumulative_billed_cents` is strictly less than ninety percent of `capped_dollar_limit_cents`; `AT_CAP_WARNING` when `cumulative_billed_cents` is at least ninety percent of `capped_dollar_limit_cents` and not yet over the cap (the ninety-percent boundary is inclusive); and `EXCEEDED` when `cumulative_billed_cents` is strictly greater than `capped_dollar_limit_cents`. A newly activated plan starts at `UNDER_CAP`.

### 2.8. Precision and Rounding

All money values are integer cents — `billed_cents`, `capped_dollar_limit_cents`, `cumulative_billed_cents` — and arithmetic on them never produces fractions. The one place a half-cent could arise is the multi-procedure payment reduction inside the per-visit billing formula (§3.5), where a per-CPT rate is multiplied by 0.5 to obtain a reduced per-unit price; that reduced per-unit price is rounded half-up to the nearest cent **per unit**, before being multiplied by the count of reduced units and summed with the first-unit price. The ordering matters: it is round-per-unit-then-sum, not sum-then-round. The MIPS composite score is the other rounded quantity in the system; it is reported to two decimal places using round-half-up (§3.7).

### 2.9. Hierarchical Consistency and Cascading State

Mutations in this system propagate beyond the resource that named the endpoint. A single activate, finalize, or discharge call can mutate several rows in a single chain:

- Activating a plan can cascade up to two hops: into the linked `VeteranReferral`, and through that referral into other draft plans that share it (§3.2).
- Finalizing a visit cascades two hops on the parent plan: refreshing `cumulative_billed_cents`, then re-evaluating `capped_status` (§3.5).
- Discharging a plan cascades three hops on its children: cancelling scheduled visits, recomputing `units_consumed` on each affected `AuthorizationGrant`, then cancelling those grants if their window is still open (§3.6).

Every row mutated by any hop of these cascades has its `updated_at` refreshed and its `version` incremented. There are no "silent" mutations: if a row's domain content changes — even by side-effect from another endpoint — its `version` ticks.

### 2.10. Time, Test-Driving the Clock, and Auto-Transitions

Several transitions in §3 are time-gated rather than client-initiated. The system exposes an admin-only test-driving capability that advances the server's logical UTC clock to a supplied instant, given in the request body as the field `to_iso8601`, and returns a body containing the new `current_utc`. Advancing the clock re-evaluates every time-gated auto-transition: any `ACTIVE` `PlanOfCare` whose `certified_end_date` is now within seven days transitions to `RECERT_DUE`; any `RECERT_DUE` `PlanOfCare` whose `certified_end_date` has now passed transitions to `EXPIRED` (with its own cascade — see §3.6); any `AuthorizationGrant` whose `effective_to` is now in the past transitions to `EXPIRED`; and any `ISSUED` `VeteranReferral` whose `expires_on` is now in the past transitions to `EXPIRED`. The capability exists for deterministic testing — its body parameter `to_iso8601` is the sole input.

### 2.11. Validation Priority Ordering

When more than one validation could fire on a single request, the server applies them in a fixed priority order so that the surfaced `error_id` is predictable. The ordering is, from highest priority to lowest: authentication (the missing-header check that produces `ERR_UNAUTHENTICATED`); role permission (`ERR_FORBIDDEN` for an unauthorized role, including the entity-backed check on `Therapist` that the `X-User-ID` actually names a `Therapist` row); path-segment existence, then body foreign-key existence (`ERR_RESOURCE_NOT_FOUND`); current-state preconditions (`ERR_INVALID_STATE`); the OCC stale-version check (`ERR_STALE_PLAN_VERSION`); business-safety rules (`ERR_VA_REFERRAL_REQUIRED`, `ERR_MIPS_ELIGIBILITY`, `ERR_CAPPED_POC_EXCEEDED`); business-constraint rules (`ERR_THERAPIST_LICENSE_INVALID`, `ERR_VA_VISIT_CAP_EXCEEDED`); business-temporal rules (`ERR_VISIT_OUT_OF_WINDOW`, `ERR_THERAPIST_DOUBLE_BOOKED`, `ERR_GRANT_WINDOW_OVERLAP`); business-fiscal rules (`ERR_AUTHORIZATION_EXHAUSTED`); business-referential rules (`ERR_GOALS_INCONSISTENT`, `ERR_RECERT_WINDOW_EXCEEDED`, `ERR_VETERAN_FLAG_REQUIRED`); and finally generic input validation (`ERR_INVALID_REQUEST`). The practical consequence is that a request can fail only one rule at a time — a payload with both a missing required field and a license mismatch surfaces the higher-priority license error, never the generic input error, because the license rule sits at the business-constraint level and the generic check sits last.

## 3. Business Logic & Workflows

This section walks the system's lifecycle from intake to discharge. Field names appear in narrative context; for the canonical request bodies of any single endpoint, two halves of the same payload may live in different subsections — a deliberate scattering that mirrors the way a real clinic's procedures spread across roles and time.

### 3.1. Patient Intake and Therapist Onboarding

A patient enters the system through a creation call by a `CaseManager` or `PlatformAdmin`. The payload supplies `full_name` (the patient's legal name, between 1 and 120 characters), `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form, and `insurance_type` from the closed enum `MEDICARE`, `COMMERCIAL`, `MEDICAID`, `VA_TRICARE`, `SELF_PAY`. The `is_veteran` flag is optional and defaults to false. There is a referential coupling between these two inputs: if `insurance_type` is `VA_TRICARE`, then `is_veteran` must be true; submitting a `VA_TRICARE` patient with `is_veteran` unset or false is rejected with `ERR_VETERAN_FLAG_REQUIRED` (HTTP 422). On successful creation the patient is persisted with `status` `ACTIVE`. The patient lifecycle has two further values, `DISCHARGED` and `INACTIVE`; the `DISCHARGED` transition is driven from §3.6 and there is no client-initiated path back from it.

Therapists are onboarded by `PlatformAdmin` alone. The payload carries `full_name`, the ten-digit `npi_number` (the National Provider Identifier, which must be unique across the `Therapist` table), the two-letter `license_state` US state code where the therapist holds licensure, and the optional `medicare_provider_enrolled` flag that defaults to false. The `medicare_provider_enrolled` flag is the gate for assignment to Medicare patients and for participation in MIPS quality reporting (§3.7).

### 3.2. Veteran Referrals and Plan-of-Care Creation

A veteran's care begins outside the clinic: a `VAReferralCoordinator` (or `PlatformAdmin`) issues a referral that names the `patient_id` of the referred veteran, the issuing facility's `referring_va_facility_code` (an uppercase identifier of four to six characters), and the `referral_authorization_number` (which must be unique across the `VeteranReferral` table). The referral carries a ceiling on the visit count it can support — `max_authorized_visits`, an integer between 1 and 60 inclusive — and an inclusive `expires_on` date in ISO 8601 form. A new referral is persisted with `status` `ISSUED`.

`PlanOfCare` rows are created by a `Therapist` or `CaseManager` in the `DRAFT` state. The payload supplies the `patient_id` of the patient receiving care, the `primary_therapist_id` of the therapist of record, the ICD-10 diagnosis code `diagnosis_icd10` (uppercase, format like `M54.5`), and the inclusive certification window: `certified_start_date` and `certified_end_date`. The end date must be on or after the start date, and the two together must span no more than ninety days. When the patient is a VA_TRICARE patient, the payload must also include `veteran_referral_id` naming the referral that authorizes this plan; for non-VA patients the field must be omitted. The plan is persisted at `status` `DRAFT` and `capped_status` `UNDER_CAP`; `capped_dollar_limit_cents` and `cumulative_billed_cents` remain unpinned at this stage (the cap is set at activation, per §2.7; cumulative billed starts at zero).

The plan also has an `initial_evaluation_id` field that is populated by the system the first time an `INITIAL` evaluation lands on the plan (see §3.3). Until that happens, the field is null.

Activation moves the plan from `DRAFT` to `ACTIVE`. The transition can only be invoked by a `Therapist`, and it requires that an `INITIAL` evaluation already exists with `plan_of_care_id` pointing back to this plan. For VA_TRICARE plans there are two additional preconditions: the plan must have a `veteran_referral_id`, the referenced `VeteranReferral` must be in `ISSUED` status, and the plan's `certified_end_date` must fall on or before the referral's `expires_on`. Violating any of the VA-specific preconditions surfaces `ERR_VA_REFERRAL_REQUIRED` (HTTP 422); the missing-initial-evaluation precondition surfaces `ERR_INVALID_STATE` (HTTP 409).

Activation is the moment the cap is pinned. The system reads the patient's `insurance_type` and writes the corresponding cents value (per §2.7) into `capped_dollar_limit_cents`. `capped_status` is set to `UNDER_CAP`. The plan's `version` increments. When the plan is VA-backed, two further cascade hops fire. First, the linked `VeteranReferral` transitions from `ISSUED` to `CONSUMED` — its own `version` increments and its `updated_at` refreshes. Second, every **other** plan that still references that same referral and remains in `DRAFT` cascades to `EXPIRED`; each such sibling has its `updated_at` refreshed and its `version` incremented. This cascade chain — `DRAFT → ACTIVE` on the activated plan, `ISSUED → CONSUMED` on the referral, `DRAFT → EXPIRED` on the sibling draft plans — is the intended serialization point for the "one referral, one active plan" invariant.

### 3.3. Evaluations and the Eight-Minute Rule

Evaluations are recorded only by a `Therapist`. The payload names `plan_of_care_id`, the performing `therapist_id`, the `evaluation_kind` from the enum `INITIAL`, `RE_EVALUATION`, `DISCHARGE`, the `performed_on` date in ISO 8601, the standardized `functional_score` (an integer from 0 to 100 inclusive, higher being better), and the therapist-reported `minutes_spent` for the session (an integer at least 8 and at most 240). On create, the system computes the `billable_units` field for the evaluation by applying CMS's eight-minute rule to `minutes_spent`: if `minutes_spent` is less than 8, `billable_units` is 0; from 8 through 22 inclusive it is 1; from 23 through 37 inclusive it is 2; from 38 through 52 inclusive it is 3; from 53 through 67 inclusive it is 4; and at 68 or more it is the result of subtracting 7 from `minutes_spent`, dividing by 15, and rounding up to the next integer. The fifteen-minute and eight-minute constants in that rule are the unit-minutes and minimum billable minutes for the entire system — they reappear on visit-side calculations in §3.4 and §3.5.

There is a one-shot side effect on the plan: the first time an `INITIAL` evaluation is recorded against a plan, the system writes the new evaluation's `id` into the plan's `initial_evaluation_id` and increments the plan's `version`. Subsequent `INITIAL` evaluations (or any non-INITIAL evaluation) do not retouch `initial_evaluation_id`. A `RE_EVALUATION` whose `performed_on` falls within the current certification window is the precondition for the recertification transition described in §3.6.

### 3.4. Authorization Grants — the Unit-Hour Pool

Care under a plan is paid for out of one or more `AuthorizationGrant` rows that pre-allocate a pool of 15-minute units. A `CaseManager` or `PlatformAdmin` creates a grant by supplying the `plan_of_care_id`, the `total_units_granted` (an integer from 1 to 600 inclusive), and the inclusive window `effective_from` and `effective_to` dates. For VA-backed plans the optional `veteran_referral_id` may be set; for non-VA plans it must be null. The grant's `effective_to` must be on or before the parent plan's `certified_end_date`. The grant is persisted at `status` `ACTIVE` with `units_consumed` and `units_finalized` both zero.

Multiple grants are permitted on a single plan, but their date windows are mutually exclusive under **closed-closed** semantics: two grants on the same plan whose `[effective_from, effective_to]` intervals share even a single day are rejected with `ERR_GRANT_WINDOW_OVERLAP` (HTTP 409). The closed-closed framing means that adjacent grants which touch on the same date — for example one ending on the 14th and another starting on the 14th — are treated as overlapping and rejected. This is intentionally stricter than the visit-overlap rule below, and the asymmetry between visit half-open semantics and grant closed-closed semantics is deliberate.

`units_consumed` is a running sum recomputed by the system whenever any visit on the grant changes status: the system enumerates the grant's visits whose `status` is one of `SCHEDULED`, `COMPLETED`, or `FINALIZED`, orders them by `created_at` ascending and then by `id` ascending, and sums each visit's `planned_units` while the visit is still `SCHEDULED` or its `billable_units` once the visit has reached `COMPLETED` or `FINALIZED`. Visits in `CANCELLED` or `NO_SHOW` status contribute nothing. `units_finalized` is the simpler companion: a running sum, ordered the same way, of `billable_units` over visits whose `status` is `FINALIZED`.

When a visit-side mutation pushes `units_consumed` to a value at least equal to `total_units_granted` (boundary inclusive: `units_consumed` ≥ `total_units_granted`), the grant auto-transitions from `ACTIVE` to `EXHAUSTED`. Subsequent attempts to complete a visit on the grant are rejected as ineligible. A grant may also transition out of `ACTIVE` for reasons unrelated to consumption: the clock-advance described in §2.10 transitions a grant to `EXPIRED` if its `effective_to` has passed; a discharge of the parent plan transitions the grant to `CANCELLED` per §3.6.

### 3.5. Visit Lifecycle — Scheduling, Completion, and Finalization

A visit is the unit of care delivery. A `Therapist` or `CaseManager` schedules a visit by supplying the `authorization_grant_id` of the funding grant, the delivering `therapist_id`, the visit's UTC interval `scheduled_start_utc` and `scheduled_end_utc` (with `scheduled_end_utc` strictly after `scheduled_start_utc`), the `planned_minutes` (an integer at least 8 and at most 240), and the `cpt_code` from the closed enum `CPT_97110_THER_EX`, `CPT_97112_NEURO_REED`, `CPT_97140_MANUAL`, `CPT_97530_THER_ACT`. A new visit is persisted at `status` `SCHEDULED` with `actual_minutes` left null and `billable_units` and `billed_cents` both zero.

At schedule time the system pre-computes `planned_units` — the forward-looking reservation against the grant — by running the eight-minute rule on `planned_minutes`. The rule is identical to the one used for evaluations in §3.3: under 8 minutes yields 0 units, 8 through 22 yields 1, 23 through 37 yields 2, 38 through 52 yields 3, 53 through 67 yields 4, and at 68 or more the units are computed by subtracting 7 from `planned_minutes`, dividing by 15, and rounding up to the next integer. The grant's `units_consumed` is then recomputed using the running-sum procedure from §3.4. The forward-looking variant is **optimistic**: it reserves units based on a forecast and may later be revised downward (or upward) when actuals come in.

Scheduling is subject to four business checks. First, both `scheduled_start_utc` and `scheduled_end_utc` must fall within both the grant's `[effective_from, effective_to]` window and the parent plan's `[certified_start_date, certified_end_date]` window; a visit that escapes either window is rejected with `ERR_VISIT_OUT_OF_WINDOW` (HTTP 422). Second, the new visit's `[scheduled_start_utc, scheduled_end_utc)` interval must not overlap any other `SCHEDULED` or `COMPLETED` visit on the same `therapist_id` — overlap is evaluated under **half-open** semantics, which means that two adjacent visits touching at exactly the same UTC instant (one ending and another starting at the same instant) are permitted; a true overlap is rejected with `ERR_THERAPIST_DOUBLE_BOOKED` (HTTP 409). Third, if the visit would push `units_consumed` past `total_units_granted` on the grant, the scheduling call is rejected with `ERR_AUTHORIZATION_EXHAUSTED` (HTTP 409). Fourth, when the parent patient's plan is backed by a veteran referral, the count of visits already linked through any grant to that referral plus this new visit must not exceed the referral's `max_authorized_visits`; a violation surfaces `ERR_VA_VISIT_CAP_EXCEEDED` (HTTP 409). The delivering therapist's `license_state` must also be valid for the patient — see the licensing rule in §3.10.

The transition from `SCHEDULED` to `COMPLETED` is driven by the delivering `Therapist` and supplies `actual_minutes` — an integer at least 8 and at most 240 — in the payload. The transition is only permitted when the parent plan's `status` is `ACTIVE` or `RECERT_DUE`, the funding grant's `status` is `ACTIVE`, and today (UTC) is on or after the date portion of `scheduled_start_utc`. On success the visit's `billable_units` is recomputed from `actual_minutes` using the chronological variant of the eight-minute rule — same buckets as the planned-units calculation, but operating on actually-delivered minutes rather than a forecast. The two variants will agree when `actual_minutes` equals `planned_minutes` and may diverge otherwise: a visit planned for 60 minutes reserves four units at schedule time, but if only 30 minutes are actually delivered, `billable_units` resolves to two. The grant's `units_consumed` is then recomputed (a `SCHEDULED` visit's `planned_units` contribution is replaced by the `COMPLETED` visit's `billable_units`), and if `units_consumed` has reached or exceeded `total_units_granted` the grant auto-transitions to `EXHAUSTED` (§3.4). When the grant has already reached `EXHAUSTED` or this completion would drive it past the cap, the call is rejected with `ERR_AUTHORIZATION_EXHAUSTED`.

Finalization moves a `COMPLETED` visit to `FINALIZED` and is the sole responsibility of a `BillingClerk`. The payload's only field is `expected_plan_of_care_version`, the client's last-observed `version` of the visit's parent plan (reached through the grant's `plan_of_care_id`). The finalize is allowed only when the visit is already `COMPLETED`, the supplied `expected_plan_of_care_version` matches the plan's current `version` (otherwise the request is rejected with `ERR_STALE_PLAN_VERSION` per §2.6), and the plan's `capped_status` is not `EXCEEDED` at the instant of finalize (otherwise `ERR_CAPPED_POC_EXCEEDED` is raised with HTTP 409).

On success the system computes `billed_cents` for the visit. Each CPT code has a per-unit rate in cents — `CPT_97110_THER_EX` at 3200, `CPT_97112_NEURO_REED` at 3900, `CPT_97140_MANUAL` at 3500, `CPT_97530_THER_ACT` at 3700. When the visit has at most one `billable_unit`, `billed_cents` is simply the unit rate (or zero, if `billable_units` is zero). When the visit has more than one unit, the **multiple-procedure payment reduction** applies: the first unit bills at the full per-CPT rate, and every unit beyond the first bills at a reduced per-unit rate equal to the CPT rate multiplied by one-half. The reduced per-unit rate is rounded half-up to the nearest cent **per unit, before** being multiplied by the number of reduced units and added to the first unit's full-rate price. The order of operations is fixed: round per unit first, then sum. For example, a four-unit visit at `CPT_97140_MANUAL` (rate 3500) bills the first unit at 3500 cents, computes a reduced per-unit price of 1750 cents (half of 3500, no rounding needed), and totals 3500 + 1750 × 3 = 8750 cents.

Finalization then cascades up the aggregate. The grant's `units_finalized` is recomputed by re-summing `billable_units` over visits in `FINALIZED` status, ordered by `created_at` then `id`. The plan's `cumulative_billed_cents` is refreshed by summing `billed_cents` over every `FINALIZED` visit reachable through any of the plan's grants, again ordered by `created_at` then `id` for determinism. Finally, the plan's `capped_status` is re-evaluated against the refreshed `cumulative_billed_cents` per the three-bucket rule in §2.7. The plan's `version` increments and its `updated_at` refreshes — these are the side effects that make the OCC pin on `expected_plan_of_care_version` non-trivial.

Two more visit-side transitions are available before completion. A `Therapist` (or a `PlatformAdmin`) may cancel a `SCHEDULED` visit, moving it to `CANCELLED`; the precondition is that today (UTC) is on or before the date portion of `scheduled_start_utc` minus one day, unless the caller's role is `PlatformAdmin`, who may cancel at any time. The grant's `units_consumed` is recomputed on cancellation. A `Therapist` may also mark a `SCHEDULED` visit as `NO_SHOW`, which is permitted only when today (UTC) is strictly after the date portion of `scheduled_start_utc`; the grant's `units_consumed` is recomputed accordingly. Once a visit reaches `FINALIZED`, `CANCELLED`, or `NO_SHOW`, no further transitions are available.

### 3.6. Recertification, Discharge, and Plan Termination

A plan in `ACTIVE` status reaches `RECERT_DUE` automatically when the server clock advances to a date strictly after `certified_end_date` minus seven days and on or before `certified_end_date`. The transition is purely a posture flag — no children change state. From `RECERT_DUE`, two paths are possible.

Recertification, driven by a `Therapist`, moves the plan back to `ACTIVE` and refreshes its certification window. The payload supplies `expected_plan_of_care_version`, a new `certified_start_date`, and a new `certified_end_date`. Three preconditions apply: a `RE_EVALUATION` evaluation must already exist for the plan with `performed_on` on or after the current `certified_start_date` and on or before the current `certified_end_date`; the supplied `expected_plan_of_care_version` must match the plan's current `version` (otherwise `ERR_STALE_PLAN_VERSION` per §2.6); and the new `certified_end_date` must be on or before the old `certified_end_date` plus ninety days (a violation surfaces `ERR_RECERT_WINDOW_EXCEEDED` with HTTP 422). On success, both certification dates are overwritten with the payload values and the plan's `version` increments.

If the clock instead advances past `certified_end_date` while the plan is still `RECERT_DUE`, the plan auto-transitions to `EXPIRED`. The expiry has three cascade effects: every `SCHEDULED` visit reachable through any of the plan's grants is cancelled, every `AuthorizationGrant` whose `effective_to` has now passed transitions from `ACTIVE` to `EXPIRED`, and every `ACTIVE` `HomeExerciseProgram` under the plan is discontinued.

Active plans can also be discharged explicitly. A `Therapist` discharges a plan after recording a `DischargeAssessment` against it (see §3.8). The transition `ACTIVE → DISCHARGED` is the trigger for a depth-three cascade on the plan's children. First hop: every `SCHEDULED` visit reachable through any `AuthorizationGrant` of this plan is cancelled (`SCHEDULED → CANCELLED`), with each cancelled visit having its `updated_at` refreshed and `version` incremented. Second hop: each affected grant has its `units_consumed` recomputed by the running-sum procedure (the cancelled visits drop out of the eligible set). Third hop: any `AuthorizationGrant` whose effective window is still open transitions `ACTIVE → CANCELLED`, with its `updated_at` and `version` updated. In parallel, every `ACTIVE` `HomeExerciseProgram` under the plan transitions to `DISCONTINUED`. Finally, the patient's own `status` flips from `ACTIVE` to `DISCHARGED` only when no other plan referencing the same `patient_id` is still in `ACTIVE` status; if the patient has another active plan, the patient remains `ACTIVE`. The plan's own `version` increments as part of the discharge.

The patient's `status` may also remain `ACTIVE` after a peer plan moves to `EXPIRED` via the clock cascade above; the `Patient` enum's third value, `INACTIVE`, is reserved for administrative deactivation paths that are not exposed in this version of the API.

### 3.7. Home Exercise Programs and MIPS Quality Reporting

Home exercise programs are prescribed by a `Therapist`. The payload names `plan_of_care_id`, the `prescribed_by_therapist_id` of the prescribing clinician, the `exercise_count` (an integer between 1 and 20 inclusive), the `weekly_frequency` (an integer between 1 and 14 inclusive), and the `prescribed_on` date in ISO 8601 form which must fall on or after the parent plan's `certified_start_date`. Prescribing a new program automatically supersedes any prior `ACTIVE` program on the same plan: each prior `ACTIVE` row transitions to `SUPERSEDED` (with `updated_at` refreshed and `version` incremented), and the new row is persisted at `status` `ACTIVE`. There is no client-initiated transition to `DISCONTINUED` — that state is reached only through the plan-discharge or plan-expiry cascades described in §3.6.

MIPS quality measures wrap a different concern: reporting outcomes to Medicare for the Merit-based Incentive Payment System. Only a `Therapist` may create or modify a measure, and only `PlatformAdmin` may adjudicate one. The creation payload names the `patient_id`, the `plan_of_care_id`, the `reporting_therapist_id`, the `measure_code` from the closed enum `MIPS128_FALL_RISK`, `MIPS131_PAIN_ASSESSMENT`, `MIPS182_FUNCTIONAL_OUTCOME`, the inclusive performance window `performance_period_start` and `performance_period_end` (with the end strictly after the start), and the `numerator_met` boolean indicating whether the patient met the quality criteria during the period. Two eligibility checks apply both at create and at submit: the patient's `insurance_type` must be `MEDICARE`, and the `Therapist` named by `reporting_therapist_id` must have `medicare_provider_enrolled` true. Violating either is rejected with `ERR_MIPS_ELIGIBILITY` (HTTP 422). A new measure is persisted at `status` `DRAFT`.

A `DRAFT` measure has a self-loop revision path: a `Therapist` may revise `numerator_met` and/or `measure_code` while leaving the performance period immutable. Revising recomputes `composite_score` and increments the measure's `version`. The same `Therapist` may submit the measure (transition `DRAFT → SUBMITTED`); submit is allowed only when the parent plan's `status` is one of `ACTIVE`, `RECERT_DUE`, `DISCHARGED`, and it triggers a recomputation of `composite_score`. Finally a `PlatformAdmin` adjudicates the `SUBMITTED` measure (transition `SUBMITTED → ACCEPTED` when the recorded `composite_score` is at least 30.0, or `SUBMITTED → REJECTED` when it is strictly below 30.0). Adjudication is the only terminal transition for the measure.

The `composite_score` formula combines three weighted inputs and is rounded half-up to two decimal places. The base score is determined by `measure_code`: 60.0 for `MIPS128_FALL_RISK`, 18.0 for `MIPS131_PAIN_ASSESSMENT`, 70.0 for `MIPS182_FUNCTIONAL_OUTCOME`. The numerator bonus adds 25.0 when `numerator_met` is true and 0.0 otherwise. The engagement bonus is computed by counting every `HomeExerciseProgram` under the same `plan_of_care_id` whose `status` is `ACTIVE` and whose `prescribed_on` falls on or after `performance_period_start` and on or before `performance_period_end`, multiplying that count by 3.5, then capping the result at a maximum of 10.0. The improvement bonus is the standardized functional improvement scaled and capped: the system identifies the `INITIAL` evaluation on the plan and the latest evaluation on the plan (ordered by `performed_on` ascending then `created_at` ascending, taking the last row), computes the latest evaluation's `functional_score` minus the initial evaluation's `functional_score` clamped at zero (so a regression contributes zero rather than a negative number), multiplies that improvement by 0.5, then caps the result at a maximum of 15.0. The four parts are summed, the total is capped at 100.0, and the result is rounded half-up to two decimal places and written to `composite_score`. The recomputation runs on every revise and on every submit, so the score visible at adjudication is always the score derived from the measure's current inputs and the plan's then-current HEP and evaluation rows.

### 3.8. Discharge Assessment and Outcome Classification

Before a `Therapist` can discharge a plan, a `DischargeAssessment` must exist for it. The assessment is also created by a `Therapist`. The payload supplies `plan_of_care_id` (whose plan must currently be in `ACTIVE` or `RECERT_DUE` status), the `assessing_therapist_id`, the `final_functional_score` (an integer from 0 to 100 inclusive), the `goals_met_count` and `total_goals_count` (each an integer with `goals_met_count` between 0 and 20 inclusive and `total_goals_count` between 1 and 20 inclusive), and the `assessed_on` date. The two goal counts have a referential relationship: `total_goals_count` must be at least `goals_met_count`. A payload where `goals_met_count` exceeds `total_goals_count` is rejected with `ERR_GOALS_INCONSISTENT` (HTTP 422).

On successful create, the system computes `discharge_outcome` by dividing `goals_met_count` by `total_goals_count` and bucketing the resulting ratio: a ratio at least 0.80 yields the outcome `SUCCESSFUL`; otherwise a ratio at least 0.40 yields `PARTIAL`; otherwise the outcome is `UNSUCCESSFUL`. The 0.80 and 0.40 thresholds are inclusive lower bounds. The assessment is persisted with `discharge_outcome` set; it does not itself drive any state change on the plan, but it unlocks the manual plan-discharge transition described in §3.6.

### 3.9. Veteran Referral Termination

A `VeteranReferral` may leave `ISSUED` along one of three paths. The `CONSUMED` transition is reached as a side effect of plan activation when a VA-backed plan binds the referral (§3.2); the `EXPIRED` transition fires automatically when the server clock advances past the referral's `expires_on` (§2.10). The third path is explicit cancellation by a `VAReferralCoordinator` or `PlatformAdmin`: cancelling an `ISSUED` referral transitions it to `CANCELLED`. The precondition is simply that the referral's `status` is `ISSUED` at the time of the call; once `CONSUMED`, `EXPIRED`, or already `CANCELLED`, no further transitions apply.

### 3.10. Therapist Licensing Demo Policy

The system enforces a demo licensing policy when a therapist is being attached to a patient's care path. The rule applies on three creation paths: scheduling a visit, recording an evaluation, and creating a plan of care. For `VA_TRICARE` patients the policy is permissive — any `Therapist`'s `license_state` is accepted. For patients with any other `insurance_type` value (`MEDICARE`, `COMMERCIAL`, `MEDICAID`, `SELF_PAY`), the therapist's `license_state` must be exactly `CA`. A violation is rejected with `ERR_THERAPIST_LICENSE_INVALID` (HTTP 422). The rule applies wherever a therapist is bound to a patient on any of those three creation paths, regardless of which `Therapist` field carries the binding.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201 and the created resource in the envelope's `data` field. Endpoints that modify an existing resource respond with HTTP 200 and the post-mutation resource. Retrieve and list endpoints respond with HTTP 200 carrying the resource (or array of resources). The full request and response semantics for each endpoint — payload fields, side effects, cascades — are described in §2 and §3 above; this table is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /rehab/patients | Create a Patient. | PlatformAdmin, CaseManager |
| GET | /rehab/patients/{id} | Retrieve a Patient by id. | PlatformAdmin, CaseManager, Therapist, BillingClerk, VAReferralCoordinator |
| GET | /rehab/patients | List Patients with optional filters. | PlatformAdmin, CaseManager |
| POST | /rehab/therapists | Create a Therapist. | PlatformAdmin |
| GET | /rehab/therapists/{id} | Retrieve a Therapist. | PlatformAdmin, CaseManager, Therapist, BillingClerk |
| GET | /rehab/therapists | List Therapists. | PlatformAdmin, CaseManager |
| POST | /rehab/veteran-referrals | Issue a VeteranReferral from a VA facility. | VAReferralCoordinator, PlatformAdmin |
| GET | /rehab/veteran-referrals/{id} | Retrieve a VeteranReferral. | PlatformAdmin, CaseManager, VAReferralCoordinator, Therapist |
| GET | /rehab/veteran-referrals | List VeteranReferrals, filterable by patient_id. | PlatformAdmin, CaseManager, VAReferralCoordinator |
| POST | /rehab/veteran-referrals/{id}/cancel | Cancel an ISSUED VeteranReferral. | VAReferralCoordinator, PlatformAdmin |
| POST | /rehab/plans-of-care | Create a PlanOfCare in DRAFT. | Therapist, CaseManager |
| GET | /rehab/plans-of-care/{id} | Retrieve a PlanOfCare. | PlatformAdmin, CaseManager, Therapist, BillingClerk, VAReferralCoordinator |
| GET | /rehab/plans-of-care | List PlansOfCare with optional filters. | PlatformAdmin, CaseManager, Therapist, BillingClerk, VAReferralCoordinator |
| POST | /rehab/plans-of-care/{id}/activate | Activate a DRAFT PlanOfCare; pins cap; cascades to VeteranReferral and sibling drafts. | Therapist |
| POST | /rehab/plans-of-care/{id}/recertify | Recertify a RECERT_DUE PlanOfCare back to ACTIVE. | Therapist |
| POST | /rehab/plans-of-care/{id}/discharge | Discharge an ACTIVE PlanOfCare; depth-3 cascade on visits, grants, and HEPs. | Therapist |
| POST | /rehab/evaluations | Create an Evaluation under a PlanOfCare. | Therapist |
| GET | /rehab/evaluations/{id} | Retrieve an Evaluation. | PlatformAdmin, Therapist, BillingClerk |
| GET | /rehab/evaluations | List Evaluations with optional filters. | PlatformAdmin, Therapist, BillingClerk |
| POST | /rehab/authorization-grants | Create an AuthorizationGrant under a PlanOfCare. | CaseManager, PlatformAdmin |
| GET | /rehab/authorization-grants/{id} | Retrieve an AuthorizationGrant. | PlatformAdmin, CaseManager, Therapist, BillingClerk |
| GET | /rehab/authorization-grants | List AuthorizationGrants with optional filters. | PlatformAdmin, CaseManager, Therapist, BillingClerk |
| POST | /rehab/visits | Schedule a Visit. | Therapist, CaseManager |
| GET | /rehab/visits/{id} | Retrieve a Visit. | PlatformAdmin, Therapist, BillingClerk, CaseManager |
| GET | /rehab/visits | List Visits with optional filters. | PlatformAdmin, Therapist, BillingClerk, CaseManager |
| POST | /rehab/visits/{id}/complete | Mark a SCHEDULED Visit COMPLETED with delivered minutes. | Therapist |
| POST | /rehab/visits/{id}/finalize | Bill a COMPLETED Visit; cascades cumulative_billed_cents and capped_status. | BillingClerk |
| POST | /rehab/visits/{id}/cancel | Cancel a SCHEDULED Visit. | Therapist, PlatformAdmin |
| POST | /rehab/visits/{id}/no-show | Mark a missed SCHEDULED Visit NO_SHOW. | Therapist |
| POST | /rehab/home-exercise-programs | Prescribe a HomeExerciseProgram; supersedes any prior ACTIVE HEP. | Therapist |
| GET | /rehab/home-exercise-programs/{id} | Retrieve a HomeExerciseProgram. | PlatformAdmin, Therapist, CaseManager |
| GET | /rehab/home-exercise-programs | List HomeExercisePrograms with optional filters. | PlatformAdmin, Therapist, CaseManager |
| POST | /rehab/mips-measures | Create a DRAFT MIPSQualityMeasure. | Therapist |
| GET | /rehab/mips-measures/{id} | Retrieve a MIPSQualityMeasure. | PlatformAdmin, Therapist |
| GET | /rehab/mips-measures | List MIPSQualityMeasures with optional filters. | PlatformAdmin, Therapist |
| POST | /rehab/mips-measures/{id}/revise | Revise a DRAFT measure; recomputes composite_score. | Therapist |
| POST | /rehab/mips-measures/{id}/submit | Submit a DRAFT MIPSQualityMeasure. | Therapist |
| POST | /rehab/mips-measures/{id}/adjudicate | Adjudicate a SUBMITTED measure to ACCEPTED or REJECTED. | PlatformAdmin |
| POST | /rehab/discharge-assessments | Record a DischargeAssessment under a PlanOfCare. | Therapist |
| GET | /rehab/discharge-assessments/{id} | Retrieve a DischargeAssessment. | PlatformAdmin, Therapist, CaseManager |
| GET | /rehab/discharge-assessments | List DischargeAssessments with optional filters. | PlatformAdmin, Therapist, CaseManager |
| POST | /_clock/set_current_utc | Test-driving: advance the server clock and re-evaluate time-gated transitions. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_PLAN_VERSION | 412 |
| ERR_VA_REFERRAL_REQUIRED | 422 |
| ERR_VETERAN_FLAG_REQUIRED | 422 |
| ERR_MIPS_ELIGIBILITY | 422 |
| ERR_CAPPED_POC_EXCEEDED | 409 |
| ERR_THERAPIST_LICENSE_INVALID | 422 |
| ERR_VA_VISIT_CAP_EXCEEDED | 409 |
| ERR_VISIT_OUT_OF_WINDOW | 422 |
| ERR_THERAPIST_DOUBLE_BOOKED | 409 |
| ERR_GRANT_WINDOW_OVERLAP | 409 |
| ERR_AUTHORIZATION_EXHAUSTED | 409 |
| ERR_GOALS_INCONSISTENT | 422 |
| ERR_RECERT_WINDOW_EXCEEDED | 422 |
