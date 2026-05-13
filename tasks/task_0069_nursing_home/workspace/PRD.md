# Nursing Home API — Product Requirements Document

## 1. Introduction

A nursing home is, at any given moment, an intersection of three otherwise independent rhythms: a resident's clinical condition, the inventory of physical beds, and the monthly cadence of fees and subsidies. Each rhythm has its own actors and its own paperwork — a Physician issues a prescription, an Admin admits an elder to a bed, a Finance officer closes a billing cycle — yet a mistake in one rhythm propagates into the others. A care-level reclassification can invalidate the active care plan; an unrecorded leave day can corrupt a month's care fee; a single drug interaction can become a chain of regulatory consequences. This document specifies the back-end API that holds these three rhythms together.

The system serves elders, their families, the clinical staff who care for them, the financial staff who bill for the care, and the external systems (hospital transfers, government subsidy programs, payment processors, and in-house messaging) whose events must be absorbed exactly once. Every clinical action that mutates a care plan, a prescription, a medication administration, or a care assessment must be auditable; every financial calculation must be reconstructible from inputs alone; and every operation that races against another must serialize to a defined winner and a defined loser-error.

The API is mounted under `/elders` for elder-scoped resources, with sibling top-level resource roots (`/rooms`, `/beds`, `/waitlist`, `/care-assessments`, `/care-plans`, `/prescriptions`, `/bills`, `/visit-reservations`, `/epidemic-config`, `/medication-errors`, `/audit-logs`) and an admin-only operational namespace (`/_events/external`, `/_clock/advance`, `/_sweep/run`).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, the caller's identifier, and `X-User-Role`, the caller's role. Requests missing either header — or carrying a malformed value — are rejected with `ERR_AUTH_MISSING` at HTTP 401. Requests that authenticate but whose role is not permitted for the targeted endpoint are rejected with `ERR_FORBIDDEN` at HTTP 403.

Eight roles exist: `Admin`, `Supervisor`, `Physician`, `Nurse`, `Caregiver`, `Family`, `Finance`, and `SystemSync`. Spelling and capitalization are significant — these strings are the only legal values of `X-User-Role`. None of the eight roles is backed by a persisted entity of its own; for every role in this list, `X-User-ID` is an opaque operator identifier not tied to any stored entity row. The server records the identifier on entities where transitions and writes capture it — for example as `assessor_id` and `approver_id` on a `CareAssessment`, as `prescriber_id` on a `Prescription`, as `nurse_id` and `witness_id` on a `MedicationAdministration`, as `caregiver_id` on a `CareTaskExecution`, and as `actor_id` and `actor_role` on an `AuditLog` row — but the server does not compare it against any row's `id`. The `Family` role is therefore not entity-backed in the database, even though Family access is logically scoped to its own elder; family-side scoping is enforced as a runtime filter against the elder referenced by the request path, not against any `id` field.

`Admin` runs facility operations: rooms, beds, admissions, transfers, leave and return, discharge, epidemic posture, and the test-only operational capabilities. `Supervisor` is the clinical approver — it approves, rejects, and returns care assessments, manages care plans across their lifecycle, and activates prescriptions on behalf of the pharmacy. `Physician` issues, suspends, resumes, and discontinues prescriptions. `Nurse` drafts and submits care assessments and records medication administrations. `Caregiver` records care-task executions. `Family` books and cancels visits, tops up the deposit, pays bills, and reads their own elder's data. `Finance` creates, finalizes, adjusts, and refunds bills, and may also accept payments and top up deposits. `SystemSync` is the service identity reserved exclusively for ingesting external-system events.

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

Every list endpoint accepts two optional query parameters: `limit` and `offset`. `limit` defaults to 10 when omitted, may not be lower than 1, and may not exceed 100; `offset` defaults to 0 and may not be lower than 0. Beyond the explicit per-endpoint ordering noted in §3 (the waitlist, for instance, is ordered by `priority_score` descending with `queued_at` ascending as the tie-break), list endpoints default to sorting by `created_at` ascending. The `meta` envelope of a list response carries the four fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true precisely when `offset + limit` is below `total_count`.

### 2.4. Resource Identity, Versioning, and Optimistic Concurrency

Every resource is identified by a server-minted `id` — a UUID without any type prefix. Most entities also carry three further system fields: `created_at` and `updated_at`, both ISO 8601 UTC strings with three fractional digits, and `version`, an integer that begins at 1 on creation and increments by one on every successful mutation. The entities that do not carry `updated_at` and `version` are `WaitlistEntry`, `CareTaskExecution`, `MedicationAdministration`, `MedicationErrorReport`, `AuditLog`, and `ExternalEvent`; these carry only `id` and `created_at`. Audit log rows additionally expose `occurred_at`, set from the server clock at the moment the audited action lands.

Optimistic concurrency control is offered on every endpoint that mutates a versioned resource. A client may include `version` in the request body to assert "I am editing the version I last read"; if the asserted `version` does not match the resource's current `version`, the write is rejected with `ERR_VERSION_CONFLICT` at HTTP 409. Omitting `version` from the request body skips the check entirely — the write applies to whatever the current version is. The mechanism applies uniformly to PATCH endpoints and to those POST action endpoints that mutate versioned state.

### 2.5. Nested Path Resolution and Resource Existence

Path parameters are resolved left-to-right. For a path such as `/elders/{id}/care-plans/{plan_id}/task-executions`, the elder is resolved before the plan, and the plan before any further parameter; the first missing resource encountered along the chain yields `ERR_NOT_FOUND` at HTTP 404. Foreign-key fields in a POST or PATCH body — `elder_id`, `room_id`, `based_on_assessment_id`, `bed_id`, `target_bed_id`, `new_plan_id`, `administration_id`, `prescription_id` — are validated separately; an unknown reference in the body yields `ERR_FK_NOT_FOUND`, also at HTTP 404. Generic schema- or type-level validation failures (missing required field, wrong JSON type, out-of-range enum value) yield `ERR_VALIDATION` at HTTP 422.

### 2.6. Monetary Precision and Cents-Based Arithmetic

All monetary fields are integers expressed in cents — `monthly_bed_fee_cents`, `deposit_balance_cents`, `outstanding_balance_cents`, `subtotal_cents`, `government_subsidy_cents`, `insurance_offset_cents`, `deposit_applied_cents`, `amount_due_cents`, `amount_cents`, `refund_amount_cents`, and `override_amount_due_cents`. There are no fractional cents in stored state and no floating-point currency on the wire.

The single non-integer currency value that arises during computation is the bed's pro-rated daily share — `monthly_bed_fee_cents` multiplied by the number of days in the cycle divided by 30 — and that share is itself rounded to a whole number of cents using **round half up** before it lands in any line item. The same round-half-up rule applies to the per-line A_LA_CARTE care fee once it has been derived from the hourly rate, the per-task minutes, and the per-hour conversion. The composite assessment score from `care_level_classification` is held to two decimal places, also rounded half up. Subsidies and insurance offsets, by contrast, are floored to integer cents — never rounded up. The pinned arithmetic order for a bill is: compute each line item to integer cents (applying round-half-up only where a non-integer intermediate exists), then sum to obtain `subtotal_cents`. Subsidy is computed from the resulting `subtotal_cents`; insurance is computed from medical line items after subsidy; deposit is applied last in a waterfall; `amount_due_cents` is what remains.

### 2.7. Validation Priority Order

When a single request would fail more than one validation, the rejection is the one with the lowest priority number on the list below. This ordering is normative: a request that would also have tripped a low-priority business check must still be rejected first by the higher-priority auth or existence check, because tests probe the exact returned `error_id`.

1. Authentication header presence — both `X-User-ID` and `X-User-Role` must be present and well-formed; otherwise `ERR_AUTH_MISSING`.
2. Role authorisation — the role must be permitted for the endpoint per §2.1 and §4; otherwise `ERR_FORBIDDEN`.
3. Path-resource existence — every resource named by a path parameter must exist, checked left-to-right; otherwise `ERR_NOT_FOUND`.
4. Body-resource existence — every foreign-key reference in the request body must exist; otherwise `ERR_FK_NOT_FOUND`.
5. State preconditions — the target resource must be in a state permitting the transition; otherwise `ERR_INVALID_STATE`.
6. Segregation-of-duties on `CareAssessment` approval, rejection, and return-for-revision — the supervisor's `X-User-ID` must differ from the draft's `assessor_id`; otherwise `ERR_SEGREGATION_OF_DUTIES`.
7. Segregation-of-duties on medication administration — the recording nurse's `X-User-ID` must differ from the prescription's `prescriber_id`; otherwise `ERR_SEGREGATION_OF_DUTIES`.
8. Controlled-substance witness — for a controlled-substance prescription, the administration's `witness_id` must be present and distinct from both the recording nurse and the prescriber; otherwise `ERR_WITNESS_REQUIRED`.
9. Drug interaction — at prescription activation, the new drug must not collide with any ACTIVE prescription's interaction list for the same elder, and its own interaction list must not contain any ACTIVE drug code; otherwise `ERR_DRUG_INTERACTION`.
10. Allergy contraindication — at prescription activation, the elder's `allergies` set must share no element with the prescription's `contraindicated_allergens` set; otherwise `ERR_ALLERGY_CONFLICT`.
11. Visit health screening — at check-in, the visitor's `temperature_c` must be strictly below `max_temperature_c`, `symptoms` must be empty, and — when the reservation's snapshotted epidemic mode is not `NORMAL` — `recent_exposure` must be false; otherwise `ERR_HEALTH_SCREENING_FAILED`.
12. Visit lockdown — at check-in, `EpidemicConfig.mode` must not be `LOCKDOWN`; otherwise `ERR_VISITATION_LOCKED`.
13. Bed-type / care-level match — admission or transfer onto an `INTENSIVE_CARE` bed requires the elder's `current_care_level` to be `INTENSIVE`, and conversely an `INTENSIVE` elder may only occupy an `INTENSIVE_CARE` bed; otherwise `ERR_BED_TYPE_MISMATCH`.
14. Single ACTIVE care plan — activating a care plan when another plan for the same elder is already in `ACTIVE` is rejected with `ERR_ACTIVE_PLAN_EXISTS`.
15. Visit slot overlap — a new RESERVED interval, treated as half-open from `slot_start_at` inclusive to `slot_end_at` exclusive, must not intersect any existing `RESERVED` or `CHECKED_IN` reservation for the same elder; otherwise `ERR_VISIT_SLOT_CONFLICT`.
16. Visit daily cap — the count of the elder's `RESERVED` plus `CHECKED_IN` reservations whose `slot_start_at` falls on the same calendar day must not exceed `EpidemicConfig.max_visitors_per_day`; otherwise `ERR_VISIT_DAILY_LIMIT`.
17. Visit slot duration — `slot_end_at` minus `slot_start_at` must lie within a closed interval bounded by 15 minutes below and 120 minutes above; otherwise `ERR_INVALID_SLOT_DURATION`.
18. Care-task recording window — a `CareTaskExecution` must be recorded within 4 hours either side of its `scheduled_for`; otherwise `ERR_TASK_RECORD_WINDOW`.
19. Medication slot scheduling — the `scheduled_slot_at` submitted to a medication administration must be a slot present in the prescription's generated dispensing schedule; otherwise `ERR_SLOT_NOT_SCHEDULED`.
20. Care-plan level match — at care-plan activation, the referenced assessment's `classification` must equal the elder's `current_care_level`; otherwise `ERR_PLAN_LEVEL_MISMATCH`.
21. Cycle coverage — at bill finalization, the elder's `ADMITTED` plus `ON_LEAVE` days within the cycle must equal the cycle's day count exactly, with no gaps; otherwise `ERR_CYCLE_COVERAGE_GAP`.
22. Refund ceiling — a refund's `refund_amount_cents` must not exceed the bill's original `deposit_applied_cents` plus the amount paid externally; otherwise `ERR_REFUND_OVER_LIMIT`.
23. Admission deposit floor — admission requires `Elder.deposit_balance_cents` to be at least 5,000.00, that is at least 500,000 cents; otherwise `ERR_DEPOSIT_INSUFFICIENT`.
24. Discharge fiscal clearance — discharge requires `Elder.outstanding_balance_cents` to be exactly zero and no `Bill` in `DRAFT` status; otherwise `ERR_OUTSTANDING_BALANCE`.
25. OCC `version` mismatch — covered in §2.4, yielding `ERR_VERSION_CONFLICT`.
26. External-event idempotency — duplicate ingestion under the same `(source, idempotency_key)` is reported as `ERR_DUPLICATE_EVENT`; the original processing result is replayed without re-applying side effects.

### 2.8. State-Transition Audit Trail

Every state transition on `CareAssessment`, `CarePlan`, `Prescription`, and every `MedicationAdministration` insertion produces exactly one `AuditLog` row. The row captures `actor_role` and `actor_id` from the request headers, `entity_type` and `entity_id` from the resource under change, an `action` verb naming the operation (for example `CREATE`, `ACTIVATE`, `APPROVE`, `REJECT`, `REVIEW_FLAGGED`, `REVIEW_CONFIRM`, `SUPERSEDE`, `DISCONTINUE`, `ADMINISTER`, `ERROR_REPORT`), the `previous_state` (or null if the entity has just been created), the `new_state` (or null where no status field is involved), and `occurred_at` set from the server clock. The four audited domains are exactly `CarePlan`, `Prescription`, `MedicationAdministration`, and `CareAssessment` — no others. List access to the audit trail is restricted to `Admin` and `Supervisor`.

### 2.9. Cascading Side Effects Across Aggregates

Several transitions in this system mutate more than one entity, and the secondary mutations are not optional: they are the contract the test suite probes for. When an elder moves from `ADMITTED` to `ON_LEAVE`, every `ACTIVE` prescription for that elder cascades to `SUSPENDED`, the bed is held in `OCCUPIED` rather than released, and any `DRAFT` bill in flight continues to accrue bed fee but ceases to accrue care or meal fee for the leave days. When the same elder returns from `ON_LEAVE` to `ADMITTED`, the `SUSPENDED` prescriptions cascade back to `ACTIVE`. When a `Supervisor` approves a `CareAssessment` whose `classification` differs from the elder's current `ACTIVE` care plan's `care_level_snapshot`, that care plan cascades from `ACTIVE` to `UNDER_REVIEW` in the same transaction; the elder's `current_care_level` is also updated to the new classification. When an elder is discharged, the bed transitions from `OCCUPIED` to `AVAILABLE`, any positive `deposit_balance_cents` is refunded via a system-issued payment event, every open `RESERVED` `VisitReservation` for that elder cascades to `CANCELLED`, and the bed release triggers waitlist promotion for any `QUEUED` entry matching the bed's type. Every mutation refreshes the affected resource's `updated_at` and bumps its `version` by one.

### 2.10. External-System Event Ingestion and Idempotency

The single endpoint reserved for `SystemSync` accepts events from four external systems identified by `source`: `PAYMENT`, `IM`, `HOSPITAL`, and `GOVT_SUBSIDY`. Each event carries an `idempotency_key` unique within its `source`, a free-form `event_type` string such as `PAYMENT_RECEIVED`, `ELDER_TRANSFERRED_TO_HOSPITAL`, or `SUBSIDY_GRANT`, and a `payload` object whose schema is source-specific. The first time a `(source, idempotency_key)` pair is processed, the corresponding domain mutation is applied — a payment lands on a `FINALIZED` bill, a hospital transfer drives the elder from `ADMITTED` to `ON_LEAVE`, a subsidy event credits a draft bill's subsidy line. The event's `applied_at` is recorded and `result_status` is set to `APPLIED`. The second submission with the same pair is recognised as a duplicate: `result_status` is set to `DUPLICATE`, the prior result is returned to the caller, no side effects are re-applied, and the response carries `ERR_DUPLICATE_EVENT`. Submissions that the system declines for domain reasons (for example a payment for a `DRAFT` bill) record `result_status: REJECTED` and surface the corresponding domain error.

### 2.11. Operational Capabilities: Clock Advance and Sweep

Two `Admin`-only capabilities exist to drive time-gated transitions in a test environment. A clock-advance capability accepts an integer number of `seconds` and advances the server's logical clock by exactly that amount; this is the mechanism by which the 24-hour waitlist offer timer, the 30-day archive timer, and the 90-day reassessment timer are exercised. A sweep capability runs the periodic background actions in a single synchronous call: outstanding `OFFERED` waitlist entries whose offer has been held for at least 24 hours return to `QUEUED` (with `offered_bed_id` cleared and the next eligible entry promoted), `ACTIVE` care plans whose `next_review_due_at` has passed move to `UNDER_REVIEW`, `SUPERSEDED` care plans that have been in that state for at least 30 days move to `ARCHIVED`, and outstanding `RESERVED` visit reservations move to `DENIED` if the current `EpidemicConfig.mode` is `LOCKDOWN`. Neither capability appears in normal operational traffic.

## 3. Business Logic & Workflows

### 3.1. Elder Onboarding, Admission, and the Waitlist

An elder enters the system as a profile carrying `full_name`, `date_of_birth`, `gender`, and `id_card_number`, along with the structured arrays `medical_history`, `allergies`, `dietary_requirements`, and `emergency_contacts`, and the `advance_directive` object whose default is the all-false directive `{dnr:false,dni:false,organ_donation:false,signed_at:null}`. `id_card_number` is required to be unique across all non-`DISCHARGED` elders — a new admission attempt for an elder whose `id_card_number` collides with a current resident is treated as a validation conflict. The newly created elder enters `PENDING_ADMISSION`. The mutable fields after creation are `emergency_contacts`, `dietary_requirements`, `advance_directive`, and `allergies`; the others are write-once until discharge.

Admission to a specific bed is gated by four preconditions and is the act that moves the elder from `PENDING_ADMISSION` to `ADMITTED`. At least one entry must be present in `emergency_contacts` — admission of an elder with an empty contact list is refused. At least one `CareAssessment` for the elder must already have been approved, because the bed-type check downstream depends on `current_care_level`. The bed referenced by the request's `bed_id` must currently be in `AVAILABLE`; two concurrent admit attempts on the same `AVAILABLE` bed serialize first-writer-wins on the `Bed.status` field, and the losing attempt is rejected with `ERR_BED_ALREADY_OCCUPIED`. And the elder's `deposit_balance_cents` must be at least 5,000.00 (500,000 cents) — the admission deposit floor, beneath which the request is rejected with `ERR_DEPOSIT_INSUFFICIENT`. When all four hold, the bed transitions from `AVAILABLE` to `OCCUPIED`, its `current_elder_id` is set to the elder, the elder's `current_bed_id` is set to the bed, an entry is appended to the elder's `admission_history` array, and — if the elder had previously been added to the waitlist and the bed had been offered to them — the matching `OFFERED` `WaitlistEntry` cascades to `FULFILLED`. The elder's `version` and the bed's `version` each increment by one.

Waitlist entries are created by `Admin` or `Family` with a `requested_bed_type` (`SINGLE`, `DOUBLE`, `MULTI`, or `INTENSIVE_CARE`) and the `elder_id` of an elder still in `PENDING_ADMISSION`. On insertion the system computes the entry's `priority_score`: the base score is taken from a per-level mapping where `L1` weighs 1, `L2` weighs 2, `L3` weighs 3, `L4` weighs 4, and `INTENSIVE` weighs 5; the base is multiplied by 100; an age bonus is added equal to the elder's age in completed years divided by 5 with the fractional part discarded — that is, one additional bonus point for every full five years of age. The priority is therefore an integer whose hundreds digit reflects acuity and whose tens-and-units encode age seniority. Two entries with the same `priority_score` are ordered by `queued_at`, with the earlier `queued_at` served first. The waitlist listing endpoint surfaces entries sorted by `priority_score` descending and `queued_at` ascending.

Promotion from `QUEUED` to `OFFERED` is triggered whenever a bed of matching `bed_type` enters `AVAILABLE` — that is, when a bed completes maintenance, when an occupant is discharged, or when a transfer releases a source bed. The highest-priority `QUEUED` entry whose `requested_bed_type` matches the now-available bed is selected; its `offered_bed_id` is recorded; the bed remains `AVAILABLE` while the entry holds a 24-hour soft claim. The entry transitions to `FULFILLED` when the corresponding admit succeeds; it returns to `QUEUED` either when the family declines (in which case `offered_bed_id` is cleared and the next eligible entry is re-promoted) or when the 24-hour timer elapses, observable only via the sweep capability. Cancelling a waitlist entry — by family request, by admin action, by discharge of the underlying elder, or by abandonment of a `PENDING_ADMISSION` elder — terminates the entry in `CANCELLED`.

### 3.2. Care Assessments and the Approval Cycle

A care assessment is a clinical document drafted by a `Nurse` for a specific elder. The Nurse records the three sub-scores — `adl_score` from 0 to 100 inclusive (higher denoting greater independence), `cognitive_score` from 0 to 30 inclusive, and `medical_condition_score` from 0 to 50 inclusive (higher denoting greater severity). On creation the assessment is in `DRAFT`; the drafting Nurse's identifier is captured in `assessor_id`.

Submission moves the assessment from `DRAFT` to `PENDING_APPROVAL` and triggers the composite score computation. The composite score is a weighted sum of three transformed components: the ADL deficit, defined as 100 minus `adl_score` and weighted by 0.5; the cognitive deficit, defined as 30 minus `cognitive_score` and weighted by 1.0; and the raw `medical_condition_score`, weighted by 1.0. The three weighted terms are summed and the result is rounded half up to two decimal places to obtain `composite_score`. The `classification` is then derived by threshold, with each threshold being an inclusive lower bound: a composite of at least 80 yields `INTENSIVE`; otherwise at least 60 yields `L4`; otherwise at least 40 yields `L3`; otherwise at least 20 yields `L2`; otherwise `L1`.

Approval is a `Supervisor` action and is governed by segregation of duties: the supervisor's `X-User-ID` must not equal the assessment's `assessor_id`. The same constraint applies to rejection and to return-for-revision; in all three operations a same-identity attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. On approval, the assessment moves from `PENDING_APPROVAL` to `APPROVED`, `approver_id` is recorded, `effective_from` is set to the current server time, `due_for_reassessment_at` is set to `effective_from` plus 90 days, and the elder's `current_care_level` is updated to the approved `classification`. If the elder has an `ACTIVE` `CarePlan` whose `care_level_snapshot` differs from the newly approved classification, that care plan is automatically advanced from `ACTIVE` to `UNDER_REVIEW` in the same transaction — the bridge between the assessment cycle and the plan-review cycle. Approval also writes an `AuditLog` row with `entity_type` of `CareAssessment` and `action` of `APPROVE`; rejection writes the parallel row with `action` of `REJECT`. Return-for-revision is the cyclic transition that loops the assessment back to `DRAFT` so the original drafting Nurse can amend the sub-scores and resubmit. The terminal state of the assessment is `REJECTED`. When two supervisors attempt to approve and reject the same `PENDING_APPROVAL` assessment simultaneously, the first writer on the `status` field wins; the loser sees `ERR_INVALID_STATE` because the assessment has already left `PENDING_APPROVAL`.

### 3.3. Care Plans, Reviews, and Supersession

A care plan begins as a `DRAFT` created by a `Supervisor`, referencing a `CareAssessment` whose `status` is `APPROVED` and whose id is supplied as `based_on_assessment_id`, and listing the elder's `daily_tasks`. Each entry in `daily_tasks` carries a `task_type` from the set `BATHING`, `FEEDING`, `TURNING`, `MEDICATION`, and `VITALS`, a `frequency_per_day` of one or more, and free-form `notes`. The plan's `status` begins as `DRAFT` and the `care_level_snapshot` is not yet bound.

Activation, performed by a `Supervisor`, drives the plan from `DRAFT` to `ACTIVE`. Activation refuses if any other care plan for the same elder is already in `ACTIVE` (rejected with `ERR_ACTIVE_PLAN_EXISTS`) and refuses if the referenced assessment's `classification` does not equal the elder's `current_care_level` (rejected with `ERR_PLAN_LEVEL_MISMATCH`). On activation, `care_level_snapshot` is frozen to the assessment's `classification` — once frozen, it does not change for the lifetime of the plan, even if the elder is later re-assessed. The `activated_at` timestamp is recorded. The `review_cycle_days` value is then derived from the snapshot using a per-level lookup: `L1` yields 90, `L2` yields 60, `L3` yields 45, `L4` yields 30, and `INTENSIVE` yields 14. The `next_review_due_at` is set to `activated_at` plus `review_cycle_days`. An audit row records the activation.

A plan in `ACTIVE` can move to `UNDER_REVIEW` along three paths. A Supervisor can flag a review manually. The Supervisor approval of a new assessment whose classification differs from `care_level_snapshot` cascades the plan into review. And the sweep capability flags any plan whose `next_review_due_at` has passed. From `UNDER_REVIEW`, two onward routes exist: confirming the review without changes restarts the cycle by setting `next_review_due_at` to the current time plus `review_cycle_days`; superseding the plan provides a `new_plan_id`, which must refer to a `DRAFT` plan for the same elder. On supersession the new plan cascades from `DRAFT` to `ACTIVE` in the same transaction and the old plan moves from `UNDER_REVIEW` to `SUPERSEDED`. Each of these transitions writes its own `AuditLog` row (with actions `REVIEW_FLAGGED`, `REVIEW_CONFIRM`, and `SUPERSEDE` respectively, and `ACTIVATE` for the new plan). A `SUPERSEDED` plan that has been in that state for at least 30 days is archived by the sweep capability and becomes read-only.

Care tasks are recorded by a `Caregiver` against an `ACTIVE` care plan. A `CareTaskExecution` carries `care_plan_id`, `task_type`, `scheduled_for`, the caregiver's `X-User-ID` captured as `caregiver_id`, an `outcome` from the set `COMPLETED`, `REFUSED`, and `OMITTED`, and `notes`. Notes are required whenever `outcome` is not `COMPLETED`. The recording must occur within plus-or-minus 4 hours of `scheduled_for`; an attempt to log a task outside that window is rejected with `ERR_TASK_RECORD_WINDOW`. The system stamps `executed_at` from the server clock at the moment the execution is recorded.

### 3.4. Prescriptions: Issuing, Activation, Suspension, and Discontinuation

A `Physician` creates a prescription for an `ADMITTED` elder with `drug_code`, `drug_name`, `is_controlled_substance`, `contraindicated_allergens`, `interacts_with_drug_codes`, `dose_mg`, `frequency_per_day`, `starts_on` (an ISO date), and `ends_on` (an ISO date inclusive, required to be on or after `starts_on`). The prescriber's identifier is captured as `prescriber_id`. The prescription enters `PENDING_REVIEW`.

Activation is performed by a `Supervisor` (acting in the pharmacy role) and runs two safety gates that are evaluated together at activation time. The drug-interaction gate considers every other prescription on the same elder that is currently in `ACTIVE` and checks symmetrically: this prescription's `drug_code` must not appear in any `ACTIVE` prescription's `interacts_with_drug_codes`, and this prescription's `interacts_with_drug_codes` must contain no `drug_code` of any `ACTIVE` prescription on the elder. A collision in either direction is rejected with `ERR_DRUG_INTERACTION`. The allergy gate requires that the intersection of the elder's `allergies` set and the prescription's `contraindicated_allergens` set be empty; any non-empty intersection is rejected with `ERR_ALLERGY_CONFLICT`. On successful activation, the system generates the dispensing schedule by producing `frequency_per_day` slots per calendar day across the inclusive date range from `starts_on` to `ends_on`. The activation writes an `AuditLog` row.

A prescription in `ACTIVE` can move to `SUSPENDED` either through a Physician's direct suspend action or as the cascade triggered by the elder moving to `ON_LEAVE`. A `SUSPENDED` prescription returns to `ACTIVE` either through a Physician's resume action or as the cascade triggered by the elder returning from leave; the resumption requires the elder's status to be `ADMITTED`. Future scheduled medication slots are blocked while a prescription is `SUSPENDED`. A prescription can be discontinued from either `PENDING_REVIEW` or `ACTIVE`, terminating in `DISCONTINUED`. Discharge of the elder requires every active prescription to be `DISCONTINUED` first; the discontinue from `ACTIVE` writes an audit row with action `DISCONTINUE`, while the discontinue from `PENDING_REVIEW` does not.

### 3.5. Medication Administration and Error Reporting

A `Nurse` records each administration against a prescription that is currently in `ACTIVE`. The `MedicationAdministration` carries `prescription_id`, `scheduled_slot_at`, the recording nurse's identifier captured as `nurse_id`, the `outcome` from the set `ADMINISTERED`, `REFUSED`, `OMITTED`, and `ERROR`, and — for controlled substances — a `witness_id`. The system stamps `administered_at` from the server clock.

Three layered safety constraints apply, evaluated in the priority order set out in §2.7. First, the recording Nurse's identifier must not equal the prescription's `prescriber_id` — the same staff member cannot both prescribe and administer; a violation yields `ERR_SEGREGATION_OF_DUTIES`. Second, when the prescription's `is_controlled_substance` is true, `witness_id` must be supplied, must denote a different person from the recording Nurse, and must also differ from the `prescriber_id`; an absent or non-distinct witness yields `ERR_WITNESS_REQUIRED`. Third, `scheduled_slot_at` must be a slot present in the prescription's generated dispensing schedule; an arbitrary timestamp is rejected with `ERR_SLOT_NOT_SCHEDULED`. Two administrations submitted concurrently for the same `(prescription_id, scheduled_slot_at)` serialize first-writer-wins on the slot's uniqueness, and the loser receives `ERR_SLOT_ALREADY_ADMINISTERED`.

Recording an administration with `outcome` of `ERROR` automatically creates a `MedicationErrorReport` row, linking it through `administration_id`, `prescription_id`, and `elder_id`, and storing that row's id back on the administration as `error_report_id`. The error report carries the categorical `error_type` from the set `WRONG_DRUG`, `WRONG_DOSE`, `WRONG_TIME`, `INTERACTION`, and `OTHER`, a `severity` from the set `MINOR`, `MODERATE`, and `SEVERE`, and a free-text `description`. The administration itself writes an `AuditLog` row whose `entity_type` is `MedicationAdministration`. Error reports may also be filed independently by a `Nurse` or `Supervisor` against an elder without an originating administration; the optional fields `administration_id` and `prescription_id` may be omitted in that path, but `elder_id`, `error_type`, `severity`, and `description` remain required.

### 3.6. Family Visits, Health Screening, and Epidemic Posture

The `EpidemicConfig` object is a single system-wide record maintained by `Admin`. Its `mode` is one of `NORMAL`, `RESTRICTED`, or `LOCKDOWN` (defaulting to `NORMAL`), and it carries two screening parameters: `max_temperature_c`, which is the inclusive temperature threshold at which a visitor is denied entry (default 37.3 degrees), and `max_visitors_per_day`, the per-elder cap on `RESERVED` plus `CHECKED_IN` reservations whose `slot_start_at` falls within a single calendar day (default 2).

A `Family` member, or an `Admin` on their behalf, creates a `VisitReservation` for an `ADMITTED` elder. The reservation captures `visitor_name`, `visitor_id_number`, `visitor_relation` from the set `SPOUSE`, `CHILD`, `SIBLING`, `OTHER_FAMILY`, `FRIEND`, and `OTHER`, and the time bounds `slot_start_at` and `slot_end_at`. Three booking-time constraints apply: the slot's duration must be at least 15 minutes and at most 120 minutes (rejection: `ERR_INVALID_SLOT_DURATION`); the half-open interval from `slot_start_at` inclusive to `slot_end_at` exclusive must not intersect any existing `RESERVED` or `CHECKED_IN` reservation for the same elder (rejection: `ERR_VISIT_SLOT_CONFLICT`, which is also the resolution for two simultaneous booking requests on overlapping intervals — first-writer-wins on the slot record, the loser sees this same code); and the elder's `RESERVED` plus `CHECKED_IN` count for the calendar day of `slot_start_at` must not exceed `max_visitors_per_day` (rejection: `ERR_VISIT_DAILY_LIMIT`). On insertion, the system snapshots `EpidemicConfig.mode` into the reservation's `epidemic_mode_at_reservation`, because the screening rule consulted at check-in depends on the mode that was in force at the time of booking, not at the time of check-in. The reservation enters `RESERVED` and exposes `health_screening` as a placeholder. A reservation in `RESERVED` may be cancelled — by family, by admin, by the discharge cascade, or by the sweep capability turning unhealthy reservations into `DENIED` — at any time before `slot_start_at`.

Check-in is performed by an `Admin` at the doorway. The request carries the visitor's submitted `visitor_id_number` and a `health_screening` object containing `temperature_c`, `symptoms` (an array of strings), and `recent_exposure` (a boolean). Check-in is allowed only within a window beginning 15 minutes before `slot_start_at` and ending at `slot_end_at`. The submitted `visitor_id_number` must match the reservation's stored `visitor_id_number`. The elder must still be `ADMITTED`. If the live `EpidemicConfig.mode` is `LOCKDOWN`, check-in is rejected with `ERR_VISITATION_LOCKED` and the reservation moves from `RESERVED` to `DENIED`. Otherwise the screening proceeds: `temperature_c` must be strictly less than `max_temperature_c`; `symptoms` must be empty; and — only when the reservation's snapshotted `epidemic_mode_at_reservation` is something other than `NORMAL` — `recent_exposure` must be false. A failure of any of these screening clauses moves the reservation from `RESERVED` to `DENIED` and yields `ERR_HEALTH_SCREENING_FAILED`. On a clean screening the reservation moves from `RESERVED` to `CHECKED_IN`; `check_in_at` is stamped. Check-out by the `Admin` moves the reservation from `CHECKED_IN` to `COMPLETED` and stamps `check_out_at`. Reservations terminate in `COMPLETED`, `CANCELLED`, or `DENIED`.

### 3.7. Billing: Drafting, Finalization, Subsidy, Insurance, Deposit, and Refund

Billing runs in monthly cycles. A `Finance` officer creates a `Bill` for an elder with `cycle_start_date` and `cycle_end_date` (both ISO date strings; both inclusive; both required to fall within the same calendar month) and `billing_mode`, which is one of `PACKAGE` or `A_LA_CARTE`. The bill enters `DRAFT`. The number of days in the cycle is the difference between `cycle_end_date` and `cycle_start_date` plus one, inclusive of both bounds. The `admitted_days` figure is the count of cycle days on which the elder was in `ADMITTED`; the remaining cycle days, on which the elder was in `ON_LEAVE`, are accounted separately. Finalization is refused if `admitted_days` plus on-leave days does not exactly equal the number of days in the cycle — that is, if there is any gap in coverage — and the rejection is `ERR_CYCLE_COVERAGE_GAP`.

Finalization, performed by `Finance`, drives the bill from `DRAFT` to `FINALIZED` and runs the full computation chain whose order is pinned. The first stage builds `line_items`. Every line is denominated in integer `amount_cents`. The bed-fee line, in category `BED`, is the bed's `monthly_bed_fee_cents` multiplied by the days-in-cycle divided by 30, with the result rounded half up to a whole number of cents — and it accrues across every day in the cycle including leave days, because the bed is held. The care-fee and meal-fee lines depend on `billing_mode`. In `PACKAGE` mode, the `care_level_snapshot` (frozen at the elder's `current_care_level` as of `cycle_start_date`) drives a per-level daily care rate — 5,000 cents per day for `L1`, 8,000 for `L2`, 12,000 for `L3`, 18,000 for `L4`, and 30,000 for `INTENSIVE` — multiplied by `admitted_days` to yield the `CARE` line in integer cents; the `MEAL` line is 4,000 cents per day multiplied by `admitted_days`. In `A_LA_CARTE` mode, the same `care_level_snapshot` drives a per-level hourly care rate — 3,000 cents per hour for `L1`, 4,500 for `L2`, 6,500 for `L3`, 9,000 for `L4`, and 15,000 for `INTENSIVE` — multiplied by the sum of `minutes_per_task` across the cycle's `CareTaskExecution` rows and divided by 60 to yield the raw care-fee, which is rounded half up to integer cents before it lands in the `CARE` line; the `MEAL` line is 1,500 cents per recorded meal multiplied by `actual_meal_count`. Medical line items are itemised in either mode, each appearing as a separate line in category `MEDICAL`. `subtotal_cents` is the sum of every line's `amount_cents`. Same elder, same cycle, same underlying activity can produce a different `subtotal_cents` in `PACKAGE` versus `A_LA_CARTE` — that is the intended distinction between the two modes.

The second stage is the government subsidy. The subsidy rate is a per-level lookup applied against `subtotal_cents`: 10% for `L1`, 15% for `L2`, 20% for `L3`, 30% for `L4`, and 40% for `INTENSIVE`. The raw subsidy is `subtotal_cents` multiplied by the rate and then floored to integer cents — never rounded up. The final `government_subsidy_cents` is the smaller of the raw figure and the monthly cap of 2,000.00 (200,000 cents). The third stage is the insurance offset, applied only to medical line items: the total of every line whose category is `MEDICAL` is multiplied by 70%, floored to integer cents, and then further capped so that subsidy plus insurance never exceeds `subtotal_cents` (the floor at zero is implicit because medical totals are non-negative). The fourth stage is the deposit waterfall: the remaining amount, computed as `subtotal_cents` minus `government_subsidy_cents` minus `insurance_offset_cents` and never permitted to be below zero, is offered to the elder's `deposit_balance_cents`; `deposit_applied_cents` is the smaller of the remainder and the current `deposit_balance_cents`. The deposit balance is decremented by `deposit_applied_cents` — the invariant is that `deposit_balance_cents` is never allowed to fall below zero. The final `amount_due_cents` is the remainder less `deposit_applied_cents`. A zero `amount_due_cents` results in the bill auto-advancing to `PAID` at the moment of finalization; a positive `amount_due_cents` holds the bill in `FINALIZED` awaiting payment. `finalized_at` is stamped. The elder's `outstanding_balance_cents` is then reconciled to the sum of `amount_due_cents` across every bill for that elder whose `status` is `FINALIZED` or `ADJUSTED` (bills in `PAID`, `REFUNDED`, or `DRAFT` are excluded from the sum). The sweep capability can be run on a bill whose `cycle_end_date` has passed; this provides a preview computation of `amount_due_cents` but does not advance the status from `DRAFT` — finalization remains a manual action.

Payment lands a bill in `PAID`. The `Family` member, or `Finance`, supplies an `external_payment_ref` which serves as the idempotency key; the same key can also arrive via an external `PAYMENT` event from the payment processor. Two pay requests for the same bill with the same `external_payment_ref` resolve such that the first applies the `FINALIZED` → `PAID` transition and the second returns the first result without re-applying side effects. The same `external_payment_ref` posted to a different bill is rejected with `ERR_DUPLICATE_PAYMENT`. A pay request against a bill that is not in `FINALIZED` is rejected with `ERR_BILL_NOT_FINALIZED` — this is the resolution of the race between a manual finalize and an incoming external `PAYMENT` event: pay requires `FINALIZED`, so a payment that arrives before the bill is finalized is refused. On a successful payment, `paid_at` is stamped and `outstanding_balance_cents` is recomputed.

Adjustment is a `Finance` action against a `FINALIZED` bill. It requires an `adjustment_reason` and accepts an `override_amount_due_cents` which replaces the computed `amount_due_cents`. The bill moves to `ADJUSTED` and the elder's `outstanding_balance_cents` is reconciled. Refund is a `Finance` action against a `PAID` bill: it carries `refund_amount_cents` and a `reason`. The refund amount must not exceed the bill's original `deposit_applied_cents` plus the amount actually paid externally; an excess is rejected with `ERR_REFUND_OVER_LIMIT`. On refund, the elder's `deposit_balance_cents` is incremented by the smaller of `refund_amount_cents` and the bill's original `deposit_applied_cents` (so that the deposit is never inflated beyond what was originally drawn), the bill moves to `REFUNDED`, and `outstanding_balance_cents` is reconciled. The `Elder` discharge transition reads `outstanding_balance_cents` exactly and refuses while it is non-zero or while any `DRAFT` bill remains, with the rejection `ERR_OUTSTANDING_BALANCE`.

Top-ups to the deposit are routed through a dedicated capability available to `Finance` and `Family`. The request carries an `amount_cents` to credit and an optional `external_payment_ref`. The elder's `deposit_balance_cents` is incremented by `amount_cents`.

### 3.8. Bed Inventory, Transfers, and Discharge

A `Room` is created by `Admin` with `room_number` (unique across the facility), `floor` (an integer of one or greater), and `room_type` from the set `STANDARD` and `INTENSIVE_CARE`. Beds within a room are created with `bed_code` (unique within `room_id`), `bed_type` from the set `SINGLE`, `DOUBLE`, `MULTI`, and `INTENSIVE_CARE`, and `monthly_bed_fee_cents`. A bed's `status` begins as `AVAILABLE` and is mutated through admission, discharge, transfer, and maintenance.

Maintenance is initiated by `Admin`: the bed moves from `AVAILABLE` to `MAINTENANCE`. Restoring the bed moves it from `MAINTENANCE` back to `AVAILABLE` and triggers waitlist promotion for any `QUEUED` entry with a matching `requested_bed_type`. The bed-type / care-level rule is consulted at every admit and at every transfer: an `INTENSIVE_CARE` bed accepts only an elder whose `current_care_level` is `INTENSIVE`, and conversely a non-`INTENSIVE_CARE` bed never accepts an `INTENSIVE` elder; the rejection is `ERR_BED_TYPE_MISMATCH`.

Transfer is an atomic operation initiated by `Admin` with `target_bed_id`. The source is the elder's `current_bed_id`; the target must be in `AVAILABLE`. The transfer releases the source bed (which moves from `OCCUPIED` to `AVAILABLE` and triggers waitlist promotion for that bed's type) and assigns the target (which moves from `AVAILABLE` to `OCCUPIED` with its `current_elder_id` set to the elder, and the elder's `current_bed_id` updated to the new bed). The bed-type / care-level rule is checked on the target. Two transfers attempting to move different elders into the same target bed simultaneously serialize first-writer-wins on the target's `Bed.status` field; the loser receives `ERR_BED_ALREADY_OCCUPIED`. An entry is appended to the elder's `admission_history`.

Leaving the facility temporarily is initiated by `Admin` (for example, on hospital transfer) or by an external `HOSPITAL` event carrying `ELDER_TRANSFERRED_TO_HOSPITAL` for the `ON_LEAVE` cascade; an optional `reason` may accompany the request. The elder moves from `ADMITTED` to `ON_LEAVE`. The bed remains `OCCUPIED` (held for return); every `ACTIVE` prescription cascades to `SUSPENDED`. Returning is an `Admin` action that requires the elder's status to be `ON_LEAVE` and the bed to still be `OCCUPIED`; on success the elder moves back to `ADMITTED` and the `SUSPENDED` prescriptions cascade back to `ACTIVE`.

Discharge — performed by `Admin` from either `ADMITTED` or `ON_LEAVE` — is the terminal transition. It requires the discharge fiscal clearance: `outstanding_balance_cents` exactly zero, no `Bill` left in `DRAFT`, and every bill closed in `PAID`, `REFUNDED`, or `ADJUSTED`. It also requires every active prescription on the elder to have already moved to `DISCONTINUED`. On success the bed moves from `OCCUPIED` to `AVAILABLE` and triggers waitlist promotion, the elder's `current_bed_id` is cleared, an entry is appended to `admission_history` with `discharged_at` stamped, any remaining positive `deposit_balance_cents` is refunded via an outbound payment event (the deposit-refund invariant), and every `RESERVED` `VisitReservation` for the elder cascades to `CANCELLED`. The elder's terminal state is `DISCHARGED`.

### 3.9. External-System Event Synchronization

The four supported event sources are `PAYMENT`, `IM`, `HOSPITAL`, and `GOVT_SUBSIDY`. A `PAYMENT_RECEIVED` event whose payload references a `FINALIZED` bill resolves exactly like an internal pay request: the bill moves to `PAID` and `outstanding_balance_cents` is reconciled. An `ELDER_TRANSFERRED_TO_HOSPITAL` `HOSPITAL` event drives the elder from `ADMITTED` to `ON_LEAVE`, triggering the standard prescription-suspension cascade. A `SUBSIDY_GRANT` `GOVT_SUBSIDY` event credits the subsidy line of a draft or finalized bill. Every event ingestion produces an `ExternalEvent` row whose `applied_at` is the server-clock instant of processing and whose `result_status` reflects the outcome (`APPLIED`, `DUPLICATE`, or `REJECTED`). The bill-finalize-versus-payment race resolves as in §3.7: the payment requires `FINALIZED` and is otherwise rejected with `ERR_BILL_NOT_FINALIZED`. Duplicate submissions on the same `(source, idempotency_key)` carry the canonical `ERR_DUPLICATE_EVENT` and replay the first stored result.

## 4. Endpoint Definitions

The endpoint table below lists every operation exposed by the API. New-resource creations return HTTP 201 with the new resource in the `data` envelope; modifications and action transitions return HTTP 200 with the updated resource; DELETEs that succeed return HTTP 204 with `data` as the empty object. Authorisation reflects the role columns; the precise side-effects and request/response payloads are governed by the narratives in §3.

| Method | Path                                                  | Description                                                          | Authorized Role(s)                                              |
|--------|-------------------------------------------------------|----------------------------------------------------------------------|-----------------------------------------------------------------|
| POST   | /elders                                               | Create an elder profile (PENDING_ADMISSION)                          | Admin                                                           |
| GET    | /elders                                               | List elders with filtering by status, current_care_level             | Admin, Supervisor, Nurse, Caregiver, Finance, Physician         |
| GET    | /elders/{id}                                          | Get elder by id                                                      | Admin, Supervisor, Nurse, Caregiver, Finance, Physician, Family |
| PATCH  | /elders/{id}                                          | Update mutable fields (contacts, dietary, advance_directive, allergies) | Admin                                                        |
| POST   | /elders/{id}/deposit                                  | Top up deposit_balance_cents                                          | Finance, Family                                                 |
| POST   | /elders/{id}/admit                                    | Admit elder to a specific bed                                         | Admin                                                           |
| POST   | /elders/{id}/leave                                    | Mark elder ON_LEAVE (e.g. hospital transfer)                          | Admin                                                           |
| POST   | /elders/{id}/return                                   | Return elder from leave                                               | Admin                                                           |
| POST   | /elders/{id}/transfer                                 | Atomic bed transfer (release source, occupy target)                   | Admin                                                           |
| POST   | /elders/{id}/discharge                                | Discharge elder                                                       | Admin                                                           |
| POST   | /rooms                                                | Create a room                                                         | Admin                                                           |
| GET    | /rooms                                                | List rooms                                                            | Admin, Supervisor                                               |
| POST   | /rooms/{id}/beds                                      | Create a bed within a room                                            | Admin                                                           |
| GET    | /beds                                                 | List beds with filters on status / bed_type                           | Admin, Supervisor                                               |
| POST   | /beds/{id}/maintenance                                | Mark bed MAINTENANCE                                                  | Admin                                                           |
| POST   | /beds/{id}/maintenance-complete                       | Restore bed to AVAILABLE                                              | Admin                                                           |
| POST   | /waitlist                                             | Add an elder to the waitlist                                          | Admin, Family                                                   |
| GET    | /waitlist                                             | List waitlist entries (sorted by priority_score desc, queued_at asc)  | Admin                                                           |
| POST   | /waitlist/{id}/decline                                | Decline an offered bed; entry returns to QUEUED                       | Family, Admin                                                   |
| DELETE | /waitlist/{id}                                        | Cancel a waitlist entry                                               | Family, Admin                                                   |
| POST   | /elders/{id}/care-assessments                         | Create draft assessment                                               | Nurse                                                           |
| POST   | /care-assessments/{id}/submit                         | Submit DRAFT for approval                                             | Nurse                                                           |
| POST   | /care-assessments/{id}/approve                        | Approve assessment                                                    | Supervisor                                                      |
| POST   | /care-assessments/{id}/reject                         | Reject assessment                                                     | Supervisor                                                      |
| POST   | /care-assessments/{id}/return-for-revision            | Return to DRAFT for revision                                          | Supervisor                                                      |
| GET    | /elders/{id}/care-assessments                         | List elder's assessments                                              | Admin, Supervisor, Nurse                                        |
| POST   | /elders/{id}/care-plans                               | Create draft care plan                                                | Supervisor                                                      |
| POST   | /care-plans/{id}/activate                             | Activate the plan                                                     | Supervisor                                                      |
| POST   | /care-plans/{id}/flag-review                          | Move ACTIVE → UNDER_REVIEW manually                                   | Supervisor                                                      |
| POST   | /care-plans/{id}/confirm-review                       | Confirm UNDER_REVIEW; restarts review cycle                           | Supervisor                                                      |
| POST   | /care-plans/{id}/supersede                            | Replace current ACTIVE plan with a new DRAFT plan                     | Supervisor                                                      |
| POST   | /care-plans/{id}/task-executions                      | Record a care task execution                                          | Caregiver                                                       |
| GET    | /care-plans/{id}                                      | Get plan                                                              | Admin, Supervisor, Nurse, Caregiver                             |
| GET    | /care-plans/{id}/task-executions                      | List task executions for a plan                                       | Admin, Supervisor, Nurse, Caregiver                             |
| POST   | /elders/{id}/prescriptions                            | Create prescription (PENDING_REVIEW)                                  | Physician                                                       |
| POST   | /prescriptions/{id}/activate                          | Activate prescription                                                 | Supervisor                                                      |
| POST   | /prescriptions/{id}/suspend                           | Suspend an ACTIVE prescription                                        | Physician                                                       |
| POST   | /prescriptions/{id}/resume                            | Resume a SUSPENDED prescription                                       | Physician                                                       |
| POST   | /prescriptions/{id}/discontinue                       | Discontinue prescription (terminal)                                   | Physician                                                       |
| POST   | /prescriptions/{id}/administrations                   | Record a MedicationAdministration                                     | Nurse                                                           |
| POST   | /medication-errors                                    | File a freestanding error report                                      | Nurse, Supervisor                                               |
| GET    | /prescriptions/{id}                                   | Get a prescription                                                    | Admin, Supervisor, Physician, Nurse                             |
| GET    | /prescriptions/{id}/administrations                   | List administrations for a prescription                               | Admin, Supervisor, Physician, Nurse                             |
| POST   | /elders/{id}/visit-reservations                       | Create a visit reservation                                            | Family, Admin                                                   |
| POST   | /visit-reservations/{id}/check-in                     | Check visitor in                                                      | Admin                                                           |
| POST   | /visit-reservations/{id}/check-out                    | Check visitor out                                                     | Admin                                                           |
| DELETE | /visit-reservations/{id}                              | Cancel a RESERVED reservation                                         | Family, Admin                                                   |
| GET    | /elders/{id}/visit-reservations                       | List reservations for elder                                           | Admin, Family                                                   |
| PUT    | /epidemic-config                                      | Set epidemic posture and screening parameters                         | Admin                                                           |
| GET    | /epidemic-config                                      | Get current epidemic posture                                          | Admin, Family, Supervisor                                       |
| POST   | /elders/{id}/bills                                    | Create a draft bill                                                   | Finance                                                         |
| POST   | /bills/{id}/finalize                                  | Finalize bill                                                         | Finance                                                         |
| POST   | /bills/{id}/pay                                       | Pay a FINALIZED bill                                                  | Family, Finance                                                 |
| POST   | /bills/{id}/adjust                                    | Adjust a FINALIZED bill                                               | Finance                                                         |
| POST   | /bills/{id}/refund                                    | Refund a PAID bill                                                    | Finance                                                         |
| GET    | /elders/{id}/bills                                    | List bills for elder                                                  | Finance, Family, Admin                                          |
| GET    | /bills/{id}                                           | Get bill                                                              | Finance, Family, Admin                                          |
| GET    | /audit-logs                                           | List audit logs                                                       | Admin, Supervisor                                               |
| POST   | /_events/external                                     | Ingest an external-system event                                       | SystemSync                                                      |
| POST   | /_clock/advance                                       | Advance the logical clock by `seconds`                                | Admin                                                           |
| POST   | /_sweep/run                                           | Run periodic sweep                                                    | Admin                                                           |

## 5. Error Code Catalogue

| Error ID                       | HTTP Status |
|--------------------------------|-------------|
| ERR_AUTH_MISSING               | 401         |
| ERR_FORBIDDEN                  | 403         |
| ERR_NOT_FOUND                  | 404         |
| ERR_FK_NOT_FOUND               | 404         |
| ERR_INVALID_STATE              | 409         |
| ERR_VERSION_CONFLICT           | 409         |
| ERR_VALIDATION                 | 422         |
| ERR_SEGREGATION_OF_DUTIES      | 403         |
| ERR_WITNESS_REQUIRED           | 422         |
| ERR_DRUG_INTERACTION           | 409         |
| ERR_ALLERGY_CONFLICT           | 409         |
| ERR_HEALTH_SCREENING_FAILED    | 422         |
| ERR_VISITATION_LOCKED          | 403         |
| ERR_BED_TYPE_MISMATCH          | 409         |
| ERR_BED_ALREADY_OCCUPIED       | 409         |
| ERR_ACTIVE_PLAN_EXISTS         | 409         |
| ERR_PLAN_LEVEL_MISMATCH        | 409         |
| ERR_VISIT_SLOT_CONFLICT        | 409         |
| ERR_VISIT_DAILY_LIMIT          | 409         |
| ERR_INVALID_SLOT_DURATION      | 422         |
| ERR_TASK_RECORD_WINDOW         | 422         |
| ERR_SLOT_NOT_SCHEDULED         | 422         |
| ERR_SLOT_ALREADY_ADMINISTERED  | 409         |
| ERR_CYCLE_COVERAGE_GAP         | 422         |
| ERR_REFUND_OVER_LIMIT          | 422         |
| ERR_DEPOSIT_INSUFFICIENT       | 422         |
| ERR_OUTSTANDING_BALANCE        | 409         |
| ERR_BILL_NOT_FINALIZED         | 409         |
| ERR_DUPLICATE_PAYMENT          | 409         |
| ERR_DUPLICATE_EVENT            | 409         |
