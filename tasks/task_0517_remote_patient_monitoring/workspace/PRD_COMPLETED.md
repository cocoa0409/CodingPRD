# Remote Patient Monitoring API — Product Requirements Document

## 1. Introduction

Chronic-care programs increasingly depend on data that arrives from a patient's home rather than a clinic visit. Remote Patient Monitoring (RPM) and Chronic Care Management (CCM) ask a small care team to enroll a patient, hand them connected devices, watch a stream of vitals for dangerous excursions, accumulate the care-management minutes that justify reimbursement, and ultimately turn that month of activity into a clean claim against a payer. This API is the system of record for that entire arc.

The product exists to keep three concerns in lockstep that are easy to let drift apart: clinical safety, billing integrity, and regulatory compliance. A vitals reading that crosses a threshold must reliably become an alert, and a critical alert must reliably become work in a provider's queue. The minutes a clinician spends coordinating care must be counted exactly once, capped fairly per day, and frozen the moment a billing month closes. And every dollar claimed must be backed by active patient consent, a closed calendar month, and a timely submission — or the claim must be refused before it ever reaches the payer.

Two design themes run through everything below. First, the system separates duties: the clinician who logs care minutes is structurally barred from signing the provider review that attests them, and the billing specialist who finalizes a claim cannot author care minutes. Second, the system is built around a *dual-variant* accounting model — a running, provisional view of a billing period that updates continuously, and a frozen, finalized view computed once when the month is sealed. The remainder of this document specifies the contracts, the cross-cutting principles, and the workflows that hold these themes together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled precisely as follows: `CareCoordinator`, `Clinician`, `Physician`, `BillingSpecialist`, and `PayerAgent`. A `CareCoordinator` manages patient enrollment, consents, device fitting, and vitals intake. A `Clinician` monitors vitals, triages alerts, and logs care-management minutes. A `Physician` authors and activates care plans and works the provider review queue. A `BillingSpecialist` administers payers, billing periods, finalization, and claim submission. A `PayerAgent` acts on behalf of the insurer to adjudicate claims and post remittances.

All five roles carry an **opaque identity**. In every case, `X-User-ID` is an operator identifier that is not tied to any persisted entity row — there is no "patient user" or "payer user" whose `id` the header must equal. The server may *record* the supplied `X-User-ID` where a workflow demands provenance: acknowledging an alert writes the caller's `X-User-ID` into `acknowledged_by_user_id` on the `ThresholdAlert`, claiming a review task writes it into `reviewer_user_id` on the `ReviewTask`, and a logged care-management block carries the performing clinician's identity in `clinician_user_id`. But the server never compares `X-User-ID` to any entity's own `id` for ownership. Where ownership-style checks exist (a physician may only sign a task they personally claimed; a signer may not have logged the patient's minutes), they compare these recorded user-id fields to one another, never to a primary key.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. A supplied `limit` that is not an integer or lies outside the 1–100 range, or a supplied `offset` that is not an integer or is negative, is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, every list endpoint returns resources sorted by their creation timestamp, `created_at`, in ascending order. The sole exception is the provider review queue, whose ordering is governed by the priority rules described in §3.

Each list response carries four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Most resources in the system are full first-class records and carry a standard set of system-managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that begins at its initial value and increments by one on every mutation; it underpins optimistic concurrency control (§2.7).

This full set applies to `Payer`, `Patient`, `CarePlan`, `Device`, `ThresholdAlert`, `ReviewTask`, `CareActivity`, `BillingPeriod`, `BillingLineItem`, and `Claim`. Two entities are deliberately lighter. A `ConsentRecord` and a `VitalsReading` are append-style records that carry only `id` and `created_at`; they do **not** carry `updated_at` and do **not** carry `version`. State changes that a consent or reading "undergoes" are modeled by writing their own system fields (for example a consent's `revoked_at` and `status`), not by an incrementing version, and these two entities never participate in optimistic concurrency.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a nested path — a patient, then a device under that patient, then readings under that device. The server validates the identifiers in a path strictly left-to-right and rejects the request at the first identifier that does not resolve, returning `ERR_NOT_FOUND`. A request for a device under a non-existent patient fails on the patient before the device is ever consulted. This same left-to-right discipline governs creation and action endpoints: the parent in the path is confirmed before any child.

Existence checks layer in a fixed order relative to one another. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then authorization (`ERR_UNAUTHORIZED`), then path-resource existence (`ERR_NOT_FOUND`). After the path resolves, the system confirms that every foreign key carried in the request body resolves to an existing entity — `payer_id`, `billing_period_id`, `device_id`, `vitals_reading_id`, and `threshold_alert_id` are all subject to this — failing with `ERR_REFERENCE_NOT_FOUND` when a referenced row is absent. Only then does the system check that all required body fields are present and of the declared type or enum domain, rejecting violations with `ERR_INVALID_REQUEST`. State-transition legality (`ERR_INVALID_STATE`) is evaluated after these structural checks, when the target entity is not in a state from which the requested transition is defined.

### 2.6. Hierarchical Consistency and Cascades

`Patient` is the aggregate root; `Device`, `ConsentRecord`, `CarePlan`, and `BillingPeriod` hang beneath it, while `VitalsReading`, `ThresholdAlert`, `CareActivity`, `BillingLineItem`, `ReviewTask`, and `Claim` cross-reference those records. A single operation frequently mutates more than one entity, and the system applies all such cascades immediately and consistently. Each entity touched by a cascade independently refreshes its own `updated_at` and increments its own `version`; the parent's version bump is never a substitute for the child's, and vice versa.

The `Patient` record is unusual in carrying **two independent status dimensions on the same row**: `enrollment_status` governs program membership and `monitoring_status` governs device data flow. These evolve separately, but specific transitions deliberately reach across the boundary — suspending an enrolled patient pauses active monitoring; activating the first device on an enrolled patient starts monitoring; returning the last active device pauses it. The precise mechanics live in §3, but the principle is fixed here: a cross-dimension cascade mutates the patient once and bumps `Patient.version` once for that change.

### 2.7. Optimistic Concurrency on Billing-Period Finalization

Finalizing a billing period is the one write in the system guarded by optimistic concurrency control. The finalize request must carry `expected_billing_period_version`, a non-optional field holding the `version` of the target `BillingPeriod` that the client last observed. The server compares it to the period's current `version`. If they differ, the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412).

This guard exists because an open period is a moving target: logging a care-management activity against it, or transmitting vitals that add a new device-day, legitimately mutates the period and advances its `version`. A finalize request still carrying the pre-mutation version is operating on a stale view of the period's accrued totals, so the system refuses it rather than freezing numbers the client never saw. No other endpoint accepts or requires a version field; only finalization participates in this check.

### 2.8. Care-Time Accounting: Provisional vs. Finalized

The system keeps two distinct views of a billing period's care-minute total, and the distinction matters everywhere money is computed. The **provisional** view, `provisional_total_minutes`, is a running figure recomputed every time a care-management activity is logged into an open period; it reflects only the activities present so far and is never frozen. The **finalized** view, `finalized_total_minutes`, is computed exactly once at finalize-time, over the activities then present, and is thereafter frozen — it starts as null and remains null until the period reaches `FINALIZED`. Because activities can be added or removed between the last provisional recompute and finalization, the two figures can legitimately diverge; the finalized figure is the one that drives billing. Both totals are expressed in whole integer minutes with no rounding. The companion frozen money figure, `finalized_total_cents`, is likewise null until finalization.

### 2.9. Threshold Bands and Breach Severity

Every transmitted vital is evaluated against the threshold band defined by the patient's currently `ACTIVE` care plan and the transmitting device's `device_type`. Comparisons on blood pressure, glucose, and pulse-oximetry are made on integer mmHg, mg/dL, and percentage values respectively; weight is compared to one decimal place using round-half-up. The bands are exact, and boundaries are inclusive exactly as stated below:

- **`BP_CUFF`**: a `WARNING` breach occurs when the systolic value is at least 140 or the diastolic value is at least 90; a `CRITICAL` breach occurs when the systolic value is at least 180 or the diastolic value is at least 120. A systolic of exactly 140 is a `WARNING` breach; 139 is not.
- **`GLUCOMETER`**: a `WARNING` breach occurs when the value is at least 250 or strictly below 70; a `CRITICAL` breach occurs when the value is at least 400 or strictly below 54.
- **`PULSE_OX`**: a `WARNING` breach occurs when the value is at most 92 and strictly greater than 88; a `CRITICAL` breach occurs when the value is at most 88. Pulse-oximetry never produces a high-side breach.
- **`WEIGHT_SCALE`**: a `WARNING` breach occurs when the value is at least the immediately prior reading plus 1.4 kilograms within the preceding 24 hours; a `WEIGHT_SCALE` reading is never `CRITICAL`.

When a reading falls into the `CRITICAL` band, that band wins over `WARNING`. If the reading enters any breach band the system sets `breach_flag` to true; otherwise it is false. If the patient has no `ACTIVE` care plan at the moment of transmission, there is no band to evaluate against and `breach_flag` is false, with no alert created.

### 2.10. Reimbursement, Settlement, and the Conserved-Value Ledger

Reimbursement rates are held on the `Payer` and quoted in integer cents: `rate_99453_cents` for the one-time device-setup/education code, `rate_99454_cents` for the device-supply/transmission unit, and `rate_99457_cents` for the first care-management 20-minute block. All money in the system is integer cents with no rounding.

A claim obeys a conserved-quantity invariant at all times: a claim's reimbursed amount plus its outstanding amount always equals the amount claimed, where the outstanding amount is the claimed amount minus the reimbursed amount. Posting a remittance moves value from outstanding into reimbursed without ever changing the claimed amount. It is therefore an absolute rule that the cumulative reimbursed amount may never exceed the claimed amount; a remittance that would push it above is refused with `ERR_REMITTANCE_EXCEEDS_CLAIM`. The settlement arithmetic and the resulting status transitions are detailed in §3.

### 2.11. Segregation of Duties

The role model is one of segregated duties, and two structural separations are enforced beyond simple role permissions. First, the `Physician` who signs a provider review task must be the same physician who claimed it — signing a task one did not personally claim is refused with `ERR_NOT_TASK_OWNER`. Second, and independently, the signing physician must not have personally logged any of the care minutes the task attests: the signer's `X-User-ID` must not equal the `clinician_user_id` of any care activity recorded for the same patient as the review task, and a violation is refused with `ERR_SEGREGATION_OF_DUTIES`. The intent is that the person attesting a patient's care cannot be a person who billed time against that same patient.

### 2.12. The Logical Clock

Every deadline, expiry, period-elapsed, and timestamp rule reads a single server-side logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time; before any explicit set call it holds precisely this default. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant; a missing, empty, or non-ISO-8601 `to_iso8601` is rejected with `ERR_INVALID_REQUEST`, and a successful set returns `200 OK` with an empty object in `data`. Because finalization eligibility ("the month has fully elapsed"), timely-filing windows, consent-coverage intervals, and the 24-hour weight-gain window all read this clock, tests drive time forward deliberately rather than relying on real time.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Patient: Payers, Patients, and Consent

The financial backdrop is established first. A `BillingSpecialist` registers a `Payer` with its organization `name`, a `payer_type` that selects the reimbursement schedule — one of `MEDICARE`, `MEDICARE_ADVANTAGE`, or `COMMERCIAL` — and the three integer-cent rates `rate_99453_cents`, `rate_99454_cents`, and `rate_99457_cents`, each of which must be zero or greater. Two further payer attributes shape downstream claims: `requires_active_consent`, a boolean that defaults to true, and `timely_filing_days`, an integer that defaults to 90 and must be at least 1. The latter is the number of days after a billing period's last calendar day within which a claim must be submitted.

A `CareCoordinator` then creates a `Patient`, supplying the patient's `payer_id`, a medical record number `mrn`, and a `full_name`. The referenced payer must exist or the create fails with `ERR_REFERENCE_NOT_FOUND`. The `mrn` must be non-empty and unique across all patients whose `enrollment_status` is one of `PENDING_CONSENT`, `ENROLLED`, or `SUSPENDED`; a collision against an active patient is refused with `ERR_DUPLICATE_RESOURCE`. A discharged patient's record number does not block reuse. Every new patient begins life with `enrollment_status` of `PENDING_CONSENT` and `monitoring_status` of `INACTIVE`, and its `care_plan_id` back-pointer — a convenience reference to the patient's current active plan — begins null.

Consent is recorded against the patient as a `ConsentRecord` carrying a `consent_type` (one of `RPM`, `CCM`, or `BOTH`) and an `effective_at` instant marking the moment the consent takes effect, inclusive. A new consent begins with `status` of `ACTIVE` and a null `revoked_at`. Recording a fresh consent when a prior `ACTIVE` consent already exists supersedes the old one: the prior record moves to `SUPERSEDED`. Revoking a consent sets its `status` to `REVOKED` and stamps `revoked_at` with the current logical-clock instant, which marks the end of the active interval exclusively. A patient's consent history is reachable by listing the consents under that patient.

### 3.2. Care Plans and the Revision Loop

A `Physician` drafts a care plan for a patient, supplying a `diagnosis_code` (the ICD-10 chronic-condition code the plan addresses), a free-text `goal_text`, and an optional `required_care_minutes` — the monthly care-minute target the plan commits to, which defaults to 20 and must be at least 20. The owning relationship lives on `patient_id`. A freshly drafted plan has `status` of `DRAFT`.

Activating a draft plan advances it from `DRAFT` to `ACTIVE`, but only if no other care plan for that patient is already `ACTIVE`; attempting to activate a second concurrent active plan without the supersede flag is refused with `ERR_ACTIVE_PLAN_EXISTS`. On activation the plan's `status` becomes `ACTIVE` and the patient's `care_plan_id` is set to the activated plan's `id`. The activation request accepts an optional `supersede` flag. When supersede is set, the activation is treated as a revision: the patient's prior `ACTIVE` plan transitions `ACTIVE → REVISED`, its `superseded_by_plan_id` is set to the newly activated plan's `id`, and that prior plan's version is bumped. This forms a revision loop across plan rows for the same patient — `DRAFT → ACTIVE → REVISED`, with the new plan now holding `ACTIVE`. The reverse navigation from a revised plan to its successor is the `superseded_by_plan_id` pointer; the successor is discoverable through the patient's care-plan list.

When a patient is discharged, any `ACTIVE` care plan is retired automatically: it transitions `ACTIVE → RETIRED`, the patient's `care_plan_id` is cleared to null, and the plan's version increments. `RETIRED` is terminal.

### 3.3. Enrollment, Suspension, and Discharge

The two patient status dimensions move through their own lifecycles, with enrollment governed by a `CareCoordinator` and monitoring moving largely as a system-driven consequence.

Enrolling a patient advances `enrollment_status` from `PENDING_CONSENT` to `ENROLLED` (and, for a previously suspended patient, from `SUSPENDED` back to `ENROLLED`). Enrollment readiness demands two things together: an `ACTIVE` consent record covering either `RPM` or `BOTH`, and an `ACTIVE` care plan for the patient. If either is missing the enroll is refused with `ERR_CONSENT_REQUIRED`, and the consent sub-condition is evaluated before the care-plan sub-condition. A successful enroll sets `enrollment_status` to `ENROLLED` and bumps `Patient.version`. When a suspended patient is resumed and at least one device with `status` of `ACTIVE` exists, monitoring is restored as a cross-dimension consequence: `monitoring_status` advances `PAUSED → MONITORING` and the patient's version increments for that change.

Suspension applies only to an enrolled patient. It moves `enrollment_status` from `ENROLLED` to `SUSPENDED`. If the patient was actively monitoring at the time, the suspension cascades across dimensions and moves `monitoring_status` from `MONITORING` to `PAUSED`; the patient's version increments. Care-time and vitals intake are gated on enrollment: transmitting vitals or logging a care activity requires the patient's `enrollment_status` to be `ENROLLED`, and an attempt while not enrolled is refused with `ERR_CONSENT_REQUIRED` — the same code used for the enroll-readiness failure.

Discharge is terminal for the enrollment dimension and may be invoked from any non-discharged state. It is blocked, however, if any billing period for the patient is still `OPEN` and has accrued provisional minutes greater than zero — that is, an open period with `provisional_total_minutes` above zero must be settled or emptied first, otherwise the discharge cannot proceed and the state guard rejects it. A successful discharge sets `enrollment_status` to `DISCHARGED`, forces `monitoring_status` to `INACTIVE`, and cascades over the patient's hardware: every device whose `status` is `ENROLLED` or `ACTIVE` is moved to `RETURNED`, and the active care plan is retired as described in §3.2. The patient's version increments. `DISCHARGED` is the terminal enrollment state.

### 3.4. Devices and the Start of Monitoring

A `CareCoordinator` enrolls a device for a patient by supplying its `device_type` — one of `BP_CUFF`, `GLUCOMETER`, `PULSE_OX`, or `WEIGHT_SCALE` — and its manufacturer `serial_number`. The serial number must be unique across devices whose `status` is `ENROLLED` or `ACTIVE`; a duplicate among active hardware is refused with `ERR_DUPLICATE_RESOURCE`. A newly enrolled device begins with `status` of `ENROLLED`, a null `activated_at`, and `setup_billed` false.

Activating a device requires that the device be `ENROLLED` and that the patient's `enrollment_status` be `ENROLLED`. Activation advances the device `ENROLLED → ACTIVE`, stamps `activated_at` with the current clock instant, and bumps the device's version. Two consequences follow. First, if the patient's `monitoring_status` was `INACTIVE`, the activation of this first device starts monitoring as a cross-entity cascade, advancing `monitoring_status` `INACTIVE → MONITORING` and bumping the patient's version. Second, activation attempts to accrue the one-time setup charge: if the device's `setup_billed` is still false, the system resolves the patient's `OPEN` billing period for the activation month (the period whose `period_year` and `period_month` match the calendar year and month of the clock at activation). If such an open period exists, a billing line item is created with `cpt_code` of `CPT_99453`, `units` of 1, and `amount_cents` equal to the payer's `rate_99453_cents`, and `setup_billed` is set true so the device can never accrue a second setup charge. If no open period exists for the activation month, the setup accrual is simply deferred and not created — the system never auto-creates a period to hold it.

A device may be returned from either `ENROLLED` or `ACTIVE`, moving it to `RETURNED` and incrementing its version. When an `ACTIVE` device is returned and no remaining device for that patient is `ACTIVE`, monitoring pauses as a cross-entity cascade: `monitoring_status` moves to `PAUSED`. `RETURNED` is terminal for a device.

### 3.5. Vitals Capture, Breach Detection, and Alerts

A `Clinician` or `CareCoordinator` transmits a vitals reading for a patient by supplying the transmitting `device_id`, the primary `reading_value`, an optional `secondary_value` (for example the diastolic figure on a blood-pressure reading, which defaults to null), and the `measured_at` instant at which the device took the measurement. The patient must be `ENROLLED` for the transmission to be accepted, per the gate in §3.3. On creation the system derives `service_date`, the UTC calendar date (formatted `YYYY-MM-DD`) extracted from `measured_at`, which is the device-day the reading counts toward.

The reading is then evaluated for a breach against the bands defined in §2.9, setting `breach_flag` accordingly. When a breach is detected, the system creates a `ThresholdAlert` linked to the reading. The alert references the breaching reading through `vitals_reading_id` and the subject through `patient_id`, derives its `severity` band — `WARNING` or `CRITICAL` — from the breach, and begins with `status` of `OPEN` and a null `acknowledged_by_user_id`. A reading that enters the `WARNING` band but not the `CRITICAL` band produces a `WARNING` alert, which is not eligible for escalation. A reading entering the `CRITICAL` band produces a `CRITICAL` alert, which is eligible for escalation into the review queue.

Transmitting a reading also keeps the owning open period's device-day count current. The system recomputes the period's `distinct_device_days` — the count of distinct `service_date` values across the patient's devices within the period's month — and when a transmission introduces a new device-day, the period is mutated and `BillingPeriod.version` increments. This is one of the legitimate version-advancing writes that the finalize OCC guard in §2.7 is designed to catch. A patient's readings are listable per patient and per device.

### 3.6. Alert Triage and the Provider Review Queue

Alerts flow through a branching lifecycle owned by clinical staff. A `Clinician` acknowledges an `OPEN` alert, advancing it `OPEN → ACKNOWLEDGED` and recording the caller's `X-User-ID` in `acknowledged_by_user_id`; the alert's version increments.

Escalation is the safety-critical branch and is permitted only on a `CRITICAL` alert. A `Clinician` may escalate an alert that is either `OPEN` or `ACKNOWLEDGED`, advancing it to `ESCALATED`; an escalate attempted on a non-critical alert is refused with `ERR_ESCALATION_NOT_PERMITTED`. Escalation cascades the creation of a new `ReviewTask` linked to this alert through `threshold_alert_id`, carrying the subject `patient_id`, a `priority` of `URGENT`, a `status` of `QUEUED`, a null `escalated_from_task_id`, and a null `reviewer_user_id`. A review task's `priority` is `URGENT` whenever the source alert's severity is `CRITICAL`, and `ROUTINE` otherwise.

Resolution closes out an alert from `ACKNOWLEDGED → RESOLVED`, but only when no linked review task is still in `QUEUED`, `IN_REVIEW`, or `ESCALATED`; an attempt to resolve while such an open task exists is refused with `ERR_OPEN_REVIEW_TASK`. `RESOLVED` is terminal for an alert.

The provider queue belongs to the `Physician`. Claiming a `QUEUED` task advances it `QUEUED → IN_REVIEW` and records the claiming physician's `X-User-ID` in `reviewer_user_id`. Claiming also performs a de-escalation cascade: if the linked `ThresholdAlert` is currently `ESCALATED`, the act of a provider taking ownership reverts the alert `ESCALATED → ACKNOWLEDGED`, bumping the alert's version. Signing a task advances it `IN_REVIEW → SIGNED` and is the attestation step; it is guarded by the two segregation rules of §2.11 — the signer must be the same physician who claimed it (`reviewer_user_id` must equal the caller's `X-User-ID`, else `ERR_NOT_TASK_OWNER`) and the signer must not have logged any of the patient's care minutes (else `ERR_SEGREGATION_OF_DUTIES`). `SIGNED` is terminal. Alternatively, an in-review task may be escalated further, advancing `IN_REVIEW → ESCALATED` and spawning a fresh child review task: the child carries `escalated_from_task_id` set to the originating task's `id`, the same `threshold_alert_id` and `patient_id` as its parent, a `priority` of `URGENT`, and a `status` of `QUEUED`, forming a self-referential escalation chain. Each transition increments the task's version.

When a physician pulls the queue filtered to queued tasks, ordering is deterministic and never involves a random identifier: `URGENT` tasks come before `ROUTINE` tasks, and within a single priority band tasks are ordered by ascending `created_at`, with the review task's own `created_at` as the final deterministic tie-break.

### 3.7. Logging Care Minutes and the Daily Cap

Care-management minutes are logged by a `Clinician` or `Physician` against an open billing period. A care activity carries the `billing_period_id` of the open period it accrues into, the performing `clinician_user_id`, an `activity_type` (one of `REVIEW`, `OUTREACH`, `CARE_COORDINATION`, or `EDUCATION`), a `minutes` count that must be at least 1 and at most 120, and a `performed_at` instant marking when the care work occurred. The patient must be `ENROLLED` (§3.3). The referenced period must be `OPEN`; logging against a period in any other state is refused with `ERR_INVALID_STATE`. The `performed_at` instant must fall inside the billing period's calendar month, otherwise the log is refused with `ERR_ACTIVITY_OUT_OF_PERIOD`.

Each activity's `counted_minutes` is derived under a per-calendar-day cap of 60 minutes. Minutes are grouped by the UTC calendar date of `performed_at`. When the sum of logged minutes on a given day does not exceed 60, every activity that day counts in full. When a day's logged minutes exceed 60, the 60-minute allowance is allocated to that day's activities in ascending `performed_at` order, with ties broken by ascending `created_at`, filling the earliest activities first; once the day's allowance is exhausted, later activities on that day receive zero `counted_minutes`. The period total is the sum of `counted_minutes` over all care activities whose `performed_at` falls within the billing month and whose `billing_period_id` is the period — activities belonging to any other period are excluded. After each care-activity create the system recomputes and writes the period's `provisional_total_minutes` over the rows present so far (the provisional view of §2.8), mutating the period and incrementing `BillingPeriod.version`. Care minutes are counted as whole integers with no rounding. A patient's activities are listable per patient and per billing period.

### 3.8. Opening and Finalizing a Billing Period

A `BillingSpecialist` opens a monthly billing period for a patient by supplying `period_year` (at least 2024) and `period_month` (1 through 12). A new period must not collide with an existing non-`REOPENED` period for the same patient on the same year-and-month: the month is treated as the half-open calendar interval from the first day at `00:00Z` up to but not including the first day of the next month, and two periods collide when their month intervals are identical. A collision is refused with `ERR_PERIOD_OVERLAP`. A new period begins with `status` of `OPEN`, `provisional_total_minutes` of 0, `distinct_device_days` of 0, and both `finalized_total_minutes` and `finalized_total_cents` null.

Finalization seals the month. It requires the period to be `OPEN`, requires the supplied `expected_billing_period_version` to match the period's current `version` (the OCC guard of §2.7, which yields `ERR_STALE_VERSION` on mismatch), and requires that the calendar month identified by `period_year` and `period_month` has fully elapsed relative to the logical clock — finalizing before the month has closed is refused with `ERR_PERIOD_NOT_CLOSED`. On a successful finalize the system computes `finalized_total_minutes` as the frozen variant of the care-time aggregation (§3.7) and then accrues the eligible CPT line items in a pinned order against the period:

1. The 99454 device-supply unit is eligible if and only if `distinct_device_days` is at least 16 — exactly 16 distinct days qualifies, 15 does not. Here `distinct_device_days` counts distinct `service_date` values over readings whose `patient_id` matches the period's patient and whose `service_date` falls within the period's month.
2. The 99457 care-management block is eligible if and only if `finalized_total_minutes` is at least 20 — exactly 20 minutes qualifies, 19 does not. The 99457 line accrues independently of whether 99454 accrued.
3. The 99453 one-time setup is *not* re-accrued at finalize; it is accrued once per device at device-activation time as described in §3.4.

For each eligible code the system creates a `BillingLineItem` with `cpt_code` set to `CPT_99454` or `CPT_99457` respectively, `units` of 1, and `amount_cents` snapshotting the payer's rate for that code (`rate_99454_cents` or `rate_99457_cents`). The period's `finalized_total_cents` is then set to the sum of the `amount_cents` of all `ACCRUED` line items, those line items are flipped `ACCRUED → FINALIZED`, the period's `status` becomes `FINALIZED`, and its version increments. A line item begins life with `status` of `ACCRUED` and may later be `FINALIZED` or `VOIDED`.

### 3.9. Reopening, Claiming, and the Settlement Cycle

A finalized period that has no live claim may be reopened by a `BillingSpecialist`: reopen is permitted only when no claim exists for the period in any status other than `DENIED`. Reopening voids every `FINALIZED` line item for the period (moving them `FINALIZED → VOIDED`), clears `finalized_total_minutes` and `finalized_total_cents` back to null, and sets the period's `status` to `REOPENED`. A reopened period may be finalized again, recomputing the frozen totals and re-accruing line items exactly as the first finalize did, returning the period to `FINALIZED`.

Submitting a claim transitions the period `FINALIZED → CLAIMED` and is the gate at which all pre-submission compliance is enforced. A claim may only be submitted on a `FINALIZED` period. Three checks guard submission. A period whose `finalized_total_cents` is zero — no eligible CPT line items — cannot be claimed, and the attempt is refused with `ERR_NOTHING_TO_CLAIM`. The claim's submission instant must fall within the payer's `timely_filing_days` of the period's last calendar day, otherwise it is refused with `ERR_TIMELY_FILING_EXPIRED`. And if the payer's `requires_active_consent` is set, an `ACTIVE` consent interval running from its `effective_at` up to but not including its `revoked_at` must fully contain the billing month: a consent whose `effective_at` is after the month start, or whose `revoked_at` is before the month end, leaves an uncovered gap and the submission is refused with `ERR_BILLING_CONSENT_GAP`. On a clean submission the system creates a `Claim` referencing the period through `billing_period_id`, copying the patient's `payer_id` onto the claim, with `claimed_cents` equal to the period's `finalized_total_cents`, `reimbursed_cents` of 0, `status` of `SUBMITTED`, and a serialized `expected_billing_period_version` field that is always null on a claim; the period moves to `CLAIMED` and its version increments.

Adjudication belongs to the `PayerAgent`. Accepting a submitted claim moves it `SUBMITTED → ACCEPTED`. Denying a submitted claim moves it `SUBMITTED → DENIED` and cascades the linked period back from `CLAIMED → FINALIZED` so it can be corrected and resubmitted. A denied claim may be resubmitted against a re-finalized period, moving it `DENIED → SUBMITTED` and resetting its `claimed_cents` to the period's current `finalized_total_cents` — this forms the resubmit cycle. The three submission compliance checks are evaluated in the order timely-filing, then billing-consent gap, then nothing-to-claim. Both a first submission and a resubmission are served by the same create endpoint and return `201 Created`, the resubmission reusing the existing denied claim row rather than minting a new one.

Remittances post against an accepted (or partially paid) claim, each supplying a `remittance_cents` amount that must be an integer of zero or greater. Given a posted remittance against a claim with claimed amount and prior reimbursed amount, the new reimbursed amount is the prior reimbursed amount plus the remittance. If the new reimbursed amount equals the claimed amount, the claim becomes `PAID`; if it is greater than zero but strictly less than the claimed amount, the claim becomes `PARTIALLY_PAID`. A remittance that would push the cumulative reimbursed amount above the claimed amount is refused with `ERR_REMITTANCE_EXCEEDS_CLAIM`, preserving the conserved-value invariant of §2.10. Concretely: from `ACCEPTED`, a remittance strictly between zero and the claimed amount moves the claim to `PARTIALLY_PAID` and records the new `reimbursed_cents`; a remittance bringing the total exactly to the claimed amount moves it to `PAID`; a remittance of zero against an `ACCEPTED` claim whose cumulative reimbursed amount is still zero leaves the claim's status unchanged. From `PARTIALLY_PAID`, a further remittance that brings the cumulative reimbursed amount exactly to the claimed amount adds to `reimbursed_cents` and moves the claim to `PAID`. `PAID` is terminal.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions — return a `200 OK` status code. All paths are mounted at the API root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/payers` | Register a payer with reimbursement rates | BillingSpecialist |
| GET | `/payers/{id}` | Fetch a payer | BillingSpecialist, CareCoordinator |
| GET | `/payers` | List payers (paginated) | BillingSpecialist, CareCoordinator |
| POST | `/patients` | Create a patient | CareCoordinator |
| GET | `/patients/{id}` | Fetch a patient (both status dimensions) | CareCoordinator, Physician, Clinician, BillingSpecialist |
| GET | `/patients` | List patients; filter by payer_id, enrollment_status | CareCoordinator, Physician, Clinician, BillingSpecialist |
| POST | `/patients/{id}/enroll` | Enroll or resume a patient | CareCoordinator |
| POST | `/patients/{id}/suspend` | Suspend an enrolled patient | CareCoordinator |
| POST | `/patients/{id}/discharge` | Discharge a patient | CareCoordinator |
| POST | `/patients/{id}/consents` | Record patient consent | CareCoordinator |
| GET | `/patients/{id}/consents` | List a patient's consent records | CareCoordinator, Physician, BillingSpecialist |
| POST | `/patients/{id}/consents/{consent_id}/revoke` | Revoke an active consent | CareCoordinator |
| POST | `/patients/{id}/care-plans` | Draft a care plan | Physician |
| GET | `/patients/{id}/care-plans` | List a patient's care plans; filter by status | Physician, CareCoordinator, Clinician |
| GET | `/care-plans/{id}` | Fetch a care plan | Physician, CareCoordinator, Clinician |
| POST | `/patients/{id}/care-plans/{plan_id}/activate` | Activate a draft care plan; supersede revises the active plan | Physician |
| POST | `/patients/{id}/devices` | Enroll a device for a patient | CareCoordinator |
| GET | `/patients/{id}/devices` | List a patient's devices; filter by status | CareCoordinator, Physician, Clinician |
| GET | `/devices/{id}` | Fetch a device | CareCoordinator, Physician, Clinician |
| POST | `/patients/{id}/devices/{device_id}/activate` | Activate an enrolled device | CareCoordinator |
| POST | `/patients/{id}/devices/{device_id}/return` | Return a device | CareCoordinator |
| POST | `/patients/{id}/vitals` | Transmit a vitals reading | Clinician, CareCoordinator |
| GET | `/patients/{id}/vitals` | List a patient's vitals readings; filter by device_id | Clinician, CareCoordinator, Physician |
| GET | `/devices/{id}/vitals` | List a device's vitals readings | Clinician, CareCoordinator, Physician |
| GET | `/alerts` | List threshold alerts; filter by patient_id, vitals_reading_id, status | Clinician, Physician, CareCoordinator |
| GET | `/alerts/{id}` | Fetch a threshold alert | Clinician, Physician, CareCoordinator |
| POST | `/alerts/{id}/acknowledge` | Acknowledge an open alert | Clinician |
| POST | `/alerts/{id}/escalate` | Escalate a critical alert; spawns an urgent review task | Clinician |
| POST | `/alerts/{id}/resolve` | Resolve an acknowledged alert | Clinician |
| GET | `/review-tasks` | Provider review queue; filter by status, priority, patient_id, threshold_alert_id, escalated_from_task_id | Physician |
| GET | `/review-tasks/{id}` | Fetch a review task | Physician |
| POST | `/review-tasks/{id}/claim` | Claim a queued task | Physician |
| POST | `/review-tasks/{id}/sign` | Sign an in-review task | Physician |
| POST | `/review-tasks/{id}/escalate` | Escalate an in-review task; spawns a child task | Physician |
| POST | `/patients/{id}/billing-periods` | Open a monthly billing period | BillingSpecialist |
| GET | `/patients/{id}/billing-periods` | List a patient's billing periods; filter by status | BillingSpecialist, CareCoordinator |
| GET | `/billing-periods/{id}` | Fetch a billing period with provisional and finalized totals | BillingSpecialist, CareCoordinator, Physician |
| POST | `/billing-periods/{id}/finalize` | Finalize a closed period (OCC-guarded) | BillingSpecialist |
| POST | `/billing-periods/{id}/reopen` | Reopen a finalized period with no live claim | BillingSpecialist |
| GET | `/billing-periods/{id}/line-items` | List a period's line items; filter by cpt_code, status | BillingSpecialist, CareCoordinator |
| POST | `/patients/{id}/care-activities` | Log a care-management minute block | Clinician, Physician |
| GET | `/patients/{id}/care-activities` | List a patient's care activities; filter by billing_period_id | Clinician, Physician, BillingSpecialist |
| GET | `/billing-periods/{id}/care-activities` | List a period's care activities | Clinician, Physician, BillingSpecialist |
| POST | `/billing-periods/{id}/claims` | Submit or resubmit a claim for a finalized period | BillingSpecialist |
| GET | `/billing-periods/{id}/claims` | List claims for a period; filter by status | BillingSpecialist, PayerAgent |
| GET | `/claims` | List claims; filter by payer_id, status | BillingSpecialist, PayerAgent |
| GET | `/claims/{id}` | Fetch a claim | BillingSpecialist, PayerAgent |
| POST | `/claims/{id}/accept` | Payer accepts a submitted claim | PayerAgent |
| POST | `/claims/{id}/deny` | Payer denies a submitted claim; reopens period to finalized | PayerAgent |
| POST | `/claims/{id}/remit` | Payer posts a remittance | PayerAgent |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied instant | BillingSpecialist, CareCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ESCALATION_NOT_PERMITTED` | 409 |
| `ERR_OPEN_REVIEW_TASK` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_TASK_OWNER` | 403 |
| `ERR_CONSENT_REQUIRED` | 409 |
| `ERR_PERIOD_NOT_CLOSED` | 409 |
| `ERR_ACTIVITY_OUT_OF_PERIOD` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_ACTIVE_PLAN_EXISTS` | 409 |
| `ERR_TIMELY_FILING_EXPIRED` | 409 |
| `ERR_BILLING_CONSENT_GAP` | 409 |
| `ERR_NOTHING_TO_CLAIM` | 409 |
| `ERR_REMITTANCE_EXCEEDS_CLAIM` | 422 |
