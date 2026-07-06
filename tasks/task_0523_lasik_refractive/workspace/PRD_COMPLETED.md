# Lasik Refractive Center API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a LASIK and refractive-surgery center. The center runs an end-to-end clinical and commercial workflow: a prospective patient is screened for surgical candidacy through corneal topography, a treatment package is selected and paid for (either outright or through a financed installment plan), a laser suite and operating surgeon are scheduled, consent is signed after the pre-operative eye-drop regimen has begun, the procedure is performed, and — once the eye has settled — a healed outcome is recorded. The system also manages the two commitments the center makes to every patient after surgery: a lifetime-or-windowed **enhancement** (a free touch-up when vision regresses within an eligibility window) and an **outcome/refund guarantee** (a monetary payout when the measured post-operative vision falls short of the guaranteed level).

The domain is deliberately cross-cutting. A single surgery case carries two independent lifecycles at once — a clinical axis (from planning through healing) and a financial axis (from unfunded through paid or refunded) — and many operations touch several resources at once, so cascades and ordering matter. Scheduling is constrained by suite turnaround, surgeon load, and daily capacity caps; financing is amortized to the cent; refunds branch by package policy; and the enhancement pathway is a genuine review loop that can bounce a request back for revision. Because coordinators can act on cases that other staff progress in parallel, the two most sensitive scheduling operations are guarded by optimistic concurrency. Every timestamp and every eligibility-window comparison is driven by a server-controlled logical clock so that time-dependent behaviour is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under `/refractive`.

### 2.1. User and Role-Based Access Control

Every request other than patient self-registration and the health check must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. When either header is missing on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes five roles, spelled exactly `Coordinator`, `Surgeon`, `Optometrist`, `Patient`, and `Anonymous`. A `Coordinator` is front-desk and operations staff: they manage configuration, create cases, run scheduling and financing, and adjudicate refunds. A `Surgeon` adjudicates screenings and enhancement requests and performs the clinical transitions (operate, heal). An `Optometrist` performs candidacy screening and enhancement re-screening. A `Patient` acts on their own case — signing consent, requesting enhancements, and filing refund claims. `Anonymous` is an unauthenticated caller who may only self-register as a patient.

Two roles are opaque operator identities. When `X-User-Role` is `Coordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise opaque and, in practice, need not be supplied because anonymous callers are confined to the open registration endpoint.

Three roles are entity-backed. When `X-User-Role` is `Surgeon`, `X-User-ID` is the `id` of the acting `Surgeon`; ownership checks on any resource that references a `Surgeon` compare the resource's surgeon foreign key to `X-User-ID`. When `X-User-Role` is `Optometrist`, `X-User-ID` is the `id` of the acting `Optometrist`; in particular, submitting a screening requires that `X-User-ID` equal the screening's `performed_by_optometrist_id`. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; a patient acts on their own resources, so consent, enhancement, and refund actions are scoped to the patient whose `id` matches `X-User-ID`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the server logical clock (Section 2.7) rather than wall-clock time.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100 by clamping out-of-range values into that range (a `limit` below 1 becomes 1, above 100 becomes 100). The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order; because many records share an identical `created_at` (the logical clock only advances on an explicit clock-set), ties are broken by `id` in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id`, formatted as a UUID with no type prefix, used purely for identity. Every resource also carries a `created_at`, an ISO 8601 UTC timestamp with three fractional digits stamped from the logical clock at creation.

Most resources additionally carry two mutation-tracking fields: `updated_at`, an ISO 8601 UTC timestamp refreshed on every change, and `version`, an integer that starts at its initial value of 1 and increments by one on each mutation. `LaserSuite`, `Surgeon`, `Optometrist`, `Patient`, `CandidacyScreening`, `SurgeryCase`, `FinancingPlan`, `ConsentForm`, `EnhancementRequest`, `SuiteBooking`, and `RefundClaim` all carry `updated_at` and `version`.

The one exception is `TreatmentPackage`. A treatment package carries only `id` and `created_at`; it has neither `updated_at` nor `version`. Packages are configuration records and are not mutation-tracked.

### 2.5. Optimistic Concurrency Control

Two operations on a surgery case are guarded by optimistic concurrency because a case can be advanced by more than one coordinator view. Both require the caller to declare the case version they last observed through the `expected_case_version` field, and both compare it against the target `SurgeryCase`'s current `version`.

When a suite booking is created for a case, the request must carry `expected_case_version` matching the case's current `version`. If the case's version has advanced since the client last read it — for example, another writer has already scheduled or cancelled it — the create is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), so the client cannot double-book a case it has not observed in its current form. Likewise, when a case is cancelled, the request must carry `expected_case_version` matching the case's current `version`; a mismatch is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). No other endpoint takes a version field, and endpoints outside these two never apply an OCC check.

### 2.6. Monetary Amounts, Precision, and Rounding

All monetary amounts are integers denominated in cents (for example `base_price_cents`, `deposit_cents`, `down_payment_cents`, `apr_bps` as basis points, `amount_cents`, `amount_settled_cents`, `monthly_installment_cents`, `refund_amount_cents`, and `GUARANTEE_FEE_CENTS`). No monetary value is ever a fractional number of cents in a stored field.

Two derived monetary calculations pin their rounding direction explicitly. The amortized monthly installment is computed once at plan creation and rounded **up** to a whole number of cents (ceiling). The refund payout is computed in whole cents and floored at zero, so it can never be negative. The ablation-depth estimate, a micron quantity rather than money, is rounded to the nearest whole micron using round-half-up, applied a single time after the full product is formed. Detailed formulas live with their business narratives in Section 3.

### 2.7. The Logical Clock and Time Semantics

The server keeps a single logical clock that drives every timestamp it stamps (`created_at`, `updated_at`, `surgery_completed_at`, `signed_at`) and every time-window comparison (enhancement eligibility, heal settling). At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it stays at that default and never falls back to wall-clock time. An administrative test-driving capability lets a `Coordinator` advance the clock to a supplied `to_iso8601` instant, after which the response reports the new `current_utc`. All downstream time reasoning uses this clock, at second resolution for window comparisons.

### 2.8. Hierarchical Consistency and Cascading Effects

Resources are peers linked by explicit foreign keys rather than nested containment, but several operations still ripple across resources, and each such ripple is a real mutation on the affected resource: it refreshes that resource's `updated_at` and increments its `version` where those fields exist. The most consequential cascade is case cancellation, which resolves everything a case had committed — its active bookings, its signed consents, and its open financing — as a single coordinated effect (detailed in Section 3). Several server-initiated transitions also propagate a patient's derived standing and a financing plan's settlement without an explicit client request on those resources. Whenever the server reconciles a resource this way, the reconciliation independently bumps that resource's `version` and `updated_at`.

### 2.9. Nested Retrieval and Left-to-Right Validation

Several read paths address a child collection through a parent (for example, a case's bookings, a case's financing plans, a case's consent forms, or a patient's screenings). For any such path, the server validates the referenced identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource. The same left-to-right existence discipline applies to body-referenced identifiers on writes. Existence is checked before role permission has any bearing on business outcome, and validation as a whole follows a fixed precedence across the system: authentication first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN`), then existence of referenced resources (`ERR_NOT_FOUND`), then request well-formedness — valid JSON with all required fields present and correctly typed, failing which the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Only after these gates do state and business rules run: a transition attempted from a state in which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409), and OCC (Section 2.5) is checked as part of that state layer.

## 3. Business Logic & Workflows

### 3.1. Configuration: Packages, Suites, Surgeons, and Optometrists

Before any patient can be treated, a `Coordinator` provisions the center's catalog and staff. A **treatment package** captures the commercial and guarantee terms of a procedure offering. It is created with a `tier` — one of `STANDARD`, `PREMIUM`, or `LIFETIME` — a `base_price_cents` (the sticker price before any deposit or financing, at least zero), a `deposit_cents` (the non-refundable deposit needed to book a suite, at least zero and no greater than `base_price_cents`), and an `enhancement_window_days` value (the number of days after surgery during which a free enhancement is covered, at least zero; a `LIFETIME` package uses 36500). The package also declares `outcome_guarantee_uncorrected_va`, the guaranteed post-operative uncorrected visual acuity expressed as a decimal greater than zero where 1.0 denotes 20/20 vision, and a `refund_mode` of either `PRO_RATA` or `DEPOSIT_FORFEIT` that selects which refund algorithm applies if the guarantee is missed. A package is created with `active` defaulting to true; only an active package may back new surgery cases.

A **laser suite** is created with a human-readable `name`, a `turnaround_buffer_minutes` value (the mandatory cleaning and reset gap the suite requires after one booking ends before the next may start, at least zero), and a `daily_case_cap` (the maximum number of active bookings the suite may hold on a single UTC calendar day, at least one). A suite's `status` defaults to `OPEN` and may be `MAINTENANCE`. A **surgeon** is created with a `full_name`, a `max_daily_cases` limit (the most active bookings that may be assigned to that surgeon on one UTC calendar day, at least one), and an `accepting` flag defaulting to true. An **optometrist** is created with only a `full_name`.

### 3.2. Patient Registration and Candidacy Screening

Anyone may register a patient; this is the single open, unauthenticated write, and it may also be performed by a `Coordinator`. Registration supplies a `full_name`, a `date_of_birth` as an ISO date in `YYYY-MM-DD` form (used later for the minimum-age check), and an optional `co_managing_optometrist_id` referencing the co-managing optometrist, which defaults to null; when supplied it must resolve to an existing `Optometrist`, else `ERR_NOT_FOUND` (HTTP 404). A newly registered patient begins with `status` set to `PROSPECT`; over their journey this derived standing moves to `CANDIDATE`, `INELIGIBLE`, or `OPERATED`.

Candidacy is established through corneal topography captured by a co-managing optometrist. An `Optometrist` creates a screening in `DRAFT` status, supplying the `patient_id`, the `performed_by_optometrist_id`, the central `corneal_thickness_um` in microns (at least zero), the steepest keratometry reading `topography_k_max` in diopters (greater than zero, the ectasia-risk marker), and the spherical-equivalent `refractive_error_diopters` magnitude (at least zero). Two further values, `ablation_depth_um` and `residual_stromal_bed_um`, are not supplied at creation; they are computed when the screening is submitted.

**Submitting** a screening moves it from `DRAFT` to `SUBMITTED` and may be performed only by the optometrist who ran it — the screening must currently be in `DRAFT` (checked first, `ERR_INVALID_STATE` (HTTP 409) otherwise), and the acting optometrist's identity must equal `performed_by_optometrist_id` (checked next, `ERR_FORBIDDEN` (HTTP 403) otherwise). Submission recomputes two derived quantities in a pinned order. First, the **ablation depth** is estimated: form the product of the square of the optical zone in millimeters (a fixed 1.0 mm), the screening's own `refractive_error_diopters`, and the depth removed per diopter (a fixed 12.0 microns per diopter), then round that single product to the nearest whole micron using round-half-up, and store it as `ablation_depth_um`. Only after the ablation depth exists is the **residual stromal bed** derived: take `corneal_thickness_um`, subtract the fixed flap thickness of 110 microns, then subtract `ablation_depth_um`, and store the whole-micron result as `residual_stromal_bed_um`.

**Adjudication** moves a `SUBMITTED` screening to a terminal `APPROVED` or `REJECTED` and is performed by a `Surgeon` who supplies a `decision`. The screening must be in `SUBMITTED`. On an approve decision, four safety gates are evaluated, and they are checked strictly in this order — residual bed first, then keratometry, then refractive error, then age:

1. The residual stromal bed must be adequate: `residual_stromal_bed_um` must be at least the minimum safe residual bed, which is 350 microns. If it falls below that floor, approval is refused with `ERR_RESIDUAL_BED_TOO_THIN` (HTTP 422).
2. The cornea must not be too steep: `topography_k_max` must be strictly less than the maximum safe keratometry, which is 48.0 diopters. If it is at or above that ceiling, approval is refused with `ERR_ECTASIA_RISK_K` (HTTP 422).
3. The error must be treatable: `refractive_error_diopters` must be no greater than the maximum treatable diopters, which is 8.0. If it exceeds that, approval is refused with `ERR_ERROR_UNTREATABLE` (HTTP 422).
4. The patient must be old enough: the patient's age in whole years as of the current logical-clock instant must be at least the minimum age, which is 18 years. If younger, approval is refused with `ERR_PATIENT_UNDERAGE` (HTTP 422).

When all four gates pass, the screening becomes `APPROVED` and, bubbling up to the patient this screening belongs to, that `Patient`'s `status` is set to `CANDIDATE`. A reject decision moves the screening to `REJECTED` and sets its `rejection_reason` to the first failing check evaluated in that same order — `THIN_BED`, then `HIGH_K`, then `HIGH_ERROR`, then `UNDERAGE`; if no gate would have failed (the screening was otherwise approvable but the surgeon still rejected it), `rejection_reason` is left null. Additionally, if the patient still has no approved screening, the patient's `status` is set to `INELIGIBLE`. The approve and reject branches are deliberate counterparts: approve runs the gate battery and promotes the patient to candidate, while reject records a reason and may downgrade the patient to ineligible.

### 3.3. Opening a Surgery Case and Its Two Independent Axes

A `Coordinator` opens a **surgery case** by supplying a `patient_id`, a `screening_id`, and a `package_id`. The referenced screening must be an `APPROVED` `CandidacyScreening` that belongs to the same patient; otherwise the case is refused with `ERR_SCREENING_NOT_APPROVED` (HTTP 422). A new case starts with `clinical_status` at `PLANNED` and `financial_status` at `UNFUNDED`. These two axes advance independently: the clinical axis runs `PLANNED → SCHEDULED → CONSENTED → OPERATED → HEALED`, while the financial axis runs from `UNFUNDED` toward `DEPOSIT_PAID`, `PAID_IN_FULL`, or `REFUNDED`. The case also holds `surgery_completed_at` (null until the procedure is performed) and `final_uncorrected_va` (null until the case is healed).

### 3.4. Funding a Case: Financing, Installments, and Settlement

Funding is the financial axis, driven entirely by a `Coordinator`, and it begins from `UNFUNDED`; if the case's financial status is not `UNFUNDED` the create is rejected as an invalid state transition with `ERR_INVALID_STATE` (HTTP 409). Creating financing supplies a `down_payment_cents` (the amount paid up front, at least zero), a `term_months` count (the number of monthly installments for the financed remainder, at least one and no more than sixty), and an `apr_bps` annual rate in basis points (at least zero, so that 1200 denotes 12.00%). The down payment must cover at least the package deposit; a down payment below `deposit_cents` is rejected with `ERR_DEPOSIT_TOO_LOW` (HTTP 422).

There are two funding outcomes, and both create a `FinancingPlan` and set the case's financial status. When the down payment covers at least the deposit but is strictly less than the package's `base_price_cents`, an `OPEN` plan is created, its computed `monthly_installment_cents` is set, its `amount_settled_cents` is initialized to the down payment, and the case moves to `DEPOSIT_PAID`. When the down payment equals the package's `base_price_cents` exactly, the case is paid outright: the plan is created already `SETTLED` with `term_months` coerced to 1, `monthly_installment_cents` set to 0, and `amount_settled_cents` equal to the base price, and the case moves straight to `PAID_IN_FULL`. Setting the case's financial status this way is a mutation on the case: whenever the case's financial status changes, the case's `version` increments by one (as it does for the scheduling and cancellation transitions on the clinical axis).

For an open plan, the **amortized monthly installment** is computed once at creation from the financed principal, which is the package's `base_price_cents` minus the `down_payment_cents`. Convert the annual rate to a decimal monthly rate by dividing `apr_bps` by 10000 and then by 12. If that monthly rate is zero, the raw installment is simply the principal divided by `term_months`. Otherwise, raise the quantity (one plus the monthly rate) to the power of `term_months` to obtain a growth factor, then the raw installment is the principal multiplied by the monthly rate multiplied by that growth factor, all divided by the growth factor minus one. Finally, round the raw installment **up** to a whole number of cents and store it as `monthly_installment_cents`.

Posting an **installment** against an open plan supplies an `amount_cents` value (at least zero) that is added to the plan's `amount_settled_cents`. The plan must be `OPEN` and the case must currently be in `DEPOSIT_PAID`, else the post is rejected as an invalid state transition with `ERR_INVALID_STATE` (HTTP 409). Once the running `amount_settled_cents` reaches or exceeds the package's `base_price_cents`, the plan flips to `SETTLED` and, bubbling up, the case's financial status moves to `PAID_IN_FULL`.

### 3.5. Scheduling: Suite Bookings Under Concurrency and Capacity Limits

Scheduling advances the clinical axis from `PLANNED` to `SCHEDULED` by creating an active **suite booking**, and it is where the tightest constraints live. A `Coordinator` books a case by supplying a `suite_id`, a `surgeon_id`, a `slot_start` and `slot_end` (ISO 8601 UTC instants describing the half-open operating interval that starts at `slot_start` and ends just before `slot_end`), and the `expected_case_version` guard. The case must be in `PLANNED`, it must be funded — that is, its financial status must be `DEPOSIT_PAID` or `PAID_IN_FULL`, failing which the booking is refused with `ERR_CASE_NOT_FUNDED` (HTTP 422) — and no active booking may already reference the case, else the booking is rejected as an invalid state transition with `ERR_INVALID_STATE` (HTTP 409). A successful booking is created with status `ACTIVE`, the case advances to `SCHEDULED`, and the case's `version` increments by one.

Several booking constraints are enforced, each with its own rejection. The slot interval must be well-formed: `slot_end` must be strictly after `slot_start`, else `ERR_INVALID_SLOT` (HTTP 422). The suite's committed schedule must stay clear: the new interval, extended by the suite's `turnaround_buffer_minutes` cleaning gap after it ends, must not overlap any other active booking on the same suite, else `ERR_SUITE_TIME_CONFLICT` (HTTP 409). The surgeon's schedule must also stay clear, but with no buffer: the bare new interval must not overlap any other active booking of the same surgeon, else `ERR_SURGEON_TIME_CONFLICT` (HTTP 409). Capacity is capped per calendar day: the number of active bookings on that suite for the UTC calendar day of `slot_start` must not exceed the suite's `daily_case_cap`, else `ERR_SUITE_DAILY_CAP` (HTTP 409), and the number of active bookings for that surgeon on the same UTC day must not exceed the surgeon's `max_daily_cases`, else `ERR_SURGEON_DAILY_CAP` (HTTP 409). Both resources must be available: the suite's `status` must be `OPEN` and the surgeon's `accepting` flag must be true, else `ERR_RESOURCE_UNAVAILABLE` (HTTP 409).

Because a case can be advanced by another coordinator view between the moment one reads it and the moment one books it, the booking carries `expected_case_version`; if it does not match the case's current `version`, the booking is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) as described in Section 2.5.

### 3.6. Consent and the Day of Surgery

Consent advances the clinical axis from `SCHEDULED` to `CONSENTED`. The patient signs their own consent by attesting that the pre-operative antibiotic and steroid drops regimen has begun, supplying `drops_regimen_started` and `signed_by_patient_id`. The case must be in `SCHEDULED`. The attestation must be affirmative — if `drops_regimen_started` is not true, the signature is refused with `ERR_DROPS_NOT_STARTED` (HTTP 422) — and the signer must be the case's own patient: `signed_by_patient_id` must equal the case's `patient_id`, else `ERR_CONSENT_PATIENT_MISMATCH` (HTTP 422). On success a `ConsentForm` is created in `SIGNED` status with its `signed_at` stamped from the logical clock, and the case advances to `CONSENTED`. A consent form may later be `REVOKED`.

Performing the procedure advances the case from `CONSENTED` to `OPERATED` and is a `Surgeon` action. The case must be in `CONSENTED`, it must have an active suite booking whose `slot_start` is at or before the current logical-clock instant, and it must have a signed (not revoked) consent form; if either the ready active booking or the signed consent form is absent, the transition is refused as an invalid state transition with `ERR_INVALID_STATE` (HTTP 409). On success the case moves to `OPERATED`, `surgery_completed_at` is stamped from the logical clock, and — bubbling up — the `Patient`'s `status` is set to `OPERATED`.

Recording the healed outcome advances the case from `OPERATED` to `HEALED` and is also a `Surgeon` action, supplying the measured `final_uncorrected_va`. The case must be in `OPERATED`, and enough time must have elapsed: the current logical-clock instant must be at or after `surgery_completed_at` plus the heal-settling period in days, which is 30 days, else the transition is refused with `ERR_HEAL_TOO_EARLY` (HTTP 422). On success the `final_uncorrected_va` is recorded and the case moves to `HEALED`.

### 3.7. Cancelling a Case and Its Cascade

A `Coordinator` may cancel a case while its clinical status is `PLANNED`, `SCHEDULED`, or `CONSENTED`; a cancel attempted from any other clinical status is refused as an invalid state transition. Cancellation carries the `expected_case_version` guard, and a mismatch against the case's current `version` is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). On success the cancellation performs a coordinated multi-resource cascade: the case's `clinical_status` becomes `CANCELLED`; every active suite booking of the case is released, moving each to `RELEASED`; every signed consent form of the case is revoked, moving each to `REVOKED`; and if an open financing plan exists it is set to `CANCELLED`, after which the case's financial axis is set to `REFUNDED` only if it was `PAID_IN_FULL` and is otherwise left unchanged. Finally the case's `version` increments by one. This is the intended three-hop chain: cancelling the case cancels its open financing, which in turn may flip the financial status.

### 3.8. The Enhancement Pathway and Its Revision Loop

After a case has healed, the patient may seek a free touch-up through an **enhancement request**, which either a `Patient` or a `Coordinator` may create. Creation supplies the `origin_case_id` (the prior healed case whose outcome is to be enhanced; its `clinical_status` must be `HEALED`, else the request is rejected as an invalid state transition with `ERR_INVALID_STATE` (HTTP 409)), the `patient_id` (which must equal the origin case's patient, else `ERR_INVALID_REQUEST` (HTTP 400)), and a free-text `reason` describing the regression or residual error. At creation the system pins `within_window`: compute the eligibility deadline as the origin case's `surgery_completed_at` plus the origin package's `enhancement_window_days`, and set `within_window` to true only when the current logical-clock instant is strictly before that deadline. The boundary is exclusive — an instant exactly equal to the deadline is already expired. A request created outside the window is refused with `ERR_ENHANCEMENT_WINDOW_EXPIRED` (HTTP 422); the same window rule guards the re-screening step. A new request begins in `REQUESTED` status with `re_screening_id` null.

The enhancement then runs a genuine review loop. An `Optometrist` attaches a re-screening, moving the request from `REQUESTED` to `RE_SCREENING`: the request must be in `REQUESTED`, it must still be within window, and the supplied `re_screening_id` must reference an existing candidacy screening belonging to the request's patient (a screening that resolves but belongs to a different patient is rejected with `ERR_INVALID_REQUEST` (HTTP 400)); on success `re_screening_id` is stored and the status becomes `RE_SCREENING`. From `RE_SCREENING` a `Surgeon` may return the request for revision, which clears `re_screening_id` back to null and returns the status to `REQUESTED` — this is the cyclic revision loop `RE_SCREENING → REQUESTED → RE_SCREENING`. Alternatively, from `RE_SCREENING` a `Surgeon` adjudicates with a `decision`: an approve decision requires that the attached re-screening's `CandidacyScreening` status be `APPROVED` (else the approve is refused as an invalid state transition with `ERR_INVALID_STATE` (HTTP 409)) and moves the request to `APPROVED`, while a deny decision moves it to the terminal `DENIED`. Finally, an `APPROVED` request may be moved by a `Surgeon` to the terminal `FULFILLED`, recording that the touch-up has been delivered.

### 3.9. The Outcome Guarantee and Dual-Variant Refunds

When a healed case falls short of its guaranteed vision, the patient is entitled to a monetary refund. Either a `Patient` or a `Coordinator` files a **refund claim** for a `case_id`. The claim is admissible only when the case is `HEALED` and actually missed its guarantee — that is, the case's `final_uncorrected_va` is strictly worse than (less than) the package's `outcome_guarantee_uncorrected_va`; if the measured acuity met or exceeded the guarantee, the claim is refused with `ERR_GUARANTEE_NOT_MET` (HTTP 422). At creation the claim copies `measured_uncorrected_va` from the case's `final_uncorrected_va` and copies `refund_mode` from the case's package. A new claim begins in `PENDING`.

A `Coordinator` adjudicates a pending claim with a `decision`. A reject decision moves the claim to `REJECTED`. A pay decision has preconditions: the claim must be `PENDING`, the origin case's financial status must be `PAID_IN_FULL` (else the pay is rejected as an invalid state transition with `ERR_INVALID_STATE` (HTTP 409)), and no fulfilled enhancement request may exist for the origin case — because if the center already honored the guarantee through an enhancement, it will not also pay cash, so a pay attempt in that situation is refused with `ERR_ENHANCEMENT_ALREADY_FULFILLED` (HTTP 409). On a successful pay decision the payout is computed and stored in `refund_amount_cents`, the claim moves to `PAID`, and the origin case's financial status is set to `REFUNDED`.

The **refund payout** is dual-variant, selected by the claim's `refund_mode`, and both variants operate on the money actually collected — the financing plan's `amount_settled_cents`. Under `PRO_RATA`, the payout is the settled amount minus the package's non-refundable `deposit_cents`, floored at zero so it is never negative. Under `DEPOSIT_FORFEIT`, the payout is the settled amount minus the package's `deposit_cents` and minus a fixed guarantee-processing fee of 25000 cents, again floored at zero; this variant is the larger clawback because it also withholds the processing fee.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions and the clock-set capability — return `200 OK`. Retrieval operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/refractive/packages` | Create a treatment package | Coordinator |
| GET | `/refractive/packages/{id}` | Fetch a package | Coordinator, Surgeon, Optometrist, Patient |
| GET | `/refractive/packages` | List packages | Coordinator, Surgeon, Optometrist, Patient |
| POST | `/refractive/suites` | Create a laser suite | Coordinator |
| GET | `/refractive/suites/{id}` | Fetch a suite | Coordinator, Surgeon |
| POST | `/refractive/surgeons` | Create a surgeon | Coordinator |
| GET | `/refractive/surgeons/{id}` | Fetch a surgeon | Coordinator, Surgeon |
| POST | `/refractive/optometrists` | Create an optometrist | Coordinator |
| GET | `/refractive/optometrists/{id}` | Fetch an optometrist | Coordinator, Optometrist |
| POST | `/refractive/patients` | Register a patient (open) | Anonymous, Coordinator |
| GET | `/refractive/patients/{id}` | Fetch a patient | Coordinator, Surgeon, Optometrist, Patient |
| GET | `/refractive/patients` | List patients | Coordinator, Surgeon, Optometrist |
| GET | `/refractive/patients/{id}/screenings` | List a patient's screenings | Coordinator, Surgeon, Optometrist, Patient |
| POST | `/refractive/screenings` | Create a draft screening | Optometrist |
| GET | `/refractive/screenings/{id}` | Fetch a screening | Coordinator, Surgeon, Optometrist, Patient |
| GET | `/refractive/screenings` | List screenings | Coordinator, Surgeon, Optometrist |
| POST | `/refractive/screenings/{id}/submit` | Submit a screening (compute ablation/residual) | Optometrist |
| POST | `/refractive/screenings/{id}/adjudicate` | Approve or reject a screening | Surgeon |
| POST | `/refractive/cases` | Create a surgery case | Coordinator |
| GET | `/refractive/cases/{id}` | Fetch a case | Coordinator, Surgeon, Optometrist, Patient |
| GET | `/refractive/cases` | List cases | Coordinator, Surgeon, Optometrist, Patient |
| POST | `/refractive/cases/{id}/financing` | Create a financing plan | Coordinator |
| GET | `/refractive/cases/{id}/financing` | List a case's financing plans | Coordinator, Patient |
| POST | `/refractive/cases/{id}/bookings` | Create a suite booking (OCC guarded) | Coordinator |
| GET | `/refractive/cases/{id}/bookings` | List a case's bookings | Coordinator, Surgeon, Patient |
| GET | `/refractive/bookings` | List suite bookings | Coordinator, Surgeon |
| GET | `/refractive/bookings/{id}` | Fetch a suite booking | Coordinator, Surgeon, Patient |
| GET | `/refractive/consent-forms` | List consent forms | Coordinator, Surgeon, Patient |
| GET | `/refractive/consent-forms/{id}` | Fetch a consent form | Coordinator, Surgeon, Patient |
| POST | `/refractive/cases/{id}/consent` | Sign consent | Patient |
| GET | `/refractive/cases/{id}/consent` | List a case's consent forms | Coordinator, Surgeon, Patient |
| POST | `/refractive/cases/{id}/operate` | Perform the procedure | Surgeon |
| POST | `/refractive/cases/{id}/heal` | Record the healed outcome | Surgeon |
| POST | `/refractive/cases/{id}/cancel` | Cancel a case (OCC guarded, cascades) | Coordinator |
| POST | `/refractive/financing/{id}/installments` | Post an installment | Coordinator |
| GET | `/refractive/financing/{id}` | Fetch a financing plan | Coordinator, Patient |
| POST | `/refractive/enhancements` | Create an enhancement request | Patient, Coordinator |
| GET | `/refractive/enhancements/{id}` | Fetch an enhancement request | Coordinator, Surgeon, Optometrist, Patient |
| GET | `/refractive/enhancements` | List enhancement requests | Coordinator, Surgeon, Optometrist, Patient |
| POST | `/refractive/enhancements/{id}/rescreen` | Attach a re-screening | Optometrist |
| POST | `/refractive/enhancements/{id}/return-for-revision` | Return an enhancement for revision | Surgeon |
| POST | `/refractive/enhancements/{id}/adjudicate` | Approve or deny an enhancement | Surgeon |
| POST | `/refractive/enhancements/{id}/fulfill` | Fulfill an approved enhancement | Surgeon |
| POST | `/refractive/refund-claims` | File a refund claim | Coordinator, Patient |
| GET | `/refractive/refund-claims/{id}` | Fetch a refund claim | Coordinator, Patient |
| GET | `/refractive/refund-claims` | List refund claims | Coordinator, Patient |
| POST | `/refractive/refund-claims/{id}/adjudicate` | Pay or reject a refund claim | Coordinator |
| POST | `/refractive/_clock/set_current_utc` | Set the server logical clock | Coordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_RESIDUAL_BED_TOO_THIN` | 422 |
| `ERR_ECTASIA_RISK_K` | 422 |
| `ERR_ERROR_UNTREATABLE` | 422 |
| `ERR_PATIENT_UNDERAGE` | 422 |
| `ERR_SCREENING_NOT_APPROVED` | 422 |
| `ERR_CONSENT_PATIENT_MISMATCH` | 422 |
| `ERR_CASE_NOT_FUNDED` | 422 |
| `ERR_DROPS_NOT_STARTED` | 422 |
| `ERR_SUITE_TIME_CONFLICT` | 409 |
| `ERR_SURGEON_TIME_CONFLICT` | 409 |
| `ERR_INVALID_SLOT` | 422 |
| `ERR_ENHANCEMENT_WINDOW_EXPIRED` | 422 |
| `ERR_HEAL_TOO_EARLY` | 422 |
| `ERR_SUITE_DAILY_CAP` | 409 |
| `ERR_SURGEON_DAILY_CAP` | 409 |
| `ERR_RESOURCE_UNAVAILABLE` | 409 |
| `ERR_DEPOSIT_TOO_LOW` | 422 |
| `ERR_GUARANTEE_NOT_MET` | 422 |
| `ERR_ENHANCEMENT_ALREADY_FULFILLED` | 409 |
