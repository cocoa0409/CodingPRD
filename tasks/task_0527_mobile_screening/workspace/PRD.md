# Mobile Screening API — Product Requirements Document

## 1. Introduction

Community health organizations increasingly deliver preventive care from mobile units — vans equipped for mammography, blood panels, bone-density scans, or skin checks — that travel to employer sites and grant-funded community locations for single-day screening events. Coordinating these events is deceptively hard: a physical unit can serve only one site per calendar day, staff must be credentialed for the modality on offer, participants must consent before being screened, abnormal results must be navigated to resolution within clinically appropriate deadlines, and every screening carries a bill that may be paid by insurance, out of pocket, or drawn from a finite grant fund.

The Mobile Screening API is the system of record for this operation. It governs the full participant journey — registration, consent, check-in, screening, result delivery, and abnormal-result follow-up — alongside the operational scaffolding of mobile units, staff rosters, sponsors, grants, event scheduling, appointment reminders, and billing. The API is designed around strict lifecycle discipline: resources move through explicit state machines, cross-entity operations cascade their side effects deterministically, and financial commitments against grant funds are conserved so that a dollar committed and later voided is returned to the pool exactly. Sponsors — whether the employers hosting events or the grant bodies funding them — receive read-only reporting on screening volumes, abnormal rates, realized cost, and navigation effectiveness.

This document specifies the complete contract: the global conventions every endpoint obeys, the business logic and workflows for each domain, the endpoint catalogue, and the full error catalogue. Because time-dependent behavior (reminder due-dates, referral deadlines) must be deterministic and testable, the server runs on a logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. This check precedes every other check on every endpoint.

The system recognizes five roles: `ProgramManager`, `ClinicalStaff`, `BillingClerk`, `PatientNavigator`, and `SponsorViewer`. A `ProgramManager` owns program setup, the mobile-unit and staff rosters, sponsors and grants, the event lifecycle, participant lifecycle actions, reminders, and event-day operations such as appointment cancellation and no-show marking. A `ClinicalStaff` member runs on-site clinical operations: registering and booking participants, recording consent, checking in, screening, delivering results, and closing appointments. A `BillingClerk` owns the billing lifecycle — adjudicating, settling, and voiding charges. A `PatientNavigator` owns abnormal-result navigation — contacting participants, scheduling follow-ups, and resolving or marking referrals lost. A `SponsorViewer` is a read-only stakeholder that reads its own sponsor record, that sponsor's grants and events, and the computed sponsor report. When a caller holds a valid role but that role is not permitted for the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Four of these roles carry an opaque identity: when `X-User-Role` is `ProgramManager`, `ClinicalStaff`, `BillingClerk`, or `PatientNavigator`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `SponsorViewer` role is likewise identified by an opaque `X-User-ID`, but that identifier carries an ownership meaning: a `SponsorViewer` may read a sponsor record, that sponsor's report, its grants, and its events only when the `X-User-ID` presented equals the `viewer_user_id` recorded on the target `Sponsor`. A `SponsorViewer` whose `X-User-ID` does not match the target sponsor's `viewer_user_id` is treated as not permitted for that read and is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

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

List endpoints are paginated via query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses include the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a system-generated `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp — an ISO 8601 UTC value with three fractional digits recorded at creation. All entities in this system additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation, and a `version` integer that begins at its initial value on creation and increments by exactly one on every mutation. Whenever the specification says an operation "bumps the version" of a resource, it means the `version` integer increments by one and `updated_at` is refreshed to the current logical time.

The `version` integer additionally serves as the optimistic-concurrency token described in §2.7. Computed fields count as mutations for versioning purposes: when a cascade adjusts a resource's derived state, that resource's `updated_at` and `version` advance accordingly.

### 2.5. Reverse Reachability and Nested Path Validation

The entity model is flat: entities reference one another by foreign-key fields rather than by nested URL containment. To let callers walk relationships in reverse, list endpoints expose filter query parameters. Staff can be filtered by `role_type`, `modality`, and `status`; sponsors by `sponsor_type`; grants by `sponsor_id`; screening events by `sponsor_id`, `mobile_unit_id`, and `status`; participants by `grant_id` and `status`; appointments by `event_id`, `participant_id`, and `status`; referrals by `appointment_id`, `participant_id`, and `status`; charges by `appointment_id`, `participant_id`, `grant_id`, and `status`; reminders by `appointment_id` and `status`; and mobile units by `status`.

For any request whose path carries a resource identifier, the server validates path identifiers left-to-right and rejects the first one that does not resolve to an existing resource. A missing resource yields a 404 error — the resource-specific code where one exists (`ERR_UNIT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, `ERR_REMINDER_NOT_FOUND`) and the generic `ERR_NOT_FOUND` otherwise. When a creation or transition request body references a foreign key that does not exist — for example an `event_id`, `participant_id`, `grant_id`, `sponsor_id`, or `mobile_unit_id` on the relevant create endpoints — the request is likewise rejected with the corresponding resource-specific 404 code.

### 2.6. The Logical Clock

The server maintains a logical UTC clock rather than reading wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it never falls back to wall-clock time. A `ProgramManager` may advance or reset the clock by supplying a target instant in the `to_iso8601` field; the clock is then set to that value and the current value is returned as `current_utc`. All time-dependent behavior — reminder due-time checks and the timestamps stamped on consent and result delivery — reads this logical clock.

### 2.7. Optimistic Concurrency Control on Charges

Two billing transitions are guarded by optimistic concurrency control keyed on the charge's `version`. Adjudicating a charge requires the request to carry `expected_charge_version` matching that charge's current `version`. If another writer has advanced the charge's version since the client last observed it — for instance an earlier adjudication attempt or a void the client did not see — the adjudication carries a stale `expected_charge_version` and is rejected with `ERR_STALE_VERSION` (HTTP 412). Settling a charge similarly requires `expected_charge_version` matching the charge's current `version`; because the adjudication that moved the charge into `ADJUDICATED` already advanced its version, a settle request that still carries the pre-adjudication value is stale and is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a charge-version field, and the `expected_event_version` supplied at publish is validated against the event as its own guard rather than as a general OCC token — publish itself accepts `expected_event_version` as a required input and is otherwise the sole event-lifecycle transition that carries a version field.

### 2.8. Grant Fund Conservation and Depletion

Grant funds obey a strict conservation invariant so that committed money is never lost or double-counted. A grant tracks its `total_budget_cents` (the funding pool), its `committed_cents` (the sum of `grant_covered_cents` across all charges drawing this grant that are in `DRAFT`, `ADJUDICATED`, or `SETTLED`), and its `settled_cents` (the sum of `grant_covered_cents` across only the `SETTLED` charges drawing this grant). Its `remaining_cents` is the available headroom, computed as `total_budget_cents` minus `committed_cents` — an *estimated burn* that treats every open commitment as already spent, which is the conservative basis used to gate new commitments. The grant's `is_depleted` flag is true exactly when `remaining_cents` is at or below the depletion floor of zero cents, and false otherwise.

These two burn views are deliberately distinct. The estimated burn, driven by `committed_cents` and hence `remaining_cents` and `is_depleted`, counts every `DRAFT`, `ADJUDICATED`, and `SETTLED` charge as spent and is what blocks new bookings. The actual burn, `settled_cents`, counts only `SETTLED` charges and represents realized spend; it is always less than or equal to the estimated burn and is what sponsor reporting uses for realized cost. All grant amounts are exact integer cents. Whenever a charge commits, settles, or voids against a grant, these figures are recomputed.

### 2.9. Monetary and Percentage Precision

All monetary values are stored and returned as exact integer cents; no fractional cents ever arise except transiently inside a calculation, where a value is rounded half up to whole cents before it is stored. Percentage figures reported by the summary and report endpoints are rounded half up to a whole percent. Where a percentage is a ratio, the ratio is computed first and the half-up rounding is applied once, at the end, to the ratio expressed as a percentage — the individual counts are never rounded before combining.

### 2.10. Cascading Side Effects and Immediate Consistency

Operations that terminate or advance a parent resource cascade deterministically to their dependents, and every affected resource has its `updated_at` refreshed and its `version` bumped as part of the cascade. The result-delivery fork, the event-cancellation cascade, the appointment no-show cascade, and the grant-conservation adjustments on charge void and settle are all specified in §3. The system is immediately consistent: the effects of a transition are visible on the next read with no deferred settlement.

## 3. Business Logic & Workflows

### 3.1. Program Setup: Units, Staff, Sponsors, and Grants

Before any screening can happen, a `ProgramManager` assembles the operational backbone. A **mobile unit** is created with a `name` (for example, "Van A"), a `modality` — one of `MAMMOGRAPHY`, `BLOOD_PANEL`, `BONE_DENSITY`, or `SKIN` — and a `daily_capacity`, the maximum number of appointment slots the unit can serve on a single event-day, which must be at least 1. A newly created unit has `status` `AVAILABLE`; retiring a unit moves it from `AVAILABLE` to `RETIRED`.

Staff are onboarded with a `full_name`, a `role_type` — one of `TECHNOLOGIST`, `RADIOLOGIST`, `NAVIGATOR`, or `PHLEBOTOMIST` — and the `modality` for which the member is credentialed, again drawn from `MAMMOGRAPHY`, `BLOOD_PANEL`, `BONE_DENSITY`, or `SKIN`. A staff member starts `ACTIVE` and can be deactivated to `INACTIVE`. Only `ACTIVE` staff of the matching modality satisfy the clinical gates described later.

Sponsors are the organizations behind events. Each **sponsor** carries a `name`, a `sponsor_type` of either `EMPLOYER` or `GRANT`, and a `viewer_user_id` — the opaque identifier of the `SponsorViewer` permitted to read this sponsor's records and report, as described in §2.1. A **grant** is a funding pool created under a `GRANT`-type sponsor; it is registered with a `sponsor_id`, a `name`, and a `total_budget_cents` that must be at least zero. At creation its `committed_cents` and `settled_cents` are zero and its `remaining_cents` equals `total_budget_cents`. The grant's `committed_cents`, `settled_cents`, `remaining_cents`, and `is_depleted` are computed fields maintained per §2.8.

### 3.2. Scheduling Events and the Unit-Day Constraint

A `ProgramManager` creates a **screening event** in `DRAFT` by supplying a `sponsor_id` (the hosting employer or grant body), a `mobile_unit_id` (the unit assigned to the day), a `modality`, a `site_label` describing the physical location, an `event_date` given as a `YYYY-MM-DD` calendar day, and the day's operating window. The window is expressed as `window_start_min`, the minutes-from-midnight at which the event opens (from 0 through 1439, inclusive lower bound), and `window_end_min`, the minutes-from-midnight at which it closes (from 1 through 1440, treated as an exclusive upper bound); `window_end_min` must be strictly greater than `window_start_min`. An event also exposes `booked_count`, a computed count of the appointments on it that are in the non-cancelled states `SCHEDULED`, `CHECKED_IN`, `SCREENED`, `RESULT_READY`, or `CLOSED`.

An event lives through the states `DRAFT`, `PUBLISHED`, `CLOSED`, and `CANCELLED`, with `CANCELLED` terminal. Publishing an event advances it from `DRAFT` to `PUBLISHED` and carries the required `expected_event_version`; the event must be in `DRAFT` (otherwise `ERR_INVALID_STATE`), the assigned mobile unit must be `AVAILABLE` (otherwise `ERR_UNIT_UNAVAILABLE`), the event's `modality` must equal the unit's `modality` (otherwise `ERR_MODALITY_MISMATCH`), and no other event already in `PUBLISHED` or `CLOSED` may share this `mobile_unit_id` and `event_date` (otherwise `ERR_UNIT_DAY_CONFLICT`) — a unit occupies a whole calendar day exclusively. Publishing bumps the event's `version`.

Closing an event advances it from `PUBLISHED` to `CLOSED`. The event must be `PUBLISHED` (otherwise `ERR_INVALID_STATE`), and no appointment on the event may be in an in-progress state of `CHECKED_IN`, `SCREENED`, or `RESULT_READY` (otherwise `ERR_OPEN_APPOINTMENTS_EXIST`). Appointments still in `SCHEDULED` do not block closure — closing the event day leaves them `SCHEDULED` so they may afterward be marked no-show; only mid-screening work prevents closure. Closing bumps the event's `version`.

Cancelling an event moves it to `CANCELLED` and is permitted while the event is in either `DRAFT` or `PUBLISHED` (otherwise `ERR_INVALID_STATE`). Cancelling from `DRAFT` simply bumps the event's `version`. Cancelling from `PUBLISHED` triggers a three-hop cascade: first, every appointment on the event that is in `SCHEDULED` or `CHECKED_IN` transitions to `CANCELLED` (this cancellation does not increment the participant's no-show strikes). Second, for each of those just-cancelled appointments, every reminder tied to it that is still `PENDING` transitions to `CANCELLED`, and — on the billing side — every charge tied to it that is in `DRAFT` or `ADJUDICATED` transitions to `VOID`; when such a charge drew a grant, that grant's `committed_cents` is reduced by the charge's `grant_covered_cents`, restoring headroom. The event's own `version` is bumped. Each affected appointment, reminder, charge, and grant likewise has its `updated_at` and `version` advanced.

The event summary endpoint reports a computed view of the day. It exposes `booked_count`, `screened_count`, `no_show_count`, `capacity`, `fill_rate_pct`, and `show_rate_pct`. Here `booked_count` counts appointments in `SCHEDULED`, `CHECKED_IN`, `SCREENED`, `RESULT_READY`, or `CLOSED`; `screened_count` counts appointments in `SCREENED`, `RESULT_READY`, or `CLOSED`; `no_show_count` counts appointments in `NO_SHOW`; and `capacity` is the assigned mobile unit's `daily_capacity`. The fill rate is the booked count divided by capacity, multiplied by 100, then rounded half up to a whole percent — the ratio is formed first and rounded once at the end, never by rounding the counts beforehand. The show rate is the screened count divided by the booked count, multiplied by 100, then rounded half up to a whole percent, applying the same ratio-then-round discipline; when the booked count is zero, the show rate is reported as 0.

### 3.3. Registering Participants and the No-Show Threshold

A `ProgramManager` or `ClinicalStaff` member registers a **participant** with a `full_name`, a `date_of_birth` given as `YYYY-MM-DD` (used for age-eligibility on the modality), and a `pay_type` of `INSURANCE`, `SELF_PAY`, or `GRANT`. When `pay_type` is `INSURANCE`, an `insurance_member_id` is required; when `pay_type` is `GRANT`, a `grant_id` referencing the funding grant is required; each is otherwise optional. A participant begins with `no_show_strikes` at 0 and `status` `ACTIVE`.

Participants accumulate no-show strikes over time. Whenever an appointment is marked no-show, the participant's `no_show_strikes` count increases by one, and if that count reaches the strike limit of three while the participant is still `ACTIVE`, the participant automatically flips to `BLOCKED`. A `BLOCKED` participant cannot be booked. A `ProgramManager` may reinstate a blocked participant, moving `status` from `BLOCKED` back to `ACTIVE` (the participant must be `BLOCKED`, otherwise `ERR_INVALID_STATE`); reinstatement resets `no_show_strikes` to 0 and bumps the participant's `version`.

### 3.4. Booking Appointments Within the Window

A `ProgramManager` or `ClinicalStaff` member books an **appointment** by supplying the `event_id` of a published event, the `participant_id` of the person being screened, a `slot_start_min` (minutes-from-midnight at which the appointment starts), and a `slot_duration_min` (the slot length in minutes, at least 1). The occupied interval is the half-open range beginning at `slot_start_min` and ending at `slot_start_min` plus `slot_duration_min`. Booking recomputes the event's `booked_count`. An appointment also carries `consent_signed`, `consent_signed_at`, `result`, and `result_delivered_at`, discussed below.

Several guards apply at booking time, and their relative ordering matters. Any missing or mistyped body field, or an out-of-range value, is rejected first as `ERR_INVALID_REQUEST`. The referenced event and participant must exist, or the corresponding 404 is returned. A participant whose `status` is `BLOCKED` cannot be booked and is rejected with `ERR_PARTICIPANT_BLOCKED`. The slot's half-open interval must lie fully within the event's window — that is, from `window_start_min` up to `window_end_min` — and a slot falling outside is rejected with `ERR_SLOT_OUTSIDE_WINDOW`. The slot's half-open interval must not overlap the interval of any existing non-cancelled appointment on the same event; two intervals that merely touch at a single point do not conflict, but any shared interior minute does, and an overlap is rejected with `ERR_SLOT_OVERLAP`. The event's `booked_count` must be strictly less than the mobile unit's `daily_capacity` at booking time; a count already at or above capacity is rejected with `ERR_EVENT_FULL`. Finally, for a `GRANT`-pay participant, the referenced grant must not be depleted — its `is_depleted` must be false — or the booking is rejected with `ERR_GRANT_DEPLETED`. Read the ordering as: request well-formedness, then existence, then the blocked-participant check, then slot-within-window, then slot-overlap, then event capacity, then grant depletion.

### 3.5. The Consent-to-Closure Screening Journey

An appointment progresses through `SCHEDULED`, `CHECKED_IN`, `SCREENED`, `RESULT_READY`, and `CLOSED`, with the diversions `CANCELLED` and `NO_SHOW`; `CLOSED`, `CANCELLED`, and `NO_SHOW` are terminal. Before clinical work begins, consent must be on file. Recording consent for an appointment sets `consent_signed` to true and stamps `consent_signed_at` with the current logical time, and bumps the appointment's `version`; either a `ProgramManager` or `ClinicalStaff` may record it.

`ClinicalStaff` check a participant in, advancing the appointment from `SCHEDULED` to `CHECKED_IN`. Check-in requires the appointment to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`), the parent event to be `PUBLISHED` (otherwise `ERR_EVENT_NOT_PUBLISHED`), and the appointment's `consent_signed` to be true (otherwise `ERR_CONSENT_REQUIRED`). Check-in bumps the appointment's `version`.

Screening advances the appointment from `CHECKED_IN` to `SCREENED` and is performed by `ClinicalStaff`. The appointment must be `CHECKED_IN` (otherwise `ERR_INVALID_STATE`), and there must exist a staff member who is `ACTIVE`, whose `modality` equals the event's modality, and whose `role_type` is `TECHNOLOGIST` or `PHLEBOTOMIST` (otherwise `ERR_NO_CREDENTIALED_STAFF`) — the roster gates the screening. Screening spawns the billing charge: a charge is created in `DRAFT` for this appointment, as detailed in §3.7, and the appointment's `version` is bumped.

Delivering a result advances the appointment from `SCREENED` to `RESULT_READY` and is performed by `ClinicalStaff`, who supply the `result` — either `NORMAL` or `ABNORMAL` — and, optionally, a `flagged_urgent` boolean. The appointment must be `SCREENED` (otherwise `ERR_INVALID_STATE`). For a `MAMMOGRAPHY` event there must additionally exist an `ACTIVE` staff member whose `role_type` is `RADIOLOGIST` and whose `modality` is `MAMMOGRAPHY` (otherwise `ERR_NO_CREDENTIALED_STAFF`). Delivering the result sets the appointment's `result` to the delivered value and stamps `result_delivered_at`, and bumps the appointment's `version`. Here the workflow forks: when the result is `ABNORMAL`, a referral is created in `OPEN` for this appointment (its priority and deadline are set per §3.6); when the result is `NORMAL`, no referral is created.

Closing an appointment advances it from `RESULT_READY` to `CLOSED` and is performed by `ClinicalStaff`; the appointment must be `RESULT_READY` (otherwise `ERR_INVALID_STATE`). When the appointment's `result` was `ABNORMAL`, its linked referral must already be in a terminal state — `RESOLVED` or `LOST_TO_FOLLOWUP` — or closure is rejected with `ERR_REFERRAL_UNRESOLVED`; a `NORMAL` appointment has no such gate. Closing bumps the appointment's `version`.

Two off-ramps exist from `SCHEDULED`, both driven by a `ProgramManager`. Cancelling a scheduled appointment moves it to `CANCELLED` (it must be `SCHEDULED`, otherwise `ERR_INVALID_STATE`); as a side effect every `PENDING` reminder for that appointment transitions to `CANCELLED`, and the appointment's `version` is bumped. Marking a no-show moves a scheduled appointment to `NO_SHOW` (it must be `SCHEDULED`, otherwise `ERR_INVALID_STATE`) but only after the parent event is `CLOSED` (otherwise `ERR_EVENT_NOT_CLOSED`). Marking a no-show cascades in three hops: the participant's `no_show_strikes` increases by one; if that count reaches the strike limit of three while the participant is `ACTIVE`, the participant flips to `BLOCKED`; and every `PENDING` reminder for the appointment transitions to `CANCELLED`. The appointment's `version` is bumped.

### 3.6. Abnormal-Result Navigation

An abnormal result opens a **referral**, which a `PatientNavigator` works to resolution. A referral records the `appointment_id` of the abnormal appointment that spawned it and the `participant_id` of the person referred, both set by the system. Its `priority` is derived at creation from the `flagged_urgent` flag supplied at result delivery: when `flagged_urgent` is true the priority is `URGENT`, otherwise it is `ROUTINE`. The referral's `due_by_date` is the deadline for navigation contact, computed as the event's `event_date` plus a service-level number of calendar days — 7 days for an `URGENT` referral and 30 days for a `ROUTINE` referral.

A referral moves through `OPEN`, `CONTACTED`, `SCHEDULED_FOLLOWUP`, and `RESOLVED`, with `LOST_TO_FOLLOWUP` as an alternate terminal outcome; `RESOLVED` and `LOST_TO_FOLLOWUP` are both terminal. The navigator contacts the participant, advancing `OPEN` to `CONTACTED` (the referral must be `OPEN`, otherwise `ERR_INVALID_STATE`); schedules a follow-up, advancing `CONTACTED` to `SCHEDULED_FOLLOWUP` (must be `CONTACTED`, otherwise `ERR_INVALID_STATE`); and resolves the referral, advancing `SCHEDULED_FOLLOWUP` to `RESOLVED` (must be `SCHEDULED_FOLLOWUP`, otherwise `ERR_INVALID_STATE`). At any point before resolution the navigator may mark the referral lost, transitioning it to `LOST_TO_FOLLOWUP` from `OPEN`, `CONTACTED`, or `SCHEDULED_FOLLOWUP` (from any other state, `ERR_INVALID_STATE`). Every one of these referral transitions bumps the referral's `version`.

### 3.7. Billing: Provisional and Finalized Responsibility

A **charge** is created automatically in `DRAFT` at the moment an appointment is screened. The system records the `appointment_id` and `participant_id`, snapshots the participant's `pay_type` onto the charge, and captures `list_price_cents` — the gross screening price for the event's modality, drawn from the price schedule of 20000 cents for `MAMMOGRAPHY`, 8000 cents for `BLOOD_PANEL`, 12000 cents for `BONE_DENSITY`, and 6000 cents for `SKIN`. At creation the charge also carries a `grant_id` when grant-funded (otherwise none), a `grant_covered_cents` amount, a `provisional_patient_responsibility_cents`, and — only later — a `final_patient_responsibility_cents`. A charge lives through `DRAFT`, `ADJUDICATED`, and `SETTLED`, with `VOID` as an alternate terminal outcome; `SETTLED` and `VOID` are terminal.

The provisional responsibility is computed at charge creation from the captured list price. For a `SELF_PAY` participant, `grant_covered_cents` is 0 and the provisional patient responsibility equals the full list price. For an `INSURANCE` participant, `grant_covered_cents` is 0 and, because the payer has not yet adjudicated, the provisional responsibility is an estimate: the list price multiplied by a provisional coinsurance rate of 20 percent (0.20), rounded half up to whole cents. For a `GRANT` participant, the grant pays up to the participant's grant headroom capped at the list price — that is, `grant_covered_cents` is the smaller of the list price and the grant's `remaining_cents` evaluated immediately before this commitment — and the provisional responsibility is the list price minus `grant_covered_cents`. When a grant-funded charge is created, the drawn `grant_covered_cents` is added to that grant's `committed_cents`, consuming headroom.

A `BillingClerk` adjudicates a charge, advancing it from `DRAFT` to `ADJUDICATED`. The charge must be `DRAFT` (otherwise `ERR_INVALID_STATE`), the supplied `expected_charge_version` must match the charge's current `version` (otherwise `ERR_STALE_VERSION`, per §2.7), and — when the charge's `pay_type` is `INSURANCE` — the request must supply an `insurance_allowed_cents` that is between 0 and the charge's `list_price_cents` inclusive (otherwise `ERR_INVALID_ADJUDICATION`). Adjudication computes the finalized responsibility: for `SELF_PAY`, the final patient responsibility equals the list price; for `INSURANCE`, it equals the list price minus `insurance_allowed_cents` (superseding, not adding to, the provisional estimate); for `GRANT`, it equals the list price minus `grant_covered_cents`. Adjudication bumps the charge's `version`.

Settling a charge advances it from `ADJUDICATED` to `SETTLED` and is performed by a `BillingClerk`. The charge must be `ADJUDICATED` (otherwise `ERR_INVALID_STATE`) and the supplied `expected_charge_version` must match the charge's current `version` (otherwise `ERR_STALE_VERSION`, per §2.7). When the charge is grant-funded, settlement increases the grant's `settled_cents` by the charge's `grant_covered_cents` while leaving `committed_cents` unchanged — the commitment simply becomes a realized settlement. Settling bumps the charge's `version`.

Voiding a charge moves it to `VOID` and is permitted while the charge is in `DRAFT` or `ADJUDICATED` (otherwise `ERR_INVALID_STATE`); void takes no version field. When the voided charge is grant-funded, its `grant_covered_cents` is subtracted back from the grant's `committed_cents`, restoring headroom and preserving the conservation invariant. Voiding bumps the charge's `version`.

### 3.8. Reminders and No-Show Communication

A `ProgramManager` schedules a **reminder** against an appointment by supplying its `appointment_id`, a `send_at_min` (the minutes-from-midnight on the event date at which the reminder becomes due), and a `channel` of either `SMS` or `EMAIL`. A reminder begins `PENDING` and can end either `SENT` or `CANCELLED`, both terminal.

Sending a reminder advances it from `PENDING` to `SENT`. The reminder must be `PENDING` (otherwise `ERR_INVALID_STATE`); the linked appointment must be in `SCHEDULED` or `CHECKED_IN` (otherwise `ERR_APPOINTMENT_NOT_ACTIVE`) — a cancelled, no-show, or closed appointment cannot be reminded; and the reminder must be due, meaning the logical clock's current time-of-day in minutes-from-midnight is at or past `send_at_min`, or the logical clock's current calendar date is later than the event's `event_date` (otherwise `ERR_REMINDER_NOT_DUE`). Sending bumps the reminder's `version`. A `ProgramManager` may also cancel a `PENDING` reminder directly, moving it to `CANCELLED` (it must be `PENDING`, otherwise `ERR_INVALID_STATE`) and bumping its `version`. Reminders are also cancelled by the system as the cascade side effect of appointment cancellation and no-show marking described in §3.5, and as part of the event-cancellation cascade in §3.2.

### 3.9. Sponsor Reporting

A sponsor's report aggregates activity across all of that sponsor's screening events, regardless of status, and their descendant appointments, charges, and referrals. It returns `events_published` — the number of the sponsor's events in `PUBLISHED` or `CLOSED`; `total_screened` — the number of appointments across those events in `SCREENED`, `RESULT_READY`, or `CLOSED`; `abnormal_count` — the number of appointments in `RESULT_READY` or `CLOSED` whose `result` is `ABNORMAL`; and `abnormal_rate_pct` — the abnormal count divided by the total screened, multiplied by 100 and rounded half up to a whole percent (0 when nothing has been screened). It also reports realized cost as `grant_settled_cents` (the sum of `grant_covered_cents` over `SETTLED` grant-funded charges on the sponsor's events), `patient_paid_cents` (the sum of `final_patient_responsibility_cents` over `SETTLED` non-grant charges on the sponsor's events), and `realized_cost_cents` (their sum). Finally it reports navigation effectiveness as `referrals_total` (the count of referrals on the sponsor's events), `referrals_resolved` (those in `RESOLVED`), and `resolution_rate_pct` (the resolved count divided by the total, times 100, rounded half up to a whole percent, and 0 when there are no referrals). Every rate follows the ratio-then-round discipline of §2.9; every monetary figure is exact integer cents.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that read a resource or that transition or otherwise modify an existing resource return `200 OK`. All endpoints are subject to the header, permission, existence, and validation checks described in §2 and §3, evaluated in the priority order: user-context headers first, then role permission, then path-resource existence, then referenced foreign-key existence, then request well-formedness, then state eligibility, then the remaining business gates in the order their workflow describes.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock (UTC) | ProgramManager |
| POST | `/mobile-units` | Create a mobile unit | ProgramManager |
| GET | `/mobile-units` | List mobile units | ProgramManager, ClinicalStaff, BillingClerk, PatientNavigator |
| GET | `/mobile-units/{id}` | Get a mobile unit | ProgramManager, ClinicalStaff, BillingClerk, PatientNavigator |
| POST | `/mobile-units/{id}/retire` | Retire a mobile unit | ProgramManager |
| POST | `/staff` | Create a staff member | ProgramManager |
| GET | `/staff` | List staff (filter by role_type/modality/status) | ProgramManager, ClinicalStaff |
| GET | `/staff/{id}` | Get a staff member | ProgramManager, ClinicalStaff |
| POST | `/staff/{id}/deactivate` | Deactivate a staff member | ProgramManager |
| POST | `/sponsors` | Create a sponsor | ProgramManager |
| GET | `/sponsors` | List sponsors | ProgramManager, BillingClerk |
| GET | `/sponsors/{id}` | Get a sponsor | ProgramManager, BillingClerk, SponsorViewer |
| GET | `/sponsors/{id}/report` | Computed sponsor report | ProgramManager, SponsorViewer |
| POST | `/grants` | Create a grant funding pool | ProgramManager |
| GET | `/grants` | List grants (filter by sponsor_id) | ProgramManager, BillingClerk |
| GET | `/grants/{id}` | Get a grant with computed burn figures | ProgramManager, BillingClerk, SponsorViewer |
| POST | `/screening-events` | Create a screening event | ProgramManager |
| GET | `/screening-events` | List events (filter by sponsor_id/mobile_unit_id/status) | ProgramManager, ClinicalStaff, BillingClerk, SponsorViewer |
| GET | `/screening-events/{id}` | Get an event | ProgramManager, ClinicalStaff, BillingClerk, SponsorViewer |
| GET | `/screening-events/{id}/summary` | Computed event summary | ProgramManager, ClinicalStaff |
| POST | `/screening-events/{id}/publish` | Publish an event | ProgramManager |
| POST | `/screening-events/{id}/close` | Close an event | ProgramManager |
| POST | `/screening-events/{id}/cancel` | Cancel an event (cascades) | ProgramManager |
| POST | `/participants` | Register a participant | ProgramManager, ClinicalStaff |
| GET | `/participants` | List participants (filter by grant_id/status) | ProgramManager, ClinicalStaff, PatientNavigator |
| GET | `/participants/{id}` | Get a participant | ProgramManager, ClinicalStaff, PatientNavigator |
| POST | `/participants/{id}/reinstate` | Reinstate a BLOCKED participant | ProgramManager |
| POST | `/appointments` | Book an appointment | ProgramManager, ClinicalStaff |
| GET | `/appointments` | List appointments (filter by event_id/participant_id/status) | ProgramManager, ClinicalStaff, BillingClerk, PatientNavigator |
| GET | `/appointments/{id}` | Get an appointment | ProgramManager, ClinicalStaff, BillingClerk, PatientNavigator |
| POST | `/appointments/{id}/consent` | Record participant consent | ProgramManager, ClinicalStaff |
| POST | `/appointments/{id}/check-in` | Check in | ClinicalStaff |
| POST | `/appointments/{id}/screen` | Perform screening (creates a DRAFT charge) | ClinicalStaff |
| POST | `/appointments/{id}/deliver-result` | Deliver result (ABNORMAL spawns a referral) | ClinicalStaff |
| POST | `/appointments/{id}/close` | Close appointment | ClinicalStaff |
| POST | `/appointments/{id}/cancel` | Cancel a scheduled appointment | ProgramManager |
| POST | `/appointments/{id}/mark-no-show` | Mark no-show after event closed | ProgramManager |
| GET | `/referrals` | List referrals (filter by appointment_id/participant_id/status) | ProgramManager, PatientNavigator, ClinicalStaff |
| GET | `/referrals/{id}` | Get a referral | ProgramManager, PatientNavigator, ClinicalStaff |
| POST | `/referrals/{id}/contact` | Contact participant | PatientNavigator |
| POST | `/referrals/{id}/schedule-followup` | Schedule follow-up | PatientNavigator |
| POST | `/referrals/{id}/resolve` | Resolve referral | PatientNavigator |
| POST | `/referrals/{id}/mark-lost` | Mark lost to follow-up | PatientNavigator |
| GET | `/charges` | List charges (filter by appointment_id/participant_id/grant_id/status) | ProgramManager, BillingClerk |
| GET | `/charges/{id}` | Get a charge | ProgramManager, BillingClerk |
| POST | `/charges/{id}/adjudicate` | Adjudicate a charge | BillingClerk |
| POST | `/charges/{id}/settle` | Settle a charge | BillingClerk |
| POST | `/charges/{id}/void` | Void a charge (restores grant headroom) | BillingClerk |
| POST | `/reminders` | Create a reminder | ProgramManager |
| GET | `/reminders` | List reminders (filter by appointment_id/status) | ProgramManager, ClinicalStaff |
| GET | `/reminders/{id}` | Get a reminder | ProgramManager, ClinicalStaff |
| POST | `/reminders/{id}/send` | Send a reminder when due | ProgramManager |
| POST | `/reminders/{id}/cancel` | Cancel a PENDING reminder | ProgramManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_NOT_FOUND` | 404 Not Found |
| `ERR_SPONSOR_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_PARTICIPANT_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGE_NOT_FOUND` | 404 Not Found |
| `ERR_REMINDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CONSENT_REQUIRED` | 409 Conflict |
| `ERR_EVENT_NOT_PUBLISHED` | 409 Conflict |
| `ERR_EVENT_NOT_CLOSED` | 409 Conflict |
| `ERR_OPEN_APPOINTMENTS_EXIST` | 409 Conflict |
| `ERR_NO_CREDENTIALED_STAFF` | 409 Conflict |
| `ERR_REFERRAL_UNRESOLVED` | 409 Conflict |
| `ERR_PARTICIPANT_BLOCKED` | 409 Conflict |
| `ERR_SLOT_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_EVENT_FULL` | 409 Conflict |
| `ERR_GRANT_DEPLETED` | 409 Conflict |
| `ERR_UNIT_UNAVAILABLE` | 409 Conflict |
| `ERR_MODALITY_MISMATCH` | 409 Conflict |
| `ERR_UNIT_DAY_CONFLICT` | 409 Conflict |
| `ERR_INVALID_ADJUDICATION` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_REMINDER_NOT_DUE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
