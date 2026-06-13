# Optometry & Vision Plan API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Optometry & Vision Plan API, a back-office platform for an optometric practice that must reconcile clinical care with two fundamentally different ways of paying for it. A single patient visit can flow down two divergent financial channels — the routine vision-plan channel underwritten by a carrier such as VSP or EyeMed, or the medical-insurance channel reserved for diagnostic eye disease — and the same clinical inputs produce different patient costs depending on which channel is chosen. The platform's central challenge is keeping the money consistent: a per-patient ledger of outstanding balances, carrier benefit pools that drain and refill as eyewear is ordered and cancelled, and claim totals that must always agree with the draws that produced them.

Beyond the financial reconciliation, the system is also a compliance instrument. Prescriptions expire on a clinical schedule, eyewear may only be dispensed against a current prescription, lab remakes are confined to a warranty window and a maximum count, benefit periods open and close on a calendar, and patients must be recalled for their next routine exam on a cadence the practice configures. Four staff roles — a front-desk coordinator, an optometrist, an optician, and a biller — each own a slice of this lifecycle, and the API enforces that ownership strictly while allowing the entities they create to reference one another across a flat, peer-to-peer topology.

Because so much downstream behavior (Rx expiry, benefit-period windows, remake deadlines, recall scheduling) depends on the passage of time, the system operates against a server-simulated clock rather than wall-clock time. All date and time arithmetic described in this document is evaluated against that simulated clock, which an operator may advance to drive test scenarios deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. The system recognizes exactly four roles, spelled precisely as follows: `FrontDesk`, `Optometrist`, `Optician`, and `Biller`. If either header is missing, or if `X-User-Role` does not name one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles divide responsibility along clinical and administrative lines. A `FrontDesk` coordinator handles scheduling, registration of patients, providers, and eligibility benefit periods, and recall outreach. An `Optometrist` conducts exams and refractions, writes and revokes prescriptions, and finalizes encounters. An `Optician` places, advances, dispenses, remakes, and cancels lab orders. A `Biller` drafts, adjudicates, settles, denies, voids, and submits claims and records carrier acknowledgements.

Two of these roles are tied to a persisted clinical identity, and two are not. When `X-User-Role` is `Optometrist`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare the resource's provider foreign key to `X-User-ID`. In particular, an encounter's clinical conduct is owned by the optometrist whose `id` equals the encounter's `provider_id`. When `X-User-Role` is `Optician`, `X-User-ID` is likewise the `id` of the acting `Provider`; the optician identity is what the system records as the dispensing optician on a lab order. By contrast, when `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. Similarly, when `X-User-Role` is `Biller`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, used to authorize claim operations but never matched against a stored `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Simulated Clock

Most resources in this system are durable, mutable records and carry a standard set of system-managed fields. Each such resource exposes an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recorded when the resource is first created; an `updated_at` timestamp, an ISO 8601 UTC value with three fractional digits refreshed on every mutation; and a `version`, an integer that begins at its initial value on creation and increments by one with each mutation of the resource. These common fields apply to patients, encounters, prescriptions, eligibilities, benefit pools, lab orders, claims, and recall reminders.

Two entities are deliberately leaner. A `Provider` carries only `id` and `created_at` — it has neither an `updated_at` nor a `version`, because provider records are not mutated after registration. The internal clock record likewise carries only its single field and is not a versioned resource. Whenever this document refers to "the clock," "the system clock," or "the current date," it means the server's simulated wall clock, exposed through the `current_utc` field of the clock state. An operator may set this clock to an arbitrary instant; doing so re-evaluates prescription expiry, benefit-period windows, and remake deadlines on every subsequent read or use. All expiry, in-period, and remake-window comparisons in this document are made against `current_utc`.

### 2.5. Nested Resource Retrieval and Reference Validation

The entity model is flat: resources are peers linked by foreign-key references rather than deeply nested URL hierarchies. A handful of paths nonetheless carry more than one identifier — for example a patient's prescriptions or an eligibility's benefit pools. For any such path, the system validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not correspond to an existing resource, before evaluating any later segment or any business rule.

Foreign-key references supplied in a request body are validated separately. When a creation request names a related resource that does not exist — for instance a `patient_id`, `provider_id`, `encounter_id`, `eligibility_id`, or `prescription_id` that matches no stored record — the request is rejected with `ERR_REFERENCE_NOT_FOUND`. This reference check applies to opening an encounter, issuing a prescription, opening an eligibility, placing a lab order, drafting a claim, and scheduling a recall reminder.

### 2.6. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order, and the first failure determines the error returned. Authentication comes first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED`. Role authorization comes second: a known but unpermitted role yields `ERR_FORBIDDEN_ROLE`. Path-resource existence comes third, yielding `ERR_NOT_FOUND`. Body foreign-key existence comes fourth, yielding `ERR_REFERENCE_NOT_FOUND`. Request-schema conformance comes fifth: required fields present, correct types, legal enum values, and honored numeric ranges — any violation yields `ERR_INVALID_REQUEST`. State legality comes sixth: a resource that is not in a state from which the requested transition is legal yields `ERR_INVALID_STATE`. Only after these six gates are passed does the system evaluate the domain-specific business rules described throughout §2 and §3 — provider-role checks, prescription-dispensability, remake windows, carrier matching, benefit-period and benefit-availability checks, medical-billing eligibility, the stale-eligibility-version check, benefit exhaustion, and payment-amount checks — each carrying its own error described where the workflow it guards is discussed. Where a single endpoint is guarded by several of these later business rules, their relative ordering is called out in the workflow narrative that introduces them.

### 2.7. Monetary Amounts, Precision, and Rounding

All monetary amounts in the system are expressed and stored as integer cents — exam fees, refraction fees, copays, allowances, frame and lens charges, draws, patient responsibilities, settlements, surcharges, and balances alike. Whenever a calculation produces a fractional cent (for example, applying a coinsurance percentage to a fee, or scaling a frame allowance by a tier multiplier), the result is rounded to a whole cent using the round-half-up method, where a value exactly halfway between two integers rounds up to the larger magnitude. The specific points at which rounding is applied are stated in the calculation narratives in §3; unless a narrative says otherwise, every intermediate monetary figure that this document names as rounded is rounded half up to a whole number of cents.

### 2.8. Benefit-Pool Reconciliation and Derived Balances

Several fields in this system are derived: they are never set directly by a client but are recomputed by the server so they always agree with the events that produced them. A `BenefitPool` tracks an `allotted_cents` capacity, a `consumed_cents` running total of draws committed against it, and a `remaining_cents` figure that is always the allotted capacity minus what has been consumed and is never allowed to fall below zero. Every draw against a pool and every release back to it recomputes `consumed_cents` and then `remaining_cents`. In parallel, a patient's `outstanding_patient_balance_cents` is a derived roll-up reconciled on every claim mutation, and a claim's own financial fields are recomputed whenever the claim is adjudicated, paid, or voided. The precise formulas live with the workflows that drive them in §3; the governing principle here is that these derived figures are recomputed atomically inside the request that triggers them, never left stale.

### 2.9. Hierarchical Consistency and Cascading Side Effects

All mutations and their cascades are atomic within the triggering request: when one operation must touch more than one entity, every affected entity is updated, and every affected `version` incremented and `updated_at` refreshed, before the request returns. Several operations in this system reach across aggregates. Drawing or releasing materials against a benefit pool can flip the owning eligibility's lifecycle state; adjudicating or voiding a routine claim consumes or restores an exam benefit on the eligibility; finalizing a routine exam can both reschedule a patient's recall and fulfill a pending reminder. These cross-entity cascades are described in full where the driving workflow is discussed in §3, and each entity they touch has its `version` advanced as part of the same atomic operation.

### 2.10. Optimistic Concurrency on Benefit Draws

Placing a lab order that draws against a benefit period is the one operation in this system protected by optimistic concurrency control, because two such draws against the same pool could otherwise oversubscribe the materials allowance. When a lab-order creation names an `eligibility_id` to draw against, the request must also carry `expected_eligibility_version`, an OCC token holding the `version` of that `Eligibility` the client last observed. The server compares this token to the eligibility's current `version`. If another writer has advanced the eligibility's `version` since the client last read it — for instance by placing an earlier benefit-drawing order that committed a materials draw, possibly exhausting the pool — the client's view of the remaining allowance is stale, and the create is rejected with `ERR_STALE_ELIGIBILITY_VERSION` at HTTP status 412, preventing a draw against an unobserved state. The `expected_eligibility_version` field is required precisely when `eligibility_id` is set; a self-pay lab order that names no eligibility draws against no pool and carries no version token.

## 3. Business Logic & Workflows

### 3.1. Registering Patients, Providers, and the Recall Cadence

A `FrontDesk` coordinator seeds the system with the people it serves. Registering a patient captures the patient's `full_name`, `date_of_birth` (an ISO date in `YYYY-MM-DD` form that must be a valid date in the past relative to the system clock), and `plan_carrier`, which is one of `VSP`, `EYEMED`, or `NONE` — `NONE` meaning the patient is self-pay only. Two further inputs are optional at registration: `medical_insurance_on_file`, a boolean that defaults to false and gates whether the patient may ever be billed through the medical channel, and `recall_interval_months`, an integer between 1 and 36 that defaults to 12 and sets how many months elapse between routine exams for recall purposes.

A freshly registered patient has no exam history, so its computed `last_routine_exam_date` and its computed `recall_due_date` both begin null, and its computed `outstanding_patient_balance_cents` begins at zero. The `last_routine_exam_date` holds the ISO date of the patient's most recent finalized routine encounter, and the `recall_due_date` is that date advanced by `recall_interval_months` calendar months; while there is no finalized routine exam on record, both remain null. Patients are retrievable individually — a read returns the live computed recall and balance fields — and in lists filterable by `plan_carrier`.

Registering a provider captures a `full_name`, a `role` that is either `OPTOMETRIST` or `OPTICIAN`, and an `npi` that must be exactly ten digits. Providers may be listed, optionally filtered by `role`. A provider record is immutable once created and, as noted in §2.4, carries neither an `updated_at` nor a `version`.

### 3.2. The Clinical Encounter and Its Lifecycle

An encounter represents one clinical visit and is opened by a `FrontDesk` coordinator or an `Optometrist`. Opening an encounter requires the `patient_id` being seen and the `provider_id` of the optometrist who will conduct the exam — and that referenced provider's `role` must be `OPTOMETRIST`, or the request is rejected with `ERR_WRONG_PROVIDER_ROLE`. The caller also supplies an `encounter_type`, either `ROUTINE_VISION` or `MEDICAL_EYE`, which determines whether the visit ultimately draws the vision plan or medical insurance; an optional `chief_complaint_code` that defaults to `Z01`, where any code beginning with the letter H (such as H40 for glaucoma) marks the complaint as medically eligible; an `exam_fee_cents` charge that must be zero or greater; and an optional `refraction_fee_cents` charge that defaults to 0 and must likewise be zero or greater. A new encounter begins in `OPEN` status with its computed `refraction_recorded` flag false.

An encounter moves through a linear clinical pipeline with one escape hatch. While the encounter is `OPEN`, issuing the first prescription from it (described in §3.3) advances it from `OPEN` to `REFRACTED` and sets `refraction_recorded` true. Once `REFRACTED`, the conducting optometrist may finalize it, advancing it from `REFRACTED` to `FINALIZED`; finalization is legal only from `REFRACTED`. Alternatively, while still `OPEN` and before any prescription references it, a `FrontDesk` coordinator may void it, advancing it from `OPEN` to `VOIDED`; voiding is permitted only when the encounter is `OPEN` and no prescription references it. Both `FINALIZED` and `VOIDED` are terminal. Any attempt to finalize or void an encounter that is not in the required starting state is rejected with `ERR_INVALID_STATE`.

Finalizing an encounter carries consequences beyond the status change. When the finalized encounter is of type `ROUTINE_VISION`, the system sets the patient's `last_routine_exam_date` to the current clock date and recomputes the patient's `recall_due_date` as that date plus the patient's `recall_interval_months` calendar months. Finalizing a routine encounter also fulfills recall outreach: any reminder for that patient that is in `SENT` status and whose due date has already passed is advanced to `FULFILLED`, as described in §3.7. Encounters are retrievable individually and in lists filterable by `patient_id`, `provider_id`, and `status`.

### 3.3. Writing, Superseding, Expiring, and Revoking Prescriptions

A prescription is the clinical record an optometrist writes from a refracted exam, and only an `Optometrist` may issue one. Issuing it requires naming the source `encounter_id`, whose referenced encounter must be in `REFRACTED` or `FINALIZED` status; the `rx_type`, either `EYEGLASS` or `CONTACT`; the right-eye and left-eye sphere powers `sphere_od` and `sphere_os`, each a diopter value from -20.00 to 20.00 that must be a multiple of 0.25; and the `issue_date` the prescription was written, which is the basis for its expiry. The patient the prescription belongs to is captured automatically: the computed `patient_id` is copied from the source encounter. A newly issued prescription begins `ACTIVE`.

Two values are computed from the prescription type at issue time. The `expiry_months` validity window is 24 months for an `EYEGLASS` prescription and 12 months for a `CONTACT` prescription, and the `expiry_date` is the `issue_date` advanced by that many months. A prescription is considered expired once the clock date is strictly later than its `expiry_date`; this expiry is evaluated on read and on use, and when it is detected the prescription's status is treated as `EXPIRED`, after which no lab order may be placed against it.

Issuing a prescription also drives the source encounter and any predecessor prescription. If the encounter is still `OPEN`, issuing the first prescription from it sets its `refraction_recorded` flag true and advances it from `OPEN` to `REFRACTED`. If the patient already holds an `ACTIVE` prescription of the identical `rx_type`, that older prescription is superseded — its status moves from `ACTIVE` to `SUPERSEDED` and its `version` is incremented — so that at most one active prescription of each type stands for a patient at any time.

An optometrist may also revoke an active prescription, moving it from `ACTIVE` to `REVOKED`. Revocation is permitted only when the prescription is `ACTIVE` and no lab order in `PLACED` or `IN_LAB` status references it; `REVOKED` is terminal. A prescription that is `EXPIRED`, `SUPERSEDED`, or `REVOKED` is no longer dispensable. Prescriptions are retrievable individually (the returned status reflects expiry against the current clock), by patient, and by filters over `encounter_id` and `patient_id`; the patient and `rx_type` and `status` filters support reverse lookup of a patient's prescription history.

### 3.4. Opening a Vision Benefit Period and Its Pools

A vision benefit period is the carrier-funded envelope a patient's eyewear and exam costs draw from, and a `FrontDesk` coordinator opens one. Opening it requires the `patient_id` it belongs to; the `carrier` underwriting it, which is one of `VSP` or `EYEMED` and must equal the patient's own `plan_carrier`, failing which the request is rejected with `ERR_CARRIER_MISMATCH`; the `benefit_period_start` ISO date on which the twelve-month period opens; the fixed `exam_copay_cents` the patient pays when the exam benefit is consumed, which must be zero or greater; and the total `materials_allowance_cents` toward frames and lenses for the period, which must be zero or greater. The system computes the `benefit_period_end` as the start date plus twelve months, and the eligibility is treated as in-period when the clock date falls on or after `benefit_period_start` and on or before `benefit_period_end`. A new eligibility begins `ACTIVE` with its computed `exam_benefit_available` flag true.

Opening an eligibility automatically provisions its two benefit pools, exactly one of each `pool_type` per eligibility. The `MATERIALS` pool's `allotted_cents` is copied from the eligibility's `materials_allowance_cents`, and it tracks frame-and-lens draws. The `EXAM` pool represents the single routine-exam benefit slot for the period. Both pools begin with `consumed_cents` of zero and a `remaining_cents` equal to their full allotment, each pool naming its owning `eligibility_id`. Eligibilities are retrievable individually and in lists filterable by `patient_id` and `status`; an eligibility's pools are reachable as a set, optionally narrowed by `pool_type`, and each pool is also retrievable on its own and listable with filters over `eligibility_id` and `pool_type`.

The eligibility's own lifecycle reacts to its materials pool. When a draw drives the `MATERIALS` pool's `remaining_cents` to exactly zero, the eligibility is automatically moved from `ACTIVE` to `EXHAUSTED`, which blocks any further allowance-drawing order. Conversely, when a later cancellation releases a draw and restores the `MATERIALS` pool's `remaining_cents` above zero, an eligibility that was `EXHAUSTED` bubbles back up from `EXHAUSTED` to `ACTIVE`. A `FrontDesk` coordinator may also terminate a benefit period, moving it to `TERMINATED`; termination is permitted when the eligibility is `ACTIVE` or `EXHAUSTED` and no lab order in `PLACED`, `IN_LAB`, or `REMAKE_REQUESTED` status references it. `TERMINATED` is terminal.

### 3.5. Placing a Lab Order and the Materials Draw

An `Optician` places a frame-and-lens lab order to fulfill a prescription. Placing it requires the `prescription_id` being fulfilled, whose referenced prescription must be `ACTIVE` and not expired; the `frame_charge_cents` retail price of the chosen frame and the `lens_charge_cents` retail price of the lens package, each zero or greater; and an optional `frame_brand_tier` of `STANDARD`, `PREMIUM`, or `DESIGNER`, defaulting to `STANDARD`. An order that draws a benefit additionally names the `eligibility_id` to draw against and, as required by §2.10, the `expected_eligibility_version` token; an order that omits `eligibility_id` is self-pay and draws against no pool. A new order begins `PLACED` with a `remake_count` of zero, and its `dispensing_optician_id` and `dispensed_at` are null until the order is dispensed.

If a lab order — whether at placement or at dispense — would be created or dispensed against a prescription that is `EXPIRED`, `SUPERSEDED`, or `REVOKED`, it is rejected with `ERR_PRESCRIPTION_NOT_DISPENSABLE`, because lenses must match a current prescription. A benefit-drawing order also enforces the carrier and period rules: the patient's `plan_carrier` must not be `NONE` (a benefit draw for a `NONE`-carrier patient is rejected with `ERR_CARRIER_MISMATCH`); the eligibility must be in-period, failing which the order is rejected with `ERR_BENEFIT_PERIOD_CLOSED`; and the eligibility must be `ACTIVE` with materials remaining, since an `EXHAUSTED` period cannot start a new draw and is rejected with `ERR_BENEFIT_EXHAUSTED`. On a benefit-drawing create these business gates are evaluated in this order: prescription dispensability first, then carrier matching, then benefit-period currency, then the stale-eligibility-version OCC check of §2.10, then benefit exhaustion.

When the order is placed, the system computes the materials cost provisionally. First it adds the `frame_charge_cents` and `lens_charge_cents` to get the retail total. It then scales a base frame allowance of 13,000 cents by a tier multiplier — 1.00 for `STANDARD`, 1.20 for `PREMIUM`, and 1.50 for `DESIGNER` — and rounds that product half up to whole cents to get the frame cap. The carrier-covered frame amount is the smaller of the actual `frame_charge_cents` and that frame cap. The desired draw is the covered frame amount plus the full `lens_charge_cents`. Because this order has no draw committed yet at placement, the room available to it is simply the `MATERIALS` pool's current `remaining_cents`; the actual draw committed, recorded on the order as `materials_draw_cents`, is the smaller of the desired draw and that available room, so a draw can never exceed the room left in the pool. The pool's `consumed_cents` is then increased by that committed draw and its `remaining_cents` recomputed. The patient's out-of-pocket for materials, recorded as `patient_materials_cost_cents`, is the retail total minus the committed draw. For a self-pay order, `materials_draw_cents` is zero and `patient_materials_cost_cents` is the full retail total. Committing a benefit draw advances the eligibility's `version` by one, and if the draw drives the pool's `remaining_cents` to zero the eligibility flips to `EXHAUSTED` as described in §3.4.

Lab orders are retrievable individually and in lists offering reverse lookup by `prescription_id`, by `eligibility_id`, by `dispensing_optician_id`, and by `status`.

### 3.6. Advancing, Dispensing, Remaking, and Cancelling Lab Orders

The lab-order lifecycle is a loop, not a line, because eyewear can be remade. An `Optician` sends a `PLACED` order to the lab, advancing it from `PLACED` to `IN_LAB`. From `IN_LAB`, the optician dispenses the finished eyewear to the patient, supplying the `dispensing_optician_id` of the dispensing provider, whose `role` must be `OPTICIAN` or the request is rejected with `ERR_WRONG_PROVIDER_ROLE`; dispensing advances the order from `IN_LAB` to `DISPENSED`, stamps `dispensed_at` with the current clock instant, and records the `dispensing_optician_id`. Dispensing is legal only from `IN_LAB`, and only while the referenced prescription is still `ACTIVE` and unexpired — otherwise `ERR_PRESCRIPTION_NOT_DISPENSABLE` applies.

At dispense the materials cost is re-evaluated as final. If the `MATERIALS` pool's remaining room has changed since placement — for example because a sibling order on the same pool was cancelled and freed room — the draw is recomputed. For this final recompute, the room available to the order is the pool's current `remaining_cents` plus this order's own already-committed draw, conceptually returning the order's existing draw to the pool before re-drawing; the new draw is again the smaller of the desired draw and that available room. The difference between the new draw and the previously committed `materials_draw_cents` is the delta by which the pool's `consumed_cents` is adjusted, and `materials_draw_cents`, `remaining_cents`, and the order's `patient_materials_cost_cents` are reconciled to the final figures. Because a sibling cancellation can free room, the final draw can be larger than the provisional one.

A dispensed order may be sent back for a remake within a warranty window. Requesting a remake advances the order from `DISPENSED` to `REMAKE_REQUESTED` and is permitted only when the order is `DISPENSED`, when the current clock instant is no later than 90 days after `dispensed_at`, and when the order's `remake_count` is below the maximum of two completed remakes; a request that falls outside the 90-day window or that has already reached two remakes is rejected with `ERR_REMAKE_WINDOW_CLOSED`. A remake request may carry an optional `reason`. Crucially, a remake commits no new materials draw — it reuses the original benefit draw, conserving the quantity already drawn from the pool. From `REMAKE_REQUESTED` the optician sends the order back to the lab, advancing it from `REMAKE_REQUESTED` to `IN_LAB` and incrementing the order's `remake_count` by one.

The second remake carries a surcharge. When sending a remake back to the lab would make the order's `remake_count` become two, the system applies a remake surcharge, evaluated in a pinned order: it first computes the prospective new count as the current `remake_count` plus one, then derives the surcharge from that prospective count, then commits the count. If the prospective new count is at least two, a surcharge of 2,500 cents is added to the order's `patient_materials_cost_cents`; otherwise the surcharge is zero. The surcharge is charged to the patient's materials cost only and is never added to or drawn from the benefit pool.

An optician may cancel an order while it is `PLACED` or `IN_LAB`, advancing it to `CANCELLED`, which is terminal; cancellation is legal only from those two states. Cancelling a benefit-drawing order releases its draw: the `MATERIALS` pool's `consumed_cents` is reduced by the order's `materials_draw_cents`, `remaining_cents` is recomputed, and the order's and the eligibility's `version` are each incremented. If that release lifts a pool that backs an `EXHAUSTED` eligibility back above zero remaining, the eligibility bubbles up from `EXHAUSTED` to `ACTIVE`, the cross-entity restoration described in §3.4.

### 3.7. Recall Reminders and Their Fulfillment

A `FrontDesk` coordinator schedules a recall reminder to bring a patient back for the next routine exam. Scheduling one requires the `patient_id` to remind and a `channel` of `EMAIL`, `SMS`, or `MAIL`; the reminder's `due_date` is copied from the patient's current `recall_due_date` at generation time. A new reminder begins `SCHEDULED`. The coordinator may mark a scheduled reminder as sent, advancing it from `SCHEDULED` to `SENT`, or cancel a scheduled reminder, advancing it from `SCHEDULED` to `CANCELLED`; both transitions are legal only from `SCHEDULED`, and `CANCELLED` and `FULFILLED` are terminal.

A reminder is fulfilled by clinical reality rather than an explicit call. As noted in §3.2, when a `ROUTINE_VISION` encounter for the patient is finalized after the reminder's `due_date` has passed, a reminder in `SENT` status for that patient advances from `SENT` to `FULFILLED` as a bubble-up from the encounter finalization. Reminders are retrievable individually and in lists filterable by `patient_id` and `status`.

### 3.8. Drafting and Adjudicating Claims: Routine versus Medical

A `Biller` bills a finalized visit by drafting a claim against its `encounter_id`, whose referenced encounter must be in `FINALIZED` status. A routine claim also names the `eligibility_id` whose vision benefit it draws; a medical claim names no eligibility. On draft the claim begins with `claim_status` of `DRAFT` and `submission_status` of `UNSUBMITTED`, and its `billing_route` is derived from the encounter's `encounter_type` — a `ROUTINE_VISION` encounter yields a `ROUTINE` route drawing the vision plan, and a `MEDICAL_EYE` encounter yields a `MEDICAL` route drawing medical insurance. A medical route is permitted only when the patient's `medical_insurance_on_file` is true and the encounter's `chief_complaint_code` begins with the letter H; a medical claim that fails either condition is rejected with `ERR_MEDICAL_BILLING_INELIGIBLE`.

Adjudicating a `DRAFT` claim advances it from `DRAFT` to `ADJUDICATED` and computes its money. Adjudication is legal only from `DRAFT`; for a routine claim it additionally requires the referenced eligibility to be in-period and its `exam_benefit_available` flag to be true, and a routine claim adjudicated when the exam benefit is no longer available is rejected with `ERR_BENEFIT_PERIOD_CLOSED`. The medical-eligibility rule above is re-checked at adjudication as well. The cost calculation begins from the encounter's billed components. For a routine claim, the billed amount is the encounter's `exam_fee_cents` plus its `refraction_fee_cents`; the carrier covers the exam slot so that the plan-paid portion is the billed amount minus the eligibility's `exam_copay_cents` but never less than zero, and the patient responsibility is the smaller of the billed amount and the `exam_copay_cents` — the refraction is bundled into the covered exam benefit. The resulting figures are stored as the claim's `billed_amount_cents`, `plan_paid_cents`, and `patient_responsibility_cents`.

For a medical claim, only the exam fee is covered and the refraction is non-covered. The covered amount is the encounter's `exam_fee_cents`; the plan pays 80 percent of that covered amount — the product of the covered amount and a medical coinsurance rate of 0.80, rounded half up to whole cents — and this is the claim's `plan_paid_cents`. The patient's coinsurance share is the covered amount minus the plan-paid amount, and the patient's total `patient_responsibility_cents` is that coinsurance share plus the encounter's full `refraction_fee_cents`, which the patient bears entirely. The medical claim's `billed_amount_cents` is the covered exam amount plus the `refraction_fee_cents`. In both routes the rounding of the plan-paid figure is performed before the patient share is derived from it.

Adjudicating a routine claim also consumes the exam benefit: the eligibility's `exam_benefit_available` flag is set false and the `EXAM` pool is marked fully consumed by setting its `consumed_cents` to its `allotted_cents`, and the eligibility's `version` is incremented. Every adjudication recomputes the patient's `outstanding_patient_balance_cents` and increments the claim's `version`. The patient's outstanding balance is the sum of `patient_responsibility_cents` across that patient's claims whose `claim_status` is `ADJUDICATED` or `SETTLED_PARTIAL`, less the amounts already settled on them.

### 3.9. Settling, Denying, and Voiding Claims; the Submission Dimension

Once a claim is `ADJUDICATED`, a `Biller` applies patient payments toward it. A payment names an `amount_cents`, which must be greater than zero and must not exceed the remaining patient responsibility — that is, the `patient_responsibility_cents` minus the amount already in `settled_cents`; a payment that is zero or negative or that exceeds the remaining balance is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. A payment that is greater than zero but smaller than the full remaining responsibility advances the claim from `ADJUDICATED` to `SETTLED_PARTIAL` and increases `settled_cents` by the payment amount. A payment that exactly equals the full responsibility while nothing has yet been settled advances the claim directly from `ADJUDICATED` to `SETTLED`. A payment that exactly closes the remaining balance on a partially settled claim advances it from `SETTLED_PARTIAL` to `SETTLED`; in both closing cases `settled_cents` is set equal to `patient_responsibility_cents`. `SETTLED` is terminal. Every payment recomputes the patient's `outstanding_patient_balance_cents` and increments the claim's `version`.

A biller may instead deny a draft claim, advancing it from `DRAFT` to `DENIED`, optionally recording a `reason`; `DENIED` is terminal. A biller may also void an adjudicated claim that has taken no payment, advancing it from `ADJUDICATED` to `VOIDED`; voiding is permitted only when the claim is `ADJUDICATED` and its `settled_cents` is zero, and `VOIDED` is terminal. Voiding a routine claim reverses its exam-benefit consumption as a compensating step: the eligibility's `exam_benefit_available` flag is restored to true, the `EXAM` pool's `consumed_cents` is reset to zero, and the eligibility's `version` is incremented. Voiding any claim recomputes the patient's `outstanding_patient_balance_cents` so the voided claim no longer contributes, and increments the claim's `version`.

The claim's carrier-submission status evolves on a parallel track that does not change its financial `claim_status`. A biller submits a claim to the carrier, advancing its `submission_status` from `UNSUBMITTED` to `SUBMITTED`; submission is permitted only when the claim's `claim_status` is `ADJUDICATED`, `SETTLED_PARTIAL`, or `SETTLED` and its `submission_status` is still `UNSUBMITTED`. After submission, the biller records the carrier's acknowledgement by supplying an `outcome`, which moves the `submission_status` from `SUBMITTED` to `ACCEPTED` or from `SUBMITTED` to `REJECTED`; an acknowledgement is legal only while the `submission_status` is `SUBMITTED`. Each submission and acknowledgement increments the claim's `version`. Claims are retrievable individually and in lists offering reverse lookup by `encounter_id` and `eligibility_id` and filterable by `claim_status`.

### 3.10. The Patient Statement Total

A `FrontDesk` coordinator or a `Biller` may request a computed patient statement that summarizes what the patient currently owes, returning the patient's `patient_id`, a `statement_total_cents`, and a `line_count`. The statement considers only the patient's claims whose `claim_status` is `ADJUDICATED` or `SETTLED_PARTIAL`; claims that are `DRAFT`, `DENIED`, `VOIDED`, or `SETTLED` are excluded. The claims in scope are processed in order of their creation timestamp ascending. For each such claim, the outstanding amount is its `patient_responsibility_cents` minus its `settled_cents`, and that per-claim outstanding amount is rounded to whole dollars — that is, rounded half up to the nearest multiple of 100 cents — first, before any summation. The `statement_total_cents` is the sum of these individually rounded per-claim figures; the rounding is applied to each line and then the rounded lines are summed, never the reverse, and the `line_count` reports how many claims fell in scope.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that read a resource, or that drive a state transition or other modification on an existing resource, return a `200 OK` status code. The simulated-clock endpoint, an administrative test-driving capability that sets `current_utc` to a supplied `to_iso8601` instant, returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the simulated server clock | FrontDesk |
| POST | `/providers` | Register a Provider | FrontDesk |
| GET | `/providers/{providerId}` | Get a Provider | FrontDesk, Optometrist, Optician, Biller |
| GET | `/providers` | List Providers | FrontDesk, Optometrist, Optician, Biller |
| POST | `/patients` | Register a Patient | FrontDesk |
| GET | `/patients/{patientId}` | Get a Patient (with computed recall and balance) | FrontDesk, Optometrist, Optician, Biller |
| GET | `/patients` | List Patients | FrontDesk, Biller |
| GET | `/patients/{patientId}/statement` | Computed patient statement total | FrontDesk, Biller |
| POST | `/encounters` | Open a clinical Encounter | FrontDesk, Optometrist |
| GET | `/encounters/{encounterId}` | Get an Encounter | FrontDesk, Optometrist, Biller |
| GET | `/encounters` | List Encounters | FrontDesk, Optometrist, Biller |
| POST | `/encounters/{encounterId}/finalize` | Finalize a refracted Encounter | Optometrist |
| POST | `/encounters/{encounterId}/void` | Void an open Encounter | FrontDesk |
| POST | `/patients/{patientId}/prescriptions` | Issue a Prescription | Optometrist |
| GET | `/prescriptions/{prescriptionId}` | Get a Prescription | FrontDesk, Optometrist, Optician |
| GET | `/patients/{patientId}/prescriptions` | List a Patient's Prescriptions | FrontDesk, Optometrist, Optician |
| GET | `/prescriptions` | List/filter Prescriptions | FrontDesk, Optometrist, Optician |
| POST | `/prescriptions/{prescriptionId}/revoke` | Revoke an active Prescription | Optometrist |
| POST | `/eligibilities` | Open a benefit period | FrontDesk |
| GET | `/eligibilities/{eligibilityId}` | Get an Eligibility | FrontDesk, Optician, Biller |
| GET | `/eligibilities` | List Eligibilities | FrontDesk, Optician, Biller |
| GET | `/eligibilities/{eligibilityId}/benefit-pools` | List an Eligibility's BenefitPools | FrontDesk, Optician, Biller |
| GET | `/benefit-pools/{benefitPoolId}` | Get a BenefitPool | FrontDesk, Optician, Biller |
| GET | `/benefit-pools` | List BenefitPools | FrontDesk, Optician, Biller |
| POST | `/eligibilities/{eligibilityId}/terminate` | Terminate a benefit period | FrontDesk |
| POST | `/lab-orders` | Place a lab order | Optician |
| GET | `/lab-orders/{labOrderId}` | Get a LabOrder | FrontDesk, Optician, Biller |
| GET | `/lab-orders` | List LabOrders | FrontDesk, Optician, Biller |
| POST | `/lab-orders/{labOrderId}/send-to-lab` | Send a placed or remake-requested order to the lab | Optician |
| POST | `/lab-orders/{labOrderId}/dispense` | Dispense an in-lab order | Optician |
| POST | `/lab-orders/{labOrderId}/request-remake` | Request a remake within the warranty window | Optician |
| POST | `/lab-orders/{labOrderId}/cancel` | Cancel a placed or in-lab order | Optician |
| POST | `/claims` | Draft a claim for a finalized Encounter | Biller |
| GET | `/claims/{claimId}` | Get a Claim | FrontDesk, Biller |
| GET | `/claims` | List Claims | FrontDesk, Biller |
| POST | `/claims/{claimId}/adjudicate` | Adjudicate a draft Claim | Biller |
| POST | `/claims/{claimId}/payments` | Apply a patient payment | Biller |
| POST | `/claims/{claimId}/deny` | Deny a draft Claim | Biller |
| POST | `/claims/{claimId}/void` | Void an unpaid adjudicated Claim | Biller |
| POST | `/claims/{claimId}/submit` | Submit a Claim to the carrier | Biller |
| POST | `/claims/{claimId}/carrier-ack` | Record carrier acknowledgement | Biller |
| POST | `/recall-reminders` | Schedule a recall reminder | FrontDesk |
| GET | `/recall-reminders/{reminderId}` | Get a RecallReminder | FrontDesk |
| GET | `/recall-reminders` | List RecallReminders | FrontDesk |
| POST | `/recall-reminders/{reminderId}/send` | Mark a reminder sent | FrontDesk |
| POST | `/recall-reminders/{reminderId}/cancel` | Cancel a scheduled reminder | FrontDesk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WRONG_PROVIDER_ROLE` | 422 |
| `ERR_PRESCRIPTION_NOT_DISPENSABLE` | 409 |
| `ERR_REMAKE_WINDOW_CLOSED` | 409 |
| `ERR_CARRIER_MISMATCH` | 422 |
| `ERR_BENEFIT_PERIOD_CLOSED` | 409 |
| `ERR_MEDICAL_BILLING_INELIGIBLE` | 422 |
| `ERR_STALE_ELIGIBILITY_VERSION` | 412 |
| `ERR_BENEFIT_EXHAUSTED` | 409 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
