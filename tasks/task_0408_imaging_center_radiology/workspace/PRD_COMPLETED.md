# Imaging Center Radiology API — Product Requirements Document

## 1. Introduction

The Imaging Center Radiology API coordinates the end-to-end diagnostic-imaging workflow that a modern radiology practice runs every day: an ordering clinician requests a study, a scheduling clerk verifies coverage and books a room, a nurse screens the patient for contrast and magnetic-resonance safety, a technologist acquires the images, and a radiologist reads, signs off, and — where the findings are urgent — raises and tracks a critical-result notification. Each of these steps is owned by a different operational role, and the system's job is to keep them honest with respect to one another: a study cannot be scheduled until its coverage is confirmed and its safety screening clears, a study cannot be read by the same person who acquired it, and a study with an urgent finding cannot be signed off until someone has been notified.

Beyond the per-study pipeline, the platform also acts as the quality and financial ledger for the center. It continuously tracks the proportion of image series that had to be repeated or rejected and escalates the whole center into a quality hold when that proportion crosses a configured threshold; it credits work-RVU to the reading radiologist according to modality, priority, contrast, and amendment status; and it measures report turnaround against modality- and priority-specific targets. A deterministic, test-controllable center clock underpins every time-sensitive rule, so that screening gates, acquisition timestamps, turnaround, and critical-result SLAs are all reproducible. This document specifies the entities, state machines, calculations, validation order, and access-control rules that any conforming implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to invoke the requested operation (per the authorization matrix in §4), the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes five roles, spelled exactly as follows: `CenterAdmin`, `SchedulingClerk`, `Nurse`, `Technologist`, and `Radiologist`.

`CenterAdmin` and `SchedulingClerk` are opaque operator identities: when `X-User-Role` is `CenterAdmin` or `SchedulingClerk`, the corresponding `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow naturally captures the acting operator, but it does not compare it to any entity's `id`. `Nurse`, `Technologist`, and `Radiologist` are each entity-backed by a `Staff` record: when `X-User-Role` is `Nurse`, `Technologist`, or `Radiologist`, the corresponding `X-User-ID` is the `id` of the acting `Staff` member, and ownership checks on any exam or report that references a `Staff` member compare the resource's stored foreign key (for example, an exam's `technologist_id` or `radiologist_id`, or a report's `radiologist_id`) to `X-User-ID`. This entity backing is what makes the segregation-of-duties and assigned-actor rules in §3 enforceable.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with no upper bound beyond the size of the collection.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; resources sharing the same `created_at` value are ordered by the sequence in which they were created (insertion order), so the ordering is stable.

Every list response includes the following fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`. `total_count` is the size of the full (post-filter) collection before pagination, and `has_more` is true exactly when `offset + limit` is strictly less than `total_count`.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. All entities in this system — the `ImagingCenter`, `Modality`, `Room`, `Staff`, `ImagingOrder`, `PriorAuthorization`, `ContrastScreening`, `ImagingExam`, `ImageSeries`, `RadiologyReport`, and `CriticalResult` — additionally carry an `updated_at` timestamp (same ISO 8601 UTC format) and an integer `version`. The `version` begins at 1 on creation and increments by exactly one on every mutation of the resource, whether that mutation is a direct client write or a server-initiated reconciliation; `updated_at` is refreshed to the moment of the same mutation.

Foreign-key fields such as `imaging_center_id`, `modality_id`, `imaging_order_id`, `imaging_exam_id`, `radiology_report_id`, `room_id`, `technologist_id`, and `radiologist_id` are system-managed UUID references; clients supply them only where an endpoint explicitly accepts them as input, and the server populates the rest from context.

### 2.5. Nested Resource Retrieval and Reference Validation

Many resources are addressed through their parent in the URL hierarchy. When a path carries more than one identifier, the server validates them strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A request for an order's screenings under a non-existent order, for example, fails on the order before the screening collection is ever consulted.

Foreign-key fields supplied in a request body — for instance a `modality_id`, `room_id`, or `technologist_id` named when scheduling an exam — are validated separately: if any of them references a resource that does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Both of these checks precede any business-rule evaluation.

### 2.6. The Deterministic Center Clock

Time in this system is not wall-clock time; it is the deterministic clock carried by each `ImagingCenter` in its `now_utc` field. A freshly created center has `now_utc` equal to `1970-01-01T00:00:00.000Z`, and the clock advances only when an administrator drives it forward. Every timestamp the system stamps — an exam's `acquired_at_utc`, an exam's `signed_off_at_utc`, a critical result's `raised_at_utc` and `acknowledged_at_utc` — is read from the owning center's `now_utc` at the instant of the action. The check-in window, report turnaround, and the critical-result SLA are therefore all evaluated against this controllable clock rather than against the host machine's time.

Advancing the clock is an administrator capability: the caller supplies the target center via `imaging_center_id` and the new instant via `to_iso8601`, and the server sets that center's `now_utc` to the supplied value. Advancing the clock is not a passive operation — it re-evaluates every `CriticalResult` under the center for SLA breach and then re-derives the center's `posture`, because an unacknowledged critical result can breach its SLA purely through the passage of time.

### 2.7. Precision and Rounding

Wherever this document specifies a computed numeric quantity — the repeat/reject rate percentage, credited work-RVU, report turnaround in minutes, and a critical result's minutes-to-acknowledgement — the value is rounded to exactly 2 decimal places using the round-half-up convention. Where a calculation composes several terms (as RVU credit does), rounding is applied once to the final product, never to the intermediate terms. Integer counters such as `total_acquired_series`, `total_repeat_reject_series`, `requested_units`, `authorized_units`, `benefit_copay_cents`, `addendum_count`, and `cleanup_buffer_minutes` are exact integers and are not rounded. Threshold comparisons described in §3 are exact: where a rule says "at or above" or "strictly after," that boundary inclusivity is part of the contract and must be honored literally.

### 2.8. Center Posture and Quality Governance

Each `ImagingCenter` exposes a computed operational `posture` that is one of `OPEN`, `QUALITY_HOLD`, or `LOCKED`. Posture is never written directly; it is re-derived from the center's own state by a fixed precedence in which the first matching condition wins. First: if the center's `admin_locked` flag is true, the posture is `LOCKED`, regardless of any quality metric. Otherwise: if the center's `repeat_reject_rate_pct` is at or above its `repeat_rate_threshold_pct`, or if any `CriticalResult` belonging to the center currently has `sla_breached` equal to true, the posture is `QUALITY_HOLD`. If neither of those holds, the posture is `OPEN`. The `admin_locked` flag is itself system-managed: it is set true only by the administrator lock capability and false only by the administrator unlock capability, and it defaults to false on a new center.

Two distinct triggers can therefore drive a center into `QUALITY_HOLD`: a quality trigger, where the repeat/reject rate has reached the configured threshold, and a safety trigger, where at least one critical result has breached its acknowledgement SLA. The quality trigger clears on its own once the rate falls back below the threshold; the safety trigger clears only once no breached, unacknowledged result remains. Because both conditions feed the same `QUALITY_HOLD` posture, the posture is re-derived after every series finalization, after a critical result is raised or acknowledged, after the clock advances, and after an unlock.

### 2.9. Hierarchical Consistency and Bubble-Up

This system makes heavy use of server-initiated state propagation: a write to a child resource can, as a documented side effect, advance the state of its parent without a separate client request against the parent. When a technologist finishes acquisition on an exam, the exam's parent order advances on its own; when a report is finalized, its exam advances; when an exam signs off, its order advances and the reading radiologist's cumulative RVU total updates. Each such propagation is a genuine mutation of the affected resource: it refreshes that resource's `updated_at` and increments its `version`. Where §3 narrates a workflow step, every "bubble-up" it describes is mandatory and atomic with the triggering write — the parent must already reflect the new state by the time the triggering request returns.

### 2.10. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two. Each requires the client to echo back the version of the parent it last observed, and each rejects the write with `ERR_STALE_VERSION` (HTTP 412) when that echoed version no longer matches the parent's current `version`.

The first is scheduling an exam against an order. That request must carry `expected_imaging_order_version`, and the value must equal the target `ImagingOrder`'s current `version`. The second is a radiologist claiming an exam to read. That request must carry `expected_imaging_exam_version`, and the value must equal the target `ImagingExam`'s current `version`. No other endpoint accepts or requires a version field; those endpoints perform no OCC check.

This OCC version match is evaluated strictly after the state check described in §3.9 (`ERR_INVALID_STATE` is checked before `ERR_STALE_VERSION`), and the implementation honors that ordering literally. Every mutation that increments an order's `version` also transitions the order out of `SCREEN_CLEARED` (scheduling moves it to `SCHEDULED`, a cancel moves it to `CANCELLED`), and every mutation that increments an exam's `version` also transitions the exam out of `ACQUIRED` (a successful claim moves it to `READING` and sets its `radiologist_id`); no version bump ever leaves the parent in the state that the guarded write requires. Consequently, any second request that arrives holding the now-stale pre-action version is necessarily acting on a parent whose state has already advanced past the transition's required precondition, so it fails the state check first and is rejected with `ERR_INVALID_STATE` rather than `ERR_STALE_VERSION`. The `ERR_STALE_VERSION` rejection would surface only if a client presented a non-matching version while the parent still satisfied the state precondition; under the transitions defined in this document no such situation arises, so a second scheduling action on an already-`SCHEDULED` order, or a second claim on an already-`READING` exam, surfaces `ERR_INVALID_STATE`.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Center, Modalities, Rooms, and Staff

A `CenterAdmin` provisions the static topology of a practice. Creating an `ImagingCenter` requires a `name` and optionally accepts a `time_zone` (an informational IANA label, defaulting to `UTC`; all stored timestamps remain UTC regardless), a `critical_ack_sla_minutes` value (defaulting to 60 minutes), and a `repeat_rate_threshold_pct` (defaulting to 8.0 percent). A new center starts with `posture` `OPEN`, `admin_locked` false, all three series counters at zero — `total_acquired_series`, `total_repeat_reject_series`, and `repeat_reject_rate_pct` — and `now_utc` at the Unix epoch as described in §2.6.

Under a center, the administrator creates one or more **modalities**. A `Modality` requires a `modality_type`, one of `MRI`, `CT`, `XRAY`, or `US`; a human-readable `name`; and a `base_rvu`, the base work-RVU credited per signed-off exam on that modality, which must be at least zero. It also accepts `requires_prior_auth`, defaulting to true; when true, an order on the modality cannot complete its benefit check until an authorization exists. The modality's `requires_contrast_screening` is not supplied by the caller — it is derived as true exactly when the `modality_type` is `MRI` or `CT`, and false for `XRAY` and `US`, which never require contrast or safety screening. The modality carries an `imaging_center_id` back to its center.

Each `Room` is created under the center and hosts exactly one modality, named by `modality_id`; the room also carries an `imaging_center_id`, a `name`, and an optional `cleanup_buffer_minutes` that defaults to 0. The cleanup buffer is the number of minutes of post-exam turnaround appended to each booking in that room, during which the room is treated as occupied. A room begins with `status` `AVAILABLE`; an administrator may later move it to `OUT_OF_SERVICE`, after which it refuses new bookings. Staff members are likewise created under the center: a `Staff` record carries an `imaging_center_id`, a `staff_role` of `TECHNOLOGIST`, `RADIOLOGIST`, or `NURSE`, a `full_name`, and a `credentialed_modalities` array naming the subset of `MRI`, `CT`, `XRAY`, and `US` the member may operate or read. The `credentialed_modalities` array must be non-empty; creating a staff member with an empty credential list is rejected with `ERR_EMPTY_CREDENTIALS`. A radiologist's `signed_rvu_total` — the cumulative work-RVU credited from signed-off exams — starts at 0.0 and is maintained by the system.

### 3.2. Order Intake, Prior Authorization, and the Benefit Gate

A `SchedulingClerk` opens the per-patient workflow by creating an `ImagingOrder` under a center. The order names the requested `modality_id`, the `patient_mrn` (a free-form medical record number), and the ordering clinician's `ordering_provider_npi`. It optionally carries a `priority` of `STAT` or `ROUTINE` (defaulting to `ROUTINE`; `STAT` orders are read-prioritized and carry tighter turnaround targets) and a `requires_contrast` flag (defaulting to false) indicating whether the ordered protocol uses IV contrast — meaningful only for MRI and CT. A new order is `REQUESTED` and also stores its `imaging_center_id`. Its `report_turnaround_minutes` and `turnaround_met` fields are null until the study is signed off.

Where the order's modality requires prior authorization, the clerk first raises a `PriorAuthorization` against the order, naming the `payer_name` and the `requested_units` (which must be at least 1). The authorization begins `PENDING` with `authorized_units` and `benefit_copay_cents` both at 0, and carries an `imaging_order_id` back to its order. The clerk then records the payer's `decision`. An `AUTHORIZE` decision moves the authorization to `AUTHORIZED` and sets `authorized_units` from the payload; the supplied `authorized_units` must be at least the `requested_units`, and a decision that authorizes fewer units than were requested is rejected with `ERR_INSUFFICIENT_AUTH_UNITS`. A `DENY` decision moves the authorization to `DENIED` and leaves `authorized_units` at 0. A decision may only be recorded while the authorization is `PENDING`; otherwise the request is rejected with `ERR_INVALID_STATE`.

The benefit check is the fiscal gate that advances the order from `REQUESTED` to `BENEFIT_CHECKED`. It may only run while the order is `REQUESTED` (otherwise `ERR_INVALID_STATE`). When the order's modality has `requires_prior_auth` true, the order must have a `PriorAuthorization` child in `AUTHORIZED` status, or the benefit check is rejected with `ERR_PRIOR_AUTH_REQUIRED`; when the modality's `requires_prior_auth` is false, this authorization check is skipped entirely and no authorization need exist. The benefit-check request optionally carries `benefit_copay_cents`, which is recorded onto the order's authorization as the patient copay assigned at benefit check; when the modality does not require prior authorization and no authorization exists, the copay defaults to 0.

### 3.3. Contrast and Safety Screening

For modalities that require contrast screening — that is, MRI and CT — a `Nurse` documents a `ContrastScreening` against the order before it can clear. The screening captures the patient's `egfr_value` (estimated GFR, the renal-safety measure), and three optional boolean flags defaulting to false: `has_contrast_allergy` for a documented prior contrast reaction, `is_pregnant` as a pregnancy flag, and `metal_implant_unsafe` for an MRI-relevant ferromagnetic implant deemed unsafe. The screening carries an `imaging_order_id` and begins with `outcome` `PENDING` and a null `blocking_reason`.

Evaluating a screening is deterministic: the same inputs always route to the same `outcome`, and the nurse does not choose `CLEARED` versus `BLOCKED` — the system decides. Evaluation may only run while the screening is `PENDING` (otherwise `ERR_INVALID_STATE`), and it never returns an error for an unsafe patient; an unsafe patient is routed to `BLOCKED` with a populated `blocking_reason`, which is itself a valid outcome. The decision walks four hard-stop conditions in this fixed precedence, and the first one that matches sets `outcome` to `BLOCKED` and writes the corresponding `blocking_reason`:

1. **Pregnancy.** If the patient is pregnant and either the order's protocol uses contrast or the modality is `CT`, the screening is `BLOCKED` with reason `PREGNANCY`. (Pregnancy is a hard stop for any contrast study and for CT regardless of contrast.)
2. **Metal implant.** If the modality is `MRI` and the patient has an unsafe metal implant, the screening is `BLOCKED` with reason `METAL_IMPLANT`.
3. **Contrast allergy.** If the order's protocol uses contrast and the patient has a documented contrast allergy, the screening is `BLOCKED` with reason `CONTRAST_ALLERGY`.
4. **Renal function.** If the order's protocol uses contrast and the patient's `egfr_value` is strictly below 30 (the minimum safe eGFR for contrast administration), the screening is `BLOCKED` with reason `RENAL_FUNCTION`.

If none of the four conditions matches, the screening clears: `outcome` becomes `CLEARED` and `blocking_reason` remains null. Note the two protocol variants this produces. For a contrast protocol (the order uses contrast), all four hard stops are live. For a non-contrast protocol, the renal and contrast-allergy gates are inert because they only apply to contrast studies, but pregnancy still blocks a `CT` study and the metal-implant stop still blocks an `MRI` study.

With benefit checked, a `Nurse` clears the order for scheduling, advancing it from `BENEFIT_CHECKED` to `SCREEN_CLEARED`. The order must be in `BENEFIT_CHECKED` for this step (otherwise `ERR_INVALID_STATE`). When the order's modality requires contrast screening, the order must have a `ContrastScreening` child whose `outcome` is `CLEARED`, or the clearance is rejected with `ERR_SCREENING_NOT_CLEARED`; when the modality does not require screening, this check is skipped and no screening need exist.

### 3.4. Scheduling: Booking a Room and Technologist

Once an order reaches `SCREEN_CLEARED`, a `SchedulingClerk` schedules it by creating an `ImagingExam`, which both books resources and advances the order from `SCREEN_CLEARED` to `SCHEDULED`. The scheduling payload names the `room_id` to reserve, the `technologist_id` to assign, the booking interval as `scheduled_start_utc` (inclusive) and `scheduled_end_utc` (exclusive), and the optimistic-concurrency token `expected_imaging_order_version` described in §2.10. The new exam is created in `BOOKED`, carries an `imaging_order_id` back to the order, and its `radiologist_id`, `acquired_at_utc`, and `signed_off_at_utc` are all null at this stage. Creating the exam increments the order's `version`.

The booking is admissible only if it survives a series of checks. The order must be in `SCREEN_CLEARED` (otherwise `ERR_INVALID_STATE`). The assigned technologist must be credentialed on the order's modality type, or the booking is rejected with `ERR_TECH_NOT_CREDENTIALED`. The booked room must host the same modality as the order requests and must not be `OUT_OF_SERVICE`; a mismatch or an out-of-service room is rejected with `ERR_ROOM_MODALITY_MISMATCH`. The interval itself must be valid — `scheduled_end_utc` strictly after `scheduled_start_utc`, otherwise `ERR_INVALID_INTERVAL`. The room must be free for the requested window: the room's booking interval extended by its `cleanup_buffer_minutes` (the room is occupied across the half-open span from the start through the exam end plus the buffer) must not overlap any other non-cancelled exam in the same room, or the booking is rejected with `ERR_ROOM_DOUBLE_BOOKED`. Finally, the technologist's interval — taken with no cleanup buffer — must not overlap any other non-cancelled exam assigned to the same technologist, or the booking is rejected with `ERR_TECH_DOUBLE_BOOKED`. A cancelled exam releases both its room interval and its technologist interval so that they no longer count toward these overlap checks.

A clerk may cancel an order at any point before it is finalized — specifically, an order may be cancelled when it is not in `SIGNED_OFF`, `ADDENDUM_REQUESTED`, or `CANCELLED`; an attempt to cancel from one of those states is rejected with `ERR_INVALID_STATE`. Cancelling an order moves it to `CANCELLED` and, if an exam exists for it in a non-terminal pre-acquisition state (`BOOKED` or `CHECKED_IN`), cascade-cancels that exam, which releases the room and technologist intervals. A clerk may also cancel a `BOOKED` or `CHECKED_IN` exam directly; an exam can no longer be cancelled once it has reached `ACQUIRING` or any later state (otherwise `ERR_INVALID_STATE`). Cancelling an exam directly likewise releases its room and technologist intervals.

### 3.5. Acquisition: Check-In, Capture, and the Repeat/Reject Rate

The assigned `Technologist` runs the acquisition phase. Each technologist action requires that the acting `X-User-ID` equal the exam's `technologist_id`, or the action is rejected with `ERR_NOT_ASSIGNED_TECH`. Check-in moves the exam from `BOOKED` to `CHECKED_IN`; it requires the exam to be `BOOKED` (otherwise `ERR_INVALID_STATE`) and may not happen before the appointment — the center's `now_utc` must be at or after the exam's `scheduled_start_utc`, otherwise the check-in is rejected with `ERR_TOO_EARLY_TO_CHECK_IN`.

Starting acquisition moves the exam from `CHECKED_IN` to `ACQUIRING`, requiring the exam to be `CHECKED_IN` (otherwise `ERR_INVALID_STATE`). This is the one acquisition step gated on center quality: the center's `posture` must not be `QUALITY_HOLD`, or the start is rejected with `ERR_CENTER_QUALITY_HOLD`. A quality hold therefore freezes new acquisitions center-wide until the hold clears.

While an exam is `ACQUIRING`, the technologist captures one or more image series. Each `ImageSeries` is created with a `series_label`, begins with `outcome` `CAPTURING`, and carries both an `imaging_exam_id` and a denormalized `imaging_center_id` copied from the exam (so that center-level rate roll-up does not need to walk the hierarchy). Finalizing a series records its terminal outcome — `ACCEPTED`, `REPEATED`, or `REJECTED` — and may only be done while the series is `CAPTURING` and its parent exam is `ACQUIRING` (otherwise `ERR_INVALID_STATE` on whichever is wrong). An `ACCEPTED` series is usable and takes no `reject_reason`; a `REPEATED` or `REJECTED` series must carry a `reject_reason` of `MOTION`, `POSITIONING`, `EXPOSURE`, `ARTIFACT`, or `EQUIPMENT`, and finalizing to `REPEATED` or `REJECTED` without one is rejected with `ERR_REJECT_REASON_REQUIRED`.

Every series finalization feeds the center's running quality aggregate. On each finalization the center's `total_acquired_series` increases by one; additionally, when the outcome is `REPEATED` or `REJECTED`, the center's `total_repeat_reject_series` also increases by one. The `repeat_reject_rate_pct` is then recomputed as 100 multiplied by `total_repeat_reject_series` divided by `total_acquired_series`, rounded half-up to 2 decimal places — except that the rate is 0.0 whenever `total_acquired_series` is zero. Immediately after the counters and rate update, the center's `posture` is re-derived per §2.8; if the recomputed rate has reached the threshold, the resulting `QUALITY_HOLD` is what blocks subsequent start-acquisition attempts across the center.

Finishing acquisition moves the exam from `ACQUIRING` to `ACQUIRED`. It requires the exam to be `ACQUIRING`, at least one `ImageSeries` on the exam to have outcome `ACCEPTED` (otherwise `ERR_NO_ACCEPTED_SERIES`), and no `ImageSeries` on the exam to still be `CAPTURING` (otherwise `ERR_SERIES_STILL_CAPTURING`). On finishing, the exam's `acquired_at_utc` is stamped from the center's `now_utc`, and the parent order bubbles up from `SCHEDULED` to `READ_PENDING`.

### 3.6. The Read: Claiming, Reporting, and Sign-Off

A `Radiologist` reads an acquired study. Claiming an exam moves it from `ACQUIRED` to `READING` and reserves the read for the claiming radiologist. The claim requires the exam to be `ACQUIRED` (otherwise `ERR_INVALID_STATE`); the acting radiologist must be credentialed on the order's modality type, or the claim is rejected with `ERR_RADIOLOGIST_NOT_CREDENTIALED`; the acting `X-User-ID` must not equal the exam's `technologist_id`, enforcing segregation of duties — the same person may not both acquire and read a study — otherwise `ERR_SEGREGATION_OF_DUTIES`; and the exam must not already be claimed, that is its `radiologist_id` must still be null, otherwise `ERR_ALREADY_CLAIMED`. The claim also requires the `expected_imaging_exam_version` token described in §2.10. A successful claim sets the exam's `radiologist_id` to the acting radiologist and increments the exam's `version`. Because that single mutation both reserves the read and advances the exam from `ACQUIRED` to `READING`, an exam whose `radiologist_id` is already set is necessarily in `READING` rather than `ACQUIRED`. The `ERR_ALREADY_CLAIMED` clause therefore only describes the intent of this precondition; the `ACQUIRED` state check sits earlier in the §3.9 priority order, so a second claim against an already-claimed exam fails that state check first and is rejected with `ERR_INVALID_STATE` (regardless of whether its echoed version is stale or fresh).

Reading produces a `RadiologyReport`. The claiming radiologist drafts a report against the `READING` exam, supplying the `findings_text` and an optional `has_critical_finding` flag (defaulting to false). The report begins in `DRAFT`, carries an `imaging_exam_id`, and takes its `radiologist_id` from the exam's claimed reader; its `rvu_credited` starts at 0.0 and its `addendum_count` at 0. Finalizing a `DRAFT` report that has never been amended moves it to `FINAL`; this requires the report to be `DRAFT`, the acting `X-User-ID` to equal the report's `radiologist_id` (otherwise `ERR_NOT_ASSIGNED_RADIOLOGIST`), and the parent exam to be in `READING` (otherwise `ERR_INVALID_STATE`). Finalizing the report for the first time bubbles the exam from `READING` to `READ_COMPLETE`.

Signing off the read moves the exam from `READ_COMPLETE` to `SIGNED_OFF`. It requires the exam to be `READ_COMPLETE` (otherwise `ERR_INVALID_STATE`) and the acting `X-User-ID` to equal the exam's `radiologist_id` (otherwise `ERR_NOT_ASSIGNED_RADIOLOGIST`). Crucially, if the report's `has_critical_finding` is true, a `CriticalResult` must already have been raised for that report, or the sign-off is rejected with `ERR_CRITICAL_RESULT_REQUIRED`. On sign-off, the exam's `signed_off_at_utc` is stamped from the center's `now_utc`, the report's `rvu_credited` is computed (see below) and added to the reading radiologist's `signed_rvu_total`, and the parent order bubbles up from `READ_PENDING` to `SIGNED_OFF`, at which point the order's `report_turnaround_minutes` and `turnaround_met` are computed.

**Work-RVU credit.** The RVU credited to the reading radiologist on a signed-off exam starts from the modality's `base_rvu`. A `STAT` order multiplies the base by a STAT factor of 1.5; a `ROUTINE` order uses a factor of 1.0. If the order uses contrast, a contrast add-on of 0.75 is added; otherwise nothing is added. The composed value is then multiplied by an amendment factor, which is 1.0 for the original sign-off and 0.5 for any sign-off that finalizes an amended report. In other words, the credited RVU equals the base multiplied by the STAT-or-routine factor, plus the contrast add-on when contrast applies, the whole then multiplied by the amendment factor — with rounding to 2 decimal places applied half-up exactly once, to the final product. On the original sign-off the amendment factor is 1.0 and the full `rvu_credited` is added to the radiologist's `signed_rvu_total`. On an addendum re-sign-off (described in §3.7) the amendment factor is 0.5, and only the delta between the new `rvu_credited` and the prior `rvu_credited` is added to `signed_rvu_total`, as a compensating adjustment so the running total stays correct.

**Report turnaround.** On sign-off, `report_turnaround_minutes` is the difference between the exam's `signed_off_at_utc` and its `acquired_at_utc`, expressed in minutes (the millisecond difference divided by sixty thousand), rounded half-up to 2 decimal places. The acquisition timestamp is fixed at acquisition, while the sign-off timestamp is the most recent sign-off, so turnaround grows after an addendum re-sign. The `turnaround_met` flag is then set by comparing the turnaround against a target chosen by modality and priority: a turnaround less than or equal to the target counts as met (the boundary value, exactly equal to the target, is met). For `STAT` orders the target in minutes is 60 for `MRI`, 45 for `CT`, 30 for `XRAY`, and 45 for `US`. For `ROUTINE` orders the target is 1440 minutes for `MRI`, 720 for `CT`, 240 for `XRAY`, and 480 for `US`.

### 3.7. Critical Results and the Acknowledgement SLA

When a report carries an urgent finding, the reading `Radiologist` raises a `CriticalResult` against it before sign-off; raising a critical result is admissible regardless of the report's current lifecycle state (`DRAFT`, `FINAL`, or `AMENDED`) — the report need not yet be finalized. The critical result names the `notified_party_role` — one of `ORDERING_PROVIDER`, `COVERING_PROVIDER`, or `RAPID_RESPONSE` — recording who was notified. It begins `UNACKNOWLEDGED`, carries a `radiology_report_id` and a denormalized `imaging_center_id`, has its `raised_at_utc` stamped from the center's `now_utc`, and has `acknowledged_at_utc`, `minutes_to_ack`, and `sla_breached` all initially unset (`sla_breached` defaults to false). A critical result's acknowledgement lifecycle evolves independently of its report's `DRAFT`/`FINAL`/`AMENDED` lifecycle; the two run in parallel on the same study.

Acknowledging a critical result moves it from `UNACKNOWLEDGED` to `ACKNOWLEDGED`, requiring it to be `UNACKNOWLEDGED` (otherwise `ERR_INVALID_STATE`). On acknowledgement, `acknowledged_at_utc` is stamped from the center's `now_utc`, `minutes_to_ack` is computed as the difference between `acknowledged_at_utc` and `raised_at_utc` in minutes (the millisecond difference divided by sixty thousand), rounded half-up to 2 decimal places, and `sla_breached` is set true when `minutes_to_ack` is strictly greater than the center's `critical_ack_sla_minutes`. While a result is still unacknowledged, its breach status is re-evaluated whenever the center clock advances: the elapsed minutes from `raised_at_utc` to the center's current `now_utc` are compared against `critical_ack_sla_minutes`, and `sla_breached` becomes true when that elapsed time is strictly greater than the SLA window. In both the acknowledged and the still-pending case the boundary is exclusive — elapsed time exactly equal to the SLA window is not a breach. Acknowledging a result also re-derives the center's `posture`, because an acknowledgement that resolves the only outstanding breach can lift a safety-driven `QUALITY_HOLD` (provided the repeat/reject rate is also below threshold).

A signed-off study can be amended. The reading radiologist opens an addendum on a `SIGNED_OFF` order, which moves the order from `SIGNED_OFF` to `ADDENDUM_REQUESTED`. This requires the order to be `SIGNED_OFF` (otherwise `ERR_INVALID_STATE`) and the order's report to be `FINAL` or `AMENDED` (otherwise `ERR_REPORT_NOT_FINAL`). Opening an addendum reopens the report to `DRAFT` and increments its `addendum_count` by one. The radiologist then re-finalizes the reopened report: a `DRAFT` report that has been reopened from a prior `FINAL` or `AMENDED` state (its `addendum_count` is at least 1) finalizes to `AMENDED` rather than `FINAL`, again requiring the acting `X-User-ID` to equal the report's `radiologist_id` (otherwise `ERR_NOT_ASSIGNED_RADIOLOGIST`). Re-finalizing to `AMENDED` bubbles the order from `ADDENDUM_REQUESTED` back to `SIGNED_OFF`, re-stamps the exam's `signed_off_at_utc`, and recomputes `report_turnaround_minutes` and `turnaround_met` against the new sign-off time as well as the reduced-factor RVU delta described in §3.6. The addendum cycle may repeat: each re-amendment reopens to `DRAFT`, bumps `addendum_count`, and re-finalizes to `AMENDED` the same way.

### 3.8. Administrative Overrides

Independently of the quality metrics, a `CenterAdmin` holds an override surface over a center's posture. Locking a center sets its `admin_locked` flag true and forces the `posture` to `LOCKED`, which by the precedence in §2.8 overrides any quality or safety condition. Unlocking clears the `admin_locked` flag and re-derives the posture from the live metrics, so a center that was masking a quality or safety condition under a `LOCKED` posture will surface that condition as `QUALITY_HOLD` once unlocked. Marking a room out of service sets its `status` to `OUT_OF_SERVICE` so it refuses further bookings. And, as described in §2.6, advancing the center clock is the administrator's means of moving deterministic time forward, re-evaluating critical-result SLAs and re-deriving posture as a consequence.

### 3.9. Validation Order

When more than one rule could reject a request, the checks are evaluated in a fixed priority so that the failure surfaced is deterministic. Authentication of the `X-User-ID` and `X-User-Role` headers comes first (`ERR_UNAUTHENTICATED`), then role authorization for the endpoint (`ERR_UNAUTHORIZED`), then existence of every path-referenced resource validated left to right (`ERR_NOT_FOUND`), then presence and type/enum validity of required body fields (`ERR_INVALID_REQUEST`), then existence of every foreign-key body field (`ERR_REFERENCE_NOT_FOUND`) — that is, after path resolution the body's required fields are checked for presence and type before any foreign-key reference it names is resolved. After those generic checks, resource-specific rules apply: the non-empty-credentials check on staff creation (`ERR_EMPTY_CREDENTIALS`), then the target resource being in the correct state for the requested transition (`ERR_INVALID_STATE`), then the optimistic-concurrency version match on the two guarded writes (`ERR_STALE_VERSION`). Business-safety, referential, temporal, and fiscal rules — screening clearance, quality hold, segregation of duties, critical-result-required, credential and room checks, interval and overlap checks, prior-auth, and authorized-units — are then evaluated within the workflow that owns them as described throughout §3. Where a semantic validation failure is not covered by a more specific code, the generic `ERR_VALIDATION` applies.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions and administrative overrides — return `200 OK`. List and fetch operations return `200 OK`. All write endpoints accept the role(s) listed; read endpoints are shared across the roles shown.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/imaging-centers` | Create an imaging center | CenterAdmin |
| GET | `/imaging-centers/{id}` | Fetch a center (posture, rate, counters) | CenterAdmin, SchedulingClerk, Nurse, Technologist, Radiologist |
| GET | `/imaging-centers` | List centers | CenterAdmin |
| POST | `/imaging-centers/{id}/lock` | Set posture LOCKED | CenterAdmin |
| POST | `/imaging-centers/{id}/unlock` | Clear admin lock; re-derive posture | CenterAdmin |
| POST | `/_clock/set_current_utc` | Set a center's deterministic now_utc; re-evaluate SLA + posture | CenterAdmin |
| POST | `/imaging-centers/{id}/modalities` | Create a modality under a center | CenterAdmin |
| GET | `/modalities/{id}` | Fetch a modality | CenterAdmin, SchedulingClerk, Nurse, Technologist, Radiologist |
| GET | `/imaging-centers/{id}/modalities` | List a center's modalities | CenterAdmin, SchedulingClerk, Nurse, Technologist, Radiologist |
| GET | `/modalities/{id}/rooms` | List rooms hosting a modality | CenterAdmin, SchedulingClerk, Technologist |
| GET | `/modalities/{id}/imaging-orders` | List orders for a modality | CenterAdmin, SchedulingClerk, Nurse, Technologist, Radiologist |
| POST | `/imaging-centers/{id}/rooms` | Create a room hosting one modality | CenterAdmin |
| GET | `/rooms/{id}` | Fetch a room | CenterAdmin, SchedulingClerk, Technologist |
| GET | `/imaging-centers/{id}/rooms` | List a center's rooms | CenterAdmin, SchedulingClerk, Technologist |
| POST | `/rooms/{id}/out-of-service` | Mark a room OUT_OF_SERVICE | CenterAdmin |
| POST | `/imaging-centers/{id}/staff` | Create a staff member | CenterAdmin |
| GET | `/staff/{id}` | Fetch a staff member (signed_rvu_total) | CenterAdmin, SchedulingClerk, Technologist, Radiologist |
| GET | `/imaging-centers/{id}/staff` | List a center's staff | CenterAdmin, SchedulingClerk, Technologist, Radiologist |
| POST | `/imaging-centers/{id}/imaging-orders` | Create an imaging order | SchedulingClerk |
| GET | `/imaging-orders/{id}` | Fetch an order (turnaround fields after sign-off) | CenterAdmin, SchedulingClerk, Nurse, Technologist, Radiologist |
| GET | `/imaging-centers/{id}/imaging-orders` | List a center's orders | CenterAdmin, SchedulingClerk, Nurse, Technologist, Radiologist |
| POST | `/imaging-orders/{id}/benefit-check` | Run prior-auth + benefit check; REQUESTED to BENEFIT_CHECKED | SchedulingClerk |
| POST | `/imaging-orders/{id}/clear-screening` | BENEFIT_CHECKED to SCREEN_CLEARED (screening-gated) | Nurse |
| POST | `/imaging-orders/{id}/exams` | Schedule an exam; SCREEN_CLEARED to SCHEDULED | SchedulingClerk |
| POST | `/imaging-orders/{id}/cancel` | Cancel an order (cascade-cancels a pre-acquired exam) | SchedulingClerk |
| POST | `/imaging-orders/{id}/request-addendum` | Open an addendum; SIGNED_OFF to ADDENDUM_REQUESTED | Radiologist |
| POST | `/imaging-orders/{id}/prior-authorizations` | Create a prior-authorization request for an order | SchedulingClerk |
| GET | `/prior-authorizations/{id}` | Fetch a prior-authorization | CenterAdmin, SchedulingClerk |
| GET | `/imaging-orders/{id}/prior-authorizations` | List an order's prior-authorizations | CenterAdmin, SchedulingClerk |
| POST | `/prior-authorizations/{id}/decision` | Record AUTHORIZE/DENY decision | SchedulingClerk |
| POST | `/imaging-orders/{id}/contrast-screenings` | Create a contrast/safety screening for an order | Nurse |
| GET | `/contrast-screenings/{id}` | Fetch a screening (outcome + blocking_reason) | CenterAdmin, SchedulingClerk, Nurse |
| GET | `/imaging-orders/{id}/contrast-screenings` | List an order's screenings | CenterAdmin, SchedulingClerk, Nurse |
| POST | `/contrast-screenings/{id}/evaluate` | Evaluate screening; PENDING to CLEARED/BLOCKED | Nurse |
| GET | `/imaging-exams/{id}` | Fetch an exam (radiologist_id, timestamps) | CenterAdmin, SchedulingClerk, Technologist, Radiologist |
| GET | `/imaging-orders/{id}/exams` | List an order's exams | CenterAdmin, SchedulingClerk, Technologist, Radiologist |
| GET | `/rooms/{id}/exams` | List exams booked in a room | CenterAdmin, SchedulingClerk, Technologist |
| GET | `/staff/{id}/exams` | List exams assigned to a staff member | CenterAdmin, SchedulingClerk, Technologist, Radiologist |
| POST | `/imaging-exams/{id}/check-in` | Check the patient in; BOOKED to CHECKED_IN | Technologist |
| POST | `/imaging-exams/{id}/start-acquisition` | Start acquisition; CHECKED_IN to ACQUIRING | Technologist |
| POST | `/imaging-exams/{id}/finish-acquisition` | Finish acquisition; ACQUIRING to ACQUIRED | Technologist |
| POST | `/imaging-exams/{id}/claim-read` | Claim the exam to read; ACQUIRED to READING | Radiologist |
| POST | `/imaging-exams/{id}/sign-off` | Sign off the read; READ_COMPLETE to SIGNED_OFF | Radiologist |
| POST | `/imaging-exams/{id}/cancel` | Cancel a pre-acquired exam; release intervals | SchedulingClerk |
| POST | `/imaging-exams/{id}/image-series` | Capture a new image series under an ACQUIRING exam | Technologist |
| GET | `/image-series/{id}` | Fetch a series | CenterAdmin, Technologist, Radiologist |
| GET | `/imaging-exams/{id}/image-series` | List an exam's series | CenterAdmin, Technologist, Radiologist |
| GET | `/imaging-centers/{id}/image-series` | List a center's series | CenterAdmin |
| POST | `/image-series/{id}/finalize` | Finalize a series outcome; updates rate + posture | Technologist |
| POST | `/imaging-exams/{id}/reports` | Create a draft radiology report (READING exam) | Radiologist |
| GET | `/radiology-reports/{id}` | Fetch a report (rvu_credited, addendum_count) | CenterAdmin, Radiologist, SchedulingClerk |
| GET | `/imaging-exams/{id}/reports` | List an exam's reports | CenterAdmin, Radiologist, SchedulingClerk |
| GET | `/staff/{id}/reports` | List reports authored by a radiologist | CenterAdmin, Radiologist |
| POST | `/radiology-reports/{id}/finalize` | Finalize a report; DRAFT to FINAL or AMENDED | Radiologist |
| POST | `/radiology-reports/{id}/critical-results` | Raise a critical result on a report | Radiologist |
| GET | `/critical-results/{id}` | Fetch a critical result (minutes_to_ack, sla_breached) | CenterAdmin, Radiologist, SchedulingClerk |
| GET | `/radiology-reports/{id}/critical-results` | List a report's critical results | CenterAdmin, Radiologist, SchedulingClerk |
| GET | `/imaging-centers/{id}/critical-results` | List a center's critical results | CenterAdmin, SchedulingClerk |
| POST | `/critical-results/{id}/acknowledge` | Acknowledge a critical result; recompute SLA + posture | Radiologist |

List endpoints accept the standard `limit` and `offset` query parameters from §2.3. In addition, several list endpoints accept a domain filter: orders may be filtered by `status`; rooms by `modality_id`; staff by `staff_role`; image series by `outcome`; critical results by `status`; and the staff-exams listing accepts an `assignment_role` filter to distinguish exams where the staff member is the technologist from those where the staff member is the radiologist.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_EMPTY_CREDENTIALS` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PRIOR_AUTH_REQUIRED` | 402 Payment Required |
| `ERR_INSUFFICIENT_AUTH_UNITS` | 422 Unprocessable Entity |
| `ERR_SCREENING_NOT_CLEARED` | 409 Conflict |
| `ERR_CENTER_QUALITY_HOLD` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_CRITICAL_RESULT_REQUIRED` | 409 Conflict |
| `ERR_RADIOLOGIST_NOT_CREDENTIALED` | 422 Unprocessable Entity |
| `ERR_TECH_NOT_CREDENTIALED` | 422 Unprocessable Entity |
| `ERR_ROOM_MODALITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_TECH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_NO_ACCEPTED_SERIES` | 409 Conflict |
| `ERR_SERIES_STILL_CAPTURING` | 409 Conflict |
| `ERR_REJECT_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ALREADY_CLAIMED` | 409 Conflict |
| `ERR_NOT_ASSIGNED_TECH` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_RADIOLOGIST` | 403 Forbidden |
| `ERR_TOO_EARLY_TO_CHECK_IN` | 409 Conflict |
| `ERR_REPORT_NOT_FINAL` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
