# Fertility Preservation & Egg Freezing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Fertility Preservation & Egg Freezing platform, an API that orchestrates the elective egg-freezing journey from a patient's first consultation through long-term cryogenic storage and, eventually, thaw or transfer. The domain is unusual in that it blends a tightly sequenced clinical workflow — ovarian-reserve testing, a stimulation-cycle protocol with a monitoring calendar, an egg-retrieval procedure, and cryopreservation into physical storage tanks — with a parallel set of financial and compliance concerns: annual storage subscriptions, employer-sponsored benefit coverage, signed consent and disposition directives, and invoicing.

The platform serves several distinct actors whose duties must remain separated. Care coordinators open consultations and build the cycle calendar; reproductive endocrinologists (physicians) run the clinical protocol and both request and authorize thaws; lab embryologists manage the cryo tanks and execute thaws; billing administrators run subscriptions, benefit coverage, and invoices; and patients themselves own the consent and disposition directives that govern what may be done with their frozen oocytes. Because a single retrieval or thaw cascades across inventory counts, subscription billing, and benefit ledgers, the system's correctness depends on precise, deterministic reconciliation of derived fields at every step.

A guiding principle throughout is that no oocyte may be reserved, thawed, transferred, or discarded without the correct authorizations in place, and that every financial figure — cycle cost, storage renewal fee, facility fee, and benefit coverage — is computed by a pinned, reproducible rule. This document defines those rules in full.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply across every endpoint. All resource collections are top-level: there is no URL nesting between aggregates, and relationships between resources are expressed through foreign-key fields carried in request bodies and responses.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly six roles: `Patient`, `Coordinator`, `Physician`, `Embryologist`, `BillingAdmin`, and `PlatformAdmin`.

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a patient compare that resource's `patient_id` to `X-User-ID`. A patient may only revoke a directive they own.
- When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting `Provider`; when a physician requests or authorizes a thaw, the server records their `X-User-ID` as the `requester_provider_id` or `authorizer_provider_id` respectively.
- When `X-User-Role` is `Embryologist`, `X-User-ID` is likewise the `id` of the acting `Provider`.
- When `X-User-Role` is `Coordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `BillingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Section 4 lists, per endpoint, the roles authorized to invoke it. Role authorization (priority 2) is evaluated only after authentication (priority 1) succeeds.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order; resources sharing an identical `created_at` are ordered by the sequence in which they were created (persistence order).

Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the query before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties

Every resource in the system carries a system-managed set of common fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. `updated_at` is an ISO 8601 UTC timestamp reflecting the most recent mutation. `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource. All timestamps are derived from the system's logical clock (see §2.6), never from wall-clock time.

Foreign-key references between resources (for example a `patient_id`, `consultation_id`, `cycle_id`, `provider_id`, `tank_id`, `retrieval_room_id`, `consent_directive_id`, or `disposition_directive_id`) are plain string fields carrying the referenced resource's `id`.

### 2.5. Monetary Values, Precision, and Rounding

All monetary values are stored and returned as integer cents; there are no fractional cents. Wherever a computation multiplies by a fraction or percentage, the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). The specific point at which rounding occurs is pinned per calculation and is stated in the relevant workflow subsection — most importantly, the storage renewal fee rounds each specimen's discounted fee before multiplying by the specimen count, and the facility fee and benefit coverage each round their single percentage product. Counts and integer quantities (such as oocyte counts and tank slots) are exact integers and are not rounded.

### 2.6. The Logical Clock and Temporal Semantics

The system operates on a logical clock rather than real time. Before any clock value is set, the server's clock reads `2026-05-01T00:00:00Z`. A `PlatformAdmin` may advance the clock by supplying a `to_iso8601` instant; the endpoint returns the new `current_utc`. All timestamp fields — including `created_at`, `updated_at`, `signed_at`, `trigger_at`, retrieval windows, subscription periods, and `last_paid_at` — are taken from this logical clock at the moment the relevant operation executes.

Two kinds of temporal overlap checks exist and differ deliberately. Monitoring appointments are checked against a provider's existing appointments using a buffered exclusion window (§3.3). Retrieval windows are checked against a room's existing retrievals using a strict half-open interval with no buffer, so back-to-back retrievals that merely touch at an endpoint are allowed (§3.4).

### 2.7. State Transitions, Cascades, and Derived-Field Reconciliation

Several resources carry a `status` governed by a state machine; the legal transitions and their preconditions are described in §3. Any attempt to drive a resource through a transition for which it is not in the correct originating state is rejected with `ERR_INVALID_STATE`. Every transition or reconciliation that mutates a resource refreshes that resource's `updated_at` and increments its `version`, including reconciliations the server performs automatically as a side effect of another operation.

Three derived quantities are reconciled immediately whenever their inputs change, and must always equal the value implied by their definition:

- A `StorageTank`'s `used_slots` is the count of `CryoSpecimen` rows assigned to that tank whose `status` is either `STORED` or `RESERVED`. The tank's `is_full` is true exactly when `used_slots` is greater than or equal to `capacity_slots`. A specimen moving into `RESERVED` does not change `used_slots` (it still occupies its slot); a specimen moving to `THAWED` or `DISCARDED` frees its slot and decrements `used_slots`.
- A `StorageSubscription`'s `specimen_count` is the count of that patient's `CryoSpecimen` in `STORED` or `RESERVED` status, and its `annual_fee_cents` is the most recent storage-renewal-fee result over that count (§3.5).
- A `BenefitCoverage`'s `remaining_cents` equals `annual_cap_cents` minus `consumed_cents`, and this invariant — consumed plus remaining always equals the annual cap — holds after every finalize and void (§3.8).

Because these fields are server-derived, clients never write them directly; they are recomputed as a cascade of the operations described in §3.

### 2.8. Optimistic Concurrency Control on Directive Creation

Creating a directive is the one operation guarded by optimistic concurrency control on a parent entity's version. A create-directive request must carry `expected_patient_version`, the `version` of the target `Patient` the client last observed. If that value does not match the patient's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because creating a new directive of the same `directive_type` supersedes the prior active directive for that patient and increments the patient's `version` by one; a client that read the patient before such a supersede and then submits a create still carrying the older version is acting on a stale view and is rejected. Directive creation is the only endpoint that takes a version field; no other endpoint accepts or requires one.

### 2.9. Validation Ordering and Reference Resolution

When multiple conditions could reject a request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The global ordering is: (1) authentication (`ERR_UNAUTHENTICATED`); (2) role authorization (`ERR_UNAUTHORIZED`); (3) request-body schema validation such as missing required fields, unknown enum values, wrong types, values that violate a non-negative or positive constraint, or a `scheduled_end` that is not strictly after `scheduled_start` (`ERR_VALIDATION`); (4) existence of every referenced resource, whether named in the path or in the body, validated left-to-right (`ERR_NOT_FOUND`); (5) the target resource being in a legal state for the requested transition (`ERR_INVALID_STATE`); (6) the directive optimistic-concurrency check (`ERR_STALE_VERSION`); and then the business rules of priorities 7 through 18, described in their workflow subsections. A lower priority number always wins: for example, an unauthenticated request to a non-existent resource returns `ERR_UNAUTHENTICATED`, not `ERR_NOT_FOUND`.

When a request references several resources, existence is checked in the left-to-right order the identifiers appear, and the first missing reference determines the `ERR_NOT_FOUND` response before any later reference or business rule is evaluated.

## 3. Business Logic & Workflows

### 3.1. Foundational Resources: Patients, Providers, Rooms, and Tanks

The journey begins with a `Patient`, onboarded by a `Coordinator` or a `BillingAdmin` with a `full_name`, a `date_of_birth`, an `email`, and an optional `employer_name` used later to match employer benefit coverage. Patient records are readable by any role.

Operational resources are provisioned by administrators. A `PlatformAdmin` registers each clinical `Provider` with a `full_name`, a `provider_role` of either `PHYSICIAN` or `EMBRYOLOGIST`, and an optional `npi` (National Provider Identifier). A `PlatformAdmin` also creates each `ProcedureRoom` with a `name` and a `room_kind` of either `RETRIEVAL_OR` or `PROCEDURE`. Cryogenic storage tanks may be created by either an `Embryologist` or a `PlatformAdmin`: each `StorageTank` has a `name` and a `capacity_slots` value, which must be at least 1 and represents the maximum number of specimens (vials or straws) it can hold. A tank's `used_slots` starts at 0 and its `is_full` starts false; both are derived thereafter as described in §2.7 and observable by reading the tank.

### 3.2. Consultation and Ovarian-Reserve Assessment

A `Coordinator` or `Physician` opens a `Consultation` for a patient by supplying the `patient_id`, the `patient_age_years` (which must be at least 18), the `amh_level` (Anti-Müllerian Hormone in ng/mL, which must be at least 0), and the `antral_follicle_count` (the AFC ultrasound count, which must be at least 0). A new consultation starts in `REQUESTED` status with `expected_oocyte_yield` of 0, `eligibility_status` of `PENDING`, and `recommended_protocol` of `NONE`.

Only a `Physician` may complete a consultation, which is legal only while it is in `REQUESTED` status and drives it to `COMPLETED`. Completion computes three derived values from the consultation's inputs.

First, the **expected oocyte yield**. A base figure is formed by multiplying the `amh_level` by 2.0 and the `antral_follicle_count` by 0.5 and adding the two products together. That base is then scaled by an age multiplier determined by `patient_age_years`: 1.00 when the patient is under 35; 0.85 when the patient is at least 35 but under 38; 0.65 when the patient is at least 38 but under 41; and 0.40 when the patient is 41 or older. The scaled figure is floored to a whole number; the result is then clamped to be no less than 0 and no greater than an upper cap of 30. This clamped integer is written to `expected_oocyte_yield`.

Second, **eligibility**. The consultation is marked `ELIGIBLE` when the `amh_level` is at least 0.5 ng/mL, and `INELIGIBLE` otherwise; the result is written to `eligibility_status`.

Third, the **recommended protocol**, written to `recommended_protocol`. When the consultation is `INELIGIBLE`, the recommended protocol is `NONE`. When the consultation is `ELIGIBLE`, the protocol is selected from the `expected_oocyte_yield` by tier and is one of `ANTAGONIST`, `LONG_AGONIST`, or `MINIMAL_STIM` using these exact boundaries: an `expected_oocyte_yield` strictly below 5 yields `MINIMAL_STIM`; a yield from 5 through 14 inclusive yields `ANTAGONIST`; and a yield of 15 or greater yields `LONG_AGONIST`.

### 3.3. Cycle Creation and the Monitoring Calendar

A `Coordinator` creates a `StimulationCycle` by supplying the `patient_id` and the `consultation_id` of the completed, eligible consultation that authorizes it. A new cycle begins in `DRAFT` status with `protocol_type` `NONE`, a `monitoring_visit_count` of 0, and `estimated_cost_cents` and `final_cost_cents` of 0.

Scheduling the cycle, performed by a `Coordinator`, advances it from `DRAFT` to `SCHEDULED`. This is permitted only when the referenced consultation is in `COMPLETED` status and its `eligibility_status` is `ELIGIBLE`; if the consultation is not both completed and eligible, the request is rejected with `ERR_CONSULTATION_NOT_ELIGIBLE`. On scheduling, the cycle copies its `protocol_type` from the consultation's `recommended_protocol` and pins a provisional `estimated_cost_cents` via the cycle-cost estimate described below.

Once scheduled, the monitoring calendar is built by a `Coordinator` creating `MonitoringAppointment` records, each with a `cycle_id`, a `provider_id` (the monitoring physician), a `scheduled_start`, and a `scheduled_end` that must be strictly later than `scheduled_start`. Creating the **first** appointment for a cycle that is in `SCHEDULED` status advances the cycle from `SCHEDULED` to `MONITORING`; each appointment created (including the first) increments the cycle's `monitoring_visit_count`, and appointments after the first leave the cycle in `MONITORING`. A new appointment starts with `visit_status` `SCHEDULED`.

Provider availability is protected by a buffered overlap check: a new monitoring appointment is rejected with `ERR_PROVIDER_UNAVAILABLE` when it overlaps any existing non-cancelled appointment for the same provider once each existing appointment is padded by 15 minutes on each side. In other words, the new appointment must not fall within 15 minutes of another of that provider's appointments; the padded window is treated as strict (half-open), so a new appointment that begins exactly 15 minutes after an existing one ends — or ends exactly 15 minutes before an existing one begins — does not conflict.

A cycle may be suspended and resumed by a `Physician`. Suspension moves a cycle from `MONITORING` to `SUSPENDED`; while suspended, the cycle is frozen and any attempt to create a new monitoring appointment for it is rejected on the state check. Resumption moves it from `SUSPENDED` back to `MONITORING`, and a cycle may cycle between these two states any number of times.

### 3.4. Trigger, Retrieval, and the Cryopreservation Cascade

Once monitoring is sufficient, a `Physician` triggers the cycle, advancing it from `MONITORING` to `TRIGGERED`. Triggering requires that the cycle's `monitoring_visit_count` be at least 3; a cycle with fewer than three non-cancelled monitoring visits is rejected with `ERR_INSUFFICIENT_MONITORING_VISITS`. On success the server records `trigger_at` from the logical clock.

Retrieval, also performed by a `Physician`, advances the cycle from `TRIGGERED` to `COMPLETED` and is the system's most far-reaching operation. The physician supplies the `retrieval_room_id` of the booking room, the `retrieval_start` and `retrieval_end` of the procedure window, the `oocytes_retrieved` aspirated in total, the `mature_oocyte_count` to be cryopreserved, the `tank_id` of the target storage tank, and the `specimen_type` of either `VIAL` or `STRAW`. Because each vial or straw holds exactly one oocyte, the number of specimens created equals the `mature_oocyte_count`.

Two guards apply before anything is written. The room must be free: if the requested `[retrieval_start, retrieval_end)` window overlaps another retrieval already booked on the same room, treating the window as half-open with no buffer so that adjacent windows sharing only an endpoint do not conflict, the request is rejected with `ERR_ROOM_UNAVAILABLE`. The tank must have room: if the tank's current `used_slots` plus the number of specimens to be created would exceed the tank's `capacity_slots`, the request is rejected with `ERR_TANK_AT_CAPACITY`; storage is permitted exactly up to and including the tank's capacity.

When both guards pass, the retrieval records `retrieval_room_id`, `retrieval_start`, `retrieval_end`, `oocytes_retrieved`, and `mature_oocyte_count` on the cycle, and then cascades:

- It creates `mature_oocyte_count` `CryoSpecimen` rows in the target tank, each with the cycle's `patient_id`, the `cycle_id` of this retrieval, the `tank_id`, the chosen `specimen_type`, an `oocyte_count` of 1, and `status` `STORED`. Creating these specimens raises the tank's `used_slots`, and once `used_slots` reaches or exceeds `capacity_slots` the tank's `is_full` becomes true.
- If the patient has a `StorageSubscription`, its `specimen_count` increases by the newly created specimens and its `annual_fee_cents` is recomputed via the storage-renewal-fee rule (§3.5).
- The cycle's `final_cost_cents` is pinned via the cycle-cost final variant.

**Cycle cost.** The cost of a cycle depends on its `protocol_type`, which selects a medication fee: 300,000 cents for `ANTAGONIST`, 350,000 cents for `LONG_AGONIST`, and 150,000 cents for `MINIMAL_STIM`. The **estimate**, pinned at scheduling as `estimated_cost_cents`, is a forward-looking projection: an 800,000-cent base cycle fee, plus a monitoring allowance of five projected visits each at 25,000 cents (that is, 125,000 cents), plus the protocol's medication fee. It deliberately excludes any retrieval fee. The **final** figure, pinned at retrieval as `final_cost_cents`, uses the actuals: the same 800,000-cent base fee, plus the cycle's actual `monitoring_visit_count` multiplied by the 25,000-cent per-visit fee, plus the protocol's medication fee, plus a retrieval fee of 400,000 cents. Both figures are whole cents.

A `Coordinator` may cancel a cycle from any non-terminal state — that is, while it is `DRAFT`, `SCHEDULED`, `MONITORING`, or `SUSPENDED` — driving it to `CANCELLED`. Cancellation releases the estimated cost with no charge, and cascades to the monitoring calendar by setting the `visit_status` of every one of that cycle's still-`SCHEDULED` monitoring appointments to `CANCELLED` (appointments already cancelled are untouched).

### 3.5. Storage Subscription Lifecycle and Renewal Billing

A `BillingAdmin` opens a `StorageSubscription` for a patient by supplying the `patient_id`; it starts in `PENDING_ACTIVATION` with a `specimen_count` of 0 and an `annual_fee_cents` of 0. A patient may hold only one non-terminal subscription; an attempt to open a second while one is still active is rejected with `ERR_DUPLICATE_ACTIVE_RESOURCE`.

Recording a payment activates or renews the billing period. From `PENDING_ACTIVATION`, recording a payment moves the subscription to `ACTIVE`, sets `current_period_start` to the current clock, sets `current_period_end` to 365 days after the start, and sets `last_paid_at` to the current clock. From `PAST_DUE`, recording a payment is permitted only while the current clock is before `current_period_end` plus a 30-day grace window — once that grace window has elapsed, recording a payment is rejected with `ERR_INVALID_STATE`; while still within the window it returns the subscription to `ACTIVE`, advancing `current_period_start` to the previous `current_period_end`, extending `current_period_end` by a further 365 days, and setting `last_paid_at` to the current clock. A subscription may cycle between `ACTIVE` and `PAST_DUE` repeatedly across successive periods.

Renewal is the billing-cycle turnover. From `ACTIVE`, a renewal is permitted only once the period has elapsed — the current clock must be at or after `current_period_end`; renewing earlier is rejected with `ERR_PERIOD_NOT_ELAPSED`. A permitted renewal recomputes `annual_fee_cents` over the current `specimen_count` and moves the subscription to `PAST_DUE`, awaiting the renewal payment. From `PAST_DUE`, renewal is rejected with `ERR_INVALID_STATE` until the current clock has reached or passed `current_period_end` plus the 30-day grace window; once it has, renewal moves the subscription to `LAPSED` and cascades: every one of that patient's `CryoSpecimen` still in `STORED` status is set to `DISCARDED`, and each discarded specimen's tank has its `used_slots` decremented accordingly.

At any point while `ACTIVE` or `PAST_DUE`, a `BillingAdmin` may cancel the subscription, driving it to `CANCELLED`; billing stops and the specimens are retained under the patient's ownership. `LAPSED` and `CANCELLED` are terminal.

**Storage renewal fee.** The annual fee is computed per specimen and then summed, in that pinned order. Each specimen's net annual fee is the base annual rate of 4,000 cents per specimen reduced by a loyalty discount of 3.33 percent (a factor of 0.0333), with that single per-specimen figure rounded half-up to a whole cent first. The subscription's `annual_fee_cents` is then that rounded per-specimen fee multiplied by the `specimen_count`. Rounding the per-specimen fee before multiplying is deliberate and can differ by a few cents from rounding a single count-times-rate product; the per-specimen order is the pinned one.

### 3.6. Consent and Disposition Directives

Directives are the compliance backbone that governs what may be done with a patient's frozen oocytes, and only a `Patient` may author or revoke them. Creating a `Directive` requires the `patient_id`, a `directive_type` of either `CONSENT` or `DISPOSITION`, and — required only when the type is `DISPOSITION` — a `disposition_action` of `THAW_TO_SELF`, `DONATE_TO_RESEARCH`, `DISCARD`, or `TRANSFER_TO_PARTNER`. A create also carries `expected_patient_version` for the concurrency check described in §2.8. A new directive is recorded in `ACTIVE` status with `signed_at` taken from the logical clock.

Creating a new directive of a given type supersedes the patient's prior active directive of that same type: the prior directive's `status` becomes `SUPERSEDED`, the new one becomes the active directive of that type, and the patient's `version` is incremented by one as part of the create. A patient may also revoke one of their own active directives, moving it from `ACTIVE` to `REVOKED`; revocation is permitted only while the directive is `ACTIVE` and only when the acting patient owns it (their `X-User-ID` equals the directive's `patient_id`). Both `SUPERSEDED` and `REVOKED` are terminal.

### 3.7. Thaw and Transfer Authorization

Removing oocytes from storage is a segregation-of-duties workflow that spans two physicians and an embryologist. A `Physician` opens a `ThawTransferAuthorization` by supplying the `patient_id`, a `specimen_ids` array listing the `CryoSpecimen` identifiers to be reserved and thawed (this is a list, not a single reference), and a `transfer_type` of `THAW_TO_TRANSFER`, `TRANSFER_OUT`, or `RESEARCH_DONATION`. The server records the requesting physician's `X-User-ID` as `requester_provider_id`, and the authorization starts in `REQUESTED` status.

Authorization is performed by a **different** `Physician`, moving the authorization from `REQUESTED` to `AUTHORIZED`, and enforces a layered set of safety checks evaluated in this fixed order. The patient must have an active consent on file: absent an `ACTIVE` `CONSENT` directive, the request is rejected with `ERR_CONSENT_NOT_ACTIVE`. The patient must likewise have an `ACTIVE` `DISPOSITION` directive, absent which the request is rejected with `ERR_DISPOSITION_NOT_ACTIVE`. Only after both directive checks pass is segregation of duties enforced: the acting physician's `X-User-ID` must differ from the `requester_provider_id`; if the same physician who requested attempts to authorize, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Every specimen named in `specimen_ids` must belong to the authorization's patient — otherwise `ERR_SPECIMEN_NOT_OWNED` — and each must currently be in `STORED` status; a specimen not in the required state is rejected with `ERR_SPECIMEN_NOT_AVAILABLE`. On success the server pins the active consent directive as `consent_directive_id` and the active disposition directive as `disposition_directive_id`, records the acting physician as `authorizer_provider_id`, and cascades each referenced `CryoSpecimen` from `STORED` to `RESERVED`. A reserved specimen continues to occupy its tank slot, so `used_slots` does not change on reservation.

Alternatively, the authorizing `Physician` may deny a requested authorization, moving it from `REQUESTED` to `DENIED`; denial is a divergent branch that reserves nothing and produces no specimen state change.

Execution is performed by an `Embryologist`, moving the authorization from `AUTHORIZED` to `EXECUTED`. Every referenced `CryoSpecimen` must currently be in `RESERVED` status — otherwise the execution is rejected with `ERR_SPECIMEN_NOT_AVAILABLE` — and execution cascades each referenced specimen from `RESERVED` to `THAWED`, decrementing its tank's `used_slots`, decrementing the patient's `StorageSubscription.specimen_count`, and recomputing that subscription's storage renewal fee. `EXECUTED` and `DENIED` are terminal.

Beyond the two paths above, a `CryoSpecimen` in `STORED` status may also reach `DISCARDED` through the subscription-lapse cascade of §3.5 or a disposition directive whose action is `DISCARD`; discarding frees the tank slot by decrementing `used_slots`.

### 3.8. Invoicing, Facility Fees, and Employer Benefit Coverage

Employer benefit coverage is set up by a `BillingAdmin` creating a `BenefitCoverage` with the `patient_id`, the sponsoring `employer_name`, an `annual_cap_cents` (at least 0), a `covered_pct` fraction between 0 and 1 inclusive, and a `covered_service_types` array — a subset of `CYCLE`, `STORAGE`, `RETRIEVAL`, and `THAW` eligible for coverage. On creation, `consumed_cents` is 0 and `remaining_cents` equals `annual_cap_cents`; the coverage starts `ACTIVE`. A patient may hold only one active coverage; a second is rejected with `ERR_DUPLICATE_ACTIVE_RESOURCE`.

Invoices are created by a `BillingAdmin` supplying the `patient_id`, a `service_type` of `CYCLE`, `STORAGE`, `RETRIEVAL`, or `THAW`, and a `line_items` array whose entries each carry a `description` and a non-negative `amount_cents`. A new invoice starts in `DRAFT` status.

**Invoice total.** The invoice figures are computed in a pinned order. First, `subtotal_cents` is the sum of the `amount_cents` across all `line_items`. Second, a facility percentage is selected by tier on that subtotal: 0.05 when the subtotal is below 500,000 cents; 0.03 when the subtotal is at least 500,000 but below 1,500,000 cents; and 0.02 when the subtotal is at least 1,500,000 cents. Third, `facility_fee_cents` is the subtotal multiplied by that percentage, rounded half-up to a whole cent. Fourth, benefit coverage is resolved (below). Last, the amount due is the subtotal plus the facility fee minus the applicable coverage.

**Benefit coverage applied.** Coverage is resolved against the patient's `ACTIVE` `BenefitCoverage` (if more than one somehow exists, the one with the earliest `created_at`). The eligible base is the invoice `subtotal_cents` when the invoice's `service_type` is among the coverage's `covered_service_types`, and 0 otherwise. A raw coverage figure is the coverage's `covered_pct` multiplied by that eligible base, rounded half-up to a whole cent. The applied coverage is the smaller of that raw figure and the coverage's `remaining_cents`, so coverage is capped at the remaining cap rather than causing a rejection. This resolution runs in two variants. At draft creation it is the **provisional** variant, reading `remaining_cents` as it stands at draft time and stored as `estimated_coverage_cents`; the draft's `total_due_cents` uses this provisional figure. At finalize it is the **final** variant, re-reading `remaining_cents` after any intervening finalized or voided invoices and stored as `settled_coverage_cents`; because the cap may have moved in between, the settled figure can diverge from the provisional one, and the finalized `total_due_cents` uses the settled figure.

Finalizing an invoice, by a `BillingAdmin`, moves it from `DRAFT` to `FINALIZED`. Finalization recomputes `subtotal_cents`, `facility_fee_cents`, the final `settled_coverage_cents`, and `total_due_cents`, and then cascades to the benefit ledger: the coverage's `consumed_cents` increases by the settled coverage, `remaining_cents` is recomputed, and the coverage flips to `EXHAUSTED` when `remaining_cents` reaches 0. Because coverage is capped at `remaining_cents`, finalizing never drives the cap negative.

Voiding a finalized invoice, again by a `BillingAdmin`, moves it from `FINALIZED` to `VOID` and compensates the ledger: the coverage's `consumed_cents` decreases by that invoice's `settled_coverage_cents`, `remaining_cents` is restored, and a coverage that had been `EXHAUSTED` returns to `ACTIVE` once its `remaining_cents` is greater than 0. Across finalize and void alike, the invariant that `consumed_cents` plus `remaining_cents` equals `annual_cap_cents` is preserved.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. In the table below, "All roles" denotes every one of the six recognized roles (`Patient`, `Coordinator`, `Physician`, `Embryologist`, `BillingAdmin`, `PlatformAdmin`).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patients` | Create a patient | Coordinator, BillingAdmin |
| GET | `/patients/{id}` | Get a patient | All roles |
| POST | `/providers` | Create a clinical provider | PlatformAdmin |
| POST | `/procedure-rooms` | Create a procedure/retrieval room | PlatformAdmin |
| POST | `/storage-tanks` | Create a cryo storage tank | Embryologist, PlatformAdmin |
| GET | `/storage-tanks/{id}` | Get a tank (observe used_slots/is_full) | Coordinator, Physician, Embryologist, BillingAdmin, PlatformAdmin |
| POST | `/consultations` | Create a consultation with ovarian-reserve inputs | Coordinator, Physician |
| GET | `/consultations/{id}` | Get a consultation | All roles |
| GET | `/consultations` | List consultations | All roles |
| POST | `/consultations/{id}/complete` | Complete consult; compute yield, eligibility, protocol | Physician |
| POST | `/stimulation-cycles` | Create a cycle (DRAFT) | Coordinator |
| GET | `/stimulation-cycles/{id}` | Get a cycle | All roles |
| GET | `/stimulation-cycles` | List cycles | All roles |
| POST | `/stimulation-cycles/{id}/schedule` | DRAFT to SCHEDULED (requires eligible consult) | Coordinator |
| POST | `/stimulation-cycles/{id}/suspend` | MONITORING to SUSPENDED | Physician |
| POST | `/stimulation-cycles/{id}/resume` | SUSPENDED to MONITORING | Physician |
| POST | `/stimulation-cycles/{id}/trigger` | MONITORING to TRIGGERED | Physician |
| POST | `/stimulation-cycles/{id}/retrieve` | TRIGGERED to COMPLETED; retrieve and cryopreserve | Physician |
| POST | `/stimulation-cycles/{id}/cancel` | Cancel a cycle | Coordinator |
| POST | `/monitoring-appointments` | Create a monitoring appointment | Coordinator |
| GET | `/monitoring-appointments/{id}` | Get an appointment | All roles |
| GET | `/monitoring-appointments` | List appointments | All roles |
| GET | `/cryo-specimens/{id}` | Get a specimen | All roles |
| GET | `/cryo-specimens` | List specimens | All roles |
| POST | `/storage-subscriptions` | Create a subscription (PENDING_ACTIVATION) | BillingAdmin |
| GET | `/storage-subscriptions/{id}` | Get a subscription | All roles |
| GET | `/storage-subscriptions` | List subscriptions | All roles |
| POST | `/storage-subscriptions/{id}/record-payment` | Activate or renew billing period | BillingAdmin |
| POST | `/storage-subscriptions/{id}/renew` | ACTIVE to PAST_DUE, or PAST_DUE to LAPSED | BillingAdmin |
| POST | `/storage-subscriptions/{id}/cancel` | ACTIVE/PAST_DUE to CANCELLED | BillingAdmin |
| POST | `/benefit-coverages` | Create employer benefit coverage | BillingAdmin |
| GET | `/benefit-coverages/{id}` | Get a coverage | All roles |
| GET | `/benefit-coverages` | List coverages | All roles |
| POST | `/directives` | Create a consent/disposition directive | Patient |
| GET | `/directives/{id}` | Get a directive | All roles |
| GET | `/directives` | List directives | All roles |
| POST | `/directives/{id}/revoke` | ACTIVE to REVOKED (owner only) | Patient |
| POST | `/thaw-transfer-authorizations` | Request a thaw/transfer | Physician |
| GET | `/thaw-transfer-authorizations/{id}` | Get an authorization | All roles |
| GET | `/thaw-transfer-authorizations` | List authorizations | All roles |
| POST | `/thaw-transfer-authorizations/{id}/authorize` | REQUESTED to AUTHORIZED (reserve specimens) | Physician |
| POST | `/thaw-transfer-authorizations/{id}/execute` | AUTHORIZED to EXECUTED (thaw cascade) | Embryologist |
| POST | `/thaw-transfer-authorizations/{id}/deny` | REQUESTED to DENIED | Physician |
| POST | `/invoices` | Create an invoice draft | BillingAdmin |
| GET | `/invoices/{id}` | Get an invoice | All roles |
| GET | `/invoices` | List invoices | All roles |
| POST | `/invoices/{id}/finalize` | DRAFT to FINALIZED (settle benefit, consume cap) | BillingAdmin |
| POST | `/invoices/{id}/void` | FINALIZED to VOID (restore benefit cap) | BillingAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CONSULTATION_NOT_ELIGIBLE` | 422 |
| `ERR_CONSENT_NOT_ACTIVE` | 422 |
| `ERR_DISPOSITION_NOT_ACTIVE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_SPECIMEN_NOT_OWNED` | 422 |
| `ERR_SPECIMEN_NOT_AVAILABLE` | 409 |
| `ERR_PROVIDER_UNAVAILABLE` | 409 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_INSUFFICIENT_MONITORING_VISITS` | 422 |
| `ERR_TANK_AT_CAPACITY` | 409 |
| `ERR_DUPLICATE_ACTIVE_RESOURCE` | 409 |
| `ERR_PERIOD_NOT_ELAPSED` | 409 |
