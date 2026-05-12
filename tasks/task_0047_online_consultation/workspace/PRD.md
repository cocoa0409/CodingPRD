# Online Consultation API — Product Requirements Document

## 1. Introduction

The Online Consultation API is the backbone of a tele-medicine workflow that connects symptomatic patients to licensed practitioners in real time. The system orchestrates a long, branching journey: a patient first answers a symptom-checker questionnaire which is scored into a severity band; non-emergency cases are matched to an appropriate department and ranked doctor; the resulting session is conducted either as a queued real-time conversation or as a pre-booked appointment, and may be text-image or video; a doctor may then draft an electronic prescription that is independently reviewed by a pharmacist and routed to a designated pharmacy or e-commerce vendor; an insurance claim is settled in real time against the public-insurance bureau; and a follow-up plan reminds the patient days or weeks later, with auto-escalation when the patient reports abnormal findings.

Because the workflow crosses four largely independent regulatory and operational boundaries — triage, clinical practice, pharmacy, and insurance — the API is designed around explicit state machines per aggregate, segregation of duties between drafting doctors and reviewing pharmacists, and event-driven settlement with downstream platforms. Auditability is a first-class concern: every clinically or financially material action appends an immutable audit-log row that can be queried for post-hoc review.

This document is the canonical specification of the API contract. All payload shapes, state transitions, validation orderings, computation formulas, and concurrency guarantees described below are normative — the test suite asserts against them precisely.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role being asserted. If either header is absent the request is rejected with `ERR_AUTH_MISSING`; if the asserted role lacks permission for the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognises exactly four roles, spelled as follows: `Patient`, `Doctor`, `Pharmacist`, and `PlatformAdmin`.

When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's `patient_id` field to `X-User-ID`. When `X-User-Role` is `Doctor`, `X-User-ID` is the `id` of the acting `Doctor`; ownership checks on a `Consultation` compare its `doctor_id` to `X-User-ID`, and ownership of a `Prescription` is via `drafting_doctor_id`. When `X-User-Role` is `Pharmacist`, `X-User-ID` is the `id` of the acting `Pharmacist`; the server records it on `Prescription.reviewing_pharmacist_id` when the pharmacist approves or rejects, and uses it for the segregation-of-duties check against `drafting_doctor_id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_user_id` on an `AuditLog` row written by a transition the admin drives) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` controls the maximum number of items returned; if not supplied, it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls the number of items to skip; if not supplied, it defaults to 0 and must be at least 0. When the caller supplies values outside these bounds, the request is rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, list results are sorted by `created_at` in ascending order. The `meta` block on a list response always carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources except `DepartmentMapping` and `AuditLog` expose the same four system-managed fields. The `id` field is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once at creation and never altered thereafter. The `updated_at` field follows the same format and is refreshed on every mutation. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation.

The two exceptions — entities created with no audit-trail of mutations — are `DepartmentMapping` and `AuditLog`. Both carry `id` and `created_at`, but neither carries `updated_at` nor `version`. `DepartmentMapping` rows are treated as configuration that is replaced rather than amended; `AuditLog` rows are append-only by design.

### 2.5. Nested Resource Validation

When an endpoint path contains identifiers (for example, `/consultation/consultations/{id}/accept`), each identifier is validated in left-to-right order, and the first one that does not resolve yields a 404 `ERR_NOT_FOUND`. When a request body references another resource by id — for instance, `consultation_id`, `triage_session_id`, `doctor_id`, `patient_id`, `prescription_id`, or `dispatch_target_id` — and that body reference fails to resolve, the response is `ERR_REF_NOT_FOUND` with HTTP 422 (distinct from the 404 used for path identifiers).

### 2.6. Validation Priority

Multiple validations may apply to the same request. The server evaluates them in a fixed order so that earlier failures shadow later ones: header presence first (`ERR_AUTH_MISSING`), then role-permission (`ERR_FORBIDDEN`), then path-existence (`ERR_NOT_FOUND`), then body foreign-key existence (`ERR_REF_NOT_FOUND`), then state-machine from-state (`ERR_INVALID_STATE`), and only after all of those have passed are domain-specific business rules evaluated. Within the business-rule band, more specific safety/regulatory checks are evaluated before fiscal validity, OCC, and finally pagination shape. Concretely: an emergency-routed triage block surfaces as `ERR_TRIAGE_EMERGENCY_ROUTED` before the system looks for an eligible doctor; a pharmacist-equals-drafter check surfaces as `ERR_SEGREGATION_OF_DUTIES` before a stale `version` could yield `ERR_VERSION_CONFLICT`; pagination shape is checked last.

### 2.7. State-Cascade and Mutation Bookkeeping

Most state transitions mutate more than one entity. Whenever a resource's persisted state changes — including its derived columns such as `queue_position`, `total_fee`, `severity_band`, `eligibility_flag`, `dispensing_status`, `reimbursed_cents`, or `self_pay_cents` — its `updated_at` is refreshed and its `version` is incremented by one. Cascading updates triggered by a single client call (for example, recomputing `queue_position` for sibling consultations of the same doctor) are likewise mutations on those siblings and bump each sibling's `version`.

The system never silently re-routes work. When a doctor `transfer`s an in-progress consultation, both the outgoing row and the newly created sibling for the receiving doctor independently bump their `version`, and the outgoing row records the receiving doctor in `transfer_to_doctor_id`. When a follow-up auto-escalates because abnormal findings were declared, the new follow-up `Consultation` is created in a fresh state and the original `FollowUpTask` records the new consultation's id in `escalation_consultation_id`.

### 2.8. Monetary Precision and Rounding

Most monetary values on the wire are integer cents, including `gross_amount_cents`, `claim_amount_cents`, `deductible_cents`, `reimbursed_cents`, `self_pay_cents`, and `self_pay_collected_cents`. The single exception is `Consultation.total_fee` and the per-doctor `base_fee`, which are decimal yuan: they are exposed to two decimal places, rounded half-up. The rounding moment matters and differs per calculation — see §3 for the order in which rounding interacts with each tier sum.

### 2.9. Optimistic Concurrency Control

All transition and mutation endpoints accept an optional `version` field in the request body. When present, it must equal the server's current `version` for the target resource; if it does not, the server rejects the request with `ERR_VERSION_CONFLICT` and does not perform the mutation. When omitted, the server applies the mutation without an OCC check. This applies to all PATCH endpoints and to every state-transition endpoint on `TriageSession`, `Consultation`, `Prescription`, `InsuranceClaim`, and `FollowUpTask`.

### 2.10. Concurrency and Event Idempotency

Several races deserve explicit treatment because the loser's specific `error_id` matters.

Two patients (or, more precisely, two doctor terminals) attempting to `accept` the same `QUEUED` consultation for a freshly freed slot serialise so that exactly one succeeds; the loser receives `ERR_DOCTOR_AT_CAPACITY` with HTTP 409, evaluated against the doctor's serialised count of `QUEUED + ACCEPTED + IN_PROGRESS` consultations.

A doctor's `complete` and a patient's cancel-by-DELETE on the same `Consultation` likewise serialise on the row's `session_status`; the loser sees `ERR_INVALID_STATE` with HTTP 409.

A pharmacist who attempts to `approve` a `REJECTED` `Prescription` while the drafting doctor simultaneously calls `revise` will lose: the revise transition wins, and the pharmacist's call returns `ERR_INVALID_STATE` (one cannot approve a prescription that is no longer `UNDER_REVIEW`).

Two `BUREAU_SETTLED` events for the same `InsuranceClaim` arriving in quick succession are deduplicated by the idempotency key `(claim_id, event.kind, bureau_ref)`; the first event mutates the claim, and the second returns `ERR_DUPLICATE_BUREAU_EVENT` with HTTP 409 without mutating `self_pay_cents` or `reimbursed_cents`.

Two appointment `Consultation`s created for the same `doctor_id` whose `scheduled_start_at` slot windows overlap — using closed-open `[start, start + SLOT_MINUTES)` interval semantics — are serialised: the second creation is rejected with `ERR_DOCTOR_SLOT_OVERLAP` and HTTP 409.

## 3. Business Logic & Workflows

### 3.1. Onboarding Patients, Doctors, Pharmacists, and Department Routing Tables

The earliest configuration is performed by a `PlatformAdmin` operator. Creating a `Patient` requires the legal `full_name`, a `date_of_birth` formatted as an ISO 8601 calendar date (YYYY-MM-DD), and a `region_code` from the server-known region enumeration. The remaining patient inputs are optional: an `insurance_policy_no` (omitted or null when the patient is uninsured), a `preferred_hospital_id` (used as the highest-ranked tie-break in doctor matching when supplied), a `preferred_doctor_id` (which, when supplied, pins matching to a specific doctor — provided that doctor passes the eligibility filter), and `chronic_condition_codes`, a list of ICD-style codes that defaults to an empty list and is consulted both during triage scoring and during prescription return-visit eligibility. The `insurance_status` is server-computed and starts at `UNKNOWN`; downstream verify-eligibility flips it to `ELIGIBLE`, `INELIGIBLE`, or `SUSPENDED`. A `Patient` may later self-update `preferred_hospital_id`, `preferred_doctor_id`, and `chronic_condition_codes` on their own row.

Registering a `Doctor` is similarly admin-driven. The payload provides the `full_name`, the `hospital_id` the doctor belongs to, the primary `department_code` (which must already exist as a registered `DepartmentMapping`), the list of sub-`specialty_codes`, and the list of `licensed_region_codes` in which the doctor is authorised to serve patients (this is the regional medical-resource gate). Two operational dials are optional at creation: `max_concurrent_sessions`, the hard cap on simultaneously `OPEN` consultation sessions, which defaults to 1, and `rating_score`, a decimal score in the range 0.00–5.00 used as the primary ranking key in doctor matching, which defaults to 0.00. The doctor's `status` defaults to `AVAILABLE` and may later be updated by the doctor themselves to `BUSY`, `OFF_DUTY`, or `SUSPENDED`.

A `Pharmacist` is registered with a `full_name`, a server-unique `license_number`, and an optional `status` that defaults to `ACTIVE` (the only alternative is `SUSPENDED`). Suspended pharmacists may not act on prescriptions.

`DepartmentMapping` rows are registered by admin with a `department_code` identifier (for example, `CARDIO` or `DERM`), an array of `disease_codes` that route to that department, and a `triage_priority` integer in which a lower number wins when several departments cover the same disease.

### 3.2. Symptom Triage and Severity Banding

A `Patient` opens a triage session by submitting the `patient_id` and the initial `questionnaire_responses`, an array of objects each carrying a `question_code`, an `answer_value`, and a `severity_weight`. The new `TriageSession` begins life in `COLLECTING`. After the patient (or the symptom checker, on the patient's behalf) has populated the questionnaire, the patient triggers assessment to advance the session from `COLLECTING` to `ASSESSED`. The assessment is rejected with `ERR_QUESTIONNAIRE_EMPTY` when the questionnaire has fewer than one entry at the moment of assessment.

Assessment computes three component scores and a final severity score. The `chief_complaint_score` is the sum of `severity_weight` across all questionnaire responses, multiplied by a chief-complaint factor of 10. The `vital_anomaly_score` is the count of questionnaire entries whose `question_code` begins with `VITAL_` and whose `answer_value` equals `ABNORMAL`, multiplied by a vital-anomaly factor of 2. The `risk_factor_score` is computed from the patient's `chronic_condition_codes`: for each code, if that code appears in the system's risk table (where `DIABETES` contributes 1, `HYPERTENSION` contributes 1, and `IMMUNOCOMPROMISED` contributes 2; codes outside the table contribute nothing), the corresponding entry is summed, and the resulting sum is multiplied by a risk factor of 3. The final `severity_score` is the sum of `chief_complaint_score`, `vital_anomaly_score`, and `risk_factor_score`. All arithmetic is integer; no rounding is required.

The `severity_band` is then derived from `severity_score` against four contiguous half-open ranges: `LOW` when the score is strictly below 30, `MID` when the score is at least 30 and strictly below 60, `HIGH` when the score is at least 60 and strictly below 90, and `EMERGENCY` when the score is at least 90.

When the band is anything other than `EMERGENCY`, assessment additionally runs the department selector to populate `recommended_department_code`. When the band is `EMERGENCY`, the assessment transition fires a secondary automatic transition from `ASSESSED` to `EMERGENCY_ROUTED`: the system mints an opaque `emergency_routing_ticket`, emits an offline-emergency-dispatch event to the event-driven sync layer, leaves `recommended_department_code` null, and subsequently rejects any attempt to create a `Consultation` against this triage session with `ERR_TRIAGE_EMERGENCY_ROUTED`. The chief-complaint snapshot, vital-anomaly snapshot, and risk-factor snapshot are also persisted as `chief_complaint_score`, `vital_anomaly_score`, and `risk_factor_score` for later inspection.

The first call to assess on a `COLLECTING` session uses the forward-looking initial variant: all currently attached responses are included and the raw weights are used. A chronological-replay variant is reserved for future re-assessment after a reopen but is not exposed in v1 — v1 is locked to the forward-looking initial variant.

A patient may also walk away from an assessed but non-emergency triage by closing it, advancing `status` from `ASSESSED` to the terminal `CLOSED`.

### 3.3. Department Routing and Doctor Matching

When the patient proceeds beyond triage by creating a `Consultation`, the body carries the `triage_session_id`, the desired `mode` (`REAL_TIME` for queue-based or `APPOINTMENT` for slot-based), a `media_type` (`TEXT_IMAGE` or `VIDEO`), and — for `APPOINTMENT` mode — a `scheduled_start_at` timestamp. The body may also carry an explicit `doctor_id`; when present it represents the patient's preferred-doctor intent.

The selector decides which `Doctor` to bind. The candidate set is built from doctors whose `department_code` equals the triage session's `recommended_department_code`, whose `licensed_region_codes` contains the patient's `region_code`, whose `status` is `AVAILABLE`, and whose `specialty_codes` intersect the disease codes the relevant `DepartmentMapping` row associates with the chosen department in at least one element. The eligibility filter is exactly that predicate; no broader "active doctors" rule applies.

If the patient's `preferred_hospital_id` is set, the candidate set is further restricted to doctors with that `hospital_id`. If the resulting candidate set is empty, the request is rejected with `ERR_NO_DOCTOR_AVAILABLE`.

Otherwise, the surviving candidates are ranked by two keys: primarily by `rating_score` descending, and secondarily by the doctor's current live load — the count of `Consultation` rows for that doctor whose `session_status` is in `QUEUED`, `ACCEPTED`, or `IN_PROGRESS` — ascending. When both keys tie, the tie is broken by ascending lexicographic order of the doctor's `id` (UUID string order). The first ranked doctor wins. Load counts are read at the instant of consultation creation (or at the instant of triage assessment when the selector is being run to fill `recommended_department_code`).

The preferred-doctor variant overrides the selector but does not override the eligibility filter. When the patient supplies a `preferred_doctor_id` (either on the patient profile or in the create-consultation payload), the system skips the selector and instead verifies that the named doctor satisfies the eligibility filter described above. If the named doctor fails the filter, the request is rejected with `ERR_PREFERRED_DOCTOR_INELIGIBLE` — the system does not silently fall back to the selector. When the patient has no preferred doctor pinned, the full eligibility-plus-ranking pipeline runs.

Creating the consultation advances the parent triage from `ASSESSED` to `MATCHED` and creates the new row in `PENDING`. The denormalised `patient_id` on the consultation must equal the triage session's `patient_id`.

### 3.4. Real-Time Queueing and Appointment Slots

A consultation's first auto-transition out of `PENDING` depends on `mode`. For `REAL_TIME`, the system advances `session_status` from `PENDING` to `QUEUED` and assigns a `queue_position` equal to one plus the count of consultation rows for the same `doctor_id` whose `session_status` is in `QUEUED`, `ACCEPTED`, or `IN_PROGRESS`. The doctor's `max_concurrent_sessions` cap is enforced here: if the count of `QUEUED + ACCEPTED + IN_PROGRESS` sessions for that doctor would exceed `max_concurrent_sessions`, the creation is rejected with `ERR_DOCTOR_AT_CAPACITY`.

For `APPOINTMENT`, the system advances `session_status` from `PENDING` directly to `ACCEPTED` (no queue) and `queue_position` remains null. Two temporal checks gate appointment creation. First, `scheduled_start_at` must not overlap any other accepted-or-in-progress appointment for the same `doctor_id`, where each existing appointment occupies the closed-open window `[scheduled_start_at, scheduled_start_at + SLOT_MINUTES)`; overlapping with a row in `ACCEPTED` or `IN_PROGRESS` yields `ERR_DOCTOR_SLOT_OVERLAP`. Second, `scheduled_start_at` must fall entirely inside a published `DoctorSchedule` open window for that doctor, evaluated against the closed-closed `[open_at, close_at]` interval (both ends inclusive); a request outside any open window yields `ERR_OUT_OF_SCHEDULE`.

A real-time consultation advances from `QUEUED` to `ACCEPTED` only when the assigned doctor explicitly accepts it. Acceptance is permitted only when the consultation is `QUEUED`, the calling user's `X-User-ID` equals the consultation's `doctor_id`, the doctor's `status` is anything other than `SUSPENDED`, and the doctor's running count of `IN_PROGRESS` sessions is strictly less than their `max_concurrent_sessions`. On acceptance the consultation's `base_fee` is snapshotted from the doctor's profile.

From `ACCEPTED`, the doctor starts the session to advance to `IN_PROGRESS`. For `APPOINTMENT` mode, the server clock must be at or after `scheduled_start_at - GRACE_BEFORE_MINUTES`. Starting sets `started_at` to the current server time; if the `media_type` is `VIDEO`, the parallel `quality_status` is initialised to `OK` (it begins at the inert `NOT_APPLICABLE` for text-image consultations).

A patient may cancel before the session begins, transitioning the consultation into the terminal `CANCELLED` status. Cancellation from `QUEUED` is unconditional and additionally recomputes `queue_position` for siblings of the same doctor. Cancellation from `ACCEPTED` is permitted only when the current server time is strictly before `scheduled_start_at - GRACE_BEFORE_MINUTES`; a later cancel attempt is rejected with `ERR_TOO_LATE_TO_CANCEL`.

### 3.5. The In-Session Experience: Text-Image, Video Quality, and Transfer

During an `IN_PROGRESS` session the doctor leads the conversation. Image uploads are recorded by the patient by attaching ids — the binary blob is handled out of band; the consultation simply collects the `attachment_id` into `image_attachment_ids`. The same `image_attachment_ids` list is exposed as part of the consultation resource.

For `VIDEO` consultations, the parallel `quality_status` dimension records the moving health of the video link. A quality report submission carries a `report_tier` and steps the status along `OK -> DEGRADED -> FAILED`. Once `quality_status` reaches `FAILED`, the doctor may no longer complete the session normally — completion of a video consultation is gated on `quality_status` being anything other than `FAILED`. The doctor's recourse is to transfer to another doctor.

A transfer advances the original consultation from `IN_PROGRESS` to the terminal `TRANSFERRED` and creates a brand-new consultation under the receiving doctor in `ACCEPTED` status with `mode = REAL_TIME` and a null `queue_position`. The body carries the `target_doctor_id`; that doctor must exist, must have `status` other than `SUSPENDED`, must not be the same as the current `doctor_id`, and must not exceed their own `max_concurrent_sessions`. On transfer the outgoing row sets `ended_at` to the current server time, computes `duration_minutes` and `total_fee` per the consultation-fee calculation (the outgoing doctor still bills for the elapsed minutes), sets `transcript_archive_id` to a freshly minted UUID, records the new sibling's doctor id in `transfer_to_doctor_id`, and recomputes `queue_position` for the outgoing doctor's remaining queue.

Normal completion of a session advances `session_status` from `IN_PROGRESS` to the terminal `COMPLETED`. The terminal transition computes `duration_minutes` as the elapsed time from `started_at` to the current server time, expressed in minutes and rounded up to the next whole minute (ceiling) for billing. It computes `total_fee` per the consultation-fee tiered formula below. It mints a fresh UUID into `transcript_archive_id` to record the session-record archive. It recomputes `queue_position` for any later-queued sibling consultations for the same doctor (queue management cascade). It emits a CONSULTATION_COMPLETED event to the event-driven sync layer. And it appends an `AuditLog` row with `action_code` `CONSULTATION_COMPLETED`.

The consultation-fee calculation is tiered on the elapsed minutes and rounded at the very end. The first ten minutes are billed at 100 cents per minute (the first-tier rate); minutes beyond ten are billed at 200 cents per minute (the second-tier rate). Formally, let the elapsed minutes be the ceiling of the elapsed seconds divided by 60. Let the first-tier minutes be the smaller of the elapsed minutes and 10, and let the second-tier minutes be zero or the elapsed minutes minus 10, whichever is greater. The raw total in cents is the snapshotted `base_fee` converted to cents, plus the first-tier minutes multiplied by the first-tier rate, plus the second-tier minutes multiplied by the second-tier rate. The final `total_fee` is that raw cents total divided by 100.0 and rounded half-up to two decimal places. The rounding happens exactly once, on the final sum — not per tier. Both `COMPLETED` and `TRANSFERRED` use the same formula; the only difference is which server moment supplies `ended_at`, and therefore the elapsed minutes.

### 3.6. Prescription Drafting, Pharmacist Review, and Dispatch

After a consultation reaches `COMPLETED`, the attending doctor may draft an electronic prescription. The draft payload carries the parent `consultation_id`, the targeted `disease_codes`, the line-item array `items`, the `dispatch_target_kind` (`PHARMACY` for a designated bricks-and-mortar pharmacy or `ECOMMERCE` for an e-commerce pharmacy), and the `dispatch_target_id` for the chosen vendor. Each entry in `items` carries a `drug_code`, a `quantity`, a `unit_price_cents`, and a `dosage_text`. Every item must have a `quantity` of at least 1 and a `unit_price_cents` of at least 1; otherwise the draft is rejected with `ERR_PRESCRIPTION_AMOUNT_INVALID`. The same constraint applies to subsequent revisions.

Drafting computes `eligibility_flag`. The prescription is eligible when one of two conditions holds: the consultation is a return-visit (informally, the patient has a prior history with this doctor) AND every disease code in `disease_codes` lies inside the system's `PRESCRIPTION_ALLOWED_DISEASES` enumeration; OR the parent consultation has `mode` `APPOINTMENT` with prior history. Otherwise the eligibility flag is `INELIGIBLE`. The flag is computed and stored at drafting time. The new prescription is created in `DRAFT` with `revision_count` zero, with `gross_amount_cents` zero (it is computed at approval), with `dispensing_status` `NONE`, and with `reviewing_pharmacist_id` and `rejection_reason` both null.

The drafting doctor (and only the drafting doctor — `X-User-ID` must equal `drafting_doctor_id`) submits the draft to the pharmacist queue, advancing `status` from `DRAFT` to `UNDER_REVIEW`. Submission requires the prescription's `eligibility_flag` to be `ELIGIBLE`; an ineligible draft is rejected with `ERR_PRESCRIPTION_INELIGIBLE`. Submission also requires the parent consultation's `session_status` to be `COMPLETED`. Submission appends an `AuditLog` row with `action_code` `PRESCRIPTION_SUBMITTED`.

Pharmacist review is the heart of segregation of duties. A pharmacist whose `X-User-ID` equals the prescription's `drafting_doctor_id` is rejected on either approval or rejection with `ERR_SEGREGATION_OF_DUTIES`. Approval transitions `status` from `UNDER_REVIEW` to `APPROVED`, records the approving pharmacist's id in `reviewing_pharmacist_id`, computes `gross_amount_cents` as the sum over `items` of `unit_price_cents` multiplied by `quantity`, and appends an `AuditLog` row with `action_code` `PRESCRIPTION_APPROVED`. Rejection — which requires a non-null `rejection_reason` in the request body — transitions `status` from `UNDER_REVIEW` to `REJECTED`, records both `reviewing_pharmacist_id` and `rejection_reason`, and appends an `AuditLog` row.

From `REJECTED`, the drafting doctor (again gated on `X-User-ID` equalling `drafting_doctor_id`) may revise to bring the prescription back to `DRAFT`. Revision may optionally replace `items` and `disease_codes`. Revision clears `rejection_reason` and increments `revision_count` by one. The system caps the revision loop: once `revision_count` has reached the configured maximum, a further revise call instead drives an automatic transition from `REJECTED` to the terminal `FAILED` and appends an `AuditLog` row with `action_code` `PRESCRIPTION_FAILED`.

An approved prescription is dispatched by the pharmacist to the configured target. Dispatch transitions `status` from `APPROVED` to `DISPATCHED`, requires `dispatch_target_id` to resolve to an active row in the pharmacy directory for the chosen `dispatch_target_kind` (otherwise `ERR_DISPATCH_TARGET_INVALID`), sets `dispensing_status` to `NONE`, emits a PRESCRIPTION_DISPATCHED event to the electronic prescription circulation platform, triggers an `InsuranceClaim` eligibility check when the patient has an `insurance_policy_no`, and appends an `AuditLog` row.

Pharmacy progress is reported back to the system as external events. Each `PHARMACY_DISPENSED` event advances `dispensing_status` through the sequence `RECEIVED -> PREPARING -> READY -> DELIVERED`. When the `DELIVERED` step is reached, the prescription's `status` advances to the terminal `DISPENSED` and an `AuditLog` row is appended. A `PHARMACY_FAILED` event from `DISPATCHED` transitions the prescription to the terminal `FAILED`, setting `dispensing_status` to `FAILED`; if a linked `InsuranceClaim` is in `SETTLING` no compensating action is taken here, and if it is already `SETTLED` no compensation is performed here either (the refund flow is out of scope of this API).

### 3.7. Insurance Eligibility, Settlement, and Self-Pay Collection

When a dispatch triggers an `InsuranceClaim`, the new claim is created with the originating `consultation_id`, the linked `prescription_id` (or null when the claim covers only the consultation fee), the patient's denormalised `patient_id`, and the initial `status` `ELIGIBILITY_PENDING`. Verifying eligibility advances the claim to either `VERIFIED` or `INELIGIBLE` depending on the result of consulting the bureau (the call body carries the `insurance_status` returned by the bureau). The consultation must already be `COMPLETED`. A patient whose `insurance_status` is `ELIGIBLE` advances the claim to `VERIFIED` and sets `deductible_cents` to a per-claim deductible of 5,000 cents and `claim_amount_cents` to the consultation's `total_fee` converted to cents plus the linked prescription's `gross_amount_cents` (when a prescription is linked). A patient whose `insurance_status` is `INELIGIBLE`, `SUSPENDED`, or `UNKNOWN` advances the claim to the terminal `INELIGIBLE` and sets `self_pay_cents` equal to the full `claim_amount_cents`.

Settlement is initiated by the platform admin and advances `status` from `VERIFIED` to `SETTLING`. Settlement runs the tiered reimbursement formula, computes `reimbursed_cents`, computes `self_pay_cents` as `claim_amount_cents` minus `reimbursed_cents`, and emits a BUREAU_SETTLE_REQUEST event. The tiered formula proceeds as follows: the eligible amount in cents is the larger of zero and `claim_amount_cents` minus `deductible_cents`. The first tier covers up to 10,000 cents of the eligible amount; the second tier covers any remainder. The tier-one amount equals the smaller of the eligible amount and 10,000; the tier-two amount equals zero or the eligible amount minus 10,000, whichever is greater. Each tier is multiplied by its rate and rounded half-up to integer cents independently; the rounded tier amounts are then summed to produce `reimbursed_cents`. (Contrast this rounding order with the consultation fee, which rounds once at the very end.) Finally, `reimbursed_cents` is capped at an annual cap of 1,000,000 cents minus the patient's year-to-date reimbursed amount across prior `SETTLED` claims this calendar year — that is, the minimum of the formula's result and the remaining annual headroom is taken.

The tier rates depend on the linked disease scope. When the linked prescription's `disease_codes` intersects the in-scope disease enumeration (or the claim covers only the consultation fee and has no prescription linkage), the first-tier rate is 0.70 and the second-tier rate is 0.50. When the linked prescription's `disease_codes` is fully outside the in-scope enumeration, penalty rates apply: the first-tier rate drops to 0.30 and the second-tier rate drops to 0.20.

The bureau returns its decision as an external event. A `BUREAU_SETTLED` event advances `status` from `SETTLING` to the terminal `SETTLED`, sets `bureau_ref` from the event payload, and is the audit point at which the compensating invariant `claim_amount_cents == reimbursed_cents + self_pay_cents` must hold. If the recomputed sum does not match `claim_amount_cents`, the violation surfaces as `ERR_INSURANCE_INVARIANT_VIOLATION`. A `BUREAU_REJECTED` event advances `status` from `SETTLING` to the terminal `REJECTED_BY_BUREAU`, resets `reimbursed_cents` to zero, and sets `self_pay_cents` to the full `claim_amount_cents`.

After the claim reaches `SETTLED`, the platform admin may collect the patient's self-pay portion. The collect-self-pay action is idempotent on `self_pay_collected_cents`: the call is accepted only while `self_pay_collected_cents` is zero, and it sets `self_pay_collected_cents` equal to `self_pay_cents`. (A `PAYMENT_CONFIRMED` event from the payment gateway has the same effect.)

### 3.8. Follow-up Plans, Reminders, and Auto-Escalation

A doctor creates a follow-up plan for a completed consultation. The payload carries the parent `consultation_id`, a `plan_template_code` identifier for the template the doctor chose, a `scheduled_reminder_at` server-clock instant, and a non-empty subset of `reminder_channels` drawn from `SMS`, `EMAIL`, and `APP_PUSH`. The denormalised `patient_id` on the follow-up must equal the consultation's `patient_id`. An empty or out-of-range `reminder_channels` value is rejected with `ERR_REMINDER_CHANNELS_INVALID`. The new task starts in `PLANNED` with `form_payload` null and `abnormal_flag` false.

When the server clock reaches `scheduled_reminder_at`, an admin-driven reminder trigger advances `status` from `PLANNED` to `REMINDED` and emits one MULTI_CHANNEL_REMINDER event per channel listed in `reminder_channels`. The patient then submits the follow-up form, providing `form_payload`; submission advances `status` from `REMINDED` to `SUBMITTED` and computes `abnormal_flag` as true when any field inside `form_payload` carries a severity equal to or greater than the abnormal threshold.

Form submission immediately runs one of two automatic transitions. When `abnormal_flag` is false, the task advances from `SUBMITTED` to the terminal `CLOSED`. When `abnormal_flag` is true, the task advances from `SUBMITTED` to the terminal `ESCALATED`: the system creates a new `Consultation` for the same patient with the same doctor in a freshly created state, records the new consultation's id in `escalation_consultation_id`, and appends an `AuditLog` row.

### 3.9. Audit Trail and Test-Driving the Clock

Every clinically or financially material action appends a row to the system's `AuditLog` capture. Each row records the `actor_role`, the `actor_user_id`, the canonical `action_code` for the operation (such as `CONSULTATION_ACCEPT`, `CONSULTATION_COMPLETED`, `PRESCRIPTION_SUBMITTED`, `PRESCRIPTION_APPROVED`, `PRESCRIPTION_FAILED`), the affected `target_entity`, the `target_id` of that entity, the `occurred_at` server-clock instant, and a `payload_digest` stable hash of the request body used as tamper-evidence. Audit log rows are append-only and may be listed by `PlatformAdmin` filtered by `target_entity`, `action_code`, and `actor_role`.

Two test-driving capabilities round out the API. An admin-only clock-advance capability moves the server's logical clock forward by a supplied `seconds` count; it does not implicitly trigger any deferred work — for example, follow-up reminders still require an explicit fire-reminder call after the clock crosses `scheduled_reminder_at`. An admin-only event-ingest capability accepts a `kind` and a `payload` and dispatches the event into the relevant aggregate: `PHARMACY_DISPENSED` and `PHARMACY_FAILED` drive `Prescription` post-dispatch transitions; `BUREAU_SETTLED` and `BUREAU_REJECTED` drive `InsuranceClaim` final transitions (the former idempotent on the composite key derived from `claim_id`, the event `kind`, and the supplied `bureau_ref`); and `PAYMENT_CONFIRMED` records self-pay collection on the linked claim.

## 4. Endpoint Definitions

Operations that create new resources return HTTP 201; all other mutations and reads return HTTP 200. Errors carry the HTTP status documented in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/consultation/patients` | Create a Patient. | PlatformAdmin |
| GET    | `/consultation/patients/{id}` | Get a patient. | Patient, PlatformAdmin |
| PATCH  | `/consultation/patients/{id}` | Update a patient's preferences and chronic-condition list. | Patient |
| POST   | `/consultation/doctors` | Create a Doctor. | PlatformAdmin |
| GET    | `/consultation/doctors/{id}` | Get a doctor. | Doctor, Patient, PlatformAdmin |
| PATCH  | `/consultation/doctors/{id}` | Update a doctor's availability or concurrency cap. | Doctor, PlatformAdmin |
| GET    | `/consultation/doctors` | List doctors with optional filters. | Patient, PlatformAdmin |
| POST   | `/consultation/pharmacists` | Register a Pharmacist. | PlatformAdmin |
| GET    | `/consultation/pharmacists/{id}` | Get a pharmacist. | Pharmacist, PlatformAdmin |
| POST   | `/consultation/department-mappings` | Register a department-to-disease mapping. | PlatformAdmin |
| GET    | `/consultation/department-mappings` | List department mappings. | Patient, Doctor, PlatformAdmin |
| POST   | `/consultation/triage-sessions` | Open a triage session in `COLLECTING` status. | Patient |
| POST   | `/consultation/triage-sessions/{id}/assess` | Compute severity, band, and recommended department. | Patient |
| POST   | `/consultation/triage-sessions/{id}/close` | Close a non-emergency assessed triage session. | Patient |
| GET    | `/consultation/triage-sessions/{id}` | Get a triage session. | Patient, Doctor, PlatformAdmin |
| POST   | `/consultation/consultations` | Create a consultation from an assessed triage session. | Patient |
| POST   | `/consultation/consultations/{id}/accept` | Doctor accepts a queued real-time consultation. | Doctor |
| POST   | `/consultation/consultations/{id}/start` | Doctor starts the session. | Doctor |
| POST   | `/consultation/consultations/{id}/quality-report` | Submit a video quality tier report. | Doctor |
| POST   | `/consultation/consultations/{id}/complete` | Doctor completes the session and finalises billing. | Doctor |
| POST   | `/consultation/consultations/{id}/transfer` | Transfer the session to another doctor. | Doctor |
| DELETE | `/consultation/consultations/{id}` | Patient cancels a queued or accepted consultation. | Patient |
| GET    | `/consultation/consultations/{id}` | Get a consultation. | Patient, Doctor, PlatformAdmin |
| GET    | `/consultation/consultations` | List consultations with optional filters. | Patient, Doctor, PlatformAdmin |
| POST   | `/consultation/consultations/{id}/image-attachments` | Record an image attachment for a consultation. | Patient |
| POST   | `/consultation/prescriptions` | Doctor drafts a prescription. | Doctor |
| POST   | `/consultation/prescriptions/{id}/submit` | Submit the draft to pharmacist review. | Doctor |
| POST   | `/consultation/prescriptions/{id}/approve` | Pharmacist approves the prescription. | Pharmacist |
| POST   | `/consultation/prescriptions/{id}/reject` | Pharmacist rejects the prescription with a reason. | Pharmacist |
| POST   | `/consultation/prescriptions/{id}/revise` | Doctor revises a rejected prescription. | Doctor |
| POST   | `/consultation/prescriptions/{id}/dispatch` | Dispatch an approved prescription to the chosen vendor. | Pharmacist |
| GET    | `/consultation/prescriptions/{id}` | Get a prescription. | Doctor, Pharmacist, Patient, PlatformAdmin |
| GET    | `/consultation/prescriptions` | List prescriptions with optional filters. | Doctor, Pharmacist, Patient, PlatformAdmin |
| POST   | `/consultation/insurance-claims/{id}/verify-eligibility` | Verify eligibility with the insurance bureau. | PlatformAdmin |
| POST   | `/consultation/insurance-claims/{id}/settle` | Initiate real-time settlement. | PlatformAdmin |
| POST   | `/consultation/insurance-claims/{id}/collect-self-pay` | Record self-pay collection (idempotent). | PlatformAdmin |
| GET    | `/consultation/insurance-claims/{id}` | Get an insurance claim. | PlatformAdmin, Patient |
| POST   | `/consultation/follow-up-tasks` | Doctor creates a follow-up plan. | Doctor |
| POST   | `/consultation/follow-up-tasks/{id}/fire-reminder` | Trigger reminder dispatch after the scheduled instant. | PlatformAdmin |
| POST   | `/consultation/follow-up-tasks/{id}/submit-form` | Patient submits the follow-up form. | Patient |
| GET    | `/consultation/follow-up-tasks/{id}` | Get a follow-up task. | Doctor, Patient, PlatformAdmin |
| GET    | `/consultation/audit-logs` | List audit log entries with optional filters. | PlatformAdmin |
| POST   | `/consultation/_clock/advance` | Advance the server clock (test harness). | PlatformAdmin |
| POST   | `/consultation/_events/emit` | Ingest an external event (test harness). | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_MISSING` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REF_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_TRIAGE_EMERGENCY_ROUTED` | 422 Unprocessable Entity |
| `ERR_NO_DOCTOR_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_PREFERRED_DOCTOR_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DOCTOR_AT_CAPACITY` | 409 Conflict |
| `ERR_DOCTOR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_OUT_OF_SCHEDULE` | 422 Unprocessable Entity |
| `ERR_TOO_LATE_TO_CANCEL` | 422 Unprocessable Entity |
| `ERR_PRESCRIPTION_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PRESCRIPTION_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DISPATCH_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_REMINDER_CHANNELS_INVALID` | 422 Unprocessable Entity |
| `ERR_QUESTIONNAIRE_EMPTY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_BUREAU_EVENT` | 409 Conflict |
| `ERR_INSURANCE_INVARIANT_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
