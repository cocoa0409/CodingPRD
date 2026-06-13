# Patient Intake & Digital Forms API — Product Requirements Document

## 1. Introduction

Front-desk teams at outpatient clinics lose hours to paper: a patient arrives, fills in a clipboard, hands over an insurance card that nobody has verified, and signs consent forms that may already be stale by the time the provider walks in. This API replaces that workflow with a fully digital pre-visit intake pipeline. It models the journey from pre-visit registration through insurance capture and payer eligibility, HIPAA and treatment consent e-signature, the medical-history questionnaire, copay collection, and finally the kiosk queue that routes the patient into an exam room.

The system is built around an **IntakeSession** — the packet of forms and money attached to a single appointment. A session is unusual in that it carries two independent status dimensions that advance on their own schedules: a workflow dimension that tracks where the patient is in the physical intake process, and a financial dimension that tracks the money owed and collected. Several supporting concepts — eligibility re-verification loops, consent revoke-and-reissue cycles, questionnaire revision loops, copay compensation (refunds), and a deterministic clock that drives form expiration and reminder firing — make the orchestration genuinely stateful. Because intake packets expire and reminders must respect quiet hours, the system runs on an explicit, test-driven clock rather than wall-clock time, so that every expiration and every scheduled action is reproducible.

This document specifies the complete contract: the global conventions every endpoint shares, the business rules and state machines that govern each entity, the precise calculations behind copay and risk scoring, and the full catalogue of endpoints and error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly four roles, spelled precisely as follows: `ClinicAdmin`, `FrontDeskStaff`, `Patient`, and `BillingClerk`. A `ClinicAdmin` configures the clinic, its providers, and its exam rooms, drives the deterministic clock, and may read every resource. A `FrontDeskStaff` member runs the operational core: registration, insurance capture and verification, consent issuance and re-issuance, questionnaire acceptance, the queue, reminders, room bookings, and demographics sync. A `Patient` acts on the kiosk: signing and revoking consent, and filling, submitting, and revising the questionnaire. A `BillingClerk` owns the copay money path — authorize, capture, void, refund — and may waive a copay.

All four roles use an **opaque** identity model. When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. The same holds for `FrontDeskStaff`, `Patient`, and `BillingClerk`: in each case `X-User-ID` is an opaque operator identifier, never matched against a stored foreign key or resource `id`. Ownership of a resource is therefore never inferred from the caller's identity; authorization is purely role-based per the matrix in §4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Append-Only Exception

Most primary resources — `Clinic`, `Provider`, `ExamRoom`, `Patient`, `Appointment`, `IntakeSession`, `InsuranceCard`, `ConsentDocument`, `QuestionnaireResponse`, `CopayPayment`, `KioskQueueEntry`, `RoomBooking`, `Reminder`, and `DemographicsSyncJob` — carry the same standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation to the resource.
- `version` (integer): a system-managed integer that begins at the resource's creation and increments by one on every mutation. It is the basis for optimistic concurrency control (§2.7).

There is one deliberate exception. An **EligibilityCheck** is an append-only event record: it carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because it is never mutated after it is written.

Whenever the server automatically reconciles a resource — bumping a derived field, cascading a state change, or adjusting a ledger — that reconciliation is itself a mutation: it refreshes the affected resource's `updated_at` and increments its `version`.

### 2.5. Nested Resource Retrieval and Identifier Validation

The API uses flat resource paths; each entity is addressed by its own `id` (for example, an intake session is addressed directly rather than under a parent). Whenever a request carries one or more resource identifiers, the system validates them left-to-right and rejects on the first identifier that does not resolve, returning the not-found error specific to that resource type. Each resource type has its own 404 code: `ERR_CLINIC_NOT_FOUND` for a clinic, `ERR_PROVIDER_NOT_FOUND` for a provider, `ERR_EXAM_ROOM_NOT_FOUND` for an exam room, `ERR_PATIENT_NOT_FOUND` for a patient, `ERR_APPOINTMENT_NOT_FOUND` for an appointment, `ERR_SESSION_NOT_FOUND` for an intake session, `ERR_INSURANCE_CARD_NOT_FOUND` for an insurance card, `ERR_ELIGIBILITY_CHECK_NOT_FOUND` for an eligibility check, `ERR_CONSENT_NOT_FOUND` for a consent document, `ERR_QUESTIONNAIRE_NOT_FOUND` for a questionnaire response, `ERR_PAYMENT_NOT_FOUND` for a copay payment, `ERR_QUEUE_ENTRY_NOT_FOUND` for a queue entry, `ERR_ROOM_BOOKING_NOT_FOUND` for a room booking, `ERR_REMINDER_NOT_FOUND` for a reminder, and `ERR_SYNC_JOB_NOT_FOUND` for a demographics sync job. The same ordering governs foreign keys supplied in a request body: every foreign key must reference an existing resource of the correct type, and a dangling reference is rejected with that type's not-found error before any business rule is evaluated.

### 2.6. The Deterministic Clock and Form Expiration

Time in this system does not come from the wall clock. Each `Clinic` holds a deterministic clock value, `current_utc`, that starts at the Unix epoch (`1970-01-01T00:00:00.000Z`) and advances only when a `ClinicAdmin` sets it. Advancing the clock is the trigger for two automatic sweeps described in §3, so the clock is the single engine behind expiration and reminder firing.

Every clinic configures how long an intake packet stays valid through `form_expiration_hours` (a positive integer, defaulting to 72). When an intake session is created, its `created_at` is stamped from the clinic's deterministic `current_utc` at that moment (not from the wall clock), and its `expires_at` is computed as the session's `created_at` plus that many hours. A session is considered expired at or after that instant — that is, when the clinic's `current_utc` is greater than or equal to `expires_at`. The boundary is inclusive: an operation attempted at the exact expiry instant is treated as occurring on an expired session. Each clinic also carries a `timezone` (an IANA timezone string, defaulting to `UTC`) used for the quiet-hours and expiration arithmetic.

### 2.7. Optimistic Concurrency Control

Two write operations guard against acting on stale parent data using optimistic concurrency control, and on those two operations the version field is required, not optional.

When authorizing a copay payment, the request body must carry `expected_intake_session_version` holding the client's last observed `version` of the target `IntakeSession`. If that value does not equal the session's current `version` — for example because eligibility has just re-resolved, changing the amount due and bumping the session's version since the client last read it — the authorization is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412). This prevents a front desk from authorizing a fresh payment for an amount that is no longer correct. This stale-version check runs before any business validation on the copay-authorize operation.

Likewise, when creating a room booking, the request body must carry `expected_exam_room_version` holding the client's last observed `version` of the target `ExamRoom`. If that value does not equal the room's current `version` — for example because another booking has just been written against the room, advancing its version — the booking is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412). A successful room booking advances the room's `version`. No other endpoint accepts or requires a version field.

### 2.8. Monetary Precision and Rounding

All money in the system is held as integer cents, so the integer legs of any cost computation need no rounding. Where a calculation produces a fractional cent amount — specifically the coinsurance legs described in §3 — the system rounds half up to a whole number of cents. The precise order in which fractional legs are rounded relative to summation is itself configurable per clinic and is described in detail in §3.6; the rounding method everywhere is round half up.

### 2.9. The Copay Ledger and the Active-Queue Counter

Each `Clinic` maintains two conserved running totals as computed fields. The first, `collected_copay_cents`, is a ledger: it is the sum of captured copay amounts across the clinic minus any amounts later refunded, and it is never negative. Capturing a copay credits this ledger by the captured amount; refunding that same copay debits it by the same amount, so the net effect of a capture followed by a refund is exactly zero. The second, `active_queue_count`, counts how many of the clinic's kiosk queue entries are currently in one of the active states `WAITING`, `CALLED`, or `IN_ROOM`. It rises by one when a session enters the queue and falls by one whenever an entry leaves the active set (reaching `DONE` or `NO_SHOW`). Both totals start at zero when the clinic is created. Every adjustment to either counter is a mutation of the clinic, refreshing its `updated_at` and incrementing its `version`.

### 2.10. Cascading Consistency Across the Session Tree

The session sits at the center of a tree of child records — insurance cards, consent documents, the questionnaire, copay payments, the queue entry, room bookings, and reminders. Many operations on a child bubble a recomputation up to the session, and several session-level transitions cascade back down to children. These propagations are not optional side notes; they are part of the contract, and §3 states each one explicitly. As a rule of thumb: completing or accepting a child form may flip the session's readiness and enqueue it; revoking a signed consent may revert a ready session and eject it from the queue; expiring or cancelling a session suppresses or cancels its pending reminders and may no-show its queue entry. Every such propagation independently mutates the resources it touches, updating their `updated_at` and `version`.

## 3. Business Logic & Workflows

### 3.1. Clinic Configuration and the Care Setting

Before any patient is seen, a `ClinicAdmin` stands up the clinic configuration. A clinic is created with a `name` and a set of operational knobs, each of which has a default. Besides `timezone` and `form_expiration_hours` (§2.6), a clinic carries quiet-hours and reminder pacing settings: `reminder_quiet_start_min` (minutes from local midnight at which the quiet window opens, defaulting to 1320, i.e. 22:00), `reminder_quiet_end_min` (minutes from local midnight at which it closes, defaulting to 420, i.e. 07:00, with the window wrapping past midnight), and `reminder_min_gap_minutes` (the minimum spacing between two reminders on the same session, a positive integer defaulting to 240, i.e. four hours). Two money knobs round out the configuration: `copay_rounding`, an enum that is either `PER_LINE_THEN_SUM` (the default) or `SUM_THEN_ROUND` and which pins the rounding order described in §3.6; and `facility_fee_cents`, a non-negative flat per-visit facility fee folded into patient responsibility. The clinic's `current_utc`, `collected_copay_cents`, and `active_queue_count` are all system-managed and initialized as described in §2.6 and §2.9.

A `ClinicAdmin` then registers providers and exam rooms. A `Provider` belongs to a clinic via `clinic_id` and is created with a `full_name`. It also carries a `cleanup_buffer_minutes` (a non-negative buffer appended after each appointment before the provider is considered free again, defaulting to 0), a `required_consent_codes` array (the consent template codes every intake session for this provider must collect, for example `HIPAA_NPP` and `TREATMENT_CONSENT`; an empty array is allowed), and a `questionnaire_required_sections` array (the section keys the medical-history questionnaire must answer for this provider, for example `ALLERGIES`, `MEDICATIONS`, and `HISTORY`; an empty array means the questionnaire is trivially complete). An `ExamRoom` belongs to a clinic via `clinic_id` and carries a human `label` such as "Room 3".

### 3.2. Registration, Appointments, and Provider Double-Booking

A patient is registered, by either a `ClinicAdmin` or `FrontDeskStaff`, with a `clinic_id`, a `legal_name`, a `date_of_birth` (an ISO date in `YYYY-MM-DD` form), and a `phone` for reminders. The patient also carries a system field, `demographics_revision`, which starts at 1 and bumps every time a demographics sync commits new demographics into this patient of record (§3.9).

Scheduling an appointment, again by a `ClinicAdmin` or `FrontDeskStaff`, links a `clinic_id`, a `provider_id`, and a `patient_id`, and fixes the visit window with `start_utc` and `end_utc` (the end must be strictly after the start). The caller may also supply `plan_default_copay_cents`, the plan's posted office-visit copay used for a forward-looking estimate, which is non-negative and defaults to 0. At creation the system computes a `provisional_copay_cents` estimate: because no insurance card or eligibility data exists yet, the estimate deliberately ignores deductible and coinsurance and simply uses the posted office-visit copay, `plan_default_copay_cents`, as the provisional figure. This forward-looking estimate is the dual-variant partner of the chronological finalized figure computed later (§3.6); for the same visit the two can diverge, because the estimate uses only the posted copay while the finalized figure applies the full multi-leg split.

Before an appointment is accepted, the system checks the provider's calendar for a collision. Each existing appointment for that provider whose `status` is not `CANCELLED` occupies the half-open interval that runs from its `start_utc` up to, but not including, its `end_utc` plus the provider's `cleanup_buffer_minutes`. The new appointment's half-open interval, from its `start_utc` up to but not including its `end_utc`, collides if it overlaps any occupied interval. Because the intervals are half-open, mere touching at a single instant does not collide: if an existing appointment's end plus buffer equals the new appointment's start, that is allowed. A genuine overlap is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`. An appointment's `status` is system-managed, begins at `SCHEDULED`, becomes `INTAKE_OPENED` when an intake session is opened against it, and is `CANCELLED` if the appointment is cancelled.

### 3.3. Opening the Intake Session and Its Two Dimensions

A `ClinicAdmin` or `FrontDeskStaff` opens an intake session by supplying an `appointment_id`; one open session is intended per appointment. On creation the system copies `clinic_id`, `provider_id`, and `patient_id` from the appointment onto the session, stamps `expires_at` as described in §2.6, transitions the parent appointment's `status` to `INTAKE_OPENED`, and initializes the two status dimensions.

The first dimension, `workflow_status`, tracks the physical intake and starts at `DRAFT`. Its terminal states are `COMPLETED`, `EXPIRED`, and `CANCELLED`. The second dimension, `financial_status`, tracks the money and starts at `PENDING_ELIGIBILITY`; its terminal states are `COPAY_SETTLED` and `WAIVED`. The two dimensions advance independently. The session also exposes two computed fields: `forms_complete`, a boolean readiness flag described in §3.4, and `final_patient_responsibility_cents`, the finalized amount the patient owes, which is null until eligibility resolves and is computed as described in §3.6.

The moment any child form is first created against a `DRAFT` session — an insurance card, a consent document, or a questionnaire response — the session automatically advances `workflow_status` from `DRAFT` to `IN_PROGRESS`, provided the session is still `DRAFT` and not expired. If the session is already at or past its expiry instant, the operation is rejected with `ERR_SESSION_EXPIRED` rather than advancing.

When a session is `READY_FOR_VISIT`, a `FrontDeskStaff` member checks the patient in, advancing `workflow_status` from `READY_FOR_VISIT` to `CHECKED_IN`. Check-in is rejected with `ERR_SESSION_NOT_READY` if the session is not in `READY_FOR_VISIT`, and rejected with `ERR_CONSENT_NOT_SIGNED` if any required consent for the session is not currently `SIGNED`. Later, a `FrontDeskStaff` member completes the session, advancing it from `CHECKED_IN` to `COMPLETED`. Completion is rejected with `ERR_SESSION_NOT_CHECKED_IN` when the session is not `CHECKED_IN`, with `ERR_QUEUE_ENTRY_NOT_DONE` when the session's queue entry has not reached `DONE`, and with `ERR_COPAY_UNSETTLED` when `financial_status` is still `COPAY_DUE` (completion requires the financial dimension to be one of `COPAY_SETTLED`, `WAIVED`, `INSURED`, or `SELF_PAY`).

A `FrontDeskStaff` member may cancel a session while its `workflow_status` is `DRAFT`, `IN_PROGRESS`, or `READY_FOR_VISIT`; a cancel attempt from any other state is rejected with `ERR_SESSION_NOT_CANCELLABLE`. Cancellation moves `workflow_status` to `CANCELLED` and cascades: if a non-terminal queue entry exists, it is moved to `NO_SHOW` and the clinic's `active_queue_count` is decremented and the clinic's `version` incremented; and every `SCHEDULED` reminder for the session is moved to `CANCELLED`. (When the cancel happens from `READY_FOR_VISIT`, the queue entry that gets no-showed is precisely the `WAITING` entry that readiness enqueued.)

### 3.4. Forms Completeness and Automatic Readiness

The session's `forms_complete` flag is recomputed whenever a consent is signed or revoked, the questionnaire is accepted or revised, or eligibility resolves. It is true only when all three of the following hold. First, consents are complete: for every code in the provider's `required_consent_codes` there exists a consent document for this session with that `consent_code` and a `status` of `SIGNED`. Second, the questionnaire is complete: either the provider's `questionnaire_required_sections` is empty, or the session has a questionnaire response whose `status` is `ACCEPTED` — note that a `FLAGGED` questionnaire does not count as complete. Third, eligibility is resolved: the session's insurance card has an `eligibility_status` of either `ELIGIBLE` or `INELIGIBLE` — the states `VERIFYING`, `UNVERIFIED`, and `NEEDS_REVIEW` do not satisfy this. A provider with an empty `required_consent_codes` makes the consent condition trivially true, and a provider with an empty `questionnaire_required_sections` makes the questionnaire condition trivially true.

Whenever `forms_complete` recomputes to true, the system attempts to advance the session from `IN_PROGRESS` to `READY_FOR_VISIT`. This advance also requires the financial gate to be met: `financial_status` must be one of `INSURED`, `SELF_PAY`, `COPAY_SETTLED`, or `WAIVED` — in other words, eligibility has resolved and any copay is no longer outstanding. If forms are complete but the financial dimension is still `PENDING_ELIGIBILITY` or `COPAY_DUE`, the readiness advance does not happen, and an explicit attempt to force it is rejected with `ERR_COPAY_REQUIRED_BEFORE_READY`. When the advance does occur, it is more than a status flip: the system automatically enqueues the session by creating one `KioskQueueEntry` with `status` `WAITING` for the session, increments the clinic's `active_queue_count` by one, and increments the clinic's `version`.

### 3.5. Insurance Capture and the Eligibility Verification Loop

A `FrontDeskStaff` member captures an insurance card against a session by supplying the `intake_session_id`, the `payer_name`, and the `member_id`. The card also accepts the financial inputs that drive the responsibility calculation, each non-negative and defaulting to 0: `plan_copay_cents` (the copay printed on the card), `plan_coinsurance_pct` (the medical coinsurance percentage from 0 to 100 applied to the above-deductible portion of the allowed amount), `facility_coinsurance_pct` (the facility coinsurance percentage from 0 to 100 applied to the clinic's facility fee), `remaining_deductible_cents` (the deductible the member still owes before coinsurance applies), and `visit_allowed_amount_cents` (the plan's allowed amount for the visit, the basis for coinsurance). Capturing the first card against a `DRAFT` session advances the session to `IN_PROGRESS` as described in §3.3. A card's `eligibility_status` starts at `UNVERIFIED`.

Verification is a loop. A `FrontDeskStaff` member begins verification, moving `eligibility_status` to `VERIFYING`; this is allowed only when the status is currently `UNVERIFIED` or `NEEDS_REVIEW` (otherwise `ERR_CARD_NOT_VERIFIABLE`) and only when the parent session is neither expired nor cancelled (otherwise `ERR_SESSION_EXPIRED`). The clerk then resolves the verification by supplying an `outcome`, which must be one of `ELIGIBLE`, `INELIGIBLE`, or `NEEDS_REVIEW`; any other value is rejected with `ERR_INVALID_OUTCOME`. Resolution is allowed only from `VERIFYING` (otherwise `ERR_CARD_NOT_VERIFYING`). Each resolution writes an append-only `EligibilityCheck` record carrying the `insurance_card_id` it was run against, the `intake_session_id` copied from the card, the `outcome`, and a `provisional_responsibility_cents` figure computed under the deductible-unmet assumption described in §3.6. Resolving also increments the session's `version`.

The three outcomes diverge. An `ELIGIBLE` outcome moves the card to `ELIGIBLE`, computes the session's `final_patient_responsibility_cents` via the four-leg split in §3.6, and cascades the session's `financial_status`: to `INSURED` if the finalized responsibility is exactly 0, or to `COPAY_DUE` if it is greater than 0. An `INELIGIBLE` outcome moves the card to `INELIGIBLE`, then runs a cascade chain: the session's `final_patient_responsibility_cents` is recomputed at the self-pay rate (the full allowed amount plus the facility fee, with no plan offset and no coinsurance), and the session's `financial_status` becomes `SELF_PAY`. A `NEEDS_REVIEW` outcome moves the card to `NEEDS_REVIEW` and records the check, but does not resolve eligibility; from `NEEDS_REVIEW` the clerk may begin verification again, forming the re-verification cycle.

### 3.6. Patient Responsibility, Coinsurance, and Rounding Order

The finalized patient responsibility is computed the moment eligibility resolves, and it is the most intricate calculation in the system. The inputs are the insurance card being resolved, the clinic's `facility_fee_cents`, the clinic's `copay_rounding` policy, and the resolved `outcome`.

When the outcome is `INELIGIBLE`, the patient is self-pay: `final_patient_responsibility_cents` is the visit's allowed amount plus the facility fee — that is, `visit_allowed_amount_cents` added to `facility_fee_cents` — with no plan offset and no coinsurance. Both inputs are integer cents, so no rounding is needed.

When the outcome is `ELIGIBLE`, the responsibility is the sum of five legs, of which three are integer and two are fractional, and no allowed-amount cap is applied to the combined sum. The three integer legs are: the **copay leg**, which is the smaller of `plan_copay_cents` and `visit_allowed_amount_cents`; the **deductible leg**, which is the smaller of `remaining_deductible_cents` and `visit_allowed_amount_cents`; and the flat `facility_fee_cents`. The two fractional legs are coinsurance. To compute them, first find the above-deductible portion of the allowed amount: subtract `remaining_deductible_cents` from `visit_allowed_amount_cents`, and if that difference is negative use 0 instead (take the larger of that difference and 0). The **medical coinsurance leg** is that above-deductible portion multiplied by `plan_coinsurance_pct` and divided by 100. The **facility coinsurance leg** is `facility_fee_cents` multiplied by `facility_coinsurance_pct` and divided by 100.

The clinic's `copay_rounding` policy pins how the two fractional legs are rounded relative to the sum. Under `PER_LINE_THEN_SUM` (the default), each fractional leg is rounded half up to a whole cent on its own, and then the total is the copay leg plus the deductible leg plus the facility fee plus the rounded medical coinsurance leg plus the rounded facility coinsurance leg. Under `SUM_THEN_ROUND`, the copay leg, the deductible leg, the facility fee, and both unrounded fractional legs are added together first, and the single resulting sum is rounded half up to a whole cent. The order matters: with two fractional legs each ending in exactly half a cent — say one equal to 100.5 and the other to 50.5 — per-line rounding lifts each up (101 plus 51) while sum-then-round rounds the combined 151.0 (which stays 151), so the two policies differ by exactly one cent. The finalized result is `final_patient_responsibility_cents`.

This finalized figure has a sibling provisional figure that is recorded on each `EligibilityCheck` as `provisional_responsibility_cents`. The provisional figure assumes the full deductible is still unmet, so coinsurance is never reached: it is the copay leg plus the deductible leg plus the facility fee — that is, the smaller of `plan_copay_cents` and the allowed amount, plus the smaller of `remaining_deductible_cents` and the allowed amount, plus `facility_fee_cents` — with both coinsurance legs treated as zero. For the same card with above-deductible exposure, the finalized figure exceeds the provisional one because the finalized figure adds the coinsurance legs. Both of these differ in turn from the forward-looking `provisional_copay_cents` estimate on the appointment (§3.2), which uses only `plan_default_copay_cents`.

### 3.7. Consent and HIPAA E-Signature

A `FrontDeskStaff` member issues a consent document for a session by supplying the `intake_session_id` and a `consent_code`. The code must be one that the provider actually requires: if the `consent_code` is not present in the provider's `required_consent_codes`, the issuance is rejected with `ERR_CONSENT_CODE_NOT_REQUIRED`. Issuing the first form against a `DRAFT` session advances it to `IN_PROGRESS`. A consent document carries a `signer_name` (the typed legal name captured at signing, optional until signing), a `signed_at` timestamp (null until signed), a `revision` counter (starting at 1, bumped on each re-issue), and a `status` that begins at `PENDING`.

A `Patient` signs a pending consent by submitting `signer_name`. Signing requires the document to be `PENDING` (otherwise `ERR_CONSENT_NOT_PENDING`), requires the parent session to be in none of `EXPIRED`, `CANCELLED`, or `COMPLETED` and to still be before its expiry instant (otherwise `ERR_SESSION_EXPIRED`), and requires a present, non-empty `signer_name` (otherwise `ERR_INVALID_REQUEST`). On success the document moves to `SIGNED` and `signed_at` is set to the clinic's `current_utc`. Signing then bubbles up: the session's `forms_complete` is recomputed, and if it flips true and the financial gate is met the session advances to `READY_FOR_VISIT`, which itself enqueues a queue entry as in §3.4.

A `Patient` may revoke a signed consent. Revocation requires the document to be `SIGNED` (otherwise `ERR_CONSENT_NOT_SIGNED`) and requires the parent session not to be `CHECKED_IN` or `COMPLETED` (otherwise `ERR_SESSION_LOCKED`). Revocation moves the document to `REVOKED` and clears `signed_at` back to null. It also bubbles up: `forms_complete` is recomputed and is now false, and if the session was `READY_FOR_VISIT` it is reverted to `IN_PROGRESS` and its `WAITING` queue entry is moved to `NO_SHOW`, decrementing the clinic's `active_queue_count` and incrementing the clinic's `version`. Finally, a `FrontDeskStaff` member may re-issue a revoked consent: re-issue requires the document to be `REVOKED` (otherwise `ERR_CONSENT_NOT_REVOKED`) and the parent session not to be expired, cancelled, or completed (otherwise `ERR_SESSION_EXPIRED`). Re-issue moves the document back to `PENDING` and increments its `revision`, closing the `PENDING` → `SIGNED` → `REVOKED` → `PENDING` cycle.

### 3.8. The Medical-History Questionnaire and Risk Scoring

A `FrontDeskStaff` member or a `Patient` starts the questionnaire for a session by supplying the `intake_session_id` and optionally an initial `answered_sections` array. There is one questionnaire response per session. Each entry in `answered_sections` carries a `section_key` and a `risk_weight` integer between 0 and 10. Starting the questionnaire against a `DRAFT` session advances it to `IN_PROGRESS`. The response exposes a `provisional_risk_score` (defaulting to 0), a `final_risk_score` (null until accepted), a `high_risk_flag` boolean (defaulting to false), and a `status` that begins at `DRAFT`. While in `DRAFT`, a `Patient` or `FrontDeskStaff` member may replace the `answered_sections` via an update; an update attempt on a questionnaire that is not `DRAFT` is rejected with `ERR_QUESTIONNAIRE_NOT_DRAFT`.

A `Patient` submits the questionnaire, moving it from `DRAFT` to `SUBMITTED`; submission requires the `DRAFT` status (otherwise `ERR_QUESTIONNAIRE_NOT_DRAFT`) and a non-expired, non-cancelled parent session (otherwise `ERR_SESSION_EXPIRED`). On submit, the `provisional_risk_score` is computed as the plain sum of the `risk_weight` values across all `answered_sections`.

A `FrontDeskStaff` member accepts a submitted questionnaire. Acceptance requires the `SUBMITTED` status (otherwise `ERR_QUESTIONNAIRE_NOT_SUBMITTED`) and requires that `answered_sections` cover every key in the provider's `questionnaire_required_sections` (otherwise `ERR_QUESTIONNAIRE_INCOMPLETE`). On acceptance the system computes the `final_risk_score` as a weighted sum: each answered section contributes its `risk_weight` multiplied by a factor of 2 when its `section_key` is one of the provider's `questionnaire_required_sections`, and multiplied by 1 otherwise; the weighted sum is rounded half up to an integer. The `high_risk_flag` is set true when the `final_risk_score` is at least 20, and false otherwise. The destination state then branches on risk: if the final score is below 20 (the flag is false) the questionnaire lands in `ACCEPTED`; if the final score is at least 20 (the flag is true) it lands in `FLAGGED` instead. Both branches compute `final_risk_score` and set `high_risk_flag` identically — only the destination differs. Acceptance that lands in `ACCEPTED` bubbles up `forms_complete` and may trigger readiness; a questionnaire in `FLAGGED` does not satisfy `forms_complete`.

A `Patient` may revise a questionnaire that is `SUBMITTED` or `FLAGGED`, moving it back to `DRAFT`; a revise attempt from any other state is rejected with `ERR_QUESTIONNAIRE_NOT_REVISABLE`. Revising clears `final_risk_score` back to null and `high_risk_flag` back to false, reopening the `DRAFT` → `SUBMITTED` → `FLAGGED` → `DRAFT` cycle.

### 3.9. Demographics Sync to the Patient of Record

A `FrontDeskStaff` member synchronizes the session's collected demographics into the patient of record. The request supplies the `intake_session_id`, an `idempotency_key`, a `synced_legal_name`, and a `synced_phone`. The job carries a `status` that begins at `QUEUED`. When the `idempotency_key` has not been used on this session, the job commits: its `status` becomes `COMMITTED`, the patient's `legal_name` and `phone` are overwritten with the synced snapshot, and the patient's `demographics_revision` is incremented by one. When the `idempotency_key` has already been used on this session, the job is a duplicate: no new job is created and no patient mutation occurs, and the original job is returned with its `status` shown as `SKIPPED_DUPLICATE` in that response. The override applies only to the returned representation; the stored original job is not mutated and retains its persisted `status` (e.g. `COMMITTED`), `updated_at`, and `version`.

### 3.10. Copay Collection, Capture, and Compensation

The copay money path is owned by a `BillingClerk`. Authorizing a copay payment supplies the `intake_session_id`, the `amount_cents` being authorized, and `expected_intake_session_version`. The optimistic-concurrency check on the session version runs first, as described in §2.7, and a mismatch rejects with `ERR_STALE_SESSION_VERSION`. The session's financial dimension must be `COPAY_DUE`; if it is not, the authorization is rejected with `ERR_COPAY_NOT_DUE`. The authorized `amount_cents` must equal the session's `final_patient_responsibility_cents`; a mismatch is rejected with `ERR_COPAY_AMOUNT_MISMATCH`. A new payment begins at `AUTHORIZED` and exposes a `refunded_cents` field that is 0 until a refund occurs.

Capturing an authorized payment moves it from `AUTHORIZED` to `CAPTURED`; capture requires the `AUTHORIZED` status (otherwise `ERR_PAYMENT_NOT_AUTHORIZED`), requires the session's `financial_status` to still be `COPAY_DUE` (otherwise `ERR_COPAY_NOT_DUE`), and requires the captured `amount_cents` to equal the session's `final_patient_responsibility_cents` (otherwise `ERR_COPAY_AMOUNT_MISMATCH`). On capture, the clinic's `collected_copay_cents` ledger is credited by `amount_cents`, and the session's `financial_status` cascades from `COPAY_DUE` to `COPAY_SETTLED`. Alternatively, a `BillingClerk` may void an authorized payment, moving it from `AUTHORIZED` to `VOIDED` (requires `AUTHORIZED`, otherwise `ERR_PAYMENT_NOT_AUTHORIZED`).

Refunding compensates a captured payment. A refund moves it from `CAPTURED` to `REFUNDED`; it requires the `CAPTURED` status (otherwise `ERR_PAYMENT_NOT_CAPTURED`), sets `refunded_cents` to the payment's `amount_cents`, debits the clinic's `collected_copay_cents` ledger by `amount_cents` (so the net of capture plus refund is zero), and cascades the session's `financial_status` from `COPAY_SETTLED` back to `COPAY_DUE`.

Separately, a `BillingClerk` may waive a copay that is due, moving the session's `financial_status` from `COPAY_DUE` to `WAIVED`. Waiving requires the financial dimension to be `COPAY_DUE` (otherwise `ERR_COPAY_NOT_DUE`) and is blocked when the session's questionnaire response has `high_risk_flag` set true — in that case the waive is rejected with `ERR_WAIVE_BLOCKED_HIGH_RISK`. A session with no questionnaire is not blocked on this ground.

### 3.11. The Kiosk Queue and Room Booking

A queue entry is created automatically when the session becomes ready (§3.4); it is not created by an explicit client call. The entry references its session via `intake_session_id`, copies the `clinic_id` from the session, carries an `exam_room_id` that is null while `WAITING` and assigned when called, and is stamped with a monotonic per-clinic `enqueued_seq` that fixes FIFO ordering. Its `status` begins at `WAITING`. One active entry is intended per session.

A `FrontDeskStaff` member calls a waiting patient by supplying an `exam_room_id`, moving the entry from `WAITING` to `CALLED` and assigning that room. Calling requires the entry to be `WAITING` (otherwise `ERR_QUEUE_ENTRY_NOT_WAITING`), requires the parent session's `workflow_status` to be `READY_FOR_VISIT` or `CHECKED_IN` (otherwise `ERR_SESSION_NOT_READY`), and requires the referenced exam room to belong to the same clinic as the session (otherwise `ERR_ROOM_CLINIC_MISMATCH`). The clerk then rooms-in the patient, moving the entry from `CALLED` to `IN_ROOM` (requires `CALLED`, otherwise `ERR_QUEUE_ENTRY_NOT_CALLED`), and later marks the visit done, moving it from `IN_ROOM` to `DONE` (requires `IN_ROOM`, otherwise `ERR_QUEUE_ENTRY_NOT_IN_ROOM`); reaching `DONE` decrements the clinic's `active_queue_count` and increments the clinic's `version`. At any point while the entry is `WAITING` or `CALLED`, the clerk may mark it a no-show, moving it to `NO_SHOW` (requires `WAITING` or `CALLED`, otherwise `ERR_QUEUE_ENTRY_NOT_ACTIVE`); reaching `NO_SHOW` likewise decrements the clinic's `active_queue_count` and increments the clinic's `version`.

A `FrontDeskStaff` member books an exam room for a window by supplying the `exam_room_id`, the `queue_entry_id`, the booking's `start_utc` and `end_utc` (end strictly after start), and `expected_exam_room_version`. The optimistic-concurrency check on the room version runs first (§2.7), rejecting a mismatch with `ERR_STALE_ROOM_VERSION`. Room bookings use closed-interval overlap semantics that differ from the provider check: each existing booking for the room occupies the closed interval from its `start_utc` through its `end_utc` inclusive, no buffer is applied, and a new booking collides only if its closed interval overlaps an existing one on more than a single shared endpoint. Adjacency is allowed — when an existing booking's end equals the new booking's start the gap is zero and that is permitted — but any strictly-interior overlap is rejected with `ERR_ROOM_DOUBLE_BOOKED`. A successful booking increments the room's `version`.

### 3.12. Reminders, Quiet Hours, and the Clock Sweep

A `FrontDeskStaff` member schedules a reminder against a session by supplying the `intake_session_id`, a `target_kind` (one of `CONSENT`, `QUESTIONNAIRE`, `COPAY`, or `GENERIC`, which selects the incomplete step the reminder nudges), the `scheduled_utc` instant at which it should fire, and `scheduled_local_min`, the minutes-from-midnight in clinic-local time corresponding to that instant. A reminder's `status` begins at `SCHEDULED`.

Two checks gate scheduling. First, quiet hours: `scheduled_local_min` must not fall inside the clinic's wrap-around quiet window, which runs from `reminder_quiet_start_min` inclusive up to `reminder_quiet_end_min` exclusive and wraps past midnight. A scheduled local minute inside that window is rejected with `ERR_REMINDER_IN_QUIET_HOURS`. Second, minimum gap: the `scheduled_utc` must be at least the clinic's `reminder_min_gap_minutes` away from every other non-cancelled reminder on the same session; a reminder too close to an existing one is rejected with `ERR_REMINDER_TOO_CLOSE`. A `FrontDeskStaff` member may cancel a scheduled reminder, moving it from `SCHEDULED` to `CANCELLED` (requires `SCHEDULED`, otherwise `ERR_REMINDER_NOT_SCHEDULED`).

Reminders and expirations come to life through the clock. When a `ClinicAdmin` sets the clinic clock, the request names the clinic via `clinic_id` and supplies the new instant as `to_iso8601`; the system stores that instant as the clinic's `current_utc` and then runs two sweeps over the clinic. The expiration sweep moves every `DRAFT` or `IN_PROGRESS` session whose `current_utc` is at or after its `expires_at` to `EXPIRED`; as that session expires, every `SCHEDULED` reminder on it is moved to `SUPPRESSED`, while any `PENDING` consent stays `PENDING` (signing it later is simply blocked by expiry). The reminder sweep then examines every `SCHEDULED` reminder whose `current_utc` is at or after its `scheduled_utc`: if the parent session is not `EXPIRED`, `CANCELLED`, or `COMPLETED` and the reminder's target step is still incomplete, the reminder is moved to `SENT`; if instead the target step is already complete or the parent session has expired, the reminder is moved to `SUPPRESSED`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that read a resource or drive a state transition on an existing resource return a `200 OK` status code. The clock endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the deterministic clinic clock and run the expiration and reminder sweeps | ClinicAdmin |
| POST | `/clinics` | Create a clinic | ClinicAdmin |
| GET | `/clinics/{id}` | Get a clinic | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/clinics` | List clinics | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/providers` | Create a provider | ClinicAdmin |
| GET | `/providers/{id}` | Get a provider | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/providers` | List providers, filterable by clinic | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/exam-rooms` | Create an exam room | ClinicAdmin |
| GET | `/exam-rooms/{id}` | Get an exam room | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/exam-rooms` | List exam rooms, filterable by clinic | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/patients` | Register a patient | ClinicAdmin, FrontDeskStaff |
| GET | `/patients/{id}` | Get a patient | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/patients` | List patients, filterable by clinic | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/appointments` | Schedule an appointment | ClinicAdmin, FrontDeskStaff |
| GET | `/appointments/{id}` | Get an appointment | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/appointments` | List appointments, filterable by clinic / provider / patient | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/intake-sessions` | Open an intake session for an appointment | ClinicAdmin, FrontDeskStaff |
| GET | `/intake-sessions/{id}` | Get an intake session | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/intake-sessions` | List intake sessions, filterable by appointment / clinic / provider / patient | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/intake-sessions/{id}/check-in` | Check the patient in | FrontDeskStaff |
| POST | `/intake-sessions/{id}/complete` | Complete the intake session | FrontDeskStaff |
| POST | `/intake-sessions/{id}/cancel` | Cancel the intake session | FrontDeskStaff |
| POST | `/intake-sessions/{id}/waive-copay` | Waive the copay | BillingClerk |
| POST | `/insurance-cards` | Capture an insurance card for a session | FrontDeskStaff |
| GET | `/insurance-cards/{id}` | Get an insurance card | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/insurance-cards` | List insurance cards, filterable by session | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/insurance-cards/{id}/verify` | Begin eligibility verification | FrontDeskStaff |
| POST | `/insurance-cards/{id}/resolve-eligibility` | Resolve verification with a payer outcome | FrontDeskStaff |
| GET | `/eligibility-checks/{id}` | Get an eligibility check record | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/eligibility-checks` | List eligibility checks, filterable by card or session | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/consent-documents` | Issue a consent / HIPAA form for a session | FrontDeskStaff |
| GET | `/consent-documents/{id}` | Get a consent document | ClinicAdmin, FrontDeskStaff, BillingClerk, Patient |
| GET | `/consent-documents` | List consent documents, filterable by session | ClinicAdmin, FrontDeskStaff, BillingClerk, Patient |
| POST | `/consent-documents/{id}/sign` | Apply the e-signature | Patient |
| POST | `/consent-documents/{id}/revoke` | Revoke a signed consent | Patient |
| POST | `/consent-documents/{id}/reissue` | Re-issue a revoked consent | FrontDeskStaff |
| POST | `/questionnaire-responses` | Start the medical-history questionnaire | FrontDeskStaff, Patient |
| GET | `/questionnaire-responses/{id}` | Get a questionnaire response | ClinicAdmin, FrontDeskStaff, BillingClerk, Patient |
| GET | `/questionnaire-responses` | List questionnaire responses, filterable by session | ClinicAdmin, FrontDeskStaff, BillingClerk, Patient |
| PATCH | `/questionnaire-responses/{id}` | Update answered sections while in draft | Patient, FrontDeskStaff |
| POST | `/questionnaire-responses/{id}/submit` | Submit the questionnaire | Patient |
| POST | `/questionnaire-responses/{id}/accept` | Accept a submitted questionnaire | FrontDeskStaff |
| POST | `/questionnaire-responses/{id}/revise` | Revise a submitted or flagged questionnaire | Patient |
| POST | `/copay-payments` | Authorize a copay payment | BillingClerk |
| GET | `/copay-payments/{id}` | Get a copay payment | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/copay-payments` | List copay payments, filterable by session | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/copay-payments/{id}/capture` | Capture an authorized copay | BillingClerk |
| POST | `/copay-payments/{id}/void` | Void an authorized copay | BillingClerk |
| POST | `/copay-payments/{id}/refund` | Refund a captured copay | BillingClerk |
| GET | `/queue-entries/{id}` | Get a kiosk queue entry | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/queue-entries` | List queue entries, filterable by session / clinic / exam room / status | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/queue-entries/{id}/call` | Call a waiting patient and assign a room | FrontDeskStaff |
| POST | `/queue-entries/{id}/room-in` | Move a called patient into the room | FrontDeskStaff |
| POST | `/queue-entries/{id}/done` | Mark the visit done | FrontDeskStaff |
| POST | `/queue-entries/{id}/no-show` | Mark a waiting or called patient a no-show | FrontDeskStaff |
| POST | `/room-bookings` | Book an exam room for a window | FrontDeskStaff |
| GET | `/room-bookings/{id}` | Get a room booking | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/room-bookings` | List room bookings, filterable by room or queue entry | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/reminders` | Schedule a reminder | FrontDeskStaff |
| GET | `/reminders/{id}` | Get a reminder | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/reminders` | List reminders, filterable by session | ClinicAdmin, FrontDeskStaff, BillingClerk |
| POST | `/reminders/{id}/cancel` | Cancel a scheduled reminder | FrontDeskStaff |
| POST | `/demographics-sync-jobs` | Sync session demographics to the patient of record | FrontDeskStaff |
| GET | `/demographics-sync-jobs/{id}` | Get a demographics sync job | ClinicAdmin, FrontDeskStaff, BillingClerk |
| GET | `/demographics-sync-jobs` | List demographics sync jobs, filterable by session | ClinicAdmin, FrontDeskStaff, BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CLINIC_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_EXAM_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_INSURANCE_CARD_NOT_FOUND` | 404 Not Found |
| `ERR_ELIGIBILITY_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_CONSENT_NOT_FOUND` | 404 Not Found |
| `ERR_QUESTIONNAIRE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_QUEUE_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_REMINDER_NOT_FOUND` | 404 Not Found |
| `ERR_SYNC_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_SESSION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ROOM_VERSION` | 412 Precondition Failed |
| `ERR_SESSION_EXPIRED` | 409 Conflict |
| `ERR_SESSION_LOCKED` | 409 Conflict |
| `ERR_SESSION_NOT_READY` | 409 Conflict |
| `ERR_SESSION_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_SESSION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_COPAY_REQUIRED_BEFORE_READY` | 409 Conflict |
| `ERR_CARD_NOT_VERIFIABLE` | 409 Conflict |
| `ERR_CARD_NOT_VERIFYING` | 409 Conflict |
| `ERR_INVALID_OUTCOME` | 400 Bad Request |
| `ERR_CONSENT_CODE_NOT_REQUIRED` | 409 Conflict |
| `ERR_CONSENT_NOT_PENDING` | 409 Conflict |
| `ERR_CONSENT_NOT_SIGNED` | 409 Conflict |
| `ERR_CONSENT_NOT_REVOKED` | 409 Conflict |
| `ERR_QUESTIONNAIRE_NOT_DRAFT` | 409 Conflict |
| `ERR_QUESTIONNAIRE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_QUESTIONNAIRE_NOT_REVISABLE` | 409 Conflict |
| `ERR_QUESTIONNAIRE_INCOMPLETE` | 409 Conflict |
| `ERR_COPAY_NOT_DUE` | 409 Conflict |
| `ERR_COPAY_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_PAYMENT_NOT_CAPTURED` | 409 Conflict |
| `ERR_COPAY_UNSETTLED` | 409 Conflict |
| `ERR_WAIVE_BLOCKED_HIGH_RISK` | 403 Forbidden |
| `ERR_QUEUE_ENTRY_NOT_WAITING` | 409 Conflict |
| `ERR_QUEUE_ENTRY_NOT_CALLED` | 409 Conflict |
| `ERR_QUEUE_ENTRY_NOT_IN_ROOM` | 409 Conflict |
| `ERR_QUEUE_ENTRY_NOT_ACTIVE` | 409 Conflict |
| `ERR_QUEUE_ENTRY_NOT_DONE` | 409 Conflict |
| `ERR_ROOM_CLINIC_MISMATCH` | 409 Conflict |
| `ERR_PROVIDER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_REMINDER_IN_QUIET_HOURS` | 409 Conflict |
| `ERR_REMINDER_TOO_CLOSE` | 409 Conflict |
| `ERR_REMINDER_NOT_SCHEDULED` | 409 Conflict |
