# General Practice EHR API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the General Practice EHR & Visit API, a back-office clinical and administrative platform for a primary-care practice. The system is the system of record for the people and the paperwork of everyday outpatient medicine: it tracks providers and the patients on their panels, the visits those patients attend, the billing that follows each encounter, the prescriptions written during care, the specialist referrals a primary-care provider issues, the patient-facing portal, and the HEDIS quality measures by which the practice's preventive-care performance is judged.

Three pressures shape the design. First, **regulatory correctness**: electronic prescribing of controlled substances (EPCS) carries hard identity-proofing and two-factor requirements that must never be bypassed, and HEDIS reporting must compute compliance rates from a defensible, auditable population. Second, **clinical-administrative workflow**: a visit moves through scheduling, arrival, the clinical encounter, coding, and billing finalization, with several legitimate detours (cancellation, no-show, reopening a coded chart), and each handoff belongs to a different role. Third, **financial integrity**: charges are derived from a shared CPT fee schedule, written down by a contractual adjustment at finalization, and rolled up into a per-patient ledger of lifetime charges and outstanding balance. Because several of these derived values reconcile across entities — a finalized visit can close a patient's open care gap, a dispensed medication can satisfy an adherence measure — the system treats cross-entity recomputation as a first-class concern rather than an afterthought.

The remainder of this document defines the global contract every endpoint obeys (Section 2), the domain workflows and the business rules scattered through them (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly five roles: `FrontDesk`, `Provider`, `Biller`, `QualityAnalyst`, and `Patient`. When a role is authenticated but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The five roles map to distinct responsibilities. A `FrontDesk` operator owns registration, scheduling, panel binding, check-in, the referral administrative workflow, and portal administration. A `Provider` is the clinician who conducts visits, codes them, writes and signs prescriptions, and requests or cancels referrals. A `Biller` defines billing codes, finalizes visits, and records payments. A `QualityAnalyst` creates and excludes HEDIS measures and reads compliance rates. A `Patient` performs portal self-service and reads their own records.

Two of these roles are **entity-backed**, meaning the `X-User-ID` is the `id` of a persisted entity and is used for ownership checks. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks compare a resource's provider foreign key to `X-User-ID` — for example, only the provider whose `id` equals a visit's `provider_id` may start or code that visit, and only the provider whose `id` equals a prescription's `provider_id` may sign it. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks compare a resource's patient foreign key to `X-User-ID`, and a patient may activate only the portal account whose `patient_id` equals `X-User-ID` and may read only their own patient record and the records hanging off it. The remaining three roles — `FrontDesk`, `Biller`, and `QualityAnalyst` — are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity. The server accepts it for authentication and authorization but does not compare it to any entity's `id`.

A violation of an entity-backed ownership check — an authenticated and role-permitted actor who is nonetheless not the owner or authorized provider of the target resource — is rejected with `ERR_NOT_RESOURCE_OWNER`. This is distinct from `ERR_FORBIDDEN`, which fires earlier when the role itself is not permitted to attempt the operation at all.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with no upper bound beyond the size of the collection.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by `created_at` in ascending order — that is, oldest first.

In addition to `limit` and `offset`, list endpoints accept optional equality-filter query parameters on their resource's foreign-key, status, and categorical fields, narrowing the collection to rows whose field exactly equals the supplied value before the page window is applied. The top-level collections filter by: providers — `specialty` and `status`; patients — `pcp_id` and `status`; CPT codes — `category`; visits — `patient_id`, `provider_id`, and `status`; prescriptions — `patient_id`, `provider_id`, `visit_id`, and `status`; referrals — `patient_id`, `referring_provider_id`, and `status`. The patient-scoped sub-collections (`/patients/{id}/visits`, `/patients/{id}/prescriptions`, `/patients/{id}/referrals`) additionally filter by `status`, and `/patients/{id}/hedis-measures` by `measure_type`, `measurement_year`, and `status`. Filter parameters are optional and an absent filter applies no constraint; an unrecognized filter parameter is simply ignored.

Every list-based response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. `total_count` reflects the size of the full filtered collection before the page window is applied, and `has_more` is true when records remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Most resources in this system are first-class records carrying a uniform set of system-managed fields. Each such resource has an `id` — a server-minted UUID with no type prefix — a `created_at` timestamp recording first creation, an `updated_at` timestamp recording the most recent modification, and a `version` integer. Both timestamps are ISO 8601 UTC values with three fractional digits. The `version` begins at 1 on creation and increments by exactly 1 on every mutation that changes the resource, including mutations that only touch derived fields. Whenever a resource is mutated, its `updated_at` is refreshed to the time of the change and its `version` is incremented in lockstep.

These properties apply to `Provider`, `Patient`, `Visit`, `ChargeLine`, `Prescription`, `Referral`, `PortalAccount`, and `HedisMeasure`. The one exception is the `CptCode`: a CPT code is a piece of shared reference configuration rather than a mutable workflow record, so it carries only an `id` and a `created_at`. A `CptCode` has neither `updated_at` nor `version`, and the system does not expose those fields for it.

### 2.5. Cross-Entity Reconciliation and Derived Fields

Several fields are **derived** — never written directly by a client, always recomputed by the server from authoritative source rows. When a server operation derives a new value for such a field, the owning resource is mutated: its `updated_at` advances and its `version` increments, exactly as in Section 2.4. This version-advancing applies to a derived recompute that is the operation's direct subject — for example the patient ledger recompute on payment, finalize, or dispense, which bumps the patient. It does **not** apply to the purely secondary recomputes of a count on a neighboring resource that are byproducts of an operation targeting a different entity: specifically, the recompute of a patient's `open_care_gaps` triggered by creating or excluding one of that patient's HEDIS measures, and the recompute of a former provider's `panel_size` when one of its panel patients is deactivated, each update the count in place without advancing that neighboring resource's `updated_at` or `version`. (Because these counts are recomputed afresh on every read, a later read of the resource still reflects the current value.) Two reconciliation chains are central to the domain and deserve explicit mention here so that implementers expect the secondary effects rather than the primary one alone.

The first chain originates when a visit is finalized. Finalizing locks the visit's charge amounts and recomputes the visit's billed total under the final pricing variant; that new total then flows into the patient's lifetime-charge and outstanding-balance ledger; and, when the finalized visit is of a qualifying type and a matching open care gap exists, the relevant quality measure flips to compliant, which in turn forces the patient's open-care-gap count to be recomputed downward. The second chain originates when a prescription is dispensed: the patient's active-medication count is recomputed, and if that count now satisfies the adherence threshold and a matching open adherence gap exists, that measure flips to compliant and the patient's open-care-gap count is again recomputed. The precise conditions and arithmetic of each step live in Section 3 near the workflow that triggers them.

### 2.6. Nested Resource Retrieval and Reference Resolution

Several endpoints address a resource through a path identifier, and a few address a child resource beneath a parent in the path. Path identifiers are validated left to right: the system confirms the existence of each identifier in the order it appears, and the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any deeper validation runs. A request for the charge lines of a non-existent visit, for instance, fails on the visit identifier before the charge-line collection is ever consulted.

Foreign keys supplied in a request body are a separate concern from path identifiers. When a write carries a reference such as `patient_id`, `provider_id`, `visit_id`, or `cpt_code` and that reference does not resolve to an existing row, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. This applies to visit scheduling, charge-line creation, prescription creation, referral creation, panel binding, HEDIS-measure creation, and portal-account creation.

### 2.7. Monetary Values, Rounding, and Pricing Precision

All money in the system is held in whole cents as integers — `base_fee_cents`, `amount_cents`, `billed_total_cents`, `lifetime_charges_cents`, `outstanding_balance_cents`, and the `amount_cents` of a recorded payment are all integer-cent quantities. Wherever a computation produces a fractional cent, the system rounds half up to the nearest whole cent: a value whose fractional part is exactly one half rounds away from zero to the next whole cent.

Rounding order is significant and is pinned. A charge line is rounded to whole cents at the line level, when the line amount is computed. A visit's billed total is then formed by **summing the already-rounded line amounts** — the system rounds per line first and then sums, never the reverse. At finalization a single further rounding is applied when the contractual write-down is taken. HEDIS compliance rates are the one non-cent monetary-style quantity; they are expressed as percentages carried to two decimal places, again rounding half up. The exact formulas appear in Section 3.

### 2.8. Optimistic Concurrency on Panel Binding

Binding a patient to a provider as that patient's primary care provider is the one operation in this system guarded by optimistic concurrency control. The panel-bind request must carry `expected_provider_version`, a non-optional field holding the `version` of the target `Provider` that the client last observed. Before the bind proceeds, the system compares `expected_provider_version` against the provider's current `version`. If they do not match — because another writer has advanced the provider's `version` since the client read it, for example by binding a different patient and consuming an open panel slot — the bind is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from binding against a stale view of the provider's remaining panel capacity. No other endpoint in the system accepts or requires a version field; panel binding is the sole concurrency-controlled write.

### 2.9. Validation Ordering

When several validations could apply to a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing or malformed header yields `ERR_UNAUTHENTICATED` before anything else. Role authorization is checked next, yielding `ERR_FORBIDDEN`. The system then confirms that every path-referenced resource exists (`ERR_NOT_FOUND`), then that every body-referenced foreign key resolves (`ERR_REFERENCE_NOT_FOUND`), then that required input fields are present, well-typed, and within their declared enum sets (`ERR_INVALID_REQUEST`). Only after these structural checks does the system evaluate state legality — whether the requested transition is defined from the resource's current state (`ERR_INVALID_STATE`) — followed by resource-ownership checks (`ERR_NOT_RESOURCE_OWNER`), and finally the domain-specific business rules described throughout Section 3. The upshot for an implementer: a structural failure always masks a business failure on the same request, and authentication always masks everything.

## 3. Business Logic & Workflows

### 3.1. Registering Providers and Building Panels

A `FrontDesk` operator registers a provider by supplying the provider's `npi`, a `full_name`, and optionally a `specialty`, a `dea_number`, an `epcs_enrolled` flag, and a `panel_capacity`. The `npi` is a National Provider Identifier and must be exactly 10 digits; it must be unique across all providers, and a duplicate is rejected with `ERR_DUPLICATE_NPI`. The `full_name` is required and must be non-empty. The `specialty`, when supplied, is one of `FAMILY_MEDICINE`, `INTERNAL_MEDICINE`, or `PEDIATRICS`, and defaults to `FAMILY_MEDICINE` when omitted. The `dea_number`, when supplied, must be exactly 9 characters — two letters followed by seven digits — and defaults to null; it is the registration that authorizes a provider to sign controlled-substance prescriptions. The `epcs_enrolled` flag records whether the provider has completed EPCS two-factor identity proofing and defaults to false. The `panel_capacity` is the maximum number of `ACTIVE` patients that may be bound to this provider as PCP; it must be a non-negative integer and defaults to 2000. A newly registered provider begins in `ACTIVE` status with a `panel_size` of 0 and a `controlled_rx_count` of 0.

A provider's `panel_size` is a derived count: the number of patients whose bound primary-care provider is this provider and whose own status is `ACTIVE`. Inactive patients never count toward panel size. The `controlled_rx_count` is likewise derived: the number of this provider's prescriptions whose `schedule` is one of the controlled schedules — `C_II`, `C_III`, `C_IV`, or `C_V` — that are currently in `SIGNED`, `TRANSMITTED`, or `DISPENSED` status.

Binding a patient to a provider as PCP is a `FrontDesk` action that names the `patient_id` to bind and carries the `expected_provider_version` concurrency token described in Section 2.8. The bind sets the patient's `pcp_id` to this provider and recomputes the provider's `panel_size`. Capacity is a hard ceiling: if completing the bind would make the provider's `panel_size` reach or exceed `panel_capacity`, the bind is rejected with `ERR_PANEL_AT_CAPACITY`. When binding is permitted, the provider's `version` increments by 1. The relative ordering of the panel-bind checks matters: structural and reference checks come first, then the at-capacity business rule, and the stale-version concurrency check is evaluated as the final guard on this endpoint.

Deactivating a provider is a `FrontDesk` action permitted only while the provider is `ACTIVE`, transitioning the provider from `ACTIVE` to `INACTIVE`. Deactivation has a cascade: every patient whose bound PCP is this provider has their `pcp_id` cleared to null and is thereby unbound, the provider's `panel_size` is recomputed to 0, and the provider's `version` increments by 1.

### 3.2. Registering Patients and the Patient Ledger

A `FrontDesk` operator registers a patient with a `first_name`, a `last_name`, a `date_of_birth`, and an administrative `sex`. The names are required and non-empty. The `date_of_birth` is an ISO date in `YYYY-MM-DD` form and must be on or before the current clock date. The `sex` is required and is either `M` or `F`; it drives sex-specific HEDIS measures. A new patient is created `ACTIVE` with `pcp_id` null and all derived counters at zero. The `pcp_id` foreign key is system-managed and is set only through the panel-bind operation of Section 3.1, never supplied directly at registration.

A patient carries four derived fields that the system maintains. `lifetime_charges_cents` is the running sum of `billed_total_cents` across this patient's `FINALIZED` visits. `outstanding_balance_cents` is `lifetime_charges_cents` minus the total of all payments recorded for the patient; it may go negative if the patient has overpaid, representing a credit. `active_medication_count` is the count of this patient's prescriptions currently in `DISPENSED` status. `open_care_gaps` is the count of this patient's HEDIS measures that are still in `GAP` status, are eligible, and belong to the current measurement year — a fixed reporting year of 2026.

A `Biller` records a payment against a patient by supplying an `amount_cents`. Recording a payment recomputes the patient's `outstanding_balance_cents` downward by the paid amount. Because outstanding balance is defined as lifetime charges minus total payments, each payment moves the balance toward zero and may carry it below zero into credit.

Deactivating a patient is a `FrontDesk` action that transitions the patient from `ACTIVE` to `INACTIVE`, permitted only when the patient is currently `ACTIVE` and has no visit in any of the non-terminal visit states `SCHEDULED`, `CHECKED_IN`, `IN_PROGRESS`, or `CODED`. An attempt to deactivate a patient who still has such an open visit is rejected with `ERR_PATIENT_HAS_OPEN_VISITS`. When deactivation proceeds, if the patient had a bound PCP, that former provider's `panel_size` is recomputed (decremented by one as this patient leaves the active panel), the patient's `pcp_id` is cleared to null, and the patient's `version` increments by 1. As noted in Section 2.5, this secondary recompute of the former provider's `panel_size` does not advance the provider's `updated_at` or increment its `version`; the provider record is left untouched apart from its refreshed `panel_size` count.

### 3.3. The CPT Fee Schedule and Charge Pricing

The billing catalogue is a set of CPT/HCPCS codes maintained by a `Biller`. Creating a code supplies a `code` string, a `short_description`, a `category`, a `base_fee_cents`, and optionally a `requires_em_level` flag. The `code` must be exactly 5 characters and unique across all codes; a duplicate is rejected with `ERR_DUPLICATE_CPT_CODE`. The `short_description` is required and non-empty. The `category` is required and is one of `EM`, `PREVENTIVE`, `VACCINE_ADMIN`, or `PROCEDURE`, and governs which fee logic applies. The `base_fee_cents` is the base fee in whole cents before units and any level multiplier and must be a non-negative integer. The `requires_em_level` flag defaults to false; when true, any charge line that bills this code must supply an evaluation-and-management level that selects a tiered multiplier.

Charge lines are added to a visit by the rendering `Provider` while the visit is `IN_PROGRESS`. A charge line names a `cpt_code` — a natural-key reference to an existing CPT code's `code` string, not a server id — and optionally `units` and an `em_level`. The `units` field is the number of units billed; it must be an integer of at least 1 and defaults to 1. The `em_level` is an evaluation-and-management level and, when supplied, must be an integer from 1 through 5 inclusive; it is required when the referenced code's `requires_em_level` is true and is otherwise null. The system does not reject or scrub an `em_level` that is supplied on a charge line whose code does not require one: such a value is persisted on the charge line as given but is ignored by the amount computation (the multiplier is held at 1 whenever the code does not require an E/M level). The charge line's owning `visit_id` is taken from the path, not the body. The line's `amount_cents` is always computed by the system; any client-supplied amount is ignored.

The line amount is derived as follows. The base is the referenced code's `base_fee_cents`. If the referenced code does not require an E/M level, the multiplier is 1. If it does require an E/M level, the multiplier is selected from the supplied `em_level`: level 1 maps to a multiplier of 0.5, level 2 to 0.8, level 3 to 1.0, level 4 to 1.4, and level 5 to 2.0. The raw amount is the base multiplied by this multiplier and then by the number of `units`. That raw amount is rounded half up to whole cents to yield the line's `amount_cents`. This per-line rounding is the pinned inner step that the visit total later consumes — the line is rounded before it is ever summed.

### 3.4. The Visit Lifecycle: Scheduling Through Coding

A visit threads a patient and a provider through a single encounter. A `FrontDesk` operator schedules a visit by naming the `patient_id`, the `provider_id`, the `visit_type`, a `scheduled_start`, a `scheduled_end`, and — for vaccination visits — a `vaccine_code`. The `visit_type` is one of `CONSULTATION`, `PHYSICAL`, or `VACCINATION`. The `scheduled_start` and `scheduled_end` are ISO 8601 UTC instants bounding a half-open slot: the start is inclusive, the end is exclusive, and the end must be strictly after the start. The `vaccine_code` is the immunization product code, such as `FLU` or `MMR`; it is required when `visit_type` is `VACCINATION` and is otherwise null. A visit is created in `SCHEDULED` status, and the slot it occupies is the half-open interval from `scheduled_start` up to but not including `scheduled_end`.

Scheduling is overlap-checked against the rendering provider's calendar. A new visit is rejected with `ERR_SLOT_OVERLAP` if its slot overlaps any existing visit of the same provider that is not cancelled and not a no-show. Because slots are half-open, two visits that merely touch at an endpoint — one ending exactly when the next begins — do not overlap and are both allowed.

From `SCHEDULED`, a visit can move in one of several directions, all initiated by a `FrontDesk` operator except where noted. Checking the patient in advances the visit from `SCHEDULED` to `CHECKED_IN`; this is permitted only when the visit is `SCHEDULED`, the rendering provider is `ACTIVE`, and the patient is `ACTIVE`. Check-in additionally enforces vaccine spacing, described in Section 3.5. Cancelling a scheduled visit moves it from `SCHEDULED` to `CANCELLED` and releases the provider's time slot. Marking a no-show moves it from `SCHEDULED` to `NO_SHOW`, is permitted only once the current clock has reached or passed the `scheduled_end`, and likewise releases the slot. Each of `CHECKED_IN`, `CANCELLED`, and `NO_SHOW` increments the visit's `version` by 1.

The rendering provider then drives the clinical phases. Starting the encounter advances the visit from `CHECKED_IN` to `IN_PROGRESS`; it requires the visit to be `CHECKED_IN` and is restricted to the provider whose `id` equals the visit's `provider_id`. Coding the visit advances it from `IN_PROGRESS` to `CODED` and requires that the visit have at least one charge line; coding writes the visit's `billed_total_cents` to the provisional total (defined below) and is likewise restricted to the visit's own provider. A coded visit can be reopened back to `IN_PROGRESS` by the provider so that charge lines can be added or corrected; reopening resets `billed_total_cents` to 0. Each of these clinical transitions increments the visit's `version` by 1.

### 3.5. Vaccine Spacing and Visit Billing Totals

Vaccine spacing is enforced at check-in. When a `VACCINATION` visit is checked in, the system rejects it with `ERR_VACCINE_INTERVAL_VIOLATION` if the same patient already has another visit for the same `vaccine_code` that has reached `CHECKED_IN` or a later status and whose `scheduled_start` falls within the 28 days immediately before this visit's `scheduled_start`. In other words, two doses of the same vaccine for one patient must be spaced at least 28 days apart; a second dose whose scheduled start is fewer than 28 days after a prior administered dose is blocked at check-in.

The visit's `billed_total_cents` is computed in two variants from the visit's charge lines. The **provisional** total — written when the visit is coded — is the plain sum of the charge lines' already-rounded `amount_cents`. No contractual adjustment is applied to the provisional total; it is the straight sum of per-line-rounded amounts. The **final** total — written when the visit is finalized — takes that same provisional sum and applies the network contractual adjustment: it multiplies the provisional sum by the quantity one minus the contractual adjustment rate of 0.10 (that is, by 0.90), then rounds the result half up to whole cents once. The final total is therefore the provisional total written down by ten percent and rounded a single time. There is no per-line status filter on either variant; a visit has no partial lines, so both variants sum every charge line belonging to the visit.

### 3.6. Visit Finalization and the Care-Gap Cascade

Finalizing a visit is a `Biller` action permitted only when the visit is `CODED`, transitioning the visit from `CODED` to `FINALIZED`. Finalization is the origin of the deeper of the two reconciliation chains, and its effects must all land together. First, the visit's `billed_total_cents` is set to the final variant of the total and the charge-line amounts are locked. Second, the patient's `lifetime_charges_cents` and `outstanding_balance_cents` are recomputed so that they now include this visit's billed total — lifetime charges resum across the patient's finalized visits, and outstanding balance is lifetime charges minus recorded payments. Third, if the finalized visit's `visit_type` is `PHYSICAL` or `VACCINATION` and the patient has a matching HEDIS measure that is still in `GAP` status for the current measurement year, that measure's status flips to `NUMERATOR_COMPLIANT`. Here "matching" is interpreted broadly: every one of the patient's measures whose `status` is `GAP` and whose `measurement_year` equals the current measurement year (2026) is flipped, regardless of the measure's `measure_type` or its `eligible` flag — there is no further pairing of a specific `measure_type` to the visit's `visit_type`, and all such GAP measures present are flipped in one pass. Fourth, that flip causes the patient's `open_care_gaps` count to be recomputed downward. Finally, the visit's `version` increments by 1. A consultation visit triggers the ledger recomputation but not the care-gap flip, since only physical and vaccination visits satisfy a preventive measure.

### 3.7. Prescriptions and the EPCS Signing Protocol

A `Provider` writes a prescription by naming the `patient_id`, the prescribing `provider_id`, the `visit_id` of the encounter during which it was written, a `drug_name`, and optionally a `schedule`. The `drug_name` is required and non-empty. The `schedule` is the DEA controlled-substance schedule and is one of `NON_CONTROLLED`, `C_II`, `C_III`, `C_IV`, or `C_V`, defaulting to `NON_CONTROLLED`. A new prescription begins in `DRAFT` status. A `two_factor_token` may be supplied later at signing; it defaults to null and is required only for controlled-substance EPCS signing.

The prescription lifecycle is a chain of provider-driven transitions with two revert edges. Submitting a draft advances it from `DRAFT` to `PENDING_SIGNATURE`; this requires the prescription to be `DRAFT` and requires the referenced visit to be in `IN_PROGRESS`, `CODED`, or `FINALIZED` status. A pending prescription can be revised back from `PENDING_SIGNATURE` to `DRAFT` so the drug or schedule can be corrected before signing. Signing advances it from `PENDING_SIGNATURE` to `SIGNED`. Transmitting advances it from `SIGNED` to `TRANSMITTED`, sending it to the pharmacy. Dispensing advances it from `TRANSMITTED` to `DISPENSED`. A prescription can also be voided from any non-terminal status — that is, from `DRAFT`, `PENDING_SIGNATURE`, `SIGNED`, or `TRANSMITTED` — moving it to `VOIDED`. Every one of these transitions increments the prescription's `version` by 1.

Signing carries the EPCS safety protocol. Signing is restricted to the provider whose `id` equals the prescription's `provider_id`. When the prescription's `schedule` is anything other than `NON_CONTROLLED`, signing additionally requires that the prescribing provider has `epcs_enrolled` true, has a non-null `dea_number`, and that a non-empty `two_factor_token` is supplied with the sign request. If any of those three controlled-substance requirements is unmet, the sign is rejected with `ERR_EPCS_REQUIREMENTS_NOT_MET`. A non-controlled prescription needs none of the EPCS factors. Signing recomputes the prescriber's `controlled_rx_count` whenever the prescription is controlled, and voiding likewise recomputes the prescriber's `controlled_rx_count` whenever the voided prescription is controlled, since both transitions change the set of the provider's live controlled prescriptions.

Dispensing is the origin of the shorter reconciliation chain. When a prescription is dispensed, the patient's `active_medication_count` is recomputed upward. Then, if the patient has a HEDIS measure of type `MED_ADHERENCE` still in `GAP` status for the current measurement year and the recomputed `active_medication_count` is at least the adherence minimum of one fill, that measure flips to `NUMERATOR_COMPLIANT` and the patient's `open_care_gaps` is recomputed. A single dispensed fill is sufficient to satisfy the adherence measure.

### 3.8. Referrals and Authorization Windows

A referral sends a patient to a specialist. A `Provider` creates a referral by naming the `patient_id`, the `referring_provider_id`, a `target_specialty`, and optionally a `priority`. The `target_specialty` is one of `CARDIOLOGY`, `DERMATOLOGY`, `ORTHOPEDICS`, or `ENDOCRINOLOGY`. The `priority` is either `ROUTINE` or `URGENT` and defaults to `ROUTINE`; it controls how long the authorization remains valid. A new referral begins in `REQUESTED` status with a null `authorization_expires_at`.

A `FrontDesk` operator administers the referral from there. Authorizing advances the referral from `REQUESTED` to `AUTHORIZED`, but only when the referred patient has a bound PCP — when the patient's `pcp_id` is non-null. An attempt to authorize a referral for a patient with no bound PCP is rejected with `ERR_NO_PCP_BOUND`. On authorization, the system sets `authorization_expires_at` to the authorizing clock instant plus a whole number of days: 90 days for a `ROUTINE` referral and 14 days for an `URGENT` one. Alternatively, a requested referral can be denied, moving it from `REQUESTED` to `DENIED`.

Once authorized, the referral can be scheduled, expired, or — by the referring provider — cancelled. Scheduling advances it from `AUTHORIZED` to `SCHEDULED` and is permitted only while the current clock is strictly before `authorization_expires_at`; an attempt to schedule once the clock has reached or passed the expiry instant is rejected with `ERR_REFERRAL_EXPIRED`. Expiring an authorized referral whose window has elapsed moves it from `AUTHORIZED` to `EXPIRED`; this system sweep is invoked through the expire operation and requires that the current clock has reached or passed `authorization_expires_at`. Invoking expire while the clock is still strictly before `authorization_expires_at` — the window has not yet elapsed — is rejected with `ERR_INVALID_STATE`, the same error returned when the referral is not in `AUTHORIZED` to begin with. A scheduled referral is completed by moving it from `SCHEDULED` to `COMPLETED`. Cancelling a referral is reserved to the referring provider — the provider whose `id` equals the referral's `referring_provider_id` — and is reachable while the referral is `REQUESTED` or `AUTHORIZED`, moving it to `CANCELLED`. Each referral transition increments the referral's `version` by 1.

### 3.9. The Patient Portal Lifecycle

A `FrontDesk` operator invites a patient to the portal by naming the `patient_id` and a `login_email`. A patient may have only one portal account, so the `patient_id` must be unique across portal accounts, and the `login_email` must likewise be unique; a violation of either uniqueness rule is rejected with `ERR_DUPLICATE_PORTAL_ACCOUNT`. A new portal account is created in `INVITED` status with a server-issued `activation_token` and a `failed_login_count` of 0.

The portal account is the one resource a `Patient` actor drives directly. Activating an account is performed by the owning patient and supplies an `activation_token`. When the supplied token matches the account's `activation_token`, the account advances from `INVITED` to `ACTIVE` and its `failed_login_count` resets to 0. When the supplied token does not match, the `failed_login_count` is incremented; if that increment brings the count to the lockout threshold of 3, the account auto-suspends, moving from `INVITED` to `SUSPENDED`. Both the successful activation and the auto-suspend increment the account's `version` by 1.

A `FrontDesk` operator administers an account beyond activation. An active account can be suspended, moving from `ACTIVE` to `SUSPENDED`. A suspended account can be reinstated, moving from `SUSPENDED` back to `ACTIVE` and resetting `failed_login_count` to 0 — the suspend-and-reinstate pair forms a cycle. An account can be permanently deactivated from any non-terminal status — `ACTIVE`, `SUSPENDED`, or `INVITED` — moving it to the terminal `DEACTIVATED` status. Every portal transition increments the account's `version` by 1.

### 3.10. HEDIS Measures, Eligibility, and Compliance Rates

A `QualityAnalyst` creates a HEDIS measure for a patient by naming the `patient_id`, a `measure_type`, a `measurement_year`, and optionally a `method` and a `chart_confirmed` flag. The `measure_type` is one of `CIS_FLU`, `BCS_MAMMOGRAM`, `CBP_BP_CONTROL`, or `MED_ADHERENCE`. The `measurement_year` is a calendar year and must be an integer of at least 2000. The `method` is either `ADMINISTRATIVE` or `HYBRID`, defaulting to `ADMINISTRATIVE`; an administrative measure relies on claims alone, while a hybrid measure also credits chart-confirmed events. The `chart_confirmed` flag, defaulting to false, marks whether a chart review confirmed the qualifying event for a hybrid measure. A new measure begins in `GAP` status, with `eligible` and `status` computed at creation.

Eligibility is computed from the patient's age and sex at the close of the measurement year. The patient's age is the whole number of years between their `date_of_birth` and December 31 of the `measurement_year`, computed by dividing the elapsed days by 365.25 and taking the floor. Each measure type has an inclusive age window — both bounds count: `CIS_FLU` covers ages 0 through 18, `BCS_MAMMOGRAM` covers ages 50 through 74, `CBP_BP_CONTROL` covers ages 18 through 85, and `MED_ADHERENCE` covers ages 18 through 120. A patient is in the eligible population when their age falls at or above the window's minimum and at or below its maximum, and — because the mammogram measure is sex-specific — when, for `BCS_MAMMOGRAM` only, the patient's `sex` is `F`. The `eligible` flag is set accordingly; a measure created for a patient outside the eligible population is recorded with `eligible` false and is excluded from rate computation.

A measure can be marked `EXCLUDED` by a `QualityAnalyst`, moving its `status` to `EXCLUDED` and removing it from the denominator of any compliance rate. Exclusion is reachable from any status other than `EXCLUDED` itself — that is, from `GAP` or `NUMERATOR_COMPLIANT` — and an attempt to exclude a measure that is already `EXCLUDED` is rejected with `ERR_INVALID_STATE`. Excluding a measure recomputes the owning patient's `open_care_gaps` and increments the measure's `version` by 1.

The compliance rate is a computed read available to a `QualityAnalyst` for a given `measure_type`, `measurement_year`, and `method`. The denominator is the count of measures of that type and year that are eligible and not excluded. The numerator depends on method. Under `ADMINISTRATIVE`, the numerator counts only those measures whose status is `NUMERATOR_COMPLIANT`. Under `HYBRID`, the numerator additionally counts measures that are still in `GAP` status but whose `chart_confirmed` is true, so hybrid yields a rate at least as high as administrative on identical data. The rate itself is a percentage: when the denominator is zero the rate is the integer 0; otherwise it is the numerator multiplied by 10000, divided by the denominator, rounded half up to a whole number, and then divided by 100 to give a percentage carried to two decimal places. The computed read returns `measure_type`, `measurement_year`, and `method` echoed back alongside the integer `numerator`, the integer `denominator`, and the `rate_pct` percentage.

### 3.11. The Logical Clock

Because authorization windows, no-show timing, and vaccine spacing all depend on the passage of time, the system exposes a test-driving capability that sets the server's logical clock to a supplied instant. The request carries a `to_iso8601` field naming the instant to which the clock should be set, and the operation returns the new `current_utc`. All temporal comparisons in the system — referral expiry, the no-show end-time gate, and vaccine-interval spacing — read this logical clock rather than wall-clock time.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including every state transition, payment recording, panel binding, and measure exclusion — return `200 OK`. The request and response bodies for each endpoint are described in the Section 3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/providers` | Register a provider | FrontDesk |
| GET | `/providers/{id}` | Fetch a provider | FrontDesk, Provider, Biller, QualityAnalyst |
| GET | `/providers` | List providers | FrontDesk, Provider, Biller, QualityAnalyst |
| POST | `/providers/{id}/deactivate` | Deactivate a provider; unbinds its panel | FrontDesk |
| POST | `/providers/{id}/panel` | Bind a patient to this provider as PCP | FrontDesk |
| GET | `/providers/{id}/patients` | List patients on this provider's panel | FrontDesk, Provider, QualityAnalyst |
| GET | `/providers/{id}/referrals` | List referrals referred by this provider | FrontDesk, Provider |
| POST | `/patients` | Register a patient | FrontDesk |
| GET | `/patients/{id}` | Fetch a patient | FrontDesk, Provider, Biller, QualityAnalyst, Patient |
| GET | `/patients` | List patients | FrontDesk, Provider, Biller, QualityAnalyst |
| POST | `/patients/{id}/deactivate` | Deactivate a patient | FrontDesk |
| POST | `/patients/{id}/payments` | Record a payment against the patient ledger | Biller |
| GET | `/patients/{id}/visits` | List visits for a patient | FrontDesk, Provider, Biller, Patient |
| GET | `/patients/{id}/prescriptions` | List prescriptions for a patient | FrontDesk, Provider, Patient |
| GET | `/patients/{id}/referrals` | List referrals for a patient | FrontDesk, Provider, Patient |
| GET | `/patients/{id}/hedis-measures` | List HEDIS measures for a patient | QualityAnalyst, Provider, FrontDesk |
| GET | `/patients/{id}/portal-account` | Fetch the patient's portal account; returned as a paginated `array`-type envelope (`response_type` "array" with the pagination `meta` fields) containing the patient's zero or one portal-account objects, not a single `object` envelope | FrontDesk, Patient |
| POST | `/cpt-codes` | Create a CPT/HCPCS billing code | Biller |
| GET | `/cpt-codes/{id}` | Fetch a CPT code by its server id | Biller, Provider, FrontDesk |
| GET | `/cpt-codes` | List CPT codes | Biller, Provider, FrontDesk |
| POST | `/visits` | Schedule a visit | FrontDesk |
| GET | `/visits/{id}` | Fetch a visit | FrontDesk, Provider, Biller, Patient |
| GET | `/visits` | List visits | FrontDesk, Provider, Biller |
| POST | `/visits/{id}/charge-lines` | Add a charge line to a visit | Provider |
| GET | `/visits/{id}/charge-lines` | List charge lines for a visit | Provider, Biller, FrontDesk |
| POST | `/visits/{id}/check-in` | Check a patient in | FrontDesk |
| POST | `/visits/{id}/start` | Begin the encounter | Provider |
| POST | `/visits/{id}/code` | Code the visit; writes provisional total | Provider |
| POST | `/visits/{id}/reopen` | Reopen a coded visit back to IN_PROGRESS | Provider |
| POST | `/visits/{id}/finalize` | Finalize billing | Biller |
| POST | `/visits/{id}/cancel` | Cancel a scheduled visit | FrontDesk |
| POST | `/visits/{id}/no-show` | Mark a scheduled visit as no-show | FrontDesk |
| POST | `/prescriptions` | Create a prescription draft | Provider |
| GET | `/prescriptions/{id}` | Fetch a prescription | Provider, Patient, FrontDesk |
| GET | `/prescriptions` | List prescriptions | Provider, FrontDesk |
| POST | `/prescriptions/{id}/submit` | Submit a draft for signature | Provider |
| POST | `/prescriptions/{id}/revise` | Return a pending prescription to DRAFT | Provider |
| POST | `/prescriptions/{id}/sign` | Sign the prescription | Provider |
| POST | `/prescriptions/{id}/transmit` | Transmit a signed prescription | Provider |
| POST | `/prescriptions/{id}/dispense` | Mark a transmitted prescription dispensed | Provider |
| POST | `/prescriptions/{id}/void` | Void a non-terminal prescription | Provider |
| POST | `/referrals` | Create a referral request | Provider |
| GET | `/referrals/{id}` | Fetch a referral | Provider, FrontDesk, Patient |
| GET | `/referrals` | List referrals | Provider, FrontDesk |
| POST | `/referrals/{id}/authorize` | Authorize a referral; sets expiry | FrontDesk |
| POST | `/referrals/{id}/deny` | Deny a requested referral | FrontDesk |
| POST | `/referrals/{id}/schedule` | Schedule an authorized referral | FrontDesk |
| POST | `/referrals/{id}/expire` | Expire an authorized referral past its window | FrontDesk |
| POST | `/referrals/{id}/complete` | Complete a scheduled referral | FrontDesk |
| POST | `/referrals/{id}/cancel` | Cancel a referral | Provider |
| POST | `/portal-accounts` | Invite a patient to the portal | FrontDesk |
| GET | `/portal-accounts/{id}` | Fetch a portal account | FrontDesk, Patient |
| POST | `/portal-accounts/{id}/activate` | Activate via token | Patient |
| POST | `/portal-accounts/{id}/suspend` | Suspend an active portal account | FrontDesk |
| POST | `/portal-accounts/{id}/reinstate` | Reinstate a suspended portal account | FrontDesk |
| POST | `/portal-accounts/{id}/deactivate` | Permanently deactivate a portal account | FrontDesk |
| POST | `/hedis-measures` | Create a HEDIS measure for a patient | QualityAnalyst |
| GET | `/hedis-measures/{id}` | Fetch a HEDIS measure | QualityAnalyst, Provider, FrontDesk |
| POST | `/hedis-measures/{id}/exclude` | Mark a measure EXCLUDED | QualityAnalyst |
| GET | `/hedis/rate` | Compliance rate over the eligible population | QualityAnalyst |
| POST | `/_clock/set_current_utc` | Set the server clock for temporal logic | FrontDesk, QualityAnalyst, Biller, Provider |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EPCS_REQUIREMENTS_NOT_MET` | 422 |
| `ERR_VACCINE_INTERVAL_VIOLATION` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_NO_PCP_BOUND` | 409 |
| `ERR_PANEL_AT_CAPACITY` | 409 |
| `ERR_REFERRAL_EXPIRED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PATIENT_HAS_OPEN_VISITS` | 409 |
| `ERR_DUPLICATE_PORTAL_ACCOUNT` | 409 |
| `ERR_DUPLICATE_NPI` | 409 |
| `ERR_DUPLICATE_CPT_CODE` | 409 |
</content>
</invoke>
