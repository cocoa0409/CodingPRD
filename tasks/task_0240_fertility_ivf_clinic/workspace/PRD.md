# Fertility IVF Clinic API — Product Requirements Document

## 1. Introduction

A fertility clinic runs a patient's IVF journey as a tightly choreographed pipeline: a stimulation protocol leading to oocyte retrieval, fertilization in the lab, then either a fresh embryo transfer or a freeze-all decision, all the while accruing medication charges, monitoring visits, frozen-specimen storage, and an insurance settlement at the end. This API exists to coordinate that pipeline deterministically, so that clinical staff, embryologists, and billing specialists each operate on a single shared source of truth rather than on scattered spreadsheets.

The system is unusual in that a single treatment cycle carries **two independent status dimensions that evolve separately** — a clinical protocol axis and a financial billing axis — and that money is computed twice with deliberately different rules: a forward-looking insurance estimate while the cycle is still in flight, and a chronological true-up at settlement that bills only what actually happened. Layered on top are safety-critical concerns: a patient may not advance through a clinical gate without an active, version-pinned consent on file; frozen specimens consume scarce physical tank capacity that must never be oversubscribed; and monitoring appointments compete for a shared clinic room-capacity pool over time. Because several of these resources are mutated by more than one actor, the system uses a deterministic logical clock and optimistic concurrency control to keep operations reproducible and free of lost updates.

This document specifies the complete contract: the resource model, the two-axis cycle state machine and its sibling lifecycles, every calculation, every validation and its error, the endpoint surface, and the role-based access rules that bind it all together.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Every resource collection lives under a clinic: the clinic itself is addressed at the top level, and every other entity is a flat collection one level beneath the clinic. Cross-entity scoping — which cycle, patient, or tank a child record belongs to — is carried in request bodies and surfaced through filtered-list query parameters, never through deeper URL nesting.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. The system recognizes exactly five roles: `ClinicAdmin`, `Nurse`, `Embryologist`, `BillingSpecialist`, and `Patient`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT`. If the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Four of the five roles are operator roles whose identity is opaque. When `X-User-Role` is `ClinicAdmin`, `Nurse`, `Embryologist`, or `BillingSpecialist`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. `ClinicAdmin` configures clinic-level reference data — insurance packages, consent forms, cryo tanks, donor and surrogate profiles, and patient records. `Nurse` drives the clinical protocol, the medication calendar, the monitoring schedule, and outcome reporting. `Embryologist` owns the laboratory transitions (fertilization, transfer, freeze) and the entire cryo specimen inventory. `BillingSpecialist` owns the cycle's billing axis: insurance estimate, settlement, and write-off.

The `Patient` role is different: it is entity-backed. When `X-User-Role` is `Patient`, the `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's patient foreign key to `X-User-ID`. In particular, a patient signs and revokes only their own consents — the `patient_id` involved must equal the caller's `X-User-ID` — and reads only records scoped to themselves.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource carries a system-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC value with three fractional digits. Most resources are mutable and additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every change) and an integer `version` that begins at its initial value and increments by one on every mutation. The mutable resources are the `Clinic`, `InsurancePackage`, `Patient`, `DonorProfile`, `SurrogateProfile`, `ConsentForm`, `PatientConsent`, `CryoTank`, `TreatmentCycle`, `MedicationOrder`, `MonitoringAppointment`, `CryoSpecimen`, `CycleInvoice`, and `OutcomeReport`.

When the system computes or refreshes a derived field on a resource — for example, recomputing a tank's free-slot views or stamping a cycle's settlement figures — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. The Deterministic Clinic Clock

Every clinic maintains a deterministic logical clock, exposed as `current_clock_utc`, which is initialized to `1970-01-01T00:00:00.000Z` when the clinic is created. **All temporal validations read this clock and never the server wall-clock.** The clock advances only through an administrative test-driving capability that sets a clinic's `current_clock_utc` to a supplied instant; that endpoint accepts the target `clinic_id` and the new timestamp `to_iso8601`. The clock is monotonic non-decreasing: an attempt to set it to a timestamp earlier than the clinic's current `current_clock_utc` is rejected with `ERR_CLOCK_NOT_MONOTONIC`. The clock is the basis for appointment interval validation, appointment completion and no-show timing, the cycle stim-start reference for the medication calendar, the `signed_at` stamp on consents, and the `storage_start_utc` stamp on stored specimens.

### 2.6. Nested Resource Retrieval and Existence Ordering

The API enforces a strict left-to-right existence protocol for every request. The clinic identifier in the path is validated first; if it does not correspond to an existing clinic the request is rejected immediately with `ERR_CLINIC_NOT_FOUND`. Only then is the second path identifier resolved — the patient, cycle, appointment, specimen, tank, consent form, package, donor, surrogate, invoice, or outcome — each yielding its own not-found error (`ERR_PATIENT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_CONSENT_FORM_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`, `ERR_SURROGATE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_OUTCOME_NOT_FOUND`) all carrying HTTP 404. Beyond path identifiers, any foreign-key field carried in a request body must reference an existing in-clinic resource: `insurance_package_id`, `donor_profile_id`, `surrogate_profile_id`, `consent_form_id`, and `cryo_tank_id` are each resolved this way, and a dangling reference yields the corresponding not-found error.

The overall ordering of checks on any mutation is fixed. Authentication context (`ERR_MISSING_AUTH_CONTEXT`) is evaluated first, then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of all path-referenced resources, then existence of body foreign keys, then payload well-formedness (`ERR_VALIDATION` — missing required fields, wrong types, invalid enum members, or out-of-domain integers such as negative counts or an end value below its start). Only after these structural checks does the system evaluate the optimistic-concurrency version match (where applicable), then the state-machine precondition that the target resource is in a state from which the requested transition is defined, and finally the business-referential and business-safety rules described in §3.

### 2.7. Optimistic Concurrency Control

Two operations in the system mutate a parent aggregate whose version may have advanced between the moment a client read it and the moment the client acts, and both are guarded by optimistic concurrency control. In each case the version check runs before any business logic.

The first is **storing a cryo specimen into a tank**. The store request must carry `expected_tank_version`, a non-optional field holding the client's last observed `version` of the target `CryoTank`. If that value does not equal the tank's current `version`, the store is rejected with `ERR_STALE_TANK_VERSION` (HTTP 412). This captures the situation where another writer has already stored a specimen into the same tank — legitimately consuming a slot and advancing the tank's version — so the current writer's view of remaining capacity is stale and the slot it intends to read may no longer be free.

The second is **settling a treatment cycle**. The settle request must carry `expected_cycle_version`, a non-optional field holding the client's last observed `version` of the target `TreatmentCycle`. If that value does not equal the cycle's current `version`, the settlement is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). This captures the situation where a cancellation has landed between the client's read and the settle call — cancellation recomputes the cancellation fee and cascades across child records, advancing the cycle version — so a settlement computed against the client's stale charge basis would be wrong. Cancelling a cycle likewise requires `expected_cycle_version` to equal the cycle's current `version`, rejecting a mismatch with `ERR_STALE_CYCLE_VERSION`. No other endpoint accepts a version field.

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Where a calculation multiplies a covered amount by a coverage fraction, the result is rounded **half up** to a whole number of cents. The rounding is applied once, to the summed covered total — never per line item. The lifetime coverage cap, where it applies, is enforced after that rounding. Medication line totals and cancellation fees are products and table lookups over integer inputs and are therefore exact, requiring no rounding. The embryo utilization rate is the one non-monetary computed figure: it is a fraction rounded half up to four decimal places, as described in §3.8.

### 2.9. Hierarchical Consistency and Cascades

Several operations mutate more than one resource. When this happens, every secondary effect is part of the same operation and must be applied together. The most significant cascade is cycle cancellation, which fans out across the cycle's medication orders, monitoring appointments, and frozen specimens, and through the specimens reaches into the separate cryo-tank aggregate; this is detailed in §3.2. Publishing a consent form that supersedes a prior version triggers a two-hop cascade into that prior form and into the patient consents pinned to it; this is detailed in §3.5. Cross-aggregate slot accounting on a tank, and the donor reservation lifecycle, are likewise driven entirely by actions on cycles and specimens rather than by direct edits. In every cascade, each resource the system mutates has its `updated_at` refreshed and, where it carries one, its `version` incremented.

## 3. Business Logic & Workflows

### 3.1. Clinic Configuration: Packages, Consent Forms, Tanks, Donors, and Surrogates

Before any treatment can begin, a `ClinicAdmin` establishes the clinic and its reference data. A clinic is created with a `name`, an optional `timezone` (an informational IANA label defaulting to `UTC`), and an optional `room_concurrency_limit` — a positive integer that defaults to 2 and that pins the maximum aggregate room-capacity weight of concurrent monitoring appointments the clinic will tolerate at any instant.

**Insurance packages** define the financial bundle a patient bills against. A package is created with a `name`, a `base_price_cents` (the non-negative list price of the cycle bundle), a `coverage_pct` (the insurance coverage fraction between 0.00 and 1.00 applied to covered line items), and a `lifetime_coverage_cap_cents` (the non-negative maximum cumulative insurer-paid amount across all cycles billing against this package). Three optional fields tune coverage: `stim_med_covered` (whether stimulation medication is insurance-covered, defaulting to true), `cryo_storage_covered` (whether annual cryo storage is covered, defaulting to false), and `annual_cryo_storage_cents` (the non-negative annual storage fee per specimen-year, defaulting to 60000 cents — that is, 600 dollars per specimen per year). A package begins `ACTIVE` and may be retired by a `ClinicAdmin` to `RETIRED`; a retired package rejects assignment to any new cycle.

**Consent forms** are versioned safety artifacts. A form is created in `DRAFT` with a `form_key` (a stable logical key such as `IVF_GENERAL`, `CRYO_STORAGE`, or `DONOR_GAMETE`, shared across versions), a `version_label` (a human label such as `v2024.1`), a `required_for` array enumerating which protocol gates the form gates (members drawn from `CYCLE_START`, `RETRIEVAL`, `TRANSFER`, and `CRYO_STORE`), and an optional `supersedes_form_id` naming the prior published version this one replaces. Only a `ClinicAdmin` publishes a form; publishing is covered in §3.5.

**Cryo tanks** are physical storage units. A tank is created by a `ClinicAdmin` or an `Embryologist` with a `label` (unique within the clinic) and a `capacity_slots` (a positive integer total canister count). It begins `ONLINE` with `reserved_slots` at 0, and either role may set it to `MAINTENANCE`; a tank in `MAINTENANCE` rejects new stores but retains its existing specimens. Each tank also exposes two derived free-slot views, `committed_free_slots` and `projected_free_slots`, described in §3.7.

**Donor profiles** carry an anonymized `code` (unique within the clinic) and a `donor_type` of either `EGG` or `SPERM`; they begin `AVAILABLE`. **Surrogate profiles** carry a `full_name` and begin `AVAILABLE`. Both are linked into cycles at creation, as described in §3.2.

Every one of these reference records also carries a `clinic_id` foreign key tying it to its owning clinic. Patients are registered by a `ClinicAdmin` or a `Nurse` with a `full_name`, a `date_of_birth` (an ISO date used for age-based eligibility), and an optional `insurance_package_id` naming the package the patient bills against; a patient begins `ACTIVE` and may be deactivated by a `ClinicAdmin` to `INACTIVE`.

### 3.2. The Treatment Cycle: Protocol Axis, Linkage, and Cancellation

A `Nurse` opens a **treatment cycle** for a patient by supplying the `patient_id` and, optionally, a `donor_profile_id` and a `surrogate_profile_id`. The cycle begins with its protocol axis, `protocol_status`, at `DRAFT` and its billing axis, `billing_status`, at `UNBILLED`; these two axes evolve independently of one another over the life of the same cycle row. At creation the cycle snapshots `insurance_package_id` from the patient's own `insurance_package_id`, so later changes to the patient do not retroactively alter the cycle's billing basis. A cycle may not be created against an `INACTIVE` patient (`ERR_PATIENT_INACTIVE`) nor against a `RETIRED` insurance package (`ERR_PACKAGE_RETIRED`). If a `donor_profile_id` is supplied, that donor must be `AVAILABLE` (`ERR_DONOR_NOT_AVAILABLE`); on success the donor moves `AVAILABLE → RESERVED`. If a `surrogate_profile_id` is supplied, the surrogate moves `AVAILABLE → MATCHED`.

The protocol axis advances through a defined pipeline, each step driven by a role-specific action. A `Nurse` begins stimulation, advancing `DRAFT → STIM`; this requires the cycle to currently be `DRAFT` (`ERR_CYCLE_BAD_PROTOCOL_STATE`), the patient to be `ACTIVE` (`ERR_PATIENT_INACTIVE`), and an active consent covering the `CYCLE_START` gate (see §3.6, `ERR_CONSENT_MISSING`). On success the system stamps the cycle's stim-start at the clinic's `current_clock_utc`, fixing the day-offset-zero reference for the medication calendar.

Recording **oocyte retrieval** advances `STIM → RETRIEVAL`; it requires the cycle to be `STIM` (`ERR_CYCLE_BAD_PROTOCOL_STATE`), an active consent covering the `RETRIEVAL` gate (`ERR_CONSENT_MISSING`), and an `oocytes_retrieved` count in the request that is an integer of at least zero (`ERR_VALIDATION`); that value is written onto the cycle. A `Nurse` may **revert a retrieval back to stimulation**, moving `RETRIEVAL → STIM`; this requires the cycle to be `RETRIEVAL` (`ERR_CYCLE_BAD_PROTOCOL_STATE`) and resets `oocytes_retrieved` to 0.

Recording **fertilization** is an `Embryologist` action advancing `RETRIEVAL → FERTILIZATION`; it requires the cycle to be `RETRIEVAL` (`ERR_CYCLE_BAD_PROTOCOL_STATE`) and an `embryos_fertilized` count in the request that is an integer at least zero and no greater than the recorded `oocytes_retrieved` (`ERR_EMBRYO_COUNT_EXCEEDS_OOCYTES`); that value is written onto the cycle. If a donor was linked to this cycle, reaching fertilization moves that donor `RESERVED → CONSUMED`.

From `FERTILIZATION` the pipeline **forks**, and the two branches diverge. An `Embryologist` may perform a **fresh transfer**, advancing `FERTILIZATION → FRESH_TRANSFER`; this branch consumes an embryo into transfer and auto-creates no cryo specimen. Alternatively an `Embryologist` may elect **freeze-all**, advancing `FERTILIZATION → FREEZE_ALL`; this branch creates no specimen automatically either — instead the caller subsequently records specimen rows for freezing, as in §3.7. Both branches require the cycle to be `FERTILIZATION` (`ERR_CYCLE_BAD_PROTOCOL_STATE`) and require at least one embryo fertilized — that is, `embryos_fertilized` of at least 1 (`ERR_NO_EMBRYOS_AVAILABLE`). In addition, the fresh-transfer branch requires an active consent covering the `TRANSFER` gate (`ERR_CONSENT_MISSING`); the freeze-all branch carries no such consent gate.

A `Nurse` **completes** a cycle, advancing it to `COMPLETED` from either `FRESH_TRANSFER` or `FREEZE_ALL`; completion requires the cycle to be in one of those two states (`ERR_CYCLE_BAD_PROTOCOL_STATE`) and requires that an outcome report already exists for the cycle (`ERR_OUTCOME_REQUIRED`). `COMPLETED` is terminal on the protocol axis.

**Cancellation.** A `Nurse` may cancel a cycle from any non-terminal protocol state — that is, when `protocol_status` is anything other than `COMPLETED` or `CANCELLED` (`ERR_CYCLE_BAD_PROTOCOL_STATE`) — and the cancel request must carry `expected_cycle_version` matching the cycle's current `version` (`ERR_STALE_CYCLE_VERSION`). Cancellation sets `protocol_status` to `CANCELLED`, computes `cancellation_fee_cents` (see §3.9), and increments the cycle's `version` by one. It then cascades. As a first-level cascade, every medication order of the cycle still in `SCHEDULED` moves to `CANCELLED`; every monitoring appointment still in `CONFIRMED` or `RESCHEDULED` moves to `CANCELLED`, freeing its room-capacity window; and every specimen of the cycle still `PENDING` or `STORED` moves to `DISCARDED`. The specimen step reaches further: each specimen that was `STORED` at cancellation, on moving to `DISCARDED`, decrements its tank's `reserved_slots` by 1 (a second-level cascade into the separate tank aggregate), and that change to `reserved_slots` in turn forces the tank's `committed_free_slots` and `projected_free_slots` to be recomputed (a third-level cascade). Finally, if the cycle had a donor that was `RESERVED` but not yet `CONSUMED`, the donor is released back to the pool, moving `RESERVED → AVAILABLE`. `CANCELLED` is terminal on the protocol axis.

### 3.3. The Medication Calendar

Within a cycle, a `Nurse` builds a **medication calendar** by adding medication orders. Each order names the parent cycle via `treatment_cycle_id` and carries a `drug_name`, a `start_day_offset` and `end_day_offset` (inclusive integer day offsets from the cycle's stim-start, where the start is at least 0 and the end is at least the start), a `daily_dose_units` (a positive integer), and a `unit_price_cents` (a non-negative per-unit cost). An order is created in `SCHEDULED`.

At creation the system computes the order's `line_total_cents`: the number of days the order spans, multiplied by `daily_dose_units`, multiplied by `unit_price_cents`. The number of days is the inclusive span of the offset range — the end offset minus the start offset, plus one — so an order from offset 3 through offset 5 spans three days. This line total is frozen at creation and does not change afterward.

The calendar forbids double-booking the same drug. A new order's day-offset interval is treated as a closed inclusive interval from `start_day_offset` through `end_day_offset`, and it must not intersect the closed interval of any existing order for the **same** `drug_name` on the same cycle that is currently `SCHEDULED` or `ADMINISTERED`. Closed-interval semantics govern the boundaries: two orders whose ranges merely abut — where the earlier order's end offset plus one equals the later order's start offset — do not overlap and are both allowed, but ranges that share even a single offset (including equal endpoints) do overlap. A violation is rejected with `ERR_MEDICATION_SCHEDULE_OVERLAP`.

A `Nurse` marks an order **administered**, moving `SCHEDULED → ADMINISTERED`, which requires the order to be `SCHEDULED` (`ERR_MED_BAD_STATE`); once administered, the order joins the chronological settlement medication set. A `Nurse` may instead **cancel** a scheduled order, moving `SCHEDULED → CANCELLED`, which likewise requires the order to be `SCHEDULED` (`ERR_MED_BAD_STATE`); a cancelled order is excluded from the settlement medication set, though if an estimate already ran it would still have been counted there. `ADMINISTERED` and `CANCELLED` are terminal. An order's lifecycle position is reflected in its `status` field, which list reads may filter on.

### 3.4. Monitoring Appointments and the Shared Room Pool

A `Nurse` schedules a **monitoring appointment** against a cycle by supplying the `treatment_cycle_id`, an `appointment_type` of `BLOODWORK`, `ULTRASOUND`, or `CONSULT`, a `start_utc`, an `end_utc`, and an optional `room_capacity_weight` (a positive integer count of concurrent-capacity units the visit consumes from the clinic's shared monitoring-room pool, defaulting to 1). The appointment occupies the half-open interval from `start_utc` (inclusive) to `end_utc` (exclusive). At creation the system snapshots the appointment's `clinic_id` from the cycle's clinic, because the appointment competes for clinic-wide room capacity rather than cycle-local capacity, and the appointment begins `CONFIRMED`.

The interval must be valid: `end_utc` must be strictly after `start_utc`, and `start_utc` must be at or after the clinic's `current_clock_utc`; either violation is rejected with `ERR_APPOINTMENT_IN_PAST`. Beyond validity, the appointment must not oversubscribe the room pool. Considering all non-terminal appointments in the same clinic — those in `CONFIRMED` or `RESCHEDULED` — the instantaneous sum of `room_capacity_weight` across appointments whose half-open intervals cover any given instant must never exceed the clinic's `room_concurrency_limit`; if admitting the new interval would push that instantaneous aggregate above the limit at any point, the request is rejected with `ERR_MONITORING_SLOT_CONFLICT`. Because the intervals are half-open, two appointments that merely abut — where the earlier one's `end_utc` exactly equals the later one's `start_utc` — do not overlap and may share the boundary instant freely.

An appointment's lifecycle is cyclic. A `Nurse` may **reschedule** a `CONFIRMED` or `RESCHEDULED` appointment to a new interval, moving it to `RESCHEDULED`; rescheduling requires the appointment to be in `CONFIRMED` or `RESCHEDULED` (`ERR_APPT_BAD_STATE`), updates its `start_utc` and `end_utc`, and re-applies both the interval-validity rule (`ERR_APPOINTMENT_IN_PAST`) and the room-overlap rule (`ERR_MONITORING_SLOT_CONFLICT`) — except that the appointment being rescheduled is excluded from its own conflict set. From `RESCHEDULED`, a `Nurse` **confirms** the appointment back to `CONFIRMED`; confirmation requires the appointment to be `RESCHEDULED` (`ERR_APPT_BAD_STATE`). A `Nurse` **completes** an appointment, moving it to `COMPLETED`, which requires it to be `CONFIRMED` or `RESCHEDULED` (`ERR_APPT_BAD_STATE`) and requires that the clinic's `current_clock_utc` be at or after the appointment's `start_utc` (`ERR_APPOINTMENT_NOT_STARTED`). A `Nurse` marks an appointment a **no-show**, moving it to `NO_SHOW`, which requires it to be `CONFIRMED` or `RESCHEDULED` (`ERR_APPT_BAD_STATE`) and requires the clinic's `current_clock_utc` to be at or after the appointment's `end_utc` (`ERR_APPOINTMENT_NOT_ENDED`). A `Nurse` may **cancel** an appointment from `CONFIRMED` or `RESCHEDULED` (`ERR_APPT_BAD_STATE`), moving it to `CANCELLED`. Reaching `COMPLETED`, `NO_SHOW`, or `CANCELLED` — all terminal — frees the appointment's room-capacity window, so its weight no longer counts toward the concurrency limit.

### 3.5. Consent Forms, Signing, and Version Pinning

A `ClinicAdmin` **publishes** a draft consent form, advancing it `DRAFT → PUBLISHED`; this requires the form to currently be `DRAFT` (`ERR_CONSENT_FORM_BAD_STATE`). If the form names a `supersedes_form_id`, that target form must exist and be `PUBLISHED` at publish time (`ERR_SUPERSEDE_TARGET_NOT_PUBLISHED`). Only a `PUBLISHED` form can be signed. Publishing with a supersede target triggers a two-hop cascade: the named target form moves `PUBLISHED → SUPERSEDED` (a first-level cascade), and then every active patient consent that was pinned to that now-superseded form moves `ACTIVE → STALE` (a second-level cascade). `SUPERSEDED` is terminal for a form.

A consent is signed through the patient-consent record. A `Patient` (or a `Nurse` acting on the patient's behalf) signs a published form by supplying the `patient_id` and the `consent_form_id`. The form must be `PUBLISHED` and non-stale at signing; attempting to sign a `DRAFT` or `SUPERSEDED` form is rejected with `ERR_CONSENT_FORM_NOT_PUBLISHED`. When the caller is a `Patient`, the supplied `patient_id` must equal the caller's `X-User-ID`. On a successful signature the consent is created `ACTIVE`, the system records `signed_at` as the clinic's `current_clock_utc`, snapshots the form's current `version` into `pinned_form_version`, and records `pinned_form_status_at_sign` as `PUBLISHED` (the only status under which a signature succeeds). The pinned version is what later lets the system detect a stale signature: when the signed form is subsequently superseded, the consent transitions to `STALE` as described above.

A `Patient` may **revoke** their own active consent, moving it `ACTIVE → REVOKED`; this requires the consent to be `ACTIVE` (`ERR_CONSENT_BAD_STATE`), and the consent's `patient_id` must equal the caller's `X-User-ID`. Both `REVOKED` and `STALE` are terminal consent states.

### 3.6. Consent Gating of Clinical Transitions

Three clinical transitions and one inventory action are gated on consent. For each gate, the patient must hold at least one `ACTIVE` patient consent whose signed, `PUBLISHED` consent form lists the relevant member in its `required_for` array; absence of such a consent is rejected with `ERR_CONSENT_MISSING`. The four gates and the operations they guard are: `CYCLE_START`, which guards starting stimulation; `RETRIEVAL`, which guards recording oocyte retrieval; `TRANSFER`, which guards performing a fresh embryo transfer; and `CRYO_STORE`, which guards storing a specimen into a tank. Because a consent that has gone `STALE` or `REVOKED` is no longer `ACTIVE`, it no longer satisfies any gate — which is precisely why a superseding republish of a form can re-block a patient who had previously cleared a gate.

### 3.7. Cryo Specimen Inventory and Tank Capacity

An `Embryologist` records a **cryo specimen** for a cycle by supplying the `treatment_cycle_id`, the `cryo_tank_id` of the intended tank, and a `specimen_type` of `EMBRYO`, `OOCYTE`, or `SPERM`. The specimen is created `PENDING`; at this point it names a tank but does not yet occupy a slot.

**Storing** a specimen advances it `PENDING → STORED` and is the cross-aggregate capacity event. The store requires the specimen to be `PENDING` (`ERR_SPECIMEN_BAD_STATE`); the cycle's `protocol_status` to be `FERTILIZATION` or `FREEZE_ALL` (`ERR_CYCLE_BAD_PROTOCOL_STATE`); an active consent covering the `CRYO_STORE` gate (`ERR_CONSENT_MISSING`); the tank to be `ONLINE` (`ERR_TANK_OFFLINE`); the tank to have room, meaning its current `reserved_slots` plus one is at most its `capacity_slots` (`ERR_TANK_AT_CAPACITY`); and the supplied `expected_tank_version` to match the tank's current `version` (`ERR_STALE_TANK_VERSION`). On success the specimen becomes `STORED`, its `storage_start_utc` is stamped at the clinic's `current_clock_utc` and its `storage_years_accrued` set to 0, the tank's `reserved_slots` is incremented by 1, and the tank's `version` is incremented by 1.

Three actions release a stored specimen's slot. **Thawing** moves `STORED → THAWED` (requires `STORED`, `ERR_SPECIMEN_BAD_STATE`). **Transferring out** to another facility moves `STORED → TRANSFERRED_OUT` (requires `STORED`, `ERR_SPECIMEN_BAD_STATE`). Each of these decrements the tank's `reserved_slots` by 1 and increments the tank's `version` by 1 as a compensating release of the slot reserved at store time. **Discarding** moves a specimen to `DISCARDED` from either `PENDING` or `STORED` (`ERR_SPECIMEN_BAD_STATE`); only if the specimen was `STORED` does discarding decrement the tank's `reserved_slots` by 1 and increment the tank's `version` by 1 — discarding a merely `PENDING` specimen touches no tank slot. `THAWED`, `DISCARDED`, and `TRANSFERRED_OUT` are terminal.

An `Embryologist` or a `BillingSpecialist` may **accrue one whole storage-year** on a specimen, which increments `storage_years_accrued` by 1; this takes effect only while the specimen is `STORED`. The accrued storage-years drive the chronological storage charges at settlement (§3.9).

A tank's committed occupancy, `reserved_slots`, is by definition the count of specimens pointing at the tank that are currently `STORED`; it is maintained incrementally by the plus-one on store and the minus-one on each release, and always reconciles to that count. From it the system derives **two distinct free-slot views of the same tank**. The committed view, `committed_free_slots`, is the tank's `capacity_slots` minus the count of its `STORED` specimens — a chronological reading that counts only slots already occupied. The projected view, `projected_free_slots`, is the tank's `capacity_slots` minus the count of its specimens that are either `PENDING` or `STORED` — a forward-looking reading that also reserves a slot for every pending specimen earmarked for the tank. The two views diverge by exactly the number of pending specimens naming the tank: a `PENDING` specimen does not hold a slot for capacity-gating purposes, so a store can legitimately succeed even when the projected view already reads zero. The store-time capacity gate uses only the committed occupancy (`reserved_slots`, the `STORED` count); the projected view is for planning and availability reads.

### 3.8. Outcome Reporting

A `Nurse` records an **outcome report** for a cycle by supplying the `treatment_cycle_id`, a `pregnancy_test_result` of `POSITIVE`, `NEGATIVE`, or `INCONCLUSIVE`, and optionally a `clinical_pregnancy` boolean (whether a clinical pregnancy was confirmed by ultrasound, defaulting to false) and a `live_birth` boolean (whether the cycle ended in a live birth, defaulting to false). An outcome report must exist before a cycle can be completed, as noted in §3.2.

At creation the report computes the cycle's `utilization_rate`, the fraction of retrieved oocytes that were fertilized. If the cycle's `oocytes_retrieved` is zero, the rate is exactly 0.0; otherwise it is the cycle's `embryos_fertilized` divided by its `oocytes_retrieved`, rounded half up to four decimal places. The rate is recomputed if the cycle's counts later change.

### 3.9. The Billing Axis: Estimate, Settlement, Write-Off, and Cancellation Fees

The billing axis evolves independently of the protocol axis. A `BillingSpecialist` first produces a **forward-looking estimate**, advancing `billing_status` `UNBILLED → ESTIMATED`. The estimate requires the cycle to be `UNBILLED` (`ERR_BILLING_BAD_STATE`) and its `protocol_status` to be one of `STIM`, `RETRIEVAL`, `FERTILIZATION`, `FRESH_TRANSFER`, or `FREEZE_ALL` (`ERR_CYCLE_BAD_PROTOCOL_STATE`). The estimate populates `estimated_patient_owed_cents` as follows. The base charge is the package's `base_price_cents`. The stimulation-medication charge is the sum of `line_total_cents` over every medication order on the cycle that is currently `SCHEDULED` or `ADMINISTERED` — that is, every order projected to be given. The cryo-storage charge assumes exactly one storage-year for each specimen currently `PENDING` or `STORED`: it is the count of those specimens multiplied by the package's `annual_cryo_storage_cents`. The gross is the base plus the medication charge plus the cryo charge. For coverage, the base is always covered; the medication charge is covered only if the package's `stim_med_covered` is true; the cryo charge is covered only if the package's `cryo_storage_covered` is true. The covered total is the sum of those covered components, multiplied by the package's `coverage_pct` and rounded half up once to whole cents to give the insurer estimate — which at the estimate stage is **not** capped by the lifetime cap. The `estimated_patient_owed_cents` is the gross minus that insurer estimate.

A `BillingSpecialist` produces the **chronological settlement**, advancing `billing_status` `ESTIMATED → SETTLED`. Settlement requires the cycle to be `ESTIMATED` (`ERR_BILLING_BAD_STATE`), the `protocol_status` to be finalized — that is, `COMPLETED` or `CANCELLED` (`ERR_CYCLE_NOT_FINALIZED`) — and the supplied `expected_cycle_version` to match the cycle's current `version` (`ERR_STALE_CYCLE_VERSION`). Settlement bills only what actually happened. The base charge is again the package's `base_price_cents`. The medication charge is the sum of `line_total_cents` over only the orders actually `ADMINISTERED` (scheduled-but-not-administered and cancelled orders are excluded). The cryo-storage charge sums, over every specimen that ever reached stored — that is, every specimen whose `storage_start_utc` has been set — that specimen's `storage_years_accrued` multiplied by the package's `annual_cryo_storage_cents`; a specimen that never left `PENDING` contributes nothing. The cancellation component is the cycle's `cancellation_fee_cents`, which is 0 unless the cycle was cancelled. The `gross_charge_cents` is the base plus the medication charge plus the cryo charge plus the cancellation component. Coverage follows the same membership as the estimate — base always covered, medication covered only if `stim_med_covered`, cryo covered only if `cryo_storage_covered` — but the cancellation fee is **never** insurance-covered. The covered total is multiplied by `coverage_pct` and rounded half up once to whole cents to give the raw insurer amount. The lifetime cap then binds: the system computes the prior insurer-paid total as the sum of `insurer_paid_cents` over all **other** cycles already `SETTLED` against the same package, takes the remaining headroom as the package's `lifetime_coverage_cap_cents` minus that prior total but never below zero, and sets `insurer_paid_cents` to the smaller of the raw insurer amount and that headroom. The `final_patient_owed_cents` is `gross_charge_cents` minus `insurer_paid_cents`. Settlement creates a `CycleInvoice` in `ISSUED` status whose `line_items` array freezes the charge lines as a snapshot — each line carrying a category drawn from `BASE`, `STIM_MED`, `CRYO_STORAGE`, and `CANCELLATION`, together with its `gross_cents`, a `covered` flag, an `insurer_cents`, and a `patient_cents` — and whose `gross_total_cents`, `insurer_total_cents`, and `patient_total_cents` sum the respective per-line amounts, with `patient_total_cents` equal to `gross_total_cents` minus `insurer_total_cents`. Settlement increments the cycle's `version` by 1. A conservation invariant must hold at settlement: `gross_charge_cents` equals `insurer_paid_cents` plus `final_patient_owed_cents`.

A `BillingSpecialist` may instead **write off** a cancelled cycle's charges, advancing `billing_status` `ESTIMATED → WRITTEN_OFF`. Write-off requires the cycle to be `ESTIMATED` (`ERR_BILLING_BAD_STATE`) and its `protocol_status` to be `CANCELLED` (`ERR_CYCLE_NOT_FINALIZED`). Only the cancellation fee survives a write-off: the system sets `final_patient_owed_cents` equal to the cycle's `cancellation_fee_cents`, sets `insurer_paid_cents` to 0, sets `gross_charge_cents` equal to the cancellation fee, and forgives all medication and storage charges. Write-off creates a `CycleInvoice` in `VOID` status capturing the written-off lines. Invoices are never created independently: they exist only as the `ISSUED` artifact of a settlement or the `VOID` artifact of a write-off, so the only invoice statuses observed are `ISSUED` and `VOID`. `SETTLED` and `WRITTEN_OFF` are terminal on the billing axis.

**Cancellation fees** are tiered by the furthest protocol stage the cycle reached before cancellation — specifically the `protocol_status` it held at the moment of the cancel transition. If the cycle was still `DRAFT`, the fee is 0. If it had reached `STIM`, the fee is 50000 cents (500 dollars). If it had reached `RETRIEVAL`, the fee is 150000 cents (1,500 dollars). If it had reached `FERTILIZATION`, the fee is 250000 cents (2,500 dollars). This fee is stored as `cancellation_fee_cents` and is the only charge that survives a write-off.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that read a resource or drive a state transition on an existing resource return a `200 OK` status code. Every path below is mounted under the clinic; the table omits request and response bodies, which must be reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clinics` | Create a clinic | ClinicAdmin |
| GET | `/clinics/{clinicId}` | Get a clinic | ClinicAdmin, Nurse, Embryologist, BillingSpecialist, Patient |
| POST | `/_clock/set_current_utc` | Set the deterministic clock for a clinic | ClinicAdmin |
| POST | `/clinics/{clinicId}/packages` | Create an insurance package | ClinicAdmin |
| GET | `/clinics/{clinicId}/packages` | List packages | ClinicAdmin, BillingSpecialist, Nurse |
| GET | `/clinics/{clinicId}/packages/{packageId}` | Get a package | ClinicAdmin, BillingSpecialist, Nurse |
| POST | `/clinics/{clinicId}/packages/{packageId}/retire` | Retire a package | ClinicAdmin |
| POST | `/clinics/{clinicId}/patients` | Register a patient | ClinicAdmin, Nurse |
| GET | `/clinics/{clinicId}/patients` | List patients | ClinicAdmin, Nurse, BillingSpecialist |
| GET | `/clinics/{clinicId}/patients/{patientId}` | Get a patient | ClinicAdmin, Nurse, BillingSpecialist, Patient |
| POST | `/clinics/{clinicId}/patients/{patientId}/deactivate` | Deactivate a patient | ClinicAdmin |
| POST | `/clinics/{clinicId}/donors` | Create a donor profile | ClinicAdmin |
| GET | `/clinics/{clinicId}/donors` | List donor profiles | ClinicAdmin, Nurse, Embryologist |
| GET | `/clinics/{clinicId}/donors/{donorId}` | Get a donor profile | ClinicAdmin, Nurse, Embryologist |
| POST | `/clinics/{clinicId}/surrogates` | Create a surrogate profile | ClinicAdmin |
| GET | `/clinics/{clinicId}/surrogates` | List surrogate profiles | ClinicAdmin, Nurse |
| GET | `/clinics/{clinicId}/surrogates/{surrogateId}` | Get a surrogate profile | ClinicAdmin, Nurse |
| POST | `/clinics/{clinicId}/consent-forms` | Create a consent form (DRAFT) | ClinicAdmin |
| GET | `/clinics/{clinicId}/consent-forms` | List consent forms | ClinicAdmin, Nurse, Patient |
| GET | `/clinics/{clinicId}/consent-forms/{formId}` | Get a consent form | ClinicAdmin, Nurse, Patient |
| POST | `/clinics/{clinicId}/consent-forms/{formId}/publish` | Publish a consent form | ClinicAdmin |
| POST | `/clinics/{clinicId}/patient-consents` | Sign a published consent form | Patient, Nurse |
| GET | `/clinics/{clinicId}/patient-consents` | List patient consents | ClinicAdmin, Nurse, Patient |
| GET | `/clinics/{clinicId}/patient-consents/{consentId}` | Get a patient consent | ClinicAdmin, Nurse, Patient |
| POST | `/clinics/{clinicId}/patient-consents/{consentId}/revoke` | Revoke own consent | Patient |
| POST | `/clinics/{clinicId}/tanks` | Create a cryo tank | ClinicAdmin, Embryologist |
| GET | `/clinics/{clinicId}/tanks` | List tanks | ClinicAdmin, Embryologist |
| GET | `/clinics/{clinicId}/tanks/{tankId}` | Get a tank | ClinicAdmin, Embryologist |
| POST | `/clinics/{clinicId}/tanks/{tankId}/set-maintenance` | Put a tank into maintenance | ClinicAdmin, Embryologist |
| POST | `/clinics/{clinicId}/cycles` | Create a treatment cycle | Nurse |
| GET | `/clinics/{clinicId}/cycles` | List cycles | ClinicAdmin, Nurse, Embryologist, BillingSpecialist, Patient |
| GET | `/clinics/{clinicId}/cycles/{cycleId}` | Get a cycle | ClinicAdmin, Nurse, Embryologist, BillingSpecialist, Patient |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/start-stim` | Begin stimulation | Nurse |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/retrieve` | Record oocyte retrieval | Nurse |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/revert-to-stim` | Revert retrieval to stimulation | Nurse |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/fertilize` | Record fertilization counts | Embryologist |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/transfer` | Perform a fresh embryo transfer | Embryologist |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/freeze-all` | Freeze all embryos | Embryologist |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/complete` | Complete a cycle | Nurse |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/cancel` | Cancel a cycle | Nurse |
| POST | `/clinics/{clinicId}/medications` | Add a medication order | Nurse |
| GET | `/clinics/{clinicId}/medications` | List medication orders | ClinicAdmin, Nurse, BillingSpecialist, Patient |
| GET | `/clinics/{clinicId}/medications/{medId}` | Get a medication order | ClinicAdmin, Nurse, BillingSpecialist, Patient |
| POST | `/clinics/{clinicId}/medications/{medId}/administer` | Mark a medication administered | Nurse |
| POST | `/clinics/{clinicId}/medications/{medId}/cancel` | Cancel a scheduled medication | Nurse |
| POST | `/clinics/{clinicId}/monitoring-appointments` | Schedule a monitoring appointment | Nurse |
| GET | `/clinics/{clinicId}/monitoring-appointments` | List monitoring appointments | ClinicAdmin, Nurse, Patient |
| GET | `/clinics/{clinicId}/monitoring-appointments/{apptId}` | Get an appointment | ClinicAdmin, Nurse, Patient |
| POST | `/clinics/{clinicId}/monitoring-appointments/{apptId}/reschedule` | Reschedule an appointment | Nurse |
| POST | `/clinics/{clinicId}/monitoring-appointments/{apptId}/confirm` | Confirm a rescheduled appointment | Nurse |
| POST | `/clinics/{clinicId}/monitoring-appointments/{apptId}/complete` | Complete an appointment | Nurse |
| POST | `/clinics/{clinicId}/monitoring-appointments/{apptId}/no-show` | Mark an appointment no-show | Nurse |
| POST | `/clinics/{clinicId}/monitoring-appointments/{apptId}/cancel` | Cancel an appointment | Nurse |
| POST | `/clinics/{clinicId}/cryo-specimens` | Create a specimen record (PENDING) | Embryologist |
| GET | `/clinics/{clinicId}/cryo-specimens` | List specimens | ClinicAdmin, Embryologist, Patient |
| GET | `/clinics/{clinicId}/cryo-specimens/{specimenId}` | Get a specimen | ClinicAdmin, Embryologist, Patient |
| POST | `/clinics/{clinicId}/cryo-specimens/{specimenId}/store` | Store a specimen into a tank | Embryologist |
| POST | `/clinics/{clinicId}/cryo-specimens/{specimenId}/accrue-storage-year` | Accrue a storage-year | Embryologist, BillingSpecialist |
| POST | `/clinics/{clinicId}/cryo-specimens/{specimenId}/thaw` | Thaw a stored specimen | Embryologist |
| POST | `/clinics/{clinicId}/cryo-specimens/{specimenId}/discard` | Discard a specimen | Embryologist |
| POST | `/clinics/{clinicId}/cryo-specimens/{specimenId}/transfer-out` | Transfer a specimen out | Embryologist |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/billing/estimate` | Produce a forward-looking estimate | BillingSpecialist |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/billing/settle` | Settle a cycle | BillingSpecialist |
| POST | `/clinics/{clinicId}/cycles/{cycleId}/billing/write-off` | Write off a cancelled cycle | BillingSpecialist |
| GET | `/clinics/{clinicId}/cycle-invoices` | List invoices | ClinicAdmin, BillingSpecialist, Patient |
| GET | `/clinics/{clinicId}/cycle-invoices/{invoiceId}` | Get an invoice | ClinicAdmin, BillingSpecialist, Patient |
| POST | `/clinics/{clinicId}/outcome-reports` | Record an outcome report | Nurse |
| GET | `/clinics/{clinicId}/outcome-reports` | List outcome reports | ClinicAdmin, Nurse, BillingSpecialist, Patient |
| GET | `/clinics/{clinicId}/outcome-reports/{outcomeId}` | Get an outcome report | ClinicAdmin, Nurse, BillingSpecialist, Patient |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_CLINIC_NOT_FOUND` | 404 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_DONOR_NOT_FOUND` | 404 |
| `ERR_SURROGATE_NOT_FOUND` | 404 |
| `ERR_CONSENT_FORM_NOT_FOUND` | 404 |
| `ERR_CONSENT_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_MEDICATION_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_TANK_NOT_FOUND` | 404 |
| `ERR_SPECIMEN_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_OUTCOME_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_STALE_TANK_VERSION` | 412 |
| `ERR_CYCLE_BAD_PROTOCOL_STATE` | 409 |
| `ERR_BILLING_BAD_STATE` | 409 |
| `ERR_APPT_BAD_STATE` | 409 |
| `ERR_MED_BAD_STATE` | 409 |
| `ERR_SPECIMEN_BAD_STATE` | 409 |
| `ERR_CONSENT_BAD_STATE` | 409 |
| `ERR_CONSENT_FORM_BAD_STATE` | 409 |
| `ERR_PATIENT_INACTIVE` | 409 |
| `ERR_PACKAGE_RETIRED` | 409 |
| `ERR_DONOR_NOT_AVAILABLE` | 409 |
| `ERR_SUPERSEDE_TARGET_NOT_PUBLISHED` | 409 |
| `ERR_CONSENT_MISSING` | 409 |
| `ERR_CONSENT_FORM_NOT_PUBLISHED` | 409 |
| `ERR_EMBRYO_COUNT_EXCEEDS_OOCYTES` | 422 |
| `ERR_NO_EMBRYOS_AVAILABLE` | 409 |
| `ERR_OUTCOME_REQUIRED` | 409 |
| `ERR_APPOINTMENT_IN_PAST` | 422 |
| `ERR_APPOINTMENT_NOT_STARTED` | 409 |
| `ERR_APPOINTMENT_NOT_ENDED` | 409 |
| `ERR_MONITORING_SLOT_CONFLICT` | 409 |
| `ERR_MEDICATION_SCHEDULE_OVERLAP` | 409 |
| `ERR_TANK_OFFLINE` | 409 |
| `ERR_TANK_AT_CAPACITY` | 409 |
| `ERR_CYCLE_NOT_FINALIZED` | 409 |
