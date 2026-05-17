# Home Health Dispatch API — Product Requirements Document

## 1. Introduction

Home health agencies coordinate care that touches three very different workflows in the same week: a clinician arrives at a patient's home, performs an OASIS assessment, locks the plan of care; nurses, therapists, and home-health aides drive between visits across a 60-day Medicare episode; and a billing team reconciles everything into a single PDGM claim once the episode closes. The friction lives in the seams — a skilled nurse visit booked outside the episode window, an aide hour beyond what was ordered, mileage rounded the wrong way, or a recertification OASIS locked a day too early — and each seam is the difference between a clean claim and a recoupment.

This document specifies the Home Health Dispatch API, the system of record that binds those workflows together. It governs the lifecycle from OASIS authoring, through episode opening, visit scheduling and completion, mileage capture, and ultimately the dual-variant computation of provisional and final PDGM payment. The intent is to make every dispatch and billing decision auditable and deterministic, so that two episodes with the same OASIS inputs and the same chronological visit log always produce the same claim. Where the underlying CMS rules embed thresholds, tier breakpoints, or time windows, this document pins them precisely.

## 2. Global Specifications & System-Wide Principles

This section establishes system-wide rules — authentication, response envelope, pagination, common resource conventions, precision, concurrency, and the cross-cutting dispatch and billing principles that any reader must internalize before reading the business logic in §3.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the role under which the action is being performed. Either header missing or malformed terminates the request with `ERR_AUTH_MISSING`. A request whose role is not authorized for the endpoint per §1.7 (reflected in §4's table) is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `IntakeCoordinator`, `FieldClinician`, `BillingSpecialist`, and `PlatformAdmin`. Their identity semantics are distinct and matter for ownership checks:

- When `X-User-Role` is `FieldClinician`, `X-User-ID` is the `id` of the acting `Clinician`; ownership checks on any resource that references a `Clinician` compare the resource's foreign-key field to `X-User-ID`. In particular, completing a visit requires that `X-User-ID` equal the `clinician_id` recorded on the `Visit`.
- When `X-User-Role` is `IntakeCoordinator`, `BillingSpecialist`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`.

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

List endpoints accept two query-string parameters that control the page window. The `limit` parameter caps the number of items returned and defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the beginning of the result set and defaults to 0.

Unless explicitly stated otherwise, list endpoints sort by `created_at` ascending — the resource that was created first appears first. The `meta` object on a list response includes `limit`, `offset`, `total_count`, and `has_more` in addition to the standard envelope fields.

### 2.4. Common Resource Properties

Every primary resource — `Patient`, `Clinician`, `OASISAssessment`, `Episode`, `Visit`, and `PDGMClaim` — carries a system-managed `id` (UUID string, no type prefix), a `created_at` ISO 8601 UTC timestamp with three fractional digits indicating when it was first written, an `updated_at` ISO 8601 UTC timestamp refreshed on any subsequent mutation, and a `version` integer that begins at 1 and increases by exactly 1 every time the resource is mutated.

`MileageLog` is immutable once recorded; the row carries `id` and `created_at` but **does not carry `updated_at` and does not carry `version`** — both fields are absent from the JSON response.

The `ClockState` singleton is purely a test-driving lever: it carries no `id`, no `created_at`, no `updated_at`, and no `version`. Its sole exposed attribute is `current_date`.

### 2.5. Nested Resource Validation

Many endpoints carry multiple identifiers in their path — for example, an OASIS read targets a patient and an OASIS, and a visit-cancel operation transits a visit identifier. The server validates path identifiers strictly left-to-right and stops on the first one that does not resolve, returning `ERR_NOT_FOUND` for that identifier. A request that references a missing patient will surface the patient-level miss before the server attempts to load the OASIS, even if the OASIS identifier is itself fabricated. This ordering also extends to creation operations: the parent must resolve before any child-payload validation is attempted.

### 2.6. Monetary Precision, Mileage Tiers, and Rounding

Money in this system always rounds half-up. Two-decimal precision (cents) is the API surface for the PDGM claim's `provisional_payment` and `final_payment`, for the `total_mileage_reimbursement` aggregated onto the claim, and for the per-row `reimbursement_amount` recorded on each `MileageLog`. The intermediate wage-adjusted base used by the case-mix path of PDGM payment rounds half-up to four decimals before it is multiplied by the case-mix weight; the multiplication's product is then rounded half-up to two decimals.

The PDGM `case_mix_weight` is itself stored to four decimals — looked up directly from the case-mix table keyed by the episode's timing category, the OASIS clinical grouping, the OASIS functional impairment level, and the OASIS admission source.

Mileage uses a round-then-sum convention that is load-bearing: each `MileageLog`'s `reimbursement_amount` is rounded to two decimals at insertion time, and the claim's `total_mileage_reimbursement` is the sum of those already-rounded values with no further rounding. Aggregating raw tiered amounts and rounding once at the end is **not** equivalent and is not permitted; the round-then-sum ordering must be preserved.

### 2.7. The 60-Day Episode Clock and Scheduled Sweeps

Time in this system is driven by a server-controlled logical clock rather than the wall clock, so tests are deterministic. The `current_date` on the `ClockState` singleton is advanced monotonically through an admin-only test-driving capability that takes a `target_date` ISO date in the request body. The target must be on or after the existing `current_date`; attempting to move the clock backward is rejected with `ERR_CLOCK_BACKWARDS`. A separate admin-only sweep capability iterates open episodes and applies the expiration rules described in §3.

The clock is the gating mechanism for three time-sensitive decisions: whether a recertification OASIS is locking inside the permitted window, whether an episode is eligible to be closed, and whether an open episode has been abandoned long enough that the sweep should expire it. Each rule is stated in its own §3 subsection — the principle here is that any decision involving "today" reads `current_date`, never the host's wall clock.

### 2.8. Concurrency and Optimistic Locking

PATCH endpoints accept an optional `version` field in the request body to support optimistic concurrency control. When the caller includes `version`, the server compares it to the resource's current `version`; on mismatch the request is rejected with `ERR_VERSION_CONFLICT`. Omitting `version` skips the check entirely and the mutation proceeds against whatever the server's current state is — this is by design for callers who explicitly want a last-writer-wins update.

Beyond OCC, the system serializes several races at the entity level so that exactly one of the racing requests succeeds and the other receives a deterministic error:

- Two concurrent attempts to open an `Episode` from the **same** `LOCKED` `OASISAssessment` serialize on `Episode.source_oasis_id`; the winner creates the episode, and the loser is rejected with `ERR_OASIS_ALREADY_USED`.
- Two concurrent attempts to open an `Episode` on the **same patient** using two **different** `LOCKED` OASIS rows serialize on the constraint of at most one `OPEN` episode per patient; the winner creates the episode, and the loser is rejected with `ERR_PATIENT_HAS_OPEN_EPISODE`.
- Two concurrent attempts to schedule a `Visit` for the same `Clinician` at overlapping `[start_minute, end_minute)` windows on the same `visit_date` serialize on the clinician's calendar; the winner schedules the visit, and the loser is rejected with `ERR_CLINICIAN_DOUBLE_BOOKED`.
- A close attempt and an expire-sweep that target the same `OPEN` `Episode` serialize on the episode's transition out of `OPEN`; exactly one of them succeeds, and the other is rejected with `ERR_EPISODE_NOT_OPEN`.

### 2.9. Validation Ordering

Every endpoint runs a fixed validation pipeline in a strict priority order; the first failing check is the rejection reason, and no later check is evaluated. The ordering is uniform across the API:

1. Auth header presence and shape (`ERR_AUTH_MISSING`).
2. RBAC: the acting role is authorized for the endpoint (`ERR_FORBIDDEN`).
3. Path-parameter existence, left-to-right (`ERR_NOT_FOUND`).
4. State preconditions on the target resource (e.g., `ERR_OASIS_NOT_DRAFT`, `ERR_OASIS_NOT_LOCKED`, `ERR_EPISODE_NOT_OPEN`, `ERR_VISIT_NOT_SCHEDULED`).
5. Business safety/compliance: license expiration (`ERR_CLINICIAN_LICENSE_EXPIRED`), clinician availability (`ERR_CLINICIAN_NOT_AVAILABLE`), discipline-to-visit-type match (`ERR_DISCIPLINE_MISMATCH`), recertification window (`ERR_RECERT_WINDOW_VIOLATION`) — evaluated in this internal order.
6. Business temporal/referential: visit date inside the episode window (`ERR_VISIT_OUTSIDE_EPISODE`), visit minute bounds (`ERR_VISIT_TIME_INVALID`), clinician double-booking (`ERR_CLINICIAN_DOUBLE_BOOKED`), OASIS-already-used / open-episode-exists (`ERR_OASIS_ALREADY_USED`).
7. Business fiscal/quota: HHA hours cap (`ERR_HHA_HOURS_EXCEEDED`).
8. Business constraints: positive mileage (`ERR_MILEAGE_NOT_POSITIVE`), mileage parent visit completed (`ERR_MILEAGE_VISIT_NOT_COMPLETED`), OCC version check (`ERR_VERSION_CONFLICT`).

Where two checks at the same category guard the same endpoint, the priority order above is the tie-breaker. For example, on visit scheduling the safety/compliance checks run before the temporal checks, so an expired license surfaces before an out-of-window date even if both are violated; among the safety checks, license expiration surfaces before clinician availability, which surfaces before discipline mismatch.

## 3. Business Logic & Workflows

### 3.1. Patients, ZIP Codes, and Wage Index

A patient enters the system when an `IntakeCoordinator` (or `PlatformAdmin`) registers them with a `full_name`, a `medicare_id`, and a `home_zip` — the five-digit ZIP code of the residence where home-health visits will be performed. The `medicare_id` is unique across patients; a second patient registered with a Medicare identifier already in use is rejected.

The ZIP code is not just demographic metadata. The PDGM payment formula is wage-adjusted by `wage_index` — a per-CBSA multiplier looked up from the patient's residence ZIP. The system computes `wage_index` from `home_zip` at patient creation and stores it on the patient row. If the patient's `home_zip` is later changed through a coordinator-driven update — which may also adjust the `full_name` — the server recomputes `wage_index` from the new ZIP and refreshes `updated_at` and `version`. Subsequent claim computations read `wage_index` off the patient row at the moment of computation: the provisional payment reads it when an episode opens, and the final payment reads it again when an episode closes, so a `home_zip` change in between can produce a different `final_payment` than the `provisional_payment` even when no other inputs vary.

Patient listing accepts a `medicare_id` filter — useful when reconciling against an external roster — along with the usual `limit` and `offset` pagination controls.

### 3.2. Clinicians and Their Discipline

Clinicians are managed by `PlatformAdmin`. Each carries a `full_name`, a `discipline` — one of `SN` (skilled nurse), `PT` (physical therapy), `OT` (occupational therapy), `SLP` (speech-language pathology), or `HHA` (home health aide) — and a `license_expiration_date` as a YYYY-MM-DD string. A `status` field on the clinician is system-managed but admin-mutable: it is either `AVAILABLE` (the clinician is on the dispatch board and may be scheduled) or `SUSPENDED` (visible in listings, but excluded from new scheduling).

Two clinician fields drive visit-scheduling gates downstream: the discipline must equal the `visit_type` requested on the visit, and the license must be still valid on the visit's date. Both gates surface in §3.5. Admins can amend the `license_expiration_date` or move a clinician between `AVAILABLE` and `SUSPENDED` after creation. The clinician listing endpoint supports filtering by `discipline` and by `status`, plus the standard pagination controls.

### 3.3. The OASIS Assessment Lifecycle

The starting point for every episode is an **OASIS Assessment** authored in the patient's home by an `IntakeCoordinator`. The OASIS captures the clinical inputs PDGM needs: `assessment_reason` (one of `START_OF_CARE`, `RECERTIFICATION`, or `RESUMPTION_OF_CARE`), `assessment_date` as a YYYY-MM-DD ISO date, `clinical_grouping` (one of `MMTA_OTHER`, `NEURO`, `WOUND`, `MS_REHAB`, `BEHAVIORAL`, or `COMPLEX`), `functional_impairment_level` (`LOW`, `MEDIUM`, or `HIGH`), `admission_source` (`COMMUNITY` or `INSTITUTIONAL`), and `hha_companion_hours_ordered` — the cap on aide companion-care hours that may be consumed during the resulting episode. If the coordinator does not supply `hha_companion_hours_ordered`, it defaults to 0, which is a hard ceiling that blocks any HHA visit from being scheduled later. The assessment is parented to a `patient_id` derived from the URL path.

A new OASIS starts in `DRAFT`. Locking it — promoting it to `LOCKED` — is the prerequisite for opening an episode, and only an `IntakeCoordinator` may lock. Lock requires that `assessment_reason`, `clinical_grouping`, `functional_impairment_level`, and `admission_source` all be populated; an attempt to lock an OASIS that is not in `DRAFT` is rejected with `ERR_OASIS_NOT_DRAFT`.

Lock further imposes assessment-reason-specific gates that depend on the patient's prior episodes and the logical clock:

- A `RECERTIFICATION` lock requires that the patient have a prior episode whose `recert_due_date` is on or before `current_date` **and** whose `end_date` is on or after `current_date` — i.e., the clock is inside the inclusive recertification window `[prior_episode.recert_due_date, prior_episode.end_date]`. A lock attempted outside that window is rejected with `ERR_RECERT_WINDOW_VIOLATION`.
- A `RESUMPTION_OF_CARE` lock requires that the patient already have an `OPEN` episode.
- A `START_OF_CARE` lock has neither of those preconditions.

Locking carries a side effect: any other OASIS on the same patient still in `DRAFT` is moved to `SUPERSEDED` in the same atomic step, refreshing each superseded row's `updated_at` and incrementing its `version`. Once a `LOCKED` OASIS has been used to open an episode and that episode subsequently reaches `CLOSED` or `EXPIRED`, when a fresh `RECERTIFICATION` OASIS is later locked on the same patient the system also moves the prior `LOCKED` OASIS to `SUPERSEDED` automatically — closing the loop on the order source for the now-completed chain. A `LOCKED` OASIS may open exactly one episode; a `SUPERSEDED` OASIS may not open any episode.

### 3.4. Opening, Closing, and Expiring an Episode

An episode is the 60-day Medicare period in which the agency delivers and bills home-health services. Opening one is an `IntakeCoordinator` action, performed by referencing a `source_oasis_id` for an OASIS that is currently `LOCKED`. Opening fails with `ERR_OASIS_NOT_LOCKED` if the referenced OASIS is not in `LOCKED` status. The patient must have no other episode whose `status` is `OPEN`; a violation is rejected with `ERR_PATIENT_HAS_OPEN_EPISODE`. The OASIS must not already have been used to open a prior episode; a violation is rejected with `ERR_OASIS_ALREADY_USED`. The `patient_id` on the new episode is taken from the path.

When the episode is created, the server derives four fields from the source OASIS atomically with the insert:

- `episode_type` is derived from `assessment_reason`: a `START_OF_CARE` OASIS produces `INITIAL`; a `RECERTIFICATION` OASIS produces `RECERT`; a `RESUMPTION_OF_CARE` OASIS produces `ROC`.
- `start_date` equals the source OASIS's `assessment_date` when `episode_type` is `INITIAL` or `ROC`; for a `RECERT` episode, `start_date` equals the prior episode's `end_date` plus one calendar day.
- `end_date` equals `start_date` plus 59 days — i.e., the inclusive 60-day window from `start_date` through `start_date + 59 days`.
- `timing_category` is `EARLY` for an `INITIAL` episode. For a `RECERT` or `ROC` episode, the timing is `LATE` whenever the chain of prior episodes for the patient contains at least one `EARLY` episode. In practice this means the first episode in a patient's chain is `EARLY` and every subsequent episode in the chain is `LATE`.
- `recert_due_date` is `end_date` minus four days — the earliest date on which a `RECERTIFICATION` OASIS may be locked to continue care into a follow-on episode.

The system also creates a paired `PDGMClaim` in `PENDING` status as a side effect of episode opening, and computes the claim's `hipps_code`, `case_mix_weight`, and `provisional_payment` in the same transaction. See §3.7 for the payment formulas.

Closing an episode is reserved for `BillingSpecialist` and represents the billing-side acknowledgement that all clinical work is done and the claim can be finalized. Closing requires the logical clock to have reached or passed the episode's `end_date` (`current_date >= end_date`) and requires that the episode have zero visits still in `SCHEDULED`. If a `SCHEDULED` visit remains, the close is blocked — the billing team must wait for it to either be completed or cancelled. The same close attempt against an episode not in `OPEN` is rejected with `ERR_EPISODE_NOT_OPEN`. A successful close re-runs the final-payment formula, the LUPA check, and the mileage aggregation on the paired claim — writing `final_payment`, `lupa_applied`, and `total_mileage_reimbursement` — and the paired `PDGMClaim` transitions from `PENDING` to `FINALIZED` atomically with the episode's transition from `OPEN` to `CLOSED`. Both the episode and the claim have their `updated_at` refreshed and `version` incremented.

For abandoned episodes — those that have aged out without a billing close — the system provides a hands-off cleanup: an admin-driven sweep that scans `OPEN` episodes and, for each one whose `end_date` is more than seven days behind `current_date` (i.e., `current_date > end_date + 7`), transitions the episode to `EXPIRED`. The expire-sweep cascade is three layers deep on a single episode:

1. The episode itself moves from `OPEN` to `EXPIRED`.
2. Every `Visit` on that episode whose status is `SCHEDULED` is cancelled in the same step, moving to `CANCELLED`.
3. The paired `PDGMClaim` is finalized: `final_payment` is set equal to `provisional_payment`, `lupa_applied` is set to `false`, `total_mileage_reimbursement` is recomputed from whatever visits have already reached `COMPLETED` on this episode, and the claim transitions from `PENDING` to `FINALIZED`.

Each entity touched by the cascade has its `updated_at` refreshed and `version` incremented. The episode listing endpoint accepts a `patient_id` filter and a `status` filter alongside the usual `limit` and `offset` pagination parameters.

### 3.5. Scheduling, Completing, and Cancelling Visits

A `Visit` is the unit of clinical work performed in a patient's home; visits are scheduled by an `IntakeCoordinator` against an `OPEN` episode and parent themselves to it through `episode_id` (derived from the URL path). The schedule request carries a `clinician_id` identifying the assigned clinician, a `visit_type` (`SN`, `PT`, `OT`, `SLP`, or `HHA`), a `visit_date` as a YYYY-MM-DD ISO date, and a `[start_minute, end_minute)` half-open time window in which `start_minute` and `end_minute` are minute-of-day integers from 0 through 1439 inclusive. A newly scheduled visit lands in `SCHEDULED` status.

Scheduling is governed by a cascade of preconditions enforced in the priority order described in §2.9:

- The target episode must be `OPEN`; mutations against a non-`OPEN` episode are rejected with `ERR_EPISODE_NOT_OPEN`.
- The clinician's license must still be valid on the visit date — `license_expiration_date` strictly greater than `visit_date`. A license whose expiration date is on or before the visit date is rejected with `ERR_CLINICIAN_LICENSE_EXPIRED`. (Strict inequality: a visit on the expiration date itself is blocked.)
- The clinician must be `AVAILABLE`; a `SUSPENDED` clinician is rejected with `ERR_CLINICIAN_NOT_AVAILABLE`.
- The clinician's `discipline` must equal the requested `visit_type`; a mismatch is rejected with `ERR_DISCIPLINE_MISMATCH`.
- The `visit_date` must be inclusively within the episode's window — at least the `start_date` and at most the `end_date`. A date outside the window is rejected with `ERR_VISIT_OUTSIDE_EPISODE`.
- The visit time window must be well-formed: `end_minute` strictly greater than `start_minute`, with both values in the inclusive range 0 through 1439. A malformed window is rejected with `ERR_VISIT_TIME_INVALID`.
- The clinician must not already be booked into an overlapping window. The system compares the requested `[start_minute, end_minute)` against every other non-`CANCELLED` visit on the same clinician on the same `visit_date`; if any other booking overlaps, the request is rejected with `ERR_CLINICIAN_DOUBLE_BOOKED`. The intervals are half-open, so two visits that touch exactly at the same minute (e.g., one ending at minute 600 and another starting at minute 600) are permitted.

For HHA visits a final fiscal check runs: the cumulative `hha_companion_hours_consumed` already on the episode, plus the proposed visit's `hha_hours`, must not exceed the episode's source OASIS `hha_companion_hours_ordered`. A breach is rejected with `ERR_HHA_HOURS_EXCEEDED`. The cumulative figure is the sum of `hha_hours` across visits on the episode whose `visit_type` is `HHA` and whose `status` is either `SCHEDULED` or `COMPLETED` — `SCHEDULED` aide hours count against the cap even before the visit happens, and `CANCELLED` aide visits do not (cancelling an aide visit frees its hours back up). For any individual visit, `hha_hours` is computed from the time window only when `visit_type` is `HHA`: `(end_minute - start_minute) / 60`, rounded half-up to two decimals; for any non-HHA `visit_type`, `hha_hours` is recorded as 0. Aggregated cumulative consumption is the sum of those per-visit rounded values (round-then-sum).

A `FieldClinician` completes a visit they own. The completion action requires that `X-User-ID` equal the visit's `clinician_id`, that `current_date` be on or after `visit_date`, and that the visit be in `SCHEDULED` status; a non-`SCHEDULED` visit is rejected with `ERR_VISIT_NOT_SCHEDULED`. A successful completion moves the visit from `SCHEDULED` to `COMPLETED`. An `IntakeCoordinator` may cancel a visit that is still in `SCHEDULED`; cancellation has no further preconditions beyond the state check and moves the visit from `SCHEDULED` to `CANCELLED`. A cancel attempt on a visit not in `SCHEDULED` is also rejected with `ERR_VISIT_NOT_SCHEDULED`.

The visit-listing endpoint scoped to an episode accepts an optional `status` filter, an optional `clinician_id` filter, and the standard pagination controls.

### 3.6. Mileage Capture

Mileage is recorded by a `FieldClinician` against a visit they have already completed. The mileage payload carries a single field `miles_driven` representing the round-trip miles for that visit; it must be strictly greater than zero, and a value of zero or negative is rejected with `ERR_MILEAGE_NOT_POSITIVE`. The parent visit must be in `COMPLETED` status; a mileage record attempted against a `SCHEDULED` or `CANCELLED` visit is rejected with `ERR_MILEAGE_VISIT_NOT_COMPLETED`. A successful insert creates an immutable `MileageLog` row whose `visit_id` is taken from the path and whose `episode_id` is the visit's parent episode, denormalized onto the row for billing aggregation.

The reimbursement amount is computed at insertion time by a three-tier formula applied to `miles_driven`. The first tier covers the first 30 miles; specifically, take whichever is smaller — `miles_driven` or 30 — and multiply by 0.70 USD per mile. The second tier covers miles in the range above 30 up to and including 100; specifically, subtract 30 from `miles_driven` (floored at zero), then take whichever is smaller of that subtraction and 70, and multiply by 0.55 USD per mile. The third tier covers every mile beyond 100; specifically, subtract 100 from `miles_driven` (floored at zero) and multiply by 0.40 USD per mile. Sum the three tier amounts and round the sum half-up to two decimals — that value is the `reimbursement_amount` stored on the `MileageLog`. Tier 1 is inclusive of mile 30; tier 2 covers the interval from mile 30 (exclusive) through mile 100 (inclusive); tier 3 covers everything strictly above mile 100.

Mileage rows are immutable. There is no update, no cancel, no version field. They live only to be aggregated into the claim's `total_mileage_reimbursement` (see §3.7 and §2.6).

### 3.7. PDGM Claim Computation: Provisional vs. Final

Every episode has exactly one paired `PDGMClaim`, created in `PENDING` at episode open and finalized when the episode reaches `CLOSED` or `EXPIRED`. The claim records the `hipps_code` (a five-character classification), the looked-up `case_mix_weight`, both payment values (`provisional_payment` and `final_payment`), the `lupa_applied` flag, the `total_mileage_reimbursement` aggregate, and a `status` of either `PENDING` or `FINALIZED`. The `episode_id` is taken from the parent episode and is unique across claims — there is exactly one claim per episode.

The `hipps_code` is composed positionally from the OASIS and timing inputs. Position 1 encodes the episode's `timing_category`: `1` for `EARLY` and `2` for `LATE`. Position 2 encodes the OASIS `clinical_grouping` as a single letter: `A` for `MMTA_OTHER`, `B` for `NEURO`, `C` for `WOUND`, `D` for `MS_REHAB`, `E` for `BEHAVIORAL`, and `F` for `COMPLEX`. Position 3 encodes the OASIS `functional_impairment_level`: `F` for `LOW`, `G` for `MEDIUM`, and `H` for `HIGH`. Position 4 encodes the OASIS `admission_source`: `J` for `COMMUNITY` and `K` for `INSTITUTIONAL`. Position 5 is the literal character `1`.

The `case_mix_weight` is the value found in the agency's case-mix weight table for the four-tuple `(timing_category, clinical_grouping, functional_impairment_level, admission_source)`. The table is fixed:

| Timing | Clinical Grouping | Functional | Admission | Weight |
| ------ | ----------------- | ---------- | --------- | ------ |
| EARLY  | MMTA_OTHER        | LOW        | COMMUNITY | 0.9000 |
| EARLY  | MMTA_OTHER        | MEDIUM     | COMMUNITY | 1.0000 |
| EARLY  | MMTA_OTHER        | HIGH       | COMMUNITY | 1.1500 |
| EARLY  | MMTA_OTHER        | LOW        | INSTITUTIONAL | 1.0500 |
| EARLY  | MMTA_OTHER        | MEDIUM     | INSTITUTIONAL | 1.1500 |
| EARLY  | MMTA_OTHER        | HIGH       | INSTITUTIONAL | 1.3000 |
| EARLY  | NEURO             | LOW        | COMMUNITY | 1.0000 |
| EARLY  | NEURO             | MEDIUM     | COMMUNITY | 1.1500 |
| EARLY  | NEURO             | HIGH       | COMMUNITY | 1.3500 |
| EARLY  | NEURO             | LOW        | INSTITUTIONAL | 1.2000 |
| EARLY  | NEURO             | MEDIUM     | INSTITUTIONAL | 1.3500 |
| EARLY  | NEURO             | HIGH       | INSTITUTIONAL | 1.5000 |
| EARLY  | WOUND             | MEDIUM     | COMMUNITY | 1.2000 |
| EARLY  | WOUND             | HIGH       | COMMUNITY | 1.4000 |
| EARLY  | MS_REHAB          | MEDIUM     | COMMUNITY | 1.1000 |
| EARLY  | BEHAVIORAL        | MEDIUM     | COMMUNITY | 0.9500 |
| EARLY  | COMPLEX           | HIGH       | INSTITUTIONAL | 1.6000 |
| LATE   | MMTA_OTHER        | LOW        | COMMUNITY | 0.8000 |
| LATE   | MMTA_OTHER        | MEDIUM     | COMMUNITY | 0.9000 |
| LATE   | MMTA_OTHER        | HIGH       | COMMUNITY | 1.0500 |
| LATE   | NEURO             | MEDIUM     | COMMUNITY | 1.0500 |
| LATE   | NEURO             | HIGH       | COMMUNITY | 1.2500 |
| LATE   | WOUND             | HIGH       | COMMUNITY | 1.3000 |

The base 30-day rate is 2,000.00 USD; the LUPA visit-count threshold is 5 (strictly: a completed-visit count of fewer than 5 triggers LUPA). The per-visit LUPA rates by discipline are: 160.00 USD for `SN`, 170.00 USD for `PT`, 165.00 USD for `OT`, 175.00 USD for `SLP`, and 80.00 USD for `HHA`.

**The provisional payment** is a forward-looking estimate computed at episode open. It assumes the agency will perform enough visits to clear the LUPA threshold, so no LUPA branch is considered. Take the base rate of 2,000.00 USD and multiply it by the patient's `wage_index` read off the patient row at the moment of episode open; round that wage-adjusted base half-up to four decimals. Multiply the rounded wage-adjusted base by the looked-up `case_mix_weight`; round the product half-up to two decimals. The result is `provisional_payment`. No visit data is read in this computation — only the source OASIS fields, the episode's `timing_category`, and the patient's `wage_index`.

**The final payment** is computed when the episode transitions from `OPEN` to `CLOSED`, and uses the actual chronological set of `COMPLETED` visits on the episode. Visits in `SCHEDULED` status block the close (see §3.4), and visits in `CANCELLED` status are excluded from the computation. Begin by counting the number of `COMPLETED` visits on the episode.

- If the count is strictly less than the LUPA threshold of 5, the claim is paid per visit instead of by case mix. Sort the `COMPLETED` visits in chronological order — ascending by `visit_date`, then by `start_minute`, then by `id` as the final tie-breaker — and walk them in that order. For each visit, take the per-visit LUPA rate for the visit's `visit_type`, multiply by the patient's `wage_index` read at the moment of close, and round half-up to two decimals — that is the visit's per-visit payment. Sum the already-rounded per-visit payments to produce `final_payment` (round-then-sum is required), and set `lupa_applied` to `true`.
- If the count is at least 5, the claim is paid by case mix. Apply the same two-step formula used for the provisional: multiply 2,000.00 USD by the patient's `wage_index` (read at the moment of close), round half-up to four decimals, multiply by the looked-up `case_mix_weight`, and round half-up to two decimals. The result is `final_payment`, and `lupa_applied` is set to `false`. In this branch, when no inputs have changed between open and close, `final_payment` equals `provisional_payment`; when `home_zip` changed (and thus `wage_index` did), the two values legitimately diverge.

In parallel with the payment computation, the system recomputes `total_mileage_reimbursement` as the sum of the `reimbursement_amount` values on `MileageLog` rows linked to `COMPLETED` visits on this episode — the round-then-sum aggregation from §2.6. Mileage rows on `CANCELLED` or `SCHEDULED` visits are excluded.

When the close is instead triggered indirectly by the expire-sweep — i.e., the episode transitions from `OPEN` to `EXPIRED` rather than `CLOSED` — the final payment is **not** recomputed from visits. Instead, `final_payment` is set equal to `provisional_payment`, `lupa_applied` is set to `false`, and `total_mileage_reimbursement` is recomputed only from already-`COMPLETED` visits' mileage rows (any mileage that would have been recorded against visits that the sweep cancelled is, by definition, absent — mileage cannot be recorded against `CANCELLED` visits in the first place). The paired claim then transitions from `PENDING` to `FINALIZED`, mirroring the `CLOSED` path's terminal claim state.

## 4. Endpoint Definitions

Operations that create a brand-new resource — a patient, a clinician, an OASIS draft, an episode, a visit, or a mileage row — return `201 Created`. Operations that mutate an existing resource — lock an OASIS, close an episode, complete or cancel a visit, advance the clock, run the sweep, or PATCH a patient or clinician — return `200 OK`. Read operations also return `200 OK`. All endpoints are mounted under the API host directly (no global prefix).

| Method | Path                                                | Description                                                                        | Authorized Role(s)                                                       |
| ------ | --------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| POST   | `/patients`                                         | Create a patient                                                                   | IntakeCoordinator, PlatformAdmin                                         |
| GET    | `/patients/{patientId}`                             | Get a patient                                                                      | IntakeCoordinator, FieldClinician, BillingSpecialist, PlatformAdmin      |
| GET    | `/patients`                                         | List patients with pagination                                                      | IntakeCoordinator, BillingSpecialist, PlatformAdmin                      |
| PATCH  | `/patients/{patientId}`                             | Update mutable patient fields                                                      | IntakeCoordinator, PlatformAdmin                                         |
| POST   | `/clinicians`                                       | Create a clinician                                                                 | PlatformAdmin                                                            |
| GET    | `/clinicians/{clinicianId}`                         | Get a clinician                                                                    | PlatformAdmin, IntakeCoordinator, FieldClinician                         |
| PATCH  | `/clinicians/{clinicianId}`                         | Update mutable clinician fields                                                    | PlatformAdmin                                                            |
| GET    | `/clinicians`                                       | List clinicians                                                                    | IntakeCoordinator, PlatformAdmin                                         |
| POST   | `/patients/{patientId}/oasis`                       | Create a DRAFT OASIS assessment                                                    | IntakeCoordinator                                                        |
| POST   | `/patients/{patientId}/oasis/{oasisId}/lock`        | Lock a DRAFT OASIS                                                                 | IntakeCoordinator                                                        |
| GET    | `/patients/{patientId}/oasis/{oasisId}`             | Get an OASIS                                                                       | IntakeCoordinator, BillingSpecialist                                     |
| POST   | `/patients/{patientId}/episodes`                    | Open a 60-day episode from a LOCKED OASIS                                          | IntakeCoordinator                                                        |
| GET    | `/episodes/{episodeId}`                             | Get an episode                                                                     | IntakeCoordinator, FieldClinician, BillingSpecialist, PlatformAdmin      |
| GET    | `/episodes`                                         | List episodes with filters                                                         | BillingSpecialist, IntakeCoordinator, PlatformAdmin                      |
| POST   | `/episodes/{episodeId}/close`                       | Close an episode; finalizes PDGMClaim                                              | BillingSpecialist                                                        |
| POST   | `/episodes/{episodeId}/visits`                      | Schedule a visit                                                                   | IntakeCoordinator                                                        |
| GET    | `/episodes/{episodeId}/visits`                      | List visits on an episode                                                          | IntakeCoordinator, FieldClinician, BillingSpecialist                     |
| GET    | `/visits/{visitId}`                                 | Get a visit                                                                        | IntakeCoordinator, FieldClinician, BillingSpecialist                     |
| POST   | `/visits/{visitId}/complete`                        | Mark a visit complete                                                              | FieldClinician                                                           |
| POST   | `/visits/{visitId}/cancel`                          | Cancel a scheduled visit                                                           | IntakeCoordinator                                                        |
| POST   | `/visits/{visitId}/mileage`                         | Record mileage for a completed visit                                               | FieldClinician                                                           |
| GET    | `/visits/{visitId}/mileage`                         | List mileage entries for a visit                                                   | FieldClinician, BillingSpecialist                                        |
| GET    | `/episodes/{episodeId}/claim`                       | Get the PDGMClaim for an episode                                                   | BillingSpecialist, IntakeCoordinator                                     |
| POST   | `/_clock/advance`                                   | Advance ClockState.current_date to a target ISO date (>= current)                  | PlatformAdmin                                                            |
| GET    | `/_clock`                                           | Read current ClockState                                                            | PlatformAdmin, IntakeCoordinator, BillingSpecialist, FieldClinician      |
| POST   | `/_sweep/expire-episodes`                           | Run the sweep that expires abandoned episodes (Episode end_date + 7 < current_date) | PlatformAdmin                                                            |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_AUTH_MISSING`                | 401 Unauthorized |
| `ERR_FORBIDDEN`                   | 403 Forbidden    |
| `ERR_NOT_FOUND`                   | 404 Not Found    |
| `ERR_OASIS_NOT_DRAFT`             | 409 Conflict     |
| `ERR_OASIS_NOT_LOCKED`            | 409 Conflict     |
| `ERR_EPISODE_NOT_OPEN`            | 409 Conflict     |
| `ERR_VISIT_NOT_SCHEDULED`         | 409 Conflict     |
| `ERR_MILEAGE_VISIT_NOT_COMPLETED` | 409 Conflict     |
| `ERR_CLINICIAN_LICENSE_EXPIRED`   | 422 Unprocessable Entity |
| `ERR_CLINICIAN_NOT_AVAILABLE`     | 422 Unprocessable Entity |
| `ERR_DISCIPLINE_MISMATCH`         | 422 Unprocessable Entity |
| `ERR_RECERT_WINDOW_VIOLATION`     | 422 Unprocessable Entity |
| `ERR_VISIT_OUTSIDE_EPISODE`       | 422 Unprocessable Entity |
| `ERR_VISIT_TIME_INVALID`          | 422 Unprocessable Entity |
| `ERR_CLINICIAN_DOUBLE_BOOKED`     | 409 Conflict     |
| `ERR_OASIS_ALREADY_USED`          | 409 Conflict     |
| `ERR_PATIENT_HAS_OPEN_EPISODE`    | 409 Conflict     |
| `ERR_HHA_HOURS_EXCEEDED`          | 422 Unprocessable Entity |
| `ERR_MILEAGE_NOT_POSITIVE`        | 422 Unprocessable Entity |
| `ERR_VERSION_CONFLICT`            | 409 Conflict     |
| `ERR_CLOCK_BACKWARDS`             | 422 Unprocessable Entity |
