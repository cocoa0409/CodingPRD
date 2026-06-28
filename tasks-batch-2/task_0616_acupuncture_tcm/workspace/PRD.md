# Acupuncture & Traditional Chinese Medicine Clinic API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the back-office API of an acupuncture and Traditional Chinese Medicine (TCM) clinic. The platform unifies several operational threads that, in a paper-and-spreadsheet practice, drift apart and create reconciliation headaches: patient intake and TCM pattern diagnosis (tongue and pulse findings), the point-prescription treatment plan that flows from a finalized diagnosis, the booking of recurring sessions against shared treatment rooms and licensed practitioners, the consumption of prepaid session packages versus per-visit billing, the dispensing of herbal formulas against a conserved inventory, and the financial settlement of each visit through either a cash discount or an insurance superbill.

The central design tension this API resolves is reconciliation under two simultaneous viewpoints. A package of prepaid credits must be tracked both forward-looking (what is still bookable after accounting for sessions already reserved) and chronologically (what has actually been realized through completed visits). A no-show or a late cancellation must trigger a penalty whose size depends on the patient's prior history and membership standing, while a cancellation that ripples outward must release reserved package credits, void add-ons, and reverse any billing artifacts already produced. Herbal inventory must be conserved exactly across fill and reversal events. Every mutation is versioned for optimistic concurrency, and a logical clock — never wall-clock time — governs all time-sensitive determinations such as lateness and arrival classification.

The reader should treat the workflows in Section 3 as the authoritative narrative of system behavior; Sections 4 and 5 only summarize the HTTP surface and the error vocabulary. Field names, calculation formulas, state transitions, and the conditions that trigger each error are described in prose throughout Sections 2 and 3 and must be assembled from there.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH`. The system recognizes exactly four roles, spelled precisely as follows: `ClinicAdmin`, `Practitioner`, `Pharmacist`, and `Patient`. When a request is authenticated but the declared role is not permitted to perform the requested operation, the system responds with `ERR_FORBIDDEN_ROLE`.

The four roles differ in how their `X-User-ID` relates to persisted data. When `X-User-Role` is `Practitioner`, `X-User-ID` is the `id` of the acting `Practitioner`; ownership checks on any resource that references a `Practitioner` compare the resource's practitioner foreign key to `X-User-ID` — for example, plan, intake, and appointment-completion operations require that the acting practitioner own the `TreatmentPlan` via its `practitioner_id`. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's `patient_id` to `X-User-ID`, so a patient may read only their own clinical and billing records. When either an entity-backed actor's `X-User-ID` fails to match the owning entity's id on a resource they are required to own, the request is rejected with `ERR_OWNERSHIP_MISMATCH`. When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `Pharmacist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter skips the given number of items and defaults to 0.

Unless otherwise specified, list endpoints return resources sorted by their creation timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource — `Patient`, `Intake`, `TreatmentPlan`, `PackageSeries`, `Practitioner`, `TreatmentRoom`, `Appointment`, `AddOn`, `HerbalFormula`, `HerbItem`, `FormulaDispense`, `Charge`, and `Superbill` — carries a server-minted `id` formatted as a UUID with no type prefix, used for identity only. Each also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created. All of these resources additionally carry an `updated_at` timestamp, refreshed on every mutation including those produced by cascades, and an integer `version` that begins at 1 and increases by one on every mutation, again including cascades. The `version` field is the basis for optimistic concurrency control described in Section 2.6. All entities in this system carry the full complement of `id`, `created_at`, `updated_at`, and `version`; none is restricted to `id` and `created_at` alone.

All time-sensitive logic in the system reads from a server logical clock rather than the host's wall clock. At startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and before any client call it reads precisely this default and never falls back to wall-clock time. An administrative test-driving capability advances the logical clock to a supplied `to_iso8601` instant and echoes back the new `current_utc`. Check-in timestamps, lateness determinations, and late-cancellation determinations all read the logical clock as their notion of "now".

### 2.5. Precision, Rounding, and Monetary Representation

All monetary amounts are stored and computed as integer cents; there are no fractional cents. Wherever a calculation multiplies cents by a fractional rate — the cash discount, the per-line insurance allowance, and the penalty multiplier — the result is rounded to the nearest whole cent using the round-half-up convention (a value whose fractional part is exactly one half rounds upward). Inventory quantities are integer grams, and credit balances are integer counts; neither admits fractional values. Where rounding order matters, it is pinned explicitly in the relevant workflow narrative in Section 3 (notably, insurance allowances are rounded on each line before the lines are summed).

### 2.6. Optimistic Concurrency Control

Two creation operations are guarded against acting on a stale view of their parent `TreatmentPlan`. Booking an appointment requires the request to carry `expected_treatment_plan_version`, which must equal the current `version` of the referenced `TreatmentPlan`. If another writer has advanced the plan's `version` since the client last read it — for instance through a hold, a resume, an earlier booking, or a dispense — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from attaching a visit to a plan it has not observed in its current form. Identically, creating a herbal-formula dispense requires `expected_treatment_plan_version` matching the referenced plan's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Two transition operations are likewise OCC-guarded but against their own resource's version. Cancelling a treatment plan requires `expected_treatment_plan_version` to match that plan's current `version`, and reversing a filled dispense requires `expected_formula_dispense_version` to match that dispense's current `version`; either mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). All other endpoints do not accept or require a version field and perform no OCC check.

### 2.7. Cascading Consistency and Automatic Reconciliation

A single client action frequently mutates more than one resource, and every such secondary effect must land. When a parent transition forces a child transition — a cancelled plan cancelling its open appointments, a cancelled appointment voiding its add-ons and billing artifacts and releasing package credits — each affected resource has its own `updated_at` refreshed and its own `version` incremented, and any state machine whose entry condition is thereby met re-evaluates automatically without a separate client request on that resource. The most consequential cascades — plan cancellation, appointment cancellation, dispense fill, and dispense reversal — are described step by step in Section 3, including the transitive chains where one secondary effect triggers a third.

### 2.8. Resource Existence and Validation Ordering

The system validates a write request in a fixed priority order, and the first failing check determines the error returned. Authentication of the headers is checked first (`ERR_MISSING_AUTH`), then role permission for the operation (`ERR_FORBIDDEN_ROLE`), then ownership for entity-backed actors acting on resources they must own (`ERR_OWNERSHIP_MISMATCH`). Next, any resource identifiers embedded in the request path are checked for existence in left-to-right order, so that on a path naming more than one resource the earlier identifier's not-found error is returned before the later one is even consulted; depending on the resource this surfaces as `ERR_PATIENT_NOT_FOUND`, `ERR_INTAKE_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_APPT_NOT_FOUND`, `ERR_DISPENSE_NOT_FOUND`, `ERR_PRACTITIONER_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_FORMULA_NOT_FOUND`, or `ERR_HERB_NOT_FOUND`. After path existence, foreign keys supplied in the request body are checked for existence (for booking, plan creation, and dispense creation), again drawing from the not-found vocabulary just listed (`ERR_PRACTITIONER_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_INTAKE_NOT_FOUND`, `ERR_FORMULA_NOT_FOUND`). Only then is the body checked for well-formedness (`ERR_INVALID_REQUEST`): required fields present, enum values legal, the appointment's `scheduled_end` strictly after its `scheduled_start`, every numeric field at or above its minimum, and `coinsurance_rate` within the inclusive range from 0 to 1.

After these foundational checks, state preconditions for the requested transition are evaluated (the various `ERR_*_NOT_*` conflict errors), followed by cross-entity referential rules, then the domain-specific safety, temporal, and fiscal rules, and finally the optimistic-concurrency version check. The precise relative ordering among the later checks for each specific operation is spelled out in the Section 3 workflow that owns the operation.

## 3. Business Logic & Workflows

### 3.1. Registering Patients and Establishing Billing Posture

A `ClinicAdmin` registers a patient by supplying the patient's `full_name` and `date_of_birth` (an ISO date in year-month-day form). The billing posture is captured at registration through `payer_mode`, which is either `CASH` or `INSURANCE` and defaults to `CASH` when omitted. A patient paying through insurance also supplies an `insurance_member_id` (the insurer's member identifier, which is null for cash patients) and a `coinsurance_rate`, a fraction between 0 and 1 inclusive representing the share of each charge the insurer covers; the rate defaults to 0.0 and is only meaningful when `payer_mode` is `INSURANCE`. A newly registered patient begins with `intake_status` of `PENDING_INTAKE`, `membership_status` of `NONE`, and `strike_count` of 0.

Membership standing is adjusted by a `ClinicAdmin` through a dedicated enrollment operation that sets `membership_status` to one of `NONE`, `ACTIVE`, or `LAPSED`; this updates the patient and increments the patient's `version`. An `ACTIVE` membership matters financially because it waives the first no-show or late-cancellation penalty a patient would otherwise incur, as described in Section 3.7. The `strike_count` accumulates no-show and late-cancellation strikes over the patient's history and is never decremented except by the reversal of the very appointment that produced a given strike.

The patient record is readable by a `ClinicAdmin`, a `Practitioner`, or the patient themselves, where a patient reading their own record must present an `X-User-ID` equal to that patient's id.

### 3.2. TCM Intake and Diagnosis

A `Practitioner` opens a new intake for a patient by supplying the `patient_id`, the `chief_complaint` text, and the four diagnostic findings: `tongue_finding` (one of `PALE`, `RED`, `PURPLE`, or `NORMAL`), `tongue_coating` (one of `THIN_WHITE`, `THICK_YELLOW`, `NONE`, or `GREASY`), `pulse_finding` (one of `WIRY`, `SLIPPERY`, `THREADY`, `RAPID`, `DEEP`, or `FLOATING`), and the diagnosed `tcm_pattern` (one of `QI_STAGNATION`, `BLOOD_DEFICIENCY`, `DAMP_HEAT`, `YANG_DEFICIENCY`, or `YIN_DEFICIENCY`). A freshly created intake has `status` of `DRAFT`.

Finalizing the intake is the gate that opens the rest of the clinical workflow. Finalization is permitted only when the intake's `status` is `DRAFT`; an attempt to finalize an intake that is not in `DRAFT` is rejected with `ERR_INTAKE_NOT_DRAFT`. Finalization additionally requires that `tcm_pattern`, `tongue_finding`, and `pulse_finding` all be present (non-null); if any of these three is missing the request is rejected with `ERR_INTAKE_INCOMPLETE`. On success the intake's `status` moves from `DRAFT` to `FINALIZED`, and as a cross-entity side effect the owning patient's `intake_status` flips from `PENDING_INTAKE` to `INTAKE_COMPLETE`, with the patient's `version` incremented by one and the intake's own `version` incremented by one. Intakes may be listed and filtered by `patient_id`, and a single intake may be retrieved by id, with read access available to a `ClinicAdmin`, a `Practitioner`, or the owning patient.

### 3.3. Treatment Plans and the Point Prescription

Once an intake is finalized, a `Practitioner` creates a treatment plan — the point prescription — by supplying the `patient_id`, the prescribing `practitioner_id`, the `intake_id` the plan derives from, the `acupoints` array of point codes (such as LI4 or ST36), and `planned_sessions`, the intended number of sessions, which must be at least 1. A plan may only be created from an intake whose `status` is `FINALIZED` and which belongs to the same patient; a violation is rejected with `ERR_INTAKE_NOT_FINALIZED`. A new plan begins with `status` of `ACTIVE`.

The plan's lifecycle is a revision loop with two terminal exits. From `ACTIVE` a practitioner may place the plan `ON_HOLD`; this is permitted only when the plan's `status` is `ACTIVE`, and otherwise rejected with `ERR_PLAN_NOT_ACTIVE`, and it increments the plan's `version`. While a plan is `ON_HOLD` no appointments and no dispenses may be created against it. From `ON_HOLD` the practitioner may resume the plan back to `ACTIVE`; this is permitted only when the plan's `status` is `ON_HOLD`, otherwise rejected with `ERR_PLAN_NOT_ON_HOLD`, and it increments the plan's `version`. A practitioner may complete an `ACTIVE` plan, moving it to the terminal `COMPLETED` state; completion is permitted only when the plan is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) and only when no appointment of this plan is currently in clinical status `SCHEDULED` or `CHECKED_IN` (otherwise `ERR_PLAN_HAS_OPEN_APPOINTMENTS`); completion increments the plan's `version`.

Cancelling a plan is the most far-reaching plan transition. A practitioner may cancel a plan whose `status` is either `ACTIVE` or `ON_HOLD`; an attempt to cancel a plan in any other status is rejected with `ERR_PLAN_NOT_CANCELLABLE`. Because cancellation is OCC-guarded, the request must carry `expected_treatment_plan_version` matching the plan's current `version`, failing which it is rejected with `ERR_STALE_VERSION`. On success the plan moves to the terminal `CANCELLED` state and its `version` is incremented. The cancellation then cascades: every appointment of this plan whose clinical status is `SCHEDULED` or `CHECKED_IN` is driven to `CANCELLED` through the system cancellation path, which fires that appointment's own full set of cancellation side effects described in Section 3.5 (including add-on voiding, billing voids, and package-credit release). This is the origin of the deepest cascade chain in the system. Plans may be listed and filtered by `patient_id`, `practitioner_id`, or `intake_id`, and a single plan may be retrieved by id, with read access for a `ClinicAdmin`, a `Practitioner`, or the owning patient.

### 3.4. Package Series and the Two Credit Balances

A `ClinicAdmin` sells a prepaid bundle to a patient by purchasing a package series, supplying the owning `patient_id`, the `total_credits` (the number of sessions purchased, which is immutable once bought and must be at least 1), and the `price_paid_cents` (the amount paid for the series, in integer cents). At purchase the series is `ACTIVE` with `reserved_credits` of 0, `consumed_credits` of 0, and both balances equal to `total_credits`.

The crux of package accounting is that a series is reconciled under two distinct balances that are recomputed on any change to an appointment booked from the series — booking, completion, no-show, or cancellation. The `reserved_credits` field is the count of appointments drawn from this series whose clinical status is currently `SCHEDULED` or `CHECKED_IN`. The `consumed_credits` field is the count of appointments drawn from this series whose clinical status has reached `COMPLETED`. Appointments that ended in `CANCELLED` or `NO_SHOW` count toward neither. From these two counts, the **provisional remaining balance** `provisional_remaining_credits` is `total_credits` minus `reserved_credits` minus `consumed_credits` — a forward-looking figure that a still-scheduled appointment already lowers, used to gate new bookings and to drive the exhaustion transition. The **finalized remaining balance** `finalized_remaining_credits` is `total_credits` minus `consumed_credits` alone — a chronological figure that only realized completions lower, used for billing and refund reconciliation; a merely scheduled appointment does not move it.

The series status tracks the provisional balance. When a booking debit drives `provisional_remaining_credits` to exactly 0, the series transitions from `ACTIVE` to `EXHAUSTED`, incrementing the series `version`. Conversely, when a reservation is released — for example by a no-show or a cancellation — and `provisional_remaining_credits` rises above 0 while the series is `EXHAUSTED`, the series transitions automatically from `EXHAUSTED` back to `ACTIVE`, again incrementing the series `version`. A `ClinicAdmin` may cancel a series that is `ACTIVE` or `EXHAUSTED`, moving it to the terminal `CANCELLED` state and incrementing its `version`, but only when the series has neither realized nor outstanding obligations: cancellation requires `consumed_credits` to be 0 (otherwise `ERR_PACKAGE_HAS_CONSUMED_CREDITS`) and `reserved_credits` to be 0 (otherwise `ERR_PACKAGE_HAS_RESERVED_CREDITS`). Series may be listed and filtered by `patient_id` and retrieved by id, with read access for a `ClinicAdmin`, a `Practitioner`, or the owning patient.

### 3.5. Booking, Running, and Closing an Appointment

Booking a session is a `ClinicAdmin` operation, and it is where the most cross-cutting validation converges. The booking request supplies the `patient_id`, the `treatment_plan_id` of the `ACTIVE` plan this visit advances, the `practitioner_id`, the `room_id`, the `scheduled_start` and `scheduled_end` instants (the end must be strictly after the start), the `base_fee_cents` per-visit base treatment fee, and `expected_treatment_plan_version` for the OCC check. The `charge_source` field declares how the visit is paid and defaults to `PER_VISIT`; when it is `PACKAGE` the request also supplies a `package_series_id` naming the series to draw a credit from, whereas a `PER_VISIT` visit leaves `package_series_id` null and will generate its own billing at completion. A new appointment opens with its clinical dimension, `clinical_status`, at `SCHEDULED` and its billing dimension, `billing_status`, at `UNBILLED`; these two state machines evolve independently of one another.

Booking enforces a layered gate. The referenced plan must be `ACTIVE`, since no appointment may attach to a held, completed, or cancelled plan; a non-active plan yields `ERR_PLAN_NOT_ACTIVE`. The patient must have completed intake — that is, `intake_status` must be `INTAKE_COMPLETE` — or the booking is rejected with `ERR_INTAKE_REQUIRED`. The room and the practitioner are then checked for temporal availability per Section 3.6. A package-funded booking additionally requires that the series have at least one provisional credit available and not be cancelled, as detailed in Section 3.4; a booking that would draw from a series with `provisional_remaining_credits` below 1 (or from a `CANCELLED` series) is rejected with `ERR_NO_CREDITS_REMAINING`. Finally the OCC check fires: `expected_treatment_plan_version` must equal the plan's current `version`, else `ERR_STALE_VERSION`. On a successful booking the appointment is created at `version` 1, the referenced plan's `version` is incremented by one, and for a `PACKAGE` booking the series' `reserved_credits` is increased by one with both balances recomputed, the exhaustion transition re-evaluated, and the series `version` incremented.

During a scheduled appointment's life a `ClinicAdmin` or a `Practitioner` may attach a cupping or moxibustion add-on, supplying the `modality` (`CUPPING` or `MOXA`) and the add-on `fee_cents`. An attached add-on begins with `status` of `ATTACHED` and increments the parent appointment's `version`; its fee participates in the visit's billing totals as described below. Add-ons may be listed and filtered by `appointment_id` and retrieved by id.

Check-in is a `ClinicAdmin` action that requires the appointment's clinical status to be `SCHEDULED` (otherwise `ERR_APPT_NOT_SCHEDULED`) and the governing plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`). Check-in moves the clinical status from `SCHEDULED` to `CHECKED_IN`, records `checked_in_at` as the logical-clock instant of check-in, computes the `arrival_class`, and increments the appointment's `version`. The `arrival_class` begins as `PENDING` and is resolved at check-in: taking the difference in seconds between `checked_in_at` and `scheduled_start`, the arrival is classified `LATE` when that difference is strictly greater than the grace allowance of ten minutes, and `ON_TIME` otherwise. The boundary is strict — an arrival exactly ten minutes after the scheduled start (a difference of exactly six hundred seconds) is `ON_TIME`, and only a difference exceeding six hundred seconds is `LATE`.

Completion is a `Practitioner` action requiring the appointment to be `CHECKED_IN` (otherwise `ERR_APPT_NOT_CHECKED_IN`). Completion moves the clinical status to `COMPLETED` and, in the parallel billing dimension, moves the billing status to `BILLED`, incrementing the appointment's `version`. The financial consequence depends on `charge_source`. When the visit is `PACKAGE`, no charge is generated; instead the series' `reserved_credits` is decreased by one and its `consumed_credits` is increased by one — leaving the provisional balance net-unchanged for this step while lowering the finalized balance by one — with the exhaustion transition re-evaluated and the series `version` incremented. When the visit is `PER_VISIT`, a billing artifact is produced: a cash patient produces a `Charge`, while an insurance patient produces a `Superbill`, both computed as described in Section 3.8.

Cancelling and marking no-show are the two compensating paths, both `ClinicAdmin` actions, and both must conserve package credits and reverse downstream artifacts. Marking an appointment as a no-show requires it to be `SCHEDULED` (otherwise `ERR_APPT_NOT_SCHEDULED`). It moves the clinical status from `SCHEDULED` to `NO_SHOW`, records this appointment as the producing strike by increasing the patient's `strike_count` by one and incrementing the patient's `version`, voids every `ATTACHED` add-on for the appointment (moving each to `VOIDED`), and increments the appointment's `version`. The penalty calculation of Section 3.7 is evaluated: when the penalty is greater than zero a `Charge` of charge type `PENALTY` is created and the billing status moves to `PENALTY_DUE`, and when the penalty equals zero the billing status moves to `WAIVED`. For a `PACKAGE` no-show the held reservation is released — `reserved_credits` is decreased by one and the credit is not consumed, so `provisional_remaining_credits` rises by one, the exhaustion-to-active transition is re-evaluated, and the series `version` is incremented.

Cancelling an appointment requires its clinical status to be `SCHEDULED` or `CHECKED_IN` (otherwise `ERR_APPT_NOT_CANCELLABLE`) and follows a transitive cascade. As the first hop, this appointment moves to `CANCELLED`, all `ATTACHED` add-ons move to `VOIDED`, and any `OPEN` `Charge` or `ISSUED` `Superbill` already produced for the appointment moves to `VOID` (with the billing status moving to `WAIVED`); the appointment's `version` is incremented. As the second hop caused by the first, if the visit was a `PACKAGE` visit the held credit is released — the series' `reserved_credits` is decreased by one, `provisional_remaining_credits` is recomputed, and the series `version` is incremented. As the third hop caused by the second, if that release lifts `provisional_remaining_credits` above 0 while the series is `EXHAUSTED`, the series auto-transitions from `EXHAUSTED` to `ACTIVE`, incurring a further series `version` bump. Separately, if the cancellation occurs within the late-cancellation cutoff window measured back from `scheduled_start`, the patient's `strike_count` is increased by one and the late-cancel variant of the penalty calculation may create a `PENALTY` `Charge`; a cancellation outside that window incurs no strike. This same cancellation logic is what the plan-cancel cascade of Section 3.3 invokes on each of the plan's open appointments.

Appointments may be listed and filtered by any of `patient_id`, `treatment_plan_id`, `practitioner_id`, `room_id`, or `package_series_id`, and retrieved by id, with read access for a `ClinicAdmin`, a `Practitioner`, or the owning patient.

### 3.6. Rooms, Practitioners, and Temporal Availability

A `ClinicAdmin` creates a practitioner by supplying `full_name`, a unique `license_number` (the state acupuncture license), and an optional `turnover_buffer_minutes`, the mandatory gap in minutes this practitioner requires between back-to-back appointments, defaulting to 0. A `ClinicAdmin` creates a treatment room or table by supplying a unique `room_name` and an optional `cleanup_buffer_minutes`, the mandatory minutes of cleanup occupancy after each appointment ends before the room frees, defaulting to 0. Both practitioners and rooms are readable as lists and singly by id.

At booking time the system rejects an appointment that would collide on its room or its practitioner. Each existing non-terminal appointment — one whose clinical status is `SCHEDULED` or `CHECKED_IN` — occupies a half-open interval running from its `scheduled_start` up to but not including its `scheduled_end`. For the room check, each existing appointment on the same `room_id` occupies an extended interval running from its `scheduled_start` up to but not including its `scheduled_end` plus that room's `cleanup_buffer_minutes` converted to seconds; the new booking is rejected with `ERR_ROOM_CONFLICT` if its own half-open interval intersects any such extended interval on the same room. For the practitioner check, there is no cleanup occupancy but a symmetric turnover buffer applies: two appointments on the same `practitioner_id` conflict when the new appointment's start is earlier than the existing appointment's end plus the practitioner's `turnover_buffer_minutes` (in seconds) and simultaneously the existing appointment's start is earlier than the new appointment's end plus that same buffer; such a conflict is rejected with `ERR_PRACTITIONER_CONFLICT`. Because the intervals are half-open and the buffers are applied as described, two appointments that are exactly adjacent with a zero buffer do not conflict.

### 3.7. No-Show and Late-Cancellation Penalties

The penalty calculation runs whenever an appointment is marked no-show, and whenever an appointment is cancelled within the late-cancellation cutoff measured back from `scheduled_start`. It takes three interacting inputs: which transition occurred (no-show versus late cancellation), the patient's prior strike count, and the patient's membership standing. Throughout this calculation, prior strikes means the patient's `strike_count` as it stood before this appointment's own strike was recorded.

The calculation has a waiver branch and a tiered branch. When the patient's `membership_status` is `ACTIVE` and the prior strike count is exactly 0, the penalty is 0 cents — the first-strike waiver for active members. Otherwise a tiered penalty applies: the tier base is 5000 cents for a no-show and 2500 cents for a late cancellation; a strike multiplier is formed as 1 plus the strike step of 0.5 times the prior strike count capped at 3 (so the prior strike count contributes through its value, but never more than 3, before being scaled); and the penalty is the tier base multiplied by that multiplier, rounded half up to whole cents. For example, with no prior strikes the multiplier is 1; with one prior strike it is 1.5; with three or more prior strikes it is 2.5, the maximum. A penalty greater than zero produces a `PENALTY` `Charge` and drives billing status to `PENALTY_DUE`; a penalty of zero drives billing status to `WAIVED`.

The billing dimension of an appointment evolves independently of the clinical dimension. From `UNBILLED` it moves to `BILLED` when the appointment completes and a charge or superbill is produced, to `PENALTY_DUE` when a no-show or late cancellation yields a penalty above zero, or to `WAIVED` when such an event yields a zero penalty. A billing status that had already reached `BILLED` or `PENALTY_DUE` moves to `WAIVED` when a later appointment cancellation voids the produced charge or superbill. Each of these billing transitions increments the appointment's `version`.

### 3.8. Settling the Visit: Cash Charges and Insurance Superbills

When a `PER_VISIT` appointment completes, exactly one billing artifact is produced, and which one depends on the patient's `payer_mode`. In both variants the visit subtotal is the appointment's `base_fee_cents` plus the sum of the `fee_cents` of every add-on on the appointment whose status is `ATTACHED`; add-ons that have been voided are excluded from the subtotal.

For a cash patient (`payer_mode` of `CASH`), a `Charge` is produced. Its `subtotal_cents` is the subtotal just described. Its `cash_discount_cents` is the subtotal multiplied by the cash discount fraction of ten percent (0.10), rounded half up to whole cents — and is 0 for any patient who is not cash. Its `total_due_cents`, the patient responsibility, is the subtotal minus the cash discount. A visit charge has `charge_type` of `VISIT`, as opposed to the `PENALTY` `charge_type` produced by penalties, and opens with `status` of `OPEN`; a charge moves to `VOID` when its appointment's cancellation reverses it.

For an insurance patient (`payer_mode` of `INSURANCE`), a `Superbill` is produced instead, and no cash discount applies. The `line_charges_cents` is an ordered list of cents amounts: the `base_fee_cents` first, then each `ATTACHED` add-on's `fee_cents` in ascending `created_at` order. The `insurance_allowed_cents` is computed by rounding each individual line amount times the patient's `coinsurance_rate` to whole cents and then summing those per-line rounded results — the rounding is performed per line and then the lines are summed, never the reverse. The `patient_responsibility_cents` is the sum of all line amounts minus `insurance_allowed_cents`. A superbill opens with `status` of `ISSUED` and moves to `VOID` when its appointment's cancellation reverses it. Charges may be listed and filtered by `appointment_id` and retrieved by id, as may superbills; both are readable by a `ClinicAdmin`, a `Practitioner`, or the owning patient.

### 3.9. Herbal Formulas, Inventory, and Conserved Dispensing

The herbal side of the practice rests on a conserved-mass inventory. A `Pharmacist` stocks an inventory item by creating a herb item with a unique `herb_name`, the `initial_grams` stocked at creation (the immutable baseline for the conservation invariant), and an optional `reorder_threshold_grams` defaulting to 0. A herb item's `on_hand_grams` is the current quantity, computed as `initial_grams` minus the total grams deducted by all filled dispenses that reference this herb; it begins equal to `initial_grams`. The `stock_status` is `LOW_STOCK` when `on_hand_grams` is at or below `reorder_threshold_grams` and `IN_STOCK` otherwise — the boundary is inclusive, so an on-hand quantity exactly equal to the threshold is `LOW_STOCK`. A `Pharmacist` or a `Practitioner` defines a herbal formula with a unique `formula_name` and a `line_items` array, each line naming a `herb_item_id` and the `grams_per_dose` for that herb (an integer of at least 1). Herb items and formulas are readable as lists and singly by id.

Dispensing is a two-step lifecycle that protects inventory. A `Pharmacist` or a `Practitioner` requests a dispense against an `ACTIVE` plan by supplying the `patient_id`, the `treatment_plan_id`, the `herbal_formula_id`, the number of `doses` (at least 1), and `expected_treatment_plan_version` for the OCC check; the referenced plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) and the plan's `version` must match the supplied expected value (otherwise `ERR_STALE_VERSION`). A requested dispense opens with `status` of `REQUESTED`, increments the referenced plan's `version`, and itself starts at `version` 1.

A `Pharmacist` fills a requested dispense, which is the inventory-debit step and the second transitive cascade in the system. Filling requires the dispense `status` to be `REQUESTED` (otherwise `ERR_DISPENSE_NOT_REQUESTED`), requires the governing plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), and requires that for every recipe line the referenced herb item's `on_hand_grams` be at least `grams_per_dose` times `doses` (otherwise `ERR_INSUFFICIENT_STOCK`); this stock safety check precedes any financial bookkeeping. On success, the first hop snapshots `total_grams_by_herb`, a map from each `herb_item_id` to the grams deducted for it, equal to that line's `grams_per_dose` times `doses`. The second hop, caused by the first, decreases each referenced herb item's `on_hand_grams` by its deducted grams and increments that herb item's `version`. The third hop, caused by the second, auto-transitions any herb item whose `on_hand_grams` has fallen to or below its `reorder_threshold_grams` from `IN_STOCK` to `LOW_STOCK`, incurring a further `version` bump on that herb item. The dispense itself moves from `REQUESTED` to `FILLED` and its `version` is incremented.

Reversing a filled dispense is the compensating action that conserves inventory mass. A `Pharmacist` reverses a dispense whose `status` is `FILLED` (otherwise `ERR_DISPENSE_NOT_FILLED`), and because reversal is OCC-guarded the request must carry `expected_formula_dispense_version` matching the dispense's current `version` (otherwise `ERR_STALE_VERSION`). Reversal restores each referenced herb item's `on_hand_grams` by exactly the grams recorded for it in `total_grams_by_herb`, increments that herb item's `version`, and auto-transitions any herb item whose `on_hand_grams` thereby rises above its `reorder_threshold_grams` from `LOW_STOCK` back to `IN_STOCK`. The dispense moves to the terminal `REVERSED` state and its `version` is incremented; across a fill and its reversal the total inventory mass is exactly conserved. Dispenses may be listed and filtered by `patient_id`, `treatment_plan_id`, or `herbal_formula_id`, and retrieved by id, with read access for a `Pharmacist`, a `Practitioner`, a `ClinicAdmin`, or the owning patient.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and the administrative clock advance — return a `200 OK` status code. The complete request payloads, side effects, and computed responses for each endpoint are defined in the Section 3 narratives; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server logical clock | ClinicAdmin |
| POST | `/practitioners` | Create a practitioner | ClinicAdmin |
| GET | `/practitioners` | List practitioners | ClinicAdmin, Practitioner, Pharmacist |
| GET | `/practitioners/{id}` | Get a practitioner | ClinicAdmin, Practitioner, Pharmacist |
| POST | `/rooms` | Create a treatment room/table | ClinicAdmin |
| GET | `/rooms` | List rooms | ClinicAdmin, Practitioner |
| GET | `/rooms/{id}` | Get a room | ClinicAdmin, Practitioner |
| POST | `/herb-items` | Create an inventory herb item | Pharmacist |
| GET | `/herb-items` | List herb items | Pharmacist, Practitioner, ClinicAdmin |
| GET | `/herb-items/{id}` | Get a herb item | Pharmacist, Practitioner, ClinicAdmin |
| POST | `/formulas` | Create a herbal formula recipe | Pharmacist, Practitioner |
| GET | `/formulas` | List formulas | Pharmacist, Practitioner, ClinicAdmin |
| GET | `/formulas/{id}` | Get a formula | Pharmacist, Practitioner, ClinicAdmin |
| POST | `/patients` | Register a patient | ClinicAdmin |
| GET | `/patients` | List patients | ClinicAdmin, Practitioner |
| GET | `/patients/{id}` | Get a patient | ClinicAdmin, Practitioner, Patient |
| POST | `/patients/{id}/membership` | Set patient membership status | ClinicAdmin |
| POST | `/intakes` | Create a TCM intake (DRAFT) | Practitioner |
| GET | `/intakes` | List intakes; filter by patient_id | ClinicAdmin, Practitioner, Patient |
| GET | `/intakes/{id}` | Get an intake | ClinicAdmin, Practitioner, Patient |
| POST | `/intakes/{id}/finalize` | Finalize an intake | Practitioner |
| POST | `/treatment-plans` | Create a treatment plan / point prescription | Practitioner |
| GET | `/treatment-plans` | List treatment plans; filter by patient_id / practitioner_id / intake_id | ClinicAdmin, Practitioner, Patient |
| GET | `/treatment-plans/{id}` | Get a treatment plan | ClinicAdmin, Practitioner, Patient |
| POST | `/treatment-plans/{id}/hold` | Put an ACTIVE plan ON_HOLD | Practitioner |
| POST | `/treatment-plans/{id}/resume` | Resume an ON_HOLD plan to ACTIVE | Practitioner |
| POST | `/treatment-plans/{id}/complete` | Complete an ACTIVE plan | Practitioner |
| POST | `/treatment-plans/{id}/cancel` | Cancel a plan; cascades to open appointments | Practitioner |
| POST | `/package-series` | Purchase a package series | ClinicAdmin |
| GET | `/package-series` | List package series; filter by patient_id | ClinicAdmin, Practitioner, Patient |
| GET | `/package-series/{id}` | Get a package series | ClinicAdmin, Practitioner, Patient |
| POST | `/package-series/{id}/cancel` | Cancel an unused package series | ClinicAdmin |
| POST | `/appointments` | Book an appointment | ClinicAdmin |
| GET | `/appointments` | List appointments; filter by patient_id / treatment_plan_id / practitioner_id / room_id / package_series_id | ClinicAdmin, Practitioner, Patient |
| GET | `/appointments/{id}` | Get an appointment | ClinicAdmin, Practitioner, Patient |
| POST | `/appointments/{id}/addons` | Attach a cupping/moxa add-on | ClinicAdmin, Practitioner |
| POST | `/appointments/{id}/check-in` | Check in a scheduled appointment | ClinicAdmin |
| POST | `/appointments/{id}/complete` | Complete a checked-in appointment | Practitioner |
| POST | `/appointments/{id}/no-show` | Mark a scheduled appointment as no-show | ClinicAdmin |
| POST | `/appointments/{id}/cancel` | Cancel a scheduled/checked-in appointment | ClinicAdmin |
| GET | `/addons` | List add-ons; filter by appointment_id | ClinicAdmin, Practitioner, Patient |
| GET | `/addons/{id}` | Get an add-on | ClinicAdmin, Practitioner, Patient |
| GET | `/charges` | List charges; filter by appointment_id | ClinicAdmin, Practitioner, Patient |
| GET | `/charges/{id}` | Get a charge | ClinicAdmin, Practitioner, Patient |
| GET | `/superbills` | List superbills; filter by appointment_id | ClinicAdmin, Practitioner, Patient |
| GET | `/superbills/{id}` | Get a superbill | ClinicAdmin, Practitioner, Patient |
| POST | `/dispenses` | Request a herbal-formula dispense | Pharmacist, Practitioner |
| GET | `/dispenses` | List dispenses; filter by patient_id / treatment_plan_id / herbal_formula_id | Pharmacist, Practitioner, ClinicAdmin, Patient |
| GET | `/dispenses/{id}` | Get a dispense | Pharmacist, Practitioner, ClinicAdmin, Patient |
| POST | `/dispenses/{id}/fill` | Fill a requested dispense; debits inventory | Pharmacist |
| POST | `/dispenses/{id}/reverse` | Reverse a filled dispense; restores inventory | Pharmacist |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_INTAKE_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_APPT_NOT_FOUND` | 404 Not Found |
| `ERR_DISPENSE_NOT_FOUND` | 404 Not Found |
| `ERR_PRACTITIONER_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_FORMULA_NOT_FOUND` | 404 Not Found |
| `ERR_HERB_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_APPT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_APPT_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_APPT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_ON_HOLD` | 409 Conflict |
| `ERR_PLAN_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PLAN_HAS_OPEN_APPOINTMENTS` | 409 Conflict |
| `ERR_INTAKE_NOT_DRAFT` | 409 Conflict |
| `ERR_INTAKE_INCOMPLETE` | 409 Conflict |
| `ERR_DISPENSE_NOT_REQUESTED` | 409 Conflict |
| `ERR_DISPENSE_NOT_FILLED` | 409 Conflict |
| `ERR_INTAKE_REQUIRED` | 409 Conflict |
| `ERR_INTAKE_NOT_FINALIZED` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_ROOM_CONFLICT` | 409 Conflict |
| `ERR_PRACTITIONER_CONFLICT` | 409 Conflict |
| `ERR_NO_CREDITS_REMAINING` | 409 Conflict |
| `ERR_PACKAGE_HAS_CONSUMED_CREDITS` | 409 Conflict |
| `ERR_PACKAGE_HAS_RESERVED_CREDITS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
