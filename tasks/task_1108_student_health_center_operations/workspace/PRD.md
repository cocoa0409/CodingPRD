# Student Health Center API — Product Requirements Document

## 1. Introduction

A campus student health center sits at the intersection of clinical care, public-health surveillance, and university finance. Students arrive for urgent visits, same-day triage, sports physicals, and travel-clinic consultations; behind every visit there is an insurance eligibility question, an immunization compliance posture that can block course registration, and a term-limited health-fee pool that partially subsidizes care. This document specifies the Student Health Center API, the system of record that ties those concerns together.

The API is mounted under `/shc` and is built around a small set of segregated operational roles — front-desk, nursing, clinical, pharmacy, billing, and health-administration staff — each of which sees only the slice of the workflow it owns. A logical clock, settable by the health administrator, drives every temporal rule in the system: deadline sweeps for immunization compliance, aging of issued invoices, expiry of insurance coverage, no-show detection, and closure of term funding pools. Because the same clock also gates compliance holds that ripple into scheduling and clearance decisions, deterministic time behavior is a first-class requirement, not a test convenience.

Three properties shape the design. First, **compliance posture is derived, never stored directly**: a student's hold state is recomputed whenever immunization records transition, invoices age past due, or payments clear, and it gates elective bookings and sports clearances in real time. Second, **money is adjudicated in two variants** — a provisional estimate at invoice generation and a final adjudicated split at issue — with a term health-fee pool debited through a pinned waterfall that subsidizes travel-clinic vaccinations. Third, **public-health reporting is segregated**: the clinician who confirms a communicable-disease case may never be the administrator who reports it, and reporting must occur within twenty-four hours of confirmation.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Once the headers are accepted, role authorization is enforced per endpoint; an authenticated caller whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN`.

The system recognizes seven roles, spelled exactly as follows: `Student`, `FrontDeskStaff`, `Nurse`, `Clinician`, `Pharmacist`, `BillingOfficer`, and `HealthAdmin`. `Any` is a pseudo-role used in §4 to indicate that every authenticated role may call the endpoint.

Identity semantics differ across roles. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` resource; ownership checks on any resource that references a `Student` compare the resource's foreign-key field (for example, an appointment's `student_id`) to `X-User-ID`, and a `Student` caller attempting to book or cancel an appointment for someone else is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `FrontDeskStaff`, `Nurse`, `Clinician`, `Pharmacist`, `BillingOfficer`, or `HealthAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for instance as `confirmed_by_user_id` and `reported_by_user_id` on a `DiseaseCase`, or as `created_by_user_id` on a `Referral` — but does not compare it to any entity's `id`. The pseudo-role `Any` has no identity of its own and simply marks endpoints that all seven concrete roles may read.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Deterministic Daily Sweep

Every temporal rule in this system — deadlines, grace periods, aging, expiry, business hours — is evaluated against a **logical clock**, never against wall-clock time. At startup the logical clock is initialized to exactly `2026-05-01T00:00:00Z`, and it advances only when a `HealthAdmin` operator sets it, supplying a `to_iso8601` timestamp. The clock must never fall back to wall-clock time on its own.

Setting the clock triggers a deterministic sweep that reconciles every time-driven state in a pinned order, with the student's compliance posture recomputed after each step and elective-appointment cancellations applied after each posture change:

1. **Invoice aging.** Every invoice in `ISSUED` or `PARTIALLY_PAID` whose `due_date` falls before the current logical date while `balance_cents` remains positive transitions to `OVERDUE`.
2. **Immunization deadlines.** Records still `PENDING` past their requirement's `deadline_date` move to `GRACE` (and further to `OVERDUE` once the grace window closes), with posture recomputed at each stage.
3. **Policy expiry.** Insurance policies in `UNVERIFIED` or `VERIFIED` whose `coverage_end` has passed transition to `EXPIRED`.
4. **No-show detection.** Appointments still `BOOKED` whose `scheduled_end` has passed transition to `NO_SHOW`.
5. **Pool closure.** A `HealthFeePool` in `OPEN` whose `term_end_date` has passed transitions to `CLOSED`; a `CLOSED` pool applies no further subsidies.

The sweep runs as a single deterministic pass in exactly this order whenever the clock is set, so that two operators setting the same `to_iso8601` always observe the same resulting state.

### 2.5. Common Resource Properties and Derived Consistency

Every primary resource in the system — students, insurance policies, immunization requirements and records, providers, on-call shifts, appointments, encounters, prescriptions, medication stocks, lab orders, disease cases, outbreak investigations, invoices, payments, referrals, and health-fee pools — carries a standard set of system-managed fields:

- **`id`** (string): a unique, server-generated identifier formatted as a UUID. The identifier expresses identity only; it is never used in any selector, ranking, or tie-break.
- **`created_at`** (string): an ISO 8601 timestamp in UTC with three fractional digits, captured when the resource is first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version`** (integer): a system-managed integer starting at 1 that increments on every mutation, including mutations that arrive as cascaded side effects from operations on other resources.

Several resources expose **computed** fields whose values are derived, never accepted from the client: a student's `compliance_posture` and `active_hold_types`; a medication stock's `on_hand` and `needs_reorder`; a pool's `spent_cents` and `exhausted`; an invoice's `charge_total_cents`, `subsidy_cents`, `insurer_pays_cents`, `patient_responsibility_cents`, and `balance_cents`. Whenever one of these derived values changes, the owning resource's `updated_at` is refreshed and its `version` is incremented, exactly as if a client had written to it directly.

### 2.6. Monetary Precision and Rounding

All monetary values in the system are integer cents. There is no floating-point money anywhere: copays, deductibles, charge lines, subsidies, payer splits, payments, pool budgets, and balances are all expressed in whole cents.

Where a calculation involves a fractional multiplication — the per-line travel-vaccine subsidy and the coinsurance share — the result is rounded to the nearest integer cent using **round half up**: a fractional part of exactly one-half rounds away from zero. All other arithmetic on monetary values is exact integer arithmetic with no rounding.

### 2.7. Nested Resource Retrieval and Existence Checking

The API enforces hierarchical, left-to-right validation for every request whose path contains one or more resource identifiers. Each identifier in the path is resolved in order, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before any later identifier is examined and before any body validation runs. The same `ERR_NOT_FOUND` applies to foreign-key references carried in the request body — a `student_id`, `provider_id`, `medication_stock_id`, or `requirement_id` that names no existing resource fails identically.

### 2.8. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control; no other endpoint accepts a version field.

The first is policy creation: a create-policy request must carry `expected_student_version`, the caller's last-observed `version` of the target student. If the student's current `version` has advanced beyond what the caller observed — for example because another policy was created in the meantime, superseding the prior one and bumping the student's version — the create is rejected with `ERR_STALE_STUDENT_VERSION` (HTTP 412), preventing the caller from unknowingly superseding a policy it has not seen.

The second is dose recording: a dose-recording request must carry `expected_record_version`, the caller's last-observed `version` of the immunization record. If the record's current `version` no longer matches — because another dose was recorded against it since the caller last read it — the request is rejected with `ERR_STALE_RECORD_VERSION` (HTTP 412), so the caller's view of `doses_received` and `dose_dates` is never silently overwritten.

Both OCC checks are evaluated after existence checks and **before** any business rule, so a stale-version rejection is never masked by a later validation failure.

### 2.9. Validation Ordering

When a single request violates several rules, the error the caller sees is determined by a fixed evaluation order, not by whichever check happens to run first:

1. **Authentication context** — missing or malformed `X-User-ID` / `X-User-Role` headers, rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — the role is not permitted on this endpoint, or a `Student` actor is acting on another student's appointment, rejected with `ERR_FORBIDDEN`.
3. **Existence** — path identifiers (left to right) and body foreign keys, rejected with `ERR_NOT_FOUND`.
4. **Stale-version (OCC)** — `expected_student_version` or `expected_record_version` mismatches, rejected with `ERR_STALE_STUDENT_VERSION` or `ERR_STALE_RECORD_VERSION`. These are checked before any business rule.
5. **State-machine preconditions** — the target resource is not in the state the action requires (a non-`BOOKED` appointment at check-in, a non-`OPEN` encounter at close, and so on), rejected with the transition's specific `409` error.
6. **Compliance and safety gates** — elective bookings under a `REGISTRATION_HOLD`, clearance while the posture is not `CLEAR`, a late case report, a reporter who is also the confirmer.
7. **Temporal rules** — inverted time ranges, appointments in the past, same-day-triage mis-dating, slot and on-call conflicts, dose-interval violations, expired policies at verify, after-hours referrals with no covering shift.
8. **Referential coherence** — a reportable result on a lab order that carries no `reportable_disease_code`.
9. **Uniqueness and cardinality** — duplicate external references, vaccine codes, medication codes, an already-`OPEN` pool, a second non-terminal immunization record for the same student and requirement, a second invoice for an encounter, an invoice on a fee-covered encounter, a student-plan policy for a non-enrolled student, and the daily triage quota.
10. **Fiscal gates** — travel-clinic bookings without a verified policy, stock sufficiency and quantity bounds, and payment amounts against the outstanding balance. These are checked last.

A concrete consequence: an elective appointment booking that would violate both the compliance hold and the triage quota surfaces `ERR_COMPLIANCE_HOLD_ACTIVE`, because the compliance gate (step 6) is evaluated before the cardinality gate (step 9).

## 3. Business Logic & Workflows

### 3.1. Registering Students and the Compliance Posture

A `HealthAdmin` operator registers each student by supplying the campus `external_ref` (the university student number, unique across all students — a duplicate registration is rejected with `ERR_DUPLICATE_STUDENT_REF`) together with the student's `full_name`. An optional `enrollment_status` may be provided at registration; when omitted it defaults to `ENROLLED`, and it may later take the values `LEAVE` or `WITHDRAWN` as the student's academic standing changes.

Every student carries two derived compliance attributes that no client ever writes directly. The first, `compliance_posture`, summarizes the student's standing with the health center and takes one of three values: `CLEAR`, `PROVISIONAL_HOLD`, or `REGISTRATION_HOLD`. The second, `active_hold_types`, lists which hold sources are currently contributing — the set may contain `IMMUNIZATION`, `FINANCIAL`, both, or neither. At registration both are initialized benignly: the posture is `CLEAR` and the hold-type list is empty.

The posture derivation runs over all of the student's immunization records and invoices against the current logical date. A record in `OVERDUE` status imposes an immunization hold. Failing that, a record in `GRACE` status imposes a provisional hold. Independently, any invoice of the student sitting in `OVERDUE` imposes a financial hold. The posture is `REGISTRATION_HOLD` whenever either an immunization hold or a financial hold is present; it is `PROVISIONAL_HOLD` when no registration-level hold exists but at least one record is in grace; otherwise it is `CLEAR`. The `active_hold_types` set contains `IMMUNIZATION` exactly when an immunization hold is present and `FINANCIAL` exactly when a financial hold is present — so a student with both an overdue record and an overdue invoice shows both entries, while a grace-period student shows neither (a provisional hold contributes no entry to the set).

This derivation is re-evaluated every time its inputs can change: the daily clock sweep, a dose being recorded, an exemption being granted, an invoice transitioning to `OVERDUE`, and a payment or void altering an invoice's balance. Two downstream gates consume the posture, and they are stated where they apply below — elective bookings in §3.4 and sports clearance at encounter close in §3.5.

### 3.2. Insurance Policies: Creation, Supersession, and Verification

A `BillingOfficer` registers an insurance policy for a student, supplying `student_id`, the `payer_type` (either `STUDENT_PLAN` for the university-sponsored plan or `EXTERNAL` for an outside insurer), the payer's `policy_number`, the coverage window as `coverage_start` and `coverage_end` (both inclusive ISO 8601 timestamps, where the end must be strictly later than the start — an inverted window is rejected with `ERR_INVALID_TIME_RANGE`), and the plan's cost-sharing terms: `copay_cents` and `deductible_cents` as non-negative integer cents, plus `coinsurance_pct`, the patient's fractional coinsurance share between 0 and 1 inclusive, applied after copay and deductible.

Creation is a **superseding** operation. When a new policy is created for a student who already has one in `UNVERIFIED` or `VERIFIED` status, the older policy transitions automatically to `SUPERSEDED`. The act of supersession is a mutation on the student aggregate and therefore increments the student's `version` by one; combined with the OCC rule in §2.8, this means a second create issued with a stale `expected_student_version` fails rather than silently stacking supersessions. The newly created policy always starts in `UNVERIFIED` with `verified_at` unset, and its `deductible_met_cents` accumulator starts at zero.

Verification is a separate `BillingOfficer` action with three preconditions, evaluated in order. The policy must currently be `UNVERIFIED` — verifying anything else is rejected with `ERR_POLICY_NOT_UNVERIFIED`. The coverage window must still be live: a policy whose `coverage_end` has passed the current logical time is rejected with `ERR_POLICY_EXPIRED`. And for the `STUDENT_PLAN` payer type specifically, the covered student's `enrollment_status` must be `ENROLLED` at verify time — a student-plan policy for a student on leave or withdrawn is rejected with `ERR_POLICY_NOT_ELIGIBLE`. A successful verify stamps `verified_at` with the current logical time and moves the policy `UNVERIFIED → VERIFIED`. Independently of the verify action, the clock sweep moves any `UNVERIFIED` or `VERIFIED` policy whose `coverage_end` has passed to `EXPIRED`. Both `SUPERSEDED` and `EXPIRED` are terminal.

The practical consequence for billing: only a `VERIFIED` policy participates in the adjudicated payer split described in §3.8, and only a `VERIFIED` policy satisfies the travel-clinic booking gate described in §3.4.

### 3.3. Immunization Requirements, Records, Doses, and Exemptions

The health administrator defines each immunization requirement with a unique `vaccine_code` (for example, MMR or MENINGITIS_ACWY — redefining an existing code is rejected with `ERR_DUPLICATE_REQUIREMENT`), the `required_doses` count (between one and three inclusive), the `min_interval_days` that must separate consecutive doses, the compliance `deadline_date` as an ISO `YYYY-MM-DD` calendar date, and a `grace_period_days` count that determines how long after the deadline a non-compliant record lingers before it hardens into an overdue state.

A `Nurse` opens an immunization record for a student against a requirement, supplying `student_id` and `requirement_id`. At most one non-terminal record may exist for a given student–requirement pair; attempting to open a second while the first is neither `IN_COMPLIANCE` nor `EXEMPTED` is rejected with `ERR_DUPLICATE_IMMUNIZATION_RECORD`. The new record starts with `doses_received` at zero and an empty `dose_dates` list. Its initial status is normally `PENDING` — but if the requirement's deadline and grace window have both already passed at creation time, the record enters `OVERDUE` immediately and the student's posture is recomputed on the spot.

From there the record's life is governed jointly by the nurse and the clock. Recording a dose requires the record to be in one of `PENDING`, `GRACE`, or `OVERDUE` — a dose against an `IN_COMPLIANCE` or `EXEMPTED` record is rejected with `ERR_RECORD_NOT_DOSEABLE`. The request carries the `dose_date` and the OCC field `expected_record_version` (§2.8). Two temporal rules apply to the dose date itself: it may not lie in the future relative to the current logical date (`ERR_DOSE_DATE_IN_FUTURE`), and — except for the very first dose, which is unconstrained — it must fall at least `min_interval_days` after the previous recorded dose (`ERR_DOSE_INTERVAL_VIOLATION`). A compliant dose increments `doses_received` by one, appends the date to `dose_dates` in chronological order, and bumps the record's `version`. When the incremented count reaches the requirement's `required_doses`, the record transitions to `IN_COMPLIANCE` and the student's compliance posture is recomputed — a recompute that may release a `PROVISIONAL_HOLD` if the record was in grace, or a `REGISTRATION_HOLD` if it was overdue and no other hold source remains.

Meanwhile the clock sweep advances the deadline machinery. When the current logical date passes a requirement's `deadline_date` while the record is still `PENDING`, the record enters `GRACE` and the posture recompute may turn the student `PROVISIONAL_HOLD`, adding `IMMUNIZATION` to `active_hold_types` only if an overdue record already exists alongside it (grace alone contributes no entry). When the date later passes `deadline_date` plus `grace_period_days`, the record hardens to `OVERDUE`: the posture becomes `REGISTRATION_HOLD` with `IMMUNIZATION` present in `active_hold_types`, and — critically — every one of the student's still-`BOOKED` appointments of an elective visit type (`SPORTS_PHYSICAL` or `TRAVEL_CLINIC`) whose `scheduled_start` lies in the future is automatically cancelled with `cancel_reason` set to `HOLD`, freeing the associated triage quota. A record created so late that it is already past deadline-plus-grace transitions `PENDING → OVERDUE` directly under the sweep, with exactly the same posture and elective-cancellation side effects as the `GRACE → OVERDUE` path.

A `Clinician` may instead exempt a record outright, supplying an `exemption_reason`. Exemption is available from any of `PENDING`, `GRACE`, or `OVERDUE` (the same `ERR_RECORD_NOT_DOSEABLE` guards terminal records) and moves the record to `EXEMPTED`, storing the reason and recomputing the student's posture. `IN_COMPLIANCE` and `EXEMPTED` are the two terminal states of an immunization record.

### 3.4. Booking Appointments: Slots, Quotas, and Compliance Gates

Both `Student` and `FrontDeskStaff` callers may book appointments, supplying `student_id`, `provider_id`, `visit_type`, and the half-open scheduling window `scheduled_start` / `scheduled_end`. A student caller may book only for themselves: when `X-User-Role` is `Student`, the supplied `student_id` must equal `X-User-ID` or the booking is rejected with `ERR_FORBIDDEN`. The `visit_type` is one of `PRIMARY_URGENT`, `SAME_DAY_TRIAGE`, `FOLLOW_UP`, `SPORTS_PHYSICAL`, or `TRAVEL_CLINIC`. A successful booking lands in `BOOKED` with `cancel_reason` set to `NONE`.

Three temporal rules guard every booking, in validation order. The window must be well-formed: `scheduled_end` strictly after `scheduled_start`, else `ERR_INVALID_TIME_RANGE`. The appointment must lie in the future: a `scheduled_start` at or before the current logical time is rejected with `ERR_APPOINTMENT_IN_PAST`. And the provider's calendar must be free: an existing `BOOKED` or `CHECKED_IN` appointment for the same provider overlapping the new window is rejected with `ERR_SLOT_CONFLICT`. Overlap uses **half-open** semantics — the interval includes its start and excludes its end — so an existing booking ending exactly at the new appointment's start, or starting exactly at its end, does not conflict.

Same-day triage carries two further constraints of its own. A `SAME_DAY_TRIAGE` appointment must be scheduled on the current logical calendar date; any other date is rejected with `ERR_SAME_DAY_ONLY`. And each provider can absorb at most four such visits per day: the system counts the provider's `SAME_DAY_TRIAGE` appointments on that date in `BOOKED` or `CHECKED_IN` status, and rejects the booking with `ERR_TRIAGE_QUOTA_EXHAUSTED` when the count has already reached four. The boundary works in the caller's favor — with three counted, the fourth booking succeeds; with four counted, the fifth is refused. `CANCELLED` and `NO_SHOW` appointments never count toward the quota, which is why cancelling a triage booking frees the slot for someone else.

The two elective visit types are gated on compliance. Booking a `SPORTS_PHYSICAL` or `TRAVEL_CLINIC` while the student's `compliance_posture` is `REGISTRATION_HOLD` is rejected with `ERR_COMPLIANCE_HOLD_ACTIVE` (a `PROVISIONAL_HOLD` does not block elective booking). A `TRAVEL_CLINIC` booking carries an additional fiscal gate, evaluated later in the ordering: the student must hold a `VERIFIED` insurance policy, and booking without one is rejected with `ERR_INSURANCE_NOT_VERIFIED`.

Once booked, an appointment resolves through one of four paths. A front-desk check-in moves it from `BOOKED` to `CHECKED_IN` and opens the encounter described in §3.5. Cancellation — by the student themselves or by any front-desk operator — moves it from `BOOKED` to `CANCELLED`, stamps `cancel_reason` as `CLIENT`, and frees any triage quota it consumed; only a `BOOKED` appointment may be cancelled this way, otherwise `ERR_APPOINTMENT_NOT_CANCELLABLE`. The compliance sweep may force-cancel it as described in §3.3 and §3.8, in which case `cancel_reason` is `HOLD` instead. And if its `scheduled_end` passes while it is still `BOOKED`, the clock sweep marks it `NO_SHOW`. For schedule visibility, the appointment list supports filtering by `student_id`, by `provider_id`, by calendar `date`, and by `status`, so the front desk can reconstruct a provider's day or a student's upcoming visits without scanning the whole book.

### 3.5. The Visit: Check-in, the Encounter, and Closing

When a student arrives, a `FrontDeskStaff` operator checks in the booked appointment. Check-in requires the appointment to be `BOOKED` — anything else is rejected with `ERR_APPOINTMENT_NOT_BOOKED` — and is an atomic pair of mutations: the appointment moves `BOOKED → CHECKED_IN`, and a new `Encounter` is created in `OPEN` status with `appointment_id`, `student_id`, `provider_id`, and `visit_type` all copied across from the appointment and `opened_at` stamped with the current logical time. The new encounter's `clearance_outcome` starts as `NONE`, and its `closed_at` remains unset while it stays open.

While the encounter is `OPEN`, the clinical staff attach work to it — prescriptions (§3.6), lab orders (§3.7), referrals (§3.9) — each creation requiring the parent encounter to be `OPEN` and failing with `ERR_ENCOUNTER_NOT_OPEN` otherwise.

Whether the visit is **fee-covered** is decided at close time. The encounter is fee-covered when its `visit_type` is one of `PRIMARY_URGENT`, `SAME_DAY_TRIAGE`, or `FOLLOW_UP` **and** the student's `enrollment_status` is `ENROLLED` at the moment of closing; the derived `fee_covered` flag records the verdict. Fee-covered encounters carry no invoice — generating one is rejected with `ERR_INVOICE_NOT_ALLOWED` — and instead close by debiting the health-fee pool as described below. Non-fee-covered visits (sports physicals, travel-clinic consultations, and any visit for a non-enrolled student) are chargeable and must be billed.

Closing is a `Clinician` action with a four-part precondition chain, evaluated in the validation order of §2.9. The encounter must be `OPEN` (`ERR_ENCOUNTER_NOT_OPEN`). All of its prescriptions must be terminal — every one in `DISPENSED` or `CANCELLED` — and every lab order must be `REVIEWED`; any residue is rejected with `ERR_UNRESOLVED_CLINICAL_WORK`. If the encounter is chargeable, an invoice must already exist for it (`ERR_BILLING_NOT_CODED`); a fee-covered encounter, conversely, must never have one. Finally, the optional `clearance_outcome` is honored only for `SPORTS_PHYSICAL` encounters — supplying it on any other visit type is rejected with `ERR_INVALID_REQUEST` — and a `clearance_outcome` of `CLEARED` additionally requires the student's `compliance_posture` to be `CLEAR`, failing with `ERR_CLEARANCE_BLOCKED` otherwise. The clearance outcome may also be recorded as `NOT_CLEARED`, which carries no posture gate.

A successful close stamps `closed_at`, moves the encounter from `OPEN` to `CLOSED`, and cascades the linked appointment from `CHECKED_IN` to `COMPLETED`, its terminal state. If the encounter is fee-covered and an `OPEN` health-fee pool exists, the pool's `spent_cents` increases by the standard visit subsidy of 12000 cents; if no pool is open, the visit simply closes without any debit.

### 3.6. Pharmacy: Prescriptions, Dispensing, and Stock Thresholds

The pharmacy catalog is managed by the `Pharmacist` role. Creating a medication stock item requires a unique `medication_code` (duplicates are rejected with `ERR_DUPLICATE_MEDICATION`), a display `medication_name`, the `initial_on_hand` unit count (zero or more), and the `reorder_threshold` at which replenishment should be flagged. The stock's live `on_hand` is derived — it starts equal to `initial_on_hand`, grows with each restock, and shrinks with each dispense, and is never allowed to go negative. The companion flag `needs_reorder` is recomputed after every stock movement: it is true exactly when `on_hand` is less than or equal to `reorder_threshold`. The comparison is boundary-inclusive — a stock sitting precisely at its threshold is already flagged.

Within an `OPEN` encounter, a `Clinician` writes a prescription naming the `medication_stock_id` and the total `quantity_prescribed` units. The prescription begins in `WRITTEN` with `quantity_dispensed` at zero, and cancel is possible only from that state: a `Clinician` cancelling a still-`WRITTEN` prescription moves it to `CANCELLED`, while attempting to cancel one already partly dispensed is rejected with `ERR_PRESCRIPTION_NOT_CANCELLABLE`.

Dispensing is a `Pharmacist` action that may be partial. Each dispense call supplies a `quantity`, and four preconditions apply in validation order: the prescription must be `WRITTEN` or `PARTIALLY_DISPENSED` (`ERR_PRESCRIPTION_NOT_DISPENSABLE`); the quantity must be positive (`ERR_INVALID_QUANTITY`); it must not exceed the units still outstanding — that is, `quantity_prescribed` minus `quantity_dispensed` (`ERR_DISPENSE_QUANTITY_EXCEEDS`); and the medication stock must hold at least that many units on hand (`ERR_INSUFFICIENT_STOCK`). A successful dispense adds the quantity to `quantity_dispensed`, subtracts it from the stock's `on_hand`, and recomputes `needs_reorder`. When the dispensed total reaches the prescribed total the prescription becomes `DISPENSED`; short of that it sits in `PARTIALLY_DISPENSED`, where further dispenses remain legal under the same four rules. Restocking is the mirror operation: the pharmacist supplies a positive `quantity` (non-positive values fail with `ERR_INVALID_QUANTITY`), the stock's `on_hand` grows by that amount, and `needs_reorder` is recomputed against the new level.

### 3.7. Laboratory Orders, Disease Cases, and Outbreak Investigations

A `Clinician` orders a lab test on an `OPEN` encounter, supplying the `test_code` and, optionally, a `reportable_disease_code` identifying the communicable disease the test screens for. The order starts `ORDERED`. From there a fixed three-step chain executes, each step gated on the previous: a `Nurse` collects the sample, moving the order from `ORDERED` to `SAMPLE_COLLECTED` (any other starting status fails with `ERR_LAB_ORDER_NOT_ORDERED`); a `Nurse` enters the result, moving it from `SAMPLE_COLLECTED` to `RESULTED` (else `ERR_LAB_ORDER_NOT_COLLECTED`); and a `Clinician` reviews it, moving it from `RESULTED` to `REVIEWED` (else `ERR_LAB_ORDER_NOT_RESULTED`).

Entering the result carries the `result_summary` and a `flags_reportable` boolean, both stored on the order. When `flags_reportable` is true, the order must have been created with a `reportable_disease_code` — flagging a reportable result on an order without one is rejected with `ERR_REPORTABLE_CODE_REQUIRED`. A reportable result triggers an automatic cascade: a `DiseaseCase` is created in `SUSPECTED` status, with `student_id` copied from the source encounter, `lab_order_id` pointing at the originating order, and `disease_code` copied from the order's `reportable_disease_code`.

The case workflow is deliberately split across two roles. A `Clinician` confirms a `SUSPECTED` case (any other status is rejected with `ERR_CASE_NOT_CONFIRMABLE`), stamping `confirmed_at` with the current logical time and `confirmed_by_user_id` with the confirming clinician's `X-User-ID`. Confirmation also evaluates the outbreak threshold described below. A `HealthAdmin` operator then reports the confirmed case to public health — never the confirming clinician. Reporting requires the case to be `CONFIRMED` (`ERR_CASE_NOT_REPORTABLE`); it must occur within twenty-four hours of `confirmed_at`, a boundary-inclusive window (`ERR_REPORT_WINDOW_EXPIRED` once the current logical time passes `confirmed_at` plus 24 hours); and the reporting operator's `X-User-ID` must differ from `confirmed_by_user_id`, enforcing segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). A successful report stamps `reported_at` and `reported_by_user_id` and moves the case `CONFIRMED → REPORTED`. Independently of reporting, a `Clinician` may resolve a case from either `CONFIRMED` or `REPORTED` (anything else fails with `ERR_CASE_NOT_RESOLVABLE`), moving it to the terminal `RESOLVED` state.

The outbreak threshold is evaluated at confirm time against a **rolling 168-hour window**: the system counts every disease case sharing the same `disease_code` whose status is `CONFIRMED` or `REPORTED` — `SUSPECTED` and `RESOLVED` cases are excluded — and whose `confirmed_at` falls within the trailing 168 hours up to and including the current moment, both bounds inclusive. When that count reaches three or more, one of two cascades fires. If no investigation exists for the disease in `ACTIVE` or `CONTAINED` status, a new `OutbreakInvestigation` is created in `ACTIVE` with `opened_at` stamped and `opened_case_count` set to the triggering count, and the `OPEN` health-fee pool (if one exists) is debited an emergency 25000 cents. If an investigation for that disease currently sits in `CONTAINED`, it reopens to `ACTIVE` instead, reflecting a relapse. A separate **ISO calendar-week** count — same filters, but bucketed into the Monday-through-Sunday ISO week containing the current moment — is maintained purely as a surveillance reporting metric and never drives auto-open or auto-reopen; the two variants diverge at window edges, since a case confirmed 167 hours ago still counts under the rolling window but may fall in the previous ISO week.

Investigations are managed by `HealthAdmin` operators through a cyclic lifecycle. An `ACTIVE` investigation may be marked contained (`ACTIVE → CONTAINED`; anything else is rejected with `ERR_OUTBREAK_NOT_ACTIVE`). A `CONTAINED` investigation may be reopened manually (`CONTAINED → ACTIVE`) or may reopen automatically through the confirm-time cascade above; both the manual reopen and the close action require `CONTAINED` status (`ERR_OUTBREAK_NOT_CONTAINED`). Finally, a `CONTAINED` investigation may be closed (`CONTAINED → CLOSED`) only when no disease case for its `disease_code` remains in any of `SUSPECTED`, `CONFIRMED`, or `REPORTED` — closing over unresolved cases is rejected with `ERR_OUTBREAK_UNRESOLVED_CASES`. The disease code under investigation is unique among investigations not yet `CLOSED`.

### 3.8. Billing: Invoices, Adjudication, Payments, and Voids

The health-fee funding model is anchored by the term pool. A `HealthAdmin` operator opens a pool for an academic `term_code` (for example, SP26), supplying the term's `budget_cents` as a positive integer and the `term_end_date` after which the sweep closes it. At most one pool may be `OPEN` at any time — creating one while another is still open is rejected with `ERR_DUPLICATE_POOL_TERM` — which is what makes "the open pool" unambiguous wherever a subsidy or debit applies. A new pool starts with `spent_cents` at zero and `exhausted` false; the `exhausted` flag is derived and turns true exactly when `spent_cents` reaches or exceeds `budget_cents`, a boundary-inclusive comparison.

Billing begins once a chargeable encounter has been coded. A `BillingOfficer` generates the invoice under the target `encounter_id`, supplying the charge `lines` — a list of `{service_category, charge_cents}` pairs in request order, where `service_category` is one of `CONSULT`, `PHARMACY`, `LAB`, `TRAVEL_VACCINE`, or `SPORTS_FEE` and each `charge_cents` is a positive integer. Exactly one invoice may exist per encounter: a second generation attempt is rejected with `ERR_INVOICE_EXISTS`, and generation against a fee-covered encounter is rejected with `ERR_INVOICE_NOT_ALLOWED`. The new invoice lands in `DRAFT` with its `variant` set to `PROVISIONAL`, its `status` likewise `DRAFT`, `issued_at` and `due_date` still unset, and `student_id` copied from the encounter.

Invoice generation runs two pinned calculations before any payer split. First, the **travel-vaccine subsidy**: for each line in request order, when the line's `service_category` is `TRAVEL_VACCINE`, the encounter's visit type is `TRAVEL_CLINIC`, and an `OPEN`, non-exhausted health-fee pool exists, the line's tentative subsidy is its `charge_cents` multiplied by one-half, rounded half-up to integer cents; every other line's tentative subsidy is zero. The rounding order is pinned — subsidy is rounded **per line first, then summed**; the alternative of summing travel charges and rounding once is rejected because it yields different cents (two 3333-cent lines at one-half produce per-line subsidies of 1667 + 1667 = 3334, versus 3333 if rounded only after summing).

Second, the **pool waterfall**. The pool's remaining budget — `budget_cents` minus `spent_cents` — is snapshotted before this invoice. The lines are then walked in request order, and each line's applied subsidy is the smaller of its tentative subsidy and the snapshot's current remainder, which is then reduced by the applied amount before the next line. Only after the whole invoice is built is the pool debited, in a single step, by the total applied subsidy. The naive reading in which the remainder is recomputed from a pool already debited by this same invoice is explicitly rejected: the snapshot makes the result well-defined. The invoice's `subsidy_cents` is the sum of applied subsidies, each line's net is its charge minus its applied subsidy, and `charge_total_cents` is the sum of the per-line nets.

The **payer split** runs in two variants. At generation time the invoice is `PROVISIONAL` and the patient pays everything: `insurer_pays_cents` is zero and `patient_responsibility_cents` equals `charge_total_cents`, regardless of any policy on file. When a `BillingOfficer` issues the invoice (the `DRAFT → ISSUED` transition — issuing anything else is rejected with `ERR_INVOICE_NOT_DRAFT`), the variant flips to `FINAL` and the split is recomputed. If a `VERIFIED` policy exists for the student at issue time, the adjudicated split applies: the amount after copay is `charge_total_cents` minus `copay_cents`, floored at zero; the deductible remaining is `deductible_cents` minus the policy's `deductible_met_cents`, floored at zero; the deductible applied to this invoice is the smaller of those two figures; the coinsurance base is the after-copay amount minus the deductible applied; the patient's coinsurance share is that base multiplied by `coinsurance_pct`, rounded half-up to integer cents. The insurer then pays `charge_total_cents` minus the copay, minus the deductible applied, minus the patient's coinsurance share — that figure lands in `insurer_pays_cents` — while the patient's responsibility is the copay plus the deductible applied plus the coinsurance share, landing in `patient_responsibility_cents`. As a side effect of issue, the policy's `deductible_met_cents` accumulates the deductible applied. If no `VERIFIED` policy exists at issue time, the final split falls back to self-pay: the patient responsibility equals `charge_total_cents` and the insurer pays nothing. Either way, issue stamps `issued_at` with the current logical time, sets `due_date` to thirty calendar days after the issue date, and initializes `balance_cents` equal to `patient_responsibility_cents`.

Payment posting creates a `Payment` under the parent `invoice_id`, accepting an `amount_cents` and a `method` — one of `CARD`, `CASH`, or `EXTERNAL_REMITTANCE` — and applies to invoices in `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE` (anything else is rejected with `ERR_INVOICE_NOT_PAYABLE`). The amount must be positive (`ERR_INVALID_QUANTITY`) and must not exceed the invoice's current `balance_cents` (`ERR_OVERPAYMENT`). Each payment is created in `POSTED` status. After every posting, the invoice's balance is recomputed as `patient_responsibility_cents` minus the sum of all `POSTED` payments, and the status is re-derived: a balance of zero is `PAID`; a positive balance below the full patient responsibility is `PARTIALLY_PAID` (or `OVERDUE` if the `due_date` has passed the current logical date); a balance restored to the full responsibility is `ISSUED` (or `OVERDUE` if past due). A payment that exactly covers the balance therefore moves the invoice `ISSUED → PAID` (or `OVERDUE → PAID`, or `PARTIALLY_PAID → PAID`), while a partial payment moves it to `PARTIALLY_PAID`. Money is conserved as an invariant: the patient responsibility always equals the outstanding balance plus the sum of posted payments, so a post followed by a void of the same payment leaves `balance_cents` unchanged. Whenever a payment or void changes an `OVERDUE` invoice's balance, the student's compliance posture is recomputed — a financial hold releases the moment no overdue invoice remains.

The clock sweep ages receivables: an `ISSUED` or `PARTIALLY_PAID` invoice whose `due_date` falls before the current logical date with a positive balance transitions to `OVERDUE`. That transition recomputes the student's posture into `REGISTRATION_HOLD` with `FINANCIAL` added to `active_hold_types`, and — exactly as in the immunization cascade — auto-cancels every still-`BOOKED` future elective appointment (`SPORTS_PHYSICAL` or `TRAVEL_CLINIC` with `scheduled_start` in the future) with `cancel_reason` set to `HOLD`, freeing any triage quota those bookings held.

Voiding is the compensating action: a `BillingOfficer` voids a `POSTED` payment (any other status fails with `ERR_PAYMENT_NOT_VOIDABLE`), stamping `voided_at` and moving the payment to its terminal `VOIDED` state. The invoice balance is then recomputed without the voided amount and its status re-derived against the current logical date — a `PAID` invoice returns to `ISSUED` when its `due_date` is still in the future, or to `OVERDUE` when the due date has already passed; a `PARTIALLY_PAID` invoice whose balance returns to the full responsibility likewise returns to `ISSUED` (future due date) or stays subject to overdue re-derivation; and an `OVERDUE` invoice flips back to `ISSUED` only when its due date remains in the future, otherwise it stays `OVERDUE`. Each of these re-derivations recomputes the student's posture, so a void can re-impose a `FINANCIAL` hold that a payment had released.

### 3.9. After-Hours Referrals and On-Call Coverage

The health center's business hours are 08:00 through 17:00 UTC daily, treated as a half-open window: 08:00:00 is inside business hours, 17:00:00 is outside them. A `Clinician` working an `OPEN` encounter may initiate a hospital referral, supplying the receiving `hospital_name` and a `reason`. The referral is created in `INITIATED` status with `created_by_user_id` recording the clinician's `X-User-ID`, and its derived `after_hours` flag records whether the referral was initiated outside business hours.

After-hours referrals are gated on coverage. When the current logical time falls outside the business-hours window, a covering on-call shift must exist — any provider's shift whose `shift_start` is at or before the current moment and whose `shift_end` is strictly after it. If no such shift exists, the referral is rejected with `ERR_NO_ONCALL_COVERAGE`. Referrals initiated inside business hours carry no such requirement. Once initiated, a referral moves from `INITIATED` to `ACCEPTED` — its terminal state — when a `Clinician` marks the receiving hospital's acceptance; accepting anything not `INITIATED` is rejected with `ERR_REFERRAL_NOT_INITIATED`.

The on-call rota itself is maintained by `HealthAdmin` operators, who schedule each shift with a `provider_id` and the closed-interval window `shift_start` / `shift_end`. Providers themselves are registered by a `HealthAdmin` operator with a `full_name`, a `provider_type` of either `CLINICIAN` or `NURSE`, and an `active` flag that defaults to true and governs whether the provider can take new appointments and shifts. The shift window must be well-formed — the end strictly after the start, else `ERR_INVALID_TIME_RANGE`. Two further constraints protect provider rest, and the overlap check is evaluated before the rest check. First, a provider's shifts may not overlap at all: on-call overlap uses **closed-interval** semantics, so two shifts that merely touch — one ending exactly when the other begins — count as overlapping and are rejected with `ERR_ONCALL_OVERLAP`. Second, any two shifts of the same provider must be separated by at least twelve hours of rest; a gap shorter than twelve hours is rejected with `ERR_ONCALL_REST_VIOLATION`, while a gap of exactly twelve hours is permitted.

## 4. Endpoint Definitions

Operations that create a new resource — registering a student, defining a requirement, booking an appointment, opening an encounter through check-in, writing a prescription or lab order, generating an invoice, posting a payment, initiating a referral, opening a pool — return `201 Created`. Operations that modify an existing resource in place — state transitions such as verify, dispense, collect, result, review, confirm, report, resolve, contain, reopen, close, cancel, issue, void, accept, and restock — return `200 OK`. Setting the logical clock returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shc/_clock/set_current_utc` | Set the logical clock and run the deterministic sweep | HealthAdmin |
| POST | `/shc/students` | Register a student | HealthAdmin |
| GET | `/shc/students/{id}` | Get a student including computed compliance posture | Any |
| POST | `/shc/insurance-policies` | Create a policy for a student (supersedes existing; OCC via expected student version) | BillingOfficer |
| POST | `/shc/insurance-policies/{id}/verify` | Verify a policy's eligibility | BillingOfficer |
| GET | `/shc/students/{id}/insurance-policies` | List a student's policies | Any |
| POST | `/shc/immunization-requirements` | Define an immunization requirement | HealthAdmin |
| POST | `/shc/immunization-records` | Open an immunization record for a student | Nurse |
| GET | `/shc/immunization-records` | List immunization records with filters | Any |
| GET | `/shc/immunization-records/{id}` | Get one immunization record | Any |
| POST | `/shc/immunization-records/{id}/doses` | Record an administered dose (OCC via expected record version) | Nurse |
| POST | `/shc/immunization-records/{id}/exempt` | Grant a medical exemption | Clinician |
| POST | `/shc/providers` | Create a provider | HealthAdmin |
| GET | `/shc/providers/{id}` | Get a provider | Any |
| POST | `/shc/on-call-shifts` | Schedule an after-hours on-call shift | HealthAdmin |
| GET | `/shc/providers/{id}/on-call-shifts` | List a provider's on-call shifts | Any |
| POST | `/shc/appointments` | Book an appointment | Student, FrontDeskStaff |
| GET | `/shc/appointments` | List appointments with filters | Any |
| GET | `/shc/appointments/{id}` | Get an appointment | Any |
| POST | `/shc/appointments/{id}/check-in` | Check in a booked appointment; creates the linked encounter | FrontDeskStaff |
| POST | `/shc/appointments/{id}/cancel` | Cancel a booked appointment; frees triage quota | Student, FrontDeskStaff |
| GET | `/shc/encounters` | List encounters with filters | Any |
| GET | `/shc/encounters/{id}` | Get an encounter | Any |
| POST | `/shc/encounters/{id}/close` | Close an encounter with clinical, billing, and clearance gates | Clinician |
| POST | `/shc/encounters/{id}/prescriptions` | Write a prescription on an open encounter | Clinician |
| GET | `/shc/prescriptions` | List prescriptions with filters | Any |
| GET | `/shc/prescriptions/{id}` | Get a prescription | Any |
| POST | `/shc/prescriptions/{id}/dispense` | Dispense units against a prescription; decrements stock | Pharmacist |
| POST | `/shc/prescriptions/{id}/cancel` | Cancel a written (never dispensed) prescription | Clinician |
| POST | `/shc/medication-stocks` | Create a medication stock item | Pharmacist |
| GET | `/shc/medication-stocks` | List medication stock | Any |
| POST | `/shc/medication-stocks/{id}/restock` | Restock units; recompute reorder flag | Pharmacist |
| POST | `/shc/encounters/{id}/lab-orders` | Order a lab test on an open encounter | Clinician |
| GET | `/shc/encounters/{id}/lab-orders` | List an encounter's lab orders | Any |
| GET | `/shc/lab-orders/{id}` | Get a lab order | Any |
| POST | `/shc/lab-orders/{id}/collect` | Collect the sample | Nurse |
| POST | `/shc/lab-orders/{id}/result` | Enter the result; may auto-create a disease case | Nurse |
| POST | `/shc/lab-orders/{id}/review` | Clinician reviews the result | Clinician |
| GET | `/shc/disease-cases` | List disease cases with filters | Any |
| GET | `/shc/disease-cases/{id}` | Get a disease case | Any |
| GET | `/shc/lab-orders/{id}/disease-cases` | List disease cases originating from a lab order | Any |
| POST | `/shc/disease-cases/{id}/confirm` | Confirm a suspected case; evaluates the outbreak threshold | Clinician |
| POST | `/shc/disease-cases/{id}/report` | Report a confirmed case to public health within 24 hours | HealthAdmin |
| POST | `/shc/disease-cases/{id}/resolve` | Resolve a confirmed or reported case | Clinician |
| GET | `/shc/outbreak-investigations` | List outbreak investigations with filters | Any |
| POST | `/shc/outbreak-investigations/{id}/contain` | Mark an active outbreak contained | HealthAdmin |
| POST | `/shc/outbreak-investigations/{id}/reopen` | Reopen a contained outbreak (relapse cycle) | HealthAdmin |
| POST | `/shc/outbreak-investigations/{id}/close` | Close a contained outbreak; requires zero unresolved cases | HealthAdmin |
| POST | `/shc/encounters/{id}/invoice` | Generate the invoice for a chargeable open encounter | BillingOfficer |
| GET | `/shc/invoices` | List invoices with filters | Any |
| GET | `/shc/invoices/{id}` | Get an invoice | Any |
| POST | `/shc/invoices/{id}/issue` | Issue a draft invoice; recompute the final payer split | BillingOfficer |
| POST | `/shc/invoices/{id}/payments` | Post a payment against an issued invoice | BillingOfficer |
| POST | `/shc/payments/{id}/void` | Void a posted payment (compensating action) | BillingOfficer |
| GET | `/shc/invoices/{id}/payments` | List an invoice's payments | Any |
| POST | `/shc/encounters/{id}/referrals` | Initiate a hospital referral from an open encounter | Clinician |
| POST | `/shc/referrals/{id}/accept` | Mark the referral accepted by the hospital | Clinician |
| GET | `/shc/encounters/{id}/referrals` | List an encounter's referrals | Any |
| POST | `/shc/health-fee-pools` | Open a term health-fee pool (at most one open at a time) | HealthAdmin |
| GET | `/shc/health-fee-pools` | List health-fee pools | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_STUDENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_RECORD_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_STUDENT_REF` | 409 Conflict |
| `ERR_DUPLICATE_REQUIREMENT` | 409 Conflict |
| `ERR_DUPLICATE_MEDICATION` | 409 Conflict |
| `ERR_DUPLICATE_POOL_TERM` | 409 Conflict |
| `ERR_DUPLICATE_IMMUNIZATION_RECORD` | 409 Conflict |
| `ERR_POLICY_NOT_UNVERIFIED` | 409 Conflict |
| `ERR_POLICY_EXPIRED` | 422 Unprocessable Entity |
| `ERR_POLICY_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_RECORD_NOT_DOSEABLE` | 409 Conflict |
| `ERR_DOSE_INTERVAL_VIOLATION` | 422 Unprocessable Entity |
| `ERR_DOSE_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_IN_PAST` | 422 Unprocessable Entity |
| `ERR_SAME_DAY_ONLY` | 422 Unprocessable Entity |
| `ERR_SLOT_CONFLICT` | 409 Conflict |
| `ERR_TRIAGE_QUOTA_EXHAUSTED` | 409 Conflict |
| `ERR_COMPLIANCE_HOLD_ACTIVE` | 403 Forbidden |
| `ERR_INSURANCE_NOT_VERIFIED` | 402 Payment Required |
| `ERR_APPOINTMENT_NOT_BOOKED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ENCOUNTER_NOT_OPEN` | 409 Conflict |
| `ERR_BILLING_NOT_CODED` | 409 Conflict |
| `ERR_UNRESOLVED_CLINICAL_WORK` | 409 Conflict |
| `ERR_CLEARANCE_BLOCKED` | 403 Forbidden |
| `ERR_INVOICE_NOT_ALLOWED` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_DISPENSE_QUANTITY_EXCEEDS` | 422 Unprocessable Entity |
| `ERR_INVALID_QUANTITY` | 422 Unprocessable Entity |
| `ERR_PRESCRIPTION_NOT_DISPENSABLE` | 409 Conflict |
| `ERR_PRESCRIPTION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_LAB_ORDER_NOT_ORDERED` | 409 Conflict |
| `ERR_LAB_ORDER_NOT_COLLECTED` | 409 Conflict |
| `ERR_LAB_ORDER_NOT_RESULTED` | 409 Conflict |
| `ERR_REPORTABLE_CODE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CASE_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_CASE_NOT_REPORTABLE` | 409 Conflict |
| `ERR_REPORT_WINDOW_EXPIRED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CASE_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_OUTBREAK_NOT_ACTIVE` | 409 Conflict |
| `ERR_OUTBREAK_NOT_CONTAINED` | 409 Conflict |
| `ERR_OUTBREAK_UNRESOLVED_CASES` | 409 Conflict |
| `ERR_INVOICE_EXISTS` | 409 Conflict |
| `ERR_INVOICE_NOT_DRAFT` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_VOIDABLE` | 409 Conflict |
| `ERR_NO_ONCALL_COVERAGE` | 409 Conflict |
| `ERR_REFERRAL_NOT_INITIATED` | 409 Conflict |
| `ERR_ONCALL_OVERLAP` | 409 Conflict |
| `ERR_ONCALL_REST_VIOLATION` | 409 Conflict |
