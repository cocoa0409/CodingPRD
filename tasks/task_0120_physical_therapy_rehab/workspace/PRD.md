# Physical Therapy Rehab API — Product Requirements Document

## 1. Introduction

Outpatient physical therapy clinics operate inside an unusually dense web of clinical, billing, and regulatory constraints: a licensed therapist must perform the initial evaluation, a referring physician must certify the plan of care, a payer (Medicare Part B, the VA Community Care Network, a commercial carrier, or the patient themselves) must authorize a finite pool of 15-minute treatment units, and every delivered visit must be billed under the CMS 8-Minute Rule with the appropriate KX modifier once the patient crosses Medicare's annual therapy threshold. Manual reconciliation across spreadsheets, scheduler tools, and biller worklists is the dominant source of denied claims and lost revenue at small and mid-size clinics.

The Physical Therapy Rehab API consolidates the full episode-of-care lifecycle behind a single REST surface. It binds patients to therapists and authorizations, computes unit balances and capped-dollar projections at every state change, enforces the segregation of duties required for discharge sign-off, and runs the MIPS quality scoring used for downstream reimbursement adjustments. The system is designed so that a clinic's front office, treating clinicians, and biller can each work within their own role boundaries while the platform preserves the cross-cutting financial and compliance invariants on their behalf.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than `GET /_health` must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the principal's operational capacity. If either header is missing or empty the request is rejected with `ERR_AUTH_MISSING`. If the role is not authorized for the requested operation the request is rejected with `ERR_FORBIDDEN`.

Four roles are recognized, spelled exactly: `ClinicAdmin`, `Therapist`, `Biller`, and `Patient`.

- When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may log it but does not compare it to any entity's `id`. `ClinicAdmin` covers front-office staff who register patients, register therapists, register VA Community Care referrals, advance the test clock, and create externally-sourced authorizations.
- When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the acting `Therapist` row; ownership and capability checks on any clinical operation that references a `Therapist` (evaluations, plan certifications, visit sign-off, HEP issuance, discharge creation) compare the resource's `clinician_id`, `prescribing_clinician_id`, or `discharging_clinician_id` foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Biller`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. `Biller` exists solely to submit signed visits to the payer; it has no clinical authority.
- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient` row; the patient can read only their own `Patient` record and acknowledge HEPs whose anchoring episode belongs to that patient.

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

List endpoints accept two query parameters: `limit` controls the maximum number of items returned per page, defaulting to 10 with a minimum of 1 and a maximum of 100; `offset` controls how many items to skip from the start, defaulting to 0 with a minimum of 0. Any `limit` outside `[1, 100]` or `offset` below 0 is rejected with `ERR_PAGINATION_RANGE`. Unless otherwise specified, list endpoints return rows sorted by `created_at` in ascending order. Each list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every server-minted resource carries an `id` which is a UUID string with no type prefix and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format) that the server refreshes on every mutation, and a `version` integer that begins at 1 on creation and increments by 1 every time the resource is mutated. The two exceptions are append-only entities — `MipsMeasure` rows and `VeteranReferral` rows — which carry only `id` and `created_at`; their `updated_at` and `version` fields are absent because the platform never mutates them in place. For `MipsMeasure` the creation timestamp is also surfaced as `scored_at`, an immutable system-set field.

Mutating endpoints accept an optional `version` field in the request body for optimistic concurrency control. When supplied, the value must equal the current `version` of the target resource; if it does not, the request is rejected with `ERR_VERSION_CONFLICT`. When omitted, the server performs the operation without comparing versions. Every successful mutation increments `version` by 1 and refreshes `updated_at` on the primary target resource, and the same `updated_at` / `version` rule applies to any secondary resource the operation mutates via cascade (for example, when finalizing an evaluation also advances `Episode.status`, the episode's `version` and `updated_at` are likewise refreshed).

### 2.5. Nested Path Resolution

When an endpoint path contains multiple resource identifiers — `patient_id`, `episode_id`, `evaluation_id`, `poc_id`, `authorization_id`, `visit_id`, `hep_id`, `discharge_id`, `therapist_id`, `referral_id` — the system resolves them strictly left-to-right and returns `ERR_NOT_FOUND` against the first id that does not resolve. Identifiers in the request body — `patient_id`, `evaluation_id`, `plan_of_care_id`, `authorization_id`, `clinician_id`, `discharging_clinician_id`, `prescribing_clinician_id`, `visit_id` — are resolved after path resolution; an unresolved body id yields `ERR_REFERENCE_NOT_FOUND`.

### 2.6. Validation Ordering

When multiple validation rules could fire on a single request, the system always evaluates them in a fixed precedence order so that the rejection a client receives is deterministic. Authentication failures (`ERR_AUTH_MISSING`) precede authorization failures (`ERR_FORBIDDEN`), both of which precede path-resolution failures (`ERR_NOT_FOUND`), which precede body-reference-resolution failures (`ERR_REFERENCE_NOT_FOUND`). Once existence is established, state checks fire next: `ERR_INVALID_STATE` for any target resource not in the required status, followed by `ERR_EPISODE_NOT_ACTIVE` for operations that require the parent episode to be active, followed by `ERR_REEVAL_DUE` for visit-scheduling specifically. Clinical-capability checks come next (`ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE`, then `ERR_SEGREGATION_OF_DUTIES`), then VA-referential checks (`ERR_VETERAN_REFERRAL_REQUIRED`, then `ERR_VA_REFERENCE_MISMATCH`), then temporal checks (`ERR_CERT_PERIOD_TOO_LONG`, then `ERR_OUT_OF_AUTH_WINDOW`, then `ERR_CLINICIAN_DOUBLE_BOOKED`, then `ERR_PATIENT_DOUBLE_BOOKED`), then quota-and-cap checks (`ERR_POC_VISIT_LIMIT`, then `ERR_INSUFFICIENT_UNITS`, then `ERR_CAP_EXCEEDED`), and finally domain-specific constraint checks (`ERR_INVALID_MIPS_EXCEPTION`) and pagination bounds (`ERR_PAGINATION_RANGE`). Generic shape failures (missing required field, wrong type, enum value not allowed) surface as `ERR_VALIDATION` and are evaluated alongside the existence layer.

### 2.7. The Unit Quota Pool

Every episode maintains a triad of integer roll-up counters that together describe the state of its 15-minute treatment-unit pool. `Episode.total_authorized_units` is the sum of `unit_quota` across every `Authorization` on the episode whose `status` is `APPROVED`. `Episode.total_reserved_units` is the sum of `units_planned` across every `Visit` on the episode whose `status` is `SCHEDULED` or `IN_SESSION`. `Episode.total_committed_units` is the sum of `units_billed` across every `Visit` whose `status` is `SIGNED` or `BILLED`. These three counters are recomputed by the server after every visit lifecycle transition and on every authorization create or revoke; the rule applied at every recomputation is that the new visit row is persisted first and then the roll-up is refreshed, so the row that triggered the recomputation contributes to the rollup it triggered. The pool invariant the system protects at all times is that reserved units plus committed units never exceed authorized units. Reading the episode via the fetch endpoint always returns freshly recomputed counters.

### 2.8. The Medicare Therapy Cap

The platform tracks each patient's calendar-year accumulation of paid PT charges via `Patient.ytd_capped_amount_cents`, an integer-cents counter that starts at 0. Two thresholds are configured: the KX threshold is 241,000 cents ($2,410.00), the 2026 Medicare PT/SLP soft cap; the hard cap is 300,000 cents ($3,000.00), the targeted-medical-review threshold above which signs are rejected. The KX modifier becomes required for an episode when `Patient.ytd_capped_amount_cents` becomes strictly greater than 241,000 cents — not equal-or-greater, but strictly greater — at which point `Episode.kx_modifier_required` is set to true and remains true thereafter. Whether an episode counts against the cap at all is governed by `Episode.cap_policy`: when the patient's `insurance_type` is `MEDICARE_PART_B` the policy is set to `CAPPED` on initial evaluation finalization, otherwise `UNCAPPED`. The cap-status read endpoint exposes the patient's `ytd_capped_amount_cents` together with three derived values: `remaining_to_threshold_cents` is the maximum of zero and (241,000 cents minus the year-to-date amount); `remaining_to_hard_cap_cents` is the maximum of zero and (300,000 cents minus the year-to-date amount); and `kx_required` is true when the year-to-date amount is strictly greater than 241,000 cents.

### 2.9. Precision and Rounding

All monetary amounts are stored and exchanged as integer cents — no fractional cents exist anywhere in the system. Unit counts are integer 15-minute units. The episode-level MIPS quality score is the only multi-decimal value the platform produces; it is rounded to two decimal places using the round-half-up rule, with rounding applied exactly once at the very end of aggregation, never to intermediate per-measure rates.

### 2.10. Cascading State Effects and Concurrency

Several operations affect more than one entity in a single request. Finalizing the first `INITIAL` evaluation on a `DRAFT` episode also moves the episode to `EVALUATED` and stamps `Episode.cap_policy`. Certifying a plan of care moves it from `DRAFT` through `CERTIFIED` to `ACTIVE` in the same request, runs the capped projection calculation, may flip `Episode.kx_modifier_required` to true if the projection would push the patient past the KX threshold, and on the first plan to be certified cascades the episode from `EVALUATED` to `ACTIVE`. Signing a visit decreases `Episode.total_reserved_units` by `units_planned` and increases `Episode.total_committed_units` by the just-computed `units_billed`. Signing a discharge moves the episode from `DISCHARGE_PENDING` to `DISCHARGED`, expires every `APPROVED` `Authorization` on the episode to `EXPIRED`, and supersedes every `HomeExerciseProgram` on the episode that is in `ISSUED` or `ACKNOWLEDGED` status to `SUPERSEDED`. Issuing a new HEP supersedes any prior `ISSUED` or `ACKNOWLEDGED` HEP on the same episode. Every entity mutated by any of these cascades has its `updated_at` refreshed and its `version` incremented as described in §2.4.

Concurrency on these multi-entity operations is resolved by row-level first-writer-wins. Two clinicians who attempt to start the same `SCHEDULED` visit at the same instant will produce exactly one `IN_SESSION` row; the loser is rejected with `ERR_INVALID_STATE`. Two clinicians who attempt to finalize the same `DRAFT` evaluation concurrently produce exactly one `FINALIZED` row; the loser is rejected with `ERR_INVALID_STATE`. Two requests that attempt to issue the same `DRAFT` HEP concurrently produce exactly one `ISSUED` row; the loser is rejected with `ERR_INVALID_STATE`. When a discharge sign races a fresh visit start on the same episode, exactly one wins on `Episode.status`; if the discharge wins, the start sees that the episode is no longer `ACTIVE` and is rejected with `ERR_EPISODE_NOT_ACTIVE`. When two visit signs race and the second would push the patient's `ytd_capped_amount_cents` past the hard cap, the patient row is serialized: both signs may complete only if both fit under the hard cap, and the second writer that finds its pre-image stale is rejected with `ERR_CAP_EXCEEDED`; the cap-tripping visit (if any) must carry `kx_applied` equal to true. When two authorization creates race against the same `VeteranReferral`, the system serializes consumption on `VeteranReferral.authorized_units`; if their combined `unit_quota` would exceed the referral's authorized total, the loser is rejected with `ERR_VA_REFERRAL_EXHAUSTED`.

## 3. Business Logic & Workflows

### 3.1. Registering the Clinical Workforce and Patient Roster

Before any clinical work can occur, a front-office operator registers therapists and patients. Registering a therapist supplies `full_name`, a 10-digit `npi`, and the therapist's `credential`, which is one of `PT`, `PTA`, or `DPT`. The platform derives `can_evaluate` automatically: it is true when the credential is `PT` or `DPT`, and false when the credential is `PTA`. A physical therapist assistant may deliver visits, but they cannot finalize or amend evaluations and they cannot sign a discharge — that capability is reserved for `PT` and `DPT` license-holders. Attempting to register a second therapist with an `npi` that already exists yields `ERR_DUPLICATE_NPI`. New therapists begin life in `status` `ACTIVE`; the inactive lifecycle state `INACTIVE` is reserved for therapists who have left the practice.

Registering a patient supplies `full_name`, `date_of_birth`, and `insurance_type`, the latter being one of `MEDICARE_PART_B`, `VA`, `COMMERCIAL`, or `SELF_PAY`. Two conditional fields piggy-back on the payer: when `insurance_type` is `MEDICARE_PART_B`, the patient's `medicare_beneficiary_id` is required and is the MBI used on every Medicare claim; when `insurance_type` is `VA`, the patient's `va_referral_id` is required and is the VA Community Care Network referral identifier that must be mirrored onto any VA-sourced authorization. The patient's lifecycle begins at `ACTIVE`; the terminal `ARCHIVED` value is reserved for patients who have completed their care or been removed from the active roster. The cap counter `ytd_capped_amount_cents` is initialized to 0 and only ever grows as Medicare-Part-B-covered visits sign.

When a patient is covered by the VA Community Care Network, the front office also registers a `VeteranReferral` record. The referral supplies the owning `patient_id` (whose `insurance_type` must be `VA`), a 3-character `referring_va_facility_code`, the integer `authorized_units` granted by the VA, and an inclusive validity window from `valid_from` through `valid_through`. The referral lifecycle begins in `ACTIVE`; it transitions to `CONSUMED` when the full unit pool has been allocated to authorizations and to `EXPIRED` when the test clock advances past `valid_through`. VA referrals are append-only beyond those two terminal states — the platform records them and consumes them, but never mutates their `authorized_units` in place, which is why `VeteranReferral` carries only `id` and `created_at` and exposes no `updated_at` or `version`.

### 3.2. Opening an Episode and Recording the Evaluation

A treating therapist opens a new episode of care by submitting a `patient_id`, the 10-digit `referring_provider_npi` of the physician who referred the patient, and a `body_region` — one of `LUMBAR`, `CERVICAL`, `KNEE`, `SHOULDER`, `HIP`, `ANKLE`, or `OTHER` — that identifies the primary anatomical region being treated. The episode is created in status `DRAFT` with its three unit counters and the boolean `kx_modifier_required` initialized to 0 and false respectively, and `cap_policy` and `discharge_outcome` left unset. While the episode remains in `DRAFT`, the same therapist can abandon it; deleting a `DRAFT` episode moves it directly to the terminal `CANCELLED` status. Once any evaluation has been finalized the episode is past `DRAFT` and can no longer be cancelled in that way.

Recording an evaluation on the episode means creating an `Evaluation` row that captures `evaluation_type` (either `INITIAL` or `REEVAL`), the `clinician_id` of the performing therapist, the APTA-style `complexity` of `LOW`, `MODERATE`, or `HIGH` (which drives both the eval CPT code and the eval surcharge applied to the visit that contains it), and the patient's `functional_baseline_score` on a 0-to-100 scale used both for MIPS measure Q127 and for the discharge functional delta. The evaluation is born in `DRAFT` with `finalized_at` unset.

Finalizing a draft evaluation, which advances the evaluation from `DRAFT` to `FINALIZED`, requires that the acting therapist's `can_evaluate` flag is true and that the supplied `functional_baseline_score` is between 0 and 100 inclusive; a therapist whose credential is `PTA` is rejected with `ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE`, and a score outside `[0, 100]` is rejected with `ERR_VALIDATION`. On a successful finalize, `finalized_at` is set to the current clock instant. The finalize operation also cascades into the episode's own state machine: when the finalized evaluation is the first `INITIAL` evaluation and the episode is in `DRAFT`, the episode advances from `DRAFT` to `EVALUATED` and `Episode.cap_policy` is stamped — set to `CAPPED` when `Patient.insurance_type` is `MEDICARE_PART_B`, otherwise `UNCAPPED`. When the finalized evaluation is a `REEVAL` and the episode is in `REEVAL_DUE`, the episode advances back from `REEVAL_DUE` to `ACTIVE`. A `FINALIZED` evaluation can be amended by the same `clinician_id` that finalized it, provided the episode is not in `DISCHARGED` or `CANCELLED`; amend transitions the evaluation to `AMENDED` and may revise `functional_baseline_score` and `complexity`. If a non-terminal `PlanOfCare` (in `DRAFT`, `CERTIFIED`, or `ACTIVE`) references the amended evaluation, the forward capped-cost projection re-runs on that plan, the plan's `capped_projection_cents` is rewritten, and `Episode.kx_modifier_required` is re-derived.

### 3.3. Certifying the Plan of Care

A `PlanOfCare` is anchored to a single evaluation and turns the clinician's intent into a budgeted authorization request. Drafting a plan supplies an `evaluation_id` that must be in `FINALIZED` or `AMENDED` status at certification time, the `certifying_physician_npi` of the referring or attending physician who is taking responsibility for the plan, the integer `planned_visit_count` expected over the certification window, the integer `planned_units_per_visit` that drives the size of the unit authorization, and the certification window itself — `cert_period_start` and `cert_period_end`, both ISO 8601 dates. The window must not exceed 90 days from start to end and `cert_period_end` must be strictly later than `cert_period_start`; violation is rejected with `ERR_CERT_PERIOD_TOO_LONG`. The plan begins in `DRAFT`.

Certifying a plan moves it from `DRAFT` through `CERTIFIED` to `ACTIVE` in the same request. Certification requires the anchoring evaluation to be in `FINALIZED` or `AMENDED`, and the window check is re-applied at certify time so a plan whose window has been edited past 90 days cannot sneak through. The plan moves from `CERTIFIED` to `ACTIVE` only when at least one `APPROVED` `Authorization` exists on the episode whose `unit_quota` is at least the product of `planned_visit_count` and `planned_units_per_visit` and whose `[valid_from, valid_through]` covers `cert_period_start`; without sufficient unit coverage the plan stays in `CERTIFIED` and certification is rejected as an invalid state for the unit-coverage rule.

The forward capped-cost projection runs during certify. It assumes PT/DPT-rate delivery (4200 cents per unit) of `planned_visit_count` × `planned_units_per_visit` units, plus a single eval surcharge keyed to the anchoring evaluation's `complexity` — 5,000 cents when `LOW`, 7,500 cents when `MODERATE`, 10,500 cents when `HIGH`. Concretely, the projection in integer cents equals (`planned_visit_count` multiplied by `planned_units_per_visit`, then multiplied by 4,200) added to the surcharge dollars corresponding to the evaluation's complexity, with the result stored as `capped_projection_cents` on the plan. The projection deliberately does not consult delivered visits — it is the forward-looking estimate. (A separately computed actual variant exists for compliance reporting at discharge: it sums actual `Visit.charge_cents` across `SIGNED` and `BILLED` visits in ascending order of when the visit was signed, with ties broken by `Visit.id` ascending; because the actual variant honors the 8-minute rule and the actual clinician's credential — which may be `PTA` at 3,500 cents per unit — its chronological actual diverges from the forward projection even when the visit count was met exactly.)

If `Episode.cap_policy` is `CAPPED` and the just-computed `capped_projection_cents` added to `Patient.ytd_capped_amount_cents` would push the patient past 241,000 cents, `Episode.kx_modifier_required` is set to true at certify time. Certifying the first plan on an episode also cascades the episode from `EVALUATED` to `ACTIVE`. An `ACTIVE` plan can later be revoked by a clinician whose `can_evaluate` is true; revocation moves the plan to terminal `REVOKED` and side-effects every `SCHEDULED` visit on that plan to `CANCELLED`. Plans whose `cert_period_end` is passed by the system clock are swept from `ACTIVE` to `EXPIRED`, with their `SCHEDULED` visits cancelled.

### 3.4. Authorizations and the VA Referral Tie-Down

Authorizations supply the unit pool that the plan of care draws against. Creating an authorization on an episode requires a `plan_of_care_id` to bind it to, a `source` of `COMMERCIAL_PAYER`, `MEDICARE_AUTO`, or `VA_REFERRAL`, an `external_reference` (the payer authorization number or the VA referral id), an integer `unit_quota` of 15-minute units, and an inclusive `[valid_from, valid_through]` window. New authorizations start in status `APPROVED`; over time they transition to `EXPIRED` (swept once the clock crosses `valid_through`, or expired wholesale when the episode discharges) or `REVOKED`.

For VA-covered patients the link to the VA Community Care Network is enforced at two points. First, the very first visit creation on an episode for a patient whose `insurance_type` is `VA` requires that an `Authorization` with `source` equal to `VA_REFERRAL` referencing an `ACTIVE` `VeteranReferral` already exists on the episode; otherwise the create is rejected with `ERR_VETERAN_REFERRAL_REQUIRED`. Second, when an authorization is created with `source` equal to `VA_REFERRAL`, its `external_reference` must equal both the `id` of an active `VeteranReferral` and the `va_referral_id` recorded on the patient; mismatch yields `ERR_VA_REFERENCE_MISMATCH`. The platform mirrors the referral id onto `Patient.va_referral_id` when a VA-sourced authorization is created, which is why those two values are required to agree.

Multiple authorizations may collectively draw against a single VA referral so long as the sum of their `unit_quota` values stays at or below the referral's `authorized_units`. If two concurrent authorization creates would jointly push that sum above the cap, exactly one succeeds and the other is rejected with `ERR_VA_REFERRAL_EXHAUSTED`.

### 3.5. Scheduling, Delivering, and Signing Visits

Scheduling a visit on an active episode supplies the binding `plan_of_care_id` (which must be in `ACTIVE` status), the binding `authorization_id` (which must be `APPROVED` and whose `valid_through` covers `scheduled_start`), the delivering therapist's `clinician_id`, the visit's `scheduled_start` and `scheduled_end` timestamps (`scheduled_end` must be strictly later than `scheduled_start`), and the integer `units_planned` the clinician expects to bill. The visit is created in `SCHEDULED`, with `units_billed`, `charge_cents`, and the boolean `kx_applied` all initialized to 0 / false, and `timed_minutes` likewise initialized to 0 until the clinician records it at sign time.

A new visit on a VA-covered episode requires the veteran-referral linkage described above. The `scheduled_start` must fall within both the bound authorization's `[valid_from, valid_through]` window and the bound plan's `[cert_period_start, cert_period_end]` window — both windows are inclusive on both endpoints — and a window violation is rejected with `ERR_OUT_OF_AUTH_WINDOW`. The total number of visits already in `SCHEDULED`, `IN_SESSION`, `SIGNED`, or `BILLED` on the plan plus this new one must not exceed `PlanOfCare.planned_visit_count`; an overflow is rejected with `ERR_POC_VISIT_LIMIT`. The episode-level quota invariant must hold at scheduling time: `total_reserved_units` plus `total_committed_units` plus the new visit's `units_planned` must remain less than or equal to `total_authorized_units`, and a shortfall is rejected with `ERR_INSUFFICIENT_UNITS`. Two clinician double-booking rules apply with different adjacency semantics: the new visit must not overlap any other visit in `SCHEDULED`, `IN_SESSION`, or `SIGNED` for the same `clinician_id` under half-open interval semantics — back-to-back visits sharing exactly the same instant on the boundary do not overlap — and violation yields `ERR_CLINICIAN_DOUBLE_BOOKED`; the new visit must not overlap any other visit in those same statuses for the same patient (resolved via the owning episode) under closed-interval semantics — back-to-back visits sharing the same instant on the boundary do overlap because the patient cannot be in two places at once — and violation yields `ERR_PATIENT_DOUBLE_BOOKED`. Scheduling a visit while the episode is in `REEVAL_DUE` is rejected with `ERR_REEVAL_DUE`; visit operations targeted at episodes not in `ACTIVE` are rejected with `ERR_EPISODE_NOT_ACTIVE`.

When the therapist arrives for the visit they advance it from `SCHEDULED` to `IN_SESSION`. Starting requires the episode to be in `ACTIVE` (not `REEVAL_DUE`), the bound plan to be in `ACTIVE`, the bound authorization to be in `APPROVED` with `valid_through` at least the visit's `scheduled_start` date, and the unit invariant (`total_reserved_units` plus `total_committed_units` not exceeding `total_authorized_units`) to still hold. Starting does not change quota counters because the units were reserved when the visit was created.

Signing the visit completes its clinical lifecycle. The signing therapist supplies `timed_minutes`, the direct one-on-one timed minutes that drive the 8-minute rule, which must be at least 8 to count for any units. The platform computes `units_billed` under the CMS 8-Minute Rule: when `timed_minutes` is strictly less than 8 the billed units are 0; otherwise the billed units are equal to the integer division of (`timed_minutes` minus 8) by 15, plus 1. In banded form this means 0 units for fewer than 8 minutes, 1 unit for 8 through 22 minutes inclusive, 2 units for 23 through 37 minutes inclusive, 3 units for 38 through 52 minutes inclusive, 4 units for 53 through 67 minutes inclusive, 5 units for 68 through 82 minutes inclusive, 6 units for 83 through 97 minutes inclusive, and one additional unit per subsequent 15-minute band. The visit charge in cents is then `units_billed` multiplied by the per-unit rate keyed to the signing therapist's `credential` — 4,200 cents per unit when the credential is `PT` or `DPT`, 3,500 cents per unit when the credential is `PTA`. If a `FINALIZED` (or `AMENDED`) evaluation has its `finalized_at` timestamp falling inside this visit's `[scheduled_start, scheduled_end]` window, the system adds the evaluation surcharge for that evaluation's `complexity` — 5,000 cents for `LOW`, 7,500 cents for `MODERATE`, 10,500 cents for `HIGH`. Because every operand is an integer-cents value, no rounding is needed; the resulting `charge_cents` is the integer total.

On a successful sign the platform decreases `total_reserved_units` by `units_planned` and increases `total_committed_units` by `units_billed`, in that order, so the just-signed row contributes to its own roll-up. When `Episode.cap_policy` is `CAPPED`, the platform adds the just-computed `charge_cents` to `Patient.ytd_capped_amount_cents`; if doing so newly pushes the patient past 241,000 cents, `Episode.kx_modifier_required` is flipped to true and the visit's `kx_applied` is set to true. If the addition would push the patient past 300,000 cents (the hard cap), the sign is rejected with `ERR_CAP_EXCEEDED` — crossing the soft threshold is allowed and merely flips `kx_applied`, but crossing the hard cap is forbidden. Two simultaneous signs that race against the same patient row are serialized: if both fit under the hard cap, both complete; the cap-tripping one must carry `kx_applied` equal to true; the loser whose pre-image is stale is rejected with `ERR_CAP_EXCEEDED`.

A signed visit awaits the biller. The biller's submit-claim operation advances the visit from `SIGNED` to `BILLED`. Submission requires the visit to currently be in `SIGNED`; if the patient's `ytd_capped_amount_cents` was strictly greater than 241,000 cents at the moment of signing and the episode's `cap_policy` is `CAPPED`, then the visit's `kx_applied` must be true at submission time, otherwise the submission is rejected as an invalid state. Submission does not change any unit counter. A visit that has not yet reached `SIGNED` can also be cancelled by a therapist; cancelling a `SCHEDULED` or `IN_SESSION` visit releases its reservation by decreasing `total_reserved_units` by the visit's `units_planned`. A `BILLED` visit is terminal.

### 3.6. Reevaluations and the 30-Day Sweep

To remain billable, every episode of physical therapy must be reevaluated periodically. The platform measures the elapsed time between the latest `FINALIZED` or `AMENDED` evaluation's `finalized_at` and the simulated clock. When the test clock is advanced and the gap reaches 30 days or more on an `ACTIVE` episode, the episode is swept to `REEVAL_DUE`. While the episode sits in `REEVAL_DUE`, scheduling new visits is blocked and is rejected with `ERR_REEVAL_DUE`. The therapist clears the block by creating a new `Evaluation` whose `evaluation_type` is `REEVAL` and finalizing it; the finalize cascade then moves the episode from `REEVAL_DUE` back to `ACTIVE`.

### 3.7. The Home Exercise Program

A home exercise program is anchored to an episode and the active plan of care. Drafting a HEP supplies the binding `plan_of_care_id` (which must be in `ACTIVE`), the `prescribing_clinician_id` of the therapist who authored it, and a non-empty `exercise_items` array, where each item describes one exercise with its name, set count, repetition count, and weekly frequency. The HEP begins in `DRAFT` with `patient_acknowledged_at` unset. Issuing the HEP requires `exercise_items` to remain non-empty and the bound plan to be in `ACTIVE`; on issue, the HEP transitions to `ISSUED`, and any prior HEP on the same episode that was in `ISSUED` or `ACKNOWLEDGED` is transitioned to terminal `SUPERSEDED`. The patient may then acknowledge the issued HEP; acknowledgment transitions it to `ACKNOWLEDGED` and stamps `patient_acknowledged_at` with the current clock instant. When the episode discharges, every HEP on the episode that is in `ISSUED` or `ACKNOWLEDGED` is also moved to `SUPERSEDED`.

### 3.8. MIPS Quality Reporting

The platform supports three CMS Merit-based Incentive Payment System measures relevant to outpatient physical therapy: `Q126_PAIN_ASSESSMENT`, `Q127_FUNCTIONAL_STATUS`, and `Q128_FALL_RISK_SCREEN`. A therapist attests a measure against a specific visit by creating a `MipsMeasure` row that supplies the `measure_code`, the `visit_id` at which the measure applies, a boolean `numerator_met` indicating whether the measure action was performed, and an `exception_reason` of `NONE`, `MEDICAL`, `PATIENT`, or `SYSTEM` documenting any approved denominator exception. The `scored_at` timestamp is set by the server when the row is created. Two business rules govern attestation: a row with `exception_reason` other than `NONE` is only valid when `numerator_met` is false (if a met measure carries an exception, the row is rejected with `ERR_INVALID_MIPS_EXCEPTION`); and `MipsMeasure` rows are append-only — once created they are never mutated, which is why the entity carries no `updated_at` or `version`.

At episode discharge, the platform aggregates these rows into an episode-level quality score. For each of the three measure codes, the system gathers every row on this episode whose `exception_reason` is `NONE` — those are the applicable rows. The subset whose `numerator_met` is true are the met rows. The per-measure rate is the count of met rows divided by the count of applicable rows; when there are no applicable rows the measure is excluded from the average. The episode-level rate is the sum of per-measure rates across non-excluded measures, divided by the count of non-excluded measures, multiplied by 100. If all three measures are excluded the score is 0.00. Rounding is applied exactly once at the very end of this aggregation, to two decimal places using the round-half-up rule; per-measure rates are never rounded before averaging. The resulting value is stamped onto `DischargeAssessment.mips_quality_score`.

### 3.9. Discharge and Episode Closure

The discharge of an episode is a two-step ceremony designed to enforce segregation of duties between the evaluating therapist and the discharging clinician. Step one is creation: a therapist opens a `DischargeAssessment` on the episode, supplying `discharging_clinician_id`, an outcome category `discharge_outcome` of `GOALS_MET`, `PARTIAL`, `PLATEAU`, `ADVERSE_EVENT`, or `PATIENT_WITHDREW`, and the patient's final functional outcome on the same 0–100 scale as the evaluation baseline, captured in `final_functional_score`. Creation requires that no visit on the episode remains in `SCHEDULED` or `IN_SESSION`; if any unfinished visit exists, the create is rejected as an invalid state. On a successful create, the assessment is created in `DRAFT` and the episode is moved from `ACTIVE` (or from `REEVAL_DUE`) to `DISCHARGE_PENDING`.

Step two is signature. Signing a draft discharge requires that the signing therapist's `can_evaluate` is true and that the `discharging_clinician_id` recorded on the assessment is not equal to the `clinician_id` of the most recent evaluation on the episode — the same person who performed the evaluation may not sign the discharge. A self-discharge attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. On a successful sign, the discharge transitions to `SIGNED`; the platform computes `functional_delta` as the difference between `final_functional_score` and the `functional_baseline_score` of the most recent `FINALIZED` or `AMENDED` evaluation on the episode (final minus baseline); the MIPS quality score described above is computed and written to `mips_quality_score`; the episode advances from `DISCHARGE_PENDING` to terminal `DISCHARGED`; `Episode.discharge_outcome` is copied from `DischargeAssessment.discharge_outcome`; every `APPROVED` authorization on the episode is moved to `EXPIRED`; and every `ISSUED` or `ACKNOWLEDGED` HEP on the episode is moved to `SUPERSEDED`. Each `DischargeAssessment.episode_id` is unique — there can be at most one discharge per episode.

### 3.10. The Simulated Clock and Scheduled Sweeps

Because reevaluation thresholds, authorization windows, plan certification windows, and VA referral windows are all calendar-driven, the platform exposes a test-only capability for an admin operator to advance the logical clock to a supplied `to` instant. Advancing the clock triggers four time-gated sweeps in a single request: every `ACTIVE` episode whose latest evaluation's `finalized_at` is now at least 30 days in the past is moved to `REEVAL_DUE`; every `ACTIVE` plan of care whose `cert_period_end` has been crossed is moved to terminal `EXPIRED`, and that plan's `SCHEDULED` visits are cancelled; every `APPROVED` authorization whose `valid_through` has been crossed is moved to terminal `EXPIRED`; every `ACTIVE` `VeteranReferral` whose `valid_through` has been crossed is moved to terminal `EXPIRED`. A separate admin-only read capability returns the simulated clock's current `now` instant. Whenever the cap-status read endpoint runs it also re-derives the patient's `kx_required` flag from `ytd_capped_amount_cents` against the 241,000-cents threshold.

## 4. Endpoint Definitions

New resource creation returns HTTP 201; the cancellation of a `DRAFT` episode returns 204; every other successful mutation and every successful read returns 200. The table below intentionally omits request bodies, response bodies, and side effects — those are scattered through §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /therapists | Register a therapist | ClinicAdmin |
| GET | /therapists/{therapist_id} | Fetch a therapist | ClinicAdmin, Therapist, Biller |
| GET | /therapists | List therapists | ClinicAdmin, Therapist, Biller |
| POST | /patients | Register a patient | ClinicAdmin |
| GET | /patients/{patient_id} | Fetch a patient | ClinicAdmin, Therapist, Biller, Patient |
| GET | /patients/{patient_id}/cap-status | Return computed Medicare cap status | ClinicAdmin, Therapist, Biller |
| POST | /veteran-referrals | Register a VA Community Care referral | ClinicAdmin |
| GET | /veteran-referrals/{referral_id} | Fetch a VA referral | ClinicAdmin, Therapist |
| POST | /episodes | Open an episode in DRAFT | Therapist |
| GET | /episodes/{episode_id} | Fetch an episode (with refreshed unit counters) | ClinicAdmin, Therapist, Biller |
| GET | /episodes | List episodes | ClinicAdmin, Therapist, Biller |
| DELETE | /episodes/{episode_id} | Cancel a DRAFT episode | Therapist |
| POST | /episodes/{episode_id}/evaluations | Create an evaluation in DRAFT | Therapist |
| POST | /evaluations/{evaluation_id}/finalize | Finalize an evaluation | Therapist |
| POST | /evaluations/{evaluation_id}/amend | Amend a finalized evaluation | Therapist |
| POST | /episodes/{episode_id}/plan-of-cares | Create a plan of care in DRAFT | Therapist |
| POST | /plan-of-cares/{poc_id}/certify | Certify and activate a plan of care | Therapist |
| POST | /plan-of-cares/{poc_id}/revoke | Revoke an active plan of care | Therapist |
| GET | /plan-of-cares/{poc_id} | Fetch a plan of care | ClinicAdmin, Therapist, Biller |
| POST | /episodes/{episode_id}/authorizations | Create an authorization on an episode | ClinicAdmin, Therapist |
| GET | /authorizations/{authorization_id} | Fetch an authorization | ClinicAdmin, Therapist, Biller |
| POST | /episodes/{episode_id}/visits | Schedule a visit | Therapist |
| POST | /visits/{visit_id}/start | Mark a visit IN_SESSION | Therapist |
| POST | /visits/{visit_id}/sign | Sign a visit (compute units and charge) | Therapist |
| POST | /visits/{visit_id}/submit-claim | Submit a signed visit to the payer | Biller |
| POST | /visits/{visit_id}/cancel | Cancel a scheduled or in-session visit | Therapist |
| GET | /visits/{visit_id} | Fetch a visit | ClinicAdmin, Therapist, Biller |
| GET | /episodes/{episode_id}/visits | List visits on an episode | ClinicAdmin, Therapist, Biller |
| POST | /episodes/{episode_id}/home-exercise-programs | Draft a HEP | Therapist |
| POST | /home-exercise-programs/{hep_id}/issue | Issue the HEP | Therapist |
| POST | /home-exercise-programs/{hep_id}/acknowledge | Patient acknowledges the HEP | Patient |
| POST | /episodes/{episode_id}/mips-measures | Attest a quality measure for a visit | Therapist |
| GET | /episodes/{episode_id}/mips-measures | List MIPS rows on an episode | ClinicAdmin, Therapist, Biller |
| POST | /episodes/{episode_id}/discharge-assessments | Open a discharge assessment in DRAFT | Therapist |
| POST | /discharge-assessments/{discharge_id}/sign | Sign discharge | Therapist |
| POST | /_clock/advance | Test-only: advance the simulated clock | ClinicAdmin |
| GET | /_clock | Test-only: return the simulated clock's current `now` | ClinicAdmin, Therapist, Biller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_MISSING | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_EPISODE_NOT_ACTIVE | 409 |
| ERR_REEVAL_DUE | 409 |
| ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE | 403 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_VETERAN_REFERRAL_REQUIRED | 422 |
| ERR_VA_REFERENCE_MISMATCH | 422 |
| ERR_VA_REFERRAL_EXHAUSTED | 409 |
| ERR_CERT_PERIOD_TOO_LONG | 422 |
| ERR_OUT_OF_AUTH_WINDOW | 422 |
| ERR_CLINICIAN_DOUBLE_BOOKED | 409 |
| ERR_PATIENT_DOUBLE_BOOKED | 409 |
| ERR_POC_VISIT_LIMIT | 422 |
| ERR_INSUFFICIENT_UNITS | 422 |
| ERR_CAP_EXCEEDED | 422 |
| ERR_INVALID_MIPS_EXCEPTION | 422 |
| ERR_PAGINATION_RANGE | 400 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_DUPLICATE_NPI | 409 |
| ERR_VALIDATION | 400 |
