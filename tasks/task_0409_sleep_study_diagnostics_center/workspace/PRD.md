# Sleep Diagnostics Center API — Product Requirements Document

## 1. Introduction

The Sleep Diagnostics Center API coordinates the full clinical journey of a patient who is investigated for a sleep-related breathing disorder, from the moment a referring clinician submits a referral through to long-term therapy follow-up. A real diagnostic center juggles several overlapping concerns at once: payers who demand prior authorization before a study may be booked, a finite inventory of physical beds that must be turned over and sanitized between overnight recordings, two fundamentally different study modalities (an attended in-lab polysomnogram versus an unattended home sleep apnea test), a scoring step performed by a technologist and an interpretation step owned by a physician, and finally the durable medical equipment supply chain that issues a CPAP device and tracks whether the patient actually uses it.

This document specifies a back-office system that ties these concerns together with a single, internally consistent set of rules. The central design intent is that no step may run ahead of its prerequisites: a study cannot be scheduled before its referral is authorized, a device cannot be ordered before a physician has interpreted the study and recommended therapy, and a compliance report cannot be filed before the device has shipped. The API also enforces the arithmetic of sleep medicine — the apnea-hypopnea index, severity banding, CMS-style adherence — so that downstream consumers receive derived values that are reproducible and auditable rather than hand-entered. Throughout, the system favors immediate consistency: every state change that affects a parent or sibling resource is applied synchronously within the same operation that triggered it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. Where a rule below names a calculation or a workflow guard, the operational detail of that rule lives in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `SchedulingCoordinator`, `SleepTechnologist`, `Physician`, `DMECoordinator`, and `Patient`.

Four of these roles are operator identities. When `X-User-Role` is `SchedulingCoordinator`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `SleepTechnologist`: `X-User-ID` is an opaque operator identifier, which the server may record — for example, the technologist who submits scoring is captured as `scored_by_tech_id` on the resulting scoring report — but it is never matched against an entity's `id`. When `X-User-Role` is `Physician`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and not compared to any entity's `id`. When `X-User-Role` is `DMECoordinator`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity and not compared to any entity's `id`.

The fifth role is entity-backed. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's patient foreign key to `X-User-ID`. A `Patient` has read-only reach over their own records — their own patient record, their own referrals (which they retrieve by filtering the referral list on their patient identifier), and the studies, follow-ups, compliance records, and other artifacts that descend from those referrals.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the start of the result set; when omitted it defaults to 0, and its minimum accepted value is 0. A `limit` outside its bounds or an `offset` below zero is rejected with `ERR_PAGINATION_INVALID`.

Several list endpoints additionally accept filter query parameters that narrow the result set before pagination is applied. A referral, study-order, DME-order, or bed list may be filtered by `status`; the referral list also accepts `patient_id`; the study-order list accepts `referral_id` and `bed_id`; and the DME-order list accepts `study_order_id` and `supersedes_dme_order_id`. These filters are optional and combine with `limit` and `offset`.

Unless an endpoint explicitly states otherwise, list results are sorted by their creation timestamp in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every persisted entity in this system — `Patient`, `Referral`, `SleepBed`, `StudyOrder`, `ScoringReport`, `DMEOrder`, `ComplianceRecord`, and `FollowUp` — carries a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix; it serves as identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that starts at 1 when the resource is created and increases by exactly 1 on every subsequent mutation. All eight entity types in this system carry the full set; none of them omit `updated_at` or `version`.

The `created_at` timestamp doubles as a deterministic ordering key. For study orders it is the tie-break key used wherever two records would otherwise sort equally, and for DME orders it serves as the lineage tie-break across a resupply chain.

### 2.5. Hierarchical Consistency and Automatic State Propagation

Several state changes in this system do not stop at the resource the client acted upon; they propagate to a parent or to children within the same synchronous operation. When the first study under an authorized referral is scheduled, the referral itself is carried forward from `AUTHORIZED` to `SCHEDULED`. When a study reaches `INTERPRETED`, its parent referral is carried from `SCHEDULED` to `COMPLETED`. When a referral is cancelled, every study beneath it that is still in `ORDERED` or `SCHEDULED` is cancelled as well, and any bed night those studies were holding is released. Each of these propagated changes is a genuine mutation of the affected resource: it refreshes that resource's `updated_at` and increments its `version`. The detailed triggers and guards for each cascade are described in Section 3 alongside the workflow that produces them.

### 2.6. Nested and Filtered Resource Retrieval

This API uses a flat collection topology: the principal resources are peers reached at their own root collections rather than nested under a single tree. Relationships between them are expressed through foreign-key fields carried in request bodies and through filtered list endpoints.

A handful of list endpoints are addressed under a parent identifier — the scoring reports of a study order, the follow-ups of a study order, and the compliance records of a DME order. For these, the path identifier is validated first: if the parent study order or DME order named in the path does not exist, the request fails with the corresponding not-found error before any child lookup is attempted. More generally, when a request carries both a path identifier and foreign-key body fields, existence is validated left to right — the referral first, then the study order, then the scoring report, DME order, or other downstream resource — and the first identifier that fails to resolve determines the not-found error returned (`ERR_REFERRAL_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_SCORING_REPORT_NOT_FOUND`, `ERR_DME_NOT_FOUND`, `ERR_COMPLIANCE_NOT_FOUND`, or `ERR_FOLLOWUP_NOT_FOUND`).

### 2.7. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is predictable. The order is: first, the presence and well-formedness of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_USER_CONTEXT`); second, whether the declared role is permitted for the operation (`ERR_FORBIDDEN_ROLE`); third, the existence of every resource named by a path identifier or a foreign-key body field, validated left to right (the not-found family above); fourth, the structural well-formedness of the request body — required fields present, enumerations valid, and numbers within their declared ranges, such as an Epworth score between 0 and 24 inclusive or a total recording time greater than zero (`ERR_INVALID_REQUEST`); and fifth, whether the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE` and its specific siblings).

Beyond these five, the domain-specific guards run in the following relative order: the cross-entity state gates that require a parent to be in a particular state (priority six); the authorization-expiry check at scheduling (priority seven); the modality-and-bed coherence check (priority eight); the bed-collision and bed-availability check (priority nine); the compliance-window overlap check (priority ten); the CPAP-recommendation gate on DME submission (priority eleven); the scoring-input sufficiency check (priority twelve); the resupply predecessor-integrity check (priority thirteen); and finally the optimistic concurrency version check (priority fourteen). Each guard's trigger condition and error code are described in Section 3 with the workflow it protects.

### 2.8. Clinical Precision and Rounding

The apnea-hypopnea index is the one derived value in this system that carries a fractional part, and it is computed to exactly 1 decimal place using the round-half-up method. Severity banding then compares that one-decimal index against exact integer thresholds. The Epworth improvement and the resupply cycle number are pure integers and are not rounded. Adherence is computed from integer minutes and integer night counts; the only ratio involved is the proportion of qualifying nights, which is treated as an exact real number and compared against its threshold without rounding. The precise formulas and threshold semantics appear in Section 3.

### 2.9. Optimistic Concurrency Control

Three create-or-mutate operations in this system are guarded by optimistic concurrency control, because each acts upon a parent resource whose `version` may have advanced since the client last read it. In every case the guarded request must carry an expected-version field that names the client's last observed `version` of the parent, and a mismatch with the parent's current `version` rejects the request with HTTP 412.

Creating a study order against a referral requires `expected_referral_version` to equal the referral's current `version`. If a prior write — an authorization approval that stamped the authorization number and expiry, or a cancellation — has advanced the referral's `version` since the client read it, the create is refused with `ERR_STALE_REFERRAL_VERSION` so that the client does not act on a referral it has not observed. Submitting scoring against a study requires `expected_study_order_version` to equal the study's current `version`; if a physician return bounced the study back to `IN_PROGRESS` and bumped its `version`, or another technologist already scored it, the submission is refused with `ERR_STALE_STUDY_VERSION`. Creating a resupply DME order — that is, a DME order whose `supersedes_dme_order_id` is set — requires `expected_supersedes_version` to equal the predecessor DME order's current `version`; if another resupply already superseded that predecessor and advanced its `version`, the create is refused with `ERR_STALE_DME_VERSION`. The `expected_supersedes_version` field is required only when `supersedes_dme_order_id` is present; an initial DME order with no predecessor carries neither field.

No other endpoint takes a version field, and the three OCC-guarded endpoints reject a stale version even when every other precondition is satisfied.

## 3. Business Logic & Workflows

### 3.1. Patients and the Inbound Referral

A patient record is the root of the clinical graph and is created by a `SchedulingCoordinator`. The coordinator supplies the patient's `full_name`, their `date_of_birth` as an ISO date in year-month-day form, and the `insurance_payer` whose name the prior-authorization gate later keys on. An optional `baseline_epworth_score` records the patient's pre-treatment Epworth Sleepiness Scale value, an integer from 0 to 24 inclusive; when omitted it defaults to 0. This baseline is retained for later comparison against the post-treatment score at follow-up completion.

A referral represents one clinician's request that this patient undergo a sleep study. The coordinator creates it under a patient by supplying the `patient_id` of the target patient, the `referring_provider_npi` of the requesting clinician, the `requested_modality` the clinician wants — either `IN_LAB_PSG` for an attended in-lab polysomnogram or `HSAT` for a home sleep apnea test — and a free-text `clinical_indication` describing why the study is warranted. The creator may also set `prior_auth_required`, a boolean that declares whether the payer demands authorization before the study can proceed; when omitted it defaults to true. A freshly created referral begins life in `SUBMITTED` status. Two further fields, `prior_auth_number` and `prior_auth_expires_on`, remain null on a new referral; they are populated only when authorization is granted, the latter being the ISO date on which the authorization lapses.

### 3.2. The Prior-Authorization Branch

Every referral must reach `AUTHORIZED` before any study beneath it may be scheduled, but the path there branches on whether the payer requires authorization. A `SchedulingCoordinator` owns the entire authorization workflow.

When a referral requires prior authorization, the coordinator first moves it from `SUBMITTED` to `PENDING_AUTH`. This request is rejected with `ERR_AUTH_NOT_REQUIRED` if the referral's `prior_auth_required` flag is false, because a no-authorization referral must not enter the pending state. Once the payer responds, the coordinator either approves or denies. Approval advances the referral from `PENDING_AUTH` to `AUTHORIZED`; the request body must supply both the `prior_auth_number` and the `prior_auth_expires_on` date, which are persisted onto the referral. Denial advances the referral from `PENDING_AUTH` to `DENIED`, which is terminal and carries no further preconditions.

A referral that does not require prior authorization takes a fast path: from `SUBMITTED` the coordinator approves it directly to `AUTHORIZED` without passing through `PENDING_AUTH`. This direct approval is legal only when the referral's `prior_auth_required` flag is false; a referral that does require authorization must instead travel through the pending state first. As with the pending-state approval, the body must provide both `prior_auth_number` and `prior_auth_expires_on`, which are stamped onto the referral, and the status becomes `AUTHORIZED`. Both approval routes therefore land in the same place with the same persisted fields; they differ only in the originating state.

A coordinator may cancel a referral while it is still in `SUBMITTED`, `PENDING_AUTH`, or `AUTHORIZED`. Cancellation is refused with `ERR_REFERRAL_HAS_ACTIVE_STUDY` if any study under the referral has progressed to `IN_PROGRESS`, `SCORED`, or `INTERPRETED`, because an active clinical study must not be abandoned by cancelling its parent. When cancellation does proceed the referral becomes `CANCELLED`, which is terminal; every study beneath it that is still in `ORDERED` or `SCHEDULED` is cascade-cancelled to `CANCELLED`; and each of those cascade-cancelled studies that was holding a bed night releases that occupancy so the bed becomes bookable for that interval again. Each cascaded study mutation refreshes its own `updated_at` and increments its own `version`.

### 3.3. Bed Inventory

The in-lab modalities require a physical bed, and bed inventory is maintained by the `SchedulingCoordinator`. A bed is created with a human-readable `bed_label` such as a room-and-bed designation. Each bed also carries a `turnover_buffer_minutes` value — the sanitation and turnover gap that must elapse after each booked night before the next night on that bed may begin — which must be zero or greater and defaults to 60 when omitted. A new bed starts in `AVAILABLE` status. A coordinator may mark a bed `OUT_OF_SERVICE`, after which it can no longer accept new bookings.

### 3.4. Ordering a Study

With an authorized referral in hand, a `SchedulingCoordinator` creates a study order. The create body names the parent referral through its `referral_id`, declares the `modality` of the study, and carries the optimistic-concurrency field `expected_referral_version`. The modality is one of three values: `IN_LAB_PSG`, `HSAT`, or `IN_LAB_TITRATION`. The third value denotes a CPAP titration study, which is an in-lab study used to find the patient's optimal therapeutic pressure. A newly created study begins in `ORDERED` status.

Study creation acts upon the referral and is therefore protected by optimistic concurrency: `expected_referral_version` must equal the referral's current `version`, and on a mismatch the create is rejected with `ERR_STALE_REFERRAL_VERSION` as described in the concurrency section. A successful create also advances the referral's own `version` by 1, reflecting that the referral has been mutated by the act of acquiring a child study. The study's `bed_id`, `night_start_utc`, and `night_end_utc` are not set at creation; they remain null until the study is scheduled. An unscheduled mail-out home test likewise carries no night window until that point.

### 3.5. Scheduling a Study and the Bed-Booking Discipline

Scheduling is the step that fixes a study to a calendar slot, and for in-lab studies to a specific bed, and it is the gate that enforces the largest cluster of business rules in the system. A `SchedulingCoordinator` schedules a study by supplying the `night_start_utc` and `night_end_utc` of the booked overnight recording, and, for in-lab studies, the `bed_id` of the chosen bed. A successful schedule persists the night window and bed onto the study and advances it from `ORDERED` to `SCHEDULED`. If at that moment the parent referral is still `AUTHORIZED`, scheduling also carries the referral forward to `SCHEDULED` — the first hop of the bubble-up cascade between a child study and its parent.

Several guards stand in front of a successful schedule. The parent referral must be in `AUTHORIZED` status; if it is not, scheduling is refused with `ERR_REFERRAL_NOT_AUTHORIZED`. The authorization must not have lapsed: when the referral carries a `prior_auth_expires_on` date, the date portion of `night_start_utc` must be on or before that expiry date, and a night that starts after the authorization has expired is rejected with `ERR_AUTH_EXPIRED`; when `prior_auth_expires_on` is null this check is skipped. The night window itself must be well-formed, meaning `night_end_utc` must be strictly later than `night_start_utc`; otherwise the request is rejected with `ERR_INVALID_NIGHT_WINDOW`.

Modality and bed must be coherent. An in-lab study — whether `IN_LAB_PSG` or `IN_LAB_TITRATION` — requires a `bed_id`; scheduling such a study without one is rejected with `ERR_BED_REQUIRED`. A home test requires the opposite: an `HSAT` study must be scheduled with no `bed_id` at all, and supplying one is rejected with `ERR_HSAT_BED_NOT_ALLOWED`. For an in-lab study the named bed must be bookable: a bed in `OUT_OF_SERVICE` status is rejected with `ERR_BED_OUT_OF_SERVICE`, and the requested night must not collide with any other night already booked on that same bed. The collision test is not a naive interval overlap — it must also honor the bed's `turnover_buffer_minutes`, which is treated as a mandatory gap inserted after each existing booked night. In other words, the new night conflicts not only when it overlaps an existing night directly but also when it begins within the turnover buffer that trails an existing night. A collision under this rule is rejected with `ERR_BED_DOUBLE_BOOKED`. When a study that held a bed is later cancelled or cascade-cancelled, the night it occupied — together with its trailing buffer — is released and becomes bookable again.

### 3.6. Recording and Scoring

Once a study is scheduled, a `SleepTechnologist` begins the overnight recording, advancing the study from `SCHEDULED` to `IN_PROGRESS`. This transition is legal only from `SCHEDULED`.

When the recording is complete the technologist submits scoring, advancing the study from `IN_PROGRESS` to `SCORED`. The scoring body carries the `total_recording_minutes` actually recorded, the `respiratory_event_count` of apnea and hypopnea events observed, the optimistic-concurrency field `expected_study_order_version`, and — for a titration study only — the `titration_optimal_cmh2o`, the optimal CPAP pressure in centimeters of water found during the night. Scoring is legal only from `IN_PROGRESS`. The recording must be sufficient: `total_recording_minutes` must be greater than zero, and a non-positive value is rejected with `ERR_INSUFFICIENT_RECORDING`, while `respiratory_event_count` must be zero or greater. A titration study additionally requires a `titration_optimal_cmh2o` greater than zero; a titration scored without it is rejected with `ERR_TITRATION_PRESSURE_REQUIRED`. Because scoring mutates the study, it is OCC-guarded: `expected_study_order_version` must equal the study's current `version`, and a mismatch is rejected with `ERR_STALE_STUDY_VERSION`.

A successful scoring does several things at once. It recomputes the study's apnea-hypopnea index and its severity band (both defined below), advances the study to `SCORED`, increments the study's `version` by 1, and creates a fresh scoring report in `DRAFT` status linked to the study through its `study_order_id`. That report captures the identity of the scoring technologist in `scored_by_tech_id` — an audit string drawn from the technologist's `X-User-ID`, not an entity foreign key — and snapshots the just-computed index and severity into its `ahi_snapshot` and `severity_snapshot` fields.

The apnea-hypopnea index, written onto the study's `ahi` field, expresses respiratory events per hour of recording. It is computed with a pinned evaluation order: first the recording hours are obtained by dividing `total_recording_minutes` by 60 as an exact division with no intermediate rounding, and then the index is obtained by dividing `respiratory_event_count` by those recording hours and rounding the quotient to 1 decimal place using round-half-up. The divide-then-round order is mandatory; rounding the recording hours before dividing would yield a different index. The same value is copied into the scoring report's `ahi_snapshot`.

The study's `severity` field is then banded from that one-decimal index using thresholds that are inclusive at the lower edge, so an exact boundary value lands in the higher band. An index below 5 is `NONE`. An index of at least 5 but below 15 is `MILD`, so an index of exactly 5.0 is `MILD`. An index of at least 15 but below 30 is `MODERATE`, so an index of exactly 15.0 is `MODERATE`. An index of 30 or above is `SEVERE`, so an index of exactly 30.0 is `SEVERE`. The resulting band is copied into the scoring report's `severity_snapshot`.

### 3.7. Physician Interpretation and the Return Loop

A scoring report sits in `DRAFT` awaiting a `Physician`, who either finalizes it or returns it for rework. Both actions are legal only while the linked study is in `SCORED`.

Returning a report sends it from `DRAFT` to `RETURNED` and, in the same operation, reverts the linked study from `SCORED` back to `IN_PROGRESS`, bumping that study's `version`. This is the deliberate revert loop: a physician who is unsatisfied kicks the work back to the technologist, who re-records or re-scores and, on the next successful scoring, produces a new `DRAFT` report. A study may therefore cycle through `SCORED` and back to `IN_PROGRESS` several times before it is finally interpreted.

Interpreting a report finalizes it. The physician supplies the `interpretation_text`, which must be non-empty, and the boolean `physician_recommends_cpap` indicating whether CPAP therapy is recommended; when omitted this flag defaults to false. Interpretation is legal only when the report is in `DRAFT` and its linked study is in `SCORED`. On success the interpretation text and the recommendation flag are persisted, the report advances from `DRAFT` to `FINALIZED`, the linked study advances from `SCORED` to `INTERPRETED` (a terminal study state), and the parent referral bubbles up from `SCHEDULED` to `COMPLETED` (a terminal referral state). Each of these propagated mutations refreshes the affected resource's `updated_at` and increments its `version`.

### 3.8. Cancelling a Study

Independent of the referral-level cascade, a `SchedulingCoordinator` may cancel an individual study while it is in either `ORDERED` or `SCHEDULED`. A cancellation attempted from any other state is rejected with `ERR_STUDY_NOT_CANCELLABLE`. A successful cancel moves the study to `CANCELLED`, which is terminal, and if the study was holding a bed night, that occupancy — including its trailing turnover buffer — is released so the interval becomes bookable again.

### 3.9. Durable Medical Equipment and the Resupply Chain

Once a study is interpreted with a CPAP recommendation, the `DMECoordinator` takes over to issue and track the device. A DME order is created by naming the justifying study through its `study_order_id`, the `device_type` to be supplied — one of `CPAP`, `APAP`, or `BIPAP` — and the `prescribed_pressure_cmh2o`, which must be greater than zero. A new DME order begins in `DRAFT` status.

An order may be either an initial order or a resupply that replaces an earlier device. A resupply names the order it replaces through `supersedes_dme_order_id` and carries the optimistic-concurrency field `expected_supersedes_version`. Resupply integrity is enforced: the predecessor named by `supersedes_dme_order_id` must itself be in `FULFILLED` status and must share the same `study_order_id` as the new order; a predecessor that is not fulfilled, or that belongs to a different study, is rejected with `ERR_RESUPPLY_PREDECESSOR_INVALID`. Because a resupply mutates its predecessor, it is OCC-guarded — `expected_supersedes_version` must equal the predecessor's current `version`, failing with `ERR_STALE_DME_VERSION` — and a successful resupply increments the predecessor's `version` by 1.

The `resupply_cycle_number` is a derived integer that records where an order sits in its lineage. An order with no predecessor — an initial order — has a cycle number of 1. A resupply's cycle number is its predecessor's `resupply_cycle_number` plus 1. Because each resupply points at exactly one earlier, already-persisted order, the chain is acyclic and the cycle numbers are well-defined when evaluated in lineage order.

The DME order then moves through its own lifecycle, all under the `DMECoordinator`. Submitting an order advances it from `DRAFT` to `SUBMITTED`, but only when the linked study is in `INTERPRETED` status — a submission against a study that is not interpreted is rejected with `ERR_STUDY_NOT_INTERPRETED` — and only when that study's `FINALIZED` scoring report carries `physician_recommends_cpap` equal to true; a submission for a study whose interpretation did not recommend CPAP is rejected with `ERR_CPAP_NOT_RECOMMENDED`. Fulfilling an order advances it from `SUBMITTED` to `FULFILLED`, marking the device as shipped and thereby making it eligible to receive compliance records and to be superseded by a resupply. An order may be cancelled while it is in `DRAFT` or `SUBMITTED`; a cancel attempted from any other state is rejected with `ERR_DME_NOT_CANCELLABLE`, and a successful cancel moves the order to `CANCELLED`.

### 3.10. Compliance Reporting and Adherence

After a device has been fulfilled, the `DMECoordinator` files compliance downloads that report how the patient is actually using the equipment. A compliance record names the fulfilled device through its `dme_order_id` and describes one observation window: the inclusive `window_start_utc`, the exclusive `window_end_utc` (which must be strictly later than the start), the `nights_used_4h_plus` count of nights in the window on which the device ran at least four hours, and the `total_usage_minutes` summed across the window. Both counts must be zero or greater. A new window must not overlap any existing compliance window for the same device; windows are treated as half-open intervals where touching endpoints do not constitute an overlap, and a true overlap is rejected with `ERR_COMPLIANCE_WINDOW_OVERLAP`.

Each record carries a derived `adherent` boolean computed against a CMS-style threshold with a pinned evaluation order. First the window length is established as the number of whole calendar days spanned, obtained by taking the difference between `window_end_utc` and `window_start_utc` in seconds, dividing by the number of seconds in a day, and rounding down to a whole number of days. This window-length gate is evaluated first: if the window spans fewer than 30 days, the record is non-adherent and the usage clauses are not evaluated at all. When the window is at least 30 days long, three conditions must all hold for the record to be adherent. There must be at least 21 nights with four or more hours of use. Those qualifying nights, taken as a proportion of the window days, must be at least 0.70 — that is, the qualifying-night count divided by the window-day count must be at least seventy percent. And the average usage on the qualifying nights, computed as `total_usage_minutes` divided by `nights_used_4h_plus` (taken as zero when there are no qualifying nights), must be at least 240 minutes. Only when the window is long enough and all three usage conditions hold is the record marked adherent; otherwise it is not. Adherence is recomputed whenever a record's inputs change.

### 3.11. Follow-Up and Symptom Improvement

The final stage tracks whether therapy actually helped. A `SchedulingCoordinator` schedules a follow-up against an interpreted study by naming it through `study_order_id` and supplying the `scheduled_for_utc` appointment time; the study must be in `INTERPRETED` status for a follow-up to be scheduled. A new follow-up begins in `SCHEDULED` status.

A scheduled follow-up resolves one of three ways, all driven by the coordinator. It may be marked a no-show, moving from `SCHEDULED` to `NO_SHOW`. It may be cancelled, moving from `SCHEDULED` to `CANCELLED`. Or it may be completed, moving from `SCHEDULED` to `COMPLETED`; completion requires the `post_treatment_epworth_score`, an integer from 0 to 24 inclusive measured after treatment. All three transitions are legal only from `SCHEDULED`.

On completion the system records the post-treatment score and derives the patient's `epworth_improvement` — the symptom change between baseline and treatment. The improvement is the patient's `baseline_epworth_score` minus the `post_treatment_epworth_score`, so a positive result indicates the patient's daytime sleepiness improved; the value may be negative if symptoms worsened. The baseline is pulled from the patient by walking the chain from the follow-up to its study, from the study to its referral, and from the referral to the patient who owns it. The derived value is stored on the follow-up and remains null until completion.

## 4. Endpoint Definitions

Operations that create a brand-new resource return a `201 Created` status code. Operations that modify or transition an existing resource, including the lifecycle action endpoints, return a `200 OK` status code. Every endpoint emits the standard response envelope, and the request body and side effects for each action are specified in the Section 3 narrative rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patients` | Create a patient | SchedulingCoordinator |
| GET | `/patients/{patientId}` | Get a patient | SchedulingCoordinator, Physician, DMECoordinator, Patient |
| POST | `/referrals` | Create a referral for a patient | SchedulingCoordinator |
| GET | `/referrals` | List referrals (filterable by patient_id) | SchedulingCoordinator, Physician, DMECoordinator, Patient |
| GET | `/referrals/{referralId}` | Get a referral | SchedulingCoordinator, Physician, DMECoordinator, Patient |
| POST | `/referrals/{referralId}/request-auth` | Move a referral to PENDING_AUTH | SchedulingCoordinator |
| POST | `/referrals/{referralId}/approve-auth` | Authorize a referral | SchedulingCoordinator |
| POST | `/referrals/{referralId}/deny-auth` | Deny prior authorization | SchedulingCoordinator |
| POST | `/referrals/{referralId}/cancel` | Cancel a referral and cascade-cancel its non-active studies | SchedulingCoordinator |
| POST | `/beds` | Create a sleep bed resource | SchedulingCoordinator |
| GET | `/beds` | List sleep beds | SchedulingCoordinator, SleepTechnologist |
| GET | `/beds/{bedId}` | Get a sleep bed | SchedulingCoordinator, SleepTechnologist |
| POST | `/beds/{bedId}/set-out-of-service` | Mark a bed OUT_OF_SERVICE | SchedulingCoordinator |
| POST | `/study-orders` | Create a study order under an authorized referral | SchedulingCoordinator |
| GET | `/study-orders` | List study orders (filterable by referral_id or bed_id) | SchedulingCoordinator, SleepTechnologist, Physician, DMECoordinator |
| GET | `/study-orders/{studyOrderId}` | Get a study order | SchedulingCoordinator, SleepTechnologist, Physician, DMECoordinator |
| POST | `/study-orders/{studyOrderId}/schedule` | Schedule a study (book a bed night for in-lab; mail-out for HSAT) | SchedulingCoordinator |
| POST | `/study-orders/{studyOrderId}/start` | Begin the recording | SleepTechnologist |
| POST | `/study-orders/{studyOrderId}/score` | Submit scoring metrics; compute AHI and severity | SleepTechnologist |
| POST | `/study-orders/{studyOrderId}/cancel` | Cancel an ORDERED/SCHEDULED study; release any held bed night | SchedulingCoordinator |
| GET | `/study-orders/{id}/scoring-reports` | List scoring reports for a study order | SchedulingCoordinator, SleepTechnologist, Physician, DMECoordinator |
| GET | `/study-orders/{id}/follow-ups` | List follow-ups for a study order | SchedulingCoordinator, Physician, DMECoordinator, Patient |
| GET | `/scoring-reports/{scoringReportId}` | Get a scoring report | SchedulingCoordinator, SleepTechnologist, Physician, DMECoordinator |
| POST | `/scoring-reports/{scoringReportId}/interpret` | Finalize interpretation; study to INTERPRETED | Physician |
| POST | `/scoring-reports/{scoringReportId}/return` | Return a draft for re-scoring; study to IN_PROGRESS | Physician |
| POST | `/dme-orders` | Create a DME order (initial or resupply) | DMECoordinator |
| GET | `/dme-orders` | List DME orders (filterable by study_order_id or supersedes_dme_order_id) | SchedulingCoordinator, Physician, DMECoordinator |
| GET | `/dme-orders/{dmeOrderId}` | Get a DME order | SchedulingCoordinator, Physician, DMECoordinator |
| POST | `/dme-orders/{dmeOrderId}/submit` | Submit a DME order (requires interpreted study + CPAP recommended) | DMECoordinator |
| POST | `/dme-orders/{dmeOrderId}/fulfill` | Mark a DME order FULFILLED (device shipped) | DMECoordinator |
| POST | `/dme-orders/{dmeOrderId}/cancel` | Cancel a DRAFT/SUBMITTED DME order | DMECoordinator |
| GET | `/dme-orders/{id}/compliance-records` | List compliance records for a DME order | SchedulingCoordinator, Physician, DMECoordinator, Patient |
| POST | `/compliance-records` | Upload a compliance-download window for a fulfilled DME order | DMECoordinator |
| GET | `/compliance-records/{complianceRecordId}` | Get a compliance record | SchedulingCoordinator, Physician, DMECoordinator, Patient |
| POST | `/follow-ups` | Schedule a follow-up for an interpreted study | SchedulingCoordinator |
| GET | `/follow-ups/{followUpId}` | Get a follow-up | SchedulingCoordinator, Physician, DMECoordinator, Patient |
| POST | `/follow-ups/{followUpId}/complete` | Complete a follow-up; record post-treatment Epworth and improvement | SchedulingCoordinator |
| POST | `/follow-ups/{followUpId}/no-show` | Mark a follow-up as NO_SHOW | SchedulingCoordinator |
| POST | `/follow-ups/{followUpId}/cancel` | Cancel a scheduled follow-up | SchedulingCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_NIGHT_WINDOW` | 422 Unprocessable Entity |
| `ERR_PAGINATION_INVALID` | 422 Unprocessable Entity |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_BED_NOT_FOUND` | 404 Not Found |
| `ERR_STUDY_NOT_FOUND` | 404 Not Found |
| `ERR_SCORING_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_DME_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLIANCE_NOT_FOUND` | 404 Not Found |
| `ERR_FOLLOWUP_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AUTH_NOT_REQUIRED` | 409 Conflict |
| `ERR_STUDY_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DME_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_REFERRAL_HAS_ACTIVE_STUDY` | 409 Conflict |
| `ERR_REFERRAL_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_STUDY_NOT_INTERPRETED` | 409 Conflict |
| `ERR_RESUPPLY_PREDECESSOR_INVALID` | 409 Conflict |
| `ERR_AUTH_EXPIRED` | 409 Conflict |
| `ERR_BED_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_BED_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_COMPLIANCE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BED_REQUIRED` | 422 Unprocessable Entity |
| `ERR_HSAT_BED_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_RECORDING` | 422 Unprocessable Entity |
| `ERR_TITRATION_PRESSURE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CPAP_NOT_RECOMMENDED` | 409 Conflict |
| `ERR_STALE_REFERRAL_VERSION` | 412 Precondition Failed |
| `ERR_STALE_STUDY_VERSION` | 412 Precondition Failed |
| `ERR_STALE_DME_VERSION` | 412 Precondition Failed |
