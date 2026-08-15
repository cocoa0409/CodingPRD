# Cpap Resupply Adherence API — Product Requirements Document

## 1. Introduction

A durable medical equipment (DME) supplier specializing in sleep therapy lives and dies by two clocks: the payer's resupply calendar, which dictates when a mask, cushion, filter, or length of tubing may be billed again, and the patient's adherence record, which dictates whether the payer will continue to cover therapy at all. This document specifies the API for a CPAP resupply and sleep-therapy adherence platform. The system tracks patients from intake through machine setup, recurring component resupply, adherence data review, mask-fit exchanges, insurance rental-to-purchase conversion, and — when therapy ends — discontinuation with equipment retrieval.

The platform serves a four-role operating model with strict segregation between clinical and fiscal authority: the person who clears an order clinically may never be the person who authorizes it for billing. Payer policy drives nearly every rule in the system — compliance thresholds, per-component cadence windows, mask-exchange limits, and the number of rental months after which a device converts to patient ownership are all configured per payer plan rather than hard-coded. Because adherence reviews, resupply shipments, and rental billing all mutate shared patient state, the API uses optimistic concurrency on the patient record to keep concurrent actors from overwriting changes they have not observed. All endpoints are mounted under the `/sleep-therapy` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the role under which the user is acting. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Four roles exist, spelled exactly as follows:

- `OpsAdmin` — the platform operator. Creates payer policies, drives the logical clock, and runs the daily operations sweep. May also read any resource.
- `IntakeCoordinator` — front-desk intake. Registers patients, enrolls devices, creates resupply orders and mask-exchange requests, and drives shipment, delivery, return, and retrieval logistics. May read any resource.
- `RespiratoryTherapist` — the clinical role. Performs machine setup and education, ingests and reviews adherence reports, clinically clears resupply orders, approves or denies mask exchanges, and initiates therapy discontinuation. May read any resource.
- `BillingSpecialist` — the fiscal role. Authorizes or denies resupply orders awaiting payer authorization, invoices delivered orders, and bills rental months. May read any resource.

All four roles use **opaque** operator identifiers. When `X-User-Role` is `OpsAdmin`, `IntakeCoordinator`, `RespiratoryTherapist`, or `BillingSpecialist`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `clinical_cleared_by_user_id` or `authorized_by_user_id` on a resupply order, or as `reviewed_by_user_id` on an adherence report — but it never compares the header value to any entity's `id`. No role is entity-backed.

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

List endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. Results are always sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count` (the total number of matching records), and `has_more` (whether additional records exist beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries four server-managed properties in addition to its business fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records when the resource was created, and `updated_at` records when it was last mutated; both are ISO 8601 UTC timestamps with three fractional digits. The `version` is an integer that starts at 1 and increments by one on every mutation of the resource. All nine entities — patients, payer policies, device enrollments, component supply plans, resupply orders, adherence reports, mask exchanges, rental contracts, and retrieval cases — follow this convention without exception.

Whenever any side effect in this document changes an entity — a status transition, a recomputed date, a recorded user id — that entity's `version` increments and its `updated_at` refreshes as part of the same atomic request. Several workflows described in §3 deliberately call out patient version increments because those increments are what concurrent writers observe through the optimistic-concurrency mechanism of §2.6.

### 2.5. The Logical Clock and the Daily Operations Sweep

The server maintains a **logical clock** that governs every date comparison in this document — cadence gates, exchange windows, rental anniversaries, retrieval deadlines, and reminder look-aheads all read this clock, never the wall clock. At startup, before any adjustment, the logical clock reads 2026-08-01T00:00:00Z; once set, it never falls back to wall-clock time. An `OpsAdmin` may advance the clock through a test-driving capability that accepts a target instant `to_iso8601` and responds with the new `current_utc`.

A second `OpsAdmin` capability runs the **daily operations sweep**, which performs the system-side scheduled work described throughout §3: reminder outreach for supply plans approaching eligibility, rental-contract activation when the first monthly anniversary arrives, and patient discontinuation finalization when a linked retrieval case closes. The sweep responds with a summary object containing `reminders_sent`, `rental_activations`, and `patient_discontinuations` counts.

### 2.6. Optimistic Concurrency on the Patient Record

Two write operations on resupply orders require the caller to prove it has observed the current state of the patient: order authorization and order shipment. Both requests must carry `expected_patient_version`, a non-optional integer holding the client's last-observed `version` of the patient the order belongs to. If that value does not equal the patient's current `version` at the moment the request is evaluated — because an adherence finalization, a mask-exchange completion, a discontinuation, or another order event has advanced the patient record since the client last read it — the request is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412). This is a deterministic stale-version comparison against stored state; it does not depend on requests overlapping in time. Endpoints other than order authorization and order shipment do not accept a version field.

### 2.7. Request Evaluation Order

When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic. First come the two authentication checks — user-context headers, then role authorization — followed by existence: path parameters are resolved left to right (a failure yields `ERR_NOT_FOUND`), then any foreign-key identifiers referenced in the request body, such as `patient_id`, `payer_policy_id`, `component_supply_plan_id`, `device_enrollment_id`, or `original_mask_plan_id` (a failure yields `ERR_FK_NOT_FOUND`). Only after existence do state and business rules run, in the endpoint-specific orders given in §3 — for example, on order creation the patient-state check precedes the plan-state check, which precedes the quantity check, which precedes the cadence gate, which precedes the prior-authorization requirement. The malformed-body check `ERR_INVALID_REQUEST` (missing required fields, invalid types, or invalid enum values) has the lowest priority of all and surfaces only when no earlier check has failed.

### 2.8. Money, Rounding, and Date Arithmetic

All money is handled as integer cents; no fractional cents exist anywhere in the system. Two rounding rules govern the numeric outputs: adherence percentages are rounded half-up to one decimal place, and the patient coinsurance share on an invoiced order is rounded half-up to a whole cent. Date arithmetic is always in calendar days (or calendar months for rental anniversaries), and every threshold comparison in the system is **inclusive** unless explicitly stated otherwise: an order placed exactly on its plan's eligibility date is eligible, a patient whose final adherence exactly equals the payer threshold is compliant, and an exchange approved on the last day of its window is within the window. The one strict comparison in the system is the mask-exchange count check, which uses a strict less-than. These boundary semantics matter and are restated beside each rule in §3.

### 2.9. Segregation of Clinical and Fiscal Duties

No single operator may both clinically clear and fiscally authorize the same resupply order. The system enforces this by recording the clearing clinician's opaque user id at clearance time and comparing it against the authorizer's identity at authorization time; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. The two steps are also performed by different roles — clinical clearance by a `RespiratoryTherapist`, authorization by a `BillingSpecialist` — so the rule fires when an organization maps one operator into both roles.

### 2.10. Parallel State Dimensions

Two entities carry **two independent state dimensions** rather than a single status. A resupply order has an `auth_status` (the authorization dimension) and a `fulfillment_status` (the logistics dimension); it is terminal when `auth_status` is `DENIED` or `CANCELLED`, or when `fulfillment_status` is `INVOICED` or `RETURNED`. A rental contract has a `billing_status` and an `equipment_status`, which evolve independently — billing may be paused for non-compliance while the equipment stays with the patient, and equipment may move through retrieval while billing has already converted or terminated. Business rules in §3 name the exact dimension and value they act on.

## 3. Business Logic & Workflows

### 3.1. Payer Policies: The Compliance and Cadence Contract

Everything downstream — adherence math, resupply cadence, exchange windows, rental conversion — reads its parameters from a **payer policy**. An `OpsAdmin` creates policies by supplying the payer's display name `payer_name`, a `plan_code` that must be unique across all policies, and the policy's numeric contract terms.

The compliance terms define what "using the machine enough" means. `compliance_threshold_pct` is an integer between 1 and 100 giving the minimum adherence percentage required for continued coverage — the CMS standard is 70. `compliance_min_hours_per_night` gives the minimum nightly usage, in hours, that counts a night as compliant (CMS standard: 4.0). `compliance_window_days` is the length of the consecutive-day look-back window over which adherence is computed (CMS standard: 30 days). `compliance_min_nights` records the minimum number of compliant nights within the window, derived as the threshold percentage divided by 100 and multiplied by the window length, rounded up to a whole number — for the CMS-standard terms, 70 percent of 30 nights rounded up is 21 nights — and pinned on the policy at intake for audit stability.

The resupply terms give the minimum number of days between billable resupplies for each component: `mask_cadence_days` (typically 90), `cushion_cadence_days` (typically 30), `filter_cadence_days` (typically 14), and `tubing_cadence_days` (typically 90). The exchange terms give `mask_exchange_window_days`, the length of the no-cost fit-exchange window (typically 30 days), and `max_exchanges_per_window`, the maximum number of no-cost exchanges permitted within one window. The rental term `rental_months_to_own` gives the number of billed rental months after which the patient owns the device (typically 10 or 13). Finally, the boolean `requires_prior_auth` marks plans under which every resupply order must carry a prior-authorization reference before it can be created.

### 3.2. Patient Intake and Device Enrollment

An `IntakeCoordinator` registers a new patient with the patient's `full_name`, `date_of_birth` as an ISO calendar date, the `payer_policy_id` of the governing payer policy, and the `prescribing_clinician_npi` — the ten-digit NPI of the prescribing clinician. A new patient starts in `INTAKE` status. The patient record also carries several fields the client never writes directly: `therapy_started_on` stays null until the first machine setup completes; `adherence_percentage` and `is_compliance_current` reflect the most recent finalized adherence report and stay null/false until one exists; `outstanding_balance_cents` aggregates invoiced patient responsibility; and `current_device_enrollment_id` and `current_rental_contract_id` point at the patient's active device enrollment and rental contract, null until such records exist. The patient list endpoint supports filtering by `patient_status`, `payer_policy_id`, `current_device_enrollment_id`, and `current_rental_contract_id`.

With the patient registered, the same coordinator enrolls a device by submitting the `patient_id`, the manufacturer `device_serial` (unique across all enrollments), the `device_model` code, and the `acquisition_type`. The acquisition type is either `RENTAL` — which will cause a rental contract to be created when setup completes — or `PURCHASE`, which creates no contract because the patient owns the device outright. A new enrollment starts in `PENDING_SETUP` status.

### 3.3. Machine Setup, Therapy Activation, and Supply Plan Seeding

Setup is a clinical act performed by a `RespiratoryTherapist` in two steps. Beginning setup moves an enrollment from `PENDING_SETUP` to `SETUP_IN_PROGRESS`; it requires the enrollment to actually be in `PENDING_SETUP` (otherwise `ERR_ENROLLMENT_NOT_PENDING_SETUP`) and the patient to still be in `INTAKE` (otherwise `ERR_PATIENT_NOT_IN_INTAKE`).

Completing setup is the pivotal event of the patient lifecycle, and it cascades widely. It requires the enrollment to be in `SETUP_IN_PROGRESS` (`ERR_ENROLLMENT_NOT_READY_FOR_SETUP` otherwise), the patient still in `INTAKE` (`ERR_PATIENT_NOT_IN_INTAKE`), and the patient's payer policy to resolve (`ERR_PAYER_POLICY_NOT_FOUND` if the patient's policy reference is dangling). On completion, all of the following happen atomically in the same request:

- The enrollment's `enrollment_status` becomes `ACTIVE` and its `setup_completed_on` records the current date.
- The patient moves from `INTAKE` to `ACTIVE_THERAPY`, `therapy_started_on` is set to the current date, and `current_device_enrollment_id` points at this enrollment.
- Four **component supply plans** are created for the patient — one each for `MASK`, `CUSHION`, `FILTER`, and `TUBING` — all in `ACTIVE` plan status, with `last_dispensed_on` and `next_eligible_on` null because nothing has been dispensed yet.
- If the enrollment's `acquisition_type` is `RENTAL`, a **rental contract** is created: `billing_status` starts `SCHEDULED`, `equipment_status` starts `WITH_PATIENT`, `rental_start_on` equals the enrollment's setup completion date, `rental_months_billed` starts at zero, the contract's `payer_policy_id` snapshots the patient's policy at creation, and the patient's `current_rental_contract_id` points at the new contract.

Each supply plan also carries `component_type`, the `quantity_per_cycle` dispensed per resupply cycle (at least one unit), and a `reminder_sent_on` date that stays null until outreach occurs. The supply-plan list endpoint can be filtered by `patient_id`, `component_type`, and `plan_status`.

### 3.4. Adherence Reporting and Compliance Enforcement

A `RespiratoryTherapist` ingests an adherence data download by supplying the `patient_id`, the `device_enrollment_id` the data came from, the `window_end_on` date (the last day of the reporting window, inclusive), the `nights_reported` count of nightly usage records in the download, and the `compliant_nights` count — the number of those nights on which usage met or exceeded the payer's `compliance_min_hours_per_night`. The report starts in `RECEIVED` status. At ingestion the server computes `window_start_on` as `window_end_on` minus the payer's `compliance_window_days` plus one day, so that start and end together span exactly the window; a submission whose window arithmetic is inconsistent with the payer's window length is rejected with `ERR_INVALID_WINDOW`. Reports can be listed with filters on `patient_id`, `device_enrollment_id`, and `report_status`.

Adherence percentage is computed in **two variants**, both rounded half-up to one decimal place. The **provisional** variant, `adherence_pct_provisional`, is available immediately at ingestion and while the report is under review: it is the compliant nights divided by the nights actually reported, times one hundred — or exactly 0.0 when no nights were reported at all. Clinicians use it as a preview, because missing nights are simply ignored. The **final** variant, `adherence_pct_final`, is computed only at finalization: it is the compliant nights divided by the payer's full `compliance_window_days`, times one hundred — so nights with no data count as non-compliant. A patient who reported 25 nights, 21 of them compliant, against a 30-day window shows a provisional 84.0 but a final 70.0.

Review follows a strict chain. Beginning review moves a report from `RECEIVED` to `UNDER_REVIEW` (any other status yields `ERR_REPORT_NOT_RECEIVED`). From `UNDER_REVIEW`, the therapist either finalizes or rejects; both require the report to be in `UNDER_REVIEW` (`ERR_REPORT_NOT_UNDER_REVIEW` otherwise). Finalization re-verifies the window arithmetic (`ERR_INVALID_WINDOW` if inconsistent), sets `report_status` to `FINALIZED`, records the therapist in `reviewed_by_user_id`, computes `adherence_pct_final`, and then settles the patient record: `adherence_percentage` becomes the final percentage, `is_compliance_current` becomes true exactly when the final percentage is **at least** the payer's `compliance_threshold_pct` — equality counts as compliant — and the enrollment's `last_adherence_download_on` is set to the current date. Rejection instead moves the report to `REJECTED` and leaves every patient field untouched.

Finalization also drives the compliance hold machinery, automatically and in the same request. When a finalized report's `adherence_pct_final` falls below the payer threshold, a patient in `ACTIVE_THERAPY` moves to `NON_COMPLIANT_HOLD`: every supply plan in `ACTIVE` for that patient is suspended into `SUSPENDED_NON_COMPLIANCE`, and an active rental contract in `BILLING` pauses into `PAUSED_NON_COMPLIANCE` — months do not accrue while paused. When a later finalized report meets or exceeds the threshold, the patient returns from `NON_COMPLIANT_HOLD` to `ACTIVE_THERAPY`, the suspended plans resume to `ACTIVE`, and the paused contract resumes to `BILLING`.

### 3.5. The Resupply Order Pipeline: From Request to Invoice

An `IntakeCoordinator` creates a resupply order by naming the `patient_id`, the `component_supply_plan_id` being fulfilled, the `requested_quantity`, and the client's last-observed patient version in `expected_patient_version`. Creation runs its checks in a fixed order: the patient must be in `ACTIVE_THERAPY` (`ERR_PATIENT_NOT_IN_ACTIVE_THERAPY`); then the plan must be in `ACTIVE` status (`ERR_PLAN_NOT_ACTIVE`); then the `requested_quantity` must equal the plan's `quantity_per_cycle` — orders are always full-cycle, never partial (`ERR_QUANTITY_MISMATCH`); then the cadence gate; then the prior-authorization requirement.

The **cadence gate** is per component. If the plan's `last_dispensed_on` is null — the patient has never received this component — the first fill is always eligible once setup has completed and the patient is in active therapy. Otherwise the plan's `next_eligible_on` is the last dispense date plus the payer's cadence for that component type — `mask_cadence_days` for `MASK`, `cushion_cadence_days` for `CUSHION`, `filter_cadence_days` for `FILTER`, `tubing_cadence_days` for `TUBING` — and the order is eligible when the current date is on or after `next_eligible_on`; one day early is `ERR_CADENCE_NOT_MET`. If the payer's `requires_prior_auth` is true, the request must carry a prior-authorization reference (`ERR_PRIOR_AUTH_REQUIRED` when absent). A newly created order lands with `auth_status` `PENDING_CLINICAL_CLEARANCE` and `fulfillment_status` `NOT_READY`. Orders can be listed filtered by `patient_id`, `component_supply_plan_id`, `auth_status`, and `fulfillment_status`.

From there the authorization dimension advances. A `RespiratoryTherapist` performs clinical clearance, which requires the order to be in `PENDING_CLINICAL_CLEARANCE` (`ERR_ORDER_NOT_PENDING_CLINICAL`) and the patient's compliance to be current — with one deliberate grace: a patient who has **no finalized adherence report yet** may be cleared for a first fill. A patient whose `is_compliance_current` is false and who does have a finalized report fails with `ERR_COMPLIANCE_NOT_CURRENT`. Clearance moves the order to `PENDING_PAYER_AUTH` and records the therapist's id in `clinical_cleared_by_user_id`.

Authorization is a fiscal step performed by a `BillingSpecialist`, and its checks run in this order: the order must be in `PENDING_PAYER_AUTH` with fulfillment still `NOT_READY` (`ERR_ORDER_NOT_PENDING_AUTH`); then segregation of duties — the authorizer's `X-User-ID` must differ from `clinical_cleared_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); then the optimistic-concurrency check of §2.6 — the request's `expected_patient_version` must equal the patient's current `version`, with a mismatch rejected as `ERR_STALE_PATIENT_VERSION` (HTTP 412). A successful authorization moves `auth_status` to `AUTHORIZED` and `fulfillment_status` to `READY_TO_SHIP`, snapshots the payer's fee schedule into the order's `unit_allowable_cents`, records the authorizer in `authorized_by_user_id`, and **increments the patient's `version` by one** — which is exactly what invalidates any other client's stale snapshot. Alternatively, the specialist may deny the order while it is in `PENDING_PAYER_AUTH`; denial moves `auth_status` to `DENIED`, stores the supplied `denial_reason_code`, and likewise increments the patient's `version`.

The fulfillment dimension then runs under the `IntakeCoordinator`, with invoicing by the `BillingSpecialist`. Shipping requires the order to be `AUTHORIZED` (`ERR_ORDER_NOT_AUTHORIZED` when the authorization dimension is in any other state) and in `READY_TO_SHIP` (`ERR_ORDER_NOT_READY_TO_SHIP`), and it carries the same `expected_patient_version` OCC check — evaluated before the readiness checks — with `ERR_STALE_PATIENT_VERSION` on mismatch. Shipping sets `fulfillment_status` to `SHIPPED`, stamps `shipped_on` with the current date, writes that date into the plan's `last_dispensed_on`, recomputes `next_eligible_on` as that date plus the component's cadence, and increments the patient's `version`. Marking delivery requires `SHIPPED` (`ERR_ORDER_NOT_SHIPPED`) and moves the order to `DELIVERED`. From `DELIVERED` there are two exits: marking the order returned moves it to `RETURNED` with no invoice and no balance impact; invoicing moves it to `INVOICED` (any other status yields `ERR_ORDER_NOT_DELIVERED`).

Invoicing computes the patient's coinsurance share. The line total is the order's `unit_allowable_cents` multiplied by its `requested_quantity`; the patient's share, stored in `patient_responsibility_cents`, is twenty percent of that line total, rounded half-up to a whole cent. Rounding applies to the line total after multiplication — never per unit. The computed share is added to the patient's `outstanding_balance_cents`, which in general aggregates the `patient_responsibility_cents` of all the patient's orders in `INVOICED` status, less any payments applied. A pre-authorization order may also be cancelled by the coordinator: cancellation is allowed only while `auth_status` is `PENDING_CLINICAL_CLEARANCE` or `PENDING_PAYER_AUTH` **and** fulfillment is still `NOT_READY` (`ERR_ORDER_NOT_CANCELLABLE` otherwise), and it moves `auth_status` to `CANCELLED`.

Reminder outreach rides the same cadence arithmetic. During each daily sweep, the system walks every supply plan in `ACTIVE` status and skips any plan whose `last_dispensed_on` is still null — there is nothing to remind about before the first fill. For the rest, it computes the plan's next eligibility date as `last_dispensed_on` plus the payer's cadence for that component, then looks ahead one week: when the current date has reached seven days before that eligibility date, and the plan's `reminder_sent_on` is either null or earlier than that look-ahead date, the sweep emits a reminder event and stamps `reminder_sent_on` with the current date. A plan reminded for one cycle will be reminded again for the next only after a new dispense has pushed the cadence forward.

### 3.6. Mask Fit Exchanges and the Exchange Window

New CPAP patients frequently need a different mask within the first weeks of therapy, and payers allow a limited number of no-cost exchanges inside a defined window. An `IntakeCoordinator` requests an exchange with the `patient_id`, the `device_enrollment_id`, the `original_mask_plan_id` of the `MASK` supply plan being exchanged, and a `reason_code` of `FIT_LEAK`, `SKIN_IRRITATION`, `WRONG_SIZE`, or `PRESSURE_INTOLERANCE`. The request lands in `REQUESTED` status, and the server computes its `window_anchor_on`, the date anchoring the exchange window.

The anchor selector looks at the most recently created prior exchange for the same patient (by `created_at`, most recent first). If no prior exchange exists, the anchor is the enrollment's `setup_completed_on`. If a prior exchange exists and its window is still open — the current date is on or before the prior anchor plus the payer's `mask_exchange_window_days` — the new exchange inherits the prior anchor, extending the same window rather than opening a fresh one. If the prior window has expired, the anchor becomes the prior exchange's `completed_on`, rolling a new window forward. Exchanges may be listed with filters on `patient_id`, `device_enrollment_id`, `original_mask_plan_id`, `superseded_by_exchange_id`, and `exchange_status`.

Approval belongs to the `RespiratoryTherapist` and enforces two checks, window first, then count. The window check requires the current date to be on or before `window_anchor_on` plus `mask_exchange_window_days` — inclusive, so with a 30-day window anchored on March 1 the last valid approval day is March 31; a later date fails with `ERR_EXCHANGE_WINDOW_EXPIRED`. The count check requires that the number of the patient's other exchanges already in `COMPLETED` status sharing this exchange's `window_anchor_on` be **strictly less than** the payer's `max_exchanges_per_window` — so with a limit of one, the first exchange in a window is permitted and the second is rejected with `ERR_EXCHANGE_LIMIT_REACHED`. An exchange not in `REQUESTED` cannot be approved at all (`ERR_EXCHANGE_NOT_REQUESTED`). Approval moves the exchange to `APPROVED`.

The coordinator then ships the replacement — requiring `APPROVED` (`ERR_EXCHANGE_NOT_APPROVED`) and moving the exchange to `SHIPPED` — and completes it upon delivery, which requires `SHIPPED` (`ERR_EXCHANGE_NOT_SHIPPED`). Completion is a cascade: `exchange_status` becomes `COMPLETED`, `completed_on` records the current date, the patient's `MASK` supply plan has its `last_dispensed_on` set to the current date and its `next_eligible_on` recomputed as that date plus the payer's `mask_cadence_days` — an exchange resets the mask resupply clock — and the most recent prior exchange for the patient that has not already been superseded is marked by writing this exchange's id into its `superseded_by_exchange_id`, forming a chain in which each exchange points at its replacement. The therapist may instead deny a `REQUESTED` exchange outright, moving it to `DENIED`, and the coordinator may cancel an exchange while it is `REQUESTED` or `APPROVED`, moving it to `CANCELLED`.

### 3.7. Rental Billing, Pause/Resume, and Conversion to Ownership

A rental contract's billing clock starts at `rental_start_on`, the setup completion date captured at contract creation. The contract projects `conversion_eligible_on` as `rental_start_on` plus the payer's `rental_months_to_own` calendar months — a straight-line projection that assumes one billed month per calendar month with no pauses. The contract also carries `monthly_rental_cents`, the payer-allowable monthly rental amount. Contracts may be listed with filters on `patient_id`, `device_enrollment_id`, `payer_policy_id`, `billing_status`, and `equipment_status`.

Billing activation is automatic: when the daily sweep observes the current date reaching one calendar month after `rental_start_on` while the contract is still `SCHEDULED`, the contract moves to `BILLING`. Thereafter, a `BillingSpecialist` bills each rental month explicitly. Billing one month enforces three checks in a fixed order: the monthly anniversary must have arrived — the current date must be on or after `rental_start_on` plus `rental_months_billed` months plus one further month, inclusive (`ERR_RENTAL_PERIOD_NOT_DUE`); the contract must be in `BILLING` status — not paused, converted, or terminated (`ERR_RENTAL_NOT_BILLING`); and the contract must not already be fully accrued, meaning `rental_months_billed` is still below the payer's `rental_months_to_own` (`ERR_RENTAL_ALREADY_CONVERTED`). Each successful bill increments `rental_months_billed` by one.

Accrual follows **actual usage**, not the straight-line projection: only months in which the contract was actively billing count. Months spent in `PAUSED_NON_COMPLIANCE` — entered automatically when the patient's adherence finalization triggers a compliance hold, and exited automatically back to `BILLING` when a later report restores compliance — do not increment `rental_months_billed`. A patient who spends two months paused therefore reaches conversion two calendar months after the projected `conversion_eligible_on`. When a bill causes `rental_months_billed` to reach `rental_months_to_own`, the contract converts in the same request: `billing_status` becomes `CONVERTED_TO_OWNERSHIP` and `equipment_status` becomes `OWNERSHIP_TRANSFERRED`. Both `CONVERTED_TO_OWNERSHIP` and `TERMINATED` are terminal for the billing dimension.

### 3.8. Discontinuation and Equipment Retrieval

A `RespiratoryTherapist` initiates discontinuation with a `reason_code` — one of `THERAPY_DISCONTINUED`, `PROLONGED_NON_COMPLIANCE`, `PAYER_STOPPED_COVERAGE`, or `PATIENT_REQUEST`. The patient must be in `ACTIVE_THERAPY` or `NON_COMPLIANT_HOLD` (`ERR_PATIENT_NOT_DISCONTINUABLE` from any other status). Initiation moves the patient to `DISCONTINUING`, suspends every supply plan into `SUSPENDED_DISCONTINUATION`, and — when an active rental contract exists — opens a **retrieval case**: the case is created in `OPEN` status carrying the contract's id in its `rental_contract_id` (null for owned devices), the `THERAPY_DISCONTINUED` reason, and a `due_on` deadline fourteen days after creation; the contract's `equipment_status` simultaneously moves from `WITH_PATIENT` to `RETRIEVAL_REQUESTED`, and the enrollment's `enrollment_status` moves from `ACTIVE` to `RETRIEVAL_PENDING`. Retrieval cases may be listed with filters on `patient_id`, `device_enrollment_id`, `rental_contract_id`, and `retrieval_status`.

The retrieval workflow is driven by the `IntakeCoordinator` through a strict chain, and state violations surface either the state-specific error or, where no specific code applies, the generic `ERR_RETRIEVAL_INVALID_STATE`. Scheduling a pickup requires `OPEN` (`ERR_RETRIEVAL_NOT_OPEN`) and moves the case to `SCHEDULED`. Marking the equipment picked up requires `SCHEDULED` (`ERR_RETRIEVAL_NOT_SCHEDULED`) and moves it to `IN_TRANSIT`. Marking it received requires `IN_TRANSIT` (`ERR_RETRIEVAL_NOT_IN_TRANSIT`), sets `retrieval_status` to `RECEIVED`, stamps `received_on` with the current date, moves the enrollment to `RETRIEVED`, and — when a rental contract is linked — moves the contract's `equipment_status` to `RETRIEVED`. Reconciliation requires `RECEIVED` (`ERR_RETRIEVAL_NOT_RECEIVED`) and moves the case to `RECONCILED`; synchronously in the same request, a patient in `DISCONTINUING` cascades to `DISCONTINUED`, every supply plan closes to `CLOSED`, and the rental contract's `billing_status` terminates to `TERMINATED` unless it has already converted.

When the equipment never comes back, the coordinator may close the case unrecoverable — but only from `OPEN`, `SCHEDULED`, or `IN_TRANSIT` (`ERR_RETRIEVAL_NOT_CLOSABLE` from any other state) and only after the deadline has passed, meaning the current date is strictly later than `due_on` (`ERR_RETRIEVAL_NOT_OVERDUE` on or before the due date). Closing unrecoverable moves the case to `CLOSED_UNRECOVERABLE` and cascades the same discontinuation finalization: the patient moves from `DISCONTINUING` to `DISCONTINUED`, supply plans close, the contract's billing terminates, and the enrollment becomes `DECOMMISSIONED` rather than `RETRIEVED` because the equipment was not recovered. On a recovered device, the enrollment cascade instead records `RETRIEVED`. Both terminal transitions of the case — `RECONCILED` and `CLOSED_UNRECOVERABLE` — are what the daily sweep and the synchronous cascade watch for when finalizing `DISCONTINUING` patients.

One final logistics step remains for recovered rental equipment: returning it to the payer. This requires the enrollment to be in `RETRIEVED` (`ERR_ENROLLMENT_NOT_RETRIEVED`) and the linked rental contract's `equipment_status` to be `RETRIEVED` as well (`ERR_RENTAL_NOT_IN_RETRIEVAL`); it moves the enrollment to `RETURNED_TO_PAYER`.

## 4. Endpoint Definitions

All endpoints live under the `/sleep-therapy` prefix. Endpoints that create a new resource respond with HTTP 201; all other successful operations, including state transitions and reads, respond with HTTP 200. Authentication, role authorization, existence checks, and the evaluation order of §2.7 apply uniformly.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /sleep-therapy/_clock/set_current_utc | Advance the logical clock to a supplied instant | OpsAdmin |
| POST | /sleep-therapy/_ops/run-daily-sweep | Run the daily sweep: reminders, rental activation, discontinuation finalization | OpsAdmin |
| POST | /sleep-therapy/payer-policies | Create a payer policy | OpsAdmin |
| GET | /sleep-therapy/payer-policies | List payer policies | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| GET | /sleep-therapy/payer-policies/{id} | Get a payer policy | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| POST | /sleep-therapy/patients | Register a new patient in INTAKE | IntakeCoordinator |
| GET | /sleep-therapy/patients | List patients with filters | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| GET | /sleep-therapy/patients/{id} | Get patient detail including computed adherence and balance | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| POST | /sleep-therapy/patients/{id}/initiate-discontinuation | Initiate therapy discontinuation; opens a retrieval case for rentals | RespiratoryTherapist |
| POST | /sleep-therapy/device-enrollments | Enroll a device for a patient | IntakeCoordinator |
| GET | /sleep-therapy/device-enrollments | List device enrollments with filters | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| GET | /sleep-therapy/device-enrollments/{id} | Get a device enrollment | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| POST | /sleep-therapy/device-enrollments/{id}/begin-setup | Begin machine setup (PENDING_SETUP to SETUP_IN_PROGRESS) | RespiratoryTherapist |
| POST | /sleep-therapy/device-enrollments/{id}/complete-setup | Complete setup; activates therapy, seeds supply plans, creates rental contract if RENTAL | RespiratoryTherapist |
| POST | /sleep-therapy/device-enrollments/{id}/return-to-payer | Return a retrieved rental device to the payer | IntakeCoordinator |
| GET | /sleep-therapy/component-supply-plans | List supply plans with filters | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| GET | /sleep-therapy/component-supply-plans/{id} | Get a supply plan | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| POST | /sleep-therapy/resupply-orders | Create a resupply order in PENDING_CLINICAL_CLEARANCE | IntakeCoordinator |
| GET | /sleep-therapy/resupply-orders | List resupply orders with filters | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| GET | /sleep-therapy/resupply-orders/{id} | Get a resupply order | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| POST | /sleep-therapy/resupply-orders/{id}/clinical-clear | Clinically clear an order | RespiratoryTherapist |
| POST | /sleep-therapy/resupply-orders/{id}/authorize | Authorize an order; OCC on the patient version | BillingSpecialist |
| POST | /sleep-therapy/resupply-orders/{id}/deny | Deny an order awaiting payer authorization | BillingSpecialist |
| POST | /sleep-therapy/resupply-orders/{id}/ship | Ship an authorized order; OCC on the patient version | IntakeCoordinator |
| POST | /sleep-therapy/resupply-orders/{id}/mark-delivered | Mark an order delivered | IntakeCoordinator |
| POST | /sleep-therapy/resupply-orders/{id}/invoice | Invoice a delivered order; computes patient responsibility | BillingSpecialist |
| POST | /sleep-therapy/resupply-orders/{id}/mark-returned | Mark a delivered order returned (no invoice) | IntakeCoordinator |
| POST | /sleep-therapy/resupply-orders/{id}/cancel | Cancel a pre-authorization order | IntakeCoordinator |
| POST | /sleep-therapy/adherence-reports | Ingest an adherence data download | RespiratoryTherapist |
| GET | /sleep-therapy/adherence-reports | List adherence reports with filters | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| GET | /sleep-therapy/adherence-reports/{id} | Get an adherence report | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| POST | /sleep-therapy/adherence-reports/{id}/begin-review | Begin clinician review of a report | RespiratoryTherapist |
| POST | /sleep-therapy/adherence-reports/{id}/finalize | Finalize a report; updates patient compliance and cascades | RespiratoryTherapist |
| POST | /sleep-therapy/adherence-reports/{id}/reject | Reject a report without patient updates | RespiratoryTherapist |
| POST | /sleep-therapy/mask-exchanges | Request a mask fit exchange | IntakeCoordinator |
| GET | /sleep-therapy/mask-exchanges | List mask exchanges with filters | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| GET | /sleep-therapy/mask-exchanges/{id} | Get a mask exchange | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| POST | /sleep-therapy/mask-exchanges/{id}/approve | Approve an exchange (window and count checks) | RespiratoryTherapist |
| POST | /sleep-therapy/mask-exchanges/{id}/ship | Ship an exchange replacement | IntakeCoordinator |
| POST | /sleep-therapy/mask-exchanges/{id}/complete | Complete an exchange; resets the mask clock and supersedes priors | IntakeCoordinator |
| POST | /sleep-therapy/mask-exchanges/{id}/deny | Deny a requested exchange | RespiratoryTherapist |
| POST | /sleep-therapy/mask-exchanges/{id}/cancel | Cancel a requested or approved exchange | IntakeCoordinator |
| GET | /sleep-therapy/rental-contracts | List rental contracts with filters | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| GET | /sleep-therapy/rental-contracts/{id} | Get a rental contract | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| POST | /sleep-therapy/rental-contracts/{id}/bill-rental-month | Bill one rental month; auto-converts at the ownership threshold | BillingSpecialist |
| GET | /sleep-therapy/retrieval-cases | List retrieval cases with filters | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| GET | /sleep-therapy/retrieval-cases/{id} | Get a retrieval case | OpsAdmin, IntakeCoordinator, RespiratoryTherapist, BillingSpecialist |
| POST | /sleep-therapy/retrieval-cases/{id}/schedule-pickup | Schedule equipment pickup | IntakeCoordinator |
| POST | /sleep-therapy/retrieval-cases/{id}/mark-picked-up | Mark equipment picked up | IntakeCoordinator |
| POST | /sleep-therapy/retrieval-cases/{id}/mark-received | Mark equipment received; cascades enrollment and contract | IntakeCoordinator |
| POST | /sleep-therapy/retrieval-cases/{id}/reconcile | Reconcile a received case; finalizes patient discontinuation | IntakeCoordinator |
| POST | /sleep-therapy/retrieval-cases/{id}/close-unrecoverable | Close a case unrecoverable after the due date | IntakeCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_PAYER_POLICY_NOT_FOUND | 404 |
| ERR_PATIENT_NOT_IN_INTAKE | 409 |
| ERR_PATIENT_NOT_IN_ACTIVE_THERAPY | 409 |
| ERR_PATIENT_NOT_DISCONTINUABLE | 409 |
| ERR_PLAN_NOT_ACTIVE | 409 |
| ERR_QUANTITY_MISMATCH | 422 |
| ERR_CADENCE_NOT_MET | 409 |
| ERR_PRIOR_AUTH_REQUIRED | 422 |
| ERR_ORDER_NOT_PENDING_CLINICAL | 409 |
| ERR_COMPLIANCE_NOT_CURRENT | 422 |
| ERR_ORDER_NOT_PENDING_AUTH | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_STALE_PATIENT_VERSION | 412 |
| ERR_ORDER_NOT_READY_TO_SHIP | 409 |
| ERR_ORDER_NOT_AUTHORIZED | 409 |
| ERR_ORDER_NOT_SHIPPED | 409 |
| ERR_ORDER_NOT_DELIVERED | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_REPORT_NOT_RECEIVED | 409 |
| ERR_REPORT_NOT_UNDER_REVIEW | 409 |
| ERR_INVALID_WINDOW | 422 |
| ERR_EXCHANGE_NOT_REQUESTED | 409 |
| ERR_EXCHANGE_WINDOW_EXPIRED | 409 |
| ERR_EXCHANGE_LIMIT_REACHED | 409 |
| ERR_EXCHANGE_NOT_APPROVED | 409 |
| ERR_EXCHANGE_NOT_SHIPPED | 409 |
| ERR_RENTAL_NOT_BILLING | 409 |
| ERR_RENTAL_PERIOD_NOT_DUE | 409 |
| ERR_RENTAL_ALREADY_CONVERTED | 409 |
| ERR_RENTAL_NOT_IN_RETRIEVAL | 409 |
| ERR_ENROLLMENT_NOT_PENDING_SETUP | 409 |
| ERR_ENROLLMENT_NOT_READY_FOR_SETUP | 409 |
| ERR_ENROLLMENT_NOT_RETRIEVED | 409 |
| ERR_RETRIEVAL_NOT_OPEN | 409 |
| ERR_RETRIEVAL_NOT_SCHEDULED | 409 |
| ERR_RETRIEVAL_NOT_IN_TRANSIT | 409 |
| ERR_RETRIEVAL_NOT_RECEIVED | 409 |
| ERR_RETRIEVAL_NOT_CLOSABLE | 409 |
| ERR_RETRIEVAL_NOT_OVERDUE | 409 |
| ERR_RETRIEVAL_INVALID_STATE | 409 |
| ERR_INVALID_REQUEST | 400 |
