# Community Paramedicine / Mobile Integrated Health API — Product Requirements Document

## 1. Introduction

Community Paramedicine and Mobile Integrated Health (MIH) programs extend acute-care capacity into the home. Instead of waiting for a high-utilizer patient to return to the emergency department, an MIH team screens the patient, enrolls them in a payer-sponsored pilot, builds a clinical care plan, and delivers a mix of in-person home visits and telehealth encounters. The financial promise of these programs is measurable: fewer avoidable emergency-department (ED) visits and inpatient readmissions, funded by a per-encounter reimbursement model that rewards ED-diversion and penalizes readmissions.

This API is the system of record for that entire arc. It governs referral intake and risk stratification, enrollment against capped pilot programs, care-plan authoring with clinical co-signature controls, field encounter scheduling and vitals capture, medication reconciliation, social-needs coordination, acute-care event tracking, and payer-pilot billing with real-time budget reconciliation. Because dollars and clinical safety are both at stake, the system enforces strict fiscal ledgers, segregation-of-duties on high-risk plans, optimistic concurrency on care-plan creation, and a set of cascading state transitions that keep enrollments, plans, and visits mutually consistent.

The requirements below are written for the engineers who will build the service. They describe the domain first and the mechanics second. Section 2 fixes the system-wide contracts every endpoint shares; Section 3 walks the business workflows where the detailed rules live; Sections 4 and 5 summarize the endpoint surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. If either header is missing or its value is not recognized, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly six roles: `ProgramAdmin`, `CareCoordinator`, `Paramedic`, `Clinician`, `BillingSpecialist`, and `PayerReviewer`. Their authorized operations are enumerated in the Section 4 endpoint table.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `CareCoordinator`, `Paramedic`, `Clinician`, or `BillingSpecialist`, `X-User-ID` is the `id` of the acting `Provider` (a persisted staff member); any ownership or authorship check on a resource that references a provider compares that resource's provider foreign key to `X-User-ID`. When `X-User-Role` is `PayerReviewer`, `X-User-ID` is the `id` of the acting `Payer`; adjudication authority is tied to that payer identity. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server may record it for audit but never compares it against any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` below 1 or above 100 is clamped into that range and a negative `offset` is treated as 0; a `limit` or `offset` that is present but not a valid integer is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. List endpoints also accept the domain-specific filters noted alongside their workflows in Section 3 — for example, providers may be filtered by `provider_type`, patients by `risk_tier`, referrals and enrollments by `patient_id`, `program_id`, `referral_id`, or `status`, care plans by `enrollment_id`, `authoring_clinician_id`, `cosigner_clinician_id`, or `status`, home visits and telehealth sessions by `enrollment_id`, `care_plan_id`, `patient_id`, `provider_id`, or `status`, med reconciliations by `enrollment_id`, `home_visit_id`, or `status`, social-needs referrals by `enrollment_id`, `domain`, or `status`, ED events by `patient_id` or `event_type`, billing claims by `enrollment_id`, `program_id`, `payer_id`, or `status`, and pilot programs by `payer_id`.

### 2.4. Common Resource Properties

Nearly every persisted resource carries a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at `1` on creation and increments by one on every mutation. It underpins the optimistic-concurrency mechanism described in Section 2.7.

There is one deliberate exception. An `EDEvent` is an immutable acute-care record: once written it is never modified. It therefore carries only `id` and `created_at`; it has neither `updated_at` nor `version`. No other entity omits these fields.

Whenever a derived counter or computed field on a resource changes as a side effect of some workflow — for example a program's budget or slot counters, or an enrollment's `revision_count` — that change is itself a mutation of the resource: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Logical Clock and Temporal Semantics

The system runs on a logical clock rather than wall-clock time, so that time-dependent calculations are deterministic and testable. Before any call is made, the clock reads `2026-03-01T00:00:00Z`. A `ProgramAdmin` may advance it by supplying a `to_iso8601` instant; the clock endpoint returns the new `current_utc`. The logical clock drives every time-sensitive computation: readmission windows, enrollment-day counts, the trailing-365-day admission window used for risk scoring, and the timestamps written to `enrolled_at` and `discharged_at`.

All datetime inputs and outputs are ISO 8601 UTC. Two datetime fields, `scheduled_start` and `scheduled_end`, appear on both home visits and telehealth sessions; a `scheduled_end` must be strictly after its `scheduled_start`, and a request that violates this is rejected as a validation error. Billing periods and scheduling windows are treated as half-open intervals — the start instant is included and the end instant is excluded — as detailed in the workflows that use them.

### 2.6. Request Validation Order and Nested Resource Resolution

When several checks could reject a request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic:

1. **Authentication.** Missing or unrecognized `X-User-ID` / `X-User-Role` headers yield `ERR_UNAUTHENTICATED`.
2. **Authorization.** A recognized role that is not permitted for the operation yields `ERR_UNAUTHORIZED`.
3. **Existence.** Every `id` in the path and every foreign key in the body is resolved left-to-right; the first that does not correspond to an existing resource yields `ERR_NOT_FOUND`.
4. **Body validation.** Missing required fields, wrong types, invalid enum members, or a `scheduled_end` that is not strictly after `scheduled_start` yield `ERR_VALIDATION`.
5. **Optimistic concurrency.** On care-plan creation, a stale `expected_enrollment_version` yields `ERR_STALE_VERSION` (see Section 2.7).
6. **State preconditions.** The target resource must be in a state that admits the requested transition. A generic illegal transition yields `ERR_INVALID_STATE`; the referral accept/decline path yields the more specific `ERR_REFERRAL_NOT_SCREENED` when the referral is not `SCREENED`; and med-reconciliation review yields `ERR_MED_REC_NOT_PENDING` when the record is not `PENDING_REVIEW`.
7. **Operational status of related resources.** A care plan that is not `ACTIVE` under a scheduled home visit yields `ERR_CARE_PLAN_NOT_ACTIVE`; an enrollment that is not `ACTIVE` yields `ERR_ENROLLMENT_NOT_ACTIVE`; a pilot program that is not `ACTIVE` yields `ERR_PROGRAM_NOT_ACTIVE`.
8. **Temporal conflicts.** Provider double-booking yields `ERR_SCHEDULE_CONFLICT`; a telehealth buffer violation yields `ERR_TELEHEALTH_BUFFER_CONFLICT`.
9. **Referential consistency.** A provider of the wrong type yields `ERR_PROVIDER_TYPE_MISMATCH`; a claim whose program/payer do not match its enrollment yields `ERR_CLAIM_EVENTS_CROSS_ENROLLMENT`.
10. **Business constraints.** Co-signature rules yield `ERR_COSIGN_REQUIRED` or `ERR_COSIGN_SAME_CLINICIAN`; a claim with no realized billable events yields `ERR_CLAIM_NO_BILLABLE_EVENTS`.
11. **Fiscal constraints.** A full pilot yields `ERR_ENROLLMENT_CAP_REACHED`; an over-budget claim yields `ERR_BUDGET_EXCEEDED`.

Lower-numbered checks always take precedence: a mid-flight state violation surfaces before a fiscal check, and a not-found parent surfaces before any body validation. When multiple checks share a priority number, each guards a distinct operation, so at most one applies to any given request.

### 2.7. Optimistic Concurrency on Care-Plan Creation

An `Enrollment` permits at most one care plan that is not yet `CLOSED`. Creating a new care plan legitimately supersedes any prior non-closed plan, so the create must be evaluated against a fresh view of the enrollment. To that end, the care-plan create operation requires an `expected_enrollment_version` field carrying the client's last observed `version` of the target `Enrollment`. If that value does not match the enrollment's current `version` — because another writer has advanced it since the client last read the enrollment — the create is rejected with `ERR_STALE_VERSION` at HTTP 412, preventing the client from attaching a plan on top of state it never observed. When the versions match, the create proceeds, closes any existing non-`CLOSED` care plan for the enrollment, and increments the enrollment's `version` by one. No other endpoint accepts or requires a version field.

### 2.8. Monetary Precision and Integer-Cent Arithmetic

All monetary quantities in the system — budgets, rates, bonuses, penalties, claim amounts, and computed savings — are stored and transported as whole integer numbers of cents. The claim-amount computation involves only integer terms and integer counts, so it requires no rounding at all. The cost-outcome computation does involve a fractional rate, so it rounds half up to whole cents; the precise rounding point is pinned in Section 3.9 so that per-visit savings are rounded before they are multiplied by a visit count, never after.

### 2.9. Pilot Program Budget and Enrollment-Slot Ledgers

Each `PilotProgram` maintains two live ledgers that must stay internally consistent at all times.

The **budget ledger** governs money. On creation, a program's `available_budget_cents` is initialized to its `budget_cap_cents` and its `committed_spend_cents` is initialized to 0. When a claim is submitted (or resubmitted), the committed amount is debited from `available_budget_cents` and credited to `committed_spend_cents`. When a submitted claim is denied, that same amount is credited back to `available_budget_cents` and decremented from `committed_spend_cents` — a compensating release that returns the program to the state it would have been in had the claim never been submitted. Paying a claim does not move program budget; the funds were already committed at submit time.

The **enrollment-slot ledger** governs capacity. On creation, `active_enrollment_count` is initialized to 0 and `remaining_slots` is initialized to the program's `enrollment_cap`. Accepting a referral increments `active_enrollment_count` by one; discharging or withdrawing an enrollment decrements it by one. After either change, `remaining_slots` is recomputed as `enrollment_cap` minus `active_enrollment_count`. A referral cannot be accepted once `active_enrollment_count` has reached `enrollment_cap`.

### 2.10. Cascading State Propagation

Several operations mutate more than one entity in a single logical step. These cascades are mandatory, not optional, and each hop is itself a state transition that fires its own side effects:

- Discharging an enrollment closes each of its non-closed care plans, and closing a care plan cancels that plan's still-scheduled home visits — a two-hop cascade from enrollment down to individual visits.
- Flagging a medication reconciliation sends the enrollment's single `ACTIVE` care plan back to `UNDER_REVISION`, which in turn increments the enrollment's `revision_count` and sets its `needs_review` flag.

The precise preconditions, counters, and reversals for each cascade are described in the Section 3 workflow that owns it. Every entity touched by a cascade has its `updated_at` and `version` advanced exactly as a direct mutation would.

## 3. Business Logic & Workflows

### 3.1. Program, Payer, and Staff Setup

A `ProgramAdmin` bootstraps the system. Payers are created first, each carrying a `name` and a `payer_type` that is one of `MEDICARE`, `MEDICAID`, or `COMMERCIAL`. A pilot program is then created with a `name` and a sponsoring `payer_id`, together with its full economic configuration: a `budget_cap_cents` ceiling on committed spend, an `enrollment_cap` on simultaneously active enrollments, the two encounter reimbursement rates `per_visit_rate_cents` and `per_telehealth_rate_cents`, the `diversion_bonus_cents` awarded when an ED-diversion target is met, the `readmission_penalty_cents` subtracted when a readmission occurs in the period, the `diversion_target_max_ed_visits` threshold that defines diversion success, the `avg_ed_cost_cents` assumed cost of one ED visit, the `diversion_credit_pct` fraction of that cost credited as savings per averted visit (a value between 0 and 1), and informational `start_date` and `end_date` markers. A newly created program is `ACTIVE`, with its budget and slot counters initialized as described in Section 2.9.

A program admin closes a program when the pilot ends, transitioning it `ACTIVE → CLOSED`; this increments the program's `version`. Attempting to close a program that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. A `CLOSED` program is terminal and rejects new claim submissions and new referral acceptances.

Staff members are represented as `Provider` records, each with a `full_name`, a `provider_type` that is one of `PARAMEDIC`, `CLINICIAN`, `COORDINATOR`, or `BILLER`, an `npi` National Provider Identifier, and an `active` flag that defaults to true when omitted and governs whether the provider may be assigned to work.

### 3.2. Patient Intake, Acute-Care Events, and Risk Stratification

A patient is registered with a `full_name`, a `date_of_birth` in `YYYY-MM-DD` form, a `baseline_ed_visits_12mo` count of ED visits in the year prior to enrollment, a `chronic_conditions_count`, and a `consent_on_file` flag that defaults to false when omitted. At creation the system computes the patient's `risk_score` and bands it into a `risk_tier` of `LOW`, `MODERATE`, or `HIGH`.

The risk score is a weighted sum. It first counts the patient's recent inpatient admissions — every `EDEvent` for the patient whose `event_type` is `INPATIENT_ADMISSION` and whose `event_date` falls on or after the logical clock's current instant minus 365 days. The score is then the patient's `baseline_ed_visits_12mo` multiplied by two, plus the `chronic_conditions_count` multiplied by three, plus that recent-admission count multiplied by five. The tier follows from the score: a score of at least 20 is `HIGH`; a score of at least 10 but below 20 is `MODERATE`; any score below 10 is `LOW`.

Acute-care utilization is recorded as `EDEvent` rows, which a `CareCoordinator` or `ProgramAdmin` may create. Each event carries a `patient_id`, an `event_type` of either `ED_VISIT` or `INPATIENT_ADMISSION`, an `event_date`, and — for an admission — an optional `discharge_date` that drives the readmission window. Recording an event has two computed effects. First, the system evaluates readmission: for a non-admission event, `is_readmission` is false; for an `INPATIENT_ADMISSION`, the system examines every prior `INPATIENT_ADMISSION` for the same patient that has a non-null `discharge_date` at or before the new event's `event_date`, and sets `is_readmission` to true if any such prior admission's discharge is within the readmission window of the new event date — that is, if the number of whole days between that prior `discharge_date` and this `event_date` is 30 or fewer. Exactly 30 days still counts as a readmission; 31 days does not. Second, because a new event changes the patient's utilization history, the system recomputes the patient's `risk_score` and `risk_tier`.

### 3.3. Referral Screening and Enrollment

The high-utilizer intake workflow begins when a `CareCoordinator` creates a `Referral` with a `patient_id`, a target `program_id`, and a `referring_source` that is one of `ED`, `HOSPITAL`, `PCP`, or `SELF`. A new referral is `SUBMITTED`.

Screening advances the referral `SUBMITTED → SCREENED` and captures a `screened_risk_tier` — a snapshot of the patient's current `risk_tier` taken at screen time. Only a screened referral may then be accepted or declined; attempting either transition on a referral that is not `SCREENED` is rejected with `ERR_REFERRAL_NOT_SCREENED`. Declining a screened referral moves it `SCREENED → DECLINED` and records the supplied `decline_reason` (a required field).

Accepting a screened referral is the pivotal step: it moves the referral `SCREENED → ACCEPTED` and creates a new `Enrollment`. Acceptance has three preconditions beyond the screened-state check — the referral's pilot program must be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`), and the program must have a free slot, meaning its `active_enrollment_count` is strictly less than its `enrollment_cap` (otherwise `ERR_ENROLLMENT_CAP_REACHED`). On success the system creates the enrollment in `ACTIVE` status, carrying the `patient_id`, `program_id`, and the originating `referral_id`, and stamps `enrolled_at` with the current logical-clock instant. It then increments the program's `active_enrollment_count` by one, recomputes `remaining_slots`, and increments the program's `version` by one. The acceptance response returns the newly created enrollment.

An enrollment tracks several derived fields over its life: `billed_amount_cents` (the running sum of amounts across its paid claims, initialized to 0), `revision_count` (how many times one of its care plans has entered `UNDER_REVISION`, initialized to 0), `needs_review` (a flag set true when a flagged reconciliation forces its active plan into revision, initialized to false), and `discharged_at` (stamped when the enrollment terminates).

### 3.4. Care Planning, Co-Signature, and Revision

A `Clinician` authors a `CarePlan` for an enrollment. The create carries an `authoring_clinician_id` (the clinician who wrote it, whose provider record must be of type `CLINICIAN`, otherwise `ERR_PROVIDER_TYPE_MISMATCH`), an optional `cosigner_clinician_id`, a `risk_level` of `LOW`, `MODERATE`, or `HIGH`, free-text `goals`, and the `expected_enrollment_version` required by the optimistic-concurrency rule in Section 2.7. The enrollment must itself be `ACTIVE` at create time, or the request is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. A new plan is created in `DRAFT`, supersedes and closes any existing non-`CLOSED` plan on the enrollment, and increments the enrollment's `version`.

Activation moves a plan into service and is where segregation of duties is enforced. A plan may be activated from `DRAFT → ACTIVE` or, after a revision cycle, from `UNDER_REVISION → ACTIVE`; the enrollment must be `ACTIVE`. When the plan's `risk_level` is `HIGH`, activation additionally requires a `cosigner_clinician_id` to be present — its absence is rejected with `ERR_COSIGN_REQUIRED` — and that co-signer must be a different provider from the `authoring_clinician_id`, since a clinician may not co-sign their own high-risk plan; a co-signer equal to the author is rejected with `ERR_COSIGN_SAME_CLINICIAN`. Activating a plan out of `UNDER_REVISION` clears the enrollment's `needs_review` flag.

Revision returns a plan to the drawing board: an `ACTIVE` plan moves `ACTIVE → UNDER_REVISION`, which increments the owning enrollment's `revision_count` by one and sets its `needs_review` flag to true. This same revision transition can be driven either by a clinician directly or automatically as the cascade from a flagged medication reconciliation (Section 3.5).

Closing a plan is terminal. From any of `DRAFT`, `ACTIVE`, or `UNDER_REVISION`, a plan may transition to `CLOSED`, and closure cascades: every home visit still in `SCHEDULED` status under that plan is cancelled. A plan is also closed automatically as the first hop of an enrollment discharge (Section 3.8).

### 3.5. Home Visits and Telehealth Encounters

Field encounters come in two forms that share vitals fields but differ in their scheduling safeguards.

A `CareCoordinator` schedules a `HomeVisit` with an `enrollment_id`, a `care_plan_id`, a `provider_id`, and a `scheduled_start`/`scheduled_end` window. The referenced care plan must be `ACTIVE` at schedule time, otherwise `ERR_CARE_PLAN_NOT_ACTIVE`; the enrollment must be `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE`; and the assigned provider must be of type `PARAMEDIC`, otherwise `ERR_PROVIDER_TYPE_MISMATCH`. Scheduling also reserves the paramedic's time: no other `SCHEDULED` home visit for the same provider may overlap the visit's half-open window `[scheduled_start, scheduled_end)`. Two visits that merely touch end-to-start do not overlap and are allowed; any true overlap is rejected with `ERR_SCHEDULE_CONFLICT`. A paramedic completes a visit by moving it `SCHEDULED → COMPLETED` and recording the vitals `systolic_bp`, `diastolic_bp`, and `heart_rate`; completion sets the visit's `billable` flag to true (it is false until then). A scheduled visit may instead be cancelled (`SCHEDULED → CANCELLED`) or marked a no-show (`SCHEDULED → NO_SHOW`); either outcome releases the paramedic's reserved window so the slot is free again.

A `CareCoordinator` schedules a `TelehealthSession` with an `enrollment_id`, the `patient_id` (the occupancy resource for buffer checks), a `provider_id`, and its own `scheduled_start`/`scheduled_end` window. The enrollment must be `ACTIVE` (`ERR_ENROLLMENT_NOT_ACTIVE`), and the assigned provider must be of type `CLINICIAN` (`ERR_PROVIDER_TYPE_MISMATCH`). Rather than an overlap check, telehealth enforces a patient buffer: no other `SCHEDULED` telehealth session for the same patient may fall within 15 minutes of this session's window. If another session lies inside that buffered window, the request is rejected with `ERR_TELEHEALTH_BUFFER_CONFLICT`. The buffer is exclusive at its boundary: a gap of exactly 15 minutes between the two sessions on either side is permitted, and only a strictly smaller gap conflicts. A session is completed (`SCHEDULED → COMPLETED`) by a clinician or a paramedic, recording `systolic_bp`, `diastolic_bp`, and `heart_rate` and setting `billable` to true; it may instead be cancelled (`SCHEDULED → CANCELLED`), which releases the patient's buffered occupancy window.

### 3.6. Medication Reconciliation

During a home visit, a `Paramedic` captures a `MedReconciliation` tied to that encounter. The record carries an `enrollment_id`, the `home_visit_id` during which medications were captured, a `medications` array of the reconciled medication strings, and a `discrepancy_count` that defaults to 0 when omitted. A new record is `DRAFTED`.

The paramedic submits the draft for clinician review, moving it `DRAFTED → PENDING_REVIEW`. A `Clinician` then reviews it, supplying a `review_outcome`; review is only permitted while the record is `PENDING_REVIEW`, otherwise `ERR_MED_REC_NOT_PENDING`. A `RECONCILED` outcome moves the record `PENDING_REVIEW → RECONCILED` and records that outcome with no further effect. A `FLAGGED` outcome moves it `PENDING_REVIEW → FLAGGED` and triggers the safety cascade: the enrollment's single `ACTIVE` care plan (there is at most one) is sent `ACTIVE → UNDER_REVISION`, which — as in Section 3.4 — increments the enrollment's `revision_count` and sets `needs_review` to true. The `review_outcome` and `status` fields are both drawn from the set `RECONCILED`/`FLAGGED`.

### 3.7. Social-Needs Referrals

Alongside clinical care, a `CareCoordinator` coordinates social determinants of health. A `SocialNeedsReferral` is opened for an `enrollment_id` in a `domain` that is one of `HOUSING`, `FOOD`, `TRANSPORT`, or `UTILITIES`; it begins `OPEN`. The coordinator refers the open need to a community partner, moving it `OPEN → REFERRED` and recording the `partner_org`. When the outcome is known, the coordinator resolves the referred need by supplying a `resolution_status` of either `RESOLVED` or `UNMET` and an optional `resolution_note`; this moves the referral `REFERRED → RESOLVED` or `REFERRED → UNMET` accordingly and records both fields. Both `RESOLVED` and `UNMET` are terminal outcomes.

### 3.8. Enrollment Discharge, Withdrawal, and Cascade Semantics

An enrollment leaves active service in one of two ways, both performed by a `CareCoordinator` and both requiring the enrollment to be `ACTIVE`.

Discharge is the cascading exit. It moves the enrollment `ACTIVE → DISCHARGED`, stamps `discharged_at` with the current logical-clock instant, and releases the program slot by decrementing the program's `active_enrollment_count` and recomputing `remaining_slots`. It also drives the full closure cascade of Section 2.10: each care plan on the enrollment that is in `DRAFT`, `ACTIVE`, or `UNDER_REVISION` is transitioned to `CLOSED`, and each such closure in turn cancels that plan's still-`SCHEDULED` home visits. Every entity touched along the way advances its `updated_at` and `version`.

Withdrawal is the simpler exit. It moves the enrollment `ACTIVE → WITHDRAWN`, stamps `discharged_at`, and releases the program slot by decrementing `active_enrollment_count` and recomputing `remaining_slots`. Withdrawal does not run the care-plan closure cascade.

### 3.9. Payer-Pilot Billing and Cost-Outcome Reporting

Billing turns realized encounters into money. A `BillingSpecialist` creates a `BillingClaim` with an `enrollment_id`, a `program_id`, a `payer_id`, and a billing period defined by `period_start` and `period_end`. The period is half-open: `period_start` is inclusive and `period_end` is exclusive. The claim's `program_id` and `payer_id` must be consistent with the enrollment — specifically the claim's `program_id` must match the enrollment's program, and its `payer_id` must match that program's sponsoring payer — otherwise the create is rejected with `ERR_CLAIM_EVENTS_CROSS_ENROLLMENT`. A new claim is `DRAFT`, and at creation the system computes a `provisional_amount_cents` estimate; it also records `billable_visit_count` and `billable_telehealth_count` on the draft, and those two counts reflect the final (`COMPLETED`-only) variant rather than the provisional variant used for `provisional_amount_cents`.

**Computing a claim amount.** The amount has one formula evaluated in two variants that differ only in which encounters count. The system first counts the enrollment's billable home visits — those whose `scheduled_start` falls in the claim's half-open period and whose status is in the variant's set — recording that count as `billable_visit_count`, and likewise counts qualifying telehealth sessions into `billable_telehealth_count`. The base amount is `billable_visit_count` multiplied by the program's `per_visit_rate_cents`, plus `billable_telehealth_count` multiplied by the program's `per_telehealth_rate_cents`. Next the system evaluates ED diversion: it counts the enrollment patient's `ED_VISIT` events whose `event_date` falls in the period, and diversion is achieved when that actual count is less than or equal to the program's `diversion_target_max_ed_visits`; if achieved, the program's `diversion_bonus_cents` is added, otherwise nothing is added. Then it evaluates readmission: if any `INPATIENT_ADMISSION` event for the patient within the period has `is_readmission` true, the program's `readmission_penalty_cents` is subtracted, otherwise nothing is subtracted. The final amount is computed in this fixed order — base first, then add the diversion bonus, then subtract the readmission penalty — and is finally floored at zero, so the amount is never negative. All terms are integer cents and no rounding is applied.

The two variants differ only in which encounter statuses count. The **provisional** variant, computed into `provisional_amount_cents` at draft creation, counts both `SCHEDULED` and `COMPLETED` visits and sessions, projecting still-scheduled encounters as if they will occur. The **final** variant, computed at submit and resubmit, counts only `COMPLETED` visits and sessions, so only realized encounters are paid.

**Submitting a claim.** Submission moves the claim `DRAFT → SUBMITTED` and has several preconditions. The claim's program must be `ACTIVE`, otherwise `ERR_PROGRAM_NOT_ACTIVE`. There must be at least one realized billable encounter in the period — that is, `billable_visit_count` plus `billable_telehealth_count` must be greater than zero — otherwise `ERR_CLAIM_NO_BILLABLE_EVENTS`. And the amount must fit the program's remaining budget: the computed final amount must be less than or equal to the program's `available_budget_cents`, otherwise `ERR_BUDGET_EXCEEDED`. On success the system computes `final_amount_cents` using the final variant, sets `amount_cents` equal to it, debits `available_budget_cents` by `amount_cents`, and credits `committed_spend_cents` by `amount_cents`.

**Adjudication.** A `PayerReviewer` adjudicates a submitted claim by supplying an `outcome`. A paid outcome moves the claim `SUBMITTED → PAID` and increments the enrollment's `billed_amount_cents` by the claim's `amount_cents`. A denied outcome moves the claim `SUBMITTED → DENIED`, records the supplied `denial_reason` (an optional field), and performs the compensating budget release of Section 2.9 — crediting `available_budget_cents` back by `amount_cents` and decrementing `committed_spend_cents` by `amount_cents`.

**Resubmission.** A `BillingSpecialist` may resubmit a denied claim, moving it `DENIED → SUBMITTED`. Resubmission recomputes `final_amount_cents` and `amount_cents` with the final variant and requires that the recomputed final amount still fit within `available_budget_cents` (otherwise `ERR_BUDGET_EXCEEDED`); on success it again debits `available_budget_cents` and credits `committed_spend_cents` by the new `amount_cents`.

**Cost-outcome reporting.** A `CareCoordinator`, `ProgramAdmin`, or `BillingSpecialist` may read an enrollment's cost-outcome summary, a computed report that never mutates state. The system first measures the enrollment's tenure: `enrollment_days` is the number of whole days from `enrolled_at` to the current logical-clock instant, taking the floor and never dropping below zero (if the clock precedes `enrolled_at`, `enrollment_days` is 0). It then projects expected ED usage as `expected_ed_visits`, computed by taking the patient's `baseline_ed_visits_12mo`, multiplying by `enrollment_days`, dividing by 365, and rounding half up to a whole number. It counts `actual_ed_visits` as the patient's `ED_VISIT` events whose `event_date` falls in the half-open interval from `enrolled_at` up to the current instant. Averted visits, `averted_ed_visits`, are the expected visits minus the actual visits, floored at zero. The per-visit saving, `per_averted_saving_cents`, is the program's `avg_ed_cost_cents` multiplied by its `diversion_credit_pct`, rounded half up to whole cents — and this rounding happens first, before any multiplication by a visit count. The chronological figure `actual_savings_cents` is `averted_ed_visits` multiplied by that rounded per-visit saving; the forward-looking figure `projected_savings_cents` is `expected_ed_visits` multiplied by the same rounded per-visit saving. Finally, `net_savings_cents` is `actual_savings_cents` minus the enrollment's `billed_amount_cents`. The summary returns all of these figures together: `projected_savings_cents`, `actual_savings_cents`, `net_savings_cents`, `averted_ed_visits`, `expected_ed_visits`, `actual_ed_visits`, and `per_averted_saving_cents`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — including state-transition actions and the logical-clock control — return `200 OK`. All list and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mih/payers` | Create a payer | ProgramAdmin |
| GET | `/mih/payers/{id}` | Fetch a payer | ProgramAdmin, CareCoordinator, BillingSpecialist, PayerReviewer |
| POST | `/mih/programs` | Create a pilot program | ProgramAdmin |
| GET | `/mih/programs/{id}` | Fetch a pilot program (includes budget and slot counters) | ProgramAdmin, CareCoordinator, BillingSpecialist, PayerReviewer, Clinician |
| GET | `/mih/programs` | List pilot programs (filter by payer) | ProgramAdmin, CareCoordinator, BillingSpecialist, PayerReviewer |
| POST | `/mih/programs/{id}/close` | Close a pilot program | ProgramAdmin |
| POST | `/mih/providers` | Create a provider (staff member) | ProgramAdmin |
| GET | `/mih/providers/{id}` | Fetch a provider | ProgramAdmin, CareCoordinator, Clinician, Paramedic, BillingSpecialist |
| GET | `/mih/providers` | List providers (filter by type) | ProgramAdmin, CareCoordinator, Clinician, Paramedic, BillingSpecialist |
| POST | `/mih/patients` | Create a patient; computes initial risk | CareCoordinator, ProgramAdmin |
| GET | `/mih/patients/{id}` | Fetch a patient | CareCoordinator, Clinician, Paramedic, ProgramAdmin |
| GET | `/mih/patients` | List patients | CareCoordinator, Clinician, Paramedic, ProgramAdmin |
| POST | `/mih/referrals` | Create a high-utilizer referral | CareCoordinator |
| GET | `/mih/referrals/{id}` | Fetch a referral | CareCoordinator, Clinician, ProgramAdmin |
| GET | `/mih/referrals` | List referrals | CareCoordinator, Clinician, ProgramAdmin |
| POST | `/mih/referrals/{id}/screen` | Screen a referral; snapshots patient risk tier | CareCoordinator |
| POST | `/mih/referrals/{id}/accept` | Accept a screened referral; creates an enrollment | CareCoordinator |
| POST | `/mih/referrals/{id}/decline` | Decline a screened referral | CareCoordinator |
| GET | `/mih/enrollments/{id}` | Fetch an enrollment | CareCoordinator, Clinician, Paramedic, BillingSpecialist, ProgramAdmin |
| GET | `/mih/enrollments` | List enrollments | CareCoordinator, Clinician, Paramedic, BillingSpecialist, ProgramAdmin |
| POST | `/mih/enrollments/{id}/discharge` | Discharge an enrollment (cascades) | CareCoordinator |
| POST | `/mih/enrollments/{id}/withdraw` | Withdraw an enrollment | CareCoordinator |
| GET | `/mih/enrollments/{id}/cost-outcome` | Computed cost/outcome summary | CareCoordinator, ProgramAdmin, BillingSpecialist |
| POST | `/mih/enrollments/{id}/care-plans` | Create a care plan (OCC-guarded) | Clinician |
| GET | `/mih/care-plans/{id}` | Fetch a care plan | Clinician, CareCoordinator, Paramedic, ProgramAdmin |
| GET | `/mih/care-plans` | List care plans | Clinician, CareCoordinator, Paramedic, ProgramAdmin |
| POST | `/mih/care-plans/{id}/activate` | Activate a care plan; enforces HIGH-risk co-sign | Clinician |
| POST | `/mih/care-plans/{id}/revise` | Send an active care plan back to revision | Clinician |
| POST | `/mih/care-plans/{id}/close` | Close a care plan; cancels scheduled visits | Clinician |
| POST | `/mih/home-visits` | Schedule a home visit | CareCoordinator |
| GET | `/mih/home-visits/{id}` | Fetch a home visit | CareCoordinator, Paramedic, Clinician, ProgramAdmin |
| GET | `/mih/home-visits` | List home visits | CareCoordinator, Paramedic, Clinician, ProgramAdmin |
| POST | `/mih/home-visits/{id}/complete` | Complete a home visit and record vitals | Paramedic |
| POST | `/mih/home-visits/{id}/cancel` | Cancel a scheduled home visit | CareCoordinator, Paramedic |
| POST | `/mih/home-visits/{id}/no-show` | Mark a scheduled home visit a no-show | Paramedic |
| POST | `/mih/telehealth-sessions` | Schedule a telehealth session | CareCoordinator |
| GET | `/mih/telehealth-sessions/{id}` | Fetch a telehealth session | CareCoordinator, Paramedic, Clinician, ProgramAdmin |
| GET | `/mih/telehealth-sessions` | List telehealth sessions | CareCoordinator, Paramedic, Clinician, ProgramAdmin |
| POST | `/mih/telehealth-sessions/{id}/complete` | Complete a telehealth session and record vitals | Clinician, Paramedic |
| POST | `/mih/telehealth-sessions/{id}/cancel` | Cancel a scheduled telehealth session | CareCoordinator, Clinician |
| POST | `/mih/med-reconciliations` | Create a medication reconciliation | Paramedic |
| GET | `/mih/med-reconciliations/{id}` | Fetch a med reconciliation | Paramedic, Clinician, CareCoordinator, ProgramAdmin |
| GET | `/mih/med-reconciliations` | List med reconciliations | Paramedic, Clinician, CareCoordinator, ProgramAdmin |
| POST | `/mih/med-reconciliations/{id}/submit` | Submit a drafted med reconciliation for review | Paramedic |
| POST | `/mih/med-reconciliations/{id}/review` | Review a med reconciliation (reconcile or flag) | Clinician |
| POST | `/mih/social-referrals` | Open a social-needs referral | CareCoordinator |
| GET | `/mih/social-referrals/{id}` | Fetch a social-needs referral | CareCoordinator, Clinician, ProgramAdmin |
| GET | `/mih/social-referrals` | List social-needs referrals | CareCoordinator, Clinician, ProgramAdmin |
| POST | `/mih/social-referrals/{id}/refer` | Refer an open social need to a partner org | CareCoordinator |
| POST | `/mih/social-referrals/{id}/resolve` | Resolve a referred social need | CareCoordinator |
| POST | `/mih/ed-events` | Record an ED visit or inpatient admission | CareCoordinator, ProgramAdmin |
| GET | `/mih/ed-events/{id}` | Fetch an ED event | CareCoordinator, Clinician, ProgramAdmin |
| GET | `/mih/ed-events` | List ED events (filter by patient) | CareCoordinator, Clinician, ProgramAdmin |
| POST | `/mih/billing-claims` | Create a draft billing claim; computes provisional amount | BillingSpecialist |
| GET | `/mih/billing-claims/{id}` | Fetch a billing claim | BillingSpecialist, ProgramAdmin, PayerReviewer |
| GET | `/mih/billing-claims` | List billing claims | BillingSpecialist, ProgramAdmin, PayerReviewer |
| POST | `/mih/billing-claims/{id}/submit` | Submit a draft claim; computes final amount and commits budget | BillingSpecialist |
| POST | `/mih/billing-claims/{id}/adjudicate` | Adjudicate a submitted claim (PAID or DENIED) | PayerReviewer |
| POST | `/mih/billing-claims/{id}/resubmit` | Resubmit a denied claim; recommits budget | BillingSpecialist |
| POST | `/mih/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_REFERRAL_NOT_SCREENED` | 409 Conflict |
| `ERR_MED_REC_NOT_PENDING` | 409 Conflict |
| `ERR_CARE_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_TELEHEALTH_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_PROVIDER_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_EVENTS_CROSS_ENROLLMENT` | 422 Unprocessable Entity |
| `ERR_COSIGN_REQUIRED` | 422 Unprocessable Entity |
| `ERR_COSIGN_SAME_CLINICIAN` | 422 Unprocessable Entity |
| `ERR_CLAIM_NO_BILLABLE_EVENTS` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_CAP_REACHED` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 409 Conflict |
