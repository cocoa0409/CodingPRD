# Home Infusion Therapy API — Product Requirements Document

## 1. Introduction

Home infusion pharmacies coordinate a long, branching clinical and financial workflow: a referral arrives from a prescribing physician, a specialty or non-specialty drug order is built and (when needed) sent to the payer for prior authorization, the compounding pharmacy reserves vials and pairs a pump for delivery, visiting nurses administer the therapy over a planned course of days, laboratory monitoring guards safety, and the whole episode is finally adjudicated and billed against a payer plan. This document specifies the backend API that runs that lifecycle end to end. It is written for the engineers who will implement the service and must capture every state transition, every cascade, every safety gate, and every monetary calculation precisely enough that two independent implementations would agree on every byte of output.

The system is, at its financial core, a **ledger-reconciliation** engine. Every claim is computed twice from the same underlying order: once as an **estimate** when the claim is drafted (using the *planned* number of infusion days) and once as a **final** figure when the claim is posted (using the *actually administered* number of days). The two passes share one formula and differ only in their day basis, and the final post is the only event that moves money on the payer plan's accumulators. Layered on top of this ledger is a **compliance and audit** regime: specialty drugs cannot be released without an approved authorization, trough-monitored therapies cannot proceed past their fourth visit without a timely lab, severe adverse reactions automatically freeze an order, and the clinician who reports a reaction is structurally barred from clearing the hold it produced.

Because the workflow is deeply interconnected — a single discontinuation can ripple through visits, compounds, inventory, and billing in one atomic request — correctness depends on the reader internalizing not just each endpoint in isolation but the way one action's side effects become another's preconditions. The sections below first fix the global contract (Section 2), then narrate the business workflows where the real logic lives (Section 3), and finally summarize the HTTP surface (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the test-driving clock endpoint must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Authentication is checked before authorization, and both are checked before any resource is looked up.

There are seven roles, spelled exactly as follows: `IntakeCoordinator`, `Pharmacist`, `AuthSpecialist`, `VisitingNurse`, `MedicalDirector`, `Biller`, and `WarehouseClerk`. Their responsibilities partition the workflow:

- An `IntakeCoordinator` registers patients, nurses, and referrals, accepts or rejects referrals, and schedules visits.
- A `Pharmacist` owns the drug catalog, infusion orders, compounding, and pump pairing.
- An `AuthSpecialist` manages prior authorizations for specialty drugs.
- A `VisitingNurse` completes and misses visits, records labs, and reports adverse events.
- A `MedicalDirector` adjudicates adverse-event holds, discontinues orders, and records labs and adverse events.
- A `Biller` owns payer plans and the claim lifecycle.
- A `WarehouseClerk` owns supply-kit shipping and pump registration.

For six of the seven roles — `IntakeCoordinator`, `Pharmacist`, `AuthSpecialist`, `MedicalDirector`, `Biller`, and `WarehouseClerk` — the `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow demands it — for example, when an adverse event is reported the reporting operator's identifier is stored as `reported_by_user_id` and the reporting role as `reported_by_role` on the `AdverseEvent` — but it never compares the opaque identifier to any entity's `id`. The one exception is the `VisitingNurse` role: when `X-User-Role` is `VisitingNurse`, the `X-User-ID` is the `id` of the acting `Nurse`. This entity-backed identity exists so that the segregation-of-duties rule described later can compare the operator who clears a hold against the operator who reported the event regardless of which role each holds.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a request for more than 100 items is capped at 100. The `offset` defaults to 0 and has a minimum of 0. Lists are always returned sorted by `created_at` in ascending order, so the oldest matching resource appears first. The pagination block exposed in the `meta` object reports `limit`, `offset`, `total_count` (the count of all matching resources before the window is applied), and `has_more` (true when resources remain beyond the current window).

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp (same format) and an integer `version`. The `version` begins at 1 when the resource is created and increments by exactly 1 on every mutation of that resource. Whenever a field on a resource changes — whether by a direct operation or by a cascade triggered elsewhere — that resource's `updated_at` is refreshed to the current logical time and its `version` is incremented. A read never changes either value.

The logical clock matters because several windows in this system are time-relative. The server maintains a logical clock whose startup default is `2026-05-01T00:00:00Z`; before any clock-setting call the clock reads exactly this default and never falls back to wall-clock time. An administrative test-driving capability advances this clock to a supplied instant carried as `to_iso8601` in the request body, and all temporal windows — lab monitoring windows, reservation intervals — are evaluated against it.

### 2.5. Monetary Precision and Rounding

All money in this system is represented as integer cents; there are no floating-point currency amounts. Where a calculation produces a fractional cent, it is rounded **half up** (a value at the exact half rounds away from zero to the next whole cent) and the rounding is applied at the specific point each calculation names — never deferred to the end of a multi-step formula. Day counts, vial counts, and severity scores are exact integers and are never rounded. The precise points at which rounding occurs are stated within the billing narratives in Section 3, because the order of rounding relative to discounting and the order of bucket allocation are themselves part of the contract.

### 2.6. Nested Resource Access and Referential Resolution

Resources are addressed as flat collections joined by foreign-key fields carried in request bodies; the API does not nest one resource's path inside another's. When a request references one or more resource identifiers — whether in the URL path or the request body — each identifier must resolve to an existing entity, and identifiers in the path are validated left to right. A reference that does not resolve is rejected with `ERR_NOT_FOUND` (HTTP 404). This existence check runs after authentication and authorization but before any business rule, so a request that names a non-existent order never reaches the state or safety checks that would otherwise apply.

### 2.7. Optimistic Concurrency on Order Versions

Claim creation is guarded by optimistic concurrency control on the order it bills. When a `Biller` creates a claim, the request must carry `expected_order_version`, which is the `version` of the target `InfusionOrder` as the client last observed it. The server compares `expected_order_version` against the order's current `version`. If they differ — because some intervening operation (a visit completion, a hold, a discontinuation cascade, or any other mutation) has advanced the order's version since the client last read it — the create is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). This protects the billable-day basis: a new claim may legitimately supersede a prior draft claim for the same order, so the server cannot infer staleness from state alone, and the version pin is the only signal that the client is working from an out-of-date view. No other endpoint in this system takes a version field; only claim creation carries `expected_order_version`.

### 2.8. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) authorization of the role (`ERR_FORBIDDEN_ROLE`); (3) existence of every referenced resource (`ERR_NOT_FOUND`); (4) structural validity of the body — required fields present and well-typed, enum members drawn from the allowed set, numeric constraints honored (`ERR_INVALID_REQUEST`, HTTP 422); (5) state legality, i.e. the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409); and then the domain-specific business rules. Among the business rules, segregation of duties, the lab-monitoring gate, nurse licensure, authorization-required release, pump and nurse scheduling overlaps, inventory sufficiency, authorization-unit ceilings, the order-version concurrency check, and therapy-completion sufficiency are each described in their workflow context in Section 3; where two business rules could both apply to one endpoint, the section that introduces them states their relative order.

### 2.9. The Inventory Conservation Invariant

Drug vials are a conserved quantity. For each `DrugCatalog` lot, the sum of `on_hand_vials` (unreserved vials available to draw) plus the vials currently committed to live compounds (those reserved by compounds in `COMPOUNDED` or `DELIVERED` status) always equals `lot_total_vials`. At catalog registration `on_hand_vials` is initialized to `lot_total_vials`. Reserving vials for a compound debits `on_hand_vials`; wasting a compound that had reserved vials credits them back. No operation may ever drive `on_hand_vials` below zero, and the conservation equality holds after every request completes.

### 2.10. The Payer Accumulator Invariant

A payer plan tracks two running accumulators, `deductible_remaining_cents` and `oop_max_remaining_cents`, that represent how much of the patient's deductible and out-of-pocket maximum remain to be met. These accumulators are read but **not** changed while a claim is only an estimate. They move only when a claim is posted, and they move back, by exactly the same amounts, if that claim is later voided — so that a post followed by a void returns the plan to its pre-post accumulator values. This compensating symmetry is what lets billing corrections be made without permanently corrupting a patient's benefit balances.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Drugs, Plans, Nurses, Pumps, and Patients

Before any clinical work begins, the operational reference data must exist. A `Pharmacist` registers a drug and its lot by supplying the `ndc_code` (the National Drug Code, which must be unique across the catalog), the `generic_name`, the `therapy_category`, the `vial_size_mg` (milligrams of active drug per vial, which must be greater than zero), the `awp_per_vial_cents` (the Average Wholesale Price per vial in integer cents, which must be at least zero), and the `lot_total_vials` (which must be at least zero). Two booleans may be supplied and each defaults to false when omitted: `is_specialty`, which marks a drug that requires an approved authorization before its order may be released, and `requires_trough_lab`, which marks a drug whose therapy demands a timely trough lab before the fourth visit may complete. On registration the server sets `on_hand_vials` equal to `lot_total_vials`. The `therapy_category` must be one of `ANTI_INFECTIVE`, `AMINOGLYCOSIDE_OR_VANCO`, `TPN`, `IMMUNE_GLOBULIN`, or `CHEMO`; it selects both the per-diem rate and the lab-monitoring policy downstream.

A `Biller` registers a payer plan with a `plan_code` (unique across plans), a `per_diem_rate_cents` map keyed by therapy category, an `awp_discount_pct` (the fraction subtracted from the gross AWP amount when adjudicating drug lines, which must be at least zero and strictly less than one), a `coinsurance_pct` (the patient's coinsurance fraction, which must be at least zero and at most one), and the two opening accumulators `deductible_remaining_cents` and `oop_max_remaining_cents` (each at least zero). The `per_diem_rate_cents` object maps a therapy category to its per-diem rate in integer cents — for example a plan might pay 12,500 cents per day for anti-infective therapy and 22,000 cents per day for total parenteral nutrition.

An `IntakeCoordinator` registers nurses and patients. A nurse is created with a `full_name`, a `license_state` (two uppercase letters), and an optional `status` that defaults to `ACTIVE` and is otherwise `INACTIVE`. A patient is created with a `full_name`, a `service_state` (two uppercase letters, the state where infusion is delivered), and a `payer_plan_id` naming the patient's active plan; the patient's own `status` begins `ACTIVE` and becomes `DISCHARGED` only through patient lifecycle handling. Pumps are registered by a `WarehouseClerk` or a `Pharmacist` with an `asset_tag` (a unique durable identifier), a `model` of either `AMBULATORY` or `STATIONARY`, and an optional `status` that defaults to `AVAILABLE` and is otherwise `RETIRED`.

### 3.2. Intake: Referral Receipt, Acceptance, and Order Creation

The clinical episode opens when an `IntakeCoordinator` records a referral for a patient, supplying the `patient_id`, the `referring_provider_npi` (the referring physician's NPI), and the `diagnosis_code` (the ICD-10 code driving therapy). A new referral begins in `RECEIVED`. From there the coordinator either accepts it, moving `RECEIVED` to `ACCEPTED`, or rejects it, moving `RECEIVED` to `REJECTED` — and `REJECTED` is terminal. Acceptance is permitted only while the referral is still `RECEIVED` and only if the patient it names exists and is `ACTIVE`. Rejection is likewise permitted only from `RECEIVED`. Attempting either transition from any other state yields `ERR_INVALID_STATE`. Each transition increments the referral's `version`.

Once a referral is `ACCEPTED`, a `Pharmacist` builds the infusion order against it. The order create carries the `referral_id`, the `drug_id`, the administration `route` (one of `IV`, `SUBQ`, or `INTRATHECAL`), the `daily_dose_mg` (milligrams per infusion day, greater than zero), the `frequency_per_day` (at least one), the `start_date` (which anchors the lab-monitoring window), and the `scheduled_days` (the planned billable count of infusion days, at least one). The referenced referral must be in `ACCEPTED`; building an order against a referral in any other state is rejected with `ERR_INVALID_STATE`. Per the validation ordering of Section 2.8, this referral-state check is a state-legality check (priority 5), evaluated only after the referenced `referral_id` and `drug_id` have resolved (priority 3) and the body fields have been validated (priority 4). The server copies `patient_id` onto the order from the referral, sets `administered_days` to 0, and places the order in `DRAFT`. The order's `hold_reason` is null at creation and is only ever set to `ADVERSE_EVENT` or `LAB_OVERDUE` when the order is held.

### 3.3. Authorization Path and Order Release

Submitting a `DRAFT` order is where the specialty branch forks. When a `Pharmacist` submits the order, the server inspects the referenced drug. If the drug's `is_specialty` is true, the order moves from `DRAFT` to `PENDING_AUTH`, signaling that payer authorization is required before therapy may proceed. If the drug's `is_specialty` is false, the same submit instead moves the order directly from `DRAFT` to `RELEASED`, skipping authorization entirely. Both branches require the order to be in `DRAFT` and both increment the order's `version`. A specialty order may never reach `RELEASED` without an approved authorization; an attempt to release one without it is barred with `ERR_AUTH_REQUIRED`.

For a `PENDING_AUTH` order, an `AuthSpecialist` submits a prior authorization carrying the `order_id` and the `requested_units` (vials requested, greater than zero). The server copies the `payer_plan_id` onto the authorization from the order's patient and places it in `SUBMITTED` with `approved_units` of 0. The specialist then either approves or denies it, and only while it is `SUBMITTED`.

Approval requires that the referenced order is itself still `PENDING_AUTH`. On approval the authorization moves `SUBMITTED` to `APPROVED`, the `approved_units` are set from the approval request body, and the order is cascaded from `PENDING_AUTH` to `RELEASED` in the same request; both the authorization's and the order's `version` increment. Denial moves `SUBMITTED` to `DENIED` and cascades in the opposite direction: the order is driven from `PENDING_AUTH` to `DISCONTINUED`, and as part of that same cascade every supply kit for that order still in `PICKING` is moved to `CANCELLED`. Both `APPROVED` and `DENIED` are terminal authorization states. The `approved_units` figure recorded at approval is later compared against the vials a compound needs, so under-approving relative to what the order requires is allowed at approval time but will block compounding downstream.

### 3.4. Compounding, Pump Pairing, and the Inventory Draw

A compound batch ties a released order to a physical pump and a delivery window. A `Pharmacist` creates the compound with the `order_id`, the `pump_id` of the paired pump, the `delivery_at` (when the pump and compound are delivered, the start of the reservation interval), and the `retrieval_at` (when the pump is retrieved, the end of the interval, treated as half-open). The new compound begins in `ORDERED` with `vials_reserved` of 0.

Preparing the batch — advancing it from `ORDERED` to `COMPOUNDED` — is the step that actually draws inventory and is gated by several checks. The compound must be in `ORDERED`, and the order it serves must be in `RELEASED` or `ACTIVE`. The number of vials the batch needs is the daily dose multiplied by the planned day count, divided by the vial size, rounded **up** to the next whole vial: that is, the daily dose in milligrams times `scheduled_days`, divided by the drug's `vial_size_mg`, with any remainder forcing one additional whole vial. Compounding may not reserve more vials than the drug's current `on_hand_vials`; a shortfall is rejected with `ERR_INSUFFICIENT_INVENTORY`. If the order went through authorization, the required vial count must not exceed the authorization's `approved_units`; needing more than was approved is rejected with `ERR_AUTH_UNITS_EXCEEDED`. The paired pump must be `AVAILABLE` and free of any conflicting reservation over the requested window (the overlap rule is detailed in Section 3.5); a collision is rejected with `ERR_PUMP_DOUBLE_BOOKED`. When all checks pass, the server sets the compound's `vials_reserved` to that computed whole-vial count, debits the drug's `on_hand_vials` by the same amount, and increments the compound's `version`. A `COMPOUNDED` batch may then be advanced from `COMPOUNDED` to `DELIVERED`. Both `DELIVERED` and `WASTED` are terminal compound states; the `WASTED` path is reached only through cascades and is described in Section 3.8.

### 3.5. Pump Reservation Geometry

Each compound occupies its pump across the half-open window from its `delivery_at` up to its `retrieval_at`, followed by a trailing reprocessing buffer of one full day — that is, 1,440 minutes — appended to the **end** of the existing reservation only. The conflict test considers only other compounds on the same `pump_id` whose status is `COMPOUNDED` or `DELIVERED`. A candidate compound conflicts with such an existing reservation when the candidate's `delivery_at` falls strictly before the existing reservation's `retrieval_at` plus the 1,440-minute buffer, and at the same time the candidate's `retrieval_at` falls strictly after the existing reservation's `delivery_at`. Because the buffer is attached only to the trailing end, a new reservation whose `delivery_at` is exactly at the existing `retrieval_at` plus the buffer does not conflict — the boundary is inclusive on the start side, so starting precisely when the buffer ends is allowed. This trailing-only, half-open geometry is deliberately distinct from the nurse-scheduling geometry described next.

### 3.6. Visit Scheduling, Nurse Eligibility, and Schedule Overlap

Nursing visits are scheduled against a released order. An `IntakeCoordinator` or a `VisitingNurse` schedules a visit with the `order_id`, the `nurse_id` of the assigned clinician, an optional `compound_id` (the compound this visit administers, left null for a teach-only visit), a `visit_type` of either `TEACH` or `ADMINISTER`, a `start_at`, and a `duration_min` (minutes, greater than zero). The server computes the visit's `sequence_index` — the 1-based ordinal of the visit within its order, ordered by `start_at` ascending and breaking ties by `created_at` ascending — and places the visit in `SCHEDULED`.

Two referential and temporal checks guard scheduling. The assigned nurse must be licensed in the patient's service area and available: the nurse's `license_state` must equal the order's patient's `service_state` and the nurse's `status` must be `ACTIVE`; otherwise the request is rejected with `ERR_NURSE_NOT_LICENSED`. The visit must also not overlap another commitment of the same nurse. For nurse scheduling, a visit occupies the **closed** interval from its `start_at` through `start_at` plus its `duration_min`, expanded by a **symmetric** travel buffer of 60 minutes on **both** ends. The conflict test considers other visits for the same `nurse_id` whose status is `SCHEDULED` or `COMPLETED`. A candidate conflicts when the candidate's `start_at` falls before the existing visit's `start_at` plus its `duration_min` plus 60 minutes, and at the same time the candidate's `start_at` plus its `duration_min` plus 60 minutes falls after the existing visit's `start_at`. A detected overlap is rejected with `ERR_NURSE_DOUBLE_BOOKED`. Note the contrast with pump geometry: the nurse buffer is symmetric and the endpoints are closed, whereas the pump buffer is trailing-only and the window is half-open.

### 3.7. Visit Completion, Order Activation, and the Lab-Monitoring Gate

Completing a scheduled visit advances it from `SCHEDULED` to `COMPLETED` and is the event that brings an order to life. The visit must be `SCHEDULED` and its order must be in `RELEASED` or `ACTIVE`. When the visit being completed is the first `COMPLETED` visit for its order, completing it cascades the order from `RELEASED` to `ACTIVE`. On every completion the server recomputes the order's `administered_days` as the count of that order's nursing visits that are in `COMPLETED` (visits in `SCHEDULED`, `MISSED`, or `CANCELLED` are excluded from the count). The visit's `version` increments, and where the order changes its `version` increments too.

Completion is also where trough monitoring is enforced. If the visit's `sequence_index` is at least 4 and the order's drug has `requires_trough_lab` set to true, the visit may complete only when a trough lab already exists in the monitoring window — specifically, a `LabResult` of `lab_type` `TROUGH` whose `collected_at` falls on or after the order's `start_date` and on or before the order's `start_date` plus the lab-due horizon. The lab-due horizon is a fixed monitoring window measured in days from the start date. If no such trough lab exists when a fourth-or-later visit on a trough-monitored order tries to complete, the completion is blocked with `ERR_LAB_OVERDUE`, and an overdue lab is one of the two conditions that can place the order on hold (see Section 3.9). A visit may instead be marked missed, moving `SCHEDULED` to `MISSED`, either directly by the nurse or by a hold cascade. `COMPLETED`, `MISSED`, and `CANCELLED` are all terminal visit states.

Lab results themselves are recorded by a `VisitingNurse` or `MedicalDirector` against an order, carrying the `order_id`, the `lab_type` (one of `TROUGH`, `PEAK`, `CMP`, or `CBC`), the `value_num` (the numeric result), the `collected_at` collection timestamp, and an optional `is_critical` flag that defaults to false and marks a value outside the safe range. A `LabResult` carries no `version` of its own beyond the common versioning every entity shares.

### 3.8. Supply Kits

Ancillary supply kits accompany an order. A `WarehouseClerk` or `Pharmacist` creates a kit with the `order_id`, a `kit_type` of `START_OF_CARE`, `WEEKLY_RESUPPLY`, or `FLUSH_ONLY`, and a `line_count` (the number of ancillary lines, at least one). A new kit is in `PICKING`. A `WarehouseClerk` ships it, moving `PICKING` to `SHIPPED`, but only while the kit is still `PICKING` and the order it supports is in `RELEASED` or `ACTIVE`. A kit may instead be moved from `PICKING` to `CANCELLED`, but only as a side effect of a cascade — either an order discontinuation or an authorization denial. `SHIPPED` and `CANCELLED` are terminal kit states.

### 3.9. Adverse Events, Severity Scoring, and the Automatic Hold

A `VisitingNurse` or `MedicalDirector` reports an adverse reaction against an order, supplying the `order_id`, an optional `visit_id` (the visit during which the reaction occurred, null when the event is not visit-bound), the `severity_grade` (a CTCAE-style grade that is one of 1, 2, 3, or 4), the `reaction_count` (the number of distinct reactions, at least zero), and the `vital_instability` flag (0 for stable, 1 for unstable vitals). On report the server records who reported it — storing the reporter's role as `reported_by_role` and the reporter's identifier as `reported_by_user_id` — and the event enters `REPORTED`.

The server then computes the event's `severity_score`. The score is the grade weighted by two, plus the reaction count weighted by one, plus the vital-instability flag weighted by three — that is, two times `severity_grade`, plus one times `reaction_count`, plus three times `vital_instability` — yielding an integer. When this `severity_score` reaches or exceeds the auto-hold threshold of 7, the reporting cascade automatically holds the order: an order in `RELEASED` or `ACTIVE` is driven to `ON_HOLD` with its `hold_reason` set to `ADVERSE_EVENT`. When the held order had been `ACTIVE`, the hold cascade also sweeps every `SCHEDULED` visit for that order whose `start_at` is in the future into `MISSED`. The same `ON_HOLD` state and `LAB_OVERDUE` hold reason are reached when a fourth-or-later visit is blocked by an overdue trough lab as described above. Each entity touched by the cascade has its `version` incremented and `updated_at` refreshed.

### 3.10. Adjudicating a Hold — Segregation of Duties

An order resting in `ON_HOLD` is cleared by a `MedicalDirector` who adjudicates the adverse event that produced the hold, supplying a `disposition`. Adjudication is permitted only while the event is `REPORTED` and the order is `ON_HOLD`. Crucially, the adjudicating operator's `X-User-ID` must differ from the event's `reported_by_user_id`: the clinician who reported a reaction may not be the one who clears the hold it caused. An attempt to adjudicate an event one personally reported is rejected with `ERR_SEGREGATION_OF_DUTIES`. This is why the `VisitingNurse` identity is entity-backed — a nurse who reports while wearing the nurse role and later attempts to adjudicate while wearing a director role is still recognized as the same identity and barred.

A `disposition` of `RESUME` moves the order from `ON_HOLD` back to `ACTIVE`, clears its `hold_reason` to null, and marks the event `ADJUDICATED`. A `disposition` of `DISCONTINUE` moves the order from `ON_HOLD` to `DISCONTINUED`, marks the event `ADJUDICATED`, and runs the full discontinuation cascade described next. Either way the event moves `REPORTED` to `ADJUDICATED` (its terminal state) and the relevant versions increment.

### 3.11. Discontinuation and Its Cascade

An order may be discontinued either through the `DISCONTINUE` adjudication path above or, for an order in `ACTIVE`, directly by a `MedicalDirector`. The direct discontinuation requires the order to be `ACTIVE`. In both cases discontinuation runs one atomic cascade. Every nursing visit still in `SCHEDULED` for that order is moved to `CANCELLED`. Every compound for that order in `ORDERED` or `COMPOUNDED` is moved to `WASTED`; and for each compound that was `COMPOUNDED` — meaning its vials had been reserved — the `vials_reserved` are returned to the drug's `on_hand_vials`, restoring the inventory conservation equality (a compound wasted from `ORDERED` had reserved nothing, so nothing returns). Every entity the cascade touches has its `version` incremented, including the order itself, which lands in `DISCONTINUED` (a terminal order state).

### 3.12. The Billing Ledger: Estimate, Final, and the Copay Waterfall

Billing is the ledger-reconciliation heart of the system, and the same arithmetic runs twice. A `Biller` creates a claim with the `order_id` and the `expected_order_version` that pins the order version as described in Section 2.7. The order must be in `ACTIVE`, `COMPLETED`, or `DISCONTINUED` for a claim to be created against it. The new claim begins in `DRAFT` with `variant` `ESTIMATE`, and on creation the server computes the estimate figures and reads — but does not change — the payer plan's accumulators. Posting the claim, moving `DRAFT` to `POSTED`, recomputes every figure under the `FINAL` variant, sets `variant` to `FINAL`, and is the only event that debits the accumulators. Posting requires the claim to be `DRAFT`. A `POSTED` claim may be voided, moving `POSTED` to `VOID` (terminal), which credits the accumulators back by exactly the amounts the post debited. The server copies `payer_plan_id` onto the claim from the order's patient at creation.

The single difference between the two variants is the **billed-day basis**, captured on the claim as `billed_days`. Under `ESTIMATE` the billed-day count is the order's `scheduled_days`. Under `FINAL` the billed-day count is the order's `administered_days`, which is the count of that order's visits in `COMPLETED`. Every monetary figure flows from that day count and the order's drug and plan.

The **per-diem line**, written to `per_diem_cents`, is the plan's per-diem rate for the order drug's therapy category, multiplied by the billed-day count. The rate is selected from the plan's `per_diem_rate_cents` map using the drug's `therapy_category`. Because both the rate and the day count are integers, this line is exact and is not rounded.

The **drug line**, written to `drug_allowed_cents`, applies a whole-vial ceiling before the plan discount, in this pinned order. First, the billed vial count is the daily dose multiplied by the billed-day count, divided by the drug's `vial_size_mg`, rounded **up** to the next whole vial — the same whole-vial ceiling used for compounding, but here driven by the billed-day count rather than the planned days. Second, the gross amount is that whole vial count multiplied by the drug's `awp_per_vial_cents`. Third, the plan discount is applied: the allowed drug line is the gross amount multiplied by one minus the plan's `awp_discount_pct`, and this single discounted product is rounded half up to whole cents to become the drug line. The whole-vial ceiling is applied before the discount, and the discounted line is rounded exactly once, at the line level.

The claim's `allowed_total_cents` is the sum of `per_diem_cents` and `drug_allowed_cents`. From that allowed total the **copay waterfall**, written to `patient_responsibility_cents` and `plan_paid_cents`, allocates patient and plan portions in a pinned order. First, the deductible bucket absorbs first: the deductible applied is the smaller of the plan's `deductible_remaining_cents` and the allowed total. The remainder after the deductible is the allowed total minus the deductible applied. Second, coinsurance is taken on that post-deductible remainder: the coinsurance amount is the remainder multiplied by the plan's `coinsurance_pct`, rounded half up to whole cents — and this coinsurance bucket is the only place rounding occurs in the waterfall. The patient's pre-cap responsibility is the deductible applied plus the coinsurance amount. Third and last, the out-of-pocket cap is applied: the patient's responsibility is the smaller of that pre-cap amount and the plan's `oop_max_remaining_cents`. Finally, `plan_paid_cents` is the allowed total minus the patient responsibility. The deductible bucket is always resolved before the coinsurance bucket, and the out-of-pocket cap is always applied last.

When the claim is posted under `FINAL`, the post additionally debits the plan: the `deductible_remaining_cents` is reduced by the deductible portion actually applied, and the `oop_max_remaining_cents` is reduced by the final `patient_responsibility_cents`. Because the post moves the accumulators, the order in which claims are posted matters — a second posted claim sees the lowered deductible and out-of-pocket balances left by the first. Voiding reverses both debits by the same amounts, returning the plan to where it stood before the post. An estimate, by contrast, leaves the accumulators untouched, so a drafted claim's figures are provisional.

A claim that survives all of the above still cannot be created if the order version has moved: the `expected_order_version` must equal the order's current `version`, or the create is rejected with `ERR_STALE_ORDER_VERSION`. And an order itself cannot be completed prematurely — a `Pharmacist` may move an order from `ACTIVE` to `COMPLETED` only when its `administered_days` are at least its `scheduled_days`; attempting to complete an order whose administered days still fall short of its scheduled days is rejected with `ERR_THERAPY_INCOMPLETE`.

## 4. Endpoint Definitions

Newly created resources are returned with HTTP 201; state transitions and other modifications return HTTP 200. The administrative clock endpoint returns HTTP 200. The table below lists the HTTP surface only; the request bodies, response side effects, and business rules for each operation are specified in the Section 3 narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | IntakeCoordinator, Pharmacist, AuthSpecialist, MedicalDirector, Biller, WarehouseClerk, VisitingNurse |
| POST | `/drug-catalog` | Register a drug and its lot | Pharmacist |
| GET | `/drug-catalog/{id}` | Fetch a drug | Pharmacist, AuthSpecialist, MedicalDirector, Biller, IntakeCoordinator |
| GET | `/drug-catalog` | List drugs | Pharmacist, AuthSpecialist, MedicalDirector, Biller, IntakeCoordinator |
| POST | `/payer-plans` | Register a payer plan | Biller |
| GET | `/payer-plans/{id}` | Fetch a payer plan | Biller, IntakeCoordinator, AuthSpecialist |
| POST | `/nurses` | Register a nurse | IntakeCoordinator |
| GET | `/nurses/{id}` | Fetch a nurse | IntakeCoordinator, VisitingNurse, MedicalDirector |
| POST | `/pumps` | Register a pump asset | WarehouseClerk, Pharmacist |
| GET | `/pumps/{id}` | Fetch a pump | WarehouseClerk, Pharmacist |
| POST | `/patients` | Register a patient | IntakeCoordinator |
| GET | `/patients/{id}` | Fetch a patient | IntakeCoordinator, MedicalDirector, Biller |
| GET | `/patients` | List patients | IntakeCoordinator, MedicalDirector, Biller |
| POST | `/referrals` | Create a referral | IntakeCoordinator |
| GET | `/referrals/{id}` | Fetch a referral | IntakeCoordinator, Pharmacist, MedicalDirector |
| GET | `/referrals` | List referrals | IntakeCoordinator, Pharmacist, MedicalDirector |
| POST | `/referrals/{id}/accept` | Accept a referral | IntakeCoordinator |
| POST | `/referrals/{id}/reject` | Reject a referral | IntakeCoordinator |
| POST | `/infusion-orders` | Create an infusion order | Pharmacist |
| GET | `/infusion-orders/{id}` | Fetch an infusion order | Pharmacist, MedicalDirector, Biller, AuthSpecialist, VisitingNurse |
| GET | `/infusion-orders` | List infusion orders | Pharmacist, MedicalDirector, Biller, AuthSpecialist |
| POST | `/infusion-orders/{id}/submit` | Submit a draft order | Pharmacist |
| POST | `/infusion-orders/{id}/discontinue` | Discontinue an active order | MedicalDirector |
| POST | `/infusion-orders/{id}/complete` | Complete an active order | Pharmacist |
| POST | `/prior-authorizations` | Submit a prior authorization | AuthSpecialist |
| GET | `/prior-authorizations/{id}` | Fetch a prior authorization | AuthSpecialist, Pharmacist, MedicalDirector |
| GET | `/prior-authorizations` | List prior authorizations | AuthSpecialist, Pharmacist, MedicalDirector |
| POST | `/prior-authorizations/{id}/approve` | Approve a prior authorization | AuthSpecialist |
| POST | `/prior-authorizations/{id}/deny` | Deny a prior authorization | AuthSpecialist |
| POST | `/compounds` | Create a compound batch | Pharmacist |
| GET | `/compounds/{id}` | Fetch a compound | Pharmacist, MedicalDirector, VisitingNurse |
| GET | `/compounds` | List compounds | Pharmacist, MedicalDirector, VisitingNurse |
| POST | `/compounds/{id}/compound` | Prepare the batch and reserve vials | Pharmacist |
| POST | `/compounds/{id}/deliver` | Mark a compound delivered | Pharmacist |
| POST | `/supply-kits` | Create an ancillary supply kit | WarehouseClerk, Pharmacist |
| GET | `/supply-kits/{id}` | Fetch a supply kit | WarehouseClerk, Pharmacist, MedicalDirector |
| GET | `/supply-kits` | List supply kits | WarehouseClerk, Pharmacist, MedicalDirector |
| POST | `/supply-kits/{id}/ship` | Ship a kit | WarehouseClerk |
| POST | `/nursing-visits` | Schedule a nursing visit | IntakeCoordinator, VisitingNurse |
| GET | `/nursing-visits/{id}` | Fetch a nursing visit | VisitingNurse, MedicalDirector, Pharmacist, IntakeCoordinator |
| GET | `/nursing-visits` | List nursing visits | VisitingNurse, MedicalDirector, Pharmacist, IntakeCoordinator |
| POST | `/nursing-visits/{id}/complete` | Complete a visit | VisitingNurse |
| POST | `/nursing-visits/{id}/miss` | Mark a visit missed | VisitingNurse |
| POST | `/lab-results` | Record a monitoring lab result | VisitingNurse, MedicalDirector |
| GET | `/lab-results/{id}` | Fetch a lab result | VisitingNurse, MedicalDirector, Pharmacist |
| GET | `/lab-results` | List lab results | VisitingNurse, MedicalDirector, Pharmacist |
| POST | `/adverse-events` | Report an adverse reaction | VisitingNurse, MedicalDirector |
| GET | `/adverse-events/{id}` | Fetch an adverse event | VisitingNurse, MedicalDirector, Pharmacist |
| GET | `/adverse-events` | List adverse events | VisitingNurse, MedicalDirector, Pharmacist |
| POST | `/adverse-events/{id}/adjudicate` | Adjudicate a held order | MedicalDirector |
| POST | `/claims` | Create a draft claim | Biller |
| GET | `/claims/{id}` | Fetch a claim | Biller, MedicalDirector |
| GET | `/claims` | List claims | Biller, MedicalDirector |
| POST | `/claims/{id}/post` | Post a draft claim | Biller |
| POST | `/claims/{id}/void` | Void a posted claim | Biller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_LAB_OVERDUE | 409 |
| ERR_NURSE_NOT_LICENSED | 422 |
| ERR_AUTH_REQUIRED | 409 |
| ERR_PUMP_DOUBLE_BOOKED | 409 |
| ERR_NURSE_DOUBLE_BOOKED | 409 |
| ERR_INSUFFICIENT_INVENTORY | 409 |
| ERR_AUTH_UNITS_EXCEEDED | 422 |
| ERR_STALE_ORDER_VERSION | 412 |
| ERR_THERAPY_INCOMPLETE | 409 |
