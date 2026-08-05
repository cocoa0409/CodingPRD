# Mens Health Hormone Clinic API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a Men's Health & Hormone clinic that manages testosterone-replacement (TRT) and erectile-dysfunction (ED) care from first intake through ongoing controlled-substance monitoring. The platform ties together the clinical and the commercial sides of the practice: patient intake and laboratory work (testosterone, PSA, and hematocrit panels), treatment plans and dosing protocols, controlled-substance prescribing with dispense/reverse accounting, subscription memberships with lab-draw credits and self-pay pharmacy pricing, telehealth and phlebotomy scheduling, dose titration with follow-up, and adverse-event triage. Because much of the work involves scheduled drugs, the system is built upon compliance guarantees — segregation of prescribing from safety review, mandatory monitoring before prescribing, and automatic suspension of therapy when a lab result is unsafe.

The API is a compliance-and-pricing engine as much as a record store. A single lab review can cascade a treatment plan into a monitoring hold and quietly suspend the underlying prescription; a single severe adverse event can revoke a prescription and cancel every pending refill behind it. At the same time, every refill carries a precisely tiered self-pay charge, and every mid-cycle membership change reprices the remaining days of the billing cycle. This specification defines those behaviors so that an implementation reproduces them exactly, including the optimistic-concurrency guards that keep two clinicians from proposing dose changes or refills against a plan or prescription they have not observed in its latest form. All resources live under a shared `/clinic` namespace and are linked by identifier references rather than nested ownership, with the sole exception of dose titrations, which are addressed beneath their treatment plan.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role string the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly four roles: `ClinicAdmin`, `Clinician`, `Pharmacist`, and `Patient`.

- When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`. The `ClinicAdmin` runs the operational back office: registering clinicians, pharmacists, membership plans, and draw stations; creating and administering memberships (activation, payment recording, plan changes, cancellation); and advancing the logical clock.
- When `X-User-Role` is `Clinician`, `X-User-ID` is the `id` of the acting `Clinician`. Ownership checks on any resource that references a `Clinician` compare that reference to `X-User-ID`. In particular, activating or prescribing against a `TreatmentPlan` requires that the plan's `clinician_id` equal `X-User-ID`, and adverse-event triage requires that the reviewing clinician's `X-User-ID` differ from the implicated plan's `clinician_id`.
- When `X-User-Role` is `Pharmacist`, `X-User-ID` is the `id` of the acting `Pharmacist`. The pharmacist dispenses and reverses refill orders.
- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`. Patients self-serve: booking telehealth visits and lab-draw appointments, requesting and cancelling refills, and reporting adverse events.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list responses are ordered by each resource's `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in the system carries a system-managed set of fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that starts at 1 (or its initial persisted value) and increments by one on every mutation to the resource, including mutations that only touch derived fields. All entity types in this system — clinicians, pharmacists, patients, membership plans, memberships, draw stations, lab panels, lab-draw appointments, telehealth visits, treatment plans, dose titrations, prescriptions, refill orders, and adverse events — carry all four fields, including `updated_at` and `version`.

Timestamps that the system records against the logical clock (for example, a membership's `cycle_anchor_date` or a lab panel's `drawn_at`) are stored and returned as ISO 8601 UTC values.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the current `version` of a parent resource. In each case the guard field is a non-optional input on the request, and the check is framed entirely in terms of stale reads: if a concurrent writer has advanced the parent's `version` since the client last observed it, the client's request is rejected before it can act on a superseded view.

Proposing a dose titration for a treatment plan requires `expected_plan_version` in the request body, carrying the client's last observed `version` of that `TreatmentPlan`. If `expected_plan_version` does not equal the plan's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a prior titration proposal legitimately advances the plan's `version` and moves it into a pending state, a second proposer working from an older read is stopped here rather than overwriting a change it never saw.

Creating a refill order requires `expected_prescription_version` in the request body, carrying the client's last observed `version` of the referenced `ControlledSubstancePrescription`. If it does not equal the prescription's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A prescription's `version` advances on every dispense, reverse, refill creation, and status change, so a refill submitted against a stale prescription view is rejected before it can draw down an allowance that has already been consumed. Endpoints other than these two do not take a version field and perform no OCC check.

### 2.6. Nested Resource Retrieval and Referential Existence

The entity topology is flat: resources reference one another by identifier rather than by URL nesting. The single exception is the dose titration, which is addressed beneath its treatment plan. When a path names more than one resource identifier (a titration under a plan), the identifiers are validated left to right, and the first identifier that does not resolve produces `ERR_NOT_FOUND` (HTTP 404) before any later identifier is examined. The same existence check applies to every identifier supplied in a request body — a `patient_id`, `plan_id`, `prescription_id`, `membership_id`, `draw_station_id`, `clinician_id`, `plan_id`, or `baseline_panel_id` that does not resolve yields `ERR_NOT_FOUND`.

### 2.7. Monetary Values, Scores, and Rounding

All monetary values in the system are integer cents: membership fees, unit prices, surcharges, proration charges, and refill charges are whole numbers of cents, never fractional and never strings. Wherever a calculation multiplies by a rate or a fraction and a rounding step is called for, the system rounds half up to the nearest whole cent. The order of rounding is significant and is specified per calculation in §3; where a formula rounds several intermediate lines, each line is rounded independently before the lines are combined.

Risk scores are integers in the range 0 through 100. Where an averaging step is specified, the mean is rounded half up to the nearest whole integer.

### 2.8. Request Validation Order

Every request is validated in a fixed priority order, and the first failing check determines the error returned. The order is: (1) presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400); (2) the acting role's permission for the operation (`ERR_INSUFFICIENT_PERMISSIONS`, 403); (3) existence of every referenced identifier, left to right (`ERR_NOT_FOUND`, 404); (4) well-formedness of the request body — required fields present, enum values legal, numeric values in range (`ERR_VALIDATION`, 400); and (5) optimistic-concurrency version match where applicable (`ERR_STALE_VERSION`, 412). Only after all of these pass does the system evaluate the state-machine and business rules described in §3, themselves ordered as noted in each workflow. A generic transition that is not enabled from a resource's current state — where no more specific state error is defined — is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 2.9. Cascading State Consistency

Several operations mutate more than one resource. When the system transitions a resource as a downstream consequence of another operation, it treats that transition as a full mutation of the affected resource: its `updated_at` is refreshed and its `version` is incremented. Three cascade chains recur throughout the workflows and are introduced here so they can be relied upon in §3. First, reviewing a lab panel whose results are unsafe places an active treatment plan into a monitoring hold and, in turn, suspends the plan's issued controlled-substance prescription; resuming the plan reverses the suspension. Second, suspending a treatment plan cancels any proposed titration and revokes the plan's issued or suspended prescriptions, and revoking a prescription cancels every pending refill order behind it. Third, a severe adverse-event triage suspends the implicated plan, which then propagates the same suspension cascade. Each of these is specified in full where its originating workflow lives.

### 2.10. The Logical Clock

All time-dependent behavior — monitoring windows, proration day counts, scheduling intervals, and record timestamps — reads from a server-managed logical clock rather than wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time. A `ClinicAdmin` may advance the clock by supplying a `to_iso8601` instant; every subsequent time-dependent computation uses that value as "now" until it is advanced again.

## 3. Business Logic & Workflows

### 3.1. Actors, Patients, and Clinic Configuration

The clinic's roster and catalog are established by registration operations. A `ClinicAdmin` registers a prescriber as a `Clinician`, supplying `full_name`, the provider's `npi`, and the `dea_number` under which controlled substances are prescribed. A `ClinicAdmin` also registers a dispensing `Pharmacist` with a `full_name` and `license_number`. Patient intake may be performed by either a `ClinicAdmin` or a `Clinician`, capturing the patient's `full_name`, `date_of_birth` (a `YYYY-MM-DD` string), `sex` (one of `MALE` or `OTHER`), and contact `email`.

Configuration of the commercial catalog is a `ClinicAdmin` responsibility. A `MembershipPlan` is created with a `tier` (one of `CORE`, `PLUS`, or `ELITE`), a recurring `monthly_fee_cents`, a billing `cycle_days` length, the number of `included_refills_per_cycle`, the number of `included_lab_draw_credits` granted when a membership is created against the plan, a `refill_discount_pct` member-discount fraction between 0.0 and 1.0 applied to refill drug cost, and a `titration_visit_fee_cents` charged for each titration follow-up. A `DrawStation` — a phlebotomy station — is created with a `name` and a `concurrent_capacity`, the maximum number of scheduled appointments whose intervals may overlap at that station.

### 3.2. Memberships: Subscription, Payment, Credits, and Proration

A membership ties a patient to a plan and tracks two independent lifecycles on the same record. A `ClinicAdmin` creates a `Membership` by supplying `patient_id` and `plan_id`. At creation the membership begins with `subscription_status` of `TRIAL` and `payment_status` of `CURRENT`; its `lab_draw_credits_remaining` is initialized to the plan's `included_lab_draw_credits`; its `cycle_anchor_date` is set to the current logical clock, marking the start of the current billing cycle; and its `last_change_charge_cents` starts at 0.

The **subscription axis** moves through `TRIAL`, `ACTIVE`, and `CANCELLED`. Activation moves a membership from `TRIAL` to `ACTIVE`; it is permitted only while `subscription_status` is `TRIAL`, and otherwise fails with `ERR_INVALID_STATE`. Cancellation moves a membership to `CANCELLED` and is permitted while `subscription_status` is `TRIAL` or `ACTIVE`, failing with `ERR_INVALID_STATE` from any other state. The **payment axis** evolves independently between `CURRENT` and `DELINQUENT`. Recording a payment carries an `outcome`: an `outcome` of `FAILED` moves a `CURRENT` membership to `DELINQUENT` (and fails with `ERR_INVALID_STATE` if it is not `CURRENT`), while an `outcome` of `SUCCEEDED` moves a `DELINQUENT` membership back to `CURRENT` (and fails with `ERR_INVALID_STATE` if it is not `DELINQUENT`). The two axes never interact: a membership may be `ACTIVE` and `DELINQUENT` at once.

Memberships may be listed and filtered by `patient_id` or `plan_id`. Lab-draw credits are conserved: at any time a membership's `lab_draw_credits_remaining` equals the plan's `included_lab_draw_credits` minus the count of that patient's lab-draw appointments in the `SCHEDULED` or `COMPLETED` states. Booking an appointment consumes one credit and cancelling a scheduled appointment restores one, as detailed in §3.4.

Switching a member to a different plan is a `ClinicAdmin` action that supplies the new plan as `new_plan_id` and reprices the remainder of the current cycle by **waterfall proration**. First, compute `days_remaining` as the number of whole days between the current logical clock and the end of the current cycle, where the cycle end is the `cycle_anchor_date` plus the old plan's `cycle_days` days; this value is never negative. Compute the old-plan credit line as the old plan's `monthly_fee_cents` multiplied by `days_remaining`, divided by the old plan's `cycle_days`, rounded half up to a whole cent. Compute the new-plan charge line as the new plan's `monthly_fee_cents` multiplied by `days_remaining`, divided by the new plan's `cycle_days`, rounded half up to a whole cent. Because the two lines use different denominators, each line is rounded independently before they are combined. The net proration charge is the new-plan charge line minus the old-plan credit line; this value is stored in `last_change_charge_cents`, and the membership's `plan_id` is updated to `new_plan_id`.

### 3.3. Laboratory Panels and the Monitoring Hold

Lab work follows a linear pipeline. A `Clinician` orders a `LabPanel` by supplying the `patient_id`, the ordering `clinician_id`, and a `panel_type` of either `BASELINE` or `MONITORING`; the panel begins in `ORDERED`. Panels may be listed and filtered by `patient_id` or `clinician_id`. Marking a panel as drawn advances it from `ORDERED` to `DRAWN` and may be performed by a `Clinician` or `ClinicAdmin`. Entering results advances a panel from `DRAWN` to `RESULTED` and records `total_testosterone_ng_dl`, `psa_ng_ml`, `hematocrit_pct`, and `drawn_at`; attempting to enter results on a panel that is not `DRAWN` fails with `ERR_PANEL_NOT_RESULTED`.

Reviewing a panel advances it from `RESULTED` to `REVIEWED`; attempting review on a panel that is not `RESULTED` likewise fails with `ERR_PANEL_NOT_RESULTED`. At review the system computes the panel's `is_unsafe` flag: a panel is unsafe when its `hematocrit_pct` is at or above 54.0, or its `psa_ng_ml` is at or above 4.0. When a reviewed panel is unsafe and the patient has a treatment plan currently in the `ACTIVE` state, the system moves that plan from `ACTIVE` to `MONITORING_HOLD` (cascade link 1). That hold, in turn, suspends the plan's issued controlled-substance prescription, as described in §3.5 and §3.6.

### 3.4. Scheduling: Lab-Draw Appointments and Telehealth Visits

Booking a `LabDrawAppointment` consumes a lab-draw credit and reserves capacity at a station. A `Patient`, `ClinicAdmin`, or `Clinician` books one by supplying `patient_id`, `draw_station_id`, and a half-open interval defined by `start_at` (inclusive) and `end_at` (exclusive). Two guards apply. First, the membership backing the patient must have at least one lab-draw credit remaining; a booking that would drive `lab_draw_credits_remaining` below zero is rejected with `ERR_INSUFFICIENT_LAB_DRAW_CREDITS`. Second, the station's concurrency must not be exceeded: counting the existing `SCHEDULED` appointments at that station whose half-open intervals overlap the requested interval, the booking is rejected with `ERR_DRAW_STATION_AT_CAPACITY` when that count is at or above the station's `concurrent_capacity`. A successful booking decrements the membership's `lab_draw_credits_remaining` by one. Appointments may be listed and filtered by `patient_id` or `draw_station_id`.

An appointment begins in `SCHEDULED`. Completing it moves it to `COMPLETED`, and cancelling it moves it to `CANCELLED`; either transition attempted from a non-`SCHEDULED` state fails with `ERR_APPOINTMENT_NOT_SCHEDULED`. Cancellation of a scheduled appointment restores one credit, incrementing the membership's `lab_draw_credits_remaining` by one; completion consumes no additional credit.

A `TelehealthVisit` is booked by a `Patient` or `ClinicAdmin` on a clinician's calendar, supplying `patient_id`, `clinician_id`, a `start_at`/`end_at` interval, and an optional `reason`. A double-booking guard protects the clinician: if any other `SCHEDULED` visit for the same clinician has an interval that overlaps the requested one or sits within a fifteen-minute buffer of it — that is, the clear gap between the two intervals is strictly less than fifteen minutes — the booking is rejected with `ERR_CLINICIAN_DOUBLE_BOOKED`. A gap of exactly fifteen minutes or more is allowed. Visits may be listed and filtered by `patient_id` or `clinician_id`. A visit begins in `SCHEDULED`; a `Clinician` completes it to `COMPLETED`, and a `Patient`, `ClinicAdmin`, or `Clinician` may cancel it to `CANCELLED`, with either transition from a non-`SCHEDULED` state rejected as `ERR_INVALID_STATE`.

### 3.5. Treatment Plans: Activation, Titration, Hold, and Suspension

The treatment plan is the clinical spine of the system. A `Clinician` drafts a `TreatmentPlan` by supplying the `patient_id`, the owning `clinician_id`, a `baseline_panel_id` referencing the baseline labs, a `protocol_type` (one of `TRT_INJECTION`, `TRT_TOPICAL`, or `ED_THERAPY`), and a `starting_dose_mg`. The plan begins in `DRAFT` with `round_index` at 0; its `current_dose_mg` is not yet set. Plans may be listed and filtered by `patient_id`, `clinician_id`, or `baseline_panel_id`.

Activation moves a plan from `DRAFT` to `ACTIVE` and is subject to a series of checks evaluated in order: the patient's membership must have `subscription_status` of `ACTIVE`, or the activation fails with `ERR_MEMBERSHIP_NOT_ACTIVE`; the plan must currently be in `DRAFT`, or it fails with `ERR_INVALID_STATE`; the referenced baseline panel must be in the `REVIEWED` state, or activation fails with `ERR_BASELINE_NOT_REVIEWED`; and the acting clinician must own the plan, meaning the plan's `clinician_id` equals `X-User-ID`, or the activation is refused with `ERR_CLINICIAN_MISMATCH`. On success the plan's `current_dose_mg` is set to its `starting_dose_mg`.

Dose titration is a cyclic follow-up loop. A `Clinician` proposes a titration by supplying a `proposed_dose_mg` together with the `expected_plan_version` guard of §2.5. The plan must be `ACTIVE`, or the proposal is rejected with `ERR_PLAN_NOT_ACTIVE`; if the version guard fails, the rejection is `ERR_STALE_VERSION`. A successful proposal moves the plan from `ACTIVE` to `TITRATION_PENDING`, creates a `DoseTitration` in the `PROPOSED` state with its `round_index` set to the plan's current `round_index` plus one and its `previous_dose_mg` captured from the plan's `current_dose_mg`, leaves its `applied` flag false, and increments the plan's `version` by one. Titration rounds for a plan may be listed. Confirming a pending titration moves the plan from `TITRATION_PENDING` back to `ACTIVE`; it requires that the plan be in `TITRATION_PENDING`, failing otherwise with `ERR_TITRATION_NOT_PENDING`, and it requires that the patient's latest `REVIEWED` lab panel have a `hematocrit_pct` below 54.0, failing otherwise with `ERR_HEMATOCRIT_UNSAFE`. On confirmation the titration's `status` becomes `CONFIRMED` and its `applied` flag becomes true, the plan's `current_dose_mg` is set to the titration's `proposed_dose_mg`, the plan's `round_index` is set to the titration's `round_index`, and the plan's `version` is incremented by one. Each confirmed titration follow-up carries the plan member's configured `titration_visit_fee_cents`.

A plan enters a monitoring hold automatically when an unsafe lab review lands, as described in §3.3: an `ACTIVE` plan moves to `MONITORING_HOLD` and its issued prescription is suspended. A `Clinician` resumes a held plan, moving it from `MONITORING_HOLD` back to `ACTIVE`; resumption requires the plan to be in `MONITORING_HOLD` (otherwise `ERR_INVALID_STATE`) and requires the patient's latest `REVIEWED` lab panel to have `is_unsafe` equal to false (otherwise `ERR_HEMATOCRIT_UNSAFE`). On resume, the prescription that was suspended by the hold is restored to `ISSUED`.

Suspension is terminal. A `Clinician` or `ClinicAdmin` may suspend a plan, and the system also suspends a plan as the consequence of a severe adverse event (§3.7). Suspension is permitted from `DRAFT`, `ACTIVE`, `TITRATION_PENDING`, or `MONITORING_HOLD`, and is otherwise rejected with `ERR_INVALID_STATE`. When a plan is suspended, any `PROPOSED` dose titration for that plan is cancelled to `CANCELLED`, and every issued or suspended controlled-substance prescription linked to the plan is revoked — which itself cascades to cancel that prescription's pending refills, as described in §3.6.

### 3.6. Controlled-Substance Prescriptions and Self-Pay Refills

A `Clinician` issues a `ControlledSubstancePrescription` against a plan, supplying the `plan_id`, the `patient_id`, the `drug_name`, the self-pay `unit_price_cents`, the default `quantity_per_fill`, the total `refills_authorized`, and an optional `is_controlled` flag that defaults to true and governs whether the controlled-substance surcharge applies. Two ownership and referential guards run in order: the body's `patient_id` must equal the referenced plan's `patient_id`, or issuance fails with `ERR_PATIENT_MISMATCH`; and the acting clinician must own the plan (`clinician_id` equal to `X-User-ID`), or issuance fails with `ERR_CLINICIAN_MISMATCH`. A safety guard then requires that the patient have at least one `REVIEWED` lab panel whose `drawn_at` is no more than ninety days before the current logical clock; absent such recent monitoring, issuance is rejected with `ERR_MONITORING_OVERDUE`. On success the prescription's `prescriber_id` is set from `X-User-ID`, its `refills_remaining` is initialized to `refills_authorized`, and its `status` is `ISSUED`. Prescriptions may be listed and filtered by `plan_id`, `patient_id`, or `prescriber_id`.

A prescription's status branches with revert. Under a monitoring hold it moves from `ISSUED` to `SUSPENDED`, and on plan resume it returns from `SUSPENDED` to `ISSUED`. A `Clinician` may revoke a prescription, and the system revokes one as a plan-suspension cascade; revocation is permitted from `ISSUED` or `SUSPENDED` (otherwise `ERR_INVALID_STATE`) and cancels every `PENDING_REVIEW` refill order behind that prescription (cascade link 3). A prescription becomes `EXHAUSTED` automatically when a dispense drives its `refills_remaining` to zero. `REVOKED` and `EXHAUSTED` are terminal.

The `refills_remaining` figure is conserved: it equals `refills_authorized` minus the number of dispensed refill orders that have not been reversed. A `Patient` or `ClinicAdmin` requests a `RefillOrder` by supplying the `prescription_id`, the `membership_id` that supplies the member discount, the `patient_id`, the `requested_quantity_units`, and the `expected_prescription_version` OCC guard of §2.5. The request is validated in order: the version guard (`ERR_STALE_VERSION`), then the referenced prescription must not be `SUSPENDED` or `REVOKED` — an `EXHAUSTED` prescription passes this particular check — or the request is rejected with `ERR_PRESCRIPTION_SUSPENDED`; then the membership's `subscription_status` must be `ACTIVE`, or the request is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`; then the membership's `payment_status` must be `CURRENT`, or the request is rejected with `ERR_MEMBERSHIP_DELINQUENT`. A successful create computes the provisional charge, stores it in `provisional_charge_cents`, sets the order to `PENDING_REVIEW`, and increments the prescription's `version` by one. Refill orders may be listed and filtered by `prescription_id`, `membership_id`, or `patient_id`.

The self-pay charge is a tiered, capped calculation with a conditional surcharge, computed identically for the provisional and final variants but over different unit counts. The number of units is `requested_quantity_units` for the provisional charge computed at create time and `dispensed_quantity_units` for the final charge computed at dispense time. Compute the gross drug cost in three marginal quantity tiers: the first 4 units are each billed at the prescription's full `unit_price_cents`; the next 6 units — those numbered 5 through 10 — are each billed at the `unit_price_cents` multiplied by 0.90 and rounded half up to a whole cent; and every unit beyond the tenth is billed at the `unit_price_cents` multiplied by 0.80 and rounded half up to a whole cent. Summing the three tier amounts gives the gross drug cost. If the prescription is controlled (`is_controlled` true), add a flat controlled-substance surcharge of 1500 cents; otherwise add nothing. Compute the member discount as the gross drug cost multiplied by the `refill_discount_pct` of the plan tied to the refill order's membership, rounded half up to a whole cent. The subtotal is the gross drug cost plus the surcharge minus the member discount. The final charge is the subtotal clamped to a floor of 1000 cents and a ceiling of 100000 cents — that is, a subtotal below 1000 becomes 1000 and a subtotal above 100000 becomes 100000. The provisional variant stores its result in `provisional_charge_cents`; the final variant stores it in `final_charge_cents`, which may differ from the provisional figure when the dispensed quantity differs from the requested quantity.

A `Pharmacist` dispenses a refill order, moving it from `PENDING_REVIEW` to `DISPENSED` and supplying the `dispensed_quantity_units`. Dispense is validated in order: the order must be `PENDING_REVIEW`, or it fails with `ERR_REFILL_NOT_DISPENSABLE`; the prescription must not be `SUSPENDED` or `REVOKED`, or it fails with `ERR_PRESCRIPTION_SUSPENDED`; and the prescription must have at least one refill remaining, or it fails with `ERR_NO_REFILLS_REMAINING` — an `EXHAUSTED` prescription reaches and fails this last check. On dispense the system computes `final_charge_cents` from `dispensed_quantity_units`, decrements the prescription's `refills_remaining` by one, and — if that decrement drives `refills_remaining` to zero — moves the prescription to `EXHAUSTED`. A `Pharmacist` may reverse a dispensed order, moving it from `DISPENSED` to `REVERSED` (otherwise `ERR_INVALID_STATE`); reversal increments the prescription's `refills_remaining` by one as a compensating entry, and if the prescription was `EXHAUSTED` and now has a positive `refills_remaining`, it is restored to `ISSUED`. A `PENDING_REVIEW` order may also be cancelled — by a `Patient`, `ClinicAdmin`, `Clinician`, or by the system's prescription-revoke cascade — moving it to `CANCELLED`; cancelling anything not in `PENDING_REVIEW` fails with `ERR_INVALID_STATE`. `CANCELLED` and `REVERSED` are terminal.

### 3.7. Adverse Events and Segregation of Duties

Either a `Clinician` or a `Patient` reports an `AdverseEvent`, supplying the `patient_id`, the implicated `plan_id`, a free-text `description`, and an optional `reported_by` clinician reference (a patient self-report leaves it null). The event begins in `REPORTED`, and its `severity` is not yet set. Events may be listed and filtered by `patient_id`, `plan_id`, or `reported_by`.

Triage is where segregation of duties is enforced. A `Clinician` triages a reported event, supplying a `severity` of `MILD` or `SEVERE`. Two guards apply: the event must be in `REPORTED`, or triage fails with `ERR_INVALID_STATE`; and the reviewing clinician's `X-User-ID` must differ from the implicated plan's `clinician_id`, or triage fails with `ERR_SEGREGATION_OF_DUTIES` — the safety reviewer may never be the plan's own prescriber. A `MILD` triage sets the event's `severity` to `MILD` and moves it to `MILD_LOGGED` with no effect on the plan. A `SEVERE` triage sets the event's `severity` to `SEVERE`, moves it to `SEVERE_ESCALATED`, and suspends the implicated plan (cascade link 1 into §3.5's suspension chain), which then revokes the plan's prescriptions and cancels their pending refills. From either `MILD_LOGGED` or `SEVERE_ESCALATED`, a `Clinician` resolves the event to `RESOLVED`; a resolve attempted from any other state fails with `ERR_INVALID_STATE`. `RESOLVED` is terminal.

### 3.8. Patient Monitoring Summary and Risk Scoring

The monitoring summary is a computed, read-only view available to a `ClinicAdmin` or `Clinician`. It reports four fields: `provisional_risk_score`, `comprehensive_risk_score`, `monitoring_status`, and `reviewed_panels_in_window`. The window of interest is the set of the patient's `REVIEWED` lab panels whose `drawn_at` is within ninety days of the current logical clock; `reviewed_panels_in_window` is the count of those panels.

Each in-window panel contributes a per-panel risk score, capped at 100, formed by summing three components. The hematocrit component is 8 multiplied by the greater of 0 and the floor of the panel's `hematocrit_pct` minus 50. The PSA component is 15 multiplied by the ceiling of the greater of 0.0 and the panel's `psa_ng_ml` minus 3.0. The low-testosterone component is a flat penalty of 25 when the panel's `total_testosterone_ng_dl` is below 300, and 0 otherwise. The per-panel score is the smaller of 100 and the sum of those three components.

The `provisional_risk_score` is the per-panel score of the single most recent in-window panel, chosen by latest `drawn_at`, breaking ties by latest `created_at`. The `comprehensive_risk_score` is the mean of the per-panel scores across all in-window panels, rounded half up to a whole integer; when there are no in-window panels, both scores are 0. Finally, `monitoring_status` is the string `CURRENT` when at least one `REVIEWED` panel falls in the ninety-day window, and `OVERDUE` when none do — mirroring the prescribing guard of §3.6, under which a patient with no recent reviewed panel cannot be issued a new prescription.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions and computed reads — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clinic/clinicians` | Register a clinician (prescriber) | ClinicAdmin |
| GET | `/clinic/clinicians/{id}` | Get clinician | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/pharmacists` | Register a pharmacist | ClinicAdmin |
| GET | `/clinic/pharmacists/{id}` | Get pharmacist | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/patients` | Intake a patient | ClinicAdmin, Clinician |
| GET | `/clinic/patients/{id}` | Get patient | ClinicAdmin, Clinician, Pharmacist, Patient |
| GET | `/clinic/patients/{id}/monitoring-summary` | Computed monitoring risk (dual-variant) | ClinicAdmin, Clinician |
| POST | `/clinic/membership-plans` | Create a membership plan | ClinicAdmin |
| GET | `/clinic/membership-plans/{id}` | Get membership plan | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/memberships` | Create a membership | ClinicAdmin |
| GET | `/clinic/memberships/{id}` | Get membership | ClinicAdmin, Clinician, Pharmacist, Patient |
| GET | `/clinic/memberships` | List/filter memberships | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/memberships/{id}/activate` | Activate membership | ClinicAdmin |
| POST | `/clinic/memberships/{id}/record-payment` | Record a payment outcome | ClinicAdmin |
| POST | `/clinic/memberships/{id}/change-plan` | Switch plan with mid-cycle proration | ClinicAdmin |
| POST | `/clinic/memberships/{id}/cancel` | Cancel membership | ClinicAdmin |
| POST | `/clinic/draw-stations` | Create a phlebotomy station | ClinicAdmin |
| GET | `/clinic/draw-stations/{id}` | Get draw station | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/lab-panels` | Order a lab panel | Clinician |
| GET | `/clinic/lab-panels/{id}` | Get lab panel | ClinicAdmin, Clinician, Pharmacist, Patient |
| GET | `/clinic/lab-panels` | List/filter lab panels | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/lab-panels/{id}/draw` | Mark panel drawn | Clinician, ClinicAdmin |
| POST | `/clinic/lab-panels/{id}/result` | Enter results | Clinician |
| POST | `/clinic/lab-panels/{id}/review` | Review results; may hold plan | Clinician |
| POST | `/clinic/lab-draw-appointments` | Book a lab-draw appointment | Patient, ClinicAdmin, Clinician |
| GET | `/clinic/lab-draw-appointments/{id}` | Get appointment | ClinicAdmin, Clinician, Pharmacist, Patient |
| GET | `/clinic/lab-draw-appointments` | List/filter appointments | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/lab-draw-appointments/{id}/complete` | Complete an appointment | Clinician, ClinicAdmin |
| POST | `/clinic/lab-draw-appointments/{id}/cancel` | Cancel an appointment (refund credit) | Patient, ClinicAdmin, Clinician |
| POST | `/clinic/telehealth-visits` | Book a telehealth visit | Patient, ClinicAdmin |
| GET | `/clinic/telehealth-visits/{id}` | Get visit | ClinicAdmin, Clinician, Pharmacist, Patient |
| GET | `/clinic/telehealth-visits` | List/filter visits | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/telehealth-visits/{id}/complete` | Complete a visit | Clinician |
| POST | `/clinic/telehealth-visits/{id}/cancel` | Cancel a visit | Patient, ClinicAdmin, Clinician |
| POST | `/clinic/treatment-plans` | Create a treatment plan (DRAFT) | Clinician |
| GET | `/clinic/treatment-plans/{id}` | Get treatment plan | ClinicAdmin, Clinician, Pharmacist, Patient |
| GET | `/clinic/treatment-plans` | List/filter treatment plans | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/treatment-plans/{id}/activate` | Activate a plan | Clinician |
| POST | `/clinic/treatment-plans/{id}/titrations` | Propose a dose titration (OCC) | Clinician |
| GET | `/clinic/treatment-plans/{id}/titrations` | List titration rounds for a plan | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/treatment-plans/{id}/titrations/{titrationId}/confirm` | Confirm and apply the pending titration | Clinician |
| POST | `/clinic/treatment-plans/{id}/suspend` | Suspend a plan (cascades) | Clinician, ClinicAdmin |
| POST | `/clinic/treatment-plans/{id}/resume` | Resume from MONITORING_HOLD | Clinician |
| POST | `/clinic/prescriptions` | Issue a controlled-substance prescription | Clinician |
| GET | `/clinic/prescriptions/{id}` | Get prescription | ClinicAdmin, Clinician, Pharmacist, Patient |
| GET | `/clinic/prescriptions` | List/filter prescriptions | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/prescriptions/{id}/revoke` | Revoke a prescription (cascades refills) | Clinician |
| POST | `/clinic/refill-orders` | Request a refill (OCC on prescription) | Patient, ClinicAdmin |
| GET | `/clinic/refill-orders/{id}` | Get refill order | ClinicAdmin, Clinician, Pharmacist, Patient |
| GET | `/clinic/refill-orders` | List/filter refill orders | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/refill-orders/{id}/dispense` | Dispense a refill (final charge) | Pharmacist |
| POST | `/clinic/refill-orders/{id}/cancel` | Cancel a pending refill | Patient, ClinicAdmin, Clinician |
| POST | `/clinic/refill-orders/{id}/reverse` | Reverse a dispensed refill | Pharmacist |
| POST | `/clinic/adverse-events` | Report an adverse event | Clinician, Patient |
| GET | `/clinic/adverse-events/{id}` | Get adverse event | ClinicAdmin, Clinician, Pharmacist, Patient |
| GET | `/clinic/adverse-events` | List/filter adverse events | ClinicAdmin, Clinician, Pharmacist, Patient |
| POST | `/clinic/adverse-events/{id}/triage` | Triage an event (segregation of duties) | Clinician |
| POST | `/clinic/adverse-events/{id}/resolve` | Resolve a triaged event | Clinician |
| POST | `/clinic/_clock/set_current_utc` | Set the server logical clock | ClinicAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_TITRATION_NOT_PENDING` | 409 Conflict |
| `ERR_PANEL_NOT_RESULTED` | 409 Conflict |
| `ERR_BASELINE_NOT_REVIEWED` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 Conflict |
| `ERR_MEMBERSHIP_DELINQUENT` | 402 Payment Required |
| `ERR_INSUFFICIENT_LAB_DRAW_CREDITS` | 402 Payment Required |
| `ERR_PATIENT_MISMATCH` | 409 Conflict |
| `ERR_CLINICIAN_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_MONITORING_OVERDUE` | 422 Unprocessable Entity |
| `ERR_HEMATOCRIT_UNSAFE` | 422 Unprocessable Entity |
| `ERR_CLINICIAN_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_DRAW_STATION_AT_CAPACITY` | 409 Conflict |
| `ERR_PRESCRIPTION_SUSPENDED` | 409 Conflict |
| `ERR_REFILL_NOT_DISPENSABLE` | 409 Conflict |
| `ERR_NO_REFILLS_REMAINING` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_SCHEDULED` | 409 Conflict |
