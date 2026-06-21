# Dental Practice Management API — Product Requirements Document

## 1. Introduction

A modern dental office runs three intertwined businesses at once: a clinical operation that charts teeth and plans treatment, a scheduling operation that fits providers and patients into a limited number of treatment chairs, and an insurance-and-billing operation that estimates benefits, predetermines coverage, files claims, and collects whatever the carrier does not pay. This API is the system of record that ties those three worlds together. It models patients and the providers who treat them, the operatories (chairs) they occupy, the insurance plans and patient coverages that govern what a carrier will pay, and the treatment plans, predeterminations, claims, recare recalls, and payment plans that move money and care through the practice.

The central difficulty the platform solves is that the *estimated* benefit a patient is quoted at planning time and the *actual* benefit a carrier pays at adjudication time are computed against the same coverage but at different moments, against an accumulator that shifts as earlier claims are paid. A treatment plan proposes a forward-looking estimate; a claim, filed and adjudicated later, recomputes the benefit against the live remaining annual maximum and may legitimately pay less. The same tension recurs across the domain — frequency and waiting windows that open and close with the calendar, an annual maximum that clamps benefits and cascades back into predeterminations, and payment plans that supersede one another under optimistic concurrency. This document specifies every entity, state machine, calculation, and validation an implementation must honor so that the estimate, the adjudication, and the ledger always reconcile.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `FrontDesk`, `Clinician`, `BillingSpecialist`, and `Patient`. A `FrontDesk` user handles registration, operatory management, scheduling, recare recall, and the acceptance or cancellation of treatment plans. A `Clinician` performs charting, treatment planning, plan proposal, revision, completion, and the clinical completion of visits. A `BillingSpecialist` owns insurance configuration, coverage attachment, predetermination, claims and their attachments, adjudication, and payment plans. A `Patient` has read-only self-service access to their own records.

Two roles are tied to a persisted entity. When `X-User-Role` is `Clinician`, `X-User-ID` is the `id` of the acting `Provider`; the server treats this identity as the acting provider but does not enforce a provider-ownership filter on reads — a `Clinician` may read and list any resource the role is authorized for regardless of which provider it references, and the `provider_id` on resources a clinician creates is taken from the request body rather than forced to equal `X-User-ID`. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's patient foreign key to `X-User-ID`, which is what restricts the `Patient` role to its own records — this is the only role for which an ownership filter is enforced, applied both on single-resource reads (a mismatch yielding `ERR_FORBIDDEN`) and on the list endpoints the `Patient` role may call (where it silently narrows the result set to the patient's own records). The other two roles are operator identities: when `X-User-Role` is `FrontDesk` or `BillingSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A supplied `limit` or `offset` that falls outside its range is silently clamped to the nearest bound (a `limit` below 1 becomes 1, above 100 becomes 100, and an `offset` below 0 becomes 0) rather than rejected; a value that is not an integer is rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Each list endpoint additionally accepts optional equality-filter query parameters on its own scalar fields (for example `status`, `patient_id`, `provider_id`, `treatment_plan_id`, `adjudication_status`, and similar): when such a parameter is supplied, only records whose corresponding field equals the supplied value are returned; an omitted filter parameter is ignored. The filter is applied before pagination, so `total_count` reflects the filtered set.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — `Patient`, `Provider`, `Operatory`, `InsurancePlan`, `PatientCoverage`, `ToothChartEntry`, `TreatmentPlan`, `TreatmentPlanItem`, `Appointment`, `Predetermination`, `Claim`, `RecareRecall`, and `PaymentPlan` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that begins at the resource's creation and increments by one on every mutation. It is the basis for optimistic concurrency control described in §2.7.

`ClaimAttachment` is the one exception. An attachment is immutable after creation, so it carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. Whenever the prose below describes a derived field being recomputed — a coverage accumulator, a plan total, a patient balance — that recomputation is itself a mutation of the owning resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. Monetary Values, Dates, and Calculation Precision

All monetary amounts in this system are stored and transmitted as **integer cents**; there are no fractional cents and no floating-point money. Field names ending in `_cents` (for example `fee_cents`, `annual_maximum_cents`, `carrier_paid_cents`) are always whole integers.

Two rounding rules govern the calculations. Wherever a benefit is computed as a percentage of a fee, the coinsurance product is taken to the largest whole number of cents that does not exceed the exact product — that is, the fractional remainder is dropped (floor), never rounded up. Wherever an installment schedule divides a principal across a count, the per-installment amount is likewise floored, and the accumulated remainder is reconciled into the final installment rather than spread across all of them; the precise mechanics live in §3.7.

Dates supplied to the system (`date_of_birth`, `coverage_start_date`, `benefit_year_start_date`, `valid_until_date`, `last_visit_date`, `visit_date`) are ISO calendar dates. Where a calculation adds a number of months to a date, the addition is calendar-month addition with the day clamped to the end of the target month when the source day does not exist there. Where a calculation measures elapsed time in months (waiting periods, frequency gaps), it counts **whole** calendar months. Chair-time fields (`start_at`, `end_at`) are ISO 8601 UTC datetimes.

### 2.6. Hierarchical Consistency and Cascades

Several operations in this system mutate more than one resource. When a treatment plan is cancelled, the cancellation cascades downward to its items and, through them, to any appointments those items had scheduled. When a claim is adjudicated, the carrier payment cascades into the coverage's accumulators, may trip the annual-maximum flag, and — when that flag trips — cascades further into the patient's approved predeterminations, forcing them to be revalidated. When a claim is voided, those same accumulators are restored in compensation. Every such secondary mutation independently refreshes the affected resource's `updated_at` and increments its `version`, exactly as §2.4 requires; the specific cascade chains are detailed in the workflow narratives of §3.

The server also performs **automatic, system-driven transitions** that no client explicitly requests on the affected resource: a recare recall flips to `DUE` when the clock reaches its due date, a pending predetermination flips to `EXPIRED` when the clock passes its validity date, an approved predetermination flips to `REQUIRES_REVALIDATION` when its coverage exhausts the annual maximum, and a payment plan flips to `PAID_OFF` the moment its postings cover the principal. These are described where the triggering workflow lives.

### 2.7. Optimistic Concurrency Control on Payment-Plan Creation

Creating a payment plan is the single operation in this system guarded by optimistic concurrency control. A request to finance a claim's patient responsibility must carry `expected_claim_version`, a non-optional field whose value is the client's last observed `version` of the target `Claim`. The server compares it to the claim's current `version`; if they do not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no payment plan is created.

This matters because creating a payment plan against a claim increments that claim's `version` by one. A newly created payment plan legitimately supersedes any prior financing arrangement for the same patient responsibility, so when a client holds a stale view of the claim — its `version` already advanced by an earlier plan's creation — the OCC check is what prevents the client from overwriting a financing arrangement it never observed. No other endpoint takes a version field, and no other endpoint performs this check.

### 2.8. Resource and Reference Resolution Order

For any request, the system validates in a fixed priority order so that failures surface predictably. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization for the role (`ERR_FORBIDDEN`). Next, every resource identifier the request names must resolve: path identifiers are checked left to right, and only then are foreign-key identifiers in the request body resolved. A path or body identifier that does not correspond to an existing resource yields the matching not-found error for that resource type — `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_OPERATORY_NOT_FOUND`, `ERR_INSURANCE_PLAN_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_TREATMENT_PLAN_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_PREDETERMINATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RECALL_NOT_FOUND`, or `ERR_PAYMENT_PLAN_NOT_FOUND` — all carrying HTTP 404. A `ToothChartEntry` that cannot be resolved by id is the one resource with no dedicated entry in the §5 catalogue; it yields a 404 whose `error_id` is `ERR_TOOTH_CHART_ENTRY_NOT_FOUND`.

Only after existence is settled does the system validate that the request body is well-formed: enum values legal, numeric ranges respected, and conditional fields supplied where their trigger field demands them. A malformed body yields `ERR_VALIDATION` (HTTP 422). The one wrinkle in this ordering is the *presence* of required fields: the implementation confirms that every required field is present (rejecting an absent one with `ERR_VALIDATION`) before it resolves any body foreign key, so a request that both omits a required field and names a non-existent foreign key in another field fails with `ERR_VALIDATION` rather than the not-found error. Once all required fields are present, the foreign keys they carry are resolved for existence as described above, and only then is the remaining body shape validated. On payment-plan creation specifically, the optimistic-concurrency check of §2.7 runs after body validation but before any state or business check, so a stale writer fails fast with `ERR_STALE_VERSION`. State checks (`ERR_INVALID_STATE` and its specific siblings) and business checks follow. This ordering is the precedence used throughout §3: a check earlier in this list, when it fires, masks any later check that would also have failed.

### 2.9. The Insurance Benefit Ledger

Each `PatientCoverage` is a live ledger of how much of a plan's annual benefit a patient has consumed. Three fields express its state, and they are maintained as stored running accumulators on the coverage rather than recomputed from the claim set on each read: `annual_benefit_used_cents` is increased by a claim's `carrier_paid_cents` when that claim adjudicates `PAID` or `PARTIALLY_PAID` and is decreased by the same amount when that claim is later voided; `deductible_met_cents` is the deductible already consumed, increased by the deductible a claim consumes at adjudication and decreased by that same amount on void; and `annual_max_reached` is a boolean that is true exactly when `annual_benefit_used_cents` has reached or exceeded the plan's `annual_maximum_cents`. These accumulators are not filtered by, partitioned into, or automatically reset at any benefit-year boundary, and there is no scheduled or clock-driven reset of `annual_maximum_cents` or `deductible_cents`: the `benefit_year_start_date` is recorded on the coverage but the running totals simply persist and are adjusted only by adjudication and void.

This ledger is conserved. A claim's adjudication debits it; a void of that same claim credits it back. Because the estimate at planning time and the adjudication at claim time both read this ledger but at different moments, the same fee can be quoted one benefit at proposal and pay a smaller benefit at adjudication once earlier claims have drawn the pool down. §3 specifies both calculations against this shared ledger.

## 3. Business Logic & Workflows

### 3.1. Registering Patients, Providers, and Operatories

The practice's foundational records are patients, providers, and operatories. A `FrontDesk` user registers a patient with a `full_name` and a `date_of_birth`; the new patient opens in `ACTIVE` status with `balance_owed_cents` initialized to zero. A patient's `balance_owed_cents` is a running total of the `patient_responsibility_cents` across that patient's claims that are not yet covered by an active payment plan, recomputed whenever a claim is adjudicated, denied, or voided, or whenever a payment plan changes. A claim whose `adjudication_status` is `VOID` is excluded from this total entirely, and a claim financed by an `ACTIVE` payment plan is likewise excluded for as long as that plan stays `ACTIVE`; once a financing plan leaves `ACTIVE` (becoming `DEFAULTED` or `PAID_OFF`) its claim's responsibility re-enters the total. `FrontDesk` may deactivate a patient, moving `status` to `INACTIVE`; an inactive patient blocks new appointments and charting. The two patient `status` values are `ACTIVE` and `INACTIVE`.

A provider is registered by `FrontDesk` with a `full_name`, a `provider_type`, and an `npi` (the ten-digit National Provider Identifier). The `provider_type` is either `DENTIST` or `HYGIENIST`, and it constrains scheduling: a `HYGIENIST` may own only preventive or perio work and is forbidden from operative appointments, as §3.4 details. A provider opens `ACTIVE` and may be deactivated to `INACTIVE` by `FrontDesk`; provider `status` is one of `ACTIVE` or `INACTIVE`.

Operatories are the treatment chairs. `FrontDesk` creates an operatory with a `room_name` and an optional `turnover_buffer_minutes` that defaults to 15 and must be at least 0; this buffer is appended after each appointment in that room and widens the room's occupancy interval for the double-booking check of §3.4. An operatory opens in `OPEN` status and can be moved to `CLOSED` by `FrontDesk`, after which it rejects new appointments. Operatory `status` is one of `OPEN` or `CLOSED`.

A `Clinician` records charting on a patient through a tooth-chart entry, whose `patient_id` is taken from the path. The clinician supplies the `provider_id` of the charting clinician, a `tooth_number` in the universal range 1 through 32, a `chart_type`, and a free-text `finding`. The `chart_type` is either `SURFACE`, a restorative finding that additionally requires a `surface` value drawn from `M`, `O`, `D`, `B`, `L`, or `I` (mesial, occlusal, distal, buccal, lingual, incisal), or `PERIO`, a pocket-depth reading that instead requires a `pocket_depth_mm` value between 1 and 12 millimeters. If the entry is `SURFACE` and omits `surface`, or is `PERIO` and omits `pocket_depth_mm`, the request fails body validation with `ERR_VALIDATION`. Charting on an inactive patient is rejected with `ERR_PATIENT_INACTIVE`.

### 3.2. Insurance Plans and Patient Coverage

A `BillingSpecialist` configures an insurance plan with a `carrier_name` and the benefit parameters the carrier offers: an `annual_maximum_cents` (which must be greater than zero), a `deductible_cents` (at least zero), and three coinsurance percentages — `preventive_coinsurance_pct`, `basic_coinsurance_pct`, and `major_coinsurance_pct` — each an integer from 0 through 100 giving the share the carrier pays for that procedure category. Two cadence parameters round out the plan: `major_waiting_period_months`, the number of months of continuous coverage required before major procedures become eligible (defaulting to 12, at least 0), and `frequency_limit_months`, the minimum number of months that must elapse between two carrier-paid procedures sharing the same CDT code for one patient (defaulting to 6, at least 0).

Attaching a plan to a patient creates a patient coverage, again a `BillingSpecialist` action, taking a `patient_id`, an `insurance_plan_id`, a `coverage_start_date` (the date coverage began, which drives waiting-period eligibility), and a `benefit_year_start_date` (recorded as the nominal annual anchor; per §2.9 it is stored but does not actually trigger any reset of the running accumulators). A new coverage opens with `annual_benefit_used_cents` at zero, `deductible_met_cents` at zero, `annual_max_reached` false, and `status` of `ACTIVE`. Coverage `status` is one of `ACTIVE` or `TERMINATED`; a `BillingSpecialist` may terminate a coverage, moving it to `TERMINATED`. Retrieving a coverage shows its live accumulators.

### 3.3. The Treatment Plan: Drafting, Proposing, and the Revision Loop

A `Clinician` opens a treatment plan for a patient by supplying a `patient_id` and the planning dentist's `provider_id`. The plan begins in `DRAFT` with `total_fee_cents` and `estimated_patient_portion_cents` at zero. A plan's `status` moves through `DRAFT`, `PROPOSED`, `ACCEPTED`, `COMPLETED`, and `CANCELLED`, of which `COMPLETED` and `CANCELLED` are terminal.

While the plan is in `DRAFT`, the clinician adds planned procedures as treatment-plan items; attempting to add an item to a plan that is not in `DRAFT` is rejected with `ERR_INVALID_STATE` (this state check runs after the item body has been validated). Each item carries a `cdt_code` (the ADA procedure code), a `category` that is one of `PREVENTIVE`, `BASIC`, or `MAJOR` and selects which coinsurance tier and waiting rule apply, and a `fee_cents` that must be greater than zero. Optionally the clinician supplies a `phase_number` (the phasing sequence, defaulting to 1, at least 1, with lower phases scheduled first), a `tooth_number` in range 1 through 32 for tooth-specific work or none for whole-mouth procedures, and a `requires_predetermination` flag (defaulting to false). The item's `treatment_plan_id` is taken from the path. A new item opens in `PLANNED` status, and adding it recomputes the plan's `total_fee_cents`. An item's `status` is one of `PLANNED`, `SCHEDULED`, `COMPLETED`, or `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal. The item also carries two computed money fields, `estimated_insurance_cents` and `estimated_patient_portion_cents`, both of which open at zero and are first populated only when the plan is proposed (§3.8); and two computed references, `predetermination_id` and `appointment_id`, both of which open as null and are each set when the corresponding predetermination is requested or appointment is scheduled.

Proposing the plan advances it from `DRAFT` to `PROPOSED`. This requires the plan to be in `DRAFT` (otherwise `ERR_INVALID_STATE`) and to hold at least one item in `PLANNED` status (otherwise `ERR_PLAN_HAS_NO_ITEMS`). On proposal, the system recomputes `estimated_insurance_cents` and `estimated_patient_portion_cents` on every `PLANNED` item using the forward-looking estimate of §3.8, then recomputes the plan-level `total_fee_cents` (the sum of `fee_cents` over the plan's non-`CANCELLED` items) and `estimated_patient_portion_cents` (the sum of `estimated_patient_portion_cents` over those same non-`CANCELLED` items).

The plan supports a revision loop. From `PROPOSED`, a `Clinician` may revise the plan back to `DRAFT`, which requires it to be in `PROPOSED` (otherwise `ERR_INVALID_STATE`) and reopens it so items may be added or removed; revising and re-proposing may repeat. Acceptance is a `FrontDesk` action that moves the plan from `PROPOSED` to `ACCEPTED`; it requires the plan to be in `PROPOSED` (otherwise `ERR_INVALID_STATE`) and the patient to be `ACTIVE` (otherwise `ERR_PATIENT_INACTIVE`). Once accepted, the items remain `PLANNED` but become schedulable.

Completing a plan is a `Clinician` action moving it from `ACCEPTED` to `COMPLETED`; it requires the plan to be `ACCEPTED` (otherwise `ERR_INVALID_STATE`) and every non-`CANCELLED` item to be `COMPLETED` (otherwise `ERR_PLAN_ITEMS_NOT_COMPLETE`).

### 3.4. Scheduling, Visits, and the Operatory Calendar

Scheduling is a `FrontDesk` responsibility. An appointment is booked with a `patient_id`, a `provider_id`, an `operatory_id`, an `appointment_type`, a `start_at`, and an `end_at`, plus an optional `treatment_plan_item_id` naming the planned procedure the visit will perform. The `appointment_type` is either `PREVENTIVE` or `OPERATIVE`, and `end_at` must be strictly later than `start_at`. The appointment opens in `SCHEDULED` status; appointment `status` ranges over `SCHEDULED`, `CHECKED_IN`, `COMPLETED`, `CANCELLED`, and `NO_SHOW`, of which the last three are terminal.

Several referential rules gate booking, all reported with the same conflict code where noted. A `HYGIENIST` provider may own only `PREVENTIVE` appointments; assigning one to an `OPERATIVE` appointment is rejected with `ERR_PROVIDER_TYPE_MISMATCH`. That same code also covers booking into a `CLOSED` operatory, booking with an `INACTIVE` provider or patient, and, on claim creation, a coverage that does not belong to the claim's patient. Independently, the chair-time must be free: a new appointment's interval must not overlap any existing non-terminal appointment on the same operatory — where the comparison widens each *existing* booking's interval by appending the operatory's `turnover_buffer_minutes` of cleanup time after that booking's `end_at`, and compares it against the candidate's own un-widened interval — nor overlap any existing non-terminal appointment for the same provider, for whom no buffer applies. Intervals are treated as half-open `[start_at, end_at)`, so two appointments that merely abut (one's `end_at` equals the other's `start_at`) do not overlap; the buffer is only ever added to the stored appointment's end, never to the candidate's, so a candidate that ends exactly when an existing booking begins is permitted regardless of the candidate's own would-be buffer. A non-terminal appointment is one whose `status` is `SCHEDULED` or `CHECKED_IN`. An overlap is rejected with `ERR_OPERATORY_DOUBLE_BOOKED`.

When an appointment names a `treatment_plan_item_id`, booking it bubbles that item from `PLANNED` to `SCHEDULED`, and the item's `appointment_id` is set to the new appointment's `id`. These item-bubble state checks run only after the referential and double-booking checks above have passed. Bubbling an item to `SCHEDULED` requires the item's parent plan to be in `ACCEPTED` (otherwise `ERR_PLAN_NOT_ACCEPTED`), which is checked first; and if the item's `requires_predetermination` flag is true, its linked predetermination must be `APPROVED` (otherwise `ERR_PREDETERMINATION_NOT_APPROVED`) — an item flagged `requires_predetermination` that was never predetermined (its `predetermination_id` is null) is treated as not approved and likewise rejected with `ERR_PREDETERMINATION_NOT_APPROVED`.

The visit then runs through its own transitions. `FrontDesk` checks a patient in, moving the appointment from `SCHEDULED` to `CHECKED_IN`; this requires the appointment to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and the patient to be `ACTIVE` (otherwise `ERR_PATIENT_INACTIVE`). A `Clinician` completes the visit, moving it from `CHECKED_IN` to `COMPLETED`; this requires the appointment to be `CHECKED_IN` (otherwise `ERR_INVALID_STATE`), and if the appointment has a `treatment_plan_item_id` whose item is `SCHEDULED`, that item bubbles up to `COMPLETED`.

`FrontDesk` may also cancel or no-show an appointment. Cancellation moves the appointment to `CANCELLED` and is permitted from either `SCHEDULED` or `CHECKED_IN` (otherwise `ERR_INVALID_STATE`); a no-show moves it to `NO_SHOW` and is permitted only from `SCHEDULED` (otherwise `ERR_INVALID_STATE`). In both cancellation and no-show, if the linked item is `SCHEDULED` it is released back to `PLANNED` and its `appointment_id` is cleared, freeing the slot.

Finally, cancelling a treatment plan cascades into scheduling. A plan cancellation is a `FrontDesk` action permitted while the plan is in `DRAFT`, `PROPOSED`, or `ACCEPTED` (otherwise `ERR_INVALID_STATE`). It moves the plan to `CANCELLED` and, at the first cascade depth, transitions every non-terminal item — those in `PLANNED` or `SCHEDULED` — to `CANCELLED`; at the second cascade depth, for each item just cancelled that has a linked `SCHEDULED` appointment, that appointment is moved to `CANCELLED`. The plan's `total_fee_cents` and `estimated_patient_portion_cents` are then recomputed and become zero.

### 3.5. Predetermination: Frequency, Waiting Periods, and Revalidation

Before a costly procedure is scheduled, a `BillingSpecialist` may request a carrier predetermination for a treatment-plan item, supplying the `treatment_plan_item_id` and the `patient_coverage_id`. Creating the predetermination snapshots the item's fee into `submitted_fee_cents`, sets the item's `predetermination_id` to the new predetermination, and opens it in `PENDING`. A predetermination's `status` ranges over `PENDING`, `APPROVED`, `DENIED`, `EXPIRED`, and `REQUIRES_REVALIDATION`; `DENIED` and `EXPIRED` are terminal.

Two eligibility gates run at predetermination creation, both expressed in whole calendar months, and "the current date" in each is the calendar date of the logical clock (§3.9). The **waiting-period** gate applies only to items whose `category` is `MAJOR`: the procedure is eligible only if the number of whole months between the coverage's `coverage_start_date` and the current date is at least the plan's `major_waiting_period_months`; preventive and basic items skip this gate entirely. The **frequency** gate looks across all of the patient's `PAID` or `PARTIALLY_PAID` claims whose linked treatment-plan item carries the same `cdt_code` as the item being predetermined and takes the most recent such claim by adjudication date: if one exists, the procedure is eligible only if the number of whole months between that claim's adjudication date (the logical-clock calendar date captured when that claim was adjudicated) and the current date is at least the plan's `frequency_limit_months`; if no such prior paid claim exists, the frequency gate passes. In both gates, reaching exactly the threshold counts as eligible. If either gate fails, the request is rejected with `ERR_WAITING_PERIOD_NOT_MET`. Separately, if the coverage's annual maximum has already been reached, requesting a benefit-bearing predetermination is rejected with `ERR_ANNUAL_MAX_REACHED` (HTTP 402).

Approval is a `BillingSpecialist` action. It records the carrier's `approved_benefit_cents` (which must be at least zero) and a `valid_until_date` (the date the approval expires), and moves the predetermination to `APPROVED`. The same approve action serves two starting states: it is permitted when the predetermination is `PENDING`, and also when it is `REQUIRES_REVALIDATION`, in which case it re-records the benefit and validity and returns to `APPROVED`; from any other state it is rejected with `ERR_INVALID_STATE`. For this action specifically, that approvable-state check runs before the body-field validation, so an approve from an un-approvable state fails with `ERR_INVALID_STATE` even when the body is also missing `approved_benefit_cents` or `valid_until_date`. When the state is approvable, `approved_benefit_cents` and `valid_until_date` must both be present (otherwise `ERR_VALIDATION`) and `approved_benefit_cents` must be at least zero (otherwise `ERR_VALIDATION`). A `BillingSpecialist` may instead deny a `PENDING` predetermination, moving it to `DENIED` (from any other state, `ERR_INVALID_STATE`).

Two system-driven transitions also act on predeterminations. When the logical clock advances past a pending predetermination's validity window, the predetermination flips from `PENDING` to `EXPIRED`. And when a coverage's annual maximum flips from not-reached to reached during a claim adjudication, every `APPROVED` predetermination on that coverage is moved to `REQUIRES_REVALIDATION`, because the approved benefit can no longer be relied upon; such an item must be re-predetermined and re-approved before it can be scheduled.

### 3.6. Claims: Submission, Adjudication, Denial, and Void

A claim is the billing artifact that follows a completed procedure. A `BillingSpecialist` creates a claim with a `patient_id`, a `treatment_plan_item_id`, and a `patient_coverage_id`. The item must be `COMPLETED` before a claim may be created, or the request is rejected with `ERR_ITEM_NOT_COMPLETED`; and the named coverage must belong to the claim's patient, or the request is rejected with `ERR_PROVIDER_TYPE_MISMATCH`. On creation, the claim snapshots the item's fee into `billed_fee_cents`, opens with `submission_status` of `DRAFT` and `adjudication_status` of `PENDING`, and sets `carrier_paid_cents` and `patient_responsibility_cents` to zero.

A claim tracks two **independent** status dimensions. The `submission_status` dimension is `DRAFT` or `SUBMITTED`; the `adjudication_status` dimension is `PENDING`, `PAID`, `PARTIALLY_PAID`, `DENIED`, or `VOID`. They advance separately, and a claim must be submitted before it can be adjudicated.

Before submission, supporting documents are attached. A `BillingSpecialist` adds a claim attachment carrying an `attachment_type` — one of `XRAY`, `PERIO_CHART`, `NARRATIVE`, or `PHOTO` — and a `document_ref`, an opaque storage handle for the attached document; the attachment's `claim_id` comes from the path. Submitting the claim, a `BillingSpecialist` action, advances `submission_status` from `DRAFT` to `SUBMITTED`; it requires the claim to be in `DRAFT` submission status (otherwise `ERR_INVALID_STATE`) and at least one attachment to exist (otherwise `ERR_CLAIM_MISSING_ATTACHMENT`).

Adjudication is the heart of the billing flow. A `BillingSpecialist` adjudicates a submitted claim; this requires `submission_status` to be `SUBMITTED` (otherwise `ERR_CLAIM_NOT_SUBMITTED`) and `adjudication_status` to be `PENDING` (otherwise `ERR_INVALID_STATE`). The system computes `carrier_paid_cents` using the chronological adjudication calculation of §3.8 and sets `patient_responsibility_cents` to `billed_fee_cents` minus `carrier_paid_cents`. The resulting adjudication status reflects whether the annual-maximum clamp bit: when the carrier payment equals the gross benefit the claim becomes `PAID`, and when the carrier payment is less than the gross benefit — because the live remaining annual maximum clamped it — the claim becomes `PARTIALLY_PAID`. Both outcomes drive the identical cascade chain: at depth one the coverage's `annual_benefit_used_cents` is increased by `carrier_paid_cents` and its `deductible_met_cents` is increased by the deductible this claim consumed (the smaller of the coverage's remaining deductible at adjudication time and the claim's `billed_fee_cents`); at depth two, if `annual_benefit_used_cents` has reached or exceeded the plan's `annual_maximum_cents`, the coverage's `annual_max_reached` is set true; at depth three, if that flag has just flipped from false to true, every `APPROVED` predetermination on that coverage moves to `REQUIRES_REVALIDATION`; and finally the patient's `balance_owed_cents` is recomputed.

A carrier denial is a separate `BillingSpecialist` action moving `adjudication_status` from `PENDING` to `DENIED`; it requires the claim to be `PENDING` (otherwise `ERR_INVALID_STATE`), sets `carrier_paid_cents` to zero and `patient_responsibility_cents` to the full `billed_fee_cents`, and recomputes the patient's `balance_owed_cents`. Because denial pays nothing, it does not touch the coverage accumulator.

Voiding reverses a paid claim. A `BillingSpecialist` voids a claim, moving `adjudication_status` to `VOID`; this is permitted only when the claim is `PAID` or `PARTIALLY_PAID` (otherwise `ERR_CLAIM_NOT_VOIDABLE`) and only when no `ACTIVE` payment plan references the claim (otherwise `ERR_CLAIM_HAS_ACTIVE_PAYMENT_PLAN`). As compensation, the void subtracts the claim's `carrier_paid_cents` back out of the coverage's `annual_benefit_used_cents`, restores `deductible_met_cents` by subtracting the deductible this claim consumed at adjudication, recomputes `annual_max_reached` (which may flip from true back to false), and recomputes the patient's `balance_owed_cents`. The void leaves the claim's own `carrier_paid_cents` and `patient_responsibility_cents` fields at the values they held when adjudicated — they are not zeroed — but the recomputed `balance_owed_cents` no longer counts this claim because the §3.1 total excludes `VOID` claims. The accumulator is conserved across the adjudicate-then-void round trip.

### 3.7. Recare Recall and Financing Patient Responsibility

Recare recall keeps patients on a hygiene cadence. A `FrontDesk` user creates a recall with a `patient_id`, a `recall_type` that is one of `PROPHY`, `PERIO_MAINT`, or `EXAM`, an `interval_months` cadence (greater than zero), and a `last_visit_date` baseline. The system computes `next_due_date` as the `last_visit_date` plus `interval_months` of calendar time, and opens the recall in `ACTIVE`; recall `status` is one of `ACTIVE` or `DUE`. When the logical clock reaches or passes a recall's `next_due_date`, the recall flips from `ACTIVE` to `DUE`. Fulfilling a recall is a `FrontDesk` action that supplies a `visit_date`: it sets `last_visit_date` to that date, recomputes `next_due_date` as `visit_date` plus `interval_months`, and resets `status` to `ACTIVE`, rolling the cadence forward.

Financing closes the loop on patient responsibility. A `BillingSpecialist` creates a payment plan against an adjudicated claim by supplying a `patient_id`, the `claim_id`, an `installment_count`, and the `expected_claim_version` that §2.7 requires. On creation, the plan snapshots `claim.patient_responsibility_cents` into `principal_cents`, computes the installment schedule below, opens with `status` `ACTIVE` and `amount_posted_cents` of zero, increments the target claim's `version` by one, and recomputes the patient's `balance_owed_cents`. The `installment_count` must be an integer between 1 and 60 — this is body validation (`ERR_VALIDATION`) and is checked before the §2.7 optimistic-concurrency check. The snapshotted `principal_cents` must be greater than zero, otherwise `ERR_VALIDATION`; because the principal depends on the resolved claim's current `patient_responsibility_cents`, this check runs after the optimistic-concurrency check rather than before it. Payment-plan `status` is one of `ACTIVE`, `PAID_OFF`, or `DEFAULTED`.

The installment schedule uses a pinned divide-then-floor order. The base per-installment amount is the principal divided by the installment count, floored to whole cents; `installment_amount_cents` is that base and applies to the first `installment_count` minus one installments. The `final_installment_cents` is whatever remains — the principal minus the base multiplied by one less than the installment count — so the final installment absorbs the rounding remainder, and the base multiplied by one-less-than-the-count plus the final installment equals the principal exactly. The `remaining_balance_cents` is the `principal_cents` minus `amount_posted_cents`.

Posting an installment is a `BillingSpecialist` action supplying an `amount_cents`: it increases `amount_posted_cents` by that amount, recomputes `remaining_balance_cents`, and recomputes the patient's `balance_owed_cents`; the moment `amount_posted_cents` reaches or exceeds `principal_cents`, the plan flips to `PAID_OFF` with `remaining_balance_cents` of zero — this can happen before all installments are posted. The supplied `amount_cents` is added as given and is not validated for sign or against the remaining balance, and posting or reversing an installment never alters the underlying claim's `patient_responsibility_cents`. Reversing the most recent installment is a `BillingSpecialist` compensation supplying an `amount_cents`: it decreases `amount_posted_cents` by that amount, recomputes `remaining_balance_cents` and the patient's `balance_owed_cents`, and if the plan was `PAID_OFF` and the reversal drops `amount_posted_cents` back below `principal_cents`, the plan reverts to `ACTIVE`. A `BillingSpecialist` may also default an `ACTIVE` plan (otherwise `ERR_INVALID_STATE`), moving it to `DEFAULTED`. The "return to balance" of a `DEFAULTED` (or `PAID_OFF`) plan is effected by the §3.1 recompute, not by adding `remaining_balance_cents`: because the patient's `balance_owed_cents` is recomputed as the sum of `patient_responsibility_cents` over claims not covered by an `ACTIVE` plan, a plan leaving `ACTIVE` causes its claim's full `patient_responsibility_cents` to re-enter that sum — regardless of how much had already been posted — and while a plan is `ACTIVE` its claim contributes nothing to the balance no matter what has been posted.

### 3.8. Estimated Versus Adjudicated Benefit

Both benefit calculations share the same deductible-and-coinsurance arithmetic against the coverage described in §2.9, but they read the ledger at different moments and serve different purposes. Both produce integer cents, and the coinsurance product is floored before any clamp.

The **forward-looking estimate** runs when a plan is proposed, once per `PLANNED` item, and is purely informational — it never rejects on waiting or frequency grounds. The system selects the patient's coverage as the `ACTIVE` `PatientCoverage` with the latest `coverage_start_date`, breaking ties by the earliest `created_at`; if the patient has no active coverage, the item's `estimated_insurance_cents` is zero. Otherwise it picks the coinsurance percentage by the item's `category` — `preventive_coinsurance_pct` for `PREVENTIVE`, `basic_coinsurance_pct` for `BASIC`, `major_coinsurance_pct` for `MAJOR`. It computes the remaining deductible as the plan's `deductible_cents` minus the coverage's current `deductible_met_cents`, floored at zero; the deductible applied is the smaller of that remaining deductible and the item's `fee_cents`; and the amount after deductible is the item's `fee_cents` minus the deductible applied. The gross benefit is the amount after deductible multiplied by the chosen coinsurance percentage, divided by 100, with any fraction dropped. The remaining annual maximum is the plan's `annual_maximum_cents` minus the coverage's current `annual_benefit_used_cents`, floored at zero. The item's `estimated_insurance_cents` is the smaller of the gross benefit and that remaining annual maximum, and its `estimated_patient_portion_cents` is the item's `fee_cents` minus `estimated_insurance_cents`. Because this estimate reads the accumulator as it stands now and ignores other in-flight planned items, it is a best-case forward view.

The **chronological adjudication** runs when a submitted claim is adjudicated and uses the *live* accumulator as it stands at that moment, after every previously adjudicated claim has already debited it. It selects the coinsurance percentage by the item's `category` exactly as the estimate does. The remaining deductible is the plan's `deductible_cents` minus the coverage's live `deductible_met_cents`, floored at zero; the deductible applied is the smaller of that and the claim's `billed_fee_cents`; the amount after deductible is `billed_fee_cents` minus the deductible applied; and the gross benefit is the amount after deductible multiplied by the chosen coinsurance percentage divided by 100, with the fraction dropped. The remaining annual maximum is the plan's `annual_maximum_cents` minus the coverage's live `annual_benefit_used_cents`, floored at zero, and `carrier_paid_cents` is the smaller of the gross benefit and that remaining annual maximum. When `carrier_paid_cents` equals the gross benefit the claim is `PAID`; when it is less, the annual-maximum clamp has bitten and the claim is `PARTIALLY_PAID`. Because the live accumulator reflects all earlier paid claims, an identical fee can adjudicate to a smaller benefit than its earlier estimate once the annual pool has been partially consumed.

The annual accumulator that both calculations read is the coverage's stored `annual_benefit_used_cents` as maintained per §2.9 — a conserved running total that adjudication of a `PAID`/`PARTIALLY_PAID` claim increases and a void of that claim decreases, with no benefit-year-window filter applied to the total. The coverage's `annual_max_reached` is true exactly when that stored total has reached or exceeded the plan's `annual_maximum_cents`; reaching the maximum exactly trips it.

### 3.9. The Deterministic Clock

Because waiting periods, frequency gaps, recare due dates, and predetermination expiry all turn on the passage of time, the system exposes an administrative capability — shared by `FrontDesk` and `BillingSpecialist` — that sets the logical system clock to a supplied `now_iso8601` instant. Setting the clock returns `200 OK` with a `data` object of the single field `now_iso8601` echoing the supplied instant (it does not return any entity). Advancing the clock is what drives the time-based transitions described above: every recare recall whose `next_due_date` is at or before the new current time (the comparison is on the calendar date) flips from `ACTIVE` to `DUE`, and every `PENDING` predetermination whose validity date has strictly passed — the current date is strictly later than `valid_until_date`, so reaching the validity date exactly does not yet expire it — flips to `EXPIRED`. The waiting-period and frequency evaluations of §3.5, and the recare due computation of §3.7, all read this clock as their notion of "now."

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource — including every state transition and every lifecycle action — return a `200 OK` status code. List and read operations also return `200 OK`. Request bodies, response shapes, and side effects are not repeated here; they are specified in the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patients` | Register a patient | FrontDesk |
| GET | `/patients` | List patients | FrontDesk, Clinician, BillingSpecialist |
| GET | `/patients/{patientId}` | Get a patient | FrontDesk, Clinician, BillingSpecialist, Patient |
| POST | `/patients/{patientId}/deactivate` | Mark a patient INACTIVE | FrontDesk |
| POST | `/patients/{patientId}/tooth-chart` | Record a tooth-chart entry | Clinician |
| GET | `/tooth-chart-entries` | List tooth-chart entries | FrontDesk, Clinician, BillingSpecialist, Patient |
| GET | `/tooth-chart-entries/{toothChartEntryId}` | Get a tooth-chart entry | FrontDesk, Clinician, BillingSpecialist, Patient |
| POST | `/providers` | Create a provider | FrontDesk |
| GET | `/providers` | List providers | FrontDesk, Clinician, BillingSpecialist |
| GET | `/providers/{providerId}` | Get a provider | FrontDesk, Clinician, BillingSpecialist, Patient |
| POST | `/providers/{providerId}/deactivate` | Mark a provider INACTIVE | FrontDesk |
| POST | `/operatories` | Create an operatory | FrontDesk |
| GET | `/operatories` | List operatories | FrontDesk, Clinician, BillingSpecialist |
| GET | `/operatories/{operatoryId}` | Get an operatory | FrontDesk, Clinician, BillingSpecialist |
| POST | `/operatories/{operatoryId}/close` | Close an operatory | FrontDesk |
| POST | `/insurance-plans` | Create an insurance plan | BillingSpecialist |
| GET | `/insurance-plans/{insurancePlanId}` | Get an insurance plan | BillingSpecialist, Clinician, FrontDesk |
| POST | `/patient-coverages` | Attach a plan to a patient | BillingSpecialist |
| GET | `/patient-coverages` | List patient coverages | BillingSpecialist, Clinician, FrontDesk |
| GET | `/patient-coverages/{patientCoverageId}` | Get a patient coverage | BillingSpecialist, Clinician, FrontDesk, Patient |
| POST | `/patient-coverages/{patientCoverageId}/terminate` | Terminate a coverage | BillingSpecialist |
| POST | `/treatment-plans` | Create a treatment plan | Clinician |
| GET | `/treatment-plans` | List treatment plans | Clinician, FrontDesk, BillingSpecialist |
| GET | `/treatment-plans/{treatmentPlanId}` | Get a treatment plan | Clinician, FrontDesk, BillingSpecialist, Patient |
| POST | `/treatment-plans/{treatmentPlanId}/items` | Add a planned procedure | Clinician |
| GET | `/treatment-plan-items` | List treatment-plan items | Clinician, FrontDesk, BillingSpecialist, Patient |
| GET | `/treatment-plan-items/{treatmentPlanItemId}` | Get a treatment-plan item | Clinician, FrontDesk, BillingSpecialist, Patient |
| POST | `/treatment-plans/{treatmentPlanId}/propose` | Propose a plan; compute estimates | Clinician |
| POST | `/treatment-plans/{treatmentPlanId}/revise` | Revise a plan back to DRAFT | Clinician |
| POST | `/treatment-plans/{treatmentPlanId}/accept` | Accept a plan | FrontDesk |
| POST | `/treatment-plans/{treatmentPlanId}/complete` | Complete a plan | Clinician |
| POST | `/treatment-plans/{treatmentPlanId}/cancel` | Cancel a plan; cascade items and appointments | FrontDesk |
| POST | `/appointments` | Schedule an appointment | FrontDesk |
| GET | `/appointments` | List appointments | FrontDesk, Clinician, BillingSpecialist |
| GET | `/appointments/{appointmentId}` | Get an appointment | FrontDesk, Clinician, BillingSpecialist, Patient |
| POST | `/appointments/{appointmentId}/check-in` | Check a patient in | FrontDesk |
| POST | `/appointments/{appointmentId}/complete` | Complete a visit; bubble linked item | Clinician |
| POST | `/appointments/{appointmentId}/cancel` | Cancel an appointment | FrontDesk |
| POST | `/appointments/{appointmentId}/no-show` | Mark a no-show | FrontDesk |
| POST | `/predeterminations` | Request a predetermination | BillingSpecialist |
| GET | `/predeterminations` | List predeterminations | BillingSpecialist, Clinician, FrontDesk |
| GET | `/predeterminations/{predeterminationId}` | Get a predetermination | BillingSpecialist, Clinician, FrontDesk |
| POST | `/predeterminations/{predeterminationId}/approve` | Approve or re-approve a predetermination | BillingSpecialist |
| POST | `/predeterminations/{predeterminationId}/deny` | Deny a predetermination | BillingSpecialist |
| POST | `/claims` | Create a claim for a completed item | BillingSpecialist |
| GET | `/claims` | List claims | BillingSpecialist, Clinician, FrontDesk |
| GET | `/claims/{claimId}` | Get a claim | BillingSpecialist, Clinician, FrontDesk, Patient |
| POST | `/claims/{claimId}/attachments` | Attach a document to a claim | BillingSpecialist |
| GET | `/claims/{id}/attachments` | List a claim's attachments | BillingSpecialist, Clinician, FrontDesk |
| POST | `/claims/{claimId}/submit` | Submit a claim to the carrier | BillingSpecialist |
| POST | `/claims/{claimId}/adjudicate` | Adjudicate a submitted claim | BillingSpecialist |
| POST | `/claims/{claimId}/deny` | Record a carrier denial | BillingSpecialist |
| POST | `/claims/{claimId}/void` | Void a paid claim | BillingSpecialist |
| POST | `/recare-recalls` | Create a recare recall | FrontDesk |
| GET | `/recare-recalls` | List recare recalls | FrontDesk, Clinician, BillingSpecialist |
| GET | `/recare-recalls/{recareRecallId}` | Get a recare recall | FrontDesk, Clinician, BillingSpecialist, Patient |
| POST | `/recare-recalls/{recareRecallId}/fulfill` | Fulfill a recall and roll the cadence | FrontDesk |
| POST | `/payment-plans` | Finance a claim's patient responsibility | BillingSpecialist |
| GET | `/payment-plans` | List payment plans | BillingSpecialist, FrontDesk |
| GET | `/payment-plans/{paymentPlanId}` | Get a payment plan | BillingSpecialist, FrontDesk, Patient |
| POST | `/payment-plans/{paymentPlanId}/post-installment` | Post an installment payment | BillingSpecialist |
| POST | `/payment-plans/{paymentPlanId}/reverse-installment` | Reverse the most recent installment | BillingSpecialist |
| POST | `/payment-plans/{paymentPlanId}/default` | Mark a payment plan DEFAULTED | BillingSpecialist |
| POST | `/_clock/set` | Set the deterministic system clock | FrontDesk, BillingSpecialist |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_OPERATORY_NOT_FOUND` | 404 Not Found |
| `ERR_INSURANCE_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_COVERAGE_NOT_FOUND` | 404 Not Found |
| `ERR_TREATMENT_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PREDETERMINATION_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_HAS_NO_ITEMS` | 409 Conflict |
| `ERR_PLAN_NOT_ACCEPTED` | 409 Conflict |
| `ERR_PLAN_ITEMS_NOT_COMPLETE` | 409 Conflict |
| `ERR_PREDETERMINATION_NOT_APPROVED` | 409 Conflict |
| `ERR_ITEM_NOT_COMPLETED` | 409 Conflict |
| `ERR_CLAIM_MISSING_ATTACHMENT` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_VOIDABLE` | 409 Conflict |
| `ERR_CLAIM_HAS_ACTIVE_PAYMENT_PLAN` | 409 Conflict |
| `ERR_PROVIDER_TYPE_MISMATCH` | 409 Conflict |
| `ERR_PATIENT_INACTIVE` | 409 Conflict |
| `ERR_OPERATORY_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_WAITING_PERIOD_NOT_MET` | 409 Conflict |
| `ERR_ANNUAL_MAX_REACHED` | 402 Payment Required |
