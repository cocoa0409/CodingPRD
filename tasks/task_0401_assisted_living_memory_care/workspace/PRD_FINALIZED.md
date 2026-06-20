# Assisted Living & Memory Care API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Assisted Living & Memory Care platform, a back-office system for operators of senior-living communities that blend assisted-living apartments with secured memory-care wings. The platform follows the prospective resident from first inquiry through clinical assessment, bed reservation, admission, ongoing care, monthly billing, and eventual discharge or transfer to a skilled-nursing facility. Around that resident journey it also tracks the physical bed inventory, the medication administration record (eMAR), fall and incident reporting, and the facility's standing with its state licensing authority.

The central tension the system resolves is that clinical, operational, and financial concerns are tightly coupled but owned by different staff disciplines. A resident's acuity — measured by activities-of-daily-living dependence, cognitive impairment, and documented behavioral risk — drives both the level of care they need and the monthly price they are charged. A memory-care diagnosis constrains which physical beds they may occupy. An outstanding balance blocks discharge; an active medication order blocks final discharge; a suspended license blocks new admissions. The platform exists to make these cross-cutting rules explicit and enforceable so that a registrar, a clinical director, a nurse, a billing clerk, and a compliance officer can each work within their own domain while the system guarantees the invariants that span all of them.

Because several of these workflows mutate shared parent records — a bed being reserved, a resident's care data being updated by a finalized assessment — the platform applies optimistic concurrency control at the points where two staff actions could legitimately collide, so that a stale view of a bed or a resident never silently overwrites a fresher one.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting staff member, and `X-User-Role` declares the operational capacity in which they are acting. If either header is absent, or if the value of `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.

The system recognizes six roles, spelled exactly as follows: `Registrar`, `ClinicalDirector`, `Nurse`, `BillingClerk`, `ComplianceOfficer`, and `Staff`. The `Registrar` owns admissions, the bed inventory, resident registration, and move-in agreements. The `ClinicalDirector` owns acuity assessments and care plans and may also place and discontinue medication orders. The `Nurse` owns eMAR administration and incident reporting and may also place and discontinue medication orders. The `BillingClerk` owns billing statements and payments. The `ComplianceOfficer` owns licensing actions and survey deficiencies, and is the only role permitted to escalate an incident into a deficiency. The `Staff` role is any authenticated staff member and confers read-only access to every collection and item retrieval endpoint across the API. When an authenticated caller invokes an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

All six roles use an opaque identity model. When `X-User-Role` is `Registrar`, `ClinicalDirector`, `Nurse`, `BillingClerk`, `ComplianceOfficer`, or `Staff`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The server may, however, record it where a workflow calls for it — for example, when a nurse records an eMAR administration, the recording nurse's identifier is stamped onto the new record as `administered_by_user_id`, and the witnessing nurse's identifier may be supplied as `witness_user_id` — but these are stored values, not ownership keys.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0.

Unless an endpoint states otherwise, every list is returned sorted by the resource's `created_at` timestamp in ascending order. Each list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification, refreshed on every mutation. The `version` is an integer that starts at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.6.

One entity is an exception to this convention. The medication administration record is an append-only, immutable audit event: each such record carries only an `id` and a `created_at`. It has no `updated_at` and no `version`, because once written it is never modified. Every other entity — facilities, units, residents, assessments, care plans, medication orders, move-in agreements, billing statements, incident reports, and survey deficiencies — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

Whenever a derived or computed field on a resource changes — for example a facility's occupancy figures, or a resident's open balance — that change counts as a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented, exactly as for a direct field edit.

### 2.5. Nested Resource Retrieval and Path Validation

Several endpoints address resources through a nested path that names more than one identifier — for instance a unit beneath a facility, or a deficiency beneath a facility. For any such request the system validates the path identifiers strictly from left to right and rejects on the first one that does not resolve. A request naming a facility and then a unit checks the facility first: if the facility does not exist the response is `ERR_FACILITY_NOT_FOUND`, and only if the facility resolves does the system look up the unit, returning `ERR_UNIT_NOT_FOUND` if that fails. The same left-to-right rule applies to facility-then-deficiency paths, where a missing facility yields `ERR_FACILITY_NOT_FOUND` and a missing deficiency within an existing facility yields `ERR_DEFICIENCY_NOT_FOUND`. Each remaining resource type has its own not-found code: `ERR_RESIDENT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CARE_PLAN_NOT_FOUND`, `ERR_MEDICATION_ORDER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, and `ERR_INCIDENT_NOT_FOUND`.

The same not-found codes apply to foreign-key references carried in a request body. When a create operation references a parent or related row — a `resident_id`, a `unit_id`, a `source_assessment_id`, a `supersedes_care_plan_id`, or a `medication_order_id` — and the referenced row does not exist, the request is rejected with the corresponding resource's not-found error.

### 2.6. Optimistic Concurrency Control

Two operations in this system mutate a shared parent record in a way that can collide with another staff member's concurrent action, and both are guarded by optimistic concurrency control. In each case the client must supply, as a required field in the request body, the version it last observed for the relevant parent; if that value does not equal the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` and an HTTP status of 412.

The first guarded operation is activating a move-in agreement. Activation reserves the agreement's bound unit, and the request must carry `expected_unit_version` holding the client's last observed `version` of that unit. If the unit's version has advanced since the client read it — most commonly because another agreement was activated and legitimately reserved the same bed, leaving the caller's belief that the bed is `AVAILABLE` stale — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), which prevents two agreements from double-reserving one bed.

The second guarded operation is finalizing an assessment. Finalizing mutates the parent resident's care level, care points, and possibly status, so the request must carry `expected_resident_version` holding the client's last observed `version` of that resident. If the resident's version has advanced since the client read it — most commonly because another assessment for the same resident was finalized, which supersedes the prior care data and bumps the resident — the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412). Other endpoints do not take a version field and are not subject to this check.

### 2.7. Monetary and Numeric Precision

All monetary amounts in the system are expressed and stored as whole integer cents; there are no fractional cents and no floating-point currency values. Where a calculation produces a fractional cent — which happens only during move-in proration — the result is rounded half up to the nearest whole cent. The care-points calculation is purely integer arithmetic over integer inputs and weights, so it requires no rounding. Occupancy rate is expressed in integer basis points and is likewise rounded half up. Plan-of-correction due dates are computed in whole calendar days. The exact rounding points within each calculation are specified in §3 alongside the workflow that triggers them.

### 2.8. State Transition Integrity and Cascading Effects

Resource state is governed by explicit state machines. A transition is only legal from the states the machine defines for it; an attempt to drive a transition from any other state is rejected with `ERR_INVALID_STATE`. Many transitions are triggered automatically by the system rather than by a direct client request on that resource — a unit becomes `RESERVED` because an agreement was activated, an assessment becomes `SUPERSEDED` because a newer one was finalized, a care plan becomes `ARCHIVED` because its resident was discharged. These automatic transitions and their accompanying recomputations are part of the triggering operation and are described in the relevant §3 workflow.

When a single operation affects more than one resource, every secondary effect is applied as part of that operation, and each mutated resource has its `updated_at` refreshed and its `version` incremented. The discharge cascade, the admission cascade, the assessment-finalize cascade, and the incident-escalation cascade are the most far-reaching of these and are spelled out in full in §3.

### 2.9. Facility Standing and Licensing

A facility carries a `license_status` reflecting its standing with the state authority, which is one of `ACTIVE`, `CONDITIONAL`, or `SUSPENDED`. A newly created facility begins `ACTIVE`. A compliance officer may move it among these states: placing it conditional advances `ACTIVE` to `CONDITIONAL`; suspending it advances either `ACTIVE` or `CONDITIONAL` to `SUSPENDED`; reinstating it returns either `SUSPENDED` or `CONDITIONAL` to `ACTIVE`. Each such action increments the facility's `version` by one. A conditional license is a flagged-but-operational state in which admissions are still allowed; only a suspended license blocks new admissions, as described in §3. The license action carries the `action` itself and accepts an optional `expected_facility_version`; this license action is not among the concurrency-guarded operations of §2.6, so the field is not required and is not subject to a stale-version rejection.

### 2.10. Computed Facility Metrics

A facility exposes several read-only aggregate metrics that the system keeps reconciled. The `bed_count` is the number of the facility's units whose status is not `RETIRED`. The `occupied_bed_count` is the number of its units whose status is `OCCUPIED`. The `occupancy_rate_bps` is the occupancy expressed in basis points. The `open_deficiency_count` is the number of survey deficiencies on the facility whose status is anything other than `CORRECTED`. The precise recomputation rules and the basis-points formula are given in §3 alongside the bed-inventory and deficiency workflows.

## 3. Business Logic & Workflows

### 3.1. Facilities, Beds, and the Occupancy Loop

A facility is the top-level organizing record and is created by either a `Registrar` or a `ComplianceOfficer`. Creation captures the facility `name`, the two-letter US `state_code` where it is licensed, its state-issued `license_number`, and the `care_point_rate_cents` — the price in cents charged per care point per month at that facility. On creation the facility's `license_status` is set to `ACTIVE` and all four computed metrics — `bed_count`, `occupied_bed_count`, `occupancy_rate_bps`, and `open_deficiency_count` — start at zero.

Beds are modeled as units beneath a facility and are created by a `Registrar`. A unit is created with a `unit_number` (the room or bed label), a `wing`, and a `monthly_base_rent_cents` — the base monthly rent in cents for that bed before any care points are added. The `wing` is one of `ASSISTED_LIVING` or `MEMORY_CARE`. The system stamps the owning `facility_id` onto the unit, sets its `status` to `AVAILABLE`, and leaves `current_resident_id` null. The `unit_number` must be unique within the facility among units that are not `RETIRED`; a collision is rejected with `ERR_DUPLICATE_UNIT_NUMBER`. Creating a unit recomputes the facility's `bed_count` and `occupancy_rate_bps`.

A unit moves through a cyclic occupancy loop: `AVAILABLE → RESERVED → OCCUPIED → CLEANING → AVAILABLE`. The system reserves a unit automatically — advancing `AVAILABLE → RESERVED` and stamping the reserving resident onto `current_resident_id` as a provisional hold — when a move-in agreement bound to that unit is activated. A reserved unit advances `RESERVED → OCCUPIED` automatically when the resident is admitted, which prompts a recomputation of the facility's `occupied_bed_count` and `occupancy_rate_bps`. If instead the binding agreement is cancelled, the reservation is released automatically, returning the unit `RESERVED → AVAILABLE` and clearing `current_resident_id`. When a resident's discharge is finalized, the unit advances `OCCUPIED → CLEANING`, `current_resident_id` is cleared, and the facility's `occupied_bed_count` and `occupancy_rate_bps` are recomputed. A `Registrar` returns a clean bed to service by marking it clean, which advances `CLEANING → AVAILABLE`. Marking clean is only legal from `CLEANING`; from any other state it is rejected with `ERR_INVALID_STATE`.

A `Registrar` may also retire a bed permanently, advancing `AVAILABLE → RETIRED`; `RETIRED` is terminal. Retiring is only legal from `AVAILABLE`, and otherwise rejected with `ERR_INVALID_STATE`. Retiring a unit recomputes the facility's `bed_count` and `occupancy_rate_bps`.

The facility metrics are derived as a strict aggregation over the facility's units. The `bed_count` is the count of units belonging to the facility whose status is not `RETIRED`. The `occupied_bed_count` is the count of units belonging to the facility whose status is `OCCUPIED`. The occupancy rate is computed in basis points on a scale of ten thousand: when `bed_count` is zero the `occupancy_rate_bps` is exactly zero (the empty-facility case never raises a division error), and otherwise it is the occupied bed count multiplied by ten thousand, divided by the bed count, with the result rounded half up to a whole number of basis points. These metrics are recomputed on unit creation, unit retirement, resident admission, and resident discharge finalization.

### 3.2. Registering and Assessing a Resident

A `Registrar` registers a prospective resident, supplying the `facility_id` the resident is associated with, the resident's `full_name`, their `date_of_birth` as an ISO `YYYY-MM-DD` date, and optionally a `stay_type` and a `respite_end_date`. The `stay_type` is one of `STANDARD` or `RESPITE` and defaults to `STANDARD`; a standard stay is a long-term residency, while a respite stay is a planned short-term stay. A respite stay requires a `respite_end_date` — the ISO date the stay is scheduled to end, which must fall strictly after the resident's move-in or admission context — whereas a standard stay must omit it entirely. Supplying a respite stay without a valid end date, or supplying an end date on a standard stay, is rejected with `ERR_INVALID_RESPITE_WINDOW`. A freshly registered resident begins in status `PROSPECT`, with `current_care_points` and `open_balance_cents` both zero and `current_care_level` null until the first assessment is finalized.

A resident moves through the lifecycle `PROSPECT → ASSESSED → ADMITTED → DISCHARGE_PENDING → DISCHARGED`, with two loops that fold back on it: an `ADMITTED → ASSESSED` reassessment loop and a `DISCHARGE_PENDING → ADMITTED` rescind. The resident's clinical acuity is established by a `ClinicalDirector` through an **Assessment**, which is created in `DRAFT` status against a `resident_id`. The assessment captures five activities-of-daily-living dependence scores — `adl_bathing`, `adl_dressing`, `adl_toileting`, `adl_transferring`, and `adl_eating`, each an integer from 0 (independent) to 4 (total dependence) — a `cognition_score` integer from 0 (intact) to 10 (severe), and an optional `behavior_flags` count of documented behavioral risk flags such as wandering, aggression, or exit-seeking, which defaults to zero. Any ADL score outside 0 through 4, a cognition score outside 0 through 10, or a negative behavior-flag count is rejected with `ERR_INVALID_ASSESSMENT_INPUT`.

Care points quantify acuity. At assessment creation a provisional `care_points_total` and `care_level` are computed and stored on the draft row, where they remain mutable while the assessment is `DRAFT`; they are not yet copied to the resident. The total is built from three components added together. The ADL component is the sum of the five ADL scores (which ranges from 0 to 20) multiplied by an ADL point weight of three. The cognition component is the cognition score multiplied by a cognition weight of two. The behavior component takes the behavior-flag count but caps it at four before weighting — that is, the smaller of the flag count and four — and multiplies that capped value by a behavior weight of five. The `care_points_total` is the sum of these three components. Because every input and weight is an integer, the total is an exact integer and no rounding is applied.

The `care_level` is assigned by a threshold ladder that a cognition gate can override. It is one of `LEVEL_1`, `LEVEL_2`, `LEVEL_3`, or `MEMORY_CARE`. First, if the cognition score is at least the memory-care cognition threshold of seven, the care level is `MEMORY_CARE` regardless of the point total — the cognition gate overrides the point tiers. Otherwise the level is read from the point total: a total of at least fifty-five is `LEVEL_3`; a total below fifty-five but at least thirty is `LEVEL_2`; and any total below thirty is `LEVEL_1`. The tier boundaries are inclusive at the lower edge, so a resident whose `care_points_total` is exactly equal to a tier minimum lands in the higher tier.

### 3.3. Finalizing an Assessment and Updating the Resident

A `ClinicalDirector` finalizes a draft assessment, advancing it `DRAFT → FINALIZED`. Finalizing is only legal when the assessment is `DRAFT` and the owning resident is not `DISCHARGED`; otherwise it is rejected with `ERR_INVALID_STATE`. Because finalizing mutates the parent resident, the request must carry `expected_resident_version` matching the resident's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` as described in §2.6.

On finalize, the `care_points_total` and `care_level` are recomputed once from the row's then-current inputs and frozen; a finalized assessment is thereafter immutable, so no later input edit can change them. Any other assessment for the same resident that was previously `FINALIZED` is automatically transitioned `FINALIZED → SUPERSEDED`, reflecting that the new assessment is now the authoritative one. The newly finalized assessment's `care_level` is copied to the resident's `current_care_level`, and its `care_points_total` is copied to the resident's `current_care_points`. Finally the resident's status advances: a resident who was `PROSPECT` becomes `ASSESSED` on the first finalize, and a resident who was already `ADMITTED` returns to `ASSESSED` as a reassessment. The resident's `version` is incremented by one as part of this update. Whether triggered by a first assessment or by a reassessment, the care-level and care-points copy happens immediately on finalize.

### 3.4. Building and Revising the Care Plan

Once a resident has a finalized assessment, a `ClinicalDirector` builds a **CarePlan**, created in `DRAFT` status. A care plan is created with a `resident_id`, a `source_assessment_id` naming the finalized assessment it is built from, an `adl_support_items` array of support-task objects each describing a `task` and a `frequency_per_day`, and an optional `supersedes_care_plan_id` naming the prior active plan this revision replaces (null for a resident's first plan). The self-referential `supersedes_care_plan_id` chains plan revisions over time.

A care plan moves through `DRAFT → ACTIVE → SUPERSEDED` for the revision loop, and `ACTIVE` or `DRAFT → ARCHIVED` when its resident is discharged. A `ClinicalDirector` activates a draft plan, advancing it `DRAFT → ACTIVE`. Activation is only legal when the plan is `DRAFT`, when its source assessment is `FINALIZED`, and when the owning resident is in either `ASSESSED` or `ADMITTED` status; otherwise it is rejected with `ERR_INVALID_STATE`. If the activated plan names a prior plan in its `supersedes_care_plan_id`, that prior plan is automatically transitioned `ACTIVE → SUPERSEDED` as part of the activation, so a resident has at most one active plan at a time.

### 3.5. Move-In Agreements and Admission

A move-in agreement binds a resident to a specific bed and is the bridge between the clinical and operational sides of the system. A `Registrar` drafts an agreement with a `resident_id`, a `unit_id` naming the bed, a `move_in_date` (the ISO date the resident occupies the bed, which also serves as the billing anchor day), and an optional `community_fee_cents` — a one-time, non-refundable community fee in cents charged on the first statement, defaulting to zero. On drafting, the agreement's `monthly_base_rent_cents` is snapshotted from the unit's current base rent so that later rent changes on the bed do not retroactively alter a signed agreement, and the agreement begins in `DRAFT` status. A resident may have at most one agreement that is in either `DRAFT` or `ACTIVE` status at any time; attempting to draft a second open agreement is rejected with `ERR_AGREEMENT_ALREADY_OPEN`.

An agreement moves through `DRAFT → ACTIVE → TERMINATED`, or `DRAFT → CANCELLED`. A `Registrar` activates a draft agreement, which advances it `DRAFT → ACTIVE` and reserves the bound bed. Activation carries the optimistic-concurrency field `expected_unit_version` described in §2.6. Beyond the version check, activation enforces a set of bed-eligibility rules. The bound unit must be `AVAILABLE` at activation time; if it is not, the activation is rejected with `ERR_BED_NOT_AVAILABLE`. The bed's wing must match the resident's care wing: a resident whose `current_care_level` is `MEMORY_CARE` may only be bound to a unit whose `wing` is `MEMORY_CARE`, and a violation is rejected with `ERR_WING_MISMATCH`. When activation succeeds, the agreement becomes `ACTIVE`, the bound unit advances `AVAILABLE → RESERVED`, the unit's `current_resident_id` is set to the agreement's resident, and the unit's `version` is incremented by one.

Cancelling a draft agreement advances it `DRAFT → CANCELLED`. If the agreement had already reserved a bed, cancellation releases it: the bound unit returns `RESERVED → AVAILABLE` and its `current_resident_id` is cleared.

A `Registrar` admits an `ASSESSED` resident to their reserved bed, advancing the resident `ASSESSED → ADMITTED`. Admission is only legal when the resident is `ASSESSED`, when the facility's `license_status` is not `SUSPENDED`, and when the resident has an `ACTIVE` move-in agreement whose bound unit is `RESERVED` and held for this resident. Admission against a suspended facility is rejected with `ERR_LICENSE_SUSPENDED`; an attempt from any other resident state is rejected with `ERR_INVALID_STATE`. On admission the bound unit advances `RESERVED → OCCUPIED`, the unit's `current_resident_id` is set to the resident, the resident's `assigned_unit_id` is set to the agreement's unit, and the facility's `occupied_bed_count` and `occupancy_rate_bps` are recomputed.

### 3.6. Discharge, Transfer, and the Discharge Cascade

Discharge proceeds in two steps that bracket a rescindable pending state. A `Registrar` initiates discharge on an `ADMITTED` resident, advancing them `ADMITTED → DISCHARGE_PENDING`. Initiation is only legal from `ADMITTED`, and it additionally requires that the resident's `open_balance_cents` be exactly zero; a resident who still owes money cannot begin discharge and is rejected with `ERR_OUTSTANDING_BALANCE`. While in `DISCHARGE_PENDING`, a `Registrar` may rescind, advancing the resident `DISCHARGE_PENDING → ADMITTED` with no further side effects.

A `Registrar` finalizes discharge from `DISCHARGE_PENDING`, supplying a `disposition` of either `TRANSFER_TO_SNF` (transfer to a skilled-nursing facility) or `OTHER`. Finalization is only legal from `DISCHARGE_PENDING` and additionally requires that every medication order for the resident already be `DISCONTINUED`; if any order is still active the request is rejected with `ERR_ACTIVE_MED_ORDERS`. The two dispositions differ only in the recorded `discharge_disposition` value; the cascade they trigger is identical. On finalize the resident advances `DISCHARGE_PENDING → DISCHARGED`, `discharge_disposition` is set to the supplied disposition, the bound unit advances `OCCUPIED → CLEANING` with its `current_resident_id` cleared, the facility's `occupied_bed_count` and `occupancy_rate_bps` are recomputed, the resident's `ACTIVE` move-in agreement advances to `TERMINATED`, the resident's care plan is archived — an `ACTIVE` plan and a `DRAFT` plan alike advance to `ARCHIVED` — and the resident's `assigned_unit_id` is cleared. `DISCHARGED` is terminal.

### 3.7. Medication Orders and the eMAR

Either a `Nurse` or a `ClinicalDirector` may place a medication order, which is created in `ACTIVE` status. An order names a `resident_id`, a `drug_name`, a `dose` string such as "5 mg", a non-empty `schedule_times` array of the local `HH:MM` times the dose is due each day, and an optional `is_controlled` boolean (defaulting to false) marking a controlled substance that requires witnessed administration. Either role may also discontinue an order, advancing it `ACTIVE → DISCONTINUED`; discontinuation is only legal from `ACTIVE`, and `DISCONTINUED` is terminal.

Administrations are recorded against an order as **medication administration records** by a `Nurse`. Each administration is an append-only, immutable event capturing the `scheduled_time` slot being recorded, the `outcome`, and an optional `witness_user_id`. The `outcome` is one of `GIVEN`, `REFUSED`, `HELD`, or `MISSED`. The system stamps the `resident_id` (copied from the order) and the `administered_by_user_id` (the recording nurse's identifier) onto the record. The `scheduled_time` must be one of the times listed in the order's `schedule_times`; a slot that is not a member of that list is rejected with `ERR_INVALID_MED_SLOT`. When the order is controlled and the recorded outcome is `GIVEN`, a `witness_user_id` is required and it must be different from the administering nurse; a missing or non-distinct witness is rejected with `ERR_WITNESS_REQUIRED`.

### 3.8. Monthly Billing, Issuance, and Payments

A `BillingClerk` creates a **BillingStatement** in `DRAFT` status for a resident and a billing month. Creation supplies the `resident_id`, the `period_year` (for example 2026), the `period_month` (an integer from 1 to 12), and an optional `is_first_statement` boolean (defaulting to false) that marks the move-in-month statement, which alone applies the community fee and move-in proration. At most one non-void statement may exist for a given resident, year, and month combination; a duplicate is rejected with `ERR_DUPLICATE_STATEMENT_PERIOD`.

A statement moves through `DRAFT → ISSUED → PARTIALLY_PAID → PAID`, and either `ISSUED` or `PARTIALLY_PAID` may be voided to `VOID`. A `BillingClerk` issues a draft statement, advancing it `DRAFT → ISSUED`; issuing requires that the resident have an `ACTIVE` move-in agreement (the rent and care lines need a bound bed). At issuance the charge lines are computed and frozen, and the resident's `open_balance_cents` is recomputed because the statement now joins the open set.

The charge computation produces three line items and a total. The care-points monthly figure is the resident's `current_care_points` multiplied by the facility's `care_point_rate_cents`. The base-rent monthly figure is the agreement's snapshotted `monthly_base_rent_cents`. For an ordinary (non-first) statement there is no proration: the `rent_charge_cents` is the full base-rent monthly figure, the `care_points_charge_cents` is the full care-points monthly figure, and the `community_fee_charge_cents` is zero. For the first statement the rent and care lines are prorated by the move-in date. The number of billable days is the number of calendar days in the billing month minus the quantity (the day-of-month of the move-in date minus one) — that is, the move-in day through the last day of the month, inclusive. Proration is then applied **per line, rounding each line independently**: the `rent_charge_cents` is the base-rent monthly figure multiplied by billable days, divided by days in the month, rounded half up to whole cents; the `care_points_charge_cents` is the care-points monthly figure multiplied by billable days, divided by days in the month, rounded half up to whole cents; and the `community_fee_charge_cents` is the agreement's `community_fee_cents`. The rounding order is pinned: each line is prorated and rounded to whole cents on its own, and only then are the lines summed — the two monthly figures must not be summed first and the combined total prorated, because on fractional days that order yields a different cent. The `total_charge_cents` is the sum of `rent_charge_cents`, `care_points_charge_cents`, and `community_fee_charge_cents`.

A `BillingClerk` records a payment against an issued statement, supplying an `amount_cents`. The payment must be greater than zero and at most the remaining balance, which is the `total_charge_cents` minus the cumulative `paid_cents`; a payment that is non-positive or exceeds the remaining balance is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. When the amount is strictly less than the remaining balance, it is added to `paid_cents` and the statement moves to (or remains in) `PARTIALLY_PAID`: an `ISSUED` statement advances `ISSUED → PARTIALLY_PAID`, and a `PARTIALLY_PAID` statement stays `PARTIALLY_PAID`. When the amount exactly equals the remaining balance, `paid_cents` is set to the `total_charge_cents` and the statement advances to `PAID` — `ISSUED → PAID` or `PARTIALLY_PAID → PAID`. Every payment recomputes the resident's `open_balance_cents`.

A `BillingClerk` may void a statement that is `ISSUED` or `PARTIALLY_PAID`, advancing it to `VOID`; voiding removes the statement from the resident's open set and recomputes the resident's `open_balance_cents`. The resident's `open_balance_cents` is the sum, over the resident's billing statements whose status is `ISSUED` or `PARTIALLY_PAID`, of each statement's `total_charge_cents` minus its `paid_cents`; it is recomputed whenever a statement is issued, paid against, or voided.

### 3.9. Incident Reporting and Escalation

A `Nurse` files an **IncidentReport** against a resident in `REPORTED` status, supplying the `resident_id`, the `incident_type` (one of `FALL`, `MEDICATION_ERROR`, `ELOPEMENT`, `INJURY`, or `OTHER`), the `occurred_at` timestamp, and the clinical `severity` (one of `MINOR`, `MODERATE`, or `SEVERE`). On creation the system computes `requires_state_report`, which is true when the severity is `SEVERE` or the incident type is `ELOPEMENT` — such incidents are state-reportable within twenty-four hours. The `linked_deficiency_id` is null until the incident is escalated.

An incident moves through `REPORTED → UNDER_INVESTIGATION`, and then forks: `UNDER_INVESTIGATION → RESOLVED` or `UNDER_INVESTIGATION → ESCALATED`. A `Nurse` begins investigation, advancing the incident `REPORTED → UNDER_INVESTIGATION`. From there a `Nurse` may resolve it, advancing `UNDER_INVESTIGATION → RESOLVED` with no deficiency spawned; `RESOLVED` is terminal. Alternatively a `ComplianceOfficer` may escalate it, advancing `UNDER_INVESTIGATION → ESCALATED`; `ESCALATED` is terminal. Escalation is only legal when the incident is `UNDER_INVESTIGATION` and additionally requires that `requires_state_report` be true; escalating an incident that is not state-reportable is rejected with `ERR_NOT_STATE_REPORTABLE`. Escalation carries `scope_severity`, `tag_code`, and `cited_at` for the deficiency it spawns. As its cascade, escalation creates a new survey deficiency on the resident's facility in `CITED` status with that scope/severity, sets the incident's `linked_deficiency_id` to the new deficiency's id, and recomputes the facility's `open_deficiency_count`.

### 3.10. Survey Deficiencies and Plans of Correction

A `ComplianceOfficer` cites a **SurveyDeficiency** against a facility in `CITED` status, supplying a `tag_code` (the state survey tag such as "F-880"), a `scope_severity`, and a `cited_at` timestamp. The system stamps the owning `facility_id`, computes the `poc_due_date`, leaves `poc_text` null, and recomputes the facility's `open_deficiency_count`. The `scope_severity` is one of `A_C_NO_HARM`, `D_F_NO_HARM`, `G_I_ACTUAL_HARM`, or `J_L_IMMEDIATE_JEOPARDY`. The plan-of-correction due date is computed by calendar-day addition from the citation date: when the scope/severity band is `J_L_IMMEDIATE_JEOPARDY` the window is two calendar days, and for every other band the window is ten calendar days; the `poc_due_date` is the calendar date of `cited_at` plus the selected number of days.

A deficiency moves through `CITED → POC_SUBMITTED → POC_ACCEPTED → CORRECTED`, with a resubmission loop `POC_SUBMITTED → POC_REJECTED → POC_SUBMITTED`. A `ComplianceOfficer` submits a plan of correction, which advances `CITED → POC_SUBMITTED` and stores the supplied `poc_text` on the deficiency. The same submit action resubmits a rejected plan, advancing `POC_REJECTED → POC_SUBMITTED` and overwriting `poc_text` with the resubmitted narrative. A `ComplianceOfficer` reviews a submitted plan with a `decision` of either accept or reject: accepting advances `POC_SUBMITTED → POC_ACCEPTED`, and rejecting advances `POC_SUBMITTED → POC_REJECTED`. Finally a `ComplianceOfficer` marks an accepted deficiency corrected, advancing `POC_ACCEPTED → CORRECTED`, which removes the deficiency from the open set and recomputes the facility's `open_deficiency_count`. `CORRECTED` is terminal, and each of these transitions is rejected with `ERR_INVALID_STATE` when attempted from a state other than the one its transition is defined from. The facility's `open_deficiency_count` is the count of survey deficiencies on the facility whose status is not `CORRECTED`, recomputed on every deficiency state change.

### 3.11. Filtering, Validation Ordering, and Read Access

List endpoints support reverse-reachability filtering by foreign key. Units may be filtered by `facility_id` and by `current_resident_id`, and additionally by `wing` and `status`. Residents may be filtered by `facility_id` and by `assigned_unit_id`, and by `status`. Assessments may be filtered by `resident_id` and by `status`. Care plans may be filtered by `resident_id`, by `source_assessment_id`, and by `supersedes_care_plan_id`, and by `status`. Medication orders may be filtered by `resident_id` and by `status`. Administrations may be filtered by `resident_id` and by `medication_order_id`. Move-in agreements may be filtered by `resident_id` and by `unit_id`, and by `status`. Billing statements may be filtered by `resident_id` and by `status`. Incident reports may be filtered by `resident_id`, by `linked_deficiency_id`, and by `status`. Survey deficiencies may be filtered by `facility_id` and by `status`. Every retrieval endpoint — both collection lists and single-item gets — is available to the `Staff` role.

When an endpoint is subject to several checks, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. The order is: first, that the `X-User-ID` and `X-User-Role` headers are present and the role is known (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, that the role is permitted for the operation (`ERR_INSUFFICIENT_PERMISSIONS`); third, that every resource named in the path exists, validated left to right (the resource-specific not-found errors); fourth, that every foreign-key field carried in the request body references an existing row (the resource-specific not-found errors); fifth, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); sixth, the optimistic-concurrency check on any declared `expected_unit_version` or `expected_resident_version` (`ERR_STALE_VERSION`); and only then the operation-specific business constraints described above. A malformed body, a missing required field, or a type mismatch is rejected with `ERR_INVALID_REQUEST`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including all state-transition actions and payment recording — return `200 OK`. Retrieval operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/facilities` | Create a facility | Registrar, ComplianceOfficer |
| GET | `/facilities` | List facilities | Staff |
| GET | `/facilities/{facilityId}` | Get a facility with computed occupancy and deficiency counts | Staff |
| POST | `/facilities/{facilityId}/license-action` | Apply a license action (PLACE_CONDITIONAL, SUSPEND, or REINSTATE) | ComplianceOfficer |
| POST | `/facilities/{facilityId}/units` | Create a unit/bed in a facility | Registrar |
| GET | `/units` | List units, filterable by facility, resident, wing, and status | Staff |
| GET | `/units/{unitId}` | Get a unit | Staff |
| POST | `/facilities/{facilityId}/units/{unitId}/mark-clean` | Mark a cleaning unit back to available | Registrar |
| POST | `/facilities/{facilityId}/units/{unitId}/retire` | Retire an available unit | Registrar |
| POST | `/residents` | Register a prospective resident | Registrar |
| GET | `/residents` | List residents, filterable by facility, unit, and status | Staff |
| GET | `/residents/{residentId}` | Get a resident with computed care level, points, and balance | Staff |
| POST | `/residents/{residentId}/admit` | Admit an assessed resident to their reserved bed | Registrar |
| POST | `/residents/{residentId}/initiate-discharge` | Move an admitted resident to discharge-pending | Registrar |
| POST | `/residents/{residentId}/rescind-discharge` | Rescind a pending discharge | Registrar |
| POST | `/residents/{residentId}/finalize-discharge` | Finalize discharge with a disposition | Registrar |
| POST | `/assessments` | Create a draft acuity assessment for a resident | ClinicalDirector |
| GET | `/assessments` | List assessments, filterable by resident and status | Staff |
| GET | `/assessments/{assessmentId}` | Get an assessment | Staff |
| POST | `/assessments/{assessmentId}/finalize` | Finalize an assessment, freezing points/level and updating the resident | ClinicalDirector |
| POST | `/care-plans` | Create a draft care plan from a finalized assessment | ClinicalDirector |
| GET | `/care-plans` | List care plans, filterable by resident, source assessment, superseded plan, and status | Staff |
| GET | `/care-plans/{carePlanId}` | Get a care plan | Staff |
| POST | `/care-plans/{carePlanId}/activate` | Activate a draft care plan | ClinicalDirector |
| POST | `/medication-orders` | Create an active medication order | Nurse, ClinicalDirector |
| GET | `/medication-orders` | List medication orders, filterable by resident and status | Staff |
| GET | `/medication-orders/{medicationOrderId}` | Get a medication order | Staff |
| POST | `/medication-orders/{medicationOrderId}/discontinue` | Discontinue a medication order | Nurse, ClinicalDirector |
| POST | `/medication-orders/{medicationOrderId}/administrations` | Record an eMAR administration event | Nurse |
| GET | `/administrations` | List eMAR events, filterable by resident and medication order | Staff |
| GET | `/administrations/{administrationId}` | Get a single eMAR administration record | Staff |
| POST | `/move-in-agreements` | Draft a move-in agreement binding a resident to a unit | Registrar |
| GET | `/move-in-agreements` | List move-in agreements, filterable by resident, unit, and status | Staff |
| GET | `/move-in-agreements/{agreementId}` | Get a move-in agreement | Staff |
| POST | `/move-in-agreements/{agreementId}/activate` | Activate a draft agreement, reserving the bed | Registrar |
| POST | `/move-in-agreements/{agreementId}/cancel` | Cancel a draft agreement, releasing any reserved bed | Registrar |
| POST | `/billing-statements` | Create a draft billing statement for a resident period | BillingClerk |
| GET | `/billing-statements` | List billing statements, filterable by resident and status | Staff |
| GET | `/billing-statements/{statementId}` | Get a billing statement | Staff |
| POST | `/billing-statements/{statementId}/issue` | Issue a draft statement, computing and freezing charge lines | BillingClerk |
| POST | `/billing-statements/{statementId}/payments` | Record a payment against an issued statement | BillingClerk |
| POST | `/billing-statements/{statementId}/void` | Void an issued or partially-paid statement | BillingClerk |
| POST | `/incident-reports` | File a fall/incident report | Nurse |
| GET | `/incident-reports` | List incident reports, filterable by resident, linked deficiency, and status | Staff |
| GET | `/incident-reports/{incidentId}` | Get an incident report | Staff |
| POST | `/incident-reports/{incidentId}/investigate` | Begin investigation | Nurse |
| POST | `/incident-reports/{incidentId}/resolve` | Resolve an investigated incident | Nurse |
| POST | `/incident-reports/{incidentId}/escalate` | Escalate a state-reportable incident into a survey deficiency | ComplianceOfficer |
| POST | `/facilities/{facilityId}/deficiencies` | Cite a survey deficiency against a facility | ComplianceOfficer |
| GET | `/deficiencies` | List survey deficiencies, filterable by facility and status | Staff |
| GET | `/deficiencies/{deficiencyId}` | Get a survey deficiency | Staff |
| POST | `/facilities/{facilityId}/deficiencies/{deficiencyId}/submit-poc` | Submit or resubmit a plan of correction | ComplianceOfficer |
| POST | `/facilities/{facilityId}/deficiencies/{deficiencyId}/review-poc` | Accept or reject a submitted plan of correction | ComplianceOfficer |
| POST | `/facilities/{facilityId}/deficiencies/{deficiencyId}/mark-corrected` | Mark an accepted deficiency corrected | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_RESIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CARE_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_MEDICATION_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_DEFICIENCY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_ASSESSMENT_INPUT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_UNIT_NUMBER` | 409 Conflict |
| `ERR_INVALID_RESPITE_WINDOW` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_ALREADY_OPEN` | 409 Conflict |
| `ERR_BED_NOT_AVAILABLE` | 409 Conflict |
| `ERR_WING_MISMATCH` | 409 Conflict |
| `ERR_LICENSE_SUSPENDED` | 409 Conflict |
| `ERR_WITNESS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_MED_SLOT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_STATEMENT_PERIOD` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_OUTSTANDING_BALANCE` | 409 Conflict |
| `ERR_ACTIVE_MED_ORDERS` | 409 Conflict |
| `ERR_NOT_STATE_REPORTABLE` | 409 Conflict |
