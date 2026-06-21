# Newborn / Parenting Registry API — Product Requirements Document

## 1. Introduction

The Newborn / Parenting Registry coordinates the full arc of a hospital birth, from the moment an expectant parent pre-registers through the day a healthy infant leaves the building with a packed discharge bag, a filed birth certificate, and a nurse follow-up schedule. The platform exists because the people who shepherd a newborn through these milestones — intake clerks, bedside nurses, neonatologists, benefits coordinators, and vital-records officers — each work from a different vantage point, on different clocks, against different deadlines. A premature infant may need a NICU bed within minutes; a dependent must be added to a parent's insurance within a thirty-day special-enrollment window; a birth certificate carries a statutory filing deadline measured in days. When these timelines are tracked in disconnected spreadsheets, infants slip through gaps: a bed claim races another, an enrollment window quietly closes, a discharge proceeds before the paperwork that legally must precede it.

This API is the single system of record that binds those workflows together. It enforces the clinical safety gates that decide whether a newborn rooms in with its mother or escalates to intensive care, arbitrates a scarce pool of NICU beds across competing admissions, computes enrollment and filing deadlines with the calendar nuances each payer and agency demands, and refuses to discharge an infant until every prerequisite — feeding evidence, bed clearance, an issued discharge bag, and a filed birth certificate — is demonstrably in place. Every consequential action is journaled to an immutable audit trail so that supervisors can reconstruct exactly what happened, by whom, and when.

This document specifies the system's behavior precisely enough that an implementation can be built and verified against it. Section 2 fixes the system-wide contracts — authentication, response shape, pagination, concurrency, precision, and the cross-cutting consistency rules. Section 3 narrates the business workflows in the order a real birth unfolds. Sections 4 and 5 enumerate the endpoints and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which they act. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly six roles, each owning a distinct slice of the registry lifecycle. An `IntakeClerk` owns the pre-registration admission pipeline — drafting, submitting, admitting, and cancelling a registration. An `AttendingNurse` owns the newborn clinical lifecycle: recording births, rooming infants in, running lactation consults, assembling and issuing discharge bags, discharging, and working the nurse follow-up tasks. A `Neonatologist` owns NICU escalation, step-down, the shared bed pool, and manual bed placement. A `BenefitsCoordinator` owns insurance policies and the thirty-day special-enrollment dependent-add workflow. A `VitalRecordsOfficer` owns the birth-certificate and SSN-application government filings. A `RegistrySupervisor` is the operational override role: it closes pre-registrations, registers beds and policies, sets the test clock, and may read every resource in the system.

All six roles are opaque operator roles. When `X-User-Role` names any of `IntakeClerk`, `AttendingNurse`, `Neonatologist`, `BenefitsCoordinator`, `VitalRecordsOfficer`, or `RegistrySupervisor`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it — for example, the role that performed an audited action is captured as `actor_role` on the corresponding audit event — but it never compares `X-User-ID` to any entity's `id`, and ownership of a resource is never decided by matching `X-User-ID` against a stored foreign key. Authorization is purely role-based: it depends only on whether the named role is permitted for the operation, as enumerated in Section 4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip before the first returned item, and it defaults to 0.

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. List responses carry the pagination bookkeeping inside the `meta` object of the envelope, populating the `limit`, `offset`, `total_count`, and `has_more` fields.

### 2.4. Resource Identity, Timestamps, and Versioning

Almost every resource in the system carries a common set of system-managed properties. The `id` is a server-minted UUID with no type prefix; it is identity only and is never consulted in any business, clinical, or billing decision. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, stamped when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every modification to the resource. The `version` field is an integer that begins at 1 when the resource is created and increments by one on every subsequent mutation of the resource; it underpins the optimistic concurrency mechanism described in §2.7.

These four common properties — `id`, `created_at`, `updated_at`, and `version` — are present on `PreRegistration`, `InsurancePolicy`, `Newborn`, `LactationConsult`, `NicuBed`, `NicuStay`, `DischargeBag`, `FollowUpTask`, `DependentEnrollment`, and `GovernmentFiling`. The lone exception is the audit-event record, which is immutable once written: it carries only an `id` and a `created_at`, and deliberately omits both `updated_at` and `version`.

### 2.5. Cascading State Consistency

A single client action frequently mutates more than one resource, and the system applies every consequence of an action before returning. When a writer escalates an infant to the NICU, the server does not merely flip the infant's status — it creates the stay record, runs the bed selector, may occupy a bed, and journals the event, all as one transition. When a neonatologist steps an infant down, the server closes that infant's open stay, frees the bed, and promotes the next waiting infant onto the freed bed in a single cascade. Each entity touched by such a cascade independently records the change: its own `updated_at` is refreshed and its own `version` is incremented. The detailed effect chains are specified per workflow in Section 3; the principle here is that secondary effects are never deferred or left to a later request — they are part of the same atomic transition that the client initiated.

### 2.6. Nested Resource Retrieval and Reference Validation

Several read endpoints address a resource by walking a path that names a parent before a child — for example, listing the newborns recorded under a particular pre-registration, the dependent enrollments under a particular policy, or the stays that have occupied a particular bed. For any such request, the server validates each identifier in the path from left to right, and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` before any deeper lookup is attempted. The same existence discipline governs write requests: every path identifier and every foreign-key reference carried in the body must resolve to an existing resource, again checked left to right, and any unresolved reference yields `ERR_NOT_FOUND`. Existence checking precedes payload well-formedness checking, which in turn precedes any state or business rule.

### 2.7. Optimistic Concurrency Control

Two operations in this system are guarded against acting on a stale view of a shared parent, because both consume a scarce resource whose availability the client may have observed before another writer changed it.

The first guard protects NICU escalation. A request to escalate a newborn to the NICU must carry `expected_newborn_version`, a non-optional field whose value is the `version` of the target `Newborn` that the client last observed. If that value does not match the newborn's current `version` — because another writer has already escalated the same infant, creating a stay that legitimately claimed a scarce bed and bumping the newborn's version — the escalation is rejected with `ERR_STALE_VERSION` at HTTP 412, and no stay is created. This prevents the second writer from acting on an out-of-date belief about whether the infant still needs a bed.

The second guard protects dependent approval. A request to approve a dependent enrollment must carry `expected_policy_version`, a non-optional field whose value is the `version` of the governing `InsurancePolicy` that the client last observed. If that value does not match the policy's current `version` — because another writer has already enrolled a dependent under the same policy, consuming a finite slot and bumping the policy version — the approval is rejected with `ERR_STALE_VERSION` at HTTP 412. This prevents the second writer from approving against a belief that a slot remains free when it no longer does.

Only these two write operations take a version field. No other endpoint accepts or requires an expected-version input.

### 2.8. Precision, Rounding, and Temporal Comparisons

Monetary amounts in this system are expressed in integer cents; the discharge-bag valuation rounds each component to a whole cent using the round-half-up convention before any summation, as detailed in §3.6. The discharge-readiness index is an integer point total. All timestamps are ISO 8601 UTC values carried to millisecond precision, and every deadline comparison in the system is evaluated against the server's current clock at millisecond resolution. The direction of each comparison — whether a boundary instant counts as inside or outside a window — is specified individually with each deadline in Section 3, because the special-enrollment window, the filing deadlines, and the follow-up due times do not all treat their boundaries the same way.

### 2.9. The Test-Driving Clock

Because much of the system's logic turns on the passage of time relative to fixed deadlines, the server maintains a single logical clock that drives every `now()` reading. A `RegistrySupervisor` may set this clock to an arbitrary UTC instant by supplying a `to_iso8601` value; the supplied instant is normalized to the canonical ISO 8601 UTC form with three fractional digits before it is stored, and the set-clock response returns a `200 OK` whose `data` object carries that normalized instant under a single `current_utc` field. From that point forward, every deadline evaluation, every admit-window check, and every miss determination reads the clock at the supplied instant. This logical clock also drives the `created_at` and `updated_at` stamps and the audit-event `created_at`, so that resource ordering is deterministic under a pinned clock; when the clock has never been set the server falls back to its real wall clock. This capability exists so that temporal behavior can be exercised deterministically.

### 2.10. The Audit Trail

Consequential transitions append an immutable audit record. Each such record names the `newborn_id` it concerns (left null for pre-registration-only events), captures the `actor_role` that performed the action, classifies the action through an `event_type`, and snapshots the triggering transition in a `detail` payload. The recognized event types are `BIRTH_RECORDED`, `NICU_ESCALATED`, `NICU_BED_ASSIGNED`, `STEP_DOWN`, `DISCHARGED`, `BAG_ISSUED`, `DEPENDENT_ENROLLED`, `SEP_EXPIRED`, `FILING_SUBMITTED`, `FILING_LATE_FLAGGED`, and `FOLLOWUP_ESCALATED`. The specific transitions that emit each event type are called out in the Section 3 workflows where those transitions occur.

## 3. Business Logic & Workflows

### 3.1. Pre-Registration and Admission

The journey begins before birth. An `IntakeClerk` opens a **pre-registration** by supplying the expectant parent's legal name in `mother_full_name`, their date of birth in `mother_dob` as an ISO 8601 calendar date, the estimated `due_date`, a `payer_policy_id` pointing at the insurance policy under which the newborn dependent will eventually be added, and the `planned_delivery_facility` as free text. The clerk may also include `birth_plan_flags`, a map of birth-plan preferences such as a breastfeeding-intent flag or a cord-blood-banking flag; when omitted it defaults to an empty map. A fresh pre-registration is created with its `status` field at `DRAFT`, its `admitted_at` is null, and its `newborn_count` — the number of newborn rows recorded against it, regardless of their clinical state — begins at zero. Every lifecycle-bearing resource in the system exposes its lifecycle position through a `status` field carrying one of the resource's defined states; the newborn instead exposes its position through the `clinical_status` field described in §3.2.

Submitting a registration advances it from `DRAFT` to `SUBMITTED`. Submission requires that all of the required intake fields — `mother_full_name`, `mother_dob`, `due_date`, `payer_policy_id`, and `planned_delivery_facility` — are present, and that the supplied `payer_policy_id` resolves to an existing insurance policy; an unresolved `payer_policy_id` is rejected with `ERR_NOT_FOUND`, and this check is applied after the `DRAFT`-state check rather than ahead of it. Admitting a registration then advances it from `SUBMITTED` to `ADMITTED`, but only inside the **admit window**: the current clock date must fall on or after the day twenty-one days before the `due_date` and on or before the day twenty-one days after the `due_date`, with both ends of that window inclusive. An admit attempt whose clock date lands outside that inclusive window is rejected with `ERR_ADMIT_WINDOW_CLOSED`. A successful admission stamps `admitted_at` with the current clock.

A registration may be withdrawn before any birth is recorded. Cancelling moves a registration from either `DRAFT` or `SUBMITTED` to `CANCELLED`, and is permitted only while `newborn_count` is zero — once a birth has been recorded under the registration, cancellation is no longer available and a cancel attempt with a non-zero `newborn_count` is rejected with `ERR_INVALID_STATE`. Each of these transitions — submit, admit, and cancel — increments the registration's `version`.

The registration is finally retired by a `RegistrySupervisor` who closes it, moving it from `BIRTH_RECORDED` to `CLOSED`. Closing is permitted only when every newborn recorded under the registration has reached `DISCHARGED`; a close attempt where some newborn is not yet `DISCHARGED` is rejected with `ERR_INVALID_STATE`. The close transition increments the registration's `version`. `CLOSED` and `CANCELLED` are the registration's terminal states.

### 3.2. Recording Births and the Multiples Case

Once a registration is `ADMITTED`, the `AttendingNurse` records each birth against it. Recording a birth creates a **newborn** and requires the infant's `birth_datetime` — the recorded moment of birth, stored as the given ISO 8601 UTC instant and serving as the anchor for the enrollment and filing clocks downstream — together with a `birth_sequence` (1 for a singleton or the first of multiples, 2 for the second, and so on), the `weight_grams` birth weight, the `gestational_age_weeks` completed-weeks figure, and the five-minute APGAR score `apgar_5min`. The nurse may also supply the infant's `legal_name` at this point, though it may be left for later. Birth weight must be at least 200 grams, gestational age must be between 20 and 45 weeks inclusive, and the APGAR score must be between 0 and 10 inclusive; a value outside these ranges is an `ERR_INVALID_REQUEST`.

The `birth_sequence` must be unique within a single registration: an attempt to record a birth whose sequence number is already used under that registration is rejected with `ERR_DUPLICATE_BIRTH_SEQUENCE`. The first birth recorded under a registration advances the registration from `ADMITTED` to `BIRTH_RECORDED`; subsequent multiples are recorded through the same action while the registration remains in `BIRTH_RECORDED`, and the registration's status stays `BIRTH_RECORDED` for them. Every birth recorded recomputes `newborn_count` and increments the registration's `version`. A newly recorded newborn starts with its `clinical_status` at `BORN`, its `pre_registration_id` set to the registration the birth was recorded under, its `care_location` at `WELL_BABY_NURSERY`, a `discharge_readiness_score` of 0, and a null `discharged_at`.

### 3.3. The First Clinical Fork: Rooming In versus NICU Escalation

Every `BORN` infant faces one decision that determines its entire pathway: does it meet the **NICU clinical criteria**? An infant meets those criteria when any one of three conditions holds — its gestational age is under 35 weeks, or its five-minute APGAR is 6 or lower, or its birth weight is under 1800 grams. Equivalently, an infant is clear of the criteria only when all three are satisfied at once: gestational age is 35 weeks or more, APGAR is 7 or more, and birth weight is 1800 grams or more.

A `BORN` infant that is clear of the criteria may be **roomed in** by the `AttendingNurse`, advancing from `BORN` to `ROOMING_IN` and setting `care_location` to `MOTHER_ROOM`. Rooming in requires that the infant currently be in `BORN`. If the infant in fact meets the NICU clinical criteria, room-in is forbidden and the attempt is rejected with `ERR_NICU_CRITERIA_MET` — such an infant must be escalated instead. The room-in transition increments the newborn's `version`.

Escalation is the `Neonatologist`'s entry into the NICU pathway, and it can be reached either directly from `BORN` or later from `ROOMING_IN` if an infant deteriorates after initially rooming in. Escalating from `BORN` requires that the infant actually meet the NICU clinical criteria; an attempt to escalate a `BORN` infant that does not meet them is rejected with `ERR_NICU_CRITERIA_NOT_MET`. (Escalation from `ROOMING_IN` reflects late deterioration and is permitted on the strength of the rooming-in status alone.) The escalation request carries the `required_level` of acuity the infant needs, the `admitted_at` escalation timestamp that marks the start of the NICU occupation interval, and the `expected_newborn_version` for the concurrency guard described in §2.7. A successful escalation moves the newborn to `NICU_ADMITTED`, sets `care_location` to `NICU`, creates a stay record, runs the bed selector, journals a `NICU_ESCALATED` audit event, and increments the newborn's `version`. The bed-selection cascade is detailed in §3.4.

### 3.4. NICU Beds, Stay Placement, and the Step-Down Cascade

NICU beds form a shared pool that newborns across different registrations compete for. A `Neonatologist` or `RegistrySupervisor` registers a **bed** with a human-readable `bed_label` that is unique within the unit and an `acuity_level` capability tier, which is one of `LEVEL_2`, `LEVEL_3`, or `LEVEL_4`, ordered so that `LEVEL_2` is lower than `LEVEL_3`, which is lower than `LEVEL_4`. A bed's `occupancy_status` is one of `VACANT`, `OCCUPIED`, or `OUT_OF_SERVICE`, beginning at `VACANT`, and it carries a `current_stay_id` back-pointer that names the open stay occupying it, null whenever the bed is vacant or out of service. That back-pointer is a convenience cache, kept consistent with the stay's own `nicu_bed_id`; the authoritative bed-to-stay history is discovered by listing the stays recorded against a bed.

When an escalation creates a **stay**, the stay records the escalated infant via `newborn_id`, the `required_level` clinical acuity it needs, the `admitted_at` start of its occupation interval, and a `discharged_at` end of that interval that remains null while the stay is open. A new stay begins in status `PENDING_BED` with a null `nicu_bed_id`. The server then runs its **bed selector**: it considers beds whose `occupancy_status` is `VACANT` and whose `acuity_level` is greater than or equal to the stay's `required_level`, and among those eligible beds it picks the earliest-created one (ordered by `created_at`, ties broken by internal creation sequence; acuity tier is not used as a tie-breaker, so a higher-acuity bed created earlier is chosen over a just-sufficient bed created later). On success the selector assigns the chosen bed's id to the stay's `nicu_bed_id`, sets the stay's status to `ACTIVE`, sets the bed's `occupancy_status` to `OCCUPIED`, points the bed's `current_stay_id` at the stay, and journals a `NICU_BED_ASSIGNED` audit event. If no eligible bed exists, the stay simply remains in `PENDING_BED` awaiting one, and `care_location` is still set to `NICU`. The valid stay statuses are `PENDING_BED`, `ACTIVE`, `STEPPED_DOWN`, `CLOSED`, and `CANCELLED`, with `CLOSED` and `CANCELLED` terminal.

A neonatologist may also place a pending stay onto a chosen bed **manually**, overriding the auto-selector. Manual placement requires that the stay currently be in `PENDING_BED`, that the target bed be `VACANT` with an `acuity_level` at or above the stay's `required_level`, and — critically — that the stay's occupation interval not overlap any prior stay interval recorded on that bed. The bed-not-`VACANT` and insufficient-bed-acuity conditions are each treated as undefined transitions and rejected with `ERR_INVALID_STATE`, evaluated after the stay's own `PENDING_BED` state check and ahead of the interval-overlap test. The overlap test uses half-open interval semantics over `[admitted_at, discharged_at)`: two intervals overlap only where they share interior time, so a new stay whose `admitted_at` exactly equals a prior stay's `discharged_at` is adjacent rather than overlapping and is permitted. A still-open interval — one whose `discharged_at` is null, as the placing stay's always is — is treated as extending to positive infinity for this comparison; concretely, the placing stay overlaps a prior stay exactly when the prior stay's `discharged_at` is null or strictly after the placing stay's `admitted_at`. A manual placement whose interval overlaps a prior interval on the bed is rejected with `ERR_BED_INTERVAL_OVERLAP`. A successful manual placement assigns the `nicu_bed_id`, sets the stay to `ACTIVE`, occupies the bed with its `current_stay_id`, journals `NICU_BED_ASSIGNED`, and increments the stay's `version`. The manual-placement request identifies the stay to place through `nicu_stay_id`.

A not-yet-bedded escalation can be **withdrawn**: a neonatologist may cancel a stay that is still in `PENDING_BED` — for instance when the infant is transferred to another hospital — moving it from `PENDING_BED` to `CANCELLED` and incrementing the stay's `version`.

**Stepping down** is the neonatologist's transition out of intensive care, and it drives the system's deepest cascade. A step-down requires that the infant have an open stay in `ACTIVE` status; a newborn whose only stay is still `PENDING_BED` (never bedded) cannot step down, and such an attempt is rejected with `ERR_NO_ACTIVE_NICU_STAY`. When a qualifying infant steps down, the server moves the newborn from `NICU_ADMITTED` to `STEP_DOWN`, sets the infant's open stay to `STEPPED_DOWN` and stamps that stay's `discharged_at` with the current clock, and frees the bed by setting its `occupancy_status` back to `VACANT` and clearing its `current_stay_id`. It then **promotes** the longest-waiting eligible stay onto that freed bed: among stays still in `PENDING_BED` whose `required_level` is at or below the freed bed's `acuity_level`, it selects the one with the earliest `admitted_at`, breaking ties by the earliest `created_at`, and gives it the bed — assigning its `nicu_bed_id`, setting it to `ACTIVE`, occupying the bed, and journaling a `NICU_BED_ASSIGNED` event for the promoted stay. The step-down itself sets the infant's `care_location` to `STEP_DOWN_UNIT`, journals a `STEP_DOWN` audit event, and increments the newborn's `version`. Later, when the infant is discharged, its `STEPPED_DOWN` stay moves to `CLOSED` with no further bed effects, since the bed was already freed at step-down.

### 3.5. Lactation Consults and Feeding Evidence

Breastfeeding support runs on a timeline parallel to the clinical pathway: a consult's lifecycle evolves independently of where the infant sits in its care progression. An `AttendingNurse` schedules a **lactation consult** for an infant by supplying the `newborn_id` and a `consult_datetime`; the consult is created in `SCHEDULED` status with a null `latch_score`. To prevent over-booking the same infant, the system enforces a **consult buffer** of 240 minutes: scheduling a consult is rejected with `ERR_CONSULT_BUFFER_CONFLICT` when its `consult_datetime` falls within 240 minutes of an existing consult for the same infant whose status is `SCHEDULED`, `COMPLETED`, or `FEEDING_AT_RISK`. The buffer is closed on both sides — the conflict triggers when the absolute gap between the new consult time and an existing consult time is 240 minutes or less, both endpoints inclusive — and consults already in `CANCELLED` are ignored for this test.

Completing a consult records the `latch_score`, a LATCH assessment between 0 and 10. Completion requires that a `latch_score` be supplied and in the 0–10 range (a missing or out-of-range score yields `ERR_INVALID_REQUEST`, checked ahead of the state check), that the consult currently be `SCHEDULED`, and that the infant not already be `DISCHARGED` — a discharged infant is treated as an undefined transition and yields `ERR_INVALID_STATE`. The outcome branches on the score. When the recorded `latch_score` is 7 or higher, the consult moves from `SCHEDULED` to `COMPLETED` and its `feeding_adequate` flag is recomputed to true (adequate feeding holds exactly when the consult is `COMPLETED` and its `latch_score` is at least 7). When the recorded `latch_score` is below 7, the consult moves instead from `SCHEDULED` to `FEEDING_AT_RISK`, the score is stored, and `feeding_adequate` stays false; no follow-up consult is auto-scheduled here, since nurse follow-up tasks are created only at discharge. Either completion outcome increments the consult's `version`. A consult may also be cancelled while it is still `SCHEDULED`, moving it from `SCHEDULED` to `CANCELLED` and incrementing its `version`; `CANCELLED` is the consult's terminal state. A `FEEDING_AT_RISK` outcome suppresses the feeding contribution to the discharge-readiness score described in §3.6.

### 3.6. Discharge Bags and Their Valuation

Before an infant can leave, a **discharge bag** of take-home supplies must be assembled and issued by the `AttendingNurse`. A bag is created for a `newborn_id` with a set of `line_items`, each item being an object carrying a `sku`, a `category`, a `qty`, and a `unit_value_cents`. The item category is one of `FORMULA`, `DIAPERS`, `EDUCATION`, `CARSEAT_VOUCHER`, or `MEDICATION`. A new bag starts in `DRAFT` with a `total_value_cents` of 0 and a `requires_pharmacy_signoff` flag of false.

Assembling a bag moves it from `DRAFT` to `ASSEMBLED` and requires that `line_items` be non-empty and that every item's `qty` be at least 1. Assembly recomputes both the bag's value and its pharmacy flag and increments the bag's `version`. The **valuation** is computed line by line, with each line's value rounded to a whole cent *before* the lines are summed — round-then-sum, never sum-then-round, since for bags with multiple half-cent lines the two orders can diverge by one or more cents. For a single line, multiply its `qty` by its `unit_value_cents` by a category multiplier, then round that product half-up to an integer number of cents. The category multipliers are: `FORMULA` at 1.00, `DIAPERS` at 1.00, `CARSEAT_VOUCHER` at 1.00, `MEDICATION` at 1.05 (a 5 percent handling surcharge), and `EDUCATION` at 0.00 (educational handouts are free). The bag's `total_value_cents` is the sum of these per-line rounded values. The `requires_pharmacy_signoff` flag is set to true exactly when any line item's `category` is `MEDICATION`.

Issuing a bag moves it from `ASSEMBLED` to `ISSUED`. Issuance requires that the bag be `ASSEMBLED`, and that the infant not already have any other bag in `ISSUED` status. When a bag carries the pharmacy flag — that is, when `requires_pharmacy_signoff` is true because a medication line is present — the issue request must carry `pharmacy_signoff` equal to true; issuing such a bag without that sign-off is rejected with `ERR_PHARMACY_SIGNOFF_REQUIRED`. Separately, attempting to issue a bag for an infant that already has another `ISSUED` bag is rejected with `ERR_BAG_ALREADY_ISSUED`. A successful issue journals a `BAG_ISSUED` audit event and increments the bag's `version`.

A bag issued in error can be **recalled** as compensation, moving it from `ISSUED` to `RECALLED`, which restores the no-issued-bag condition so that discharge is re-gated. Recall is permitted only while the infant is not yet `DISCHARGED` — a bag cannot be recalled after the infant has been released, and an attempt to do so is rejected with `ERR_INVALID_STATE` — and it increments the bag's `version`. `RECALLED` is the bag's terminal state.

### 3.7. Government Filings: Birth Certificate and SSN Application

A `VitalRecordsOfficer` files two kinds of paperwork for each infant, distinguished by the `filing_type` discriminator: a `BIRTH_CERTIFICATE` and an `SSN_APPLICATION`. A filing is created for a `newborn_id` and its given `filing_type`, beginning in `PENDING`. At creation the server computes the statutory `filing_deadline` from the infant's `birth_datetime` as a full ISO 8601 UTC instant that preserves the birth time-of-day: a birth-certificate filing is due exactly 5 calendar days after the birth instant, and an SSN-application filing is due exactly 365 calendar days after the birth instant. A filing carries a `submitted_at` (null until it is transmitted), an `acknowledged_at` (null until the agency responds), and a `reference_number` — the agency-issued certificate number or SSN-application receipt — which stays null until acceptance.

Submitting a filing transmits it to the agency. Submission is gated on two preconditions, each with its own rejection. First, the infant's `legal_name` must be non-null; submitting while the name is still null is rejected with `ERR_LEGAL_NAME_REQUIRED`. (The nurse or vital-records officer may set `legal_name` on the newborn at any time before filing.) Second, for an `SSN_APPLICATION` only, the same infant's `BIRTH_CERTIFICATE` filing must already be in `SUBMITTED`, `LATE_FLAGGED`, or `ACCEPTED`; submitting an SSN application before its companion birth certificate has at least been submitted is rejected with `ERR_BIRTH_CERT_PREREQUISITE`. On a valid submission the server stamps `submitted_at` with the current clock, and the outcome branches on lateness: a filing is late when its `submitted_at` is strictly after its `filing_deadline`. A timely submission moves the filing from `PENDING` to `SUBMITTED` and journals a `FILING_SUBMITTED` audit event. A late submission instead moves the filing from `PENDING` to `LATE_FLAGGED` and journals a `FILING_LATE_FLAGGED` audit event. A `LATE_FLAGGED` filing still satisfies the SSN birth-certificate prerequisite, but it does *not* satisfy the discharge prerequisite, which accepts only `SUBMITTED` or `ACCEPTED`. Every submission increments the filing's `version`.

Acknowledging a filing records the agency's response. The acknowledge request carries an `outcome` indicating acceptance or rejection — one of the literal values `ACCEPTED` or `REJECTED` — and a `reference_number` on acceptance. Acknowledging a filing as accepted requires a `reference_number` in the request; it stores that reference and stamps `acknowledged_at` with the current clock, moving a `SUBMITTED` filing or a `LATE_FLAGGED` filing to `ACCEPTED`. Acknowledging a filing as rejected applies to a filing in `SUBMITTED` or `LATE_FLAGGED`, stamps `acknowledged_at`, and moves it to `REJECTED`. A `REJECTED` filing may be **resubmitted**: submitting again moves it from `REJECTED` back to `SUBMITTED` (this revision loop again requires a non-null `legal_name`, and for an `SSN_APPLICATION` again requires the companion birth-certificate prerequisite), re-stamps `submitted_at`, and increments the `version`, making the filing lifecycle cyclic. The lateness branch above applies only to a first submission out of `PENDING`; a resubmission out of `REJECTED` always lands in `SUBMITTED` and journals `FILING_SUBMITTED` regardless of whether the re-stamped `submitted_at` falls after the `filing_deadline`. Each acknowledge transition also increments the filing's `version`.

A filing may be cancelled only while it is still `PENDING`, moving it from `PENDING` to `CANCELLED` and incrementing the `version`; once a filing has been submitted, late-flagged, accepted, or rejected it follows the acknowledge and resubmit paths instead. The filing's terminal states are `ACCEPTED` and `CANCELLED`.

### 3.8. Discharge Readiness and Release

An infant is released only when it is clinically and administratively ready, and readiness is measured by a computed index, the `discharge_readiness_score`, that runs from 0 to 100. The score is the capped sum of four independent contributions, each evaluated on its own and then added together, with the total finally limited to no more than 100. The first contribution is a tiered weight term: 40 points when `weight_grams` is 2500 or more, otherwise 25 points when it is 2000 or more, otherwise 10 points when it is 1800 or more, otherwise 0 points. The second is a feeding term worth 30 points when at least one lactation consult for this infant is `COMPLETED` with its `feeding_adequate` true, and 0 points otherwise. The third is a NICU-clearance term worth 20 points when the infant has no open stay — that is, no stay in `PENDING_BED` and none in `ACTIVE` — and 0 points otherwise. The fourth is a filing term worth 10 points when a `BIRTH_CERTIFICATE` filing for this infant is in `SUBMITTED` or `ACCEPTED`, and 0 points otherwise. The four terms are summed and the result is capped at 100. This score is recomputed both when an infant is marked discharge-ready and whenever the infant is read.

Marking an infant **discharge-ready** is the `AttendingNurse`'s transition to `DISCHARGE_READY`, reachable from either `ROOMING_IN` or `STEP_DOWN`. In both cases the score is recomputed at the moment of the call and must be at least 70; a recomputed score below 70 is rejected with `ERR_READINESS_BELOW_THRESHOLD`. From `ROOMING_IN`, the infant must currently be in `ROOMING_IN` and meet the threshold. From `STEP_DOWN`, the infant must currently be in `STEP_DOWN`, must have no open stay (no stay in `PENDING_BED` or `ACTIVE`) — a lingering open stay is treated as an undefined transition and rejected with `ERR_INVALID_STATE` rather than a business-rule error — and must meet the threshold, the threshold being checked only after the open-stay guard passes. The transition recomputes the score and increments the newborn's `version`.

**Discharging** the infant is the final clinical transition, moving it from `DISCHARGE_READY` to `DISCHARGED`. Discharge is gated on two sibling prerequisites: exactly one discharge bag for the infant must be in `ISSUED`, and a `BIRTH_CERTIFICATE` filing for the infant must be in `SUBMITTED` or `ACCEPTED`. If either prerequisite is unmet, the discharge is rejected with `ERR_DISCHARGE_PREREQUISITE`. A successful discharge sets `care_location` to `RELEASED`, stamps `discharged_at` with the current clock, journals a `DISCHARGED` audit event, increments the newborn's `version`, and **spawns four follow-up tasks** for the nurse: one each of type `WEIGHT_CHECK`, `JAUNDICE_CHECK`, `FEEDING_CHECK`, and `SAFETY_CALL`, each created in `OPEN` with a computed deadline. `DISCHARGED` is the newborn's terminal clinical state; the recognized clinical statuses are `BORN`, `ROOMING_IN`, `NICU_ADMITTED`, `STEP_DOWN`, `DISCHARGE_READY`, and `DISCHARGED`, and the recognized care locations are `WELL_BABY_NURSERY`, `MOTHER_ROOM`, `NICU`, `STEP_DOWN_UNIT`, and `RELEASED`.

### 3.9. Nurse Follow-Up After Release

The four follow-up tasks spawned at discharge each carry a `task_type`, a server-computed `due_at` deadline, a `scheduled_at` time the nurse plans the contact (null until set), and an `attempt_count` starting at 0. Each task's `due_at` is measured from the infant's `discharged_at` plus a per-type service-level window: a `WEIGHT_CHECK` is due 48 hours after discharge, a `JAUNDICE_CHECK` 72 hours after, a `FEEDING_CHECK` 120 hours after, and a `SAFETY_CALL` 168 hours after. The valid task statuses are `OPEN`, `ATTEMPTED`, `COMPLETED`, `ESCALATED`, `MISSED`, and `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal.

The nurse works a task by **recording attempts**. Recording an attempt is allowed while the task is `OPEN` or `ATTEMPTED`; it increments `attempt_count` by 1 and, when the request supplies a `scheduled_at`, sets `scheduled_at` from the request (an omitted `scheduled_at` leaves the existing value untouched rather than clearing it), then increments the task's `version`. The first recorded attempt moves an `OPEN` task to `ATTEMPTED`. Subsequent attempts loop on `ATTEMPTED` as long as the count after incrementing remains below 3. The attempt whose post-increment `attempt_count` reaches exactly 3 moves the task from `ATTEMPTED` to `ESCALATED` and journals a `FOLLOWUP_ESCALATED` audit event — three consecutive missed contacts escalate the task. A nurse may instead **complete** a task that is `OPEN` or `ATTEMPTED`, moving it to `COMPLETED` and incrementing its `version`. A task may also be **marked missed**, moving an `OPEN` or `ATTEMPTED` task to `MISSED`; this is permitted only once the current clock is strictly past the task's `due_at`, and it increments the task's `version`.

### 3.10. Adding the Newborn as an Insurance Dependent

In parallel with the clinical and filing workflows, the `BenefitsCoordinator` adds the newborn to a parent's coverage within the thirty-day special-enrollment period. An **insurance policy** is created with a `carrier_name`, a `subscriber_name` (the parent's legal name), a `plan_type` that is one of `EMPLOYER_GROUP`, `MARKETPLACE`, or `MEDICAID`, a `coverage_effective_date`, and a `dependent_slots_max` cap of at least 1 on how many dependents may be added. The policy tracks `dependents_added_count`, the number of its enrollments currently in `ENROLLED`, recomputed as enrollments come and go.

A **dependent enrollment** is created for a `newborn_id` and a `policy_id` with the `requested_at` instant at which the add request was submitted. On creation the server computes the `sep_deadline` — the close of the special-enrollment period — from the infant's `birth_datetime` plus 30 calendar days, with the time component of the birth instant preserved in that raw deadline. The deadline then takes one of two plan-driven variants. For a `MARKETPLACE` policy the deadline is the hard birth-plus-30-calendar-days instant, with no weekend roll and keeping the birth time-of-day. For an `EMPLOYER_GROUP` or `MEDICAID` policy the deadline rolls when the raw birth-plus-30-days instant lands on a weekend: if it falls on a Saturday or a Sunday, the deadline rolls forward to 23:59:59.999Z on the following Monday, extending the window; if it falls on any weekday, the raw deadline stands unchanged. An enrollment is within its window exactly when its `requested_at` is at or before the `sep_deadline`, with the boundary instant inclusive. A new enrollment begins in `PENDING` with a null `retroactive_effective_date`; the valid enrollment statuses are `PENDING`, `ENROLLED`, `SEP_EXPIRED`, `DENIED`, and `TERMINATED`, with the last three terminal.

**Approving** an enrollment moves it from `PENDING` to `ENROLLED`. Approval carries the `expected_policy_version` concurrency guard from §2.7 and is subject to two further business gates evaluated against the policy and the window. If the enrollment's `requested_at` is strictly after its `sep_deadline`, the window has closed and the approval is rejected with `ERR_SEP_WINDOW_CLOSED` — note that approving past the deadline does not silently expire the row; it is rejected and the enrollment stays `PENDING`. If the governing policy's count of `ENROLLED` dependents already equals its `dependent_slots_max`, the approval is rejected with `ERR_DEPENDENT_SLOTS_EXHAUSTED`. Enrollment is independent of the infant's clinical state — an infant need not be discharged to be enrolled. A successful approval sets `retroactive_effective_date` to the calendar date of the infant's `birth_datetime` (coverage always backdates to the birth date when enrolled within the window), recomputes the policy's `dependents_added_count`, journals a `DEPENDENT_ENROLLED` audit event, and increments the policy's `version`.

A `PENDING` enrollment whose window has already passed may be **explicitly expired** by the coordinator, moving it from `PENDING` to `SEP_EXPIRED`; this transition is the deliberate close of a lapsed request, requires that the `requested_at` be strictly after the `sep_deadline` — attempting to expire an enrollment still within its window is rejected with `ERR_INVALID_STATE` — journals a `SEP_EXPIRED` audit event, and increments the `version`. A `PENDING` enrollment may instead be **denied**, moving it from `PENDING` to `DENIED` and incrementing the `version`. An `ENROLLED` enrollment may be **terminated** as compensation for an erroneous enrollment, moving it from `ENROLLED` to `TERMINATED`; termination recomputes the policy's `dependents_added_count` (releasing the slot back to the policy) and increments the `version`.

### 3.11. Validation Ordering

When several checks could fire on a single request, they are evaluated in a fixed precedence so that the most fundamental failure surfaces first. Authentication comes first: a missing header or unknown role yields `ERR_UNAUTHENTICATED`. Authorization comes next: a known role that is not permitted for the operation yields `ERR_UNAUTHORIZED`. Then existence is checked — every path identifier and every body foreign key, left to right, with any unresolved reference yielding `ERR_NOT_FOUND`. Then the request body is validated for well-formedness, required fields, and correct types and enum values, with violations yielding `ERR_INVALID_REQUEST`. Only then is the state check applied: an action whose transition is not defined from the target resource's current state yields `ERR_INVALID_STATE`. After the state check, on the two guarded writes, the optimistic-concurrency comparison of §2.7 applies and a mismatch yields `ERR_STALE_VERSION`. The domain-specific business rules — NICU criteria, pharmacy sign-off, the birth-certificate prerequisite, the discharge prerequisite, the legal-name requirement, the SEP window, the readiness threshold, duplicate birth sequence, the active-stay requirement for step-down, dependent-slot exhaustion, the bed-interval overlap, the consult buffer, the admit window, and the already-issued bag — are evaluated after these foundational checks. This ordering guarantees, for example, that an unauthenticated request is never told it has the wrong state, and that a request against a missing resource is never told its payload is malformed.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a registration, a newborn, a policy, a consult, a bed, a stay (via escalation), a bag, a filing, or a dependent enrollment — return a `201 Created` status code. Operations that modify an existing resource, including all state-transition actions and reads, return a `200 OK` status code. All endpoints are mounted as top-level collections with no shared path prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock to a supplied instant for deterministic temporal tests | RegistrySupervisor |
| POST | `/insurance-policies` | Create an insurance policy | BenefitsCoordinator, RegistrySupervisor |
| GET | `/insurance-policies/{id}` | Read an insurance policy | BenefitsCoordinator, RegistrySupervisor |
| GET | `/insurance-policies/{id}/dependent-enrollments` | List dependent enrollments under a policy; filter by status | BenefitsCoordinator, RegistrySupervisor |
| POST | `/registrations` | Create a pre-registration in DRAFT | IntakeClerk |
| GET | `/registrations/{id}` | Read a pre-registration | IntakeClerk, AttendingNurse, RegistrySupervisor |
| GET | `/registrations` | List pre-registrations; filter by payer_policy_id or status | IntakeClerk, RegistrySupervisor |
| POST | `/registrations/{id}/submit` | Submit a draft pre-registration | IntakeClerk |
| POST | `/registrations/{id}/admit` | Admit a submitted pre-registration (admit-window gated) | IntakeClerk |
| POST | `/registrations/{id}/cancel` | Cancel a pre-registration with no newborns | IntakeClerk |
| POST | `/registrations/{id}/close` | Close a pre-registration once all newborns are discharged | RegistrySupervisor |
| POST | `/registrations/{id}/newborns` | Record a birth under a pre-registration | AttendingNurse |
| GET | `/registrations/{id}/newborns` | List newborns under a pre-registration | AttendingNurse, Neonatologist, RegistrySupervisor |
| GET | `/newborns/{id}` | Read a newborn (recomputes discharge readiness) | AttendingNurse, Neonatologist, BenefitsCoordinator, VitalRecordsOfficer, RegistrySupervisor |
| PATCH | `/newborns/{id}` | Update mutable newborn fields (legal name) | AttendingNurse, VitalRecordsOfficer |
| POST | `/newborns/{id}/room-in` | Room a newborn in with its mother | AttendingNurse |
| POST | `/newborns/{id}/nicu-escalate` | Escalate a newborn to the NICU (OCC-guarded) | Neonatologist |
| POST | `/newborns/{id}/step-down` | Step a newborn down from the NICU | Neonatologist |
| POST | `/newborns/{id}/mark-discharge-ready` | Mark a newborn discharge-ready | AttendingNurse |
| POST | `/newborns/{id}/discharge` | Discharge a newborn | AttendingNurse |
| GET | `/newborns/{id}/audit-events` | List audit events for a newborn; filter by event_type | RegistrySupervisor, AttendingNurse, Neonatologist |
| POST | `/lactation-consults` | Schedule a lactation consult for a newborn | AttendingNurse |
| GET | `/lactation-consults/{id}` | Read a lactation consult | AttendingNurse, RegistrySupervisor |
| GET | `/lactation-consults` | List lactation consults; filter by newborn_id or status | AttendingNurse, RegistrySupervisor |
| POST | `/lactation-consults/{id}/complete` | Complete a consult (records the latch score) | AttendingNurse |
| POST | `/lactation-consults/{id}/cancel` | Cancel a scheduled consult | AttendingNurse |
| POST | `/nicu-beds` | Register a NICU bed in the shared pool | Neonatologist, RegistrySupervisor |
| GET | `/nicu-beds/{id}` | Read a NICU bed | Neonatologist, RegistrySupervisor |
| GET | `/nicu-beds` | List NICU beds; filter by occupancy_status | Neonatologist, RegistrySupervisor |
| GET | `/nicu-beds/{id}/nicu-stays` | List stays that have occupied a bed; filter by status | Neonatologist, RegistrySupervisor |
| POST | `/nicu-beds/{id}/assign-stay` | Manually place a pending stay onto a bed | Neonatologist |
| GET | `/nicu-stays/{id}` | Read a NICU stay | Neonatologist, RegistrySupervisor |
| GET | `/nicu-stays` | List NICU stays; filter by newborn_id or status | Neonatologist, RegistrySupervisor |
| POST | `/nicu-stays/{id}/cancel` | Withdraw a not-yet-bedded escalation | Neonatologist |
| POST | `/discharge-bags` | Create a discharge bag for a newborn | AttendingNurse |
| GET | `/discharge-bags/{id}` | Read a discharge bag | AttendingNurse, RegistrySupervisor |
| GET | `/discharge-bags` | List discharge bags; filter by newborn_id or status | AttendingNurse, RegistrySupervisor |
| POST | `/discharge-bags/{id}/assemble` | Assemble a draft bag (recomputes value and pharmacy flag) | AttendingNurse |
| POST | `/discharge-bags/{id}/issue` | Issue an assembled bag | AttendingNurse |
| POST | `/discharge-bags/{id}/recall` | Recall an issued bag | AttendingNurse |
| GET | `/follow-up-tasks/{id}` | Read a follow-up task | AttendingNurse, RegistrySupervisor |
| GET | `/follow-up-tasks` | List follow-up tasks; filter by newborn_id, status, or task_type | AttendingNurse, RegistrySupervisor |
| POST | `/follow-up-tasks/{id}/record-attempt` | Record a contact attempt on a task | AttendingNurse |
| POST | `/follow-up-tasks/{id}/complete` | Complete a follow-up task | AttendingNurse |
| POST | `/follow-up-tasks/{id}/mark-missed` | Mark a follow-up task missed | AttendingNurse |
| POST | `/dependent-enrollments` | Create a dependent-add request | BenefitsCoordinator |
| GET | `/dependent-enrollments/{id}` | Read a dependent enrollment | BenefitsCoordinator, RegistrySupervisor |
| GET | `/dependent-enrollments` | List dependent enrollments; filter by newborn_id, policy_id, or status | BenefitsCoordinator, RegistrySupervisor |
| POST | `/dependent-enrollments/{id}/approve` | Approve a dependent enrollment (OCC-guarded) | BenefitsCoordinator |
| POST | `/dependent-enrollments/{id}/deny` | Deny a dependent enrollment | BenefitsCoordinator |
| POST | `/dependent-enrollments/{id}/expire` | Explicitly expire a lapsed pending enrollment | BenefitsCoordinator |
| POST | `/dependent-enrollments/{id}/terminate` | Terminate an enrolled dependent | BenefitsCoordinator |
| POST | `/government-filings` | Create a government filing | VitalRecordsOfficer |
| GET | `/government-filings/{id}` | Read a government filing | VitalRecordsOfficer, RegistrySupervisor |
| GET | `/government-filings` | List government filings; filter by newborn_id, filing_type, or status | VitalRecordsOfficer, RegistrySupervisor |
| POST | `/government-filings/{id}/submit` | Submit or resubmit a filing | VitalRecordsOfficer |
| POST | `/government-filings/{id}/acknowledge` | Acknowledge a filing as accepted or rejected | VitalRecordsOfficer |
| POST | `/government-filings/{id}/cancel` | Cancel a pending filing | VitalRecordsOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NICU_CRITERIA_MET` | 422 |
| `ERR_PHARMACY_SIGNOFF_REQUIRED` | 422 |
| `ERR_BIRTH_CERT_PREREQUISITE` | 422 |
| `ERR_DISCHARGE_PREREQUISITE` | 422 |
| `ERR_LEGAL_NAME_REQUIRED` | 422 |
| `ERR_SEP_WINDOW_CLOSED` | 422 |
| `ERR_READINESS_BELOW_THRESHOLD` | 422 |
| `ERR_DUPLICATE_BIRTH_SEQUENCE` | 409 |
| `ERR_NO_ACTIVE_NICU_STAY` | 422 |
| `ERR_DEPENDENT_SLOTS_EXHAUSTED` | 422 |
| `ERR_NICU_CRITERIA_NOT_MET` | 422 |
| `ERR_ADMIT_WINDOW_CLOSED` | 422 |
| `ERR_BAG_ALREADY_ISSUED` | 409 |
| `ERR_BED_INTERVAL_OVERLAP` | 409 |
| `ERR_CONSULT_BUFFER_CONFLICT` | 409 |
| `ERR_VALIDATION` | 422 |
