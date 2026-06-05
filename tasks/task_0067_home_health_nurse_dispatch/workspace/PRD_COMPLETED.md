# Home Health Nurse Dispatch API — Product Requirements Document

## 1. Introduction

Home health agencies live or die by the accuracy of two intertwined records: the clinical care a patient actually received, and the Medicare reimbursement that care earns. This API backs the operational spine of such an agency — from the moment a registered nurse performs an OASIS assessment in a patient's living room, through the dispatch of skilled nursing, physical, occupational, and speech therapy visits, the booking of home health aide companion hours, the tracking of clinician travel mileage, and finally the settlement of a 60-day Medicare certification episode under the Patient-Driven Groupings Model (PDGM).

The central organizing object is the **episode**: a 60-day window of certified care opened from a START_OF_CARE OASIS assessment and closed when billing finalizes its payment. Around each episode orbit the plan of care that orders visits, the individual discipline visits and companion shifts that deliver care, the mileage claims that reimburse travel, the recertification requests that extend care past sixty days, and an immutable audit log of everything that happened. Five operator roles — intake, clinical, scheduling, billing, and compliance — each own a slice of this lifecycle, and the system must keep their views consistent even when two of them touch the same episode in close succession.

Because the dollars at stake are real and audited, this specification is unusually strict about *when* a number is computed and *which* inputs feed it. A forward-looking provisional payment estimate, recomputed as the plan and visits evolve, must never be confused with the chronological actual settlement computed only from completed visits at discharge. The two can legitimately diverge for the same episode, and the system must report both faithfully.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is absent, or if `X-User-Role` is not one of the five recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation per the authorization rules described throughout this document and summarized in §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles are spelled exactly `IntakeCoordinator`, `Clinician`, `Scheduler`, `BillingManager`, and `ComplianceOfficer`. An `IntakeCoordinator` creates patients, records OASIS assessments, opens, activates, and cancels episodes, creates plans of care, opens recertification requests, and resubmits returned recerts. A `Clinician` confirms and completes the visits they are personally assigned and files mileage claims against those visits. A `Scheduler` schedules, cancels, and marks-missed visits and books, delivers, and cancels companion shifts. A `BillingManager` manages PDGM rate configurations, finalizes and reopens episodes, and approves or rejects mileage claims. A `ComplianceOfficer` approves, returns, or denies recertification requests.

Identity binding differs by role. When `X-User-Role` is `Clinician`, `X-User-ID` is the `id` of the acting `Clinician` entity; ownership checks on any resource that references a `Clinician` compare the resource's foreign-key field to `X-User-ID`. Concretely, for the two clinician-owned actions — confirming a visit and completing a visit — the acting `X-User-ID` must equal the visit's `clinician_id`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `IntakeCoordinator`, `Scheduler`, `BillingManager`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts and may log it but never compares it to any entity's `id`.

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

All collection-returning endpoints are paginated through two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. Collections are always sorted by `created_at` in ascending order, so the earliest-created record appears first. Each paginated response surfaces its pagination state inside the `meta` object through four fields: `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (a boolean indicating whether records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned an `id` that is a server-minted UUID carrying no type prefix. Every resource also records a `created_at` timestamp in ISO 8601 UTC form with three fractional-second digits, set once when the resource is first persisted and never altered thereafter.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `version` starts at 1 on creation and increases by exactly 1 on every mutation of that resource; `updated_at` is refreshed to the server clock whenever the resource changes. These versioned resources are `Patient`, `Clinician`, `OASISAssessment`, `Episode`, `PlanOfCare`, `Visit`, `CompanionShift`, `MileageClaim`, `RecertRequest`, and `PaymentLedger`. Two resource types are deliberately lightweight: `PdgmRateConfig` and `EpisodeEvent` carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field, because they are write-once configuration and audit records that are never individually mutated after creation.

### 2.5. Nested Resource Resolution

Many resources are addressed through nested paths — a plan of care, visit, companion shift, recert request, event log, or mileage claim is reached through its parent. Path segments are resolved strictly left to right, and the first segment whose referenced resource does not exist causes the request to fail immediately with `ERR_NOT_FOUND` (HTTP 404). The same existence rule covers any resource referenced in the request body. This left-to-right discipline means that if both a parent and a child id are invalid, the parent's absence is reported first.

### 2.6. Episode Version Propagation and Cascading Effects

The `Episode` is the consistency anchor of the whole system. Many child operations are designed to bump the parent episode's `version`: activating an episode, creating a new plan of care, opening a recertification request, approving or denying a recert, finalizing, reopening, and cancelling all increment `Episode.version` by 1 and refresh its `updated_at`. State transitions on a child resource (a visit, companion shift, or mileage claim) increment that child's own `version` by 1, and several of them additionally fold values into the episode's running computed totals as described in §3.

Two cascades deserve emphasis here because they touch more than one record at once. Cancelling a DRAFT episode sets every `ACTIVE` plan of care on that episode to `SUPERSEDED`, unlocks the START_OF_CARE OASIS that seeded it so that a corrected episode can later reuse it, appends a CANCELLED audit event, and bumps the episode version. Creating a new plan of care supersedes the previously `ACTIVE` plan (setting it to `SUPERSEDED` and appending a PLAN_SUPERSEDED event) before the new plan is persisted as the single `ACTIVE` plan, then recomputes the episode's provisional payment and bumps the episode version.

### 2.7. Optimistic Concurrency on Plan Creation

Creating a plan of care is the one operation guarded by optimistic concurrency control. The create-plan-of-care request must carry a non-optional `expected_episode_version` field holding the client's last-observed `version` of the target `Episode`. Before the new plan is written, the server compares `expected_episode_version` to the episode's current `version`. If a different writer has advanced the episode's version since the client last read it — for example, because another plan was already created and superseded the one the client believed was active — the create is rejected with `ERR_STALE_EPISODE_VERSION` (HTTP 412), preventing the client from overwriting a plan it has never observed. If the `expected_episode_version` field is missing entirely from the request body, that is a malformed request and is rejected with `ERR_VERSION_REQUIRED` (HTTP 400). No other endpoint accepts or requires a version field.

### 2.8. Monetary Precision and Rounding

All monetary and mileage amounts are carried to 2 decimal places and rounded half-up at each rounding point specified in §3. Where a calculation rounds intermediate results, the rounding happens exactly where stated; in particular, companion-shift cost is rounded once per shift to the cent and only then summed, which can differ in the last cent from summing raw hours and multiplying once. Visit and companion-shift weekly-capacity counts are plain integers.

## 3. Business Logic & Workflows

### 3.1. Establishing the Roster: Patients, Clinicians, OASIS, and Rates

Care begins with reference data. An `IntakeCoordinator` registers a patient by supplying the patient's `full_name`, a `medicare_id`, a residential `home_zip`, and the residence coordinates `home_lat` and `home_lon`. The `medicare_id` must be non-empty and unique across all patients, and `home_zip` must consist of exactly five digits; violations of body shape, type, or these constraints are rejected with `ERR_VALIDATION` (HTTP 400). A newly created patient begins life with `status` of `ACTIVE`. Whenever a patient is read back, the system computes `open_episode_id`: the `id` of the single episode belonging to that patient whose status is currently one of `DRAFT`, `ACTIVE`, or `RECERT_PENDING`, or null when the patient has no such episode.

A `Scheduler` onboards clinicians. Each clinician record carries a `full_name`, a `discipline` drawn from `RN`, `PT`, `OT`, `SLP`, or `HHA`, a `license_active` flag that defaults to true, the home-base coordinates `base_lat` and `base_lon` from which travel mileage is measured, and a `weekly_visit_cap` that defaults to 40 and must be at least 1. A clinician's `license_active` or `weekly_visit_cap` may later be revised, which increments that clinician's version.

The clinical order source is the OASIS assessment, recorded by an `IntakeCoordinator`. An assessment names the assessed patient via `patient_id`, the performing RN via `clinician_id`, an `assessment_type` of either `START_OF_CARE` or `RECERTIFICATION`, the `assessment_date` that anchors the episode, a PDGM `clinical_group` from `MMTA_OTHER`, `WOUND`, `NEURO_REHAB`, `COMPLEX_NURSING`, or `MS_REHAB`, a `functional_level` of `LOW`, `MEDIUM`, or `HIGH`, and a `comorbidity_count` of zero or greater. Every assessment is created with `locked` set to false; it becomes locked once an episode create or recert consumes it, and a locked assessment can no longer seed another episode.

Reimbursement rates live in PDGM rate configurations, owned by the `BillingManager`. Each configuration row applies to one `clinical_group` and carries a `base_30day_rate` greater than zero, three case-mix multipliers `functional_weight_low`, `functional_weight_medium`, and `functional_weight_high` selected according to the episode's functional level, a `lupa_threshold` of at least 1, and an `active` flag defaulting to true. At most one active configuration row may exist per clinical group, and the active row is the one consulted whenever payment is computed.

### 3.2. Opening and Activating an Episode

An `IntakeCoordinator` opens a 60-day episode from a START_OF_CARE assessment. The create payload names the patient via `patient_id`, the seeding assessment via `soc_oasis_id`, and optionally the immediately preceding episode in a recertification chain via `prior_episode_id` (null for a patient's first episode). On creation the system copies `clinical_group` and `functional_level` from the seeding OASIS onto the episode, sets `cert_start` equal to that assessment's `assessment_date`, sets `cert_end` to the last day of the window — that is, `cert_start` plus 59 days inclusive — copies the `lupa_threshold` from the active rate configuration for the episode's clinical group (defaulting to 1 when no active configuration exists for that group), locks the seeding OASIS, and leaves the episode in `DRAFT` status. The seeding assessment must be of type `START_OF_CARE`, must belong to the same patient, and must not already be locked; otherwise the create fails with `ERR_OASIS_INVALID` (HTTP 422). Because a patient may have at most one non-terminal episode at a time, an attempt to open an episode for a patient who already holds a `DRAFT`, `ACTIVE`, or `RECERT_PENDING` episode is rejected with `ERR_PATIENT_HAS_OPEN_EPISODE` (HTTP 409).

Before care can be dispatched, the `IntakeCoordinator` must attach a plan and activate the episode. Activation drives the episode `DRAFT → ACTIVE`. It requires that the episode hold exactly one `ACTIVE` plan of care; if no such plan exists, activation fails with `ERR_PLAN_REQUIRED` (HTTP 422). Activation further requires that the `soc_oasis_id` reference a `START_OF_CARE` assessment and that the patient have no other non-terminal episode (the patient's open episode must be this one). On success, activation appends an ACTIVATED audit event, recomputes the episode's forward-looking provisional payment from the active plan, and bumps the episode version. Activation is the gate that allows visits to be scheduled.

A DRAFT episode that was opened in error can instead be cancelled by the `IntakeCoordinator`, driving `DRAFT → CANCELLED`. Cancellation is permitted only while the episode is in `DRAFT`; it supersedes every `ACTIVE` plan on the episode, unlocks the seeding OASIS so it can seed a corrected episode, appends a CANCELLED event, and bumps the episode version. Both `DISCHARGED` and `CANCELLED` are terminal states for an episode.

### 3.3. The Plan of Care and the Provisional Estimate

A plan of care expresses the physician's order in terms of intended visit counts. The `IntakeCoordinator` creates it against an episode with `planned_rn_visits`, `planned_pt_visits`, `planned_ot_visits`, and `planned_slp_visits` — each a non-negative integer — together with `companion_hours_authorized`, a non-negative number of home health aide hours, and the `expected_episode_version` discussed in §2.7. The plan is stored with `status` of `ACTIVE`, and only one plan per episode may be `ACTIVE` at a time; the prior active plan, if any, transitions `ACTIVE → SUPERSEDED` and a PLAN_SUPERSEDED event is appended. Creating a plan recomputes the episode's provisional payment and bumps the episode version.

The **provisional payment**, stored on the episode as `provisional_payment`, is a forward-looking estimate, recomputed on episode activation, on every plan create or supersede, and on each visit completion. It assumes every planned visit will be delivered, so the Low Utilization adjustment never applies in this forward view. The computation proceeds as follows. First, the planned total is the sum of `planned_rn_visits`, `planned_pt_visits`, `planned_ot_visits`, and `planned_slp_visits`. Next, the case-mix amount is the active configuration's `base_30day_rate` multiplied by the functional weight chosen for the episode's functional level (the low, medium, or high weight) and then multiplied by a comorbidity multiplier. The comorbidity multiplier is exactly 1.00 when the seeding OASIS `comorbidity_count` equals zero; it is 1.06 when that count is 1 or 2; and it is 1.18 when that count is 3 or greater. Finally, if the planned total is greater than or equal to the episode's `lupa_threshold`, the provisional payment is the case-mix amount multiplied by 2 (the episode spans two 30-day periods), rounded half-up to two decimal places; otherwise the provisional payment is a flat per-visit rate of $165.00 multiplied by the planned total, rounded half-up to two decimal places. The estimate always reflects the single `ACTIVE` plan's planned counts, regardless of how many actual visits exist or what state they are in.

### 3.4. Dispatching, Confirming, and Closing Out Visits

Once an episode is `ACTIVE`, a `Scheduler` schedules discipline visits against it. A scheduled visit names the assigned clinician via `clinician_id`, the `discipline` it bills under (`RN`, `PT`, `OT`, or `SLP`), and a half-open time window from `scheduled_start` inclusive to `scheduled_end` exclusive. The visit is created in `SCHEDULED` status with `billable` false. Scheduling requires the parent episode to be `ACTIVE`; attempting it against any other episode state yields `ERR_EPISODE_NOT_ACTIVE` (HTTP 409). The visit's `discipline` must match the assigned clinician's own discipline, or the request is rejected with `ERR_DISCIPLINE_MISMATCH` (HTTP 422). The window must satisfy `scheduled_start` strictly before `scheduled_end`, and both ends must fall within the episode's `cert_start` through `cert_end` window inclusive; otherwise the schedule fails with `ERR_VISIT_OUT_OF_CERT_WINDOW` (HTTP 422). The new window must also not overlap any non-terminal visit already held by the same clinician — because the interval is half-open, a visit ending exactly when another begins is permitted, but any true overlap is rejected with `ERR_CLINICIAN_DOUBLE_BOOKED` (HTTP 409).

Capacity is governed by the clinician's weekly cap. A clinician may hold at most `weekly_visit_cap` visits in `CONFIRMED` or `COMPLETED` status within any single ISO week, where a week runs from Monday at 00:00 UTC up to the following Monday at 00:00 UTC, and a visit belongs to the week containing its `scheduled_start`. The capacity check counts the clinician's existing `CONFIRMED` and `COMPLETED` visits in the relevant week, excluding the visit under test, and rejects the operation when adding one more would carry the count above the cap; the rejection is `ERR_WEEKLY_CAP_EXCEEDED` (HTTP 422). This same capacity rule is evaluated both when a visit is scheduled and when a clinician confirms one.

A `Clinician` confirms an assigned visit, driving `SCHEDULED → CONFIRMED`, which reserves the clinician's weekly capacity slot. Confirmation requires that the acting clinician be the visit's assigned `clinician_id`, that the parent episode be `ACTIVE`, and that the clinician's `license_active` be true. An inactive license is rejected with `ERR_LICENSE_INACTIVE` (HTTP 422); a non-active episode with `ERR_EPISODE_NOT_ACTIVE`; and a stranger attempting another clinician's visit with `ERR_NOT_RESOURCE_OWNER`. The same clinician later completes the visit, driving `CONFIRMED → COMPLETED`, but only after the visit window has elapsed — that is, `scheduled_end` is at or before the current server clock — and only while they are the assigned clinician and the episode remains `ACTIVE`. Completion sets `billable` true, recomputes the episode's provisional payment to reflect the now-completed visit, appends a VISIT_COMPLETED event, and bumps the visit version.

Two divergent off-ramps exist from a confirmed visit. The `Scheduler` may mark a confirmed visit missed, driving `CONFIRMED → MISSED`; this is allowed once the window has elapsed (`scheduled_end` at or before the current server clock), sets `billable` false, releases the clinician's weekly-cap slot, appends a VISIT_MISSED event, and bumps the visit version. A missed visit never bills — this is the deliberate contrast with completion, which both bills and feeds payment. Separately, the `Scheduler` may cancel a visit that is in either `SCHEDULED` or `CONFIRMED` status, driving it to `CANCELLED`; cancellation releases the clinician's weekly-cap slot and bumps the visit version. `COMPLETED`, `MISSED`, and `CANCELLED` are all terminal for a visit. Any attempt to drive a transition from a state that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.5. Companion Hours

Home health aide companion coverage is booked separately. A `Scheduler` books a companion shift against an `ACTIVE` episode by naming the aide via `clinician_id` and a half-open window from `shift_start` inclusive to `shift_end` exclusive. The referenced clinician's discipline must be `HHA`, or the booking is rejected with `ERR_DISCIPLINE_MISMATCH` (HTTP 422); the parent episode must be `ACTIVE`, failing which yields `ERR_EPISODE_NOT_ACTIVE` (HTTP 409). The window must satisfy `shift_start` strictly before `shift_end`, or the booking is rejected with `ERR_VALIDATION` (HTTP 400). The shift's `hours` is computed from its duration — the difference between `shift_end` and `shift_start` expressed in hours, rounded to two decimal places. The shift is created in `BOOKED` status. A new shift must not overlap any non-terminal companion shift on the same patient's episode, and consecutive shifts of the same aide must respect a travel buffer of half an hour (30 minutes) between one shift's end and the next shift's start; a violation of either constraint is rejected with `ERR_COMPANION_SHIFT_CONFLICT` (HTTP 409).

When the aide has worked the shift, the `Scheduler` marks it delivered, driving `BOOKED → DELIVERED`. Delivery is permitted only once the shift window has elapsed (`shift_end` at or before the current server clock) and only while the parent episode is `ACTIVE`. Crucially, delivery is blocked when accruing this shift's hours would carry the episode's `companion_hours_used` above the `companion_hours_authorized` figure on the episode's active plan; that overflow is rejected with `ERR_COMPANION_HOURS_EXCEEDED` (HTTP 422). On success the shift's `hours` are added to the episode's running `companion_hours_used`, and the shift version is bumped. A `BOOKED` shift may instead be cancelled by the `Scheduler`, driving `BOOKED → CANCELLED` and bumping the shift version. `DELIVERED` and `CANCELLED` are terminal for a companion shift.

### 3.6. Travel Mileage and Tiered Reimbursement

After a visit is completed, the assigned `Clinician` may file a mileage claim against it, supplying only the `claimed_miles` they assert they drove round trip (a non-negative number). The claim is created in `PENDING` status, and at creation the system computes `computed_miles`: the straight-line great-circle (haversine) distance in miles from the clinician's base coordinates (`base_lat`, `base_lon`) to the patient's home coordinates (`home_lat`, `home_lon`), doubled for the round trip (the stored `computed_miles` is that doubled distance rounded half-up to two decimal places). The claim records `visit_id` identifying the completed visit it is claimed against, and is created with both `reimbursable_miles` and `reimbursement` null until adjudication.

The `BillingManager` adjudicates each claim. Approving a claim drives `PENDING → APPROVED` and is permitted only when the parent visit is `COMPLETED` and the claimed distance does not exceed the computed distance inflated by the overclaim tolerance of 1.10 — that is, `claimed_miles` must be at most `computed_miles` multiplied by 1.10. (Both the overclaim ceiling and the cap below are formed from the full-precision unrounded doubled great-circle distance multiplied by 1.10 and only then rounded half-up to two decimal places — not from the already-rounded stored `computed_miles` — so the two can differ by a cent.) A claim that exceeds this ceiling is rejected with `ERR_MILEAGE_OVERCLAIM` (HTTP 422). On approval the reimbursement is computed in stages. The capped figure is the smaller of `claimed_miles` and that rounded ceiling. From the capped figure, the first 5.0 miles are a free tier that earns nothing, so the billable distance is the capped figure minus 5.0, floored at zero; this billable distance is recorded as `reimbursable_miles`. The billable distance is then priced on two marginal tiers: the first 20.0 billable miles earn $0.67 per mile, and any billable miles beyond 20.0 earn $0.50 per mile. The `reimbursement` is the first-tier miles times $0.67 plus the second-tier miles times $0.50, rounded half-up to two decimal places. The approved reimbursement is then added to the episode's running `total_mileage_reimbursed`, and the claim version is bumped.

Rejecting a claim drives `PENDING → REJECTED`, which is permitted only from `PENDING`, sets the claim's `reimbursement` to zero (leaving `reimbursable_miles` null), and bumps the claim version. `APPROVED` and `REJECTED` are terminal for a mileage claim.

### 3.7. Recertification: Extending Care Past Sixty Days

When a patient needs care beyond the original sixty days, the episode is recertified. An `IntakeCoordinator` opens a recertification request against an `ACTIVE` episode, naming the supporting assessment via `recert_oasis_id`. Opening the request drives the episode `ACTIVE → RECERT_PENDING` and creates the request in `SUBMITTED` status, bumping the episode version. The request may only be opened while the recertification window is open — that is, the current server clock date falls within the final 14 days before `cert_end`; the comparison is by calendar date (the date components of the pinned clock and of `cert_end`, time-of-day ignored) and is inclusive at both ends, so the window admits every date from `cert_end` minus 14 days through `cert_end` itself. An attempt outside that window is rejected with `ERR_RECERT_WINDOW_CLOSED` (HTTP 422). The supporting assessment must be of type `RECERTIFICATION`, belong to the same patient, and not be locked, or the request fails with `ERR_RECERT_OASIS_INVALID` (HTTP 422). The request also carries a `review_note` written by the compliance reviewer — accepted optionally on the open request and defaulting to the empty string when omitted — and a `revision_count` that starts at zero.

A `ComplianceOfficer` adjudicates the submitted request along three branches, each permitted only from `SUBMITTED`. Approving it drives the request `SUBMITTED → APPROVED` and requires that the supporting OASIS still be unlocked; approval locks that recert OASIS, drives the parent episode `RECERT_PENDING → ACTIVE`, extends `cert_end` by 60 days (the new `cert_end` is the old `cert_end` plus 60 days, with `cert_start` unchanged), copies `clinical_group` and `functional_level` from the recert OASIS onto the episode, recomputes the episode's `lupa_threshold` from the active rate configuration for the new clinical group, appends a RECERT_APPROVED event, and bumps the episode version. Denying the request drives it `SUBMITTED → DENIED` and returns the parent episode `RECERT_PENDING → ACTIVE` under the original certification window with no extension to `cert_end`, bumping the episode version; a `review_note` supplied in the deny body is stored on the request. Returning the request for revision drives it `SUBMITTED → RETURNED`, stores the `review_note` (a `review_note` supplied in the return body overwrites the stored one), and bumps the request's own version. Both deny and return leave `review_note` unchanged when the body omits it.

A returned request re-enters the loop: the `IntakeCoordinator` resubmits it, driving `RETURNED → SUBMITTED` and incrementing its `revision_count` by 1. The revision loop is bounded — at most three revisions are allowed, so a resubmission attempted when `revision_count` already equals 3 is rejected with `ERR_MAX_REVISIONS_EXCEEDED` (HTTP 422). The cycle `ACTIVE → RECERT_PENDING → ACTIVE` may repeat across the life of an episode, forming a recert chain that successive episodes record through `prior_episode_id`. `APPROVED` and `DENIED` are terminal for a recertification request.

### 3.8. Finalizing, Settling, and Reopening

When all care is delivered, the `BillingManager` finalizes the episode, driving `ACTIVE → DISCHARGED`. Finalize is permitted only when every visit on the episode is in a terminal state — none may remain `SCHEDULED` or `CONFIRMED` — and the episode holds no `SUBMITTED` recertification request; otherwise it is rejected with `ERR_EPISODE_NOT_SETTLEABLE` (HTTP 409).

The **final settlement** is computed chronologically and from actuals only. It considers exactly those visits in `COMPLETED` status at finalize time, walked in ascending `scheduled_start` order with `created_at` as the tie-break; visits that are `SCHEDULED`, `CONFIRMED`, `MISSED`, or `CANCELLED` are excluded. Let the completed-visit count be the number of such visits. The case-mix amount is computed exactly as in the provisional estimate — `base_30day_rate` times the chosen functional weight times the comorbidity multiplier (1.00 when `comorbidity_count` is zero, 1.06 when it is 1 or 2, and 1.18 when it is 3 or greater). Here, however, the Low Utilization adjustment can bite: if the completed-visit count is strictly less than the episode's `lupa_threshold`, the payment basis is `LUPA_PER_VISIT` and the gross PDGM amount is $165.00 per completed visit, rounded half-up to two decimal places; otherwise the payment basis is `FULL_PDGM` and the gross PDGM amount is the case-mix amount multiplied by 2, rounded half-up to two decimal places. This is why the final settlement can diverge from the provisional estimate for the same episode — the provisional view assumed full delivery, while the final view honors what was actually completed.

The companion-hour offset folded into settlement is built shift by shift to pin the rounding order. For each `DELIVERED` companion shift on the episode, that shift's cost is its `hours` multiplied by the companion hourly rate of $24.05, rounded half-up to two decimal places per shift; the `companion_offset` is the sum of those per-shift rounded costs, which is a positive payable amount. The settlement then records `gross_pdgm` (the amount above), `mileage_offset` equal to the episode's accumulated `total_mileage_reimbursed`, `companion_offset` as just computed, and `net_settlement` equal to `gross_pdgm` plus `mileage_offset` plus `companion_offset`. That net amount is also written to the episode's `final_payment` (which is zero until finalize). Finalize creates a `PaymentLedger` row capturing `episode_id`, `payment_basis`, `gross_pdgm`, `mileage_offset`, `companion_offset`, `net_settlement`, and a `reversed` flag set false. It appends a FINALIZED event and then a DISCHARGED event, sets the patient's `status` to `DISCHARGED` if the patient has no other non-terminal episode, and bumps the episode version.

A finalized episode can be reopened by the `BillingManager` within a 30-day reopen window measured from the finalize event, driving `DISCHARGED → ACTIVE`. Reopen is permitted only when the episode has a `PaymentLedger` row that has not already been reversed and the request arrives no later than 30 days after the finalize event; a request that arrives beyond that 30-day window is rejected with `ERR_REOPEN_WINDOW_CLOSED` (HTTP 422). Reopening is a compensating action: it sets that ledger row's `reversed` flag to true (conceptually backing out the `net_settlement`), resets the episode's `final_payment` to zero, restores the patient's `status` to `ACTIVE`, appends a LEDGER_REVERSED event, and bumps the episode version.

### 3.9. The Audit Trail

Every materially significant change appends an `EpisodeEvent` to the episode's immutable log. Each event records the owning episode via `episode_id`, an `event_type`, a human-readable `detail`, and an `occurred_at` server timestamp. The `event_type` is one of `ACTIVATED`, `PLAN_SUPERSEDED`, `VISIT_COMPLETED`, `VISIT_MISSED`, `RECERT_APPROVED`, `FINALIZED`, `LEDGER_REVERSED`, `DISCHARGED`, or `CANCELLED`, written by the workflows described above. The event log is read-only once written and, like rate configurations, carries no `version` or `updated_at`.

### 3.10. Order of Evaluation

Because so many rules in this domain turn on the current moment — visit-window elapsation, the recertification window, the reopen window — a test-driving capability lets an operator pin the server's logical clock to a fixed instant supplied as `now_utc`. All five roles may exercise this capability, and the pinned clock is the one consulted by every temporal check described above.

Where several checks guard a single operation, they are evaluated in a fixed priority order so that the most fundamental failure is reported first. Authentication comes first: a missing or unknown `X-User-Role`/`X-User-ID` yields `ERR_UNAUTHENTICATED`. Role authorization comes next, yielding `ERR_FORBIDDEN_ROLE` when the role may not perform the operation. Resource ownership follows for the clinician-owned confirm and complete actions, yielding `ERR_NOT_RESOURCE_OWNER`; because ownership is read off the target visit, that target visit's own existence is verified first (a missing target visit yields `ERR_NOT_FOUND` before the ownership comparison). Existence of every other referenced resource is then checked left to right, yielding `ERR_NOT_FOUND`. After that comes the transition-state check, yielding `ERR_INVALID_STATE` when the target is not in a state that permits the requested transition. Only once those gate checks pass does the system evaluate the operation-specific business rules — episode-active requirements, license, discipline, OASIS validity, temporal windows, capacity, fiscal limits, settleability, the single-open-episode rule, and finally the optimistic-concurrency version match — each surfacing the specific error named alongside its rule in the sections above.

## 4. Endpoint Definitions

All endpoints share a uniform status-code convention: creating a new resource returns 201 Created, while every state transition, mutation, and read returns 200 OK. Request bodies, computed fields, and side effects are intentionally not repeated here — they are specified in the §3 workflows above and must be reconstructed from that narrative.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/patients` | Create a patient | IntakeCoordinator |
| GET | `/patients/{id}` | Fetch a patient (open_episode_id computed) | IntakeCoordinator, Scheduler, BillingManager, ComplianceOfficer |
| GET | `/patients/{id}/episodes` | List episodes for a patient | IntakeCoordinator, Scheduler, BillingManager, ComplianceOfficer |
| POST | `/clinicians` | Create a clinician | Scheduler |
| GET | `/clinicians/{id}` | Fetch a clinician | Scheduler, IntakeCoordinator, BillingManager |
| PATCH | `/clinicians/{id}` | Update clinician license_active or weekly_visit_cap | Scheduler |
| GET | `/clinicians/{id}/visits` | List visits assigned to a clinician, filterable by status | Scheduler, Clinician, BillingManager |
| POST | `/oasis-assessments` | Record an OASIS assessment (SOC or recert order source) | IntakeCoordinator |
| GET | `/oasis-assessments` | List OASIS assessments, filterable by patient or clinician | IntakeCoordinator, ComplianceOfficer |
| GET | `/oasis-assessments/{id}` | Fetch a single OASIS assessment | IntakeCoordinator, ComplianceOfficer |
| GET | `/oasis-assessments/{id}/recert-requests` | List recert requests citing this OASIS | IntakeCoordinator, ComplianceOfficer |
| POST | `/pdgm-rate-configs` | Create a PDGM rate config row for a clinical group | BillingManager |
| GET | `/pdgm-rate-configs` | List PDGM rate configs, filterable by clinical_group and by active (`active=true`/`active=false`) | BillingManager, IntakeCoordinator |
| POST | `/episodes` | Open a 60-day episode from a START_OF_CARE OASIS | IntakeCoordinator |
| GET | `/episodes` | List episodes, filterable by patient, SOC OASIS, or prior episode | IntakeCoordinator, Scheduler, BillingManager, ComplianceOfficer |
| GET | `/episodes/{id}` | Fetch an episode with computed payment/mileage/companion fields | IntakeCoordinator, Scheduler, BillingManager, ComplianceOfficer |
| POST | `/episodes/{id}/activate` | Activate a DRAFT episode (requires one ACTIVE plan) | IntakeCoordinator |
| POST | `/episodes/{id}/cancel` | Cancel a DRAFT episode; supersede plans and unlock SOC OASIS | IntakeCoordinator |
| POST | `/episodes/{id}/finalize` | Settle PDGM payment and discharge (FULL_PDGM vs LUPA) | BillingManager |
| POST | `/episodes/{id}/reopen` | Reopen a discharged episode within window; reverse the settlement ledger | BillingManager |
| GET | `/episodes/{id}/summary` | Computed read returning the same episode object shape as `GET /episodes/{id}` (its `provisional_payment`, `final_payment`, `total_mileage_reimbursed`, and `companion_hours_used` fields; no extra summary-only or payment-basis field is added) | BillingManager, IntakeCoordinator |
| GET | `/episodes/{id}/events` | List the episode audit log | BillingManager, IntakeCoordinator, ComplianceOfficer |
| POST | `/episodes/{id}/plans-of-care` | Create a PlanOfCare; supersedes the prior ACTIVE plan (OCC on episode version) | IntakeCoordinator |
| GET | `/episodes/{id}/plans-of-care` | List plans of care for an episode, filterable by status | IntakeCoordinator, BillingManager |
| POST | `/episodes/{id}/visits` | Schedule a discipline visit against an ACTIVE episode | Scheduler |
| GET | `/episodes/{id}/visits` | List visits for an episode, filterable by status | Scheduler, BillingManager, IntakeCoordinator |
| GET | `/visits/{id}` | Fetch a visit | Scheduler, Clinician, BillingManager |
| POST | `/visits/{id}/confirm` | Clinician confirms an assigned visit (reserves weekly slot) | Clinician |
| POST | `/visits/{id}/complete` | Clinician completes a confirmed visit (becomes billable) | Clinician |
| POST | `/visits/{id}/mark-missed` | Mark a confirmed visit missed (frees capacity, never bills) | Scheduler |
| POST | `/visits/{id}/cancel` | Cancel a scheduled or confirmed visit | Scheduler |
| POST | `/episodes/{id}/companion-shifts` | Book an HHA companion shift against an ACTIVE episode | Scheduler |
| GET | `/episodes/{id}/companion-shifts` | List companion shifts for an episode, filterable by status | Scheduler, BillingManager |
| POST | `/companion-shifts/{id}/deliver` | Mark a companion shift delivered (accrues companion hours) | Scheduler |
| POST | `/companion-shifts/{id}/cancel` | Cancel a booked companion shift | Scheduler |
| POST | `/visits/{id}/mileage-claims` | File a mileage claim against a completed visit | Clinician |
| GET | `/visits/{id}/mileage-claims` | List mileage claims for a visit | Clinician, BillingManager, Scheduler |
| POST | `/mileage-claims/{id}/approve` | Approve a mileage claim (computes tiered reimbursement) | BillingManager |
| POST | `/mileage-claims/{id}/reject` | Reject a mileage claim | BillingManager |
| POST | `/episodes/{id}/recert-requests` | Open a recert request within the recert window | IntakeCoordinator |
| GET | `/episodes/{id}/recert-requests` | List recert requests for an episode | IntakeCoordinator, ComplianceOfficer |
| GET | `/recert-requests/{id}` | Fetch a recert request | IntakeCoordinator, ComplianceOfficer |
| POST | `/recert-requests/{id}/approve` | Approve a recert (extends cert window 60 days) | ComplianceOfficer |
| POST | `/recert-requests/{id}/return` | Return a recert for revision | ComplianceOfficer |
| POST | `/recert-requests/{id}/resubmit` | Resubmit a returned recert | IntakeCoordinator |
| POST | `/recert-requests/{id}/deny` | Deny a recert (episode returns to ACTIVE, no extension) | ComplianceOfficer |
| GET | `/episodes/{id}/payment-ledger` | List payment ledger rows for an episode | BillingManager |
| POST | `/_clock/set_current_utc` | Test-only: set the server's current UTC clock | BillingManager, IntakeCoordinator, Scheduler, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_VALIDATION | 400 |
| ERR_VERSION_REQUIRED | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_EPISODE_NOT_ACTIVE | 409 |
| ERR_CLINICIAN_DOUBLE_BOOKED | 409 |
| ERR_COMPANION_SHIFT_CONFLICT | 409 |
| ERR_EPISODE_NOT_SETTLEABLE | 409 |
| ERR_PATIENT_HAS_OPEN_EPISODE | 409 |
| ERR_STALE_EPISODE_VERSION | 412 |
| ERR_LICENSE_INACTIVE | 422 |
| ERR_DISCIPLINE_MISMATCH | 422 |
| ERR_OASIS_INVALID | 422 |
| ERR_RECERT_OASIS_INVALID | 422 |
| ERR_RECERT_WINDOW_CLOSED | 422 |
| ERR_REOPEN_WINDOW_CLOSED | 422 |
| ERR_VISIT_OUT_OF_CERT_WINDOW | 422 |
| ERR_WEEKLY_CAP_EXCEEDED | 422 |
| ERR_PLAN_REQUIRED | 422 |
| ERR_MAX_REVISIONS_EXCEEDED | 422 |
| ERR_MILEAGE_OVERCLAIM | 422 |
| ERR_COMPANION_HOURS_EXCEEDED | 422 |
